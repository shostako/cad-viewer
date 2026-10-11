/**
 * Volume, area and centre of mass of a mesh-format part (backend/app/properties.py's
 * mesh_part_properties and _mesh_bodies; the judgement is as strict there:
 * an open or wrongly wound mesh gets no volume, never a partial one).
 *
 * The display mesh's vertices are split along sharp edges: merged back by
 * position first, or every box would read as open.
 */
import { weld, type TriMesh } from './meshload.ts'

export type Reason = 'open' | 'no_faces' | 'degenerate' | 'winding' | 'failed'
export type Vec3 = [number, number, number]

export interface PartProps {
  closed: boolean
  volume: number | null
  area: number | null
  centerOfMass: Vec3 | null
  reason: Reason | null
}

const DEGENERATE_REL = 1e-9

function part(closed: boolean, volume: number | null, area: number | null, com: Vec3 | null, reason: Reason | null): PartProps {
  return { closed, volume, area, centerOfMass: com, reason }
}

export function meshPartProperties(positions: ArrayLike<number>, indices: ArrayLike<number>): PartProps {
  try {
    if (indices.length === 0) return part(false, null, 0, null, 'no_faces')
    const m = weld(positions, indices)
    const area = meshArea(m)
    const edges = directedEdges(m)
    if (!watertight(edges)) return part(false, null, area, null, 'open')
    if (!windingConsistent(edges)) return part(false, null, area, null, 'winding')
    const [lo, hi] = bounds(m.positions)
    const diag = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    const [volume, com] = meshBodies(m)
    if (volume <= DEGENERATE_REL * diag ** 3) return part(false, null, area, null, 'degenerate')
    return part(true, volume, area, com, null)
  } catch {
    return part(false, null, null, null, 'failed')
  }
}

export function meshArea(m: TriMesh): number {
  const p = m.positions, f = m.indices
  let area = 0
  for (let t = 0; t < f.length; t += 3) {
    const a = 3 * f[t], b = 3 * f[t + 1], c = 3 * f[t + 2]
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2]
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2]
    area += Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) / 2
  }
  return area
}

/** each directed edge (from, to), as from * nv + to -> how many faces run along it that way */
interface Edges {
  count: Map<number, number>
  nv: number
}

function directedEdges(m: TriMesh): Edges {
  const nv = m.positions.length / 3
  const f = m.indices
  const count = new Map<number, number>()
  for (let t = 0; t < f.length; t += 3) {
    for (let k = 0; k < 3; k++) {
      const key = f[t + k] * nv + f[t + ((k + 1) % 3)]
      count.set(key, (count.get(key) ?? 0) + 1)
    }
  }
  return { count, nv }
}

/** every edge has exactly two faces (whichever way they run) */
function watertight({ count, nv }: Edges): boolean {
  const undirected = new Map<number, number>()
  for (const [key, n] of count) {
    const a = Math.floor(key / nv), b = key % nv
    const u = Math.min(a, b) * nv + Math.max(a, b)
    undirected.set(u, (undirected.get(u) ?? 0) + n)
  }
  for (const n of undirected.values()) if (n !== 2) return false
  return true
}

/** the two faces of every edge run along it opposite ways (a closed mesh) */
function windingConsistent({ count, nv }: Edges): boolean {
  for (const [key, n] of count) {
    if (n !== 1) return false
    const a = Math.floor(key / nv), b = key % nv
    if (count.get(b * nv + a) !== 1) return false
  }
  return true
}

function bounds(p: ArrayLike<number>): [Vec3, Vec3] {
  const lo: Vec3 = [Infinity, Infinity, Infinity]
  const hi: Vec3 = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < p.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], p[i + k])
      hi[k] = Math.max(hi[k], p[i + k])
    }
  }
  return [lo, hi]
}

interface Body {
  /** its faces' indices into the mesh's (three per face) */
  faces: Uint32Array
  signed: number
  com: Vec3
  lo: Vec3
  hi: Vec3
}

/** the mesh's bodies: faces connected through shared edges */
function splitBodies(m: TriMesh): Body[] {
  const f = m.indices
  const nf = f.length / 3
  const nv = m.positions.length / 3
  const parent = Int32Array.from({ length: nf }, (_, i) => i)
  const find = (i: number): number => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]]
      i = parent[i]
    }
    return i
  }
  const firstFace = new Map<number, number>()
  for (let t = 0; t < nf; t++) {
    for (let k = 0; k < 3; k++) {
      const i = f[3 * t + k], j = f[3 * t + ((k + 1) % 3)]
      const key = Math.min(i, j) * nv + Math.max(i, j)
      const other = firstFace.get(key)
      if (other === undefined) firstFace.set(key, t)
      else {
        const ra = find(t), rb = find(other)
        if (ra !== rb) parent[Math.max(ra, rb)] = Math.min(ra, rb)
      }
    }
  }
  const byRoot = new Map<number, number[]>()
  for (let t = 0; t < nf; t++) {
    const r = find(t)
    const list = byRoot.get(r)
    if (list) list.push(f[3 * t], f[3 * t + 1], f[3 * t + 2])
    else byRoot.set(r, [f[3 * t], f[3 * t + 1], f[3 * t + 2]])
  }
  return [...byRoot.values()].map((list) => body(m.positions, Uint32Array.from(list)))
}

/** a body's signed volume (positive when its faces point out) and centre of mass */
function body(p: Float64Array, faces: Uint32Array): Body {
  let vol = 0
  const mom: Vec3 = [0, 0, 0]
  const lo: Vec3 = [Infinity, Infinity, Infinity]
  const hi: Vec3 = [-Infinity, -Infinity, -Infinity]
  for (let t = 0; t < faces.length; t += 3) {
    const a = 3 * faces[t], b = 3 * faces[t + 1], c = 3 * faces[t + 2]
    const v =
      (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) -
        p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) +
        p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) /
      6
    vol += v
    for (let k = 0; k < 3; k++) {
      mom[k] += (v * (p[a + k] + p[b + k] + p[c + k])) / 4
      lo[k] = Math.min(lo[k], p[a + k], p[b + k], p[c + k])
      hi[k] = Math.max(hi[k], p[a + k], p[b + k], p[c + k])
    }
  }
  const com: Vec3 = vol !== 0 ? [mom[0] / vol, mom[1] / vol, mom[2] / vol] : [0, 0, 0]
  return { faces, signed: vol, com, lo, hi }
}

/**
 * volume and centre of mass, body by body: a body's role comes from the
 * smallest body that encloses it and their relative orientation (facing the
 * other way flips material -> cavity -> island; the same way, an overlap, is
 * summed). Decided largest first, so a parent is decided before its child.
 */
function meshBodies(m: TriMesh): [number, Vec3] {
  const bodies = splitBodies(m)
  if (bodies.length === 1) return [Math.abs(bodies[0].signed), bodies[0].com]
  const whole = body(m.positions, m.indices)
  const order = bodies.map((_, k) => k).sort((a, b) => Math.abs(bodies[b].signed) - Math.abs(bodies[a].signed) || a - b)
  const role = new Map<number, number>()
  let total = 0
  const mom: Vec3 = [0, 0, 0]
  for (const k of order) {
    const parents = [...role.keys()].filter((q) => inside(m.positions, bodies[k], bodies[q]))
    if (!parents.length) role.set(k, 1)
    else {
      const p = parents.reduce((x, y) => (Math.abs(bodies[y].signed) < Math.abs(bodies[x].signed) ? y : x))
      const same = bodies[k].signed * bodies[p].signed > 0
      role.set(k, same ? role.get(p)! : -role.get(p)!)
    }
    const w = role.get(k)! * Math.abs(bodies[k].signed)
    total += w
    for (let i = 0; i < 3; i++) mom[i] += w * bodies[k].com[i]
  }
  if (total <= 0) return [0, whole.com]
  return [total, [mom[0] / total, mom[1] / total, mom[2] / total]]
}

/** inner lies within outer: a majority of inner's centre and a few of its vertices (pulled a hair toward it) */
function inside(p: Float64Array, inner: Body, outer: Body): boolean {
  for (let k = 0; k < 3; k++) if (inner.lo[k] < outer.lo[k] || inner.hi[k] > outer.hi[k]) return false
  const verts = [...new Set(inner.faces)].sort((a, b) => a - b)
  const step = Math.max(1, Math.floor(verts.length / 4))
  const probes: Vec3[] = [inner.com]
  for (let i = 0; i < verts.length && probes.length < 5; i += step) {
    const v = 3 * verts[i]
    probes.push([0, 1, 2].map((k) => p[v + k] + (inner.com[k] - p[v + k]) * 1e-6) as Vec3)
  }
  let hits = 0
  for (const q of probes) if (contains(p, outer.faces, q)) hits++
  return hits * 2 > probes.length
}

/** q is inside the closed surface of these faces: crossings of a ray (odd), the ray slightly off the axes */
export function contains(p: Float64Array, faces: Uint32Array, q: Vec3): boolean {
  const d: Vec3 = [0.5773502691896258, 0.5773502691896257 + 1.3e-4, 0.5773502691896258 - 0.7e-4]
  let crossings = 0
  for (let t = 0; t < faces.length; t += 3) {
    const a = 3 * faces[t], b = 3 * faces[t + 1], c = 3 * faces[t + 2]
    // Möller–Trumbore
    const e1x = p[b] - p[a], e1y = p[b + 1] - p[a + 1], e1z = p[b + 2] - p[a + 2]
    const e2x = p[c] - p[a], e2y = p[c + 1] - p[a + 1], e2z = p[c + 2] - p[a + 2]
    const hx = d[1] * e2z - d[2] * e2y, hy = d[2] * e2x - d[0] * e2z, hz = d[0] * e2y - d[1] * e2x
    const det = e1x * hx + e1y * hy + e1z * hz
    if (Math.abs(det) < 1e-18) continue
    const inv = 1 / det
    const sx = q[0] - p[a], sy = q[1] - p[a + 1], sz = q[2] - p[a + 2]
    const u = (sx * hx + sy * hy + sz * hz) * inv
    if (u < 0 || u > 1) continue
    const qx = sy * e1z - sz * e1y, qy = sz * e1x - sx * e1z, qz = sx * e1y - sy * e1x
    const v = (d[0] * qx + d[1] * qy + d[2] * qz) * inv
    if (v < 0 || u + v > 1) continue
    const tt = (e2x * qx + e2y * qy + e2z * qz) * inv
    if (tt > 0) crossings++
  }
  return crossings % 2 === 1
}

export interface ModelProps {
  source: 'brep' | 'mesh'
  units: 'mm'
  parts: (PartProps & { id: number; name: string })[]
  total: {
    volume: number | null
    area: number | null
    centerOfMass: Vec3 | null
    closedParts: number
    openParts: number
  }
}

/** the parts' totals (properties.py's _model) */
export function modelProps(source: 'brep' | 'mesh', parts: (PartProps & { id: number; name: string })[]): ModelProps {
  const closed = parts.filter((p) => p.volume !== null)
  const withArea = parts.filter((p) => p.area !== null)
  let volume: number | null = null
  let com: Vec3 | null = null
  if (closed.length) {
    volume = closed.reduce((s, p) => s + p.volume!, 0)
    com = [0, 1, 2].map((i) => closed.reduce((s, p) => s + p.volume! * p.centerOfMass![i], 0) / volume!) as Vec3
  }
  return {
    source,
    units: 'mm',
    parts,
    total: {
      volume,
      area: withArea.length ? withArea.reduce((s, p) => s + p.area!, 0) : null,
      centerOfMass: com,
      closedParts: closed.length,
      openParts: parts.length - closed.length,
    },
  }
}
