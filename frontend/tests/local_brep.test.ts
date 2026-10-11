/**
 * The Web version's STEP/IGES (src/local/brep.ts, OpenCASCADE 8 in WebAssembly)
 * against the backend (tessellation.py, OCP 7.9), on testdata's B-rep files:
 * the same parts, names, colours, tree, file unit, face / edge / vertex
 * numbering and B-rep vertex points. The triangles may differ a little (two
 * OCCT versions mesh on their own), so their count and the display box are
 * compared within a margin.
 *
 *   npm test   (testdata/make_step_assembly.py, make_testdata.py and
 *               make_iges_loose.py first; the backend's venv: backend/.venv or CAD_VIEWER_PYTHON)
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createInstance } from 'libcascade/single/init'

import { LocalBackend, memoryStore } from '../src/local/backend.ts'
import { parseMeshPack } from '../src/meshpack.ts'
import { loadBrep } from '../src/local/brep.ts'
import { tracer } from './occt_tracer.ts'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const PYTHON = process.env.CAD_VIEWER_PYTHON ?? path.join(ROOT, 'backend', '.venv', 'bin', 'python')
const FILES = ['mini_mold.step', 'curved_part.step', 'inch_block.step', 'loose_faces_box.igs', 'named_parts.step'].map((f) => path.join(ROOT, 'testdata', f))
const present = FILES.filter((f) => fs.existsSync(f))
const ready = fs.existsSync(PYTHON) && present.length === FILES.length

const golden: Record<string, any> = ready
  ? JSON.parse(execFileSync(PYTHON, [path.join(ROOT, 'scripts', 'engine_golden.py'), ...FILES], { encoding: 'utf-8', maxBuffer: 1 << 28 }))
  : {}

const backend = new LocalBackend(memoryStore(), '0.0.0', () => createInstance())

for (const file of FILES) {
  test(`${path.basename(file)}: as the backend reads it`, { skip: !ready && 'no backend venv or testdata' }, async () => {
    const want = golden[file]
    assert.ok(want && !want.error, JSON.stringify(want))
    const up = await backend.handle('POST', '/api/models', { name: path.basename(file), bytes: new Uint8Array(fs.readFileSync(file)).buffer })
    assert.equal(up.status, 200, JSON.stringify(up.body))
    const meta = up.body as any
    assert.equal(meta.format, 'brep')
    assert.deepEqual(meta.tree, want.tree, 'the tree')
    assert.equal(meta.fileUnit, want.fileUnit, 'the file unit')
    const pack = parseMeshPack((await backend.handle('GET', `/api/models/${meta.id}/mesh.bin`)).body as ArrayBuffer)
    const header = pack.header as any
    assert.ok(Math.abs(header.deflection - want.deflection) <= 1e-9 * want.deflection, `deflection ${header.deflection} vs ${want.deflection}`)
    assert.equal(header.parts.length, want.parts.length, 'parts')
    for (const exp of want.parts) {
      const got = header.parts.find((p: any) => p.id === exp.id)
      const what = `part ${exp.id} (${exp.name})`
      assert.equal(got.name, exp.name, `${what}: name`)
      if (exp.color === null) assert.equal(got.color, null, `${what}: colour`)
      else got.color.forEach((c: number, i: number) => assert.ok(Math.abs(c - exp.color[i]) < 1e-6, `${what}: colour`))
      // the B-rep's numbering: the same faces and edges with triangles / segments
      assert.deepEqual(got.faceRanges.map((r: any) => r.faceId), exp.faceIds, `${what}: face ids`)
      assert.deepEqual(got.edgeRanges.map((r: any) => r.edgeId), exp.edgeIds, `${what}: edge ids`)
      // each edge's polyline starts and ends where the backend's does (a curve sampled over its whole range)
      const seg = pack.buffers[`p${exp.id}:edges`]
      got.edgeRanges.forEach((r: any, i: number) => {
        const a = [...seg.slice(6 * r.segStart, 6 * r.segStart + 3)]
        const b = [...seg.slice(6 * (r.segStart + r.segCount) - 3, 6 * (r.segStart + r.segCount))]
        const [ea, eb] = exp.edgeEnds[i]
        const near = (p: number[], q: number[]) => p.every((x, k) => Math.abs(x - q[k]) < 1e-3)
        assert.ok(near(a, ea) && near(b, eb), `${what}: edge ${r.edgeId} runs ${a} → ${b}, the backend's ${ea} → ${eb}`)
      })
      const vtx = pack.buffers[`p${exp.id}:vertices`]
      assert.equal(vtx.length / 3, exp.vertices, `${what}: vertices`)
      for (let i = 0; i < exp.vertices; i++) {
        for (let k = 0; k < 3; k++) assert.ok(Math.abs(vtx[3 * i + k] - exp.vertexPositions[i][k]) < 1e-4, `${what}: vertex ${i + 1}`)
      }
      // the triangles: each OCCT meshes on its own, within the same deflection
      const tris = pack.buffers[`p${exp.id}:indices`].length / 3
      assert.ok(Math.abs(tris - exp.triangles) <= Math.max(2, 0.25 * exp.triangles), `${what}: ${tris} triangles vs ${exp.triangles}`)
      if (exp.bbox) {
        const p = pack.buffers[`p${exp.id}:positions`]
        for (let k = 0; k < 3; k++) {
          let lo = Infinity, hi = -Infinity
          for (let i = k; i < p.length; i += 3) (lo = Math.min(lo, p[i])), (hi = Math.max(hi, p[i]))
          assert.ok(Math.abs(lo - exp.bbox[0][k]) <= 2 * want.deflection && Math.abs(hi - exp.bbox[1][k]) <= 2 * want.deflection, `${what}: box`)
        }
      }
      // the triangles face out of the solid (a reversed face's turned): the mesh's
      // signed volume is the backend's exact one, within the meshing's deflection;
      // and each node's normal is on its triangles' outer side
      const p = pack.buffers[`p${exp.id}:positions`], ix = pack.buffers[`p${exp.id}:indices`], nr = pack.buffers[`p${exp.id}:normals`]
      assert.equal(nr.length, p.length, `${what}: a normal per node`)
      const exact = want.properties.parts.find((q: any) => q.id === exp.id)
      if (exact?.volume) {
        let vol = 0
        let inward = 0
        for (let t = 0; t < ix.length; t += 3) {
          const [a, b, c] = [3 * ix[t], 3 * ix[t + 1], 3 * ix[t + 2]]
          const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2]
          const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2]
          const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
          vol += (p[a] * nx + p[a + 1] * ny + p[a + 2] * nz) / 6
          if (nx * nr[a] + ny * nr[a + 1] + nz * nr[a + 2] < 0) inward++
        }
        assert.ok(Math.abs(vol - exact.volume) <= 0.02 * exact.volume, `${what}: the mesh's volume ${vol} vs the B-rep's ${exact.volume}`)
        assert.ok(inward <= 0.01 * (ix.length / 3), `${what}: ${inward} triangles against their normals`)
      }
    }
  })
}

test('a model deleted: gone, its OpenCASCADE objects freed, the next one fine', { skip: !ready && 'no testdata' }, async () => {
  const be = new LocalBackend(memoryStore(), '0.0.0', () => createInstance())
  const bytes = () => new Uint8Array(fs.readFileSync(FILES[0])).buffer
  const a = (await be.handle('POST', '/api/models', { name: 'a.step', bytes: bytes() })).body as any
  assert.equal((await be.handle('DELETE', `/api/models/${a.id}`)).status, 200)
  assert.equal((await be.handle('GET', `/api/models/${a.id}/mesh.bin`)).status, 404)
  const b = await be.handle('POST', '/api/models', { name: 'a.step', bytes: bytes() })
  assert.equal(b.status, 200)
  assert.notEqual((b.body as any).id, a.id, 'read again, not the deleted one')
})

test('a STEP that is not one', async () => {
  const up = await backend.handle('POST', '/api/models', { name: 'bad.step', bytes: new TextEncoder().encode('not a step file').buffer })
  assert.equal(up.status, 422, JSON.stringify(up.body))
})

for (const file of FILES) {
  test(`${path.basename(file)}: a load leaves no OCCT object behind but the model's own`, { skip: !fs.existsSync(file) && 'no testdata' }, async () => {
    const T = tracer(await createInstance())
    const { meshes } = loadBrep(T.oc, new Uint8Array(fs.readFileSync(file)), path.basename(file))
    // the model's own: each part's shape and its face, edge and vertex maps
    const own = new Set(meshes.flatMap((m) => [m.part.shape, m.faceMap, m.edgeMap, m.vertexMap].map(T.raw)))
    assert.equal(own.size, 4 * meshes.length)
    const left = T.made.filter((o) => !o.isDeleted() && !own.has(o))
    assert.ok(T.made.length > 100, `the tracer saw ${T.made.length} objects: it must see what a load makes`)
    assert.equal(left.length, 0, `${left.length} of ${T.made.length} OCCT objects left: ${[...new Set(left.map((o) => o.constructor?.name))].join(', ')}`)
    // and the model's own alive (measurements use them)
    for (const o of own) assert.ok(!o.isDeleted(), `the model's ${o.constructor?.name} deleted`)
  })
}
