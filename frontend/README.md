# Dashboard frontend

React + TypeScript + Tailwind CSS, built with Vite. See the "Web dashboard"
section of the repository README for how to run it against the FastAPI backend.

```bash
npm install
npm run dev      # http://localhost:5173, /api proxied to :8000
npm run build    # emits dist/, served by `python main.py dashboard`
npm run lint     # oxlint
```

`npm run build` runs `tsc -b` first, so a type error fails the build.

## Layout

| Path | Role |
| --- | --- |
| `src/index.css` | Design tokens (light/dark), base styles, shared utilities |
| `src/lib/types.ts` | Response types mirroring `app/dashboard/api.py` |
| `src/lib/api.ts` | Fetch wrapper and query-string builder |
| `src/lib/format.ts` | Indonesian number/date/rupiah formatting |
| `src/lib/palette.ts` | Chart series colours and the status colour map |
| `src/lib/slices.ts` | Small array helpers used by the charts |
| `src/lib/theme-context.ts` / `src/lib/processing-context.ts` | Context definitions |
| `src/hooks/useQuery.ts` | Fetch-on-mount hook, polling, action state |
| `src/hooks/useFilters.ts` | URL query-string filter state shared by list pages |
| `src/components/ThemeProvider.tsx` | Light/dark/system preference + persistence |
| `src/components/ProcessingProvider.tsx` | Single batch-progress poller |
| `src/components/ui.tsx` | Shared primitives: buttons, fields, tables, states |
| `src/components/badges.tsx` | Status, check, and confidence indicators |
| `src/components/charts.tsx` | Theme-aware inline SVG charts |
| `src/components/AppShell.tsx` | Sidebar, header, theme selector, mobile drawer |
| `src/pages/` | One lazily-loaded file per route |

## Conventions

- **Colour comes from tokens, never literals.** Use `bg-card`,
  `text-muted-foreground`, `border-border`, `text-primary`, and the
  `*-soft` / `*-border` status pairs. Raw palette classes such as `bg-slate-900`
  are what break dark mode, and are not to be reintroduced.
- Add a token in `@theme inline` (`src/index.css`) if a new colour is genuinely
  needed, rather than reaching for a default Tailwind palette value.
- API requests are always relative (`/api/...`). Vite proxies that to the
  backend in development and the backend serves both from one origin in
  production, so there is no base-URL environment variable to configure.
- Filter state lives in the URL query string so review-queue links are
  shareable and the back button behaves. `useUrlFilters` owns that for the
  list pages.
- Charts are inline SVG; there is no charting dependency. They read
  `var(--chart-N)`, so they follow the theme without re-rendering logic.
- Only the values themselves are colour-coded by confidence. Pass/fail
  indicators use a shape-independent red/amber/green scheme that stays
  distinguishable without relying on hue alone.
- Long tables set `hideBelow` on the columns that can be dropped on narrow
  screens instead of being rendered inside a horizontally scrolling page.
- Each route is `lazy()`-loaded in `App.tsx`, so a page is only fetched when
  visited.