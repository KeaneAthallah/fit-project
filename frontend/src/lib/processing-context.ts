import { createContext, useContext } from 'react'
import type { ProcessingState } from './types'

export interface ProcessingContextValue {
  state: ProcessingState | null
  error: string | null
  loading: boolean
  /** False on the very first load, so a poll does not blank the UI. */
  initialLoading: boolean
  refetch: () => void
}

export const ProcessingContext = createContext<ProcessingContextValue | null>(null)

/**
 * Batch progress is app-wide state: the sidebar indicator, the dashboard card,
 * the documents table and the exports banner all want the same answer. Polling
 * once here and sharing it removes four redundant requests per interval.
 */
export function useProcessing(): ProcessingContextValue {
  const ctx = useContext(ProcessingContext)
  if (!ctx) throw new Error('useProcessing must be used inside <ProcessingProvider>')
  return ctx
}