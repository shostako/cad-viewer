"""E2E: grid toggle, view presets, keyboard / mouse rotation, auto-rotate.

Checks behaviour through the camera state (window.__cadView) and screen
projections (window.__cadProject), plus pixels for the grid. Needs the same
servers as the other E2E scripts.
"""
import io
import math
import os
import re
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright
import gui_common

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
BG = (0x1D, 0x21, 0x26)  # scene background


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def close(a, b, tol=1e-3):
    return all(abs(x - y) < tol for x, y in zip(a, b))


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    def load():
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        page.set_input_files("#file-input", STEP)
        page.wait_for_function(
            "document.querySelector('#hud-info').textContent.includes('三角形')", timeout=60000
        )
        page.wait_for_timeout(500)

    def view():
        return page.evaluate("window.__cadView()")

    def offset_dir():
        v = view()
        return norm(sub(v["position"], v["target"]))

    def ctl(name):
        """controller whose label starts with `name` (exact for short labels like 上)"""
        return gui_common.ctl(page, name)

    def click_button(name):
        ctl(name).locator("button").click()
        page.wait_for_timeout(100)

    def project(xyz):
        return page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", xyz)

    def floor_ink():
        """count non-background pixels in a patch of bare floor.

        The patch is computed at run time beside the model: from the left edge
        to just left of the model's projected box, between the tree panel and
        the HUD or the axis triad (bottom left), whichever reaches higher: both
        are page DOM over the canvas, so a screenshot shows them as ink. The
        fit fills most of the canvas, so a fixed patch would
        overlap the model; and close up the floor's 50 mm grid lines are too
        far apart to cross a narrow patch, so step back first (from a fresh
        fit, so every call sees the same view).
        """
        page.keyboard.press("f")
        for _ in range(3):
            page.keyboard.press("-")
        xs = [project([x, y, z])["x"] for x in (0, 100) for y in (0, 60) for z in (0, 40)]
        tree = page.locator("#tree-panel").bounding_box()
        hud = page.locator("#hud").bounding_box()
        tri = page.locator("#triad").bounding_box()
        # 32 px clear of the panels: their shadows (8 px down, 24 px blur) reach that far
        x0, x1 = 8, int(min(xs)) - 8
        y0, y1 = int(tree["y"] + tree["height"]) + 32, int(min(hud["y"], tri["y"] if tri else hud["y"])) - 32
        assert x1 - x0 >= 60 and y1 - y0 >= 200, ("floor patch too small", x0, x1, y0, y1)
        png = page.screenshot()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        box = img.crop((x0, y0, x1, y1))
        return sum(1 for px in box.getdata() if max(abs(a - b) for a, b in zip(px, BG)) > 6)

    page.goto(BASE_URL)
    page.evaluate("localStorage.removeItem('cad-viewer:view')")
    load()

    # ---- 1. grid toggle (rendered pixels, persisted across reload) ------------
    assert view()["gridVisible"] is True
    ink_on = floor_ink()
    ctl("グリッド").locator("input").click()
    page.wait_for_timeout(200)
    ink_off = floor_ink()
    print("grid ink on/off:", ink_on, ink_off)
    assert view()["gridVisible"] is False
    assert ink_on > 50 and ink_off < ink_on // 10, (ink_on, ink_off)
    load()  # reload: the choice is remembered
    assert view()["gridVisible"] is False, "grid preference must survive a reload"
    assert floor_ink() < ink_on // 10, "after a reload the grid must not be drawn"
    ctl("グリッド").locator("input").click()
    assert view()["gridVisible"] is True

    # ---- 2. view presets: direction, and what is right / up on screen ---------
    def screen_dirs():
        v = view()
        t = v["target"]
        o = project(t)
        ex = project([t[0] + 10, t[1], t[2]])
        ey = project([t[0], t[1] + 10, t[2]])
        ez = project([t[0], t[1], t[2] + 10])
        # screen y grows downward; return (dx, -dy) so "up" is positive
        return {k: (e["x"] - o["x"], o["y"] - e["y"]) for k, e in (("x", ex), ("y", ey), ("z", ez))}

    for preset, d in [("正面", [0, -1, 0]), ("右", [1, 0, 0]), ("背面", [0, 1, 0]), ("左", [-1, 0, 0])]:
        click_button(preset)
        assert close(offset_dir(), d), (preset, offset_dir())
        s = screen_dirs()
        assert s["z"][1] > 5 and abs(s["z"][0]) < 1, (preset, s)  # Z points up on screen
    click_button("正面")
    s = screen_dirs()
    assert s["x"][0] > 5, s  # front: +X to the right

    click_button("上")
    assert dot(offset_dir(), [0, 0, 1]) > 0.999, offset_dir()
    s = screen_dirs()
    assert s["x"][0] > 5 and s["y"][1] > 5, ("top: +X right, +Y up", s)
    click_button("下")
    assert dot(offset_dir(), [0, 0, -1]) > 0.999, offset_dir()
    s = screen_dirs()
    assert s["x"][0] > 5 and s["y"][1] < -5, ("bottom: +X right, +Y down", s)
    click_button("等角")
    assert close(offset_dir(), norm([1, -1, 1])), offset_dir()

    # ---- 3. keyboard (turntable) ----------------------------------------------
    page.mouse.click(640, 400)  # focus the page (mode なし: a click picks nothing)
    click_button("正面")
    # focus stays on the GUI button just clicked — arrows must still work
    page.keyboard.press("ArrowRight")
    d = offset_dir()
    assert d[0] > 0.05 and abs(math.degrees(math.atan2(d[0], -d[1])) - 5) < 0.5, d  # camera moved right 5 deg
    page.keyboard.press("ArrowLeft")
    assert close(offset_dir(), [0, -1, 0]), offset_dir()
    page.keyboard.press("ArrowUp")
    assert offset_dir()[2] > 0.05, offset_dir()  # camera moved up
    for _ in range(40):  # 200 deg: the turntable stops at the top instead of rolling over
        page.keyboard.press("ArrowUp")
    v = view()
    d = offset_dir()
    assert d[2] > 0.99 and d[1] < 0, ("stays on the front side at the pole", d)
    assert close(v["up"], [0, 0, 1]), v["up"]

    click_button("正面")
    dist0 = math.dist(view()["position"], view()["target"])
    page.keyboard.press("+")
    assert math.dist(view()["position"], view()["target"]) < dist0 * 0.95
    page.keyboard.press("-")
    assert abs(math.dist(view()["position"], view()["target"]) - dist0) < dist0 * 1e-3
    t0 = view()["target"]
    page.keyboard.press("Shift+ArrowRight")
    t1 = view()["target"]
    assert t1[0] > t0[0] and abs(t1[2] - t0[2]) < 1e-6, (t0, t1)  # front view: slide along +X
    assert close(offset_dir(), [0, -1, 0]), "Shift+arrow slides, it does not turn"

    # arrows must not move the view while typing in a text box
    page.evaluate("""() => { const i = document.createElement('input'); i.type = 'text';
        i.id = 'tmp-text'; document.body.appendChild(i); i.focus() }""")
    before = view()["position"]
    page.keyboard.press("ArrowRight")
    assert close(view()["position"], before), "arrow in a text box moved the view"
    page.evaluate("document.getElementById('tmp-text').remove()")

    # ---- 4. free rotation: tumble over the top --------------------------------
    ctl("回転方式").locator("select").select_option(label="自由回転")
    assert view()["rotateMode"] == "free"
    click_button("正面")
    # focus stays on the GUI button just clicked — arrows must still work
    for _ in range(36):  # 180 deg up: over the top to the back, upside down
        page.keyboard.press("ArrowUp")
    v = view()
    assert close(offset_dir(), [0, 1, 0], 1e-2), offset_dir()
    assert close(v["up"], [0, 0, -1], 1e-2), v["up"]

    # mouse drag also tumbles freely
    click_button("正面")
    page.mouse.move(640, 650)
    page.mouse.down()
    for i in range(1, 21):
        page.mouse.move(640, 650 - i * 25)
        page.wait_for_timeout(16)
    page.mouse.up()
    page.wait_for_timeout(800)  # let the coast settle
    v = view()
    print("after free drag: dir", [round(x, 3) for x in offset_dir()], "up", [round(x, 3) for x in v["up"]])
    assert v["up"][2] < 0.5, ("a long vertical drag must tumble past the top", v["up"])

    # back to turntable: Z is up again
    ctl("回転方式").locator("select").select_option(label="ターンテーブル")
    v = view()
    assert v["rotateMode"] == "turntable" and close(v["up"], [0, 0, 1]), v

    # turntable drag turns the view (and keeps Z up)
    click_button("正面")
    page.mouse.move(500, 400)
    page.mouse.down()
    page.mouse.move(700, 400, steps=10)
    page.mouse.up()
    page.wait_for_timeout(800)
    d = offset_dir()
    assert abs(d[0]) > 0.1, ("horizontal drag must orbit", d)
    assert close(view()["up"], [0, 0, 1])

    # ---- 5. auto-rotate, paused while the mouse is held ------------------------
    click_button("正面")
    ctl("自動回転").locator("input").click()
    page.wait_for_timeout(1000)
    d = offset_dir()
    turned = math.degrees(math.atan2(d[0], -d[1]))
    print("auto-rotate turned in ~1 s:", round(turned, 1), "deg")
    assert 10 < abs(turned) < 80, turned
    page.mouse.move(640, 760)
    page.mouse.down()
    page.wait_for_timeout(200)
    a = offset_dir()
    page.wait_for_timeout(600)
    b = offset_dir()
    page.mouse.up()
    assert close(a, b, 1e-3), ("auto-rotate must pause while the mouse is held", a, b)
    page.wait_for_timeout(400)
    assert not close(b, offset_dir(), 1e-3), "auto-rotate must resume after release"
    ctl("自動回転").locator("input").click()
    page.wait_for_timeout(300)
    a = offset_dir()
    page.wait_for_timeout(500)
    assert close(a, offset_dir(), 1e-3), "auto-rotate off must stop the spin"

    # ---- 5b. auto-rotate survives a button held while the window loses focus --
    ctl("自動回転").locator("input").click()
    page.mouse.move(640, 760)
    page.mouse.down()
    page.wait_for_timeout(200)
    page.evaluate("window.dispatchEvent(new Event('blur'))")  # e.g. Alt+Tab mid-drag
    a = offset_dir()
    page.wait_for_timeout(500)
    assert not close(a, offset_dir(), 1e-3), "a blur must release the held pointer"
    page.mouse.up()
    ctl("自動回転").locator("input").click()

    # ---- 5c. a preset clicked during a drag's coast stays put -----------------
    for mode in ("ターンテーブル", "自由回転"):
        ctl("回転方式").locator("select").select_option(label=mode)
        click_button("等角")
        page.mouse.move(400, 600)
        page.mouse.down()
        page.mouse.move(900, 300, steps=4)  # fast flick: leaves a long coast
        page.mouse.up()
        click_button("正面")
        page.wait_for_timeout(600)
        assert close(offset_dir(), [0, -1, 0], 1e-3), (mode, "preset drifted with the coast", offset_dir())
    ctl("回転方式").locator("select").select_option(label="ターンテーブル")

    page.screenshot(path="/tmp/cad_viewer_view_controls.png")

    # ---- 6. a touch cancelled by the OS must not leave auto-rotate paused -----
    # (TrackballControls ends a cancelled pointer without its 'end' event)
    tctx = browser.new_context(viewport={"width": 1280, "height": 800}, has_touch=True)
    tpage = tctx.new_page()
    tpage.on("pageerror", lambda e: errors.append(str(e)))
    tpage.goto(BASE_URL)
    tpage.wait_for_load_state("networkidle")
    tpage.set_input_files("#file-input", STEP)
    tpage.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('三角形')", timeout=60000
    )
    page = tpage  # helpers above read the module-level `page`
    ctl("回転方式").locator("select").select_option(label="自由回転")
    ctl("自動回転").locator("input").click()
    cdp = tctx.new_cdp_session(tpage)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 640, "y": 700}]})
    tpage.wait_for_timeout(300)
    a = offset_dir()
    tpage.wait_for_timeout(300)
    assert close(a, offset_dir(), 1e-3), "a held touch must pause auto-rotate"
    cdp.send("Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []})
    tpage.wait_for_timeout(300)
    b = offset_dir()
    tpage.wait_for_timeout(500)
    assert not close(b, offset_dir(), 1e-3), "auto-rotate must resume after a cancelled touch"
    tpage.evaluate("localStorage.removeItem('cad-viewer:view')")
    tctx.close()
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("VIEW CONTROLS E2E OK")
    browser.close()
