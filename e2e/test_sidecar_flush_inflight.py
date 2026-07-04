"""Regression (PR #4 round-2): teardown must await an already-in-flight sidecar
PUT, not just a queued pendingSave.

Bug (fixed): when the debounce timer fired, flushSidecar() cleared pendingSave
and started the PUT. A same-id reload then reached `await flushSidecar()`, saw
pendingSave === undefined, and returned immediately — so getSidecar() could run
before the write landed and restore stale entries. Fix tracks the in-flight PUT
(inFlightSave) and every teardown awaits it.

The __cadStallSidecar(ms) hook holds the NEXT PUT in flight so the reload
deterministically races the debounce-timer save.
"""
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5173")

STEP = str(TESTDATA / "mini_mold.step")
NOTE = f"inflight検証{int(time.time())}"


def load(page):
    page.set_input_files("#file-input", STEP)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')",
        timeout=15000,
    )


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    load(page)
    page.wait_for_timeout(300)

    # arm: the NEXT sidecar PUT stalls 2s, giving us an in-flight window
    page.evaluate("window.__cadStallSidecar(2000)")

    # add an annotation -> starts the 800ms debounce timer
    page.locator(".lil-gui select").first.select_option("注記")
    pt = page.evaluate("window.__cadProject(50, 30, 15)")
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type(NOTE)
    page.keyboard.press("Enter")

    # wait past the debounce so the TIMER fires the (now-stalled) PUT
    page.wait_for_timeout(1000)
    # the PUT is in flight (stalled). Reload the SAME model: teardown must await
    # that in-flight write before getSidecar(), or the note is lost.
    load(page)
    page.wait_for_timeout(2500)  # let the stalled PUT settle + restore

    items = page.locator("#measure-list li").all_text_contents()
    print("restored entries:", items)
    assert any(NOTE in i for i in items), (
        f"note lost: teardown did not await the in-flight PUT: {items}"
    )
    assert not errors, errors
    print("SIDECAR FLUSH IN-FLIGHT OK")
    browser.close()
