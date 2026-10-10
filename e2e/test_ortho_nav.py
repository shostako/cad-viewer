"""E2E: navigation in parallel projection (投影 = 平行, #8 A3).

The same navigation as perspective (test_nav_*.py) must work with the parallel
camera: wheel zoom toward the cursor and its stops, the controls' own dolly,
keys, the double-click pivot, picking with snaps, measure markers, auto-rotate
and the PNG export. The drag pans are in test_ortho_pan.py (kept apart for the
CI per-script limit).

Expected values never come from the code under test (rule of nav_common.py).
The parallel zoom limits come from the specification: the visible
half-heights perspective shows at its own wheel stops after a fit of mini_mold
(r = half its diagonal, near = r / 500, far = 200 r):
hMin = 4 near tan 25°, hMax = 0.25 far tan 25°.

N1 wheel toward a surface; N2 over empty space; N3 the stops; N4 a section;
N5 keys; N6 the controls' dolly (middle drag) stays within the stops; N7 the
double-click pivot; N8 picks, snaps and measure markers; N9 auto-rotate; N10
the PNG export.
"""
import math

import numpy as np
from PIL import Image

from nav_common import MOLD, STEP_SRC, SURFACE, close, dot, length, nav_session, norm, sub

# the shared mini_mold.step: this script keeps sidecars in the page (stub_sidecar)
STEP = str(STEP_SRC)

CAV_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)
R_MOLD = length(sub(MOLD[1], MOLD[0])) / 2
T25 = math.tan(math.radians(25))
H_MIN = 4 * (R_MOLD / 500) * T25
H_MAX = 0.25 * 200 * R_MOLD * T25
MARKER = (0xFF, 0xB0, 0x20)

with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
    ctl, click_button, set_mode, set_rotate, set_projection = n.ctl, n.click_button, n.set_mode, n.set_rotate, n.set_projection
    direction, same_dir, depth_check, plane_point, wheel = n.direction, n.same_dir, n.depth_check, n.plane_point, n.wheel
    kscale, hv, canvas_rect, centre = n.kscale, n.visible_half_height, n.canvas_rect, n.centre

    def frame():
        page.evaluate("new Promise(r => requestAnimationFrame(r))")

    def fit():
        n.fit()  # records the panels the fit saw (fill_check compares them)

    def drag(button, x0, y0, dx, dy, steps):
        """a drag in steps with a frame between them. A big jump inside one frame
        can make the trackball skip its zoom (factor 1 + dy * speed <= 0); at
        60 px per frame its factor stays above 0.5."""
        page.mouse.move(x0, y0)
        page.mouse.down(button=button)
        for i in range(1, steps + 1):
            page.mouse.move(x0 + dx * i / steps, y0 + dy * i / steps)
            frame()
        page.mouse.up(button=button)

    load(STEP)
    set_projection("平行")
    assert view()["projection"] == "orthographic"
    print("limits", H_MIN, H_MAX)

    for mode in ("ターンテーブル", "自由回転"):
        n.setup_view(mode)

        # ---- N1. wheel toward a surface: the point stays under the cursor ------
        cur = tuple(round(c) for c in project(SURFACE))
        hit = pick(cur)
        assert hit and hit["kind"] == "face", (mode, hit)
        P = hit["point"]
        v_start = view()
        k_start = kscale(v_start)
        for _ in range(5):
            v0 = view()
            k0 = kscale(v0)
            wheel(cur, -100)
            v1 = view()
            assert math.dist(project(P), cur) <= 0.5, (mode, "N1 drift", project(P), cur)
            assert abs(kscale(v1) / k0 - 1 / 0.9) <= 1e-6, (mode, "N1 step", kscale(v1) / k0)
            kt = math.dist(v1["target"], P) / math.dist(v0["target"], P)
            assert abs(kt - 0.9) <= 1e-6, (mode, "N1 zoomed about another point", kt)
            same_dir(v0, v1)
        for _ in range(5):
            wheel(cur, 100)
        v = view()
        assert close(v["target"], v_start["target"], 1e-6 * R_MOLD), (mode, v["target"], v_start["target"])
        assert abs(kscale(v) / k_start - 1) <= 1e-6, (mode, "N1 back", kscale(v), k_start)
        print("N1", mode, "ok")

        # ---- N2. over empty space: the target-plane point stays under the cursor -
        empty = (640, 22)
        assert pick(empty) is None, (mode, "N2 not empty")
        A = plane_point(empty)
        for _ in range(3):
            k0 = kscale()
            wheel(empty, -100)
            assert math.dist(project(A), empty) <= 0.5, (mode, "N2 drift", project(A))
            assert abs(kscale() / k0 - 1 / 0.9) <= 1e-6, (mode, "N2 step")
        for _ in range(3):
            wheel(empty, 100)
        print("N2", mode, "ok")

        # ---- N3 / N6. the wheel's stops, and the controls' dolly (middle drag)
        # stays within them: one notch back from a stop, then a 600 px drag on
        # past it (OrbitControls: x 0.95^6 = 0.74, the trackball: more)
        cx, cy = centre()
        page.mouse.move(*cur)
        for i in range(20):
            page.mouse.wheel(0, -300)
            if i % 10 == 9:
                settle()
                assert math.dist(project(P), cur) <= 1, (mode, "N3 drift", i)
        settle()
        assert abs(hv() / H_MIN - 1) <= 1e-6, (mode, "N3 near stop", hv(), H_MIN)
        h = pick(cur)
        assert h and math.dist(h["point"], P) < 1e-3, (mode, "N3 pick at the stop", h)
        depth_check(*MOLD)
        v = view()
        wheel(cur, -100, 2)
        assert close(view()["position"], v["position"], 1e-9 * R_MOLD) and view()["zoom"] == v["zoom"], (mode, "past the stop")
        page.keyboard.press("-")
        drag("middle", cx, cy + 280, 0, -600, 10)  # up: magnify
        page.wait_for_timeout(1000)
        settle()
        assert abs(hv() / H_MIN - 1) <= 1e-6, (mode, "N6 dolly passed hMin", hv(), H_MIN)
        page.mouse.move(*cur)
        for i in range(30):
            page.mouse.wheel(0, 300)
        settle()
        assert abs(hv() / H_MAX - 1) <= 1e-6, (mode, "N3 far stop", hv(), H_MAX)
        depth_check(*MOLD)
        page.keyboard.press("+")
        drag("middle", cx, cy - 320, 0, 600, 10)  # down: shrink
        page.wait_for_timeout(1000)
        settle()
        assert abs(hv() / H_MAX - 1) <= 1e-6, (mode, "N6 dolly passed hMax", hv(), H_MAX)
        depth_check(*MOLD)
        print("N3/N6", mode, "ok")
        fit()

        # ---- N7. double-click pivot ------------------------------------------------
        cur = tuple(round(c) for c in project(SURFACE))
        P = pick(cur)["point"]
        v0 = view()
        k0 = kscale(v0)
        page.mouse.dblclick(*cur)
        assert n.marker_rect() is not None, (mode, "N7 marker")
        page.wait_for_timeout(400)
        v1 = view()
        assert close(v1["target"], P, 1e-6 * R_MOLD), (mode, "N7 target", v1["target"], P)
        # the view centre: where a fit puts the target (the free area's centre)
        assert math.dist(project(P), n.view_centre()) <= 0.5, (mode, "N7 centre", project(P), n.view_centre())
        assert abs(kscale(v1) / k0 - 1) <= 1e-9, (mode, "N7 zoom changed", kscale(v1), k0)
        same_dir(v0, v1)
        print("N7", mode, "ok")
        fit()
    set_rotate("ターンテーブル")
    n.setup_view("ターンテーブル")

    # ---- N4. a section: the clipped side is not a zoom point --------------------
    page.locator(".lil-gui .lil-title", has_text="断面").click()
    ctl("有効").locator("input").click()
    settle()
    cur = tuple(round(c) for c in project(SURFACE))
    assert pick(cur) is None, "N4 picked through the section"
    A = plane_point(cur)
    k0 = kscale()
    wheel(cur, -100)
    assert math.dist(project(A), cur) <= 0.5, ("N4 drift", project(A), cur)
    assert abs(kscale() / k0 - 1 / 0.9) <= 1e-6, "N4 step"
    ctl("有効").locator("input").click()
    page.locator(".lil-gui .lil-title", has_text="断面").click()
    fit()
    print("N4 ok")

    # ---- N5. keys ---------------------------------------------------------------
    page.mouse.click(640, 22)  # focus the page (mode なし: a click picks nothing)
    v0 = view()
    k0 = kscale(v0)
    t0 = v0["target"]
    p0 = project(t0)
    page.keyboard.press("+")
    v1 = view()
    assert abs(kscale(v1) / k0 - 1 / 0.9) <= 1e-6, ("N5 +", kscale(v1) / k0)
    assert close(v1["target"], t0, 1e-9 * R_MOLD) and math.dist(project(t0), p0) <= 1e-6, "N5 + moved the target"
    same_dir(v0, v1)
    page.mouse.move(*centre())  # most of the way in by wheel, the rest by key
    for _ in range(15):
        page.mouse.wheel(0, -300)
    settle()
    for _ in range(10):
        page.keyboard.press("+")
    assert abs(hv() / H_MIN - 1) <= 1e-6, ("N5 + stop", hv(), H_MIN)
    ch = canvas_rect()[3]
    t0 = view()["target"]
    p0 = project(t0)
    page.keyboard.press("Shift+ArrowRight")
    p1 = project(t0)
    assert abs((p0[0] - p1[0]) - 0.05 * ch) <= 0.5 and abs(p1[1] - p0[1]) <= 0.5, ("N5 Shift+→", p0, p1, ch)
    fit()
    v0 = view()
    page.keyboard.press("ArrowRight")
    v1 = view()
    d0, d1 = direction(v0), direction(v1)
    turned = math.degrees(math.atan2(d0[0] * d1[1] - d0[1] * d1[0], d0[0] * d1[0] + d0[1] * d1[1]))
    assert abs(abs(turned) - 5) <= 1e-6 * 57.3 and abs(d0[2] - d1[2]) <= 1e-9, ("N5 → turn", turned, d0, d1)
    fit()
    print("N5 ok")

    # ---- N8. picks, snaps and measure markers -----------------------------------
    click_button("等角")
    fit()

    def toward(a, b, px):
        pa, pb = project(a), project(b)
        d = norm(sub(pb, pa))
        return (pa[0] + d[0] * px, pa[1] + d[1] * px)

    h = pick(toward((100, 60, 15), (50, 30, 15), 8))
    assert h and h["kind"] == "vertex" and math.dist(h["point"], (100, 60, 15)) < 1e-3, ("N8 vertex", h)
    h = pick(toward((50, 0, 15), (50, 30, 15), 6))
    assert h and h["kind"] == "edge", ("N8 edge", h)
    h = pick(project(SURFACE))
    assert h and h["kind"] == "face", ("N8 face", h)
    set_mode("計測")
    page.mouse.click(*project(CAV_TOP))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    settle()
    img = np.asarray(n.canvas_image()).astype(int)
    mask = np.abs(img - np.array(MARKER)).max(axis=2) <= 40
    ys, xs = np.nonzero(mask)
    assert len(xs), "N8 no marker drawn"
    s = img.shape[1] / canvas_rect()[2]
    bw, bh = (xs.max() - xs.min() + 1) / s, (ys.max() - ys.min() + 1) / s
    print("N8 marker bbox", bw, bh)
    assert 4 <= bw <= 14 and 4 <= bh <= 14, ("N8 marker size", bw, bh)
    page.mouse.click(*project(PLATE_TOP))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離 20.000')", timeout=10000)
    click_button("計測クリア")
    set_mode("なし")
    print("N8 ok")

    # ---- N9. auto-rotate ------------------------------------------------------------
    a = direction()
    ctl("自動回転").locator("input").click()
    page.wait_for_timeout(1000)
    ctl("自動回転").locator("input").click()
    turned = math.degrees(math.acos(min(1, dot(a, direction()))))
    print("N9 turned", round(turned, 1))
    assert 10 < turned < 80, ("N9", turned)
    fit()

    # ---- N10. the PNG export is the frame on screen ----------------------------------
    screen = np.asarray(n.canvas_image()).astype(int)
    with page.expect_download(timeout=15000) as info:
        page.locator("#toolbar button[data-action='png']").click()
    png = Image.open(info.value.path()).convert("RGB")
    out = np.asarray(png).astype(int)
    assert out.shape == screen.shape, (out.shape, screen.shape)
    diff = np.abs(out - screen).max()
    print("N10 export vs screen", diff)
    assert diff <= 3, ("N10 export differs from the screen", diff)

    page.screenshot(path="/tmp/cad_viewer_ortho_nav.png")
    print("ORTHO NAV E2E OK")
