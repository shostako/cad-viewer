/**
 * The Web version's backend: the checkout's /api routes (backend/app/main.py),
 * answered in the page's Worker (worker.ts) with the same paths, statuses and
 * bodies, so api.ts reads them the one way (../engine.ts).
 *
 * So far (docs/designs/web-version.md, W2–W6): mesh formats (STL, OBJ, PLY,
 * OFF, 3MF: the display mesh, volume and area), STEP/IGES (OpenCASCADE in
 * WebAssembly, brep.ts: parts, tree, colours, the display mesh with its B-rep
 * face / edge / vertex IDs; the exact measurements, volume and centre of mass:
 * measure.ts, brepprops.ts), the wall thickness (thickness.ts), 厚肉 (thick.ts),
 * the projected area (projection.ts), DXF (the backend's drawing.py in Pyodide,
 * drawing.ts), the sidecars (kept in IndexedDB, by the file's
 * content hash as the backend names its files). The rest answers 501 with what
 * is not there yet in the Web version.
 */
import { BrepLoadError, loadBrep, type PartMesh } from './brep.ts'
import { DrawingLoadError, type DrawingRenderer } from './drawing.ts'
import { brepPartProperties } from './brepprops.ts'
import { MeasureError, Measurer } from './measure.ts'
import { MESH_EXTS, loadMesh, MeshLoadError } from './meshload.ts'
import { meshPartProperties, modelProps, type ModelProps } from './meshprops.ts'
import { packBuffers, packParts } from './pack.ts'
import { projectedArea } from './projection.ts'
import { gridBudgets, NotSolid, partField, spots, type PartField } from './thick.ts'
import { vertexThickness, vertexThicknessBall } from './thickness.ts'
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
  format: 'mesh' | 'brep' | 'drawing'
  /** a drawing's SVG */
  svg?: string
  hash: string
  meta: Record<string, unknown>
  blob: ArrayBuffer
  /** a mesh format's display mesh */
  mesh?: DisplayMesh
  /** a B-rep's parts, with their shapes and face / edge / vertex maps (for measuring) */
  brep?: PartMesh[]
  properties?: ModelProps
  /** thickness.bin by method, the 厚肉 grids, thick.bin, the projected areas (kept once computed) */
  thickness?: Partial<Record<'ray' | 'ball', ArrayBuffer>>
  thickFields?: Map<number, PartField | string>
  thickBlob?: ArrayBuffer
  projections?: Map<string, unknown>
}

interface DisplayPart {
  id: number
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
  faceRanges: { faceId: number; triStart: number; triCount: number }[]
}

const THICK_SPOTS_MAX = 50

/** OpenCASCADE (libcascade), made once on the first STEP/IGES */
export type OcctProvider = () => Promise<unknown>

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
  private readonly occtProvider: OcctProvider | null
  private occt: Promise<unknown> | null = null
  private readonly drawing: DrawingRenderer | null

  /**
   * version: the app's (package.json's), for /api/health; occt: OpenCASCADE for
   * STEP/IGES; drawing: the DXF renderer (drawing.ts). None: not opened
   */
  constructor(sidecars: SidecarStore, version: string, occt: OcctProvider | null = null, drawing: DrawingRenderer | null = null) {
    this.sidecars = sidecars
    this.version = version
    this.occtProvider = occt
    this.drawing = drawing
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
      this.drop(model)
      return json(200, { deleted: model.id })
    }
    if (!model) return detail(404, 'model not found')
    this.touch(model)
    if (model.format === 'drawing') return this.drawingRoute(model, method, parts[3] ?? '', body)
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
        return json(200, await this.properties(model))
      case 'POST measure': {
        if (model.format !== 'brep') return detail(422, 'measurement requires a B-rep model (STEP/IGES)')
        const oc = await this.occt!
        try {
          return json(200, new Measurer(oc, model.brep!).run(body))
        } catch (e) {
          if (e instanceof MeasureError) return detail(422, e.message)
          // OCCT's own exceptions arrive as numbers (a C++ exception's address)
          return detail(500, `計測の誤り: ${e instanceof Error ? e.message : 'OpenCASCADE の例外'}`)
        }
      }
      case 'GET drawing.svg':
        return detail(404, 'model has no drawing payload')
      case 'GET thickness.bin': {
        const method = url.searchParams.get('method') ?? 'ray'
        if (method !== 'ray' && method !== 'ball') return detail(422, "method must be 'ray' or 'ball'")
        model.thickness ??= {}
        model.thickness[method] ??= packBuffers(
          this.displayParts(model).map((p) => {
            const t = (method === 'ball' ? vertexThicknessBall : vertexThickness)(p.positions, p.normals, p.indices)
            // Infinity (no hit) as 0: the frontend's "no data"
            return [`p${p.id}:thickness`, Float32Array.from(t, (x) => (Number.isFinite(x) ? x : 0)), 1] as [string, Float32Array, number]
          }),
        )
        return { status: 200, kind: 'binary', body: model.thickness[method]!.slice(0) }
      }
      case 'GET thick':
        return this.thick(model, url.searchParams)
      case 'GET thick.bin':
        return this.thickBin(model)
      case 'GET projected_area': {
        const axis = url.searchParams.get('axis') ?? 'Z'
        if (!['X', 'Y', 'Z'].includes(axis)) return detail(422, 'axis must be X, Y or Z')
        const raw = url.searchParams.get('parts')
        let wanted: Set<number> | null = null
        if (raw !== null) {
          const ids = raw.split(',').filter((x) => x.trim())
          if (ids.some((x) => !/^\s*-?\d+\s*$/.test(x))) return detail(422, 'parts must be comma-separated part ids')
          wanted = new Set(ids.map(Number))
        }
        const meshes = this.displayParts(model).filter((p) => wanted === null || wanted.has(p.id))
        const ids = meshes.map((p) => p.id).sort((a, b) => a - b)
        const key = `${axis}:${ids.join(',')}`
        model.projections ??= new Map()
        if (!model.projections.has(key)) {
          model.projections.set(key, { ...projectedArea(meshes, axis), parts: ids })
          while (model.projections.size > 8) model.projections.delete(model.projections.keys().next().value!)
        }
        return json(200, model.projections.get(key))
      }
      default:
        return detail(404, 'Not Found')
    }
  }

  /** the model's /properties (kept once computed) */
  private async properties(model: Model): Promise<ModelProps> {
    if (model.format === 'brep') {
      const oc = await this.occt!
      model.properties ??= modelProps(
        'brep',
        model.brep!.map((m) => ({ id: m.part.id, name: m.part.name, ...brepPartProperties(oc, m.part.shape) })),
      )
    } else {
      model.properties ??= modelProps('mesh', [{ id: 0, name: model.name, ...meshPartProperties(model.mesh!.positions, model.mesh!.indices) }])
    }
    return model.properties
  }

  /** the display mesh part by part (what mesh.bin sends) */
  private displayParts(model: Model): DisplayPart[] {
    if (model.format === 'brep') {
      return model.brep!.map((m) => ({ id: m.part.id, positions: m.positions, normals: m.normals, indices: m.indices, faceRanges: m.faceRanges }))
    }
    return [{ id: 0, positions: model.mesh!.positions, normals: model.mesh!.normals, indices: model.mesh!.indices, faceRanges: [] }]
  }

  /** each part's 厚肉 grid, or why it has none (main._thick_fields): computed once, kept */
  private async thickFields(model: Model): Promise<Map<number, PartField | string>> {
    if (model.thickFields) return model.thickFields
    // a B-rep part's closure is the B-rep's (its display mesh has hairline gaps along curved seams)
    const closed = new Map<number, string | null>()
    if (model.format === 'brep') {
      for (const p of (await this.properties(model)).parts) closed.set(p.id, p.closed ? null : (p.reason ?? 'open'))
    }
    const parts = this.displayParts(model)
    const boxes = new Map<number, number>()
    for (const p of parts) {
      let v = 0
      if (p.positions.length) {
        const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
        for (let i = 0; i < p.positions.length; i += 3) for (let k = 0; k < 3; k++) (lo[k] = Math.min(lo[k], p.positions[i + k])), (hi[k] = Math.max(hi[k], p.positions[i + k]))
        v = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
      }
      boxes.set(p.id, v)
    }
    const budget = gridBudgets(boxes)
    const fields = new Map<number, PartField | string>()
    for (const p of parts) {
      const why = closed.get(p.id)
      if (why) {
        fields.set(p.id, why)
        continue
      }
      try {
        fields.set(p.id, partField(p.positions, p.indices, p.faceRanges, closed.has(p.id), budget.get(p.id)))
      } catch (e) {
        fields.set(p.id, e instanceof NotSolid ? e.reason : 'failed')
      }
    }
    model.thickFields = fields
    return fields
  }

  private async thick(model: Model, q: URLSearchParams): Promise<Answer> {
    const ratio = Number(q.get('ratio') ?? '1.5')
    if (!(ratio >= 1 && ratio <= 10)) return detail(422, 'ratio must be 1..10')
    const given = new Map<number, number>()
    for (const item of (q.get('nominal') ?? '').split(',').filter(Boolean)) {
      const m = item.match(/^\s*(-?\d+)\s*:\s*([-+0-9.eE]+)\s*$/)
      if (!m || !Number.isFinite(Number(m[2]))) return detail(422, `nominal: '${item}' is not partId:mm`)
      const mm = Number(m[2])
      if (!(mm >= 0.01 && mm <= 1000)) return detail(422, 'nominal must be 0.01..1000 mm')
      given.set(Number(m[1]), mm)
    }
    const fields = await this.thickFields(model)
    const out = [...fields.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([id, f]) => {
        if (typeof f === 'string') return { id, status: f }
        const nom = given.get(id) ?? f.nominalAuto
        const found = nom ? spots(f, nom, ratio) : []
        const r4 = (x: number) => Math.round(x * 1e4) / 1e4
        return {
          id,
          status: nom ? 'ok' : 'no_nominal',
          pitch: r4(f.pitch),
          nominalAuto: f.nominalAuto === null ? null : r4(f.nominalAuto),
          nominal: nom === null || nom === undefined ? null : r4(nom),
          spots: found.slice(0, THICK_SPOTS_MAX),
          spotsMore: Math.max(found.length - THICK_SPOTS_MAX, 0),
        }
      })
    return json(200, { ratio, parts: out })
  }

  private async thickBin(model: Model): Promise<Answer> {
    if (!model.thickBlob) {
      const fields = await this.thickFields(model)
      model.thickBlob = packBuffers(
        this.displayParts(model).map((p) => {
          const v = new Float32Array(p.positions.length / 3)
          const f = fields.get(p.id)
          if (f && typeof f !== 'string') {
            if (f.vertexThickness) v.set(f.vertexThickness)
            else {
              const t = new Map(f.faceThickness.map(([fid, th]) => [fid, th]))
              for (const fr of p.faceRanges) {
                const th = t.get(fr.faceId)
                if (!th) continue
                for (let k = 3 * fr.triStart; k < 3 * (fr.triStart + fr.triCount); k++) v[p.indices[k]] = th
              }
            }
          }
          return [`p${p.id}:thick`, v, 1] as [string, Float32Array, number]
        }),
      )
    }
    return { status: 200, kind: 'binary', body: model.thickBlob.slice(0) }
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
    if (ext === 'dwg') return detail(422, 'Web 版では DWG を開けない（DWG の変換には PC のプログラム ODA File Converter が要る）。DXF に書き出して開く')
    if (LATER_MESH_EXTS.includes(ext)) return notYet('glTF/GLB を開く')
    const brep = BREP_EXTS.includes(ext)
    if (!brep && !DRAWING_EXTS.includes(ext) && !(MESH_EXTS as readonly string[]).includes(ext)) return detail(415, `unsupported file extension: .${ext}`)
    const hash = await sha256Hex32(bytes)
    for (const m of this.models.values()) {
      if (m.hash === hash && m.name === name) {
        this.touch(m)
        return json(200, { id: m.id, name: m.name, format: m.format, hash, ...(brep ? { cached: true } : {}), ...m.meta })
      }
    }
    if (brep) return this.uploadBrep(name, hash, bytes)
    if (ext === 'dxf') return this.uploadDrawing(name, hash, bytes)
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
    this.keep(model)
    return json(200, { id: model.id, name, format: 'mesh', hash, ...meta })
  }

  private async uploadDrawing(name: string, hash: string, bytes: Uint8Array): Promise<Answer> {
    if (!this.drawing) return notYet('2D 図面（DXF）を開く')
    let out
    try {
      out = await this.drawing(bytes, name)
    } catch (e) {
      if (e instanceof DrawingLoadError) return detail(422, e.message)
      return detail(503, `図面の部品（Python）を読み込めなかった: ${e instanceof Error ? e.message : String(e)}`)
    }
    const model: Model = { id: newId(), name, format: 'drawing', hash, meta: out.meta, blob: new ArrayBuffer(0), svg: out.svg }
    this.keep(model)
    return json(200, { id: model.id, name, format: 'drawing', hash, ...out.meta })
  }

  /** a drawing's routes: its SVG and sidecar; the 3D ones answer as the backend does */
  private async drawingRoute(model: Model, method: string, what: string, body: unknown): Promise<Answer> {
    switch (`${method} ${what}`) {
      case 'GET drawing.svg':
        return { status: 200, kind: 'text', body: model.svg!, type: 'image/svg+xml' }
      case 'GET sidecar':
        return json(200, (await this.sidecars.get(model.hash)) ?? {})
      case 'PUT sidecar':
        await this.sidecars.put(model.hash, body)
        return json(200, { saved: true })
      case 'GET mesh.bin':
        return detail(404, 'model has no mesh payload')
      case 'POST measure':
        return detail(422, 'measurement requires a B-rep model (STEP/IGES)')
      case 'GET thickness.bin':
        return detail(422, 'thickness requires a 3D model (mesh or B-rep)')
      case 'GET thick':
      case 'GET thick.bin':
        return detail(422, '厚肉 requires a 3D model (mesh or B-rep)')
      case 'GET properties':
        return detail(422, 'properties require a 3D model (mesh or B-rep)')
      case 'GET projected_area':
        return detail(422, 'projected area requires a 3D model (mesh or B-rep)')
      default:
        return detail(404, 'Not Found')
    }
  }

  private async uploadBrep(name: string, hash: string, bytes: Uint8Array): Promise<Answer> {
    if (!this.occtProvider) return notYet('STEP/IGES を開く')
    let oc: unknown
    try {
      oc = await (this.occt ??= this.occtProvider())
    } catch (e) {
      this.occt = null // try again next time
      return detail(503, `OpenCASCADE を読み込めなかった: ${e instanceof Error ? e.message : String(e)}`)
    }
    const info: { fileUnit?: string | null } = {}
    let loaded
    try {
      loaded = loadBrep(oc, bytes, name, info)
    } catch (e) {
      // OCCT's own exceptions arrive as numbers (a C++ exception's address)
      const why = e instanceof BrepLoadError || e instanceof Error ? e.message : 'OpenCASCADE の例外'
      return detail(422, why)
    }
    const { blob, meta } = packParts(loaded.meshes, loaded.tree, loaded.deflection)
    meta.fileUnit = info.fileUnit ?? null
    const model: Model = { id: newId(), name, format: 'brep', hash, meta, blob, brep: loaded.meshes }
    this.keep(model)
    return json(200, { id: model.id, name, format: 'brep', hash, cached: false, ...meta })
  }

  /** a new model, the least recently used ones dropped past MAX_MODELS */
  private keep(model: Model): void {
    this.models.set(model.id, model)
    while (this.models.size > MAX_MODELS) this.drop(this.models.values().next().value!)
  }

  /** a model gone (evicted or deleted): its OCCT objects freed too (they live in the WebAssembly heap) */
  private drop(model: Model): void {
    this.models.delete(model.id)
    for (const m of model.brep ?? []) {
      for (const o of [m.faceMap, m.edgeMap, m.vertexMap, m.part.shape]) o?.delete?.()
    }
    model.brep = undefined
  }
}
