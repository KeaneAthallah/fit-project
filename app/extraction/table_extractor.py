"""Table extraction from PDF pages.

Uses pdfplumber for text PDFs. Many Indonesian financial statements have no
ruling lines, so we try the default (lines) strategy first, then fall back to
the text-alignment strategy. Leading non-numeric cells of a row are joined to
form the row label. For scanned pages the OCR text is parsed heuristically.
Also detects multi-year column headers so one row can yield several year
observations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)

_YEAR_HEADER_RE = re.compile(r"\b(20[0-2]\d)\b")

# A cell qualifies as a VALUE cell only when it is number-shaped: optional
# sign/paren/currency, digits with separators, optional %/word-quantifier.
# Prose fragments ('In 2024, the', 'No. C2-10099.HT') must never become values.
_VALUE_CELL_RE = re.compile(
    r"^\s*[\(\-–—]?\s*(?:Rp\.?\s*)?[\d.,]+\s*(?:%|saham|lembar|shares?)?\s*[\)]?\s*$",
    re.I,
)
# Cells that contain digits but are clearly NOT values (reference numbers,
# dates, id codes, ranges, word-embedded numbers). Share-quantity suffixes
# ('saham'/'shares') ARE value-quantifiers, so they don't disqualify.
_NON_VALUE_CELL_RE = re.compile(
    r"(?:No\.?\s*|20[0-2]\d|\d{2,}/\d{2,}|[A-Za-z]{3,}\s*\d|\d\s+(?!saham\b|lembar\b|shares?\b)[A-Za-z]{3,})",
    re.I,
)
# OCR row split: 'label  1.234 567 (890)' -> label + trailing numbers.
# Every quantifier inside the number run is possessive. The previous form,
# `(?:[-–(]?\s*(?:Rp\s*)?[\d.,]+\)?[\s]*)+`, left two overlapping sources of
# ambiguity: the `\s*` at the end of one repetition versus the `\s*` at the
# start of the next, and re-partitioning one digit run across repetitions.
# Either let a single non-matching OCR line take exponential time to reject,
# which is what pinned a worker core for a whole batch. Possessive quantifiers
# make each repetition match exactly one token, so the scan is linear; the set
# of accepted strings is unchanged.
_NUM_RUN = r"(?:[\s]*+[-–(]?[\s]*+(?:Rp[\s]*+)?[\d.,]++[\s]*+[\)]?)+"
_OCR_ROW_RE = re.compile(rf"^(.*?)[\s\.…]+({_NUM_RUN})[\s]*+$")


def _is_value_cell(text: str) -> bool:
    """Discriminate numeric value cells from label/prose cells containing digits."""
    t = text.strip()
    if not t or not re.search(r"\d", t):
        return False
    if _VALUE_CELL_RE.match(t) and not _NON_VALUE_CELL_RE.search(t):
        return True
    # Parenthesized negative like '(520,193)' or '(6'
    if re.fullmatch(r"\(?[\d.,]+\)?", t):
        return True
    return False

_TEXT_STRATEGY_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    # min_words_vertical is deliberately left at pdfplumber's default (1).
    # Requiring 2 words to anchor a column boundary lets a boundary form from an
    # intra-number gap, splitting one wide value into '2' + '1,171,173' and
    # '9' + ',228,733'. Both halves then look like complete numbers, so the
    # total silently reads as 2 and fails the balance-sheet identity check.
    # Default 1 keeps every total intact (verified on AALI 2021 p137/p138).
    "min_words_horizontal": 1,
    "text_x_tolerance": 2,
}


@dataclass
class TableCell:
    row_label: str
    values: list[tuple[int | None, str]]  # (year or None, raw value string)


@dataclass
class PageTable:
    page_number: int
    rows: list[TableCell] = field(default_factory=list)
    header_years: list[int] = field(default_factory=list)


# Per-page stated-unit override: '(Rp miliar)', '(dalam jutaan)', 'in billions'.
# MD&A pages often state their tables in a different unit than the primary
# statements; a single document-level unit then corrupts one of the two.
_PAGE_UNIT_RE = re.compile(
    r"\(\s*(?:Rp\.?\s*)?(ribu|juta|miliar|triliun|thousand|million|billion|trillion)[a-z]*"
    r"(?:\s+(?:rupiah|usd?|dollars?))?\s*\)"
    r"|(?:dalam|in)\s+((?:ribu|juta|miliar|triliun|thousand|million|billion|trillion)[a-z]*)"
    r"(?:\s+(?:rupiah|usd?|dollars?))?",
    re.I,
)

_UNIT_WORD_TO_NAME = {
    "ribu": "ribuan", "ribuan": "ribuan", "thousand": "ribuan", "thousands": "ribuan",
    "juta": "juta", "jutaan": "juta", "million": "juta", "millions": "juta",
    "miliar": "miliar", "miliaran": "miliar", "billion": "miliar", "billions": "miliar",
    "triliun": "triliun", "triliunan": "triliun", "trillion": "triliun", "trillions": "triliun",
}

_UNIT_MULTIPLIERS = {"ribuan": 1_000, "juta": 1_000_000, "miliar": 1_000_000_000,
                     "triliun": 1_000_000_000_000}


def detect_page_unit(text: str) -> tuple[str | None, int]:
    """Detect a parenthesized page-level unit like '(Rp miliar)'.

    Returns (unit_name, multiplier) or (None, 1). Among multiple matches the
    one accompanied by a currency word wins ('dalam miliaran Rupiah' beats
    '(dalam Jutaan)' from an unrelated 'Saham Beredar (dalam Jutaan)' row);
    then the LARGEST multiplier wins (a page's overall scale is its biggest
    stated unit, since smaller units only appear for quantities like shares).
    """
    candidates: list[tuple[int, str]] = []  # (priority, unit_name)
    for m in _PAGE_UNIT_RE.finditer(text[:3000]):
        word = (m.group(1) or m.group(2) or "").lower()
        name = _UNIT_WORD_TO_NAME.get(word)
        if not name:
            continue
        has_currency = bool(re.search(r"rupiah|usd|dollar", m.group(0), re.I))
        candidates.append((2 if has_currency else 1, name))
    if not candidates:
        return None, 1
    candidates.sort(key=lambda c: (-c[0], -_UNIT_MULTIPLIERS[c[1]]))
    name = candidates[0][1]
    return name, _UNIT_MULTIPLIERS[name]


# ---------------------------------------------------------------------------
# Prose guard: a real statement line item is a short noun phrase, never a
# sentence. pdfplumber merges every text cell left of the first number into one
# label string, so an MD&A narrative page produces labels like
#   'triliun pada tahun 2020. Marg in laba bruto jug a mengalami ...'
#   'transaksi kontrak berjangka komo ditas. Pada outstanding forward ...'
# which then match a canonical label via the substring tier and are stored as
# real figures. Worse, the digits harvested from such prose ('2020', '12.3')
# become the value.
#
# Signal is deliberately narrow so genuine split labels ('Total aset tidak
# lan car', which have no verb) still pass.
# ---------------------------------------------------------------------------
_PROSE_MAX_WORDS = 14          # real line items are well under this
_PROSE_SENTENCE_END_RE = re.compile(r"[.!?]\s+\S")   # internal sentence break
_PROSE_VERB_RE = re.compile(
    r"\b(penurunan|kenaikan|peningkatan|meningkat|menurun|sebesar|terjadi|"
    r"disebabkan|berasal|merupakan|menjadi|adalah|terdiri|dicatat|mencatat|"
    r"menyalami|pernah|diperkirakan|hingga|sekitar)\b",
    re.I,
)
_PROSE_CONNECTIVE_RE = re.compile(
    r"\b(terhadap|menjadi|karena|sehingga|however|although|whereas|"
    r"dibanding|dibandingkan|compared|than|due|because|including)\b",
    re.I,
)
# Verb-initial clauses typical of merged narrative columns: 'laba ditahan serta
# menyetujui keputusan...'. Kept separate from _PROSE_VERB_RE because these
# read as word-initial only, and matching them anywhere would reject legitimate
# labels like 'Penyimpanan barang dan bahan baku'.
_PROSE_CLAUSE_RE = re.compile(
    r"^(laba ditahan|adalah|merupakan|dapat|telah|sudah|akan|"
    r"kami|perseroan|perusahaan|selama|untuk tahun|during|there|these|"
    r"the company|amounting|berjumlah|sebesar|dengan|ketika|when)\b",
    re.I,
)
# Leading/trailing filler typical of merged prose columns.
_PROSE_TAIL_RE = re.compile(
    r"(d an|an|s wa|wa n|ung|nya|lah|kah)\s*$", re.I)


def is_prose_label(label: str) -> bool:
    """True when a row label is narrative prose rather than a statement line.

    Real financial line items are short, verb-free noun phrases
    ('Total aset tidak lancar', 'Beban pokok penjualan', 'Laba bruto'). Table
    extraction concatenates all text left of the first number, so an MD&A page
    yields sentence fragments that would otherwise be mapped by the substring
    tier and stored as figures. Requiring a currency header is not sufficient
    on its own: these pages often also carry a unit line.
    """
    s = " ".join((label or "").split())
    if not s:
        return True
    words = s.split()
    if len(words) > _PROSE_MAX_WORDS:
        return True
    if _PROSE_SENTENCE_END_RE.search(s):
        return True
    if _PROSE_VERB_RE.search(s):
        return True
    if _PROSE_CONNECTIVE_RE.search(s):
        return True
    if _PROSE_CLAUSE_RE.match(s):
        return True
    return False


def _split_row(cells: list[str]) -> tuple[str, list[str]] | None:
    """Split a raw row into (label, numeric value strings). None if not a data row."""
    if not cells:
        return None
    cleaned = ["" if c is None else str(c).replace("\n", " ").strip() for c in cells]
    numeric: list[str] = []
    label_parts: list[str] = []
    # cells before the first numeric cell form the label; after are values
    seen_number = False
    for c in cleaned:
        if not c:
            if seen_number:
                numeric.append("")
            continue
        if not seen_number and re.search(r"\d", c) and not _YEAR_HEADER_RE.fullmatch(c):
            if _is_value_cell(c):
                seen_number = True
                numeric.append(c)
            else:
                # Digits but not value-shaped (reference no., date, prose):
                # keep it in the label so it never reaches the number parser.
                label_parts.append(c)
        elif not seen_number:
            label_parts.append(c)
        else:
            numeric.append(c)
    label = " ".join(p for p in label_parts if p).strip()
    nums = [n for n in numeric if re.search(r"\d", n)]
    if not label or not nums:
        return None
    if is_prose_label(label):
        return None
    return label, nums


def _detect_header_years(rows: list[list[str | None]]) -> list[int]:
    """Find standalone year headers in the top rows of a table.

    Only rows[:4] are scanned: a statement's period header sits at the top,
    while years buried deep in the body are usually comparatives, footnotes or
    reference numbers rather than column headers.
    """
    years: list[int] = []
    for row in rows[:4]:
        for cell in row or []:
            if cell is None:
                continue
            for m in _YEAR_HEADER_RE.finditer(str(cell)):
                y = int(m.group(1))
                if y not in years:
                    years.append(y)
    return years


def _find_year_header_depth(rows: list[list[str | None]], limit: int = 12) -> list[int]:
    """Same as _detect_header_years but searches deeper.

    Some statements put the year header lower down the page: AALI's Indonesian
    and English cash-flow columns sit side by side, and the English block's
    header lands around row 8 rather than row 2. Scanning only rows[:4] missed
    it, so every value on that page fell back to the filename year and the same
    statement was stored twice under two different years.

    Only used as a FALLBACK when the shallow scan finds nothing. Scanning the
    body of a table that already has a header picks up unrelated years from
    footnote prose (AALI p167 yielded 2016 alongside its real 2022/2021), which
    would then mis-zip every column.
    """
    years: list[int] = []
    for row in rows[:limit]:
        for cell in row or []:
            if cell is None:
                continue
            text = str(cell)
            if not _YEAR_HEADER_RE.search(text):
                continue
            for m in _YEAR_HEADER_RE.finditer(text):
                y = int(m.group(1))
                if y not in years:
                    years.append(y)
    return years


def _header_years(rows: list[list[str | None]]) -> list[int]:
    """Header years for a table: shallow scan first, deeper scan as fallback."""
    years = _detect_header_years(rows)
    if years:
        return years
    return _find_year_header_depth(rows)


# A standalone number token: '(18,474.41)', '-1.234,56', '520', '18,47', '(', '4.41)'
_NUMBER_TOKEN_RE = re.compile(r"^[\(\-–—]?[\d.,]+[\)]?$|^\($|^[\d.,]+\)$")


def _number_score(s: str) -> int:
    """0 = not numeric / lone paren, 1 = fragment, 2 = complete number."""
    t = s.strip()
    if t == "(":
        return 1  # lone open paren: start of a parenthesized negative
    if not t or not _numberish(t):
        return 0
    if t.count("(") == t.count(")") and not t.endswith((".", ",")) and not t.startswith("("):
        return 2
    if t.startswith("(") and t.endswith(")") and not t.endswith((".", ",")):
        return 2
    # '(18,474.41)' form
    if re.fullmatch(r"\([\d.,]+\)", t):
        return 2
    # A bare digits group with no dangling separator and no paren: complete
    if re.fullmatch(r"[\d.,]+", t) and not t.endswith((".", ",")):
        return 2
    return 1


def _numberish(fragment: str) -> bool:
    """True when the fragment is purely numeric-shaped (digits+separators+parens)."""
    f = fragment.strip()
    return bool(f) and bool(_NUMBER_TOKEN_RE.match(f)) and bool(re.search(r"\d", f))


_LEADING_DIGIT_RUN_RE = re.compile(r"^\d{1,3}$")
_TRAILING_GROUP_RE = re.compile(r"^[.,]\d[\d.,]*$")


def _is_leading_digit_run(cells: list[str | None], i: int) -> bool:
    """True when cells[i] is the head of a number split across a cell boundary.

    pdfplumber's text strategy cuts a wide number column at a fixed width, so
    5,960,396 arrives as '5' + ',960,396' and 9,228,733 as '9' + ',228,733'.
    Both halves look like well-formed standalone numbers, so _number_score rates
    them complete and no merge happens — the row then reports 5 instead of
    5,960,396 (a factor of ~1.2M, which is what produced the liabilities_split
    failures).

    The test is deliberately narrow: the head must be bare digits with no
    separators or parens, and the tail must start with a separator. A standalone
    number never begins with ',' or '.', so this cannot fuse two real numbers
    ('12' next to '34' stays untouched).
    """
    head = (cells[i] or "").strip()
    if not _LEADING_DIGIT_RUN_RE.match(head):
        return False
    j = i + 1
    while j < len(cells) and cells[j] is not None and not str(cells[j]).strip():
        j += 1
    if j >= len(cells) or cells[j] is None:
        return False
    return bool(_TRAILING_GROUP_RE.match(str(cells[j]).strip()))


def _merge_number_fragments(cells: list[str | None]) -> list[str | None]:
    """Reassemble numeric tokens that the text strategy split across cells.

    pdfplumber's vertical 'text' strategy can place an open-paren, the number
    body and the close-paren in separate cells — '(18,474.41)' arrives as
    '(' + '18,47' + '4.41)'. Joins adjacent cells ONLY when a cell is an
    unbalanced fragment (lone '(' or trailing '4.41)' with open paren pending,
    or '17,974.' with a dangling separator). Well-formed standalone numbers
    ('28,793,225', '(520,193)') are NEVER touched, and two complete numbers in
    adjacent cells are never concatenated.
    """
    out: list[str | None] = []
    i = 0
    n = len(cells)
    while i < n:
        cur = cells[i]
        if cur is None:
            out.append(cur)
            i += 1
            continue
        if _is_leading_digit_run(cells, i):
            head = cur.strip()
            j = i + 1
            while j < n and cells[j] is not None and not str(cells[j]).strip():
                j += 1
            tail = (cells[j] or "").strip()
            out.append(head + tail)
            i = j + 1
            continue
        score = _number_score(cur)
        if score != 1:
            # Not numeric, or already a complete number: leave as-is.
            out.append(cur)
            i += 1
            continue
        # Fragment: merge forward while the candidate stays number-shaped and
        # we reach a complete number.
        merged = cur.strip()
        j = i + 1
        while j < n and cells[j] is not None and _number_score(cells[j]) >= 1:
            candidate = merged + cells[j].strip()
            if _number_score(candidate) == 2:
                merged = candidate
                j += 1
                break
            # Partial progress only if the run is still plausibly one token
            # (e.g. '(' + '18,47' with more to come).
            if re.match(r"^[\(\-–—]?[\d.,]+$", merged) or merged == "(":
                merged = candidate
                j += 1
                continue
            break
        out.append(merged)
        i = j
    return out


def _process_table(tbl: list[list[str | None]], pt: PageTable,
                   preferred_year: int | None = None) -> None:
    years = order_header_years(_header_years(tbl), preferred_year)
    if years and not pt.header_years:
        pt.header_years = years
    for row in tbl or []:
        row = _merge_number_fragments(list(row or []))
        split = _split_row(row)
        if split is None:
            continue
        label, nums = split
        # Only zip to a year when the value count actually matches the header
        # count. A mismatch means the columns are not the header's columns, so
        # leaving the year unset lets the caller fall back to the document year
        # instead of silently mislabelling values.
        if years and len(nums) == len(years):
            pt.rows.append(TableCell(label, list(zip(years, nums))))
        else:
            pt.rows.append(TableCell(label, [(None, n) for n in nums]))


def order_header_years(years: list[int], preferred: int | None) -> list[int]:
    """Reorder detected header years so the document's own period comes first.

    Header years are read in the order they appear in the text stream, which is
    not the order of the value columns. AALI's 2021 equity statement prints
    21,171,173 then 19,247,794 under a header read as [2020, 2021], so the zip
    assigned the current year to the prior year's figure and shifted equity
    between years.

    Statements put the current reporting period in the first value column, so
    anchoring the detected list on the reporting year repairs the pairing
    without guessing. A year not present in the header is never invented here.
    """
    if not preferred or preferred not in years or len(years) < 2:
        return years
    return [preferred] + [y for y in years if y != preferred]


def extract_tables_from_file(
    path: str,
    page_numbers: list[int],
    max_pages: int = 0,
    preferred_year: int | None = None,
) -> dict[int, PageTable]:
    """Extract tables for the given 1-based page numbers using pdfplumber."""
    import pdfplumber

    out: dict[int, PageTable] = {}
    if not page_numbers:
        return out
    targets = set(page_numbers)
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            if i not in targets:
                continue
            if max_pages and len(out) >= max_pages:
                break
            pt = PageTable(page_number=i)
            # Strategy 1: default (lines/rects) — best for ruled tables.
            try:
                tables = page.extract_tables()
            except Exception as exc:
                logger.warning("pdfplumber lines-strategy failed on page %d: %s", i, exc)
                tables = []
            for tbl in tables or []:
                _process_table(tbl, pt, preferred_year)

            # Strategy 2: text alignment — for unruled financial statements.
            if not pt.rows:
                try:
                    tables = page.extract_tables(_TEXT_STRATEGY_SETTINGS)
                except Exception as exc:
                    logger.warning("pdfplumber text-strategy failed on page %d: %s", i, exc)
                    tables = []
                for tbl in tables or []:
                    _process_table(tbl, pt, preferred_year)
            out[i] = pt
    return out


def parse_ocr_table_text(text: str, preferred_year: int | None = None) -> PageTable:
    """Heuristic parse of OCR text into table rows: 'label .... 123 456'."""
    pt = PageTable(page_number=0)
    header_years: list[int] = []
    for m in _YEAR_HEADER_RE.finditer(text[:800]):
        y = int(m.group(1))
        if y not in header_years:
            header_years.append(y)
    header_years = order_header_years(header_years, preferred_year)

    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 4:
            continue
        # Split label from trailing numeric tokens. The trailing run is matched
        # as a single possessive class so there is no nested quantifier to
        # backtrack over — the previous `(?:...[\s]*)+` form was ambiguous and
        # spent minutes of CPU on long OCR lines that never matched.
        m = _OCR_ROW_RE.match(line)
        if not m:
            continue
        label = m.group(1).strip(" .:|-")
        # Labels ending in words ('sebesar', '2024, the') mean the trailing
        # digits are prose fragments, not table values.
        if re.search(r"[A-Za-z]{3,}", label.split()[-1] if label.split() else ""):
            continue
        value_part = m.group(2).strip()
        tokens = re.findall(r"[-–(]?\s*(?:Rp\s*)?[\d][\d.,]*\)?", value_part)
        tokens = [t.strip() for t in tokens if re.search(r"\d", t)]
        if not label or not tokens:
            continue
        if header_years and len(tokens) == len(header_years):
            pt.rows.append(TableCell(label, list(zip(header_years, tokens))))
        else:
            pt.rows.append(TableCell(label, [(None, t) for t in tokens]))
    return pt
