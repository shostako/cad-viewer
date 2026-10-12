"""E2E: 版の比較's 左右に見比べる (見せ方): the old version left of a line, the
new one right of it, one camera; the line dragged (viewer.ts setSplit).

revision_b (new, open) against revision_a: the new boss (R3 at (30, 30), its
top at z 8) is in the new version alone, the rib (its top at z 9 over x 44.25
.. 45.75, y 8 .. 32) in the old one alone. The colour at a point of each is
read in 新しい版だけ / 前の版だけ first; then, split, it must show only on its
own version's side of the line, whichever side the point is dragged to. The
value under the cursor is of the version on its side. A saved image is split
as the screen is.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image

from nav_common import TESTDATA, nav_session

BOSS_TOP = (30, 30, 8)
RIB_TOP = (45, 26, 9)

with nav_session() as nav:
    page = nav.page
    nav.load(TESTDATA / "revision_b.step", props="live")
    with page.expect_file_chooser() as fc:
        nav.ctl("別の版と比べる").locator("button").click()
    fc.value.set_files(str(TESTDATA / "revision_a.step"))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)

    def show(label):
        nav.ctl("見せ方").locator("select").select_option(label=label)
        nav.settle()

    def rgb(p):
        return nav.canvas_rgb([nav.project(p)])[0][:3]

    def close(a, b, tol=12):
        return max(abs(x - y) for x, y in zip(a, b)) <= tol

    # ---- the colours of the two places in their own versions --------------------------
    show("新しい版だけ")
    added = rgb(BOSS_TOP)
    show("前の版だけ")
    removed = rgb(RIB_TOP)
    assert not close(added, removed, 40), (added, removed)
    assert page.evaluate("window.__cadSwipe()") == {"at": None, "shown": False}

    # ---- split: the line in the middle, its labels ----------------------------------------
    show("左右に見比べる")
    assert page.evaluate("window.__cadSwipe()") == {"at": 0.5, "shown": True}
    assert page.locator(".swipe-label").all_inner_texts() == ["前の版", "新しい版"]

    def drag_to(x):
        """the line dragged to page x; where it stopped (a fraction of the canvas)"""
        box = page.locator("#swipe-bar").bounding_box()
        bx, by = box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.7
        page.mouse.move(bx, by)
        page.mouse.down()
        page.mouse.move(x, by, steps=6)
        page.mouse.up()
        nav.settle()
        l, _, w, _ = nav.canvas_rect()
        at = page.evaluate("window.__cadSwipe()")["at"]
        assert abs(at - (x - l) / w) < 0.01, (at, x)
        bar = page.locator("#swipe-bar").bounding_box()
        assert abs(bar["x"] + bar["width"] / 2 - x) <= 2, (bar, x)  # the line drawn where it is
        return at

    for p, mine, other in ((BOSS_TOP, "new", added), (RIB_TOP, "old", removed)):
        px, py = nav.project(p)
        # the point right of the line: the new version there
        drag_to(px - 60)
        here = rgb(p)
        assert close(here, other) == (mine == "new"), (p, "right", here, other)
        # left of it: the old version there
        drag_to(px + 60)
        here = rgb(p)
        assert close(here, other) == (mine == "old"), (p, "left", here, other)

    # ---- the value under the cursor: of the version on the cursor's side --------------------
    rx, ry = nav.project(RIB_TOP)
    drag_to(rx + 80)  # the rib's top left of the line: the old version's
    page.mouse.move(rx, ry)
    page.wait_for_function("document.querySelector('#cursor-tip').textContent.includes('前の版の面')", timeout=5000)
    assert "削られた −6.00 mm（前の版の面）" in page.inner_text("#cursor-tip"), page.inner_text("#cursor-tip")
    bx, by = nav.project(BOSS_TOP)
    drag_to(bx - 80)  # the new boss's top right of it: the new version's
    page.mouse.move(bx, by)
    page.wait_for_function("document.querySelector('#cursor-tip').textContent.includes('新しい版の面')", timeout=5000)
    tip = page.inner_text("#cursor-tip")
    assert "足された +5.00 mm（新しい版の面）" in tip, tip

    # ---- 画像を保存: the image split as the screen is (the new boss right of the line) ----------
    with page.expect_download(timeout=15000) as info:
        page.locator("#toolbar button[data-action='png']").click()
    img = Image.open(BytesIO(Path(info.value.path()).read_bytes())).convert("RGB")
    l, t, w, h = nav.canvas_rect()
    sx, sy = img.width / w, img.height / h
    shot = img.getpixel((int((bx - l) * sx), int((by - t) * sy)))
    assert close(shot, added), (shot, added)
    drag_to(bx + 80)  # left of the line now: the old version's (no boss there)
    with page.expect_download(timeout=15000) as info:
        page.locator("#toolbar button[data-action='png']").click()
    img = Image.open(BytesIO(Path(info.value.path()).read_bytes())).convert("RGB")
    shot = img.getpixel((int((bx - l) * sx), int((by - t) * sy)))
    assert not close(shot, added), (shot, added)

    # ---- another way of showing: whole again, the line gone ---------------------------------
    show("重ねる（変わった所）")
    assert page.evaluate("window.__cadSwipe()") == {"at": None, "shown": False}
    assert close(rgb(BOSS_TOP), added)
    # the split kept where it was for the next time
    show("左右に見比べる")
    at = page.evaluate("window.__cadSwipe()")["at"]
    assert at is not None and abs(at - 0.5) > 0.01, at
    nav.ctl("比較をやめる").locator("button").click()
    nav.settle()
    assert page.evaluate("window.__cadSwipe()") == {"at": None, "shown": False}
    print("OK: 版の比較の左右の見比べ")
