"""PDF type detection: TEXT vs SCANNED vs HYBRID."""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from app.core.logging import get_logger

logger = get_logger(__name__)

# A page with fewer extractable characters than this is considered image-only.
TEXT_CHAR_THRESHOLD = 100


@dataclass
class PdfClassification:
    pdf_type: str            # TEXT / SCANNED / HYBRID
    page_count: int
    text_pages: int
    scanned_pages: int
    page_types: list[tuple[int, str]]  # (page_number_1based, TEXT|SCANNED)


def classify_pdf(path: str | bytes, sample_pages: int = 20) -> PdfClassification:
    """Classify a PDF by sampling up to `sample_pages` evenly distributed pages."""
    doc = pymupdf.open(path)
    try:
        n = doc.page_count
        if n == 0:
            return PdfClassification("TEXT", 0, 0, 0, [])
        if n <= sample_pages:
            indices = list(range(n))
        else:
            step = n / sample_pages
            indices = sorted({int(i * step) for i in range(sample_pages)})

        page_types: list[tuple[int, str]] = []
        text_pages = scanned_pages = 0
        for idx in indices:
            page = doc[idx]
            txt = page.get_text("text").strip()
            ptype = "TEXT" if len(txt) >= TEXT_CHAR_THRESHOLD else "SCANNED"
            page_types.append((idx + 1, ptype))
            if ptype == "TEXT":
                text_pages += 1
            else:
                scanned_pages += 1

        if scanned_pages == 0:
            pdf_type = "TEXT"
        elif text_pages == 0:
            pdf_type = "SCANNED"
        else:
            pdf_type = "HYBRID"
        logger.debug("%s classified as %s (%d pages sampled)", path, pdf_type, len(indices))
        return PdfClassification(pdf_type, n, text_pages, scanned_pages, page_types)
    finally:
        doc.close()
