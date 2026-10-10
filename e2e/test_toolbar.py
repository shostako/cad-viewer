"""E2E: the toolbar and its keys (issue #23 item 10).

The toolbar sits at the top of the right-hand column (264 px, 12 px from the
window's top and right edges), the operation panel 8 px under it:

  開く · 全体表示 | 回転 · 計測 · 注記 | 断面 · 表示スタイル · 画像を保存 · ?

- On the empty screen only 開く, 表示スタイル and ? can be pressed.
- 開く opens the file dialog; 全体表示 frames the model (nav_common's free
  area, which counts the toolbar as a panel); 画像を保存 downloads a PNG; ?
  opens and closes the key list.
- The mode in use is pressed, also when the operation panel's モード changes
  it; M and N switch 計測 and 注記 on, or back to 回転; the buttons do the
  same.
- S cuts (断面's 有効, and a pick on the cut-away side misses), and the button
  follows the panel's checkbox; W steps through the display styles in the
  select's order, and the button's title names the style.
- The letters typed into a note change nothing; H hides the toolbar with the
  panels.
- A mesh model: 計測 looks off and says why in its title; pressed, the status
  line says why at once. A drawing: 注記, 断面 and 表示スタイル cannot be
  pressed, and N, S and W do nothing; M still measures.
- 表示 starts folded (the toolbar switches the style).

Oracles: DOM rects, attributes and classes, the operation panel's controls,
__cadView (displayStyle), __cadPick, the download, the file chooser.
"""
from nav_common import DXF, MOLD, TESTDATA, nav_session

import gui_common

STL = str(TESTDATA / "ribbed_plate.stl")
ACTIONS = ["open", "fit", "mode-none", "mode-measure", "mode-note", "section", "style", "png", "help"]
EDGE, GAP, COLUMN, BAR_H = 12, 8, 264, 36
CUT = (90, 10, 15)  # on the plate's top, on the side the default section cuts away
STYLES = ["shaded-edges", "shaded", "wireframe", "xray"]
STYLE_NAMES = {"shaded-edges": "陰影＋稜線", "shaded": "陰影のみ", "wireframe": "ワイヤーフレーム", "xray": "半透明"}

with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    W = 1280

    def btn(action):
        return page.locator(f"#toolbar button[data-action='{action}']")

    def pressed():
        return [a for a in ACTIONS if btn(a).get_attribute("aria-pressed") == "true"]

    def enabled():
        return [a for a in ACTIONS if btn(a).is_enabled()]

    def mode():
        return gui_common.ctl(page, "モード").locator("select").input_value()

    def rect(sel):
        return page.evaluate(
            "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] }", sel
        )

    def shown(sel):
        return page.evaluate("s => document.querySelector(s).getClientRects().length > 0", sel)

    def style():
        return n.view()["displayStyle"]

    def cut_misses():
        hit = n.pick(n.project(CUT))
        return hit is None or hit["point"][0] <= 50.5

    # ---- 1. the empty screen: in place, only 開く, 表示スタイル and ? pressable
    t = rect("#toolbar")
    assert abs(t[2] - t[0] - COLUMN) <= 0.5 and abs(W - t[2] - EDGE) <= 0.5 and abs(t[1] - EDGE) <= 0.5, ("1 the toolbar", t)
    assert abs(t[3] - t[1] - BAR_H) <= 0.5, ("1 its height", t)
    g = rect(".lil-gui.lil-root")
    assert abs(g[1] - (t[3] + GAP)) <= 0.5 and abs(g[2] - t[2]) <= 0.5, ("1 the operation panel under it", t, g)
    assert page.evaluate("[...document.querySelectorAll('#toolbar button')].map(b => b.dataset.action)") == ACTIONS
    assert enabled() == ["open", "style", "help"], enabled()
    titles = {a: btn(a).get_attribute("title") for a in ACTIONS}
    for a, key in (("fit", "F"), ("mode-none", "Esc"), ("mode-measure", "（M）"), ("mode-note", "（N）"),
                   ("section", "（S）"), ("style", "W"), ("help", "?")):
        assert key in titles[a], ("1 the key in the title", a, titles[a])
    assert page.title() == "cad-viewer", page.title()
    print("1 empty", [round(x) for x in t], enabled())

    # ---- 2. 開く: the file dialog; then the model, 回転 pressed, 表示 folded
    with page.expect_file_chooser() as fc:
        btn("open").click()
    fc.value.set_files(n.paths["step"])
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000)
    n.settle()
    assert enabled() == ACTIONS and pressed() == ["mode-none"], (enabled(), pressed())
    assert page.title() == "mini_mold.step — cad-viewer", ("2 the tab names the file", page.title())
    assert "lil-closed" in gui_common.folder_title(page, "表示").locator("xpath=..").get_attribute("class"), "2 表示 folded"

    # ---- 3. the modes: buttons, M and N, and the panel's モード
    btn("mode-measure").click()
    assert mode() == "計測" and pressed() == ["mode-measure"], (mode(), pressed())
    assert "計測: クリックで 1 点目" in page.inner_text("#hud-info")
    page.keyboard.press("m")
    assert mode() == "なし" and pressed() == ["mode-none"], ("3 M again: back to 回転", mode(), pressed())
    page.keyboard.press("m")
    assert mode() == "計測"
    page.keyboard.press("n")
    assert mode() == "注記" and pressed() == ["mode-note"], (mode(), pressed())
    page.keyboard.press("n")
    assert mode() == "なし"
    btn("mode-note").click()
    assert mode() == "注記"
    btn("mode-none").click()
    assert mode() == "なし" and pressed() == ["mode-none"]
    gui_common.set_mode(page, "計測")
    assert pressed() == ["mode-measure"], ("3 the panel's モード is followed", pressed())
    gui_common.set_mode(page, "なし")
    print("3 modes ok")

    # ---- 4. 断面: S, the button, and the panel's checkbox
    assert not cut_misses(), "4 the plate's top before the section"
    page.keyboard.press("s")
    page.wait_for_timeout(200)
    enabled_box = gui_common.ctl(page, "有効").locator("input")
    assert enabled_box.is_checked() and "section" in pressed() and cut_misses(), ("4 S cuts", pressed())
    page.keyboard.press("s")
    page.wait_for_timeout(200)
    assert not enabled_box.is_checked() and "section" not in pressed() and not cut_misses(), "4 S again"
    btn("section").click()
    page.wait_for_timeout(200)
    assert enabled_box.is_checked() and cut_misses()
    enabled_box.click()
    page.wait_for_timeout(200)
    assert "section" not in pressed() and not cut_misses(), ("4 the button follows the checkbox", pressed())
    print("4 section ok")

    # ---- 5. 表示スタイル: W steps through the styles, the title names it
    assert style() == STYLES[0]
    select = gui_common.ctl(page, "表示スタイル").locator("select")
    for i in range(1, 5):
        page.keyboard.press("w") if i % 2 else btn("style").click()
        page.wait_for_timeout(100)
        want = STYLES[i % 4]
        # (lil-gui's select shows the names: its options' values are the names)
        assert style() == want and select.input_value() == STYLE_NAMES[want], ("5 the next style", i, style(), select.input_value())
        assert f"表示スタイル: {STYLE_NAMES[want]}" in btn("style").get_attribute("title"), btn("style").get_attribute("title")
    print("5 styles ok")

    # ---- 6. 全体表示 frames the model again; 画像を保存 downloads; ? opens the key list
    for _ in range(3):
        page.keyboard.press("ArrowLeft")
    for _ in range(4):
        page.keyboard.press("+")
    n.wait_gui_idle()
    btn("fit").click()
    n.settle()
    n.mark_fit()
    print("6 fit", n.fill_check(*MOLD, "toolbar fit", fallback=False))
    with page.expect_download() as dl:
        btn("png").click()
    assert dl.value.suggested_filename.endswith(".png"), dl.value.suggested_filename
    btn("help").click()
    assert shown("#help-card")
    btn("help").click()
    assert not shown("#help-card")

    # ---- 7. letters typed into a note change nothing
    gui_common.set_mode(page, "注記")
    page.mouse.click(*n.project((50, 30, 35)))
    page.wait_for_selector(".note-input", timeout=5000)
    # one letter at a time: m then n would switch 計測 on and 注記 back, and end where it began
    for i, k in enumerate("mnsw"):
        page.keyboard.type(k)
        assert mode() == "注記" and style() == STYLES[0] and "section" not in pressed(), ("7 a key in a note", k, mode(), style())
        assert page.input_value(".note-input") == "mnsw"[: i + 1]
    page.keyboard.press("Escape")
    gui_common.set_mode(page, "なし")

    # ---- 8. H hides the toolbar with the panels
    page.keyboard.press("h")
    n.settle()
    assert not shown("#toolbar"), "8 H hides the toolbar"
    page.keyboard.press("h")
    n.settle()
    assert shown("#toolbar")

    # ---- 9. a mesh model: 計測 looks off, says why, and the line says it at once
    n.load(STL)
    m = btn("mode-measure")
    assert "off" in (m.get_attribute("class") or "") and "STEP・IGES" in m.get_attribute("title"), m.get_attribute("title")
    m.click()
    assert mode() == "計測" and "STEP/IGES" in page.inner_text("#hud-info"), page.inner_text("#hud-info")
    gui_common.set_mode(page, "なし")

    # ---- 10. a drawing: no 注記, 断面 or 表示スタイル; N S W do nothing, M measures
    n.load(DXF, wait_text="2D図面")
    assert page.title() == "plate_drawing.dxf — cad-viewer", page.title()
    assert enabled() == ["open", "fit", "mode-none", "mode-measure", "png", "help"], enabled()
    before = select.input_value()
    for k in ("n", "s", "w"):
        page.keyboard.press(k)
    assert mode() == "なし" and select.input_value() == before and not enabled_box.is_checked(), "10 N S W on a drawing"
    page.keyboard.press("m")
    assert mode() == "計測" and pressed() == ["mode-measure"]
    page.keyboard.press("m")
    assert mode() == "なし"
    print("10 drawing ok")

    page.screenshot(path="/tmp/cad_viewer_toolbar.png")
    print("TOOLBAR E2E OK")
