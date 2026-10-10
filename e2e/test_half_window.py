"""E2E: the layout for half a screen (issue #23 item 7), at 767 x 639.

- The status card (bottom left) is the status line and a ? at its end: no
  title, no lines of key help.
- The key list: the ? button and the ? key open it; ? again, Esc and its ×
  close it. It sits above the status line and the axis triad, from the
  window's left edge to the right-hand column. Not modal: the arrow keys still
  turn the view while it is open. A list for 3D and one for a drawing. A ?
  typed into a note is a character. Esc closes the list before it touches a
  measurement. Its foot shows package.json's version.
- 視点: the seven buttons in rows of four (two rows), which still set the view;
  a closed 視点 shows none of them.
- 回転速度 only while 自動回転 is on.
- 体積・重量: the total first, the parts table folded under 部品ごとの値（N 部品）;
  opened or folded, it stays so across a reload.
- The folders: all folded on the empty screen; with a model, each the way the
  user left it (by default 表示 and 視点 open, the rest closed), across a reload.
- The panels cover less of the window: 50.3 % right after loading mini_mold
  before this change (the union of the panels' rectangles, measured with this
  script's own count), under 47 % now (44.7 % measured). The right-hand column
  still runs from top to bottom while 表示 is open (its default).

Oracles: DOM rectangles, classes and attributes, the camera (__cadView), the
version in frontend/package.json, the parts of mini_mold (make_step_assembly.py).
Sidecars stay in the page (page.route): nothing reaches the shared backend.
"""
import json
import math
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

import gui_common

ROOT = Path(__file__).resolve().parents[1]
TESTDATA = ROOT / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
DXF = str(TESTDATA / "plate_drawing.dxf")
VERSION = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]
W, H = 767, 639
EDGE, GAP = 12, 8
TOP_FOLDERS = ("表示", "断面", "肉厚", "抜き勾配", "体積・重量")
VIEWS = (("正面", "背面", "右", "左"), ("上", "下", "等角"))
PARTS = ["cavity_block", "core_pin", "core_pin", "plate"]
COVER_BEFORE = 0.503

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": W, "height": H})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.route(
        "**/sidecar",
        lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {}),
    )

    def goto():
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

    def load(path, done="三角形"):
        page.set_input_files("#file-input", path)
        page.wait_for_function(
            "([d, n]) => { const t = document.querySelector('#hud-info').textContent; return t.includes(d) && t.includes(n) }",
            arg=[done, Path(path).name],
            timeout=60000,
        )

    def load_model():
        load(STEP)
        page.wait_for_function(
            "!document.querySelector('#props-panel').classList.contains('hidden')"
            " && !document.querySelector('#props-total').classList.contains('hidden')",
            timeout=30000,
        )
        page.wait_for_timeout(500)  # the column settles (ResizeObserver, next frame)

    # drawn: it has boxes (offsetParent would be null for the fixed GUI too)
    def shown(sel):
        return page.evaluate("s => { const e = document.querySelector(s); return !!e && e.getClientRects().length > 0 }", sel)

    def rect(sel):
        """left, top, right, bottom; None while it is not drawn"""
        return page.evaluate(
            "s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;"
            " const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] }",
            sel,
        )

    def folder_closed(name):
        return "lil-closed" in gui_common.folder_title(page, name).locator("xpath=..").get_attribute("class")

    def folders():
        return {f: not folder_closed(f) for f in TOP_FOLDERS + ("視点",)}

    def column_left():
        lefts = [r[0] for r in (rect(".lil-gui.lil-root"), rect("#corner-br")) if r and r[2] > r[0]]
        return min(lefts) if lefts else W - EDGE

    def help_shown():
        return shown("#help-card")

    def check_help_place(tag):
        """above the status line and the triad, from the left edge to the column"""
        c = rect("#help-card")
        above = min(r[1] for r in (rect("#hud"), rect("#triad")) if r)
        assert abs(c[0] - EDGE) <= 0.5, (tag, "left edge", c)
        assert c[3] <= above - GAP + 0.5, (tag, "above the status line and the triad", c, above)
        assert c[2] <= column_left() - GAP + 0.5, (tag, "left of the right-hand column", c, column_left())
        assert c[1] >= EDGE - 0.5, (tag, "inside the window", c)

    def view():
        return page.evaluate("window.__cadView()")

    def settled_view():
        """the camera once its damping has come to rest"""
        prev = view()
        for _ in range(30):
            page.wait_for_timeout(100)
            cur = view()
            if cur["position"] == prev["position"]:
                return cur
            prev = cur
        return prev

    def turned(a, b):
        """degrees between the two views' directions from their targets"""
        da = [x - t for x, t in zip(a["position"], a["target"])]
        db = [x - t for x, t in zip(b["position"], b["target"])]
        dot = sum(x * y for x, y in zip(da, db))
        na, nb = (sum(x * x for x in d) ** 0.5 for d in (da, db))
        return math.degrees(math.acos(max(-1.0, min(1.0, dot / (na * nb)))))

    goto()

    # ---- 1. the empty screen: every folder folded, nothing scrolls, one status line
    assert folders() == {f: False for f in TOP_FOLDERS} | {"視点": True}, folders()
    scroll = page.evaluate(
        "(() => { const c = document.querySelector('.lil-gui.lil-root > .lil-children'); return [c.scrollHeight, c.clientHeight] })()"
    )
    assert scroll[0] <= scroll[1] + 1, ("1 the operation panel scrolls on the empty screen", scroll)
    hud_text = page.inner_text("#hud")
    assert "ドラッグ" not in hud_text and "cad-viewer" not in hud_text.lower(), ("1 the status card carries more than its line", hud_text)
    info = rect("#hud-info")
    assert info[3] - info[1] < 30, ("1 one status line", info)
    b, hud = rect("#help-open"), rect("#hud")
    assert hud[0] <= b[0] and b[2] <= hud[2] and hud[1] <= b[1] and b[3] <= hud[3], ("1 the ? in the status card", b, hud)
    print("1 empty", folders(), "status", [round(x) for x in hud])

    # ---- 2. the key list: the button, ?, Esc, ×
    page.click("#help-open")
    assert help_shown() and page.get_attribute("#help-open", "aria-expanded") == "true"
    check_help_place("2 empty")
    keys = page.inner_text("#help-keys")
    assert "回転" in keys and "ダブルクリック" in keys and "Esc" in keys, keys
    # the wheel zooms toward the cursor, + and − toward the rotation centre (Codex on #37)
    rows = page.evaluate(
        "[...document.querySelectorAll('#help-keys .help-row')].map(r =>"
        " [r.querySelector('.help-what').textContent, [...r.querySelectorAll('kbd')].map(k => k.textContent)])"
    )
    assert ["拡大・縮小（カーソルの位置へ）", ["ホイール"]] in rows and ["拡大・縮小（回転の中心へ）", ["+", "−"]] in rows, rows
    assert page.inner_text("#help-foot") == f"cad-viewer {VERSION}", page.inner_text("#help-foot")
    page.keyboard.press("?")
    assert not help_shown() and page.get_attribute("#help-open", "aria-expanded") == "false", "2 ? closes"
    page.keyboard.press("?")
    assert help_shown(), "2 ? opens"
    page.keyboard.press("Escape")
    assert not help_shown(), "2 Esc closes"
    page.keyboard.press("?")
    page.click("#help-close")
    assert not help_shown(), "2 × closes"
    print("2 key list ok")

    # ---- 3. a model: the folders come back (the defaults), the status card stays small
    load_model()
    # (表示 starts folded since the toolbar switches the style, #23 item 10)
    assert folders() == {"表示": False, "視点": True, "断面": False, "肉厚": False, "抜き勾配": False, "体積・重量": False}, folders()
    hud = rect("#hud")
    assert hud[3] - hud[1] < 60, ("3 the status card: two lines at most", hud)
    assert "ダブルクリック" not in page.inner_text("#hud")
    cover = page.evaluate(
        """() => {
          const sels = ['#toolbar', '.lil-gui.lil-root', '#tree-panel', '#measure-panel', '#props-panel', '#hud', '#triad']
          const rs = sels.map(s => document.querySelector(s)).filter(e => e && e.getClientRects().length).map(e => e.getBoundingClientRect())
          let n = 0
          for (let y = 0.5; y < innerHeight; y++) for (let x = 0.5; x < innerWidth; x++)
            if (rs.some(r => x >= r.left && x < r.right && y >= r.top && y < r.bottom)) n++
          return n / (innerWidth * innerHeight)
        }"""
    )
    print("3 cover", round(cover, 3), "before", COVER_BEFORE)
    assert cover < 0.47, ("3 the panels must cover less of the window", cover)

    # ---- 4. 視点: rows of four, still setting the view; closed, none shown
    btn = {name: gui_common.ctl(page, name).locator("button") for row in VIEWS for name in row}
    box = {name: b.bounding_box() for name, b in btn.items()}
    gui = rect(".lil-gui.lil-root")
    for row in VIEWS:
        tops = {round(box[n]["y"], 1) for n in row}
        assert len(tops) == 1, ("4 one row", row, tops)
    assert box["上"]["y"] >= box["正面"]["y"] + box["正面"]["height"], ("4 the second row under the first", box)
    widths = {round(b["width"], 1) for b in box.values()}
    assert len(widths) == 1, ("4 one width", widths)
    for a, b2 in zip(VIEWS[0], VIEWS[1]):
        assert abs(box[a]["x"] - box[b2]["x"]) <= 0.5, ("4 columns", a, b2, box[a], box[b2])
    for n, b in box.items():
        assert gui[0] <= b["x"] and b["x"] + b["width"] <= gui[2], ("4 inside the panel", n, b, gui)
    btn["上"].click()
    page.wait_for_timeout(300)
    v = view()
    d = [t - q for t, q in zip(v["target"], v["position"])]
    norm = sum(x * x for x in d) ** 0.5
    assert d[2] / norm < -0.999, ("4 上 looks down", v)
    btn["等角"].click()
    page.wait_for_timeout(300)
    preset = gui_common.folder_title(page, "視点").locator("xpath=..")
    h_open = preset.bounding_box()["height"]
    gui_common.folder_title(page, "視点").click()
    gui_common.wait_gui_idle(page)
    assert all(not b.is_visible() for b in btn.values()), "4 a closed 視点 shows its buttons"
    h_closed = preset.bounding_box()["height"]
    assert h_closed < h_open - 40, ("4 closed, the folder is its title", h_open, h_closed)
    gui_common.folder_title(page, "視点").click()
    gui_common.wait_gui_idle(page)
    assert all(b.is_visible() for b in btn.values())
    print("4 views", {n: (round(b["x"]), round(b["y"])) for n, b in box.items()})

    # ---- 5. 回転速度 only with 自動回転 on
    speed = gui_common.ctl(page, "回転速度")
    auto = gui_common.ctl(page, "自動回転").locator("input")
    assert not speed.is_visible(), "5 回転速度 with 自動回転 off"
    auto.click()
    page.wait_for_timeout(100)
    assert speed.is_visible(), "5 回転速度 with 自動回転 on"
    auto.click()
    page.wait_for_timeout(100)
    assert not speed.is_visible()

    # ---- 6. 体積・重量: the total first, the parts table folded
    toggle = page.locator("#props-parts-toggle")
    assert toggle.inner_text() == "部品ごとの値（4 部品）", toggle.inner_text()
    assert toggle.get_attribute("aria-expanded") == "false" and not shown("#props-parts-wrap")
    assert rect("#props-total")[3] <= rect("#props-parts-toggle")[1] + 0.5, "6 the total above the table's toggle"
    h0 = rect("#props-panel")
    toggle.click()
    page.wait_for_timeout(300)
    assert toggle.get_attribute("aria-expanded") == "true" and shown("#props-parts-wrap")
    names = sorted(page.locator("#props-parts tbody td.name").all_inner_texts())
    assert names == PARTS, names
    h1 = rect("#props-panel")
    assert (h1[3] - h1[1]) > (h0[3] - h0[1]) + 30, ("6 the table opens", h0, h1)
    print("6 props", round(h0[3] - h0[1]), "->", round(h1[3] - h1[1]))

    # ---- 7. remembered across a reload: 断面 opened, 表示 folded, the table open
    gui_common.folder_title(page, "断面").click()
    gui_common.wait_gui_idle(page)
    gui_common.folder_title(page, "表示").click()
    gui_common.wait_gui_idle(page)
    goto()
    assert folders() == {f: False for f in TOP_FOLDERS} | {"視点": True}, ("7 the empty screen folds them all", folders())
    load_model()
    assert folders() == {"表示": False, "視点": True, "断面": True, "肉厚": False, "抜き勾配": False, "体積・重量": False}, folders()
    assert page.get_attribute("#props-parts-toggle", "aria-expanded") == "true" and shown("#props-parts-wrap")
    # folded again, also remembered
    page.click("#props-parts-toggle")
    goto()
    load_model()
    assert page.get_attribute("#props-parts-toggle", "aria-expanded") == "false" and not shown("#props-parts-wrap")
    print("7 remembered", folders())

    # ---- 8. the key list over a model: placed, not modal, Esc before the measurement
    # (抜き勾配 opened first: its opening resizes the operation panel, which
    # would lay the column out again, the list with it)
    draft = gui_common.ctl(page, "色分け").locator("input")
    page.keyboard.press("?")
    assert help_shown()
    check_help_place("8 model")
    # the status card grows under the open list (the 抜き勾配 legend): the list moves up
    hud0 = rect("#hud")
    draft.click()
    page.wait_for_function("!document.querySelector('#draft-legend').classList.contains('hidden')", timeout=30000)
    page.wait_for_timeout(300)
    assert rect("#hud")[1] < hud0[1] - 50, ("8 the legend must make the status card taller", hud0, rect("#hud"))
    check_help_place("8 a legend under the list")
    draft.click()
    page.wait_for_timeout(300)
    # one press turns 5 degrees about the vertical (a little less between the
    # directions of an elevated view); the damping alone moves it far less
    v0 = settled_view()
    page.keyboard.press("ArrowLeft")
    a = turned(v0, settled_view())
    assert a > 3 and help_shown(), ("8 the arrows turn the view with the list open", a)
    page.keyboard.press("Escape")
    assert not help_shown()
    gui_common.set_mode(page, "計測")
    page.keyboard.press("?")
    page.keyboard.press("Escape")
    assert not help_shown() and gui_common.ctl(page, "モード").locator("select").input_value() == "計測", (
        "8 Esc closes the list, the mode stays"
    )
    page.keyboard.press("Escape")
    assert gui_common.ctl(page, "モード").locator("select").input_value() == "なし", "8 the next Esc ends 計測"
    # a ? typed into a note is a character
    gui_common.set_mode(page, "注記")
    pt = page.evaluate("window.__cadProject(50, 30, 35)")
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("a?b")
    assert not help_shown() and page.input_value(".note-input") == "a?b", "8 ? in a note"
    page.keyboard.press("Escape")  # the note is dropped
    gui_common.set_mode(page, "なし")
    print("8 over a model ok")

    # ---- 9. a drawing: its own list
    load(DXF, done="2D 図面")
    page.click("#help-open")
    assert help_shown()
    keys = page.inner_text("#help-keys")
    assert "スナップ" in keys and "ダブルクリック" not in keys and "回転" not in keys, keys
    page.click("#help-close")
    print("9 drawing ok")

    page.screenshot(path="/tmp/cad_viewer_half_window.png")
    errors = [e for e in errors if "Failed to load resource" not in e]
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("HALF WINDOW E2E OK")
    browser.close()
