"""Directory scanner: discovers PDFs and infers the company from folder names."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import SecurityError
from app.core.logging import get_logger

logger = get_logger(__name__)

_YEAR_RE = re.compile(r"(20\d{2})")


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


def scan_directory(input_root: Path, limit: int | None = None) -> list[DiscoveredFile]:
    """Recursively find all PDFs under input_root."""
    if not input_root.exists():
        raise SecurityError(f"Input directory does not exist: {input_root}")
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
    logger.info("Scanner discovered %d PDFs under %s", len(results), input_root)
    return results
