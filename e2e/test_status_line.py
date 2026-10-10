"""E2E: the status line in Japanese with the right unit, and the empty screen's
operation panel (issue #47 item 3).

- STEP and IGES are read into mm: OCCT converts the file's unit. mini_mold.step
  (make_step_assembly.py: 4 parts, plate 100 x 60 x 15 with the block and pins
  up to z 40) reads "mini_mold.step — 4 部品・304 三角形・100.0 × 60.0 × 40.0 mm";
  the same file saying its unit is the metre (SI_UNIT($,.METRE.) in place of
  the millimetre) reads 1000 times as large, still in mm
- a mesh (ribbed_plate.stl, make_testdata.py: 80 x 50 plate, bosses up to z 12)
  claims no unit: "（単位はファイルのまま）"
- a drawing (plate_drawing.dxf, make_dxf.py: 200 x 100): "2D 図面・200.0 × 100.0"
- the empty screen's panel holds 表示 only; モード, 計測クリア, 画像の背景 and
  the model's folders come with a file, and go again when a failed load
  leaves the screen empty

Oracles: how the test data are made (the generators), the STEP file's own
unit, DOM visibility (getClientRects: the panel is fixed, offsetParent lies).
"""
import shutil
import tempfile
from pathlib import Path

from nav_common import BASE_URL, nav_session

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
MOLD = TESTDATA / "mini_mold.step"
STL = TESTDATA / "ribbed_plate.stl"
DXF = TESTDATA / "plate_drawing.dxf"
ITEMS = ["モード", "計測クリア", "画像の背景"]
MODEL_FOLDERS = ["断面", "肉厚", "抜き勾配", "体積・重量"]

with nav_session() as n:
    page = n.page
    n.stub_sidecar()

    def hud():
        return page.text_content("#hud-info")

    def shown():
        """the panel's controllers and folders on screen, by name"""
        return page.evaluate(
            """() => {
                 const vis = (e) => !!e && e.getClientRects().length > 0
                 const ctl = {}, fol = {}
                 for (const c of document.querySelectorAll('.lil-gui .lil-controller')) {
                   const name = c.querySelector('.lil-name')?.textContent
                   if (name) ctl[name] = vis(c)
                 }
                 for (const t of document.querySelectorAll('.lil-gui .lil-title')) {
                   const f = t.parentElement
                   if (f.classList.contains('lil-root')) continue
                   fol[t.textContent.trim()] = vis(t)
                 }
                 return { ctl, fol }
               }"""
        )

    def assert_empty_panel(tag):
        s = shown()
        print(tag, s)
        assert s["fol"].get("表示") is True, (tag, "表示 stays on the empty screen", s)
        for name in ITEMS:
            assert s["ctl"].get(name) is False, (tag, f"{name} comes with a file", s)
        for name in MODEL_FOLDERS:
            assert s["fol"].get(name) is False, (tag, f"{name} comes with a model", s)

    # ---- the empty screen
    assert_empty_panel("empty")

    # ---- a STEP file: parts, triangles, the size in mm
    tmp = tempfile.mkdtemp(prefix="cad_status_")
    try:
        mold = Path(tmp) / "mini_mold.step"
        mold.write_bytes(MOLD.read_bytes())
        n.load(mold)
        assert hud() == "mini_mold.step — 4 部品・304 三角形・100.0 × 60.0 × 40.0 mm", hud()
        s = shown()
        assert all(s["ctl"].get(k) for k in ITEMS), ("a model brings the items", s)
        assert all(s["fol"].get(k) for k in ["表示", *MODEL_FOLDERS]), ("a model brings the folders", s)

        # ---- the same model, the file saying metres: OCCT reads it into mm
        text = MOLD.read_text()
        # every representation states its length unit (one per part): all of them become metres
        assert text.count("SI_UNIT(.MILLI.,.METRE.)") >= 1, "the test file states its length unit"
        metres = Path(tmp) / "mold_in_metres.step"
        metres.write_text(text.replace("SI_UNIT(.MILLI.,.METRE.)", "SI_UNIT($,.METRE.)"))
        n.load(metres)
        # (the triangles may differ: the pins are 1000 times as large for the tessellation)
        assert hud().startswith("mold_in_metres.step — 4 部品・") and hud().endswith("三角形・100000.0 × 60000.0 × 40000.0 mm"), hud()

        # ---- a mesh: no unit claimed
        n.load(STL)
        assert hud().startswith("ribbed_plate.stl — ") and hud().endswith("三角形・80.0 × 50.0 × 12.0（単位はファイルのまま）"), hud()
        assert " mm" not in hud(), hud()

        # ---- a drawing
        n.load(DXF, wait_text="2D 図面")
        assert hud() == "plate_drawing.dxf — 2D 図面・200.0 × 100.0（計測で端点・中心に吸い付く）", hud()
        s = shown()
        assert s["ctl"].get("モード") is True, ("a drawing measures", s)
        for name in ["表示", *MODEL_FOLDERS]:
            assert s["fol"].get(name) is False, ("a drawing has no 3D folders", name, s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- a fresh page, a failed load, the card closed: the empty panel again
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    bad = Path(tempfile.mkdtemp(prefix="cad_status_bad_")) / "notes.txt"
    try:
        bad.write_text("not a CAD file")
        page.set_input_files("#file-input", str(bad))
        page.wait_for_function("document.querySelector('#load-card')?.textContent.includes('対応していない')", timeout=30000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert_empty_panel("after a failed load")
        # the refusal of that file (415) is the browser's console error this step asked for
        n.errors[:] = [e for e in n.errors if "status of 415" not in e]
    finally:
        shutil.rmtree(bad.parent, ignore_errors=True)
    print("STATUS LINE E2E OK")
