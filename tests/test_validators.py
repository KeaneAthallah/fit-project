import pytest

from app.financial.validators import (
    ValidationCheck,
    ValidationSeverity,
    aggregate_status,
    validate_document,
)


def _doc(*triples):
    """Build {statement: {field: {normalized_value: ...}}} from (statement, field, value)."""
    values: dict = {}
    for statement, field, value in triples:
        values.setdefault(statement, {})[field] = {"normalized_value": value}
    return values


def _check(checks, name):
    return next(c for c in checks if c.check_name == name)


class TestBalanceSheetIdentity:
    def test_balanced(self):
        values = _doc(
            ("balance_sheet", "total_assets", 500),
            ("balance_sheet", "total_liabilities", 300),
            ("balance_sheet", "total_equity", 200),
        )
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert check.status == "VALID"

    def test_unbalanced(self):
        values = _doc(
            ("balance_sheet", "total_assets", 500_000_000),
            ("balance_sheet", "total_liabilities", 300_000_000),
            ("balance_sheet", "total_equity", 100_000_000),
        )
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert check.status in ("WARNING", "ERROR")

    def test_unbalanced_small_numbers_still_flagged_when_far_off(self):
        """A 100-unit diff on tiny totals exceeds both default tolerances."""
        values = _doc(
            ("balance_sheet", "total_assets", 500),
            ("balance_sheet", "total_liabilities", 300),
            ("balance_sheet", "total_equity", 100),
        )
        check = _check(
            validate_document(values, absolute_tolerance=0, relative_tolerance=0.001),
            "assets_equals_liabilities_plus_equity",
        )
        assert check.status in ("WARNING", "ERROR")

    def test_within_tolerance(self):
        values = _doc(
            ("balance_sheet", "total_assets", 100),
            ("balance_sheet", "total_liabilities", 50),
            ("balance_sheet", "total_equity", 50.5),  # 0.5% off
        )
        check = _check(validate_document(values, tolerance=0.01),
                       "assets_equals_liabilities_plus_equity")
        assert check.status == "VALID"

    def test_missing_fields_not_applicable(self):
        """Requirement #5: missing equity => NOT_APPLICABLE, never ERROR."""
        values = _doc(("balance_sheet", "total_assets", 500))
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert check.status == "NOT_APPLICABLE"

    def test_case5_partial_missing(self):
        """Spec case 5: A=100B, L=60B, equity missing -> NOT_APPLICABLE."""
        values = _doc(
            ("balance_sheet", "total_assets", 100_000_000_000),
            ("balance_sheet", "total_liabilities", 60_000_000_000),
        )
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert check.status == "NOT_APPLICABLE"
        assert check.severity == ValidationSeverity.INFO.value

    def test_case4_valid(self):
        """Spec case 4: A=100B, L=60B, E=40B -> VALID."""
        values = _doc(
            ("balance_sheet", "total_assets", 100_000_000_000),
            ("balance_sheet", "total_liabilities", 60_000_000_000),
            ("balance_sheet", "total_equity", 40_000_000_000),
        )
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert check.status == "VALID"
        assert check.difference == 0

    def test_case6_warning_within_tolerance(self):
        """Spec case 6: 1000 difference on 100B -> within tolerance -> VALID
        (or WARNING at stricter settings), never ERROR."""
        values = _doc(
            ("balance_sheet", "total_assets", 100_000_000_000),
            ("balance_sheet", "total_liabilities", 60_000_000_000),
            ("balance_sheet", "total_equity", 40_000_001_000),
        )
        check = _check(
            validate_document(values, absolute_tolerance=1000, relative_tolerance=0.001),
            "assets_equals_liabilities_plus_equity",
        )
        assert check.status in ("VALID", "WARNING")
        assert check.status != "ERROR"


class TestTolerances:
    def test_absolute_tolerance_passes_small_diff(self):
        values = _doc(
            ("balance_sheet", "total_assets", 1_000_000),
            ("balance_sheet", "total_liabilities", 600_000),
            ("balance_sheet", "total_equity", 400_900),
        )
        # diff = 100 < abs tol 1000 -> VALID
        check = _check(validate_document(values, absolute_tolerance=1000),
                       "assets_equals_liabilities_plus_equity")
        assert check.status == "VALID"

    def test_relative_tolerance_passes_proportional_diff(self):
        values = _doc(
            ("balance_sheet", "total_assets", 100_000_000_000),
            ("balance_sheet", "total_liabilities", 60_000_000_000),
            ("balance_sheet", "total_equity", 40_050_000_000),
        )
        # diff = 50M / 100B = 0.05% < 0.1% rel tol -> VALID
        check = _check(validate_document(values, relative_tolerance=0.001),
                       "assets_equals_liabilities_plus_equity")
        assert check.status == "VALID"

    def test_unit_scale_bumps_absolute_tolerance(self):
        """Values stated in millions get a scaled absolute tolerance."""
        values = _doc(
            ("balance_sheet", "total_assets", 100_000_000_000),
            ("balance_sheet", "total_liabilities", 60_000_000_000),
            ("balance_sheet", "total_equity", 40_000_500_000),
        )
        check = _check(validate_document(values, absolute_tolerance=1000),
                       "assets_equals_liabilities_plus_equity")
        # unit scale 1e6 => abs tol effectively 1e9; diff 500M < 1e9 -> VALID
        assert check.status == "VALID"


class TestEvidence:
    def test_evidence_present(self):
        values = _doc(
            ("balance_sheet", "total_assets", 500),
            ("balance_sheet", "total_liabilities", 300),
            ("balance_sheet", "total_equity", 200),
        )
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert check.evidence["expected"] == 500
        assert check.evidence["actual"] == 500  # actual = liabilities + equity
        assert "total_assets" in str(check.evidence["values_used"])
        assert "absolute_tolerance" in check.evidence
        assert "relative_tolerance" in check.evidence

    def test_na_evidence_lists_missing(self):
        values = _doc(("balance_sheet", "total_assets", 500))
        check = _check(validate_document(values), "assets_equals_liabilities_plus_equity")
        assert "total_equity" in check.evidence["missing_fields"]


class TestIncomeStatement:
    def test_gross_profit_ok(self):
        values = _doc(
            ("income_statement", "revenue", 100),
            ("income_statement", "cost_of_revenue", 70),
            ("income_statement", "gross_profit", 30),
        )
        check = _check(validate_document(values), "gross_profit_identity")
        assert check.status == "VALID"

    def test_gross_profit_ok_with_sales_instead_of_revenue(self):
        """A report that labels its top line 'Penjualan' has no `revenue`.

        The identity has to run on `sales` too, otherwise every such report
        silently loses the check instead of being validated.
        """
        values = _doc(
            ("income_statement", "sales", 100),
            ("income_statement", "cost_of_revenue", 70),
            ("income_statement", "gross_profit", 30),
        )
        check = _check(validate_document(values), "gross_profit_identity")
        assert check.status == "VALID"

    def test_gross_profit_reports_the_top_line_it_used(self):
        values = _doc(
            ("income_statement", "sales", 100),
            ("income_statement", "cost_of_revenue", 70),
            ("income_statement", "gross_profit", 30),
        )
        check = _check(validate_document(values), "gross_profit_identity")
        assert check.evidence.get("top_line") == "sales"

    def test_gross_profit_not_applicable_without_a_top_line(self):
        values = _doc(
            ("income_statement", "cost_of_revenue", 70),
            ("income_statement", "gross_profit", 30),
        )
        check = _check(validate_document(values), "gross_profit_identity")
        assert check.status == "NOT_APPLICABLE"
        assert "sales" in check.message and "revenue" in check.message

    def test_gross_profit_catches_a_bad_sales_figure(self):
        # Magnitudes must clear the default absolute tolerance (1,000) for the
        # mismatch to register at all.
        values = _doc(
            ("income_statement", "sales", 1_000_000),
            ("income_statement", "cost_of_revenue", 700_000),
            ("income_statement", "gross_profit", 310_000),
        )
        check = _check(validate_document(values), "gross_profit_identity")
        assert check.status == "ERROR"

    def test_net_income_ok(self):
        values = _doc(
            ("income_statement", "profit_before_tax", 50),
            ("income_statement", "income_tax", 10),
            ("income_statement", "net_income", 40),
        )
        check = _check(validate_document(values), "net_income_identity")
        assert check.status == "VALID"


class TestCashFlow:
    def test_reconciliation_ok(self):
        values = _doc(
            ("cash_flow", "beginning_cash_balance", 10),
            ("cash_flow", "cash_flow_operating", 25),
            ("cash_flow", "cash_flow_investing", -10),
            ("cash_flow", "cash_flow_financing", -5),
            ("cash_flow", "ending_cash_balance", 20),
        )
        check = _check(validate_document(values), "cash_flow_reconciliation")
        assert check.status == "VALID"

    def test_ending_matches_balance_sheet(self):
        values = _doc(
            ("cash_flow", "ending_cash_balance", 20),
            ("balance_sheet", "cash_and_cash_equivalents", 20),
        )
        check = _check(validate_document(values), "cash_matches_balance_sheet")
        assert check.status == "VALID"


class TestTreasuryAndEquity:
    def test_negative_treasury_value_no_error(self):
        """Negative treasury carrying value is normal — no ERROR may appear."""
        values = _doc(
            ("balance_sheet", "total_assets", 500),
            ("balance_sheet", "total_liabilities", 300),
            ("balance_sheet", "total_equity", 200),
            ("equity", "treasury_shares_carrying_value", -5_000_000_000),
        )
        checks = validate_document(values)
        assert not any(c.status == "ERROR" for c in checks)

    def test_missing_treasury_not_flagged(self):
        """Missing treasury shares is NOT_FOUND territory — no ERROR, no WARNING."""
        values = _doc(
            ("balance_sheet", "total_assets", 500),
            ("balance_sheet", "total_liabilities", 300),
            ("balance_sheet", "total_equity", 200),
        )
        checks = validate_document(values)
        treasury_checks = [c for c in checks if "treasury" in c.check_name]
        assert not any(c.status == "ERROR" for c in treasury_checks)

    def test_positive_treasury_value_warns_only(self):
        values = _doc(
            ("equity", "treasury_shares_carrying_value", 5_000_000),
        )
        checks = validate_document(values)
        tcheck = _check(checks, "treasury_shares_positive_value")
        assert tcheck.status == "WARNING"

    def test_no_authorized_equals_issued_check(self):
        """Authorized vs issued vs paid-up capital are never compared (req #11)."""
        values = _doc(
            ("equity", "authorized_capital", 10_000_000_000),
            ("equity", "issued_capital", 6_000_000_000),
            ("equity", "paid_up_capital", 6_000_000_000),
        )
        checks = validate_document(values)
        assert not any("authorized" in c.check_name for c in checks)


class TestAggregation:
    def test_no_data_not_error(self):
        checks = validate_document({})
        assert aggregate_status(checks) in ("NOT_APPLICABLE", "NOT_FOUND", "REVIEW_REQUIRED")
        assert aggregate_status(checks) != "ERROR"

    def test_aggregate_error_wins(self):
        checks = [
            ValidationCheck("a", 1, 1, 0, "VALID", ""),
            ValidationCheck("b", 1, 5, -4, "ERROR", ""),
        ]
        assert aggregate_status(checks) == "ERROR"

    def test_aggregate_na_only(self):
        checks = [
            ValidationCheck("a", None, None, None, "NOT_APPLICABLE", ""),
        ]
        assert aggregate_status(checks) == "NOT_APPLICABLE"


if __name__ == "__main__":
    pytest.main([__file__])
