"""E2E: the 記録's 該当箇所 (issue #59 P1 5, its rest): an image of each place.

- With the 問題の一覧 on, the page to print has 該当箇所: an image of each of
  the first 12 places, in the list's order, its caption the row's (kind, value,
  part, point). The card says how many.
- Each image is the place as its row's press shows it (the place's run
  framed in the whole image), with a ring on the place's point, in the image;
  a 薄肉 or a 勾配不足 in the warm colours of the heatmap or the draft
  colouring around the ring, a 反対側 in blue.
- Making them leaves the screen as it was: the view, the colouring (none on;
  the heatmap on; with 薄肉 alone, the last images in the heatmap), the legends,
  a place gone to with a legend's button (its marker, its index, what F fits).
- Without the list: no 該当箇所.

Oracles (none from the code under test): ribbed_plate.stl's make
(testdata/make_testdata.py): three ribs 1.2 mm thick (薄肉 under 1.5 mm), six
runs of vertical walls (勾配不足), six faces that look down (反対側): 15 places.
The images' pixels (PIL).
"""
import base64
import io
import math
import re

from PIL import Image

import gui_common
from nav_common import TESTDATA, classic_basis, nav_session

RIBBED = TESTDATA / "ribbed_plate.stl"
BOX = ((-40, -25, 0), (40, 25, 12))
RING = (0xFF, 0xD0, 0x60)  # the ring's yellow, as the screen's marker (style.css --cv-measure)


def img_of(src):
    return Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("RGB")


def ring_centre(im):
    """the mean place of the ring's pixels (yellow, JPEG-blurred), and how many"""
    xs, ys = [], []
    px = im.load()
    for y in range(0, im.height, 2):
        for x in range(0, im.width, 2):
            r, g, b = px[x, y]
            if math.dist((r, g, b), RING) < 60:
                xs.append(x)
                ys.append(y)
    return (sum(xs) / len(xs), sum(ys) / len(ys), len(xs)) if xs else (None, None, 0)


def around(im, cx, cy, pred, half=60):
    """how many pixels within half px of (cx, cy) the predicate holds for"""
    px = im.load()
    n = 0
    for y in range(max(0, int(cy) - half), min(im.height, int(cy) + half), 2):
        for x in range(max(0, int(cx) - half), min(im.width, int(cx) + half), 2):
            if pred(*px[x, y]):
                n += 1
    return n


# (shaded: the colours come darker than the palette)
warm = lambda r, g, b: r > 120 and r > 1.6 * g and r > 2.5 * b
blue = lambda r, g, b: b > 170 and b > 1.5 * r

with nav_session() as n:
    page = n.page
    # the checks at the app's own 1.5 mm and 1.0° (判定の基準 手で決める), as written: the default is the material's
    classic_basis(page)

    def colouring():
        return page.evaluate(
            "(() => ({ heat: !document.querySelector('#thickness-legend').classList.contains('hidden'),"
            " draft: !document.querySelector('#draft-legend').classList.contains('hidden') }))()"
        )

    n.load(RIBBED, props="live", box=BOX)

    # ---- without the list: no 該当箇所
    gui_common.ctl(page, "確認の記録…").locator("button").click()
    assert "該当箇所" not in page.inner_text("#report-what"), page.inner_text("#report-what")
    with page.expect_popup() as pp:
        page.click("#report-page")
    tab = pp.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), timeout=10000)
    tab.wait_for_load_state()
    assert "該当箇所" not in tab.inner_text("body")
    tab.close()
    page.keyboard.press("Escape")

    # ---- with the list
    gui_common.open_folder(page, "問題の一覧")
    # 厚肉 is test_thick_spots.py's: this list is the wall's and the draft's, as written
    gui_common.ctl(page, "厚肉を調べる").locator("input").uncheck()
    gui_common.ctl(page, "一覧を出す").locator("input").check()
    page.wait_for_function("!!window.__cadCheck()", timeout=60000)
    n.settle()
    rows = page.evaluate("window.__cadCheck()")["rows"]
    kinds = [r["kind"] for r in rows]
    assert kinds == ["thin"] * 3 + ["short"] * 6 + ["opposite"] * 6, kinds
    view_before, colour_before = n.view(), colouring()
    assert colour_before == {"heat": False, "draft": False}, colour_before

    gui_common.ctl(page, "確認の記録…").locator("button").click()
    what = page.inner_text("#report-what")
    assert what.endswith("該当箇所の画像 12 枚（印刷用のページ）"), what
    with page.expect_popup() as pp:
        page.click("#report-page")
    tab = pp.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), timeout=60000)
    tab.wait_for_load_state()
    page.keyboard.press("Escape")
    n.settle()

    # the screen as it was
    view_after = n.view()
    for k in view_before:
        a, b = view_before[k], view_after[k]
        same = a == b if not isinstance(a, list) else all(abs(x - y) < 1e-6 for x, y in zip(a, b))
        assert same, ("the view is put back", k, a, b)
    assert colouring() == colour_before, ("the colouring is put back", colouring())

    # the page's 該当箇所
    title = tab.evaluate("[...document.querySelectorAll('h2')].map(h => h.textContent).find(t => t.startsWith('該当箇所'))")
    assert title == "該当箇所（12 / 15 行）", title
    figs = tab.evaluate("[...document.querySelectorAll('figure.spot')].map(f => [f.querySelector('img').src, f.querySelector('figcaption').textContent])")
    assert len(figs) == 12, len(figs)
    for i, (src, cap) in enumerate(figs):
        kind = kinds[i]
        name = {"thin": "薄肉", "short": "勾配不足", "opposite": "反対側"}[kind]
        assert re.match(rf"^{i + 1}\. {name} ", cap), (i, cap)
        if kind == "thin":
            assert re.search(r"薄肉 1\.2\d mm · ", cap), cap
        assert src.startswith("data:image/jpeg;base64,"), src[:40]
        im = img_of(src)
        cx, cy, count = ring_centre(im)
        assert count >= 8, ("a ring on the place", i, count)
        assert 0.03 * im.width < cx < 0.97 * im.width and 0.03 * im.height < cy < 0.97 * im.height, ("the place in the image", i, cx, cy, im.size)
        colour = blue if kind == "opposite" else warm
        assert around(im, cx, cy, colour) >= 20, ("in its kind's colours", i, kind, around(im, cx, cy, colour))
    print("1 spots", title, [c for _, c in figs[:4]])
    tab.close()

    def make_page():
        gui_common.ctl(page, "確認の記録…").locator("button").click()
        with page.expect_popup() as pp:
            page.click("#report-page")
        t = pp.value
        t.wait_for_url(lambda u: u.startswith("blob:"), timeout=60000)
        t.wait_for_load_state()
        page.keyboard.press("Escape")
        n.settle()
        k = t.evaluate("document.querySelectorAll('figure.spot').length")
        t.close()
        return k

    # ---- the heatmap on before: it comes back on (the last images were in the draft colours)
    gui_common.ctl(page, "ヒートマップ").locator("input").check()
    page.wait_for_function("!document.querySelector('#thickness-legend').classList.contains('hidden')", timeout=60000)
    n.settle()
    # and a place gone to with the legend's button: it stays (its marker, its index, what F fits)
    page.locator(".go-btn[data-go='thin']").click()
    n.settle()
    page.wait_for_timeout(450)  # the move takes 0.3 s
    n.settle()
    went = page.evaluate("window.__cadSpot()")
    state = page.inner_text(".go-state[data-go='thin']")
    assert went and went["index"] == 0 and page.locator(".spot-marker").count() == 1, went

    def press_f():
        page.mouse.move(5, 400)
        page.keyboard.press("f")
        n.settle()
        page.wait_for_timeout(450)
        n.settle()
        return n.view()

    # what F fits there (the place's box, kept by the fit), before the 記録
    at_place = press_f()
    assert make_page() == 12
    assert colouring() == {"heat": True, "draft": False}, ("the heatmap as it was", colouring())
    kept = page.evaluate("window.__cadSpot()")
    assert kept and kept["kind"] == "thin" and kept["index"] == 0, ("the place gone to stays", kept)
    assert page.locator(".spot-marker").count() == 1 and page.inner_text(".go-state[data-go='thin']") == state, "its marker and its index"
    refit = press_f()
    assert all(abs(x - y) < 1e-6 for x, y in zip(refit["position"], at_place["position"])), ("F fits the place again", refit["position"], at_place["position"])
    gui_common.ctl(page, "ヒートマップ").locator("input").uncheck()
    n.settle()

    # ---- 薄肉 alone (the draft not checked): the last images were in the heatmap; it goes again
    gui_common.ctl(page, "抜き勾配を調べる").locator("input").uncheck()
    page.wait_for_function("(() => { const c = window.__cadCheck(); return !!c && c.rows.every(r => r.kind === 'thin') })()", timeout=60000)
    n.settle()
    assert make_page() == 3
    assert colouring() == {"heat": False, "draft": False}, ("nothing on, as it was", colouring())
    print("2 the colouring put back", colouring())
print("REPORT SPOTS E2E OK")
