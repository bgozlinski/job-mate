/// <reference types="vitest/config" />
import tailwind from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const API = process.env.JOBMATE_API_URL ?? 'http://localhost:8000'

// Everything the browser loads comes from this server, including /api. That
// is not a convenience: the session lives in cookies, and cookies belong to
// an origin. Served from one origin the browser sends them with no CORS
// preflight and no SameSite=None, and SameSite=Lax is enough to stand in for
// a CSRF token (see app/auth/cookies.py). Pointing the app straight at
// :8000 instead would need all three of those loosened, in development only,
// which is how a deployment ends up with a login that works locally and
// nowhere else.
//
// The prefix is stripped on the way out because the API has no /api: FastAPI
// serves /auth, /documents, /resumes at the root. The prefix exists to tell
// this server which requests are not its own.
export default defineConfig({
  plugins: [react(), tailwind()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: API,
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
