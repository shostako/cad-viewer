"""Exact B-rep measurements (the whole point of this app).

The frontend picks entities on the tessellated mesh (an approximation);
every measurement here is computed on the original B-rep, so the values
are exact regardless of tessellation deflection.

Entity reference (from the frontend):
    {"partId": 0, "kind": "face"|"edge"|"vertex", "id": 12}
    {"kind": "point", "xyz": [x, y, z]}   # snapped vertex / arbitrary point
"""
from __future__ import annotations

from typing import Any

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_CurveType,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_SurfaceType,
)
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS, TopoDS_Shape

from .tessellation import PartMesh


class MeasureError(Exception):
    pass


def _resolve(ref: dict[str, Any], meshes: list[PartMesh]) -> TopoDS_Shape:
    kind = ref.get("kind")
    if kind == "point":
        x, y, z = ref["xyz"]
        return BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Vertex()

    part_id = ref.get("partId")
    ent_id = ref.get("id")
    if part_id is None or ent_id is None:
        raise MeasureError(f"invalid entity ref: {ref}")
    mesh = next((m for m in meshes if m.part.part_id == part_id), None)
    if mesh is None:
        raise MeasureError(f"unknown partId: {part_id}")

    topo_map = {"face": mesh.face_map, "edge": mesh.edge_map, "vertex": mesh.vertex_map}.get(kind)
    if topo_map is None:
        raise MeasureError(f"unknown entity kind: {kind}")
    if not (1 <= ent_id <= topo_map.Extent()):
        raise MeasureError(f"{kind} id {ent_id} out of range (1..{topo_map.Extent()})")
    return topo_map.FindKey(ent_id)


def distance(a: dict, b: dict, meshes: list[PartMesh]) -> dict[str, Any]:
    """Exact minimum distance between two entities (BRepExtrema)."""
    sa, sb = _resolve(a, meshes), _resolve(b, meshes)
    ext = BRepExtrema_DistShapeShape(sa, sb)
    if not ext.IsDone() or ext.NbSolution() < 1:
        raise MeasureError("distance computation failed")
    pa, pb = ext.PointOnShape1(1), ext.PointOnShape2(1)
    return {
        "type": "distance",
        "value": ext.Value(),
        "pointA": [pa.X(), pa.Y(), pa.Z()],
        "pointB": [pb.X(), pb.Y(), pb.Z()],
    }


def edge_info(ref: dict, meshes: list[PartMesh]) -> dict[str, Any]:
    """Edge length; plus radius/center/diameter when the edge is circular."""
    shape = _resolve(ref, meshes)
    edge = TopoDS.Edge_s(shape)

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    length = props.Mass()

    out: dict[str, Any] = {"type": "edge", "length": length}
    curve = BRepAdaptor_Curve(edge)
    if curve.GetType() == GeomAbs_Circle:
        circ = curve.Circle()
        c = circ.Location()
        ax = circ.Axis().Direction()
        out.update(
            {
                "curve": "circle",
                "radius": circ.Radius(),
                "diameter": 2 * circ.Radius(),
                "center": [c.X(), c.Y(), c.Z()],
                "axis": [ax.X(), ax.Y(), ax.Z()],
            }
        )
    else:
        out["curve"] = GeomAbs_CurveType(curve.GetType()).name.removeprefix("GeomAbs_").lower()
    return out


def face_info(ref: dict, meshes: list[PartMesh]) -> dict[str, Any]:
    """Face area; plus cylinder radius/axis (hole/boss) or plane normal."""
    shape = _resolve(ref, meshes)
    face = TopoDS.Face_s(shape)

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    area = props.Mass()

    out: dict[str, Any] = {"type": "face", "area": area}
    surf = BRepAdaptor_Surface(face)
    stype = surf.GetType()
    if stype == GeomAbs_Cylinder:
        cyl = surf.Cylinder()
        c = cyl.Location()
        ax = cyl.Axis().Direction()
        out.update(
            {
                "surface": "cylinder",
                "radius": cyl.Radius(),
                "diameter": 2 * cyl.Radius(),
                "center": [c.X(), c.Y(), c.Z()],
                "axis": [ax.X(), ax.Y(), ax.Z()],
            }
        )
    elif stype == GeomAbs_Plane:
        pln = surf.Plane()
        n = pln.Axis().Direction()
        out.update({"surface": "plane", "normal": [n.X(), n.Y(), n.Z()]})
    else:
        out["surface"] = GeomAbs_SurfaceType(stype).name.removeprefix("GeomAbs_").lower()
    return out


def run(request: dict[str, Any], meshes: list[PartMesh]) -> dict[str, Any]:
    mtype = request.get("type")
    if mtype == "distance":
        return distance(request["a"], request["b"], meshes)
    if mtype == "edge_info":
        return edge_info(request["ref"], meshes)
    if mtype == "face_info":
        return face_info(request["ref"], meshes)
    raise MeasureError(f"unknown measurement type: {mtype}")
