"""E2E Phase 3: section clipping, annotation, sidecar persistence."""
from playwright.sync_api import sync_playwright

STEP = "/home/shostako/ClaudeCode/cad-viewer/testdata/mini_mold.step"


def load_model(page):
    page.goto("http://127.0.0.1:5183")
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", STEP)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000
    )
    page.wait_for_timeout(800)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    load_model(page)

    # --- 1) section: open folder, enable clipping
    page.locator(".lil-gui .lil-title", has_text="断面").click()
    page.wait_for_timeout(200)
    page.locator(".lil-gui input[type=checkbox]").first.click()  # 有効
    page.wait_for_timeout(500)
    page.screenshot(path="/tmp/cad_viewer_section.png")
    print("section screenshot taken")

    # disable section again
    page.locator(".lil-gui input[type=checkbox]").first.click()
    page.wait_for_timeout(300)

    # --- 2) annotation
    page.locator(".lil-gui select").first.select_option("注記")
    pt = page.evaluate("window.__cadProject(50, 30, 35)")
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("ゲート位置ここ")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)  # debounce save = 800ms
    items = page.locator("#measure-list li").all_text_contents()
    print("entries:", items)
    assert any("ゲート位置ここ" in i for i in items), items
    labels = page.locator(".note-label").all_text_contents()
    assert "ゲート位置ここ" in labels, labels
    page.screenshot(path="/tmp/cad_viewer_annotation.png")

    # --- 3) persistence: reload and re-upload the same file
    load_model(page)
    page.wait_for_timeout(500)
    items = page.locator("#measure-list li").all_text_contents()
    print("restored entries:", items)
    assert any("ゲート位置ここ" in i for i in items), f"annotation not restored: {items}"
    labels = page.locator(".note-label").all_text_contents()
    assert "ゲート位置ここ" in labels
    page.screenshot(path="/tmp/cad_viewer_restored.png")

    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("PHASE3 E2E OK")
    browser.close()
