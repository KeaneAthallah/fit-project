import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { relativeTime } from '../lib/format'
import { useProcessing } from '../lib/processing-context'
import { useTheme, type ThemePreference } from '../lib/theme-context'
import { Badge, IconButton, Spinner, Tooltip } from './ui'

const NAV = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/documents', label: 'Documents', icon: 'documents' },
  { to: '/validations', label: 'Review queue', icon: 'validations' },
  { to: '/values', label: 'Values', icon: 'values' },
  { to: '/results', label: 'Results', icon: 'results' },
  { to: '/exports', label: 'Exports', icon: 'exports' },
] as const

const SIDEBAR_COLLAPSED_KEY = 'fre.sidebar'

const ICON_PATHS: Record<string, string> = {
  dashboard: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1V10.5Z',
  documents:
    'M6 2h8l4 4v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Zm8 1.5V7h3.5M8.5 12h7M8.5 16h7',
  validations:
    'M12 3 4 6v6c0 4.5 3.4 7.9 8 9 4.6-1.1 8-4.5 8-9V6l-8-3Zm-2.5 9L11 13.5 15 9',
  values: 'M4 19h16M7 16V9m5 7V5m5 11v-4',
  results:
    'M4 5h16v14H4V5Zm0 5h16M10 10v9',
  exports:
    'M12 3v12m0-12 4 4m-4-4-4 4M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2',
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'M6 6l12 12M18 6L6 18',
  collapse: 'M15 6l-6 6 6 6',
  expand: 'M9 6l6 6-6 6',
  sun: 'M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66 1.41-1.41M4.93 19.07l1.41-1.41m0-11.32L4.93 4.93m14.14 14.14-1.41-1.41M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z',
  monitor:
    'M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm4 15h8m-4-4v4',
}

function Icon({ name, className = 'h-5 w-5' }: { name: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d={ICON_PATHS[name] ?? ''} />
    </svg>
  )
}

/* ------------------------------------------------------------------ theme */

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: string }[] = [
  { value: 'light', label: 'Light', icon: 'sun' },
  { value: 'dark', label: 'Dark', icon: 'moon' },
  { value: 'system', label: 'System', icon: 'monitor' },
]

function ThemeToggle() {
  const { preference, resolved, setPreference } = useTheme()
  return (
    <div
      role="group"
      aria-label="Colour theme"
      className="flex shrink-0 items-center gap-0.5 rounded-lg border border-border bg-muted/60 p-0.5"
    >
      {THEME_OPTIONS.map((option) => {
        const active = preference === option.value
        return (
          <Tooltip key={option.value} label={option.label}>
            <button
              type="button"
              onClick={() => setPreference(option.value)}
              aria-pressed={active}
              // "System" resolves to light or dark, so the pressed state of the
              // system button is announced together with what it resolved to.
              aria-label={
                option.value === 'system'
                  ? `System theme (currently ${resolved})`
                  : `${option.label} theme`
              }
              className={`inline-flex h-9 w-9 items-center justify-center rounded-md transition-colors ${
                active
                  ? 'bg-card text-foreground shadow-xs'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon name={option.icon} className="h-4 w-4" />
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}

/* --------------------------------------------------------------- sidebar */

function NavList({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Main">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={'end' in item ? item.end : false}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center rounded-md text-sm font-medium transition-colors ${
              collapsed ? 'justify-center px-2 py-2.5' : 'gap-2.5 px-2.5 py-2.5'
            } ${
              isActive
                ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                : 'text-sidebar-muted hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'
            }`
          }
        >
          {({ isActive }) => (
            <>
              <Icon name={item.icon} className="h-5 w-5 shrink-0" />
              {/* Collapsed sidebar hides the label entirely rather than
                  squeezing it; the tooltip carries the name instead. */}
              {!collapsed && <span className="min-w-0 truncate">{item.label}</span>}
              {collapsed && (
                <span className="sr-only">
                  {item.label}
                  {isActive ? ' (current page)' : ''}
                </span>
              )}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

function RunStatus({ collapsed }: { collapsed: boolean }) {
  const { state } = useProcessing()
  if (!state) return null

  const tone = state.running ? 'info' : state.error ? 'danger' : 'neutral'
  const label = state.running
    ? `Running ${relativeTime(state.started_at)}`
    : state.error
      ? 'Last run failed'
      : state.finished_at
        ? `Idle · finished ${relativeTime(state.finished_at)}`
        : 'Idle'

  const badge = (
    <Badge tone={tone} className={collapsed ? 'justify-center px-1.5' : ''} title={label}>
      {state.running ? <Spinner className="h-3 w-3 shrink-0" /> : null}
      {!collapsed && label}
    </Badge>
  )

  if (!collapsed) return <div className="px-3 py-3">{badge}</div>
  return (
    <div className="flex justify-center px-2 py-3">
      <Tooltip label={label} side="top">
        {badge}
      </Tooltip>
    </div>
  )
}

function SidebarBrand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={`flex items-center gap-2.5 px-3 py-4 ${collapsed ? 'justify-center px-0' : ''}`}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
        F
      </div>
      {!collapsed && (
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-sidebar-foreground">
            Financial Extractor
          </p>
          <p className="truncate text-[11px] text-sidebar-muted">IDX annual reports</p>
        </div>
      )}
      {collapsed && <span className="sr-only">Financial Extractor</span>}
    </div>
  )
}

/* ---------------------------------------------------------------- drawer */

/** Traps Tab inside the drawer and restores focus to the trigger on close.
 *  Without this a keyboard user tabs straight out of an open overlay and into
 *  the page behind it. */
function useDrawerFocus(
  ref: React.RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void,
) {
  const restoreTo = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    restoreTo.current = document.activeElement as HTMLElement | null

    const node = ref.current
    const focusables = () =>
      Array.from(
        node?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((el) => el.offsetParent !== null)

    focusables()[0]?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    // Stop the page behind the overlay from scrolling under the visitor's
    // finger on touch devices.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      restoreTo.current?.focus?.()
    }
  }, [open, onClose, ref])
}

function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLElement>(null)
  useDrawerFocus(ref, open, onClose)

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <aside
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-sidebar-border bg-sidebar"
      >
        <div className="flex items-center justify-between gap-2 border-b border-sidebar-border px-3 py-3">
          <p className="min-w-0 truncate text-sm font-semibold text-sidebar-foreground">
            Financial Extractor
          </p>
          <IconButton label="Close navigation" onClick={onClose} className="text-sidebar-muted">
            <Icon name="close" />
          </IconButton>
        </div>
        <NavList collapsed={false} onNavigate={onClose} />
        <RunStatus collapsed={false} />
      </aside>
    </div>
  )
}

/* ------------------------------------------------------------------ shell */

function useRouteTitle(pathname: string): string {
  if (pathname.startsWith('/documents/')) return 'Document detail'
  const match = NAV.find((item) =>
    'end' in item && item.end ? pathname === item.to : pathname.startsWith(item.to),
  )
  return match?.label ?? 'Financial Extractor'
}

export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })
  const { pathname } = useLocation()
  const routeTitle = useRouteTitle(pathname)

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        /* storage unavailable: collapse still works for this session */
      }
      return next
    })
  }

  return (
    <div className="flex min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only-focusable fixed top-3 left-3 z-60 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar. Sticky rather than fixed so the main column keeps a
          single scroll context and the page never gains a scrollbar gap. */}
      <aside
        className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-150 lg:flex ${
          collapsed ? 'w-[4.25rem]' : 'w-60'
        }`}
      >
        <SidebarBrand collapsed={collapsed} />
        <NavList collapsed={collapsed} />
        <RunStatus collapsed={collapsed} />
        <div className="border-t border-sidebar-border p-2">
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-muted transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
          >
            <Icon name={collapsed ? 'expand' : 'collapse'} className="h-5 w-5 shrink-0" />
            {!collapsed && <span className="truncate">Collapse</span>}
            {collapsed && <span className="sr-only">Expand sidebar</span>}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex items-center gap-2 border-b border-border bg-background/85 px-3 py-2 backdrop-blur-sm sm:px-4">
          <IconButton
            label="Open navigation"
            className="lg:hidden"
            aria-expanded={drawerOpen}
            aria-controls="mobile-navigation"
            onClick={() => setDrawerOpen(true)}
          >
            <Icon name="menu" />
          </IconButton>

          {/* min-w-0 + truncate: the longest route title cannot push the
              controls off the right edge of a narrow header. */}
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
            {routeTitle}
          </h1>

          <div className="hidden shrink-0 sm:block">
            <RunStatus collapsed={false} />
          </div>
          <ThemeToggle />
        </header>

        <main id="main-content" className="min-w-0 flex-1">
          {/* max-width keeps line length sane on a 1920px monitor; the
              horizontal padding is responsive. */}
          <div className="mx-auto w-full max-w-[1440px] px-3 py-4 sm:px-5 sm:py-5 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>

      <div id="mobile-navigation">
        <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      </div>
    </div>
  )
}