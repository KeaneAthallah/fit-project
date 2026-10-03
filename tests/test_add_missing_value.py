"""Adding a figure the extractor never found.

An empty grid cell is not the same problem as a wrong one: there is no pipeline
value to correct or revert, so it needs its own endpoint. What matters is that
the added figure is treated as authoritative, cannot be duplicated, and -- like
an edit -- is not silently undone by the next re-processing run.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_config, load_config, set_config
from app.dashboard.server import create_app
from app.storage.database import get_engine, get_session_factory
from app.storage.models import Document
from app.storage.repository import Repository


@pytest.fixture()
def env(tmp_path, monkeypatch):
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
            str(tmp_path / "a.pdf"), "hash-a", "PT AAA Tbk", "a.pdf"
        )
        repo.replace_values(
            doc,
            [
                {
                    "company": doc.company,
                    "year": 2024,
                    "statement": "balance_sheet",
                    "field": "total_assets",
                    "raw_label": "Total aset",
                    "raw_value": "1.000.000",
                    "normalized_value": 1_000_000_000.0,
                    "unit": "juta",
                    "currency": "IDR",
                    "page": 5,
                    "extraction_method": "table",
                    "confidence": 0.9,
                    "status": "OK",
                }
            ],
        )

    with TestClient(app) as c:
        yield c, doc.id

    set_config(load_config())


def _add(client, document_id, **overrides):
    payload = {
        "document_id": document_id,
        "field": "total_equity",
        "year": 2024,
        "normalized_value": 600_000_000.0,
    }
    payload.update(overrides)
    return client.post("/api/values", json=payload)


def test_adding_a_missing_figure_fills_the_empty_grid_cell(env):
    client, doc_id = env
    assert _add(client, doc_id).status_code == 200

    body = client.get("/api/results/summary").json()
    row = next(r for r in body["items"] if r["year"] == 2024)
    cell = row["cells"]["total_equity"]
    assert cell is not None
    assert cell["normalized_value"] == 600_000_000.0
    # Hand-entered, so it is the authority for this figure.
    assert cell["is_edited"] is True
    assert cell["extraction_method"] == "manual"


def test_an_added_figure_takes_the_reports_currency(env):
    """It should not claim 'not detected' just because nobody typed a currency."""
    client, doc_id = env
    value = _add(client, doc_id).json()["value"]
    assert value["currency"] == "IDR"


def test_the_statement_is_derived_from_the_field(env):
    client, doc_id = env
    value = _add(client, doc_id).json()["value"]
    assert value["statement"] == "balance_sheet"
    assert value["field"] == "total_equity"


def test_an_unknown_field_is_refused(env):
    client, doc_id = env
    r = _add(client, doc_id, field="not_a_field")
    assert r.status_code == 400
    assert "not_a_field" not in r.json()["detail"] or "must be one of" in r.json()["detail"]


def test_a_figure_that_already_exists_is_not_duplicated(env):
    client, doc_id = env
    r = _add(client, doc_id, field="total_assets")
    assert r.status_code == 409
    assert "already has a figure" in r.json()["detail"]

    values = client.get("/api/values", params={"field": "total_assets"}).json()
    assert values["pagination"]["total"] == 1


def test_a_figure_without_a_number_is_refused(env):
    """Clearing an existing figure is an edit, not an add."""
    client, doc_id = env
    assert _add(client, doc_id, normalized_value=None).status_code == 400
    assert _add(client, doc_id, normalized_value="1.234").status_code == 400
    assert _add(client, doc_id, normalized_value=True).status_code == 400


def test_an_unknown_document_is_refused(env):
    client, _ = env
    assert _add(client, 999_999).status_code == 404


def test_a_figure_at_the_scale_of_real_data_is_accepted(env):
    """Authorized capital of IDR 2.36e15 is stored in this system.

    A ceiling below that would refuse to correct a figure that genuinely
    exists, which is the wrong way for a typo guard to fail.
    """
    client, doc_id = env
    big = 2_359_587_200_000_000
    r = _add(client, doc_id, normalized_value=big)
    assert r.status_code == 200
    assert r.json()["value"]["normalized_value"] == big


def test_the_ceiling_is_the_exact_integer_boundary(env):
    """Range checking and exactness are the same limit.

    Anything accepted must still be renderable digit-for-digit in the browser,
    so the ceiling is 2**53 - 1 and not a rounder number.
    """
    client, doc_id = env
    assert _add(client, doc_id, normalized_value=2**53 - 1).status_code == 200

    # The first integer that cannot be held exactly is refused rather than
    # accepted and quietly rounded on the way to the screen.
    r = _add(client, doc_id, field="total_assets", normalized_value=2**53 + 1)
    assert r.status_code == 400
    assert "typo" in r.json()["detail"]


def test_the_row_lists_the_reports_an_added_figure_can_go_in(env):
    client, doc_id = env
    row = next(
        r for r in client.get("/api/results/summary").json()["items"] if r["year"] == 2024
    )
    assert [d["id"] for d in row["documents"]] == [doc_id]
    assert row["documents"][0]["filename"] == "a.pdf"


def test_an_added_figure_survives_reprocessing(env):
    """The whole point of an audit trail is that a retry cannot undo it.

    Re-processing rebuilds every value for the document from scratch. An
    edit is reattached to the extractor's row; an added figure has no such row,
    so without special handling it is deleted -- the one correction a retry
    silently reverts.
    """
    client, doc_id = env
    assert _add(client, doc_id).status_code == 200

    cfg = get_config()
    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        doc = s.get(Document, doc_id)
        # Exactly what a retry sends: the extractor found total_assets only.
        repo.replace_values(
            doc,
            [
                {
                    "company": doc.company,
                    "year": 2024,
                    "statement": "balance_sheet",
                    "field": "total_assets",
                    "raw_label": "Total aset",
                    "raw_value": "1.000.000",
                    "normalized_value": 1_000_000_000.0,
                    "unit": "juta",
                    "currency": "IDR",
                    "page": 5,
                    "extraction_method": "table",
                    "confidence": 0.9,
                    "status": "OK",
                }
            ],
        )

    body = client.get("/api/results/summary").json()
    row = next(r for r in body["items"] if r["year"] == 2024)
    assert row["cells"]["total_equity"]["normalized_value"] == 600_000_000.0
    assert row["cells"]["total_equity"]["extraction_method"] == "manual"
    # And it was not duplicated either.
    values = client.get("/api/values", params={"field": "total_equity"}).json()
    assert values["pagination"]["total"] == 1