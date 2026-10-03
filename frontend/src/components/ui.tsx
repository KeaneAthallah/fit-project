import { forwardRef, useId, type ReactNode } from 'react'

/* ================================================================== layout */

/**
 * The one surface primitive in the app. Everything else - stats, tables, forms,
 * banners - is either this component or a composition of its pieces, which is
 * what keeps padding, radius and border consistent from page to page.
 */
export function Card({
  title,
  subtitle,
  actions,
  footer,
  children,
  className = '',
  padded = true,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  footer?: ReactNode
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section
      className={`flex min-w-0 flex-col rounded-lg border border-border bg-card text-card-foreground ${className}`}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-border px-4 py-3">
          {/* min-w-0 lets a long title ellipsize instead of pushing the
              action buttons off the right edge. */}
          <div className="min-w-0 flex-1">
            {title && (
              <h2 className="truncate text-sm font-semibold text-foreground" title={typeof title === 'string' ? title : undefined}>
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`min-w-0 flex-1 ${padded ? 'p-4' : ''}`}>{children}</div>
      {footer && <div className="border-t border-border px-4 py-3">{footer}</div>}
    </section>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      {/* max-w + break-words: a 200-character company name wraps instead of
          forcing the whole page to scroll sideways. */}
      <div className="min-w-0 max-w-3xl flex-1">
        <h1 className="text-xl font-semibold tracking-tight text-foreground break-words">
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground break-words">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Grid({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`grid gap-4 ${className}`}>{children}</div>
}

/* =================================================================== stats */

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent'

const TONE_TEXT: Record<Tone, string> = {
  neutral: 'text-foreground',
  info: 'text-info',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-destructive',
  accent: 'text-accent-foreground',
}

export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
  icon,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: Tone
  icon?: ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </span>
        {icon && <span className="shrink-0 text-muted-foreground">{icon}</span>}
      </div>
      {/* break-words rather than truncate: a figure must never be cut off. */}
      <div className={`tnum mt-1.5 text-2xl font-semibold break-words ${TONE_TEXT[tone]}`}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-muted-foreground break-words">{hint}</div>}
    </div>
  )
}

/* ================================================================== badges */

const BADGE_TONES: Record<Tone, string> = {
  neutral: 'bg-neutral-soft text-neutral-soft-foreground ring-border',
  info: 'bg-info-soft text-info-soft-foreground ring-info-soft',
  success: 'bg-success-soft text-success-soft-foreground ring-success-soft',
  warning: 'bg-warning-soft text-warning-soft-foreground ring-warning-soft',
  danger: 'bg-danger-soft text-danger-soft-foreground ring-danger-soft',
  accent: 'bg-accent text-accent-foreground ring-accent',
}

export function Badge({
  tone = 'neutral',
  children,
  className = '',
  title,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_TONES[tone]} ${className}`}
    >
      {/* truncate keeps a long status inside its pill; the title attribute
          keeps the full text reachable on hover. */}
      <span className="truncate">{children}</span>
    </span>
  )
}

/* =================================================================== icons */

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      // Spinners report status, so they keep animating under reduced-motion.
      data-essential-motion
      role="status"
      aria-label="Loading"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
    </svg>
  )
}

/**
 * Icon-only control. `label` is mandatory: an icon button with no accessible
 * name is invisible to a screen reader, and the tooltip is built from the same
 * string so the two can never drift apart.
 */
export function IconButton({
  label,
  children,
  className = '',
  ...rest
}: { label: string; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <Tooltip label={label}>
      <button
        type="button"
        aria-label={label}
        className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
        {...rest}
      >
        {children}
      </button>
    </Tooltip>
  )
}

/** Hover/focus tooltip. Purely additive: the control keeps its own aria-label,
 *  so removing the bubble never removes the accessible name. */
export function Tooltip({
  label,
  children,
  side = 'bottom',
}: {
  label: string
  children: ReactNode
  side?: 'top' | 'bottom'
}) {
  const position =
    side === 'top'
      ? 'bottom-full left-1/2 -translate-x-1/2 mb-1.5'
      : 'top-full left-1/2 -translate-x-1/2 mt-1.5'
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-50 hidden max-w-64 rounded-md bg-foreground px-2 py-1 text-xs whitespace-nowrap text-background shadow-md group-hover/tip:block group-focus-within/tip:block ${position}`}
      >
        {label}
      </span>
    </span>
  )
}

/* ================================================================ controls */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-primary text-primary-foreground hover:bg-primary/90 disabled:bg-primary/50',
  secondary:
    'bg-card text-secondary-foreground ring-1 ring-inset ring-border hover:bg-accent hover:text-accent-foreground disabled:opacity-50',
  ghost: 'text-muted-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-50',
  danger: 'bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:bg-destructive/50',
}

// h-10 (40px) everywhere: comfortably tappable on a phone without looking
// chunky on a desktop, which is the usual failure mode of a single scale.
const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-2.5 text-xs gap-1.5',
  md: 'h-10 px-3.5 text-sm gap-2',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  pending = false,
  children,
  className = '',
  ...rest
}: {
  variant?: ButtonVariant
  size?: ButtonSize
  pending?: boolean
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      disabled={pending || rest.disabled}
      aria-busy={pending || undefined}
      className={`inline-flex max-w-full shrink-0 items-center justify-center rounded-md font-medium transition-colors disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]} ${className}`}
      {...rest}
    >
      {pending && <Spinner className="h-3.5 w-3.5 shrink-0" />}
      {/* min-w-0 + truncate: a long label wraps-or-truncates inside the button
          rather than widening the row and overflowing the card. */}
      <span className="min-w-0 truncate">{children}</span>
    </button>
  )
}

const FIELD_BASE =
  'w-full min-w-0 rounded-md border border-input bg-card text-foreground placeholder:text-muted-foreground transition-colors hover:border-ring/60 focus:border-ring disabled:opacity-50'

export function Field({
  label,
  hint,
  htmlFor,
  children,
  className = '',
}: {
  label: ReactNode
  hint?: ReactNode
  htmlFor: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-muted-foreground break-words">{hint}</p>}
    </div>
  )
}

/** `forwardRef` so callers that open an input programmatically (e.g. an
 *  inline table-cell editor) can focus it without reaching for a native
 *  `<input>` and losing the shared field styling. */
export const Input = forwardRef<HTMLInputElement, { label?: ReactNode; hint?: ReactNode } & React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ label, hint, className = '', ...rest }, ref) {
    const id = useId()
    const input = (
      <input
        ref={ref}
        id={label ? id : undefined}
        className={`${FIELD_BASE} h-10 px-3 text-sm ${className}`}
        {...rest}
      />
    )
    if (!label) return input
    return (
      <Field label={label} hint={hint} htmlFor={id}>
        {input}
      </Field>
    )
  },
)

export function Select({
  label,
  hint,
  options,
  className = '',
  ...rest
}: {
  label?: ReactNode
  hint?: ReactNode
  options: { value: string; label: string; count?: number }[]
} & React.SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId()
  const select = (
    <select
      id={label ? id : undefined}
      className={`${FIELD_BASE} h-10 cursor-pointer px-3 text-sm ${className}`}
      {...rest}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
          {o.count !== undefined ? ` (${o.count.toLocaleString('id-ID')})` : ''}
        </option>
      ))}
    </select>
  )
  if (!label) return select
  return (
    <Field label={label} hint={hint} htmlFor={id}>
      {select}
    </Field>
  )
}

export function Checkbox({
  label,
  className = '',
  ...rest
}: { label: ReactNode } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  return (
    <label
      htmlFor={id}
      className="flex min-h-10 cursor-pointer items-center gap-2 text-sm text-foreground"
    >
      <input
        id={id}
        type="checkbox"
        className={`h-4 w-4 shrink-0 cursor-pointer rounded border-input accent-primary ${className}`}
        {...rest}
      />
      <span className="min-w-0 break-words">{label}</span>
    </label>
  )
}

/* =================================================================== table */

type Align = 'left' | 'right' | 'center'
const ALIGN: Record<Align, string> = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
}

/** Breakpoint at which a low-priority column reappears. Mobile keeps only the
 *  columns needed to identify and act on a row; the rest scroll back in as
 *  room allows. This is what stops a 10-column table forcing a 10-column
 *  horizontal scroll on a 375px screen. */
type HideBelow = 'sm' | 'md' | 'lg' | 'xl' | '2xl'
const HIDE_BELOW: Record<HideBelow, string> = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
  xl: 'hidden xl:table-cell',
  '2xl': 'hidden 2xl:table-cell',
}

/**
 * Horizontal scroll lives inside this element, never on the page: the wrapper
 * is `min-w-0` and the table is `w-full`, so a wide table can never widen the
 * body and produce page-level horizontal scrolling.
 *
 * `stickyHeader` gives the header its own scrollport, which is what makes the
 * sticky header actually stick; it is opt-in because a nested vertical
 * scroller is only an improvement on lists long enough to need one.
 */
export function Table({
  children,
  className = '',
  caption,
  stickyHeader = false,
}: {
  children: ReactNode
  className?: string
  caption?: string
  stickyHeader?: boolean
}) {
  return (
    <div
      className={`scroll-thin min-w-0 overflow-x-auto ${
        stickyHeader ? 'sticky-header max-h-[min(70vh,44rem)] overflow-y-auto' : ''
      }`}
    >
      <table className={`w-full border-collapse text-sm ${className}`}>
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  )
}

export function Th({
  children,
  align = 'left',
  onSort,
  sorted = false,
  hideBelow,
  className = '',
}: {
  children?: ReactNode
  align?: Align
  onSort?: () => void
  sorted?: 'asc' | 'desc' | false
  hideBelow?: HideBelow
  className?: string
}) {
  return (
    <th
      scope="col"
      // aria-sort belongs on the header cell, and only the active column gets a
      // value - that is what lets a screen reader announce "sorted descending".
      aria-sort={sorted ? (sorted === 'asc' ? 'ascending' : 'descending') : onSort ? 'none' : undefined}
      className={`border-b border-border bg-muted px-3 py-2 text-xs font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase ${ALIGN[align]} ${
        hideBelow ? HIDE_BELOW[hideBelow] : ''
      } ${className}`}
    >
      {onSort ? (
        <button
          type="button"
          onClick={onSort}
          className={`inline-flex items-center gap-1 rounded transition-colors hover:text-foreground ${
            align === 'right' ? 'flex-row-reverse' : ''
          }`}
        >
          <span>{children}</span>
          <SortIndicator dir={sorted} />
        </button>
      ) : (
        children
      )}
    </th>
  )
}

export function Td({
  children,
  align = 'left',
  className = '',
  mono = false,
  title,
  hideBelow,
  colSpan,
}: {
  children: ReactNode
  align?: Align
  className?: string
  mono?: boolean
  title?: string
  hideBelow?: HideBelow
  colSpan?: number
}) {
  return (
    <td
      title={title}
      colSpan={colSpan}
      className={`border-b border-border/60 px-3 py-2 align-top text-muted-foreground ${ALIGN[align]} ${
        mono ? 'font-mono text-xs' : ''
      } ${hideBelow ? HIDE_BELOW[hideBelow] : ''} ${className}`}
    >
      {children}
    </td>
  )
}

/** Inline SVG chevrons rather than text glyphs: the original used a character
 *  that never rendered, which is why the sort indicator was invisible. */
function SortIndicator({ dir }: { dir: 'asc' | 'desc' | false }) {
  if (!dir) {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-3 w-3 shrink-0 opacity-40"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        aria-hidden
      >
        <path d="M8 9l4-4 4 4M8 15l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3 w-3 shrink-0 text-primary"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      aria-hidden
    >
      {dir === 'asc' ? (
        <path d="M6 15l6-6 6 6" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  )
}

export function Tr({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <tr className={`transition-colors hover:bg-accent/40 ${className}`}>{children}</tr>
}

/* =================================================================== state */

/** Placeholder block shown while data loads. Reserves the final layout so the
 *  page does not jump when the content arrives. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className}`} />
}

export function SkeletonTable({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }, (_, c) => (
            <Skeleton
              key={c}
              className={`h-4 flex-1 ${c === 0 ? 'max-w-[14rem]' : ''}`}
              // Vary the widths so the block reads as a table, not a stack.
            />
          ))}
        </div>
      ))}
    </div>
  )
}

export function Loading({ label = 'Loading.' }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-3 py-12 text-sm text-muted-foreground"
    >
      <Spinner className="h-4 w-4 text-primary" />
      {label}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <svg
        viewBox="0 0 24 24"
        className="h-8 w-8 text-muted-foreground/50"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        aria-hidden
      >
        <path d="M4 7h16v12H4zM4 7l2-3h12l2 3" strokeLinejoin="round" />
      </svg>
      <p className="text-sm font-medium text-foreground break-words">{title}</p>
      {hint && <p className="max-w-md text-xs text-muted-foreground break-words">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** Single banner component for every informational state. Replaces the four
 *  hand-rolled alert blocks that had drifted apart in colour and spacing. */
export function Alert({
  tone = 'info',
  title,
  children,
  action,
  className = '',
}: {
  tone?: Tone
  title?: ReactNode
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  const tones: Record<Tone, string> = {
    neutral: 'bg-neutral-soft text-neutral-soft-foreground border-border',
    info: 'bg-info-soft text-info-soft-foreground border-info-soft',
    success: 'bg-success-soft text-success-soft-foreground border-success-soft',
    warning: 'bg-warning-soft text-warning-soft-foreground border-warning-soft',
    danger: 'bg-danger-soft text-danger-soft-foreground border-danger-soft',
    accent: 'bg-accent text-accent-foreground border-accent',
  }
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border px-3 py-2.5 text-sm ${tones[tone]} ${className}`}
    >
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <span className="min-w-0 break-words">
          {title && <span className="font-medium">{title} </span>}
          {children}
        </span>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <Alert
      tone="danger"
      title="Something went wrong."
      action={
        onRetry ? (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    >
      {/* Long server messages (stack traces, paths) must wrap, not overflow. */}
      <span className="wrap-anywhere">{message}</span>
    </Alert>
  )
}

export function KeyValue({
  label,
  children,
  truncate = true,
}: {
  label: string
  children: ReactNode
  truncate?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <dd
        className={`mt-0.5 text-sm text-foreground ${
          truncate ? 'truncate' : 'break-words'
        }`}
        title={typeof children === 'string' ? children : undefined}
      >
        {children}
      </dd>
    </div>
  )
}

/* ==================================================================== tabs */

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  className = '',
}: {
  tabs: { key: T; label: string; count?: number }[]
  active: T
  onChange: (key: T) => void
  className?: string
}) {
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const index = tabs.findIndex((t) => t.key === active)
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const delta = event.key === 'ArrowRight' ? 1 : -1
      const next = (index + delta + tabs.length) % tabs.length
      onChange(tabs[next].key)
    }
  }

  return (
    <div
      role="tablist"
      onKeyDown={onKeyDown}
      className={`scroll-thin -mb-px flex gap-1 overflow-x-auto border-b border-border ${className}`}
    >
      {tabs.map((tab) => {
        const selected = tab.key === active
        return (
          <button
            key={tab.key}
            role="tab"
            type="button"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.key)}
            className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors ${
              selected
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="tnum rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                {tab.count.toLocaleString('id-ID')}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/* =============================================================== pagination */

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPage,
}: {
  page: number
  pages: number
  total: number
  pageSize: number
  onPage: (page: number) => void
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-border px-4 py-3">
      <p className="tnum text-xs text-muted-foreground">
        {from.toLocaleString('id-ID')}-{to.toLocaleString('id-ID')} of{' '}
        {total.toLocaleString('id-ID')}
      </p>
      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant="secondary"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </Button>
        <span className="tnum px-2 text-xs text-muted-foreground">
          Page {page} / {Math.max(pages, 1)}
        </span>
        <Button
          size="sm"
          variant="secondary"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  )
}