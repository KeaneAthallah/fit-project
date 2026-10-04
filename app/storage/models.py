"""SQLAlchemy ORM models for processing tracking."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    company: Mapped[str] = mapped_column(String(512), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pdf_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # TEXT/SCANNED/HYBRID
    ocr_used: Mapped[int] = mapped_column(Integer, default=0)  # boolean-ish
    extraction_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reporting_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    financial_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON stage timings
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_documents_company_year", "company", "reporting_year"),
    )

    pages: Mapped[list["PageResult"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    values: Mapped[list["ExtractedValue"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    validations: Mapped[list["ValidationResult"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class PageResult(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    pdf_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # TEXT / SCANNED
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocr_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_relevant: Mapped[int] = mapped_column(Integer, default=0)
    # Parent-company-only ("entitas induk") statement, not the consolidated group.
    is_parent_only: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="pages")


class ExtractedValue(Base):
    __tablename__ = "extracted_values"
    __table_args__ = (UniqueConstraint("document_id", "field", "year", "statement", name="uq_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    company: Mapped[str] = mapped_column(String(512), index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    statement: Mapped[str] = mapped_column(String(32))  # balance_sheet / income_statement / cash_flow / equity
    field: Mapped[str] = mapped_column(String(64), index=True)
    raw_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Some line items are not amounts: an IDX subsector reads "D2. Food &
    # Beverage". Those rows carry the classification verbatim here and leave
    # normalized_value NULL, so a classification is never coerced to a number.
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(64))  # table | cover_text | pattern | ai | manual
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="OK")  # OK / REVIEW_REQUIRED
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # ---- manual correction trail -----------------------------------------
    # A human correcting a mis-extracted figure must not erase the pipeline's
    # own answer: this is a financial system, so the pre-edit number stays
    # readable and the row records who-when-why it changed. `edited_at` being
    # set is what marks the row as hand-corrected (there is no separate flag to
    # drift out of sync with it).
    original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edit_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[Document] = relationship(back_populates="values")


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    company: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_name: Mapped[str] = mapped_column(String(64))
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    difference: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32))  # VALID/WARNING/REVIEW_REQUIRED/ERROR/NOT_APPLICABLE/NOT_FOUND
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)  # INFO/WARNING/ERROR
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)  # accounting_mismatch/missing_fields/...
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON evidence blob

    document: Mapped[Document] = relationship(back_populates="validations")

    __table_args__ = (
        Index("ix_validation_status", "status"),
        Index("ix_validation_doc_check", "document_id", "check_name"),
    )


class AIExtractionCache(Base):
    __tablename__ = "ai_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExtractionCache(Base):
    """Persistent cache for page text / OCR / table results (requirement #18)."""

    __tablename__ = "extraction_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # page_text | ocr | tables
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
