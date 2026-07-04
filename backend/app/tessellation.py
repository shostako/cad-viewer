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

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepLib import BRepLib_ToolTriangulatedShape
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESCAFControl import IGESCAFControl_Reader
from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
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
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
)
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


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


# ---------------------------------------------------------------- meshing


def combined_deflection(parts: list[Part], relative: float = 1e-3) -> float:
    box = Bnd_Box()
    for p in parts:
        BRepBndLib.Add_s(p.shape, box)
    if box.IsVoid():
        return 0.1
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    diag = math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))
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


def _edge_polyline(edge, ancestors: TopTools_IndexedDataMapOfShapeListOfShape) -> np.ndarray | None:
    """Edge polyline from the triangulation of an adjacent face."""
    if not ancestors.Contains(edge):
        return None
    faces = ancestors.FindFromKey(edge)
    it = faces.begin() if hasattr(faces, "begin") else None
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
    defl = combined_deflection(parts)
    meshes = [tessellate_part(p, defl) for p in parts]
    return meshes, tree, defl
