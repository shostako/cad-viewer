"""E2E: double-click sets the rotation centre (both rotate modes) — the C checks
of the navigation suite. Split from test_navigation.py so each script stays well
under the CI per-script limit. Helpers and the rule for expected values: nav_common.py.
"""
import math

from nav_common import (
    LOAD_DIR, RUNNER, STEP, SURFACE,
    close, dot, nav_session, norm, sub,
)

with nav_session(boxes=("runner",)) as n:
    page = n.page
    paths = n.paths
    load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
    canvas_rect, ctl, click_button, set_mode, set_rotate = n.canvas_rect, n.ctl, n.click_button, n.set_mode, n.set_rotate
    direction, same_dir, rect, fill_check, depth_check = n.direction, n.same_dir, n.rect, n.fill_check, n.depth_check
    
    load(STEP)

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
    # canvas centre that is P itself, so the target stays P (picking in the
    # in-between pose would zoom about another point and move the target off P)
    # The camera state when the wheel event arrives is recorded (window capture
    # runs before the viewer's listener), to prove the wheel really landed
    # mid-slide. On a slow machine the 250 ms slide may end first: then retry.
    page.evaluate(
        """() => window.addEventListener('wheel', () => { window.__atWheel = window.__cadView() },
                                         { capture: true })"""
    )
    for attempt in range(3):
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
        at = page.evaluate("window.__atWheel")
        if math.dist(at["target"], P) > 1e-3:
            break  # the wheel arrived while the target was still on its way to P
        print("C10 slide ended before the wheel, retrying", attempt)
    else:
        raise AssertionError("C10 could not send the wheel during the slide")
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
    print("NAV PIVOT E2E OK")
