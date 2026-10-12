"""E2E: 版の比較's 自動で合わせる (docs/designs/align.md, 段 2): the compared
version placed where it fits the open one best (autoalign.ts).

- revision_a.step against revision_a_moved.step (revision_a turned and moved,
  no change of shape: testdata/make_step_assembly.py MOVED_A): before, all of
  it is a change; after, nothing is, and the motion is the file's undone.
- against revision_b_moved.step (revision_b turned and moved, MOVED_B): the
  changes of the two versions in one frame (test_compare_places.py: added the
  new boss +5 and the raised boss +2, removed the rib -6). What changed does
  not pull the fit. Also from a datum's alignment: the top alone (searched
  about it too), a corner alone (searched too), and three datums (refined
  from there alone: one placement).
- tilted_block.step against itself (a block: it fits as well four ways): the
  four are told, the one that does not move it first, 次の置き方 goes round.
- two STL boxes (a mesh format: no datums), one moved along X: 基準で合わせる
  says it cannot, 自動で合わせる puts it back.
"""
import math
import os
import tempfile

from nav_common import SLOW_SCENE_TIMEOUT, TESTDATA, box_stl, nav_session

OPEN = TESTDATA / "revision_a.step"
MOVED_A = TESTDATA / "revision_a_moved.step"
MOVED_B = TESTDATA / "revision_b_moved.step"
BLOCK = TESTDATA / "tilted_block.step"


def mat(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def turn_about(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return {
        "x": [[1, 0, 0], [0, c, -s], [0, s, c]],
        "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
        "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]],
    }[axis]


# the files' motions (make_step_assembly.py): p -> move + R p
R_A, T_A = mat(turn_about("z", 45), turn_about("y", 120)), (-30, 50, 10)
R_B, T_B = mat(turn_about("x", 30), turn_about("z", 90)), (80, 20, 5)

with nav_session(timeout=SLOW_SCENE_TIMEOUT) as nav:
    page = nav.page
    tmp = tempfile.mkdtemp(prefix="cad_auto_")

    def align_state():
        return page.evaluate("window.__cadAlign()")

    def places():
        return page.evaluate("window.__cadCompare()")

    def hud():
        return page.inner_text("#hud-info")

    def compare_with(path):
        with page.expect_file_chooser() as fc:
            nav.ctl("別の版と比べる").locator("button").click()
        fc.value.set_files(str(path))
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
        nav.settle()

    def auto_align(want_from="file"):
        nav.ctl("自動で合わせる").locator("button").click()
        page.wait_for_function(
            "f => { const a = window.__cadAlign().aligned; return a && a.kind === 'auto' && a.auto.from === f"
            " && document.querySelector('#hud-info').textContent.includes('足された') }",
            arg=want_from,
            timeout=180000,
        )
        nav.settle()
        return align_state()["aligned"]

    def undoes(a, R, T, turn_tol=0.01, at=(30, 20, 3), move_tol=0.01):
        """the motion found takes the moved file back: R's undoing within turn_tol degrees, a point of the part within move_tol mm"""
        r = [a["r"][0:3], a["r"][3:6], a["r"][6:9]]
        rel = mat(r, R)  # the found turn after the file's: the identity when it undoes it
        angle = math.degrees(math.acos(max(-1, min(1, (rel[0][0] + rel[1][1] + rel[2][2] - 1) / 2))))
        assert angle < turn_tol, (angle, a["r"], a["auto"], a["shift"])
        moved = [T[i] + sum(R[i][k] * at[k] for k in range(3)) for i in range(3)]
        back = [a["t"][i] + sum(r[i][k] * moved[k] for k in range(3)) for i in range(3)]
        assert math.dist(back, at) < move_tol, (back, at)

    def no_change():
        p = places()
        assert p["added"] == [] and p["removed"] == [], p

    # ---- the same shape, only moved: nothing is a change once it is put back -----------
    nav.load(OPEN, props="live")
    compare_with(MOVED_A)
    assert max(q["peak"] for q in places()["added"]) > 10
    a = auto_align()
    undoes(a, R_A, T_A)
    assert a["auto"]["alike"] == 0 and a["auto"]["fits"][0]["within"] > 0.99, a["auto"]
    no_change()
    line = page.inner_text("#compare-legend [data-align]")
    assert line.startswith("位置合わせ（自動）: 比べる版を回転 ") and "（ファイルどうしの位置のずれ）" in line and "残りが形の変更" in line, line
    assert "通りある" not in line and not nav.ctl("次の置き方").is_visible(), line
    nav.ctl("位置合わせを外す").locator("button").click()
    page.wait_for_function("window.__cadAlign().aligned === null", timeout=120000)

    # ---- another version, moved: the changes in one frame, what changed not pulling ------
    compare_with(MOVED_B)
    nav.ctl("新しいのは").locator("select").select_option(label="比べる版")
    nav.settle()
    a = auto_align()
    undoes(a, R_B, T_B)
    within = a["auto"]["fits"][0]["within"]
    assert 0.85 < within < 0.99, within  # the new boss, the raised boss's top and band, the rib's place: apart
    p = places()
    assert [round(q["peak"], 2) for q in p["added"]] == [5.0, 2.0], p["added"]
    assert [round(q["peak"], 2) for q in p["removed"]] == [-6.0], p["removed"]

    # ---- from a datum's alignment ----------------------------------------------------
    def by_datums(points):
        """基準で合わせる by these faces (revision_b's own frame: clicked on revision_a as they
        are, on the compared file where MOVED_B puts them); fewer than 3: Enter after them.
        An entry (p, at) is a vertex at p, clicked at `at` (just inside the outline)"""
        nav.ctl("基準で合わせる").locator("button").click()
        on = lambda p, side: p if side == "open" else tuple(T_B[i] + sum(R_B[i][j] * p[j] for j in range(3)) for i in range(3))
        for side in ("open", "other"):
            for k, entry in enumerate(points):
                nav.settle()
                p, at, kind = (entry[0], entry[1], "vertex") if isinstance(entry[0], tuple) else (entry, entry, "face")
                q = on(p, side)
                x, y = nav.project(on(at, side))
                got = page.evaluate("([x, y]) => window.__cadAlignPick(x, y)", [x, y])
                assert got and got["kind"] == kind and math.dist(got["point"], q) < 0.5, (q, got)
                page.mouse.click(x, y)
                if side == "open":
                    page.wait_for_function("n => window.__cadAlign().counts.open === n || window.__cadAlign().side === 'other'", arg=k + 1, timeout=30000)
            if side == "open" and len(points) < 3:
                page.keyboard.press("Enter")
        page.wait_for_function("(() => { const a = window.__cadAlign().aligned; return a && a.kind === 'datums' })()", timeout=120000)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
        return align_state()["aligned"]

    # the top alone (a turn about it left free): searched about it too
    nav.ctl("位置合わせを外す").locator("button").click()
    page.wait_for_function("window.__cadAlign().aligned === null", timeout=120000)
    by_datums([(5, 5, 3)])
    a = auto_align("datums")
    undoes(a, R_B, T_B)
    assert a["auto"]["starts"] > 12, a["auto"]  # the turns about the top, and the search
    assert "基準の合わせから詰めた" in page.inner_text("#compare-legend [data-align]")
    # a corner alone (every turn free): the search too
    by_datums([((60, 0, 3), (59.6, 0.4, 3))])
    a = auto_align("datums")
    undoes(a, R_B, T_B)
    assert a["auto"]["starts"] > 1, a["auto"]  # the datums' alignment and the search
    # the top, the old boss's side and the front (every turn and move fixed): refined from
    # there alone, one placement (a symmetric part stays as the datums put it)
    d = by_datums([(5, 5, 3), (15, 16, 7), (30, 0, 1.5)])
    assert d["fixed"] == {"turn": 3, "move": 3}, d
    a = auto_align("datums")
    assert a["auto"]["starts"] == 1 and len(a["auto"]["fits"]) == 1, a["auto"]
    undoes(a, R_B, T_B)
    nav.ctl("比較をやめる").locator("button").click()

    # ---- a block against itself: four placements fit alike ------------------------------
    nav.load(BLOCK, props="live")
    compare_with(BLOCK)
    a = auto_align()
    assert a["auto"]["alike"] == 3 and all(f["within"] > 0.99 for f in a["auto"]["fits"][:4]), a["auto"]
    assert a["angle"] < 1e-3 and math.hypot(*a["t"]) < 1e-3, ("the one that does not move it first", a["angle"], a["t"])
    no_change()
    line = page.inner_text("#compare-legend [data-align]")
    assert "同じくらい合う置き方がほかに 3 通りある（対称な形。いまは 1/4）" in line, line
    turns = []
    for k in range(4):
        nav.ctl("次の置き方").locator("button").click()
        page.wait_for_function(
            "k => window.__cadAlign().aligned.auto.at === k && document.querySelector('#hud-info').textContent.includes('足された')",
            arg=(k + 1) % 4,
            timeout=120000,
        )
        nav.settle()
        a = align_state()["aligned"]
        turns.append(round(a["angle"]))
        no_change()
        assert f"いまは {(k + 1) % 4 + 1}/4" in page.inner_text("#compare-legend [data-align]")
    assert sorted(turns) == [0, 180, 180, 180], turns  # round to the first again
    nav.ctl("比較をやめる").locator("button").click()

    # ---- a mesh format: no datums, but 自動で合わせる ---------------------------------------
    box_a, box_b = os.path.join(tmp, "auto_a.stl"), os.path.join(tmp, "auto_b.stl")
    box_stl(box_a, (0, 0, 0), (40, 30, 10))
    box_stl(box_b, (100, 0, 0), (140, 30, 10))
    nav.load(box_a)
    compare_with(box_b)
    nav.ctl("基準で合わせる").locator("button").click()
    assert "STEP・IGES どうしだけ" in hud() and align_state()["side"] is None, hud()
    a = auto_align()
    assert a["angle"] < 1e-3 and abs(a["t"][0] + 100) < 1e-3 and abs(a["t"][1]) < 1e-3 and abs(a["t"][2]) < 1e-3, (a["angle"], a["t"])
    no_change()
    print("OK: 版の比較の自動の位置合わせ")
