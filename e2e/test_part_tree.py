"""E2E: the part tree is where work on single parts starts (issue #23 item 11).

- each row has a mark in the colour the 3D view draws the part in; the two
  parts named core_pin get the numbers 1 and 2, down the tree (the file's
  order: the pin at x 25 first)
- the row under the pointer highlights its part in the 3D view, only while
  the pointer is on it; a press on the row ends it until the pointer moves
  again; the panel keeps its size (the fit avoids it)
- in mode なし, the part under the cursor in the 3D view marks its row (not in
  計測 / 注記, not off the model; it follows a still cursor when the view turns)
- これだけ表示 hides the other parts, 全部表示 shows them all again
- この部品へ寄る frames just that part in the free area, as 全体表示 frames the
  model (a group: its shown parts); not a hidden part; H fits the same part
  again into the larger area
- the tree folds from its header; the buttons are reached with Tab and work
  with Enter, and the row the keyboard is in highlights its part
- a saved image (PNG) never has the highlight
- IGES: the loose curves' mark is their amber; their row turns the lines cyan

Oracles (none from the code under test): the known shapes of
testdata/make_step_assembly.py (plate 100 x 60 x 15, core pins r4 at x 25 / 75,
y 30, z 15..40, the pin at x 25 first in the file, cavity block 30..70 x
15..45 x 15..35) and their colours as written there (linear RGB:
Quantity_TOC_RGB), the loose curves' amber of the spec, window.__cadProject /
__cadPick, canvas pixels (the mark's chromaticity against the drawn face's:
lighting scales a colour, it does not turn it), the DOM (boxes, texts,
computed styles, rects), nav_common's free-area rule for the fits, a saved
PNG.
"""
import re

from PIL import Image

from nav_common import LOOSE_IGES, MOLD, MOLD_NO_PLATE, nav_session

PLATE = ((0, 0, 0), (100, 60, 15))
PIN1 = ((21, 26, 15), (29, 34, 40))  # the first core_pin of the file: x 25
PIN2 = ((71, 26, 15), (79, 34, 40))
BLOCK = ((30, 15, 15), (70, 45, 35))
BOXES = {"plate": PLATE, "pin1": PIN1, "pin2": PIN2, "block": BLOCK}
# points on the parts' top faces, seen from the load view (checked by picks)
TOPS = {"plate": (90, 10, 15), "pin1": (25, 30, 40), "pin2": (75, 30, 40), "block": (50, 30, 35)}
# rows as (label text, number beside it)
ROWS = {"group": ("mini_mold", ""), "plate": ("plate", ""), "pin1": ("core_pin", "1"),
        "pin2": ("core_pin", "2"), "block": ("cavity_block", "")}
# the colours make_step_assembly.py writes (linear RGB)
FILE_RGB = {"plate": (0.6, 0.6, 0.62), "pin1": (0.8, 0.15, 0.1), "pin2": (0.8, 0.15, 0.1), "block": (0.15, 0.3, 0.75)}
CURVE = (0xE0, 0xB0, 0x50)  # loose curves are drawn amber (README; test_iges_sewing.py)
LIT = 40  # the sum of |channel change| a highlight makes at least
SAME = 4  # and that nothing else moves by more than


def srgb(c):
    """linear 0..1 -> sRGB 0..255"""
    v = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return round(255 * v)


def lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def chroma(rgb):
    """the colour without its brightness: linear r, g, b over their sum"""
    c = [lin(x) for x in rgb]
    s = sum(c)
    return [x / s for x in c]


def diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def parts_at(pt):
    """the parts whose boxes hold a picked point (two where parts touch)"""
    return [name for name, (lo, hi) in BOXES.items() if all(lo[i] - 0.05 <= pt[i] <= hi[i] + 0.05 for i in range(3))]


def part_of(pt):
    """the part whose box holds a picked point (the top points of TOPS: one part)"""
    names = parts_at(pt)
    return names[0] if len(names) == 1 else None


with nav_session() as n:
    page = n.page
    n.load(n.paths["step"])
    tree = page.locator("#tree-panel")
    labels = page.locator("#tree-panel label")

    def row_list():
        """(label text, the number beside the label) of every row, down the tree"""
        return [tuple(r) for r in page.evaluate(
            """() => [...document.querySelectorAll('#tree-panel label')].map(l =>
                 [l.textContent, l.parentElement.textContent.slice(l.textContent.length).trim()])"""
        )]

    def row(key):
        return labels.nth(row_list().index(ROWS[key])).locator("xpath=..")

    def box_states():
        return {k: tuple(page.evaluate("b => [b.checked, b.indeterminate]", row(k).locator("input").element_handle()))
                for k in ROWS}

    def button(key, title):
        return row(key).locator(f"button[title='{title}']")

    def panel_rect():
        return tree.evaluate("e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height] }")

    def median_rgb(xy, img, sx, sy, cl, ct):
        px = [img.getpixel((int((xy[0] - cl) * sx) + dx, int((xy[1] - ct) * sy) + dy)) for dx in (-2, 0, 2) for dy in (-2, 0, 2)]
        return tuple(sorted(p[i] for p in px)[len(px) // 2] for i in range(3))

    def rgb_at(pts):
        """the drawn colour around each page point (3 x 3 median of a 5 x 5 spot)"""
        n.settle()
        img = n.canvas_image()
        cl, ct, cw, ch = n.canvas_rect()
        sx, sy = img.width / cw, img.height / ch
        return {k: median_rgb(xy, img, sx, sy, cl, ct) for k, xy in pts.items()}

    def mark_rgb(key):
        rgb = row(key).locator("label i").evaluate("e => getComputedStyle(e).backgroundColor")
        return tuple(int(v) for v in re.findall(r"\d+", rgb)[:3])

    def opacity(loc):
        """the opacity an element is drawn with (its own times its ancestors')"""
        return loc.evaluate(
            "e => { let o = 1; for (; e; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o }"
        )

    def marked():
        """rows drawn with a background while the pointer is not on the tree (the 3D view's mark)"""
        return [tuple(r) for r in page.evaluate(
            """() => [...document.querySelectorAll('#tree-panel label')].map(l => l.parentElement)
                 .filter(r => getComputedStyle(r).backgroundColor !== 'rgba(0, 0, 0, 0)')
                 .map(r => [r.querySelector('label').textContent,
                            r.textContent.slice(r.querySelector('label').textContent.length).trim()])"""
        )]

    # ---- 1. rows, numbers, the count -------------------------------------------
    assert row_list() == list(ROWS.values()), row_list()
    # the label holds the bare name (other scripts find rows by it)
    assert page.locator("#tree-panel label span").all_text_contents() == [r[0] for r in ROWS.values()]
    assert page.inner_text("#tree-count") == "4", page.inner_text("#tree-count")
    for key, (name, num) in ROWS.items():
        shown = f"{name} {num}".strip()
        group = key == "group"
        assert button(key, "このグループだけ表示" if group else "これだけ表示").get_attribute("aria-label") == f"{shown} だけ表示"
        assert button(key, "このグループへ寄る" if group else "この部品へ寄る").get_attribute("aria-label") == f"{shown} へ寄る"
        # seen only on the row under the pointer (or the keyboard's)
        assert opacity(row(key).locator("button").first) == 0, (key, "buttons shown without hover")
    print("1 rows", row_list())

    # the parts on screen at the load view: each top point picks its own part
    pts = {k: n.project(v) for k, v in TOPS.items()}
    for k, xy in pts.items():
        hit = n.pick(xy)
        assert hit and part_of(hit["point"]) == k, ("top point", k, hit)
    away = (640, 60)  # empty canvas above the model, clear of the panels
    assert n.pick(away) is None
    page.mouse.move(*away)
    base = rgb_at(pts)

    # ---- 2. the colour marks -----------------------------------------------------
    for k in ("plate", "pin1", "pin2", "block"):
        mark = mark_rgb(k)
        want = tuple(srgb(c) for c in FILE_RGB[k])
        assert diff(mark, want) <= 6, ("2 the mark is the file's colour", k, mark, want)
        # the drawn top face has the mark's colour, only darker or lighter
        cm, cp = chroma(mark), chroma(base[k])
        assert max(abs(a - b) for a, b in zip(cm, cp)) <= 0.025, ("2 the mark is the drawn colour", k, mark, base[k], cm, cp)
    print("2 marks", {k: mark_rgb(k) for k in ("plate", "pin1", "block")}, "drawn", base)

    # ---- 3. the row under the pointer highlights its part, only while there ----
    r0 = panel_rect()
    for key, lit in (("pin1", {"pin1"}), ("pin2", {"pin2"}), ("plate", {"plate"}), ("block", {"block"}),
                     ("group", {"plate", "pin1", "pin2", "block"})):
        row(key).hover()
        now = rgb_at(pts)
        for k in pts:
            d = diff(now[k], base[k])
            assert (d >= LIT) if k in lit else (d <= SAME), ("3 hover", key, k, now[k], base[k])
        assert opacity(row(key).locator("button").first) == 1, ("3 the buttons show on hover", key)
        assert panel_rect() == r0, ("3 the panel changed its size on hover", key, r0, panel_rect())
        page.mouse.move(*away)
        now = rgb_at(pts)
        assert all(diff(now[k], base[k]) <= SAME for k in pts), ("3 the highlight stays after leaving", key, now, base)
    # leaving to the panel's own header ends it too
    row("pin2").hover()
    assert diff(rgb_at(pts)["pin2"], base["pin2"]) >= LIT
    page.locator("#tree-count").hover()
    assert diff(rgb_at(pts)["pin2"], base["pin2"]) <= SAME, "3 the highlight stays over the header"
    print("3 hover ok")

    # ---- 4. a press ends it until the pointer moves again -------------------------
    plate_box = row("plate").locator("input")
    plate_box.click()  # hidden; the pointer stays on the row
    assert n.pick(pts["plate"]) is None, "4 the plate must be hidden"
    plate_box.click()  # shown again
    assert diff(rgb_at(pts)["plate"], base["plate"]) <= SAME, "4 the highlight right after a click"
    bb = plate_box.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] / 2 + 3, bb["y"] + bb["height"] / 2)
    assert diff(rgb_at(pts)["plate"], base["plate"]) >= LIT, "4 a move on the row brings the highlight back"
    page.mouse.move(*away)
    print("4 press ok")

    # ---- 5. the part under the cursor in the 3D view marks its row (なし only) ----
    for k, xy in pts.items():
        page.mouse.move(*xy)
        n.settle()
        assert marked() == [ROWS[k]], ("5 3D hover", k, marked())
    page.mouse.move(*away)
    n.settle()
    assert marked() == [], ("5 off the model", marked())
    page.mouse.move(*pts["block"])
    n.settle()
    for mode in ("計測", "注記"):
        n.set_mode(mode)
        page.mouse.move(pts["block"][0] + 1, pts["block"][1])
        n.settle()
        assert marked() == [], ("5 no mark in", mode, marked())
    n.set_mode("なし")  # the cursor stays on the block: marked at once
    n.settle()
    assert marked() == [ROWS["block"]], ("5 back in なし", marked())
    # the view turns under a still cursor (on pin 2, away from the turn's
    # centre): the mark follows what is under it now
    page.mouse.move(*pts["pin2"])
    n.settle()
    assert marked() == [ROWS["pin2"]]
    seen = set()
    for _ in range(12):
        page.keyboard.press("ArrowRight")
        n.settle()
        n.settle()
        hit = n.pick(pts["pin2"])
        m = marked()
        if hit is None:
            assert m == [], ("5 turned view, off the model", m)
        else:
            # a pick snaps to a line of the part under the cursor: on the pin's
            # bottom edge that point is in the plate's box too
            want = [ROWS[k] for k in parts_at(hit["point"])]
            assert len(m) == 1 and m[0] in want, ("5 turned view", hit, m)
        seen.add(tuple(m))
    assert len(seen) >= 2, ("5 the turn must bring another part (or none) under the cursor", seen)
    page.mouse.move(*away)
    n.load(n.paths["step"])  # back to the load view
    pts = {k: n.project(v) for k, v in TOPS.items()}
    page.mouse.move(*away)
    base = rgb_at(pts)
    print("5 3D hover ok, seen", seen)

    # ---- 6. これだけ表示, 全部表示 -------------------------------------------------
    show_all = page.get_by_role("button", name="全部表示", exact=True)
    assert show_all.is_disabled(), "6 全部表示 with every part shown"
    row("pin2").hover()
    button("pin2", "これだけ表示").click()
    st = box_states()
    assert st == {"group": (True, True), "plate": (False, False), "pin1": (False, False),
                  "pin2": (True, False), "block": (False, False)}, ("6 boxes after これだけ表示", st)
    for k, xy in pts.items():
        hit = n.pick(xy)
        if k == "pin2":
            assert hit and part_of(hit["point"]) == "pin2", ("6 pin2 still there", hit)
        else:
            assert hit is None or part_of(hit["point"]) == "pin2", ("6 a hidden part is picked", k, hit)
    assert not show_all.is_disabled()
    show_all.click()
    st = box_states()
    assert all(v == (True, False) for v in st.values()), ("6 boxes after 全部表示", st)
    for k, xy in pts.items():
        hit = n.pick(xy)
        assert hit and part_of(hit["point"]) == k, ("6 shown again", k, hit)
    assert show_all.is_disabled()
    # a group: これだけ表示 on the whole assembly shows everything (nothing else to hide)
    row("plate").locator("input").click()
    row("group").hover()
    button("group", "このグループだけ表示").click()
    assert all(v == (True, False) for v in box_states().values()), ("6 group これだけ表示", box_states())
    page.mouse.move(*away)
    print("6 show only / show all ok")

    # ---- 7. この部品へ寄る ----------------------------------------------------------
    v0 = n.view()
    row("pin1").hover()
    button("pin1", "この部品へ寄る").click()
    n.settle()
    n.mark_fit()
    n.same_dir(v0, n.view())
    print("7 pin1", n.fill_check(*PIN1, "zoom to pin1", fallback=False))
    # H fits the same pin again into the area the hidden panels leave
    page.keyboard.press("h")
    n.settle()
    n.mark_fit()
    print("7 pin1, panels hidden", n.fill_check(*PIN1, "pin1 hidden panels"))
    page.keyboard.press("h")
    n.settle()
    n.mark_fit()
    n.fill_check(*PIN1, "pin1 panels back")
    # a group with a hidden part: its shown parts
    row("plate").locator("input").click()
    row("group").hover()
    button("group", "このグループへ寄る").click()
    n.settle()
    n.mark_fit()
    print("7 group without the plate", n.fill_check(*MOLD_NO_PLATE, "group zoom"))
    # a hidden part: no zoom, the view stays
    row("pin2").locator("input").click()
    zoom2 = row("pin2").locator("button[aria-label='core_pin 2 へ寄る']")
    assert zoom2.is_disabled(), "7 寄る on a hidden part"
    v1 = n.view()
    zoom2.click(force=True)
    zoom2.evaluate("b => b.click()")
    n.settle()
    v2 = n.view()
    assert v1["target"] == v2["target"] and v1["position"] == v2["position"], ("7 a hidden part moved the view", v1, v2)
    page.get_by_role("button", name="全部表示", exact=True).click()
    page.mouse.move(*away)
    print("7 zoom ok")

    # ---- 8. folding the tree --------------------------------------------------------
    fold = page.get_by_role("button", name="部品ツリー", exact=True)
    h_open = panel_rect()[3]
    assert fold.get_attribute("aria-expanded") == "true"
    fold.click()
    assert fold.get_attribute("aria-expanded") == "false"
    assert not labels.first.is_visible(), "8 rows shown on a folded tree"
    h_folded = panel_rect()[3]
    assert h_folded < 0.5 * h_open and h_folded < 50, ("8 the folded panel's height", h_open, h_folded)
    n.fit()
    n.fill_check(*MOLD, "folded tree", needs=("#tree-panel",))
    fold.click()
    assert labels.first.is_visible() and abs(panel_rect()[3] - h_open) <= 0.5, ("8 unfolded", h_open, panel_rect())
    assert all(v == (True, False) for v in box_states().values()), "8 folding changed the boxes"
    page.mouse.move(*away)
    print("8 fold ok", round(h_open), "->", round(h_folded))

    # ---- 9. keyboard ---------------------------------------------------------------
    n.load(n.paths["step"])
    pts = {k: n.project(v) for k, v in TOPS.items()}
    page.mouse.click(*away)  # Tab goes on from the canvas: the tree comes next
    base = rgb_at(pts)
    only_plate = button("plate", "これだけ表示")
    for _ in range(12):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.getAttribute('aria-label')") == "plate だけ表示":
            break
    else:
        raise AssertionError(("9 Tab never reached plate だけ表示", page.evaluate("document.activeElement.outerHTML")))
    assert opacity(only_plate) == 1, "9 the buttons show with the keyboard in the row"
    now = rgb_at(pts)
    assert diff(now["plate"], base["plate"]) >= LIT and diff(now["block"], base["block"]) <= SAME, ("9 keyboard highlight", now, base)
    page.keyboard.press("Enter")
    st = box_states()
    assert st["plate"] == (True, False) and not any(st[k][0] for k in ("pin1", "pin2", "block")), ("9 Enter: これだけ表示", st)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "plate へ寄る"
    v0 = n.view()
    page.keyboard.press("Enter")
    n.settle()
    n.mark_fit()
    n.same_dir(v0, n.view())
    print("9 plate by keyboard", n.fill_check(*PLATE, "plate by keyboard"))
    lit_now = rgb_at({"plate": n.project(TOPS["plate"])})["plate"]
    page.mouse.click(*away)  # the focus leaves the tree: no highlight
    plain = rgb_at({"plate": n.project(TOPS["plate"])})["plate"]
    assert diff(lit_now, plain) >= LIT, ("9 the highlight with the focus, none after", lit_now, plain)
    page.get_by_role("button", name="全部表示", exact=True).click()
    page.mouse.move(*away)
    print("9 keyboard ok")

    # ---- 10. a saved image has no highlight ------------------------------------------
    n.load(n.paths["step"])
    pts = {k: n.project(v) for k, v in TOPS.items()}
    page.mouse.move(*away)
    base = rgb_at(pts)
    row("pin1").hover()
    lit = rgb_at(pts)
    assert diff(lit["pin1"], base["pin1"]) >= LIT
    with page.expect_download(timeout=15000) as dl:
        # a click from script: the pointer stays on the row
        page.evaluate("document.querySelector(\"#toolbar button[data-action='png']\").click()")
    img = Image.open(dl.value.path()).convert("RGB")
    cl, ct, cw, ch = n.canvas_rect()
    saved = {k: median_rgb(xy, img, img.width / cw, img.height / ch, cl, ct) for k, xy in pts.items()}
    for k in pts:
        assert diff(saved[k], base[k]) <= 2 * SAME, ("10 the saved image", k, saved[k], base[k])
    assert diff(rgb_at(pts)["pin1"], lit["pin1"]) <= SAME, "10 the highlight must come back on screen"
    page.mouse.move(*away)
    print("10 png ok")

    # ---- 11. IGES: the loose curves' mark and highlight --------------------------------
    n.load(LOOSE_IGES)
    rows = row_list()
    assert rows == [("ソリッド", ""), ("曲線（3 本）", "")], rows
    curve_row = labels.nth(1).locator("xpath=..")
    mark = tuple(int(v) for v in re.findall(r"\d+", curve_row.locator("label i").evaluate(
        "e => getComputedStyle(e).backgroundColor"))[:3])
    assert diff(mark, CURVE) <= 3, ("11 the curves' mark", mark)
    solid_row = labels.nth(0).locator("xpath=..")
    solid_mark = tuple(int(v) for v in re.findall(r"\d+", solid_row.locator("label i").evaluate(
        "e => getComputedStyle(e).backgroundColor"))[:3])
    top = n.project((5, 10, 30))
    hit = n.pick(top)
    assert hit and abs(hit["point"][2] - 30) < 0.01, ("11 the solid's top", hit)
    drawn = rgb_at({"top": top})["top"]
    cm, cp = chroma(solid_mark), chroma(drawn)
    assert max(abs(a - b) for a, b in zip(cm, cp)) <= 0.025, ("11 the solid's mark", solid_mark, drawn)

    def amber_count():
        n.settle()
        img = n.canvas_image()
        return sum(1 for px in img.getdata() if max(abs(a - b) for a, b in zip(px, CURVE)) < 40)

    page.mouse.move(*away)
    a0 = amber_count()
    curve_row.hover()
    a1 = amber_count()
    page.mouse.move(*away)
    a2 = amber_count()
    print("11 amber pixels", a0, a1, a2)
    assert a0 > 100 and a1 < 0.2 * a0 and abs(a2 - a0) <= 0.02 * a0, ("11 the curves' highlight", a0, a1, a2)

    page.screenshot(path="/tmp/cad_viewer_part_tree.png")
    print("PART TREE E2E OK")
