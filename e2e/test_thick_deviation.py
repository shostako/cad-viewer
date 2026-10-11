"""E2E: the 肉厚 heatmap's 一般部との比（面ごと） method (#59 P1 9, thickness transitions).

As commercial tools show thickness variation (Moldflow's Design Adviser: the
nominal wall ±20 % and ±50 %; CADEX: a wall off its median by 20 %;
docs/thickness-prior-art.md), each face is painted by its thickness (面ごと)
against its part's general wall, in five bands.

The specification, written out here (not read from the code):
- bands: more than 50 % thinner red, 20〜50 % thinner orange, within ±20 %
  green (the general wall), 20〜50 % thicker light purple, more than 50 %
  thicker purple. The bands' edges are 「ずれ 小」 and 「ずれ 大」 (shown with
  this 方式 only); the general wall each part's own, or the one given.
- the legend says the bands and the general wall; under the cursor the
  thickness and its % off the general wall.

Oracles (none from the code under test): ribbed_plate.stl's make
(testdata/make_testdata.py): the plate 2 thick (the general wall), the ribs
1.2 (40 % thinner), the bosses ⌀6 (three times). mini_mold.step's parts
(make_step_assembly.py): each part's faces its own wall. The screen's pixels
at points of known faces (window.__cadProject, checked with window.__cadPick).
"""
import io

import numpy as np
from PIL import Image

import gui_common
from nav_common import TESTDATA, nav_session

RIBBED = TESTDATA / "ribbed_plate.stl"
BOSS_TOP = (30, 18, 12)
PLATE_TOP = (12, -24.5, 2)
RIB_SIDE = (25.6, -10, 6)


def green(c):
    r, g, b = c
    return g > r + 20 and g > b + 10


def orange(c):
    r, g, b = c
    return r > g + 30 and r > b + 60 and g > b


def purple(c):
    r, g, b = c
    return r > g + 25 and b > g + 25


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

    def set_number(name, v):
        inp = ctl(name).locator("input").last
        inp.fill(str(v))
        inp.press("Enter")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        n.settle()

    def shown(name):
        return ctl(name).is_visible()

    def title():
        return page.inner_text(".thick-title")

    n.load(str(RIBBED), props="live")
    page.mouse.move(1390, 890)
    for p, axis in ((BOSS_TOP, 2), (PLATE_TOP, 2), (RIB_SIDE, 0)):
        hit = n.pick(n.project(p))
        assert hit and hit["kind"] == "face" and abs(hit["point"][axis] - p[axis]) < 0.05, (p, hit)
    gui_common.open_folder(page, "肉厚")
    assert not shown("ずれ 小 (%)") and not shown("ずれ 大 (%)"), "the bands' rows only with 一般部との比"
    ctl("方式").locator("select").select_option(label="一般部との比（面ごと）")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    assert shown("ずれ 小 (%)") and shown("ずれ 大 (%)")
    box = ctl("ヒートマップ").locator("input")
    if not box.is_checked():
        box.click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=90000)
    n.settle()
    page.wait_for_timeout(300)
    t = title()
    wall = float(t.split("一般部 ")[1].split(" mm")[0])
    assert t.startswith("肉厚（一般部との比、面ごと。一般部 ") and abs(wall - 2) <= 0.2, t
    bands = page.locator(".deviation-band").all_inner_texts()
    assert bands == ["−50 % より薄い", "−50〜−20 %", "±20 %（一般部）", "+20〜+50 %", "+50 % より厚い"], bands
    plate, rib, boss = colour_at(PLATE_TOP), colour_at(RIB_SIDE), colour_at(BOSS_TOP)
    assert green(plate), ("the plate is the general wall", plate)
    assert orange(rib), ("the ribs 40 % thinner", rib)
    assert purple(boss), ("the bosses three times", boss)
    page.mouse.move(*n.project(RIB_SIDE))
    page.wait_for_function("(document.querySelector('#cursor-tip')?.textContent || '').includes('一般部の')", timeout=10000)
    tip = page.inner_text("#cursor-tip")
    pct = int(tip.split("一般部の ")[1].split(" %")[0].replace("−", "-").replace("+", "").replace("±", ""))
    assert abs(float(tip.split()[0]) - 1.2) <= 0.2 and -50 <= pct <= -30, tip
    page.mouse.move(1390, 890)
    print("1 bands:", "plate", plate, "rib", rib, "boss", boss, tip)

    # ---- the small band 50 %: the ribs (−40 %) are the general wall's now; the large one moves past it
    set_number("ずれ 小 (%)", 50)
    assert float(ctl("ずれ 大 (%)").locator("input").last.input_value()) > 50
    page.wait_for_function("document.querySelector('.deviation-band[data-band=\"2\"]')?.textContent === '±50 %（一般部）'", timeout=30000)
    n.settle()
    assert green(colour_at(RIB_SIDE)) and purple(colour_at(BOSS_TOP))
    set_number("ずれ 小 (%)", 20)
    set_number("ずれ 大 (%)", 50)
    page.wait_for_function("document.querySelector('.deviation-band[data-band=\"2\"]')?.textContent === '±20 %（一般部）'", timeout=30000)
    print("2 the bands move")

    # ---- the general wall given 1.2 mm: the ribs are it, the plate (+67 %) purple
    set_number("一般部 (mm・0 で自動)", 1.2)
    page.wait_for_function("document.querySelector('.thick-title')?.textContent.includes('一般部 1.2 mm')", timeout=30000)
    n.settle()
    assert green(colour_at(RIB_SIDE)) and purple(colour_at(PLATE_TOP)), (colour_at(RIB_SIDE), colour_at(PLATE_TOP))
    set_number("一般部 (mm・0 で自動)", 0)
    print("3 the general wall given")

    # ---- an assembly: each part against its own wall (the plate 15, the block's walls, the pins)
    n.load(str(TESTDATA / "mini_mold.step"), props="live")
    page.mouse.move(1390, 890)
    box = ctl("ヒートマップ").locator("input")
    if not box.is_checked():
        box.click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=90000)
    n.settle()
    page.wait_for_timeout(300)
    assert "一般部 部品ごと" in title(), title()
    for p in ((50, 5, 15), (50, 30, 35)):  # the plate's top in front of the block, the block's top
        c = colour_at(p)
        assert green(c), ("a part against its own wall", p, c)
    print("4 mini_mold: each part its own wall")
    assert not n.errors, n.errors
print("THICK DEVIATION E2E OK")
