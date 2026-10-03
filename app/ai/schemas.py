"""Pydantic schemas for AI extraction output.

The AI layer must return exactly these structures — anything else is a
validation failure and must be treated as REVIEW_REQUIRED, never guessed.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ValueObservation(BaseModel):
    """A single (field, year) observation."""

    model_config = ConfigDict(extra="forbid")

    field: str
    year: int | None = None
    raw_label: str | None = None
    raw_value: str | None = None
    normalized_value: float | None = None
    currency: str | None = None
    unit: str | None = None  # e.g. 'juta' for money; 'shares' for share counts
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: str | None = None


class StatementExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[ValueObservation] = Field(default_factory=list)


class DocumentExtraction(BaseModel):
    """Top-level AI extraction result for the relevant pages of a document."""

    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    reporting_year: int | None = None
    currency: str | None = None
    unit: str | None = None
    balance_sheet: StatementExtraction = Field(default_factory=StatementExtraction)
    income_statement: StatementExtraction = Field(default_factory=StatementExtraction)
    cash_flow: StatementExtraction = Field(default_factory=StatementExtraction)
    equity: StatementExtraction = Field(default_factory=StatementExtraction)
    unidentified_labels: list[str] = Field(default_factory=list)
