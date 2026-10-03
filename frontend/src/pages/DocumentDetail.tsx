import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useQuery } from '../hooks/useQuery'
import { dateTime, dec, duration, num, rupiah, titleCase } from '../lib/format'
import type { DocumentDetail as DocumentDetailData, ExtractedValue, ValidationCheck } from '../lib/types'
import { CheckBadge, Confidence, DocStatusBadge, ValueStatusBadge } from '../components/badges'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorBanner,
  KeyValue,
  Pagination,
  Skeleton,
  SkeletonTable,
  Table,
  Tabs,
  Td,
  Th,
} from '../components/ui'

type Tab = 'values' | 'checks' | 'pages'

function Overview({ data }: { data: DocumentDetailData }) {
  const counts = data.checks.reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1
    return acc
  }, {})

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Extraction" className="lg:col-span-2">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 xl:grid-cols-4">
            <KeyValue label="Status">
              <DocStatusBadge status={data.status} />
            </KeyValue>
            <KeyValue label="Reporting year">{data.reporting_year ?? '-'}</KeyValue>
            <KeyValue label="PDF type">{titleCase(data.pdf_type ?? '-')}</KeyValue>
            <KeyValue label="OCR used">{data.ocr_used ? 'Yes' : 'No'}</KeyValue>
            <KeyValue label="Pages">{num(data.page_count)}</KeyValue>
            <KeyValue label="Text pages">{num(data.text_pages)}</KeyValue>
            <KeyValue label="OCR pages">{num(data.ocr_pages)}</KeyValue>
            <KeyValue label="Financial pages">{num(data.financial_pages)}</KeyValue>
            <KeyValue label="Values">{num(data.values.length)}</KeyValue>
            <KeyValue label="Processing time">{duration(data.processing_time)}</KeyValue>
            {/* The confidence meter is wider than a truncated cell. */}
            <KeyValue label="Avg confidence" truncate={false}>
              <Confidence value={data.avg_confidence} />
            </KeyValue>
            <KeyValue label="Completed">{dateTime(data.completed_at)}</KeyValue>
          </dl>
          {data.error_message && (
            <Alert tone="danger" className="mt-4">
              <span className="wrap-anywhere">{data.error_message}</span>
            </Alert>
          )}
        </Card>

        <Card title="Validation" subtitle={`${num(data.checks.length)} checks recorded`}>
          {data.checks.length === 0 ? (
            <EmptyState title="No validation checks" />
          ) : (
            <ul className="space-y-2">
              {Object.entries(counts)
                .sort((a, b) => b[1] - a[1])
                .map(([status, n]) => (
                  <li key={status} className="flex items-center gap-2">
                    <CheckBadge status={status} />
                    <span className="tnum ml-auto text-sm font-medium text-foreground">{n}</span>
                  </li>
                ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Source file">
          {/* break-all: a Windows path has no spaces to break on, and a long
              one would otherwise widen the card. */}
          <p className="font-mono text-xs break-all text-muted-foreground">{data.file_path}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            Created {dateTime(data.created_at)} &middot; Updated {dateTime(data.updated_at)}
          </p>
        </Card>
      </div>
    </>
  )
}

function ValuesTable({ values }: { values: ExtractedValue[] }) {
  if (values.length === 0) return <EmptyState title="No values extracted" />
  return (
    <Table caption="Extracted values">
      <thead>
        <tr>
          <Th>Statement</Th>
          <Th hideBelow="sm">Field</Th>
          <Th hideBelow="lg">Raw label</Th>
          <Th align="right">Raw</Th>
          <Th align="right">Normalised</Th>
          <Th hideBelow="xl">Unit</Th>
          <Th align="right" hideBelow="sm">
            Page
          </Th>
          <Th hideBelow="lg">Method</Th>
          <Th>Confidence</Th>
          <Th hideBelow="md">Status</Th>
        </tr>
      </thead>
      <tbody>
        {values.map((v) => (
          <tr key={v.id} className="transition-colors hover:bg-accent/40">
            <Td className="text-xs whitespace-nowrap">{titleCase(v.statement)}</Td>
            <Td hideBelow="sm" className="font-medium text-foreground">
              {titleCase(v.field)}
            </Td>
            <Td hideBelow="lg" className="max-w-56 text-xs">
              <span className="block truncate" title={v.raw_label ?? undefined}>
                {v.raw_label ?? '-'}
              </span>
            </Td>
            <Td align="right" mono>
              <span className="block max-w-32 truncate" title={v.raw_value ?? undefined}>
                {v.raw_value ?? '-'}
              </span>
            </Td>
            <Td align="right" mono className="font-medium text-foreground">
              {rupiah(v.normalized_value)}
            </Td>
            <Td hideBelow="xl">{v.unit ?? '-'}</Td>
            <Td align="right" mono hideBelow="sm">
              {v.page ?? '-'}
            </Td>
            <Td hideBelow="lg" className="text-xs">
              {titleCase(v.extraction_method)}
            </Td>
            <Td>
              <Confidence value={v.confidence} />
            </Td>
            <Td hideBelow="md">
              <ValueStatusBadge status={v.status} />
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}

function ChecksTable({ checks }: { checks: ValidationCheck[] }) {
  if (checks.length === 0) return <EmptyState title="No validation checks recorded" />
  return (
    <Table caption="Validation checks">
      <thead>
        <tr>
          <Th>Check</Th>
          <Th>Status</Th>
          <Th align="right">Expected</Th>
          <Th align="right">Actual</Th>
          <Th align="right" hideBelow="md">
            Difference
          </Th>
          <Th hideBelow="sm">Message</Th>
        </tr>
      </thead>
      <tbody>
        {checks.map((c) => (
          <tr key={c.id} className="transition-colors hover:bg-accent/40">
            <Td>
              <span className="block font-medium text-foreground">{titleCase(c.check_name)}</span>
              {c.category && (
                <span className="block truncate text-xs text-muted-foreground">
                  {titleCase(c.category)}
                </span>
              )}
            </Td>
            <Td>
              <CheckBadge status={c.status} />
            </Td>
            <Td align="right" mono>
              <span className="block max-w-32 truncate" title={c.expected ?? undefined}>
                {c.expected ?? '-'}
              </span>
            </Td>
            <Td align="right" mono>
              <span className="block max-w-32 truncate" title={c.actual ?? undefined}>
                {c.actual ?? '-'}
              </span>
            </Td>
            <Td align="right" mono hideBelow="md">
              {c.difference !== null ? num(c.difference) : '-'}
            </Td>
            <Td hideBelow="sm" className="max-w-md text-xs">
              <span className="break-words">{c.message ?? '-'}</span>
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}

function PagesTable({ docId }: { docId: number }) {
  const [page, setPage] = useState(1)
  const [includeText, setIncludeText] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const pageSize = 25

  const { data, error, initialLoading, refetch } = useQuery(
    () => api.documentPages(docId, { page, page_size: pageSize, include_text: includeText }),
    [docId, page, includeText],
  )

  if (error) return <ErrorBanner message={error} onRetry={refetch} />
  if (initialLoading) {
    return (
      <div className="p-4">
        <SkeletonTable rows={8} cols={5} />
      </div>
    )
  }
  if (!data) return null

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-3">
        <Checkbox
          label="Load extracted page text"
          checked={includeText}
          onChange={(e) => {
            setIncludeText(e.target.checked)
            setPage(1)
            setExpanded(null)
          }}
        />
        <p className="text-xs text-muted-foreground">
          {includeText
            ? 'Text is fetched for the current page only.'
            : 'Enable text to inspect what OCR read.'}
        </p>
      </div>

      {data.items.length === 0 ? (
        <EmptyState title="No page records" />
      ) : (
        <Table caption="Pages">
          <thead>
            <tr>
              <Th align="right">Page</Th>
              <Th>Type</Th>
              <Th hideBelow="sm">Section</Th>
              <Th align="right" hideBelow="md">
                OCR conf.
              </Th>
              <Th align="right" hideBelow="lg">
                OCR time
              </Th>
              <Th align="right">Chars</Th>
              <Th align="right" hideBelow="md">
                Flags
              </Th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((p) => {
              const isOpen = expanded === p.page_number
              return (
                <Fragment key={p.id}>
                  <tr className="transition-colors hover:bg-accent/40">
                    <Td align="right" mono>
                      <button
                        type="button"
                        disabled={!includeText}
                        onClick={() => setExpanded(isOpen ? null : p.page_number)}
                        title={
                          includeText
                            ? isOpen
                              ? 'Hide extracted text'
                              : 'Show extracted text'
                            : 'Enable "Load extracted page text" first'
                        }
                        aria-expanded={isOpen}
                        className="inline-flex h-8 min-w-10 items-center justify-center gap-1 rounded-md text-muted-foreground enabled:hover:bg-accent enabled:hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {/* Inline chevrons: the glyph this used to be a literal
                            character that never rendered. */}
                        <svg
                          viewBox="0 0 24 24"
                          className={`h-3 w-3 shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          aria-hidden
                        >
                          <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        {p.page_number}
                      </button>
                    </Td>
                    <Td>{titleCase(p.pdf_type ?? '-')}</Td>
                    <Td hideBelow="sm" className="max-w-48 text-xs">
                      <span className="block truncate" title={p.section ?? undefined}>
                        {p.section ?? '-'}
                      </span>
                    </Td>
                    <Td align="right" mono hideBelow="md">
                      {p.ocr_confidence !== null ? dec(p.ocr_confidence) : '-'}
                    </Td>
                    <Td align="right" mono hideBelow="lg">
                      {p.ocr_time !== null ? `${dec(p.ocr_time)}s` : '-'}
                    </Td>
                    <Td align="right" mono>
                      {num(p.text_length)}
                    </Td>
                    <Td align="right" hideBelow="md">
                      <span className="flex flex-wrap justify-end gap-1">
                        {p.is_relevant && <span className="sr-only">Relevant page. </span>}
                        {p.is_relevant && <RelevanceChip label="relevant" />}
                        {p.is_parent_only && <RelevanceChip label="parent only" />}
                      </span>
                    </Td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={7} className="border-b border-border bg-muted/50 px-3 py-3">
                        {p.text ? (
                          <pre className="scroll-thin max-h-96 overflow-auto rounded-md border border-border bg-card p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-muted-foreground">
                            {p.text}
                          </pre>
                        ) : (
                          <p className="text-xs text-muted-foreground">
                            No text recorded for this page.
                          </p>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </Table>
      )}

      {data.items.length > 0 && (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          total={data.pagination.total}
          pageSize={data.pagination.page_size}
          onPage={setPage}
        />
      )}
    </>
  )
}

function RelevanceChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-neutral-soft px-2 py-0.5 text-xs font-medium whitespace-nowrap text-neutral-soft-foreground ring-1 ring-inset ring-border">
      {label}
    </span>
  )
}

export default function DocumentDetail() {
  const { docId } = useParams<{ docId: string }>()
  const id = Number(docId)
  const [tab, setTab] = useState<Tab>('values')

  const detail = useQuery(() => api.document(id), [id])

  if (Number.isNaN(id)) {
    return <ErrorBanner message="Invalid document id" />
  }

  if (detail.initialLoading) {
    return (
      <>
        <Skeleton className="mb-4 h-4 w-32" />
        <Skeleton className="mb-5 h-8 w-72" />
        <Skeleton className="h-56 w-full" />
      </>
    )
  }
  if (detail.error) {
    return <ErrorBanner message={detail.error} onRetry={detail.refetch} />
  }
  const data = detail.data
  if (!data) return null

  return (
    <>
      <div className="mb-4">
        <Link
          to="/documents"
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            aria-hidden
          >
            <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          All documents
        </Link>
      </div>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0 max-w-3xl flex-1">
          <h1 className="text-xl font-semibold tracking-tight break-words text-foreground">
            {data.company}
          </h1>
          <p className="mt-1 font-mono text-xs break-all text-muted-foreground">
            {data.filename}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <DocStatusBadge status={data.status} />
          <Button variant="secondary" pending={detail.loading} onClick={detail.refetch}>
            Refresh
          </Button>
        </div>
      </div>

      <Overview data={data} />

      <div className="mt-6">
        <Tabs
          className="mb-3"
          active={tab}
          onChange={setTab}
          tabs={[
            { key: 'values', label: 'Extracted values', count: data.values.length },
            { key: 'checks', label: 'Validation checks', count: data.checks.length },
            { key: 'pages', label: 'Pages', count: data.page_rows },
          ]}
        />

        <Card padded={false}>
          {tab === 'values' && <ValuesTable values={data.values} />}
          {tab === 'checks' && <ChecksTable checks={data.checks} />}
          {tab === 'pages' && <PagesTable docId={id} />}
        </Card>
      </div>
    </>
  )
}