"""Core document processing pipeline.

Per document:
    classify PDF -> per-page text/OCR decision (only OCR pages that need it) ->
    classify pages -> financial relevance scoring -> tables only on candidate
    pages -> detect unit -> rule-based extraction -> AI extraction (optional,
    batched, cached) -> confidence scoring -> validation (only when data is
    sufficient) -> persist everything (raw + structured, never overwritten).

Stage timings are collected in ``result.metrics`` for the diagnose command.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.base import AIExtractor, cache_key_for
from app.ai.schemas import DocumentExtraction
from app.core.config import AppConfig, get_config
from app.core.exceptions import PDFParseError
from app.core.logging import get_logger
from app.extraction.ocr import ocr_page
from app.extraction.page_classifier import (
    classify_section,
    financial_page_score,
    is_parent_only_page,
)
from app.extraction.table_extractor import detect_page_unit, extract_tables_from_file, parse_ocr_table_text
from app.financial.mappings import map_label, resolve_treasury_field
from app.financial.percentage import is_percentage, parse_percentage
from app.financial.normalizer import UnitInfo, detect_unit, normalize_value
_UI = UnitInfo
from app.financial.parser import NumberParseError, parse_financial_number, looks_like_number, parse_share_quantity
from app.financial.plausibility import (
    NON_MONETARY_FIELDS,
    correct_unit_multiplier,
    is_implausible_amount,
    is_monetary,
)
from app.financial.validators import (
    ValidationCheck,
    ValidationStatus,
    aggregate_status,
    count_status,
    status_breakdown,
    validate_document,
)
from app.ingestion.metadata import year_from_filename, year_from_text
from app.ingestion.pdf_detector import classify_pdf
from app.storage.models import Document
from app.storage.repository import Repository

logger = get_logger(__name__)

STATEMENT_KEYS = ("balance_sheet", "income_statement", "cash_flow", "equity")


@dataclass
class DocumentResult:
    doc: Document
    page_count: int = 0
    pdf_type: str | None = None
    ocr_used: bool = False
    reporting_year: int | None = None
    avg_confidence: float | None = None
    extraction_status: str = "UNKNOWN"
    validation_status: str = "UNKNOWN"
    values: list[dict] = field(default_factory=list)
    validations: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    text_pages: int = 0
    ocr_pages: int = 0
    financial_pages: int = 0
    ai_calls: int = 0
    validation_breakdown: dict = field(default_factory=dict)
    error_count: int = 0
    review_count: int = 0


def _value_rank(v: dict) -> tuple[int, float]:
    """Support score for an observation, used to settle competing values.

    Mirrors the extraction-time ranking (see `_authority`): a primary statement
    page beats a header-zipped page, which beats an unsectioned page, and
    confidence breaks the remaining ties. Implausible amounts rank lowest.
    """
    if v.get("implausible"):
        return -2, v.get("confidence", 0.0)
    if v.get("is_parent_only"):
        return -1, v.get("confidence", 0.0)
    if v.get("section") in STATEMENT_KEYS:
        rank = 3
    elif v.get("year_from_header"):
        rank = 2
    else:
        rank = 1
    return rank, v.get("confidence", 0.0)


def resolve_document_path(file_path: str | Path) -> Path:
    """Locate a document's PDF even when the stored path is from another host.

    `documents.file_path` is recorded by whichever host ran `scan`, and that
    path is reused verbatim. The same SQLite file is mounted into the Docker
    container, where a stored `C:\\Users\\...\\report.pdf` does not exist: every
    document failed instantly with "File missing" and the container silently
    produced empty reports.

    Paths are therefore treated as a hint. The stored path wins when it exists;
    otherwise the tail after the input directory is re-joined onto the
    currently configured input directory, and as a last resort the file is
    looked up by name under it.
    """
    raw = Path(file_path)
    if raw.exists():
        return raw

    input_dir = get_config().input_directory
    if not input_dir.exists():
        return raw

    # Stored path was absolute on a different host: keep the part below the
    # corpus root and re-root it on this host's input directory.
    text = str(raw).replace("\\", "/")
    parts = [p for p in text.split("/") if p]
    for anchor in ("LAPORAN KEUANGAN", input_dir.name):
        if anchor in parts:
            idx = parts.index(anchor)
            candidate = input_dir.joinpath(*parts[idx + 1:])
            if candidate.exists():
                return candidate
            break

    # No corpus anchor in the path, e.g. the corpus was mounted somewhere else.
    # Retry with the longest suffix that lands on a real file: deterministic,
    # and it keeps the company folder so a bare name search cannot pick the
    # wrong company.
    if len(parts) > 1:
        for start in range(1, len(parts)):
            candidate = input_dir.joinpath(*parts[start:])
            if candidate.is_file():
                return candidate

    # Fall back to a recursive name match (unique per corpus).
    try:
        matches = list(input_dir.rglob(raw.name))
    except OSError:
        matches = []
    if len(matches) == 1:
        return matches[0]
    return raw


class DocumentProcessor:
    def __init__(self, cfg: AppConfig, repo: Repository, ai_extractor: AIExtractor | None):
        self.cfg = cfg
        self.repo = repo
        self.ai = ai_extractor

    # ------------------------------------------------------------------ #
    def process(self, doc: Document, force: bool = False) -> DocumentResult:
        start = time.perf_counter()
        result = DocumentResult(doc=doc)
        self.repo.mark_processing(doc)
        try:
            self._process_inner(doc, result, force)
        except Exception as exc:
            logger.exception("Processing failed for %s", doc.file_path)
            result.errors.append(str(exc))
            self.repo.mark_failed(doc, str(exc))
            result.extraction_status = "FAILED"
            result.metrics["total"] = time.perf_counter() - start
            self._write_raw(doc, result)
            return result
        result.metrics["total"] = time.perf_counter() - start
        self.repo.mark_completed(doc, processing_time=result.metrics["total"])
        return result

    # ------------------------------------------------------------------ #
    def _process_inner(self, doc: Document, result: DocumentResult, force: bool) -> None:
        self.repo.set_status(doc, "PROCESSING")
        path = resolve_document_path(doc.file_path)
        if not path.exists():
            # Report the configured root too: "File missing" against a path from
            # another host is unactionable without it.
            raise PDFParseError(
                f"File missing: {doc.file_path} "
                f"(searched under input directory: {get_config().input_directory})")

        # 1. Per-page content decision: check each page's text layer and only
        # OCR pages that actually need it (requirements #14/#15).
        t0 = time.perf_counter()
        cls = classify_pdf(str(path))
        result.pdf_type = cls.pdf_type
        result.page_count = cls.page_count
        result.metrics["pdf_classification"] = time.perf_counter() - t0
        self.repo.set_status(doc, "OCR" if cls.pdf_type != "TEXT" else "EXTRACTING")

        t0 = time.perf_counter()
        pages = self._extract_page_content(doc, result, force)
        result.metrics["text_and_ocr"] = time.perf_counter() - t0
        result.text_pages = sum(1 for p in pages if p["pdf_type"] == "TEXT")
        result.ocr_pages = sum(1 for p in pages if p["pdf_type"] == "SCANNED")

        result.values_meta_pages = pages  # type: ignore[attr-defined]

        # 2. Page classification + relevance scoring (cheap, deterministic)
        t0 = time.perf_counter()
        for p in pages:
            p["section"] = classify_section(p["text"] or "")
            p["is_parent_only"] = is_parent_only_page(p["text"] or "")
            p["score"] = financial_page_score(p["text"] or "")
            p["is_relevant"] = 1 if (
                p["score"] >= self.cfg.processing.min_financial_page_score
                or p["section"] is not None
            ) else 0
        result.financial_pages = sum(1 for p in pages if p["is_relevant"])
        result.metrics["page_classification"] = time.perf_counter() - t0

        self.repo.replace_pages(doc, [
            {k: p[k] for k in ("page_number", "pdf_type", "text", "section", "is_relevant",
                               "is_parent_only", "ocr_confidence", "ocr_engine", "ocr_time")
             if k in p}
            for p in pages
        ])

        # 3. Detect year + unit
        year = doc.reporting_year or year_from_filename(doc.filename)
        if year is None:
            full_head = "\n".join((p["text"] or "") for p in pages[:6])
            year = year_from_text(full_head)
        result.reporting_year = year

        unit_info = self._detect_unit_overall(doc, pages)
        self._save_raw_pages(doc, pages)

        # 4. Extraction: rule-based on tables + AI on relevant pages only
        t0 = time.perf_counter()
        self.repo.set_status(doc, "EXTRACTING")
        values = self._extract_values(doc, pages, unit_info, year, result, force)
        result.metrics["extraction"] = time.perf_counter() - t0
        result.values = values
        self.repo.replace_values(doc, values)

        # 5. Confidence scoring
        result.avg_confidence = self._average_confidence(values)

        # 6. Validation — field-aware, runs ONLY on normalized values, grouped
        # per reporting period so years are never mixed (requirements #11/#12).
        t0 = time.perf_counter()
        self.repo.set_status(doc, "VALIDATING")
        by_year = self._group_by_year(values)
        validation_rows: list[dict] = []
        all_checks: list[ValidationCheck] = []
        for yr, grouped in sorted(by_year.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
            checks = validate_document(
                grouped,
                tolerance=self.cfg.validation.tolerance,
                absolute_tolerance=self.cfg.validation.absolute_tolerance,
                relative_tolerance=self.cfg.validation.relative_tolerance,
            )
            all_checks.extend(checks)
            for c in checks:
                validation_rows.append(
                    {
                        "company": doc.company,
                        "year": yr,
                        "check_name": c.check_name,
                        "expected": f"{c.expected:,.2f}" if c.expected is not None else None,
                        "actual": f"{c.actual:,.2f}" if c.actual is not None else None,
                        "difference": c.difference,
                        "status": c.status,
                        "message": c.message,
                        "severity": c.severity,
                        "category": c.category,
                        "evidence": json.dumps(c.evidence, default=str) if c.evidence else None,
                    }
                )
        result.validations = validation_rows
        self.repo.replace_validations(doc, validation_rows)

        # Document-level validation status reflects ONLY the accounting checks.
        # Low extraction confidence is tracked separately (requirement #21).
        result.validation_status = aggregate_status(all_checks)
        result.validation_breakdown = status_breakdown(all_checks)  # type: ignore[attr-defined]
        result.error_count = count_status(all_checks, ValidationStatus.ERROR)  # type: ignore[attr-defined]
        result.review_count = count_status(all_checks, ValidationStatus.REVIEW_REQUIRED)  # type: ignore[attr-defined]
        result.metrics["validation"] = time.perf_counter() - t0

        # 7. Final statuses. Low-confidence values -> per-value REVIEW_REQUIRED
        # status on the value itself (already set in extraction) and a count in
        # metrics — they do NOT fail validation and do NOT loop the document
        # back through processing (root cause of the old '126 errors' loop).
        low_conf_count = sum(
            1 for v in values
            if v.get("confidence", 0) < self.cfg.confidence.review_threshold
        )
        result.metrics["low_confidence_values"] = low_conf_count
        result.extraction_status = "COMPLETED"
        self.repo.update_extract_meta(
            doc,
            page_count=result.page_count,
            pdf_type=result.pdf_type,
            ocr_used=result.ocr_used,
            reporting_year=result.reporting_year,
            avg_confidence=result.avg_confidence,
            extraction_status=result.extraction_status,
            validation_status=result.validation_status,
            text_pages=result.text_pages,
            ocr_pages=result.ocr_pages,
            financial_pages=result.financial_pages,
            metrics=json.dumps(result.metrics, default=str),
        )
        # Document is COMPLETED unless validation found a real inconsistency.
        if result.validation_status == "ERROR":
            self.repo.set_status(doc, "REVIEW_REQUIRED")
        # Persist raw extraction
        self._write_raw(doc, result)
        breakdown = result.validation_breakdown
        breakdown_str = " ".join(f"{k.lower()}={v}" for k, v in sorted(breakdown.items()))
        logger.info(
            "Processed %s: type=%s pages=%d (text=%d ocr=%d) financial=%d values=%d "
            "validation: %s | low_conf=%d extraction_errors=%d %.1fs",
            doc.filename, result.pdf_type, result.page_count, result.text_pages,
            result.ocr_pages, result.financial_pages, len(values),
            breakdown_str or "none", low_conf_count, len(result.errors),
            result.metrics.get("total", 0),
        )

    # ------------------------------------------------------------------ #
    def _extract_page_content(self, doc: Document, result: DocumentResult, force: bool) -> list[dict]:
        """Per-page: use text layer when sufficient; OCR only that page otherwise."""
        import pymupdf

        pages: list[dict] = []
        max_pages = self.cfg.processing.max_pages_per_document
        threshold = self.cfg.processing.text_char_threshold
        ocr_dir = self._ocr_dir(doc)
        cache_dir = self.cfg.data_dir / "cache" / "ocr"
        pdf_hash = doc.file_hash or ""

        with pymupdf.open(str(resolve_document_path(doc.file_path))) as pdf:
            n = pdf.page_count if max_pages <= 0 else min(pdf.page_count, max_pages)
            for i in range(n):
                pno = i + 1
                page = pdf[i]
                text = ""
                try:
                    text = page.get_text("text") or ""
                except Exception:
                    text = ""
                if len(text.strip()) >= threshold:
                    pages.append({"page_number": pno, "pdf_type": "TEXT", "text": text})
                    continue
                # Insufficient text layer -> OCR just this page (cached).
                try:
                    ocr = ocr_page(
                        page, self.cfg.ocr, pno,
                        save_image_dir=ocr_dir,
                        cache_dir=None if force else cache_dir,
                        pdf_hash=pdf_hash,
                    )
                except Exception as exc:
                    # One unreadable page must not kill a 300-page document:
                    # record the error and keep the page as textless.
                    logger.warning("OCR failed on page %d of %s — skipping page: %s",
                                   pno, doc.filename, exc)
                    result.errors.append(f"OCR failed on page {pno}: {exc}")
                    pages.append({"page_number": pno, "pdf_type": "OCR_FAILED", "text": ""})
                    continue
                pages.append(
                    {
                        "page_number": pno,
                        "pdf_type": "SCANNED",
                        "text": ocr.text,
                        "ocr_confidence": ocr.confidence,
                        "ocr_engine": ocr.engine,
                        "ocr_time": ocr.processing_time,
                        "ocr_cached": ocr.cached,
                    }
                )
                result.ocr_used = True
        return pages

    # ------------------------------------------------------------------ #
    def _ocr_dir(self, doc: Document) -> Path:
        slug = re.sub(r"[^\w\-]+", "_", Path(doc.file_path).stem)[:80]
        return self.cfg.data_dir / "ocr" / doc.company[:80] / f"{slug}_{doc.id or ''}"

    def _extracted_dir(self, doc: Document) -> Path:
        slug = re.sub(r"[^\w\-]+", "_", Path(doc.file_path).stem)[:80]
        return self.cfg.data_dir / "extracted" / doc.company[:80] / f"{slug}_{doc.id or ''}"

    def _detect_unit_overall(self, doc: Document, pages: list[dict]) -> UnitInfo:
        """Detect the dominant unit from statement pages, else first relevant pages.

        Only pages classified as primary statements are trusted first: summary
        and highlights pages often mention narrative amounts ('Rp1.15 trillion
        in 2024') that must not define the statement unit.
        """
        statement_pages = [p["text"] or "" for p in pages if p.get("section") in STATEMENT_KEYS]
        candidates: list[str] = statement_pages
        if not candidates:
            for p in pages:
                if p.get("is_relevant"):
                    candidates.append(p["text"] or "")
        if not candidates:
            candidates = [(p["text"] or "") for p in pages[:4]]
        # Look for explicit unit statements near statement headers.
        # Also handles paren forms: '(dalam Jutaan)', '(in billion)', 'dalam Jutaan)'.
        intro = r"(?:dalam|in|disajikan\s+dalam|expressed\s+in)\s+(?:\(?\s*)?"
        unitword = r"(?:ribu|juta|miliar|triliun|thousand|million|billion|trillion)"
        unit_re = re.compile(intro + "(" + unitword + r"[a-z]*" + r"(?:\s+(?:rupiah|usd?|dollars?))?" + r"(?:\s*\)?)" + ")", re.I)
        for text in candidates[:8]:
            m = unit_re.search(text[:2500])
            if m:
                info = detect_unit(m.group(0))
                if info.unit or info.currency:
                    info.confidence = max(info.confidence, 0.9)
                    return info
            plain = detect_unit(text[:2500])
            if plain.unit and plain.confidence >= 0.85:
                return plain
        info = detect_unit(" ".join(candidates[:2])[:2500])
        return info

    # ------------------------------------------------------------------ #
    def _extract_values(
        self,
        doc: Document,
        pages: list[dict],
        unit_info: UnitInfo,
        year: int | None,
        result: DocumentResult,
        force: bool,
    ) -> list[dict]:
        values: dict[tuple[str, str, int | None], dict] = {}
        parent_pages = {p["page_number"] for p in pages if p.get("is_parent_only")}

        def _authority(v: dict) -> tuple[int, float]:
            """Rank competing observations for the same (statement, field, year).

            A primary financial statement page is authoritative for its own line
            items; notes and unsectioned pages are not. Notes routinely restate a
            total ('Total aset tidak lancar' inside a note table) or clip a
            column, so confidence alone lets a notes fragment beat the real
            statement: AALI 2021 kept a truncated notes value of 187,614m over
            the balance sheet's 20,985,698m, which then failed the assets_split
            identity check.

            A year taken from a detected table header column is the third signal:
            it was zipped to a verified column, whereas a lone value from an
            unsectioned page takes its year from the filename and can belong to
            a different statement entirely. ADES 2021 kept a notes-page
            'Beban pokok penjualan' of (258.230) over the financial-highlights
            table's correct (435.507) purely on confidence.

            Statement rank dominates, then year provenance, then confidence.

            Parent-only ("entitas induk") statements are demoted below every
            consolidated observation regardless of rank. They are a different
            reporting entity, not a better source: AISA 2021 draws its
            consolidated assets from p215-217 but its liabilities from the
            parent's supplementary statements on p364, so the two subtotals
            never reconcile. Setting section to None upstream keeps these pages
            out of STATEMENT_KEYS; this explicit guard covers AI extractions,
            which stamp their own section.
            """
            if v.get("implausible"):
                return -2, v.get("confidence", 0.0)
            if v.get("is_parent_only"):
                return -1, v.get("confidence", 0.0)
            if v.get("section") in STATEMENT_KEYS:
                rank = 3
            elif v.get("year_from_header"):
                rank = 2
            else:
                rank = 1
            return rank, v.get("confidence", 0.0)

        def add(statement: str, fld: str, v: dict) -> None:
            # Stamping here covers every producer (rule-based, table, OCR and
            # AI) uniformly, including AI output that carries its own section.
            if v.get("page") in parent_pages:
                v["is_parent_only"] = True
            # Year plausibility is enforced at the single choke point every
            # producer passes through, so a header zipped to the wrong column
            # cannot invent a fiscal year either.
            checked = self._plausible_year(v.get("year"), doc)
            if v.get("year") is not None and checked is None:
                return
            v["year"] = checked
            # Rank implausible amounts below every real observation. They are
            # still recorded (the data is auditable, and the exporter flags
            # them) but a bare fragment must never outrank the real total.
            if is_implausible_amount(v.get("normalized_value"), fld, v.get("unit")):
                v["implausible"] = True
                # ...and it must stop claiming to be a verified figure. The
                # ranking above only decides which value is *shown*; without
                # this the grid presented a page number as `status=OK`, which
                # is the same as asserting it was checked and found correct.
                if v.get("status", "OK") == "OK":
                    v["status"] = "IMPLAUSIBLE"
            key = (statement, fld, v.get("year"))
            existing = values.get(key)
            if existing is None or _authority(v) > _authority(existing):
                values[key] = v

        # A. Rule-based extraction from tables and statement pages
        # Unmapped labels are preserved as UNMAPPED observations — data is
        # never lost, and they never become validation errors (requirement #4).
        unmapped: list[dict] = []
        self._rule_based_extraction(doc, pages, unit_info, add, result, unmapped)
        if unmapped:
            result.metrics["unmapped_fields"] = len(unmapped)
            self._write_unmapped(doc, unmapped)

        # B. AI extraction on relevant pages only
        if self.ai is not None and self.ai.provider_name != "none":
            if not self.cfg.send_to_external_ai and self.ai.provider_name != "ollama":
                logger.warning(
                    "AI provider configured but SEND_TO_EXTERNAL_AI=false; skipping AI extraction"
                )
            else:
                try:
                    self._ai_extraction(doc, pages, unit_info, year, add, force, result)
                except Exception as exc:
                    logger.error("AI extraction failed for %s: %s", doc.filename, exc)
                    result.errors.append(f"AI extraction: {exc}")

        return list(values.values())

    # ------------------------------------------------------------------ #
    def _rule_based_extraction(self, doc, pages, unit_info, add, result, unmapped=None) -> None:
        relevant = [p for p in pages if p.get("is_relevant")]
        # Drop parent-only ("entitas induk") statements here rather than only
        # de-ranking them: where no consolidated counterpart exists, ranking
        # cannot help, because a lone observation still wins by default. A
        # parent's liabilities would then be stored beside the group's assets.
        # Reports that only ever present parent figures keep nothing, which is
        # the honest outcome — a mixed set is worse than an absent one.
        relevant = [p for p in relevant if not p.get("is_parent_only")]
        if not relevant:
            return
        # Only send candidate pages to expensive table extraction, capped
        # (requirements #16/#22).
        text_pages = [p["page_number"] for p in relevant if p["pdf_type"] == "TEXT"]
        cap = self.cfg.processing.table_max_pages
        if len(text_pages) > cap:
            # Prefer statement-section pages first, then highest score.
            prio = sorted(
                relevant,
                key=lambda p: (p.get("section") in STATEMENT_KEYS, p.get("score", 0)),
                reverse=True,
            )
            text_pages = [p["page_number"] for p in prio[:cap] if p["pdf_type"] == "TEXT"]

        # Tables from text pages (batch to bound memory)
        tables_by_page: dict = {}
        for chunk_start in range(0, len(text_pages), 20):
            chunk = text_pages[chunk_start : chunk_start + 20]
            tables_by_page.update(
                extract_tables_from_file(
                    str(resolve_document_path(doc.file_path)), chunk,
                    preferred_year=doc.reporting_year))

        for p in relevant:
            section = p.get("section")
            if section not in STATEMENT_KEYS or p.get("is_parent_only"):
                section = None
            # Per-page stated unit: an MD&A page may say '(Rp miliar)' while
            # the primary statements are 'dalam jutaan' — using one document
            # unit for both corrupts one of them.
            page_unit_info = unit_info
            page_text = p["text"] or ""
            page_unit = detect_page_unit(page_text)
            if page_unit[0] and page_unit[1] != unit_info.multiplier:
                # A page may state its own unit ("dalam jutaan") when the
                # document-level unit belongs to the notes -- using one
                # multiplier for both corrupts whichever page it is wrong for.
                effective_unit, effective_multiplier = page_unit[0], page_unit[1]
            else:
                effective_unit, effective_multiplier = unit_info.unit, unit_info.multiplier

            # Cross-check the stated unit against the page's own numbers. A note
            # reading 'dalam ribuan' on a page whose figures are already
            # rupiah-scale would otherwise inflate correct values by 1,000x,
            # which then fails every identity check that spans the page.
            #
            # This runs for the document's own multiplier too, not only when the
            # page disagrees with it. A document-level 'juta' header is a claim,
            # and the page's figures are the evidence: trusting it uncritically
            # is what turned one printed figure into both 17,527,130,084 and
            # 17,527,130,084,000,000.
            multiplier, reason = correct_unit_multiplier(
                page_text, effective_multiplier)
            if reason:
                logger.debug("p%s: unit x%s rejected (%s)",
                             p["page_number"], effective_multiplier, reason)
            if multiplier != effective_multiplier or effective_unit != unit_info.unit:
                page_unit_info = _UI(
                    currency=unit_info.currency,
                    unit=effective_unit if multiplier != 1 else None,
                    multiplier=multiplier,
                    raw_snippet=f"page-unit:{effective_unit}",
                    confidence=0.9,
                )
            pt = tables_by_page.get(p["page_number"])
            rows = pt.rows if pt is not None else []
            if pt is None or not rows:
                if p["pdf_type"] == "SCANNED":
                    pt2 = parse_ocr_table_text(p["text"] or "",
                                               preferred_year=doc.reporting_year)
                    rows = pt2.rows
                    header_years = pt2.header_years
                else:
                    continue
            else:
                header_years = pt.header_years

            for cell in rows:
                fld, map_conf = map_label(cell.row_label, section)
                if fld is None:
                    # Preserve unmapped labeled values (requirement #4): stored
                    # alongside results with status UNMAPPED_FIELD, never an error.
                    if unmapped is not None:
                        for _yr, _raw in cell.values:
                            if not looks_like_number(_raw):
                                continue
                            try:
                                _parsed = parse_financial_number(_raw)
                            except NumberParseError:
                                continue
                            if _parsed is None:
                                continue
                            unmapped.append({
                                "company": doc.company,
                                "year": _yr or self._pick_year(doc, header_years),
                                "section": section,
                                "raw_label": cell.row_label,
                                "raw_value": _raw,
                                "value": _parsed,
                                "page": p["page_number"],
                            })
                    continue
                # Treasury shares: disambiguate quantity vs monetary vs %
                if fld == "treasury_shares_quantity" and cell.values:
                    fld = resolve_treasury_field(cell.values[0][1])
                statement = section or "balance_sheet"
                if section is None:
                    statement = self._statement_for_field(fld)
                for yr, raw in cell.values:
                    # Share quantities are stored unscaled, never unit-multiplied.
                    if fld == "treasury_shares_quantity":
                        qty = parse_share_quantity(raw)
                        if qty is None:
                            continue
                        conf = map_conf * 0.9
                        values_entry = {
                            "company": doc.company,
                            "year": yr or self._pick_year(doc, header_years),
                            "statement": "equity",
                            "field": fld,
                            "raw_label": cell.row_label,
                            "raw_value": raw,
                            "normalized_value": qty,
                            "currency": None,
                            "unit": "shares",
                            "page": p["page_number"],
                            "section": "equity",
                            "extraction_method": "table" if pt is not None else "ocr",
                            "confidence": round(min(conf, 0.95), 3),
                            "status": "OK",
                        }
                        add("equity", fld, values_entry)
                        continue
                    if not looks_like_number(raw):
                        continue
                    # Percentages are ratios: capture without unit scaling and
                    # without polluting the parse-failure log.
                    if is_percentage(raw):
                        # ...but only for a field that IS a percentage. A '%'
                        # token sitting next to a monetary row means the label
                        # matched the wrong column -- typically the ownership
                        # percentage printed beside an equity line. Storing it
                        # would assert 'total equity = 86 rupiah', and because
                        # `unit='percent'` exempts it from the monetary floors
                        # the value sailed through plausibility as `OK` and then
                        # outranked the real figure on confidence.
                        if not is_monetary(fld, None):
                            pct = parse_percentage(raw)
                            if pct is not None:
                                add(statement, fld, {
                                    "company": doc.company,
                                    "year": yr or self._pick_year(doc, header_years),
                                    "statement": statement,
                                    "field": fld,
                                    "raw_label": cell.row_label,
                                    "raw_value": raw,
                                    "normalized_value": pct,
                                    "currency": None,
                                    "unit": "percent",
                                    "page": p["page_number"],
                                    "section": section,
                                    "extraction_method": "table" if pt is not None else "ocr",
                                    "confidence": round(min(map_conf * 0.9, 0.95), 3),
                                    "status": "OK",
                                })
                            continue
                        logger.debug(
                            "Skipping percentage %r mapped to monetary field %r "
                            "(label matched the wrong column) on page %s",
                            raw, fld, p["page_number"],
                        )
                        continue
                    try:
                        parsed = parse_financial_number(raw)
                    except NumberParseError:
                        # OCR/table corruption fragments (e.g. '2c,2n', ',4',
                        # half-split '(520,193') are diagnostic info, not
                        # extraction failures worth surfacing as errors.
                        logger.debug(
                            "Skipping corrupted token %r for label %r on page %s",
                            raw, cell.row_label, p["page_number"],
                        )
                        continue
                    if parsed is None:
                        continue
                    conf = map_conf * 0.9
                    if p["pdf_type"] == "SCANNED":
                        ocr_conf = p.get("ocr_confidence") or 0.6
                        conf *= 0.5 + 0.5 * ocr_conf
                    # Plausibility guard against false unit detection: if the
                    # scaled value would exceed the global market-cap-scale
                    # ceiling (10^17 IDR) the multiplier is almost certainly
                    # wrong (e.g. narrative 'trillion' captured as report
                    # unit). Keep the raw magnitude instead of corrupting.
                    normalized = normalize_value(parsed, page_unit_info)
                    unit_out = page_unit_info.unit
                    # Only record a currency that was actually detected. Falling
                    # back to "IDR" would state as fact something that was never
                    # read, and a filter over the column would then report every
                    # document as rupiah -- including any that are not. An
                    # undetected currency stays NULL and shows as such.
                    currency_out = page_unit_info.currency
                    if abs(normalized) > 1e17:
                        normalized = parsed
                        unit_out = None
                        currency_out = unit_info.currency
                        conf *= 0.6
                    values_entry = {
                        "company": doc.company,
                        "year": yr or self._pick_year(doc, header_years),
                        "statement": statement,
                        "field": fld,
                        "raw_label": cell.row_label,
                        "raw_value": raw,
                        "normalized_value": normalized,
                        "currency": currency_out,
                        "unit": unit_out,
                        "page": p["page_number"],
                        "section": section,
                        "extraction_method": "table" if pt is not None else "ocr",
                        "confidence": round(min(conf, 0.95), 3),
                        "status": "OK",
                    }
                    if yr is not None and header_years:
                        values_entry["year_from_header"] = True
                    if conf < self.cfg.confidence.review_threshold:
                        values_entry["status"] = "REVIEW_REQUIRED"
                    add(statement, fld, values_entry)

    # ------------------------------------------------------------------ #
    def _ai_extraction(self, doc, pages, unit_info, year, add, force, result) -> None:
        relevant = [p for p in pages if p.get("is_relevant") or p.get("section") in STATEMENT_KEYS]
        if not relevant:
            return
        # Never let the AI read parent-only ("entitas induk") statements: they
        # are a separate reporting entity, so any figure it returns would
        # compete with the consolidated ones for the same (statement, field,
        # year) key. Excluding the pages is cheaper and more reliable than
        # trying to filter its output afterwards.
        relevant = [p for p in relevant if not p.get("is_parent_only")]
        if not relevant:
            return
        t0 = time.perf_counter()
        calls = 0
        # Batch relevant pages into windows of ~6 pages to bound token usage —
        # ONE structured request per window, never one per field (#19).
        window = 6
        for i in range(0, len(relevant), window):
            batch = relevant[i : i + window]
            content = "\n\n".join(
                f"=== PAGE {p['page_number']} ({p.get('section') or 'unclassified'}) ===\n{p['text']}"
                for p in batch
            )
            key = cache_key_for(content, self.cfg.ai.model, doc.company, doc.filename)
            cached = self.repo.ai_cache_get(key) if (self.cfg.ai.cache and not force) else None
            if cached:
                extraction = DocumentExtraction.model_validate(json.loads(cached))
                source = "ai-cache"
            else:
                extraction = self.ai.extract_structured(  # type: ignore[union-attr]
                    content=content,
                    filename=doc.filename,
                    company=doc.company,
                    year_hint=year,
                    unit_hint=unit_info.raw_snippet or "",
                    page_first=batch[0]["page_number"],
                    page_last=batch[-1]["page_number"],
                )
                calls += 1
                if self.cfg.ai.cache:
                    self.repo.ai_cache_put(key, extraction.model_dump_json())
                source = "ai"

            for stmt_key in STATEMENT_KEYS:
                stmt = getattr(extraction, stmt_key)
                for obs in stmt.observations:
                    if not obs.field:
                        continue
                    conf = float(obs.confidence)
                    entry = {
                        "company": extraction.company or doc.company,
                        "year": obs.year or year,
                        "statement": stmt_key,
                        "field": obs.field,
                        "raw_label": obs.raw_label,
                        "raw_value": obs.raw_value,
                        "normalized_value": obs.normalized_value,
                        "currency": obs.currency or unit_info.currency,
                        "unit": obs.unit or unit_info.unit,
                        "page": batch[0]["page_number"],
                        "section": stmt_key,
                        "extraction_method": source,
                        "confidence": round(conf, 3),
                        "status": "OK" if conf >= self.cfg.confidence.review_threshold else "REVIEW_REQUIRED",
                    }
                    # Treasury share quantities from AI: never unit-scale them.
                    if obs.field == "treasury_shares_quantity" and obs.raw_value:
                        qty = parse_share_quantity(obs.raw_value)
                        if qty is not None:
                            entry["normalized_value"] = qty
                            entry["currency"] = None
                            entry["unit"] = "shares"
                    if obs.normalized_value is not None and obs.raw_value and unit_info.multiplier > 1 \
                            and source == "ai" and obs.unit is None \
                            and obs.field != "treasury_shares_quantity":
                        try:
                            raw_num = parse_financial_number(obs.raw_value)
                            if raw_num is not None and abs(obs.normalized_value) < abs(raw_num):
                                entry["normalized_value"] = normalize_value(raw_num, unit_info)
                        except NumberParseError:
                            pass
                    add(stmt_key, obs.field, entry)
        result.metrics["ai_calls"] = result.metrics.get("ai_calls", 0) + calls
        result.metrics["ai_time"] = result.metrics.get("ai_time", 0.0) + (time.perf_counter() - t0)

    # ------------------------------------------------------------------ #
    def _statement_for_field(self, fld: str) -> str:
        from app.financial.mappings import FIELD_LABELS

        for stmt, fields in FIELD_LABELS.items():
            if fld in fields:
                return stmt
        return "balance_sheet"

    # A statement may present comparatives, but never the future. Indonesian
    # annual reports show at most ~10 prior years (5-year summaries, plus
    # restated figures), so anything outside this band is a misparse: a court
    # case number ('putusan Homologasi No. 121/Pdt'), a footnote reference or
    # a licence number read as a fiscal year. AISA's 2020 report otherwise
    # produced a 2029 balance sheet.
    _YEAR_LOOKBACK = 10

    def _plausible_year(self, yr: int | None, doc: Document) -> int | None:
        """Reject years outside [reporting_year - 10, reporting_year + 1]."""
        if yr is None:
            return None
        anchor = doc.reporting_year or year_from_filename(doc.filename)
        if not anchor:
            return yr
        if anchor - self._YEAR_LOOKBACK <= yr <= anchor + 1:
            return yr
        logger.debug(
            "Dropping implausible year %s for %s (reporting year %s)",
            yr, doc.filename, anchor,
        )
        return None

    def _pick_year(self, doc: Document, header_years: list[int]) -> int | None:
        """Fallback year when a value could not be zipped to a header column.

        The document's own reporting year wins over max(header_years). A
        statement printed side by side in Indonesian and English yields two
        pages for one statement whose headers read [2022, 2021]; max() picks
        2022 on one page and 2021 on the other, storing the same figure under
        two different years. The report's own period is unambiguous, so it is
        the correct fallback. Multi-year highlight tables are unaffected
        because their columns zip successfully and never reach here.
        """
        if doc.reporting_year:
            return doc.reporting_year
        if header_years:
            return max(header_years)
        return year_from_filename(doc.filename)

    def _average_confidence(self, values: list[dict]) -> float | None:
        confs = [v.get("confidence", 0) for v in values]
        return round(sum(confs) / len(confs), 3) if confs else None

    def _group_by_year(self, values: list[dict]) -> dict[int | None, dict]:
        """Group observations into {year: {statement: {field: value}}} for
        validation.

        Implausible amounts are excluded: they are misparses (a bare '1' left by
        an interleaved table column, or a note figure scaled by an incidental
        unit word), not measurements. Feeding them to the identity checks
        produced errors like `total_assets = 1`, which said nothing about the
        document and buried the real findings. They remain in the database and
        in the CSV, flagged.

        Where a field was observed more than once the best-supported value wins
        rather than whichever was extracted last; the old assignment silently
        let a late low-authority fragment overwrite a verified statement total.
        """
        out: dict[int | None, dict] = {}
        for v in values:
            if v.get("implausible"):
                continue
            yr = v.get("year")
            bucket = out.setdefault(yr, {}).setdefault(v["statement"], {})
            fld = v["field"]
            existing = bucket.get(fld)
            if existing is None or _value_rank(v) > _value_rank(existing):
                bucket[fld] = v
        return out

    @staticmethod
    def _worst(statuses: list[str]) -> str:
        order = ["VALID", "NOT_FOUND", "NOT_APPLICABLE", "SKIPPED", "WARNING", "REVIEW_REQUIRED", "ERROR"]
        return max(statuses, key=order.index) if statuses else "NOT_APPLICABLE"

    # ------------------------------------------------------------------ #
    def _write_unmapped(self, doc: Document, unmapped: list[dict]) -> None:
        """Persist unmapped label/value observations so no data is lost."""
        out_dir = self._extracted_dir(doc)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = [
            {**u, "status": "UNMAPPED_FIELD", "normalized_field": None} for u in unmapped
        ]
        (out_dir / "unmapped_fields.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )

    def _save_raw_pages(self, doc: Document, pages: list[dict]) -> None:
        out_dir = self.cfg.data_dir / "raw_text" / doc.company[:80]
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\w\-]+", "_", Path(doc.file_path).stem)[:80]
        payload = [
            {k: p.get(k) for k in ("page_number", "pdf_type", "section", "is_relevant", "score",
                                   "ocr_confidence")}
            for p in pages
        ]
        (out_dir / f"{slug}_{doc.id or 0}_pages.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def _write_raw(self, doc: Document, result: DocumentResult) -> None:
        out_dir = self._extracted_dir(doc)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "document": doc.file_path,
            "company": doc.company,
            "filename": doc.filename,
            "pdf_type": result.pdf_type,
            "ocr_used": result.ocr_used,
            "reporting_year": result.reporting_year,
            "avg_confidence": result.avg_confidence,
            "extraction_status": result.extraction_status,
            "validation_status": result.validation_status,
            "metrics": result.metrics,
            "text_pages": result.text_pages,
            "ocr_pages": result.ocr_pages,
            "financial_pages": result.financial_pages,
            "values": result.values,
            "validations": result.validations,
            "validation_breakdown": result.validation_breakdown,
            "extraction_errors": result.errors,
            "errors": result.errors,
        }
        (out_dir / "extraction.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
