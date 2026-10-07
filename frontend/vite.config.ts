import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the SPA, the Django backend and Keycloak share one origin through this proxy,
// so session cookies, CSRF and OIDC redirects work exactly as they do behind Traefik. The original
// Host header must survive the proxy: Django builds the OIDC callback URL from it, Keycloak its
// login page URLs, and Keycloak only accepts the app's own URLs as redirect targets.
const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'
const keycloak = process.env.KEYCLOAK_URL ?? 'http://127.0.0.1:8180'
const toBackend = { target: backend, changeOrigin: false }

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': toBackend,
      '/oidc': toBackend,
      '/admin': toBackend,
      '/static': toBackend,
      '/auth': {
        target: keycloak,
        changeOrigin: false,
        // Keycloak builds its URLs from these (KC_PROXY_HEADERS=xforwarded), as behind Traefik.
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            proxyReq.setHeader('X-Forwarded-Host', req.headers.host ?? 'localhost:5173')
            proxyReq.setHeader('X-Forwarded-Proto', 'http')
          })
        },
      },
    },
  },
})
