import { titleCase } from '../lib/format'
import { Badge, type Tone } from './ui'

/** Document pipeline states. Semantically grouped rather than one hue per
 *  state: anything still moving is "info", anything needing a human is
 *  "warning", anything broken is "danger". */
const DOC_TONES: Record<string, Tone> = {
  COMPLETED: 'success',
  PROCESSING: 'info',
  OCR: 'info',
  EXTRACTING: 'info',
  VALIDATING: 'info',
  DISCOVERED: 'neutral',
  REVIEW_REQUIRED: 'warning',
  FAILED: 'danger',
  DUPLICATE: 'accent',
}

/** Validation outcomes. */
const CHECK_TONES: Record<string, Tone> = {
  VALID: 'success',
  WARNING: 'warning',
  ERROR: 'danger',
  REVIEW_REQUIRED: 'warning',
  NOT_APPLICABLE: 'neutral',
  NOT_FOUND: 'neutral',
  INCOMPLETE: 'accent',
  UNMAPPED: 'accent',
}

function Dash() {
  return <span className="text-muted-foreground">-</span>
}

export function DocStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Dash />
  const label = titleCase(status)
  return (
    <Badge tone={DOC_TONES[status] ?? 'neutral'} title={label}>
      {label}
    </Badge>
  )
}

export function CheckBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Dash />
  const label = titleCase(status)
  return (
    <Badge tone={CHECK_TONES[status] ?? 'neutral'} title={label}>
      {label}
    </Badge>
  )
}

/** Extracted-value acceptance state. */
export function ValueStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Dash />
  const label = titleCase(status)
  const tone: Tone =
    status === 'ACCEPTED' || status === 'OK'
      ? 'success'
      : status === 'REJECTED' || status === 'IMPLAUSIBLE'
        ? 'danger'
        : 'warning'
  return (
    <Badge tone={tone} title={label}>
      {label}
    </Badge>
  )
}

/** The 0.80 boundary is `config.confidence.review_threshold` - the same value
 *  the pipeline uses to flag a value REVIEW_REQUIRED. */
export function Confidence({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <Dash />
  const v = Math.max(0, Math.min(1, value))
  const level = v >= 0.95 ? 'High' : v >= 0.8 ? 'Medium' : 'Low'
  const tone: Tone = v >= 0.95 ? 'success' : v >= 0.8 ? 'info' : 'warning'
  const text = level === 'High' ? 'text-success' : level === 'Medium' ? 'text-info' : 'text-warning'
  return (
    <span
      className="inline-flex items-center gap-2"
      // The bar is decorative; the percentage and the band carry the meaning.
      title={`${(v * 100).toFixed(1)}% confidence (${level})`}
    >
      <span
        className="h-1.5 w-10 shrink-0 overflow-hidden rounded-full bg-muted sm:w-12"
        aria-hidden
      >
        <span
          className={`block h-full rounded-full ${
            tone === 'success' ? 'bg-success' : tone === 'info' ? 'bg-info' : 'bg-warning'
          }`}
          style={{ width: `${v * 100}%` }}
        />
      </span>
      <span className="tnum text-xs whitespace-nowrap text-muted-foreground">
        <span className={text}>{(v * 100).toFixed(0)}%</span>{' '}
        <span className="text-muted-foreground/70">{level}</span>
      </span>
    </span>
  )
}