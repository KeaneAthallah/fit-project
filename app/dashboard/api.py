"""JSON API for the React dashboard.

Everything the SPA reads goes through here. The module is deliberately thin
around the pipeline: it translates HTTP into repository/orchestrator calls and
shapes the result, and keeps the presentation decisions that belong to neither
layer -- above all the results grid, which has to decide what to do when two
source documents disagree about the same figure.
"""
from __future__ import annotations

import datetime as dt
import math
import threading
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.core.config import AppConfig, get_config
from app.financial.mappings import FIELD_LABELS
from app.storage.database import get_engine, get_session_factory
from app.storage.models import ExtractedValue, ValidationResult
from app.storage.repository import Repository

router = APIRouter(prefix="/api")
Cfg = Depends(get_config)


# --------------------------------------------------------------------------
# field metadata
#
# Header text lives here rather than in the React components so that the grid,
# the value list and the company profile all name a figure the same way.
# --------------------------------------------------------------------------

FIELD_TITLES: dict[str, str] = {
    "total_assets": "Total assets",
    "current_assets": "Total current assets",
    "non_current_assets": "Total non-current assets",
    "cash_and_cash_equivalents": "Cash and cash equivalents",
    "accounts_receivable": "Accounts receivable",
    "inventory": "Inventory",
    "prepaid_expenses": "Prepaid expenses",
    "fixed_assets": "Fixed assets",
    "intangible_assets": "Intangible assets",
    "investment_properties": "Investment properties",
    "other_assets": "Other assets",
    "current_liabilities": "Total current liabilities",
    "non_current_liabilities": "Total non-current liabilities",
    "total_liabilities": "Total liabilities",
    "issued_and_paid_up_capital": "Issued and paid-up capital",
    "retained_earnings": "Retained earnings",
    "total_equity": "Total equity",
    "total_liabilities_and_equity": "Total liabilities and equity",
    "revenue": "Revenue",
    "sales": "Sales",
    "cost_of_revenue": "Cost of revenue",
    "gross_profit": "Gross profit",
    "operating_expenses": "Operating expenses",
    "operating_income": "Operating profit",
    "finance_income": "Finance income",
    "finance_costs": "Finance costs",
    "profit_before_tax": "Profit before tax",
    "income_tax": "Income tax",
    "net_income": "Profit for the year",
    "cash_flow_operating": "Cash flow from operations",
    "cash_flow_investing": "Cash flow from investing",
    "cash_flow_financing": "Cash flow from financing",
    "net_change_in_cash": "Net change in cash",
    "beginning_cash_balance": "Cash at beginning of period",
    "ending_cash_balance": "Cash at end of period",
    "authorized_capital": "Authorized capital",
    "issued_capital": "Issued capital",
    "paid_up_capital": "Paid-up capital",
    "treasury_shares_quantity": "Treasury shares (quantity)",
    "treasury_shares_nominal_value": "Treasury shares (nominal value)",
    "treasury_shares_carrying_value": "Treasury shares (carrying value)",
    "additional_paid_in_capital": "Additional paid-in capital",
    "appropriated_retained_earnings": "Appropriated retained earnings",
    "unappropriated_retained_earnings": "Unappropriated retained earnings",
    "other_comprehensive_income": "Other comprehensive income",
    "other_equity_components": "Other equity components",
    "non_controlling_interest": "Non-controlling interest",
}

# The summary grid, in the order a reader works down it: what the company owns,
# then what it is worth, then the year's trading result, then tax. A figure the
# scan did not extract for a given company simply gets no column rather than a
# column of em dashes, and anything outside this list is reachable through
# ?fields= or the exports, not the default view.
HEADLINE_FIELDS: tuple[str, ...] = (
    "total_assets",
    "total_equity",
    "additional_paid_in_capital",
    "revenue",
    "sales",
    "profit_before_tax",
    "net_income",
    "income_tax",
)

ALL_FIELDS: frozenset[str] = frozenset(
    f for fields in FIELD_LABELS.values() for f in fields
)

# field -> statement, first statement wins so a name reused across statements
# resolves to the one that defines it.
FIELD_STATEMENT: dict[str, str] = {}
for _stmt, _fields in FIELD_LABELS.items():
    for _f in _fields:
        FIELD_STATEMENT.setdefault(_f, _stmt)

# A reading pair is a dispute once the gap exceeds this fraction of the LARGER
# figure. Judged against the smaller reading instead, a small figure next to a
# large one is blown up into a false conflict. Exactly half is agreement: the
# rule is "more than 50%", so the boundary itself must not decorate the grid.
DISPUTE_THRESHOLD = 0.5

# The largest integer a double holds exactly. Anything above it cannot be
# rendered digit-for-digit in the browser, so accepting it would quietly round a
# figure on the way to the screen.
MAX_EXACT_INT = 2**53 - 1

_FINDING_STATUSES = frozenset({"ERROR", "WARNING", "REVIEW_REQUIRED"})

_DOC_SORT_COLUMNS = {
    "id", "company", "filename", "status", "page_count", "reporting_year",
    "avg_confidence", "processing_time", "created_at", "updated_at",
}
_VALUE_SORT_COLUMNS = {
    "id", "company", "year", "field", "statement", "confidence",
    "normalized_value", "status", "created_at",
}
_CHECK_SORT_COLUMNS = {"id", "company", "year", "check_name", "status", "severity"}

# The UI offers display names, not column names. Mapping them here keeps the
# sort dropdown and the schema from having to agree on vocabulary.
_DOC_SORT_ALIASES = {
    "confidence": "avg_confidence",
    "year": "reporting_year",
    "updated": "updated_at",
    "created": "created_at",
}
_VALUE_SORT_ALIASES = {"year": "year", "updated": "created_at"}
_CHECK_SORT_ALIASES = {"updated": "id"}


def _sort_key(requested: str | None, allowed: set[str],
              aliases: dict[str, str], default: str) -> str:
    if not requested:
        return default
    candidate = aliases.get(requested, requested)
    return candidate if candidate in allowed else default


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.isoformat()


def _pagination(total: int, page: int, page_size: int) -> dict[str, int]:
    pages = math.ceil(total / page_size) if page_size > 0 else 0
    return {"total": total, "page": page, "page_size": page_size, "pages": pages}


def _page_of(rows: list[Any], page: int, page_size: int) -> list[Any]:
    """Clamp rather than 404: a page past the end is an empty result, not an
    error, because the grid can be filtered while a request is in flight."""
    start = max(page - 1, 0) * page_size
    return rows[start:start + page_size]


def _norm_currency(raw: str | None) -> str | None:
    if raw is None:
        return None
    c = raw.strip()
    return c.upper() or None


def _currency_matches(value: str | None, wanted: str) -> bool:
    w = wanted.strip().lower()
    if w == "none":
        return value is None
    return value is not None and value.strip().lower() == w


def _session(cfg: AppConfig):
    return get_session_factory(get_engine(cfg))()


def _validated_amount(
    raw: Any,
    *,
    allow_none: bool = False,
    required: bool = True,
) -> int | float | None:
    """Accept only a real, finite, exactly-representable number.

    Pydantic would answer 422 and would coerce a numeric string on the way in,
    which is precisely what must not happen here: "1.500.000.000" silently
    becoming 1.5 is the failure mode this guards against.
    """
    if raw is None:
        if allow_none:
            return None
        raise HTTPException(400, "normalized_value is required.")
    # bool subclasses int, so True must not become 1 rupiah.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HTTPException(
            400,
            "normalized_value must be a number, not text. Send digits only "
            "(1500000000), not a formatted amount like '1.500.000.000'.",
        )
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise HTTPException(400, "normalized_value must be a finite number.")
        if not raw.is_integer():
            # A stray cents figure stays fractional rather than being rounded.
            return raw
    amount = int(raw)
    if abs(amount) > MAX_EXACT_INT:
        raise HTTPException(
            400,
            f"normalized_value {amount} is too large to store exactly and is "
            f"probably a typo. The largest exactly representable figure is "
            f"{MAX_EXACT_INT}.",
        )
    return amount


def _clean_note(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HTTPException(400, "note must be a string.")
    return raw.strip() or None


# --------------------------------------------------------------------------
# the results grid's decision rules
# --------------------------------------------------------------------------

def _summary_rank(v: ExtractedValue) -> tuple[int, float, int]:
    """Deterministic winner among duplicates of one figure.

    A hand correction first, because the user knows more than the score does.
    Then the extractor's own confidence, then the lowest id so the choice does
    not depend on row order.
    """
    return (0 if v.edited_at is not None else 1, -(v.confidence or 0.0), v.id)


def _is_disputed(amounts: Iterable[float | None]) -> bool:
    real = [a for a in amounts if a is not None]
    if len(real) < 2:
        return False
    hi, lo = max(real), min(real)
    if hi <= 0:
        return False
    return (hi - lo) / hi > DISPUTE_THRESHOLD


def _candidate(v: ExtractedValue) -> dict[str, Any]:
    return {
        "id": v.id,
        "document_id": v.document_id,
        "normalized_value": v.normalized_value,
        "raw_value": v.raw_value,
        "unit": v.unit,
        "page": v.page,
        "confidence": v.confidence,
        "status": v.status,
    }


def _summary_cell(
    winner: ExtractedValue, readings: list[ExtractedValue]
) -> dict[str, Any]:
    """One grid cell.

    When the readings disagree materially the cell keeps saying so and carries
    every reading. Confidence cannot break the tie on its own -- on OCR'd
    statements it is anti-correlated with correctness, so ranking by it selects
    the wrong side rather than merely hiding the conflict.
    """
    cell: dict[str, Any] = {
        "id": winner.id,
        "document_id": winner.document_id,
        "normalized_value": winner.normalized_value,
        "original_value": winner.original_value,
        "confidence": winner.confidence or 0.0,
        "status": winner.status,
        "is_edited": winner.edited_at is not None,
        "extraction_method": winner.extraction_method,
        "page": winner.page,
        "currency": winner.currency,
    }
    # A hand correction is the reader's own ruling, so it settles the dispute
    # rather than leaving the grid still arguing about it.
    settled = winner.edited_at is not None
    if not settled and _is_disputed(r.normalized_value for r in readings):
        cell["disputed"] = True
        cell["candidates"] = [
            _candidate(r)
            for r in sorted(
                readings,
                key=lambda r: (r.normalized_value is None, -(r.normalized_value or 0)),
            )
        ]
    return cell


def _row_currency(cells: dict[str, Any]) -> str:
    """The row's own reporting currency.

    Undetected counts as a distinct answer rather than being folded into IDR:
    "we could not tell" and "it is rupiah" are different claims, and a row that
    mixes the two with a real code is genuinely mixed.
    """
    codes = {c["currency"] for c in cells.values() if c is not None}
    if len(codes) > 1:
        return "Mixed"
    if not codes:
        return "Not detected"
    only = next(iter(codes))
    return only or "Not detected"


def _resolve_fields(raw: str | None, present: Iterable[str]) -> list[str]:
    have = set(present)
    wanted = [f.strip() for f in (raw or "").split(",") if f.strip()]
    if wanted:
        unknown = [f for f in wanted if f not in ALL_FIELDS]
        if unknown:
            raise HTTPException(
                400,
                f"Unknown field(s): {', '.join(unknown)}. "
                f"Must be one of: {', '.join(sorted(ALL_FIELDS))}.",
            )
        # Requested order is honoured, duplicates dropped.
        seen: set[str] = set()
        return [f for f in wanted if not (f in seen or seen.add(f))]
    # No usable preference: the headline figures in their canonical order. Only
    # the ones this scope actually has, so the grid never opens on a wall of
    # em dashes for figures no report in view contained.
    return [f for f in HEADLINE_FIELDS if f in have]


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------

def _doc_dict(d, *, counts: dict[int, tuple[int, int]] | None = None) -> dict[str, Any]:
    out = {
        "id": d.id,
        "company": d.company,
        "filename": d.filename,
        "file_path": d.file_path,
        "status": d.status,
        "pdf_type": d.pdf_type,
        "page_count": d.page_count,
        "text_pages": d.text_pages,
        "ocr_pages": d.ocr_pages,
        "financial_pages": d.financial_pages,
        "ocr_used": bool(d.ocr_used),
        "reporting_year": d.reporting_year,
        "avg_confidence": d.avg_confidence,
        "extraction_status": d.extraction_status,
        "validation_status": d.validation_status,
        "processing_time": d.processing_time,
        "error_message": d.error_message,
        "started_at": _iso(d.started_at),
        "completed_at": _iso(d.completed_at),
        "created_at": _iso(d.created_at),
        "updated_at": _iso(d.updated_at),
    }
    if counts is not None:
        values, errors = counts.get(d.id, (0, 0))
        out["value_count"] = values
        out["validation_errors"] = errors
    return out


def _value_dict(v: ExtractedValue) -> dict[str, Any]:
    return {
        "id": v.id,
        "document_id": v.document_id,
        "company": v.company,
        "year": v.year,
        "statement": v.statement,
        "field": v.field,
        "raw_label": v.raw_label,
        "raw_value": v.raw_value,
        "normalized_value": v.normalized_value,
        "currency": v.currency,
        "unit": v.unit,
        "page": v.page,
        "section": v.section,
        "extraction_method": v.extraction_method,
        "confidence": v.confidence or 0.0,
        "status": v.status,
        "original_value": v.original_value,
        "original_method": v.original_method,
        "edited_at": _iso(v.edited_at),
        "edit_note": v.edit_note,
        "is_edited": v.edited_at is not None,
    }


def _check_dict(c, *, file_path: str | None = None) -> dict[str, Any]:
    out = {
        "id": c.id,
        "document_id": c.document_id,
        "company": c.company,
        "year": c.year,
        "check_name": c.check_name,
        "expected": c.expected,
        "actual": c.actual,
        "difference": c.difference,
        "status": c.status,
        "severity": c.severity,
        "category": c.category,
        "message": c.message,
        "evidence": c.evidence,
    }
    if file_path is not None:
        out["file_path"] = file_path
    return out


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------

@router.get("/documents")
def list_documents(
    cfg: AppConfig = Cfg,
    search: str | None = None,
    status: str | None = None,
    company: str | None = None,
    validation_status: str | None = None,
    sort: str = "updated",
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        docs = repo.all_documents()

        rows: list[Any] = []
        needle = (search or "").strip().lower()
        for d in docs:
            if status and d.status != status:
                continue
            if company and company.strip().lower() not in (d.company or "").lower():
                continue
            if validation_status and (d.validation_status or "") != validation_status:
                continue
            if needle and needle not in " ".join(
                filter(None, [d.company, d.filename, d.file_path])
            ).lower():
                continue
            rows.append(d)

        key = _sort_key(sort, _DOC_SORT_COLUMNS, _DOC_SORT_ALIASES, "updated_at")
        rows.sort(
            key=lambda d: (getattr(d, key) is None, getattr(d, key)),
            reverse=(order or "desc").lower() == "desc",
        )

        counts: dict[int, tuple[int, int]] = {}
        for v in repo.all_values():
            n, e = counts.get(v.document_id, (0, 0))
            counts[v.document_id] = (n + 1, e)
        for c in repo.all_validations():
            if c.status in _FINDING_STATUSES:
                n, e = counts.get(c.document_id, (0, 0))
                counts[c.document_id] = (n, e + 1)

        total = len(rows)
        page_rows = _page_of(rows, page, page_size)
        return {
            "items": [_doc_dict(d, counts=counts) for d in page_rows],
            "pagination": _pagination(total, page, page_size),
        }


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, cfg: AppConfig = Cfg) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        doc = repo.get_document(doc_id)
        if doc is None:
            raise HTTPException(404, f"No document with id {doc_id}.")
        values = repo.values_for_document(doc)
        checks = repo.all_validations()
        doc_checks = [c for c in checks if c.document_id == doc_id]
        pages = repo.get_pages(doc)
        out = _doc_dict(doc)
        out["values"] = [_value_dict(v) for v in values]
        out["checks"] = [_check_dict(c, file_path=doc.file_path) for c in doc_checks]
        out["page_rows"] = len(pages)
        return out


@router.get("/documents/{doc_id}/pages")
def get_document_pages(
    doc_id: int,
    cfg: AppConfig = Cfg,
    include_text: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        doc = repo.get_document(doc_id)
        if doc is None:
            raise HTTPException(404, f"No document with id {doc_id}.")
        pages = repo.get_pages(doc)
        rows = [
            {
                "id": p.id,
                "page_number": p.page_number,
                "pdf_type": p.pdf_type,
                "ocr_confidence": p.ocr_confidence,
                "ocr_engine": p.ocr_engine,
                "ocr_time": p.ocr_time,
                "section": p.section,
                "is_relevant": bool(p.is_relevant),
                "is_parent_only": bool(p.is_parent_only),
                # Page text can run to thousands of characters; the list view
                # only needs the metadata.
                "text": p.text if include_text else None,
                "text_length": len(p.text or ""),
            }
            for p in pages
        ]
        return {
            "items": _page_of(rows, page, page_size),
            "pagination": _pagination(len(rows), page, page_size),
        }


# --------------------------------------------------------------------------
# companies
# --------------------------------------------------------------------------

@router.get("/companies")
def list_companies(cfg: AppConfig = Cfg) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        docs = repo.all_documents()
    grouped: dict[str, dict[str, Any]] = {}
    for d in docs:
        entry = grouped.setdefault(d.company, {"company": d.company, "documents": 0,
                                               "status_counts": {}})
        entry["documents"] += 1
        entry["status_counts"][d.status] = entry["status_counts"].get(d.status, 0) + 1
    items = sorted(grouped.values(), key=lambda e: e["company"].lower())
    return {"items": items}


@router.get("/companies/{company:path}")
def get_company_profile(company: str, cfg: AppConfig = Cfg) -> dict[str, Any]:
    """Everything held for one company, across every filing.

    It must not reach a different answer to the same figures than the grid does,
    so the series below are built by the same helpers: a figure the grid calls
    disputed is disputed here, and a gap in years is a null point rather than a
    silently compressed axis.
    """
    wanted = company.strip()
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        docs = [d for d in repo.all_documents() if d.company == wanted]
        if not docs:
            raise HTTPException(404, f"No filings on record for '{wanted}'.")

        values = [v for v in repo.all_values() if v.company == wanted]
        checks = repo.all_validations()

    doc_by_id = {d.id: d for d in docs}
    values = [v for v in values if v.document_id in doc_by_id]

    years_present = sorted({v.year for v in values if v.year is not None})
    axis = years_present

    # One winning reading per (year, field), decided exactly as the grid does.
    grouped: dict[tuple[int | None, str], list[ExtractedValue]] = {}
    for v in values:
        grouped.setdefault((v.year, v.field), []).append(v)

    metrics: dict[str, list[dict[str, Any]]] = {}
    disputed_fields: set[str] = set()
    disputed_cells = 0
    flagged_cells = 0
    without_currency = 0

    for (year, field), readings in grouped.items():
        winner = min(readings, key=_summary_rank)
        cell = _summary_cell(winner, readings)
        if cell.get("disputed"):
            disputed_cells += 1
            disputed_fields.add(field)
        if winner.status and winner.status != "OK":
            flagged_cells += 1
        if winner.currency is None:
            without_currency += 1
        metrics.setdefault(field, {})[year] = cell  # type: ignore[assignment]

    series: dict[str, list[dict[str, Any]]] = {}
    for field, by_year in metrics.items():
        # A metric that only ever appears on an undated report still gets a row.
        field_axis = axis or [None]
        points: list[dict[str, Any]] = []
        for year in field_axis:
            cell = by_year.get(year)
            if cell is None:
                # Explicit null so the chart keeps an even time axis.
                points.append({"year": year, "normalized_value": None})
            else:
                points.append({"year": year, **cell})
        series[field] = points

    failed_checks: dict[str, str] = {}
    for c in checks:
        if c.company != wanted or c.status not in _FINDING_STATUSES:
            continue
        if c.year is not None and axis and c.year not in axis:
            continue
        failed_checks[c.check_name] = c.status

    currencies = sorted({v.currency for v in values if v.currency})

    doc_rows = []
    for d in sorted(docs, key=lambda d: d.filename or ""):
        dv = [v for v in values if v.document_id == d.id]
        doc_rows.append({
            "id": d.id,
            "filename": d.filename,
            "file_path": d.file_path,
            "status": d.status,
            "pdf_type": d.pdf_type,
            "pages": d.page_count,
            "reporting_year": d.reporting_year,
            "values": len(dv),
            "years": sorted({v.year for v in dv if v.year is not None}),
        })

    with_values = len({v.document_id for v in values})
    return {
        "company": wanted,
        "years": years_present,
        "currencies": currencies,
        "totals": {
            "documents": len(docs),
            "documents_with_values": with_values,
            "figures": len(values),
            "years": len(years_present),
            "fields": len({v.field for v in values}),
        },
        "metrics": series,
        "quality": {
            "figures": len(values),
            "disputed_cells": disputed_cells,
            "flagged_cells": flagged_cells,
            "cells_without_currency": without_currency,
            "failed_checks": failed_checks,
            "disputed_fields": sorted(disputed_fields),
        },
        "documents": doc_rows,
        "labels": {f: FIELD_TITLES.get(f, f.replace("_", " ").capitalize())
                   for f in series},
    }


# --------------------------------------------------------------------------
# validations
# --------------------------------------------------------------------------

@router.get("/validations")
def list_validations(
    cfg: AppConfig = Cfg,
    status: str | None = None,
    check_name: str | None = None,
    category: str | None = None,
    company: str | None = None,
    year: int | None = None,
    search: str | None = None,
    sort: str = "id",
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        paths = {d.id: d.file_path for d in repo.all_documents()}
        rows = repo.all_validations()

    needle = (search or "").strip().lower()
    kept = []
    for c in rows:
        if status and c.status != status:
            continue
        if check_name and c.check_name != check_name:
            continue
        if category and (c.category or "") != category:
            continue
        if company and company.strip().lower() not in (c.company or "").lower():
            continue
        if year is not None and c.year != year:
            continue
        if needle and needle not in " ".join(
            filter(None, [c.company, c.check_name, c.message, c.expected, c.actual])
        ).lower():
            continue
        kept.append(c)

    key = _sort_key(sort, _CHECK_SORT_COLUMNS, _CHECK_SORT_ALIASES, "id")
    kept.sort(key=lambda c: (getattr(c, key) is None, getattr(c, key)),
              reverse=(order or "desc").lower() == "desc")
    total = len(kept)
    return {
        "items": [
            _check_dict(c, file_path=paths.get(c.document_id))
            for c in _page_of(kept, page, page_size)
        ],
        "pagination": _pagination(total, page, page_size),
    }


@router.get("/validations/facets")
def validation_facets(cfg: AppConfig = Cfg) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        rows = Repository(s).all_validations()

    def tally(attr: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for r in rows:
            v = getattr(r, attr)
            if v:
                counts[v] = counts.get(v, 0) + 1
        return [{"status" if attr == "status" else attr: k, "count": n}
                for k, n in sorted(counts.items())]

    return {
        "statuses": tally("status"),
        "check_names": tally("check_name"),
        "categories": tally("category"),
        "years": sorted({r.year for r in rows if r.year is not None}),
    }


# --------------------------------------------------------------------------
# extracted values
# --------------------------------------------------------------------------

@router.get("/values")
def list_values(
    cfg: AppConfig = Cfg,
    statement: str | None = None,
    field: str | None = None,
    company: str | None = None,
    year: int | None = None,
    status: str | None = None,
    currency: str | None = None,
    min_confidence: float | None = None,
    search: str | None = None,
    sort: str = "id",
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        rows = Repository(s).all_values()

    needle = (search or "").strip().lower()
    kept = []
    for v in rows:
        if statement and v.statement != statement:
            continue
        if field and v.field != field:
            continue
        if company and company.strip().lower() not in (v.company or "").lower():
            continue
        if year is not None and v.year != year:
            continue
        if status and v.status != status:
            continue
        if currency and not _currency_matches(v.currency, currency):
            continue
        if min_confidence is not None and (v.confidence or 0.0) < min_confidence:
            continue
        if needle and needle not in " ".join(
            filter(None, [v.company, v.field, v.raw_label, v.raw_value, v.statement])
        ).lower():
            continue
        kept.append(v)

    key = _sort_key(sort, _VALUE_SORT_COLUMNS, _VALUE_SORT_ALIASES, "id")
    kept.sort(key=lambda v: (getattr(v, key) is None, getattr(v, key)),
              reverse=(order or "desc").lower() == "desc")
    total = len(kept)
    return {
        "items": [_value_dict(v) for v in _page_of(kept, page, page_size)],
        "pagination": _pagination(total, page, page_size),
    }


@router.get("/values/facets")
def value_facets(cfg: AppConfig = Cfg) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        rows = Repository(s).all_values()

    def tally(attr: str, key: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for r in rows:
            v = getattr(r, attr)
            if v:
                counts[v] = counts.get(v, 0) + 1
        return [{key: k, "count": n} for k, n in sorted(counts.items())]

    currencies: dict[str, int] = {}
    for r in rows:
        # 'none' is the literal bucket for rows where nothing was detected, which
        # is not the same claim as being confirmed IDR.
        key = r.currency or "none"
        currencies[key] = currencies.get(key, 0) + 1

    return {
        "statements": tally("statement", "statement"),
        "fields": tally("field", "field"),
        "years": sorted({r.year for r in rows if r.year is not None}),
        "currencies": [{"currency": k, "count": n}
                       for k, n in sorted(currencies.items())],
    }


@router.patch("/values/{value_id}")
def patch_value(
    value_id: int,
    payload: dict[str, Any] = Body(...),
    cfg: AppConfig = Cfg,
) -> dict[str, Any]:
    """Record or undo a hand correction."""
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        value = repo.get_value(value_id)
        if value is None:
            raise HTTPException(404, f"No extracted value with id {value_id}.")

        if payload.get("revert"):
            if value.edited_at is None:
                raise HTTPException(409, "This value has not been edited.")
            repo.revert_value_edit(value)
            return {"value": _value_dict(repo.get_value(value_id))}

        if "normalized_value" not in payload:
            raise HTTPException(
                400, "Provide normalized_value, or {\"revert\": true}."
            )
        amount = _validated_amount(payload.get("normalized_value"), allow_none=True)
        note = _clean_note(payload.get("note"))
        raw_value = payload.get("raw_value")
        if raw_value is not None and not isinstance(raw_value, str):
            raise HTTPException(400, "raw_value must be a string.")
        repo.apply_value_edit(value, amount, raw_value=raw_value, note=note)
        return {"value": _value_dict(repo.get_value(value_id))}


@router.post("/values")
def create_value(
    payload: dict[str, Any] = Body(...),
    cfg: AppConfig = Cfg,
) -> dict[str, Any]:
    """Add a figure the extractor never found.

    Separate from PATCH because there is no pipeline value to preserve: nothing
    to correct and nothing to revert to. The row is still an audit record, so it
    is hand-marked and `replace_values` re-creates it on a retry.
    """
    doc_id = payload.get("document_id")
    field = payload.get("field")
    if not isinstance(field, str) or field not in ALL_FIELDS:
        raise HTTPException(
            400, f"field must be one of: {', '.join(sorted(ALL_FIELDS))}."
        )
    year = payload.get("year")
    if year is not None and not isinstance(year, int):
        raise HTTPException(400, "year must be an integer or null.")
    amount = _validated_amount(payload.get("normalized_value"))
    note = _clean_note(payload.get("note"))
    statement = FIELD_STATEMENT.get(field, "balance_sheet")
    currency = _norm_currency(payload.get("currency"))

    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        doc = repo.get_document(doc_id) if isinstance(doc_id, int) else None
        if doc is None:
            raise HTTPException(404, f"No document with id {doc_id}.")

        clash = s.query(ExtractedValue).filter(
            ExtractedValue.document_id == doc.id,
            ExtractedValue.field == field,
            ExtractedValue.year == year,
            ExtractedValue.statement == statement,
        ).first()
        if clash is not None:
            raise HTTPException(
                409,
                f"This document already has a figure for '{field}'. Correct the "
                f"existing value instead of adding a second one.",
            )

        if currency is None:
            # An added figure in a report whose currency was detected should not
            # claim "not detected" just because nobody typed it in.
            seen = [
                v.currency for v in repo.values_for_document(doc) if v.currency
            ]
            if seen:
                currency = max(set(seen), key=seen.count)

        row = ExtractedValue(
            document_id=doc.id,
            company=doc.company,
            year=year,
            statement=statement,
            field=field,
            raw_label=FIELD_TITLES.get(field, field),
            raw_value=None,
            normalized_value=amount,
            currency=currency,
            unit=None,
            page=None,
            extraction_method="manual",
            confidence=1.0,
            status="OK",
            original_value=None,
            original_method=None,
            edited_at=dt.datetime.now(dt.timezone.utc),
            edit_note=note,
        )
        s.add(row)
        s.commit()
        return {"value": _value_dict(s.get(ExtractedValue, row.id))}


# --------------------------------------------------------------------------
# the results grid
# --------------------------------------------------------------------------

def _summary_scope(
    cfg: AppConfig,
    *,
    fields: str | None,
    company: str | None,
    year: int | None,
    currency: str | None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str], list[dict[str, int]]]:
    """Every summary row the filters admit, plus its columns and labels.

    The grid and the Excel export both start here, so a downloaded workbook is
    the table on screen rather than a second and slightly different answer to the
    same question. Pagination is left to the caller: a download that quietly
    contained only the visible page would be worse than no download at all.
    """
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        values = repo.all_values()
        docs = {d.id: d for d in repo.all_documents()}
        checks = repo.all_validations()

    scoped = values
    if company:
        needle = company.strip().lower()
        scoped = [v for v in scoped if needle in (v.company or "").lower()]
    if year is not None:
        scoped = [v for v in scoped if v.year == year]

    columns = _resolve_fields(fields, {v.field for v in scoped})

    grouped: dict[tuple[str, int | None], dict[str, list[ExtractedValue]]] = {}
    for v in scoped:
        if v.field in columns:
            grouped.setdefault((v.company, v.year), {}).setdefault(
                v.field, []
            ).append(v)

    # The currency choices are scoped to the columns on screen. A dropdown that
    # offers a currency no cell can hold reads as a broken filter rather than as
    # an empty result, so the global list is not reused here. It deliberately
    # ignores its own currency filter, or the filter could only be set once.
    currency_counts: dict[str, int] = {}
    for v in scoped:
        if v.field in columns:
            key = v.currency or "none"
            currency_counts[key] = currency_counts.get(key, 0) + 1
    currencies = [{"currency": k, "count": n}
                  for k, n in sorted(currency_counts.items())]

    failed_by_row: dict[tuple[str, int | None], dict[str, str]] = {}
    for c in checks:
        if c.status not in _FINDING_STATUSES:
            continue
        failed_by_row.setdefault((c.company, c.year), {})[c.check_name] = c.status

    rows: list[dict[str, Any]] = []
    for (comp, yr), by_field in grouped.items():
        cells: dict[str, Any] = {}
        for field in columns:
            readings = by_field.get(field)
            if not readings:
                cells[field] = None
                continue
            winner = min(readings, key=_summary_rank)
            cell = _summary_cell(winner, readings)
            if currency and not _currency_matches(winner.currency, currency):
                # Filtered to a different currency, so this figure is not part of
                # the answer being shown for it.
                cells[field] = None
                continue
            cells[field] = cell

        if currency and not any(c is not None for c in cells.values()):
            continue  # nothing on this row is in the requested currency

        row_docs: dict[int, set[str]] = {}
        for field, readings in by_field.items():
            for v in readings:
                if currency and not _currency_matches(v.currency, currency):
                    continue
                row_docs.setdefault(v.document_id, set()).add(v.statement)

        rows.append({
            "company": comp,
            "year": yr,
            "currency": _row_currency(cells),
            "cells": cells,
            # A value must belong to a document, so an empty cell needs a target.
            "documents": [
                {"id": did, "filename": docs[did].filename if did in docs else None,
                 "statements": sorted(stmts)}
                for did, stmts in sorted(
                    row_docs.items(),
                    key=lambda kv: (-len(kv[1]), kv[0]),
                )
            ],
            "failed_checks": failed_by_row.get((comp, yr), {}),
        })

    rows.sort(key=lambda r: (r["company"].lower(),
                             (1, 0) if r["year"] is None else (0, -r["year"])))
    labels = {f: FIELD_TITLES.get(f, f.replace("_", " ").capitalize())
              for f in columns}
    return rows, columns, labels, currencies


@router.get("/results/summary")
def results_summary(
    cfg: AppConfig = Cfg,
    fields: str | None = None,
    company: str | None = None,
    year: int | None = None,
    currency: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
) -> dict[str, Any]:
    rows, columns, labels, currencies = _summary_scope(
        cfg, fields=fields, company=company, year=year, currency=currency
    )
    return {
        "items": _page_of(rows, page, page_size),
        "fields": columns,
        "labels": labels,
        "currencies": currencies,
        "pagination": _pagination(len(rows), page, page_size),
    }


@router.get("/results/summary/export")
def results_summary_export(
    cfg: AppConfig = Cfg,
    fields: str | None = None,
    company: str | None = None,
    year: int | None = None,
    currency: str | None = None,
) -> Response:
    """The summary grid as a workbook, filtered exactly as the screen is.

    Same scoping as ``/results/summary`` and deliberately unpaginated: the point
    of an export is the whole answer. Built in memory and streamed back, so
    nothing is written to the output directory to be cleaned up later, and no
    filename is taken from the request.
    """
    from app.export.excel import summary_grid_workbook

    rows, columns, labels, _ = _summary_scope(
        cfg, fields=fields, company=company, year=year, currency=currency
    )
    # The filters go into the workbook too: a file with no record of what it
    # was narrowed to cannot be checked against the screen it came from.
    applied = {k: v for k, v in
               (("company", company), ("year", year), ("currency", currency))
               if v not in (None, "")}
    body = summary_grid_workbook(rows, columns, labels, applied)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=body,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="results-summary-{stamp}.xlsx"'
        },
    )


@router.get("/results/coverage")
def results_coverage(cfg: AppConfig = Cfg) -> dict[str, Any]:
    """Name the companies whose filings exist but have not been read.

    Without this the only visible fact is "company X is not in the report", which
    reads as "there is no filing" when the truth is "we have not opened it yet".
    """
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        docs = repo.all_documents()
        read_docs = {v.document_id for v in repo.all_values()}

    by_company: dict[str, list[Any]] = {}
    for d in docs:
        by_company.setdefault(d.company, []).append(d)

    with_values = {d.company for d in docs if d.id in read_docs}
    missing = []
    for comp, cdocs in sorted(by_company.items()):
        if comp in with_values:
            # A company that did produce data is never listed, however many of
            # its other documents are still queued.
            continue
        by_status: dict[str, int] = {}
        for d in cdocs:
            by_status[d.status] = by_status.get(d.status, 0) + 1
        missing.append({
            "company": comp,
            "documents": len(cdocs),
            "by_status": by_status,
        })

    return {
        "companies_discovered": len(by_company),
        "companies_with_values": len(with_values),
        "companies_without_values": len(missing),
        "documents_total": len(docs),
        "documents_with_values": len(read_docs),
        "missing": missing,
    }


# --------------------------------------------------------------------------
# dashboard totals
# --------------------------------------------------------------------------

@router.get("/summary")
def dashboard_summary(cfg: AppConfig = Cfg) -> dict[str, Any]:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        docs = repo.all_documents()
        values = repo.all_values()
        checks = repo.all_validations()

    status_counts: dict[str, int] = {}
    extraction_counts: dict[str, int] = {}
    validation_doc_counts: dict[str, int] = {}
    for d in docs:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1
        if d.extraction_status:
            extraction_counts[d.extraction_status] = (
                extraction_counts.get(d.extraction_status, 0) + 1
            )
        if d.validation_status:
            validation_doc_counts[d.validation_status] = (
                validation_doc_counts.get(d.validation_status, 0) + 1
            )

    check_status_counts: dict[str, int] = {}
    by_name: dict[tuple[str, str], int] = {}
    by_category: dict[str, int] = {}
    for c in checks:
        check_status_counts[c.status] = check_status_counts.get(c.status, 0) + 1
        key = (c.check_name, c.status)
        by_name[key] = by_name.get(key, 0) + 1
        if c.category:
            by_category[c.category] = by_category.get(c.category, 0) + 1

    confs = [d.avg_confidence for d in docs if d.avg_confidence is not None]
    low = sum(1 for v in values if (v.confidence or 0.0) < 0.5)

    buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    histogram = []
    for lo, hi in buckets:
        n = sum(1 for v in values
                if v.confidence is not None and lo <= v.confidence < hi)
        histogram.append({"bucket": f"{int(lo * 100)}-{int(min(hi, 1.0) * 100)}%",
                          "count": n})

    errors_by_company: dict[str, int] = {}
    for c in checks:
        if c.status in _FINDING_STATUSES:
            errors_by_company[c.company] = errors_by_company.get(c.company, 0) + 1
    worst = [
        {"company": comp, "errors": n}
        for comp, n in sorted(errors_by_company.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    ]

    return {
        "documents": len(docs),
        "companies": len({d.company for d in docs}),
        "pages": sum(d.page_count or 0 for d in docs),
        "values": len(values),
        "checks": len(checks),
        "low_confidence_values": low,
        "avg_confidence": round(sum(confs) / len(confs), 4) if confs else None,
        "status_counts": status_counts,
        "extraction_status_counts": extraction_counts,
        "validation_doc_counts": validation_doc_counts,
        "check_status_counts": check_status_counts,
        "check_by_name": [
            {"check_name": n, "status": st, "count": c}
            for (n, st), c in sorted(by_name.items())
        ],
        "check_by_category": [
            {"category": k, "count": v} for k, v in sorted(by_category.items())
        ],
        "confidence_histogram": histogram,
        "worst_companies": worst,
    }


# --------------------------------------------------------------------------
# batch control
# --------------------------------------------------------------------------

class _Job:
    """Process-wide handle on the single background batch that may be running."""

    def __init__(self) -> None:
        # Reentrant on purpose. begin()/request_stop() take this lock themselves,
        # and the start endpoint has to hold it across a check-then-set on
        # `running`. With a plain Lock that nested acquisition self-deadlocks the
        # requesting thread *while it owns the lock*, which wedges every other
        # endpoint that needs a snapshot -- and because the worker thread is
        # launched only after that block, the batch never starts either.
        self._lock = threading.RLock()
        self.running = False
        self.started_at: dt.datetime | None = None
        self.finished_at: dt.datetime | None = None
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.mode: str | None = None
        # Set by the stop button. The orchestrator polls it between documents, so
        # a stop is cooperative: queued documents never start and in-flight ones
        # finish cleanly instead of being stranded half-extracted.
        self._cancel = threading.Event()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    @property
    def cancel_event(self) -> threading.Event:
        """The flag the orchestrator polls. Never cleared here."""
        return self._cancel

    def begin(self, mode: str) -> None:
        with self._lock:
            self._cancel.clear()
            self.running = True
            self.started_at = dt.datetime.now(dt.timezone.utc)
            self.finished_at = None
            self.result = None
            self.error = None
            self.mode = mode

    def request_stop(self) -> None:
        with self._lock:
            self._cancel.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                # True once a stop has been asked for but in-flight documents are
                # still draining, so the UI can say "stopping" instead of
                # pretending the stop was instant.
                "cancel_requested": self._cancel.is_set(),
                "started_at": _iso(self.started_at),
                "finished_at": _iso(self.finished_at),
                "result": self.result,
                "error": self.error,
                "mode": self.mode,
            }


JOB = _Job()


def _resolve_scan_dir(cfg: AppConfig, raw: str | None) -> Path:
    candidate = Path(raw).expanduser() if raw else cfg.input_directory
    if not candidate.is_absolute():
        candidate = cfg.project_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise HTTPException(400, f"Not a directory: {candidate}")
    return candidate


@router.get("/processing")
def get_processing(cfg: AppConfig = Cfg) -> dict[str, Any]:
    from app.pipeline.orchestrator import status_summary

    snap = JOB.snapshot()
    snap["summary"] = status_summary(cfg)
    snap["input_directory"] = str(cfg.input_directory)
    return snap


@router.post("/processing")
def start_processing(
    payload: dict[str, Any] = Body(default_factory=dict),
    cfg: AppConfig = Cfg,
) -> dict[str, Any]:
    from dataclasses import replace

    from app.pipeline.orchestrator import discover, process_batch, retry_failed, retry_review

    payload = payload or {}
    action = payload.get("action") or "process"
    known = {"scan", "process", "scan_process", "retry_failed", "retry_review"}
    if action not in known:
        raise HTTPException(
            400,
            f"Unknown action '{action}'. Expected one of: {', '.join(sorted(known))}.",
        )
    force = bool(payload.get("force"))
    raw_limit = payload.get("limit")
    limit = int(raw_limit) if isinstance(raw_limit, int) else None

    # Validate the path before claiming the job slot so a bad request fails fast
    # and visibly instead of dying silently inside the worker thread.
    scan_dir = _resolve_scan_dir(cfg, payload.get("input")) if action in {
        "scan", "scan_process"
    } else None

    with JOB._lock:
        if JOB.running:
            raise HTTPException(409, "A batch is already running")
        JOB.begin(action)

    def work() -> None:
        try:
            scan_result: dict[str, Any] | None = None
            if action in {"scan", "scan_process"}:
                # discover() reads cfg.input_directory, so scan against a copy
                # that points at the requested directory. Copying keeps the
                # shared config (and other threads) untouched.
                scan_cfg = replace(cfg, input_directory=scan_dir) if scan_dir else cfg
                found = discover(scan_cfg, limit=limit)
                scan_result = {"directory": str(scan_dir), "discovered": found}

            if action == "retry_failed":
                result = retry_failed(cfg)
            elif action == "retry_review":
                result = retry_review(cfg)
            elif action == "scan":
                # Scan only: register the PDFs and stop.
                result = {"scanned": scan_result}
            else:
                result = process_batch(cfg, force=force, limit=limit,
                                       cancel_event=JOB.cancel_event)
                if scan_result is not None:
                    result = {"scanned": scan_result, "processed": result}
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as job state
            with JOB._lock:
                JOB.error = f"{type(exc).__name__}: {exc}"
        else:
            with JOB._lock:
                JOB.result = result
        finally:
            with JOB._lock:
                JOB.running = False
                JOB.finished_at = dt.datetime.now(dt.timezone.utc)

    threading.Thread(target=work, daemon=True, name="dashboard-batch").start()
    return {"started": True, **JOB.snapshot()}


@router.post("/processing/stop")
def stop_processing() -> dict[str, Any]:
    """Ask the running batch to stop.

    This is cooperative on purpose. Killing the server instead would abandon
    whatever documents were mid-extraction in an in-flight status, and those
    documents would then be invisible until some later run repaired them. Here
    the queue is cancelled and the documents already running are allowed to
    finish and checkpoint, so nothing is lost and a resumed run picks up exactly
    where this one stopped.
    """
    with JOB._lock:
        if not JOB.running:
            raise HTTPException(409, "No batch is running")
    # Outside the lock: request_stop takes it too. The RLock makes this safe
    # either way, but keeping the call out of the block means the lock is never
    # held across anything but a flag read.
    JOB.request_stop()

    return {
        "stopping": True,
        "detail": "Stopping after the in-flight documents finish. This can "
                  "take a minute for a document that is already partway "
                  "through OCR.",
        **JOB.snapshot(),
    }


# --------------------------------------------------------------------------
# log and exports
# --------------------------------------------------------------------------

@router.get("/log")
def tail_log(cfg: AppConfig = Cfg, lines: int = Query(120, ge=1, le=5000)) -> dict[str, Any]:
    path = cfg.project_root / "logs" / "processing.log"
    if not path.is_file():
        return {"path": None, "lines": []}
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"path": str(path), "lines": content[-lines:]}


@router.post("/exports")
def run_exports(cfg: AppConfig = Cfg) -> dict[str, Any]:
    from app.export.csv_export import export_reports
    from app.export.reports import generate_reports, generate_review_queue

    reports = export_reports(cfg)
    review = generate_review_queue(cfg)
    summary = generate_reports(cfg)
    return {"reports": reports, "review_queue": review, "summary": summary}


@router.get("/exports/files")
def export_files(cfg: AppConfig = Cfg) -> dict[str, Any]:
    out = cfg.output_directory
    items = []
    if out.is_dir():
        for f in sorted(out.iterdir()):
            if not f.is_file():
                continue
            stem = f.stem.lower()
            kind = "review" if ("review" in stem or "queue" in stem) else "report"
            items.append({
                "name": f.name,
                "kind": kind,
                "size": f.stat().st_size,
                "modified_at": _iso(
                    dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc)
                ),
                "path": str(f),
            })
    return {"items": items}


@router.get("/exports/download/{name}")
def download_export(name: str, cfg: AppConfig = Cfg) -> FileResponse:
    out = cfg.output_directory.resolve()
    target = (out / name).resolve()
    # Guard the traversal before touching the filesystem.
    if target.parent != out or not target.is_file():
        raise HTTPException(404, f"No export named '{name}'.")
    return FileResponse(target, filename=target.name)