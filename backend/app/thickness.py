"""Wall thickness estimation on the tessellated display mesh.

Two methods (both trimesh-based, embree-accelerated rays):

ray  — inward-normal ray per vertex; thickness = distance to first hit.
       Fast. Overestimates on oblique walls and rib junctions (the ray
       travels diagonally through the joint).

ball — rolling ball / maximal tangent sphere: the largest sphere tangent to
       the surface at the vertex that fits inside the solid; thickness =
       its diameter. This is the standard definition used by commercial
       thickness checkers. Implemented as a batched binary search on the
       sphere center depth t along the inward normal: the sphere (center
       p - n*t, radius t) fits iff the nearest surface distance from the
       center is >= t (tangency at p itself gives exactly t). The ray
       result caps the search: t <= d_ray / 2.
       ~10 batched nearest-point queries; slower but honest at junctions.

Both run on the display mesh, so they work for B-rep parts and plain mesh
uploads alike. With `ball`, no sphere fits at a vertex where the surface
turns away (a corner, a convex edge however shallow, the flat strips of a
convex curved surface): those vertices get 0, which the heatmap shows as
"no data". The search's tolerance would let a small sphere "fit" there and
read as a wall a fraction of a mm thin.
"""
from __future__ import annotations

import numpy as np
import trimesh
import trimesh.proximity


def vertex_thickness(
    positions: np.ndarray,  # (N, 3) float32
    normals: np.ndarray,  # (N, 3) float32
    indices: np.ndarray,  # (M, 3) uint32
) -> np.ndarray:
    """Per-vertex thickness, float32; unhit rays get +inf."""
    n_verts = len(positions)
    out = np.full(n_verts, np.inf, dtype=np.float32)
    if n_verts == 0 or len(indices) == 0:
        return out

    mesh = trimesh.Trimesh(
        vertices=positions.astype(np.float64),
        faces=indices.astype(np.int64),
        process=False,
    )
    diag = float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0)))
    eps = max(diag * 1e-5, 1e-9)

    # normalize (guard against zero normals)
    n = normals.astype(np.float64)
    lens = np.linalg.norm(n, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    n = n / lens

    origins = positions.astype(np.float64) - n * eps
    dirs = -n

    locations, index_ray, _ = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=dirs, multiple_hits=False
    )
    if len(index_ray) == 0:
        return out

    dist = np.linalg.norm(locations - origins[index_ray], axis=1) + eps
    # a hit almost at the origin is the ray grazing its own surface — ignore
    valid = dist > 3 * eps
    out[index_ray[valid]] = dist[valid].astype(np.float32)
    return out


def vertex_thickness_ball(
    positions: np.ndarray,  # (N, 3) float32
    normals: np.ndarray,  # (N, 3) float32
    indices: np.ndarray,  # (M, 3) uint32
    iterations: int = 12,
) -> np.ndarray:
    """Rolling-ball thickness per vertex (sphere diameter), float32.

    Vertices whose ray probe found nothing stay +inf; vertices where no
    tangent sphere fits (a corner, a convex edge, a convex curved surface's
    strips) get 0.
    """
    n_verts = len(positions)
    out = np.full(n_verts, np.inf, dtype=np.float32)
    if n_verts == 0 or len(indices) == 0:
        return out

    d_ray = vertex_thickness(positions, normals, indices)
    hit = np.isfinite(d_ray)
    if not hit.any():
        return out

    mesh = trimesh.Trimesh(
        vertices=positions.astype(np.float64),
        faces=indices.astype(np.int64),
        process=False,
    )
    pq = trimesh.proximity.ProximityQuery(mesh)
    diag = float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0)))
    tol = max(diag * 1e-5, 1e-9)

    n = normals[hit].astype(np.float64)
    lens = np.linalg.norm(n, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    n = n / lens
    p = positions[hit].astype(np.float64)

    # binary search on sphere center depth t: sphere fits iff
    # nearest-surface distance from center >= t - tol
    lo = np.zeros(hit.sum())
    hi0 = d_ray[hit].astype(np.float64) / 2.0
    hi = hi0.copy()
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        centers = p - n * mid[:, None]
        _, dist, _ = pq.on_surface(centers)
        fits = dist >= mid - tol
        lo = np.where(fits, mid, lo)
        hi = np.where(fits, hi, mid)

    # What stopped the sphere: at the first size that did not fit (hi), the
    # surface nearest its centre is what it ran into. Across the wall, that is
    # well over a radius from the vertex (a parallel wall: 2t, the wedge's
    # bottom: 1.9t, the floor of a square notch: 1.41t). Beside the vertex, at
    # most t from it, the sphere cut the face next to the vertex: a corner, a
    # convex crease however shallow (the faces t·sin θ away, t on a right
    # angle), the flat strips of a convex curved surface. No sphere fits there;
    # only the tolerance (dist >= t - tol) let one in, up to tol / (1 - cos θ):
    # a wall a fraction of a mm thin that is not there (#63). No value. The
    # line is drawn at 1.2t, between the right angle's t and the notch's 1.41t.
    blocked = np.flatnonzero((lo > 0) & (hi < hi0 * (1 - 1e-9)))
    if blocked.size:
        q, _, _ = pq.on_surface(p[blocked] - n[blocked] * hi[blocked][:, None])
        beside = np.linalg.norm(q - p[blocked], axis=1) < 1.2 * hi[blocked]
        lo[blocked[beside]] = 0.0
    out[hit] = (2.0 * lo).astype(np.float32)
    return out
