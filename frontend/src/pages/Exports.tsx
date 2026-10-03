import { useState } from 'react'
import { api } from '../lib/api'
import { useAction, useQuery } from '../hooks/useQuery'
import { bytes, dateTime, num } from '../lib/format'
import { useProcessing } from '../lib/processing-context'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Loading,
  PageHeader,
  Select,
  SkeletonTable,
  Table,
  Td,
  Th,
} from '../components/ui'

const LOG_SIZES = [50, 200, 500, 1000]

function ExportsCard() {
  const files = useQuery(() => api.exportFiles(), [])
  const { run, pending, error, reset } = useAction(() => api.runExports())
  const [notice, setNotice] = useState<string | null>(null)

  const generate = async () => {
    const result = await run()
    if (result) {
      setNotice(
        `Generated ${num(Object.values(result.reports).reduce((a, b) => a + b, 0))} report files and ${num(Object.values(result.review_queue).reduce((a, b) => a + b, 0))} review files.`,
      )
      files.refetch()
    }
  }

  const reports = (files.data?.items ?? []).filter((f) => f.kind === 'report')
  const review = (files.data?.items ?? []).filter((f) => f.kind === 'review')

  return (
    <Card
      title="Generated files"
      subtitle="CSV and Excel reports written to the output directory"
      actions={
        <Button variant="primary" pending={pending} onClick={generate}>
          Generate reports
        </Button>
      }
    >
      <div className="space-y-3">
        {error && <ErrorBanner message={error} onRetry={reset} />}
        {notice && (
          <Alert
            tone="success"
            action={
              <Button size="sm" variant="secondary" onClick={() => setNotice(null)}>
                Dismiss
              </Button>
            }
          >
            {notice}
          </Alert>
        )}
        {files.error && <ErrorBanner message={files.error} onRetry={files.refetch} />}
      </div>

      {files.initialLoading ? (
        <div className="mt-4">
          <SkeletonTable rows={5} cols={4} />
        </div>
      ) : files.data?.items.length === 0 ? (
        <EmptyState
          title="No exports yet"
          hint="Run the pipeline, then generate reports to produce reviewable CSV files."
          action={
            <Button size="sm" variant="secondary" pending={pending} onClick={generate}>
              Generate reports
            </Button>
          }
        />
      ) : (
        <div className="space-y-5">
          {[
            { title: 'Summary reports', rows: reports },
            { title: 'Review queue', rows: review },
          ]
            .filter((g) => g.rows.length > 0)
            .map((group) => (
              <div key={group.title}>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                  {group.title} ({num(group.rows.length)})
                </h3>
                <Table caption={group.title}>
                  <thead>
                    <tr>
                      <Th>File</Th>
                      <Th align="right">Size</Th>
                      <Th hideBelow="sm">Modified</Th>
                      <Th align="right">Download</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map((f) => (
                      <tr key={f.path} className="transition-colors hover:bg-accent/40">
                        <Td className="font-mono text-xs font-medium">
                          {/* max-w + truncate: generated file names include
                              long company names and dates. */}
                          <span className="block max-w-[18rem] truncate sm:max-w-[28rem]" title={f.name}>
                            {f.name}
                          </span>
                        </Td>
                        <Td align="right" mono>
                          {bytes(f.size)}
                        </Td>
                        <Td hideBelow="sm" className="text-xs whitespace-nowrap">
                          {dateTime(f.modified_at)}
                        </Td>
                        <Td align="right">
                          <a
                            href={api.downloadUrl(f.name)}
                            className="text-xs font-medium text-primary hover:underline"
                          >
                            Download
                          </a>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            ))}
        </div>
      )}
    </Card>
  )
}

function LogCard() {
  const [lines, setLines] = useState(200)
  const log = useQuery(() => api.log(lines), [lines])

  return (
    <Card
      title="Pipeline log"
      subtitle={log.data?.path ? `Tailing ${log.data.path}` : 'Last lines of the processing log'}
      actions={
        <>
          <Select
            aria-label="Number of log lines"
            options={LOG_SIZES.map((n) => ({ value: String(n), label: `${n} lines` }))}
            value={String(lines)}
            onChange={(e) => setLines(Number(e.target.value))}
            className="h-9 w-28"
          />
          <Button size="sm" variant="secondary" pending={log.loading} onClick={log.refetch}>
            Refresh
          </Button>
        </>
      }
    >
      {log.error ? (
        <ErrorBanner message={log.error} onRetry={log.refetch} />
      ) : log.initialLoading ? (
        <Loading />
      ) : log.data?.lines.length === 0 ? (
        <EmptyState title="Log is empty" hint="No processing run has written to the log yet." />
      ) : (
        // Log lines are long and unbreakable-ish, so the pre scrolls
        // horizontally inside its own box rather than widening the page.
        <pre className="scroll-thin max-h-96 overflow-auto rounded-lg border border-border bg-code-surface p-3 font-mono text-xs leading-relaxed text-code-foreground">
          {log.data?.lines.join('\n')}
        </pre>
      )}
    </Card>
  )
}

export default function Exports() {
  const { state } = useProcessing()

  return (
    <>
      <PageHeader
        title="Exports"
        subtitle="Generate downloadable reports and inspect the processing log"
      />

      <div className="space-y-4">
        {state?.running && (
          <Alert tone="warning">
            A batch is running. Generating reports now may snapshot incomplete data.
          </Alert>
        )}
        <ExportsCard />
        <LogCard />
      </div>
    </>
  )
}