/**
 * The places a colour map points at, to go to from its legend (issue #47
 * item 7):
 *
 * - thinSpots: where the wall is thinner than the threshold (肉厚), the
 *   thinnest first. A place is a run of thin vertices joined by triangles and
 *   by nearness (on a grid of cells the threshold across: up to about twice
 *   the threshold apart). The two sides of a thin wall are different B-rep
 *   faces that share no vertex, but they are nearer than the threshold. With
 *   none thinner than the threshold, the one thinnest point.
 * - draftSpots: the faces of one draft class (勾配不足, 反対側), the largest
 *   first. A B-rep face is one place (only its triangles of that class count:
 *   a curved face can be partly short); a mesh-format part has no faces, so a
 *   run of triangles of the class joined by their corners is one place.
 *
 * Each place has a point on the surface (the marker), the outward normal there
 * (the view looks at it from outside, along -normal), its extent (framed) and
 * its value (the thickness in mm, the draft angle in degrees there).
 *
 * The draft classes are those of the colouring (draft.ts): a B-rep vertex by
 * its normal (a triangle counts for a class when one of its corners has it:
 * the class's colour shows in it), a mesh-format triangle by its winding.
 */
import { draftClass, draftSine, type DraftClass } from './draft'
import type { FaceRange } from './model'

type Vec3 = [number, number, number]

/** one visible part with faces, as the viewer draws it (world coordinates) */
export interface SpotPart {
  partId: number
  positions: ArrayLike<number>
  /** vertex normals; a mesh-format part's are averaged ones (smooth shading) */
  normals: ArrayLike<number>
  indices: ArrayLike<number>
  /** B-rep faces; empty for mesh formats */
  faceRanges: readonly FaceRange[]
  /** mesh formats: the winding sign of the part (draft.ts windingSign); asked for by draftSpots only */
  windingSign(): 1 | -1
}

export interface Spot {
  partId: number
  /** the B-rep face of a draft place (null: a thin place, or a mesh-format part) */
  faceId: number | null
  /** the marker's point, on the surface */
  at: Vec3
  /** the outward normal at `at` (unit) */
  normal: Vec3
  /** the place's extent */
  min: Vec3
  max: Vec3
  /** thickness (mm) of a thin place; the draft angle (degrees) at `at` of a draft place */
  value: number
  /** a draft place's area (its triangles of the class); 0 for a thin place */
  area: number
  /** a 厚肉 place: its largest sphere (inside the part; drawn while the place is gone to), and its diameter / the general wall */
  sphere?: { center: Vec3; radius: number }
  ratio?: number
}

/** union-find over n items */
class Joins {
  private readonly up: Int32Array
  constructor(n: number) {
    this.up = new Int32Array(n)
    for (let i = 0; i < n; i++) this.up[i] = i
  }
  find(i: number): number {
    let r = i
    while (this.up[r] !== r) r = this.up[r]
    while (this.up[i] !== r) {
      const next = this.up[i]
      this.up[i] = r
      i = next
    }
    return r
  }
  join(a: number, b: number): void {
    const ra = this.find(a)
    const rb = this.find(b)
    if (ra !== rb) this.up[Math.max(ra, rb)] = Math.min(ra, rb)
  }
}

/**
 * For each vertex, the first vertex at exactly the same point. The
 * tessellation gives the faces on both sides of an edge the same points
 * along it (one polygon per edge), so equal is the test.
 */
function samePoint(positions: ArrayLike<number>): Int32Array {
  const n = Math.floor(positions.length / 3)
  const first = new Map<string, number>()
  const out = new Int32Array(n)
  for (let i = 0; i < n; i++) {
    const key = `${positions[i * 3]},${positions[i * 3 + 1]},${positions[i * 3 + 2]}`
    const f = first.get(key)
    if (f === undefined) {
      first.set(key, i)
      out[i] = i
    } else out[i] = f
  }
  return out
}

/**
 * Join the thin vertices that are near each other: on a grid of cells the
 * threshold across, each thin vertex joins the first thin vertex of its cell
 * and of the 26 cells around it (so points up to about two cells apart join:
 * both sides of a thin wall, and thin spots closer than that).
 */
function joinNear(P: ArrayLike<number>, n: number, thin: (i: number) => boolean, cell: number, joins: Joins): void {
  if (!(cell > 0)) return
  const first = new Map<string, number>()
  const key = (x: number, y: number, z: number) => `${x},${y},${z}`
  const cellOf = (i: number): Vec3 => [Math.floor(P[i * 3] / cell), Math.floor(P[i * 3 + 1] / cell), Math.floor(P[i * 3 + 2] / cell)]
  for (let i = 0; i < n; i++) {
    if (!thin(i)) continue
    const [x, y, z] = cellOf(i)
    const k = key(x, y, z)
    if (!first.has(k)) first.set(k, i)
  }
  for (let i = 0; i < n; i++) {
    if (!thin(i)) continue
    const [x, y, z] = cellOf(i)
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        for (let dz = -1; dz <= 1; dz++) {
          const f = first.get(key(x + dx, y + dy, z + dz))
          if (f !== undefined) joins.join(i, f)
        }
  }
}

function unit(x: number, y: number, z: number): Vec3 {
  const l = Math.hypot(x, y, z)
  return l > 0 ? [x / l, y / l, z / l] : [0, 0, 1]
}

function point(p: ArrayLike<number>, i: number): Vec3 {
  return [p[i * 3], p[i * 3 + 1], p[i * 3 + 2]]
}

/** grow the box [min, max] by the point */
function grow(min: Vec3, max: Vec3, x: number, y: number, z: number): void {
  if (x < min[0]) min[0] = x
  if (y < min[1]) min[1] = y
  if (z < min[2]) min[2] = z
  if (x > max[0]) max[0] = x
  if (y > max[1]) max[1] = y
  if (z > max[2]) max[2] = z
}

/**
 * The places thinner than `threshold`, the thinnest first; with none, the
 * thinnest point (if any vertex has a value). `values` are the heatmap's
 * thickness per vertex and part (no value: not > 0).
 */
export function thinSpots(parts: readonly SpotPart[], values: ReadonlyMap<number, ArrayLike<number>>, threshold: number): Spot[] {
  const spots: Spot[] = []
  let thinnest: Spot | null = null
  for (const part of parts) {
    const v = values.get(part.partId)
    if (!v) continue
    const P = part.positions
    const n = Math.min(Math.floor(P.length / 3), v.length)
    const thin = (i: number): boolean => i < n && v[i] > 0 && v[i] < threshold
    for (let i = 0; i < n; i++) {
      if (v[i] > 0 && (!thinnest || v[i] < thinnest.value)) {
        const at = point(P, i)
        thinnest = {
          partId: part.partId,
          faceId: null,
          at,
          normal: unit(part.normals[i * 3], part.normals[i * 3 + 1], part.normals[i * 3 + 2]),
          min: [...at],
          max: [...at],
          value: v[i],
          area: 0,
        }
      }
    }
    const joins = new Joins(n)
    const I = part.indices
    for (let t = 0; t + 2 < I.length; t += 3) {
      const a = I[t]
      const b = I[t + 1]
      const c = I[t + 2]
      if (thin(a) && thin(b)) joins.join(a, b)
      if (thin(b) && thin(c)) joins.join(b, c)
      if (thin(a) && thin(c)) joins.join(a, c)
    }
    joinNear(P, n, thin, threshold, joins)
    const byRoot = new Map<number, Spot>()
    for (let i = 0; i < n; i++) {
      if (!thin(i)) continue
      const r = joins.find(i)
      const s = byRoot.get(r)
      const x = P[i * 3]
      const y = P[i * 3 + 1]
      const z = P[i * 3 + 2]
      if (!s) {
        byRoot.set(r, {
          partId: part.partId,
          faceId: null,
          at: [x, y, z],
          normal: unit(part.normals[i * 3], part.normals[i * 3 + 1], part.normals[i * 3 + 2]),
          min: [x, y, z],
          max: [x, y, z],
          value: v[i],
          area: 0,
        })
        continue
      }
      grow(s.min, s.max, x, y, z)
      if (v[i] < s.value) {
        s.value = v[i]
        s.at = [x, y, z]
        s.normal = unit(part.normals[i * 3], part.normals[i * 3 + 1], part.normals[i * 3 + 2])
      }
    }
    spots.push(...byRoot.values())
  }
  if (!spots.length) return thinnest ? [thinnest] : []
  // the thinnest first; equal ones in the order of the parts and vertices
  return spots.sort((a, b) => a.value - b.value)
}

/** a triangle of a place: its area, and where the marker would go on it */
interface Tri {
  area: number
  /** all of it has the class (B-rep: all three corners; a mesh-format triangle always) */
  full: boolean
  at: Vec3
  normal: Vec3
  /** sine of the draft angle at `at` */
  sine: number
}

/**
 * The class of each vertex of a B-rep part, by its display normal: what
 * draftColors paints it.
 */
function vertexClasses(part: SpotPart, dir: readonly [number, number, number], sinRequired: number): DraftClass[] {
  const N = part.normals
  const n = Math.floor(part.positions.length / 3)
  const out: DraftClass[] = new Array(n)
  for (let i = 0; i < n; i++) out[i] = draftClass(draftSine(N[i * 3], N[i * 3 + 1], N[i * 3 + 2], dir), sinRequired)
  return out
}

function area(P: ArrayLike<number>, a: number, b: number, c: number): { area: number; cross: Vec3 } {
  const ux = P[b] - P[a]
  const uy = P[b + 1] - P[a + 1]
  const uz = P[b + 2] - P[a + 2]
  const vx = P[c] - P[a]
  const vy = P[c + 1] - P[a + 1]
  const vz = P[c + 2] - P[a + 2]
  const cross: Vec3 = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]
  return { area: Math.hypot(...cross) / 2, cross }
}

/**
 * Triangle t of a B-rep part, if one of its corners has the class (the class's
 * colour shows in it): the marker goes in its middle, along its corners' mean
 * normal, when all three have the class; else on a corner that has it.
 */
function brepTriangle(part: SpotPart, t: number, cls: DraftClass, vcls: DraftClass[], dir: readonly [number, number, number]): Tri | null {
  const I = part.indices
  const v = [I[t * 3], I[t * 3 + 1], I[t * 3 + 2]]
  const of = v.map((i) => vcls[i] === cls)
  if (!of.some(Boolean)) return null
  const P = part.positions
  const N = part.normals
  const [a, b, c] = v.map((i) => i * 3)
  const full = of.every(Boolean)
  let at: Vec3
  let normal: Vec3
  if (full) {
    at = [(P[a] + P[b] + P[c]) / 3, (P[a + 1] + P[b + 1] + P[c + 1]) / 3, (P[a + 2] + P[b + 2] + P[c + 2]) / 3]
    normal = unit(N[a] + N[b] + N[c], N[a + 1] + N[b + 1] + N[c + 1], N[a + 2] + N[b + 2] + N[c + 2])
  } else {
    const k = v[of.indexOf(true)] * 3
    at = [P[k], P[k + 1], P[k + 2]]
    normal = unit(N[k], N[k + 1], N[k + 2])
  }
  return { area: area(P, a, b, c).area, full, at, normal, sine: draftSine(normal[0], normal[1], normal[2], dir) }
}

/** triangle t of a mesh-format part, if it has the class (by its winding, as draftColorsFlat paints it) */
function meshTriangle(
  part: SpotPart,
  t: number,
  cls: DraftClass,
  sign: 1 | -1,
  dir: readonly [number, number, number],
  sinRequired: number,
): Tri | null {
  const I = part.indices
  const P = part.positions
  const [a, b, c] = [I[t * 3] * 3, I[t * 3 + 1] * 3, I[t * 3 + 2] * 3]
  const { area: ar, cross } = area(P, a, b, c)
  const normal = unit(cross[0] * sign, cross[1] * sign, cross[2] * sign)
  const sine = draftSine(normal[0], normal[1], normal[2], dir)
  if (draftClass(sine, sinRequired) !== cls) return null
  const at: Vec3 = [(P[a] + P[b] + P[c]) / 3, (P[a + 1] + P[b + 1] + P[c + 1]) / 3, (P[a + 2] + P[b + 2] + P[c + 2]) / 3]
  return { area: ar, full: true, at, normal, sine }
}

/** a place being collected: its box, area, and the triangle the marker goes on */
interface Gather {
  partId: number
  faceId: number | null
  min: Vec3
  max: Vec3
  area: number
  best: Tri | null
}

function gather(g: Gather, part: SpotPart, t: number, tri: Tri): void {
  const P = part.positions
  const I = part.indices
  for (let k = 0; k < 3; k++) {
    const i = I[t * 3 + k] * 3
    grow(g.min, g.max, P[i], P[i + 1], P[i + 2])
  }
  g.area += tri.area
  // the marker on the largest triangle that is all of the class (else the largest one)
  const b = g.best
  if (!b || (tri.full && !b.full) || (tri.full === b.full && tri.area > b.area)) g.best = tri
}

function newGather(partId: number, faceId: number | null): Gather {
  return { partId, faceId, min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity], area: 0, best: null }
}

function toSpot(g: Gather): Spot {
  const b = g.best!
  return {
    partId: g.partId,
    faceId: g.faceId,
    at: b.at,
    normal: b.normal,
    min: g.min,
    max: g.max,
    value: (Math.asin(Math.max(-1, Math.min(1, b.sine))) * 180) / Math.PI,
    area: g.area,
  }
}

/**
 * The places of draft class `cls` for the pull direction `dir` (unit) and the
 * required angle, the largest first.
 */
export function draftSpots(
  parts: readonly SpotPart[],
  dir: readonly [number, number, number],
  requiredDeg: number,
  cls: DraftClass,
): Spot[] {
  const sinRequired = Math.sin((requiredDeg * Math.PI) / 180)
  const out: Spot[] = []
  for (const part of parts) {
    const nTri = Math.floor(part.indices.length / 3)
    if (part.faceRanges.length) {
      const vcls = vertexClasses(part, dir, sinRequired)
      for (const f of part.faceRanges) {
        const g = newGather(part.partId, f.faceId)
        for (let t = f.triStart; t < Math.min(f.triStart + f.triCount, nTri); t++) {
          const tri = brepTriangle(part, t, cls, vcls, dir)
          if (tri) gather(g, part, t, tri)
        }
        if (g.best) out.push(toSpot(g))
      }
      continue
    }
    // a mesh-format part: runs of triangles of the class joined by their corners
    const sign = part.windingSign()
    const tris: (Tri | null)[] = []
    for (let t = 0; t < nTri; t++) tris.push(meshTriangle(part, t, cls, sign, dir, sinRequired))
    const same = samePoint(part.positions)
    const joins = new Joins(Math.floor(part.positions.length / 3))
    const I = part.indices
    for (let t = 0; t < nTri; t++) {
      if (!tris[t]) continue
      const a = same[I[t * 3]]
      joins.join(a, same[I[t * 3 + 1]])
      joins.join(a, same[I[t * 3 + 2]])
    }
    const byRoot = new Map<number, Gather>()
    for (let t = 0; t < nTri; t++) {
      const tri = tris[t]
      if (!tri) continue
      const r = joins.find(same[I[t * 3]])
      let g = byRoot.get(r)
      if (!g) byRoot.set(r, (g = newGather(part.partId, null)))
      gather(g, part, t, tri)
    }
    for (const g of byRoot.values()) out.push(toSpot(g))
  }
  return out.sort((a, b) => b.area - a.area)
}

/**
 * What a spot's marker says: the thickness as under the cursor (「0.82 mm」),
 * the draft angle as under the cursor without its class (「勾配 −2.0°」: a real
 * minus sign, none on a value that rounds to 0; draft.ts draftTipText).
 */
export function spotText(kind: 'thin' | 'thick' | 'undercut' | DraftClass, s: Spot): string {
  if (kind === 'thin') return `${s.value.toFixed(2)} mm`
  if (kind === 'undercut') return `${s.area.toFixed(1)} mm²`
  if (kind === 'thick') return `⌀${s.value.toFixed(2)} mm（一般部の ${(s.ratio ?? 0).toFixed(1)} 倍）`
  const value = Math.abs(s.value).toFixed(1)
  const sign = s.value < 0 && value !== '0.0' ? '−' : ''
  return `勾配 ${sign}${value}°`
}
