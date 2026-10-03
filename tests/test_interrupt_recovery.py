"""Ctrl+C must not silently lose documents.

Stopping a long run is routine. Before this, a Ctrl+C (or a closed terminal, or
a crash) left documents parked in an in-flight status - PROCESSING, EXTRACTING,
OCR, VALIDATING. Nothing retries those: `process` only picks up DISCOVERED and
FAILED, so the documents were stranded and every later report was quietly short.
An interrupted run really did strand 10 documents here.
"""
import pytest

from app.core.config import load_config, set_config
from app.pipeline.orchestrator import (
    IN_FLIGHT_STATUSES,
    _release_in_flight,
    recover_interrupted,
)
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Temp project workspace with one PDF and a fresh database."""
    import pymupdf

    input_dir = tmp_path / "input" / "PT ABC Indonesia"
    input_dir.mkdir(parents=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 720), "PT ABC INDONESIA\nLAPORAN KEUANGAN 2024")
    doc.save(str(input_dir / "laporan_2024.pdf"))
    doc.close()

    cfg = load_config()
    cfg.input_directory = tmp_path / "input"
    cfg.output_directory = tmp_path / "output"
    cfg.database_url = f"sqlite:///{(tmp_path / 'db' / 'processing.db').as_posix()}"
    cfg.processing.workers = 1
    cfg.processing.raw_data_directory = str(tmp_path / "data")
    set_config(cfg)
    yield cfg
    set_config(load_config())


@pytest.fixture()
def cfg(workspace):
    return workspace


def _statuses(cfg):
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        return Repository(s).count_by_status()


def _force_status(cfg, doc_id, status):
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        repo.set_status(repo.get_document(doc_id), status)


@pytest.mark.parametrize("status", IN_FLIGHT_STATUSES)
def test_every_in_flight_status_is_recovered(cfg, status):
    """Each status a document can be parked in must be reset."""
    from app.pipeline.orchestrator import discover

    discover(cfg)
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        doc_id = Repository(s).all_documents()[0].id

    _force_status(cfg, doc_id, status)
    assert _statuses(cfg).get(status) == 1

    ids = recover_interrupted(cfg)

    assert doc_id in ids
    assert _statuses(cfg).get(status) is None
    assert _statuses(cfg).get("DISCOVERED") == 1


def test_completed_documents_are_untouched(cfg):
    from app.pipeline.orchestrator import discover

    discover(cfg)
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        doc_id = Repository(s).all_documents()[0].id

    _force_status(cfg, doc_id, "COMPLETED")
    before = _statuses(cfg)

    recover_interrupted(cfg)

    assert _statuses(cfg) == before


def test_failed_documents_are_untouched(cfg):
    """FAILED is a real outcome that retry-failed depends on."""
    from app.pipeline.orchestrator import discover

    discover(cfg)
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        doc_id = Repository(s).all_documents()[0].id

    _force_status(cfg, doc_id, "FAILED")
    before = _statuses(cfg)

    recover_interrupted(cfg)

    assert _statuses(cfg) == before


def test_recovery_is_idempotent(cfg):
    from app.pipeline.orchestrator import discover

    discover(cfg)
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        doc_id = Repository(s).all_documents()[0].id

    _force_status(cfg, doc_id, "OCR")
    assert len(recover_interrupted(cfg)) == 1
    assert recover_interrupted(cfg) == []
    assert _statuses(cfg).get("DISCOVERED") == 1


def test_release_in_flight_targets_only_the_named_documents(cfg):
    """Only the documents a forced exit names are reset; the rest keep their
    in-flight state so a genuinely running batch is not disturbed."""
    from app.pipeline.orchestrator import discover

    import pymupdf
    second = cfg.input_directory / "PT DEF Indonesia"
    second.mkdir(parents=True)
    d = pymupdf.open()
    d.new_page().insert_text((72, 720), "PT DEF INDONESIA 2024")
    d.save(str(second / "laporan_2024.pdf"))
    d.close()

    discover(cfg)
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        ids = [doc.id for doc in Repository(s).all_documents()]
    assert len(ids) >= 2, "need two documents for this check"

    for doc_id in ids:
        _force_status(cfg, doc_id, "EXTRACTING")

    _release_in_flight([ids[0]])

    remaining = _statuses(cfg)
    assert remaining.get("DISCOVERED") == 1
    assert remaining.get("EXTRACTING") == len(ids) - 1


def test_release_in_flight_with_empty_list_is_a_noop(cfg):
    from app.pipeline.orchestrator import discover

    discover(cfg)
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        doc_id = Repository(s).all_documents()[0].id

    _force_status(cfg, doc_id, "OCR")
    before = _statuses(cfg)

    _release_in_flight([])

    assert _statuses(cfg) == before


def test_recovery_never_raises_on_missing_tables(cfg):
    """A fresh database must not make the recovery step fatal."""
    # No scan: the table exists but is empty.
    assert recover_interrupted(cfg) == []


class TestCliInterruptExit:
    def test_keyboard_interrupt_exits_130_without_traceback(self, monkeypatch, capsys):
        from app.cli import commands

        def boom():
            raise KeyboardInterrupt

        monkeypatch.setattr(commands, "cli", boom)
        with pytest.raises(SystemExit) as exc:
            commands.main()
        assert exc.value.code == 130
        err = capsys.readouterr().err
        assert "Interrupted" in err
        assert "Traceback" not in err

    def test_unexpected_error_exits_1(self, monkeypatch):
        from app.cli import commands

        def boom():
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(commands, "cli", boom)
        with pytest.raises(SystemExit) as exc:
            commands.main()
        assert exc.value.code == 1

    def test_systemexit_passes_through(self, monkeypatch):
        """click uses SystemExit for --help and usage errors; it must not be
        rewritten to 1."""
        from app.cli import commands

        def boom():
            raise SystemExit(0)

        monkeypatch.setattr(commands, "cli", boom)
        with pytest.raises(SystemExit) as exc:
            commands.main()
        assert exc.value.code == 0

    def test_clean_exit_is_untouched(self, monkeypatch):
        from app.cli import commands

        monkeypatch.setattr(commands, "cli", lambda: None)
        assert commands.main() is None

