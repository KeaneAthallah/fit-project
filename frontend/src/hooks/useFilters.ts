import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

/** A stable empty list, so pages that pass no `multi` option do not get a
 *  new array identity every render (which would defeat the memos below). */
const NO_MULTI_KEYS: readonly never[] = []

/**
 * Filter state that lives in the URL.
 *
 * Values and Review queue both filter, sort and page entirely through query
 * parameters, so a row on the dashboard can link straight to a filtered queue
 * and the browser back button steps through the filters. This hook owns the
 * repetitive parts of that contract so the pages only describe which keys they
 * care about.
 *
 * Pass a module-level constant for `keys`: it is used as a dependency. A page
 * that keeps page state in the same parameter object -- a tab, a sort, a page
 * number -- should list those in `keys` but not in `options.clearable`, so they
 * are read back but neither counted as filters nor wiped by `clearAll`.
 *
 * A key listed in `options.multi` holds several values at once and travels as
 * repeated parameters (`?subsector=a&subsector=b`), the only lossless URL
 * encoding for a value that can itself contain a separator. Its value comes
 * back through `multiValues` as a string array; the scalar `values` map leaves
 * those keys out entirely.
 */
export function useUrlFilters<K extends string, M extends K = never>(
  keys: readonly K[],
  options: { clearable?: readonly string[]; multi?: readonly M[] } = {},
) {
  const [searchParams, setSearchParams] = useSearchParams()
  const clearable = options.clearable ?? keys
  const multi = options.multi ?? NO_MULTI_KEYS

  // `get`/`setParam` accept any key, not just the ones in `keys`: paging and
  // sorting also live in the URL, and typing them separately at every call site
  // adds nothing.
  const get = useCallback(
    (key: string) => searchParams.get(key) ?? '',
    [searchParams],
  )

  const getAll = useCallback(
    (key: string) => searchParams.getAll(key),
    [searchParams],
  )

  const setParam = useCallback(
    (key: string, value: string | string[]) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          // Replacing rather than appending: the URL is the state, so a
          // stale value left behind would outlive the change that
          // superseded it.
          next.delete(key)
          if (Array.isArray(value)) {
            for (const item of value) {
              if (item) next.append(key, item)
            }
          } else if (value) {
            next.set(key, value)
          }
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

  // Clears the filters and nothing else. `setSearchParams({})` would also throw
  // away the tab, the sort and any parameter belonging to another feature,
  // which reads to the reader as the page having reset itself.
  const clearAll = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const key of clearable) next.delete(key)
        next.delete('page')
        return next
      },
      { replace: true },
    )
  }, [clearable, setSearchParams])

  const values = useMemo(() => {
    const out = {} as Record<Exclude<K, M>, string>
    for (const key of keys) {
      if (multi.includes(key as M)) continue
      out[key as Exclude<K, M>] = searchParams.get(key) ?? ''
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, searchParams, multi])

  const multiValues = useMemo(() => {
    const out = {} as Record<M, string[]>
    for (const key of multi) out[key] = searchParams.getAll(key)
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multi, searchParams])

  const activeCount = clearable.reduce(
    (n, key) =>
      multi.includes(key as M)
        ? n + (searchParams.getAll(key).length > 0 ? 1 : 0)
        : n + (searchParams.get(key) ? 1 : 0),
    0,
  )

  return { searchParams, get, getAll, setParam, clearAll, values, multiValues, activeCount }
}
