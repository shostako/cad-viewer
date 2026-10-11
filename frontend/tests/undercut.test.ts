/**
 * アンダーカットの候補 (src/undercut.ts) on shapes whose answer is known from
 * how they are made: a box, a slab hanging over a block (one part, and as two
 * parts), and the pull turned.
 *
 *   npm test        (frontend)
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import type { Surface } from '../src/compare.ts'
import { DOWN, UP, reachOf, undercutArea, type ReachPart } from '../src/undercut.ts'
import { UndercutView, reachText } from '../src/undercutview.ts'

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

/** two surfaces as one part */
function join(a: Surface, b: Surface): Surface {
  const off = a.positions.length / 3
  return {
    positions: Float32Array.from([...a.positions, ...b.positions]),
    normals: Float32Array.from([...a.normals, ...b.normals]),
    indices: Uint32Array.from([...a.indices, ...[...b.indices].map((i) => i + off)]),
  }
}

/** every vertex of a part with its normal and reach */
function* vertices(p: ReachPart): Generator<{ x: number; y: number; z: number; n: [number, number, number]; r: number }> {
  for (let i = 0; i < p.reach.length; i++) {
    yield { x: p.positions[3 * i], y: p.positions[3 * i + 1], z: p.positions[3 * i + 2], n: [p.normals[3 * i], p.normals[3 * i + 1], p.normals[3 * i + 2]], r: p.reach[i] }
  }
}

const near = (a: number, b: number) => Math.abs(a - b) < 1e-3
/** not on a line where the answer changes (those points may go either way) */
const clear = (v: number, ...lines: number[]) => lines.every((l) => Math.abs(v - l) > 1e-3)

test('a box: its top reached from above, its bottom from below, its sides from both', () => {
  const [p] = reachOf([box([0, 0, 0], [10, 10, 10])], [0, 0, 1]).parts
  let count = 0
  for (const v of vertices(p)) {
    const want = v.n[2] > 0.5 ? UP : v.n[2] < -0.5 ? DOWN : UP | DOWN
    assert.equal(v.r, want, `${[v.x, v.y, v.z]} n ${v.n}`)
    count++
  }
  assert.ok(count > 100)
})

const block = box([0, 0, 0], [10, 10, 10])
// a slab over the block, wider in x, narrower in y: its shadow on the block's top is x 0..10, y 2..8
const slab = box([-5, 2, 15], [15, 8, 17])

test("a slab over a block, one part: the block's top under it and its underside over the block are undercuts", () => {
  const [p] = reachOf([join(block, slab)], [0, 0, 1]).parts
  let under = 0, over = 0
  for (const v of vertices(p)) {
    if (!clear(v.x, 0, 10) || !clear(v.y, 2, 8)) continue
    const shadow = v.x > 0 && v.x < 10 && v.y > 2 && v.y < 8
    if (near(v.z, 10) && v.n[2] > 0.5) {
      // the block's top: from above unless the slab is over it
      assert.equal(v.r, shadow ? 0 : UP, `block top ${[v.x, v.y]}`)
      if (shadow) under++
    } else if (near(v.z, 15) && v.n[2] < -0.5) {
      // the slab's underside: from below unless the block is under it
      assert.equal(v.r, shadow ? 0 : DOWN, `slab underside ${[v.x, v.y]}`)
      if (shadow) over++
    }
  }
  assert.ok(under > 20 && over > 20, `${under} ${over}: the faces are cut finer, so the shadow has points`)
  // the shadow on each: 10 x 6
  const area = undercutArea(p)
  assert.ok(Math.abs(area - 120) < 12, `area ${area}`)
})

test('as two parts, neither blocks the other (each is molded on its own)', () => {
  const parts = reachOf([block, slab], [0, 0, 1]).parts
  for (const p of parts) for (const v of vertices(p)) assert.notEqual(v.r, 0, `${[v.x, v.y, v.z]}`)
  assert.equal(undercutArea(parts[0]) + undercutArea(parts[1]), 0)
})

test('the pull turned to x: the shadow is no undercut (the halves move along x)', () => {
  const [p] = reachOf([join(block, slab)], [1, 0, 0]).parts
  for (const v of vertices(p)) {
    if (near(v.z, 10) && v.n[2] > 0.5 && clear(v.x, 0, 10) && clear(v.y, 2, 8)) assert.equal(v.r, UP | DOWN, `block top ${[v.x, v.y]}`)
  }
})

test('the area counts the parts shown only', () => {
  // two parts, each a slab over a block (its own undercuts)
  const lifted = (s: Surface, dx: number): Surface => ({ ...s, positions: s.positions.map((v, i) => (i % 3 === 0 ? v + dx : v)) })
  const one = join(block, slab)
  const reach = reachOf([one, lifted(one, 40)], [0, 0, 1])
  const view = new UndercutView(reach, [7, 9])
  // (the two need not be equal to the last point: one on a shadow's edge may fall either way at another place)
  const [a7, a9] = reach.parts.map(undercutArea)
  assert.ok(a7 > 100 && a9 > 100)
  assert.ok(Math.abs(view.area(() => true) - (a7 + a9)) < 1e-9)
  assert.ok(Math.abs(view.area((id) => id !== 9) - a7) < 1e-9)
  assert.equal(view.area(() => false), 0)
})

test('under the cursor: the class of the corner nearest the point (a class does not blend)', () => {
  // one triangle, its corners of three classes; looked at from straight above
  const part: ReachPart = {
    positions: Float32Array.from([0, 0, 0, 10, 0, 0, 0, 10, 0]),
    normals: Float32Array.from([0, 0, 1, 0, 0, 1, 0, 0, 1]),
    indices: Uint32Array.from([0, 1, 2]),
    reach: Uint8Array.from([UP, 0, DOWN]),
  }
  const view = new UndercutView({ parts: [part], edges: [1] }, [1])
  view.build()
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 100)
  const at = (x: number, y: number) => {
    camera.position.set(x, y, 10)
    camera.lookAt(x, y, 0)
    camera.updateMatrixWorld()
    return view.valueAt(new THREE.Vector2(0, 0), camera)
  }
  assert.equal(at(8.5, 0.5), reachText(0), 'by the second corner')
  assert.equal(at(0.5, 8.5), reachText(DOWN), 'by the third')
  assert.equal(at(1, 1), reachText(UP), 'by the first')
  assert.equal(at(20, 20), null, 'off it')
})

test('a small part beside a large one, far off: its own resolution and its own offset (Codex on #102)', () => {
  // the slab over the block at 1/100 (a gap of 0.05 mm under the slab), and a 1 m box 10 m away
  const scale = (s: Surface, k: number): Surface => ({ ...s, positions: s.positions.map((v) => v * k) })
  const small = scale(join(block, slab), 0.01)
  const big = box([10000, 0, 0], [11000, 1000, 1000])
  const { parts, edges } = reachOf([small, big], [0, 0, 1])
  assert.ok(edges[0] < edges[1] / 1000, `${edges}`)
  // the shadows as at full size, scaled by 1/100 squared
  const area = undercutArea(parts[0])
  assert.ok(Math.abs(area - 0.012) < 0.0012, `area ${area}`)
  assert.equal(undercutArea(parts[1]), 0)
})
