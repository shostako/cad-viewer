/**
 * The Web version's engine (src/local/) against the backend, on mesh files:
 * the same files read by both, the answers compared (the backend's by
 * scripts/engine_golden.py, which runs the routes' own code). Two separate
 * implementations (trimesh in Python; this, in TypeScript): each is the
 * other's oracle.
 *
 *   npm test        (frontend; the backend's venv is needed: backend/.venv, or CAD_VIEWER_PYTHON)
 *
 * The files are made here: known shapes in every format the Web version reads,
 * and testdata/ribbed_plate.stl when it is there (testdata/make_testdata.py).
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { zipSync } from 'three/examples/jsm/libs/fflate.module.js'

import { LocalBackend, memoryStore } from '../src/local/backend.ts'
import { parseMeshPack } from '../src/meshpack.ts'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const PYTHON = process.env.CAD_VIEWER_PYTHON ?? path.join(ROOT, 'backend', '.venv', 'bin', 'python')

type V = [number, number, number]
type Tri = [V, V, V]

// ---- shapes (faces wound counter-clockwise from outside) -----------------------

function box(lo: V, hi: V): Tri[] {
  const [x0, y0, z0] = lo, [x1, y1, z1] = hi
  const c = (i: number): V => [i & 1 ? x1 : x0, i & 2 ? y1 : y0, i & 4 ? z1 : z0]
  const quads = [
    [0, 2, 3, 1], [4, 5, 7, 6], // z0, z1
    [0, 1, 5, 4], [2, 6, 7, 3], // y0, y1
    [0, 4, 6, 2], [1, 3, 7, 5], // x0, x1
  ]
  return quads.flatMap(([a, b, cc, d]) => [[c(a), c(b), c(cc)], [c(a), c(cc), c(d)]] as Tri[])
}

const flip = (tris: Tri[]): Tri[] => tris.map(([a, b, c]) => [a, c, b])

/** a prism over an n-gon (smooth sides, flat caps) */
function prism(n: number, r: number, h: number): Tri[] {
  const ring = (z: number) => Array.from({ length: n }, (_, i): V => [r * Math.cos((2 * Math.PI * i) / n), r * Math.sin((2 * Math.PI * i) / n), z])
  const lo = ring(0), hi = ring(h)
  const out: Tri[] = []
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    out.push([lo[i], lo[j], hi[j]], [lo[i], hi[j], hi[i]])
    out.push([[0, 0, 0], lo[j], lo[i]], [[0, 0, h], hi[i], hi[j]])
  }
  return out
}

/** a polygon (counter-clockwise, star-shaped from its first corner) extruded from z 0 to h */
function extrude(poly: [number, number][], h: number): Tri[] {
  const out: Tri[] = []
  const at = (i: number, z: number): V => [poly[i][0], poly[i][1], z]
  for (let i = 1; i + 1 < poly.length; i++) {
    out.push([at(0, 0), at(i + 1, 0), at(i, 0)], [at(0, h), at(i, h), at(i + 1, h)])
  }
  for (let i = 0; i < poly.length; i++) {
    const j = (i + 1) % poly.length
    out.push([at(i, 0), at(j, 0), at(j, h)], [at(i, 0), at(j, h), at(i, h)])
  }
  return out
}

/** a UV sphere (all smooth) */
function sphere(r: number, nu: number, nv: number): Tri[] {
  const p = (u: number, v: number): V => {
    const th = (Math.PI * v) / nv, ph = (2 * Math.PI * u) / nu
    return [r * Math.sin(th) * Math.cos(ph), r * Math.sin(th) * Math.sin(ph), r * Math.cos(th)]
  }
  const out: Tri[] = []
  for (let v = 0; v < nv; v++) {
    for (let u = 0; u < nu; u++) {
      const a = p(u, v), b = p(u, v + 1), c = p(u + 1, v + 1), d = p(u + 1, v)
      if (v > 0) out.push([a, b, d])
      if (v < nv - 1) out.push([b, c, d])
    }
  }
  return out
}

// ---- writers ---------------------------------------------------------------------

/** shared vertices and indices of a triangle list */
function indexed(tris: Tri[]): { v: V[]; f: number[][] } {
  const v: V[] = []
  const seen = new Map<string, number>()
  const f = tris.map((t) =>
    t.map((p) => {
      const k = p.join(',')
      let i = seen.get(k)
      if (i === undefined) {
        i = v.length
        seen.set(k, i)
        v.push(p)
      }
      return i
    }),
  )
  return { v, f }
}

function stlBinary(tris: Tri[]): Uint8Array {
  const b = new ArrayBuffer(84 + 50 * tris.length)
  const d = new DataView(b)
  d.setUint32(80, tris.length, true)
  tris.forEach((t, i) => t.forEach((p, k) => p.forEach((x, j) => d.setFloat32(84 + 50 * i + 12 + 12 * k + 4 * j, x, true))))
  return new Uint8Array(b)
}

const stlText = (tris: Tri[]) =>
  `solid s\n${tris.map((t) => ` facet normal 0 0 0\n  outer loop\n${t.map((p) => `   vertex ${p.join(' ')}`).join('\n')}\n  endloop\n endfacet`).join('\n')}\nendsolid s\n`

function obj(tris: Tri[]): string {
  const { v, f } = indexed(tris)
  // negative indices (from the end) for every other face
  return `${v.map((p) => `v ${p.join(' ')}`).join('\n')}\n${f.map((t, i) => `f ${t.map((k) => (i % 2 ? k - v.length : k + 1) + '/1').join(' ')}`).join('\n')}\n`
}

function plyText(tris: Tri[]): string {
  const { v, f } = indexed(tris)
  return `ply\nformat ascii 1.0\nelement vertex ${v.length}\nproperty float x\nproperty float y\nproperty float z\nelement face ${f.length}\nproperty list uchar int vertex_indices\nend_header\n${v.map((p) => p.join(' ')).join('\n')}\n${f.map((t) => `3 ${t.join(' ')}`).join('\n')}\n`
}

function plyBinary(tris: Tri[]): Uint8Array {
  const { v, f } = indexed(tris)
  const head = new TextEncoder().encode(
    `ply\nformat binary_little_endian 1.0\nelement vertex ${v.length}\nproperty double x\nproperty double y\nproperty double z\nproperty uchar red\nelement face ${f.length}\nproperty list uchar uint vertex_indices\nend_header\n`,
  )
  const body = new DataView(new ArrayBuffer(v.length * 25 + f.length * 13))
  let at = 0
  for (const p of v) {
    for (const x of p) (body.setFloat64(at, x, true), (at += 8))
    body.setUint8(at++, 200)
  }
  for (const t of f) {
    body.setUint8(at++, 3)
    for (const k of t) (body.setUint32(at, k, true), (at += 4))
  }
  const out = new Uint8Array(head.byteLength + body.byteLength)
  out.set(head)
  out.set(new Uint8Array(body.buffer), head.byteLength)
  return out
}

function off(tris: Tri[]): string {
  const { v, f } = indexed(tris)
  return `OFF\n# a comment\n${v.length} ${f.length} 0\n${v.map((p) => p.join(' ')).join('\n')}\n${f.map((t) => `3 ${t.join(' ')}`).join('\n')}\n`
}

/** a 3MF: the first shape an object placed by its build item's transform, the second inside a components object;
 * quote: the attributes' quotes (XML allows both) */
function threeMf(a: Tri[], b: Tri[], quote = '"'): Uint8Array {
  const mesh = (id: number, tris: Tri[]) => {
    const { v, f } = indexed(tris)
    return `<object id="${id}" type="model"><mesh><vertices>${v.map((p) => `<vertex x="${p[0]}" y="${p[1]}" z="${p[2]}"/>`).join('')}</vertices><triangles>${f.map((t) => `<triangle v1="${t[0]}" v2="${t[1]}" v3="${t[2]}"/>`).join('')}</triangles></mesh></object>`
  }
  const model = `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>${mesh(1, a)}${mesh(2, b)}<object id="3" type="model"><components><component objectid="2" transform="1 0 0 0 0 1 0 -1 0 0 0 30"/></components></object></resources>
<build><item objectid="1" transform="0 1 0 -1 0 0 0 0 1 5 6 7"/><item objectid="3" transform="0 0 1 0 1 0 -1 0 0 100 0 0"/></build></model>`
  const enc = (s: string) => new TextEncoder().encode(quote === '"' ? s : s.replace(/="([^"]*)"/g, "='$1'"))
  return zipSync({
    '[Content_Types].xml': enc('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'),
    '_rels/.rels': enc('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'),
    '3D/3dmodel.model': enc(model),
  })
}

// ---- faces of more than three corners (#87; backend/tests/test_polygons.py has the same shapes) ----

type Faces = { v: V[]; f: number[][] }
type Poly = [number, number][]

/** an L of area 64, from a corner that does not see the far end of the L (the fan from it is wrong) */
const L_POLY: Poly = [[10, 4], [4, 4], [4, 10], [0, 10], [0, 0], [10, 0]]
/** a comb of four slots (area 9 x 5 - 4 x 4), from a slot's bottom corner */
const COMB: Poly = [[1, 1], [1, 5], [0, 5], [0, 0], [9, 0], [9, 5], [8, 5], [8, 1], [7, 1], [7, 5], [6, 5], [6, 1], [5, 1], [5, 5], [4, 5], [4, 1], [3, 1], [3, 5], [2, 5], [2, 1]]
/** a 10 x 10 square with a 4 x 4 hole joined to the outside by a cut (its ends twice, at the same places) */
const BRIDGED: Poly = [[0, 5], [0, 0], [10, 0], [10, 10], [0, 10], [0, 5], [3, 5], [3, 7], [7, 7], [7, 3], [3, 3], [3, 5]]
/** the L from its first outer corner: concave, but the fan is right */
const STAR: Poly = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]]

/** a prism over a counter-clockwise polygon: each cap one face from the polygon's
 * first corner (the bottom turned over), the walls quads (skip: walls left out) */
function prismFaces(poly: Poly, h: number, skip: (i: number, j: number) => boolean = () => false): Faces {
  const n = poly.length
  const v: V[] = [...poly.map(([x, y]): V => [x, y, 0]), ...poly.map(([x, y]): V => [x, y, h])]
  const f: number[][] = [[0, ...Array.from({ length: n - 1 }, (_, i) => n - 1 - i)], Array.from({ length: n }, (_, i) => n + i)]
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    if (!skip(i, j)) f.push([i, j, n + j, n + i])
  }
  return { v, f }
}

/** turned about the x axis (a > 0) or the y axis (a < 0) by |a|: the caps' normals' largest axis is then y or x */
const tilt = ({ v, f }: Faces, a: number): Faces => {
  const c = Math.cos(Math.abs(a)), s = Math.sin(Math.abs(a))
  return { v: v.map(([x, y, z]): V => (a > 0 ? [x, y * c - z * s, y * s + z * c] : [x * c + z * s, y, -x * s + z * c])), f }
}

const objFaces = ({ v, f }: Faces) => `${v.map((p) => `v ${p.join(' ')}`).join('\n')}\n${f.map((t) => `f ${t.map((k) => k + 1).join(' ')}`).join('\n')}\n`
const offFaces = ({ v, f }: Faces) => `OFF\n${v.length} ${f.length} 0\n${v.map((p) => p.join(' ')).join('\n')}\n${f.map((t) => `${t.length} ${t.join(' ')}`).join('\n')}\n`
const plyHead = (fmt: string, { v, f }: Faces) =>
  `ply\nformat ${fmt} 1.0\nelement vertex ${v.length}\nproperty double x\nproperty double y\nproperty double z\nelement face ${f.length}\nproperty list uchar int vertex_indices\nend_header\n`
const plyFacesText = (m: Faces) => `${plyHead('ascii', m)}${m.v.map((p) => p.join(' ')).join('\n')}\n${m.f.map((t) => `${t.length} ${t.join(' ')}`).join('\n')}\n`
function plyFacesBinary(m: Faces): Uint8Array {
  const head = new TextEncoder().encode(plyHead('binary_little_endian', m))
  const body = new DataView(new ArrayBuffer(m.v.length * 24 + m.f.reduce((s, t) => s + 1 + 4 * t.length, 0)))
  let at = 0
  for (const p of m.v) for (const x of p) (body.setFloat64(at, x, true), (at += 8))
  for (const t of m.f) {
    body.setUint8(at++, t.length)
    for (const k of t) (body.setInt32(at, k, true), (at += 4))
  }
  const out = new Uint8Array(head.byteLength + body.byteLength)
  out.set(head)
  out.set(new Uint8Array(body.buffer), head.byteLength)
  return out
}
const alongCut = (i: number, j: number) => (i === 5 && j === 6) || (i === 11 && j === 0)

// ---- the files and the comparison -----------------------------------------------

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cad-viewer-engine-'))
const files: Record<string, Uint8Array | string> = {
  'box.stl': stlBinary(box([0, 0, 0], [2, 3, 4])),
  'box_text.stl': stlText(box([-1, -2, -3], [4, 5, 6])),
  'cavity.stl': stlBinary([...box([0, 0, 0], [10, 10, 10]), ...flip(box([3, 3, 3], [7, 7, 7]))]),
  'two_bodies.stl': stlBinary([...box([0, 0, 0], [1, 1, 1]), ...box([5, 0, 0], [7, 2, 2])]),
  'inside_out.stl': stlBinary(flip(box([0, 0, 0], [3, 3, 3]))),
  'open.stl': stlBinary(box([0, 0, 0], [3, 3, 3]).slice(1)),
  'mixed_winding.stl': stlBinary((() => { const b = box([0, 0, 0], [3, 3, 3]); b[3] = flip([b[3]])[0]; return b })()),
  // two separate boxes, the small one inside out: not inside the other, so material too
  'separate_flipped.stl': stlBinary([...box([0, 0, 0], [4, 4, 4]), ...flip(box([10, 1, 1], [12, 3, 3]))]),
  // an L, and a small box inside out in its notch: within the L's bounds but
  // not inside it, so material too (only the ray test, not the bounds, tells)
  'notch.stl': stlBinary([...extrude([[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]], 3), ...flip(box([6, 6, 1], [8, 8, 2]))]),
  'prism.obj': obj(prism(32, 5, 8)),
  // 10 sides: 36 degrees apart, over the 30 of a smooth surface
  'decagon.stl': stlBinary(prism(10, 4, 3)),
  'sphere.ply': plyText(sphere(4, 24, 12)),
  // 13 sides: 27.7 degrees apart, off the 30-degree edge (at exactly 30, the
  // last bit of the two arccos decides, differently in numpy and in JS)
  'prism_binary.ply': plyBinary(prism(13, 3, 2)),
  'box.off': off(box([0, 0, 0], [1, 2, 3])),
  'parts.3mf': threeMf(box([0, 0, 0], [2, 3, 4]), prism(16, 2, 3)),
  'single_quotes.3mf': threeMf(box([0, 0, 0], [3, 2, 1]), prism(12, 1, 2), "'"),
  // faces of more than three corners, cut along their shape (#87). trimesh does
  // not read the OFF and the binary PLY (different corner counts): the backend
  // reads those as meshload.ts does
  'l_prism.obj': objFaces(prismFaces(L_POLY, 3)),
  'l_prism.off': offFaces(prismFaces(L_POLY, 3)),
  'l_prism.ply': plyFacesText(prismFaces(L_POLY, 3)),
  'l_prism_binary.ply': plyFacesBinary(prismFaces(L_POLY, 3)),
  'comb.obj': objFaces(prismFaces(COMB, 2)),
  'comb_binary.ply': plyFacesBinary(prismFaces(COMB, 2)),
  'hole_cut.obj': objFaces(prismFaces(BRIDGED, 2, alongCut)),
  'hole_cut.off': offFaces(prismFaces(BRIDGED, 2, alongCut)),
  'star.obj': objFaces(prismFaces(STAR, 3)),
  'tilted_x.obj': objFaces(tilt(prismFaces(COMB, 2), 1.1)),
  'tilted_y.ply': plyFacesText(tilt(prismFaces(L_POLY, 3), -1.1)),
  // one face that crosses itself: no ear, a fan
  'bowtie.obj': 'v 0 0 0\nv 4 4 0\nv 4 0 0\nv 0 4 0\nf 1 2 3 4\n',
}
for (const [name, data] of Object.entries(files)) fs.writeFileSync(path.join(dir, name), data)
const paths = Object.keys(files).map((n) => path.join(dir, n))
const ribbed = path.join(ROOT, 'testdata', 'ribbed_plate.stl')
if (fs.existsSync(ribbed)) paths.push(ribbed)

const hasPython = fs.existsSync(PYTHON)
const golden: Record<string, any> = hasPython
  ? JSON.parse(execFileSync(PYTHON, [path.join(ROOT, 'scripts', 'engine_golden.py'), ...paths], { encoding: 'utf-8', maxBuffer: 1 << 26 }))
  : {}

function close(a: number, b: number, rel: number, what: string): void {
  assert.ok(Math.abs(a - b) <= rel * Math.max(1, Math.abs(a), Math.abs(b)), `${what}: ${a} vs ${b}`)
}

for (const file of paths) {
  test(`${path.basename(file)}: as the backend reads it`, { skip: !hasPython && 'no backend venv (CAD_VIEWER_PYTHON)' }, async () => {
    const want = golden[file]
    assert.ok(want && !want.error, `the backend: ${JSON.stringify(want)}`)
    const be = new LocalBackend(memoryStore(), '0.0.0')
    const up = await be.handle('POST', '/api/models', { name: path.basename(file), bytes: new Uint8Array(fs.readFileSync(file)).buffer })
    assert.equal(up.status, 200, JSON.stringify(up.body))
    const meta = up.body as any
    // the display mesh: the same vertices split along the same sharp edges
    assert.equal(meta.triangleCount, want.triangleCount, 'triangles')
    assert.equal(meta.vertexCount, want.vertexCount, 'vertices of the display mesh')
    for (const k of ['min', 'max'] as const) for (let i = 0; i < 3; i++) close(meta.bbox[k][i], want.bbox[k][i], 1e-6, `bbox ${k}`)
    // the same vertices with the same normals (the order is each engine's own)
    const pack = parseMeshPack((await be.handle('GET', `/api/models/${meta.id}/mesh.bin`)).body as ArrayBuffer)
    const pos = pack.buffers['p0:positions'], nrm = pack.buffers['p0:normals']
    const r4 = (x: number) => Math.round(x * 1e4) / 1e4 + 0 // + 0: no -0
    const mine = Array.from({ length: pos.length / 3 }, (_, i) => [...pos.slice(3 * i, 3 * i + 3), ...nrm.slice(3 * i, 3 * i + 3)].map(r4))
    const order = (a: number[], b: number[]) => { for (let k = 0; k < 6; k++) if (a[k] !== b[k]) return a[k] - b[k]; return 0 }
    mine.sort(order)
    const theirs = (want.vertices as number[][]).map((v) => v.map(r4)).sort(order)
    let off = 0
    for (let i = 0; i < mine.length; i++) if (mine[i].some((x, k) => Math.abs(x - theirs[i][k]) > 2e-4)) off++
    assert.equal(off, 0, `${off} of ${mine.length} vertices or their normals differ, e.g. ${JSON.stringify(mine.find((v, i) => v.some((x, k) => Math.abs(x - theirs[i][k]) > 2e-4)))}`)
    // the same triangles (how a face of more than three corners is cut, #87):
    // each from its least corner, the turn kept, as engine_golden.py's triangles
    const idx = pack.buffers['p0:indices']
    const tris: number[][] = []
    for (let t = 0; t < idx.length; t += 3) {
      const tri = [0, 1, 2].map((k) => [0, 1, 2].map((j) => r4(pos[3 * idx[t + k] + j])))
      let least = 0
      for (let k = 1; k < 3; k++) if (order([...tri[k], 0, 0, 0], [...tri[least], 0, 0, 0]) < 0) least = k
      tris.push([...tri.slice(least), ...tri.slice(0, least)].flat())
    }
    const byCorners = (a: number[], b: number[]) => { for (let k = 0; k < 9; k++) if (a[k] !== b[k]) return a[k] - b[k]; return 0 }
    tris.sort(byCorners)
    const wantTris = (want.triangles as number[][][]).map((t) => t.flat()).sort(byCorners)
    assert.equal(tris.length, wantTris.length, 'triangles')
    const differ = tris.findIndex((t, i) => t.some((x, k) => Math.abs(x - wantTris[i][k]) > 2e-4))
    assert.equal(differ, -1, `triangle ${differ} differs: ${JSON.stringify(tris[differ])} vs ${JSON.stringify(wantTris[differ])}`)
    const props = (await be.handle('GET', `/api/models/${meta.id}/properties`)).body as any
    const [got, exp] = [props.parts[0], want.properties.parts[0]]
    assert.equal(got.closed, exp.closed, 'closed')
    assert.equal(got.reason, exp.reason, 'reason')
    for (const k of ['volume', 'area'] as const) {
      if (exp[k] === null) assert.equal(got[k], null, k)
      else close(got[k], exp[k], 1e-9, k)
    }
    if (exp.centerOfMass) for (let i = 0; i < 3; i++) close(got.centerOfMass[i], exp.centerOfMass[i], 1e-9, 'centre of mass')
    else assert.equal(got.centerOfMass, null)
    close(props.total.volume ?? 0, want.properties.total.volume ?? 0, 1e-9, 'total volume')
  })
}

test('known values (no backend needed)', async () => {
  const be = new LocalBackend(memoryStore(), '0.0.0')
  const read = async (name: string) => {
    const up = await be.handle('POST', '/api/models', { name, bytes: new Uint8Array(fs.readFileSync(path.join(dir, name))).buffer })
    return (await be.handle('GET', `/api/models/${(up.body as any).id}/properties`)).body as any
  }
  close((await read('box.stl')).total.volume, 24, 1e-9, 'a 2 x 3 x 4 box')
  close((await read('cavity.stl')).total.volume, 1000 - 64, 1e-9, 'a 10 box less a 4 box inside')
  close((await read('two_bodies.stl')).total.volume, 1 + 8, 1e-9, 'two boxes')
  close((await read('separate_flipped.stl')).total.volume, 64 + 8, 1e-9, 'two boxes apart, one inside out')
  close((await read('notch.stl')).total.volume, (100 - 36) * 3 + 4, 1e-9, 'an L and a box in its notch')
  close((await read('inside_out.stl')).total.volume, 27, 1e-9, 'a box turned inside out')
  assert.equal((await read('open.stl')).parts[0].reason, 'open')
  // faces of more than three corners cut along their shape (#87): the fan from
  // the first corner has the volume right too (its triangles out of the face
  // cancel), but not the area
  const perimeter = (p: Poly) => p.reduce((s, [x, y], i) => s + Math.hypot(p[(i + 1) % p.length][0] - x, p[(i + 1) % p.length][1] - y), 0)
  for (const [name, area, h, poly] of [
    ['l_prism.obj', 64, 3, L_POLY], ['l_prism.off', 64, 3, L_POLY], ['l_prism.ply', 64, 3, L_POLY], ['l_prism_binary.ply', 64, 3, L_POLY],
    ['comb.obj', 29, 2, COMB], ['comb_binary.ply', 29, 2, COMB], ['tilted_x.obj', 29, 2, COMB], ['tilted_y.ply', 64, 3, L_POLY],
    ['star.obj', 64, 3, STAR],
  ] as [string, number, number, Poly][]) {
    const p = (await read(name)).parts[0]
    // the values come from the display mesh's float32 positions: off the grid (tilted), to 1e-7 or so
    const rel = name.startsWith('tilted') ? 1e-6 : 1e-9
    close(p.volume, area * h, rel, `${name}: volume`)
    close(p.area, 2 * area + h * perimeter(poly), rel, `${name}: area`)
  }
  for (const name of ['hole_cut.obj', 'hole_cut.off']) close((await read(name)).total.volume, 84 * 2, 1e-9, `${name}: volume`)
  assert.equal((await read('mixed_winding.stl')).parts[0].reason, 'winding')
})

test('the routes: sidecars by content, errors as the backend says them', async () => {
  const store = memoryStore()
  const be = new LocalBackend(store, '1.2.3')
  assert.deepEqual((await be.handle('GET', '/api/health')).body, { status: 'ok', app: 'cad-viewer', version: '1.2.3', engine: 'local' })
  const bytes = () => new Uint8Array(fs.readFileSync(path.join(dir, 'box.stl'))).buffer
  const a = (await be.handle('POST', '/api/models', { name: 'a.stl', bytes: bytes() })).body as any
  assert.deepEqual((await be.handle('GET', `/api/models/${a.id}/sidecar`)).body, {}, 'none saved yet')
  await be.handle('PUT', `/api/models/${a.id}/sidecar`, { version: 1, entries: [{ text: '注記' }] })
  // the same bytes under another name: the same sidecar (keyed by content), another model
  const b = (await be.handle('POST', '/api/models', { name: 'b.stl', bytes: bytes() })).body as any
  assert.notEqual(b.id, a.id)
  assert.equal(b.hash, a.hash)
  assert.deepEqual((await be.handle('GET', `/api/models/${b.id}/sidecar`)).body, { version: 1, entries: [{ text: '注記' }] })
  // the same name and bytes again: the same model
  assert.equal(((await be.handle('POST', '/api/models', { name: 'a.stl', bytes: bytes() })).body as any).id, a.id)
  const mesh = await be.handle('GET', `/api/models/${a.id}/mesh.bin`)
  assert.equal(mesh.kind, 'binary')
  assert.equal((await be.handle('POST', `/api/models/${a.id}/measure`, { type: 'distance' })).status, 422)
  assert.equal((await be.handle('GET', '/api/models/nope/mesh.bin')).status, 404)
  assert.equal((await be.handle('POST', '/api/models', { name: 'x.xyz', bytes: bytes() })).status, 415)
  assert.equal((await be.handle('POST', '/api/models', { name: 'bad.stl', bytes: new TextEncoder().encode('hello').buffer })).status, 422)
  assert.equal((await be.handle('POST', '/api/models', { name: 'empty.stl', bytes: new ArrayBuffer(0) })).status, 400)
})
