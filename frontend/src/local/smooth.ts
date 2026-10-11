/**
 * The display mesh of a triangle mesh: vertices split along sharp edges, so
 * flat faces shade flat and curved ones smooth (backend/app/loaders.py, after
 * trimesh's graph.smooth_shade with its 30 degrees).
 *
 * Faces are grouped: adjacent faces less than 30 degrees apart are one smooth
 * surface, except that a large flat region (trimesh's facets: adjacent faces in
 * one plane, |sin| of their angle under 1 / (2 sqrt 5000), so within 0.405
 * degrees or turned over; of more than a tenth of the mesh's area) is a group
 * of its own, so its edge does not round off into a fillet next to it. A vertex gets a
 * copy per group it is in, its normal the mean of that group's faces at it,
 * weighted by their angle there (trimesh's vertex normals).
 */
import type { TriMesh } from './meshload.ts'

export interface DisplayMesh {
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
}

const SMOOTH = (30 * Math.PI) / 180
/** trimesh's facets: (radius / span)^2 > 5000 with radius = span / |2 sin angle|, so |sin angle| under this */
const FACET_SIN = 1 / (2 * Math.sqrt(5000))
const FACET_MIN_AREA = 10

/** union-find over n items */
class Groups {
  readonly parent: Int32Array
  constructor(n: number) {
    this.parent = Int32Array.from({ length: n }, (_, i) => i)
  }
  find(i: number): number {
    while (this.parent[i] !== i) {
      this.parent[i] = this.parent[this.parent[i]]
      i = this.parent[i]
    }
    return i
  }
  join(a: number, b: number): void {
    const ra = this.find(a), rb = this.find(b)
    if (ra !== rb) this.parent[Math.max(ra, rb)] = Math.min(ra, rb)
  }
}

export interface FaceData {
  normals: Float64Array
  areas: Float64Array
  /** pairs of faces sharing an edge (an edge of exactly two faces) */
  adjacency: Uint32Array
}

export function faceData(m: TriMesh): FaceData {
  const p = m.positions, f = m.indices
  const nf = f.length / 3
  const normals = new Float64Array(nf * 3)
  const areas = new Float64Array(nf)
  for (let t = 0; t < nf; t++) {
    const a = 3 * f[3 * t], b = 3 * f[3 * t + 1], c = 3 * f[3 * t + 2]
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2]
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2]
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
    const len = Math.hypot(nx, ny, nz)
    areas[t] = len / 2
    if (len > 0) {
      normals[3 * t] = nx / len
      normals[3 * t + 1] = ny / len
      normals[3 * t + 2] = nz / len
    }
  }
  const edgeFaces = new Map<number, number[]>()
  const nv = p.length / 3
  for (let t = 0; t < nf; t++) {
    for (let k = 0; k < 3; k++) {
      const i = f[3 * t + k], j = f[3 * t + ((k + 1) % 3)]
      const key = Math.min(i, j) * nv + Math.max(i, j)
      const list = edgeFaces.get(key)
      if (list) list.push(t)
      else edgeFaces.set(key, [t])
    }
  }
  const adj: number[] = []
  for (const list of edgeFaces.values()) if (list.length === 2) adj.push(list[0], list[1])
  return { normals, areas, adjacency: Uint32Array.from(adj) }
}

function angleBetween(n: Float64Array, a: number, b: number): number {
  const d = n[3 * a] * n[3 * b] + n[3 * a + 1] * n[3 * b + 1] + n[3 * a + 2] * n[3 * b + 2]
  return Math.acos(Math.max(-1, Math.min(1, d)))
}

/** each face's group (an index; faces of one group share their vertices) */
export function shadeGroups(m: TriMesh, fd: FaceData = faceData(m)): Int32Array {
  const nf = m.indices.length / 3
  const { normals, areas, adjacency } = fd
  // large flat regions first
  const flat = new Groups(nf)
  for (let e = 0; e < adjacency.length; e += 2) {
    if (Math.abs(Math.sin(angleBetween(normals, adjacency[e], adjacency[e + 1]))) < FACET_SIN) flat.join(adjacency[e], adjacency[e + 1])
  }
  const flatArea = new Map<number, number>()
  const flatSize = new Map<number, number>()
  for (let t = 0; t < nf; t++) {
    const r = flat.find(t)
    flatArea.set(r, (flatArea.get(r) ?? 0) + areas[t])
    flatSize.set(r, (flatSize.get(r) ?? 0) + 1)
  }
  let total = 0
  for (let t = 0; t < nf; t++) total += areas[t]
  const inFacet = new Uint8Array(nf)
  for (let t = 0; t < nf; t++) {
    const r = flat.find(t)
    if ((flatSize.get(r) ?? 0) >= 2 && (flatArea.get(r) ?? 0) > total / FACET_MIN_AREA) inFacet[t] = 1
  }
  // smooth surfaces among the rest
  const smooth = new Groups(nf)
  for (let e = 0; e < adjacency.length; e += 2) {
    const a = adjacency[e], b = adjacency[e + 1]
    if (inFacet[a] || inFacet[b]) continue
    if (angleBetween(normals, a, b) < SMOOTH) smooth.join(a, b)
  }
  const out = new Int32Array(nf)
  for (let t = 0; t < nf; t++) out[t] = inFacet[t] ? flat.find(t) : nf + smooth.find(t)
  return out
}

export function displayMesh(m: TriMesh): DisplayMesh {
  const p = m.positions, f = m.indices
  const nf = f.length / 3
  const fd = faceData(m)
  const groups = shadeGroups(m, fd)
  const copies = new Map<string, number>()
  const pos: number[] = []
  const nrm: number[] = []
  const idx = new Uint32Array(f.length)
  for (let t = 0; t < nf; t++) {
    for (let k = 0; k < 3; k++) {
      const v = f[3 * t + k]
      const key = `${v}:${groups[t]}`
      let c = copies.get(key)
      if (c === undefined) {
        c = pos.length / 3
        copies.set(key, c)
        pos.push(p[3 * v], p[3 * v + 1], p[3 * v + 2])
        nrm.push(0, 0, 0)
      }
      idx[3 * t + k] = c
      // the face's angle at this corner
      const a = 3 * v, b = 3 * f[3 * t + ((k + 1) % 3)], d = 3 * f[3 * t + ((k + 2) % 3)]
      const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2]
      const wx = p[d] - p[a], wy = p[d + 1] - p[a + 1], wz = p[d + 2] - p[a + 2]
      const lu = Math.hypot(ux, uy, uz), lw = Math.hypot(wx, wy, wz)
      const ang = lu > 0 && lw > 0 ? Math.acos(Math.max(-1, Math.min(1, (ux * wx + uy * wy + uz * wz) / (lu * lw)))) : 0
      nrm[3 * c] += fd.normals[3 * t] * ang
      nrm[3 * c + 1] += fd.normals[3 * t + 1] * ang
      nrm[3 * c + 2] += fd.normals[3 * t + 2] * ang
    }
  }
  for (let c = 0; c < nrm.length; c += 3) {
    const len = Math.hypot(nrm[c], nrm[c + 1], nrm[c + 2])
    if (len > 0) {
      nrm[c] /= len
      nrm[c + 1] /= len
      nrm[c + 2] /= len
    }
  }
  return { positions: Float32Array.from(pos), normals: Float32Array.from(nrm), indices: idx }
}
