"""E2E: wheel zoom toward the cursor (both rotate modes) — the B checks of the
navigation suite. Split from test_navigation.py so each script stays well under
the CI per-script limit. Helpers and the rule for expected values: nav_common.py.
"""
import math

from nav_common import (
    LOAD_DIR, MOLD, RUNNER, SURFACE,
    add, close, corners, cross, dot, length, mul, nav_session, norm, sub,
)

with nav_session() as n:
    page = n.page
    paths = n.paths
    STEP = paths["step"]  # private copy, empty sidecar (nav_session)
    load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
    canvas_rect, ctl, click_button, set_mode, set_rotate = n.canvas_rect, n.ctl, n.click_button, n.set_mode, n.set_rotate
    direction, same_dir, rect, fill_check, depth_check = n.direction, n.same_dir, n.rect, n.fill_check, n.depth_check
    plane_point, wheel, canvas_ink_rect = n.plane_point, n.wheel, n.canvas_ink_rect

    load(STEP)

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
        n.fit()

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
        # 0.729 per event: 250 mm -> the near stop takes ~20 events
        page.mouse.move(*cur)
        for i in range(30):
            page.mouse.wheel(0, -300)
            if i % 10 == 9:
                settle()
                assert math.dist(project(P), cur) <= 1, (mode, "B3 drift", i)
        settle()
        v = view()
        d = dot(sub(P, v["position"]), direction(v))
        assert d > v["near"], (mode, "passed the near plane", d, v["near"])
        # the stop itself (spec: 4 near-plane distances short of the point zoomed to)
        stop = math.dist(v["position"], P)
        assert abs(stop - 4 * v["near"]) <= 1e-6 * 4 * v["near"], (mode, "near stop", stop, v["near"])
        wheel(cur, -100, 2)
        v2 = view()
        assert close(v2["position"], v["position"], 1e-9), (mode, "zoomed past the stop")
        h = pick(cur)
        assert h and math.dist(h["point"], P) < 1e-3, (mode, "a nearer surface is hit now", h)
        dists = []
        # 0.5 mm -> the far-side stop (far/4) takes ~28 events
        page.mouse.move(*cur)
        for i in range(40):
            page.mouse.wheel(0, 300)
            if i % 10 == 9:
                settle()
                v = view()
                dists.append(math.dist(v["position"], v["target"]))
        assert abs(dists[-1] - dists[-2]) <= 1e-9 * dists[-1], (mode, "zoom-out never stops", dists[-3:])
        v = view()
        # where it stops (spec: camera to target = a quarter of the far plane)
        assert abs(dists[-1] - 0.25 * v["far"]) <= 1e-6 * v["far"], (mode, "far stop", dists[-1], v["far"])
        f = direction(v)
        for c in corners(*MOLD):
            assert dot(sub(c, v["position"]), f) < v["far"], (mode, "model beyond far")
        n.fit()

        # B4. a section: the clipped side is not a zoom point
        page.locator(".lil-gui .lil-title", has_text="断面").click()
        ctl("有効").locator("input").click()
        settle()
        # cur is over the plate top at x=90, clipped away (x <= 50 is kept). Behind
        # it the cursor's ray meets nothing on the kept side, so the zoom must go
        # to the target-plane point, never to the clipped plate top
        Q = pick(cur)
        assert Q is None, (mode, "picked through the section", Q)
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
        n.fit()  # waits for the 断面 folder to finish closing

        # B5. the page itself never scrolls
        assert page.evaluate("document.scrollingElement.scrollTop") == 0
    set_rotate("ターンテーブル")

    page.screenshot(path="/tmp/cad_viewer_nav_wheel.png")
    print("NAV WHEEL E2E OK")
