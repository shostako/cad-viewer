"""E2E: 全体表示 keeps the model clear of the panels (A5).

The fit frames the model in the free area: the largest part of the canvas no
overlay panel covers (the rule and the oracle: nav_common.py free_rect). The
expected free area comes from the panels' getBoundingClientRect, recorded at
each fit; the model's place from box corners through __cadProject, canvas
pixels and __cadPick. `needs=` on a check proves the case depends on that
panel: a correct fit that ignored it would fail the same check.

- P1 the long runner at load: left of the GUI, above the HUD; the target sits
     at the view centre through turns and presets; pixels; picking
- P3 the 視点 folder closed / open, and the whole GUI collapsed (the band
     under its title wins: a fit that read the GUI once would not see it)
- P6 a resize keeps the shift in px (clamped, restored), with no re-fit
- P4 700 x 900: left of the GUI; with 表示 closed, the band under it
- P5 400 x 900 falls back to the whole canvas; 450 x 900 does not
- P2 an IGES with a short tree and the 体積・重量 values (the motivating layout)
- P7 a long measurement list; a reload restores it before the one load fit
"""
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from nav_common import (
    LOAD_DIR, LOOSE_BOX, LOOSE_IGES, MOLD, RUNNER, TESTDATA,
    close, empty_sidecar, free_rect, nav_session, norm, overlaps, sub,
)

BACKEND_PY = Path(__file__).resolve().parents[1] / "backend" / ".venv" / "bin" / "python"
# generated (testdata/*.igs is git-ignored): make it on a fresh checkout, with OCP from the backend venv
if not LOOSE_IGES.exists():
    subprocess.run([str(BACKEND_PY), str(TESTDATA / "make_iges_loose.py")], check=True)

GUI = ".lil-gui.lil-root"

tmp = tempfile.mkdtemp(prefix="cad_fit_panels_")
try:
    # a private copy of the mold (five trailing newlines: its own hash, so its
    # own sidecar on a shared backend; nav_session's copy has three,
    # test_png_export.py's seven)
    MOLD_COPY = os.path.join(tmp, "mini_mold.step")
    Path(MOLD_COPY).write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 5)

    with nav_session(boxes=("runner",)) as n:
        page = n.page
        load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
        canvas_rect, ctl, click_button, set_mode = n.canvas_rect, n.ctl, n.click_button, n.set_mode
        rect, fill_check, fit = n.rect, n.fill_check, n.fit

        def panels():
            return n.panel_rects()

        def folder_title(name):
            return page.locator(".lil-gui .lil-title", has_text=name).first

        def resize(w, h):
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(300)
            settle()

        def local(xy):
            cl, ct, _, _ = canvas_rect()
            return (xy[0] - cl, xy[1] - ct)

        # ---- P1. the long runner at load (props held at 計算中…) ----------------
        load(n.paths["runner"])
        F, _ = n.free_area()
        print("P1 free area", F, "panels", panels())
        # the GUI column (right) and the HUD (bottom left) both bound it
        print("P1", fill_check(*RUNNER, "runner load", fallback=False, needs=(GUI, "#hud")))
        v = view()
        assert close(norm(sub(v["position"], v["target"])), LOAD_DIR, 1e-9), v
        assert close(v["up"], [0, 0, 1], 1e-12), v["up"]
        # pixels: what is drawn is where the corners project, clear of every panel
        ctl("グリッド").locator("input").click()
        settle()
        ink = n.canvas_ink_rect()
        want = rect(*RUNNER)
        print("P1 ink", [round(x, 1) for x in ink], "corners", [round(x, 1) for x in want])
        assert all(abs(a - b) <= 3 for a, b in zip(ink, want)), (ink, want)
        ink_local = local(ink[:2]) + local(ink[2:])
        for sel, p in panels().items():
            assert not overlaps(ink_local, p), ("drawn under a panel", sel, p, ink_local)
        ctl("グリッド").locator("input").click()
        settle()
        # picking goes through the same shifted projection: the top face centre
        top = (149, 13.75, 4.5)
        hit = pick(project(top))
        assert hit and hit["kind"] == "face" and math.dist(hit["point"], top) < 0.5, ("P1 pick", hit)
        # the target (rotation centre) sits at the view centre, through turns and presets
        centre = n.view_centre()
        t0 = v["target"]
        assert math.dist(project(t0), centre) <= 0.5, ("P1 target at the view centre", project(t0), centre)
        for _ in range(3):
            page.keyboard.press("ArrowRight")
        assert close(view()["target"], t0, 1e-9)
        assert math.dist(project(t0), centre) <= 0.5, ("P1 turn", project(t0), centre)
        click_button("正面")
        assert close(view()["target"], t0, 1e-9)
        assert math.dist(project(t0), n.view_centre()) <= 0.5, ("P1 preset", project(t0))
        click_button("等角")

        # ---- P3. the 視点 folder closed and open; the whole GUI collapsed --------
        # At 1280 x 800 the GUI's height does not change the runner's free area
        # (the band under it stays smaller than the column left of it): these
        # two steps cover the shorter and the taller GUI. P3c is the one where
        # the GUI's size decides.
        gui_open = panels()[GUI]
        folder_title("視点").click()
        fit()
        gui_closed = panels()[GUI]
        assert gui_closed[3] < gui_open[3] - 100, ("視点 closed: the GUI must be shorter", gui_open, gui_closed)
        print("P3 視点 closed", fill_check(*RUNNER, "視点 closed", fallback=False, needs=(GUI,)))
        folder_title("視点").click()
        fit()
        assert abs(panels()[GUI][3] - gui_open[3]) <= 0.5
        print("P3 視点 open", fill_check(*RUNNER, "視点 open", fallback=False, needs=(GUI,)))

        # P3c. the root collapsed to its title: the band under it is the free area
        page.locator(".lil-gui.lil-root > .lil-title").click()
        fit()
        _, _, W, H = canvas_rect()
        F, _ = n.free_area()
        g = panels()[GUI]
        assert g[3] - g[1] < 60, ("the GUI must be collapsed", g)
        assert F[2] == W and F[1] >= g[3] - 0.5, ("P3c: the band under the collapsed GUI", F, g)
        print("P3c collapsed", fill_check(*RUNNER, "GUI collapsed", fallback=False, needs=(GUI, "#hud")))
        page.locator(".lil-gui.lil-root > .lil-title").click()
        n.wait_gui_idle()

        # ---- P6. a resize keeps the shift in px (no re-fit) -----------------------
        fit()
        _, _, W, H = canvas_rect()
        F, _ = n.free_area()
        s = (W / 2 - (F[0] + F[2]) / 2, H / 2 - (F[1] + F[3]) / 2)
        assert s[0] > 100 and s[1] > 30, ("P6 needs a shift both ways", s)
        t0 = view()["target"]
        for w, want in (
            (1000, (500 - s[0], 400 - s[1])),
            # 0.3 of the width at most: 90 px at 300
            (300, (150 - min(s[0], 0.3 * 300), 400 - s[1])),
            # the stored shift was not clamped: it comes back in full
            (1280, (640 - s[0], 400 - s[1])),
        ):
            resize(w, 800)
            got = project(t0)
            print("P6", w, [round(x, 2) for x in got], "want", [round(x, 2) for x in want])
            assert math.dist(got, want) <= 0.5, ("P6 shift after a resize", w, got, want)
            assert close(view()["target"], t0, 1e-9), ("P6 a resize must not re-fit", w)
        fit()

        # ---- P4. 700 x 900 -------------------------------------------------------
        resize(700, 900)
        fit()
        F, fb = n.free_area()
        g = panels()[GUI]
        assert F[2] <= g[0] + 0.5, ("P4 left of the GUI", F, g)
        print("P4 700x900", fill_check(*RUNNER, "700x900", fallback=False, needs=(GUI,)))
        v0 = view()
        folder_title("表示").click()
        n.wait_gui_idle()
        v1 = view()
        # panels changing do not re-fit
        assert close(v1["position"], v0["position"], 1e-6) and close(v1["target"], v0["target"], 1e-6), "P4 re-fit"
        fit()
        _, _, W, H = canvas_rect()
        F, fb = n.free_area()
        g = panels()[GUI]
        assert F[1] >= g[3] - 0.5 and F[2] == W, ("P4 the band under the shorter GUI", F, g)
        print("P4 表示 closed", fill_check(*RUNNER, "700x900 表示 closed", fallback=False, needs=(GUI,)))
        folder_title("表示").click()
        n.wait_gui_idle()

        # ---- P5. narrow windows: fallback below MIN_FREE --------------------------
        resize(400, 900)
        fit()
        _, _, W, H = canvas_rect()
        part, _ = free_rect(W, H, list(panels().values()), min_free=0)
        assert part != (0, 0, W, H), ("P5 the panels must cover part of the canvas", part)
        print("P5 400x900", fill_check(*RUNNER, "400x900", fallback=True))
        cl, ct, _, _ = canvas_rect()
        tc = project(view()["target"])
        assert math.dist(tc, (cl + W / 2, ct + H / 2)) <= 0.5, ("P5 fallback: target at the canvas centre", tc)
        resize(450, 900)
        fit()
        _, _, W, H = canvas_rect()
        F, _ = n.free_area()
        assert 0.40 < (F[2] - F[0]) / W < 0.45, ("P5 just above MIN_FREE", F, W)
        print("P5 450x900", fill_check(*RUNNER, "450x900", fallback=False))
        resize(1280, 800)

        # ---- P2. an IGES with a short tree, then its 体積・重量 values -----------
        # pins a binding width independent of CI fonts; the fit reads whatever
        # rects are on screen, so the oracle stays independent
        page.add_style_tag(content="#props-panel{min-width:330px}")
        # the values are held for 2 s, so the load-time check runs while the
        # panel is still 計算中… (as at the load fit)
        load(LOOSE_IGES, props=2000)
        F, _ = n.free_area()
        tree = panels()["#tree-panel"]
        assert F[0] == 0 and F[1] >= tree[3] - 0.5, ("P2 the band under the short tree", F, tree)
        print("P2 load", fill_check(*LOOSE_BOX, "IGES load", needs=("#tree-panel", "#hud")))
        page.wait_for_function(
            "(() => { const e = document.querySelector('#props-total');"
            " return e && !e.classList.contains('hidden') })()",
            timeout=30000,
        )
        settle()
        fit()
        pr, g, hud = panels()["#props-panel"], panels()[GUI], panels()["#hud"]
        assert pr[0] <= g[0] - 60 and pr[1] <= hud[1] - 30, ("P2 the values panel must reach past the GUI and the HUD", pr, g, hud)
        print("P2 values", fill_check(*LOOSE_BOX, "IGES values", needs=("#props-panel", "#tree-panel", "#hud")))

        # ---- P7. the mold with a long measurement list ----------------------------
        empty_sidecar(page, MOLD_COPY)  # a previous failed run may have left entries
        load(MOLD_COPY)
        fit()
        print("P7 empty list", fill_check(*MOLD, "mold", needs=("#tree-panel",)))
        v0 = view()
        set_mode("注記")
        for i in range(12):
            pt = (8 + 7 * i, 5, 15)  # plate top, front strip: clear of the pins and the block
            xy = project(pt)
            hit = pick(xy)
            assert hit and hit["kind"] == "face" and math.dist(hit["point"], pt) < 0.5, ("P7 note point", pt, hit)
            for sel, p in panels().items():
                lx, ly = local(xy)
                assert not (p[0] <= lx <= p[2] and p[1] <= ly <= p[3]), ("P7 note point under a panel", pt, sel, p)
            page.mouse.click(*xy)
            page.wait_for_selector(".note-input", timeout=5000)
            # full-width text: CJK glyphs are 1 em in any font, so the list
            # reaches its CSS max-width (360 px) on any machine
            page.keyboard.insert_text(f"ゲート側の抜き勾配とR止まりを確認し、型側の合わせ面とエジェクタ位置も見るメモ{i:02d}")
            page.keyboard.press("Enter")
            page.wait_for_function(f"document.querySelectorAll('#measure-list li').length === {i + 1}", timeout=5000)
        set_mode("なし")
        settle()
        v1 = view()
        assert close(v1["position"], v0["position"], 1e-6) and close(v1["target"], v0["target"], 1e-6), "P7 re-fit"
        _, _, W, H = canvas_rect()
        m, g = panels()["#measure-panel"], panels()[GUI]
        assert m[3] - m[1] >= 0.3 * H and m[0] <= g[0] - 80, ("P7 the list must be long and wide", m, g)
        fit()
        print("P7 long list", fill_check(*MOLD, "mold, 12 notes", needs=("#measure-panel", "#tree-panel")))

        # reload: the list is restored before the one fit of the load. The
        # sidecar GET is delayed, and every frame's camera position is sampled:
        # a provisional fit drawn before the list is back would show up as a
        # third pose (neither the one before nor the final one)
        def slow_sidecar(route):
            if route.request.method == "GET":
                time.sleep(0.3)
            route.continue_()

        page.route("**/sidecar", slow_sidecar)
        try:
            page.evaluate(
                """() => { window.__poses = []; window.__sampling = true
                   const tick = () => { window.__poses.push(window.__cadView().position)
                     if (window.__sampling) requestAnimationFrame(tick) }
                   requestAnimationFrame(tick) }"""
            )
            pre = view()["position"]
            load(MOLD_COPY)
            page.evaluate("window.__sampling = false")
            poses = page.evaluate("window.__poses")
        finally:
            page.unroute("**/sidecar")
        assert page.locator("#measure-list li").count() == 12, "P7 the list must be restored"
        print("P7 reload", fill_check(*MOLD, "mold reload", needs=("#measure-panel",)))
        final = view()["position"]
        scale = max(map(abs, final))
        other = [q for q in poses if not (close(q, pre, 1e-9 * scale) or close(q, final, 1e-9 * scale))]
        print("P7 sampled frames", len(poses), "other poses", len(other))
        assert len(poses) >= 10, ("P7 too few frames sampled", len(poses))
        assert not other, ("P7 a provisional framing was drawn", other[:3], pre, final)

        # leave the private sidecar empty
        with page.expect_response(lambda r: "/sidecar" in r.url and r.request.method == "PUT", timeout=10000):
            ctl("計測クリア").locator("button").click()

        page.screenshot(path="/tmp/cad_viewer_nav_fit_panels.png")
        print("NAV FIT PANELS E2E OK")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
