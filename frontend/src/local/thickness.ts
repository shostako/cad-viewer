/**
 * Wall thickness on the display mesh in the Web version (backend/app/thickness.py,
 * step for step): the ray method and the rolling ball, per vertex, on
 * three-mesh-bvh (the backend: trimesh with embree). 0 for no value (the
 * backend's inf, sent as 0).
 *
 * One difference: a vertex on an edge whose ray starts in the next face's plane
 * and runs along it (a box's corner). embree sometimes reports the face it
 * grazes at once (a hit too near to count: no value), sometimes not (the far
 * side); three-mesh-bvh never does. Such a ray measures no wall either way.
 */
import { BufferAttribute, BufferGeometry, DoubleSide, Ray, Vector3 } from 'three'
import { MeshBVH } from 'three-mesh-bvh'

/** a BVH over a mesh (its own geometry: the BVH keeps it; indirect, the triangles' order stays) */
export function bvhOf(positions: ArrayLike<number>, indices: ArrayLike<number>): MeshBVH {
  const g = new BufferGeometry()
  g.setAttribute('position', new BufferAttribute(Float32Array.from(positions), 3))
  g.setIndex(new BufferAttribute(Uint32Array.from(indices), 1))
  return new MeshBVH(g, { indirect: true })
}

function diagonal(p: ArrayLike<number>): number {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) (lo[k] = Math.min(lo[k], p[i + k])), (hi[k] = Math.max(hi[k], p[i + k]))
  return Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
}

/** unit normals (a zero one stays zero, as the backend's guard leaves it) */
function unit(normals: ArrayLike<number>, i: number): [number, number, number] {
  const x = normals[3 * i], y = normals[3 * i + 1], z = normals[3 * i + 2]
  const l = Math.hypot(x, y, z) || 1
  return [x / l, y / l, z / l]
}

/** per vertex: the distance to the first surface along the inward normal (Infinity: no hit) */
export function vertexThickness(positions: ArrayLike<number>, normals: ArrayLike<number>, indices: ArrayLike<number>, bvh?: MeshBVH): Float64Array {
  const n = positions.length / 3
  const out = new Float64Array(n).fill(Infinity)
  if (n === 0 || indices.length === 0) return out
  bvh ??= bvhOf(positions, indices)
  const eps = Math.max(diagonal(positions) * 1e-5, 1e-9)
  const ray = new Ray()
  for (let i = 0; i < n; i++) {
    const [nx, ny, nz] = unit(normals, i)
    ray.origin.set(positions[3 * i] - nx * eps, positions[3 * i + 1] - ny * eps, positions[3 * i + 2] - nz * eps)
    ray.direction.set(-nx, -ny, -nz)
    const hit = bvh.raycastFirst(ray, DoubleSide)
    if (!hit) continue
    const d = hit.point.distanceTo(ray.origin) + eps
    // a hit almost at the origin is the ray grazing its own surface
    if (d > 3 * eps) out[i] = d
  }
  return out
}

/**
 * per vertex: the diameter of the largest sphere tangent at the vertex that
 * fits (a binary search on its centre's depth, the ray's half its cap); 0
 * where none fits (a corner, a convex edge, the strips of a convex surface);
 * Infinity where the ray found nothing
 */
export function vertexThicknessBall(positions: ArrayLike<number>, normals: ArrayLike<number>, indices: ArrayLike<number>, iterations = 12): Float64Array {
  const n = positions.length / 3
  const out = new Float64Array(n).fill(Infinity)
  if (n === 0 || indices.length === 0) return out
  const bvh = bvhOf(positions, indices)
  const dRay = vertexThickness(positions, normals, indices, bvh)
  const tol = Math.max(diagonal(positions) * 1e-5, 1e-9)
  const centre = new Vector3()
  const hitInfo = { point: new Vector3(), distance: 0, faceIndex: 0 }
  const onTri = new Vector3()
  const p = new Vector3()
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(dRay[i])) continue
    const [nx, ny, nz] = unit(normals, i)
    p.set(positions[3 * i], positions[3 * i + 1], positions[3 * i + 2])
    let lo = 0
    const hi0 = dRay[i] / 2
    let hi = hi0
    for (let k = 0; k < iterations; k++) {
      const mid = (lo + hi) / 2
      centre.set(p.x - nx * mid, p.y - ny * mid, p.z - nz * mid)
      const d = bvh.closestPointToPoint(centre, hitInfo)!.distance
      if (d >= mid - tol) lo = mid
      else hi = mid
    }
    // what stopped the sphere at the first size that did not fit: the nearest
    // triangle to its centre. One through the vertex (a corner, a convex crease,
    // the next strip of a convex surface) cuts every sphere tangent there: no value
    if (lo > 0 && hi < hi0 * (1 - 1e-9)) {
      centre.set(p.x - nx * hi, p.y - ny * hi, p.z - nz * hi)
      // the nearest triangles (all of them, within the tolerance: at a box's corner
      // two faces' triangles are as near, and trimesh's pick among them is its own)
      const reach = bvh.closestPointToPoint(centre, hitInfo)!.distance + tol
      let through = false
      bvh.shapecast({
        intersectsBounds: (box) => box.distanceToPoint(centre) <= reach,
        intersectsTriangle: (t) => {
          t.closestPointToPoint(centre, onTri)
          if (onTri.distanceTo(centre) > reach) return false
          t.closestPointToPoint(p, onTri)
          through = onTri.distanceTo(p) <= tol
          return through
        },
      })
      if (through) lo = 0
    }
    out[i] = 2 * lo
  }
  return out
}
