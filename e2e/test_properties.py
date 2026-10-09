"""E2E: volume / area / weight panel (C1).

Expected values come from how the test models are built (make_step_assembly.py:
plate 100x60x15, two core pins r4 h25, cavity block 40x30x20; the STL boxes
written here), the resin table of the specification, and the camera state.
Needs the same servers as the other E2E scripts, with a backend that has
GET /api/models/{id}/properties.
"""
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
DXF = str(TESTDATA / "plate_drawing.dxf")
PREFS = "cad-viewer:props"

V = {"plate": 100 * 60 * 15, "core_pin": math.pi * 4**2 * 25, "cavity_block": 40 * 30 * 20}
A = {
    "plate": 2 * (100 * 60 + 100 * 15 + 60 * 15),
    "core_pin": 2 * math.pi * 4 * 25 + 2 * math.pi * 4**2,
    "cavity_block": 2 * (40 * 30 + 40 * 20 + 30 * 20),
}
PARTS = ["plate", "core_pin", "core_pin", "cavity_block"]
V_ALL = sum(V[n] for n in PARTS)
A_ALL = sum(A[n] for n in PARTS)
DENSITY = {"PMMA": 1.19, "PC": 1.20, "ABS": 1.05, "PP": 0.90, "PA66": 1.14, "POM": 1.41, "PS": 1.05}


def box_stl(path, size, top=True):
    """ASCII STL of a box at the origin; quads counter-clockwise seen from outside"""
    x, y, z = size
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    quads = [(0, 3, 2, 1), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    if top:
        quads.append((4, 5, 6, 7))
    out = ["solid b"]
    for a, b, c, d in quads:
        for t in ((a, b, c), (a, c, d)):
            out.append("facet normal 0 0 0\n outer loop")
            out += [f"  vertex {v[i][0]} {v[i][1]} {v[i][2]}" for i in t]
            out.append(" endloop\nendfacet")
    out.append("endsolid b")
    Path(path).write_text("\n".join(out))


def num(text):
    return float(text.replace(",", ""))


def near(shown, want, digits):
    return abs(shown - want) <= 0.5 * 10**-digits + 1e-9


def rects_overlap(a, b):
    return a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]


tmp = tempfile.mkdtemp(prefix="cad_props_")
CLOSED_STL = os.path.join(tmp, "box_closed.stl")
OPEN_STL = os.path.join(tmp, "box_open.stl")
box_stl(CLOSED_STL, (10, 20, 30))
box_stl(OPEN_STL, (10, 20, 30), top=False)
# A private copy of the mold (nine trailing newlines: its own content hash, so
# its own sidecar, emptied below). Other scripts leave measurements on the
# shared mini_mold.step; restored here they would lengthen the measurement list
# that the layout check in 5. lays out against the GUI.
STEP = os.path.join(tmp, "mini_mold.step")
Path(STEP).write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 9)
# 12: a private copy (its own hash, so its own model id and sidecar): the
# measurements it makes never touch mini_mold.step's sidecar
LAYOUT_STEP = os.path.join(tmp, "layout_mold.step")
Path(LAYOUT_STEP).write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 13)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        errors = []

        def new_page():
            pg = browser.new_page(viewport={"width": 1280, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(BASE_URL)
            pg.wait_for_load_state("networkidle")
            return pg

        page = new_page()
        r = page.request.post(
            f"{BASE_URL}/api/models",
            multipart={"file": {"name": "mini_mold.step", "mimeType": "application/octet-stream",
                                "buffer": Path(STEP).read_bytes()}},
            timeout=120000,
        )
        assert r.ok, ("upload", r.status, r.text())
        r = page.request.put(f"{BASE_URL}/api/models/{r.json()['id']}/sidecar", data={"version": 1, "entries": []})
        assert r.ok, ("empty sidecar", r.status, r.text())
        page.evaluate(f"localStorage.removeItem('{PREFS}')")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        def ctl(name):
            label = page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
            return page.locator(".lil-gui .lil-controller").filter(has=label).first

        def folder(name):
            return page.locator(".lil-gui").filter(has=page.locator(":scope > .lil-title", has_text=name)).first

        def load(path, wait_text="tris"):
            page.set_input_files("#file-input", path)
            page.wait_for_function(
                "([w, n]) => { const t = document.querySelector('#hud-info').textContent;"
                " return t.includes(w) && t.includes(n) }",
                arg=[wait_text, Path(path).name],
                timeout=60000,
            )

        def wait_values():
            page.wait_for_function(
                "document.querySelector('#props-total-volume')?.textContent.length > 0"
                " && !document.querySelector('#props-total').classList.contains('hidden')",
                timeout=60000,
            )

        def hidden(sel):
            return page.evaluate(
                "(s) => { const e = document.querySelector(s); return !e || e.offsetParent === null }", sel
            )

        def rows():
            out = {}
            for tr in page.locator("#props-parts tbody tr").all():
                cells = {c: tr.locator(f"td.{c}").inner_text() for c in ("name", "vol", "area", "mass")}
                out.setdefault(cells["name"], []).append(cells)
            return out

        def total():
            return {k: page.inner_text(f"#props-total-{k}") for k in ("volume", "area", "mass")}

        def check_total(vol, area, density):
            t = total()
            m = re.fullmatch(r"([\d,]+\.\d{3}) cm³（([\d,]+) mm³）", t["volume"])
            assert m, t
            assert near(num(m.group(1)), vol / 1000, 3) and near(num(m.group(2)), vol, 0), (t, vol)
            m = re.fullmatch(r"([\d,]+\.\d{2}) cm²", t["area"])
            assert m and near(num(m.group(1)), area / 100, 2), (t, area)
            m = re.fullmatch(r"([\d,]+\.\d{2}) g", t["mass"])
            assert m and near(num(m.group(1)), vol / 1000 * density, 2), (t, vol, density)

        def check_rows(names, density):
            r = rows()
            assert sorted(sum(([n] * len(v) for n, v in r.items()), [])) == sorted(names), r
            for name, cells_list in r.items():
                for cells in cells_list:
                    assert re.fullmatch(r"[\d,]+\.\d{3}", cells["vol"]), cells
                    assert near(num(cells["vol"]), V[name] / 1000, 3), cells
                    assert re.fullmatch(r"[\d,]+\.\d{2}", cells["area"]) and near(num(cells["area"]), A[name] / 100, 2), cells
                    assert re.fullmatch(r"[\d,]+\.\d{2}", cells["mass"]), cells
                    assert near(num(cells["mass"]), V[name] / 1000 * density, 2), (cells, density)

        def tree_box(name, nth=0):
            return page.locator("#tree-panel label", has_text=re.compile("^" + name + "$")).nth(nth).locator("input")

        def title():
            return page.inner_text("#props-total-title")

        # 1. nothing loaded: no panel; the folder starts closed
        assert hidden("#props-panel")
        assert "lil-closed" in (folder("体積・重量").get_attribute("class") or "")

        # 2. mini_mold: four rows, the total, PMMA
        load(STEP)
        wait_values()
        assert page.inner_text("#props-density") == "PMMA 1.19 g/cm³", page.inner_text("#props-density")
        check_rows(PARTS, 1.19)
        assert title() == "合計（表示中 4/4 部品）", title()
        check_total(V_ALL, A_ALL, 1.19)
        t = total()
        assert t == {"volume": "116.513 cm³（116,513 mm³）", "area": "234.58 cm²", "mass": "138.65 g"}, t
        assert hidden("#props-note"), page.inner_text("#props-note")
        print("2 mini_mold", t)

        # 3. hiding parts in the tree takes them out of the total
        tree_box("plate").click()
        check_rows(["core_pin", "core_pin", "cavity_block"], 1.19)
        assert title() == "合計（表示中 3/4 部品）"
        check_total(2 * V["core_pin"] + V["cavity_block"], 2 * A["core_pin"] + A["cavity_block"], 1.19)
        tree_box("core_pin").click()
        check_rows(["core_pin", "cavity_block"], 1.19)
        assert title() == "合計（表示中 2/4 部品）"
        check_total(V["core_pin"] + V["cavity_block"], A["core_pin"] + A["cavity_block"], 1.19)
        tree_box("mini_mold").click()  # the group: unchecks every child, one change event each
        assert hidden("#props-parts-wrap")
        assert title() == "表示中の部品なし"
        assert total() == {"volume": "—", "area": "—", "mass": "—"}, total()
        tree_box("mini_mold").click()
        assert title() == "合計（表示中 4/4 部品）"
        check_total(V_ALL, A_ALL, 1.19)

        # 4. resin and specific gravity
        folder("体積・重量").locator(":scope > .lil-title").click()
        resin = ctl("樹脂").locator("select")
        dens = ctl("比重").locator("input")

        def resin_shown():
            return resin.evaluate("s => s.options[s.selectedIndex].text")

        for name in ("PC", "PP"):
            resin.select_option(label=name)
            assert abs(float(dens.input_value()) - DENSITY[name]) < 1e-9, dens.input_value()
            assert page.inner_text("#props-density") == f"{name} {DENSITY[name]:.2f} g/cm³"
            check_total(V_ALL, A_ALL, DENSITY[name])
        dens.fill("1.234")
        dens.press("Enter")
        assert resin_shown() == "その他", resin_shown()
        assert page.inner_text("#props-density") == "比重 1.234 g/cm³"
        check_total(V_ALL, A_ALL, 1.234)
        resin.select_option(label="その他")
        assert abs(float(dens.input_value()) - 1.234) < 1e-9
        check_total(V_ALL, A_ALL, 1.234)
        before = page.evaluate("window.__cadView().position")
        dens.click()
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowRight")
        after = page.evaluate("window.__cadView().position")
        # tolerance: OrbitControls' damping rounds the position by ~1e-12 per frame
        assert all(abs(x - y) < 1e-6 for x, y in zip(after, before)), ("arrow keys in the field moved the view", before, after)
        page.evaluate("document.activeElement.blur()")

        # 5. layout: the panel stays clear of the GUI, the HUD and the measure list
        ctl("モード").locator("select").select_option("計測")
        n_before = page.locator("#measure-list li").count()
        for xyz in ((50, 30, 35), (90, 10, 15)):
            pt = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(400)
        page.wait_for_function(f"document.querySelectorAll('#measure-list li').length > {n_before}", timeout=10000)
        for state in ("open", "closed"):
            if state == "closed":
                folder("体積・重量").locator(":scope > .lil-title").click()
                page.wait_for_timeout(400)  # lil-gui animates the folder
            page.wait_for_timeout(200)
            boxes = {
                s: page.locator(s).first.bounding_box()
                for s in ("#props-panel", "#measure-panel", "#hud", ".lil-gui.lil-root")
            }
            names = list(boxes)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    assert not rects_overlap(boxes[names[i]], boxes[names[j]]), (state, names[i], names[j], boxes)
            pb = boxes["#props-panel"]
            assert pb["y"] + pb["height"] <= 900 - 12 + 0.5, (state, pb)
            tb = page.locator("#props-total").bounding_box()
            assert tb["y"] >= pb["y"] and tb["y"] + tb["height"] <= pb["y"] + pb["height"] + 0.5, (state, tb, pb)
            print("5 layout", state, {k: (round(b["y"]), round(b["y"] + b["height"])) for k, b in boxes.items()})
        hud_before = page.inner_text("#hud-info")
        n_mid = page.locator("#measure-list li").count()
        page.mouse.click(pb["x"] + pb["width"] / 2, pb["y"] + pb["height"] / 2)
        page.wait_for_timeout(400)
        assert page.locator("#measure-list li").count() == n_mid and page.inner_text("#hud-info") == hud_before
        while page.locator("#measure-list li").count() > n_before:
            page.locator("#measure-list li button").last.click()
            page.wait_for_timeout(100)
        ctl("モード").locator("select").select_option("なし")

        # 6. a section is only a view: the values are the whole parts'
        page.locator(".lil-gui .lil-title", has_text="断面").click()
        ctl("有効").locator("input").click()
        page.wait_for_timeout(200)
        check_total(V_ALL, A_ALL, 1.234)
        ctl("有効").locator("input").click()

        # 7. resin and gravity survive a reload
        page.wait_for_timeout(1000)  # let the sidecar save settle
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        load(STEP)
        wait_values()
        assert resin_shown() == "その他" and abs(float(dens.input_value()) - 1.234) < 1e-9
        assert page.inner_text("#props-density") == "比重 1.234 g/cm³"
        check_total(V_ALL, A_ALL, 1.234)
        folder("体積・重量").locator(":scope > .lil-title").click()
        resin.select_option(label="PMMA")
        assert page.inner_text("#props-density") == "PMMA 1.19 g/cm³"

        # 8. mesh formats: one part, no table, the unit note
        load(CLOSED_STL)
        wait_values()
        assert hidden("#props-parts-wrap") and hidden("#props-total-title")
        assert total() == {"volume": "6.000 cm³（6,000 mm³）", "area": "22.00 cm²", "mass": "7.14 g"}, total()
        assert "mm とみなす" in page.inner_text("#props-note")
        load(OPEN_STL)
        wait_values()
        assert total() == {"volume": "体積なし（閉じていない）", "area": "20.00 cm²", "mass": "—"}, total()

        # 9. drawings: no panel, no request
        requests = []
        page.on("request", lambda r: requests.append(r.url) if "/properties" in r.url else None)
        load(DXF, wait_text="2D図面")
        page.wait_for_timeout(300)
        assert hidden("#props-panel")
        assert not requests, requests
        page.close()

        # 10. a late answer for a model that was replaced is dropped. The load
        #     does not wait for the values (__cadPropsWait(0)): it shows 計算中…
        #     at once, whatever the machine's speed
        page = new_page()
        page.evaluate("window.__cadStallProperties(2000); window.__cadPropsWait(0)")
        page.set_input_files("#file-input", STEP)
        page.wait_for_function("document.querySelector('#props-status')?.textContent === '計算中…'", timeout=60000)
        load(DXF, wait_text="2D図面")
        page.wait_for_timeout(2500)
        assert hidden("#props-panel"), "a stale answer brought the panel back"
        page.close()

        # 10b. a replacement that fails before the teardown (a broken file) leaves
        #      the current model on screen: its late answer must still be shown
        page = new_page()
        bad = TESTDATA / "_broken_for_props.stl"
        bad.write_text("this is not an STL")
        try:
            page.evaluate("window.__cadStallProperties(2000); window.__cadPropsWait(0)")
            page.set_input_files("#file-input", STEP)
            page.wait_for_function("document.querySelector('#props-status')?.textContent === '計算中…'", timeout=60000)
            page.set_input_files("#file-input", str(bad))
            page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
            wait_values()  # the stalled answer for mini_mold arrives and is shown
            assert title() == "合計（表示中 4/4 部品）", title()
        finally:
            bad.unlink()
        errors[:] = [e for e in errors if "Failed to load resource" not in e]  # the broken file's 422
        page.close()

        # 11. a part without a volume is listed but not summed
        page = new_page()

        def one_open(route):
            resp = route.fetch()
            body = resp.json()
            pin = next(q for q in body["parts"] if q["name"] == "core_pin")
            pin.update(volume=None, closed=False, reason="open", centerOfMass=None)
            route.fulfill(response=resp, json=body)

        page.route("**/api/models/*/properties", one_open)
        load(STEP)
        wait_values()
        pins = rows()["core_pin"]
        open_pin = [c for c in pins if c["vol"] == "体積なし（閉じていない）"]
        assert len(open_pin) == 1 and open_pin[0]["area"] == "7.29" and open_pin[0]["mass"] == "—", pins
        assert title() == "合計（表示中 4/4 部品）"
        v_closed = V["plate"] + V["core_pin"] + V["cavity_block"]
        # volume / weight: closed parts only; area: every part with faces (the open pin too)
        check_total(v_closed, A["plate"] + 2 * A["core_pin"] + A["cavity_block"], 1.19)
        assert total()["volume"].startswith("115.257 cm³") and total()["area"] == "234.58 cm²", total()
        assert page.inner_text("#props-note") == "体積なしの 1 部品は体積・重量の合計に含めない（面積は含める）"

        page.close()

        # 11b. a part whose computation failed has no area either: it gets its
        #      own note (not 面積は含める) and stays out of every total
        page = new_page()

        def one_failed(route):
            resp = route.fetch()
            body = resp.json()
            pin = next(q for q in body["parts"] if q["name"] == "core_pin")
            pin.update(volume=None, area=None, closed=False, reason="failed", centerOfMass=None)
            route.fulfill(response=resp, json=body)

        page.route("**/api/models/*/properties", one_failed)
        load(STEP)
        wait_values()
        check_total(v_closed, A["plate"] + A["core_pin"] + A["cavity_block"], 1.19)
        assert total()["area"] == "227.29 cm²", total()
        assert page.inner_text("#props-note") == "計算できなかった 1 部品は合計に含めない", page.inner_text("#props-note")
        page.close()

        # 12. no parts table (計算中…, or a one-part model): the measure list
        #     takes the room up to the GUI before it scrolls; no table row is
        #     kept free. Window 800 px tall, the default GUI (表示 open).
        page = new_page()
        page.set_viewport_size({"width": 1280, "height": 800})
        page.evaluate("window.__cadStallProperties(120000)")  # 計算中… for the whole section
        load(LAYOUT_STEP)
        page.wait_for_function("document.querySelector('#props-status')?.textContent === '計算中…'")
        assert hidden("#props-parts-wrap")
        ctl("モード").locator("select").select_option("計測")
        page.evaluate("document.activeElement.blur()")
        a, b = (page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(q)) for q in ((90, 10, 15), (50, 30, 35)))

        def stack():
            return page.evaluate(
                """(() => { const r = s => document.querySelector(s).getBoundingClientRect()
                  const panel = document.querySelector('#measure-panel')
                  return { gui: r('.lil-gui.lil-root').bottom, list: r('#measure-panel').top, listH: r('#measure-panel').height,
                           props: r('#props-panel').top, propsBottom: r('#props-panel').bottom, scrolls: panel.scrollHeight > panel.clientHeight + 1,
                           vh: innerHeight } })()"""
            )

        added = 0  # entries restored from an earlier run (a cut-short cleanup) only fill the list sooner
        while True:
            n = page.locator("#measure-list li").count()
            page.mouse.click(a["x"], a["y"])
            page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')")
            page.mouse.click(b["x"], b["y"])
            page.wait_for_function(f"document.querySelectorAll('#measure-list li').length > {n}", timeout=10000)
            page.wait_for_timeout(100)
            added += 1
            st = stack()
            if st["scrolls"] or added >= 12:
                break
        print("12 no table:", added, "added,", st)
        assert st["scrolls"], ("the list never filled its room", st)
        assert st["listH"] < 0.4 * st["vh"] - 1, ("capped by 40vh, not by the room: the check needs a lower window", st)
        assert st["list"] < st["props"] and st["propsBottom"] <= st["vh"] - 12 + 0.5, st
        gap = st["list"] - (st["gui"] + 8)
        assert -0.5 <= gap <= 1.5, ("the list scrolls while room is left empty under the GUI", round(gap, 1), st)
        ctl("モード").locator("select").select_option("なし")
        while page.locator("#measure-list li").count() > 0:
            page.locator("#measure-list li button").last.click()
            page.wait_for_timeout(50)
        page.wait_for_timeout(1000)  # let the sidecar save (now empty) settle

        page.evaluate(f"localStorage.removeItem('{PREFS}')")
        page.screenshot(path="/tmp/cad_viewer_properties.png")
        if errors:
            print("PAGE ERRORS:", errors)
        assert not errors
        print("PROPERTIES E2E OK")
        browser.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
