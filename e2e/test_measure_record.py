"""E2E: the 計測 list as a record to copy (issue #23 item 8).

- A row reads its value first, with its unit ("20.000 mm", "⌀8.000 mm"), a mark
  of its kind, and what was measured on a second line ("cavity_block 面#6 ↔
  plate 面#6"); a note is its own text. The 3D labels say mm too (a note's
  does not).
- A row's copy and the head's すべてコピー put tab-separated lines on the
  clipboard (種類, 値, 単位, 対象 A, 対象 B): Excel pastes them into cells. A
  diameter's 値 is the bare number. The copy works from the keyboard too.
- The × stays the row's only button (other scripts press "the row's button").
- The row under the pointer lights its label (class hot) and its points (the
  preselection's cyan, read off the canvas); the label under the pointer lights
  its row. A label takes no clicks: a click on it picks the model under it.
- The values can be selected (a double-click takes the number).
- Entries saved before this change (the sidecar's form did not change) show
  the same way, and one whose text is not a measurement's shows as it is.

Oracles: __cadPick at the clicked points (the face ids in the rows), the parts
of mini_mold (make_step_assembly.py: pins r 4), the clipboard itself, canvas
pixels at the projected points, DOM classes and text.
"""
import base64
import io
import math
import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

import gui_common

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
BLOCK_TOP = (50, 30, 35)
PLATE_TOP = (90, 10, 15)
NOTE_AT = (62, 40, 35)  # on the block's top too, away from the distance's points
# pin 2 (x 75, y 30, r 4, z 15..40): its sides toward the camera (from +X, -Y; pin 1 is behind the block)
PIN_SIDES = ((75, 26, 27), (79, 30, 27), (77.83, 27.17, 27))
MARKER = (0xFF, 0xB0, 0x20)
HOT = (0x55, 0xD6, 0xFF)
HEAD = "種類\t値\t単位\t対象 A\t対象 B"
# saved before the change: a distance, an edge's diameter, a note, and text that is no measurement
OLD_ENTRIES = [
    {"text": "面#6 ↔ 面#3 : 12.500", "labelText": "12.500", "labelPos": [60, 20, 25],
     "line": [[60, 20, 15], [60, 20, 35]], "markers": [[60, 20, 15], [60, 20, 35]]},
    {"text": "円エッジ ⌀4.000 (L=12.566)", "labelText": "⌀4.000", "labelPos": [25, 30, 40]},
    {"text": "📌 古い注記", "labelText": "古い注記", "labelPos": [50, 30, 35], "markers": [[50, 30, 35]], "annotation": True},
    {"text": "手で書いた行", "labelText": "", "labelPos": [0, 0, 0]},
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    saved = {"entries": []}

    def sidecar(route):
        if route.request.method == "GET":
            route.fulfill(json={"version": 1, "entries": saved["entries"]})
        else:
            route.fulfill(json={})

    page.route("**/sidecar", sidecar)

    def load():
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        page.set_input_files("#file-input", STEP)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('tris')", timeout=60000)
        page.wait_for_timeout(500)

    def project(q):
        xy = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(q))
        return (xy["x"], xy["y"])

    def pick(q):
        return page.evaluate("([x, y]) => window.__cadPick(x, y)", list(project(q)))

    def rows():
        return page.evaluate(
            """() => [...document.querySelectorAll('#measure-list li')].map(li => ({
                 kind: li.dataset.kind, icon: !!li.querySelector('.m-icon svg'),
                 value: li.querySelector('.m-value')?.textContent ?? null,
                 unit: li.querySelector('.m-unit')?.textContent ?? null,
                 what: li.querySelector('.m-what')?.textContent ?? null,
                 buttons: [...li.querySelectorAll('button')].map(b => b.textContent),
                 hot: li.classList.contains('hot') }))"""
        )

    def clipboard():
        return page.evaluate("navigator.clipboard.readText()")

    def pixel(xy):
        url = page.evaluate(
            "new Promise(r => requestAnimationFrame(() => r(document.querySelector('#viewport canvas').toDataURL())))"
        )
        img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
        c = page.evaluate("(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect(); return [r.left, r.top] })()")
        return img.getpixel((round(xy[0] - c[0]), round(xy[1] - c[1])))

    def near(px, rgb, tol=40):
        return all(abs(a - b) <= tol for a, b in zip(px, rgb))

    def label(text):
        return page.locator(".dim-label, .note-label", has_text=text).first

    def view():
        return page.evaluate("window.__cadView()")

    def settled_view():
        """the camera once its damping has come to rest"""
        prev = view()
        for _ in range(30):
            page.wait_for_timeout(100)
            cur = view()
            if cur["position"] == prev["position"]:
                return cur
            prev = cur
        return prev

    def turned(a, b):
        """degrees between the two views' directions from their targets"""
        da = [x - t for x, t in zip(a["position"], a["target"])]
        db = [x - t for x, t in zip(b["position"], b["target"])]
        dot = sum(x * y for x, y in zip(da, db))
        na, nb = (sum(x * x for x in d) ** 0.5 for d in (da, db))
        return math.degrees(math.acos(max(-1.0, min(1.0, dot / (na * nb)))))

    load()
    page.evaluate("navigator.clipboard.writeText('')")

    # ---- 1. a distance, a diameter, a note
    hb, hp = pick(BLOCK_TOP), pick(PLATE_TOP)
    assert hb and hb["kind"] == "face" and hp and hp["kind"] == "face", (hb, hp)
    gui_common.set_mode(page, "計測")
    for q in (BLOCK_TOP, PLATE_TOP):
        page.mouse.click(*project(q))
        page.wait_for_timeout(300)
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 1", timeout=15000)
    side = next((q for q in PIN_SIDES if (h := pick(q)) and h["kind"] == "face" and abs(h["point"][2] - q[2]) < 0.5
                 and abs(((h["point"][0] - 75) ** 2 + (h["point"][1] - 30) ** 2) ** 0.5 - 4) < 0.3), None)
    assert side, "no side of pin 2 faces the camera"
    page.mouse.click(*project(side))
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 2", timeout=15000)
    page.keyboard.press("Escape")  # its first point
    gui_common.set_mode(page, "注記")
    page.mouse.click(*project(NOTE_AT))
    page.wait_for_selector(".note-input", timeout=5000)
    page.keyboard.type("ゲート位置")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 3", timeout=5000)
    gui_common.set_mode(page, "なし")
    page.wait_for_timeout(300)
    a, b = f"cavity_block 面#{hb['id']}", f"plate 面#{hp['id']}"
    got = rows()
    print("1 rows", got)
    want = [
        ("distance", "20.000 mm", " mm", f"{a} ↔ {b}"),
        ("diameter", "⌀8.000 mm", " mm", "core_pin 円筒面"),
        ("note", "ゲート位置", None, None),
    ]
    assert [(r["kind"], r["value"], r["unit"], r["what"]) for r in got] == want, got
    assert all(r["icon"] for r in got), "1 every row has its kind's mark"
    tops = page.evaluate(
        "[...document.querySelectorAll('#measure-list li')].filter(li => li.querySelector('.m-what'))"
        ".map(li => [li.querySelector('.m-value').getBoundingClientRect().top, li.querySelector('.m-what').getBoundingClientRect().top])"
    )
    assert len(tops) == 2 and all(v < w for v, w in tops), ("1 the value first, what was measured under it", tops)
    assert all(r["buttons"] == ["×"] for r in got), ("1 the × is the row's only button", got)
    assert page.locator("#measure-count").inner_text() == "3"
    # the 3D labels: lengths with mm, the note as written
    assert label("20.000").inner_text() == "20.000 mm" and label("⌀8.000").inner_text() == "⌀8.000 mm"
    assert label("ゲート位置").inner_text() == "ゲート位置"

    # ---- 2. copying: a row, all of them, from the keyboard
    line_dist = f"距離\t20.000\tmm\t{a}\t{b}"
    line_dia = "直径\t8.000\tmm\tcore_pin 円筒面\t"
    line_note = "注記\tゲート位置\t\t\t"
    copy1 = page.locator("#measure-list li").nth(0).locator(".m-copy")
    copy1.click()
    page.wait_for_timeout(100)
    assert clipboard() == line_dist, ("2 a row's copy", clipboard())
    assert "done" in copy1.get_attribute("class"), "2 the copy shows it was done"
    page.click("#measure-copy-all")
    page.wait_for_timeout(100)
    text = clipboard()
    assert text == "\n".join([HEAD, line_dist, line_dia, line_note]), ("2 すべてコピー", text)
    assert all(len(line.split("\t")) == 5 for line in text.split("\n")), "2 five cells a line"
    assert "コピーした" in page.inner_text("#measure-copy-all")
    page.evaluate("navigator.clipboard.writeText('')")
    page.locator("#measure-list li").nth(1).locator(".m-copy").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(100)
    assert clipboard() == line_dia, ("2 the copy from the keyboard", clipboard())
    print("2 copy ok")

    # ---- 3. the row and its label: hover one, the other lights
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    pts = [project(BLOCK_TOP), project(PLATE_TOP)]
    before = [pixel(q) for q in pts]
    assert all(near(c, MARKER) for c in before), ("3 the points before", before)
    row1 = page.locator("#measure-list li").nth(0)
    row1.hover()
    page.wait_for_timeout(300)
    assert "hot" in label("20.000").get_attribute("class"), "3 the row lights its label"
    hot = [pixel(q) for q in pts]
    assert all(near(c, HOT) for c in hot), ("3 the row lights its points", hot)
    assert not any("hot" in (label(t).get_attribute("class") or "") for t in ("⌀8.000", "ゲート位置")), "3 one entry only"
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    assert all(near(pixel(q), MARKER) for q in pts) and "hot" not in label("20.000").get_attribute("class"), "3 back"
    box = label("20.000").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(300)
    assert [r["hot"] for r in rows()] == [True, False, False], ("3 the label lights its row", rows())
    page.mouse.move(640, 790)  # the canvas, clear of every label
    page.wait_for_timeout(300)
    assert not any(r["hot"] for r in rows()), "3 off the label"
    # a label takes no pointer: a click on it picks the model under it (a first
    # point), and a drag from it turns the view
    gui_common.set_mode(page, "計測")
    mid = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.click(*mid)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    page.keyboard.press("Escape")
    gui_common.set_mode(page, "なし")
    v0 = settled_view()
    page.mouse.move(*mid)
    page.mouse.down()
    page.mouse.move(mid[0] + 120, mid[1], steps=6)
    page.mouse.up()
    a_turn = turned(v0, settled_view())
    assert a_turn > 10, ("3 a drag from a label must turn the view", a_turn)
    print("3 linking ok")

    # ---- 4. a value can be selected
    r = page.evaluate(
        """() => { const t = document.querySelector('#measure-list li .m-value').firstChild
             const i = t.data.indexOf('20.000'); const r = document.createRange()
             r.setStart(t, i); r.setEnd(t, i + 6)
             const b = r.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom] }"""
    )
    page.mouse.dblclick((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
    assert page.evaluate("getSelection().toString()") == "20.000", page.evaluate("getSelection().toString()")
    page.evaluate("getSelection().removeAllRanges()")

    # ---- 5. entries saved before the change
    saved["entries"] = OLD_ENTRIES
    load()
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 4", timeout=10000)
    got = [(r["kind"], r["value"], r["what"]) for r in rows()]
    print("5 old rows", got)
    assert got == [
        ("distance", "12.500 mm", "面#6 ↔ 面#3"),
        ("diameter", "⌀4.000 mm", "円エッジ (L=12.566)"),
        ("note", "古い注記", None),
        ("other", "手で書いた行", None),
    ], got
    page.click("#measure-copy-all")
    page.wait_for_timeout(100)
    assert clipboard().split("\n")[1:] == [
        "距離\t12.500\tmm\t面#6\t面#3",
        "直径\t4.000\tmm\t円エッジ (L=12.566)\t",
        "注記\t古い注記\t\t\t",
        "\t\t\t手で書いた行\t",
    ], clipboard()

    page.screenshot(path="/tmp/cad_viewer_measure_record.png")
    errors = [e for e in errors if "Failed to load resource" not in e]
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("MEASURE RECORD E2E OK")
    browser.close()
