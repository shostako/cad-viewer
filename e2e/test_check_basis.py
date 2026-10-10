"""E2E: 判定の基準 (issue #59 P1 10): a material's thickness and draft, with their basis.

- 問題の一覧 > 判定の基準: 手で決める at first (the conditions as before, no
  basis said). 基準を編集… opens a card: a row a material (the 体積・重量
  panel's resins), each at the app's defaults (1.5 mm, 1.0°, basis 未設定).
  Values out of range are not saved (the card says which); a value finer
  than the folders' step (0.1) is saved at the step, and the card says so.
- A material chosen sets the 肉厚 folder's 閾値 and the 抜き勾配 folder's 必要な
  勾配; the list follows them, and its conditions (and the 記録's) name the
  basis. A material not edited says 未設定. The 体積・重量 resin stays as it was.
- A value changed by hand: back to 手で決める. The choice and the values
  survive a reload. Esc and a click elsewhere close the card. On a window too
  narrow for it beside the column, the card (and 確認の記録's) stays in it.

Oracles (none from the code under test): ribbed_plate.stl's make
(testdata/make_testdata.py): its three ribs are 1.2 mm thick (薄肉 under 1.5 mm,
not under 1.0 mm), its vertical walls have no draft (勾配不足 at 0.5° too).
"""
import csv
import io
from pathlib import Path

import gui_common
from nav_common import TESTDATA, nav_session

RIBBED = TESTDATA / "ribbed_plate.stl"
BOX = ((-40, -25, 0), (40, 25, 12))
PLAIN = "肉厚 1.5 mm 未満（レイ法）・型開き +Z・勾配 1.0° 未満"
SOURCE = "社内の目安（2026-10）"

with nav_session() as n:
    page = n.page

    def check():
        return page.evaluate("window.__cadCheck()")

    def wait_list(pred="true"):
        page.wait_for_function(f"(() => {{ const c = window.__cadCheck(); return !!c && ({pred}) }})()", timeout=60000)
        n.settle()
        return check()

    def conditions():
        return page.inner_text("#check-panel .check-conditions")

    def thin_rows(c):
        return [r for r in c["rows"] if r["kind"] == "thin"]

    def basis_ctl():
        return gui_common.ctl(page, "判定の基準").locator("select")

    def basis_shown():
        return basis_ctl().evaluate("s => s.options[s.selectedIndex].text")

    def number(name):
        return float(gui_common.ctl(page, name).locator("input").last.input_value())

    def open_card():
        gui_common.ctl(page, "基準を編集…").locator("button").click()
        page.wait_for_selector("#basis-pop:not(.hidden)")

    def card_shown():
        return page.evaluate("!document.querySelector('#basis-pop').classList.contains('hidden')")

    def row(material):
        return page.locator(f"#basis-pop tr[data-material='{material}']")

    def wait_conditions(text):
        page.wait_for_function(
            f"document.querySelector('#check-panel .check-conditions')?.textContent === {text!r}", timeout=60000
        )
        n.settle()
        return check()

    n.load(RIBBED, props="live", box=BOX)
    gui_common.open_folder(page, "問題の一覧")
    assert basis_shown() == "手で決める", basis_shown()
    gui_common.ctl(page, "一覧を出す").locator("input").check()
    c = wait_list()
    assert conditions() == PLAIN, conditions()
    assert len(thin_rows(c)) == 3, ("the three ribs under 1.5 mm", c)

    # ---- the card: every material at the defaults, basis 未設定
    open_card()
    materials = page.evaluate("[...document.querySelectorAll('#basis-pop tbody tr')].map(t => t.dataset.material)")
    assert materials == ["PMMA", "PC", "ABS", "PP", "PA66", "POM", "PS"], materials
    for m in materials:
        assert row(m).locator(".basis-thin").input_value() == "1.5" and row(m).locator(".basis-draft").input_value() == "1", m
        assert row(m).locator(".basis-source").input_value() == "", m
    page.keyboard.press("Escape")
    assert not card_shown(), "Esc closes the card"
    open_card()
    row("PS").locator(".basis-source").focus()
    page.keyboard.press("Escape")
    assert not card_shown(), "Esc in a field closes it too"
    open_card()
    page.mouse.click(300, 600)
    n.settle()
    assert not card_shown(), "a click elsewhere closes it"

    # out of range: not saved
    open_card()
    row("PC").locator(".basis-thin").fill("0")
    page.click("#basis-save")
    note = page.inner_text("#basis-note")
    assert note.startswith("保存しなかった: PC の値が範囲の外"), note
    row("PC").locator(".basis-thin").fill("1.0")
    row("PC").locator(".basis-draft").fill("0.5")
    row("PC").locator(".basis-source").fill(SOURCE)
    page.click("#basis-save")
    assert page.inner_text("#basis-note") == "保存した"
    page.keyboard.press("Escape")
    # saving changes nothing in use (手で決める)
    assert basis_shown() == "手で決める" and number("閾値 (mm)") == 1.5 and conditions() == PLAIN
    print("1 card", materials)

    # ---- PC: its values set the folders, the list follows, the conditions name it
    basis_ctl().select_option(label="PC")
    want = f"肉厚 1.0 mm 未満（レイ法）・型開き +Z・勾配 0.5° 未満・基準 PC（根拠: {SOURCE}）"
    c = wait_conditions(want)
    assert number("閾値 (mm)") == 1.0 and number("必要な勾配 (°)") == 0.5, (number("閾値 (mm)"), number("必要な勾配 (°)"))
    assert thin_rows(c) == [], ("the ribs (1.2 mm) are not under 1.0 mm", thin_rows(c))
    assert len([r for r in c["rows"] if r["kind"] == "short"]) == 6, ("the walls have no draft: short at 0.5° too", c)
    # the 体積・重量 resin is its own
    assert page.inner_text("#props-density") == "PMMA 1.19 g/cm³", page.inner_text("#props-density")
    # the 記録 says the conditions with the basis
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    with page.expect_download() as d:
        page.click("#report-csv")
    page.keyboard.press("Escape")
    recs = list(csv.reader(io.StringIO(Path(d.value.path()).read_bytes()[3:].decode("utf-8"), newline="")))
    i = next(k for k, r in enumerate(recs) if r and r[0].startswith("問題の一覧"))
    assert recs[i + 1] == [f"条件: {want}"], recs[i + 1]
    print("2 PC", want)

    # ---- a material not edited: the defaults, 未設定
    basis_ctl().select_option(label="PP")
    c = wait_conditions(f"{PLAIN}・基準 PP（根拠: 未設定）")
    assert len(thin_rows(c)) == 3, c

    # ---- a value by hand: back to 手で決める
    inp = gui_common.ctl(page, "閾値 (mm)").locator("input").last
    inp.fill("1.3")
    inp.press("Enter")
    c = wait_conditions("肉厚 1.3 mm 未満（レイ法）・型開き +Z・勾配 1.0° 未満")
    assert basis_shown() == "手で決める", basis_shown()
    print("3 by hand", conditions())

    # ---- the choice and the values survive a reload
    basis_ctl().select_option(label="PC")
    wait_conditions(want)
    page.reload()
    page.wait_for_selector("#file-input", state="attached")
    n.load(RIBBED, props="live", box=BOX)
    gui_common.open_folder(page, "問題の一覧")
    assert basis_shown() == "PC", basis_shown()
    assert number("閾値 (mm)") == 1.0 and number("必要な勾配 (°)") == 0.5
    gui_common.ctl(page, "一覧を出す").locator("input").check()
    wait_conditions(want)
    open_card()
    assert row("PC").locator(".basis-source").input_value() == SOURCE
    page.keyboard.press("Escape")
    print("4 after a reload", conditions())

    # ---- a value finer than the folders' step: saved at the step, and said so
    open_card()
    row("PC").locator(".basis-thin").fill("1.25")
    page.click("#basis-save")
    note = page.inner_text("#basis-note")
    assert note == "保存した（0.1 刻みに丸めた: PC の肉厚 1.25 → 1.3）", note
    assert row("PC").locator(".basis-thin").input_value() == "1.3"
    page.keyboard.press("Escape")
    wait_conditions(f"肉厚 1.3 mm 未満（レイ法）・型開き +Z・勾配 0.5° 未満・基準 PC（根拠: {SOURCE}）")
    assert number("閾値 (mm)") == 1.3, number("閾値 (mm)")

    # ---- a narrow window: the cards stay in it (over the column when there is no room beside it)
    page.set_viewport_size({"width": 560, "height": 800})
    n.settle()
    for name, sel in (("基準を編集…", "#basis-pop"), ("確認の記録…", "#report-pop")):
        gui_common.ctl(page, name).locator("button").click()
        page.wait_for_selector(f"{sel}:not(.hidden)")
        r = page.evaluate(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] }})()")
        assert r[0] >= 0 and r[2] <= 560 and r[1] >= 0 and r[3] <= 800, (name, r)
        page.keyboard.press("Escape")
        n.settle()
    print("5 narrow", r)
print("CHECK BASIS E2E OK")
