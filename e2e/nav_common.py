"""Shared setup and helpers for the navigation E2E scripts (e2e/test_nav_*.py).

Expected values never come from the code under test: they are known box
corners projected through window.__cadProject, picker hits (__cadPick), the
camera state (__cadView, including near/far), constants of the specification
(load direction (1,-1,0.7), Z up, fill 0.88, MIN_FREE 0.4), the panels'
getBoundingClientRect and canvas pixels.

全体表示 (fit) frames the model in the free area: the largest axis-aligned
rectangle of the canvas that no visible overlay panel (PANELS) overlaps, at
least MIN_FREE of the canvas width and height (ties: centre nearest the canvas
centre, then smaller left, then smaller top); the whole canvas when there is
none. free_rect() below is an independent copy of that rule (the app's is
frontend/src/freearea.ts). The fit reads the panels once, when it runs, so the
oracle uses the panel rects recorded at the fit (Nav.fit / Nav.load) and fails
if they change before the check (a lil-gui folder animates for 300 ms; the HUD
text changes after measurements). A load waits a little for the 体積・重量
values before its fit, so that the fit sees the panel's final size; Nav.load
takes timing out of that (props=): by default it holds the values
(__cadStallProperties) and has the load not wait for them (__cadPropsWait(0)),
so the panel shows 計算中… at the fit and keeps it until the check.

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
# nav_session gives each script a private copy of this (nav.paths["step"])
STEP_SRC = TESTDATA / "mini_mold.step"
DXF = str(TESTDATA / "plate_drawing.dxf")
BG = (0x1D, 0x21, 0x26)  # scene background
MOLD = ((0, 0, 0), (100, 60, 40))  # make_step_assembly.py: plate 100x60x15 + pins/block up to z 40
MOLD_NO_PLATE = ((21, 15, 15), (79, 45, 40))  # pins r4 at x 25/75 (z 15..40) + block 30..70 x 15..45
SURFACE = (90, 10, 15)  # on the plate's top face, clear of the pins and the block
RUNNER = ((0, 0, 0), (298, 27.5, 4.5))
LOOSE_IGES = TESTDATA / "loose_faces_box.igs"  # testdata/make_iges_loose.py
LOOSE_BOX = ((0, 0, 0), (10, 20, 30))  # its sewn solid (the 100 mm axis lines are not framed)
TINY = ((0, 0, 0), (0.05, 0.03, 0.02))
HUGE = ((0, 0, 0), (5000, 3000, 2000))
BOXES = {"runner": RUNNER, "tiny": TINY, "huge": HUGE}
# overlay panels a fit keeps the model clear of (frontend/src/main.ts FIT_PANELS)
PANELS = (".lil-gui.lil-root", "#tree-panel", "#hud", "#measure-panel", "#props-panel")
MIN_FREE = 0.4


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


def free_rect(w, h, panels, min_free=MIN_FREE):
    """((l, t, r, b), fallback): the free area of a w x h canvas (rule above).

    panels: canvas-local (l, t, r, b). fallback is True when no rectangle
    qualifies and the whole canvas is used.
    """
    clipped = []
    for l, t, r, b in panels:
        c = (max(l, 0), max(t, 0), min(r, w), min(b, h))
        if c[2] > c[0] and c[3] > c[1]:
            clipped.append(c)
    lefts = [0] + [p[2] for p in clipped]
    rights = [w] + [p[0] for p in clipped]
    tops = [0] + [p[3] for p in clipped]
    bottoms = [h] + [p[1] for p in clipped]
    best, best_key = None, None
    for l in lefts:
        for r in rights:
            if r - l < min_free * w:
                continue
            for t in tops:
                for b in bottoms:
                    if b - t < min_free * h:
                        continue
                    if any(p[0] < r and p[2] > l and p[1] < b and p[3] > t for p in clipped):
                        continue
                    dx, dy = (l + r - w) / 2, (t + b - h) / 2
                    key = ((r - l) * (b - t), -(dx * dx + dy * dy), -l, -t)
                    if best_key is None or key > best_key:
                        best, best_key = (l, t, r, b), key
    return (best, False) if best else ((0, 0, w, h), True)


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def fit_metrics(B, F):
    """(fill, horizontal centring error, vertical centring error, inside) of rect B framed in F"""
    fw, fh = F[2] - F[0], F[3] - F[1]
    bw, bh = B[2] - B[0], B[3] - B[1]
    left, right, top, bottom = B[0] - F[0], F[2] - B[2], B[1] - F[1], F[3] - B[3]
    return (
        max(bw / fw, bh / fh),
        abs(left - right) / fw,
        abs(top - bottom) / fh,
        min(left, right, top, bottom) >= 0,
    )


def would_fail(B, F, A):
    """Would a correct fit into area A (instead of F) fail the checks against F?

    B is the box as framed in F. A fit into A scales it by k (the limiting
    ratio of A over that of F) and centres it in A. Margins are a little
    narrower than fill_check's, so a case that passes only by luck is not
    counted as a test of that panel.
    """
    bw, bh = B[2] - B[0], B[3] - B[1]
    Aw, Ah = A[2] - A[0], A[3] - A[1]
    Fw, Fh = F[2] - F[0], F[3] - F[1]
    k = min(Aw / bw, Ah / bh) / min(Fw / bw, Fh / bh)
    cx, cy = (A[0] + A[2]) / 2, (A[1] + A[3]) / 2
    B2 = (cx - k * bw / 2, cy - k * bh / 2, cx + k * bw / 2, cy + k * bh / 2)
    fill, ex, ey, inside = fit_metrics(B2, F)
    return not (0.865 <= fill <= 0.895) or ex > 0.015 or ey > 0.015 or not inside


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
        self.fit_panels = None  # panel rects at the last fit (fit / load)

    def load(self, path, wait_text="tris", props="frozen"):
        """Open a file and wait for its HUD text (set in the same task as the load fit).

        props: the 体積・重量 values.
        - "frozen": held for good, and the load does not wait for them: the
          panel shows 計算中… at the fit and after it
        - "live": let through (also disarms a hold left over from a 2D load,
          which makes no request), and the load waits for them however long
          they take: the panel shows the values at the fit
        - "late": held for good, with the app's own wait: the load waits that
          long, then fits with 計算中…
        - "unheld": let through, and the load does not wait for them: they come
          when they come (a script that holds /properties itself with a route)
        """
        stall, wait = {"frozen": (1e9, 0), "live": (0, 600000), "late": (1e9, None), "unheld": (0, 0)}[props]
        self.page.evaluate(
            "([s, w]) => { window.__cadStallProperties(s); window.__cadPropsWait(w ?? undefined) }", [stall, wait]
        )
        self.page.set_input_files("#file-input", str(path))
        self.page.wait_for_function(
            f"document.querySelector('#hud-info').textContent.includes({wait_text!r})"
            " && document.querySelector('#hud-info').textContent.includes("
            f"{Path(path).name!r})",
            timeout=60000,
        )
        self.settle()
        self.fit_panels = self.panel_rects()

    def wait_gui_idle(self):
        """until no lil-gui folder is opening or closing (it animates for 300 ms)"""
        self.settle()  # lil-gui adds lil-transition one frame after the click
        self.page.wait_for_function("!document.querySelector('.lil-gui.lil-transition')", timeout=5000)
        self.settle()

    def fit(self, trigger="f"):
        """全体表示 by a key ("f", "F", "Home") or the button ("button"); records the panel rects"""
        self.wait_gui_idle()
        if trigger == "button":
            self.ctl("全体表示").locator("button").click()
        else:
            self.page.keyboard.press(trigger)
        self.settle()
        self.fit_panels = self.panel_rects()

    def panel_rects(self, exclude=()):
        """{selector: canvas-local (l, t, r, b)} of the visible panels"""
        cl, ct, _, _ = self.canvas_rect()
        rects = self.page.evaluate(
            """sels => sels.map(s => { const e = document.querySelector(s)
                 if (!e) return null; const r = e.getBoundingClientRect()
                 return r.width > 0 && r.height > 0 ? [r.left, r.top, r.right, r.bottom] : null })""",
            [s for s in PANELS if s not in exclude],
        )
        out = {}
        for sel, r in zip([s for s in PANELS if s not in exclude], rects):
            if r:
                out[sel] = (r[0] - cl, r[1] - ct, r[2] - cl, r[3] - ct)
        return out

    def assert_panels_unchanged(self):
        now = self.panel_rects()
        then = self.fit_panels
        assert then is not None, "no fit recorded (use Nav.fit / Nav.load)"
        same = now.keys() == then.keys() and all(
            all(abs(a - b) <= 0.5 for a, b in zip(now[k], then[k])) for k in now
        )
        assert same, ("panels changed between the fit and the check", then, now)

    def free_area(self, exclude=(), min_free=MIN_FREE):
        """((l, t, r, b) canvas-local, fallback) from the panels on screen"""
        _, _, cw, ch = self.canvas_rect()
        return free_rect(cw, ch, list(self.panel_rects(exclude).values()), min_free)

    def view_centre(self):
        """page coordinates of the free area's centre (where a fit puts the target)"""
        self.assert_panels_unchanged()
        cl, ct, _, _ = self.canvas_rect()
        (l, t, r, b), _ = self.free_area()
        return [cl + (l + r) / 2, ct + (t + b) / 2]

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

    def fill_check(self, lo, hi, tag="", fallback=None, needs=()):
        """The box fills 0.86-0.90 of the free area's limiting dimension, centred in it.

        fallback: if given, whether the whole canvas must have been used.
        needs: panels this case depends on: a correct fit that ignored one of
        them must fail these checks (otherwise the case cannot catch it).
        """
        self.assert_panels_unchanged()
        cl, ct, cw, ch = self.canvas_rect()
        F, fell_back = self.free_area()
        x0, y0, x1, y1 = self.rect(lo, hi)
        B = (x0 - cl, y0 - ct, x1 - cl, y1 - ct)
        fill, ex, ey, inside = fit_metrics(B, F)
        info = (tag, [round(x, 1) for x in F], round(fill, 4), round(ex, 4), round(ey, 4), [round(x, 1) for x in B])
        assert 0.86 <= fill <= 0.90, ("fill", info)
        assert inside, ("inside the free area", info)
        assert ex <= 0.01 and ey <= 0.01, ("centred in the free area", info)
        if not fell_back:
            for sel, p in self.panel_rects().items():
                assert not overlaps(B, p), ("under a panel", sel, p, info)
        if fallback is not None:
            assert fell_back == fallback, ("fallback", fell_back, info)
        for sel in needs:
            A, _ = self.free_area(exclude=(sel,))
            assert would_fail(B, F, A), ("case no longer depends on", sel, A, info)
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

    def canvas_image(self):
        """the canvas as drawn (an RGB image of its device pixels)"""
        url = self.page.evaluate(
            "new Promise(r => requestAnimationFrame(() =>"
            " r(document.querySelector('#viewport canvas').toDataURL())))"
        )
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")

    def canvas_rgb(self, points):
        """the drawn colour at each page point"""
        img = self.canvas_image()
        cl, ct, cw, ch = self.canvas_rect()
        sx, sy = img.width / cw, img.height / ch
        return [img.getpixel((int((x - cl) * sx), int((y - ct) * sy))) for x, y in points]

    def canvas_ink_rect(self):
        """bounding box (page px) of canvas pixels that differ from the background"""
        img = self.canvas_image()
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
        self.fit()


def put_sidecar(page, path, entries):
    """Upload a file through the API and save a sidecar with these entries for it.

    The sidecar is keyed by the file's content hash, so the next load of the
    same bytes restores exactly these entries. The backend stores any JSON.
    """
    r = page.request.post(
        f"{BASE_URL}/api/models",
        multipart={"file": {"name": Path(path).name, "mimeType": "application/octet-stream",
                            "buffer": Path(path).read_bytes()}},
        timeout=120000,
    )
    assert r.ok, ("upload", r.status, r.text())
    r = page.request.put(f"{BASE_URL}/api/models/{r.json()['id']}/sidecar", data={"version": 1, "entries": entries})
    assert r.ok, ("put sidecar", r.status, r.text())


def empty_sidecar(page, path):
    """an empty sidecar for this file: its next load restores no measurement list"""
    put_sidecar(page, path, [])


@contextmanager
def nav_session(boxes=()):
    """A fresh page on the app with cleared view preferences.

    boxes: names from BOXES to write as STL files (nav.paths[name]). The page
    must log no errors; the files are removed afterwards.

    nav.paths["step"] is a private copy of mini_mold.step (three trailing
    newlines: its own content hash, so its own sidecar), emptied here. Other
    scripts leave entries on the shared mini_mold.step, and a restored list is
    a panel the fit avoids: it would shrink and move these framings.
    """
    tmp = tempfile.mkdtemp(prefix="cad_nav_")
    try:
        paths = {"step": os.path.join(tmp, "mini_mold.step")}
        Path(paths["step"]).write_bytes(STEP_SRC.read_bytes() + b"\n" * 3)
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
            empty_sidecar(page, paths["step"])
            yield nav
            page.evaluate("localStorage.removeItem('cad-viewer:view')")
            if nav.errors:
                print("PAGE ERRORS:", nav.errors)
            assert not nav.errors
            browser.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
