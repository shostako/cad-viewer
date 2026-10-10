"""E2E: the angle between two flat things (planar faces, straight edges).

mini_mold (make_step_assembly.py): the cavity block 30..70 x 15..45, its top at
z 35 on the plate's top (z 15). Picked in 計測:

- the block's top and its front side (y 15): they meet, so the distance is
  0.000 mm, and the angle 90.000° comes as an entry of its own; the status
  line says both; the label reads 90.000° (no mm)
- the block's top and the plate's top: parallel, so no angle
- the block's front-right edge (vertical) and the plate's top: a line and a
  plane, 90°

The rows, the copy (角度, the bare number, °) and the labels follow the
measure record's rules. Oracles: __cadPick for what the clicks take (the face
and edge ids in the rows), the known geometry's right angles, the clipboard.
"""
from nav_common import nav_session

import gui_common

BLOCK_TOP = (50, 30, 35)
BLOCK_FRONT = (50, 15, 25)
PLATE_TOP = (90, 10, 15)
# the vertical edge between the front and the right side: both faces face the
# camera (+X, -Y), so the click lands on the drawn edge, not past a silhouette
BLOCK_EDGE = (70, 15, 25)

with nav_session() as n:
    page = n.page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    n.stub_sidecar()
    n.load(n.paths["step"])
    gui_common.set_mode(page, "計測")

    def rows():
        return page.evaluate(
            """() => [...document.querySelectorAll('#measure-list li')].map(li => ({
                 kind: li.dataset.kind, value: li.querySelector('.m-value')?.textContent ?? null,
                 what: li.querySelector('.m-what')?.textContent ?? null }))"""
        )

    def measure(p, q):
        n0 = len(rows())
        for x in (p, q):
            page.mouse.click(*n.project(x))
            page.wait_for_timeout(300)
        page.wait_for_function(
            f"document.querySelectorAll('#measure-list li').length > {n0}"
            " && document.querySelector('#hud-info').textContent.includes('距離')",
            timeout=15000,
        )
        page.wait_for_timeout(300)
        return rows()[n0:]

    ht, hf = n.pick(n.project(BLOCK_TOP)), n.pick(n.project(BLOCK_FRONT))
    assert ht["kind"] == "face" and hf["kind"] == "face" and ht["partId"] == hf["partId"], (ht, hf)
    blk = ht["partId"]
    a = f"cavity_block 面#{ht['id']}"
    b = f"cavity_block 面#{hf['id']}"

    # ---- 1. the block's top and front: 0.000 mm, and 90.000° as its own entry
    new = measure(BLOCK_TOP, BLOCK_FRONT)
    print("1", new, page.text_content("#hud-info"))
    assert new == [
        {"kind": "distance", "value": "0.000 mm", "what": f"{a} ↔ {b}"},
        {"kind": "angle", "value": "90.000°", "what": f"{a} ∠ {b}"},
    ], new
    assert page.text_content("#hud-info") == "距離 0.000　角度 90.000°", page.text_content("#hud-info")
    assert page.locator(".dim-label", has_text="90.000").first.inner_text() == "90.000°"
    page.locator("#measure-list li").nth(1).locator(".m-copy").click()
    page.wait_for_timeout(100)
    assert page.evaluate("navigator.clipboard.readText()") == f"角度\t90.000\t°\t{a}\t{b}", page.evaluate("navigator.clipboard.readText()")

    # ---- 2. parallel tops: no angle
    new = measure(BLOCK_TOP, PLATE_TOP)
    print("2", new)
    assert [r["kind"] for r in new] == ["distance"] and new[0]["value"] == "20.000 mm", new

    # ---- 3. a vertical edge and the plate's top: a line and a plane, 90°
    he = n.pick(n.project(BLOCK_EDGE))
    assert he and he["kind"] == "edge" and he["partId"] == blk, ("the click must take the block's edge", he)
    new = measure(BLOCK_EDGE, PLATE_TOP)
    print("3", new)
    assert [r["kind"] for r in new] == ["distance", "angle"] and new[1]["value"] == "90.000°", new
    assert new[1]["what"].startswith(f"cavity_block エッジ#{he['id']} ∠ plate 面#"), new[1]

    gui_common.set_mode(page, "なし")
    print("MEASURE ANGLE E2E OK")
