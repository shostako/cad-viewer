/**
 * What a click would pick in 計測 / 注記, shown before the click (hover
 * preselection), and the exact size (⌀, R, SR, 勾配) for its label.
 *
 * The highlight is light blue (水色), apart from the orange / yellow of the
 * measurements and the green of the notes: a face is tinted, an edge drawn
 * thick, a vertex ringed; after the first point of a measurement, a dotted
 * line runs from it to the candidate. It lives in viewer.cues: never picked,
 * never framed by a fit, left out of a saved image. Its geometry is built once
 * per entity, from the part's display data (the face's triangles, the edge's
 * segments): moving over the same entity only moves the dotted line's end.
 */
import * as THREE from 'three'
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js'
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js'
import { measureEdgeInfo, measureFaceInfo } from './api'
import type { PartData } from './model'
import type { PickResult } from './picking'
import { edgeSize, faceSize, type Size } from './sizes'
import type { Viewer } from './viewer'

/** 水色; #cursor-tip[data-kind='pick'] (style.css) frames the label in the same colour */
export const PRESELECT_COLOR = 0x55d6ff
/** a face's tint: lit like the parts, so it reads as light blue over any part colour (red pins too) */
const FACE_OPACITY = 0.7
/** CSS px */
const EDGE_WIDTH = 4
const RING_RADIUS_PX = 9
const RING_WIDTH_PX = 2.5
const DASH_WIDTH = 2
const DASH_PX = 6
const GAP_PX = 4
/**
 * Drawn after the parts and the see-through faces (transparent pass), under
 * the measure markers (999) and lines (998), so the data stays on top.
 */
const ORDER = 990

export class Preselect {
  private readonly viewer: Viewer
  private readonly group = new THREE.Group()
  private parts = new Map<number, PartData>()
  /** the entity drawn now ("partId:kind:id"); null: none */
  private key: string | null = null
  private face: THREE.Mesh | null = null
  /**
   * Per part, a geometry over the part mesh's own vertex, normal and index
   * buffers (already on the GPU); a face is drawn as its range of the index
   * (faceRanges), so nothing is copied. Never disposed: dispose() would free
   * those shared buffers under the part mesh. The viewer disposes them with
   * its meshes on the next model; setModel only drops these wrappers.
   */
  private faceGeometries = new Map<number, THREE.BufferGeometry>()
  private edge: LineSegments2 | null = null
  private readonly ring: THREE.Mesh
  private readonly dash: LineSegments2
  private readonly faceMaterial: THREE.MeshStandardMaterial
  private readonly edgeMaterial: LineMaterial
  private readonly dashMaterial: LineMaterial

  constructor(viewer: Viewer) {
    this.viewer = viewer
    this.group.visible = false
    viewer.cues.add(this.group)

    this.faceMaterial = new THREE.MeshStandardMaterial({
      color: PRESELECT_COLOR,
      metalness: 0.1,
      roughness: 0.65,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: FACE_OPACITY,
      // over its own face, which the parts pull back (polygonOffset 1): in
      // front of it, still behind whatever is in front of the face
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    })
    // An edge and a vertex are drawn over everything: a thick line in the
    // depth test would be cut down to a hairline along a concave edge (the
    // faces beside it are nearer), and the whole of the edge is what a click takes.
    this.edgeMaterial = new LineMaterial({
      color: PRESELECT_COLOR,
      linewidth: EDGE_WIDTH,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    })
    const ringMaterial = new THREE.MeshBasicMaterial({
      color: PRESELECT_COLOR,
      side: THREE.DoubleSide,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    })
    this.ring = new THREE.Mesh(new THREE.RingGeometry(1 - RING_WIDTH_PX / RING_RADIUS_PX, 1, 40), ringMaterial)
    this.ring.renderOrder = ORDER + 2
    this.ring.visible = false
    this.ring.frustumCulled = false // sized in onBeforeRender, after the culling
    // facing the camera at a constant size on screen, either projection
    this.ring.onBeforeRender = (_r, _s, camera) => {
      this.ring.quaternion.copy(camera.quaternion)
      this.ring.scale.setScalar(this.viewer.worldPerPixel(this.ring.position) * RING_RADIUS_PX)
      this.ring.updateMatrixWorld() // the renderer has read the matrices already this frame
    }
    this.group.add(this.ring)

    // the dotted line: a unit segment along +X, placed and stretched from the
    // first point to the candidate, so moving it writes no buffer
    this.dashMaterial = new LineMaterial({
      color: PRESELECT_COLOR,
      linewidth: DASH_WIDTH,
      dashed: true,
      dashSize: DASH_PX,
      gapSize: GAP_PX,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    })
    const dashGeo = new LineSegmentsGeometry()
    dashGeo.setPositions([0, 0, 0, 1, 0, 0])
    this.dash = new LineSegments2(dashGeo, this.dashMaterial)
    this.dash.computeLineDistances() // 0 .. 1 along the unit segment
    this.dash.renderOrder = ORDER - 1
    this.dash.frustumCulled = false
    this.dash.visible = false
    const mid = new THREE.Vector3()
    const lineBeforeRender = this.dash.onBeforeRender.bind(this.dash) // sets the line's resolution
    this.dash.onBeforeRender = (renderer: THREE.WebGLRenderer) => {
      lineBeforeRender(renderer)
      // dashes and gaps in screen px: the unit length is the line's length in px (at its middle)
      mid.set(0.5, 0, 0).applyMatrix4(this.dash.matrixWorld)
      this.dashMaterial.dashScale = this.dash.scale.x / this.viewer.worldPerPixel(mid)
    }
    this.group.add(this.dash)
  }

  /** The parts of a new model (none: an empty screen or a drawing). Drops what was drawn. */
  setModel(parts: readonly PartData[]): void {
    this.hide()
    // the same ids on the next model (the same file again) must build anew
    this.clearEntity()
    this.parts = new Map(parts.map((p) => [p.id, p]))
    this.faceGeometries = new Map()
  }

  get shown(): boolean {
    return this.group.visible
  }

  /**
   * Highlight `pick`; `from` (the chosen first point of a measurement) adds the
   * dotted line to the pick's point. A pick without a B-rep entity (a face of
   * a mesh model, id -1) has nothing to highlight: hidden.
   */
  show(pick: PickResult, from: THREE.Vector3 | null): void {
    const key = `${pick.partId}:${pick.kind}:${pick.id}`
    if (key !== this.key) {
      this.clearEntity()
      if (!this.build(pick)) return this.hide()
      this.key = key
    }
    // the section's planes as the part has them now (also on the same entity:
    // they can change between two moves)
    const clip = (this.viewer.getPartMesh(pick.partId)?.material as THREE.Material | undefined)?.clippingPlanes ?? null
    if (this.face) this.faceMaterial.clippingPlanes = clip
    if (this.edge) this.edgeMaterial.clippingPlanes = clip

    const len = from ? from.distanceTo(pick.point) : 0
    this.dash.visible = len > 0
    if (from && len > 0) {
      this.dash.position.copy(from)
      this.dash.quaternion.setFromUnitVectors(X_AXIS, pick.point.clone().sub(from).divideScalar(len))
      this.dash.scale.set(len, 1, 1)
    }
    this.group.visible = true
  }

  hide(): void {
    this.group.visible = false
    this.dash.visible = false
  }

  /** Make the highlight of one entity; false when the part has no such entity. */
  private build(pick: PickResult): boolean {
    const part = this.parts.get(pick.partId)
    if (!part) return false
    if (pick.kind === 'vertex') {
      const i = (pick.id - 1) * 3 // 1-based, as the picker gives it
      if (i < 0 || i + 2 >= part.vertices.length) return false
      this.ring.position.set(part.vertices[i], part.vertices[i + 1], part.vertices[i + 2])
      this.ring.visible = true
      return true
    }
    if (pick.kind === 'edge') {
      const r = part.edgeRanges.find((e) => e.edgeId === pick.id)
      if (!r || r.segCount <= 0) return false
      const geo = new LineSegmentsGeometry()
      geo.setPositions(part.edges.slice(r.segStart * 6, (r.segStart + r.segCount) * 6))
      this.edge = new LineSegments2(geo, this.edgeMaterial)
      this.edge.renderOrder = ORDER + 1
      this.group.add(this.edge)
      return true
    }
    // a face: its range of the part's triangles, drawn from the part's own
    // buffers (the picker's BVH is indirect: the index keeps the face order)
    const r = part.faceRanges.find((f) => f.faceId === pick.id)
    if (!r || r.triCount <= 0) return false
    const geo = this.faceGeometry(pick.partId)
    if (!geo) return false
    geo.setDrawRange(r.triStart * 3, r.triCount * 3)
    this.face = new THREE.Mesh(geo, this.faceMaterial)
    this.face.renderOrder = ORDER
    this.group.add(this.face)
    return true
  }

  /** the geometry a face of this part is drawn with (see faceGeometries) */
  private faceGeometry(partId: number): THREE.BufferGeometry | null {
    let geo = this.faceGeometries.get(partId) ?? null
    if (geo) return geo
    const src = this.viewer.getPartMesh(partId)?.geometry
    const position = src?.getAttribute('position')
    const normal = src?.getAttribute('normal')
    if (!src?.index || !position || !normal) return null
    geo = new THREE.BufferGeometry()
    geo.setAttribute('position', position)
    geo.setAttribute('normal', normal)
    geo.setIndex(src.index)
    this.faceGeometries.set(partId, geo)
    return geo
  }

  /** Drop the entity: the edge's own geometry is disposed (a face's is the part's, kept); the materials stay. */
  private clearEntity(): void {
    this.key = null
    this.ring.visible = false
    if (this.face) this.group.remove(this.face)
    if (this.edge) {
      this.group.remove(this.edge)
      this.edge.geometry.dispose()
    }
    this.face = null
    this.edge = null
  }
}

const X_AXIS = new THREE.Vector3(1, 0, 0)

/** ms the cursor stays on one face or edge before its size is asked for */
export const SIZE_REST_MS = 150

/**
 * The exact size of a face or an edge for the label (sizes.ts: ⌀, R, SR,
 * 勾配), from the backend (edge_info / face_info: the B-rep, not the display
 * mesh). Only a size the whole face or edge has: the radius of curvature at a
 * point of a B-spline is not asked for (it would change along it; a click
 * tells it). Asked once the cursor has stayed on the entity for SIZE_REST_MS,
 * not for every entity it passes over, and once per entity of a model: the
 * answer (a size, or none: flat, or the request failed) is kept until another
 * model is opened. `learned` is called when an answer comes for the entity
 * under the cursor.
 */
export class SizeCache {
  private modelId: string | null = null
  /** per model (a new map on setModel: a late answer for the old model goes to the old map) */
  private known = new Map<string, Size | null>()
  private asked = new Set<string>()
  /** the face / edge the cursor is on; null: none (or a vertex) */
  private restKey: string | null = null
  private timer: ReturnType<typeof setTimeout> | undefined
  private readonly learned: () => void

  constructor(learned: () => void) {
    this.learned = learned
  }

  /** Another model (null: none, or one without a B-rep: nothing is asked). */
  setModel(modelId: string | null): void {
    this.rest(null)
    this.modelId = modelId
    this.known = new Map()
    this.asked = new Set()
  }

  /** the size of the face / edge; null: none, or not known yet */
  get(pick: PickResult): Size | null {
    return this.known.get(keyOf(pick)) ?? null
  }

  /** The cursor is on `pick` now (null: on nothing). Another face or edge starts the wait. */
  rest(pick: PickResult | null): void {
    const key = pick && pick.kind !== 'vertex' && pick.id > 0 ? keyOf(pick) : null
    if (key === this.restKey) return
    clearTimeout(this.timer)
    this.timer = undefined
    this.restKey = key
    const modelId = this.modelId
    if (!pick || !key || !modelId || this.known.has(key) || this.asked.has(key)) return
    const ref = { partId: pick.partId, kind: pick.kind, id: pick.id }
    this.timer = setTimeout(() => {
      this.timer = undefined
      const known = this.known
      this.asked.add(key)
      // no click point: no radius of curvature at a point is asked for
      const answer = ref.kind === 'edge' ? measureEdgeInfo(modelId, ref).then(edgeSize) : measureFaceInfo(modelId, ref).then(faceSize)
      void answer.then(
        (s) => {
          known.set(key, s)
          if (known === this.known && this.restKey === key) this.learned()
        },
        // a failed request is no answer (the backend may be back): ask again
        // the next time the cursor rests on it
        () => {
          if (known === this.known) this.asked.delete(key)
        },
      )
    }, SIZE_REST_MS)
  }
}

function keyOf(pick: PickResult): string {
  return `${pick.partId}:${pick.kind}:${pick.id}`
}
