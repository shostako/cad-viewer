"""Generate loose_faces_box.igs: an IGES the way CAD exports often look.

A 10 x 20 x 30 box written as six separate trimmed surfaces (no solid entity),
plus three 100 mm coordinate-axis lines. Readers report one part per face and
one per line; the viewer must sew the faces into one solid, draw the lines,
and frame the box rather than the much longer lines.

Usage: backend/.venv/bin/python testdata/make_iges_loose.py
"""
from pathlib import Path

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from OCP.IGESControl import IGESControl_Writer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

OUT = Path(__file__).parent / "loose_faces_box.igs"

box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
writer = IGESControl_Writer("MM", 0)  # 0 = trimmed surfaces, not a B-rep solid
faces = TopExp_Explorer(box, TopAbs_FACE)
while faces.More():
    writer.AddShape(faces.Current())
    faces.Next()
for a, b in (((-50, 0, 0), (50, 0, 0)), ((0, -50, 0), (0, 50, 0)), ((0, 0, -50), (0, 0, 50))):
    writer.AddShape(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
writer.ComputeModel()
if not writer.Write(str(OUT)):
    raise SystemExit("IGES write failed")
print(f"wrote {OUT}")
