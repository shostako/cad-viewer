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
  // drawing (2D) payloads
  bbox2d?: { min: [number, number]; max: [number, number] }
  snapPoints?: { dxf: [number, number]; svg: [number, number]; kind: string }[]
}

export async function fetchDrawingSvg(modelId: string): Promise<string> {
  const res = await fetch(`/api/models/${modelId}/drawing.svg`)
  if (!res.ok) throw new Error(`svg fetch failed: ${res.status}`)
  return res.text()
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

/** Per-vertex thickness per part (server ray-cast; 0 = no data). */
export async function fetchThickness(modelId: string): Promise<Map<number, Float32Array>> {
  const res = await fetch(`/api/models/${modelId}/thickness.bin`)
  if (!res.ok) throw new Error(`thickness fetch failed: ${res.status}`)
  const pack = parseMeshPack(await res.arrayBuffer())
  const out = new Map<number, Float32Array>()
  for (const [name, arr] of Object.entries(pack.buffers)) {
    const m = name.match(/^p(\d+):thickness$/)
    if (m) out.set(Number(m[1]), arr as Float32Array)
  }
  return out
}

export async function getSidecar(modelId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/models/${modelId}/sidecar`)
  if (!res.ok) return {}
  return res.json()
}

export async function putSidecar(modelId: string, body: unknown): Promise<void> {
  await fetch(`/api/models/${modelId}/sidecar`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
