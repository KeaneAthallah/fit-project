import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Filter state that lives in the URL.
 *
 * Values and Review queue both filter, sort and page entirely through query
 * parameters, so a row on the dashboard can link straight to a filtered queue
 * and the browser back button steps through the filters. This hook owns the
 * repetitive parts of that contract so the pages only describe which keys they
 * care about.
 *
 * Pass a module-level constant for `keys`: it is used as a dependency.
 */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const [searchParams, setSearchParams] = useSearchParams()

  // `get`/`setParam` accept any key, not just the ones in `keys`: paging and
  // sorting also live in the URL, and typing them separately at every call site
  // adds nothing.
  const get = useCallback(
    (key: string) => searchParams.get(key) ?? '',
    [searchParams],
  )

  const setParam = useCallback(
    (key: string, value: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (value) next.set(key, value)
          else next.delete(key)
          // Any filter change invalidates the current page number, otherwise
          // page 7 of a new, narrower result set renders as an empty table.
          if (key !== 'page') next.delete('page')
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const clearAll = useCallback(() => {
    setSearchParams({}, { replace: true })
  }, [setSearchParams])

  const values = useMemo(() => {
    const out = {} as Record<K, string>
    for (const key of keys) out[key] = searchParams.get(key) ?? ''
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, searchParams])

  const activeCount = keys.reduce(
    (n, key) => (searchParams.get(key) ? n + 1 : n),
    0,
  )

  return { searchParams, get, setParam, clearAll, values, activeCount }
}