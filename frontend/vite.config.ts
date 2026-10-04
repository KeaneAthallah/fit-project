import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
// The dev server owns the public port so that hot reload needs no restart and
// the URL never changes, which means the API lives on its own internal port and
// is reached through this proxy. run-dashboard.ps1 passes the port it gave
// FastAPI; the default keeps a bare `npm run dev` working against :8000.
const apiPort = process.env.FITRI_API_PORT ?? '8000'

// Vite answers 403 to any Host header it does not recognise, which is what
// stops a public server being hijacked by DNS rebinding. Loopback and *.localhost
// are allowed automatically, so a request to 127.0.0.1 works out of the box --
// but a Cloudflare quick tunnel arrives with a Host of
// <random-words>.trycloudflare.com and is refused. The hostname is different on
// every start, so the suffix is allowed rather than one literal host; a leading
// dot matches the domain itself and every subdomain. FITRI_ALLOWED_HOSTS adds
// more, comma separated, in case the tunnel provider changes.
const extraHosts = (process.env.FITRI_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((h) => h.trim())
  .filter(Boolean)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.FITRI_UI_PORT ?? 5173),
    // Fail rather than slide to the next free port: the whole point of putting
    // the dev server on the public port is that the URL does not move, and a
    // silent jump would break exactly that without saying so.
    strictPort: true,
    allowedHosts: ['.trycloudflare.com', ...extraHosts],
    // The FastAPI backend owns /api in production (it serves dist/ from the same
    // origin). Proxying it in dev keeps every request same-origin, so no CORS
    // preflight and no env-specific base URL to get wrong.
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // The backend mounts dist/assets at /assets, so asset URLs must stay
    // root-relative rather than becoming ./assets/... under a nested route.
    assetsDir: 'assets',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
})