"""Application configuration.

Loads settings from ``config.yaml`` and overrides them with environment
variables (from the process environment or a local ``.env`` file).
"""
from __future__ import annotations

# Schema version used by the lightweight storage migration.
SCHEMA_VERSION = 3

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class OCRConfig:
    engine: str = "tesseract"
    language: str = "ind+eng"
    dpi: int = 300
    deskew: bool = True
    denoise: bool = True
    binarize: bool = True
    cache: bool = True
    tesseract_cmd: str | None = None
    # Dedicated scratch dir for tesseract's per-page PNG/TSV files. pytesseract
    # writes them into tempfile.gettempdir() and, after every single call,
    # re-enumerates that whole directory to glob "tess*" leftovers. Sharing one
    # system temp dir across 10 workers makes every OCR page a full directory
    # scan of a busy %TEMP% (hundreds of entries, constantly rescanned by
    # Defender), which is what wedged the batch at 100% CPU and 0 bytes I/O.
    temp_dir: str = "./data/tmp/tesseract"
    # Language packs. Point this at a writable directory holding every
    # *.traineddata you need: the tesseract install dir is usually under
    # Program Files and cannot be written without admin. Empty = use the
    # tesseract install's own tessdata directory.
    tessdata_dir: str = "./data/tessdata"
    # Cap on simultaneous tesseract processes. Each one is internally
    # multi-threaded, so running one per worker oversubscribes the CPU and
    # multiplies temp-file churn for no throughput gain.
    max_concurrent: int = 4
    # image_to_osd() costs a second tesseract process (and a second temp PNG)
    # per page. Off by default: --psm 6 tolerates the small skews that appear in
    # these scans, and deskew() already handles the rest.
    detect_orientation: bool = False


@dataclass
class AIConfig:
    provider: str = "none"
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: int = 4000
    cache: bool = True
    api_key: str | None = None
    base_url: str | None = None
    relevant_page_strategy: str = "keyword"


@dataclass
class ConfidenceConfig:
    # Mirrors the page-authority scale in `pipeline.processor.page_confidence`
    # (1.0 primary statement page, 0.9 header-zipped, 0.75 indirect). `high` and
    # `medium` label those tiers; they are not further gradations.
    high: float = 0.90
    medium: float = 0.75
    # Below this -> REVIEW_REQUIRED (never ERROR). Set above the indirect tier so
    # a figure read off a notes or unsectioned page is actually flagged. At the
    # old 0.50 nothing could ever fall below it, because label matching was the
    # only thing that moved the number and it now always resolves to 1.0.
    review_threshold: float = 0.85


@dataclass
class ValidationConfig:
    tolerance: float = 0.01                    # legacy relative tolerance
    absolute_tolerance: float = 1_000.0        # e.g. 1000 IDR
    relative_tolerance: float = 0.001          # 0.1 %
    # Rule severities (requirement #25) — configurable, not hardcoded.
    missing_fields_severity: str = "info"
    unmapped_fields_severity: str = "info"
    low_confidence_severity: str = "warning"
    incomplete_statement_severity: str = "info"
    accounting_mismatch_severity: str = "error"
    rounding_difference_severity: str = "warning"
    enabled: bool = True


PROCESSING_MODES = ("fast", "balanced", "accurate")


@dataclass
class ProcessingConfig:
    workers: int = 4
    ocr_workers: int = 2
    max_pages_per_document: int = 0
    raw_data_directory: str = "./data"
    mode: str = "balanced"
    max_ai_concurrent_requests: int = 2
    # Per-page OCR decision threshold (chars of text layer below this => OCR)
    text_char_threshold: int = 100
    # Relevance score a page must reach before expensive processing
    min_financial_page_score: int = 3
    table_max_pages: int = 60                  # cap pages sent to pdfplumber per doc


@dataclass
class AppConfig:
    input_directory: Path = PROJECT_ROOT / "XBRL"
    output_directory: Path = PROJECT_ROOT / "output"
    database_url: str = "sqlite:///./database/processing.db"
    language: str = "id+en"
    ocr: OCRConfig = field(default_factory=OCRConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    send_to_external_ai: bool = False
    project_root: Path = PROJECT_ROOT

    # ---- derived paths -------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return (PROJECT_ROOT / self.processing.raw_data_directory).resolve()

    @property
    def database_path(self) -> Path:
        raw = self.database_url
        if raw.startswith("sqlite:///"):
            p = Path(raw.replace("sqlite:///", "", 1))
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            return p
        return PROJECT_ROOT / "database" / "processing.db"

    @property
    def review_dir(self) -> Path:
        return self.output_directory / "review"

    @property
    def logs_dir(self) -> Path:
        return PROJECT_ROOT / "logs"

    @property
    def ocr_temp_dir(self) -> Path:
        """Absolute scratch dir handed to tesseract for page images/TSV files."""
        raw = Path(self.ocr.temp_dir)
        return raw if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()

    @property
    def ocr_tessdata_dir(self) -> Path | None:
        """Absolute language-pack dir, or None to use the install's own."""
        raw = (self.ocr.tessdata_dir or "").strip()
        if not raw:
            return None
        p = Path(raw)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _deep_get(d: dict[str, Any], key: str, default: Any = None) -> Any:
    return d.get(key, default) if isinstance(d, dict) else default


def _autodetect_tesseract() -> str | None:
    """Find tesseract.exe in common Windows install locations."""
    import shutil

    if shutil.which("tesseract"):
        return None  # already on PATH
    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        Path("/usr/bin/tesseract"),
        Path("/opt/homebrew/bin/tesseract"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration, applying .env overrides."""
    load_dotenv(PROJECT_ROOT / ".env")

    cfg = AppConfig()
    path = config_path or PROJECT_ROOT / "config.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        cfg.input_directory = Path(
            os.getenv("INPUT_DIRECTORY", data.get("input_directory", cfg.input_directory))
        )
        cfg.output_directory = Path(
            os.getenv("OUTPUT_DIRECTORY", data.get("output_directory", cfg.output_directory))
        )
        if not cfg.input_directory.is_absolute():
            cfg.input_directory = (PROJECT_ROOT / cfg.input_directory).resolve()
        if not cfg.output_directory.is_absolute():
            cfg.output_directory = (PROJECT_ROOT / cfg.output_directory).resolve()
        cfg.database_url = os.getenv("DATABASE_URL", data.get("database_url", cfg.database_url))
        cfg.language = os.getenv("LANGUAGE", data.get("language", cfg.language))
        cfg.send_to_external_ai = os.getenv(
            "SEND_TO_EXTERNAL_AI", str(data.get("send_to_external_ai", False))
        ).lower() in ("1", "true", "yes")

        proc = _deep_get(data, "processing", {}) or {}
        cfg.processing.workers = int(os.getenv("WORKERS", proc.get("workers", cfg.processing.workers)))
        cfg.processing.ocr_workers = int(
            os.getenv("OCR_WORKERS", proc.get("ocr_workers", cfg.processing.ocr_workers))
        )
        cfg.processing.max_pages_per_document = int(proc.get("max_pages_per_document", 0))
        cfg.processing.raw_data_directory = proc.get("raw_data_directory", "./data")

        ocr = _deep_get(data, "ocr", {}) or {}
        cfg.ocr.engine = os.getenv("OCR_ENGINE", ocr.get("engine", cfg.ocr.engine))
        cfg.ocr.language = os.getenv("OCR_LANGUAGE", ocr.get("language", cfg.ocr.language))
        cfg.ocr.dpi = int(ocr.get("dpi", cfg.ocr.dpi))
        cfg.ocr.tesseract_cmd = os.getenv("TESSERACT_CMD") or _autodetect_tesseract()
        pre = ocr.get("preprocess", {}) or {}
        cfg.ocr.deskew = bool(pre.get("deskew", True))
        cfg.ocr.denoise = bool(pre.get("denoise", True))
        cfg.ocr.binarize = bool(pre.get("binarize", True))
        cfg.ocr.cache = bool(ocr.get("cache", True))
        cfg.ocr.temp_dir = os.getenv("OCR_TEMP_DIR", ocr.get("temp_dir", cfg.ocr.temp_dir))
        cfg.ocr.tessdata_dir = os.getenv(
            "OCR_TESSDATA_DIR", ocr.get("tessdata_dir", cfg.ocr.tessdata_dir)
        )
        cfg.ocr.max_concurrent = int(
            os.getenv("OCR_MAX_CONCURRENT", ocr.get("max_concurrent", cfg.ocr.max_concurrent))
        )
        cfg.ocr.detect_orientation = bool(
            ocr.get("detect_orientation", cfg.ocr.detect_orientation)
        )

        ai = _deep_get(data, "ai", {}) or {}
        cfg.ai.provider = os.getenv("AI_PROVIDER", ai.get("provider", cfg.ai.provider)).lower()
        cfg.ai.model = os.getenv("AI_MODEL", ai.get("model", cfg.ai.model))
        cfg.ai.temperature = float(ai.get("temperature", cfg.ai.temperature))
        cfg.ai.max_tokens = int(ai.get("max_tokens", cfg.ai.max_tokens))
        cfg.ai.cache = bool(ai.get("cache", True))
        cfg.ai.api_key = os.getenv("OPENAI_API_KEY")
        cfg.ai.base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OLLAMA_BASE_URL")
        cfg.ai.relevant_page_strategy = ai.get("relevant_page_strategy", "keyword")

        conf = _deep_get(data, "confidence", {}) or {}
        cfg.confidence.high = float(os.getenv("CONFIDENCE_HIGH", conf.get("high", 0.90)))
        cfg.confidence.medium = float(os.getenv("CONFIDENCE_MEDIUM", conf.get("medium", 0.75)))
        cfg.confidence.review_threshold = float(
            os.getenv("CONFIDENCE_REVIEW", conf.get("review_threshold", 0.50)))

        val = _deep_get(data, "validation", {}) or {}
        cfg.validation.tolerance = float(os.getenv("VALIDATION_TOLERANCE", val.get("tolerance", 0.01)))
        cfg.validation.absolute_tolerance = float(
            os.getenv("VALIDATION_ABSOLUTE_TOLERANCE", val.get("absolute_tolerance", 1_000.0))
        )
        cfg.validation.relative_tolerance = float(
            os.getenv("VALIDATION_RELATIVE_TOLERANCE", val.get("relative_tolerance", 0.001))
        )
        cfg.validation.enabled = bool(val.get("enabled", True))
        rules = val.get("rules", {}) or {}
        cfg.validation.missing_fields_severity = rules.get("missing_fields", {}).get("severity", "info")
        cfg.validation.unmapped_fields_severity = rules.get("unmapped_fields", {}).get("severity", "info")
        cfg.validation.low_confidence_severity = rules.get("low_confidence", {}).get("severity", "warning")
        cfg.validation.incomplete_statement_severity = rules.get("incomplete_statement", {}).get("severity", "info")
        cfg.validation.accounting_mismatch_severity = rules.get("accounting_mismatch", {}).get("severity", "error")
        cfg.validation.rounding_difference_severity = rules.get("rounding_difference", {}).get("severity", "warning")

        mode = os.getenv("PROCESSING_MODE", _deep_get(data, "processing", {}).get("mode", "balanced"))
        if mode in PROCESSING_MODES:
            cfg.processing.mode = mode
        cfg.processing.max_ai_concurrent_requests = int(
            os.getenv("MAX_AI_CONCURRENT_REQUESTS",
                      _deep_get(data, "processing", {}).get("max_ai_concurrent_requests", 2))
        )
        _apply_mode(cfg)

    return cfg


def _apply_mode(cfg: AppConfig) -> None:
    """Tune pipeline knobs per processing mode (fast / balanced / accurate)."""
    if cfg.processing.mode == "fast":
        cfg.ocr.deskew = False
        cfg.ocr.denoise = False
        cfg.ocr.binarize = False
        cfg.ocr.dpi = min(cfg.ocr.dpi, 200)
        cfg.processing.min_financial_page_score = 5
        cfg.processing.table_max_pages = 30
        cfg.ai.max_tokens = min(cfg.ai.max_tokens, 3000)
    elif cfg.processing.mode == "accurate":
        cfg.ocr.deskew = True
        cfg.ocr.denoise = True
        cfg.ocr.binarize = True
        cfg.ocr.dpi = max(cfg.ocr.dpi, 300)
        cfg.processing.min_financial_page_score = 2
        cfg.processing.table_max_pages = 120
    # balanced: leave config as-is


# Singleton-style accessor
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: AppConfig) -> None:
    global _config
    _config = cfg
