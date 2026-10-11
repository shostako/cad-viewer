/**
 * Exact B-rep measurements in the Web version: a port of backend/app/measure.py,
 * step for step, on OpenCASCADE in WebAssembly (libcascade). The answers have
 * the backend's keys, values and wording; frontend/tests/local_measure.test.ts
 * compares the two on testdata's models. Change one, change the other.
 *
 * libcascade's enums are their names as strings ('GeomAbs_Circle'); an
 * out-parameter of a number comes back in a result object; an object passed
 * by reference is filled in place.
 *
 * Every OCCT object a measurement makes or is handed back goes in its bag
 * (k(...), occtbag.ts) and is deleted when it ends; the answer is numbers.
 */
import type { PartMesh } from './brep.ts'
import { withBag, type Keep } from './occtbag.ts'

/* eslint-disable @typescript-eslint/no-explicit-any */
type OC = any
type Xyz = [number, number, number]
type Answer = Record<string, any>

export class MeasureError extends Error {}

// (measure.py's constants, with its reasons)
const PARALLEL_SIN = 1e-9
const LINE_TOL = 1e-7
const ANGLE_MIN_DEG = 1e-6
const RECOGNIZE_TOL = 1e-4
const CURVATURE_MIN = 1e-5
const TURN_TOL = 1e-9
const AXIS_PARALLEL_SIN = 1e-6
const MAX_SAMPLES = 64
const MAX_STARTS = 16

const PART_HAS_NO: Record<string, string> = {
  centre: '部品全体に中心はない',
  max: '部品全体の最大の距離は出さない（頂点か稜線を選ぶ）',
}

const deg = (rad: number) => (rad * 180) / Math.PI
const xyz = (p: any): Xyz => [p.X(), p.Y(), p.Z()]
/** GeomAbs_BSplineCurve -> bsplinecurve (Python's .name.removeprefix("GeomAbs_").lower()) */
const kindName = (e: string) => String(e).replace(/^GeomAbs_/, '').toLowerCase()

export class Measurer {
  private readonly oc: OC
  private readonly meshes: PartMesh[]
  /** the bag of the measurement under way */
  private k: Keep = (o) => o

  constructor(oc: OC, meshes: PartMesh[]) {
    this.oc = oc
    this.meshes = meshes
  }

  run(request: any): Answer {
    return withBag((k) => {
      this.k = k
      try {
        return this.dispatch(request)
      } finally {
        this.k = (o) => o
      }
    })
  }

  private dispatch(request: any): Answer {
    const mtype = request?.type
    if (mtype === 'distance') {
      const mode = request.mode ?? 'min'
      if (!['min', 'centre', 'max'].includes(mode)) throw new MeasureError('mode must be min, centre or max')
      return this.distance(request.a, request.b, near(request.nearA, 'nearA'), near(request.nearB, 'nearB'), mode)
    }
    if (mtype === 'edge_info') return this.edgeInfo(request.ref, near(request.near))
    if (mtype === 'face_info') return this.faceInfo(request.ref, near(request.near))
    if (mtype === 'vertex_info') return this.vertexInfo(request.ref)
    throw new MeasureError(`unknown measurement type: ${mtype}`)
  }

  // ---- refs ----------------------------------------------------------------

  private resolve(ref: any): any {
    const oc = this.oc, k = this.k
    const kind = ref?.kind
    if (kind === 'point') {
      const [x, y, z] = ref.xyz
      return k(k(new oc.BRepBuilderAPI_MakeVertex(k(new oc.gp_Pnt(x, y, z)))).Vertex())
    }
    const partId = ref?.partId, id = ref?.id
    if (partId === undefined || partId === null || id === undefined || id === null) throw new MeasureError(`invalid entity ref: ${pyRepr(ref)}`)
    const mesh = this.meshes.find((m) => m.part.id === partId)
    if (!mesh) throw new MeasureError(`unknown partId: ${partId}`)
    if (kind === 'part') return mesh.part.shape // the model's own: not in the bag
    const map = ({ face: mesh.faceMap, edge: mesh.edgeMap, vertex: mesh.vertexMap } as Record<string, any>)[kind]
    if (!map) throw new MeasureError(`unknown entity kind: ${kind}`)
    if (!(id >= 1 && id <= map.Size())) throw new MeasureError(`${kind} id ${id} out of range (1..${map.Size()})`)
    return k(map.FindKey(id))
  }

  private type(shape: any): string {
    return shape.ShapeType()
  }

  // ---- distance --------------------------------------------------------------

  private distance(a: any, b: any, nearA: Xyz | null, nearB: Xyz | null, mode: string): Answer {
    const oc = this.oc
    const sa = this.resolve(a), sb = this.resolve(b)
    if (mode !== 'min') {
      for (const [ref, which] of [[a, '1 点目'], [b, '2 点目']] as const) {
        if (ref?.kind === 'part') return unavailable(mode, `${which}: ${PART_HAS_NO[mode]}`)
      }
    }
    if (mode === 'centre') return this.centreDistance(sa, sb, nearA)
    if (mode === 'max') return this.maxDistance(sa, sb)
    const k = this.k
    const ext = k(new oc.BRepExtrema_DistShapeShape(sa, sb))
    if (!ext.IsDone() || ext.NbSolution() < 1) throw new MeasureError('distance computation failed')
    const value = ext.Value()
    let line = this.parallelFacesLine(sa, sb, nearA, nearB)
    if (line !== null && Math.abs(line[0].Distance(line[1]) - value) > LINE_TOL) line = null
    if (line === null) {
      const i = this.nearestSolution(ext, nearA, nearB)
      line = [k(ext.PointOnShape1(i)), k(ext.PointOnShape2(i))]
    }
    const [pa, pb] = line
    const out: Answer = {
      type: 'distance',
      value,
      pointA: xyz(pa),
      pointB: xyz(pb),
      delta: [pb.X() - pa.X(), pb.Y() - pa.Y(), pb.Z() - pa.Z()],
    }
    const ang = this.angleBetween(sa, sb)
    if (ang !== null && ang > ANGLE_MIN_DEG) out.angle = ang
    return out
  }

  private nearestSolution(ext: any, nearA: Xyz | null, nearB: Xyz | null): number {
    const oc = this.oc, k = this.k
    if (nearA === null && nearB === null) return 1
    const qa = nearA ? k(new oc.gp_Pnt(...nearA)) : null
    const qb = nearB ? k(new oc.gp_Pnt(...nearB)) : null
    let best = 1, bestD = Infinity
    for (let i = 1; i <= ext.NbSolution(); i++) {
      const d = (qa ? k(ext.PointOnShape1(i)).Distance(qa) : 0) + (qb ? k(ext.PointOnShape2(i)).Distance(qb) : 0)
      if (d < bestD) (best = i), (bestD = d)
    }
    return best
  }

  private planeOf(shape: any): [any, any] | null {
    const oc = this.oc, k = this.k
    if (this.type(shape) !== 'TopAbs_FACE') return null
    const face = k(oc.TopoDS.Face(shape))
    const surf = k(new oc.BRepAdaptor_Surface(face, true))
    if (surf.GetType() !== 'GeomAbs_Plane') return null
    return [face, k(surf.Plane())]
  }

  private onFace(face: any, p: any, tol: number): boolean {
    const state = this.k(new this.oc.BRepClass_FaceClassifier(face, p, tol)).State()
    return state === 'TopAbs_IN' || state === 'TopAbs_ON'
  }

  private project(p: any, pln: any): any {
    const oc = this.oc, k = this.k
    const n = k(k(pln.Axis()).Direction())
    const d = k(new oc.gp_Vec(k(pln.Location()), p)).Dot(k(new oc.gp_Vec(n)))
    return k(new oc.gp_Pnt(p.X() - d * n.X(), p.Y() - d * n.Y(), p.Z() - d * n.Z()))
  }

  /** two parallel planar faces: the line through a clicked point, when both feet lie on their faces */
  private parallelFacesLine(sa: any, sb: any, nearA: Xyz | null, nearB: Xyz | null): [any, any] | null {
    const oc = this.oc, k = this.k
    const fa = this.planeOf(sa), fb = this.planeOf(sb)
    if (!fa || !fb) return null
    const [faceA, plnA] = fa, [faceB, plnB] = fb
    const na = k(k(plnA.Axis()).Direction()), nb = k(k(plnB.Axis()).Direction())
    if (k(k(new oc.gp_Vec(na)).Crossed(k(new oc.gp_Vec(nb)))).Magnitude() > PARALLEL_SIN) return null
    const tries: [Xyz | null, any, any, any, any, boolean][] = [
      [nearA, faceA, plnA, faceB, plnB, true],
      [nearB, faceB, plnB, faceA, plnA, false],
    ]
    for (const [q, srcFace, srcPln, dstFace, dstPln, fromA] of tries) {
      if (q === null) continue
      const p = this.project(k(new oc.gp_Pnt(...q)), srcPln)
      const r = this.project(p, dstPln)
      if (this.onFace(srcFace, p, 1e-6) && this.onFace(dstFace, r, 1e-6)) return fromA ? [p, r] : [r, p]
    }
    return null
  }

  /** ('plane', normal) for a planar face, ('line', direction) for a straight edge; null otherwise */
  private flat(shape: any): [string, any] | null {
    const oc = this.oc, k = this.k
    const t = this.type(shape)
    if (t === 'TopAbs_FACE') {
      const surf = k(new oc.BRepAdaptor_Surface(k(oc.TopoDS.Face(shape)), true))
      if (surf.GetType() === 'GeomAbs_Plane') return ['plane', k(new oc.gp_Vec(k(k(k(surf.Plane()).Axis()).Direction())))]
    } else if (t === 'TopAbs_EDGE') {
      const curve = k(new oc.BRepAdaptor_Curve(k(oc.TopoDS.Edge(shape))))
      if (curve.GetType() === 'GeomAbs_Line') return ['line', k(new oc.gp_Vec(k(k(curve.Line()).Direction())))]
    }
    return null
  }

  private angleBetween(sa: any, sb: any): number | null {
    const fa = this.flat(sa), fb = this.flat(sb)
    if (!fa || !fb) return null
    const [ka, va] = fa, [kb, vb] = fb
    const d = deg(Math.atan2(this.k(va.Crossed(vb)).Magnitude(), Math.abs(va.Dot(vb))))
    return ka !== kb ? 90 - d : d
  }

  // ---- centre -------------------------------------------------------------------

  /** ['point', gp_Pnt] / ['axis', gp_Ax1] / ['none', why] (measure._centre) */
  private centre(shape: any): [string, any] {
    const oc = this.oc, k = this.k
    const kind = this.type(shape)
    if (kind === 'TopAbs_VERTEX') return ['point', k(oc.BRep_Tool.Pnt(k(oc.TopoDS.Vertex(shape))))]
    if (kind === 'TopAbs_EDGE') {
      const edge = k(oc.TopoDS.Edge(shape))
      const curve = k(new oc.BRepAdaptor_Curve(edge))
      const ctype = curve.GetType()
      if (ctype === 'GeomAbs_Circle') return ['point', k(k(curve.Circle()).Location())]
      if (ctype === 'GeomAbs_Ellipse') return ['point', k(k(curve.Ellipse()).Location())]
      if (ctype === 'GeomAbs_BSplineCurve' || ctype === 'GeomAbs_BezierCurve') {
        const circ = k(new oc.gp_Circ())
        if (k(new oc.ShapeAnalysis_CanonicalRecognition(edge)).IsCircle(RECOGNIZE_TOL, circ)) return ['point', k(circ.Location())]
      }
      if (ctype === 'GeomAbs_Line') return ['none', '直線の稜線に中心はない']
      return ['none', 'この稜線に中心はない（円でも楕円でもない）']
    }
    if (kind !== 'TopAbs_FACE') return ['none', '部品全体に中心はない']
    const face = k(oc.TopoDS.Face(shape))
    const surf = k(new oc.BRepAdaptor_Surface(face, true))
    const stype = surf.GetType()
    let name: string | null = null
    let geom: any = null
    if (stype === 'GeomAbs_Cylinder') (name = 'cylinder'), (geom = k(surf.Cylinder()))
    else if (stype === 'GeomAbs_Cone') (name = 'cone'), (geom = k(surf.Cone()))
    else if (stype === 'GeomAbs_Torus') (name = 'torus'), (geom = k(surf.Torus()))
    else if (stype === 'GeomAbs_Sphere') (name = 'sphere'), (geom = k(surf.Sphere()))
    else if (stype === 'GeomAbs_Plane') name = 'plane'
    if (name === null && (stype === 'GeomAbs_BSplineSurface' || stype === 'GeomAbs_BezierSurface')) {
      const found = this.recognize(face)
      if (found) [name, geom] = found
    }
    if (name === 'cylinder' || name === 'cone' || name === 'torus') return ['axis', k(geom.Axis())]
    if (name === 'sphere') return ['point', k(geom.Location())]
    if (name === 'plane') return ['none', '平面に中心はない']
    return ['none', 'この面に中心はない（円筒・円錐・球・トーラスでない）']
  }

  private foot(p: any, ax: any): any {
    const oc = this.oc, k = this.k
    const d = k(new oc.gp_Vec(k(ax.Direction())))
    return k(k(ax.Location()).Translated(k(d.Multiplied(k(new oc.gp_Vec(k(ax.Location()), p)).Dot(d)))))
  }

  private centreDistance(sa: any, sb: any, nearA: Xyz | null): Answer {
    const oc = this.oc, k = this.k
    const [ka, ca] = this.centre(sa), [kb, cb] = this.centre(sb)
    for (const [k, c, which] of [[ka, ca, '1 点目'], [kb, cb, '2 点目']] as const) {
      if (k === 'none') return unavailable('centre', `${which}: ${c}`)
    }
    let pa: any, pb: any
    if (ka === 'point' && kb === 'point') (pa = ca), (pb = cb)
    else if (ka === 'point') (pa = ca), (pb = this.foot(ca, cb))
    else if (kb === 'point') (pa = this.foot(cb, ca)), (pb = cb)
    else {
      const sin = k(k(new oc.gp_Vec(k(ca.Direction()))).Crossed(k(new oc.gp_Vec(k(cb.Direction()))))).Magnitude()
      if (sin > AXIS_PARALLEL_SIN) return unavailable('centre', `軸が平行でない（${deg(Math.asin(Math.min(1, sin))).toFixed(1)}°）`)
      pa = this.foot(nearA ? k(new oc.gp_Pnt(...nearA)) : k(ca.Location()), ca)
      pb = this.foot(pa, cb)
    }
    return answer('centre', pa, pb)
  }

  // ---- max ---------------------------------------------------------------------

  private farthestOn(curve: any, p: any): any {
    const oc = this.oc, k = this.k
    const cands = [k(curve.Value(curve.FirstParameter())), k(curve.Value(curve.LastParameter()))]
    const ext = k(new (extPC(oc))(p, curve))
    if (ext.IsDone()) for (let i = 1; i <= ext.NbExt(); i++) cands.push(k(k(ext.Point(i)).Value()))
    return cands.reduce((best, q) => (q.SquareDistance(p) > best.SquareDistance(p) ? q : best))
  }

  private along(c: any): any[] {
    const oc = this.oc, k = this.k
    try {
      const ua = k(new oc.GCPnts_UniformAbscissa(c, MAX_SAMPLES, -1))
      if (ua.IsDone() && ua.NbPoints() >= 2) {
        const out = []
        for (let i = 1; i <= ua.NbPoints(); i++) out.push(k(c.Value(ua.Parameter(i))))
        return out
      }
    } catch {
      // an adaptor the length cannot be taken of: by parameter
    }
    const u0 = c.FirstParameter(), u1 = c.LastParameter()
    return Array.from({ length: MAX_SAMPLES }, (_, i) => k(c.Value(u0 + ((u1 - u0) * i) / (MAX_SAMPLES - 1))))
  }

  private climb(ca: any, cb: any, pa: any, pb: any): [any, any] {
    for (let k = 0; k < 100; k++) {
      const qb = this.farthestOn(cb, pa)
      const qa = this.farthestOn(ca, qb)
      const gain = qa.Distance(qb) - pa.Distance(pb)
      if (gain >= 0) (pa = qa), (pb = qb)
      if (gain <= 1e-12) break
    }
    return [pa, pb]
  }

  private maxDistance(sa: any, sb: any): Answer {
    const oc = this.oc, k = this.k
    const kinds: string[] = []
    for (const [shape, which] of [[sa, '1 点目'], [sb, '2 点目']] as const) {
      const kind = this.type(shape)
      if (kind !== 'TopAbs_VERTEX' && kind !== 'TopAbs_EDGE') {
        const what = kind === 'TopAbs_FACE' ? '面' : '部品全体'
        return unavailable('max', `${which}: ${what}の最大の距離は出さない（頂点か稜線を選ぶ）`)
      }
      kinds.push(kind)
    }
    const pnt = (s: any) => k(oc.BRep_Tool.Pnt(k(oc.TopoDS.Vertex(s))))
    const crv = (s: any) => k(new oc.BRepAdaptor_Curve(k(oc.TopoDS.Edge(s))))
    if (kinds[0] === 'TopAbs_VERTEX' && kinds[1] === 'TopAbs_VERTEX') return answer('max', pnt(sa), pnt(sb))
    if (kinds[0] === 'TopAbs_VERTEX') {
      const pa = pnt(sa)
      return answer('max', pa, this.farthestOn(crv(sb), pa))
    }
    if (kinds[1] === 'TopAbs_VERTEX') {
      const pb = pnt(sb)
      return answer('max', this.farthestOn(crv(sa), pb), pb)
    }
    const ca = crv(sa), cb = crv(sb)
    const ptsA = this.along(ca), ptsB = this.along(cb)
    const n = ptsA.length, m = ptsB.length
    const d2 = ptsA.map((p) => ptsB.map((q) => p.SquareDistance(q)))
    const peak = (i: number, j: number) => {
      for (let k = i - 1; k <= i + 1; k++) for (let l = j - 1; l <= j + 1; l++) if (k >= 0 && k < n && l >= 0 && l < m && d2[k][l] > d2[i][j]) return false
      return true
    }
    // Python sorts (d2, i, j) tuples ascending and keeps the last MAX_STARTS
    const starts: [number, number, number][] = []
    for (let i = 0; i < n; i++) for (let j = 0; j < m; j++) if (peak(i, j)) starts.push([d2[i][j], i, j])
    starts.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2])
    let best: [any, any] | null = null
    for (const [, i, j] of starts.slice(-MAX_STARTS)) {
      const [pa, pb] = this.climb(ca, cb, ptsA[i], ptsB[j])
      if (best === null || pa.SquareDistance(pb) > best[0].SquareDistance(best[1])) best = [pa, pb]
    }
    return answer('max', best![0], best![1])
  }

  // ---- edges and faces ----------------------------------------------------------

  private circle(circ: any, full: boolean): Answer {
    const k = this.k
    return {
      curve: 'circle',
      radius: circ.Radius(),
      diameter: 2 * circ.Radius(),
      center: xyz(k(circ.Location())),
      axis: xyz(k(k(circ.Axis()).Direction())),
      full,
    }
  }

  private curveRadiusNear(curve: any, q: Xyz): Answer {
    const oc = this.oc, k = this.k
    const p = k(new oc.gp_Pnt(...q))
    const params = [curve.FirstParameter(), curve.LastParameter()]
    const ext = k(new (extPC(oc))(p, curve))
    if (ext.IsDone()) for (let i = 1; i <= ext.NbExt(); i++) params.push(k(ext.Point(i)).Parameter())
    const t = params.reduce((best, u) => (k(curve.Value(u)).SquareDistance(p) < k(curve.Value(best)).SquareDistance(p) ? u : best))
    const props = k(new oc.BRepLProp_CLProps(curve, t, 2, 1e-9))
    if (!props.IsTangentDefined()) return {}
    const c = Math.abs(props.Curvature())
    if (c <= CURVATURE_MIN) return {}
    return { localRadius: 1 / c, at: xyz(k(props.Value())) }
  }

  private edgeInfo(ref: any, q: Xyz | null): Answer {
    const oc = this.oc, k = this.k
    const edge = k(oc.TopoDS.Edge(this.resolve(ref)))
    const props = k(new oc.GProp_GProps())
    oc.BRepGProp.LinearProperties(edge, props, false, false)
    const out: Answer = { type: 'edge', length: props.Mass() }
    const curve = k(new oc.BRepAdaptor_Curve(edge))
    const ctype = curve.GetType()
    if (ctype === 'GeomAbs_Circle') {
      const span = curve.LastParameter() - curve.FirstParameter()
      Object.assign(out, this.circle(k(curve.Circle()), span >= 2 * Math.PI - TURN_TOL))
      return out
    }
    out.curve = kindName(ctype)
    if (ctype === 'GeomAbs_Line') {
      const a = k(curve.Value(curve.FirstParameter())), b = k(curve.Value(curve.LastParameter()))
      const d = k(new oc.gp_Vec(a, b))
      out.start = xyz(a)
      out.end = xyz(b)
      if (d.Magnitude() > 0) out.direction = xyz(k(d.Normalized()))
      return out
    }
    if (ctype === 'GeomAbs_BSplineCurve' || ctype === 'GeomAbs_BezierCurve') {
      const circ = k(new oc.gp_Circ())
      if (k(new oc.ShapeAnalysis_CanonicalRecognition(edge)).IsCircle(RECOGNIZE_TOL, circ)) {
        Object.assign(out, this.circle(circ, curve.IsClosed()), { recognized: true })
        return out
      }
    }
    if (q !== null) Object.assign(out, this.curveRadiusNear(curve, q))
    return out
  }

  private hasSeam(face: any): boolean {
    const oc = this.oc, k = this.k
    const ex = k(new oc.TopExp_Explorer(face, 'TopAbs_EDGE', 'TopAbs_SHAPE'))
    for (; ex.More(); ex.Next()) if (oc.BRep_Tool.IsClosed(k(oc.TopoDS.Edge(k(ex.Current()))), face)) return true
    return false
  }

  /** a B-spline face that is a plane, a cylinder, a cone or a sphere within RECOGNIZE_TOL */
  private recognize(face: any): [string, any] | null {
    const oc = this.oc, k = this.k
    const tests: [string, () => any, string][] = [
      ['plane', () => new oc.gp_Pln(), 'IsPlane'],
      ['cylinder', () => new oc.gp_Cylinder(), 'IsCylinder'],
      ['cone', () => new oc.gp_Cone(), 'IsCone'],
      ['sphere', () => new oc.gp_Sphere(), 'IsSphere'],
    ]
    for (const [name, make, test] of tests) {
      const geom = k(make())
      // a recogniser of its own for each test: a failed test leaves its state behind
      if (k(new oc.ShapeAnalysis_CanonicalRecognition(face))[test](RECOGNIZE_TOL, geom)) return [name, geom]
    }
    return null
  }

  private surfaceRadiusNear(face: any, surf: any, q: Xyz): Answer {
    const oc = this.oc, k = this.k
    const proj = k(new oc.GeomAPI_ProjectPointOnSurf(k(new oc.gp_Pnt(...q)), k(oc.BRep_Tool.Surface(face))))
    if (proj.NbPoints() < 1) return {}
    // the out-parameters come back by their C++ names (U, V)
    const { U: u, V: v } = proj.LowerDistanceParameters()
    const props = k(new oc.BRepLProp_SLProps(surf, u, v, 2, 1e-9))
    if (!props.IsCurvatureDefined()) return {}
    const c = Math.max(Math.abs(props.MaxCurvature()), Math.abs(props.MinCurvature()))
    if (c <= CURVATURE_MIN) return {}
    return { localRadius: 1 / c, at: xyz(k(props.Value())) }
  }

  private faceInfo(ref: any, q: Xyz | null): Answer {
    const oc = this.oc, k = this.k
    const face = k(oc.TopoDS.Face(this.resolve(ref)))
    const props = k(new oc.GProp_GProps())
    oc.BRepGProp.SurfaceProperties(face, props, false, false)
    const out: Answer = { type: 'face', area: props.Mass(), ...this.loops(face) }
    const surf = k(new oc.BRepAdaptor_Surface(face, true))
    const stype = surf.GetType()
    const kinds: Record<string, [string, () => any]> = {
      GeomAbs_Cylinder: ['cylinder', () => k(surf.Cylinder())],
      GeomAbs_Plane: ['plane', () => k(surf.Plane())],
      GeomAbs_Torus: ['torus', () => k(surf.Torus())],
      GeomAbs_Sphere: ['sphere', () => k(surf.Sphere())],
      GeomAbs_Cone: ['cone', () => k(surf.Cone())],
    }
    let name: string
    let geom: any = null
    if (kinds[stype]) {
      name = kinds[stype][0]
      geom = kinds[stype][1]()
    } else {
      name = kindName(stype)
      const found = stype === 'GeomAbs_BSplineSurface' || stype === 'GeomAbs_BezierSurface' ? this.recognize(face) : null
      if (found) {
        ;[name, geom] = found
        out.recognized = true
      }
    }
    out.surface = name
    if (name === 'cylinder') {
      Object.assign(out, {
        radius: geom.Radius(),
        diameter: 2 * geom.Radius(),
        center: xyz(k(geom.Location())),
        axis: xyz(k(k(geom.Axis()).Direction())),
        full: this.hasSeam(face),
      })
    } else if (name === 'plane') {
      const n = k(k(geom.Axis()).Direction())
      out.normal = xyz(face.Orientation() === 'TopAbs_REVERSED' ? k(n.Reversed()) : n)
    } else if (name === 'torus') {
      Object.assign(out, { radius: geom.MinorRadius(), majorRadius: geom.MajorRadius(), center: xyz(k(geom.Location())), axis: xyz(k(k(geom.Axis()).Direction())) })
    } else if (name === 'sphere') {
      Object.assign(out, { radius: geom.Radius(), center: xyz(k(geom.Location())) })
    } else if (name === 'cone') {
      Object.assign(out, { angle: Math.abs(deg(geom.SemiAngle())), apex: xyz(k(geom.Apex())), axis: xyz(k(k(geom.Axis()).Direction())) })
    } else if (q !== null) {
      Object.assign(out, this.surfaceRadiusNear(face, surf, q))
    }
    return out
  }

  private loopLength(wire: any, face: any): number {
    const oc = this.oc, k = this.k
    let total = 0
    const ex = k(new oc.TopExp_Explorer(wire, 'TopAbs_EDGE', 'TopAbs_SHAPE'))
    for (; ex.More(); ex.Next()) {
      const edge = k(oc.TopoDS.Edge(k(ex.Current())))
      if (oc.BRep_Tool.Degenerated(edge) || oc.BRep_Tool.IsClosed(edge, face)) continue
      const props = k(new oc.GProp_GProps())
      oc.BRepGProp.LinearProperties(edge, props, false, false)
      total += props.Mass()
    }
    return total
  }

  private loops(face: any): Answer {
    const oc = this.oc, k = this.k
    const outer = k(oc.BRepTools.OuterWire(face))
    if (outer.IsNull()) return {}
    const holes: number[] = []
    const ex = k(new oc.TopExp_Explorer(face, 'TopAbs_WIRE', 'TopAbs_SHAPE'))
    for (; ex.More(); ex.Next()) {
      const wire = k(ex.Current())
      if (!wire.IsSame(outer)) holes.push(this.loopLength(wire, face))
    }
    return { perimeter: this.loopLength(outer, face), holes: holes.sort((x, y) => y - x) }
  }

  private vertexInfo(ref: any): Answer {
    const oc = this.oc
    if (ref?.kind !== 'vertex') throw new MeasureError(`vertex_info takes a vertex of the model, not: ${pyRepr(ref)}`)
    const shape = this.resolve(ref)
    if (this.type(shape) !== 'TopAbs_VERTEX') throw new MeasureError(`not a vertex: ${pyRepr(ref)}`)
    return { type: 'vertex', point: xyz(this.k(oc.BRep_Tool.Pnt(this.k(oc.TopoDS.Vertex(shape))))) }
  }
}

/**
 * Extrema_ExtPC (a point's extrema on a curve): a typedef of a template, bound
 * under the template's long name only
 */
function extPC(oc: OC): any {
  return oc.Extrema_ExtPC ?? oc[Object.keys(oc).find((k) => k.startsWith('Extrema_GGExtPC_Adaptor3d_Curve_'))!]
}

function unavailable(mode: string, why: string): Answer {
  return { type: 'distance', mode, unavailable: why }
}

function answer(mode: string, pa: any, pb: any): Answer {
  return {
    type: 'distance',
    mode,
    value: pa.Distance(pb),
    pointA: xyz(pa),
    pointB: xyz(pb),
    delta: [pb.X() - pa.X(), pb.Y() - pa.Y(), pb.Z() - pa.Z()],
  }
}

/** a clicked point [x, y, z], or null (measure._near) */
function near(value: unknown, name = 'near'): Xyz | null {
  if (value === undefined || value === null) return null
  if (!Array.isArray(value) || value.length !== 3 || !value.every((c) => typeof c === 'number' && Number.isFinite(c))) {
    throw new MeasureError(`${name} must be [x, y, z]`)
  }
  return [value[0], value[1], value[2]]
}

/** a ref as Python prints a dict (the backend's error messages show it so) */
function pyRepr(v: unknown): string {
  if (v === null || v === undefined) return 'None'
  if (typeof v === 'string') return `'${v}'`
  if (typeof v === 'boolean') return v ? 'True' : 'False'
  if (Array.isArray(v)) return `[${v.map(pyRepr).join(', ')}]`
  if (typeof v === 'object') return `{${Object.entries(v as Record<string, unknown>).map(([k, x]) => `'${k}': ${pyRepr(x)}`).join(', ')}}`
  return String(v)
}
