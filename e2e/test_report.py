"""E2E: 確認の記録 (issue #59 P1 5): the review, a CSV, a page to print.

- 確認の記録… is in the operation panel with a file on screen (not on the
  empty screen). Its card sits left of the column, in the window; Esc and a
  click elsewhere close it. It says what the record will hold.
- The CSV (UTF-8 with a BOM, CRLF lines): the file's name and identity (the
  SHA-256 of its bytes), the app's version, the review as typed (a comma, a
  quote and a line break in the comment survive), the measure list, the
  問題の一覧 with its conditions, the 体積・重量 values; each value with
  where it comes from.
- The page to print opens in a new tab, named for the PDF; the same values,
  the review, the view's image. Printed to A4: a long table runs onto more
  pages with its head line again on each, and the image is on one page.
- Another file: the review starts blank again, the name stays. A tab the
  browser will not open: the page is saved as a file instead. A drawing: the
  measure list alone. A mesh model: its volume comes from its triangles. The
  unit: mm for a B-rep (read into mm); a mesh and a drawing keep the file's
  numbers, of a unit not said.
- A drawing's page waits for its image: a file opened meanwhile does not get
  into that record (its name, its identity are the drawing's).

Oracles (none from the code under test): mini_mold.step's make
(testdata/make_step_assembly.py): the plate 0..100 x 0..60 x 0..15 (90 cm³),
two pins of radius 4, z 15..40 (π·16·25 mm³ each), the block
30..70 x 15..45 x 15..35 (24 cm³); PMMA's specific gravity 1.19; the pin's
top (z 40) is 25 above the plate's top. The SHA-256 of the file's bytes
(hashlib), the version in frontend/package.json. Where the record must say
what the screen says, the screen's text (the lists, the panel) is read from
the page.
"""
import csv
import hashlib
import io
import json
import math
import re
import tempfile
from pathlib import Path

import gui_common
from nav_common import TESTDATA, empty_sidecar, nav_session

ROOT = Path(__file__).resolve().parent.parent
VERSION = json.loads((ROOT / "frontend" / "package.json").read_text())["version"]
PIN_VOL = math.pi * 4**2 * 25
TOTAL_VOL = 100 * 60 * 15 + 2 * PIN_VOL + 40 * 30 * 20  # mm³
PMMA = 1.19

tmp = tempfile.mkdtemp(prefix="cad_report_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 73)
MOLD_HASH = hashlib.sha256(mold.read_bytes()).hexdigest()[:32]

try:
    import fitz  # PyMuPDF: the PDF's text by page (here only, not in CI)
except ImportError:
    fitz = None


def blocks(text):
    """the CSV's tables: {title: [rows]} (a block is its title line, its rows, a blank line)"""
    rows = list(csv.reader(io.StringIO(text, newline="")))
    out, title = {}, None
    for r in rows:
        if not r or r == [""]:
            title = None
        elif title is None:
            title = r[0]
            out[title] = []
        else:
            out[title].append(r)
    return out


def table(block, head0):
    """a block's rows below its head line (the line starting head0) as dicts"""
    i = next(k for k, r in enumerate(block) if r[0] == head0)
    head = block[i]
    return head, [dict(zip(head, r)) for r in block[i + 1 :]]


with nav_session() as n:
    page = n.page
    report_ctl = lambda: gui_common.ctl(page, "確認の記録…")

    def open_card():
        report_ctl().locator("button").click()
        page.wait_for_selector("#report-pop:not(.hidden)")

    def card_shown():
        return page.evaluate("!document.querySelector('#report-pop').classList.contains('hidden')")

    def save_csv():
        with page.expect_download() as d:
            page.click("#report-csv")
        data = Path(d.value.path()).read_bytes()
        return d.value.suggested_filename, data

    assert not report_ctl().is_visible(), "no 確認の記録 on the empty screen"

    # ---- mini_mold: a measurement, the 問題の一覧, the 体積・重量
    empty_sidecar(page, mold)
    n.load(str(mold), props="live")
    assert report_ctl().is_visible()
    gui_common.set_mode(page, "計測")
    pin_top, plate_top = (75, 30, 40), (90, 50, 15)
    for xyz, part in ((pin_top, 2), (plate_top, 0)):
        p = n.pick(n.project(xyz))
        assert p and p["kind"] == "face" and abs(p["point"][2] - xyz[2]) < 1e-3, (xyz, p)
    page.mouse.click(*n.project(pin_top))
    n.settle()
    page.mouse.click(*n.project(plate_top))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離 25.000')", timeout=10000)
    gui_common.set_mode(page, "なし")
    gui_common.open_folder(page, "問題の一覧")
    gui_common.ctl(page, "一覧を出す").locator("input").check()
    page.wait_for_function("!!window.__cadCheck()", timeout=60000)
    page.wait_for_function("document.querySelector('#props-total-proj')?.textContent.includes('cm²')", timeout=60000)
    n.settle()
    check = page.evaluate("window.__cadCheck()")
    n_check = len(check["rows"]) + len(check["undecided"])
    list_value = page.inner_text("#measure-list li .m-value")
    panel = {k: page.inner_text(f"#props-total-{k}") for k in ("volume", "mass", "proj", "clamp")}

    # ---- the card
    open_card()
    pop = page.evaluate("(() => { const r = document.querySelector('#report-pop').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
    gui = page.evaluate("(() => { const r = document.querySelector('.lil-gui.lil-root').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
    vw, vh = page.evaluate("[innerWidth, innerHeight]")
    assert 0 <= pop[0] and pop[2] <= gui[0] and 0 <= pop[1] and pop[3] <= vh, ("left of the column, in the window", pop, gui, vh)
    what = page.inner_text("#report-what")
    assert what == f"載せるもの: 計測 1 件・問題の一覧 {n_check} 行・体積・重量・いまの画面", what
    page.keyboard.press("Escape")
    assert not card_shown(), "Esc closes the card"
    open_card()
    page.mouse.click(300, 600)
    n.settle()
    assert not card_shown(), "a click elsewhere closes it"
    open_card()
    comment = 'ピンの側面, "0°"\nお客さんに確認する'
    page.select_option("#report-status", label="要確認")
    page.fill("#report-by", "テスト 太郎")
    page.fill("#report-comment", comment)
    page.focus("#report-comment")
    page.keyboard.press("Escape")  # from inside a field too
    assert not card_shown(), "Esc in a field closes it"
    open_card()
    assert page.input_value("#report-comment") == comment, "the review stays while the file is on screen"
    print("1 card", what)

    # ---- the CSV
    name, data = save_csv()
    assert re.fullmatch(r"mini_mold_記録_\d{8}-\d{6}\.csv", name), name
    assert data.startswith(b"\xef\xbb\xbf"), "UTF-8 with a BOM (Excel reads the Japanese)"
    text = data[3:].decode("utf-8")
    # CRLF lines; a bare line break only inside the quoted comment
    assert text.count("\r\n") > 20 and text.replace("\r\n", "").count("\n") == comment.count("\n"), "CRLF lines"
    b = blocks(text)
    rec = dict(b["確認の記録"][1:])
    assert rec["ファイル"] == "mini_mold.step" and rec["識別（SHA-256 の先頭 32 桁）"] == MOLD_HASH, rec
    assert rec["アプリ"] == f"cad-viewer {VERSION}" and rec["単位"] == "mm" and rec["形式"] == "B-rep（STEP・IGES）", rec
    assert rec["判定"] == "要確認" and rec["確認者"] == "テスト 太郎" and rec["コメント"] == comment, rec
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", rec["確認日時"]), rec

    head, rows = table(b["計測（1 件）"], "種類")
    assert head == ["種類", "値", "単位", "対象 A", "対象 B", "ΔX", "ΔY", "ΔZ", "出どころ"], head
    (m,) = rows
    # the number as it is (every digit, mm: the record keeps the internal value), the list's 3 decimals of it
    assert m["種類"] == "距離" and abs(float(m["値"]) - 25) < 1e-9 and m["単位"] == "mm" and m["出どころ"] == "B-rep の真値", m
    assert list_value.startswith(f"{float(m['値']):.3f}"), ("the list's value", list_value, m)
    assert abs(float(m["ΔZ"]) - 25) < 1e-9 and m["ΔX"] == "0" and m["ΔY"] == "0", m

    title = next(t for t in b if t.startswith("問題の一覧"))
    assert title == f"問題の一覧（{n_check} 行）", title
    block = b[title]
    assert block[0] == ["条件: 肉厚 1.5 mm 未満（レイ法）・型開き +Z・勾配 1.0° 未満"], block[0]
    head, rows = table(block, "種類")
    kinds = [r["種類"] for r in rows]
    assert kinds.count("勾配不足") == 10 and kinds.count("反対側") == 4, ("the ten walls, the four bottoms", kinds)
    assert len(rows) == n_check and all(r["出どころ"] == "表示用メッシュの近似" for r in rows if r["種類"] != "判定できない"), rows
    assert all(r["値"] == "0.00" for r in rows if r["種類"] == "勾配不足"), rows

    head, rows = table(b["体積・重量"], "項目")
    props = {}
    for r in rows:
        props.setdefault(r["項目"], []).append(r)
    vol, mass = props["体積"][0], props["重量"][0]
    assert vol["値"] == f"{TOTAL_VOL / 1000:.3f}" and vol["単位"] == "cm³" and vol["出どころ"] == "B-rep の真値", vol
    assert mass["値"] == f"{TOTAL_VOL / 1000 * PMMA:.2f}" and mass["単位"] == "g", mass
    assert props["比重"][0]["値"] == "1.19" and props["比重"][0]["出どころ"] == "入力した値（PMMA）", props["比重"]
    # the screen's values, the same numbers (the panel groups the digits)
    assert panel["volume"].startswith(f"{float(vol['値']):,.3f} cm³"), (panel, vol)
    assert panel["mass"] == f"{float(mass['値']):,.2f} g", (panel, mass)
    proj = props["投影面積"][0]
    assert panel["proj"].startswith(f"{float(proj['値']):,.2f} cm²") and proj["出どころ"] == "表示用メッシュの近似（型開き Z）", (panel, proj)
    kn = next(r for r in props["型締力"] if r["単位"] == "kN")
    assert panel["clamp"].startswith(f"{float(kn['値']):,.1f} kN") and kn["出どころ"] == "入力した値からの目安", (panel, kn)
    head, rows = table(b["部品ごとの体積・重量"], "部品")
    by_part = sorted((r["部品"], r["体積 cm³"]) for r in rows)
    want = sorted([("plate", "90.000"), ("core_pin", f"{PIN_VOL / 1000:.3f}"), ("core_pin", f"{PIN_VOL / 1000:.3f}"), ("cavity_block", "24.000")])
    assert by_part == want, by_part
    assert [r[0] for r in b["部品（4）"][1:]] == ["plate", "core_pin", "core_pin", "cavity_block"], b["部品（4）"]
    print("2 csv", name, f"{len(text)} chars", vol["値"], mass["値"])

    # a cell Excel would run as a formula gets a ' first; a number stays a number
    fields = page.evaluate("async () => { const m = await import('/src/report.ts'); return ['=1+1', '@x', '-5.000', '+3', 'a,b'].map(m.csvField) }")
    assert fields == ["'=1+1", "'@x", "-5.000", "+3", '"a,b"'], fields

    # ---- the page to print
    with page.expect_popup() as pp:
        page.click("#report-page")
    tab = pp.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), timeout=10000)
    tab.wait_for_load_state()
    assert re.fullmatch(r"mini_mold_記録_\d{8}-\d{6}", tab.title()), tab.title()
    body = tab.inner_text("body")
    for s in (MOLD_HASH, "要確認", "テスト 太郎", "お客さんに確認する", f"cad-viewer {VERSION}", "25.000", f"{TOTAL_VOL / 1000:,.3f}"):
        assert s in body, (s, body[:400])
    shown_rows = tab.evaluate("[...document.querySelectorAll('section')].find(s => s.querySelector('h2').textContent.startsWith('問題の一覧')).querySelectorAll('tbody tr').length")
    assert shown_rows == n_check, (shown_rows, n_check)
    img = tab.evaluate("(() => { const i = document.querySelector('figure img'); return i && [i.naturalWidth, i.naturalHeight] })()")
    assert img and img[0] > 100 and img[1] > 100, img
    pdf = tab.pdf(format="A4", prefer_css_page_size=True)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    assert pages >= 1, pages
    # a long table: its rows run onto more pages, each with the head line again; the image on one page
    tab.evaluate(
        "(() => { const s = [...document.querySelectorAll('section')].find(s => s.querySelector('h2').textContent.startsWith('問題の一覧'));"
        " const tb = s.querySelector('tbody'); const rows = [...tb.children];"
        " for (let k = 0; k < 6; k++) for (const r of rows) tb.appendChild(r.cloneNode(true)) })()"
    )
    long_pdf = tab.pdf(format="A4", prefer_css_page_size=True)
    long_pages = len(re.findall(rb"/Type\s*/Page[^s]", long_pdf))
    assert long_pages > pages, ("the long table runs onto more pages", pages, long_pages)
    if fitz is not None:
        doc = fitz.open(stream=long_pdf, filetype="pdf")
        with_rows = 0
        for k, pg in enumerate(doc):
            words = pg.get_text("words")  # (x0, y0, x1, y1, word, ...)
            lines = {}
            for w in words:
                lines.setdefault(round(w[1]), []).append(w[4])
            ys = sorted(lines)
            row_ys = [y for y in ys if lines[y][0] in ("勾配不足", "反対側")]
            if not row_ys:
                continue
            with_rows += 1
            above = [y for y in ys if y < row_ys[0]]
            # the line just above the first row on a page is the table's head
            head_line = "".join(lines[above[-1]]) if above else ""
            assert head_line.startswith("種類値単位部品") and head_line.endswith("出どころ"), (k, [lines[y] for y in above[-2:]])
        assert with_rows >= 2, with_rows
        imgs = [(k, r) for k, pg in enumerate(doc) for info in pg.get_images() for r in pg.get_image_rects(info[0])]
        assert len(imgs) == 1, ("the image whole, on one page", imgs)
        print("3 page", tab.title(), f"{pages} page(s), the long one {long_pages}; head on every page with rows ({with_rows})")
    else:
        print("3 page", tab.title(), f"{pages} page(s), the long one {long_pages} (PyMuPDF not here: the pages' text not read)")
    tab.close()

    # ---- the tab cannot open: the page is saved as a file
    page.evaluate("window.__open = window.open; window.open = () => null")
    with page.expect_download() as d:
        page.click("#report-page")
    assert re.fullmatch(r"mini_mold_記録_\d{8}-\d{6}\.html", d.value.suggested_filename), d.value.suggested_filename
    html = Path(d.value.path()).read_text(encoding="utf-8")
    assert MOLD_HASH in html and "<img src=\"data:image/png;base64," in html
    page.evaluate("window.open = window.__open")
    assert "新しいタブを開けなかった" in page.inner_text("#hud-info"), page.inner_text("#hud-info")
    print("4 saved as a file", d.value.suggested_filename)

    # ---- another file: the review starts blank, the name stays; a mesh model's volume from its triangles
    page.keyboard.press("Escape")
    n.load(TESTDATA / "ribbed_plate.stl", props="live")
    page.wait_for_function("document.querySelector('#props-total-volume')?.textContent.includes('cm³')", timeout=60000)
    open_card()
    assert page.input_value("#report-status") == "none" and page.input_value("#report-comment") == "", "a new file: a blank review"
    assert page.input_value("#report-by") == "テスト 太郎", "the name stays"
    _, data = save_csv()
    b = blocks(data[3:].decode("utf-8"))
    rec = dict(b["確認の記録"][1:])
    assert rec["形式"] == "メッシュ（STL など）" and rec["判定"] == "未記入", rec
    assert rec["単位"].startswith("ファイルの数のまま"), ("a mesh's numbers are not said to be mm", rec["単位"])
    assert rec["識別（SHA-256 の先頭 32 桁）"] == hashlib.sha256((TESTDATA / "ribbed_plate.stl").read_bytes()).hexdigest()[:32]
    _, rows = table(b["体積・重量"], "項目")
    assert rows[0]["項目"] == "体積" and rows[0]["出どころ"] == "メッシュの三角形から", rows[0]
    assert b["問題の一覧"] == [["出していない（操作パネルの「問題の一覧」で出す）"]], b["問題の一覧"]
    print("5 mesh", rec["形式"], rows[0])
    page.keyboard.press("Escape")

    # ---- a drawing: its measure list alone
    n.load(TESTDATA / "plate_drawing.dxf", wait_text="2D 図面")
    open_card()
    assert page.inner_text("#report-what") == "載せるもの: 計測 0 件・いまの画面", page.inner_text("#report-what")
    _, data = save_csv()
    b = blocks(data[3:].decode("utf-8"))
    assert list(b) == ["確認の記録", "計測（0 件）"], list(b)
    rec = dict(b["確認の記録"][1:])
    assert rec["形式"] == "図面（DXF・DWG）" and rec["単位"].startswith("図面の数のまま"), rec
    print("6 drawing", list(b))

    # ---- the drawing's page waits for its image; a file opened meanwhile stays out of it
    dxf_hash = hashlib.sha256((TESTDATA / "plate_drawing.dxf").read_bytes()).hexdigest()[:32]
    page.evaluate(
        """async () => {
             const P = (await import('/src/drawing2d.ts')).Drawing2D.prototype
             const plain = P.snapshot
             window.__snapGo = null
             // the image of the drawing as it is now, handed over only when released
             P.snapshot = async function (bg) {
               const c = await plain.call(this, bg)
               await new Promise((go) => { window.__snapGo = go })
               return c
             }
           }"""
    )
    with page.expect_popup() as pp:
        page.click("#report-page")
    page.wait_for_function("!!window.__snapGo", timeout=10000)
    n.load(TESTDATA / "ribbed_plate.stl")  # opened while the image is being made
    page.evaluate("window.__snapGo()")
    tab = pp.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), timeout=10000)
    tab.wait_for_load_state()
    body = tab.inner_text("body")
    assert "plate_drawing.dxf" in body and dxf_hash in body and "ribbed_plate" not in body, body[:300]
    tab.close()
    print("7 the drawing's record, not the file opened meanwhile")
print("REPORT E2E OK")
