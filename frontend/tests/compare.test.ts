/**
 * Comparing two versions (src/compare.ts) on shapes whose distances are known
 * from how they are made: a box raised by 2, a rib taken away, a notch filled.
 *
 *   npm test        (frontend)
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { bvhOfParts, chooseEdge, compare, diagonalOf, signedDistances, subdivide, type Surface } from '../src/compare.ts'

type V = [number, number, number]

/** a part made of flat faces, each its own vertices (as a B-rep's display mesh: vertices repeat along the rims) */
function faces(list: V[][]): Surface {
  const positions: number[] = [], normals: number[] = [], indices: number[] = []
  for (const poly of list) {
    // the face's normal from its corners (counter-clockwise from outside)
    const [a, b, c] = poly
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], w = [c[0] - a[0], c[1] - a[1], c[2] - a[2]]
    const n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
    const l = Math.hypot(...n)
    const base = positions.length / 3
    for (const p of poly) positions.push(...p), normals.push(n[0] / l, n[1] / l, n[2] / l)
    // a fan from the first corner (the faces here are star-shaped from it)
    for (let k = 1; k + 1 < poly.length; k++) indices.push(base, base + k, base + k + 1)
  }
  return { positions: Float32Array.from(positions), normals: Float32Array.from(normals), indices: Uint32Array.from(indices) }
}

function box(lo: V, hi: V): Surface {
  const [x0, y0, z0] = lo, [x1, y1, z1] = hi
  return faces([
    [[x0, y0, z0], [x0, y1, z0], [x1, y1, z0], [x1, y0, z0]], // bottom (-z)
    [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], // top
    [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]], // -y
    [[x0, y1, z0], [x0, y1, z1], [x1, y1, z1], [x1, y1, z0]], // +y
    [[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]], // -x
    [[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]], // +x
  ])
}

/** a counter-clockwise polygon (star-shaped from its first corner) from z 0 to h */
function prism(poly: [number, number][], h: number): Surface {
  const n = poly.length
  const list: V[][] = [
    poly.map(([x, y]): V => [x, y, 0]).reverse(),
    poly.map(([x, y]): V => [x, y, h]),
  ]
  // the bottom reversed starts at the last corner: put the first corner first again
  list[0].unshift(list[0].pop()!)
  for (let i = 0; i < n; i++) {
    const [x0, y0] = poly[i], [x1, y1] = poly[(i + 1) % n]
    list.push([[x0, y0, 0], [x1, y1, 0], [x1, y1, h], [x0, y0, h]])
  }
  return faces(list)
}

/** every vertex of a sampled side with its offset */
function* vertices(s: { positions: Float32Array; offset: Float32Array }): Generator<[number, number, number, number]> {
  for (let i = 0; i < s.offset.length; i++) yield [s.positions[3 * i], s.positions[3 * i + 1], s.positions[3 * i + 2], s.offset[i]]
}

/** the largest difference from the expected offsets (the finer mesh is float32: to 1e-5 or so) */
function worst(s: { positions: Float32Array; offset: Float32Array }, want: (x: number, y: number, z: number) => number): number {
  let w = 0
  for (const [x, y, z, o] of vertices(s)) w = Math.max(w, Math.abs(o - want(x, y, z)))
  return w
}

test('a box raised by 2: + outside the other, - inside, 0 where the surfaces meet', () => {
  const a = [box([0, 0, 0], [10, 10, 10])]
  const b = [box([0, 0, 0], [10, 10, 12])]
  const { a: sa, b: sb } = compare(a, b)
  // b's points: outside a by their height over 10
  assert.ok(worst(sb, (_x, _y, z) => Math.max(0, z - 10)) < 1e-4, 'the raised version')
  // a's top: inside b, as deep as the nearest of b's faces
  assert.ok(worst(sa, (x, y, z) => (z === 10 ? -Math.min(2, x, 10 - x, y, 10 - y) : 0)) < 1e-4, 'the first version')
  assert.equal(Math.max(...sb.offset), 2)
})

test('a rib taken away: its faces outside the other version by their height over the plate', () => {
  const plate = box([0, 0, 0], [20, 10, 2])
  const rib = box([9, 1, 2], [11, 9, 6])
  const { a: sa, b: sb } = compare([plate, rib], [plate])
  const ribPoints = [...vertices(sa)].filter(([x, y, z]) => z > 2 && x >= 9 && x <= 11 && y >= 1 && y <= 9)
  assert.ok(ribPoints.length > 50, 'the rib is cut finer: its sides have points between its rims')
  for (const [x, y, z, o] of ribPoints) assert.ok(Math.abs(o - (z - 2)) < 1e-4, `rib point ${[x, y, z]}: ${o}`)
  // everything of the second version is on the first
  assert.ok(worst(sb, () => 0) < 1e-6)
})

test('a notch filled: seen though no vertex of the display meshes is in it', () => {
  const L: [number, number][] = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]]
  const a = [prism(L, 2)]
  const b = [box([0, 0, 0], [10, 10, 2])]
  // the vertices alone: the notch's walls have none but at z 0 and 2, on b's faces
  for (let i = 0; i < a[0].positions.length; i += 3) assert.ok([0, 2].includes(a[0].positions[i + 2]))
  const { a: sa, b: sb } = compare(a, b)
  // the notch's walls: inside b
  const walls = [...vertices(sa)].filter(([x, y, z]) => z > 0 && z < 2 && ((x === 4 && y > 4) || (y === 4 && x > 4)))
  assert.ok(walls.length > 20)
  // (as deep as the nearest face of the box b: its top, bottom or a side)
  for (const [x, y, z, o] of walls) assert.ok(Math.abs(o + Math.min(z, 2 - z, x, 10 - x, y, 10 - y)) < 1e-4, `wall ${[x, y, z]}: ${o}`)
  // b's top and bottom over the notch: outside a by how far the notch's walls are
  const over = [...vertices(sb)].filter(([x, y, z]) => (z === 0 || z === 2) && x > 4 && y > 4)
  assert.ok(over.length > 50)
  for (const [x, y, z, o] of over) assert.ok(Math.abs(o - Math.min(x - 4, y - 4)) < 1e-4, `over ${[x, y, z]}: ${o}`)
})

test('the side at a sharp edge: each face counts by its angle there, not by its triangles', () => {
  // a wedge along y (length 4) whose edge at x 10 is sharp (5.7 degrees): the
  // bottom (-z) is cut into 12 triangles meeting at the edge's end (10, 0, 0),
  // the slanted top into 2
  const L = 4
  const bottom: V[] = [[10, 0, 0], ...Array.from({ length: 13 }, (_, k): V => [0, (L * k) / 12, 0]), [10, L, 0]]
  const wedge = faces([
    bottom,
    [[10, 0, 0], [10, L, 0], [0, L, 1], [0, 0, 1]], // the slanted top
    [[0, 0, 0], [0, 0, 1], [0, L, 1], [0, L, 0]], // the back (-x)
    [[0, 0, 0], [10, 0, 0], [0, 0, 1]], // the end y 0
    [[0, L, 0], [0, L, 1], [10, L, 0]], // the end y L
  ])
  // just past the edge's end, a little up: outside, nearest to the corner (10, 0, 0).
  // From there it is 0.05 below the bottom's plane's outside and 0.15 over the
  // top's: counted by triangles (12 against 2) the bottom would say inside
  const d = signedDistances([11, 0, 0.05], bvhOfParts([wedge]), 1e-9)[0]
  assert.ok(Math.abs(d - Math.hypot(1, 0.05)) < 1e-6, `outside the tip: ${d}`)
  // and just inside the tip, below the top
  const inside = signedDistances([9.5, 2, 0.02], bvhOfParts([wedge]), 1e-9)[0]
  assert.ok(inside < 0, `inside: ${inside}`)
})

test('the finer mesh: the same surface, no edge longer than asked', () => {
  const s = box([0, 0, 0], [10, 20, 30])
  const L = 3
  const f = subdivide([s], L)
  let area = 0, longest = 0
  const p = f.positions
  for (let t = 0; t < f.indices.length; t += 3) {
    const [i, j, k] = [f.indices[t], f.indices[t + 1], f.indices[t + 2]]
    const u = [p[3 * j] - p[3 * i], p[3 * j + 1] - p[3 * i + 1], p[3 * j + 2] - p[3 * i + 2]]
    const w = [p[3 * k] - p[3 * i], p[3 * k + 1] - p[3 * i + 1], p[3 * k + 2] - p[3 * i + 2]]
    area += Math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]) / 2
    for (const [m, n] of [[i, j], [j, k], [k, i]]) longest = Math.max(longest, Math.hypot(p[3 * n] - p[3 * m], p[3 * n + 1] - p[3 * m + 1], p[3 * n + 2] - p[3 * m + 2]))
  }
  assert.ok(Math.abs(area - 2 * (200 + 300 + 600)) < 1e-6 * 2200, `area ${area}`)
  assert.ok(longest <= L + 1e-5, `longest ${longest}`)
  // the normals are the faces' (each face flat)
  for (let i = 0; i < f.normals.length; i += 3) assert.ok(Math.abs(Math.hypot(f.normals[i], f.normals[i + 1], f.normals[i + 2]) - 1) < 1e-6)
})

test('the edge grows to keep under the budget', () => {
  const s = [box([0, 0, 0], [100, 100, 100])]
  assert.equal(chooseEdge(s, s), diagonalOf(s) / 150)
  const L = chooseEdge(s, s, 5000)
  const f = subdivide(s, L)
  assert.ok(f.positions.length / 3 <= 5000, `${f.positions.length / 3} vertices`)
  assert.ok(f.positions.length / 3 > 1000, 'not far under it either')
})
