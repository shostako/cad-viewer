/**
 * The faces of more than three corners in OBJ, PLY and OFF, cut into triangles
 * along their shape (#87): backend/app/polygons.py's triangulate, step for step
 * (both versions must cut a face into the same triangles; tests/local_mesh.test.ts
 * compares them).
 *
 * A face keeps the fan from its first corner (what trimesh makes of every face)
 * when the fan is right: every one of its triangles turns the face's way, which
 * is when the triangles cover the face once. Otherwise (a concave face whose
 * first corner does not see every other one) it is cut by ear clipping.
 */

/** the triangles of one face, as corner indices, three by three, pushed to out
 * (P: x, y, z per vertex; the triangles turn the face's way) */
export function triangulate(P: ArrayLike<number>, poly: number[], out: number[]): void {
  const k = poly.length
  if (k < 3) return
  if (k === 3) {
    out.push(poly[0], poly[1], poly[2])
    return
  }
  // the face's normal (Newell's method: also for a face not quite flat)
  let nx = 0, ny = 0, nz = 0
  for (let i = 0; i < k; i++) {
    const p = 3 * poly[i], q = 3 * poly[(i + 1) % k]
    nx += (P[p + 1] - P[q + 1]) * (P[p + 2] + P[q + 2])
    ny += (P[p + 2] - P[q + 2]) * (P[p] + P[q])
    nz += (P[p] - P[q]) * (P[p + 1] + P[q + 1])
  }
  const nn = nx * nx + ny * ny + nz * nz
  let fanRight = true
  if (nn !== 0) {
    const tol = 1e-9 * nn
    for (let i = 1; i + 1 < k; i++) {
      // written as polygons.py's all(... >= -tol): a NaN makes the fan wrong in both
      if (!(turn(P, poly[0], poly[i], poly[i + 1], nx, ny, nz) >= -tol)) {
        fanRight = false
        break
      }
    }
  }
  if (fanRight) {
    for (let i = 1; i + 1 < k; i++) out.push(poly[0], poly[i], poly[i + 1])
    return
  }
  earClip(P, poly, nx, ny, nz, out)
}

/** (b - a) x (c - a), along the normal: > 0 when a b c turns the face's way */
function turn(P: ArrayLike<number>, a: number, b: number, c: number, nx: number, ny: number, nz: number): number {
  const ux = P[3 * b] - P[3 * a], uy = P[3 * b + 1] - P[3 * a + 1], uz = P[3 * b + 2] - P[3 * a + 2]
  const vx = P[3 * c] - P[3 * a], vy = P[3 * c + 1] - P[3 * a + 1], vz = P[3 * c + 2] - P[3 * a + 2]
  return (uy * vz - uz * vy) * nx + (uz * vx - ux * vz) * ny + (ux * vy - uy * vx) * nz
}

const mod = (i: number, m: number) => ((i % m) + m) % m

/** ear clipping on the face seen along its normal's largest axis (polygons.py's _ear_clip) */
function earClip(P: ArrayLike<number>, poly: number[], nx: number, ny: number, nz: number, out: number[]): void {
  const ax = Math.abs(nx), ay = Math.abs(ny), az = Math.abs(nz)
  // drop the largest axis; the other two in cyclic order keep the turn's sign
  let iu: number, iv: number, s: number
  if (ax >= ay && ax >= az) [iu, iv, s] = [1, 2, nx]
  else if (ay >= az) [iu, iv, s] = [2, 0, ny]
  else [iu, iv, s] = [0, 1, nz]
  const sign = s > 0 ? 1 : -1
  const eps = 1e-10 * Math.abs(s)
  const U = poly.map((i) => P[3 * i + iu])
  const V = poly.map((i) => P[3 * i + iv])
  const cross = (a: number, b: number, c: number) => sign * ((U[b] - U[a]) * (V[c] - V[a]) - (V[b] - V[a]) * (U[c] - U[a]))

  const L = poly.map((_, i) => i) // the corners left, by their place in poly
  const isEar = (i: number): boolean => {
    const m = L.length
    const a = L[mod(i - 1, m)], b = L[i], c = L[mod(i + 1, m)]
    if (cross(a, b, c) <= eps) return false
    for (let j = 0; j < m; j++) {
      const p = L[j]
      if (p === a || p === b || p === c) continue
      if (cross(L[mod(j - 1, m)], p, L[mod(j + 1, m)]) > eps) continue // turns the face's way: not inside
      if (cross(a, b, p) >= -eps && cross(b, c, p) >= -eps && cross(c, a, p) >= -eps) return false
    }
    return true
  }

  let i = 0
  let misses = 0
  while (L.length > 3) {
    const m = L.length
    if (isEar(i)) {
      out.push(poly[L[mod(i - 1, m)]], poly[L[i]], poly[L[mod(i + 1, m)]])
      L.splice(i, 1)
      // the corner before may have become an ear: look at it next
      i = mod(i - 1, m - 1)
      misses = 0
    } else {
      i = mod(i + 1, m)
      misses++
      if (misses >= m) {
        // no ear: the face crosses itself; the rest as a fan
        for (let j = 1; j + 1 < L.length; j++) out.push(poly[L[0]], poly[L[j]], poly[L[j + 1]])
        return
      }
    }
  }
  out.push(poly[L[0]], poly[L[1]], poly[L[2]])
}
