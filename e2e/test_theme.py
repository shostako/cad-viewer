"""E2E: 配色 (表示 > 配色: ダーク / ライト / PC に合わせる).

The specification, written out here (not read from the code):
- the default is ダーク, as the app always was: the 3D background #1d2126
- ライト: the 3D background #e4e8ed; the panels light, their text at least
  4.5:1 against what is behind it (WCAG 2 contrast, the panels' own colours
  composited over the background); a dimension's end points #c05f00 and its
  line #9a6a00 (3:1 or more on the light background, where the dark ones'
  yellow is 1.3:1)
- switching repaints what is on screen: a saved dimension and the first point
  of a measurement waiting for its second; switching back gives the dark ones
  again (#ffb020, #ffd060). The edge under the cursor is #0a87b8 on the light
  page (#55d6ff on the dark one)
- 半透明 on the light page keeps the edge lines dark (#20262e): the dark page
  lifts them to the part's colour, which would wash out on the light one
- the choice survives a reload, and is in place before the app's code runs
  (index.html: no dark flash on a light page)
- PC に合わせる follows the system's setting (prefers-color-scheme), also when
  it changes while the page is open
- a loose-curve part (loose_faces_box.igs: 曲線（3 本）) is drawn in the
  theme's curve colour, #e0b050 dark and #9a6a00 light, and its mark in the
  part tree follows a switch
- a 2D drawing: ダーク its page is the 3D background, ライト a white page with
  the drawing's white lines black (as the white export); switching with a
  drawing open keeps its measurement, in the theme's colours (#9a6a00 on the
  white page); 表示 stays in 2D with 配色 alone

Oracles: the spec colours above, the screen's pixels (where the 3D points
project, window.__cadProject), computed styles with the WCAG formula,
mini_mold.step's make (testdata/make_step_assembly.py: the plate's top at z 15,
the cavity block from y 15) and plate_drawing.dxf's (a 200 x 100 plate, holes
at (50, 50) and (150, 50)).
"""
import io
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import gui_common
from nav_common import TESTDATA, nav_session, put_sidecar

DARK_SCENE = (0x1D, 0x21, 0x26)
LIGHT_SCENE = (0xE4, 0xE8, 0xED)
DARK_MARKER, DARK_DIM = (0xFF, 0xB0, 0x20), (0xFF, 0xD0, 0x60)
LIGHT_MARKER, LIGHT_DIM = (0xC0, 0x5F, 0x00), (0x9A, 0x6A, 0x00)
LIGHT_DIM_HEX = "#9a6a00"
DARK_PICK, LIGHT_PICK = (0x55, 0xD6, 0xFF), (0x0A, 0x87, 0xB8)
EDGE = (0x20, 0x26, 0x2E)

tmp = tempfile.mkdtemp(prefix="cad_theme_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 91)
# the plate's right top edge (x 100, z 15), away from the dimension below
EDGE_MID = (100, 30, 15)
# a distance along the plate's front, in front of the cavity block (y 15..45)
A, B = (10, 6, 15), (90, 6, 15)
ENTRY = {"text": "面#1 ↔ 面#2 : 80.000", "labelText": "80.000", "labelPos": [50, 6, 15],
         "line": [list(A), list(B)], "markers": [list(A), list(B)]}
# the first point of a new measurement: on the plate's top, where nothing is
# in front of it (the first of these that a pick finds there)
FIRSTS = [(95, 52, 15), (5, 52, 15), (95, 2, 15), (3, 30, 15)]


def lum(rgb):
    c = np.asarray(rgb, dtype=float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return float(lin @ np.array([0.2126, 0.7152, 0.0722]))


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def near(px, col, tol=6):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, col))


def dist(a, b):
    return sum(abs(int(x) - y) for x, y in zip(a, b))


def like(px, want, other, tol=48):
    """a thin line's pixel: within tol of its colour, and nearer it than the other
    theme's (a 1 px line blends with what is behind it on some GPUs)"""
    return near(px, want, tol) and dist(px, want) < dist(px, other)


with nav_session() as n:
    page = n.page
    page.set_viewport_size({"width": 1280, "height": 800})
    put_sidecar(page, mold, [ENTRY])

    def shot():
        return np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB"))

    def at(img, xy):
        return tuple(int(v) for v in img[int(round(xy[1])), int(round(xy[0]))])

    def closest(img, xy, col, r=2):
        """the pixel within r px of xy nearest to col (a 1 px line between pixels)"""
        x, y = int(round(xy[0])), int(round(xy[1]))
        box = img[y - r:y + r + 1, x - r:x + r + 1].reshape(-1, 3).astype(int)
        return tuple(box[np.argmin(np.abs(box - np.array(col)).sum(axis=1))])

    def theme():
        return page.evaluate("document.documentElement.dataset.theme")

    def choose(label):
        gui_common.open_folder(page, "表示")
        gui_common.ctl(page, "配色").locator("select").select_option(label=label)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        n.settle()
        page.wait_for_timeout(100)
        n.settle()

    def away():
        """the mouse off the model (no hover cues where the pixels are read)"""
        page.mouse.move(1270, 790)
        n.settle()

    def background_pixel(img):
        """the 3D background: the canvas's top-left, above the grid (the tree panel is to its right)"""
        cl, ct, cw, ch = n.canvas_rect()
        return at(img, (cl + 4, ct + ch - 4))

    def dimension(img):
        """the saved dimension's two end points and two points of its line (a quarter in from each end)"""
        pa, pb = n.project_many([A, B])
        q1 = [pa[0] + (pb[0] - pa[0]) / 4, pa[1] + (pb[1] - pa[1]) / 4]
        q3 = [pa[0] + 3 * (pb[0] - pa[0]) / 4, pa[1] + 3 * (pb[1] - pa[1]) / 4]
        return pa, pb, q1, q3

    def check_dimension(marker, dim, what):
        img = shot()
        pa, pb, q1, q3 = dimension(img)
        for p in (pa, pb):
            assert near(at(img, p), marker), (what, "an end point", at(img, p), marker)
        other = LIGHT_DIM if dim == DARK_DIM else DARK_DIM
        for q in (q1, q3):
            c = closest(img, q, dim)
            assert like(c, dim, other), (what, "the line", c, dim)
        return img

    # ---- the default: ダーク, as always
    n.load(str(mold), props="live")
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 1", timeout=10000)
    away()
    assert theme() == "dark", theme()
    gui_common.open_folder(page, "表示")
    assert gui_common.ctl(page, "配色").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "ダーク"
    img = check_dimension(DARK_MARKER, DARK_DIM, "dark")
    assert near(background_pixel(img), DARK_SCENE, 2), background_pixel(img)
    print("1 dark: background", background_pixel(img))

    # ---- ライト: the background, the dimension repainted
    choose("ライト")
    away()
    assert theme() == "light", theme()
    img = check_dimension(LIGHT_MARKER, LIGHT_DIM, "light")
    bg = background_pixel(img)
    assert near(bg, LIGHT_SCENE, 2), bg
    assert contrast(LIGHT_MARKER, LIGHT_SCENE) >= 3 and contrast(LIGHT_DIM, LIGHT_SCENE) >= 3
    print("2 light: background", bg, "marker", contrast(LIGHT_MARKER, LIGHT_SCENE), "line", contrast(LIGHT_DIM, LIGHT_SCENE))

    # ---- the panels' text: 4.5:1 against what is behind it
    gui_common.open_folder(page, "問題の一覧")
    gui_common.ctl(page, "一覧を出す").locator("input").check()
    page.wait_for_function("!!window.__cadCheck()", timeout=60000)
    n.settle()
    away()
    low = page.evaluate(
        """() => {
          const parse = (c) => {
            const m = c.match(/rgba?\\(([^)]+)\\)/)
            if (!m) return [0, 0, 0, 0]
            const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number)
            return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]
          }
          const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
          const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])
          const over = (top, under) => under.map((v, i) => v * (1 - top[3]) + top[i] * top[3])
          const scene = parse(getComputedStyle(document.body).backgroundColor).slice(0, 3)
          const behind = (el) => {
            const chain = []
            for (let e = el; e; e = e.parentElement) chain.unshift(e)
            return chain.reduce((c, e) => over(parse(getComputedStyle(e).backgroundColor), c), scene)
          }
          const out = []
          let checked = 0
          const roots = ['#tree-panel', '.lil-gui.lil-root', '#measure-panel', '#props-panel', '#check-panel', '#hud']
          for (const root of roots) {
            for (const el of document.querySelectorAll(root + ', ' + root + ' *')) {
              const own = [...el.childNodes].some((t) => t.nodeType === 3 && t.textContent.trim())
              if (!own || !el.getClientRects().length || el.closest('.lil-disabled, [disabled]')) continue
              const cs = getComputedStyle(el)
              if (cs.visibility === 'hidden' || +cs.opacity < 1) continue
              checked++
              const bg = behind(el)
              const fg = over(parse(cs.color), bg)
              const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x)
              const ratio = (a + 0.05) / (b + 0.05)
              if (ratio < 4.5) out.push([root, el.className || el.tagName, el.textContent.trim().slice(0, 20), +ratio.toFixed(2)])
            }
          }
          return { out, checked }
        }"""
    )
    assert low["checked"] > 60, ("the panels' texts were looked at", low["checked"])
    assert not low["out"], ("text under 4.5:1 on the light panels", low["out"])
    lil_bg = page.evaluate("getComputedStyle(document.querySelector('.lil-gui.lil-root')).backgroundColor")
    assert lum(tuple(int(v) for v in lil_bg[lil_bg.index("(") + 1:lil_bg.index(")")].split(",")[:3])) > 0.8, lil_bg
    print("3 light panels:", low["checked"], "texts, every one 4.5:1 or more; the operation panel", lil_bg)

    # ---- the first point of a measurement, repainted while it waits
    gui_common.ctl(page, "一覧を出す").locator("input").uncheck()
    n.set_mode("計測")
    away()

    def edge_under_cursor(pick):
        pe = n.project(EDGE_MID)
        page.mouse.move(*pe)
        n.settle()
        page.wait_for_function("document.querySelector('#cursor-tip')?.textContent.includes('エッジ')", timeout=10000)
        n.settle()
        c = closest(shot(), pe, pick, 3)
        away()
        return c

    c = edge_under_cursor(LIGHT_PICK)
    assert like(c, LIGHT_PICK, DARK_PICK), ("light: the edge under the cursor", c)
    pf = None
    for p in FIRSTS:
        q = n.project(p)
        hit = n.pick(q)
        if hit and hit.get("kind") == "face" and max(abs(a - b) for a, b in zip(hit["point"], p)) < 0.5:
            pf = q
            break
    assert pf, "a free place on the plate's top"
    page.mouse.move(*pf)
    n.settle()
    page.mouse.click(*pf)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('2 点目')", timeout=20000)
    away()
    img = shot()
    assert near(at(img, pf), LIGHT_MARKER), ("light: the first point", at(img, pf))
    choose("ダーク")
    away()
    img = shot()
    assert near(at(img, pf), DARK_MARKER), ("dark again: the first point", at(img, pf))
    check_dimension(DARK_MARKER, DARK_DIM, "dark again")
    page.keyboard.press("Escape")
    n.settle()
    c = edge_under_cursor(DARK_PICK)
    assert like(c, DARK_PICK, LIGHT_PICK), ("dark again: the edge under the cursor", c)
    print("4 the first point, the saved dimension and the edge under the cursor repainted both ways")

    # ---- 半透明 on the light page: the edge lines stay dark
    n.set_mode("なし")
    choose("ライト")
    gui_common.ctl(page, "表示スタイル").locator("select").select_option(label="半透明")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    n.settle()
    away()
    pe = n.project(EDGE_MID)
    c = closest(shot(), pe, EDGE, 3)
    # lifted for the dark page it would be the plate's grey (about 150 a channel)
    assert near(c, EDGE, 48), ("light 半透明: a dark edge", c)
    gui_common.ctl(page, "表示スタイル").locator("select").select_option(label="陰影＋稜線")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    n.settle()
    print("4b light 半透明: the edge", tuple(int(v) for v in c))

    # ---- kept: a reload comes up light, before the app's code runs (with
    # every script but the page's own stopped, only index.html can say it)
    choose("ライト")
    page.route("**/*", lambda r: r.abort() if r.request.resource_type == "script" else r.continue_())
    page.reload()
    early = page.evaluate("[document.documentElement.dataset.theme, typeof window.__cadProject]")
    assert early == ["light", "undefined"], early
    page.unroute("**/*")
    n.errors[:] = [e for e in n.errors if "ERR_FAILED" not in e]  # the scripts stopped on purpose
    page.reload()
    page.wait_for_selector("#file-input", state="attached")
    n.settle()
    url = page.evaluate("document.querySelector('#viewport canvas').toDataURL()")
    import base64

    empty = np.asarray(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB"))
    assert near(at(empty, (empty.shape[1] // 2, 4)), LIGHT_SCENE, 2), at(empty, (empty.shape[1] // 2, 4))
    print("5 reloaded:", early, "the empty view", at(empty, (empty.shape[1] // 2, 4)))

    # ---- PC に合わせる: the system's setting, also when it changes
    page.emulate_media(color_scheme="dark")
    choose("PC に合わせる")
    assert theme() == "dark", theme()
    page.emulate_media(color_scheme="light")
    page.wait_for_function("document.documentElement.dataset.theme === 'light'", timeout=5000)
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'", timeout=5000)
    page.reload()
    page.wait_for_selector("#file-input", state="attached")
    assert theme() == "dark", theme()
    page.emulate_media(color_scheme="light")
    page.wait_for_function("document.documentElement.dataset.theme === 'light'", timeout=5000)
    print("6 PC に合わせる follows the system")

    # ---- a loose-curve part: its mark in the part tree follows the switch
    choose("ダーク")
    n.load(str(TESTDATA / "loose_faces_box.igs"))
    mark = """(() => {
        const row = [...document.querySelectorAll('#tree-panel .tree-row')].find((r) => r.textContent.includes('曲線'))
        return row && getComputedStyle(row.querySelector('.tree-mark')).backgroundColor
    })()"""
    assert page.evaluate(mark) == "rgb(224, 176, 80)", page.evaluate(mark)
    choose("ライト")
    assert page.evaluate(mark) == "rgb(154, 106, 0)", ("light: the curves' mark", page.evaluate(mark))
    choose("ダーク")
    assert page.evaluate(mark) == "rgb(224, 176, 80)", ("dark again: the curves' mark", page.evaluate(mark))
    print("6b the loose curves' mark in the tree follows the theme")

    # ---- a 2D drawing: its page, its lines, a measurement kept across a switch
    page.set_input_files("#file-input", str(TESTDATA / "plate_drawing.dxf"))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('2D 図面')", timeout=60000)
    page.wait_for_timeout(300)
    page_fill = "document.querySelector('#viewport2d svg > rect').getAttribute('fill')"
    assert page.evaluate(page_fill).lower() == "#1d2126", page.evaluate(page_fill)
    # 表示 in 2D: 配色 alone
    rows = page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-title')].find(t => t.textContent.trim() === '表示').parentElement
                   return [...f.querySelectorAll('.lil-controller')].filter(c => c.getClientRects().length).map(c => c.querySelector('.lil-name').textContent) }"""
    )
    assert rows == ["配色"], rows
    gui_common.ctl(page, "モード").locator("select").select_option("計測")

    def svg_click(x, y):
        pos = page.evaluate(
            """([x, y]) => {
                const svg = document.querySelector('#viewport2d svg')
                const vb = svg.viewBox.baseVal
                const sx = (vb.width + 2 * vb.x) / 200, sy = (vb.height + 2 * vb.y) / 100
                const pt = new DOMPoint(x * sx, (100 - y) * sy).matrixTransform(svg.getScreenCTM())
                return { x: pt.x, y: pt.y }
            }""",
            [x, y],
        )
        page.mouse.click(pos["x"], pos["y"])
        page.wait_for_timeout(300)

    svg_click(50, 50)
    svg_click(150, 50)
    assert "100.000" in page.text_content("#hud-info")
    gui_common.ctl(page, "モード").locator("select").select_option("なし")
    lines = "[...document.querySelectorAll('#viewport2d .dimline2d')].map(l => l.getAttribute('stroke'))"
    assert page.evaluate(lines) == ["#ffd060"], page.evaluate(lines)

    def drawing_pixels():
        """the drawing's page on screen, short of the panels over it (their text is dark or light too)"""
        r = page.evaluate(
            """(() => {
                const b = document.querySelector('#viewport2d svg > rect').getBoundingClientRect()
                const gui = document.querySelector('.lil-gui.lil-root').getBoundingClientRect()
                const hud = document.querySelector('#hud').getBoundingClientRect()
                return [b.left, b.top, Math.min(b.right, gui.left), Math.min(b.bottom, hud.top)]
            })()"""
        )
        img = shot()[int(r[1]) + 4:int(r[3]) - 4, int(r[0]) + 4:int(r[2]) - 4]
        assert img.shape[0] > 100 and img.shape[1] > 300, img.shape
        return img.reshape(-1, 3)

    dark_px = drawing_pixels()
    choose("ライト")
    assert page.evaluate(page_fill).lower() == "#ffffff", page.evaluate(page_fill)
    assert page.evaluate(lines) == [LIGHT_DIM_HEX], ("the measurement kept, in the light colour", page.evaluate(lines))
    assert page.evaluate("document.querySelectorAll('#viewport2d svg').length") == 2, "the drawing and the measurement layer, once each"
    light_px = drawing_pixels()
    white = (light_px.min(axis=1) >= 250).mean()
    dark_ink = (light_px.max(axis=1) <= 60).sum()
    bright_ink_dark = (dark_px.min(axis=1) >= 200).sum()
    assert white > 0.9, ("a white page", white)
    assert dark_ink > 100 and bright_ink_dark > 100, ("the white lines drawn black", dark_ink, bright_ink_dark)
    choose("ダーク")
    assert page.evaluate(page_fill).lower() == "#1d2126" and page.evaluate(lines) == ["#ffd060"]
    print("7 2D: page", "white", round(white, 3), "black lines", int(dark_ink), "(white on the dark page", int(bright_ink_dark), ")")

    assert not n.errors, n.errors
print("THEME E2E OK")
