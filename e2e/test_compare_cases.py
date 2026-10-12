"""E2E: 版の比較 on pairs of versions with one known change each (the cases
#59 asks the comparison to show as meant; testdata/make_step_assembly.py
make_compare_cases). The new version is open, the previous one compared with it.

- the same shape (a file against itself): no place changed
- a hole moved (R3 at (20, 20) to (25, 20)): added where the old hole was (the
  new version's faces over it), removed where the new one is. The largest
  change is the hole's radius, 3 (the old hole's middle is 3 from its wall),
  less up to about a finer triangle's edge (the finer mesh need not have a
  point at the very middle). Each place: the faces over the hole's crescent
  (2 x 26.0 mm²: a disc of R3 less its overlap with the other, two discs 5
  apart overlapping 2.25 mm²) and the other hole's wall inside it (an arc of
  1.17 rad x R3 x 3 high, 10.5 mm²), less the band at its foot
- a plate made thicker (3 to 3.5): added +0.50, its top (2400 mm²) and the
  sides' bands from 3 up (200 mm around x 0.5), the band's lowest part within
  the tolerance not counted
- a part taken away and one added (an assembly: the pin R2 x 10 gone, a cap 10
  x 10 x 4 new): added the cap's top and sides (+4.00, 100 + 160 mm²), removed
  the pin's top and side (-10.00, 12.6 + 125.7 mm²), less their bands at the
  plate. The 記録's table has the two
"""
import csv
import io
import math
from pathlib import Path

import gui_common
from nav_common import TESTDATA, nav_session

CRESCENT = 2 * (math.pi * 9 - (18 * math.acos(5 / 6) - 2.5 * math.sqrt(11))) + 2 * math.acos(5 / 6) * 3 * 3

with nav_session() as nav:
    page = nav.page

    def compare(case, other=None):
        """open case's b, compare it with its a (or `other`): its places, and the tolerance"""
        nav.load(TESTDATA / f"compare_{case}_b.step", props="live")
        with page.expect_file_chooser() as fc:
            nav.ctl("別の版と比べる").locator("button").click()
        fc.value.set_files(str(other or TESTDATA / f"compare_{case}_a.step"))
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
        nav.settle()
        tol = float(nav.ctl("許容").locator("input").input_value())
        return page.evaluate("window.__cadCompare()"), tol

    def near(x, y, rel):
        return abs(x - y) <= rel * y

    def stop():
        nav.ctl("比較をやめる").locator("button").click()
        nav.settle()

    # ---- the same shape: nothing -------------------------------------------------------
    p, _ = compare("thick", TESTDATA / "compare_thick_b.step")
    assert p["added"] == [] and p["removed"] == [], p
    stop()

    # ---- a hole moved ------------------------------------------------------------------
    p, tol = compare("hole")
    (add,), (rem,) = p["added"], p["removed"]
    for q, sign, centre in ((add, 1, (20, 20)), (rem, -1, (25, 20))):
        assert 2.6 <= sign * q["peak"] <= 3.0 + 1e-3, q  # the radius, less up to a finer edge
        assert math.hypot(q["at"][0] - centre[0], q["at"][1] - centre[1]) < 0.5, q["at"]
        assert 0.85 * CRESCENT < q["area"] < CRESCENT, (q["area"], CRESCENT)
    stop()

    # ---- a plate made thicker ----------------------------------------------------------
    p, tol = compare("thick")
    assert p["removed"] == [], p
    (add,) = p["added"]
    assert abs(add["peak"] - 0.5) < 1e-3 and abs(add["at"][2] - 3.5) < 1e-3, add
    want = 60 * 40 + 200 * (0.5 - tol)
    assert near(add["area"], want, 0.01), (add["area"], want)
    stop()

    # ---- a part taken away, one added --------------------------------------------------
    p, tol = compare("parts")
    (add,), (rem,) = p["added"], p["removed"]
    assert abs(add["peak"] - 4) < 1e-3 and 5 <= add["at"][0] <= 15 and 28 <= add["at"][1] <= 38, add
    assert near(add["area"], 100 + 160 - 40 * tol, 0.01), add["area"]
    assert abs(rem["peak"] + 10) < 1e-3 and math.hypot(rem["at"][0] - 50, rem["at"][1] - 30) <= 2 + 1e-3, rem
    assert near(rem["area"], math.pi * 4 + 2 * math.pi * 2 * (10 - tol), 0.01), rem["area"]
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    page.wait_for_selector("#report-pop:not(.hidden)")
    with page.expect_download() as d:
        page.click("#report-csv")
    rows = list(csv.reader(io.StringIO(Path(d.value.path()).read_bytes().decode("utf-8-sig"), newline="")))
    i = next(k for k, r in enumerate(rows) if r and r[0].startswith("版の比較"))
    j = next(k for k in range(i, len(rows)) if rows[k] and rows[k][0] == "種類")
    assert rows[i][0] == "版の比較（2 所）", rows[i]
    assert [(r[0], r[1]) for r in rows[j + 1 : j + 3]] == [("足された", "4.000"), ("削られた", "-10.000")], rows[j + 1 : j + 3]
    page.keyboard.press("Escape")
    print("OK: 版の比較の分かっている変化")
