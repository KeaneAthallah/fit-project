import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useDebounced, useQuery } from '../hooks/useQuery'
import { useUrlFilters } from '../hooks/useFilters'
import { currencyLabel, currencyOptions, num, rupiah, titleCase } from '../lib/format'
import { Confidence, ValueStatusBadge } from '../components/badges'
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  PageHeader,
  Pagination,
  Select,
  SkeletonTable,
  Table,
  Td,
  Th,
} from '../components/ui'

const SORTABLE = [
  { value: 'field', label: 'Field' },
  { value: 'value', label: 'Value' },
  { value: 'confidence', label: 'Confidence' },
  { value: 'year', label: 'Year' },
  { value: 'company', label: 'Company' },
  { value: 'page', label: 'Page' },
]

type SortKey = (typeof SORTABLE)[number]['value']

const CONFIDENCE_FLOORS = [
  { value: '', label: 'Any confidence' },
  { value: '0.99', label: '99% and above' },
  { value: '0.95', label: '95% and above' },
  { value: '0.9', label: '90% and above' },
  { value: '0.8', label: '80% and above (review threshold)' },
  { value: '0', label: 'Below 50% (needs review)' },
]

const FILTER_KEYS = [
  'search',
  'statement',
  'field',
  'company',
  'year',
  'min_confidence',
  'currency',
] as const

const PAGE_SIZE = 50

export default function Values() {
  const { get, setParam, clearAll, values, activeCount } = useUrlFilters(FILTER_KEYS)
  const page = Number(get('page') || '1')
  const debouncedSearch = useDebounced(get('search'))
  const facets = useQuery(() => api.valueFacets(), [])
  const companies = useQuery(() => api.companies(), [])

  // Default to lowest confidence first: this page exists to find values worth
  // checking, and the doubtful ones are what you want at the top.
  const sort = (get('sort') || 'confidence') as SortKey
  const order = (get('order') || 'asc') as 'asc' | 'desc'

  const params = useMemo(
    () => ({
      statement: values.statement,
      field: values.field,
      company: values.company,
      year: values.year,
      min_confidence: values.min_confidence,
      currency: values.currency,
      search: debouncedSearch,
      sort,
      order,
      page,
      page_size: PAGE_SIZE,
    }),
    [values, debouncedSearch, sort, order, page],
  )

  const { data, error, loading, initialLoading, refetch } = useQuery(
    () => api.values(params),
    [JSON.stringify(params)],
  )

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

  // The value facets endpoint does not return companies (it would mean
  // grouping the whole table twice), so the list comes from /api/companies.
  const companyOptions = [
    { value: '', label: 'All companies' },
    ...(companies.data?.items ?? []).map((c) => ({ value: c.company, label: c.company })),
  ]

  const applySort = (key: SortKey) => {
    setParam('sort', key)
    // Names read best A-Z; magnitudes and confidence read best largest-first.
    setParam('order', key === 'company' || key === 'field' ? 'asc' : 'desc')
  }

  const sortedIndicator = (key: SortKey) => (sort === key ? order : false)

  return (
    <>
      <PageHeader
        title="Values"
        subtitle={
          data
            ? `${num(data.pagination.total)} values match`
            : 'Extracted financial line items'
        }
        actions={
          <Button variant="secondary" pending={loading} onClick={refetch}>
            Refresh
          </Button>
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Input
            label="Search"
            placeholder="Field, label or company"
            value={get('search')}
            onChange={(e) => setParam('search', e.target.value)}
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
            label="Year"
            options={yearOptions}
            value={values.year}
            onChange={(e) => setParam('year', e.target.value)}
          />
          <Select
            label="Company"
            options={companyOptions}
            value={values.company}
            onChange={(e) => setParam('company', e.target.value)}
          />
          <Select
            label="Confidence"
            options={CONFIDENCE_FLOORS}
            value={values.min_confidence}
            onChange={(e) => setParam('min_confidence', e.target.value)}
          />
          <Select
            label="Currency"
            hint="'Not detected' means no currency was found in the source, not that it is rupiah."
            options={currencyOptions(facets.data?.currencies)}
            value={values.currency}
            onChange={(e) => setParam('currency', e.target.value)}
          />
          <Select
            label="Sort by"
            options={SORTABLE.map((s) => ({ value: s.value, label: s.label }))}
            value={sort}
            onChange={(e) => applySort(e.target.value as SortKey)}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">
            Direction:{' '}
            <button
              type="button"
              onClick={() => setParam('order', order === 'asc' ? 'desc' : 'asc')}
              className="rounded font-medium text-primary hover:underline"
            >
              {order === 'asc' ? 'ascending' : 'descending'}
            </button>
          </p>
          {activeCount > 0 && (
            <Button size="sm" variant="ghost" onClick={clearAll}>
              Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
            </Button>
          )}
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
            title="No values match these filters"
            hint={
              activeCount
                ? 'Try clearing a filter.'
                : 'Values appear once a document has been processed.'
            }
            action={
              activeCount ? (
                <Button size="sm" variant="secondary" onClick={clearAll}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <Table caption="Extracted values" stickyHeader>
              <thead>
                <tr>
                  <Th onSort={() => applySort('field')} sorted={sortedIndicator('field')}>
                    Field
                  </Th>
                  <Th hideBelow="sm">Statement</Th>
                  <Th onSort={() => applySort('company')} sorted={sortedIndicator('company')}>
                    Company
                  </Th>
                  <Th
                    align="right"
                    hideBelow="sm"
                    onSort={() => applySort('year')}
                    sorted={sortedIndicator('year')}
                  >
                    Year
                  </Th>
                  <Th align="right" onSort={() => applySort('value')} sorted={sortedIndicator('value')}>
                    Value
                  </Th>
                  <Th align="right" hideBelow="lg">
                    Raw
                  </Th>
                  <Th hideBelow="xl">Unit</Th>
                  <Th hideBelow="2xl">Currency</Th>
                  <Th align="right" hideBelow="xl" onSort={() => applySort('page')} sorted={sortedIndicator('page')}>
                    Page
                  </Th>
                  <Th
                    onSort={() => applySort('confidence')}
                    sorted={sortedIndicator('confidence')}
                  >
                    Confidence
                  </Th>
                  <Th hideBelow="lg">Status</Th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((v) => (
                  <tr key={v.id} className="transition-colors hover:bg-accent/40">
                    <Td>
                      {/* The field name links to the source document, which
                          saves a dedicated "Open" column on a narrow screen. */}
                      <Link
                        to={`/documents/${v.document_id}`}
                        className="block min-w-0 font-medium text-foreground hover:text-primary"
                      >
                        <span className="block truncate">{titleCase(v.field)}</span>
                      </Link>
                      {v.raw_label && (
                        <span
                          className="block max-w-[14rem] truncate text-xs text-muted-foreground sm:max-w-[20rem]"
                          title={v.raw_label}
                        >
                          {v.raw_label}
                        </span>
                      )}
                    </Td>
                    <Td hideBelow="sm" className="text-xs whitespace-nowrap">
                      {titleCase(v.statement)}
                    </Td>
                    <Td>
                      <Link
                        to={`/values?company=${encodeURIComponent(v.company)}`}
                        className="block max-w-[12rem] truncate hover:text-primary hover:underline"
                        title={v.company}
                      >
                        {v.company}
                      </Link>
                    </Td>
                    <Td align="right" mono hideBelow="sm">
                      {v.year ?? '-'}
                    </Td>
                    <Td align="right" mono className="font-medium text-foreground">
                      {rupiah(v.normalized_value)}
                    </Td>
                    <Td align="right" mono hideBelow="lg" className="max-w-32 text-muted-foreground">
                      <span className="block truncate" title={v.raw_value ?? undefined}>
                        {v.raw_value ?? '-'}
                      </span>
                    </Td>
                    <Td hideBelow="xl" className="text-xs">
                      {v.unit ?? '-'}
                    </Td>
                    <Td hideBelow="2xl" className="text-xs whitespace-nowrap">
                      {v.currency ? (
                        <span title={currencyLabel(v.currency)}>{v.currency}</span>
                      ) : (
                        <span
                          className="text-muted-foreground"
                          title="No currency was found in the source for this figure."
                        >
                          Not detected
                        </span>
                      )}
                    </Td>
                    <Td align="right" mono hideBelow="xl">
                      {v.page ?? '-'}
                    </Td>
                    <Td>
                      <Confidence value={v.confidence} />
                    </Td>
                    <Td hideBelow="lg">
                      <ValueStatusBadge status={v.status} />
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
                onPage={(p) => setParam('page', String(p))}
              />
            )}
          </>
        )}
      </Card>

      <p className="mt-3 text-xs break-words text-muted-foreground">
        Figures are shown in full, exactly as extracted &mdash; nothing is scaled or
        rounded. &ldquo;Raw&rdquo; is the figure as printed in the report;
        &ldquo;Value&rdquo; is the normalised figure after the unit on that page was applied.
        &ldquo;Not detected&rdquo; in the currency column means no currency was found in the
        source, which is not the same as being rupiah.
      </p>
    </>
  )
}