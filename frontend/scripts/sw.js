// The Web version's service worker (docs/designs/web-version.md, W7): the app
// working without the network. src/webapp.ts registers it; vite.config.ts
// writes it into the build (dist-web/sw.js) with VERSION and SHELL filled in.
//
// - installed: the page, its scripts and styles (SHELL) kept, so the page
//   opens offline.
// - every request to this site: the network first, its answer kept (the
//   OpenCASCADE and Python parts too, the first time they are used); without
//   the network (no connection), the kept answer. A server's own error (a 502
//   from a CDN, a captive portal's page) is passed on as it is. Online nothing
//   changes: the newest is always asked for (the browser's own cache keeps that
//   cheap), so nothing old stays.
// - a new version: caches of its own, the old ones dropped once it takes over.
const VERSION = __VERSION__
const SHELL = __SHELL__
const CACHE = `cad-viewer-${VERSION}`

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('cad-viewer-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return
  event.respondWith(
    fetch(req)
      .then((res) => {
        // whole answers only (a range's 206 cannot be kept)
        if (res.status === 200 && res.type === 'basic') {
          const copy = res.clone()
          event.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined))
        }
        return res
      })
      .catch(async () => {
        // by the address alone: a server's Vary (Origin, Accept-Encoding) would
        // otherwise set the page kept at install apart from the page asked for
        const kept = await caches.match(req, { cacheName: CACHE, ignoreVary: true })
        if (kept) return kept
        // a page of the app's (its address with ?… or index.html): the app's page
        if (req.mode === 'navigate') {
          const page = await caches.match(new URL('./', self.registration.scope).href, { cacheName: CACHE, ignoreVary: true })
          if (page) return page
        }
        return Response.error()
      }),
  )
})
