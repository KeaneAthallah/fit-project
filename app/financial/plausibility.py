"""Magnitude plausibility for extracted monetary amounts.

Indonesian annual reports state their unit in the statement header ("dinyatakan
dalam jutaan rupiah"), and that unit is applied to a whole page. Two failures
follow, and both were silently poisoning every accounting identity check:

1. Table extraction emits bare fragments. A page whose columns interleave
   produces tokens like '1', '4', '( 3' next to the real figures, and those
   fragments were stored as real amounts. 1,999 of them existed, including
   `total_assets = 1`, which then destroyed assets_split for that year.

2. The unit word is picked up from incidental prose. A note reading "dinyatakan
   dalam ribuan" on a page whose actual figures are already full rupiah
   (`4.223.727.970.626`) multiplied a correct number by 1,000.

Both are detectable without a model: a listed company's statement line items are
never below one miliar rupiah, and a page whose numbers are already
rupiah-scale is not stated in thousands.

This module is the single definition of "implausible"; the exporter imports it
rather than keeping its own threshold, so a row can never be flagged in one
place and silently accepted in another.
"""
from __future__ import annotations

import re

# The floor below a monetary figure is not implausible is expressed in the
# currency the filing actually reported, not in rupiah for everything. It used
# to be one rupiah constant, which flagged correct figures for two unrelated
# reasons:
#
#   - A currency mismatch. PMMP's 2024 total loss of -122,921,818 USD is an
#     ordinary listed-company result; it was flagged only because 1.2e8 is below
#     a 1e9 rupiah threshold. 632 such rows were USD.
#   - A filer reporting in whole currency units. A non-controlling interest of
#     19,757 rupiah is what the filing says, and it is real.
#
# The floor exists to catch a mis-detected scale multiplier, so it can only be
# judged against the scale that was actually applied -- see
# `minimum_plausible_monetary`.
_MIN_PLAUSIBLE_MONETARY_BY_CURRENCY = {
    "IDR": 1_000_000_000.0,
    "USD": 100_000.0,
}
# An undetected currency is held to the rupiah floor rather than a relaxed one:
# the corpus is overwhelmingly rupiah, and where the currency was genuinely not
# read the conservative threshold is the right default.
_MIN_PLAUSIBLE_MONETARY_DEFAULT = 1_000_000_000.0

# Floor for a row in plain currency units, where no rupiah-scale assumption may
# be made. Low enough to pass any real whole-rupiah or whole-dollar amount, high
# enough to still reject a stray fragment: a page number or a stray digit read
# as money lands far below it.
_MIN_PLAUSIBLE_PLAIN_UNITS = 1_000.0

# Multiplier each recognised unit label stands for. Recorded so the scale a row
# was read at is inspectable next to the floors derived from it.
MULTIPLIER_BY_UNIT = {
    "ribuan": 1_000.0,
    "juta": 1_000_000.0,
    "miliar": 1_000_000_000.0,
}

# Kept as the module-level name callers and tests import. It is the rupiah floor,
# which is what a row in rupiah at a recognised scale is held to.
MIN_PLAUSIBLE_MONETARY = _MIN_PLAUSIBLE_MONETARY_BY_CURRENCY["IDR"]

# Ceiling for a single reported line item, used to catch a unit multiplier
# applied too many times.
#
# Total assets of the largest Indonesian listed companies sit near 1e14 rupiah;
# authorized capital of the most extreme is under 3e15. A ceiling of 1e16 leaves
# roughly 3x headroom above the largest real figure while still rejecting a
# single mistyped unit. 1e17 was too loose to do that job: it admitted a value
# inflated by a full 1,000,000x, which is exactly the error this bounds.
MAX_PLAUSIBLE_MONETARY = 1e16

# Ceiling applied to a page's median figure *after* its declared unit is
# multiplied in. Stricter than the per-value ceiling above, because a statement
# page carries a whole column of figures: if the declared unit pushes the middle
# of the page past this, the unit describes something else in the document (a
# note, or a different statement), not the page being read.
MAX_PLAUSIBLE_SCALED_PAGE_MEDIAN = 1e15

# Fields that are legitimately small, so the monetary floor must not apply.
NON_MONETARY_FIELDS = frozenset({
    "treasury_shares_quantity",
    "treasury_shares_percentage",
    "treasury_shares_nominal_value",
    "treasury_shares_carrying_value",
})

NON_MONETARY_UNITS = frozenset({"percent", "shares"})


def is_monetary(field: str | None, unit: str | None = None) -> bool:
    """Whether this field's value is a currency amount subject to the floors."""
    if field and field in NON_MONETARY_FIELDS:
        return False
    if unit and unit in NON_MONETARY_UNITS:
        return False
    return True


def minimum_plausible_monetary(currency: str | None = None,
                               unit: str | None = None) -> float:
    """Smallest normalized amount that can be a real figure, in reported units.

    - No scale multiplier was recorded (`unit is None`). The filing stated plain
      currency units, so a rupiah threshold has nothing to say about it: this is
      the case for 12,855 of 21,041 extracted rows, and it covered 1,172 of the
      1,309 rows the old rupiah floor flagged -- a non-controlling interest of
      19,757, a -122,921,818 USD loss. The floor drops to a bare
      fragment-detector, which still rejects a page number (37) read as money.
    - A scale was applied (`unit` is 'juta', 'ribuan', ...). The currency's own
      floor applies, so a mis-detected multiplier is still caught.

    The ceiling is unaffected either way, so a unit applied too many times is
    still rejected in every currency.
    """
    if unit is None:
        return _MIN_PLAUSIBLE_PLAIN_UNITS
    return _MIN_PLAUSIBLE_MONETARY_BY_CURRENCY.get(
        currency, _MIN_PLAUSIBLE_MONETARY_DEFAULT)


def is_implausible_amount(normalized: float | None, field: str | None = None,
                          unit: str | None = None,
                          currency: str | None = None) -> bool:
    """True when the amount cannot be a real reported figure."""
    if normalized is None:
        return False
    if not is_monetary(field, unit):
        return False
    magnitude = abs(normalized)
    if magnitude == 0.0:
        return False
    if magnitude > MAX_PLAUSIBLE_MONETARY:
        return True
    return magnitude < minimum_plausible_monetary(currency, unit)


_NUM_RE = re.compile(r"\d[\d.,]*")


def page_magnitudes(text: str) -> list[float]:
    """Numeric magnitudes appearing in a page's text, separator noise removed.

    Used to sanity-check a detected unit: if the page's own numbers are already
    rupiah-scale, the unit word came from incidental prose.
    """
    out: list[float] = []
    for token in _NUM_RE.findall(text or ""):
        cleaned = token.replace(".", "").replace(",", "")
        if not cleaned or not cleaned.isdigit():
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if value >= 100.0:
            out.append(value)
    return out


def correct_unit_multiplier(text: str, multiplier: int) -> tuple[int, str | None]:
    """Reject a unit multiplier the page's own numbers contradict.

    A page stating "ribuan" whose figures are already in the trillions has not
    been stated in thousands; scaling them would inflate the report by 1,000x.
    The page's median magnitude is used rather than its maximum so a single
    large footnote does not mask a correctly scaled statement.

    The second rule matters as much as the first. The threshold above only fires
    when the raw digits are *already* obviously rupiah-scale, so a page of
    mid-sized figures that is merely mis-declared passes it: 17.527.130.084
    scaled by a stray 'juta' gives 1.75e16, which the old ceiling accepted and
    which therefore outranked the correct 1.75e10. Comparing the scaled median
    against a realistic ceiling catches that, because an entire page of figures
    cannot legitimately be that large.
    """
    if multiplier <= 1:
        return multiplier, None

    magnitudes = page_magnitudes(text)
    if not magnitudes:
        return multiplier, None

    magnitudes.sort()
    median = magnitudes[len(magnitudes) // 2]

    # Median already at rupiah scale: the header's unit word is incidental.
    if median >= 10_000_000_000:
        return 1, f"median magnitude {median:,.0f} already rupiah-scale; " \
                  f"ignored x{multiplier} unit"

    # The declared unit would push the whole page past anything reportable.
    scaled = median * multiplier
    if scaled > MAX_PLAUSIBLE_SCALED_PAGE_MEDIAN:
        return 1, f"scaled median {scaled:,.0f} exceeds the " \
                  f"{MAX_PLAUSIBLE_SCALED_PAGE_MEDIAN:,.0f} reporting ceiling; " \
                  f"ignored x{multiplier} unit"

    # Median far too small for the claimed unit to be plausible either.
    if scaled < MIN_PLAUSIBLE_MONETARY and median >= 1000:
        return multiplier, None

    return multiplier, None