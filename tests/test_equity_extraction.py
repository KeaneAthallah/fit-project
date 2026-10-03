"""Tests for the new equity/share-capital extraction (requirements #1-#3, #10, #34)."""
import pytest

from app.financial.mappings import map_label, resolve_treasury_field
from app.financial.parser import (
    correct_ocr_number,
    is_share_quantity,
    parse_financial_number,
    parse_share_quantity,
)


class TestIssuedAndPaidUpCapitalMapping:
    @pytest.mark.parametrize("label", [
        "Modal Ditempatkan dan Disetor",
        "Modal Ditempatkan & Disetor",
        "Modal Ditempatkan",
        "Modal Disetor",
        "Issued and Paid-up Capital",
        "Issued and Paid Up Capital",
        "Issued Capital",
        "Paid-up Capital",
        "Paid Up Capital",
        "Share Capital",
    ])
    def test_variations_map(self, label):
        field, conf = map_label(label)
        assert field in (
            "issued_and_paid_up_capital", "issued_capital", "paid_up_capital",
        ), f"{label!r} mapped to {field!r}"
        assert conf >= 0.85

    def test_context_balancesheet(self):
        field, _ = map_label("Modal Ditempatkan dan Disetor", "balance_sheet")
        assert field == "issued_and_paid_up_capital"

    def test_authorized_is_separate(self):
        field, _ = map_label("Modal Dasar", "equity")
        assert field == "authorized_capital"

    def test_field_in_field_labels(self):
        from app.financial.mappings import FIELD_LABELS
        assert "issued_and_paid_up_capital" in FIELD_LABELS["equity"]
        assert "issued_and_paid_up_capital" in FIELD_LABELS["balance_sheet"]


class TestTreasuryMapping:
    @pytest.mark.parametrize("label", [
        "Saham Treasuri", "Saham Treasury", "Saham Tresuri", "Treasury Shares",
        "Treasury Stock", "Repurchased Shares", "Shares Repurchased",
        "Modal Saham yang Diperoleh Kembali", "Saham yang Diperoleh Kembali",
    ])
    def test_variations_map(self, label):
        field, conf = map_label(label, "equity")
        assert field in ("treasury_shares_quantity", "treasury_shares_carrying_value"), \
            f"{label!r} mapped to {field!r}"
        assert conf >= 0.85

    def test_resolve_quantity(self):
        assert resolve_treasury_field("1.000.000 saham") == "treasury_shares_quantity"
        assert resolve_treasury_field("1,250,000 shares") == "treasury_shares_quantity"

    def test_resolve_carrying_value(self):
        assert resolve_treasury_field("(5.000.000.000)") == "treasury_shares_carrying_value"
        assert resolve_treasury_field("Rp 5.000.000.000") == "treasury_shares_carrying_value"

    def test_resolve_percentage(self):
        assert resolve_treasury_field("2,5%") == "treasury_shares_percentage"
        assert resolve_treasury_field("5 percent") == "treasury_shares_percentage"


class TestShareQuantityParsing:
    def test_case2_quantity(self):
        """Spec case 2: '1.250.000 saham' -> quantity 1250000, NOT money."""
        qty = parse_share_quantity("1.250.000 saham")
        assert qty == 1_250_000

    def test_quantity_english(self):
        assert parse_share_quantity("6,000,000 shares") == 6_000_000

    def test_not_a_quantity(self):
        assert parse_share_quantity("(5.000.000.000)") is None
        assert parse_share_quantity("Rp 1.234.567") is None
        assert parse_share_quantity("-") is None

    def test_is_share_quantity(self):
        assert is_share_quantity("1.000.000 saham")
        assert not is_share_quantity("1.000.000")

    def test_quantity_never_negative_money(self):
        """'Saham Treasuri 1.000.000 saham' must NOT become -1000000 Rupiah."""
        qty = parse_share_quantity("1.000.000 saham")
        assert qty == 1_000_000
        assert qty > 0


class TestTreasuryNegativeValue:
    def test_case3_parentheses_negative(self):
        """Spec case 3: '(5.000.000.000)' -> carrying value -5000000000."""
        assert parse_financial_number("(5.000.000.000)") == -5_000_000_000

    def test_negative_sign(self):
        assert parse_financial_number("-5.000.000.000") == -5_000_000_000


class TestOCRCorrection:
    def test_o_to_zero(self):
        assert correct_ocr_number("1.234.OOO") == "1.234.000"

    def test_l_to_one(self):
        assert correct_ocr_number("Rp l.234.567") == "Rp 1.234.567"

    def test_comma_variant(self):
        assert correct_ocr_number("1,234,OOO") == "1,234,000"

    def test_words_untouched(self):
        assert correct_ocr_number("Modal") == "Modal"
        assert correct_ocr_number("Laba ditahan") == "Laba ditahan"
        assert correct_ocr_number("Otoritas Jasa Keuangan") == "Otoritas Jasa Keuangan"

    def test_correction_feeds_parser(self):
        assert parse_financial_number("1.234.OOO") == 1_234_000
        assert parse_financial_number("Rp l.234.567") == 1_234_567


class TestEquityFieldCoverage:
    def test_all_required_equity_fields_exist(self):
        from app.financial.mappings import FIELD_LABELS
        equity = FIELD_LABELS["equity"]
        for f in [
            "authorized_capital", "issued_capital", "paid_up_capital",
            "issued_and_paid_up_capital", "treasury_shares_quantity",
            "treasury_shares_nominal_value", "treasury_shares_carrying_value",
            "additional_paid_in_capital", "retained_earnings",
            "appropriated_retained_earnings", "unappropriated_retained_earnings",
            "other_comprehensive_income", "other_equity_components",
            "non_controlling_interest", "total_equity",
        ]:
            assert f in equity, f"missing equity field {f}"

    def test_non_controlling_interest(self):
        field, _ = map_label("Kepentingan Non Pengendali", "equity")
        assert field == "non_controlling_interest"


if __name__ == "__main__":
    pytest.main([__file__])
