/** Colour tokens shared by the charts and the status badges.
 *
 * These are CSS variable references rather than literal colours, so a chart
 * re-colours itself when the theme changes - which is why there is no chart
 * colour hardcoded anywhere in the component tree. Kept out of the component
 * modules so those files export components only (keeps React Fast Refresh
 * working). */

/** Categorical series for generic charts. Order matters: adjacent series
 *  should not be the two closest hues. */
export const CHART_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
] as const

/** Semantic slots reused by both document and check statuses. Grouping the
 *  hues this way means "this needs attention" looks the same everywhere: warm
 *  for review, red for failure, green for a clean result. */
export const STATUS_COLORS = {
  ok: 'var(--chart-1)',
  progress: 'var(--chart-2)',
  warn: 'var(--chart-3)',
  danger: 'var(--chart-4)',
  duplicate: 'var(--chart-5)',
  neutral: 'var(--chart-6)',
} as const

export type StatusColorMap = Record<string, string>

export const DOC_STATUS_COLORS: StatusColorMap = {
  COMPLETED: STATUS_COLORS.ok,
  PROCESSING: STATUS_COLORS.progress,
  OCR: STATUS_COLORS.progress,
  EXTRACTING: STATUS_COLORS.progress,
  VALIDATING: STATUS_COLORS.progress,
  DISCOVERED: STATUS_COLORS.neutral,
  REVIEW_REQUIRED: STATUS_COLORS.warn,
  FAILED: STATUS_COLORS.danger,
  DUPLICATE: STATUS_COLORS.duplicate,
}

export const CHECK_STATUS_COLORS: StatusColorMap = {
  VALID: STATUS_COLORS.ok,
  WARNING: STATUS_COLORS.warn,
  ERROR: STATUS_COLORS.danger,
  REVIEW_REQUIRED: STATUS_COLORS.warn,
  NOT_APPLICABLE: STATUS_COLORS.neutral,
  NOT_FOUND: STATUS_COLORS.neutral,
  INCOMPLETE: STATUS_COLORS.duplicate,
  UNMAPPED: STATUS_COLORS.duplicate,
}

/** Order used when laying out donut segments, so the biggest, most actionable
 *  states come first and a given chart always renders the same way. */
export const DOC_STATUS_ORDER = [
  'COMPLETED',
  'PROCESSING',
  'OCR',
  'EXTRACTING',
  'VALIDATING',
  'REVIEW_REQUIRED',
  'FAILED',
  'DISCOVERED',
  'DUPLICATE',
]

export const CHECK_STATUS_ORDER = [
  'ERROR',
  'WARNING',
  'REVIEW_REQUIRED',
  'INCOMPLETE',
  'UNMAPPED',
  'NOT_FOUND',
  'VALID',
  'NOT_APPLICABLE',
]