"""Shared setup and helpers for the display-style E2E scripts (A4, 表示スタイル):
test_display_styles.py and test_display_styles_more.py.

Expected values never come from the code under test. They come from
window.__cadProject projections of geometry whose construction is known
(testdata/make_step_assembly.py: plate 100x60x15 at the origin, core pins
r 4 h 25 at (25,30,15) and (75,30,15), cavity block 40x30x20 at (30,15,15);
the STL boxes and walls written here), picks (__cadPick), the camera
(__cadView), the colours of the specification (background, marker, the amber
of loose curves) and canvas pixels read with toDataURL inside rAF.

The STEP is a private copy with eleven trailing newlines: its own hash, so its
own model id and sidecar on a shared backend. test_section_annotation leaves
annotations in mini_mold.step's sidecar, and restoring them would put marker
spheres on the canvas and labels into the PNG export. Every load checks that
nothing was restored. No step here writes a sidecar.

The checks use the B-rep edges of mini_mold, projected, to keep sample points
away from lines: a sample point is at least 10 px from every edge (also the
hidden ones, which show in ワイヤーフレーム), and the bins of an edge band are
at least 8 px from every other edge.

Not named test_*.py, so the E2E loops do not run it on its own.
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

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

from nav_common import BASE_URL, BG, TESTDATA, box_stl, cross, dot, sub  # noqa: F401 (BG, box_stl: re-exported)

MOLD_SRC = TESTDATA / "mini_mold.step"
PLATE = ((0, 0, 0), (100, 60, 15))
BLOCK = ((30, 15, 15), (70, 45, 35))
PIN_R = 4
PIN_Z = (15, 40)
PIN1 = (25, 30)
PIN2 = (75, 30)
MARKER = (0xFF, 0xB0, 0x20)
CURVE = (0xE0, 0xB0, 0x50)  # loose curves (IGES construction lines)
S = (90, 10, 15)  # plate top, clear of the pins and the block
BLOCK_TOP = (50, 30, 35)
PIN1_TOP = (25, 30, 40)
# on pin1's side that faces the iso camera (angle -45 deg), 7 mm above the plate:
# seen through the block's y=15 and x=30 walls. Lower, the hidden back half of
# pin1's bottom circle projects onto it (1 px away at z = 19); higher, the view
# ray enters the block near its top front edge. At 22 every projected edge is
# about 20 px away (checked at run time).
Q = (25 + 4 * math.cos(-math.pi / 4), 30 + 4 * math.sin(-math.pi / 4), 22)
PLATE_FRONT_TOP = ((0, 0, 15), (100, 0, 15))
# the part of PLATE_FRONT_TOP an edge band looks at: in the iso view the hidden
# bottom-left edge of the plate crosses it on screen at x = 15 (t = 0.15)
EDGE_T = (0.2, 0.9)
LABELS = {"shaded-edges": "陰影＋稜線", "shaded": "陰影のみ", "wireframe": "ワイヤーフレーム", "xray": "半透明"}


# ---- geometry (pure) ----------------------------------------------------------
def box_edges(lo, hi):
    c = [[(hi if i & 1 else lo)[0], (hi if i & 2 else lo)[1], (hi if i & 4 else lo)[2]] for i in range(8)]
    return [(c[a], c[b]) for a in range(8) for b in range(a + 1, 8) if bin(a ^ b).count("1") == 1]


def pin_edges(cx, cy, n=64):
    """B-rep edges of a core pin: the two circles (as n-gons) and the seam at angle 0"""
    segs = []
    for z in PIN_Z:
        pts = [[cx + PIN_R * math.cos(2 * math.pi * k / n), cy + PIN_R * math.sin(2 * math.pi * k / n), z] for k in range(n)]
        segs += [(pts[k], pts[(k + 1) % n]) for k in range(n)]
    segs.append(([cx + PIN_R, cy, PIN_Z[0]], [cx + PIN_R, cy, PIN_Z[1]]))
    return segs


def mold_edges():
    return box_edges(*PLATE) + box_edges(*BLOCK) + pin_edges(*PIN1) + pin_edges(*PIN2)


def mold_vertices():
    v = [list(a) for a, _ in box_edges(*PLATE)] + [list(a) for a, _ in box_edges(*BLOCK)]
    for cx, cy in (PIN1, PIN2):
        v += [[cx + PIN_R, cy, z] for z in PIN_Z]
    return v


def seg_box(c, q, lo, hi):
    """slab test of segment c->q against a box: (entry parameter, entry axis) or None"""
    d = sub(q, c)
    t0, t1, axis = 0.0, 1.0, None
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if not lo[i] <= c[i] <= hi[i]:
                return None
            continue
        a, b = (lo[i] - c[i]) / d[i], (hi[i] - c[i]) / d[i]
        if a > b:
            a, b = b, a
        if a > t0:
            t0, axis = a, i
        t1 = min(t1, b)
        if t0 > t1:
            return None
    return t0, axis


def in_box(p, lo, hi, eps=0.0):
    return all(lo[i] - eps <= p[i] <= hi[i] + eps for i in range(3))


def in_pin(p, cxy, eps=0.0):
    return math.hypot(p[0] - cxy[0], p[1] - cxy[1]) <= PIN_R + eps and PIN_Z[0] - eps <= p[2] <= PIN_Z[1] + eps


def seg_clear(c, q, solids, n=2000, stop=0.999):
    """no sample of c->q (up to `stop`) inside any of the solids (callables p -> bool)"""
    for k in range(n + 1):
        t = stop * k / n
        p = [c[i] + (q[i] - c[i]) * t for i in range(3)]
        if any(f(p) for f in solids):
            return False
    return True


def pt_seg(p, a, b):
    p, a, b = np.asarray(p, float), np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    l2 = ab @ ab
    t = 0.0 if l2 == 0 else min(1.0, max(0.0, ((p - a) @ ab) / l2))
    return float(np.linalg.norm(p - (a + t * ab)))


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def seg_seg(a, b, c, d):
    """2D distance between segments ab and cd"""
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


def luminance(rgb):
    """WCAG relative luminance of 0-255 sRGB pixels (... x 3)"""
    c = np.asarray(rgb, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def tri_stl(path, tris):
    """ASCII STL of the given triangles (normals from the winding)"""
    lines = ["solid t"]
    for p in tris:
        n = cross(sub(p[1], p[0]), sub(p[2], p[0]))
        ln = math.sqrt(dot(n, n)) or 1
        lines.append(f"facet normal {n[0] / ln} {n[1] / ln} {n[2] / ln}\n outer loop")
        lines += [f"  vertex {q[0]} {q[1]} {q[2]}" for q in p]
        lines.append(" endloop\nendfacet")
    lines.append("endsolid t")
    Path(path).write_text("\n".join(lines))


def quad(a, b, c, d):
    return [(a, b, c), (a, c, d)]


def decode(data):
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(int)


def diff(a, b):
    return np.abs(np.asarray(a, float) - np.asarray(b, float))


# ---- the page -----------------------------------------------------------------
class Disp:
    """The page plus the helpers the display-style checks use."""

    def __init__(self, page, tmp, mold):
        self.page = page
        self.tmp = tmp
        self.mold = mold
        self.errors = []

    # -- loading and the GUI
    def load(self, path, wait_text="tris"):
        self.page.set_input_files("#file-input", path)
        self.page.wait_for_function(
            "([w, n]) => { const t = document.querySelector('#hud-info').textContent;"
            " return t.includes(w) && t.includes(n) }",
            arg=[wait_text, Path(path).name],
            timeout=60000,
        )
        self.settle()
        n = self.page.locator("#measure-list li").count()
        assert n == 0, ("a sidecar restored entries onto the canvas", path, n)

    def settle(self):
        self.page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def blur(self):
        self.page.evaluate("document.activeElement && document.activeElement.blur()")

    def view(self):
        return self.page.evaluate("window.__cadView()")

    def render_info(self):
        self.settle()
        return self.page.evaluate("window.__cadRenderInfo()")

    def ctl(self, name):
        label = self.page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
        return self.page.locator(".lil-gui .lil-controller").filter(has=label).first

    def style_select(self):
        return self.ctl("表示スタイル").locator("select")

    def style_label(self):
        return self.style_select().evaluate("s => s.selectedOptions[0].text")

    def select_style(self, key):
        """choose a style by its key (LABELS); the app blurs the select itself"""
        self.style_select().select_option(label=LABELS[key])
        self.settle()
        got = self.view()["displayStyle"]
        assert got == key, ("style not applied", key, got)

    def click_button(self, name):
        self.ctl(name).locator("button").click()
        self.settle()

    def set_mode(self, label):
        self.ctl("モード").locator("select").select_option(label)
        self.blur()

    def grid_off(self):
        if self.view()["gridVisible"]:
            self.ctl("グリッド").locator("input").click()
            self.blur()
        assert self.view()["gridVisible"] is False
        self.settle()

    def open_folder(self, name):
        title = self.page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$")).first
        folder = title.locator("xpath=..")
        if "lil-closed" in (folder.get_attribute("class") or ""):
            title.click()

    def check(self, name, on):
        box = self.ctl(name).locator("input")
        if box.is_checked() != on:
            box.click()
        self.blur()
        self.settle()

    def preset(self, name, fit=True):
        self.click_button(name)
        if fit:
            self.blur()
            self.page.keyboard.press("f")
        self.settle()

    # -- projections and picks
    def project(self, xyz):
        r = self.page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
        return (r["x"], r["y"])

    def project_many(self, pts):
        r = self.page.evaluate("ps => ps.map(([x, y, z]) => window.__cadProject(x, y, z))", [list(p) for p in pts])
        return [(q["x"], q["y"]) for q in r]

    def pick(self, xy):
        return self.page.evaluate("([x, y]) => window.__cadPick(x, y)", list(xy))

    def segments(self, edges=None):
        """projected edges (page px), mini_mold's B-rep edges by default"""
        edges = edges if edges is not None else mold_edges()
        pts = self.project_many([p for e in edges for p in e])
        return [(np.array(pts[2 * k]), np.array(pts[2 * k + 1])) for k in range(len(edges))]

    def clearance(self, pt, segs, exclude=()):
        return min(pt_seg(pt, a, b) for k, (a, b) in enumerate(segs) if k not in exclude)

    def assert_clear(self, pt, segs, tag, min_px=10, pick_point=False):
        d = self.clearance(pt, segs)
        assert d >= min_px, ("sample point too close to an edge", tag, round(d, 1))
        if pick_point:
            # the picker snaps to vertices within 14 px
            vs = self.project_many(mold_vertices())
            dv = min(math.dist(pt, v) for v in vs)
            assert dv >= 16, ("pick point too close to a vertex", tag, round(dv, 1))
        return d

    # -- pixels
    def canvas_origin(self):
        r = self.page.evaluate(
            "(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect(); return [r.left, r.top] })()"
        )
        return np.array(r, float)

    def frame(self):
        """the WebGL canvas as on screen (read inside rAF, right after the app's own render)"""
        url = self.page.evaluate(
            "new Promise(r => requestAnimationFrame(() =>"
            " r(document.querySelector('#viewport canvas').toDataURL())))"
        )
        return decode(base64.b64decode(url.split(",", 1)[1]))

    def px(self, img, xy):
        """3x3 mean around page point xy"""
        o = self.canvas_origin()
        cx, cy = int(math.floor(xy[0] - o[0])), int(math.floor(xy[1] - o[1]))
        return img[cy - 1 : cy + 2, cx - 1 : cx + 2].reshape(-1, 3).mean(axis=0)

    def band(self, img, p0, p1, bins=9, t0=0.1, t1=0.9):
        """pixels within 3 px of the projected segment p0-p1 (page px), between t0
        and t1, in `bins` bins along it; with each bin's `ends`, the pixels 6 px
        from the segment. Returns [(band pixels, end pixels)], each N x 3."""
        o = self.canvas_origin()
        a, b = np.asarray(p0, float) - o, np.asarray(p1, float) - o
        d = b - a
        L = np.linalg.norm(d)
        u, nrm = d / L, np.array([-d[1], d[0]]) / L
        x0, x1 = int(min(a[0], b[0])) - 8, int(max(a[0], b[0])) + 9
        y0, y1 = int(min(a[1], b[1])) - 8, int(max(a[1], b[1])) + 9
        h, w = img.shape[:2]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        ys, xs = np.mgrid[y0:y1, x0:x1]
        cx, cy = xs + 0.5 - a[0], ys + 0.5 - a[1]
        t = (cx * u[0] + cy * u[1]) / L
        dist = np.abs(cx * nrm[0] + cy * nrm[1])
        sel = (t >= t0) & (t <= t1)
        k = np.minimum(((t - t0) / (t1 - t0) * bins).astype(int), bins - 1)
        out = []
        for i in range(bins):
            m = sel & (k == i)
            out.append((img[y0:y1, x0:x1][m & (dist <= 3)], img[y0:y1, x0:x1][m & (np.abs(dist - 6) <= 0.5)]))
        return out

    def band_clear(self, p0, p1, segs, own, bins=9, t0=0.1, t1=0.9, min_px=8):
        """every bin of the band is at least min_px from every other projected edge"""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        worst = 1e9
        for i in range(bins):
            ta, tb = t0 + (t1 - t0) * i / bins, t0 + (t1 - t0) * (i + 1) / bins
            a, b = p0 + (p1 - p0) * ta, p0 + (p1 - p0) * tb
            for k, (c, d) in enumerate(segs):
                if k in own:
                    continue
                worst = min(worst, seg_seg(a, b, c, d))
        assert worst >= min_px, ("band too close to another edge", round(worst, 1))
        return worst

    def edge_mask(self, shape, segs, r=6):
        """pixels whose centre is within r px of any projected edge"""
        o = self.canvas_origin()
        h, w = shape[:2]
        mask = np.zeros((h, w), bool)
        for a, b in segs:
            a, b = a - o, b - o
            x0, x1 = max(0, int(min(a[0], b[0]) - r - 1)), min(w, int(max(a[0], b[0]) + r + 2))
            y0, y1 = max(0, int(min(a[1], b[1]) - r - 1)), min(h, int(max(a[1], b[1]) + r + 2))
            if x0 >= x1 or y0 >= y1:
                continue
            ys, xs = np.mgrid[y0:y1, x0:x1]
            px, py = xs + 0.5, ys + 0.5
            ab = b - a
            l2 = ab @ ab
            t = np.zeros_like(px) if l2 == 0 else np.clip(((px - a[0]) * ab[0] + (py - a[1]) * ab[1]) / l2, 0, 1)
            dx, dy = px - (a[0] + t * ab[0]), py - (a[1] + t * ab[1])
            mask[y0:y1, x0:x1] |= dx * dx + dy * dy <= r * r
        return mask

    def poly_mask(self, shape, pts):
        """pixels whose centre is inside the convex polygon pts (page px)"""
        o = self.canvas_origin()
        P = [np.asarray(p, float) - o for p in pts]
        h, w = shape[:2]
        ys, xs = np.mgrid[0:h, 0:w]
        px, py = xs + 0.5, ys + 0.5
        sign = None
        mask = np.ones((h, w), bool)
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            s = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
            area = sum(P[j][0] * P[(j + 1) % len(P)][1] - P[(j + 1) % len(P)][0] * P[j][1] for j in range(len(P)))
            sign = 1 if area > 0 else -1
            mask &= s * sign >= 0
        return mask

    # -- the mold's parts
    def mold_parts(self):
        """part ids from picks in the current view, and pin1's tree checkbox.

        Pin1's checkbox: hide the first core_pin and pick pin1's top again; if
        the answer changed, that box is pin1's, otherwise the second one is."""
        ids = {}
        for name, xyz in (("block", BLOCK_TOP), ("plate", S), ("pin1", PIN1_TOP)):
            hit = self.pick(self.project(xyz))
            assert hit, (name, "pick missed")
            ids[name] = hit["partId"]
        assert len(set(ids.values())) == 3, ids
        boxes = self.page.locator("#tree-panel label", has_text=re.compile("^core_pin$")).locator("input")
        assert boxes.count() == 2, boxes.count()
        first = boxes.nth(0)
        first.click()
        self.settle()
        hit = self.pick(self.project(PIN1_TOP))
        first.click()
        self.settle()
        pin1_box = first if (hit is None or hit["partId"] != ids["pin1"]) else boxes.nth(1)
        block_box = self.page.locator("#tree-panel label", has_text=re.compile("^cavity_block$")).locator("input").first
        return ids, pin1_box, block_box

    def toggle(self, box, on):
        if box.is_checked() != on:
            box.click()
        self.blur()
        self.settle()

    def iso_q_setup(self):
        """等角 view with a fit; check that Q is seen through the block's y=15 face.

        Returns (proj(Q), the point E where the view ray enters the block)."""
        self.preset("等角")
        C = self.view()["position"]
        hit = seg_box(C, Q, *BLOCK)
        assert hit, ("the ray to Q must cross the block", C)
        t, axis = hit
        E = [C[i] + (Q[i] - C[i]) * t for i in range(3)]
        assert axis == 1 and abs(E[1] - 15) < 1e-6 and 15 < E[2] < 35, ("enters through the y=15 face", E, axis)
        n = (math.cos(-math.pi / 4), math.sin(-math.pi / 4), 0)
        assert dot(n, sub(C, Q)) > 0, "pin1's surface at Q faces the camera"
        assert seg_clear(C, Q, [lambda p: in_box(p, *PLATE, -1e-6), lambda p: in_pin(p, PIN2)]), "the ray hits the plate or pin2"
        q = self.project(Q)
        self.assert_clear(q, self.segments(), "Q", pick_point=True)
        return q, E

    def see_through(self):
        """(c) toggle pin1 behind the block: the pixel at Q in RGB, pin shown minus hidden"""
        q, _ = self.iso_q_setup()
        _, pin1_box, _ = self.mold_parts()
        shown = self.px(self.frame(), q)
        self.toggle(pin1_box, False)
        hidden = self.px(self.frame(), q)
        self.toggle(pin1_box, True)
        return shown - hidden


@contextmanager
def display_session():
    """A fresh context (1280 x 800, devicePixelRatio 1, downloads) on the app,
    with cleared view preferences and a private copy of mini_mold.step.
    The page must log no errors; the temp files are removed afterwards."""
    tmp = tempfile.mkdtemp(prefix="cad_display_")
    try:
        mold = os.path.join(tmp, "display_mold.step")
        Path(mold).write_bytes(MOLD_SRC.read_bytes() + b"\n" * 11)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1, accept_downloads=True)
            page = context.new_page()
            d = Disp(page, tmp, mold)
            page.on("pageerror", lambda e: d.errors.append(str(e)))
            page.on("console", lambda m: d.errors.append(m.text) if m.type == "error" else None)
            page.goto(BASE_URL)
            page.evaluate("localStorage.removeItem('cad-viewer:view')")
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            yield d
            page.evaluate("localStorage.removeItem('cad-viewer:view'); localStorage.removeItem('cad-viewer:export')")
            if d.errors:
                print("PAGE ERRORS:", d.errors)
            assert not d.errors
            browser.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
