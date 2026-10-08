"""E2E: 表示スタイル (A4) on mini_mold — 陰影＋稜線 / 陰影のみ / ワイヤーフレーム / 半透明.

(a) 陰影のみ draws no edge lines; (b) ワイヤーフレーム draws no faces, keeps the
lines, and a face is still picked; (r) a switch builds no geometry and adds no
draw calls in 半透明; (c) 半透明 shows pin1 through the cavity block, picks the
front face (pin1 once the block is hidden), keeps the edges, and the measure
marker on top; (d) the thickness heatmap shows in 陰影のみ and 半透明, and the
HUD says it cannot in ワイヤーフレーム; (e) the section cap is opaque and closes
the cut in the opaque styles, translucent in the see-through ones; (h) the PNG
export is what is on screen, with dark edges on a white page.

Expected values: display_common.py (projections of known geometry, picks,
specification colours, canvas pixels). Persistence, new models, STL, loose
curves and the keyboard are in test_display_styles_more.py.
"""
import math
import os
from pathlib import Path

import numpy as np

from display_common import (
    BG, BLOCK, EDGE_T, MARKER, PIN1, PLATE_FRONT_TOP, Q, S, decode, diff, display_session,
    luminance, mold_edges, seg_box,
)

MARK = (56, 35, 35)
OWN = [k for k, (a, b) in enumerate(mold_edges()) if a == list(PLATE_FRONT_TOP[0]) and b == list(PLATE_FRONT_TOP[1])]
assert len(OWN) == 1, OWN

with display_session() as d:
    page = d.page
    d.load(d.mold)
    d.grid_off()

    # ---- 1. defaults ----------------------------------------------------------
    assert d.style_label() == "陰影＋稜線", d.style_label()
    assert d.view()["displayStyle"] == "shaded-edges", d.view()

    d.preset("等角")
    segs = d.segments()
    ids, pin1_box, block_box = d.mold_parts()
    print("part ids:", ids)
    s_xy = d.project(S)
    d.assert_clear(s_xy, segs, "S", pick_point=True)
    e0, e1 = d.project(PLATE_FRONT_TOP[0]), d.project(PLATE_FRONT_TOP[1])
    print("edge band clearance: %.1f px" % d.band_clear(e0, e1, segs, OWN, 9, *EDGE_T))

    def band(img):
        return d.band(img, e0, e1, 9, *EDGE_T)

    def dark_bins(img):
        """bins with a pixel as dark as the edge colour (#20262e: max channel 46)"""
        return sum(1 for b, _ in band(img) if len(b) and b.max(axis=1).min() <= 80)

    def bright_bins(img):
        """bins with a pixel well above the background (see-through edges are light)"""
        return sum(1 for b, _ in band(img) if len(b) and (b - np.array(BG)).max() >= 80)

    def contrast_bins(img):
        """bins whose brightest pixel stands out from the pixels 6 px off the line"""
        return sum(1 for b, e in band(img) if len(b) and len(e) and b.mean(axis=1).max() - e.mean() >= 40)

    img = d.frame()
    S_default = d.px(img, s_xy)
    dark_default = dark_bins(img)

    # ---- (a) 陰影のみ: faces as before, no edge lines -------------------------
    d.select_style("shaded")
    img = d.frame()
    S_shaded = d.px(img, s_xy)
    dark_shaded = dark_bins(img)
    print("(a) dark edge bins 陰影＋稜線 / 陰影のみ:", dark_default, dark_shaded, " S:", S_default, S_shaded)
    assert dark_default >= 7, ("the default style draws the edge", dark_default)
    assert dark_shaded == 0, ("陰影のみ still draws the edge", dark_shaded)
    assert diff(S_shaded, S_default).max() <= 2, ("faces changed", S_default, S_shaded)

    # ---- (b) ワイヤーフレーム: no faces, the lines stay, faces are still picked ---
    d.select_style("wireframe")
    img = d.frame()
    S_wire = d.px(img, s_xy)
    strip_pts = d.project_many([(5, 3, 15), (95, 3, 15), (95, 12, 15), (5, 12, 15)])
    strip = d.poly_mask(img.shape, strip_pts) & ~d.edge_mask(img.shape, segs)
    bg_share = float(np.mean(np.abs(img[strip] - np.array(BG)).max(axis=1) <= 8))
    bright = bright_bins(img)
    hit = d.pick(s_xy)
    print("(b) S", S_wire, "strip px", int(strip.sum()), "background share %.4f" % bg_share, "bright bins", bright, "pick", hit)
    assert diff(S_default, BG).max() >= 40, ("S is on a face in the default style", S_default)
    assert diff(S_wire, BG).max() <= 8, ("a face is drawn in ワイヤーフレーム", S_wire)
    assert strip.sum() >= 3000, ("strip too small to tell", int(strip.sum()))
    assert bg_share >= 0.995, ("faces drawn in ワイヤーフレーム", bg_share)
    assert hit and hit["kind"] == "face" and hit["partId"] == ids["plate"], ("hidden faces must stay pickable", hit)
    assert max(abs(a - b) for a, b in zip(hit["point"], S)) <= 0.5, hit
    assert bright >= 7, ("the edge must show (light) in ワイヤーフレーム", bright)

    # ---- (r) a switch builds nothing; 半透明 draws in one pass ---------------
    infos = []
    for cycle in range(2):
        for key in ("shaded-edges", "shaded", "wireframe", "xray"):
            d.select_style(key)
            infos.append((cycle, key, d.render_info()))
    for i in infos:
        print("(r)", i)
    geos = {i[2]["geometries"] for i in infos}
    assert len(geos) == 1, ("a style switch built or freed geometry", geos)
    progs1 = [i[2]["programs"] for i in infos if i[0] == 1]
    assert all(p == infos[3][2]["programs"] for p in progs1), ("new programs on a second cycle", progs1)
    for cycle in range(2):
        calls = {i[1]: i[2]["calls"] for i in infos if i[0] == cycle}
        assert calls["xray"] == calls["shaded-edges"], ("半透明 must draw each part once", calls)

    # ---- (c) 半透明: pin1 through the block, picks, edges, marker ------------
    d.select_style("shaded-edges")
    q, E = d.iso_q_setup()
    print("(c) Q on screen", q, "block entry", [round(x, 2) for x in E])

    def pin_toggle():
        shown = d.px(d.frame(), q)
        d.toggle(pin1_box, False)
        hidden = d.px(d.frame(), q)
        d.toggle(pin1_box, True)
        return shown - hidden

    opaque = pin_toggle()
    d.select_style("xray")
    see = pin_toggle()
    print("(c) pin1 shown - hidden at Q: 陰影＋稜線", opaque, " 半透明", see)
    assert np.abs(opaque).max() <= 2, ("pin1 must be hidden by the opaque block", opaque)
    assert see[0] >= 8 and see[0] > see[2], ("pin1 must show (red) through the block in 半透明", see)

    hit = d.pick(q)
    print("(c) pick in 半透明:", hit)
    assert hit and hit["kind"] == "face" and hit["partId"] == ids["block"], ("the front face is picked", hit)
    assert max(abs(a - b) for a, b in zip(hit["point"], E)) <= 0.5, (hit, E)
    d.toggle(block_box, False)
    hit = d.pick(q)
    d.toggle(block_box, True)
    print("(c) pick with the block hidden:", hit)
    assert hit and hit["kind"] == "face" and hit["partId"] == ids["pin1"], ("hide the outer part to pick the inner one", hit)
    assert max(abs(a - b) for a, b in zip(hit["point"], Q)) <= 1.0, (hit, Q)

    img = d.frame()
    kept = contrast_bins(img)
    print("(c) edge bins standing out in 半透明:", kept)
    assert kept >= 7, ("edges must stay in 半透明", kept)

    # on the block top; its centre is 9 px from the plate's hidden back edge on screen
    m_xy = d.project(MARK)
    d.assert_clear(m_xy, segs, "marker", pick_point=True)
    before = d.px(d.frame(), m_xy)
    d.set_mode("計測")
    page.mouse.click(*m_xy)
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('相手をクリック')", timeout=10000)
    d.settle()
    marker = d.px(d.frame(), m_xy)
    d.set_mode("なし")
    d.settle()
    after = d.px(d.frame(), m_xy)
    n_entries = page.locator("#measure-list li").count()
    print("(c) marker pixel", marker, "before / after", before, after, "entries", n_entries)
    assert diff(marker, MARKER).max() <= 30, ("the marker must draw over the see-through faces", marker)
    assert diff(after, before).max() <= 3, ("the marker must go with mode なし", before, after)
    assert n_entries == 0, n_entries

    # ---- (d) thickness heatmap in 陰影のみ and 半透明 --------------------------
    d.select_style("shaded")
    off_sh = d.px(d.frame(), s_xy)
    d.select_style("xray")
    off_x = d.px(d.frame(), s_xy)
    d.open_folder("肉厚")
    d.check("ヒートマップ", True)
    page.wait_for_function(
        "document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=60000
    )
    d.settle()
    on_x = d.px(d.frame(), s_xy)
    d.select_style("shaded")
    on_sh = d.px(d.frame(), s_xy)
    d.select_style("xray")
    on_x2 = d.px(d.frame(), s_xy)
    d.select_style("shaded")
    on_sh2 = d.px(d.frame(), s_xy)

    def bmr(c):
        return c[2] - c[0]

    print("(d) S heatmap off/on 陰影のみ", off_sh, on_sh, on_sh2, " 半透明", off_x, on_x, on_x2)
    assert bmr(on_sh) - bmr(off_sh) >= 20, ("heatmap colours missing in 陰影のみ", off_sh, on_sh)
    assert bmr(on_x) - bmr(off_x) >= 10 and bmr(on_x2) - bmr(off_x) >= 10, ("heatmap colours missing in 半透明", off_x, on_x, on_x2)
    assert diff(on_sh2, on_sh).max() <= 3, ("a style round trip changed the heatmap", on_sh, on_sh2)
    d.select_style("wireframe")
    hud = page.text_content("#hud-info")
    print("(d) HUD in ワイヤーフレーム:", hud)
    assert "肉厚ヒートマップ表示中" in hud and "ワイヤーフレーム" in hud, hud
    d.select_style("shaded")
    hud = page.text_content("#hud-info")
    assert "肉厚ヒートマップ表示中" in hud and "ワイヤーフレーム" not in hud, hud
    d.check("ヒートマップ", False)

    # ---- (e) section caps in every style -------------------------------------
    d.select_style("shaded-edges")
    d.preset("右")
    CUT = (50, 22, 25)  # block cross-section, outside pin1's silhouette (y 26..34)
    CUTP = (50, 8, 7)  # plate cross-section
    P1 = (PIN1[0] + math.sqrt(4**2 - 2**2), 32, 25)  # pin1's side facing +x, behind the cut block
    C = d.view()["position"]
    t = (50 - C[0]) / (P1[0] - C[0])
    at = [C[i] + (P1[i] - C[i]) * t for i in range(3)]
    assert 17 <= at[1] <= 43 and 17 <= at[2] <= 33, ("the view ray to P1 crosses the block's cut", at)
    assert seg_box(C, P1, *BLOCK) is not None
    segs_r = d.segments()
    pts = {"cut": d.project(CUT), "cutp": d.project(CUTP), "p1": d.project(P1)}
    for k, xy in pts.items():
        d.assert_clear(xy, segs_r, k)
    d.open_folder("断面")
    d.check("有効", True)
    assert d.ctl("キャップ").locator("input").is_checked()

    sec = {}
    for key in ("shaded-edges", "shaded", "xray", "wireframe"):
        d.select_style(key)
        img = d.frame()
        r = {"cut": d.px(img, pts["cut"]), "cutp": d.px(img, pts["cutp"]), "p1": d.px(img, pts["p1"])}
        d.toggle(pin1_box, False)
        r["p1_nopin"] = d.px(d.frame(), pts["p1"])
        d.toggle(pin1_box, True)
        d.check("キャップ", False)
        r["cut_nocap"] = d.px(d.frame(), pts["cut"])
        d.check("キャップ", True)
        sec[key] = r
        print("(e)", key, {k: v.round(1).tolist() for k, v in r.items()})

    o = sec["shaded-edges"]
    assert o["cut"].max() - o["cut"].min() <= 60, ("the opaque cap is grey", o["cut"])
    assert o["cut_nocap"][2] - o["cut_nocap"][0] >= 60, ("without the cap the block's inside shows (blue)", o["cut_nocap"])
    assert diff(o["cut"], o["cutp"]).max() <= 6, ("an opaque cap looks the same over the block and the plate", o)
    assert diff(o["p1"], o["p1_nopin"]).max() <= 2, ("the opaque cap hides pin1", o)
    s_ = sec["shaded"]
    assert diff(s_["cut"], o["cut"]).max() <= 3 and diff(s_["cutp"], o["cutp"]).max() <= 3, ("陰影のみ cap", s_)
    x = sec["xray"]
    assert diff(x["cut"], x["cut_nocap"]).max() >= 8, ("半透明: no cap", x)
    assert diff(x["cut"], x["cutp"]).max() >= 8, ("半透明: the cap must let what is behind it show", x)
    assert x["p1"][0] - x["p1_nopin"][0] >= 6, ("半透明: pin1 must show through the cap", x)
    w = sec["wireframe"]
    assert diff(w["cut"], w["cut_nocap"]).max() >= 8, ("ワイヤーフレーム: no cap", w)
    assert diff(w["cut"], o["cut"]).max() >= 8, ("ワイヤーフレーム: the cap must be translucent", w, o)
    d.check("有効", False)

    # ---- (h) the PNG export is the screen, in the current style --------------
    def export(tag):
        with page.expect_download(timeout=15000) as info:
            d.click_button("画像を保存")
        path = os.path.join(d.tmp, f"{tag}.png")
        info.value.save_as(path)
        page.wait_for_function("document.querySelector('#hud-info').textContent.startsWith('画像を保存: ')")
        return decode(Path(path).read_bytes())

    d.preset("等角")
    q = d.project(Q)
    d.select_style("xray")
    screen = d.frame()
    png_x = export("xray")
    dd = np.abs(png_x - screen).max(axis=2)
    same = float(np.mean(dd <= 2))
    d.select_style("shaded-edges")
    png_d = export("default")
    print("(h) 半透明 export equal to the screen: %.5f, max diff %d; Q export 半透明 / 陰影＋稜線" % (same, dd.max()),
          d.px(png_x, q), d.px(png_d, q))
    assert png_x.shape == screen.shape, (png_x.shape, screen.shape)
    assert same >= 0.999 and dd.max() <= 24, ("the export is not the screen", same, int(dd.max()))
    assert diff(d.px(png_x, q), d.px(png_d, q)).max() >= 8, ("the export must be in the current style", q)

    d.select_style("wireframe")
    d.ctl("画像の背景").locator("select").select_option(label="白")
    d.blur()
    png_w = export("wire_white")
    darkest = [float(luminance(b).min()) for b, _ in band(png_w) if len(b)]
    bright_again = bright_bins(d.frame())
    print("(h) 白 export, darkest luminance per bin:", [round(v, 3) for v in darkest], " screen bright bins after:", bright_again)
    assert sum(1 for v in darkest if v <= 0.18) >= 7, ("light edges on a white page", darkest)
    assert bright_again >= 7, ("the screen's edges must be light again after the export", bright_again)

    page.screenshot(path="/tmp/cad_viewer_display_styles.png")
    print("DISPLAY STYLES E2E OK")
