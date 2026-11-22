"""E2E: the moulding's checks are frozen and hidden without ?molding (2026-11-22).

Opened as a user opens it (no ?molding), the model is looked at as 一般 even
when 射出成形 was kept from before: no 用途 row, no 抜き勾配 or 問題の一覧
folder, no 型内圧 or clamping force. 肉厚, 断面 and 体積・重量 stay, and the
projected area stays with its own direction (投影の向き: one of the six, or a
face or an edge picked). The material card hides the moulding's columns
(勾配, 厚肉). With ?molding the 用途 row comes back, and 射出成形 brings the
folders and the clamping force back. In a window too short for both rows
射出成形 folds the area's row (the force's keeps it); 一般, with no force's
row, keeps the area's row at that height.

The expected areas come from how the part is made (testdata/
make_step_assembly.py make_tilted_block): a block of 40 x 30 x 10 turned 30°
about X, its top's normal (0, -0.5, 0.866). Its shadow along Z is
40 x 30 cos 30° + 40 x 10 sin 30° = 12.39 cm²; along X it is the 30 x 10
section = 3.00 cm²; along the top's normal 40 x 30 = 12.00 cm².
"""
import json
import math
import re

import gui_common
from nav_common import APP_URL, TESTDATA, nav_session

PART = TESTDATA / "tilted_block.step"
C, S = math.cos(math.radians(30)), math.sin(math.radians(30))
TOP = (20, 15 * C - 10 * S, 15 * S + 10 * C)  # the top's middle

with nav_session(molding=False) as nav:
    page = nav.page
    # 射出成形 kept from before (PC, with a gravity typed for it): 射出成形 must not come
    # back without ?molding, and the gravity goes with PC (一般's material is SS400)
    saved = {"use": "molding", "chosen": {"molding": "PC", "general": "SS400"}, "density": 1.5}
    page.evaluate("(s) => localStorage.setItem('cad-viewer:materials', s)", json.dumps(saved))
    page.reload()
    page.wait_for_load_state("networkidle")
    nav.load(PART, props="live")
    nav.ctl("グリッド").locator("input").click()
    nav.settle()

    def hud():
        return page.inner_text("#hud-info")

    def folder_shown(name):
        return gui_common.folder_title(page, name).is_visible()

    def row_shown(name):
        label = page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
        rows = page.locator(".lil-gui .lil-controller").filter(has=label)
        return any(rows.nth(i).is_visible() for i in range(rows.count()))

    def shadow():
        page.wait_for_function("!document.querySelector('#props-panel').textContent.includes('計算中')", timeout=60000)
        m = re.search(r"投影\s*([\d.]+) cm²（([^・]+)・目安）", page.inner_text("#props-panel"))
        assert m, page.inner_text("#props-panel")
        return float(m.group(1)), m.group(2)

    def no_clamp():
        assert not page.locator("#props-clamp-label").is_visible(), "no clamping force in 一般"
        assert not page.locator("#props-total-clamp").is_visible()
        assert not row_shown("型内圧")

    # ---- what is hidden, what stays -------------------------------------------------------
    for name in ("抜き勾配", "問題の一覧"):
        assert not folder_shown(name), name
    for name in ("肉厚", "断面", "体積・重量"):
        assert folder_shown(name), name
    assert not row_shown("用途"), "the 用途 row is hidden"
    assert row_shown("材料")
    assert page.inner_text("#props-density") == "SS400 7.85 g/cm³", page.inner_text("#props-density")

    # ---- the projected area along 投影の向き (the six; the sign does not matter) ------------
    direction = nav.ctl("向き（投影面積）").locator("select")
    assert direction.evaluate("s => s.options[s.selectedIndex].text") == "+Z"
    assert shadow() == (12.39, "Z"), shadow()
    no_clamp()
    title = page.locator("#props-total-proj").get_attribute("title")
    assert title.startswith("投影面積: 投影の向き（Z）へ投影した") and "ランナー" not in title, title
    assert "ランナー" not in page.locator("#props-total-mass").get_attribute("title")
    direction.select_option(label="−X")
    assert shadow() == (3.00, "X"), shadow()
    no_clamp()

    # ---- a face picked: the top's normal ----------------------------------------------------
    nav.ctl("向きを面・稜線から選ぶ").locator("button").click()
    assert hud().startswith("投影の向き: 平らな面"), hud()
    x, y = nav.project(TOP)
    page.mouse.click(x, y)
    page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('投影の向きを 選んだ向き')", timeout=30000)
    assert hud() == "投影の向きを 選んだ向き (0.000, -0.500, 0.866) にした", hud()
    assert shadow() == (12.00, "選んだ向き"), shadow()
    no_clamp()


    # ---- the material card without the moulding's columns -----------------------------------
    nav.ctl("材料").locator(".cv-material-edit").click()
    page.wait_for_selector("#basis-pop:not(.hidden)")
    heads = page.locator("#basis-pop thead th")
    shown_heads = [heads.nth(i).inner_text() for i in range(heads.count()) if heads.nth(i).is_visible()]
    assert shown_heads[:3] == ["材料", "比重", "肉厚 mm"] and "勾配 °" not in shown_heads and "厚肉 倍" not in shown_heads, shown_heads
    resin = page.locator("#basis-pop tbody tr", has=page.locator(".basis-draft")).first
    assert resin.count() == 1, "the resins are listed in 一般 too"
    assert not resin.locator(".basis-draft").is_visible() and not resin.locator(".basis-thick").is_visible()
    assert resin.locator(".basis-density").is_visible() and resin.locator(".basis-thin").is_visible()
    page.keyboard.press("Escape")

    # ---- ?molding: the 用途 row back; 射出成形 brings the folders and the force back --------
    page.goto(APP_URL)
    page.wait_for_load_state("networkidle")
    nav.load(PART, props="live")
    assert row_shown("用途"), "?molding shows the 用途 row"
    use = nav.ctl("用途").locator("select")
    use.select_option(label="射出成形")
    nav.settle()
    for name in ("抜き勾配", "問題の一覧"):
        assert folder_shown(name), name
    assert not row_shown("向き（投影面積）"), "射出成形 takes the direction from 抜き勾配"
    assert row_shown("型内圧")
    page.wait_for_function("document.querySelector('#props-total-clamp')?.offsetParent !== null", timeout=60000)
    assert page.inner_text("#props-clamp-label") == "型締力"

    # ---- a short window: 射出成形 folds the area's row (the force's keeps it on its tooltip);
    # at the same height 一般, with no force's row, keeps the area's row
    def frames():
        page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def area_row():
        return page.locator("#props-total-proj").is_visible()

    folded_at = None
    for height in range(560, 299, -20):
        page.set_viewport_size({"width": 1280, "height": height})
        frames()
        if not area_row():
            folded_at = height
            break
    assert folded_at, "射出成形 folds the area's row in some short window (the control)"
    use.select_option(label="一般")
    nav.settle()
    frames()
    assert area_row(), ("一般 keeps the area's row", folded_at)
    # lower still (一般's panel is a row shorter and folds later): never folded while the panel shows
    for height in range(folded_at - 20, 199, -20):
        page.set_viewport_size({"width": 1280, "height": height})
        frames()
        if page.locator("#props-total").is_visible():
            assert area_row(), ("一般 keeps the area's row", height)
    page.set_viewport_size({"width": 1280, "height": folded_at})
    frames()
    # a reload keeps the six only: the −X chosen before the pick
    assert shadow() == (3.00, "X"), shadow()
    no_clamp()

print("OK: the moulding's checks are hidden without ?molding; the projected area keeps its own direction")
