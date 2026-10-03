import pytest

from app.financial.parser import NumberParseError, looks_like_number, parse_financial_number


class TestIndonesianNumbers:
    def test_thousands_dots(self):
        assert parse_financial_number("1.234.567") == 1234567.0

    def test_decimal_comma(self):
        assert parse_financial_number("1.234.567,89") == 1234567.89

    def test_simple_decimal(self):
        assert parse_financial_number("1.234,56") == 1234.56

    def test_currency_prefix(self):
        assert parse_financial_number("Rp 1.234.567.890") == 1234567890.0

    def test_parentheses_negative(self):
        assert parse_financial_number("(1.500.000)") == -1500000.0

    def test_minus_sign(self):
        assert parse_financial_number("-1.234.567") == -1234567.0

    def test_plain_integer(self):
        assert parse_financial_number("5000") == 5000.0


class TestEnglishNumbers:
    def test_comma_thousands(self):
        assert parse_financial_number("1,234,567") == 1234567.0

    def test_comma_thousands_decimal(self):
        assert parse_financial_number("1,234,567.89") == 1234567.89

    def test_english_decimal(self):
        assert parse_financial_number("1234.56") == 1234.56


class TestNoValue:
    def test_dash(self):
        assert parse_financial_number("-") is None

    def test_en_dash(self):
        assert parse_financial_number("–") is None

    def test_empty(self):
        assert parse_financial_number("") is None

    def test_none(self):
        assert parse_financial_number(None) is None

    def test_n_a(self):
        assert parse_financial_number("n/a") is None


class TestEdgeCases:
    def test_spaces_in_number(self):
        assert parse_financial_number("1 234 567") == 1234567.0

    def test_trailing_period(self):
        assert parse_financial_number("1.234.567.") == 1234567.0

    def test_invalid_raises(self):
        with pytest.raises(NumberParseError):
            parse_financial_number("12.34.567")  # bad grouping, not decimal

    def test_truncated_tail_returns_none(self):
        """Digits lost at a cell boundary must not become a fabricated value."""
        for raw in ("1.", "30.", "9.", "021,", "(14,", "(68,", "(4,"):
            assert parse_financial_number(raw) is None, raw

    def test_complete_number_with_trailing_separator_still_parses(self):
        """A multi-group number keeps its value; the trailing mark is stray."""
        assert parse_financial_number("1.234.567.") == 1234567.0
        assert parse_financial_number("28,793,225,") == 28793225.0

    def test_real_small_values_unaffected(self):
        """Rejecting truncations must not drop legitimate small figures."""
        assert parse_financial_number("1") == 1.0
        assert parse_financial_number("1,5") == 1.5
        assert parse_financial_number("12") == 12.0
        assert parse_financial_number("0,5") == 0.5

    def test_looks_like_number(self):
        assert looks_like_number("1.234")
        assert not looks_like_number("-")
        assert not looks_like_number("")


if __name__ == "__main__":
    pytest.main([__file__])
