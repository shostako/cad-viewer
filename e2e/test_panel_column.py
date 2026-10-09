"""E2E: the right-hand column, the GUI above and the measure list / volume panel below.

The GUI (lil-gui, fixed top right) grows as folders open, and the bottom-right
stack (#measure-panel above #props-panel) grows with each measurement. On a
short window the two used to meet, and the GUI's folder titles covered the
measure list's delete buttons (a click on × landed on 体積・重量).

Every check reads the page itself, never the layout code: element rectangles
(getBoundingClientRect), what the browser hit-tests at a point
(document.elementFromPoint) and the result of real clicks.

The HUD (bottom left) must stay clear of the column too: on half a screen its
lines are longer than the room left of the column.

Steps: (0) the empty screen on half a screen; mini_mold.step on a 1280x700
window, six distance measurements; then (1) the default folders, (2) every
folder open, (3) a 560 px window, (4) a roomy 1200 px window where nothing has
to give way, (5) a folder opened at the bottom of a GUI that scrolls is brought
into view, (5b) half a screen, (6) deleting with × works and the panel goes
away with the last entry.
"""
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
# make_step_assembly.py: cavity block top (z 35) and the plate top (z 15)
CAV_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)
N_MEASURE = 6
FOLDERS = ("表示", "断面", "肉厚", "抜き勾配", "体積・重量")
MARGIN = 12  # #corner-br's distance from the window's bottom
HALF = {"width": 767, "height": 639}  # a browser on the right half of a 1536x816 screen


def overlap(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 700})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    # "ResizeObserver loop completed with undelivered notifications" reaches
    # window's error event but not always the console: collect it in the page
    page.add_init_script(
        "window.__winErrors = []; window.addEventListener('error', e => window.__winErrors.push(String(e.message)))"
    )
    # The shared backend may hold notes on mini_mold from other scripts, and
    # this one deletes entries: sidecars stay in the page, the backend is
    # neither read nor written.
    page.route(
        "**/sidecar",
        lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {}),
    )
    page.goto(BASE_URL)
    page.evaluate("localStorage.clear()")
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    def settle(ms=450):
        # lil-gui animates folders for 300 ms; the column settles a frame or two later
        page.wait_for_timeout(ms)
        page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def folder(name):
        return page.locator(".lil-gui").filter(has=page.locator(":scope > .lil-title", has_text=name)).first

    def set_folder(name, want_open):
        title = folder(name).locator(":scope > .lil-title")
        if (title.get_attribute("aria-expanded") == "true") != want_open:
            title.click()
        settle()

    def rects():
        return page.evaluate(
            """() => { const q = s => { const e = document.querySelector(s);
                 if (!e || e.offsetParent === null && getComputedStyle(e).position !== 'fixed') return null;
                 const r = e.getBoundingClientRect(); return {left: r.left, top: r.top, right: r.right, bottom: r.bottom} };
               return { gui: q('.lil-gui.lil-root'), measure: q('#measure-panel'), props: q('#props-panel'),
                        total: q('#props-total'), hud: q('#hud'), h: window.innerHeight } }"""
        )

    def hit_free(sel, tag):
        """every element matching sel is either scrolled out of its list or hit-tests as itself"""
        res = page.evaluate(
            """(sel) => [...document.querySelectorAll(sel)].map(e => {
                 const r = e.getBoundingClientRect();
                 const list = e.closest('#measure-panel, #props-panel');
                 const lr = list.getBoundingClientRect();
                 const x = r.left + r.width / 2, y = r.top + r.height / 2;
                 if (y < lr.top || y > lr.bottom) return 'scrolled';
                 const t = document.elementFromPoint(x, y);
                 return t === e || e.contains(t) ? 'ok' : (t ? t.className || t.tagName : 'null') })""",
            sel,
        )
        assert res and "ok" in res, (tag, sel, res)
        assert all(r in ("ok", "scrolled") for r in res), (tag, sel, res)
        return res

    def check_column(tag):
        r = rects()
        h = r["h"]
        for k in ("gui", "measure", "props", "total"):
            assert r[k], (tag, k, r)
        # nothing in the stack sits under the GUI, and the two panels do not meet
        for k in ("measure", "props"):
            assert not overlap(r["gui"], r[k]), (tag, "gui over", k, r)
        assert not overlap(r["measure"], r["props"]), (tag, r)
        # the HUD (bottom left) stays clear of the whole column
        for k in ("gui", "measure", "props"):
            assert not overlap(r["hud"], r[k]), (tag, "hud under", k, r)
        # all of it is on the screen, the total line included
        assert r["gui"]["top"] >= -0.5 and r["gui"]["bottom"] <= h + 0.5, (tag, r)
        assert r["props"]["bottom"] <= h - MARGIN + 0.5, (tag, r)
        assert r["props"]["top"] <= r["total"]["top"] and r["total"]["bottom"] <= r["props"]["bottom"] + 0.5, (tag, r)
        # the browser hits the buttons themselves, not a GUI title over them
        hit_free("#measure-list li button", tag)
        # the list keeps room for its title and at least two whole entries (each
        # wraps to two lines within the column's one width, 264 px)
        seen = page.evaluate(
            """() => { const m = document.querySelector('#measure-panel');
                 const lo = m.getBoundingClientRect().top + m.clientTop, hi = lo + m.clientHeight;
                 const li = [...m.querySelectorAll('#measure-list li')];
                 return [li.length, li.filter(e => { const r = e.getBoundingClientRect();
                   return r.top >= lo - 0.5 && r.bottom <= hi + 0.5 }).length] }"""
        )
        assert seen[1] >= min(seen[0], 2), (tag, "entries in full view (all, seen)", seen)
        print(tag, seen, {k: (round(v["top"]), round(v["bottom"])) for k, v in r.items() if isinstance(v, dict)})
        return r

    def gui_scrolls():
        return page.evaluate(
            "(() => { const c = document.querySelector('.lil-gui.lil-root > .lil-children');"
            " return c.scrollHeight > c.clientHeight + 1 })()"
        )

    # 0. the empty screen on half of a 1536 px screen (767x639): the HUD's
    # opening hint is longer than the room left of the GUI, so it has to wrap
    page.set_viewport_size(HALF)
    settle()
    r0 = rects()
    print("0 empty half", r0["hud"], r0["gui"])
    assert r0["hud"] and r0["gui"], r0
    assert not overlap(r0["hud"], r0["gui"]), ("0 hud under the GUI", r0)
    page.set_viewport_size({"width": 1280, "height": 700})
    settle()

    page.set_input_files("#file-input", STEP)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000)
    page.wait_for_function("!document.querySelector('#props-panel').classList.contains('hidden')"
                           " && document.querySelector('#props-total') !== null", timeout=60000)
    settle(800)

    page.locator(".lil-gui select").first.select_option("計測")
    page.evaluate("document.activeElement && document.activeElement.blur()")

    def click_world(xyz):
        pt = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(250)

    assert page.locator("#measure-list li").count() == 0
    for i in range(N_MEASURE):
        click_world(CAV_TOP)
        click_world(PLATE_TOP)
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length >= {i + 1}", timeout=10000)
    settle()
    assert page.locator("#measure-list li").count() == N_MEASURE

    # 1. default folders (表示 and 視点 open)
    check_column("1 default 700")

    # 2. every folder open: the GUI alone would be taller than the window
    for name in FOLDERS:
        set_folder(name, True)
    check_column("2 all open 700")
    assert gui_scrolls(), "the GUI should have given way and scroll"

    # 3. shorter window
    page.set_viewport_size({"width": 1280, "height": 560})
    settle()
    check_column("3 all open 560")

    # 4. a roomy window: nothing gives way, the GUI shows everything without a scrollbar
    for name in FOLDERS[1:]:
        set_folder(name, False)
    page.set_viewport_size({"width": 1280, "height": 1200})
    settle()
    check_column("4 roomy 1200")
    assert not gui_scrolls(), "the GUI scrolls although the window has room"
    # the measure list shows every entry (no inner scrollbar) when it has room
    assert page.evaluate(
        "(() => { const m = document.querySelector('#measure-panel'); return m.scrollHeight <= m.clientHeight + 1 })()"
    ), "the measure list scrolls although the window has room"

    # 5. back to 700 with every folder open, scroll the GUI to the top, then
    # close and reopen 抜き勾配 (low in the GUI): it comes into view, title included
    page.set_viewport_size({"width": 1280, "height": 700})
    for name in FOLDERS:
        set_folder(name, True)
    assert gui_scrolls()
    set_folder("抜き勾配", False)
    # put the closed folder's title on the GUI's bottom edge: opened there, its
    # content is out of view unless something scrolls it in
    page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-gui')].find(g =>
             g.querySelector(':scope > .lil-title').textContent === '抜き勾配');
           const c = document.querySelector('.lil-gui.lil-root > .lil-children');
           c.scrollTop = 0;
           c.scrollTop += f.querySelector(':scope > .lil-title').getBoundingClientRect().bottom - c.getBoundingClientRect().bottom }"""
    )
    settle(100)
    before = page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-gui')].find(g =>
             g.querySelector(':scope > .lil-title').textContent === '抜き勾配');
           const c = document.querySelector('.lil-gui.lil-root > .lil-children');
           const t = f.querySelector(':scope > .lil-title').getBoundingClientRect();
           return { x: t.left + t.width / 2, y: t.top + t.height / 2, bottom: t.bottom,
                    edge: c.getBoundingClientRect().bottom, scrollTop: c.scrollTop } }"""
    )
    assert abs(before["bottom"] - before["edge"]) <= 1 and before["scrollTop"] > 0, before
    page.mouse.click(before["x"], before["y"])
    settle(700)
    vis = page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-gui')].find(g =>
             g.querySelector(':scope > .lil-title').textContent === '抜き勾配');
           const s = document.querySelector('.lil-gui.lil-root > .lil-children').getBoundingClientRect();
           const t = f.querySelector(':scope > .lil-title').getBoundingClientRect();
           const ctl = [...f.querySelectorAll(':scope > .lil-children .lil-controller')];
           const last = ctl[ctl.length - 1].getBoundingClientRect();
           return { open: f.querySelector(':scope > .lil-title').getAttribute('aria-expanded'),
                    titleTop: t.top, lastBottom: last.bottom, top: s.top, bottom: s.bottom } }"""
    )
    print("5 reveal", before, vis)
    assert vis["open"] == "true", vis
    assert vis["lastBottom"] <= vis["bottom"] + 0.5, ("opened folder not brought into view", vis)
    assert vis["titleTop"] >= vis["top"] - 0.5, ("scrolled past the folder's title", vis)
    check_column("5 after reveal")

    # 5a. no opening animation (a style that turns transitions off, as reduced
    # motion would): no transitionend comes, and the folder still comes into view
    page.add_style_tag(content=".lil-gui .lil-children { transition: none !important }")
    set_folder("抜き勾配", False)
    page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-gui')].find(g =>
             g.querySelector(':scope > .lil-title').textContent === '抜き勾配');
           const c = document.querySelector('.lil-gui.lil-root > .lil-children');
           c.scrollTop = 0;
           c.scrollTop += f.querySelector(':scope > .lil-title').getBoundingClientRect().bottom - c.getBoundingClientRect().bottom }"""
    )
    settle(100)
    t = page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-gui')].find(g =>
             g.querySelector(':scope > .lil-title').textContent === '抜き勾配');
           const r = f.querySelector(':scope > .lil-title').getBoundingClientRect();
           return [r.left + r.width / 2, r.top + r.height / 2] }"""
    )
    page.mouse.click(*t)
    settle(800)
    vis2 = page.evaluate(
        """() => { const f = [...document.querySelectorAll('.lil-gui .lil-gui')].find(g =>
             g.querySelector(':scope > .lil-title').textContent === '抜き勾配');
           const s = document.querySelector('.lil-gui.lil-root > .lil-children').getBoundingClientRect();
           const ctl = [...f.querySelectorAll(':scope > .lil-children .lil-controller')];
           return { lastBottom: ctl[ctl.length - 1].getBoundingClientRect().bottom, bottom: s.bottom } }"""
    )
    print("5a reveal without animation", vis2)
    assert vis2["lastBottom"] <= vis2["bottom"] + 0.5, ("5a no transition: not brought into view", vis2)

    # 5b. half a screen (767x639), every folder open
    page.set_viewport_size(HALF)
    settle()
    check_column("5b half screen")

    # 6. the × buttons work (a real click, as in the original failure) down to
    # the last entry, on the half-screen window
    for left in range(N_MEASURE, 0, -1):
        btn = page.locator("#measure-list li button").first
        btn.click(timeout=5000)
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length === {left - 1}", timeout=5000)
        settle(100)
        if left > 1:
            check_column(f"6 delete, {left - 1} left")
    assert page.evaluate("document.querySelector('#measure-panel').classList.contains('hidden')")
    settle()
    # with the list gone, the GUI gets its height back (only the volume panel below)
    r6 = rects()
    assert not overlap(r6["gui"], r6["props"]), r6
    assert not overlap(r6["hud"], r6["gui"]) and not overlap(r6["hud"], r6["props"]), r6
    page.screenshot(path="/tmp/cad_viewer_panel_column.png")

    errors += page.evaluate("window.__winErrors")
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("PANEL COLUMN E2E OK")
    browser.close()
