"""E2E: an IGES of loose faces + construction lines (testdata/make_iges_loose.py).

- the tree shows one sewn solid and one curve group, not FACE x6 / EDGE x3
- 全体表示 frames the 10 x 20 x 30 box, not the 100 mm axis lines
- the lines are drawn in a color that shows on the dark background
"""
import io
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
IGES = str(TESTDATA / "loose_faces_box.igs")
BACKEND_PY = Path(__file__).resolve().parents[1] / "backend" / ".venv" / "bin" / "python"

# the fixture is generated (testdata/*.igs is git-ignored): make it on a fresh
# checkout. Needs OCP, so it runs in the backend venv, not this interpreter.
if not Path(IGES).exists():
    subprocess.run([str(BACKEND_PY), str(TESTDATA / "make_iges_loose.py")], check=True)
CURVE = (0xE0, 0xB0, 0x50)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.set_input_files("#file-input", IGES)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('三角形')", timeout=60000)
    page.wait_for_timeout(800)
    print("HUD:", page.text_content("#hud-info"))

    labels = page.locator("#tree-panel label span").all_text_contents()
    print("tree:", labels)
    assert labels == ["ソリッド", "曲線（3 本）"], labels
    assert "10.0 × 20.0 × 30.0 mm" in page.text_content("#hud-info"), page.text_content("#hud-info")

    # framing: the box's projected size on screen
    corners = [[x, y, z] for x in (0, 10) for y in (0, 20) for z in (0, 30)]
    pts = [page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", c) for c in corners]
    h = max(q["y"] for q in pts) - min(q["y"] for q in pts)
    w = max(q["x"] for q in pts) - min(q["x"] for q in pts)
    print(f"box on screen: {w:.0f} x {h:.0f} px")
    assert h > 800 * 0.4, ("全体表示 must frame the box, not the axis lines", h)

    # the axis lines are visible (amber), not the near-background edge color.
    # Not counted on the part tree: its mark for the curves is amber too
    img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    t = page.locator("#tree-panel").bounding_box()
    ImageDraw.Draw(img).rectangle((t["x"], t["y"], t["x"] + t["width"], t["y"] + t["height"]), fill=(0, 0, 0))
    amber = sum(1 for px in img.getdata() if max(abs(a - b) for a, b in zip(px, CURVE)) < 40)
    print("amber pixels:", amber)
    assert amber > 100, amber

    page.screenshot(path="/tmp/cad_viewer_iges_sewing.png")
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("IGES SEWING E2E OK")
    browser.close()
