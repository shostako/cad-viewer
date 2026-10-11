"""Projected area along the mold-opening direction (for a clamping-force estimate).

The projected area is the area of the model's shadow on a plane normal to the
direction: the union of the projected triangles, so overlapping parts, a boss
over the plate and the two sides of a closed body count once, and a through
hole stays open. The direction is one of the axes (the same choice as the
draft analysis), or any direction (one picked from a face or an edge: a
basis square to it, basis()); its sign does not matter, the shadow is the same.

Like the wall thickness this runs on the display mesh, not the B-rep: an
estimate. A curved outline is the tessellation's polygon (inside the true
outline by at most the chordal deviation).

The union is found by rasterising: every triangle is filled into a bitmap and
the set pixels are counted. Pillow's fill takes in every pixel the outline
touches, so a bitmap of pixel size h over-counts by about the outline's length
times h/2. Two bitmaps, h and h/2, give the area to first order exactly
(Richardson): A ≈ 2·A(h/2) − A(h). What remains is the rounding of the
outline to the pixels, within about the outline's length times one pixel
(mini_mold: 0.03 %; a 300 x 1 mm sliver, a plate seen edge-on: 0.2 %). The
pixel size keeps the finer bitmap under a fixed number of pixels.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw

AXES = {"X": 0, "Y": 1, "Z": 2}
# the finer bitmap's pixel count and longest side (the coarse one has a quarter
# of the pixels). The side is generous: a thin plate seen edge-on (300 x 1 mm)
# needs its 1 mm cut into hundreds of pixels, or the rounding at the long edges
# is a percent of the area.
_MAX_PIXELS = 64_000_000
_MAX_SIDE = 1 << 17


def _bitmap_area(tris: np.ndarray, lo: np.ndarray, h: float, size: tuple[int, int]) -> float:
    """mm² covered by the 2D triangles (n, 3, 2) on a bitmap of pixel size h"""
    im = Image.new("1", size, 0)
    draw = ImageDraw.Draw(im)
    px = (tris - lo) / h
    for t in px.tolist():
        draw.polygon([tuple(p) for p in t], fill=1)
    # the unset pixels from the histogram: a numpy copy of the bitmap would be
    # one byte per pixel (64 MB for the finer one)
    return float(size[0] * size[1] - im.histogram()[0]) * h * h


def unit_direction(direction: Sequence[float]) -> np.ndarray | None:
    """the direction made a unit vector; None when it is not three finite numbers, not all 0"""
    d = np.asarray(direction, dtype=np.float64)
    if d.shape != (3,) or not np.isfinite(d).all():
        return None
    n = float(np.linalg.norm(d))
    return d / n if n > 0 else None


def axis_of(d: np.ndarray) -> str | None:
    """the axis a unit direction lies along, to the last bit (its sign aside); None for any other"""
    for name, k in AXES.items():
        if abs(d[k]) == 1.0 and all(d[i] == 0.0 for i in range(3) if i != k):
            return name
    return None


def basis(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """two unit vectors square to the unit direction d and to each other: the first
    from d and the axis d is least along (the first such, in X Y Z), the second d x it.
    The Web version's projection.ts makes the same pair"""
    k = 0
    for i in (1, 2):
        if abs(d[i]) < abs(d[k]):
            k = i
    e = np.zeros(3)
    e[k] = 1.0
    u = np.cross(d, e)
    u = u / np.linalg.norm(u)
    return u, np.cross(d, u)


def projected_area(
    parts: Iterable[tuple[np.ndarray, np.ndarray]], axis: str = "Z", direction: np.ndarray | None = None
) -> dict[str, Any]:
    """the shadow's area (mm²) of the given (positions, indices) meshes along axis X / Y / Z,
    or along a unit direction (unit_direction) when one is given"""
    head: dict[str, Any] = {"axis": axis}
    flat = True
    if direction is not None:
        head = {"axis": "dir", "dir": direction.tolist()}
        along = axis_of(direction)
        if along is not None:
            axis = along  # the axis's own way: the same answer as asking for the axis
        else:
            flat = False
            u, v = basis(direction)
    k = AXES[axis]
    keep = [i for i in range(3) if i != k]
    chunks = []
    for positions, indices in parts:
        p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
        idx = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
        if len(idx):
            t = p[idx]
            chunks.append(t[:, :, keep] if flat else np.stack([t @ u, t @ v], axis=-1))
    tris = np.concatenate(chunks) if chunks else np.zeros((0, 3, 2))
    if len(tris):
        # walls along the axis project to slivers with no area: Pillow would
        # still draw them as lines, which the extrapolation would have to undo
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        twice = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
        lo, hi = tris.reshape(-1, 2).min(0), tris.reshape(-1, 2).max(0)
        scale = float(np.max(hi - lo))
        tris = tris[twice > (scale * 1e-9) ** 2]
    if len(tris) == 0:
        return {**head, "area": 0.0, "pixel": None}

    lo, hi = tris.reshape(-1, 2).min(0), tris.reshape(-1, 2).max(0)
    w, hgt = (hi - lo).tolist()
    # the finer bitmap: pixel count and longest side capped (a margin of 2 px)
    h = max(math.sqrt(w * hgt / _MAX_PIXELS), max(w, hgt) / (_MAX_SIDE - 8), 1e-9)
    origin = lo - 2 * h

    def size(step: float) -> tuple[int, int]:
        return (int(math.ceil(w / step)) + 5, int(math.ceil(hgt / step)) + 5)

    coarse = _bitmap_area(tris, origin, 2 * h, size(2 * h))
    fine = _bitmap_area(tris, origin, h, size(h))
    area = max(2 * fine - coarse, 0.0)
    return {**head, "area": area, "pixel": h}
