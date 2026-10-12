/**
 * 自動で合わせる (src/autoalign.ts) on shapes moved by a known motion: the
 * placement must be found again, what changed must not pull it, and a
 * symmetric shape must be told.
 *
 *   npm test        (frontend)
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { moveBy, turn, turnAngle, type Motion, type Xyz } from '../src/align.ts'
import { autoAlign, axisStarts, ordered, principal, samplePoints, type Fit } from '../src/autoalign.ts'
import type { Surface } from '../src/compare.ts'

type V = [number, number, number]

/** a box's six faces, each its own vertices (as a B-rep's display mesh) */
function box(lo: V, hi: V): Surface {
  const [x0, y0, z0] = lo, [x1, y1, z1] = hi
  const list: V[][] = [
    [[x0, y0, z0], [x0, y1, z0], [x1, y1, z0], [x1, y0, z0]],
    [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]],
    [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]],
    [[x0, y1, z0], [x0, y1, z1], [x1, y1, z1], [x1, y1, z0]],
    [[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]],
    [[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]],
  ]
  const positions: number[] = [], normals: number[] = [], indices: number[] = []
  for (const poly of list) {
    const [a, b, c] = poly
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], w = [c[0] - a[0], c[1] - a[1], c[2] - a[2]]
    const n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
    const l = Math.hypot(...n)
    const base = positions.length / 3
    for (const p of poly) positions.push(...p), normals.push(n[0] / l, n[1] / l, n[2] / l)
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3)
  }
  return { positions: Float32Array.from(positions), normals: Float32Array.from(normals), indices: Uint32Array.from(indices) }
}

const deg = Math.PI / 180
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
/** a surface moved by m (the compared file written in another frame) */
function moved(s: Surface, m: Motion): Surface {
  const p = Float32Array.from(s.positions), n = Float32Array.from(s.normals)
  for (let i = 0; i < p.length; i += 3) {
    const q = moveBy(m, [p[i], p[i + 1], p[i + 2]])
    const d = turn(m.r, [n[i], n[i + 1], n[i + 2]])
    p.set(q, i)
    n.set(d, i)
  }
  return { positions: p, normals: n, indices: s.indices }
}

// a plate with a step on it off its middle (no turn of it fits but the right one)
const PLATE = box([0, 0, 0], [60, 40, 3])
const STEP = box([40, 5, 3], [50, 15, 8])
const M: Motion = { r: mul(turnAbout([1, 0, 0], 30), turnAbout([0, 0, 1], 90)), t: [80, 20, 5] }

/** the motion found is m's undoing: its turn within 1e-3°, its move within 1e-3 mm at the part */
function undoes(found: Motion, m: Motion): void {
  const want = inverse(m)
  const rel = turnAngle(mul(found.r, transpose(want.r))).angle
  assert.ok(rel < 1e-3, `turned ${rel}° off`)
  const at: Xyz = [30, 20, 3]
  const a = moveBy(found, moveBy(m, at))
  assert.ok(Math.hypot(a[0] - at[0], a[1] - at[1], a[2] - at[2]) < 1e-3, `moved ${a} for ${at}`)
}

test('a plate with a step, moved: the placement found again, the only one that fits', () => {
  const r = autoAlign([PLATE, STEP], [moved(PLATE, M), moved(STEP, M)], { motion: null }, 0.05)
  undoes(r.fits[0].motion, M)
  assert.ok(r.fits[0].within > 0.999 && r.fits[0].rms < 1e-3, JSON.stringify(r.fits[0]))
  assert.equal(r.alike, 0)
})

test('what changed does not pull the fit: the step made higher, the plate still on the plate', () => {
  const higher = box([40, 5, 3], [50, 15, 12])
  const r = autoAlign([PLATE, STEP], [moved(PLATE, M), moved(higher, M)], { motion: null }, 0.05)
  undoes(r.fits[0].motion, M)
  // the higher step's top and the upper part of its sides stay apart (the change)
  const f = r.fits[0]
  assert.ok(f.within < 0.97 && f.within > 0.85, `${f.within}`)
  assert.ok(f.rms < 1e-3, `${f.rms}`)
})

test('a plain block: it fits as well each way round (four placements), and that is told', () => {
  const block = box([0, 0, 0], [40, 30, 10])
  const r = autoAlign([block], [moved(block, M)], { motion: null }, 0.05)
  assert.equal(r.alike, 3, JSON.stringify(r.fits.map((f) => f.within)))
  for (const f of r.fits.slice(0, 4)) assert.ok(f.within > 0.999, `${f.within}`)
})

test('a plain block in the same place: of the placements that fit alike, the one that does not move it first', () => {
  const block = box([0, 0, 0], [40, 30, 10])
  const r = autoAlign([block], [block], { motion: null }, 0.05)
  assert.equal(r.alike, 3)
  assert.ok(turnAngle(r.fits[0].motion.r).angle < 1e-6 && Math.hypot(...r.fits[0].motion.t) < 1e-6, JSON.stringify(r.fits[0].motion))
})

test('from a start (the alignment by datums): refined from there alone', () => {
  const want = inverse(M)
  const start: Motion = { r: mul(turnAbout([0.6, 0.8, 0], 1), want.r), t: [want.t[0] + 0.5, want.t[1] - 0.3, want.t[2]] }
  const r = autoAlign([PLATE, STEP], [moved(PLATE, M), moved(STEP, M)], { motion: start }, 0.05)
  assert.equal(r.fits.length, 1)
  undoes(r.fits[0].motion, M)
})

test('from a plane alone (a turn about it left free): turned about it in steps, it is found', () => {
  // the plate's top matched, but 100° round about its normal: refined alone, it stops short
  const want = inverse(M)
  const R = turnAbout([0, 0, 1], 100)
  const at: Xyz = [30, 20, 3]
  const q = turn(R, [want.t[0] - at[0], want.t[1] - at[1], want.t[2] - at[2]])
  const off: Motion = { r: mul(R, want.r), t: [q[0] + at[0], q[1] + at[1], q[2] + at[2]] }
  const b = [moved(PLATE, M), moved(STEP, M)]
  const alone = autoAlign([PLATE, STEP], b, { motion: off }, 0.05)
  assert.ok(alone.fits[0].within < 0.95, `alone it stops short: ${alone.fits[0].within}`)
  const r = autoAlign([PLATE, STEP], b, { motion: off, spin: { axis: [0, 0, 1], at } }, 0.05)
  undoes(r.fits[0].motion, M)
  assert.equal(r.alike, 0)
})

test('the order: the best fit first; of those that fit alike, the least move first, whatever their RMS', () => {
  const centre: Xyz = [20, 15, 5]
  const at = (angle: number, rms: number, within = 1): Fit => {
    const r = turnAbout([0, 0, 1], angle)
    const q = turn(r, centre)
    return { motion: { r, t: [centre[0] - q[0], centre[1] - q[1], centre[2] - q[2]] }, within, rms }
  }
  // the turned ones fit a little closer (rms), the one not moved is still first among the alike
  const o = ordered([at(180, 0), at(0, 2e-3), at(90, 1e-3), at(0, 0, 0.5)], centre, 50)
  assert.deepEqual(o.fits.map((f) => Math.round(turnAngle(f.motion.r).angle)), [0, 90, 180, 0])
  assert.equal(o.alike, 2)
  assert.equal(o.fits[3].within, 0.5, 'the one that fits worse last')
})

test('the starts: the alignment by datums alone when it fixed everything; with a free turn, the turns about it and the search', () => {
  const b = [moved(PLATE, M), moved(STEP, M)]
  const want = inverse(M)
  assert.equal(autoAlign([PLATE, STEP], b, { motion: want }, 0.05).starts, 1)
  const spun = autoAlign([PLATE, STEP], b, { motion: want, spin: { axis: [0, 0, 1], at: [30, 20, 3] } }, 0.05).starts
  const searched = autoAlign([PLATE, STEP], b, { motion: null }, 0.05).starts
  assert.equal(spun, 12 + searched)
  assert.equal(searched, 5, 'the places in the files and the 4 ways round the axes')
})

test('the principal axes: largest spread first, a turn (det +1)', () => {
  const p = principal(samplePoints([box([0, 0, 0], [40, 30, 10])], 4000))
  assert.ok(p.spread[0] > p.spread[1] && p.spread[1] > p.spread[2], `${p.spread}`)
  const a = p.axes
  const det = a[0] * (a[4] * a[8] - a[5] * a[7]) - a[1] * (a[3] * a[8] - a[5] * a[6]) + a[2] * (a[3] * a[7] - a[4] * a[6])
  assert.ok(Math.abs(det - 1) < 1e-9, `${det}`)
  // the first along x (40), the last along z (10)
  assert.ok(Math.abs(Math.abs(a[0]) - 1) < 0.02 && Math.abs(Math.abs(a[8]) - 1) < 0.02, `${a}`)
})

test('the placements of the principal axes: 4 for a box, 8 for a square plate, 24 for a cube', () => {
  const n = (s: Surface) => axisStarts(samplePoints([s], 4000, 5), samplePoints([moved(s, M)], 4000, 6)).length
  assert.equal(n(box([0, 0, 0], [40, 30, 10])), 4)
  assert.equal(n(box([0, 0, 0], [40, 40, 5])), 8)
  assert.equal(n(box([0, 0, 0], [20, 20, 20])), 24)
})

test('points spread by area: the same every time, on the surface', () => {
  const s = [box([0, 0, 0], [40, 30, 10])]
  const a = samplePoints(s, 500, 7), b = samplePoints(s, 500, 7)
  assert.deepEqual([...a], [...b])
  for (let i = 0; i < a.length; i += 3) {
    const [x, y, z] = [a[i], a[i + 1], a[i + 2]]
    const off = Math.min(Math.abs(x), Math.abs(x - 40), Math.abs(y), Math.abs(y - 30), Math.abs(z), Math.abs(z - 10))
    assert.ok(off < 1e-6, `${[x, y, z]}`)
  }
})
