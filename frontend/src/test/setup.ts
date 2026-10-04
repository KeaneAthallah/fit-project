import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library only self-cleans when Vitest globals are enabled, and this
// suite imports `describe`/`it` explicitly instead. Without this every render
// would accumulate in the same document.
afterEach(() => {
  cleanup()
})