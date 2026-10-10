"""E2E: 選択, what a click may take in 計測 / 注記 (issue #59 P1 8).

- The operation panel's 選択 (すべて / 面 / 稜線 / 頂点 / 部品) shows in 計測
  and 注記 on a 3D model, not in なし. The status line's hint names it
  (「稜線だけ」).
- Near the plate's top front edge (4 px off it, on screen): すべて takes the
  edge, 面 the face. 15 px off: すべて the face, 稜線 the edge; 40 px off,
  稜線 nothing. 18 px from the plate's corner: すべて no vertex, 頂点 the
  corner.
- 部品: the pin under the cursor is taken whole: the highlight and its name
  (「core_pin · 全体」) before the click, the status line after it; the second
  pin and the cavity block are 1 apart (a clearance between parts).

Oracles (none from the code under test): mini_mold.step's make
(testdata/make_step_assembly.py): the plate 0..100 x 0..60 x 0..15, core pins
of radius 4 at (25, 30) and (75, 30) z 15..40, the cavity block
30..70 x 15..45 x 15..35. Distances on screen from __cadProject; what a click
takes from __cadPick (the same pick as the click and the hover).
"""
import math
import tempfile
from pathlib import Path

import gui_common
from nav_common import TESTDATA, empty_sidecar, nav_session

tmp = tempfile.mkdtemp(prefix="cad_filter_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 63)

with nav_session() as n:
    page = n.page
    empty_sidecar(page, mold)

    def hud():
        return page.inner_text("#hud-info")

    def filter_ctl():
        return gui_common.ctl(page, "選択")

    def set_filter(label):
        filter_ctl().locator("select").select_option(label=label)
        n.settle()

    def toward(a, b, px):
        """the screen point px from a's projection toward b's"""
        pa, pb = n.project(a), n.project(b)
        d = math.dist(pa, pb)
        return [pa[0] + (pb[0] - pa[0]) * px / d, pa[1] + (pb[1] - pa[1]) * px / d]

    def pick(xy):
        return n.pick(xy)

    n.load(str(mold))
    assert not filter_ctl().is_visible(), "選択 only in 計測 / 注記"
    gui_common.set_mode(page, "注記")
    assert filter_ctl().is_visible()
    gui_common.set_mode(page, "計測")
    assert filter_ctl().is_visible()
    assert filter_ctl().locator("select").evaluate("s => s.options[s.selectedIndex].text") == "すべて"

    # ---- near an edge: すべて snaps, 面 does not; farther, 稜線 still takes it, then nothing
    edge, inside = (15, 0, 15), (15, 10, 15)  # the plate's top front edge, its top behind it (clear of the pins)
    p4, p15, p40 = toward(edge, inside, 4), toward(edge, inside, 15), toward(edge, inside, 40)
    assert pick(p4)["kind"] == "edge" and pick(p15)["kind"] == "face", (pick(p4), pick(p15))
    set_filter("面")
    assert pick(p4)["kind"] == "face", pick(p4)
    set_filter("稜線")
    e15 = pick(p15)
    assert e15 and e15["kind"] == "edge" and abs(e15["point"][1]) < 1e-3 and abs(e15["point"][2] - 15) < 1e-3, e15
    assert pick(p40) is None, pick(p40)
    wait = "document.querySelector('#hud-info').textContent.includes('稜線だけ')"
    page.wait_for_function(wait, timeout=5000)
    assert hud() == "計測: クリックで 1 点目（稜線だけ・Esc でやめる）", hud()
    print("1 edges", e15)

    # the hover shows what the click takes
    page.mouse.move(*p15)
    n.settle()
    page.wait_for_timeout(200)
    tip = page.inner_text("#cursor-tip")
    page.mouse.click(*p15)
    n.settle()
    assert hud().startswith(tip.split(" ⌀")[0].replace(" · ", " ") + " を選択"), (tip, hud())
    page.keyboard.press("Escape")
    n.settle()

    # ---- near a corner: 頂点 takes it from farther
    corner = (0, 0, 15)
    p18 = toward(corner, (10, 10, 15), 18)
    set_filter("すべて")
    assert pick(p18)["kind"] != "vertex", pick(p18)
    set_filter("頂点")
    v = pick(p18)
    assert v and v["kind"] == "vertex" and math.dist(v["point"], corner) < 1e-3, v
    print("2 vertex", v)

    # ---- 部品: a whole part, and the clearance between two
    set_filter("部品")
    pin2_front = (75, 26, 30)  # the second pin, toward the viewer
    xy = n.project(pin2_front)
    p = pick(xy)
    assert p and p["kind"] == "part", p
    page.mouse.move(*xy)
    n.settle()
    page.wait_for_timeout(200)
    assert page.inner_text("#cursor-tip") == "core_pin · 全体", page.inner_text("#cursor-tip")
    page.mouse.click(*xy)
    n.settle()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('core_pin 全体 を選択')", timeout=5000)
    block_top = n.project((50, 30, 35))
    assert pick(block_top)["kind"] == "part"
    page.mouse.move(*block_top)
    page.mouse.click(*block_top)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離 1.000')", timeout=10000)
    row = page.evaluate("[...document.querySelectorAll('#measure-list li')].map(li => li.querySelector('.m-what')?.textContent).pop()")
    assert row == "core_pin 全体 ↔ cavity_block 全体", row
    print("3 parts:", hud(), row)
print("PICK FILTER E2E OK")
