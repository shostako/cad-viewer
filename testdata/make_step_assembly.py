"""Generate colored STEP test data (run with backend venv).

Creates mini_mold.step: a plate (gray) + 2 core pins (red) + cavity block (blue),
assembled with locations — exercises XCAF colors, assembly tree, curved faces.

Creates curved_part.step: the curved faces whose radius (R) is measured, each
of a known size (see make_curved_part).

Creates inch_block.step: a block of 1 x 2 x 0.5 in (25.4 x 50.8 x 12.7 mm)
written in inches (the 計測の単位's file unit; see make_inch_block).

Creates named_parts.step: an instance's own name and colour (see make_named_parts).

Usage: backend/.venv/bin/python testdata/make_step_assembly.py
"""
import math
from pathlib import Path

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.GeomAbs import GeomAbs_Circle
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

OUT = Path(__file__).parent


def named(shape_tool, label, name):
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    return label


def loc(x, y, z):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(x, y, z))
    return TopLoc_Location(t)


def write(doc, name: str) -> None:
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.Transfer(doc, STEPControl_AsIs)
    path = str(OUT / name)
    assert writer.Write(path) == IFSelect_RetDone
    print(f"wrote {path}")


def main() -> None:
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    plate = BRepPrimAPI_MakeBox(100, 60, 15).Shape()
    pin = BRepPrimAPI_MakeCylinder(4, 25).Shape()
    cavity = BRepPrimAPI_MakeBox(40, 30, 20).Shape()

    l_plate = named(st, st.AddShape(plate, False), "plate")
    l_pin = named(st, st.AddShape(pin, False), "core_pin")
    l_cavity = named(st, st.AddShape(cavity, False), "cavity_block")

    gray = Quantity_Color(0.6, 0.6, 0.62, Quantity_TOC_RGB)
    red = Quantity_Color(0.8, 0.15, 0.1, Quantity_TOC_RGB)
    blue = Quantity_Color(0.15, 0.3, 0.75, Quantity_TOC_RGB)
    ct.SetColor(l_plate, gray, XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    ct.SetColor(l_pin, red, XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    ct.SetColor(l_cavity, blue, XCAFDoc_ColorType.XCAFDoc_ColorSurf)

    asm = st.NewShape()
    named(st, asm, "mini_mold")
    st.AddComponent(asm, l_plate, loc(0, 0, 0))
    st.AddComponent(asm, l_pin, loc(25, 30, 15))
    st.AddComponent(asm, l_pin, loc(75, 30, 15))
    st.AddComponent(asm, l_cavity, loc(30, 15, 15))
    st.UpdateAssemblies()
    write(doc, "mini_mold.step")

    make_curved_part()
    make_inch_block()
    make_named_parts()


def make_named_parts() -> None:
    """named_parts.step: an assembly "frame" of two instances of one uncoloured
    box (10 mm): "left" at the origin, with the instance's own name and colour
    (green: the box it refers to takes it), and an unnamed one at x 20 (the
    box's name, "brick", and no colour). Two pins, one along z ("pin_z") and one
    along x ("pin_x"): their axes cross."""
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    brick = named(st, st.AddShape(BRepPrimAPI_MakeBox(10, 10, 10).Shape(), False), "brick")
    frame = named(st, st.NewShape(), "frame")
    left = named(st, st.AddComponent(frame, brick, loc(0, 0, 0)), "left")
    st.AddComponent(frame, brick, loc(20, 0, 0))
    # two pins, one along z and one along x: their axes cross (no centre distance)
    pin_z = named(st, st.AddShape(BRepPrimAPI_MakeCylinder(1.5, 8).Shape(), False), "pin_z")
    pin_x = named(st, st.AddShape(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), 2, 10).Shape(), False), "pin_x")
    st.AddComponent(frame, pin_z, loc(50, 10, 0))
    st.AddComponent(frame, pin_x, loc(40, 0, 5))
    st.UpdateAssemblies()
    green = Quantity_Color(0.2, 0.7, 0.3, Quantity_TOC_RGB)
    ct.SetColor(left, green, XCAFDoc_ColorType.XCAFDoc_ColorGen)
    write(doc, "named_parts.step")


# curved_part.step: the sizes the tests check
BODY = (60, 40, 10)  # the block, from the origin; its 4 vertical edges rounded
CORNER_R = 5.0  # the rounded corners: a quarter of a cylinder each, edged by quarter circles
HOLE = (12, 20, 3.0)  # a through hole ⌀6 at (12, 20): a whole cylinder, edged by whole circles
BOSS = (38, 20, 6.0, 8.0, 2.0)  # a boss at (38, 20) on the top: radius 6 at its foot, 8 high, 2° draft (a cone)
BOSS_FILLET_R = 1.0  # the boss's foot rounded: a torus of that small radius
DIMPLE = (52, 30, 12, 4.0)  # a dimple: a sphere of radius 4 centred 2 above the top
# nurbs_pin: a cylinder of radius 3, 10 high at (75, 20), its top edge rounded,
# all turned into B-splines. Its side and top are a cylinder and a plane again
# within the recognition's tolerance; its rounding was a torus, which nothing
# recognises: the curvature at a click on it tells the radius
PIN = (75, 20, 3.0, 10.0)
PIN_FILLET_R = 1.0


def edges(shape):
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        yield TopoDS.Edge_s(ex.Current())
        ex.Next()


def make_curved_part() -> None:
    """A part with each kind of curved face the radius measurement tells apart."""
    w, d, h = BODY
    box = BRepPrimAPI_MakeBox(w, d, h).Shape()
    mk = BRepFilletAPI_MakeFillet(box)
    for e in edges(box):
        c = BRepAdaptor_Curve(e)
        p0, p1 = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        if abs(p0.X() - p1.X()) < 1e-9 and abs(p0.Y() - p1.Y()) < 1e-9:  # a vertical edge
            mk.Add(CORNER_R, e)
    body = mk.Shape()

    bx, by, r0, bh, draft = BOSS
    r1 = r0 - bh * math.tan(math.radians(draft))
    cone = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(bx, by, h), gp_Dir(0, 0, 1)), r0, r1, bh).Shape()
    body = BRepAlgoAPI_Fuse(body, cone).Shape()
    mk = BRepFilletAPI_MakeFillet(body)
    for e in edges(body):
        c = BRepAdaptor_Curve(e)
        if c.GetType() == GeomAbs_Circle:
            circle = c.Circle()
            if abs(circle.Radius() - r0) < 1e-6 and abs(circle.Location().Z() - h) < 1e-6:
                mk.Add(BOSS_FILLET_R, e)
    body = mk.Shape()

    hx, hy, hr = HOLE
    drill = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(hx, hy, -1), gp_Dir(0, 0, 1)), hr, h + 2).Shape()
    body = BRepAlgoAPI_Cut(body, drill).Shape()
    sx, sy, sz, sr = DIMPLE
    body = BRepAlgoAPI_Cut(body, BRepPrimAPI_MakeSphere(gp_Pnt(sx, sy, sz), sr).Shape()).Shape()

    px, py, pr, ph = PIN
    pin = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(px, py, 0), gp_Dir(0, 0, 1)), pr, ph).Shape()
    mk = BRepFilletAPI_MakeFillet(pin)
    for e in edges(pin):
        c = BRepAdaptor_Curve(e)
        if c.GetType() == GeomAbs_Circle and abs(c.Circle().Location().Z() - ph) < 1e-6:
            mk.Add(PIN_FILLET_R, e)
    pin = BRepBuilderAPI_NurbsConvert(mk.Shape(), True).Shape()

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    l_body = named(st, st.AddShape(body, False), "body")
    l_pin = named(st, st.AddShape(pin, False), "nurbs_pin")
    ct.SetColor(l_body, Quantity_Color(0.6, 0.6, 0.62, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    ct.SetColor(l_pin, Quantity_Color(0.8, 0.15, 0.1, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    asm = st.NewShape()
    named(st, asm, "curved_part")
    st.AddComponent(asm, l_body, loc(0, 0, 0))
    st.AddComponent(asm, l_pin, loc(0, 0, 0))
    st.UpdateAssemblies()
    write(doc, "curved_part.step")


def make_inch_block() -> None:
    """A block of 25.4 x 50.8 x 12.7 mm from the origin, written in inches:
    the file says 1 x 2 x 0.5 (its unit INCH); OCCT reads it back into mm."""
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_Writer

    writer = STEPControl_Writer()  # first: it sets the write.step.* defaults
    old = Interface_Static.CVal_s("write.step.unit")
    Interface_Static.SetCVal_s("write.step.unit", "INCH")
    try:
        writer.Transfer(BRepPrimAPI_MakeBox(25.4, 50.8, 12.7).Shape(), STEPControl_AsIs)
        assert writer.Write(str(OUT / "inch_block.step")) == IFSelect_RetDone
    finally:
        Interface_Static.SetCVal_s("write.step.unit", old)


if __name__ == "__main__":
    main()
