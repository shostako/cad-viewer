"""E2E: thickness heatmap colours that break at the threshold, its legend
(colour bar with mm ticks), and the value under the cursor (#cursor-tip): the
thickness while the heatmap is on, the draft angle while the draft colouring is on.

Expected values never come from the code under test. They come from how the
models are built: testdata/ribbed_plate.stl (make_testdata.py: plate 80x50x2
at z 0..2, ribs 1.2 thick (x -25 / 0 / 25 +-0.6), y +-23, z 2..10, bosses r3
z 2..12 at (+-30, 18)); a taper written here whose thickness is 1 + x/20 under
its flat bottom; the frustum of draft_cases.py with every side wall at 2 deg;
mini_mold.step (make_step_assembly.py: plate top z 15, front wall y 0, core
pin r4 at (75, 30)). Points are projected with window.__cadProject and
confirmed with window.__cadPick; colours are canvas pixels read with toDataURL
inside rAF; the legend's ticks and bar are read from the DOM rects and a page
screenshot of the bar; the thick end is the colour the spec keeps (linear
0.35 / 0.55 / 0.80, sRGB 160 / 196 / 231).

Sidecar requests are answered in the page: no sidecar is written on the backend.
"""
import io
import math
import os
import re
import shutil
import tempfile

from PIL import Image
from playwright.sync_api import sync_playwright

from draft_cases import F_DRAFT, FTOP, XW, YW, frustum_stl
from nav_common import BASE_URL, STEP_SRC, TESTDATA, Nav

STL = str(TESTDATA / "ribbed_plate.stl")
STEP = str(STEP_SRC)
DXF = str(TESTDATA / "plate_drawing.dxf")
SHOTS = "/tmp/cad_viewer_thickness_scale"

RIB_T, PLATE_T = 1.2, 2.0
RIB = (0.6, -10, 6)  # +X side of the middle rib, half way up
RIB2 = (-24.4, -12, 5)  # +X side of the left rib
PLATE = (6, -10, 2)  # plate top between the middle and the right rib
PLATE_LEFT = (-38, -20, 2)  # plate top near its -X edge (in front of the left rib's end: not behind it)

RIBS_X = (-25, 0, 25)


def ribbed_t(q):
    """thickness of the ribbed plate at a surface point: a rib's side (1.2) or the plate's top (2.0); None elsewhere"""
    x, y, z = q
    if abs(y) <= 23 and 2 <= z <= 10 and any(abs(abs(x - rx) - RIB_T / 2) <= 1e-3 for rx in RIBS_X):
        return RIB_T
    if abs(z - PLATE_T) <= 1e-3 and abs(x) <= 40 and abs(y) <= 25:
        return PLATE_T
    return None


# taper: flat bottom z 0 over x 0..40, y 0..20; top z = 1 + x/20. The bottom's
# inner rectangle (x 5..35, y 5..15) is two triangles inside a ring of
# triangles, so its corners touch no other face: their rays (straight up)
# meet the top only, thickness 1 + x/20 exactly, and a point between them
# reads the same law
TAPER_IN = ((5, 5), (35, 15))


def taper_t(x):
    return 1 + x / 20


TAPER_PTS = ((12, 10, 0), (21, 8, 0), (29, 12, 0))

# mini_mold.step
TOP = (90, 10, 15)
FRONT = (50, 0, 7.5)
PIN_DEG = -40  # on the core pin at x 75: between two of its facet columns, not on one
PIN = (75 + 4 * math.cos(math.radians(PIN_DEG)), 30 + 4 * math.sin(math.radians(PIN_DEG)), 30)
PIN_DRAFT_X = math.degrees(math.asin(math.cos(math.radians(PIN_DEG))))  # pull +X: asin(n.x) = 50 deg


def write_stl(path, tris):
    lines = ["solid t"]
    for p in tris:
        lines.append("facet normal 0 0 0\n outer loop")
        lines += [f"  vertex {c[0]!r} {c[1]!r} {c[2]!r}" for c in p]
        lines.append(" endloop\nendfacet")
    lines.append("endsolid t")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def oriented(a, b, c, want):
    """(a, b, c) wound so that (b - a) x (c - a) points along `want`"""
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    return (a, b, c) if sum(n[i] * want[i] for i in range(3)) > 0 else (a, c, b)


def quad(a, b, c, d, want):
    return [oriented(a, b, c, want), oriented(a, c, d, want)]


def taper_stl(path):
    (ix0, iy0), (ix1, iy1) = TAPER_IN
    O = [(0, 0, 0), (40, 0, 0), (40, 20, 0), (0, 20, 0)]
    I = [(ix0, iy0, 0), (ix1, iy0, 0), (ix1, iy1, 0), (ix0, iy1, 0)]
    T = [(x, y, taper_t(x)) for x, y, _ in O]
    down = (0, 0, -1)
    tris = quad(*I, down)
    for k in range(4):
        tris += quad(O[k], O[(k + 1) % 4], I[(k + 1) % 4], I[k], down)
    tris += quad(*T, (-1 / 20, 0, 1))
    tris += quad(O[0], O[3], T[3], T[0], (-1, 0, 0))
    tris += quad(O[1], O[2], T[2], T[1], (1, 0, 0))
    tris += quad(O[0], O[1], T[1], T[0], (0, -1, 0))
    tris += quad(O[3], O[2], T[2], T[3], (0, 1, 0))
    write_stl(path, tris)


def red_side(c):
    """hot (below the threshold): red clearly above green and blue (lighting changes brightness, not the order)"""
    return c[0] >= 80 and c[0] >= 1.6 * max(c[1], c[2])


def blue_side(c):
    """cool (at or above the threshold): blue clearly above red, and not below green"""
    return c[2] >= c[0] + 15 and c[2] >= c[1]


def number(text, unit):
    m = re.fullmatch(r"([−-]?\d+\.\d+) ?" + re.escape(unit), text)
    assert m, ("tip text", text, unit)
    return float(m.group(1).replace("−", "-"))


def main():
    tmp = tempfile.mkdtemp(prefix="cad_thick_")
    try:
        TAPER = os.path.join(tmp, "taper.stl")
        taper_stl(TAPER)
        FRUSTUM = os.path.join(tmp, "frustum.stl")
        frustum_stl(FRUSTUM)
        INSIDE_OUT = os.path.join(tmp, "frustum_inside_out.stl")
        frustum_stl(INSIDE_OUT, inside_out=True)
        # draft_cases.py uploads the same frustums under other names, and the
        # backend answers the same bytes with the first upload's name (the HUD
        # shows that): two trailing newlines give these their own
        for path in (FRUSTUM, INSIDE_OUT):
            with open(path, "a") as f:
                f.write("\n\n")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            nav = Nav(page, {})
            page.on("pageerror", lambda e: nav.errors.append(str(e)))
            page.on("console", lambda m: nav.errors.append(m.text) if m.type == "error" else None)
            # sidecars stay in the page (from before the first load)
            page.route(
                "**/sidecar",
                lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {}),
            )
            page.goto(BASE_URL)
            page.evaluate("localStorage.removeItem('cad-viewer:view'); localStorage.removeItem('cad-viewer:draft')")
            page.reload()
            page.wait_for_load_state("networkidle")
            # the floor grid lies in the plane of the bottom faces (the taper is read from below)
            nav.ctl("グリッド").locator("input").click()
            run(page, nav, TAPER, FRUSTUM, INSIDE_OUT)
            page.evaluate("localStorage.removeItem('cad-viewer:view'); localStorage.removeItem('cad-viewer:draft')")
            if nav.errors:
                print("PAGE ERRORS:", nav.errors)
            assert not nav.errors
            browser.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("E2E OK")


def run(page, nav, TAPER, FRUSTUM, INSIDE_OUT):
    settle, project, pick, ctl = nav.settle, nav.project, nav.pick, nav.ctl

    # ---- helpers ------------------------------------------------------------
    def open_folder(name):
        title = page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$")).first
        if title.get_attribute("aria-expanded") != "true":
            title.click()
            nav.wait_gui_idle()

    def box(name):
        return ctl(name).locator("input")

    def toggle(name, on):
        if box(name).evaluate("e => e.checked") != on:
            box(name).click()
        settle()

    def toggle_in_place(name, on):
        """tick or untick by a DOM click: the mouse stays where it is"""
        if box(name).evaluate("e => e.checked") != on:
            box(name).evaluate("e => e.click()")
        settle()

    def set_threshold(v):
        inp = ctl("閾値").locator("input")
        inp.fill(str(v))
        inp.press("Enter")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        settle()

    def set_select(name, label):
        ctl(name).locator("select").select_option(label=label)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        settle()

    def heat_on():
        toggle("ヒートマップ", True)
        page.wait_for_function(
            "document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=60000
        )
        settle()

    def on_face(xyz, tol=0.3):
        """xyz is on the canvas and the first surface the eye meets there; its screen point"""
        xy = project(xyz)
        cl, ct, cw, ch = nav.canvas_rect()
        assert cl + 4 <= xy[0] <= cl + cw - 4 and ct + 4 <= xy[1] <= ct + ch - 4, ("off the canvas", xyz, xy)
        hit = pick(xy)
        assert hit and math.dist(hit["point"], xyz) <= tol, ("not on screen", xyz, hit)
        return xy

    def colours(pts):
        """median colour of a 5x5 patch of canvas pixels around each point's projection"""
        img = nav.canvas_image()
        cl, ct, cw, ch = nav.canvas_rect()
        out = {}
        for k, xyz in pts.items():
            x, y = on_face(xyz)
            cx, cy = int((x - cl) * img.width / cw), int((y - ct) * img.height / ch)
            patch = [img.getpixel((cx + dx, cy + dy)) for dx in range(-2, 3) for dy in range(-2, 3)]
            out[k] = tuple(sorted(q[i] for q in patch)[12] for i in range(3))
        return out

    def tip():
        """(shown, text, rect) of the label beside the cursor"""
        return page.evaluate(
            """(() => { const e = document.querySelector('#cursor-tip')
                 if (!e) return [false, '', null]
                 const r = e.getBoundingClientRect()
                 return [getComputedStyle(e).display !== 'none' && r.width > 0, e.textContent, [r.left, r.top, r.right, r.bottom]] })()"""
        )

    def hover(xy):
        page.mouse.move(*xy)
        settle()
        return tip()

    def tip_value(xyz, unit="mm"):
        """hover the projection of xyz (confirmed on screen): the number on the tip"""
        xy = on_face(xyz)
        shown, text, rect = hover(xy)
        assert shown, ("no tip over the model", xyz, text)
        # beside the cursor (right and below, away from the window's edges), and never in the way
        assert 0 <= rect[0] - xy[0] <= 40 and 0 <= rect[1] - xy[1] <= 40, ("tip not beside the cursor", xy, rect)
        under = page.evaluate(
            "([x, y]) => document.elementFromPoint(x, y)?.id ?? ''", [(rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2]
        )
        assert under != "cursor-tip", "the tip takes the pointer"
        return number(text, unit) if unit else text

    def assert_hidden(tag):
        shown, text, _ = tip()
        assert not shown, (tag, "tip still shown", text)

    def legend_shown():
        return page.locator("#thickness-legend").is_visible()

    def check_legend(threshold, method):
        assert legend_shown(), "legend missing with the heatmap on"
        text = page.inner_text("#thickness-legend")
        assert method in text, ("method on the legend", method, text)
        info = page.evaluate(
            """(() => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom] }
                 return { bar: r(document.querySelector('#thickness-legend .thick-bar')),
                          ticks: [...document.querySelectorAll('#thickness-legend .thick-tick')].map(e => [e.textContent, r(e)]) } })()"""
        )
        bar = info["bar"]
        ticks = info["ticks"]
        want = ["0", f"{threshold:.1f}", f"{2 * threshold:.1f} mm"]
        assert [t for t, _ in ticks] == want, ("ticks", [t for t, _ in ticks], want)
        (_, t0), (_, t1), (_, t2) = ticks
        mid = (bar[0] + bar[2]) / 2
        assert abs(t0[0] - bar[0]) <= 2, ("0 at the bar's left end", t0, bar)
        assert abs((t1[0] + t1[2]) / 2 - mid) <= 2, ("threshold tick at the middle", t1, bar)
        assert abs(t2[2] - bar[2]) <= 2, ("2x threshold at the bar's right end", t2, bar)
        assert t0[1] >= bar[3] - 1 and t1[1] >= bar[3] - 1, ("ticks under the bar", ticks, bar)
        # the bar's colours, as painted: hot up to the threshold tick, cool from it
        clip = {"x": bar[0], "y": bar[1], "width": bar[2] - bar[0], "height": bar[3] - bar[1]}
        img = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")
        row = img.height // 2
        cols = [img.getpixel((x, row)) for x in range(img.width)]
        w = img.width
        for f in (0.03, 0.25, 0.45):
            assert red_side(cols[int(f * w)]), ("hot part of the bar", f, cols[int(f * w)])
        for f in (0.55, 0.75, 0.97):
            assert blue_side(cols[int(f * w)]), ("cool part of the bar", f, cols[int(f * w)])
        # columns 0 and w - 1 are the bar's border over the HUD's bluish background
        first_cool = next(x for x in range(2, w - 2) if blue_side(cols[x]))
        assert all(red_side(c) for c in cols[2:first_cool - 1]), "the hot part must be hot all the way to the break"
        assert all(blue_side(c) for c in cols[first_cool + 1 : w - 2]), "the cool part must be cool all the way"
        assert abs(bar[0] + first_cool - (t1[0] + t1[2]) / 2) <= 2, ("break at the threshold tick", first_cool, t1, bar)
        end = cols[w - 3]
        assert all(abs(a - b) <= 6 for a, b in zip(end, (160, 196, 231))), ("thick end of the bar", end)
        return text

    # ================= (a) ribbed plate, heatmap at 1.5 mm =======================
    nav.load(STL)
    open_folder("肉厚")
    assert not legend_shown(), "legend before the heatmap"
    xy = on_face(RIB)
    assert not hover(xy)[0], "a tip without a colouring"
    set_threshold(1.5)
    heat_on()
    c = colours({"RIB": RIB, "RIB2": RIB2, "PLATE": PLATE})
    print("(a) 1.5 mm:", c)
    assert red_side(c["RIB"]) and red_side(c["RIB2"]), ("a 1.2 mm rib under 1.5 must be red", c)
    assert blue_side(c["PLATE"]), ("the 2.0 mm plate over 1.5 must be on the blue side", c)
    text = check_legend(1.5, "レイ法")
    print("(a) legend:", text.replace("\n", " / "))
    hud = page.inner_text("#hud-info")
    assert hud.startswith("肉厚ヒートマップ表示中（レイ法"), hud
    page.screenshot(path=SHOTS + "_a.png")

    # the value under the cursor
    v_rib, v_rib2, v_plate = tip_value(RIB), tip_value(RIB2), tip_value(PLATE)
    print("(a) tip rib / rib / plate:", v_rib, v_rib2, v_plate)
    assert abs(v_rib - RIB_T) <= 0.05 and abs(v_rib2 - RIB_T) <= 0.05, (v_rib, v_rib2)
    assert abs(v_plate - PLATE_T) <= 0.05, v_plate

    # off the model (background beside the plate's -X edge): no tip
    edge = on_face(PLATE_LEFT)
    off = (edge[0] - 60, edge[1])
    assert pick(off) is None, ("not background", off, pick(off))
    hover(off)
    assert_hidden("off the model")
    # and back
    assert abs(tip_value(PLATE) - PLATE_T) <= 0.05
    # onto a panel (the cursor leaves the 3D view): no tip
    gui = page.locator(".lil-gui.lil-root > .lil-title").bounding_box()
    hover((gui["x"] + 20, gui["y"] + gui["height"] / 2))
    assert_hidden("over the control panel")

    # the view moves under a still cursor (keys): the tip follows what is under it
    edge = on_face(PLATE_LEFT)
    still = (edge[0] - 50, edge[1])
    assert pick(still) is None, ("not background", still)
    hover(still)
    assert_hidden("background before the pan")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Shift+ArrowRight")  # the camera slides right: the model moves left on screen
    settle()
    settle()
    hit = pick(still)
    want = hit and ribbed_t(hit["point"])
    assert want, ("a rib's side or the plate's top under the cursor now", hit)
    shown, text, _ = tip()
    print("(a) after the pan, without a move:", shown, text, "on", [round(v, 2) for v in hit["point"]])
    assert shown and abs(number(text, "mm") - want) <= 0.05, ("the tip must follow the view", shown, text, want)
    page.keyboard.press("f")  # back to a fit (same direction)
    settle()

    # a wheel turn hides it until the cursor moves again
    xy = on_face(PLATE)
    hover(xy)
    assert tip()[0]
    page.mouse.wheel(0, -100)
    settle()
    assert_hidden("after a wheel turn")
    hover((xy[0] + 1, xy[1]))
    shown, text, _ = tip()
    assert shown and abs(number(text, "mm") - PLATE_T) <= 0.05, ("the point under the cursor stays with a wheel zoom", text)
    page.keyboard.press("f")
    settle()

    # a press and a drag (turns the view) hide it; it comes back with the next move
    xy = on_face(RIB)
    hover(xy)
    assert tip()[0]
    page.mouse.down()
    settle()
    assert_hidden("button down")
    page.mouse.move(xy[0] + 15, xy[1] + 4, steps=5)
    settle()
    assert_hidden("dragging")
    page.mouse.up()
    settle()
    assert_hidden("released, not moved yet")
    page.wait_for_timeout(400)  # the coast of the drag
    xy = on_face(RIB)
    assert abs(tip_value(RIB) - RIB_T) <= 0.05

    # ================= (b) threshold 1.0: the 1.2 mm rib turns cool =================
    set_threshold(1.0)
    c = colours({"RIB": RIB, "RIB2": RIB2, "PLATE": PLATE})
    print("(b) 1.0 mm:", c)
    assert blue_side(c["RIB"]) and blue_side(c["RIB2"]), ("a 1.2 mm rib over 1.0 must be on the blue side", c)
    assert blue_side(c["PLATE"]), c
    check_legend(1.0, "レイ法")
    # the method on the legend follows the 方式
    set_select("方式", "ローリングボール法")
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中（ローリングボール法')",
        timeout=120000,
    )
    settle()
    check_legend(1.0, "ローリングボール法")
    set_select("方式", "レイ法")
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中（レイ法')", timeout=60000
    )
    set_threshold(1.5)
    check_legend(1.5, "レイ法")

    # heatmap off with the cursor on the model (not moved): tip and legend go.
    # A fit first ends the coast of the drag above: while the view moves, the
    # tip looks again by itself, and this would not test the switch
    page.keyboard.press("f")
    settle()
    xy = on_face(RIB)
    assert abs(tip_value(RIB) - RIB_T) <= 0.05
    toggle_in_place("ヒートマップ", False)
    assert_hidden("heatmap off")
    assert not legend_shown(), "legend after the heatmap went off"
    page.mouse.move(xy[0] + 1, xy[1])
    settle()
    assert_hidden("no colouring: no tip")

    # ================= (c) taper: the value is blended inside a triangle ==========
    nav.load(TAPER)
    nav.click_button("下")
    page.keyboard.press("f")
    settle()
    heat_on()
    for q in TAPER_PTS:
        xy = on_face(q)
        got = tip_value(q)
        at = pick(xy)["point"]
        want = taper_t(at[0])
        print("(c) taper at", [round(v, 2) for v in at], "tip", got, "want", round(want, 3))
        assert abs(got - want) <= 0.05, ("thickness between the vertices", at, got, want)
    toggle("ヒートマップ", False)

    # ================= (d) draft angle under the cursor ===========================
    # ribbed plate (mesh format, per triangle): walls 0, the top 90, signs with the direction
    nav.load(STL)
    open_folder("抜き勾配")
    set_select("型開き方向", "+Z")
    req = ctl("必要な勾配").locator("input")
    req.fill("1")
    req.press("Enter")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    toggle("色分け", True)
    assert page.locator("#draft-legend").is_visible() and not legend_shown()

    def draft(xyz):
        text = tip_value(xyz, unit=None)
        m = re.fullmatch(r"勾配 ([−-]?\d+\.\d)°（(抜ける側|勾配不足|反対側)）", text)
        assert m, ("draft tip text", text)
        return float(m.group(1).replace("−", "-")), m.group(2)

    got = {"RIB": draft(RIB), "PLATE": draft(PLATE)}
    print("(d) ribbed plate +Z:", got)
    assert got["RIB"] == (0.0, "勾配不足"), got
    assert got["PLATE"] == (90.0, "抜ける側"), got
    set_select("型開き方向", "−Z")
    got = {"RIB": draft(RIB), "PLATE": draft(PLATE)}
    print("(d) ribbed plate −Z:", got)
    assert got["RIB"] == (0.0, "勾配不足") and got["PLATE"] == (-90.0, "反対側"), got
    set_select("型開き方向", "+X")
    assert draft(RIB) == (90.0, "抜ける側"), "the rib's +X side faces +X"
    # off the model and draft off (cursor still): no tip
    edge = on_face(PLATE_LEFT)
    hover((edge[0] - 60, edge[1]))
    assert_hidden("draft: off the model")
    page.keyboard.press("f")  # a still view, as for the heatmap above
    settle()
    xy = on_face(PLATE)
    hover(xy)
    assert tip()[0]
    toggle_in_place("色分け", False)
    assert_hidden("draft off")
    # the frustum (2 deg walls), and the same frustum wound inside out: same readings
    for path in (FRUSTUM, INSIDE_OUT):
        nav.load(path)
        set_select("型開き方向", "+Z")
        toggle("色分け", True)
        got = {k: draft(q) for k, q in {"XW": XW, "YW": YW, "FTOP": FTOP}.items()}
        print("(d)", os.path.basename(path), "+Z:", got)
        want = (F_DRAFT, "抜ける側")
        assert got["XW"] == want and got["YW"] == want and got["FTOP"] == (90.0, "抜ける側"), got
        set_select("型開き方向", "−Z")
        got = {k: draft(q) for k, q in {"XW": XW, "FTOP": FTOP}.items()}
        print("(d)", os.path.basename(path), "−Z:", got)
        assert got["XW"] == (-F_DRAFT, "反対側") and got["FTOP"] == (-90.0, "反対側"), got
        toggle("色分け", False)
    # mini_mold (B-rep: display normals blended across the triangle)
    nav.load(STEP)
    set_select("型開き方向", "+Z")
    toggle("色分け", True)
    got = {"TOP": draft(TOP), "FRONT": draft(FRONT)}
    print("(d) mini_mold +Z:", got)
    assert got["TOP"] == (90.0, "抜ける側") and got["FRONT"] == (0.0, "勾配不足"), got
    set_select("型開き方向", "+X")
    a, cls = draft(PIN)
    print("(d) mini_mold +X, pin at", PIN_DEG, "deg:", a, cls, "want", round(PIN_DRAFT_X, 2))
    assert abs(a - PIN_DRAFT_X) <= 1.5 and cls == "抜ける側", (a, cls)
    page.screenshot(path=SHOTS + "_d.png")
    toggle("色分け", False)
    set_select("型開き方向", "+Z")

    # ================= (e) the heatmap takes over from the draft; drawings =========
    open_folder("肉厚")
    toggle("色分け", True)
    heat_on()
    assert legend_shown() and not page.locator("#draft-legend").is_visible()
    check_legend(1.5, "レイ法")
    toggle("色分け", True)  # the draft takes over: the heatmap's legend goes
    assert not legend_shown(), "thickness legend under the draft colouring"
    toggle("色分け", False)
    heat_on()
    nav.load(DXF, wait_text="2D図面")
    assert not legend_shown(), "legend on a drawing"
    assert_hidden("drawing")
    nav.load(STL)
    assert not legend_shown(), "a new model opens without the heatmap"
    hover(on_face(RIB))
    assert_hidden("a new model opens without the heatmap")


if __name__ == "__main__":
    main()
