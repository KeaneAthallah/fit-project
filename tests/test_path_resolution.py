"""Regression: the stored file_path may come from a different host.

The SQLite file is mounted into the Docker container, so paths recorded on the
Windows host (`C:\\Users\\...\\LAPORAN KEUANGAN\\...`) do not exist inside the
Linux container. Before this resolver every document failed instantly with
"File missing" and the container wrote empty CSV reports without raising.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import AppConfig  # noqa: E402
from app.pipeline.processor import resolve_document_path  # noqa: E402

# A path recorded on a DIFFERENT host: the container records /app/..., and this
# machine's own root is C:\Users\kenn\Documents\Fitri. Neither exists in the
# tmp_path fixture, which is what makes the re-rooting behaviour observable.
FOREIGN_WINDOWS = r"C:\Users\testhost\Documents\Fitri\LAPORAN KEUANGAN\ADES Akasha Wira International Tbk\2021.pdf"
FOREIGN_LINUX = "/app/LAPORAN KEUANGAN/ADES Akasha Wira International Tbk/2021.pdf"
REAL_WINDOWS = r"C:\Users\kenn\Documents\Fitri\LAPORAN KEUANGAN\ADES Akasha Wira International Tbk\2021.pdf"


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    """A fake corpus root plus a config pointing at it."""
    root = tmp_path / "LAPORAN KEUANGAN"
    target = root / "ADES Akasha Wira International Tbk"
    target.mkdir(parents=True)
    (target / "2021.pdf").write_bytes(b"%PDF-1.4 fake")

    cfg = AppConfig()
    cfg.input_directory = root
    monkeypatch.setattr("app.pipeline.processor.get_config", lambda: cfg)
    return root


class TestPathResolution:
    def test_existing_path_wins(self, corpus):
        real = corpus / "ADES Akasha Wira International Tbk" / "2021.pdf"
        assert resolve_document_path(str(real)) == real

    def test_windows_path_resolves_under_linux_root(self, corpus):
        resolved = resolve_document_path(FOREIGN_WINDOWS)
        assert resolved.exists()
        assert resolved.name == "2021.pdf"
        assert resolved.parent.name == "ADES Akasha Wira International Tbk"

    def test_linux_path_resolves_under_windows_root(self, corpus):
        resolved = resolve_document_path(FOREIGN_LINUX)
        assert resolved.exists()
        assert resolved.name == "2021.pdf"

    def test_path_is_reported_relative_to_corpus_root(self, corpus):
        resolved = resolve_document_path(FOREIGN_WINDOWS)
        assert resolved.is_relative_to(corpus)

    def test_unknown_file_is_returned_unchanged(self, corpus):
        missing = str(corpus / "nope" / "absent.pdf")
        assert resolve_document_path(missing) == Path(missing)

    def test_name_fallback_when_relative_layout_differs(self, corpus):
        """A layout with no company subfolder resolves by unique filename."""
        (corpus / "loose.pdf").write_bytes(b"%PDF-1.4 loose")
        resolved = resolve_document_path("/elsewhere/loose.pdf")
        assert resolved.exists()
        assert resolved.name == "loose.pdf"

    def test_path_without_corpus_anchor_resolves(self, corpus):
        """A differently mounted root has no 'LAPORAN KEUANGAN' segment; the
        longest suffix that lands on a real file is used, so the company folder
        still disambiguates."""
        stored = "/mnt/scans/ADES Akasha Wira International Tbk/2021.pdf"
        resolved = resolve_document_path(stored)
        assert resolved.exists()
        assert resolved.parent.name == "ADES Akasha Wira International Tbk"

    def test_ambiguous_name_is_not_guessed(self, corpus):
        """Two files share a name: guessing would silently pick the wrong
        company, so the stored path is returned untouched."""
        for folder in ("Company A", "Company B"):
            d = corpus / folder
            d.mkdir(parents=True, exist_ok=True)
            (d / "twin.pdf").write_bytes(b"%PDF-1.4 twin")
        resolved = resolve_document_path("/nowhere/twin.pdf")
        assert not resolved.exists()
        assert str(resolved) == str(Path("/nowhere/twin.pdf"))

    def test_never_raises_on_missing_input_dir(self, monkeypatch, tmp_path):
        cfg = AppConfig()
        cfg.input_directory = tmp_path / "does-not-exist"
        monkeypatch.setattr("app.pipeline.processor.get_config", lambda: cfg)
        resolved = resolve_document_path(FOREIGN_WINDOWS)
        assert isinstance(resolved, Path)

    def test_handles_posix_separators_in_stored_path(self, corpus):
        stored = "/host/root/LAPORAN KEUANGAN/ADES Akasha Wira International Tbk/2021.pdf"
        assert resolve_document_path(stored).exists()

    def test_real_stored_path_is_used_when_present(self):
        """On the host that recorded it, the absolute path is authoritative."""
        real = Path(REAL_WINDOWS)
        if not real.exists():
            pytest.skip("document not present on this host")
        assert resolve_document_path(REAL_WINDOWS) == real


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    pytest.main([__file__, "-v"])
