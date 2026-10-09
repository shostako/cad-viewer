"""E2E: the empty-screen card, and 3D-only controls hidden on 2D drawings (A2).

A failed load shows its own card (#load-card, see test_load_card.py) in place
of the empty-screen card; closing it brings the empty-screen card back when
nothing is on screen.

Checks what is on screen (visibility of the GUI folders, the card, the HUD
key help, the option state of the mode selector) as models and drawings are
opened in turn. Needs the same servers as the other E2E scripts.
"""
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
STL = str(TESTDATA / "ribbed_plate.stl")
DXF = str(TESTDATA / "plate_drawing.dxf")
FOLDERS_3D = ["表示", "断面", "肉厚", "抜き勾配", "体積・重量"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    def load(path, wait_text="tris"):
        page.set_input_files("#file-input", path)
        page.wait_for_function(
            "([w, n]) => { const t = document.querySelector('#hud-info').textContent;"
            " return t.includes(w) && t.includes(n) }",
            arg=[wait_text, Path(path).name],
            timeout=60000,
        )

    def visible(sel):
        return page.locator(sel).first.is_visible()

    def folder_visible(name):
        title = page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$"))
        return title.first.is_visible()

    def failed_card(why=""):
        """the failed load's card is up (its reason containing `why`); close it"""
        card = page.locator("#load-card")
        assert card.is_visible() and "ファイルを開けなかった" in card.inner_text(), card.inner_text()
        assert why in page.inner_text("#load-reason"), page.inner_text("#load-reason")
        page.click("#load-close")
        assert not card.is_visible()

    def mode_select():
        label = page.locator(".lil-name", has_text=re.compile("^モード"))
        return page.locator(".lil-gui .lil-controller").filter(has=label).first.locator("select")

    def note_disabled():
        return mode_select().evaluate("s => [...s.options].find(o => o.text === '注記').disabled")

    def keys():
        return page.inner_text("#hud-keys")

    def check_3d():
        for f in FOLDERS_3D:
            assert folder_visible(f), ("3D folder hidden", f)
        assert not note_disabled()
        assert "回転" in keys() and "ダブルクリック" in keys(), keys()
        assert not visible("#empty-hint")

    def check_2d():
        for f in FOLDERS_3D:
            assert not folder_visible(f), ("3D folder shown on a drawing", f)
        assert folder_visible("操作")
        assert note_disabled(), "注記 must be disabled on a drawing"
        k = keys()
        assert "回転" not in k and "ダブルクリック" not in k, k
        assert "ドラッグ: 移動" in k and "スナップ" in k, k
        assert not visible("#empty-hint")
        assert not visible("#tree-panel")

    # 1. empty screen: the card, and its button opens the file dialog
    assert visible("#empty-hint")
    card = page.locator("#empty-hint")
    assert "ドロップ" in card.inner_text() and "DXF" in card.inner_text(), card.inner_text()
    box = card.bounding_box()
    vw, vh = 1280, 800
    # in the middle of the part left of the operation panel (it fits there at 1280)
    gui = page.locator(".lil-gui.lil-root").bounding_box()
    assert gui["x"] >= box["width"] + 32, (gui, box)
    assert abs(box["x"] + box["width"] / 2 - gui["x"] / 2) < 2 and abs(box["y"] + box["height"] / 2 - vh / 2) < 2, (box, gui)
    with page.expect_file_chooser() as fc:
        page.click("#empty-open")
    fc.value.set_files(STEP)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000)
    check_3d()

    # 2. a drawing: 3D-only controls go away, the key help changes
    def selected_mode():
        return mode_select().evaluate("s => s.options[s.selectedIndex].text")

    # section and thickness switched on in 3D must not survive a drawing
    page.locator(".lil-gui .lil-title", has_text=re.compile("^断面$")).click()
    page.locator(".lil-gui .lil-controller").filter(
        has=page.locator(".lil-name", has_text=re.compile("^有効"))
    ).first.locator("input").click()
    page.locator(".lil-gui .lil-title", has_text=re.compile("^肉厚$")).click()
    page.locator(".lil-gui .lil-controller").filter(
        has=page.locator(".lil-name", has_text=re.compile("^ヒートマップ"))
    ).first.locator("input").click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('ヒートマップ表示中')", timeout=60000)

    mode_select().select_option("注記")
    load(DXF, wait_text="2D図面")
    check_2d()
    assert selected_mode() == "なし", ("注記 must fall back to なし on a drawing", selected_mode())
    # 計測 still works on drawings
    mode_select().select_option("計測")
    assert selected_mode() == "計測"
    mode_select().select_option("なし")

    # 3. back to 3D (mesh and B-rep): everything is back, section and heatmap off
    load(STL)
    check_3d()
    for name in ("有効", "ヒートマップ"):
        box = page.locator(".lil-gui .lil-controller").filter(
            has=page.locator(".lil-name", has_text=re.compile("^" + name))
        ).first.locator("input")
        assert not box.is_checked(), (name, "still on after a drawing")
    load(DXF, wait_text="2D図面")
    check_2d()
    load(STEP)
    check_3d()
    assert visible("#tree-panel")

    # 4. a failed load keeps what is on screen; on an empty screen the card comes back
    bad = TESTDATA / "_broken_for_test.stl"
    bad.write_text("this is not an STL")
    try:
        page.set_input_files("#file-input", str(bad))
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
        assert not visible("#empty-hint"), "the model is still on screen: no open card"
        failed_card("読めない")
        assert not visible("#empty-hint") and visible("#tree-panel"), "the model is still on screen"
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        page.set_input_files("#file-input", str(bad))
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
        assert not visible("#empty-hint"), "the failed card stands in for the open card"
        failed_card("読めない")
        assert visible("#empty-hint"), "nothing loaded: the open card comes back with the failed card closed"
    finally:
        bad.unlink()

    # 5. a failure after the old model was torn down (the upload worked, the mesh
    #    did not arrive) leaves an empty screen: the card must come back
    load(STEP)
    assert not visible("#empty-hint")
    page.route("**/mesh.bin", lambda route: route.abort())
    try:
        page.set_input_files("#file-input", STL)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
    finally:
        page.unroute("**/mesh.bin")
    failed_card("受け取れなかった")
    assert visible("#empty-hint"), "the old model is gone and nothing replaced it: the card must come back"
    load(STEP)
    assert not visible("#empty-hint")

    # 6. the same with a drawing on screen: the old drawing must not stay
    #    visible (and clickable) under the card, and the 3D-only folders stay
    #    hidden only while a drawing is shown
    load(DXF, wait_text="2D図面")
    assert page.locator("#viewport2d svg").count() == 1
    page.route("**/drawing.svg", lambda route: route.abort())
    try:
        page.set_input_files("#file-input", DXF)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
    finally:
        page.unroute("**/drawing.svg")
    failed_card("受け取れなかった")
    assert visible("#empty-hint"), "nothing is shown any more: the card must come back"
    assert page.locator("#viewport2d svg").count() == 0, "the old drawing is still in the 2D viewer"
    assert not visible("#viewport2d")
    check_keys_3d = keys()
    assert "回転" in check_keys_3d, check_keys_3d  # the empty screen is the 3D one again
    load(DXF, wait_text="2D図面")
    check_2d()

    page.screenshot(path="/tmp/cad_viewer_view_modes.png")
    # the 422 of the broken file and the aborted mesh request
    errors = [e for e in errors if "Failed to load resource" not in e]
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("VIEW MODES E2E OK")
    browser.close()
