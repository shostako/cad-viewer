"""厚肉 (#59 item 2): where a part is much thicker than its general wall.

Measured from inside the part, on a grid:

1. The part's grid: the points of a regular grid (pitch h) inside the part
   (embree ray parity, trimesh `contains`), and for each the distance to the
   part's surface (scipy's Euclidean distance transform: to the nearest grid
   point outside, less h / 2). That distance is the radius of the largest
   sphere centred there that fits in the part.
2. 面ごとの肉厚: at points sampled over each triangle, the largest sphere
   tangent to the surface there that fits in the part (the rolling ball, as
   thickness.py's `ball`, here searched on the grid's distances): its
   diameter is the wall there. A B-rep face's thickness is the area-weighted
   median of its samples; a mesh part's vertices take their triangles'.
3. 一般部の肉厚 (nominal): the area-weighted mode of the faces' thicknesses
   (a mesh part: of the triangles'), in bins of 4 % (a log scale): the wall
   most of the part is made of. It can be given instead.
4. 肉だまり: the grid points whose sphere is at least `ratio` x nominal across.
   A connected group of them is one place; its row is its largest sphere (the
   centre and the diameter, the distance to the surface measured again there
   exactly), with diameter / nominal.

Everything is on the display mesh, like the thickness heatmap: an estimate
within about the pitch (said with the values). A part that is not closed and
consistently wound gets no values (判定できない), as for its volume.

The pitch: a sixteenth of a first guess of the wall (the area-weighted median of
inward rays from the triangles' centres), coarser if the grid would exceed
GRID_MAX points (then the walls are seen in fewer steps: said by the pitch).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh
import trimesh.proximity
from scipy import ndimage

log = logging.getLogger(__name__)

GRID_MAX = 12_000_000
"""grid points of one part at most (memory: ~100 MB while it is computed)"""
MODEL_GRID_MAX = 24_000_000
"""grid points of a whole model at most (the grids are kept: ~100 MB), shared
by the parts in proportion to their boxes' volumes (each GRID_MIN at least,
less when the parts are many: the sum stays under this)"""
GRID_MIN = 500_000
STEPS_PER_WALL = 16
"""grid steps across the first guess of the wall"""
SAMPLES_MAX = 400_000
"""surface samples of one part at most (the triangles' own centres at least)"""
GRID_SHIFT = np.array([0.37, 0.29, 0.43])
"""the grid's offset, in steps (odd fractions: off the model's round coordinates)"""
FACE_QUANTILE = 0.9
"""a face's thickness: this quantile of its samples' (area-weighted). A face
narrower than the wall (a plate's side) has most of its tangent spheres
stopped by the faces beside it; its far side is the wall all the same"""
BIN = 0.04
"""the nominal's bins: 4 % wide (log scale)"""
SEARCH_STEPS = 12


@dataclass
class PartField:
    """a part's grid (kept: the spots for another ratio or nominal come from it again)"""

    origin: np.ndarray  # (3,) the first grid point
    pitch: float
    radius: np.ndarray  # (nx, ny, nz) float32: distance to the surface, 0 outside
    mesh: trimesh.Trimesh
    """the part's surface (a part of several bodies: their faces on the union's outside only)"""
    tri_thickness: np.ndarray  # (M,) per display triangle (the sample's; 0: none)
    face_thickness: list[tuple[int, float, float]]  # (faceId, thickness, area) for B-rep faces
    vertex_thickness: np.ndarray | None  # (N,) per display vertex, mesh parts
    nominal_auto: float | None


class NotSolid(Exception):
    """the part cannot be judged (not closed, not consistently wound, no faces)"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _solid(positions: np.ndarray, indices: np.ndarray, trusted_closed: bool = False) -> trimesh.Trimesh:
    """the part's mesh, merged by position. trusted_closed: its closure was
    judged elsewhere (a B-rep part's, exactly), not on these triangles"""
    if len(indices) == 0:
        raise NotSolid("no_faces")
    m = trimesh.Trimesh(np.asarray(positions, dtype=np.float64), np.asarray(indices, dtype=np.int64), process=True)
    if not trusted_closed and not m.is_watertight:
        raise NotSolid("open")
    if not trusted_closed and not m.is_winding_consistent:
        raise NotSolid("winding")
    if m.volume < 0:  # inside out as a whole: the grid only needs inside / outside
        m.invert()
    if abs(m.volume) <= 1e-9 * float(np.linalg.norm(m.extents)) ** 3:
        raise NotSolid("degenerate")
    return m


def _first_guess(m: trimesh.Trimesh) -> float:
    """the area-weighted median of inward rays from the triangles' centres"""
    c = m.triangles_center
    n = m.face_normals
    eps = max(float(np.linalg.norm(m.extents)) * 1e-6, 1e-9)
    loc, idx, _ = m.ray.intersects_location(c - n * eps, -n, multiple_hits=False)
    if len(idx) == 0:
        return float(min(m.extents))
    d = np.linalg.norm(loc - c[idx], axis=1)
    w = m.area_faces[idx]
    order = np.argsort(d)
    cw = np.cumsum(w[order])
    return float(d[order][np.searchsorted(cw, cw[-1] / 2)])


def _grid(
    m: trimesh.Trimesh, guess: float, grid_max: int = GRID_MAX, bodies: list[tuple[trimesh.Trimesh, int]] | None = None
) -> tuple[np.ndarray, float, np.ndarray]:
    lo, hi = m.bounds
    size = hi - lo
    h = guess / STEPS_PER_WALL
    # coarser until the grid fits (2 points of margin all round: outside for sure)
    while np.prod(np.ceil(size / h) + 5) > grid_max:
        h *= 1.25
    h = max(h, float(np.linalg.norm(size)) * 1e-4)
    shape = (np.ceil(size / h) + 5).astype(int)
    # off the model's round coordinates by an odd fraction of a step: no grid
    # line runs along a face or through an edge (a ray there would graze it)
    origin = lo - 2 * h + h * GRID_SHIFT
    inside = _inside(m, origin, h, shape, bodies)
    d = ndimage.distance_transform_edt(inside, sampling=h).astype(np.float32)
    # to the nearest grid point outside, less half a step: about to the surface
    radius = np.where(inside, np.maximum(d - h / 2, 0), 0).astype(np.float32)
    return origin, h, radius


def _bodies(m: trimesh.Trimesh) -> list[tuple[trimesh.Trimesh, int]] | None:
    """the part's bodies with their roles (+1 material, -1 cavity), largest first,
    when there are several and each is closed (else None: the mesh is one
    surface). The roles as /properties takes them (properties._mesh_bodies): a
    body nobody encloses is material; one facing its parent's way keeps the
    parent's role (an overlap), one facing the other way flips it (a cavity in
    material, an island in a cavity)"""
    if m.body_count <= 1:
        return None
    bodies = m.split(only_watertight=False)
    if len(bodies) < 2 or not all(b.is_watertight for b in bodies):
        return None
    from .properties import _inside as body_inside

    signed = [float(b.volume) for b in bodies]
    order = sorted(range(len(bodies)), key=lambda k: (-abs(signed[k]), k))
    role: dict[int, int] = {}
    for k in order:
        parents = [q for q in role if body_inside(bodies[k], bodies[q])]
        if not parents:
            role[k] = 1
        else:
            p = min(parents, key=lambda q: abs(signed[q]))
            role[k] = role[p] if signed[k] * signed[p] > 0 else -role[p]
    return [(bodies[k], role[k]) for k in order]


def _in_union(bodies: list[tuple[trimesh.Trimesh, int]], pts: np.ndarray) -> np.ndarray:
    """points inside the part's material: the bodies in order, material added, cavities taken away"""
    out = np.zeros(len(pts), dtype=bool)
    for b, role in bodies:
        inside = b.contains(pts)
        out = out | inside if role > 0 else out & ~inside
    return out


def _outside_faces(m: trimesh.Trimesh, bodies: list[tuple[trimesh.Trimesh, int]]) -> trimesh.Trimesh:
    """the faces of the bodies on the outside of their union: a hair off each
    triangle's centre, outward, is not in the material (a face inside another
    body, two faces that touch, is not the part's surface)"""
    d = max(float(np.linalg.norm(m.extents)) * 1e-5, 1e-7)
    keep = ~_in_union(bodies, m.triangles_center + m.face_normals * d)
    return trimesh.Trimesh(m.vertices, m.faces[keep], process=False)


def _inside(
    m: trimesh.Trimesh, origin: np.ndarray, h: float, shape: np.ndarray, bodies: list[tuple[trimesh.Trimesh, int]] | None = None
) -> np.ndarray:
    """the grid points inside the part's material.

    A part of one body, or one whose bodies are not each closed (a B-rep
    solid's display mesh with hairline gaps along its seams): the crossings of
    the whole mesh. A part of several closed bodies: each body's inside by its
    own crossings, and the bodies' roles as /properties takes them
    (properties._mesh_bodies): material bodies are added (two that overlap or
    touch are their union; the crossings of both together would make a void of
    the overlap), a cavity is taken away, an island in it added back. The
    largest first, so a body's parent is decided before it."""
    if bodies is None:
        return _inside_crossings(m, origin, h, shape)
    out = np.zeros(tuple(int(v) for v in shape), dtype=bool)
    for b, role in bodies:
        mask = _inside_crossings(b, origin, h, shape)
        if role > 0:
            out |= mask
        else:
            out &= ~mask
    return out


def _inside_crossings(m: trimesh.Trimesh, origin: np.ndarray, h: float, shape: np.ndarray) -> np.ndarray:
    """the grid points inside a mesh by its crossings: one ray up each column of
    the grid (those over the mesh's box), the stretches between its crossings
    in pairs (a column whose crossings do not pair up asks point by point instead)"""
    nx, ny, nz = (int(v) for v in shape)
    xs = origin[0] + h * np.arange(nx)
    ys = origin[1] + h * np.arange(ny)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    z0 = origin[2] - h
    starts = np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, z0)], axis=1)
    inside = np.zeros((nx * ny, nz), dtype=bool)
    # only the columns over the mesh's box can cross it
    lo, hi = m.bounds
    over = np.flatnonzero((starts[:, 0] >= lo[0]) & (starts[:, 0] <= hi[0]) & (starts[:, 1] >= lo[1]) & (starts[:, 1] <= hi[1]))
    if not len(over):
        return inside.reshape(nx, ny, nz)
    dirs = np.tile([0.0, 0.0, 1.0], (len(over), 1))
    loc, ray, _ = m.ray.intersects_location(starts[over], dirs, multiple_hits=True)
    ray = over[ray]
    zs = origin[2] + h * np.arange(nz)
    if len(ray):
        order = np.lexsort((loc[:, 2], ray))
        ray, hz = ray[order], loc[order, 2]
        cols, first, counts = np.unique(ray, return_index=True, return_counts=True)
        odd = []
        for col, f, c in zip(cols, first, counts):
            if c % 2:
                odd.append(col)
                continue
            z = hz[f : f + c]
            for a, b in zip(z[0::2], z[1::2]):
                inside[col] |= (zs > a) & (zs < b)
        if odd:
            odd = np.array(odd)
            pts = np.stack([np.repeat(starts[odd, 0], nz), np.repeat(starts[odd, 1], nz), np.tile(zs, len(odd))], axis=1)
            inside[odd] = m.contains(pts).reshape(len(odd), nz)
    return inside.reshape(nx, ny, nz)


def _radius_at(f_origin: np.ndarray, h: float, radius: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """the grid's distance to the surface at points (trilinear)"""
    coords = ((pts - f_origin) / h).T
    return ndimage.map_coordinates(radius, coords, order=1, mode="constant", cval=0.0)


def _samples(m: trimesh.Trimesh, spacing: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """points over the triangles (the centres of an n x n split of each), their
    triangle, normal (the triangle's) and area. n from the triangle's longest
    edge / spacing. (The vertices' normals blended, a B-rep's true ones, came
    within 1 % of these on a cylinder: the grid's pitch is what counts.)"""
    tris = m.triangles
    edge = np.max(np.linalg.norm(tris - np.roll(tris, 1, axis=1), axis=2), axis=1)
    n = np.clip(np.ceil(edge / spacing), 1, 32).astype(int)
    total = int(np.sum(n * n))
    while total > SAMPLES_MAX and n.max() > 1:
        n = np.maximum(1, (n * 0.8).astype(int))
        total = int(np.sum(n * n))
    pts, tri_of, area = [], [], []
    for k in np.unique(n):
        sel = np.flatnonzero(n == k)
        # the centres of the k x k split: barycentric (i + 1/3, j + 1/3) / k and (i + 2/3, j + 2/3) / k
        bc = []
        for i in range(k):
            for j in range(k - i):
                bc.append(((i + 1 / 3) / k, (j + 1 / 3) / k))
                if i + j < k - 1:
                    bc.append(((i + 2 / 3) / k, (j + 2 / 3) / k))
        bc = np.array(bc)  # (k*k, 2)
        a, b = bc[:, 0], bc[:, 1]
        t = tris[sel]  # (s, 3, 3)
        p = t[:, None, 0] + a[None, :, None] * (t[:, None, 1] - t[:, None, 0]) + b[None, :, None] * (t[:, None, 2] - t[:, None, 0])
        pts.append(p.reshape(-1, 3))
        tri_of.append(np.repeat(sel, len(bc)))
        area.append(np.repeat(m.area_faces[sel] / len(bc), len(bc)))
    tri_of_a = np.concatenate(tri_of)
    return np.concatenate(pts), tri_of_a, m.face_normals[tri_of_a], np.concatenate(area)


def _ball(origin: np.ndarray, h: float, radius: np.ndarray, p: np.ndarray, n: np.ndarray) -> np.ndarray:
    """the diameter of the largest sphere tangent at p (inward normal -n) that
    fits, on the grid: its centre at depth t fits while the distance to the
    surface there is still t. The grid's distances are within h / 2 either way
    (where the surface falls between two grid points), so within h / 2 is
    taken as fitting: the diameter is then within about h / 2 of the wall"""
    lo = np.zeros(len(p))
    hi = np.full(len(p), float(radius.max()) + h)
    for _ in range(SEARCH_STEPS):
        mid = (lo + hi) / 2
        fits = _radius_at(origin, h, radius, p - n * mid[:, None]) >= mid - h / 2
        lo = np.where(fits, mid, lo)
        hi = np.where(fits, hi, mid)
    return 2 * lo


def _weighted_median(v: np.ndarray, w: np.ndarray) -> float:
    order = np.argsort(v)
    cw = np.cumsum(w[order])
    return float(v[order][np.searchsorted(cw, cw[-1] / 2)])


def _grouped_quantile(group: np.ndarray, v: np.ndarray, w: np.ndarray, size: int, q: float) -> tuple[np.ndarray, np.ndarray]:
    """each group's weighted q-quantile of v (0 for a group with no weight) and its total weight"""
    order = np.lexsort((v, group))
    g, vs, ws = group[order], v[order], w[order]
    total = np.bincount(g, weights=ws, minlength=size)
    cw = np.cumsum(ws)
    before = np.concatenate([[0.0], np.cumsum(total)[:-1]])
    present = total > 0
    idx = np.searchsorted(cw, before[present] + total[present] * q)
    med = np.zeros(size)
    med[present] = vs[np.minimum(idx, len(vs) - 1)]
    return med, total


def nominal_of(values: np.ndarray, weights: np.ndarray) -> float | None:
    """the area-weighted mode, in bins BIN wide on a log scale (the bin's own weighted median)"""
    ok = values > 0
    if not ok.any():
        return None
    v, w = values[ok], weights[ok]
    b = np.floor(np.log(v) / math.log(1 + BIN)).astype(int)
    keys, inv = np.unique(b, return_inverse=True)
    best = int(np.argmax(np.bincount(inv, weights=w)))
    sel = inv == best
    return _weighted_median(v[sel], w[sel])


def part_field(
    positions: np.ndarray,
    indices: np.ndarray,
    face_ranges: list[dict[str, int]],
    trusted_closed: bool = False,
    grid_max: int = GRID_MAX,
) -> PartField:
    """the grid and the walls of one part (raises NotSolid); its grid grid_max points at most"""
    m = _solid(positions, indices, trusted_closed)
    bodies = _bodies(m)
    guess = _first_guess(m)
    origin, h, radius = _grid(m, guess, grid_max, bodies)
    # samples on the display triangles (not the merged mesh's: the face ids are the display's)
    disp = trimesh.Trimesh(np.asarray(positions, dtype=np.float64), np.asarray(indices, dtype=np.int64), process=False)
    if m.volume > 0 and disp.volume < 0:
        disp.invert()
    pts, tri_of, nrm, area = _samples(disp, max(h, guess / 4))
    if bodies is not None:
        # a triangle inside the bodies' union (two that touch or overlap) is not the
        # part's surface: its samples say nothing of a wall (no value, no weight)
        d = max(float(np.linalg.norm(m.extents)) * 1e-5, 1e-7)
        inner = _in_union(bodies, disp.triangles_center + disp.face_normals * d)
        keep = ~inner[tri_of]
        pts, tri_of, nrm, area = pts[keep], tri_of[keep], nrm[keep], area[keep]
    diam = _ball(origin, h, radius, pts, nrm)
    # a triangle's own value: its samples' (one sample: its own), as a face's
    tri_t, tri_w = _grouped_quantile(tri_of, diam, area, len(disp.faces), FACE_QUANTILE)
    faces: list[tuple[int, float, float]] = []
    if face_ranges:
        # a B-rep face: the quantile of all its samples (the display triangles in its range)
        tri_face = np.full(len(disp.faces), -1)
        for k, fr in enumerate(face_ranges):
            tri_face[int(fr["triStart"]) : int(fr["triStart"]) + int(fr["triCount"])] = k
        sf = tri_face[tri_of]
        keep = sf >= 0
        med, tot = _grouped_quantile(sf[keep], diam[keep], area[keep], len(face_ranges), FACE_QUANTILE)
        faces = [(int(fr["faceId"]), float(med[k]), float(tot[k])) for k, fr in enumerate(face_ranges) if tot[k] > 0]
        nominal = nominal_of(np.array([f[1] for f in faces]), np.array([f[2] for f in faces])) if faces else None
        vertex_t = None
    else:
        nominal = nominal_of(tri_t, tri_w)
        # a vertex: the area-weighted mean of its triangles' values
        vt = np.zeros(len(positions))
        vw = np.zeros(len(positions))
        for k in range(3):
            np.add.at(vt, indices[:, k], tri_t * tri_w)
            np.add.at(vw, indices[:, k], tri_w * (tri_t > 0))
        vertex_t = np.where(vw > 0, vt / np.maximum(vw, 1e-30), 0.0).astype(np.float32)
    surface = m if bodies is None else _outside_faces(m, bodies)
    return PartField(origin, h, radius, surface, tri_t.astype(np.float32), faces, vertex_t, nominal)


REFINE_MAX = 50
"""places whose deepest point is searched for exactly (the rest: their grid point's)"""
_NEIGHBOURS = np.array([(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)], dtype=np.float64)


def _deepest(pq: trimesh.proximity.ProximityQuery, field: PartField, c: np.ndarray) -> tuple[np.ndarray, float]:
    """from a grid point, the point nearby farthest from the surface (exact
    distances, a pattern search down to h / 32): the centre of the largest
    sphere there. A step stays in the material (the grid's inside)"""
    h = field.pitch
    best = float(pq.on_surface(c[None])[1][0])
    step = h
    while step > h / 32:
        cand = c + _NEIGHBOURS * step
        cand = cand[_radius_at(field.origin, h, field.radius, cand) > 0]
        if len(cand):
            _, d, _ = pq.on_surface(cand)
            k = int(np.argmax(d))
            if d[k] > best * (1 + 1e-9):
                c, best = cand[k], float(d[k])
                continue
        step /= 2
    return c, best


def grid_budgets(boxes: dict[int, float]) -> dict[int, int]:
    """each part's share of MODEL_GRID_MAX by its box's volume (GRID_MIN to
    GRID_MAX); the shares together never over MODEL_GRID_MAX (with many parts
    the least share goes down, and all are scaled down to fit)"""
    if not boxes:
        return {}
    least = min(GRID_MIN, MODEL_GRID_MAX // len(boxes))
    total = sum(max(v, 0.0) for v in boxes.values())
    if total <= 0:
        share = {k: min(GRID_MAX, MODEL_GRID_MAX // len(boxes)) for k in boxes}
    else:
        share = {k: min(GRID_MAX, max(least, MODEL_GRID_MAX * max(v, 0.0) / total)) for k, v in boxes.items()}
    over = sum(share.values()) / MODEL_GRID_MAX
    return {k: int(v / over) if over > 1 else int(v) for k, v in share.items()}


def spots(field: PartField, nominal: float, ratio: float) -> list[dict[str, Any]]:
    """肉だまり: the places where a sphere at least ratio x nominal across fits, largest first"""
    limit = ratio * nominal / 2
    thick = field.radius >= limit
    if not thick.any():
        return []
    lab, count = ndimage.label(thick, structure=np.ones((3, 3, 3)))
    peaks = ndimage.maximum_position(field.radius, lab, index=np.arange(1, count + 1))
    pq = trimesh.proximity.ProximityQuery(field.mesh)
    centres = field.origin + field.pitch * np.array(peaks, dtype=np.float64)
    order = np.argsort([-field.radius[p] for p in peaks])
    out = []
    for rank, k in enumerate(order):
        c, r = centres[k], None
        if rank < REFINE_MAX:
            c, r = _deepest(pq, field, c)
        else:
            r = float(pq.on_surface(c[None])[1][0])
        d = 2 * r
        # where the sphere touches the surface (the nearest point): the view looks at it from outside
        near, _, tri = pq.on_surface(np.asarray(c)[None])
        out.append(
            {
                "center": [round(float(x), 4) for x in c],
                "diameter": round(d, 4),
                "ratio": round(d / nominal, 3),
                "surface": [round(float(x), 4) for x in near[0]],
                "normal": [round(float(x), 6) for x in field.mesh.face_normals[int(tri[0])]],
            }
        )
    out.sort(key=lambda s: -s["diameter"])
    return out
