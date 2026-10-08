"""E2E: parallel projection (投影 = 平行, #8 A3) — switching, fit, pixels, preferences.

Expected values never come from the code under test (rule of nav_common.py):
the camera state (__cadView), projections of known points (__cadProject),
canvas pixels, the geometry of mini_mold.step (make_step_assembly.py) and of
STL boxes written here, the constants of the specification (fill 0.88, wheel
step 0.9, fov 50°, near = r / 500, MIN_ZOOM_NEARS 4, far = 200 r,
MAX_ZOOM_FAR 0.25, load direction (1, -1, 0.7)) and the same quantity measured
in the other projection.

Sidecars stay in the page (Nav.stub_sidecar): measures left on the shared
backend would be drawn into the canvas.

T1 default; T2 switching keeps direction, up, target and size, and a round
trip comes back; T2b switching at the near stop; T3 parallel in pixels (two
equal boxes at different depths are congruent on screen); T4 fit in parallel;
T5 true proportions seen square-on; T6 preference stored and validated; T7 2D
drawings; T8 resize.
"""
import math
import os
import shutil
import tempfile

import numpy as np

from nav_common import (
    BG, DXF, HUGE, LOAD_DIR, MOLD, RUNNER, STEP, SURFACE, TINY,
    add, boxes_stl, close, corners, cross, dot, length, mul, nav_session, norm, sub,
)

# make_step_assembly.py: plate, cavity block, two core pins (r 4, z 15..40)
PLATE = ((0, 0, 0), (100, 60, 15))
BLOCK = ((30, 15, 15), (70, 45, 35))
PINS = ((25, 30), (75, 30))
CAV_TOP = (50, 30, 35)
# two identical boxes, apart on screen in 等角 and in 上, at different depths
BOX_A = ((0, 0, 0), (30, 15, 10))
BOX_B = ((60, 60, 40), (90, 75, 50))


def mold_points():
    """points whose projections bound mini_mold's silhouette (the pins as 72-gons)"""
    pts = corners(*PLATE) + corners(*BLOCK)
    for cx, cy in PINS:
        for k in range(72):
            a = 2 * math.pi * k / 72
            for z in (15, 40):
                pts.append([cx + 4 * math.cos(a), cy + 4 * math.sin(a), z])
    return pts


tmp = tempfile.mkdtemp(prefix="cad_ortho_")
try:
    TWO = os.path.join(tmp, "two_boxes.stl")
    boxes_stl(TWO, [BOX_A, BOX_B])
    with nav_session(boxes=("runner", "tiny", "huge")) as n:
        page = n.page
        paths = n.paths
        n.stub_sidecar()
        load, settle, view, project, pick = n.load, n.settle, n.view, n.project, n.pick
        ctl, click_button, set_rotate, set_projection = n.ctl, n.click_button, n.set_rotate, n.set_projection
        direction, same_dir, rect, fill_check, depth_check = n.direction, n.same_dir, n.rect, n.fill_check, n.depth_check
        kscale, canvas_rect = n.kscale, n.canvas_rect

        def grid(on):
            box = ctl("グリッド").locator("input")
            if box.is_checked() != on:
                box.click()
            page.evaluate("document.activeElement && document.activeElement.blur()")
            settle()

        def ink_mask():
            """(mask of non-background canvas pixels, canvas px per CSS px)"""
            img = np.asarray(n.canvas_image()).astype(int)
            cl, ct, cw, ch = canvas_rect()
            mask = np.abs(img - np.array(BG)).max(axis=2) > 6
            return mask, img.shape[1] / cw

        def ink_rect():
            cl, ct, cw, ch = canvas_rect()
            mask, s = ink_mask()
            ys, xs = np.nonzero(mask)
            assert len(xs), "nothing drawn"
            return cl + xs.min() / s, ct + ys.min() / s, cl + (xs.max() + 1) / s, ct + (ys.max() + 1) / s

        def points_rect(pts):
            q = n.project_many(pts)
            return min(p[0] for p in q), min(p[1] for p in q), max(p[0] for p in q), max(p[1] for p in q)

        def two_blobs():
            """the ink split at its widest empty column gap: [(bbox, cropped mask), ...] left to right"""
            mask, s = ink_mask()
            cols = np.nonzero(mask.any(axis=0))[0]
            gaps = np.diff(cols)
            g = int(np.argmax(gaps))
            assert gaps[g] > 5, ("the two boxes touch on screen", gaps[g])
            out = []
            for c0, c1 in ((cols[0], cols[g] + 1), (cols[g + 1], cols[-1] + 1)):
                sub_mask = mask[:, c0:c1]
                ys = np.nonzero(sub_mask.any(axis=1))[0]
                y0, y1 = ys[0], ys[-1] + 1
                out.append(((c0 / s, y0 / s, c1 / s, y1 / s), sub_mask[y0:y1]))
            return out

        def iou_aligned(a, b):
            h = max(a.shape[0], b.shape[0])
            w = max(a.shape[1], b.shape[1])
            pa = np.zeros((h, w), bool)
            pb = np.zeros((h, w), bool)
            pa[: a.shape[0], : a.shape[1]] = a
            pb[: b.shape[0], : b.shape[1]] = b
            return (pa & pb).sum() / (pa | pb).sum()

        def stored():
            return page.evaluate("JSON.parse(localStorage.getItem('cad-viewer:view') || 'null')")

        # ---- T1. default: perspective --------------------------------------------
        assert view()["projection"] == "perspective", view()
        assert n.projection_label() == "透視", n.projection_label()
        assert not page.locator("#triad").is_visible()

        # ---- T2. switching keeps the view; a round trip comes back -----------------
        load(STEP)
        grid(False)
        for mode in ("ターンテーブル", "自由回転"):
            if mode == "自由回転":
                n.setup_view(mode)  # 等角, rolled, fit
            v0 = view()
            k0 = kscale(v0)
            set_projection("平行")
            v1 = view()
            assert v1["projection"] == "orthographic", v1
            same_dir(v0, v1, 1e-9)
            assert close(v1["up"], v0["up"], 1e-9), (mode, v1["up"], v0["up"])
            assert close(v1["target"], v0["target"], 1e-9 * 100), (mode, v1["target"], v0["target"])
            k1 = kscale(v1)
            assert abs(k1 / k0 - 1) <= 1e-6, (mode, "size at the target", k0, k1)
            depth_check(*MOLD)
            ink = ink_rect()
            want = points_rect(mold_points())
            print("T2", mode, "ink", [round(x, 1) for x in ink], "points", [round(x, 1) for x in want])
            assert all(abs(a - b) <= 3 for a, b in zip(ink, want)), (mode, ink, want)
            set_projection("透視")
            v2 = view()
            assert v2["projection"] == "perspective"
            d0 = length(sub(v0["position"], v0["target"]))
            assert close(v2["position"], v0["position"], 1e-9 * d0), (mode, "round trip", v2["position"], v0["position"])
            assert close(v2["up"], v0["up"], 1e-9), (mode, v2["up"], v0["up"])
            print("T2", mode, "ok")
        set_rotate("ターンテーブル")

        # ---- T2b. switch at the perspective near stop -----------------------------
        page.keyboard.press("f")
        settle()
        cur = n.project(SURFACE)
        page.mouse.move(*cur)
        for _ in range(30):
            page.mouse.wheel(0, -300)
        settle()
        set_projection("平行")
        # step back until the whole model is on the canvas (with room for the pins)
        cl, ct, cw, ch = canvas_rect()
        for i in range(150):
            r = points_rect(mold_points())
            if r[0] > cl + 20 and r[1] > ct + 20 and r[2] < cl + cw - 20 and r[3] < ct + ch - 20:
                break
            page.keyboard.press("-")
        else:
            raise AssertionError(("T2b the model never fitted", r))
        settle()
        depth_check(*MOLD)
        ink = ink_rect()
        want = points_rect(mold_points())
        print("T2b", i, "presses; ink", [round(x, 1) for x in ink], "points", [round(x, 1) for x in want])
        assert all(abs(a - b) <= 3 for a, b in zip(ink, want)), ("T2b", ink, want)
        h = pick(project(CAV_TOP))
        assert h and math.dist(h["point"], CAV_TOP) < 1e-3, ("T2b pick", h)
        set_projection("透視")

        # ---- T3. parallel in pixels: equal boxes at different depths are congruent --
        load(TWO)
        grid(False)
        set_projection("平行")
        click_button("等角")
        page.keyboard.press("f")
        settle()
        v = view()
        f = direction(v)
        da = dot(sub([15, 7.5, 5], v["position"]), f)
        db = dot(sub([75, 67.5, 45], v["position"]), f)
        assert da - db > 20, ("box B must be nearer", da, db)
        (ra, ma), (rb, mb) = two_blobs()
        wa, ha = ra[2] - ra[0], ra[3] - ra[1]
        wb, hb = rb[2] - rb[0], rb[3] - rb[1]
        iou = iou_aligned(ma, mb)
        print("T3 ortho", (round(wa, 1), round(ha, 1)), (round(wb, 1), round(hb, 1)), "iou", round(iou, 4))
        assert abs(wa - wb) <= 1 and abs(ha - hb) <= 1, ("T3 sizes", wa, ha, wb, hb)
        assert iou >= 0.95, ("T3 shapes", iou)
        set_projection("透視")
        page.keyboard.press("f")
        settle()
        (ra, ma), (rb, mb) = two_blobs()
        area_a = (ra[2] - ra[0]) * (ra[3] - ra[1])
        area_b = (rb[2] - rb[0]) * (rb[3] - rb[1])
        print("T3 persp areas", round(area_a), round(area_b))
        assert area_b > 1.03 * area_a, ("T3 control: perspective draws the nearer box larger", area_a, area_b)

        # ---- T5. true proportions seen square-on (上) ------------------------------
        set_projection("平行")
        click_button("上")
        page.keyboard.press("f")
        settle()
        (ra, _), (rb, _) = two_blobs()
        cl, ct, cw, ch = canvas_rect()
        for tag, r, (lo, hi) in (("A", ra, BOX_A), ("B", rb, BOX_B)):
            w, h = r[2] - r[0], r[3] - r[1]
            assert abs(w / h - 2) <= 3 / h, ("T5 aspect", tag, w, h)
            top = points_rect([[x, y, hi[2]] for x in (lo[0], hi[0]) for y in (lo[1], hi[1])])
            page_r = (cl + r[0], ct + r[1], cl + r[2], ct + r[3])
            assert all(abs(a - b) <= 2 for a, b in zip(page_r, top)), ("T5 rect", tag, page_r, top)
        assert abs((ra[2] - ra[0]) - (rb[2] - rb[0])) <= 2, ("T5 widths", ra, rb)
        print("T5 ortho", [round(x, 1) for x in ra], [round(x, 1) for x in rb])
        set_projection("透視")
        page.keyboard.press("f")
        settle()
        (ra, _), (rb, _) = two_blobs()
        print("T5 persp widths", round(ra[2] - ra[0], 1), round(rb[2] - rb[0], 1))
        assert (rb[2] - rb[0]) > 1.05 * (ra[2] - ra[0]), ("T5 control", ra, rb)
        # the extra: mini_mold's four vertical plate edges are equal on screen in 平行
        load(STEP)
        set_projection("平行")
        click_button("等角")
        page.keyboard.press("f")
        settle()
        vecs = []
        for x, y in ((0, 0), (100, 0), (100, 60), (0, 60)):
            a, b = project((x, y, 0)), project((x, y, 15))
            vecs.append((b[0] - a[0], b[1] - a[1]))
        l0 = math.hypot(*vecs[0])
        for vv in vecs[1:]:
            assert abs(vv[0] * vecs[0][1] - vv[1] * vecs[0][0]) / (l0 * math.hypot(*vv)) < 1e-9, ("T3 parallel", vecs)
            assert abs(math.hypot(*vv) / l0 - 1) < 1e-6, ("T3 lengths", vecs)
        print("T3/T5 ok")

        # ---- T4. fit in parallel ---------------------------------------------------
        load(paths["runner"])
        v = view()
        assert v["projection"] == "orthographic", "the projection survives a load"
        assert close(direction(v), mul(LOAD_DIR, -1), 1e-9), v
        print("T4 load", fill_check(*RUNNER, "runner"))
        depth_check(*RUNNER)
        triggers = ["f", "Home", "F", "button"]
        for i, preset in enumerate(["正面", "上", "右", "等角", "左"]):
            click_button(preset)
            for _ in range(3):
                page.keyboard.press("-")
            for _ in range(2):
                page.keyboard.press("Shift+ArrowRight")
            v0 = view()
            trig = triggers[i % len(triggers)]
            if trig == "button":
                click_button("全体表示")
            else:
                page.keyboard.press(trig)
            settle()
            v1 = view()
            same_dir(v0, v1)
            print("T4", preset, trig, fill_check(*RUNNER, preset))
            depth_check(*RUNNER)
        page.set_viewport_size({"width": 600, "height": 900})
        page.wait_for_timeout(300)
        page.keyboard.press("f")
        settle()
        print("T4 narrow", fill_check(*RUNNER, "600x900"))
        page.set_viewport_size({"width": 1280, "height": 800})
        page.wait_for_timeout(300)
        set_rotate("自由回転")
        for _ in range(20):
            page.keyboard.press("ArrowUp")
        for _ in range(5):
            page.keyboard.press("ArrowRight")
        v0 = view()
        page.keyboard.press("f")
        settle()
        v1 = view()
        same_dir(v0, v1)
        assert abs(v1["up"][2]) < 0.9, ("T4 still rolled", v1["up"])
        print("T4 free", fill_check(*RUNNER, "free"))
        set_rotate("ターンテーブル")
        for name, box in (("tiny", TINY), ("huge", HUGE)):
            load(paths[name])
            v = view()
            assert v["projection"] == "orthographic" and close(direction(v), mul(LOAD_DIR, -1), 1e-9), (name, v)
            print("T4", name, fill_check(*box, name))
            depth_check(*box)
        load(STEP)
        assert view()["projection"] == "orthographic"
        print("T4 mold", fill_check(*MOLD, "mold"))

        # ---- T8. resize keeps the scale; square-on proportions ---------------------
        k0 = kscale()
        page.set_viewport_size({"width": 900, "height": 800})
        page.wait_for_timeout(300)
        settle()
        k1 = kscale()
        assert abs(k1 / k0 - 1) <= 1e-6, ("T8 resize changed the scale", k0, k1)
        grid(False)
        for mode, tol in (("自由回転", 1e-6), ("ターンテーブル", 1e-5)):
            set_rotate(mode)
            click_button("上")
            page.keyboard.press("f")
            settle()
            r = points_rect([[x, y, 15] for x in (0, 100) for y in (0, 60)])
            ratio = (r[2] - r[0]) / (r[3] - r[1])
            assert abs(ratio - 100 / 60) <= tol, ("T8 plate top", mode, ratio)
            ink = ink_rect()
            assert all(abs(a - b) <= 2 for a, b in zip(ink, r)), ("T8 ink", mode, ink, r)
            print("T8", mode, round(ratio, 9))
        set_rotate("ターンテーブル")
        page.set_viewport_size({"width": 1280, "height": 800})
        page.wait_for_timeout(300)
        grid(True)

        # ---- T7. 2D drawings hide the row; back in 3D the projection is kept --------
        load(DXF, wait_text="2D図面")
        assert not ctl("投影").is_visible(), "the projection row must be hidden on a drawing"
        load(STEP)
        assert ctl("投影").is_visible()
        assert view()["projection"] == "orthographic"
        print("T7", fill_check(*MOLD, "after 2D"))

        # ---- T6. the preference: stored, restored, validated -----------------------
        s = stored()
        assert s and s["projection"] == "orthographic", s
        page.reload()
        page.wait_for_load_state("networkidle")
        assert view()["projection"] == "orthographic", "restored before any load"
        assert n.projection_label() == "平行"
        load(STEP)
        assert view()["projection"] == "orthographic"
        fill_check(*MOLD, "restored")
        for bad in ("fisheye", 1, None):
            page.evaluate(
                "v => localStorage.setItem('cad-viewer:view', JSON.stringify({grid: false, projection: v}))", bad
            )
            page.reload()
            page.wait_for_load_state("networkidle")
            v = view()
            assert v["projection"] == "perspective", (bad, v)
            assert n.projection_label() == "透視", (bad, n.projection_label())
            assert v["gridVisible"] is False, ("the other preferences are kept", bad, v)
        set_projection("平行")
        assert stored()["projection"] == "orthographic"
        set_projection("透視")
        assert stored()["projection"] == "perspective", stored()
        print("T6 ok")
        page.screenshot(path="/tmp/cad_viewer_ortho.png")
    print("ORTHO E2E OK")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
