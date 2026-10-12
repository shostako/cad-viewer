"""E2E: 型開き方向 picked from a face or an edge (選んだ向き, #59 P2).

The expected values come from how the part is made (testdata/
make_step_assembly.py make_tilted_block): a block of 40 x 30 x 10 turned 30°
about X. Its top's normal is (0, -0.5, 0.866). Its -Y side's normal is
(0, -0.866, -0.5): along +Z that side leans 30° away (反対側, blue); along the
top's normal it is a wall (0°, 勾配不足, red). The shadow along the top's normal
is 40 x 30 = 12.00 cm²; along Z, 40 x 30 cos 30° + 40 x 10 sin 30° = 12.39 cm².
The colour is read off the canvas at projected points, by its dominant channel
(draft_cases.cls).

Steps: +Z; 選んだ向き chosen before a pick (asks for one; Esc keeps +Z); the top
picked (the line, the list, the legend, the colours, the shadow); turned over; the undercut candidates along it; back to +Z and to the
picked one again (no new click); Esc gives a pick up; an edge picked (its
direction); the undercut candidates along a picked face's normal; a mesh model
cannot pick; a reload keeps the six only.
"""
import math
import re

import gui_common
from draft_cases import cls
from nav_common import TESTDATA, nav_session

PART = TESTDATA / "tilted_block.step"
C, S = math.cos(math.radians(30)), math.sin(math.radians(30))
TOP = (20, 15 * C - 10 * S, 15 * S + 10 * C)  # the top's middle
SIDE = (20, -5 * S, 5 * C)  # the -Y side's middle
EDGE = (20, -10 * S, 10 * C)  # the edge between the top and the -Y side, along X

with nav_session(boxes=("tiny",)) as nav:
    page = nav.page
    nav.load(PART, props="live")
    nav.ctl("グリッド").locator("input").click()
    nav.settle()

    def hud():
        return page.inner_text("#hud-info")

    def colour(xyz):
        return cls(nav.canvas_rgb([nav.project(xyz)])[0])

    def legend():
        return page.inner_text("#draft-legend")

    def shadow():
        page.wait_for_function("!document.querySelector('#props-panel').textContent.includes('計算中')", timeout=60000)
        m = re.search(r"投影\s*([\d.]+) cm²（([^・]+)・目安）", page.inner_text("#props-panel"))
        assert m, page.inner_text("#props-panel")
        return float(m.group(1)), m.group(2)

    def dir_select():
        return nav.ctl("型開き方向").locator("select")

    def dir_text():
        return dir_select().evaluate("s => s.options[s.selectedIndex].text")

    def pick_at(xyz):
        x, y = nav.project(xyz)
        page.mouse.click(x, y)
        nav.settle()

    # ---- along +Z ---------------------------------------------------------------------
    dir_select().select_option(label="+Z")
    nav.ctl("色分け").locator("input").check()
    nav.settle()
    assert colour(SIDE) == "opposite" and colour(TOP) == "ok", (colour(SIDE), colour(TOP))
    assert shadow() == (12.39, "Z"), shadow()

    # ---- 選んだ向き chosen before any is picked: a pick is asked for; Esc keeps +Z ----------
    dir_select().select_option(label="選んだ向き")
    nav.settle()
    assert hud().startswith("型開き方向: 平らな面"), hud()
    assert dir_text() == "+Z", dir_text()
    page.mouse.move(5, 5)
    page.keyboard.press("Escape")
    nav.settle()
    assert dir_text() == "+Z" and "型開き +Z" in legend()

    # ---- the top picked ---------------------------------------------------------------
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    assert hud().startswith("型開き方向: 平らな面"), hud()
    pick_at(TOP)
    page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('型開き方向を 選んだ向き')", timeout=30000)
    label = "選んだ向き (0.000, -0.500, 0.866)"
    assert hud() == f"型開き方向を {label} にした", hud()
    assert dir_text() == "選んだ向き"
    assert f"型開き {label}" in legend(), legend()
    assert colour(SIDE) == "short" and colour(TOP) == "ok", (colour(SIDE), colour(TOP))
    assert shadow() == (12.00, "選んだ向き"), shadow()
    # the list says it in its conditions
    gui_common.open_folder(page, "問題の一覧")
    box = nav.ctl("一覧を出す").locator("input")
    box.check()
    page.wait_for_function("!!window.__cadCheck()", timeout=90000)
    nav.settle()
    assert f"型開き {label}" in page.inner_text("#check-panel .check-conditions"), page.inner_text("#check-panel .check-conditions")
    box.uncheck()

    # ---- turned over: the top faces away ------------------------------------------------
    nav.ctl("向きを反転").locator("button").click()
    nav.settle()
    assert "型開き 選んだ向き (0.000, 0.500, -0.866)" in legend(), legend()
    assert colour(TOP) == "opposite" and colour(SIDE) == "short", (colour(TOP), colour(SIDE))
    assert shadow() == (12.00, "選んだ向き")
    nav.ctl("向きを反転").locator("button").click()
    nav.settle()

    # ---- the undercut candidates along it (a block: none) ---------------------------------
    nav.ctl("アンダーカットの候補").locator("input").check()
    page.wait_for_function(
        f"document.querySelector('#hud-info').textContent.includes('なし（型開き方向 {label}）')", timeout=120000
    )
    assert f"型開き方向 {label}" in page.inner_text("#undercut-legend")
    nav.ctl("アンダーカットの候補").locator("input").uncheck()
    nav.ctl("色分け").locator("input").check()
    nav.settle()

    # ---- back to +Z, and to the picked one again: no new click ------------------------------
    dir_select().select_option(label="+Z")
    nav.settle()
    assert colour(SIDE) == "opposite" and "型開き +Z" in legend()
    dir_select().select_option(label="選んだ向き")
    nav.settle()
    assert colour(SIDE) == "short" and f"型開き {label}" in legend()
    assert not hud().startswith("型開き方向: 平らな面"), "no new pick asked for"

    # ---- Esc gives a pick up: the direction stays -------------------------------------------
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    assert hud().startswith("型開き方向: 平らな面")
    page.mouse.move(5, 5)
    page.keyboard.press("Escape")
    nav.settle()
    assert not hud().startswith("型開き方向:"), hud()
    pick_at(SIDE)  # a click now picks nothing
    assert f"型開き {label}" in legend()

    # ---- a pick under way, then one of the six chosen: the pick is given up (the next
    # click on the model does not change the direction: Codex on #105)
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    dir_select().select_option(label="+Z")
    nav.settle()
    assert not hud().startswith("型開き方向: 平らな面"), hud()
    pick_at(TOP)
    assert dir_text() == "+Z" and "型開き +Z" in legend(), (dir_text(), legend())
    # and the same with 向きを反転
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    nav.ctl("向きを反転").locator("button").click()
    nav.settle()
    pick_at(TOP)
    assert dir_text() == "−Z", dir_text()
    nav.ctl("向きを反転").locator("button").click()
    dir_select().select_option(label="選んだ向き")
    nav.settle()

    # ---- an edge: its direction (X, either way) -------------------------------------------
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    pick_at(EDGE)
    page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('型開き方向を 選んだ向き')", timeout=30000)
    assert re.fullmatch(r"型開き方向を 選んだ向き \(-?1\.000, 0\.000, 0\.000\) にした", hud()), hud()
    # along X the top and the side are walls
    assert colour(TOP) == "short" and colour(SIDE) == "short", (colour(TOP), colour(SIDE))

    # ---- the undercut candidates along a picked direction: the block with a side hole,
    # a pocket and a hook (test_undercut.py), its front (-Y) picked: only the pocket is
    # one, 2 pi 3 x 10 + pi 3² = 216.8 mm² (along +Z they are 755.5)
    nav.ctl("色分け").locator("input").uncheck()
    nav.load(TESTDATA / "undercut_block.step")
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    pick_at((20, 0, 15))
    page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('型開き方向を 選んだ向き')", timeout=30000)
    assert hud() == "型開き方向を 選んだ向き (0.000, -1.000, 0.000) にした", hud()
    nav.ctl("アンダーカットの候補").locator("input").check()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('mm²（型開き方向 選んだ向き')", timeout=120000)
    m = re.search(r"アンダーカットの候補: (\d+\.\d) mm²", hud())
    assert m and abs(float(m.group(1)) - 216.8) < 0.015 * 216.8, hud()
    nav.ctl("アンダーカットの候補").locator("input").uncheck()

    # ---- a mesh model has no faces to pick ------------------------------------------------
    nav.load(nav.paths["tiny"])
    nav.ctl("面・稜線から選ぶ").locator("button").click()
    assert "STEP・IGES のモデルだけ" in hud(), hud()

    # ---- a reload keeps the six only: the last of them chosen ---------------------------
    nav.load(PART)
    dir_select().select_option(label="−Y")
    dir_select().select_option(label="選んだ向き")
    nav.settle()
    assert dir_text() == "選んだ向き"
    page.reload()
    page.wait_for_load_state("networkidle")
    nav.load(PART)
    assert dir_text() == "−Y", dir_text()
    print("OK: 選んだ向き")
