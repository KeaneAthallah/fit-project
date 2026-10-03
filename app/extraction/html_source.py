"""Read IDX inline-XBRL HTML filings as financial-statement sources.

The XBRL corpus is not a document format the PDF pipeline can be pointed at.
Each ``XBRL/<company>/<year>/`` folder is one filing made of many small HTML
files, one per statement or note, rendered by IDX's XWand viewer::

    1000000.html   cover page, general information
    1210000.html   statement of financial position
    1321000.html   statement of profit or loss and OCI
    1410000.html   statement of changes in equity
    1510000.html   statement of cash flows
    16xxxx.html .. notes to the financial statements

Two properties of that corpus drive the design here.

First, the scale of the figures is declared only on the cover page, under
"Level of rounding used in financial statements", and never repeated on the
statement pages. Reading ``1321000.html`` on its own gives revenue as
``21,815,035`` with no indication that the real figure is Rp 21.8 trillion, so
a reader that never opens the cover is wrong by six orders of magnitude. Every
cover in the corpus declares one of the three scales in ``_ROUNDING_SCALES``,
so the value is read from there and carried across the filing.

Second, the tables are regular: a row is ``label | value | prior value |
English label``, with the period dates in a header row above. That is close
enough to the PDF layout that the existing row/label/year logic in
``table_extractor`` applies unchanged, so this module converts HTML into the
same ``list[list[str]]`` cell grid that ``_process_table`` already consumes
rather than reimplementing label splitting and year alignment.

Statement identity is likewise taken from each page's own title rather than
from its filename. Statement codes are not stable across issuers -- the same
income statement arrives as ``1321000.html`` under the by-function taxonomy and
``1311000.html`` under the by-nature one -- whereas the title text inside the
file always names the statement unambiguously.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path

from app.core.logging import get_logger
from app.extraction.table_extractor import PageTable, _process_table

logger = get_logger(__name__)

HTML_SUFFIXES = frozenset({".html", ".htm"})

# Cover page ("1000000.html") is present in every filing and is the only page
# that states the reporting scale, so it anchors the document.
COVER_FILENAME = "1000000.html"

# The value of "Level of rounding used in financial statements", mapped to the
# unit name and multiplier the rest of the pipeline uses. IDX filings use
# Indonesian and English on the same line, e.g. "Jutaan / In Million", so both
# halves are matched.
_ROUNDING_SCALES: tuple[tuple[re.Pattern[str], str | None, int], ...] = (
    (re.compile(r"jutaan|in\s+million", re.I), "juta", 1_000_000),
    (re.compile(r"ribuan|in\s+thousand", re.I), "ribuan", 1_000),
    (re.compile(r"miliaran|in\s+billion", re.I), "miliar", 1_000_000_000),
    (re.compile(r"triliun|triliunan|in\s+trillion", re.I), "triliun", 1_000_000_000_000),
    # Full rupiah: an explicit statement that no scaling was applied.
    (re.compile(r"satuan\s+penuh|full\s+amount", re.I), None, 1),
)

_ROUNDING_LABEL_RE = re.compile(
    r"^(?:level of rounding used in financial statements"
    r"|pembulatan yang digunakan dalam penyajian jumlah dalam laporan keuangan)$",
    re.I,
)

# The cover states the presentation currency in the same three-line shape as the
# rounding scale: "Mata uang pelaporan" / "Rupiah / IDR" /
# "Description of presentation currency". Reading it beats assuming IDR, because
# a handful of Indonesian groups file in USD or SGD.
_CURRENCY_LABEL_RE = re.compile(
    r"^(?:description of presentation currency|mata uang pelaporan)$", re.I)

_ISO_CODE_RE = re.compile(r"\b([A-Z]{3})\b")

_CURRENCY_KEYWORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"rupiah", re.I), "IDR"),
    (re.compile(r"us\s*dollar|usd|amerika\s+serat", re.I), "USD"),
    (re.compile(r"singapore", re.I), "SGD"),
    (re.compile(r"euro", re.I), "EUR"),
    (re.compile(r"yuan|renminbi|china", re.I), "CNY"),
    (re.compile(r"yen|jepang", re.I), "JPY"),
    (re.compile(r"pound|sterling|inggris", re.I), "GBP"),
    (re.compile(r"won|korea", re.I), "KRW"),
    (re.compile(r"ringgit|malaysia", re.I), "MYR"),
    (re.compile(r"baht|thailand", re.I), "THB"),
    (re.compile(r"hong\s*kong", re.I), "HKD"),
    (re.compile(r"taiwan", re.I), "TWD"),
    (re.compile(r"australia|aussie", re.I), "AUD"),
    (re.compile(r"swiss|franc", re.I), "CHF"),
)

_TABLE_RE = re.compile(r"(?is)<table\b.*?</table>")
_ROW_RE = re.compile(r"(?is)<tr\b[^>]*>.*?</tr>")
_CELL_RE = re.compile(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>")
_DROP_RE = re.compile(r"(?is)<(script|style|head)\b.*?</\1>")
_BR_RE = re.compile(r"(?i)<br\s*/?>|</p>|</div>|</tr>")
_CELL_END_RE = re.compile(r"(?i)</t[dh]>")


@dataclass
class HtmlFiling:
    """One XBRL filing: the cover page plus one page per statement or note."""

    text: str
    table: PageTable
    # Which file this page came from. Statement filenames are taxonomy codes, so
    # this is the only way to trace a value back to a specific XBRL concept.
    path: Path | None = None
    # (unit_name, multiplier) as declared on the cover, or None when this page
    # is not a cover or states no scale.
    declared_unit: tuple[str | None, int] | None = None
    # ISO code of the presentation currency, when the cover states one.
    declared_currency: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class HtmlDocument:
    """Every page of one company-year filing, cover first."""

    pages: list[HtmlFiling]
    warnings: list[str] = field(default_factory=list)

    @property
    def declared_unit(self) -> tuple[str | None, int] | None:
        """The scale the cover declares, or None if it declares none.

        Pages are ordered cover-first, so the first page that states a scale is
        the cover's. Nothing else in the filing repeats it, so this is the only
        place the answer can come from.
        """
        for page in self.pages:
            if page.declared_unit is not None:
                return page.declared_unit
        return None

    @property
    def declared_currency(self) -> str | None:
        """The currency the cover declares, or None if it declares none."""
        for page in self.pages:
            if page.declared_currency is not None:
                return page.declared_currency
        return None


def is_html_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in HTML_SUFFIXES


def _cell_text(fragment: str) -> str:
    """Flatten one cell to plain text."""
    text = _BR_RE.sub("\n", fragment)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", unescape(text)).strip()


def _plain_lines(html: str) -> list[str]:
    """Visible text as one string per line, with markup and CSS discarded."""
    text = _DROP_RE.sub(" ", html)
    text = _CELL_END_RE.sub("\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return [line.strip() for line in text.split("\n") if line.strip()]


def _candidate_values_near_label(lines: list[str],
                                 label_re: re.Pattern[str]) -> list[str]:
    """Lines sitting just above every occurrence of a cover label.

    Covers render as ``Indonesian label / value / English label``, so the value
    is the line above whichever label matched. Both labels are tried because the
    Indonesian one can sit *above* its own value while the English one sits
    below it, and only one of the two lookups lands on the value. Scanning every
    occurrence matters: returning on the first label match would read the line
    above the Indonesian label, which belongs to the previous field.
    """
    candidates: list[str] = []
    for index, line in enumerate(lines):
        if not label_re.match(line):
            continue
        for back in (1, 2):
            pos = index - back
            if pos >= 0:
                candidates.append(lines[pos])
    return candidates


def read_declared_scale(html: str) -> tuple[str | None, int] | None:
    """Read the cover page's declared presentation scale.

    Returns ``(unit_name, multiplier)``, where a unit name of None means full
    rupiah, or None when the page states no scale at all.

    The cover renders as ``label | value | English label`` on consecutive lines,
    so the value is the line immediately before the English label. Scanning for
    the English label and stepping back is used in preference to indexing cells,
    because the cover's three columns occupy one cell per row while a statement
    page packs them into a single row.
    """
    lines = _plain_lines(html)
    for index, line in enumerate(lines):
        if not _ROUNDING_LABEL_RE.match(line):
            continue
        # The declared value sits directly above the label. Guard the index so a
        # label at the very top of a truncated file cannot walk off the front.
        for back in (1, 2):
            pos = index - back
            if pos < 0:
                continue
            candidate = lines[pos]
            for pattern, unit, multiplier in _ROUNDING_SCALES:
                if pattern.search(candidate):
                    return unit, multiplier
    return None


def read_declared_currency(html: str) -> str | None:
    """Read the cover's declared presentation currency as an ISO code.

    Prefers the ISO code the cover prints ("Rupiah / IDR" -> ``IDR``), falling
    back to matching the Indonesian or English currency name for covers that
    spell it out without a code.
    """
    candidates = _candidate_values_near_label(_plain_lines(html), _CURRENCY_LABEL_RE)
    for value in candidates:
        iso = _ISO_CODE_RE.search(value)
        if iso:
            return iso.group(1)
        for pattern, code in _CURRENCY_KEYWORDS:
            if pattern.search(value):
                return code
    return None


def _cell_grid(html: str) -> list[list[list[str]]]:
    """Every table in the document as a list of rows of cell text."""
    tables: list[list[list[str]]] = []
    for table in _TABLE_RE.finditer(html):
        rows: list[list[str]] = []
        for row in _ROW_RE.finditer(table.group(0)):
            cells = [_cell_text(m.group(1)) for m in _CELL_RE.finditer(row.group(0))]
            # A row of empty cells carries no label and no figure; dropping it
            # keeps the row numbering aligned with what the reader sees.
            if any(cell for cell in cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def read_html_file(path: Path, page_number: int = 1,
                   preferred_year: int | None = None) -> HtmlFiling:
    """Parse one XBRL HTML file into text plus a statement table.

    Never raises: a file that cannot be read is reported as an empty filing so
    that one bad document cannot end a batch of thousands.
    """
    try:
        html = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return HtmlFiling(text="", table=PageTable(page_number=page_number),
                          warnings=[f"unreadable: {exc}"])

    table = PageTable(page_number=page_number)
    warnings: list[str] = []
    try:
        for grid in _cell_grid(html):
            # _process_table owns label splitting, fragment merging and
            # year/column alignment, all of which the PDF path already relies on.
            _process_table(grid, table, preferred_year)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Table extraction failed for %s: %s", path, exc)
        warnings.append(f"table extraction failed: {exc}")

    return HtmlFiling(
        text="\n".join(_plain_lines(html)),
        table=table,
        path=Path(path),
        declared_unit=read_declared_scale(html),
        declared_currency=read_declared_currency(html),
        warnings=warnings,
    )


def read_document(cover_or_file: Path, preferred_year: int | None = None,
                  max_pages: int = 0) -> HtmlDocument:
    """Read a whole filing: the page given plus its sibling HTML files.

    ``cover_or_file`` only has to name one file in the filing; its directory is
    what identifies the filing. Pages are ordered with the cover first so that
    :attr:`HtmlDocument.declared_unit` finds the scale before any statement
    page, and so that unit detection sees the cover text early.
    """
    anchor = Path(cover_or_file)
    directory = anchor.parent
    if not directory.is_dir():
        return HtmlDocument(
            pages=[read_html_file(anchor, 1, preferred_year)],
            warnings=[f"not a filing directory: {directory}"],
        )

    files = sorted(p for p in directory.iterdir() if p.is_file() and is_html_path(p))
    # The cover leads; everything else follows in numeric order so that the five
    # primary statements come before the notes.
    files.sort(key=lambda p: (p.name != COVER_FILENAME, p.name))

    warnings: list[str] = []
    pages: list[HtmlFiling] = []
    for path in files:
        if max_pages > 0 and len(pages) >= max_pages:
            warnings.append(f"stopped at max_pages={max_pages}")
            break
        page = read_html_file(path, len(pages) + 1, preferred_year)
        warnings.extend(f"{path.name}: {w}" for w in page.warnings)
        pages.append(page)

    return HtmlDocument(pages=pages, warnings=warnings)


def page_texts(document: HtmlDocument) -> list[tuple[int, str]]:
    """(page_number, text) for every page, in filing order."""
    return [(i + 1, p.text) for i, p in enumerate(document.pages)]