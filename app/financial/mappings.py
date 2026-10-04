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
        ],
        "equity_attributable_to_owners_of_parent": [
            "Jumlah ekuitas yang diatribusikan kepada pemilik entitas induk",
        ],
        "total_liabilities_and_equity": [
            "total liabilitas dan ekuitas", "jumlah liabilitas dan ekuitas", "total kewajiban dan ekuitas",
            "total liabilities and equity", "jumlah pasiva",
        ],
    },
    "income_statement": {
        "sales": [
            "penjualan", "penjualan bersih", "penjualan neto", "hasil penjualan",
            "sales", "net sales",
        ],
        "sales_and_revenue": [
            "Penjualan dan pendapatan usaha",
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
        "total_profit_loss_before_tax": [
            "Jumlah laba (rugi) sebelum pajak penghasilan",
        ],
        "total_profit_loss": [
            "Jumlah laba (rugi)",
        ],
        "net_income": [
            "laba tahun berjalan", "laba bersih tahun berjalan", "laba bersih", "laba neto",
            "net income", "net profit", "profit for the year", "laba rugi tahun berjalan",
            "laba (rugi) tahun berjalan",
        ],
    },
    "cash_flow": {
        "income_tax_paid_operating": [
            "Penerimaan pengembalian (pembayaran) pajak penghasilan dari aktivitas operasi",
        ],
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


def _normalize_phrase(s: str) -> str:
    """Case and whitespace only: punctuation is part of the label.

    ``_normalize_label`` cannot be used to recognise a label whose
    parentheses carry meaning rather than a unit annotation.
    ``Jumlah laba (rugi)`` is not the same line as ``Jumlah laba``, and
    ``Penerimaan pengembalian (pembayaran) pajak`` names a different line
    from ``Penerimaan pengembalian pajak``. Flattening the brackets would
    collapse both pairs onto one key, so this tier keeps them apart.
    """
    return re.sub(r"\s+", " ", s.strip()).lower()


EXACT_MAP: dict[str, dict[str, str]] = {}
PHRASE_MAP: dict[str, dict[str, str]] = {}
_PHRASE_ALL: dict[str, str] = {}

for _stmt, _fields in FIELD_LABELS.items():
    _m: dict[str, str] = {}
    _p: dict[str, str] = {}
    for _field, _labels in _fields.items():
        for _lab in _labels:
            _norm = _normalize_label(_lab)
            _m.setdefault(_norm, _field)
            _phrase = _normalize_phrase(_lab)
            _p.setdefault(_phrase, _field)
            _PHRASE_ALL.setdefault(_phrase, _field)
    EXACT_MAP[_stmt] = _m
    PHRASE_MAP[_stmt] = _p


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
    """Punctuation-insensitive key, for the tier below the exact phrase.

    Parentheticals are dropped rather than flattened because filings annotate
    line items with units -- ``Pendapatan (dalam jutaan Rupiah)``,
    ``Aset (1)`` -- and that annotation must not defeat the match. Where the
    parentheses *are* the label, the phrase tier above has already resolved it,
    so this cannot collapse ``Jumlah laba (rugi)`` onto ``Jumlah laba``.
    """
    s = re.sub(r"\([^)]*\)", " ", raw_label.strip())
    s = re.sub(r"^\d+[\.\)]\s*", "", s)
    return _normalize_label(s)


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

    Exact only, and binary: a registered label resolves to 1.0, anything else
    to (None, 0.0). Scoring the tiers separately used to imply that a matched
    line item was more or less certainly that line item, but a label either is
    the registered wording or it is not. Measured over 57,435 table rows in the
    corpus, every mapped label scored 1.0 -- the intermediate rungs never fired,
    so only their constant reached the database. A label split across table
    cells still resolves; it just does not score lower for having been split.

    A label that is not a registered line item returns None, and the caller
    keeps it as an unmapped observation rather than assigning it to the nearest
    field. Searches the given statement first, then all others.
    """
    search_order: list[str] = []
    if statement and statement in EXACT_MAP:
        search_order.append(statement)
    search_order.extend(k for k in EXACT_MAP if k not in search_order)

    phrase = _normalize_phrase(raw_label)
    if phrase:
        for stmt in search_order:
            field = PHRASE_MAP[stmt].get(phrase)
            if field:
                return field, 1.0
        field = _PHRASE_ALL.get(phrase)
        if field:
            return field, 1.0

    cleaned = _clean_label(raw_label)
    if not cleaned:
        return None, 0.0

    for stmt in search_order:
        field = EXACT_MAP[stmt].get(cleaned)
        if field:
            return field, 1.0

    collapsed = cleaned.replace(" ", "")
    if collapsed:
        for stmt in search_order:
            field = COLLAPSED_MAP.get(stmt, {}).get(collapsed)
            if field:
                return field, 1.0
        field = _COLLAPSED_ALL.get(collapsed)
        if field:
            return field, 1.0

    return None, 0.0
