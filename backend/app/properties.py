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

Orientation matters as much as closure: a closed shell whose faces disagree
on which side is outside (B-rep), or a mesh body turned inside out, would make
the signed volume integral cancel part of the body. A B-rep shell with mixed
face orientation gets no volume (reason "winding"). A mesh is split into
connected bodies: an inward-facing body inside another is a cavity and is
subtracted; an inward-facing body anywhere else is a body turned inside out and
counts with its absolute volume (as a B-rep body turned inside out does).

Known limit: bodies that overlap inside one part are summed, not united.

Totals: volume, weight and centre of mass come from the parts with a volume;
the area total counts every part with faces (an open surface has an area too).

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
from OCP.ShapeAnalysis import ShapeAnalysis_Shell
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


def _mixed_orientation(shell: TopoDS_Shape) -> bool:
    """a closed shell whose faces disagree on which side is outside: some edge
    is used twice in the same direction. BRep_Tool.IsClosed ignores
    orientation, and the signed volume integral then cancels part of the body
    (a 10x20x30 box with one face flipped reads 4000 mm3, not 6000)."""
    sas = ShapeAnalysis_Shell()
    sas.LoadShells(shell)
    return bool(sas.CheckOrientedShells(shell, True))


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
        mixed = False
        for solid in _shapes(shape, TopAbs_SOLID):
            shells = _shapes(solid, TopAbs_SHELL)
            # IsClosed on the solid itself is unreliable (False for a plain
            # cylinder); check every shell instead
            if shells and all(BRep_Tool.IsClosed_s(s) for s in shells):
                if any(_mixed_orientation(s) for s in shells):
                    mixed = True
                else:
                    bodies.append(_volume(solid))
            else:
                is_open = True
        for shell in _shapes(shape, TopAbs_SHELL, TopAbs_SOLID):
            # a closed shell outside any solid (STEP surface models, sewn but
            # not made solid) still bounds a volume
            if not BRep_Tool.IsClosed_s(shell):
                is_open = True
            elif _mixed_orientation(shell):
                mixed = True
            else:
                bodies.append(_volume(shell))
        if _shapes(shape, TopAbs_FACE, TopAbs_SHELL):
            is_open = True  # loose faces
        if is_open:
            return _part(False, None, area, None, OPEN)
        if mixed:
            return _part(False, None, area, None, WINDING)
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
        volume, com = _mesh_bodies(m)
        if volume <= _DEGENERATE_REL * diag**3:
            return _part(False, None, area, None, DEGENERATE)
        return _part(True, volume, area, com, None)
    except Exception:
        log.exception("properties failed for a mesh part")
        return _part(False, None, None, None, FAILED)


def _mesh_bodies(m: trimesh.Trimesh) -> tuple[float, list[float]]:
    """volume and centre of mass of a closed, consistently wound mesh, body by
    body. An inward-facing body inside an outward one is a cavity (subtracted);
    any other inward-facing body is a body turned inside out (added with its
    absolute volume). Summing the signed volumes of the whole mesh would
    subtract a separate inverted body (6000 + inverted 1000 read 5000)."""
    bodies = m.split(only_watertight=False) if m.body_count > 1 else [m]
    signed = [(b, float(b.volume)) for b in bodies]
    outward = [b for b, v in signed if v > 0]
    total = 0.0
    moment = np.zeros(3)
    for b, v in signed:
        cavity = v < 0 and any(_inside(b, o) for o in outward)
        w = -abs(v) if cavity else abs(v)
        total += w
        moment += w * np.asarray(b.center_mass, dtype=np.float64)
    if total <= 0:
        return 0.0, [float(x) for x in m.center_mass]
    return total, [float(x) for x in moment / total]


def _inside(inner: trimesh.Trimesh, outer: trimesh.Trimesh) -> bool:
    lo, hi = outer.bounds
    ilo, ihi = inner.bounds
    if (ilo < lo).any() or (ihi > hi).any():
        return False
    return bool(outer.contains(inner.vertices[:1])[0])


def _model(source: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [p for p in parts if p["volume"] is not None]
    with_area = [p for p in parts if p["area"] is not None]
    total: dict[str, Any] = {
        "volume": None,
        # every part with faces: an open surface has an area too
        "area": sum(p["area"] for p in with_area) if with_area else None,
        "centerOfMass": None,
    }
    if closed:
        volume = sum(p["volume"] for p in closed)
        total["volume"] = volume
        total["centerOfMass"] = [
            sum(p["volume"] * p["centerOfMass"][i] for p in closed) / volume for i in range(3)
        ]
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
