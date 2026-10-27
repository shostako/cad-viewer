"""DXF/DWG (2D drawing) loading: SVG rendering + snap point extraction.

Coordinate mapping (verified empirically, ezdxf 1.4):
with Page(width=bbox_w, height=bbox_h, mm, margins=0) the SVG viewBox is
normalized to `0 0 W H` with max(W, H) = 1,000,000, mapping model coords
linearly and y-flipped. The scale is derived from the emitted viewBox
(never assumed):
    svg_x = (x - xmin) * (W / bbox_w)
    svg_y = (ymax - y) * (H / bbox_h)
Snap points are shipped in BOTH coordinate systems: svg coords for display
alignment, DXF coords for exact measurement values.

Japanese text (issue #90): ezdxf draws a text style whose font the PC lacks
with DejaVu Sans, and a character a font lacks as a box. In a drawing with
Japanese in it, a style whose font has none of it is given a font that has
(CJK_FONTS, the first found). CAD_VIEWER_FONT_DIRS (folders, os.pathsep
between) adds fonts to the PC's: the tests' and the Web version's (Noto Sans JP).

A DXF before R2007 that names no code page ($DWGCODEPAGE) is read as
ANSI_1252; Japanese CAD writes such files in Shift_JIS. One whose text is
Shift_JIS with kana or full-width characters in it is read as ANSI_932
(_declare_codepage).

A SPLINE whose curve ezdxf cannot make (fit points with one repeated: a
ZeroDivisionError) stopped the whole drawing. It is made drawable, or left out
(_repair_splines); any other failure in drawing is a DrawingLoadError, said in
words, not an internal error.

DWG requires the free ODA File Converter (not redistributable); when absent
we fail with an actionable message. It is looked for on PATH, and on Windows
also where its installer puts it (C:\\Program Files\\ODA\\ODAFileConverter
<version>\\, the newest one).
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
from typing import Any

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf import recover
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.fonts import fonts
from ezdxf.math import Vec3
from ezdxf.path import make_path

MAX_SNAP_POINTS = 50000

ODA_HINT = (
    "DWGの読み込みには ODA File Converter が必要（無料・手動インストール）。"
    "https://www.opendesign.com/guestfiles/oda_file_converter から入手して入れる"
    "（Windows は既定の場所に入れれば見つける。ほかの場所や Linux では PATH に通す）。"
    "DXFなら直接読める。"
)


def _version_key(path: str) -> tuple:
    """ODAFileConverter 26.4.0 -> (26, 4, 0): the newest install sorts last"""
    folder = os.path.basename(os.path.dirname(path))
    return tuple(int(n) for n in re.findall(r"\d+", folder))


def find_oda() -> str | None:
    """the ODA File Converter's executable, or None when it is not installed"""
    found = shutil.which("ODAFileConverter")
    if found or sys.platform != "win32":
        return found
    hits = []
    for root in {os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")} - {None}:
        hits += glob.glob(os.path.join(root, "ODA", "ODAFileConverter*", "ODAFileConverter.exe"))
    return max(hits, key=_version_key) if hits else None


class DrawingLoadError(Exception):
    pass


# Japanese (and the other CJK scripts): the CJK punctuation, kana, the
# ideographs and their compatibility forms, the full-width forms
_CJK = re.compile("[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

# fonts with Japanese in them, the first one found used: the Web version's
# (bundled), Linux's (Noto CJK), Windows' (Yu Gothic, Meiryo, MS Gothic), Office's
CJK_FONTS = (
    "NotoSansJP-Regular.otf",
    "NotoSansCJK-Regular.ttc",
    "NotoSansCJKjp-Regular.otf",
    "YuGothR.ttc",
    "YuGothM.ttc",
    "meiryo.ttc",
    "msgothic.ttc",
    "ArialUni.ttf",
)

_extra_fonts_added = False
# the routes run in threads: the fonts added once, by one of them
_fonts_lock = threading.Lock()


def _add_extra_fonts() -> None:
    """CAD_VIEWER_FONT_DIRS' fonts beside the PC's (once)"""
    global _extra_fonts_added
    with _fonts_lock:
        if _extra_fonts_added:
            return
        _extra_fonts_added = True
        dirs = [d for d in os.environ.get("CAD_VIEWER_FONT_DIRS", "").split(os.pathsep) if d and os.path.isdir(d)]
        if dirs:
            fonts.font_manager.build(dirs, support_dirs=False)
            forget_font_lookups()


# what ezdxf remembers of its font lookups (ezdxf 1.4.4's own names, pinned in
# requirements.lock): a family not found, a missing font's stand-in (DejaVu Sans) kept
# under that font's name, the glyph renderers by font file. tests/test_drawing_japanese.py
# checks they are there (an ezdxf upgrade that renames them fails it, not a drawing)
FONT_LOOKUPS = (("font_manager", "_match_cache"), ("font_manager", "_loaded_ttf_fonts"), ("_CachedFont", "_glyph_caches"))


def forget_font_lookups() -> None:
    """after fonts are added (here, and the Web version's Japanese font: src/local/drawing.ts):
    what ezdxf remembers of the lookups made before them forgotten (one not there: nothing to
    forget)"""
    for owner, name in FONT_LOOKUPS:
        memo = getattr(getattr(fonts, owner, None), name, None)
        if memo is not None:
            memo.clear()


def _drawn_entities(doc):
    """the entities load_drawing draws: modelspace's, and those of the blocks they insert
    (an INSERT's, a dimension's), nested; an INSERT's attributes too. Not paper space, not a
    block nothing in modelspace uses"""
    seen: set[str] = set()
    layouts = [doc.modelspace()]
    while layouts:
        for e in layouts.pop():
            yield e
            t = e.dxftype()
            if t == "INSERT":
                yield from e.attribs
                name = e.dxf.get("name")
            elif t in ("DIMENSION", "ARC_DIMENSION", "RADIAL_DIMENSION", "LARGE_RADIAL_DIMENSION"):
                name = e.dxf.get("geometry")
            else:
                continue
            if name and name not in seen and name in doc.blocks:
                seen.add(name)
                layouts.append(doc.blocks.get(name))


def _japanese_by_style(doc) -> dict[str, set[str]]:
    """the Japanese characters each text style draws (styles by name, in lower case), of the
    entities drawn (modelspace's and its blocks'): a text's, an attribute's, an MTEXT's style. A dimension's text is an MTEXT in its block
    (ezdxf draws a dimension from its block only), in its dimension style's text style"""
    out: dict[str, set[str]] = {}

    def add(style: str | None, text: str | None) -> None:
        chars = set(_CJK.findall(text or ""))
        if chars:
            out.setdefault((style or "Standard").lower(), set()).update(chars)

    for e in _drawn_entities(doc):
        t = e.dxftype()
        if t == "MTEXT":
            add(e.dxf.get("style"), e.text)
        elif t in ("TEXT", "ATTRIB", "ATTDEF"):
            add(e.dxf.get("style"), e.dxf.get("text"))
    return out


def _style_font_file(style) -> str:
    """the font file a text style is drawn with here (ezdxf's own choice, the fallback included)"""
    font = style.dxf.get("font", "") or ""
    if font:
        order = ezdxf.options.get("drawing-addon", "shx_resolve_order", "tsl")  # as the drawing add-on resolves it
        return fonts.resolve_font_face(font, order=order).filename
    family, italic, bold = style.get_extended_font_data()
    face = fonts.find_best_match(family=family, weight=700 if bold else 400, italic=italic) if family else None
    return (face or fonts.FontFace()).filename or fonts.font_manager.fallback_font_name()


def _has_glyphs(font_file: str, chars: set[str]) -> bool:
    """a TrueType/OpenType font with all of chars (a stroke font: none)"""
    if not font_file.lower().endswith((".ttf", ".ttc", ".otf")):
        return False
    try:
        cmap = fonts.font_manager.get_ttf_font(font_file).getBestCmap()
    except Exception:  # noqa: BLE001 — unreadable: as one without them
        return False
    return all(ord(c) in cmap for c in chars)


# an MTEXT's font change: \\fFamily|b0|i0|c128|p49; or \\Ffile.shx|c0; (not after an escaping backslash)
_MTEXT_FONT = re.compile(r"(?<!\\)\\([fF])([^|;]*)((?:\|[^;]*)?);")


def _fit_mtext(mtext, used: set[str], cjk: str, cjk_family: str) -> None:
    """an MTEXT's font changes to a font without Japanese: to the one with it (a family not
    found, or any font file, draws no Japanese at all, not even boxes)"""

    def swap(m: re.Match) -> str:
        code, name, rest = m.groups()
        if code == "f":
            face = fonts.find_best_match(family=name) if name else None
            if face is not None and _has_glyphs(face.filename, used):
                return m.group(0)
            return f"\\f{cjk_family}{rest};"
        order = ezdxf.options.get("drawing-addon", "shx_resolve_order", "tsl")
        if name and _has_glyphs(fonts.resolve_font_face(name, order=order).filename, used):
            return m.group(0)
        # a font file (\\F, AutoCAD's for SHX fonts): ezdxf draws no Japanese from one, even
        # one that has it; changed to a font family (its |… settings dropped: \\F's are not \\f's)
        return f"\\f{cjk_family};"

    mtext.text = _MTEXT_FONT.sub(swap, mtext.text)


def _fit_fonts(doc) -> None:
    """in a drawing with Japanese in it, the text styles that draw it and the MTEXTs' font
    changes, whose font has none of it, given a font that has (a style with Latin text only
    keeps its font)"""
    by_style = _japanese_by_style(doc)
    if not by_style:
        return
    _add_extra_fonts()
    cjk = next((f for f in CJK_FONTS if fonts.font_manager.has_font(f)), None)
    if cjk is None:
        return  # none on this PC: as before
    for style in doc.styles:
        used = by_style.get(style.dxf.name.lower())
        if used and not _has_glyphs(_style_font_file(style), used):
            style.dxf.font = cjk
    family = fonts.font_manager.get_font_face(cjk).family
    for e in _drawn_entities(doc):
        if e.dxftype() == "MTEXT":
            used = set(_CJK.findall(e.text))
            if used:
                _fit_mtext(e, used, cjk, family)


# A DXF before R2007 (AC1021) is in the code page its $DWGCODEPAGE names, and ezdxf reads one
# that names none as ANSI_1252. Japanese CAD writes some without it, in Shift_JIS (a mold
# drawing, AC1014): every Japanese text garbled. Read as ANSI_932 when its text is all
# Shift_JIS with kana or full-width characters in it (a Western file read as Shift_JIS
# hardly gives those: they are Shift_JIS's leads 0x81-0x84, rare or unused in ANSI_1252)
_ACADVER = re.compile(rb"\$ACADVER[ \t]*(\r?\n)[ \t]*1[ \t]*\r?\n[ \t]*(AC\d{4})[ \t]*\r?\n")
_KANA_OR_FULL_WIDTH = re.compile("[\u3000-\u30ff\uff01-\uff60]")


def _declare_codepage(data: bytes) -> bytes:
    """a DXF (bytes) that names no code page and is in Shift_JIS (above): $DWGCODEPAGE
    ANSI_932 put after its $ACADVER. Any other: as it is"""
    if data.startswith(b"AutoCAD Binary DXF") or b"$DWGCODEPAGE" in data:
        return data
    m = _ACADVER.search(data)
    if m is None or m.group(2) >= b"AC1021":
        return data  # R2007 and after: UTF-8 whatever it names
    try:
        text = [line.decode("cp932") for line in data.splitlines() if not line.isascii()]
    except UnicodeDecodeError:
        return data
    if not any(_KANA_OR_FULL_WIDTH.search(t) for t in text):
        return data
    nl = m.group(1)
    return data[: m.end()] + b"  9" + nl + b"$DWGCODEPAGE" + nl + b"  3" + nl + b"ANSI_932" + nl + data[m.end() :]


def _curve_ok(spline) -> bool:
    """ezdxf makes the SPLINE's curve (what the drawing and its extents are made of)"""
    try:
        make_path(spline)
    except Exception:  # noqa: BLE001 — any: the drawing would not open
        return False
    return True


def _repair_splines(doc) -> None:
    """the SPLINEs drawn whose curve ezdxf cannot make, made drawable. Japanese CAD writes fit
    points with one repeated (two at the same place: a step of zero, ZeroDivisionError): the
    repeated one dropped. Still not: a polyline through its points (the control points, else
    the fit points; ezdxf draws a SPLINE of degree 1 rounded at its corners), in its place
    with its layer, colour and line. Fewer than 2 points: left out"""
    for e in [e for e in _drawn_entities(doc) if e.dxftype() == "SPLINE" and not _curve_ok(e)]:
        by_fit = not e.control_point_count()
        points = Vec3.list(e.fit_points if by_fit else e.control_points)
        distinct = points[:1]
        for p in points[1:]:
            if not p.isclose(distinct[-1], abs_tol=1e-9):
                distinct.append(p)
        if by_fit:
            e.fit_points = distinct
            if _curve_ok(e):
                continue
        layout = e.get_layout()
        if layout is None:
            continue
        if len(distinct) >= 2:
            layout.add_polyline3d(distinct, dxfattribs=e.graphic_properties())
        layout.delete_entity(e)


def load_drawing(data: bytes, filename: str) -> tuple[str, dict[str, Any]]:
    """bytes -> (svg string, meta with snap points and bbox)."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext != "dwg":
        data = _declare_codepage(data)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, f"input.{ext}")
        with open(path, "wb") as f:
            f.write(data)

        if ext == "dwg":
            oda = find_oda()
            if oda is None:
                raise DrawingLoadError(ODA_HINT)
            import ezdxf
            from ezdxf.addons import odafc

            if sys.platform == "win32":
                # ezdxf looks only at its own setting (a fixed folder without the version)
                ezdxf.options.set("odafc-addon", "win_exec_path", oda)
            else:
                # WSLg では WAYLAND_DISPLAY が立っており、Qt が wayland プラグインを
                # 探して stderr に警告を吐く。ezdxf の odafc は stderr 非空を失敗と
                # みなすため、xcb を明示して警告ごと黙らせる（変換自体は headless）。
                # Windows の Qt には xcb が無いので、Linux だけ。
                os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

            try:
                doc = odafc.readfile(path)
            except Exception as e:
                raise DrawingLoadError(f"DWG変換失敗: {e}") from e
        else:
            try:
                doc, auditor = recover.readfile(path)
            except Exception as e:
                raise DrawingLoadError(f"DXF読み込み失敗: {e}") from e
            if auditor.has_errors:
                # recovered with errors — still usable, but note it
                pass

    try:
        return _draw(doc)
    except DrawingLoadError:
        raise
    except Exception as e:
        # an internal error said in words (the upload says "Internal Server Error" only)
        logging.getLogger(__name__).exception("drawing %s failed", filename)
        raise DrawingLoadError(f"図面の描画に失敗: {type(e).__name__}: {e}") from e


def _draw(doc) -> tuple[str, dict[str, Any]]:
    """a drawing read: (svg, meta) (load_drawing's)"""
    _repair_splines(doc)
    _fit_fonts(doc)
    msp = doc.modelspace()
    extents = ezbbox.extents(msp, fast=True)
    if not extents.has_data:
        raise DrawingLoadError("図面に描画エンティティが無い")
    xmin, ymin = extents.extmin.x, extents.extmin.y
    xmax, ymax = extents.extmax.x, extents.extmax.y
    w = max(xmax - xmin, 1e-9)
    h = max(ymax - ymin, 1e-9)

    ctx = RenderContext(doc)
    backend = SVGBackend()
    Frontend(ctx, backend).draw_layout(msp, finalize=True)
    page = layout.Page(w, h, layout.Units.mm, margins=layout.Margins.all(0))
    svg = backend.get_string(page)

    # derive the actual scale from the emitted viewBox (do not assume it)
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if m is None:
        raise DrawingLoadError("SVG viewBox not found (ezdxf output format changed?)")
    vb_w, vb_h = float(m.group(1)), float(m.group(2))
    sx = vb_w / w
    sy = vb_h / h

    # widen the viewBox 1% per side so boundary strokes aren't clipped.
    # coordinates inside the svg are untouched — the snap mapping stays exact.
    pad = 0.01 * max(vb_w, vb_h)
    svg = svg.replace(
        m.group(0),
        f'viewBox="{-pad:.1f} {-pad:.1f} {vb_w + 2 * pad:.1f} {vb_h + 2 * pad:.1f}"',
        1,
    )

    snaps = _snap_points(msp)

    def to_svg(p: tuple[float, float]) -> list[float]:
        return [round((p[0] - xmin) * sx, 1), round((ymax - p[1]) * sy, 1)]

    meta = {
        "bbox2d": {"min": [xmin, ymin], "max": [xmax, ymax]},
        "svgScale": [sx, sy],
        "snapPoints": [
            {"dxf": [round(p[0], 6), round(p[1], 6)], "svg": to_svg(p), "kind": k}
            for p, k in snaps
        ],
    }
    return svg, meta


MAX_INSERT_DEPTH = 4  # nested block references: expand a few levels, no more


def _snap_points(msp) -> list[tuple[tuple[float, float], str]]:
    """Endpoint / center / vertex snap targets from common entity types.

    INSERT (block reference) entities are expanded via virtual_entities(),
    which yields transformed copies of the block contents — the SVG renderer
    draws that geometry, so it must be snappable too, not just the insertion
    point. Depth-limited for nested blocks.
    """
    out: list[tuple[tuple[float, float], str]] = []

    def add(x: float, y: float, kind: str) -> None:
        if len(out) < MAX_SNAP_POINTS:
            out.append(((x, y), kind))

    def scan(entities, depth: int) -> None:
        for e in entities:
            if len(out) >= MAX_SNAP_POINTS:
                return  # cap reached — stop scanning entities entirely
            t = e.dxftype()
            try:
                if t == "LINE":
                    add(e.dxf.start.x, e.dxf.start.y, "end")
                    add(e.dxf.end.x, e.dxf.end.y, "end")
                elif t == "CIRCLE":
                    c, r = e.dxf.center, e.dxf.radius
                    add(c.x, c.y, "center")
                    for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
                        add(c.x + dx, c.y + dy, "quadrant")
                elif t == "ARC":
                    c = e.dxf.center
                    add(c.x, c.y, "center")
                    sp, ep = e.start_point, e.end_point
                    add(sp.x, sp.y, "end")
                    add(ep.x, ep.y, "end")
                elif t == "LWPOLYLINE":
                    for x, y, *_ in e.get_points():
                        add(x, y, "vertex")
                elif t == "POLYLINE":
                    for v in e.vertices:
                        add(v.dxf.location.x, v.dxf.location.y, "vertex")
                elif t == "POINT":
                    add(e.dxf.location.x, e.dxf.location.y, "point")
                elif t == "INSERT":
                    add(e.dxf.insert.x, e.dxf.insert.y, "insert")
                    if depth < MAX_INSERT_DEPTH:
                        # transformed virtual copies of the block contents
                        scan(e.virtual_entities(), depth + 1)
            except Exception:
                continue  # skip malformed entities

    scan(msp, 0)
    return out
