"""Draft-angle colouring (抜き勾配, C2): the E2E cases, run in three scripts.

test_draft_angle.py runs (a), test_draft_mesh.py (b), test_draft_thickness.py
(c)-(e). As one script it took longer than the CI runner's limit per script
(300 s); this module is not named test_*.py, so the E2E loops do not run it.

Expected classes never come from the code under test. They come from how the
models are built: mini_mold.step (make_step_assembly.py: plate 100x60x15 with
+Z top, -Z bottom and vertical walls; pins r4 at x 25/75; cavity block
30..70 x 15..45 x 15..35) and a frustum STL written here whose four side walls
lean exactly 2 deg. The colour on screen is read from the canvas pixels at
projected points (window.__cadProject) that the picker confirms are on the
expected face (window.__cadPick). Lighting shades the class colours, so a
pixel is classified by its dominant channel: green = 抜ける側, red = 勾配不足,
blue = 反対側, anything greyish = neutral (part colours, cap, background).

Steps: (a) empty screen, then mini_mold: classes, horizontal pulls (the pins'
curved faces), section, direction, 0 deg, off, bottom view, free rotation +
keyboard (a dropdown that keeps focus), hidden part; (b) frustum: all six pull
directions and the 2 deg boundary; a filleted STL whose under-drafted wall
must stay red up to the fillet (mesh formats are classified per triangle);
an open STL gets the legend's note on face orientation, a closed STL wound
inside out is coloured as if wound outward (and gets no note), and the
colouring's per-triangle copy follows the display style (A4); (c) mutual exclusion
with the thickness heatmap, including held and aborted thickness requests, a
方式 switch and a measure result on the status line; (d) hidden on a drawing,
reset on reload, ticking while the mesh is still loading; (e) remembered
direction / angle, bad stored values.
"""
import base64
import io
import math
import os
import re
import shutil
import tempfile

from PIL import Image

from nav_common import BG, DXF, STEP_SRC, SURFACE, classic_basis, cross, nav_session, norm, sub
from engine_net import Net

# The shared mini_mold.step: every sidecar request is answered in the page
# (see run()), so other scripts' notes on it never show here.
STEP = str(STEP_SRC)

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


def frustum_stl(path, bottom=True, inside_out=False):
    """ASCII STL of the frustum: quads as nav_common.box_stl, normals from the winding.
    bottom=False leaves the base out: an open surface (no volume).
    inside_out=True writes every triangle the other way round (normals too): a
    closed solid whose file says front on the inside, as some exporters write"""
    a, b = F_HALF, F_TOPHALF
    v = [(-a, -a, 0.0), (a, -a, 0.0), (a, a, 0.0), (-a, a, 0.0), (-b, -b, F_H), (b, -b, F_H), (b, b, F_H), (-b, b, F_H)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    if not bottom:
        quads = quads[1:]
    lines = ["solid frustum"]
    for q in quads:
        for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            if inside_out:
                tri = tri[::-1]
            p = [v[i] for i in tri]
            n = norm(cross(sub(p[1], p[0]), sub(p[2], p[0])))
            lines.append(f"facet normal {n[0]!r} {n[1]!r} {n[2]!r}\n outer loop")
            lines += [f"  vertex {c[0]!r} {c[1]!r} {c[2]!r}" for c in p]
            lines.append(" endloop\nendfacet")
    lines.append("endsolid frustum")
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ---- filleted bar: profile in XZ extruded along Y; side walls with 1 deg draft
# run up to z G_HW, then an R3 fillet of 6 facets turns into the flat top.
# The backend averages vertex normals across edges below 30 deg, so the wall's
# top corners share normals with the first fillet facet (about 7.4 deg away).
G_HALF, G_HW, G_R, G_L, G_DRAFT, G_FACETS = 20.0, 7.0, 3.0, 30.0, 1.0, 6


def fillet_profile():
    """CCW in (x, z): right wall up, fillet, top, left fillet, left wall down"""
    t = math.tan(math.radians(G_DRAFT))
    pw = (G_HALF - G_HW * t, G_HW)  # top of the right wall
    th0 = math.radians(G_DRAFT)  # elevation of the wall normal
    n0 = (math.cos(th0), math.sin(th0))
    c = (pw[0] - G_R * n0[0], pw[1] - G_R * n0[1])  # fillet centre
    right = [(G_HALF, 0.0), pw]
    for k in range(1, G_FACETS + 1):
        th = th0 + (math.pi / 2 - th0) * k / G_FACETS
        right.append((c[0] + G_R * math.cos(th), c[1] + G_R * math.sin(th)))
    left = [(-x, z) for x, z in reversed(right)]
    return right + left


G_TOP_Z = fillet_profile()[G_FACETS + 1][1]


def facet(lines, p):
    n = norm(cross(sub(p[1], p[0]), sub(p[2], p[0])))
    lines.append(f"facet normal {n[0]!r} {n[1]!r} {n[2]!r}\n outer loop")
    lines += [f"  vertex {c[0]!r} {c[1]!r} {c[2]!r}" for c in p]
    lines.append(" endloop\nendfacet")


def fillet_stl(path):
    prof = fillet_profile()
    lines = ["solid fillet"]
    for i in range(len(prof)):
        (x0, z0), (x1, z1) = prof[i], prof[(i + 1) % len(prof)]
        a, b, c, d = (x0, 0.0, z0), (x1, 0.0, z1), (x1, G_L, z1), (x0, G_L, z0)
        facet(lines, (a, d, c))  # (dz, 0, -dx): outward for a CCW profile
        facet(lines, (a, c, b))
    cx = sum(x for x, _ in prof) / len(prof)
    cz = sum(z for _, z in prof) / len(prof)
    for i in range(len(prof)):
        (x0, z0), (x1, z1) = prof[i], prof[(i + 1) % len(prof)]
        facet(lines, ((cx, 0.0, cz), (x0, 0.0, z0), (x1, 0.0, z1)))  # -Y
        facet(lines, ((cx, G_L, cz), (x1, G_L, z1), (x0, G_L, z0)))  # +Y
    lines.append("endsolid fillet")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def wall_pt(z):
    """on the +X wall of the filleted bar, mid-length"""
    return (G_HALF - z * math.tan(math.radians(G_DRAFT)), G_L / 2, z)


G_PTS = {"W90": wall_pt(0.9 * G_HW), "W60": wall_pt(0.6 * G_HW), "W20": wall_pt(0.2 * G_HW)}


def cls(rgb):
    """class of a rendered pixel by its dominant channel (lighting changes brightness, not the dominant hue)"""
    order = sorted(range(3), key=lambda k: rgb[k], reverse=True)
    top, second = rgb[order[0]], rgb[order[1]]
    if top >= 60 and top >= 1.6 * max(second, 1):
        return ("short", "ok", "opposite")[order[0]]
    return "neutral"


def same(a, b, tol=4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def run(parts: str) -> None:
    """Run the sections named in parts: "a" (mini_mold), "b" (mesh formats),
    "c" ((c) thickness, then (d) drawing and reload, then (e) remembered values)."""
    tmp = tempfile.mkdtemp(prefix="cad_draft_")
    try:
        FRUSTUM = os.path.join(tmp, "draft_frustum.stl")
        frustum_stl(FRUSTUM)
        FILLET = os.path.join(tmp, "draft_fillet.stl")
        fillet_stl(FILLET)
        OPEN = os.path.join(tmp, "draft_open.stl")
        frustum_stl(OPEN, bottom=False)
        INSIDE_OUT = os.path.join(tmp, "draft_inside_out.stl")
        frustum_stl(INSIDE_OUT, inside_out=True)

        with nav_session() as nav:
            page = nav.page
            # the checks at the app's own 1.5 mm and 1.0° (判定の基準 手で決める), as written: the default is the material's
            classic_basis(page)
            settle, project, pick, ctl, click_button = nav.settle, nav.project, nav.pick, nav.ctl, nav.click_button
            # The shared backend may hold measure markers on mini_mold from other
            # runs; they would be drawn over the sample points. Saves stay in the
            # page too (step c measures): nothing is written to the backend.
            Net.of(page).route(
                "**/sidecar",
                lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {}),
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

            def props_ready():
                """the 体積・重量 panel has the /properties answer of the model on screen"""
                page.wait_for_function(
                    "!document.querySelector('#props-panel').classList.contains('hidden')"
                    " && document.querySelector('#props-status').classList.contains('hidden')",
                    timeout=60000,
                )

            def summary_line():
                t = hud()
                assert "三角形" in t and "肉厚" not in t and "エラー" not in t, ("status line", t)

            if "a" in parts:
                # ================= (a) mini_mold ==========================================
                # a0. nothing to colour on the empty screen: the folder is not there
                # (the panel holds 表示 only until a file is open, issue #47 item 3)
                title = page.locator(".lil-gui .lil-title", has_text=re.compile("^抜き勾配$")).first
                assert title.count() == 1 and not title.is_visible(), "a0 抜き勾配 on the empty screen"
                assert not legend_shown(), "a0 legend over an empty scene"

                nav.load(STEP, props="live")
                props_ready()
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
                assert not same(got["PIN2_SIDE"][1], B["PIN2_SIDE"]), ("pin not recoloured", got, B)
                assert legend_shown()
                text = legend()
                assert "+Z" in text and "1.0°" in text and "垂直な壁を含む" in text, text
                assert "型開き側にあれば逆勾配" in text, ("blue must not promise a release", text)
                assert "緑と青が逆" not in text, ("closed solids get no orientation note", text)
                i_ok, i_short, i_opp = text.index("抜ける側"), text.index("勾配不足"), text.index("反対側")
                assert i_ok < i_short < i_opp, text
                sw = page.evaluate(
                    "[...document.querySelectorAll('#draft-legend .draft-swatch')]"
                    ".map(e => getComputedStyle(e).backgroundColor.match(/\\d+/g).map(Number))"
                )
                assert [cls(tuple(c)) for c in sw] == ["ok", "short", "opposite"], sw

                # a2b. horizontal pulls: the side walls and the pins' curved faces. The pin
                # at x 75 is the second instance of a shared shape; PIN2_SIDE's normal is
                # (0.707, -0.707, 0), so n.d = 0.707 for both +X and -Y.
                set_dir("+X")
                expect(
                    ALL_PTS,
                    {"PIN2_SIDE": "ok", "RIGHT": "ok", "FRONT": "short", "TOP": "short", "CAV_FRONT": "short"},
                    "a2b +X",
                )
                set_dir("−Y")
                expect(
                    ALL_PTS,
                    {"PIN2_SIDE": "ok", "FRONT": "ok", "CAV_FRONT": "ok", "RIGHT": "short", "TOP": "short"},
                    "a2b -Y",
                )
                set_dir("+Z")

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

                # a8. free rotation; the arrow keys move the view even while the
                # dropdown keeps focus (after a pick, and after closing it unchanged)
                nav.set_rotate("自由回転")
                click_button("等角")
                set_dir("−Z")
                sel = ctl("型開き方向").locator("select")
                assert sel.evaluate("s => document.activeElement === s"), "set_dir leaves the select focused"
                sel.click()  # open the popup ...
                page.keyboard.press("Escape")  # ... and close it without a change
                assert sel.evaluate("s => document.activeElement === s"), "still focused after Escape"
                v0 = nav.view()
                page.keyboard.press("ArrowRight")
                settle()
                assert dir_text() == "−Z", ("ArrowRight on the closed select changed the direction", dir_text())
                assert "−Z" in legend(), legend()
                assert max(abs(a - b) for a, b in zip(nav.view()["position"], v0["position"])) > 1e-3, "the view must turn"
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

            if "b" in parts:
                # ================= (b) frustum with 2 deg walls ===========================
                nav.load(FRUSTUM, props="live")
                open_folder("抜き勾配")  # also when (a) did not run (the empty screen has no such folder)
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
                    if label == "+Z":
                        # the flat copy is lit like the part: the top and the two walls
                        # face the light at different angles, so the same green comes
                        # out at different brightness (a copy with no usable normals
                        # shades them all alike)
                        lit = {k: sum(c) for k, c in colours(F_PTS).items()}
                        assert max(lit.values()) - min(lit.values()) >= 30, ("b2 flat copy not lit", lit)
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

                # b5. filleted STL: the 1 deg wall is under-drafted at 3 deg all the way
                # up to the fillet; the facets of the fillet itself lean 8 deg or more
                nav.load(FILLET, props="live")
                click_button("右")
                page.keyboard.press("f")
                settle()
                for p in G_PTS.values():
                    on_face(p)
                GB = colours(G_PTS)
                open_folder("断面")
                toggle("有効", True)  # X 0.5: the +X half (with the wall) is cut away
                set_required(3.0)
                toggle("色分け", True)
                for k, p in G_PTS.items():
                    # the eye goes through the cut to the inside of the far (-X) wall
                    hit = pick(project(p))
                    assert hit is None or hit["point"][0] < 0, ("b5 wall must be clipped", k, hit)
                got = classes(G_PTS)
                assert all(v[0] == "neutral" for v in got.values()), ("b5 clipped wall drawn coloured", got)
                toggle("有効", False)
                expect(G_PTS, {"W90": "short", "W60": "short", "W20": "short"}, "b5 wall at 3 deg")
                set_required(0.5)
                expect(G_PTS, {"W90": "ok", "W60": "ok", "W20": "ok"}, "b5 wall at 0.5 deg")
                set_required(3.0)
                click_button("等角")
                page.keyboard.press("f")
                settle()
                top_pt = (0.0, G_L / 2, G_TOP_Z)
                on_face(top_pt)
                expect({"T": top_pt}, {"T": "ok"}, "b5 top")
                click_button("右")
                page.keyboard.press("f")
                settle()
                # the heatmap takes over: the per-triangle copy goes, the part shows its heatmap
                open_folder("肉厚")
                toggle("ヒートマップ", True)
                page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')")
                assert not checked("色分け")
                # W90: nine tenths from the wall's top corners, which sit 40 mm from the
                # far wall (thick: the heatmap's blue end, nothing like the draft red)
                H = classes({"W90": G_PTS["W90"]})["W90"]
                assert H[0] != "short", ("b5 draft colours left over the heatmap", H)
                toggle("ヒートマップ", False)
                toggle("色分け", True)
                expect(G_PTS, {"W90": "short"}, "b5 colouring again")
                toggle("色分け", False)
                now = colours(G_PTS)
                for k in G_PTS:
                    assert same(now[k], GB[k]), ("b5 base colour not restored", k, now[k], GB[k])
                set_required(1.0)

                # b6. open STL (no base): the legend notes that its faces keep the file's
                # orientation, once /properties has answered. The answer is held by a
                # route until the colouring is on (a timed stall ran out on the slow CI
                # runner before the check), then let through.
                held_props = []
                Net.of(page).route("**/properties", lambda r: held_props.append(r))
                nav.load(OPEN, props="unheld")  # the route above holds the values
                click_button("等角")
                page.keyboard.press("f")
                settle()
                toggle("色分け", True)
                page.wait_for_timeout(300)
                assert held_props, "b6 /properties was not requested"
                assert "緑と青が逆" not in legend(), ("b6 note before /properties answered", legend())
                Net.of(page).unroute("**/properties")
                for r in held_props:
                    r.continue_()
                page.wait_for_function(
                    "document.querySelector('#draft-legend').textContent.includes('緑と青が逆')", timeout=30000
                )
                assert "1 個" in legend(), legend()
                on_face(FTOP)
                expect({"FTOP": FTOP}, {"FTOP": "ok"}, "b6 top of the open frustum")
                toggle("色分け", False)

                # b7. the same closed frustum wound inside out: the colours are those of
                # b2 (the solid's outside is its outside, whatever the file's winding),
                # and no note (it is closed: /properties gives it a volume)
                nav.load(INSIDE_OUT, props="live")
                click_button("等角")
                page.keyboard.press("f")
                settle()
                for p in F_PTS.values():
                    on_face(p)
                toggle("色分け", True)
                for label in ("+Z", "−Z", "+X", "−Y"):
                    set_dir(label)
                    expect(F_PTS, SIX[label], f"b7 inside-out {label} 1.0")
                # /properties has answered with a volume (the open frustum before had none)
                page.wait_for_function(
                    "(() => { const t = document.querySelector('#props-total');"
                    " return t && !t.classList.contains('hidden')"
                    " && document.querySelector('#props-total-volume').textContent.includes('cm') })()",
                    timeout=30000,
                )
                settle()
                assert "緑と青が逆" not in legend(), ("b7 closed part noted as unoriented", legend())
                set_dir("+Z")
                toggle("色分け", False)

                # b8. the colouring's per-triangle copy of a mesh part takes the
                # display style, and the part mesh stays hidden behind it (kept
                # for picking only): the same number of draw calls with and
                # without the colouring in every style, and in ワイヤーフレーム
                # a point inside the top face stays the background
                def style(label):
                    ctl("表示スタイル").locator("select").select_option(label=label)
                    page.evaluate("document.activeElement && document.activeElement.blur()")
                    settle()

                def calls():
                    settle()
                    return page.evaluate("window.__cadRenderInfo().calls")

                STYLE_LABELS = ("陰影＋稜線", "陰影のみ", "ワイヤーフレーム", "半透明")
                plain = {}
                for label in STYLE_LABELS:
                    style(label)
                    plain[label] = calls()
                # a point inside the top face, away from its diagonal and edges,
                # where the uncoloured wireframe shows the background
                style("ワイヤーフレーム")
                img = grab()
                inside = None
                for fx, fy in ((0.5, -0.5), (-0.5, 0.5), (0.55, 0.0), (0.0, -0.55), (-0.55, 0.0), (0.0, 0.55)):
                    q = (fx * F_TOPHALF, fy * F_TOPHALF, F_H)
                    if same(px(img, q), BG, 6):
                        inside = q
                        break
                assert inside, "b8 no background point inside the top face in ワイヤーフレーム"
                toggle("色分け", True)
                for label in STYLE_LABELS:
                    style(label)
                    got = calls()
                    assert got == plain[label], ("b8 draw calls with the colouring", label, got, plain[label])
                    if label == "ワイヤーフレーム":
                        c = px(grab(), inside)
                        assert same(c, BG, 6), ("b8 the coloured copy is filled in ワイヤーフレーム", c)
                style("陰影＋稜線")
                expect(F_PTS, SIX["+Z"], "b8 back to 陰影＋稜線")
                toggle("色分け", False)
                assert calls() == plain["陰影＋稜線"], "b8 the part mesh is drawn again"

            if "c" in parts:  # (c), (d) and (e) build on each other
                # ================= (c) thickness heatmap: one at a time ===================
                nav.load(STEP, props="live")
                open_folder("抜き勾配")  # the empty screen has no such folder
                open_folder("肉厚")
                on_face(TOP)
                B_TOP = colours({"TOP": TOP})["TOP"]
                assert dir_text() == "+Z"

                # c2-c4. a held thickness request, overtaken by the draft, is dropped
                held = []
                Net.of(page).route(THICK_RE, lambda r: held.append(r))
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
                with Net.of(page).expect_request_finished(lambda r: "thickness.bin" in r.url, timeout=60000):
                    held[0].continue_()
                Net.of(page).unroute(THICK_RE)
                page.wait_for_timeout(300)
                settle()
                expect({"TOP": TOP}, {"TOP": "ok"}, "c4 late thickness response ignored")
                assert not checked("ヒートマップ")
                summary_line()

                # c5. a late thickness error after the draft took over is dropped too
                held2 = []
                Net.of(page).route(THICK_RE, lambda r: held2.append(r))
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
                with Net.of(page).expect_event("requestfailed", lambda r: "thickness.bin" in r.url):
                    held2[0].abort()
                page.wait_for_timeout(300)
                settle()
                Net.of(page).unroute(THICK_RE)
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

                # c12. the request of the previous 方式 failing after a switch is dropped:
                # ball is held, ray (cached) is shown, then the ball request fails
                meth = ctl("方式").locator("select")
                meth.select_option(label="ローリングボール法")  # heatmap off: nothing fetched
                held3 = []
                Net.of(page).route(THICK_RE, lambda r: held3.append(r))
                toggle("ヒートマップ", True)
                page.wait_for_function("document.querySelector('#hud-info').textContent.includes('ボール法')")
                for _ in range(50):
                    if held3:
                        break
                    page.wait_for_timeout(100)
                assert held3, "ball request not seen"
                meth.select_option(label="レイ法")
                page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中（レイ法')")
                n_err = len(nav.errors)
                with Net.of(page).expect_event("requestfailed", lambda r: "thickness.bin" in r.url):
                    held3[0].abort()
                page.wait_for_timeout(300)
                settle()
                Net.of(page).unroute(THICK_RE)
                nav.errors[n_err:] = [e for e in nav.errors[n_err:] if "Failed to load resource" not in e]
                assert "エラー" not in hud() and "レイ法" in hud(), ("c12 late failure of the old 方式", hud())
                assert checked("ヒートマップ"), "c12 the heatmap must stay on"
                assert same(colours({"TOP": TOP})["TOP"], T), "c12 heatmap colour"

                # c13. a measure line written while the heatmap is on stays when it goes off
                # (the line is final once the face's area has come: it says it then)
                nav.set_mode("計測")
                x, y = project(TOP)
                page.mouse.click(x, y)
                page.wait_for_function("document.querySelector('#hud-info').textContent.includes('を選択（面積')")
                msg = hud()
                toggle("ヒートマップ", False)
                assert hud() == msg, ("c13 the measure line was replaced", msg, hud())
                nav.set_mode("なし")
                assert same(colours({"TOP": TOP})["TOP"], B_TOP), "c13 base colour"

                # ================= (d) drawing, reload reset ==============================
                toggle("色分け", True)
                nav.load(DXF, wait_text="2D 図面", props="live")  # no hold left armed for the direct load in d2
                title = page.locator(".lil-gui .lil-title", has_text=re.compile("^抜き勾配$")).first
                assert not title.is_visible(), "the folder must be hidden on a drawing"
                assert not legend_shown()
                assert not checked("色分け"), "a drawing resets the colouring"
                # d2. ticked while the mesh is still on its way: nothing to colour yet,
                # so the box snaps back and the model arrives uncoloured
                held_mesh = []
                Net.of(page).route("**/mesh.bin", lambda r: held_mesh.append(r))
                page.set_input_files("#file-input", STEP)
                for _ in range(300):
                    if held_mesh:
                        break
                    page.wait_for_timeout(100)
                assert held_mesh, "mesh request not seen"
                assert title.is_visible()
                toggle("色分け", True)
                assert not checked("色分け"), "d2 ticked while loading"
                assert not legend_shown()
                held_mesh[0].continue_()
                Net.of(page).unroute("**/mesh.bin")
                page.wait_for_function(
                    "document.querySelector('#hud-info').textContent.includes('三角形')"
                    " && document.querySelector('#hud-info').textContent.includes('mini_mold.step')",
                    timeout=60000,
                )
                settle()
                assert not checked("色分け")
                assert not legend_shown()
                assert same(colours({"TOP": TOP})["TOP"], B_TOP), "d2 reloaded model is uncoloured"

                # ================= (e) remembered direction and angle =====================
                toggle("色分け", True)
                set_dir("−Z")
                set_required(2.5)
                page.reload()
                page.wait_for_load_state("networkidle")
                # the empty screen has no 抜き勾配: a model brings it, with the remembered settings
                nav.load(STEP, props="live")
                open_folder("抜き勾配")
                assert dir_text() == "−Z", dir_text()
                assert float(ctl("必要な勾配").locator("input").input_value()) == 2.5
                assert not checked("色分け"), "the on/off box is not remembered"
                assert not legend_shown()
                page.evaluate(f"localStorage.setItem('{DRAFT_KEY}', JSON.stringify({{dir: 'bogus', required: 99}}))")
                page.reload()
                page.wait_for_load_state("networkidle")
                nav.load(STEP, props="live")
                assert dir_text() == "+Z", dir_text()
                assert float(ctl("必要な勾配").locator("input").input_value()) == 1.0

            page.evaluate(f"localStorage.removeItem('{DRAFT_KEY}')")
            page.screenshot(path=f"/tmp/cad_viewer_draft_angle_{parts}.png")
        print(f"DRAFT ANGLE E2E OK ({parts})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
