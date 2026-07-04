import { parseMeshPack, type MeshPack } from './meshpack'

export interface ModelMeta {
  id: string
  name: string
  format: string
  vertexCount: number
  triangleCount: number
  partCount: number
  cached?: boolean
  bbox: { min: number[]; max: number[] }
}

export async function uploadModel(file: File): Promise<ModelMeta> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/models', { method: 'POST', body: form })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail ?? `upload failed: ${res.status}`)
  }
  return res.json()
}

export async function fetchMesh(modelId: string): Promise<MeshPack> {
  const res = await fetch(`/api/models/${modelId}/mesh.bin`)
  if (!res.ok) throw new Error(`mesh fetch failed: ${res.status}`)
  return parseMeshPack(await res.arrayBuffer())
}

export interface EntityRef {
  partId?: number
  kind: 'face' | 'edge' | 'vertex' | 'point'
  id?: number
  xyz?: [number, number, number]
}

export interface DistanceResult {
  type: 'distance'
  value: number
  pointA: [number, number, number]
  pointB: [number, number, number]
}

export interface EdgeInfoResult {
  type: 'edge'
  length: number
  curve: string
  radius?: number
  diameter?: number
  center?: [number, number, number]
  axis?: [number, number, number]
}

export interface FaceInfoResult {
  type: 'face'
  area: number
  surface: string
  radius?: number
  diameter?: number
  center?: [number, number, number]
  axis?: [number, number, number]
  normal?: [number, number, number]
}

async function measureRequest<T>(modelId: string, body: unknown): Promise<T> {
  const res = await fetch(`/api/models/${modelId}/measure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail ?? `measure failed: ${res.status}`)
  }
  return res.json()
}

export function measureDistance(modelId: string, a: EntityRef, b: EntityRef) {
  return measureRequest<DistanceResult>(modelId, { type: 'distance', a, b })
}

export function measureEdgeInfo(modelId: string, ref: EntityRef) {
  return measureRequest<EdgeInfoResult>(modelId, { type: 'edge_info', ref })
}

export function measureFaceInfo(modelId: string, ref: EntityRef) {
  return measureRequest<FaceInfoResult>(modelId, { type: 'face_info', ref })
}
