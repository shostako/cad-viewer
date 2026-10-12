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

The distance's answer carries "delta": the dimension line from its end on A
to its end on B, along the axes. Between two flat things (planar faces,
straight edges, one of each) that are not parallel, it also carries "angle":
their angle in degrees, 0 to 90 (angle_between).

A distance request's "mode" (default "min") asks for another distance
between the same two entities, its answer shaped as the shortest's (value,
pointA, pointB, delta; "mode" says which):
- "centre": between their centres (centre_distance). A point for a vertex, a
  circle, an ellipse, a sphere; an axis for a cylinder, a cone, a torus. Two
  axes must be parallel (the distance between their lines).
- "max": the largest distance between their points, for vertices and edges
  (max_distance).
A pair that has no such distance answers {"unavailable": why} instead (a plane
has no centre, crossed axes, a face's largest distance), never a stand-in.

A vertex (vertex_info) says its point.

A face also says its boundary (face_info): "perimeter", the length of its
outer loop, and "holes", the lengths of its inner loops (a plate's holes, the
foot of a boss), each without the seam edges a closed surface is cut along
(a cylinder's outer loop is its two circles). An edge says its "length".

A face or an edge (face_info, edge_info) says its size by its kind:
- cylinder, circle: "radius" and "diameter", and "full" (a whole turn: a hole
  or a boss, told by ⌀; a part of a turn, a fillet or a rounded corner, by R)
- torus: "radius", the small one (a fillet around a circle); sphere: "radius";
  cone: "angle", its half angle in degrees (the draft of a drafted boss)
- a B-spline face or edge that is one of these within RECOGNIZE_TOL counts as
  that kind ("recognized": true): files written as B-splines (IGES often) have
  their holes and fillets told the same way
- anything else, given "near" (the clicked point): "localRadius", the smallest
  radius of curvature of the true surface or curve at the point nearest to it
  ("at"), when it is curved at all
"""
from __future__ import annotations

import logging
import math
from typing import Any

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_CLProps, BRepLProp_SLProps
from OCP.Extrema import Extrema_ExtPC
from OCP.GCPnts import GCPnts_UniformAbscissa
from OCP.GeomAbs import (
    GeomAbs_BezierCurve,
    GeomAbs_BezierSurface,
    GeomAbs_BSplineCurve,
    GeomAbs_BSplineSurface,
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_CurveType,
    GeomAbs_Cylinder,
    GeomAbs_Ellipse,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceType,
    GeomAbs_Torus,
)
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.gp import gp_Ax1, gp_Circ, gp_Cone, gp_Cylinder, gp_Pln, gp_Pnt, gp_Sphere, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.ShapeAnalysis import ShapeAnalysis_CanonicalRecognition
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Shape

from .tessellation import PartMesh


class MeasureError(Exception):
    pass


# the two planes count as parallel when |na x nb| of their unit normals is at most this.
# Only a first cut: the line through a click must also be as long as the value
# (LINE_TOL), and that check is the one that holds (planes 1e-9 rad apart drift
# by 1e-6 mm over a metre, past LINE_TOL), so tightening this changes nothing
PARALLEL_SIN = 1e-9
# mm: a dimension line put through a click must be as long as the value, this closely
LINE_TOL = 1e-7
# degrees: at or below this, two flat things are parallel and no angle is given
ANGLE_MIN_DEG = 1e-6
# mm: a B-spline face or edge within this of a cylinder, a sphere, a cone or a
# circle counts as one. A tenth of the last digit shown (0.001 mm): the value
# shown is that of the shape the file meant
RECOGNIZE_TOL = 1e-4
# 1/mm: a curvature at or below this is flat (a radius over 100 m): no radius
CURVATURE_MIN = 1e-5
# rad: a circle this short of a whole turn is still whole
TURN_TOL = 1e-9
# two axes count as parallel when the sine of their angle is at most this (a
# micrometre over a metre); the centre distance of axes is that of parallel ones
AXIS_PARALLEL_SIN = 1e-6
# points along each edge (evenly by length) where the farthest pair of two edges is first looked for
MAX_SAMPLES = 64
# the farthest pairs among those (each a peak of the sampled distances) climbed from
MAX_STARTS = 16


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

    if kind == "part":  # a whole part (選択: 部品): its shape, every solid and face of it
        return mesh.part.shape
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
    mode: str = "min",
) -> dict[str, Any]:
    """Exact minimum distance between two entities (BRepExtrema); with mode
    "centre" the distance between their centres (centre_distance), with "max"
    the largest distance between their points (max_distance).

    near_a / near_b (the clicked points, optional) choose the dimension line
    among equally short ones; the value is the same either way.
    """
    sa, sb = _resolve(a, meshes), _resolve(b, meshes)
    if mode != "min":
        # a whole part has neither, whatever its shape is (a part of one
        # cylindrical face, or of one edge, is still the part): said by the ref
        for ref, which in ((a, "1 点目"), (b, "2 点目")):
            if ref.get("kind") == "part":
                return _unavailable(mode, f"{which}: {PART_HAS_NO[mode]}")
    if mode == "centre":
        return centre_distance(sa, sb, near_a)
    if mode == "max":
        return max_distance(sa, sb)
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
    out: dict[str, Any] = {
        "type": "distance",
        "value": value,
        "pointA": [pa.X(), pa.Y(), pa.Z()],
        "pointB": [pb.X(), pb.Y(), pb.Z()],
        # from A to B along the axes (the line's own ends: exact, as the value)
        "delta": [pb.X() - pa.X(), pb.Y() - pa.Y(), pb.Z() - pa.Z()],
    }
    ang = angle_between(sa, sb)
    if ang is not None and ang > ANGLE_MIN_DEG:
        out["angle"] = ang
    return out


# why a whole part (選択: 部品) has no distance of the mode
PART_HAS_NO = {
    "centre": "部品全体に中心はない",
    "max": "部品全体の最大の距離は出さない（頂点か稜線を選ぶ）",
}


def _unavailable(mode: str, why: str) -> dict[str, Any]:
    """a distance that this pair does not have: said why, nothing measured"""
    return {"type": "distance", "mode": mode, "unavailable": why}


def _answer(mode: str, pa: gp_Pnt, pb: gp_Pnt) -> dict[str, Any]:
    return {
        "type": "distance",
        "mode": mode,
        "value": pa.Distance(pb),
        "pointA": _xyz(pa),
        "pointB": _xyz(pb),
        "delta": [pb.X() - pa.X(), pb.Y() - pa.Y(), pb.Z() - pa.Z()],
    }


def _centre(shape: TopoDS_Shape) -> tuple[str, Any]:
    """What a shape is centred on: ("point", gp_Pnt) for a vertex, a circle or
    an ellipse, a sphere; ("axis", gp_Ax1) for a cylinder, a cone or a torus
    (B-spline ones recognised as such too); ("none", why) for the rest."""
    kind = shape.ShapeType()
    if kind == TopAbs_VERTEX:
        return "point", BRep_Tool.Pnt_s(TopoDS.Vertex_s(shape))
    if kind == TopAbs_EDGE:
        edge = TopoDS.Edge_s(shape)
        curve = BRepAdaptor_Curve(edge)
        ctype = curve.GetType()
        if ctype == GeomAbs_Circle:
            return "point", curve.Circle().Location()
        if ctype == GeomAbs_Ellipse:
            return "point", curve.Ellipse().Location()
        if ctype in (GeomAbs_BSplineCurve, GeomAbs_BezierCurve):
            circ = gp_Circ()
            if ShapeAnalysis_CanonicalRecognition(edge).IsCircle(RECOGNIZE_TOL, circ):
                return "point", circ.Location()
        if ctype == GeomAbs_Line:
            return "none", "直線の稜線に中心はない"
        return "none", "この稜線に中心はない（円でも楕円でもない）"
    if kind != TopAbs_FACE:
        return "none", "部品全体に中心はない"
    face = TopoDS.Face_s(shape)
    surf = BRepAdaptor_Surface(face)
    stype = surf.GetType()
    name, geom = {
        GeomAbs_Cylinder: ("cylinder", surf.Cylinder),
        GeomAbs_Cone: ("cone", surf.Cone),
        GeomAbs_Torus: ("torus", surf.Torus),
        GeomAbs_Sphere: ("sphere", surf.Sphere),
        GeomAbs_Plane: ("plane", None),
    }.get(stype, (None, None))
    geom = geom() if geom else None
    if name is None and stype in (GeomAbs_BSplineSurface, GeomAbs_BezierSurface):
        name, geom = _recognize(face) or (None, None)
    if name in ("cylinder", "cone", "torus"):
        return "axis", geom.Axis()
    if name == "sphere":
        return "point", geom.Location()
    if name == "plane":
        return "none", "平面に中心はない"
    return "none", "この面に中心はない（円筒・円錐・球・トーラスでない）"


def _foot(p: gp_Pnt, ax: gp_Ax1) -> gp_Pnt:
    """the point of the axis's line nearest to p"""
    d = gp_Vec(ax.Direction())
    return ax.Location().Translated(d.Multiplied(gp_Vec(ax.Location(), p).Dot(d)))


def centre_distance(sa: TopoDS_Shape, sb: TopoDS_Shape, near_a=None) -> dict[str, Any]:
    """The distance between the centres of two entities (_centre): two points,
    a point and an axis (to the axis's line), two parallel axes (between their
    lines: the line drawn across at the click on A). An entity without a centre,
    or axes that are not parallel, have none: said why."""
    (ka, ca), (kb, cb) = _centre(sa), _centre(sb)
    for k, c, which in ((ka, ca, "1 点目"), (kb, cb, "2 点目")):
        if k == "none":
            return _unavailable("centre", f"{which}: {c}")
    if ka == "point" and kb == "point":
        pa, pb = ca, cb
    elif ka == "point":
        pa, pb = ca, _foot(ca, cb)
    elif kb == "point":
        pa, pb = _foot(cb, ca), cb
    else:
        sin = gp_Vec(ca.Direction()).Crossed(gp_Vec(cb.Direction())).Magnitude()
        if sin > AXIS_PARALLEL_SIN:
            return _unavailable("centre", f"軸が平行でない（{math.degrees(math.asin(min(1.0, sin))):.1f}°）")
        pa = _foot(gp_Pnt(*near_a) if near_a is not None else ca.Location(), ca)
        pb = _foot(pa, cb)
    return _answer("centre", pa, pb)


def _farthest_on(curve: BRepAdaptor_Curve, p: gp_Pnt) -> gp_Pnt:
    """the point of the curve farthest from p, exactly: its ends or a point
    where the distance is extreme (Extrema_ExtPC gives them all)"""
    cands = [curve.Value(curve.FirstParameter()), curve.Value(curve.LastParameter())]
    ext = Extrema_ExtPC(p, curve)
    if ext.IsDone():
        cands += [ext.Point(i).Value() for i in range(1, ext.NbExt() + 1)]
    return max(cands, key=lambda q: q.SquareDistance(p))


def max_distance(sa: TopoDS_Shape, sb: TopoDS_Shape) -> dict[str, Any]:
    """The largest distance between a point of A and a point of B, for vertices
    and edges (a face's largest needs a definition first: said so).

    A vertex and an edge: the farthest point of the edge, exactly. Two edges:
    MAX_SAMPLES points along each, evenly by length (a narrow lobe of a spline
    still has its length: it gets points). Every pair that is farther than the
    pairs around it is a start (up to MAX_STARTS, the farthest): from there, each
    end in turn moves to the exactly farthest point of the other edge until the
    pair grows no more (lines end at their ends, circles at their far points).
    The farthest pair reached is the answer. A search, not a proof: a lobe
    shorter than the spacing of the points could be missed (exact for a vertex
    and an edge, and for lines and circles)."""
    kinds = []
    for shape, which in ((sa, "1 点目"), (sb, "2 点目")):
        kind = shape.ShapeType()
        if kind not in (TopAbs_VERTEX, TopAbs_EDGE):
            what = "面" if kind == TopAbs_FACE else "部品全体"
            return _unavailable("max", f"{which}: {what}の最大の距離は出さない（頂点か稜線を選ぶ）")
        kinds.append(kind)
    if kinds == [TopAbs_VERTEX, TopAbs_VERTEX]:
        return _answer("max", BRep_Tool.Pnt_s(TopoDS.Vertex_s(sa)), BRep_Tool.Pnt_s(TopoDS.Vertex_s(sb)))
    if kinds[0] == TopAbs_VERTEX:
        pa = BRep_Tool.Pnt_s(TopoDS.Vertex_s(sa))
        return _answer("max", pa, _farthest_on(BRepAdaptor_Curve(TopoDS.Edge_s(sb)), pa))
    if kinds[1] == TopAbs_VERTEX:
        pb = BRep_Tool.Pnt_s(TopoDS.Vertex_s(sb))
        return _answer("max", _farthest_on(BRepAdaptor_Curve(TopoDS.Edge_s(sa)), pb), pb)
    ca, cb = BRepAdaptor_Curve(TopoDS.Edge_s(sa)), BRepAdaptor_Curve(TopoDS.Edge_s(sb))
    pts_a, pts_b = _along(ca), _along(cb)
    d2 = [[p.SquareDistance(q) for q in pts_b] for p in pts_a]
    n, m = len(pts_a), len(pts_b)

    def peak(i: int, j: int) -> bool:
        return all(d2[i][j] >= d2[k][l] for k in (i - 1, i, i + 1) for l in (j - 1, j, j + 1) if 0 <= k < n and 0 <= l < m)

    starts = sorted((d2[i][j], i, j) for i in range(n) for j in range(m) if peak(i, j))[-MAX_STARTS:]
    best: tuple[gp_Pnt, gp_Pnt] | None = None
    for _, i, j in starts:
        pa, pb = _climb(ca, cb, pts_a[i], pts_b[j])
        if best is None or pa.SquareDistance(pb) > best[0].SquareDistance(best[1]):
            best = (pa, pb)
    return _answer("max", *best)


def _along(c: BRepAdaptor_Curve) -> list[gp_Pnt]:
    """MAX_SAMPLES points evenly spread by length along the curve (by parameter if that fails)"""
    try:
        ua = GCPnts_UniformAbscissa(c, MAX_SAMPLES)
        if ua.IsDone() and ua.NbPoints() >= 2:
            return [c.Value(ua.Parameter(i)) for i in range(1, ua.NbPoints() + 1)]
    except Exception as e:  # an adaptor the length cannot be taken of: by parameter
        logging.getLogger(__name__).debug("points by parameter (no length along the curve): %s", e)
    u0, u1 = c.FirstParameter(), c.LastParameter()
    return [c.Value(u0 + (u1 - u0) * i / (MAX_SAMPLES - 1)) for i in range(MAX_SAMPLES)]


def _climb(ca: BRepAdaptor_Curve, cb: BRepAdaptor_Curve, pa: gp_Pnt, pb: gp_Pnt) -> tuple[gp_Pnt, gp_Pnt]:
    """from (pa, pb), each end in turn to the exactly farthest point of the other curve, until it grows no more"""
    for _ in range(100):
        qb = _farthest_on(cb, pa)
        qa = _farthest_on(ca, qb)
        gain = qa.Distance(qb) - pa.Distance(pb)
        if gain >= 0:
            pa, pb = qa, qb  # the exact points, also when they gained nothing
        if gain <= 1e-12:
            break
    return pa, pb


def _flat(shape: TopoDS_Shape) -> tuple[str, gp_Vec] | None:
    """('plane', its normal) for a planar face, ('line', its direction) for a
    straight edge; None for anything else (a cylinder, a circle, a vertex)"""
    if shape.ShapeType() == TopAbs_FACE:
        surf = BRepAdaptor_Surface(TopoDS.Face_s(shape))
        if surf.GetType() == GeomAbs_Plane:
            return "plane", gp_Vec(surf.Plane().Axis().Direction())
    elif shape.ShapeType() == TopAbs_EDGE:
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
        if curve.GetType() == GeomAbs_Line:
            return "line", gp_Vec(curve.Line().Direction())
    return None


def angle_between(sa: TopoDS_Shape, sb: TopoDS_Shape) -> float | None:
    """The angle in degrees (0..90) between two planes, two straight lines, or a
    line and a plane; None when either is not flat. Between planes it is the
    angle of their normals, between lines that of their directions (either way
    round: 0..90), and a line's angle to a plane is 90 less its angle to the
    plane's normal. atan2 of |cross| and |dot| keeps small angles exact (acos
    loses them near 1)."""
    fa, fb = _flat(sa), _flat(sb)
    if fa is None or fb is None:
        return None
    (ka, va), (kb, vb) = fa, fb
    deg = math.degrees(math.atan2(va.Crossed(vb).Magnitude(), abs(va.Dot(vb))))
    return 90.0 - deg if ka != kb else deg


def _nearest_solution(ext: BRepExtrema_DistShapeShape, near_a, near_b) -> int:
    """the solution (1-based) whose ends are nearest the clicked points; 1 without them"""
    if near_a is None and near_b is None:
        return 1
    qa = gp_Pnt(*near_a) if near_a is not None else None
    qb = gp_Pnt(*near_b) if near_b is not None else None
    best, best_d = 1, float("inf")
    for i in range(1, ext.NbSolution() + 1):
        d = (ext.PointOnShape1(i).Distance(qa) if qa is not None else 0.0) + (
            ext.PointOnShape2(i).Distance(qb) if qb is not None else 0.0
        )
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


def _xyz(p) -> list[float]:
    return [p.X(), p.Y(), p.Z()]


def _circle(circ: gp_Circ, full: bool) -> dict[str, Any]:
    return {
        "curve": "circle",
        "radius": circ.Radius(),
        "diameter": 2 * circ.Radius(),
        "center": _xyz(circ.Location()),
        "axis": _xyz(circ.Axis().Direction()),
        "full": full,
    }


def _curve_radius_near(curve: BRepAdaptor_Curve, near: tuple[float, float, float]) -> dict[str, Any]:
    """the curve's radius of curvature at its point nearest to `near` (its ends count)"""
    q = gp_Pnt(*near)
    params = [curve.FirstParameter(), curve.LastParameter()]
    ext = Extrema_ExtPC(q, curve)
    if ext.IsDone():
        params += [ext.Point(i).Parameter() for i in range(1, ext.NbExt() + 1)]
    t = min(params, key=lambda u: curve.Value(u).SquareDistance(q))
    props = BRepLProp_CLProps(curve, t, 2, 1e-9)
    if not props.IsTangentDefined():
        return {}
    k = abs(props.Curvature())
    if k <= CURVATURE_MIN:
        return {}
    return {"localRadius": 1 / k, "at": _xyz(props.Value())}


def edge_info(ref: dict, meshes: list[PartMesh], near=None) -> dict[str, Any]:
    """Edge length; plus its radius when it is (part of) a circle; otherwise,
    given the clicked point, the radius of curvature there."""
    shape = _resolve(ref, meshes)
    edge = TopoDS.Edge_s(shape)

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    out: dict[str, Any] = {"type": "edge", "length": props.Mass()}
    curve = BRepAdaptor_Curve(edge)
    ctype = curve.GetType()
    if ctype == GeomAbs_Circle:
        span = curve.LastParameter() - curve.FirstParameter()
        out.update(_circle(curve.Circle(), span >= 2 * math.pi - TURN_TOL))
        return out
    out["curve"] = GeomAbs_CurveType(ctype).name.removeprefix("GeomAbs_").lower()
    if ctype == GeomAbs_Line:
        # a straight edge: its ends and its direction from the start to the end
        # of its curve (an axis of a coordinate system can be taken from it)
        a, b = curve.Value(curve.FirstParameter()), curve.Value(curve.LastParameter())
        d = gp_Vec(a, b)
        out.update(start=_xyz(a), end=_xyz(b))
        if d.Magnitude() > 0:
            out["direction"] = _xyz(d.Normalized())
        return out
    if ctype in (GeomAbs_BSplineCurve, GeomAbs_BezierCurve):
        circ = gp_Circ()
        if ShapeAnalysis_CanonicalRecognition(edge).IsCircle(RECOGNIZE_TOL, circ):
            out.update(_circle(circ, curve.IsClosed()), recognized=True)
            return out
    if near is not None and ctype != GeomAbs_Line:
        out.update(_curve_radius_near(curve, near))
    return out


def _has_seam(face: TopoDS_Face) -> bool:
    """the face closes on itself round a turn (a whole cylinder): an edge of it is its seam"""
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        if BRep_Tool.IsClosed_s(TopoDS.Edge_s(ex.Current()), face):
            return True
        ex.Next()
    return False


def _recognize(face: TopoDS_Face) -> tuple[str, Any] | None:
    """a B-spline face that is a plane, a cylinder, a cone or a sphere within RECOGNIZE_TOL"""
    for name, geom, test in (
        ("plane", gp_Pln(), "IsPlane"),
        ("cylinder", gp_Cylinder(), "IsCylinder"),
        ("cone", gp_Cone(), "IsCone"),
        ("sphere", gp_Sphere(), "IsSphere"),
    ):
        # a recogniser of its own for each test: a failed test leaves its state behind
        if getattr(ShapeAnalysis_CanonicalRecognition(face), test)(RECOGNIZE_TOL, geom):
            return name, geom
    return None


def _surface_radius_near(face: TopoDS_Face, surf: BRepAdaptor_Surface, near: tuple[float, float, float]) -> dict[str, Any]:
    """the smallest radius of curvature of the face's surface at its point nearest to `near`"""
    proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*near), BRep_Tool.Surface_s(face))
    if proj.NbPoints() < 1:
        return {}
    u, v = proj.LowerDistanceParameters()
    props = BRepLProp_SLProps(surf, u, v, 2, 1e-9)
    if not props.IsCurvatureDefined():
        return {}
    k = max(abs(props.MaxCurvature()), abs(props.MinCurvature()))
    if k <= CURVATURE_MIN:
        return {}
    return {"localRadius": 1 / k, "at": _xyz(props.Value())}


def face_info(ref: dict, meshes: list[PartMesh], near=None) -> dict[str, Any]:
    """Face area; plus the size its kind has (module docstring): the radius of
    a cylinder (and whether it is a whole one), a torus or a sphere, a cone's
    half angle, a plane's normal; otherwise, given the clicked point, the
    radius of curvature there."""
    shape = _resolve(ref, meshes)
    face = TopoDS.Face_s(shape)

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    out: dict[str, Any] = {"type": "face", "area": props.Mass(), **_loops(face)}
    surf = BRepAdaptor_Surface(face)
    stype = surf.GetType()
    kinds = {
        GeomAbs_Cylinder: ("cylinder", surf.Cylinder),
        GeomAbs_Plane: ("plane", surf.Plane),
        GeomAbs_Torus: ("torus", surf.Torus),
        GeomAbs_Sphere: ("sphere", surf.Sphere),
        GeomAbs_Cone: ("cone", surf.Cone),
    }
    if stype in kinds:
        name, get = kinds[stype]
        geom = get()
    else:
        name, geom = GeomAbs_SurfaceType(stype).name.removeprefix("GeomAbs_").lower(), None
        found = _recognize(face) if stype in (GeomAbs_BSplineSurface, GeomAbs_BezierSurface) else None
        if found is not None:
            (name, geom), out["recognized"] = found, True
    out["surface"] = name
    if name == "cylinder":
        out.update(
            radius=geom.Radius(),
            diameter=2 * geom.Radius(),
            center=_xyz(geom.Location()),
            axis=_xyz(geom.Axis().Direction()),
            full=_has_seam(face),
        )
    elif name == "plane":
        # out of the solid: the plane's own normal, turned when the face is reversed
        n = geom.Axis().Direction()
        out["normal"] = _xyz(n.Reversed() if face.Orientation() == TopAbs_REVERSED else n)
        # a point of the plane (its own origin: it may lie outside the face), for
        # a plane to align by (版の比較's 位置合わせ)
        out["origin"] = _xyz(geom.Location())
    elif name == "torus":
        out.update(
            radius=geom.MinorRadius(),
            majorRadius=geom.MajorRadius(),
            center=_xyz(geom.Location()),
            axis=_xyz(geom.Axis().Direction()),
        )
    elif name == "sphere":
        out.update(radius=geom.Radius(), center=_xyz(geom.Location()))
    elif name == "cone":
        out.update(angle=abs(math.degrees(geom.SemiAngle())), apex=_xyz(geom.Apex()), axis=_xyz(geom.Axis().Direction()))
    elif near is not None:
        out.update(_surface_radius_near(face, surf, near))
    return out


def _loop_length(wire, face: TopoDS_Face) -> float:
    """the length of a loop of a face: its edges, but not a seam (an edge the
    face meets on both sides, where a closed surface is cut) nor a degenerate
    one (a sphere's pole)"""
    total = 0.0
    ex = TopExp_Explorer(wire, TopAbs_EDGE)
    while ex.More():
        edge = TopoDS.Edge_s(ex.Current())
        ex.Next()
        if BRep_Tool.Degenerated_s(edge) or BRep_Tool.IsClosed_s(edge, face):
            continue
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(edge, props)
        total += props.Mass()
    return total


def _loops(face: TopoDS_Face) -> dict[str, Any]:
    """the face's outer loop ("perimeter") and its inner loops ("holes"), longest first"""
    outer = BRepTools.OuterWire_s(face)
    if outer.IsNull():
        return {}
    holes = []
    ex = TopExp_Explorer(face, TopAbs_WIRE)
    while ex.More():
        wire = ex.Current()
        ex.Next()
        if not wire.IsSame(outer):
            holes.append(_loop_length(wire, face))
    return {"perimeter": _loop_length(outer, face), "holes": sorted(holes, reverse=True)}


def vertex_info(ref: dict, meshes: list[PartMesh]) -> dict[str, Any]:
    """A vertex's point, from the B-rep (the display mesh's copy is float32).

    Only a vertex of the model: a point ref ({"kind": "point", "xyz": …}) would
    resolve to a vertex made from the caller's own numbers, handed back as if
    the B-rep had said them."""
    if ref.get("kind") != "vertex":
        raise MeasureError(f"vertex_info takes a vertex of the model, not: {ref}")
    shape = _resolve(ref, meshes)
    if shape.ShapeType() != TopAbs_VERTEX:
        raise MeasureError(f"not a vertex: {ref}")
    return {"type": "vertex", "point": _xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(shape)))}


def _near(value: Any, name: str = "near") -> tuple[float, float, float] | None:
    """a clicked point as given, [x, y, z]; None when there is none"""
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(isinstance(c, (int, float)) and math.isfinite(c) for c in value)
    ):
        raise MeasureError(f"{name} must be [x, y, z]")
    return float(value[0]), float(value[1]), float(value[2])


def run(request: dict[str, Any], meshes: list[PartMesh]) -> dict[str, Any]:
    mtype = request.get("type")
    if mtype == "distance":
        mode = request.get("mode", "min")
        if mode not in ("min", "centre", "max"):
            raise MeasureError("mode must be min, centre or max")
        return distance(
            request["a"], request["b"], meshes, _near(request.get("nearA"), "nearA"), _near(request.get("nearB"), "nearB"), mode
        )
    if mtype == "edge_info":
        return edge_info(request["ref"], meshes, _near(request.get("near")))
    if mtype == "face_info":
        return face_info(request["ref"], meshes, _near(request.get("near")))
    if mtype == "vertex_info":
        return vertex_info(request["ref"], meshes)
    raise MeasureError(f"unknown measurement type: {mtype}")
