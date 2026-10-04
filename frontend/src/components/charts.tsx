import type { ReactNode } from 'react'

/* Hand-rolled SVG rather than a charting dependency: these are three fixed
 * shapes, and owning the markup keeps the palette consistent with the badges
 * and avoids a large dependency that has to agree with Tailwind's version.
 * Colour tokens live in src/lib/palette.ts so this module exports components
 * only (React Fast Refresh).
 *
 * Two rules every chart here obeys:
 *   1. Height is controlled - a fixed, modest maximum, never derived from the
 *      data. Fifty categories must not make the page two thousand pixels tall.
 *   2. Nothing can exceed its container: wrappers are min-w-0 and width-full,
 *      and the only scrolling happens inside the chart, never on the page. */

export interface Slice {
  label: string
  value: number
  color: string
}

/* ------------------------------------------------------------------ donut */

/** Donut with a centred total and a legend. */
export function Donut({
  slices,
  centerLabel,
  centerValue,
  size = 200,
}: {
  slices: Slice[]
  centerLabel: string
  centerValue: string
  /** Max width in px. The ring shrinks below this on narrow screens rather
   *  than overflowing, because the box is `w-full` with a max-width. */
  size?: number
}) {
  const total = slices.reduce((a, s) => a + s.value, 0)

  // An all-zero dataset renders an empty ring with "0" in the middle, which
  // reads as broken. Say so explicitly instead.
  if (total === 0) {
    return (
      <div className="flex min-h-[10rem] items-center justify-center py-4 text-sm text-muted-foreground">
        Belum ada data
      </div>
    )
  }

  const radius = 100 / 2 - 12
  const circumference = 2 * Math.PI * radius

  // Each arc's dash offset is the cumulative length of the slices before it, so
  // the segments join into one continuous ring.
  const arcs = slices.reduce<(Slice & { dash: number; offset: number; fraction: number })[]>(
    (acc, s) => {
      const fraction = s.value / total
      const startFraction = acc.reduce((a, prev) => a + prev.fraction, 0)
      acc.push({
        ...s,
        fraction,
        dash: fraction * circumference,
        offset: -startFraction * circumference,
      })
      return acc
    },
    [],
  )

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-4 sm:justify-start">
      {/* relative is required by the centred total overlay. The ring scales
          down on narrow screens because the box is w-full with a max-width. */}
      <div className="relative aspect-square w-full shrink-0" style={{ maxWidth: size }}>
        <svg
          viewBox="0 0 200 200"
          className="h-full w-full -rotate-90"
          role="img"
          aria-label={`${centerLabel}: ${centerValue}`}
        >
          <circle
            cx={100}
            cy={100}
            r={radius}
            fill="none"
            stroke="var(--chart-track)"
            strokeWidth={16}
          />
          {arcs.map((a) => (
            <circle
              key={a.label}
              cx={100}
              cy={100}
              r={radius}
              fill="none"
              stroke={a.color}
              strokeWidth={16}
              strokeDasharray={`${a.dash} ${circumference - a.dash}`}
              strokeDashoffset={a.offset}
            >
              <title>{`${a.label}: ${a.value.toLocaleString('id-ID')}`}</title>
            </circle>
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="tnum px-4 text-center text-xl font-semibold break-words text-foreground">
            {centerValue}
          </span>
          <span className="px-4 text-center text-[11px] tracking-wide text-muted-foreground uppercase">
            {centerLabel}
          </span>
        </div>
      </div>
      <Legend slices={arcs} />
    </div>
  )
}

function Legend({ slices }: { slices: (Slice & { fraction: number })[] }) {
  return (
    // min-w-0 + flex-1 lets the legend take the remaining width and wrap
    // instead of forcing the row wider than the card.
    <ul className="min-w-0 flex-1 space-y-1.5 sm:min-w-44">
      {slices.map((s) => (
        <li key={s.label} className="flex items-center gap-2 text-sm">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ background: s.color }}
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate text-muted-foreground" title={s.label}>
            {s.label}
          </span>
          <span className="tnum shrink-0 font-medium text-foreground">
            {s.value.toLocaleString('id-ID')}
          </span>
          <span className="tnum w-10 shrink-0 text-right text-xs text-muted-foreground">
            {(s.fraction * 100).toFixed(0)}%
          </span>
        </li>
      ))}
    </ul>
  )
}

/* --------------------------------------------------------------- bar list */

/** Horizontal ranked bars. Reads better than a vertical chart when the labels
 *  are company or check names. */
export function BarList({
  items,
  emptyLabel = 'Tidak ada yang ditampilkan',
  formatValue = (n: number) => n.toLocaleString('id-ID'),
  color = 'var(--chart-2)',
}: {
  items: { label: string; value: number; hint?: string }[]
  emptyLabel?: string
  formatValue?: (n: number) => string
  color?: string
}) {
  if (items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">{emptyLabel}</p>
    )
  }
  const max = Math.max(...items.map((i) => i.value), 1)

  // A ranked list of 50 companies should not become a 2000px column. Past a
  // dozen rows the list scrolls inside itself rather than growing the page.
  const scrollable = items.length > 12
  const list = (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-muted-foreground" title={item.label}>
              {item.label}
            </span>
            <span className="tnum shrink-0 font-medium text-foreground">
              {formatValue(item.value)}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max((item.value / max) * 100, item.value > 0 ? 2 : 0)}%`, background: color }}
            />
          </div>
          {item.hint && <p className="mt-0.5 text-xs break-words text-muted-foreground">{item.hint}</p>}
        </li>
      ))}
    </ul>
  )

  return scrollable ? (
    <div className="scroll-thin max-h-96 overflow-y-auto pr-1">{list}</div>
  ) : (
    list
  )
}

/* -------------------------------------------------------------- histogram */

/** Vertical histogram over ordered buckets (confidence distribution).
 *  Buckets scroll horizontally rather than compressing into unreadable slivers. */
export function Histogram({
  buckets,
  color = 'var(--chart-2)',
}: {
  buckets: { label: string; value: number; hint?: ReactNode }[]
  color?: string
}) {
  const max = Math.max(...buckets.map((b) => b.value), 1)

  return (
    <div className="min-w-0">
      <div className="scroll-thin overflow-x-auto">
        {/* Fixed modest heights at each breakpoint. Never a data-derived
            height, so the page cannot jump as values change. */}
        <div className="flex h-32 items-end gap-2 sm:h-36">
          {buckets.map((b) => (
            <div
              key={b.label}
              className="flex min-w-10 flex-1 flex-col items-center justify-end gap-1"
              title={`${b.label}: ${b.value}`}
            >
              <span className="tnum text-xs font-medium text-muted-foreground">{b.value}</span>
              {/* Percentage of a fixed-height parent, so the bar scales with
                  the viewport rather than growing without bound. */}
              <div
                className="w-full rounded-t-sm"
                style={{
                  height: `${Math.max((b.value / max) * 100, b.value > 0 ? 4 : 0)}%`,
                  background: color,
                }}
              />
            </div>
          ))}
        </div>
      </div>
      <div className="scroll-thin mt-1.5 overflow-x-auto border-t border-border pt-1.5">
        <div className="flex gap-2">
          {buckets.map((b) => (
            <span
              key={b.label}
              className="min-w-10 flex-1 text-center text-[11px] break-words text-muted-foreground"
            >
              {b.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ stacked bar */

/** Stacked proportion bar - compact status mix for table headers. */
export function StackedBar({ slices }: { slices: Slice[] }) {
  const total = slices.reduce((a, s) => a + s.value, 0)
  if (total === 0) return <div className="h-2 w-full rounded-full bg-muted" />
  return (
    <div
      className="flex h-2 w-full overflow-hidden rounded-full bg-muted"
      role="img"
      aria-label={slices.map((s) => `${s.label}: ${s.value}`).join(', ')}
    >
      {slices.map((s) => (
        <div
          key={s.label}
          style={{ width: `${(s.value / total) * 100}%`, background: s.color }}
          title={`${s.label}: ${s.value}`}
        />
      ))}
    </div>
  )
}