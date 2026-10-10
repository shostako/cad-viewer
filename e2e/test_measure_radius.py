"""E2E: the size of a curved face or edge, told by its kind (issue #47 item 1).

curved_part.step (make_step_assembly.py, make_curved_part): body, a block
60 x 40 x 10 with its vertical edges rounded R5, a through hole ⌀6 at (12, 20),
a boss at (38, 20) (radius 6 at its foot, 8 high, 2° draft, its foot rounded
R1), a dimple (a sphere of radius 4 centred at (52, 30, 12)); nurbs_pin, a
cylinder of radius 3 at (75, 20) with its top edge rounded R1, all written as
B-splines.

In 計測 the first click on a curved face or edge adds its size as an entry of
its own: a whole cylinder or circle ⌀, a part of one R, a torus R, a sphere
SR, a cone 勾配 (degrees), a B-spline cylinder ⌀ (recognised), and a B-spline
of no simple kind the R at the click. Checked: the row (value with its mark
and unit, what was measured), the 3D label, the copy (the bare number), the
hover label (no R at a point: it would change along the face), and a reload
(the saved entries read back the same).

Oracles: the known geometry; __cadPick at each aim (the click must land on the
aimed face or edge: its point within 0.3 mm of the aim); the clipboard.
"""
import math
import shutil
import tempfile
from pathlib import Path

from nav_common import empty_sidecar, nav_session

import gui_common

SRC = Path(__file__).resolve().parents[1] / "testdata" / "curved_part.step"
C45 = math.cos(math.radians(45))
T2 = math.tan(math.radians(2))
# the boss's rounding: its tube's centre is 1 above the top and 1 off the drafted side
BOSS_TUBE = 6 - T2 + 1 / math.cos(math.radians(2))


def facing(cx, cy, r, z):
    """the point at distance r from the axis (cx, cy) on the side toward the camera (+X, -Y)"""
    return (cx + r * C45, cy - r * C45, z)


# (name, aim, kind, the row's value, what the row says was measured, the label, zoom in first)
AIMS = [
    ("corner", facing(55, 5, 5, 5), "face", "R5.000 mm", "body 円筒面", "R5.000 mm", False),
    ("hole", (12 - 3 * C45, 20 + 3 * C45, 9), "face", "⌀6.000 mm", "body 円筒面", "⌀6.000 mm", True),  # its far wall
    ("dimple", (52 - 4 * math.sin(math.radians(30)) * C45, 30 + 4 * math.sin(math.radians(30)) * C45,
                12 - 4 * math.cos(math.radians(30))), "face", "SR4.000 mm", "body 球面", "SR4.000 mm", True),
    ("boss_side", facing(38, 20, 6 - 4 * T2, 14), "face", "勾配 2.000°", "body 円錐面", "勾配 2.000°", False),
    ("boss_round", facing(38, 20, BOSS_TUBE - C45, 11 - C45), "face", "R1.000 mm", "body トーラス面", "R1.000 mm", True),
    ("pin_side", facing(75, 20, 3, 5), "face", "⌀6.000 mm", "nurbs_pin 円筒面", "⌀6.000 mm", False),
    ("pin_round", facing(75, 20, 2 + C45, 9 + C45), "face", "R1.000 mm", "nurbs_pin 曲面（クリックした点）", "R1.000 mm", True),
    ("corner_arc", facing(55, 5, 5, 10), "edge", "R5.000 mm", "body 円弧 (L=7.854)", "R5.000 mm", False),
    ("hole_rim", (12 - 3 * C45, 20 + 3 * C45, 10), "edge", "⌀6.000 mm", "body 円エッジ (L=18.850)", "⌀6.000 mm", True),
]
# the hover label's size: that of the whole face or edge; none for the R at a point (pin_round)
HOVER = {
    "corner": " R5.000", "hole": " ⌀6.000", "dimple": " SR4.000", "boss_side": " 勾配 2.000°", "boss_round": " R1.000",
    "pin_side": " ⌀6.000", "corner_arc": " R5.000", "hole_rim": " ⌀6.000",
}
COPY = {
    "corner": "半径\t5.000\tmm\tbody 円筒面\t",
    "dimple": "半径\t4.000\tmm\tbody 球面\t",
    "boss_side": "勾配\t2.000\t°\tbody 円錐面\t",
    "pin_round": "半径\t1.000\tmm\tnurbs_pin 曲面（クリックした点）\t",
}

tmp = tempfile.mkdtemp(prefix="cad_radius_")
try:
    # a private copy: its own content hash, so its own sidecar (the reload reads it back)
    step = Path(tmp) / "curved_part.step"
    step.write_bytes(SRC.read_bytes() + b"\n" * 17)
    with nav_session() as n:
        page = n.page
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.evaluate("window.__cadViewMotion(false)")
        empty_sidecar(page, step)
        n.load(step)
        gui_common.set_mode(page, "計測")

        def rows():
            return page.evaluate(
                """() => [...document.querySelectorAll('#measure-list li')].map(li => ({
                     kind: li.dataset.kind, value: li.querySelector('.m-value')?.textContent ?? null,
                     what: li.querySelector('.m-what')?.textContent ?? null }))"""
            )

        def tip():
            return page.evaluate(
                "(() => { const e = document.querySelector('#cursor-tip');"
                " return e && getComputedStyle(e).display !== 'none' ? e.textContent : '' })()"
            )

        def aim_at(name, xyz, kind, zoom):
            """the screen point of the aim, zoomed in on it first when the shape is small"""
            if zoom:
                page.keyboard.press("f")
                n.settle()
                x, y = n.project(xyz)
                page.mouse.move(x, y)
                for _ in range(8):
                    page.mouse.wheel(0, -300)
                    page.wait_for_timeout(60)
                n.settle()
            xy = n.project(xyz)
            hit = n.pick(xy)
            assert hit and hit["kind"] == kind, (name, "the aim must be a", kind, hit)
            assert math.dist(hit["point"], xyz) < 0.3, (name, "the click lands off the aim", hit, xyz)
            return xy

        by_name = {}
        for name, xyz, kind, value, what, label, zoom in AIMS:
            xy = aim_at(name, xyz, kind, zoom)
            # the hover label first: the whole face's or edge's size, none for the R at a point
            page.mouse.move(xy[0] + 1, xy[1])
            page.mouse.move(*xy)
            if name in HOVER:
                page.wait_for_function(
                    f"document.querySelector('#cursor-tip')?.textContent.endsWith({HOVER[name]!r})", timeout=10000
                )
            else:
                page.wait_for_timeout(800)  # the rest (150 ms) and an answer, had one been asked
                t = tip()
                assert t and " R" not in t and "⌀" not in t, (name, "no size at a point in the hover", t)
            n0 = len(rows())
            page.mouse.click(*xy)
            page.wait_for_function(f"document.querySelectorAll('#measure-list li').length > {n0}", timeout=15000)
            new = rows()[n0:]
            print(name, new)
            kind_of_row = "draft" if value.startswith("勾配") else "radius" if "R" in value else "diameter"
            assert new == [{"kind": kind_of_row, "value": value, "what": what}], (name, new)
            by_name[name] = n0
            assert page.locator(".dim-label", has_text=label).count() >= 1, (name, label)
            assert page.locator(".dim-label", has_text=label).first.inner_text() == label, (name, label)
            page.keyboard.press("Escape")  # drop the first point: the next click starts afresh
            page.wait_for_timeout(100)
            if zoom:
                page.keyboard.press("f")
                n.settle()

        # ---- the copy: the bare number, its kind's name
        for name, want in COPY.items():
            page.locator("#measure-list li").nth(by_name[name]).locator(".m-copy").click()
            page.wait_for_timeout(100)
            got = page.evaluate("navigator.clipboard.readText()")
            assert got == want, (name, got)

        # ---- a reload: the saved entries read back as the same rows
        before = rows()
        page.wait_for_timeout(1500)  # the sidecar's save (0.8 s after the last change)
        page.reload()
        page.wait_for_load_state("networkidle")
        page.evaluate("window.__cadViewMotion(false)")
        n.load(step)
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length === {len(before)}", timeout=15000)
        assert rows() == before, (rows(), before)

        empty_sidecar(page, step)
        gui_common.set_mode(page, "なし")
    print("MEASURE RADIUS E2E OK")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
