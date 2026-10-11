"""E2E: the card in the middle while a file loads, and when it cannot be opened (issue #23 item 9).

- loading: the file's name and size, the step (送信 → 形状の変換 → 表示の準備:
  the steps before the current one ticked), a bar; it takes the place of the
  open card on the first load and shows on later loads too; gone once the
  model is on screen
- a load that a newer one overtook never touches the card (not its steps, not
  with its failure)
- failed: a reason in plain words for each kind of failure, the file's name,
  the backend's own message behind 詳細を見る, 別のファイルを選ぶ (the file
  dialog) and 閉じる
- placed in the middle of the part of the window left of the operation panel;
  in a window too narrow for that, in the middle, over the panel (its buttons
  still take clicks)

The requests are held, answered or broken with page.route, so the steps are
seen without depending on timing. Oracles: the card's DOM (texts, the classes
of the steps), the file sizes on disk, the operation panel's rect, the HUD.
"""
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from engine_net import Net

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
BASE_URL = os.environ.get("CAD_VIEWER_URL", "http://127.0.0.1:5183")
STEP = str(TESTDATA / "mini_mold.step")
STL = str(TESTDATA / "ribbed_plate.stl")
DXF = str(TESTDATA / "plate_drawing.dxf")


def kb(path):
    """the size as the card gives it for a file under 1 MB"""
    return f"{max(1, round(os.path.getsize(path) / 1024))} KB"


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 767, "height": 639})
    # the plain <input> here: the file picker is taken away, as in a browser without it (its path: test_recent.py)
    page.add_init_script("window.showOpenFilePicker = undefined")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    # sidecars stay in the page: nothing reaches the shared backend's files
    Net.of(page).route(
        "**/sidecar",
        lambda r: r.fulfill(json={"version": 1, "entries": []} if r.request.method == "GET" else {}),
    )
    tmp = tempfile.mkdtemp(prefix="cad_load_card_")

    def card():
        """(shown, failed, title, file, steps {name: state}, reason, detail shown, indeterminate)"""
        return page.evaluate(
            """(() => { const c = document.querySelector('#load-card')
                 const steps = {}
                 c.querySelectorAll('#load-steps li').forEach(li => { steps[li.textContent] = li.className })
                 const d = document.querySelector('#load-detail')
                 return { shown: c.getBoundingClientRect().width > 0, failed: c.classList.contains('failed'),
                   title: c.querySelector('#load-title').textContent, file: c.querySelector('#load-file').textContent,
                   steps, reason: c.querySelector('#load-reason').textContent,
                   detail: d.getBoundingClientRect().height > 0 ? d.textContent : null,
                   moving: c.classList.contains('indeterminate') } })()"""
        )

    def hud():
        return page.text_content("#hud-info")

    def visible(sel):
        return page.locator(sel).first.is_visible()

    def wait_until(js, timeout=30000):
        page.wait_for_function(js, timeout=timeout)

    def wait_steps(active):
        page.wait_for_function(
            "a => { const li = document.querySelector('#load-steps li.active'); return !!li && li.textContent === a }",
            arg=active,
            timeout=30000,
        )

    def held_requests(url, method, store):
        """hold the requests to url with this method in store (the others go on)"""
        Net.of(page).route(url, lambda r: store.append(r) if r.request.method == method else r.continue_())

    def wait_held(store, n=1):
        for _ in range(200):
            if len(store) >= n:
                return
            page.wait_for_timeout(50)
        raise AssertionError(("request not seen", n, len(store)))

    def centred_left_of_panel(sel):
        box = page.locator(sel).bounding_box()
        gui = page.locator(".lil-gui.lil-root").bounding_box()
        vw = page.viewport_size["width"]
        vh = page.viewport_size["height"]
        fits = gui["x"] >= box["width"] + 32
        want_x = gui["x"] / 2 if fits else vw / 2
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        assert abs(cx - want_x) < 2 and abs(cy - vh / 2) < 2, (sel, box, gui, fits)
        return fits

    # ---- 1. the first load, step by step (767 x 639: half a screen)
    assert visible("#empty-hint") and not card()["shown"]
    assert centred_left_of_panel("#empty-hint"), "the open card fits left of the panel at 767"
    posts, meshes = [], []
    held_requests("**/api/models", "POST", posts)
    held_requests("**/mesh.bin", "GET", meshes)
    page.set_input_files("#file-input", STEP)
    wait_held(posts)
    c = card()
    print("1 sending", c)
    assert c["shown"] and not c["failed"] and c["title"] == "読み込み中", c
    assert c["file"] == f"mini_mold.step（{kb(STEP)}）", c
    assert not visible("#empty-hint"), "1 the load card takes the open card's place"
    assert centred_left_of_panel("#load-card")
    # the request is held: the file is going up or the backend has it (not more)
    assert c["steps"]["表示の準備"] == "" and "active" in (c["steps"]["送信"] + c["steps"]["形状の変換"]), c
    assert "読み込み中" in hud()
    Net.of(page).unroute("**/api/models")
    posts[0].continue_()
    wait_held(meshes)
    wait_steps("表示の準備")
    c = card()
    print("1 preparing", c)
    assert c["steps"] == {"送信": "done", "形状の変換": "done", "表示の準備": "active"}, c
    assert c["moving"], "1 a moving bar after the upload"
    Net.of(page).unroute("**/mesh.bin")
    meshes[0].continue_()
    wait_until("document.querySelector('#hud-info').textContent.includes('三角形')")
    assert not card()["shown"], "1 the card goes with the model on screen"
    assert not visible("#empty-hint")

    # ---- 2. a later load shows the card too (the old model goes first)
    meshes = []
    held_requests("**/mesh.bin", "GET", meshes)
    page.set_input_files("#file-input", STL)
    wait_held(meshes)
    c = card()
    print("2 second load", c)
    assert c["shown"] and c["file"] == f"ribbed_plate.stl（{kb(STL)}）" and c["steps"]["表示の準備"] == "active", c
    Net.of(page).unroute("**/mesh.bin")
    meshes[0].continue_()
    wait_until(
        "document.querySelector('#hud-info').textContent.includes('三角形')"
        " && document.querySelector('#hud-info').textContent.includes('ribbed_plate.stl')"
    )
    assert not card()["shown"]

    # ---- 3. an overtaken load never touches the card: A's upload is held
    #    while B gets to 表示の準備; then A goes on late (3a: it gets through,
    #    3b: it breaks off). B's card keeps B's step, and A's failure stays off it
    def overtaken(release, tag):
        first_post, meshes = [], []

        def hold_first_post(r):
            if r.request.method == "POST" and not first_post:
                first_post.append(r)
            else:
                r.continue_()

        Net.of(page).route("**/api/models", hold_first_post)
        held_requests("**/mesh.bin", "GET", meshes)
        page.set_input_files("#file-input", STEP)  # A
        wait_held(first_post)
        page.set_input_files("#file-input", STL)  # B
        wait_held(meshes)
        wait_steps("表示の準備")
        assert "ribbed_plate.stl" in card()["file"]
        with Net.of(page).expect_event("requestfinished" if release == "continue" else "requestfailed",
                               lambda q: q.method == "POST"):
            first_post[0].continue_() if release == "continue" else first_post[0].abort()
        page.wait_for_timeout(300)
        c = card()
        print(tag, "after the overtaken load", c)
        assert c["shown"] and not c["failed"] and "ribbed_plate.stl" in c["file"], (tag, "A on B's card", c)
        assert c["steps"]["表示の準備"] == "active", (tag, "A moved B's step", c)
        assert "エラー" not in hud(), hud()
        Net.of(page).unroute("**/api/models")
        Net.of(page).unroute("**/mesh.bin")
        meshes[0].continue_()
        wait_until(
            "document.querySelector('#hud-info').textContent.includes('三角形')"
            " && document.querySelector('#hud-info').textContent.includes('ribbed_plate.stl')"
        )
        assert not card()["shown"]

    overtaken("continue", "3a")
    overtaken("abort", "3b")

    # ---- 4. failures: the reason in plain words, the backend's message behind 詳細を見る
    def fail_with(path, reason_has, detail_has=None, route=None):
        if route:
            Net.of(page).route("**/api/models", route)
        page.set_input_files("#file-input", path)
        wait_until("document.querySelector('#load-card').classList.contains('failed')")
        if route:
            Net.of(page).unroute("**/api/models")
        c = card()
        print("4", os.path.basename(path), c["reason"])
        assert c["shown"] and c["title"] == "ファイルを開けなかった" and c["file"] == os.path.basename(path), c
        assert reason_has in c["reason"], (reason_has, c)
        assert "エラー" in hud() and os.path.basename(path) in hud(), hud()
        assert c["detail"] is None, "the backend's message is folded at first"
        if detail_has is not None:
            page.click("#load-more")
            c = card()
            assert c["detail"] and detail_has in c["detail"], (detail_has, c)
            assert page.inner_text("#load-more") == "詳細を隠す"
            page.click("#load-more")
            assert card()["detail"] is None
        return c

    bad_ext = os.path.join(tmp, "notes.txt")
    Path(bad_ext).write_text("not a CAD file")
    fail_with(bad_ext, "この形式には対応していない", "unsupported file extension")
    broken = os.path.join(tmp, "broken.stl")
    Path(broken).write_text("this is not an STL")
    fail_with(broken, "STL として読めない", "failed to parse mesh")
    empty = os.path.join(tmp, "empty.step")
    Path(empty).write_bytes(b"")
    fail_with(empty, "ファイルが空")
    fail_with(
        STEP,
        "大きすぎる",
        "file too large",
        route=lambda r: r.fulfill(status=413, json={"detail": "file too large"}),
    )
    fail_with(STEP, "backend につながらない", route=lambda r: r.abort())
    # a reason the backend already gives in Japanese (the drawing loader) is shown as it is
    fail_with(
        DXF,
        "図面に描画エンティティが無い",
        route=lambda r: r.fulfill(status=422, json={"detail": "図面に描画エンティティが無い"}),
    )
    assert card()["reason"] == "図面に描画エンティティが無い"
    # Esc closes a failed card too
    fail_with(broken, "STL として読めない")
    page.keyboard.press("Escape")
    assert not card()["shown"], "4 Esc must close the failed card"
    # a connection lost after the whole file went up: the backend was there
    # (simulated by hand: the browser cannot be made to drop it mid-conversion)
    lost = page.evaluate(
        """async () => {
             const api = await import('/src/api.ts')
             const lc = await import('/src/loadcard.ts')
             const e = new api.UploadError('no answer from the backend (network error)', 0)
             return [lc.failureReason(e, 'a.step', 'send'), lc.failureReason(e, 'a.step', 'convert')]
           }"""
    )
    print("4 connection lost:", lost)
    assert "つながらない" in lost[0] and "変換の途中で通信が切れた" in lost[1], lost
    # the model of section 3 is still on screen under the card (the axis
    # triad shows only with a 3D model on screen)
    assert visible("#triad") and not visible("#empty-hint")

    # ---- 4b. the cards follow the operation panel's left edge when only the
    #     panel changes (a wider panel here; hiding it does the same)
    page.set_input_files("#file-input", broken)
    wait_until("document.querySelector('#load-card').classList.contains('failed')")
    page.evaluate("document.querySelector('.lil-gui.lil-root').style.setProperty('--width', '330px')")
    page.wait_for_timeout(200)
    assert centred_left_of_panel("#load-card"), "4b the card did not follow the panel"
    page.evaluate("document.querySelector('.lil-gui.lil-root').style.removeProperty('--width')")
    page.wait_for_timeout(200)
    centred_left_of_panel("#load-card")

    # ---- 5. 別のファイルを選ぶ: the file dialog, and the next load replaces the card
    with page.expect_file_chooser() as fc:
        page.click("#load-another")
    fc.value.set_files(STEP)
    wait_until(
        "document.querySelector('#hud-info').textContent.includes('三角形')"
        " && document.querySelector('#hud-info').textContent.includes('mini_mold.step')"
    )
    assert not card()["shown"], "5 the next load's success clears the failed card"

    # ---- 6. too narrow to sit beside the panel: the middle of the window, over
    #    the panel, and its buttons still take clicks
    page.set_viewport_size({"width": 450, "height": 800})
    page.wait_for_timeout(300)
    fail_with(broken, "STL として読めない")
    assert not centred_left_of_panel("#load-card"), "6 450 px leave no room beside the panel"
    page.click("#load-close")  # over the panel: Playwright refuses a click on a covered button
    assert not card()["shown"]

    def above_panel(sel):
        """drawn over the operation panel: the higher z-index in the same stacking context"""
        return page.evaluate(
            "s => +getComputedStyle(document.querySelector(s)).zIndex"
            " > +getComputedStyle(document.querySelector('.lil-gui.lil-root')).zIndex",
            sel,
        )

    # the loading card and the open card go over the panel too; the open
    # card's button takes clicks there
    meshes = []
    held_requests("**/mesh.bin", "GET", meshes)
    page.set_input_files("#file-input", STL)
    wait_held(meshes)
    assert not centred_left_of_panel("#load-card") and above_panel("#load-card"), "6 the loading card under the panel"
    Net.of(page).unroute("**/mesh.bin")
    meshes[0].continue_()
    wait_until("document.querySelector('#hud-info').textContent.includes('三角形')")
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    assert visible("#empty-hint") and not centred_left_of_panel("#empty-hint")
    assert above_panel("#empty-hint"), "6 the open card under the panel"
    with page.expect_file_chooser():
        page.click("#empty-open")

    page.screenshot(path="/tmp/cad_viewer_load_card.png")
    # the refused and aborted requests of the failures
    errors = [e for e in errors if "Failed to load resource" not in e]
    if errors:
        print("PAGE ERRORS:", errors)
    assert not errors
    print("LOAD CARD E2E OK")
    browser.close()
