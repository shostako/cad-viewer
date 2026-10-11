/**
 * The Web version's Worker: the LocalBackend (backend.ts) off the page's
 * thread, so a long calculation does not stop the screen. Messages:
 * { id, method, path, body } in, { id, status, kind, body, type? } out (bytes
 * transferred, not copied).
 */
import wasmUrl from 'libcascade/single/wasm?url'

import { version } from '../../package.json'
import { LocalBackend, type Answer } from './backend.ts'
import { idbStore } from './idb.ts'

/** OpenCASCADE, loaded on the first STEP/IGES (its 43 MB wasm is fetched then, and cached by the browser) */
const occt = async () => {
  const { createInstance } = await import('libcascade/single/init')
  return createInstance({ locateFile: (file: string) => (file.endsWith('.wasm') ? wasmUrl : file) })
}

const backend = new LocalBackend(idbStore(), version, occt)

self.onmessage = async (e: MessageEvent<{ id: number; method: string; path: string; body?: unknown }>) => {
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
