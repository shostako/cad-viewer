"""E2E: 問題の一覧 (issue #59 P1 1).

- ribbed_plate.stl, both checks (1.5 mm, レイ法; +Z, 1.0°): 薄肉 the three
  ribs (1.2 mm, one row a rib), 勾配不足 the six runs of vertical walls (the
  plate's sides, each rib's, each boss's), 反対側 the six faces that look
  down (the plate's bottom, the ribs' and the bosses' bottoms on the plate),
  and 判定できない one row: the vertices without a thickness, as many as the
  backend's thickness.bin has (read by this test).
- A row's press: the colours of its kind come on (the heatmap for 薄肉, the
  draft colouring for 勾配不足), the view goes there with the marker on the
  place, and the row is marked.
- The threshold at 1.0 mm with the draft not checked: no 薄肉.
- mini_mold.step: 勾配不足 the ten vertical walls, the largest first, 反対側
  the four faces that look down, 薄肉 none at 1.5 mm. The plate's row button
  shows the plate alone: 4 walls, 1 bottom; with the thickness alone the list
  says nothing was found (a plate of one thickness, every vertex with a value).
- curved_part.step, the draft alone: the boss's cone (2°) is not short at
  1.0° and is at 3.0°.
- An open box (a face missing, written by this test): 判定できない 閉じていない,
  none of its faces listed.
- すべてコピー: the head line and a line a row.
- The card sits in the window, under the operation panel; off, the card goes,
  and the marker it put up.

Oracles (none from the code under test): how the models are built
(testdata/make_testdata.py, make_step_assembly.py; the open box here), the
backend's thickness.bin, __cadProject (the marker on screen).
"""
import json
import math
import struct
import tempfile
from pathlib import Path

import gui_common
from nav_common import BASE_URL, TESTDATA, classic_basis, nav_session
from engine_net import Net
import engine_net

TOL = 1e-3
PINS = ((25, 30), (75, 30))
PIN_R = 4
RIBS = (-25, 0, 25)
RIB_T = 1.2
BOSSES = (-30, 30)  # ribbed_plate's: r 3 at y 18, z 2..12
RIBBED = ((-40, -25, 0), (40, 25, 12))  # ribbed_plate's box
BOSS = (38, 20, 6.0, 8.0, 2.0)  # curved_part's: (x, y, radius at the foot, height, draft °) on the top z 10


def near(a, b, tol=TOL):
    return abs(a - b) <= tol


def mold_wall(p, nrm):
    """(name, area) of the vertical wall of mini_mold the point is on, or None"""
    x, y, z = p
    if abs(nrm[2]) > 1e-6:
        return None
    if 0 <= z <= 15:
        for name, ok, area in (
            ("plate -Y", near(y, 0) and nrm[1] < -0.99, 1500),
            ("plate +Y", near(y, 60) and nrm[1] > 0.99, 1500),
            ("plate -X", near(x, 0) and nrm[0] < -0.99, 900),
            ("plate +X", near(x, 100) and nrm[0] > 0.99, 900),
        ):
            if ok:
                return name, area
    if 15 <= z <= 35:
        for name, ok, area in (
            ("block -Y", near(y, 15) and nrm[1] < -0.99, 800),
            ("block +Y", near(y, 45) and nrm[1] > 0.99, 800),
            ("block -X", near(x, 30) and nrm[0] < -0.99, 600),
            ("block +X", near(x, 70) and nrm[0] > 0.99, 600),
        ):
            if ok and 30 - TOL <= x <= 70 + TOL and 15 - TOL <= y <= 45 + TOL:
                return name, area
    if 15 <= z <= 40:
        for i, (cx, cy) in enumerate(PINS):
            r = math.hypot(x - cx, y - cy)
            if 0.97 * PIN_R <= r <= PIN_R + TOL:
                return f"pin {i}", 2 * math.pi * PIN_R * 25
    return None


def mold_down(p, nrm):
    """the face of mini_mold that looks down the point is on, or None"""
    if nrm[2] > -0.999:
        return None
    x, y, z = p
    if near(z, 0):
        return "plate bottom"
    if near(z, 15):
        if 30 <= x <= 70 and 15 <= y <= 45:
            return "block bottom"
        for i, (cx, cy) in enumerate(PINS):
            if math.hypot(x - cx, y - cy) <= PIN_R + TOL:
                return f"pin {i} bottom"
    return None


def ribbed_wall(p, nrm):
    """the run of vertical walls of ribbed_plate the point is on, or None"""
    x, y, z = p
    if abs(nrm[2]) > 1e-6:
        return None
    if -TOL <= z <= 2 + TOL and (near(abs(x), 40) or near(abs(y), 25)):
        return "plate"
    for i, rx in enumerate(RIBS):
        if 2 - TOL <= z <= 10 + TOL and abs(x - rx) <= RIB_T / 2 + TOL and abs(y) <= 23 + TOL:
            return f"rib {i}"
    for i, bx in enumerate(BOSSES):
        if 2 - TOL <= z <= 12 + TOL and math.hypot(x - bx, y - 18) <= 3 + TOL:
            return f"boss {i}"
    return None


def ribbed_down(p, nrm):
    """the face of ribbed_plate that looks down the point is on, or None"""
    if nrm[2] > -0.999:
        return None
    x, y, z = p
    if near(z, 0):
        return "plate bottom"
    if near(z, 2):
        for i, rx in enumerate(RIBS):
            if abs(x - rx) <= RIB_T / 2 + TOL and abs(y) <= 23 + TOL:
                return f"rib {i} bottom"
        for i, bx in enumerate(BOSSES):
            if math.hypot(x - bx, y - 18) <= 3 + TOL:
                return f"boss {i} bottom"
    return None


def on_boss_cone(p):
    """on curved_part's boss cone (above its foot's rounding)"""
    bx, by, r0, h, draft = BOSS
    x, y, z = p
    if not 11 <= z <= 10 + h + TOL:
        return False
    want = r0 - (z - 10) * math.tan(math.radians(draft))
    return abs(math.hypot(x - bx, y - by) - want) <= 0.1


def open_box_stl(path):
    """a 20 x 20 x 10 box without its top: 5 faces, 10 triangles (ASCII STL)"""
    v = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0), (0, 0, 10), (20, 0, 10), (20, 20, 10), (0, 20, 10)]
    quads = [(0, 3, 2, 1), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]  # bottom and 4 sides, outward
    lines = ["solid open_box"]
    for a, b, c, d in quads:
        for t in ((a, b, c), (a, c, d)):
            lines += ["facet normal 0 0 0", "outer loop", *[f"vertex {v[i][0]} {v[i][1]} {v[i][2]}" for i in t], "endloop", "endfacet"]
    lines.append("endsolid open_box")
    Path(path).write_text("\n".join(lines) + "\n")


def no_value_count(page, path):
    """(vertices without a thickness, vertices) of the one part of a file, from the backend (レイ法)"""
    r = engine_net.upload(page, path)
    assert r.ok, r.status
    blob = engine_net.api(page, "GET", f"/api/models/{r.json()['id']}/thickness.bin?method=ray", timeout=600000).body()
    (hl,) = struct.unpack_from("<I", blob, 0)
    head = json.loads(blob[4 : 4 + hl])
    bufs = head["buffers"].items() if isinstance(head["buffers"], dict) else [(b["name"], b) for b in head["buffers"]]
    (name, d), = list(bufs)
    vals = struct.unpack_from(f"<{d['count']}f", blob, 4 + hl + d["offset"])
    return sum(1 for x in vals if not x > 0), len(vals)


tmp = tempfile.mkdtemp(prefix="cad_check_")
open_box = Path(tmp) / "open\tbox.stl"  # a tab in its name: the copy must keep its cells
open_box_stl(open_box)

with nav_session() as n:
    page = n.page
    # the checks at the app's own 1.5 mm and 1.0° (判定の基準 手で決める), as written: the default is the material's
    classic_basis(page)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    n.stub_sidecar()

    def check():
        return page.evaluate("window.__cadCheck()")

    def kinds(c):
        return [r["kind"] for r in c["rows"]]

    def wait_list(pred="true"):
        """the list once made (and pred(c) holds on it)"""
        page.wait_for_function(f"(() => {{ const c = window.__cadCheck(); return !!c && ({pred}) }})()", timeout=60000)
        n.settle()
        return check()

    def set_box(name, on):
        box = gui_common.ctl(page, name).locator("input")
        box.check() if on else box.uncheck()

    def set_number(name, v):
        inp = gui_common.ctl(page, name).locator("input").last
        inp.fill(str(v))
        inp.press("Enter")

    def marker():
        return page.evaluate(
            "(() => { const m = document.querySelector('.spot-marker'); if (!m) return null;"
            " const r = m.getBoundingClientRect(); return { xy: [r.left, r.top], text: m.textContent } })()"
        )

    def press_row(kind, i=0):
        page.locator(f"#check-panel .check-list li[data-kind='{kind}'] .check-go").nth(i).click()
        n.settle()
        page.wait_for_timeout(450)  # the move takes 0.3 s
        n.settle()

    def shown(sel):
        return page.evaluate(f"(() => {{ const e = document.querySelector({sel!r}); return !!e && !e.classList.contains('hidden') }})()")

    def folder_shown():
        return gui_common.folder_title(page, "問題の一覧").is_visible()

    # the empty screen: no folder for a list there is nothing to make from
    assert not folder_shown(), "no 問題の一覧 on the empty screen"

    # ================= ribbed_plate: all three kinds, and what has no thickness =======
    n.load(TESTDATA / "ribbed_plate.stl", props="live", box=RIBBED)
    assert folder_shown()
    gui_common.open_folder(page, "問題の一覧")
    # 厚肉 is test_thick_spots.py's: this list is the wall's and the draft's, as written
    set_box("厚肉を調べる", False)
    set_box("一覧を出す", True)
    c = wait_list()
    thin = [r for r in c["rows"] if r["kind"] == "thin"]
    assert len(thin) == 3 and all(abs(r["value"] - RIB_T) < 0.01 for r in thin), ("the three ribs, 1.2 mm", thin)
    ribs = sorted(ribbed_wall(r["at"], [0, 0, 0]) or "?" for r in thin)
    assert ribs == ["rib 0", "rib 1", "rib 2"], ("one row a rib", ribs, [r["at"] for r in thin])
    short = [r for r in c["rows"] if r["kind"] == "short"]
    walls = sorted(ribbed_wall(r["at"], r["normal"]) or "?" for r in short)
    assert walls == sorted(["plate", "rib 0", "rib 1", "rib 2", "boss 0", "boss 1"]), ("six runs of vertical walls", walls)
    assert all(abs(r["value"]) < 0.05 for r in short), short
    downs = sorted(ribbed_down(r["at"], r["normal"]) or "?" for r in c["rows"] if r["kind"] == "opposite")
    assert downs == sorted(["plate bottom", "rib 0 bottom", "rib 1 bottom", "rib 2 bottom", "boss 0 bottom", "boss 1 bottom"]), downs
    assert kinds(c) == ["thin"] * 3 + ["short"] * 6 + ["opposite"] * 6, ("thin, then short, then opposite", kinds(c))
    none, verts = no_value_count(page, TESTDATA / "ribbed_plate.stl")
    assert none > 0 and c["undecided"] == [{"partId": 0, "why": f"肉厚の値が出ない頂点 {none} / {verts} 個"}], (c["undecided"], none, verts)
    counts = page.inner_text("#check-panel .check-counts")
    assert counts == "薄肉 3・勾配不足 6・反対側 6・判定できない 1", counts
    cond = page.inner_text("#check-panel .check-conditions")
    assert cond == "肉厚 1.5 mm 未満（レイ法）・型開き +Z・勾配 1.0° 未満", cond
    print("1 ribbed_plate", counts, f"({none} of {verts} without a thickness)")

    # the card: in the window, under the operation panel
    card = page.evaluate("(() => { const r = document.querySelector('#check-panel').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
    gui = page.evaluate("(() => { const r = document.querySelector('.lil-gui.lil-root').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
    vw, vh = page.evaluate("[innerWidth, innerHeight]")
    assert 0 <= card[0] and card[2] <= vw and 0 <= card[1] and card[3] <= vh, ("the card in the window", card, vw, vh)
    assert card[1] >= gui[3] - 0.5, ("the card under the operation panel", card, gui)
    # 全体表示 with the card up: framed in the area clear of every panel, the card among them
    # (here the column's other panels set the same side: the card alone does not move the fit)
    n.fit()
    n.fill_check(*n.box, "fit beside the card")

    # ---- a row's press: its colours, its place
    press_row("thin", 1)
    c = check()
    row = c["current"]
    assert row and row["kind"] == "thin" and row["at"] == thin[1]["at"], ("the row pressed is marked", row, thin[1])
    assert shown("#thickness-legend") and not shown("#draft-legend"), "薄肉: the heatmap comes on"
    m = marker()
    assert m and m["text"] == "1.20 mm", m
    assert math.dist(m["xy"], n.project(row["at"])) <= 3, ("the marker on the place", m, n.project(row["at"]))
    assert page.locator("#check-panel .check-list li.current").count() == 1
    press_row("short", 0)
    row = check()["current"]
    assert row["kind"] == "short" and shown("#draft-legend") and not shown("#thickness-legend"), "勾配不足: the draft colours come on"
    m = marker()
    assert m and m["text"] == "勾配 0.0°" and math.dist(m["xy"], n.project(row["at"])) <= 3, (m, row)
    print("2 a row goes to its place")

    # ---- the threshold at 1.0 mm, the draft not checked: no 薄肉 (and the marker goes)
    set_box("抜き勾配を調べる", False)
    gui_common.open_folder(page, "肉厚")
    set_number("閾値 (mm)", 1.0)
    c = wait_list("c.conditions.thin && c.conditions.thin.threshold === 1 && !c.conditions.draft")
    assert c["rows"] == [] and len(c["undecided"]) == 1, c
    assert marker() is None, "a new list takes the marker away"
    assert page.inner_text("#check-panel .check-counts") == "薄肉 0・判定できない 1"
    set_number("閾値 (mm)", 1.5)
    set_box("抜き勾配を調べる", True)
    print("3 at 1.0 mm none")

    # ================= mini_mold: the walls and the bottoms; the plate alone =========
    n.load(n.paths["step"], props="live")
    assert not shown("#check-panel"), "a new model takes the list away"
    set_box("一覧を出す", True)
    c = wait_list()
    short = [r for r in c["rows"] if r["kind"] == "short"]
    walls = [mold_wall(r["at"], r["normal"]) for r in short]
    assert all(walls) and len({w[0] for w in walls}) == 10, ("the ten vertical walls", walls)
    assert [w[1] for w in walls] == sorted((w[1] for w in walls), reverse=True), ("the largest first", walls)
    assert all(abs(r["area"] - w[1]) < 1.0 for r, w in zip(short, walls) if not w[0].startswith("pin")), ("a wall's area", short)
    downs = sorted(mold_down(r["at"], r["normal"]) or "?" for r in c["rows"] if r["kind"] == "opposite")
    assert downs == sorted(["plate bottom", "block bottom", "pin 0 bottom", "pin 1 bottom"]), downs
    assert not [r for r in c["rows"] if r["kind"] == "thin"], "nothing under 1.5 mm"
    print("4 mini_mold", page.inner_text("#check-panel .check-counts"))
    # the plate's row button: the plate alone
    plate_row = page.locator("#check-panel .check-list li[data-kind='short']").filter(has_text="plate").first
    plate_row.locator(".check-only").click()
    c = wait_list("c.rows.length === 5")
    assert sorted(mold_wall(r["at"], r["normal"])[0] for r in c["rows"] if r["kind"] == "short") == ["plate +X", "plate +Y", "plate -X", "plate -Y"], c["rows"]
    set_box("抜き勾配を調べる", False)
    c = wait_list("!c.conditions.draft")
    assert c["rows"] == [] and c["undecided"] == [], ("a plate of one thickness: nothing", c)
    assert page.inner_text("#check-panel .check-none") == "この条件では見つからなかった"
    set_box("抜き勾配を調べる", True)
    page.locator("#tree-show-all").click()
    print("5 the plate alone: nothing found")

    # ---- すべてコピー, the clipboard API refused: the measure list's stand-in copies it
    c = wait_list("c.rows.length === 14")
    page.evaluate(
        "async () => { await navigator.clipboard.writeText('before');"
        " window.__write = navigator.clipboard.writeText; navigator.clipboard.writeText = () => Promise.reject(new DOMException('no', 'NotAllowedError')) }"
    )
    page.locator("#check-panel .check-copy-all").click()
    page.wait_for_function("document.querySelector('#check-panel .check-copy-all').classList.contains('done')", timeout=5000)
    page.evaluate("() => { navigator.clipboard.writeText = window.__write }")
    lines = page.evaluate("navigator.clipboard.readText()").split("\n")
    assert lines[0] == "種類\t値\t単位\t部品\tX\tY\tZ\t面積 (mm²)\t条件", lines[0]
    assert len(lines) == 1 + len(c["rows"]) + len(c["undecided"]), (len(lines), c)
    first = lines[1].split("\t")
    r0 = c["rows"][0]
    assert first[0] == "勾配不足" and float(first[1]) == round(r0["value"], 2) and first[2:4] == ["°", "plate"], first
    assert [float(v) for v in first[4:7]] == [round(v, 3) for v in r0["at"]], (first, r0["at"])
    assert abs(float(first[7]) - r0["area"]) < 0.05 and first[8] == "肉厚 1.5 mm 未満（レイ法）・型開き +Z・勾配 1.0° 未満", first
    print("6 copy ok")

    # ---- off: the card goes, and the marker it put up
    press_row("opposite", 0)
    assert marker() is not None
    set_box("一覧を出す", False)
    n.settle()
    assert not shown("#check-panel") and marker() is None, "off: the card and its marker go"
    print("7 off ok")

    # ================= curved_part: the boss's 2° cone at 1.0° and at 3.0° ===========
    n.load(TESTDATA / "curved_part.step", props="live")
    set_box("一覧を出す", True)
    set_box("肉厚を調べる", False)
    c = wait_list("!c.conditions.thin")
    assert not [r for r in c["rows"] if r["kind"] == "short" and on_boss_cone(r["at"])], ("2° is enough at 1.0°", c["rows"])
    # the body's faces at y 0 and x 0: a coordinate that rounds to 0 has no sign
    wheres = page.locator("#check-panel .check-where").all_inner_texts()
    assert any("0.0" in w for w in wheres) and not any("-0.0" in w for w in wheres), wheres
    gui_common.open_folder(page, "抜き勾配")
    set_number("必要な勾配 (°)", 3)
    c = wait_list("c.conditions.draft.required === 3")
    assert [r for r in c["rows"] if r["kind"] == "short" and on_boss_cone(r["at"])], ("2° is short at 3.0°", c["rows"])
    set_number("必要な勾配 (°)", 1)
    set_box("肉厚を調べる", True)
    print("8 the boss's cone")

    # ================= an open box: not judged ========================================
    n.load(open_box, props="live")
    set_box("一覧を出す", True)
    c = wait_list()
    assert c["rows"] == [] and c["undecided"] == [{"partId": 0, "why": "閉じていない"}], c
    assert page.inner_text("#check-panel .check-counts") == "薄肉 0・勾配不足 0・反対側 0・判定できない 1"
    # its name has a tab: the copy keeps nine cells a line
    page.locator("#check-panel .check-copy-all").click()
    page.wait_for_timeout(300)
    lines = [l.split("\t") for l in page.evaluate("navigator.clipboard.readText()").split("\n")]
    assert len(lines) == 2 and all(len(l) == 9 for l in lines) and "box" in lines[1][3], lines
    print("9 an open box: 閉じていない", lines[1][3])

    # ================= /properties fails: said, not waited for ==========================
    Net.of(page).route("**/properties", lambda r: r.fulfill(status=500, body="no"))
    n.load(TESTDATA / "ribbed_plate.stl", props="unheld", box=RIBBED)
    set_box("一覧を出す", True)
    page.wait_for_function(
        "document.querySelector('#check-panel')?.textContent.includes('部品が閉じているかを調べられなかった')", timeout=30000
    )
    Net.of(page).unroute("**/properties")
    # the 500 asked for here logs "Failed to load resource": expected here only
    n.errors[:] = [e for e in n.errors if "status of 500" not in e]
    print("10 no properties: said")

    # ================= a drawing: no folder ==============================================
    n.load(TESTDATA / "plate_drawing.dxf", wait_text="2D 図面")
    assert not folder_shown() and not shown("#check-panel"), "a drawing has no 問題の一覧"
    print("11 drawing: no folder")
print("CHECK LIST E2E OK")
