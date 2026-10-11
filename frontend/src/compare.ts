/**
 * Comparing two versions of a part (docs/designs/compare.md): how far each
 * surface lies from the other's, and on which side.
 *
 * Both versions' display meshes are cut finer (subdivide: a triangle's edges
 * no longer than about 1/150 of the models' size), and at every vertex of the
 * finer mesh the nearest point of the other version is found (three-mesh-bvh).
 * The vertices of the display mesh alone are too few: a plane's vertices are
 * on its rim, so a filled hole (its wall's vertices on the other version's
 * top and bottom) would not show.
 *
 * The sign says whether the point is outside the other version (+) or inside
 * it (-): by the other's outward normals at the nearest point, each triangle
 * that has the nearest point weighted by its angle there (the angle-weighted
 * pseudonormal of Baerentzen and Aanaes, which is outward wherever the nearest
 * point lies: inside a triangle, on an edge, at a corner). The triangles are
 * found by where they are, not by shared vertices: the display mesh of a B-rep
 * repeats the vertices along each face's rim.
 *
 * Runs in a Worker (compareworker.ts) in both versions of the app; no backend.
 */
import { BufferAttribute, BufferGeometry, Triangle, Vector3 } from 'three'
import { MeshBVH } from 'three-mesh-bvh'

/** one part's display mesh */
export interface Surface {
  positions: ArrayLike<number>
  normals: ArrayLike<number>
  indices: ArrayLike<number>
}

/** a version's surface cut finer, with each vertex's signed distance to the other version */
export interface Sampled {
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
  /**
   * per vertex, mm: the distance to the other version's surface, + outside it,
   * - inside it (0 on it, to the last 1e-6 of the size)
   */
  offset: Float32Array
}

export interface Comparison {
  a: Sampled
  b: Sampled
  /** the longest edge length a part's triangles were cut to */
  edge: number
}

/** at most this many vertices of the finer mesh for each version (the edge grows to keep under it) */
export const SAMPLE_BUDGET = 600_000
/** the finer mesh's edge: the models' size over this */
export const EDGE_DIVISOR = 150

/** the diagonal of the box around both versions */
export function diagonalOf(...sides: Surface[][]): number {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
  for (const parts of sides) {
    for (const s of parts) {
      const p = s.positions
      for (let i = 0; i < p.length; i += 3) {
        for (let k = 0; k < 3; k++) {
          if (p[i + k] < lo[k]) lo[k] = p[i + k]
          if (p[i + k] > hi[k]) hi[k] = p[i + k]
        }
      }
    }
  }
  return lo[0] === Infinity ? 0 : Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
}

function edgeOf(p: ArrayLike<number>, i: number, j: number): number {
  return Math.hypot(p[3 * j] - p[3 * i], p[3 * j + 1] - p[3 * i + 1], p[3 * j + 2] - p[3 * i + 2])
}

/** how many pieces each triangle's edges are cut into for each part's edge length */
function cuts(parts: Surface[], L: readonly number[]): number[][] {
  return parts.map((s, pi) => {
    const out: number[] = []
    const ix = s.indices, p = s.positions
    for (let t = 0; t < ix.length; t += 3) {
      const e = Math.max(edgeOf(p, ix[t], ix[t + 1]), edgeOf(p, ix[t + 1], ix[t + 2]), edgeOf(p, ix[t + 2], ix[t]))
      out.push(Math.max(1, Math.ceil(e / L[pi])))
    }
    return out
  })
}

const gridVertices = (n: number) => ((n + 1) * (n + 2)) / 2

/** the finer mesh's vertices for these cuts: the parts' own, and each triangle's grid but its corners */
function finerVertices(parts: Surface[], ns: number[][]): number {
  let nv = 0
  parts.forEach((s, pi) => {
    nv += s.positions.length / 3
    for (const n of ns[pi]) nv += gridVertices(n) - 3
  })
  return nv
}

/**
 * Each part's edge length to cut it to: its own size over EDGE_DIVISOR (a
 * small part beside a large one, or far from it, keeps its own resolution:
 * Codex on #102), all longer by one factor when that would make more than
 * `budget` vertices for the parts together.
 */
export function partEdges(parts: Surface[], budget = SAMPLE_BUDGET): number[] {
  const L = parts.map((s) => {
    const d = diagonalOf([s])
    return d > 0 ? d / EDGE_DIVISOR : 1
  })
  for (let k = 0; k < 20; k++) {
    const count = finerVertices(parts, cuts(parts, L))
    if (count <= budget) return L
    const f = Math.sqrt(count / budget) * 1.05
    for (let i = 0; i < L.length; i++) L[i] *= f
  }
  return L
}

/** the smallest distance that is not zero, for a part (its size's 1e-6) */
export const tinyOf = (s: Surface): number => Math.max(diagonalOf([s]) * 1e-6, 1e-9)

/**
 * The parts' triangles cut into n x n smaller ones each (n from the longest
 * edge), as one mesh. The display mesh's own vertices are kept and shared as
 * before (a triangle short enough is not cut: its corners are all it has); the
 * points between them are each triangle's own (the rims of two triangles are
 * the same segment, cut alike or not: no gap in the surface). Normals are the
 * display normals blended across each triangle.
 */
export function subdivide(parts: Surface[], L: number | readonly number[]): Omit<Sampled, 'offset'> & { starts: number[] } {
  const ns = cuts(parts, typeof L === 'number' ? parts.map(() => L) : L)
  /** where each part's vertices start (they run together, a part after the other) */
  const starts: number[] = []
  const nv = finerVertices(parts, ns)
  let nt = 0
  for (const list of ns) for (const n of list) nt += n * n
  const positions = new Float32Array(3 * nv)
  const normals = new Float32Array(3 * nv)
  const indices = new Uint32Array(3 * nt)
  let v = 0, t = 0
  const put = (x: number, y: number, z: number, nx: number, ny: number, nz: number) => {
    positions[3 * v] = x
    positions[3 * v + 1] = y
    positions[3 * v + 2] = z
    const l = Math.hypot(nx, ny, nz) || 1
    normals[3 * v] = nx / l
    normals[3 * v + 1] = ny / l
    normals[3 * v + 2] = nz / l
    return v++
  }
  parts.forEach((s, pi) => {
    const ix = s.indices, P = s.positions, N = s.normals
    // the part's own vertices first, at base + their index
    const base = v
    starts.push(v)
    for (let i = 0; i < P.length / 3; i++) put(P[3 * i], P[3 * i + 1], P[3 * i + 2], N[3 * i], N[3 * i + 1], N[3 * i + 2])
    ns[pi].forEach((n, k) => {
      const a = ix[3 * k], b = ix[3 * k + 1], c = ix[3 * k + 2]
      // the grid: row i (0..n) along a->b, column j (0..n-i) along a->c; id[row[i] + j]
      const id = new Uint32Array(gridVertices(n))
      const row: number[] = []
      let g = 0
      for (let i = 0; i <= n; i++) {
        row.push(g)
        for (let j = 0; j <= n - i; j++, g++) {
          if (i === 0 && j === 0) id[g] = base + a
          else if (i === n && j === 0) id[g] = base + b
          else if (i === 0 && j === n) id[g] = base + c
          else {
            const wb = i / n, wc = j / n, wa = 1 - wb - wc
            const at = (q: number) => wa * P[3 * a + q] + wb * P[3 * b + q] + wc * P[3 * c + q]
            const nm = (q: number) => wa * N[3 * a + q] + wb * N[3 * b + q] + wc * N[3 * c + q]
            id[g] = put(at(0), at(1), at(2), nm(0), nm(1), nm(2))
          }
        }
      }
      for (let i = 0; i < n; i++) {
        for (let j = 0; j < n - i; j++) {
          const p00 = id[row[i] + j], p10 = id[row[i + 1] + j], p01 = id[row[i] + j + 1]
          indices[t++] = p00
          indices[t++] = p10
          indices[t++] = p01
          if (j + 1 < n - i) {
            indices[t++] = p10
            indices[t++] = id[row[i + 1] + j + 1]
            indices[t++] = p01
          }
        }
      }
    })
  })
  return { positions, normals, indices, starts }
}

/** one BVH over all of a version's parts (their triangles in order) */
export function bvhOfParts(parts: Surface[]): MeshBVH {
  let nv = 0, nt = 0
  for (const s of parts) (nv += s.positions.length), (nt += s.indices.length)
  const pos = new Float32Array(nv)
  const ix = new Uint32Array(nt)
  let v = 0, t = 0
  for (const s of parts) {
    pos.set(s.positions, v)
    const off = v / 3
    for (let k = 0; k < s.indices.length; k++) ix[t + k] = s.indices[k] + off
    v += s.positions.length
    t += s.indices.length
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new BufferAttribute(pos, 3))
  g.setIndex(new BufferAttribute(ix, 1))
  return new MeshBVH(g, { indirect: true })
}

/**
 * The signed distance from each point to the surface in `bvh` (+ outside, -
 * inside, by the angle-weighted pseudonormal at the nearest point). `tiny`:
 * at or under it the point is on the surface (0, no side asked).
 */
export function signedDistances(points: ArrayLike<number>, bvh: MeshBVH, tiny: number): Float32Array {
  const n = points.length / 3
  const out = new Float32Array(n)
  const p = new Vector3()
  const hit = { point: new Vector3(), distance: 0, faceIndex: 0 }
  const onTri = new Vector3()
  const normal = new Vector3()
  const pseudo = new Vector3()
  const v = new Vector3()
  const e1 = new Vector3(), e2 = new Vector3(), e3 = new Vector3()
  for (let i = 0; i < n; i++) {
    p.set(points[3 * i], points[3 * i + 1], points[3 * i + 2])
    const got = bvh.closestPointToPoint(p, hit)
    if (!got) {
      out[i] = NaN
      continue
    }
    const d = hit.distance
    if (d <= tiny) continue // 0
    const c = hit.point
    v.subVectors(p, c)
    // every triangle with the same nearest point, its outward normal weighted
    // by its angle at that point: 2 pi inside it, pi on an edge, its corner's
    // angle at a corner
    pseudo.set(0, 0, 0)
    const reach = d + tiny
    bvh.shapecast({
      intersectsBounds: (box) => box.distanceToPoint(p) <= reach,
      intersectsTriangle: (t) => {
        t.closestPointToPoint(p, onTri)
        if (onTri.distanceTo(c) > tiny) return false
        t.getNormal(normal)
        pseudo.addScaledVector(normal, angleAt(t, c, tiny, e1, e2, e3))
        return false
      },
    })
    out[i] = v.dot(pseudo) >= 0 ? d : -d
  }
  return out
}

/** the angle of triangle t at point c on it: its corner's angle there, pi on an edge, 2 pi inside */
function angleAt(t: Triangle, c: Vector3, tiny: number, e1: Vector3, e2: Vector3, e3: Vector3): number {
  const corners: [Vector3, Vector3, Vector3][] = [
    [t.a, t.b, t.c],
    [t.b, t.c, t.a],
    [t.c, t.a, t.b],
  ]
  for (const [q, r, s] of corners) {
    if (q.distanceTo(c) <= tiny) {
      e1.subVectors(r, q)
      e2.subVectors(s, q)
      return e1.angleTo(e2)
    }
  }
  for (const [q, r] of corners) {
    // on the edge q-r: its distance from the line, along the edge's length
    e1.subVectors(r, q)
    e2.subVectors(c, q)
    const len = e1.length()
    if (len > 0 && e3.crossVectors(e2, e1).length() / len <= tiny) return Math.PI
  }
  return 2 * Math.PI
}

/**
 * a version's finer mesh measured against the other's surface, each part with
 * its own smallest distance (tinyOf: not the assembly's, Codex on #102)
 */
function measured(parts: Surface[], edges: number[], other: Surface[]): Sampled {
  const f = subdivide(parts, edges)
  const n = f.positions.length / 3
  const offset = new Float32Array(n)
  if (!other.some((s) => s.indices.length)) offset.fill(NaN)
  else {
    const bvh = bvhOfParts(other)
    parts.forEach((s, k) => {
      const from = f.starts[k], to = k + 1 < parts.length ? f.starts[k + 1] : n
      offset.set(signedDistances(f.positions.subarray(3 * from, 3 * to), bvh, tinyOf(s)), from)
    })
  }
  return { positions: f.positions, normals: f.normals, indices: f.indices, offset }
}

/** both versions cut finer and measured against each other */
export function compare(a: Surface[], b: Surface[], budget = SAMPLE_BUDGET): Comparison {
  const ea = partEdges(a, budget)
  const eb = partEdges(b, budget)
  return { a: measured(a, ea, b), b: measured(b, eb, a), edge: Math.max(0, ...ea, ...eb) }
}
