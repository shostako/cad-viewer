"""Wall thickness estimation: inward-normal ray casting per vertex.

For each display vertex, shoot a ray from just inside the surface along the
inverted normal; the distance to the first hit is the local wall thickness.
Known bias: at rib junctions the ray may cross into the joining wall and
over/under-estimate — fine for injection-molding sanity checks (当たり付け).
A rolling-ball method can replace this later if precision is needed.

Runs on the tessellated display mesh (trimesh + embree when available), so it
works for both B-rep parts and plain mesh uploads.
"""
from __future__ import annotations

import numpy as np
import trimesh


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
