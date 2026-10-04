"""Excel workbook generation with openpyxl.

Two live entry points:

* :func:`summary_grid_workbook` builds the Results > Summary grid as workbook
  bytes for the dashboard's download button.
* :func:`export_workbook` is the older ten-sheet workbook. SUPERSEDED: the batch
  reports are emitted as CSV by ``app.export.csv_export``. Kept only as a
  fallback and not wired into any command; delete once no downstream process
  consumes the .xlsx.
"""
from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path
from typing import Any, Sequence

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

# Zebra band and the tint for a row whose figures failed a reconciliation
# check. Excel has no access to the app's CSS tokens, so these are literal
# values; they are chosen to sit under the header blue without competing with it
# and to stay legible when printed in greyscale.
BAND_FILL = PatternFill("solid", fgColor="F4F7FA")
WARN_FILL = PatternFill("solid", fgColor="FCE9E9")

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
"income_statement": ["sales", "sales_and_revenue", "cost_of_revenue", "gross_profit", "operating_income",
                          "total_profit_loss_before_tax", "total_profit_loss", "net_income"],
    "cash_flow": ["cash_flow_operating", "cash_flow_investing", "cash_flow_financing",
                  "net_change_in_cash", "beginning_cash_balance", "ending_cash_balance",
                  "income_tax_paid_operating"],
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


def summary_grid_workbook(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    labels: dict[str, str],
    filters: dict[str, Any] | None = None,
) -> bytes:
    """The Results > Summary grid, as workbook bytes.

    Built to be handed to somebody else, which drives three choices:

    * Figures are written as numbers, not text, so the recipient can total a
      column. ``MONEY_FMT`` keeps every digit the source reported.
    * A figure the pipeline never found stays an empty cell. "The report does
      not disclose this line" and "it is nil" are different claims, and an empty
      cell is the only one that does not silently assert the second.
    * The caveats travel with the data. Currency varies per row, so a column
      total across rows is not automatically meaningful; and a row whose own
      arithmetic failed is shaded and named rather than quietly shipped as if it
      reconciled. The grid shows both of these on screen and an export that
      dropped them would be less trustworthy than the screen it came from.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"

    headings = ["Company", "Year", "Currency", "Sub-sector"]
    headings += [labels.get(f, f.replace("_", " ").capitalize()) for f in columns]
    headings += ["Checks failed", "Source documents"]
    ws.append(headings)

    warned: set[int] = set()
    for r, row in enumerate(rows, start=2):
        failed = sorted(row.get("failed_checks") or {})
        # Provenance: which PDFs the row's figures came from, so a recipient who
        # disputes a number can go and read it. Falls back to the id when a
        # document has no filename on disk.
        sources = sorted(
            {
                (d.get("filename") or f"document {d.get('id')}")
                for d in (row.get("documents") or [])
            }
        )
        figures = []
        for field in columns:
            cell = (row.get("cells") or {}).get(field)
            figures.append(
                cell.get("normalized_value") if isinstance(cell, dict) else None
            )
        ws.append([
            row.get("company"),
            row.get("year"),
            row.get("currency"),
            # Stated as filed, code prefix and all. Two filings describing one
            # sector are left as the two strings they are: merging them here
            # would assert an equivalence the source never made.
            row.get("subsector"),
            *figures,
            ", ".join(failed),
            ", ".join(sources),
        ])
        if failed:
            warned.add(r)

    ncols = len(headings)
    nrows = len(rows)
    first_figure, last_figure = 5, 4 + len(columns)

    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = BORDER
        cell.alignment = Alignment(
            horizontal="right" if first_figure <= c <= last_figure else "left",
            vertical="center",
            wrap_text=True,
        )
    ws.row_dimensions[1].height = 30

    for r in range(2, nrows + 2):
        # A failed check tints the whole row, because it is a property of the row
        # and a single tinted cell reads as a typo. Otherwise alternate, so a
        # figure can be traced back to its company across eight columns.
        band = WARN_FILL if r in warned else (BAND_FILL if r % 2 == 0 else None)
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            if band is not None:
                cell.fill = band
            if first_figure <= c <= last_figure:
                cell.number_format = MONEY_FMT
                cell.alignment = Alignment(horizontal="right")
            elif c == 2:
                cell.alignment = Alignment(horizontal="center")

    # Freeze the header row and the three identity columns: the figure columns
    # are the ones that scroll away, and a number with no company beside it is
    # not readable.
    ws.freeze_panes = ws.cell(row=2, column=min(first_figure, ncols))

    if nrows > 0:
        ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}{nrows + 1}"

    _set_widths(ws, [38, 8, 14] + [20] * len(columns) + [26, 44])

    _notes_sheet(wb, rows=rows, columns=columns, filters=filters or {})
    return _to_bytes(wb)


def _notes_sheet(
    wb: Workbook, *, rows: Sequence[dict[str, Any]], columns: Sequence[str],
    filters: dict[str, Any],
) -> None:
    """The caveats, on their own sheet.

    Kept off the data sheet because a note row above the header would break the
    autofilter and a cell comment is too easy to miss. This is read once, by
    whoever opens the file.
    """
    ws = wb.create_sheet("Notes")
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 96
    bold = Font(bold=True)

    def put(label: str, text: str) -> None:
        ws.append([label, text])
        ws.cell(row=ws.max_row, column=1).font = bold
        ws.cell(row=ws.max_row, column=2).alignment = Alignment(wrap_text=True)

    put("Generated", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    put(
        "Contents",
        f"{len(rows)} company-year "
        f"{'row' if len(rows) == 1 else 'rows'}, {len(columns)} "
        f"{'figure' if len(columns) == 1 else 'figures'}.",
    )

    ws.append([])
    ws.append(["How to read this file"])
    ws.cell(row=ws.max_row, column=1).font = bold
    put(
        "Blank figure",
        "The pipeline found no such line in any report for that company-year. "
        "It is not zero, and it should not be totalled as zero.",
    )
    put(
        "Currency",
        "Amounts are in each row's own currency, shown in the Currency column. "
        "A column total is only meaningful across rows that share a currency.",
    )
    put(
        "'Not detected'",
        "No currency was found in the source for those figures. This is not the "
        "same as Indonesian rupiah.",
    )
    put(
        "'Mixed'",
        "The figures in that row disagree about currency, or mix a detected code "
        "with an undetected one. Check before using the row.",
    )
    put(
        "Checks failed",
        "Reconciliation checks the pipeline ran that did not hold for that "
        "company-year. Those rows are shaded. The figures are still shown; they "
        "are just known not to add up.",
    )
    put(
        "Source documents",
        "The reports the figures in that row were extracted from.",
    )

    ws.append([])
    ws.append(["Filters applied at export"])
    ws.cell(row=ws.max_row, column=1).font = bold
    applied = {k: v for k, v in filters.items() if v not in (None, "")}
    if applied:
        for key, value in applied.items():
            put(str(key).replace("_", " ").capitalize(), str(value))
    else:
        put("None", "Every company, year and currency was included.")


def _to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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
    headers = ["Company", "Year", "Sales", "Sales and Revenue", "Net Income", "Total Assets", "Total Liabilities",
               "Total Equity", "Operating Cash Flow", "Investing Cash Flow", "Financing Cash Flow",
               "Extraction Status", "Confidence"]
    ws.append(headers)
    doc_by_id = {d.id: d for d in docs}
    summary_rows = {}
    for v in values:
        if v.field not in ("sales", "sales_and_revenue", "net_income", "total_assets", "total_liabilities",
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
        conf = row.get("sales") or row.get("sales_and_revenue")
        doc = next((d for d in docs if d.company == company), None)
        ws.append([
            company, year,
            val("sales"), val("sales_and_revenue"),
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
