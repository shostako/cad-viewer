"""Generate test DXF drawings with known coordinates (run with backend venv).

plate_drawing.dxf: 200x100 rectangle outline + 2 holes (r=10) at (50,50), (150,50)
+ centerline. All in mm.

colours_drawing.dxf: 100x50 outline (colour 7) + a WIPEOUT 30x20 at (10,10)-(40,30)
+ a yellow line (colour 2) y=40 from x=50 to 95 + a cyan line (colour 4) x=60
from y=5 to 35 + yellow text "GATE A" (h=5) at (65,10) + a line in the true
colour #1d2126 (the 3D view's background) y=45 from x=5 to 45. For the
white-page PNG export: the wipeout is filled with the page colour, yellow and
cyan are light, and the #1d2126 line must stay dark (the 2D view swaps the
page colour for that very colour on screen).

japanese_drawing.dxf (issue #90): Japanese written the ways Japanese CAD writes
it, each in a font a PC may lack (they draw with the drawing's Japanese font,
backend/app/drawing.py): a style on MS Gothic "寸法 R5" at (0,0); a style on
SHX fonts with a big font "注記" at (0,10); an MTEXT with a font change
\\fＭＳ ゴシック "材質 PMMA" at (0,20); an MTEXT with a font file \\F "ゲート" at
(0,30); a dimension 0..50 at y=-10 "全長 <>". And "GATE B" at (60,0) in a style
on a missing font with Latin only (it keeps its font). Inside a 100x45 outline.

`python make_dxf.py` writes them all; `python make_dxf.py colours_drawing` only that one.
"""
import sys
from pathlib import Path

import ezdxf

OUT = Path(__file__).parent


def plate_drawing() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # outline 200x100
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True)
    # holes
    msp.add_circle((50, 50), radius=10)
    msp.add_circle((150, 50), radius=10)
    # centerline
    msp.add_line((0, 50), (200, 50), dxfattribs={"linetype": "CENTER"})
    return doc


def colours_drawing() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    msp.add_wipeout([(10, 10), (40, 10), (40, 30), (10, 30)])
    msp.add_line((50, 40), (95, 40), dxfattribs={"color": 2})
    msp.add_line((60, 5), (60, 35), dxfattribs={"color": 4})
    msp.add_text("GATE A", height=5, dxfattribs={"color": 2}).set_placement((65, 10))
    msp.add_line((5, 45), (45, 45), dxfattribs={"true_color": ezdxf.rgb2int((0x1D, 0x21, 0x26))})
    return doc


def japanese_drawing() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010", setup=["dimstyles"])
    doc.styles.new("MSG", dxfattribs={"font": "msgothic.ttc"})
    doc.styles.new("SHX", dxfattribs={"font": "txt.shx", "bigfont": "extfont2.shx"})
    doc.styles.new("LATIN", dxfattribs={"font": "romans.shx"})
    msp = doc.modelspace()
    msp.add_lwpolyline([(-5, -15), (95, -15), (95, 40), (-5, 40)], close=True)
    msp.add_text("寸法 R5", height=5, dxfattribs={"style": "MSG"}).set_placement((0, 0))
    msp.add_text("注記", height=5, dxfattribs={"style": "SHX"}).set_placement((0, 10))
    msp.add_mtext("\\fＭＳ ゴシック|b0|i0|c128|p49;材質 PMMA", dxfattribs={"char_height": 5, "insert": (0, 25)})
    msp.add_mtext("\\Ftxt.shx,extfont2.shx;ゲート", dxfattribs={"char_height": 5, "insert": (0, 35)})
    msp.add_text("GATE B", height=5, dxfattribs={"style": "LATIN"}).set_placement((60, 0))
    msp.add_linear_dim(base=(0, -10), p1=(0, -5), p2=(50, -5), text="全長 <>").render()
    return doc


DRAWINGS = {"plate_drawing": plate_drawing, "colours_drawing": colours_drawing, "japanese_drawing": japanese_drawing}


def main(names: list[str]) -> None:
    for name in names or list(DRAWINGS):
        path = OUT / f"{name}.dxf"
        DRAWINGS[name]().saveas(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
