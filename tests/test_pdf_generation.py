"""End-to-end tests using synthetic PDFs (no external fixtures needed)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
import pytest

from app.core.config import load_config, set_config
from app.pipeline.orchestrator import discover, process_batch, status_summary
from app.storage.repository import sha256_of_file

TEXT_PDF_CONTENT = """PT ABC INDONESIA
LAPORAN POSISI KEUANGAN
Per 31 Desember 2024 dan 2023
(Dalam jutaan Rupiah)

                                2024        2023
ASET
Aset Lancar
Kas dan Setara Kas              15.000      12.000
Piutang Usaha                   25.000      20.000
Persediaan                      30.000      28.000
Total Aset Lancar               70.000      60.000
Aset Tetap                     330.000     290.000
TOTAL ASET                     400.000     350.000

LIABILITAS DAN EKUITAS
Total Liabilitas               250.000     220.000
Modal Disetor                  100.000     100.000
Saldo Laba                       50.000      30.000
TOTAL EKUITAS                  150.000     130.000
TOTAL LIABILITAS DAN EKUITAS   400.000     350.000


PT ABC INDONESIA
LAPORAN LABA RUGI
Untuk Tahun Yang Berakhir 31 Desember 2024
(Dalam jutaan Rupiah)

Pendapatan                     120.000     100.000
Beban Pokok Pendapatan          80.000      65.000
Laba Kotor                      40.000      35.000
Laba Tahun Berjalan              8.000       6.000
"""


def make_text_pdf(path: Path, content: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for line in content.splitlines():
        page.insert_text((50, y), line, fontsize=8, fontname="cour")
        y += 12
    doc.save(str(path))
    doc.close()


def make_scanned_pdf(path: Path, content: str) -> None:
    """A PDF whose pages are images only (text rendered to raster)."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for line in content.splitlines():
        page.insert_text((50, y), line, fontsize=8, fontname="cour")
        y += 12
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    doc.close()
    doc2 = pymupdf.open()
    page2 = doc2.new_page(width=595, height=842)
    page2.insert_image(page2.rect, stream=img_bytes)
    doc2.save(str(path))
    doc2.close()


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Set up a temp project workspace with sample PDFs and a fresh config."""
    input_dir = tmp_path / "input" / "PT ABC Indonesia"
    input_dir.mkdir(parents=True)
    make_text_pdf(input_dir / "laporan_2024.pdf", TEXT_PDF_CONTENT)

    cfg = load_config()
    cfg.input_directory = tmp_path / "input"
    cfg.output_directory = tmp_path / "output"
    cfg.database_url = f"sqlite:///{(tmp_path / 'db' / 'processing.db').as_posix()}"
    cfg.processing.workers = 1
    cfg.ocr.engine = "tesseract"
    cfg.ocr.language = "eng"
    cfg.ocr.deskew = False
    cfg.ocr.denoise = False
    cfg.ocr.binarize = False
    cfg.ocr.dpi = 200
    cfg.processing.raw_data_directory = str(tmp_path / "data")
    cfg.confidence.review_threshold = 0.5
    cfg.confidence.medium = 0.5
    set_config(cfg)
    yield cfg
    set_config(load_config())


class TestTextPdfPipeline:
    def test_discover_and_process(self, workspace):
        cfg = workspace
        assert discover(cfg) == 1
        result = process_batch(cfg)
        assert result["total"] == 1

        s = status_summary(cfg)
        assert s["status_counts"].get("COMPLETED") == 1

        engine = __import__("app.storage.database", fromlist=["get_engine"]).get_engine(cfg)
        Session = __import__("app.storage.database", fromlist=["get_session_factory"]).get_session_factory(engine)
        from app.storage.repository import Repository

        with Session() as session:
            repo = Repository(session)
            values = repo.all_values()
            fields = {v.field for v in values}
            assert "total_assets" in fields
            assert "revenue" in fields
            ta = {v for v in values if v.field == "total_assets"}
            # Multi-year: both 2024 and 2023 observations exist
            years = {v.year for v in ta}
            assert 2024 in years or 2023 in years

    def test_resume_skips_completed(self, workspace):
        cfg = workspace
        discover(cfg)
        process_batch(cfg)
        # second run should not reprocess completed docs
        result = process_batch(cfg)
        assert result.get("total", 0) == 0

    def test_force_reprocesses_completed(self, workspace):
        """`--force` must actually reach COMPLETED documents.

        It previously could not: process_batch filtered candidates by status
        before consulting force, and COMPLETED was not in the default filter,
        so the flag silently did nothing.
        """
        cfg = workspace
        discover(cfg)
        process_batch(cfg)
        assert status_summary(cfg)["status_counts"].get("COMPLETED") == 1

        result = process_batch(cfg, force=True)
        assert result["total"] == 1
        assert result["processed"] == 1

    def test_export_csv_reports(self, workspace):
        """One tidy data file, plus diagnostics, instead of ten CSVs."""
        cfg = workspace
        discover(cfg)
        process_batch(cfg)
        from app.export.csv_export import export_reports

        counts = export_reports(cfg)
        out = cfg.output_directory / "reports"
        assert out.is_dir()
        for name in ("financial_reports.csv", "diagnostics.csv", "documents.csv"):
            assert (out / name).exists(), name
        assert counts["financial_reports.csv"] > 0

    def test_report_is_single_file_long_format(self, workspace):
        """The deliverable is ONE file whose `section` column separates the
        statements. A workbook's sheets cannot exist in CSV, so they must not
        be re-created as one file per statement."""
        import csv as _csv

        cfg = workspace
        discover(cfg)
        process_batch(cfg)
        from app.export.csv_export import export_reports

        export_reports(cfg)
        out = cfg.output_directory / "reports"

        statements = [
            p for p in out.glob("*.csv")
            if p.name not in {"diagnostics.csv", "documents.csv"}
        ]
        assert [p.name for p in statements] == ["financial_reports.csv"]

        with (out / "financial_reports.csv").open(encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        assert rows, "expected at least one figure"
        for col in ("company", "year", "section", "field", "raw_value",
                    "normalized_value", "unit", "page", "data_flags"):
            assert col in rows[0], col
        # Every row is a measurement, tagged by section.
        assert all(r["section"] for r in rows)

    def test_legacy_per_sheet_files_are_removed(self, workspace):
        """Earlier exports wrote one CSV per workbook sheet. Leaving them next
        to the new single file invites reading stale numbers as current."""
        cfg = workspace
        discover(cfg)
        process_batch(cfg)
        from app.export.csv_export import export_reports

        export_reports(cfg)
        out = cfg.output_directory / "reports"
        for name in ("summary.csv", "balance_sheet.csv", "raw_data.csv",
                     "validation.csv", "errors.csv", "processing_log.csv"):
            stale = out / name
            stale.write_text("stale", encoding="utf-8")
        (out / "financial_reports.xlsx").write_bytes(b"stale")
        (out / "keep_me.csv").write_text("mine", encoding="utf-8")

        export_reports(cfg)

        for name in ("summary.csv", "balance_sheet.csv", "raw_data.csv",
                     "validation.csv", "errors.csv", "processing_log.csv",
                     "financial_reports.xlsx"):
            assert not (out / name).exists(), name
        assert (out / "financial_reports.csv").exists()
        assert (out / "keep_me.csv").exists(), "must not touch unrelated files"


class TestDuplicateDetection:
    def test_duplicate_hash(self, workspace):
        cfg = workspace
        src = cfg.input_directory / "PT ABC Indonesia" / "laporan_2024.pdf"
        dst_dir = cfg.input_directory / "PT COPY Indonesia"
        dst_dir.mkdir()
        shutil.copy(src, dst_dir / "laporan_2024_copy.pdf")
        discover(cfg)
        s = status_summary(cfg)
        assert s["status_counts"].get("DUPLICATE") == 1


class TestHashing:
    def test_sha256_changes_with_content(self, tmp_path):
        a = tmp_path / "a.pdf"
        b = tmp_path / "b.pdf"
        make_text_pdf(a, "hello")
        make_text_pdf(b, "hello2")
        assert sha256_of_file(a) != sha256_of_file(b)
        assert sha256_of_file(a) == sha256_of_file(a)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
