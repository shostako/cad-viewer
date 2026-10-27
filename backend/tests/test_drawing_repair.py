"""DXF files a Japanese CAD wrote that did not open, or opened garbled
(app/drawing.py: _declare_codepage, _repair_splines).

- Shift_JIS without $DWGCODEPAGE: drawn as the same file naming ANSI_932 is
  (ezdxf's own reading of a declared file is the oracle). A Western file
  without one is left as it is.
- A SPLINE ezdxf cannot make a curve of: the drawing opens, drawn as the same
  drawing written clean is (the repeated fit point not written, the curveless
  spline not written), or, for knots that make no curve, straight lines through
  its control points (their box is the drawing's).
- Anything else failing in drawing: 422 with the reason, not a 500.
"""
from __future__ import annotations

import io

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app import drawing
from app.main import app

TEXTS = ("樹脂キャップ", "２．８個取り")


def dxf_text(doc) -> str:
    s = io.StringIO()
    doc.write(s)
    return s.getvalue()


def sjis(codepage: str | None, version: str = "R2000", newline: str = "\r\n") -> bytes:
    """a drawing with Japanese texts in Shift_JIS, naming codepage (None: naming none)"""
    doc = ezdxf.new(version)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    for i, t in enumerate(TEXTS):
        msp.add_text(t, height=5).set_placement((5, 35 - 10 * i))
    text = dxf_text(doc)
    named = "  9\n$DWGCODEPAGE\n  3\nANSI_1252\n"
    assert text.count(named) == 1
    text = text.replace(named, "" if codepage is None else f"  9\n$DWGCODEPAGE\n  3\n{codepage}\n")
    return text.replace("\n", newline).encode("cp932")


def svg_of(data: bytes) -> str:
    svg, _meta = drawing.load_drawing(data, "t.dxf")
    return svg


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_shift_jis_without_codepage_read_as_ansi_932(newline):
    data = sjis(None, newline=newline)
    assert drawing._declare_codepage(data) != data
    want = svg_of(sjis("ANSI_932", newline=newline))
    assert svg_of(data) == want
    # the oracle tells the two readings apart: read as ANSI_1252 (as before), it is not that
    assert svg_of(sjis("ANSI_1252", newline=newline)) != want


@pytest.mark.parametrize(
    "data",
    [
        # Western text in ANSI_1252 that Shift_JIS also decodes (half-width katakana)
        b"  0\nSECTION\n  2\nHEADER\n  9\n$ACADVER\n  1\nAC1015\n  0\nENDSEC\n  0\nSECTION\n  2\nENTITIES\n"
        + "  0\nTEXT\n  1\nØ25 ±0.1 30°\n".encode("cp1252")
        + b"  0\nENDSEC\n  0\nEOF\n",
        # Western text Shift_JIS does not decode
        b"  9\n$ACADVER\n  1\nAC1015\n" + "  1\nCafé éclair\n".encode("cp1252"),
        # naming a code page
        b"  9\n$ACADVER\n  1\nAC1015\n  9\n$DWGCODEPAGE\n  3\nANSI_1252\n" + "  1\n樹脂\n".encode("cp932"),
        # R2007 and after: UTF-8 whatever it names
        b"  9\n$ACADVER\n  1\nAC1024\n" + "  1\n樹脂キャップ\n".encode("cp932"),
        # no $ACADVER
        "  0\nSECTION\n  2\nENTITIES\n  0\nTEXT\n  1\n樹脂キャップ\n".encode("cp932"),
    ],
    ids=["western-decodable", "western", "named", "r2007", "no-acadver"],
)
def test_codepage_left_as_it_is(data):
    assert drawing._declare_codepage(data) is data


def outline_doc():
    doc = ezdxf.new("R2000")
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    return doc


def upload(data: bytes):
    return TestClient(app).post("/api/models", files={"file": ("t.dxf", data, "x")})


def test_spline_with_a_repeated_fit_point():
    points = [(60, 10), (70, 20), (80, 15), (90, 25)]
    bad, clean = outline_doc(), outline_doc()
    bad.modelspace().add_spline(fit_points=[points[0], *points[:2], points[2], points[3], points[3]])
    clean.modelspace().add_spline(fit_points=points)
    r = upload(dxf_text(bad).encode())
    assert r.status_code == 200, r.text
    assert svg_of(dxf_text(bad).encode()) == svg_of(dxf_text(clean).encode())


def test_spline_without_a_curve_left_out():
    bad, clean = outline_doc(), outline_doc()
    bad.modelspace().add_spline(fit_points=[(50, 5), (50, 5), (50, 5)])
    assert svg_of(dxf_text(bad).encode()) == svg_of(dxf_text(clean).encode())


def test_spline_with_knots_that_make_no_curve_drawn_straight():
    doc = outline_doc()
    s = doc.modelspace().add_spline()
    s.dxf.degree = 3
    s.control_points = [(10, 5), (40, 80), (70, -20), (130, 15)]
    s.knots = [0] * 8
    r = upload(dxf_text(doc).encode())
    assert r.status_code == 200, r.text
    # straight lines through the control points: their box, out of the outline's
    assert r.json()["bbox2d"] == {"min": [0.0, -20.0], "max": [130.0, 80.0]}


def test_polyline_in_place_of_the_spline_keeps_its_layer_colour_and_line():
    doc = outline_doc()
    doc.layers.add("108")
    attribs = {"layer": "108", "color": 1, "linetype": "DASHED", "lineweight": 35}
    s = doc.modelspace().add_spline(dxfattribs=attribs)
    s.dxf.degree = 3
    s.control_points = [(10, 5), (40, 80), (70, -20), (130, 15)]
    s.knots = [0] * 8
    drawing._repair_splines(doc)
    _outline, poly = doc.modelspace()
    assert poly.dxftype() == "POLYLINE"
    assert {k: poly.dxf.get(k) for k in attribs} == attribs
    assert [tuple(v.dxf.location) for v in poly.vertices] == [(10, 5, 0), (40, 80, 0), (70, -20, 0), (130, 15, 0)]


def test_drawing_failure_said_in_words(monkeypatch):
    def broken(doc):
        raise ZeroDivisionError("float division")

    monkeypatch.setattr(drawing, "_fit_fonts", broken)
    r = upload(dxf_text(outline_doc()).encode())
    assert r.status_code == 422
    assert r.json()["detail"] == "図面の描画に失敗: ZeroDivisionError: float division"
