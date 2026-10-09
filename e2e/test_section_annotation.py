"""E2E Phase 3: section clipping, annotation, sidecar persistence.

The section's 有効 is found by its name (gui_common): this script once ticked
"the first checkbox" of the operation panel, which is グリッド, and never
turned the section on. Now a pick checks the clipping itself: the plate's top
at x 90 is on the side the default section (axis X at 0.5, x <= 50 kept)
cuts away.

The model is a private copy of mini_mold.step (fifteen trailing newlines: its
own content hash, so its own sidecar; the other scripts' copies take the odd
counts 3 to 13). Its sidecar is emptied before and after:
the note this script writes no longer stays on the shared mini_mold.step,
where other scripts and the user's own views saw it.
"""
import os
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

import gui_common
from nav_common import empty_sidecar

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

tmp = tempfile.mkdtemp(prefix="cad_section_note_")
STEP = os.path.join(tmp, "mini_mold.step")
Path(STEP).write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 15)
CUT = (90, 10, 15)  # on the plate's top, on the side the section cuts away


def load_model(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", STEP)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000
    )
    page.wait_for_timeout(800)


def pick_at(page, xyz):
    xy = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
    return page.evaluate("([x, y]) => window.__cadPick(x, y)", [xy["x"], xy["y"]])


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(BASE_URL)
        empty_sidecar(page, STEP)  # a run that failed half way may have left its note
        load_model(page)

        # --- 1) section: 有効 cuts the plate's far half away
        hit = pick_at(page, CUT)
        assert hit and abs(hit["point"][0] - CUT[0]) < 0.5, ("the plate's top before the section", hit)
        gui_common.open_folder(page, "断面")
        enabled = gui_common.ctl(page, "有効").locator("input")
        enabled.click()
        page.wait_for_timeout(500)
        assert enabled.is_checked()
        hit = pick_at(page, CUT)
        print("section on, pick at x 90:", hit)
        assert hit is None or hit["point"][0] <= 50.5, ("the section did not cut", hit)
        page.screenshot(path="/tmp/cad_viewer_section.png")

        # disable section again
        enabled.click()
        page.wait_for_timeout(300)
        hit = pick_at(page, CUT)
        assert hit and abs(hit["point"][0] - CUT[0]) < 0.5, ("the plate's top is back", hit)

        # --- 2) annotation
        gui_common.set_mode(page, "注記")
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

        empty_sidecar(page, STEP)
        if errors:
            print("PAGE ERRORS:", errors)
        assert not errors
        print("PHASE3 E2E OK")
        browser.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
