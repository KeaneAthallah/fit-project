import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAction, useLiveRefresh, useQuery } from '../hooks/useQuery'
import type { QueryState } from '../hooks/useQuery'
import { useProcessing } from '../lib/processing-context'
import { useUrlFilters } from '../hooks/useFilters'
import { currencyLabel, currencyOptions, formatDateID, rupiah, titleCase } from '../lib/format'
import { fieldLabel } from '../lib/field-labels'
import { companyPath } from '../lib/paths'
import { results as s } from '../lib/strings'
import type {
  ProcessingState,
  ResultsCoverage,
  SummaryCandidate,
  SummaryCell,
  SummaryDocument,
} from '../lib/types'
import { Confidence } from '../components/badges'
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  MultiSelect,
  PageHeader,
  Pagination,
  Select,
  SkeletonTable,
  Table,
  Td,
  Th,
} from '../components/ui'

const FILTER_KEYS = ['company', 'year', 'currency', 'subsector', 'profitable', 'pencatatan', 'page'] as const

// The keys that are genuinely filters. `page` is pagination rather than a
// filter, so counting it would tell the reader they have a filter applied when
// they have not, and "Clear N filters" would throw away their place in the
// results along with the filters.
const CLEARABLE_KEYS = ['company', 'year', 'currency', 'subsector', 'profitable', 'pencatatan'] as const

// The sub-sector filter holds several classifications at once, so it travels
// as repeated URL parameters rather than one joined string.
const MULTI_KEYS = ['subsector'] as const

const PAGE_SIZE = 50

/**
 * Accepts a plain number and tolerates thousands separators.
 *
 * Deliberately NOT locale-aware: the stored figures are raw rupiah, and a
 * guess at whether "1.500.000" means one and a half million or fifteen hundred
 * million is exactly the kind of ambiguity a financial field must not have.
 * Anything else is rejected rather than guessed.
 *
 * A decimal part is allowed and required to be there when the stored figure has
 * one: the extractor keeps every digit it read, so `31635083104.74` is a real
 * row that has to be correctable, not just readable.
 */
function parseAmount(input: string): { value: number } | { error: string } {
  const trimmed = input.trim()
  // Empty means "this figure is not present", which the API models as null.
  // It is deliberately not the same as zero.
  if (trimmed === '') return { value: Number.NaN }
  if (!/^-?[0-9][0-9,]*(\.[0-9]+)?$/.test(trimmed)) {
    return {
      error: 'Masukkan angka saja, dengan bagian desimal opsional. Koma mengelompokkan ribuan.',
    }
  }
  const value = Number(trimmed.replace(/,/g, ''))
  // Magnitude rather than `isSafeInteger`, which would reject the fractional
  // figures this field exists to correct. The API stores `int | float`, and a
  // value past MAX_SAFE_INTEGER has already lost the digits that matter.
  if (!Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER) {
    return { error: 'Angka itu terlalu besar untuk disimpan dengan aman.' }
  }
  return { value }
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
  const where = `${label} untuk ${company}${year ? ` ${year}` : ''}`
  // Figures never wrap: a broken amount is read as a different amount.
  const base = `whitespace-nowrap ${className}`

  if (!cell) {
    if (!canAdd) {
      return (
        <Td align="right" className={`tnum text-muted-foreground/40 ${base}`} title={`Tidak ada ${label} yang ditemukan`}>
          &mdash;
        </Td>
      )
    }
    return (
      <Td align="right" className={base}>
        <button
          type="button"
          onClick={onAdd}
          title={`Tambah ${where}`}
          aria-label={`Tambah ${where}`}
          className="tnum group inline-flex items-center gap-1 rounded-md border border-dashed border-border px-1.5 py-0.5 text-sm text-muted-foreground/70 transition-colors hover:border-primary hover:bg-accent hover:text-primary"
        >
          <span aria-hidden className="text-xs leading-none">
            +
          </span>
          <span className="text-[0.65rem] font-sans font-semibold uppercase tracking-wide">
            tambah
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
        title={`Ubah ${where}`}
        aria-label={`Ubah ${where}`}
        className="tnum -mr-1 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 font-mono text-sm font-semibold text-foreground hover:bg-accent hover:text-primary"
      >
        {rupiah(cell.normalized_value)}
        {cell.is_edited && (
          <span className="rounded bg-accent px-1 text-[0.6rem] font-sans font-semibold uppercase tracking-wide text-accent-foreground">
            diubah
          </span>
        )}
        {cell.disputed && (
          <span
            className="rounded bg-danger-soft px-1 text-[0.6rem] font-sans font-bold uppercase tracking-wide text-danger-soft-foreground"
            title="Dua pembacaan angka ini tidak sepakat. Klik untuk membandingkannya."
          >
            dipersengketakan
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
      setError('Masukkan angka yang ditambahkan.')
      return
    }
    if (documentId === null) {
      setError('Pilih laporan angka ini berasal.')
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
              {mode === 'edit' ? 'Mengoreksi' : 'Menambahkan'} {label}
            </span>{' '}
            untuk {company}
            {year ? ` ${year}` : ''}
            {mode === 'edit' && cell?.extraction_method === 'manual' && (
              <>{s.editor.addManualNote}</>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <Input
              ref={amountRef}
              label={s.editor.amountLabel(mode)}
              hint={
                mode === 'edit' && cell?.normalized_value != null
                  ? s.editor.currentHint(rupiah(cell.normalized_value))
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
                label={s.editor.report}
                className="w-64"
                options={documents.map((d) => ({
                  value: String(d.id),
                  label: d.filename ?? s.editor.documentFallback(d.id),
                }))}
                value={documentId === null ? '' : String(documentId)}
                onChange={(e) => setDocumentId(Number(e.target.value))}
              />
            )}

            <Input
              label={s.editor.reason}
              hint={s.editor.reasonHint}
              className="w-64"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={s.editor.reasonPlaceholder}
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
              {s.editor.save(mode)}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={onDone}>
              Batal
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
                {s.editor.revertTo(rupiah(cell?.original_value ?? null))}
              </Button>
            )}
            {mode === 'add' && filename && (
              <span className="text-xs text-muted-foreground">
                {s.editor.filedUnder(filename)}
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
        {s.coverage.showing(data.companies_with_values, data.companies_discovered)}
      </p>
      <p className="mt-1">
        {s.coverage.missing(
          data.companies_without_values,
          documents_with_values,
          documents_total,
          breakdown,
        )}
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
          {start.pending ? s.coverage.starting : s.coverage.processRemaining}
        </Button>
        {/* The dashboard is where batch progress lives; /processing is not a
            route, and linking to it landed on the not-found page. */}
        <Link
          to="/"
          className="text-xs font-medium underline underline-offset-2"
        >
          {s.coverage.watchProgress}
        </Link>
        <details>
          <summary className="cursor-pointer text-xs">
            {s.coverage.showCompanies(data.companies_without_values)}
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
                  ({s.coverage.docs(m.documents)})
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
              {s.sources.title(documents.length)}
            </p>
            {documents.length === 0 ? (
              <p className="text-muted-foreground">{s.sources.none}</p>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {documents.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-baseline gap-2">
                    <Link
                      to={`/documents/${d.id}`}
                      className="font-medium text-primary underline-offset-2 hover:underline"
                    >
                      {d.filename ?? s.sources.reportFallback(d.id)}
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
              {s.sources.currencyLine(
                currency ?? s.sources.notStated,
                year !== null ? String(year) : s.sources.undated,
              )}
            </p>
          </div>

          <div>
            <p className="font-semibold text-foreground">
              {s.sources.checksTitle(entries.length)}
            </p>
            {entries.length === 0 ? (
              <p className="text-muted-foreground">{s.sources.allHeld}</p>
            ) : (
              <>
                <p className="mt-1 text-muted-foreground">
                  {s.sources.notReconciled}
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
  const where = `${label} untuk ${company}${year ? ` ${year}` : ''}`

  const accept = () => {
    if (picked) save.run({ normalized_value: picked.normalized_value }).then(onDone)
  }

  return (
    <tr>
      <Td colSpan={colSpan} className="bg-warning-soft">
        <div className="py-1 text-xs">
          <p className="font-semibold text-foreground">
            {s.dispute.title(candidates.length, where)}
          </p>
          <p className="mt-0.5 text-muted-foreground">{s.dispute.hint}</p>

          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[0.65rem] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1 pr-3 font-semibold">{s.dispute.value}</th>
                  <th className="py-1 pr-3 font-semibold">{s.dispute.rawText}</th>
                  <th className="py-1 pr-3 font-semibold">{s.dispute.report}</th>
                  <th className="py-1 pr-3 font-semibold">{s.dispute.page}</th>
                  <th className="py-1 pr-3 font-semibold">
                    {s.dispute.confidence}
                  </th>
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
                          {picked?.id === c.id ? s.dispute.selected : s.dispute.useThis}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {error && (
            <p className="mt-2 text-xs text-danger-soft-foreground">
              {typeof error === 'string' ? error : s.dispute.couldNotSave}
            </p>
          )}

          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              disabled={!picked || pending}
              onClick={accept}
              className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground disabled:opacity-50"
            >
              {pending ? s.dispute.saving : s.dispute.accept}
            </button>
            <button
              type="button"
              onClick={onDone}
              className="text-muted-foreground underline-offset-2 hover:underline"
            >
              {s.dispute.close}
            </button>
            {picked && (
              <span className="text-muted-foreground">
                {s.dispute.recordedAsManual}
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
        {s.processing.stopped}
        <button
          type="button"
          className="ml-2 underline underline-offset-2"
          onClick={() => setJustStopped(false)}
        >
          {s.processing.dismiss}
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
            <strong>{s.processing.stopping}</strong> {s.processing.stoppingHint}
          </>
        ) : (
          <>
            <strong>{s.processing.running}</strong> {s.processing.runningHint}
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
        {stopping || stop.pending ? s.processing.stopping : s.processing.stop}
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
  params: Record<string, string | string[]>
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
          ? s.grid.exportNothingTitle
          : s.grid.exportTitle(rowCount)
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
      {s.grid.export}
    </ButtonLink>
  )
}

function SummaryGrid({
  companies,
  globalCurrencies,
  selectedSubsectors,
  setParam,
  values,
  years,
}: {
  companies: { company: string }[]
  globalCurrencies: { currency: string; count: number }[] | undefined
  /** The sub-sector classifications in force, from the repeated URL
   *  parameters. A company has one classification, but the reader may
   *  want several of them on screen at once. */
  selectedSubsectors: string[]
  setParam: (key: string, value: string | string[]) => void
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

  // The profit filter is a dropdown now: 'laba' or 'rugi'. A link
  // saved while it was still a checkbox carries the literal 'true',
  // which meant laba -- it keeps its meaning rather than silently
  // becoming "no filter". Anything else a hand-edited link might
  // carry reads as off, so the control and the request can never
  // disagree about whether the filter is applied.
  const profitMode =
    values.profitable === 'true'
      ? 'laba'
      : values.profitable === 'laba' || values.profitable === 'rugi'
        ? values.profitable
        : ''
  // The hint describes the choice in force rather than the control,
  // so a reader sees what the current answer means.
  const profitHint =
    profitMode === 'laba'
      ? s.grid.noNetLossHint
      : profitMode === 'rugi'
        ? s.grid.lossOnlyHint
        : s.grid.profitFilterHint

  // The listing-date filter narrows to companies whose shares were
  // recorded before a year. The register is the source of truth: a
  // company it does not know has no date, and an unknown is not a
  // "before 2020".
  const pencatatan = values.pencatatan

  const summary = useQuery(
    () =>
      api.resultsSummary({
        company: values.company,
        year: values.year,
        currency: values.currency,
        subsector: selectedSubsectors,
        profitable: profitMode,
        pencatatan_before: pencatatan,
        page,
        page_size: PAGE_SIZE,
      }),
    // The filters are the dependencies: leaving any out would let the
    // URL change without the grid noticing.
    [values.company, values.year, values.currency, selectedSubsectors, profitMode, pencatatan, page],
  )

  // The export takes the same filters as the grid, and not the page number: a
  // file that held only the visible page would be indistinguishable from the
  // whole answer unless the reader already knew to check.
  const exportParams = {
    company: values.company,
    year: values.year,
    currency: values.currency,
    subsector: selectedSubsectors,
    profitable: profitMode,
    pencatatan_before: pencatatan,
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
          label={s.grid.company}
          options={[
            { value: '', label: s.grid.allCompanies },
            ...companies.map((c) => ({ value: c.company, label: c.company })),
          ]}
          value={values.company}
          onChange={(e) => setParam('company', e.target.value)}
        />
        <Select
          label={s.grid.year}
          options={[
            { value: '', label: s.grid.allYears },
            ...years.map((y) => ({ value: y, label: y })),
          ]}
          value={values.year}
          onChange={(e) => setParam('year', e.target.value)}
        />
        <Select
          label={s.grid.currency}
          hint={s.grid.currencyHint}
          // Prefer the summary's own list, which only offers currencies the
          // displayed columns can match; fall back to the global facets so the
          // control is never empty.
          options={currencyOptions(data?.currencies ?? globalCurrencies, values.currency)}
          value={values.currency}
          onChange={(e) => setParam('currency', e.target.value)}
        />
        {/* The classification is one per company but pickable several
            at once, so it is a multi-select rather than a dropdown
            of one. The list comes from the summary's own response,
            scoped the way the currency control is: only the sectors
            the other filters can still reach. The server keeps a
            selection the filters have emptied in the list at a count
            of zero, so a ticked option never vanishes while the query
            is still narrowed by it. */}
        <MultiSelect
          label={s.grid.subsector}
          hint={s.grid.subsectorHint}
          placeholder={s.grid.allSubsectors}
          options={(data?.subsectors ?? []).map((sub) => ({
            value: sub.subsector,
            label:
              sub.subsector === 'none'
                ? s.grid.noSubsectorDeclared
                : sub.subsector,
            count: sub.count,
          }))}
          values={selectedSubsectors}
          onChange={(picked) => setParam('subsector', picked)}
        />
        {/* "Laba terus"/"Rugi terus" are claims about the bottom
            line rather than a column: the server keeps the
            company-years whose net result points the chosen way
            whether or not the profit column is on screen, and
            drops the rest -- including years with no profit figure
            at all, because a missing number is evidence of neither. */}
        <Select
          label={s.grid.profitFilter}
          hint={profitHint}
          options={[
            { value: '', label: s.grid.allProfit },
            { value: 'laba', label: s.grid.noNetLoss },
            { value: 'rugi', label: s.grid.lossOnly },
          ]}
          value={profitMode}
          onChange={(e) => setParam('profitable', e.target.value)}
        />
        {/* The listing date is a property of the company, not
            of the year, so this filter narrows whole companies:
            a share listed in 2022 cannot honestly report a 2019
            figure. A company the register does not know has no
            date to judge by and leaves with them. */}
        <Select
          label={s.grid.pencatatan}
          hint={s.grid.pencatatanHint}
          options={[
            { value: '', label: s.grid.allPencatatan },
            { value: '2020', label: s.grid.before2020 },
          ]}
          value={pencatatan}
          onChange={(e) => setParam('pencatatan', e.target.value)}
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
            title={s.grid.noMatchTitle}
            hint={s.grid.noMatchHint}
          />
        ) : (
          <Card
            padded={false}
            subtitle={
              data
                ? s.grid.summary(
                    data.pagination.total,
                    data.fields.length,
                    data.pagination.page,
                    data.pagination.pages,
                  )
                : undefined
            }
            actions={
              <SummaryExport
                params={exportParams}
                rowCount={data?.pagination.total ?? 0}
              />
            }
          >
            <Table caption={s.grid.caption} stickyHeader>
              <thead>
                <tr>
                  {/* Pinned: the figure columns are what scroll off, and a
                      number with no company beside it cannot be read. The
                      background is restated because a sticky cell is lifted out
                      of the row's own background. */}
                  <Th className="sticky left-0 z-20 bg-muted">
                    {s.grid.company}
                  </Th>
                  <Th>{s.grid.year}</Th>
                  <Th hideBelow="lg">{s.grid.currency}</Th>
                  <Th>{s.grid.subsector}</Th>
                  <Th hideBelow="lg">{s.grid.pencatatan}</Th>
                  {data.fields.map((field, i) => (
                    <Th
                      key={field}
                      align="right"
                      // A rule between "who" and "how much", so the eye finds the
                      // edge of the identity block on a wide table.
                      className={i === 0 ? 'border-l border-border' : ''}
                    >
                      {fieldLabel(field, data.labels[field])}
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
                              title={s.grid.sourceDetailsTitle}
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
                                title={s.grid.openProfile(row.company)}
                              >
                                {row.company}
                              </Link>
                              {failed.length > 0 && (
                                <span
                                  className="mt-0.5 block cursor-help"
                                  title={s.grid.notReconciling(
                                    failed
                                      .map((c) => titleCase(c))
                                      .join(', '),
                                  )}
                                >
                                  <Badge tone="danger">
                                    {s.grid.checksFailed(failed.length)}
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
                            <Badge tone="warning">{s.grid.mixed}</Badge>
                          ) : row.currency === 'Not detected' ? (
                            <span
                              className="text-muted-foreground"
                              title={s.grid.notDetectedHint}
                            >
                              {s.grid.notDetected}
                            </span>
                          ) : (
                            <span title={currencyLabel(row.currency)}>
                              {currencyLabel(row.currency)}
                            </span>
                          )}
                        </Td>
                        {/* The declared sub-sector is a sentence, not a figure, so
                            it gets its own thin column: a reader glancing at a
                            row can see at a glance which business the numbers
                            belong to. */}
                        <Td hideBelow="lg" className="text-xs">
                          <span className="text-muted-foreground">
                            {row.subsector || '—'}
                          </span>
                        </Td>
                        {/* The listing date is an identity of the
                            company, so it sits with the other
                            identity columns; a company the register
                            does not know shows an em dash, never a
                            guessed date. */}
                        <Td hideBelow="lg" className="text-xs">
                          <span className="text-muted-foreground">
                            {formatDateID(row.pencatatan) || '—'}
                          </span>
                        </Td>
                        {data.fields.map((field, i) => {
                          const cell = row.cells[field] ?? null
                          return (
                            <GridCell
                              key={field}
                              cell={cell}
                              label={fieldLabel(field, data.labels[field])}
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
                          colSpan={4 + data.fields.length}
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
                            // Keyed by the cell it is editing. Without this the two
                            // editors share one slot in this row, so opening a
                            // second figure in the same row would reuse the open
                            // instance and keep its amount, note and selection
                            // while `cell` had already moved on -- and saving would
                            // then write one figure's value over another.
                            key={`dispute:${rowKey}:${open.field}`}
                            colSpan={4 + data.fields.length}
                            cell={open.cell}
                            company={open.company}
                            year={open.year}
                            label={fieldLabel(open.field, data.labels[open.field])}
                            documents={rowDocuments}
                            onDone={() => {
                              setActiveCell(null)
                              void summary.refetch()
                            }}
                          />
                        ) : (
                          <CellForm
                            key={`edit:${rowKey}:${open.field}`}
                            cell={open.cell}
                            mode={open.mode}
                            colSpan={4 + data.fields.length}
                            company={open.company}
                            year={open.year}
                            field={open.field}
                            label={fieldLabel(open.field, data.labels[open.field])}
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
  const { setParam, clearAll, values, multiValues, activeCount } = useUrlFilters(
    FILTER_KEYS,
    { clearable: CLEARABLE_KEYS, multi: MULTI_KEYS },
  )
  const facets = useQuery(() => api.valueFacets(), [])
  const companies = useQuery(() => api.companies(), [])

  return (
    <>
      <PageHeader
        title={s.title}
        subtitle={s.subtitle}
      />

      <Alert tone="info" className="mb-4">
        {s.correctionsNote.lead}{' '}
        <strong>{s.correctionsNote.revert}</strong> {s.correctionsNote.tail}
      </Alert>

      {activeCount > 0 && (
        <div className="mb-3 flex justify-end">
          <Button size="sm" variant="ghost" onClick={clearAll}>
            {s.clearFilters(activeCount)}
          </Button>
        </div>
      )}

      <SummaryGrid
        companies={companies.data?.items ?? []}
        globalCurrencies={facets.data?.currencies}
        selectedSubsectors={multiValues.subsector ?? []}
        setParam={setParam}
        values={values}
        years={(facets.data?.years ?? []).map(String)}
      />
    </>
  )
}
