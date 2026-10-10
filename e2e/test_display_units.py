"""E2E: 計測の単位・桁 (issue #59 P1 6): the screen only.

- 表示 has 計測の単位 (mm, インチ) and 計測の桁 (小数 0〜6 桁): mm and 3 at first.
- With インチ and 4 decimals: the list's rows (a diameter, a distance with its
  ΔX ΔY ΔZ, an angle), the 3D labels, the status line of a new measurement,
  the size beside the cursor and すべてコピー say the numbers in inches with 4
  decimals; an angle stays in degrees (4 decimals). Back to mm and 3: as
  before, to the character.
- The saved entries do not change: no save is sent on a switch, and the
  sidecar reads the same; a new entry keeps its number (value) as the backend
  gave it. The 記録's CSV keeps mm, every digit.
- The choice survives a reload. An entry saved before the numbers were kept
  (text only) is shown in inches too, from its text.
- A file written in inches (inch_block.step) says so on the status line (元の
  単位: in), comes in mm (its size), and the 記録 names its unit; a file in mm
  says nothing more.

Oracles (none from the code under test): mini_mold.step's make
(testdata/make_step_assembly.py): the pins of radius 4 (⌀8), the pin's top
(z 40) 25 above the plate's top (z 15), the plate's top and front face at 90°;
inch_block.step's: 1 x 2 x 0.5 in, 25.4 x 50.8 x 12.7 mm. 25.4 mm an inch.
The plate's corner (0, 0, 15) to the second pin's top (a disk of radius 4 at
(75, 30), z 40): to the disk's rim toward the corner, by hand.
The sidecar as the backend gives it back.
"""
import csv
import io
import math
import tempfile
from pathlib import Path

import gui_common
from nav_common import BASE_URL, TESTDATA, empty_sidecar, nav_session, put_sidecar

IN = 25.4
# the plate's corner to the second pin's top: the rim's point toward the corner
_C = math.hypot(75, 30)
SLANT_AT = (75 - 4 * 75 / _C, 30 - 4 * 30 / _C, 40)
SLANT = math.dist((0, 0, 15), SLANT_AT)
tmp = tempfile.mkdtemp(prefix="cad_units_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 79)
old = Path(tmp) / "old_mini_mold.step"  # an entry saved before the numbers were kept
old.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 81)
INCH_BLOCK = TESTDATA / "inch_block.step"


def model_id(page, path):
    """the backend's id of these bytes under this name (the app's: the same entry is used again)"""
    r = page.request.post(
        f"{BASE_URL}/api/models",
        multipart={"file": {"name": Path(path).name, "mimeType": "application/octet-stream", "buffer": Path(path).read_bytes()}},
        timeout=120000,
    )
    assert r.ok, r.status
    return r.json()["id"]


with nav_session() as n:
    page = n.page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    puts = []
    page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" and r.url.endswith("/sidecar") else None)

    def rows():
        return page.evaluate(
            "[...document.querySelectorAll('#measure-list li')].map(li => [li.dataset.kind, li.querySelector('.m-value')?.textContent ?? '',"
            " li.querySelector('.m-where')?.textContent ?? ''])"
        )

    def labels():
        return sorted(page.evaluate("[...document.querySelectorAll('.dim-label')].map(e => e.textContent)"))

    def hud():
        return page.inner_text("#hud-info")

    def set_shown(unit, digits):
        gui_common.ctl(page, "計測の単位").locator("select").select_option(label=unit)
        gui_common.ctl(page, "計測の桁").locator("select").select_option(label=f"小数 {digits} 桁")
        n.settle()

    def click(xyz, kind="face"):
        xy = n.project(xyz)
        p = n.pick(xy)
        assert p and p["kind"] == kind, (xyz, p)
        page.mouse.click(*xy)
        n.settle()

    def sidecar(path):
        r = page.request.get(f"{BASE_URL}/api/models/{model_id(page, path)}/sidecar")
        assert r.ok
        return r.json()

    # ---- the controls: mm and 3 at first
    empty_sidecar(page, mold)
    n.load(str(mold))
    assert gui_common.ctl(page, "計測の単位").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "mm"
    assert gui_common.ctl(page, "計測の桁").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "小数 3 桁"
    assert "元の単位" not in hud(), ("a file in mm says nothing more", hud())

    # ---- three measurements: a pin's diameter, a distance, an angle (with its distance 0)
    gui_common.set_mode(page, "計測")
    pin_side, pin_top, plate_top, plate_front = (75, 26, 30), (75, 30, 40), (90, 50, 15), (50, 0, 7.5)
    click(pin_side)
    page.wait_for_function("document.querySelectorAll('#measure-list li[data-kind=diameter]').length === 1", timeout=10000)
    page.keyboard.press("Escape")
    n.settle()
    click(pin_top)
    click(plate_top)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離 25.000')", timeout=10000)
    click(plate_top)
    click(plate_front)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('角度 90.000°')", timeout=10000)
    corner = (0, 0, 15)
    a, b = n.project(corner), n.project((10, 10, 15))
    k = 6 / math.dist(a, b)  # 6 px toward the plate's top: the ray must hit the plate; the corner snaps
    xy = [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]
    v = n.pick(xy)
    assert v and v["kind"] == "vertex" and math.dist(v["point"], corner) < 1e-3, v
    page.mouse.click(*xy)
    n.settle()
    click((75, 30, 40))
    page.wait_for_function(f"document.querySelector('#hud-info').textContent.includes('距離 {SLANT:.3f}')", timeout=10000)
    mm_rows, mm_labels = rows(), labels()
    by_kind = {}
    for k, v, w in mm_rows:
        by_kind.setdefault(k, []).append((v, w))
    assert by_kind["diameter"][0][0] == "⌀8.000 mm", by_kind
    assert sorted(v for v, _ in by_kind["distance"]) == sorted(["0.000 mm", "25.000 mm", f"{SLANT:.3f} mm"]), by_kind
    assert by_kind["angle"][0][0] == "90.000°", by_kind
    assert {"⌀8.000 mm", "25.000 mm", "90.000°"} <= set(mm_labels), mm_labels
    # the saved entries (the save is sent a moment after the list changes)
    for _ in range(50):
        saved = sidecar(mold)
        if len(saved["entries"]) == 5:
            break
        page.wait_for_timeout(200)
    assert len(saved["entries"]) == 5, saved
    values = sorted(e.get("value") for e in saved["entries"] if "value" in e)
    want = sorted([0, 8, 25, 90, SLANT])
    assert len(values) == 5 and all(abs(a - b) < 1e-9 for a, b in zip(values, want)), ("the numbers as the backend gave them", values)
    print("1 mm", mm_rows, mm_labels)

    # ---- インチ, 4 decimals: the screen's numbers in inches
    gui_common.set_mode(page, "なし")
    puts.clear()
    set_shown("インチ", 4)
    in_rows = rows()
    by_kind = {}
    for k, v, w in in_rows:
        by_kind.setdefault(k, []).append((v, w))
    assert by_kind["diameter"][0][0] == f"⌀{8 / IN:.4f} in", by_kind
    assert sorted(v for v, _ in by_kind["distance"]) == sorted([f"{0:.4f} in", f"{25 / IN:.4f} in", f"{SLANT / IN:.4f} in"]), by_kind
    d = [abs(a - b) / IN for a, b in zip(SLANT_AT, (0, 0, 15))]
    slant_where = next(w for v, w in by_kind["distance"] if v == f"{SLANT / IN:.4f} in")
    assert slant_where == f"ΔX\u00a0{d[0]:.4f}　ΔY\u00a0{d[1]:.4f}　ΔZ\u00a0{d[2]:.4f}", slant_where
    assert by_kind["angle"][0][0] == "90.0000°", ("an angle stays in degrees", by_kind)
    assert {f"⌀{8 / IN:.4f} in", f"{25 / IN:.4f} in", "90.0000°"} <= set(labels()), labels()
    # the saved entries are as they were, and none was sent
    page.wait_for_timeout(1500)
    assert puts == [], ("a switch sends no save", puts)
    assert sidecar(mold) == saved, "the sidecar does not change"
    # the copy: as shown
    page.click("#measure-copy-all")
    copied = page.evaluate("navigator.clipboard.readText()")
    lines = [l.split("\t") for l in copied.split("\n")]
    dist = next(l for l in lines if l[0] == "距離" and l[1] != f"{0:.4f}")
    assert dist[1:3] == [f"{25 / IN:.4f}", "in"] and dist[7] == f"{25 / IN:.4f}", dist
    print("2 in", in_rows)

    # the status line of a new measurement, the size beside the cursor
    gui_common.set_mode(page, "計測")
    click(pin_top)
    click(plate_top)
    page.wait_for_function(f"document.querySelector('#hud-info').textContent.includes('距離 {25 / IN:.4f} in')", timeout=10000)
    page.mouse.move(*n.project(pin_side))
    n.settle()
    page.wait_for_function(f"document.querySelector('#cursor-tip')?.textContent.includes('⌀{8 / IN:.4f} in')", timeout=10000)
    print("3", hud(), page.inner_text("#cursor-tip"))
    page.keyboard.press("Escape")
    gui_common.set_mode(page, "なし")

    # the 記録: mm, every digit
    for _ in range(50):
        if len(sidecar(mold)["entries"]) == 6:
            break
        page.wait_for_timeout(200)
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    with page.expect_download() as d:
        page.click("#report-csv")
    text = Path(d.value.path()).read_bytes()[3:].decode("utf-8")
    page.keyboard.press("Escape")
    recs = list(csv.reader(io.StringIO(text, newline="")))
    head = next(i for i, r in enumerate(recs) if r[:2] == ["種類", "値"])
    dists = [r for r in recs[head + 1 :] if r and r[0] == "距離"]
    assert dists and all(r[2] == "mm" for r in dists), dists
    assert any(abs(float(r[1]) - 25) < 1e-9 for r in dists), dists
    print("4 record in mm", [r[1:3] for r in dists])

    # ---- mm with 6 decimals: the saved number's digits (its text has 3)
    set_shown("mm", 6)
    six = [v for k, v, _ in rows() if k == "distance"]
    assert f"{SLANT:.6f} mm" in six, (six, SLANT)

    # ---- back to mm and 3: as before, to the character
    set_shown("mm", 3)
    assert rows()[:5] == mm_rows, (rows(), mm_rows)
    assert {"⌀8.000 mm", "25.000 mm", "90.000°"} <= set(labels()), labels()

    # ---- the choice survives a reload; an old entry (its text only) is shown from its text
    set_shown("インチ", 4)
    put_sidecar(page, old, [{"text": "plate 面#6 ↔ plate 面#1 : 25.400", "labelText": "25.400", "labelPos": [50, 30, 15], "markers": [[50, 30, 15], [50, 30, 0]]}])
    page.reload()
    page.wait_for_selector("#file-input", state="attached")
    n.load(str(old))
    assert gui_common.ctl(page, "計測の単位").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "インチ"
    r = rows()
    assert r == [["distance", f"{1:.4f} in", ""]], r
    assert f"{1:.4f} in" in labels(), labels()
    print("5 reload, old entry", r)

    # ---- a file written in inches: said on the status line, read into mm, named in the 記録
    n.load(str(INCH_BLOCK), wait_text="元の単位")
    assert hud().endswith("25.4 × 50.8 × 12.7 mm（元の単位: in）"), hud()
    title = gui_common.ctl(page, "計測の単位").get_attribute("title")
    assert title and "元のファイルの単位: in" in title, title
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    with page.expect_download() as d:
        page.click("#report-csv")
    rec = dict(r[:2] for r in csv.reader(io.StringIO(Path(d.value.path()).read_bytes()[3:].decode("utf-8"), newline="")) if len(r) >= 2)
    assert rec.get("元のファイルの単位") == "in" and rec.get("単位") == "mm", rec
    print("6 inch file", hud())
print("DISPLAY UNITS E2E OK")
