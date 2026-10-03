"""Hand corrections of extracted values must be safe and durable.

The extractor is conservative but it does misparse amounts (the known failure
is a 1000x scale slip on the highlights page). Correcting such a value by hand
is the fix, and it was impossible before this endpoint existed.

Two things make that safe, and both are tested here:

1. The correction never destroys the extractor's own answer. `original_value`
   and `original_method` survive so the row can be reverted and an auditor can
   see what changed.
2. The correction survives re-processing. `retry_failed` / `retry_review` call
   `process(force=True)`, which rebuilds every value from scratch -- if the
   hand fix were not carried across, the next retry would silently restore the
   wrong number and the user would have no way to tell.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_config, load_config, set_config
from app.dashboard.server import create_app
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A dashboard wired to a throwaway database, seeded with one value."""
    monkeypatch.delenv("AI_PROVIDER", raising=False)

    cfg = load_config()
    cfg.database_url = f"sqlite:///{(tmp_path / 'db' / 'processing.db').as_posix()}"
    set_config(cfg)

    app = create_app(cfg)
    app.dependency_overrides[get_config] = lambda: cfg

    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        doc, _ = repo.upsert_document(
            str(tmp_path / "laporan.pdf"), "hash-1", "PT ABC Indonesia", "laporan.pdf"
        )
        repo.replace_values(
            doc,
            [
                {
                    "company": doc.company,
                    "year": 2024,
                    "statement": "balance_sheet",
                    "field": "total_assets",
                    "raw_label": "Jumlah Assets",
                    "raw_value": "1.500.000.000",
                    "normalized_value": 1_500_000_000.0,
                    "unit": None,
                    "page": 5,
                    "extraction_method": "table",
                    "confidence": 0.42,
                    "status": "REVIEW_REQUIRED",
                }
            ],
        )
        doc_id = doc.id
        value_id = repo.values_for_document(doc)[0].id

    with TestClient(app) as c:
        c.value_id = value_id
        c.doc_id = doc_id
        yield c

    set_config(load_config())


def _stored(client):
    Session = get_session_factory(get_engine(get_config()))
    with Session() as s:
        return Repository(s).get_value(client.value_id)


def _patch(client, **payload):
    return client.patch(f"/api/values/{client.value_id}", json=payload)


# --------------------------------------------------------------------------
# the correction itself
# --------------------------------------------------------------------------
def test_edit_persists_and_keeps_the_extracted_figure(client):
    r = _patch(client, normalized_value=1_500_000_000_000.0, note="mis-scaled on highlights page")
    assert r.status_code == 200

    body = r.json()["value"]
    assert body["normalized_value"] == 1_500_000_000_000.0
    assert body["original_value"] == 1_500_000_000.0
    assert body["is_edited"] is True
    assert body["extraction_method"] == "manual"
    assert body["edit_note"] == "mis-scaled on highlights page"
    assert body["edited_at"] is not None

    # And it really reached the database, not just the response.
    row = _stored(client)
    assert row.normalized_value == 1_500_000_000_000.0
    assert row.edited_at is not None


def test_edit_survives_a_new_page_load(client):
    _patch(client, normalized_value=42.0)
    listed = client.get("/api/values", params={"page_size": 5}).json()["items"]
    assert listed[0]["normalized_value"] == 42.0
    assert listed[0]["is_edited"] is True


def test_edited_value_leaves_the_review_queue(client):
    """A human-confirmed figure is no longer awaiting review."""
    _patch(client, normalized_value=99.0)
    assert _stored(client).status == "OK"
    remaining = client.get("/api/values", params={"status": "REVIEW_REQUIRED"}).json()["pagination"]["total"]
    assert remaining == 0


def test_edit_does_not_inflate_extractor_confidence(client):
    """`confidence` scores the extractor; an edit must not flatter that metric."""
    _patch(client, normalized_value=1234.0)
    assert _stored(client).confidence == pytest.approx(0.42)


def test_a_cleared_value_is_allowed(client):
    r = _patch(client, normalized_value=None)
    assert r.status_code == 200
    assert _stored(client).normalized_value is None


def test_blank_note_is_stored_as_absent(client):
    _patch(client, normalized_value=7.0, note="   ")
    assert _stored(client).edit_note is None


# --------------------------------------------------------------------------
# revert
# --------------------------------------------------------------------------
def test_revert_restores_value_and_method(client):
    _patch(client, normalized_value=5.0)
    r = _patch(client, revert=True)
    assert r.status_code == 200

    body = r.json()["value"]
    assert body["normalized_value"] == 1_500_000_000.0
    assert body["is_edited"] is False
    # The method is restored, not guessed back to a plausible default.
    assert body["extraction_method"] == "table"
    assert body["edit_note"] is None


def test_revert_returns_the_first_figure_not_the_intermediate_one(client):
    _patch(client, normalized_value=111.0)
    _patch(client, normalized_value=222.0)
    _patch(client, revert=True)
    assert _stored(client).normalized_value == 1_500_000_000.0


def test_revert_without_an_edit_is_rejected(client):
    r = _patch(client, revert=True)
    assert r.status_code == 409


# --------------------------------------------------------------------------
# durability across re-processing
# --------------------------------------------------------------------------
def test_hand_correction_survives_reprocessing(client):
    """The regression that matters: a retry must not undo a human's fix.

    `replace_values` is what a forced re-run calls. If it dropped the
    correction, `retry_review` would quietly restore the wrong number.
    """
    _patch(client, normalized_value=1_500_000_000_000.0, note="manual fix")

    Session = get_session_factory(get_engine(get_config()))
    with Session() as s:
        repo = Repository(s)
        doc = repo.get_document(client.doc_id)
        repo.replace_values(
            doc,
            [
                {
                    "company": doc.company,
                    "year": 2024,
                    "statement": "balance_sheet",
                    "field": "total_assets",
                    "raw_label": "Jumlah Assets",
                    # The re-extraction produces its own (wrong) number; the
                    # hand correction has to win over it.
                    "normalized_value": 1_500_000.0,
                    "unit": None,
                    "page": 5,
                    "extraction_method": "ai",
                    "confidence": 0.9,
                }
            ],
        )
        row = repo.values_for_document(doc)[0]
        assert row.normalized_value == 1_500_000_000_000.0
        assert row.extraction_method == "manual"
        assert row.edit_note == "manual fix"
        assert row.original_value == 1_500_000_000.0


def test_reprocessing_does_not_disturb_unedited_rows(client):
    Session = get_session_factory(get_engine(get_config()))
    with Session() as s:
        repo = Repository(s)
        doc = repo.get_document(client.doc_id)
        repo.replace_values(
            doc,
            [
                {
                    "company": doc.company,
                    "year": 2024,
                    "statement": "income_statement",
                    "field": "net_income",
                    "normalized_value": 500.0,
                    "extraction_method": "ai",
                    "confidence": 0.8,
                }
            ],
        )
        rows = repo.values_for_document(doc)
        assert len(rows) == 1
        assert rows[0].normalized_value == 500.0
        assert rows[0].extraction_method == "ai"
        assert rows[0].edited_at is None


# --------------------------------------------------------------------------
# input validation -- a mistyped correction is worse than no correction
# --------------------------------------------------------------------------
def test_unknown_value_is_404(client):
    assert client.patch("/api/values/999999", json={"normalized_value": 1.0}).status_code == 404


def test_missing_amount_is_400(client):
    assert _patch(client, note="just a note").status_code == 400


def test_formatted_string_is_rejected(client):
    """Indonesian-formatted text must not be silently misread."""
    r = _patch(client, normalized_value="1.500.000.000")
    assert r.status_code == 400
    assert _stored(client).normalized_value == 1_500_000_000.0


def test_boolean_is_rejected(client):
    """bool subclasses int, so True must not become 1 rupiah."""
    assert _patch(client, normalized_value=True).status_code == 400


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_is_rejected(client, literal):
    """Sent as raw text because these are not valid JSON.

    `json.loads` accepts the `NaN`/`Infinity` literals by default, so a
    permissive client (or a proxy that rewrites bodies) can deliver them even
    though a conforming one cannot encode them.
    """
    r = client.patch(
        f"/api/values/{client.value_id}",
        content=f'{{"normalized_value": {literal}}}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert _stored(client).normalized_value == 1_500_000_000.0


def test_absurd_magnitude_is_rejected(client):
    r = _patch(client, normalized_value=1e18)
    assert r.status_code == 400
    assert _stored(client).normalized_value == 1_500_000_000.0


def test_negative_totals_are_allowed(client):
    """Expenses and corrections are legitimately negative."""
    r = _patch(client, normalized_value=-250_000.0)
    assert r.status_code == 200
    assert _stored(client).normalized_value == -250_000.0


def test_non_string_note_is_rejected(client):
    assert _patch(client, normalized_value=1.0, note=123).status_code == 400
