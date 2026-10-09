"""E2E: the axis triad in the bottom-left corner (#8 A3).

Expected values never come from the triad's code: the screen directions of the
world axes come from window.__cadProject, the views from the 視点 buttons
(compared through __cadView), the layout from DOM rectangles and the
browser's own hit test (document.elementFromPoint), colours from a page
screenshot and the export from the frame on screen (canvas toDataURL).

Sidecars stay in the page (Nav.stub_sidecar): this script makes measures and
counts the list.

R1 shown only with a 3D model (the HUD moves right of it); R2 clear of the
other corner UI at every window size; R3 follows the camera; R4 the nearer
end is on top; R5 a click sets the same view as the 視点 button; R6 clicks
never reach the model (measure, note, pivot), a wheel over a disc zooms;
R7 not in the PNG export, axis colours; R8 hover.
"""
import io
import math
import re

import numpy as np
from PIL import Image

from nav_common import DXF, STEP_SRC, add, close, mul, nav_session

# the shared mini_mold.step: this script keeps sidecars in the page (stub_sidecar)
STEP = str(STEP_SRC)

CAV_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)
ENDS = {"+X": "右", "-X": "左", "+Y": "背面", "-Y": "正面", "+Z": "上", "-Z": "下"}
AXES = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}
COLOURS = {"X": (0xE5, 0x53, 0x4B), "Y": (0x57, 0xB8, 0x5A), "Z": (0x4D, 0x86, 0xF0)}
SIZES = ((767, 639), (1280, 560), (1280, 700), (1920, 1080))
FOLDERS = ("表示", "断面", "肉厚", "抜き勾配", "体積・重量")


def overlap(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
    ctl, set_mode, set_rotate, set_projection = n.ctl, n.set_mode, n.set_rotate, n.set_projection

    def blur():
        page.evaluate("document.activeElement && document.activeElement.blur()")

    def press(name):
        """a GUI button by a DOM click: the same handler as a mouse click,
        without Playwright's wait for a still element (headless frames of a
        close-up take ~100 ms, and this script presses buttons ~150 times)"""
        ctl(name).locator("button").evaluate("b => b.click()")
        settle()

    def box(sel):
        b = page.locator(sel).bounding_box() if page.locator(sel).count() else None
        return b

    def rects():
        return page.evaluate(
            """() => { const q = s => { const e = document.querySelector(s);
                 if (!e || !e.getClientRects().length) return null;
                 const r = e.getBoundingClientRect(); return {left: r.left, top: r.top, right: r.right, bottom: r.bottom} };
               return { triad: q('#triad'), hud: q('#hud'), tree: q('#tree-panel'), gui: q('.lil-gui.lil-root'),
                        measure: q('#measure-panel'), props: q('#props-panel'), w: innerWidth, h: innerHeight } }"""
        )

    def disc(end):
        """page coordinates of the disc of an axis end"""
        r = page.evaluate(
            """a => { const r = document.querySelector(`#triad .triad-end[data-axis="${a}"] circle`).getBoundingClientRect();
                 return [r.left + r.width / 2, r.top + r.height / 2] }""",
            end,
        )
        return tuple(r)

    def svg_centre():
        r = page.evaluate(
            "(() => { const r = document.querySelector('#triad svg').getBoundingClientRect();"
            " return [r.left + r.width / 2, r.top + r.height / 2] })()"
        )
        return tuple(r)

    def hit_end(xy):
        """data-axis of the triad end the browser hits at xy (or what it hits instead)"""
        return page.evaluate(
            """([x, y]) => { const e = document.elementFromPoint(x, y); if (!e) return null;
                 const g = e.closest('.triad-end'); return g ? g.dataset.axis : (e.id || e.tagName) }""",
            list(xy),
        )

    def same_view(a, b, tol=1e-9):
        scale = max(1.0, max(abs(x) for x in a["position"]))
        assert close(a["position"], b["position"], tol * scale), (a["position"], b["position"])
        assert close(a["target"], b["target"], tol * scale), (a["target"], b["target"])
        assert close(a["up"], b["up"], tol), (a["up"], b["up"])

    def triad_visible():
        return page.locator("#triad").is_visible()

    # ---- R1. shown only with a 3D model; the HUD moves right of it ----------------
    assert box("#triad") is None, "no triad on the empty screen"
    assert box("#hud")["x"] == 12, box("#hud")
    load(STEP)
    assert triad_visible() and box("#hud")["x"] == 108, (box("#triad"), box("#hud"))
    load(DXF, wait_text="2D図面")
    assert not triad_visible() and box("#hud")["x"] == 12, "hidden on a drawing"
    load(STEP)
    assert triad_visible()
    page.route("**/mesh.bin", lambda r: r.abort())
    try:
        page.set_input_files("#file-input", STEP)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
    finally:
        page.unroute("**/mesh.bin")
    assert not triad_visible() and box("#hud")["x"] == 12, "hidden after a failed load"
    load(STEP)
    assert triad_visible()
    print("R1 ok")

    # ---- R2. clear of the corner UI at every size ---------------------------------------
    page.wait_for_function("!document.querySelector('#props-panel').classList.contains('hidden')", timeout=60000)
    set_mode("計測")
    # each click waits for the last one's answer: a click while a measure is
    # still in flight is dropped (MeasureTool.busy), and the shared backend
    # can be slow
    for k in range(2):
        page.mouse.click(*project(CAV_TOP))
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
        page.mouse.click(*project(PLATE_TOP))
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length >= {k + 1}", timeout=10000)
    set_mode("なし")
    page.locator(".lil-gui .lil-title", has_text=re.compile("^抜き勾配$")).click()
    ctl("色分け").locator("input").click()
    page.locator(".lil-gui .lil-title", has_text=re.compile("^抜き勾配$")).click()
    assert page.locator("#draft-legend").is_visible()
    # a long tree (60 rows): the panel grows to its 60vh cap; copies of a real row
    page.evaluate(
        """() => { const ul = document.querySelector('#tree-body ul'); const li = ul.lastElementChild;
             for (let i = ul.querySelectorAll('li').length; i < 60; i++) ul.appendChild(li.cloneNode(true)) }"""
    )

    def check_layout(tag):
        page.wait_for_timeout(450)  # lil-gui's folder animation; the column settles a frame later
        settle()
        r = rects()
        t = r["triad"]
        assert t, (tag, "triad hidden")
        assert t["left"] >= 0 and t["top"] >= 0 and t["right"] <= r["w"] and t["bottom"] <= r["h"], (tag, r)
        for k in ("hud", "tree", "gui", "measure", "props"):
            assert r[k], (tag, k, "not shown")
            assert not overlap(t, r[k]), (tag, "triad under", k, t, r[k])
        assert not overlap(r["hud"], r["tree"]), (tag, "hud under the tree", r["hud"], r["tree"])
        print("R2", tag, {k: (round(v["left"]), round(v["top"]), round(v["right"]), round(v["bottom"]))
                          for k, v in r.items() if isinstance(v, dict)})

    for w, h in SIZES:
        page.set_viewport_size({"width": w, "height": h})
        check_layout(f"{w}x{h}")
    page.set_viewport_size({"width": 767, "height": 639})
    for name in FOLDERS:
        title = page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$"))
        if title.get_attribute("aria-expanded") != "true":
            title.click()
    check_layout("767x639 all open")
    for name in FOLDERS[1:]:
        page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$")).click()
    # the rest at the user's own size (half a 1536x816 screen): the triad's
    # corner is the tightest there, and smaller frames keep the script short
    page.set_viewport_size({"width": 767, "height": 639})
    page.wait_for_timeout(300)
    press("計測クリア")
    ctl("色分け").locator("input").evaluate("e => e.checked && e.click()")
    # in 等角 no two discs overlap: each disc's centre hits that disc
    press("等角")
    settle()
    for end in ENDS:
        assert hit_end(disc(end)) == end, ("R2 hit test", end, hit_end(disc(end)))
    print("R2 ok")

    # ---- R3. follows the camera ---------------------------------------------------------
    def check_follow(tag):
        settle()
        t = view()["target"]
        p0 = project(t)
        c = svg_centre()
        vs = {}
        for a, d in AXES.items():
            q = project(add(t, mul(d, 0.1)))
            vs[a] = (q[0] - p0[0], q[1] - p0[1])
        vmax = max(math.hypot(*v) for v in vs.values())
        for a, v in vs.items():
            up_, um = disc("+" + a), disc("-" + a)
            u = (up_[0] - c[0], up_[1] - c[1])
            assert math.dist(um, (c[0] - u[0], c[1] - u[1])) <= 1.5, (tag, a, "negative end", um, u, c)
            if math.hypot(*v) <= 0.2 * vmax:
                continue  # nearly along the view: its direction on screen is noise
            ang = math.degrees(abs(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])))
            assert ang <= 3, (tag, a, "direction", ang, u, v)
        print("R3", tag, "ok")

    press("等角")
    check_follow("等角")
    page.mouse.click(350, 20)  # focus the page (empty canvas between the tree and the GUI)
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    for _ in range(2):
        page.keyboard.press("ArrowUp")
    check_follow("turntable keys")
    n.setup_view("自由回転")
    check_follow("free rolled")
    set_rotate("ターンテーブル")
    set_projection("平行")
    press("等角")
    check_follow("parallel 等角")
    set_projection("透視")

    # ---- R4. the nearer end is drawn on top ------------------------------------------
    for preset, end in (("上", "+Z"), ("下", "-Z"), ("正面", "-Y")):
        press(preset)
        settle()
        assert hit_end(svg_centre()) == end, ("R4", preset, hit_end(svg_centre()))
    print("R4 ok")

    # ---- R5. a click sets the same view as the 視点 button ------------------------------
    def check_clicks(tag):
        for end, button in ENDS.items():
            press("等角")
            page.mouse.click(*disc(end))
            settle()
            by_click = view()
            press("等角")
            press(button)
            by_button = view()
            same_view(by_click, by_button)
        print("R5", tag, "ok")

    check_clicks("turntable")
    set_rotate("自由回転")
    check_clicks("free")
    set_projection("平行")
    check_clicks("free parallel")
    set_projection("透視")
    set_rotate("ターンテーブル")

    # ---- R6. clicks never reach the model ----------------------------------------------
    press("等角")
    page.keyboard.press("f")
    for i in range(60):
        if all(pick(disc(e)) for e in ENDS):
            break
        page.keyboard.press("+")
    else:
        raise AssertionError("R6 the model never covered the triad")
    pose = view()

    def back_to_pose(end):
        press("等角")
        same_view(view(), pose)
        assert pick(disc(end)), ("R6 guard: the model is under the disc", end)

    set_mode("計測")
    count = page.locator("#measure-list li").count()
    for end in ENDS:
        back_to_pose(end)
        page.mouse.click(*disc(end))
        page.wait_for_timeout(150)
        assert page.locator("#measure-list li").count() == count, ("R6 measure", end)
        assert "相手をクリック" not in page.text_content("#hud-info"), ("R6 pending measure", end)
    set_mode("注記")
    for end in ENDS:
        back_to_pose(end)
        page.mouse.click(*disc(end))
        page.wait_for_timeout(150)
        assert page.locator(".note-input").count() == 0, ("R6 note", end)
    set_mode("なし")
    for end in ENDS:
        back_to_pose(end)
        t0 = view()["target"]
        page.mouse.dblclick(*disc(end))
        page.wait_for_timeout(150)
        assert n.marker_rect() is None, ("R6 pivot marker", end)
        assert close(view()["target"], t0, 1e-9), ("R6 pivot moved the target", end)
    back_to_pose("+X")
    k0 = n.kscale()
    n.wheel(disc("+X"), -100)
    k1 = n.kscale()
    assert abs(k1 / k0 - 1 / 0.9) <= 1e-6, ("R6 wheel over a disc", k1 / k0)
    print("R6 ok")

    # ---- R7. not in the PNG export; the axis colours -------------------------------------
    page.keyboard.press("f")
    press("等角")
    page.mouse.move(350, 20)
    settle()
    t = box("#triad")
    screen = np.asarray(n.canvas_image()).astype(int)
    with page.expect_download(timeout=15000) as info:
        ctl("画像を保存").locator("button").click()
    out = np.asarray(Image.open(info.value.path()).convert("RGB")).astype(int)
    assert out.shape == screen.shape, (out.shape, screen.shape)
    x0, y0, x1, y1 = int(t["x"]), int(t["y"]), int(t["x"] + t["width"]), int(t["y"] + t["height"])
    diff = np.abs(out[y0:y1, x0:x1] - screen[y0:y1, x0:x1]).max()
    assert diff <= 3, ("R7 the triad is in the export", diff)
    shot = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB")).astype(int)
    yy, xx = np.mgrid[0 : shot.shape[0], 0 : shot.shape[1]]
    for a, colour in COLOURS.items():
        cx, cy = disc("+" + a)
        near = (xx - cx) ** 2 + (yy - cy) ** 2 <= 49
        px = shot[near]
        px = px[px.min(axis=1) < 200]  # the white letter out
        med = np.median(px, axis=0)
        assert np.abs(med - np.array(colour)).max() <= 40, ("R7 colour", a, med, colour)
    print("R7 ok")

    # ---- R8. hover ------------------------------------------------------------------------
    page.mouse.move(*disc("+X"))
    page.wait_for_timeout(100)
    stroke = page.evaluate(
        "getComputedStyle(document.querySelector('#triad .triad-end[data-axis=\"+X\"] circle')).stroke"
    )
    assert stroke == "rgb(255, 255, 255)", ("R8 hover", stroke)
    page.mouse.move(350, 20)

    page.screenshot(path="/tmp/cad_viewer_triad.png")
    # the aborted mesh request of R1
    n.errors[:] = [e for e in n.errors if "Failed to load resource" not in e]
    print("TRIAD E2E OK")
