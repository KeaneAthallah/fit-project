import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useLiveRefresh, useQuery } from '../hooks/useQuery'
import { useProcessing } from '../lib/processing-context'
import { rupiah, titleCase } from '../lib/format'
import type { CompanyProfile, SummaryMetricPoint } from '../lib/types'
import { ValueStatusBadge } from '../components/badges'
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  Loading,
  PageHeader,
  Table,
  Td,
  Th,
} from '../components/ui'

/**
 * One company, seen whole.
 *
 * The results grid answers "how do these companies compare"; this answers "what
 * do we actually hold for this one". Those are different questions and forcing
 * both out of the same table is what makes a wide grid hard to read, so the
 * figures here are deliberately few and large, with everything else one click
 * away on the grid.
 */

/** Sizing a chart needs a scale, and these values span rupiah magnitudes, so a
 *  plain linear axis would flatten every bar but the largest one. */
function compactAxis(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e12) return `${(value / 1e12).toFixed(abs >= 1e13 ? 0 : 1)}T`
  if (abs >= 1e9) return `${(value / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`
  return value.toFixed(0)
}

function pointAt(series: SummaryMetricPoint[], year: number) {
  return series.find((p) => p.year === year)
}

/**
 * Side-by-side bars, one group per year.
 *
 * Drawn as plain SVG rather than pulled in as a chart dependency: it is a dozen
 * rectangles, and every colour comes from the theme tokens so it stays legible
 * in dark mode without a second set of styles to maintain.
 */
function TrendChart({
  profile,
  fields,
}: {
  profile: CompanyProfile
  fields: string[]
}) {
  const series = fields
    .map((f) => ({ field: f, points: profile.metrics[f] }))
    .filter((s) => s.points && s.points.length > 0)
  if (series.length === 0) return null

  const values = series.flatMap((s) =>
    s.points.map((p) => p.normalized_value ?? 0),
  )
  const peak = Math.max(...values.map(Math.abs), 1)

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

  // Gridlines on round numbers, so the axis can be read without arithmetic.
  const ticks = [0, 0.5, 1].map((f) => f * peak)

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full min-w-[520px]"
        role="img"
        aria-label={`${series.map((s) => profile.labels[s.field]).join(', ')} by year`}
      >
        {ticks.map((t) => {
          const y = padT + plotH - (t / peak) * plotH
          return (
            <g key={t}>
              <line
                x1={padL}
                x2={W - 12}
                y1={y}
                y2={y}
                className="stroke-border"
                strokeWidth={1}
                strokeDasharray={t === 0 ? undefined : '3 3'}
              />
              <text
                x={padL - 6}
                y={y + 3}
                textAnchor="end"
                className="fill-muted-foreground text-[9px]"
              >
                {compactAxis(t)}
              </text>
            </g>
          )
        })}

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
              const h = Math.max(1, (Math.abs(value) / peak) * plotH)
              const x =
                padL + yi * groupW + (groupW - barW * series.length) / 2 + si * barW
              return (
                <rect
                  key={s.field}
                  x={x}
                  y={padT + plotH - h}
                  width={barW - 2}
                  height={h}
                  rx={1.5}
                  className={
                    si === 0
                      ? 'fill-primary/80'
                      : si === 1
                        ? 'fill-accent'
                        : 'fill-muted-foreground/50'
                  }
                >
                  <title>
                    {`${profile.labels[s.field]} ${year}: ${rupiah(value)}`}
                  </title>
                </rect>
              )
            })}
          </g>
        ))}
      </svg>

      <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
        {series.map((s, i) => (
          <span key={s.field} className="inline-flex items-center gap-1.5">
            <span
              className={
                i === 0
                  ? 'h-2.5 w-2.5 rounded-sm bg-primary/80'
                  : i === 1
                    ? 'h-2.5 w-2.5 rounded-sm bg-accent'
                    : 'h-2.5 w-2.5 rounded-sm bg-muted-foreground/50'
              }
            />
            {profile.labels[s.field]}
          </span>
        ))}
        <span className="ml-auto">Values in rupiah, as reported.</span>
      </div>
    </div>
  )
}

/** One big number, the way a reader scans a summary rather than a table. */
function StatTile({
  label,
  point,
  currency,
}: {
  label: string
  point: SummaryMetricPoint | undefined
  currency?: string | null
}) {
  const value = point?.normalized_value
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="truncate text-xs text-muted-foreground" title={label}>
        {label}
      </div>
      <div className="tnum mt-0.5 font-mono text-lg font-semibold leading-tight">
        {value === null || value === undefined ? (
          <span className="text-muted-foreground/50">&mdash;</span>
        ) : (
          rupiah(value)
        )}
      </div>
      <div className="mt-1 flex min-h-[1.25rem] items-center gap-1">
        {point?.disputed && (
          <Badge
            tone="danger"
            title="Sources disagree on this figure. Open the results grid to choose."
          >
            disputed
          </Badge>
        )}
        {point?.status && point.status !== 'OK' && !point.disputed && (
          <ValueStatusBadge status={point.status} />
        )}
        {currency && (
          <span className="text-[0.65rem] text-muted-foreground">{currency}</span>
        )}
      </div>
    </div>
  )
}

/**
 * Assets against liabilities and equity, as one bar per year.
 *
 * The point is not precision: it is that when the two halves do not meet, the
 * gap is visible without reading a number, which is the same thing the
 * accounting validation reports in words.
 */
function BalanceSheetBars({ profile }: { profile: CompanyProfile }) {
  const assets = profile.metrics.total_assets
  const liabs = profile.metrics.total_liabilities
  const equity = profile.metrics.total_equity
  if (!assets) return null

  return (
    <ul className="space-y-2">
      {profile.years.map((year) => {
        const a = pointAt(assets, year)?.normalized_value ?? null
        const l = pointAt(liabs, year)?.normalized_value ?? null
        const e = pointAt(equity, year)?.normalized_value ?? null
        if (a === null || a === 0) return null
        // Shares of total assets; a missing half is shown as a gap rather than
        // quietly rescaled to 100%.
        const lShare = l === null ? null : Math.min(100, Math.max(0, (l / a) * 100))
        const eShare = e === null ? null : Math.min(100, Math.max(0, (e / a) * 100))
        const balanced = l !== null && e !== null && Math.abs(l + e - a) / a < 0.01
        return (
          <li key={year} className="text-xs">
            <div className="mb-0.5 flex items-baseline justify-between gap-2">
              <span className="font-medium">{year}</span>
              <span className="tnum font-mono text-muted-foreground">
                {rupiah(a)}
                {balanced ? (
                  <span className="ml-2 text-[0.65rem] text-success-soft-foreground">
                    balances
                  </span>
                ) : (
                  <span className="ml-2 text-[0.65rem] text-warning-soft-foreground">
                    does not balance
                  </span>
                )}
              </span>
            </div>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
              {lShare !== null && (
                <div
                  className="bg-accent"
                  style={{ width: `${lShare}%` }}
                  title={`Liabilities ${rupiah(l)}`}
                />
              )}
              {eShare !== null && (
                <div
                  className="bg-primary/80"
                  style={{ width: `${eShare}%` }}
                  title={`Equity ${rupiah(e)}`}
                />
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export default function CompanyDetail() {
  const { company = '' } = useParams<{ company: string }>()
  const name = decodeURIComponent(company)

  const query = useQuery(() => api.companyProfile(name), [name])
  // A batch can add figures for this company while the page is open, which is
  // the same reason the results grid stays live.
  const { state } = useProcessing()
  const refresh = query.refetch
  useLiveRefresh(refresh, state?.running ?? false)

  const profile = query.data
  const latest = profile?.years.length
    ? profile.years[profile.years.length - 1]
    : undefined

  const tiles = useMemo(() => {
    if (!profile || latest === undefined) return []
    return [
      { field: 'total_assets' },
      { field: 'total_liabilities' },
      { field: 'total_equity' },
      { field: 'equity_attributable_to_owners_of_parent' },
      { field: 'sales_and_revenue' },
      { field: 'net_income' },
    ].map(({ field }) => ({
      label: profile.labels[field] ?? titleCase(field),
      point: pointAt(profile.metrics[field] ?? [], latest),
    }))
  }, [profile, latest])

  if (query.initialLoading) return <Loading label="Loading company." />
  if (query.error) {
    return (
      <>
        <PageHeader title={name} />
        <ErrorBanner message={query.error} onRetry={query.refetch} />
      </>
    )
  }
  if (!profile) return <EmptyState title="No company loaded." />

  const { totals, quality } = profile
  const q = quality

  return (
    <>
      <PageHeader
        title={profile.company}
        subtitle={
          totals.years > 0
            ? `${totals.years} reporting year${totals.years === 1 ? '' : 's'}, latest ${latest}`
            : 'No reporting year could be read'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/results?company=${encodeURIComponent(profile.company)}`}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
            >
              All figures
            </Link>
            <Link
              to={`/documents?company=${encodeURIComponent(profile.company)}`}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
            >
              Documents
            </Link>
          </div>
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card title="Coverage">
          <dl className="space-y-1 text-sm">
            {[
              ['Filings held', `${totals.documents}`],
              [
                'Produced figures',
                `${totals.documents_with_values} of ${totals.documents}`,
              ],
              ['Figures extracted', `${totals.figures}`],
              ['Distinct fields', `${totals.fields}`],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="tnum font-mono font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          {totals.documents_with_values < totals.documents && (
            <p className="mt-2 text-xs text-warning-soft-foreground">
              {totals.documents - totals.documents_with_values} filing(s) produced
              nothing yet.
            </p>
          )}
        </Card>

        <Card title="Latest year" className="sm:col-span-1">
          <div className="tnum font-mono text-2xl font-semibold">{latest ?? '-'}</div>
          <p className="mt-1 text-xs text-muted-foreground">
            {profile.currencies.length > 0
              ? `Reported in ${profile.currencies.join(', ')}`
              : 'No currency detected in the source'}
          </p>
        </Card>

        <Card title="Disputed figures" className="sm:col-span-1">
          <div
            className={`tnum font-mono text-2xl font-semibold ${
              q.disputed_cells > 0 ? 'text-danger-soft-foreground' : ''
            }`}
          >
            {q.disputed_cells}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            of {q.figures} headline figures, where sources disagree by more than half
          </p>
        </Card>

        <Card title="Accounting checks" className="sm:col-span-1">
          <div
            className={`tnum font-mono text-2xl font-semibold ${
              Object.keys(q.failed_checks).length > 0
                ? 'text-danger-soft-foreground'
                : 'text-success-soft-foreground'
            }`}
          >
            {Object.keys(q.failed_checks).length}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            failing or warning across this company's reports
          </p>
        </Card>
      </div>

      {q.disputed_cells > 0 && (
        <Alert tone="warning" className="mb-4" title="Some figures are disputed.">
          {q.disputed_fields.length} field(s) have readings differing by more than half
          across this company's reports, so no single one is presented as the
          answer. Highest extractor confidence does not mean most correct here.{' '}
          <Link
            to={`/results?company=${encodeURIComponent(profile.company)}`}
            className="font-medium underline underline-offset-2"
          >
            Choose the right reading
          </Link>
          .
        </Alert>
      )}

      {tiles.length > 0 && (
        <Card
          title={`Headline figures, ${latest}`}
          subtitle="Latest reporting year. A dash means the figure was not found in any of this company's reports."
          className="mb-4"
        >
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {tiles.map((t) => (
              <StatTile
                key={t.label}
                label={t.label}
                point={t.point}
                currency={t.point?.currency}
              />
            ))}
          </div>
        </Card>
      )}

      <div className="mb-4 grid gap-3 lg:grid-cols-5">
        <Card
          title="Trend"
          subtitle="Reported figures by year, unrounded"
          className="lg:col-span-3"
        >
          <TrendChart
            profile={profile}
            fields={['sales_and_revenue', 'net_income', 'total_assets']}
          />
        </Card>

        <Card
          title="What the assets are owed"
          subtitle="Liabilities then equity, as a share of total assets"
          className="lg:col-span-2"
        >
          <BalanceSheetBars profile={profile} />
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-accent" /> Liabilities
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-primary/80" /> Equity
            </span>
          </div>
        </Card>
      </div>

      {Object.keys(q.failed_checks).length > 0 && (
        <Card title="Checks that did not pass" className="mb-4">
          <ul className="space-y-1.5 text-sm">
            {Object.entries(q.failed_checks).map(([check, status]) => (
              <li key={check} className="flex items-center gap-2">
                <Badge tone={status === 'ERROR' ? 'danger' : 'warning'}>
                  {status.toLowerCase()}
                </Badge>
                <span className="font-mono text-xs">{check}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            A failed check does not mean the figure is wrong. It means the report's
            own numbers do not reconcile, which is worth knowing before quoting any
            of them.
          </p>
        </Card>
      )}

      <Card
        title={`Filings (${profile.documents.length})`}
        subtitle="Every report held for this company, whether or not it produced figures."
        padded={false}
      >
        <Table>
          <thead>
            <tr>
              <Th>Report</Th>
              <Th align="right">Year</Th>
              <Th align="right">Pages</Th>
              <Th align="right">Figures</Th>
              <Th>Status</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {profile.documents.map((d) => (
              <tr key={d.id}>
                <Td>
                  <span className="font-medium">{d.filename}</span>
                  {d.pdf_type && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {d.pdf_type.toLowerCase()}
                    </span>
                  )}
                </Td>
                <Td align="right" className="tnum">
                  {d.reporting_year ?? '-'}
                </Td>
                <Td align="right" className="tnum text-muted-foreground">
                  {d.pages ?? '-'}
                </Td>
                <Td align="right" className="tnum">
                  {d.values > 0 ? d.values : <span className="text-muted-foreground/50">0</span>}
                </Td>
                <Td>
                  <Badge
                    tone={
                      d.status === 'COMPLETED'
                        ? 'success'
                        : d.status === 'FAILED'
                          ? 'danger'
                          : 'neutral'
                    }
                  >
                    {titleCase(d.status)}
                  </Badge>
                </Td>
                <Td align="right">
                  <Link
                    to={`/documents/${d.id}`}
                    className="text-sm font-medium underline underline-offset-2"
                  >
                    Open
                  </Link>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  )
}