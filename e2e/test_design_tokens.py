"""E2E: one look for the whole app (issue #23 item 5).

The panels used to come in two looks (the grey lil-gui and the navy panels of
the app's own), three widths in the right-hand column and four heading styles.
The rules checked here are the specification, written out in this file (not
read from the stylesheet):

- the right-hand column (the operation panel, the measure list, the volume
  panel) is one width, 264 px, with one right edge 12 px from the window's
- every panel has the same surface colour, border colour and corner radius,
  and the operation panel (lil-gui) has them too
- one heading style: 12 px, bold, the secondary grey, no letter spacing, no
  capitals
- the keyboard focus shows a 2 px ring in the one interactive colour on the
  app's own buttons
- the 3D background stays #1d2126 (other checks use it as a spec colour)

Oracles: computed styles and DOM rects, and a canvas pixel.
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")

COLUMN = 264
EDGE = 12
SURFACE = "rgba(21, 25, 31, 0.94)"
SURFACE_SOLID = "rgb(21, 25, 31)"
BORDER = "rgb(48, 56, 69)"
RADIUS = "10px"
HEADING = {"fontSize": "12px", "fontWeight": "600", "color": "rgb(170, 180, 193)", "letterSpacing": "normal", "textTransform": "none"}
ACCENT = "rgb(76, 154, 255)"
ON_ACCENT = "rgb(11, 18, 32)"
SCENE = (0x1D, 0x21, 0x26)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    # sidecars stay in the page: a restored list would not change these rules,
    # but nothing reaches the shared backend's files
    page.route(
        "**/sidecar",
        lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {}),
    )
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    def style(sel, props):
        return page.evaluate(
            "([s, ps]) => { const c = getComputedStyle(document.querySelector(s)); return Object.fromEntries(ps.map(p => [p, c[p]])) }",
            [sel, props],
        )

    def rect(sel):
        return page.evaluate(
            "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] }",
            sel,
        )

    # ---- the empty screen: the operation panel and the open card share the surface
    gui = ".lil-gui.lil-root"
    for sel in (gui, "#empty-hint", "#hud"):
        st = style(sel, ["borderTopColor", "borderTopLeftRadius"])
        assert st == {"borderTopColor": BORDER, "borderTopLeftRadius": RADIUS}, (sel, st)
    assert style("#hud", ["backgroundColor"])["backgroundColor"] == SURFACE
    assert style("#empty-hint", ["backgroundColor"])["backgroundColor"] == SURFACE
    # lil-gui paints its own body (opaque: its rows scroll under the title)
    assert style(gui, ["backgroundColor"])["backgroundColor"] == SURFACE_SOLID, style(gui, ["backgroundColor"])
    g = rect(gui)
    assert abs((g[2] - g[0]) - COLUMN) <= 0.5 and abs(1280 - g[2] - EDGE) <= 0.5 and abs(g[1] - EDGE) <= 0.5, ("GUI", g)
    # the main button is the one interactive colour, its text dark on it
    st = style("#empty-open", ["backgroundColor", "color"])
    assert st == {"backgroundColor": ACCENT, "color": ON_ACCENT}, st
    # and the keyboard focus shows the ring there too
    page.locator("#empty-open").focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    st = page.evaluate(
        "(() => { const e = document.activeElement; const c = getComputedStyle(e);"
        " return [e.id, c.outlineStyle, c.outlineWidth, c.outlineColor] })()"
    )
    assert st == ["empty-open", "solid", "2px", ACCENT], ("focus ring on the main button", st)
    print("empty screen ok", g)

    # ---- a model with six measurements: the right-hand column is one width
    page.set_input_files("#file-input", STEP)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000)
    page.wait_for_function("!document.querySelector('#props-panel').classList.contains('hidden')", timeout=30000)
    label = page.locator(".lil-name", has_text="モード")
    page.locator(".lil-gui .lil-controller").filter(has=label).first.locator("select").select_option("計測")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    pts = [(50, 30, 35), (90, 10, 15), (60, 20, 35), (10, 50, 15)]
    for a, b in ((0, 1), (2, 3)):
        for q in (pts[a], pts[b]):
            xy = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(q))
            page.mouse.click(xy["x"], xy["y"])
            page.wait_for_timeout(300)
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 2", timeout=10000)
    page.wait_for_timeout(300)
    cols = {sel: rect(sel) for sel in (gui, "#measure-panel", "#props-panel")}
    print("column", cols)
    for sel, r in cols.items():
        assert abs((r[2] - r[0]) - COLUMN) <= 0.5, ("one width", sel, r)
        assert abs(1280 - r[2] - EDGE) <= 0.5, ("one right edge", sel, r)
    for sel in ("#tree-panel", "#measure-panel", "#props-panel", "#hud"):
        st = style(sel, ["backgroundColor", "borderTopColor", "borderTopLeftRadius"])
        assert st == {"backgroundColor": SURFACE, "borderTopColor": BORDER, "borderTopLeftRadius": RADIUS}, (sel, st)
    # one heading style
    for sel in ("#tree-title", "#measure-title", "#props-head"):
        st = style(sel, list(HEADING))
        assert st == HEADING, (sel, st)
    # the font of the tokens, first in every panel's list (the OS falls back as needed)
    for sel in ("#hud", "#tree-panel", gui):
        fam = style(sel, ["fontFamily"])["fontFamily"]
        assert fam.startswith('"Yu Gothic UI"'), (sel, fam)

    # ---- the keyboard focus: a 2 px ring in the interactive colour
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    page.evaluate("document.querySelector('#measure-list li button').focus({ focusVisible: true })")
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    st = page.evaluate(
        "(() => { const e = document.activeElement; const c = getComputedStyle(e);"
        " return [e.closest('#measure-list') !== null, c.outlineStyle, c.outlineWidth, c.outlineColor] })()"
    )
    print("focus", st)
    assert st == [True, "solid", "2px", ACCENT], st
    # パネルを出す (the panels hidden with H): the same ring
    page.keyboard.press("h")
    page.wait_for_function("!document.querySelector('#panels-show').classList.contains('hidden')", timeout=5000)
    page.locator("#panels-show").focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    st = page.evaluate(
        "(() => { const e = document.activeElement; const c = getComputedStyle(e);"
        " return [e.id, c.outlineStyle, c.outlineWidth, c.outlineColor] })()"
    )
    assert st == ["panels-show", "solid", "2px", ACCENT], ("focus ring on パネルを出す", st)
    page.locator("#panels-show").click()

    # ---- the 3D background is untouched
    url = page.evaluate(
        "new Promise(r => requestAnimationFrame(() => r(document.querySelector('#viewport canvas').toDataURL())))"
    )
    import base64
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    corner = img.getpixel((img.width // 2, 4))
    assert all(abs(a - b) <= 2 for a, b in zip(corner, SCENE)), ("the 3D background", corner)

    page.screenshot(path="/tmp/cad_viewer_design_tokens.png")
    errors = [e for e in errors if "Failed to load resource" not in e]
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("DESIGN TOKENS E2E OK")
    browser.close()
