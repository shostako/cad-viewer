/** Entity picking with snap priority: vertex > edge > face.
 *
 * Raycasting runs on the display mesh (three-mesh-bvh accelerated), but every
 * pick resolves to a topology ID (faceId / edgeId / vertexId) that maps 1:1 to
 * the server-side B-rep — measurements are then computed exactly on the server.
 */
import * as THREE from 'three'
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from 'three-mesh-bvh'
import type { EdgeRange, FaceRange, PartData } from './model'
import type { Viewer } from './viewer'

// install BVH acceleration globally
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree
THREE.Mesh.prototype.raycast = acceleratedRaycast

export type EntityKind = 'vertex' | 'edge' | 'face' | 'part'
/**
 * What a click may take (the operation panel's 選択): anything (a vertex, else
 * an edge near the cursor, else the face), one kind alone, or a whole part.
 */
export type PickFilter = 'any' | 'face' | 'edge' | 'vertex' | 'part'

export interface PickResult {
  partId: number
  kind: EntityKind
  id: number
  /** snapped 3D point (exact for vertices, approximate for edge/face hits) */
  point: THREE.Vector3
}

/** The display triangle under the cursor (no snapping): for values read off the per-vertex colours. */
export interface FaceHit {
  partId: number
  /** triangle index in the part's display mesh, in its index order (the BVH is built indirect and keeps it) */
  triangle: number
  /** its three vertex indices */
  vertices: [number, number, number]
  /** barycentric weights of the hit point on it, in the order of `vertices` (each 0..1, sum 1) */
  weights: [number, number, number]
}

const VERTEX_SNAP_PX = 14
const EDGE_SNAP_PX = 10
/** px: how near a vertex or an edge a click takes it when that kind alone may be picked (farther: nothing) */
const FILTER_SNAP_PX = 24

export class Picker {
  /** what a click may take (PickFilter); the hover preselection asks the same pick, so it shows the same */
  filter: PickFilter = 'any'
  private raycaster = new THREE.Raycaster()
  private parts = new Map<number, PartData>()
  private meshes: THREE.Mesh[] = []

  private viewer: Viewer

  constructor(viewer: Viewer) {
    this.viewer = viewer
  }

  setModel(parts: PartData[]): void {
    this.parts.clear()
    this.meshes = []
    for (const part of parts) {
      this.parts.set(part.id, part)
      const mesh = this.viewer.getPartMesh(part.id)
      if (mesh) {
        // indirect: keep the original index order — faceRanges (triStart/triCount)
        // map triangles to B-rep faceIds and must never be reshuffled
        mesh.geometry.computeBoundsTree({ indirect: true })
        mesh.userData.partId = part.id
        this.meshes.push(mesh)
      }
    }
  }

  clear(): void {
    for (const m of this.meshes) m.geometry.disposeBoundsTree()
    this.meshes = []
    this.parts.clear()
  }

  /**
   * First hit the user can see: a visible part, not on the clipped-away side
   * of a section. The raycaster tests the raw geometry; with the section tool
   * active the nearest hits may lie on the clipped side, so clicks in a
   * sectioned view never select (measure/annotate/zoom to) what is hidden.
   */
  private firstVisibleHit(ndc: THREE.Vector2): THREE.Intersection | null {
    // a parallel ray starts on the camera plane: the camera must be behind
    // everything, with up-to-date matrices, before the ray is made
    this.viewer.prepareCamera()
    this.raycaster.setFromCamera(ndc, this.viewer.camera)
    const visible = this.meshes.filter((m) => m.parent?.visible)
    const hits = this.raycaster.intersectObjects(visible, false)
    const hit = hits.find((h) => {
      const planes = (h.object as THREE.Mesh).material as THREE.Material
      const clip = (planes as THREE.Material & { clippingPlanes?: THREE.Plane[] }).clippingPlanes
      if (!clip || clip.length === 0) return true
      return clip.every((p) => p.distanceToPoint(h.point) >= 0)
    })
    return hit ?? null
  }

  /** Surface point under the cursor, without snapping: the wheel's zoom point and the rotation centre. */
  surfacePoint(ndc: THREE.Vector2): THREE.Vector3 | null {
    return this.firstVisibleHit(ndc)?.point.clone() ?? null
  }

  /**
   * The triangle under the cursor and where on it the cursor is, without
   * snapping: the first visible hit, as for surfacePoint. The values under
   * the cursor (thickness, draft angle) are read from it.
   */
  faceHit(ndc: THREE.Vector2): FaceHit | null {
    const hit = this.firstVisibleHit(ndc)
    if (!hit?.face || hit.faceIndex === undefined || hit.faceIndex === null) return null
    const { a, b, c } = hit.face
    const pos = (hit.object as THREE.Mesh).geometry.getAttribute('position')
    const w = THREE.Triangle.getBarycoord(
      hit.point,
      new THREE.Vector3().fromBufferAttribute(pos, a),
      new THREE.Vector3().fromBufferAttribute(pos, b),
      new THREE.Vector3().fromBufferAttribute(pos, c),
      new THREE.Vector3(),
    )
    // the hit lies on the triangle: only float noise can take a weight below
    // 0; a degenerate triangle (no weights) is never hit, but split it evenly
    const ws = w ? [Math.max(w.x, 0), Math.max(w.y, 0), Math.max(w.z, 0)] : [1, 1, 1]
    const sum = ws[0] + ws[1] + ws[2]
    return {
      partId: hit.object.userData.partId as number,
      triangle: hit.faceIndex,
      vertices: [a, b, c],
      weights: [ws[0] / sum, ws[1] / sum, ws[2] / sum],
    }
  }

  /**
   * The part under the cursor as the view draws it (the part tree marks its
   * row from the 3D view): a drawn line first, as a click takes it (in
   * 半透明 / ワイヤーフレーム every visible part's lines; in the shaded
   * styles the lines of a curve-only part, which are always drawn), else the
   * first visible face. In the shaded styles a curve wins only in front of
   * that face (the face hides what is behind it).
   */
  partAt(ndc: THREE.Vector2): number | null {
    return this.partHit(ndc)?.partId ?? null
  }

  /** the part under the cursor (partAt) and the point on it: a whole-part pick (選択: 部品) takes it */
  private partHit(ndc: THREE.Vector2): { partId: number; point: THREE.Vector3 } | null {
    const seeThrough = this.viewer.seeThrough
    const line = this.snapDrawnLines(ndc, seeThrough ? undefined : (part) => part.indices.length === 0, true)
    if (line && seeThrough) return line
    const hit = this.firstVisibleHit(ndc)
    if (line && (!hit || this.depth(line.point) <= this.depth(hit.point) + 2 * this.pxScale(hit.point))) {
      return line
    }
    return hit ? { partId: hit.object.userData.partId as number, point: hit.point.clone() } : null
  }

  /** how far in front of the camera a point is, along the view */
  private depth(at: THREE.Vector3): number {
    return -at.clone().applyMatrix4(this.viewer.camera.matrixWorldInverse).z
  }

  /** Pick at normalized device coords; returns null when nothing is hit. */
  pick(ndc: THREE.Vector2): PickResult | null {
    const f = this.filter
    // ワイヤーフレーム / 半透明 draw every visible part's lines, also through
    // the faces in front of them: a click on a drawn line means that line,
    // whichever part it belongs to. Without this the ray hits the (undrawn or
    // see-through) face of the part in front, and a measurement silently
    // takes the wrong part.
    // a whole part: the part as the view draws it (partAt: a curve-only part
    // by its lines too). Id 0, never a face's, edge's or vertex's number (those start at 1)
    if (f === 'part') {
      const at = this.partHit(ndc)
      return at && this.parts.has(at.partId) ? { partId: at.partId, kind: 'part', id: 0, point: at.point } : null
    }
    if (this.viewer.seeThrough && f !== 'face') {
      const drawn = this.snapDrawnLines(ndc, undefined, false, f === 'any' ? 'any' : f)
      if (drawn) return drawn
      if (f !== 'any') return null // a vertex or an edge alone: none near
    }
    const hit = this.firstVisibleHit(ndc)
    if (!hit) return null
    const partId = hit.object.userData.partId as number
    const part = this.parts.get(partId)
    if (!part || hit.faceIndex === undefined || hit.faceIndex === null) return null

    // snap candidates must respect the same clipping planes as the hit —
    // a clipped-away vertex/edge within snap radius must not win
    const hitMat = (hit.object as THREE.Mesh).material as THREE.Material & {
      clippingPlanes?: THREE.Plane[]
    }
    const clip = hitMat.clippingPlanes ?? []

    // 1) vertex snap (screen-space); a vertex alone: farther, and nothing else
    if (f === 'any' || f === 'vertex') {
      const v = this.snapVertex(part, hit.point, clip, f === 'vertex' ? FILTER_SNAP_PX : VERTEX_SNAP_PX)
      if (v) return v
      if (f === 'vertex') return null
    }

    // 2) edge snap (screen-space distance to edge segments); an edge alone: likewise
    if (f === 'any' || f === 'edge') {
      const e = this.snapEdge(part, hit.point, clip, f === 'edge' ? FILTER_SNAP_PX : EDGE_SNAP_PX)
      if (e) return e
      if (f === 'edge') return null
    }

    // 3) face
    // Mesh formats (STL/3MF/...) ship faceRanges: [] — no B-rep face ids exist.
    // Still return a generic face pick (id -1) so annotation mode gets its
    // hit.point and measure mode can show the "STEP/IGES only" HUD message
    // instead of silently ignoring every click on the model surface.
    if (part.faceRanges.length === 0) {
      return { partId, kind: 'face', id: -1, point: hit.point.clone() }
    }
    const faceId = findRange(part.faceRanges, hit.faceIndex)
    if (faceId === null) return null
    return { partId, kind: 'face', id: faceId, point: hit.point.clone() }
  }

  /**
   * Screen-space snap to the drawn B-rep lines of every visible part:
   * vertex within VERTEX_SNAP_PX, else edge within EDGE_SNAP_PX (the same
   * priority as pick()). The nearest on screen wins; on a tie the one nearer
   * the camera. Clipped-away points (section) never win. A pass over the edge
   * segments of the visible parts: it runs once per click, and for the hover
   * preselection of 計測 / 注記 at most once per frame and, after a scan that
   * took a while, only after four times that long (main.ts pickUnderCursor;
   * not at all during a drag).
   */
  private snapDrawnLines(
    ndc: THREE.Vector2,
    only?: (part: PartData) => boolean,
    curves = false,
    want: 'any' | 'vertex' | 'edge' = 'any',
  ): PickResult | null {
    // a kind alone is looked for farther, and the other kind not at all
    const vR = want === 'vertex' ? FILTER_SNAP_PX : want === 'edge' ? -1 : VERTEX_SNAP_PX
    const eR = want === 'edge' ? FILTER_SNAP_PX : want === 'vertex' ? -1 : EDGE_SNAP_PX
    const cam = this.viewer.camera
    cam.updateMatrixWorld()
    const el = this.viewer.renderer.domElement
    const w = el.clientWidth
    const h = el.clientHeight
    const cx = ((ndc.x + 1) / 2) * w
    const cy = ((1 - ndc.y) / 2) * h
    const view = cam.matrixWorldInverse
    const near = cam.near
    this.raycaster.setFromCamera(ndc, cam)
    const ray = this.raycaster.ray

    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    const va = new THREE.Vector3()
    const vb = new THREE.Vector3()
    const p = new THREE.Vector3()
    const onSeg = new THREE.Vector3()
    /** view-space point -> screen px (x, y), into out */
    const toScreen = (v: THREE.Vector3, out: THREE.Vector3): THREE.Vector3 => {
      out.copy(v).applyMatrix4(cam.projectionMatrix) // includes the perspective divide
      return out.set(((out.x + 1) / 2) * w, ((1 - out.y) / 2) * h, -v.z)
    }
    const visibleAt = (clip: THREE.Plane[], q: THREE.Vector3) => clip.every((pl) => pl.distanceToPoint(q) >= 0)
    // within 0.5 px of each other on screen counts as a tie: the nearer one wins
    const better = (d: number, depth: number, bestD: number, bestDepth: number) =>
      d < bestD - 0.5 || (d <= bestD + 0.5 && depth < bestDepth)

    let vBest: PickResult | null = null
    let vD = vR
    let vDepth = Infinity
    let eBest: { part: PartData; seg: number; point: THREE.Vector3 } | null = null
    let eD = eR
    let eDepth = Infinity
    const sa = new THREE.Vector3()
    const sb = new THREE.Vector3()

    for (const part of this.parts.values()) {
      if (only && !only(part)) continue
      // (loose curves count only for partAt: a click does not take them)
      const drawn = this.viewer.hasEdgeLines(part.id) || (curves && this.viewer.hasCurveLines(part.id))
      if (!drawn || !this.viewer.isPartVisible(part.id)) continue
      const mat = this.viewer.getPartMesh(part.id)?.material as
        | (THREE.Material & { clippingPlanes?: THREE.Plane[] | null })
        | undefined
      const clip = mat?.clippingPlanes ?? []

      const vs = part.vertices
      for (let i = 0; i + 2 < vs.length; i += 3) {
        p.set(vs[i], vs[i + 1], vs[i + 2])
        va.copy(p).applyMatrix4(view)
        if (va.z > -near) continue // behind the camera
        toScreen(va, sa)
        const d = Math.hypot(sa.x - cx, sa.y - cy)
        if (d > vR || !better(d, sa.z, vD, vDepth) || !visibleAt(clip, p)) continue
        vD = d
        vDepth = sa.z
        vBest = { partId: part.id, kind: 'vertex', id: i / 3 + 1, point: p.clone() } // 1-based, as snapVertex
      }
      if (vBest || eR < 0) continue // a vertex beats any edge; still look for nearer vertices in other parts

      const segs = part.edges
      for (let s = 0; s * 6 + 5 < segs.length; s++) {
        a.set(segs[s * 6], segs[s * 6 + 1], segs[s * 6 + 2])
        b.set(segs[s * 6 + 3], segs[s * 6 + 4], segs[s * 6 + 5])
        va.copy(a).applyMatrix4(view)
        vb.copy(b).applyMatrix4(view)
        // keep the part in front of the near plane (a segment crossing it would project inverted)
        if (va.z > -near && vb.z > -near) continue
        if (va.z > -near) va.lerp(vb, (va.z + near) / (va.z - vb.z))
        else if (vb.z > -near) vb.lerp(va, (vb.z + near) / (vb.z - va.z))
        toScreen(va, sa)
        toScreen(vb, sb)
        const dx = sb.x - sa.x
        const dy = sb.y - sa.y
        const l2 = dx * dx + dy * dy
        const t = l2 > 0 ? THREE.MathUtils.clamp(((cx - sa.x) * dx + (cy - sa.y) * dy) / l2, 0, 1) : 0
        const d = Math.hypot(sa.x + t * dx - cx, sa.y + t * dy - cy)
        if (d > eR) continue
        // the 3D point: on the segment, nearest the pick ray (perspective-correct)
        ray.distanceSqToSegment(a, b, undefined, onSeg)
        const depth = -p.copy(onSeg).applyMatrix4(view).z
        if (!better(d, depth, eD, eDepth) || !visibleAt(clip, onSeg)) continue
        eD = d
        eDepth = depth
        eBest = { part, seg: s, point: onSeg.clone() }
      }
    }
    if (vBest) return vBest
    if (!eBest) return null
    const edgeId = findEdgeRange(eBest.part.edgeRanges, eBest.seg)
    if (edgeId === null) return null
    return { partId: eBest.part.id, kind: 'edge', id: edgeId, point: eBest.point }
  }

  private pxScale(at: THREE.Vector3): number {
    // world units per screen pixel at the hit (perspective: depends on its distance)
    return this.viewer.worldPerPixel(at)
  }

  private snapVertex(
    part: PartData,
    hitPoint: THREE.Vector3,
    clip: THREE.Plane[] = [],
    px = VERTEX_SNAP_PX,
  ): PickResult | null {
    const maxDist = px * this.pxScale(hitPoint)
    let best = -1
    let bestD = maxDist
    const vs = part.vertices
    const p = new THREE.Vector3()
    for (let i = 0; i < vs.length; i += 3) {
      p.set(vs[i], vs[i + 1], vs[i + 2])
      if (clip.length && !clip.every((pl) => pl.distanceToPoint(p) >= 0)) continue
      const d = p.distanceTo(hitPoint)
      if (d < bestD) {
        bestD = d
        best = i / 3
      }
    }
    if (best < 0) return null
    return {
      partId: part.id,
      kind: 'vertex',
      id: best + 1, // TopTools map indices are 1-based
      point: new THREE.Vector3(vs[best * 3], vs[best * 3 + 1], vs[best * 3 + 2]),
    }
  }

  private snapEdge(
    part: PartData,
    hitPoint: THREE.Vector3,
    clip: THREE.Plane[] = [],
    px = EDGE_SNAP_PX,
  ): PickResult | null {
    const maxDist = px * this.pxScale(hitPoint)
    const segs = part.edges
    let bestD = maxDist
    let bestSeg = -1
    const bestPoint = new THREE.Vector3()
    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    const closest = new THREE.Vector3()
    const line = new THREE.Line3()
    for (let s = 0; s * 6 + 5 < segs.length; s++) {
      a.set(segs[s * 6], segs[s * 6 + 1], segs[s * 6 + 2])
      b.set(segs[s * 6 + 3], segs[s * 6 + 4], segs[s * 6 + 5])
      line.set(a, b)
      line.closestPointToPoint(hitPoint, true, closest)
      if (clip.length && !clip.every((pl) => pl.distanceToPoint(closest) >= 0)) continue
      const d = closest.distanceTo(hitPoint)
      if (d < bestD) {
        bestD = d
        bestSeg = s
        bestPoint.copy(closest)
      }
    }
    if (bestSeg < 0) return null
    const edgeId = findEdgeRange(part.edgeRanges, bestSeg)
    if (edgeId === null) return null
    return { partId: part.id, kind: 'edge', id: edgeId, point: bestPoint.clone() }
  }
}

// Contract (backend tessellation.py): faceRanges/edgeRanges are emitted in
// ascending triStart/segStart order with no overlap — triangles are packed
// per face in TopTools map order. The binary searches below rely on this.
// Note: hit.faceIndex maps to the ORIGINAL triangle order because the BVH is
// built with {indirect: true}; the E2E pick tests pin this behavior.
function findRange(ranges: FaceRange[], triIndex: number): number | null {
  let lo = 0
  let hi = ranges.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const r = ranges[mid]
    if (triIndex < r.triStart) hi = mid - 1
    else if (triIndex >= r.triStart + r.triCount) lo = mid + 1
    else return r.faceId
  }
  return null
}

function findEdgeRange(ranges: EdgeRange[], segIndex: number): number | null {
  let lo = 0
  let hi = ranges.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const r = ranges[mid]
    if (segIndex < r.segStart) hi = mid - 1
    else if (segIndex >= r.segStart + r.segCount) lo = mid + 1
    else return r.edgeId
  }
  return null
}
