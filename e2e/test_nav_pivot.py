"""E2E: double-click sets the rotation centre (both rotate modes) — the C checks
of the navigation suite. Split from test_navigation.py so each script stays well
under the CI per-script limit. Helpers and the rule for expected values: nav_common.py.

"Mid-screen" is the view centre: the centre of the free area a fit framed
the model in (Nav.view_centre, from the panels' rects), not the canvas centre.
"""
import math

from nav_common import (
    LOAD_DIR, RUNNER, SURFACE,
    add, close, dot, mul, nav_session, norm, sub,
)

with nav_session(boxes=("runner",)) as n:
    page = n.page
    paths = n.paths
    STEP = paths["step"]  # private copy, empty sidecar (nav_session)
    load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
    canvas_rect, ctl, click_button, set_mode, set_rotate = n.canvas_rect, n.ctl, n.click_button, n.set_mode, n.set_rotate
    direction, same_dir, rect, fill_check, depth_check = n.direction, n.same_dir, n.rect, n.fill_check, n.depth_check
    
    load(STEP)

    # ============ C. double-click rotation centre ================================
    centre = n.view_centre()

    def setup(mode):
        global centre
        set_rotate(mode)
        click_button("等角")
        if mode == "自由回転":
            for _ in range(7):
                page.keyboard.press("ArrowUp")
            for _ in range(3):
                page.keyboard.press("ArrowRight")
        n.fit()
        centre = n.view_centre()

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
        # no marker left from before: the one awaited below is this click's
        page.wait_for_selector(".pivot-marker", state="detached", timeout=2000)
        page.mouse.dblclick(*cur)
        # the marker enters the page with the next drawn frame (on a loaded machine, after the
        # double-click has returned) and stays 1 s from the click: read at most 500 + 300 ms in
        page.wait_for_selector(".pivot-marker", state="attached", timeout=500)
        page.wait_for_timeout(300)  # the slide (250 ms from the click) is over
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
    n.fit()
    centre = n.view_centre()

    # C6. an interruption finishes the slide (the new centre is kept)
    Qp = (50, 30, 35)  # top of the cavity block
    curq = tuple(round(c) for c in project(Qp))
    Q = pick(curq)["point"]
    page.mouse.dblclick(*curq)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    assert close(view()["target"], Q, 1e-4), ("C6", view()["target"], Q)
    assert math.dist(project(Q), centre) <= 0.5
    n.fit()
    centre = n.view_centre()

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
    # back to a known view: how far auto-rotate turned depends on the machine's
    # timing, and C8-C11 aim at points that other parts hide from some
    # directions (after about 1.25 s of spinning, C11's plate point lies behind
    # the cavity block and the pick finds the block's edge)
    setup("自由回転")

    # C8. a section: the clipped side is never the centre
    page.locator(".lil-gui .lil-title", has_text="断面").click()
    ctl("有効").locator("input").click()
    settle()
    cur = tuple(round(c) for c in project(SURFACE))
    # the plate top under cur (x=90) is clipped away and the ray meets nothing on
    # the kept side (x <= 50): a double-click there must not set a centre
    Q = pick(cur)
    assert Q is None, ("C8 picked through the section", Q)
    v0 = view()
    page.mouse.dblclick(*cur)
    page.wait_for_timeout(500)
    assert close(view()["target"], v0["target"], 1e-12), ("C8 centred on a clipped point", view()["target"])
    ctl("有効").locator("input").click()
    page.locator(".lil-gui .lil-title", has_text="断面").click()

    # C10. a wheel step during the slide zooms from the slide's end pose: at the
    # view centre that is P itself (or the plate-top point under the whole pixel
    # the wheel lands on), so the target stays on P (picking in the in-between
    # pose would zoom about another point and move the target off P)
    # The wheel must land while the 250 ms slide is still running. Timing two
    # separate inputs cannot promise that (on the CI runner the slide ended first
    # every time), so the wheel is sent from inside the page: a one-shot window
    # dblclick listener runs after the viewer's own (on #viewport) has started
    # the slide, and dispatches the wheel in the next task. The camera state
    # when the wheel arrives is recorded (window capture runs first) to prove it.
    n.fit()  # waits for the 断面 folder of C8 to finish closing
    centre = n.view_centre()
    # a synthetic WheelEvent carries whole pixels (Chrome drops the fraction),
    # and the view centre can be at .5 (the free area is 703 px tall)
    w = [math.floor(c) for c in centre]
    cur = tuple(round(c) for c in project(SURFACE))
    P = pick(cur)["point"]
    v0 = view()
    f0 = direction(v0)
    depth = dot(sub(P, v0["position"]), f0)
    page.evaluate(
        """([cx, cy]) => {
             const vp = document.querySelector('#viewport')
             window.addEventListener('wheel', () => { window.__atWheel = window.__cadView() },
                                     { capture: true, once: true })
             window.addEventListener('dblclick', () => setTimeout(() => vp.dispatchEvent(
               new WheelEvent('wheel', { deltaY: -100, clientX: cx, clientY: cy, bubbles: true, cancelable: true })
             ), 0), { once: true })
           }""",
        w,
    )
    page.mouse.dblclick(*cur)
    page.wait_for_timeout(400)
    at = page.evaluate("window.__atWheel")
    assert at and math.dist(at["target"], P) > 1e-3, ("C10 the wheel did not land mid-slide", at and at["target"], P)
    v = view()
    # the zoom point stays under the cursor: after the zoom it is the surface
    # point under w (within a pixel of P). The slide ends with the target on P
    # and the camera depth behind it (no turn, no zoom); one notch scales both
    # by 0.9 about the zoom point
    Z = pick(w)["point"]
    assert math.dist(Z, P) < 0.5, ("C10 zoom point", Z, P)
    end_cam = add(P, mul(f0, -depth))
    want_t = add(Z, mul(sub(P, Z), 0.9))
    want_c = add(Z, mul(sub(end_cam, Z), 0.9))
    assert close(v["target"], want_t, 1e-4), ("C10 target", v["target"], want_t, P)
    assert math.dist(v["position"], want_c) <= 1e-6 * depth, ("C10 camera", v["position"], want_c)

    # C11. a second double-click during the slide starts from the pose on
    # screen: it never jumps to the first slide's end first
    n.fit()
    centre = n.view_centre()
    cur1 = tuple(round(c) for c in project(SURFACE))
    cur2 = tuple(round(c) for c in project((10, 5, 15)))  # plate top, near the front left corner
    hit2 = pick(cur2)
    assert hit2 and hit2["kind"] == "face", ("C11 cur2 must be on a face", cur2, hit2, view())
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
    n.fit()
    page.mouse.dblclick(*tuple(round(c) for c in project(SURFACE)))
    load(paths["runner"])
    page.wait_for_timeout(400)
    v = view()
    assert close(norm(sub(v["position"], v["target"])), LOAD_DIR, 1e-9), v
    fill_check(*RUNNER, "reload mid-slide")
    assert marker_rect() is None

    page.screenshot(path="/tmp/cad_viewer_navigation.png")
    print("NAV PIVOT E2E OK")
