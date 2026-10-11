"""E2E: 厚肉 in 問題の一覧 (#59 P1 2): where a sink or a void is to be feared.

The specification, written out here (not read from the code):
- 問題の一覧 > 厚肉を調べる (on at first): a place is where a sphere at least
  the ratio x the general wall across fits in the part. The ratio is the 肉厚
  folder's 厚肉 (一般部の倍): the material's (1.5 for the resins) while
  判定の基準 follows it; the general wall each part's own, or the one given.
  The conditions say both; the counts have 厚肉 after 薄肉.
- A row: the largest sphere's diameter and its ratio, the part, where the
  sphere touches the surface. Pressed: the view goes there and the sphere is
  drawn, seen through the faces in front of it.
- The 記録 (CSV) has the rows (厚肉, the diameter in mm).
- 材料の基準 has the ratio for the resins, none for the metals.

Oracles (none from the code under test): ribbed_plate.stl's make
(testdata/make_testdata.py): an 80 x 50 x 2 plate, three ribs 1.2 thick, two
bosses of radius 3 at (±30, 18) from z 2 to 12. The plate is the general wall
(2); the bosses are the two places, a sphere 6 across (a little under: the
cylinder is a polygon) centred on their axes 3 to 9 up; the ribs' junctions
are not (a rib thinner than the wall). The screen's pixels where the sphere
projects (window.__cadProject).
"""
import csv
import io
from pathlib import Path

import numpy as np
from PIL import Image

import gui_common
from nav_common import TESTDATA, nav_session

RIBBED = TESTDATA / "ribbed_plate.stl"
BOSSES = [(-30, 18), (30, 18)]

with nav_session() as n:
    page = n.page
    page.set_viewport_size({"width": 1400, "height": 900})
    n.stub_sidecar()

    def check():
        return page.evaluate("window.__cadCheck()")

    def wait_list(pred="true"):
        page.wait_for_function(f"(() => {{ const c = window.__cadCheck(); return !!c && ({pred}) }})()", timeout=90000)
        n.settle()
        return check()

    def thick_rows(c):
        return [r for r in c["rows"] if r["kind"] == "thick"]

    def conditions():
        return page.inner_text("#check-panel .check-conditions")

    def shot():
        return np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB")).astype(int)

    def set_number(name, v):
        inp = gui_common.ctl(page, name).locator("input").last
        inp.fill(str(v))
        inp.press("Enter")
        page.evaluate("document.activeElement && document.activeElement.blur()")

    n.load(str(RIBBED), props="live")
    gui_common.open_folder(page, "肉厚")
    gui_common.open_folder(page, "問題の一覧")
    assert gui_common.ctl(page, "厚肉を調べる").locator("input").is_checked()
    assert float(gui_common.ctl(page, "厚肉 (一般部の倍)").locator("input").last.input_value()) == 1.5
    gui_common.ctl(page, "一覧を出す").locator("input").check()
    c = wait_list("c.rows.some(r => r.kind === 'thick')")
    rows = thick_rows(c)
    assert len(rows) == 2, rows
    for s in rows:
        cx, cy, cz = s["sphere"]["center"]
        assert 5.9 <= s["value"] <= 6.0 + 1e-6 and abs(s["sphere"]["radius"] * 2 - s["value"]) < 1e-6, s
        assert min(abs(cx - bx) + abs(cy - by) for bx, by in BOSSES) <= 0.3, ("on a boss's axis", s)
        assert 3 - 0.1 <= cz <= 9 + 0.1, ("3 to 9 up", s)
        # where it touches: the boss's side (3 from the axis) or the plate's bottom
        ax, ay, az = s["at"]
        assert abs(np.hypot(ax - cx, ay - cy) ** 2 + (az - cz) ** 2 - (s["value"] / 2) ** 2) < 0.1, s
        # the general wall is the plate's (2): the ratio about 3
        assert abs(s["ratio"] - s["value"] / 2) <= 0.2, s
    assert sorted(round(r["sphere"]["center"][0]) for r in rows) == [-30, 30]
    cond = conditions()
    assert "厚肉 一般部の 1.5 倍以上（一般部 部品ごとに自動）" in cond, cond
    counts = page.inner_text("#check-panel .check-counts")
    assert counts.startswith("薄肉 0・厚肉 2・勾配不足"), counts
    texts = page.locator("#check-panel li[data-kind='thick'] .check-value").all_inner_texts()
    assert all(t.startswith("⌀5.9") and "一般部の" in t and t.endswith("倍") for t in texts), texts
    print("1 two places:", [r["value"] for r in rows], cond)

    # ---- a row pressed: the view goes there, the sphere drawn over the faces
    cx, cy, cz = rows[0]["sphere"]["center"]
    page.locator("#check-panel li[data-kind='thick'] .check-go").first.click()
    page.wait_for_function("document.querySelector('.spot-marker')?.textContent.includes('一般部の')", timeout=10000)
    page.wait_for_timeout(1000)  # the view's move
    n.settle()
    p = n.project((cx, cy, cz))
    with_sphere = shot()[int(p[1]) - 3 : int(p[1]) + 4, int(p[0]) - 3 : int(p[0]) + 4].reshape(-1, 3).mean(axis=0)
    # the sphere is purple over the part's light blue: red and blue over green
    r_, g_, b_ = with_sphere
    assert r_ > g_ + 10 and b_ > g_ + 10, ("the sphere over the boss", with_sphere)
    print("2 the sphere at", [round(v) for v in p], with_sphere.round())

    # ---- the ratio by hand: 3.5 is more than the bosses' (about 3): none; 判定の基準 is 手で決める
    set_number("厚肉 (一般部の倍)", 3.5)
    c = wait_list("!c.rows.some(r => r.kind === 'thick')")
    assert gui_common.ctl(page, "判定の基準").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "手で決める"
    assert "厚肉 一般部の 3.5 倍以上" in conditions(), conditions()
    # the general wall given (1 mm): the plate (2) is thick too now, and with
    # the bosses on it one place (the STL's bodies only touch, a box, ribs and
    # cylinders laid together: their union is the part). Its largest is a boss's
    set_number("厚肉 (一般部の倍)", 1.5)
    set_number("一般部 (mm・0 で自動)", 1)
    c = wait_list("c.rows.some(r => r.kind === 'thick') && !!document.querySelector('#check-panel .check-conditions')?.textContent.includes('一般部 1.0 mm')")
    rows = thick_rows(c)
    assert len(rows) == 1 and 5.9 <= rows[0]["value"] <= 6.0 + 1e-6, rows
    assert abs(rows[0]["ratio"] - rows[0]["value"]) <= 0.01, ("the ratio to 1 mm", rows[0])
    set_number("一般部 (mm・0 で自動)", 0)
    wait_list("c.rows.filter(r => r.kind === 'thick').length === 2")
    print("3 the ratio and the general wall")

    # ---- the material's ratio: PMMA's at 3.2 (材料の基準), 判定の基準 back on the material: the bosses (about 3) are not 厚肉
    page.click(".cv-material-edit")
    page.wait_for_selector("#basis-pop:not(.hidden)")
    page.locator("#basis-pop tr[data-material='PMMA'] .basis-thick").fill("3.2")
    page.click("#basis-save")
    page.keyboard.press("Escape")
    gui_common.ctl(page, "判定の基準").locator("select").select_option(label="材料に合わせる")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    c = wait_list("!c.rows.some(r => r.kind === 'thick') && !!document.querySelector('#check-panel .check-conditions')?.textContent.includes('3.2 倍以上')")
    assert float(gui_common.ctl(page, "厚肉 (一般部の倍)").locator("input").last.input_value()) == 3.2
    page.click(".cv-material-edit")
    page.wait_for_selector("#basis-pop:not(.hidden)")
    page.click("#basis-defaults")
    page.click("#basis-save")
    page.keyboard.press("Escape")
    wait_list("c.rows.filter(r => r.kind === 'thick').length === 2")
    print("3b the material's ratio")

    # ---- the 記録 has the rows
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    with page.expect_download() as d:
        page.click("#report-csv")
    page.keyboard.press("Escape")
    recs = list(csv.reader(io.StringIO(Path(d.value.path()).read_bytes()[3:].decode("utf-8"), newline="")))
    thick = [r for r in recs if r and r[0] == "厚肉"]
    assert len(thick) == 2 and all(5.9 <= float(r[1]) <= 6.0 and r[2] == "mm" for r in thick), thick
    print("4 the 記録:", thick[0][:3])
    # its page: the places' images, a 厚肉 one with its sphere (framed: in the image's middle, purple)
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    with page.expect_popup() as pp:
        page.click("#report-page")
    tab = pp.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), timeout=90000)
    tab.wait_for_load_state()
    page.keyboard.press("Escape")
    figs = tab.evaluate("[...document.querySelectorAll('figure.spot')].map(f => [f.querySelector('img').src, f.querySelector('figcaption').textContent])")
    thick_figs = [(src, cap) for src, cap in figs if " 厚肉 ⌀5.9" in cap]
    assert len(thick_figs) == 2, [cap for _, cap in figs]
    import base64

    img = np.asarray(Image.open(io.BytesIO(base64.b64decode(thick_figs[0][0].split(",", 1)[1]))).convert("RGB")).astype(int)
    h, w = img.shape[:2]
    mid = img[h // 2 - 4 : h // 2 + 5, w // 2 - 4 : w // 2 + 5].reshape(-1, 3).mean(axis=0)
    assert mid[0] > mid[1] + 10 and mid[2] > mid[1] + 10, ("the sphere in the image", mid)
    tab.close()
    print("4b the page:", thick_figs[0][1], mid.round())

    # ---- 厚肉を調べる off: no rows, not in the conditions or the counts
    gui_common.ctl(page, "厚肉を調べる").locator("input").uncheck()
    c = wait_list("!c.rows.some(r => r.kind === 'thick')")
    # (the basis may name 厚肉 in its source: the condition itself is what goes)
    assert "厚肉 一般部の" not in conditions() and "厚肉" not in page.inner_text("#check-panel .check-counts"), conditions()
    print("5 off")

    # ---- 材料の基準: the ratio for the resins, none for the metals
    page.click(".cv-material-edit")
    page.wait_for_selector("#basis-pop:not(.hidden)")
    assert page.locator("#basis-pop tr[data-material='PMMA'] .basis-thick").input_value() == "1.5"
    page.keyboard.press("Escape")
    gui_common.ctl(page, "用途").locator("select").select_option(label="一般")
    page.click(".cv-material-edit")
    page.wait_for_selector("#basis-pop:not(.hidden)")
    assert page.locator("#basis-pop tr[data-material='SUS304'] .basis-thick").count() == 0
    page.keyboard.press("Escape")
    assert not gui_common.ctl(page, "厚肉 (一般部の倍)").is_visible(), "一般: no 厚肉 rows"
    print("6 the materials' ratio")
    assert not n.errors, n.errors
print("THICK SPOTS E2E OK")
