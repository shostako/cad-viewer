"""E2E: where a measurement is (issue #47 item 2): a distance along the axes,
a whole circle's centre, a vertex's point.

mini_mold (make_step_assembly.py): plate 100 x 60 x 15 from the origin; pin 2
radius 4 at (75, 30), z 15..40; the cavity block 30..70 x 15..45, z 15..35.

- the plate's top front right corner (100, 0, 15) to the block's (70, 15, 35):
  slanted, so the row's third line says ΔX 30.000 ΔY 15.000 ΔZ 20.000 (sizes,
  no sign), and the copy has them in its own cells
- the block's top to the plate's top: straight down, no third line (ΔZ alone
  is the value), the copy's cells 0, 0, 20
- pin 2's top rim: ⌀8.000, its third line 中心 (75.000, 30.000, 40.000)
- the hover label of a vertex: its name and its point
- a reload reads the same rows back (the saved entries keep the axes and the centre)

Oracles: the known geometry; __cadPick at each aim (a vertex: exactly the
corner); the clipboard.
"""
import math

from nav_common import empty_sidecar, nav_session

import gui_common

PLATE_CORNER = (100, 0, 15)
BLOCK_CORNER = (70, 15, 35)
BLOCK_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)
PIN2_RIM = (75, 26, 40)  # on pin 2's top circle, the side toward the camera (-Y)
HEAD = "種類\t値\t単位\t対象 A\t対象 B\tΔX\tΔY\tΔZ"

with nav_session() as n:
    page = n.page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.evaluate("window.__cadViewMotion(false)")
    step = n.paths["step"]  # a private copy, its own sidecar (emptied by nav_session)
    n.load(step)
    gui_common.set_mode(page, "計測")

    def rows():
        return page.evaluate(
            """() => [...document.querySelectorAll('#measure-list li')].map(li => ({
                 kind: li.dataset.kind, value: li.querySelector('.m-value')?.textContent ?? null,
                 what: li.querySelector('.m-what')?.textContent ?? null,
                 where: li.querySelector('.m-where')?.textContent ?? null }))"""
        )

    def aim(xyz, kind):
        xy = n.project(xyz)
        hit = n.pick(xy)
        assert hit and hit["kind"] == kind and math.dist(hit["point"], xyz) < (1e-6 if kind == "vertex" else 0.3), (xyz, kind, hit)
        return xy, hit

    def measure(p, kp, q, kq):
        n0 = len(rows())
        (pxy, ph), (qxy, qh) = aim(p, kp), aim(q, kq)
        page.mouse.click(*pxy)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
        page.mouse.click(*qxy)
        page.wait_for_function(
            f"document.querySelectorAll('#measure-list li').length > {n0}"
            " && document.querySelector('#hud-info').textContent.includes('距離')",
            timeout=15000,
        )
        page.wait_for_timeout(200)
        return rows()[n0:], ph, qh

    def copy_row(i):
        page.evaluate("navigator.clipboard.writeText('')")
        page.locator("#measure-list li").nth(i).locator(".m-copy").click()
        page.wait_for_timeout(100)
        return page.evaluate("navigator.clipboard.readText()")

    # ---- the hover label of a vertex: its point, exact
    xy, hit = aim(PLATE_CORNER, "vertex")
    page.mouse.move(xy[0] + 1, xy[1])
    page.mouse.move(*xy)
    page.wait_for_function(
        "document.querySelector('#cursor-tip')?.textContent.endsWith(' (100.000, 0.000, 15.000)')", timeout=10000
    )
    print("vertex label:", page.text_content("#cursor-tip"))

    # ---- 1. two corners: slanted
    new, ph, qh = measure(PLATE_CORNER, "vertex", BLOCK_CORNER, "vertex")
    print("1", new)
    a, b = f"plate 頂点#{ph['id']}", f"cavity_block 頂点#{qh['id']}"
    d = math.dist(PLATE_CORNER, BLOCK_CORNER)
    assert new == [{"kind": "distance", "value": f"{d:.3f} mm", "what": f"{a} ↔ {b}",
                    "where": "ΔX\u00a030.000　ΔY\u00a015.000　ΔZ\u00a020.000"}], new
    assert copy_row(0) == f"距離\t{d:.3f}\tmm\t{a}\t{b}\t30.000\t15.000\t20.000", page.evaluate("navigator.clipboard.readText()")

    # the right half of a screen: the third line wraps rather than cut its numbers off
    page.set_viewport_size({"width": 767, "height": 639})
    page.wait_for_timeout(300)
    fit = page.evaluate(
        """() => { const e = document.querySelector('#measure-list li .m-where')
             return [e.scrollWidth, e.clientWidth, e.getClientRects().length, e.getBoundingClientRect().height,
                     parseFloat(getComputedStyle(e).lineHeight)] }"""
    )
    print("767 where:", fit)
    assert fit[0] <= fit[1], ("the third line is cut off at 767 px", fit)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_timeout(300)

    # ---- 2. the tops: straight down, no third line
    new, ph, qh = measure(BLOCK_TOP, "face", PLATE_TOP, "face")
    print("2", new)
    a2, b2 = f"cavity_block 面#{ph['id']}", f"plate 面#{qh['id']}"
    assert new == [{"kind": "distance", "value": "20.000 mm", "what": f"{a2} ↔ {b2}", "where": None}], new
    assert copy_row(1) == f"距離\t20.000\tmm\t{a2}\t{b2}\t0.000\t0.000\t20.000", page.evaluate("navigator.clipboard.readText()")

    # ---- 3. pin 2's rim: its centre
    n0 = len(rows())
    xy, hit = aim(PIN2_RIM, "edge")
    page.mouse.click(*xy)
    page.wait_for_function(f"document.querySelectorAll('#measure-list li').length > {n0}", timeout=15000)
    new = rows()[n0:]
    print("3", new)
    assert new == [{"kind": "diameter", "value": "⌀8.000 mm", "what": "core_pin 円エッジ (L=25.133)",
                    "where": "中心\u00a0(75.000, 30.000, 40.000)"}], new
    page.keyboard.press("Escape")
    # the centre is not in the copy: the ΔX ΔY ΔZ cells are a distance's
    assert copy_row(2) == "直径\t8.000\tmm\tcore_pin 円エッジ (L=25.133)\t\t\t\t", page.evaluate("navigator.clipboard.readText()")
    page.click("#measure-copy-all")
    page.wait_for_timeout(100)
    assert page.evaluate("navigator.clipboard.readText()").split("\n")[0] == HEAD

    # ---- 4. a reload: the same rows
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
    print("MEASURE AXES E2E OK")
