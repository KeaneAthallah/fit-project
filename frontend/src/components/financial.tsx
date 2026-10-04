import { Link } from 'react-router-dom'
import {
  compactRupiah,
  deltaShort,
  deltaText,
  rupiah,
  type Delta,
  type DeltaTone,
} from '../lib/format'
import { INDICATOR_META, fieldLabel } from '../lib/field-labels'
import { OVERVIEW_FIELDS, pointAt } from '../lib/metrics'
import { common, company as companyStrings } from '../lib/strings'
import type { CompanyProfile, SummaryMetricPoint } from '../lib/types'
import { ValueStatusBadge } from './badges'
import { Badge, EmptyState, Table, Td, Th } from './ui'

/** The most recent year before `year`, whatever it reported -- a
 *  null value included, because "last year had no figure" is the
 *  honest reason for showing no change rather than hiding the gap. */
function pointBefore(
  series: SummaryMetricPoint[] | undefined,
  year: number,
): SummaryMetricPoint | undefined {
  if (!series) return undefined
  let best: SummaryMetricPoint | undefined
  for (const p of series) {
    if (p.year < year && (!best || p.year > best.year)) best = p
  }
  return best
}

/** Accounting convention: a negative figure in parentheses, the way
 *  the statements print a loss. */
function statementRupiah(value: number): string {
  return value < 0 ? `(${rupiah(-value)})` : rupiah(value)
}

/** Sizing a chart needs a scale, and these values span rupiah
 *  magnitudes, so a plain linear axis would flatten every bar but
 *  the largest one. Indonesian abbreviations: Jt / M / T. */
function compactAxis(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e12) return `${(value / 1e12).toFixed(abs >= 1e13 ? 0 : 1)}T`
  if (abs >= 1e9) return `${(value / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}M`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}Jt`
  return value.toFixed(0)
}

const SERIES_FILL = ['fill-primary/80', 'fill-accent', 'fill-muted-foreground/50']
const SERIES_DOT = ['bg-primary/80', 'bg-accent', 'bg-muted-foreground/50']

/* ------------------------------------------------------------------ KPI */

function DeltaChip({ delta }: { delta: Delta }) {
  const arrow =
    delta.tone === 'up' ? '↑' : delta.tone === 'down' ? '↓' : '→'
  const toneClass =
    delta.tone === 'up'
      ? 'text-success-soft-foreground'
      : delta.tone === 'down'
        ? 'text-danger-soft-foreground'
        : 'text-muted-foreground'
  return (
    <span
      className={`inline-flex items-center gap-1 text-[0.7rem] font-medium ${toneClass}`}
      title={delta.text}
    >
      <span aria-hidden>{arrow}</span>
      <span>{delta.text}</span>
    </span>
  )
}

/** One headline indicator: compact value at a glance, the exact
 *  figure one hover away, the change against the previous reporting
 *  year, and where the number came from. */
export function KpiCard({
  field,
  profile,
  year,
}: {
  field: string
  profile: CompanyProfile
  year: number
}) {
  const apiLabel = profile.labels[field]
  const short = INDICATOR_META[field]?.short ?? fieldLabel(field, apiLabel)
  const full = INDICATOR_META[field]?.full ?? fieldLabel(field, apiLabel)
  const series = profile.metrics[field]
  const point = pointAt(series, year)
  const previous = pointBefore(series, year)
  const value = point?.normalized_value
  const delta = deltaText(value, previous?.normalized_value)

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <span
          className="min-w-0 truncate text-xs text-muted-foreground"
          title={full}
        >
          {short}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {point?.disputed && (
            <Badge
              tone="danger"
              title="Sumber tidak sepakat tentang angka ini. Buka grid Hasil untuk memilih."
            >
              dipersengketakan
            </Badge>
          )}
          {point?.status && point.status !== 'OK' && !point.disputed && (
            <ValueStatusBadge status={point.status} />
          )}
        </span>
      </div>
      <div
        className="tnum mt-1 font-mono text-xl font-semibold leading-tight"
        title={
          value === null || value === undefined
            ? common.noDataHint
            : `${common.exactValue}: ${statementRupiah(value)}`
        }
      >
        {value === null || value === undefined ? (
          <span className="text-muted-foreground/50">&mdash;</span>
        ) : (
          compactRupiah(value)
        )}
      </div>
      <div className="mt-1 flex min-h-[1.25rem] flex-wrap items-center gap-x-2 gap-y-1">
        {delta && <DeltaChip delta={delta} />}
        {point?.currency && (
          <span className="text-[0.65rem] text-muted-foreground">
            {point.currency}
          </span>
        )}
        <span className="text-[0.65rem] text-muted-foreground">{year}</span>
      </div>
      <div className="mt-1.5 border-t border-border pt-1.5">
        <SourceLine profile={profile} point={point} />
      </div>
    </div>
  )
}

/* ------------------------------------------------------- source tracing */

/** Where a figure was read from: the report and the statement page.
 *  Rendered only when the reading actually carries a document, so
 *  a hand-entered correction with no source says nothing rather
 *  than pointing nowhere. */
export function SourceLine({
  profile,
  point,
}: {
  profile: CompanyProfile
  point: SummaryMetricPoint | undefined
}) {
  if (!point?.document_id) return null
  const doc = profile.documents.find((d) => d.id === point.document_id)
  const page = point.page ?? point.candidates?.[0]?.page ?? null
  return (
    <Link
      to={`/documents/${point.document_id}`}
      className="inline-flex max-w-full items-baseline gap-1 text-xs font-medium text-primary hover:underline"
      title={companyStrings.kpis.sourceHint}
    >
      <span className="shrink-0 text-muted-foreground">
        {common.source}:
      </span>
      <span className="min-w-0 truncate">
        {companyStrings.kpis.sourceLine(doc?.filename ?? `#${point.document_id}`, page)}
      </span>
    </Link>
  )
}

/* ------------------------------------------------------ equity composition */

/** Ekuitas pemilik entitas induk + kepentingan non pengendali =
 *  jumlah ekuitas, as one connected figure rather than three
 *  unrelated cards, with a proportion bar so the split is visible
 *  without reading the numbers.
 *
 *  A half the company did not report is a gap, not a quiet rescale
 *  to 100%: the bar only ever shows what was actually declared. */
export function EquityComposition({
  profile,
  year,
}: {
  profile: CompanyProfile
  year: number
}) {
  const parent = pointAt(
    profile.metrics.equity_attributable_to_owners_of_parent,
    year,
  )?.normalized_value ?? null
  const nci = pointAt(profile.metrics.non_controlling_interest, year)
    ?.normalized_value ?? null
  const total = pointAt(profile.metrics.total_equity, year)
    ?.normalized_value ?? null

  if (parent === null && nci === null && total === null) return null

  const parts = [
    {
      field: 'equity_attributable_to_owners_of_parent',
      value: parent,
      fill: SERIES_FILL[0],
      dot: SERIES_DOT[0],
    },
    ...(nci === null
      ? []
      : [
          {
            field: 'non_controlling_interest',
            value: nci,
            fill: SERIES_FILL[1],
            dot: SERIES_DOT[1],
          },
        ]),
  ]
  // Shares of the total the statements print; a missing total is
  // shown as a gap rather than invented from the parts.
  const basis = total ?? parent ?? nci

  return (
    <div className="space-y-2.5">
      {parts.map((p) => {
        const meta = INDICATOR_META[p.field]
        return (
          <div
            key={p.field}
            className="flex items-baseline justify-between gap-3"
          >
            <span className="flex min-w-0 items-center gap-2 text-sm">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-sm ${p.dot}`}
                aria-hidden
              />
              <span
                className="min-w-0 truncate text-muted-foreground"
                title={meta?.full}
              >
                {meta?.short ?? p.field}
              </span>
            </span>
            <span
              className="tnum shrink-0 font-mono text-sm font-medium"
              title={
                p.value === null
                  ? common.noDataHint
                  : `${common.exactValue}: ${statementRupiah(p.value)}`
              }
            >
              {p.value === null ? (
                <span className="text-muted-foreground/50">&mdash;</span>
              ) : (
                statementRupiah(p.value)
              )}
            </span>
          </div>
        )
      })}

      {basis !== null && basis > 0 && (
        <div
          className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={parts
            .filter((p) => p.value !== null)
            .map((p) => `${INDICATOR_META[p.field]?.short}: ${statementRupiah(p.value!)}`)
            .join(', ')}
        >
          {parts.map(
            (p) =>
              p.value !== null &&
              p.value > 0 && (
                <div
                  key={p.field}
                  className={p.fill}
                  style={{ width: `${Math.min(100, (p.value / basis) * 100)}%` }}
                  title={`${INDICATOR_META[p.field]?.short}: ${statementRupiah(p.value)}`}
                />
              ),
          )}
        </div>
      )}

      <div className="flex items-baseline justify-between gap-3 border-t border-border pt-2.5">
        <span
          className="text-sm font-medium"
          title={INDICATOR_META.total_equity.full}
        >
          {INDICATOR_META.total_equity.short}
        </span>
        <span
          className="tnum font-mono text-base font-semibold"
          title={
            total === null
              ? common.noDataHint
              : `${common.exactValue}: ${statementRupiah(total)}`
          }
        >
          {total === null ? (
            <span className="text-muted-foreground/50">&mdash;</span>
          ) : (
            statementRupiah(total)
          )}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- trend chart */

/** Side-by-side bars, one group per year, with a zero baseline.
 *
 *  Drawn as plain SVG rather than pulled in as a chart dependency:
 *  it is a few dozen rectangles, and every colour comes from the
 *  theme tokens so it stays legible in dark mode without a second
 *  set of styles to maintain.
 *
 *  A loss is drawn BELOW the zero line, the way the statement
 *  reads it. Scaling every bar by its absolute value -- the
 *  obvious shortcut -- would draw a loss year as a tall upward
 *  bar and claim the year was good. */
export function TrendChart({
  profile,
  fields,
  ariaLabel,
}: {
  profile: CompanyProfile
  fields: string[]
  ariaLabel: string
}) {
  const series = fields
    .map((f) => ({ field: f, points: profile.metrics[f] }))
    .filter(
      (s) => s.points && s.points.some((p) => p.normalized_value !== null),
    )
  if (series.length === 0) return null

  const values = series.flatMap((s) =>
    s.points
      .map((p) => p.normalized_value)
      .filter((v): v is number => v !== null),
  )
  let lo = Math.min(0, ...values)
  let hi = Math.max(0, ...values)
  // An all-zero dataset still needs a drawable axis.
  if (hi === lo) hi = lo + 1

  const W = 640
  const H = 210
  const padL = 54
  const padB = 26
  const padT = 10
  const plotW = W - padL - 12
  const plotH = H - padT - padB
  const years = profile.years
  const groupW = plotW / Math.max(years.length, 1)
  const barW = Math.min(26, (groupW - 8) / series.length)
  const y = (v: number) => padT + plotH * (1 - (v - lo) / (hi - lo))

  // Gridlines on the axis extremes and zero, so the chart can be
  // read without arithmetic.
  const ticks = Array.from(new Set([lo, 0, hi]))

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full min-w-[520px]"
        role="img"
        aria-label={ariaLabel}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padL}
              x2={W - 12}
              y1={y(t)}
              y2={y(t)}
              className="stroke-border"
              strokeWidth={1}
              strokeDasharray={t === 0 ? undefined : '3 3'}
            />
            <text
              x={padL - 6}
              y={y(t) + 3}
              textAnchor="end"
              className="fill-muted-foreground text-[9px]"
            >
              {compactAxis(t)}
            </text>
          </g>
        ))}

        {years.map((year, yi) => (
          <g key={year}>
            <text
              x={padL + yi * groupW + groupW / 2}
              y={H - 8}
              textAnchor="middle"
              className="fill-muted-foreground text-[10px]"
            >
              {year}
            </text>
            {series.map((s, si) => {
              const p = pointAt(s.points, year)
              const value = p?.normalized_value
              if (value === null || value === undefined) return null
              // The bar grows away from zero: upward for a figure,
              // downward for a loss.
              const top = y(Math.max(value, 0))
              const bottom = y(Math.min(value, 0))
              const x =
                padL + yi * groupW + (groupW - barW * series.length) / 2 + si * barW
              return (
                <rect
                  key={s.field}
                  x={x}
                  y={top}
                  width={barW - 2}
                  height={Math.max(1, bottom - top)}
                  rx={1.5}
                  className={SERIES_FILL[si]}
                >
                  <title>{`${fieldLabel(s.field, profile.labels[s.field])} ${year}: ${rupiah(value)}`}</title>
                </rect>
              )
            })}
          </g>
        ))}
      </svg>

      <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
        {series.map((s, i) => (
          <span key={s.field} className="inline-flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-sm ${SERIES_DOT[i]}`} />
            {fieldLabel(s.field, profile.labels[s.field])}
          </span>
        ))}
        <span className="ml-auto">{companyStrings.kpis.valuesAsReported}</span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ tax activity */

/** Pajak penghasilan dari aktivitas operasi. The sign is the
 *  meaning: cash out (a payment, negative) and cash in (a refund,
 *  positive) are different events, so the label follows the sign
 *  rather than the reader guessing what a minus sign means. */
export function TaxActivityCard({
  profile,
  year,
}: {
  profile: CompanyProfile
  year: number
}) {
  const meta = INDICATOR_META.income_tax_paid_operating
  const point = pointAt(profile.metrics.income_tax_paid_operating, year)
  const value = point?.normalized_value

  if (value === null || value === undefined) {
    return <EmptyState title={common.dataNotAvailable} hint={companyStrings.kpis.taxNone} />
  }
  const paid = value < 0

  return (
    <div className="space-y-1.5">
      <span
        className="block text-xs text-muted-foreground"
        title={meta.full}
      >
        {meta.short}
      </span>
      <div
        className="tnum font-mono text-2xl font-semibold"
        title={`${common.exactValue}: ${statementRupiah(value)}`}
      >
        {compactRupiah(value)}
      </div>
      <span
        className={`inline-flex items-center gap-1.5 text-xs font-medium ${
          paid ? 'text-warning-soft-foreground' : 'text-success-soft-foreground'
        }`}
      >
        <span
          className={`h-2 w-2 rounded-full ${
            paid ? 'bg-warning' : 'bg-success'
          }`}
          aria-hidden
        />
        {paid ? companyStrings.kpis.taxPaid : companyStrings.kpis.taxRefund}
      </span>
      <div>
        <SourceLine profile={profile} point={point} />
      </div>
    </div>
  )
}

/* ------------------------------------------------------- Ikhtisar Keuangan */

/** The nine indicators against every reporting year, plus the change
 *  on the latest year -- the transpose of the results grid for one
 *  company.
 *
 *  A field no report of this company contained at all is dropped
 *  rather than shown as a row of em dashes, matching the grid's
 *  own rule. Figures the company did report keep their exact
 *  digits: this is the detail view the compact cards summarise. */
export function IkhtisarTable({ profile }: { profile: CompanyProfile }) {
  const years = profile.years
  const rows = OVERVIEW_FIELDS.filter((f) =>
    profile.metrics[f]?.some((p) => p.normalized_value !== null),
  )
  if (rows.length === 0 || years.length === 0) return null

  const latest = years[years.length - 1]
  const deltaTone: Record<DeltaTone, string> = {
    up: 'text-success-soft-foreground',
    down: 'text-danger-soft-foreground',
    flat: 'text-muted-foreground',
    state: 'text-muted-foreground',
  }

  return (
    <Table caption={companyStrings.kpis.overview} stickyHeader>
      <thead>
        <tr>
          <Th className="sticky left-0 z-10 bg-card">Indikator</Th>
          {years.map((y) => (
            <Th key={y} align="right" className="tnum">
              {y}
            </Th>
          ))}
          <Th align="right">{common.change}</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((field) => {
          const series = profile.metrics[field]
          const apiLabel = profile.labels[field]
          const short = INDICATOR_META[field]?.short ?? fieldLabel(field, apiLabel)
          const full = INDICATOR_META[field]?.full ?? fieldLabel(field, apiLabel)
          const latestPoint = pointAt(series, latest)
          const previous = pointBefore(series, latest)
          const delta = deltaShort(
            latestPoint?.normalized_value,
            previous?.normalized_value,
          )
          return (
            <tr key={field}>
              <Td
                className="sticky left-0 z-10 max-w-56 bg-card"
                title={full}
              >
                <span className="block truncate font-medium">{short}</span>
              </Td>
              {years.map((y) => {
                const value = pointAt(series, y)?.normalized_value
                return (
                  <Td
                    key={y}
                    align="right"
                    mono
                    className="tnum"
                    title={
                      value === null || value === undefined
                        ? common.noDataHint
                        : statementRupiah(value)
                    }
                  >
                    {value === null || value === undefined ? (
                      <span className="text-muted-foreground/50">&mdash;</span>
                    ) : (
                      statementRupiah(value)
                    )}
                  </Td>
                )
              })}
              <Td
                align="right"
                className={`tnum ${delta ? deltaTone[delta.tone] : ''}`}
                title={delta?.text}
              >
                {delta ? delta.text : <span className="text-muted-foreground/50">&mdash;</span>}
              </Td>
            </tr>
          )
        })}
      </tbody>
    </Table>
  )
}
