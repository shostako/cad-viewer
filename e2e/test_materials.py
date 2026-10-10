"""E2E: 材料と用途 (one material for the gravity, the 判定の基準 and the 記録).

The specification, written out here (not read from the code):
- 用途 and 材料 are the operation panel's first rows (a 3D model's). 射出成形
  (at first): the seven resins, PMMA at first. 一般: the eight metals, then
  the resins, SS400 at first; 抜き勾配, 問題の一覧, 型内圧 and the projected
  area / clamping force rows are not shown (and the list goes off).
- Each material starts at the general standards (docs/material-basis.md):
  STANDARD below. 判定の基準 follows the material at first (材料に合わせる):
  the 閾値 and the 必要な勾配 are the material's, the conditions name it and
  its basis. A value changed by hand: 手で決める; 材料に合わせる puts them back.
- The weight is the volume x the material's gravity; a gravity typed in 比重
  is 手入力 for that material (another material chosen drops it).
- 材料の基準 (材料's ✎, 問題の一覧's 基準を編集…): a row a material of the
  用途 (一般: 金属 and 樹脂 under their headings, a metal without a draft). An
  edited row is marked and its ↺ puts the standard back; 既定に戻す puts all
  back; nothing is kept until 保存; out of range is not saved, finer than the
  steps (0.001, 0.01 mm, 0.1°) saved at the step and said. 書き出す writes
  every material's saved values to a file; 読み込む… takes a file's into the
  rows (保存 keeps them); a file that is not one is said so.
- The 記録 says the 用途 and the material (with its values and basis); 一般's
  has no 問題の一覧.
- Everything survives a reload; what the app kept before materials (the
  体積・重量 resin, その他's gravity, the 判定の基準's edited rows) comes along.

Oracles (none from the code under test): STANDARD; mini_mold.step's make
(testdata/make_step_assembly.py: its volume, the ten vertical walls with no
draft, the four faces that look down); ribbed_plate.stl's (its ribs 1.2 mm
thick); the file's JSON as written here.
"""
import csv
import io
import json
import math
import re
import tempfile
from pathlib import Path

import gui_common
from nav_common import BASE_URL, TESTDATA, nav_session

STANDARD = {
    "PMMA": (1.19, 0.64, 0.5), "PC": (1.2, 1.0, 0.5), "ABS": (1.05, 1.14, 0.5), "PP": (0.9, 0.89, 0.5),
    "PA66": (1.14, 1.0, 0.5), "POM": (1.41, 0.76, 0.5), "PS": (1.05, 0.89, 0.5),
    "SS400": (7.85, 0.8, None), "S45C": (7.85, 0.8, None), "SUS304": (7.93, 0.8, None), "A5052": (2.68, 0.8, None),
    "A6061": (2.7, 0.8, None), "銅 C1100": (8.89, 0.8, None), "黄銅 C3604": (8.5, 0.8, None), "純チタン 2 種": (4.51, 0.8, None),
}
RESINS = ["PMMA", "PC", "ABS", "PP", "PA66", "POM", "PS"]
METALS = ["SS400", "S45C", "SUS304", "A5052", "A6061", "銅 C1100", "黄銅 C3604", "純チタン 2 種"]
PMMA_SOURCE = "Protolabs の肉厚の表（下端）・各社の勾配の最小・DuPont の厚肉"
PC_SOURCE = "Protolabs・Fictiv の肉厚（下端）・Covestro の勾配・DuPont の厚肉"
METAL_SOURCE = "Protolabs Network の切削の最小肉厚（推奨）"
V_ALL = 100 * 60 * 15 + 2 * math.pi * 4**2 * 25 + 40 * 30 * 20  # mm³: the plate, two pins, the block
RIBBED = TESTDATA / "ribbed_plate.stl"

tmp = Path(tempfile.mkdtemp(prefix="cad_materials_"))
mold = tmp / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 97)


def grams(density):
    return f"{V_ALL / 1000 * density:,.2f} g"


with nav_session() as n:
    page = n.page

    def ctl(name):
        return gui_common.ctl(page, name)

    def select_text(name):
        return ctl(name).locator("select").evaluate("s => s.options[s.selectedIndex].text")

    def options(name):
        return ctl(name).locator("select").evaluate("s => [...s.options].map(o => o.text)")

    def choose(name, label):
        ctl(name).locator("select").select_option(label=label)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        n.settle()

    def number(name):
        return float(ctl(name).locator("input").last.input_value())

    def shown(sel):
        return page.locator(sel).first.is_visible()

    def folder_shown(name):
        return page.evaluate(
            "n => [...document.querySelectorAll('.lil-gui .lil-title')].some(t => t.textContent.trim() === n && t.getClientRects().length > 0)",
            name,
        )

    def row_shown(name):
        return page.evaluate(
            "n => [...document.querySelectorAll('.lil-gui .lil-controller')].some(c => c.querySelector('.lil-name')?.textContent === n && c.getClientRects().length > 0)",
            name,
        )

    def mass():
        return page.inner_text("#props-total-mass")

    def conditions():
        return page.inner_text("#check-panel .check-conditions")

    def wait_conditions(text):
        page.wait_for_function(
            f"document.querySelector('#check-panel .check-conditions')?.textContent === {text!r}", timeout=60000
        )
        n.settle()
        return page.evaluate("window.__cadCheck()")

    def card_shown():
        return page.evaluate("!document.querySelector('#basis-pop').classList.contains('hidden')")

    def open_card(via="✎"):
        if via == "✎":
            page.click(".cv-material-edit")
        else:
            ctl("基準を編集…").locator("button").click()
        page.wait_for_selector("#basis-pop:not(.hidden)")

    def row(m):
        return page.locator(f"#basis-pop tr[data-material='{m}']")

    def card_rows():
        return page.evaluate("[...document.querySelectorAll('#basis-pop tbody tr[data-material]')].map(t => t.dataset.material)")

    def row_values(m):
        r = row(m)
        draft = r.locator(".basis-draft")
        return (
            float(r.locator(".basis-density").input_value()),
            float(r.locator(".basis-thin").input_value()),
            float(draft.input_value()) if draft.count() else None,
        )

    def edited(m):
        return "edited" in (row(m).get_attribute("class") or "")

    def record():
        ctl("確認の記録…").locator("button").click()
        with page.expect_download() as d:
            page.click("#report-csv")
        page.keyboard.press("Escape")
        return list(csv.reader(io.StringIO(Path(d.value.path()).read_bytes()[3:].decode("utf-8"), newline="")))

    def meta(recs, key):
        return next((r[1] for r in recs if r and r[0] == key), None)

    def basis_line(m, thin, draft, source):
        return f"肉厚 {thin} mm 未満（レイ法）・型開き +Z・勾配 {draft}° 未満・基準 {m}（根拠: {source}）"

    # ================= 射出成形, PMMA: the general standard from the start
    n.load(str(mold), props="live")
    page.wait_for_function("document.querySelector('#props-total-mass')?.textContent.endsWith(' g')", timeout=60000)
    rows = page.evaluate("[...document.querySelectorAll('.lil-gui.lil-root > .lil-children > .lil-controller .lil-name')].slice(0, 3).map(e => e.textContent)")
    assert rows == ["用途", "材料", "モード"], ("the first rows", rows)
    assert select_text("用途") == "射出成形" and select_text("材料") == "PMMA"
    assert options("材料") == RESINS, options("材料")
    gui_common.open_folder(page, "肉厚")
    gui_common.open_folder(page, "抜き勾配")
    assert number("閾値 (mm)") == 0.64 and number("必要な勾配 (°)") == 0.5, (number("閾値 (mm)"), number("必要な勾配 (°)"))
    assert page.inner_text("#props-density") == "PMMA 1.19 g/cm³" and mass() == grams(1.19), (page.inner_text("#props-density"), mass())
    gui_common.open_folder(page, "問題の一覧")
    assert select_text("判定の基準") == "材料に合わせる"
    # 厚肉 is test_thick_spots.py's: this list is the wall's and the draft's, as written
    ctl("厚肉を調べる").locator("input").uncheck()
    ctl("一覧を出す").locator("input").check()
    c = wait_conditions(basis_line("PMMA", "0.64", "0.5", PMMA_SOURCE))
    counts = page.inner_text("#check-panel .check-counts")
    assert counts.startswith("薄肉 0・勾配不足 10・反対側 4"), counts
    print("1 PMMA:", conditions())

    # ---- another material: its gravity and its standard
    choose("材料", "PC")
    wait_conditions(basis_line("PC", "1.0", "0.5", PC_SOURCE))
    assert number("閾値 (mm)") == 1.0 and page.inner_text("#props-density") == "PC 1.20 g/cm³" and mass() == grams(1.2), mass()

    # ---- a value by hand: 手で決める; 材料に合わせる puts the material's back
    inp = ctl("閾値 (mm)").locator("input").last
    inp.fill("1.3")
    inp.press("Enter")
    wait_conditions("肉厚 1.3 mm 未満（レイ法）・型開き +Z・勾配 0.5° 未満")
    assert select_text("判定の基準") == "手で決める"
    choose("判定の基準", "材料に合わせる")
    wait_conditions(basis_line("PC", "1.0", "0.5", PC_SOURCE))
    assert number("閾値 (mm)") == 1.0
    print("2 PC, by hand and back")

    # ---- a gravity by hand: 手入力 for PC (its 判定の基準 stays); another material drops it
    gui_common.open_folder(page, "体積・重量")
    dens = ctl("比重 (g/cm³)").locator("input")
    dens.fill("1.234")
    dens.press("Enter")
    page.evaluate("document.activeElement.blur()")
    n.settle()
    assert page.inner_text("#props-density") == "PC 1.234 g/cm³（手入力）" and mass() == grams(1.234), (page.inner_text("#props-density"), mass())
    assert select_text("材料") == "PC" and conditions() == basis_line("PC", "1.0", "0.5", PC_SOURCE)
    recs = record()
    weight = next(r for r in recs if r and r[0] == "比重")
    assert weight[1:] == ["1.234", "g/cm³", "入力した値（PC に手で）"], weight
    assert meta(recs, "用途") == "射出成形", meta(recs, "用途")
    assert meta(recs, "材料") == f"PC（一般的な基準: 比重 1.234（手入力）・肉厚の下限 1.0 mm・勾配 0.5°・厚肉 1.5 倍。根拠: {PC_SOURCE}）", meta(recs, "材料")
    choose("材料", "ABS")
    assert page.inner_text("#props-density") == "ABS 1.05 g/cm³" and float(dens.input_value()) == 1.05
    choose("材料", "PC")
    dens.fill("1.2")  # the material's own value: not 手入力
    dens.press("Enter")
    page.evaluate("document.activeElement.blur()")
    n.settle()
    assert page.inner_text("#props-density") == "PC 1.20 g/cm³", page.inner_text("#props-density")
    # a gravity by hand, then another 用途: its material is another, the gravity typed goes
    dens.fill("1.25")
    dens.press("Enter")
    page.evaluate("document.activeElement.blur()")
    n.settle()
    assert page.inner_text("#props-density") == "PC 1.25 g/cm³（手入力）", page.inner_text("#props-density")
    choose("用途", "一般")
    assert page.inner_text("#props-density") == "SS400 7.85 g/cm³" and mass() == grams(7.85), (page.inner_text("#props-density"), mass())
    choose("用途", "射出成形")
    assert page.inner_text("#props-density") == "PC 1.20 g/cm³", ("the gravity typed for PC went with the switch", page.inner_text("#props-density"))
    # 一般 took the list off; it stays off back in 射出成形
    assert not shown("#check-panel")
    gui_common.open_folder(page, "問題の一覧")
    ctl("一覧を出す").locator("input").check()
    wait_conditions(basis_line("PC", "1.0", "0.5", PC_SOURCE))
    print("3 gravity by hand")

    # ================= the card (射出成形: the resins), from the ✎ and from 基準を編集…
    open_card()
    assert card_rows() == RESINS, card_rows()
    for m in RESINS:
        assert row_values(m) == STANDARD[m], (m, row_values(m))
        assert not edited(m) and row(m).locator(".basis-reset").is_disabled(), m
    assert row("PMMA").locator(".basis-source").input_value() == PMMA_SOURCE
    page.keyboard.press("Escape")
    assert not card_shown(), "Esc closes the card"
    open_card(via="button")
    page.mouse.click(300, 600)
    n.settle()
    assert not card_shown(), "a click elsewhere closes it"
    open_card()
    page.click(".cv-material-edit")
    assert not card_shown(), "its ✎ again closes it"

    open_card()
    row("PC").locator(".basis-thin").fill("0")
    page.click("#basis-save")
    assert page.inner_text("#basis-note").startswith("保存しなかった: PC の値が範囲の外"), page.inner_text("#basis-note")
    row("PC").locator(".basis-thin").fill("1.555")
    row("PC").locator(".basis-source").fill("社内の目安（2026-10）")
    assert edited("PC") and not row("PC").locator(".basis-reset").is_disabled()
    page.click("#basis-save")
    assert page.inner_text("#basis-note") == "保存した（刻みに丸めた: PC の肉厚 1.555 → 1.56）", page.inner_text("#basis-note")
    assert row("PC").locator(".basis-thin").input_value() == "1.56"
    page.keyboard.press("Escape")
    wait_conditions(basis_line("PC", "1.56", "0.5", "社内の目安（2026-10）"))
    assert number("閾値 (mm)") == 1.56
    # an edited material's values in the 記録 are 直した値
    recs = record()
    assert meta(recs, "材料").startswith("PC（直した値: 比重 1.20・肉厚の下限 1.56 mm"), meta(recs, "材料")
    print("4 card: PC edited", conditions())

    # ---- ↺ and 既定に戻す: the standard back into the rows, kept by 保存
    open_card()
    row("PC").locator(".basis-reset").click()
    assert row_values("PC") == STANDARD["PC"] and not edited("PC")
    assert conditions() == basis_line("PC", "1.56", "0.5", "社内の目安（2026-10）"), "nothing kept before 保存"
    row("PS").locator(".basis-thin").fill("2")
    row("PC").locator(".basis-thin").fill("1.7")
    page.click("#basis-defaults")
    assert all(row_values(m) == STANDARD[m] and not edited(m) for m in RESINS)
    page.click("#basis-save")
    page.keyboard.press("Escape")
    wait_conditions(basis_line("PC", "1.0", "0.5", PC_SOURCE))
    print("5 ↺ and 既定に戻す")

    # ---- 書き出す / 読み込む…
    open_card()
    with page.expect_download() as d:
        page.click("#basis-export")
    assert d.value.suggested_filename == "cad-viewer-材料の基準.json", d.value.suggested_filename
    data = json.loads(Path(d.value.path()).read_text("utf-8"))
    assert data["kind"] == "materials" and list(data["materials"]) == METALS + RESINS, list(data["materials"])
    for m, (dn, th, dr) in STANDARD.items():
        v = data["materials"][m]
        assert (v["density"], v["thin"], v["draft"]) == (dn, th, dr), (m, v)
    data["materials"]["PC"].update(thin=1.5, source="社外の基準")
    data["materials"]["SS400"].update(density=7.87)
    data["materials"]["謎の材料"] = {"density": 1, "thin": 1, "draft": 1, "source": ""}
    data["materials"]["PP"].update(thin=99)
    f = tmp / "edited.json"
    f.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    page.set_input_files("#basis-file", str(f))
    page.wait_for_function("document.querySelector('#basis-note').textContent.startsWith('読み込んだ')", timeout=5000)
    assert page.inner_text("#basis-note") == "読み込んだ: 14 材料（表にあるのは 6。保存で決まる）。読めなかった: PP・謎の材料", page.inner_text("#basis-note")
    assert row_values("PC") == (1.2, 1.5, 0.5) and edited("PC") and row_values("PP") == STANDARD["PP"]
    assert conditions() == basis_line("PC", "1.0", "0.5", PC_SOURCE), "nothing kept before 保存"
    page.click("#basis-save")
    page.keyboard.press("Escape")
    wait_conditions(basis_line("PC", "1.5", "0.5", "社外の基準"))
    bad = tmp / "notes.json"
    bad.write_text('{"kind": "notes"}', "utf-8")
    open_card()
    page.set_input_files("#basis-file", str(bad))
    page.wait_for_function("document.querySelector('#basis-note').textContent.startsWith('読み込めなかった')", timeout=5000)
    assert page.inner_text("#basis-note") == "読み込めなかった: 材料の基準のファイルではない"
    page.keyboard.press("Escape")
    print("6 file out and in")

    # ================= 一般: the metals; the moulding's rows go
    choose("用途", "一般")
    assert options("材料") == METALS + RESINS, options("材料")
    assert select_text("材料") == "SS400"
    assert not folder_shown("抜き勾配") and not folder_shown("問題の一覧"), "the moulding's folders"
    assert not row_shown("型内圧 (MPa)") and row_shown("比重 (g/cm³)")
    assert not shown("#check-panel"), "the list goes off"
    page.wait_for_function("document.querySelector('#props-total-mass').textContent !== ''", timeout=10000)
    assert not shown("#props-total-proj") and not shown("#props-total-clamp"), "no projected area, no clamping force"
    # the imported SS400 gravity was saved with the card (7.87)
    assert page.inner_text("#props-density") == "SS400 7.87 g/cm³" and mass() == grams(7.87), (page.inner_text("#props-density"), mass())
    assert number("閾値 (mm)") == 0.8
    open_card()
    assert card_rows() == METALS + RESINS, card_rows()
    heads = page.evaluate("[...document.querySelectorAll('#basis-pop tr.basis-group th')].map(t => t.textContent)")
    assert heads == ["金属", "樹脂"], heads
    assert row("SUS304").locator(".basis-draft").count() == 0 and row("PMMA").locator(".basis-draft").count() == 1
    assert edited("SS400") and row_values("SUS304") == STANDARD["SUS304"]
    page.keyboard.press("Escape")
    recs = record()
    assert meta(recs, "用途") == "一般"
    assert meta(recs, "材料") == f"SS400（直した値: 比重 7.87・肉厚の下限 0.8 mm。根拠: {METAL_SOURCE}）", meta(recs, "材料")
    assert not any(r and r[0].startswith("問題の一覧") for r in recs), "一般's 記録 has no 問題の一覧"
    weight = next(r for r in recs if r and r[0] == "比重")
    assert weight[1:] == ["7.87", "g/cm³", "材料 SS400 の値（直した値）"], weight
    choose("材料", "純チタン 2 種")
    assert page.inner_text("#props-density") == "純チタン 2 種 4.51 g/cm³" and mass() == grams(4.51)
    print("7 一般:", page.inner_text("#props-density"))

    # ---- back to 射出成形: its material (PC), its folders
    choose("用途", "射出成形")
    assert select_text("材料") == "PC" and folder_shown("抜き勾配") and folder_shown("問題の一覧") and row_shown("型内圧 (MPa)")
    page.wait_for_function("document.querySelector('#props-total-clamp')?.textContent.includes('kN')", timeout=30000)

    # ================= a reload: everything kept
    choose("用途", "一般")
    page.reload()
    page.wait_for_selector("#file-input", state="attached")
    n.load(str(mold), props="live")
    assert select_text("用途") == "一般" and select_text("材料") == "純チタン 2 種"
    choose("用途", "射出成形")
    assert select_text("材料") == "PC"
    gui_common.open_folder(page, "問題の一覧")
    ctl("厚肉を調べる").locator("input").uncheck()  # the reload put it back on
    ctl("一覧を出す").locator("input").check()
    wait_conditions(basis_line("PC", "1.5", "0.5", "社外の基準"))
    print("8 reloaded")

    # ================= what the app kept before materials comes along
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    old = ctx.new_page()
    old.goto(BASE_URL)
    old.evaluate(
        """() => {
            localStorage.removeItem('cad-viewer:materials')
            localStorage.setItem('cad-viewer:props', JSON.stringify({ resin: 'その他', density: 1.15, pressure: 55 }))
            localStorage.setItem('cad-viewer:check-basis', JSON.stringify({ selected: '', bases: {
              PMMA: { thin: 1.5, draft: 1, source: '' }, POM: { thin: 1.2, draft: 0.8, source: '社内' } } }))
        }"""
    )
    old.reload()
    old.wait_for_selector("#file-input", state="attached")
    kept = old.evaluate("JSON.parse(localStorage.getItem('cad-viewer:materials'))")
    assert kept["chosen"]["molding"] == "PMMA" and kept["density"] == 1.15 and kept["follow"] is True, kept
    assert list(kept["edits"]) == ["POM"] and kept["edits"]["POM"] == {"density": 1.41, "thin": 1.2, "draft": 0.8, "thick": 1.5, "source": "社内"}, kept["edits"]
    old.evaluate("localStorage.setItem('cad-viewer:props', JSON.stringify({ resin: 'PC', density: 1.2, pressure: 55 })); localStorage.removeItem('cad-viewer:materials')")
    old.reload()
    old.wait_for_selector("#file-input", state="attached")
    kept = old.evaluate("JSON.parse(localStorage.getItem('cad-viewer:materials'))")
    assert kept["chosen"]["molding"] == "PC" and kept["density"] is None, kept
    ctx.close()
    print("9 the old keys come along:", kept["chosen"])

    # ================= a narrow window: the cards stay in it
    page.set_viewport_size({"width": 560, "height": 800})
    n.settle()
    for name, sel in (("基準を編集…", "#basis-pop"), ("確認の記録…", "#report-pop")):
        ctl(name).locator("button").click()
        page.wait_for_selector(f"{sel}:not(.hidden)")
        r = page.evaluate(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] }})()")
        assert r[0] >= 0 and r[2] <= 560 and r[1] >= 0 and r[3] <= 800, (name, r)
        page.keyboard.press("Escape")
        n.settle()
    print("10 narrow", r)
    assert not n.errors, n.errors
print("MATERIALS E2E OK")
