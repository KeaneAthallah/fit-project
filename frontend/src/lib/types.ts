/** Response shapes from `app/dashboard/api.py`. Kept hand-written rather than
 *  generated so the contract is visible in one place. */

export type DocStatus =
  | 'DISCOVERED'
  | 'PROCESSING'
  | 'OCR'
  | 'EXTRACTING'
  | 'VALIDATING'
  | 'COMPLETED'
  | 'REVIEW_REQUIRED'
  | 'FAILED'
  | 'DUPLICATE'

export type CheckStatus =
  | 'VALID'
  | 'WARNING'
  | 'ERROR'
  | 'NOT_APPLICABLE'
  | 'NOT_FOUND'
  | 'INCOMPLETE'
  | 'REVIEW_REQUIRED'
  | 'UNMAPPED'

export interface DocumentSummary {
  id: number
  company: string
  filename: string
  file_path: string
  status: DocStatus
  pdf_type: string | null
  page_count: number | null
  text_pages: number | null
  ocr_pages: number | null
  financial_pages: number | null
  ocr_used: boolean
  reporting_year: number | null
  avg_confidence: number | null
  extraction_status: string | null
  validation_status: CheckStatus | null
  processing_time: number | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string | null
  updated_at: string | null
  /** Present on list responses only. */
  validation_errors?: number
  value_count?: number
}

export interface ExtractedValue {
  id: number
  document_id: number
  company: string
  year: number | null
  statement: string
  field: string
  raw_label: string | null
  raw_value: string | null
  normalized_value: number | null
  currency: string | null
  unit: string | null
  page: number | null
  section: string | null
  extraction_method: string
  confidence: number
  status: string
  /** Hand-correction trail. `is_edited` is derived from `edited_at` server-side. */
  original_value: number | null
  original_method: string | null
  edited_at: string | null
  edit_note: string | null
  is_edited: boolean
}

/** Payload for PATCH /api/values/{id}. Either set `normalized_value` or `revert`. */
export interface ValueEdit {
  normalized_value?: number | null
  raw_value?: string
  note?: string
  revert?: boolean
}

/** One figure in the results grid. `null` means the report has no such line --
 *  distinct from a figure that legitimately extracted as zero. */
/** One figure inside a summary row. Mirrors the backend's summary cell. */
/** One reading of a figure, offered when the sources contradict each other. */
export interface SummaryCandidate {
  id: number
  document_id: number
  normalized_value: number
  raw_value: string | null
  unit: string | null
  page: number | null
  confidence: number | null
  status: string
}

export interface SummaryCell {
  id: number
  document_id: number
  normalized_value: number | null
  /** The extractor's reading before any hand correction; null if hand-entered. */
  original_value: number | null
  confidence: number
  status: string
  is_edited: boolean
  /** 'ai' | 'pattern' | 'table' | 'manual' */
  extraction_method: string
  page: number | null
  /** Per figure, because one row can mix currencies ("Mixed"). */
  currency: string | null
  /** True when two readings of this figure differ enough that the grid refuses
   *  to present one as the answer. Confidence cannot break the tie because it
   *  is anti-correlated with correctness on OCR'd statements. */
  disputed?: boolean
  /** Every reading, largest first, when `disputed`. */
  candidates?: SummaryCandidate[]
}

/** One company-year row of the results grid. */
export interface SummaryRow {
  company: string
  year: number | null
  /** Reporting currency for the row: 'IDR', 'USD', 'Not detected' when no
   *  currency was found in the source, or 'Mixed' if the figures disagree. */
  currency: string | null
  /** Reporting sub-sector, when the source declares one (e.g. "Food" or
   *  "Individuals"). The API may send an empty string and it is not
   *  guaranteed to be present. */
  subsector: string | null
  /** The date the company's shares were listed on the exchange
   *  (tanggal pencatatan), ISO format, from the listing register.
   *  Null when the register does not know the company. */
  pencatatan?: string | null
  cells: Record<string, SummaryCell | null>
  /** Reports a hand-entered figure on this row can be filed under, best first.
   *  A value must belong to a document, so an empty cell needs a target. */
  documents?: SummaryDocument[]
  /** Accounting identities the pipeline ran against this company-year that did
   *  NOT hold, e.g. `assets_equals_liabilities_plus_equity`. Empty when the row
   *  reconciles. Without this the grid shows figures that are known not to add
   *  up and says nothing. */
  failed_checks?: Record<string, string>
}

/** A report that contributes to a summary row. */
export interface SummaryDocument {
  id: number
  filename: string | null
  /** Statements this report actually carries, e.g. ['balance_sheet']. */
  statements: string[]
}

/** GET /api/results/coverage */
export interface ResultsCoverage {
  companies_discovered: number
  companies_with_values: number
  companies_without_values: number
  documents_total: number
  documents_with_values: number
  missing: { company: string; documents: number; by_status: Record<string, number> }[]
}

/** Body of POST /api/values. */
export interface NewValue {
  document_id: number
  field: string
  year: number | null
  normalized_value: number
  note?: string | null
  currency?: string | null
}

/** GET /api/results/summary */
export interface ResultsSummary {
  items: SummaryRow[]
  fields: string[]
  /** Display labels keyed by field, so header text lives server-side. */
  labels: Record<string, string>
  /**
   * Currencies present in the fields this grid shows. Scoped to the summary on
   * purpose: the global list also covers fields that are not columns here and
   * would offer filters that can never match a row.
   */
  currencies: { currency: string; count: number }[]
  /**
   * Sub-sectors the current filters can still narrow to, the same way
   * `currencies` is scoped. The literal key `none` is the bucket for
   * company-years whose filing declares no sub-sector.
   */
  subsectors: { subsector: string; count: number }[]
  pagination: Pagination
}

export interface ValidationCheck {
  id: number
  document_id: number
  company: string
  year: number | null
  check_name: string
  expected: string | null
  actual: string | null
  difference: number | null
  status: CheckStatus
  severity: string | null
  category: string | null
  message: string | null
  evidence: string | null
  /** Present on list responses only. */
  file_path?: string | null
}

export interface PageRow {
  id: number
  page_number: number
  pdf_type: string | null
  ocr_confidence: number | null
  ocr_engine: string | null
  ocr_time: number | null
  section: string | null
  is_relevant: boolean
  is_parent_only: boolean
  text: string | null
  text_length: number
}

export interface DocumentDetail extends DocumentSummary {
  values: ExtractedValue[]
  checks: ValidationCheck[]
  page_rows: number
}

export interface Pagination {
  total: number
  page: number
  page_size: number
  pages: number
}

export interface Paged<T> {
  items: T[]
  pagination: Pagination
}

export interface Summary {
  documents: number
  companies: number
  pages: number
  values: number
  checks: number
  low_confidence_values: number
  avg_confidence: number | null
  status_counts: Record<string, number>
  extraction_status_counts: Record<string, number>
  validation_doc_counts: Record<string, number>
  check_status_counts: Record<string, number>
  check_by_name: { check_name: string; status: string; count: number }[]
  check_by_category: { category: string; count: number }[]
  confidence_histogram: { bucket: string; count: number }[]
  worst_companies: { company: string; errors: number }[]
}

export interface CompanyRow {
  company: string
  documents: number
  status_counts: Record<string, number>
}

/** GET /api/summary/financials — the corpus-level aggregates the
 *  home dashboard leads with. `leaders[field]` is ranked largest
 *  first, holding each company's most recently reported figure;
 *  `coverage` counts the distinct companies that report each of
 *  the nine indicators. */
export interface FinancialPulse {
  subsectors: { subsector: string; companies: number }[]
  /** Companies whose filings never declared a sub-sector. */
  undeclared_subsectors: number
  leaders: Record<
    string,
    { company: string; year: number | null; value: number | null }[]
  >
  coverage: Record<string, number>
}

export interface ValidationFacets {
  statuses: { status: string; count: number }[]
  check_names: { check_name: string; count: number }[]
  categories: { category: string; count: number }[]
  years: number[]
}

export interface ValueFacets {
  statements: { statement: string; count: number }[]
  fields: { field: string; count: number }[]
  years: number[]
  /** `currency` is the code, or the literal 'none' for rows where no currency
   *  was detected -- which is not the same as being confirmed IDR. */
  currencies: { currency: string; count: number }[]
}

export type BatchAction =
  | 'scan'
  | 'process'
  | 'scan_process'
  | 'retry_failed'
  | 'retry_review'

export interface ScanResult {
  directory: string
  discovered: number
}

export interface CompanyProfile {
  company: string
  years: number[]
  currencies: string[]
  totals: {
    documents: number
    documents_with_values: number
    figures: number
    years: number
    fields: number
  }
  /** One series per headline metric, oldest year first. */
  metrics: Record<string, SummaryMetricPoint[]>
  quality: {
    figures: number
    disputed_cells: number
    flagged_cells: number
    cells_without_currency: number
    failed_checks: Record<string, string>
    disputed_fields: string[]
  }
  documents: {
    id: number
    filename: string
    file_path: string
    status: string
    pdf_type: string | null
    pages: number | null
    reporting_year: number | null
    values: number
    years: number[]
  }[]
  labels: Record<string, string>
}

/** One year of one metric. Missing years are present with a null value so the
 *  chart keeps an even time axis instead of silently compressing the gaps. */
export interface SummaryMetricPoint {
  year: number
  id?: number
  document_id?: number
  normalized_value: number | null
  currency?: string | null
  status?: string
  is_edited?: boolean
  disputed?: boolean
  /** The declared sub-sector rides here instead of
   *  `normalized_value`, because it is a classification, not a
   *  figure. */
  text_value?: string | null
  /** Statement page the figure was read from, when known. */
  page?: number | null
  confidence?: number
  candidates?: SummaryCandidate[]
}

export interface ProcessingState {
  running: boolean
  /** True once a stop has been requested but in-flight documents are still
   *  draining, so the UI can say "stopping" rather than claiming it stopped. */
  cancel_requested?: boolean
  started_at: string | null
  finished_at: string | null
  result: {
    scanned?: ScanResult
    processed?: Record<string, unknown>
    discovered?: number
  } | null
  error: string | null
  mode: BatchAction | null
  /** Directory that will be scanned; returned by GET /api/processing. */
  input_directory?: string
  summary?: {
    companies: number
    documents: number
    pages: number
    status_counts: Record<string, number>
    ocr_documents: number
    avg_confidence: number | null
  }
}

export interface ExportFile {
  name: string
  kind: 'report' | 'review'
  size: number
  modified_at: string | null
  path: string
}

export interface ExportResult {
  reports: Record<string, number>
  review_queue: Record<string, number>
  summary: Record<string, unknown>
}