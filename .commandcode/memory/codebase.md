# Codebase memory: Finance Report Extractor (Fitri)

Indonesian annual-filing (inline XBRL/HTML) extraction pipeline + web dashboard.
Python FastAPI backend, React 19 SPA frontend, SQLite storage.
The repo-root README.md is the user-facing doc — this file is the agent
orientation: where things live, the non-obvious rules, and how to validate work.

## Run & validate

- Backend tests: `python -m pytest tests/ -q` (from repo root)
- Frontend: `npx vitest run` + `npx tsc -b` + `npx oxlint` (from `frontend/`)
- **`NODE_ENV=test` is required for vitest** (`$env:NODE_ENV='test'; npx vitest run`).
  The shell has a global `NODE_ENV=production`, which loads React's production
  build and fails every RTL test with `React.act is not a function`. Pre-existing,
  affects clean HEAD too.
- Dev servers: `./run-dashboard.ps1` (Vite on :8000 proxying `/api` to FastAPI,
  HMR on, optional Cloudflare tunnel). It refuses to start if :8000 is busy —
  a leftover dev server from an earlier session is common; check before assuming.
- Backend API alone: `python main.py dashboard --host 127.0.0.1 --port <n>`

## Domain rules (these are load-bearing, not style)

- **One folder = one document**: `XBRL/<company>/<year>/` holds cover + statements
  (+ notes, 2022+). Year comes from the folder; filenames are taxonomy codes.
- **Cover is authoritative** for presentation scale (`Satuan Penuh`/`Jutaan`/`Ribuan`)
  and currency — no statement page repeats them. 17 of 545 filings report in USD.
- **A company has ONE sub-sector** (IDX classification, e.g. "43. Textile, Garment").
  It is resolved from all the company's filings, not per (company, year), and rides
  on `ExtractedValue.text_value` (not `normalized_value` — it is a sentence, not a
  figure). A 2023 row carries the classification declared on the 2024 cover.
- **Accuracy beats coverage**: unknown values stay `null` + low confidence + review
  queue. A missing figure is not a zero. "Not detected" currency is its own bucket,
  never conflated with IDR.
- Figures are shown digit-for-digit (no rounding/abbreviation, even in Excel).
  Hand-entered values are range-checked at `2**53 - 1`.
- The product is organized around **nine primary indicators** — total_assets,
  equity_attributable_to_owners_of_parent, non_controlling_interest,
  total_equity, sales_and_revenue, total_profit_loss_before_tax,
  total_profit_loss, net_income, income_tax_paid_operating
  (`OVERVIEW_FIELDS` in `frontend/src/lib/metrics.ts`; the same list drives
  `FINANCIAL_COVERAGE_FIELDS` in `app/dashboard/api.py`). They are the core
  information hierarchy on both the entity page and the home dashboard.
- **Disputed readings**: when a field's readings disagree by more than half
  of the max (`_is_disputed`, DISPUTE_THRESHOLD), the grid picks NO winner —
  the cell is flagged `disputed` and carries every reading as `candidates`.
  Confidence cannot break the tie (it is anti-correlated with correctness on
  OCR'd statements). A hand correction settles the dispute. The entity page
  shows an alert; the user picks the right reading in Results.
- The UI language is **fully Indonesian** — nav, buttons, empty/error states,
  and the official indicator names. Locked decision, not per-string.
- Indonesian numbers: `1.234.567,89`, `(1.500.000)` → negative. Unit words match
  bare and `-an` forms (`juta`/`jutaan`...).
- Confidence tiers: 1.0 primary statement page, 0.9 year zipped to a table header
  column, 0.75 notes/unsectioned page.

## Backend (`app/`)

- `core/` config (`config.yaml` + `.env` overrides, `load_config`/`set_config`),
  logging, exceptions
- `ingestion/` scanner (discovers filings), pdf type detection, metadata
- `extraction/` html_source (XBRL reader), text_extractor, ocr, page_classifier,
  table_extractor
- `financial/` parser (ID/EN numbers), normalizer (units/scale), mappings (label →
  canonical field), validators (A=L+E etc., dual tolerance), plausibility, percentage
- `ai/` provider abstraction (none/openai/compatible/ollama), prompts, Pydantic schemas
- `storage/` SQLAlchemy models + Repository (SQLite, WAL). Models: `Document`,
  `PageResult`, `ExtractedValue`, `ValidationResult`, `AIExtractionCache`,
  `ExtractionCache`. `_VALUE_COLUMNS` = all ExtractedValue columns minus
  id/document_id — `Repository.replace_values` filters row dicts through it.
- `pipeline/` processor + orchestrator (thread pool, resumable via DB)
- `export/` excel.py (openpyxl workbook), csv_export, reports
- `dashboard/` FastAPI JSON API (`api.py`) + SPA static hosting (`server.py`)
- `cli/` click commands: scan, process, run, export, status, inspect, diagnose,
  diagnose-validation, remap-fields, retry-failed, retry-review, dashboard

### Dashboard API (`app/dashboard/api.py`, prefix `/api`)

`/health`, `/documents`, `/documents/{id}`, `/documents/{id}/pages`, `/companies`,
`/companies/{company:path}`, `/validations`, `/validations/facets`, `/values`,
`/values/facets`, `PATCH /values/{id}` (edit), `POST /values` (hand-add),
`/results/summary`, `/results/summary/export` (.xlsx), `/results/coverage`,
`/summary` (dashboard stats), `/summary/financials` (corpus financial pulse),
`/processing` GET/POST, `/processing/stop`, `/log`,
`/exports` POST, `/exports/files`, `/exports/download/{name}`

- `/summary/financials` — corpus-level aggregates the home dashboard leads
  with: `subsectors` (companies per declared sub-sector, counted once per
  company, top 12), `undeclared_subsectors`, `leaders` (per
  `FINANCIAL_LEADER_FIELDS` = total_assets / sales_and_revenue /
  total_equity / total_profit_loss; top 8 by the company's LATEST reported
  year, not the largest single reading), `coverage` (distinct companies
  reporting each of the nine indicators). Computed with the grid's winner
  rules (`_summary_rank`), so a leader can never disagree with the grid.
  Undated readings (year null) count toward coverage but never win a
  "latest" slot. Covered by `TestFinancialPulse` in `tests/test_results_summary.py`.
- `/results/summary` returns `{items, fields, labels, currencies, subsectors,
  pagination}`. The `currencies`/`subsectors` lists are **scoped facets**: they
  respect the other filters but never their own (so every option returns rows), and
  a filter in force is always offered even at count 0.
- Multi-select filters travel as **repeated query params** (`?subsector=a&subsector=b`),
  never comma-joined — real classifications contain commas.
- Summary grid decision rules live in `_summary_scope` (one winner per
  (company, year) per field, ranked by edited_at > confidence > id via
  `_summary_rank`). The grid and the Excel export both start there.

## Frontend (`frontend/src/`)

- `pages/`: Dashboard, Documents, DocumentDetail, CompanyDetail, Values,
  Validations, Results, Exports
- `components/ui.tsx` — the design system, single source of visual truth: Card,
  PageHeader, Field, Input, Select, MultiSelect (h-10 trigger + popover of drawn
  checkboxes), Checkbox (drawn box, native input invisible for a11y), Table/Th/Td/Tr
  (`HideBelow` responsive column tiers), Pagination, Stat, Badge, Alert, ErrorBanner,
  EmptyState, SkeletonTable, Tabs, Tooltip, Button/ButtonLink, IconButton
- `components/badges.tsx` — DocStatusBadge, CheckBadge, ValueStatusBadge,
  Confidence (bar + Tinggi/Sedang/Rendah, 0.80 = review_threshold)
- `components/charts.tsx` — hand-rolled SVG: Donut, BarList, Histogram,
  StackedBar. No chart library anywhere. Fixed modest heights, internal
  scroll, colours from theme tokens so dark mode works for free.
- `components/financial.tsx` — the indicator components: KpiCard (compact
  value + exact-on-hover + YoY delta + source line), SourceLine,
  EquityComposition (parent + NCI = total, proportion bar that never
  rescales a partial declaration to 100%), TrendChart (zero baseline is
  real — losses drawn BELOW zero, never abs-scaled), TaxActivityCard
  (sign-aware: negative = payment, positive = refund), IkhtisarTable
  (nine indicators × years + change column)
- `hooks/`: `useQuery` (query state + polling), `useUrlFilters` (filter state in the
  URL; `multi` keys travel as repeated params, read back via `multiValues`),
  `useLiveRefresh` (poll while a batch runs), `useProcessing` context
- `lib/`: `api.ts` (`api` object + `qs()` which drops null/undefined/'' and repeats
  array values; `api.financialPulse()`), `types.ts` (`FinancialPulse`;
  `SummaryMetricPoint` carries `text_value`, `page`, `confidence`,
  `candidates`, `disputed`), `format.ts` (rupiah, `num`, `titleCase`,
  `currencyOptions`, `compactRupiah` — Rp 12,45 T / 850,2 M / 425,7 Jt,
  `deltaText`/`deltaShort` → `Delta` with tone up/down/flat/state; a
  percentage is only shown off a positive previous value, otherwise a
  state chip like `rugi melebar`), `field-labels.ts` (`FIELD_LABELS_ID`
  Indonesian names for canonical fields, `INDICATOR_META` short/full
  variants, `fieldLabel()` falls back to the API label then the key),
  `metrics.ts` (`OVERVIEW_FIELDS` — the nine indicators in reading order,
  `pointAt`, `subsectorOf` — latest declared classification wins),
  `strings.ts` (**every** user-facing string, Indonesian, as named-export
  const objects per area — `nav`, `dashboard`, `company`, `results`, … —
  plus DOC/CHECK/VALUE_STATUS_LABELS maps; no runtime `t('key')` lookup,
  so a missing translation is a compile error), `paths.ts` (`companyPath` —
  company names contain spaces/ampersands/slashes, always `encodeURIComponent`),
  `processing-context.ts`, `theme-context.ts`, `palette.ts`, `slices.ts`
- Theme: light/dark/system in `localStorage` under `fre.theme`, applied pre-paint.
- Tailwind 4 + Vite 8. No Radix — overlays (popover, tooltip) are hand-rolled.

### Dashboard (home)

- Leads with the **financial pulse** (`FinancialPulseSection`, from
  `/summary/financials`): sub-sector coverage list, per-headline-figure
  leader lists (top 8, latest reported year, comparison bars), and
  per-indicator coverage chips. Pipeline-health cards (RunBatchCard,
  RecentDocuments) sit below it.

### CompanyDetail (entity page)

- Header: company name, sub-sector badge (`subsectorOf` — per-company,
  resolved from the latest declaration), years, currencies.
- 4 KPI cards (`CORE_FIELDS`: total_assets, total_equity, sales_and_revenue,
  total_profit_loss) → equity composition + balance-sheet bars (Aset,
  Liabilitas, dan Ekuitas) + tax card row → profitability and
  assets/equity TrendCharts → IkhtisarKeuangan table (all nine indicators).
- `disputed_cells > 0` renders a warning Alert linking to the filtered
  Results grid so the user can pick the right reading.

### Results page (the main correction surface)

- One row per (company, year), one column per extracted field. Click a figure to
  correct (PATCH, original kept in `original_value`, Revert restores it); click an
  empty cell to hand-add (POST — recorded as manual from the start).
- Filters: company, year, currency, sub-sector (multi), no-net-loss (`profitable`),
  all in the URL. Page resets whenever a filter changes.
- Disputed cells open `DisputeChooser` (all readings with value/raw text/report/
  page/confidence; "Gunakan ini" PATCHes the choice). `CoverageNotice` explains
  companies absent from the grid because their filings produced no figures;
  `CompanySources` shows per-row source documents and failed checks.
- Excel export column order: Company, Year, Currency, Sub-sector, Total assets,
  Total equity, Sales and revenue, Sales, Net income, Checks failed, Source documents.

## Tests

- Backend: `tests/` (pytest; `test_results_summary.py` covers the grid decision
  rules, export, and `TestFinancialPulse`; fixture companies PT AAA/BBB/CCC Tbk
  with declared sub-sectors).
- Frontend: `src/pages/Results.test.tsx`, `src/pages/CompanyDetail.test.tsx`
  (RTL; mocks `api` via `vi.hoisted` + `vi.mock('../lib/api')`, asserts on
  `useSearchParams` state, not on rendered query strings) + `src/lib/format.test.ts`.
  Plain RTL matchers only — no jest-dom (`toBeTruthy()`, never
  `toBeInTheDocument()`).

## Gotchas

- `run-dashboard.ps1` teardown sweeps orphan python/node/cloudflared processes whose
  command line mentions the repo — re-running it kills a stale dev server.
- AMRT 2022 has no HTML filing (corrupt IDX zip); its 2022 figures come from the
  2023 filing's comparative column, attributed to the 2023 document.
- `XBRL/` is git-ignored (~2.5 GB); regenerate with `.\download-idx-xbrl.ps1`.
- API keys only in `.env` (gitignored); `send_to_external_ai` must be explicitly
  true before any text leaves the machine.
