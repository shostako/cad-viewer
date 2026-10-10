"""Regression (Issue #2): an edit made within the 800ms auto-save debounce
window must survive a model switch.

Bug (fixed): teardown cleared the pending debounce timer and clearAll() wiped
the entries before anything was written, so the last annotation/measurement was
lost from the OLD model's sidecar. Fix flushes the pending save on teardown.

This test deliberately switches models IMMEDIATELY after adding a note (no wait),
so the debounce timer has NOT fired yet — the note only persists if teardown
flushes it.
"""
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
import gui_common

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

STEP = str(TESTDATA / "mini_mold.step")
STL = str(TESTDATA / "ribbed_plate.stl")
NOTE = f"flush検証{int(time.time())}"


def load(page, path):
    page.set_input_files("#file-input", path)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('三角形')",
        timeout=15000,
    )


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    load(page, STEP)
    page.wait_for_timeout(300)

    # add an annotation
    gui_common.ctl(page, "モード").locator("select").select_option("注記")
    pt = page.evaluate("window.__cadProject(50, 30, 15)")
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type(NOTE)
    page.keyboard.press("Enter")
    # NO wait: switch models within the 800ms debounce window on purpose
    load(page, STL)
    page.wait_for_timeout(300)

    # reload the STEP — its sidecar must carry the note that teardown flushed
    load(page, STEP)
    page.wait_for_timeout(1000)
    items = page.locator("#measure-list li").all_text_contents()
    print("restored entries:", items)
    assert any(NOTE in i for i in items), f"note lost on fast model switch: {items}"

    assert not errors, errors
    print("SIDECAR FLUSH OK")
    browser.close()
