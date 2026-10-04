import type {
  BatchAction,
  CompanyProfile,
  CompanyRow,
  DocumentDetail,
  DocumentSummary,
  ExportFile,
  ExportResult,
  Paged,
  PageRow,
  ProcessingState,
  Summary,
  FinancialPulse,
  ValidationCheck,
  ValidationFacets,
  ValueFacets,
  ExtractedValue,
  ValueEdit,
  NewValue,
  ResultsSummary,
  ResultsCoverage,
} from './types'

/** Vite proxies /api to the FastAPI backend in dev (see vite.config.ts), and the
 *  backend serves the built SPA from the same origin in production, so a
 *  relative base works in both. */
const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    })
  } catch {
    throw new ApiError(
      'Backend tidak dapat dijangkau. Apakah `python main.py dashboard` berjalan di port 8000?',
      0,
    )
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body; the status line is the best we have */
    }
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** Builds `?a=1&b=x`, dropping null/undefined/empty so callers can pass filter
 *  state straight through without conditionally building the object. A list
 *  value becomes a repeated parameter (`?a=1&a=2`) -- the only lossless way
 *  to carry several values, since a filter's own text can contain the
 *  separator a joined string would need. */
export function qs(params: Record<string, string | number | boolean | string[] | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item !== '' && item !== null && item !== undefined) {
          sp.append(k, String(item))
        }
      }
      continue
    }
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  summary: () => request<Summary>('/summary'),

  /** Corpus-level financial aggregates: which sub-sectors are
   *  covered, the largest companies by each headline figure, and
   *  how many companies report each of the nine indicators.
   *  Computed with the same winner rules as the results grid, so
   *  a leader here cannot disagree with the grid. */
  financialPulse: () => request<FinancialPulse>('/summary/financials'),

  documents: (params: Record<string, string | number | boolean | null>) =>
    request<Paged<DocumentSummary>>(`/documents${qs(params)}`),

  document: (id: number) => request<DocumentDetail>(`/documents/${id}`),

  documentPages: (
    id: number,
    params: Record<string, string | number | boolean | null>,
  ) => request<Paged<PageRow>>(`/documents/${id}/pages${qs(params)}`),

  companies: () => request<{ items: CompanyRow[] }>('/companies'),

  validations: (params: Record<string, string | number | boolean | null>) =>
    request<Paged<ValidationCheck>>(`/validations${qs(params)}`),

  validationFacets: () => request<ValidationFacets>('/validations/facets'),

  values: (params: Record<string, string | number | boolean | null>) =>
    request<Paged<ExtractedValue>>(`/values${qs(params)}`),

  valueFacets: () => request<ValueFacets>('/values/facets'),

  /** The results grid: one row per company-year, one column per extracted
   *  field. `fields` narrows the columns; by default only the headline figures
   *  are shown, in the server's reading order. `subsector` is repeated, once
   *  per selected classification. */
  resultsSummary: (params: Record<string, string | number | string[] | null>) =>
    request<ResultsSummary>(`/results/summary${qs(params)}`),

  /** The same grid as a downloadable .xlsx, filtered the same way but
   *  deliberately unpaginated: a file holding only the visible page would be
   *  worse than no file at all. A URL rather than a promise, because the
   *  browser performs the download -- `request()` is JSON-only. Filters are
   *  passed, `page`/`page_size` deliberately are not. */
  summaryExportUrl: (params: Record<string, string | number | string[] | null>) =>
    `${BASE}/results/summary/export${qs(params)}`,

  /** Which discovered reports have produced values yet. Makes the gap between
   *  "no data" and "not read yet" visible instead of silently omitting rows. */
  resultsCoverage: () => request<ResultsCoverage>('/results/coverage'),

  /** Correct one extracted value, or pass `{ revert: true }` to undo a
   *  correction. Returns the stored row so the caller can adopt the server's
   *  version instead of assuming what was saved. */
  updateValue: (id: number, body: ValueEdit) =>
    request<{ value: ExtractedValue }>(`/values/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  /** Add a figure the extractor did not find, filling an empty grid cell.
   *  Separate from `updateValue` because there is no pipeline figure to
   *  preserve: nothing to correct and nothing to revert to. */
  createValue: (body: NewValue) =>
    request<{ value: ExtractedValue }>('/values', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  processing: () => request<ProcessingState>('/processing'),

  /** Everything known about one company across all of its filings. The name is
   *  a path segment, so it is encoded rather than interpolated. */
  companyProfile: (company: string) =>
    request<CompanyProfile>(`/companies/${encodeURIComponent(company)}`),

  startProcessing: (body: {
    action?: BatchAction
    force?: boolean
    limit?: number | null
    input?: string | null
  }) =>
    request<ProcessingState>('/processing', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /**
   * Ask the running batch to wind down. Cooperative: queued documents never
   * start and in-flight ones finish, so nothing is stranded mid-extraction.
   */
  stopProcessing: () =>
    request<ProcessingState & { stopping: boolean; detail: string }>(
      '/processing/stop',
      { method: 'POST' },
    ),

  log: (lines = 120) => request<{ path: string | null; lines: string[] }>(`/log${qs({ lines })}`),

  runExports: () => request<ExportResult>('/exports', { method: 'POST' }),

  exportFiles: () => request<{ items: ExportFile[] }>('/exports/files'),

  downloadUrl: (name: string) => `${BASE}/exports/download/${encodeURIComponent(name)}`,
}