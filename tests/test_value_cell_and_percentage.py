"""Tests for the 126-unparseable-errors fix on 2024.pdf.

Covers: percentage tokens, prose-fragment rejection in table rows, and
OCR-corrupted token tolerance.
"""
import pytest

from app.financial.parser import NumberParseError, parse_financial_number
from app.financial.percentage import is_percentage, parse_percentage
from app.financial.plausibility import (
    MAX_PLAUSIBLE_MONETARY,
    MIN_PLAUSIBLE_MONETARY,
    is_implausible_amount,
    is_monetary,
)
from app.extraction.table_extractor import (
    _TEXT_STRATEGY_SETTINGS,
    _is_value_cell,
    _merge_number_fragments,
    _split_row,
)


class TestNumberFragmentMerging:
    """Text-strategy tables split '(18,474.41)' into '(' + '18,47' + '4.41)'."""

    def test_aali_2024_row(self):
        row = ['Beban Pokok Pen', 'dapatan |', 'Cost of Revenue', '', '', '',
               '(', '18,47', '4.41)', '(17,974.', '49)', '499.92', '', '3']
        out = _merge_number_fragments(row)
        assert '(18,474.41)' in out
        assert '(17,974.49)' in out
        assert '499.92' in out  # complete number untouched

    def test_complete_numbers_untouched(self):
        row = ['Total Aset', '28,793,225', '28,846,243']
        assert _merge_number_fragments(row) == row

    def test_paren_numbers_untouched(self):
        row = ['Laba Bruto', '(520,193)', '(264,688)']
        assert _merge_number_fragments(row) == row

    def test_split_paren_mid_row(self):
        row = ['Selisih', '(944,3', '34)', '1,112,829']
        assert _merge_number_fragments(row) == ['Selisih', '(944,334)', '1,112,829']

    def test_labels_untouched(self):
        row = ['Kas', '109']
        assert _merge_number_fragments(row) == ['Kas', '109']

    def test_wide_number_split_after_leading_digits(self):
        # AALI 2021 p138: 5,960,396 arrives as '5' + ',960,396'. Both halves
        # look like standalone numbers, so the merge must be explicit.
        row = ['Total liabilitas jangka pendek', '5', ',960,396', '1,7', '92,506']
        assert _merge_number_fragments(row) == [
            'Total liabilitas jangka pendek', '5,960,396', '1,7', '92,506']

    def test_wide_number_split_multiple_rows(self):
        assert _merge_number_fragments(['Total liabilitas', '9', ',228,733']) == \
            ['Total liabilitas', '9,228,733']
        assert _merge_number_fragments(['Total ekuitas', '2', '1,171,173']) == \
            ['Total ekuitas', '2', '1,171,173']  # tail has no separator: no merge

    def test_two_runs_of_digits_are_not_fused(self):
        # '12' next to '34' must stay two numbers: the tail lacks a separator.
        assert _merge_number_fragments(['x', '12', '34']) == ['x', '12', '34']
        assert _merge_number_fragments(['x', '109', '12']) == ['x', '109', '12']


class TestPageUnitDetection:
    """Per-page '(Rp miliar)' overrides the document-level unit."""

    def test_paren_miliar(self):
        from app.extraction.table_extractor import detect_page_unit
        assert detect_page_unit("(Rp miliar)\nLaba per Saham") == ("miliar", 1_000_000_000)

    def test_dalam_jutaan_rupiah(self):
        from app.extraction.table_extractor import detect_page_unit
        assert detect_page_unit("(dalam jutaan Rupiah)") == ("juta", 1_000_000)

    def test_currency_phrase_beats_bare_jutaan(self):
        """'dalam miliaran Rupiah' outranks '(dalam Jutaan)' from a
        'Saham Beredar (dalam Jutaan)' row (AALI 2024 page 12)."""
        from app.extraction.table_extractor import detect_page_unit
        text = "Saham Beredar (dalam Jutaan)\ndalam miliaran Rupiah dan menggunakan"
        assert detect_page_unit(text) == ("miliar", 1_000_000_000)

    def test_narrative_not_detected(self):
        from app.extraction.table_extractor import detect_page_unit
        assert detect_page_unit("naik menjadi Rp1.15 trillion, driven by") == (None, 1)


class TestGrossProfitSignPresentation:
    """Cost of revenue may be negative (parenthesized) or positive expense."""

    def _gp_check(self, rev, cost, gp):
        from app.financial.validators import validate_document
        values = {
            "income_statement": {
                "revenue": {"normalized_value": rev},
                "cost_of_revenue": {"normalized_value": cost},
                "gross_profit": {"normalized_value": gp},
            },
        }
        return next(c for c in validate_document(values)
                    if c.check_name == "gross_profit_identity")

    def test_negative_cost_presentation(self):
        check = self._gp_check(21_815e9, -18_474.41e9, 3_341e9)
        assert check.status == "VALID"

    def test_positive_cost_presentation(self):
        check = self._gp_check(21_815e9, 18_474.41e9, 3_341e9)
        assert check.status == "VALID"


class TestPercentage:
    @pytest.mark.parametrize("raw", ["4%", "15%", "15,6%", "(2,5)%", "5 %"])
    def test_is_percentage(self, raw):
        assert is_percentage(raw)

    @pytest.mark.parametrize("raw", ["1.234", "Rp 5.000", "1.000.000 saham", "-", "abc"])
    def test_not_percentage(self, raw):
        assert not is_percentage(raw)

    def test_parse(self):
        assert parse_percentage("15,6%") == 15.6
        assert parse_percentage("4%") == 4.0
        assert parse_percentage("(2,5)%") == -2.5

    def test_percentage_not_monetary_error(self):
        """'4%' must not raise NumberParseError in the extraction loop."""
        # is_percentage gates before parse_financial_number is called.
        assert is_percentage("4%")


class TestValueCellDiscrimination:
    @pytest.mark.parametrize("cell", [
        "15.000", "1,234,567", "(520,193)", "12%", "1.000.000 saham", "-5.000", "3,882,1",
    ])
    def test_value_cells(self, cell):
        assert _is_value_cell(cell), cell

    @pytest.mark.parametrize("cell", [
        "In 2024, the",          # prose with year
        "No. C2-10099.HT",       # reference number
        "No. 3626.",
        "Per 31 Desember",       # date phrase
        "ent No. 176",
        "No.C2-5992.HT.01.04.TH.97",
        "ties in 2024",          # prose ending in year
        "ber 2022,",
        "5 dan",                 # Indonesian prose with digit
    ])
    def test_non_value_cells(self, cell):
        assert not _is_value_cell(cell), cell


class TestSplitRow:
    def test_prose_row_rejected(self):
        """A row whose 'value' cells are prose fragments yields no data row."""
        row = ["setara kas sebesar", "Rp2,09 triliu", "ang tahun 2024"]
        assert _split_row(row) is None

    def test_clean_row(self):
        row = ["Kas dan setara kas", "15.000", "12.000"]
        split = _split_row(row)
        assert split is not None
        label, nums = split
        assert "Kas" in label
        assert nums == ["15.000", "12.000"]

    def test_reference_number_stays_in_label(self):
        row = ["No. C2-10099.HT", "Surat Setoran Pajak", "1.234"]
        split = _split_row(row)
        # Either rejected entirely, or the ref-no went to the label — never a value.
        if split is not None:
            label, nums = split
            assert nums == ["1.234"]


class TestOCRTokensTolerated:
    def test_truncated_tokens_still_parse_or_fail_gracefully(self):
        """Tokens like '2c,2n' are OCR garbage — the parser raises, and the
        processor now skips them silently instead of logging errors."""
        with pytest.raises(NumberParseError):
            parse_financial_number("2c,2n")

    def test_half_split_negative_still_parses(self):
        """'(520,193' (unclosed paren) parses as negative — common OCR crop."""
        assert parse_financial_number("(520,193") == -520193


class TestTextStrategySettings:
    """The vertical column settings decide whether a wide number survives.

    min_words_vertical=2 lets a column boundary form from an intra-number gap,
    so '21,171,173' arrives as '2' + '1,171,173' and the total reads as 2.
    """

    def test_min_words_vertical_not_overridden(self):
        assert "min_words_vertical" not in _TEXT_STRATEGY_SETTINGS

    def test_still_pins_horizontal_tolerance(self):
        # These two remain pinned: they widen the row grid and align digits.
        assert _TEXT_STRATEGY_SETTINGS["min_words_horizontal"] == 1
        assert _TEXT_STRATEGY_SETTINGS["text_x_tolerance"] == 2

    def test_strategies_are_text_aligned(self):
        assert _TEXT_STRATEGY_SETTINGS["vertical_strategy"] == "text"
        assert _TEXT_STRATEGY_SETTINGS["horizontal_strategy"] == "text"


class TestPercentageCannotBecomeMonetaryFigure:
    """A '%' token must never be stored as a currency amount.

    Found in production: `86%` printed beside an equity line was stored as
    `total_equity = 86`, and `70,93%` as `sales = 71`. Because the row was
    tagged `unit='percent'`, `is_monetary()` returned False, which exempted it
    from the monetary floors entirely -- so it passed plausibility as `status=OK`
    and then outranked the real figure (261,986,773,775) on confidence.
    """

    def test_monetary_field_is_monetary(self):
        assert is_monetary("total_equity", None)
        assert is_monetary("sales", None)
        assert is_monetary("income_tax", None)

    def test_percentage_field_is_not_monetary(self):
        # The one case where a '%' token legitimately belongs.
        assert not is_monetary("treasury_shares_percentage", None)
        assert not is_monetary("treasury_shares_quantity", None)

    def test_a_percentage_would_slip_past_the_magnitude_floors(self):
        """Why the guard has to live at the mapping step, not in plausibility."""
        # 86 is below MIN_PLAUSIBLE_MONETARY, so a monetary tagging would catch
        # it -- but with unit='percent' it is exempt and sails through.
        assert 86 < MIN_PLAUSIBLE_MONETARY
        assert not is_monetary("total_equity", "percent")
        assert not is_implausible_amount(86.0, "total_equity", "percent")

    def test_both_production_tokens_are_percentages(self):
        assert is_percentage("86%")
        assert is_percentage("70,93%")
        assert parse_percentage("86%") == 86.0
        assert parse_percentage("70,93%") == 70.93

    def test_genuine_share_percentage_still_parses(self):
        assert parse_percentage("4%") == 4.0


class TestImplausibleAmountsAreNotReportedAsVerified:
    """`status=OK` is a claim that a figure was checked and found correct.

    Demoting an implausible value in the ranking only decides which value is
    *shown*; without also demoting its status the grid presented a page number
    ('37' read as income_tax) as a verified figure.
    """

    def test_a_page_number_is_implausible(self):
        assert is_implausible_amount(37.0, "income_tax", None)
        assert is_implausible_amount(6.0, "prepaid_expenses", None)
        assert is_implausible_amount(0.0, "total_assets", None) is False

    def test_a_real_figure_is_not_implausible(self):
        assert not is_implausible_amount(261_986_773_775.0, "total_equity", None)
        assert not is_implausible_amount(3.0e12, "total_assets", None)

    def test_double_scaling_is_now_caught(self):
        """The ceiling used to admit a 1,000,000x error, which is how one printed
        figure ended up in the grid twice: 17,527,130,084 and
        17,527,130,084,000,000. The inflated copy lost the contest on confidence
        (0.855 against 0.54), so the ceiling is what has to catch it."""
        assert 17_527_130_084_000_000 > MAX_PLAUSIBLE_MONETARY
        assert is_implausible_amount(17_527_130_084_000_000.0, "net_income", None)
        # The correctly scaled reading is untouched.
        assert not is_implausible_amount(17_527_130_084.0, "net_income", None)


    if __name__ == "__main__":
        pytest.main([__file__, "-v"])
