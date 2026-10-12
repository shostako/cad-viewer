/**
 * アンダーカットの候補 (docs/designs/undercut.md): where a straight pull of two
 * mold halves along d cannot reach the part's surface.
 *
 * Each part's display mesh is cut finer (compare.ts subdivide: a shadow often
 * falls across part of a face, the floor under an overhang), and from every
 * vertex a ray goes up (+d) and one down (-d), from a little off the surface
 * along its normal. A ray that leaves without meeting the part again means
 * that half of the mold can reach the point. Neither: an undercut candidate
 * (a slide, a lifter, or a forced release). The other parts do not block: each
 * is molded in its own mold.
 *
 * Runs in a Worker (undercutworker.ts) in both versions of the app; no backend.
 */
import { DoubleSide, Ray, Vector3 } from 'three'

import { SAMPLE_BUDGET, bvhOfParts, diagonalOf, partEdges, subdivide, type Surface } from './compare.ts'

/** a vertex the upper half (along +d) reaches */
export const UP = 1
/** a vertex the lower half (along -d) reaches */
export const DOWN = 2

export interface ReachPart {
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
  /** per vertex: UP | DOWN bits; 0 is an undercut candidate */
  reach: Uint8Array
}

export interface Reach {
  parts: ReachPart[]
  /** the edge length each part's triangles were cut to */
  edges: number[]
}

/** each part's finer mesh with what each vertex is reached from along dir (a unit vector) */
export function reachOf(parts: Surface[], dir: readonly [number, number, number], budget = SAMPLE_BUDGET): Reach {
  // each part at its own resolution, and off its surface by its own size's
  // 1e-5: a large part beside a small one sets neither (Codex on #102)
  const edges = partEdges(parts, budget)
  const d = new Vector3(...dir).normalize()
  const back = d.clone().negate()
  const ray = new Ray()
  const out: ReachPart[] = []
  parts.forEach((part, k) => {
    const eps = Math.max(diagonalOf([part]) * 1e-5, 1e-9)
    const f = subdivide([part], edges[k])
    const n = f.positions.length / 3
    const reach = new Uint8Array(n)
    if (part.indices.length) {
      const bvh = bvhOfParts([part])
      const into = inward(f.positions, f.indices)
      for (let i = 0; i < n; i++) {
        // off the surface along the normal, and into its face along it by a quarter
        // of that. A point on a rim or at a corner is moved off it: there a ray along
        // the pull runs along a border, and meets what is beside it at once (a wall's
        // foot is in the plane of the floor it stands on; the pocket's corner at its
        // floor saw the opening's edge): #102 counted the inner edges as undercuts.
        // A quarter, so that the point stays outside its face however `into` points
        // (at a vertex shared by faces that turn, a box's corner indexed as one, the
        // middle of the triangles around it is inside the solid: Codex on #106) and
        // however far the normal leans from the face (to 75°: cos > 1/4)
        ray.origin.set(
          f.positions[3 * i] + eps * (f.normals[3 * i] + 0.25 * into[3 * i]),
          f.positions[3 * i + 1] + eps * (f.normals[3 * i + 1] + 0.25 * into[3 * i + 1]),
          f.positions[3 * i + 2] + eps * (f.normals[3 * i + 2] + 0.25 * into[3 * i + 2]),
        )
        ray.direction.copy(d)
        let r = bvh.raycastFirst(ray, DoubleSide) ? 0 : UP
        ray.direction.copy(back)
        if (!bvh.raycastFirst(ray, DoubleSide)) r |= DOWN
        reach[i] = r
      }
    }
    out.push({ positions: f.positions, normals: f.normals, indices: f.indices, reach })
  })
  return { parts: out, edges }
}

/**
 * Per vertex, the unit direction into its face: to the middle of the
 * triangles around it (inside a face they balance out, to rounding: the
 * direction there is of no account, a quarter of the offset, see reachOf)
 */
function inward(P: Float32Array, ix: Uint32Array): Float32Array {
  const n = P.length / 3
  const sum = new Float64Array(3 * n)
  const count = new Uint32Array(n)
  for (let t = 0; t < ix.length; t += 3) {
    const [a, b, c] = [ix[t], ix[t + 1], ix[t + 2]]
    for (const v of [a, b, c]) {
      for (let k = 0; k < 3; k++) sum[3 * v + k] += (P[3 * a + k] + P[3 * b + k] + P[3 * c + k]) / 3
      count[v]++
    }
  }
  const out = new Float32Array(3 * n)
  for (let v = 0; v < n; v++) {
    if (!count[v]) continue
    const x = sum[3 * v] / count[v] - P[3 * v], y = sum[3 * v + 1] / count[v] - P[3 * v + 1], z = sum[3 * v + 2] / count[v] - P[3 * v + 2]
    const l = Math.hypot(x, y, z)
    if (l > 0) {
      out[3 * v] = x / l
      out[3 * v + 1] = y / l
      out[3 * v + 2] = z / l
    }
  }
  return out
}

/** the area of a part's undercut candidates: each finer triangle by the share of its vertices that are (mm²) */
export function undercutArea(p: ReachPart): number {
  let area = 0
  const P = p.positions, ix = p.indices
  for (let t = 0; t < ix.length; t += 3) {
    const [a, b, c] = [ix[t], ix[t + 1], ix[t + 2]]
    const k = (p.reach[a] === 0 ? 1 : 0) + (p.reach[b] === 0 ? 1 : 0) + (p.reach[c] === 0 ? 1 : 0)
    if (!k) continue
    const ux = P[3 * b] - P[3 * a], uy = P[3 * b + 1] - P[3 * a + 1], uz = P[3 * b + 2] - P[3 * a + 2]
    const vx = P[3 * c] - P[3 * a], vy = P[3 * c + 1] - P[3 * a + 1], vz = P[3 * c + 2] - P[3 * a + 2]
    area += (Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) / 2) * (k / 3)
  }
  return area
}

/** a place of undercut candidates on one part (spots.ts Spot's fields) */
export interface UndercutPlace {
  /** the candidate vertex nearest the place's middle (the marker), and its normal */
  at: [number, number, number]
  normal: [number, number, number]
  min: [number, number, number]
  max: [number, number, number]
  /** mm²: the finer triangles by the share of their corners that are candidates */
  area: number
}

/**
 * A part's undercut candidates as places, the largest first: the candidate
 * vertices joined by the finer triangles' edges, and by nearness (closer than
 * the finer mesh's edge `edge`: the rims of two display triangles are cut into
 * points of their own, apart by less than that). A place smaller than one
 * finer triangle (edge² / 2) is a point where the classes meet, not a place.
 */
export function undercutPlaces(p: ReachPart, edge: number): UndercutPlace[] {
  const n = p.reach.length
  const P = p.positions
  const up = new Int32Array(n).fill(-1)
  const find = (i: number): number => {
    let r = i
    while (up[r] !== r) r = up[r]
    while (up[i] !== r) {
      const next = up[i]
      up[i] = r
      i = next
    }
    return r
  }
  const join = (a: number, b: number) => {
    const ra = find(a), rb = find(b)
    if (ra !== rb) up[ra] = rb
  }
  for (let i = 0; i < n; i++) if (p.reach[i] === 0) up[i] = i
  const ix = p.indices
  for (let t = 0; t < ix.length; t += 3) {
    for (const [a, b] of [[ix[t], ix[t + 1]], [ix[t + 1], ix[t + 2]], [ix[t + 2], ix[t]]]) if (up[a] >= 0 && up[b] >= 0) join(a, b)
  }
  // nearness: a grid of cells `edge` across; a point and those of the cells around it
  const reach = edge * 1.01
  const cell = (v: number) => Math.floor(v / reach)
  const cells = new Map<string, number[]>()
  for (let i = 0; i < n; i++) {
    if (up[i] < 0) continue
    const key = `${cell(P[3 * i])},${cell(P[3 * i + 1])},${cell(P[3 * i + 2])}`
    const list = cells.get(key)
    if (list) list.push(i)
    else cells.set(key, [i])
  }
  for (let i = 0; i < n; i++) {
    if (up[i] < 0) continue
    const cx = cell(P[3 * i]), cy = cell(P[3 * i + 1]), cz = cell(P[3 * i + 2])
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        for (let dz = -1; dz <= 1; dz++) {
          for (const j of cells.get(`${cx + dx},${cy + dy},${cz + dz}`) ?? []) {
            if (j <= i) continue
            const d = Math.hypot(P[3 * j] - P[3 * i], P[3 * j + 1] - P[3 * i + 1], P[3 * j + 2] - P[3 * i + 2])
            if (d <= reach) join(i, j)
          }
        }
  }
  // each place's area and its middle (area-weighted)
  const area = new Map<number, number>()
  const mid = new Map<number, [number, number, number]>()
  for (let t = 0; t < ix.length; t += 3) {
    const tri = [ix[t], ix[t + 1], ix[t + 2]]
    const zero = tri.filter((v) => up[v] >= 0)
    if (!zero.length) continue
    const [a, b, c] = tri
    const ux = P[3 * b] - P[3 * a], uy = P[3 * b + 1] - P[3 * a + 1], uz = P[3 * b + 2] - P[3 * a + 2]
    const vx = P[3 * c] - P[3 * a], vy = P[3 * c + 1] - P[3 * a + 1], vz = P[3 * c + 2] - P[3 * a + 2]
    const w = (Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) / 2) * (zero.length / 3)
    const r = find(zero[0])
    area.set(r, (area.get(r) ?? 0) + w)
    const m = mid.get(r) ?? [0, 0, 0]
    for (let k = 0; k < 3; k++) m[k] += (w * (P[3 * a + k] + P[3 * b + k] + P[3 * c + k])) / 3
    mid.set(r, m)
  }
  const places = new Map<number, UndercutPlace & { best: number }>()
  for (let i = 0; i < n; i++) {
    if (up[i] < 0) continue
    const r = find(i)
    const a = area.get(r) ?? 0
    if (!(a > 0)) continue
    const m = mid.get(r)!
    const c: [number, number, number] = [m[0] / a, m[1] / a, m[2] / a]
    const at: [number, number, number] = [P[3 * i], P[3 * i + 1], P[3 * i + 2]]
    const d = Math.hypot(at[0] - c[0], at[1] - c[1], at[2] - c[2])
    let place = places.get(r)
    if (!place) {
      place = { at, normal: [p.normals[3 * i], p.normals[3 * i + 1], p.normals[3 * i + 2]], min: [...at], max: [...at], area: a, best: d }
      places.set(r, place)
    } else if (d < place.best) {
      place.at = at
      place.normal = [p.normals[3 * i], p.normals[3 * i + 1], p.normals[3 * i + 2]]
      place.best = d
    }
    for (let k = 0; k < 3; k++) {
      place.min[k] = Math.min(place.min[k], at[k])
      place.max[k] = Math.max(place.max[k], at[k])
    }
  }
  return [...places.values()]
    .filter((q) => q.area >= (edge * edge) / 2)
    .map(({ best: _best, ...q }) => q)
    .sort((a, b) => b.area - a.area)
}
