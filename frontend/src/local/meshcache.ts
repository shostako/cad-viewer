/**
 * The Web version's cache of a STEP/IGES file's load (backend/app/cache.py's,
 * in the browser): the display mesh and the load's answer, by the file's
 * content, kept in the origin's private file system (OPFS). The second time a
 * file is opened it is not read again: OpenCASCADE is not even loaded until a
 * measurement or the volume needs the B-rep (backend.ts reads it then, as the
 * backend does after a cache hit).
 *
 * The key changes with what the load makes: the file's bytes, the meshing's
 * parameters, CACHE_VERSION (the backend's, which a change to the parts' or the
 * faces' numbering bumps) and the app's version (a release reads every file
 * again once).
 */

/** backend/app/cache.py's CACHE_VERSION (frontend/tests/local_cache.test.ts checks they agree) */
export const CACHE_VERSION = 4
/** the meshing's parameters, as the backend writes them into its key */
export const CACHE_PARAMS = 'defl_rel=1e-3;ang=0.35'
/** the cache keeps this many files (the ones written last) */
export const CACHE_MAX = 40

export interface CachedLoad {
  blob: ArrayBuffer
  meta: Record<string, unknown>
}

export interface MeshCache {
  get(key: string): Promise<CachedLoad | null>
  put(key: string, load: CachedLoad): Promise<void>
}

/** the key of a file's load (hex, as the backend's: its 32 first digits) */
export async function cacheKey(bytes: Uint8Array, appVersion: string): Promise<string> {
  const tail = new TextEncoder().encode(`|v${CACHE_VERSION}|${CACHE_PARAMS}|web ${appVersion}`)
  const all = new Uint8Array(bytes.byteLength + tail.byteLength)
  all.set(bytes)
  all.set(tail, bytes.byteLength)
  const digest = await crypto.subtle.digest('SHA-256', all)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32)
}

/** in memory (the tests) */
export function memoryCache(): MeshCache & { size(): number } {
  const m = new Map<string, CachedLoad>()
  return {
    get: async (k) => {
      const v = m.get(k)
      return v ? { blob: v.blob.slice(0), meta: structuredClone(v.meta) } : null
    },
    put: async (k, v) => void m.set(k, { blob: v.blob.slice(0), meta: structuredClone(v.meta) }),
    size: () => m.size,
  }
}

/**
 * in the origin's private file system (the Worker's): a folder of <key>.bin
 * and <key>.json. A load is there once both are; an error (no OPFS, no room)
 * leaves the cache out, never the load.
 */
export function opfsCache(folder = 'load-cache'): MeshCache {
  const dir = async () => (await navigator.storage.getDirectory()).getDirectoryHandle(folder, { create: true })
  const write = async (d: FileSystemDirectoryHandle, name: string, data: ArrayBuffer | string) => {
    const w = await (await d.getFileHandle(name, { create: true })).createWritable()
    await w.write(data)
    await w.close() // the file changes here, whole (the stream writes to a copy until then)
  }
  return {
    async get(key) {
      try {
        const d = await dir()
        const meta = JSON.parse(await (await (await d.getFileHandle(`${key}.json`)).getFile()).text())
        const blob = await (await (await d.getFileHandle(`${key}.bin`)).getFile()).arrayBuffer()
        return { blob, meta }
      } catch {
        return null
      }
    },
    async put(key, load) {
      try {
        const d = await dir()
        // the mesh first: an entry counts once its answer (.json) is there
        await write(d, `${key}.bin`, load.blob)
        await write(d, `${key}.json`, JSON.stringify(load.meta))
        await prune(d)
      } catch {
        // no cache this time: the file is read again next time
      }
    },
  }
}

/**
 * the loads past CACHE_MAX, the ones written first, removed; and a mesh whose
 * answer was never written (a write cut short: another tab's half-made entry
 * only costs that tab its cache)
 */
async function prune(d: FileSystemDirectoryHandle): Promise<void> {
  const written: [string, number][] = []
  const meshes: string[] = []
  for await (const [name, h] of (d as unknown as AsyncIterable<[string, FileSystemHandle]>)) {
    if (h.kind !== 'file') continue
    if (name.endsWith('.json')) written.push([name.slice(0, -5), (await (h as FileSystemFileHandle).getFile()).lastModified])
    else if (name.endsWith('.bin')) meshes.push(name.slice(0, -4))
  }
  written.sort((a, b) => b[1] - a[1])
  const kept = new Set(written.slice(0, CACHE_MAX).map(([key]) => key))
  for (const [key] of written.slice(CACHE_MAX)) await d.removeEntry(`${key}.json`).catch(() => {})
  for (const key of meshes) if (!kept.has(key)) await d.removeEntry(`${key}.bin`).catch(() => {})
}
