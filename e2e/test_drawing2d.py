"""E2E Phase 4: DXF drawing view + snap measurement (hole pitch = 100.000)."""
from playwright.sync_api import sync_playwright

import os
from pathlib import Path
import gui_common

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")

DXF = str(TESTDATA / "plate_drawing.dxf")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", DXF)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('2D図面')", timeout=60000
    )
    hud = page.text_content("#hud-info")
    print("HUD:", hud)
    assert "200.0 × 100.0" in hud, hud
    page.wait_for_timeout(300)
    page.screenshot(path="/tmp/cad_viewer_dxf.png")

    # measure mode: click the two hole centers (dxf (50,50) and (150,50))
    gui_common.ctl(page, "モード").locator("select").select_option("計測")

    def svg_click(dxf_x, dxf_y):
        # snap points carry svg coords; convert via the svg CTM in-page
        pos = page.evaluate(
            """([x, y]) => {
                const svg = document.querySelector('#viewport2d svg')
                const vb = svg.viewBox.baseVal
                // viewBox is padded (vb.x = -pad); content spans vb.width + 2*vb.x
                const sx = (vb.width + 2 * vb.x) / 200, sy = (vb.height + 2 * vb.y) / 100
                const svgX = x * sx, svgY = (100 - y) * sy
                const ctm = svg.getScreenCTM()
                const pt = new DOMPoint(svgX, svgY).matrixTransform(ctm)
                return { x: pt.x, y: pt.y }
            }""",
            [dxf_x, dxf_y],
        )
        page.mouse.click(pos["x"], pos["y"])
        page.wait_for_timeout(300)

    svg_click(50, 50)
    hud = page.text_content("#hud-info")
    print("after A:", hud)
    assert "(50, 50)" in hud, hud

    svg_click(150, 50)
    hud = page.text_content("#hud-info")
    print("after B:", hud)
    assert "100.000" in hud, f"hole pitch should be exactly 100.000: {hud}"

    page.screenshot(path="/tmp/cad_viewer_dxf_measure.png")

    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("DRAWING2D E2E OK")
    browser.close()
