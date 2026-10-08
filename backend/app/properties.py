"""Volume, surface area and centre of mass per part (for weight estimates).

B-rep parts are integrated exactly by OCCT (BRepGProp, Gauss integration on
the true surfaces), independent of how coarse the display mesh is. Mesh
formats are integrated over their triangles.

The judgement is strict: a part with any open shell, loose face or gap gets
no volume at all. A partial volume (the closed bodies of a part, minus an
open one) would make the weight silently too small, which is worse than
showing none — the user then knows to check the model.

Mesh formats: the display blob splits vertices along sharp edges (flat
shading), so the triangles no longer share vertices there. They are merged
back by position before the closed/winding checks; otherwise every box-like
STL would read as open.

Lengths are mm: OCCT converts STEP/IGES to mm on reading; mesh formats carry
no unit and are taken as mm (the UI says so).
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import trimesh
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHAPE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_ShapeEnum
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape

from .meshpack import unpack_parts

log = logging.getLogger(__name__)

# reasons a part has no volume
OPEN, NO_FACES, DEGENERATE, WINDING, FAILED = "open", "no_faces", "degenerate", "winding", "failed"
# |body volume| <= this * bbox_diag**3 -> flat (sheet-like), not a solid
_DEGENERATE_REL = 1e-9


def _shapes(shape: TopoDS_Shape, kind: TopAbs_ShapeEnum, avoid: TopAbs_ShapeEnum = TopAbs_SHAPE) -> list[TopoDS_Shape]:
    out = []
    e = TopExp_Explorer(shape, kind, avoid)
    while e.More():
        out.append(e.Current())
        e.Next()
    return out


def _volume(shape: TopoDS_Shape) -> tuple[float, tuple[float, float, float]]:
    """signed volume and centroid (OCCT handles hollow solids by shell orientation)"""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    c = props.CentreOfMass()
    return props.Mass(), (c.X(), c.Y(), c.Z())


def _combine(bodies: list[tuple[float, tuple[float, float, float]]]) -> tuple[float, list[float] | None]:
    """sum of |V| and the |V|-weighted centroid: a body turned inside out
    (negative volume) must not cancel another"""
    total = sum(abs(v) for v, _ in bodies)
    if total <= 0:
        return 0.0, None
    com = [sum(abs(v) * c[i] for v, c in bodies) / total for i in range(3)]
    return total, com


def _diag(shape: TopoDS_Shape) -> float:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return 0.0
    x0, y0, z0, x1, y1, z1 = box.Get()
    return math.dist((x0, y0, z0), (x1, y1, z1))


def _part(closed: bool, volume, area, com, reason) -> dict[str, Any]:
    return {"closed": closed, "volume": volume, "area": area, "centerOfMass": com, "reason": reason}


def brep_part_properties(shape: TopoDS_Shape) -> dict[str, Any]:
    """closed / volume / area / centerOfMass / reason of one B-rep part"""
    try:
        if not _shapes(shape, TopAbs_FACE):
            return _part(False, None, 0.0, None, NO_FACES)  # curves / points only
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, props)
        area = props.Mass()

        bodies = []
        is_open = False
        for solid in _shapes(shape, TopAbs_SOLID):
            shells = _shapes(solid, TopAbs_SHELL)
            # IsClosed on the solid itself is unreliable (False for a plain
            # cylinder); check every shell instead
            if shells and all(BRep_Tool.IsClosed_s(s) for s in shells):
                bodies.append(_volume(solid))
            else:
                is_open = True
        for shell in _shapes(shape, TopAbs_SHELL, TopAbs_SOLID):
            # a closed shell outside any solid (STEP surface models, sewn but
            # not made solid) still bounds a volume
            if BRep_Tool.IsClosed_s(shell):
                bodies.append(_volume(shell))
            else:
                is_open = True
        if _shapes(shape, TopAbs_FACE, TopAbs_SHELL):
            is_open = True  # loose faces
        if is_open:
            return _part(False, None, area, None, OPEN)
        volume, com = _combine(bodies)
        if volume <= _DEGENERATE_REL * _diag(shape) ** 3:
            return _part(False, None, area, None, DEGENERATE)
        return _part(True, volume, area, com, None)
    except Exception:  # OCCT can throw on broken geometry: report, keep the other parts
        log.exception("properties failed for a part")
        return _part(False, None, None, None, FAILED)


def mesh_part_properties(positions: np.ndarray, indices: np.ndarray) -> dict[str, Any]:
    """the same for a triangle mesh (vertices merged by position first)"""
    try:
        if len(indices) == 0:
            return _part(False, None, 0.0, None, NO_FACES)
        m = trimesh.Trimesh(
            np.asarray(positions, dtype=np.float64), np.asarray(indices, dtype=np.int64), process=True
        )
        area = float(m.area)
        if not m.is_watertight:
            return _part(False, None, area, None, OPEN)
        if not m.is_winding_consistent:
            return _part(False, None, area, None, WINDING)
        diag = float(np.linalg.norm(m.extents))
        volume = abs(float(m.volume))
        if volume <= _DEGENERATE_REL * diag**3:
            return _part(False, None, area, None, DEGENERATE)
        # a hollow STL's inner shell faces inward, so its signed volume is
        # subtracted; center_mass follows the same signed integral
        return _part(True, volume, area, [float(x) for x in m.center_mass], None)
    except Exception:
        log.exception("properties failed for a mesh part")
        return _part(False, None, None, None, FAILED)


def _model(source: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [p for p in parts if p["volume"] is not None]
    total: dict[str, Any] = {"volume": None, "area": None, "centerOfMass": None}
    if closed:
        volume = sum(p["volume"] for p in closed)
        total = {
            "volume": volume,
            "area": sum(p["area"] for p in closed),
            "centerOfMass": [sum(p["volume"] * p["centerOfMass"][i] for p in closed) / volume for i in range(3)],
        }
    total["closedParts"] = len(closed)
    total["openParts"] = len(parts) - len(closed)
    return {"source": source, "units": "mm", "parts": parts, "total": total}


def brep_properties(meshes) -> dict[str, Any]:
    """per part of a B-rep model (tessellation.PartMesh list)"""
    return _model(
        "brep",
        [{"id": m.part.part_id, "name": m.part.name, **brep_part_properties(m.part.shape)} for m in meshes],
    )


def mesh_properties(blob: bytes) -> dict[str, Any]:
    """per part of a mesh-format model, from its packed display blob"""
    _header, parts = unpack_parts(blob)
    return _model(
        "mesh",
        [{"id": p["id"], "name": p["name"], **mesh_part_properties(p["positions"], p["indices"])} for p in parts],
    )
