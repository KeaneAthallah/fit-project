"""Accounting consistency validation — evidence-based, field-aware, cheap.

Architecture:
    - Explicit status taxonomy (requirement #8): VALID / WARNING / ERROR /
      NOT_APPLICABLE / NOT_FOUND / INCOMPLETE / REVIEW_REQUIRED / UNMAPPED.
    - Field-aware (requirement #6): a statement validator only runs when that
      statement actually contributed extracted fields. A document with no cash
      flow statement produces NO cash-flow check rows at all — not rows of
      NOT_APPLICABLE noise.
    - Minimum-data rule (requirement #7): arithmetic checks only run when every
      required value exists.
    - Dual tolerance (requirement #10): absolute OR relative, scaled by report
      unit. All comparisons on normalized values only.
    - Every check records category + evidence. Categories let the caller count
      real ERRORs separately from informational rows (requirements #21/#23).
    - Validation operates purely on already-normalized structured data —
      no PDF/OCR/AI access. Milliseconds per document (requirement #28).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ValidationStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_FOUND = "NOT_FOUND"
    INCOMPLETE = "INCOMPLETE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNMAPPED = "UNMAPPED"


class ValidationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class CheckCategory(str, Enum):
    ACCOUNTING_MATCH = "accounting_mismatch"      # arithmetic identity checks
    ROUNDING = "rounding_difference"              # slightly-above-tolerance
    MISSING_FIELD = "missing_fields"              # required-in-context field absent
    UNMAPPED_FIELD = "unmapped_fields"            # value kept, no canonical field
    INCOMPLETE_STATEMENT = "incomplete_statement" # statement present but partial
    LOW_CONFIDENCE = "low_confidence"             # review, not error


@dataclass
class ValidationCheck:
    check_name: str
    expected: float | None
    actual: float | None
    difference: float | None
    status: str
    message: str
    severity: str = ValidationSeverity.INFO.value
    statement: str | None = None
    category: str = CheckCategory.ACCOUNTING_MATCH.value
    # Evidence: which values were used and what tolerance was applied.
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check_name,
            "status": self.status,
            "severity": self.severity,
            "statement": self.statement,
            "category": self.category,
            "difference": self.difference,
            "message": self.message,
            "evidence": self.evidence,
        }


def _unit_scale_hint(values: dict[str, dict[str, Any]]) -> float:
    """Infer a magnitude scale from the largest normalized value present, so the
    absolute tolerance scales with the statement unit (ribuan/jutaan/miliaran)."""
    magnitudes = [
        abs(float(e.get("normalized_value")))
        for stmt in values.values()
        for e in stmt.values()
        if e.get("normalized_value") is not None
    ]
    if not magnitudes:
        return 1.0
    m = max(magnitudes)
    if m >= 1e12:
        return 1e6
    if m >= 1e9:
        return 1e3
    return 1.0


def _check_difference(
    name: str,
    expected: float,
    actual: float,
    abs_tol: float,
    rel_tol: float,
    statement: str | None = None,
    evidence_extra: dict[str, Any] | None = None,
    unit_scale: float = 1.0,
) -> ValidationCheck:
    """Compare expected vs actual with absolute OR relative tolerance."""
    diff = actual - expected
    abs_diff = abs(diff)
    denom = max(abs(expected), 1.0)
    rel_diff = abs_diff / denom

    scaled_abs_tol = abs_tol * unit_scale

    evidence = {
        "equation": name,
        "expected": expected,
        "actual": actual,
        "absolute_difference": abs_diff,
        "relative_difference": round(rel_diff, 8),
        "absolute_tolerance": scaled_abs_tol,
        "relative_tolerance": rel_tol,
        "unit_scale": unit_scale,
    }
    if evidence_extra:
        evidence.update(evidence_extra)

    if abs_diff <= scaled_abs_tol or rel_diff <= rel_tol:
        return ValidationCheck(
            name, expected, actual, diff, ValidationStatus.VALID.value,
            f"Difference {abs_diff:,.2f} within tolerance "
            f"(abs<={scaled_abs_tol:,.0f} or rel<={rel_tol:.4%})",
            ValidationSeverity.INFO.value, statement,
            CheckCategory.ACCOUNTING_MATCH.value, evidence,
        )
    if rel_diff <= max(rel_tol * 10, 0.01):
        return ValidationCheck(
            name, expected, actual, diff, ValidationStatus.WARNING.value,
            f"Rounding difference {abs_diff:,.2f} ({rel_diff:.4%}) slightly above tolerance",
            ValidationSeverity.WARNING.value, statement,
            CheckCategory.ROUNDING.value, evidence,
        )
    return ValidationCheck(
        name, expected, actual, diff, ValidationStatus.ERROR.value,
        f"Difference {abs_diff:,.2f} ({rel_diff:.4%}) exceeds tolerance",
        ValidationSeverity.ERROR.value, statement,
        CheckCategory.ACCOUNTING_MATCH.value, evidence,
    )


def _not_applicable(name: str, missing: list[str], statement: str | None = None) -> ValidationCheck:
    return ValidationCheck(
        name, None, None, None, ValidationStatus.NOT_APPLICABLE.value,
        f"Insufficient data: missing {', '.join(missing)}",
        ValidationSeverity.INFO.value, statement,
        CheckCategory.MISSING_FIELD.value,
        {"missing_fields": missing, "reason": "Insufficient data"},
    )


def _get(values: dict[str, dict[str, dict[str, Any]]], statement: str, field: str) -> float | None:
    entry = values.get(statement, {}).get(field)
    if entry is None:
        return None
    v = entry.get("normalized_value")
    return float(v) if v is not None else None


def _statement_has_data(values: dict[str, dict[str, Any]]) -> bool:
    """True when the statement contributed at least one usable value."""
    return any(
        e.get("normalized_value") is not None
        for e in values.values()
    )


def validate_document(
    values: dict[str, dict[str, dict[str, Any]]],
    tolerance: float = 0.01,
    absolute_tolerance: float = 1_000.0,
    relative_tolerance: float = 0.001,
) -> list[ValidationCheck]:
    """Validate a per-year set of values: {statement: {field: {normalized_value: ...}}}.

    Field-aware: validators only run against statements that actually produced
    extracted fields. All comparisons happen on normalized (unit-scaled) values
    within a single reporting period — periods are never mixed (requirements
    #11/#12; the caller groups by year).
    """
    checks: list[ValidationCheck] = []
    scale = _unit_scale_hint(values)

    bs = values.get("balance_sheet", {})
    ist = values.get("income_statement", {})
    cf = values.get("cash_flow", {})

    def run(name: str, statement: str, required: list[tuple[str, str]], fn) -> None:
        """Run an arithmetic check only when all required values exist AND the
        statement actually contributed data (requirement #6/#7)."""
        got = {f: _get(values, s, f) for s, f in required}
        missing = [f for f, v in got.items() if v is None]
        if missing:
            # Only emit a NOT_APPLICABLE row when the statement has at least
            # some data — otherwise skip silently (no noise rows).
            if _statement_has_data(values.get(statement, {})):
                checks.append(_not_applicable(name, missing, statement))
            return
        checks.append(fn(got))

    def run_with_topline(
        name: str, statement: str, alternatives: list[str],
        required: list[tuple[str, str]], fn,
    ) -> None:
        """Like `run`, but the top of the identity may be any one of several
        fields.

        A report labels the same top line 'Penjualan' or 'Pendapatan', which map
        to `sales` and `revenue` respectively. Requiring one specific slug would
        silently stop the check from running on half the corpus.
        """
        got = {f: _get(values, s, f) for s, f in required}
        chosen: str | None = None
        for alt in alternatives:
            if _get(values, statement, alt) is not None:
                chosen = alt
                break
        missing = [f for f, v in got.items() if v is None]
        if chosen is None:
            missing = [*alternatives, *missing]
        if missing:
            if _statement_has_data(values.get(statement, {})):
                checks.append(_not_applicable(name, missing, statement))
            return
        got["top"] = _get(values, statement, chosen)
        got["top_field"] = chosen
        checks.append(fn(got))

    # ---------------- Balance sheet (only if BS fields exist) --------------
    if _statement_has_data(bs):
        ta = _get(values, "balance_sheet", "total_assets")
        tl = _get(values, "balance_sheet", "total_liabilities")
        te = _get(values, "balance_sheet", "total_equity")

        # 1. Assets = Liabilities + Equity
        if None not in (ta, tl, te):
            checks.append(_check_difference(
                "assets_equals_liabilities_plus_equity", ta, tl + te,
                absolute_tolerance, relative_tolerance, "balance_sheet",
                evidence_extra={"values_used": {"total_assets": ta, "total_liabilities": tl,
                                                "total_equity": te}},
                unit_scale=scale,
            ))
        elif ta is not None:
            # Total assets alone is not enough to judge the equation.
            missing = [n for n, v in (("total_liabilities", tl), ("total_equity", te)) if v is None]
            checks.append(_not_applicable(
                "assets_equals_liabilities_plus_equity", missing, "balance_sheet"))

        # 2. Total assets = current + non-current
        run("assets_split", "balance_sheet",
            [("balance_sheet", "total_assets"), ("balance_sheet", "current_assets"),
             ("balance_sheet", "non_current_assets")],
            lambda g: _check_difference("assets_split", g["total_assets"],
                                        g["current_assets"] + g["non_current_assets"],
                                        absolute_tolerance, relative_tolerance,
                                        "balance_sheet", unit_scale=scale))

        # 3. Total liabilities = current + non-current
        run("liabilities_split", "balance_sheet",
            [("balance_sheet", "total_liabilities"), ("balance_sheet", "current_liabilities"),
             ("balance_sheet", "non_current_liabilities")],
            lambda g: _check_difference("liabilities_split", g["total_liabilities"],
                                        g["current_liabilities"] + g["non_current_liabilities"],
                                        absolute_tolerance, relative_tolerance,
                                        "balance_sheet", unit_scale=scale))
    # No BS data -> no BS checks at all. Missing statements are normal.

    # ---------------- Income statement -------------------------------------
    if _statement_has_data(ist):
        def _gp_check(g: dict) -> ValidationCheck:
            # Presentation varies: cost of revenue may be stored as a negative
            # number '(18,474.41)' or as a positive expense '18,474.41'.
            # Normalize to a positive expense magnitude before subtracting.
            cost = abs(g["cost_of_revenue"])
            return _check_difference("gross_profit_identity",
                                     g["top"] - cost, g["gross_profit"],
                                     absolute_tolerance, relative_tolerance,
                                     "income_statement", unit_scale=scale,
                                     evidence_extra={"top_line": g["top_field"]})

        # Either 'sales' (Penjualan) or 'revenue' (Pendapatan) may be the top line.
        run_with_topline("gross_profit_identity", "income_statement", ["sales", "revenue"],
                         [("income_statement", "cost_of_revenue"),
                          ("income_statement", "gross_profit")],
                         _gp_check)

        run("net_income_identity", "income_statement",
            [("income_statement", "profit_before_tax"), ("income_statement", "income_tax"),
             ("income_statement", "net_income")],
            lambda g: _check_difference("net_income_identity",
                                        g["profit_before_tax"] - g["income_tax"], g["net_income"],
                                        absolute_tolerance, relative_tolerance,
                                        "income_statement", unit_scale=scale))

    # ---------------- Cash flow ---------------------------------------------
    begin = _get(values, "cash_flow", "beginning_cash_balance")
    end = _get(values, "cash_flow", "ending_cash_balance")
    if _statement_has_data(cf):
        ops = _get(values, "cash_flow", "cash_flow_operating")
        inv = _get(values, "cash_flow", "cash_flow_investing")
        fin = _get(values, "cash_flow", "cash_flow_financing")
        if None not in (begin, end, ops, inv, fin):
            checks.append(_check_difference("cash_flow_reconciliation", end,
                                            begin + ops + inv + fin,
                                            absolute_tolerance, relative_tolerance,
                                            "cash_flow", unit_scale=scale))
        elif begin is not None and end is not None:
            netchange = _get(values, "cash_flow", "net_change_in_cash")
            if netchange is not None:
                checks.append(_check_difference("cash_change_reconciliation", end,
                                                begin + netchange,
                                                absolute_tolerance, relative_tolerance,
                                                "cash_flow", unit_scale=scale))
            else:
                checks.append(_not_applicable(
                    "cash_flow_reconciliation", ["net_change_in_cash"], "cash_flow"))
        # else: not enough cash-flow values — no check row, no error.

    # Cash-flow ending balance vs balance-sheet cash (cross-statement check).
    cash_bs = _get(values, "balance_sheet", "cash_and_cash_equivalents")
    if end is not None and cash_bs is not None:
        checks.append(_check_difference("cash_matches_balance_sheet", end, cash_bs,
                                        absolute_tolerance, relative_tolerance,
                                        "cash_flow", unit_scale=scale))

    # ---------------- Equity -------------------------------------------------
    eq = values.get("equity", {})
    if _statement_has_data(eq):
        # Treasury shares sign sanity — negative carrying value is NORMAL
        # (contra-equity). Positive value gets a WARNING only (requirement #18).
        tsc = _get(values, "equity", "treasury_shares_carrying_value")
        if tsc is not None and tsc > 0:
            checks.append(ValidationCheck(
                "treasury_shares_positive_value", None, tsc, None,
                ValidationStatus.WARNING.value,
                "Treasury shares carrying value is positive; usually presented as "
                "a deduction (negative). Verify column interpretation.",
                ValidationSeverity.WARNING.value, "equity",
                CheckCategory.LOW_CONFIDENCE.value,
                {"values_used": {"treasury_shares_carrying_value": tsc}},
            ))
        # NOTE: no authorized == issued == paid-up capital checks (req #11/#17).
        # Missing optional equity fields are simply not checked at all (#15/#16).

    if not checks:
        # Document-level signal without counting as an error.
        checks.append(ValidationCheck(
            "no_checks_possible", None, None, None,
            ValidationStatus.NOT_APPLICABLE.value,
            "Not enough statement fields extracted to run any validation",
            ValidationSeverity.INFO.value, None,
            CheckCategory.INCOMPLETE_STATEMENT.value,
        ))
    return checks


def count_status(checks: list[ValidationCheck], status: ValidationStatus | str) -> int:
    """Count checks with an exact status. Only ERROR counts as an error —
    WARNING / NOT_FOUND / NOT_APPLICABLE / UNMAPPED / REVIEW_REQUIRED never do
    (requirement #23)."""
    s = status.value if isinstance(status, ValidationStatus) else status
    return sum(1 for c in checks if c.status == s)


def aggregate_status(checks: list[ValidationCheck]) -> str:
    """Aggregate check statuses into a document-level validation status.

    Only real ERRORs escalate; NOT_APPLICABLE/NOT_FOUND/UNMAPPED never do.
    """
    statuses = [c.status for c in checks]
    if any(s == ValidationStatus.ERROR.value for s in statuses):
        return ValidationStatus.ERROR.value
    if any(s == ValidationStatus.WARNING.value for s in statuses):
        return ValidationStatus.WARNING.value
    if any(s == ValidationStatus.REVIEW_REQUIRED.value for s in statuses):
        return ValidationStatus.REVIEW_REQUIRED.value
    if any(s == ValidationStatus.VALID.value for s in statuses):
        return ValidationStatus.VALID.value
    if any(s == ValidationStatus.NOT_APPLICABLE.value for s in statuses):
        return ValidationStatus.NOT_APPLICABLE.value
    return ValidationStatus.NOT_FOUND.value


def status_breakdown(checks: list[ValidationCheck]) -> dict[str, int]:
    """Full status histogram for logs/diagnostics (requirement #22)."""
    out: dict[str, int] = {}
    for c in checks:
        out[c.status] = out.get(c.status, 0) + 1
    return out
