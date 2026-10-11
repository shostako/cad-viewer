"""E2E: a face's area and loops, an edge's length (issue #59 P1 3).

In 計測, the first point's face or edge says what it measures by itself on the
status line once the backend has told (a face: 面積 and 周長, and how many
inner loops; an edge: 長さ). Enter puts it on the list (a face: a 面積 row and
a 周長 row, the inner loops on the 周長 row's third line; an edge: a 長さ row)
and ends the selection: the next click is a first point again. The rows copy
as 種類 / 値 / 単位 / 対象, one value a row. A second click still measures the
distance (nothing extra is listed); Esc still cancels; a vertex has nothing of
its own (Enter does nothing).

Oracles (none from the code under test): how the models are built
(testdata/make_step_assembly.py). mini_mold: the plate's top 100 x 60 at z 15,
a part of its own (the block and the pins are other parts: no holes in it):
area 6000, loop 320; its top front edge (y 0, z 15) 100 long. curved_part: the
top of the body at z 10, the 60 x 40 outline rounded R5 at its 4 corners,
cut by the through hole (r 3), the dimple (a sphere of r 4 2 above: r sqrt 12)
and the boss's foot (its rounding meets the top at the tube's radius): its
area the outline's less the three circles', its loop the outline's.
"""
import math
import tempfile
from pathlib import Path

import gui_common
from nav_common import TESTDATA, empty_sidecar, nav_session, put_sidecar
from engine_net import Net

DEG = math.pi / 180
BOSS_TUBE = 6 - math.tan(2 * DEG) + 1 / math.cos(2 * DEG)
OUTLINE = 2 * (60 - 10) + 2 * (40 - 10) + 2 * math.pi * 5
OUTLINE_AREA = 60 * 40 - (4 - math.pi) * 25
HOLES = sorted([2 * math.pi * BOSS_TUBE, 2 * math.pi * math.sqrt(12), 2 * math.pi * 3], reverse=True)
TOP_AREA = OUTLINE_AREA - math.pi * (BOSS_TUBE**2 + 12 + 9)


def f3(v):
    return f"{v:.3f}"


tmp = tempfile.mkdtemp(prefix="cad_area_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 43)
curved = Path(tmp) / "curved_part.step"
curved.write_bytes((TESTDATA / "curved_part.step").read_bytes() + b"\n" * 47)

with nav_session() as n:
    page = n.page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    for f in (mold, curved):
        empty_sidecar(page, f)

    def hud():
        return page.inner_text("#hud-info")

    def rows():
        return page.evaluate(
            """() => [...document.querySelectorAll('#measure-list li')].map(li => ({
                 kind: li.dataset.kind, value: li.querySelector('.m-value')?.textContent ?? null,
                 what: li.querySelector('.m-what')?.textContent ?? null,
                 where: li.querySelector('.m-where')?.textContent ?? null }))"""
        )

    def click(xyz, kind):
        xy = n.project(xyz)
        hit = n.pick(xy)
        assert hit and hit["kind"] == kind, ("the aim must be a", kind, hit, xyz)
        # on the aim itself (not on a face in front of it)
        assert math.dist(hit["point"], xyz) < 0.3, ("the click lands off the aim", hit, xyz)
        page.mouse.move(*xy)
        page.mouse.click(*xy)
        n.settle()
        return hit

    def wait_hud(part):
        page.wait_for_function("t => document.querySelector('#hud-info').textContent.includes(t)", arg=part, timeout=10000)

    # ================= mini_mold: the plate's top, its front edge ==================
    n.load(str(mold))
    gui_common.set_mode(page, "計測")
    click((8, 8, 15), "face")
    wait_hud(f"面積 {f3(6000)} mm²・周長 {f3(320)}）")
    assert "Enter で一覧へ" in hud() and "内側の輪郭" not in hud(), hud()
    assert rows() == [], "nothing is listed before Enter"
    page.keyboard.press("Enter")
    n.settle()
    r = rows()
    assert [(x["kind"], x["value"]) for x in r] == [("area", f"{f3(6000)} mm²"), ("perimeter", f"{f3(320)} mm")], r
    assert all(x["what"].startswith("plate 面#") for x in r), r
    assert "1 点目" in hud(), ("Enter ends the selection: the next click is a first point", hud())
    # the 3D labels: the area's with its mm², the loop's with mm
    labels = page.evaluate("[...document.querySelectorAll('.dim-label')].map(e => e.textContent)")
    assert f"{f3(6000)} mm²" in labels and f"周長 {f3(320)} mm" in labels, labels
    print("1 the plate's top", [(x["kind"], x["value"]) for x in r])

    click((50, 0, 15), "edge")
    wait_hud(f"長さ {f3(100)}）")
    page.keyboard.press("Enter")
    n.settle()
    r = rows()
    assert (r[-1]["kind"], r[-1]["value"]) == ("length", f"{f3(100)} mm") and r[-1]["what"].startswith("plate エッジ#"), r
    print("2 the front edge", r[-1])

    # a second click measures the distance as before: nothing of the first's own is listed
    before = len(rows())
    click((8, 8, 15), "face")
    wait_hud("面積")
    click((50, 30, 35), "face")  # the block's top
    page.wait_for_function("n => document.querySelectorAll('#measure-list li').length > n", arg=before, timeout=10000)
    added = rows()[before:]
    assert [x["kind"] for x in added] == ["distance"], added
    # Esc cancels the first point as before; a vertex has nothing of its own
    click((8, 8, 15), "face")
    wait_hud("面積")
    page.keyboard.press("Escape")
    n.settle()
    page.keyboard.press("Enter")
    n.settle()
    assert len(rows()) == before + 1, ("Esc cancelled: Enter adds nothing", rows())
    print("3 distance and Esc as before")

    # Enter and the focus. After the toolbar's 計測 (a mouse click) and a click
    # on the model, Enter lists (the model's click takes the focus to the page).
    # A control the keyboard moved to (Tab) keeps its Enter: plate's これだけ表示
    # in the part tree does its work, nothing is listed, the first point still
    # waits
    before = len(rows())
    page.locator("#toolbar button[data-action='mode-measure']").click()
    click((8, 8, 15), "face")
    wait_hud("面積")
    focus = page.evaluate("() => [document.activeElement?.dataset?.action ?? document.activeElement?.tagName, document.activeElement?.matches(':focus-visible')]")
    page.keyboard.press("Enter")
    n.settle()
    assert len(rows()) == before + 2, ("Enter lists after the clicks", focus, rows()[before:])
    click((8, 8, 15), "face")
    wait_hud("面積")
    for _ in range(150):
        page.keyboard.press("Tab")
        if page.evaluate(
            "() => { const a = document.activeElement; return !!a && a.classList.contains('tree-only') && !!a.closest('.tree-row')?.textContent.includes('plate') }"
        ):
            break
    else:
        raise AssertionError("Tab never reached plate's これだけ表示")
    page.keyboard.press("Enter")
    n.settle()
    assert len(rows()) == before + 2, ("the tree's button had the Enter: nothing listed", rows()[before:])
    shown = page.evaluate(
        "() => Object.fromEntries([...document.querySelectorAll('#tree-panel .tree-row')].map(r => [r.textContent.trim(), r.querySelector('input')?.checked]))"
    )
    assert shown["plate"] and not any(shown[k] for k in ("core_pin1", "core_pin2", "cavity_block")), ("plate alone is shown", shown)
    assert "を選択（面積" in hud(), ("the first point still waits", hud())
    page.locator("#tree-show-all").click()
    page.keyboard.press("Escape")
    n.settle()
    print("3b Enter and the focus", focus)

    # the copy: one value a row
    page.locator("#measure-copy-all").click()
    copied = page.evaluate("navigator.clipboard.readText()").split("\n")
    lines = [l.split("\t") for l in copied[1:]]
    assert lines[0][:3] == ["面積", f3(6000), "mm²"] and lines[0][3].startswith("plate 面#"), lines[0]
    assert lines[1][:3] == ["周長", f3(320), "mm"], lines[1]
    assert lines[2][:3] == ["長さ", f3(100), "mm"], lines[2]
    print("4 copy ok")

    # a late answer for an earlier first point does not land on the next one: the
    # plate's top chosen (its face's answer held), the block's top taken as the
    # second point, the front edge chosen as the next first point, then the
    # held answer let through
    held = []

    def hold_face_info(route):
        if '"face_info"' in (route.request.post_data or ""):
            held.append(route)
        else:
            route.continue_()

    Net.of(page).route("**/api/models/*/measure", hold_face_info)
    before = len(rows())
    click((8, 8, 15), "face")
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "the first point's face answer is held"
    click((50, 30, 35), "face")
    page.wait_for_function("n => document.querySelectorAll('#measure-list li').length > n", arg=before, timeout=10000)
    click((50, 0, 15), "edge")
    wait_hud(f"長さ {f3(100)}）")
    for r_ in held:
        r_.continue_()
    Net.of(page).unroute("**/api/models/*/measure")
    page.wait_for_timeout(1500)
    assert f"長さ {f3(100)}）" in hud() and "面積" not in hud(), ("the late face answer landed on the edge", hud())
    page.keyboard.press("Enter")
    n.settle()
    assert [x["kind"] for x in rows()[before:]] == ["distance", "length"], rows()[before:]
    print("4b a late answer dropped")
    mold_rows = rows()

    # ================= curved_part: the top with its three inner loops =============
    n.load(str(curved))
    gui_common.set_mode(page, "計測")
    click((25, 8, 10), "face")  # clear of the boss from the load view
    wait_hud(f"面積 {f3(TOP_AREA)} mm²・周長 {f3(OUTLINE)}・内側の輪郭 3 個）")
    page.keyboard.press("Enter")
    n.settle()
    r = rows()
    assert [(x["kind"], x["value"]) for x in r] == [("area", f"{f3(TOP_AREA)} mm²"), ("perimeter", f"{f3(OUTLINE)} mm")], r
    assert r[1]["where"] == f"内側の輪郭 3 個: {'・'.join(f3(h) for h in HOLES)}", r[1]
    print("5 the curved top", r)
    curved_rows = r

    # ================= kept: both files open again with their rows ==================
    for f, want in ((mold, mold_rows), (curved, curved_rows)):
        n.load(str(f))
        page.wait_for_function("n => document.querySelectorAll('#measure-list li').length === n", arg=len(want), timeout=10000)
        assert rows() == want, ("the rows come back as they were", f.name, rows(), want)
    print("6 kept in the sidecar")

    # ================= a part name with the words in it (Codex on #62) ===============
    odd = Path(tmp) / "odd_names.step"
    odd.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 51)
    put_sidecar(page, odd, [
        {"text": f"上 面積 プレート 面#1 面積 {f3(6000)} mm²", "labelText": f"{f3(6000)} mm²", "labelPos": [8, 8, 15], "markers": [[8, 8, 15]], "area": 6000},
        {"text": f"上 周長 プレート 面#1 周長 {f3(320)}", "labelText": f"周長 {f3(320)}", "labelPos": [8, 8, 15], "perimeter": 320, "holes": []},
        {"text": f"上 長さ プレート エッジ#2 長さ {f3(100)}", "labelText": f"長さ {f3(100)}", "labelPos": [50, 0, 15], "markers": [[50, 0, 15]], "length": 100},
    ])
    n.load(str(odd))
    page.wait_for_function("() => document.querySelectorAll('#measure-list li').length === 3", timeout=10000)
    got = [(x["kind"], x["what"]) for x in rows()]
    assert got == [("area", "上 面積 プレート 面#1"), ("perimeter", "上 周長 プレート 面#1"), ("length", "上 長さ プレート エッジ#2")], got
    print("7 a part name with the words in it")
print("MEASURE AREA E2E OK")
