"""DXF/DWG (2D drawing) loading: SVG rendering + snap point extraction.

Coordinate mapping (verified empirically, ezdxf 1.4):
with Page(width=bbox_w, height=bbox_h, mm, margins=0) the SVG viewBox is
normalized to `0 0 W H` with max(W, H) = 1,000,000, mapping model coords
linearly and y-flipped. The scale is derived from the emitted viewBox
(never assumed):
    svg_x = (x - xmin) * (W / bbox_w)
    svg_y = (ymax - y) * (H / bbox_h)
Snap points are shipped in BOTH coordinate systems: svg coords for display
alignment, DXF coords for exact measurement values.

DWG requires the free ODA File Converter (not redistributable); when absent
we fail with an actionable message.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Any

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf import recover
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.svg import SVGBackend

MAX_SNAP_POINTS = 50000

ODA_HINT = (
    "DWGの読み込みには ODA File Converter が必要（無料・手動インストール）。"
    "https://www.opendesign.com/guestfiles/oda_file_converter から入手して "
    "PATH に通せ。DXFなら直接読める。"
)


class DrawingLoadError(Exception):
    pass


def load_drawing(data: bytes, filename: str) -> tuple[str, dict[str, Any]]:
    """bytes -> (svg string, meta with snap points and bbox)."""
    ext = filename.rsplit(".", 1)[-1].lower()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, f"input.{ext}")
        with open(path, "wb") as f:
            f.write(data)

        if ext == "dwg":
            if shutil.which("ODAFileConverter") is None:
                raise DrawingLoadError(ODA_HINT)
            from ezdxf.addons import odafc

            try:
                doc = odafc.readfile(path)
            except Exception as e:
                raise DrawingLoadError(f"DWG変換失敗: {e}") from e
        else:
            try:
                doc, auditor = recover.readfile(path)
            except Exception as e:
                raise DrawingLoadError(f"DXF読み込み失敗: {e}") from e
            if auditor.has_errors:
                # recovered with errors — still usable, but note it
                pass

    msp = doc.modelspace()
    extents = ezbbox.extents(msp, fast=True)
    if not extents.has_data:
        raise DrawingLoadError("図面に描画エンティティが無い")
    xmin, ymin = extents.extmin.x, extents.extmin.y
    xmax, ymax = extents.extmax.x, extents.extmax.y
    w = max(xmax - xmin, 1e-9)
    h = max(ymax - ymin, 1e-9)

    ctx = RenderContext(doc)
    backend = SVGBackend()
    Frontend(ctx, backend).draw_layout(msp, finalize=True)
    page = layout.Page(w, h, layout.Units.mm, margins=layout.Margins.all(0))
    svg = backend.get_string(page)

    # derive the actual scale from the emitted viewBox (do not assume it)
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if m is None:
        raise DrawingLoadError("SVG viewBox not found (ezdxf output format changed?)")
    vb_w, vb_h = float(m.group(1)), float(m.group(2))
    sx = vb_w / w
    sy = vb_h / h

    # widen the viewBox 1% per side so boundary strokes aren't clipped.
    # coordinates inside the svg are untouched — the snap mapping stays exact.
    pad = 0.01 * max(vb_w, vb_h)
    svg = svg.replace(
        m.group(0),
        f'viewBox="{-pad:.1f} {-pad:.1f} {vb_w + 2 * pad:.1f} {vb_h + 2 * pad:.1f}"',
        1,
    )

    snaps = _snap_points(msp)

    def to_svg(p: tuple[float, float]) -> list[float]:
        return [round((p[0] - xmin) * sx, 1), round((ymax - p[1]) * sy, 1)]

    meta = {
        "bbox2d": {"min": [xmin, ymin], "max": [xmax, ymax]},
        "svgScale": [sx, sy],
        "snapPoints": [
            {"dxf": [round(p[0], 6), round(p[1], 6)], "svg": to_svg(p), "kind": k}
            for p, k in snaps
        ],
    }
    return svg, meta


MAX_INSERT_DEPTH = 4  # nested block references: expand a few levels, no more


def _snap_points(msp) -> list[tuple[tuple[float, float], str]]:
    """Endpoint / center / vertex snap targets from common entity types.

    INSERT (block reference) entities are expanded via virtual_entities(),
    which yields transformed copies of the block contents — the SVG renderer
    draws that geometry, so it must be snappable too, not just the insertion
    point. Depth-limited for nested blocks.
    """
    out: list[tuple[tuple[float, float], str]] = []

    def add(x: float, y: float, kind: str) -> None:
        if len(out) < MAX_SNAP_POINTS:
            out.append(((x, y), kind))

    def scan(entities, depth: int) -> None:
        for e in entities:
            if len(out) >= MAX_SNAP_POINTS:
                return  # cap reached — stop scanning entities entirely
            t = e.dxftype()
            try:
                if t == "LINE":
                    add(e.dxf.start.x, e.dxf.start.y, "end")
                    add(e.dxf.end.x, e.dxf.end.y, "end")
                elif t == "CIRCLE":
                    c, r = e.dxf.center, e.dxf.radius
                    add(c.x, c.y, "center")
                    for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
                        add(c.x + dx, c.y + dy, "quadrant")
                elif t == "ARC":
                    c = e.dxf.center
                    add(c.x, c.y, "center")
                    sp, ep = e.start_point, e.end_point
                    add(sp.x, sp.y, "end")
                    add(ep.x, ep.y, "end")
                elif t == "LWPOLYLINE":
                    for x, y, *_ in e.get_points():
                        add(x, y, "vertex")
                elif t == "POLYLINE":
                    for v in e.vertices:
                        add(v.dxf.location.x, v.dxf.location.y, "vertex")
                elif t == "POINT":
                    add(e.dxf.location.x, e.dxf.location.y, "point")
                elif t == "INSERT":
                    add(e.dxf.insert.x, e.dxf.insert.y, "insert")
                    if depth < MAX_INSERT_DEPTH:
                        # transformed virtual copies of the block contents
                        scan(e.virtual_entities(), depth + 1)
            except Exception:
                continue  # skip malformed entities

    scan(msp, 0)
    return out
