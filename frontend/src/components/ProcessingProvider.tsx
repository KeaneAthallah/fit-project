import { useMemo } from 'react'
import { api } from '../lib/api'
import { useQuery } from '../hooks/useQuery'
import { ProcessingContext, type ProcessingContextValue } from '../lib/processing-context'

/** 4s is fast enough that the indicator flips almost immediately after a batch
 *  starts or finishes, and slow enough not to matter against a local SQLite
 *  read. */
const POLL_MS = 4000

export function ProcessingProvider({ children }: { children: React.ReactNode }) {
  const { data, error, loading, initialLoading, refetch } = useQuery<Awaited<ReturnType<typeof api.processing>>>(
    () => api.processing(),
    [],
    { pollMs: POLL_MS },
  )

  const value = useMemo<ProcessingContextValue>(
    () => ({ state: data, error, loading, initialLoading, refetch }),
    [data, error, loading, initialLoading, refetch],
  )

  return <ProcessingContext.Provider value={value}>{children}</ProcessingContext.Provider>
}