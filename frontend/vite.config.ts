import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The FastAPI backend owns /api in production (it serves dist/ from the same
    // origin). Proxying it in dev keeps every request same-origin, so no CORS
    // preflight and no env-specific base URL to get wrong.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
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
})