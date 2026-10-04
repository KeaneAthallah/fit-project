# Finance Report Extractor

Extract structured financial data from hundreds of Indonesian annual filings
(inline XBRL, downloaded as HTML by `download-idx-xbrl.ps1`) and consolidate
everything into **one Excel workbook** — with full provenance, validation,
confidence scoring, and a resumable processing database.

A PDF path is still supported for scanned filings, but the current corpus is
XBRL, which is already text and never goes through OCR.

## What it does

```text
SCAN → [HTML: read filing folder] / [PDF: CLASSIFY TEXT/SCANNED/HYBRID → TEXT/OCR]
     → CLASSIFY PAGES → TABLE EXTRACTION → NORMALIZE NUMBERS & UNITS
     → RULE-BASED + AI EXTRACTION → VALIDATE (A = L + E, cash flow, …)
     → CONFIDENCE SCORING → REVIEW QUEUE → EXCEL
```

## XBRL corpus

Filings live in `XBRL/<company>/<year>/`, where each year folder holds one
filing: a cover, the primary statements, and (2022+) the notes, as separate HTML
files.

- **One folder = one document.** The statements only mean anything together,
  and the cover is the only page that states the presentation scale
  (`Satuan Penuh` / `Jutaan` / `Ribuan`), which no statement page repeats.
- **No OCR.** XBRL is text, so it is never rasterised or sent to Tesseract.
  Rendering markup as an image and reading it back would be pure loss. Set
  `OCR_ENGINE=none` to disable OCR for the PDF path as well.
- **Year comes from the folder**, because statement filenames are taxonomy codes
  (`1321000.html`) and carry no year.
- **Comparative columns** are kept: `2024 | 2023` becomes one observation per year,
  matching the PDF behaviour.
- **Scale and currency are read from the cover, not sniffed.** The cover's
  "level of rounding" gives the multiplier (333 filings full rupiah, 175
  millions, 37 thousands) and "presentation currency" gives the ISO code. That
  second field matters: 17 of the 545 filings (ANJT, FISH, PMMP, MSJA) report in
  **USD**, so assuming IDR would mislabel them. Neither is stated on any
  statement page.
- **Taxonomy variants** are handled by page title, not filename, so the income
  statement is found whether IDX filed it as `1321000.html` or `1311000.html`.
- `XBRL` is git-ignored: ~2.5 GB of third-party data across ~11k files.
  Regenerate with `.\download-idx-xbrl.ps1`.

### Known gap: AMRT 2022 has no filing of its own

`XBRL\AMRT Sumber Alfaria Trijaya Tbk\2022` holds `instance.xbrl` rather than
HTML, because IDX serves a truncated `inlineXBRL.zip` for it (217,438 bytes with
no central directory — it is corrupt at the source, not in transit). The
downloader falls back to `instance.zip`, which is a plain XBRL instance document:
636 `idx-cor` facts and no HTML table, so the label-based extractor reads nothing
from it. The scanner is HTML-only and skips that year, giving **545 filings
instead of 546**.

**No figures are lost.** Every filing carries its prior year as a comparative
column, so AMRT's 2023 filing supplies 2022 — the identity still closes
(liabilities 19,275,574 + equity 11,470,692 = total assets 30,746,266) and the
dashboard reports 2022 in full. The only loss is provenance: those figures are
attributed to the 2023 document rather than a 2022 one, so per-document
validation for that year runs against the 2023 filing. Recovering the document
would mean a separate concept-based XBRL extractor contributing no new values,
so it is deliberately not implemented.

## Features

- **Indonesian number parsing**: `1.234.567,89`, `(1.500.000)` → `-1500000`, `Rp …`
- **Unit detection**: `Dalam jutaan Rupiah` → values scaled to full Rupiah (originals preserved). For XBRL the cover's declared scale is authoritative
- **Multi-year tables**: one row with `2024 | 2023` columns becomes one observation per year
- **Label mapping (ID + EN)**: `Kas dan Setara Kas`, `Cash and Cash Equivalents`, … → canonical fields
- **Equity coverage**: `Modal Ditempatkan dan Disetor` → `issued_and_paid_up_capital`, authorized vs issued vs paid-up kept separate, treasury shares split into **quantity / nominal / carrying value / percentage** (a share count is never mistaken for money)
- **Validation**: evidence-based accounting checks → `VALID / WARNING / REVIEW_REQUIRED / ERROR / NOT_APPLICABLE / NOT_FOUND`. Missing optional fields are **not** errors; checks only run when all required values exist
- **Dual tolerance**: a check passes when the difference is within `VALIDATION_ABSOLUTE_TOLERANCE` **or** `VALIDATION_RELATIVE_TOLERANCE` (absolute tolerance scales with the report unit)
- **Never hallucinate**: unknown values stay `null` and go to the review queue
- **Resumable**: SQLite tracks every document; restart where you left off
- **Duplicate detection**: SHA-256 file hashing
- **Per-page OCR (PDF only)**: each page's text layer is checked — only pages that actually need it are OCR'd (never the whole 200-page report for one scanned page)
- **Adaptive OCR (PDF only)**: image quality decides whether deskew/denoise/binarize run; clean scans skip the expensive CV; results cached per (PDF hash, page)
- **Two-stage extraction**: cheap keyword scoring (`financial_page_score`) selects relevant pages *before* any table extraction or AI calls
- **Consolidated AI**: one structured request per page window (never one request per field); responses cached
- **Processing modes**: `--mode fast | balanced | accurate` (default balanced)
- **Parallel workers**: configurable `WORKERS`; heavy C libs release the GIL
- **Diagnostics**: `python main.py diagnose path/to/file.pdf` shows text/OCR/financial page counts, AI calls and per-stage timings

## Installation

```bash
pip install -r requirements.txt
```

To process the XBRL corpus nothing else is needed. For OCR of scanned PDFs,
install [Tesseract](https://github.com/tesseract-ocr/tesseract)
with the Indonesian language pack (`tesseract-ocr-ind`). On Windows the app
auto-detects `C:\Program Files\Tesseract-OCR\tesseract.exe`, or set
`TESSERACT_CMD` in `.env`.

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-ind
```

On Windows install from the [UB Mannheim
build](https://github.com/UB-Mannheim/tesseract/wiki) and make sure both
language packs are selected. If a language pack is missing the app does not
fail: it drops that language at startup and logs which traineddata file is
missing, so `language: "ind+eng"` against an install with only `eng` degrades
to `eng` instead of failing every page.

### Excluding the OCR scratch dir from Defender

OCR writes a full-page PNG per scanned page, and Windows Defender scans each
one on write. Excluding the scratch directory removes that per-page scan:

```powershell
# Run from an elevated PowerShell prompt
Add-MpPreference -ExclusionPath "C:\path\to\Fitri\data\tmp\tesseract"
```

The path is configurable with `ocr.temp_dir` in `config.yaml` (or
`OCR_TEMP_DIR`). The app points `tempfile` at it so tesseract's page images
never land in the shared system `%TEMP%` — that directory used to be
re-enumerated after every single OCR call by every worker, which stalled a
10-worker batch outright.

## Quick start

```bash
# Sample mode: first 5 filings only
python main.py run --input "./XBRL" --limit 5

# One company first
python main.py run --input "./XBRL/PT ABC Indonesia"

# Full pipeline: everything
python main.py run --input "./XBRL"
```

Or step by step:

```bash
python main.py scan --input "./XBRL"        # discover filings
python main.py process                              # process pending docs
python main.py export                               # Excel + reports
python main.py status                               # progress overview
python main.py inspect laporan_2024.pdf             # per-document detail
python main.py diagnose path/to/report.pdf          # timing + validation deep-dive
python main.py run --input "./XBRL" --mode fast   # speed mode
python main.py retry-failed                         # re-run failures
python main.py retry-review                         # re-run review queue
python main.py dashboard                            # web dashboard (port 8000)
python main.py remap-fields                         # preview a field rename (dry run)
python main.py remap-fields --apply                 # apply it, skipping collisions
```

`remap-fields` moves stored values from one canonical field to another, for when
a line item is filed under the wrong name. It prints its plan and writes nothing
unless `--apply` is passed. It plans the whole change first, so a row is never
read into a field that is itself being vacated, and it refuses to apply a rename
that would collide with an existing value rather than overwriting one.

## Web dashboard

The dashboard is a React single-page app served by the same FastAPI process that
exposes the JSON API, so it is deployed as one unit with no separate web server
in production.

**Development** — two processes, with Vite proxying `/api` to the backend so the
browser stays same-origin:

```bash
python main.py dashboard        # terminal 1: API on :8000
cd frontend && npm install      # terminal 2: once
cd frontend && npm run dev      # Vite on :5173, /api -> :8000
```

Open http://localhost:5173.

**Production** — build once and let FastAPI serve the bundle on a single port:

```bash
cd frontend && npm run build    # emits frontend/dist
python main.py dashboard        # serves the app and /api on :8000
```

Open http://localhost:8000. If `frontend/dist` is missing the server still
starts and falls back to a minimal server-rendered page, so the API stays usable.

The Docker image builds the frontend in a separate stage and copies `dist/` in,
so the container ships the dashboard with no Node runtime:

```bash
docker compose --profile dashboard up --build   # http://localhost:8000
```

### One-command launcher

`run-dashboard.ps1` wraps the steps above: it installs and builds the frontend
when needed, starts the backend, waits until `/api/status` answers, opens the
browser, and (unless `-NoTunnel` is passed) publishes the same port through a
Cloudflare quick tunnel for access from another machine.

```powershell
.\run-dashboard.ps1                 # production build, tunnel, browser
.\run-dashboard.ps1 -Dev            # Vite on :5173 with HMR, backend on :8000
.\run-dashboard.ps1 -NoTunnel       # localhost only
.\run-dashboard.ps1 -ForceRebuild   # ignore the cached build
```

The tunnel URL is written to `logs/dashboard-url.txt` and printed on start.
Quick tunnels are **public and unauthenticated** — anyone with the URL can read
your financial data, and the URL changes on every run. Use it for short-lived
sharing only, and pass `-NoTunnel` for normal local use.

### Interface

- **Light / Dark / System** theme selector in the header. The choice is stored
  in `localStorage` under `fre.theme`, and an inline script applies it before
  first paint so there is no flash of the wrong theme.
- **Responsive** from a phone to a wide monitor: the sidebar becomes a drawer,
  wide tables drop their least important columns, and horizontally scrolling is
  confined to the table wrapper rather than the page.
- **Accessible**: skip link, visible focus rings, keyboard-operable sortable
  column headers (`aria-sort`), labelled controls, and a focus-trapped drawer
  that closes on `Escape`.

### Pages

| Page | What it is for |
| --- | --- |
| Dashboard | Corpus coverage, validation health, confidence distribution, batch control |
| Documents | Searchable/filterable document list with per-document confidence and check counts |
| Document detail | Extracted values, validation checks, and per-page OCR text |
| Review queue | Every validation check, filterable by outcome, check, category, company, year |
| Values | Browse every extracted line item with raw vs normalised figures |
| Results | One row per company-year, one column per extracted field, editable in place |
| Exports | Generate reports, download them, and tail the processing log |

### Results

The Results page is the overview and the correction surface in one place.

- **Summary tab** — one row per (company, year), one column per extracted field.
  By default every field the scan actually produced is a column, headline
  figures first, so nothing extracted is hidden; `fields=` narrows the table.
  A field that was never extracted gets no column. Companies whose reports have
  not been read yet are reported by `GET /api/results/coverage` rather than
  being silently absent from the grid.
  Filter by company, year, and reporting currency. Each row states its own
  currency: `IDR`, `USD`, `Not detected` when no currency was found in the
  source, or `Mixed` when the figures in that row disagree. The currency filter
  only offers currencies that the displayed columns can actually match, so
  every option returns rows.
- **Click a figure** to correct it. The extracted number is kept in
  `original_value`, and **Revert** puts it back.
- **Click an empty cell** to add a figure the extractor did not find. This is
  not an edit: there is no prior reading to preserve, so the row is recorded as
  hand-entered from the start. A figure must belong to a report, so the row
  lists the reports for that company-year, preferring one that carries the same
  statement.
- **Results is the summary only** — one row per company-year, with the same
  click-to-correct and click-to-add behaviour. The row-level audit trail (raw
  label, page, statement, confidence, and edit history) lives on its own
  **Values** page, which supports searching, sorting and filtering every
  extracted figure.

Corrections and added figures both survive re-processing. An edit is reattached
to the extractor's row; an added figure is kept as its own row, because dropping
it would make "add a missing figure" the one correction a retry silently undoes.

Figures are shown in full, digit for digit. Nothing is rounded, abbreviated, or
rescaled for display (no "Rp 28,79 T"), including in the Excel export. The API
range-checks hand-entered values at `2**53 - 1`, the largest integer a browser
represents exactly, so a value that can be entered is also a value that can be
shown without loss.

## Output

```text
output/
├── financial_reports.xlsx    # 9 sheets (Summary, statements, Raw, Validation, Errors, Log)
├── processing_report.json
└── extraction_summary.json

review/                       # review queue as CSV
├── low_confidence.csv
├── extraction_errors.csv
├── validation_errors.csv
└── failed_documents.csv

data/                         # raw material: never lost
├── raw_text/                 # per-page metadata + classification
├── ocr/                      # original rendered page images
└── extracted/                # full extraction JSON per document

database/processing.db        # resumable processing state (SQLite)
logs/                         # app.log, processing.log, errors.log
```

Every extracted value carries provenance: company, document, page, raw label,
raw value, normalized value, currency, unit, method, confidence.

### Housekeeping

`reset.ps1` clears everything the pipeline generates — `output/`, `review/`,
`database/`, `logs/`, and the derived material under `data/` (`raw_text/`,
`ocr/`, `extracted/`, `cache/`, `tmp/`) — so the next run starts clean.

```powershell
.\reset.ps1 -WhatIf            # list exactly what would be deleted
.\reset.ps1 -Confirm           # delete the listed folders and the database
.\reset.ps1 -Confirm -KeepDatabase
.\reset.ps1 -Confirm -KeepLogs
.\reset.ps1 -Confirm -DeleteTessdata
```

Source PDFs under the input directory are **never** touched, and the OCR
language packs in `data/tessdata/` are kept unless you pass
`-DeleteTessdata` (deleting them means re-downloading `ind.traineddata`, see
below). Always run `-WhatIf` first: the prompt lists the resolved targets before
anything is deleted.

## Excel workbook

| Sheet | Content |
|---|---|
| Summary | One row per company/year with headline figures + confidence |
| Balance Sheet / Income Statement / Cash Flow / Equity | Field, raw label + raw value, normalized value, currency, unit, page, source-file hyperlink, confidence, extraction method |
| Raw Data | Every observation incl. raw representations |
| Validation | Accounting checks with expected/actual/difference/status/severity |
| Errors | Failed documents + failed checks |
| Processing Log | Text/OCR/financial page counts, durations, file hyperlinks |
| Diagnostics | Per-document stage timings and AI-call counts |

## AI extraction (optional)

Works fine without AI (rule-based table + label extraction). To enable:

```env
# .env — OpenAI or any OpenAI-compatible endpoint
AI_PROVIDER=openai
AI_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
SEND_TO_EXTERNAL_AI=true      # explicit acknowledgement documents leave your machine

# …or fully local with Ollama (no key, no data leaves your machine)
AI_PROVIDER=ollama
AI_MODEL=llama3.1
OLLAMA_BASE_URL=http://localhost:11434
SEND_TO_EXTERNAL_AI=true
```

Cost control: only pages classified as financially relevant are sent (in small
batches), and AI responses are cached in SQLite — reprocessing is free.

## Configuration

`config.yaml` (defaults) overridable via `.env` — see `.env.example`.
Key settings: `INPUT_DIRECTORY`, `WORKERS`, `OCR_LANGUAGE`,
`CONFIDENCE_THRESHOLD`, `VALIDATION_ABSOLUTE_TOLERANCE`,
`VALIDATION_RELATIVE_TOLERANCE`, `PROCESSING_MODE`,
`MAX_AI_CONCURRENT_REQUESTS`, `AI_PROVIDOR`.
API keys live only in `.env` (gitignored).

Under `ocr:` — `temp_dir` (tesseract scratch dir, see above), `max_concurrent`
(simultaneous tesseract processes; each one is itself multi-threaded, so this
is usually well below `workers`), `detect_orientation` (off: `image_to_osd`
costs a second tesseract run per page), `dpi`, `language`, `cache`.

### OCR language packs

`ocr.tessdata_dir` points tesseract at `data/tessdata/` instead of the install
directory, which is read-only without admin rights on Windows. It **replaces**
the default search path, so it must contain every language you use:

```powershell
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" data\tessdata\
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" data\tessdata\
Invoke-WebRequest https://github.com/tesseract-ocr/tessdata/raw/main/ind.traineddata -OutFile data\tessdata\ind.traineddata
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --tessdata-dir data\tessdata --list-langs
```

Missing packs are not fatal: the requested language is reduced to the packs
that are installed (with one warning per run), and the OCR cache is keyed on
the *resolved* language, so installing a pack and re-running does re-OCR.

### Windows performance: Defender and OCR

OCR is I/O bound, and on Windows two things make it far slower than expected:

1. **Antivirus.** Every rendered page is written to disk as a PNG and read back
   by tesseract. Excluding the scratch dir removes two scan passes per page:
   ```powershell
   # elevated PowerShell
   Add-MpPreference -ExclusionPath "C:\path\to\data\tmp\tesseract"
   Set-MpPreference -ExclusionPath "C:\path\to\data\tmp\tesseract"
   ```
2. **Scratch dir.** pytesseract writes into the system temp dir and re-globs
   it after every call, so a busy `%TEMP%` turns each OCR page into a full
   directory scan. `ocr.temp_dir` keeps that directory tiny instead.

### Processing modes

| Mode | OCR (PDF only) | Page filter | AI |
|---|---|---|---|
| `fast` | minimal preprocessing, 200 DPI | aggressive (score >= 5) | minimal tokens |
| `balanced` (default) | normal | normal (score >= 3) | structured extraction |
| `accurate` | deeper preprocessing, 300+ DPI | relaxed (score >= 2) | deeper table analysis |

## Docker

```bash
docker compose run --rm sample                          # 5-filing smoke test
docker compose up app                                   # full run
docker compose --profile dashboard up --build           # web dashboard on :8000
```

The image includes Tesseract with the Indonesian language pack, and builds the
React frontend in a separate stage so the dashboard is baked in without a Node
runtime. If you set `OCR_TESSDATA_DIR`, mount your own `data/tessdata` and it
will take precedence.

## Tests

```bash
python -m pytest tests/ -v
```

Covers number parsing (ID/EN), unit conversion, label mapping, year detection,
validation identities, page classification, duplicate detection, resume
behavior, and a full end-to-end pipeline run on generated text PDFs.

## Architecture

```text
frontend/            React SPA (Vite + TypeScript + Tailwind CSS)
app/
├── core/         config, logging, exceptions
├── ingestion/    scanner, pdf type detection, metadata
├── extraction/   text extraction, OCR pipeline, page classifier, tables
├── financial/    number parser, unit normalizer, label mappings, validators
├── ai/           provider abstraction (OpenAI / compatible / Ollama / none), Pydantic schemas
├── storage/      SQLAlchemy models + repository (SQLite, WAL)
├── pipeline/     document processor + batch orchestrator (thread pool)
├── export/       openpyxl workbook, review CSVs, summary reports
├── dashboard/    FastAPI JSON API + static hosting for the SPA
└── cli/          click commands
```

## Accuracy policy

This is a financial-data system: **accuracy beats coverage**. When a value
cannot be identified confidently, the system records `null` with low
confidence and routes the document/value to the review queue instead of
guessing. Validation failures are flagged, never auto-corrected.

Two consequences worth knowing when reading the data:

- **A missing figure and a zero are different.** An empty grid cell means the
  line item was not found; it never means the company reported zero. Use the
  add affordance on the cell to record a figure that exists but was not
  extracted.
- **"Not detected" is not "IDR".** Currency is only recorded when the source
  says so. Reports that do not state a currency are left unset rather than being
  stamped with a default, so the currency filter cannot claim an undetected
  document is rupiah.

Unit words are matched in both the bare and the `-an` form (`juta` / `jutaan`,
`ribu` / `ribuan`, `miliar` / `miliaran`, `triliun` / `triliunan`), because
statements mix them freely and a missed unit word leaves a figure 1,000x to
1e12x out. Whole-number amounts are parsed as integers rather than floats, so a
long figure keeps its last digit.
