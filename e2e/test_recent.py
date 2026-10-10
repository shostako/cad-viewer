"""E2E: 最近開いたファイル (issue #47 item 5).

The file picker (File System Access) opens a file and keeps its handle in this
browser (IndexedDB), newest first, up to 8. The list is on the empty screen's
card and under 開く's ▾; a row opens the file again (asking for leave to read
it again when the browser wants that), and its measurements and notes come
back from the sidecar; × takes a row off.

- Fresh: no list on the card; the ▾ says there is none yet.
- Picked files are listed newest first, with when and how big; the same file
  picked again moves up (no second row); the ninth file pushes the oldest off.
- After a reload the card lists them; a row opens its file, the saved note
  comes back, and the row moves to the top.
- × takes a row off, also for the next visit.
- A file that is gone: the status line says so and the row goes. Leave to read
  refused: the status line says so and the row stays.
- Esc and a click elsewhere close the ▾'s list; with the key list open as
  well, Esc closes only the ▾'s list (one press, one thing).
- Two tabs share the list: a file opened in one is listed in the other, and a
  row taken off in one does not come back by the other's next change.
- A picked file that cannot be read (gone between the pick and the read): the
  status line says so.
- Without the picker (another browser): 開く falls back to the plain file
  dialog, and nothing is added (no handle).

The picker cannot be driven in headless Chromium, so a stand-in for
window.showOpenFilePicker returns real FileSystemFileHandles of files written
into the origin private file system (navigator.storage.getDirectory()): the
same kind of handle Chrome's picker gives, kept in IndexedDB as it is.

Oracles: the files written here (their names and sizes), the DOM (rows,
texts), the status line, the measure list (the note saved through the API for
the file's bytes, as put_sidecar does).
"""
import base64

from nav_common import TESTDATA, box_stl, nav_session, put_sidecar

STUB = """
window.__picked = 0
window.showOpenFilePicker = async () => {
  window.__picked++
  const root = await navigator.storage.getDirectory()
  return [await root.getFileHandle(window.__nextPick)]
}
"""
NOTE = {"text": "📌 最近の注記", "labelText": "最近の注記", "labelPos": [50, 30, 35], "markers": [[50, 30, 35]], "annotation": True}

with nav_session() as n:
    page = n.page
    page.add_init_script(STUB)
    page.reload()
    page.wait_for_load_state("networkidle")

    def put_file(name, data, pg=None):
        (pg or page).evaluate(
            """async ([name, b64]) => {
                 const root = await navigator.storage.getDirectory()
                 const h = await root.getFileHandle(name, { create: true })
                 const w = await h.createWritable()
                 await w.write(Uint8Array.from(atob(b64), c => c.charCodeAt(0)))
                 await w.close() }""",
            [name, base64.b64encode(data).decode()],
        )

    def pick(name, pg=None):
        """開く with the picker giving this file; waits for its status line"""
        pg = pg or page
        pg.evaluate("n => { window.__nextPick = n }", name)
        pg.locator("#toolbar button[data-action='open']").click()
        pg.wait_for_function("n => document.querySelector('#hud-info').textContent.includes(n)", arg=name, timeout=60000)
        pg.wait_for_timeout(150)  # the list is written after the open

    def pop_rows(pg=None):
        return (pg or page).locator("#recent-pop-list .recent-name").all_text_contents()

    def card_rows(pg=None):
        return (pg or page).locator("#recent-list .recent-name").all_text_contents()

    def open_pop(pg=None):
        pg = pg or page
        pg.locator("#toolbar button[data-action='recent']").click()
        pg.wait_for_selector("#recent-pop:not(.hidden)")

    def hidden(sel):
        return "hidden" in (page.locator(sel).get_attribute("class") or "")

    # ---- 1. fresh: nothing kept yet
    assert hidden("#recent-box"), "no list on the card before anything is opened"
    open_pop()
    assert pop_rows() == [] and not hidden("#recent-pop-empty"), (pop_rows(), "the ▾ says there is none")
    assert page.locator("#toolbar button[data-action='recent']").get_attribute("aria-pressed") == "true"
    page.keyboard.press("Escape")
    assert hidden("#recent-pop"), "Esc closes the list"
    assert page.locator("#toolbar button[data-action='recent']").get_attribute("aria-pressed") == "false"

    # the files: private copies (their own content hashes, so their own sidecars)
    mold = (TESTDATA / "mini_mold.step").read_bytes() + b"\n" * 37
    curved = (TESTDATA / "curved_part.step").read_bytes() + b"\n" * 41
    put_file("mold_a.step", mold)
    put_file("curved_b.step", curved)
    sizes = {"mold_a.step": len(mold), "curved_b.step": len(curved)}
    # the note saved for mold_a's bytes comes back when it is opened from the list
    tmp_mold = n.paths["step"].rsplit("/", 1)[0] + "/mold_a.step"
    open(tmp_mold, "wb").write(mold)
    put_sidecar(page, tmp_mold, [NOTE])

    # ---- 2. picked files are listed, newest first
    pick("mold_a.step")
    pick("curved_b.step")
    assert page.evaluate("window.__picked") == 2
    open_pop()
    assert pop_rows() == ["curved_b.step", "mold_a.step"], pop_rows()
    metas = page.locator("#recent-pop-list .recent-meta").all_text_contents()
    for name, meta in zip(pop_rows(), metas):
        kb = max(1, round(sizes[name] / 1024))
        assert meta.endswith(f"・ {kb} KB"), (name, meta, kb)
    page.mouse.click(400, 400)  # a click elsewhere closes it
    assert hidden("#recent-pop")
    pick("mold_a.step")  # the same file again: it moves up, no second row
    open_pop()
    assert pop_rows() == ["mold_a.step", "curved_b.step"], pop_rows()
    page.keyboard.press("Escape")
    print("2 listed", pop_rows())

    # ---- 3. after a reload: the card lists them; a row opens its file with its note
    page.reload()
    page.wait_for_selector("#recent-box:not(.hidden)", timeout=10000)
    assert card_rows() == ["mold_a.step", "curved_b.step"], card_rows()
    page.locator("#recent-list .recent-open").nth(1).click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('curved_b.step')", timeout=60000)
    page.wait_for_timeout(150)
    open_pop()
    assert pop_rows() == ["curved_b.step", "mold_a.step"], ("the row opened moves to the top", pop_rows())
    page.locator("#recent-pop-list .recent-open").nth(1).click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('mold_a.step')", timeout=60000)
    assert hidden("#recent-pop"), "opening a row closes the list"
    page.wait_for_function("document.querySelector('#measure-list')?.textContent.includes('最近の注記')", timeout=10000)
    print("3 reopened, the note came back")

    # ---- 4. eight at most: the oldest go
    for i in range(8):
        path = n.paths["step"].rsplit("/", 1)[0] + f"/box_{i}.stl"
        box_stl(path, (0, 0, 0), (10 + i, 10, 10))
        put_file(f"box_{i}.stl", open(path, "rb").read())
        pick(f"box_{i}.stl")
    open_pop()
    want = [f"box_{i}.stl" for i in range(7, -1, -1)]
    assert pop_rows() == want, ("the newest eight", pop_rows())
    page.keyboard.press("Escape")

    # ---- 5. × takes a row off, for the next visit too
    open_pop()
    page.locator("#recent-pop-list .recent-row").nth(2).locator(".recent-forget").click()
    want.pop(2)
    # the row goes once the list is written (IndexedDB), a moment later
    page.wait_for_function("n => document.querySelectorAll('#recent-pop-list .recent-row').length === n", arg=len(want))
    assert pop_rows() == want, pop_rows()
    assert not hidden("#recent-pop"), "× does not close the list"
    page.keyboard.press("Escape")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#recent-box:not(.hidden)", timeout=10000)
    assert card_rows() == want, ("kept for the next visit", card_rows())
    print("5 forgot one", card_rows())

    # ---- 6. a file that is gone: said, and its row goes
    page.evaluate("async () => (await navigator.storage.getDirectory()).removeEntry('box_7.stl')")
    page.locator("#recent-list .recent-open").nth(0).click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('box_7.stl が見つからない')", timeout=10000)
    want.pop(0)
    page.wait_for_function("n => document.querySelectorAll('#recent-list .recent-row').length === n", arg=len(want))
    assert card_rows() == want, card_rows()

    # ---- 7. leave to read refused: said, and the row stays
    page.evaluate(
        """() => { const P = FileSystemFileHandle.prototype
             P.queryPermission = async () => 'prompt'; P.requestPermission = async () => 'denied' }"""
    )
    page.locator("#recent-list .recent-open").nth(0).click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('を読む許可が無い')", timeout=10000)
    assert card_rows() == want, ("the row stays", card_rows())
    page.reload()  # the stand-ins for leave go with the page
    page.wait_for_load_state("networkidle")
    # the list as kept for the next visit (a change is written a moment after the click)
    page.wait_for_selector("#recent-box:not(.hidden)", timeout=10000)
    assert card_rows() == want, ("a refused row stays, also for the next visit", card_rows())
    print("6-7 gone and refused ok")

    # ---- 7b. Esc with the key list open too: only the ▾'s list goes
    page.keyboard.press("?")
    page.wait_for_selector("#help-card:not(.hidden)", timeout=5000)
    open_pop()
    page.keyboard.press("Escape")
    assert hidden("#recent-pop"), "Esc closes the ▾'s list"
    assert not hidden("#help-card"), "the key list stays (one press, one thing)"
    page.keyboard.press("Escape")
    assert hidden("#help-card")

    # ---- 7c. a picked file that cannot be read: said
    put_file("gone.stl", open(path, "rb").read())
    page.evaluate(
        "async () => { const root = await navigator.storage.getDirectory();"
        " const h = await root.getFileHandle('gone.stl'); await root.removeEntry('gone.stl');"
        " window.showOpenFilePicker = async () => [h] }"
    )
    page.locator("#toolbar button[data-action='open']").click()
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('gone.stl を読めなかった')", timeout=10000)
    page.reload()  # the stand-in picker comes back with the page
    page.wait_for_load_state("networkidle")

    # ---- 7d. two tabs share the list (one browser context: its storage is theirs)
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(STUB)
    tab_a, tab_b = ctx.new_page(), ctx.new_page()
    for t in (tab_a, tab_b):
        t.goto(page.url)
        t.wait_for_load_state("networkidle")
    box = open(path, "rb").read()
    for name in ("two_0.stl", "two_1.stl", "two_2.stl"):
        put_file(name, box, tab_a)
    for name in ("two_0.stl", "two_1.stl"):
        pick(name, tab_a)
    # a file opened in one tab is listed in the other
    tab_b.wait_for_function("() => document.querySelector('#recent-list .recent-name')?.textContent === 'two_1.stl'", timeout=10000)
    assert card_rows(tab_b) == ["two_1.stl", "two_0.stl"], card_rows(tab_b)
    # the other tab takes a row off; this tab's next change must not bring it back
    tab_b.locator("#recent-list .recent-row").nth(1).locator(".recent-forget").click()
    tab_a.wait_for_function("() => ![...document.querySelectorAll('#recent-list .recent-name, #recent-pop-list .recent-name')].some(e => e.textContent === 'two_0.stl')", timeout=10000)
    pick("two_2.stl", tab_a)
    open_pop(tab_a)
    assert pop_rows(tab_a) == ["two_2.stl", "two_1.stl"], ("the other tab's change kept", pop_rows(tab_a))
    tab_a.keyboard.press("Escape")
    # a change whose word never came (another tab writing without telling): the
    # next change is made to the list as stored, not to this tab's copy
    tab_a.evaluate(
        "() => new Promise((ok, no) => { const r = indexedDB.open('cad-viewer', 1);"
        " r.onsuccess = () => { const tx = r.result.transaction('recent', 'readwrite'); const st = tx.objectStore('recent');"
        " const g = st.get('list'); g.onsuccess = () => { st.put(g.result.filter(e => e.name !== 'two_1.stl'), 'list') };"
        " tx.oncomplete = () => { r.result.close(); ok() }; tx.onerror = () => no(tx.error) }; r.onerror = () => no(r.error) })"
    )
    pick("two_0.stl", tab_a)
    open_pop(tab_a)
    assert pop_rows(tab_a) == ["two_0.stl", "two_2.stl"], ("the stored list, not this tab's copy", pop_rows(tab_a))
    ctx.close()
    print("7 Esc, unreadable, two tabs ok")

    # ---- 8. without the picker: the plain file dialog, nothing added
    page.evaluate("window.showOpenFilePicker = undefined")
    before = card_rows()
    with page.expect_file_chooser() as fc:
        page.locator("#toolbar button[data-action='open']").click()
    fc.value.set_files(n.paths["step"])
    page.wait_for_function("document.querySelector('#hud-info').textContent.includes('三角形')", timeout=60000)
    open_pop()
    assert pop_rows() == before, ("no handle, no row", pop_rows(), before)
    page.keyboard.press("Escape")
    print("8 fallback ok")
print("RECENT E2E OK")
