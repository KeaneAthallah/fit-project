"""OCR pipeline for scanned pages.

Performance design:
    - Single tesseract pass: word confidences are derived from the same
      ``image_to_data`` call that produces the text (previously the page was
      OCR'd twice — once for data, once for the string).
    - Adaptive preprocessing: image quality (blur/contrast estimate) decides
      whether deskew/denoise/binarize run; clean scans skip the expensive CV.
    - Page-level disk cache: ``cache/ocr/<pdf-hash>/<page>.txt`` keyed by the
      PDF hash + page number + engine settings, so reprocessing the same PDF
      never re-OCRs (requirement #18).
    - Private temp dir + bounded tesseract concurrency: pytesseract writes a
      PNG per page into ``tempfile.gettempdir()`` and re-enumerates that whole
      directory (``glob("tess*")``) after every call. Sharing the system
      ``%TEMP%`` across the worker pool turned each OCR page into a full
      directory scan of a busy folder that Defender rescans, which stalled a
      10-worker batch at 100% CPU with zero I/O. See ``_use_dedicated_temp_dir``.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract
import pymupdf
from pytesseract import Output

from app.core.config import PROJECT_ROOT, OCRConfig
from app.core.exceptions import OCRError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OCRPageResult:
    page_number: int
    text: str
    confidence: float        # mean word confidence 0..100
    engine: str
    processing_time: float
    image_path: str | None = None
    cached: bool = False
    preprocessing: str = "none"


def configure_tesseract(cfg: OCRConfig) -> None:
    if cfg.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd


_temp_lock = threading.Lock()
_temp_dir_ready: Path | None = None
_tessdata_ready: Path | None = None

_slot_lock = threading.Lock()
_slots: threading.Semaphore | None = None
_slots_limit = -1

_languages_lock = threading.Lock()
_languages: dict[str, str] = {}


def _use_tessdata_dir(cfg: OCRConfig) -> None:
    """Point tesseract at a writable directory of language packs.

    The install lives under Program Files, so adding a language pack normally
    needs admin. ``TESSDATA_PREFIX`` overrides the search path for every
    tesseract invocation (including ``--list-langs``) without argv quoting
    hazards, which matters because the path can contain spaces. The directory
    replaces the default one, so it must hold every language in use.
    """
    global _tessdata_ready
    if _tessdata_ready is not None:
        return
    raw = (cfg.tessdata_dir or "").strip()
    if not raw:
        return  # explicit opt-out: use the install's own tessdata
    with _temp_lock:
        if _tessdata_ready is not None:
            return
        target = Path(raw)
        if not target.is_absolute():
            target = (PROJECT_ROOT / target).resolve()
        if not target.is_dir():
            logger.warning(
                "OCR tessdata dir %s does not exist — using the tesseract "
                "install's language packs instead. Language packs present: %s",
                target, _installed_languages() or "none detected",
            )
            return
        packs = sorted(p.stem for p in target.glob("*.traineddata"))
        if not packs:
            logger.warning("OCR tessdata dir %s contains no *.traineddata", target)
            return
        os.environ["TESSDATA_PREFIX"] = str(target)
        _tessdata_ready = target
        logger.info("Tesseract language packs: %s (%s)", target, ", ".join(packs))


def _use_dedicated_temp_dir(cfg: OCRConfig) -> None:
    """Redirect pytesseract's scratch files to a private directory.

    ``pytesseract.save()`` writes ``tess_*.PNG`` into ``tempfile.gettempdir()``
    and ``cleanup()`` then globs ``tess*`` in that directory after every single
    call. On Windows the glob starts with a full ``os.scandir`` of the parent
    directory, so with N workers each OCR page costs one directory enumeration
    of the shared system ``%TEMP%``. That directory is also where Defender
    queues its scans of every freshly written file. Result: workers block
    indefinitely in ``scandir`` and the batch wedges.

    Repointing ``tempfile.tempdir`` at a small dedicated folder keeps the scan
    bounded and keeps the traffic away from unrelated applications' temp files.
    Add the folder to the Defender exclusion list (see README) to also skip the
    real-time scan of each page image.
    """
    global _temp_dir_ready
    if _temp_dir_ready is not None:
        return
    with _temp_lock:
        if _temp_dir_ready is not None:
            return
        raw = Path(cfg.temp_dir)
        target = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
        try:
            target.mkdir(parents=True, exist_ok=True)
            # Drop leftovers from a previously killed run so the directory that
            # gets globbed stays tiny.
            for stale in target.glob("tess*"):
                try:
                    stale.unlink()
                except OSError:
                    pass
            tempfile.tempdir = str(target)
            # Older pytesseract releases captured the temp dir at import time.
            if hasattr(pytesseract.pytesseract, "DATADIR"):
                pytesseract.pytesseract.DATADIR = str(target)
            _temp_dir_ready = target
            logger.info("Tesseract temp directory: %s", target)
        except OSError as exc:
            # Never let scratch-dir setup break OCR: fall back to the default
            # temp dir and say so loudly.
            logger.warning("Could not use OCR temp dir %s (%s) — falling back "
                           "to the system temp dir", target, exc)


def tesseract_slot(limit: int) -> threading.Semaphore:
    """Semaphore bounding simultaneous tesseract processes.

    Tesseract is internally multi-threaded, so one process per worker both
    oversubscribes the CPU and multiplies temp-file churn for no extra
    throughput. The limiter is shared by all workers and rebuilt only when the
    configured limit changes.
    """
    global _slots, _slots_limit
    limit = max(1, limit)
    with _slot_lock:
        if _slots is None or _slots_limit != limit:
            _slots = threading.Semaphore(limit)
            _slots_limit = limit
        return _slots


def resolve_language(lang: str) -> str:
    """Drop languages this tesseract install has no traineddata for.

    ``language: "ind+eng"`` against an install that only ships
    ``eng.traineddata`` fails every page with ``Failed loading language 'ind'``,
    burning three retries before the page is dropped. Keep the languages that
    are actually installed and say which ones are missing.
    """
    if not lang or lang in _languages:
        return _languages.get(lang, lang)
    wanted = [p for p in lang.split("+") if p]
    # Double-checked: get_languages() shells out to tesseract, and without the
    # lock every worker starting at once runs it (and logs) in parallel.
    with _languages_lock:
        if lang in _languages:
            return _languages[lang]
        available = _installed_languages()
        keep = [p for p in wanted if p in available]
        if not keep:
            keep = ["eng"] if "eng" in available else ([sorted(available)[0]]
                                                       if available else wanted)
        if keep != wanted:
            missing = [p for p in wanted if p not in available]
            logger.warning(
                "OCR language %s unavailable (missing traineddata: %s) — using %s. "
                "Install the language packs, e.g. copy ind.traineddata into the "
                "tesseract tessdata directory.",
                lang, ", ".join(missing) or "none", "+".join(keep),
            )
        resolved = "+".join(keep)
        _languages[lang] = resolved
        return resolved


def _installed_languages() -> set[str]:
    """Languages this tesseract build has traineddata for; empty if unknown."""
    try:
        return set(pytesseract.get_languages())
    except Exception:
        logger.debug("Could not list tesseract languages", exc_info=True)
        return set()


def render_page(page: pymupdf.Page, dpi: int) -> np.ndarray:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def image_quality(image: np.ndarray) -> float:
    """Estimate readability: combine sharpness (variance of Laplacian) and contrast."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    contrast = float(np.std(gray))
    # Normalize both to a rough 0..1 score.
    s = min(sharpness / 500.0, 1.0)
    c = min(contrast / 60.0, 1.0)
    return 0.6 * s + 0.4 * c


def deskew(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inverted > 0))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    if abs(angle) < 0.3 or abs(angle) > 15:
        return image
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def denoise(image: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)


def binarize(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def enhance_contrast(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)


def _fix_orientation(image: np.ndarray, lang: str, slots: threading.Semaphore) -> np.ndarray:
    try:
        with slots:
            osd = pytesseract.image_to_osd(image, lang=lang[:2] if lang else "en")
        rotate = int(osd.split("Rotate:")[1].split("\n")[0])
        if rotate in (90, 180, 270):
            image = np.rot90(image, k=rotate // 90).copy()
    except Exception:
        pass  # OSD can fail on sparse pages; leave image as-is
    return image


def _cache_path(
    cache_dir: Path | None,
    pdf_hash: str,
    page_number: int,
    cfg: OCRConfig,
    lang: str = "",
) -> Path | None:
    """Cache key includes the *resolved* language.

    resolve_language() can silently downgrade e.g. "ind+eng" to "eng" when a
    pack is missing, and results from different packs are not interchangeable —
    keying on the configured string alone would reuse pre-downgrade output after
    the pack is installed.
    """
    if cache_dir is None or not pdf_hash:
        return None
    key = hashlib.sha256(
        f"{pdf_hash}|{page_number}|{lang or cfg.language}|{cfg.dpi}|{cfg.deskew}"
        f"|{cfg.denoise}|{cfg.binarize}|{cfg.detect_orientation}".encode()
    ).hexdigest()[:32]
    return cache_dir / pdf_hash[:16] / f"page_{page_number:04d}_{key}.txt"


def ocr_page(
    page: pymupdf.Page,
    cfg: OCRConfig,
    page_number: int,
    save_image_dir: Path | None = None,
    cache_dir: Path | None = None,
    pdf_hash: str = "",
) -> OCRPageResult:
    """Render + (adaptive) preprocess + OCR a single PDF page.

    Results are cached on disk per (pdf hash, page, settings). The cache is
    checked before any rendering/OCR work is done.
    """
    _use_dedicated_temp_dir(cfg)
    _use_tessdata_dir(cfg)
    configure_tesseract(cfg)
    slots = tesseract_slot(cfg.max_concurrent)
    lang = resolve_language(cfg.language)
    start = time.time()

    cpath = _cache_path(cache_dir, pdf_hash, page_number, cfg, lang)
    if cpath is not None and cpath.exists():
        try:
            text = cpath.read_text(encoding="utf-8")
            header, _, body = text.partition("\n")
            # header: conf<TAB>engine<TAB>preprocessing
            try:
                conf_s, engine, prep = header.split("\t")
                conf = float(conf_s)
            except ValueError:
                conf, engine, prep = 0.5, "tesseract", "cached-legacy"
            return OCRPageResult(
                page_number=page_number,
                text=body,
                confidence=conf,
                engine=engine,
                processing_time=time.time() - start,
                image_path=None,
                cached=True,
                preprocessing=prep,
            )
        except Exception:
            pass  # corrupted cache entry -> recompute

    try:
        image = render_page(page, cfg.dpi)
        if save_image_dir is not None:
            save_image_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(save_image_dir / f"page_{page_number:04d}.png"), image)

        # Adaptive preprocessing: only degrade to expensive CV when the image
        # quality score suggests the scan needs it (requirement #21).
        quality = image_quality(image)
        applied: list[str] = []

        if quality < 0.35:
            # Poor scan: full pipeline
            if cfg.deskew:
                image = deskew(image)
                applied.append("deskew")
            if cfg.denoise:
                image = denoise(image)
                applied.append("denoise")
            image = enhance_contrast(image)
            applied.append("contrast")
            if cfg.binarize:
                image = binarize(image)
                applied.append("binarize")
        elif quality < 0.7:
            # Mediocre scan: light pipeline (deskew + contrast only)
            if cfg.deskew:
                image = deskew(image)
                applied.append("deskew")
            image = enhance_contrast(image)
            applied.append("contrast")
        # else: clean scan, OCR the raw render directly

        if cfg.detect_orientation:
            image = _fix_orientation(image, lang, slots)

        data = _tesseract_with_retry(image, lang, slots)
        words: list[str] = []
        confs: list[float] = []
        for txt, conf in zip(data["text"], data["conf"]):
            t = str(txt).strip()
            if not t or conf == "-1":
                continue
            words.append(t)
            confs.append(float(conf))
        # Rebuild text from word data instead of a second image_to_string pass.
        text = _words_to_text(data)
        mean_conf = float(np.mean(confs)) if confs else 0.0
        elapsed = time.time() - start
        prep = "+".join(applied) if applied else "none"

        if cpath is not None:
            try:
                cpath.parent.mkdir(parents=True, exist_ok=True)
                cpath.write_text(f"{mean_conf / 100.0:.4f}\ttesseract\t{prep}\n{text}", encoding="utf-8")
            except Exception:
                pass

        return OCRPageResult(
            page_number=page_number,
            text=text.strip(),
            confidence=mean_conf / 100.0,
            engine="tesseract",
            processing_time=elapsed,
            image_path=str(save_image_dir / f"page_{page_number:04d}.png") if save_image_dir else None,
            cached=False,
            preprocessing=prep,
        )
    except Exception as exc:
        raise OCRError(f"OCR failed on page {page_number}: {exc}") from exc


def _tesseract_with_retry(image, lang: str,
                          slots: threading.Semaphore, attempts: int = 3) -> dict:
    """pytesseract call with retry for transient Windows file-lock errors.

    Seen in production: ``(3221225786, 'Error opening data file ...')`` —
    antivirus briefly locks ``tessdata`` while several workers open it. A
    short backoff retry resolves it; without this, one transient error
    failed the whole page.

    The slot is acquired per attempt, never held across the backoff sleep.
    """
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            with slots:
                return pytesseract.image_to_data(
                    image, lang=lang, output_type=Output.DICT, config="--psm 6"
                )
        except Exception as exc:
            if attempt == attempts:
                raise
            logger.warning("Tesseract attempt %d/%d failed (%s) — retrying in %.1fs",
                           attempt, attempts, exc, delay)
            time.sleep(delay)
            delay *= 2
    raise OCRError("unreachable")  # pragma: no cover


def _words_to_text(data: dict) -> str:
    """Reconstruct page text from tesseract word boxes (single-pass OCR)."""
    lines: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for i, txt in enumerate(data["text"]):
        t = str(txt).strip()
        if not t:
            continue
        key = (data["block_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((data["word_num"][i], t))
    out_lines = []
    for key in sorted(lines):
        ws = sorted(lines[key])
        out_lines.append(" ".join(t for _, t in ws))
    return "\n".join(out_lines)
