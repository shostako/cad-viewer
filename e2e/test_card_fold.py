"""E2E: the bottom-right cards fold to their heads (問題の一覧, 計測).

- Each card's title is a button (aria-expanded): pressed, 問題の一覧 keeps its
  head (すべてコピー too) and its counts, 計測 its head (the count, すべてコピー);
  the rows go. Pressed again, they come back.
- Folded, a card is short; the column gives the room to the others (the
  operation panel first, as it lays out), and the cards still do not overlap.
- Folded or not survives a reload (the list folded when it is made again).

Oracles (none from the code under test): mini_mold.step's make
(testdata/make_step_assembly.py: 勾配不足 the ten vertical walls, 反対側 the
four faces that look down); eight notes saved for the file; what the page
shows (getBoundingClientRect, visibility).
"""
import tempfile
from pathlib import Path

import gui_common
from nav_common import TESTDATA, nav_session, put_sidecar

tmp = tempfile.mkdtemp(prefix="cad_fold_")
mold = Path(tmp) / "mini_mold.step"
mold.write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 85)
NOTES = [
    {"text": f"📌 メモ{i}", "labelText": f"メモ{i}", "labelPos": [10 + 10 * i, 5, 15], "markers": [[10 + 10 * i, 5, 15]], "annotation": True}
    for i in range(8)
]

with nav_session() as n:
    page = n.page
    page.set_viewport_size({"width": 1280, "height": 860})
    put_sidecar(page, mold, NOTES)

    def rect(sel):
        return page.evaluate(f"(() => {{ const r = document.querySelector({sel!r}).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] }})()")

    def shown(sel):
        return page.locator(sel).first.is_visible()

    def expanded(sel):
        return page.get_attribute(sel, "aria-expanded")

    def no_overlap():
        cards = [rect(s) for s in ("#check-panel", "#measure-panel", "#props-panel")]
        for a, b in zip(cards, cards[1:]):
            assert a[3] <= b[1] + 0.5, ("the cards do not overlap", cards)
        gui = rect(".lil-gui.lil-root")
        assert gui[3] <= cards[0][1] + 0.5, ("under the operation panel", gui, cards[0])

    def list_on():
        gui_common.open_folder(page, "問題の一覧")
        gui_common.ctl(page, "一覧を出す").locator("input").check()
        page.wait_for_function("!!window.__cadCheck()", timeout=60000)
        n.settle()

    n.load(str(mold), props="live")
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 8", timeout=10000)
    list_on()
    check_fold, measure_fold = "#check-panel .card-fold", "#measure-fold"
    assert expanded(check_fold) == "true" and expanded(measure_fold) == "true"
    assert shown("#check-panel .check-list li") and shown("#measure-list li")
    open_h = {s: rect(s)[3] - rect(s)[1] for s in ("#check-panel", "#measure-panel", ".lil-gui.lil-root")}
    no_overlap()

    # ---- 問題の一覧 folded: its head and its counts
    page.click(check_fold)
    n.settle()
    page.wait_for_timeout(100)
    n.settle()
    assert expanded(check_fold) == "false"
    assert not shown("#check-panel .check-list") and not shown("#check-panel .check-conditions"), "the rows and the conditions go"
    assert shown("#check-panel .check-counts") and shown("#check-panel .check-copy-all"), "the counts and すべてコピー stay"
    counts = page.inner_text("#check-panel .check-counts")
    assert counts.startswith("薄肉 0・厚肉 0・勾配不足 10・反対側 4"), counts
    folded_h = rect("#check-panel")[3] - rect("#check-panel")[1]
    assert folded_h < 80 and folded_h < open_h["#check-panel"] / 2, (folded_h, open_h)
    # the room goes to the others: the operation panel first (it scrolled), then the measure list
    others = sum(rect(s)[3] - rect(s)[1] for s in ("#measure-panel", ".lil-gui.lil-root"))
    before = open_h["#measure-panel"] + open_h[".lil-gui.lil-root"]
    assert others > before + 0.5 * (open_h["#check-panel"] - folded_h), ("the room goes to the others", others, before)
    no_overlap()
    print("1 問題の一覧 folded", folded_h, "the others", before, "->", others)

    # ---- 計測 folded: its head (the count, すべてコピー)
    page.click(measure_fold)
    n.settle()
    page.wait_for_timeout(100)
    n.settle()
    assert expanded(measure_fold) == "false"
    assert not shown("#measure-list"), "the rows go"
    assert page.inner_text("#measure-count") == "8" and shown("#measure-copy-all"), "the count and すべてコピー stay"
    m_h = rect("#measure-panel")[3] - rect("#measure-panel")[1]
    assert m_h < 60, m_h
    no_overlap()
    print("2 計測 folded", m_h)

    # ---- after a reload: still folded (the list folded when made again)
    page.reload()
    page.wait_for_selector("#file-input", state="attached")
    n.load(str(mold), props="live")
    page.wait_for_function("document.querySelectorAll('#measure-list li').length === 8", timeout=10000)
    list_on()
    assert expanded(check_fold) == "false" and expanded(measure_fold) == "false", (expanded(check_fold), expanded(measure_fold))
    assert not shown("#check-panel .check-list") and not shown("#measure-list")

    # ---- opened again: the rows are back, at their room
    page.click(check_fold)
    page.click(measure_fold)
    n.settle()
    page.wait_for_timeout(100)
    n.settle()
    assert expanded(check_fold) == "true" and expanded(measure_fold) == "true"
    assert shown("#check-panel .check-list li") and shown("#measure-list li")
    again = {s: rect(s)[3] - rect(s)[1] for s in ("#check-panel", "#measure-panel", ".lil-gui.lil-root")}
    assert all(abs(again[s] - open_h[s]) < 2 for s in again), (again, open_h)
    no_overlap()
    print("3 opened again", again)
print("CARD FOLD E2E OK")
