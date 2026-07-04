from playwright.sync_api import sync_playwright

import os
from pathlib import Path

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5173")

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
        "document.querySelector('#hud-info').textContent.includes('tris')",
        timeout=60000,
    )
    page.wait_for_timeout(1000)
    hud = page.text_content("#hud-info")
    print("HUD:", hud)

    # tree panel visible with 4 parts
    assert not page.locator("#tree-panel").evaluate("el => el.classList.contains('hidden')")
    labels = page.locator("#tree-panel label span").all_text_contents()
    print("tree labels:", labels)
    assert "mini_mold" in labels
    assert labels.count("core_pin") == 2

    page.screenshot(path="/tmp/cad_viewer_step.png")

    # toggle a core_pin off and confirm scene doesn't error
    page.locator("#tree-panel label", has_text="core_pin").first.locator("input").click()
    page.wait_for_timeout(500)
    page.screenshot(path="/tmp/cad_viewer_step_toggled.png")

    assert "4 parts" in hud, hud
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("STEP E2E OK")
    browser.close()
