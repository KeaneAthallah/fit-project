"""The nine statement indicators, matched on their exact wording.

Every case here is a label copied verbatim out of a filing in ``XBRL/``. The
figures asserted are the ones printed beside those labels, so a mapping change
that silently folds one line into another fails here rather than showing up as
a plausible wrong number in the database.
"""
from __future__ import annotations

import pytest

from app.extraction.html_source import read_html_file
from app.financial.mappings import map_label

CORPUS = "XBRL"


# (field, statement, exact label, company, year, statement page, expected raw
# value for the reporting year)
INDICATORS = [
    (
        "total_assets", "balance_sheet", "Jumlah aset",
        "AISA FKS Food Sejahtera Tbk", 2022, "1210000.html", "1,826,350",
    ),
    (
        "equity_attributable_to_owners_of_parent", "balance_sheet",
        "Jumlah ekuitas yang diatribusikan kepada pemilik entitas induk",
        "AALI Astra Agro Lestari Tbk", 2020, "1210000.html", "18,752,493",
    ),
    (
        "non_controlling_interest", "balance_sheet", "Kepentingan non-pengendali",
        "AALI Astra Agro Lestari Tbk", 2020, "1210000.html", "495,301",
    ),
    (
        "total_equity", "balance_sheet", "Jumlah ekuitas",
        "AISA FKS Food Sejahtera Tbk", 2022, "1210000.html", "777,861",
    ),
    (
        "sales_and_revenue", "income_statement", "Penjualan dan pendapatan usaha",
        "AISA FKS Food Sejahtera Tbk", 2022, "1321000.html", "1,843,760",
    ),
    (
        "total_profit_loss_before_tax", "income_statement",
        "Jumlah laba (rugi) sebelum pajak penghasilan",
        "AISA FKS Food Sejahtera Tbk", 2022, "1321000.html", "(     56,487   )",
    ),
    (
        "total_profit_loss", "income_statement", "Jumlah laba (rugi)",
        "AISA FKS Food Sejahtera Tbk", 2022, "1321000.html", "(     62,359   )",
    ),
    (
        "income_tax_paid_operating", "cash_flow",
        "Penerimaan pengembalian (pembayaran) pajak penghasilan dari aktivitas operasi",
        "AALI Astra Agro Lestari Tbk", 2020, "1510000.html", "560,293",
    ),
]


@pytest.mark.parametrize("field,statement,label,_co,_yr,_page,_raw", INDICATORS)
def test_label_maps_to_its_own_field(field, statement, label, _co, _yr, _page, _raw):
    assert map_label(label, statement) == (field, 1.0)


@pytest.mark.parametrize("field,statement,label,company,year,page,raw", INDICATORS)
def test_filing_yields_that_value_for_that_field(
    field, statement, label, company, year, page, raw, corpus_root
):
    """The value beside the label in the filing is the value stored."""
    filing = read_html_file(corpus_root / company / str(year) / page, 1, year)
    rows = [r for r in filing.table.rows if r.row_label == label]
    assert rows, f"{label!r} is not a row of {company} {year} {page}"
    values = dict(rows[0].values)
    assert values.get(year) == raw


@pytest.mark.parametrize("field,statement,label,_co,_yr,_page,_raw", INDICATORS)
def test_label_is_not_folded_into_a_nearer_field(
    field, statement, label, _co, _yr, _page, _raw
):
    """The distinguishing feature survives mapping.

    Each of these labels contains or resembles another line in the same
    statement. If any of them collapsed into that neighbour the figure would
    be stored under a heading the filing never gave it.
    """
    neighbours = {
        "total_assets": {"current_assets", "non_current_assets"},
        "equity_attributable_to_owners_of_parent": {"total_equity"},
        "total_equity": {"equity_attributable_to_owners_of_parent"},
        "total_profit_loss": {"total_profit_loss_before_tax"},
        "total_profit_loss_before_tax": {"total_profit_loss"},
    }
    got, _ = map_label(label, statement)
    assert got not in neighbours.get(field, set())


def test_tax_line_accepts_a_second_wording():
    """Different companies print the same cash-flow tax line differently,
    so a second wording must land on the same field."""
    assert map_label("Pembayaran pajak penghasilan badan", "cash_flow") == (
        "income_tax_paid_operating",
        1.0,
    )


class TestParenthesesAreSignificant:
    """Brackets that are part of the label must not be stripped away.

    `_clean_label` drops parentheticals so that a unit annotation such as
    '(dalam jutaan Rupiah)' cannot defeat a match. Where the parentheses carry
    the meaning of the line instead, dropping them merges two different lines.
    """

    def test_profit_or_loss_is_not_profit(self):
        assert map_label("Jumlah laba (rugi)", "income_statement") == (
            "total_profit_loss", 1.0,
        )
        # The profit-only line is not a registered line item at all, so it must
        # not be read as the profit-or-loss line.
        assert map_label("Jumlah laba", "income_statement") == (None, 0.0)

    def test_refunded_or_paid_is_not_refunded(self):
        exact = ("Penerimaan pengembalian (pembayaran) pajak penghasilan "
                 "dari aktivitas operasi")
        assert map_label(exact, "cash_flow") == ("income_tax_paid_operating", 1.0)
        without = ("Penerimaan pengembalian pajak penghasilan "
                   "dari aktivitas operasi")
        assert map_label(without, "cash_flow") == (None, 0.0)

    def test_unit_annotation_still_ignored(self):
        assert map_label("Jumlah aset (dalam jutaan Rupiah)", "balance_sheet") == (
            "total_assets", 1.0,
        )


class TestSubSectorRoundTrips:
    """A text field has to survive storage and come back out.

    `normalized_value` is NULL for the sub-sector by design, so if the API did
    not also carry `text_value` the field would be stored correctly and then
    read back as an empty cell. Nothing else would catch it: extraction reports
    full coverage, and the grid just shows a blank column.
    """

    def _stored(self, tmp_path, **overrides):
        from app.core.config import AppConfig, set_config
        from app.storage.database import get_engine, get_session_factory
        from app.storage.repository import Repository

        cfg = AppConfig()
        cfg.database_url = f"sqlite:///{(tmp_path / 'db' / 'p.db').as_posix()}"
        set_config(cfg)
        Session = get_session_factory(get_engine(cfg))
        with Session() as s:
            repo = Repository(s)
            doc, _ = repo.upsert_document(
                str(tmp_path / "1210000.html"), "hash-sub", "PT Sub Tbk", "1210000.html"
            )
            row = {
                "company": "PT Sub Tbk", "year": 2024, "statement": "cover",
                "field": "sub_sector",
                "raw_label": "Subsektor", "raw_value": "Food & Beverage",
                "normalized_value": None, "text_value": "Food & Beverage",
                "page": 1, "section": None, "extraction_method": "cover_text",
                "confidence": 1.0, "status": "OK",
            }
            row.update(overrides)
            repo.replace_values(doc, [row])
            return repo.all_values()

    def test_value_dict_carries_the_text(self, tmp_path):
        from app.dashboard.api import _value_dict

        v = self._stored(tmp_path)
        payload = _value_dict(v[0])
        assert payload["text_value"] == "Food & Beverage"
        assert payload["normalized_value"] is None

    def test_summary_grid_cell_carries_the_text(self, tmp_path):
        from app.dashboard.api import _summary_cell

        v = self._stored(tmp_path)
        cell = _summary_cell(v[0], list(v))
        assert cell["text_value"] == "Food & Beverage"

    def test_cover_reading_is_full_confidence(self, tmp_path):
        """The cover is the sub-sector's own home, as the balance sheet is for
        total assets -- so this is a certain figure, not a hedged one."""
        from app.pipeline.processor import CONFIDENCE_STATEMENT_PAGE

        v = self._stored(tmp_path)
        assert v[0].confidence == CONFIDENCE_STATEMENT_PAGE == 1.0
        assert v[0].extraction_method == "cover_text"


class TestRemovedFieldsStayRemoved:
    @pytest.mark.parametrize("label", [
        "Pendapatan", "Pendapatan usaha", "Revenue", "Net revenue",
    ])
    def test_revenue_is_unmapped(self, label):
        assert map_label(label, "income_statement") == (None, 0.0)

    @pytest.mark.parametrize("label", [
        "Laba sebelum pajak", "Profit before tax",
        "Beban pajak penghasilan", "Income tax",
    ])
    def test_profit_before_tax_and_income_tax_are_unmapped(self, label):
        assert map_label(label, "income_statement") == (None, 0.0)

    def test_cash_flow_tax_line_never_lands_in_an_income_tax_field(self):
        """The cash-flow tax line must not be stored as a P&L tax charge."""
        label = ("Penerimaan pengembalian (pembayaran) pajak penghasilan "
                 "dari aktivitas operasi")
        field, _ = map_label(label, "cash_flow")
        assert field not in {"income_tax", "revenue", "profit_before_tax"}