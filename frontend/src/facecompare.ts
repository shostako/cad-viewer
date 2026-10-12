/**
 * 面の変化 for 版の比較 (docs/designs/compare-faces.md): the B-rep faces of
 * the two versions paired, as SOLIDWORKS's Compare Geometry pairs them: the
 * same face, a face changed (moved, its size changed, its shape trimmed
 * otherwise), a face of one version alone. What a change is is told in the
 * drawing's terms: a hole's axis moved 5.00 mm, a face moved +0.50 mm along
 * its normal, a radius from R3.00 to R3.50.
 *
 * The faces come from the backend's (or the Web version's) measure "faces"
 * (face_info for every face). The compared version's are moved into the open
 * one's frame by the alignment first. Pure (no three.js, no DOM).
 */
import { moveBy, turn, type Motion, type Xyz } from './align.ts'

/** a face as measure "faces" tells it (the sizes its kind has) */
export interface FaceInfo {
  id: number
  surface: string
  area: number
  centroid: Xyz
  perimeter?: number
  normal?: Xyz
  origin?: Xyz
  axis?: Xyz
  center?: Xyz
  radius?: number
  majorRadius?: number
  apex?: Xyz
  angle?: number
}

export interface PartFaces {
  partId: number
  /** the part's name (a part of one version alone is told by it) */
  name: string
  faces: FaceInfo[]
}

/** what became of a face (or a part) */
export type FaceChangeKind = 'moved' | 'resized' | 'reshaped' | 'added' | 'removed'

/** the kinds as the screen names them */
export const FACE_CHANGE_NAMES: Record<FaceChangeKind, string> = {
  moved: '動いた',
  resized: '大きさが変わった',
  reshaped: '形が変わった',
  added: '新しい版にだけ',
  removed: '前の版にだけ',
}

export interface FaceChange {
  kind: FaceChangeKind
  /** the face's kind (plane, cylinder, ...) or 'part' (a part of one version alone) */
  surface: string
  /** what it is, in the drawing's terms */
  text: string
  /** the same, short (a line of the legend) */
  short: string
  /** where (in the open version's frame): the face's centroid, the new one's for a change */
  at: Xyz
  /** how much it moved or grew (mm; 0 for a reshape or a face of one version alone) */
  amount: number
  /** the face's area (a part's: its faces'), mm² */
  area: number
  /** the faces (or a part) it is about: the old version's and the new one's (side 'a' the open version) */
  old: { side: 'a' | 'b'; partId: number; faceId: number | null } | null
  new: { side: 'a' | 'b'; partId: number; faceId: number | null } | null
}

export interface FaceComparison {
  /** how many faces are the same in both */
  same: number
  changes: FaceChange[]
}

/** directions closer than this (the sine, 0.5°) are the same */
const PARALLEL = Math.sin((0.5 * Math.PI) / 180)

type V = Xyz
const sub = (a: V, b: V): V => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot = (a: V, b: V) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: V, b: V): V => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const norm = (a: V) => Math.hypot(a[0], a[1], a[2])
const unit = (a: V): V => {
  const l = norm(a) || 1
  return [a[0] / l, a[1] / l, a[2] / l]
}
/** a's part square to the unit d */
const across = (a: V, d: V): V => {
  const k = dot(a, d)
  return [a[0] - k * d[0], a[1] - k * d[1], a[2] - k * d[2]]
}
const sameDir = (a: V, b: V) => dot(a, b) > 0 && norm(cross(unit(a), unit(b))) <= PARALLEL
const sameLine = (a: V, b: V) => norm(cross(unit(a), unit(b))) <= PARALLEL
const deg = (r: number) => (r * 180) / Math.PI

/** a face moved by m (its points moved, its directions turned) */
export function movedFace(f: FaceInfo, m: Motion): FaceInfo {
  const out: FaceInfo = { ...f, centroid: moveBy(m, f.centroid) }
  for (const k of ['origin', 'center', 'apex'] as const) if (f[k]) out[k] = moveBy(m, f[k]!)
  for (const k of ['normal', 'axis'] as const) if (f[k]) out[k] = unit(turn(m.r, f[k]!))
  return out
}

/** the same surface (kind and sizes) within the tolerance: the same plane, cylinder, ... wherever trimmed */
export function sameSurface(a: FaceInfo, b: FaceInfo, tol: number): boolean {
  if (a.surface !== b.surface) return false
  switch (a.surface) {
    case 'plane':
      return !!(a.normal && b.normal && a.origin && b.origin) && sameDir(a.normal, b.normal) && Math.abs(dot(a.normal, sub(b.origin, a.origin))) <= tol
    case 'cylinder':
      return (
        !!(a.axis && b.axis && a.center && b.center) &&
        sameLine(a.axis, b.axis) &&
        Math.abs(a.radius! - b.radius!) <= tol &&
        norm(across(sub(b.center, a.center), unit(a.axis))) <= tol
      )
    case 'cone':
      return (
        !!(a.axis && b.axis && a.apex && b.apex) &&
        sameLine(a.axis, b.axis) &&
        Math.abs(a.angle! - b.angle!) <= deg(PARALLEL) &&
        norm(sub(a.apex, b.apex)) <= tol
      )
    case 'sphere':
      return !!(a.center && b.center) && Math.abs(a.radius! - b.radius!) <= tol && norm(sub(a.center, b.center)) <= tol
    case 'torus':
      return (
        !!(a.axis && b.axis && a.center && b.center) &&
        sameLine(a.axis, b.axis) &&
        norm(sub(a.center, b.center)) <= tol &&
        Math.abs(a.radius! - b.radius!) <= tol &&
        Math.abs(a.majorRadius! - b.majorRadius!) <= tol
      )
    default:
      // a surface of no kind with sizes (a B-spline): by where it is and how large
      return norm(sub(a.centroid, b.centroid)) <= tol && Math.abs(a.area - b.area) <= tol * Math.max(a.perimeter ?? 0, b.perimeter ?? 0, 1)
  }
}

/** the same face: the same surface, trimmed alike (its area and centroid within the tolerance) */
export function sameFace(a: FaceInfo, b: FaceInfo, tol: number): boolean {
  if (!sameSurface(a, b, tol)) return false
  const rim = Math.max(a.perimeter ?? 0, b.perimeter ?? 0)
  // trimmed a tolerance otherwise all round: the area by the rim times it
  return Math.abs(a.area - b.area) <= tol * Math.max(rim, 1) && norm(sub(a.centroid, b.centroid)) <= tol
}

/** 3 decimals, the sign always (a change) */
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}`
const at2 = (p: V) => `(${p.map((v) => (Math.abs(v) < 5e-3 ? 0 : v).toFixed(2)).join(', ')})`
const dir3 = (d: V) => `(${d.map((v) => (Math.abs(v) < 5e-4 ? 0 : v).toFixed(3)).join(', ')})`

/** +X, -Z, ...: a direction along an axis; else its components (2 decimals) */
export function dirShort(d: V): string {
  const u = unit(d)
  const k = [0, 1, 2].find((i) => Math.abs(Math.abs(u[i]) - 1) < 1e-6)
  if (k !== undefined) return `${u[k] > 0 ? '+' : '−'}${'XYZ'[k]}`
  return `(${u.map((v) => (Math.abs(v) < 5e-3 ? 0 : v).toFixed(2)).join(', ')})`
}

/** the name a face is told by in a line: its kind and its size, a plane by its normal (+Z) */
export function shortName(f: FaceInfo): string {
  return f.surface === 'plane' ? `平面 ${dirShort(f.normal!)}` : faceName(f)
}

/** the name a face is told by: its kind and its size */
export function faceName(f: FaceInfo): string {
  switch (f.surface) {
    case 'plane':
      return `平面（法線 ${dir3(f.normal!)}）`
    case 'cylinder':
      return `円筒 R${f.radius!.toFixed(2)}`
    case 'cone':
      return `円錐（半角 ${f.angle!.toFixed(2)}°）`
    case 'sphere':
      return `球 SR${f.radius!.toFixed(2)}`
    case 'torus':
      return `円環 R${f.radius!.toFixed(2)}`
    default:
      return `曲面（${f.surface}）`
  }
}

/**
 * A change of the old face o into the new face n, of the same kind (null: not
 * a change of one into the other): moved (a plane along its normal, an axis
 * across itself, a centre), resized (a radius, a cone's angle), or, the same
 * surface trimmed otherwise, reshaped. Its cost: how far it went (the nearer
 * pairs first).
 */
function changeOf(o: FaceInfo, n: FaceInfo, tol: number): { kind: FaceChangeKind; text: string; short: string; amount: number; cost: number } | null {
  if (o.surface !== n.surface) return null
  const name = faceName(n)
  const area = `面積 ${o.area.toFixed(1)} → ${n.area.toFixed(1)} mm²`
  // the two must be about where each other is: their centroids no farther apart
  // than the larger face is across (the pin's foot and a new cap's are on one
  // plane, 40 apart: not one face changed)
  const across0 = Math.max(Math.sqrt(o.area), Math.sqrt(n.area), tol)
  const apart = norm(sub(o.centroid, n.centroid))
  const sn = shortName(n), areas = `面積 ${o.area.toFixed(1)} → ${n.area.toFixed(1)}`
  if (sameSurface(o, n, tol)) return apart <= across0 ? { kind: 'reshaped', text: `${name}: 形が変わった（${area}）`, short: `${sn}: ${areas}`, amount: 0, cost: apart } : null
  switch (o.surface) {
    case 'plane': {
      if (!sameDir(o.normal!, n.normal!)) return null
      if (norm(across(sub(n.centroid, o.centroid), unit(o.normal!))) > across0) return null
      const d = dot(o.normal!, sub(n.origin!, o.origin!))
      return {
        kind: 'moved',
        text: `${name}: 法線の向きに ${signed(d)} mm 動いた`,
        short: `${sn}: ${signed(d)} mm`,
        amount: Math.abs(d),
        cost: Math.abs(d) + norm(across(sub(n.centroid, o.centroid), o.normal!)),
      }
    }
    case 'cylinder':
    case 'torus': {
      if (!sameLine(o.axis!, n.axis!)) return null
      const axis = unit(o.axis!)
      const shift = across(sub(n.center!, o.center!), axis)
      // a hole moved a few of its radii at most; along the axis the faces overlap
      if (norm(shift) > 4 * Math.max(o.radius!, n.radius!) + tol) return null
      if (Math.abs(dot(sub(n.centroid, o.centroid), axis)) > across0) return null
      const moved = norm(shift) > tol
      const grown = Math.abs(n.radius! - o.radius!) > tol || (o.surface === 'torus' && Math.abs(n.majorRadius! - o.majorRadius!) > tol)
      if (moved && grown) return null // two changes at once: not told as one face's
      if (moved) {
        const from = o.centroid, to = sub(o.centroid, [-shift[0], -shift[1], -shift[2]])
        return {
          kind: 'moved',
          text: `${name}: 軸が ${norm(shift).toFixed(2)} mm 動いた（${at2(from)} → ${at2(to)}）`,
          short: `${sn}: 軸が ${norm(shift).toFixed(2)} mm`,
          amount: norm(shift),
          cost: norm(shift),
        }
      }
      const dr = n.radius! - o.radius!
      return {
        kind: 'resized',
        text: `${faceName(o)} → R${n.radius!.toFixed(2)}: 半径 ${signed(dr)} mm`,
        short: `${faceName(o)} → R${n.radius!.toFixed(2)}`,
        amount: Math.abs(dr),
        cost: Math.abs(dr) + norm(sub(n.centroid, o.centroid)),
      }
    }
    case 'cone': {
      if (!sameLine(o.axis!, n.axis!)) return null
      const d = norm(sub(n.apex!, o.apex!))
      if (d > across0) return null
      const da = n.angle! - o.angle!
      if (Math.abs(da) > deg(PARALLEL)) return { kind: 'resized', text: `${faceName(o)}: 半角 ${signed(da)}°`, short: `${faceName(o)}: ${signed(da)}°`, amount: Math.abs(da), cost: d + Math.abs(da) }
      return { kind: 'moved', text: `${name}: 頂点が ${d.toFixed(2)} mm 動いた`, short: `${sn}: 頂点が ${d.toFixed(2)} mm`, amount: d, cost: d }
    }
    case 'sphere': {
      const d = norm(sub(n.center!, o.center!))
      const dr = n.radius! - o.radius!
      if (d > tol && Math.abs(dr) > tol) return null
      if (d > 4 * Math.max(o.radius!, n.radius!) + tol) return null
      if (d > tol) return { kind: 'moved', text: `${name}: 中心が ${d.toFixed(2)} mm 動いた`, short: `${sn}: 中心が ${d.toFixed(2)} mm`, amount: d, cost: d }
      return { kind: 'resized', text: `${faceName(o)} → SR${n.radius!.toFixed(2)}: 半径 ${signed(dr)} mm`, short: `${faceName(o)} → SR${n.radius!.toFixed(2)}`, amount: Math.abs(dr), cost: Math.abs(dr) }
    }
    default:
      return null
  }
}

/**
 * The faces of the two versions paired (the module's comment). oldParts and
 * newParts as measured; the side of each ('a' the open version, 'b' the
 * compared one) and the motion that puts the compared version in the open
 * one's frame. tol: the comparison's tolerance. Changes whose faces are far
 * apart (more than `reach`: a part's size) are not taken as one face's.
 */
export function compareFaces(
  oldParts: PartFaces[],
  newParts: PartFaces[],
  sides: { old: 'a' | 'b'; new: 'a' | 'b' },
  motion: Motion,
  tol: number,
  reach = Infinity,
): FaceComparison {
  type Item = { f: FaceInfo; partId: number; taken: boolean }
  const place = (parts: PartFaces[], side: 'a' | 'b'): Item[] =>
    parts.flatMap((p) => p.faces.map((f) => ({ f: side === 'b' ? movedFace(f, motion) : f, partId: p.partId, taken: false })))
  const olds = place(oldParts, sides.old), news = place(newParts, sides.new)
  const ref = (side: 'a' | 'b', it: Item) => ({ side, partId: it.partId, faceId: it.f.id })
  // 1. the same faces: each old face to the nearest same new one
  let same = 0
  for (const o of olds) {
    let best: Item | null = null
    for (const n of news) {
      if (n.taken || !sameFace(o.f, n.f, tol)) continue
      if (!best || norm(sub(n.f.centroid, o.f.centroid)) < norm(sub(best.f.centroid, o.f.centroid))) best = n
    }
    if (best) {
      o.taken = best.taken = true
      same++
    }
  }
  // 2. the changed faces: the pairs of the rest that are a change of one into the other, the cheapest first
  const pairs: { o: Item; n: Item; c: NonNullable<ReturnType<typeof changeOf>> }[] = []
  for (const o of olds) {
    if (o.taken) continue
    for (const n of news) {
      if (n.taken) continue
      const c = changeOf(o.f, n.f, tol)
      if (c && norm(sub(n.f.centroid, o.f.centroid)) <= reach) pairs.push({ o, n, c })
    }
  }
  pairs.sort((x, y) => x.c.cost - y.c.cost)
  const changes: FaceChange[] = []
  for (const { o, n, c } of pairs) {
    if (o.taken || n.taken) continue
    o.taken = n.taken = true
    changes.push({ kind: c.kind, surface: n.f.surface, text: c.text, short: c.short, at: n.f.centroid, amount: c.amount, area: n.f.area, old: ref(sides.old, o), new: ref(sides.new, n) })
  }
  // 3. a face of one version alone: a part none of whose faces is in the other, as the part;
  //    a face on a surface the other version has (split, or a piece cut off) reshaped
  const alone = (items: Item[], others: Item[], parts: PartFaces[], side: 'a' | 'b', kind: 'added' | 'removed') => {
    const which = kind === 'added' ? '新しい版' : '前の版'
    for (const p of parts) {
      const mine = items.filter((it) => it.partId === p.partId)
      if (mine.length && mine.every((it) => !it.taken)) {
        const area = mine.reduce((s, it) => s + it.f.area, 0)
        const c = centroidOf(mine.map((it) => it.f))
        changes.push({
          kind,
          surface: 'part',
          text: `部品「${p.name}」: ${which}にだけある（面 ${mine.length}、面積 ${area.toFixed(1)} mm²）`,
          short: `部品「${p.name}」（面 ${mine.length}）`,
          at: c,
          amount: 0,
          area,
          old: kind === 'removed' ? { side, partId: p.partId, faceId: null } : null,
          new: kind === 'added' ? { side, partId: p.partId, faceId: null } : null,
        })
        for (const it of mine) it.taken = true
      }
    }
    for (const it of items) {
      if (it.taken) continue
      it.taken = true
      const on = others.find((x) => sameSurface(x.f, it.f, tol))
      if (on) {
        changes.push({
          kind: 'reshaped',
          surface: it.f.surface,
          text: `${faceName(it.f)}: 形が変わった（同じ面の${kind === 'added' ? '新しい版で増えた' : '前の版にあった'}部分、面積 ${it.f.area.toFixed(1)} mm²）`,
          short: `${shortName(it.f)}: ${kind === 'added' ? '増えた' : '減った'}部分 ${it.f.area.toFixed(1)} mm²`,
          at: it.f.centroid,
          amount: 0,
          area: it.f.area,
          old: kind === 'removed' ? ref(side, it) : ref(sides.old, on),
          new: kind === 'added' ? ref(side, it) : ref(sides.new, on),
        })
        continue
      }
      changes.push({
        kind,
        surface: it.f.surface,
        text: `${faceName(it.f)}: ${which}にだけある（面積 ${it.f.area.toFixed(1)} mm²）`,
        short: `${shortName(it.f)}（${it.f.area.toFixed(1)} mm²）`,
        at: it.f.centroid,
        amount: 0,
        area: it.f.area,
        old: kind === 'removed' ? ref(side, it) : null,
        new: kind === 'added' ? ref(side, it) : null,
      })
    }
  }
  alone(olds, news, oldParts, sides.old, 'removed')
  alone(news, olds, newParts, sides.new, 'added')
  const order: Record<FaceChangeKind, number> = { moved: 0, resized: 1, added: 2, removed: 3, reshaped: 4 }
  changes.sort((x, y) => order[x.kind] - order[y.kind] || y.amount - x.amount)
  return { same, changes }
}

/** the area-weighted centroid of faces */
function centroidOf(faces: FaceInfo[]): Xyz {
  let a = 0
  const c: Xyz = [0, 0, 0]
  for (const f of faces) {
    a += f.area
    for (let k = 0; k < 3; k++) c[k] += f.area * f.centroid[k]
  }
  return a > 0 ? [c[0] / a, c[1] / a, c[2] / a] : faces[0]?.centroid ?? [0, 0, 0]
}
