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

# One miliar rupiah. Indonesian listed companies report in the billions, so a
# monetary statement line item below this is a misparse rather than a figure.
MIN_PLAUSIBLE_MONETARY = 1_000_000_000.0

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


def is_implausible_amount(normalized: float | None, field: str | None = None,
                          unit: str | None = None) -> bool:
    """True when the amount cannot be a real reported figure."""
    if normalized is None:
        return False
    if not is_monetary(field, unit):
        return False
    magnitude = abs(normalized)
    if magnitude == 0.0:
        return False
    return magnitude < MIN_PLAUSIBLE_MONETARY or magnitude > MAX_PLAUSIBLE_MONETARY


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