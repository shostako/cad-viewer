"""E2E: 版の比較's changed places (変わった所へ) and the 記録's table of them.

The places come from how the versions are made (testdata/make_step_assembly.py
make_revisions; test_compare.py says them). Added, on the new version where it
is outside the old one: the new boss (R3, to 5 over the plate: its top and its
side, 28.3 + 94.2 mm²) and the raised boss's 2 mm more (its top and the band of
its side, 50.3 + 50.3 mm²). Removed, on the old version where it is outside
the new one: the rib (1.5 x 24 x 6: its top, sides and ends, 36 + 288 + 18 mm²).
A band at each foot is not counted (the tolerance, 0.15 mm, and half a finer
triangle): the areas are some percent under these.

Steps: the buttons; added, the largest change first, round again; removed; the
places made again for another tolerance; the 新しいのは turned: the kinds
swap; the 記録's CSV has them.
"""
import csv
import io
import math
from pathlib import Path

import gui_common
from nav_common import SLOW_SCENE_TIMEOUT, TESTDATA, nav_session

NEW = TESTDATA / "revision_b.step"
OLD = TESTDATA / "revision_a.step"
NEW_BOSS = math.pi * 9 + 2 * math.pi * 3 * 5
RAISED = math.pi * 16 + 2 * math.pi * 4 * 2
RIB = 36 + 288 + 18

with nav_session(timeout=SLOW_SCENE_TIMEOUT) as nav:
    page = nav.page
    nav.load(NEW, props="live")

    def places():
        return page.evaluate("window.__cadCompare()")

    def state(kind):
        return page.inner_text(f"#compare-legend .go-state[data-go='compare-{kind}']")

    def press(kind):
        page.locator(f"#compare-legend .go-btn[data-go='compare-{kind}']").click()
        nav.settle()

    def near(a, b, rel):
        return abs(a - b) <= rel * b

    with page.expect_file_chooser() as fc:
        nav.ctl("別の版と比べる").locator("button").click()
    fc.value.set_files(str(OLD))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)

    # ---- the places, as made ----------------------------------------------------------
    p = places()
    added, removed = p["added"], p["removed"]
    assert [round(q["peak"], 2) for q in added] == [5.0, 2.0], added
    assert [round(q["peak"], 2) for q in removed] == [-6.0], removed
    # (under by the band at the foot: the tolerance and half a finer triangle across, a
    # triangle there counted by its share of corners in the place; ~0.4 mm x the perimeter)
    assert near(added[0]["area"], NEW_BOSS, 0.12) and near(added[1]["area"], RAISED, 0.12), [q["area"] for q in added]
    assert near(removed[0]["area"], RIB, 0.06), removed[0]["area"]
    assert all(q["area"] < a for q, a in zip(added + removed, (NEW_BOSS, RAISED, RIB))), "never over"
    # where: the new boss at (30, 30), the raised one at (15, 20), the rib x 44.25..45.75
    (x, y, _), (x2, y2, _) = added[0]["at"], added[1]["at"]
    assert math.hypot(x - 30, y - 30) <= 3.01 and math.hypot(x2 - 15, y2 - 20) <= 4.01, (added[0]["at"], added[1]["at"])
    assert 44.24 <= removed[0]["at"][0] <= 45.76 and abs(removed[0]["at"][2] - 9) < 1e-3, removed[0]["at"]

    # ---- 変わった所へ: the largest first, round again -------------------------------------
    assert state("added") == "" and state("removed") == ""
    press("added")
    assert state("added") == "1/2 ・ +5.00 mm", state("added")
    press("added")
    assert state("added") == "2/2 ・ +2.00 mm", state("added")
    press("added")
    assert state("added") == "1/2 ・ +5.00 mm"
    # the view frames the place: its marker in the canvas's middle part
    cx, cy = nav.project(added[0]["at"])
    l, t, w, h = nav.canvas_rect()
    assert l + 0.15 * w < cx < l + 0.85 * w and t + 0.15 * h < cy < t + 0.85 * h, (cx, cy, nav.canvas_rect())
    press("removed")
    assert state("removed") == "1/1 ・ −6.00 mm" and state("added") == "", (state("removed"), state("added"))

    # ---- another tolerance: the places made again (3 takes in the raised boss's 2) --------
    box = nav.ctl("許容").locator("input")
    box.fill("3")
    box.press("Enter")
    nav.settle()
    assert state("removed") == "" and [round(q["peak"], 2) for q in places()["added"]] == [5.0], places()
    box.fill("0.15")
    box.press("Enter")
    nav.settle()

    # ---- the other way round: the kinds swap ------------------------------------------
    nav.ctl("新しいのは").locator("select").select_option(label="比べる版")
    nav.settle()
    p = places()
    assert [round(q["peak"], 2) for q in p["added"]] == [6.0] and [round(q["peak"], 2) for q in p["removed"]] == [-5.0, -2.0], p
    nav.ctl("新しいのは").locator("select").select_option(label="開いている版")
    nav.settle()

    # ---- the 記録's CSV: the places, the largest first --------------------------------------
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    page.wait_for_selector("#report-pop:not(.hidden)")
    with page.expect_download() as d:
        page.click("#report-csv")
    text = Path(d.value.path()).read_bytes().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    i = next(k for k, r in enumerate(rows) if r and r[0].startswith("版の比較"))
    assert rows[i][0] == "版の比較（3 所）", rows[i]
    j = next(k for k in range(i, len(rows)) if rows[k] and rows[k][0] == "種類")
    body = [r for r in rows[j + 1 : j + 4]]
    assert [(r[0], r[1], r[2]) for r in body] == [("足された", "5.000", "mm"), ("足された", "2.000", "mm"), ("削られた", "-6.000", "mm")], body
    assert any("許容 ±0.15 mm" in c for r in rows[i : j + 1] for c in r), rows[i : j + 1]
    print("OK: 版の比較の変わった所")
