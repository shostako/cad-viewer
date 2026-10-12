"""E2E: 版の比較's 位置合わせ (docs/designs/align.md): the compared version moved
onto the open one by datums clicked on both.

The open version is revision_a.step; the compared one revision_b_moved.step,
revision_b turned 90° about Z, then 30° about X, then moved by (80, 20, 5)
(testdata/make_step_assembly.py MOVED_B). In the files' own places the two do
not meet: everything is a change. Aligned by the plate's top, the old boss's
axis and the plate's front (A|B|C: the top sets the tilt and the height, the
boss's axis the place across, the front the turn about the axis), the motion
must be the file's motion undone, and the changes those of the two versions in
one frame (test_compare_places.py: added the new boss +5 and the raised boss
+2, removed the rib -6).

Steps: the files as they are; the datums on the open version (Backspace takes
one back); on the compared one (a datum of another kind is refused); the
motion and the places; the legend and the 記録; again by the top, the boss's
foot (a circle) and a corner (a point); one plane alone (Enter): what it leaves
free; 位置合わせを外す; Esc gives a choice up; so does opening the 記録.
"""
import csv
import io
import math
from pathlib import Path

import gui_common
from nav_common import TESTDATA, nav_session

OPEN = TESTDATA / "revision_a.step"
OTHER = TESTDATA / "revision_b_moved.step"
NEW_BOSS = math.pi * 9 + 2 * math.pi * 3 * 5
RAISED = math.pi * 16 + 2 * math.pi * 4 * 2
RIB = 36 + 288 + 18


def mat(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def turn_about(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == "x":
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


# the file's motion (make_step_assembly.py MOVED_B): p -> MOVE + R p
R = mat(turn_about("x", 30), turn_about("z", 90))
MOVE = (80, 20, 5)


def moved(p):
    return tuple(MOVE[i] + sum(R[i][k] * p[k] for k in range(3)) for i in range(3))


# the datums, in revision_a's (and revision_b's own) frame: the plate's top, the
# old boss's side (its axis; the boss is at (15, 20), R4), the plate's front;
# the boss's foot (a circle's edge, the same in both: the boss grew upward) and
# a corner of the plate (a vertex)
TOP, BOSS, FRONT = (5, 5, 3), (15, 16, 7), (30, 0, 1.5)
FOOT, CORNER, NEAR_CORNER = (15, 16, 3), (60, 0, 3), (59.6, 0.4, 3)

with nav_session() as nav:
    page = nav.page
    nav.load(OPEN, props="live")

    def align_state():
        return page.evaluate("window.__cadAlign()")

    def places():
        return page.evaluate("window.__cadCompare()")

    def hud():
        return page.inner_text("#hud-info")

    def click_datum(p, kind="face", at=None):
        """click the model point p, or `at` near it (a corner on the outline: just inside it), as
        the side shown has it: what the click takes is checked first (p, or on p's edge)"""
        nav.settle()
        x, y = nav.project(at or p)
        got = page.evaluate("([x, y]) => window.__cadAlignPick(x, y)", [x, y])
        assert got and got["kind"] == kind and math.dist(got["point"], p) < 0.5, (p, got)
        before = align_state()["counts"]
        page.mouse.click(x, y)
        page.wait_for_function(
            "([o, b]) => { const s = window.__cadAlign(); return s.side === null || s.counts.open !== o || s.counts.other !== b"
            " || document.querySelector('#hud-info').textContent.includes('だった') }",
            arg=[before["open"], before["other"]],
            timeout=30000,
        )

    with page.expect_file_chooser() as fc:
        nav.ctl("別の版と比べる").locator("button").click()
    fc.value.set_files(str(OTHER))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    nav.ctl("新しいのは").locator("select").select_option(label="比べる版")
    nav.settle()

    # ---- the files as they are: nothing meets ----------------------------------------
    p = places()
    assert max(q["peak"] for q in p["added"]) > 10 and min(q["peak"] for q in p["removed"]) < -10, p
    assert align_state()["aligned"] is None
    assert not nav.ctl("位置合わせを外す").is_visible()

    # ---- the datums on the open version ---------------------------------------------
    nav.ctl("基準で合わせる").locator("button").click()
    assert align_state()["side"] == "open"
    assert "開いている版の基準の 1 つ目" in hud(), hud()
    assert page.locator("#compare-legend").is_hidden(), "the comparison's colours are not shown"
    click_datum(TOP)
    click_datum(FRONT)
    assert align_state()["counts"]["open"] == 2
    assert page.locator(".align-label").all_inner_texts() == ["1 平面", "2 平面"], page.locator(".align-label").all_inner_texts()
    page.keyboard.press("Backspace")  # the front taken back: the boss's axis second
    assert align_state()["counts"]["open"] == 1 and page.locator(".align-label").count() == 1
    click_datum(BOSS)
    click_datum(FRONT)  # the third: on to the compared version
    s = align_state()
    assert s["side"] == "other" and s["counts"] == {"open": 3, "other": 0}, s
    assert "1 つ目の基準（平面）" in hud(), hud()

    # ---- on the compared version, in its file's place: the same, in the same order ------
    click_datum(moved(BOSS))  # an axis where a plane comes first: refused
    assert "平面を選ぶ（軸だった）" in hud() and align_state()["counts"]["other"] == 0, hud()
    click_datum(moved(TOP))
    click_datum(moved(BOSS))
    assert page.locator(".align-label").all_inner_texts() == ["1 平面", "2 軸"]
    click_datum(moved(FRONT))
    page.wait_for_function("window.__cadAlign().aligned !== null && document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    nav.settle()

    # ---- the motion: the file's undone, every datum on its partner -----------------------
    a = align_state()["aligned"]
    assert a["kinds"] == ["plane", "axis", "plane"] and a["fixed"] == {"turn": 3, "move": 3}, a
    want_r = [R[j][i] for i in range(3) for j in range(3)]  # R's transpose, row-major
    assert all(abs(x - y) < 1e-9 for x, y in zip(a["r"], want_r)), (a["r"], want_r)
    want_t = [-sum(want_r[3 * i + k] * MOVE[k] for k in range(3)) for i in range(3)]
    assert all(abs(x - y) < 1e-6 for x, y in zip(a["t"], want_t)), (a["t"], want_t)
    assert all(f["distance"] < 1e-6 and f["angle"] < 1e-6 for f in a["misfit"]), a["misfit"]
    # the angle of R: 90° about Z then 30° about X is one turn of acos((tr R - 1) / 2)
    tr = R[0][0] + R[1][1] + R[2][2]
    assert abs(a["angle"] - math.degrees(math.acos((tr - 1) / 2))) < 1e-6, a["angle"]
    assert page.locator(".align-label").count() == 0, "the markers go"

    # ---- the places: those of the two versions in one frame ---------------------------
    def near(x, y, rel):
        return abs(x - y) <= rel * y

    def check_places():
        p = places()
        added, removed = p["added"], p["removed"]
        assert [round(q["peak"], 2) for q in added] == [5.0, 2.0], added
        assert [round(q["peak"], 2) for q in removed] == [-6.0], removed
        assert near(added[0]["area"], NEW_BOSS, 0.12) and near(added[1]["area"], RAISED, 0.12), [q["area"] for q in added]
        assert near(removed[0]["area"], RIB, 0.06), removed[0]["area"]
        # in the open version's frame: the new boss at (30, 30), the raised one at (15, 20), the rib's top at z 9
        (x, y, _), (x2, y2, _) = added[0]["at"], added[1]["at"]
        assert math.hypot(x - 30, y - 30) <= 3.01 and math.hypot(x2 - 15, y2 - 20) <= 4.01, (added[0]["at"], added[1]["at"])
        assert 44.24 <= removed[0]["at"][0] <= 45.76 and abs(removed[0]["at"][2] - 9) < 1e-3, removed[0]["at"]

    def check_motion(a):
        assert a["fixed"] == {"turn": 3, "move": 3}, a
        assert all(abs(x - y) < 1e-9 for x, y in zip(a["r"], want_r)), (a["r"], want_r)
        assert all(abs(x - y) < 1e-6 for x, y in zip(a["t"], want_t)), (a["t"], want_t)
        assert all(f["distance"] < 1e-6 and f["angle"] < 1e-6 for f in a["misfit"]), a["misfit"]

    check_places()

    # ---- the legend and the 記録 --------------------------------------------------------
    line = page.inner_text("#compare-legend [data-align]")
    assert line.startswith("位置合わせ: 基準 平面・軸・平面。比べる版を回転 ") and "基準のずれ 最大 0.000 mm・0.00°" in line, line
    assert "決まらない" not in line, line
    assert nav.ctl("位置合わせを外す").is_visible()
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    page.wait_for_selector("#report-pop:not(.hidden)")
    with page.expect_download() as d:
        page.click("#report-csv")
    rows = list(csv.reader(io.StringIO(Path(d.value.path()).read_bytes().decode("utf-8-sig"), newline="")))
    i = next(k for k, r in enumerate(rows) if r and r[0].startswith("版の比較"))
    assert rows[i][0] == "版の比較（3 所）", rows[i]
    assert any("位置合わせ: 基準 平面・軸・平面" in c for r in rows[i : i + 3] for c in r), rows[i : i + 3]
    page.keyboard.press("Escape")
    page.wait_for_selector("#report-pop", state="hidden")

    # ---- again by the top, the boss's foot (a circle's edge) and a corner (a vertex) ------
    nav.ctl("基準で合わせる").locator("button").click()
    click_datum(TOP)
    click_datum(FOOT, kind="edge")
    click_datum(CORNER, kind="vertex", at=NEAR_CORNER)
    assert page.locator(".align-label").count() == 0 and align_state()["side"] == "other"
    click_datum(moved(TOP))
    click_datum(moved(FOOT), kind="edge")
    click_datum(moved(CORNER), kind="vertex", at=moved(NEAR_CORNER))
    page.wait_for_function("(() => { const a = window.__cadAlign().aligned; return a && a.kinds[1] === 'circle' })()", timeout=120000)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    a = align_state()["aligned"]
    assert a["kinds"] == ["plane", "circle", "point"], a
    check_motion(a)
    check_places()

    # ---- one plane alone (Enter): it fixes the tilt and the height, the rest stays --------
    nav.ctl("基準で合わせる").locator("button").click()
    click_datum(TOP)
    page.keyboard.press("Enter")
    assert align_state()["side"] == "other"
    click_datum(moved(TOP))
    page.wait_for_function("(() => { const a = window.__cadAlign().aligned; return a && a.kinds.length === 1 })()", timeout=120000)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    a = align_state()["aligned"]
    assert a["fixed"] == {"turn": 2, "move": 1}, a
    # the compared version's centre moved along the open top's normal only (Z)
    assert abs(a["shift"][0]) < 1e-6 and abs(a["shift"][1]) < 1e-6, a["shift"]
    line = page.inner_text("#compare-legend [data-align]")
    assert "基準で決まらない動き（回転 1・移動 2）" in line, line

    # ---- 位置合わせを外す: the files' own places again ------------------------------------------
    nav.ctl("位置合わせを外す").locator("button").click()
    page.wait_for_function("window.__cadAlign().aligned === null", timeout=120000)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    p = places()
    assert max(q["peak"] for q in p["added"]) > 10, p
    assert page.locator("#compare-legend [data-align]").count() == 0
    assert not nav.ctl("位置合わせを外す").is_visible()

    # ---- Esc gives a choice up: the comparison as it was --------------------------------
    nav.ctl("基準で合わせる").locator("button").click()
    click_datum(TOP)
    page.keyboard.press("Escape")
    s = align_state()
    assert s["side"] is None and s["aligned"] is None, s
    assert page.locator("#compare-legend").is_visible() and page.locator(".align-label").count() == 0

    # ---- the 記録 opened while datums are clicked: the choice ends, the comparison is back
    # (the 記録 is of the comparison on screen, Codex on #108) ---------------------------
    nav.ctl("基準で合わせる").locator("button").click()
    click_datum(TOP)
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    page.wait_for_selector("#report-pop:not(.hidden)")
    s = align_state()
    assert s["side"] is None and s["aligned"] is None, s
    assert page.locator("#compare-legend").is_visible() and page.locator(".align-label").count() == 0
    page.keyboard.press("Escape")
    print("OK: 版の比較の位置合わせ")
