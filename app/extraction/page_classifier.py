"""Page-level classification: which financial statement section does a page belong to?"""
from __future__ import annotations

import re

# Ordered: first strong match wins. Regexes are line-start tolerant.
SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("balance_sheet", re.compile(
        r"(laporan\s+posisi\s+keuangan|neraca|statement\s+of\s+financial\s+position|balance\s+sheet)", re.I)),
    ("income_statement", re.compile(
        r"(laporan\s+laba\s+rugi|laporan\s+labarugi|perhitungan\s+hasil\s+usaha|"
        r"statement\s+of\s+profit\s+or\s+loss|income\s+statement|profit\s+and\s+loss)", re.I)),
    ("cash_flow", re.compile(
        r"(laporan\s+arus\s+kas|statement\s+of\s+cash\s+flows?|cash\s+flow\s+statement)", re.I)),
    ("equity", re.compile(
        r"(laporan\s+perubahan\s+ekuitas|statement\s+of\s+changes?\s+in\s+equity)", re.I)),
    ("notes", re.compile(
        r"(catatan\s+atas\s+laporan\s+keuangan|notes\s+to\s+(the\s+)?financial\s+statements?)", re.I)),
    ("comprehensive_income", re.compile(
        r"(laporan\s+penghasilan\s+komprehensif|statement\s+of\s+comprehensive\s+income)", re.I)),
]

# Standalone qualifier lines printed under the company name on a statement page.
# These must be *whole lines*: "ENTITAS INDUK" (parent entity) is the opposite of
# "DAN ENTITAS ANAK" (and its subsidiaries), and a loose substring search for
# "entitas induk" matches ordinary notes prose plus the standard
# "Catatan atas laporan keuangan konsolidasian" boilerplate on nearly every page.
PARENT_ONLY_MARKER_RE = re.compile(
    r"^\(?\s*(entitas\s+induk|parent\s+only|parent\s+entity)\s*\)?$", re.I)
CONSOLIDATED_MARKER_RE = re.compile(
    r"^\(?\s*(dan\s+entitas\s+anak(?:nya)?|and\s+(?:its\s+)?subsidiaries|"
    r"konsolidasian|consolidated)\s*\)?$", re.I)
SUPPLEMENTARY_INFO_RE = re.compile(
    r"(informasi\s+keuangan\s+tambahan|supplementary\s+financial\s+information)", re.I)

# Keywords that mark a page as likely containing financial statement data worth
# sending to the AI/table extraction layers.
RELEVANCE_KEYWORDS = [
    "aset", "liabilitas", "ekuitas", "pendapatan", "laba", "beban", "kas",
    "arus kas", "total", "assets", "liabilities", "equity", "revenue", "profit",
    "expenses", "cash", "retained earnings", "saldo awal", "saldo akhir",
]

# High-signal keywords (requirement #16): weighted scoring for financial pages.
STRONG_KEYWORDS = [
    "laporan posisi keuangan", "laporan laba rugi", "laporan arus kas",
    "laporan perubahan ekuitas", "neraca", "catatan atas laporan keuangan",
    "statement of financial position", "income statement", "cash flows",
    "statement of changes in equity",
]
MEDIUM_KEYWORDS = [
    "pendapatan", "laba", "aset", "liabilitas", "ekuitas", "kas", "modal",
    "saham", "saham treasuri", "revenue", "equity", "capital", "treasury shares",
]


def financial_page_score(text: str) -> int:
    """Cheap deterministic relevance score for a page (requirement #16).

    Strong statement-title keywords score 3 each; medium financial terms 1
    each; capped at 20. Pages scoring >= min_financial_page_score go through
    the expensive extraction pipeline; the rest are skipped.
    """
    low = (text or "").lower()
    score = 0
    for kw in STRONG_KEYWORDS:
        if kw in low:
            score += 3
    for kw in MEDIUM_KEYWORDS:
        if kw in low:
            score += 1
    # numeric density bonus: statements are full of numbers
    digits = sum(1 for ch in low if ch.isdigit())
    if digits > 200:
        score += 2
    elif digits > 50:
        score += 1
    return min(score, 20)

TITLE_RE = re.compile(
    r"(laporan\s+(?:posisi\s+keuangan|laba\s+rugi|arus\s+kas|perubahan\s+ekuitas|penghasilan\s+komprehensif)|"
    r"neraca|catatan\s+atas\s+laporan\s+keuangan|"
    r"statement\s+of\s+(?:financial\s+position|profit\s+or\s+loss|cash\s+flows?|changes\s+in\s+equity|comprehensive\s+income)|"
    r"balance\s+sheet|income\s+statement|notes\s+to\s+(?:the\s+)?financial\s+statements?)",
    re.I,
)


def classify_section(text: str) -> str | None:
    """Return the section key if the page looks like a primary statement page."""
    head = text[:1200]
    for key, pat in SECTION_PATTERNS:
        m = pat.search(head)
        if m:
            # "Catatan atas ..." mentions other statements in the title of the
            # notes; if 'catatan' matched first we already return notes since
            # it is earlier in the list only for exact matches. Prefer exact
            # title matches near the top of the page.
            return key
    return None


def classify_section_strict(text: str) -> str | None:
    """Classify only when a statement title appears near the page top."""
    head = text[:600]
    for key, pat in SECTION_PATTERNS:
        if pat.search(head):
            return key
    return None


def is_parent_only_page(text: str) -> bool:
    """True when a statement page presents the *parent company alone*, not the group.

    Indonesian annual reports often append the parent's separate ("entitas induk")
    financial statements after the consolidated ones, and classify both as
    ``balance_sheet``. They are different reporting entities: mixing them makes
    current/non-current subtotals from one entity fail to reconcile against
    totals from the other. AISA 2021 drew assets from the consolidated pages
    (215-217) but liabilities from the parent's supplementary statements (p364).

    Detection is deliberately narrow. A page qualifies only if it carries an
    explicit supplementary-information header, or has a standalone parent marker
    line within a few lines above the statement title. A consolidated marker in
    the same window always wins, so a page cannot match both.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return False

    if SUPPLEMENTARY_INFO_RE.search("\n".join(lines[:40])[:1500]):
        return True

    for i, ln in enumerate(lines[:40]):
        if not TITLE_RE.search(ln):
            continue
        window = lines[max(0, i - 5):i]
        if any(CONSOLIDATED_MARKER_RE.match(w) for w in window):
            return False
        if any(PARENT_ONLY_MARKER_RE.match(w) for w in window):
            return True
    return False


def is_relevant_page(text: str, min_hits: int = 3) -> bool:
    low = text.lower()
    hits = sum(1 for kw in RELEVANCE_KEYWORDS if kw in low)
    if hits >= min_hits:
        return True
    # A statement title alone also makes a page relevant.
    return TITLE_RE.search(low) is not None


def find_statement_title(text: str) -> str | None:
    m = TITLE_RE.search(text[:1500])
    return m.group(0) if m else None
