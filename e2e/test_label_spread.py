"""E2E: the measurements' labels never cover one another (issue #23, "あとで").

Three measurements of the same two points put three labels on one spot. The
first stays where its line's middle is; each later one moves down, below the
labels it would cover, in the order they were made (so a label does not jump
about while the view turns). A label on its own is not moved.

- no two labels overlap (2 px apart at least), also after the view turns
- the first label stays centred on its anchor; the others sit under it
- with the first one deleted, the next takes its place at the anchor
- a diameter's label elsewhere stays on its own anchor

Oracles: the labels' DOM rects, __cadProject of the anchors (the line's
middle on the block's top click, the pin's rim), __cadPick for the clicks.
"""
from nav_common import nav_session

import gui_common

BLOCK_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)

with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    n.load(n.paths["step"])
    gui_common.set_mode(page, "計測")
    hit = n.pick(n.project(BLOCK_TOP))
    bx, by = hit["point"][0], hit["point"][1]
    anchor3d = (bx, by, 25)  # the line from the block's top click down to the plate (z 35 to 15): its middle

    def labels():
        return page.evaluate(
            "[...document.querySelectorAll('.dim-label')].map(l => { const r = l.getBoundingClientRect();"
            " return { text: l.textContent, l: r.left, t: r.top, r: r.right, b: r.bottom } })"
        )

    def overlaps(a, b, gap=1.5):
        return a["l"] < b["r"] + gap and a["r"] > b["l"] - gap and a["t"] < b["b"] + gap and a["b"] > b["t"] - gap

    def centre(x):
        return ((x["l"] + x["r"]) / 2, (x["t"] + x["b"]) / 2)

    def check_spread(tag):
        ls = labels()
        for i in range(len(ls)):
            for j in range(i + 1, len(ls)):
                assert not overlaps(ls[i], ls[j]), (tag, "labels overlap", ls[i], ls[j])
        return ls

    for _ in range(3):
        for q in (BLOCK_TOP, PLATE_TOP):
            page.mouse.click(*n.project(q))
            page.wait_for_timeout(300)
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 3", timeout=15000)
    page.mouse.move(5, 795)
    n.settle()

    # ---- 1. spread: the first on its anchor, the others under it, none overlapping
    ls = check_spread("1")
    assert [x["text"] for x in ls] == ["20.000 mm"] * 3, ls
    a = n.project(anchor3d)
    c0 = centre(ls[0])
    assert abs(c0[0] - a[0]) <= 2 and abs(c0[1] - a[1]) <= 2, ("1 the first label on its anchor", c0, a)
    assert ls[0]["t"] < ls[1]["t"] < ls[2]["t"], ("1 the later ones under it, in order", ls)
    assert all(abs(x["l"] - ls[0]["l"]) <= 0.5 for x in ls), ("1 straight down", ls)
    print("1 spread", [round(x["t"]) for x in ls], "anchor", [round(v) for v in a])

    # ---- 2. the view turns: still none overlapping
    for _ in range(6):
        page.keyboard.press("ArrowLeft")
    n.settle()
    check_spread("2 turned")
    n.click_button("等角")
    n.settle()

    # ---- 3. the first deleted: the next takes the anchor
    page.locator("#measure-list li").nth(0).locator("button").click()
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 2", timeout=5000)
    page.mouse.move(5, 795)
    n.settle()
    ls = check_spread("3")
    a = n.project(anchor3d)
    c0 = centre(ls[0])
    assert abs(c0[0] - a[0]) <= 2 and abs(c0[1] - a[1]) <= 2, ("3 the next on the anchor", c0, a)

    # ---- 3b. the stack near the view's bottom: the later labels go above, all
    #      inside the view (Codex on #43: they were pushed off it)
    canvas = page.evaluate("(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect(); return [r.top, r.bottom] })()")
    page.locator("#measure-list li").nth(0).locator("button").click()  # back to one... then two more
    for _ in range(2):
        for q in (BLOCK_TOP, PLATE_TOP):
            page.mouse.click(*n.project(q))
            page.wait_for_timeout(300)
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 3", timeout=15000)
    page.mouse.move(5, 795)
    n.settle()
    # slide the view (Shift + an arrow) until the anchor is 30 px above the view's bottom
    first = lambda: labels()[0]
    key = "Shift+ArrowUp"
    b0 = first()["b"]
    page.keyboard.press(key)
    n.settle()
    if first()["b"] < b0:
        key = "Shift+ArrowDown"
    for _ in range(60):
        if first()["b"] >= canvas[1] - 30:
            break
        page.keyboard.press(key)
        n.settle()
    ls = check_spread("3b")
    print("3b near the bottom", [round(x["t"]) for x in ls], "view bottom", round(canvas[1]))
    assert ls[0]["b"] >= canvas[1] - 45, ("3b the anchor must be near the bottom", ls[0], canvas)
    assert all(x["t"] >= canvas[0] - 0.5 and x["b"] <= canvas[1] + 0.5 for x in ls), ("3b labels off the view", ls, canvas)
    assert ls[1]["b"] <= ls[0]["t"] and ls[2]["b"] <= ls[1]["t"], ("3b the later ones above, in order", ls)
    n.click_button("等角")
    page.keyboard.press("f")
    n.settle()

    # ---- 4. a label on its own stays on its own anchor (the pin's ⌀, on its rim)
    rim = (75, 26, 40)
    page.mouse.click(*n.project(rim))
    page.wait_for_function("[...document.querySelectorAll('.dim-label')].some(l => l.textContent.startsWith('⌀'))", timeout=15000)
    page.keyboard.press("Escape")  # its first point
    page.mouse.move(5, 795)
    n.settle()
    dia = [x for x in check_spread("4") if x["text"].startswith("⌀")][0]
    centre_info = page.evaluate(
        "() => { const l = [...document.querySelectorAll('.dim-label')].find(l => l.textContent.startsWith('⌀')); return l.style.marginTop }"
    )
    assert centre_info in ("", "0px"), ("4 a label on its own is not moved", centre_info, dia)
    gui_common.set_mode(page, "なし")
    print("LABEL SPREAD E2E OK")
