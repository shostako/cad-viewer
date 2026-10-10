"""E2E: the section in mm, its cut toward the camera, a thin frame (issue #23, "あとで" 1).

mini_mold (make_step_assembly.py): plate 100 x 60 x 15, block 30..70 x 15..45
up to z 35, pins at x 25 / 75. The opening view looks from +X, -Y, +Z.

- Put in (S), the section cuts away the side the camera is on, so the cut
  faces it: along X the +X half goes (as before), along Y now the -Y half
  (before, the +Y half went and the cut faced away: nothing seemed to happen),
  along Z the top. 反転 shows the side chosen.
- Turned to the other side (-X, +Y), the section put in again cuts the +Y half.
- 位置 (mm) is the plane's place along the axis in mm: typed 20, the cut is at
  x 20. A new axis starts from the middle of the model along it.
- The plane is drawn as a thin frame around the model's cross-section, not a
  filled square: the plane outside the frame is the background.

Oracles: __cadPick on either side of the expected cut (the picker clips as
the view does), the known heights and extents of mini_mold, canvas pixels on
the plane outside the model, the operation panel's 反転 and 位置 (mm).
"""
import gui_common
from nav_common import nav_session

BG = (0x1D, 0x21, 0x26)

with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    n.load(n.paths["step"])

    def hits(q):
        """the pick at q's projection lands on q (the model is there, not cut away)"""
        h = n.pick(n.project(q))
        return bool(h) and all(abs(a - b) < 0.5 for a, b in zip(h["point"], q))

    def axis(a):
        gui_common.ctl(page, "軸").locator("select").select_option(a)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        n.settle()

    def flip():
        return gui_common.ctl(page, "反転").locator("input").is_checked()

    def pos():
        return float(gui_common.ctl(page, "位置 (mm)").locator("input").first.input_value())

    def section(on):
        btn = gui_common.toolbar(page, "section")
        if (btn.get_attribute("aria-pressed") == "true") != on:
            page.keyboard.press("s")
        n.settle()

    # the plate's top on either side of each cut, and the block's top
    assert hits((90, 10, 15)) and hits((90, 50, 15)) and hits((50, 30, 35)), "the model before the section"

    # ---- 1. X (the default): the +X half goes, toward the camera
    section(True)
    assert pos() == 50 and not flip(), (pos(), flip())
    assert not hits((90, 10, 15)) and hits((10, 10, 15)), "1 X: the +X half must go"

    # ---- 2. Y: the -Y half goes now (the camera is at -Y), 反転 shows it
    axis("Y")
    assert pos() == 30 and flip(), ("2 Y from the middle, toward the camera", pos(), flip())
    assert not hits((90, 10, 15)) and hits((90, 50, 15)), "2 Y: the -Y half must go"

    # ---- 3. Z: the top goes (the camera is above)
    axis("Z")
    assert pos() == 20 and not flip(), (pos(), flip())
    assert not hits((50, 30, 35)) and hits((90, 10, 15)), "3 Z: the top must go"

    # ---- 4. from the other side (-X, +Y): along Y the +Y half goes
    axis("Y")
    section(False)
    for _ in range(36):  # 5 degrees a press: half a turn about the vertical
        page.keyboard.press("ArrowLeft")
    n.settle()
    section(True)
    assert not flip(), "4 the camera at +Y: the lower side stays"
    assert not hits((10, 50, 15)) and hits((10, 10, 15)), "4 from +Y the +Y half must go"
    section(False)
    gui_common.toolbar(page, "fit").click()
    n.click_button("等角")

    # ---- 5. 位置 (mm): typed 20 along X, the cut is at x 20
    section(True)
    axis("X")
    field = gui_common.ctl(page, "位置 (mm)").locator("input").first
    field.fill("20")
    field.press("Enter")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    n.settle()
    assert pos() == 20, pos()
    assert hits((18, 10, 15)) and not hits((22, 10, 15)), "5 the cut at x 20"
    # a new axis starts from the middle (Z: 20 of 0..40), not at the same fraction (8)
    axis("Z")
    assert pos() == 20, ("5 Z from the middle", pos())

    # ---- 6. the plane is a thin frame: on the plane, outside the frame, the background
    gui_common.ctl(page, "グリッド").locator("input").click()  # no floor lines behind the samples
    n.settle()
    axis("X")  # x 50, the middle
    assert pos() == 50, pos()
    # x 50, y -10 and -13, low (the model is y 0..60, the frame 3.7 mm outside
    # it; the old filled square reached y -16): the line of sight beyond them
    # meets nothing, the grid is off
    pts = [n.project((50, y, z)) for y, z in ((-10, 3), (-10, 8), (-13, 5), (-13, 12))]
    px = n.canvas_rgb(pts)
    print("6 on the plane outside the frame", px)
    assert all(max(abs(a - b) for a, b in zip(c, BG)) <= 6 for c in px), ("6 the plane is filled", px)
    gui_common.ctl(page, "グリッド").locator("input").click()
    section(False)

    print("SECTION MM E2E OK")
