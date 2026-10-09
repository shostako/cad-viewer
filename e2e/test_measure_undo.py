"""E2E: measurements and notes are hard to lose (issue #23 item 1).

- 計測クリア and × can be undone for a few seconds: the toast's 元に戻す or
  Ctrl+Z puts the list back as it was (same entries, same order), and the
  autosave then writes the restored list again
- the undo lapses: after the toast's time, after another change to the list,
  and on a model switch
- Esc in 計測 drops a chosen first point (3D and 2D); a second Esc leaves the mode
- on a drawing, 計測クリア can be undone too (its measurements are the drawing's own)
- a note being typed is kept when the user clicks elsewhere; only Esc discards it;
  opening another file saves it to its own model first

Oracles: the entries' texts read from the list before a deletion, the sidecar
PUT bodies the page sends (caught by a route, nothing reaches the shared
backend), the HUD texts, the mode select's value, and the 2D overlay's circles.
Model points come from testdata/make_step_assembly.py (mini_mold.step: plate
100x60x15, pins r4 at x 25/75, y 30, z 15..40, cavity block 30..70 x 15..45 x 15..35).
"""
import json
import math
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
STL = str(TESTDATA / "ribbed_plate.stl")
DXF = str(TESTDATA / "plate_drawing.dxf")
CAV_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)
PLATE_TOP2 = (10, 8, 15)
UNDO_S = 8  # the toast's time (main.ts UNDO_MS)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    puts = []  # sidecar bodies the app saves, newest last

    def sidecar(route):
        if route.request.method == "GET":
            route.fulfill(json={"version": 1, "entries": []})
        else:
            puts.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(json={"saved": True})

    page.route("**/sidecar", sidecar)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    def ctl(name):
        label = page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
        return page.locator(".lil-gui .lil-controller").filter(has=label).first

    def set_mode(label):
        ctl("モード").locator("select").select_option(label)
        page.evaluate("document.activeElement && document.activeElement.blur()")

    def mode():
        return ctl("モード").locator("select").input_value()

    def load(path, wait_text="tris"):
        page.set_input_files("#file-input", path)
        page.wait_for_function(
            "([w, n]) => { const t = document.querySelector('#hud-info').textContent;"
            " return t.includes(w) && t.includes(n) }",
            arg=[wait_text, Path(path).name],
            timeout=60000,
        )
        page.wait_for_timeout(300)

    def hud():
        return page.text_content("#hud-info")

    def texts():
        return [t.replace("×", "").strip() for t in page.locator("#measure-list li").all_inner_texts()]

    def count():
        return page.locator("#measure-list li").count()

    def wait_count(n):
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length === {n}", timeout=10000)

    def toast_shown():
        return page.evaluate("!document.querySelector('#undo-toast').classList.contains('hidden')")

    def click_world(xyz):
        pt = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
        page.mouse.click(pt["x"], pt["y"])

    def measure(a, b):
        n = count()
        click_world(a)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
        click_world(b)
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length > {n}", timeout=10000)

    def pin_side():
        """a point on pin2's side that picks its cylindrical face (not a seam edge)"""
        for deg in range(-30, -151, -10):
            a = math.radians(deg)
            q = (75 + 4 * math.cos(a), 30 + 4 * math.sin(a), 28)
            xy = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(q))
            hit = page.evaluate("([x, y]) => window.__cadPick(x, y)", [xy["x"], xy["y"]])
            if hit and hit["kind"] == "face":
                return q
        raise AssertionError("no face pick on pin2's side")

    def last_put_entries():
        return len(puts[-1].get("entries", [])) if puts else None

    def wait_put(n):
        """the autosave (800 ms after a change) writes a list of n entries"""
        for _ in range(40):
            page.wait_for_timeout(100)
            if last_put_entries() == n:
                return
        raise AssertionError(("autosave", n, [len(b.get("entries", [])) for b in puts[-3:]]))

    load(STEP)
    set_mode("計測")
    measure(CAV_TOP, PLATE_TOP)
    side = pin_side()
    n = count()
    click_world(side)  # the cylinder: its ⌀ entry comes first, then the distance
    page.wait_for_function(f"document.querySelectorAll('#measure-list li').length > {n}", timeout=10000)
    click_world(PLATE_TOP2)
    wait_count(n + 2)
    full = texts()
    print("entries:", full)
    assert len(full) == 3 and any("⌀8.000" in t for t in full), full
    wait_put(3)

    # ---- 1. 計測クリア, then 元に戻す
    ctl("計測クリア").locator("button").click()
    wait_count(0)
    assert toast_shown(), "the undo toast must show"
    assert "3 件" in page.inner_text("#undo-toast"), page.inner_text("#undo-toast")
    # the toast sits clear of the right-hand column and above the HUD
    t = page.locator("#undo-toast").bounding_box()
    h = page.locator("#hud").bounding_box()
    g = page.locator(".lil-gui.lil-root").bounding_box()
    assert t["y"] + t["height"] <= h["y"] + 0.5, ("toast over the HUD", t, h)
    assert t["x"] + t["width"] <= g["x"] - 0.5, ("toast under the GUI", t, g)
    wait_put(0)  # the cleared list is saved too: the undo must write it back
    page.locator("#undo-btn").click()
    wait_count(3)
    assert texts() == full, ("1 restored list", texts(), full)
    assert not toast_shown(), "the toast goes when the undo is used"
    assert "元に戻した" in hud(), hud()
    wait_put(3)
    print("1 clear + undo ok")

    # ---- 2. × on the middle entry, then Ctrl+Z: same order
    page.locator("#measure-list li").nth(1).locator("button").click()
    wait_count(2)
    assert toast_shown() and "1 件" in page.inner_text("#undo-toast")
    page.keyboard.press("Control+z")
    wait_count(3)
    assert texts() == full, ("2 order after Ctrl+Z", texts(), full)
    print("2 delete + Ctrl+Z ok")

    # ---- 3. the undo lapses after the toast's time
    page.locator("#measure-list li").nth(0).locator("button").click()
    wait_count(2)
    page.wait_for_timeout(UNDO_S * 1000 + 600)
    assert not toast_shown(), "the toast must go after its time"
    page.keyboard.press("Control+z")
    page.wait_for_timeout(300)
    assert count() == 2, "3 Ctrl+Z after the undo lapsed restored something"
    print("3 lapse ok")

    # ---- 4. another change to the list ends the undo
    page.locator("#measure-list li").nth(0).locator("button").click()
    wait_count(1)
    assert toast_shown()
    measure(CAV_TOP, PLATE_TOP)
    wait_count(2)
    assert not toast_shown(), "a new measurement must end the undo"
    page.keyboard.press("Control+z")
    page.wait_for_timeout(300)
    assert count() == 2, "4 Ctrl+Z after another change"
    print("4 a new change ends the undo ok")

    # ---- 5. Esc drops the first point, a second Esc leaves the mode
    n = count()
    click_world(CAV_TOP)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    page.keyboard.press("Escape")
    assert "1 点目を取り消した" in hud(), hud()
    assert mode() == "計測"
    click_world(PLATE_TOP)  # a new first point, not the partner of the dropped one
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    page.wait_for_timeout(500)
    assert count() == n, ("5 a distance was made from the dropped point", texts())
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    assert mode() == "なし", mode()
    print("5 Esc ok")

    # ---- 6. a note: a click elsewhere keeps it, Esc throws it away
    set_mode("注記")
    n = count()
    click_world(PLATE_TOP)
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("クリックで確定")
    page.mouse.click(30, 400)  # empty canvas, left of the model
    wait_count(n + 1)
    assert any("クリックで確定" in t for t in texts()), texts()
    click_world(PLATE_TOP2)
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("すてる")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.locator(".note-input").count() == 0 and count() == n + 1, texts()
    assert not any("すてる" in t for t in texts())
    set_mode("なし")
    print("6 notes ok")

    # ---- 6c. while a note is being typed, one click on × deletes and one click
    # on 元に戻す undoes (the note's commit must not eat the click); the note
    # stays open and is still committed with Enter
    set_mode("注記")
    n = count()
    click_world(PLATE_TOP2)
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("途中")
    page.locator("#measure-list li").nth(0).locator("button").click()
    wait_count(n - 1)
    assert toast_shown()
    assert page.locator(".note-input").count() == 1 and page.locator(".note-input").input_value() == "途中"
    page.locator("#undo-btn").click()
    wait_count(n)
    assert page.locator(".note-input").count() == 1, "6c the undo click closed the note"
    page.locator(".note-input").press("Enter")
    wait_count(n + 1)
    assert any("途中" in t for t in texts()), texts()
    set_mode("なし")
    print("6c one click while typing ok")

    # ---- 6d. an undo keeps a first point chosen after the deletion
    set_mode("計測")
    n = count()
    page.locator("#measure-list li").nth(0).locator("button").click()
    wait_count(n - 1)
    click_world(CAV_TOP)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    page.keyboard.press("Control+z")
    wait_count(n)
    click_world(PLATE_TOP)  # the partner of the first point chosen before the undo
    wait_count(n + 1)
    assert texts()[-1].endswith("20.000"), ("6d the first point was dropped by the undo", texts())
    set_mode("なし")
    print("6d undo keeps the first point ok")

    # ---- 6b. a note still being typed when another file is opened goes to its
    # own model (saved before the switch), not to the new one
    set_mode("注記")
    click_world(PLATE_TOP)
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("読み込み前の注記")
    saved_before = len(puts)
    load(STL)  # set_input_files: the note input keeps the focus until the load
    assert any("読み込み前の注記" in json.dumps(b, ensure_ascii=False) for b in puts[saved_before:]), \
        ("6b the note being typed was not saved to its model", puts[saved_before:])
    assert page.locator(".note-input").count() == 0 and count() == 0, texts()
    set_mode("なし")
    print("6b note before a load ok")

    # ---- 6e. a note opened while the next file is uploading still goes to the
    # model it was clicked on (saved before the switch)
    load(STEP)
    held = []
    page.route("**/api/models", lambda r: held.append(r) if r.request.method == "POST" else r.continue_())
    page.set_input_files("#file-input", STL)
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "6e the upload was not seen"
    set_mode("注記")
    click_world(PLATE_TOP)
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("アップロード中の注記")
    saved_before = len(puts)
    page.unroute("**/api/models")
    held[0].continue_()
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')"
        " && document.querySelector('#hud-info').textContent.includes('ribbed_plate.stl')",
        timeout=60000,
    )
    assert any("アップロード中の注記" in json.dumps(b, ensure_ascii=False) for b in puts[saved_before:]), \
        ("6e the note opened during the upload was lost", puts[saved_before:])
    assert count() == 0, ("6e the note went to the new model", texts())
    set_mode("なし")
    print("6e note during an upload ok")

    # ---- 7. a model switch ends the undo
    load(STEP)
    set_mode("計測")
    measure(CAV_TOP, PLATE_TOP)
    set_mode("なし")
    page.locator("#measure-list li").nth(0).locator("button").click()
    wait_count(0)
    assert toast_shown()
    load(STL)
    assert not toast_shown(), "a model switch must end the undo"
    page.keyboard.press("Control+z")
    page.wait_for_timeout(300)
    assert count() == 0, ("7 entries of the old model came back", texts())
    print("7 model switch ok")

    # ---- 8. 2D: Esc drops the first snap point
    load(DXF, wait_text="2D図面")
    set_mode("計測")

    def svg_click(dxf_x, dxf_y):
        pos = page.evaluate(
            """([x, y]) => {
                const svg = document.querySelector('#viewport2d svg')
                const vb = svg.viewBox.baseVal
                const sx = (vb.width + 2 * vb.x) / 200, sy = (vb.height + 2 * vb.y) / 100
                const pt = new DOMPoint(x * sx, (100 - y) * sy).matrixTransform(svg.getScreenCTM())
                return { x: pt.x, y: pt.y }
            }""",
            [dxf_x, dxf_y],
        )
        page.mouse.click(pos["x"], pos["y"])
        page.wait_for_timeout(300)

    def circles():
        return page.evaluate("document.querySelectorAll('#viewport2d svg .overlay2d circle').length")

    svg_click(50, 50)
    assert "(50, 50)" in hud() and circles() == 1, (hud(), circles())
    page.keyboard.press("Escape")
    assert "1 点目を取り消した" in hud() and circles() == 0, (hud(), circles())
    svg_click(150, 50)
    assert "(150, 50)" in hud() and "距離" not in hud(), hud()
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    assert mode() == "なし"
    print("8 2D Esc ok")

    # ---- 9. 2D: 計測クリア can be undone too (the drawing's own measurements)
    def dims():
        return page.evaluate(
            "[...document.querySelectorAll('#viewport2d svg .overlay2d text.dimtext2d')].map(t => t.textContent)"
        )

    set_mode("計測")
    svg_click(50, 50)
    svg_click(150, 50)
    assert "100.000" in hud() and dims() == ["100.000"] and circles() == 2, (hud(), dims(), circles())
    ctl("計測クリア").locator("button").click()
    assert dims() == [] and circles() == 0
    assert toast_shown() and "1 件" in page.inner_text("#undo-toast"), page.inner_text("#undo-toast")
    page.keyboard.press("Control+z")
    page.wait_for_timeout(200)
    assert dims() == ["100.000"] and circles() == 2, ("9 2D undo", dims(), circles())
    assert not toast_shown()
    # a new 2D measurement ends the undo
    ctl("計測クリア").locator("button").click()
    assert toast_shown()
    svg_click(50, 50)
    svg_click(150, 50)
    assert not toast_shown(), "9 a new 2D measurement must end the undo"
    page.keyboard.press("Control+z")
    page.wait_for_timeout(200)
    assert dims() == ["100.000"], ("9 Ctrl+Z after a new 2D measurement", dims())
    set_mode("なし")
    print("9 2D clear + undo ok")

    page.screenshot(path="/tmp/cad_viewer_measure_undo.png")
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("MEASURE UNDO E2E OK")
    browser.close()
