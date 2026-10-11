import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'

// mode "web" (npm run build:web / dev:web): the Web version, whose engine is in
// the page (src/local/, .env.web sets VITE_CAD_ENGINE=local); served from any
// folder (GitHub Pages: /cad-viewer/), built into dist-web
// the checkout's /api goes to its backend; the Web version has none to go to
// (preview takes server.proxy unless told otherwise: an E2E against the Web
// version's preview once reached a backend running on :8008 that way)
const backendProxy = { '/api': { target: 'http://127.0.0.1:8008', changeOrigin: true } }

/** the Web version as an app: its manifest (web-public/manifest.webmanifest) named in the page */
function webManifest(): Plugin {
  return {
    name: 'cad-viewer-manifest',
    transformIndexHtml: () => [
      { tag: 'link', attrs: { rel: 'manifest', href: 'manifest.webmanifest' }, injectTo: 'head' },
      { tag: 'link', attrs: { rel: 'icon', href: 'icon-192.png' }, injectTo: 'head' },
      { tag: 'meta', attrs: { name: 'theme-color', content: '#1d2126' }, injectTo: 'head' },
    ],
  }
}

/** files kept when the service worker is installed: the page's own; the large ones (OpenCASCADE's wasm) as they are used */
const SHELL_MAX_BYTES = 2_000_000

/**
 * the service worker (scripts/sw.js) written into the build, with the page's
 * files to keep (SHELL) and a version from them (a new build, new caches)
 */
function serviceWorker(): Plugin {
  return {
    name: 'cad-viewer-sw',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const shell = ['./', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png']
      const hash = createHash('sha256')
      for (const [file, item] of Object.entries(bundle).sort(([a], [b]) => a.localeCompare(b))) {
        const body = item.type === 'chunk' ? item.code : item.source
        hash.update(file).update(body)
        const size = typeof body === 'string' ? Buffer.byteLength(body) : body.byteLength
        if (file.endsWith('.map') || file === 'index.html' || size > SHELL_MAX_BYTES) continue
        shell.push(file)
      }
      hash.update(readFileSync('web-public/manifest.webmanifest'))
      const source = readFileSync('scripts/sw.js', 'utf-8')
        // functions: a string replacement would read $& and $' in it as patterns
        .replace('__VERSION__', () => JSON.stringify(hash.digest('hex').slice(0, 16)))
        .replace('__SHELL__', () => JSON.stringify(shell))
      this.emitFile({ type: 'asset', fileName: 'sw.js', source })
    },
  }
}

export default defineConfig(({ mode }) => ({
  base: mode === 'web' ? './' : '/',
  build: { outDir: mode === 'web' ? 'dist-web' : 'dist' },
  worker: { format: 'es' },
  server: { proxy: mode === 'web' ? {} : backendProxy },
  preview: { proxy: mode === 'web' ? {} : backendProxy },
  // libcascade finds its glue and wasm next to its own module (import.meta.url),
  // pyodide its node: imports only in Node: neither pre-bundled into Vite's cache
  optimizeDeps: mode === 'web' ? { exclude: ['libcascade', 'pyodide'] } : undefined,
  // the Web version's Python for drawings (web-public/py/, scripts/web-assets.mjs);
  // the checkout's version has nothing to copy
  publicDir: mode === 'web' ? 'web-public' : false,
  // the Web version: installable, offline (src/webapp.ts)
  plugins: mode === 'web' ? [webManifest(), serviceWorker()] : [],
}))
