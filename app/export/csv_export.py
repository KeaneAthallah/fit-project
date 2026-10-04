"""Single-file CSV report generation.

The previous deliverable was an .xlsx workbook whose ten sheets duplicated the
same rows ten ways. Sheets cannot exist in CSV, so instead of faking them the
report is now ONE tidy long-format file, ``output/reports/financial_reports.csv``:
one row per extracted figure, with a ``section`` column separating the
statements. That is the shape both Excel pivot tables and pandas expect, and it
means adding a statement never adds a file.

Validation findings live in ``diagnostics.csv`` alongside them. They are a
different grain (a check result, not a figure) and mixing the two into one file
would force every consumer to filter out rows that are not measurements.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.financial.plausibility import (
    MAX_PLAUSIBLE_MONETARY,
    is_implausible_amount,
)
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository

logger = get_logger(__name__)

# utf-8-sig so Excel on Windows opens the Indonesian text correctly instead of
# mojibake; pandas/Excel both handle the BOM transparently.
ENCODING = "utf-8-sig"
NEWLINE = ""

REPORT_FILENAME = "financial_reports.csv"
DIAGNOSTICS_FILENAME = "diagnostics.csv"

# Files written by earlier versions, one per workbook sheet. The report is a
# single file now, so these are removed on export rather than left behind to be
# mistaken for current output. An explicit name list, never a glob, so an
# unrelated file in the directory is never touched.
LEGACY_FILENAMES = (
    "summary.csv",
    "balance_sheet.csv",
    "income_statement.csv",
    "cash_flow.csv",
    "equity.csv",
    "raw_data.csv",
    "validation.csv",
    "errors.csv",
    "processing_log.csv",
    "financial_reports.xlsx",
)

# Emission order for the `section` column. Statements first, then treasury and
# anything unmapped, so the file reads top-down like the workbook did.
SECTION_ORDER = (
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "equity",
    "treasury_shares",
    "other",
)

# Field order within a section: headline totals first, then detail. Anything not
# listed sorts alphabetically after these.
HEADLINE_FIELDS = (
    "total_assets",
    "total_liabilities",
    "total_equity",
    "equity_attributable_to_owners_of_parent",
    "total_liabilities_and_equity",
    "sales",
    "sales_and_revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "total_profit_loss_before_tax",
    "total_profit_loss",
    "net_income",
    "income_tax_paid_operating",
    "cash_flow_operating",
    "cash_flow_investing",
    "cash_flow_financing",
    "net_change_in_cash",
    "ending_cash_balance",
)

# A normalized monetary amount is stored in whole rupiah. The plausibility
# floor and ceiling live in app.financial.plausibility so extraction, validation
# and export can never disagree about what counts as a real figure. The floor
# itself is per-currency and per-scale (see `minimum_plausible_monetary`), so it
# is not restated here as a constant.


def _write(path: Path, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding=ENCODING, newline=NEWLINE) as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        w.writerow(headers)
        for row in rows:
            w.writerow(["" if c is None else c for c in row])
            n += 1
    return n


def _flag(norm: float | None, unit: str | None = None,
          field: str | None = None,
          currency: str | None = None) -> str:
    """Marker column: WHY a reviewer should distrust this row.

    Silence is the dangerous outcome for financial data, so anything
    implausible is labelled explicitly instead of being quietly emitted.

    Which of the two reasons applies is decided against the same floor the
    plausibility module uses for this row's currency and scale. It used to
    compare against a local copy of the rupiah constant, which meant a USD row
    could be labelled IMPLAUSIBLE_MAGNITUDE on a rupiah threshold.
    """
    if norm is None:
        return ""
    if not is_implausible_amount(norm, field, unit, currency):
        return ""
    if abs(norm) > MAX_PLAUSIBLE_MONETARY:
        return "IMPLAUSIBLE_SCALE"
    return "IMPLAUSIBLE_MAGNITUDE"


def section_of(value: Any) -> str:
    """Statement bucket for a value, falling back to its page classification."""
    for candidate in (getattr(value, "statement", None),
                      getattr(value, "section", None)):
        if candidate:
            return str(candidate)
    return "other"


def _remove_legacy_outputs(out: Path) -> list[str]:
    """Delete superseded per-sheet files from earlier exports."""
    removed: list[str] = []
    for name in LEGACY_FILENAMES:
        stale = out / name
        try:
            if stale.is_file():
                stale.unlink()
                removed.append(name)
        except OSError as exc:
            logger.warning("Could not remove stale report %s: %s", stale, exc)
    if removed:
        logger.info("Removed %d superseded report file(s): %s",
                    len(removed), ", ".join(removed))
    return removed


def export_reports(cfg: AppConfig, out_dir: Path | None = None) -> dict[str, int]:
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = repo.all_documents()
        values = repo.all_values()
        validations = repo.all_validations()

    out = out_dir or (cfg.output_directory / "reports")
    out.mkdir(parents=True, exist_ok=True)
    _remove_legacy_outputs(out)
    doc_by_id = {d.id: d for d in docs}
    section_rank = {s: i for i, s in enumerate(SECTION_ORDER)}
    field_rank = {f: i for i, f in enumerate(HEADLINE_FIELDS)}

    def sort_key(v: Any) -> tuple:
        return (
            v.company or "",
            # Unknown year last, otherwise ascending: 2020 < 2021 < 2022.
            (v.year is None, v.year if v.year is not None else 0),
            section_rank.get(section_of(v), len(SECTION_ORDER)),
            field_rank.get(v.field, len(HEADLINE_FIELDS)),
            v.field or "",
            v.page if v.page is not None else 0,
        )

    values = sorted(values, key=sort_key)

    def _report_rows() -> Iterable[list[Any]]:
        for v in values:
            doc = doc_by_id.get(v.document_id)
            yield [
                v.company,
                v.year,
                section_of(v),
                v.field,
                v.raw_label,
                v.raw_value,
                v.normalized_value,
                # Blank for every monetary line, but the only place the declared
                # sub-sector's text lands in a report. Without it the cover
                # statement exports as a row of empty cells.
                getattr(v, "text_value", None) or "",
                v.currency,
                v.unit,
                v.page,
                getattr(v, "section", None) or "",
                Path(doc.file_path).name if doc else "",
                v.confidence,
                v.extraction_method,
                v.status,
                _flag(v.normalized_value, v.unit, v.field, v.currency),
            ]

    counts = {
        REPORT_FILENAME: _write(
            out / REPORT_FILENAME,
            ["company", "year", "section", "field", "label", "raw_value",
             "normalized_value", "text_value", "currency", "unit", "page",
             "page_section", "source_file", "confidence", "extraction_method",
             "status", "data_flags"],
            _report_rows(),
        )
    }

    # -- diagnostics: check results, plus document-level context ----------- #
    doc_status_by_company: dict[str, str] = {}
    for d in docs:
        doc_status_by_company.setdefault(d.company or "", d.status or "")

    def _diag_rows() -> Iterable[list[Any]]:
        for r in sorted(validations,
                        key=lambda x: (x.company or "", str(x.year),
                                       x.check_name or "")):
            doc = doc_by_id.get(r.document_id)
            yield [
                r.company,
                r.year,
                r.check_name,
                r.expected,
                r.actual,
                r.difference,
                r.status,
                getattr(r, "severity", None) or "",
                Path(doc.file_path).name if doc else "",
                doc_status_by_company.get(r.company or "", ""),
                r.message,
            ]

    counts[DIAGNOSTICS_FILENAME] = _write(
        out / DIAGNOSTICS_FILENAME,
        ["company", "year", "check", "expected", "actual", "difference", "status",
         "severity", "source_file", "document_status", "message"],
        _diag_rows(),
    )

    # -- document processing summary --------------------------------------- #
    def _doc_rows() -> Iterable[list[Any]]:
        for d in docs:
            ts = d.completed_at or d.updated_at or d.created_at
            if isinstance(ts, dt.datetime):
                ts = ts.strftime("%Y-%m-%d %H:%M:%S")
            try:
                metrics = json.loads(getattr(d, "metrics", None) or "{}")
            except Exception:
                metrics = {}
            yield [
                Path(d.file_path).name, d.company, d.status, d.pdf_type,
                d.page_count,
                getattr(d, "text_pages", None), getattr(d, "ocr_pages", None),
                getattr(d, "financial_pages", None),
                "YES" if d.ocr_used else "NO",
                round(d.processing_time, 2) if d.processing_time else None,
                ts,
                d.error_message or "",
                json.dumps(metrics, default=str) if metrics else "",
            ]

    counts["documents.csv"] = _write(
        out / "documents.csv",
        ["file", "company", "status", "pdf_type", "pages", "text_pages",
         "ocr_pages", "financial_pages", "ocr_used", "duration_seconds",
         "timestamp", "error", "metrics"],
        _doc_rows(),
    )

    logger.info("CSV reports written to %s", out)
    return counts