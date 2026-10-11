"""E2E: アンダーカットの候補 (docs/designs/undercut.md): what neither half of a straight pull reaches.

The expected classes come from how the part is made (testdata/
make_step_assembly.py make_undercut_block): a block 40 x 30 x 20 with a side
hole of R3 along y (axis x 10, z 10), a pocket of R3 from the top at (30, 8) to
z 10, and a hook: a post x 24..26, y 18..28 to z 30 with a lip over the top,
x 26..32, y 18..28, z 27..30. Pulled along Z the side hole's inside, the lip's
underside, the floor under it and the post's wall under it are undercuts:
2 pi 3 x 30 + 6 x 10 + 6 x 10 + 7 x 10 = 755.5 mm². Along Y the pocket is
(its wall and bottom: 2 pi 3 x 10 + pi 3² = 216.8 mm²), the side hole is not.
The class at a point is read from the value under the cursor, and the colour
from the canvas (classed by its hue).

Steps: Z: the area, the classes, the colour of an undercut; the light theme's
colours; Y; the section;
the draft's colouring and the candidates take over from each other; a measuring
mode keeps them; a new file ends them; a part hidden in the tree takes its
colours with it.
"""
import math
import re

import gui_common
from nav_common import TESTDATA, nav_session

PART = TESTDATA / "undercut_block.step"

HOLE = (10, 1.5, 7.2)  # the side hole's inside, its bottom near the front opening
FLOOR = (29, 19, 20)  # the block's top under the lip
TOP = (5, 25, 20)  # the block's top, nothing over it
# the pocket's far wall, 2 under its rim (seen through its opening from the load view, from +X -Y above)
POCKET = (30 - 3 / math.sqrt(2), 8 + 3 / math.sqrt(2), 18)
FRONT = (20, 0, 15)  # the front face (-Y)
LIP = (29, 23, 30)  # the lip's top

AREA_Z = 2 * math.pi * 3 * 30 + 60 + 60 + 70
AREA_Y = 2 * math.pi * 3 * 10 + math.pi * 9

UNDERCUT = "アンダーカットの候補（上にも下にも抜けない）"
UP = "上の型で抜ける"
DOWN = "下の型で抜ける"
BOTH = "上下どちらにも抜ける（型開き方向に沿った面）"


def magenta(rgb):
    r, g, b = rgb
    return r > g + 60 and r > b + 20


with nav_session() as nav:
    page = nav.page
    nav.load(PART)
    nav.ctl("グリッド").locator("input").click()
    nav.settle()

    def hud():
        return page.inner_text("#hud-info")

    def area():
        m = re.search(r"アンダーカットの候補: (\d+\.\d) mm²", hud())
        assert m, hud()
        return float(m.group(1))

    def tip_at(xyz):
        x, y = nav.project(xyz)
        page.mouse.move(x, y)
        page.wait_for_function("!document.querySelector('#cursor-tip').classList.contains('hidden')", timeout=5000)
        text = page.inner_text("#cursor-tip")
        page.mouse.move(5, 5)
        page.wait_for_function("document.querySelector('#cursor-tip').classList.contains('hidden')", timeout=5000)
        return text

    def tip_at_any(xyz):
        """the value under the cursor there, or None when there is none"""
        x, y = nav.project(xyz)
        page.mouse.move(x, y)
        nav.settle()
        page.wait_for_timeout(200)
        shown = not page.evaluate("document.querySelector('#cursor-tip').classList.contains('hidden')")
        text = page.inner_text("#cursor-tip") if shown else None
        page.mouse.move(5, 5)
        nav.settle()
        return text

    def expect(pts, tag):
        got = {k: tip_at(p) for k, (p, _) in pts.items()}
        bad = {k: got[k] for k, (_, want) in pts.items() if got[k] != want}
        assert not bad, (tag, "want", {k: w for k, (_, w) in pts.items()}, "got", got)

    def box(name):
        return nav.ctl(name).locator("input")

    def checked(name):
        nav.settle()  # .listen() updates the box on the next frame
        return box(name).evaluate("e => e.checked")

    def legend_shown():
        return page.locator("#undercut-legend").is_visible()

    def wait_area(direction):
        page.wait_for_function(
            f"document.querySelector('#hud-info').textContent.includes('mm²（型開き方向 {direction}）')", timeout=120000
        )

    # ---- along Z ---------------------------------------------------------------------
    nav.ctl("型開き方向").locator("select").select_option(label="+Z")
    box("アンダーカットの候補").click()
    wait_area("+Z")
    assert legend_shown()
    a = area()
    assert abs(a - AREA_Z) < 0.05 * AREA_Z, ("Z", a, AREA_Z)
    assert f"{a:.1f} mm²" in page.inner_text("#undercut-legend")
    expect(
        {"hole": (HOLE, UNDERCUT), "floor": (FLOOR, UNDERCUT), "top": (TOP, UP), "pocket": (POCKET, UP), "front": (FRONT, BOTH), "lip": (LIP, UP)},
        "Z",
    )
    rgb = nav.canvas_rgb([nav.project(HOLE), nav.project(FLOOR), nav.project(TOP)])
    assert magenta(rgb[0]) and magenta(rgb[1]) and not magenta(rgb[2]), ("the colours", rgb)

    # ---- the light theme: the colours made again, each at 3:1 against its background --------
    def contrast(c1, c2):
        def lum(c):
            f = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            r, g, b = (f(x / 255) for x in c)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        hi, lo = sorted((lum(c1), lum(c2)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def swatches():
        return [
            tuple(int(v) for v in re.findall(r"\d+", c)[:3])
            for c in page.eval_on_selector_all("#undercut-legend .draft-swatch", "els => els.map(e => getComputedStyle(e).backgroundColor)")
        ]

    dark = swatches()
    nav.ctl("配色").locator("select").select_option(label="ライト")
    nav.settle()
    light = swatches()
    assert light != dark and all(contrast(c, (0xE4, 0xE8, 0xED)) >= 3 for c in light), ("ライト", light)
    assert tip_at(HOLE) == UNDERCUT  # the classes stay
    nav.ctl("配色").locator("select").select_option(label="ダーク")
    nav.settle()
    assert swatches() == dark

    # ---- along Y: the pocket is one, the side hole is not --------------------------------
    nav.ctl("型開き方向").locator("select").select_option(label="+Y")
    wait_area("+Y")
    a = area()
    assert abs(a - AREA_Y) < 0.08 * AREA_Y, ("Y", a, AREA_Y)
    expect({"pocket": (POCKET, UNDERCUT), "hole": (HOLE, BOTH), "front": (FRONT, DOWN)}, "Y")
    nav.ctl("型開き方向").locator("select").select_option(label="+Z")
    wait_area("+Z")

    # ---- the section: what it cut away is not told under the cursor ------------------------
    # (X at the middle, 20: the +X half goes, the camera's side; the floor under the lip is there)
    section = gui_common.toolbar(page, "section")
    section.click()
    nav.settle()
    assert tip_at_any(FLOOR) != UNDERCUT, "the floor under the lip is cut away"
    section.click()
    nav.settle()
    assert tip_at(FLOOR) == UNDERCUT

    # ---- one colouring at a time ------------------------------------------------------
    box("色分け").click()
    assert checked("色分け") and not checked("アンダーカットの候補")
    assert not legend_shown() and page.locator("#draft-legend").is_visible()
    box("アンダーカットの候補").click()
    wait_area("+Z")
    assert not checked("色分け") and legend_shown()

    # ---- a measuring mode keeps them (the part is pickable under them) -------------------
    nav.ctl("モード").locator("select").select_option("計測")
    nav.settle()
    assert checked("アンダーカットの候補") and legend_shown()
    nav.ctl("モード").locator("select").select_option("なし")

    # ---- a new file ends them -----------------------------------------------------------
    nav.load(nav.paths["step"])  # mini_mold: a plate, two pins, a block on it, each a part
    assert not checked("アンダーカットの候補") and not legend_shown()

    # ---- a part hidden in the tree takes its colours with it ------------------------------
    # (the block's front wall, along the pull; behind it, the plate's top, from above).
    # Hidden before the candidates are put on, and after
    BLOCK_FRONT = (50, 15, 25)
    row = page.locator("#tree-panel label", has_text=re.compile("^cavity_block$")).locator("xpath=..")
    row.locator("input").click()
    nav.settle()
    box("アンダーカットの候補").click()
    page.wait_for_function(
        "(t => t.includes('mm²（型開き方向 +Z）') || t.includes('なし（型開き方向 +Z）'))"
        "(document.querySelector('#hud-info').textContent)",
        timeout=120000,
    )
    assert tip_at(BLOCK_FRONT) == UP, "the plate's top behind the block hidden before"
    row.locator("input").click()
    nav.settle()
    assert tip_at(BLOCK_FRONT) == BOTH
    row.locator("input").click()
    nav.settle()
    assert tip_at(BLOCK_FRONT) == UP, "the plate's top behind the hidden block"
    print("OK: アンダーカットの候補")
