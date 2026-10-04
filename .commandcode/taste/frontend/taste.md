# Frontend taste

## Numbers & financial formatting
- Indonesian conventions throughout: `.` groups thousands, `,` is the decimal mark. Compact display scales to Rp units — `Rp 12,45 T`, `Rp 850,2 M`, `Rp 425,7 Jt` — with trailing zeros dropped (`Rp 1 T`, not `Rp 12,00 T`). Confidence: 0.9
- Negative money prints in accounting parentheses: `Rp (245,6 M)`, never a bare minus sign the reader has to interpret. Confidence: 0.9
- Precision is never lost: every compact/rounded figure keeps the exact value one hover away (tooltip) or in the detail table. Confidence: 0.9
- `null`/missing is never silently rendered as `Rp 0` — it shows an em-dash or a contextual empty state unless business logic explicitly defines it as zero. Confidence: 0.9
- Year-over-year deltas show a percentage only when the previous value is positive; off a non-positive base, show a state chip instead (`kembali laba dari tahun lalu`, `rugi melebar`, `rugi menyusut`) — a percentage change out of a loss is nonsense. Confidence: 0.75

## Structure & patterns
- User-facing strings live in `src/lib/strings.ts` as named-export `const` objects per area (`nav`, `dashboard`, `company`, …) — no runtime `t('key')` lookup, so a missing translation is a compile error. Established project pattern. Confidence: 0.7
- Financial field labels live in `src/lib/field-labels.ts` with `short` + `full` variants: long official Indonesian line-item names render short on cards/tables with the full official name in tooltips, so long labels never overflow or break layout. Confidence: 0.8
- Charts are hand-rolled SVG — the project has no chart library. Colors come from theme tokens (`fill-primary`, `bg-accent`, …) so dark mode works without a second style set; the zero baseline is real, with losses drawn below zero, never `Math.abs`-scaled upward. Charts must be readable within 2–3 seconds: fixed height, no 3D, no decorative charts, no overlapping labels, no chart overflow (internal horizontal scroll instead), minimal animation. Confidence: 0.75
- `components/*.tsx` files export components only — shared helpers and constants (field lists, series pickers) live in `lib/` (e.g. `lib/metrics.ts`). oxlint enforces the split, and moving helpers out of a component file also fixes React Fast Refresh warnings. Confidence: 0.9
- Enum/status display labels are shared, never re-translated per page: import the existing `DOC_STATUS_LABELS` / `CHECK_STATUS_LABELS` / `VALUE_STATUS_LABELS` constants from `strings.ts` (composing with a prefix string like `${s.validationPrefix} ${CHECK_STATUS_LABELS.VALID}`) when building filter options, badges, or selects — no duplicate translations for the same enum. Confidence: 0.9

## Product information architecture (locked decisions)
- The product is organized around 9 primary financial indicators — they are the core information hierarchy, not secondary metadata. The entity page leads with 4 KPI cards (Jumlah Aset, Jumlah Ekuitas, Penjualan dan Pendapatan Usaha, Jumlah Laba (Rugi)), then equity composition, profitability and asset/equity trend charts, the tax card, and the Ikhtisar Keuangan table (all 9 indicators × years + Perubahan). The home Dashboard leads with the corpus financial pulse (subsector coverage, top companies per headline figure with comparison bars, per-indicator coverage chips); pipeline-health cards sit below. The user locked both structures via ask_user_question. Confidence: 0.85
- Subsektor is a per-company property, resolved from the latest declaration that printed one (an older filing without the classification still belongs to the newest cover's sector) — shown as a header badge, never dressed up as a financial KPI card. Confidence: 0.8
- Equity composition renders as connected figures (Pemilik Entitas Induk + Kepentingan Non Pengendali = Jumlah Ekuitas) with a stacked proportion bar; a missing NCI shows parent against total — the bar never rescales a partial declaration to 100%. Confidence: 0.8
- The tax cash-flow card is sign-aware by design: negative → "Pembayaran pajak penghasilan", positive → "Penerimaan pengembalian pajak" — the sign is the meaning, not a detail for the reader to guess. Confidence: 0.75
- Every financial figure shows provenance when the data carries it — `Sumber: {filename} · Halaman {page}`, linking to the document — but it is never invented and is simply omitted when a reading has no document. Confidence: 0.8
- Backend aggregates that feed rankings or coverage counts must reuse the results grid's winner rules (`_summary_rank`: hand correction → extractor confidence → lowest id as tie-break) and count distinct companies; an undated reading (year null) never wins a "latest year" slot. A dashboard leader must never disagree with the grid. Confidence: 0.75

## Testing & debugging
- When visible strings change, component tests must be updated to assert the new strings — tests assert aria-labels/visible text, not keys. Confidence: 0.9
- When a page crashes at render after localization, run its component test (`npx vitest run`) — tests render the full page, so a runtime crash (e.g. a string key missing from the actual `strings.ts` section) fails them; always read the real `strings.ts` section for exact key names before wiring a page to it. Confidence: 0.85
