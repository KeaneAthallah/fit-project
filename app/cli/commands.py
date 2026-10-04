"""Command-line interface."""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table as RichTable

from app.core.config import get_config
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)

console = Console()


def _cfg():
    cfg = get_config()
    setup_logging(cfg.logs_dir)
    return cfg


@click.group()
def cli() -> None:
    """Finance Report Extractor — PDF financial statements to Excel."""


@cli.command()
@click.option("--input", "input_dir", default=None, help="Root directory containing company folders.")
@click.option("--limit", default=None, type=int, help="Only discover the first N PDFs (sample mode).")
def scan(input_dir: str | None, limit: int | None) -> None:
    """Discover all PDF files and register them in the processing database."""
    from app.pipeline.orchestrator import discover

    cfg = _cfg()
    if input_dir:
        from app.core.config import load_config, set_config

        cfg2 = load_config()
        cfg2.input_directory = Path(input_dir).resolve()
        set_config(cfg2)
        cfg = cfg2
    n = discover(cfg, limit=limit)
    console.print(f"[green]Registered {n} new documents.[/green]")


@cli.command()
@click.option("--limit", default=None, type=int, help="Process at most N documents (sample mode).")
@click.option("--workers", default=None, type=int, help="Override worker count.")
@click.option("--force", is_flag=True, help="Re-process even completed documents.")
def process(limit: int | None, workers: int | None, force: bool) -> None:
    """Process all pending discovered documents."""
    from app.core.config import set_config
    from app.pipeline.orchestrator import process_batch

    cfg = _cfg()
    if workers:
        cfg.processing.workers = workers
        set_config(cfg)
    result = process_batch(cfg, force=force, limit=limit)
    console.print(f"[green]Processed {result.get('processed', 0)}/{result.get('total', 0)} documents.[/green]")


@cli.command()
def export() -> None:
    """Generate the CSV reports + review queue + summary reports."""
    from app.export.csv_export import export_reports
    from app.export.reports import generate_reports, generate_review_queue, print_summary

    cfg = _cfg()
    counts = export_reports(cfg)
    review = generate_review_queue(cfg)
    summary = generate_reports(cfg)
    console.print(f"[green]CSV reports:[/green] {cfg.output_directory / 'reports'}")
    for name, n in counts.items():
        console.print(f"    {name:26s} {n:>7,d} rows")
    console.print(f"[green]Review queue:[/green] {review}")
    print_summary(summary)


@cli.command()
@click.option("--input", "input_dir", default=None, help="Root directory containing company folders.")
@click.option("--limit", default=None, type=int, help="Sample mode: only N PDFs.")
@click.option("--workers", default=None, type=int)
@click.option("--force", is_flag=True, help="Re-process everything, ignoring caches.")
@click.option("--mode", default=None, type=click.Choice(["fast", "balanced", "accurate"]),
              help="Processing mode: fast / balanced / accurate (default: balanced).")
def run(input_dir: str | None, limit: int | None, workers: int | None, force: bool,
        mode: str | None) -> None:
    """Complete pipeline: scan -> process -> export."""
    from app.core.config import load_config, set_config, _apply_mode
    from app.export.csv_export import export_reports
    from app.export.reports import generate_reports, generate_review_queue, print_summary
    from app.pipeline.orchestrator import discover, process_batch, print_performance_report

    cfg = _cfg()
    if input_dir:
        cfg = load_config()
        cfg.input_directory = Path(input_dir).resolve()
        set_config(cfg)
    if mode:
        cfg.processing.mode = mode
        _apply_mode(cfg)
        set_config(cfg)
    if workers:
        cfg.processing.workers = workers
        set_config(cfg)

    discover(cfg, limit=limit)
    batch = process_batch(cfg, force=force, limit=limit)
    export_reports(cfg)
    generate_review_queue(cfg)
    summary = generate_reports(cfg)
    print_summary(summary)
    print_performance_report(batch, cfg)


@cli.command()
def status() -> None:
    """Show processing status summary."""
    from app.pipeline.orchestrator import status_summary

    cfg = _cfg()
    s = status_summary(cfg)
    table = RichTable(title="Processing Status")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Companies", str(s["companies"]))
    table.add_row("Documents", str(s["documents"]))
    table.add_row("Pages", f"{s['pages']:,}")
    table.add_row("OCR documents", str(s["ocr_documents"]))
    avg = s.get("avg_confidence")
    table.add_row("Avg confidence", f"{avg * 100:.1f}%" if avg is not None else "-")
    for st, n in sorted(s["status_counts"].items()):
        table.add_row(f"  status: {st}", str(n))
    console.print(table)


@cli.command("remap-fields")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Actually rewrite the rows. Without this the command only reports.")
def remap_fields(apply_changes: bool) -> None:
    """Re-resolve every stored value's canonical field from its raw label.

    Mappings get corrected over time (labels were split, merged, or taught a
    new synonym). Rows already in the database keep whatever the mapping said on
    the day they were extracted, so a mapping fix does nothing until the
    documents are re-processed. This re-applies the current mappings to the
    stored `raw_label` instead of re-running OCR and extraction.

    Dry run by default: it reports every row whose field would change, grouped
    by transition, so the effect can be inspected before it is written.
    """
    from sqlalchemy import select

    from app.financial.mappings import map_label
    from app.storage.database import get_engine, get_session_factory
    from app.storage.models import ExtractedValue

    cfg = _cfg()
    engine = get_engine(cfg)
    Session = get_session_factory(engine)

    changes: dict[tuple[str, str], int] = {}
    skipped_unmapped = 0
    skipped_conflict = 0
    samples: dict[tuple[str, str], str] = {}

    with Session() as s:
        rows = list(s.scalars(select(ExtractedValue)))
        # The natural key is what a rename can collide with.
        occupied = {(r.document_id, r.field, r.year, r.statement) for r in rows}

        # Decided once, applied once: re-deciding at write time could disagree
        # with what was reported (two labels swapping fields, say) and silently
        # write something other than the preview.
        planned: list[tuple[ExtractedValue, str]] = []

        for v in rows:
            if not v.raw_label:
                skipped_unmapped += 1
                continue
            target, _ = map_label(v.raw_label, v.statement)
            if target is None or target == v.field:
                skipped_unmapped += 1
                continue
            key = (v.document_id, target, v.year, v.statement)
            if key in occupied:
                # Renaming would duplicate a row that already exists for this
                # observation. Leaving it alone is safer than guessing which of
                # the two is right.
                skipped_conflict += 1
                continue
            # Release this row's own key so a later row can legitimately take
            # it (A->B and B->A in the same document).
            occupied.discard((v.document_id, v.field, v.year, v.statement))
            occupied.add(key)
            planned.append((v, target))
            transition = (v.field, target)
            changes[transition] = changes.get(transition, 0) + 1
            samples.setdefault(transition, v.raw_label)

        if apply_changes and planned:
            for value, target in planned:
                value.field = target
            s.commit()

    table = RichTable(title="Field remap" + ("" if apply_changes else " (dry run)"))
    table.add_column("From")
    table.add_column("To")
    table.add_column("Rows", justify="right")
    table.add_column("Example raw label")
    for (src, dst), n in sorted(changes.items(), key=lambda kv: -kv[1]):
        table.add_row(src, dst, str(n), samples[(src, dst)])
    console.print(table)
    console.print(f"Unchanged or unmapped: {skipped_unmapped}")
    if skipped_conflict:
        console.print(f"[yellow]Skipped {skipped_conflict} row(s) that would collide with an existing value.[/yellow]")
    if changes and not apply_changes:
        console.print("[yellow]Nothing was written. Re-run with --apply to make these changes.[/yellow]")
    elif apply_changes:
        console.print(f"[green]Rewrote {sum(changes.values())} value(s).[/green]")


@cli.command("retry-failed")
def retry_failed() -> None:
    """Retry documents that previously failed."""
    from app.pipeline.orchestrator import retry_failed as rf

    cfg = _cfg()
    result = rf(cfg)
    console.print(f"[green]Retried {result.get('processed', 0)} failed documents.[/green]")


@cli.command("retry-review")
def retry_review() -> None:
    """Re-process documents flagged for review."""
    from app.pipeline.orchestrator import retry_review as rr

    cfg = _cfg()
    result = rr(cfg)
    console.print(f"[green]Re-processed {result.get('processed', 0)} review documents.[/green]")


@cli.command()
@click.argument("document_query")
def inspect(document_query: str) -> None:
    """Inspect a document by id, filename substring, or company substring."""
    from app.storage.database import get_engine, get_session_factory
    from app.storage.repository import Repository

    cfg = _cfg()
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = repo.all_documents()
        matches = [
            d for d in docs
            if document_query.lower() in Path(d.file_path).name.lower()
            or document_query.lower() in d.company.lower()
            or document_query == str(d.id)
        ]
        if not matches:
            console.print(f"[red]No documents matching {document_query!r}[/red]")
            return
        for d in matches[:10]:
            table = RichTable(title=f"#{d.id} {Path(d.file_path).name}")
            table.add_column("Field")
            table.add_column("Value")
            for k, v in [
                ("Company", d.company), ("Status", d.status), ("PDF type", d.pdf_type),
                ("Pages", d.page_count), ("OCR used", bool(d.ocr_used)),
                ("Reporting year", d.reporting_year), ("Avg confidence", d.avg_confidence),
                ("Extraction", d.extraction_status), ("Validation", d.validation_status),
                ("Duration", f"{d.processing_time:.1f}s" if d.processing_time else None),
                ("Error", d.error_message), ("Path", d.file_path),
            ]:
                table.add_row(str(k), str(v))
            console.print(table)
            values = repo.values_for_document(d)
            if values:
                vt = RichTable(title=f"{len(values)} extracted values")
                for col in ("Statement", "Field", "Year", "Value", "Conf", "Page", "Method"):
                    vt.add_column(col)
                for v in sorted(values, key=lambda x: (x.statement, x.field, str(x.year)))[:40]:
                    vt.add_row(v.statement, v.field, str(v.year),
                               f"{v.normalized_value:,.0f}" if v.normalized_value is not None else "-",
                               f"{v.confidence:.2f}", str(v.page), v.extraction_method)
                console.print(vt)


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option(
    "--reload",
    "reload_",
    is_flag=True,
    default=False,
    help="Restart the server when app/ changes, so backend edits need no manual restart.",
)
def dashboard(host: str, port: int, reload_: bool) -> None:
    """Launch the local web dashboard (optional; requires fastapi/uvicorn)."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]fastapi/uvicorn not installed. pip install fastapi uvicorn[/red]")
        return

    if reload_:
        _serve_with_watch(host, port)
        return

    from app.dashboard.server import create_app

    cfg = _cfg()
    uvicorn.run(create_app(cfg), host=host, port=port)


def _serve_with_watch(host: str, port: int) -> None:
    """Run the API in a child process and restart it when app/ changes.

    uvicorn's own reloader is not used here. On Windows it stops the worker with
    ``os.kill(pid, CTRL_C_EVENT)`` followed by a blocking ``process.join()``, and
    it only works when a console is attached: the event goes to the console, not
    to the handle, so a worker whose stdout is a log file never receives it and
    the join never returns. Since this launcher deliberately redirects output to
    logs/dashboard-api.log, that path hangs on the first edit. Supervising the
    child directly makes the restart a plain terminate-and-respawn, which behaves
    the same in a terminal and with redirected output.
    """
    import os
    import subprocess
    import threading

    try:
        from watchfiles import watch
    except ImportError:
        console.print(
            "[red]watchfiles is required for --reload. pip install watchfiles[/red]"
        )
        return

    root = Path.cwd()
    watch_dir = root / "app"
    if not watch_dir.is_dir():
        console.print(f"[red]no app/ directory under {root}; nothing to watch[/red]")
        return

    # A new process group keeps a console Ctrl+C aimed at this watcher from also
    # killing the worker: stopping is then always this loop's decision, so a
    # child that is mid-restart cannot be killed twice and orphaned.
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0

    def spawn() -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "app.cli.commands", "dashboard",
             "--host", host, "--port", str(port)],
            cwd=str(root),
            creationflags=creationflags,
        )

    stopping = threading.Event()
    child: subprocess.Popen | None = spawn()

    def stop_child(proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # A worker wedged in a request will not act on SIGTERM in time.
            proc.kill()
            proc.wait(timeout=5)

    try:
        for changes in watch(
            str(watch_dir),
            stop_event=stopping,
            # Editors save in bursts and a save often rewrites a sibling file;
            # coalescing first means one restart per save rather than several.
            debounce=500,
            step=50,
            watch_filter=lambda _change, path: path.endswith(".py"),
        ):
            if stopping.is_set():
                break
            assert child is not None
            if child.poll() is not None:
                # Crashed on its own. Respawning here would hide a real error
                # behind an endless crash loop, so report it and stop.
                console.print(
                    f"[red]server exited with code {child.returncode}; "
                    f"not watching for changes[/red]"
                )
                break
            if not changes:
                continue
            names = ", ".join(sorted({Path(c[1]).name for c in changes}))
            console.print(f"[cyan]changed: {names} -- restarting[/cyan]")
            stop_child(child)
            child = spawn()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        stop_child(child)


@cli.command("diagnose")
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--mode", default=None, type=click.Choice(["fast", "balanced", "accurate"]))
def diagnose(pdf_path: str, mode: str | None) -> None:
    """Deep-dive one PDF: page/OCR/AI breakdown, stage timings, validation summary."""
    from app.core.config import _apply_mode, set_config
    from app.pipeline.orchestrator import diagnose_document

    cfg = _cfg()
    if mode:
        cfg.processing.mode = mode
        _apply_mode(cfg)
        set_config(cfg)
    report = diagnose_document(cfg, pdf_path)

    table = RichTable(title=f"Diagnose: {Path(pdf_path).name}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    metrics = report.get("metrics", {})
    for label, key in [
        ("PDF pages", "page_count"),
        ("Text pages", "text_pages"),
        ("OCR pages", "ocr_pages"),
        ("Financial pages", "financial_pages"),
        ("AI calls", "ai_calls"),
        ("Extracted values", "values"),
    ]:
        table.add_row(label, str(report.get(key, 0) or 0))
    for stage in ("pdf_classification", "text_and_ocr", "page_classification",
                  "extraction", "validation", "total"):
        v = metrics.get(stage)
        if v is not None:
            table.add_row(f"Time: {stage}", f"{v:.1f}s")
    console.print(table)

    vt = RichTable(title="Validation")
    vt.add_column("Check")
    vt.add_column("Status")
    counts: dict[str, int] = {}
    for c in report.get("validations", []):
        vt.add_row(c.get("check_name", ""), str(c.get("status", "")))
        counts[c.get("status", "")] = counts.get(c.get("status", ""), 0) + 1
    console.print(vt)
    if counts:
        console.print(" ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    out = report.get("report_path")
    if out:
        console.print(f"[green]Full report:[/green] {out}")


@cli.command("diagnose-validation")
@click.argument("pdf_path", type=click.Path(exists=True))
def diagnose_validation(pdf_path: str) -> None:
    """Per-statement validation breakdown for one PDF (shows real error count)."""
    from app.pipeline.processor import DocumentProcessor
    from app.storage.database import get_engine, get_session_factory
    from app.storage.repository import Repository, sha256_of_file

    cfg = _cfg()
    p = Path(pdf_path).resolve()
    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        company = p.parent.name or "diagnose"
        doc, _ = repo.upsert_document(
            file_path=str(p), file_hash=sha256_of_file(p),
            company=company, filename=p.name,
        )
        from app.core.exceptions import AIProviderError
        ai = None
        try:
            from app.ai.base import create_extractor
            ai = create_extractor(cfg.ai)
        except AIProviderError:
            pass
        processor = DocumentProcessor(cfg, repo, ai)
        result = processor.process(doc, force=True)

    console.print("=" * 40)
    console.print("[bold]VALIDATION DIAGNOSTICS[/bold]")
    console.print("=" * 40)
    console.print(f"Document: {p.name}")
    console.print(f"Financial pages: {result.financial_pages}")
    console.print(f"Extracted values: {len(result.values)}")
    console.print(f"Unmapped values preserved: {result.metrics.get('unmapped_fields', 0)}")
    console.print()
    # Per-statement status histogram
    stmt_counts: dict[str, dict[str, int]] = {}
    for row in result.validations:
        stmt = _statement_for_check(row["check_name"])
        stmt_counts.setdefault(stmt, {})
        st = row["status"]
        stmt_counts[stmt][st] = stmt_counts[stmt].get(st, 0) + 1
    for stmt, counts in stmt_counts.items():
        console.print(f"[bold]{stmt}:[/bold]")
        for st, n in sorted(counts.items()):
            console.print(f"    {st}: {n}")
    real_errors = sum(1 for row in result.validations if row["status"] == "ERROR")
    warnings = sum(1 for row in result.validations if row["status"] == "WARNING")
    review = sum(1 for row in result.validations if row["status"] == "REVIEW_REQUIRED")
    low_conf = result.metrics.get("low_confidence_values", 0)
    console.print()
    console.print(f"Actual errors (accounting inconsistencies): [bold red]{real_errors}[/bold red]")
    console.print(f"Warnings: {warnings}")
    console.print(f"Review required (checks): {review}")
    console.print(f"Low-confidence values (review, not errors): {low_conf}")
    console.print(f"Extraction failures (pages/values unreadable): {len(result.errors)}")
    console.print("=" * 40)


def _statement_for_check(check_name: str) -> str:
    """Rough statement attribution for diagnostics display."""
    if "gross_profit" in check_name or "net_income" in check_name:
        return "Income Statement"
    if "cash" in check_name:
        return "Cash Flow"
    if "treasury" in check_name or "capital" in check_name:
        return "Equity"
    if check_name == "no_checks_possible":
        return "Document"
    return "Balance Sheet"


def main() -> None:
    """CLI entry point.

    Ctrl+C is a normal way to stop a long run, so it exits cleanly with a
    message and a non-zero code instead of dumping a KeyboardInterrupt
    traceback. Any document left mid-processing is reset by the next run's
    recovery step.
    """
    try:
        cli()
    except KeyboardInterrupt:
        print("\nInterrupted. Progress up to this point is saved; run the same "
              "command again to continue.", file=sys.stderr)
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("Unhandled error")
        print(f"\nError: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
