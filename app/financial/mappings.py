"""Mapping of financial statement line-item labels to canonical field names.

Each canonical field has a list of label patterns (Indonesian first, English
second). Matching is done on a normalized label (lowercased, punctuation and
extra spaces removed) with exact match first, then substring match.
"""
from __future__ import annotations

import re

FIELD_LABELS: dict[str, dict[str, list[str]]] = {
    "balance_sheet": {
        "total_assets": [
            "total aset", "jumlah aset", "total assets", "jumlah aktiva", "total aktiva",
        ],
        "current_assets": [
            "total aset lancar", "jumlah aset lancar", "total current assets", "jumlah aktiva lancar",
        ],
        "non_current_assets": [
            "total aset tidak lancar", "jumlah aset tidak lancar", "aset tidak lancar",
            "total non-current assets", "total noncurrent assets", "jumlah aktiva tetap dan tidak lancar",
        ],
        "cash_and_cash_equivalents": [
            "kas dan setara kas", "kas dan setara-kas", "kas", "cash and cash equivalents", "cash",
        ],
        "accounts_receivable": [
            "piutang usaha", "piutang dagang", "accounts receivable", "trade receivables",
        ],
        "inventory": [
            "persediaan", "inventories", "inventory",
        ],
        "prepaid_expenses": [
            "beban dibayar dimuka", "biaya dibayar di muka", "uang muka", "prepaid expenses", "prepayments",
        ],
        "fixed_assets": [
            "aset tetap", "aktiva tetap", "property plant and equipment", "properti mesin dan peralatan",
        ],
        "intangible_assets": [
            "aset tidak berwujud", "intangible assets", "aset tak berwujud",
        ],
        "investment_properties": [
            "properti investasi", "investment properties", "investment property",
        ],
        "other_assets": [
            "aset lainnya", "aktiva lainnya", "other assets",
        ],
        "current_liabilities": [
            "total liabilitas jangka pendek", "jumlah liabilitas jangka pendek", "liabilitas jangka pendek",
            "total current liabilities", "kewajiban jangka pendek", "jumlah kewajiban jangka pendek",
        ],
        "non_current_liabilities": [
            "liabilitas jangka panjang", "kewajiban jangka panjang", "total non-current liabilities",
            "total noncurrent liabilities", "jumlah liabilitas jangka panjang",
        ],
        "total_liabilities": [
            "total liabilitas", "jumlah liabilitas", "total kewajiban", "jumlah kewajiban",
            "total liabilities",
        ],
        "issued_and_paid_up_capital": [
            "modal ditempatkan dan disetor", "modal ditempatkan disetor", "modal disetor",
            "modal ditempatkan", "modal saham", "issued and paid up capital",
            "issued and paid-up capital", "issued capital", "paid-up capital", "paid up capital",
            "share capital",
        ],
        "retained_earnings": [
            "saldo laba", "laba ditahan", "retained earnings", "defisit",
        ],
        "total_equity": [
            "total ekuitas", "jumlah ekuitas", "total equity", "jumlah modal", "total shareholders equity",
            "total pemegang saham", "ekuitas yang dapat diatribusikan",
        ],
        "total_liabilities_and_equity": [
            "total liabilitas dan ekuitas", "jumlah liabilitas dan ekuitas", "total kewajiban dan ekuitas",
            "total liabilities and equity", "jumlah pasiva",
        ],
    },
    "income_statement": {
        "revenue": [
            "pendapatan", "pendapatan usaha", "pendapatan dari operasi",
            "revenue", "net revenue",
        ],
        # 'Sales' and 'Revenue' are distinct lines in different reports:
        # some call the top line Penjualan, others Pendapatan. Collapsing them
        # meant a report's sales figure could be presented as its revenue, so
        # they are kept apart and consumers accept either as the top line.
        "sales": [
            "penjualan", "penjualan bersih", "penjualan neto", "hasil penjualan",
            "sales", "net sales",
        ],
        "cost_of_revenue": [
            "beban pokok pendapatan", "beban pokok penjualan", "harga pokok penjualan",
            "cost of revenue", "cost of goods sold", "cost of sales", "beban pokok usaha",
        ],
        "gross_profit": [
            "laba kotor", "laba bruto", "gross profit", "laba usaha kotor",
        ],
        "operating_expenses": [
            "beban operasi", "beban usaha", "beban operasional", "operating expenses", "beban penjualan",
            "beban administrasi dan umum", "beban umum dan administrasi",
        ],
        "operating_income": [
            "laba usaha", "laba operasi", "operating income", "operating profit", "hasil operasi",
        ],
        "finance_income": [
            "pendapatan bunga", "pendapatan finansial", "finance income", "interest income",
            "pendapatan lain-lain",
        ],
        "finance_costs": [
            "beban bunga", "beban finansial", "finance costs", "finance expenses", "interest expense",
        ],
        "profit_before_tax": [
            "laba sebelum pajak", "laba sebelum beban pajak", "profit before tax",
            "laba sebelum pajak penghasilan", "laba sebelum pajak penghasilan",
        ],
        "income_tax": [
            "beban pajak penghasilan", "pajak penghasilan", "income tax", "income tax expense",
        ],
        "net_income": [
            "laba tahun berjalan", "laba bersih tahun berjalan", "laba bersih", "laba neto",
            "net income", "net profit", "profit for the year", "laba rugi tahun berjalan",
            "laba (rugi) tahun berjalan",
        ],
    },
    "cash_flow": {
        "cash_flow_operating": [
            "kas diterima dari aktivitas operasi", "arus kas dari aktivitas operasi",
            "kas neto dari aktivitas operasi", "net cash from operating activities",
            "cash flows from operating activities", "net cash provided by operating activities",
            "aktivitas operasi",
        ],
        "cash_flow_investing": [
            "kas diterima dari aktivitas investasi", "arus kas dari aktivitas investasi",
            "kas neto dari aktivitas investasi", "net cash from investing activities",
            "cash flows from investing activities", "aktivitas investasi",
        ],
        "cash_flow_financing": [
            "kas diterima dari aktivitas pendanaan", "arus kas dari aktivitas pendanaan",
            "kas neto dari aktivitas pendanaan", "net cash from financing activities",
            "cash flows from financing activities", "aktivitas pendanaan", "aktivitas pendanaan (finansing)",
        ],
        "net_change_in_cash": [
            "kenaikan (penurunan) neto kas dan setara kas", "kenaikan penurunan neto kas",
            "kenaikan neto kas dan setara kas", "penurunan neto kas dan setara kas",
            "net increase decrease in cash", "net increase in cash and cash equivalents",
            "kenaikan (penurunan) kas",
        ],
        "beginning_cash_balance": [
            "kas dan setara kas awal periode", "saldo awal kas dan setara kas", "kas dan setara kas pada awal periode",
            "cash and cash equivalents at beginning of period", "kas dan setara kas pada 1 january",
        ],
        "ending_cash_balance": [
            "kas dan setara kas akhir periode", "saldo akhir kas dan setara kas",
            "kas dan setara kas pada akhir periode", "cash and cash equivalents at end of period",
        ],
    },
    "equity": {
        "authorized_capital": [
            "modal dasar", "modal diizinkan", "authorized capital", "authorised capital",
        ],
        "issued_capital": [
            "modal ditempatkan", "issued capital",
        ],
        "paid_up_capital": [
            "modal disetor", "paid-up capital", "paid up capital",
        ],
        "issued_and_paid_up_capital": [
            "modal ditempatkan dan disetor", "modal ditempatkan disetor",
            "modal ditempatkan dan disetor", "modal ditempatkan disetor",
            "issued and paid up capital", "issued and paid-up capital",
            "issued capital and paid up capital",
        ],
        "treasury_shares_quantity": [
            "saham treasuri", "saham treasury", "saham tresuri", "treasury shares",
            "treasury stock", "repurchased shares", "shares repurchased",
        ],
        "treasury_shares_nominal_value": [
            "saham treasuri nominal", "nilai nominal saham treasuri", "treasury shares nominal",
            "treasury stock nominal",
        ],
        "treasury_shares_carrying_value": [
            "saham treasuri", "saham treasury", "saham tresuri", "treasury shares",
            "treasury stock", "repurchased shares", "shares repurchased",
            "modal saham yang diperoleh kembali", "saham yang diperoleh kembali",
        ],
        "additional_paid_in_capital": [
            "agio saham", "tambahan modal disetor", "additional paid-in capital", "agio atas saham",
            "tambahan modal disetor atas saham", "capital surplus", "surplus nilai nominal",
        ],
        "retained_earnings": [
            "saldo laba", "laba ditahan", "retained earnings",
        ],
        "appropriated_retained_earnings": [
            "saldo laba yang disisihkan", "laba ditahan disisihkan", "saldo laba disetorkan",
            "appropriated retained earnings",
        ],
        "unappropriated_retained_earnings": [
            "saldo laba tidak disisihkan", "laba ditahan tidak disisihkan",
            "unappropriated retained earnings",
        ],
        "other_comprehensive_income": [
            "penghasilan komprehensif lain", "laba (rugi) komprehensif lain", "other comprehensive income",
            "saldo komprehensif lain", "penghasilan komprehensif lain tahun berjalan",
        ],
        "other_equity_components": [
            "komponen ekuitas lainnya", "other equity components",
        ],
        "non_controlling_interest": [
            "pengendonlian non pengendali", "kepentingan non pengendali",
            "non controlling interest", "non-controlling interest", "nci",
            "ekuitas yang dapat diatribusikan kepada pemegang saham non pengendali",
        ],
        "total_equity": [
            "total ekuitas", "jumlah ekuitas", "total equity", "jumlah modal dan saldo laba",
        ],
    },
}

# Build normalized lookup structures at import time.
def _normalize_label(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


EXACT_MAP: dict[str, dict[str, str]] = {}
SUBSTRING_ENTRIES: list[tuple[str, str, str]] = []  # (statement, field, normalized_label)

for _stmt, _fields in FIELD_LABELS.items():
    _m: dict[str, str] = {}
    for _field, _labels in _fields.items():
        for _lab in _labels:
            _norm = _normalize_label(_lab)
            _m.setdefault(_norm, _field)
            SUBSTRING_ENTRIES.append((_stmt, _field, _norm))
    EXACT_MAP[_stmt] = _m

SUBSTRING_ENTRIES.sort(key=lambda e: -len(e[2]))  # longest first: most specific label wins


# Whitespace-insensitive tier. Table extraction frequently breaks a word across
# two cells ('aset tidak lan car', 'Ja ngka Pendek'), which is invisible in the
# raw text layer but corrupts the label before mapping. A canonical label and
# its split fragments share a collapsed key, so these resolve to the same field
# without maintaining a dictionary of every splittable word.
COLLAPSED_MAP: dict[str, dict[str, str]] = {}
_COLLAPSED_ALL: dict[str, str] = {}

for _stmt, _entries in EXACT_MAP.items():
    _cm: dict[str, str] = {}
    for _norm, _field in _entries.items():
        _collapsed = _norm.replace(" ", "")
        # setdefault keeps the first field for a collapsed key; a genuine
        # collision is between near-identical labels and the ordering above is
        # deterministic.
        _cm.setdefault(_collapsed, _field)
        _COLLAPSED_ALL.setdefault(_collapsed, _field)
    COLLAPSED_MAP[_stmt] = _cm


def _clean_label(raw_label: str) -> str:
    s = raw_label.strip()
    # Strip share-quantity suffixes so 'Saham Treasuri 1.000 saham' cleans like
    # 'Saham Treasuri'; the value itself is disambiguated separately.
    # Remove trailing parenthetical notes like "(dalam jutaan Rupiah)" and footnote markers
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"^\d+[\.\)]\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    # Repair OCR letter-splitting inside words: 'jangk a pendek' -> 'jangka pendek',
    # 'divide nds' -> 'dividends'. Only joins when the merged word is a known
    # dictionary term — otherwise fragments like 'issued and paid up capital'
    # would merge into nonsense ('paidup') and break mapping.
    lowered = s.lower()
    def _rejoin(match: re.Match[str]) -> str:
        merged = match.group(1) + match.group(2)
        return merged if merged in _KNOWN_COMPOUND_WORDS else match.group(0)
    s = re.sub(r"\b(\w{3,}) ([a-z]{1,3})\b", _rejoin, lowered)
    return _normalize_label(s)


# Words that OCR commonly splits with a stray space ('jangk a', 'K as').
_KNOWN_COMPOUND_WORDS = frozenset({
    "jangka", "kas", "asets", "bersih", "ditahan", "disetor", "ditempatkan",
    "treasuri", "treasury", "pendapatan", "persediaan", "piutang", "beban",
    "laba", "rugi", "ekuitas", "aset", "aktiva", "kewajiban", "liabilitas",
    "dividends", "dividen", "pendek", "panjang", "lainnya", "komprehensif",
    "pengendali", "kepentingan", "berjalan", "disisihkan", "setara",
    "operasi", "usaha", "pokok", "kotor", "pajak", "bunga", "utama",
})


# Labels that are ambiguous on their own: 'saham treasuri' may carry a share
# quantity, nominal value or carrying value; the caller must disambiguate via
# ``resolve_treasury_field`` using the raw value / table context.
AMBIGUOUS_TREASURY_LABELS = frozenset({"treasury_shares_quantity", "treasury_shares_carrying_value"})


def resolve_treasury_field(raw_value: str | None) -> str:
    """Pick the right treasury-shares field based on the raw value.

    '1.000.000 saham'  -> treasury_shares_quantity  (share count, not money)
    '(5.000.000.000)'  -> treasury_shares_carrying_value (monetary, negative)
    '% saham'          -> treasury_shares_percentage
    """
    from app.financial.parser import is_share_quantity

    if raw_value and re.search(r"%|persen|percent", raw_value, re.I):
        return "treasury_shares_percentage"
    if is_share_quantity(raw_value):
        return "treasury_shares_quantity"
    return "treasury_shares_carrying_value"


def map_label(raw_label: str, statement: str | None = None) -> tuple[str | None, float]:
    """Map a raw line-item label to a canonical field.

    Returns (field, confidence). Confidence is 1.0 for exact matches, 0.85 for
    substring matches. Searches the given statement first, then all others.
    """
    cleaned = _clean_label(raw_label)
    if not cleaned:
        return None, 0.0

    search_order: list[str] = []
    if statement and statement in EXACT_MAP:
        search_order.append(statement)
    search_order.extend(k for k in EXACT_MAP if k not in search_order)

    # exact match
    for stmt in search_order:
        field = EXACT_MAP[stmt].get(cleaned)
        if field:
            return field, 1.0

    # whitespace-insensitive match: the label is a canonical one whose word was
    # split by table extraction ('Total aset tidak lan car'). Scored below a true
    # exact hit so a clean label always wins when both are present.
    collapsed = cleaned.replace(" ", "")
    if collapsed:
        for stmt in search_order:
            field = COLLAPSED_MAP.get(stmt, {}).get(collapsed)
            if field:
                return field, 0.95
        field = _COLLAPSED_ALL.get(collapsed)
        if field:
            return field, 0.9

    # substring match (label contains the known label or vice versa)
    for stmt, field, known in SUBSTRING_ENTRIES:
        if statement and stmt != statement and known not in ("total assets", "total ekuitas"):
            continue
        if known in cleaned or cleaned in known:
            if len(cleaned) >= max(4, len(known) // 2):
                return field, 0.85

    return None, 0.0
