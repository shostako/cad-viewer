"""E2E: a change of view moves smoothly (issue #23, "あとで": 視点の切り替えを滑らかに).

A preset (視点), an axis of the triad and a fit (F, the toolbar, この部品へ寄る,
the refit after H) take about 0.3 s on screen instead of a jump. Under
automation the motion is off (every other script reads the camera right
after a click); this script turns it on with window.__cadViewMotion(true).

- 上 from the opening view: the frames go from the old direction to the new
  one, nearer the end at every frame, and stop exactly where the jump goes.
- F after turning and zooming: the frames move, and the last one passes the
  fit's own check (nav_common.fill_check).
- A key in the middle of a change ends it first: ← right after 正面 turns 5
  degrees from 正面, not from somewhere on the way.
- A load frames the model at once (no motion from the old view).
- prefers-reduced-motion: no motion even when turned on.

Oracles: __cadView sampled at every animation frame inside the page, the
direction of the jump (motion off), nav_common's fit check.
"""
import math

from nav_common import MOLD, nav_session

SAMPLE_JS = """ms => new Promise(res => {
  const out = []
  const t0 = performance.now()
  const tick = () => {
    const v = window.__cadView()
    out.push({ t: performance.now() - t0, position: v.position, target: v.target, up: v.up, zoom: v.zoom })
    if (performance.now() - t0 < ms) requestAnimationFrame(tick)
    else res(out)
  }
  requestAnimationFrame(tick)
})"""


def direction(v):
    d = [p - t for p, t in zip(v["position"], v["target"])]
    n = math.sqrt(sum(x * x for x in d))
    return [x / n for x in d]


def angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


def close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    n.load(n.paths["step"])
    start = n.view()

    def press_preset(name, sample_ms=0):
        """click a 視点 button; with sample_ms, __cadView at every frame from the click on"""
        btn = n.ctl(name).locator("button")
        if not sample_ms:
            btn.click()
            n.settle()
            return None
        handle = page.evaluate_handle(
            "([name, ms]) => { const b = [...document.querySelectorAll('.lil-controller button')]"
            ".find(b => b.textContent.trim() === name); const p = (" + SAMPLE_JS + ")(ms); b.click(); return p }",
            [name, sample_ms],
        )
        return handle.json_value()

    # ---- 1. the jump, with the motion off: where 上 goes
    n.ctl("上")  # (opens 表示 and 視点 first: the panel's size settles before anything is read)
    n.wait_gui_idle()
    press_preset("上")
    top = n.view()
    press_preset("等角")
    iso = n.view()
    page.evaluate("window.__cadViewMotion(true)")

    # ---- 2. 上 with the motion on: from the old direction to the new, then exactly there
    frames = press_preset("上", 600)
    d0, d1 = direction(iso), direction(top)
    total = angle(d0, d1)
    to_end = [angle(direction(f), d1) for f in frames]
    print("2 frames", len(frames), "angles to the end", [round(a, 1) for a in to_end[::3]])
    assert to_end[0] > 0.8 * total, ("2 the first frame is near the start", to_end[0], total)
    assert any(0.2 * total < a < 0.8 * total for a in to_end), ("2 no frame on the way", to_end)
    assert all(b <= a + 0.05 for a, b in zip(to_end, to_end[1:])), ("2 nearer the end at every frame", to_end)
    last = frames[-1]
    assert close(last["position"], top["position"], 1e-6) and close(last["target"], top["target"], 1e-6), (last, top)
    assert close(last["up"], top["up"], 1e-9), (last["up"], top["up"])
    # eased: it sets off slowly (a fifth of the way in time, under a sixth of the
    # turn; a steady speed would be a fifth)
    # (the time is from the click: the sampling starts with it)
    early = [(f["t"], 1 - a / total) for f, a in zip(frames, to_end) if 30 <= f["t"] <= 100]
    assert early and all(p < 0.8 * t / 300 for t, p in early), ("2 eased at the start", early)
    moving = [f["t"] for f, a in zip(frames, to_end) if a > 1e-6]
    print("2 moving for", round(moving[-1]), "ms")
    assert 150 <= moving[-1] <= 500, ("2 about 0.3 s", moving[-1])

    # ---- 3. F after turning and zooming: it moves, and ends framed
    for _ in range(4):
        page.keyboard.press("ArrowLeft")
    for _ in range(4):
        page.keyboard.press("+")
    n.settle()
    before = n.view()
    frames = page.evaluate_handle(
        "() => { const p = (" + SAMPLE_JS + ")(600); window.dispatchEvent(new KeyboardEvent('keydown', { key: 'f' })); return p }"
    ).json_value()
    dists = [math.dist(f["position"], f["target"]) for f in frames]
    print("3 distance", round(dists[0], 1), "->", round(dists[-1], 1))
    assert dists[0] < dists[-1] - 1 and any(dists[0] + 1 < d < dists[-1] - 1 for d in dists), ("3 the zoom out moves", dists[::3])
    n.mark_fit()
    print("3", n.fill_check(*MOLD, "fit with motion", fallback=False))
    assert close(direction(frames[-1]), direction(before), 1e-9), "3 a fit keeps the direction"
    # the fit is the view the panels' H fits again (the moving fit remembered where it goes)
    page.keyboard.press("h")
    page.wait_for_timeout(600)
    n.mark_fit()
    print("3 H", n.fill_check(*MOLD, "refit with motion, panels hidden", fallback=False))
    page.keyboard.press("h")
    page.wait_for_timeout(600)
    n.mark_fit()
    n.fill_check(*MOLD, "refit with motion, panels back", fallback=False)

    # ---- 4. a key in the middle of a change ends it first
    press_preset("等角")
    n.settle()
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.evaluate(
        "() => { [...document.querySelectorAll('.lil-controller button')].find(b => b.textContent.trim() === '正面').click();"
        " window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' })) }"
    )
    page.wait_for_timeout(600)
    n.settle()
    d = direction(n.view())
    front = [0, -1, 0]
    print("4 after ← mid-way", [round(x, 4) for x in d], round(angle(d, front), 2))
    assert 4.5 <= angle(d, front) <= 5.5 and abs(d[2]) < 1e-6, ("4 5 degrees from 正面", d)

    # ---- 4b. 投影 switched while a fit moves: the fit still counts (H fits again);
    #      a double-click while a preset moves: the preset first (Codex on #41)
    for _ in range(3):
        page.keyboard.press("ArrowLeft")
    n.settle()
    page.evaluate(
        "() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'f' }));"
        " const s = [...document.querySelectorAll('.lil-controller')].find(c => c.querySelector('.lil-name')?.textContent === '投影').querySelector('select');"
        " s.value = '平行'; s.dispatchEvent(new Event('change')) }"
    )
    page.wait_for_timeout(600)
    assert n.view()["projection"] == "orthographic", n.view()["projection"]
    page.keyboard.press("h")
    page.wait_for_timeout(600)
    n.mark_fit()
    print("4b H after a switch mid-fit", n.fill_check(*MOLD, "refit after a switch mid-fit", fallback=False))
    page.keyboard.press("h")
    page.wait_for_timeout(600)
    n.set_projection("透視")
    n.settle()
    press_preset("等角")
    n.settle()
    centre = n.project((50, 30, 20))
    # 正面 clicked, and a real double-click straight after (well inside its 0.3 s)
    page.evaluate("() => [...document.querySelectorAll('.lil-controller button')].find(b => b.textContent.trim() === '正面').click()")
    page.mouse.dblclick(*centre)
    assert page.evaluate("!!document.querySelector('.pivot-marker')"), "4b the double-click must set a rotation centre"
    page.wait_for_timeout(700)
    d = direction(n.view())
    assert angle(d, [0, -1, 0]) < 1e-6, ("4b a double-click mid-preset: the preset first", d)
    press_preset("等角")
    n.settle()

    # ---- 5. a load frames at once: watched from before the load, every frame
    #      after 読み込み中 has gone is the same pose
    # (kept on window: evaluate would wait for the promise, before the load ran).
    # The same file again can load within a frame (the model kept, the Web
    # version's Worker answering at once): 読み込み中 may never be drawn, so the
    # frames are also counted from when the script has seen the load done
    page.evaluate(
        """() => { window.__loaded = false; window.__watch = new Promise(res => {
          const out = []
          let loading = false
          const t0 = performance.now()
          const tick = () => {
            const t = document.querySelector('#hud-info').textContent
            if (t.includes('読み込み中')) loading = true
            else if (loading || window.__loaded) out.push(window.__cadView().position)
            if (performance.now() - t0 < 20000 && out.length < 30) requestAnimationFrame(tick)
            else res(out)
          }
          requestAnimationFrame(tick)
        }) }"""
    )
    n.load(n.paths["step"])
    page.evaluate("() => { window.__loaded = true }")
    positions = page.evaluate("() => window.__watch")
    assert len(positions) == 30, ("5 the frames after the load", len(positions))
    assert all(close(q, positions[0], 1e-9) for q in positions), ("5 the load fit moves", positions[0], positions[-1])

    # ---- 6. prefers-reduced-motion: no motion
    page.emulate_media(reduced_motion="reduce")
    frames = press_preset("上", 300)
    assert all(close(f["position"], frames[-1]["position"], 1e-9) for f in frames), "6 reduced motion moves"
    page.emulate_media(reduced_motion="no-preference")
    page.evaluate("window.__cadViewMotion(false)")

    print("VIEW MOTION E2E OK")
