/**
 * 面の変化 (src/facecompare.ts) on faces made as measure "faces" tells them:
 * a plate made thicker, a hole moved, a hole made larger, a part taken away
 * and one added, a face split in two, and a version in another frame.
 *
 *   npm test        (frontend)
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { moveBy, turn, type Motion, type Xyz } from '../src/align.ts'
import { compareFaces, movedFace, type FaceInfo, type PartFaces } from '../src/facecompare.ts'

const I: Motion = { r: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0] }
let next = 1
/** a rectangle face of a plane: its normal, a corner and its two sides */
function rect(normal: Xyz, corner: Xyz, u: Xyz, v: Xyz): FaceInfo {
  const lu = Math.hypot(...u), lv = Math.hypot(...v)
  return {
    id: next++,
    surface: 'plane',
    normal,
    origin: corner,
    area: lu * lv,
    perimeter: 2 * (lu + lv),
    centroid: [0, 1, 2].map((k) => corner[k] + (u[k] + v[k]) / 2) as Xyz,
  }
}
/** a box's six faces, x0..x1 etc. */
function boxFaces([x0, y0, z0]: Xyz, [x1, y1, z1]: Xyz): FaceInfo[] {
  const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0
  return [
    rect([0, 0, -1], [x0, y0, z0], [dx, 0, 0], [0, dy, 0]),
    rect([0, 0, 1], [x0, y0, z1], [dx, 0, 0], [0, dy, 0]),
    rect([0, -1, 0], [x0, y0, z0], [dx, 0, 0], [0, 0, dz]),
    rect([0, 1, 0], [x0, y1, z0], [dx, 0, 0], [0, 0, dz]),
    rect([-1, 0, 0], [x0, y0, z0], [0, dy, 0], [0, 0, dz]),
    rect([1, 0, 0], [x1, y0, z0], [0, dy, 0], [0, 0, dz]),
  ]
}
/** a hole's wall (a whole cylinder along z) */
function hole(x: number, y: number, r: number, h: number): FaceInfo {
  return { id: next++, surface: 'cylinder', axis: [0, 0, 1], center: [x, y, 0], radius: r, area: 2 * Math.PI * r * h, perimeter: 4 * Math.PI * r, centroid: [x, y, h / 2] }
}
const part = (name: string, faces: FaceInfo[], partId = 0): PartFaces => ({ partId, name, faces })
const kinds = (r: ReturnType<typeof compareFaces>) => r.changes.map((c) => c.kind)
const ab = { old: 'b', new: 'a' } as const

test('a plate made thicker: its top moved +0.50 along its normal, its sides reshaped, its bottom the same', () => {
  const r = compareFaces([part('plate', boxFaces([0, 0, 0], [60, 40, 3]))], [part('plate', boxFaces([0, 0, 0], [60, 40, 3.5]))], ab, I, 0.15, 100)
  assert.equal(r.same, 1)
  assert.deepEqual(kinds(r), ['moved', 'reshaped', 'reshaped', 'reshaped', 'reshaped'])
  assert.match(r.changes[0].text, /^平面（法線 \(0\.000, 0\.000, 1\.000\)）: 法線の向きに \+0\.50 mm 動いた$/)
  assert.ok(Math.abs(r.changes[0].amount - 0.5) < 1e-12)
  assert.deepEqual(r.changes[0].at, [30, 20, 3.5])
})

test('a hole moved: its axis moved 5.00 mm, from where to where; the plate faces the same', () => {
  const plate = boxFaces([0, 0, 0], [60, 40, 3])
  const r = compareFaces([part('plate', [...plate, hole(20, 20, 3, 3)])], [part('plate', [...plate, hole(25, 20, 3, 3)])], ab, I, 0.15, 100)
  assert.equal(r.same, 6)
  assert.equal(r.changes.length, 1)
  assert.equal(r.changes[0].text, '円筒 R3.00: 軸が 5.00 mm 動いた（(20.00, 20.00, 1.50) → (25.00, 20.00, 1.50)）')
})

test('a hole made larger: its radius +0.50', () => {
  const r = compareFaces([part('plate', [hole(20, 20, 3, 3)])], [part('plate', [hole(20, 20, 3.5, 3)])], ab, I, 0.15, 100)
  assert.deepEqual(kinds(r), ['resized'])
  assert.equal(r.changes[0].text, '円筒 R3.00 → R3.50: 半径 +0.50 mm')
})

test('a torus whose large radius changed: told by it (Codex on #111)', () => {
  const torus = (R: number, r: number): FaceInfo => ({ id: next++, surface: 'torus', axis: [0, 0, 1], center: [0, 0, 3], radius: r, majorRadius: R, area: 4 * Math.PI ** 2 * R * r, perimeter: 0, centroid: [0, 0, 3] })
  const r = compareFaces([part('boss', [torus(10, 2)])], [part('boss', [torus(12, 2)])], ab, I, 0.15, 100)
  assert.deepEqual(kinds(r), ['resized'])
  assert.equal(r.changes[0].text, '円環 R2.00: 大きい方の半径 R10.00 → R12.00（+2.00 mm）')
  assert.ok(Math.abs(r.changes[0].amount - 2) < 1e-12)
})

test('a part taken away and one added: told as parts, not their faces paired across', () => {
  const plate = boxFaces([0, 0, 0], [60, 40, 3])
  const pin = [hole(50, 30, 2, 10), rect([0, 0, 1], [48, 28, 13], [4, 0, 0], [0, 4, 0]), rect([0, 0, -1], [48, 28, 3], [4, 0, 0], [0, 4, 0])]
  const cap = boxFaces([5, 28, 3], [15, 38, 7])
  const r = compareFaces([part('plate', plate, 0), part('pin', pin, 1)], [part('plate', plate, 0), part('cap', cap, 1)], ab, I, 0.15, 100)
  assert.equal(r.same, 6)
  assert.deepEqual(kinds(r), ['added', 'removed'])
  assert.match(r.changes[0].text, /^部品「cap」: 新しい版にだけある（面 6、/)
  assert.match(r.changes[1].text, /^部品「pin」: 前の版にだけある（面 3、/)
  assert.deepEqual(r.changes[0].new, { side: 'a', partId: 1, faceId: null })
})

test('a face split in two (a rib across it): both pieces reshaped, none of one version alone', () => {
  const top = rect([0, 0, 1], [0, 0, 3], [60, 0, 0], [0, 40, 0])
  const left = rect([0, 0, 1], [0, 0, 3], [29, 0, 0], [0, 40, 0]), right = rect([0, 0, 1], [31, 0, 3], [29, 0, 0], [0, 40, 0])
  const r = compareFaces([part('plate', [top])], [part('plate', [left, right])], ab, I, 0.15, 100)
  assert.deepEqual(kinds(r), ['reshaped', 'reshaped'])
  assert.ok(r.changes.every((c) => !/だけある/.test(c.text)), JSON.stringify(r.changes))
})

test('the compared version in another frame: moved into the open one first, then the same', () => {
  const c = Math.cos(Math.PI / 6), s = Math.sin(Math.PI / 6)
  const m: Motion = { r: [1, 0, 0, 0, c, -s, 0, s, c], t: [10, -5, 2] }
  const inv: Motion = { r: [1, 0, 0, 0, c, s, 0, -s, c], t: [0, 0, 0] }
  inv.t = turn(inv.r, [-10, 5, -2])
  const faces = [...boxFaces([0, 0, 0], [60, 40, 3]), hole(20, 20, 3, 3)]
  // the compared file (b) is the open one (a) moved by m; the alignment is m's undoing
  const b = faces.map((f) => movedFace(f, m))
  const r = compareFaces([part('plate', b)], [part('plate', faces)], ab, inv, 0.15, 100)
  assert.equal(r.same, 7)
  assert.equal(r.changes.length, 0)
  assert.deepEqual(moveBy(inv, moveBy(m, [1, 2, 3])).map((v) => Math.round(v * 1e9) / 1e9), [1, 2, 3])
})
