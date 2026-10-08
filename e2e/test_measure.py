"""E2E: measure exact distance between cavity top face and plate top face (= 20.000)."""
from playwright.sync_api import sync_playwright

import os
from pathlib import Path

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

STEP = str(TESTDATA / "mini_mold.step")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", STEP)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000
    )
    page.wait_for_timeout(800)

    # enable measure mode
    page.locator(".lil-gui select").first.select_option("計測")

    def click_world(x, y, z):
        pt = page.evaluate(f"window.__cadProject({x}, {y}, {z})")
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(400)

    # A: cavity_block top face center (50, 30, 35)
    click_world(50, 30, 35)
    hud = page.text_content("#hud-info")
    print("after click A:", hud)
    assert "選択" in hud, hud

    # B: plate top face, exposed near (90, 10, 15)
    click_world(90, 10, 15)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('距離')", timeout=10000
    )
    hud = page.text_content("#hud-info")
    print("after click B:", hud)
    assert "20.000" in hud, f"expected exact 20.000, got: {hud}"

    # measurement list has the entry
    items = page.locator("#measure-list li").all_text_contents()
    print("list:", items)
    assert any("20.000" in i for i in items)

    page.wait_for_timeout(400)
    page.screenshot(path="/tmp/cad_viewer_measure.png")

    # delete the entry -> panel hides
    page.locator("#measure-list li button").last.click()
    page.wait_for_timeout(200)

    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("MEASURE E2E OK")
    browser.close()
