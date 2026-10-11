/**
 * The Web version's Worker: the LocalBackend (backend.ts) off the page's
 * thread, so a long calculation does not stop the screen. Messages:
 * { id, method, path, body } in, { id, status, kind, body, type? } out (bytes
 * transferred, not copied).
 */
import wasmUrl from 'libcascade/single/wasm?url'

import { version } from '../../package.json'
import { LocalBackend, type Answer } from './backend.ts'
import { pyodideRenderer, type DrawingRenderer } from './drawing.ts'
import { idbStore } from './idb.ts'
import { opfsCache } from './meshcache.ts'

/** OpenCASCADE, loaded on the first STEP/IGES (its 43 MB wasm is fetched then, and cached by the browser) */
const occt = async () => {
  const { createInstance } = await import('libcascade/single/init')
  return createInstance({ locateFile: (file: string) => (file.endsWith('.wasm') ? wasmUrl : file) })
}

/** where web-public/py's files are served: the page says it first (init) */
let pyBase: string | null = null
let renderer: DrawingRenderer | null = null
const drawing: DrawingRenderer = (bytes, name) => {
  if (!pyBase) throw new Error('the page has not said where py/ is')
  const base = pyBase
  renderer ??= pyodideRenderer(
    base,
    async (opts) => (await import('pyodide')).loadPyodide(opts),
    async (file) => {
      const res = await fetch(base + file)
      if (!res.ok) throw new Error(`${file}: ${res.status}`)
      return new Uint8Array(await res.arrayBuffer())
    },
  )
  return renderer(bytes, name)
}

// STEP/IGES loads kept in the origin's private file system (meshcache.ts): the second time, at once
const backend = new LocalBackend(idbStore(), version, occt, drawing, typeof navigator.storage?.getDirectory === 'function' ? opfsCache() : null)

self.onmessage = async (e: MessageEvent<{ id: number; method: string; path: string; body?: unknown; init?: { pyBase: string } }>) => {
  if (e.data.init) {
    pyBase = e.data.init.pyBase
    return
  }
  const { id, method, path, body } = e.data
  let answer: Answer
  try {
    answer = await backend.handle(method, path, body)
  } catch (err) {
    answer = { status: 500, kind: 'json', body: { detail: `Web 版の計算で誤り: ${err instanceof Error ? err.message : String(err)}` } }
  }
  const transfer = answer.kind === 'binary' ? [answer.body] : []
  ;(self as unknown as Worker).postMessage({ id, ...answer }, transfer)
}
