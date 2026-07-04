/** Typed view over the unified parts payload (backend meshpack.pack_parts / pack_trimesh). */
import type { MeshPack } from './meshpack'

export interface FaceRange {
  faceId: number
  triStart: number
  triCount: number
}

export interface EdgeRange {
  edgeId: number
  segStart: number
  segCount: number
}

export interface PartData {
  id: number
  name: string
  color: [number, number, number] | null
  faceRanges: FaceRange[]
  edgeRanges: EdgeRange[]
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
  edges: Float32Array
}

export interface TreeNodeData {
  name: string
  partId?: number
  children?: TreeNodeData[]
}

export interface ModelData {
  parts: PartData[]
  tree: TreeNodeData
}

interface PartHeader {
  id: number
  name: string
  color: [number, number, number] | null
  faceRanges: FaceRange[]
  edgeRanges: EdgeRange[]
}

export function toModelData(pack: MeshPack): ModelData {
  const partHeaders = (pack.header.parts ?? []) as PartHeader[]
  const parts: PartData[] = partHeaders.map((p) => ({
    ...p,
    positions: pack.buffers[`p${p.id}:positions`] as Float32Array,
    normals: pack.buffers[`p${p.id}:normals`] as Float32Array,
    indices: pack.buffers[`p${p.id}:indices`] as Uint32Array,
    edges: pack.buffers[`p${p.id}:edges`] as Float32Array,
  }))
  const tree = pack.header.tree as TreeNodeData
  return { parts, tree }
}
