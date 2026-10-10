"""E2E: the frames stop while nothing changes (issue #8 D1, issue #23 "あとで").

A still model used to be drawn 60 times a second (a laptop's battery, heat
and fan). Now the frames go on for 1 s after any change and then stop, with
one frame a second as a net for a change nobody announced.

- Still for a while: at most a few frames in 3 s; the screen keeps the model
  (the last frame stays shown).
- A key, the pointer on the canvas, 自動回転 (for as long as it is on), a
  resize: the frames come back at once. (Counted over 0.6 s and compared with
  the still rate, at most one a second: a slow machine draws fewer frames, but
  the gap stays wide.)
- A change that comes later by itself (the thickness heatmap, its answer held
  back 2 s): drawn at once when it lands, not a second later.
- A read of the canvas (toDataURL) draws the frame first, also while still.

Oracles: window.__cadRenderInfo().frames (the frames drawn), page
screenshots (what is shown) and canvas reads, the known model.
"""
import io

from PIL import Image

import gui_common
from nav_common import nav_session

SCENE = (0x1D, 0x21, 0x26)

with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    n.load(n.paths["step"])

    def frames():
        return page.evaluate("window.__cadRenderInfo().frames")

    def drawn_in(ms):
        f0 = frames()
        page.wait_for_timeout(ms)
        return frames() - f0

    def shown(xy):
        """the colour on screen (the compositor's picture, not a read of the canvas)"""
        img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
        return img.getpixel((round(xy[0]), round(xy[1])))

    def far(c, ref, d=30):
        return max(abs(a - b) for a, b in zip(c, ref)) > d

    plate = n.project((90, 10, 15))  # the plate's top

    # ---- 1. still: the frames stop, the model stays on screen
    page.mouse.move(5, 795)  # off the canvas's model, then still
    page.wait_for_timeout(1500)
    still = drawn_in(3000)
    print("1 frames in 3 s, still:", still)
    # (one a second goes on: the net for a change nobody announced)
    assert 2 <= still <= 5, ("1 the frames must stop, but for one a second", still)
    assert far(shown(plate), SCENE), "1 the model must stay shown"

    # ---- 2. a key, the pointer, a resize: back at once
    page.wait_for_timeout(1500)
    page.keyboard.press("ArrowLeft")
    after_key = drawn_in(600)
    page.wait_for_timeout(1500)
    page.mouse.move(*plate)
    after_move = drawn_in(600)
    page.wait_for_timeout(1500)
    page.set_viewport_size({"width": 1200, "height": 800})
    after_resize = drawn_in(600)
    page.set_viewport_size({"width": 1280, "height": 800})
    print("2 frames in 0.6 s after a key / a move / a resize:", after_key, after_move, after_resize)
    assert min(after_key, after_move, after_resize) >= 3, ("2 the frames must come back", after_key, after_move, after_resize)

    # ---- 3. 自動回転: frames for as long as it is on
    auto = gui_common.ctl(page, "自動回転").locator("input")
    auto.click()
    page.mouse.move(5, 795)
    page.wait_for_timeout(1500)  # past the wake of the click
    spinning = drawn_in(1000)
    auto.click()
    print("3 frames in 1 s with 自動回転, 1.5 s after the click:", spinning)
    assert spinning >= 5, ("3 自動回転 must go on drawing", spinning)

    # ---- 4. a change landing by itself: the heatmap's answer held back 2 s
    n.settle()
    page.wait_for_timeout(1500)
    before = shown(plate)
    held = []

    def hold(route):
        held.append(route)

    page.route("**/thickness.bin*", hold)
    gui_common.ctl(page, "ヒートマップ").locator("input").click()
    page.mouse.move(5, 795)
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "4 the heatmap asked for no values"
    page.wait_for_timeout(2000)  # asleep again
    f0 = frames()
    page.unroute("**/thickness.bin*")
    held[0].continue_()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('肉厚ヒートマップ表示中')", timeout=30000)
    page.wait_for_timeout(600)
    landed = frames() - f0
    now = shown(plate)
    print("4 frames within 0.6 s of the answer:", landed, "plate", before, "->", now)
    assert landed >= 3, ("4 the answer must be drawn at once", landed)
    assert far(now, before, 20), ("4 the heatmap's colour on screen", before, now)
    gui_common.ctl(page, "ヒートマップ").locator("input").click()

    # ---- 5. a read of the canvas draws first, also while still
    page.wait_for_timeout(1500)
    f0 = frames()
    rgb = n.canvas_rgb([plate])[0]
    assert frames() - f0 >= 1 and far(rgb, SCENE), ("5 a read draws the frame", frames() - f0, rgb)

    # ---- 6. a measurement whose answer lands by itself: its line is drawn at once
    held.clear()
    page.route("**/measure", hold)
    gui_common.set_mode(page, "計測")
    for q in ((50, 30, 35), (90, 10, 15)):
        page.mouse.click(*n.project(q))
        page.wait_for_timeout(200)
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "6 no measure request"
    page.mouse.move(5, 795)
    page.wait_for_timeout(2000)  # asleep again
    f0 = frames()
    page.unroute("**/measure")
    for r in held:
        r.continue_()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('距離')", timeout=15000)
    page.wait_for_timeout(600)
    landed = frames() - f0
    print("6 frames within 0.6 s of the measure:", landed)
    assert landed >= 3, ("6 the new line must be drawn at once", landed)
    gui_common.set_mode(page, "なし")

    print("RENDER IDLE E2E OK")
