# AGENTS.md — agent handbook for Fitri

Indonesian annual-filing (inline XBRL/HTML) extraction pipeline + web
dashboard: Python FastAPI backend, React 19 + Vite SPA, SQLite storage.
The UI is fully Indonesian. `README.md` is the user-facing doc;
`.commandcode/memory/codebase.md` holds the longer orientation notes.

## Run & validate

- Backend tests: `python -m pytest tests/ -q` (repo root)
- Frontend: from `frontend/` — `$env:NODE_ENV='test'; npx vitest run`,
  then `npx tsc -b`, then `npx oxlint`. All three must pass before work
  is done. (`NODE_ENV=test` is required: the shell sets
  `NODE_ENV=production`, which fails every RTL test.)
- Dev servers: `./run-dashboard.ps1` (Vite on :8000 proxying `/api`).
  It refuses to start if :8000 is busy — a leftover dev server from an
  earlier session is common; check before assuming.

## Layout

- `app/` — `core/` config, `ingestion/` scanner, `extraction/` (html,
  ocr, tables), `financial/` (parser, normalizer, mappings, validators),
  `ai/` provider abstraction, `storage/` SQLAlchemy models + Repository,
  `pipeline/` processor + orchestrator, `export/` (openpyxl workbook,
  csv), `dashboard/` FastAPI JSON API (`api.py`), SPA hosting
  (`server.py`) and the listing register (`pencatatan.py`), `cli/`
  click commands.
- `frontend/src/` — `pages/` (Dashboard, Documents, DocumentDetail,
  CompanyDetail, Values, Validations, Results, Exports),
  `components/ui.tsx` (the design system), `components/financial.tsx`
  (indicator components), `hooks/` (`useQuery`, `useUrlFilters` —
  filter state lives in the URL), `lib/` (`api.ts`, `types.ts`,
  `format.ts`, `strings.ts` — every user-facing string, Indonesian,
  named-export const objects).

## Load-bearing rules

- One folder = one document (`XBRL/<company>/<year>/`); the cover is
  authoritative for presentation scale and currency.
- **A company has ONE sub-sector** (IDX classification), resolved from
  all its filings, riding on `ExtractedValue.text_value` — it is a
  sentence, not a figure.
- **Accuracy beats coverage**: unknown stays `null`, never 0; "not
  detected" currency is its own bucket, never conflated with IDR.
- The results grid (`_summary_scope` in `app/dashboard/api.py`) picks
  ONE winner per (company, year, field): hand correction > confidence >
  lowest id. The grid and the Excel export both start there, so a
  download is the table on screen, not a second answer.
- Disputed readings (readings disagree by more than half the max) have
  NO winner — the cell carries every reading as `candidates` until a
  hand correction settles it.
- Figures are shown digit-for-digit with Indonesian formatting
  (`1.234.567,89`, negatives in parentheses).
- `tanggal pencatatan.xlsx` (repo root) is the IDX listing register:
  kode, nama, tanggal per company. `app/dashboard/pencatatan.py` joins
  it onto every results row by normalized company name (PT/Tbk. and
  punctuation ignored, ticker optional) and backs the "Tanggal
  Pencatatan" column and the "Di bawah tahun 2020" filter — which
  keeps only companies listed before that year. A company the register
  does not know is hidden by the filter: an unknown is not a "yes". A
  missing or empty register is a loud error, never a silent empty
  mapping (which would hide every company and read as a broken table).
- Field sets are defined in several layers (backend `mappings.py` and
  coverage constants, frontend `metrics.ts`/`field-labels.ts`, the
  pytest suites) and can drift — enumerate the actual members before
  asserting consistency.

## Conventions

- Scanning vocabulary (`app/financial/mappings.py`) and display labels
  (`FIELD_TITLES`, `strings.ts`) are strictly separate layers — a
  scanning change never touches labels, and vice versa.
- Every user-facing string lives in `frontend/src/lib/strings.ts`; a
  missing key is a compile error, not a runtime one.
- Frontend tests use plain RTL matchers only (no jest-dom):
  `toBeTruthy()`, never `toBeInTheDocument()`.
- `components/*.tsx` exports components only; shared helpers and
  constants live in `lib/`.
- `shell_command` runs under cmd.exe and mangles `;` chains; use the
  PowerShell tool when environment variables are needed. PowerShell has
  no heredocs — write multi-line commit messages to a file and pass
  `git commit -F <path>`.
