/**
 * The Web version's load cache (src/local/meshcache.ts, backend.ts): the second
 * time a STEP/IGES is opened (a new page, the same cache) it comes from the
 * cache, OpenCASCADE not loaded, with the first time's answer and mesh.bin to
 * the byte. The display mesh's calculations (thickness, the projected area)
 * need no B-rep; a measurement or the volume reads the B-rep again, once, and
 * answers as the first page does. The key changes with the file and the app's
 * version; CACHE_VERSION is the backend's.
 *
 *   npm test   (testdata first)
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createInstance } from 'libcascade/single/init'

import { LocalBackend, memoryStore, sha256Hex32 } from '../src/local/backend.ts'
import { CACHE_VERSION, cacheKey, memoryCache } from '../src/local/meshcache.ts'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const FILES = ['mini_mold.step', 'loose_faces_box.igs'].map((f) => path.join(ROOT, 'testdata', f))

/* eslint-disable @typescript-eslint/no-explicit-any */
const upload = async (be: LocalBackend, file: string) => {
  const r = await be.handle('POST', '/api/models', { name: path.basename(file), bytes: new Uint8Array(fs.readFileSync(file)).buffer })
  assert.equal(r.status, 200, JSON.stringify(r.body))
  return r.body as any
}
const bytesOf = (r: any) => new Uint8Array(r.body as ArrayBuffer)

for (const file of FILES) {
  test(`${path.basename(file)}: opened again from the cache, as the first time`, { skip: !fs.existsSync(file) && 'no testdata' }, async () => {
    const cache = memoryCache()
    const first = new LocalBackend(memoryStore(), '9.9.9', () => createInstance(), null, cache)
    const a = await upload(first, file)
    assert.equal(a.cached, false)
    assert.equal(cache.size(), 1, 'the load kept')

    // a new page: its own Worker, OpenCASCADE not loaded, the same cache
    let loads = 0
    const second = new LocalBackend(memoryStore(), '9.9.9', () => (loads++, createInstance()), null, cache)
    const b = await upload(second, file)
    assert.equal(b.cached, true)
    assert.equal(loads, 0, 'from the cache: OpenCASCADE not loaded')
    const { id: _a, cached: _ca, ...restA } = a
    const { id: _b, cached: _cb, ...restB } = b
    assert.deepEqual(restB, restA, 'the same answer')
    const at = (be: LocalBackend, m: any, p: string, body?: unknown) => be.handle(body === undefined ? 'GET' : 'POST', `/api/models/${m.id}/${p}`, body)
    assert.deepEqual(bytesOf(await at(second, b, 'mesh.bin')), bytesOf(await at(first, a, 'mesh.bin')), 'mesh.bin to the byte')

    // the display mesh's calculations, from the cached mesh: no B-rep needed
    assert.deepEqual(bytesOf(await at(second, b, 'thickness.bin?method=ray')), bytesOf(await at(first, a, 'thickness.bin?method=ray')))
    assert.deepEqual((await at(second, b, 'projected_area?axis=Z')).body, (await at(first, a, 'projected_area?axis=Z')).body)
    assert.equal(loads, 0, 'thickness and the projected area without OpenCASCADE')

    // a measurement and the volume: the B-rep read again, once; the same answers
    const requests: any[] = []
    for (const part of a.parts as any[]) {
      for (let f = 1; f <= 12; f++) requests.push({ type: 'face_info', ref: { partId: part.id, kind: 'face', id: f } })
      for (let e = 1; e <= 12; e++) requests.push({ type: 'edge_info', ref: { partId: part.id, kind: 'edge', id: e } })
      requests.push({ type: 'distance', a: { partId: part.id, kind: 'face', id: 1 }, b: { partId: part.id, kind: 'face', id: 2 } })
    }
    for (const req of requests) {
      const [x, y] = [await at(first, a, 'measure', req), await at(second, b, 'measure', req)]
      assert.deepEqual([y.status, y.body], [x.status, x.body], JSON.stringify(req))
    }
    assert.deepEqual((await at(second, b, 'properties')).body, (await at(first, a, 'properties')).body)
    assert.deepEqual((await at(second, b, 'thick?ratio=1.5')).body, (await at(first, a, 'thick?ratio=1.5')).body)
    assert.equal(loads, 1, 'OpenCASCADE loaded once, the B-rep read once')
  })
}

test('the cache key: the file and the app version in it', async () => {
  const one = await sha256Hex32(new TextEncoder().encode('one')), two = await sha256Hex32(new TextEncoder().encode('two'))
  const k = await cacheKey(one, '1.0.0')
  assert.match(k, /^[0-9a-f]{32}$/)
  assert.equal(await cacheKey(one, '1.0.0'), k, 'the same file and version: the same key')
  assert.notEqual(await cacheKey(two, '1.0.0'), k, 'another file')
  assert.notEqual(await cacheKey(one, '1.0.1'), k, 'another version: read again')
})

test("CACHE_VERSION is the backend's (a change to the parts' or faces' numbering bumps both)", () => {
  const m = fs.readFileSync(path.join(ROOT, 'backend', 'app', 'cache.py'), 'utf-8').match(/^CACHE_VERSION = (\d+)/m)
  assert.ok(m, 'CACHE_VERSION in backend/app/cache.py')
  assert.equal(CACHE_VERSION, Number(m[1]))
})

test('a cache that fails: the file opened all the same, read each time', async () => {
  const file = FILES[0]
  if (!fs.existsSync(file)) return
  const broken = { get: async () => null, put: async () => { throw new Error('no room') } }
  const be = new LocalBackend(memoryStore(), '9.9.9', () => createInstance(), null, broken)
  const r = await be.handle('POST', '/api/models', { name: 'mini_mold.step', bytes: new Uint8Array(fs.readFileSync(file)).buffer })
  assert.equal(r.status, 200, JSON.stringify(r.body))
})
