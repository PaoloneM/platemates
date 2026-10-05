import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the SPA and the Django backend share one origin through this proxy, so session
// cookies and CSRF work exactly as they do behind nginx in production.
const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
    },
  },
})
