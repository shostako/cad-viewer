/**
 * The Web version's Engine (../engine.ts): the backend's requests answered by
 * the Worker in this page (worker.ts, backend.ts), as Responses like the
 * backend's own. Nothing leaves the page.
 */
import type { Engine, UploadAnswer } from '../engine.ts'

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

export const localEngine: Engine = {
  async fetch(path, init) {
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    return response(await ask(method, path, body))
  },
  async upload(file, onSent): Promise<UploadAnswer> {
    const bytes = await file.arrayBuffer()
    onSent?.(1) // nothing to send: the bytes are here already
    const r = await ask('POST', '/api/models', { name: file.name, bytes }, [bytes])
    return { status: r.status, statusText: '', body: JSON.stringify(r.body) }
  },
}
