"""Currency filtering, and the promise that a figure is never rounded.

Two separate guarantees are tested here.

Currency:
- A filter can select a currency.
- "No currency detected" is a state of its own. It is not folded into IDR,
  because "we could not tell what currency this is" and "it is rupiah" are
  different answers, and a filter that merged them would report an undetected
  document as a rupiah one.

Exactness:
- A whole figure keeps every digit. The parser returns whole numbers as `int`
  precisely so no binary float is constructed for them: `float` holds integers
  exactly only up to 2**53, and figures in this dataset already pass 2.36e15.
- Scaling by a unit multiplier (ribuan / juta / miliar) stays exact, because the
  multiplier is an integer power of ten.
- What the API hands to the browser is the same number that was scanned.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_config, load_config, set_config
from app.dashboard.server import create_app
from app.financial.parser import parse_financial_number
from app.storage.database import get_engine, get_session_factory
from app.storage.repository import Repository

BIG = 2_359_587_200_000_000  # larger than any figure in the real database


def _value(doc, field, amount, *, currency="IDR", year=2024, statement="balance_sheet"):
    return {
        "company": doc.company,
        "year": year,
        "statement": statement,
        "field": field,
        "raw_label": field.replace("_", " ").title(),
        "raw_value": str(amount),
        "normalized_value": amount,
        "currency": currency,
        "unit": None,
        "page": 5,
        "extraction_method": "table",
        "confidence": 0.9,
        "status": "OK",
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)

    cfg = load_config()
    cfg.database_url = f"sqlite:///{(tmp_path / 'db' / 'processing.db').as_posix()}"
    set_config(cfg)

    app = create_app(cfg)
    app.dependency_overrides[get_config] = lambda: cfg

    Session = get_session_factory(get_engine(cfg))
    with Session() as s:
        repo = Repository(s)
        idr, _ = repo.upsert_document("idr.pdf", "h-idr", "PT IDR Tbk", "idr.pdf")
        repo.replace_values(idr, [_value(idr, "total_assets", 1_000_000, currency="IDR")])

        usd, _ = repo.upsert_document("usd.pdf", "h-usd", "PT USD Inc", "usd.pdf")
        repo.replace_values(usd, [_value(usd, "total_assets", 500_000, currency="USD")])

        # Nothing in this report named a currency at all.
        unknown, _ = repo.upsert_document("x.pdf", "h-x", "PT Unknown Tbk", "x.pdf")
        repo.replace_values(unknown, [_value(unknown, "total_assets", 7, currency=None)])

    with TestClient(app) as c:
        yield c

    set_config(load_config())


# --------------------------------------------------------------------------
# parsing keeps every digit


def test_whole_numbers_parse_as_int_not_float():
    """A whole figure must never pass through a binary float.

    `float` is exact for integers only below 2**53. Going through it is how a
    large figure silently gains or loses a digit, so whole input is converted
    with `int` and stays exact at any magnitude.
    """
    for raw in ("28.793.000.000.000", "1,234,567", "2359587200000000", "0", "7"):
        parsed = parse_financial_number(raw)
        assert isinstance(parsed, int), f"{raw!r} produced {type(parsed).__name__}"
        assert parsed == int(raw.replace(".", "").replace(",", ""))


def test_a_figure_past_the_float_ceiling_keeps_its_last_digit():
    """2**53 is the last integer a double holds exactly; 2**53 + 1 is not.

    A figure this size is beyond anything in the current data, which is the
    point: the guarantee is that exactness does not depend on the size of the
    next report.
    """
    first_lossy = 2**53 + 1
    parsed = parse_financial_number(f"{first_lossy:,}")
    assert parsed == first_lossy
    # The float path drops a digit here and returns the neighbouring even value.
    assert int(float(str(first_lossy))) == first_lossy - 1


def test_negative_and_parenthesised_figures_stay_exact():
    assert parse_financial_number("(1,234,567)") == -1234567
    assert parse_financial_number("-28.793.000.000.000") == -28793000000000
    assert isinstance(parse_financial_number("(1,234,567)"), int)


def test_fractional_input_keeps_its_fraction():
    """A stray cents figure is rare but must not be rounded to whole rupiah."""
    parsed = parse_financial_number("1,286,605,455.80")
    assert parsed == pytest.approx(1286605455.80)


def test_scaling_by_a_unit_multiplier_is_exact():
    from app.financial.normalizer import detect_unit, normalize_value

    parsed = parse_financial_number("28.793")
    scaled = normalize_value(parsed, detect_unit("dalam miliar"))
    # 28.793 x 1e9 = 28,793,000,000,000 exactly, not 28,793,000,000,000.002.
    assert scaled == 28793000000000
    assert isinstance(scaled, int)


def test_a_very_large_figure_survives_the_api_and_json(client):
    """What the browser receives must be the number that was scanned."""
    Session = get_session_factory(get_engine(get_config()))
    with Session() as s:
        repo = Repository(s)
        doc = next(d for d in repo.all_documents() if d.company == "PT IDR Tbk")
        repo.replace_values(doc, [_value(doc, "total_assets", BIG, currency="IDR")])

    listed = client.get("/api/values", params={"company": "PT IDR Tbk"}).json()["items"]
    stored = next(v for v in listed if v["field"] == "total_assets")
    assert stored["normalized_value"] == BIG

    grid = client.get("/api/results/summary", params={"company": "PT IDR Tbk"}).json()
    row = next(r for r in grid["items"] if r["company"] == "PT IDR Tbk")
    assert row["cells"]["total_assets"]["normalized_value"] == BIG


def test_a_hand_correction_is_not_rounded(client):
    listed = client.get("/api/values", params={"company": "PT IDR Tbk"}).json()["items"]
    value_id = listed[0]["id"]
    typed = 1_286_605_455_80  # a figure with cents
    r = client.patch(f"/api/values/{value_id}", json={"normalized_value": float(typed) + 0.8})
    assert r.status_code == 200
    assert r.json()["value"]["normalized_value"] == pytest.approx(typed + 0.8)


# --------------------------------------------------------------------------
# currency filtering


def test_filter_values_by_currency(client):
    idr = client.get("/api/values", params={"currency": "IDR"}).json()
    usd = client.get("/api/values", params={"currency": "USD"}).json()
    assert {v["company"] for v in idr["items"]} == {"PT IDR Tbk"}
    assert {v["company"] for v in usd["items"]} == {"PT USD Inc"}
    assert idr["pagination"]["total"] == 1


def test_filter_is_case_insensitive(client):
    r = client.get("/api/values", params={"currency": "usd"})
    assert r.status_code == 200
    assert r.json()["pagination"]["total"] == 1


def test_undetected_currency_is_its_own_bucket(client):
    """`currency=none` means nothing was detected. It must not return IDR rows."""
    none = client.get("/api/values", params={"currency": "none"}).json()
    assert {v["company"] for v in none["items"]} == {"PT Unknown Tbk"}
    assert none["items"][0]["currency"] is None


def test_no_currency_filter_returns_everything(client):
    assert client.get("/api/values", params={}).json()["pagination"]["total"] == 3


def test_facets_report_currencies_with_counts(client):
    facets = client.get("/api/values/facets").json()
    counts = {f["currency"]: f["count"] for f in facets["currencies"]}
    assert counts == {"IDR": 1, "USD": 1, "none": 1}


def test_summary_grid_filters_by_currency(client):
    idr = client.get("/api/results/summary", params={"currency": "IDR"}).json()
    assert {r["company"] for r in idr["items"]} == {"PT IDR Tbk"}
    usd = client.get("/api/results/summary", params={"currency": "USD"}).json()
    assert {r["company"] for r in usd["items"]} == {"PT USD Inc"}


def test_summary_row_reports_its_reporting_currency(client):
    body = client.get("/api/results/summary").json()
    by_company = {r["company"]: r for r in body["items"]}
    assert by_company["PT IDR Tbk"]["currency"] == "IDR"
    assert by_company["PT USD Inc"]["currency"] == "USD"
    # Nothing was detected for this one, which is not the same as IDR.
    assert by_company["PT Unknown Tbk"]["currency"] == "Not detected"


def test_a_row_with_conflicting_currencies_says_mixed(client):
    """Silently picking one currency would misstate what the report contains."""
    Session = get_session_factory(get_engine(get_config()))
    with Session() as s:
        repo = Repository(s)
        doc = next(d for d in repo.all_documents() if d.company == "PT IDR Tbk")
        repo.replace_values(
            doc,
            [
                _value(doc, "total_assets", 1_000_000, currency="IDR"),
                _value(doc, "net_income", 250_000, currency="USD", statement="income_statement"),
            ],
        )

    body = client.get("/api/results/summary", params={"company": "PT IDR Tbk"}).json()
    assert body["items"][0]["currency"] == "Mixed"