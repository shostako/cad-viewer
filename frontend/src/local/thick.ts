/**
 * 厚肉 in the Web version: a port of backend/app/thick.py, step for step (see
 * there for the why of each). The part's grid of inside points (rays up the
 * columns, three-mesh-bvh for embree), their distance to the surface
 * (Felzenszwalb's separable distance transform for scipy's), the faces'
 * thickness (the rolling ball on the grid), the general wall (the faces'
 * area-weighted mode), the places much thicker (the grid's connected groups,
 * their deepest point searched again on the exact surface).
 */
import { DoubleSide, Ray, Vector3 } from 'three'
import type { MeshBVH } from 'three-mesh-bvh'

import { weld, type TriMesh } from './meshload.ts'
import { directedEdges, inside as bodyInside, splitBodies, watertight, windingConsistent, type Body, type Vec3 } from './meshprops.ts'
import { bvhOf } from './thickness.ts'

export const GRID_MAX = 12_000_000
export const MODEL_GRID_MAX = 24_000_000
export const GRID_MIN = 500_000
const STEPS_PER_WALL = 16
const SAMPLES_MAX = 400_000
const GRID_SHIFT: Vec3 = [0.37, 0.29, 0.43]
const FACE_QUANTILE = 0.9
const BIN = 0.04
const SEARCH_STEPS = 12
export const REFINE_MAX = 50

export class NotSolid extends Error {
  readonly reason: string
  constructor(reason: string) {
    super(reason)
    this.reason = reason
  }
}

/** a mesh with a BVH (for rays, closest points, inside tests) */
interface Surface {
  positions: Float64Array
  indices: Uint32Array
  bvh: MeshBVH
}

export interface PartField {
  origin: Vec3
  pitch: number
  shape: [number, number, number]
  /** distance to the surface per grid point (x fastest last: [ix][iy][iz] as C order), 0 outside */
  radius: Float32Array
  /** the part's surface (several bodies: their faces on the union's outside only) */
  surface: Surface
  faceNormals: Float64Array
  triThickness: Float32Array
  faceThickness: [number, number, number][]
  vertexThickness: Float32Array | null
  nominalAuto: number | null
}

// ---- small helpers -------------------------------------------------------------

function surfaceOf(m: TriMesh): Surface {
  return { positions: m.positions, indices: m.indices, bvh: bvhOf(m.positions, m.indices) }
}

function extents(p: ArrayLike<number>): [Vec3, Vec3] {
  const lo: Vec3 = [Infinity, Infinity, Infinity], hi: Vec3 = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) (lo[k] = Math.min(lo[k], p[i + k])), (hi[k] = Math.max(hi[k], p[i + k]))
  return [lo, hi]
}

const norm3 = (v: number[]) => Math.hypot(v[0], v[1], v[2])

/** per triangle: centre, unit normal (0 for a degenerate one), area */
function triangleData(p: ArrayLike<number>, f: ArrayLike<number>): { centre: Float64Array; normal: Float64Array; area: Float64Array } {
  const nt = f.length / 3
  const centre = new Float64Array(3 * nt), normal = new Float64Array(3 * nt), area = new Float64Array(nt)
  for (let t = 0; t < nt; t++) {
    const a = 3 * f[3 * t], b = 3 * f[3 * t + 1], c = 3 * f[3 * t + 2]
    for (let k = 0; k < 3; k++) centre[3 * t + k] = (p[a + k] + p[b + k] + p[c + k]) / 3
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2]
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2]
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
    const l = Math.hypot(nx, ny, nz)
    area[t] = l / 2
    if (l > 0) (normal[3 * t] = nx / l), (normal[3 * t + 1] = ny / l), (normal[3 * t + 2] = nz / l)
  }
  return { centre, normal, area }
}

function signedVolume(p: ArrayLike<number>, f: ArrayLike<number>): number {
  let v = 0
  for (let t = 0; t < f.length; t += 3) {
    const a = 3 * f[t], b = 3 * f[t + 1], c = 3 * f[t + 2]
    v += (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) - p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) + p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) / 6
  }
  return v
}

function inverted(f: ArrayLike<number>): Uint32Array {
  const out = new Uint32Array(f.length)
  for (let t = 0; t < f.length; t += 3) (out[t] = f[t]), (out[t + 1] = f[t + 2]), (out[t + 2] = f[t + 1])
  return out
}

const RAY_DIR = new Vector3(0.5773502691896258, 0.5774502691896257, 0.5772802691896258).normalize()

/** q is inside the surface: the crossings of a ray (slightly off the axes) are odd */
function containsPoint(s: Surface, q: Vec3, ray = new Ray()): boolean {
  ray.origin.set(q[0], q[1], q[2])
  ray.direction.copy(RAY_DIR)
  const hits = s.bvh.raycast(ray, DoubleSide)
  // a crossing through an edge or a vertex is reported once per triangle there: once
  const ds = hits.map((h) => h.distance).sort((a, b) => a - b)
  let n = 0
  for (let i = 0; i < ds.length; i++) if (i === 0 || ds[i] - ds[i - 1] > 1e-9) n++
  return n % 2 === 1
}

// ---- the part ---------------------------------------------------------------------

/** the part's mesh, merged by position (raises NotSolid); trustedClosed: judged elsewhere (a B-rep's) */
function solid(positions: ArrayLike<number>, indices: ArrayLike<number>, trustedClosed: boolean): TriMesh {
  if (indices.length === 0) throw new NotSolid('no_faces')
  let m = weld(positions, indices)
  if (!trustedClosed) {
    const e = directedEdges(m)
    if (!watertight(e)) throw new NotSolid('open')
    if (!windingConsistent(e)) throw new NotSolid('winding')
  }
  if (signedVolume(m.positions, m.indices) < 0) m = { positions: m.positions, indices: inverted(m.indices) }
  const [lo, hi] = extents(m.positions)
  if (Math.abs(signedVolume(m.positions, m.indices)) <= 1e-9 * norm3([hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]) ** 3) throw new NotSolid('degenerate')
  return m
}

/** the area-weighted median of inward rays from the triangles' centres */
function firstGuess(m: TriMesh, s: Surface): number {
  const [lo, hi] = extents(m.positions)
  const size = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]
  const { centre, normal, area } = triangleData(m.positions, m.indices)
  const eps = Math.max(norm3(size) * 1e-6, 1e-9)
  const ray = new Ray()
  const d: number[] = [], w: number[] = []
  for (let t = 0; t < area.length; t++) {
    const c = [centre[3 * t], centre[3 * t + 1], centre[3 * t + 2]], n = [normal[3 * t], normal[3 * t + 1], normal[3 * t + 2]]
    ray.origin.set(c[0] - n[0] * eps, c[1] - n[1] * eps, c[2] - n[2] * eps)
    ray.direction.set(-n[0], -n[1], -n[2])
    if (ray.direction.lengthSq() === 0) continue
    const hit = s.bvh.raycastFirst(ray, DoubleSide)
    if (!hit) continue
    d.push(Math.hypot(hit.point.x - c[0], hit.point.y - c[1], hit.point.z - c[2]))
    w.push(area[t])
  }
  if (!d.length) return Math.min(...size)
  return weightedMedian(d, w)
}

function weightedMedian(v: number[], w: number[]): number {
  const order = v.map((_, i) => i).sort((a, b) => v[a] - v[b] || a - b)
  let total = 0
  for (const i of order) total += w[i]
  let cw = 0
  for (const i of order) {
    cw += w[i]
    if (cw >= total / 2) return v[i]
  }
  return v[order[order.length - 1]]
}

/** the part's bodies with their roles (+1 material, -1 cavity), largest first; null for one body */
function bodiesOf(m: TriMesh): { body: Body; role: number; surface: Surface }[] | null {
  const bodies = splitBodies(m)
  if (bodies.length < 2) return null
  for (const b of bodies) {
    const sub = { positions: m.positions, indices: b.faces }
    if (!watertight(directedEdges(sub))) return null
  }
  const order = bodies.map((_, k) => k).sort((a, b) => Math.abs(bodies[b].signed) - Math.abs(bodies[a].signed) || a - b)
  const role = new Map<number, number>()
  for (const k of order) {
    const parents = [...role.keys()].filter((q) => bodyInside(m.positions, bodies[k], bodies[q]))
    if (!parents.length) role.set(k, 1)
    else {
      const p = parents.reduce((x, y) => (Math.abs(bodies[y].signed) < Math.abs(bodies[x].signed) ? y : x))
      role.set(k, bodies[k].signed * bodies[p].signed > 0 ? role.get(p)! : -role.get(p)!)
    }
  }
  return order.map((k) => ({ body: bodies[k], role: role.get(k)!, surface: { positions: m.positions, indices: bodies[k].faces, bvh: bvhOf(m.positions, bodies[k].faces) } }))
}

function inUnion(bodies: { role: number; surface: Surface }[], q: Vec3, ray: Ray): boolean {
  let out = false
  for (const b of bodies) {
    const inside = containsPoint(b.surface, q, ray)
    out = b.role > 0 ? out || inside : out && !inside
  }
  return out
}

/** the grid points inside one closed mesh: a ray up each column, the stretches between its crossings in pairs */
function insideCrossings(s: Surface, origin: Vec3, h: number, shape: [number, number, number], out: Uint8Array, role: number): void {
  const [nx, ny, nz] = shape
  const [lo, hi] = extents(s.positions)
  const ray = new Ray()
  const z0 = origin[2] - h
  const mask = new Uint8Array(nz)
  for (let ix = 0; ix < nx; ix++) {
    const x = origin[0] + h * ix
    if (x < lo[0] || x > hi[0]) continue
    for (let iy = 0; iy < ny; iy++) {
      const y = origin[1] + h * iy
      if (y < lo[1] || y > hi[1]) continue
      ray.origin.set(x, y, z0)
      ray.direction.set(0, 0, 1)
      const all = s.bvh.raycast(ray, DoubleSide).map((r) => r.point.z).sort((a, b) => a - b)
      // a crossing through an edge is one, though the two triangles there each report it
      // (embree's multiple hits, as trimesh takes them, step past each hit)
      const zs = all.filter((z, i) => i === 0 || z - all[i - 1] > 1e-9 * Math.max(1, Math.abs(z)))
      if (!zs.length) continue
      mask.fill(0)
      if (zs.length % 2 === 0) {
        for (let k = 0; k < zs.length; k += 2) {
          const a = zs[k], b = zs[k + 1]
          for (let iz = 0; iz < nz; iz++) {
            const z = origin[2] + h * iz
            if (z > a && z < b) mask[iz] = 1
          }
        }
      } else {
        // the crossings do not pair up (a ray through an edge): point by point
        for (let iz = 0; iz < nz; iz++) mask[iz] = containsPoint(s, [x, y, origin[2] + h * iz], ray) ? 1 : 0
        ray.origin.set(x, y, z0)
        ray.direction.set(0, 0, 1)
      }
      const base = (ix * ny + iy) * nz
      for (let iz = 0; iz < nz; iz++) {
        if (role > 0) out[base + iz] |= mask[iz]
        else if (mask[iz]) out[base + iz] = 0
      }
    }
  }
}

/** 1D squared distance transform (Felzenszwalb & Huttenlocher) of f (0 at the sites, Infinity elsewhere), in place */
function dt1(f: Float64Array, n: number, d: Float64Array, v: Int32Array, z: Float64Array): void {
  let k = 0
  v[0] = 0
  z[0] = -Infinity
  z[1] = Infinity
  for (let q = 1; q < n; q++) {
    if (f[q] === Infinity) continue
    if (f[v[k]] === Infinity) {
      v[k] = q
      continue
    }
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
    while (s <= z[k]) {
      k--
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
    }
    k++
    v[k] = q
    z[k] = s
    z[k + 1] = Infinity
  }
  if (f[v[0]] === Infinity) {
    d.fill(Infinity, 0, n)
    return
  }
  k = 0
  for (let q = 0; q < n; q++) {
    while (z[k + 1] < q) k++
    const r = q - v[k]
    d[q] = r * r + f[v[k]]
  }
}

/** each inside point's distance to the nearest outside grid point (scipy's distance_transform_edt with sampling h) */
export function distanceTransform(inside: Uint8Array, shape: [number, number, number], h: number): Float32Array {
  const [nx, ny, nz] = shape
  const g = new Float64Array(nx * ny * nz)
  for (let i = 0; i < g.length; i++) g[i] = inside[i] ? Infinity : 0
  const m = Math.max(nx, ny, nz)
  const f = new Float64Array(m), d = new Float64Array(m), v = new Int32Array(m), z = new Float64Array(m + 1)
  // along z (contiguous), then y, then x
  for (let ix = 0; ix < nx; ix++) {
    for (let iy = 0; iy < ny; iy++) {
      const base = (ix * ny + iy) * nz
      for (let iz = 0; iz < nz; iz++) f[iz] = g[base + iz]
      dt1(f, nz, d, v, z)
      for (let iz = 0; iz < nz; iz++) g[base + iz] = d[iz]
    }
  }
  for (let ix = 0; ix < nx; ix++) {
    for (let iz = 0; iz < nz; iz++) {
      for (let iy = 0; iy < ny; iy++) f[iy] = g[(ix * ny + iy) * nz + iz]
      dt1(f, ny, d, v, z)
      for (let iy = 0; iy < ny; iy++) g[(ix * ny + iy) * nz + iz] = d[iy]
    }
  }
  for (let iy = 0; iy < ny; iy++) {
    for (let iz = 0; iz < nz; iz++) {
      for (let ix = 0; ix < nx; ix++) f[ix] = g[(ix * ny + iy) * nz + iz]
      dt1(f, nx, d, v, z)
      for (let ix = 0; ix < nx; ix++) g[(ix * ny + iy) * nz + iz] = d[ix]
    }
  }
  const out = new Float32Array(g.length)
  for (let i = 0; i < g.length; i++) out[i] = inside[i] ? Math.sqrt(g[i]) * h : 0
  return out
}

/** the grid's distance to the surface at a point (trilinear; 0 beyond the grid, as scipy's constant mode) */
function radiusAt(f: { origin: Vec3; pitch: number; shape: [number, number, number]; radius: Float32Array }, x: number, y: number, z: number): number {
  const [nx, ny, nz] = f.shape
  const gx = (x - f.origin[0]) / f.pitch, gy = (y - f.origin[1]) / f.pitch, gz = (z - f.origin[2]) / f.pitch
  // scipy's constant mode: nothing interpolated beyond the grid's edges
  if (gx < 0 || gy < 0 || gz < 0 || gx > nx - 1 || gy > ny - 1 || gz > nz - 1) return 0
  const i0 = Math.floor(gx), j0 = Math.floor(gy), k0 = Math.floor(gz)
  const fx = gx - i0, fy = gy - j0, fz = gz - k0
  let out = 0
  for (let di = 0; di < 2; di++) {
    const i = i0 + di
    if (i < 0 || i >= nx) continue
    const wx = di ? fx : 1 - fx
    for (let dj = 0; dj < 2; dj++) {
      const j = j0 + dj
      if (j < 0 || j >= ny) continue
      const wy = dj ? fy : 1 - fy
      for (let dk = 0; dk < 2; dk++) {
        const k = k0 + dk
        if (k < 0 || k >= nz) continue
        const wz = dk ? fz : 1 - fz
        out += wx * wy * wz * f.radius[(i * ny + j) * nz + k]
      }
    }
  }
  return out
}

/** points over the triangles (the centres of an n x n split of each), their triangle, normal and area */
function samples(p: ArrayLike<number>, f: ArrayLike<number>, normal: Float64Array, area: Float64Array, spacing: number) {
  const nt = f.length / 3
  const nOf = new Int32Array(nt)
  for (let t = 0; t < nt; t++) {
    const a = 3 * f[3 * t], b = 3 * f[3 * t + 1], c = 3 * f[3 * t + 2]
    const e = Math.max(
      Math.hypot(p[a] - p[c], p[a + 1] - p[c + 1], p[a + 2] - p[c + 2]),
      Math.hypot(p[b] - p[a], p[b + 1] - p[a + 1], p[b + 2] - p[a + 2]),
      Math.hypot(p[c] - p[b], p[c + 1] - p[b + 1], p[c + 2] - p[b + 2]),
    )
    nOf[t] = Math.min(32, Math.max(1, Math.ceil(e / spacing)))
  }
  let total = 0
  for (let t = 0; t < nt; t++) total += nOf[t] * nOf[t]
  let biggest = 0
  for (let t = 0; t < nt; t++) biggest = Math.max(biggest, nOf[t])
  while (total > SAMPLES_MAX && biggest > 1) {
    total = 0
    biggest = 0
    for (let t = 0; t < nt; t++) {
      nOf[t] = Math.max(1, Math.trunc(nOf[t] * 0.8))
      total += nOf[t] * nOf[t]
      biggest = Math.max(biggest, nOf[t])
    }
  }
  const ks = [...new Set(nOf)].sort((x, y) => x - y)
  const pts: number[] = [], triOf: number[] = [], nrm: number[] = [], w: number[] = []
  for (const k of ks) {
    const bc: [number, number][] = []
    for (let i = 0; i < k; i++) {
      for (let j = 0; j < k - i; j++) {
        bc.push([(i + 1 / 3) / k, (j + 1 / 3) / k])
        if (i + j < k - 1) bc.push([(i + 2 / 3) / k, (j + 2 / 3) / k])
      }
    }
    for (let t = 0; t < nt; t++) {
      if (nOf[t] !== k) continue
      const a = 3 * f[3 * t], b = 3 * f[3 * t + 1], c = 3 * f[3 * t + 2]
      for (const [u, v] of bc) {
        for (let q = 0; q < 3; q++) pts.push(p[a + q] + u * (p[b + q] - p[a + q]) + v * (p[c + q] - p[a + q]))
        triOf.push(t)
        nrm.push(normal[3 * t], normal[3 * t + 1], normal[3 * t + 2])
        w.push(area[t] / bc.length)
      }
    }
  }
  return { pts, triOf, nrm, w }
}

/** each sample's largest tangent sphere that fits, on the grid (its diameter) */
function ball(f: PartField | Omit<PartField, 'surface' | 'faceNormals' | 'triThickness' | 'faceThickness' | 'vertexThickness' | 'nominalAuto'>, pts: number[], nrm: number[]): Float64Array {
  const n = pts.length / 3
  let rmax = 0
  for (let i = 0; i < f.radius.length; i++) rmax = Math.max(rmax, f.radius[i])
  const out = new Float64Array(n)
  const h = f.pitch
  for (let s = 0; s < n; s++) {
    let lo = 0, hi = rmax + h
    for (let it = 0; it < SEARCH_STEPS; it++) {
      const mid = (lo + hi) / 2
      const fits = radiusAt(f, pts[3 * s] - nrm[3 * s] * mid, pts[3 * s + 1] - nrm[3 * s + 1] * mid, pts[3 * s + 2] - nrm[3 * s + 2] * mid) >= mid - h / 2
      if (fits) lo = mid
      else hi = mid
    }
    out[s] = 2 * lo
  }
  return out
}

/** each group's weighted q-quantile of v (0 with no weight) and its total weight (thick._grouped_quantile) */
function groupedQuantile(group: ArrayLike<number>, v: ArrayLike<number>, w: ArrayLike<number>, size: number, q: number): [Float64Array, Float64Array] {
  const order = Array.from({ length: group.length }, (_, i) => i).sort((a, b) => group[a] - group[b] || v[a] - v[b] || a - b)
  const total = new Float64Array(size)
  for (let i = 0; i < group.length; i++) total[group[i]] += w[i]
  const med = new Float64Array(size)
  let at = 0
  let cw = 0
  let before = 0
  for (let g = 0; g < size; g++) {
    const target = before + total[g] * q
    if (total[g] > 0) {
      // the first sample (in the global order) whose cumulative weight reaches the target
      while (at < order.length && cw + w[order[at]] < target) cw += w[order[at++]]
      med[g] = v[order[Math.min(at, order.length - 1)]]
    }
    before += total[g]
    // past this group's samples
    while (at < order.length && group[order[at]] === g) cw += w[order[at++]]
  }
  return [med, total]
}

/** the area-weighted mode, in bins BIN wide on a log scale (the bin's own weighted median) */
export function nominalOf(values: ArrayLike<number>, weights: ArrayLike<number>): number | null {
  const bins = new Map<number, number>()
  for (let i = 0; i < values.length; i++) {
    if (!(values[i] > 0)) continue
    const b = Math.floor(Math.log(values[i]) / Math.log(1 + BIN))
    bins.set(b, (bins.get(b) ?? 0) + weights[i])
  }
  if (!bins.size) return null
  let best = 0, bestW = -Infinity
  for (const b of [...bins.keys()].sort((x, y) => x - y)) if (bins.get(b)! > bestW) (best = b), (bestW = bins.get(b)!)
  const v: number[] = [], w: number[] = []
  for (let i = 0; i < values.length; i++) {
    if (values[i] > 0 && Math.floor(Math.log(values[i]) / Math.log(1 + BIN)) === best) (v.push(values[i]), w.push(weights[i]))
  }
  return weightedMedian(v, w)
}

/** each part's share of MODEL_GRID_MAX by its box's volume (thick.grid_budgets) */
export function gridBudgets(boxes: Map<number, number>): Map<number, number> {
  const out = new Map<number, number>()
  if (!boxes.size) return out
  const least = Math.min(GRID_MIN, Math.floor(MODEL_GRID_MAX / boxes.size))
  let total = 0
  for (const v of boxes.values()) total += Math.max(v, 0)
  const share = new Map<number, number>()
  for (const [k, v] of boxes) {
    share.set(k, total <= 0 ? Math.min(GRID_MAX, Math.floor(MODEL_GRID_MAX / boxes.size)) : Math.min(GRID_MAX, Math.max(least, (MODEL_GRID_MAX * Math.max(v, 0)) / total)))
  }
  let sum = 0
  for (const v of share.values()) sum += v
  const over = sum / MODEL_GRID_MAX
  for (const [k, v] of share) out.set(k, Math.trunc(over > 1 ? v / over : v))
  return out
}

/** the grid and the walls of one part (raises NotSolid) (thick.part_field) */
export function partField(
  positions: ArrayLike<number>,
  indices: ArrayLike<number>,
  faceRanges: { faceId: number; triStart: number; triCount: number }[],
  trustedClosed = false,
  gridMax = GRID_MAX,
): PartField {
  const m = solid(positions, indices, trustedClosed)
  const whole = surfaceOf(m)
  const bodies = bodiesOf(m)
  const guess = firstGuess(m, whole)
  // the grid
  const [lo, hi] = extents(m.positions)
  const size = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]
  let h = guess / STEPS_PER_WALL
  while ((Math.ceil(size[0] / h) + 5) * (Math.ceil(size[1] / h) + 5) * (Math.ceil(size[2] / h) + 5) > gridMax) h *= 1.25
  h = Math.max(h, norm3(size) * 1e-4)
  const shape: [number, number, number] = [Math.ceil(size[0] / h) + 5, Math.ceil(size[1] / h) + 5, Math.ceil(size[2] / h) + 5]
  const origin: Vec3 = [lo[0] - 2 * h + h * GRID_SHIFT[0], lo[1] - 2 * h + h * GRID_SHIFT[1], lo[2] - 2 * h + h * GRID_SHIFT[2]]
  const inside = new Uint8Array(shape[0] * shape[1] * shape[2])
  if (bodies === null) insideCrossings(whole, origin, h, shape, inside, 1)
  else for (const b of bodies) insideCrossings(b.surface, origin, h, shape, inside, b.role)
  const d = distanceTransform(inside, shape, h)
  const radius = new Float32Array(d.length)
  for (let i = 0; i < d.length; i++) radius[i] = inside[i] ? Math.max(d[i] - h / 2, 0) : 0
  const grid = { origin, pitch: h, shape, radius }

  // samples on the display triangles (the face ids are the display's)
  let dispIdx: Uint32Array = Uint32Array.from(indices)
  if (signedVolume(positions, dispIdx) < 0) dispIdx = inverted(dispIdx)
  const tri = triangleData(positions, dispIdx)
  const smp = samples(positions, dispIdx, tri.normal, tri.area, Math.max(h, guess / 4))
  let { pts, triOf, nrm, w } = smp
  if (bodies !== null) {
    const dd = Math.max(norm3(size) * 1e-5, 1e-7)
    const ray = new Ray()
    const nt = dispIdx.length / 3
    const inner = new Uint8Array(nt)
    for (let t = 0; t < nt; t++) {
      const q: Vec3 = [0, 1, 2].map((k) => tri.centre[3 * t + k] + tri.normal[3 * t + k] * dd) as Vec3
      inner[t] = inUnion(bodies, q, ray) ? 1 : 0
    }
    const keep = triOf.map((t) => !inner[t])
    pts = pts.filter((_, i) => keep[Math.floor(i / 3)])
    nrm = nrm.filter((_, i) => keep[Math.floor(i / 3)])
    w = w.filter((_, i) => keep[i])
    triOf = triOf.filter((_, i) => keep[i])
  }
  const diam = ball(grid, pts, nrm)
  const nt = dispIdx.length / 3
  const [triT, triW] = groupedQuantile(triOf, diam, w, nt, FACE_QUANTILE)
  let faces: [number, number, number][] = []
  let nominal: number | null
  let vertexT: Float32Array | null = null
  if (faceRanges.length) {
    const triFace = new Int32Array(nt).fill(-1)
    faceRanges.forEach((fr, k) => triFace.fill(k, fr.triStart, fr.triStart + fr.triCount))
    const g: number[] = [], v: number[] = [], ww: number[] = []
    triOf.forEach((t, i) => {
      if (triFace[t] >= 0) (g.push(triFace[t]), v.push(diam[i]), ww.push(w[i]))
    })
    const [med, tot] = groupedQuantile(g, v, ww, faceRanges.length, FACE_QUANTILE)
    faces = faceRanges.flatMap((fr, k) => (tot[k] > 0 ? [[fr.faceId, med[k], tot[k]] as [number, number, number]] : []))
    nominal = faces.length ? nominalOf(faces.map((f) => f[1]), faces.map((f) => f[2])) : null
  } else {
    nominal = nominalOf(triT, triW)
    const nv = positions.length / 3
    const vt = new Float64Array(nv), vw = new Float64Array(nv)
    for (let t = 0; t < nt; t++) {
      for (let k = 0; k < 3; k++) {
        const i = indices[3 * t + k]
        vt[i] += triT[t] * triW[t]
        vw[i] += triT[t] > 0 ? triW[t] : 0
      }
    }
    vertexT = new Float32Array(nv)
    for (let i = 0; i < nv; i++) vertexT[i] = vw[i] > 0 ? vt[i] / Math.max(vw[i], 1e-30) : 0
  }
  // the surface the spheres touch (several bodies: their faces on the union's outside)
  let surface = whole
  if (bodies !== null) {
    const dd = Math.max(norm3(size) * 1e-5, 1e-7)
    const mt = triangleData(m.positions, m.indices)
    const ray = new Ray()
    const kept: number[] = []
    for (let t = 0; t < m.indices.length / 3; t++) {
      const q: Vec3 = [0, 1, 2].map((k) => mt.centre[3 * t + k] + mt.normal[3 * t + k] * dd) as Vec3
      if (!inUnion(bodies, q, ray)) kept.push(m.indices[3 * t], m.indices[3 * t + 1], m.indices[3 * t + 2])
    }
    surface = surfaceOf({ positions: m.positions, indices: Uint32Array.from(kept) })
  }
  return {
    ...grid,
    surface,
    faceNormals: triangleData(surface.positions, surface.indices).normal,
    triThickness: Float32Array.from(triT),
    faceThickness: faces,
    vertexThickness: vertexT,
    nominalAuto: nominal,
  }
}

// ---- 肉だまり ------------------------------------------------------------------------

const NEIGHBOURS: Vec3[] = []
for (const i of [-1, 0, 1]) for (const j of [-1, 0, 1]) for (const k of [-1, 0, 1]) if (i || j || k) NEIGHBOURS.push([i, j, k])

function closest(s: Surface, x: number, y: number, z: number, info = { point: new Vector3(), distance: 0, faceIndex: 0 }) {
  const r = s.bvh.closestPointToPoint(new Vector3(x, y, z), info)!
  // faceIndex is the mesh's own (MeshBVH's closestPointToPoint resolves an indirect BVH's order itself)
  return { point: r.point, distance: r.distance, tri: r.faceIndex }
}

/** from a grid point, the point nearby farthest from the surface (exact distances, a pattern search down to h / 32) */
function deepest(field: PartField, c: Vec3): [Vec3, number] {
  const h = field.pitch
  let best = closest(field.surface, ...c).distance
  let step = h
  while (step > h / 32) {
    let k = -1
    let bestD = -Infinity
    let cand: Vec3 | null = null
    for (const nb of NEIGHBOURS) {
      const q: Vec3 = [c[0] + nb[0] * step, c[1] + nb[1] * step, c[2] + nb[2] * step]
      if (!(radiusAt(field, ...q) > 0)) continue
      const d = closest(field.surface, ...q).distance
      if (d > bestD) (bestD = d), (cand = q), (k = 1)
    }
    if (k >= 0 && bestD > best * (1 + 1e-9)) {
      c = cand!
      best = bestD
      continue
    }
    step /= 2
  }
  return [c, best]
}

const r4 = (x: number) => Math.round(x * 1e4) / 1e4
const r3 = (x: number) => Math.round(x * 1e3) / 1e3
const r6 = (x: number) => Math.round(x * 1e6) / 1e6

/** the places where a sphere at least ratio x nominal across fits, largest first (thick.spots) */
export function spots(field: PartField, nominal: number, ratio: number) {
  const limit = (ratio * nominal) / 2
  const [nx, ny, nz] = field.shape
  const n = field.radius.length
  const label = new Int32Array(n)
  // 26-connected groups, labelled in C order (scipy's label numbers them so)
  const peaks: number[] = []
  const stack: number[] = []
  let count = 0
  for (let i = 0; i < n; i++) {
    if (label[i] || !(field.radius[i] >= limit)) continue
    count++
    label[i] = count
    stack.push(i)
    let peak = i
    while (stack.length) {
      const c = stack.pop()!
      if (field.radius[c] > field.radius[peak] || (field.radius[c] === field.radius[peak] && c < peak)) peak = c
      const cx = Math.floor(c / (ny * nz)), cy = Math.floor(c / nz) % ny, cz = c % nz
      for (let dx = -1; dx <= 1; dx++) {
        const x = cx + dx
        if (x < 0 || x >= nx) continue
        for (let dy = -1; dy <= 1; dy++) {
          const y = cy + dy
          if (y < 0 || y >= ny) continue
          for (let dz = -1; dz <= 1; dz++) {
            const z = cz + dz
            if (z < 0 || z >= nz) continue
            const q = (x * ny + y) * nz + z
            if (!label[q] && field.radius[q] >= limit) {
              label[q] = count
              stack.push(q)
            }
          }
        }
      }
    }
    peaks.push(peak)
  }
  if (!peaks.length) return []
  const centres = peaks.map((p): Vec3 => {
    const x = Math.floor(p / (ny * nz)), y = Math.floor(p / nz) % ny, z = p % nz
    return [field.origin[0] + field.pitch * x, field.origin[1] + field.pitch * y, field.origin[2] + field.pitch * z]
  })
  const order = peaks.map((_, k) => k).sort((a, b) => field.radius[peaks[b]] - field.radius[peaks[a]] || a - b)
  const out: { center: number[]; diameter: number; ratio: number; surface: number[]; normal: number[] }[] = []
  order.forEach((k, rank) => {
    let c = centres[k], r: number
    if (rank < REFINE_MAX) [c, r] = deepest(field, c)
    else r = closest(field.surface, ...c).distance
    const d = 2 * r
    const near = closest(field.surface, ...c)
    const fnrm = [0, 1, 2].map((q) => field.faceNormals[3 * near.tri + q])
    out.push({
      center: c.map(r4),
      diameter: r4(d),
      ratio: r3(d / nominal),
      surface: [near.point.x, near.point.y, near.point.z].map(r4),
      normal: fnrm.map(r6),
    })
  })
  out.sort((a, b) => b.diameter - a.diameter)
  return out
}
