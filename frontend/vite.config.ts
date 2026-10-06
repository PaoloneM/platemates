import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the SPA and the Django backend share one origin through this proxy, so session
// cookies and CSRF work exactly as they do behind nginx in production. The original Host header
// must survive the proxy: Django builds the OIDC callback URL from it, and Keycloak only accepts
// the app's own URLs as redirect targets.
const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'
const toBackend = { target: backend, changeOrigin: false }

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': toBackend,
      '/oidc': toBackend,
      '/admin': toBackend,
      '/static': toBackend,
    },
  },
})
