/**
 * The Web version's backend: the checkout's /api routes (backend/app/main.py),
 * answered in the page's Worker (worker.ts) with the same paths, statuses and
 * bodies, so api.ts reads them the one way (../engine.ts).
 *
 * So far (docs/designs/web-version.md, W2): mesh formats (STL, OBJ, PLY, OFF,
 * 3MF): the display mesh, volume and area, the sidecars (kept in IndexedDB,
 * by the file's content hash as the backend names its files). The rest answers
 * 501 with what is not there yet in the Web version.
 */
import { MESH_EXTS, loadMesh, MeshLoadError } from './meshload.ts'
import { meshPartProperties, modelProps, type ModelProps } from './meshprops.ts'
import { packBuffers } from './pack.ts'
import { displayMesh, type DisplayMesh } from './smooth.ts'

/** an answer: JSON, bytes or text, with its HTTP status */
export type Answer =
  | { status: number; kind: 'json'; body: unknown }
  | { status: number; kind: 'binary'; body: ArrayBuffer }
  | { status: number; kind: 'text'; body: string; type: string }

/** where the sidecars are kept (IndexedDB in the page; a Map in the tests) */
export interface SidecarStore {
  get(hash: string): Promise<unknown | undefined>
  put(hash: string, value: unknown): Promise<void>
}

export function memoryStore(): SidecarStore {
  const m = new Map<string, unknown>()
  return {
    get: async (k) => (m.has(k) ? structuredClone(m.get(k)) : undefined),
    put: async (k, v) => void m.set(k, structuredClone(v)),
  }
}

interface Model {
  id: string
  name: string
  format: 'mesh'
  hash: string
  meta: Record<string, unknown>
  blob: ArrayBuffer
  mesh: DisplayMesh
  properties?: ModelProps
}

const MAX_MODELS = 16
const BREP_EXTS = ['step', 'stp', 'iges', 'igs']
const DRAWING_EXTS = ['dxf', 'dwg']
const LATER_MESH_EXTS = ['glb', 'gltf']

const json = (status: number, body: unknown): Answer => ({ status, kind: 'json', body })
const detail = (status: number, message: string): Answer => json(status, { detail: message })
const notYet = (what: string): Answer => detail(501, `Web 版ではまだ使えない: ${what}`)

export async function sha256Hex32(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as Uint8Array<ArrayBuffer>)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32)
}

function newId(): string {
  const b = new Uint8Array(6)
  crypto.getRandomValues(b)
  return [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
}

export class LocalBackend {
  /** least recently used first */
  private readonly models = new Map<string, Model>()
  private readonly sidecars: SidecarStore
  private readonly version: string

  /** version: the app's (package.json's), for /api/health */
  constructor(sidecars: SidecarStore, version: string) {
    this.sidecars = sidecars
    this.version = version
  }

  /** path: from /api (with a query); body: a PUT's JSON, or an upload's { name, bytes } */
  async handle(method: string, path: string, body?: unknown): Promise<Answer> {
    const url = new URL(path, 'http://local')
    const parts = url.pathname.split('/').filter(Boolean) // api, models, id, what
    if (parts[0] !== 'api') return detail(404, 'Not Found')
    if (parts[1] === 'health' && method === 'GET') return json(200, { status: 'ok', app: 'cad-viewer', version: this.version, engine: 'local' })
    if (parts[1] !== 'models') return detail(404, 'Not Found')
    if (parts.length === 2) {
      if (method === 'POST') return this.upload(body as { name: string; bytes: ArrayBuffer })
      if (method === 'GET') return json(200, [...this.models.values()].map((m) => ({ id: m.id, name: m.name, format: m.format, ...m.meta })))
      return detail(405, 'Method Not Allowed')
    }
    const model = this.models.get(parts[2])
    if (method === 'DELETE' && parts.length === 3) {
      if (!model) return detail(404, 'model not found')
      this.models.delete(model.id)
      return json(200, { deleted: model.id })
    }
    if (!model) return detail(404, 'model not found')
    this.touch(model)
    switch (`${method} ${parts[3] ?? ''}`) {
      case 'GET mesh.bin':
        return { status: 200, kind: 'binary', body: model.blob.slice(0) }
      case 'GET sidecar': {
        const saved = await this.sidecars.get(model.hash)
        return json(200, saved ?? {})
      }
      case 'PUT sidecar':
        await this.sidecars.put(model.hash, body)
        return json(200, { saved: true })
      case 'GET properties':
        model.properties ??= modelProps('mesh', [
          { id: 0, name: model.name, ...meshPartProperties(model.mesh.positions, model.mesh.indices) },
        ])
        return json(200, model.properties)
      case 'POST measure':
        return detail(422, 'measurement requires a B-rep model (STEP/IGES)')
      case 'GET drawing.svg':
        return detail(422, 'not a drawing')
      case 'GET thickness.bin':
        return notYet('肉厚')
      case 'GET thick':
      case 'GET thick.bin':
        return notYet('厚肉')
      case 'GET projected_area':
        return notYet('投影面積')
      default:
        return detail(404, 'Not Found')
    }
  }

  private touch(m: Model): void {
    this.models.delete(m.id)
    this.models.set(m.id, m)
  }

  private async upload(file: { name: string; bytes: ArrayBuffer } | undefined): Promise<Answer> {
    if (!file?.bytes) return detail(400, 'empty file')
    const bytes = new Uint8Array(file.bytes)
    if (bytes.byteLength === 0) return detail(400, 'empty file')
    const name = file.name || 'model'
    const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : ''
    if (BREP_EXTS.includes(ext)) return notYet('STEP/IGES を開く（次の段で）')
    if (DRAWING_EXTS.includes(ext)) return notYet('2D 図面（DXF/DWG）を開く')
    if (LATER_MESH_EXTS.includes(ext)) return notYet('glTF/GLB を開く')
    if (!(MESH_EXTS as readonly string[]).includes(ext)) return detail(415, `unsupported file extension: .${ext}`)
    const hash = await sha256Hex32(bytes)
    for (const m of this.models.values()) {
      if (m.hash === hash && m.name === name) {
        this.touch(m)
        return json(200, { id: m.id, name: m.name, format: m.format, hash, ...m.meta })
      }
    }
    let mesh: DisplayMesh
    let lo = [0, 0, 0], hi = [0, 0, 0]
    try {
      const tri = loadMesh(bytes, ext)
      mesh = displayMesh(tri)
      const p = tri.positions
      lo = [Infinity, Infinity, Infinity]
      hi = [-Infinity, -Infinity, -Infinity]
      for (let i = 0; i < p.length; i += 3) {
        for (let k = 0; k < 3; k++) {
          lo[k] = Math.min(lo[k], p[i + k])
          hi[k] = Math.max(hi[k], p[i + k])
        }
      }
    } catch (e) {
      const why = e instanceof MeshLoadError || e instanceof Error ? e.message : String(e)
      return detail(422, `failed to parse mesh: ${why}`)
    }
    const tree = { name: 'root', children: [{ name, partId: 0 }] }
    const blob = packBuffers(
      [
        ['p0:positions', mesh.positions, 3],
        ['p0:normals', mesh.normals, 3],
        ['p0:indices', mesh.indices, 1],
        ['p0:edges', new Float32Array(0), 3],
        ['p0:vertices', new Float32Array(0), 3],
      ],
      { parts: [{ id: 0, name, color: null, faceRanges: [], edgeRanges: [] }], tree },
    )
    const meta = {
      vertexCount: mesh.positions.length / 3,
      triangleCount: mesh.indices.length / 3,
      partCount: 1,
      bbox: { min: lo, max: hi },
      tree,
      parts: [{ id: 0, name, color: null }],
    }
    const model: Model = { id: newId(), name, format: 'mesh', hash, meta, blob, mesh }
    this.models.set(model.id, model)
    while (this.models.size > MAX_MODELS) this.models.delete(this.models.keys().next().value!)
    return json(200, { id: model.id, name, format: 'mesh', hash, ...meta })
  }
}
