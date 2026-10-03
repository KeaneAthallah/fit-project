"""Unit detection and value normalization.

Detects the stated unit of a financial statement (e.g. 'Dalam jutaan Rupiah',
'In millions of USD') and multiplies extracted values so they are expressed in
base currency units (1 Rupiah, 1 USD).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_UNIT_PATTERNS: list[tuple[re.Pattern[str], str, int]] = [
    # (regex, canonical unit name, multiplier)
    #
    # The Indonesian word takes an optional `-an` suffix ("juta" and "jutaan" are
    # both used, and statements mix them). Written as `an?` it would require the
    # literal "a" and match only "jutaan", so the bare form -- which is at least
    # as common, and is what most statements write -- was silently missed and the
    # figure kept the wrong multiplier.
    (re.compile(r"\btriliun(?:an)?\b|\btrillions?\b", re.I), "triliun", 1_000_000_000_000),
    (re.compile(r"\bmiliar(?:an)?\b|\bbillions?\b", re.I), "miliar", 1_000_000_000),
    (re.compile(r"\bjuta(?:an)?\b|\bmillions?\b|\bjt\b", re.I), "juta", 1_000_000),
    (re.compile(r"\bribu(?:an)?\b|\bthousands?\b|\brb\b", re.I), "ribuan", 1_000),
]

_CURRENCY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bUSD\b|\bUS\$|\bDolar\s*(?:AS|Amerika)\b|\$|^US\b", re.I), "USD"),
    (re.compile(r"\bEUR\b|\bEuro\b", re.I), "EUR"),
    (re.compile(r"\bSGD\b", re.I), "SGD"),
    (re.compile(r"\bJPY\b|\bYen\b", re.I), "JPY"),
    (re.compile(r"\bRp\b|\bRupiah\b|\bRupiahs?\b", re.I), "IDR"),
]


@dataclass
class UnitInfo:
    currency: str | None
    unit: str | None          # ribuan / juta / miliar / None
    multiplier: int           # 1 / 1_000 / 1_000_000 / ...
    raw_snippet: str | None
    confidence: float


def detect_unit(text: str) -> UnitInfo:
    """Detect currency + unit from a text snippet (usually the statement header)."""
    currency = None
    unit = None
    multiplier = 1
    confidence = 0.0
    snippet = None

    # A unit word only counts when preceded by a unit-introducing word
    # ('dalam jutaan', 'in millions', 'disajikan dalam ribuan', ...).
    # Bare mentions in narrative prose ('Rp1.15 trillion in 2024', 'in billion)'
    # fragments) must NOT set the report unit (root cause of x1e12 corruption).
    unit_intro_re = re.compile(
        r"(?:dalam|disajikan\s+dalam|expressed\s+in|in)\s+[^\n]{0,40}?",
        re.I,
    )

    for pat, cur in _CURRENCY_PATTERNS:
        m = pat.search(text)
        if m:
            currency = cur
            snippet = m.group(0)
            confidence = max(confidence, 0.7)
            break

    for pat, name, mult in _UNIT_PATTERNS:
        m = pat.search(text)
        if m and unit_intro_re.search(text):
            unit = name
            multiplier = mult
            snippet = f"{snippet} {m.group(0)}".strip() if snippet else m.group(0)
            confidence = max(confidence, 0.85)
            break

    # 'Dalam Rupiah' exactly => base unit, high confidence
    if re.search(r"[Dd]alam\s+(?:jumlah\s+)?[Rr]upiah(?!\s*\w)", text) and unit is None:
        unit = None
        multiplier = 1
        confidence = max(confidence, 0.9)

    return UnitInfo(currency=currency, unit=unit, multiplier=multiplier,
                    raw_snippet=snippet, confidence=confidence)


def normalize_value(value: float, unit_info: UnitInfo) -> float:
    """Scale a parsed value into base currency units.

    The multiplier is always a power of ten and integral, so multiplying an `int`
    by it stays an exact `int` -- a whole-rupiah figure is still whole-rupiah
    after scaling, with no float rounding anywhere in the path.
    """
    return value * unit_info.multiplier


def scale_multiplier_from_text(text: str) -> UnitInfo:
    return detect_unit(text)
