"""E2E: アンダーカットの候補 in the 問題の一覧 (#59 P2: the problem places listed, gone to).

The expected places come from how the part is made (testdata/
make_step_assembly.py make_undercut_block; test_undercut.py has the shapes).
Along Z there are two: the side hole's inside (2 pi 3 x 30 = 565.5 mm²) and
the hook's (its lip's underside 6 x 10, the floor under it 6 x 10 and the
post's wall under it 7 x 10, which meet: 190 mm²). Along Y one: the pocket
(2 pi 3 x 10 + pi 3² = 216.8 mm²).

Steps: off at first; on: the rows, their areas and places, the counts and the
conditions; a row goes to its place and puts the candidates' colours on; the
direction turned: the list made again; two parts, by area over them; off again.
"""
import math

from nav_common import TESTDATA, nav_session

PART = TESTDATA / "undercut_block.step"
HOLE = 2 * math.pi * 3 * 30
HOOK = 60 + 60 + 70
POCKET = 2 * math.pi * 3 * 10 + math.pi * 9

with nav_session() as nav:
    page = nav.page
    nav.load(PART, props="live")

    def box(name):
        return nav.ctl(name).locator("input")

    def check():
        return page.evaluate("window.__cadCheck()")

    def undercut_rows():
        c = check()
        return [r for r in c["rows"] if r["kind"] == "undercut"]

    def wait_list():
        page.wait_for_function("!!window.__cadCheck() && !document.querySelector('#check-panel .check-busy')", timeout=120000)
        nav.settle()

    nav.ctl("型開き方向").locator("select").select_option(label="+Z")
    # the list with the undercuts alone (the other kinds have their own scripts)
    box("一覧を出す").check()
    for name in ("肉厚を調べる", "厚肉を調べる", "抜き勾配を調べる"):
        box(name).uncheck()
    nav.settle()
    assert not box("アンダーカットを調べる").is_checked(), "off at first (its rays take seconds)"
    assert page.locator("#check-panel").is_hidden() or not undercut_rows()

    # ---- on: two places along Z ----------------------------------------------------------
    box("アンダーカットを調べる").check()
    wait_list()
    rows = undercut_rows()
    areas = [r["area"] for r in rows]
    assert len(rows) == 2, areas
    assert abs(areas[0] - HOLE) < 0.01 * HOLE and abs(areas[1] - HOOK) < 0.02 * HOOK, areas
    # where they are: in the side hole (its axis x 10, z 10, r 3), by the hook (x 24..32, y 18..28, z 20..27)
    x, y, z = rows[0]["at"]
    assert abs(math.hypot(x - 10, z - 10) - 3) < 0.05 and 0 <= y <= 30, rows[0]["at"]
    x, y, z = rows[1]["at"]
    assert 24 <= x <= 32.01 and 18 <= y <= 28 and 20 - 1e-3 <= z <= 27 + 1e-3, rows[1]["at"]
    assert "アンダーカット 2" in page.inner_text("#check-panel .check-counts")
    assert "アンダーカット（型開き +Z へまっすぐ開く 2 枚の型）" in page.inner_text("#check-panel .check-conditions")
    first = page.locator("#check-panel li[data-kind='undercut'] .check-go").first
    assert f"{areas[0]:.1f} mm²" in first.inner_text(), first.inner_text()

    # ---- a row goes to its place, with the candidates' colours ------------------------------
    assert not box("アンダーカットの候補").is_checked()
    first.click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('mm²（型開き方向 +Z）')", timeout=60000)
    assert box("アンダーカットの候補").is_checked() and page.locator("#undercut-legend").is_visible()
    assert check()["current"]["kind"] == "undercut"

    # ---- the direction turned: the list made again ---------------------------------------
    nav.ctl("型開き方向").locator("select").select_option(label="+Y")
    page.wait_for_function(
        "(c => c && c.rows.filter(r => r.kind === 'undercut').length === 1)(window.__cadCheck())", timeout=120000
    )
    wait_list()
    (row,) = undercut_rows()
    assert abs(row["area"] - POCKET) < 0.015 * POCKET, row["area"]
    x, y, z = row["at"]
    assert math.hypot(x - 30, y - 8) <= 3.01 and 10 - 1e-3 <= z <= 20, row["at"]
    assert "アンダーカット（型開き +Y へまっすぐ開く 2 枚の型）" in page.inner_text("#check-panel .check-conditions")

    # ---- two parts: by area over the parts (undercut_pair.step: the first part's hole
    # R1, 125.7 mm²; the second's R3, 377.0 mm²) --------------------------------------
    nav.load(TESTDATA / "undercut_pair.step", props="live")
    nav.ctl("型開き方向").locator("select").select_option(label="+Z")
    box("一覧を出す").check()  # a new file turns the list off
    page.wait_for_function("(c => c && c.rows.filter(r => r.kind === 'undercut').length === 2)(window.__cadCheck())", timeout=120000)
    areas = [r["area"] for r in undercut_rows()]
    small, large = 2 * math.pi * 1 * 20, 2 * math.pi * 3 * 20
    assert abs(areas[0] - large) < 0.015 * large and abs(areas[1] - small) < 0.03 * small, areas

    # ---- a new file lets the old model's reach go (its Worker stopped: Codex on #106) -----
    assert page.evaluate("window.__cadReach()") is not None
    nav.load(nav.paths["step"])
    assert page.evaluate("window.__cadReach()") is None, page.evaluate("window.__cadReach()")
    nav.load(TESTDATA / "undercut_pair.step", props="live")
    box("一覧を出す").check()
    wait_list()

    # ---- off: no undercut rows, no condition --------------------------------------------
    box("アンダーカットを調べる").uncheck()
    nav.settle()
    assert "アンダーカット" not in page.inner_text("#check-panel")
    print("OK: 問題の一覧のアンダーカット")
