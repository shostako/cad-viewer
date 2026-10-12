/**
 * Projected area along an axis, or any direction, in the Web version (backend/app/projection.py):
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
  /** the unit direction, when one was asked for instead of an axis */
  dir?: number[]
  area: number
  pixel: number | null
}

type Xyz = [number, number, number]

/** the direction made a unit vector; null when it is not three finite numbers, not all 0 (projection.py unit_direction) */
export function unitDirection(d: readonly number[]): Xyz | null {
  if (d.length !== 3 || !d.every(Number.isFinite)) return null
  // by the largest first, as projection.py (the same unit vector in both)
  const m = Math.max(Math.abs(d[0]), Math.abs(d[1]), Math.abs(d[2]))
  if (m === 0) return null
  const s: Xyz = [d[0] / m, d[1] / m, d[2] / m]
  const n = Math.hypot(s[0], s[1], s[2])
  return [s[0] / n, s[1] / n, s[2] / n]
}

/** the axis a unit direction lies along, to the last bit (its sign aside); null for any other */
function axisOf(d: Xyz): string | null {
  for (const [name, k] of Object.entries(AXES)) if (Math.abs(d[k]) === 1 && [0, 1, 2].every((i) => i === k || d[i] === 0)) return name
  return null
}

/** two unit vectors square to d and to each other (projection.py basis: the same pair) */
function basis(d: Xyz): [Xyz, Xyz] {
  let k = 0
  for (const i of [1, 2]) if (Math.abs(d[i]) < Math.abs(d[k])) k = i
  const e: Xyz = [0, 0, 0]
  e[k] = 1
  const cross = (a: Xyz, b: Xyz): Xyz => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
  const c = cross(d, e)
  const n = Math.hypot(c[0], c[1], c[2])
  const u: Xyz = [c[0] / n, c[1] / n, c[2] / n]
  return [u, cross(d, u)]
}

export function projectedArea(
  parts: { positions: ArrayLike<number>; indices: ArrayLike<number> }[],
  axis: string,
  direction: Xyz | null = null,
): ProjectedArea {
  let head: { axis: string; dir?: number[] } = { axis }
  let uv: [Xyz, Xyz] | null = null
  if (direction) {
    head = { axis: 'dir', dir: [...direction] }
    const along = axisOf(direction)
    if (along) axis = along // the axis's own way: the same answer as asking for the axis
    else uv = basis(direction)
  }
  const k = AXES[axis]
  const [u, v] = [0, 1, 2].filter((i) => i !== k)
  // the 2D triangles, slivers (walls along the axis) dropped
  const tris: number[] = []
  const at = (p: ArrayLike<number>, a: number, w: Xyz) => p[a] * w[0] + p[a + 1] * w[1] + p[a + 2] * w[2]
  for (const { positions: p, indices: f } of parts) {
    for (let t = 0; t < f.length; t += 3) {
      const a = 3 * f[t], b = 3 * f[t + 1], c = 3 * f[t + 2]
      if (uv) tris.push(at(p, a, uv[0]), at(p, a, uv[1]), at(p, b, uv[0]), at(p, b, uv[1]), at(p, c, uv[0]), at(p, c, uv[1]))
      else tris.push(p[a + u], p[a + v], p[b + u], p[b + v], p[c + u], p[c + v])
    }
  }
  if (!tris.length) return { ...head, area: 0, pixel: null }
  let lox = Infinity, loy = Infinity, hix = -Infinity, hiy = -Infinity
  for (let i = 0; i < tris.length; i += 2) (lox = Math.min(lox, tris[i])), (hix = Math.max(hix, tris[i])), (loy = Math.min(loy, tris[i + 1])), (hiy = Math.max(hiy, tris[i + 1]))
  const scale = Math.max(hix - lox, hiy - loy)
  const kept: number[] = []
  for (let i = 0; i < tris.length; i += 6) {
    const twice = Math.abs((tris[i + 2] - tris[i]) * (tris[i + 5] - tris[i + 1]) - (tris[i + 3] - tris[i + 1]) * (tris[i + 4] - tris[i]))
    if (twice > (scale * 1e-9) ** 2) kept.push(...tris.slice(i, i + 6))
  }
  if (!kept.length) return { ...head, area: 0, pixel: null }
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
  return { ...head, area: count * h * h, pixel: h }
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
