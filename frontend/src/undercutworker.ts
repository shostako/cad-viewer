/**
 * アンダーカットの候補's Worker (undercut.ts): the parts' display meshes and
 * the pull direction in, the finer meshes and what reaches each vertex out.
 * Off the page's thread (a large part takes seconds); the same in both versions.
 */
import type { Surface } from './compare.ts'
import { reachOf, type Reach } from './undercut.ts'

export interface ReachAsk {
  parts: Surface[]
  dir: [number, number, number]
}

export type ReachReply = { ok: true; result: Reach } | { ok: false; error: string }

self.onmessage = (e: MessageEvent<ReachAsk>) => {
  try {
    const result = reachOf(e.data.parts, e.data.dir)
    const transfer: Transferable[] = []
    for (const p of result.parts) transfer.push(p.positions.buffer, p.normals.buffer, p.indices.buffer, p.reach.buffer)
    ;(self as unknown as Worker).postMessage({ ok: true, result } satisfies ReachReply, transfer)
  } catch (err) {
    ;(self as unknown as Worker).postMessage({ ok: false, error: err instanceof Error ? err.message : String(err) } satisfies ReachReply)
  }
}
