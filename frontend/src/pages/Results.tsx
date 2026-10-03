import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAction, useDebounced, useLiveRefresh, useQuery } from '../hooks/useQuery'
import type { QueryState } from '../hooks/useQuery'
import { useProcessing } from '../lib/processing-context'
import { useUrlFilters } from '../hooks/useFilters'
import { currencyLabel, currencyOptions, num, rupiah, titleCase } from '../lib/format'
import { companyPath } from '../lib/paths'
import type {
  ExtractedValue,
  ProcessingState,
  ResultsCoverage,
  SummaryCandidate,
  SummaryCell,
  SummaryDocument,
} from '../lib/types'
import { Confidence, ValueStatusBadge } from '../components/badges'
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  PageHeader,
  Pagination,
  Select,
  SkeletonTable,
  Table,
  Tabs,
  Td,
  Th,
} from '../components/ui'

const FILTER_KEYS = [
  'view',
  'search',
  'company',
  'year',
  'statement',
  'field',
  'status',
  'currency',
  'sort',
  'order',
  'page',
] as const

const PAGE_SIZE = 50

const STATUS_OPTIONS = [
  { value: '', label: 'Any status' },
  { value: 'REVIEW_REQUIRED', label: 'Needs review' },
  { value: 'OK', label: 'Accepted' },
]

type SortKey = 'company' | 'field' | 'year' | 'value' | 'confidence'
type View = 'summary' | 'values'

/**
 * Accepts a plain number and tolerates thousands separators.
 *
 * Deliberately NOT locale-aware: the stored figures are raw rupiah, and a
 * guess at whether "1.500.000" means one and a half million or fifteen hundred
 * million is exactly the kind of ambiguity a financial field must not have.
 * Anything else is rejected rather than guessed.
 */
function parseAmount(input: string): { value: number } | { error: string } {
  const trimmed = input.trim()
  // Empty means "this figure is not present", which the API models as null.
  // It is deliberately not the same as zero.
  if (trimmed === '') return { value: Number.NaN }
  if (!/^-?[0-9][0-9,]*$/.test(trimmed)) {
    return { error: 'Enter digits only, optionally separated by commas.' }
  }
  const cleaned = trimmed.replace(/,/g, '')
  if (!Number.isSafeInteger(Number(cleaned.replace('-', '')))) {
    return { error: 'That number is too large to be stored safely.' }
  }
  return { value: Number(cleaned) }
}

function EditRow({
  value,
  onDone,
}: {
  value: ExtractedValue
  onDone: (row: ExtractedValue) => void
}) {
  const [amount, setAmount] = useState(
    value.normalized_value === null ? '' : String(value.normalized_value),
  )
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const amountRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    amountRef.current?.focus()
    amountRef.current?.select()
  }, [])

  const save = useAction(async (body: Parameters<typeof api.updateValue>[1]) =>
    api.updateValue(value.id, body),
  )

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const parsed = parseAmount(amount)
    if ('error' in parsed) {
      setError(parsed.error)
      return
    }
    setError(null)
    // Number.NaN is how parseAmount signals "clear the figure"; JSON.stringify
    // turns it into null, which is exactly what the API wants.
    void save
      .run({ normalized_value: parsed.value, note: note.trim() || undefined })
      .then((res) => {
        if (res) onDone(res.value)
      })
  }

  return (
    <tr>
      <td colSpan={8} className="border-b border-border bg-muted/50 px-4 py-3">
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:max-w-3xl">
            <Input
              ref={amountRef}
              label="Corrected amount (full rupiah)"
              hint={
                value.normalized_value === null
                  ? 'Currently empty. Clear the field to leave it empty.'
                  : `Extractor read ${value.normalized_value.toLocaleString('id-ID')}.`
              }
              inputMode="numeric"
              autoComplete="off"
              spellCheck={false}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value)
                setError(null)
              }}
              aria-invalid={error ? true : undefined}
              className="tnum font-mono"
            />
            <Input
              label="Why (optional)"
              hint="Kept on the row so the change is auditable later."
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. mis-scaled on the highlights page"
              maxLength={200}
            />
          </div>

          {error && (
            <Alert tone="danger" className="lg:max-w-3xl">
              {error}
            </Alert>
          )}
          {save.error && <ErrorBanner message={save.error} onRetry={save.reset} />}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" size="sm" pending={save.pending}>
              Save correction
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={() => onDone(value)}>
              Cancel
            </Button>
            {value.is_edited && value.original_value !== null && (
              <span className="text-xs text-muted-foreground">
                Extractor originally read {rupiah(value.original_value)}
              </span>
            )}
          </div>
        </form>
      </td>
    </tr>
  )
}

function RevertButton({
  value,
  onDone,
}: {
  value: ExtractedValue
  onDone: (row: ExtractedValue) => void
}) {
  const revert = useAction(() => api.updateValue(value.id, { revert: true }))
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        pending={revert.pending}
        onClick={() => void revert.run().then((r) => r && onDone(r.value))}
        title={
          value.original_value === null
            ? "Restore the extractor's reading"
            : `Restore ${rupiah(value.original_value)}`
        }
      >
        Revert
      </Button>
      {revert.error && (
        <span className="sr-only" role="alert">
          {revert.error}
        </span>
      )}
    </>
  )
}

/** One figure in the grid.
 *
 *  Both states are buttons, because both are actions: a figure is corrected in
 *  place, and an empty cell is where a missing figure gets added. The empty
 *  state deliberately does not look like a dead em dash -- a reader has to be
 *  able to see that something can be done there. */
function GridCell({
  cell,
  label,
  company,
  year,
  canAdd,
  className = '',
  onEdit,
  onAdd,
}: {
  cell: SummaryCell | null | undefined
  label: string
  company: string
  year: number | null
  canAdd: boolean
  className?: string
  onEdit: () => void
  onAdd: () => void
}) {
  const where = `${label} for ${company}${year ? ` ${year}` : ''}`
  // Figures never wrap: a broken amount is read as a different amount.
  const base = `whitespace-nowrap ${className}`

  if (!cell) {
    if (!canAdd) {
      return (
        <Td align="right" className={`tnum text-muted-foreground/40 ${base}`} title={`No ${label} was found`}>
          &mdash;
        </Td>
      )
    }
    return (
      <Td align="right" className={base}>
        <button
          type="button"
          onClick={onAdd}
          title={`Add ${where}`}
          aria-label={`Add ${where}`}
          className="tnum group inline-flex items-center gap-1 rounded-md border border-dashed border-border px-1.5 py-0.5 text-sm text-muted-foreground/70 transition-colors hover:border-primary hover:bg-accent hover:text-primary"
        >
          <span aria-hidden className="text-xs leading-none">
            +
          </span>
          <span className="text-[0.65rem] font-sans font-semibold uppercase tracking-wide">
            add
          </span>
        </button>
      </Td>
    )
  }
  return (
    <Td align="right" className={base}>
      <button
        type="button"
        onClick={onEdit}
        title={`Edit ${where}`}
        aria-label={`Edit ${where}`}
        className="tnum -mr-1 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 font-mono text-sm font-semibold text-foreground hover:bg-accent hover:text-primary"
      >
        {rupiah(cell.normalized_value)}
        {cell.is_edited && (
          <span className="rounded bg-accent px-1 text-[0.6rem] font-sans font-semibold uppercase tracking-wide text-accent-foreground">
            edited
          </span>
        )}
        {cell.disputed && (
          <span
            className="rounded bg-danger-soft px-1 text-[0.6rem] font-sans font-bold uppercase tracking-wide text-danger-soft-foreground"
            title="Two readings of this figure disagree. Click to compare them."
          >
            disputed
          </span>
        )}
        {/* The pencil is a hover affordance, not a permanent fixture: one per
            cell across every column turns a table of numbers into a field of
            icons. Keyboard focus still reveals it. */}
        <svg
          viewBox="0 0 24 24"
          className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden
        >
          <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z" strokeLinejoin="round" />
        </svg>
      </button>
    </Td>
  )
}

/** Inline editor for one summary cell, in the grid row itself.
 *
 *  Handles both cases, because from the grid they are the same gesture:
 *  - `edit`: a figure exists, so the extractor reading is preserved and can be
 *    reverted to.
 *  - `add`: nothing exists, so there is no "before" to keep; the row is recorded
 *    as hand-entered from the start.
 */
function CellForm({
  cell,
  colSpan,
  company,
  documents,
  field,
  label,
  mode,
  year,
  onDone,
}: {
  cell: SummaryCell | null
  colSpan: number
  company: string
  documents: SummaryDocument[]
  field: string
  label: string
  mode: 'add' | 'edit'
  year: number | null
  onDone: () => void
}) {
  const [amount, setAmount] = useState(
    mode === 'edit' && cell?.normalized_value != null ? String(cell.normalized_value) : '',
  )
  const [note, setNote] = useState('')
  const [documentId, setDocumentId] = useState<number | null>(documents[0]?.id ?? null)
  const [error, setError] = useState<string | null>(null)
  const amountRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    amountRef.current?.focus()
    amountRef.current?.select()
  }, [])

  const saveValue = useAction((body: Parameters<typeof api.updateValue>[1]) =>
    cell ? api.updateValue(cell.id, body) : Promise.resolve(null),
  )
  const saveNew = useAction((body: Parameters<typeof api.createValue>[0]) =>
    api.createValue(body),
  )

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const parsed = parseAmount(amount)
    if ('error' in parsed) {
      setError(parsed.error)
      return
    }
    setError(null)

    if (mode === 'edit' && cell) {
      // Number.NaN is how parseAmount signals "clear the figure"; JSON.stringify
      // turns it into null, which is exactly what the API wants.
      void saveValue
        .run({ normalized_value: parsed.value, note: note.trim() || undefined })
        .then((res) => {
          if (res) onDone()
        })
      return
    }

    if (Number.isNaN(parsed.value)) {
      setError('Enter the figure to add.')
      return
    }
    if (documentId === null) {
      setError('Choose which report this figure belongs to.')
      return
    }
    void saveNew
      .run({
        document_id: documentId,
        field,
        year,
        normalized_value: parsed.value,
        note: note.trim() || undefined,
      })
      .then((res) => {
        if (res) onDone()
      })
  }

  const reverting =
    mode === 'edit' && cell?.is_edited && cell.original_value !== null
  const revert = useAction(() =>
    cell ? api.updateValue(cell.id, { revert: true }) : Promise.resolve(null),
  )

  const filename = documents.find((d) => d.id === documentId)?.filename

  return (
    <tr>
      <Td colSpan={colSpan} className="border-b border-border bg-muted/50">
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">
              {mode === 'edit' ? 'Correcting' : 'Adding'} {label}
            </span>{' '}
            for {company}
            {year ? ` ${year}` : ''}
            {mode === 'edit' && cell?.extraction_method === 'manual' && (
              <> — this figure was entered by hand, so there is no extractor's reading to revert to.</>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <Input
              ref={amountRef}
              label={mode === 'edit' ? 'Corrected amount (full rupiah)' : 'Amount (full rupiah)'}
              hint={
                mode === 'edit' && cell?.normalized_value != null
                  ? `Currently ${rupiah(cell.normalized_value)}. Clear the field to leave it empty.`
                  : undefined
              }
              className="tnum w-56 font-mono"
              inputMode="numeric"
              autoComplete="off"
              spellCheck={false}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value)
                setError(null)
              }}
              aria-invalid={error ? true : undefined}
              placeholder="e.g. 600000000"
            />

            {mode === 'add' && documents.length > 1 && (
              <Select
                label="Report"
                className="w-64"
                options={documents.map((d) => ({
                  value: String(d.id),
                  label: d.filename ?? `Document ${d.id}`,
                }))}
                value={documentId === null ? '' : String(documentId)}
                onChange={(e) => setDocumentId(Number(e.target.value))}
              />
            )}

            <Input
              label="Why (optional)"
              hint="Kept on the row so the change is auditable later."
              className="w-64"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. mis-scaled on the highlights page"
              maxLength={200}
            />
          </div>

          {error && (
            <Alert tone="danger" className="lg:max-w-3xl">
              {error}
            </Alert>
          )}
          {(saveValue.error || saveNew.error || revert.error) && (
            <ErrorBanner
              message={(saveValue.error || saveNew.error || revert.error) as string}
              onRetry={() => {
                saveValue.reset()
                saveNew.reset()
                revert.reset()
              }}
            />
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" size="sm" pending={saveValue.pending || saveNew.pending}>
              {mode === 'edit' ? 'Save correction' : 'Add figure'}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={onDone}>
              Cancel
            </Button>
            {reverting && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                pending={revert.pending}
                onClick={() =>
                  void revert.run().then((res) => {
                    if (res) onDone()
                  })
                }
              >
                Revert to {rupiah(cell?.original_value ?? null)}
              </Button>
            )}
            {mode === 'add' && filename && (
              <span className="text-xs text-muted-foreground">
                Filed under {filename}. Kept even if the report is processed again.
              </span>
            )}
          </div>
        </form>
      </Td>
    </tr>
  )
}

/**
 * Says out loud that most reports have not been read yet.
 *
 * The grid can only show rows that exist in the data, so a company whose PDFs
 * are still queued is absent from it. Without this notice that reads as "this
 * company has no financial data", which is a very different claim from "we
 * have not looked yet" -- and it is the reason a company can appear to be
 * missing from a report it does have.
 */
function CoverageNotice({ query }: { query: QueryState<ResultsCoverage> | null }) {
  const coverage = query ?? { data: null }
  const start = useAction(() => api.startProcessing({ action: 'process' }))
  const data = coverage.data
  if (!data || data.companies_without_values === 0) return null

  const { documents_with_values, documents_total } = data
  const queued = data.missing
    .flatMap((m) => Object.entries(m.by_status))
    .reduce<Record<string, number>>((acc, [status, n]) => {
      acc[status] = (acc[status] ?? 0) + n
      return acc
    }, {})
  const breakdown = Object.entries(queued)
    .sort((a, b) => b[1] - a[1])
    .map(([status, n]) => `${n} ${status.toLowerCase()}`)
    .join(', ')

  return (
    // Semantic tone tokens rather than fixed amber-50/amber-900: the latter are
    // light-mode colours and stay pale-on-pale under a dark theme.
    <div className="mt-4 rounded-lg border border-warning-soft bg-warning-soft p-3 text-sm text-warning-soft-foreground">
      <p className="font-semibold">
        Showing {data.companies_with_values} of {data.companies_discovered} companies
      </p>
      <p className="mt-1">
        {data.companies_without_values} companies have no figures yet because their
        reports have not been read: {documents_with_values} of {documents_total} documents
        produced data ({breakdown}). They are missing from the grid below because
        nothing has been extracted, not because the filings are absent.
      </p>
      {start.error && (
        <p className="mt-2 text-xs text-danger-soft-foreground">{start.error}</p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="primary"
          size="sm"
          pending={start.pending}
          onClick={() => start.run()}
        >
          {start.pending ? 'Starting...' : 'Process remaining documents'}
        </Button>
        {/* The dashboard is where batch progress lives; /processing is not a
            route, and linking to it landed on the not-found page. */}
        <Link
          to="/"
          className="text-xs font-medium underline underline-offset-2"
        >
          Watch progress on the dashboard
        </Link>
        <details>
          <summary className="cursor-pointer text-xs">
            Show the {data.companies_without_values} companies
          </summary>
          <ul className="mt-1 max-h-40 list-inside list-disc overflow-y-auto text-xs">
            {data.missing.map((m) => (
              <li key={m.company}>
                <Link
                  to={companyPath(m.company)}
                  className="underline underline-offset-2"
                >
                  {m.company}
                </Link>{' '}
                <span className="opacity-70">
                  ({m.documents} doc{m.documents === 1 ? '' : 's'})
                </span>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  )
}

/**
 * Per-company provenance: which reports the row came from, and which
 * accounting checks it failed.
 *
 * A grid of 41 numbers answers "what did you extract". It does not answer
 * "where did this come from" or "can I trust it" -- and those are the first
 * two questions anyone asks when a figure looks wrong. Without this the only
 * way to find out was to open every source PDF by hand.
 */
function CompanySources({
  colSpan,
  company,
  year,
  currency,
  documents,
  failed,
}: {
  colSpan: number
  company: string
  year: number | null
  currency: string | null
  documents: SummaryDocument[]
  failed: Record<string, string>
}) {
  const entries = Object.entries(failed)
  return (
    <tr>
      <Td colSpan={colSpan} className="bg-muted/30">
        <div className="grid gap-4 py-1 text-xs md:grid-cols-2">
          <div>
            <p className="font-semibold text-foreground">
              Source reports ({documents.length})
            </p>
            {documents.length === 0 ? (
              <p className="text-muted-foreground">
                No report is linked to these figures.
              </p>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {documents.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-baseline gap-2">
                    <Link
                      to={`/documents/${d.id}`}
                      className="font-medium text-primary underline-offset-2 hover:underline"
                    >
                      {d.filename ?? `Report ${d.id}`}
                    </Link>
                    {d.statements.length > 0 && (
                      <span className="text-muted-foreground">
                        {d.statements.map((s) => titleCase(s)).join(', ')}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-muted-foreground">
              Reporting currency: {currency ?? 'not stated'} &middot; figures are for{' '}
              {year ?? 'an undated report'}.
            </p>
          </div>

          <div>
            <p className="font-semibold text-foreground">
              Checks that did not hold ({entries.length})
            </p>
            {entries.length === 0 ? (
              <p className="text-muted-foreground">
                Every accounting identity the pipeline could test for this
                company-year held. Checks that could not be run are reported as
                &ldquo;not enough data&rdquo; and are not failures.
              </p>
            ) : (
              <>
                <p className="mt-1 text-muted-foreground">
                  These figures are known not to reconcile. At least one number
                  in each identity below is wrong; the checks cannot say which.
                </p>
                <ul className="mt-1 space-y-0.5">
                  {entries.map(([check, severity]) => (
                    <li key={check}>
                      <Badge tone={severity === 'ERROR' ? 'danger' : 'warning'}>
                        {severity ?? 'Warning'}
                      </Badge>{' '}
                      {titleCase(check)}
                    </li>
                  ))}
                </ul>
                <p className="mt-2">
                  <Link
                    to={`/validations?company=${encodeURIComponent(company)}`}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    See the full breakdown
                  </Link>
                </p>
              </>
            )}
          </div>
        </div>
      </Td>
    </tr>
  )
}

/**
 * Side-by-side readings of a figure the sources disagree about.
 *
 * Choosing one records it as a hand correction, which is what finally settles
 * it: a manual value outranks every extractor reading on the next load, and the
 * original stays in `original_value` for audit. Nothing is guessed here -- if
 * none of the readings is right, the reader types the figure instead.
 */
function DisputeChooser({
  colSpan,
  cell,
  company,
  year,
  label,
  documents,
  onDone,
}: {
  colSpan: number
  cell: SummaryCell | null | undefined
  company: string
  year: number | null
  label: string
  documents: SummaryDocument[]
  onDone: () => void
}) {
  const [picked, setPicked] = useState<SummaryCandidate | null>(null)
  const save = useAction((body: Parameters<typeof api.updateValue>[1]) =>
    api.updateValue(cell!.id, body),
  )
  const create = useAction((body: Parameters<typeof api.createValue>[0]) =>
    api.createValue(body),
  )
  const pending = save.pending || create.pending
  const error = save.error ?? create.error
  const candidates = cell?.candidates ?? []
  const where = `${label} for ${company}${year ? ` ${year}` : ''}`

  const accept = () => {
    if (picked) save.run({ normalized_value: picked.normalized_value }).then(onDone)
  }

  return (
    <tr>
      <Td colSpan={colSpan} className="bg-warning-soft">
        <div className="py-1 text-xs">
          <p className="font-semibold text-foreground">
            {candidates.length} readings of {where} disagree
          </p>
          <p className="mt-0.5 text-muted-foreground">
            The grid will not pick one for you. Higher extractor confidence
            does not mean more correct here -- on these statements the
            mis-scaled reading often scores higher. Choose the reading that
            matches the source, or close this and type the figure instead.
          </p>

          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[0.65rem] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1 pr-3 font-semibold">Value</th>
                  <th className="py-1 pr-3 font-semibold">Raw text</th>
                  <th className="py-1 pr-3 font-semibold">Report</th>
                  <th className="py-1 pr-3 font-semibold">Page</th>
                  <th className="py-1 pr-3 font-semibold">Confidence</th>
                  <th className="py-1 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => {
                  const doc = documents.find((d) => d.id === c.document_id)
                  return (
                    <tr
                      key={c.id}
                      className={
                        picked?.id === c.id ? 'bg-primary/10' : undefined
                      }
                    >
                      <td className="py-1 pr-3 font-mono text-sm font-semibold">
                        {rupiah(c.normalized_value)}
                      </td>
                      <td className="py-1 pr-3 font-mono text-muted-foreground">
                        {c.raw_value ?? '-'}
                        {c.unit ? ` (${c.unit})` : ''}
                      </td>
                      <td className="py-1 pr-3">
                        {doc?.filename ?? `Report ${c.document_id}`}
                      </td>
                      <td className="py-1 pr-3">{c.page ?? '-'}</td>
                      <td className="py-1 pr-3">
                        <Confidence value={c.confidence} />
                      </td>
                      <td className="py-1">
                        <button
                          type="button"
                          className="rounded-md border border-border px-2 py-0.5 font-medium hover:border-primary hover:bg-accent hover:text-primary"
                          onClick={() => setPicked(c)}
                        >
                          {picked?.id === c.id ? 'Selected' : 'Use this'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {error && (
            <p className="mt-2 text-red-700">
              {typeof error === 'string' ? error : 'Could not save.'}
            </p>
          )}

          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              disabled={!picked || pending}
              onClick={accept}
              className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground disabled:opacity-50"
            >
              {pending ? 'Saving...' : 'Accept this reading'}
            </button>
            <button
              type="button"
              onClick={onDone}
              className="text-muted-foreground underline-offset-2 hover:underline"
            >
              Close
            </button>
            {picked && (
              <span className="text-muted-foreground">
                Recorded as a hand correction, so it wins from now on and the
                extractor reading is kept for audit.
              </span>
            )}
          </div>
        </div>
      </Td>
    </tr>
  )
}

/**
 * Says what the batch is doing and offers the one thing that cannot be done
 * from the command line mid-run: stopping it.
 *
 * Job status arrives as a prop so the page and this banner cannot disagree about
 * whether a batch is running, and so only one poller watches it.
 */
function LiveProcessingBanner({
  job,
  onChanged,
}: {
  job: ProcessingState | null
  onChanged: () => void
}) {
  const stop = useAction(() => api.stopProcessing())
  const running = job?.running ?? false
  const [justStopped, setJustStopped] = useState(false)

  // Catch the transition so the banner can acknowledge a stop instead of
  // vanishing the instant running flips to false.
  const wasRunning = useRef(false)
  useEffect(() => {
    if (wasRunning.current && !running) {
      setJustStopped(true)
      onChanged()
    }
    wasRunning.current = running
    // onChanged is stable enough here: it only triggers refetches, and
    // depending on it would re-fire on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  if (!running && !justStopped) return null

  if (!running) {
    return (
      <Alert tone="info" className="mb-3">
        Batch stopped. Documents already being read finished and were saved;
        the rest are still queued.
        <button
          type="button"
          className="ml-2 underline underline-offset-2"
          onClick={() => setJustStopped(false)}
        >
          Dismiss
        </button>
      </Alert>
    )
  }

  const stopping = job?.cancel_requested === true

  return (
    <Alert tone="info" className="mb-3 flex items-center gap-3">
      <span className="flex-1">
        {stopping ? (
          <>
            <strong>Stopping...</strong> Documents already being read finish
            first, then the queue is dropped. Nothing is lost.
          </>
        ) : (
          <>
            <strong>Processing in the background.</strong> This grid updates as
            each report is read.
          </>
        )}
      </span>
      <Button
        type="button"
        variant="danger"
        size="sm"
        pending={stop.pending}
        disabled={stopping}
        onClick={() => stop.run()}
      >
        {stopping || stop.pending ? 'Stopping...' : 'Stop'}
      </Button>
    </Alert>
  )
}

/**
 * Download the grid as a workbook.
 *
 * A real link rather than a fetch-then-save: the browser owns the transfer, so
 * the filename comes from the response headers and a large export never depends
 * on a JS blob resolving first. The on-screen filters travel with it so the file
 * answers the question the table is answering; the page number deliberately does
 * not, because a download containing only the visible page is quietly wrong.
 */
function SummaryExport({
  params,
  rowCount,
}: {
  params: Record<string, string>
  rowCount: number
}) {
  const empty = rowCount === 0
  return (
    <ButtonLink
      // An anchor with no href is not focusable and cannot be activated, which
      // is what "disabled" has to mean for something styled as a button.
      href={empty ? undefined : api.summaryExportUrl(params)}
      variant="secondary"
      aria-disabled={empty || undefined}
      title={
        empty
          ? 'Nothing to export: no company-years match the current filters.'
          : `Download all ${num(rowCount)} rows as an .xlsx, every page, with a sheet explaining the blanks and the currencies`
      }
    >
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden
      >
        <path
          d="M12 3v11m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      Export to Excel
    </ButtonLink>
  )
}

function SummaryGrid({
  companies,
  globalCurrencies,
  setParam,
  values,
  years,
}: {
  companies: { company: string }[]
  globalCurrencies: { currency: string; count: number }[] | undefined
  setParam: (key: string, value: string) => void
  values: Record<string, string>
  years: string[]
}) {
  const page = Number(values.page || '1')
  // Which grid cell is open for editing, if any. Both states live here so only
  // one cell can ever be open, and Escape/row-render close it consistently.
  const [activeCell, setActiveCell] = useState<{
    row: string
    field: string
    mode: 'add' | 'edit' | 'dispute'
    cell: SummaryCell | null
    company: string
    year: number | null
  } | null>(null)
  // Which row has its source-detail panel open. One at a time: the panel is
  // tall, and stacking several makes the grid unreadable.
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  useEffect(() => {
    if (!activeCell) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActiveCell(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [activeCell])

  const summary = useQuery(
    () =>
      api.resultsSummary({
        company: values.company,
        year: values.year,
        currency: values.currency,
        page,
        page_size: PAGE_SIZE,
      }),
    [values.company, values.year, values.currency, page],
  )

  // The export takes the same filters as the grid, and not the page number: a
  // file that held only the rows on screen would be indistinguishable from the
  // whole answer unless the reader already knew to check.
  const exportParams = {
    company: values.company,
    year: values.year,
    currency: values.currency,
  }

  // The grid is the thing being built by a batch, so it polls while one runs.
  // Batch status comes from the app-wide context rather than a second poller of
  // its own, which would double the requests and could disagree with the
  // sidebar about whether a batch is running.
  const { state: job } = useProcessing()
  const processing = job?.running ?? false
  const refresh = summary.refetch
  useLiveRefresh(refresh, processing)
  const coverageQuery = useQuery(() => api.resultsCoverage(), [], {
    pollMs: processing ? 10000 : undefined,
  })

  const data = summary.data

  return (
    <>
      <LiveProcessingBanner job={job} onChanged={refresh} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:max-w-4xl">
        <Select
          label="Company"
          options={[
            { value: '', label: 'All companies' },
            ...companies.map((c) => ({ value: c.company, label: c.company })),
          ]}
          value={values.company}
          onChange={(e) => {
            setParam('company', e.target.value)
            setParam('page', '1')
          }}
        />
        <Select
          label="Year"
          options={[
            { value: '', label: 'All years' },
            ...years.map((y) => ({ value: y, label: y })),
          ]}
          value={values.year}
          onChange={(e) => {
            setParam('year', e.target.value)
            setParam('page', '1')
          }}
        />
        <Select
          label="Currency"
          hint="Reporting currency found in the source. 'Not detected' means no currency was found, not that it is rupiah."
          // Prefer the summary's own list, which only offers currencies the
          // displayed columns can match; fall back to the global facets so the
          // control is never empty.
          options={currencyOptions(data?.currencies ?? globalCurrencies)}
          value={values.currency}
          onChange={(e) => {
            setParam('currency', e.target.value)
            setParam('page', '1')
          }}
        />
      </div>

      {summary.error && (
        <div className="mt-4">
          <ErrorBanner message={summary.error} onRetry={summary.refetch} />
        </div>
      )}

      <div className="mt-4">
        <CoverageNotice query={coverageQuery} />
      </div>

      <div className="mt-4">
        {summary.initialLoading ? (
          <SkeletonTable rows={8} cols={6} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="No company-years match"
            hint="Adjust the filters, or process more documents from the dashboard."
          />
        ) : (
          <Card
            padded={false}
            subtitle={
              data
                ? `${num(data.pagination.total)} company-year${
                    data.pagination.total === 1 ? '' : 's'
                  } · ${data.fields.length} figure${data.fields.length === 1 ? '' : 's'}${
                    data.pagination.pages > 1
                      ? ` · page ${data.pagination.page} of ${data.pagination.pages}`
                      : ''
                  }`
                : undefined
            }
            actions={
              <SummaryExport
                params={exportParams}
                rowCount={data?.pagination.total ?? 0}
              />
            }
          >
            <Table caption="Results summary by company and year" stickyHeader>
              <thead>
                <tr>
                  {/* Pinned: the figure columns are what scroll off, and a
                      number with no company beside it cannot be read. The
                      background is restated because a sticky cell is lifted out
                      of the row's own background. */}
                  <Th className="sticky left-0 z-20 bg-muted">Company</Th>
                  <Th>Year</Th>
                  <Th hideBelow="lg">Currency</Th>
                  {data.fields.map((field, i) => (
                    <Th
                      key={field}
                      align="right"
                      // A rule between "who" and "how much", so the eye finds the
                      // edge of the identity block on a wide table.
                      className={i === 0 ? 'border-l border-border' : ''}
                    >
                      {data.labels[field] ?? titleCase(field)}
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((row, index) => {
                  const rowKey = `${row.company}-${row.year}`
                  // Alternating bands. Keyed to the row's position rather than
                  // an nth-child rule, because a row expands into extra <tr>s
                  // and CSS would start the striping mid-group.
                  const banded = index % 2 === 1
                  // `documents` is only present on a current backend; defaulting
                  // keeps the grid usable rather than throwing on an older one.
                  const rowDocuments = row.documents ?? []
                  const open =
                    activeCell !== null && activeCell.row === rowKey ? activeCell : null
                  // Identities the pipeline ran against this company-year that
                  // did not hold. Shown because a row whose own arithmetic
                  // fails must not be presented with the same confidence as one
                  // that reconciles -- the numbers are still there to read, but
                  // the reader is told they are known not to add up.
                  const failed = Object.keys(row.failed_checks ?? {})
                  // Per-company detail panel. A row of 41 numbers answers
                  // "what did you extract" but not "where did this come from",
                  // which is the first question anyone asks when a figure
                  // looks wrong.
                  const detailsOpen = expandedRow === rowKey

                  return (
                    <Fragment key={rowKey}>
                      <tr
                        className={`group transition-colors hover:bg-accent/40 ${
                          banded ? 'bg-muted/30' : ''
                        }`}
                      >
                        {/* Sticky for the same reason as its header, and given
                            the band's own background so figures scrolling
                            underneath do not show through it. */}
                        <Td
                          className={`sticky left-0 z-10 max-w-56 border-r text-xs group-hover:bg-accent/40 ${
                            banded ? 'bg-muted/95' : 'bg-card'
                          }`}
                        >
                          <div className="flex items-start gap-1">
                            <button
                              type="button"
                              className="mt-0.5 shrink-0 rounded text-muted-foreground hover:text-foreground"
                              aria-expanded={detailsOpen}
                              title="Source documents and checks for this company"
                              onClick={() =>
                                setExpandedRow(detailsOpen ? null : rowKey)
                              }
                            >
                              {detailsOpen ? '▾' : '▸'}
                            </button>
                            <div className="min-w-0">
                              {/* The name opens the company profile, which is the
                                  "what do we have for this one" view; the caret
                                  beside it stays the per-row provenance panel. */}
                              <Link
                                to={companyPath(row.company)}
                                className="block truncate font-medium text-foreground underline-offset-2 hover:underline"
                                title={`Open the profile for ${row.company}`}
                              >
                                {row.company}
                              </Link>
                              {failed.length > 0 && (
                                <span
                                  className="mt-0.5 block cursor-help"
                                  title={`These figures do not reconcile: ${failed
                                    .map((c) => titleCase(c))
                                    .join(', ')}. The pipeline ran these checks and they did not hold.`}
                                >
                                  <Badge tone="danger">
                                    {failed.length} check{failed.length === 1 ? '' : 's'} failed
                                  </Badge>
                                </span>
                              )}
                            </div>
                          </div>
                        </Td>
                        <Td mono>{row.year ?? '-'}</Td>
                        <Td hideBelow="lg" className="text-xs">
                          {row.currency === null ? (
                            <span className="text-muted-foreground/60">&mdash;</span>
                          ) : row.currency === 'Mixed' ? (
                            <Badge tone="warning">Mixed</Badge>
                          ) : row.currency === 'Not detected' ? (
                            <span
                              className="text-muted-foreground"
                              title="No currency was found in the source for these figures."
                            >
                              Not detected
                            </span>
                          ) : (
                            <span title={currencyLabel(row.currency)}>
                              {currencyLabel(row.currency)}
                            </span>
                          )}
                        </Td>
                        {data.fields.map((field, i) => {
                          const cell = row.cells[field] ?? null
                          return (
                            <GridCell
                              key={field}
                              cell={cell}
                              label={data.labels[field] ?? titleCase(field)}
                              company={row.company}
                              year={row.year}
                              canAdd={rowDocuments.length > 0}
                              className={i === 0 ? 'border-l border-border' : ''}
                              onEdit={() =>
                                setActiveCell({
                                  row: rowKey,
                                  field,
                                  mode: cell?.disputed ? 'dispute' : 'edit',
                                  cell,
                                  company: row.company,
                                  year: row.year,
                                })
                              }
                              onAdd={() =>
                                setActiveCell({
                                  row: rowKey,
                                  field,
                                  mode: 'add',
                                  cell: null,
                                  company: row.company,
                                  year: row.year,
                                })
                              }
                            />
                          )
                        })}
                      </tr>
                      {detailsOpen && (
                        <CompanySources
                          colSpan={3 + data.fields.length}
                          company={row.company}
                          year={row.year}
                          currency={row.currency}
                          documents={rowDocuments}
                          failed={row.failed_checks ?? {}}
                        />
                      )}
                      {open !== null &&
                        (open.mode === 'dispute' ? (
                          <DisputeChooser
                            colSpan={3 + data.fields.length}
                            cell={open.cell}
                            company={open.company}
                            year={open.year}
                            label={data.labels[open.field] ?? titleCase(open.field)}
                            documents={rowDocuments}
                            onDone={() => {
                              setActiveCell(null)
                              void summary.refetch()
                            }}
                          />
                        ) : (
                          <CellForm
                            cell={open.cell}
                            mode={open.mode}
                            colSpan={3 + data.fields.length}
                            company={open.company}
                            year={open.year}
                            field={open.field}
                            label={data.labels[open.field] ?? titleCase(open.field)}
                            documents={rowDocuments}
                            onDone={() => {
                              setActiveCell(null)
                              void summary.refetch()
                            }}
                          />
                        ))}
                    </Fragment>
                  )
                })}
              </tbody>
            </Table>
            <Pagination
              page={data.pagination.page}
              pages={data.pagination.pages}
              total={data.pagination.total}
              pageSize={data.pagination.page_size}
              onPage={(p) => setParam('page', String(p))}
            />
          </Card>
        )}
      </div>
    </>
  )
}

export default function Results() {
  const { get, setParam, clearAll, values, activeCount } = useUrlFilters(FILTER_KEYS)
  const view = (get('view') || 'summary') as View
  const page = Number(get('page') || '1')
  const debouncedSearch = useDebounced(get('search'))

  const facets = useQuery(() => api.valueFacets(), [])
  const companies = useQuery(() => api.companies(), [])

  const sort = (get('sort') || 'company') as SortKey
  const order = (get('order') || 'asc') as 'asc' | 'desc'

  const params = useMemo(
    () => ({
      search: debouncedSearch,
      company: values.company,
      year: values.year,
      statement: values.statement,
      field: values.field,
      status: values.status,
      currency: values.currency,
      sort,
      order,
      page,
      page_size: PAGE_SIZE,
    }),
    [values, debouncedSearch, sort, order, page],
  )

  // The list view is only fetched when it is on screen: the summary grid is the
  // landing view, and 877 rows of values behind it are not worth the round trip.
  const { data, error, initialLoading, refetch } = useQuery(
    () => (view === 'values' ? api.values(params) : Promise.resolve(null)),
    [JSON.stringify(params), view],
  )

  const [patched, setPatched] = useState<Record<number, ExtractedValue>>({})
  const applyServerRow = useCallback(
    (row: ExtractedValue) => setPatched((prev) => ({ ...prev, [row.id]: row })),
    [],
  )

  // Only patches for rows on this page are consulted, so entries left behind
  // by earlier pages are inert rather than stale data on screen.
  const rows = useMemo(() => {
    const items = data?.items ?? []
    return items.map((v) => patched[v.id] ?? v)
  }, [data, patched])

  const [editingId, setEditingId] = useState<number | null>(null)
  // A correction writes to a row this table owns, so the server's copy of just
  // that row is patched in. A refetch would also work, but it throws away
  // scroll position and re-queries every active filter.
  const afterEdit = useCallback(
    (row: ExtractedValue) => {
      applyServerRow(row)
      setEditingId(null)
    },
    [applyServerRow],
  )

  const applySort = (key: SortKey) => {
    setParam('sort', key)
    setParam('order', sort === key && order === 'asc' ? 'desc' : 'asc')
    setParam('page', '1')
  }

  const statementOptions = [
    { value: '', label: 'All statements' },
    ...(facets.data?.statements ?? []).map((s) => ({
      value: s.statement,
      label: titleCase(s.statement),
      count: s.count,
    })),
  ]

  const fieldOptions = [
    { value: '', label: 'All fields' },
    ...(facets.data?.fields ?? []).map((f) => ({
      value: f.field,
      label: titleCase(f.field),
      count: f.count,
    })),
  ]

  const yearOptions = [
    { value: '', label: 'All years' },
    ...(facets.data?.years ?? []).map((y) => ({ value: String(y), label: String(y) })),
  ]

  const companyOptions = [
    { value: '', label: 'All companies' },
    ...(companies.data?.items ?? []).map((c) => ({ value: c.company, label: c.company })),
  ]

  const editedCount = rows.filter((r) => r.is_edited).length

  return (
    <>
      <PageHeader
        title="Results"
        subtitle="Headline figures per company-year, and every extracted value behind them. Click any amount to correct it."
      />

      <Tabs
        className="mb-4"
        tabs={[
          { key: 'summary' as View, label: 'Summary' },
          { key: 'values' as View, label: 'All values' },
        ]}
        active={view}
        onChange={(key) => setParam('view', key)}
      />

      <Alert tone="info" className="mb-4">
        Corrections keep the extractor&apos;s original reading alongside them, and{' '}
        <strong>Revert</strong> puts it back. Corrections survive re-processing,
        but a document&apos;s validation checks are not recomputed automatically.
      </Alert>

      {view === 'summary' ? (
        <SummaryGrid
          companies={companies.data?.items ?? []}
          globalCurrencies={facets.data?.currencies}
          setParam={setParam}
          values={values}
          years={(facets.data?.years ?? []).map(String)}
        />
      ) : (
        <>
          <Card className="mb-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              <Input
                label="Search"
                placeholder="Field, label or company"
                value={get('search')}
                onChange={(e) => setParam('search', e.target.value)}
              />
              <Select
                label="Company"
                options={companyOptions}
                value={values.company}
                onChange={(e) => setParam('company', e.target.value)}
              />
              <Select
                label="Year"
                options={yearOptions}
                value={values.year}
                onChange={(e) => setParam('year', e.target.value)}
              />
              <Select
                label="Statement"
                options={statementOptions}
                value={values.statement}
                onChange={(e) => setParam('statement', e.target.value)}
              />
              <Select
                label="Field"
                options={fieldOptions}
                value={values.field}
                onChange={(e) => setParam('field', e.target.value)}
              />
              <Select
                label="Status"
                options={STATUS_OPTIONS}
                value={values.status}
                onChange={(e) => setParam('status', e.target.value)}
              />
              <Select
                label="Currency"
                options={currencyOptions(facets.data?.currencies)}
                value={values.currency}
                onChange={(e) => setParam('currency', e.target.value)}
              />
            </div>
            {activeCount > 0 && (
              <div className="mt-4 flex items-center border-t border-border pt-3">
                <Button size="sm" variant="ghost" onClick={clearAll}>
                  Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
                </Button>
              </div>
            )}
          </Card>

          {error && <ErrorBanner message={error} onRetry={refetch} />}

          <Card padded={false}>
            {initialLoading ? (
              <div className="p-4">
                <SkeletonTable rows={10} cols={7} />
              </div>
            ) : rows.length === 0 ? (
              <EmptyState
                title="No results match"
                hint="Adjust the filters, or process more documents from the dashboard."
              />
            ) : (
              <>
                <Table caption="Extracted result values">
                  <thead>
                    <tr>
                      <Th
                        onSort={() => applySort('company')}
                        sorted={sort === 'company' ? order : false}
                      >
                        Company
                      </Th>
                      <Th hideBelow="sm" onSort={() => applySort('year')} sorted={sort === 'year' ? order : false}>
                        Year
                      </Th>
                      <Th onSort={() => applySort('field')}>Field</Th>
                      <Th
                        hideBelow="md"
                        onSort={() => applySort('value')}
                        sorted={sort === 'value' ? order : false}
                      >
                        Value
                      </Th>
                      <Th hideBelow="lg">Source</Th>
                      <Th
                        hideBelow="xl"
                        onSort={() => applySort('confidence')}
                        sorted={sort === 'confidence' ? order : false}
                      >
                        Confidence
                      </Th>
                      <Th hideBelow="lg">Status</Th>
                      <Th align="right">Correct</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((v) => {
                      const open = editingId === v.id
                      return (
                        <Fragment key={v.id}>
                          <tr className="transition-colors hover:bg-accent/40">
                            <Td className="max-w-48 text-xs">
                              <Link
                                to={`/documents/${v.document_id}`}
                                className="block truncate font-medium text-foreground hover:text-primary hover:underline"
                                title={v.company}
                              >
                                {v.company}
                              </Link>
                            </Td>
                            <Td hideBelow="sm" mono>
                              {v.year ?? '-'}
                            </Td>
                            <Td className="max-w-56 text-xs">
                              <span className="block truncate font-medium text-foreground" title={v.field}>
                                {titleCase(v.field)}
                              </span>
                              {v.edit_note && (
                                <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={v.edit_note}>
                                  {v.edit_note}
                                </span>
                              )}
                            </Td>
                            <Td hideBelow="md" align="right">
                              <button
                                type="button"
                                onClick={() => setEditingId(open ? null : v.id)}
                                aria-expanded={open}
                                title="Correct this value"
                                className="tnum -mr-1 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 font-mono text-sm font-semibold text-foreground hover:bg-accent hover:text-primary"
                              >
                                {rupiah(v.normalized_value)}
                                <svg
                                  viewBox="0 0 24 24"
                                  className="h-3 w-3 shrink-0 text-muted-foreground"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="2"
                                  aria-hidden
                                >
                                  <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z" strokeLinejoin="round" />
                                </svg>
                              </button>
                              {v.is_edited && (
                                <Badge tone="accent" className="mt-1">
                                  Edited
                                </Badge>
                              )}
                            </Td>
                            <Td hideBelow="lg" className="max-w-52 text-xs">
                              <span className="block truncate text-muted-foreground" title={v.raw_label ?? undefined}>
                                {v.raw_label ?? '-'}
                              </span>
                              <span className="mt-0.5 block text-xs text-muted-foreground/80">
                                p{v.page ?? '-'} &middot; {titleCase(v.statement)}
                              </span>
                            </Td>
                            <Td hideBelow="xl">
                              <Confidence value={v.confidence} />
                            </Td>
                            <Td hideBelow="lg">
                              <ValueStatusBadge status={v.status} />
                            </Td>
                            <Td align="right">
                              {v.is_edited ? (
                                <RevertButton value={v} onDone={afterEdit} />
                              ) : (
                                <Button size="sm" variant="ghost" onClick={() => setEditingId(v.id)}>
                                  Edit
                                </Button>
                              )}
                            </Td>
                          </tr>
                          {open && <EditRow value={v} onDone={afterEdit} />}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </Table>

                <Pagination
                  page={data!.pagination.page}
                  pages={data!.pagination.pages}
                  total={data!.pagination.total}
                  pageSize={data!.pagination.page_size}
                  onPage={(p) => setParam('page', String(p))}
                />
              </>
            )}
          </Card>

          {editedCount > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">
              {num(editedCount)} value{editedCount === 1 ? '' : 's'} on this page{' '}
              {editedCount === 1 ? 'has' : 'have'} been corrected.
            </p>
          )}
        </>
      )}
    </>
  )
}
