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
