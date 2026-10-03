"""Batch orchestration: scanning, discovery, parallel processing, resume.

Architecture:
    Producer (scanner) -> task list -> ThreadPool workers -> SQLite (WAL).

Threads are used rather than processes because the heavy lifting (PyMuPDF,
OpenCV, Tesseract) releases the GIL, and SQLite dislikes multi-process writers.
Worker count is configurable (WORKERS / OCR_WORKERS).
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.ai.base import create_extractor
from app.core.config import AppConfig, get_config
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.ingestion.scanner import scan_directory
from app.pipeline.processor import DocumentProcessor, DocumentResult
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository, sha256_of_file

logger = get_logger(__name__)

__all__ = [
    "discover", "process_batch", "retry_failed", "retry_review",
    "status_summary", "diagnose_document", "print_performance_report",
]


def discover(cfg: AppConfig, limit: int | None = None) -> int:
    """Scan input dir, register PDFs in the DB (with duplicate detection)."""
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    files = scan_directory(cfg.input_directory, limit=limit)
    new = 0
    with Session() as session:
        repo = Repository(session)
        for f in files:
            try:
                file_hash = sha256_of_file(f.path)
            except OSError as exc:
                logger.error("Cannot hash %s: %s", f.path, exc)
                continue
            doc, created = repo.upsert_document(
                file_path=str(f.path), file_hash=file_hash, company=f.company, filename=f.filename
            )
            if created and doc.status == "DISCOVERED":
                new += 1
    logger.info("Discovery complete: %d files, %d newly registered", len(files), new)
    return new


_TRANSIENT_DB_MARKERS = (
    "database is locked", "database table is locked", "unable to open database file",
)


# Statuses a document passes through while it is being worked on. A run that is
# interrupted (Ctrl+C, a closed terminal, a crash) leaves documents parked in one
# of these, because a thread cannot run its own cleanup once the process dies.
# Nothing retries them: `process` only picks up DISCOVERED/FAILED, so they are
# stranded silently. recover_interrupted() resets them at the start of a run.
IN_FLIGHT_STATUSES = ("PROCESSING", "EXTRACTING", "OCR", "VALIDATING", "PARSING")


def recover_interrupted(cfg: AppConfig) -> list[int]:
    """Return documents stranded mid-processing to DISCOVERED.

    Called at the start of every batch. Without this a Ctrl+C mid-run silently
    loses those documents: they are neither completed nor failed, so the next
    run skips them and the report is quietly short.
    """
    try:
        Session = get_session_factory(get_engine(cfg))
        with Session() as session:
            repo = Repository(session)
            docs = repo.documents_with_status(list(IN_FLIGHT_STATUSES))
            ids = [d.id for d in docs]
            for doc in docs:
                repo.set_status(doc, "DISCOVERED")
        if ids:
            logger.warning(
                "Recovered %d document(s) left mid-processing by an interrupted "
                "run: %s", len(ids), ", ".join(str(i) for i in ids[:20]))
        return ids
    except Exception:
        logger.error("Could not recover interrupted documents", exc_info=True)
        return []


def _release_in_flight(doc_ids: list[int]) -> None:
    """Best-effort reset of documents a forced exit left mid-processing.

    Uses the config the batch is already running under, so no global lookup is
    needed.
    """
    if not doc_ids:
        return
    try:
        Session = get_session_factory(get_engine(get_config()))
        with Session() as session:
            repo = Repository(session)
            wanted = set(doc_ids)
            for doc in repo.documents_with_status(list(IN_FLIGHT_STATUSES)):
                if doc.id in wanted:
                    repo.set_status(doc, "DISCOVERED")
    except Exception:
        pass


def _is_transient_db_error(exc: BaseException) -> bool:
    """True for SQLite contention errors worth an automatic retry.

    SQLAlchemy wraps OperationalError into richer exceptions, so match on
    message text rather than exception type.
    """
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_DB_MARKERS)


def _mark_failed_cleanly(cfg: AppConfig, doc_id: int, exc: BaseException) -> None:
    """Record a worker failure on a fresh session, storing the real error text
    instead of a generic placeholder, so `retry-failed` triage is possible."""
    msg = f"{type(exc).__name__}: {exc}"[:500]
    try:
        Session = get_session_factory(get_engine(cfg))
        with Session() as session:
            repo = Repository(session)
            doc = repo.get_document(doc_id)
            if doc is not None:
                repo.mark_failed(doc, msg)
    except Exception:
        logger.error("Could not mark document %d as FAILED", doc_id, exc_info=True)


def _process_one(cfg: AppConfig, doc_id: int, force: bool,
                 attempts: int = 2) -> DocumentResult | None:
    """Worker entry point with one automatic retry for transient DB errors.

    Each attempt gets a fresh session/engine + AI extractor, so a poisoned
    session can never leak into the retry. Only SQLite contention errors
    ('database is locked' etc.) are retried; anything else fails immediately
    with the real error recorded.
    """
    for attempt in range(1, attempts + 1):
        try:
            return _process_one_attempt(cfg, doc_id, force)
        except Exception as exc:
            if attempt < attempts and _is_transient_db_error(exc):
                delay = 2 * attempt
                logger.warning(
                    "Transient database error on document id=%d (attempt %d/%d) — "
                    "retrying in %ds: %s", doc_id, attempt, attempts, delay, exc)
                time.sleep(delay)
                continue
            _mark_failed_cleanly(cfg, doc_id, exc)
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


def _process_one_attempt(cfg: AppConfig, doc_id: int, force: bool) -> DocumentResult | None:
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        doc = repo.get_document(doc_id)
        if doc is None:
            return None
        if doc.status == "COMPLETED" and not force:
            return None
        ai = None
        try:
            ai = create_extractor(cfg.ai)
        except AIProviderError as exc:
            logger.debug("AI extractor unavailable: %s", exc)
        processor = DocumentProcessor(cfg, repo, ai)
        return processor.process(doc, force=force)


class _KeepAwake:
    """Stop Windows from sleeping while a batch runs (no-op on other OSes).

    A ~2h batch is exactly the kind of run that gets killed by an idle
    timeout. ES_SYSTEM_REQUIRED blocks system sleep but still lets the
    display turn off.
    """

    def __enter__(self) -> "_KeepAwake":
        self._active = False
        if sys.platform == "win32":
            try:
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                if ctypes.windll.kernel32.SetThreadExecutionState(
                        ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
                    self._active = True
            except Exception:  # never let this break a batch
                logger.debug("Could not set keep-awake state", exc_info=True)
        return self

    def __exit__(self, *exc) -> None:
        if self._active:
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS
            except Exception:
                pass


class _RichLogHandler(logging.Handler):
    """Render WARNING+ log records as clean styled lines above the live
    progress bar, instead of letting raw stderr writes tear through it."""

    _STYLE = {"WARNING": "yellow", "ERROR": "bold red", "CRITICAL": "bold red"}

    def __init__(self, progress):
        super().__init__(level=logging.WARNING)
        self._progress = progress
        self.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            from rich.markup import escape
            msg = escape(self.format(record))
            style = self._STYLE.get(record.levelname, "white")
            self._progress.console.print(f"[{style}]{msg}[/]")
        except Exception:
            pass


def _quiet_stderr_logging():
    """Raise the stderr console log handler to ERROR while the progress bar is
    up (INFO lines would mangle it). Returns (handler, previous_level)."""
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr:
            prev = h.level
            h.setLevel(logging.ERROR)
            return h, prev
    return None, None


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds}s"


_PENDING_STATUSES = ("DISCOVERED", "PROCESSING", "OCR", "EXTRACTING", "VALIDATING")
# `--force` means "re-process everything", so terminal states become eligible too.
_FORCE_STATUSES = _PENDING_STATUSES + ("COMPLETED", "REVIEW_REQUIRED", "FAILED")


def process_batch(cfg: AppConfig, force: bool = False, limit: int | None = None,
                  statuses: tuple[str, ...] | None = None,
                  cancel_event: threading.Event | None = None) -> dict:
    """Process pending documents with a configurable worker pool.

    REVIEW_REQUIRED is intentionally NOT auto-reprocessed: review documents are
    COMPLETED extractions awaiting human attention, not failures. Re-queuing
    them caused an infinite processing loop. Use `retry-review` to redo them
    explicitly. An explicit ``force`` (CLI `--force`) does re-queue them, since
    the operator asked for a full redo.

    ``cancel_event`` requests a cooperative stop, which is what the dashboard's
    stop button sets. Queued documents are cancelled outright and the ones
    already running are allowed to finish, so stopping never strands a document
    in an in-flight status the way killing the process does.
    """
    if statuses is None:
        statuses = _FORCE_STATUSES if force else _PENDING_STATUSES
    # A previous run may have been interrupted, stranding documents in an
    # in-flight status that nothing retries. Reset them first so this run
    # picks them up instead of silently skipping them.
    recover_interrupted(cfg)
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = repo.documents_by_status(*statuses)
    if limit:
        docs = docs[:limit]
    if not docs:
        logger.info("No documents pending processing")
        return {"total": 0}

    workers = max(1, cfg.processing.workers)
    logger.info("Processing %d documents with %d workers", len(docs), workers)
    t0 = time.time()
    done = 0
    failed = 0
    warned = 0
    errors_total = 0
    validation_errors_total = 0

    use_bar = sys.stderr.isatty()

    # Documents cancelled before they started. Tracked so the final summary can
    # say plainly how much of the batch was left unprocessed.
    skipped = 0
    stop_announced = False

    def _stop_requested() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _finish_one(d, res, exc=None):
        """Shared completion handling: logging + counters. Returns True on success."""
        nonlocal errors_total, validation_errors_total, failed, warned
        if exc is not None:
            failed += 1
            # exc_info logs the full traceback to errors.log so crashes are
            # diagnosable after the fact.
            logger.error("Worker crashed on %s", d.file_path, exc_info=exc)
            return False
        if res and res.errors:
            errors_total += len(res.errors)
            logger.warning(
                "Document %s had %d extraction errors (pages/values that could not be read)",
                d.filename, len(res.errors))
        if res and res.error_count:
            warned += 1
            validation_errors_total += res.error_count
            logger.warning(
                "Document %s: %d validation ERROR(s) (accounting inconsistencies)",
                d.filename, res.error_count)
        return True

    def _run_pool(progress_cb=None):
        nonlocal done, skipped, stop_announced
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_process_one, cfg, d.id, force): d for d in docs}
            try:
                for fut in as_completed(futures):
                    d = futures[fut]
                    if fut.cancelled():
                        # Stopped before this document ever started. It is not a
                        # failure and not progress; it stays pending for the
                        # next run.
                        skipped += 1
                        continue
                    try:
                        res = fut.result()
                        _finish_one(d, res)
                    except Exception as exc:
                        _finish_one(d, None, exc)
                    done += 1
                    if progress_cb:
                        progress_cb(d)

                    if not stop_announced and _stop_requested():
                        # Cancel everything still queued, then keep draining so
                        # the documents already running finish and checkpoint
                        # cleanly instead of being stranded mid-extraction.
                        queued = [f for f in futures if f.cancel()]
                        stop_announced = True
                        in_flight = sum(
                            1 for f in futures
                            if not f.done() and not f.cancelled()
                        )
                        logger.warning(
                            "Stop requested: cancelled %d queued document(s), "
                            "waiting for %d in-flight to finish.",
                            len(queued), in_flight,
                        )
            except KeyboardInterrupt:
                # Ctrl+C: stop handing out new work. cancel() only affects
                # tasks that have not started, so anything already running is
                # left to finish here; a second Ctrl+C breaks out of that wait
                # and strands it, which is what recover_interrupted() repairs on
                # the next run.
                pending = [f for f in futures if not f.done()]
                for f in pending:
                    f.cancel()
                logger.warning(
                    "Interrupted: cancelled %d queued document(s), waiting for "
                    "%d in-flight to finish. Press Ctrl+C again to exit now.",
                    len(pending), sum(1 for f in pending if not f.cancelled()))
                try:
                    for f in pending:
                        f.cancel()
                        try:
                            f.result()
                        except BaseException:
                            pass
                        done += 1
                except KeyboardInterrupt:
                    still_running = [
                        futures[f].id for f in pending
                        if not f.done() and not f.cancelled()
                    ]
                    _release_in_flight(still_running)
                    logger.warning(
                        "Forced exit. %d document(s) were mid-processing; they "
                        "will be picked up again on the next run.",
                        len(still_running))
                    raise
                raise

    console = None
    with _KeepAwake():
        try:
            if use_bar:
                rich_handler = None
                quiet = (None, None)
                try:
                    from rich.console import Console
                    from rich.progress import (
                        BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
                        TextColumn, TimeElapsedColumn,
                    )

                    console = Console(stderr=True)
                    progress = Progress(
                        SpinnerColumn(),
                        TextColumn("[bold cyan]Extracting"),
                        BarColumn(bar_width=34, complete_style="cyan",
                                  finished_style="green"),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        TextColumn("[dim]{task.fields[eta]}"),
                        TextColumn("{task.fields[stats]}"),
                        console=console,
                    )
                    rich_handler = _RichLogHandler(progress)
                    logging.getLogger().addHandler(rich_handler)
                    quiet = _quiet_stderr_logging()

                    with progress:
                        task_id = progress.add_task(
                            "Extracting", total=len(docs), eta="", stats="")

                        def _stats_markup():
                            return (f"  [green]ok {done - warned - failed}[/]"
                                    f" · [yellow]warn {warned}[/]"
                                    f" · [red]fail {failed}[/]")

                        def cb(d):
                            elapsed = time.time() - t0
                            rate = done / elapsed if elapsed > 0 else 0
                            remaining = len(docs) - done
                            eta = f"~{remaining / rate / 60:.0f} min left" if rate > 0 else ""
                            progress.update(task_id, advance=1, eta=eta,
                                            stats=_stats_markup())

                        _run_pool(progress_cb=cb)
                except ImportError:  # rich missing
                    _run_pool()
                finally:
                    if rich_handler is not None:
                        logging.getLogger().removeHandler(rich_handler)
                    if quiet[0] is not None:
                        quiet[0].setLevel(quiet[1])
            else:
                last_logged = 0

                def cb(d):
                    nonlocal last_logged
                    elapsed = time.time() - t0
                    pct = int(done * 100 / len(docs)) if docs else 0
                    if pct >= last_logged + 10 or done == len(docs):  # log every 10%
                        last_logged = pct
                        rate = done / elapsed if elapsed > 0 else 0
                        remaining = (len(docs) - done) / rate / 60 if rate > 0 else 0
                        logger.info("Progress: %d/%d (%d%%) — %.1f docs/min, ~%.0f min left",
                                    done, len(docs), pct, rate * 60, remaining)

                _run_pool(progress_cb=cb)
        except KeyboardInterrupt:
            elapsed = time.time() - t0
            logger.warning(
                "Batch interrupted by user: %d/%d done in %.0fs. In-flight "
                "documents finished and were checkpointed; the rest stay "
                "pending. Run 'python main.py run' to resume.",
                done, len(docs), elapsed)
            print(f"\nInterrupted: {done}/{len(docs)} done. "
                  f"Run 'python main.py run' to resume.")
            return {"total": len(docs), "processed": done, "elapsed": elapsed,
                    "interrupted": True,
                    "extraction_errors": errors_total,
                    "validation_errors": validation_errors_total}

    elapsed = time.time() - t0

    if console is not None:
        from rich.rule import Rule
        console.print()
        console.print(Rule("[bold]Batch summary[/]", style="dim"))
        if skipped:
            console.print(
                f"  [yellow]Stopped early: {skipped} document(s) left pending "
                f"and will be picked up by the next run.[/]")
        if elapsed > 0:
            console.print(
                f"  Documents         : [bold]{done}/{len(docs)}[/] in "
                f"{_fmt_duration(elapsed)} ({done / elapsed * 60:.1f} docs/min)")
        console.print(
            f"  Clean             : [green]{done - warned - failed}[/]"
            f"   ·   Warnings : [yellow]{warned}[/]"
            f"   ·   Failed : [red]{failed}[/]")
        console.print(
            f"  Extraction issues : {errors_total}   ·   "
            f"Validation errors : {validation_errors_total}")
        if failed:
            console.print("  [red]Run 'python main.py retry-failed' to reprocess the "
                          "failed documents.[/]")
        console.print()

    logger.info("Batch complete: %d/%d documents in %.1fs (%.1f docs/min) | "
                "extraction errors: %d | validation errors: %d",
                done, len(docs), elapsed, done / elapsed * 60 if elapsed else 0,
                errors_total, validation_errors_total)
    return {"total": len(docs), "processed": done, "elapsed": elapsed,
            "skipped": skipped,
            "cancelled": bool(stop_announced),
            "extraction_errors": errors_total,
            "validation_errors": validation_errors_total}


def diagnose_document(cfg: AppConfig, pdf_path: str) -> dict:
    """Process a single PDF and return a detailed diagnostic report (req #29)."""
    import json
    import uuid
    from pathlib import Path as _Path

    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    p = _Path(pdf_path).resolve()
    file_hash = sha256_of_file(p)

    with Session() as session:
        repo = Repository(session)
        company = p.parent.name or "diagnose"
        doc, _ = repo.upsert_document(
            file_path=str(p), file_hash=file_hash, company=company, filename=p.name
        )
        ai = None
        try:
            ai = create_extractor(cfg.ai)
        except AIProviderError as exc:
            logger.debug("AI extractor unavailable: %s", exc)
        processor = DocumentProcessor(cfg, repo, ai)
        result = processor.process(doc, force=True)

    metrics = result.metrics
    report = {
        "file": str(p),
        "page_count": result.page_count,
        "text_pages": result.text_pages,
        "ocr_pages": result.ocr_pages,
        "financial_pages": result.financial_pages,
        "ai_calls": metrics.get("ai_calls", 0),
        "values": len(result.values),
        "metrics": metrics,
        "validations": result.validations,
    }
    out = cfg.output_directory / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{p.stem[:60]}_{uuid.uuid4().hex[:8]}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def print_performance_report(batch_result: dict, cfg: AppConfig) -> None:
    """Print actual processing speed metrics (requirement #30)."""
    elapsed = batch_result.get("elapsed", 0) or 0
    total = batch_result.get("total", 0) or 0
    docs_per_min = (total / elapsed * 60) if elapsed > 0 else 0
    logger.info(
        "Performance: %d docs in %.1fs (%.2f docs/min, mode=%s, workers=%d)",
        total, elapsed, docs_per_min, cfg.processing.mode, cfg.processing.workers,
    )
    print()
    print("PERFORMANCE")
    print(f"  Documents       : {total} in {elapsed:.1f}s")
    if elapsed > 0:
        print(f"  Throughput      : {docs_per_min:.2f} documents/minute")
    print(f"  Mode            : {cfg.processing.mode}")
    print(f"  Workers         : {cfg.processing.workers}")


def retry_failed(cfg: AppConfig) -> dict:
    return process_batch(cfg, force=True, statuses=("FAILED",))


def retry_review(cfg: AppConfig) -> dict:
    return process_batch(cfg, force=True, statuses=("REVIEW_REQUIRED",))


def status_summary(cfg: AppConfig) -> dict:
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        counts = repo.count_by_status()
        docs = repo.all_documents()
    companies = {d.company for d in docs}
    pages = sum(d.page_count or 0 for d in docs)
    confs = [d.avg_confidence for d in docs if d.avg_confidence is not None]
    return {
        "companies": len(companies),
        "documents": len(docs),
        "pages": pages,
        "status_counts": counts,
        "ocr_documents": sum(1 for d in docs if d.ocr_used),
        "avg_confidence": round(sum(confs) / len(confs), 4) if confs else None,
    }
