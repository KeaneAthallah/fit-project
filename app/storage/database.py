"""SQLite database engine/session management."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppConfig
from app.storage.models import Base

logger = logging.getLogger(__name__)

# Concurrency settings applied to EVERY new DBAPI connection. Pragmas are
# per-connection in SQLite — setting them once on a single pooled connection
# (the old approach) left other connections with busy_timeout=0, which made
# multi-worker batches fail with 'database is locked'.
SQLITE_BUSY_TIMEOUT_MS = 30_000


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    # NOTE: journal_mode=WAL is NOT set here — switching journal mode requires
    # an exclusive lock and fails under concurrency. WAL is persistent in the
    # DB file and set once in get_engine().
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

logger = logging.getLogger(__name__)

# Lightweight column migrations: (table, column, DDL type). Applied idempotently
# at startup so an existing processing.db keeps working after upgrades.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("documents", "text_pages", "INTEGER"),
    ("documents", "ocr_pages", "INTEGER"),
    ("documents", "financial_pages", "INTEGER"),
    ("documents", "metrics", "TEXT"),
    ("validation_results", "severity", "VARCHAR(16)"),
    ("validation_results", "category", "VARCHAR(32)"),
    ("validation_results", "evidence", "TEXT"),
    ("pages", "is_parent_only", "INTEGER DEFAULT 0"),
    # Manual corrections (human fixing a mis-extracted figure).
    ("extracted_values", "original_value", "REAL"),
    ("extracted_values", "original_method", "VARCHAR(64)"),
    ("extracted_values", "edited_at", "DATETIME"),
    ("extracted_values", "edit_note", "TEXT"),
    # Non-monetary line items (IDX subsector classification).
    ("extracted_values", "text_value", "TEXT"),
]

_INDEX_MIGRATIONS: list[tuple[str, str]] = [
    ("ix_documents_company_year", "CREATE INDEX IF NOT EXISTS ix_documents_company_year ON documents (company, reporting_year)"),
    ("ix_validation_status", "CREATE INDEX IF NOT EXISTS ix_validation_status ON validation_results (status)"),
    ("ix_validation_doc_check", "CREATE INDEX IF NOT EXISTS ix_validation_doc_check ON validation_results (document_id, check_name)"),
]


def _migrate(engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                logger.info("Migration: added %s.%s", table, column)
        for name, ddl in _INDEX_MIGRATIONS:
            conn.execute(text(ddl))
        conn.commit()


# One engine per database path — creating engines per worker call raced on
# create_all when many workers started simultaneously on a fresh DB.
_ENGINES: dict[str, Engine] = {}


def get_engine(cfg: AppConfig):
    db_path: Path = cfg.database_path
    url = f"sqlite:///{db_path.as_posix()}"
    if url in _ENGINES:
        return _ENGINES[url]

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    _migrate(engine)
    # WAL mode is persistent in the DB file; per-connection pragmas (busy
    # timeout, synchronous) are set by the connect-event listener above.
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.commit()
    _ENGINES[url] = engine
    return engine


def get_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
