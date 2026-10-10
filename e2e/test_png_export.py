"""E2E: save the view as a PNG (C3) — 3D with labels, white background, 2D drawings.

The expected pixels never come from the export code. They come from:
- the frame on screen (the WebGL canvas read with toDataURL inside rAF, as
  nav_common.canvas_ink_rect does), which the export must match;
- window.__cadProject for where the model and the measurement markers are;
- the DOM rects of the labels and of the panels;
- the DXF -> SVG mapping of the ezdxf background rect (200 x 100 mm and
  100 x 50 mm drawings) for the 2D checks;
- the DOM range of a word in a label for where its text is on screen;
- the colours of the specification (background #1d2126, markers #ffb020,
  dimension labels #ffd060) and contrast against white (WCAG luminance).

Viewport 1280 x 800 at devicePixelRatio 2 (1 for a while, through CDP, as
when the window moves to another monitor), time zone Asia/Tokyo, downloads
through Playwright's download event. The STEP is a private copy with seven
trailing newlines (its own hash, so its own model id and sidecar on a shared
backend); the DXF copy is named plate.drawing.dxf to check that only the last
extension is dropped from the file name.
"""
import base64
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright
import gui_common

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BACKEND_PY = Path(__file__).resolve().parents[1] / "backend" / ".venv" / "bin" / "python"
COLOURS_DXF = TESTDATA / "colours_drawing.dxf"
# generated (testdata/*.dxf is git-ignored): make it on a fresh checkout,
# with ezdxf from the backend venv
if not COLOURS_DXF.exists():
    subprocess.run([str(BACKEND_PY), str(TESTDATA / "make_dxf.py"), "colours_drawing"], check=True)
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
# 全体表示 frames the model clear of the panels (README), so a smaller window
# draws the mold too small: its dimension and note labels would touch
VIEW_W, VIEW_H, DPR = 1280, 800, 2
TZ = "Asia/Tokyo"
BG = (0x1D, 0x21, 0x26)  # scene background
MARKER = (0xFF, 0xB0, 0x20)  # measurement markers (3D spheres, 2D circles)
DIM = (0xFF, 0xD0, 0x60)  # dimension label background / 2D dimension text
PLATE = ((0, 0, 0), (100, 60, 15))  # make_step_assembly.py
MOLD = ((0, 0, 0), (100, 60, 40))  # plate + pins + block
CLICK_A = (50, 30, 35)  # cavity block top, centre
CLICK_B = (90, 10, 15)  # plate top, clear of the pins and the block (20.000 below A)
NOTE_AT = (10, 10, 15)  # plate top, front-left: left of the block, clear of the panels
EZDXF_PAGE = (33, 40, 48)  # the page ezdxf draws a drawing on (its background rect, #212830)
DRAW_PAGE = BG  # on screen a drawing's page is the 3D background: the viewer swaps ezdxf's
# runs of spaces: the page collapses them to one, an export must too
NOTE_WORD = "G1-ABC"
NOTE_TEXT = "ゲート      " + NOTE_WORD


def corners(lo, hi):
    return [[(hi if i & 1 else lo)[0], (hi if i & 2 else lo)[1], (hi if i & 4 else lo)[2]] for i in range(8)]


def grow(r, d):
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def inside(pt, r):
    return r[0] <= pt[0] <= r[2] and r[1] <= pt[1] <= r[3]


def decode(data):
    img = Image.open(io.BytesIO(data))
    rgba = np.asarray(img.convert("RGBA")).astype(int)
    return rgba[:, :, :3], rgba[:, :, 3]


def luminance(rgb):
    """WCAG relative luminance of 0-255 sRGB pixels (... x 3)"""
    c = np.asarray(rgb, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


tmp = tempfile.mkdtemp(prefix="cad_png_")
try:
    STEP = os.path.join(tmp, "mini_mold.step")
    Path(STEP).write_bytes((TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 7)
    DXF = os.path.join(tmp, "plate.drawing.dxf")
    shutil.copyfile(TESTDATA / "plate_drawing.dxf", DXF)
    STL = str(TESTDATA / "ribbed_plate.stl")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEW_W, "height": VIEW_H},
            device_scale_factor=DPR,
            timezone_id=TZ,
            accept_downloads=True,
        )
        page = context.new_page()
        errors = []
        downloads = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("download", lambda d: downloads.append(d))
        page.goto(BASE_URL)
        # a fresh context has empty storage; this only guards against a reused profile
        page.evaluate("localStorage.removeItem('cad-viewer:export'); localStorage.removeItem('cad-viewer:view')")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        def settle():
            page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

        def ctl(name):
            return gui_common.ctl(page, name)

        save_btn = page.locator("#toolbar button[data-action='png']")
        bg_select = ctl("画像の背景").locator("select")

        def blur():
            page.evaluate("document.activeElement && document.activeElement.blur()")

        def set_mode(label):
            ctl("モード").locator("select").select_option(label)
            blur()

        def set_background(label):
            bg_select.select_option(label=label)
            blur()

        def hud():
            return page.text_content("#hud-info")

        def rect_of(sel):
            """client rect (l, t, r, b) of the first visible match, or None"""
            return page.evaluate(
                """sel => { const e = [...document.querySelectorAll(sel)].find(
                    (x) => x.getClientRects().length && getComputedStyle(x).display !== 'none');
                  if (!e) return null; const r = e.getBoundingClientRect();
                  return [r.left, r.top, r.right, r.bottom] }""",
                sel,
            )

        def canvas_rect():
            return rect_of("#viewport canvas")

        def project(xyz):
            r = page.evaluate("([x, y, z]) => window.__cadProject(x, y, z)", list(xyz))
            return (r["x"], r["y"])

        def pick(xy):
            return page.evaluate("([x, y]) => window.__cadPick(x, y)", list(xy))

        def proj_rect(lo, hi):
            pts = [project(c) for c in corners(lo, hi)]
            return (min(q[0] for q in pts), min(q[1] for q in pts), max(q[0] for q in pts), max(q[1] for q in pts))

        def screen_frame():
            """the WebGL canvas as on screen (read inside rAF, right after the app's own render)"""
            url = page.evaluate(
                "new Promise(r => requestAnimationFrame(() =>"
                " r(document.querySelector('#viewport canvas').toDataURL())))"
            )
            rgb, _ = decode(base64.b64decode(url.split(",", 1)[1]))
            return rgb

        def export(tag):
            """click 画像を保存 and return (file name, RGB array, time before, time after)"""
            before = time.time()
            with page.expect_download(timeout=15000) as info:
                save_btn.click()
            dl = info.value
            after = time.time()
            path = os.path.join(tmp, f"{tag}.png")
            dl.save_as(path)
            shutil.copyfile(path, f"/tmp/cad_viewer_png_{tag}.png")
            rgb, alpha = decode(Path(path).read_bytes())
            assert alpha.min() == 255, (tag, "the PNG must be opaque")
            page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('画像を保存: ')")
            assert dl.suggested_filename in hud(), (hud(), dl.suggested_filename)
            return dl.suggested_filename, rgb, before, after

        def check_name(name, base, before, after):
            m = re.fullmatch(re.escape(base) + r"_(\d{8}-\d{6})\.png", name)
            assert m, ("file name", name, base)
            t = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=ZoneInfo(TZ)).timestamp()
            assert before - 1 <= t <= after + 1, ("local time in the name", name, before, after)

        # ---- pixel helpers (device px of the image; rects in client CSS px) ----
        def dev_box(r, origin, img):
            """client rect -> integer device-px box (x0, y0, x1, y1), clipped to the image"""
            h, w = img.shape[:2]
            x0 = max(0, int(np.floor((r[0] - origin[0]) * DPR)))
            y0 = max(0, int(np.floor((r[1] - origin[1]) * DPR)))
            x1 = min(w, int(np.ceil((r[2] - origin[0]) * DPR)))
            y1 = min(h, int(np.ceil((r[3] - origin[1]) * DPR)))
            return x0, y0, x1, y1

        def inner_box(r, origin):
            """client rect -> device-px box of the pixels fully inside it"""
            return (
                int(np.ceil((r[0] - origin[0]) * DPR)),
                int(np.ceil((r[1] - origin[1]) * DPR)),
                int(np.floor((r[2] - origin[0]) * DPR)),
                int(np.floor((r[3] - origin[1]) * DPR)),
            )

        def rect_mask(img, origin, rects):
            m = np.zeros(img.shape[:2], bool)
            for r in rects:
                x0, y0, x1, y1 = dev_box(r, origin, img)
                m[y0:y1, x0:x1] = True
            return m

        def patch(img, origin, xy, half):
            cx = int(round((xy[0] - origin[0]) * DPR))
            cy = int(round((xy[1] - origin[1]) * DPR))
            return img[cy - half : cy + half + 1, cx - half : cx + half + 1].reshape(-1, 3)

        def near_colour(px, col, tol):
            return np.all(np.abs(px - np.array(col)) <= tol, axis=-1)

        def corner_patches(img):
            return [img[:8, :8], img[:8, -8:], img[-8:, :8], img[-8:, -8:]]

        # ---- (e) nothing open: the button is disabled and does nothing --------
        assert save_btn.is_disabled(), "画像を保存 must be disabled with nothing open"
        save_btn.click(force=True)
        page.wait_for_timeout(1000)
        assert not downloads, "no download with nothing open"
        assert bg_select.evaluate("s => s.selectedOptions[0].text") == "画面のまま"

        # ---- (a) 3D, 画面のまま, grid off ---------------------------------------
        page.set_input_files("#file-input", STEP)
        page.wait_for_function(
            "(() => { const t = document.querySelector('#hud-info').textContent;"
            " return t.includes('三角形') && t.includes('mini_mold.step') })()",
            timeout=60000,
        )
        assert save_btn.is_enabled(), "a model is open: the button works"
        # the export renders once on demand; a buffer kept for every frame costs performance
        pdb = page.evaluate(
            "(() => { const c = document.querySelector('#viewport canvas');"
            " return (c.getContext('webgl2') || c.getContext('webgl')).getContextAttributes().preserveDrawingBuffer })()"
        )
        assert pdb is False, ("the renderer must not keep preserveDrawingBuffer", pdb)
        ctl("計測クリア").locator("button").click()  # a previous failed run may have left entries
        settle()
        for xyz in (CLICK_A, CLICK_B, NOTE_AT):
            hit = pick(project(xyz))
            assert hit and hit["kind"] == "face", ("the test points must hit a face", xyz, hit)
            assert max(abs(a - b) for a, b in zip(hit["point"], xyz)) < 0.5, ("hit where projected", xyz, hit)
        set_mode("計測")
        for xyz in (CLICK_A, CLICK_B):
            page.mouse.click(*project(xyz))
            page.wait_for_timeout(300)
        page.wait_for_function(
            "document.querySelector('#hud-info').textContent.includes('距離')", timeout=10000
        )
        assert "20.000" in hud(), hud()
        set_mode("注記")
        page.mouse.click(*project(NOTE_AT))
        page.wait_for_selector(".note-input", timeout=5000)
        page.keyboard.type(NOTE_TEXT)
        page.keyboard.press("Enter")
        page.wait_for_selector(".note-label", timeout=5000)
        assert page.text_content(".note-label") == NOTE_TEXT, ("the note keeps its spaces", page.text_content(".note-label"))
        set_mode("なし")
        ctl("グリッド").locator("input").click()
        blur()
        settle()
        page.wait_for_function(
            "(() => { const e = document.querySelector('#props-panel');"
            " return e && !e.classList.contains('hidden') && e.textContent.includes('体積') })()",
            timeout=30000,
        )
        settle()

        cl, ct, cr, cb = canvas_rect()
        origin = (cl, ct)
        cw, ch = cr - cl, cb - ct
        assert page.evaluate("devicePixelRatio") == DPR
        assert float(cw * DPR).is_integer() and float(ch * DPR).is_integer(), (cw, ch)
        dim_r = rect_of(".dim-label")
        note_r = rect_of(".note-label")
        assert dim_r and note_r, (dim_r, note_r)
        assert not overlap(dim_r, note_r), ("labels must not overlap", dim_r, note_r)
        markers = [project(CLICK_A), project(CLICK_B)]
        for m in markers:
            for r in (dim_r, note_r):
                assert not inside(m, grow(r, 4)), ("marker under a label", m, r)
        labels = [grow(dim_r, 2), grow(note_r, 2)]

        A0 = screen_frame()
        name, img, before, after = export("3d_screen")
        print("3D export:", name, img.shape)

        # 1. size: the canvas in device pixels
        assert img.shape[:2] == (int(ch * DPR), int(cw * DPR)), ("size", img.shape, cw, ch)
        assert A0.shape == img.shape, (A0.shape, img.shape)

        # 2. the model is where the projections say
        label_mask = rect_mask(img, origin, labels)
        ink = (np.abs(img - np.array(BG)).max(axis=2) > 6) & ~label_mask
        ys, xs = np.nonzero(ink)
        ink_box = (cl + xs.min() / DPR, ct + ys.min() / DPR, cl + (xs.max() + 1) / DPR, ct + (ys.max() + 1) / DPR)
        plate_r = proj_rect(*PLATE)
        mold_r = proj_rect(*MOLD)
        inner, outer = grow(plate_r, -3), grow(mold_r, 3)
        assert ink_box[0] <= inner[0] and ink_box[1] <= inner[1] and ink_box[2] >= inner[2] and ink_box[3] >= inner[3], (
            "model missing where the plate projects",
            ink_box,
            plate_r,
        )
        assert ink_box[0] >= outer[0] and ink_box[1] >= outer[1] and ink_box[2] <= outer[2] and ink_box[3] <= outer[3], (
            "ink outside the model",
            ink_box,
            mold_r,
        )
        assert np.abs(patch(img, origin, project(CLICK_A), 0)[0] - np.array(BG)).max() > 6

        # 2b. the image is the frame on screen, outside the labels painted on top
        d = np.abs(img - A0).max(axis=2)[~label_mask]
        same = np.mean(d <= 2)
        print("equal to the screen: %.5f, max diff %d" % (same, d.max()))
        assert same >= 0.999 and d.max() <= 24, ("not the frame on screen", same, d.max())

        # 2c. markers where the projections say (drawn last, depth test off)
        for m in markers:
            px = patch(img, origin, m, 1)
            assert near_colour(px, MARKER, 30).all(), ("marker missing at its projection", m, px.tolist())

        # 3. dimension label: yellow box with dark text
        x0, y0, x1, y1 = inner_box(dim_r, origin)
        box = img[y0:y1, x0:x1].reshape(-1, 3)
        yellow = np.mean(near_colour(box, DIM, 16))
        content = inner_box((dim_r[0] + 6, dim_r[1] + 3, dim_r[2] - 6, dim_r[3] - 3), origin)
        cbox = img[content[1] : content[3], content[0] : content[2]].reshape(-1, 3)
        dark = np.mean(cbox.sum(axis=1) < 200)
        print("dim label: yellow %.3f, text %.3f" % (yellow, dark))
        assert yellow >= 0.5, ("dimension label not painted", yellow)
        assert dark >= 0.05, ("dimension label text not painted", dark)

        # 4. note label: green box
        x0, y0, x1, y1 = inner_box(note_r, origin)
        box = img[y0:y1, x0:x1].reshape(-1, 3)
        green = np.mean((box[:, 1] - box[:, 0] >= 30) & (box[:, 1] - box[:, 2] >= 15))
        print("note label: green %.3f" % green)
        assert green >= 0.5, ("note label not painted", green)
        # 4b. its text is all there: the word after the run of spaces is painted
        #     where the page laid it out (the page shows one space, not six)
        word_r = page.evaluate(
            """word => { const t = document.querySelector('.note-label').firstChild
                const i = t.data.indexOf(word); const r = document.createRange()
                r.setStart(t, i); r.setEnd(t, i + word.length)
                const b = r.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom] }""",
            NOTE_WORD,
        )
        assert note_r[0] < word_r[0] < word_r[2] < note_r[2], ("the word is inside the label", word_r, note_r)
        x0, y0, x1, y1 = inner_box(word_r, origin)
        text_cols = (img[y0:y1, x0:x1].min(axis=2) >= 150).any(axis=0)
        third = max(1, (x1 - x0) // 3)
        print("note word columns with text: first third %.2f, all %.2f" % (text_cols[:third].mean(), text_cols.mean()))
        assert text_cols[:third].mean() >= 0.5 and text_cols.mean() >= 0.5, (
            "the note's last word is not where the page shows it",
            text_cols[:third].mean(),
            text_cols.mean(),
        )

        # 5. no panels: where they are on screen, the image shows the background
        panels = [r for r in (rect_of(s) for s in (".lil-gui.lil-root", "#hud", "#tree-panel", "#measure-panel", "#props-panel")) if r]
        assert len(panels) == 5, panels
        region = rect_mask(img, origin, panels) & ~rect_mask(img, origin, [grow(mold_r, 4)]) & ~label_mask
        print("panel region:", int(region.sum()), "device px")
        assert region.sum() >= 20000, ("panel region too small to tell", int(region.sum()))
        off = np.abs(img - np.array(BG)).max(axis=2)[region]
        assert off.max() <= 3, ("a panel is in the image", int(np.sum(off > 3)))

        # 6. (d) file name: <name without extension>_<local yyyyMMdd-HHmmss>.png
        check_name(name, "mini_mold", before, after)

        # 7. 白 with the grid hidden: no grid in the image, and the screen keeps it hidden
        S0 = screen_frame()
        set_background("白")
        name, img, before, after = export("3d_white_nogrid")
        S1 = screen_frame()
        assert np.abs(S0 - S1).max() <= 1, ("screen changed by a white export", int(np.abs(S0 - S1).max()))
        page_px = ~rect_mask(img, origin, [grow(mold_r, 4)] + labels)
        not_white = int((img.min(axis=2) < 248)[page_px].sum())
        print("white export, grid off: non-white page pixels", not_white)
        assert not_white == 0, ("a grid (or anything) on the white page with the grid off", not_white)
        assert not ctl("グリッド").locator("input").is_checked()

        # ---- (b) 3D, 白, grid on: white for the export only ------------------------
        ctl("グリッド").locator("input").click()
        blur()
        settle()
        A = screen_frame()
        bare = ~rect_mask(A, origin, [grow(mold_r, 4)] + labels)
        grid_px = (np.abs(A - np.array(BG)).max(axis=2) > 6) & bare
        G_A = int(grid_px.sum())
        print("grid pixels on screen:", G_A)
        assert G_A >= 1500, ("too little grid on screen to tell", G_A)
        set_background("白")
        name, img, before, after = export("3d_white")
        B = screen_frame()

        # 1. the screen is restored exactly
        assert np.abs(A - B).max() <= 1, ("screen not restored", int(np.abs(A - B).max()))
        # 2. white page in the image, 3. dark page on screen
        for c in corner_patches(img):
            assert np.mean(c.min(axis=2) >= 250) >= 0.75, ("image corner not white", c.reshape(-1, 3)[:4].tolist())
        for c in corner_patches(B):
            assert np.mean(near_colour(c, BG, 3)) >= 0.75, ("screen corner not dark", c.reshape(-1, 3)[:4].tolist())
        # 4. no dark grid (nor panels) on the white page
        dark_px = int(((img.min(axis=2) < 150) & bare).sum())
        print("dark pixels on the white page:", dark_px)
        assert dark_px <= 0.1 * G_A, ("dark grid on the white page", dark_px, G_A)
        # 4b. ... but a light grid where the grid is on screen
        g = img[grid_px].min(axis=1)
        light, not_dark = np.mean(g < 248), np.mean(g >= 150)
        print("grid positions in the white image: light %.3f, not dark %.3f" % (light, not_dark))
        assert light >= 0.5 and not_dark >= 0.9, ("no light grid on the white page", light, not_dark)
        # 5. the dimension label is still there
        x0, y0, x1, y1 = inner_box(dim_r, origin)
        assert np.mean(near_colour(img[y0:y1, x0:x1].reshape(-1, 3), DIM, 16)) >= 0.5
        check_name(name, "mini_mold", before, after)

        # ---- (b3) the screen's scale changes after the page opened ------------------
        # (the window moved to a monitor at 100 %): the canvas and the image follow
        cdp = context.new_cdp_session(page)

        def set_dpr(v):
            cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": VIEW_W, "height": VIEW_H, "deviceScaleFactor": v, "mobile": False},
            )
            page.wait_for_function(f"devicePixelRatio === {v}")

        set_dpr(1)
        assert canvas_rect() == [cl, ct, cr, cb], "same CSS size"
        # no resize: only the scale changed, and the screen is sharp at it
        page.wait_for_function(
            f"document.querySelector('#viewport canvas').width === {int(cw)}", timeout=5000
        )
        name, img, before, after = export("3d_dpr1")
        print("3D export at devicePixelRatio 1:", img.shape)
        assert img.shape[:2] == (int(ch), int(cw)), ("size after the scale change", img.shape, cw, ch)
        dim_r1 = rect_of(".dim-label")
        x0, y0 = int(np.ceil(dim_r1[0] - cl)), int(np.ceil(dim_r1[1] - ct))
        x1, y1 = int(np.floor(dim_r1[2] - cl)), int(np.floor(dim_r1[3] - ct))
        assert np.mean(near_colour(img[y0:y1, x0:x1].reshape(-1, 3), DIM, 16)) >= 0.5, "label at scale 1"
        set_dpr(DPR)
        page.wait_for_function(
            f"document.querySelector('#viewport canvas').width === {int(cw * DPR)}", timeout=5000
        )

        # ---- (b2) the choice survives a reload; empty the private sidecar --------
        with page.expect_response(
            lambda r: "/sidecar" in r.url and r.request.method == "PUT", timeout=10000
        ):
            ctl("計測クリア").locator("button").click()
        page.reload()
        page.wait_for_load_state("networkidle")
        assert bg_select.evaluate("s => s.selectedOptions[0].text") == "白", "画像の背景 must be remembered"
        assert save_btn.is_disabled()

        # ---- (c) 2D drawing ---------------------------------------------------------
        page.set_input_files("#file-input", DXF)
        page.wait_for_function(
            "document.querySelector('#hud-info').textContent.includes('2D 図面')", timeout=60000
        )
        assert save_btn.is_enabled()

        def dxf_client(x, y, size=(200, 100)):
            """DXF mm -> client px, through the ezdxf background rect (the drawing's extents)"""
            r = page.evaluate(
                """([x, y, w, h]) => {
                    const svg = document.querySelector('#viewport2d svg')
                    const bg = svg.querySelector(':scope > rect')
                    const s = bg.width.baseVal.value / w
                    const pt = new DOMPoint(x * s, (h - y) * s).matrixTransform(svg.getScreenCTM())
                    return [pt.x, pt.y] }""",
                [x, y, size[0], size[1]],
            )
            return (r[0], r[1])

        set_mode("計測")
        for q in ((50, 50), (150, 50)):
            page.mouse.click(*dxf_client(*q))
            page.wait_for_timeout(200)
        assert "100.000" in hud(), hud()
        set_mode("なし")
        vb0 = page.evaluate("document.querySelector('#viewport2d svg').getAttribute('viewBox')")
        page.mouse.move(*dxf_client(100, 70))
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(200)
        page.mouse.move(500, 450)
        page.mouse.down()
        for i in range(1, 7):
            page.mouse.move(500 - 10 * i, 450 + 25 * i / 6)
        page.mouse.up()
        settle()
        vb1 = page.evaluate("document.querySelector('#viewport2d svg').getAttribute('viewBox')")
        assert vb1 != vb0, ("the view must have moved", vb0, vb1)

        sl, st, sr, sb = rect_of("#viewport2d svg")
        sorigin = (sl, st)
        LINES = [(50, 60), (150, 60), (50, 40), (100, 100)]  # hole tops / bottom, the outline's top edge
        INTERIOR = (100, 75)
        HOLES = [(50, 50), (150, 50)]
        pts = {q: dxf_client(*q) for q in LINES + [INTERIOR] + HOLES + [(100, 50)]}
        for q, c in pts.items():
            assert sl + 10 <= c[0] <= sr - 10 and st + 10 <= c[1] <= sb - 10, ("sample point off screen", q, c)
        assert abs(pts[HOLES[0]][1] - pts[HOLES[1]][1]) <= 0.5, "the dimension line must be horizontal"
        hud_r = rect_of("#hud")
        gui_r = rect_of(".lil-gui.lil-root")

        def above(xy):
            return (xy[0], xy[1] - 3)  # inside the 5 px marker, clear of the line through its centre

        # 白 (remembered from (b2))
        name, img, before, after = export("2d_white")
        print("2D export (白):", name, img.shape)
        assert img.shape[:2] == (round((sb - st) * DPR), round((sr - sl) * DPR)), ("2D size", img.shape)
        for c in corner_patches(img):
            assert np.mean(c.min(axis=2) >= 250) >= 0.75, ("2D corner not white", c.reshape(-1, 3)[:4].tolist())
        for q in LINES:
            px = patch(img, sorigin, pts[q], 2)
            assert px.max(axis=1).min() <= 80, ("2D line missing (白: black lines)", q, px.tolist())
        px = patch(img, sorigin, pts[INTERIOR], 2)
        assert px.min() >= 250, ("2D page not white", px.tolist())
        for q in HOLES:
            px = patch(img, sorigin, above(pts[q]), 1)
            assert near_colour(px, MARKER, 25).all(), ("2D marker missing", q, px.tolist())
        mid = pts[(100, 50)]
        x0, y0, x1, y1 = dev_box((mid[0], mid[1] - 13, mid[0] + 50, mid[1] - 3), sorigin, img)
        text_px = int(near_colour(img[y0:y1, x0:x1], DIM, 20).sum())
        halo_px = int(near_colour(img[y0:y1, x0:x1], BG, 12).sum())
        print("2D dimension text pixels:", text_px, "dark outline pixels:", halo_px)
        assert text_px >= 20, ("2D dimension text missing", text_px)
        # the pale value reads on white through its dark outline (3 px on screen)
        assert halo_px >= 100, ("2D dimension text has no dark outline", halo_px)
        for r in (gui_r, hud_r):
            x0, y0, x1, y1 = dev_box(r, sorigin, img)
            share = np.mean(img[y0:y1, x0:x1].max(axis=2) < 100)
            assert share <= 0.05, ("a panel is in the 2D image", r, share)
        # 3. only the last extension goes (meta.name would be plate_drawing.dxf if deduplicated)
        check_name(name, "plate.drawing", before, after)

        # 画面のまま
        set_background("画面のまま")
        name, img, before, after = export("2d_screen")
        for q in LINES:
            px = patch(img, sorigin, pts[q], 2)
            assert px.min(axis=1).max() >= 180, ("2D line missing (white lines)", q, px.tolist())
        px = patch(img, sorigin, pts[INTERIOR], 1)
        assert near_colour(px, DRAW_PAGE, 2).all(), ("2D page colour", px.tolist())
        for q in HOLES:
            px = patch(img, sorigin, above(pts[q]), 1)
            assert near_colour(px, MARKER, 25).all(), ("2D marker missing", q, px.tolist())
        check_name(name, "plate.drawing", before, after)

        # ---- (c2) a double-click saves one file: clicks during an export are dropped --
        k = len(downloads)
        with page.expect_download(timeout=15000):
            save_btn.dblclick()
        page.wait_for_timeout(2000)
        print("downloads from a double-click:", len(downloads) - k)
        assert len(downloads) == k + 1, ("a double-click must save one file", len(downloads) - k)

        # ---- (f) 白 for a drawing with a WIPEOUT and light colours ---------------------
        page.set_input_files("#file-input", str(COLOURS_DXF))
        page.wait_for_function(
            "document.querySelector('#hud-info').textContent.includes('colours_drawing.dxf')", timeout=60000
        )
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('2D 図面')")
        settle()
        set_background("白")
        CSIZE = (100, 50)
        sl, st, sr, sb = rect_of("#viewport2d svg")
        sorigin = (sl, st)
        name, img, before, after = export("2d_colours_white")
        for c in corner_patches(img):
            assert np.mean(c.min(axis=2) >= 250) >= 0.75, ("corner not white", c.reshape(-1, 3)[:4].tolist())
        # 1. the wipeout (page-coloured on screen, so unseen) is white, not a dark box;
        #    neither page colour (the screen's, ezdxf's) is left, but for the
        #    line drawn in #1d2126 itself (y 45, x 5..45): the screen swaps the
        #    page to that very colour, and the white page must not take the line
        a, b = dxf_client(3, 47, CSIZE), dxf_client(47, 43, CSIZE)
        lx0, ly0, lx1, ly1 = dev_box((a[0], a[1], b[0], b[1]), sorigin, img)
        page_mask = near_colour(img, DRAW_PAGE, 6) | near_colour(img, EZDXF_PAGE, 6)
        page_mask[ly0:ly1, lx0:lx1] = False
        page_dark = int(page_mask.sum())
        wipe = patch(img, sorigin, dxf_client(25, 20, CSIZE), 10)
        print("page-coloured pixels:", page_dark, "wipeout centre min", int(wipe.min()))
        assert page_dark <= 20, ("the drawing's page colour is left on the white page", page_dark)
        assert wipe.min() >= 250, ("the wipeout is not white", wipe[:4].tolist())
        native = patch(img, sorigin, dxf_client(25, 45, CSIZE), 3)
        darkest_native = native[int(np.argmin(luminance(native)))]
        print("the #1d2126 line:", darkest_native.tolist())
        assert all(abs(int(c) - t) <= 12 for c, t in zip(darkest_native, DRAW_PAGE)), (
            "the line drawn in #1d2126 went white with the page", darkest_native.tolist())
        # 2. the ACI 7 outline is black
        px = patch(img, sorigin, dxf_client(30, 50, CSIZE), 3)
        assert px.max(axis=1).min() <= 80, ("outline not black", px.tolist())

        # 3. light lines are darkened to read on white, with their hue kept
        def darkest(xy):
            px = patch(img, sorigin, xy, 4)
            return px[int(np.argmin(luminance(px)))]

        yel = darkest(dxf_client(72.5, 40, CSIZE))
        cya = darkest(dxf_client(60, 20, CSIZE))
        print("yellow line", yel.tolist(), "cyan line", cya.tolist())
        assert luminance(yel) <= 0.30 and luminance(cya) <= 0.30, ("light line under 3:1 on white", yel, cya)
        assert yel[0] - yel[2] >= 60 and yel[1] - yel[2] >= 60 and abs(yel[0] - yel[1]) <= 20, ("not yellow", yel)
        assert cya[1] - cya[0] >= 60 and cya[2] - cya[0] >= 60 and abs(cya[1] - cya[2]) <= 20, ("not cyan", cya)
        # 4. the yellow text: dark yellow ink, no pure yellow left
        a, b = dxf_client(64, 16, CSIZE), dxf_client(97, 9, CSIZE)
        x0, y0, x1, y1 = dev_box((a[0], a[1], b[0], b[1]), sorigin, img)
        box = img[y0:y1, x0:x1].reshape(-1, 3)
        yellowish = (box[:, 0] - box[:, 2] >= 60) & (box[:, 1] - box[:, 2] >= 60)
        ink = int((yellowish & (luminance(box) <= 0.30)).sum())
        bright = int(near_colour(box, (255, 255, 0), 60).sum())
        print("yellow text: dark ink", ink, "pure yellow", bright)
        assert ink >= 100 and bright == 0, ("yellow text not darkened", ink, bright)
        # 5. the screen is untouched: its page stays the 3D background
        assert page.evaluate("document.querySelector('#viewport2d svg > rect').getAttribute('fill')") == "#1d2126"
        check_name(name, "colours_drawing", before, after)

        # ---- (e2) a load that fails after the teardown disables the button again --
        page.route("**/mesh.bin", lambda route: route.abort())
        page.set_input_files("#file-input", STL)
        page.wait_for_function("document.querySelector('#hud-info').textContent.includes('エラー')", timeout=30000)
        page.unroute("**/mesh.bin")
        assert save_btn.is_disabled(), "nothing on screen after a failed load: the button must be disabled"

        n = len(downloads)
        assert n == 8, ("one download per export", n)
        errors = [e for e in errors if "Failed to load resource" not in e]  # the aborted mesh request
        if errors:
            print("PAGE ERRORS:", errors)
        assert not errors
        print("PNG EXPORT E2E OK")
        browser.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
