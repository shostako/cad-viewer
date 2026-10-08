"""E2E: draft-angle colouring (抜き勾配, C2).

Expected classes never come from the code under test. They come from how the
models are built: mini_mold.step (make_step_assembly.py: plate 100x60x15 with
+Z top, -Z bottom and vertical walls; pins r4 at x 25/75; cavity block
30..70 x 15..45 x 15..35) and a frustum STL written here whose four side walls
lean exactly 2 deg. The colour on screen is read from the canvas pixels at
projected points (window.__cadProject) that the picker confirms are on the
expected face (window.__cadPick). Lighting shades the class colours, so a
pixel is classified by its dominant channel: green = 抜ける側, red = 勾配不足,
blue = 反対側, anything greyish = neutral (part colours, cap, background).

Steps: (a) mini_mold: classes, section, direction, 0 deg, off, bottom view,
free rotation + keyboard, hidden part; (b) frustum: all six pull directions and
the 2 deg boundary; (c) mutual exclusion with the thickness heatmap, including
a held and an aborted thickness request; (d) hidden on a drawing, reset on
reload; (e) remembered direction / angle, bad stored values.
"""
import base64
import io
import math
import os
import re
import shutil
import tempfile

from PIL import Image

from nav_common import DXF, STEP, SURFACE, cross, nav_session, norm, sub

DRAFT_KEY = "cad-viewer:draft"
THICK_RE = re.compile(r"/thickness\.bin")

# ---- sample points (make_step_assembly.py), all seen from the load view ------
TOP = SURFACE  # (90, 10, 15) plate top, normal +Z
TOP2 = (10, 8, 15)  # plate top on the other side of the X 0.5 cut
FRONT = (50, 0, 7.5)  # plate wall, normal -Y
RIGHT = (100, 30, 7.5)  # plate wall, normal +X
CAV_FRONT = (50, 15, 25)  # cavity block wall, normal -Y
PIN2_SIDE = (75 + 4 * math.cos(math.radians(-45)), 30 + 4 * math.sin(math.radians(-45)), 30)  # pin at x 75
CUT = (50, 30, 7.5)  # on the X 0.5 section plane, inside the plate
BOTTOM = (20, 45, 0)  # plate bottom, normal -Z (seen from the 下 view)
PLATE_PTS = {"TOP": TOP, "TOP2": TOP2, "FRONT": FRONT, "RIGHT": RIGHT}
ALL_PTS = {**PLATE_PTS, "CAV_FRONT": CAV_FRONT, "PIN2_SIDE": PIN2_SIDE}

# ---- frustum: square base +-20 at z 0, height 20, every side wall at 2 deg ----
F_HALF, F_H, F_DRAFT = 20.0, 20.0, 2.0
F_TOPHALF = F_HALF - F_H * math.tan(math.radians(F_DRAFT))
FTOP = (0.0, 0.0, F_H)
XW = (F_HALF - (F_H / 2) * math.tan(math.radians(F_DRAFT)), 0.0, F_H / 2)  # +X wall
YW = (0.0, -(F_HALF - (F_H / 2) * math.tan(math.radians(F_DRAFT))), F_H / 2)  # -Y wall
F_PTS = {"FTOP": FTOP, "XW": XW, "YW": YW}
# with required 1 deg: n.d is 1 (top), sin 2 deg (walls along the pull),
# cos 2 deg (wall facing the pull axis) or 0; signs flip with the direction
SIX = {
    "+Z": {"FTOP": "ok", "XW": "ok", "YW": "ok"},
    "−Z": {"FTOP": "opposite", "XW": "opposite", "YW": "opposite"},
    "+X": {"FTOP": "short", "XW": "ok", "YW": "short"},
    "−X": {"FTOP": "short", "XW": "opposite", "YW": "short"},
    "+Y": {"FTOP": "short", "XW": "short", "YW": "opposite"},
    "−Y": {"FTOP": "short", "XW": "short", "YW": "ok"},
}


def frustum_stl(path):
    """ASCII STL of the frustum: quads as nav_common.box_stl, normals from the winding"""
    a, b = F_HALF, F_TOPHALF
    v = [(-a, -a, 0.0), (a, -a, 0.0), (a, a, 0.0), (-a, a, 0.0), (-b, -b, F_H), (b, -b, F_H), (b, b, F_H), (-b, b, F_H)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    lines = ["solid frustum"]
    for q in quads:
        for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            p = [v[i] for i in tri]
            n = norm(cross(sub(p[1], p[0]), sub(p[2], p[0])))
            lines.append(f"facet normal {n[0]!r} {n[1]!r} {n[2]!r}\n outer loop")
            lines += [f"  vertex {c[0]!r} {c[1]!r} {c[2]!r}" for c in p]
            lines.append(" endloop\nendfacet")
    lines.append("endsolid frustum")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def cls(rgb):
    """class of a rendered pixel by its dominant channel (lighting changes brightness, not the dominant hue)"""
    order = sorted(range(3), key=lambda k: rgb[k], reverse=True)
    top, second = rgb[order[0]], rgb[order[1]]
    if top >= 60 and top >= 1.6 * max(second, 1):
        return ("short", "ok", "opposite")[order[0]]
    return "neutral"


def same(a, b, tol=4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


tmp = tempfile.mkdtemp(prefix="cad_draft_")
try:
    FRUSTUM = os.path.join(tmp, "draft_frustum.stl")
    frustum_stl(FRUSTUM)

    with nav_session() as nav:
        page = nav.page
        settle, project, pick, ctl, click_button = nav.settle, nav.project, nav.pick, nav.ctl, nav.click_button
        # The shared backend may hold measure markers on mini_mold from other
        # runs; they would be drawn over the sample points.
        page.route(
            "**/sidecar",
            lambda r: r.fulfill(json={"version": 1, "entries": []}) if r.request.method == "GET" else r.continue_(),
        )
        page.evaluate(f"localStorage.removeItem('{DRAFT_KEY}')")
        page.reload()
        page.wait_for_load_state("networkidle")
        # the floor grid lies in the plane of the plate's bottom face
        ctl("グリッド").locator("input").click()

        # ---- helpers ------------------------------------------------------------
        def grab():
            settle()
            url = page.evaluate(
                "new Promise(r => requestAnimationFrame(() =>"
                " r(document.querySelector('#viewport canvas').toDataURL())))"
            )
            return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")

        def px(img, xyz):
            """median colour of a 5x5 patch around the projection of xyz"""
            x, y = project(xyz)
            cl, ct, cw, ch = nav.canvas_rect()
            cx, cy = int((x - cl) * img.width / cw), int((y - ct) * img.height / ch)
            patch = [img.getpixel((cx + dx, cy + dy)) for dx in range(-2, 3) for dy in range(-2, 3)]
            return tuple(sorted(p[k] for p in patch)[12] for k in range(3))

        def on_face(xyz):
            """xyz is on the canvas and the first thing the eye meets there"""
            xy = project(xyz)
            cl, ct, cw, ch = nav.canvas_rect()
            assert cl + 4 <= xy[0] <= cl + cw - 4 and ct + 4 <= xy[1] <= ct + ch - 4, ("off the canvas", xyz, xy)
            hit = pick(xy)
            assert hit and hit["kind"] == "face" and math.dist(hit["point"], xyz) <= 0.3, ("not on screen", xyz, hit)

        def classes(pts):
            img = grab()
            rgb = {k: px(img, p) for k, p in pts.items()}
            return {k: (cls(c), c) for k, c in rgb.items()}

        def expect(pts, want, tag):
            got = classes(pts)
            bad = {k: got[k] for k in want if got[k][0] != want[k]}
            assert not bad, (tag, "want", want, "got", got)
            return got

        def colours(pts):
            img = grab()
            return {k: px(img, p) for k, p in pts.items()}

        def open_folder(name):
            title = page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$")).first
            if title.get_attribute("aria-expanded") != "true":
                title.click()
                page.wait_for_timeout(300)  # open transition

        def checked(name):
            settle()  # .listen() updates the box on the next frame
            return ctl(name).locator("input").evaluate("e => e.checked")

        def toggle(name, on):
            box = ctl(name).locator("input")
            if box.evaluate("e => e.checked") != on:
                box.click()
            settle()

        def set_dir(label):
            sel = ctl("型開き方向").locator("select")
            sel.focus()  # a mouse pick leaves the select focused
            sel.select_option(label=label)
            settle()

        def dir_text():
            return ctl("型開き方向").locator("select").evaluate("s => s.options[s.selectedIndex].text")

        def set_required(v):
            inp = ctl("必要な勾配").locator("input")
            inp.fill(str(v))
            inp.press("Enter")
            settle()

        def legend_shown():
            return page.locator("#draft-legend").is_visible()

        def legend():
            return page.inner_text("#draft-legend")

        def hud():
            return page.inner_text("#hud-info")

        def summary_line():
            t = hud()
            assert "tris" in t and "肉厚" not in t and "エラー" not in t, ("status line", t)

        # ================= (a) mini_mold ==========================================
        nav.load(STEP)
        for p in ALL_PTS.values():
            on_face(p)
        B = colours(ALL_PTS)
        for k in PLATE_PTS:
            assert cls(B[k]) == "neutral", ("plate base colour", k, B[k])
        assert not legend_shown()

        # a2. on, +Z, 1.0
        open_folder("抜き勾配")
        assert dir_text() == "+Z" and float(ctl("必要な勾配").locator("input").input_value()) == 1.0
        toggle("色分け", True)
        assert checked("色分け")
        got = expect(
            ALL_PTS,
            {"TOP": "ok", "TOP2": "ok", "FRONT": "short", "RIGHT": "short", "CAV_FRONT": "short"},
            "a2 +Z 1.0",
        )
        assert not same(got["CAV_FRONT"][1], B["CAV_FRONT"]), ("cavity wall not recoloured", got, B)
        assert legend_shown()
        text = legend()
        assert "+Z" in text and "1.0°" in text and "垂直な壁を含む" in text, text
        i_ok, i_short, i_opp = text.index("抜ける側"), text.index("勾配不足"), text.index("反対側")
        assert i_ok < i_short < i_opp, text
        sw = page.evaluate(
            "[...document.querySelectorAll('#draft-legend .draft-swatch')]"
            ".map(e => getComputedStyle(e).backgroundColor.match(/\\d+/g).map(Number))"
        )
        assert [cls(tuple(c)) for c in sw] == ["ok", "short", "opposite"], sw

        # a3. section, still in the load view: clipping survives the vertex-colour shader
        open_folder("断面")
        toggle("有効", True)

        def check_section(tag):
            assert pick(project(TOP)) is None, (tag, "TOP must be clipped", pick(project(TOP)))
            on_face(TOP2)
            got = classes({"TOP": TOP, "TOP2": TOP2, "CUT": CUT})
            assert got["TOP"][0] == "neutral", (tag, "clipped TOP", got)
            assert got["TOP2"][0] == "ok", (tag, got)
            assert got["CUT"][0] == "neutral", (tag, "the cap is drawn over the cut", got)

        check_section("a3 section")
        toggle("色分け", False)
        toggle("色分け", True)
        check_section("a3 section, colouring off and on")
        toggle("キャップ", False)
        # without the cap the eye looks into the plate: the inside of its bottom face
        hit = pick(project(CUT))
        assert hit and hit["kind"] == "face" and abs(hit["point"][2]) < 1e-3, ("inside of the bottom face", hit)
        expect({"CUT": CUT}, {"CUT": "opposite"}, "a3 no cap: inside of the bottom face (-Z)")
        toggle("キャップ", True)
        toggle("有効", False)
        expect({"TOP": TOP}, {"TOP": "ok"}, "a3 section off")

        # a4. pull -Z: top and bottom swap, walls stay short
        set_dir("−Z")
        expect(PLATE_PTS, {"TOP": "opposite", "TOP2": "opposite", "FRONT": "short", "RIGHT": "short"}, "a4 -Z")
        assert "−Z" in legend(), legend()
        set_dir("+Z")

        # a5. 0 deg: vertical walls are enough
        set_required(0)
        expect(PLATE_PTS, {"TOP": "ok", "FRONT": "ok", "RIGHT": "ok"}, "a5 0 deg")
        assert "0.0°" in legend() and "垂直" not in legend(), legend()
        set_required(1.0)
        expect({"FRONT": FRONT}, {"FRONT": "short"}, "a5 back to 1 deg")

        # a6. off: every part back to its own colour, legend gone
        toggle("色分け", False)
        assert not checked("色分け")
        now = colours(ALL_PTS)
        for k in ALL_PTS:
            assert same(now[k], B[k]), ("a6 base colour not restored", k, now[k], B[k])
        assert not legend_shown()

        # a7. the bottom face, from below
        toggle("色分け", True)
        click_button("下")
        page.keyboard.press("f")
        settle()
        on_face(BOTTOM)
        expect({"B": BOTTOM}, {"B": "opposite"}, "a7 bottom +Z")
        set_dir("−Z")
        expect({"B": BOTTOM}, {"B": "ok"}, "a7 bottom -Z")
        set_dir("+Z")

        # a8. free rotation; the select gives the arrow keys back to the view
        nav.set_rotate("自由回転")
        click_button("等角")
        set_dir("−Z")
        sel = ctl("型開き方向").locator("select")
        assert not sel.evaluate("s => document.activeElement === s"), "the select must not keep focus"
        for _ in range(3):
            page.keyboard.press("ArrowUp")
        for _ in range(2):
            page.keyboard.press("ArrowRight")
        page.keyboard.press("f")  # fit in the rolled view (keeps direction and roll)
        settle()
        assert dir_text() == "−Z", ("arrow keys changed the pull direction", dir_text())
        up = nav.view()["up"]
        assert max(abs(u - w) for u, w in zip(up, (0, 0, 1))) > 0.05, ("the arrows must roll the view", up)
        on_face(TOP)
        expect({"TOP": TOP}, {"TOP": "opposite"}, "a8 rolled view, -Z")
        set_dir("+Z")
        expect({"TOP": TOP}, {"TOP": "ok"}, "a8 rolled view, +Z")
        nav.set_rotate("ターンテーブル")

        # a9. a hidden part still gets new colours
        click_button("等角")
        on_face(TOP)
        plate_box = page.locator("#tree-body label").filter(
            has=page.locator("span", has_text=re.compile(r"^plate$"))
        ).locator("input").first
        plate_box.click()
        settle()
        assert pick(project(TOP)) is None, "plate hidden"
        assert classes({"TOP": TOP})["TOP"][0] == "neutral"
        set_dir("−Z")
        plate_box.click()
        settle()
        on_face(TOP)
        expect({"TOP": TOP}, {"TOP": "opposite"}, "a9 shown again after -Z")
        set_dir("+Z")
        expect({"TOP": TOP}, {"TOP": "ok"}, "a9 +Z")

        # ================= (b) frustum with 2 deg walls ===========================
        nav.load(FRUSTUM)
        assert not checked("色分け"), "a new model starts uncoloured"
        assert not legend_shown()
        for p in F_PTS.values():
            on_face(p)
        FB = colours(F_PTS)
        for k, c in FB.items():
            assert cls(c) == "neutral", ("frustum base colour", k, c)
        toggle("色分け", True)
        for label, want in SIX.items():
            set_dir(label)
            expect(F_PTS, want, f"b2 {label} 1.0")
        set_dir("+Z")
        set_required(3.0)
        expect(F_PTS, {"FTOP": "ok", "XW": "short", "YW": "short"}, "b3 +Z 3.0")
        set_required(2.0)
        expect(F_PTS, {"FTOP": "ok", "XW": "ok", "YW": "ok"}, "b3 +Z exactly 2.0")
        set_dir("−Z")
        set_required(3.0)
        expect(F_PTS, {"FTOP": "opposite", "XW": "short", "YW": "short"}, "b3 -Z 3.0")
        toggle("色分け", False)
        now = colours(F_PTS)
        for k in F_PTS:
            assert same(now[k], FB[k]), ("b4 base colour not restored", k, now[k], FB[k])
        set_dir("+Z")
        set_required(1.0)

        # ================= (c) thickness heatmap: one at a time ===================
        nav.load(STEP)
        open_folder("肉厚")
        on_face(TOP)
        B_TOP = colours({"TOP": TOP})["TOP"]
        assert dir_text() == "+Z"

        # c2-c4. a held thickness request, overtaken by the draft, is dropped
        held = []
        page.route(THICK_RE, lambda r: held.append(r))
        toggle("ヒートマップ", True)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚計算中')")
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        assert held, "thickness request not seen"
        toggle("色分け", True)
        assert not checked("ヒートマップ"), "c3 the draft turns the heatmap off"
        summary_line()
        expect({"TOP": TOP}, {"TOP": "ok"}, "c3")
        with page.expect_request_finished(lambda r: "thickness.bin" in r.url, timeout=60000):
            held[0].continue_()
        page.unroute(THICK_RE)
        page.wait_for_timeout(300)
        settle()
        expect({"TOP": TOP}, {"TOP": "ok"}, "c4 late thickness response ignored")
        assert not checked("ヒートマップ")
        summary_line()

        # c5. a late thickness error after the draft took over is dropped too
        held2 = []
        page.route(THICK_RE, lambda r: held2.append(r))
        toggle("ヒートマップ", True)
        assert not checked("色分け") and not legend_shown(), "c5 the heatmap turns the draft off"
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚計算中')")
        for _ in range(50):
            if held2:
                break
            page.wait_for_timeout(100)
        assert held2, "thickness request not seen"
        toggle("色分け", True)
        n_err = len(nav.errors)
        with page.expect_event("requestfailed", lambda r: "thickness.bin" in r.url):
            held2[0].abort()
        page.wait_for_timeout(300)
        settle()
        page.unroute(THICK_RE)
        # the aborted request logs "Failed to load resource": expected here only
        nav.errors[n_err:] = [e for e in nav.errors[n_err:] if "Failed to load resource" not in e]
        summary_line()
        assert checked("色分け")
        expect({"TOP": TOP}, {"TOP": "ok"}, "c5")

        # c6. the heatmap takes over from the draft
        toggle("ヒートマップ", True)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')")
        assert not checked("色分け") and not legend_shown(), "c6 the heatmap turns the draft off"
        T = colours({"TOP": TOP})["TOP"]
        assert not same(T, B_TOP) and cls(T) != "ok", ("c6 heatmap colour", T, B_TOP)

        # c7. draft parameters changed while it is off leave the heatmap alone
        set_dir("−Z")
        assert same(colours({"TOP": TOP})["TOP"], T), "c7 heatmap wiped by a draft parameter change"

        # c8. the draft takes over again; the heatmap line goes away
        toggle("色分け", True)
        assert not checked("ヒートマップ")
        summary_line()
        got = expect({"TOP": TOP}, {"TOP": "opposite"}, "c8 -Z")
        assert not same(got["TOP"][1], T), ("c8 still the heatmap", got, T)

        # c9. thickness parameters changed while it is off leave the draft alone.
        # 15 mm >= 2 x 2.0, so the heatmap colour at TOP stays saturated: T stays valid
        thr = ctl("閾値").locator("input")
        thr.fill("2.0")
        thr.press("Enter")
        settle()
        expect({"TOP": TOP}, {"TOP": "opposite"}, "c9 after 閾値")

        # c10. heatmap again (cached now)
        toggle("ヒートマップ", True)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')")
        assert not checked("色分け")
        assert same(colours({"TOP": TOP})["TOP"], T), "c10 heatmap colour"

        # c11. heatmap off: base colour and the model line back
        toggle("ヒートマップ", False)
        assert same(colours({"TOP": TOP})["TOP"], B_TOP), "c11 base colour"
        summary_line()
        set_dir("+Z")

        # ================= (d) drawing, reload reset ==============================
        toggle("色分け", True)
        nav.load(DXF, wait_text="2D図面")
        title = page.locator(".lil-gui .lil-title", has_text=re.compile("^抜き勾配$")).first
        assert not title.is_visible(), "the folder must be hidden on a drawing"
        assert not legend_shown()
        assert not checked("色分け"), "a drawing resets the colouring"
        nav.load(STEP)
        assert title.is_visible()
        assert not checked("色分け")
        assert same(colours({"TOP": TOP})["TOP"], B_TOP), "d2 reloaded model is uncoloured"

        # ================= (e) remembered direction and angle =====================
        toggle("色分け", True)
        set_dir("−Z")
        set_required(2.5)
        page.reload()
        page.wait_for_load_state("networkidle")
        open_folder("抜き勾配")
        assert dir_text() == "−Z", dir_text()
        assert float(ctl("必要な勾配").locator("input").input_value()) == 2.5
        assert not checked("色分け"), "the on/off box is not remembered"
        assert not legend_shown()
        page.evaluate(f"localStorage.setItem('{DRAFT_KEY}', JSON.stringify({{dir: 'bogus', required: 99}}))")
        page.reload()
        page.wait_for_load_state("networkidle")
        assert dir_text() == "+Z", dir_text()
        assert float(ctl("必要な勾配").locator("input").input_value()) == 1.0

        page.evaluate(f"localStorage.removeItem('{DRAFT_KEY}')")
        page.screenshot(path="/tmp/cad_viewer_draft_angle.png")
    print("DRAFT ANGLE E2E OK")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
