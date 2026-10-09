"""Exact B-rep measurements (the whole point of this app).

The frontend picks entities on the tessellated mesh (an approximation);
every measurement here is computed on the original B-rep, so the values
are exact regardless of tessellation deflection.

Entity reference (from the frontend):
    {"partId": 0, "kind": "face"|"edge"|"vertex", "id": 12}
    {"kind": "point", "xyz": [x, y, z]}   # snapped vertex / arbitrary point

A distance request may also carry "nearA" / "nearB": the points the user
clicked. They never change the value; they choose where the dimension line
is drawn when the minimum is reached at many places (two parallel faces:
anywhere they overlap), so that the line stands where the user clicked.
"""
from __future__ import annotations

from typing import Any

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_CurveType,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_SurfaceType,
)
from OCP.gp import gp_Pln, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN, TopAbs_ON
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape

from .tessellation import PartMesh


class MeasureError(Exception):
    pass


# the two planes count as parallel when |na x nb| of their unit normals is at most this
PARALLEL_SIN = 1e-9
# mm: a dimension line put through a click must be as long as the value, this closely
LINE_TOL = 1e-7


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


def distance(
    a: dict,
    b: dict,
    meshes: list[PartMesh],
    near_a: list[float] | None = None,
    near_b: list[float] | None = None,
) -> dict[str, Any]:
    """Exact minimum distance between two entities (BRepExtrema).

    near_a / near_b (the clicked points, optional) choose the dimension line
    among equally short ones; the value is the same either way.
    """
    sa, sb = _resolve(a, meshes), _resolve(b, meshes)
    ext = BRepExtrema_DistShapeShape(sa, sb)
    if not ext.IsDone() or ext.NbSolution() < 1:
        raise MeasureError("distance computation failed")
    value = ext.Value()
    line = _parallel_faces_line(sa, sb, near_a, near_b)
    # the line through a click must realise the value: planes that are only
    # nearly parallel pass the parallel test, yet drift apart across the faces
    if line is not None and abs(line[0].Distance(line[1]) - value) > LINE_TOL:
        line = None
    if line is None:
        i = _nearest_solution(ext, near_a, near_b)
        line = (ext.PointOnShape1(i), ext.PointOnShape2(i))
    pa, pb = line
    return {
        "type": "distance",
        "value": value,
        "pointA": [pa.X(), pa.Y(), pa.Z()],
        "pointB": [pb.X(), pb.Y(), pb.Z()],
    }


def _nearest_solution(ext: BRepExtrema_DistShapeShape, near_a, near_b) -> int:
    """the solution (1-based) whose ends are nearest the clicked points; 1 without them"""
    if near_a is None and near_b is None:
        return 1
    qa = gp_Pnt(*near_a) if near_a is not None else None
    qb = gp_Pnt(*near_b) if near_b is not None else None
    best, best_d = 1, float("inf")
    for i in range(1, ext.NbSolution() + 1):
        d = (ext.PointOnShape1(i).Distance(qa) if qa else 0.0) + (ext.PointOnShape2(i).Distance(qb) if qb else 0.0)
        if d < best_d:
            best, best_d = i, d
    return best


def _plane_of(shape: TopoDS_Shape) -> tuple[TopoDS_Face, gp_Pln] | None:
    if shape.ShapeType() != TopAbs_FACE:
        return None
    face = TopoDS.Face_s(shape)
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_Plane:
        return None
    return face, surf.Plane()


def _on_face(face: TopoDS_Face, p: gp_Pnt, tol: float) -> bool:
    return BRepClass_FaceClassifier(face, p, tol).State() in (TopAbs_IN, TopAbs_ON)


def _parallel_faces_line(sa, sb, near_a, near_b) -> tuple[gp_Pnt, gp_Pnt] | None:
    """Two parallel planar faces: the minimum is reached wherever they overlap
    (seen along their normal), and BRepExtrema returns only a few of those
    places (often corners). Put the line through a clicked point instead: the
    click on one face, dropped onto its plane, and its foot on the other
    plane, when both lie on their faces. None when they do not (the general
    case keeps BRepExtrema's solutions)."""
    fa, fb = _plane_of(sa), _plane_of(sb)
    if fa is None or fb is None:
        return None
    (face_a, pln_a), (face_b, pln_b) = fa, fb
    na, nb = pln_a.Axis().Direction(), pln_b.Axis().Direction()
    # gp_Vec: gp_Dir.Crossed raises on parallel directions (a zero result)
    if gp_Vec(na).Crossed(gp_Vec(nb)).Magnitude() > PARALLEL_SIN:
        return None
    for near, src_face, src_pln, dst_face, dst_pln, from_a in (
        (near_a, face_a, pln_a, face_b, pln_b, True),
        (near_b, face_b, pln_b, face_a, pln_a, False),
    ):
        if near is None:
            continue
        p = _project(gp_Pnt(*near), src_pln)
        q = _project(p, dst_pln)
        # both feet on their faces: the faces overlap there, so the planes' gap
        # (|pq|) is the minimum distance itself
        if _on_face(src_face, p, 1e-6) and _on_face(dst_face, q, 1e-6):
            return (p, q) if from_a else (q, p)
    return None


def _project(p: gp_Pnt, pln: gp_Pln) -> gp_Pnt:
    """the foot of p on the plane"""
    n = pln.Axis().Direction()
    d = gp_Vec(pln.Location(), p).Dot(gp_Vec(n))
    return gp_Pnt(p.X() - d * n.X(), p.Y() - d * n.Y(), p.Z() - d * n.Z())


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
        return distance(request["a"], request["b"], meshes, request.get("nearA"), request.get("nearB"))
    if mtype == "edge_info":
        return edge_info(request["ref"], meshes)
    if mtype == "face_info":
        return face_info(request["ref"], meshes)
    raise MeasureError(f"unknown measurement type: {mtype}")
