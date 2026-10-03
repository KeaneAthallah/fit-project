"""Data-access layer for the processing database."""
from __future__ import annotations

import functools
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.storage.models import (
    AIExtractionCache,
    Document,
    ExtractedValue,
    PageResult,
    ValidationResult,
)

# SQLite allows exactly ONE writer at a time. With 10+ worker threads, a long
# insert (300-page documents) can hold the write lock past any busy_timeout,
# surfacing as 'database is locked'. Workers spend their time on OCR/PDF work,
# not the DB — serializing commits process-wide costs nothing and eliminates
# the failure mode entirely.
_DB_WRITE_LOCK = threading.Lock()


def _serialized_write(fn):
    """Serialize an ENTIRE write transaction under the process-wide lock.

    The lock must span flush-through-commit: a bare commit-time lock would
    deadlock (thread A flushes -> holds SQLite write lock -> waits for process
    lock; thread B holds process lock -> commit waits on SQLite lock).
    """
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with _DB_WRITE_LOCK:
            return fn(self, *args, **kwargs)
    return wrapper


def sha256_of_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


# Extraction-only ranking hints (e.g. year_from_header) ride along on the value
# dicts to order competing observations. They are not columns, so they are
# filtered out before persistence.
_VALUE_COLUMNS = frozenset(ExtractedValue.__table__.columns.keys()) - {
    "id",
    "document_id",
}


class Repository:
    def __init__(self, session: Session):
        self.session = session

    # ---- documents -----------------------------------------------------
    @_serialized_write
    def upsert_document(self, file_path: str, file_hash: str, company: str, filename: str) -> tuple[Document, bool]:
        """Insert a discovered document; returns (doc, created)."""
        doc = self.session.scalar(select(Document).where(Document.file_path == file_path))
        if doc:
            return doc, False
        # Duplicate detection by hash (same content in another location).
        dup = self.session.scalar(
            select(Document).where(Document.file_hash == file_hash, Document.status != "FAILED")
        )
        if dup is not None:
            doc = Document(
                file_path=file_path,
                file_hash=file_hash,
                company=company,
                filename=filename,
                status="DUPLICATE",
                error_message=f"Duplicate of document id={dup.id} ({dup.file_path})",
            )
            self.session.add(doc)
            self.session.commit()
            return doc, True

        doc = Document(file_path=file_path, file_hash=file_hash, company=company, filename=filename)
        self.session.add(doc)
        self.session.commit()
        return doc, True

    def get_document(self, doc_id: int) -> Document | None:
        return self.session.get(Document, doc_id)

    def get_document_by_path(self, file_path: str) -> Document | None:
        return self.session.scalar(select(Document).where(Document.file_path == file_path))

    def documents_by_status(self, *statuses: str) -> list[Document]:
        stmt = select(Document).where(Document.status.in_(statuses)).order_by(Document.id)
        return list(self.session.scalars(stmt))

    def all_documents(self) -> list[Document]:
        return list(self.session.scalars(select(Document).order_by(Document.id)))

    def count_by_status(self) -> dict[str, int]:
        rows = self.session.execute(
            select(Document.status, func.count(Document.id)).group_by(Document.status)
        ).all()
        return {status: n for status, n in rows}

    def documents_with_status(self, statuses: list[str]) -> list[Document]:
        """Documents in any of the given statuses (used to recover interrupted runs)."""
        if not statuses:
            return []
        return list(
            self.session.scalars(
                select(Document).where(Document.status.in_(statuses))
                .order_by(Document.id)
            )
        )

    @_serialized_write
    def set_status(self, doc: Document, status: str, error_message: str | None = None) -> None:
        doc.status = status
        if error_message is not None:
            doc.error_message = error_message[:4000]
        self.session.commit()

    @_serialized_write
    def mark_processing(self, doc: Document) -> None:
        import datetime as dt

        doc.status = "PROCESSING"
        doc.started_at = dt.datetime.now(dt.timezone.utc)
        doc.error_message = None
        self.session.commit()

    @_serialized_write
    def mark_completed(self, doc: Document, processing_time: float | None = None) -> None:
        import datetime as dt

        doc.status = "COMPLETED"
        doc.completed_at = dt.datetime.now(dt.timezone.utc)
        if processing_time is not None:
            doc.processing_time = processing_time
        self.session.commit()

    @_serialized_write
    def mark_failed(self, doc: Document, error: str) -> None:
        import datetime as dt

        doc.status = "FAILED"
        doc.completed_at = dt.datetime.now(dt.timezone.utc)
        doc.error_message = error[:4000]
        self.session.commit()

    @_serialized_write
    def update_extract_meta(
        self,
        doc: Document,
        page_count: int | None = None,
        pdf_type: str | None = None,
        ocr_used: bool | None = None,
        reporting_year: int | None = None,
        avg_confidence: float | None = None,
        extraction_status: str | None = None,
        validation_status: str | None = None,
        text_pages: int | None = None,
        ocr_pages: int | None = None,
        financial_pages: int | None = None,
        metrics: str | None = None,
    ) -> None:
        if page_count is not None:
            doc.page_count = page_count
        if pdf_type is not None:
            doc.pdf_type = pdf_type
        if ocr_used is not None:
            doc.ocr_used = 1 if ocr_used else 0
        if reporting_year is not None:
            doc.reporting_year = reporting_year
        if avg_confidence is not None:
            doc.avg_confidence = avg_confidence
        if extraction_status is not None:
            doc.extraction_status = extraction_status
        if validation_status is not None:
            doc.validation_status = validation_status
        if text_pages is not None:
            doc.text_pages = text_pages
        if ocr_pages is not None:
            doc.ocr_pages = ocr_pages
        if financial_pages is not None:
            doc.financial_pages = financial_pages
        if metrics is not None:
            doc.metrics = metrics
        self.session.commit()

    @_serialized_write
    def reset_for_retry(self, doc: Document) -> None:
        doc.status = "DISCOVERED"
        doc.error_message = None
        doc.extraction_status = None
        doc.validation_status = None
        self.session.commit()

    # ---- pages ----------------------------------------------------------
    @_serialized_write
    def replace_pages(self, doc: Document, pages: list[dict[str, Any]]) -> None:
        doc.pages.clear()
        self.session.flush()
        for p in pages:
            doc.pages.append(PageResult(**p))
        self.session.commit()

    def get_pages(self, doc: Document) -> list[PageResult]:
        return list(self.session.scalars(
            select(PageResult).where(PageResult.document_id == doc.id).order_by(PageResult.page_number)
        ))

    # ---- extracted values ----------------------------------------------
    @_serialized_write
    def replace_values(self, doc: Document, values: list[dict[str, Any]]) -> None:
        """Replace all extracted values in a single transaction (batch insert).

        Hand corrections are carried across the replacement. Re-processing a
        document (`retry_failed`, `retry_review`, or a forced batch) rebuilds
        every value from scratch, so without this a human correction would be
        silently overwritten by the next retry -- losing the only copy of the
        right number. The correction is keyed on (statement, field, year),
        which is also the natural key of the table, so it reattaches to the row
        the extractor produced for that same observation.

        A hand-entered figure for a line the extractor never found has no such
        counterpart, so it is re-created from its own column values rather than
        reattached. It is snapshotted before the collection is cleared because
        the cleared children cannot be reused afterwards.
        """
        manual = {
            (v.statement, v.field, v.year): v
            for v in doc.values
            if v.edited_at is not None
        }
        # Snapshot, not a live reference: `doc.values.clear()` below is what
        # removes these rows, and an object pending deletion cannot be appended
        # back to the collection.
        manual_snapshot = {
            key: {"document_id": doc.id} | {c: getattr(v, c) for c in _VALUE_COLUMNS}
            for key, v in manual.items()
        }

        doc.values.clear()
        self.session.flush()
        # Bulk insert inside one transaction; a single commit per document,
        # not per row (requirement #23).
        rows = [ExtractedValue(**{k: v for k, v in row.items() if k in _VALUE_COLUMNS}) for row in values]

        for r in rows:
            prior = manual.get((r.statement, r.field, r.year))
            if prior is None:
                continue
            r.normalized_value = prior.normalized_value
            r.raw_value = prior.raw_value
            r.original_value = prior.original_value
            r.original_method = prior.original_method
            r.edited_at = prior.edited_at
            r.edit_note = prior.edit_note
            # The correction is now the authority for this observation, so the
            # row stops being a pipeline observation that a human reviewed.
            r.extraction_method = "manual"
            r.status = "OK"

        # Anything hand-entered that the extractor did not also produce is kept
        # as its own row. Dropping it would make "add a missing figure" the one
        # correction that a retry silently undoes.
        claimed = {(r.statement, r.field, r.year) for r in rows}
        for key, snapshot in manual_snapshot.items():
            if key not in claimed:
                rows.append(ExtractedValue(**snapshot))

        doc.values = rows
        self.session.commit()

    def all_values(self) -> list[ExtractedValue]:
        return list(self.session.scalars(select(ExtractedValue).order_by(ExtractedValue.id)))

    def values_for_document(self, doc: Document) -> list[ExtractedValue]:
        return list(self.session.scalars(select(ExtractedValue).where(ExtractedValue.document_id == doc.id)))

    def get_value(self, value_id: int) -> ExtractedValue | None:
        return self.session.get(ExtractedValue, value_id)

    @_serialized_write
    def apply_value_edit(
        self,
        value: ExtractedValue,
        normalized_value: float | None,
        raw_value: str | None = None,
        note: str | None = None,
    ) -> None:
        """Record a human correction to one extracted value.

        `original_value`/`original_method` keep the FIRST pre-edit state, so
        editing a row twice and then reverting returns to what the pipeline
        actually produced rather than to the intermediate correction. The
        method has to be preserved rather than guessed: `extraction_method` is
        reported in the Excel workbook, and writing back a plausible-looking
        'pattern' would fabricate provenance.
        """
        import datetime as dt

        if value.edited_at is None:
            value.original_value = value.normalized_value
            value.original_method = value.extraction_method
        value.normalized_value = normalized_value
        if raw_value is not None:
            value.raw_value = raw_value
        value.edit_note = note or None
        value.edited_at = dt.datetime.now(dt.timezone.utc)
        value.extraction_method = "manual"
        # A human has confirmed this figure, so it is no longer awaiting review.
        # `confidence` is deliberately left alone: it scores the extractor, and
        # inflating it would quietly improve the corpus-wide confidence metric
        # that the dashboard reports as pipeline quality.
        value.status = "OK"
        self.session.commit()

    @_serialized_write
    def revert_value_edit(self, value: ExtractedValue) -> None:
        """Undo a hand correction, restoring the extracted figure and method."""
        value.normalized_value = value.original_value
        value.raw_value = None
        if value.original_method is not None:
            value.extraction_method = value.original_method
        value.original_value = None
        value.original_method = None
        value.edited_at = None
        value.edit_note = None
        value.status = "OK"
        self.session.commit()

    # ---- validation ------------------------------------------------------
    @_serialized_write
    def replace_validations(self, doc: Document, results: list[dict[str, Any]]) -> None:
        doc.validations.clear()
        self.session.flush()
        for r in results:
            doc.validations.append(ValidationResult(**r))
        self.session.commit()

    def all_validations(self) -> list[ValidationResult]:
        return list(self.session.scalars(select(ValidationResult).order_by(ValidationResult.id)))

    # ---- AI cache --------------------------------------------------------
    def ai_cache_get(self, key: str) -> str | None:
        row = self.session.scalar(select(AIExtractionCache).where(AIExtractionCache.cache_key == key))
        return row.response_json if row else None

    @_serialized_write
    def ai_cache_put(self, key: str, response_json: str) -> None:
        exists = self.session.scalar(select(AIExtractionCache).where(AIExtractionCache.cache_key == key))
        if not exists:
            self.session.add(AIExtractionCache(cache_key=key, response_json=response_json))
            self.session.commit()

    def export_all_as_json(self) -> dict[str, Any]:
        """Serialize the whole DB state (used for processing_report.json)."""
        docs = self.all_documents()
        out = []
        for d in docs:
            out.append(
                {
                    "id": d.id,
                    "file_path": d.file_path,
                    "company": d.company,
                    "status": d.status,
                    "pdf_type": d.pdf_type,
                    "page_count": d.page_count,
                    "ocr_used": bool(d.ocr_used),
                    "reporting_year": d.reporting_year,
                    "avg_confidence": d.avg_confidence,
                    "extraction_status": d.extraction_status,
                    "validation_status": d.validation_status,
                    "processing_time": d.processing_time,
                    "error_message": d.error_message,
                }
            )
        return json.dumps(out, default=str) if False else {"documents": out}
