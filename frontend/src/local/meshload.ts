/**
 * Triangle meshes from files (the Web version's backend/app/loaders.py, which
 * uses trimesh): STL (binary and text), OBJ, PLY (text and binary), OFF, 3MF.
 * A file of several bodies or objects becomes one mesh (trimesh's to_mesh),
 * vertices at the same place merged into one (trimesh's process=True).
 *
 * GLB/glTF are not read here yet (the checkout's version reads them).
 */
import { unzipSync } from 'three/examples/jsm/libs/fflate.module.js'

import { triangulate } from './polygons.ts'

export interface TriMesh {
  /** x, y, z per vertex */
  positions: Float64Array
  /** three vertex indices per triangle */
  indices: Uint32Array
}

export class MeshLoadError extends Error {}

export const MESH_EXTS = ['stl', 'obj', 'ply', 'off', '3mf'] as const

/** the mesh of a file's bytes, by its extension (lower case, no dot) */
export function loadMesh(bytes: Uint8Array, ext: string): TriMesh {
  let soup: Soup
  switch (ext) {
    case 'stl':
      soup = readStl(bytes)
      break
    case 'obj':
      soup = readObj(text(bytes))
      break
    case 'ply':
      soup = readPly(bytes)
      break
    case 'off':
      soup = readOff(text(bytes))
      break
    case '3mf':
      soup = read3mf(bytes)
      break
    default:
      throw new MeshLoadError(`unsupported mesh format: .${ext}`)
  }
  if (soup.indices.length === 0) throw new MeshLoadError('no triangle geometry found in file')
  return weld(soup.positions, soup.indices)
}

/** vertices and triangles as read (vertices may repeat) */
interface Soup {
  positions: ArrayLike<number>
  indices: ArrayLike<number>
}

function text(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes)
}

// ---- merging the vertices at one place ---------------------------------------

/** vertices closer than 1e-8 in every coordinate are one (trimesh rounds to 8 decimals) */
export function weld(positions: ArrayLike<number>, indices: ArrayLike<number>): TriMesh {
  const n = positions.length / 3
  const remap = new Uint32Array(n)
  const seen = new Map<string, number>()
  const out: number[] = []
  for (let i = 0; i < n; i++) {
    const x = positions[3 * i], y = positions[3 * i + 1], z = positions[3 * i + 2]
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      remap[i] = 0xffffffff
      continue
    }
    const key = `${Math.round(x * 1e8)},${Math.round(y * 1e8)},${Math.round(z * 1e8)}`
    let k = seen.get(key)
    if (k === undefined) {
      k = out.length / 3
      seen.set(key, k)
      out.push(x, y, z)
    }
    remap[i] = k
  }
  const tris: number[] = []
  for (let t = 0; t < indices.length; t += 3) {
    const a = remap[indices[t]], b = remap[indices[t + 1]], c = remap[indices[t + 2]]
    if (a === 0xffffffff || b === 0xffffffff || c === 0xffffffff) continue // a vertex at infinity
    tris.push(a, b, c)
  }
  return { positions: Float64Array.from(out), indices: Uint32Array.from(tris) }
}

// ---- STL -----------------------------------------------------------------------

function readStl(bytes: Uint8Array): Soup {
  if (bytes.byteLength >= 84) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const count = view.getUint32(80, true)
    // binary when the size is the header's count of 50-byte triangles (a text
    // STL may start with "solid" too, but its size is never that)
    if (84 + count * 50 === bytes.byteLength) {
      const positions = new Float32Array(count * 9)
      for (let t = 0; t < count; t++) {
        const at = 84 + t * 50 + 12 // after the facet's normal
        for (let k = 0; k < 9; k++) positions[9 * t + k] = view.getFloat32(at + 4 * k, true)
      }
      return { positions, indices: Uint32Array.from({ length: count * 3 }, (_, i) => i) }
    }
  }
  const s = text(bytes)
  if (!/^\s*solid/i.test(s)) throw new MeshLoadError('not an STL file')
  const positions: number[] = []
  const re = /vertex\s+(\S+)\s+(\S+)\s+(\S+)/gi
  for (let m = re.exec(s); m; m = re.exec(s)) positions.push(Number(m[1]), Number(m[2]), Number(m[3]))
  const n = Math.floor(positions.length / 9) * 3
  return { positions, indices: Uint32Array.from({ length: n }, (_, i) => i) }
}

// ---- OBJ -----------------------------------------------------------------------

/** the triangles of faces of any number of corners, each cut along its shape (polygons.ts) */
function cut(positions: number[], faces: number[][]): number[] {
  const indices: number[] = []
  for (const f of faces) triangulate(positions, f, indices)
  return indices
}

function readObj(s: string): Soup {
  const positions: number[] = []
  const faces: number[][] = []
  for (const raw of s.split(/\r?\n/)) {
    const line = raw.trim()
    if (line.startsWith('v ')) {
      const [, x, y, z] = line.split(/\s+/)
      positions.push(Number(x), Number(y), Number(z))
    } else if (line.startsWith('f ')) {
      const nv = positions.length / 3
      // "f 1 2 3", "f 1/1 2/2 3/3", "f 1//1 ...", negative = from the end
      faces.push(
        line
          .split(/\s+/)
          .slice(1)
          .map((tok) => {
            const i = parseInt(tok.split('/')[0], 10)
            return i < 0 ? nv + i : i - 1
          }),
      )
    }
  }
  return { positions, indices: cut(positions, faces) }
}

// ---- OFF -----------------------------------------------------------------------

function readOff(s: string): Soup {
  const tokens = s
    .split(/\r?\n/)
    .map((l) => l.replace(/#.*/, '').trim())
    .filter((l) => l)
    .join(' ')
    .split(/\s+/)
  let at = 0
  if (/^[A-Z]*OFF$/.test(tokens[0])) at++
  const nv = Number(tokens[at++])
  const nf = Number(tokens[at++])
  at++ // the edge count
  const positions = tokens.slice(at, at + 3 * nv).map(Number)
  at += 3 * nv
  const faces: number[][] = []
  for (let f = 0; f < nf; f++) {
    const k = Number(tokens[at++])
    faces.push(tokens.slice(at, at + k).map(Number))
    at += k
  }
  return { positions, indices: cut(positions, faces) }
}

// ---- PLY -----------------------------------------------------------------------

const PLY_TYPES: Record<string, [number, string]> = {
  char: [1, 'Int8'], int8: [1, 'Int8'], uchar: [1, 'Uint8'], uint8: [1, 'Uint8'],
  short: [2, 'Int16'], int16: [2, 'Int16'], ushort: [2, 'Uint16'], uint16: [2, 'Uint16'],
  int: [4, 'Int32'], int32: [4, 'Int32'], uint: [4, 'Uint32'], uint32: [4, 'Uint32'],
  float: [4, 'Float32'], float32: [4, 'Float32'], double: [8, 'Float64'], float64: [8, 'Float64'],
}

interface PlyProp {
  name: string
  type: string
  /** a list: the count's type */
  countType?: string
}

function readPly(bytes: Uint8Array): Soup {
  const head = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.byteLength, 65536)))
  const end = head.indexOf('end_header')
  if (!head.startsWith('ply') || end < 0) throw new MeshLoadError('not a PLY file')
  const bodyAt = head.indexOf('\n', end) + 1
  let format = 'ascii'
  const elements: { name: string; count: number; props: PlyProp[] }[] = []
  for (const line of head.slice(0, end).split(/\r?\n/)) {
    const w = line.trim().split(/\s+/)
    if (w[0] === 'format') format = w[1]
    else if (w[0] === 'element') elements.push({ name: w[1], count: Number(w[2]), props: [] })
    else if (w[0] === 'property' && elements.length) {
      const props = elements[elements.length - 1].props
      if (w[1] === 'list') props.push({ name: w[4], type: w[3], countType: w[2] })
      else props.push({ name: w[2], type: w[1] })
    }
  }
  const positions: number[] = []
  const faces: number[][] = []
  const take = (el: string, values: Record<string, number | number[]>) => {
    if (el === 'vertex') positions.push(Number(values.x), Number(values.y), Number(values.z))
    else if (el === 'face') {
      const vs = (values.vertex_indices ?? values.vertex_index) as number[] | undefined
      if (vs) faces.push(vs)
    }
  }
  if (format === 'ascii') {
    const tokens = new TextDecoder().decode(bytes.subarray(bodyAt)).trim().split(/\s+/)
    let at = 0
    for (const el of elements) {
      for (let i = 0; i < el.count; i++) {
        const values: Record<string, number | number[]> = {}
        for (const p of el.props) {
          if (p.countType) {
            const k = Number(tokens[at++])
            values[p.name] = tokens.slice(at, at + k).map(Number)
            at += k
          } else values[p.name] = Number(tokens[at++])
        }
        take(el.name, values)
      }
    }
  } else {
    const little = format === 'binary_little_endian'
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    let at = bodyAt
    const read = (type: string): number => {
      const t = PLY_TYPES[type]
      if (!t) throw new MeshLoadError(`PLY: unknown type ${type}`)
      const getter = `get${t[1]}` as 'getFloat32'
      const v = (view[getter] as (o: number, le: boolean) => number).call(view, at, little)
      at += t[0]
      return v
    }
    for (const el of elements) {
      for (let i = 0; i < el.count; i++) {
        const values: Record<string, number | number[]> = {}
        for (const p of el.props) {
          if (p.countType) {
            const k = read(p.countType)
            const list: number[] = []
            for (let j = 0; j < k; j++) list.push(read(p.type))
            values[p.name] = list
          } else values[p.name] = read(p.type)
        }
        take(el.name, values)
      }
    }
  }
  return { positions, indices: cut(positions, faces) }
}

// ---- 3MF -----------------------------------------------------------------------

/** a 3MF transform "m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32" (rows; a point is a row vector) */
type Affine = number[]
const IDENTITY: Affine = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]

function parseTransform(s: string | undefined): Affine {
  if (!s) return IDENTITY
  const m = s.trim().split(/\s+/).map(Number)
  return m.length === 12 && m.every(Number.isFinite) ? m : IDENTITY
}

/** a then b (a point is moved by a first) */
function compose(a: Affine, b: Affine): Affine {
  const out = new Array<number>(12)
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 3; c++) {
      let v = r === 3 ? b[9 + c] : 0
      for (let k = 0; k < 3; k++) v += a[3 * r + k] * b[3 * k + c]
      out[3 * r + c] = v
    }
  }
  return out
}

/** an XML attribute's value, in double or single quotes (XML allows both) */
function attr(tag: string, name: string): string | undefined {
  const m = tag.match(new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`))
  return m ? (m[1] ?? m[2]) : undefined
}

function read3mf(bytes: Uint8Array): Soup {
  let files: Record<string, Uint8Array>
  try {
    files = unzipSync(bytes)
  } catch {
    throw new MeshLoadError('not a 3MF file (not a zip)')
  }
  const rels = files['_rels/.rels'] ? text(files['_rels/.rels']) : ''
  const target = rels.match(/Target\s*=\s*(?:"\/?([^"]+\.model)"|'\/?([^']+\.model)')/i)
  const start = target ? (target[1] ?? target[2]) : undefined
  const modelName = start && files[start] ? start : Object.keys(files).find((f) => /\.model$/i.test(f))
  if (!modelName) throw new MeshLoadError('3MF: no model in the package')
  const xml = text(files[modelName])

  // objects: a mesh, or components (other objects, each with a transform)
  const meshes = new Map<string, { v: number[]; t: number[] }>()
  const components = new Map<string, { id: string; m: Affine }[]>()
  const objRe = /<object\b([^>]*)>([\s\S]*?)<\/object>/g
  for (let o = objRe.exec(xml); o; o = objRe.exec(xml)) {
    const id = attr(o[1], 'id') ?? ''
    const body = o[2]
    if (/<mesh\b/.test(body)) {
      const v: number[] = []
      const t: number[] = []
      for (const m of body.matchAll(/<vertex\b([^>]*)\/?>/g)) v.push(Number(attr(m[1], 'x')), Number(attr(m[1], 'y')), Number(attr(m[1], 'z')))
      for (const m of body.matchAll(/<triangle\b([^>]*)\/?>/g)) t.push(Number(attr(m[1], 'v1')), Number(attr(m[1], 'v2')), Number(attr(m[1], 'v3')))
      meshes.set(id, { v, t })
    } else {
      const list = [...body.matchAll(/<component\b([^>]*)\/?>/g)].map((m) => ({
        id: attr(m[1], 'objectid') ?? '',
        m: parseTransform(attr(m[1], 'transform')),
      }))
      components.set(id, list)
    }
  }
  const positions: number[] = []
  const indices: number[] = []
  const place = (id: string, m: Affine, depth: number) => {
    if (depth > 32) return // a component cycle
    const mesh = meshes.get(id)
    if (mesh) {
      const base = positions.length / 3
      for (let i = 0; i < mesh.v.length; i += 3) {
        const x = mesh.v[i], y = mesh.v[i + 1], z = mesh.v[i + 2]
        positions.push(
          x * m[0] + y * m[3] + z * m[6] + m[9],
          x * m[1] + y * m[4] + z * m[7] + m[10],
          x * m[2] + y * m[5] + z * m[8] + m[11],
        )
      }
      for (const k of mesh.t) indices.push(base + k)
    }
    for (const c of components.get(id) ?? []) place(c.id, compose(c.m, m), depth + 1)
  }
  const build = xml.match(/<build\b[^>]*>([\s\S]*?)<\/build>/)?.[1] ?? ''
  const items = [...build.matchAll(/<item\b([^>]*)\/?>/g)]
  if (items.length) for (const it of items) place(attr(it[1], 'objectid') ?? '', parseTransform(attr(it[1], 'transform')), 0)
  else for (const id of meshes.keys()) place(id, IDENTITY, 0)
  return { positions, indices }
}
