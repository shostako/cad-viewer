/**
 * 座標系 (issue #59 P1 7): an origin and axes of one's own, taken from the
 * model's exact geometry, to read points and ΔX ΔY ΔZ in.
 *
 * Three clicks: the origin (a vertex, the centre of a circle or a sphere),
 * the Z axis (a plane's normal out of the solid, a straight edge, the axis of
 * a cylinder, a cone or a circle), the X axis (the same kinds; made square to
 * Z). Y is Z × X. The backend gives each exactly (measure.py's vertex_info,
 * edge_info, face_info), not the display mesh.
 *
 * Only what the screen shows changes (sizes.ts shown.frame): the saved
 * measurements and the 記録 keep the model's own coordinates. Lengths and
 * angles are the same in any frame.
 */
import { measureEdgeInfo, measureFaceInfo, measureVertexInfo, type EntityRef } from './api'
import type { PickResult } from './picking'
import type { Frame } from './sizes'

type Xyz = [number, number, number]

/** what the clicks are for, in turn ('pull': one click, the 抜き勾配's 型開き方向: startPull) */
export type FrameStep = 'origin' | 'z' | 'x' | 'pull'

/** the line of the status line that asks for the step's click */
export const FRAME_PROMPTS: Record<FrameStep, string> = {
  origin: '座標系: 原点をクリック（頂点、円の稜線か球の面の中心・Esc でやめる）',
  z: '座標系: Z 軸をクリック（平面の法線、直線の稜線、円筒・円錐・円の軸・Esc でやめる）',
  x: '座標系: X 軸をクリック（Z と同じ種類。Z に直角にそろえる・Esc でやめる）',
  pull: '型開き方向: 平らな面（その法線）、直線の稜線、円筒・円錐・円の軸をクリック（Esc でやめる）',
}

/** the prompt's own part, after its "座標系: " / "型開き方向: " */
const promptBody = (step: FrameStep) => FRAME_PROMPTS[step].replace(/^[^:]+: /, '')
/** what the status line says a step is about */
const stepName = (step: FrameStep) => (step === 'pull' ? '型開き方向' : '座標系')

/** an axis closer to Z than this (the sine of the angle) cannot make X */
const PARALLEL_SIN = 1e-6

const dot = (a: Xyz, b: Xyz) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: Xyz, b: Xyz): Xyz => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const norm = (a: Xyz) => Math.hypot(a[0], a[1], a[2])
const unit = (a: Xyz): Xyz => {
  const l = norm(a)
  return [a[0] / l, a[1] / l, a[2] / l]
}

/**
 * The frame made from an origin and two axes: Z as given, X its part square
 * to Z, Y = Z × X. null when X lies along Z (no X to make).
 */
export function makeFrame(origin: Xyz, z: Xyz, x: Xyz): Frame | null {
  const zu = unit(z)
  const xu = unit(x)
  const along = dot(xu, zu)
  const sq: Xyz = [xu[0] - along * zu[0], xu[1] - along * zu[1], xu[2] - along * zu[2]]
  if (norm(sq) < PARALLEL_SIN) return null
  const xs = unit(sq)
  return { origin: [...origin], x: xs, y: cross(zu, xs), z: zu }
}

/** a point of the origin: a vertex, the centre of a circle, of a sphere; or why not */
async function originOf(modelId: string, ref: EntityRef): Promise<Xyz | string> {
  if (ref.kind === 'vertex') return (await measureVertexInfo(modelId, ref)).point
  if (ref.kind === 'edge') {
    const i = await measureEdgeInfo(modelId, ref)
    return i.center ?? 'この稜線に中心はない'
  }
  if (ref.kind === 'face') {
    const i = await measureFaceInfo(modelId, ref)
    return i.surface === 'sphere' && i.center ? i.center : 'この面に中心はない'
  }
  return '部品全体に中心はない'
}

/** a direction of an axis: a plane's normal, a straight edge, an axis; or why not */
async function axisOf(modelId: string, ref: EntityRef): Promise<Xyz | string> {
  const why = 'この形には向きがない'
  if (ref.kind === 'edge') {
    const i = await measureEdgeInfo(modelId, ref)
    return i.direction ?? i.axis ?? why
  }
  if (ref.kind === 'face') {
    const i = await measureFaceInfo(modelId, ref)
    if (i.surface === 'plane' && i.normal) return i.normal
    return (i.surface === 'cylinder' || i.surface === 'cone') && i.axis ? i.axis : why
  }
  return why
}

export interface FrameToolHooks {
  /** the status line says this (a prompt, a reason, the result) */
  say: (text: string) => void
  /** a frame was chosen (or null: back to the model's own) */
  changed: (frame: Frame | null) => void
}

/** The three clicks that choose a frame (main.ts sends the clicks while it is active). */
export class FrameTool {
  private modelId: string | null = null
  private step: FrameStep | null = null
  private origin: Xyz | null = null
  private z: Xyz | null = null
  /** 'pull': what the direction is for */
  private onPull: ((dir: Xyz) => void) | null = null
  /** a click being answered: the next one waits (it is dropped) */
  private asking = false
  /** bumped by a new model and by stop(): a late answer for the old one is dropped */
  private session = 0
  private hooks: FrameToolHooks

  constructor(hooks: FrameToolHooks) {
    this.hooks = hooks
  }

  /** the model the clicks are on (null: none, or one without a B-rep); stops a choice under way */
  setModel(modelId: string | null): void {
    this.stop()
    this.modelId = modelId
  }

  get active(): boolean {
    return this.step !== null
  }

  get available(): boolean {
    return this.modelId !== null
  }

  /** begin: the origin's click is asked for */
  start(): void {
    if (!this.modelId) return
    this.session++
    this.step = 'origin'
    this.origin = this.z = null
    this.asking = false
    this.hooks.say(FRAME_PROMPTS.origin)
  }

  /**
   * One click instead, for the 抜き勾配's 型開き方向 (#59 P2): a plane's normal
   * out of the solid, a straight edge, the axis of a cylinder, a cone or a
   * circle, as the frame's axes are taken. `done` gets it (a unit vector).
   */
  startPull(done: (dir: Xyz) => void): void {
    if (!this.modelId) return
    this.session++
    this.step = 'pull'
    this.origin = this.z = null
    this.onPull = done
    this.asking = false
    this.hooks.say(FRAME_PROMPTS.pull)
  }

  /** what the clicks are for now (null: nothing is being chosen) */
  get choosing(): FrameStep | null {
    return this.step
  }

  /** give up the choice under way (the frame shown stays as it was) */
  stop(): void {
    this.session++
    this.step = null
    this.origin = this.z = null
    this.onPull = null
    this.asking = false
  }

  /** a click while choosing: its face, edge or vertex is asked for what the step needs */
  async pick(pick: PickResult): Promise<void> {
    const modelId = this.modelId
    const step = this.step
    if (!modelId || !step || this.asking || pick.id < 1) return
    const session = this.session
    this.asking = true
    const ref: EntityRef = { partId: pick.partId, kind: pick.kind, id: pick.id }
    try {
      const got = step === 'origin' ? await originOf(modelId, ref) : await axisOf(modelId, ref)
      if (session !== this.session) return
      // why not, and the step's prompt again: 「座標系: この稜線に中心はない — 原点をクリック（…）」
      if (typeof got === 'string') return this.hooks.say(`${stepName(step)}: ${got} — ${promptBody(step)}`)
      if (step === 'pull') {
        const done = this.onPull
        this.step = null
        this.onPull = null
        return done?.(unit(got))
      }
      if (step === 'origin') {
        this.origin = got
        this.step = 'z'
        return this.hooks.say(FRAME_PROMPTS.z)
      }
      if (step === 'z') {
        this.z = got
        this.step = 'x'
        return this.hooks.say(FRAME_PROMPTS.x)
      }
      const frame = makeFrame(this.origin!, this.z!, got)
      if (!frame) return this.hooks.say(`座標系: Z 軸と平行で X 軸にならない — ${promptBody('x')}`)
      this.step = null
      this.hooks.changed(frame)
    } catch (e) {
      if (session === this.session) this.hooks.say(`${stepName(step)}: 調べられなかった（${e instanceof Error ? e.message : e}）`)
    } finally {
      if (session === this.session) this.asking = false
    }
  }
}
