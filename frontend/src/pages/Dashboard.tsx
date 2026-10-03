import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAction, useLiveRefresh, useQuery } from '../hooks/useQuery'
import { num, pct, relativeTime, titleCase } from '../lib/format'
import { useProcessing } from '../lib/processing-context'
import type { BatchAction } from '../lib/types'
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
      title="Scan and process"
      subtitle="Scan walks a folder for PDFs and registers them; process then runs OCR, extraction and validation on what is already registered."
    >
      <div className="space-y-3">
        {error && <ErrorBanner message={error} onRetry={reset} />}

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
          <Input
            label="Scan directory"
            placeholder="Path to a folder of PDFs"
            value={scanDir}
            spellCheck={false}
            onChange={(e) => setScanDirOverride(e.target.value)}
            hint="Relative paths resolve from the project root. Paths outside it are rejected."
          />
          <Input
            label="Limit"
            placeholder="all"
            inputMode="numeric"
            value={limit}
            onChange={(e) => setLimit(e.target.value.replace(/\D/g, ''))}
            hint="Optional cap"
          />
        </div>

        {scanDirOverride !== null && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setScanDirOverride(null)}
            className="-mt-1"
          >
            Reset to configured directory
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
            {running ? 'Running' : 'Scan and process'}
          </Button>
          <Button disabled={disabled} onClick={() => start('scan', { limit: limitValue })}>
            Scan only
          </Button>
          <Button disabled={disabled} onClick={() => start('process', { limit: limitValue })}>
            Process registered
          </Button>
          <Button disabled={disabled} onClick={() => start('process', { force: true })}>
            Reprocess all
          </Button>
          <Button disabled={disabled} onClick={() => start('retry_failed')}>
            Retry failures
          </Button>
          <Button disabled={disabled} onClick={() => start('retry_review')}>
            Retry review
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
                  {stopping
                    ? 'Stopping'
                    : `Running ${titleCase(state?.mode ?? 'batch')}`}
                </span>
                <span>Started {relativeTime(state?.started_at)}.</span>
                <Button
                  variant="danger"
                  size="sm"
                  pending={stop.pending}
                  disabled={stopping}
                  onClick={() => stop.run()}
                >
                  {stopping ? 'Stopping...' : 'Stop'}
                </Button>
              </span>
              <span className="mt-1 block text-xs">
                {stopping
                  ? 'Documents already being read finish first, then the queue is dropped. Nothing is lost.'
                  : 'This card refreshes automatically; watch detail in the log on the Exports page.'}
              </span>
            </Alert>
          ) : state?.error ? (
            <Alert tone="danger" title="Last run failed.">
              <span className="wrap-anywhere">{state.error}</span>
            </Alert>
          ) : scanResult ? (
            <Alert tone="success" action={<Button size="sm" variant="secondary" onClick={refetchState}>Dismiss</Button>}>
              Scanned <span className="font-mono text-xs wrap-anywhere">{scanResult.directory}</span>{' '}
              &mdash; {num(scanResult.discovered)} new document
              {scanResult.discovered === 1 ? '' : 's'} registered.
            </Alert>
          ) : null}
        </div>

        {summary ? (
          <dl className="grid grid-cols-2 gap-4 border-t border-border pt-3 sm:grid-cols-4">
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">Documents</dt>
              <dd className="tnum text-lg font-semibold">{num(summary.documents)}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">Companies</dt>
              <dd className="tnum text-lg font-semibold">{num(summary.companies)}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">OCR documents</dt>
              <dd className="tnum text-lg font-semibold">{num(summary.ocr_documents)}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted-foreground">Avg confidence</dt>
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
      title="Recently updated"
      actions={
        <Link
          to="/documents"
          className="text-xs font-medium text-primary hover:underline"
        >
          All documents
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
          title="No documents yet"
          hint="Run Scan and process above to register the PDFs in your input folder."
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
                  {doc.validation_errors ? `${num(doc.validation_errors)} checks` : '-'}
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

export default function Dashboard() {
  const summary = useQuery(() => api.summary(), [])
  const { state, refetch: refetchState } = useProcessing()
  // Keep the tiles live while a batch runs; the pipeline commits each document
  // as it finishes, so the numbers really do move.
  useLiveRefresh(summary.refetch, state?.running ?? false)

  if (summary.initialLoading) {
    return (
      <>
        <PageHeader title="Dashboard" />
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

  const s = summary.data
  if (!s) return null

  const docSlices = slicesFromCounts(s.status_counts, DOC_STATUS_ORDER, DOC_STATUS_COLORS)
  const checkSlices = slicesFromCounts(
    s.check_status_counts,
    CHECK_STATUS_ORDER,
    CHECK_STATUS_COLORS,
  )
  const problemCount =
    (s.validation_doc_counts.ERROR ?? 0) + (s.validation_doc_counts.WARNING ?? 0)

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Extraction coverage and data-quality health across the corpus"
        actions={
          <Button
            variant="secondary"
            pending={summary.loading}
            onClick={() => {
              summary.refetch()
              refetchState()
            }}
          >
            Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label="Documents" value={num(s.documents)} hint={`${num(s.companies)} companies`} />
        <Stat label="Pages" value={num(s.pages)} hint={`${num(s.values)} values extracted`} />
        <Stat
          label="Validation checks"
          value={num(s.checks)}
          hint={`${num(s.check_status_counts.ERROR ?? 0)} errors`}
          tone={s.check_status_counts.ERROR ? 'danger' : 'success'}
        />
        <Stat
          label="Needs attention"
          value={num(problemCount)}
          hint="documents with errors or warnings"
          tone={problemCount ? 'warning' : 'success'}
        />
        <Stat
          label="Low confidence"
          value={num(s.low_confidence_values)}
          hint="values below review threshold"
          tone={s.low_confidence_values ? 'warning' : 'success'}
        />
        <Stat
          label="Avg confidence"
          value={s.avg_confidence ? pct(s.avg_confidence) : '-'}
          tone={(s.avg_confidence ?? 0) >= 0.9 ? 'success' : 'warning'}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card
          title="Documents by status"
          subtitle="Pipeline state per document"
          actions={
            <Link
              to="/documents"
              className="text-xs font-medium text-primary hover:underline"
            >
              View all
            </Link>
          }
        >
          <Donut slices={docSlices} centerLabel="documents" centerValue={num(s.documents)} />
        </Card>

        <Card
          title="Checks by outcome"
          subtitle="Accounting validation results"
          actions={
            <Link
              to="/validations"
              className="text-xs font-medium text-primary hover:underline"
            >
              Review queue
            </Link>
          }
        >
          <Donut slices={checkSlices} centerLabel="checks" centerValue={num(s.checks)} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card
          title="Extraction confidence"
          subtitle="Documents bucketed by average extraction confidence"
          className="lg:col-span-2"
        >
          {s.confidence_histogram.length === 0 ? (
            <EmptyState
              title="No extracted values yet"
              hint="Process a document to populate this distribution."
            />
          ) : (
            <Histogram
              buckets={s.confidence_histogram.map((b) => ({
                label: b.bucket,
                value: b.count,
              }))}
            />
          )}
        </Card>

        <Card title="Documents needing review" subtitle="Ranked by failing checks">
          <BarList
            items={s.worst_companies.map((c) => ({ label: c.company, value: c.errors }))}
            emptyLabel="No validation errors"
            color="var(--chart-4)"
          />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Most frequent checks">
          {s.check_by_name.length === 0 ? (
            <EmptyState title="No checks recorded" />
          ) : (
            <ul className="space-y-1.5">
              {s.check_by_name.slice(0, 8).map((c) => (
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

        <Card title="Categories">
          {s.check_by_category.length === 0 ? (
            <EmptyState title="No categories recorded" />
          ) : (
            <BarList
              items={s.check_by_category.map((c) => ({
                label: titleCase(c.category ?? 'uncategorised'),
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