"""Directory scanner: discovers filings and infers company and year from the tree.

Two corpus layouts are supported, chosen by what is actually present under the
input root.

The XBRL corpus, which is the current one, is organised as::

    XBRL/<company>/<year>/<statement>.html

A filing is a *folder*, not a file: the cover, the five primary statements and
the notes are separate HTML documents that only mean anything together. The
cover (``1000000.html``) anchors the folder because it is the only page that
declares the presentation scale. One folder therefore becomes one
:class:`DiscoveredFile`, and the year comes from the folder name -- statement
filenames are codes like ``1321000.html`` and carry no year at all.

The legacy PDF corpus, one self-contained file per filing, keeps its original
behaviour: every ``*.pdf`` is its own document and the year is read from the
filename.

HTML is preferred when the tree contains any, which is what makes switching
corpora a matter of pointing ``input_directory`` at the new folder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import SecurityError
from app.core.logging import get_logger

logger = get_logger(__name__)

_YEAR_RE = re.compile(r"(20\d{2})")

# Anchor file for an XBRL filing folder; see module docstring.
COVER_FILENAME = "1000000.html"

_PDF_SUFFIXES = frozenset({".pdf"})
_HTML_SUFFIXES = frozenset({".html", ".htm"})


@dataclass
class DiscoveredFile:
    path: Path
    company: str
    filename: str
    filename_year: int | None


def sanitize_component(name: str) -> str:
    """Reject path components that could escape the input root or contain junk."""
    if ".." in name or "/" in name or "\\" in name or "\x00" in name:
        raise SecurityError(f"Unsafe path component: {name!r}")
    return name.strip()


def _company_from_parents(path: Path, input_root: Path) -> str | None:
    """The first-level directory under the input root is the company name."""
    try:
        rel = path.relative_to(input_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 2:
        return parts[0]
    return None


def _year_from_filename(name: str) -> int | None:
    m = _YEAR_RE.search(name)
    return int(m.group(1)) if m else None


def _has_html(root: Path) -> bool:
    """Whether the tree holds any HTML at all.

    Searched recursively on purpose: in an XBRL corpus the HTML lives two levels
    down (``<company>/<year>/*.html``), so probing only the root and its company
    folders finds nothing and misclassifies the corpus as PDF.
    """
    try:
        return next(root.rglob("*.htm*"), None) is not None
    except OSError:
        return False


def _anchor_file(folder: Path, suffixes: frozenset[str]) -> Path | None:
    """The file that represents a filing folder, preferring the cover page."""
    try:
        files = sorted(p for p in folder.iterdir()
                       if p.is_file() and p.suffix.lower() in suffixes)
    except OSError:
        return None
    if not files:
        return None
    cover = folder / COVER_FILENAME
    if cover in files:
        return cover
    return files[0]


def _scan_html(input_root: Path, limit: int | None) -> list[DiscoveredFile]:
    """One document per filing folder, anchored on that folder's cover page."""
    results: list[DiscoveredFile] = []
    for company_dir in sorted(p for p in input_root.iterdir() if p.is_dir()):
        company = company_dir.name
        for year_dir in sorted(p for p in company_dir.iterdir() if p.is_dir()):
            anchor = _anchor_file(year_dir, _HTML_SUFFIXES)
            if anchor is None:
                continue
            year = _year_from_filename(year_dir.name)
            if year is None:
                logger.warning("Skipping %s: folder name states no year", year_dir)
                continue
            results.append(
                DiscoveredFile(
                    path=anchor,
                    company=company,
                    # Carries the year so the processor can read it back from the
                    # filename without a schema change.
                    filename=f"{company} {year}",
                    filename_year=year,
                )
            )
            if limit and len(results) >= limit:
                return results
    return results


def _scan_pdf(input_root: Path, limit: int | None) -> list[DiscoveredFile]:
    """One document per PDF, as before."""
    results: list[DiscoveredFile] = []
    for pdf in sorted(input_root.rglob("*.pdf")):
        if not pdf.is_file():
            continue
        company = _company_from_parents(pdf, input_root) or input_root.name
        results.append(
            DiscoveredFile(
                path=pdf,
                company=company,
                filename=pdf.name,
                filename_year=_year_from_filename(pdf.stem),
            )
        )
        if limit and len(results) >= limit:
            break
    return results


def scan_directory(input_root: Path, limit: int | None = None) -> list[DiscoveredFile]:
    """Recursively find filings under input_root.

    An XBRL tree is recognised by the presence of any HTML file and scanned one
    filing-folder at a time; otherwise the tree is treated as the legacy PDF
    corpus.
    """
    if not input_root.exists():
        raise SecurityError(f"Input directory does not exist: {input_root}")
    if not input_root.is_dir():
        raise SecurityError(f"Input directory is not a directory: {input_root}")

    if _has_html(input_root):
        results = _scan_html(input_root, limit)
        logger.info("Scanner discovered %d XBRL filings under %s", len(results), input_root)
        return results

    results = _scan_pdf(input_root, limit)
    logger.info("Scanner discovered %d PDFs under %s", len(results), input_root)
    return results