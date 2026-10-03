"""Regression tests for the false-positive validation error epidemic.

Root cause being tested: financial_page count was conflated with validation
errors, and low-confidence / missing / unmapped values all escalated to ERROR.
These tests pin the corrected behavior (requirements #20, #23, #29).
"""
from app.financial.validators import (
    ValidationCheck,
    ValidationStatus,
    aggregate_status,
    count_status,
    status_breakdown,
    validate_document,
)


def _value(v):
    return {"normalized_value": v}


# ---------------------------------------------------------------------------
# The exact scenario from the bug report: many financial pages, few values.
# ---------------------------------------------------------------------------

class TestFewValuesManyPages:
    def _sparse_doc(self, n_fields: int) -> dict:
        """A document with only a handful of extracted fields (like the logs:
        financial=126, values=31) — e.g. just total_assets + revenue."""
        return {
            "balance_sheet": {"total_assets": _value(400_000_000_000)},
            "income_statement": {"revenue": _value(120_000_000_000)},
        }

    def test_126_pages_31_values_not_126_errors(self):
        values = self._sparse_doc(31)
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0

    def test_110_pages_24_values_not_100_errors(self):
        values = {
            "balance_sheet": {"total_assets": _value(350_000_000_000),
                              "total_liabilities": _value(220_000_000_000)},
        }
        checks = validate_document(values)
        # Only NOT_APPLICABLE rows (or none) — zero ERRORs.
        errors = count_status(checks, ValidationStatus.ERROR)
        na = count_status(checks, ValidationStatus.NOT_APPLICABLE)
        assert errors == 0
        assert errors + na == len(checks)

    def test_aggregate_never_error_for_sparse_doc(self):
        values = self._sparse_doc(24)
        assert aggregate_status(validate_document(values)) != "ERROR"

    def test_empty_document_no_errors(self):
        checks = validate_document({})
        assert count_status(checks, ValidationStatus.ERROR) == 0
        assert aggregate_status(checks) in ("NOT_APPLICABLE", "NOT_FOUND")

    def test_zero_error_count_helper(self):
        """error_count must use exact status match, not len(results)."""
        checks = [
            ValidationCheck("a", None, None, None, "NOT_APPLICABLE", ""),
            ValidationCheck("b", None, None, None, "NOT_APPLICABLE", ""),
            ValidationCheck("c", None, None, None, "WARNING", ""),
            ValidationCheck("d", None, None, None, "REVIEW_REQUIRED", ""),
            ValidationCheck("e", 1, 5, -4, "ERROR", ""),
        ]
        assert count_status(checks, ValidationStatus.ERROR) == 1
        assert status_breakdown(checks) == {
            "NOT_APPLICABLE": 2, "WARNING": 1, "REVIEW_REQUIRED": 1, "ERROR": 1,
        }


# ---------------------------------------------------------------------------
# Statement applicability: empty statements produce no check rows at all.
# ---------------------------------------------------------------------------

class TestFieldAwareValidation:
    def test_no_cashflow_no_cashflow_rows(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(500), "total_liabilities": _value(300),
                "total_equity": _value(200),
            },
        }
        checks = validate_document(values)
        assert not any(c.statement == "cash_flow" for c in checks)
        assert count_status(checks, ValidationStatus.ERROR) == 0

    def test_balance_sheet_only(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(500), "total_liabilities": _value(300),
                "total_equity": _value(200),
            },
        }
        checks = validate_document(values)
        bs_check = next(c for c in checks if c.check_name == "assets_equals_liabilities_plus_equity")
        assert bs_check.status == "VALID"

    def test_notes_pages_produce_nothing(self):
        """A notes-only document (many 'financial' pages, no statement totals)
        must generate zero errors."""
        values = {
            "balance_sheet": {"cash_and_cash_equivalents": _value(15_000)},
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0


# ---------------------------------------------------------------------------
# Optional fields: missing is NOT_FOUND/NOT_APPLICABLE, never ERROR.
# ---------------------------------------------------------------------------

class TestOptionalFields:
    def test_missing_treasury_is_not_error(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(500_000_000_000),
                "total_liabilities": _value(300_000_000_000),
                "total_equity": _value(200_000_000_000),
            },
            # no treasury_shares_* at all
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0
        assert not any("treasury" in c.check_name for c in checks)

    def test_missing_additional_paid_in(self):
        values = {
            "equity": {"total_equity": _value(150_000_000)},
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0

    def test_partial_balance_sheet_incomplete_not_error(self):
        values = {
            "balance_sheet": {"total_assets": _value(500)},
        }
        checks = validate_document(values)
        bs = next(c for c in checks if c.check_name == "assets_equals_liabilities_plus_equity")
        assert bs.status == "NOT_APPLICABLE"
        assert bs.severity == "INFO"


# ---------------------------------------------------------------------------
# Real accounting inconsistencies must STILL be errors (req #27).
# ---------------------------------------------------------------------------

class TestRealErrorsStillDetected:
    def test_genuinely_wrong_balance_sheet(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(500_000_000_000),
                "total_liabilities": _value(300_000_000_000),
                "total_equity": _value(250_000_000_000),  # 300+250=550 != 500
            },
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 1

    def test_valid_balance_sheet(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(500_000_000_000),
                "total_liabilities": _value(300_000_000_000),
                "total_equity": _value(200_000_000_000),
            },
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0
        assert count_status(checks, ValidationStatus.VALID) >= 1

    def test_rounding_difference_valid_or_warning(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(100_000_000_000),
                "total_liabilities": _value(60_000_000_000),
                "total_equity": _value(40_000_001_000),  # 1000 off
            },
        }
        checks = validate_document(
            values, absolute_tolerance=1000, relative_tolerance=0.001)
        statuses = {c.status for c in checks}
        assert statuses.isdisjoint({"ERROR"})

    def test_rounding_slightly_over_tolerance_warns(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(100_000_000_000),
                "total_liabilities": _value(60_000_000_000),
                "total_equity": _value(40_500_000_000),  # 0.5% off
            },
        }
        checks = validate_document(
            values, absolute_tolerance=0, relative_tolerance=0.001)
        bs = next(c for c in checks if c.check_name == "assets_equals_liabilities_plus_equity")
        # 0.5% is within the warning band (rel <= max(10x tol, 1%)) -> WARNING
        assert bs.status == "WARNING"
        assert bs.category == "rounding_difference"


# ---------------------------------------------------------------------------
# Low confidence / negative / zero values are never validation errors.
# ---------------------------------------------------------------------------

class TestNonErrors:
    def test_negative_treasury_value(self):
        values = {
            "equity": {"treasury_shares_carrying_value": _value(-5_000_000_000)},
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0

    def test_zero_values(self):
        values = {
            "balance_sheet": {
                "total_assets": _value(0),
                "total_liabilities": _value(0),
                "total_equity": _value(0),
            },
        }
        checks = validate_document(values)
        assert count_status(checks, ValidationStatus.ERROR) == 0

    def test_period_grouping_by_caller(self):
        """The processor groups by year before validating; each year's checks
        only see that year's values. Cross-year differences never appear."""
        y2024 = {
            "balance_sheet": {
                "total_assets": _value(500_000_000_000),
                "total_liabilities": _value(300_000_000_000),
                "total_equity": _value(200_000_000_000),
            },
        }
        y2023 = {
            "balance_sheet": {
                "total_assets": _value(450_000_000_000),
                "total_liabilities": _value(280_000_000_000),
                "total_equity": _value(170_000_000_000),
            },
        }
        for period_values in (y2024, y2023):
            checks = validate_document(period_values)
            assert count_status(checks, ValidationStatus.ERROR) == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
