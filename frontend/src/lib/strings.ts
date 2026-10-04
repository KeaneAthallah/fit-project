/** Every user-facing string in the app, in Indonesian.
 *
 *  Named exports per area rather than a runtime `t('key')`
 *  lookup: the compiler then proves a string exists, and a
 *  missing translation is a type error instead of a raw key
 *  printed on screen. Each area is imported only by the
 *  components that render it. */

import { num } from './format'

export const common = {
  loading: 'Memuat…',
  retry: 'Coba lagi',
  search: 'Cari',
  clear: 'Bersihkan',
  close: 'Tutup',
  open: 'Buka',
  all: 'Semua',
  none: 'Tidak ada',
  of: 'dari',
  perPage: 'per halaman',
  previous: 'Sebelumnya',
  next: 'Berikutnya',
  noResults: 'Tidak ada hasil',
  notAvailable: 'Belum tersedia',
  dataNotAvailable: 'Data belum tersedia',
  cannotLoad: 'Data tidak dapat dimuat',
  loadProblem: 'Terjadi masalah saat mengambil data.',
  refresh: 'Segarkan',
  add: 'Tambah',
  edit: 'Ubah',
  delete: 'Hapus',
  cancel: 'Batal',
  save: 'Simpan',
  confirm: 'Konfirmasi',
  columns: 'Kolom',
  filters: 'Filter',
  export: 'Ekspor',
  source: 'Sumber',
  year: 'Tahun',
  years: 'Tahun',
  pages: 'Halaman',
  figures: 'Angka',
  status: 'Status',
  actions: 'Tindakan',
  companies: 'perusahaan',
  company: 'Perusahaan',
  change: 'Perubahan',
  latestYear: 'Tahun Terbaru',
  reportedYears: 'Tahun Pelaporan',
  /** Tooltip on every compact figure: the exact value is one
   *  hover away, so nothing is ever really rounded away. */
  exactValue: 'Nilai persis',
  /** Shown where a figure was not found in any report. */
  noDataHint: 'Angka ini tidak ditemukan dalam laporan mana pun.',
}

export const nav = {
  dashboard: 'Dasbor',
  documents: 'Dokumen',
  validations: 'Antrean Tinjauan',
  values: 'Nilai',
  results: 'Hasil',
  exports: 'Ekspor',
}

export const app = {
  name: 'Ekstraktor Keuangan',
  openNavigation: 'Buka navigasi',
  closeNavigation: 'Tutup navigasi',
  themeLabel: 'Tema warna',
  themeLight: 'Terang',
  themeDark: 'Gelap',
  themeSystem: 'Sistem',
  themeTooltip: (label: string) => `Tema ${label.toLowerCase()}`,
  running: 'Berjalan',
  idle: 'Siaga',
  batchRunning: 'Pemrosesan berjalan',
}

export const dashboard = {
  title: 'Dasbor',
  subtitle: 'Cakupan ekstraksi dan kesehatan kualitas data di seluruh korpus',
  stats: {
    documents: 'Dokumen',
    pages: 'Halaman',
    checks: 'Pemeriksaan Validasi',
    attention: 'Perlu Perhatian',
    lowConfidence: 'Kepercayaan Rendah',
    avgConfidence: 'Rata-rata Kepercayaan',
    companies: (n: number) => `${n} perusahaan`,
    valuesExtracted: (n: number) => `${n} nilai diekstraksi`,
    errors: (n: number) => `${n} kesalahan`,
    attentionHint: 'dokumen dengan kesalahan atau peringatan',
    lowConfidenceHint: 'nilai di bawah ambang tinjauan',
  },
  cards: {
    byStatus: 'Dokumen berdasarkan status',
    byStatusSub: 'Status pipeline per dokumen',
    viewAll: 'Lihat semua',
    byOutcome: 'Pemeriksaan berdasarkan hasil',
    byOutcomeSub: 'Hasil validasi akuntansi',
    reviewQueue: 'Antrean tinjauan',
    confidence: 'Kepercayaan Ekstraksi',
    confidenceSub: 'Dokumen dikelompokkan berdasarkan rata-rata kepercayaan ekstraksi',
    needingReview: 'Dokumen yang Perlu Ditinjau',
    needingReviewSub: 'Diperingkat berdasarkan pemeriksaan yang gagal',
    noErrors: 'Tidak ada kesalahan validasi',
    frequentChecks: 'Pemeriksaan Paling Sering',
    noChecks: 'Belum ada pemeriksaan yang tercatat',
    categories: 'Kategori',
    noCategories: 'Tidak ada kategori yang tercatat',
    uncategorized: 'tanpa kategori',
    noValues: 'Belum ada nilai yang diekstraksi',
    noValuesHint: 'Proses dokumen untuk mengisi distribusi ini.',
    noDocuments: 'Belum ada dokumen',
    noDocumentsHint:
      'Jalankan Pindai dan Proses di bawah untuk mendaftarkan PDF di folder masukan Anda.',
    checksSuffix: 'pemeriksaan',
    recentlyUpdated: 'Baru diperbarui',
    allDocuments: 'Semua dokumen',
  },
  batch: {
    title: 'Pindai dan proses',
    subtitle:
      'Pindai menjelajahi sebuah folder untuk PDF dan mendaftarkannya; proses kemudian menjalankan OCR, ekstraksi, dan validasi pada yang sudah terdaftar.',
    scanDir: 'Direktori Pindai',
    scanDirPlaceholder: 'Path ke folder berisi PDF',
    scanDirHint:
      'Path relatif diurai dari akar proyek. Path di luarnya ditolak.',
    limit: 'Batas',
    limitPlaceholder: 'semua',
    limitHint: 'Batas opsional',
    resetDir: 'Atur ulang ke direktori yang dikonfigurasi',
    scanProcess: 'Pindai dan proses',
    scanOnly: 'Pindai saja',
    processRegistered: 'Proses yang terdaftar',
    reprocessAll: 'Proses ulang semua',
    retryFailed: 'Coba lagi yang gagal',
    retryReview: 'Coba lagi yang ditinjau',
    running: 'Berjalan',
    stopping: 'Berhenti',
    stop: 'Berhenti',
    started: 'Dimulai',
    stopHint:
      'Dokumen yang sedang dibaca selesai lebih dulu, lalu antrean dikosongkan. Tidak ada yang hilang.',
    liveHint:
      'Kartu ini diperbarui otomatis; detailnya ada di log pada halaman Ekspor.',
    lastRunFailed: 'Pemindaian terakhir gagal.',
    scanned: (dir: string, n: number) =>
      `Berhasil memindai ${dir} — ${n} dokumen baru terdaftar.`,
    dismiss: 'Tutup',
    summary: {
      documents: 'Dokumen',
      companies: 'Perusahaan',
      ocr: 'Dokumen OCR',
      avgConfidence: 'Rata-rata Kepercayaan',
    },
  },
  pulse: {
    title: 'Gambaran Keuangan',
    subtitle:
      'Apa yang dimiliki korpus ini secara finansial: subsektor yang tercakup, perusahaan terbesar, dan indikator yang dilaporkan',
    subsectors: 'Cakupan Subsektor',
    subsectorsSub: 'Perusahaan per klasifikasi yang dideklarasikan',
    undeclared: 'Tanpa subsektor',
    largest: 'Perusahaan Terbesar',
    largestSub: 'Jumlah aset tertinggi — laporan terbaru per perusahaan',
    revenue: 'Pendapatan Tertinggi',
    revenueSub: 'Penjualan dan pendapatan usaha tertinggi',
    profit: 'Laba Tertinggi',
    profitSub: 'Jumlah laba (rugi) tertinggi',
    coverage: 'Cakupan Indikator',
    coverageSub:
      'Perusahaan yang melaporkan masing-masing dari sembilan indikator',
    noData: 'Belum ada angka keuangan',
    noDataHint:
      'Pindai dan proses dokumen untuk melihat gambaran keuangan korpus ini.',
    /** BarList label for a company row: the year its figure comes from. */
    asOf: (year: number | null) => (year ? `tahun ${year}` : 'tahun tidak diketahui'),
  },
}

export const company = {
  loading: 'Memuat perusahaan.',
  notLoaded: 'Tidak ada perusahaan yang dimuat.',
  subtitle: (years: number, latest: number) =>
    `${years} tahun pelaporan, terbaru ${latest}`,
  noYears: 'Tidak ada tahun pelaporan yang bisa dibaca',
  allFigures: 'Semua Angka',
  documents: 'Dokumen',
  coverage: {
    title: 'Cakupan',
    filings: 'Laporan dimiliki',
    produced: 'Angka yang dihasilkan',
    producedOf: (withValues: number, total: number) =>
      `${withValues} dari ${total}`,
    extracted: 'Angka diekstraksi',
    fields: 'Bidang berbeda',
    unfinished: (n: number) =>
      `${n} laporan belum menghasilkan apa pun.`,
  },
  latest: {
    title: 'Tahun Terbaru',
    reportedIn: (currencies: string) => `Dilaporkan dalam ${currencies}`,
    noCurrency: 'Tidak ada mata uang yang terdeteksi di sumber',
  },
  disputed: {
    title: 'Angka Dipersengketakan',
    of: (figures: number) =>
      `dari ${figures} angka utama, di mana sumber tidak sepakat lebih dari setengah`,
    alertTitle: 'Beberapa angka dipersengketakan.',
    alertBody: (n: number) =>
      `${n} bidang memiliki pembacaan yang berbeda lebih dari setengah di seluruh laporan perusahaan ini, jadi tidak satu pun ditampilkan sebagai jawaban. Kepercayaan ekstraktor tertinggi tidak berarti paling benar di sini.`,
    choose: 'Pilih pembacaan yang benar',
  },
  checks: {
    title: 'Pemeriksaan Akuntansi',
    failing: 'gagal atau peringatan di seluruh laporan perusahaan ini',
    failedTitle: 'Pemeriksaan yang tidak lolos',
    failedHint:
      'Pemeriksaan yang gagal tidak berarti angka salah. Artinya angka-angka dalam laporan sendiri tidak cocok, yang perlu diketahui sebelum mengutip salah satunya.',
  },
  kpis: {
    title: 'Ringkasan Keuangan',
    subtitle: 'Empat indikator utama, laporan terbaru. Arahkan kursor untuk nilai persis.',
    equity: 'Komposisi Ekuitas',
    equitySub: 'Ekuitas pemilik entitas induk dan kepentingan non pengendali',
    profitability: 'Profitabilitas',
    profitabilitySub: 'Pendapatan, laba sebelum pajak, dan laba (rugi) per tahun',
    assetsEquity: 'Aset dan Ekuitas',
    assetsEquitySub: 'Jumlah aset dan jumlah ekuitas per tahun',
    tax: 'Aktivitas Pajak',
    taxSub: 'Pajak penghasilan dari aktivitas operasi, per tahun',
    taxPaid: 'Pembayaran pajak penghasilan',
    taxRefund: 'Penerimaan pengembalian pajak',
    taxNone: 'Tidak ada angka pajak penghasilan yang diekstraksi untuk periode ini.',
    overview: 'Ikhtisar Keuangan',
    overviewSub: 'Sembilan indikator utama per tahun pelaporan',
    noFigures: 'Belum ada angka keuangan',
    noFiguresHint:
      'Perusahaan ini belum memiliki angka yang diekstraksi. Pindai dan proses laporannya, atau lihat halaman Hasil.',
    balances: 'seimbang',
    doesNotBalance: 'tidak seimbang',
    valuesAsReported: 'Nilai dalam rupiah, sebagaimana dilaporkan.',
    sourceLine: (filename: string, page: number | null) =>
      `${filename}${page ? ` · Halaman ${page}` : ''}`,
    sourceHint: 'Buka laporan sumber angka ini',
    legendLiabilities: 'Liabilitas',
    legendEquity: 'Ekuitas',
  },
  filings: {
    title: (n: number) => `Laporan (${n})`,
    subtitle: 'Setiap laporan yang dimiliki perusahaan ini, apakah atau tidak menghasilkan angka.',
    report: 'Laporan',
    year: 'Tahun',
    pages: 'Halaman',
    figures: 'Angka',
    status: 'Status',
    open: 'Buka',
  },
}

/** Status enum values as the reader sees them. The backend stores
 *  English keys; the product's working language is Indonesian, so
 *  the labels a badge or a filter option shows live here. Pages
 *  fall back to the raw key for a status this table does not know. */
export const DOC_STATUS_LABELS: Record<string, string> = {
  DISCOVERED: 'Ditemukan',
  PROCESSING: 'Diproses',
  OCR: 'OCR',
  EXTRACTING: 'Mengekstraksi',
  VALIDATING: 'Memvalidasi',
  COMPLETED: 'Selesai',
  REVIEW_REQUIRED: 'Perlu ditinjau',
  FAILED: 'Gagal',
  DUPLICATE: 'Duplikat',
}

export const CHECK_STATUS_LABELS: Record<string, string> = {
  VALID: 'Valid',
  WARNING: 'Peringatan',
  ERROR: 'Gagal',
  NOT_APPLICABLE: 'Tidak berlaku',
  NOT_FOUND: 'Tidak ditemukan',
  INCOMPLETE: 'Belum lengkap',
  REVIEW_REQUIRED: 'Perlu ditinjau',
  UNMAPPED: 'Belum dipetakan',
}

export const VALUE_STATUS_LABELS: Record<string, string> = {
  OK: 'Baik',
  ACCEPTED: 'Diterima',
  REJECTED: 'Ditolak',
  IMPLAUSIBLE: 'Tidak masuk akal',
  FLAGGED: 'Diflag',
  REVIEW_REQUIRED: 'Perlu ditinjau',
}

export const results = {
  title: 'Hasil',
  subtitle: 'Angka utama per perusahaan-tahun. Klik angka apa pun untuk mengoreksinya.',
  correctionsNote: {
    lead: 'Koreksi menyimpan bacaan asli ekstraktor di sampingnya, dan',
    revert: 'Kembalikan',
    tail: 'mengembalikannya. Koreksi bertahan saat pemrosesan ulang, tetapi pemeriksaan validasi dokumen tidak dihitung ulang secara otomatis.',
  },
  clearFilters: (n: number) => `Bersihkan ${n} filter`,
  grid: {
    company: 'Perusahaan',
    year: 'Tahun',
    currency: 'Mata Uang',
    currencyHint:
      'Mata uang pelaporan yang ditemukan di sumber. "Tidak terdeteksi" berarti tidak ada mata uang yang ditemukan, bukan berarti rupiah.',
    subsector: 'Subsektor',
    subsectorHint:
      'Klasifikasi bisnis yang dideklarasikan pada sampul laporan. Satu per perusahaan; pilih beberapa untuk membandingkannya.',
    allSubsectors: 'Semua subsektor',
    noSubsectorDeclared: 'Tanpa subsektor yang dideklarasikan',
    noNetLoss: 'Laba terus',
    noNetLossHint:
      'Hanya perusahaan-tahun yang melaporkan laba. Tahun yang rugi, atau tidak menunjukkan angka laba, ditinggalkan.',
    allCompanies: 'Semua perusahaan',
    allYears: 'Semua tahun',
    summary: (total: number, fields: number, page: number, pages: number) => {
      const s = `${num(total)} perusahaan-tahun · ${num(fields)} angka`
      return pages > 1 ? `${s} · halaman ${num(page)} dari ${num(pages)}` : s
    },
    checksFailed: (n: number) => `${n} pemeriksaan gagal`,
    mixed: 'Campuran',
    notDetected: 'Tidak terdeteksi',
    notDetectedHint: 'Tidak ada mata uang yang ditemukan di sumber untuk angka-angka ini.',
    noMatchTitle: 'Tidak ada perusahaan-tahun yang cocok',
    noMatchHint: 'Sesuaikan filter, atau proses lebih banyak dokumen dari dasbor.',
    export: 'Ekspor ke Excel',
    exportNothingTitle:
      'Tidak ada yang diekspor: tidak ada perusahaan-tahun yang cocok dengan filter saat ini.',
    exportTitle: (rows: number) =>
      `Unduh semua ${num(rows)} baris sebagai .xlsx, setiap halaman, dengan lembar yang menjelaskan sel kosong dan mata uangnya`,
    caption: 'Ringkasan hasil per perusahaan dan tahun',
    sourceDetailsTitle:
      'Dokumen sumber dan pemeriksaan untuk perusahaan ini',
    openProfile: (company: string) => `Buka profil ${company}`,
    notReconciling: (checks: string) =>
      `Angka-angka ini tidak cocok: ${checks}. Pipeline menjalankan pemeriksaan ini dan tidak terpenuhi.`,
  },
  editor: {
    amountLabel: (mode: 'add' | 'edit') =>
      mode === 'edit' ? 'Jumlah koreksi (rupiah penuh)' : 'Jumlah (rupiah penuh)',
    currentHint: (current: string) =>
      `Saat ini ${current}. Kosongkan kolom untuk membiarkannya kosong.`,
    report: 'Laporan',
    documentFallback: (id: number) => `Dokumen ${id}`,
    reason: 'Alasan (opsional)',
    reasonHint: 'Disimpan di baris agar perubahan dapat diaudit nanti.',
    reasonPlaceholder: 'mis. salah skala di halaman ringkasan',
    save: (mode: 'add' | 'edit') => (mode === 'edit' ? 'Simpan koreksi' : 'Tambah angka'),
    cancel: 'Batal',
    revertTo: (value: string) => `Kembalikan ke ${value}`,
    addManualNote:
      ' — angka ini dimasukkan oleh tangan, jadi tidak ada pembacaan ekstraktor yang bisa dikembalikan.',
    addEmptyError: 'Masukkan angka yang ditambahkan.',
    addNoDocumentError: 'Pilih laporan angka ini berasal.',
    filedUnder: (filename: string) =>
      `Disimpan di bawah ${filename}. Tetap ada meskipun laporan diproses ulang.`,
  },
  processing: {
    stopped:
      'Pemrosesan berhenti. Dokumen yang sedang dibaca selesai dan tersimpan; sisanya masih dalam antrean.',
    dismiss: 'Tutup',
    stopping: 'Berhenti...',
    stoppingHint:
      'Dokumen yang sedang dibaca selesai lebih dulu, lalu antrean dikosongkan. Tidak ada yang hilang.',
    running: 'Pemrosesan berjalan di latar belakang.',
    runningHint: 'Grid ini diperbarui saat setiap laporan dibaca.',
    stop: 'Berhenti',
  },
  coverage: {
    showing: (withValues: number, discovered: number) =>
      `Menampilkan ${num(withValues)} dari ${num(discovered)} perusahaan`,
    missing: (
      withoutValues: number,
      documentsWithValues: number,
      documentsTotal: number,
      breakdown: string,
    ) =>
      `${num(withoutValues)} perusahaan belum memiliki angka karena laporannya belum dibaca: ${num(documentsWithValues)} dari ${num(documentsTotal)} dokumen menghasilkan data (${breakdown}). Mereka tidak ada di grid di bawah karena belum ada yang diekstraksi, bukan karena laporannya absen.`,
    processRemaining: 'Proses dokumen yang tersisa',
    starting: 'Memulai...',
    watchProgress: 'Pantau perkembangannya di dasbor',
    showCompanies: (n: number) => `Tampilkan ${num(n)} perusahaan`,
    docs: (n: number) => `${num(n)} dokumen`,
  },
  sources: {
    title: (n: number) => `Laporan sumber (${num(n)})`,
    none: 'Tidak ada laporan yang terhubung ke angka-angka ini.',
    currencyLine: (currency: string, year: string) =>
      `Mata uang pelaporan: ${currency} · angka-angka untuk ${year}.`,
    checksTitle: (n: number) => `Pemeriksaan yang tidak lolos (${num(n)})`,
    allHeld:
      'Setiap identitas akuntansi yang bisa diuji pipeline untuk perusahaan-tahun ini terpenuhi. Pemeriksaan yang tidak bisa dijalankan dilaporkan sebagai "data tidak cukup" dan bukan kegagalan.',
    notReconciled:
      'Angka-angka ini diketahui tidak cocok. Setidaknya satu angka dalam setiap identitas di bawah salah; pemeriksaan tidak bisa menyebutkan yang mana.',
    fullBreakdown: 'Lihat rincian lengkap',
    reportFallback: (id: number) => `Laporan ${id}`,
    notStated: 'tidak dinyatakan',
    undated: 'laporan tanpa tanggal',
  },
  dispute: {
    title: (n: number, where: string) => `${num(n)} pembacaan ${where} tidak sepakat`,
    hint:
      'Grid tidak akan memilih satu untuk Anda. Kepercayaan ekstraktor yang lebih tinggi tidak berarti lebih benar di sini — pada laporan seperti ini, bacaan yang salah skalanya justru sering skor lebih tinggi. Pilih bacaan yang cocok dengan sumber, atau tutup ini dan ketik angkanya sendiri.',
    value: 'Nilai',
    rawText: 'Teks mentah',
    report: 'Laporan',
    page: 'Halaman',
    confidence: 'Kepercayaan',
    useThis: 'Gunakan ini',
    selected: 'Terpilih',
    couldNotSave: 'Gagal menyimpan.',
    accept: 'Terima pembacaan ini',
    saving: 'Menyimpan...',
    close: 'Tutup',
    recordedAsManual:
      'Tercatat sebagai koreksi tangan, jadi mulai sekarang nilai ini yang menang dan bacaan ekstraktor disimpan untuk audit.',
  },
}

export const documents = {
  title: 'Dokumen',
  matchCount: (n: number) => `${num(n)} dokumen cocok`,
  live: 'Langsung',
  refresh: 'Segarkan',
  search: 'Cari',
  searchPlaceholder: 'Perusahaan atau nama berkas',
  status: 'Status',
  company: 'Perusahaan',
  allCompanies: 'Semua perusahaan',
  validation: 'Validasi',
  allStatuses: 'Semua status',
  anyValidationState: 'Status validasi apa pun',
  validationPrefix: 'Validasi:',
  sort: 'Urutan',
  ascending: 'menaik',
  descending: 'menurun',
  sortHint: 'ketuk kepala kolom untuk mengubah',
  clearFilters: 'Bersihkan filter',
  rows: 'Baris',
  noMatchTitle: 'Tidak ada dokumen yang cocok dengan filter ini',
  noMatchHintFiltered: 'Coba bersihkan satu filter.',
  noMatchHint: 'Jalankan pipeline dari dasbor untuk menemukan dokumen.',
  tableHeaders: {
    company: 'Perusahaan',
    status: 'Status',
    year: 'Tahun',
    pages: 'Halaman',
    financial: 'Keuangan',
    confidence: 'Kepercayaan',
    checks: 'Pemeriksaan',
    values: 'Nilai',
    updated: 'Diperbarui',
  },
  sortKeys: {
    company: 'Perusahaan',
    filename: 'Nama berkas',
    status: 'Status',
    pages: 'Halaman',
    confidence: 'Kepercayaan',
    year: 'Tahun',
    updated: 'Diperbarui',
    id: 'ID',
  },
}

export const docDetail = {
  allDocuments: 'Semua dokumen',
  refresh: 'Segarkan',
  invalidId: 'ID dokumen tidak valid',
  tabs: {
    values: 'Nilai terekstraksi',
    checks: 'Pemeriksaan validasi',
    pages: 'Halaman',
  },
  overview: {
    title: 'Ekstraksi',
    status: 'Status',
    reportingYear: 'Tahun pelaporan',
    pdfType: 'Jenis PDF',
    ocrUsed: 'OCR dipakai',
    yes: 'Ya',
    no: 'Tidak',
    pages: 'Halaman',
    textPages: 'Halaman teks',
    ocrPages: 'Halaman OCR',
    financialPages: 'Halaman keuangan',
    values: 'Nilai',
    processingTime: 'Waktu pemrosesan',
    avgConfidence: 'Rata-rata kepercayaan',
    completed: 'Selesai',
  },
  validation: {
    title: 'Validasi',
    subtitle: (n: number) => `${num(n)} pemeriksaan tercatat`,
    none: 'Belum ada pemeriksaan validasi',
  },
  sourceFile: {
    title: 'Berkas sumber',
    createdUpdated: (created: string, updated: string) =>
      `Dibuat ${created} · Diperbarui ${updated}`,
  },
  values: {
    none: 'Belum ada nilai diekstraksi',
    caption: 'Nilai terekstraksi',
    statement: 'Pernyataan',
    field: 'Bidang',
    rawLabel: 'Label mentah',
    raw: 'Mentah',
    normalised: 'Ternormalisasi',
    unit: 'Unit',
    page: 'Halaman',
    method: 'Metode',
    confidence: 'Kepercayaan',
    status: 'Status',
  },
  checks: {
    none: 'Belum ada pemeriksaan validasi tercatat',
    caption: 'Pemeriksaan validasi',
    check: 'Pemeriksaan',
    status: 'Status',
    expected: 'Diharapkan',
    actual: 'Aktual',
    difference: 'Selisih',
    message: 'Pesan',
  },
  pages: {
    loadText: 'Muat teks halaman terekstraksi',
    textCurrentOnly: 'Teks hanya diambil untuk halaman saat ini.',
    textEnableHint: 'Aktifkan teks untuk memeriksa bacaan OCR.',
    none: 'Belum ada catatan halaman',
    caption: 'Halaman',
    page: 'Halaman',
    type: 'Jenis',
    section: 'Bagian',
    ocrConfidence: 'Konf. OCR',
    ocrTime: 'Waktu OCR',
    chars: 'Karakter',
    flags: 'Tanda',
    hideText: 'Sembunyikan teks terekstraksi',
    showText: 'Tampilkan teks terekstraksi',
    enableFirst: 'Aktifkan "Muat teks halaman terekstraksi" dulu',
    relevant: 'relevan',
    parentOnly: 'induk saja',
    relevantSr: 'Halaman relevan. ',
    noText: 'Belum ada teks tercatat untuk halaman ini.',
  },
}

export const validations = {
  title: 'Antrean Tinjauan',
  matchCount: (n: number, filtered: boolean) =>
    `${num(n)} pemeriksaan cocok${filtered ? ' (difilter)' : ''}`,
  subtitle: 'Hasil validasi akuntansi di seluruh dokumen',
  refresh: 'Segarkan',
  checksCenter: 'pemeriksaan',
  noResultsYet: 'Belum ada hasil validasi',
  search: 'Cari',
  searchPlaceholder: 'Perusahaan, pemeriksaan, atau pesan',
  outcome: 'Hasil',
  check: 'Pemeriksaan',
  category: 'Kategori',
  year: 'Tahun',
  company: 'Perusahaan',
  allOutcomes: 'Semua hasil',
  allChecks: 'Semua pemeriksaan',
  allCategories: 'Semua kategori',
  allYears: 'Semua tahun',
  allCompanies: 'Semua perusahaan',
  clearFilters: 'Bersihkan filter',
  clearN: (n: number) => `Bersihkan ${n} filter`,
  noMatchTitle: 'Tidak ada pemeriksaan yang cocok',
  noMatchHintFiltered: 'Coba bersihkan satu filter.',
  noMatchHint: 'Hasil validasi muncul setelah dokumen diproses.',
  tableHeaders: {
    outcome: 'Hasil',
    check: 'Pemeriksaan',
    company: 'Perusahaan',
    year: 'Tahun',
    expected: 'Diharapkan',
    actual: 'Aktual',
    difference: 'Selisih',
    message: 'Pesan',
  },
  caption: 'Pemeriksaan validasi',
}

export const values = {
  title: 'Nilai',
  matchCount: (n: number) => `${num(n)} nilai cocok`,
  subtitle: 'Pos keuangan terekstraksi',
  refresh: 'Segarkan',
  search: 'Cari',
  searchPlaceholder: 'Bidang, label, atau perusahaan',
  statement: 'Pernyataan',
  field: 'Bidang',
  year: 'Tahun',
  company: 'Perusahaan',
  confidence: 'Kepercayaan',
  currency: 'Mata Uang',
  currencyHint:
    '"Tidak terdeteksi" berarti tidak ada mata uang yang ditemukan di sumber, bukan berarti rupiah.',
  sortBy: 'Urutkan berdasarkan',
  direction: 'Arah',
  ascending: 'menaik',
  descending: 'menurun',
  clearFilters: 'Bersihkan filter',
  clearN: (n: number) => `Bersihkan ${n} filter`,
  allStatements: 'Semua pernyataan',
  allFields: 'Semua bidang',
  allYears: 'Semua tahun',
  allCompanies: 'Semua perusahaan',
  confidenceFloors: [
    { value: '', label: 'Kepercayaan apa pun' },
    { value: '0.99', label: '99% ke atas' },
    { value: '0.95', label: '95% ke atas' },
    { value: '0.9', label: '90% ke atas' },
    { value: '0.8', label: '80% ke atas (ambang tinjauan)' },
    { value: '0', label: 'Di bawah 50% (perlu ditinjau)' },
  ],
  noMatchTitle: 'Tidak ada nilai yang cocok dengan filter ini',
  noMatchHintFiltered: 'Coba bersihkan satu filter.',
  noMatchHint: 'Nilai muncul setelah dokumen diproses.',
  tableHeaders: {
    field: 'Bidang',
    statement: 'Pernyataan',
    company: 'Perusahaan',
    year: 'Tahun',
    value: 'Nilai',
    raw: 'Mentah',
    unit: 'Unit',
    currency: 'Mata Uang',
    page: 'Halaman',
    confidence: 'Kepercayaan',
    status: 'Status',
  },
  sortKeys: {
    field: 'Bidang',
    value: 'Nilai',
    confidence: 'Kepercayaan',
    year: 'Tahun',
    company: 'Perusahaan',
    page: 'Halaman',
  },
  caption: 'Nilai terekstraksi',
  notDetected: 'Tidak terdeteksi',
  notDetectedHint: 'Tidak ada mata uang yang ditemukan di sumber untuk angka ini.',
  footnote:
    'Angka ditampilkan lengkap, persis sebagaimana diekstraksi — tidak ada yang diskalakan atau dibulatkan. "Mentah" adalah angka sebagaimana tercetak di laporan; "Nilai" adalah angka yang sudah dinormalisasi setelah unit pada halaman itu diterapkan. "Tidak terdeteksi" di kolom mata uang berarti tidak ada mata uang yang ditemukan di sumber, yang tidak sama dengan rupiah.',
}

export const exports = {
  title: 'Ekspor',
  subtitle: 'Hasilkan laporan yang dapat diunduh dan periksa log pemrosesan',
  batchRunning:
    'Pemrosesan berjalan. Menghasilkan laporan sekarang mungkin menangkap data yang belum lengkap.',
  files: {
    title: 'Berkas yang dihasilkan',
    subtitle: 'Laporan CSV dan Excel yang ditulis ke direktori keluaran',
    generate: 'Hasilkan laporan',
    notice: (reports: number, review: number) =>
      `${num(reports)} berkas laporan dan ${num(review)} berkas tinjauan dihasilkan.`,
    dismiss: 'Tutup',
    noneTitle: 'Belum ada ekspor',
    noneHint:
      'Jalankan pipeline, lalu hasilkan laporan untuk membuat berkas CSV yang bisa ditinjau.',
    summaryReports: 'Laporan ringkasan',
    reviewQueue: 'Antrean tinjauan',
    file: 'Berkas',
    size: 'Ukuran',
    modified: 'Diubah',
    download: 'Unduh',
  },
  log: {
    title: 'Log pipeline',
    tailing: (path: string) => `Mengikuti ${path}`,
    lastLines: 'Baris terakhir dari log pemrosesan',
    lineCountLabel: 'Jumlah baris log',
    lines: (n: number) => `${n} baris`,
    refresh: 'Segarkan',
    emptyTitle: 'Log kosong',
    emptyHint: 'Belum ada pemrosesan yang menulis ke log.',
  },
}
