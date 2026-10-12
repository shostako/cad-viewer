/**
 * 自動で合わせる for 版の比較 (docs/designs/align.md, 段 2): the compared
 * version placed where it fits the open one best, as inspection software's
 * prealignment and local best fit do.
 *
 * Where to start from: the datums' alignment alone, when it fixed every turn
 * and move; or, with none, the files' own places and the placements that put
 * the two versions' principal axes on each other (each way round the axes
 * can be); and, when the datums left a turn free (a plane alone), those and
 * the datums' alignment turned about the free axis in steps. Each is refined by point-to-plane ICP: points spread over the
 * compared version by area, each to its nearest point of the open one, along
 * the normal there. Points farther than the tolerance from the open version
 * (once the fit is close: three times the median spread before that) are left
 * out, so what changed between the versions does not pull the fit: what
 * stays apart is the change of shape, the motion the shift of place.
 *
 * A fit is the better the more of the compared version's points lie within
 * the tolerance of the open one after it (its RMS within them breaks a tie).
 * Placements that fit within a point of the best one (a symmetric shape fits
 * as well turned over or round) are told: the fit alone does not say which is
 * meant (a datum where the shape is not symmetric does).
 *
 * Runs in a Worker (alignworker.ts) in both versions of the app; no backend.
 */
import { Vector3 } from 'three'
import type { MeshBVH } from 'three-mesh-bvh'

import { turn, turnAngle, type Motion, type Xyz } from './align.ts'
import { bvhOfParts, diagonalOf, type Surface } from './compare.ts'

/** a placement of the compared version: its motion; the share of its points within the tolerance after it (0..1), and their RMS (mm) */
export interface Fit {
  motion: Motion
  within: number
  rms: number
}

export interface AutoAlignment {
  /** the placements found, the best first (no two the same placement) */
  fits: Fit[]
  /** how many after the first fit about as well (within ALIKE of its share): a symmetric shape */
  alike: number
  /** how many placements it started from (1: the datums' alignment alone) */
  starts: number
}

/** points for the search from each start, and for the last fit of the best ones */
export const SEARCH_POINTS = 1500
export const FINAL_POINTS = 12000
/** ICP's rounds at most, and at each reach */
const ROUNDS = 120
const ROUNDS_PER_REACH = 12
/** a placement fits about as well as the best one within this share of the points (a symmetric shape) */
export const ALIKE = 0.01
/** two eigenvalues this close (relative to the largest) may swap their axes */
const SAME_SPREAD = 0.15

/** a small deterministic random (mulberry32): the same points every time for the same files */
function random(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** n points spread over the surfaces by area (x, y, z each) */
export function samplePoints(parts: Surface[], n: number, seed = 1): Float64Array {
  const tris: { s: Surface; t: number }[] = []
  const cum: number[] = []
  let total = 0
  for (const s of parts) {
    const P = s.positions, ix = s.indices
    for (let t = 0; t < ix.length; t += 3) {
      const a = 3 * ix[t], b = 3 * ix[t + 1], c = 3 * ix[t + 2]
      const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2]
      const vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2]
      const area = Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) / 2
      if (!(area > 0)) continue
      total += area
      tris.push({ s, t })
      cum.push(total)
    }
  }
  const out = new Float64Array(3 * n)
  if (!tris.length) return new Float64Array(0)
  const rnd = random(seed)
  for (let i = 0; i < n; i++) {
    // the triangle by area (a binary search in the running sums), a point in it
    const x = rnd() * total
    let lo = 0, hi = cum.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (cum[mid] < x) lo = mid + 1
      else hi = mid
    }
    const { s, t } = tris[lo]
    let u = rnd(), v = rnd()
    if (u + v > 1) (u = 1 - u), (v = 1 - v)
    const P = s.positions, ix = s.indices
    const a = 3 * ix[t], b = 3 * ix[t + 1], c = 3 * ix[t + 2]
    for (let k = 0; k < 3; k++) out[3 * i + k] = P[a + k] + u * (P[b + k] - P[a + k]) + v * (P[c + k] - P[a + k])
  }
  return out
}

/** the centroid and the principal axes (columns of a turn, det +1) of points, with their spreads (eigenvalues), largest first */
export function principal(pts: Float64Array): { centre: Xyz; axes: number[]; spread: Xyz } {
  const n = pts.length / 3
  const c: Xyz = [0, 0, 0]
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) c[k] += pts[3 * i + k] / n
  const m = [0, 0, 0, 0, 0, 0, 0, 0, 0]
  for (let i = 0; i < n; i++) {
    const d = [pts[3 * i] - c[0], pts[3 * i + 1] - c[1], pts[3 * i + 2] - c[2]]
    for (let r = 0; r < 3; r++) for (let q = 0; q < 3; q++) m[3 * r + q] += (d[r] * d[q]) / n
  }
  const { values, vectors } = jacobi(m)
  const order = [0, 1, 2].sort((x, y) => values[y] - values[x])
  const axes = new Array<number>(9)
  order.forEach((j, col) => {
    for (let r = 0; r < 3; r++) axes[3 * r + col] = vectors[3 * r + j]
  })
  // det +1: a turn, not a mirror
  const det =
    axes[0] * (axes[4] * axes[8] - axes[5] * axes[7]) - axes[1] * (axes[3] * axes[8] - axes[5] * axes[6]) + axes[2] * (axes[3] * axes[7] - axes[4] * axes[6])
  if (det < 0) for (let r = 0; r < 3; r++) axes[3 * r + 2] *= -1
  return { centre: c, axes, spread: [values[order[0]], values[order[1]], values[order[2]]] }
}

/** the eigenvalues and eigenvectors (columns) of a symmetric 3 x 3 (row-major), by Jacobi's rotations */
function jacobi(a0: number[]): { values: Xyz; vectors: number[] } {
  const a = [...a0]
  const v = [1, 0, 0, 0, 1, 0, 0, 0, 1]
  for (let sweep = 0; sweep < 50; sweep++) {
    const off = Math.abs(a[1]) + Math.abs(a[2]) + Math.abs(a[5])
    if (off < 1e-15 * (Math.abs(a[0]) + Math.abs(a[4]) + Math.abs(a[8]) + 1e-300)) break
    for (const [p, q] of [[0, 1], [0, 2], [1, 2]]) {
      const apq = a[3 * p + q]
      if (Math.abs(apq) < 1e-300) continue
      const theta = (a[3 * q + q] - a[3 * p + p]) / (2 * apq)
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1))
      const c = 1 / Math.sqrt(t * t + 1), s = t * c
      // a <- J^T a J, v <- v J (J the rotation in the p-q plane)
      for (let k = 0; k < 3; k++) {
        const akp = a[3 * k + p], akq = a[3 * k + q]
        a[3 * k + p] = c * akp - s * akq
        a[3 * k + q] = s * akp + c * akq
      }
      for (let k = 0; k < 3; k++) {
        const apk = a[3 * p + k], aqk = a[3 * q + k]
        a[3 * p + k] = c * apk - s * aqk
        a[3 * q + k] = s * apk + c * aqk
      }
      for (let k = 0; k < 3; k++) {
        const vkp = v[3 * k + p], vkq = v[3 * k + q]
        v[3 * k + p] = c * vkp - s * vkq
        v[3 * k + q] = s * vkp + c * vkq
      }
    }
  }
  return { values: [a[0], a[4], a[8]], vectors: v }
}

const mul = (a: readonly number[], b: readonly number[]) => {
  const out = new Array<number>(9)
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[3 * i + j] = a[3 * i] * b[j] + a[3 * i + 1] * b[3 + j] + a[3 * i + 2] * b[6 + j]
  return out
}
const transpose = (a: readonly number[]) => [a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8]]

/** the 24 turns that take the axes onto the axes (signed permutations, det +1) */
function axisTurns(): number[][] {
  const out: number[][] = []
  const perms = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]]
  for (const p of perms) {
    for (let signs = 0; signs < 8; signs++) {
      const m = [0, 0, 0, 0, 0, 0, 0, 0, 0]
      for (let r = 0; r < 3; r++) m[3 * r + p[r]] = signs & (1 << r) ? -1 : 1
      const det = m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6])
      if (det > 0) out.push(m)
    }
  }
  return out
}

/**
 * The placements that put the compared version's principal axes on the open
 * one's: each way round (4), and with axes of about the same spread swapped
 * (a square plate: 8, a cube: 24). Their centroids on each other.
 */
export function axisStarts(a: Float64Array, b: Float64Array): Motion[] {
  const pa = principal(a), pb = principal(b)
  const big = Math.max(pa.spread[0], pb.spread[0], 1e-300)
  const out: Motion[] = []
  for (const s of axisTurns()) {
    // s takes b's axis j to a's axis i where s[i][j] != 0: only axes of about the same spread
    let ok = true
    for (let i = 0; i < 3 && ok; i++) for (let j = 0; j < 3; j++) if (s[3 * i + j] && Math.abs(pa.spread[i] - pb.spread[j]) > SAME_SPREAD * big) ok = false
    if (!ok) continue
    const r = mul(mul(pa.axes, s), transpose(pb.axes))
    const rc = turn(r, pb.centre)
    out.push({ r, t: [pa.centre[0] - rc[0], pa.centre[1] - rc[1], pa.centre[2] - rc[2]] })
  }
  return out
}

/** the open version's triangles: for each, its unit normal (the BVH's geometry, in its index order) */
function triangleNormals(bvh: MeshBVH): Float64Array {
  const g = bvh.geometry
  const P = g.getAttribute('position').array, ix = g.index!.array
  const out = new Float64Array(ix.length)
  for (let t = 0; t < ix.length; t += 3) {
    const a = 3 * ix[t], b = 3 * ix[t + 1], c = 3 * ix[t + 2]
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2]
    const vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2]
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
    const l = Math.hypot(nx, ny, nz) || 1
    out[t] = nx / l
    out[t + 1] = ny / l
    out[t + 2] = nz / l
  }
  return out
}

interface Target {
  bvh: MeshBVH
  normals: Float64Array
}

/** each point moved by m, its nearest point on the open version: the distance, and (into near/normal) where and the normal there */
function nearest(target: Target, m: Motion, pts: Float64Array, near: Float64Array, normal: Float64Array, dist: Float64Array): void {
  const p = new Vector3()
  const hit = { point: new Vector3(), distance: 0, faceIndex: 0 }
  const r = m.r, t = m.t
  for (let i = 0; i < pts.length / 3; i++) {
    const x = pts[3 * i], y = pts[3 * i + 1], z = pts[3 * i + 2]
    p.set(r[0] * x + r[1] * y + r[2] * z + t[0], r[3] * x + r[4] * y + r[5] * z + t[1], r[6] * x + r[7] * y + r[8] * z + t[2])
    target.bvh.closestPointToPoint(p, hit)
    near[3 * i] = hit.point.x
    near[3 * i + 1] = hit.point.y
    near[3 * i + 2] = hit.point.z
    const f = 3 * hit.faceIndex
    normal[3 * i] = target.normals[f]
    normal[3 * i + 1] = target.normals[f + 1]
    normal[3 * i + 2] = target.normals[f + 2]
    dist[i] = hit.distance
  }
}

function median(xs: Float64Array): number {
  const s = Float64Array.from(xs).sort()
  return s.length ? s[s.length >> 1] : 0
}

/** the turn of a small rotation vector w (Rodrigues) */
function smallTurn(w: Xyz): number[] {
  const th = Math.hypot(w[0], w[1], w[2])
  if (th < 1e-300) return [1, 0, 0, 0, 1, 0, 0, 0, 1]
  const [x, y, z] = [w[0] / th, w[1] / th, w[2] / th]
  const c = Math.cos(th), s = Math.sin(th), C = 1 - c
  return [c + x * x * C, x * y * C - z * s, x * z * C + y * s, y * x * C + z * s, c + y * y * C, y * z * C - x * s, z * x * C - y * s, z * y * C + x * s, c + z * z * C]
}

/** the 6 x 6 system solved (Gaussian elimination with pivoting); null when it is singular */
function solve6(A: number[], b: number[]): number[] | null {
  const n = 6
  const M = A.map((v) => v)
  const x = b.map((v) => v)
  for (let col = 0; col < n; col++) {
    let piv = col
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r * n + col]) > Math.abs(M[piv * n + col])) piv = r
    if (Math.abs(M[piv * n + col]) < 1e-300) return null
    if (piv !== col) {
      for (let k = 0; k < n; k++) [M[col * n + k], M[piv * n + k]] = [M[piv * n + k], M[col * n + k]]
      ;[x[col], x[piv]] = [x[piv], x[col]]
    }
    for (let r = col + 1; r < n; r++) {
      const f = M[r * n + col] / M[col * n + col]
      for (let k = col; k < n; k++) M[r * n + k] -= f * M[col * n + k]
      x[r] -= f * x[col]
    }
  }
  for (let r = n - 1; r >= 0; r--) {
    let s = x[r]
    for (let k = r + 1; k < n; k++) s -= M[r * n + k] * x[k]
    x[r] = s / M[r * n + r]
  }
  return x
}

/**
 * Point-to-plane ICP from m: each round, the points moved, their nearest
 * points and normals on the open version, and the small motion that brings
 * them onto the planes there (linearized about their centre, damped where
 * they do not hold it: a flat face lets it slide). Each point is weighted by
 * how near it is against a reach (Cauchy: 1 / (1 + (d / reach)²), none past 5
 * reaches), the reach halved from `reach` down to the tolerance as the fit
 * settles (a cut that is narrow from the start leaves out the points that
 * would put the rest right, and the fit stops short). Last, the points within
 * the tolerance alone (what changed is out of it).
 */
export function refine(target: Target, m0: Motion, pts: Float64Array, tolerance: number, size: number, reach0?: number): Motion {
  const n = pts.length / 3
  const near = new Float64Array(3 * n), normal = new Float64Array(3 * n), dist = new Float64Array(n), weight = new Float64Array(n)
  let m: Motion = { r: [...m0.r], t: [...m0.t] as Xyz }
  nearest(target, m, pts, near, normal, dist)
  let reach = Math.max(tolerance, reach0 ?? 3 * median(dist))
  let total = 0
  for (let last = false; ; ) {
    for (let round = 0; round < ROUNDS_PER_REACH && total < ROUNDS; round++, total++) {
      nearest(target, m, pts, near, normal, dist)
      for (let i = 0; i < n; i++) {
        const d = dist[i]
        weight[i] = last ? (d <= tolerance ? 1 : 0) : d > 5 * reach ? 0 : 1 / (1 + (d / reach) ** 2)
      }
      const step = stepOf(m, pts, near, normal, weight, size)
      if (!step) break
      m = step.m
      if (step.small) break
    }
    if (last || total >= ROUNDS) break
    if (reach <= tolerance) last = true
    else reach = Math.max(tolerance, reach / 2)
  }
  return m
}

/** one Gauss-Newton step of the weighted point-to-plane fit (null: too few points to hold it) */
function stepOf(
  m: Motion,
  pts: Float64Array,
  near: Float64Array,
  normal: Float64Array,
  weight: Float64Array,
  size: number,
): { m: Motion; small: boolean } | null {
  const n = pts.length / 3
  const r = m.r
  const moved = (i: number): Xyz => {
    const x = pts[3 * i], y = pts[3 * i + 1], z = pts[3 * i + 2]
    return [r[0] * x + r[1] * y + r[2] * z + m.t[0], r[3] * x + r[4] * y + r[5] * z + m.t[1], r[6] * x + r[7] * y + r[8] * z + m.t[2]]
  }
  // the weighted points' centre (the turn is about it)
  const c: Xyz = [0, 0, 0]
  let wsum = 0, count = 0
  for (let i = 0; i < n; i++) {
    if (!(weight[i] > 0)) continue
    const q = moved(i)
    for (let k = 0; k < 3; k++) c[k] += weight[i] * q[k]
    wsum += weight[i]
    count++
  }
  if (count < 6 || !(wsum > 0)) return null
  for (let k = 0; k < 3; k++) c[k] /= wsum
  const A = new Array<number>(36).fill(0), b = new Array<number>(6).fill(0)
  for (let i = 0; i < n; i++) {
    const w = weight[i]
    if (!(w > 0)) continue
    const q = moved(i)
    const nx = normal[3 * i], ny = normal[3 * i + 1], nz = normal[3 * i + 2]
    const px = q[0] - c[0], py = q[1] - c[1], pz = q[2] - c[2]
    // J = [(p - c) x n, n], the residual (p - its nearest point) . n
    const J = [py * nz - pz * ny, pz * nx - px * nz, px * ny - py * nx, nx, ny, nz]
    const res = (q[0] - near[3 * i]) * nx + (q[1] - near[3 * i + 1]) * ny + (q[2] - near[3 * i + 2]) * nz
    for (let row = 0; row < 6; row++) {
      b[row] -= w * J[row] * res
      for (let col = 0; col < 6; col++) A[6 * row + col] += w * J[row] * J[col]
    }
  }
  // damping: the turn's rows in mm² (the part's size), the move's in 1
  const damp = 1e-9 * wsum
  for (let row = 0; row < 3; row++) A[7 * row] += damp * size * size
  for (let row = 3; row < 6; row++) A[7 * row] += damp
  const x = solve6(A, b)
  if (!x) return null
  const w: Xyz = [x[0], x[1], x[2]], dt: Xyz = [x[3], x[4], x[5]]
  const R = smallTurn(w)
  const rc = turn(R, [m.t[0] - c[0], m.t[1] - c[1], m.t[2] - c[2]])
  return {
    m: { r: mul(R, m.r), t: [rc[0] + c[0] + dt[0], rc[1] + c[1] + dt[1], rc[2] + c[2] + dt[2]] },
    small: Math.hypot(...w) < 1e-10 && Math.hypot(...dt) < 1e-10 * size,
  }
}

/** how well m fits: the share of the points within the tolerance of the open version, and their RMS */
export function fitOf(target: Target, m: Motion, pts: Float64Array, tolerance: number): Fit {
  const n = pts.length / 3
  const near = new Float64Array(3 * n), normal = new Float64Array(3 * n), dist = new Float64Array(n)
  nearest(target, m, pts, near, normal, dist)
  let k = 0, sq = 0
  for (const d of dist) {
    if (d > tolerance) continue
    k++
    sq += d * d
  }
  return { motion: m, within: n ? k / n : 0, rms: k ? Math.sqrt(sq / k) : 0 }
}

/** two motions place the compared version the same (within a tenth of a degree, and the tolerance at its farthest point) */
function samePlace(a: Motion, b: Motion, reach: number, tolerance: number): boolean {
  const rel = turnAngle(mul(a.r, transpose(b.r))).angle
  const d = Math.hypot(a.t[0] - b.t[0], a.t[1] - b.t[1], a.t[2] - b.t[2])
  return rel < 0.1 && d + (rel * Math.PI * reach) / 180 <= Math.max(tolerance, 1e-6 * reach)
}

/** where 自動で合わせる starts from (the module's comment) */
export interface AutoStart {
  /** the alignment there is (the datums'); null: none */
  motion: Motion | null
  /**
   * the datums left a turn free about this axis (through `at`, on the open
   * version): the start turned about it each SPIN_STEP degrees is tried too,
   * and the search from the files' own places and the principal axes
   */
  spin?: { axis: Xyz; at: Xyz } | null
}

/** the steps of the turns about a datum's free axis (degrees) */
export const SPIN_STEP = 30

/** the starts to refine (the module's comment) */
function startsOf(start: AutoStart, a: Surface[], search: Float64Array): Motion[] {
  const identity: Motion = { r: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0] }
  const searched = () => [identity, ...axisStarts(samplePoints(a, SEARCH_POINTS, 3), search)]
  const m = start.motion
  if (!m) return searched()
  if (!start.spin) return [m]
  const { axis, at } = start.spin
  const spun: Motion[] = []
  for (let k = 0; k < 360 / SPIN_STEP; k++) {
    const R = smallTurn([axis[0] * k * SPIN_STEP * (Math.PI / 180), axis[1] * k * SPIN_STEP * (Math.PI / 180), axis[2] * k * SPIN_STEP * (Math.PI / 180)])
    const q = turn(R, [m.t[0] - at[0], m.t[1] - at[1], m.t[2] - at[2]])
    spun.push({ r: mul(R, m.r), t: [q[0] + at[0], q[1] + at[1], q[2] + at[2]] })
  }
  return [...spun, ...searched()]
}

/**
 * The compared version (b) placed to fit the open one (a) best (the module's
 * comment), from `start`.
 */
export function autoAlign(a: Surface[], b: Surface[], start: AutoStart, tolerance: number): AutoAlignment {
  const bvh = bvhOfParts(a)
  const target: Target = { bvh, normals: triangleNormals(bvh) }
  const size = diagonalOf(a, b) || 1
  const search = samplePoints(b, SEARCH_POINTS, 1)
  const final = samplePoints(b, FINAL_POINTS, 2)
  const starts = startsOf(start, a, search)
  // each start refined on the few points, the distinct placements kept
  const found: Fit[] = []
  for (const s of starts) {
    const m = refine(target, s, search, tolerance, size)
    const f = fitOf(target, m, search, tolerance)
    if (!found.some((g) => samePlace(g.motion, m, size, tolerance))) found.push(f)
  }
  found.sort((x, y) => y.within - x.within || x.rms - y.rms)
  // the best ones (those that fit about as well as the first) refined on the many points
  const best = found[0]?.within ?? 0
  const near = found.filter((f) => f.within >= best - 3 * ALIKE)
  const fits: Fit[] = []
  for (const f of near) {
    const m = refine(target, f.motion, final, tolerance, size, 4 * tolerance)
    if (!fits.some((g) => samePlace(g.motion, m, size, tolerance))) fits.push(fitOf(target, m, final, tolerance))
  }
  return { ...ordered(fits, centreOf(final), size), starts: starts.length }
}

/**
 * The placements in their order: the best fit first; of those that fit about
 * as well as it (within ALIKE), the one that moves the compared version
 * (`centre`, of a part of `size`) least first (two versions of a symmetric part
 * written in one frame stay as they are, not turned over). alike: how many
 * after the first fit about as well.
 */
export function ordered(found: Fit[], centre: Xyz, size: number): { fits: Fit[]; alike: number } {
  const fits = [...found].sort((x, y) => y.within - x.within || x.rms - y.rms)
  const top = fits[0]?.within ?? 0
  const alikeFits = fits.filter((f) => f.within >= top - ALIKE)
  const rest = fits.filter((f) => f.within < top - ALIKE)
  alikeFits.sort((x, y) => moveSize(x.motion, centre, size) - moveSize(y.motion, centre, size))
  return { fits: [...alikeFits, ...rest], alike: Math.max(0, alikeFits.length - 1) }
}

/** the points' centroid */
function centreOf(pts: Float64Array): Xyz {
  const c: Xyz = [0, 0, 0]
  const n = pts.length / 3
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) c[k] += pts[3 * i + k] / n
  return c
}

/** how far a motion takes the compared version: its turn (radians times the size) and its centre's move */
function moveSize(m: Motion, centre: Xyz, size: number): number {
  const q = turn(m.r, centre)
  return (turnAngle(m.r).angle * Math.PI * size) / 180 + Math.hypot(q[0] + m.t[0] - centre[0], q[1] + m.t[1] - centre[1], q[2] + m.t[2] - centre[2])
}
