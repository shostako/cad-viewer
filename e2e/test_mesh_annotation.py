"""Regression: annotation mode must work on mesh models (STL/3MF).

Bug (fixed): pack_trimesh() ships faceRanges: [] for mesh formats, and the
picker's face fallback returned null for them — every click on the model
surface (away from vertex/edge snap range) was silently ignored, so 注記
mode could not place a note and measure mode never showed its HUD hint.
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

STL = str(TESTDATA / "ribbed_plate.stl")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", STL)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')",
        timeout=15000,
    )
    page.wait_for_timeout(500)

    # annotation on the mesh surface (center of the plate — no vertex nearby)
    page.locator(".lil-gui select").first.select_option("注記")
    pt = page.evaluate("window.__cadProject(0, 0, 12)")  # top face center
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("メッシュ注記テスト")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)

    items = page.locator("#measure-list li").all_text_contents()
    print("entries:", items)
    assert any("メッシュ注記テスト" in i for i in items), items

    # measure mode on a mesh must show the STEP/IGES-only hint, not silence
    page.locator(".lil-gui select").first.select_option("計測")
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(500)
    hud = page.text_content("#hud-info")
    print("HUD:", hud)
    assert "STEP/IGES" in hud, f"expected mesh-measure hint, got: {hud}"

    assert not errors, errors
    print("MESH ANNOTATION E2E OK")
    browser.close()
