import { titleCase } from './format'
import { CHART_COLORS, type StatusColorMap } from './palette'
import type { Slice } from '../components/charts'

/**
 * Turns a `{ STATUS: count }` record from the API into chart slices.
 *
 * Zero buckets are dropped so the legend only lists states that actually
 * occur, and `order` fixes the segment order so a given chart renders
 * identically every time it loads. Anything the backend reports that the
 * order list predates is appended rather than silently lost - a new pipeline
 * status should still be visible instead of vanishing from the chart.
 */
export function slicesFromCounts(
  counts: Record<string, number>,
  order: readonly string[],
  colors: StatusColorMap,
  colorOffset = 0,
): Slice[] {
  const out: Slice[] = []
  const seen = new Set<string>()

  order.forEach((status, i) => {
    seen.add(status)
    const value = counts[status] ?? 0
    if (value > 0) {
      out.push({
        label: titleCase(status),
        value,
        color: colors[status] ?? CHART_COLORS[(i + colorOffset) % CHART_COLORS.length],
      })
    }
  })

  for (const [status, value] of Object.entries(counts)) {
    if (!seen.has(status) && value > 0) {
      out.push({
        label: titleCase(status),
        value,
        color: CHART_COLORS[(out.length + colorOffset) % CHART_COLORS.length],
      })
    }
  }

  return out
}