import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useDebounced, useLiveRefresh, useQuery } from '../hooks/useQuery'
import { dateTime } from '../lib/format'
import {
  CHECK_STATUS_LABELS,
  DOC_STATUS_LABELS,
  documents as s,
} from '../lib/strings'
import { useProcessing } from '../lib/processing-context'
import { Confidence, DocStatusBadge } from '../components/badges'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  PageHeader,
  Pagination,
  Select,
  SkeletonTable,
  Spinner,
  Table,
  Td,
  Th,
} from '../components/ui'

const PAGE_SIZES = [25, 50, 100]

const STATUS_OPTIONS = [
  { value: '', label: s.allStatuses },
  { value: 'COMPLETED', label: DOC_STATUS_LABELS.COMPLETED },
  { value: 'REVIEW_REQUIRED', label: DOC_STATUS_LABELS.REVIEW_REQUIRED },
  { value: 'FAILED', label: DOC_STATUS_LABELS.FAILED },
  { value: 'PROCESSING', label: DOC_STATUS_LABELS.PROCESSING },
  { value: 'DISCOVERED', label: DOC_STATUS_LABELS.DISCOVERED },
  { value: 'DUPLICATE', label: DOC_STATUS_LABELS.DUPLICATE },
]

const VALIDATION_OPTIONS = [
  { value: '', label: s.anyValidationState },
  { value: 'VALID', label: `${s.validationPrefix} ${CHECK_STATUS_LABELS.VALID}` },
  { value: 'ERROR', label: `${s.validationPrefix} ${CHECK_STATUS_LABELS.ERROR}` },
  {
    value: 'WARNING',
    label: `${s.validationPrefix} ${CHECK_STATUS_LABELS.WARNING}`,
  },
  {
    value: 'REVIEW_REQUIRED',
    label: `${s.validationPrefix} ${CHECK_STATUS_LABELS.REVIEW_REQUIRED}`,
  },
]

/** Sort keys must match `sort_columns` in `list_documents`. Column order here
 *  is presentation only - the table headers drive the sort. */
const SORTABLE = [
  { value: 'company', label: s.sortKeys.company },
  { value: 'filename', label: s.sortKeys.filename },
  { value: 'status', label: s.sortKeys.status },
  { value: 'pages', label: s.sortKeys.pages },
  { value: 'confidence', label: s.sortKeys.confidence },
  { value: 'year', label: s.sortKeys.year },
  { value: 'updated', label: s.sortKeys.updated },
  { value: 'id', label: s.sortKeys.id },
]

type SortKey = (typeof SORTABLE)[number]['value']

export default function Documents() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [company, setCompany] = useState('')
  const [validationStatus, setValidationStatus] = useState('')
  const [sort, setSort] = useState<SortKey>('updated')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)

  const debouncedSearch = useDebounced(search)

  // Any filter change invalidates the current page number, otherwise page 7 of
  // a new, narrower result set renders as an empty table. Adjusting state
  // during render is the documented React pattern for derived state; doing it
  // in an effect would render the stale page once first.
  const filterKey = `${debouncedSearch}|${status}|${company}|${validationStatus}`
  const [lastFilterKey, setLastFilterKey] = useState(filterKey)
  if (filterKey !== lastFilterKey) {
    setLastFilterKey(filterKey)
    setPage(1)
  }

  const params = useMemo(
    () => ({
      search: debouncedSearch,
      status,
      company,
      validation_status: validationStatus,
      sort,
      order,
      page,
      page_size: pageSize,
    }),
    [debouncedSearch, status, company, validationStatus, sort, order, page, pageSize],
  )

  const companies = useQuery(() => api.companies(), [])
  const { data, error, loading, initialLoading, refetch } = useQuery(
    () => api.documents(params),
    [JSON.stringify(params)],
  )

  // Poll while a batch is running so documents appear and change status as the
  // pipeline works through them, instead of only after a manual refresh.
  const { state } = useProcessing()
  useLiveRefresh(refetch, state?.running ?? false)

  const toggleSort = (key: SortKey) => {
    if (key === sort) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(key)
      // Names read best A-Z; metrics read best largest-first.
      setOrder(key === 'company' || key === 'filename' || key === 'status' ? 'asc' : 'desc')
    }
  }

  const activeFilters =
    [debouncedSearch, status, company, validationStatus].filter(Boolean).length > 0
  const clearAll = () => {
    setSearch('')
    setStatus('')
    setCompany('')
    setValidationStatus('')
  }

  const companyOptions = [
    { value: '', label: s.allCompanies },
    ...(companies.data?.items ?? []).map((c) => ({
      value: c.company,
      label: c.company,
      count: c.documents,
    })),
  ]

  const running = state?.running ?? false

  return (
    <>
      <PageHeader
        title={s.title}
        subtitle={data ? s.matchCount(data.pagination.total) : undefined}
        actions={
          <div className="flex items-center gap-2">
            {running && (
              <Badge tone="info" className="h-8 px-2.5">
                <Spinner className="h-3 w-3" />
                {s.live}
              </Badge>
            )}
            <Button variant="secondary" pending={loading} onClick={refetch}>
              {s.refresh}
            </Button>
          </div>
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            label={s.search}
            placeholder={s.searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Select
            label={s.status}
            options={STATUS_OPTIONS}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          />
          <Select
            label={s.company}
            options={companyOptions}
            value={company}
            onChange={(e) => setCompany(e.target.value)}
          />
          <Select
            label={s.validation}
            options={VALIDATION_OPTIONS}
            value={validationStatus}
            onChange={(e) => setValidationStatus(e.target.value)}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">
            {s.sort}:{' '}
            <span className="font-medium text-foreground">
              {order === 'asc' ? s.ascending : s.descending}
            </span>
            <span className="hidden sm:inline"> &middot; {s.sortHint}</span>
          </p>
          <div className="flex items-center gap-2">
            {activeFilters && (
              <Button size="sm" variant="ghost" onClick={clearAll}>
                {s.clearFilters}
              </Button>
            )}
            <div className="w-24">
              <Select
                label={s.rows}
                options={PAGE_SIZES.map((n) => ({ value: String(n), label: String(n) }))}
                value={String(pageSize)}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setPage(1)
                }}
              />
            </div>
          </div>
        </div>
      </Card>

      {error && <ErrorBanner message={error} onRetry={refetch} />}

      <Card padded={false}>
        {initialLoading ? (
          <div className="p-4">
            <SkeletonTable rows={10} cols={6} />
          </div>
        ) : data?.items.length === 0 ? (
          <EmptyState
            title={s.noMatchTitle}
            hint={
              activeFilters ? s.noMatchHintFiltered : s.noMatchHint
            }
            action={
              activeFilters ? (
                <Button size="sm" variant="secondary" onClick={clearAll}>
                  {s.clearFilters}
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <Table caption={s.title} stickyHeader>
              <thead>
                <tr>
                  <Th onSort={() => toggleSort('company')} sorted={sort === 'company' ? order : false}>
                    {s.tableHeaders.company}
                  </Th>
                  <Th onSort={() => toggleSort('status')} sorted={sort === 'status' ? order : false}>
                    {s.tableHeaders.status}
                  </Th>
                  <Th
                    align="right"
                    hideBelow="sm"
                    onSort={() => toggleSort('year')}
                    sorted={sort === 'year' ? order : false}
                  >
                    {s.tableHeaders.year}
                  </Th>
                  <Th
                    align="right"
                    hideBelow="lg"
                    onSort={() => toggleSort('pages')}
                    sorted={sort === 'pages' ? order : false}
                  >
                    {s.tableHeaders.pages}
                  </Th>
                  <Th align="right" hideBelow="xl">
                    {s.tableHeaders.financial}
                  </Th>
                  <Th
                    hideBelow="md"
                    onSort={() => toggleSort('confidence')}
                    sorted={sort === 'confidence' ? order : false}
                  >
                    {s.tableHeaders.confidence}
                  </Th>
                  <Th align="right" hideBelow="sm">
                    {s.tableHeaders.checks}
                  </Th>
                  <Th align="right" hideBelow="xl">
                    {s.tableHeaders.values}
                  </Th>
                  <Th
                    hideBelow="lg"
                    onSort={() => toggleSort('updated')}
                    sorted={sort === 'updated' ? order : false}
                  >
                    {s.tableHeaders.updated}
                  </Th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((doc) => (
                  <tr key={doc.id} className="transition-colors hover:bg-accent/40">
                    <Td>
                      <Link to={`/documents/${doc.id}`} className="group block min-w-0">
                        <span className="block truncate font-medium text-foreground group-hover:text-primary">
                          {doc.company}
                        </span>
                        {/* max-w + truncate: a 120-character file name ellipsizes
                            rather than widening the table. */}
                        <span
                          className="block max-w-[16rem] truncate font-mono text-xs text-muted-foreground sm:max-w-[24rem]"
                          title={doc.filename}
                        >
                          {doc.filename}
                        </span>
                      </Link>
                    </Td>
                    <Td>
                      <DocStatusBadge status={doc.status} />
                    </Td>
                    <Td align="right" mono hideBelow="sm">
                      {doc.reporting_year ?? '-'}
                    </Td>
                    <Td align="right" mono hideBelow="lg">
                      {doc.page_count ?? '-'}
                    </Td>
                    <Td align="right" mono hideBelow="xl">
                      {doc.financial_pages ?? '-'}
                    </Td>
                    <Td hideBelow="md">
                      <Confidence value={doc.avg_confidence} />
                    </Td>
                    <Td align="right" mono hideBelow="sm">
                      {doc.validation_errors ? (
                        <span
                          className={`font-medium ${
                            doc.validation_errors > 0 ? 'text-destructive' : 'text-foreground'
                          }`}
                        >
                          {doc.validation_errors}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </Td>
                    <Td align="right" mono hideBelow="xl">
                      {doc.value_count ?? '-'}
                    </Td>
                    <Td hideBelow="lg" className="text-xs whitespace-nowrap text-muted-foreground">
                      {dateTime(doc.updated_at ?? doc.completed_at ?? doc.created_at)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {data && (
              <Pagination
                page={data.pagination.page}
                pages={data.pagination.pages}
                total={data.pagination.total}
                pageSize={data.pagination.page_size}
                onPage={setPage}
              />
            )}
          </>
        )}
      </Card>
    </>
  )
}