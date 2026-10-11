"""E2E: 版の比較 (docs/designs/compare.md): two versions of a part, coloured by what was added and removed.

The expected colours come from how the versions are made (testdata/
make_step_assembly.py make_revisions): a plate 60 x 40 x 3 in both; the first
(revision_a) with a boss of R4 at (15, 20) to z 11 and a rib at x 44.25..45.75,
y 8..32, to z 9; the next (revision_b) with that boss to z 13 (2 higher), a new
boss of R3 at (30, 30) to z 8, and no rib. revision_b is opened, revision_a
compared with it. The colour on screen is read from the canvas at projected
points (window.__cadProject) and classed by its hue: blue-green (added),
red-orange (removed), grey (unchanged).

Steps: the comparison and its line; 重ねる (the new version, the removed rib
over it); 新しい版だけ, 前の版だけ; the tolerance; 新しいのは turned the other
way; the section cuts it; the value under the cursor; the light theme's
colours; a measuring mode ends it; a drawing refused; a part hidden in the tree
is compared all the same; a new file ends it.
"""
import math
import re

import gui_common
from nav_common import DXF, STEP_SRC, TESTDATA, nav_session

NEW = TESTDATA / "revision_b.step"
OLD = TESTDATA / "revision_a.step"

BOSS_TOP = (15, 21, 13)  # the raised boss's top (+2 on the new version)
OLD_BOSS_TOP = (15, 20.5, 11)  # the first version's boss top: inside the new boss, 2 under its top
NEW_BOSS_TOP = (30, 30.5, 8)  # the new boss's top (+5)
NEW_BOSS_FOOT = (30, 30.5, 3)  # the first version's plate top under the new boss: inside it, 3 from its side
RIB_TOP = (45, 20, 9)  # the rib's top (the first version only: -6)
RIB_FOOT = (45, 20, 3)  # the new version's plate top where the rib stood: inside the rib, 0.75 from its sides
PLATE = (8, 6, 3)  # far from every change


def hue(rgb):
    """the class of a rendered colour: 'added' (blue-green), 'removed' (red-orange), 'same' (grey) or '?'"""
    r, g, b = rgb
    # blue-green: green over red, and at least as strong as blue (the parts' own
    # light blue has more blue than green)
    if g > r + 25 and g >= b - 8:
        return "added"
    if r > g + 25 and r > b + 25:
        return "removed"
    if max(rgb) - min(rgb) <= 18 and max(rgb) > 60:
        return "same"
    return "?"


with nav_session() as nav:
    page = nav.page
    nav.load(NEW)

    def hud():
        return page.inner_text("#hud-info")

    def classes(pts):
        nav.settle()
        rgb = nav.canvas_rgb([nav.project(p) for p in pts.values()])
        return {k: (hue(c), c) for k, c in zip(pts, rgb)}

    def expect(pts, tag):
        got = classes({k: p for k, (p, _) in pts.items()})
        bad = {k: got[k] for k, (_, want) in pts.items() if got[k][0] != want}
        assert not bad, (tag, "want", {k: w for k, (_, w) in pts.items()}, "got", got)

    def compare_with(path):
        with page.expect_file_chooser() as fc:
            nav.ctl("別の版と比べる").locator("button").click()
        fc.value.set_files(str(path))

    def select(name, label):
        nav.ctl(name).locator("select").select_option(label=label)
        nav.settle()

    def legend_shown():
        return page.locator("#compare-legend").is_visible()

    # the grid lies in the plate's bottom plane; off, it cannot tint the samples
    nav.ctl("グリッド").locator("input").click()
    nav.settle()
    before = classes({"new boss": NEW_BOSS_TOP})["new boss"]
    assert before[0] != "added", ("the model's own colour is not the added colour", before)

    # ---- the comparison --------------------------------------------------------------
    compare_with(OLD)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    line = hud()
    # the largest changes: the new boss (+5 over the plate) and the rib (6 over it)
    assert "足された 最大 +5.00 mm" in line and "削られた 最大 −6.00 mm" in line, line
    assert legend_shown()
    legend = page.inner_text("#compare-legend")
    assert "新しい版 revision_b.step" in legend and "前の版 revision_a.step" in legend, legend
    tol = float(nav.ctl("許容").locator("input").input_value())
    assert 0.01 <= tol < 0.75, ("the tolerance starts at the meshes' coarseness, under the smallest change here", tol)
    assert nav.ctl("比べる版").locator("input").input_value() == "revision_a.step"

    # 重ねる: the new version in colour, the removed rib over it
    expect(
        {
            "raised boss": (BOSS_TOP, "added"),
            "new boss": (NEW_BOSS_TOP, "added"),
            "rib": (RIB_TOP, "removed"),
            "plate": (PLATE, "same"),
        },
        "重ねる",
    )

    # one version alone
    select("見せ方", "新しい版だけ")
    expect({"raised boss": (BOSS_TOP, "added"), "rib's foot": (RIB_FOOT, "removed"), "plate": (PLATE, "same")}, "新しい版だけ")
    select("見せ方", "前の版だけ")
    expect(
        {
            "first boss top": (OLD_BOSS_TOP, "added"),
            "under the new boss": (NEW_BOSS_FOOT, "added"),
            "rib": (RIB_TOP, "removed"),
            "plate": (PLATE, "same"),
        },
        "前の版だけ",
    )

    # the tolerance: 3 mm takes in the raised boss (2) and the rib's foot (0.75), not the new boss (5)
    select("見せ方", "新しい版だけ")
    box = nav.ctl("許容").locator("input")
    box.fill("3")
    box.press("Enter")
    nav.settle()
    expect({"raised boss": (BOSS_TOP, "same"), "rib's foot": (RIB_FOOT, "same"), "new boss": (NEW_BOSS_TOP, "added")}, "許容 3 mm")
    assert "許容 ±3 mm" in page.inner_text("#compare-legend")
    box.fill(str(tol))
    box.press("Enter")
    nav.settle()

    # the other way round: the compared file is the new one; what the open one
    # (now the previous version, 前の版だけ) has more was removed
    select("新しいのは", "比べる版")
    select("見せ方", "前の版だけ")
    assert "新しい版 revision_a.step" in page.inner_text("#compare-legend")
    expect({"new boss": (NEW_BOSS_TOP, "removed"), "raised boss": (BOSS_TOP, "removed"), "plate": (PLATE, "same")}, "新しいのは 比べる版")
    select("新しいのは", "開いている版")

    # the section cuts the comparison too: at X 30 (the middle), the +X half (the camera's side) goes
    select("見せ方", "重ねる（変わった所）")
    section = gui_common.toolbar(page, "section")
    section.click()
    nav.settle()
    assert section.get_attribute("aria-pressed") == "true"
    got = classes({"boss": BOSS_TOP, "rib": RIB_TOP})
    assert got["boss"][0] == "added" and got["rib"][0] != "removed", ("断面", got)
    # meshes made again while it is in (見せ方) are cut too
    select("見せ方", "前の版だけ")
    select("見せ方", "重ねる（変わった所）")
    got = classes({"boss": BOSS_TOP, "rib": RIB_TOP})
    assert got["boss"][0] == "added" and got["rib"][0] != "removed", ("断面, made again", got)
    # cut across the boss at Z 12 (between the first version's top, 11, and the
    # next one's, 13), from above: inside the new boss the first version's top
    # is not drawn (a surface of the old version inside the new one is not what
    # was removed), nor told under the cursor
    nav.ctl("軸").locator("select").select_option("Z")
    pos = nav.ctl("位置 (mm)").locator("input").first
    pos.fill("12")
    pos.press("Enter")
    nav.settle()
    inside = classes({"first top": OLD_BOSS_TOP})["first top"]
    assert inside[0] != "added", ("the old version's top inside the new boss", inside)
    x, y = nav.project(OLD_BOSS_TOP)
    page.mouse.move(x, y)
    page.wait_for_function("!document.querySelector('#cursor-tip').classList.contains('hidden')", timeout=5000)
    # (the new boss's own wall behind, unchanged: not its top, which the section took away)
    tip = page.inner_text("#cursor-tip")
    assert "新しい版の面" in tip and "許容" in tip, tip
    page.mouse.move(5, 5)
    nav.ctl("軸").locator("select").select_option("X")
    section.click()
    nav.settle()
    expect({"rib": (RIB_TOP, "removed")}, "断面 off")

    # the value under the cursor: as the colour says it
    select("見せ方", "新しい版だけ")
    x, y = nav.project(NEW_BOSS_TOP)
    page.mouse.move(x, y)
    page.wait_for_function("!document.querySelector('#cursor-tip').classList.contains('hidden')", timeout=5000)
    tip = page.inner_text("#cursor-tip")
    m = re.search(r"足された \+(\d+\.\d+) mm（新しい版の面）", tip)
    assert m and math.isclose(float(m.group(1)), 5, abs_tol=0.02), tip
    page.mouse.move(5, 5)
    # on the raised boss's side the change grows with the height (z - 11): the value between the finer mesh's vertices
    side = (15 + 4 * math.cos(math.radians(-45)), 20 + 4 * math.sin(math.radians(-45)), 12.2)
    x, y = nav.project(side)
    page.mouse.move(x, y)
    page.wait_for_function("document.querySelector('#cursor-tip').textContent.includes('足された')", timeout=5000)
    m = re.search(r"足された \+(\d+\.\d+) mm", page.inner_text("#cursor-tip"))
    assert m and math.isclose(float(m.group(1)), 1.2, abs_tol=0.03), page.inner_text("#cursor-tip")
    page.mouse.move(5, 5)

    # the light theme: the colours are made again, each at 3:1 against its background at least
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
            for c in page.eval_on_selector_all("#compare-legend .draft-swatch", "els => els.map(e => getComputedStyle(e).backgroundColor)")
        ]

    dark = swatches()
    nav.ctl("配色").locator("select").select_option(label="ライト")
    nav.settle()
    light = swatches()
    assert light != dark and all(contrast(c, (0xE4, 0xE8, 0xED)) >= 3 for c in light), ("ライト", light)
    nav.ctl("配色").locator("select").select_option(label="ダーク")
    nav.settle()
    assert swatches() == dark

    # a measuring mode works on the open model: the comparison ends
    nav.ctl("モード").locator("select").select_option("計測")
    nav.settle()
    assert not legend_shown()
    assert "足された" not in hud(), hud()
    assert classes({"new boss": NEW_BOSS_TOP})["new boss"][0] != "added", "the model in its own colours again"
    nav.ctl("モード").locator("select").select_option("なし")

    # a drawing cannot be compared: the line says so, nothing changes
    compare_with(DXF)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('比べられなかった')", timeout=60000)
    assert "図面（2D）とは比べられない" in hud(), hud()
    assert not legend_shown()

    # a part hidden in the tree is compared all the same: an assembly against the same
    # file under another name, its block hidden, has no change (the other file has no
    # tree to hide the block in)
    nav.load(nav.paths["step"])
    row = page.locator("#tree-panel label", has_text=re.compile("^cavity_block$")).locator("xpath=..")
    row.locator("input").click()
    nav.settle()
    compare_with(STEP_SRC)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    assert "足された 最大 ±0.00 mm、削られた 最大 ±0.00 mm" in hud(), hud()
    row.locator("input").click()
    nav.load(NEW)

    # again, then a new file: the comparison was the old model's
    compare_with(OLD)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    assert legend_shown()
    nav.load(OLD)
    assert not legend_shown()
    assert nav.ctl("比べる版").locator("input").input_value() == ""
    print("OK: 版の比較")
