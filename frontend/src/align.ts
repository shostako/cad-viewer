/**
 * 位置合わせ for 版の比較 (docs/designs/align.md): the compared version moved
 * onto the open one by datums picked on both, in the order of precedence they
 * were picked in (3-2-1, as a drawing's datums A|B|C).
 *
 * The turn first: the datums' directions (a plane's normal, an axis's
 * direction), then the directions from the first datum with a place (an axis,
 * a circle, a point) to the later ones. The first direction is matched
 * exactly, the first one not along it sets the turn about it (as frame.ts
 * makes a frame's X square to Z). Then the move: each datum in turn takes the
 * directions not yet fixed (a plane its normal, an axis the two square to it,
 * a circle or a point all three). What the datums leave free keeps the
 * compared version's centre where it is.
 *
 * Pure (no three.js, no DOM): the unit tests run it in Node.
 */

export type Xyz = [number, number, number]

/** what a datum is: a plane, an axis (a line), a circle (a centre on an axis), a point */
export type DatumKind = 'plane' | 'axis' | 'circle' | 'point'

export interface Datum {
  kind: DatumKind
  /** a plane: a point of it; an axis: a point of the line; a circle: its centre; a point: it */
  at: Xyz
  /** a plane: its normal out of the solid (it has a sign); an axis, a circle: its direction (no sign) */
  dir?: Xyz
  /** where it was clicked (its marker; a plane's misfit is measured there) */
  mark: Xyz
}

/** the same datum on the open version and on the compared one */
export interface DatumPair {
  open: Datum
  other: Datum
}

/** x -> r x + t (r row-major) */
export interface Motion {
  r: number[]
  t: Xyz
}

export interface Alignment {
  motion: Motion
  /** of the 3 turns and the 3 moves, how many the datums fixed (the rest keep the compared version's centre) */
  fixed: { turn: number; move: number }
  /** each pair after the motion: how far apart (mm) and at what angle (degrees) */
  misfit: { distance: number; angle: number }[]
}

/** the names the screen gives the kinds */
export const DATUM_NAMES: Record<DatumKind, string> = { plane: '平面', axis: '軸', circle: '円', point: '点' }

/** directions closer to each other than this (the sine of the angle) are along each other */
const PARALLEL_SIN = 1e-6

const dot = (a: Xyz, b: Xyz) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: Xyz, b: Xyz): Xyz => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const sub = (a: Xyz, b: Xyz): Xyz => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const add = (a: Xyz, b: Xyz): Xyz => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const scale = (a: Xyz, k: number): Xyz => [a[0] * k, a[1] * k, a[2] * k]
const norm = (a: Xyz) => Math.hypot(a[0], a[1], a[2])
const unit = (a: Xyz): Xyz => scale(a, 1 / norm(a))
const IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1]

/** r a */
export function turn(r: readonly number[], a: Xyz): Xyz {
  return [r[0] * a[0] + r[1] * a[1] + r[2] * a[2], r[3] * a[0] + r[4] * a[1] + r[5] * a[2], r[6] * a[0] + r[7] * a[1] + r[8] * a[2]]
}

/** the motion's image of a point */
export const moveBy = (m: Motion, a: Xyz): Xyz => add(turn(m.r, a), m.t)

/** a's part square to the unit vectors `along` (taken in turn, made square to each other first) */
function squareTo(a: Xyz, along: Xyz[]): Xyz {
  const basis: Xyz[] = []
  for (const d of along) {
    let e = d
    for (const b of basis) e = sub(e, scale(b, dot(e, b)))
    if (norm(e) > PARALLEL_SIN) basis.push(unit(e))
  }
  let out = a
  for (const b of basis) out = sub(out, scale(b, dot(out, b)))
  return out
}

/** the frame (columns x, y, z) with z along `z` and x the part of `x` square to it */
function frameOf(z: Xyz, x: Xyz): number[] {
  const zu = unit(z)
  const xu = unit(sub(x, scale(zu, dot(x, zu))))
  const yu = cross(zu, xu)
  // row-major, the columns x, y, z
  return [xu[0], yu[0], zu[0], xu[1], yu[1], zu[1], xu[2], yu[2], zu[2]]
}

/** a b (3 x 3, row-major) */
function mul(a: readonly number[], b: readonly number[]): number[] {
  const out = new Array<number>(9)
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[3 * i + j] = a[3 * i] * b[j] + a[3 * i + 1] * b[3 + j] + a[3 * i + 2] * b[6 + j]
  return out
}

const transpose = (a: readonly number[]) => [a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8]]

/** the smallest turn taking the unit vector a to the unit vector b */
function smallestTurn(a: Xyz, b: Xyz): number[] {
  const c = dot(a, b)
  const k = cross(a, b)
  if (c < -1 + 1e-12) {
    // half a turn, about a line square to a (any: none is nearer than another)
    const e: Xyz = Math.abs(a[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]
    const n = unit(squareTo(e, [a]))
    return [2 * n[0] * n[0] - 1, 2 * n[0] * n[1], 2 * n[0] * n[2], 2 * n[1] * n[0], 2 * n[1] * n[1] - 1, 2 * n[1] * n[2], 2 * n[2] * n[0], 2 * n[2] * n[1], 2 * n[2] * n[2] - 1]
  }
  // Rodrigues: I + [k]x + [k]x^2 / (1 + c)
  const f = 1 / (1 + c)
  const [x, y, z] = k
  return [
    1 - f * (y * y + z * z), -z + f * x * y, y + f * x * z,
    z + f * x * y, 1 - f * (x * x + z * z), -x + f * y * z,
    -y + f * x * z, x + f * y * z, 1 - f * (x * x + y * y),
  ]
}

/** a direction to match: u on the compared version, v on the open one; an axis's has no sign */
interface Direction {
  u: Xyz
  v: Xyz
  signed: boolean
}

const hasPlace = (d: Datum) => d.kind !== 'plane'

/** the pairs' directions, in their order of precedence (the module's comment) */
function directionsOf(pairs: DatumPair[]): Direction[] {
  const out: Direction[] = []
  for (const p of pairs) {
    if (p.open.dir && p.other.dir) out.push({ u: unit(p.other.dir), v: unit(p.open.dir), signed: p.open.kind === 'plane' })
  }
  const placed = pairs.filter((p) => hasPlace(p.open))
  if (placed.length > 1) {
    const first = placed[0]
    const lines = (d: Datum, e: Datum) => [d, e].filter((x) => x.kind === 'axis' && x.dir).map((x) => unit(x.dir!))
    for (const p of placed.slice(1)) {
      // along an axis a datum has no place: what is left is the way from one to the other
      const u = squareTo(sub(p.other.at, first.other.at), lines(first.other, p.other))
      const v = squareTo(sub(p.open.at, first.open.at), lines(first.open, p.open))
      const size = Math.max(1, ...p.open.at.map(Math.abs), ...first.open.at.map(Math.abs))
      if (norm(u) > 1e-9 * size && norm(v) > 1e-9 * size) out.push({ u: unit(u), v: unit(v), signed: true })
    }
  }
  return out
}

const along = (a: Xyz, b: Xyz) => norm(cross(a, b)) <= PARALLEL_SIN

/** the turn the directions set (the module's comment), and how many of the 3 turns they fixed */
function turnOf(dirs: Direction[]): { r: number[]; fixed: number } {
  if (!dirs.length) return { r: [...IDENTITY], fixed: 0 }
  const p = dirs[0]
  const s = dirs.slice(1).find((d) => !along(d.u, p.u) && !along(d.v, p.v))
  // an axis's direction has no sign: the smaller turn of the ones it allows
  let best: number[] | null = null
  for (const sp of p.signed ? [1] : [1, -1]) {
    for (const ss of !s || s.signed ? [1] : [1, -1]) {
      const r = s ? mul(frameOf(p.v, s.v), transpose(frameOf(scale(p.u, sp), scale(s.u, ss)))) : smallestTurn(scale(p.u, sp), p.v)
      if (!best || r[0] + r[4] + r[8] > best[0] + best[4] + best[8] + 1e-12) best = r
    }
  }
  return { r: best!, fixed: s ? 3 : 2 }
}

/** the directions a datum's place fixes (unit vectors), on the open version */
function rowsOf(d: Datum): Xyz[] {
  if (d.kind === 'plane') return [unit(d.dir!)]
  if (d.kind === 'axis') {
    const a = unit(d.dir!)
    const e1 = unit(squareTo(Math.abs(a[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0], [a]))
    return [e1, cross(a, e1)]
  }
  return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
}

/**
 * The motion of the compared version that puts its datums on the open
 * version's, in the order of precedence (the module's comment). `centre`: the
 * compared version's centre, which what the datums leave free keeps in place.
 */
export function align(pairs: DatumPair[], centre: Xyz): Alignment {
  for (const p of pairs) {
    if (p.open.kind !== p.other.kind) throw new Error(`基準の種類が違う（${DATUM_NAMES[p.open.kind]}と${DATUM_NAMES[p.other.kind]}）`)
  }
  const { r, fixed: turned } = turnOf(directionsOf(pairs))
  // the move: t = the sum of value * direction over a basis made as the datums fix it
  const basis: Xyz[] = []
  const values: number[] = []
  for (const p of pairs) {
    const gap = sub(p.open.at, turn(r, p.other.at))
    for (const row of rowsOf(p.open)) {
      let e = row
      for (const b of basis) e = sub(e, scale(b, dot(e, b)))
      const l = norm(e)
      if (l <= PARALLEL_SIN) continue // fixed already (by a datum before it)
      let known = 0
      basis.forEach((b, k) => (known += values[k] * dot(row, b)))
      basis.push(scale(e, 1 / l))
      values.push((dot(row, gap) - known) / l)
    }
  }
  const moved = basis.length
  // the rest: the centre stays (its move has no part along them)
  const stay = sub(centre, turn(r, centre))
  for (const axis of [[1, 0, 0], [0, 1, 0], [0, 0, 1]] as Xyz[]) {
    if (basis.length === 3) break
    const e = squareTo(axis, basis)
    if (norm(e) <= 0.5) continue
    const g = unit(e)
    basis.push(g)
    values.push(dot(g, stay))
  }
  let t: Xyz = [0, 0, 0]
  basis.forEach((b, k) => (t = add(t, scale(b, values[k]))))
  const motion = { r, t }
  return { motion, fixed: { turn: turned, move: moved }, misfit: pairs.map((p) => misfitOf(p, motion)) }
}

/** the angle between two unit vectors, degrees (atan2: acos loses the last digits near 0) */
const angleOf = (a: Xyz, b: Xyz) => (Math.atan2(norm(cross(a, b)), dot(a, b)) * 180) / Math.PI

/** how far the moved datum is from the open one, and at what angle (the module's comment; an axis's either way) */
function misfitOf(p: DatumPair, m: Motion): { distance: number; angle: number } {
  const at = moveBy(m, p.other.at)
  const dir = p.other.dir ? unit(turn(m.r, p.other.dir)) : null
  const open = p.open.dir ? unit(p.open.dir) : null
  const angle = dir && open ? (p.open.kind === 'plane' ? angleOf(dir, open) : Math.min(angleOf(dir, open), angleOf(scale(dir, -1), open))) : 0
  let distance: number
  if (p.open.kind === 'plane') distance = Math.abs(dot(dir!, sub(p.open.mark, at))) // the open plane's click to the moved plane
  else if (p.open.kind === 'axis') distance = norm(squareTo(sub(p.open.at, at), [dir!])) // the open axis's point to the moved line
  else distance = norm(sub(at, p.open.at))
  return { distance, angle }
}

/** the turn of a motion as an angle (degrees, 0..180) about an axis (a unit vector; [0, 0, 1] for none) */
export function turnAngle(r: readonly number[]): { angle: number; axis: Xyz } {
  const c = (r[0] + r[4] + r[8] - 1) / 2
  const skew: Xyz = [r[7] - r[5], r[2] - r[6], r[3] - r[1]]
  // atan2: acos loses the last digits near 0 and half a turn
  const angle = (Math.atan2(norm(skew) / 2, c) * 180) / Math.PI
  if (c > -0.5) return norm(skew) > 1e-12 ? { angle, axis: unit(skew) } : { angle: 0, axis: [0, 0, 1] }
  // far round (the skew part is small): the symmetric part is cos I + (1 - cos) k k^T,
  // its longest column along k; its sign from the skew part
  const k = 1 - c
  const cols: Xyz[] = [
    [(r[0] - c) / k, (r[3] + r[1]) / (2 * k), (r[6] + r[2]) / (2 * k)],
    [(r[1] + r[3]) / (2 * k), (r[4] - c) / k, (r[7] + r[5]) / (2 * k)],
    [(r[2] + r[6]) / (2 * k), (r[5] + r[7]) / (2 * k), (r[8] - c) / k],
  ]
  let axis = unit(cols.reduce((a, b) => (norm(b) > norm(a) ? b : a)))
  if (dot(axis, skew) < 0) axis = scale(axis, -1)
  return { angle, axis }
}

/** the move of a point by the motion (the compared version's centre: what the screen tells) */
export const shiftOf = (m: Motion, at: Xyz): Xyz => sub(moveBy(m, at), at)

/** surfaces moved: new arrays (positions turned and moved, normals turned) */
export function movedSurfaces<S extends { positions: ArrayLike<number>; normals: ArrayLike<number>; indices: ArrayLike<number> }>(
  parts: S[],
  m: Motion,
): { positions: Float32Array; normals: Float32Array; indices: ArrayLike<number> }[] {
  const r = m.r, t = m.t
  return parts.map((s) => {
    const n = s.positions.length
    const positions = new Float32Array(n), normals = new Float32Array(s.normals.length)
    for (let i = 0; i < n; i += 3) {
      const x = s.positions[i], y = s.positions[i + 1], z = s.positions[i + 2]
      positions[i] = r[0] * x + r[1] * y + r[2] * z + t[0]
      positions[i + 1] = r[3] * x + r[4] * y + r[5] * z + t[1]
      positions[i + 2] = r[6] * x + r[7] * y + r[8] * z + t[2]
    }
    for (let i = 0; i < s.normals.length; i += 3) {
      const x = s.normals[i], y = s.normals[i + 1], z = s.normals[i + 2]
      normals[i] = r[0] * x + r[1] * y + r[2] * z
      normals[i + 1] = r[3] * x + r[4] * y + r[5] * z
      normals[i + 2] = r[6] * x + r[7] * y + r[8] * z
    }
    return { positions, normals, indices: s.indices }
  })
}
