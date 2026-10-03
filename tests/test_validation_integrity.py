"""Regressions for the 725 validation errors.

The identity checks (assets_split, assets_equals_liabilities_plus_equity,
gross_profit_identity, ...) were failing on 300 of 357 documents for two
extraction reasons rather than because of accounting inconsistencies:

  1. Bare table fragments were stored as real amounts. Pages whose columns
     interleave emit tokens like '1', '4', '( 3' beside the genuine figures, so
     `total_assets = 1` was recorded and every identity check spanning that
     year failed. 1,999 such rows existed.

  2. The unit word was taken from incidental prose. A note reading 'dinyatakan
     dalam ribuan' on a page whose figures were already full rupiah
     (4.223.727.970.626) inflated correct values by 1,000x.

Identity checks are meant to surface genuine accounting inconsistencies. Feeding
them misparses buries the real findings, so implausible amounts are excluded
from validation while remaining in the database and the CSV, flagged.
"""
import pytest

from app.financial.plausibility import (
    MAX_PLAUSIBLE_MONETARY,
    MIN_PLAUSIBLE_MONETARY,
    correct_unit_multiplier,
    is_implausible_amount,
    is_monetary,
    page_magnitudes,
)
from app.pipeline.processor import DocumentProcessor, _value_rank


class TestImplausibility:
    @pytest.mark.parametrize("value", [1, 1000, 72_000_000, 999_999_999, -3.0, 12.0])
    def test_fragments_and_tiny_amounts_rejected(self, value):
        assert is_implausible_amount(value, "total_assets", "juta")

    def test_plausible_amount_accepted(self):
        assert not is_implausible_amount(4_223_727_970_626, "total_assets", "juta")

    def test_real_total_assets_accepted(self):
        assert not is_implausible_amount(77_700_000_000_000, "total_assets", None)

    def test_absurdly_large_rejected(self):
        """A unit word applied too many times lands above any real figure."""
        assert is_implausible_amount(MAX_PLAUSIBLE_MONETARY * 100,
                                     "total_assets", "ribuan")

    def test_none_is_not_implausible(self):
        assert not is_implausible_amount(None, "total_assets", "juta")

    def test_zero_is_not_implausible(self):
        assert not is_implausible_amount(0.0, "total_assets", "juta")

    def test_negative_large_is_plausible(self):
        """Contra items are legitimately negative."""
        assert not is_implausible_amount(-1_179_794_000_000,
                                         "cost_of_revenue", "juta")

    @pytest.mark.parametrize("field", [
        "treasury_shares_quantity", "treasury_shares_percentage",
        "treasury_shares_nominal_value", "treasury_shares_carrying_value",
    ])
    def test_share_fields_exempt_from_floor(self, field):
        assert not is_implausible_amount(500_000, field, "shares")
        assert not is_monetary(field, "shares")

    def test_percent_unit_exempt(self):
        assert not is_implausible_amount(1.5, "margin", "percent")

    def test_floor_boundary(self):
        assert not is_implausible_amount(MIN_PLAUSIBLE_MONETARY, "revenue")
        assert is_implausible_amount(MIN_PLAUSIBLE_MONETARY - 1, "revenue")


class TestPageMagnitudes:
    def test_indonesian_thousand_separators_removed(self):
        text = "Total aset 4.223.727.970.626 Liability"
        assert page_magnitudes(text) == [4223727970626]

    def test_small_tokens_ignored(self):
        assert page_magnitudes("halaman 12 dari 99") == []

    def test_empty_text(self):
        assert page_magnitudes("") == []

    def test_none_text(self):
        assert page_magnitudes(None) == []


class TestUnitCorrection:
    def test_ribuan_rejected_when_figures_already_rupiah(self):
        """The real case: 'dinyatakan dalam ribuan' in a note on a page whose
        totals are 4.2 trillion rupiah."""
        text = "dalam ribuan rupiah " + ("Total aset 4.223.727.970.626 " * 3)
        multiplier, reason = correct_unit_multiplier(text, 1_000)
        assert multiplier == 1
        assert reason and "rupiah" in reason

    def test_ribuan_kept_when_figures_are_small(self):
        text = "dalam ribuan rupiah " + ("Persediaan 4.223.727 " * 3)
        multiplier, reason = correct_unit_multiplier(text, 1_000)
        assert multiplier == 1_000
        assert reason is None

    def test_juta_kept_for_normal_millions(self):
        text = "dalam jutaan rupiah " + ("Total aset 28.846.243 " * 3)
        multiplier, _ = correct_unit_multiplier(text, 1_000_000)
        assert multiplier == 1_000_000

    def test_base_unit_untouched(self):
        multiplier, reason = correct_unit_multiplier("Total aset 4.223.727.970.626", 1)
        assert multiplier == 1
        assert reason is None

    def test_no_numbers_leaves_unit_alone(self):
        multiplier, reason = correct_unit_multiplier("dalam ribuan", 1_000)
        assert multiplier == 1_000
        assert reason is None

    def test_single_large_footnote_does_not_flip_unit(self):
        """Median, not max: one big number in a note must not override a
        correctly scaled statement."""
        text = ("dalam ribuan rupiah " + ("Persediaan 4.223.727 " * 5)
                + " Investments 99.000.000.000.000")
        multiplier, _ = correct_unit_multiplier(text, 1_000)
        assert multiplier == 1_000

    def test_mid_sized_page_is_not_double_scaled(self):
        """The real BOBA case: '17.527.130.084' under a stray 'juta' gives
        1.75e16. The digits were not large enough to trip the old
        rupiah-scale threshold on their own, but they are large enough that
        scaling them is checkable, so the unit is rejected either way."""
        text = "dalam jutaan rupiah " + ("Laba bersih 17.527.130.084 " * 3)
        multiplier, reason = correct_unit_multiplier(text, 1_000_000)
        assert multiplier == 1
        assert reason

    def test_scaled_page_median_ceiling_catches_sub_threshold_pages(self):
        """The gap the rupiah-scale threshold leaves: a median between 1e9 and
        1e10 looks plausible on its own, but no statement page's middle figure
        is 5e15 after scaling. The ceiling is the second, independent guard."""
        text = "dalam jutaan rupiah " + ("Total aset 5.000.000.000 " * 3)
        multiplier, reason = correct_unit_multiplier(text, 1_000_000)
        assert multiplier == 1
        assert reason and "ceiling" in reason

    def test_document_level_unit_is_also_checked(self):
        """A document multiplier arriving without a page unit is still a claim
        that the page's own figures have to support."""
        text = ("dalam jutaan " + ("Total aset 17.527.130.084 " * 3))
        multiplier, _ = correct_unit_multiplier(text, 1_000_000)
        assert multiplier == 1


class TestValidationGrouping:
    """The grouping rule decides what the identity checks actually see."""

    def _group(self, values):
        proc = DocumentProcessor.__new__(DocumentProcessor)
        return proc._group_by_year(values)

    def test_implausible_value_excluded(self):
        out = self._group([
            {"year": 2021, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 1.0, "implausible": True},
        ])
        # No empty year bucket is left behind for the caller to iterate.
        assert out == {}

    def test_implausible_excluded_but_real_sibling_kept(self):
        out = self._group([
            {"year": 2021, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 1.0, "implausible": True},
            {"year": 2021, "statement": "balance_sheet", "field": "total_liabilities",
             "normalized_value": 3.0e12},
        ])
        fields = out[2021]["balance_sheet"]
        assert set(fields) == {"total_liabilities"}

    def test_plausible_value_kept(self):
        out = self._group([
            {"year": 2021, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 4.2e12, "implausible": False},
        ])
        assert out[2021]["balance_sheet"]["total_assets"]["normalized_value"] == 4.2e12

    def test_best_observation_wins_not_the_last(self):
        """A late low-authority fragment used to overwrite a verified total."""
        out = self._group([
            {"year": 2021, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 77.7e12, "section": "balance_sheet",
             "confidence": 0.9, "implausible": False},
            {"year": 2021, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 1.0, "section": None, "confidence": 0.4,
             "implausible": True},
        ])
        got = out[2021]["balance_sheet"]["total_assets"]["normalized_value"]
        assert got == 77.7e12

    def test_year_none_grouped_separately(self):
        out = self._group([
            {"year": None, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 4.2e12},
            {"year": 2021, "statement": "balance_sheet", "field": "total_assets",
             "normalized_value": 5.0e12},
        ])
        assert set(out) == {None, 2021}


class TestValueRank:
    def test_statement_page_outranks_unsectioned(self):
        strong = {"section": "balance_sheet", "confidence": 0.9}
        weak = {"section": None, "confidence": 0.9}
        assert _value_rank(strong) > _value_rank(weak)

    def test_confidence_breaks_ties(self):
        a = {"section": "balance_sheet", "confidence": 0.95}
        b = {"section": "balance_sheet", "confidence": 0.50}
        assert _value_rank(a) > _value_rank(b)

    def test_header_zipped_beats_unsectioned(self):
        a = {"section": None, "year_from_header": True, "confidence": 0.8}
        b = {"section": None, "confidence": 0.8}
        assert _value_rank(a) > _value_rank(b)

    def test_implausible_ranks_lowest(self):
        bad = {"normalized_value": 1.0, "section": "balance_sheet",
               "confidence": 0.99, "implausible": True}
        good = {"normalized_value": 4e12, "section": None, "confidence": 0.4}
        assert _value_rank(bad) < _value_rank(good)

    def test_parent_only_ranks_below_statements(self):
        parent = {"is_parent_only": True, "confidence": 0.95}
        plain = {"section": None, "confidence": 0.5}
        assert _value_rank(parent) < _value_rank(plain)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])