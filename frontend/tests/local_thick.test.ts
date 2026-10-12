/**
 * The Web version's wall thickness, 厚肉 and projected area (src/local/thickness.ts,
 * thick.ts, projection.ts) against the backend's own routes (thickness.bin,
 * /thick, /thick.bin, /projected_area through FastAPI's TestClient,
 * scripts/engine_golden.py --routes).
 *
 * A mesh file has the same display mesh in both (local_mesh.test.ts): the
 * values are compared vertex by vertex (a vertex known by its position and
 * normal; the two engines order them each their own way). A B-rep's display
 * mesh is each OCCT's own (OCP 7.9, OCCT 8): its values are compared face by
 * face (thick.bin) and by their spread (the rays), within the grid's pitch.
 *
 *   npm test   (testdata first; the backend's venv: backend/.venv or CAD_VIEWER_PYTHON)
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createInstance } from 'libcascade/single/init'

import { LocalBackend, memoryStore } from '../src/local/backend.ts'
import { parseMeshPack } from '../src/meshpack.ts'
import { bvhOf } from '../src/local/thickness.ts'
import { Vector3 } from 'three'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const PYTHON = process.env.CAD_VIEWER_PYTHON ?? path.join(ROOT, 'backend', '.venv', 'bin', 'python')
/** a box as a binary STL (faces out) */
function boxStl(lo: number[], hi: number[]): Uint8Array {
  const c = (i: number) => [i & 1 ? hi[0] : lo[0], i & 2 ? hi[1] : lo[1], i & 4 ? hi[2] : lo[2]]
  const quads = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
  const tris = quads.flatMap(([a, b, cc, d]) => [[a, b, cc], [a, cc, d]])
  const buf = new ArrayBuffer(84 + 50 * tris.length)
  const v = new DataView(buf)
  v.setUint32(80, tris.length, true)
  tris.forEach((t, i) => t.forEach((k, j) => c(k).forEach((x, q) => v.setFloat32(84 + 50 * i + 12 + 12 * j + 4 * q, x, true))))
  return new Uint8Array(buf)
}
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'cad-viewer-thick-'))
// a sheet thinner than the rays' 3 eps (eps = 1e-5 of the diagonal): its rays' hits are too near to count
fs.writeFileSync(path.join(TMP, 'thin_sheet.stl'), boxStl([0, 0, 0], [100, 50, 0.002]))
const MESH = [path.join(ROOT, 'testdata', 'ribbed_plate.stl'), path.join(TMP, 'thin_sheet.stl')]
const BREP = ['mini_mold.step', 'curved_part.step'].map((f) => path.join(ROOT, 'testdata', f))
const FILES = [...MESH, ...BREP]
const ready = fs.existsSync(PYTHON) && FILES.every((f) => fs.existsSync(f))
const golden: Record<string, any> = ready
  ? JSON.parse(execFileSync(PYTHON, [path.join(ROOT, 'scripts', 'engine_golden.py'), '--routes', ...FILES], { encoding: 'utf-8', maxBuffer: 1 << 29 }))
  : {}

async function local(file: string) {
  const be = new LocalBackend(memoryStore(), '0.0.0', () => createInstance())
  const up = await be.handle('POST', '/api/models', { name: path.basename(file), bytes: new Uint8Array(fs.readFileSync(file)).buffer })
  assert.equal(up.status, 200, JSON.stringify(up.body))
  const meta = up.body as any
  const id = meta.id
  const bin = async (p: string) => {
    const r = await be.handle('GET', `/api/models/${id}/${p}`)
    assert.equal(r.status, 200, `${p}: ${JSON.stringify(r.body)}`)
    return parseMeshPack(r.body as ArrayBuffer)
  }
  const js = async (p: string) => {
    const r = await be.handle('GET', `/api/models/${id}/${p}`)
    assert.equal(r.status, 200, `${p}: ${JSON.stringify(r.body)}`)
    return r.body as any
  }
  return { be, id, meta, bin, js }
}

/** a vertex's key: its position and normal, rounded */
const key = (p: ArrayLike<number>, n: ArrayLike<number>, i: number) =>
  [p[3 * i], p[3 * i + 1], p[3 * i + 2], n[3 * i], n[3 * i + 1], n[3 * i + 2]].map((x) => (Math.round(x * 1e4) / 1e4 + 0).toFixed(4)).join(',')

function median(v: number[]): number {
  const s = v.filter((x) => x > 0).sort((a, b) => a - b)
  return s.length ? s[Math.floor(s.length / 2)] : 0
}

for (const file of MESH) {
  test(`${path.basename(file)}: thickness, 厚肉 and the projected area as the backend's (the same display mesh)`, { skip: !ready && 'no backend venv or testdata' }, async () => {
    const want = golden[file]
    assert.ok(want && !want.error, JSON.stringify(want))
    const { bin, js, meta } = await local(file)
    const mesh = await bin('mesh.bin')
    const p = mesh.buffers['p0:positions'], n = mesh.buffers['p0:normals']
    const wp = want.mesh['p0:positions'], wn = want.mesh['p0:normals']
    // whether vertex i's ray starts on another face (within a hair of it)
    const surface = bvhOf(p, mesh.buffers['p0:indices'])
    let lo = Infinity, hi = -Infinity
    for (const x of p) (lo = Math.min(lo, x)), (hi = Math.max(hi, x))
    const eps = Math.max(Math.hypot(...[0, 1, 2].map((k) => {
      let a = Infinity, b = -Infinity
      for (let i = k; i < p.length; i += 3) (a = Math.min(a, p[i])), (b = Math.max(b, p[i]))
      return b - a
    })) * 1e-5, 1e-9)
    const grazes = (i: number) => {
      const l = Math.hypot(n[3 * i], n[3 * i + 1], n[3 * i + 2]) || 1
      const o = new Vector3(p[3 * i] - (n[3 * i] / l) * eps, p[3 * i + 1] - (n[3 * i + 1] / l) * eps, p[3 * i + 2] - (n[3 * i + 2] / l) * eps)
      return surface.closestPointToPoint(o)!.distance < eps / 2
    }
    const index = new Map<string, number>()
    for (let i = 0; i < wp.length / 3; i++) index.set(key(wp, wn, i), i)
    for (const [name, mine] of [
      ['thickness_ray', (await bin('thickness.bin?method=ray')).buffers['p0:thickness']],
      ['thickness_ball', (await bin('thickness.bin?method=ball')).buffers['p0:thickness']],
      ['thick_bin', (await bin('thick.bin')).buffers['p0:thick']],
    ] as const) {
      const theirs = want[name][name === 'thick_bin' ? 'p0:thick' : 'p0:thickness']
      const off: string[] = []
      let grazed = 0
      for (let i = 0; i < p.length / 3; i++) {
        const j = index.get(key(p, n, i))
        assert.ok(j !== undefined, `vertex ${i} not in the backend's display mesh`)
        const a = mine[i], b = theirs[j]
        // embree's (float32) rays within a few of their last digits
        if (Math.abs(a - b) <= 1e-4 + 2e-5 * Math.abs(b)) continue
        // a ray along the next face (it starts in that face's plane): embree's hit is its own (thickness.ts)
        if (name === 'thickness_ray' && grazes(i)) {
          grazed++
          continue
        }
        off.push(`v${i} ${a} vs ${b}`)
      }
      assert.equal(off.length, 0, `${name}: ${off.length} of ${p.length / 3} differ: ${off.slice(0, 6).join('; ')}`)
      assert.ok(grazed <= 0.4 * (p.length / 3), `${name}: ${grazed} rays along a face`)
    }
    for (const ratio of [1.5, 1.1]) {
      const got = await js(`thick?ratio=${ratio}`)
      const exp = want[ratio === 1.5 ? 'thick' : 'thick_low']
      const [g, e] = [got.parts[0], exp.parts[0]]
      assert.equal(g.status, e.status)
      assert.ok(Math.abs(g.pitch - e.pitch) <= 1e-3 * e.pitch, `pitch ${g.pitch} vs ${e.pitch}`)
      assert.ok(Math.abs(g.nominalAuto - e.nominalAuto) <= 1e-3, `nominal ${g.nominalAuto} vs ${e.nominalAuto}`)
      assert.equal(g.spots.length + g.spotsMore, e.spots.length + e.spotsMore, `ratio ${ratio}: the places ${JSON.stringify(g.spots.map((s: any) => s.diameter))} vs ${JSON.stringify(e.spots.map((s: any) => s.diameter))}`)
      g.spots.forEach((s: any, k: number) => {
        const t = e.spots[k]
        const same = (a: number[], b: number[], tol: number) => a.every((x, q) => Math.abs(x - b[q]) <= tol)
        assert.ok(Math.abs(s.diameter - t.diameter) <= 1e-3 && Math.abs(s.ratio - t.ratio) <= 1e-3 && same(s.normal, t.normal, 1e-4), `spot ${k}: ${JSON.stringify(s)} vs ${JSON.stringify(t)}`)
        if (!same(s.center, t.center, 1e-2)) {
          // a tie: the largest sphere fits all along a line (a boss's axis), and each
          // search stops somewhere on it. The backend's centre is as deep in this geometry
          const d = surface.closestPointToPoint(new Vector3(...t.center))!.distance
          assert.ok(Math.abs(2 * d - t.diameter) <= 2e-3, `spot ${k}: the backend's centre ${t.center} is ${2 * d} deep here, not ${t.diameter}`)
        }
      })
    }
    // the projected area: both rasterise, each to within a fraction of the outline's
    // length times the backend's pixel (a sheet seen edge-on is a few pixels across;
    // a pixel all along the outline, set or missed, is past it)
    const box = meta.bbox
    const outlineOf = (ax: string) => {
      const [u, v] = [0, 1, 2].filter((k) => k !== 'XYZ'.indexOf(ax))
      return 2 * (box.max[u] - box.min[u] + box.max[v] - box.min[v])
    }
    for (const ax of ['X', 'Y', 'Z']) {
      const got = await js(`projected_area?axis=${ax}`)
      const exp = want.projected[ax]
      // (the backend's own raster is off the true area by up to about 0.4 of that)
      const tol = Math.max(2e-3 * exp.area, 0.6 * outlineOf(ax) * exp.pixel)
      assert.ok(Math.abs(got.area - exp.area) <= tol, `${ax}: ${got.area} vs ${exp.area} (within ${tol})`)
      assert.deepEqual(got.parts, exp.parts)
    }
    // along a direction of its own: the same, the outline's length at most the box's
    {
      const got = await js('projected_area?dir=1,2,3')
      const exp = want.projected.dir
      const span = [0, 1, 2].map((k) => box.max[k] - box.min[k])
      const tol = Math.max(2e-3 * exp.area, 0.6 * 2 * (span[0] + span[1] + span[2]) * exp.pixel)
      assert.equal(got.axis, 'dir')
      assert.ok(Math.abs(got.area - exp.area) <= tol, `dir: ${got.area} vs ${exp.area} (within ${tol})`)
      // along an axis given as a direction: the axis's own answer
      assert.equal((await js('projected_area?dir=0,0,2')).area, (await js('projected_area?axis=Z')).area)
      // any size (projection.py's unit_direction, by the largest first)
      // (1, 2, 3) as large as a double goes (2e308 would be past it, and refused)
      const huge = (await js('projected_area?dir=0.5e308,1e308,1.5e308')).area
      assert.ok(Math.abs(huge - got.area) <= 1e-6 * got.area, `${huge} vs ${got.area}`)
      assert.equal((await js('projected_area?dir=1e-300,0,0')).area, (await js('projected_area?axis=X')).area)
    }
    // the shadows known exactly: the thin sheet's 50 x 0.002, 100 x 0.002, 100 x 50;
    // ribbed_plate's from above, its plate's 80 x 50 (the ribs and bosses inside it)
    const exact: Record<string, [string, number][]> = {
      'thin_sheet.stl': [['X', 0.1], ['Y', 0.2], ['Z', 5000]],
      'ribbed_plate.stl': [['Z', 4000]],
    }
    {
      for (const [ax, area] of exact[path.basename(file)] ?? []) {
        const got = await js(`projected_area?axis=${ax}`)
        // a pixel's centre in or out decides each pixel: off by well under a pixel along the outline
        assert.ok(Math.abs(got.area - area) <= 0.25 * outlineOf(ax) * want.projected[ax].pixel, `${ax}: ${got.area} vs ${area}`)
      }
    }
  })
}

for (const file of BREP) {
  test(`${path.basename(file)}: thickness, 厚肉 and the projected area near the backend's (each OCCT's display mesh)`, { skip: !ready && 'no backend venv or testdata' }, async () => {
    const want = golden[file]
    assert.ok(want && !want.error, JSON.stringify(want))
    const { bin, js } = await local(file)
    const mesh = await bin('mesh.bin')
    const parts = (mesh.header as any).parts as { id: number; faceRanges: { faceId: number; triStart: number; triCount: number }[] }[]
    const ray = await bin('thickness.bin?method=ray')
    const thickBin = await bin('thick.bin')
    const thick = await js('thick?ratio=1.5')
    for (const part of parts) {
      const pid = part.id
      const what = `part ${pid}`
      // the rays' spread: the median wall
      const mr = median([...ray.buffers[`p${pid}:thickness`]]), wr = median(want.thickness_ray[`p${pid}:thickness`])
      assert.ok(Math.abs(mr - wr) <= 0.02 * wr + 1e-3, `${what}: the rays' median ${mr} vs ${wr}`)
      // 厚肉: the general wall within the pitch, and each face's thickness
      const g = thick.parts.find((x: any) => x.id === pid), e = want.thick.parts.find((x: any) => x.id === pid)
      assert.equal(g.status, e.status, what)
      if (e.status !== 'ok') continue
      const pitch = Math.max(g.pitch, e.pitch)
      assert.ok(Math.abs(g.nominalAuto - e.nominalAuto) <= pitch, `${what}: nominal ${g.nominalAuto} vs ${e.nominalAuto} (pitch ${pitch})`)
      assert.equal(g.spots.length + g.spotsMore, e.spots.length + e.spotsMore, `${what}: the places`)
      const faceOf = (ranges: typeof part.faceRanges, idx: ArrayLike<number>, v: ArrayLike<number>) => {
        const out = new Map<number, number>()
        for (const fr of ranges) out.set(fr.faceId, v[idx[3 * fr.triStart]])
        return out
      }
      const mine = faceOf(part.faceRanges, mesh.buffers[`p${pid}:indices`], thickBin.buffers[`p${pid}:thick`])
      const wpart = want.mesh.parts.find((x: any) => x.id === pid)
      const theirs = faceOf(wpart.faceRanges, want.mesh[`p${pid}:indices`], want.thick_bin[`p${pid}:thick`])
      for (const [fid, t] of theirs) {
        const m = mine.get(fid) ?? 0
        assert.ok(Math.abs(m - t) <= 2 * pitch, `${what} face ${fid}: ${m} vs ${t}`)
      }
    }
    for (const ax of ['X', 'Y', 'Z', 'dir']) {
      const got = await js(ax === 'dir' ? 'projected_area?dir=1,2,3' : `projected_area?axis=${ax}`)
      const exp = want.projected[ax]
      assert.ok(Math.abs(got.area - exp.area) <= 5e-3 * exp.area, `${ax}: ${got.area} vs ${exp.area}`)
    }
  })
}

test('the routes\' errors as the backend words them', async () => {
  const { be, id } = await local(MESH[0])
  for (const [p, status, text] of [
    ['thickness.bin?method=x', 422, "method must be 'ray' or 'ball'"],
    ['thick?ratio=20', 422, 'ratio must be 1..10'],
    ['thick?nominal=a', 422, "nominal: 'a' is not partId:mm"],
    ['thick?nominal=0:5000', 422, 'nominal must be 0.01..1000 mm'],
    ['projected_area?axis=W', 422, 'axis must be X, Y or Z'],
    ['projected_area?parts=x', 422, 'parts must be comma-separated part ids'],
    ['projected_area?dir=1,2', 422, 'dir must be three numbers, not all 0'],
    ['projected_area?dir=0,0,0', 422, 'dir must be three numbers, not all 0'],
    ['projected_area?dir=1,,2', 422, 'dir must be three numbers, not all 0'],
    ['projected_area?dir=nan,0,1', 422, 'dir must be three numbers, not all 0'],
    ['projected_area?dir=2e308,0,0', 422, 'dir must be three numbers, not all 0'],
  ] as const) {
    const r = await be.handle('GET', `/api/models/${id}/${p}`)
    assert.equal(r.status, status, p)
    assert.equal((r.body as any).detail, text, p)
  }
  // no parts: an empty shadow
  const none = (await be.handle('GET', `/api/models/${id}/projected_area?axis=Z&parts=`)).body as any
  assert.deepEqual(none, { axis: 'Z', area: 0, pixel: null, parts: [] })
})
