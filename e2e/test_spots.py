"""E2E: the legends' buttons that go to the places their colours point at (issue #47 item 7).

- 抜き勾配 on mini_mold (+Z, 1.0°): 勾配不足's この色の面へ goes to the ten
  vertical walls one after the other, the largest first, and after the tenth
  to the first again; 反対側's to the four faces that look down. Each time the
  view looks at the face from outside (a little from above when it looks
  sideways), the marker sits on the face and on screen, and the legend says
  which of how many and the angle there.
- A change that makes another list (the required angle, a part hidden in the
  tree) takes the marker and the count away; the next press counts again
  (with the block hidden: six walls).
- H (the panels hidden, the view fitted again) keeps the place framed.
- A saved image leaves the marker out (it points at where the view went).
- 肉厚 on ribbed_plate.stl: at 1.5 mm the three 1.2 mm ribs are three places
  (both sides of a rib are one place); at 1.0 mm none is thinner, and the
  button goes to the thinnest point (a rib's side, 1.2 mm), saying so.

Oracles (none from the code under test): how the models are built.
mini_mold.step (testdata/make_step_assembly.py): the plate 0..100 x 0..60 x
0..15, the cavity block 30..70 x 15..45 x 15..35, core pins r4 at (25, 30)
and (75, 30), z 15..40. With +Z and 1.0° every vertical wall is 勾配不足
(plate 4, block 4, the pins' sides 2), every face that looks down is 反対側
(the plate's bottom at z 0; the block's and the pins' at z 15); their areas
(plate 100 x 15 and 60 x 15, block 40 x 20 and 30 x 20, a pin's side
2 pi 4 x 25) give the order. ribbed_plate.stl (make_testdata.py): ribs 1.2
thick at x -25 / 0 / 25 (+-0.6), y +-23, z 2..10, the plate 2 thick.
window.__cadView (the camera), __cadProject (on screen), the DOM (the
legend's text, the marker). window.__cadSpot reports where a press went; its
place is checked against the shapes above, not taken as the answer.
"""
import io
import math
import os
import tempfile

from PIL import Image

import gui_common
from nav_common import TESTDATA, nav_session

PLATE = ((0, 0, 0), (100, 60, 15))
BLOCK = ((30, 15, 15), (70, 45, 35))
PINS = ((25, 30), (75, 30))
PIN_R = 4
RIBS = (-25, 0, 25)
RIB_T = 1.2
RIBBED = ((-40, -25, 0), (40, 25, 12))

TOL = 1e-3
YELLOW = (0xFF, 0xD0, 0x60)  # the marker's ring and label (--cv-measure)


def yellow_count(img, box):
    """pixels near the marker's yellow inside box (l, t, r, b) of an RGB image"""
    n = 0
    for x in range(max(0, box[0]), min(img.width, box[2])):
        for y in range(max(0, box[1]), min(img.height, box[3])):
            p = img.getpixel((x, y))
            if max(abs(p[i] - YELLOW[i]) for i in range(3)) <= 40:
                n += 1
    return n


def near(a, b, tol=TOL):
    return abs(a - b) <= tol


def wall_of(p, n, hidden=()):
    """(name, area) of the vertical wall of mini_mold the point p (normal n) is on, or None"""
    x, y, z = p
    if abs(n[2]) > 1e-6:
        return None
    pl, ph = PLATE
    if 0 <= z <= 15:
        for name, ok, area in (
            ("plate -Y", near(y, 0) and n[1] < -0.99, 1500),
            ("plate +Y", near(y, 60) and n[1] > 0.99, 1500),
            ("plate -X", near(x, 0) and n[0] < -0.99, 900),
            ("plate +X", near(x, 100) and n[0] > 0.99, 900),
        ):
            if ok and pl[0] - TOL <= x <= ph[0] + TOL and pl[1] - TOL <= y <= ph[1] + TOL:
                return name, area
    if "block" not in hidden and 15 <= z <= 35:
        for name, ok, area in (
            ("block -Y", near(y, 15) and n[1] < -0.99, 800),
            ("block +Y", near(y, 45) and n[1] > 0.99, 800),
            ("block -X", near(x, 30) and n[0] < -0.99, 600),
            ("block +X", near(x, 70) and n[0] > 0.99, 600),
        ):
            if ok and 30 - TOL <= x <= 70 + TOL and 15 - TOL <= y <= 45 + TOL:
                return name, area
    if 15 <= z <= 40:
        for i, (cx, cy) in enumerate(PINS):
            r = math.hypot(x - cx, y - cy)
            # on the tessellated side: a triangle's centre is a little inside the circle
            radial = ((x - cx) * n[0] + (y - cy) * n[1]) / max(r, 1e-9)
            if 0.97 * PIN_R <= r <= PIN_R + TOL and radial > 0.95:
                return f"pin {i}", 2 * math.pi * PIN_R * 25
    return None


def down_face_of(p, n):
    """the face of mini_mold that looks down (反対側 for +Z) the point is on, or None"""
    if n[2] > -0.999:
        return None
    x, y, z = p
    if near(z, 0) and 0 <= x <= 100 and 0 <= y <= 60:
        return "plate bottom"
    if near(z, 15):
        if 30 <= x <= 70 and 15 <= y <= 45:
            return "block bottom"
        for i, (cx, cy) in enumerate(PINS):
            if math.hypot(x - cx, y - cy) <= PIN_R + TOL:
                return f"pin {i} bottom"
    return None


with nav_session() as n:
    page = n.page
    n.stub_sidecar()

    def spot():
        return page.evaluate("window.__cadSpot()")

    def state(kind):
        return page.inner_text(f".go-state[data-go='{kind}']")

    def press(kind):
        page.locator(f".go-btn[data-go='{kind}']").click()
        n.settle()
        page.wait_for_timeout(450)  # the move takes 0.3 s (none under automation, but cheap to wait)
        n.settle()

    def marker_xy():
        return page.evaluate(
            "(() => { const m = document.querySelector('.spot-marker'); if (!m) return null;"
            " const r = m.getBoundingClientRect(); return [r.left, r.top] })()"
        )

    def check_view(s, label):
        """the camera looks at the place from outside, and the place is on screen"""
        v = n.view()
        to_cam = [v["position"][i] - v["target"][i] for i in range(3)]
        d = math.sqrt(sum(c * c for c in to_cam))
        facing = sum(to_cam[i] / d * s["spot"]["normal"][i] for i in range(3))
        assert facing > 0.85, (label, "the view must look at the place from outside", facing, s)
        cl, ct, cw, ch = n.canvas_rect()
        x, y = n.project(s["spot"]["at"])
        assert cl <= x <= cl + cw and ct <= y <= ct + ch, (label, "the place must be on screen", (x, y))
        m = marker_xy()
        assert m and math.dist(m, (x, y)) <= 3, (label, "the marker must sit on the place", m, (x, y))

    # ================= 抜き勾配 on mini_mold ==========================================
    n.load(n.paths["step"])
    gui_common.open_folder(page, "抜き勾配")
    gui_common.ctl(page, "色分け").locator("input").check()
    n.settle()
    assert state("short") == "" and state("opposite") == "", "no count before a press"
    assert spot() is None and marker_xy() is None

    walls = []
    for i in range(10):
        press("short")
        s = spot()
        assert s and s["kind"] == "short" and s["index"] == i and s["count"] == 10, (i, s)
        w = wall_of(s["spot"]["at"], s["spot"]["normal"])
        assert w, ("a 勾配不足 place must be on a vertical wall", s)
        walls.append(w)
        assert abs(s["spot"]["value"]) < 0.05, ("a vertical wall's draft is 0°", s)
        assert state("short") == f"{i + 1}/10 ・ 勾配 0.0°", state("short")
        check_view(s, f"short {i}")
    names = [w[0] for w in walls]
    assert len(set(names)) == 10, ("ten different walls", names)
    areas = [w[1] for w in walls]
    assert areas == sorted(areas, reverse=True), ("the largest first", walls)
    print("1 勾配不足", names)
    press("short")
    assert spot()["index"] == 0 and wall_of(spot()["spot"]["at"], spot()["spot"]["normal"])[0] == names[0], "after the tenth, the first again"

    downs = []
    for i in range(4):
        press("opposite")
        s = spot()
        assert s and s["kind"] == "opposite" and s["count"] == 4, s
        f = down_face_of(s["spot"]["at"], s["spot"]["normal"])
        assert f, ("a 反対側 place must look down", s)
        downs.append(f)
        assert state("opposite") == f"{i + 1}/4 ・ 勾配 −90.0°", state("opposite")
        assert state("short") == "", "only the list in use says where it is"
        check_view(s, f"opposite {i}")
    assert sorted(downs) == sorted(["plate bottom", "block bottom", "pin 0 bottom", "pin 1 bottom"]), downs
    assert downs[0] == "plate bottom", ("the largest first", downs)
    print("2 反対側", downs)

    # ---- a saved image leaves the marker out; the screen has it
    mx, my = marker_xy()
    around = (round(mx) - 12, round(my) - 26, round(mx) + 90, round(my) + 12)
    shown = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    assert yellow_count(shown, around) > 30, ("the marker is on screen", yellow_count(shown, around))
    with page.expect_download(timeout=15000) as info:
        page.locator("#toolbar button[data-action='png']").click()
    path = os.path.join(tempfile.mkdtemp(prefix="cad_spots_"), "view.png")
    info.value.save_as(path)
    saved = Image.open(path).convert("RGB")
    cl, ct, cw, ch = n.canvas_rect()
    sx, sy = saved.width / cw, saved.height / ch
    in_png = (round((around[0] - cl) * sx), round((around[1] - ct) * sy), round((around[2] - cl) * sx), round((around[3] - ct) * sy))
    assert yellow_count(saved, in_png) == 0, ("the saved image must leave the marker out", yellow_count(saved, in_png))
    print("2b the saved image has no marker")

    # ---- H: the panels hidden, the view fitted again, the same place framed
    at = spot()["spot"]["at"]
    page.keyboard.press("h")
    n.settle()
    page.wait_for_timeout(450)
    n.settle()
    cl, ct, cw, ch = n.canvas_rect()
    x, y = n.project(at)
    assert cl <= x <= cl + cw and ct <= y <= ct + ch, ("H keeps the place on screen", (x, y))
    assert math.dist(marker_xy(), (x, y)) <= 3
    page.keyboard.press("h")
    n.settle()
    page.wait_for_timeout(450)

    # ---- another list: the required angle, then a hidden part
    req = gui_common.ctl(page, "必要な勾配 (°)").locator("input").last
    req.fill("2")
    req.press("Enter")
    n.settle()
    assert spot() is None and marker_xy() is None, "a new angle takes the marker away"
    assert state("opposite") == "", state("opposite")
    labels = page.locator("#tree-panel label")
    texts = labels.all_text_contents()
    labels.nth(texts.index("cavity_block")).locator("xpath=..").locator("input").uncheck()
    n.settle()
    press("short")
    s = spot()
    assert s["count"] == 6, ("with the block hidden: the plate's 4 walls and the pins' 2", s)
    for i in range(6):
        w = wall_of(spot()["spot"]["at"], spot()["spot"]["normal"], hidden=("block",))
        assert w and not w[0].startswith("block"), spot()
        if i < 5:
            press("short")
    labels.nth(texts.index("cavity_block")).locator("xpath=..").locator("input").check()
    n.settle()
    assert spot() is None and marker_xy() is None, "showing a part again makes another list"
    print("3 another list ok")

    # the colouring off: no buttons, no marker
    press("short")
    assert marker_xy() is not None
    gui_common.ctl(page, "色分け").locator("input").uncheck()
    n.settle()
    assert marker_xy() is None and spot() is None, "the colouring off takes the marker away"

    # ================= 肉厚 on ribbed_plate.stl =======================================
    n.load(str(TESTDATA / "ribbed_plate.stl"), box=RIBBED)
    gui_common.open_folder(page, "肉厚")
    gui_common.ctl(page, "ヒートマップ").locator("input").check()
    page.wait_for_function("document.querySelector('#thickness-legend:not(.hidden) .go-btn') !== null", timeout=60000)
    thr = gui_common.ctl(page, "閾値 (mm)").locator("input").last
    thr.fill("1.5")
    thr.press("Enter")
    n.settle()
    ribs = []
    for i in range(3):
        press("thin")
        s = spot()
        assert s and s["kind"] == "thin" and s["count"] == 3 and s["index"] == i, ("three ribs, three places", s)
        x, y, z = s["spot"]["at"]
        rib = min(RIBS, key=lambda c: abs(x - c))
        assert abs(abs(x - rib) - RIB_T / 2) <= TOL and 2 <= z <= 10 and abs(y) <= 23, ("on a rib's side", s)
        assert abs(s["spot"]["value"] - RIB_T) <= 0.05, s
        lo, hi = s["spot"]["min"], s["spot"]["max"]
        assert near(lo[0], rib - RIB_T / 2) and near(hi[0], rib + RIB_T / 2), ("both sides of the rib are one place", s)
        ribs.append(rib)
        assert state("thin") == f"{i + 1}/3 ・ {s['spot']['value']:.2f} mm", state("thin")
        check_view(s, f"thin {i}")
    assert sorted(ribs) == sorted(RIBS), ribs
    print("4 thin places", ribs)

    thr.fill("1.0")
    thr.press("Enter")
    n.settle()
    assert spot() is None and marker_xy() is None, "a new threshold takes the marker away"
    press("thin")
    s = spot()
    assert s and s["count"] == 1 and abs(s["spot"]["value"] - RIB_T) <= 0.05, ("none under 1.0: the thinnest point", s)
    x = s["spot"]["at"][0]
    assert min(abs(abs(x - c) - RIB_T / 2) for c in RIBS) <= TOL, ("the thinnest is on a rib's side", s)
    assert state("thin") == f"閾値より薄い所は無い。いちばん薄い所 {s['spot']['value']:.2f} mm", state("thin")
    check_view(s, "thinnest")
    gui_common.ctl(page, "ヒートマップ").locator("input").uncheck()
    n.settle()
    assert marker_xy() is None and spot() is None, "the heatmap off takes the marker away"
    print("5 thinnest ok")
print("SPOTS E2E OK")
