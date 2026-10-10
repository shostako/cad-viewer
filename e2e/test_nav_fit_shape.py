"""E2E: 全体表示 chooses its area by the model's shape on screen (issue #23 item 6).

The free area is the largest rectangle clear of the panels, unless another
shows the model at least SWITCH_GAIN (1.1) times as large; then the one that
shows it largest (nav_common.py has the rule and its independent copy,
free_rect). At 1280 x 800 with mini_mold the two candidates are the column
right of the part tree (the largest) and the band under it (as wide as the
view left of the GUI):

- 正面: the mold is wide and flat on screen: the band shows it about 1.2
  times as large, so the fit uses the band
- 上: the band shows it about 1.05 times as large, under 1.1, so the fit
  stays in the largest rectangle
- the same in the parallel projection

The test pins the tree panel's size (180 x 170 px) and the status card's
height (90 px, bottom left): the gains then do not depend on the fonts (the
tree's text and the status line's wrapping set their sizes), and 上 stays well
inside 1 to 1.1. (The status card was 2 to 4 lines taller before #23 item 7
took its title and key help out; at its height now the band under the tree
reaches lower right of the axis triad, and 上 crossed 1.1.) The fit reads
whatever rects are on screen, so the oracle stays independent.

Each case also proves it can tell the rules apart: the fit that the other
rule would make (always the largest rectangle; always the one that shows the
model largest) fails the same checks. Oracles: the panels' rects, the mold's
known box projected through window.__cadProject, the camera (__cadView).
"""
from nav_common import MOLD, free_rect, model_size, nav_session, would_fail

with nav_session() as n:
    page = n.page
    page.set_viewport_size({"width": 1280, "height": 800})
    page.add_style_tag(
        content="#tree-panel{width:180px!important;height:170px!important}"
        "#hud{height:90px!important;box-sizing:border-box}"
    )
    n.load(n.paths["step"])

    def candidates():
        """(the rule's area, the largest, the one that shows the mold largest, gain)"""
        _, _, cw, ch = n.canvas_rect()
        panels = list(n.panel_rects().values())
        size = model_size(*MOLD, n.view())
        F, fb = free_rect(cw, ch, panels, size)
        assert not fb
        L, _ = free_rect(cw, ch, panels, (0, 0))
        G, _ = free_rect(cw, ch, panels, size, gain=1)

        def shows(R):
            return min((R[2] - R[0]) / size[0], (R[3] - R[1]) / size[1])

        return F, L, G, shows(G) / shows(L)

    def framed():
        cl, ct, _, _ = n.canvas_rect()
        x0, y0, x1, y1 = n.rect(*MOLD)
        return (x0 - cl, y0 - ct, x1 - cl, y1 - ct)

    for projection in ("透視", "平行"):
        n.set_projection(projection)
        tree = n.panel_rects()["#tree-panel"]

        # ---- 1. 正面: the band under the tree shows the wide mold larger
        n.click_button("正面")
        n.fit()
        F, L, G, gain = candidates()
        info = n.fill_check(*MOLD, f"{projection} 正面", fallback=False, needs=("#tree-panel",))
        print(projection, "1 正面", info, "largest", L, "gain", round(gain, 3))
        assert gain >= 1.15, ("1 the case needs a clear gain", gain)
        assert F == G and F[0] == 0 and F[1] >= tree[3] - 0.5, ("1 the band under the tree", F, tree)
        assert would_fail(framed(), F, L), ("1 a fit in the largest rectangle would pass too", L)

        # ---- 2. 上: a gain under SWITCH_GAIN keeps the largest rectangle
        n.click_button("上")
        n.fit()
        F, L, G, gain = candidates()
        info = n.fill_check(*MOLD, f"{projection} 上", fallback=False, needs=("#tree-panel",))
        print(projection, "2 上", info, "largest-showing", G, "gain", round(gain, 3))
        assert 1.02 <= gain <= 1.08 and G != L, ("2 the case needs a gain under the threshold", gain, G, L)
        assert F == L and F[0] >= tree[2] - 0.5 and F[1] == 0, ("2 the column beside the tree", F, tree)
        assert would_fail(framed(), F, G), ("2 a fit in the rectangle that shows it largest would pass too", G)

        # ---- 3. the view turned back: F again picks by the shape seen now
        n.click_button("正面")
        n.fit()
        F, _, _, _ = candidates()
        n.fill_check(*MOLD, f"{projection} 正面 again", fallback=False)
        assert F[0] == 0 and F[1] >= tree[3] - 0.5, ("3 the band again", F)
        n.click_button("等角")

    page.screenshot(path="/tmp/cad_viewer_nav_fit_shape.png")
    print("NAV FIT SHAPE E2E OK")
