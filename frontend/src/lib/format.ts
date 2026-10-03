const idDecimal = new Intl.NumberFormat('id-ID', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Formats a number with every digit it actually has.
 *
 * `Intl.NumberFormat` caps `maximumFractionDigits` (3 by default, 20 allowed),
 * so a formatter that does not raise it will quietly round: 1,286,605,455.8
 * comes back as 1,286,605,456. Every figure here is a scanned number, and a
 * rounded one is a wrong one -- the fractional part is part of what was
 * reported. 20 is the maximum the formatter honours and is far more precision
 * than any financial statement carries. */
const exactNumber = new Intl.NumberFormat('id-ID', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 20,
})

/** Indonesian convention: `.` groups thousands, `,` is the decimal mark. */
export function num(value: number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  return exactNumber.format(value)
}

export function dec(value: number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  return idDecimal.format(value)
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

/** A money figure, exactly as scanned.
 *
 * Deliberately not abbreviated to "28,79 T": scaling divides by 1e12 and then
 * formats to two decimals, which discards most of the digits of the number the
 * source actually reported. An accountant reading a results table needs the
 * figure they can tie back to the statement, so the full value is shown and
 * grouped for legibility. Nothing is scaled and nothing is rounded. */
export function rupiah(value: number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  return exactNumber.format(value)
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}m ${Math.round(seconds % 60)}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.round((Date.now() - then) / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

/** `total_liabilities_and_equity` -> `Total liabilities and equity` */
export function humanize(snake: string | null | undefined): string {
  if (!snake) return '—'
  const words = snake.replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function titleCase(snake: string): string {
  return snake
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** The currency codes the extractor recognises, written out so a reader does
 *  not have to know that IDR means rupiah. */
const CURRENCY_LABELS: Record<string, string> = {
  IDR: 'IDR — Rupiah',
  USD: 'USD — US Dollar ($)',
  EUR: 'EUR — Euro',
  SGD: 'SGD — Singapore Dollar',
}

/** `none` is the bucket for figures where no currency was detected in the
 *  source. It is deliberately not folded into IDR: "we could not tell" and "it
 *  is rupiah" are different answers and a filter must not conflate them. */
export function currencyLabel(code: string | null | undefined, fallback = '—'): string {
  if (!code) return fallback
  if (code === 'none') return 'Not detected'
  return CURRENCY_LABELS[code] ?? code
}

/** Options for a currency filter, built from the server's counts so the reader
 *  can see that a currency exists but holds no values before selecting it. */
export function currencyOptions(
  currencies: { currency: string; count: number }[] | undefined,
): { value: string; label: string }[] {
  return [
    { value: '', label: 'All currencies' },
    ...(currencies ?? []).map((c) => ({
      value: c.currency,
      label: `${currencyLabel(c.currency)} (${c.count})`,
    })),
  ]
}