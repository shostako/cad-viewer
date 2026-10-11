/**
 * The comparison's Worker (compare.ts): the two versions' display meshes in,
 * the finer meshes and their distances out. Off the page's thread: a large pair
 * takes seconds. The same in both versions of the app (no backend).
 */
import { compare, type Comparison, type Surface } from './compare.ts'

export interface CompareAsk {
  a: Surface[]
  b: Surface[]
}

export type CompareReply = { ok: true; result: Comparison } | { ok: false; error: string }

self.onmessage = (e: MessageEvent<CompareAsk>) => {
  try {
    const result = compare(e.data.a, e.data.b)
    const transfer: Transferable[] = []
    for (const s of [result.a, result.b]) transfer.push(s.positions.buffer, s.normals.buffer, s.indices.buffer, s.offset.buffer)
    ;(self as unknown as Worker).postMessage({ ok: true, result } satisfies CompareReply, transfer)
  } catch (err) {
    ;(self as unknown as Worker).postMessage({ ok: false, error: err instanceof Error ? err.message : String(err) } satisfies CompareReply)
  }
}
