import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  THEME_STORAGE_KEY,
  ThemeContext,
  type ResolvedTheme,
  type ThemeContextValue,
  type ThemePreference,
} from '../lib/theme-context'

const VALID: readonly ThemePreference[] = ['light', 'dark', 'system']

function readStored(): ThemePreference {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY)
    return VALID.includes(raw as ThemePreference) ? (raw as ThemePreference) : 'system'
  } catch {
    return 'system'
  }
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  )
}

/**
 * Owns the light/dark/system preference, persists it, and keeps the `dark`
 * class on <html> in sync. The initial value is read back off the document so it
 * matches what the inline script in index.html already applied.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStored)
  const [systemDark, setSystemDark] = useState<boolean>(systemPrefersDark)

  // Track the OS setting so "system" reacts without a reload. Removed on unmount
  // to avoid leaking a listener for the life of the tab.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const resolved: ResolvedTheme =
    preference === 'system' ? (systemDark ? 'dark' : 'light') : preference

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
    document.documentElement.dataset.theme = preference
    try {
      localStorage.setItem(THEME_STORAGE_KEY, preference)
    } catch {
      /* storage unavailable: the theme still applies for this session */
    }
  }, [preference, resolved])

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
  }, [])

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}