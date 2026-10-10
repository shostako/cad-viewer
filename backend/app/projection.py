"""Projected area along the mold-opening direction (for a clamping-force estimate).

The projected area is the area of the model's shadow on a plane normal to the
direction: the union of the projected triangles, so overlapping parts, a boss
over the plate and the two sides of a closed body count once, and a through
hole stays open. The direction is one of the axes (the same choice as the
draft analysis); its sign does not matter, the shadow is the same.

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
from typing import Any, Iterable

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
    return float(np.count_nonzero(np.asarray(im))) * h * h


def projected_area(parts: Iterable[tuple[np.ndarray, np.ndarray]], axis: str) -> dict[str, Any]:
    """the shadow's area (mm²) of the given (positions, indices) meshes along axis X / Y / Z"""
    k = AXES[axis]
    keep = [i for i in range(3) if i != k]
    chunks = []
    for positions, indices in parts:
        p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
        idx = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
        if len(idx):
            chunks.append(p[idx][:, :, keep])
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
        return {"axis": axis, "area": 0.0, "pixel": None}

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
    return {"axis": axis, "area": area, "pixel": h}
