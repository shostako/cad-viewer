"""E2E: in 計測 / 注記, what a click would pick is shown before the click
(hover preselection): the face tinted, the edge drawn thick, the vertex ringed,
in light blue (水色); its name beside the cursor (#cursor-tip) as the measure
list names it, with the exact ⌀ of a circular edge / cylindrical face, and a
vertex's point, once the backend has answered; after the first point, a
dotted line from it to the candidate; the status line says which point the
next click gives.

Expected values never come from the code under test. They come from how
mini_mold.step is built (testdata/make_step_assembly.py: plate 100x60x15,
core pins r4 at x 25 / 75, y 30, z 15..40, cavity block 30..70 x 15..45 x
15..35), window.__cadProject / window.__cadPick (the picker a click uses),
canvas pixels read with toDataURL inside rAF, the PNG the browser downloads,
DOM texts and rects. A highlight is found by comparing a frame with it against
a frame of the same view without it (the cursor off the model, or mode なし):
the pixels that change must be where the entity is drawn, and closer to the
highlight colour than before.

Sidecar requests are answered in the page: nothing is written on the backend.
"""
import json
import math
import re

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

from nav_common import BASE_URL, DXF, STEP_SRC, TESTDATA, Nav, sub

STEP = str(STEP_SRC)
STL = str(TESTDATA / "ribbed_plate.stl")
SHOTS = "/tmp/cad_viewer_hover_preselect"
LB = np.array((0x55, 0xD6, 0xFF))  # the highlight colour (水色), sRGB

MEASURE_HINT = "計測: クリックで 1 点目（Esc でやめる）"
NOTE_HINT = "注記: クリックした点に注記を付ける（Esc でやめる）"
MESH_HINT = "計測はSTEP/IGESモデルのみ（メッシュ形式に真値はない）"

BLOCK_TOP = (50, 30, 35)  # the middle of the cavity block's top face
BLOCK_EDGE = (50, 15, 35)  # the middle of the block's top front edge (y 15, z 35)
CORNER = (100, 0, 15)  # the plate's front right top corner
PLATE_TOP = (90, 10, 15)  # on the plate's top face, clear of the pins and the block
PIN2, PIN1, PIN_R = (75, 30), (25, 30), 4
PIN2_RIM = (75, 26, 40)  # on pin 2's top circle, the side toward the camera (-Y)
PIN2_SIDE = (75 + 4 * math.cos(math.radians(-60)), 30 + 4 * math.sin(math.radians(-60)), 27)
# the shortest distance from the block's top face (z 35, x 30..70, y 15..45) to the corner: from (70, 15, 35)
TOP_TO_CORNER = math.dist((70, 15, 35), CORNER)
# the corner's label: its name, then its point (the backend's, exact)
CORNER_AT = " (100.000, 0.000, 15.000)"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        nav = Nav(page, {})
        page.on("pageerror", lambda e: nav.errors.append(str(e)))
        page.on("console", lambda m: nav.errors.append(m.text) if m.type == "error" else None)
        infos = []  # edge_info / face_info requests: (type, kind, id)

        def on_request(r):
            if r.url.endswith("/measure") and r.method == "POST":
                body = json.loads(r.post_data or "{}")
                if body.get("type") in ("edge_info", "face_info"):
                    ref = body["ref"]
                    infos.append((body["type"], ref["partId"], ref["kind"], ref["id"]))

        page.on("request", on_request)
        nav.stub_sidecar()  # from before the first load
        page.goto(BASE_URL)
        page.evaluate("localStorage.removeItem('cad-viewer:view')")
        page.reload()
        page.wait_for_load_state("networkidle")
        run(page, nav, infos)
        page.evaluate("localStorage.removeItem('cad-viewer:view')")
        if nav.errors:
            print("PAGE ERRORS:", nav.errors)
        assert not nav.errors
        browser.close()
    print("HOVER PRESELECT E2E OK")


def run(page, nav, infos):
    settle, project, pick = nav.settle, nav.project, nav.pick

    # ---- helpers ----------------------------------------------------------------
    def hud():
        return page.text_content("#hud-info")

    def tip():
        """(shown, text) of the label beside the cursor"""
        return page.evaluate(
            """(() => { const e = document.querySelector('#cursor-tip'); if (!e) return [false, '']
                 const r = e.getBoundingClientRect()
                 return [getComputedStyle(e).display !== 'none' && r.width > 0, e.textContent] })()"""
        )

    def tip_text(tag):
        shown, text = tip()
        assert shown, (tag, "no label beside the cursor", text)
        return text

    def assert_no_tip(tag):
        shown, text = tip()
        assert not shown, (tag, "a label is shown", text)

    def frame():
        return np.asarray(nav.canvas_image()).astype(int)

    def to_px(img, xy):
        cl, ct, cw, ch = nav.canvas_rect()
        return int((xy[0] - cl) * img.shape[1] / cw), int((xy[1] - ct) * img.shape[0] / ch)

    def changed(h, r, pts, thr=25):
        """share of the points whose colour differs by more than thr between frames h and r"""
        n = 0
        for xy in pts:
            x, y = to_px(h, xy)
            n += int(np.abs(h[y, x] - r[y, x]).max() > thr)
        return n / len(pts)

    def toward_lb(h, r, pts, by=20):
        """share of the points whose colour got closer to the highlight colour by `by` or more"""
        n = 0
        for xy in pts:
            x, y = to_px(h, xy)
            n += int(np.linalg.norm(h[y, x] - LB) <= np.linalg.norm(r[y, x] - LB) - by)
        return n / len(pts)

    def near_lb(h, pts, tol=60):
        n = 0
        for xy in pts:
            x, y = to_px(h, xy)
            n += int(np.abs(h[y, x] - LB).max() <= tol)
        return n / len(pts)

    def same_frame(a, b, tag, tol=3):
        d = int(np.abs(a - b).max())
        assert d <= tol, (tag, "the frame differs (a highlight left on screen?)", d, int((np.abs(a - b).max(axis=2) > tol).sum()))

    def hover(xy):
        page.mouse.move(*xy)
        settle()

    def on(xyz, tol=0.3):
        """xyz's screen point, which must see xyz (the first surface the eye meets there)"""
        xy = project(xyz)
        hit = pick(xy)
        assert hit and math.dist(hit["point"], xyz) <= tol, ("not on screen", xyz, hit)
        return xy

    def picks(xys):
        """__cadPick at each point, in one round trip"""
        return page.evaluate("pts => pts.map(([x, y]) => window.__cadPick(x, y))", [list(q) for q in xys])

    def visible_samples(pts, kind="face", same_as=None):
        """projections of the points that a pick there sees as `same_as` (partId, kind, id)"""
        xys = nav.project_many(pts)
        out = []
        for q, xy, hit in zip(pts, xys, picks(xys)):
            if hit and hit["kind"] == kind and math.dist(hit["point"], q) <= 0.3:
                if same_as is None or (hit["partId"], hit["kind"], hit["id"]) == same_as:
                    out.append(xy)
        return out

    def name_of(hit, part):
        kind = {"face": "面", "edge": "エッジ", "vertex": "頂点"}[hit["kind"]]
        return f"{part} · {kind}#{hit['id']}"

    def set_mode(label):
        nav.set_mode(label)
        settle()

    def background_point():
        cl, ct, cw, ch = nav.canvas_rect()
        for fx, fy in ((0.66, 0.85), (0.7, 0.8), (0.2, 0.6), (0.5, 0.2), (0.15, 0.4), (0.75, 0.15)):
            xy = (cl + fx * cw, ct + fy * ch)
            el = page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.tagName", list(xy))
            if pick(xy) is None and el == "CANVAS":
                return xy
        raise AssertionError("no background point")

    def plain_frame():
        """the frame without any highlight: the cursor on the background (nothing to pick)"""
        hover(background_point())
        assert_no_tip("background")
        return frame()

    # block top face samples (visible and on that face), the front face, the plate top
    TOP_PTS = [(x, y, 35) for x in (34, 42, 50, 58, 66) for y in (19, 25, 30, 35, 41)]
    FRONT_PTS = [(x, 15, z) for x in (36, 50, 64) for z in (20, 25, 30)]
    PLATE_PTS = [(10, 10, 15), (90, 10, 15), (15, 50, 15), (88, 50, 15), (50, 7, 15)]

    # ================= (a) なし: nothing is drawn or named ========================
    nav.load(STEP)
    assert hud().startswith("mini_mold"), hud()
    summary = hud()
    plain = plain_frame()
    a_xy = on(BLOCK_TOP)
    hover(a_xy)
    assert_no_tip("mode なし")
    same_frame(frame(), plain, "(a) mode なし over the block")
    print("(a) なし: no label, no highlight")

    # ================= (b) 計測: the status line ===================================
    set_mode("計測")
    assert hud() == MEASURE_HINT, hud()
    set_mode("なし")
    assert hud() == summary, ("the hint goes with the mode", hud())
    set_mode("計測")
    print("(b) hint:", hud())

    # ================= (c) a face ====================================================
    plain = plain_frame()
    hit = pick(a_xy)
    assert hit["kind"] == "face", hit
    face_a = (hit["partId"], hit["kind"], hit["id"])
    hover(a_xy)
    t = tip_text("(c) face")
    print("(c) face label:", t, "pick", hit)
    assert t == name_of(hit, "cavity_block"), (t, hit)
    h = frame()
    top = visible_samples(TOP_PTS, same_as=face_a)
    front = visible_samples(FRONT_PTS)
    plate = visible_samples(PLATE_PTS)
    assert len(top) >= 15 and len(front) >= 6 and len(plate) >= 4, (len(top), len(front), len(plate))
    c_top, c_front, c_plate = changed(h, plain, top), changed(h, plain, front), changed(h, plain, plate)
    lb_top = toward_lb(h, plain, top)
    print("(c) changed: top %.2f front %.2f plate %.2f; top toward 水色 %.2f" % (c_top, c_front, c_plate, lb_top))
    assert c_top >= 0.95 and lb_top >= 0.9, ("the face must be tinted 水色", c_top, lb_top)
    assert c_front == 0 and c_plate == 0, ("only that face", c_front, c_plate)
    page.screenshot(path=SHOTS + "_face.png")

    # ================= (d) an edge ===================================================
    e_xy = on(BLOCK_EDGE, tol=0.5)
    hit = pick(e_xy)
    assert hit["kind"] == "edge", hit
    hover(e_xy)
    t = tip_text("(d) edge")
    print("(d) edge label:", t, "pick", hit)
    assert t == name_of(hit, "cavity_block"), (t, hit)
    h = frame()
    p0, p1 = project((30, 15, 35)), project((70, 15, 35))
    along = [(p0[0] + (p1[0] - p0[0]) * k / 40, p0[1] + (p1[1] - p0[1]) * k / 40) for k in range(4, 37)]
    d = sub(p1, p0)
    nrm = (-d[1] / math.hypot(*d), d[0] / math.hypot(*d))
    beside = [(x + s * 9 * nrm[0], y + s * 9 * nrm[1]) for x, y in along[::3] for s in (1, -1)]
    c_along, c_beside, lb_along = changed(h, plain, along), changed(h, plain, beside), near_lb(h, along)
    print("(d) changed along %.2f beside %.2f; along near 水色 %.2f; top %.2f" % (c_along, c_beside, lb_along, changed(h, plain, top)))
    assert c_along >= 0.95 and lb_along >= 0.9, ("the edge must be drawn thick in 水色", c_along, lb_along)
    assert c_beside == 0, ("a line, not a band", c_beside)
    assert changed(h, plain, top) <= 0.05, "an edge, not the face"
    page.screenshot(path=SHOTS + "_edge.png")

    # ================= (e) a vertex (the cursor 6 px off the corner) ================
    def corner_xy():
        """6 px from the corner's projection, toward the plate's top"""
        c = project(CORNER)
        toward = sub(project(PLATE_TOP), c)
        return c, (c[0] + 6 * toward[0] / math.hypot(*toward), c[1] + 6 * toward[1] / math.hypot(*toward))

    c_xy, v_xy = corner_xy()
    hit = pick(v_xy)
    assert hit and hit["kind"] == "vertex" and math.dist(hit["point"], CORNER) < 1e-6, ("the snap takes the corner", hit)
    vertex_b = hit
    hover(v_xy)
    page.wait_for_function(f"document.querySelector('#cursor-tip')?.textContent.endsWith({CORNER_AT!r})", timeout=10000)
    t = tip_text("(e) vertex")
    print("(e) vertex label:", t)
    assert t == name_of(hit, "plate") + CORNER_AT, (t, hit)
    h = frame()
    ring = [(c_xy[0] + 7.75 * math.cos(a), c_xy[1] + 7.75 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 24, endpoint=False)]
    inside = [(c_xy[0] + 2.5 * math.cos(a), c_xy[1] + 2.5 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    outside = [(c_xy[0] + 15 * math.cos(a), c_xy[1] + 15 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
    c_ring, c_in, c_out, lb_ring = changed(h, plain, ring), changed(h, plain, inside), changed(h, plain, outside), near_lb(h, ring)
    print("(e) changed ring %.2f inside %.2f outside %.2f; ring near 水色 %.2f" % (c_ring, c_in, c_out, lb_ring))
    assert c_ring >= 0.9 and lb_ring >= 0.8, ("a 水色 ring round the vertex", c_ring, lb_ring)
    assert c_in <= 0.15 and c_out == 0, ("a ring, nothing else", c_in, c_out)
    assert changed(h, plain, plate) == 0, "a vertex, not the face"
    page.screenshot(path=SHOTS + "_vertex.png")

    # ================= (f) the ⌀ of a circular edge and a cylindrical face ===========
    def wait_dia(tag, want="⌀8.000"):
        page.wait_for_function(
            f"document.querySelector('#cursor-tip').textContent.endsWith({want!r})"
            " && getComputedStyle(document.querySelector('#cursor-tip')).display !== 'none'",
            timeout=10000,
        )
        return tip_text(tag)

    rim_xy = on(PIN2_RIM, tol=0.5)
    hit = pick(rim_xy)
    assert hit["kind"] == "edge", ("pin 2's top circle", hit)
    rim = (hit["partId"], "edge", hit["id"])
    asked = len(infos)
    hover(rim_xy)
    t0 = tip_text("(f) rim")
    t1 = wait_dia("(f) rim")
    print("(f) rim:", t0, "->", t1)
    assert t1 == name_of(hit, "core_pin") + " ⌀8.000", (t1, hit)
    rim_asks = [q for q in infos[asked:] if q[1:] == rim]
    assert len(rim_asks) == 1 and rim_asks[0][0] == "edge_info", ("asked once for the edge", infos[asked:])
    # the cylindrical side
    side_xy = on(PIN2_SIDE, tol=0.5)
    hit = pick(side_xy)
    assert hit["kind"] == "face", ("pin 2's side", hit)
    hover(side_xy)
    t1 = wait_dia("(f) side")
    print("(f) side:", t1)
    assert t1 == name_of(hit, "core_pin") + " ⌀8.000", (t1, hit)
    # a plane has none (it is asked about all the same: only the backend knows)
    hover(a_xy)
    page.wait_for_timeout(700)
    t1 = tip_text("(f) plane")
    assert t1 == name_of(pick(a_xy), "cavity_block"), ("no ⌀ on a plane", t1)
    top_face = pick(a_xy)
    assert [q[0] for q in infos if q[1:] == (top_face["partId"], "face", top_face["id"])] == ["face_info"], infos
    # back on the rim: known at once, not asked again
    n = len(infos)
    hover(rim_xy)
    assert tip_text("(f) rim again").endswith(" ⌀8.000"), "the answer is kept"
    page.wait_for_timeout(400)
    assert [q for q in infos[n:] if q[1:] == rim] == [], ("asked again", infos[n:])
    # Passing over an edge (for less than the rest) asks nothing for it; resting
    # on it does. The pass is two synthetic moves one frame apart (a real mouse
    # move takes a round trip); an edge that a slow frame let the wait run out
    # on is used up (asked), so each try takes a fresh one.
    def passed_over(xy, key):
        n = len(infos)
        el = page.evaluate(
            """async ([p1, p2]) => {
                 const vp = document.querySelector('#viewport')
                 const move = ([x, y]) => vp.dispatchEvent(new PointerEvent('pointermove',
                   { clientX: x, clientY: y, isPrimary: true, pointerType: 'mouse', bubbles: true }))
                 const frame = () => new Promise(r => requestAnimationFrame(() => r()))
                 move(p1); await frame(); const t = performance.now()
                 move(p2); await frame()
                 return performance.now() - t }""",
            [list(xy), list(side_xy)],  # ends on pin 2's side (known: asks nothing)
        )
        page.wait_for_timeout(400)
        return el, [q for q in infos[n:] if q[1:] == key]

    tried = []
    for q in ((40, 0, 15), (100, 40, 15), (20, 0, 15), (100, 20, 15), (60, 0, 0), (100, 50, 0)):
        xy = project(q)
        hh = pick(xy)
        if not hh or hh["kind"] != "edge":
            continue
        key = (hh["partId"], "edge", hh["id"])
        if [r for r in infos if r[1:] == key]:
            continue  # asked before: says nothing
        el, asked = passed_over(xy, key)
        tried.append((q, round(el), asked))
        if el < 140:
            assert asked == [], ("asked for an edge the cursor only passed over", q, el, asked)
            hover(xy)
            page.wait_for_timeout(500)
            assert [r[0] for r in infos if r[1:] == key] == ["edge_info"], ("asked once after a rest", q, infos[-3:])
            break
    else:
        tried.append("skipped: no frame came within 140 ms (a loaded machine)")
    print("(f) passing over an edge:", tried)

    # ---- (f2) a request that fails is no answer: the next rest asks again
    rim1_xy = on((PIN1[0], PIN1[1] - PIN_R, 40), tol=0.5)
    h1 = pick(rim1_xy)
    assert h1["kind"] == "edge", ("pin 1's top circle", h1)
    key1 = (h1["partId"], "edge", h1["id"])
    assert not [q for q in infos if q[1:] == key1], "pin 1's rim asked before"
    failed = []

    def fail_first(route):
        body = json.loads(route.request.post_data or "{}")
        ref = body.get("ref", {})
        if not failed and body.get("type") == "edge_info" and (ref.get("partId"), ref.get("kind"), ref.get("id")) == key1:
            failed.append(1)
            route.abort()
        else:
            route.continue_()

    page.route("**/measure", fail_first)
    hover(rim1_xy)
    page.wait_for_timeout(700)
    assert failed, "(f2) the rim was not asked about"
    assert not tip_text("(f2) after the failure").endswith("⌀8.000")
    hover(a_xy)  # away: the block's top (known, asks nothing)
    hover(rim1_xy)  # back: a new rest
    t = wait_dia("(f2) asked again")
    page.unroute("**/measure")
    assert [q[0] for q in infos if q[1:] == key1] == ["edge_info", "edge_info"], ("(f2)", infos[-4:])
    # the aborted request's console line
    nav.errors[:] = [e for e in nav.errors if "Failed to load resource" not in e]
    print("(f2) asked again after a failure:", t)

    # ================= (g) the pick a click makes; the dotted line; status lines =====
    # before any first point: no dotted line toward the plate
    hover(on(PLATE_TOP))
    pre = frame()
    pt_a, pt_c = project(BLOCK_TOP), project(PLATE_TOP)
    seg = [(pt_a[0] + (pt_c[0] - pt_a[0]) * k / 200, pt_a[1] + (pt_c[1] - pt_a[1]) * k / 200) for k in range(0, 201)]
    # where the segment crosses the block (not the plate's top, which the candidate tints), 10 px clear of the first point
    pt = pick(pt_c)
    plate_top = (pt["partId"], "face", pt["id"])

    over_block = [q for q, hh in zip(seg, picks(seg))
                  if math.dist(q, pt_a) >= 10 and hh is not None and (hh["partId"], hh["kind"], hh["id"]) != plate_top]
    assert len(over_block) >= 30, ("the segment must cross the block", len(over_block))
    plain = plain_frame()
    assert changed(pre, plain, over_block) <= 0.02, "a dotted line before the first point"

    hover(a_xy)
    t_a = tip_text("(g) A")
    page.mouse.click(*a_xy)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    first = hud()
    print("(g) after the first click:", first)
    assert first.startswith(t_a.replace(" · ", " ") + " を選択") and "2 点目" in first, (first, t_a)
    # the dotted line from the first point to the candidate (the plate's top)
    plain_pending = plain_frame()
    hover(project(PLATE_TOP))
    h = frame()
    c_dash, lb_dash = changed(h, plain_pending, over_block), near_lb(h, [q for q in over_block], tol=70)
    print("(g) dotted line over the block: changed %.2f, near 水色 %.2f" % (c_dash, lb_dash))
    assert 0.3 <= c_dash <= 0.9, ("a dotted line from the first point to the candidate", c_dash)
    assert lb_dash >= 0.25, ("the dotted line is 水色", lb_dash)
    assert "Esc で取り消し" in first, first
    page.screenshot(path=SHOTS + "_dash.png")
    # Esc drops the first point: its dotted line goes at once, the cursor still
    h_still = frame()
    page.keyboard.press("Escape")
    settle()
    print("(g) after Esc:", hud())
    assert hud().startswith("1 点目を取り消した"), hud()
    assert changed(frame(), plain, over_block) <= 0.02, "(g) the dotted line stays after Esc"
    assert changed(h_still, plain, over_block) >= 0.3, "(g) the case needs the line before Esc"
    hover(a_xy)
    page.mouse.click(*a_xy)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    # the vertex: the label, then the click takes that very vertex
    hover(v_xy)
    t_b = tip_text("(g) B")
    assert t_b == name_of(vertex_b, "plate") + CORNER_AT, ("the point is known already", t_b)
    page.mouse.click(*v_xy)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離')", timeout=10000)
    # the row: the value with its unit first, what was measured under it
    rows = page.evaluate(
        "[...document.querySelectorAll('#measure-list li')].map(li =>"
        " [li.querySelector('.m-value').textContent, li.querySelector('.m-what').textContent])"
    )
    # the list names the vertex as the label does, without its point (the label's addition)
    want = [f"{TOP_TO_CORNER:.3f} mm", f"{t_a.replace(' · ', ' ')} ↔ {t_b.removesuffix(CORNER_AT).replace(' · ', ' ')}"]
    print("(g) row:", rows, "want", want)
    assert rows == [want], (rows, want)
    assert hud() == f"距離 {TOP_TO_CORNER:.3f}", hud()
    assert_no_tip("after the click")
    # the result stays when the mode goes; the hint comes back with the mode
    set_mode("なし")
    assert hud() == f"距離 {TOP_TO_CORNER:.3f}", ("a result stays", hud())
    set_mode("計測")
    assert hud() == MEASURE_HINT, hud()
    nav.click_button("計測クリア")

    # ================= (h) hidden on click until the next move ======================
    plain = plain_frame()
    far_top = [q for q in top if math.dist(q, a_xy) >= 14]
    hover(a_xy)
    assert changed(frame(), plain, far_top) >= 0.95
    page.mouse.down()
    settle()
    assert_no_tip("button down")
    assert changed(frame(), plain, far_top) == 0, "the highlight must go on the press"
    page.mouse.up()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    page.wait_for_timeout(300)
    settle()
    assert_no_tip("after the click, not moved")
    assert changed(frame(), plain, far_top) == 0, "the highlight must stay away until the cursor moves"
    hover((a_xy[0] + 1, a_xy[1]))
    assert tip_text("moved after the click") == t_a
    assert changed(frame(), plain, far_top) >= 0.95, "back with the next move"
    nav.click_button("計測クリア")  # drops the first point too
    assert hud() == MEASURE_HINT, ("no partner to ask for: back to the hint", hud())

    # ================= (i) a drag, a wheel turn, off the model, off the view ========
    def compare_with_nashi(tag):
        """this frame against the same view in mode なし (no highlight can be there)"""
        a = frame()
        nav.set_mode("なし")
        settle()
        b = frame()
        same_frame(a, b, tag)
        nav.set_mode("計測")
        settle()

    hover(a_xy)
    assert tip()[0]
    page.mouse.down()
    page.mouse.move(a_xy[0] + 15, a_xy[1] + 4, steps=5)
    settle()
    assert_no_tip("dragging")
    page.keyboard.press("f")  # still held: stop the coast, so the view stays as it is
    settle()
    assert_no_tip("dragging, after F")
    compare_with_nashi("(i) during a drag")
    page.mouse.up()
    settle()
    page.keyboard.press("f")
    a_xy = on(BLOCK_TOP)
    print("(i) drag ok")

    hover(a_xy)
    assert tip()[0]
    page.mouse.wheel(0, -100)
    settle()
    settle()
    assert_no_tip("after a wheel turn")
    compare_with_nashi("(i) after a wheel turn")
    hover((a_xy[0] + 1, a_xy[1]))
    assert tip_text("moved after the wheel") == t_a, "the point under the cursor stays with the wheel zoom"
    page.keyboard.press("f")
    settle()
    a_xy = on(BLOCK_TOP)
    print("(i) wheel ok")

    hover(a_xy)
    assert tip()[0]
    hover(background_point())
    assert_no_tip("off the model")
    compare_with_nashi("(i) off the model")
    hover(a_xy)
    assert tip()[0]
    gui = page.locator(".lil-gui.lil-root > .lil-title").bounding_box()
    hover((gui["x"] + 20, gui["y"] + gui["height"] / 2))
    assert_no_tip("over the control panel")
    compare_with_nashi("(i) off the view")
    print("(i) off the model / view ok")

    # ================= (j) leaving the mode (the cursor stays) =======================
    top = visible_samples(TOP_PTS, same_as=face_a)  # the drag above turned the view
    assert len(top) >= 15, len(top)
    plain = plain_frame()
    hover(a_xy)
    assert changed(frame(), plain, top) >= 0.95
    nav.set_mode("なし")
    settle()
    assert_no_tip("mode なし")
    same_frame(frame(), plain, "(j) the mode left with the cursor on the face")
    nav.set_mode("計測")
    settle()
    assert tip_text("back in 計測, the cursor still there") == t_a, "the mode back under a still cursor"
    print("(j) ok")

    # ================= (k) not in the saved image, not in the fit ====================
    plain = plain_frame()
    hover(a_xy)
    h = frame()
    assert changed(h, plain, top) >= 0.95
    with page.expect_download(timeout=15000) as info:
        page.locator("#toolbar button[data-action='png']").evaluate("b => b.click()")  # the mouse stays on the face
    png = np.asarray(Image.open(info.value.path()).convert("RGB")).astype(int)
    assert png.shape == plain.shape, (png.shape, plain.shape)
    same_frame(png, plain, "(k) the saved image")
    assert changed(frame(), plain, top) >= 0.95, "the screen keeps the highlight"
    page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('画像を保存: ')", timeout=10000)
    print("(k) the saved image has no highlight")
    # F with the label and the highlight shown frames as without them. The
    # label must lie in the area a fit frames in (else a fit that took it for
    # a panel would frame the same, and this would test nothing)
    hover(a_xy)
    assert tip()[0]
    r = page.evaluate("(() => { const r = document.querySelector('#cursor-tip').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
    cl, ct, _, _ = nav.canvas_rect()
    (fl, ft, fr, fb), _ = nav.free_area()
    assert fl < r[0] - cl and r[2] - cl < fr and ft < r[1] - ct and r[3] - ct < fb, ("the label is not in the fit's area", r, (fl, ft, fr, fb))
    page.keyboard.press("f")
    settle()
    v1 = nav.view()
    hover(background_point())
    page.keyboard.press("f")
    settle()
    v2 = nav.view()
    assert all(max(abs(a - b) for a, b in zip(v1[k], v2[k])) <= 1e-9 for k in ("position", "target", "up")), (v1, v2)
    print("(k) the fit ignores the label and the highlight")

    # ================= (l) a measurement in flight: no highlight (a click is dropped) ===
    a_xy, c_xy = on(BLOCK_TOP), on(PLATE_TOP)
    _, v_xy = corner_xy()
    plain = plain_frame()
    plate_samples = visible_samples([(85, 8, 15), (92, 12, 15), (88, 52, 15), (12, 52, 15)])
    page.evaluate("window.__cadStallMeasure(1500)")
    page.mouse.click(*a_xy)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    page.mouse.click(*v_xy)  # the corner: the distance request is held 1.5 s
    page.wait_for_timeout(100)
    hover(c_xy)
    hover((c_xy[0] + 1, c_xy[1]))
    assert "距離" not in hud(), "the request should still be held"
    assert_no_tip("while the measurement is in flight")
    assert changed(frame(), plain, plate_samples) == 0, "no highlight while a click would be dropped"
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離')", timeout=10000)
    settle()
    t = tip_text("after the answer, the cursor still")
    assert t == name_of(pick((c_xy[0] + 1, c_xy[1])), "plate"), t
    nav.click_button("計測クリア")
    print("(l) ok")

    # ================= (m) 注記 ======================================================
    set_mode("注記")
    assert hud() == NOTE_HINT, hud()
    hover(a_xy)
    assert tip_text("注記") == t_a
    page.mouse.click(*a_xy)
    page.wait_for_selector(".note-input", timeout=5000)
    assert_no_tip("note box open")
    page.keyboard.press("Escape")
    set_mode("なし")
    assert hud() == summary, ("the note hint goes with the mode", hud())
    print("(m) ok")

    # ================= (n) 半透明: a line drawn through the block ===================
    nav.ctl("表示スタイル").locator("select").select_option(label="半透明")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    settle()
    seam = None
    for z in (32, 28, 36, 24, 20):
        xy = project((PIN1[0] + PIN_R, PIN1[1], z))
        hh = pick(xy)
        if hh and hh["kind"] == "edge" and math.dist(hh["point"], (PIN1[0] + PIN_R, PIN1[1], z)) <= 0.6:
            seam = (xy, hh)
            break
    assert seam, "no point of pin 1's seam that picks it through the block"
    set_mode("計測")
    hover(seam[0])
    t = tip_text("(n) seam")
    assert t == name_of(seam[1], "core_pin"), (t, seam[1])
    page.mouse.click(*seam[0])
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    assert hud().startswith(t.replace(" · ", " ") + " を選択"), (hud(), t)
    nav.click_button("計測クリア")
    set_mode("なし")
    nav.ctl("表示スタイル").locator("select").select_option(label="陰影＋稜線")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    print("(n) 半透明 ok:", t)

    # ================= (n2) 半透明: a slow hover pick waits before the next ==========
    # Every scan of the drawn lines is made to take 25 ms (a model with many
    # edges) and every pick's start and end are logged, by patching the
    # picker's class in the page (the dev server's module the app uses).
    nav.ctl("表示スタイル").locator("select").select_option(label="半透明")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    set_mode("計測")
    plain_xray = plain_frame()
    page.evaluate(
        """async () => {
             const P = (await import('/src/picking.ts')).Picker.prototype
             window.__plainScan = P.snapDrawnLines
             window.__plainPick = P.pick
             window.__pickLog = []
             window.__scanMs = 25
             P.snapDrawnLines = function (ndc) {
               const t = performance.now()
               while (performance.now() - t < window.__scanMs) {}
               return window.__plainScan.call(this, ndc)
             }
             P.pick = function (ndc) {
               const t0 = performance.now()
               const r = window.__plainPick.call(this, ndc)
               window.__pickLog.push([t0, performance.now()])
               return r
             }
           }"""
    )
    a, b = project(BLOCK_TOP), project(PLATE_TOP)
    for k in range(31):
        page.mouse.move(a[0] + (b[0] - a[0]) * k / 30, a[1] + (b[1] - a[1]) * k / 30)
        page.wait_for_timeout(20)
    page.wait_for_timeout(500)
    log = page.evaluate("window.__pickLog")
    # a move inside a wait (right after a pick): the place is looked at when the
    # wait is over, without another move (the block's top, not the plate). A
    # slower scan here (100 ms: a wait of 400 ms) so that the move surely lands
    # inside the wait, also on a busy machine
    page.evaluate("window.__scanMs = 100")
    page.mouse.move(b[0] + 4, b[1])
    page.wait_for_timeout(150)  # its pick (100 ms) has run; the hover now waits 400 ms
    page.mouse.move(*a)
    page.wait_for_timeout(900)
    t = tip_text("(n2) where the cursor stopped")
    ha = pick(a)
    # the block's top face (the plate's top has the same number: the part tells them apart)
    assert ha and ha["kind"] == "face", ha
    assert t == name_of(ha, "cavity_block"), ("(n2) the last place was not looked at", t, ha)
    # a mode change inside a wait: the label and the highlight come back together
    # (a pick of 200 ms, then a wait of 800 ms; the mode changes inside it)
    page.evaluate("window.__scanMs = 200")
    page.mouse.move(a[0] + 3, a[1])
    page.wait_for_timeout(350)
    set_mode("注記")
    settle()
    shown, text = tip()
    lit = changed(frame(), plain_xray, [a, (a[0] + 3, a[1]), (a[0], a[1] + 3), (a[0] - 3, a[1])])
    print("(n2) after a mode change inside a wait:", shown, text, "highlight", round(lit, 2))
    assert shown and text == t and lit >= 0.75, ("(n2) the label without its highlight", shown, text, lit)
    page.evaluate(
        """async () => {
             const P = (await import('/src/picking.ts')).Picker.prototype
             P.snapDrawnLines = window.__plainScan
             P.pick = window.__plainPick
           }"""
    )
    ratios = [(log[i + 1][0] - log[i][1]) / (log[i][1] - log[i][0]) for i in range(len(log) - 1)]
    print("(n2) hover picks", len(log), "wait / pick time", [round(r, 1) for r in ratios])
    assert len(log) >= 3, ("(n2) the case needs several picks", log)
    assert min(ratios) >= 3.6, ("(n2) a hover pick right after a slow one", ratios)
    set_mode("なし")
    nav.ctl("表示スタイル").locator("select").select_option(label="陰影＋稜線")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    print("(n2) ok")

    # ================= (o) the heatmap's value: the pick's name wins in 計測 ========
    title = page.locator(".lil-gui .lil-title", has_text=re.compile("^肉厚$")).first
    title.click()
    nav.wait_gui_idle()
    nav.ctl("ヒートマップ").locator("input").click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=120000)
    hover(on(PLATE_TOP))
    t = tip_text("(o) なし with the heatmap")
    assert re.fullmatch(r"\d+\.\d+ mm|データなし", t), ("the value in なし", t)
    set_mode("計測")
    hover((project(PLATE_TOP)[0] + 1, project(PLATE_TOP)[1]))
    t = tip_text("(o) 計測 with the heatmap")
    assert t.startswith("plate · 面#"), ("the pick's name wins in 計測", t)
    set_mode("なし")
    assert "肉厚ヒートマップ表示中" in hud(), ("the heatmap line is back", hud())
    nav.ctl("ヒートマップ").locator("input").click()
    title.click()
    nav.wait_gui_idle()
    print("(o) ok")

    # ================= (p) a mesh model: nothing to preselect ========================
    nav.load(STL)
    set_mode("計測")
    assert hud() == MESH_HINT, hud()
    plain = plain_frame()
    xy = nav.centre()
    assert pick(xy), "the plate under the middle of the view"
    hover(xy)
    assert_no_tip("mesh model, 計測")
    same_frame(frame(), plain, "(p) mesh model, 計測")
    set_mode("注記")
    hover((xy[0] + 1, xy[1]))
    assert_no_tip("mesh model, 注記")
    same_frame(frame(), plain, "(p) mesh model, 注記")
    set_mode("なし")
    print("(p) ok")

    # ================= (q) a 2D drawing: no highlight, no label, its own lines =======
    nav.load(DXF, wait_text="2D図面")
    drawing = hud()
    set_mode("計測")
    assert hud() == drawing, ("a drawing keeps its own status line", hud())
    box = page.locator("#viewport2d").bounding_box()
    hover((box["x"] + box["width"] / 2, box["y"] + box["height"] / 2))
    assert_no_tip("2D drawing")
    set_mode("なし")
    print("(q) ok")

    # ================= (r) a mode kept through a load: its hint after the summary ===
    set_mode("計測")
    nav.load(STEP)
    line = hud()
    print("(r) loaded in 計測:", line)
    assert "tris" in line and line.endswith(" — " + MEASURE_HINT), line
    set_mode("なし")
    assert hud() == line[: -len(" — " + MEASURE_HINT)], ("(r) back to the summary", hud())
    set_mode("注記")
    nav.load(STL)
    assert hud().endswith(" — " + NOTE_HINT), hud()
    set_mode("計測")  # a mesh model: the click only says it cannot measure
    assert hud() == MESH_HINT, hud()
    set_mode("なし")
    print("(r) ok")


if __name__ == "__main__":
    main()
