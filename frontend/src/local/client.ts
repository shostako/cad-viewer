/**
 * The Web version's Engine (../engine.ts): the backend's requests answered by
 * the Worker in this page (worker.ts, backend.ts), as Responses like the
 * backend's own. Nothing leaves the page.
 *
 * For the E2E scripts (e2e/engine_net.py), which hold, answer or watch the
 * app's requests by their URLs as page.route does over HTTP: when the page has
 * window.__cadEngineNet (put there by a script), every request is shown to it
 * first, and its answer after. Without it, nothing of this runs.
 */
import { EngineUnreachable, type Engine, type UploadAnswer } from '../engine.ts'

type Reply = { id: number; status: number; kind: 'json' | 'binary' | 'text'; body: unknown; type?: string }

let worker: Worker | null = null
let next = 1
const waiting = new Map<number, (r: Reply) => void>()

function ask(method: string, path: string, body?: unknown, transfer: Transferable[] = []): Promise<Reply> {
  if (!worker) {
    worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
    worker.onmessage = (e: MessageEvent<Reply>) => {
      const done = waiting.get(e.data.id)
      waiting.delete(e.data.id)
      done?.(e.data)
    }
  }
  const id = next++
  return new Promise((resolve) => {
    waiting.set(id, resolve)
    worker!.postMessage({ id, method, path, body }, transfer)
  })
}

function response(r: Reply): Response {
  if (r.kind === 'binary') return new Response(r.body as ArrayBuffer, { status: r.status, headers: { 'Content-Type': 'application/octet-stream' } })
  if (r.kind === 'text') return new Response(r.body as string, { status: r.status, headers: { 'Content-Type': r.type ?? 'text/plain' } })
  return new Response(JSON.stringify(r.body), { status: r.status, headers: { 'Content-Type': 'application/json' } })
}

// ---- the E2E scripts' hook -------------------------------------------------------

/** what a script decided for a request: let it through, answer it, or cut it */
type Decision = { action: 'continue' } | { action: 'abort' } | { action: 'fulfill'; status: number; body: string; contentType?: string }

interface Net {
  route(req: { url: string; method: string; postData: string | null }): Promise<Decision>
  /** a request going (no status; its body), answered (its status), or cut (failed) */
  observe(ev: { url: string; method: string; postData?: string | null; status?: number; failed?: boolean }): void
}

const net = (): Net | undefined => (globalThis as { __cadEngineNet?: Net }).__cadEngineNet

/**
 * the request through the script's hook (when there is one), then the Worker.
 * sent: once the request is taken (past the hook), as the last of an upload's
 * bytes going out over HTTP (a cut request was never sent)
 */
async function send(method: string, path: string, body: unknown, postData: string | null, transfer: Transferable[] = [], sent?: () => void): Promise<Reply | Response> {
  const hook = net()
  const url = new URL(path, location.href).href
  if (hook) {
    hook.observe({ url, method, postData })
    const d = await hook.route({ url, method, postData })
    if (d.action === 'abort') {
      hook.observe({ url, method, failed: true })
      throw new EngineUnreachable('the request was cut')
    }
    sent?.()
    if (d.action === 'fulfill') {
      const res = new Response(d.body, { status: d.status, headers: { 'Content-Type': d.contentType ?? 'text/plain' } })
      hook.observe({ url, method, status: d.status })
      return res
    }
  } else sent?.()
  const r = await ask(method, path, body, transfer)
  hook?.observe({ url, method, status: r.status })
  return r
}

export const localEngine: Engine = {
  async fetch(path, init) {
    const method = (init?.method ?? 'GET').toUpperCase()
    const text = typeof init?.body === 'string' ? init.body : null
    let r: Reply | Response
    try {
      r = await send(method, path, text === null ? undefined : JSON.parse(text), text)
    } catch (e) {
      // as fetch fails when the network does
      if (e instanceof EngineUnreachable) throw new TypeError('Failed to fetch')
      throw e
    }
    return r instanceof Response ? r : response(r)
  },
  async upload(file, onSent): Promise<UploadAnswer> {
    const bytes = await file.arrayBuffer()
    // nothing to send (the bytes are here already): all of it gone once the request is taken
    const r = await send('POST', '/api/models', { name: file.name, bytes }, null, [bytes], () => onSent?.(1))
    if (r instanceof Response) return { status: r.status, statusText: r.statusText, body: await r.text() }
    return { status: r.status, statusText: '', body: JSON.stringify(r.body) }
  },
}

/**
 * E2E only: a request to the engine as the backend's API would take it (the
 * scripts' page.request over HTTP); a file as { name, base64 }. Not the hook:
 * a script's own request is not the app's.
 */
;(globalThis as Record<string, unknown>).__cadEngineRequest = async (method: string, path: string, body?: unknown) => {
  let payload = body
  const file = body as { name?: string; base64?: string } | undefined
  if (file?.base64 !== undefined) {
    const raw = atob(file.base64)
    const bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
    payload = { name: file.name, bytes: bytes.buffer }
  }
  const r = await ask(method, path, payload)
  if (r.kind === 'binary') {
    const b = new Uint8Array(r.body as ArrayBuffer)
    let s = ''
    for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000))
    return { status: r.status, base64: btoa(s) }
  }
  return { status: r.status, body: r.body }
}
