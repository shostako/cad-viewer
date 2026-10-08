"""E2E: 全体表示 (fit) — the A checks of the navigation suite.

Split from test_navigation.py so each script stays well under the CI
per-script limit. Helpers and the rule for expected values: nav_common.py
(the fit fills the free area of the canvas, clear of the panels; the cases
built around the panels themselves are in test_nav_fit_panels.py).
"""
import re

from nav_common import (
    DXF, HUGE, LOAD_DIR, MOLD, MOLD_NO_PLATE, RUNNER, SURFACE, TINY,
    add, close, corners, cross, dot, length, mul, nav_session, norm, sub,
)

with nav_session(boxes=("runner", "tiny", "huge")) as n:
    page = n.page
    paths = n.paths
    STEP = paths["step"]  # private copy, empty sidecar (nav_session)
    load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
    canvas_rect, ctl, click_button, set_mode, set_rotate = n.canvas_rect, n.ctl, n.click_button, n.set_mode, n.set_rotate
    direction, same_dir, rect, fill_check, depth_check = n.direction, n.same_dir, n.rect, n.fill_check, n.depth_check
    plane_point, wheel, canvas_ink_rect, marker_rect = n.plane_point, n.wheel, n.canvas_ink_rect, n.marker_rect

    # ============ A. fit =========================================================
    # A1. default view of a long part
    load(paths["runner"])
    v = view()
    print("A1 runner", fill_check(*RUNNER, "runner"))
    assert close(norm(sub(v["position"], v["target"])), LOAD_DIR, 1e-9), v
    assert close(v["up"], [0, 0, 1], 1e-12), v["up"]
    depth_check(*RUNNER)

    # A2. the pixels agree with the projected corners
    ctl("グリッド").locator("input").click()
    settle()
    ink = canvas_ink_rect()
    want = rect(*RUNNER)
    print("A2 ink", [round(x, 1) for x in ink], "corners", [round(x, 1) for x in want])
    assert all(abs(a - b) <= 3 for a, b in zip(ink, want)), (ink, want)
    ctl("グリッド").locator("input").click()

    # A3. fit keeps the direction, from every trigger
    triggers = ["f", "Home", "F", "button"]
    for i, preset in enumerate(["正面", "上", "右", "等角", "左"]):
        click_button(preset)
        for _ in range(3):
            page.keyboard.press("-")
        for _ in range(2):
            page.keyboard.press("Shift+ArrowRight")
        v0 = view()
        trig = triggers[i % len(triggers)]
        n.fit(trig)
        v1 = view()
        same_dir(v0, v1)
        print("A3", preset, trig, fill_check(*RUNNER, preset))
        depth_check(*RUNNER)

    # A4. narrow viewport: the width limits
    page.set_viewport_size({"width": 600, "height": 900})
    page.wait_for_timeout(300)
    n.fit()
    print("A4 narrow", fill_check(*RUNNER, "600x900"))
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_timeout(300)
    n.fit()
    fill_check(*RUNNER, "1280x800")

    # A5. free rotation: fit keeps the roll
    set_rotate("自由回転")
    for _ in range(20):
        page.keyboard.press("ArrowUp")
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    for _ in range(3):
        page.keyboard.press("-")
    v0 = view()
    n.fit()
    v1 = view()
    same_dir(v0, v1)
    assert abs(v1["up"][2]) < 0.9, ("still rolled", v1["up"])
    print("A5 free", fill_check(*RUNNER, "free"))
    set_rotate("ターンテーブル")

    # A6. height-limited view, then hidden parts
    load(STEP)
    click_button("右")
    n.fit()
    # the tree (top left) narrows the free area: a fit that ignored it would overfill
    print("A6 right", fill_check(*MOLD, "mold right", needs=("#tree-panel",)))
    plate_box = page.locator("#tree-panel label", has_text=re.compile("^plate$")).locator("input")
    plate_box.click()
    n.fit()
    print("A6 no plate", fill_check(*MOLD_NO_PLATE, "no plate"))
    plate_box.click()

    # A7. near / far follow the model
    load(paths["tiny"])
    print("A7 tiny", fill_check(*TINY, "tiny"))
    depth_check(*TINY)
    load(paths["huge"])
    print("A7 huge", fill_check(*HUGE, "huge"))
    depth_check(*HUGE)

    # A8. loading resets the direction (and the roll)
    set_rotate("自由回転")
    for _ in range(7):
        page.keyboard.press("ArrowUp")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    assert not close(view()["up"], [0, 0, 1], 1e-3)
    load(paths["runner"])
    v = view()
    assert close(norm(sub(v["position"], v["target"])), LOAD_DIR, 1e-9), v
    assert close(v["up"], [0, 0, 1], 1e-12), v["up"]
    fill_check(*RUNNER, "reload")
    set_rotate("ターンテーブル")

    # A9. 2D drawing: F / Home fit the drawing; then 3D again (aspect must survive)
    load(DXF, wait_text="2D図面")
    svg = "#viewport2d svg"
    def vbox():
        return [float(x) for x in page.get_attribute(svg, "viewBox").split()]

    vb0 = vbox()
    for key in ("f", "Home"):
        page.mouse.move(640, 400)
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(100)
        assert vbox() != vb0, "wheel must zoom the drawing"
        page.keyboard.press(key)
        assert close(vbox(), vb0, 1e-9 * max(map(abs, vb0))), (key, vbox(), vb0)
    load(STEP)
    # the load fit, with the tree that this same load shows
    fill_check(*MOLD, "after 2D", needs=("#tree-panel",))

    # A11. the window resized while a 2D drawing is shown, then a 3D load: the
    #      3D canvas was hidden, so it has not taken the new size yet when the
    #      mesh comes; the load fit must use the new size anyway. Whether the
    #      canvas has caught up by then depends on timing (a frame may pass
    #      while the mesh is fetched), so the cycle runs with several sizes.
    for w, h in ((900, 700), (1100, 650), (800, 900), (1280, 800)):
        load(DXF, wait_text="2D図面")
        page.set_viewport_size({"width": w, "height": h})
        load(STEP)
        _, _, cw, ch = canvas_rect()
        assert (cw, ch) == (w, h), ("A11 the canvas fills the window", cw, ch, w, h)
        print("A11", w, h, fill_check(*MOLD, f"after 2D + resize to {w}x{h}"))

    # A12. the same without timing: the canvas's box changes and a fit runs in
    #      the same task, so the ResizeObserver cannot have reported the new
    #      size yet (it does so at the next frame). The style is the test's
    #      stand-in for a resize the canvas has not caught up with.
    page.evaluate(
        """() => {
             const v = document.querySelector('#viewport')
             v.style.right = '320px'
             v.style.bottom = '120px'
             window.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', code: 'KeyF' }))
           }"""
    )
    settle()
    n.fit_panels = n.panel_rects()  # as at the fit: nothing changed them since
    _, _, cw, ch = canvas_rect()
    assert (cw, ch) == (960, 680), ("A12 the canvas follows its box", cw, ch)
    print("A12", fill_check(*MOLD, "fit before the resize is reported"))
    page.evaluate("(() => { const v = document.querySelector('#viewport'); v.style.right = ''; v.style.bottom = '' })()")
    page.wait_for_timeout(300)
    n.fit()

    # A10. F typed into the note box does not fit
    set_mode("注記")
    page.keyboard.press("-")
    page.keyboard.press("-")
    pt = project((50, 30, 35))
    page.mouse.click(*pt)
    page.wait_for_selector(".note-input", timeout=5000)
    before = view()
    page.keyboard.type("f")
    settle()
    assert close(view()["position"], before["position"], 1e-12), "F in the note box moved the view"
    page.keyboard.press("Escape")
    set_mode("なし")
    n.fit()

    page.screenshot(path="/tmp/cad_viewer_nav_fit.png")
    print("NAV FIT E2E OK")
