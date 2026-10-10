/** Measurement mode: two-click exact distance + the size of a curved pick.
 *
 * Click A → marker. Click B → server computes exact B-rep distance
 * (BRepExtrema) and we draw the dimension between the true nearest points.
 * Picking a curved edge or face also reports its exact size by its kind
 * (sizes.ts): the ⌀ of a hole or a boss (the injection-molding bread &
 * butter), the R of a fillet, the SR of a sphere, a cone's draft, or the
 * radius of curvature at the click on a B-spline.
 */
import * as THREE from 'three'
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import {
  measureDistance,
  measureEdgeInfo,
  measureFaceInfo,
  type EntityRef,
} from './api'
import type { PickResult } from './picking'
import { AREA_UNIT, LOCAL_NOTE, edgeSize, faceSize, fmt, fmtDeg, sizeText, type Size } from './sizes'
import type { Viewer } from './viewer'

/** Serializable form of an entry — persisted to the model's sidecar. */
export interface EntryData {
  /** list panel text */
  text: string
  /** 3D label content (empty = no label) */
  labelText: string
  labelPos: [number, number, number]
  line?: [[number, number, number], [number, number, number]]
  markers?: [number, number, number][]
  annotation?: boolean
  /** a distance: its line from A to B along the axes (the backend's, exact) */
  delta?: [number, number, number]
  /** a whole circle's centre (the backend's, exact) */
  centre?: [number, number, number]
  /** a face's area (mm²), its outer loop's length and its inner loops' (mm): one entry each, the loops in the perimeter's */
  area?: number
  perimeter?: number
  holes?: number[]
  /** an edge's length (mm) */
  length?: number
}

/** what a face or an edge measures by itself */
type Extent = { kind: 'face'; area: number; perimeter?: number; holes: number[] } | { kind: 'edge'; length: number }

/** 「面積 1500.000 mm²・周長 230.000」「長さ 100.000」 */
function extentText(x: Extent): string {
  if (x.kind === 'edge') return `長さ ${fmt(x.length)}`
  const loops = x.perimeter === undefined ? '' : `・周長 ${fmt(x.perimeter)}${x.holes.length ? `・内側の輪郭 ${x.holes.length} 個` : ''}`
  return `面積 ${fmt(x.area)} ${AREA_UNIT}${loops}`
}

export interface MeasureEntry {
  id: number
  label: string
  objects: THREE.Object3D[]
  data: EntryData
}

const MARKER_COLOR = 0xffb020
const DIM_COLOR = 0xffd060
/** the entry whose row the pointer is on: preselect.ts's cyan (style.css --cv-pick) */
const HOT_COLOR = 0x55d6ff
/**
 * The unit of every measured length: OCCT reads STEP and IGES into mm (its
 * default session unit), and only B-rep models are measured. Shown on the 3D
 * labels and in the list; the saved entries keep the bare numbers.
 */
export const LENGTH_UNIT = 'mm'

export class MeasureTool {
  private viewer: Viewer
  private modelId: string | null = null
  // bumped on every clearAll(): invalidates in-flight requests even when a
  // re-upload of identical content yields the same (deduped) model id
  private session = 0
  private isBrep = false
  /** part names when the model has more than one part: a pick names its part (see describe) */
  private partNames: ReadonlyMap<number, string> | null = null
  private pending: { pick: PickResult; marker: THREE.Object3D } | null = null
  /**
   * What the first point's face or edge measures by itself (its area and loops,
   * its length), once the backend has told: the status line says it, Enter
   * puts it on the list (recordPending)
   */
  private pendingExtent: Extent | null = null
  private extentListener: (() => void) | null = null
  private entries: MeasureEntry[] = []
  /** the entry lit by setHot */
  private hotId: number | null = null
  private nextId = 1
  private listeners: (() => void)[] = []
  busy = false

  constructor(viewer: Viewer) {
    this.viewer = viewer
  }

  onChange(fn: () => void): void {
    this.listeners.push(fn)
  }

  private emit(): void {
    for (const fn of this.listeners) fn()
  }

  setModel(modelId: string, isBrep: boolean, partNames?: ReadonlyMap<number, string>): void {
    this.clearAll()
    this.modelId = modelId
    this.isBrep = isBrep
    this.partNames = partNames && partNames.size > 1 ? partNames : null
    // again: clearAll told the listeners before the new model's kind was set
    // (the toolbar's 計測 shows whether this one can be measured)
    this.emit()
  }

  get available(): boolean {
    return this.modelId !== null && this.isBrep
  }

  list(): readonly MeasureEntry[] {
    return this.entries
  }

  /** a first point is chosen and waits for its partner (Esc cancels it) */
  get hasPending(): boolean {
    return this.pending !== null
  }

  /** where the chosen first point is (the marker), while it waits for its partner */
  get pendingPoint(): THREE.Vector3 | null {
    return this.pending?.pick.point ?? null
  }

  /** Handle a pick in measure mode. Returns a status message for the HUD. */
  async handlePick(pick: PickResult): Promise<string> {
    if (!this.modelId || this.busy) return ''

    if (!this.pending) {
      const marker = this.makeMarker(pick.point)
      this.viewer.overlay.add(marker)
      this.pending = { pick, marker }
      this.pendingExtent = null
      // circular entity? report its exact diameter as a bonus entry (and what
      // the face or edge measures by itself, for the status line and Enter)
      void this.reportEntityInfo(pick)
      return this.pendingStatus()
    }

    const a = this.pending
    this.pending = null
    this.pendingExtent = null
    this.busy = true
    // capture: setModel()/clearAll()/cancelPending() can run while the request
    // is in flight (each bumps session). A late result must neither be added to
    // the new model NOR reset the busy flag the active request now owns.
    const requestedModelId = this.modelId
    const requestedSession = this.session
    try {
      // the clicked points: the line stands where the user clicked (parallel faces)
      const res = await measureDistance(
        requestedModelId,
        toRef(a.pick),
        toRef(pick),
        a.pick.point.toArray() as [number, number, number],
        pick.point.toArray() as [number, number, number],
      )
      if (this.modelId !== requestedModelId || this.session !== requestedSession) {
        this.viewer.disposeOverlayObject(a.marker)
        return '' // stale: model switched mid-flight
      }
      // temporary first-click marker is replaced by the restored-from-data entry
      this.viewer.disposeOverlayObject(a.marker)
      const pa = res.pointA
      const pb = res.pointB
      const mid: [number, number, number] = [
        (pa[0] + pb[0]) / 2,
        (pa[1] + pb[1]) / 2,
        (pa[2] + pb[2]) / 2,
      ]
      const data: EntryData = {
        text: `${this.describe(a.pick)} ↔ ${this.describe(pick)} : ${fmt(res.value)}`,
        labelText: fmt(res.value),
        labelPos: mid,
        markers: [a.pick.point.toArray() as [number, number, number], pick.point.toArray() as [number, number, number]],
        ...(res.value > 1e-12 ? { line: [pa, pb] as EntryData['line'] } : {}),
        ...(res.delta ? { delta: res.delta } : {}),
      }
      this.addFromData(data)
      // two flat things not parallel: their angle too, as an entry of its own
      if (res.angle !== undefined) {
        const [ma, mb] = data.markers!
        this.addFromData({
          text: `${this.describe(a.pick)} ∠ ${this.describe(pick)} : ${fmtDeg(res.angle)}`,
          labelText: fmtDeg(res.angle),
          labelPos: [(ma[0] + mb[0]) / 2, (ma[1] + mb[1]) / 2, (ma[2] + mb[2]) / 2],
        })
        return `距離 ${fmt(res.value)}　角度 ${fmtDeg(res.angle)}`
      }
      return `距離 ${fmt(res.value)}`
    } catch (e) {
      this.viewer.disposeOverlayObject(a.marker)
      throw e
    } finally {
      // only release busy if we still own it: cancelPending() or a newer pick
      // bumps session and takes over the picker, so a stale return must not
      // clear the busy flag out from under the active request
      if (this.session === requestedSession) this.busy = false
    }
  }

  /** Build overlay graphics from serializable data and register the entry. */
  addFromData(data: EntryData): void {
    const objects: THREE.Object3D[] = []
    try {
      for (const m of data.markers ?? []) {
        const marker = this.makeMarker(new THREE.Vector3(...m))
        this.viewer.overlay.add(marker)
        objects.push(marker)
      }
      if (data.line) {
        const line = this.makeDimLine(
          new THREE.Vector3(...data.line[0]),
          new THREE.Vector3(...data.line[1]),
        )
        this.viewer.overlay.add(line)
        objects.push(line)
      }
      if (data.labelText) {
        // a length says its unit (a note is the user's own text, an angle has its °, an area its mm²)
        const label = this.viewer.makeLabel(
          data.annotation || /[°²]$/.test(data.labelText) ? data.labelText : `${data.labelText} ${LENGTH_UNIT}`,
          new THREE.Vector3(...data.labelPos),
          data.annotation ? 'note-label' : 'dim-label',
        )
        this.viewer.overlay.add(label)
        objects.push(label)
      }
    } catch (e) {
      // all or nothing: a half-built entry would leave markers no entry owns
      for (const o of objects) this.viewer.disposeOverlayObject(o)
      throw e
    }
    this.addEntry(data.text, objects, data)
  }

  /**
   * 面#6, or "cavity_block 面#6" in an assembly: in ワイヤーフレーム / 半透明 a
   * click can go through one part to another, and the HUD and the list must
   * say which part was taken.
   */
  private describe(pick: PickResult): string {
    return `${this.partPrefix(pick)}${entityName(pick)}`
  }

  /**
   * The name of a pick beside the cursor before the click (preselection):
   * describe's name with the part set off by a dot, "cavity_block · 面#6"
   * ("面#6" for a one-part model).
   */
  label(pick: PickResult): string {
    const name = this.partNames?.get(pick.partId)
    return name ? `${name} · ${entityName(pick)}` : entityName(pick)
  }

  /** "core_pin " in an assembly (see describe), "" for a one-part model */
  private partPrefix(pick: PickResult): string {
    const name = this.partNames?.get(pick.partId)
    return name ? `${name} ` : ''
  }

  toJSON(): EntryData[] {
    return this.entries.map((e) => e.data)
  }

  /**
   * Rebuild saved entries; returns how many could not be (skipped). A sidecar
   * is plain JSON that anyone can edit: one bad entry must not cost the
   * others, nor stop the load that restores them.
   */
  restore(datas: EntryData[]): number {
    let failed = 0
    for (const d of datas) {
      try {
        this.addFromData(d)
      } catch (e) {
        failed++
        console.warn('skipped a saved measurement that cannot be rebuilt', d, e)
      }
    }
    return failed
  }

  /**
   * Replace the list with saved entries (the undo of a deletion). Unlike
   * clearAll + restore, a chosen first point and a measurement in flight
   * stay: the user may have started the next one before undoing.
   * Returns how many could not be rebuilt.
   */
  replaceAll(datas: EntryData[]): number {
    for (const e of this.entries) for (const o of e.objects) this.viewer.disposeOverlayObject(o)
    this.entries = []
    const failed = this.restore(datas)
    this.emit() // also when nothing could be rebuilt
    return failed
  }

  cancelPending(): void {
    // invalidate in-flight distance / entity-info requests too — leaving
    // measure mode must not let a late response add (and autosave) an entry
    this.session++
    // free the picker immediately: the in-flight request (if any) is now stale
    // and its late response is dropped by the session guard, so don't make the
    // user wait for it to release busy. (Slow exact B-rep measurements used to
    // freeze all new picks until the abandoned request returned.)
    this.busy = false
    this.pendingExtent = null
    if (this.pending) {
      this.viewer.disposeOverlayObject(this.pending.marker)
      this.pending = null
    }
  }

  /** tell when the first point's area / length is known (the status line can say it then) */
  onPendingExtent(f: () => void): void {
    this.extentListener = f
  }

  /**
   * The status line while a first point waits for its partner: what it is,
   * what it measures by itself once known (面積 and 周長 of a face, 長さ of an
   * edge), and what the keys do.
   */
  pendingStatus(): string {
    const p = this.pending
    if (!p) return ''
    const x = this.pendingExtent
    if (!x) return `${this.describe(p.pick)} を選択 — 相手をクリックで 2 点目（Esc で取り消し）`
    return `${this.describe(p.pick)} を選択（${extentText(x)}）— 相手をクリックで 2 点目、Enter で一覧へ（Esc で取り消し）`
  }

  /**
   * Enter: put what the first point's face or edge measures by itself on the
   * list (a face: its 面積 and its 周長, an edge: its 長さ), labelled at the
   * click, and end the selection. False when there is nothing to put (no first
   * point, a vertex, or the backend has not told yet).
   */
  recordPending(): boolean {
    const p = this.pending
    const x = this.pendingExtent
    if (!p || !x) return false
    this.viewer.disposeOverlayObject(p.marker)
    this.pending = null
    this.pendingExtent = null
    const what = this.describe(p.pick) // "cavity_block 面#6" ("面#6" in a one-part model)
    const at = p.pick.point.toArray() as [number, number, number]
    if (x.kind === 'edge') {
      this.addFromData({ text: `${what} 長さ ${fmt(x.length)}`, labelText: `長さ ${fmt(x.length)}`, labelPos: at, markers: [at], length: x.length })
      return true
    }
    this.addFromData({
      text: `${what} 面積 ${fmt(x.area)} ${AREA_UNIT}`,
      labelText: `${fmt(x.area)} ${AREA_UNIT}`,
      labelPos: at,
      markers: [at],
      area: x.area,
    })
    if (x.perimeter !== undefined) {
      const holes = x.holes.length ? `（内側の輪郭 ${x.holes.length} 個: ${x.holes.map(fmt).join('・')}）` : ''
      this.addFromData({
        text: `${what} 周長 ${fmt(x.perimeter)}${holes}`,
        labelText: `周長 ${fmt(x.perimeter)}`,
        labelPos: at,
        perimeter: x.perimeter,
        holes: x.holes,
      })
    }
    return true
  }

  private async reportEntityInfo(pick: PickResult): Promise<void> {
    if (!this.modelId) return
    // same stale-response hazard as handlePick: drop late results after a model switch
    const requestedModelId = this.modelId
    const requestedSession = this.session
    // the click: where a B-spline's radius of curvature is asked, and the label of an R
    const near = pick.point.toArray() as [number, number, number]
    try {
      let size: Size | null = null
      // an edge says its length too: "円エッジ ⌀8.000 (L=25.133)", "円弧 R5.000 (L=7.854)"
      let length = ''
      let extent: Extent | null = null
      if (pick.kind === 'edge') {
        const info = await measureEdgeInfo(requestedModelId, toRef(pick), near)
        size = edgeSize(info)
        length = ` (L=${fmt(info.length)})`
        extent = { kind: 'edge', length: info.length }
      } else if (pick.kind === 'face') {
        const info = await measureFaceInfo(requestedModelId, toRef(pick), near)
        size = faceSize(info)
        extent = { kind: 'face', area: info.area, perimeter: info.perimeter, holes: info.holes ?? [] }
      }
      if (this.modelId !== requestedModelId || this.session !== requestedSession) return
      // still the first point waiting (not its partner's, not a cancelled one's)
      if (extent && this.pending?.pick === pick) {
        this.pendingExtent = extent
        this.extentListener?.()
      }
      if (!size) return
      const tag = sizeText(size)
      this.addFromData({
        text: `${this.partPrefix(pick)}${size.name} ${tag}${size.local ? LOCAL_NOTE : ''}${length}`,
        labelText: tag,
        // a whole circle's label at its centre (a hole's middle), the rest where it was measured
        labelPos: size.centre ?? size.at ?? near,
        ...(size.centre ? { centre: size.centre } : {}),
      })
    } catch {
      /* info is best-effort; distance flow continues regardless */
    }
  }

  /** Add a text annotation pinned to a 3D point. */
  addAnnotation(text: string, at: THREE.Vector3): void {
    this.addFromData({
      text: `📌 ${text}`,
      labelText: text,
      labelPos: at.toArray() as [number, number, number],
      markers: [at.toArray() as [number, number, number]],
      annotation: true,
    })
  }

  private addEntry(label: string, objects: THREE.Object3D[], data: EntryData): void {
    this.entries.push({ id: this.nextId++, label, objects, data })
    this.emit()
  }

  /**
   * Light one entry's label, line and points in the cyan of the preselection
   * (its row is under the pointer), or none (null). Only colours and a class
   * change: nothing is rebuilt.
   */
  setHot(id: number | null): void {
    if (id === this.hotId) return
    this.hotId = id
    for (const e of this.entries) {
      const hot = e.id === id
      for (const o of e.objects) {
        if (o instanceof CSS2DObject) o.element.classList.toggle('hot', hot)
        else if (o instanceof THREE.Line) (o.material as THREE.LineBasicMaterial).color.setHex(hot ? HOT_COLOR : DIM_COLOR)
        else if (o instanceof THREE.Mesh) (o.material as THREE.MeshBasicMaterial).color.setHex(hot ? HOT_COLOR : MARKER_COLOR)
      }
    }
  }

  /** the entry whose 3D label is drawn at this point of the page (client px), if any */
  entryAt(x: number, y: number): number | null {
    // the last drawn is on top
    for (let i = this.entries.length - 1; i >= 0; i--) {
      for (const o of this.entries[i].objects) {
        if (!(o instanceof CSS2DObject)) continue
        const r = o.element.getBoundingClientRect()
        // (a label out of the view is not displayed: an empty box)
        if (r.width > 0 && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return this.entries[i].id
      }
    }
    return null
  }

  remove(id: number): void {
    const i = this.entries.findIndex((e) => e.id === id)
    if (i < 0) return
    for (const o of this.entries[i].objects) this.viewer.disposeOverlayObject(o)
    this.entries.splice(i, 1)
    this.emit()
  }

  clearAll(): void {
    this.cancelPending() // bumps session — invalidates all in-flight requests
    for (const e of this.entries) for (const o of e.objects) this.viewer.disposeOverlayObject(o)
    this.entries = []
    this.emit()
  }

  private makeMarker(at: THREE.Vector3): THREE.Object3D {
    // screen-constant size via onBeforeRender scaling
    const geo = new THREE.SphereGeometry(1, 12, 12)
    // transparent at full opacity only so it draws in three's transparent
    // pass, after the see-through faces of 半透明 and the translucent section
    // cap: drawn in the opaque pass, those would blend over it
    const mat = new THREE.MeshBasicMaterial({ color: MARKER_COLOR, depthTest: false, transparent: true })
    const m = new THREE.Mesh(geo, mat)
    m.renderOrder = 999
    m.position.copy(at)
    const viewer = this.viewer
    m.onBeforeRender = () => {
      m.scale.setScalar(viewer.worldPerPixel(m.position) * 4) // ≈4px radius, either projection
    }
    return m
  }

  private makeDimLine(a: THREE.Vector3, b: THREE.Vector3): THREE.Object3D {
    const geo = new THREE.BufferGeometry().setFromPoints([a, b])
    // transparent at full opacity for the same reason as the markers
    const mat = new THREE.LineBasicMaterial({ color: DIM_COLOR, depthTest: false, transparent: true })
    const line = new THREE.Line(geo, mat)
    line.renderOrder = 998
    return line
  }
}

/** 面#6, エッジ#2, 頂点#5: the B-rep entity of a pick, as the HUD and the list name it */
function entityName(pick: PickResult): string {
  return `${{ vertex: '頂点', edge: 'エッジ', face: '面' }[pick.kind]}#${pick.id}`
}

function toRef(pick: PickResult): EntityRef {
  // Always send the topology ref. Vertex picks used to be flattened to a
  // 'point' ref, but the snapped coordinate comes from the float32 display
  // mesh — on large-coordinate STEP/IGES models that rounding defeats the
  // exact B-rep measurement. The id IS the 1-based TopTools vertex map index,
  // which the backend resolves to the exact vertex.
  return { partId: pick.partId, kind: pick.kind, id: pick.id }
}
