"""Per-page text extraction for text-based PDFs."""
from __future__ import annotations

import pymupdf

from app.core.logging import get_logger

logger = get_logger(__name__)


def extract_page_text(page: pymupdf.Page) -> str:
    try:
        return page.get_text("text") or ""
    except Exception as exc:  # corrupted page content
        logger.warning("get_text failed on page %s: %s", page.number + 1, exc)
        return ""


def extract_all_pages(path: str, max_pages: int = 0) -> list[tuple[int, str]]:
    """Return [(page_number_1based, text), ...]. Streams page by page."""
    out: list[tuple[int, str]] = []
    with pymupdf.open(path) as doc:
        n = doc.page_count if max_pages <= 0 else min(doc.page_count, max_pages)
        for i in range(n):
            page = doc[i]
            text = extract_page_text(page)
            out.append((i + 1, text))
    return out
