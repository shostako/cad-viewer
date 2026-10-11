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

import { SAMPLE_BUDGET, bvhOfParts, chooseEdge, diagonalOf, subdivide, type Surface } from './compare.ts'

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
  /** the edge length the triangles were cut to */
  edge: number
}

/** each part's finer mesh with what each vertex is reached from along dir (a unit vector) */
export function reachOf(parts: Surface[], dir: readonly [number, number, number], budget = SAMPLE_BUDGET): Reach {
  const edge = chooseEdge(parts, parts, budget)
  const eps = Math.max(diagonalOf(parts) * 1e-5, 1e-9)
  const d = new Vector3(...dir).normalize()
  const back = d.clone().negate()
  const ray = new Ray()
  const out: ReachPart[] = []
  for (const part of parts) {
    const f = subdivide([part], edge)
    const n = f.positions.length / 3
    const reach = new Uint8Array(n)
    if (part.indices.length) {
      const bvh = bvhOfParts([part])
      for (let i = 0; i < n; i++) {
        ray.origin.set(
          f.positions[3 * i] + eps * f.normals[3 * i],
          f.positions[3 * i + 1] + eps * f.normals[3 * i + 1],
          f.positions[3 * i + 2] + eps * f.normals[3 * i + 2],
        )
        ray.direction.copy(d)
        let r = bvh.raycastFirst(ray, DoubleSide) ? 0 : UP
        ray.direction.copy(back)
        if (!bvh.raycastFirst(ray, DoubleSide)) r |= DOWN
        reach[i] = r
      }
    }
    out.push({ ...f, reach })
  }
  return { parts: out, edge }
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
