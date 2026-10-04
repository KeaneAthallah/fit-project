/** Helpers for reading one company's metric series, shared by
 *  the entity page and the dashboard. Lives in lib rather than
 *  beside the components so components/financial.tsx exports
 *  components only (React Fast Refresh). */

import type { CompanyProfile, SummaryMetricPoint } from './types'

/** The nine indicators, in the order a reader works down them: what
 *  the company owns, then what it is worth, then the year's trading
 *  result, then tax. `sub_sector` travels with the company, not the
 *  years, so it is shown in the header rather than as a row here. */
export const OVERVIEW_FIELDS = [
  'total_assets',
  'equity_attributable_to_owners_of_parent',
  'non_controlling_interest',
  'total_equity',
  'sales_and_revenue',
  'total_profit_loss_before_tax',
  'total_profit_loss',
  'net_income',
  'income_tax_paid_operating',
] as const

/** The winning reading of one field in one year. */
export function pointAt(
  series: SummaryMetricPoint[] | undefined,
  year: number,
): SummaryMetricPoint | undefined {
  return series?.find((p) => p.year === year)
}

/** The company's sub-sector: a per-company property, resolved from
 *  the latest filing that declared one, exactly as the results grid
 *  resolves it. A 2023 filing that never printed the classification
 *  still belongs to the sector the 2024 cover declared. */
export function subsectorOf(profile: CompanyProfile): string | null {
  const series = profile.metrics.sub_sector
  if (!series) return null
  let best: SummaryMetricPoint | undefined
  for (const p of series) {
    if ((p.text_value ?? '').trim() && (!best || p.year > best.year)) {
      best = p
    }
  }
  return best?.text_value?.trim() ?? null
}
