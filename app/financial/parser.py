"""Financial number parsing for Indonesian and English formats.

Handles:
    1.234.567        -> 1234567      (Indonesian thousands separator)
    1.234.567,89     -> 1234567.89
    Rp 1.234.567.890 -> 1234567890
    (1.234.567)      -> -1234567     (parentheses = negative)
    -1.234.567       -> -1234567
    1,234,567        -> 1234567      (English thousands separator)
    1,234,567.89     -> 1234567.89
    -                -> None         (a dash means no value)
    1.234.567,00     -> 1234567.0

OCR-corruption handling (``correct_ocr_number``):  O->0, l/I->1, S->5, B->8
are only substituted when the token is *already number-shaped* (digits mixed
with separators plus a few confusable letters) — never applied to arbitrary
text, so words like "laba" or "Otoritas" are untouched.
"""
from __future__ import annotations

import re

_NUMBER_BODY = r"[0-9][0-9.,\s]*"
_CURRENCY_PREFIX = r"(?:(?:Rp|IDR|USD|EUR|US\$|\$)\s*)"

_FULL_NUMBER_RE = re.compile(
    rf"(?P<neg>[-–—(]?\s*)(?P<cur>{_CURRENCY_PREFIX}?)(?P<num>{_NUMBER_BODY}?)(?P<close>\s*\))?"
)

_DASH_ONLY_RE = re.compile(r"^[-–—]+$")


class NumberParseError(ValueError):
    pass

# ---------------------------------------------------------------------------
# OCR correction
# ---------------------------------------------------------------------------

# Characters OCR commonly confuses inside number tokens.
_OCR_CHAR_MAP = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8"})

# A token is number-shaped if, after normalizing separators, it is basically
# digits with grouping separators and at most a handful of confusables.
_NUMBER_SHAPED_RE = re.compile(r"^\s*[\(\-–—]?\s*(?:Rp\s*)?[0-9OolISB][0-9OolISB.,\s]*(?:\s*\))?\s*$")


def correct_ocr_number(raw: str) -> str:
    """Repair OCR-confused characters in a token that looks like a number.

    Only applies when the token is number-shaped: contains digits/separators
    and no words. '1.234.OOO' -> '1.234.000'; 'Rp l.234.567' -> 'Rp 1.234.567'.
    Words like 'Modal' or 'Tahun' are returned unchanged.
    """
    if not raw or not _NUMBER_SHAPED_RE.match(raw):
        return raw
    # Preserve surrounding whitespace/parens; translate only the body.
    return raw.translate(_OCR_CHAR_MAP)


def _is_truncated_tail(s: str) -> bool:
    """True for a token whose trailing digits were lost at a cell boundary.

    '1.', '30.', '(14,' and '021,' are single digit groups followed by a
    separator: the separator had more digits after it that never arrived.
    Parsing the surviving prefix invents a real-looking but fabricated figure —
    '1.' became 1,000,000 and '30.' became 30,000,000 — which then failed
    identity checks or silently understated a line item.

    A *multi-group* number followed by a separator ('1.234.567.') is different:
    its digits are all present and the trailing mark is stray punctuation, so
    it keeps parsing.
    """
    if not re.search(r"\d", s):
        return False
    body = s.strip().strip("()").strip()
    if not body or not body[-1] in ".,":
        return False
    body = body[:-1]
    # More than one group means the number itself is complete.
    return not re.search(r"[.,]", body)


def _to_number(digits: str) -> int | float:
    """Turn a plain decimal string into a number without losing any of it.

    `float` holds every integer exactly only up to 2**53 (9,007,199,254,740,992).
    Figures in this dataset already reach 2.36e15 and a currency amount is whole
    in practice, so an integral value is returned as `int` and stays exact at any
    magnitude the database can hold -- no rounding happens because no binary
    float is ever constructed for it. `int` is a valid stand-in for `float`
    wherever one is expected and keeps mixed arithmetic exact.

    Only genuinely fractional input (a stray cents figure on a statement that
    reports in rupiah) goes through `float`, which is the only precision the
    format itself can represent.
    """
    if "." not in digits:
        return int(digits)
    return float(digits)


def parse_financial_number(raw: str | None, apply_ocr_fix: bool = True) -> float | None:
    """Parse a financial number string into a number.

    Whole figures are returned as `int` and are therefore exact; see
    `_to_number`. Returns None when the input represents "no value" (dash,
    empty, '-', 'n/a') or a truncated fragment whose trailing digits were lost.
    Raises NumberParseError when the string contains a number-like token that
    cannot be parsed (so callers can flag it rather than silently drop it).
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s or _DASH_ONLY_RE.match(s) or s.lower() in {"n/a", "na", "nil", "-,-"}:
        return None
    if _is_truncated_tail(s):
        return None

    if apply_ocr_fix:
        s = correct_ocr_number(s)

    s = _strip_spaces(s)

    # Detect explicit negative markers
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    elif s.startswith("(") and s.count("(") == 1:
        # Unclosed paren — common OCR crop, e.g. '(520,193'
        negative = True
        s = s[1:].strip()
    if s.startswith("-"):
        negative = True
        s = s[1:].strip()
    elif s.startswith("–") or s.startswith("—"):
        negative = True
        s = s[1:].strip()

    # Remove currency symbols/prefixes
    s = re.sub(rf"^{_CURRENCY_PREFIX}", "", s, flags=re.I)
    s = s.strip()

    # If what remains is only separators -> no value
    if not re.search(r"\d", s):
        if _DASH_ONLY_RE.match(raw.strip()):
            return None
        raise NumberParseError(f"Cannot parse number from {raw!r}")

    # Suffix like 'jt', 'rb' handled by unit layer, not here.
    s = s.rstrip(".,;:")

    # Decide decimal vs thousands separators.
    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Whichever comes last is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            # Indonesian: 1.234.567,89
            integer_part, frac_part = s.rsplit(",", 1)
            integer_clean = integer_part.replace(".", "")
            if not re.fullmatch(r"\d*", integer_clean) or not re.fullmatch(r"\d*", frac_part):
                raise NumberParseError(f"Cannot parse number from {raw!r}")
            value = _to_number(f"{integer_clean}.{frac_part}" if frac_part else integer_clean)
        else:
            # English: 1,234,567.89
            integer_part, frac_part = s.rsplit(".", 1)
            integer_clean = integer_part.replace(",", "")
            if not re.fullmatch(r"\d*", integer_clean) or not re.fullmatch(r"\d*", frac_part):
                raise NumberParseError(f"Cannot parse number from {raw!r}")
            value = _to_number(f"{integer_clean}.{frac_part}" if frac_part else integer_clean)
    elif has_comma:
        # Only commas: 1,234,567 (English thousands) OR 1234,56 (Indonesian decimal)
        grouped = _apply_thousands_groups(s, ",")
        if grouped is not None:
            value = _to_number(grouped)
        else:
            parts = s.split(",")
            if len(parts) == 2 and re.fullmatch(r"\d+", parts[0]) and re.fullmatch(r"\d+", parts[1]):
                value = _to_number(f"{parts[0]}.{parts[1]}")
            else:
                raise NumberParseError(f"Cannot parse number from {raw!r}")
    elif has_dot:
        # Only dots: 1.234.567 (Indonesian thousands) OR 1234.56 (English decimal)
        grouped = _apply_thousands_groups(s, ".")
        if grouped is not None:
            value = _to_number(grouped)
        else:
            parts = s.split(".")
            if len(parts) == 2 and re.fullmatch(r"\d+", parts[0]) and re.fullmatch(r"\d+", parts[1]):
                value = _to_number(s)
            else:
                raise NumberParseError(f"Cannot parse number from {raw!r}")
    else:
        if not re.fullmatch(r"\d+(?:\.\d+)?", s):
            raise NumberParseError(f"Cannot parse number from {raw!r}")
        value = _to_number(s)

    return -value if negative else value


def looks_like_number(raw: str) -> bool:
    """Quick heuristic: does this token contain a parseable number?"""
    if not raw or _DASH_ONLY_RE.match(raw.strip()):
        return False
    return bool(re.search(r"\d", raw))


# ---------------------------------------------------------------------------
# Share quantities: "1.000.000 saham", "6,000,000 shares", "125.000 lembar"
# ---------------------------------------------------------------------------

_SHARE_UNIT_RE = re.compile(
    r"\b(saham|lembar|shares?|stocks?)\b", re.I
)


def parse_share_quantity(raw: str | None) -> float | None:
    """Parse a share-count token like '1.000.000 saham' -> 1000000.

    Returns None when the token is not a share quantity (no unit word, or it
    is a dash/no-value marker). This is deliberately separate from monetary
    parsing so a quantity is never mistaken for a currency amount.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s or _DASH_ONLY_RE.match(s):
        return None
    if not _SHARE_UNIT_RE.search(s):
        return None
    num_part = _SHARE_UNIT_RE.sub(" ", s)
    try:
        value = parse_financial_number(num_part.strip())
    except NumberParseError:
        return None
    return value


def is_share_quantity(raw: str | None) -> bool:
    """True when the token explicitly denotes a number of shares."""
    if not raw:
        return False
    return bool(_SHARE_UNIT_RE.search(raw)) and bool(re.search(r"\d", raw))


def _strip_spaces(s: str) -> str:
    return re.sub(r"[\s\u00a0\u202f]", "", s)


def _apply_thousands_groups(s: str, sep: str) -> str | None:
    """Validate grouping like 1.234.567 for sep='.'; returns cleaned digits or None."""
    parts = s.split(sep)
    if len(parts) < 2:
        return None
    head, *groups = parts
    if not re.fullmatch(r"\d{1,3}", head):
        return None
    if not all(re.fullmatch(r"\d{3}", g) for g in groups):
        return None
    return head + "".join(groups)
