import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAction, useLiveRefresh, useQuery } from '../hooks/useQuery'
import { compactRupiah, num, pct, relativeTime, rupiah, titleCase } from '../lib/format'
import { OVERVIEW_FIELDS } from '../lib/metrics'
import { INDICATOR_META } from '../lib/field-labels'
import { dashboard as s, common } from '../lib/strings'
import { useProcessing } from '../lib/processing-context'
import type { BatchAction, FinancialPulse } from '../lib/types'
import { slicesFromCounts } from '../lib/slices'
import {
  CHECK_STATUS_COLORS,
  CHECK_STATUS_ORDER,
  DOC_STATUS_COLORS,
  DOC_STATUS_ORDER,
} from '../lib/palette'
import { BarList, Donut, Histogram, StackedBar } from '../components/charts'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  PageHeader,
  Skeleton,
  Spinner,
  Stat,
} from '../components/ui'

/** Body accepted by POST /api/processing. */
interface BatchStart {
  action: BatchAction
  force?: boolean
  limit?: number | null
  input?: string | null
}

/**
 * Two distinct pipeline steps, deliberately kept as separate buttons:
 *   scan - walk the input directory and register PDFs in the database
 *   process - OCR/extract/validate the documents already registered
 * `scan_process` chains them, which is what most people want day to day.
 */
function RunBatchCard() {
  const { state, refetch: refetchState } = useProcessing()
  const { run, pending, error, reset } = useAction((body: BatchStart) =>
    api.startProcessing(body),
  )
  // Stopping is cooperative: the batch stops handing out new documents and
  // lets the ones already being read finish, so no report is left half-written.
  const stop = useAction(() => api.stopProcessing())

  // The backend reports the directory that would actually be scanned. Derive it
  // until the operator types something, rather than copying it into state with
  // an effect.
  const [scanDirOverride, setScanDirOverride] = useState<string | null>(null)
  const scanDir = scanDirOverride ?? state?.input_directory ?? ''

  const [limit, setLimit] = useState('')
  const summary = state?.summary
  const running = state?.running ?? false
  const stopping = state?.cancel_requested === true
  const scanResult = state?.result?.scanned
  const disabled = running || pending
  const limitValue = limit ? Number(limit) : null

  const start = (action: BatchAction, extra: Partial<BatchStart> = {}) =>
    run({ action, input: scanDir || null, ...extra })

  return (
    <Card
      title={s.batch.title}
      subtitle={s.batch.subtitle}
    >
      <div className="space-y-3">
        {error && <ErrorBanner message={error} onRetry={reset} />}

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
          <Input
            label={s.batch.scanDir}
            placeholder={s.batch.scanDirPlaceholder}
            value={scanDir}
            spellCheck={false}
            onChange={(e) => setScanDirOverride(e.target.value)}
            hint={s.batch.scanDirHint}
          />
          <Input
            label={s.batch.limit}
            placeholder={s.batch.limitPlaceholder}
            inputMode="numeric"
            value={limit}
            onChange={(e) => setLimit(e.target.value.replace(/\D/g, ''))}
            hint={s.batch.limitHint}
          />
        </div>

        {scanDirOverride !== null && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setScanDirOverride(null)}
            className="-mt-1"
          >
            {s.batch.resetDir}
          </Button>
        )}

        {/* flex-wrap keeps every button reachable on a 320px screen instead of
            overflowing; each keeps its own label rather than collapsing to an
            icon the visitor has to guess. */}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            disabled={disabled}
            pending={pending}
            onClick={() => start('scan_process', { limit: limitValue })}
          >
            {running ? s.batch.running : s.batch.scanProcess}
          </Button>
          <Button disabled={disabled} onClick={() => start('scan', { limit: limitValue })}>
            {s.batch.scanOnly}
          </Button>
          <Button disabled={disabled} onClick={() => start('process', { limit: limitValue })}>
            {s.batch.processRegistered}
          </Button>
          <Button disabled={disabled} onClick={() => start('process', { force: true })}>
            {s.batch.reprocessAll}
          </Button>
          <Button disabled={disabled} onClick={() => start('retry_failed')}>
            {s.batch.retryFailed}
          </Button>
          <Button disabled={disabled} onClick={() => start('retry_review')}>
            {s.batch.retryReview}
          </Button>
        </div>

        {/* Announced politely so a screen-reader user learns a batch started
            without having to hunt for the change. */}
        <div aria-live="polite">
          {running ? (
            <Alert tone="info">
              <span className="inline-flex flex-wrap items-center gap-2">
                <Spinner className="h-4 w-4" />
                <span className="font-medium">
                  {stopping ? s.batch.stopping : `${s.batch.running} ${titleCase(state?.mode ?? 'batch')}`}
                </span>
                <span>
                  {s.batch.started} {relativeTime(state?.started_at)}.
                </span>
                <Button
                  variant="danger"
                  size="sm"
                  pending={stop.pending}
                  disabled={stopping}
                  onClick={() => stop.run()}
                >
                  {stopping ? s.batch.stopping : s.batch.stop}
                </Button>
              </span>
              <span className="mt-1 block text-xs">
                {stopping ? s.batch.stopHint : s.batch.liveHint}
              </span>
            </Alert>
          ) : state?.error ? (
            <Alert tone="danger" title={s.batch.lastRunFailed}>
              <span className="wrap-anywhere">{state.error}</span>
            </Alert>
          ) : scanResult ? (
            <Alert tone="success" action={<Button size="sm" variant="secondary" onClick={refetchState}>{s.batch.dismiss}</Button>}>
              {s.batch.scanned(scanResult.directory, scanResult.discovered ?? 0)}
            </Alert>
          ) : null}
        </div>

        {summary ? (
          <dl className="grid grid-cols-2 gap-4 border-t border-border pt-3 sm:grid-cols-4">
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">{s.batch.summary.documents}</dt>
              <dd className="tnum text-lg font-semibold">{num(summary.documents)}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">{s.batch.summary.companies}</dt>
              <dd className="tnum text-lg font-semibold">{num(summary.companies)}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">{s.batch.summary.ocr}</dt>
              <dd className="tnum text-lg font-semibold">{num(summary.ocr_documents)}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">{s.batch.summary.avgConfidence}</dt>
              <dd className="tnum text-lg font-semibold">
                {summary.avg_confidence ? pct(summary.avg_confidence) : '-'}
              </dd>
            </div>
          </dl>
        ) : null}
      </div>
    </Card>
  )
}

function RecentDocuments() {
  const recent = useQuery(
    () => api.documents({ page: 1, page_size: 8, sort: 'updated', order: 'desc' }),
    [],
  )
  const { state } = useProcessing()
  useLiveRefresh(recent.refetch, state?.running ?? false)

  return (
    <Card
      title={s.cards.recentlyUpdated}
      actions={
        <Link
          to="/documents"
          className="text-xs font-medium text-primary hover:underline"
        >
          {s.cards.allDocuments}
        </Link>
      }
    >
      {recent.error ? (
        <ErrorBanner message={recent.error} onRetry={recent.refetch} />
      ) : recent.initialLoading ? (
        <div className="space-y-2" aria-hidden>
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-9" />
          ))}
        </div>
      ) : recent.data?.items.length === 0 ? (
        <EmptyState
          title={s.cards.noDocuments}
          hint={s.cards.noDocumentsHint}
        />
      ) : (
        <ul className="divide-y divide-border">
          {recent.data?.items.map((doc) => (
            <li key={doc.id}>
              <Link
                to={`/documents/${doc.id}`}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-2.5 transition-colors hover:bg-accent/50"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">
                    {doc.company}
                  </span>
                  <span className="block truncate font-mono text-xs text-muted-foreground">
                    {doc.filename}
                  </span>
                </span>
                <span className="hidden text-xs text-muted-foreground sm:block">
                  {doc.reporting_year ?? '-'}
                </span>
                <span className="hidden w-20 text-xs text-muted-foreground sm:block">
                  {doc.validation_errors ? `${num(doc.validation_errors)} ${s.cards.checksSuffix}` : '-'}
                </span>
                <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">
                  {relativeTime(doc.updated_at ?? doc.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** One ranked company in the pulse. The row is a link, so a
 *  reader can jump from "largest" straight into the entity
 *  view without going through the grid. */
function LeaderRow({
  rank,
  company,
  year,
  value,
  max,
}: {
  rank: number
  company: string
  year: number | null
  value: number | null
  max: number
}) {
  return (
    <li>
      <Link
        to={`/companies/${encodeURIComponent(company)}`}
        className="group block rounded-md px-2 py-1.5 transition-colors hover:bg-accent/50"
      >
        <div className="flex items-baseline justify-between gap-3">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="tnum w-4 shrink-0 text-xs text-muted-foreground">
              {rank}
            </span>
            <span className="min-w-0 truncate text-sm font-medium text-foreground group-hover:underline">
              {company}
            </span>
          </span>
          <span
            className="tnum shrink-0 text-sm font-medium"
            title={value === null ? common.noDataHint : `${common.exactValue}: ${rupiah(value)}`}
          >
            {compactRupiah(value)}
          </span>
        </div>
        {/* The bar is the comparison: how much larger the
            leader is than the next, at a glance. */}
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary/70"
            style={{
              width: `${Math.max((Math.abs(value ?? 0) / max) * 100, value ? 2 : 0)}%`,
            }}
          />
        </div>
        <span className="block text-[0.65rem] text-muted-foreground">
          {s.pulse.asOf(year)}
        </span>
      </Link>
    </li>
  )
}

function LeaderList({
  items,
}: {
  items: FinancialPulse['leaders'][string]
}) {
  if (items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {common.noResults}
      </p>
    )
  }
  const max = Math.max(...items.map((i) => Math.abs(i.value ?? 0)), 1)
  return (
    <ul className="space-y-1">
      {items.map((row, i) => (
        <LeaderRow
          key={row.company}
          rank={i + 1}
          company={row.company}
          year={row.year}
          value={row.value}
          max={max}
        />
      ))}
    </ul>
  )
}

/** Which classifications the corpus covers, and how many
 *  companies report under each. */
function SubsectorList({ pulse }: { pulse: FinancialPulse }) {
  return (
    <div className="space-y-2">
      <BarList
        items={pulse.subsectors.map((row) => ({
          label: row.subsector,
          value: row.companies,
        }))}
        formatValue={(n) => num(n)}
        emptyLabel={common.noResults}
      />
      {pulse.undeclared_subsectors > 0 && (
        <p className="text-xs text-muted-foreground">
          {s.pulse.undeclared}: {num(pulse.undeclared_subsectors)}
        </p>
      )}
    </div>
  )
}

/** How many companies report each of the nine indicators --
 *  the honest answer to "what can I actually analyse here". */
function CoverageChips({ pulse }: { pulse: FinancialPulse }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {OVERVIEW_FIELDS.map((field) => {
        const meta = INDICATOR_META[field]
        const count = pulse.coverage[field] ?? 0
        return (
          <li
            key={field}
            className="flex items-baseline justify-between gap-3 rounded-md border border-border px-2.5 py-2"
            title={meta?.full}
          >
            <span className="min-w-0 truncate text-xs text-muted-foreground">
              {meta?.short ?? field}
            </span>
            <span className="tnum shrink-0 text-sm font-medium">
              {num(count)}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** The financial pulse of the whole corpus: what is covered,
 *  who is largest, who earns the most. Fed by
 *  /api/summary/financials, which aggregates with the same
 *  winner rules as the results grid, so a leader here
 *  cannot disagree with the grid. */
function FinancialPulseSection() {
  const pulse = useQuery(() => api.financialPulse(), [])
  const { state } = useProcessing()
  // A batch commits figures as documents finish, so the
  // rankings move while it runs.
  useLiveRefresh(pulse.refetch, state?.running ?? false)

  if (pulse.initialLoading) {
    return (
      <div className="mb-4" aria-hidden>
        <Skeleton className="mb-3 h-4 w-56" />
        <div className="grid gap-4 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-40" />
          <Skeleton className="h-40 lg:col-span-2" />
        </div>
      </div>
    )
  }
  if (pulse.error) {
    return <ErrorBanner message={pulse.error} onRetry={pulse.refetch} />
  }
  const p = pulse.data
  if (!p) return null

  const covered = Object.values(p.coverage).some((n) => n > 0)
  if (!covered && p.subsectors.length === 0) {
    return (
      <Card title={s.pulse.title} subtitle={s.pulse.subtitle}>
        <EmptyState title={s.pulse.noData} hint={s.pulse.noDataHint} />
      </Card>
    )
  }

  return (
    <section aria-label={s.pulse.title} className="mb-4">
      <h2 className="text-sm font-semibold text-foreground">
        {s.pulse.title}
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {s.pulse.subtitle}
      </p>
      <div className="mt-3 grid gap-4 lg:grid-cols-3">
        <Card title={s.pulse.subsectors} subtitle={s.pulse.subsectorsSub}>
          <SubsectorList pulse={p} />
        </Card>
        <Card title={s.pulse.largest} subtitle={s.pulse.largestSub}>
          <LeaderList items={p.leaders.total_assets ?? []} />
        </Card>
        <Card title={s.pulse.revenue} subtitle={s.pulse.revenueSub}>
          <LeaderList items={p.leaders.sales_and_revenue ?? []} />
        </Card>
        <Card title={s.pulse.profit} subtitle={s.pulse.profitSub}>
          <LeaderList items={p.leaders.total_profit_loss ?? []} />
        </Card>
        <Card
          title={s.pulse.coverage}
          subtitle={s.pulse.coverageSub}
          className="lg:col-span-2"
        >
          <CoverageChips pulse={p} />
        </Card>
      </div>
    </section>
  )
}

export default function Dashboard() {
  const summary = useQuery(() => api.summary(), [])
  const { state, refetch: refetchState } = useProcessing()
  // Keep the tiles live while a batch runs; the pipeline commits each document
  // as it finishes, so the numbers really do move.
  useLiveRefresh(summary.refetch, state?.running ?? false)

  if (summary.initialLoading) {
    return (
      <>
        <PageHeader title={s.title} />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[5.5rem]" />
          ))}
        </div>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </>
    )
  }
  if (summary.error) {
    return <ErrorBanner message={summary.error} onRetry={summary.refetch} />
  }

  const s0 = summary.data
  if (!s0) return null

  const docSlices = slicesFromCounts(s0.status_counts, DOC_STATUS_ORDER, DOC_STATUS_COLORS)
  const checkSlices = slicesFromCounts(
    s0.check_status_counts,
    CHECK_STATUS_ORDER,
    CHECK_STATUS_COLORS,
  )
  const problemCount =
    (s0.validation_doc_counts.ERROR ?? 0) + (s0.validation_doc_counts.WARNING ?? 0)

  return (
    <>
      <PageHeader
        title={s.title}
        subtitle={s.subtitle}
        actions={
          <Button
            variant="secondary"
            pending={summary.loading}
            onClick={() => {
              summary.refetch()
              refetchState()
            }}
          >
            {common.refresh}
          </Button>
        }
      />

      {/* The financial pulse leads: what the corpus holds,
          before the pipeline that produced it. */}
      <FinancialPulseSection />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label={s.stats.documents} value={num(s0.documents)} hint={s.stats.companies(s0.companies)} />
        <Stat label={s.stats.pages} value={num(s0.pages)} hint={s.stats.valuesExtracted(s0.values)} />
        <Stat
          label={s.stats.checks}
          value={num(s0.checks)}
          hint={s.stats.errors(s0.check_status_counts.ERROR ?? 0)}
          tone={s0.check_status_counts.ERROR ? 'danger' : 'success'}
        />
        <Stat
          label={s.stats.attention}
          value={num(problemCount)}
          hint={s.stats.attentionHint}
          tone={problemCount ? 'warning' : 'success'}
        />
        <Stat
          label={s.stats.lowConfidence}
          value={num(s0.low_confidence_values)}
          hint={s.stats.lowConfidenceHint}
          tone={s0.low_confidence_values ? 'warning' : 'success'}
        />
        <Stat
          label={s.stats.avgConfidence}
          value={s0.avg_confidence ? pct(s0.avg_confidence) : '-'}
          tone={(s0.avg_confidence ?? 0) >= 0.9 ? 'success' : 'warning'}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card
          title={s.cards.byStatus}
          subtitle={s.cards.byStatusSub}
          actions={
            <Link
              to="/documents"
              className="text-xs font-medium text-primary hover:underline"
            >
              {s.cards.viewAll}
            </Link>
          }
        >
          <Donut slices={docSlices} centerLabel={s.stats.documents.toLowerCase()} centerValue={num(s0.documents)} />
        </Card>

        <Card
          title={s.cards.byOutcome}
          subtitle={s.cards.byOutcomeSub}
          actions={
            <Link
              to="/validations"
              className="text-xs font-medium text-primary hover:underline"
            >
              {s.cards.reviewQueue}
            </Link>
          }
        >
          <Donut slices={checkSlices} centerLabel={s.stats.checks.toLowerCase()} centerValue={num(s0.checks)} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card
          title={s.cards.confidence}
          subtitle={s.cards.confidenceSub}
          className="lg:col-span-2"
        >
          {s0.confidence_histogram.length === 0 ? (
            <EmptyState
              title={s.cards.noValues}
              hint={s.cards.noValuesHint}
            />
          ) : (
            <Histogram
              buckets={s0.confidence_histogram.map((b) => ({
                label: b.bucket,
                value: b.count,
              }))}
            />
          )}
        </Card>

        <Card title={s.cards.needingReview} subtitle={s.cards.needingReviewSub}>
          <BarList
            items={s0.worst_companies.map((c) => ({ label: c.company, value: c.errors }))}
            emptyLabel={s.cards.noErrors}
            color="var(--chart-4)"
          />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title={s.cards.frequentChecks}>
          {s0.check_by_name.length === 0 ? (
            <EmptyState title={s.cards.noChecks} />
          ) : (
            <ul className="space-y-1.5">
              {s0.check_by_name.slice(0, 8).map((c) => (
                <li key={`${c.check_name}-${c.status}`}>
                  <Link
                    to={`/validations?check_name=${encodeURIComponent(c.check_name)}&status=${c.status}`}
                    className="group flex items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-accent/50"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-muted-foreground group-hover:text-foreground">
                        {titleCase(c.check_name)}
                      </span>
                      <span className="mt-1 block">
                        <StackedBar
                          slices={slicesFromCounts(
                            { [c.status]: c.count },
                            CHECK_STATUS_ORDER,
                            CHECK_STATUS_COLORS,
                          )}
                        />
                      </span>
                    </span>
                    <span className="tnum shrink-0 text-sm font-medium text-foreground">
                      {num(c.count)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={s.cards.categories}>
          {s0.check_by_category.length === 0 ? (
            <EmptyState title={s.cards.noCategories} />
          ) : (
            <BarList
              items={s0.check_by_category.map((c) => ({
                label: titleCase(c.category ?? s.cards.uncategorized),
                value: c.count,
              }))}
            />
          )}
        </Card>
      </div>

      <div className="mt-4">
        <RunBatchCard />
      </div>

      <div className="mt-4">
        <RecentDocuments />
      </div>
    </>
  )
}
