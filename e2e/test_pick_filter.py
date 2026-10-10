"""E2E: 選択, what a click may take in 計測 / 注記 (issue #59 P1 8).

- The operation panel's 選択 (すべて / 面 / 稜線 / 頂点 / 部品) shows in 計測
  and 注記 on a 3D model, not in なし. The status line's hint names it
  (「稜線だけ」).
- Near the plate's top front edge (4 px off it, on screen): すべて takes the
  edge, 面 the face. 15 px off: すべて the face, 稜線 the edge; 40 px off,
  稜線 nothing. 18 px from the plate's corner: すべて no vertex, 頂点 the
  corner.
- 部品: the pin under the cursor is taken whole: the highlight and its name
  (「core_pin · 全体」) before the click, the status line after it; the second
  pin and the cavity block are 1 apart (a clearance between parts). A
  curve-only part is taken by its lines (loose_faces_box.igs: the three axis
  lines, 曲線（3 本）): lit 水色 under the cursor; from all three, the box's far
  corner is nearest the Z axis.

Oracles (none from the code under test): mini_mold.step's make
(testdata/make_step_assembly.py): the plate 0..100 x 0..60 x 0..15, core pins
of radius 4 at (25, 30) and (75, 30) z 15..40, the cavity block
30..70 x 15..45 x 15..35. loose_faces_box.igs's make
(testdata/make_iges_loose.py): the box 0..10 x 0..20 x 0..30 and the lines
x, y, z from -50 to 50 through the origin. Distances on screen from
__cadProject; what a click takes from __cadPick (the same pick as the click and
the hover).
"""
import io
import math
import tempfile
from pathlib import Path

from PIL import Image

import gui_common
from nav_common import LOOSE_IGES, TESTDATA, empty_sidecar, nav_session

tmp = tempfile.mkdtemp(prefix="cad_filter_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 63)
loose = Path(tmp) / "loose_faces_box.igs"
loose.write_bytes(LOOSE_IGES.read_bytes() + b"\n" * 67)

with nav_session() as n:
    page = n.page
    empty_sidecar(page, mold)

    def hud():
        return page.inner_text("#hud-info")

    def filter_ctl():
        return gui_common.ctl(page, "選択")

    def set_filter(label):
        filter_ctl().locator("select").select_option(label=label)
        n.settle()

    def toward(a, b, px):
        """the screen point px from a's projection toward b's"""
        pa, pb = n.project(a), n.project(b)
        d = math.dist(pa, pb)
        return [pa[0] + (pb[0] - pa[0]) * px / d, pa[1] + (pb[1] - pa[1]) * px / d]

    def pick(xy):
        return n.pick(xy)

    LIGHT_BLUE = (0x55, 0xD6, 0xFF)  # the preselection's 水色 (preselect.ts PRESELECT_COLOR)

    def blueness(xyz):
        """how near the pixel at the point is to 水色 (1) rather than to the plain pin (0), a 5 x 5 mean"""
        x, y = n.project(xyz)
        img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
        px = [img.getpixel((int(x) + dx, int(y) + dy)) for dx in range(-2, 3) for dy in range(-2, 3)]
        mean = [sum(c[i] for c in px) / len(px) for i in range(3)]
        return mean

    n.load(str(mold))
    assert not filter_ctl().is_visible(), "選択 only in 計測 / 注記"
    gui_common.set_mode(page, "注記")
    assert filter_ctl().is_visible()
    gui_common.set_mode(page, "計測")
    assert filter_ctl().is_visible()
    assert filter_ctl().locator("select").evaluate("s => s.options[s.selectedIndex].text") == "すべて"

    # ---- near an edge: すべて snaps, 面 does not; farther, 稜線 still takes it, then nothing
    edge, inside = (15, 0, 15), (15, 10, 15)  # the plate's top front edge, its top behind it (clear of the pins)
    p4, p15, p40 = toward(edge, inside, 4), toward(edge, inside, 15), toward(edge, inside, 40)
    assert pick(p4)["kind"] == "edge" and pick(p15)["kind"] == "face", (pick(p4), pick(p15))
    set_filter("面")
    assert pick(p4)["kind"] == "face", pick(p4)
    set_filter("稜線")
    e15 = pick(p15)
    assert e15 and e15["kind"] == "edge" and abs(e15["point"][1]) < 1e-3 and abs(e15["point"][2] - 15) < 1e-3, e15
    assert pick(p40) is None, pick(p40)
    wait = "document.querySelector('#hud-info').textContent.includes('稜線だけ')"
    page.wait_for_function(wait, timeout=5000)
    assert hud() == "計測: クリックで 1 点目（稜線だけ・Esc でやめる）", hud()
    print("1 edges", e15)

    # the hover shows what the click takes
    page.mouse.move(*p15)
    n.settle()
    page.wait_for_timeout(200)
    tip = page.inner_text("#cursor-tip")
    page.mouse.click(*p15)
    n.settle()
    assert hud().startswith(tip.split(" ⌀")[0].replace(" · ", " ") + " を選択"), (tip, hud())
    page.keyboard.press("Escape")
    n.settle()

    # ---- near a corner: 頂点 takes it from farther
    corner = (0, 0, 15)
    p18 = toward(corner, (10, 10, 15), 18)
    set_filter("すべて")
    assert pick(p18)["kind"] != "vertex", pick(p18)
    set_filter("頂点")
    v = pick(p18)
    assert v and v["kind"] == "vertex" and math.dist(v["point"], corner) < 1e-3, v
    assert pick(p15) is None, ("頂点 alone: none near the middle of an edge", pick(p15))
    print("2 vertex", v)

    # ---- 部品: a whole part, and the clearance between two
    set_filter("部品")
    pin2_front = (75, 26, 30)  # the second pin, toward the viewer
    xy = n.project(pin2_front)
    p = pick(xy)
    assert p and p["kind"] == "part", p
    # the highlight is the whole pin: on its side under the cursor, its top too
    # (with 面 only the side is tinted: the top keeps the pin's own colour)
    pin2_top, pin2_low = (75, 30, 40), (75, 26, 18)  # its top, and its side below the cursor
    plain, plain_low = blueness(pin2_top), blueness(pin2_low)  # before the cursor is on the pin
    page.mouse.move(*xy)
    n.settle()
    page.wait_for_timeout(200)
    assert page.inner_text("#cursor-tip") == "core_pin · 全体", page.inner_text("#cursor-tip")
    lit, lit_low = blueness(pin2_top), blueness(pin2_low)
    set_filter("面")
    page.mouse.move(xy[0] + 1, xy[1])
    n.settle()
    page.wait_for_timeout(200)
    face_only = blueness(pin2_top)
    set_filter("部品")
    page.mouse.move(*xy)
    n.settle()
    page.wait_for_timeout(200)
    to_blue = lambda c: math.dist(c, LIGHT_BLUE)
    assert to_blue(lit) < to_blue(plain) - 40, ("部品: the pin's top is tinted too", plain, lit)
    assert to_blue(lit_low) < to_blue(plain_low) - 40, ("部品: and its side", plain_low, lit_low)
    assert to_blue(face_only) > to_blue(lit) + 40, ("面: the top keeps its colour", face_only, lit)
    print("2b the whole pin lit", [round(v) for v in plain], [round(v) for v in lit], [round(v) for v in face_only])
    page.mouse.click(*xy)
    n.settle()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('core_pin 全体 を選択')", timeout=5000)
    block_top = n.project((50, 30, 35))
    assert pick(block_top)["kind"] == "part"
    page.mouse.move(*block_top)
    page.mouse.click(*block_top)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離 1.000')", timeout=10000)
    row = page.evaluate("[...document.querySelectorAll('#measure-list li')].map(li => li.querySelector('.m-what')?.textContent).pop()")
    assert row == "core_pin 全体 ↔ cavity_block 全体", row
    print("3 parts:", hud(), row)
    page.keyboard.press("Escape")
    n.settle()

    # ---- a curve-only part (no faces): taken by its lines
    empty_sidecar(page, loose)
    n.load(str(loose))
    gui_common.set_mode(page, "計測")
    assert filter_ctl().locator("select").evaluate("s => s.options[s.selectedIndex].text") == "部品"
    on_x = (-20, 0, 0)  # the X axis line, clear of the box (and on screen: the box is framed)
    xy = n.project(on_x)
    size = page.viewport_size
    assert 0 < xy[0] < size["width"] and 0 < xy[1] < size["height"], xy
    p = pick(xy)
    assert p and p["kind"] == "part", ("a curve-only part is taken by its lines", p)

    def nearest_blue(xyz):
        """the pixel within 3 px of the point that is nearest 水色: the line is a few px wide"""
        x, y = n.project(xyz)
        img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
        px = [img.getpixel((int(x) + dx, int(y) + dy)) for dx in range(-3, 4) for dy in range(-3, 4)]
        return min(px, key=lambda c: math.dist(c, LIGHT_BLUE))

    on_y = (0, -8, 0)  # another of its lines, away from the cursor (and on screen)
    yy = n.project(on_y)
    assert 0 < yy[0] < size["width"] and 0 < yy[1] < size["height"], yy
    page.mouse.move(5, 5)
    n.settle()
    page.wait_for_timeout(200)
    plain = nearest_blue(on_y)
    page.mouse.move(*xy)
    n.settle()
    page.wait_for_timeout(200)
    assert page.inner_text("#cursor-tip") == "曲線（3 本） · 全体", page.inner_text("#cursor-tip")
    lit = nearest_blue(on_y)
    assert math.dist(lit, LIGHT_BLUE) < math.dist(plain, LIGHT_BLUE) - 40, ("its other lines are lit too", plain, lit)
    page.mouse.click(*xy)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('曲線（3 本） 全体 を選択')", timeout=5000)
    # the partner: the box's far corner. From the whole part it is nearest the
    # Z axis, √(10² + 20²) (the X axis alone: √(20² + 30²))
    set_filter("頂点")
    far = toward((10, 20, 30), (5, 10, 15), 6)  # just inside the outline: the ray must hit the box
    v = pick(far)
    assert v and v["kind"] == "vertex" and math.dist(v["point"], (10, 20, 30)) < 1e-3, v
    page.mouse.move(*far)
    page.mouse.click(*far)
    want = f"距離 {math.hypot(10, 20):.3f}"
    page.wait_for_function(f"document.querySelector('#hud-info').textContent.includes('{want}')", timeout=10000)
    print("4 curves:", plain, lit, hud())
print("PICK FILTER E2E OK")
