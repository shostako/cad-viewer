/**
 * 位置合わせ (src/align.ts) on datums whose motion is known from how they are
 * made: the open version's datums, and the compared version's the same ones
 * moved back by a known motion. The alignment must find that motion again.
 *
 *   npm test        (frontend)
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { align, movedSurfaces, moveBy, shiftOf, turn, turnAngle, type Datum, type DatumPair, type Motion, type Xyz } from '../src/align.ts'

const deg = Math.PI / 180

/** a turn about a unit axis by an angle (degrees), row-major */
function turnAbout(axis: Xyz, angle: number): number[] {
  const [x, y, z] = axis
  const c = Math.cos(angle * deg), s = Math.sin(angle * deg), C = 1 - c
  return [c + x * x * C, x * y * C - z * s, x * z * C + y * s, y * x * C + z * s, c + y * y * C, y * z * C - x * s, z * x * C - y * s, z * y * C + x * s, c + z * z * C]
}
const mul = (a: number[], b: number[]) => {
  const out = new Array<number>(9)
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[3 * i + j] = a[3 * i] * b[j] + a[3 * i + 1] * b[3 + j] + a[3 * i + 2] * b[6 + j]
  return out
}
const transpose = (a: number[]) => [a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8]]
const inverse = (m: Motion): Motion => {
  const rt = transpose(m.r)
  const t = turn(rt, m.t)
  return { r: rt, t: [-t[0], -t[1], -t[2]] }
}

/** the compared version's datum: the open one moved back by `m` (the compared file is the open one moved by m⁻¹) */
function back(d: Datum, m: Motion, flip = false): Datum {
  const inv = inverse(m)
  const dir = d.dir ? turn(inv.r, d.dir) : undefined
  return { kind: d.kind, at: moveBy(inv, d.at), dir: dir && flip ? [-dir[0], -dir[1], -dir[2]] : dir, mark: moveBy(inv, d.mark) }
}

// a plate 60 x 40 x 3 at the origin, as the test data's revisions: its datums
const bottom: Datum = { kind: 'plane', at: [0, 0, 0], dir: [0, 0, -1], mark: [30, 20, 0] }
const front: Datum = { kind: 'plane', at: [0, 0, 0], dir: [0, -1, 0], mark: [30, 0, 1.5] }
const left: Datum = { kind: 'plane', at: [0, 0, 0], dir: [-1, 0, 0], mark: [0, 20, 1.5] }
const hole1: Datum = { kind: 'axis', at: [15, 20, 3], dir: [0, 0, 1], mark: [19, 20, 6] }
const hole2: Datum = { kind: 'axis', at: [45, 10, 0], dir: [0, 0, 1], mark: [47, 10, 2] }

/** turned 90° about Z and 30° about X, and moved */
const M: Motion = { r: mul(turnAbout([1, 0, 0], 30), turnAbout([0, 0, 1], 90)), t: [80, 20, 5] }

function near(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < a.length; i++) assert.ok(Math.abs(a[i] - b[i]) <= tol, `${what}: ${a} vs ${b}`)
}

function pairs(m: Motion, ...open: Datum[]): DatumPair[] {
  return open.map((d) => ({ open: d, other: back(d, m) }))
}

const centreOf = (m: Motion): Xyz => moveBy(inverse(m), [30, 20, 1.5])

test('three planes: the motion found again, nothing left free, no misfit', () => {
  const a = align(pairs(M, bottom, front, left), centreOf(M))
  near(a.motion.r, M.r, 1e-12, 'turn')
  near(a.motion.t, M.t, 1e-9, 'move')
  assert.deepEqual(a.fixed, { turn: 3, move: 3 })
  for (const f of a.misfit) assert.ok(f.distance < 1e-9 && f.angle < 1e-6, JSON.stringify(f))
})

test('upside down: the normals of the planes (out of the solid) turn it over, though not turning is the smaller turn', () => {
  const flip: Motion = { r: turnAbout([1, 0, 0], 180), t: [10, 40, 3] }
  const a = align(pairs(flip, bottom, front, left), centreOf(flip))
  near(a.motion.r, flip.r, 1e-12, 'turn')
  near(a.motion.t, flip.t, 1e-9, 'move')
})

test('A|B|C = the bottom, a hole, another hole: the way from hole to hole sets the turn', () => {
  // the second hole's axis written the other way round: an axis has no sign
  const ps: DatumPair[] = [
    { open: bottom, other: back(bottom, M) },
    { open: hole1, other: back(hole1, M) },
    { open: hole2, other: back(hole2, M, true) },
  ]
  const a = align(ps, centreOf(M))
  near(a.motion.r, M.r, 1e-12, 'turn')
  near(a.motion.t, M.t, 1e-9, 'move')
  assert.deepEqual(a.fixed, { turn: 3, move: 3 })
})

test('three points: the motion found again', () => {
  const pts: Datum[] = [[0, 0, 0], [60, 0, 0], [0, 40, 3]].map((p) => ({ kind: 'point', at: p as Xyz, mark: p as Xyz }))
  const a = align(pairs(M, ...pts), centreOf(M))
  near(a.motion.r, M.r, 1e-12, 'turn')
  near(a.motion.t, M.t, 1e-9, 'move')
  assert.deepEqual(a.fixed, { turn: 3, move: 3 })
})

test('a circle and a point: the centre fixes the place, the way to the point the turn about the axis', () => {
  const circle: Datum = { kind: 'circle', at: [15, 20, 3], dir: [0, 0, 1], mark: [19, 20, 3] }
  const corner: Datum = { kind: 'point', at: [60, 40, 3], mark: [60, 40, 3] }
  const a = align(pairs(M, circle, corner), centreOf(M))
  near(a.motion.r, M.r, 1e-12, 'turn')
  near(a.motion.t, M.t, 1e-9, 'move')
  assert.deepEqual(a.fixed, { turn: 3, move: 3 })
})

test('one plane: the faces meet, the rest keeps the centre (no move along the plane)', () => {
  const c = centreOf(M)
  const a = align(pairs(M, bottom), c)
  assert.deepEqual(a.fixed, { turn: 2, move: 1 })
  // the moved bottom lies on the open one: its normal along it, its points on it
  near(turn(a.motion.r, back(bottom, M).dir!), [0, 0, -1], 1e-12, 'normal')
  assert.ok(Math.abs(moveBy(a.motion, back(bottom, M).mark)[2]) < 1e-9, 'on the plane')
  // the centre moved along the normal only
  const s = shiftOf(a.motion, c)
  near([s[0], s[1]], [0, 0], 1e-9, `the centre's move ${s}`)
})

test('two points: the way between them is the only direction; the first point is the place', () => {
  const pts: Datum[] = [[0, 0, 0], [60, 0, 0]].map((p) => ({ kind: 'point', at: p as Xyz, mark: p as Xyz }))
  const a = align(pairs(M, ...pts), centreOf(M))
  assert.deepEqual(a.fixed, { turn: 2, move: 3 })
  for (const p of pts) near(moveBy(a.motion, back(p, M).at), p.at, 1e-9, 'each point on its own')
})

test('precedence: the first datum is matched exactly, a later one that disagrees only as far as it can', () => {
  // the compared version's left side 2° off square to the front (another shape there)
  const ps = pairs(M, bottom, front, left)
  const off = turnAbout([0, 0, 1], 2)
  ps[2] = { open: left, other: back({ ...left, dir: turn(off, left.dir!) }, M) }
  ps[1] = { open: front, other: back(front, M) }
  const a = align(ps, centreOf(M))
  // the bottom and the front set the turn: the left side does not
  near(a.motion.r, M.r, 1e-12, 'turn')
  assert.ok(a.misfit[0].distance < 1e-9 && a.misfit[0].angle < 1e-6, 'the bottom exactly')
  assert.ok(a.misfit[1].angle < 1e-6, 'the front square to it')
  assert.ok(Math.abs(a.misfit[2].angle - 2) < 1e-6, `the left side 2° off: ${a.misfit[2].angle}`)
})

test('the same datums on both: no motion', () => {
  const ps = [bottom, front, left].map((d) => ({ open: d, other: d }))
  const a = align(ps, [30, 20, 1.5])
  near(a.motion.r, [1, 0, 0, 0, 1, 0, 0, 0, 1], 1e-15, 'turn')
  near(a.motion.t, [0, 0, 0], 1e-12, 'move')
})

test('an axis alone: its direction either way, the smaller turn', () => {
  const ps: DatumPair[] = [{ open: hole1, other: { ...hole1, dir: [0, 0, -1] } }]
  const a = align(ps, [30, 20, 1.5])
  near(a.motion.r, [1, 0, 0, 0, 1, 0, 0, 0, 1], 1e-15, 'no turn: the axis is the same line')
  assert.deepEqual(a.fixed, { turn: 2, move: 2 })
})

test('datums of two kinds are refused', () => {
  assert.throws(() => align([{ open: bottom, other: hole1 }], [0, 0, 0]), /種類が違う/)
})

test('the turn as an angle about an axis, also half a turn', () => {
  const t1 = turnAngle(turnAbout([0, 0.6, 0.8], 37))
  assert.ok(Math.abs(t1.angle - 37) < 1e-9)
  near(t1.axis, [0, 0.6, 0.8], 1e-9, 'axis')
  const t2 = turnAngle(turnAbout([0.6, 0, -0.8], 180))
  assert.ok(Math.abs(t2.angle - 180) < 1e-9)
  // half a turn's axis either way
  const s = Math.sign(t2.axis[0])
  near(t2.axis.map((v) => v * s), [0.6, 0, -0.8], 1e-6, 'half a turn')
  assert.equal(turnAngle([1, 0, 0, 0, 1, 0, 0, 0, 1]).angle, 0)
})

test('surfaces moved: positions turned and moved, normals turned', () => {
  const s = { positions: Float32Array.from([1, 0, 0, 0, 1, 0]), normals: Float32Array.from([1, 0, 0, 0, 0, 1]), indices: [0, 1, 0] }
  const [m] = movedSurfaces([s], { r: turnAbout([0, 0, 1], 90), t: [10, 0, 0] })
  near(m.positions, [10, 1, 0, 9, 0, 0], 1e-6, 'positions')
  near(m.normals, [0, 1, 0, 0, 0, 1], 1e-6, 'normals')
})
