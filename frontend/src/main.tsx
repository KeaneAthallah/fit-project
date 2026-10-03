import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import { ProcessingProvider } from './components/ProcessingProvider.tsx'
import { ThemeProvider } from './components/ThemeProvider.tsx'
import './index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('Root element #root not found in index.html')
}

createRoot(container).render(
  <StrictMode>
    <ThemeProvider>
      {/* One poller for batch progress, shared by every consumer. Sits above
          the router so it keeps running while the user navigates. */}
      <ProcessingProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ProcessingProvider>
    </ThemeProvider>
  </StrictMode>,
)