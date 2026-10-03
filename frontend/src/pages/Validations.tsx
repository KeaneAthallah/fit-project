import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useDebounced, useQuery } from '../hooks/useQuery'
import { useUrlFilters } from '../hooks/useFilters'
import { num, titleCase } from '../lib/format'
import { CheckBadge } from '../components/badges'
import { CHART_COLORS, CHECK_STATUS_COLORS } from '../lib/palette'
import { Donut, type Slice } from '../components/charts'
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
  Table,
  Td,
  Th,
} from '../components/ui'

const FILTER_KEYS = ['status', 'check_name', 'category', 'company', 'year', 'search'] as const
const PAGE_SIZE = 50

export default function Validations() {
  // Filters live in the URL so a check row from the dashboard links straight to
  // a filtered queue, and the browser back button behaves.
  const { get, setParam, clearAll, values, activeCount } = useUrlFilters(FILTER_KEYS)
  const page = Number(get('page') || '1')
  const debouncedSearch = useDebounced(get('search'))
  const facets = useQuery(() => api.validationFacets(), [])
  const companies = useQuery(() => api.companies(), [])

  const params = useMemo(
    () => ({
      status: values.status,
      check_name: values.check_name,
      category: values.category,
      company: values.company,
      year: values.year,
      search: debouncedSearch,
      page,
      page_size: PAGE_SIZE,
    }),
    [values, debouncedSearch, page],
  )

  const { data, error, loading, initialLoading, refetch } = useQuery(
    () => api.validations(params),
    [JSON.stringify(params)],
  )

  const statusOptions = [
    { value: '', label: 'All outcomes' },
    ...(facets.data?.statuses ?? []).map((s) => ({
      value: s.status,
      label: titleCase(s.status),
      count: s.count,
    })),
  ]

  const checkOptions = [
    { value: '', label: 'All checks' },
    ...(facets.data?.check_names ?? []).map((c) => ({
      value: c.check_name,
      label: titleCase(c.check_name),
      count: c.count,
    })),
  ]

  const categoryOptions = [
    { value: '', label: 'All categories' },
    ...(facets.data?.categories ?? []).map((c) => ({
      value: c.category,
      label: titleCase(c.category),
      count: c.count,
    })),
  ]

  const yearOptions = [
    { value: '', label: 'All years' },
    ...(facets.data?.years ?? []).map((y) => ({ value: String(y), label: String(y) })),
  ]

  // The validation facets endpoint does not return companies, so the list
  // comes from /api/companies instead.
  const companyOptions = [
    { value: '', label: 'All companies' },
    ...(companies.data?.items ?? []).map((c) => ({ value: c.company, label: c.company })),
  ]

  const slices: Slice[] = (facets.data?.statuses ?? []).map((s, i) => ({
    label: titleCase(s.status),
    value: s.count,
    color: CHECK_STATUS_COLORS[s.status] ?? CHART_COLORS[i % CHART_COLORS.length],
  }))

  const checkTotal = slices.reduce((a, s) => a + s.value, 0)

  return (
    <>
      <PageHeader
        title="Review queue"
        subtitle={
          data
            ? `${num(data.pagination.total)} checks match${activeCount ? ' (filtered)' : ''}`
            : 'Accounting validation results across all documents'
        }
        actions={
          <Button variant="secondary" pending={loading} onClick={refetch}>
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          {checkTotal > 0 ? (
            <Donut slices={slices} centerLabel="checks" centerValue={num(checkTotal)} size={160} />
          ) : (
            <EmptyState title="No validation results yet" />
          )}
        </Card>

        <Card className="lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Search"
              placeholder="Company, check or message"
              value={get('search')}
              onChange={(e) => setParam('search', e.target.value)}
            />
            <Select
              label="Outcome"
              options={statusOptions}
              value={values.status}
              onChange={(e) => setParam('status', e.target.value)}
            />
            <Select
              label="Check"
              options={checkOptions}
              value={values.check_name}
              onChange={(e) => setParam('check_name', e.target.value)}
            />
            <Select
              label="Category"
              options={categoryOptions}
              value={values.category}
              onChange={(e) => setParam('category', e.target.value)}
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
          </div>
          {activeCount > 0 && (
            <div className="mt-4 flex border-t border-border pt-3">
              <Button size="sm" variant="ghost" onClick={clearAll}>
                Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
              </Button>
            </div>
          )}
        </Card>
      </div>

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} onRetry={refetch} />
        </div>
      )}

      <Card className="mt-4" padded={false}>
        {initialLoading ? (
          <div className="p-4">
            <SkeletonTable rows={10} cols={6} />
          </div>
        ) : data?.items.length === 0 ? (
          <EmptyState
            title="No checks match"
            hint={
              activeCount
                ? 'Try clearing a filter.'
                : 'Validation results appear after a document has been processed.'
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
            <Table caption="Validation checks" stickyHeader>
              <thead>
                <tr>
                  <Th>Outcome</Th>
                  <Th>Check</Th>
                  <Th>Company</Th>
                  <Th align="right" hideBelow="sm">
                    Year
                  </Th>
                  <Th align="right" hideBelow="md">
                    Expected
                  </Th>
                  <Th align="right" hideBelow="md">
                    Actual
                  </Th>
                  <Th align="right" hideBelow="lg">
                    Difference
                  </Th>
                  <Th hideBelow="lg">Message</Th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((c) => (
                  <tr key={c.id} className="transition-colors hover:bg-accent/40">
                    <Td>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <CheckBadge status={c.status} />
                        {c.severity && c.severity !== c.status && (
                          <Badge tone="neutral">{c.severity}</Badge>
                        )}
                      </div>
                    </Td>
                    <Td>
                      {/* Links to the source document, which replaces a
                          dedicated trailing action column. */}
                      <Link
                        to={`/documents/${c.document_id}`}
                        className="block min-w-0 hover:text-primary"
                      >
                        <span className="block truncate font-medium text-foreground">
                          {titleCase(c.check_name)}
                        </span>
                      </Link>
                      {c.category && (
                        <span className="block truncate text-xs text-muted-foreground">
                          {titleCase(c.category)}
                        </span>
                      )}
                    </Td>
                    <Td>
                      <Link
                        to={`/validations?company=${encodeURIComponent(c.company)}`}
                        className="block max-w-[14rem] truncate hover:text-primary hover:underline"
                        title={c.company}
                      >
                        {c.company}
                      </Link>
                    </Td>
                    <Td align="right" mono hideBelow="sm">
                      {c.year ?? '-'}
                    </Td>
                    <Td align="right" mono hideBelow="md">
                      <span className="block max-w-32 truncate" title={c.expected ?? undefined}>
                        {c.expected ?? '-'}
                      </span>
                    </Td>
                    <Td align="right" mono hideBelow="md">
                      <span className="block max-w-32 truncate" title={c.actual ?? undefined}>
                        {c.actual ?? '-'}
                      </span>
                    </Td>
                    <Td align="right" mono hideBelow="lg">
                      {c.difference !== null && c.difference !== undefined
                        ? num(c.difference)
                        : '-'}
                    </Td>
                    <Td hideBelow="lg" className="max-w-sm text-xs">
                      <span className="break-words">{c.message ?? '-'}</span>
                      {c.evidence && (
                        <span className="mt-0.5 block font-mono text-[11px] break-all text-muted-foreground">
                          {c.evidence}
                        </span>
                      )}
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
    </>
  )
}