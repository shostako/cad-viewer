/**
 * 位置合わせ's clicks (docs/designs/align.md): the datums on the open version
 * (1 to MAX_DATUMS of them), then the same ones on the compared version, in
 * the same order and of the same kinds. align.ts finds the motion; main.ts
 * shows each side and sends the clicks while the tool is active.
 *
 * A datum's values come from the backend (face_info, edge_info, vertex_info:
 * the B-rep's), as 座標系 takes its origin and axes (frame.ts).
 */
import { DATUM_NAMES, type Datum, type DatumPair, type Xyz } from './align'
import type { AlignAsk, AlignReply } from './alignworker'
import type { AutoAlignment, AutoStart } from './autoalign'
import type { Surface } from './compare'
import { measureEdgeInfo, measureFaceInfo, measureVertexInfo, type EntityRef } from './api'
import type { PickResult } from './picking'

/** 自動で合わせる in the Worker (autoalign.ts); cancel() stops it (the promise then never settles) */
export function runAutoAlign(a: Surface[], b: Surface[], start: AutoStart, tolerance: number): { promise: Promise<AutoAlignment>; cancel(): void } {
  const worker = new Worker(new URL('./alignworker.ts', import.meta.url), { type: 'module' })
  const promise = new Promise<AutoAlignment>((resolve, reject) => {
    worker.onmessage = (e: MessageEvent<AlignReply>) => {
      worker.terminate()
      const r = e.data
      if (r.ok) resolve(r.result)
      else reject(new Error(r.error))
    }
    worker.onerror = (e) => {
      worker.terminate()
      reject(new Error(e.message || '自動の合わせの計算が止まった'))
    }
  })
  // copies: the meshes on screen keep their arrays
  const copy = (parts: Surface[]): Surface[] =>
    parts.map((s) => ({ positions: Float32Array.from(s.positions), normals: Float32Array.from(s.normals), indices: Uint32Array.from(s.indices) }))
  const ca = copy(a), cb = copy(b)
  const transfer = [...ca, ...cb].flatMap((s) => [(s.positions as Float32Array).buffer, (s.normals as Float32Array).buffer, (s.indices as Uint32Array).buffer])
  worker.postMessage({ a: ca, b: cb, start, tolerance } satisfies AlignAsk, transfer)
  return { promise, cancel: () => worker.terminate() }
}

/** which version the clicks are on */
export type AlignSide = 'open' | 'other'

/** a datum each for the 3 turns and the 3 moves, in every combination (align.ts) */
export const MAX_DATUMS = 3

/** what a click may be (the prompt says it) */
const KINDS = '平らな面、円筒・円錐・球の面、直線・円の稜線、頂点'

/** the datum a click is on (the B-rep's values), or why it is none */
export async function datumOf(modelId: string, pick: PickResult): Promise<Datum | string> {
  const ref: EntityRef = { partId: pick.partId, kind: pick.kind, id: pick.id }
  const mark = pick.point.toArray() as Xyz
  if (pick.kind === 'vertex') return { kind: 'point', at: (await measureVertexInfo(modelId, ref)).point, mark }
  if (pick.kind === 'edge') {
    const i = await measureEdgeInfo(modelId, ref)
    if (i.curve === 'circle' && i.center && i.axis) return { kind: 'circle', at: i.center, dir: i.axis, mark }
    if (i.direction && i.start) return { kind: 'axis', at: i.start, dir: i.direction, mark }
    return 'この稜線は直線でも円でもない'
  }
  if (pick.kind === 'face') {
    const i = await measureFaceInfo(modelId, ref)
    if (i.surface === 'plane' && i.normal && i.origin) return { kind: 'plane', at: i.origin, dir: i.normal, mark }
    if (i.surface === 'cylinder' && i.center && i.axis) return { kind: 'axis', at: i.center, dir: i.axis, mark }
    if (i.surface === 'cone' && i.apex && i.axis) return { kind: 'axis', at: i.apex, dir: i.axis, mark }
    if (i.surface === 'sphere' && i.center) return { kind: 'point', at: i.center, mark }
    if (i.surface === 'torus' && i.center && i.axis) return { kind: 'circle', at: i.center, dir: i.axis, mark }
    return 'この面は平面・円筒・円錐・球・円環のどれでもない'
  }
  return '部品全体は基準にならない'
}

export interface AlignHooks {
  /** the status line says this (a prompt, a reason) */
  say(text: string): void
  /** show this version (the clicks are on it now) */
  show(side: AlignSide): void
  /** the markers of the datums chosen on the side shown: where, and their number and kind */
  marks(list: { at: Xyz; text: string }[]): void
  /** every datum has its partner: align by them */
  done(pairs: DatumPair[]): void
}

/** 位置合わせ's choice of datums (main.ts sends the clicks of the side shown while it is active) */
export class AlignTool {
  private ids: Record<AlignSide, string> | null = null
  private _side: AlignSide | null = null
  private chosen: Record<AlignSide, Datum[]> = { open: [], other: [] }
  /** a click being answered: the next one waits (it is dropped) */
  private asking = false
  /** bumped by start() and stop(): a late answer for an old choice is dropped */
  private session = 0
  private hooks: AlignHooks

  constructor(hooks: AlignHooks) {
    this.hooks = hooks
  }

  get active(): boolean {
    return this._side !== null
  }

  /** the version the clicks are on (null: none) */
  get side(): AlignSide | null {
    return this._side
  }

  /** how many datums each side has */
  get counts(): Record<AlignSide, number> {
    return { open: this.chosen.open.length, other: this.chosen.other.length }
  }

  /** begin on the open version: openId and otherId are the two versions' models (B-reps) */
  start(openId: string, otherId: string): void {
    this.session++
    this.ids = { open: openId, other: otherId }
    this.chosen = { open: [], other: [] }
    this.asking = false
    this.goTo('open')
  }

  /** give it up (what is shown is the caller's to put back) */
  stop(): void {
    this.session++
    this._side = null
    this.ids = null
    this.chosen = { open: [], other: [] }
    this.asking = false
  }

  /** Enter: on the open version with a datum or more, on to the compared version */
  next(): void {
    if (this._side === 'open' && this.chosen.open.length) this.goTo('other')
  }

  /** Backspace: the last datum of the side shown goes (on the compared version with none: back to the open one) */
  back(): void {
    if (!this._side || this.asking) return
    const list = this.chosen[this._side]
    if (list.length) list.pop()
    else if (this._side === 'other') return this.goTo('open')
    this.prompt()
  }

  /** a click on the side shown: its datum, or why not */
  async pick(pick: PickResult): Promise<void> {
    const side = this._side
    if (!side || !this.ids || this.asking || pick.id < 1) return
    const session = this.session
    this.asking = true
    try {
      const got = await datumOf(this.ids[side], pick)
      if (session !== this.session) return
      if (typeof got === 'string') return this.prompt(`${got} — `)
      if (side === 'other') {
        const want = this.chosen.open[this.chosen.other.length].kind
        if (got.kind !== want) return this.prompt(`${DATUM_NAMES[want]}を選ぶ（${DATUM_NAMES[got.kind]}だった） — `)
      }
      this.chosen[side].push(got)
      if (side === 'open' && this.chosen.open.length === MAX_DATUMS) return this.goTo('other')
      if (side === 'other' && this.chosen.other.length === this.chosen.open.length) {
        const pairs = this.chosen.open.map((open, k) => ({ open, other: this.chosen.other[k] }))
        this.stop()
        this.hooks.marks([])
        return this.hooks.done(pairs)
      }
      this.prompt()
    } catch (e) {
      if (session === this.session) this.prompt(`調べられなかった（${e instanceof Error ? e.message : e}） — `)
    } finally {
      if (session === this.session) this.asking = false
    }
  }

  private goTo(side: AlignSide): void {
    this._side = side
    if (side === 'other') this.chosen.other = []
    this.hooks.show(side)
    this.prompt()
  }

  /** the side's prompt (after `why`, a reason the last click was not taken) and its markers */
  private prompt(why = ''): void {
    const side = this._side
    if (!side) return
    const list = this.chosen[side]
    this.hooks.marks(list.map((d, k) => ({ at: d.mark, text: `${k + 1} ${DATUM_NAMES[d.kind]}` })))
    if (side === 'open') {
      const n = list.length
      const keys = n ? 'Enter で比べる版へ・Backspace で 1 つ戻す・' : ''
      this.hooks.say(`位置合わせ: ${why}開いている版の基準の ${n + 1} つ目をクリック（${KINDS}）・${keys}Esc でやめる`)
      return
    }
    const k = list.length
    const want = DATUM_NAMES[this.chosen.open[k].kind]
    this.hooks.say(`位置合わせ: ${why}比べる版で、${k + 1} つ目の基準（${want}）をクリック・Backspace で 1 つ戻す・Esc でやめる`)
  }
}
