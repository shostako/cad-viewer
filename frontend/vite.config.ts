import { defineConfig } from 'vite'

// mode "web" (npm run build:web / dev:web): the Web version, whose engine is in
// the page (src/local/, .env.web sets VITE_CAD_ENGINE=local); served from any
// folder (GitHub Pages: /cad-viewer/), built into dist-web
// the checkout's /api goes to its backend; the Web version has none to go to
// (preview takes server.proxy unless told otherwise: an E2E against the Web
// version's preview once reached a backend running on :8008 that way)
const backendProxy = { '/api': { target: 'http://127.0.0.1:8008', changeOrigin: true } }

export default defineConfig(({ mode }) => ({
  base: mode === 'web' ? './' : '/',
  build: { outDir: mode === 'web' ? 'dist-web' : 'dist' },
  worker: { format: 'es' },
  server: { proxy: mode === 'web' ? {} : backendProxy },
  preview: { proxy: mode === 'web' ? {} : backendProxy },
  // libcascade finds its glue and wasm next to its own module (import.meta.url):
  // not pre-bundled into Vite's cache, where they are not
  optimizeDeps: mode === 'web' ? { exclude: ['libcascade'] } : undefined,
}))
