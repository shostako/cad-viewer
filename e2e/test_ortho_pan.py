"""E2E: the right-drag pan in parallel projection (投影 = 平行, #8 A3), both rotate modes.

Split from test_ortho_nav.py for the CI per-script limit: the turntable's pan
coasts out over many frames, and slow headless frames make that long.

Expected values never come from the code under test (rule of nav_common.py):
- turntable (OrbitControls): the point under the cursor follows the cursor,
  so a 200 px drag moves the target's projection 200 px, in both projections;
- 自由回転 (TrackballControls): the rate is measured in perspective (vertical,
  where it does not depend on the window's aspect; with the trackball's coast
  it is several times the drag), and parallel must give the same rate on both
  axes, for mini_mold and for a 0.05 mm box. TrackballControls
  scales a parallel pan by the camera's distance, which in parallel projection
  has nothing to do with the scale on screen: without a correction the rate
  would follow the model's size.

The coast is waited out by frame count: OrbitControls' damping keeps 0.95 of
the rest each frame (0.95^120 < 0.3 %), the trackball's 0.8 (0.8^40 < 1e-3).
"""
from nav_common import STEP, nav_session

DRAG = 200
TOL_TURNTABLE = 0.02
TOL_FREE = 0.03

with nav_session(boxes=("tiny",)) as n:
    page = n.page
    paths = n.paths
    n.stub_sidecar()
    load, settle, view, project = n.load, n.settle, n.view, n.project
    set_rotate, set_projection, centre = n.set_rotate, n.set_projection, n.centre

    def frames(k):
        page.evaluate(
            "k => new Promise(r => { let i = 0; const f = () => ++i >= k ? r() : requestAnimationFrame(f);"
            " requestAnimationFrame(f) })",
            k,
        )

    def fit():
        page.keyboard.press("f")
        settle()

    def pan_shift(dx, dy, coast_frames):
        """right-drag by (dx, dy) in 10 steps (a frame between them); the shift
        of the old target's projection once the coast is over"""
        t0 = view()["target"]
        p0 = project(t0)
        cx, cy = centre()
        x0, y0 = cx - dx / 2, cy - dy / 2 + 100
        page.mouse.move(x0, y0)
        page.mouse.down(button="right")
        for i in range(1, 11):
            page.mouse.move(x0 + dx * i / 10, y0 + dy * i / 10)
            frames(1)
        page.mouse.up(button="right")
        frames(coast_frames)
        p1 = project(t0)
        return p1[0] - p0[0], p1[1] - p0[1]

    load(STEP)

    # turntable: the scene follows the cursor in both projections
    for proj in ("透視", "平行"):
        set_projection(proj)
        fit()
        sx, sy = pan_shift(0, -DRAG, 120)
        print("turntable", proj, round(sx, 2), round(sy, 2))
        assert abs(abs(sy) / DRAG - 1) <= TOL_TURNTABLE and abs(sx) <= 2, ("turntable", proj, sx, sy)

    # 自由回転: parallel pans at the perspective trackball's vertical rate
    set_projection("透視")
    n.setup_view("自由回転")
    _, s_p = pan_shift(0, -DRAG, 40)
    s_p = abs(s_p)
    print("free perspective", round(s_p, 2))
    assert s_p > DRAG / 2, ("the perspective drag did not pan", s_p)
    set_projection("平行")
    fit()
    _, sy = pan_shift(0, -DRAG, 40)
    sx, _ = pan_shift(DRAG, 0, 40)
    print("free parallel", round(sx, 2), round(sy, 2))
    assert abs(abs(sy) / s_p - 1) <= TOL_FREE and abs(abs(sx) / s_p - 1) <= TOL_FREE, ("parallel rate", sx, sy, s_p)
    load(paths["tiny"])
    assert view()["projection"] == "orthographic"
    n.setup_view("自由回転")
    _, sy = pan_shift(0, -DRAG, 40)
    print("free parallel tiny", round(sy, 2))
    assert abs(abs(sy) / s_p - 1) <= TOL_FREE, ("parallel rate (tiny)", sy, s_p)
    set_rotate("ターンテーブル")

    page.screenshot(path="/tmp/cad_viewer_ortho_pan.png")
    print("ORTHO PAN E2E OK")
