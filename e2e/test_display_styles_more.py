"""E2E: 表示スタイル (A4) — depth writes, STL, keyboard, persistence, loose curves.

(c3) 半透明 writes no depth: a wall behind another wall of the same STL shows
through it, from either side (whatever order the triangles are drawn in);
(g) an STL in ワイヤーフレーム shows its triangles, not its faces, and is still
picked; a switch builds no geometry; (k) after choosing a style the arrow keys
turn the view; (f) the style applies to newly loaded models, survives a reload
and a 2D drawing, and a bad stored value falls back to the default; (i) loose
curves stay drawn in every style.

Expected values: display_common.py. The STLs are written to a temp directory;
the IGES fixture is generated like test_iges_sewing.py does.
"""
import os
import subprocess
from pathlib import Path

import numpy as np

from display_common import BG, CURVE, TESTDATA, box_stl, diff, display_session, pt_seg, quad, tri_stl

BACKEND_PY = Path(__file__).resolve().parents[1] / "backend" / ".venv" / "bin" / "python"
IGES = TESTDATA / "loose_faces_box.igs"
# generated (testdata/*.igs is git-ignored): make it on a fresh checkout, with
# OCP from the backend venv
if not IGES.exists():
    subprocess.run([str(BACKEND_PY), str(TESTDATA / "make_iges_loose.py")], check=True)
DXF = str(TESTDATA / "plate_drawing.dxf")

# (c3) two parallel walls 40 apart, and each wall alone; a tiny triangle in the
# opposite corner gives every model the same bounding box, so the same camera
A = quad((0, 0, 0), (40, 0, 0), (40, 0, 40), (0, 0, 40))
B = quad((0, 40, 0), (40, 40, 0), (40, 40, 40), (0, 40, 40))
TINY_HI = [((40, 40, 40), (39.9, 40, 40), (40, 40, 39.9))]
TINY_LO = [((0, 0, 0), (0.1, 0, 0), (0, 0, 0.1))]
WALL_SAMPLES = {"正面": (12, 0, 28), "背面": (12, 40, 28)}
# (g) a flat STL box
BOX = ((0, 0, 0), (100, 60, 10))
BOX_DIAG = ((0, 0, 10), (100, 60, 10))  # a triangle edge of the top face
BOX_I = (75, 15, 10)  # top face, clear of every triangle edge


def box_tri_edges(lo, hi):
    """the triangle edges of nav_common.box_stl's box (12 box edges + 6 face diagonals)"""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    edges = set()
    for a, b, c, dd in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]:
        for t in ((a, b, c), (a, c, dd)):
            for i in range(3):
                edges.add(tuple(sorted((t[i], t[(i + 1) % 3]))))
    return [(list(v[i]), list(v[j])) for i, j in sorted(edges)]


with display_session() as d:
    page = d.page
    paths = {}
    for name, tris in (("walls", A + B), ("ref_a", A + TINY_HI), ("ref_b", B + TINY_LO)):
        paths[name] = os.path.join(d.tmp, f"{name}.stl")
        tri_stl(paths[name], tris)
    paths["box"] = os.path.join(d.tmp, "box.stl")
    box_stl(paths["box"], *BOX)

    # ---- (c3) 半透明 writes no depth --------------------------------------------
    d.select_style("xray")
    cam0 = None
    cams = {}
    px = {}
    for name in ("walls", "ref_a", "ref_b"):
        d.load(paths[name])
        if name == "walls":
            d.grid_off()
        v = d.view()
        cam = v["position"] + v["target"] + v["up"]
        cam0 = cam0 or cam
        assert max(abs(a - b) for a, b in zip(cam, cam0)) <= 1e-9, ("same box, same camera", name, cam, cam0)
        for view, xyz in WALL_SAMPLES.items():
            d.preset(view)  # the fit depends only on the box and the direction: the same for all three
            v = d.view()
            cams.setdefault(view, v["position"] + v["target"] + v["up"])
            assert max(abs(a - b) for a, b in zip(v["position"] + v["target"] + v["up"], cams[view])) <= 1e-9, (name, view)
            if name == "walls":
                # the view ray through the sample meets the far wall well inside it
                C = d.view()["position"]
                far_y = 40 - xyz[1]
                t = (far_y - C[1]) / (xyz[1] - C[1])
                far = [C[i] + (xyz[i] - C[i]) * t for i in range(3)]
                assert 3 <= far[0] <= 37 and 3 <= far[2] <= 37, ("far wall hit", view, far)
            for key in ("xray", "shaded-edges"):
                d.select_style(key)
                px[(name, view, key)] = d.px(d.frame(), d.project(xyz))
            d.select_style("xray")
    for view, ref in (("正面", "ref_a"), ("背面", "ref_b")):
        dx = diff(px[("walls", view, "xray")], px[(ref, view, "xray")]).max()
        do = diff(px[("walls", view, "shaded-edges")], px[(ref, view, "shaded-edges")]).max()
        print("(c3)", view, "walls vs front wall alone: 半透明 %d, 陰影＋稜線 %d" % (dx, do),
              px[("walls", view, "xray")], px[(ref, view, "xray")])
        assert dx >= 8, ("半透明: the far wall of the same part must show through", view, dx)
        assert do <= 2, ("opaque: the near wall hides the far one", view, do)

    # ---- (g) STL in ワイヤーフレーム: triangle edges, no faces --------------------
    d.load(paths["box"])
    d.preset("上")
    segs = d.segments(box_tri_edges(*BOX))
    i_xy = d.project(BOX_I)
    clear = min(pt_seg(i_xy, a, b) for a, b in segs)
    assert clear >= 10, ("I too close to a triangle edge", clear)
    g0, g1 = d.project(BOX_DIAG[0]), d.project(BOX_DIAG[1])

    def diag_bins(img):
        return d.band(img, g0, g1, 8, 0.15, 0.85)

    d.select_style("wireframe")
    img = d.frame()
    lit = sum(1 for b, _ in diag_bins(img) if len(b) and (b - np.array(BG)).max() >= 40)
    i_wire = d.px(img, i_xy)
    hit = d.pick(i_xy)
    print("(g) ワイヤーフレーム: diagonal bins lit", lit, "I", i_wire, "pick", hit)
    assert lit >= 6, ("the STL's triangle edges must show", lit)
    assert diff(i_wire, BG).max() <= 8, ("the STL's faces must not be drawn", i_wire)
    assert hit and hit["kind"] == "face" and hit["id"] == -1, hit
    assert max(abs(a - b) for a, b in zip(hit["point"], BOX_I)) <= 0.5, hit
    d.select_style("shaded-edges")
    img = d.frame()
    i_sh = d.px(img, i_xy)
    flat = max(float(np.abs(b - i_sh).max()) for b, _ in diag_bins(img) if len(b))
    print("(g) 陰影＋稜線: I", i_sh, "diagonal band max diff from I", flat)
    assert diff(i_sh, BG).max() >= 40, ("faces drawn in 陰影＋稜線", i_sh)
    assert flat <= 12, ("no triangle lines in 陰影＋稜線", flat)
    infos = []
    for key in ("shaded-edges", "shaded", "wireframe", "xray", "wireframe", "shaded-edges"):
        d.select_style(key)
        infos.append((key, d.render_info()))
    print("(g) render info:", infos)
    assert len({i["geometries"] for _, i in infos}) == 1, ("a style switch built or freed geometry", infos)

    # ---- (k) after choosing a style the arrows turn the view ------------------
    sel = d.style_select()
    sel.focus()
    sel.select_option(label="陰影のみ")
    d.settle()
    focused = sel.evaluate("s => document.activeElement === s")
    before = d.view()["position"]
    page.keyboard.press("ArrowRight")
    d.settle()
    v = d.view()
    print("(k) select focused after the choice:", focused, "moved:", before != v["position"], v["displayStyle"])
    assert not focused, "the style select must give up the focus"
    assert max(abs(a - b) for a, b in zip(before, v["position"])) > 1e-6, "ArrowRight must turn the view"
    assert v["displayStyle"] == "shaded", v["displayStyle"]

    # ---- (f) new models, reload, 2D drawing, bad stored value ------------------
    def see_through(tag):
        dv = d.see_through()
        print("(f)", tag, "pin1 shown - hidden at Q:", dv)
        assert dv[0] >= 8 and dv[0] > dv[2], (tag, "not see-through", dv)

    d.select_style("xray")
    d.load(paths["box"])
    d.load(d.mold)
    see_through("1 new model")

    page.goto(page.url)
    page.wait_for_load_state("networkidle")
    assert d.style_label() == "半透明", d.style_label()
    assert d.view()["displayStyle"] == "xray", d.view()
    d.load(d.mold)
    see_through("2 after a reload")

    d.load(DXF, wait_text="2D図面")
    assert not d.ctl("表示スタイル").is_visible(), "表示スタイル is a 3D control"
    d.load(d.mold)
    assert d.style_label() == "半透明", d.style_label()
    see_through("3 after a drawing")

    # ---- (i) loose curves stay drawn in every style ----------------------------
    d.load(str(IGES))
    d.preset("等角")

    def amber():
        img = d.frame()
        return int(np.sum(np.abs(img - np.array(CURVE)).max(axis=2) < 40))

    counts = {}
    for key in ("shaded-edges", "shaded", "wireframe"):
        d.select_style(key)
        counts[key] = amber()
    print("(i) amber pixels:", counts)
    assert counts["shaded-edges"] >= 200, counts
    for key in ("shaded", "wireframe"):
        assert counts[key] >= 0.8 * counts["shaded-edges"], ("loose curves must stay", key, counts)

    # ---- (f) 4. a bad stored style falls back to the default -------------------
    page.evaluate("localStorage.setItem('cad-viewer:view', JSON.stringify({style: 'bogus', grid: false}))")
    page.goto(page.url)
    page.wait_for_load_state("networkidle")
    v = d.view()
    print("(f) 4 bogus:", d.style_label(), v["displayStyle"], v["gridVisible"])
    assert d.style_label() == "陰影＋稜線" and v["displayStyle"] == "shaded-edges", (d.style_label(), v)
    assert v["gridVisible"] is False, "the other preferences are still read"

    page.screenshot(path="/tmp/cad_viewer_display_styles_more.png")
    print("DISPLAY STYLES MORE E2E OK")
