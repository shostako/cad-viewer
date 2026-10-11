/**
 * Projected area along an axis in the Web version (backend/app/projection.py):
 * the union of the display mesh's projected triangles on a bitmap of the same
 * pixel size as the backend's finer one.
 *
 * Not the backend's raster (Pillow fills every pixel an outline touches, and
 * two bitmaps extrapolate that away): here a pixel is set when its centre is in
 * a triangle (half-open edges), which has no such bias, so one bitmap gives the
 * area to about the outline's length times a pixel, as the backend's does.
 */
const AXES: Record<string, number> = { X: 0, Y: 1, Z: 2 }
const MAX_PIXELS = 64_000_000
const MAX_SIDE = 1 << 17

export interface ProjectedArea {
  axis: string
  area: number
  pixel: number | null
}

export function projectedArea(parts: { positions: ArrayLike<number>; indices: ArrayLike<number> }[], axis: string): ProjectedArea {
  const k = AXES[axis]
  const [u, v] = [0, 1, 2].filter((i) => i !== k)
  // the 2D triangles, slivers (walls along the axis) dropped
  const tris: number[] = []
  for (const { positions: p, indices: f } of parts) {
    for (let t = 0; t < f.length; t += 3) {
      const a = 3 * f[t], b = 3 * f[t + 1], c = 3 * f[t + 2]
      tris.push(p[a + u], p[a + v], p[b + u], p[b + v], p[c + u], p[c + v])
    }
  }
  if (!tris.length) return { axis, area: 0, pixel: null }
  let lox = Infinity, loy = Infinity, hix = -Infinity, hiy = -Infinity
  for (let i = 0; i < tris.length; i += 2) (lox = Math.min(lox, tris[i])), (hix = Math.max(hix, tris[i])), (loy = Math.min(loy, tris[i + 1])), (hiy = Math.max(hiy, tris[i + 1]))
  const scale = Math.max(hix - lox, hiy - loy)
  const kept: number[] = []
  for (let i = 0; i < tris.length; i += 6) {
    const twice = Math.abs((tris[i + 2] - tris[i]) * (tris[i + 5] - tris[i + 1]) - (tris[i + 3] - tris[i + 1]) * (tris[i + 4] - tris[i]))
    if (twice > (scale * 1e-9) ** 2) kept.push(...tris.slice(i, i + 6))
  }
  if (!kept.length) return { axis, area: 0, pixel: null }
  lox = loy = Infinity
  hix = hiy = -Infinity
  for (let i = 0; i < kept.length; i += 2) (lox = Math.min(lox, kept[i])), (hix = Math.max(hix, kept[i])), (loy = Math.min(loy, kept[i + 1])), (hiy = Math.max(hiy, kept[i + 1]))
  const w = hix - lox, hgt = hiy - loy
  const h = Math.max(Math.sqrt((w * hgt) / MAX_PIXELS), Math.max(w, hgt) / (MAX_SIDE - 8), 1e-9)
  const ox = lox - 2 * h, oy = loy - 2 * h
  const W = Math.ceil(w / h) + 5, H = Math.ceil(hgt / h) + 5
  const bits = new Uint32Array(Math.ceil((W * H) / 32))
  for (let i = 0; i < kept.length; i += 6) fill(kept, i, ox, oy, h, W, H, bits)
  let count = 0
  for (let i = 0; i < bits.length; i++) {
    let x = bits[i]
    x -= (x >>> 1) & 0x55555555
    x = (x & 0x33333333) + ((x >>> 2) & 0x33333333)
    count += (((x + (x >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24
  }
  return { axis, area: count * h * h, pixel: h }
}

/** set the pixels whose centres are in the triangle (rows by their centre line, x half-open) */
function fill(t: number[], i: number, ox: number, oy: number, h: number, W: number, H: number, bits: Uint32Array): void {
  const xs = [t[i] - ox, t[i + 2] - ox, t[i + 4] - ox].map((x) => x / h)
  const ys = [t[i + 1] - oy, t[i + 3] - oy, t[i + 5] - oy].map((y) => y / h)
  const y0 = Math.max(0, Math.ceil(Math.min(...ys) - 0.5)), y1 = Math.min(H - 1, Math.ceil(Math.max(...ys) - 0.5) - 1)
  for (let j = y0; j <= y1; j++) {
    const yc = j + 0.5
    let lo = Infinity, hi = -Infinity
    for (let e = 0; e < 3; e++) {
      const xa = xs[e], ya = ys[e], xb = xs[(e + 1) % 3], yb = ys[(e + 1) % 3]
      if ((ya <= yc && yb > yc) || (yb <= yc && ya > yc)) {
        const x = xa + ((yc - ya) * (xb - xa)) / (yb - ya)
        lo = Math.min(lo, x)
        hi = Math.max(hi, x)
      }
    }
    if (!(hi > lo)) continue
    const c0 = Math.max(0, Math.ceil(lo - 0.5)), c1 = Math.min(W - 1, Math.ceil(hi - 0.5) - 1)
    for (let c = c0; c <= c1; c++) {
      const b = j * W + c
      bits[b >>> 5] |= 1 << (b & 31)
    }
  }
}
