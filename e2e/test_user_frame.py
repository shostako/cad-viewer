"""E2E: 座標系 (issue #59 P1 7): an origin and axes of one's own.

- 座標系 > 原点と軸を選ぶ asks three clicks, whatever the mode: the origin (a
  vertex), Z (a plane's normal), X (a plane's normal, made square to Z). A
  click that cannot be the step's (a plane as the origin, a cylinder along Z
  as X) says why and asks again. Esc gives the choice up.
- With the frame: the status line says it; its mark (X, Y, Z from the origin)
  is drawn; a vertex's point beside the cursor, a slanted distance's ΔX ΔY ΔZ
  and a circle's centre in the list are in the frame. Lengths do not change.
- What is saved does not change: no save is sent, the sidecar reads the
  same, the 記録's numbers are the model's own (it names the frame).
- 元の座標系に戻す: the model's own again, the mark goes. Another model
  starts in its own; a mesh has no B-rep to take a frame from.

Oracles (none from the code under test): mini_mold.step's make
(testdata/make_step_assembly.py): the plate 0..100 x 0..60 x 0..15, the second
pin of radius 4 at (75, 30), z 15..40. The frame: the origin at the plate's
corner (100, 60, 15), Z the top's normal (0, 0, 1), X the front's (0, -1, 0),
so Y = Z × X = (1, 0, 0) and a point (x, y, z) reads (60 − y, x − 100, z − 15).
Screen places from __cadProject; picks from __cadPick.
"""
import csv
import io
import math
import tempfile
from pathlib import Path

import gui_common
from nav_common import BASE_URL, TESTDATA, empty_sidecar, nav_session

tmp = tempfile.mkdtemp(prefix="cad_frame_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 83)
ORIGIN = (100, 60, 15)


def in_frame(p):
    return (60 - p[1], p[0] - 100, p[2] - 15)


def pt(p):
    return "(" + ", ".join(f"{v:.3f}" for v in p) + ")"


# the plate's corner to the second pin's top: the rim's point toward the corner
_C = math.hypot(75, 30)
RIM = (75 - 4 * 75 / _C, 30 - 4 * 30 / _C, 40)
DELTA = [b - a for a, b in zip((0, 0, 15), RIM)]  # the model's own ΔX ΔY ΔZ


def model_id(page, path):
    r = page.request.post(
        f"{BASE_URL}/api/models",
        multipart={"file": {"name": Path(path).name, "mimeType": "application/octet-stream", "buffer": Path(path).read_bytes()}},
        timeout=120000,
    )
    assert r.ok
    return r.json()["id"]


with nav_session() as n:
    page = n.page
    puts = []
    page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" and r.url.endswith("/sidecar") else None)

    def hud():
        return page.inner_text("#hud-info")

    def choose():
        gui_common.ctl(page, "原点と軸を選ぶ").locator("button").click()
        n.settle()

    def near(xyz, toward, px=6):
        a, b = n.project(xyz), n.project(toward)
        k = px / math.dist(a, b)
        return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]

    def click_at(xy, kind):
        p = n.pick(xy)
        assert p and p["kind"] == kind, (xy, p)
        page.mouse.click(*xy)
        n.settle()
        return p

    def wait_hud(text, timeout=10000):
        page.wait_for_function(f"document.querySelector('#hud-info').textContent.includes({text!r})", timeout=timeout)
        return hud()

    def tip_at(xy):
        page.mouse.move(*xy)
        n.settle()
        page.wait_for_timeout(250)
        return page.inner_text("#cursor-tip")

    def axis_labels():
        return page.evaluate(
            "[...document.querySelectorAll('.frame-axis')].map(e => { const r = e.getBoundingClientRect(); return [e.textContent, r.left + r.width / 2, r.top + r.height / 2] })"
        )

    empty_sidecar(page, mold)
    n.load(str(mold))
    gui_common.open_folder(page, "座標系")
    assert gui_common.ctl(page, "今の座標系").locator("input").input_value() == "元の座標系"
    corner_xy = near(ORIGIN, (50, 30, 15))
    top_xy = n.project((90, 10, 15))
    front_xy = n.project((85, 0, 7))
    pin_xy = n.project((75, 26, 30))

    # ---- Esc gives the choice up
    choose()
    assert hud().startswith("座標系: 原点をクリック"), hud()
    page.keyboard.press("Escape")
    n.settle()
    assert not hud().startswith("座標系"), hud()
    click_at(top_xy, "face")  # in なし, a click does nothing now
    assert not hud().startswith("座標系"), hud()

    # ---- three clicks (in なし: the mode does not matter), with the wrong kinds said
    choose()
    click_at(top_xy, "face")
    assert wait_hud("中心はない").startswith("座標系: この面に中心はない — 原点をクリック"), hud()
    v = click_at(corner_xy, "vertex")
    assert math.dist(v["point"], ORIGIN) < 1e-3, v
    wait_hud("Z 軸をクリック")
    click_at(top_xy, "face")
    wait_hud("X 軸をクリック")
    click_at(pin_xy, "face")  # the pin's side: its axis is Z's
    assert wait_hud("平行").startswith("座標系: Z 軸と平行で X 軸にならない — X 軸をクリック"), hud()
    click_at(front_xy, "face")
    done = wait_hud("座標系を決めた")
    assert "原点 (100.000, 60.000, 15.000)・X (0.000000, -1.000000, 0.000000)・Y (1.000000, 0.000000, 0.000000)・Z (0.000000, 0.000000, 1.000000)" in done, done
    assert gui_common.ctl(page, "今の座標系").locator("input").input_value() == "原点 (100.000, 60.000, 15.000)"
    print("1 frame", done)

    # making the frame: X square to Z (its part along Z dropped), the axes of unit length, Y = Z × X;
    # an X along Z makes none (hand-worked: Z (0, 0, 2) → (0, 0, 1); X (1, 0, 1) → (1, 0, 0); Y (0, 1, 0))
    made = page.evaluate(
        "async () => { const m = await import('/src/frame.ts');"
        " return [m.makeFrame([1, 2, 3], [0, 0, 2], [1, 0, 1]), m.makeFrame([0, 0, 0], [0, 0, 1], [0, 0, -3])] }"
    )
    f = made[0]
    assert f["origin"] == [1, 2, 3] and made[1] is None, made
    for got, want in ((f["x"], (1, 0, 0)), (f["y"], (0, 1, 0)), (f["z"], (0, 0, 1))):
        assert math.dist(got, want) < 1e-12, (got, want)

    # its mark: X, Y, Z at a tenth of the model's size from the origin
    size = 0.1 * math.dist((0, 0, 0), (100, 60, 40))
    labels = {name: (x, y) for name, x, y in axis_labels()}
    for name, d in (("X", (0, -1, 0)), ("Y", (1, 0, 0)), ("Z", (0, 0, 1))):
        want = n.project([o + size * c for o, c in zip(ORIGIN, d)])
        assert name in labels and math.dist(labels[name], want) < 4, (name, labels.get(name), want)

    # ---- in the frame: a vertex beside the cursor, a slanted distance's Δ, a circle's centre
    gui_common.set_mode(page, "計測")
    corner0 = near((0, 0, 15), (10, 10, 15))
    tip = tip_at(corner0)
    assert tip.endswith(pt(in_frame((0, 0, 15)))), ("the corner in the frame", tip)
    click_at(corner0, "vertex")
    click_at(n.project((75, 30, 40)), "face")
    wait_hud(f"距離 {math.dist((0, 0, 15), RIM):.3f}")  # a length is the same in any frame
    rim_xy = n.project((75, 26, 40))
    rim = n.pick(rim_xy)
    assert rim and rim["kind"] == "edge", rim
    page.mouse.click(*rim_xy)
    n.settle()
    page.wait_for_function("document.querySelectorAll('#measure-list li[data-kind=diameter]').length === 1", timeout=10000)
    page.keyboard.press("Escape")
    n.settle()
    rows = page.evaluate("[...document.querySelectorAll('#measure-list li')].map(li => [li.dataset.kind, li.querySelector('.m-where')?.textContent ?? ''])")
    where = dict(rows)
    d = [abs(DELTA[1]), abs(DELTA[0]), abs(DELTA[2])]  # along X = −y, Y = x, Z = z
    assert where["distance"] == f"ΔX {d[0]:.3f}　ΔY {d[1]:.3f}　ΔZ {d[2]:.3f}", (where, d)
    assert where["diameter"] == f"中心 {pt(in_frame((75, 30, 40)))}", where
    print("2 in the frame", tip, rows)

    # ---- nothing saved changes; the 記録 keeps the model's own
    page.wait_for_timeout(1500)
    saved = page.request.get(f"{BASE_URL}/api/models/{model_id(page, mold)}/sidecar").json()
    dist = next(e for e in saved["entries"] if "delta" in e)
    assert all(abs(a - b) < 1e-9 for a, b in zip(dist["delta"], DELTA)), ("the saved Δ: the model's own", dist["delta"], DELTA)
    gui_common.set_mode(page, "なし")
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    with page.expect_download() as dl:
        page.click("#report-csv")
    page.keyboard.press("Escape")
    recs = list(csv.reader(io.StringIO(Path(dl.value.path()).read_bytes()[3:].decode("utf-8"), newline="")))
    meta = dict(r[:2] for r in recs if len(r) >= 2)
    assert meta["座標系"].startswith("原点 (100.000, 60.000, 15.000)・X (0.000000, -1.000000, 0.000000)") and meta["座標系"].endswith("（記録の値は元の座標系のまま）"), meta["座標系"]
    head = next(i for i, r in enumerate(recs) if r[:2] == ["種類", "値"])
    rec = next(r for r in recs[head + 1 :] if r and r[0] == "距離" and float(r[1]) > 1)
    assert all(abs(float(rec[5 + k]) - abs(DELTA[k])) < 1e-9 for k in range(3)), ("the 記録's Δ: the model's own", rec, DELTA)
    puts_with_frame = list(puts)

    # ---- back to the model's own
    gui_common.ctl(page, "元の座標系に戻す").locator("button").click()
    n.settle()
    assert hud() == "元の座標系に戻した", hud()
    assert axis_labels() == [], "the mark goes"
    rows = dict(page.evaluate("[...document.querySelectorAll('#measure-list li')].map(li => [li.dataset.kind, li.querySelector('.m-where')?.textContent ?? ''])"))
    assert rows["distance"] == f"ΔX {abs(DELTA[0]):.3f}　ΔY {abs(DELTA[1]):.3f}　ΔZ {abs(DELTA[2]):.3f}", rows
    assert rows["diameter"] == "中心 (75.000, 30.000, 40.000)", rows
    gui_common.set_mode(page, "計測")
    assert tip_at(corner0).endswith("(0.000, 0.000, 15.000)"), page.inner_text("#cursor-tip")
    gui_common.set_mode(page, "なし")
    page.wait_for_timeout(1500)
    # the frame's choices sent no save (the saves are the measurements')
    assert len(puts) == len(puts_with_frame), ("a frame sends no save", puts, puts_with_frame)
    print("3 back", rows)

    # ---- another model starts in its own; a mesh has none to take
    choose()
    click_at(corner_xy, "vertex")
    click_at(top_xy, "face")
    click_at(front_xy, "face")
    wait_hud("座標系を決めた")
    n.load(TESTDATA / "ribbed_plate.stl")
    assert axis_labels() == [] and gui_common.ctl(page, "今の座標系").locator("input").input_value() == "元の座標系"
    choose()
    assert hud().startswith("座標系は STEP・IGES のモデルだけ"), hud()
    print("4 another model", hud())
print("USER FRAME E2E OK")
