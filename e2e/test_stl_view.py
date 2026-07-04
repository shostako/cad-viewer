from playwright.sync_api import sync_playwright

STL = "/home/shostako/ClaudeCode/cad-viewer/testdata/ribbed_plate.stl"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto("http://127.0.0.1:5183")
    page.wait_for_load_state("networkidle")
    page.screenshot(path="/tmp/cad_viewer_initial.png")

    page.set_input_files("#file-input", STL)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')",
        timeout=15000,
    )
    page.wait_for_timeout(800)  # let camera/grid settle & render
    hud = page.text_content("#hud-info")
    print("HUD:", hud)
    page.screenshot(path="/tmp/cad_viewer_loaded.png")

    assert "304 tris" in hud, f"unexpected HUD: {hud}"
    assert "80.0 × 50.0 × 12.0" in hud, f"unexpected bbox: {hud}"
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors, "console errors detected"
    print("E2E OK")
    browser.close()
