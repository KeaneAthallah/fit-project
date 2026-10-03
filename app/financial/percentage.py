"""Percentage value handling.

Percentages ('4%', '15,6%', '(2,5)%') are ratios, not monetary amounts.
They must never enter the monetary normalization pipeline (unit-scaling a
percentage corrupts it) and never be logged as unparseable numbers.
"""
from __future__ import annotations

import re

from app.financial.parser import NumberParseError, parse_financial_number

# Percent sign may sit before OR after the closing paren: '4%', '(2,5)%', '-2,5%'.
_PERCENT_RE = re.compile(
    r"^\s*[\(\-\u2013\u2014]?\s*(?:Rp\s*)?\d+(?:[.,]\d+)*\s*%\s*[\)]?\s*$"
    r"|^\s*[\(\-\u2013\u2014]?\s*(?:Rp\s*)?\d+(?:[.,]\d+)*\s*[\)]\s*%\s*$"
)


def is_percentage(raw: str | None) -> bool:
    """True when the whole token is a percentage like '4%' or '(2,5)%'."""
    if not raw:
        return False
    return bool(_PERCENT_RE.match(raw))


def parse_percentage(raw: str | None) -> float | None:
    """Parse '15,6%' -> 15.6 (kept in percent units, NOT scaled by report unit).

    Returns None when the token is not a percentage.
    """
    if not is_percentage(raw):
        return None
    num_part = raw.replace("%", "").strip()
    # Normalize a trailing close-paren left by the paren-order variation.
    if num_part.endswith(")") and num_part.count(")") > num_part.count("("):
        num_part = "(" + num_part
    try:
        value = parse_financial_number(num_part)
    except NumberParseError:
        return None
    return value
