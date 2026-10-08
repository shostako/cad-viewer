"""H1 regression: switching models must not corrupt the previous model's sidecar.

Bug (fixed): the debounced sidecar save captured the OLD model id while the
new model's teardown/restore was running, overwriting model A's sidecar with
[] (or model B's entries).
"""
import time

from playwright.sync_api import sync_playwright

import os
from pathlib import Path

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

STEP = str(TESTDATA / "mini_mold.step")
STL = str(TESTDATA / "ribbed_plate.stl")
NOTE = f"分離テスト{int(time.time())}"


def load(page, path):
    page.set_input_files("#file-input", path)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000
    )
    page.wait_for_timeout(600)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # model A: add a unique annotation
    load(page, STEP)
    page.locator(".lil-gui select").first.select_option("注記")
    pt = page.evaluate("window.__cadProject(50, 30, 35)")
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type(NOTE)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)  # let the debounced save land

    # switch to model B IMMEDIATELY after an entry change would be riskiest,
    # but also cover the plain switch: clear + switch within the debounce window
    page.locator(".lil-gui select").first.select_option("なし")
    load(page, STL)  # model B (mesh) — teardown of A happens here
    page.wait_for_timeout(1200)  # if the bug lives, the bad save fires now

    # back to model A: the annotation must still be there
    load(page, STEP)
    items = page.locator("#measure-list li").all_text_contents()
    print("restored entries:", items)
    assert any(NOTE in i for i in items), f"sidecar was corrupted: {items}"

    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("SIDECAR ISOLATION OK")
    browser.close()
