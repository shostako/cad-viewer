"""E2E: hide the panels for a while to see the model larger (issue #23 item 2).

H (or 隠す in the GUI's title bar) hides the GUI, the part tree, the measure
list and the volume panel, and the HUD's title and key help; its status line,
the axis triad and a パネルを出す button stay. A view the user has not moved
since its fit is fitted again into the area the panels leave; a moved view is
left as it is. On half a screen (767 x 639) the model gets much larger.

Oracles: nav_common's free rectangle computed from the panels' DOM rects (the
same rule as the app, written separately), the projected corners of the
mold's known box (window.__cadProject), the camera state (window.__cadView),
element visibility, and the HUD status line's height (one line). Also: the
refit still happens after a fit and a projection switch (the switch keeps the
view), and a held H (keyboard auto-repeat) toggles once.
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
        n.mark_fit()
        return n.fill_check(*MOLD, tag)

    def same_view(a, b):
        return all(close(a[k], b[k], 1e-9 * 1000) for k in ("position", "target", "up"))

    PANELS_SHOWN = (".lil-gui.lil-root", "#tree-panel", "#corner-br")
    w0 = width()
    print("shown", n.fill_check(*MOLD, "loaded"), "width", round(w0, 1))
    assert not hidden("#panels-hide") and hidden("#panels-show")
    # 隠す stays a small button at the right end of the title bar: the rest of
    # the title still takes the clicks that fold the GUI
    hide_box = page.locator("#panels-hide").bounding_box()
    title_hit = page.evaluate(
        "(() => { const t = document.querySelector('.lil-gui.lil-root > .lil-title').getBoundingClientRect();"
        " const e = document.elementFromPoint(t.left + t.width / 2, t.top + t.height / 2);"
        " return e.classList.contains('lil-title') })()"
    )
    assert hide_box["width"] < 80 and title_hit, ("隠す covers the GUI's title", hide_box, title_hit)

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

    # ---- 5b. a fit, then the other projection: the view is still the fit's
    #     (the switch keeps it), so hiding fits again into the larger area
    n.fit()
    n.set_projection("平行")
    w_par = width()
    page.keyboard.press("h")
    n.settle()
    assert hidden(".lil-gui.lil-root")
    refitted("parallel, hidden")
    assert width() > 1.3 * w_par, ("5b no refit after a projection switch", w_par, width())
    page.keyboard.press("h")
    n.settle()
    n.set_projection("透視")
    n.fit()

    # ---- 5c. a held H: the key's auto-repeat does not toggle again
    page.keyboard.press("h")
    n.settle()
    assert hidden(".lil-gui.lil-root")
    for _ in range(3):
        page.evaluate("window.dispatchEvent(new KeyboardEvent('keydown', { key: 'h', code: 'KeyH', repeat: true }))")
        n.settle()
    assert hidden(".lil-gui.lil-root") and not hidden("#panels-show"), "5c auto-repeat toggled the panels"
    page.keyboard.press("h")
    n.settle()
    assert not hidden(".lil-gui.lil-root")

    # ---- 6. a drawing: the toggle works there too
    n.load(DXF, wait_text="2D図面", props="live")
    page.keyboard.press("h")
    n.settle()
    assert hidden(".lil-gui.lil-root") and not hidden("#panels-show")
    page.keyboard.press("h")
    n.settle()
    assert not hidden(".lil-gui.lil-root")

    # ---- 7. an operation panel too tall for the window scrolls its list: its
    #    title (with 隠す on it) keeps its height, as a folder's title has
    page.set_viewport_size({"width": 767, "height": 420})
    n.load(n.paths["step"])
    for name in ("表示", "視点", "断面", "肉厚"):
        title = page.locator(".lil-gui .lil-title", has_text=name).first
        if title.get_attribute("aria-expanded") != "true":
            title.click()
    n.wait_gui_idle()
    m = page.evaluate(
        """(() => { const root = document.querySelector('.lil-gui.lil-root')
             const list = root.querySelector(':scope > .lil-children')
             const t = root.querySelector(':scope > .lil-title').getBoundingClientRect()
             const f = root.querySelector('.lil-children .lil-gui > .lil-title').getBoundingClientRect()
             const b = document.querySelector('#panels-hide').getBoundingClientRect()
             return { scrolls: list.scrollHeight > list.clientHeight + 2, title: [t.top, t.bottom],
                      folder: f.height, button: [b.top, b.bottom] } })()"""
    )
    print("7 low window", m)
    assert m["scrolls"], ("7 the case needs a list that scrolls", m)
    assert abs((m["title"][1] - m["title"][0]) - m["folder"]) <= 0.5, ("7 the title shrank", m)
    assert m["title"][0] <= m["button"][0] and m["button"][1] <= m["title"][1], ("7 隠す sticks out of the title", m)
    page.locator("#panels-hide").click()
    n.settle()
    assert hidden(".lil-gui.lil-root") and not hidden("#panels-show")
    page.locator("#panels-show").click()
    n.settle()

    page.screenshot(path="/tmp/cad_viewer_hide_panels.png")
    print("HIDE PANELS E2E OK")
