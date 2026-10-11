"""E2E: the dimension line stands where the user clicked (issue #23 item 8).

Two parallel faces are at their minimum distance wherever they overlap, and
BRepExtrema returns only a few of those places (often a corner), so the line
used to land far from both clicks. The page now sends the clicked points with
the request, and the backend puts the line through one of them, square to both
faces (backend/tests/test_measure.py has the cases in detail).

mini_mold.step (testdata/make_step_assembly.py): the plate's top is z 15 over
100 x 60, the cavity block's top z 35 over x 30..70, y 15..45. A click on the
plate at x 90 does not face the block, so the line goes through the click on
the block, down to the plate: from (x, y, 35) to (x, y, 15), with (x, y) the
point the click picked there.

Oracles: __cadPick at the clicked pixels (where the clicks landed), the known
heights of the two faces, and the line saved with the entry (the sidecar PUT
body, caught in the page: nothing reaches the shared backend).
"""
import json
import math

from nav_common import SURFACE, nav_session
from engine_net import Net

BLOCK_TOP = (50, 30, 35)

with nav_session() as n:
    page = n.page
    puts = []

    def sidecar(route):
        if route.request.method == "PUT":
            puts.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(json={})
        else:
            route.fulfill(json={"version": 1, "entries": []})

    Net.of(page).route("**/sidecar", sidecar)
    n.load(n.paths["step"])
    n.set_mode("計測")

    def measure(first, second):
        """click the two points; the line saved with the new entry, and where each click landed"""
        landed = []
        for q in (first, second):
            xy = n.project(q)
            hit = n.pick(xy)
            assert hit and hit["kind"] == "face" and math.dist(hit["point"], q) < 0.5, ("not on screen", q, hit)
            landed.append(hit["point"])
            page.mouse.click(*xy)
            page.wait_for_timeout(250)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離')", timeout=15000)
        page.wait_for_timeout(1200)  # the autosave (800 ms debounce)
        entries = puts[-1]["entries"]
        line = [e for e in entries if e.get("line")][-1]["line"]
        return line, landed

    def close(a, b, tol=1e-3):
        """1 µm: the page's click and __cadPick at the projected pixel round the
        pointer a little differently (a corner of the overlap is tens of mm off)"""
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    # ---- 1. the plate (x 90: not under the block), then the block's top
    line, (pa, pb) = measure(SURFACE, BLOCK_TOP)
    print("1 line", line, "clicks", pa, pb)
    assert "20.000" in page.text_content("#hud-info"), page.text_content("#hud-info")
    assert close(line[0], (pb[0], pb[1], 15)) and close(line[1], (pb[0], pb[1], 35)), (
        "1 the line must go through the click on the block", line, pb)

    # ---- 2. the other way round: the block first, then the plate
    line, (pa, pb) = measure(BLOCK_TOP, SURFACE)
    print("2 line", line, "clicks", pa, pb)
    assert close(line[0], (pa[0], pa[1], 35)) and close(line[1], (pa[0], pa[1], 15)), (
        "2 the line must go through the click on the block", line, pa)

    n.set_mode("なし")
    print("MEASURE LINE E2E OK")
