import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../lib/api'

export interface QueryState<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** True only on the first load, so a refetch does not blank the table. */
  initialLoading: boolean
  refetch: () => void
}

/**
 * Minimal fetch-on-mount hook. The API is a local SQLite read, so there is no
 * cache to speak of; `deps` behaves like a useEffect dependency list and
 * `pollMs` re-runs the request on an interval for live batch progress.
 */
export function useQuery<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  options: { pollMs?: number } = {},
): QueryState<T> {
  const { pollMs } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [initialLoading, setInitialLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  // The fetcher closes over props, so its identity changes every render. It is
  // kept in a ref so that does not restart the fetch effect. Assigned in an
  // effect rather than during render; this effect is declared first so the
  // current fetcher is in place before the fetch effect below runs.
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  // Tracks an outstanding request so the poller below cannot stack a second one
  // on top of it: a slow SQLite query can outlast the interval, and the older
  // response would then land after the newer one and win.
  const inFlight = useRef(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    inFlight.current = true

    fetcherRef
      .current()
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : String(err))
      })
      .finally(() => {
        // Ownership of the flag passes to whichever request is current, so a
        // superseded request must leave it alone: clearing it here would let the
        // poller start another request on top of the live one. The current
        // request clears it when it settles, which is what unblocks the poller.
        if (!cancelled) inFlight.current = false
        if (cancelled) return
        setLoading(false)
        setInitialLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  useEffect(() => {
    if (!pollMs) return
    const id = window.setInterval(() => {
      if (!inFlight.current) setNonce((n) => n + 1)
    }, pollMs)
    return () => window.clearInterval(id)
  }, [pollMs])

  const refetch = useCallback(() => setNonce((n) => n + 1), [])

  return { data, error, loading, initialLoading, refetch }
}

/**
 * Imperative one-shot call (button handlers: run exports, start a batch).
 * Tracks its own pending/error state so the button can disable itself.
 */
export function useAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
): {
  run: (...args: TArgs) => Promise<TResult | null>
  pending: boolean
  error: string | null
  reset: () => void
} {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const actionRef = useRef(action)
  useEffect(() => {
    actionRef.current = action
  })

  const run = useCallback(async (...args: TArgs) => {
    setPending(true)
    setError(null)
    try {
      const result = await actionRef.current(...args)
      return result
    } catch (err: unknown) {
      if (mounted.current) {
        setError(err instanceof ApiError ? err.message : String(err))
      }
      return null
    } finally {
      if (mounted.current) setPending(false)
    }
  }, [])

  return { run, pending, error, reset: useCallback(() => setError(null), []) }
}

/**
 * Re-runs `refetch` on an interval only while `active` is true, and fires one
 * final refresh the moment it goes false.
 *
 * The pipeline commits each document to SQLite as it finishes (WAL mode, so
 * concurrent reads are safe), which means the database really is live. Without
 * this the tables would only ever show whatever was there at mount time. The
 * trailing refetch matters: the final state of the last document is committed
 * after `active` flips to false, so polling alone would miss it.
 */
export function useLiveRefresh(
  refetch: () => void,
  active: boolean,
  intervalMs = 2500,
): void {
  const wasActive = useRef(false)

  useEffect(() => {
    if (!active) {
      if (wasActive.current) refetch()
      wasActive.current = false
      return
    }
    wasActive.current = true
    const id = window.setInterval(refetch, intervalMs)
    return () => window.clearInterval(id)
  }, [active, refetch, intervalMs])
}

/** Debounces a fast-changing value (search boxes) so typing does not fire a
 *  request per keystroke. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(id)
  }, [value, delay])
  return debounced
}