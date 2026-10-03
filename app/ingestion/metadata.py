"""Document metadata helpers (filename year detection, report titles)."""
from __future__ import annotations

import re

_YEAR_RE = re.compile(r"(20[0-2]\d)")


def year_from_filename(filename: str) -> int | None:
    m = _YEAR_RE.search(filename)
    return int(m.group(1)) if m else None


def year_from_text(text: str, max_chars: int = 5000) -> int | None:
    """Guess the fiscal year from the document's first pages' text.

    Looks for patterns like '31 December 2024', 'December 31, 2024',
    'Tahun Buku 2024', 'Laporan Keuangan 2024', or a bare recent year.
    """
    head = text[:max_chars]
    patterns = [
        r"(?:Tahun\s+Buku|Fiscal\s+Year|Year\s+Ended|Year\s+then\s+Ended)\s*:?\s*(20[0-2]\d)",
        r"(?:31|30)\s+(?:Desember|December)\s+(20[0-2]\d)",
        r"(?:Desember|December)\s+(?:31|30),?\s+(20[0-2]\d)",
        r"Laporan\s+(?:Keuangan|Tahunan)\s+(20[0-2]\d)",
    ]
    for pat in patterns:
        m = re.search(pat, head, flags=re.IGNORECASE)
        if m:
            year = int(m.group(1))
            if 2000 <= year <= 2035:
                return year
    # Fallback: the most frequent 20xx year in the header region.
    years = [int(y) for y in re.findall(r"20[0-2]\d", head)]
    candidates = [y for y in years if 2005 <= y <= 2030]
    if candidates:
        return max(set(candidates), key=candidates.count)
    return None
