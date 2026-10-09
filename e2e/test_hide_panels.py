"""E2E: hide the panels for a while to see the model larger (issue #23 item 2).

H (or 隠す in the GUI's title bar) hides the GUI, the part tree, the measure
list and the volume panel, and the HUD's title and key help; its status line,
the axis triad and a パネルを出す button stay. A view the user has not moved
since its fit is fitted again into the area the panels leave; a moved view is
left as it is. On half a screen (767 x 639) the model gets much larger.

Oracles: nav_common's free rectangle computed from the panels' DOM rects (the
same rule as the app, written separately), the projected corners of the
mold's known box (window.__cadProject), the camera state (window.__cadView),
element visibility, and the HUD status line's height (one line).
"""
from nav_common import DXF, MOLD, close, nav_session

with nav_session() as n:
    page = n.page
    page.set_viewport_size({"width": 767, "height": 639})
    n.load(n.paths["step"])

    def hidden(sel):
        return page.evaluate(
            "s => { const e = document.querySelector(s); return !e || e.getBoundingClientRect().width === 0 }", sel
        )

    def width():
        x0, _, x1, _ = n.rect(*MOLD)
        return x1 - x0

    def refitted(tag):
        """the app fitted again on the toggle: check against the panels now on screen"""
        n.fit_panels = n.panel_rects()
        return n.fill_check(*MOLD, tag)

    def same_view(a, b):
        return all(close(a[k], b[k], 1e-9 * 1000) for k in ("position", "target", "up"))

    PANELS_SHOWN = (".lil-gui.lil-root", "#tree-panel", "#corner-br", "#hud-title", "#hud-keys")
    w0 = width()
    print("shown", n.fill_check(*MOLD, "loaded"), "width", round(w0, 1))
    assert not hidden("#panels-hide") and hidden("#panels-show")

    # ---- 1. H hides; the unmoved view fits again, much larger
    page.keyboard.press("h")
    n.settle()
    for sel in PANELS_SHOWN:
        assert hidden(sel), ("1 still shown", sel)
    assert not hidden("#hud-info") and not hidden("#triad") and not hidden("#panels-show")
    info = refitted("hidden")
    w1 = width()
    print("1 hidden", info, "width", round(w1, 1), "x", round(w1 / w0, 2))
    assert w1 > 1.3 * w0, ("1 the model must get larger", w0, w1)
    # the status line keeps one line: the HUD's room is not cut by the hidden GUI
    h_info = page.evaluate("document.querySelector('#hud-info').getBoundingClientRect().height")
    assert h_info < 30, ("1 the status line wraps", h_info)

    # ---- 2. H again shows them; the view (still unmoved) fits back
    page.keyboard.press("h")
    n.settle()
    for sel in PANELS_SHOWN:
        assert not hidden(sel), ("2 still hidden", sel)
    assert hidden("#panels-show")
    refitted("shown again")
    assert abs(width() - w0) <= 1, ("2 back to the first size", w0, width())

    # ---- 3. a moved view is left as it is
    page.keyboard.press("ArrowLeft")
    n.settle()
    v0 = n.view()
    page.keyboard.press("h")
    n.settle()
    assert hidden(".lil-gui.lil-root")
    assert same_view(v0, n.view()), ("3 a moved view was fitted again", v0, n.view())
    page.keyboard.press("h")
    n.settle()
    assert same_view(v0, n.view()), "3 a moved view was fitted again (shown)"

    # ---- 4. the buttons; the GUI's folders keep their state
    n.fit()
    folders = page.evaluate(
        "[...document.querySelectorAll('.lil-gui .lil-title')].map(t => t.getAttribute('aria-expanded'))"
    )
    page.locator("#panels-hide").click()
    n.settle()
    assert hidden(".lil-gui.lil-root") and not hidden("#panels-show")
    page.locator("#panels-show").click()
    n.settle()
    assert not hidden(".lil-gui.lil-root") and hidden("#panels-show")
    folders2 = page.evaluate(
        "[...document.querySelectorAll('.lil-gui .lil-title')].map(t => t.getAttribute('aria-expanded'))"
    )
    assert folders == folders2, ("4 the 隠す button folded the GUI", folders, folders2)
    refitted("buttons")

    # ---- 5. typing h in a note does not hide anything
    n.set_mode("注記")
    xy = n.project((90, 10, 15))
    page.mouse.click(*xy)
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("h")
    assert not hidden(".lil-gui.lil-root"), "5 h in a text box hid the panels"
    assert page.locator(".note-input").input_value() == "h"
    page.keyboard.press("Escape")
    n.set_mode("なし")

    # ---- 6. a drawing: the toggle works there too
    n.load(DXF, wait_text="2D図面", props="live")
    page.keyboard.press("h")
    n.settle()
    assert hidden(".lil-gui.lil-root") and not hidden("#panels-show")
    page.keyboard.press("h")
    n.settle()
    assert not hidden(".lil-gui.lil-root")

    page.screenshot(path="/tmp/cad_viewer_hide_panels.png")
    print("HIDE PANELS E2E OK")
