"""E2E: 距離 in 計測, the distance the second point measures (issue #59 P1 4).

- The operation panel's 距離 (最短 / 中心間 / 最大) is shown in 計測 on a 3D
  model, not in なし nor on a 2D drawing. A first point says what its partner
  will measure (相手をクリックで中心間を測る).
- 中心間: the through hole's top rim (a circle: its centre) and the boss's
  cone (its axis) are 26 apart; the status line, the 3D label and the list's
  row say 中心間. A plane has no centre: said why, nothing listed.
- 最大: the body's front top edge and its right top edge, farthest at their
  far ends. A face has no largest distance: said why, nothing listed.
- 最短 again: the shortest, as before.
- The copy: 中心間 and 最大 in 種類, the bare number in 値. Opening the file
  again brings the rows back as they were.

Oracles (none from the code under test): curved_part.step's make
(testdata/make_step_assembly.py): the body 60 x 40 x 10 from the origin, its 4
vertical edges rounded R5 (so the front top edge runs x 5..55 at y 0, z 10,
the right top edge y 5..35 at x 60, z 10); the through hole r 3 at (12, 20);
the boss, a cone at (38, 20) on the top. Picks are checked to land on the aim
(__cadProject, __cadPick).
"""
import math
import tempfile
from pathlib import Path

import gui_common
from nav_common import TESTDATA, empty_sidecar, nav_session
from engine_net import Net

FAR = math.hypot(55, 35)
DEG = math.pi / 180


def f3(v):
    return f"{v:.3f}"


tmp = tempfile.mkdtemp(prefix="cad_modes_")
curved = Path(tmp) / "curved_part.step"
curved.write_bytes((TESTDATA / "curved_part.step").read_bytes() + b"\n" * 61)

with nav_session() as n:
    page = n.page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    empty_sidecar(page, curved)

    def hud():
        return page.inner_text("#hud-info")

    def rows():
        return page.evaluate(
            """() => [...document.querySelectorAll('#measure-list li')].map(li => ({
                 kind: li.dataset.kind, value: li.querySelector('.m-value')?.textContent ?? null,
                 what: li.querySelector('.m-what')?.textContent ?? null }))"""
        )

    def click(xyz, kind):
        xy = n.project(xyz)
        hit = n.pick(xy)
        assert hit and hit["kind"] == kind, ("the aim must be a", kind, hit, xyz)
        assert math.dist(hit["point"], xyz) < 0.5, ("the click lands off the aim", hit, xyz)
        page.mouse.move(*xy)
        page.mouse.click(*xy)
        n.settle()
        return hit

    def wait_hud(part):
        page.wait_for_function("t => document.querySelector('#hud-info').textContent.includes(t)", arg=part, timeout=10000)

    def distance_shown():
        return gui_common.ctl(page, "距離").is_visible()

    def set_distance(label):
        gui_common.ctl(page, "距離").locator("select").select_option(label=label)
        n.settle()

    n.load(str(curved))
    assert not distance_shown(), "距離 only in 計測"
    gui_common.set_mode(page, "計測")
    assert distance_shown(), "距離 in 計測"
    assert gui_common.ctl(page, "距離").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "最短"

    # ---- 中心間: the hole's rim and the boss's cone
    set_distance("中心間")
    click((12, 23, 10), "edge")  # the hole's top rim, off its seam
    wait_hud("相手をクリックで中心間を測る")
    boss_side = (38, 20 - (6 - 4 * math.tan(2 * DEG)), 14)  # the cone halfway up, toward the viewer
    click(boss_side, "face")
    wait_hud(f"中心間 {f3(26)}")
    r = [x for x in rows() if x["kind"] == "centre"]
    assert len(r) == 1 and r[0]["value"] == f"中心間 {f3(26)} mm" and " ↔ " in r[0]["what"], rows()
    labels = page.evaluate("[...document.querySelectorAll('.dim-label')].map(e => e.textContent)")
    assert f"中心間 {f3(26)} mm" in labels, labels
    print("1 中心間", r[0])

    # a plane has no centre: said, nothing listed
    before = len(rows())
    click((25, 8, 10), "face")  # the top, clear of the boss from the load view
    click(boss_side, "face")
    wait_hud("中心間は測れない")
    assert "1 点目: 平面に中心はない" in hud() and len(rows()) == before, (hud(), rows())
    print("2 no centre:", hud())

    # ---- 最大: the front top edge and the right top edge (one row: no angle with it)
    set_distance("最大")
    n_before = len(rows())
    click((30, 0, 10), "edge")
    wait_hud("相手をクリックで最大を測る")
    click((60, 20, 10), "edge")
    wait_hud(f"最大 {f3(FAR)}")
    r = rows()[n_before:]
    assert [(x["kind"], x["value"]) for x in r] == [("max", f"最大 {f3(FAR)} mm")], r
    # a face has none
    before = len(rows())
    click((30, 0, 10), "edge")
    click((25, 8, 10), "face")
    wait_hud("最大は測れない")
    assert "2 点目: 面の最大の距離は出さない" in hud() and len(rows()) == before, (hud(), rows())
    print("3 最大", r[0])

    # ---- 最短 again: as before, the two edges' right angle with it
    set_distance("最短")
    n_before = len(rows())
    click((30, 0, 10), "edge")
    wait_hud("を選択")
    assert "を測る" not in hud() and "相手をクリックで 2 点目" in hud(), hud()
    click((60, 20, 10), "edge")
    wait_hud("距離 ")
    r = rows()[n_before:]
    assert [x["kind"] for x in r] == ["distance", "angle"] and not r[0]["value"].startswith(("中心間", "最大")), r
    print("4 最短", r)

    # ---- the copy, and the rows kept
    page.locator("#measure-copy-all").click()
    lines = [l.split("\t") for l in page.evaluate("navigator.clipboard.readText()").split("\n")[1:]]
    kinds = [(l[0], l[1]) for l in lines if l[0] in ("中心間", "最大")]
    assert kinds == [("中心間", f3(26)), ("最大", f3(FAR))], lines
    kept = rows()
    n.load(str(curved))
    page.wait_for_function("n => document.querySelectorAll('#measure-list li').length === n", arg=len(kept), timeout=10000)
    assert rows() == kept, ("the rows come back as they were", rows(), kept)
    print("5 copy and kept")

    # ---- a load that fails in 計測 after the old model went leaves the empty
    # screen: no 距離 there (Codex on #66). The mesh fails after the upload; a
    # file that fails at the upload keeps the old model (and 距離 with it)
    Net.of(page).route("**/mesh.bin", lambda r: r.fulfill(status=500, body="no"))
    page.set_input_files("#file-input", str(curved))
    page.wait_for_function("document.querySelector('#load-card')?.textContent.includes('開けなかった')", timeout=30000)
    n.settle()
    Net.of(page).unroute("**/mesh.bin")
    n.errors[:] = [e for e in n.errors if "status of 500" not in e]  # asked for here
    assert gui_common.ctl(page, "モード").locator("select").evaluate("s => s.options[s.selectedIndex].text") == "計測", "still in 計測"
    assert not distance_shown(), "the empty screen has nothing to measure"
    n.load(str(curved))
    assert distance_shown(), "a model again: 距離 is back"
    print("5b a failed load: no 距離 on the empty screen")

    # ---- a drawing: no 距離
    gui_common.set_mode(page, "計測")
    n.load(str(TESTDATA / "plate_drawing.dxf"), wait_text="2D 図面")
    assert not distance_shown(), "a drawing measures its own way"
    print("6 drawing: no 距離")
print("MEASURE MODES E2E OK")
