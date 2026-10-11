import { defineConfig } from 'vite'

// mode "web" (npm run build:web / dev:web): the Web version, whose engine is in
// the page (src/local/, .env.web sets VITE_CAD_ENGINE=local); served from any
// folder (GitHub Pages: /cad-viewer/), built into dist-web
export default defineConfig(({ mode }) => ({
  base: mode === 'web' ? './' : '/',
  build: { outDir: mode === 'web' ? 'dist-web' : 'dist' },
  worker: { format: 'es' },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8008',
        changeOrigin: true,
      },
    },
  },
}))
