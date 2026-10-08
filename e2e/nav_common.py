"""Shared setup and helpers for the navigation E2E scripts (e2e/test_nav_*.py).

Expected values never come from the code under test: they are known box
corners projected through window.__cadProject, picker hits (__cadPick), the
camera state (__cadView, including near/far), constants of the specification
(load direction (1,-1,0.7), Z up, fill 0.88) and canvas pixels.

The navigation checks used to be one script (test_navigation.py). On the CI
runner it took longer than the per-script limit (300 s), so it is split into
fit / wheel / pivot scripts. This module is not named test_*.py, so the E2E
loops do not run it on its own.
"""
import base64
import io
import math
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
DXF = str(TESTDATA / "plate_drawing.dxf")
BG = (0x1D, 0x21, 0x26)  # scene background
MOLD = ((0, 0, 0), (100, 60, 40))  # make_step_assembly.py: plate 100x60x15 + pins/block up to z 40
MOLD_NO_PLATE = ((21, 15, 15), (79, 45, 40))  # pins r4 at x 25/75 (z 15..40) + block 30..70 x 15..45
SURFACE = (90, 10, 15)  # on the plate's top face, clear of the pins and the block
RUNNER = ((0, 0, 0), (298, 27.5, 4.5))
TINY = ((0, 0, 0), (0.05, 0.03, 0.02))
HUGE = ((0, 0, 0), (5000, 3000, 2000))
BOXES = {"runner": RUNNER, "tiny": TINY, "huge": HUGE}


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


class Nav:
    """The page plus the helpers the navigation checks use."""

    def __init__(self, page, paths):
        self.page = page
        self.paths = paths
        self.errors = []

    def load(self, path, wait_text="tris"):
        self.page.set_input_files("#file-input", path)
        self.page.wait_for_function(
            f"document.querySelector('#hud-info').textContent.includes({wait_text!r})"
            " && document.querySelector('#hud-info').textContent.includes("
            f"{Path(path).name!r})",
            timeout=60000,
        )
        self.settle()

    def settle(self):
        self.page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def view(self):
        return self.page.evaluate("window.__cadView()")

    def project(self, xyz):
        r = self.page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
        return (r["x"], r["y"])

    def pick(self, xy):
        return self.page.evaluate("([x, y]) => window.__cadPick(x, y)", list(xy))

    def canvas_rect(self):
        return self.page.evaluate(
            "(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect();"
            " return [r.left, r.top, r.width, r.height] })()"
        )

    def centre(self):
        """page coordinates of the canvas centre"""
        cl, ct, cw, ch = self.canvas_rect()
        return [cl + cw / 2, ct + ch / 2]

    def ctl(self, name):
        label = self.page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
        return self.page.locator(".lil-gui .lil-controller").filter(has=label).first

    def click_button(self, name):
        self.ctl(name).locator("button").click()
        self.settle()

    def set_mode(self, label):
        self.ctl("モード").locator("select").select_option(label)
        self.page.evaluate("document.activeElement && document.activeElement.blur()")

    def set_rotate(self, label):
        self.ctl("回転方式").locator("select").select_option(label=label)
        self.page.evaluate("document.activeElement && document.activeElement.blur()")

    def direction(self, v=None):
        v = v or self.view()
        return norm(sub(v["target"], v["position"]))

    def same_dir(self, v0, v1, tol=1e-9):
        assert dot(self.direction(v0), self.direction(v1)) >= 1 - tol, (self.direction(v0), self.direction(v1))
        assert close(v0["up"], v1["up"], 1e-6), (v0["up"], v1["up"])

    def rect(self, lo, hi):
        pts = [self.project(c) for c in corners(lo, hi)]
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def fill_check(self, lo, hi, tag=""):
        cl, ct, cw, ch = self.canvas_rect()
        x0, y0, x1, y1 = self.rect(lo, hi)
        fw, fh = (x1 - x0) / cw, (y1 - y0) / ch
        lim = max(fw, fh)
        left, right = x0 - cl, cl + cw - x1
        top, bottom = y0 - ct, ct + ch - y1
        info = (tag, round(fw, 4), round(fh, 4), round(left, 1), round(right, 1), round(top, 1), round(bottom, 1))
        assert 0.86 <= lim <= 0.90, ("fill", info)
        assert min(left, right, top, bottom) >= 0, ("inside the canvas", info)
        assert abs(left - right) <= 0.01 * cw and abs(top - bottom) <= 0.01 * ch, ("centred", info)
        return info

    def depth_check(self, lo, hi):
        v = self.view()
        f = self.direction(v)
        for c in corners(lo, hi):
            d = dot(sub(c, v["position"]), f)
            assert v["near"] < d < v["far"], ("depth", c, d, v["near"], v["far"])

    def plane_point(self, xy):
        """point on the plane through the target, square to the view, under pixel xy"""
        v = self.view()
        t = v["target"]
        f = self.direction(v)
        r = norm(cross(f, v["up"]))
        u = cross(r, f)
        L = length(sub(v["position"], t)) * 0.1
        p0 = self.project(t)
        pr = self.project(add(t, mul(r, L)))
        pu = self.project(add(t, mul(u, L)))
        # projection is linear on that plane (constant depth): solve for alpha, beta
        a11, a21 = pr[0] - p0[0], pr[1] - p0[1]
        a12, a22 = pu[0] - p0[0], pu[1] - p0[1]
        bx, by = xy[0] - p0[0], xy[1] - p0[1]
        det = a11 * a22 - a12 * a21
        al = (bx * a22 - a12 * by) / det
        be = (a11 * by - bx * a21) / det
        return add(t, add(mul(r, al * L), mul(u, be * L)))

    def wheel(self, xy, dy, n=1):
        self.page.mouse.move(*xy)
        for _ in range(n):
            self.page.mouse.wheel(0, dy)
        self.settle()

    def canvas_ink_rect(self):
        """bounding box (page px) of canvas pixels that differ from the background"""
        url = self.page.evaluate(
            "new Promise(r => requestAnimationFrame(() =>"
            " r(document.querySelector('#viewport canvas').toDataURL())))"
        )
        img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
        cl, ct, cw, ch = self.canvas_rect()
        sx, sy = img.width / cw, img.height / ch
        diff = ImageChops.difference(img, Image.new("RGB", img.size, BG))
        mask = diff.point(lambda q: 255 if q > 6 else 0).convert("L")
        bb = mask.getbbox()
        assert bb, "nothing drawn"
        return cl + bb[0] / sx, ct + bb[1] / sy, cl + bb[2] / sx, ct + bb[3] / sy

    def marker_rect(self):
        return self.page.evaluate(
            "(() => { const m = document.querySelector('.pivot-marker'); if (!m) return null;"
            " const r = m.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2] })()"
        )

    def setup_view(self, mode):
        """等角 view in the given rotate mode (rolled in free mode), then fit"""
        self.set_rotate(mode)
        self.click_button("等角")
        if mode == "自由回転":
            for _ in range(7):
                self.page.keyboard.press("ArrowUp")
            for _ in range(3):
                self.page.keyboard.press("ArrowRight")
            assert not close(self.view()["up"], [0, 0, 1], 1e-3)
        self.page.keyboard.press("f")
        self.settle()


@contextmanager
def nav_session(boxes=()):
    """A fresh page on the app with cleared view preferences.

    boxes: names from BOXES to write as STL files (nav.paths[name]). The page
    must log no errors; the files are removed afterwards.
    """
    tmp = tempfile.mkdtemp(prefix="cad_nav_")
    try:
        paths = {}
        for name in boxes:
            paths[name] = os.path.join(tmp, f"{name}.stl")
            box_stl(paths[name], *BOXES[name])
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            nav = Nav(page, paths)
            page.on("pageerror", lambda e: nav.errors.append(str(e)))
            page.on("console", lambda m: nav.errors.append(m.text) if m.type == "error" else None)
            page.goto(BASE_URL)
            page.evaluate("localStorage.removeItem('cad-viewer:view')")
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            yield nav
            page.evaluate("localStorage.removeItem('cad-viewer:view')")
            if nav.errors:
                print("PAGE ERRORS:", nav.errors)
            assert not nav.errors
            browser.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
