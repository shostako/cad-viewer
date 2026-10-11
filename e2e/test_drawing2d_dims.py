"""E2E: 2D drawings — readable dimension values, 2D measurements in the 計測 list,
the drawing on the 3D background (issue #23 item 12).

- the measurement layer (markers, dimension lines, values) is drawn in screen px:
  the value is a 13 px text at 767 x 639 and at 1920 x 1080, after zooming in
  and out, panning and resizing (Chromium caps an SVG font size at 10000 user
  units; drawn in the drawing's own units, a viewBox about 1e6 wide, the value
  needed more than that on a window narrower than about 1330 px and shrank),
  and the markers and lines stay on the projected snap points
- the 計測 list has a row per 2D measurement with its value, ΔX and ΔY; the
  value can be selected (double-click) to copy it; a row's × deletes that one,
  元に戻す / Ctrl+Z puts it back in its place, and so for 計測クリア; an undo
  keeps a first point chosen after the deletion; a new measurement ends it
- the PNG export has the layer at the same place and size and in its colours,
  on the screen's page and on the white one, also at devicePixelRatio 2
- the page on screen is the 3D background #1d2126 (the drawing's own page and
  the area around it), and the drawing's lines show on it (3:1 or more)

Oracles: the known drawing (testdata/make_dxf.py, plate_drawing.dxf: a 200 x 100
outline, holes r10 at (50,50) and (150,50), a centre line y=50), mapped to the
page through the ezdxf background rect (the drawing's extents) and the drawing
svg's getScreenCTM; the computed font size times the text's screen scale; a
13 px reference text that the test draws itself (its height and the height of
its digits above the baseline); page screenshots and the downloaded PNGs; the
spec colours (page #1d2126, markers #ffb020, values and lines #ffd060). The
sidecar is answered in the page (page.route): nothing reaches the shared backend.
"""
import io
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright
from engine_net import Net

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
DXF = str(TESTDATA / "plate_drawing.dxf")
SIZE = (200, 100)  # the drawing's extents (make_dxf.py)
SMALL, LARGE = (767, 639), (1920, 1080)  # half a screen, a full HD screen
PAGE = (0x1D, 0x21, 0x26)  # the 3D background: the drawing's page on screen
MARKER = (0xFF, 0xB0, 0x20)
DIM = (0xFF, 0xD0, 0x60)
FONT_PX = 13  # the value's size on screen
MARKER_PX = 10  # a marker's diameter on screen
# snap points: hole centres and quadrants, outline corners, the centre line's end
M1 = ((50, 50), (150, 50))
M2 = ((0, 100), (50, 40))
M3 = ((150, 40), (200, 50))
M4 = ((50, 60), (160, 50))
M5 = ((0, 50), (40, 50))
INTERIOR = (100, 75)  # page between the centre line and the top edge, clear of every measurement
LINES = [(100, 100), (0, 25), (150, 60)]  # the outline's top and left edges, hole 2's top


def expected(m):
    dx, dy = m[1][0] - m[0][0], m[1][1] - m[0][1]
    return math.hypot(dx, dy), abs(dx), abs(dy)


def decode(data):
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(int)


def near_colour(px, col, tol):
    return np.all(np.abs(px - np.array(col)) <= tol, axis=-1)


def luminance(rgb):
    """WCAG relative luminance of 0-255 sRGB pixels (... x 3)"""
    c = np.asarray(rgb, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def inside(pt, r, margin=0):
    return r[0] - margin <= pt[0] <= r[2] + margin and r[1] - margin <= pt[1] <= r[3] + margin


OVERLAY_JS = """() => {
  const q = (sel) => [...document.querySelectorAll(sel)]
  const at = (el, x, y) => { const p = new DOMPoint(x, y).matrixTransform(el.getScreenCTM()); return [p.x, p.y] }
  return {
    texts: q('#viewport2d svg .overlay2d text.dimtext2d').map((t) => {
      const r = t.getBoundingClientRect(), m = t.getScreenCTM()
      return { value: t.textContent, rect: [r.left, r.top, r.right, r.bottom],
               px: parseFloat(getComputedStyle(t).fontSize) * Math.hypot(m.a, m.b) }
    }),
    circles: q('#viewport2d svg .overlay2d circle').map((c) => {
      const r = c.getBoundingClientRect()
      return [(r.left + r.right) / 2, (r.top + r.bottom) / 2, r.width, r.height]
    }),
    lines: q('#viewport2d svg .overlay2d line').map((l) =>
      [...at(l, l.x1.baseVal.value, l.y1.baseVal.value), ...at(l, l.x2.baseVal.value, l.y2.baseVal.value)]),
  }
}"""

tmp = tempfile.mkdtemp(prefix="cad_dims_")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": SMALL[0], "height": SMALL[1]}, device_scale_factor=1, accept_downloads=True
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        Net.of(page).route(
            "**/sidecar",
            lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {"saved": True}),
        )
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        def settle():
            page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

        def ctl(name):
            label = page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
            return page.locator(".lil-gui .lil-controller").filter(has=label).first

        def blur():
            page.evaluate("document.activeElement && document.activeElement.blur()")

        def set_mode(label):
            ctl("モード").locator("select").select_option(label)
            blur()

        def hud():
            return page.text_content("#hud-info")

        def dxf_client(x, y):
            """DXF mm -> client px, through the ezdxf background rect (the drawing's extents)"""
            r = page.evaluate(
                """([x, y, w, h]) => {
                    const svg = document.querySelector('#viewport2d svg')
                    const s = svg.querySelector(':scope > rect').width.baseVal.value / w
                    const pt = new DOMPoint(x * s, (h - y) * s).matrixTransform(svg.getScreenCTM())
                    return [pt.x, pt.y] }""",
                [x, y, SIZE[0], SIZE[1]],
            )
            return (r[0], r[1])

        def rect_of(sel):
            """client rect (l, t, r, b) of the first visible match, or None"""
            return page.evaluate(
                """sel => { const e = [...document.querySelectorAll(sel)].find(
                    (x) => x.getClientRects().length && getComputedStyle(x).display !== 'none');
                  if (!e) return null; const r = e.getBoundingClientRect();
                  return [r.left, r.top, r.right, r.bottom] }""",
                sel,
            )

        def covers():
            """panels over the drawing on screen (a screenshot shows them, an export does not)"""
            sels = (".lil-gui.lil-root", "#hud", "#measure-panel", "#undo-toast")
            return [r for r in (rect_of(s) for s in sels) if r]

        def shot():
            return decode(page.screenshot())

        def rows():
            """each row as (value, unit, the second line): the value first, then ΔX and ΔY"""
            return [
                tuple(r)
                for r in page.evaluate(
                    """() => [...document.querySelectorAll('#measure-list li')].map(li =>
                         ['.m-value', '.m-unit', '.m-what'].map(s => li.querySelector(s)?.textContent ?? null))"""
                )
            ]

        def wait_rows(n):
            try:
                page.wait_for_function(f"document.querySelectorAll('#measure-list li').length === {n}", timeout=10000)
            except PlaywrightTimeout:
                raise AssertionError((f"the list should have {n} rows", rows())) from None

        def toast():
            shown = page.evaluate("!document.querySelector('#undo-toast').classList.contains('hidden')")
            return page.inner_text("#undo-toast") if shown else None

        def click_dxf(q):
            page.mouse.click(*dxf_client(*q))

        def measure(m):
            n = len(rows())
            click_dxf(m[0])
            page.wait_for_function(
                "t => document.querySelector('#hud-info').textContent.includes(t)",
                arg=f"({m[0][0]}, {m[0][1]}) を選択",
                timeout=10000,
            )
            click_dxf(m[1])
            wait_rows(n + 1)
            d, dx, dy = expected(m)
            assert f"距離 {d:.3f}" in hud(), (m, hud())

        # ---- the drawing on the dark page ------------------------------------------
        page.set_input_files("#file-input", DXF)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('2D 図面')", timeout=60000)
        settle()

        def check_page(tag, img, origin=(0, 0), scale=1.0, white=False, cover=()):
            """the page colour (inside the drawing and around it) and the lines on it, in an
            image of the drawing whose (0, 0) is the client point `origin`, `scale` px per
            CSS px; points under `cover` (client rects: panels on a screenshot) are skipped"""

            def px_at(q, half):
                cx = int(round((q[0] - origin[0]) * scale))
                cy = int(round((q[1] - origin[1]) * scale))
                return img[cy - half : cy + half + 1, cx - half : cx + half + 1].reshape(-1, 3)

            page_col = (255, 255, 255) if white else PAGE
            q = dxf_client(*INTERIOR)
            assert near_colour(px_at(q, 2), page_col, 1).all(), (tag, "page inside the drawing", px_at(q, 2)[:4].tolist())
            # around the drawing: above its page rect (the letterbox of a wide drawing)
            r = rect_of("#viewport2d svg > rect")
            around = ((r[0] + r[2]) / 2, r[1] - 25)
            if around[1] >= 5 and not any(inside(around, c, 6) for c in cover):
                px = px_at(around, 2)
                assert near_colour(px, page_col, 1).all(), (tag, "page around the drawing", px[:4].tolist())
            # the lines: the pixel most unlike the page (a line about 1 px wide is spread
            # over two rows) stands out from it 3:1 or more (light on the dark page, dark on white)
            page_lum = luminance(np.array(page_col))
            for line in LINES:
                q = dxf_client(*line)
                if any(inside(q, c, 8) for c in cover):
                    continue
                lum = luminance(px_at(q, 3))
                best = lum.min() if white else lum.max()
                contrast = (max(best, page_lum) + 0.05) / (min(best, page_lum) + 0.05)
                assert contrast >= 3, (tag, "line does not show on the page", line, round(contrast, 2))

        check_page("767 fit", shot(), cover=covers())
        print("page colour and lines ok")

        # ---- a 13 px reference text, drawn by the test --------------------------------
        family = page.evaluate("getComputedStyle(document.querySelector('#viewport2d')).fontFamily")
        ref = page.evaluate(
            """family => {
                const NS = 'http://www.w3.org/2000/svg'
                const svg = document.createElementNS(NS, 'svg')
                svg.id = 'ref13'
                svg.setAttribute('width', '120')
                svg.setAttribute('height', '40')
                svg.style.cssText = 'position:fixed;left:0;top:0;z-index:5000;background:#1d2126'
                const t = document.createElementNS(NS, 'text')
                const attrs = { x: 10, y: 28, 'font-size': 13, fill: '#ffd060', 'font-family': family }
                for (const [k, v] of Object.entries(attrs)) t.setAttribute(k, String(v))
                t.textContent = '100.000'
                svg.appendChild(t)
                document.body.appendChild(svg)
                return { h: t.getBoundingClientRect().height }
            }""",
            family,
        )
        img = decode(page.screenshot(clip={"x": 0, "y": 0, "width": 120, "height": 40}))
        ys = np.nonzero(near_colour(img, DIM, 40).any(axis=1))[0]
        ref["cap"] = 28 - int(ys.min())  # the digits' height above the baseline
        page.evaluate("document.getElementById('ref13').remove()")
        print("reference 13 px text:", ref)
        assert 7 <= ref["cap"] <= 12, ref

        # ---- three measurements ---------------------------------------------------------
        set_mode("計測")
        current = []
        for m in (M1, M2, M3):
            measure(m)
            current.append(m)
        state = {"marker": None}

        def check_rows(tag):
            got = rows()
            assert len(got) == len(current), (tag, got)
            assert page.locator("#measure-list li.m2d").count() == len(current), (tag, "rows not marked 2D")
            for (value, unit, what), m in zip(got, current):
                d, dx, dy = expected(m)
                # no unit: a drawing's numbers are in its own unit
                assert (value, unit, what) == (f"{d:.3f}", None, f"ΔX {dx:.3f}　ΔY {dy:.3f}"), (tag, "row", value, unit, what, m)
                assert "↔" not in what, (tag, "a 2D row reads like a 3D one", what)

        def check_layer(tag, pending=None):
            """the layer as drawn: the values in order, markers and lines on the projected
            snap points, each value a 13 px text from the middle of its line"""
            o = page.evaluate(OVERLAY_JS)
            values = [t["value"] for t in o["texts"]]
            assert values == [f"{expected(m)[0]:.3f}" for m in current], (tag, "values", values)
            assert len(o["lines"]) == len(current), (tag, "lines", len(o["lines"]))
            points = [q for m in current for q in m] + ([pending] if pending else [])
            assert len(o["circles"]) == len(points), (tag, "markers", len(o["circles"]), len(points))
            for q in points:
                c = dxf_client(*q)
                d = min(math.hypot(k[0] - c[0], k[1] - c[1]) for k in o["circles"])
                assert d <= 1, (tag, "no marker on the snap point", q, round(d, 2))
            for k in o["circles"]:
                assert abs(k[2] - MARKER_PX) <= 1 and abs(k[3] - MARKER_PX) <= 1, (tag, "marker size", k)
                if state["marker"] is None:
                    state["marker"] = k[2]
                assert abs(k[2] - state["marker"]) <= 0.5, (tag, "marker size changed", k, state["marker"])
            for i, m in enumerate(current):
                a, b = dxf_client(*m[0]), dxf_client(*m[1])
                x1, y1, x2, y2 = o["lines"][i]
                ends = sorted([(x1, y1), (x2, y2)])
                for e, w in zip(ends, sorted([a, b])):
                    assert math.hypot(e[0] - w[0], e[1] - w[1]) <= 1, (tag, "line off its points", m, o["lines"][i], a, b)
                t = o["texts"][i]
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                left, top, right, bottom = t["rect"]
                assert abs(left - mid[0]) <= 1.5 and top <= mid[1] <= bottom, (tag, "value off its line", m, t["rect"], mid)
                assert abs(t["px"] - FONT_PX) <= 1, (tag, "value not 13 px on screen", m, round(t["px"], 2))
                assert abs((bottom - top) - ref["h"]) <= 1, (tag, "value not as tall as a 13 px text", m, bottom - top, ref["h"])
            return o

        def check_pixels(tag, img, o, origin=(0, 0), scale=1.0, cover=()):
            """the markers, and the digits of a value on a horizontal line, as drawn in `img`
            (see check_page for origin, scale and cover); returns the digits' height in CSS px"""
            h, w = img.shape[:2]
            seen = 0
            for m in current:
                a, b = dxf_client(*m[0]), dxf_client(*m[1])
                n = (-(b[1] - a[1]), b[0] - a[0])
                ln = math.hypot(*n)
                for q in (a, b):
                    # 3 px across the line from the centre: inside the 5 px marker, off the line
                    s = (q[0] + 3 * n[0] / ln, q[1] + 3 * n[1] / ln)
                    x, y = int(round((s[0] - origin[0]) * scale)), int(round((s[1] - origin[1]) * scale))
                    if not (2 <= x < w - 2 and 2 <= y < h - 2) or any(inside(s, c, 8) for c in cover):
                        continue
                    seen += 1
                    assert near_colour(img[y, x], MARKER, 40), (tag, "marker missing", m, q, img[y, x].tolist())
            assert seen >= 2, (tag, "too few markers to see", seen)
            # a value whose line runs along its baseline (a slanted line would cross the
            # digits' box): its digits as tall as the reference's
            i = next(k for k, m in enumerate(current) if m[0][1] == m[1][1])
            a, b = dxf_client(*current[i][0]), dxf_client(*current[i][1])
            base = (a[1] + b[1]) / 2
            left, top, right, bottom = o["texts"][i]["rect"]
            if any(inside((x, y), c, 4) for c in cover for x in (left, right) for y in (top, bottom)):
                return None
            x0, x1 = int(np.floor((left - origin[0]) * scale)), int(np.ceil((right - origin[0]) * scale))
            y0, y1 = int(np.floor((top - 2 - origin[1]) * scale)), int(np.ceil((bottom - origin[1]) * scale))
            box = img[max(0, y0) : y1, max(0, x0) : x1]
            ink = near_colour(box, DIM, 40)
            assert ink.sum() >= 20 * scale * scale, (tag, "value not painted", int(ink.sum()))
            cap = ((base - origin[1]) * scale - (max(0, y0) + np.nonzero(ink.any(axis=1))[0].min())) / scale
            assert abs(cap - ref["cap"]) <= 1, (tag, "digits not as tall as a 13 px text", round(cap, 2), ref["cap"])
            return cap

        check_rows("3 rows")
        print("rows:", rows())
        # the value can be selected to copy it: a double-click takes the number
        r = page.evaluate(
            """() => { const t = document.querySelector('#measure-list li .m-value').firstChild
                const i = t.data.indexOf('100.000'); const r = document.createRange()
                r.setStart(t, i); r.setEnd(t, i + 7)
                const b = r.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom] }"""
        )
        page.mouse.dblclick((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
        selected = page.evaluate("getSelection().toString()")
        assert selected == "100.000", ("the value cannot be selected", selected)
        page.evaluate("getSelection().removeAllRanges()")
        assert page.locator("#measure-list button").first.inner_text() == "×"
        # すべてコピー: a tab-separated line per row, the drawing's numbers without a unit
        # (the clipboard is caught in the page: this context has no clipboard permission)
        page.evaluate(
            "() => { window.__copied = []; navigator.clipboard.writeText = t => { window.__copied.push(t); return Promise.resolve() } }"
        )
        page.click("#measure-copy-all")
        page.wait_for_function("window.__copied.length === 1", timeout=5000)
        lines = page.evaluate("window.__copied[0]").split("\n")
        assert lines[0] == "種類\t値\t単位\t対象 A\t対象 B\tΔX\tΔY\tΔZ" and len(lines) == len(current) + 1, lines
        for line, m in zip(lines[1:], current):
            d, dx, dy = expected(m)
            # a drawing has no entity names and no ΔZ: its ΔX and ΔY in their own cells
            assert line == f"距離\t{d:.3f}\t\t\t\t{dx:.3f}\t{dy:.3f}\t", ("the copied line", line, m)
        print("list rows and copy ok")

        def check_view(tag):
            settle()
            o = check_layer(tag)
            cap = check_pixels(tag, shot(), o, cover=covers())
            print(f"{tag}: value {o['texts'][0]['px']:.2f} px, digits {cap} px")
            return o

        check_view("767 fit")
        # zoom in at the first value, out past the fit, pan
        page.mouse.move(*dxf_client(100, 50))
        for _ in range(2):
            page.mouse.wheel(0, -100)
        check_view("767 zoomed in")
        page.mouse.move(*dxf_client(100, 50))
        for _ in range(4):
            page.mouse.wheel(0, 100)
        check_view("767 zoomed out")
        start = dxf_client(100, 80)
        page.mouse.move(*start)
        page.mouse.down()
        for i in range(1, 7):
            page.mouse.move(start[0] + 12 * i, start[1] + 6 * i)
        page.mouse.up()
        assert len(rows()) == 3, "a drag made a measurement"
        check_view("767 panned")
        # a bigger window, without a fit (the layer follows the resize), then F
        page.set_viewport_size({"width": LARGE[0], "height": LARGE[1]})
        check_view("1920 resized")
        page.keyboard.press("f")
        check_view("1920 fit")
        check_page("1920 fit", shot(), cover=covers())
        page.set_viewport_size({"width": SMALL[0], "height": SMALL[1]})
        settle()
        page.keyboard.press("f")
        o = check_view("767 again")

        # ---- PNG export: the layer at the same place and size -----------------------------
        save_btn = page.locator("#toolbar button[data-action='png']")
        bg_select = ctl("画像の背景").locator("select")
        screen_img = shot()
        screen_cap = check_pixels("screen", screen_img, o, cover=covers())
        assert screen_cap is not None, "the first value is under a panel"

        def export(tag):
            with page.expect_download(timeout=15000) as info:
                save_btn.click()
            path = os.path.join(tmp, f"{tag}.png")
            info.value.save_as(path)
            shutil.copyfile(path, f"/tmp/cad_viewer_dims_{tag}.png")
            page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('画像を保存: ')")
            blur()
            return decode(Path(path).read_bytes())

        sl, st, sr, sb = rect_of("#viewport2d svg")
        origin = (sl, st)
        for label, white in (("画面のまま", False), ("白", True)):
            bg_select.select_option(label=label)
            blur()
            img = export("white" if white else "screen")
            assert img.shape[:2] == (round(sb - st), round(sr - sl)), (label, img.shape)
            check_page(f"PNG {label}", img, origin, 1.0, white=white)
            cap = check_pixels(f"PNG {label}", img, o, origin, 1.0)
            assert abs(cap - screen_cap) <= 0.5, (label, "the value's size differs from the screen", cap, screen_cap)
            # the first value (M1) at the same place as on screen: the same pixels of its colour
            left, top, right, bottom = o["texts"][0]["rect"]
            x0, x1, y0, y1 = int(left) - 2, int(right) + 3, int(top) - 2, int(bottom) + 3
            on_screen = near_colour(screen_img[y0:y1, x0:x1], DIM, 40)
            in_png = near_colour(img[y0 - int(st) : y1 - int(st), x0 - int(sl) : x1 - int(sl)], DIM, 40)
            same = np.mean(on_screen == in_png)
            assert same >= 0.95, (label, "the value is not where the screen shows it", round(same, 3))
            if white:
                halo = int(near_colour(img[y0 - int(st) : y1 - int(st), x0 - int(sl) : x1 - int(sl)], PAGE, 12).sum())
                assert halo >= 50, (label, "the value has lost its dark outline on white", halo)
            print(f"PNG {label}: value digits {cap} px, same pixels as the screen {same:.3f}")

        # devicePixelRatio 2 (a monitor at 200 %): the image is twice as large, the layer too
        cdp = context.new_cdp_session(page)

        def set_dpr(v):
            cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": SMALL[0], "height": SMALL[1], "deviceScaleFactor": v, "mobile": False},
            )
            page.wait_for_function(f"devicePixelRatio === {v}")

        set_dpr(2)
        img = export("white_dpr2")
        assert img.shape[:2] == (round((sb - st) * 2), round((sr - sl) * 2)), img.shape
        check_page("PNG 白 x2", img, origin, 2.0, white=True)
        cap = check_pixels("PNG 白 x2", img, page.evaluate(OVERLAY_JS), origin, 2.0)
        print(f"PNG 白 at devicePixelRatio 2: value digits {cap} CSS px")
        set_dpr(1)
        bg_select.select_option(label="画面のまま")
        blur()
        print("PNG export ok")

        # ---- × deletes one row; 元に戻す / Ctrl+Z puts it back in its place -----------------
        full = rows()
        page.locator("#measure-list li").nth(1).locator("button").click()
        wait_rows(2)
        current = [M1, M3]
        check_rows("× row 2")
        check_layer("× row 2")
        assert toast() and "1 件" in toast(), ("no undo offered for the ×", toast())
        page.keyboard.press("Control+z")
        wait_rows(3)
        current = [M1, M2, M3]
        assert rows() == full, ("Ctrl+Z", rows(), full)
        check_layer("× row 2 + Ctrl+Z")
        assert toast() is None, "the toast goes when the undo is used"
        assert "元に戻した" in hud(), hud()
        page.locator("#measure-list li").nth(0).locator("button").click()
        wait_rows(2)
        current = [M2, M3]
        check_layer("× row 1")
        page.locator("#undo-btn").click()
        wait_rows(3)
        current = [M1, M2, M3]
        assert rows() == full, ("元に戻す", rows(), full)
        check_view("× row 1 + 元に戻す")
        print("× + undo ok")

        # an undo keeps a first point chosen after the deletion
        page.locator("#measure-list li").nth(2).locator("button").click()
        wait_rows(2)
        click_dxf(M4[0])
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')")
        page.keyboard.press("Control+z")
        wait_rows(3)
        check_layer("undo with a first point", pending=M4[0])
        click_dxf(M4[1])
        wait_rows(4)
        current = [M1, M2, M3, M4]
        check_rows("the first point kept")
        check_layer("the first point kept")
        # a new measurement ends the undo of a ×
        page.locator("#measure-list li").nth(0).locator("button").click()
        wait_rows(3)
        assert toast(), "no undo after a ×"
        measure(M5)
        assert toast() is None, "a new measurement must end the undo"
        page.keyboard.press("Control+z")
        page.wait_for_timeout(300)
        current = [M2, M3, M4, M5]
        check_rows("Ctrl+Z after a new measurement")
        print("undo keeps the first point, a new measurement ends it ok")

        # ---- 計測クリア, then 元に戻す --------------------------------------------------
        full = rows()
        ctl("計測クリア").locator("button").click()
        wait_rows(0)
        assert page.evaluate("document.querySelector('#measure-panel').classList.contains('hidden')")
        assert page.evaluate("document.querySelectorAll('#viewport2d svg .overlay2d > *').length") == 0, "layer not cleared"
        assert toast() and "4 件" in toast(), ("no undo offered for 計測クリア", toast())
        page.locator("#undo-btn").click()
        wait_rows(4)
        assert rows() == full, ("計測クリア + 元に戻す", rows(), full)
        check_rows("計測クリア + 元に戻す")
        check_view("計測クリア + 元に戻す")
        print("計測クリア + undo ok")

        page.screenshot(path="/tmp/cad_viewer_drawing2d_dims.png")
        if errors:
            print("PAGE ERRORS:", errors)
        assert not errors
        print("DRAWING2D DIMS E2E OK")
        browser.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
