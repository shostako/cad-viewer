"""E2E: 版の比較's 面の変化 (docs/designs/compare-faces.md): the B-rep faces of
the two versions paired, told in the drawing's terms (facecompare.ts).

On the versions with one known change each (testdata/make_step_assembly.py
make_compare_cases) and the two revisions (make_revisions):
- a hole moved: its cylinder's axis moved 5.00 mm, (20, 20) to (25, 20); the
  plate's six faces the same (its top and bottom keep their area: the hole is
  as large; their centroids move 0.06, within the tolerance)
- a plate made thicker: its top moved +0.50 along its normal, its four sides
  reshaped (taller), its bottom the same; the other way round, -0.50
- a part taken away, one added: told as the parts (cap, pin)
- revision_b against revision_a: the raised boss's top +2.00 first; the new
  boss's faces of the new version alone; the rib's of the old one alone. The
  same with revision_b turned and moved (compared with revision_a open, the new
  one), aligned automatically: its faces moved into the open one's frame
- the legend's lines (5, the rest in the 記録), a press goes to the face; the
  記録's table; none for mesh files
"""
import csv
import io
import math
import tempfile
from pathlib import Path

import gui_common
from nav_common import TESTDATA, box_stl, nav_session

with nav_session() as nav:
    page = nav.page

    def compare(new, old):
        nav.load(TESTDATA / f"{new}.step" if isinstance(new, str) else new, props="live")
        with page.expect_file_chooser() as fc:
            nav.ctl("別の版と比べる").locator("button").click()
        fc.value.set_files(str(TESTDATA / f"{old}.step" if isinstance(old, str) else old))
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)

    def faces():
        page.wait_for_function("window.__cadFaceChanges() !== null", timeout=60000)
        nav.settle()
        return page.evaluate("window.__cadFaceChanges()")

    def stop():
        nav.ctl("比較をやめる").locator("button").click()
        nav.settle()

    # ---- a hole moved ------------------------------------------------------------------
    compare("compare_hole_b", "compare_hole_a")
    f = faces()
    assert f["same"] == 6 and len(f["changes"]) == 1, f
    (c,) = f["changes"]
    assert c["kind"] == "moved" and c["text"] == "円筒 R3.00: 軸が 5.00 mm 動いた（(20.00, 20.00, 1.50) → (25.00, 20.00, 1.50)）", c
    assert abs(c["amount"] - 5) < 1e-6 and math.dist(c["at"], (25, 20, 1.5)) < 1e-6, c
    stop()

    # ---- a plate made thicker, both ways round -------------------------------------------
    compare("compare_thick_b", "compare_thick_a")
    f = faces()
    assert f["same"] == 1 and [c["kind"] for c in f["changes"]] == ["moved"] + ["reshaped"] * 4, f
    assert f["changes"][0]["short"] == "平面 +Z: +0.50 mm", f["changes"][0]
    nav.ctl("新しいのは").locator("select").select_option(label="比べる版")
    page.wait_for_function("(() => { const f = window.__cadFaceChanges(); return f && f.changes[0].short === '平面 +Z: −0.50 mm' })()", timeout=60000)
    nav.ctl("新しいのは").locator("select").select_option(label="開いている版")  # (it stays for the next comparison)
    stop()

    # ---- a part taken away, one added ----------------------------------------------------
    compare("compare_parts_b", "compare_parts_a")
    f = faces()
    assert f["same"] == 6 and [(c["kind"], c["short"]) for c in f["changes"]] == [("added", "部品「cap」（面 6）"), ("removed", "部品「pin」（面 3）")], f
    stop()

    # ---- the two revisions: the legend, a press, the 記録 --------------------------------
    compare("revision_b", "revision_a")
    f = faces()
    kinds = [c["kind"] for c in f["changes"]]
    assert f["changes"][0]["short"] == "平面 +Z: +2.00 mm", f["changes"][0]  # the raised boss's top
    assert kinds.count("added") == 2 and kinds.count("removed") == 5, kinds  # the new boss's side and top; the rib's five
    lines = page.locator("#compare-legend .face-change")
    assert lines.count() == 5, lines.count()
    assert "ほか 5 件" in page.inner_text("#compare-legend .face-changes")
    lines.nth(0).click()
    nav.settle()
    # the marker on the face, with what changed in full
    assert page.locator(".spot-marker").count() == 1 and page.inner_text(".spot-marker .spot-text") == f["changes"][0]["text"], page.locator(".spot-marker").count()
    assert page.locator("#compare-legend .face-change.current").count() == 1
    assert "current" in page.locator("#compare-legend .face-change").nth(0).get_attribute("class")
    x, y = nav.project(f["changes"][0]["at"])
    l, t, w, h = nav.canvas_rect()
    assert l + 0.15 * w < x < l + 0.85 * w and t + 0.15 * h < y < t + 0.85 * h, (x, y)  # the view on it
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    page.wait_for_selector("#report-pop:not(.hidden)")
    with page.expect_download() as d:
        page.click("#report-csv")
    rows = list(csv.reader(io.StringIO(Path(d.value.path()).read_bytes().decode("utf-8-sig"), newline="")))
    i = next(k for k, r in enumerate(rows) if r and r[0].startswith("面の変化"))
    assert rows[i][0] == f"面の変化（{len(f['changes'])} 件）", rows[i]
    j = next(k for k in range(i, len(rows)) if rows[k] and rows[k][0] == "種類")
    body = rows[j + 1 : j + 1 + len(f["changes"])]
    assert body[0][:2] == ["動いた", "平面（法線 (0.000, 0.000, 1.000)）: 法線の向きに +2.00 mm 動いた"], body[0]
    assert [r[0] for r in body].count("前の版にだけ") == 5
    page.keyboard.press("Escape")
    stop()

    # ---- revision_b turned and moved, the new one compared: aligned automatically, the same
    # changes (its faces moved into the open one's frame) -----------------------------------
    compare("revision_a", "revision_b_moved")
    nav.ctl("新しいのは").locator("select").select_option(label="比べる版")
    nav.ctl("自動で合わせる").locator("button").click()
    page.wait_for_function(
        "(() => { const a = window.__cadAlign().aligned; const f = window.__cadFaceChanges(); return a && a.kind === 'auto' && f && f.changes.length })()",
        timeout=180000,
    )
    nav.settle()
    g = page.evaluate("window.__cadFaceChanges()")
    assert [c["short"] for c in g["changes"]] == [c["short"] for c in f["changes"]], ([c["short"] for c in g["changes"]], [c["short"] for c in f["changes"]])
    stop()

    # ---- mesh files: no faces to pair -----------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="cad_faces_")
    a, b = Path(tmp) / "faces_a.stl", Path(tmp) / "faces_b.stl"
    box_stl(a, (0, 0, 0), (40, 30, 10))
    box_stl(b, (0, 0, 0), (40, 30, 12))
    compare(a, b)
    nav.settle()
    assert page.evaluate("window.__cadFaceChanges()") is None
    assert page.locator("#compare-legend .face-changes").count() == 0
    print("OK: 版の比較の面の変化")
