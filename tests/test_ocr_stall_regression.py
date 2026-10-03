"""Regression tests for the worker-pool stall and the OCR table regex.

A batch once wedged with every worker blocked in ``pytesseract.cleanup()``
(scanning the shared system %TEMP% directory) while one core was pinned by a
catastrophically backtracking row regex. These tests keep both fixed.
"""
import os
import re
import shutil
import tempfile
import threading
import time

import pytest
from pathlib import Path

from app.core.config import OCRConfig
from app.extraction import ocr as ocr_mod
from app.extraction.ocr import _cache_path, resolve_language, tesseract_slot
from app.extraction.table_extractor import _OCR_ROW_RE, parse_ocr_table_text

# The pattern this replaced, kept verbatim so the two can be compared.
_LEGACY_ROW_RE = re.compile(
    r"^(.*?)[\s\.\u2026]+((?:[-–(]?\s*(?:Rp\s*)?[\d.,]+\)?[\s]*)+)$"
)


class TestOCRRowRegex:
    @pytest.mark.parametrize("line", [
        "Total aset            12,345,678   11,222,333",
        "Pendapatan            Rp 1.234.567  999.888",
        "Laba bersih           (520.193)  410.221",
        "Jumlah  1.234  (56)  78,9",
        "Net income      1 2 3",
        "EBITDA  (1.000)  2.000  -3.000",
        "Nilai 1.234,5",
        "Diskon  (1.000)",
    ])
    def test_matches_legacy(self, line):
        assert _OCR_ROW_RE.match(line).groups() == _LEGACY_ROW_RE.match(line).groups()

    @pytest.mark.parametrize("line", [
        "Total aset",
        "Some narrative line with no numbers",
        "Pendapatan neto  5%  7%",
        "   ",
    ])
    def test_rejects_same_as_legacy(self, line):
        assert _OCR_ROW_RE.match(line) is None
        assert _LEGACY_ROW_RE.match(line) is None

    def test_linear_on_non_matching_line(self):
        """The old pattern took exponential time to reject this shape."""
        line = "9 " * 200 + "x"
        start = time.perf_counter()
        _OCR_ROW_RE.match(line)
        assert time.perf_counter() - start < 1.0

    def test_parses_identically_to_legacy(self, monkeypatch):
        """Whole-function equivalence, not just per-line regex equivalence."""
        from app.extraction import table_extractor

        text = "\n".join([
            "LAPORAN POSISI KEUANGAN 31 Desember 2024",
            "Total aset             12,345,678   11,222,333",
            "Liabilitas             (1.000)     (2.000)",
            "Laba bersih            4.500  3.900  12,5%",
            "Keterangan ini explains 1.115",
            "Modal disetor  1.000.000.000",
            "Kas dan setara kas 9 8 7",
        ])
        expected = parse_ocr_table_text(text)
        monkeypatch.setattr(table_extractor, "_OCR_ROW_RE", _LEGACY_ROW_RE)
        legacy = parse_ocr_table_text(text)
        assert ([(c.row_label, c.values) for c in expected.rows]
                == [(c.row_label, c.values) for c in legacy.rows])
        assert expected.header_years == legacy.header_years


class TestResolveLanguage:
    def setup_method(self):
        ocr_mod._languages.clear()

    def test_drops_uninstalled_language(self, monkeypatch):
        monkeypatch.setattr(ocr_mod, "_installed_languages", lambda: {"eng", "osd"})
        assert resolve_language("ind+eng") == "eng"

    def test_keeps_installed_languages(self, monkeypatch):
        monkeypatch.setattr(ocr_mod, "_installed_languages", lambda: {"ind", "eng"})
        assert resolve_language("ind+eng") == "ind+eng"

    def test_falls_back_when_none_requested_is_installed(self, monkeypatch):
        monkeypatch.setattr(ocr_mod, "_installed_languages", lambda: {"eng", "jpn"})
        assert resolve_language("ind") == "eng"

    def test_listing_happens_once(self, monkeypatch):
        calls = []

        def fake():
            calls.append(1)
            return {"eng"}

        monkeypatch.setattr(ocr_mod, "_installed_languages", fake)
        assert resolve_language("ind") == "eng"
        assert resolve_language("ind") == "eng"
        assert len(calls) == 1


class TestTesseractSlot:
    def test_reused_while_limit_is_unchanged(self):
        assert tesseract_slot(2) is tesseract_slot(2)

    def test_rebuilt_when_limit_changes(self):
        assert tesseract_slot(2) is not tesseract_slot(5)

    def test_limit_is_honoured(self):
        slot = tesseract_slot(3)
        acquired = [slot.acquire(blocking=False) for _ in range(3)]
        assert all(acquired)
        assert slot.acquire(blocking=False) is False
        for _ in range(3):
            slot.release()

    def test_zero_is_clamped_to_one(self):
        slot = tesseract_slot(0)
        assert slot.acquire(blocking=False) is True
        assert slot.acquire(blocking=False) is False
        slot.release()


class TestTessdataDir:
    def setup_method(self):
        self.packs = tempfile.mkdtemp(prefix="_fitri_tessdata_")
        self.prev_prefix = os.environ.get("TESSDATA_PREFIX")
        ocr_mod._tessdata_ready = None

    def teardown_method(self):
        if self.prev_prefix is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = self.prev_prefix
        ocr_mod._tessdata_ready = None
        shutil.rmtree(self.packs, ignore_errors=True)

    def _pack(self, name):
        path = os.path.join(self.packs, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        return path

    def test_sets_tessdata_prefix(self):
        self._pack("eng.traineddata")
        self._pack("ind.traineddata")

        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir=self.packs))

        assert os.environ["TESSDATA_PREFIX"] == self.packs
        assert ocr_mod._tessdata_ready == Path(self.packs)

    def test_relative_path_resolves_against_project_root(self):
        self._pack("eng.traineddata")

        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir="./data/tessdata"))

        assert ocr_mod._tessdata_ready == (ocr_mod.PROJECT_ROOT / "data" / "tessdata").resolve()

    def test_empty_config_leaves_environment_untouched(self):
        self._pack("eng.traineddata")

        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir=""))

        assert ocr_mod._tessdata_ready is None
        assert os.environ.get("TESSDATA_PREFIX") == self.prev_prefix

    def test_missing_dir_warns_and_keeps_install_packs(self, monkeypatch):
        warned = []
        monkeypatch.setattr(ocr_mod.logger, "warning", lambda *a, **k: warned.append(a[0]))
        monkeypatch.setattr(ocr_mod, "_installed_languages", lambda: {"eng"})

        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir=os.path.join(self.packs, "nope")))

        assert warned
        assert ocr_mod._tessdata_ready is None
        assert os.environ.get("TESSDATA_PREFIX") == self.prev_prefix

    def test_empty_dir_warns_and_keeps_install_packs(self, monkeypatch):
        warned = []
        monkeypatch.setattr(ocr_mod.logger, "warning", lambda *a, **k: warned.append(a[0]))

        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir=self.packs))

        assert warned
        assert ocr_mod._tessdata_ready is None
        assert os.environ.get("TESSDATA_PREFIX") == self.prev_prefix

    def test_second_call_is_a_no_op(self):
        self._pack("eng.traineddata")
        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir=self.packs))
        ready = ocr_mod._tessdata_ready

        ocr_mod._use_tessdata_dir(OCRConfig(tessdata_dir="/nonexistent/elsewhere"))

        assert ocr_mod._tessdata_ready == ready
        assert os.environ["TESSDATA_PREFIX"] == self.packs


class TestCacheKeyTracksResolvedLanguage:
    def test_downgraded_language_does_not_reuse_pre_downgrade_cache(self, tmp_path):
        cfg = OCRConfig()
        # Cache written while "ind" was missing, i.e. OCR actually ran as "eng".
        before = _cache_path(tmp_path, "a" * 64, 1, cfg, "eng")
        before.parent.mkdir(parents=True, exist_ok=True)
        before.write_text("0.5\ttesseract\tcached-legacy\nold text", encoding="utf-8")

        # With the pack installed the key must not match the old entry.
        after = _cache_path(tmp_path, "a" * 64, 1, cfg, "ind+eng")
        assert after != before
        assert not after.exists()

    def test_orientation_flag_changes_the_key(self, tmp_path):
        cfg = OCRConfig()
        with_osd = _cache_path(tmp_path, "b" * 64, 1, cfg, "ind+eng")
        cfg.detect_orientation = True
        without_osd = _cache_path(tmp_path, "b" * 64, 1, cfg, "ind+eng")
        assert with_osd != without_osd


class TestDedicatedTempDir:
    def setup_method(self):
        self.scratch = tempfile.gettempdir() + "_fitri_scratch_test"
        self.system_temp = tempfile.gettempdir()
        ocr_mod._temp_dir_ready = None

    def teardown_method(self):
        tempfile.tempdir = self.system_temp
        ocr_mod._temp_dir_ready = None
        shutil.rmtree(self.scratch, ignore_errors=True)

    def test_redirects_pytesseract_scratch_files(self):
        cfg = OCRConfig()
        cfg.temp_dir = self.scratch
        before = set(os.listdir(self.system_temp))

        ocr_mod._use_dedicated_temp_dir(cfg)

        assert tempfile.tempdir == self.scratch
        assert set(os.listdir(self.system_temp)) == before
        assert os.path.isdir(self.scratch)

    def test_clears_leftovers_from_a_killed_run(self):
        os.makedirs(self.scratch, exist_ok=True)
        stale = os.path.join(self.scratch, "tess_stale_input.PNG")
        with open(stale, "wb") as fh:
            fh.write(b"x")

        ocr_mod._use_dedicated_temp_dir(OCRConfig(temp_dir=self.scratch))

        assert os.listdir(self.scratch) == []

    def test_second_call_is_a_no_op(self):
        ocr_mod._use_dedicated_temp_dir(OCRConfig(temp_dir=self.scratch))
        ready = ocr_mod._temp_dir_ready
        ocr_mod._use_dedicated_temp_dir(OCRConfig(temp_dir="/nonexistent/elsewhere"))
        assert ocr_mod._temp_dir_ready == ready


def test_concurrent_ocr_pages_do_not_block_each_other():
    """The stall was workers serialising on one shared temp directory."""
    n_workers = 8
    started = threading.Barrier(n_workers, timeout=30)
    errors = []

    def worker(i):
        try:
            started.wait()
            tesseract_slot(2).acquire()
            time.sleep(0.05)
            tesseract_slot(2).release()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()
    assert errors == []
