/**
 * The Web version's exact measurements and B-rep volumes (src/local/measure.ts,
 * brepprops.ts; OpenCASCADE 8 in WebAssembly) against the backend's
 * (measure.py, properties.py; OCP 7.9) on testdata's B-rep models: the same
 * requests (scripts/engine_golden.py makes them over every face, edge and
 * vertex, and asks the backend), the same answers. Errors as 422 with the
 * backend's own words.
 *
 * Numbers agree within 1e-6 mm (two OCCT versions, the same geometry), the
 * dimension line's ends too: on these models every shortest distance's ends
 * stand where the backend's do (a minimum reached at many places is put
 * through the clicks, or is BRepExtrema's same first solution). Not the
 * largest distance of a circle and itself: every diameter is one, and which
 * one the search ends on follows the last bit of the sampled distances (the
 * value must agree, and the ends be that far apart).
 *
 *   npm test   (testdata first; the backend's venv: backend/.venv or CAD_VIEWER_PYTHON)
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createInstance } from 'libcascade/single/init'

import { LocalBackend, memoryStore } from '../src/local/backend.ts'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const PYTHON = process.env.CAD_VIEWER_PYTHON ?? path.join(ROOT, 'backend', '.venv', 'bin', 'python')
const FILES = ['mini_mold.step', 'curved_part.step', 'inch_block.step', 'loose_faces_box.igs', 'named_parts.step'].map((f) => path.join(ROOT, 'testdata', f))
const ready = fs.existsSync(PYTHON) && FILES.every((f) => fs.existsSync(f))
const golden: Record<string, any> = ready
  ? JSON.parse(execFileSync(PYTHON, [path.join(ROOT, 'scripts', 'engine_golden.py'), ...FILES], { encoding: 'utf-8', maxBuffer: 1 << 28 }))
  : {}
const backend = new LocalBackend(memoryStore(), '0.0.0', () => createInstance())

const TOL = 1e-6

/** the differences between two answers (paths), numbers within TOL */
function diff(got: any, want: any, at = ''): string[] {
  if (typeof want === 'number') return typeof got === 'number' && Math.abs(got - want) <= TOL * Math.max(1, Math.abs(want)) ? [] : [`${at}: ${got} vs ${want}`]
  if (Array.isArray(want)) {
    if (!Array.isArray(got) || got.length !== want.length) return [`${at}: ${JSON.stringify(got)} vs ${JSON.stringify(want)}`]
    return want.flatMap((w, i) => diff(got[i], w, `${at}[${i}]`))
  }
  if (want && typeof want === 'object') {
    if (!got || typeof got !== 'object') return [`${at}: ${JSON.stringify(got)} vs an object`]
    const keys = new Set([...Object.keys(want), ...Object.keys(got)])
    return [...keys].flatMap((k) => (k in want ? (k in got ? diff(got[k], want[k], `${at}.${k}`) : [`${at}.${k}: missing`]) : [`${at}.${k}: not the backend's`]))
  }
  return got === want ? [] : [`${at}: ${JSON.stringify(got)} vs ${JSON.stringify(want)}`]
}

for (const file of FILES) {
  test(`${path.basename(file)}: the measurements and the volume as the backend's`, { skip: !ready && 'no backend venv or testdata' }, async () => {
    const want = golden[file]
    assert.ok(want && !want.error, JSON.stringify(want))
    const up = await backend.handle('POST', '/api/models', { name: path.basename(file), bytes: new Uint8Array(fs.readFileSync(file)).buffer })
    assert.equal(up.status, 200, JSON.stringify(up.body))
    const id = (up.body as any).id
    const problems: string[] = []
    let tied = 0
    for (const { request, answer, error } of want.measures) {
      const got = await backend.handle('POST', `/api/models/${id}/measure`, request)
      const what = JSON.stringify(request)
      if (error !== undefined) {
        if (got.status !== 422 || (got.body as any).detail !== error) problems.push(`${what}: ${got.status} ${JSON.stringify(got.body)}, the backend's 422 ${error}`)
        continue
      }
      if (got.status !== 200) {
        problems.push(`${what}: ${got.status} ${JSON.stringify(got.body)}`)
        continue
      }
      let d = diff(got.body, answer)
      const g = got.body as any
      if (d.length && request.mode === 'max' && !d.some((x) => !/^\.(pointA|pointB|delta)/.test(x))) {
        const len = Math.hypot(g.pointB[0] - g.pointA[0], g.pointB[1] - g.pointA[1], g.pointB[2] - g.pointA[2])
        if (Math.abs(len - answer.value) <= TOL) (d = []), tied++
      }
      if (d.length) problems.push(`${what}: ${d.slice(0, 4).join('; ')}`)
    }
    assert.equal(problems.length, 0, `${problems.length} of ${want.measures.length} differ:\n${problems.slice(0, 12).join('\n')}`)
    // a few ties only (a circle with itself), not a search that ends elsewhere in general
    assert.ok(tied <= 4, `${tied} largest distances with their ends elsewhere`)

    const props = (await backend.handle('GET', `/api/models/${id}/properties`)).body
    const pd = diff(props, want.properties)
    assert.equal(pd.length, 0, `the properties differ: ${pd.slice(0, 6).join('; ')}`)
  })
}

test('B-rep volumes, known values (no backend needed): turned over, open, two bodies', async () => {
  const { brepPartProperties } = await import('../src/local/brepprops.ts')
  const oc: any = await createInstance()
  const box = (x: number, y: number, z: number, at = [0, 0, 0]) =>
    new oc.BRepPrimAPI_MakeBox(new oc.gp_Pnt(at[0], at[1], at[2]), x, y, z).Shape()
  const p = brepPartProperties(oc, box(10, 20, 30))
  assert.ok(p.closed && Math.abs(p.volume! - 6000) < 1e-6 && Math.abs(p.area! - 2200) < 1e-6, JSON.stringify(p))
  assert.deepEqual(p.centerOfMass!.map((c) => Math.round(c * 1e6) / 1e6), [5, 10, 15])
  // a solid turned inside out: the same volume, not a negative one
  const r = brepPartProperties(oc, box(10, 20, 30).Reversed())
  assert.ok(r.closed && Math.abs(r.volume! - 6000) < 1e-6, JSON.stringify(r))
  // a box's faces but one: an open shell, no volume
  const faces: any[] = []
  const ex = new oc.TopExp_Explorer(box(10, 10, 10), oc.TopAbs_ShapeEnum.TopAbs_FACE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE)
  for (; ex.More(); ex.Next()) faces.push(ex.Current())
  const sewing = new oc.BRepBuilderAPI_Sewing(1e-6, true, true, true, false)
  for (const f of faces.slice(1)) sewing.Add(f)
  sewing.Perform(new oc.Message_ProgressRange())
  const open = brepPartProperties(oc, sewing.SewedShape())
  assert.equal(open.reason, 'open', JSON.stringify(open))
  assert.equal(open.volume, null)
  // two boxes in one part: summed, the centre of mass between them by volume
  const builder = new oc.BRep_Builder()
  const both = new oc.TopoDS_Compound()
  builder.MakeCompound(both)
  builder.Add(both, box(10, 10, 10))
  builder.Add(both, box(10, 10, 10, [100, 0, 0]))
  const two = brepPartProperties(oc, both)
  assert.ok(Math.abs(two.volume! - 2000) < 1e-6 && Math.abs(two.centerOfMass![0] - 55) < 1e-6, JSON.stringify(two))
  // faces only: none (curves or points only)
  assert.equal(brepPartProperties(oc, new oc.BRepBuilderAPI_MakeVertex(new oc.gp_Pnt(1, 2, 3)).Vertex()).reason, 'no_faces')
})

/**
 * the OCCT objects a calculation gets hold of, for the leak check: oc wrapped,
 * every object that comes out of a constructor or a call recorded (what the
 * model keeps is wrapped by own(), and not recorded). The calculation sees
 * wrappers; OCCT sees the objects themselves.
 */
function tracer(oc: any) {
  const made: any[] = []
  const raw = new WeakMap<object, any>()
  const unwrap = (v: any) => (v !== null && typeof v === 'object' && raw.has(v) ? raw.get(v) : v)
  const wrapObject = (t: any, record: boolean): any => {
    if (record) made.push(t)
    const px = new Proxy(t, {
      get(target, prop) {
        const v = target[prop]
        if (typeof v !== 'function') return v
        if (prop === 'delete' || prop === 'isDeleted') return v.bind(target)
        return (...args: any[]) => out(v.apply(target, args.map(unwrap)))
      },
    })
    raw.set(px, t)
    return px
  }
  const out = (v: any) => (v !== null && typeof v === 'object' && typeof v.delete === 'function' ? wrapObject(v, true) : v)
  const wrapFunction = (f: any): any =>
    new Proxy(f, {
      construct: (target, args) => out(new target(...args.map(unwrap))),
      apply: (target, self, args) => out(target.apply(self, args.map(unwrap))),
      get: (target, prop) => (typeof target[prop] === 'function' ? wrapFunction(target[prop]) : target[prop]),
    })
  const wrapped = new Proxy(oc, { get: (target, prop) => (typeof target[prop] === 'function' ? wrapFunction(target[prop]) : target[prop]) })
  return { oc: wrapped, own: (t: any) => wrapObject(t, false), made }
}

for (const file of FILES.filter((f) => !f.endsWith('.igs'))) {
  test(`${path.basename(file)}: each measurement and the properties leave no OCCT object behind`, { skip: !ready && 'no backend venv or testdata' }, async () => {
    const { loadBrep } = await import('../src/local/brep.ts')
    const { Measurer, MeasureError } = await import('../src/local/measure.ts')
    const { brepPartProperties } = await import('../src/local/brepprops.ts')
    const oc: any = await createInstance()
    const { meshes } = loadBrep(oc, new Uint8Array(fs.readFileSync(file)), path.basename(file))
    const T = tracer(oc)
    const own = meshes.map((m) => ({
      ...m,
      part: { ...m.part, shape: T.own(m.part.shape) },
      faceMap: T.own(m.faceMap),
      edgeMap: T.own(m.edgeMap),
      vertexMap: T.own(m.vertexMap),
    }))
    const measurer = new Measurer(T.oc, own)
    const check = (what: string) => {
      const left = T.made.filter((o) => !o.isDeleted())
      assert.equal(left.length, 0, `${what}: ${left.length} of ${T.made.length} OCCT objects left: ${[...new Set(left.map((o) => o.constructor?.name))].join(', ')}`)
      T.made.length = 0
    }
    let seen = 0
    for (const { request } of golden[file].measures) {
      try {
        measurer.run(request)
      } catch (e) {
        if (!(e instanceof MeasureError)) throw e
      }
      seen += T.made.length
      check(JSON.stringify(request))
    }
    assert.ok(seen > 1000, `the tracer saw ${seen} objects: it must see what the measurements make`)
    for (const m of own) {
      brepPartProperties(T.oc, m.part.shape)
      check(`properties of part ${m.part.id}`)
    }
  })
}
