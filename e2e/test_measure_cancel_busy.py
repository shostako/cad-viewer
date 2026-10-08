"""Regression (Issue #3): leaving measure mode while a distance request is in
flight must not freeze subsequent picks.

Bug (fixed): cancelPending() bumped session (so the late response is dropped)
but left busy=true, so handlePick's `if (this.busy) return ''` ignored every new
pick until the abandoned request finally returned. Fix releases busy in
cancelPending, and handlePick's finally only clears busy if it still owns the
session (so a stale return can't reset a newer request's flag).

The __cadStallMeasure(ms) test hook holds the NEXT distance request in flight so
we can cancel mid-request deterministically.
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

STEP = str(TESTDATA / "mini_mold.step")


def select_mode(page, mode):
    page.locator(".lil-gui select").first.select_option(mode)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", STEP)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')",
        timeout=15000,
    )
    page.wait_for_timeout(300)

    # the model's sidecar may restore prior measurements — count by DELTA, not
    # absolute, so the test is independent of persisted state
    def dist_count():
        return len([i for i in page.locator("#measure-list li").all_text_contents() if "↔" in i])

    select_mode(page, "計測")
    before = dist_count()

    # hold the next distance request in flight for 2s
    page.evaluate("window.__cadStallMeasure(2000)")
    a = page.evaluate("window.__cadProject(25, 30, 15)")
    b = page.evaluate("window.__cadProject(75, 30, 15)")
    page.mouse.click(a["x"], a["y"])
    page.wait_for_timeout(100)
    page.mouse.click(b["x"], b["y"])  # fires the (stalled) distance request; busy=true
    page.wait_for_timeout(200)

    # leave measure mode WHILE the request is still stalled -> cancelPending
    select_mode(page, "なし")
    page.wait_for_timeout(100)

    # let the stalled request resolve (it is now stale and must be dropped)
    page.wait_for_timeout(2500)

    # back to measure mode: a fresh measurement must register (busy was released)
    select_mode(page, "計測")
    a2 = page.evaluate("window.__cadProject(25, 30, 15)")
    b2 = page.evaluate("window.__cadProject(75, 30, 15)")
    page.mouse.click(a2["x"], a2["y"])
    page.wait_for_timeout(100)
    page.mouse.click(b2["x"], b2["y"])
    page.wait_for_timeout(1000)

    after = dist_count()
    print(f"distance entries: before={before} after={after}")
    # +1 exactly: the cancelled (stalled) measurement was dropped, and the fresh
    # one registered — proving busy was released by cancelPending
    assert after == before + 1, (
        f"expected +1 (stalled dropped, fresh added), before={before} after={after}"
    )

    assert not errors, errors
    print("MEASURE CANCEL-BUSY OK")
    browser.close()
