/** Measurement mode: two-click exact distance + entity info on circular picks.
 *
 * Click A → marker. Click B → server computes exact B-rep distance
 * (BRepExtrema) and we draw the dimension between the true nearest points.
 * Picking a circular edge / cylindrical face also reports its exact
 * diameter (hole/boss measurement, the injection-molding bread & butter).
 */
import * as THREE from 'three'
import {
  measureDistance,
  measureEdgeInfo,
  measureFaceInfo,
  type EntityRef,
} from './api'
import type { PickResult } from './picking'
import type { Viewer } from './viewer'

export interface MeasureEntry {
  id: number
  label: string
  objects: THREE.Object3D[]
}

const MARKER_COLOR = 0xffb020
const DIM_COLOR = 0xffd060

export class MeasureTool {
  private viewer: Viewer
  private modelId: string | null = null
  private isBrep = false
  private pending: { pick: PickResult; marker: THREE.Object3D } | null = null
  private entries: MeasureEntry[] = []
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

  setModel(modelId: string, isBrep: boolean): void {
    this.clearAll()
    this.modelId = modelId
    this.isBrep = isBrep
  }

  get available(): boolean {
    return this.modelId !== null && this.isBrep
  }

  list(): readonly MeasureEntry[] {
    return this.entries
  }

  /** Handle a pick in measure mode. Returns a status message for the HUD. */
  async handlePick(pick: PickResult): Promise<string> {
    if (!this.modelId || this.busy) return ''

    if (!this.pending) {
      const marker = this.makeMarker(pick.point)
      this.viewer.overlay.add(marker)
      this.pending = { pick, marker }
      // circular entity? report its exact diameter as a bonus entry
      void this.reportEntityInfo(pick)
      return `${describe(pick)} を選択 — 相手をクリック`
    }

    const a = this.pending
    this.pending = null
    this.busy = true
    try {
      const res = await measureDistance(this.modelId, toRef(a.pick), toRef(pick))
      const pa = new THREE.Vector3(...res.pointA)
      const pb = new THREE.Vector3(...res.pointB)
      const objects: THREE.Object3D[] = [a.marker, this.makeMarker(pick.point)]
      this.viewer.overlay.add(objects[1])

      if (res.value > 1e-12) {
        const line = this.makeDimLine(pa, pb)
        this.viewer.overlay.add(line)
        objects.push(line)
      }
      const mid = pa.clone().add(pb).multiplyScalar(0.5)
      const label = this.viewer.makeLabel(fmt(res.value), mid)
      this.viewer.overlay.add(label)
      objects.push(label)

      this.addEntry(`${describe(a.pick)} ↔ ${describe(pick)} : ${fmt(res.value)}`, objects)
      return `距離 ${fmt(res.value)}`
    } catch (e) {
      this.viewer.disposeOverlayObject(a.marker)
      throw e
    } finally {
      this.busy = false
    }
  }

  cancelPending(): void {
    if (this.pending) {
      this.viewer.disposeOverlayObject(this.pending.marker)
      this.pending = null
    }
  }

  private async reportEntityInfo(pick: PickResult): Promise<void> {
    if (!this.modelId) return
    try {
      if (pick.kind === 'edge') {
        const info = await measureEdgeInfo(this.modelId, toRef(pick))
        if (info.curve === 'circle' && info.diameter !== undefined && info.center) {
          const center = new THREE.Vector3(...info.center)
          const label = this.viewer.makeLabel(`⌀${fmt(info.diameter)}`, center)
          this.viewer.overlay.add(label)
          this.addEntry(`円エッジ ⌀${fmt(info.diameter)} (L=${fmt(info.length)})`, [label])
        }
      } else if (pick.kind === 'face') {
        const info = await measureFaceInfo(this.modelId, toRef(pick))
        if (info.surface === 'cylinder' && info.diameter !== undefined && info.center) {
          const label = this.viewer.makeLabel(`⌀${fmt(info.diameter)}`, pick.point)
          this.viewer.overlay.add(label)
          this.addEntry(`円筒面 ⌀${fmt(info.diameter)}`, [label])
        }
      }
    } catch {
      /* info is best-effort; distance flow continues regardless */
    }
  }

  private addEntry(label: string, objects: THREE.Object3D[]): void {
    this.entries.push({ id: this.nextId++, label, objects })
    this.emit()
  }

  remove(id: number): void {
    const i = this.entries.findIndex((e) => e.id === id)
    if (i < 0) return
    for (const o of this.entries[i].objects) this.viewer.disposeOverlayObject(o)
    this.entries.splice(i, 1)
    this.emit()
  }

  clearAll(): void {
    this.cancelPending()
    for (const e of this.entries) for (const o of e.objects) this.viewer.disposeOverlayObject(o)
    this.entries = []
    this.emit()
  }

  private makeMarker(at: THREE.Vector3): THREE.Object3D {
    // screen-constant size via onBeforeRender scaling
    const geo = new THREE.SphereGeometry(1, 12, 12)
    const mat = new THREE.MeshBasicMaterial({ color: MARKER_COLOR, depthTest: false })
    const m = new THREE.Mesh(geo, mat)
    m.renderOrder = 999
    m.position.copy(at)
    const viewer = this.viewer
    m.onBeforeRender = () => {
      const dist = viewer.camera.position.distanceTo(m.position)
      const s = (dist * Math.tan((viewer.camera.fov * Math.PI) / 360) * 2) /
        viewer.renderer.domElement.clientHeight * 4 // ≈4px radius
      m.scale.setScalar(s)
    }
    return m
  }

  private makeDimLine(a: THREE.Vector3, b: THREE.Vector3): THREE.Object3D {
    const geo = new THREE.BufferGeometry().setFromPoints([a, b])
    const mat = new THREE.LineBasicMaterial({ color: DIM_COLOR, depthTest: false })
    const line = new THREE.Line(geo, mat)
    line.renderOrder = 998
    return line
  }
}

function toRef(pick: PickResult): EntityRef {
  if (pick.kind === 'vertex') {
    // vertices snap to exact B-rep coords already; send the point (works
    // uniformly and avoids vertexId ambiguity across seam duplicates)
    return { kind: 'point', xyz: [pick.point.x, pick.point.y, pick.point.z] }
  }
  return { partId: pick.partId, kind: pick.kind, id: pick.id }
}

function describe(pick: PickResult): string {
  const kind = { vertex: '頂点', edge: 'エッジ', face: '面' }[pick.kind]
  return `${kind}#${pick.id}`
}

function fmt(v: number): string {
  return v.toFixed(3)
}
