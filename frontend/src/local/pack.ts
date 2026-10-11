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
