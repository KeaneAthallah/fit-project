import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useLiveRefresh, useQuery } from '../hooks/useQuery'
import { useProcessing } from '../lib/processing-context'
import { titleCase } from '../lib/format'
import { INDICATOR_META, fieldLabel } from '../lib/field-labels'
import { common, company as s } from '../lib/strings'
import type { CompanyProfile } from '../lib/types'
import { OVERVIEW_FIELDS, pointAt, subsectorOf } from '../lib/metrics'
import {
  EquityComposition,
  IkhtisarTable,
  KpiCard,
  TaxActivityCard,
  TrendChart,
} from '../components/financial'
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Skeleton,
  Table,
  Td,
  Th,
} from '../components/ui'

/**
 * One company, seen whole.
 *
 * The results grid answers "how do these companies compare"; this
 * answers "how is this company doing". The nine indicators the
 * product is organized around lead: four core figures at a
 * glance, then how equity is composed, how the year traded,
 * what tax did, and finally every indicator against every
 * year. Coverage, quality and the filings themselves stay one
 * glance below, because a figure a reader cannot trust is worth
 * knowing about before quoting it.
 */

/** Does this company report this field in any year? A card
 *  about a figure the company never declared would read as
 *  broken, so its section is dropped instead. */
function hasField(profile: CompanyProfile, field: string): boolean {
  return profile.metrics[field]?.some((p) => p.normalized_value !== null) ?? false
}

/** The four indicators a reader scans first. */
const CORE_FIELDS = [
  'total_assets',
  'total_equity',
  'sales_and_revenue',
  'total_profit_loss',
] as const

const EQUITY_FIELDS = [
  'equity_attributable_to_owners_of_parent',
  'non_controlling_interest',
  'total_equity',
] as const

/**
 * Assets against liabilities and equity, as one bar per year.
 *
 * The point is not precision: it is that when the two halves
 * do not meet, the gap is visible without reading a number,
 * which is the same thing the accounting validation reports
 * in words.
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
        // Shares of total assets; a missing half is shown as a
        // gap rather than quietly rescaled to 100%.
        const lShare = l === null ? null : Math.min(100, Math.max(0, (l / a) * 100))
        const eShare = e === null ? null : Math.min(100, Math.max(0, (e / a) * 100))
        const balanced = l !== null && e !== null && Math.abs(l + e - a) / a < 0.01
        return (
          <li key={year} className="text-xs">
            <div className="mb-0.5 flex items-baseline justify-between gap-2">
              <span className="font-medium">{year}</span>
              <span className="tnum font-mono text-muted-foreground">
                {a < 0 ? `(${(-a).toLocaleString('id-ID')})` : a.toLocaleString('id-ID')}
                {balanced ? (
                  <span className="ml-2 text-[0.65rem] text-success-soft-foreground">
                    {s.kpis.balances}
                  </span>
                ) : (
                  <span className="ml-2 text-[0.65rem] text-warning-soft-foreground">
                    {s.kpis.doesNotBalance}
                  </span>
                )}
              </span>
            </div>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
              {lShare !== null && (
                <div
                  className="bg-accent"
                  style={{ width: `${lShare}%` }}
                  title={`${fieldLabel('total_liabilities', profile.labels.total_liabilities)}`}
                />
              )}
              {eShare !== null && (
                <div
                  className="bg-primary/80"
                  style={{ width: `${eShare}%` }}
                  title={`${fieldLabel('total_equity', profile.labels.total_equity)}`}
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
  // A batch can add figures for this company while the page is
  // open, which is the same reason the results grid stays live.
  const { state } = useProcessing()
  const refresh = query.refetch
  useLiveRefresh(refresh, state?.running ?? false)

  const profile = query.data
  const latest = profile?.years.length
    ? profile.years[profile.years.length - 1]
    : undefined

  // Loading resembles the final layout: the strip, the four
  // KPI cards, the composition row, so the page does not jump
  // when the figures land.
  if (query.initialLoading) {
    return (
      <>
        <PageHeader title={name} />
        <div className="mb-4 h-12 rounded-lg border border-border bg-card" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-6">
          <Skeleton className="h-44 lg:col-span-2" />
          <Skeleton className="h-44 lg:col-span-2" />
          <Skeleton className="h-44 lg:col-span-2" />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </>
    )
  }
  if (query.error) {
    return (
      <>
        <PageHeader title={name} />
        <ErrorBanner message={query.error} onRetry={query.refetch} />
      </>
    )
  }
  if (!profile) return <EmptyState title={s.notLoaded} />

  const { totals, quality } = profile
  const q = quality
  const subsector = subsectorOf(profile)
  const hasFigures = latest !== undefined
  const equityPresent = EQUITY_FIELDS.some((f) => hasField(profile, f))
  const profitabilityPresent = hasField(profile, 'sales_and_revenue') ||
    hasField(profile, 'total_profit_loss_before_tax') ||
    hasField(profile, 'total_profit_loss')
  const overviewPresent = hasFigures && OVERVIEW_FIELDS.some((f) => hasField(profile, f))

  return (
    <>
      <PageHeader
        title={profile.company}
        subtitle={
          totals.years > 0 && latest !== undefined
            ? s.subtitle(totals.years, latest)
            : s.noYears
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/results?company=${encodeURIComponent(profile.company)}`}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
            >
              {s.allFigures}
            </Link>
            <Link
              to={`/documents?company=${encodeURIComponent(profile.company)}`}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
            >
              {s.documents}
            </Link>
          </div>
        }
      />

      {/* What this entity is. The sub-sector is a property of
          the company, not of a year, so it leads the page
          without pretending to be a financial KPI. */}
      <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-border bg-card px-4 py-3">
        <span className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 text-xs text-muted-foreground" title={INDICATOR_META.sub_sector.full}>
            {INDICATOR_META.sub_sector.short}
          </span>
          {subsector ? (
            <Badge tone="accent" title={INDICATOR_META.sub_sector.full}>
              {subsector}
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">&mdash;</span>
          )}
        </span>
        {profile.currencies.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {s.latest.reportedIn(profile.currencies.join(', '))}
          </span>
        )}
      </div>

      {hasFigures && (
        <>
          {/* The four indicators a reader scans first. */}
          <section aria-label={s.kpis.title} className="mb-4">
            <h2 className="text-sm font-semibold text-foreground">
              {s.kpis.title}
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {s.kpis.subtitle}
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {CORE_FIELDS.map((field) => (
                <KpiCard key={field} field={field} profile={profile} year={latest!} />
              ))}
            </div>
          </section>

          {/* How the company is composed: equity split, the
              balance sheet identity, and what tax did. */}
          <div className="grid gap-4 lg:grid-cols-6">
            {equityPresent && (
              <Card
                title={s.kpis.equity}
                subtitle={s.kpis.equitySub}
                className="lg:col-span-2"
              >
                <EquityComposition profile={profile} year={latest!} />
              </Card>
            )}
            {hasField(profile, 'total_assets') && (
              <Card
                title="Aset, Liabilitas, dan Ekuitas"
                subtitle="Liabilitas lalu ekuitas, sebagai bagian dari jumlah aset"
                className="lg:col-span-2"
              >
                <BalanceSheetBars profile={profile} />
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-accent" />{' '}
                    {s.kpis.legendLiabilities}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-primary/80" />{' '}
                    {s.kpis.legendEquity}
                  </span>
                </div>
              </Card>
            )}
            <Card
              title={s.kpis.tax}
              subtitle={s.kpis.taxSub}
              className="lg:col-span-2"
            >
              <TaxActivityCard profile={profile} year={latest!} />
            </Card>
          </div>

          {/* Trends: the year's trading, then the balance sheet
              growing. */}
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {profitabilityPresent && (
              <Card title={s.kpis.profitability} subtitle={s.kpis.profitabilitySub}>
                <TrendChart
                  profile={profile}
                  fields={[
                    'sales_and_revenue',
                    'total_profit_loss_before_tax',
                    'total_profit_loss',
                  ]}
                  ariaLabel={`${fieldLabel('sales_and_revenue')}, ${fieldLabel('total_profit_loss_before_tax')}, ${fieldLabel('total_profit_loss')} per tahun`}
                />
              </Card>
            )}
            {hasField(profile, 'total_assets') && hasField(profile, 'total_equity') && (
              <Card title={s.kpis.assetsEquity} subtitle={s.kpis.assetsEquitySub}>
                <TrendChart
                  profile={profile}
                  fields={['total_assets', 'total_equity']}
                  ariaLabel={`${fieldLabel('total_assets')} dan ${fieldLabel('total_equity')} per tahun`}
                />
              </Card>
            )}
          </div>

          {/* Every indicator, every year -- the detail the
              cards summarise. */}
          {overviewPresent && (
            <Card
              title={s.kpis.overview}
              subtitle={s.kpis.overviewSub}
              className="mt-4"
            >
              <IkhtisarTable profile={profile} />
            </Card>
          )}
        </>
      )}

      {!hasFigures && (
        <Card className="mb-4">
          <EmptyState title={s.kpis.noFigures} hint={s.kpis.noFiguresHint} />
        </Card>
      )}

      {q.disputed_cells > 0 && (
        <Alert tone="warning" className="mb-4" title={s.disputed.alertTitle}>
          {s.disputed.alertBody(q.disputed_fields.length)}{' '}
          <Link
            to={`/results?company=${encodeURIComponent(profile.company)}`}
            className="font-medium underline underline-offset-2"
          >
            {s.disputed.choose}
          </Link>
          .
        </Alert>
      )}

      {/* Coverage and quality: what is held, and how much of it
          can be trusted. */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card title={s.coverage.title}>
          <dl className="space-y-1 text-sm">
            {[
              [s.coverage.filings, `${totals.documents}`],
              [
                s.coverage.produced,
                s.coverage.producedOf(totals.documents_with_values, totals.documents),
              ],
              [s.coverage.extracted, `${totals.figures}`],
              [s.coverage.fields, `${totals.fields}`],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="tnum font-mono font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          {totals.documents_with_values < totals.documents && (
            <p className="mt-2 text-xs text-warning-soft-foreground">
              {s.coverage.unfinished(totals.documents - totals.documents_with_values)}
            </p>
          )}
        </Card>

        <Card title={s.latest.title}>
          <div className="tnum font-mono text-2xl font-semibold">
            {latest ?? '-'}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {profile.currencies.length > 0
              ? s.latest.reportedIn(profile.currencies.join(', '))
              : s.latest.noCurrency}
          </p>
        </Card>

        <Card title={s.disputed.title}>
          <div
            className={`tnum font-mono text-2xl font-semibold ${
              q.disputed_cells > 0 ? 'text-danger-soft-foreground' : ''
            }`}
          >
            {q.disputed_cells}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {s.disputed.of(q.figures)}
          </p>
        </Card>

        <Card title={s.checks.title}>
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
            {s.checks.failing}
          </p>
        </Card>
      </div>

      {Object.keys(q.failed_checks).length > 0 && (
        <Card title={s.checks.failedTitle} className="mt-4">
          <ul className="space-y-1.5 text-sm">
            {Object.entries(q.failed_checks).map(([check, status]) => (
              <li key={check} className="flex items-center gap-2">
                <Badge tone={status === 'ERROR' ? 'danger' : 'warning'}>
                  {titleCase(status)}
                </Badge>
                <span className="font-mono text-xs">{check}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            {s.checks.failedHint}
          </p>
        </Card>
      )}

      <Card
        title={s.filings.title(profile.documents.length)}
        subtitle={s.filings.subtitle}
        className="mt-4"
        padded={false}
      >
        <Table>
          <thead>
            <tr>
              <Th>{s.filings.report}</Th>
              <Th align="right">{s.filings.year}</Th>
              <Th align="right">{s.filings.pages}</Th>
              <Th align="right">{s.filings.figures}</Th>
              <Th>{s.filings.status}</Th>
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
                    {common.open}
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
