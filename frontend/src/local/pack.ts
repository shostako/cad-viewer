/**
 * The binary mesh protocol, written (backend/app/meshpack.py's pack_buffers;
 * read by ../meshpack.ts): [uint32 headerLen][header JSON][buffers...], each
 * buffer described in the header's "buffers" by its offset after the header,
 * byteLength, count (numbers, not items), dtype and itemSize.
 */

export type Packable = Float32Array | Uint32Array

export function packBuffers(buffers: [string, Packable, number][], extraHeader: Record<string, unknown> = {}): ArrayBuffer {
  const descs: Record<string, unknown> = {}
  let offset = 0
  for (const [name, arr, itemSize] of buffers) {
    descs[name] = {
      offset,
      byteLength: arr.byteLength,
      count: arr.length,
      dtype: arr instanceof Float32Array ? 'float32' : 'uint32',
      itemSize,
    }
    offset += arr.byteLength
  }
  const header = new TextEncoder().encode(JSON.stringify({ buffers: descs, ...extraHeader }))
  const out = new Uint8Array(4 + header.byteLength + offset)
  new DataView(out.buffer).setUint32(0, header.byteLength, true)
  out.set(header, 4)
  let at = 4 + header.byteLength
  for (const [, arr] of buffers) {
    out.set(new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength), at)
    at += arr.byteLength
  }
  return out.buffer
}

/** what packParts needs of a part (brep.ts's PartMesh) */
export interface PackablePart {
  part: { id: number; name: string; color: [number, number, number] | null }
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
  edgePositions: Float32Array
  vertexPositions: Float32Array
  faceRanges: unknown[]
  edgeRanges: unknown[]
}

/** tessellated B-rep parts into the protocol (meshpack.pack_parts): the blob and the upload's meta */
export function packParts(meshes: PackablePart[], tree: unknown, deflection: number): { blob: ArrayBuffer; meta: Record<string, unknown> } {
  const buffers: [string, Packable, number][] = []
  const parts: Record<string, unknown>[] = []
  let tris = 0, verts = 0
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
  for (const m of meshes) {
    const pid = m.part.id
    buffers.push(
      [`p${pid}:positions`, m.positions, 3],
      [`p${pid}:normals`, m.normals, 3],
      [`p${pid}:indices`, m.indices, 1],
      [`p${pid}:edges`, m.edgePositions, 3],
      [`p${pid}:vertices`, m.vertexPositions, 3],
    )
    parts.push({ id: pid, name: m.part.name, color: m.part.color, faceRanges: m.faceRanges, edgeRanges: m.edgeRanges })
    tris += m.indices.length / 3
    verts += m.positions.length / 3
    for (let i = 0; i < m.positions.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        lo[k] = Math.min(lo[k], m.positions[i + k])
        hi[k] = Math.max(hi[k], m.positions[i + k])
      }
    }
  }
  // all-empty parts: a zero box (Infinity is not JSON)
  const box = lo.every(Number.isFinite) && hi.every(Number.isFinite) ? { min: lo, max: hi } : { min: [0, 0, 0], max: [0, 0, 0] }
  const blob = packBuffers(buffers, { parts, tree, deflection })
  const meta = {
    vertexCount: verts,
    triangleCount: tris,
    partCount: parts.length,
    bbox: box,
    tree,
    parts: parts.map((p) => ({ id: p.id, name: p.name, color: p.color })),
  }
  return { blob, meta }
}
