/** Indonesian names for the canonical financial fields.
 *
 *  The backend's FIELD_TITLES are English; the product's working
 *  language is Indonesian, and several of these are official
 *  financial-statement line items whose Indonesian names are the ones
 *  an accountant reads on the report itself. `fieldLabel` falls back
 *  to the API's label for a field this table does not know, so a new
 *  extraction field degrades to English rather than to a snake_case
 *  key. */

export const FIELD_LABELS_ID: Record<string, string> = {
  total_assets: 'Jumlah Aset',
  current_assets: 'Total Aset Lancar',
  non_current_assets: 'Total Aset Tidak Lancar',
  cash_and_cash_equivalents: 'Kas dan Setara Kas',
  accounts_receivable: 'Piutang Usaha',
  inventory: 'Persediaan',
  prepaid_expenses: 'Beban Dibayar di Muka',
  fixed_assets: 'Aset Tetap',
  intangible_assets: 'Aset Tidak Berwujud',
  investment_properties: 'Properti Investasi',
  other_assets: 'Aset Lainnya',
  current_liabilities: 'Total Liabilitas Lancar',
  non_current_liabilities: 'Total Liabilitas Tidak Lancar',
  total_liabilities: 'Total Liabilitas',
  issued_and_paid_up_capital: 'Modal Ditempatkan dan Disetor',
  retained_earnings: 'Laba Ditahan',
  total_equity: 'Jumlah Ekuitas',
  equity_attributable_to_owners_of_parent:
    'Ekuitas yang Diatribusikan kepada Pemilik Entitas Induk',
  total_liabilities_and_equity: 'Total Liabilitas dan Ekuitas',
  sales: 'Penjualan',
  sales_and_revenue: 'Penjualan dan Pendapatan Usaha',
  cost_of_revenue: 'Beban Pokok Penjualan',
  gross_profit: 'Laba Kotor',
  operating_expenses: 'Beban Usaha',
  operating_income: 'Laba Usaha',
  finance_income: 'Pendapatan Keuangan',
  finance_costs: 'Beban Keuangan',
  total_profit_loss_before_tax: 'Jumlah Laba (Rugi) Sebelum Pajak Penghasilan',
  total_profit_loss: 'Jumlah Laba (Rugi)',
  net_income: 'Laba (Rugi) Tahun Buku',
  income_tax_paid_operating:
    'Penerimaan Pengembalian (Pembayaran) Pajak Penghasilan dari Aktivitas Operasi',
  sub_sector: 'Subsektor',
  cash_flow_operating: 'Arus Kas dari Aktivitas Operasi',
  cash_flow_investing: 'Arus Kas dari Aktivitas Investasi',
  cash_flow_financing: 'Arus Kas dari Aktivitas Pendanaan',
  net_change_in_cash: 'Perubahan Bersih Kas',
  beginning_cash_balance: 'Kas di Awal Periode',
  ending_cash_balance: 'Kas di Akhir Periode',
  authorized_capital: 'Modal Dasar',
  issued_capital: 'Modal Ditempatkan',
  paid_up_capital: 'Modal Disetor',
  treasury_shares_quantity: 'Saham Treasury (Jumlah)',
  treasury_shares_nominal_value: 'Saham Treasury (Nilai Nominal)',
  treasury_shares_carrying_value: 'Saham Treasury (Nilai Pembukuan)',
  additional_paid_in_capital: 'Tambahan Modal yang Disetor',
  appropriated_retained_earnings: 'Laba Ditahan yang Ditetapkan',
  unappropriated_retained_earnings: 'Laba Ditahan yang Tidak Ditetapkan',
  other_comprehensive_income: 'Penghasilan Komprehensif Lain',
  other_equity_components: 'Komponen Ekuitas Lainnya',
  non_controlling_interest: 'Kepentingan Non Pengendali',
}

/** The nine indicators the product is organized around. `short` is what
 *  a card shows; `full` is the official line-item wording, kept for
 *  tooltips and the Ikhtisar Keuangan table so the long names the
 *  statements print never have to be abbreviated away. */
export const INDICATOR_META: Record<string, { short: string; full: string }> = {
  sub_sector: {
    short: 'Subsektor',
    full: 'Subsektor (klasifikasi IDX yang dideklarasikan laporan)',
  },
  total_assets: {
    short: 'Jumlah Aset',
    full: 'Jumlah Aset',
  },
  equity_attributable_to_owners_of_parent: {
    short: 'Ekuitas Pemilik Entitas Induk',
    full: 'Jumlah Ekuitas yang Diatribusikan kepada Pemilik Entitas Induk',
  },
  non_controlling_interest: {
    short: 'Kepentingan Non Pengendali',
    full: 'Kepentingan Non Pengendali',
  },
  total_equity: {
    short: 'Jumlah Ekuitas',
    full: 'Jumlah Ekuitas',
  },
  sales_and_revenue: {
    short: 'Penjualan dan Pendapatan Usaha',
    full: 'Penjualan dan Pendapatan Usaha',
  },
  total_profit_loss_before_tax: {
    short: 'Laba (Rugi) Sebelum Pajak',
    full: 'Jumlah Laba (Rugi) Sebelum Pajak Penghasilan',
  },
  total_profit_loss: {
    short: 'Jumlah Laba (Rugi)',
    full: 'Jumlah Laba (Rugi)',
  },
  income_tax_paid_operating: {
    short: 'Pajak Penghasilan — Aktivitas Operasi',
    full: 'Penerimaan Pengembalian (Pembayaran) Pajak Penghasilan dari Aktivitas Operasi',
  },
}

/** The Indonesian name of a field, falling back to the API's English
 *  label, then to the raw key. Never returns an empty string. */
export function fieldLabel(field: string, apiLabel?: string): string {
  return FIELD_LABELS_ID[field] ?? apiLabel ?? field
}
