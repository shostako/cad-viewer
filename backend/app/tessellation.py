"""STEP/IGES loading and tessellation with topology IDs.

Core principle: "the mesh is a display-time lie; measurements use the B-rep truth."
Every triangle and edge polyline sent to the frontend carries the index of its
originating TopoDS_Face / TopoDS_Edge (via TopTools_IndexedMapOfShape), so the
frontend can ask the server for exact B-rep measurements later (Phase 2).

Output per part:
    positions / normals : float32 (per-face duplicated vertices -> crisp shading)
    indices             : uint32, triangles grouped per face
    faceRanges          : [{faceId, triStart, triCount}]
    edgePositions       : float32 line-segment pairs, grouped per edge
    edgeRanges          : [{edgeId, segStart, segCount}]
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepLib import BRepLib_ToolTriangulatedShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GCPnts import GCPnts_TangentialDeflection
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESCAFControl import IGESCAFControl_Reader
from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
from OCP.ShapeFix import ShapeFix_Solid
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.gp import gp_Pnt
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_ShapeEnum,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Iterator, TopoDS_Shape
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
)
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


_log = logging.getLogger(__name__)


class BrepLoadError(Exception):
    pass


@dataclass
class Part:
    part_id: int
    name: str
    shape: TopoDS_Shape
    color: tuple[float, float, float] | None = None


@dataclass
class TreeNode:
    name: str
    part_id: int | None = None
    children: list["TreeNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.part_id is not None:
            d["partId"] = self.part_id
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class PartMesh:
    part: Part
    positions: np.ndarray  # (N, 3) float32
    normals: np.ndarray  # (N, 3) float32
    indices: np.ndarray  # (M, 3) uint32
    face_ranges: list[dict[str, int]]
    edge_positions: np.ndarray  # (K, 3) float32, consecutive pairs = segments
    edge_ranges: list[dict[str, int]]
    vertex_positions: np.ndarray = None  # (V, 3) float32, row i = vertexId i+1
    # server-side topology handles for measurement
    face_map: TopTools_IndexedMapOfShape = None
    edge_map: TopTools_IndexedMapOfShape = None
    vertex_map: TopTools_IndexedMapOfShape = None


# ---------------------------------------------------------------- loading


def _label_name(label: TDF_Label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        ext: TCollection_ExtendedString = attr.Get()
        try:
            return ext.ToExtString()
        except Exception:
            pass
        # fallback: char-by-char
        return "".join(chr(ext.Value(i)) for i in range(1, ext.Length() + 1))
    return ""


def _read_document(data: bytes, filename: str, tmpdir: str) -> TDocStd_Document:
    import os

    ext = filename.rsplit(".", 1)[-1].lower()
    path = os.path.join(tmpdir, f"input.{ext}")
    with open(path, "wb") as f:
        f.write(data)

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    if ext in ("step", "stp"):
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise BrepLoadError("STEP read failed (file corrupt or unsupported)")
        if not reader.Transfer(doc):
            raise BrepLoadError("STEP transfer failed")
    elif ext in ("iges", "igs"):
        reader = IGESCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise BrepLoadError("IGES read failed (file corrupt or unsupported)")
        if not reader.Transfer(doc):
            raise BrepLoadError("IGES transfer failed")
    else:
        raise BrepLoadError(f"not a B-rep format: .{ext}")
    return doc


def extract_parts(doc: TDocStd_Document) -> tuple[list[Part], TreeNode]:
    """Flatten the XCAF assembly into located leaf parts + a display tree."""
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    parts: list[Part] = []
    root = TreeNode(name="root")

    def label_color(label: TDF_Label) -> tuple[float, float, float] | None:
        c = Quantity_Color()
        for ctype in (
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
            XCAFDoc_ColorType.XCAFDoc_ColorGen,
        ):
            # label -> color label -> color (the only label overload OCP exposes)
            color_label = TDF_Label()
            from OCP.XCAFDoc import XCAFDoc_ColorTool

            if XCAFDoc_ColorTool.GetColor_s(label, ctype, color_label):
                if XCAFDoc_ColorTool.GetColor_s(color_label, c):
                    return (c.Red(), c.Green(), c.Blue())
        return None

    def visit(
        label: TDF_Label,
        loc: TopLoc_Location,
        node: TreeNode,
        inherited_color,
        name_override: str | None = None,
    ) -> None:
        raw_name = _label_name(label)
        # instance labels carry auto-generated names like "=>[0:1:1:2]" — ignore those
        if raw_name.startswith("=>"):
            raw_name = ""
        name = name_override or raw_name or "part"
        color = label_color(label) or inherited_color

        ref = TDF_Label()
        if XCAFDoc_ShapeTool.GetReferredShape_s(label, ref):
            # instance -> follow reference directly (no wrapper node),
            # composing this instance's location
            inst_loc = XCAFDoc_ShapeTool.GetLocation_s(label)
            visit(ref, loc.Multiplied(inst_loc), node, color, raw_name or None)
            return

        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, comps)
            sub = _child(node, name)
            for i in range(1, comps.Length() + 1):
                visit(comps.Value(i), loc, sub, color)
            return

        shape = TopoDS_Shape()
        if not XCAFDoc_ShapeTool.GetShape_s(label, shape) or shape.IsNull():
            return
        located = shape.Moved(loc)
        part = Part(part_id=len(parts), name=name, shape=located, color=color)
        parts.append(part)
        node.children.append(TreeNode(name=name, part_id=part.part_id))

    def _child(node: TreeNode, name: str) -> TreeNode:
        # named group node for assemblies/instances; leaves attach themselves
        child = TreeNode(name=name)
        node.children.append(child)
        return child

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        visit(free.Value(i), TopLoc_Location(), root, None)

    if not parts:
        raise BrepLoadError("no shapes found in file")
    return parts, root


# ---------------------------------------------------------------- loose shapes

# Sewing tolerances (model units, mm after OCCT's import conversion), tried in
# order. Exported IGES often leaves gaps of a few microns to ~0.01 mm between
# neighbouring trimmed surfaces.
SEW_TOLERANCES = (1e-4, 1e-3, 1e-2)
# never sew wider than this fraction of the sewn faces' bounding-box diagonal:
# a tolerance near the size of real features would weld them shut. The
# trade-off: exporter gaps are absolute, so a small part (diagonal < 10 mm)
# only gets the 0.0001 mm step, and a 0.002 mm gap there stays open (the part
# shows as a surface instead of a solid).
SEW_MAX_REL = 1e-4

def _contains(shape: TopoDS_Shape, kind) -> bool:
    return TopExp_Explorer(shape, kind).More()


def _is_sheet(shape: TopoDS_Shape) -> bool:
    """faces not yet part of a solid: FACE, SHELL, or a compound of those"""
    t = shape.ShapeType()
    if t in (TopAbs_ShapeEnum.TopAbs_FACE, TopAbs_ShapeEnum.TopAbs_SHELL):
        return True
    return (
        t == TopAbs_ShapeEnum.TopAbs_COMPOUND
        and _contains(shape, TopAbs_FACE)
        and not _contains(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    )


def _is_curve(shape: TopoDS_Shape) -> bool:
    t = shape.ShapeType()
    if t in (TopAbs_ShapeEnum.TopAbs_EDGE, TopAbs_ShapeEnum.TopAbs_WIRE):
        return True
    return t == TopAbs_ShapeEnum.TopAbs_COMPOUND and not _contains(shape, TopAbs_FACE) and _contains(shape, TopAbs_EDGE)


def _face_total(shapes: list[TopoDS_Shape]) -> int:
    n = 0
    for shape in shapes:
        e = TopExp_Explorer(shape, TopAbs_FACE)
        while e.More():
            n += 1
            e.Next()
    return n


def merge_loose_shapes(parts: list[Part], tree: TreeNode) -> tuple[list[Part], TreeNode]:
    """Turn a heap of loose top-level faces / curves into bodies.

    IGES (and some STEP) exports carry a solid as dozens of separate trimmed
    surfaces, which XCAF reports as one "part" per face (the tree fills with
    FACE, FACE, ...). Sew those faces into shells, close them into solids where
    possible, and gather loose curves into a single part. Parts inside
    assemblies, and files whose top level is already solids, are left alone.

    Deterministic for the same input: the lazy B-rep re-parse after a cache hit
    must reproduce the same part / face numbering as the cached mesh (sewing
    runs single-threaded and the input order follows the tree; enabling
    BRepBuilderAPI_Sewing's parallel mode would break this).

    Sewing is a convenience: if it fails, the file opens unsewn.
    """
    top_ids = [c.part_id for c in tree.children if c.part_id is not None]
    by_id = {p.part_id: p for p in parts}
    sheets = [by_id[i] for i in top_ids if _is_sheet(by_id[i].shape)]
    curves = [by_id[i] for i in top_ids if _is_curve(by_id[i].shape)]
    if _face_total([p.shape for p in sheets]) < 2:
        sheets = []  # a single loose face has nothing to be sewn to
    if len(curves) < 2:
        curves = []
    if not sheets and not curves:
        return parts, tree

    bodies: list[TopoDS_Shape] = []
    if sheets:
        try:
            bodies = _sew([p.shape for p in sheets])
        except Exception:
            _log.warning("sewing loose faces failed; opening the file unsewn", exc_info=True)
            return parts, tree
        if not bodies:
            return parts, tree

    merged_ids = {p.part_id for p in sheets + curves}
    new_parts: list[Part] = []
    new_tree = TreeNode(name=tree.name)

    def add(name: str, shape: TopoDS_Shape, color) -> None:
        part = Part(part_id=len(new_parts), name=name, shape=shape, color=color)
        new_parts.append(part)
        new_tree.children.append(TreeNode(name=name, part_id=part.part_id))

    # untouched top-level entries keep their order (ahead of the sewn bodies
    # and the curve group); assembly subtrees are renumbered in place
    def copy_node(node: TreeNode) -> TreeNode:
        if node.part_id is not None:
            old = by_id[node.part_id]
            part = Part(part_id=len(new_parts), name=old.name, shape=old.shape, color=old.color)
            new_parts.append(part)
            return TreeNode(name=node.name, part_id=part.part_id)
        return TreeNode(name=node.name, children=[copy_node(c) for c in node.children])

    for child in tree.children:
        if child.part_id is not None and child.part_id in merged_ids:
            continue
        new_tree.children.append(copy_node(child))

    if bodies:
        solids = sum(1 for b in bodies if b.ShapeType() == TopAbs_ShapeEnum.TopAbs_SOLID)
        color = _common_color(sheets)
        for i, body in enumerate(bodies, 1):
            kind = "ソリッド" if body.ShapeType() == TopAbs_ShapeEnum.TopAbs_SOLID else "サーフェス"
            same_kind = solids if kind == "ソリッド" else len(bodies) - solids
            add(f"{kind} {i}" if same_kind > 1 else kind, body, color)
    if curves:
        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for p in curves:
            builder.Add(compound, p.shape)
        add(f"曲線（{len(curves)} 本）", compound, _common_color(curves))
    return new_parts, new_tree


def _common_color(parts: list[Part]):
    # faces of differing colors sew into one body that has one color: fall back
    # to the default color rather than pick one arbitrarily
    colors = {p.color for p in parts}
    return colors.pop() if len(colors) == 1 else None


def _sew(shapes: list[TopoDS_Shape]) -> list[TopoDS_Shape]:
    """Sew faces into bodies: closed shells become solids, the rest stay shells.

    Each shell settles at the smallest tolerance that closes it; only what is
    still open goes on to the next, wider step. Otherwise one open face (or a
    real gap) anywhere would drag every body up to the widest tolerance and
    weld neighbouring sheets onto shells that had already closed cleanly.
    A settled shell is never sewn again, so faces that only reach it at a
    wider step end up as a separate surface rather than reopening it.
    Raises if sewing yields nothing (the caller then opens the file unsewn).
    """
    # cap from the faces being sewn only: a long construction line or an
    # unrelated big solid elsewhere in the file must not widen the tolerance
    # enough to weld real gaps in a small body. The slack keeps a diagonal that
    # lands exactly on a step (10 mm -> 0.001) from losing it to rounding.
    cap = max(_shape_diagonal(shapes) * SEW_MAX_REL, SEW_TOLERANCES[0]) * (1 + 1e-9)
    tolerances = [t for t in SEW_TOLERANCES if t <= cap]
    settled: list[TopoDS_Shape] = []
    pending = list(shapes)
    for tol in tolerances:
        sewing = BRepBuilderAPI_Sewing(tol)
        for shape in pending:
            sewing.Add(shape)
        sewing.Perform()
        bodies = _top_level(sewing.SewedShape())
        if not bodies:
            raise ValueError(f"sewing at {tol} returned no shape")
        settled += [b for b in bodies if _is_closed_shell(b)]
        pending = [b for b in bodies if not _is_closed_shell(b)]
        if not pending:
            break
    return [_close(b) for b in settled + pending]


def _is_closed_shell(shape: TopoDS_Shape) -> bool:
    return shape.ShapeType() == TopAbs_ShapeEnum.TopAbs_SHELL and BRep_Tool.IsClosed_s(shape)


def _top_level(shape: TopoDS_Shape | None) -> list[TopoDS_Shape]:
    """the shells / faces inside a sewing result, through nested compounds"""
    if shape is None or shape.IsNull():
        return []
    if shape.ShapeType() != TopAbs_ShapeEnum.TopAbs_COMPOUND:
        return [shape]
    out: list[TopoDS_Shape] = []
    it = TopoDS_Iterator(shape)
    while it.More():
        out += _top_level(it.Value())
        it.Next()
    return out


def _close(body: TopoDS_Shape) -> TopoDS_Shape:
    """a closed shell as an outward-facing solid; anything else unchanged"""
    if not _is_closed_shell(body):
        return body
    try:
        solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(body)).Solid()
        fix = ShapeFix_Solid()  # orients the shell outward (a sewn shell may face in)
        fix.Init(solid)
        fix.Perform()
        result = fix.Solid()
        volume = _volume(result)
        if abs(volume) < 1e-12:
            _log.info("closed shell has no volume; keeping it as a surface")
            return body  # degenerate: not worth calling a solid
        if volume < 0:  # still inside-out: flip so volume / normals come out right
            result = result.Reversed()
        return result
    except Exception:
        _log.warning("closed shell could not be made a solid; keeping it as a surface", exc_info=True)
        return body


def _volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _diagonal(parts: list[Part]) -> float:
    return _shape_diagonal([p.shape for p in parts])


def _shape_diagonal(shapes: list[TopoDS_Shape]) -> float:
    box = Bnd_Box()
    for shape in shapes:
        BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return 0.0
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))


# ---------------------------------------------------------------- meshing


def combined_deflection(parts: list[Part], relative: float = 1e-3) -> float:
    diag = _diagonal(parts)
    if diag == 0.0:
        return 0.1
    return max(diag * relative, 1e-6)


def tessellate_part(part: Part, lin_deflection: float, ang_deflection: float = 0.35) -> PartMesh:
    shape = part.shape
    BRepMesh_IncrementalMesh(shape, lin_deflection, False, ang_deflection, True)

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)

    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    tri_indices: list[np.ndarray] = []
    face_ranges: list[dict[str, int]] = []
    vert_offset = 0
    tri_offset = 0

    for fi in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(fi))
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue

        trsf = loc.Transformation()
        n_nodes = tri.NbNodes()
        pts = np.empty((n_nodes, 3), dtype=np.float32)
        for i in range(1, n_nodes + 1):
            p = tri.Node(i).Transformed(trsf)
            pts[i - 1] = (p.X(), p.Y(), p.Z())

        # per-node normals (OCCT computes & caches them on the triangulation)
        BRepLib_ToolTriangulatedShape.ComputeNormals_s(face, tri)
        nrm = np.empty((n_nodes, 3), dtype=np.float32)
        for i in range(1, n_nodes + 1):
            d = tri.Normal(i)
            nrm[i - 1] = (d.X(), d.Y(), d.Z())
        # rotate normals by the location's rotational part
        rot = np.array(
            [[trsf.Value(r, c) for c in range(1, 4)] for r in range(1, 4)],
            dtype=np.float32,
        )
        nrm = nrm @ rot.T

        reversed_ = face.Orientation() == TopAbs_REVERSED
        if reversed_:
            nrm = -nrm

        n_tris = tri.NbTriangles()
        tris = np.empty((n_tris, 3), dtype=np.uint32)
        for i in range(1, n_tris + 1):
            a, b, c = tri.Triangle(i).Get()
            tris[i - 1] = (a - 1, c - 1, b - 1) if reversed_ else (a - 1, b - 1, c - 1)

        positions.append(pts)
        normals.append(nrm)
        tri_indices.append(tris + vert_offset)
        face_ranges.append({"faceId": fi, "triStart": tri_offset, "triCount": n_tris})
        vert_offset += n_nodes
        tri_offset += n_tris

    # ---- edges: polyline on triangulation, fallback to nothing (rare)
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    ancestors = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)

    seg_chunks: list[np.ndarray] = []
    edge_ranges: list[dict[str, int]] = []
    seg_offset = 0

    for ei in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(ei))
        pl = _edge_polyline(edge, ancestors)
        if pl is None and _face_count(edge, ancestors) == 0:
            # a free curve (no face to borrow a polyline from): sample it directly
            pl = _curve_polyline(edge, lin_deflection, ang_deflection)
        if pl is None or len(pl) < 2:
            continue
        # polyline (n pts) -> line segment pairs (2*(n-1) pts)
        segs = np.empty((2 * (len(pl) - 1), 3), dtype=np.float32)
        segs[0::2] = pl[:-1]
        segs[1::2] = pl[1:]
        n_segs = len(pl) - 1
        seg_chunks.append(segs)
        edge_ranges.append({"edgeId": ei, "segStart": seg_offset, "segCount": n_segs})
        seg_offset += n_segs

    # ---- vertices: exact B-rep vertex coordinates (snap targets)
    vertex_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vertex_map)
    verts = np.empty((vertex_map.Extent(), 3), dtype=np.float32)
    for vi in range(1, vertex_map.Extent() + 1):
        p: gp_Pnt = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex_map.FindKey(vi)))
        verts[vi - 1] = (p.X(), p.Y(), p.Z())

    empty3 = np.empty((0, 3), dtype=np.float32)
    return PartMesh(
        part=part,
        positions=np.vstack(positions) if positions else empty3,
        normals=np.vstack(normals) if normals else empty3,
        indices=np.vstack(tri_indices) if tri_indices else np.empty((0, 3), dtype=np.uint32),
        face_ranges=face_ranges,
        edge_positions=np.vstack(seg_chunks) if seg_chunks else empty3,
        edge_ranges=edge_ranges,
        vertex_positions=verts,
        face_map=face_map,
        edge_map=edge_map,
        vertex_map=vertex_map,
    )


def _face_count(edge, ancestors: TopTools_IndexedDataMapOfShapeListOfShape) -> int:
    # MapShapesAndAncestors also lists edges that bound no face, with an empty list
    return ancestors.FindFromKey(edge).Size() if ancestors.Contains(edge) else 0


def _curve_polyline(edge, lin_deflection: float, ang_deflection: float) -> np.ndarray | None:
    """Polyline for an edge that bounds no face (a loose curve in the file)."""
    if BRep_Tool.Degenerated_s(edge):
        return None
    try:
        curve = BRepAdaptor_Curve(edge)  # applies the edge's location
        disc = GCPnts_TangentialDeflection(curve, ang_deflection, lin_deflection)
    except Exception:
        return None
    n = disc.NbPoints()
    if n < 2:
        return None
    out = np.empty((n, 3), dtype=np.float32)
    for i in range(1, n + 1):
        p = disc.Value(i)
        out[i - 1] = (p.X(), p.Y(), p.Z())
    return out


def _edge_polyline(edge, ancestors: TopTools_IndexedDataMapOfShapeListOfShape) -> np.ndarray | None:
    """Edge polyline from the triangulation of an adjacent face."""
    if not ancestors.Contains(edge):
        return None
    faces = ancestors.FindFromKey(edge)
    face_shape = faces.First() if faces.Size() > 0 else None
    if face_shape is None:
        return None
    face = TopoDS.Face_s(face_shape)
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is None:
        return None
    poly = BRep_Tool.PolygonOnTriangulation_s(edge, tri, loc)
    if poly is None:
        return None
    trsf = loc.Transformation()
    nodes = poly.Nodes()
    out = np.empty((nodes.Length(), 3), dtype=np.float32)
    for i in range(1, nodes.Length() + 1):
        p = tri.Node(nodes.Value(i)).Transformed(trsf)
        out[i - 1] = (p.X(), p.Y(), p.Z())
    return out


# ---------------------------------------------------------------- top level


def load_brep(data: bytes, filename: str) -> tuple[list[PartMesh], TreeNode, float]:
    """Full pipeline: bytes -> located parts -> tessellated meshes + tree."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        doc = _read_document(data, filename, tmpdir)
    parts, tree = extract_parts(doc)
    parts, tree = merge_loose_shapes(parts, tree)
    defl = combined_deflection(parts)
    meshes = [tessellate_part(p, defl) for p in parts]
    return meshes, tree, defl
