/**
 * 自動で合わせる's Worker (autoalign.ts): the two versions' display meshes, the
 * alignment to start from and the tolerance in, the placements found out. Off
 * the page's thread: a search from several placements takes seconds. The same
 * in both versions of the app (no backend).
 */
import { autoAlign, type AutoAlignment, type AutoStart } from './autoalign.ts'
import type { Surface } from './compare.ts'

export interface AlignAsk {
  a: Surface[]
  b: Surface[]
  start: AutoStart
  tolerance: number
}

export type AlignReply = { ok: true; result: AutoAlignment } | { ok: false; error: string }

self.onmessage = (e: MessageEvent<AlignAsk>) => {
  try {
    const { a, b, start, tolerance } = e.data
    ;(self as unknown as Worker).postMessage({ ok: true, result: autoAlign(a, b, start, tolerance) } satisfies AlignReply)
  } catch (err) {
    ;(self as unknown as Worker).postMessage({ ok: false, error: err instanceof Error ? err.message : String(err) } satisfies AlignReply)
  }
}
