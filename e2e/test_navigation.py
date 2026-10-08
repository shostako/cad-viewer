"""E2E: 全体表示 (fit), wheel zoom toward the cursor, double-click rotation centre.

Expected values never come from the code under test: they are known box
corners projected through window.__cadProject, picker hits (__cadPick), the
camera state (__cadView, including near/far), constants of the specification
(load direction (1,-1,0.7), Z up, fill 0.88) and canvas pixels.

The STL boxes are written to a temporary directory; mini_mold.step and
plate_drawing.dxf come from testdata/. Needs the same servers as the other
E2E scripts.
"""
import base64
import io
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
DXF = str(TESTDATA / "plate_drawing.dxf")
BG = (0x1D, 0x21, 0x26)  # scene background
LOAD_DIR = None  # set below: normalised (1, -1, 0.7)
MOLD = ((0, 0, 0), (100, 60, 40))  # make_step_assembly.py: plate 100x60x15 + pins/block up to z 40
MOLD_NO_PLATE = ((21, 15, 15), (79, 45, 40))  # pins r4 at x 25/75 (z 15..40) + block 30..70 x 15..45
SURFACE = (90, 10, 15)  # on the plate's top face, clear of the pins and the block


# ---- vector helpers -----------------------------------------------------------
def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def mul(a, k):
    return [x * k for x in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def length(v):
    return math.sqrt(dot(v, v))


def norm(v):
    n = length(v)
    return [x / n for x in v]


def close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


LOAD_DIR = norm([1, -1, 0.7])


def corners(lo, hi):
    return [[(hi if i & 1 else lo)[0], (hi if i & 2 else lo)[1], (hi if i & 4 else lo)[2]] for i in range(8)]


def box_stl(path, lo, hi):
    """12-triangle ASCII STL of an axis-aligned box, outward normals."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    lines = ["solid box"]
    for a, b, c, d in quads:
        for tri in ((a, b, c), (a, c, d)):
            p = [v[i] for i in tri]
            n = norm(cross(sub(p[1], p[0]), sub(p[2], p[0])))
            lines.append(f"facet normal {n[0]} {n[1]} {n[2]}\n outer loop")
            lines += [f"  vertex {q[0]} {q[1]} {q[2]}" for q in p]
            lines.append(" endloop\nendfacet")
    lines.append("endsolid box")
    Path(path).write_text("\n".join(lines))


tmp = tempfile.mkdtemp(prefix="cad_nav_")
RUNNER = ((0, 0, 0), (298, 27.5, 4.5))
TINY = ((0, 0, 0), (0.05, 0.03, 0.02))
HUGE = ((0, 0, 0), (5000, 3000, 2000))
paths = {}
for name, (lo, hi) in (("runner", RUNNER), ("tiny", TINY), ("huge", HUGE)):
    paths[name] = os.path.join(tmp, f"{name}.stl")
    box_stl(paths[name], lo, hi)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def load(path, wait_text="tris"):
            page.set_input_files("#file-input", path)
            page.wait_for_function(
                f"document.querySelector('#hud-info').textContent.includes({wait_text!r})"
                " && document.querySelector('#hud-info').textContent.includes("
                f"{Path(path).name!r})",
                timeout=60000,
            )
            settle()

        def settle():
            page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

        def view():
            return page.evaluate("window.__cadView()")

        def project(xyz):
            r = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
            return (r["x"], r["y"])

        def pick(xy):
            return page.evaluate("([x, y]) => window.__cadPick(x, y)", list(xy))

        def canvas_rect():
            return page.evaluate(
                "(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect();"
                " return [r.left, r.top, r.width, r.height] })()"
            )

        def ctl(name):
            label = page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
            return page.locator(".lil-gui .lil-controller").filter(has=label).first

        def click_button(name):
            ctl(name).locator("button").click()
            settle()

        def set_mode(label):
            ctl("モード").locator("select").select_option(label)
            page.evaluate("document.activeElement && document.activeElement.blur()")

        def set_rotate(label):
            ctl("回転方式").locator("select").select_option(label=label)
            page.evaluate("document.activeElement && document.activeElement.blur()")

        def direction(v=None):
            v = v or view()
            return norm(sub(v["target"], v["position"]))

        def same_dir(v0, v1, tol=1e-9):
            assert dot(direction(v0), direction(v1)) >= 1 - tol, (direction(v0), direction(v1))
            assert close(v0["up"], v1["up"], 1e-6), (v0["up"], v1["up"])

        def rect(lo, hi):
            pts = [project(c) for c in corners(lo, hi)]
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            return min(xs), min(ys), max(xs), max(ys)

        def fill_check(lo, hi, tag=""):
            cl, ct, cw, ch = canvas_rect()
            x0, y0, x1, y1 = rect(lo, hi)
            fw, fh = (x1 - x0) / cw, (y1 - y0) / ch
            lim = max(fw, fh)
            left, right = x0 - cl, cl + cw - x1
            top, bottom = y0 - ct, ct + ch - y1
            info = (tag, round(fw, 4), round(fh, 4), round(left, 1), round(right, 1), round(top, 1), round(bottom, 1))
            assert 0.86 <= lim <= 0.90, ("fill", info)
            assert min(left, right, top, bottom) >= 0, ("inside the canvas", info)
            assert abs(left - right) <= 0.01 * cw and abs(top - bottom) <= 0.01 * ch, ("centred", info)
            return info

        def depth_check(lo, hi):
            v = view()
            f = direction(v)
            for c in corners(lo, hi):
                d = dot(sub(c, v["position"]), f)
                assert v["near"] < d < v["far"], ("depth", c, d, v["near"], v["far"])

        def plane_point(xy):
            """point on the plane through the target, square to the view, under pixel xy"""
            v = view()
            t = v["target"]
            f = direction(v)
            r = norm(cross(f, v["up"]))
            u = cross(r, f)
            L = length(sub(v["position"], t)) * 0.1
            p0 = project(t)
            pr = project(add(t, mul(r, L)))
            pu = project(add(t, mul(u, L)))
            # projection is linear on that plane (constant depth): solve for alpha, beta
            a11, a21 = pr[0] - p0[0], pr[1] - p0[1]
            a12, a22 = pu[0] - p0[0], pu[1] - p0[1]
            bx, by = xy[0] - p0[0], xy[1] - p0[1]
            det = a11 * a22 - a12 * a21
            al = (bx * a22 - a12 * by) / det
            be = (a11 * by - bx * a21) / det
            return add(t, add(mul(r, al * L), mul(u, be * L)))

        def wheel(xy, dy, n=1):
            page.mouse.move(*xy)
            for _ in range(n):
                page.mouse.wheel(0, dy)
            settle()

        def canvas_ink_rect():
            """bounding box (page px) of canvas pixels that differ from the background"""
            url = page.evaluate(
                "new Promise(r => requestAnimationFrame(() =>"
                " r(document.querySelector('#viewport canvas').toDataURL())))"
            )
            img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
            cl, ct, cw, ch = canvas_rect()
            sx, sy = img.width / cw, img.height / ch
            diff = ImageChops.difference(img, Image.new("RGB", img.size, BG))
            mask = diff.point(lambda q: 255 if q > 6 else 0).convert("L")
            bb = mask.getbbox()
            assert bb, "nothing drawn"
            return cl + bb[0] / sx, ct + bb[1] / sy, cl + bb[2] / sx, ct + bb[3] / sy

        page.goto(BASE_URL)
        page.evaluate("localStorage.removeItem('cad-viewer:view')")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

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
            if trig == "button":
                click_button("全体表示")
            else:
                page.keyboard.press(trig)
            settle()
            v1 = view()
            same_dir(v0, v1)
            print("A3", preset, trig, fill_check(*RUNNER, preset))
            depth_check(*RUNNER)

        # A4. narrow viewport: the width limits
        page.set_viewport_size({"width": 600, "height": 900})
        page.wait_for_timeout(300)
        page.keyboard.press("f")
        settle()
        print("A4 narrow", fill_check(*RUNNER, "600x900"))
        page.set_viewport_size({"width": 1280, "height": 800})
        page.wait_for_timeout(300)
        page.keyboard.press("f")
        settle()
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
        page.keyboard.press("f")
        settle()
        v1 = view()
        same_dir(v0, v1)
        assert abs(v1["up"][2]) < 0.9, ("still rolled", v1["up"])
        print("A5 free", fill_check(*RUNNER, "free"))
        set_rotate("ターンテーブル")

        # A6. height-limited view, then hidden parts
        load(STEP)
        click_button("右")
        page.keyboard.press("f")
        settle()
        print("A6 right", fill_check(*MOLD, "mold right"))
        plate_box = page.locator("#tree-panel label", has_text=re.compile("^plate$")).locator("input")
        plate_box.click()
        page.keyboard.press("f")
        settle()
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
        fill_check(*MOLD, "after 2D")

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
        page.keyboard.press("f")
        settle()

        # ============ B. wheel zoom (both rotate modes) ==============================
        for mode in ("ターンテーブル", "自由回転"):
            set_rotate(mode)
            click_button("等角")
            if mode == "自由回転":
                for _ in range(7):
                    page.keyboard.press("ArrowUp")
                for _ in range(3):
                    page.keyboard.press("ArrowRight")
                assert not close(view()["up"], [0, 0, 1], 1e-3)
            page.keyboard.press("f")
            settle()

            # B1. toward a surface: the point stays under the cursor
            cur = tuple(round(c) for c in project(SURFACE))
            hit = pick(cur)
            assert hit and hit["kind"] == "face", (mode, hit)
            P = hit["point"]
            assert math.dist(P, SURFACE) < 1, (mode, P)
            v_start = view()
            # the target plane is well behind P: zooming toward the target would drift P
            assert dot(sub(v_start["target"], P), direction(v_start)) > 10
            for _ in range(5):
                v0 = view()
                wheel(cur, -100)
                v1 = view()
                q = project(P)
                assert math.dist(q, cur) <= 0.5, (mode, "B1 drift", q, cur)
                # exactly one notch (0.9) closer to P itself. Zooming about any other
                # point on the cursor's ray would keep P under the cursor too, but
                # would step by a different share of the distance to P
                k = math.dist(v1["position"], P) / math.dist(v0["position"], P)
                assert abs(k - 0.9) <= 1e-6, (mode, k)
                same_dir(v0, v1)
            for _ in range(5):
                wheel(cur, 100)
            v = view()
            assert close(v["position"], v_start["position"], 1e-4), (mode, v["position"], v_start["position"])
            assert close(v["target"], v_start["target"], 1e-4)
            print("B1", mode, "ok")

            # B2. over empty space: the point on the target plane stays under the cursor
            empty = (640, 22)
            assert pick(empty) is None
            A = plane_point(empty)
            v_start = view()
            for _ in range(3):
                v0 = view()
                wheel(empty, -100)
                v1 = view()
                q = project(A)
                assert math.dist(q, empty) <= 0.5, (mode, "B2 drift", q)
                kt = math.dist(v1["target"], A) / math.dist(v0["target"], A)
                kc = math.dist(v1["position"], A) / math.dist(v0["position"], A)
                assert abs(kt - kc) <= 1e-6, (mode, kt, kc)
                # the new target lies on the line from A through the old target
                assert length(cross(sub(v1["target"], A), sub(v0["target"], A))) <= 1e-6 * length(sub(v0["target"], A)) ** 2
                same_dir(v0, v1)
            for _ in range(3):
                wheel(empty, 100)
            assert close(view()["position"], v_start["position"], 1e-4)
            print("B2", mode, "ok")

            # B3. the camera stops in front of the surface, and before the far plane
            for i in range(60):
                page.mouse.move(*cur)
                page.mouse.wheel(0, -300)
                if i % 10 == 9:
                    settle()
                    assert math.dist(project(P), cur) <= 1, (mode, "B3 drift", i)
            settle()
            v = view()
            d = dot(sub(P, v["position"]), direction(v))
            assert d > v["near"], (mode, "passed the near plane", d, v["near"])
            wheel(cur, -100, 2)
            v2 = view()
            assert close(v2["position"], v["position"], 1e-9), (mode, "zoomed past the stop")
            h = pick(cur)
            assert h and math.dist(h["point"], P) < 1e-3, (mode, "a nearer surface is hit now", h)
            dists = []
            for i in range(80):
                page.mouse.move(*cur)
                page.mouse.wheel(0, 300)
                if i % 10 == 9:
                    settle()
                    v = view()
                    dists.append(math.dist(v["position"], v["target"]))
            assert abs(dists[-1] - dists[-2]) <= 1e-9 * dists[-1], (mode, "zoom-out never stops", dists[-3:])
            v = view()
            f = direction(v)
            for c in corners(*MOLD):
                assert dot(sub(c, v["position"]), f) < v["far"], (mode, "model beyond far")
            page.keyboard.press("f")
            settle()

            # B4. a section: the clipped side is not a zoom point
            page.locator(".lil-gui .lil-title", has_text="断面").click()
            ctl("有効").locator("input").click()
            settle()
            Q = pick(cur)  # cur is over the plate at x=90, clipped away (x <= 50 is kept)
            if Q and Q["kind"] == "face":
                assert Q["point"][0] <= 50 + 1e-6, Q
                expected = Q["point"]
            else:
                expected = plane_point(cur)
            v0 = view()
            wheel(cur, -100)
            assert math.dist(project(expected), cur) <= 0.5, (mode, "B4", Q)
            # the clipped plate top is on the same ray: only the step size tells
            # which point the zoom went to
            k = math.dist(view()["position"], expected) / math.dist(v0["position"], expected)
            assert abs(k - 0.9) <= 1e-6, (mode, "B4 zoomed about a clipped point", k)
            ctl("有効").locator("input").click()
            page.locator(".lil-gui .lil-title", has_text="断面").click()
            page.keyboard.press("f")
            settle()

            # B5. the page itself never scrolls
            assert page.evaluate("document.scrollingElement.scrollTop") == 0
        set_rotate("ターンテーブル")

        # ============ C. double-click rotation centre ================================
        CENTRE_JS = "(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect();" \
            " return [r.left + r.width / 2, r.top + r.height / 2] })()"
        centre = page.evaluate(CENTRE_JS)

        def setup(mode):
            set_rotate(mode)
            click_button("等角")
            if mode == "自由回転":
                for _ in range(7):
                    page.keyboard.press("ArrowUp")
                for _ in range(3):
                    page.keyboard.press("ArrowRight")
            page.keyboard.press("f")
            settle()

        def marker_rect():
            return page.evaluate(
                "(() => { const m = document.querySelector('.pivot-marker'); if (!m) return null;"
                " const r = m.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2] })()"
            )

        for mode in ("ターンテーブル", "自由回転"):
            setup(mode)
            # C1. slide (no turn, no zoom) until P is mid-screen
            cur = tuple(round(c) for c in project(SURFACE))
            hit = pick(cur)
            assert hit and hit["kind"] == "face", hit
            P = hit["point"]
            v0 = view()
            depth = dot(sub(P, v0["position"]), direction(v0))
            page.evaluate(
                """([x, y, z]) => { window.__samples = []; const tick = () => {
                     window.__samples.push({ t: performance.now(), p: window.__cadProject(x, y, z), v: window.__cadView() })
                     if (window.__sampling) requestAnimationFrame(tick) }
                   window.__sampling = true; requestAnimationFrame(tick) }""",
                P,
            )
            page.mouse.dblclick(*cur)
            assert marker_rect() is not None, "marker must show"
            page.wait_for_timeout(450)  # the slide takes 250 ms; the marker stays 1 s
            m = marker_rect()
            assert m and math.dist(m, centre) <= 3, (mode, "marker", m)
            page.wait_for_timeout(250)
            page.evaluate("window.__sampling = false")
            samples = page.evaluate("window.__samples")
            v1 = view()
            assert close(v1["target"], P, 1e-4), (mode, v1["target"], P)
            assert math.dist(project(P), centre) <= 0.5, (mode, project(P), centre)
            same_dir(v0, v1)
            assert abs(math.dist(v1["position"], P) - depth) <= 1e-6 * depth, (mode, "pivot changed the zoom")
            f0 = direction(v0)
            dists = [math.dist((s["p"]["x"], s["p"]["y"]), centre) for s in samples]
            for s in samples:
                assert dot(direction(s["v"]), f0) >= 1 - 1e-9, (mode, "the camera turned mid-slide")
            for a, b in zip(dists, dists[1:]):
                assert b <= a + 0.5, (mode, "P moved away from the centre", a, b)
            d0, d1 = dists[0], dists[-1]
            mid = [d for d in dists if d1 + 0.1 * (d0 - d1) < d < d1 + 0.9 * (d0 - d1)]
            assert len(mid) >= 1, (mode, "jumped instead of sliding", dists)
            moving = [s["t"] for s, d in zip(samples, dists) if d < d0 - 0.5]
            settled = [s["t"] for s, d in zip(samples, dists) if d <= d1 + 0.5]
            dur = settled[0] - (moving[0] if moving else samples[0]["t"])
            assert 100 <= dur + 34 and dur <= 600, (mode, "slide duration", dur)  # +2 frames of sampling slack
            page.wait_for_timeout(2000)
            assert marker_rect() is None, "marker must go away"

            # C2. later turns go around P, from keys and from a drag
            for _ in range(3):
                page.keyboard.press("ArrowRight")
            assert math.dist(project(P), centre) <= 0.5, (mode, "keys turn around P")
            page.mouse.move(centre[0] - 100, centre[1] + 150)
            page.mouse.down()
            page.mouse.move(centre[0] + 100, centre[1] + 150, steps=10)
            page.mouse.up()
            page.wait_for_timeout(800)
            assert math.dist(project(P), centre) <= 1, (mode, "drag turns around P", project(P))
            print("C1/C2", mode, "ok")
        set_rotate("ターンテーブル")
        setup("ターンテーブル")

        # C3. empty space: nothing happens
        v0 = view()
        page.mouse.dblclick(640, 22)
        page.wait_for_timeout(400)
        v1 = view()
        assert close(v1["target"], v0["target"], 1e-12) and close(v1["position"], v0["position"], 1e-12)
        assert marker_rect() is None

        # C4. 計測 / 注記: both clicks are picks, not a pivot
        set_mode("計測")
        v0 = view()
        page.mouse.dblclick(*project((50, 30, 35)))
        page.wait_for_timeout(500)
        assert close(view()["target"], v0["target"], 1e-12), "pivot in 計測 mode"
        click_button("計測クリア")
        set_mode("なし")

        # C5. a drag that returns to where it started is not a click
        X = tuple(round(c) for c in project(SURFACE))
        v0 = view()
        page.mouse.move(*X)
        page.mouse.down()
        page.mouse.move(X[0] + 40, X[1], steps=5)
        page.mouse.move(X[0] + 1, X[1], steps=5)
        page.mouse.up()
        page.mouse.click(*X)
        page.wait_for_timeout(500)
        v1 = view()
        assert close(v1["target"], v0["target"], 1e-9), ("C5", v1["target"], v0["target"])
        page.keyboard.press("f")
        settle()

        # C6. an interruption finishes the slide (the new centre is kept)
        Qp = (50, 30, 35)  # top of the cavity block
        curq = tuple(round(c) for c in project(Qp))
        Q = pick(curq)["point"]
        page.mouse.dblclick(*curq)
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(400)
        assert close(view()["target"], Q, 1e-4), ("C6", view()["target"], Q)
        assert math.dist(project(Q), centre) <= 0.5
        page.keyboard.press("f")
        settle()

        # C7. auto-rotate pauses for the slide, then spins around the new centre
        ctl("自動回転").locator("input").click()
        cur = tuple(round(c) for c in project(SURFACE))
        page.mouse.dblclick(*cur)  # the view spins meanwhile: the hit is near SURFACE, on the plate top
        page.wait_for_timeout(600)
        P2 = view()["target"]
        assert abs(P2[2] - 15) < 1e-6 and math.dist(P2, SURFACE) < 5, ("C7", P2)
        a = direction()
        for _ in range(5):
            page.wait_for_timeout(100)
            assert math.dist(project(P2), centre) <= 1, ("C7 off centre", project(P2))
        turned = math.degrees(math.acos(min(1, dot(a, direction()))))
        assert turned > 3, ("auto-rotate stalled", turned)
        ctl("自動回転").locator("input").click()
        page.keyboard.press("f")
        settle()

        # C8. a section: the clipped side is never the centre
        page.locator(".lil-gui .lil-title", has_text="断面").click()
        ctl("有効").locator("input").click()
        settle()
        cur = tuple(round(c) for c in project(SURFACE))
        Q = pick(cur)
        v0 = view()
        page.mouse.dblclick(*cur)
        page.wait_for_timeout(500)
        if Q and Q["kind"] == "face":
            assert close(view()["target"], Q["point"], 1e-4) and view()["target"][0] <= 50 + 1e-6
        else:
            assert close(view()["target"], v0["target"], 1e-12)
        ctl("有効").locator("input").click()
        page.locator(".lil-gui .lil-title", has_text="断面").click()

        # C10. a wheel step during the slide zooms from the slide's end pose: at the
        # canvas centre that is P itself, so the target stays P (picking in the
        # in-between pose would zoom about another point and move the target off P)
        page.keyboard.press("f")
        settle()
        cur = tuple(round(c) for c in project(SURFACE))
        P = pick(cur)["point"]
        v0 = view()
        depth = dot(sub(P, v0["position"]), direction(v0))
        page.mouse.dblclick(*cur)
        page.mouse.move(*centre)
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(400)
        v = view()
        assert close(v["target"], P, 1e-4), ("C10 target", v["target"], P)
        assert abs(math.dist(v["position"], P) - 0.9 * depth) <= 1e-6 * depth, ("C10 distance", math.dist(v["position"], P), depth)

        # C11. a second double-click during the slide starts from the pose on
        # screen: it never jumps to the first slide's end first
        page.keyboard.press("f")
        settle()
        cur1 = tuple(round(c) for c in project(SURFACE))
        cur2 = tuple(round(c) for c in project((10, 5, 15)))  # plate top, near the front left corner
        assert pick(cur2)["kind"] == "face"
        P1 = pick(cur1)["point"]
        # the camera state at each press, after the viewer has handled it (bubble
        # phase on window): the presses of the second double-click must still see
        # the first slide in progress, not its end pose
        page.evaluate(
            """() => { window.__downs = []
               window.addEventListener('pointerdown', () => window.__downs.push(window.__cadView())) }"""
        )
        page.mouse.dblclick(*cur1)
        page.mouse.dblclick(*cur2)
        page.wait_for_timeout(700)
        downs = page.evaluate("window.__downs")
        assert len(downs) == 4, len(downs)
        for d in downs[2:]:
            assert math.dist(d["target"], P1) > 1e-3, ("C11 the first slide jumped to its end", d["target"], P1)
        end = view()["target"]
        # what lies under cur2 depends on how far the first slide got: only check
        # that the second one won (the centre is not P1) and finished
        assert not close(end, P1, 1), ("C11 second centre", end)
        assert math.dist(project(end), centre) <= 0.5

        # C9. a reload during the slide drops it
        page.keyboard.press("f")
        settle()
        page.mouse.dblclick(*tuple(round(c) for c in project(SURFACE)))
        load(paths["runner"])
        page.wait_for_timeout(400)
        v = view()
        assert close(norm(sub(v["position"], v["target"])), LOAD_DIR, 1e-9), v
        fill_check(*RUNNER, "reload mid-slide")
        assert marker_rect() is None

        page.screenshot(path="/tmp/cad_viewer_navigation.png")
        page.evaluate("localStorage.removeItem('cad-viewer:view')")
        if errors:
            print("PAGE ERRORS:", errors)
        assert not errors
        print("NAVIGATION E2E OK")
        browser.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
