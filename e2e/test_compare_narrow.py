"""E2E: 版の比較's legend in a low window (#59 P2: panels must not cover the
model too much on a small screen).

In an 800 x 600 window, revision_b against revision_a: 面の変化 starts folded
(its line alone: the window is lower than 800); the view is fitted again once
the comparison is shown, where the legend leaves room (the model's middle not
under it, most of its outline clear of it). The legend folds to its title,
and that is kept over a reload. 面の変化 opened is kept too; in a window of
800 or more it starts open, and the view is fitted again once it has filled
the legend.
"""
import math

from nav_common import SLOW_SCENE_TIMEOUT, TESTDATA, nav_session

# revision_b's box (testdata/make_step_assembly.py make_revisions): the plate and the bosses
LO, HI = (0, 0, 0), (60, 40, 13)


def corners(lo, hi):
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


with nav_session(timeout=SLOW_SCENE_TIMEOUT) as nav:
    page = nav.page

    def compare(width, height):
        page.set_viewport_size({"width": width, "height": height})
        nav.load(TESTDATA / "revision_b.step", props="live")
        with page.expect_file_chooser() as fc:
            nav.ctl("別の版と比べる").locator("button").click()
        fc.value.set_files(str(TESTDATA / "revision_a.step"))
        page.wait_for_function(
            "document.querySelector('#hud-info').textContent.includes('足された') && document.querySelector('#compare-legend .face-changes')",
            timeout=120000,
        )
        nav.settle()

    def legend_rect():
        b = page.locator("#hud").bounding_box()
        return b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]

    def covered():
        """the model's outline (its box's projected corners' bounding rectangle): the share under the legend"""
        pts = nav.project_many(corners(LO, HI))
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        l, t, r, b = legend_rect()
        ix = max(0, min(x1, r) - max(x0, l))
        iy = max(0, min(y1, b) - max(y0, t))
        return ix * iy / ((x1 - x0) * (y1 - y0)), nav.project(((LO[0] + HI[0]) / 2, (LO[1] + HI[1]) / 2, (LO[2] + HI[2]) / 2))

    # ---- a low window: 面の変化 folded, the view fitted clear of the legend ---------------
    page.evaluate("localStorage.removeItem('cad-viewer:compare-legend-folded'); localStorage.removeItem('cad-viewer:face-changes-folded')")
    compare(800, 600)
    faces = page.locator("#compare-legend .face-changes")
    assert "folded" in faces.get_attribute("class"), faces.get_attribute("class")
    assert page.locator("#compare-legend .face-change").first.is_hidden()
    assert page.locator("#compare-legend .face-fold").is_visible() and "面の変化（B-rep の面）" in page.inner_text("#compare-legend .face-fold")
    share, (cx, cy) = covered()
    l, t, r, b = legend_rect()
    assert not (l <= cx <= r and t <= cy <= b), ("the model's middle under the legend", (cx, cy), (l, t, r, b))
    # (the window leaves little room: about a quarter stays under it; not fitted again, a third)
    assert share < 0.3, share

    # ---- the legend folds to its title; kept over a reload -------------------------------
    h0 = page.locator("#compare-legend").bounding_box()["height"]
    page.locator("#compare-legend .compare-fold").click()
    nav.settle()
    h1 = page.locator("#compare-legend").bounding_box()["height"]
    assert h1 < 50 and h1 < h0 / 3, (h0, h1)  # its title alone (two lines at most)
    assert page.locator("#compare-legend .thick-bar").is_hidden() and "版の比較（新しい版 revision_b.step" in page.inner_text("#compare-legend")
    page.reload()
    compare(800, 600)
    assert "folded" in page.locator("#compare-legend").get_attribute("class")
    page.locator("#compare-legend .compare-fold").click()  # open again
    nav.settle()
    assert page.locator("#compare-legend .thick-bar").is_visible()

    # ---- 面の変化 opened: its lines; kept --------------------------------------------------
    page.locator("#compare-legend .face-fold").click()
    nav.settle()
    assert page.locator("#compare-legend .face-change").first.is_visible()
    page.reload()
    compare(800, 600)
    assert "folded" not in page.locator("#compare-legend .face-changes").get_attribute("class")

    # ---- a window of 800 or more, never folded or opened: 面の変化 open ------------------------
    page.evaluate("localStorage.removeItem('cad-viewer:face-changes-folded')")
    page.reload()
    compare(900, 820)
    assert "folded" not in page.locator("#compare-legend .face-changes").get_attribute("class")
    assert page.locator("#compare-legend .face-change").first.is_visible()
    # fitted again once 面の変化 filled the legend (it comes after the comparison, Codex on #115)
    nav.settle()
    share, (cx, cy) = covered()
    l, t, r, b = legend_rect()
    # (fitted once only, before 面の変化, the full legend covered some 15 % of the outline here)
    assert not (l <= cx <= r and t <= cy <= b) and share < 0.05, (share, (cx, cy), (l, t, r, b))
    # ---- the view turned while 面の変化 is asked for: not fitted back (Claude on #115) ------------
    # (two models not asked for their faces yet: each model's are asked once)
    nav.load(TESTDATA / "compare_hole_b.step", props="live")
    page.evaluate("window.__cadStallFaces(4000)")
    with page.expect_file_chooser() as fc:
        nav.ctl("別の版と比べる").locator("button").click()
    fc.value.set_files(str(TESTDATA / "compare_hole_a.step"))
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('足された')", timeout=120000)
    assert page.locator("#compare-legend .face-changes").count() == 0, "面の変化 not yet in"
    page.locator("#viewport canvas").focus()
    page.keyboard.press("ArrowLeft")  # the view turned
    nav.settle()
    turned = page.evaluate("window.__cadView().position")
    page.wait_for_selector("#compare-legend .face-changes", timeout=60000)
    nav.settle()
    now = page.evaluate("window.__cadView().position")
    assert math.dist(now, turned) < 1e-6, ("the turned view fitted back", turned, now)
    print("OK: 版の比較の凡例（低い窓）")
