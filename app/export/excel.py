"""Legacy Excel workbook generation with openpyxl.

SUPERSEDED: reports are emitted as CSV by ``app.export.csv_export``. Kept only
as a fallback and not wired into any command; delete once no downstream process
consumes the .xlsx.

Sheets:

Sheets:
    1 Summary, 2 Balance Sheet, 3 Income Statement, 4 Cash Flow, 5 Equity,
    6 Raw Extracted Data, 7 Validation, 8 Errors, 9 Processing Log.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository

logger = get_logger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# Money format that never rounds. `#,##0` displays 1,286,605,455.80 as
# 1,286,605,456, silently discarding digits the source actually reported. The
# decimal placeholders here are literal: Excel prints what is present and pads
# nothing, so whole-rupiah figures stay whole and fractional ones keep every
# digit instead of being cut to two.
MONEY_FMT = "#,##0.##########;[Red]-#,##0.##########"

STATEMENT_SHEETS = [
    ("balance_sheet", "Balance Sheet"),
    ("income_statement", "Income Statement"),
    ("cash_flow", "Cash Flow"),
    ("equity", "Equity"),
]

STATEMENT_TITLE_ROWS = {
    "balance_sheet": ["total_assets", "current_assets", "non_current_assets", "total_liabilities",
                      "total_equity", "total_liabilities_and_equity"],
    "income_statement": ["sales", "revenue", "cost_of_revenue", "gross_profit", "operating_income",
                         "profit_before_tax", "income_tax", "net_income"],
    "cash_flow": ["cash_flow_operating", "cash_flow_investing", "cash_flow_financing",
                  "net_change_in_cash", "beginning_cash_balance", "ending_cash_balance"],
    "equity": ["authorized_capital", "issued_capital", "paid_up_capital",
               "issued_and_paid_up_capital", "treasury_shares_quantity",
               "treasury_shares_nominal_value", "treasury_shares_carrying_value",
               "treasury_shares_percentage", "additional_paid_in_capital",
               "retained_earnings", "appropriated_retained_earnings",
               "unappropriated_retained_earnings", "other_comprehensive_income",
               "other_equity_components", "non_controlling_interest", "total_equity"],
}


def _style_header(ws, ncols: int, nrows: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    if nrows > 0:
        ref = f"A1:{get_column_letter(ncols)}{nrows + 1}"
        ws.auto_filter.ref = ref


def _set_widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _add_table(ws, name: str, ncols: int, nrows: int) -> None:
    if nrows <= 0:
        return
    ref = f"A1:{get_column_letter(ncols)}{nrows + 1}"
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    try:
        ws.add_table(t)
    except Exception:
        pass  # overlapping names/filters are non-fatal


def _hyperlink_formula(path: str) -> str:
    return f'=HYPERLINK("{path}","{Path(path).name}")'


def export_workbook(cfg: AppConfig, out_path: Path | None = None) -> Path:
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = repo.all_documents()
        values = repo.all_values()
        validations = repo.all_validations()

    out = out_path or (cfg.output_directory / "financial_reports.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # ------------------------------------------------------------------ #
    # Sheet 1 — Summary
    ws = wb.active
    ws.title = "Summary"
    headers = ["Company", "Year", "Sales", "Revenue", "Net Income", "Total Assets", "Total Liabilities",
               "Total Equity", "Operating Cash Flow", "Investing Cash Flow", "Financing Cash Flow",
               "Extraction Status", "Confidence"]
    ws.append(headers)
    doc_by_id = {d.id: d for d in docs}
    summary_rows = {}
    for v in values:
        if v.field not in ("sales", "revenue", "net_income", "total_assets", "total_liabilities",
                           "total_equity", "cash_flow_operating", "cash_flow_investing",
                           "cash_flow_financing"):
            continue
        key = (v.company, v.year)
        row = summary_rows.setdefault(key, {})
        if v.field not in row or v.confidence > row[v.field].confidence:
            row[v.field] = v
    nrows = 0
    for (company, year), row in sorted(summary_rows.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        def val(f):
            e = row.get(f)
            return e.normalized_value if e else None
        # Confidence is reported for whichever top line the report used.
        conf = row.get("sales") or row.get("revenue")
        doc = next((d for d in docs if d.company == company), None)
        ws.append([
            company, year,
            val("sales"), val("revenue"),
            val("net_income"), val("total_assets"),
            val("total_liabilities"), val("total_equity"),
            val("cash_flow_operating"), val("cash_flow_investing"), val("cash_flow_financing"),
            doc.extraction_status if doc else "",
            conf.confidence if conf else None,
        ])
        nrows += 1
    _style_header(ws, len(headers), nrows)
    for r in range(2, nrows + 2):
        for c in range(3, 11):
            ws.cell(row=r, column=c).number_format = MONEY_FMT
        ws.cell(row=r, column=12).number_format = "0.0%"
    _set_widths(ws, [34, 8, 18, 18, 18, 18, 18, 18, 18, 18, 18, 12])
    _add_table(ws, "Summary", len(headers), nrows)

    # ------------------------------------------------------------------ #
    # Sheets 2-5 — per-statement detail (with full provenance, req #33)
    for stmt_key, sheet_name in STATEMENT_SHEETS:
        ws = wb.create_sheet(sheet_name)
        headers = ["Company", "Year", "Field", "Raw Label", "Raw Value", "Normalized Value",
                   "Currency", "Unit", "Page", "Source PDF", "Confidence", "Extraction Method"]
        ws.append(headers)
        nrows = 0
        stmt_values = [v for v in values if v.statement == stmt_key]
        # Order rows per the canonical field order for the statement.
        order = {f: i for i, f in enumerate(STATEMENT_TITLE_ROWS.get(stmt_key, []))}
        stmt_values.sort(key=lambda v: (v.company, str(v.year), order.get(v.field, 999), v.field))
        for v in stmt_values:
            doc = doc_by_id.get(v.document_id)
            ws.append([
                v.company, v.year, v.field, v.raw_label, v.raw_value, v.normalized_value,
                v.currency, v.unit, v.page,
                _hyperlink_formula(doc.file_path) if doc else "",
                v.confidence,
                v.extraction_method,
            ])
            r = ws.max_row
            ws.cell(row=r, column=6).number_format = MONEY_FMT
            ws.cell(row=r, column=11).number_format = "0.0%"
            nrows += 1
        _style_header(ws, len(headers), nrows)
        _set_widths(ws, [34, 8, 30, 40, 20, 20, 10, 12, 8, 44, 12, 14])
        _add_table(ws, sheet_name.replace(" ", ""), len(headers), nrows)

    # ------------------------------------------------------------------ #
    # Sheet 6 — Raw Extracted Data
    ws = wb.create_sheet("Raw Data")
    headers = ["Company", "Year", "Statement", "Field", "Raw Label", "Raw Value",
               "Normalized Value", "Currency", "Unit", "Page", "Method", "Confidence", "Status"]
    ws.append(headers)
    nrows = 0
    for v in values:
        ws.append([v.company, v.year, v.statement, v.field, v.raw_label, v.raw_value,
                   v.normalized_value, v.currency, v.unit, v.page, v.extraction_method,
                   v.confidence, v.status])
        ws.cell(row=ws.max_row, column=7).number_format = MONEY_FMT
        nrows += 1
    _style_header(ws, len(headers), nrows)
    _set_widths(ws, [34, 8, 18, 26, 40, 20, 20, 10, 12, 8, 12, 12, 18])
    _add_table(ws, "RawData", len(headers), nrows)

    # ------------------------------------------------------------------ #
    # Sheet 7 — Validation
    ws = wb.create_sheet("Validation")
    headers = ["Company", "Year", "Check", "Expected", "Actual", "Difference", "Status",
               "Severity", "Message"]
    ws.append(headers)
    nrows = 0
    for r in validations:
        ws.append([r.company, r.year, r.check_name, r.expected, r.actual,
                   r.difference, r.status, getattr(r, "severity", None) or "", r.message])
        row_idx = ws.max_row
        for c in (5, 6, 7):
            ws.cell(row=row_idx, column=c).number_format = MONEY_FMT
        status_cell = ws.cell(row=row_idx, column=7)
        if r.status == "ERROR":
            status_cell.font = Font(color="9C0006", bold=True)
            status_cell.fill = PatternFill("solid", fgColor="FFC7CE")
        elif r.status == "WARNING":
            status_cell.font = Font(color="9C6500", bold=True)
            status_cell.fill = PatternFill("solid", fgColor="FFEB9C")
        elif r.status == "VALID":
            status_cell.font = Font(color="006100")
            status_cell.fill = PatternFill("solid", fgColor="C6EFCE")
        elif r.status in ("NOT_APPLICABLE", "NOT_FOUND", "SKIPPED"):
            status_cell.font = Font(color="808080")
        nrows += 1
    _style_header(ws, len(headers), nrows)
    _set_widths(ws, [34, 8, 40, 20, 20, 18, 16, 12, 60])
    _add_table(ws, "Validation", len(headers), nrows)

    # ------------------------------------------------------------------ #
    # Sheet 8 — Errors (REAL errors only: FAILED docs + ERROR-status checks;
    # WARNING/REVIEW_REQUIRED live in the Validation sheet, req #23)
    ws = wb.create_sheet("Errors")
    headers = ["Company", "File", "Page", "Error", "Status", "Message"]
    ws.append(headers)
    nrows = 0
    for d in docs:
        if d.status == "FAILED" and d.error_message:
            ws.append([d.company, Path(d.file_path).name, None, "PROCESSING", "FAILED", d.error_message])
            nrows += 1
        for r in validations:
            if r.document_id == d.id and r.status == "ERROR":
                ws.append([r.company, Path(d.file_path).name, None, r.check_name, r.status, r.message])
                nrows += 1
    _style_header(ws, len(headers), nrows)
    _set_widths(ws, [34, 44, 8, 34, 18, 70])
    _add_table(ws, "Errors", len(headers), nrows)

    # ------------------------------------------------------------------ #
    # Sheet 9 — Processing Log
    ws = wb.create_sheet("Processing Log")
    headers = ["File", "Company", "Pages", "Text Pages", "OCR Pages", "Financial Pages",
               "OCR", "Status", "Duration (s)", "Timestamp", "Path"]
    ws.append(headers)
    nrows = 0
    for d in docs:
        ts = d.completed_at or d.updated_at or d.created_at
        if isinstance(ts, dt.datetime):
            ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        ws.append([
            Path(d.file_path).name, d.company, d.page_count,
            getattr(d, "text_pages", None), getattr(d, "ocr_pages", None),
            getattr(d, "financial_pages", None),
            "YES" if d.ocr_used else "NO", d.status,
            round(d.processing_time, 2) if d.processing_time else None,
            ts, d.file_path,
        ])
        r = ws.max_row
        ws.cell(row=r, column=11).hyperlink = d.file_path
        ws.cell(row=r, column=11).value = "open"
        nrows += 1
    _style_header(ws, len(headers), nrows)
    _set_widths(ws, [44, 34, 8, 10, 10, 12, 6, 18, 12, 20, 12])
    _add_table(ws, "ProcessingLog", len(headers), nrows)

    # ------------------------------------------------------------------ #
    # Sheet 10 — Diagnostics (per-document stage timings, req #29)
    ws = wb.create_sheet("Diagnostics")
    headers = ["File", "Company", "PDF Type", "Pages", "Text Pages", "OCR Pages",
               "Financial Pages", "AI Calls", "Total (s)", "Stage Timings (JSON)"]
    ws.append(headers)
    nrows = 0
    for d in docs:
        metrics_raw = getattr(d, "metrics", None)
        metrics: dict = {}
        if metrics_raw:
            try:
                metrics = json.loads(metrics_raw)
            except Exception:
                metrics = {}
        ws.append([
            Path(d.file_path).name, d.company, d.pdf_type, d.page_count,
            getattr(d, "text_pages", None), getattr(d, "ocr_pages", None),
            getattr(d, "financial_pages", None),
            metrics.get("ai_calls"),
            round(metrics.get("total", 0), 2) if metrics.get("total") else None,
            json.dumps({k: round(v, 3) if isinstance(v, float) else v
                        for k, v in metrics.items()}, default=str) if metrics else None,
        ])
        nrows += 1
    _style_header(ws, len(headers), nrows)
    _set_widths(ws, [44, 34, 12, 8, 10, 10, 12, 10, 10, 70])
    _add_table(ws, "Diagnostics", len(headers), nrows)

    wb.save(out)
    logger.info("Excel workbook written to %s", out)
    return out
