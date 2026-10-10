"""E2E: projected area and clamping force in the 体積・重量 panel (issue #47 item 4).

Expected values come from how mini_mold is built (make_step_assembly.py:
plate 100 x 60 x 15 at the origin; core pins r 4, z 15..40 at (25, 30) and
(75, 30); cavity block 40 x 30 x 20 at (30, 15, 15)) and from F = p x A
(1 MPa on 1 mm² is 1 N; 1 tf = 9806.65 N). The shadows:
  along Z: 100 x 60                                   = 6000 mm²
  along X: plate 60 x 15 + block 30 x 20 + pins 8 x 5 = 1540 mm²
  along Y: plate 100 x 15 + block 40 x 20 + 2 x 8 x 25 = 2700 mm²
  along X without the plate: 600 + 40                 = 640 mm²

- the panel shows 投影面積（axis） and 型締力（p MPa） for the 抜き勾配's
  型開き方向 (its sign does not matter) and the 型内圧 (default 40 MPa)
- the area follows the direction and the parts shown in the tree; nothing
  shown, nothing projected
- the 型内圧 survives a reload
- while the area is asked for, 計算中…; no rows on a 2D drawing
  (along Y without the plate: block 40 x 20 + pins 2 x 8 x 25 = 1200 mm²)
"""
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
import gui_common

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
DXF = str(TESTDATA / "plate_drawing.dxf")
G = 9.80665
# the area is an estimate from a rasterised shadow (backend/app/projection.py):
# mini_mold's lands within 0.03 %; the rows round to 0.01 cm², 0.1 kN, 0.1 tf
REL = 5e-4

tmp = tempfile.mkdtemp(prefix="cad_proj_")
# a private copy (its own content hash, so its own sidecar): the measurements
# other scripts leave on mini_mold.step never show up here
STEP = os.path.join(tmp, "proj_mold.step")
Path(STEP).write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 17)


def num(text):
    return float(text.replace(",", "").split()[0])


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        page.evaluate("localStorage.removeItem('cad-viewer:props'); localStorage.removeItem('cad-viewer:draft')")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        def load(path):
            page.set_input_files("#file-input", path)
            page.wait_for_function(
                "(n) => document.querySelector('#hud-info').textContent.includes(n)"
                " && !document.querySelector('#props-total').classList.contains('hidden')",
                arg=Path(path).name,
                timeout=60000,
            )

        def shown(axis, area_mm2, mpa):
            """wait for the rows of this axis to carry a value, then check them against area and pressure"""
            page.wait_for_function(
                "(a) => document.querySelector('#props-proj-label').textContent === `投影面積（${a}）`"
                " && document.querySelector('#props-total-proj').textContent.endsWith('cm²')",
                arg=axis,
                timeout=60000,
            )
            area = page.inner_text("#props-total-proj")
            assert area.endswith(" cm²") and abs(num(area) - area_mm2 / 100) <= 0.005 + REL * area_mm2 / 100, (
                axis, area, area_mm2)
            assert page.inner_text("#props-clamp-label") == f"型締力（{mpa:g} MPa）", page.inner_text("#props-clamp-label")
            clamp = page.locator("#props-total-clamp")
            sub = clamp.locator(".sub").inner_text()
            kn = clamp.evaluate("e => e.firstChild.textContent")
            newtons = area_mm2 * mpa
            assert kn.endswith(" kN") and abs(num(kn) - newtons / 1000) <= 0.05 + REL * newtons / 1000, (kn, newtons)
            assert sub.startswith("（") and sub.endswith(" tf）"), sub
            assert abs(num(sub[1:]) - newtons / 1000 / G) <= 0.05 + REL * newtons / 1000 / G, (sub, newtons)
            note = page.inner_text("#props-note")
            assert "投影面積・型締力は表示用メッシュからの目安" in note, note

        def tree_box(name):
            label = page.locator("#tree-panel label", has_text=name).first
            return label.locator("xpath=..").locator("input").first

        # 1. along Z (the default 型開き方向 +Z), 40 MPa
        load(STEP)
        shown("Z", 6000, 40)

        # 2. the direction of the 抜き勾配 drives it; −X and +X project alike
        direction = gui_common.ctl(page, "型開き方向").locator("select")
        direction.select_option(label="−X")
        shown("X", 1540, 40)
        direction.select_option(label="+Y")
        shown("Y", 2700, 40)
        direction.select_option(label="+X")
        shown("X", 1540, 40)

        # 3. the cavity pressure: the force follows, the area stays
        pressure = gui_common.ctl(page, "型内圧").locator("input")
        pressure.fill("75")
        pressure.press("Enter")
        shown("X", 1540, 75)

        # 4. the parts shown in the tree: without the plate, the block and the pins
        tree_box("plate").click()
        shown("X", 640, 75)
        page.get_by_role("button", name="全部表示", exact=True).click()
        shown("X", 1540, 75)

        # 5. while the answer is on its way: 計算中…, then the value (along Y
        # without the plate, not asked for before: block 40 x 20 + pins 2 x 8 x 25)
        direction.select_option(label="+Y")
        shown("Y", 2700, 75)
        page.evaluate("window.__cadStallProjection(1500)")
        tree_box("plate").click()
        page.wait_for_function(
            "document.querySelector('#props-total-proj').textContent === '計算中…'", timeout=5000
        )
        assert page.inner_text("#props-total-clamp") == "—"
        shown("Y", 1200, 75)
        page.get_by_role("button", name="全部表示", exact=True).click()
        direction.select_option(label="−Z")
        shown("Z", 6000, 75)

        # 6. the pressure and the direction survive a reload
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        load(STEP)
        shown("Z", 6000, 75)
        assert float(gui_common.ctl(page, "型内圧").locator("input").input_value()) == 75

        # 7. a 2D drawing: no panel, no rows
        page.set_input_files("#file-input", DXF)
        page.wait_for_function("document.querySelector('#props-panel').classList.contains('hidden')", timeout=60000)
        page.wait_for_function(
            "(n) => document.querySelector('#hud-info').textContent.includes(n)", arg=Path(DXF).name, timeout=60000
        )
        page.wait_for_timeout(400)  # past the debounce: no request may bring the rows back
        assert page.locator("#props-panel").is_hidden()

        assert not errors, errors
        browser.close()
    print("OK test_projection")


if __name__ == "__main__":
    main()
