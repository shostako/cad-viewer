"""Japanese text in a 2D drawing (issue #90; app/drawing.py's _fit_fonts).

A text in a font the PC lacks (or one without Japanese) is drawn with the
drawing's Japanese font: the SVG is the one of the same drawing written with
that font named outright (the oracle: ezdxf drawing a font it has, no fitting
needed). A style with Latin text only keeps its font; a drawing without
Japanese is drawn as before, to the byte.

The Japanese font: frontend/web-public/py/NotoSansJP-Regular.otf (put there by
npm run build:web, the Web version's) through CAD_VIEWER_FONT_DIRS, else one
of the PC's (drawing.CJK_FONTS); none: skipped.
"""
from __future__ import annotations

import io
import pathlib

import ezdxf
import pytest
from ezdxf.fonts import fonts

from app import drawing

WEB_FONTS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "web-public" / "py"


@pytest.fixture(scope="module", autouse=True)
def japanese_font():
    """the drawing's Japanese font (its file name), the Web version's added when it is there"""
    if (WEB_FONTS / "NotoSansJP-Regular.otf").is_file():
        mp = pytest.MonkeyPatch()
        mp.setenv("CAD_VIEWER_FONT_DIRS", str(WEB_FONTS))
        drawing._extra_fonts_added = False
        drawing._add_extra_fonts()
        mp.undo()
        # the fonts CAD_VIEWER_FONT_DIRS adds are looked at (a PC's own Noto CJK draws these alike)
        assert fonts.font_manager.has_font("NotoSansJP-Regular.otf")
    found = next((f for f in drawing.CJK_FONTS if fonts.font_manager.has_font(f)), None)
    if found is None:
        pytest.skip("no Japanese font (npm run build:web puts the Web version's in frontend/web-public/py)")
    return found


def svg_of(doc) -> str:
    s = io.StringIO()
    doc.write(s)
    svg, _meta = drawing.load_drawing(s.getvalue().encode(), "t.dxf")
    return svg


def new_doc():
    doc = ezdxf.new("R2010", setup=["dimstyles"])
    doc.modelspace().add_line((0, -20), (100, -20))  # the same extents in every drawing
    doc.modelspace().add_line((0, 40), (100, 40))
    return doc


def styled(font: str, add, bigfont: str = ""):
    doc = new_doc()
    doc.styles.new("S", dxfattribs={"font": font, "bigfont": bigfont})
    add(doc.modelspace(), "S")
    return doc


TEXT = lambda msp, style: msp.add_text("寸法 R5", height=5, dxfattribs={"style": style}).set_placement((0, 0))  # noqa: E731


@pytest.mark.parametrize(
    "font, bigfont",
    [("msgothic.ttc", ""), ("txt.shx", "extfont2.shx"), ("NoSuchFont.ttf", ""), ("DejaVuSans.ttf", "")],
    ids=["MS Gothic (not here)", "SHX and a big font", "a font not here", "a font here without Japanese"],
)
def test_a_text_style_without_japanese(japanese_font, font, bigfont):
    got = svg_of(styled(font, TEXT, bigfont))
    want = svg_of(styled(japanese_font, TEXT))
    assert got == want


@pytest.mark.parametrize(
    "code",
    ["\\fＭＳ ゴシック|b0|i0|c128|p49;", "\\fMS Gothic|b0|i0;", "\\fNoSuchFont|b0|i0;", "\\Ftxt.shx,extfont2.shx;", "\\Fmsgothic.ttc|c128;"],
    ids=["MS Gothic by its Japanese name", "MS Gothic", "a family not here", "SHX font files", "a font file"],
)
def test_an_mtext_font_change_without_japanese(japanese_font, code):
    family = fonts.font_manager.get_font_face(japanese_font).family

    def mtext(content):
        doc = new_doc()
        doc.modelspace().add_mtext(content, dxfattribs={"char_height": 5, "insert": (0, 30)})
        return doc

    assert svg_of(mtext(f"{code}材質 PMMA")) == svg_of(mtext(f"\\f{family};材質 PMMA"))


def test_a_dimension_text(japanese_font):
    """a dimension's text: the MTEXT in its block, in its dimension style's text style (not the drawing's Standard)"""

    def dim(font):
        doc = new_doc()
        doc.styles.new("DIMTEXT", dxfattribs={"font": font})
        doc.dimstyles.duplicate_entry("EZDXF", "JPDIM").dxf.dimtxsty = "DIMTEXT"
        doc.modelspace().add_linear_dim(base=(0, -10), p1=(0, -5), p2=(50, -5), text="全長 <>", dimstyle="JPDIM").render()
        return doc

    assert svg_of(dim("txt.shx")) == svg_of(dim(japanese_font))


def test_only_the_styles_that_draw_japanese_change(japanese_font):
    doc = new_doc()
    doc.styles.new("JP", dxfattribs={"font": "msgothic.ttc"})
    doc.styles.new("LATIN", dxfattribs={"font": "romans.shx"})
    doc.modelspace().add_text("注記", height=5, dxfattribs={"style": "JP"})
    doc.modelspace().add_text("GATE B", height=5, dxfattribs={"style": "LATIN"})
    # a backslash written as \\: text, not a font change
    m = doc.modelspace().add_mtext("\\\\fMS Gothic;注記", dxfattribs={"char_height": 5})
    drawing._fit_fonts(doc)
    assert doc.styles.get("JP").dxf.font == japanese_font
    assert doc.styles.get("LATIN").dxf.font == "romans.shx", "Latin text only: its font kept"
    assert m.text == "\\\\fMS Gothic;注記"


def test_a_drawing_without_japanese_as_before(monkeypatch):
    doc = styled("msgothic.ttc", lambda msp, style: msp.add_text("GATE A", height=5, dxfattribs={"style": style}))
    doc.modelspace().add_mtext("\\fMS Gothic|b0|i0;R5", dxfattribs={"char_height": 5, "insert": (0, 30)})
    got = svg_of(doc)
    monkeypatch.setattr(drawing, "_fit_fonts", lambda _doc: None)
    assert got == svg_of(doc)


def test_the_testdata_drawing(japanese_font):
    """testdata/japanese_drawing.dxf (make_dxf.py): its Japanese all drawn, none as boxes"""
    path = pathlib.Path(__file__).resolve().parents[2] / "testdata" / "japanese_drawing.dxf"
    if not path.is_file():
        pytest.skip("testdata/make_dxf.py not run")
    doc = ezdxf.readfile(path)
    drawing._fit_fonts(doc)
    family = fonts.font_manager.get_font_face(japanese_font).family
    assert {s.dxf.name: s.dxf.font for s in doc.styles if s.dxf.name in ("MSG", "SHX", "LATIN")} == {
        "MSG": japanese_font,
        "SHX": japanese_font,
        "LATIN": "romans.shx",
    }
    mtexts = [e.text for e in doc.modelspace().query("MTEXT")]
    assert mtexts == [f"\\f{family}|b0|i0|c128|p49;材質 PMMA", f"\\f{family};ゲート"], mtexts


def test_only_what_is_drawn_counts(japanese_font):
    """modelspace and the blocks it inserts (nested, and an insert's attributes) are drawn;
    paper space and a block nothing uses are not, and do not change a style"""
    doc = new_doc()
    for name in ("SHARED", "INBLOCK", "NESTED", "ATTR", "UNUSED"):
        doc.styles.new(name, dxfattribs={"font": "msgothic.ttc"})
    msp = doc.modelspace()
    msp.add_text("GATE", dxfattribs={"style": "SHARED"})
    doc.paperspace().add_text("注記", dxfattribs={"style": "SHARED"})
    inner = doc.blocks.new("INNER")
    inner.add_text("詳細", dxfattribs={"style": "NESTED"})
    title = doc.blocks.new("TITLE")
    title.add_text("表題", dxfattribs={"style": "INBLOCK"})
    title.add_blockref("INNER", (0, 0))
    msp.add_blockref("TITLE", (0, 0)).add_attrib("NAME", "品名", dxfattribs={"style": "ATTR"})
    doc.blocks.new("SPARE").add_text("予備", dxfattribs={"style": "UNUSED"})
    drawing._fit_fonts(doc)
    fonts_now = {s.dxf.name: s.dxf.font for s in doc.styles if s.dxf.name in ("SHARED", "INBLOCK", "NESTED", "ATTR", "UNUSED")}
    assert fonts_now == {
        "SHARED": "msgothic.ttc",  # Japanese in paper space only: not drawn
        "INBLOCK": japanese_font,
        "NESTED": japanese_font,
        "ATTR": japanese_font,
        "UNUSED": "msgothic.ttc",
    }
