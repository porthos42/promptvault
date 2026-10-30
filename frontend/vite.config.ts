import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Dev: Vite on :5173 proxies /api to the FastAPI backend on :8080.
// Build: output goes into the Python package so one process serves everything.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
  build: {
    outDir: '../backend/src/promptvault/static',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: false,
  },
})
