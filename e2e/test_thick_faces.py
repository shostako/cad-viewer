"""E2E: the 肉厚 heatmap's 面ごと (形の中から) method (#59 P1 2, its second view).

The specification, written out here (not read from the code):
- 方式 面ごと（形の中から）: each face takes its own thickness (from the grid
  inside the part, GET /thick.bin), on the heatmap's colours: under the
  閾値 red to orange, over it blue.
- 厚肉 (射出成形): a face whose thickness is the 厚肉 ratio x its part's general
  wall or more is purple; the legend says it. A change of the ratio or of the
  general wall paints the faces again at once. 一般 has no purple band.
- Every vertex has a value (a B-rep face's, also on a flat face whose vertices
  are only on its edges, where the rolling ball has none).

Oracles (none from the code under test): ribbed_plate.stl's make
(testdata/make_testdata.py): the plate 2 thick (the general wall), the ribs
1.2, the bosses ⌀6 (about 3 times the plate); mini_mold.step's faces all
flat or a pin's cylinder (make_step_assembly.py). The screen's pixels at
points of known faces (window.__cadProject, checked with window.__cadPick).
"""
import io

import numpy as np
from PIL import Image

import gui_common
from nav_common import TESTDATA, nav_session
from engine_net import Net

RIBBED = TESTDATA / "ribbed_plate.stl"
# points on faces seen from the view the file opens in (checked by a pick)
BOSS_TOP = (30, 18, 12)
PLATE_TOP = (12, -24.5, 2)
RIB_SIDE = (25.6, -10, 6)
# the plate's front side (2 high): its wall is the plate's 2 (a ray along the plate would say 80)
PLATE_SIDE = (12, -25, 1)


def purple(c):
    r, g, b = c
    return r > g + 25 and b > g + 25


def blue(c):
    r, g, b = c
    return b > r + 25 and b > g + 10


def warm(c):
    r, g, b = c
    return r > g + 30 and r > b + 30


with nav_session() as n:
    page = n.page
    page.set_viewport_size({"width": 1400, "height": 900})
    n.stub_sidecar()

    def ctl(name):
        return gui_common.ctl(page, name)

    def colour_at(p):
        xy = n.project(p)
        img = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB")).astype(int)
        x, y = int(round(xy[0])), int(round(xy[1]))
        return tuple(img[y - 2 : y + 3, x - 2 : x + 3].reshape(-1, 3).mean(axis=0).round())

    def check_pick(p, normal_axis, sign):
        hit = n.pick(n.project(p))
        assert hit and hit["kind"] == "face" and abs(hit["point"][normal_axis] - p[normal_axis]) < 0.05, (p, hit)

    def heat_on():
        box = ctl("ヒートマップ").locator("input")
        if not box.is_checked():
            box.click()
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=90000)
        n.settle()

    def set_number(name, v):
        inp = ctl(name).locator("input").last
        inp.fill(str(v))
        inp.press("Enter")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        n.settle()

    n.load(str(RIBBED), props="live")
    page.mouse.move(1390, 890)
    for p, axis in ((BOSS_TOP, 2), (PLATE_TOP, 2), (RIB_SIDE, 0), (PLATE_SIDE, 1)):
        check_pick(p, axis, 1)
    gui_common.open_folder(page, "肉厚")
    ctl("方式").locator("select").select_option(label="面ごと（形の中から）")
    heat_on()
    page.wait_for_timeout(300)
    n.settle()
    text = page.inner_text(".thick-title")
    assert text.startswith("肉厚（面ごと、閾値 0.64 mm 未満が赤・橙）"), text
    band = page.inner_text(".thick-band")
    assert band == "厚肉: 一般部（部品ごと）の 1.5 倍以上", band
    boss, plate, rib, side = colour_at(BOSS_TOP), colour_at(PLATE_TOP), colour_at(RIB_SIDE), colour_at(PLATE_SIDE)
    assert purple(boss), ("the boss (about 3 times the wall) is 厚肉", boss)
    assert blue(plate) and blue(rib), ("the plate and the ribs over 0.64", plate, rib)
    assert blue(side) and not purple(side), ("the plate's side: the plate's wall, not its length", side)
    print("1 面ごと:", "boss", boss, "plate", plate, "rib", rib)

    # ---- the 閾値 1.5: the ribs (1.2) are under it, the plate (2) is not
    set_number("閾値 (mm)", 1.5)
    page.wait_for_timeout(200)
    rib, plate = colour_at(RIB_SIDE), colour_at(PLATE_TOP)
    assert warm(rib) and blue(plate), ("the ribs under 1.5, the plate over", rib, plate)
    # the value under the cursor: the rib's face, about 1.2
    page.mouse.move(*n.project(RIB_SIDE))
    page.wait_for_function("/mm$/.test(document.querySelector('#cursor-tip')?.textContent || '')", timeout=10000)
    tip = page.inner_text("#cursor-tip")
    assert abs(float(tip.split()[0]) - 1.2) <= 0.2, tip
    page.mouse.move(1390, 890)
    print("2 the 閾値 1.5:", "rib", rib, tip)

    # ---- the ratio 3.5: the bosses (about 3) are not 厚肉 any more, at once
    set_number("厚肉 (一般部の倍)", 3.5)
    page.wait_for_function("document.querySelector('.thick-band')?.textContent.includes('3.5 倍以上')", timeout=30000)
    n.settle()
    boss = colour_at(BOSS_TOP)
    assert blue(boss) and not purple(boss), ("the boss under 3.5 times", boss)
    # the general wall given 1 mm, the ratio 1.5: the plate (2) is 厚肉 too
    set_number("厚肉 (一般部の倍)", 1.5)
    set_number("一般部 (mm・0 で自動)", 1)
    page.wait_for_function("document.querySelector('.thick-band')?.textContent === '厚肉: 一般部（1.0 mm）の 1.5 倍以上'", timeout=30000)
    n.settle()
    assert purple(colour_at(PLATE_TOP)) and purple(colour_at(BOSS_TOP)), "the plate and the bosses over 1.5 mm"
    set_number("一般部 (mm・0 で自動)", 0)
    print("3 the ratio and the general wall paint again")

    # ---- 一般: no 厚肉 band
    ctl("用途").locator("select").select_option(label="一般")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_function("!document.querySelector('.thick-band')", timeout=30000)
    n.settle()
    assert not purple(colour_at(BOSS_TOP)), "一般: the boss in the heatmap's own colours"
    ctl("用途").locator("select").select_option(label="射出成形")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_function("!!document.querySelector('.thick-band')", timeout=30000)
    print("4 一般: no band")

    # ---- a late answer does not paint over a newer one: a new ratio asks /thick
    # (held 3 s here), 一般 meanwhile: the band stays away when the answer comes
    import time

    def slow(route):
        time.sleep(3)
        route.continue_()

    Net.of(page).route("**/thick?*", slow)
    set_number("厚肉 (一般部の倍)", 2)
    ctl("用途").locator("select").select_option(label="一般")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(4500)
    n.settle()
    assert page.locator(".thick-band").count() == 0, "the late molding answer painted its band over 一般"
    assert not purple(colour_at(BOSS_TOP))
    Net.of(page).unroute("**/thick?*")
    ctl("用途").locator("select").select_option(label="射出成形")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_function("document.querySelector('.thick-band')?.textContent.includes('2 倍以上')", timeout=30000)
    print("4b a late answer dropped")

    # ---- a B-rep model: every vertex has a value (the faces' own), unlike the rolling ball
    n.load(str(TESTDATA / "mini_mold.step"), props="live")
    gui_common.open_folder(page, "問題の一覧")
    for name, method in (("ローリングボール法", "ball"), ("面ごと（形の中から）", "face")):
        ctl("方式").locator("select").select_option(label=name)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        box = ctl("一覧を出す").locator("input")
        if box.is_checked():
            box.uncheck()
        box.check()
        page.wait_for_function("!!window.__cadCheck()", timeout=90000)
        n.settle()
        none = [u for u in page.evaluate("window.__cadCheck().undecided") if "肉厚の値が出ない頂点" in u["why"]]
        if method == "ball":
            assert none, "the rolling ball has no value on mini_mold's flat faces' vertices"
            # where to look instead (#63): in the list's line and in the legend
            assert all("「面ごと（形の中から）」で見る" in u["why"] for u in none), none
            gui_common.open_folder(page, "肉厚")
            heat = ctl("ヒートマップ").locator("input")
            if not heat.is_checked():
                heat.check()
            page.wait_for_function("document.querySelector('#thickness-legend')?.textContent.includes('球の入らない頂点')", timeout=90000)
            assert "「面ごと（形の中から）」で見る" in page.inner_text("#thickness-legend")
            heat.uncheck()
        else:
            assert not none, ("面ごと: a value on every vertex", none)
    print("5 mini_mold: every vertex has a value 面ごと")
    assert not n.errors, n.errors
print("THICK FACES E2E OK")
