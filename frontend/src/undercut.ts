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

import { SAMPLE_BUDGET, bvhOfParts, diagonalOf, partEdges, placesOf, subdivide, type Place, type Surface } from './compare.ts'

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

/** a place of undercut candidates on one part (compare.ts placesOf) */
export type UndercutPlace = Place

/**
 * A part's undercut candidates as places, the largest first (compare.ts
 * placesOf: the candidate vertices joined by the finer triangles' edges and by
 * nearness; a place under half a finer triangle is not one)
 */
export function undercutPlaces(p: ReachPart, edge: number): UndercutPlace[] {
  return placesOf(p, (i) => p.reach[i] === 0, edge).sort((a, b) => b.area - a.area)
}
