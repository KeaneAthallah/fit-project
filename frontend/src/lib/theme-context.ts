import { createContext, useContext } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'fre.theme'

export interface ThemeContextValue {
  /** What the visitor chose, including "follow the operating system". */
  preference: ThemePreference
  /** What is actually on screen right now. */
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

/** Throws outside a ThemeProvider so a missing provider fails loudly at
 *  development time instead of silently rendering the wrong theme. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}