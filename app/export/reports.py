"""Review queue + summary report generation."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository

logger = get_logger(__name__)


def _write_csv(path: Path, headers: list[str], rows: list[list]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)
    return len(rows)


def generate_review_queue(cfg: AppConfig) -> dict[str, int]:
    """Write review/*.csv files; returns counts per file."""
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = repo.all_documents()
        values = repo.all_values()
        validations = repo.all_validations()

    review_dir = cfg.review_dir
    counts: dict[str, int] = {}
    # id -> path lookup, so per-value report rows don't rescan `docs` each time.
    path_by_id = {d.id: d.file_path for d in docs}

    # low_confidence.csv
    counts["low_confidence.csv"] = _write_csv(
        review_dir / "low_confidence.csv",
        ["company", "year", "statement", "field", "raw_label", "raw_value", "normalized_value",
         "page", "confidence", "document"],
        [[v.company, v.year, v.statement, v.field, v.raw_label, v.raw_value, v.normalized_value,
          v.page, v.confidence, path_by_id.get(v.document_id, "")]
         for v in values if v.confidence < cfg.confidence.review_threshold],
    )

    # extraction_errors.csv — documents that actually failed to process.
    # DUPLICATE is deliberately excluded: a duplicate is a discovery outcome, not
    # an extraction error, and listing it here double-counted it in
    # failed_documents.csv and made "extraction errors" totals look worse than
    # they were. Duplicates are reported separately below.
    err_rows = []
    for d in docs:
        if d.status != "FAILED":
            continue
        for msg in (d.error_message or "").split("; "):
            if msg:
                err_rows.append([d.company, Path(d.file_path).name, msg])
    counts["extraction_errors.csv"] = _write_csv(
        review_dir / "extraction_errors.csv", ["company", "file", "error"], err_rows)

    # validation_errors.csv — REAL accounting inconsistencies only (ERROR status).
    # Warnings/review items are reported separately so error counts stay honest
    # (requirement #23).
    counts["validation_errors.csv"] = _write_csv(
        review_dir / "validation_errors.csv",
        ["company", "year", "check", "expected", "actual", "difference", "status", "severity",
         "category", "message"],
        [[r.company, r.year, r.check_name, r.expected, r.actual, r.difference, r.status,
          getattr(r, "severity", None) or "", getattr(r, "category", None) or "", r.message]
         for r in validations if r.status == "ERROR"],
    )

    # validation_warnings.csv — WARNING + REVIEW_REQUIRED, not errors.
    counts["validation_warnings.csv"] = _write_csv(
        review_dir / "validation_warnings.csv",
        ["company", "year", "check", "expected", "actual", "difference", "status", "severity",
         "category", "message"],
        [[r.company, r.year, r.check_name, r.expected, r.actual, r.difference, r.status,
          getattr(r, "severity", None) or "", getattr(r, "category", None) or "", r.message]
         for r in validations if r.status in ("WARNING", "REVIEW_REQUIRED")],
    )

    # failed_documents.csv — real failures only.
    counts["failed_documents.csv"] = _write_csv(
        review_dir / "failed_documents.csv",
        ["company", "file", "status", "error"],
        [[d.company, Path(d.file_path).name, d.status, d.error_message]
         for d in docs if d.status == "FAILED"],
    )

    # duplicates.csv — same file content under two paths; the original is kept.
    counts["duplicates.csv"] = _write_csv(
        review_dir / "duplicates.csv",
        ["company", "file", "note"],
        [[d.company, Path(d.file_path).name, d.error_message]
         for d in docs if d.status == "DUPLICATE"],
    )
    logger.info("Review queue written: %s", counts)
    return counts


def generate_reports(cfg: AppConfig) -> dict:
    """processing_report.json + extraction_summary.json + console summary."""
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = repo.all_documents()
        values = repo.all_values()
        validations = repo.all_validations()

    cfg.output_directory.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1

    pages = sum(d.page_count or 0 for d in docs)
    ocr_docs = sum(1 for d in docs if d.ocr_used)
    confs = [d.avg_confidence for d in docs if d.avg_confidence is not None]

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "companies": len({d.company for d in docs}),
        "documents": len(docs),
        "pages_processed": pages,
        "status_counts": counts,
        "ocr_documents": ocr_docs,
        "text_documents": len([d for d in docs if d.pdf_type == "TEXT"]),
        "extracted_values": len(values),
        "validation_checks": len(validations),
        "average_confidence": round(sum(confs) / len(confs), 4) if confs else None,
    }
    (cfg.output_directory / "extraction_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    doc_report = [
        {
            "company": d.company,
            "file": d.file_path,
            "status": d.status,
            "pdf_type": d.pdf_type,
            "pages": d.page_count,
            "ocr_used": bool(d.ocr_used),
            "reporting_year": d.reporting_year,
            "avg_confidence": d.avg_confidence,
            "extraction_status": d.extraction_status,
            "validation_status": d.validation_status,
            "processing_time": d.processing_time,
            "error": d.error_message,
        }
        for d in docs
    ]
    (cfg.output_directory / "processing_report.json").write_text(
        json.dumps({"summary": summary, "documents": doc_report}, indent=2), encoding="utf-8")

    return summary


def print_summary(summary: dict) -> None:
    print("=" * 40)
    print("FINANCIAL REPORT EXTRACTION COMPLETE")
    print("=" * 40)
    print(f"Companies       : {summary.get('companies', 0)}")
    print(f"PDF Documents   : {summary.get('documents', 0)}")
    print(f"Pages Processed : {summary.get('pages_processed', 0):,}")
    print()
    counts = summary.get("status_counts", {})
    print(f"Successful      : {counts.get('COMPLETED', 0)}")
    print(f"Review Required : {counts.get('REVIEW_REQUIRED', 0)}")
    print(f"Failed          : {counts.get('FAILED', 0)}")
    print(f"Duplicates      : {counts.get('DUPLICATE', 0)}")
    print()
    print(f"OCR Documents   : {summary.get('ocr_documents', 0)}")
    print(f"Text Documents  : {summary.get('text_documents', 0)}")
    print()
    avg = summary.get("average_confidence")
    print(f"Average Confidence : {avg * 100:.1f}%" if avg is not None else "Average Confidence : n/a")
    print()
    print("CSV Output:")
    print("output/reports/financial_reports.csv  (one row per figure;")
    print("                             filter by the `section` column)")
    print("output/reports/diagnostics.csv        (validation checks)")
    print("output/reports/documents.csv          (per-document processing log)")
    print("=" * 40)
