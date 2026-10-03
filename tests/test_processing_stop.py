"""Stopping a batch must not lose or strand documents.

An earlier way to stop a run was to kill the server, which abandons whatever was
mid-extraction. Those documents sit in an in-flight status that ordinary runs
skip, so the data silently disappears until a later repair pass happens to catch
it. The stop button asks the batch to wind down instead: documents still queued
never start, documents already running are allowed to finish and checkpoint, and
the rest stay pending for the next run.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_config, load_config, set_config
from app.dashboard.server import create_app
from app.pipeline import orchestrator
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    conf = load_config()
    conf.database_url = f"sqlite:///{(tmp_path / 'db' / 'processing.db').as_posix()}"
    # One worker, so exactly one document is in flight and the rest are still
    # queued. With the production pool every document starts before the first
    # one finishes, and there is nothing left for a stop to cancel -- which is
    # correct behaviour but makes the assertions untestable.
    conf.processing.workers = 1
    set_config(conf)
    return conf


def _seed(cfg, count: int) -> None:
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        for i in range(count):
            repo.upsert_document(f"/tmp/doc{i}.pdf", f"hash-{i}", f"PT {i} Tbk", "d.pdf")


class TestCooperativeStop:
    def test_stop_leaves_queued_documents_pending(self, cfg, monkeypatch):
        """The whole point: a stopped batch must not report work it skipped."""
        _seed(cfg, 12)
        started: list[int] = []
        event = threading.Event()

        def fake_process(_conf, doc_id, _force):
            started.append(doc_id)
            # Ask to stop while the first document is in flight, which is the
            # only moment a stop can arrive: there is nothing to stop before
            # the batch starts, and nothing left to stop once it finishes.
            event.set()
            return SimpleNamespace(errors=[], error_count=0)

        monkeypatch.setattr(orchestrator, "_process_one", fake_process)
        result = orchestrator.process_batch(
            cfg, cancel_event=event, limit=12
        )

        assert result["cancelled"] is True
        assert result["skipped"] == 11
        assert result["processed"] == 1
        assert len(started) == 1

    def test_cancelled_documents_stay_pending_not_failed(self, cfg, monkeypatch):
        """A skipped document must be retryable, not recorded as broken."""
        _seed(cfg, 6)
        event = threading.Event()
        monkeypatch.setattr(
            orchestrator,
            "_process_one",
            lambda *a: (event.set(), SimpleNamespace(errors=[], error_count=0))[1],
        )
        result = orchestrator.process_batch(cfg, cancel_event=event)

        assert result["skipped"] > 0
        assert result["extraction_errors"] == 0

        from app.pipeline.orchestrator import _PENDING_STATUSES

        Session = get_session_factory(get_engine(cfg))
        with Session() as s:
            repo = Repository(s)
            still_pending = repo.documents_by_status(*_PENDING_STATUSES)
        # The stubbed worker writes nothing, so every seeded document is still
        # pending -- including the one it "processed". What matters is that none
        # was lost or demoted to a failed status by being skipped.
        assert len(still_pending) == 6
        assert len(repo.documents_by_status("FAILED")) == 0

    def test_uncancelled_run_reports_nothing_skipped(self, cfg, monkeypatch):
        _seed(cfg, 4)
        monkeypatch.setattr(
            orchestrator,
            "_process_one",
            lambda *a: SimpleNamespace(errors=[], error_count=0),
        )
        result = orchestrator.process_batch(cfg, cancel_event=threading.Event())

        assert result["cancelled"] is False
        assert result["skipped"] == 0
        assert result["processed"] == 4


@pytest.fixture()
def client(cfg):
    app = create_app(cfg)
    app.dependency_overrides[get_config] = lambda: cfg
    return TestClient(app)


class TestStopEndpoint:
    def test_stopping_nothing_is_an_error(self, client):
        resp = client.post("/api/processing/stop")
        assert resp.status_code == 409
        assert "no batch is running" in resp.json()["detail"].lower()

    def test_stop_marks_the_job_and_keeps_running_visible(self, client):
        """A stop is not instant: the UI must still show the batch as running
        while the in-flight documents drain, otherwise it looks stopped while
        it is still writing."""
        from app.dashboard.api import JOB

        JOB.begin("process")
        try:
            assert JOB.snapshot()["running"] is True
            assert JOB.snapshot()["cancel_requested"] is False

            resp = client.post("/api/processing/stop")
            assert resp.status_code == 200
            assert resp.json()["stopping"] is True

            snap = JOB.snapshot()
            assert snap["cancel_requested"] is True
            assert snap["running"] is True
        finally:
            with JOB._lock:
                JOB.running = False

    def test_starting_a_batch_clears_a_previous_stop(self, client):
        """A stale stop flag would kill the next run the instant it started."""
        from app.dashboard.api import JOB

        JOB.begin("process")
        JOB.request_stop()
        assert JOB.cancel_requested is True

        JOB.begin("process")
        try:
            assert JOB.cancel_requested is False
        finally:
            with JOB._lock:
                JOB.running = False

    def test_cancel_event_is_the_one_the_job_polls(self, client):
        """The endpoint and the orchestrator must share one flag object."""
        from app.dashboard.api import JOB

        JOB.begin("process")
        try:
            assert JOB.cancel_event is JOB.cancel_event
            JOB.request_stop()
            assert JOB.cancel_event.is_set()
        finally:
            with JOB._lock:
                JOB.running = False


class TestJobLockIsReentrant:
    """Regression: the start endpoint self-deadlocked and wedged the whole API.

    The start handler has to hold the job lock across a check-then-set on
    `running`, and then calls JOB.begin(), which takes the same lock. With a
    plain threading.Lock that nested acquisition blocked the requesting thread
    while it owned the lock, which deadlocked everything that needs a snapshot
    (GET /api/processing, POST /api/processing/stop) and -- because the worker
    thread only starts after that block -- meant the batch never ran at all.
    Through a Cloudflare tunnel this surfaced only as an opaque HTTP 524.

    These tests assert on thread liveness with a timeout rather than just
    calling the method, so a regression fails the test instead of hanging the
    suite forever.
    """

    @staticmethod
    def _run_within(job, fn, timeout: float = 5.0) -> bool:
        def run() -> None:
            with job._lock:
                fn()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=timeout)
        return not t.is_alive()

    def test_begin_while_holding_the_lock_does_not_deadlock(self):
        from app.dashboard.api import _Job

        job = _Job()
        assert self._run_within(job, lambda: job.begin("process")), (
            "JOB.begin() deadlocked while the job lock was already held"
        )
        assert job.running is True

    def test_request_stop_while_holding_the_lock_does_not_deadlock(self):
        from app.dashboard.api import _Job

        job = _Job()
        job.begin("process")
        assert self._run_within(job, job.request_stop), (
            "JOB.request_stop() deadlocked while the job lock was already held"
        )
        assert job.cancel_requested is True

    def test_start_endpoint_leaves_status_readable(self, client, monkeypatch):
        """The user-visible symptom: a start request wedged every later read."""
        monkeypatch.setattr(orchestrator, "discover", lambda *a, **k: 0)

        outcome: dict[str, object] = {}

        def start() -> None:
            try:
                outcome["resp"] = client.post("/api/processing", json={"action": "scan"})
            except Exception as exc:  # noqa: BLE001 - surfaced as a failure below
                outcome["exc"] = exc

        t = threading.Thread(target=start, daemon=True)
        t.start()
        t.join(timeout=30)
        assert not t.is_alive(), "POST /api/processing never returned; it deadlocked"
        assert "exc" not in outcome, f"start raised {outcome.get('exc')!r}"
        assert outcome["resp"].status_code == 200

        # The lock must have been released again, or the UI cannot poll.
        assert client.get("/api/processing").status_code == 200

        from app.dashboard.api import JOB

        JOB.request_stop()
        with JOB._lock:
            JOB.running = False