"""Generate test DXF drawings with known coordinates (run with backend venv).

plate_drawing.dxf: 200x100 rectangle outline + 2 holes (r=10) at (50,50), (150,50)
+ centerline. All in mm.

colours_drawing.dxf: 100x50 outline (colour 7) + a WIPEOUT 30x20 at (10,10)-(40,30)
+ a yellow line (colour 2) y=40 from x=50 to 95 + a cyan line (colour 4) x=60
from y=5 to 35 + yellow text "GATE A" (h=5) at (65,10). For the white-page PNG
export: the wipeout is filled with the page colour, yellow and cyan are light.

`python make_dxf.py` writes both; `python make_dxf.py colours_drawing` only that one.
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
    return doc


DRAWINGS = {"plate_drawing": plate_drawing, "colours_drawing": colours_drawing}


def main(names: list[str]) -> None:
    for name in names or list(DRAWINGS):
        path = OUT / f"{name}.dxf"
        DRAWINGS[name]().saveas(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
