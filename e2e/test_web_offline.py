"""E2E: the Web version's build as an app (docs/designs/web-version.md, W7).

The built Web version (npm run build:web) at CAD_VIEWER_WEB_BUILD (its folder,
frontend/dist-web), served by this script; without it, skipped (the checkout's
version and Vite's dev server have no service worker).

"Offline" is the server down: its connections closed unanswered, the page's
and the Worker's alike (Playwright's set_offline cuts the page's only: the
Worker would still fetch OpenCASCADE and Python from the network).

- The service worker takes the page over once it is open; the server down
  straight after the first visit, the page opens again (kept at install).
- A STEP opened, then (a new page, its own Worker) the same file again: it
  comes from the load cache (the answer says cached), the B-rep read again for
  a measurement.
- The server down: the page opens again from what the service worker kept (at
  an address with ?…, never asked for online: the app's page); a STEP opens
  and is measured (OpenCASCADE's wasm from the kept copy), a DXF
  opens (Pyodide and ezdxf from the kept copies).
- A file the PC opens with the installed app (window.launchQueue, stubbed here:
  no installing in a test) opens as one chosen in the file picker, and goes on
  the recent list.

Oracles: the answers' own fields (cached), the status line, the recent list,
navigator.serviceWorker.controller; none from the code under test.
"""
import base64
import mimetypes
import os
import socket
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

import engine_net

BUILD = os.environ.get("CAD_VIEWER_WEB_BUILD")
if not BUILD:
    print("skipped: set CAD_VIEWER_WEB_BUILD to the Web version's build (frontend/dist-web, npm run build:web)")
    sys.exit(0)
BUILD = Path(BUILD).resolve()
assert (BUILD / "sw.js").is_file(), f"{BUILD}: no sw.js (not the Web version's build?)"

for ext, kind in ((".mjs", "text/javascript"), (".js", "text/javascript"), (".wasm", "application/wasm"), (".webmanifest", "application/manifest+json")):
    mimetypes.add_type(kind, ext)


class Site(SimpleHTTPRequestHandler):
    """the build's files; while the site is down, every connection closed unanswered"""

    down = False

    def handle_one_request(self):
        if Site.down:
            self.close_connection = True
            return
        super().handle_one_request()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")  # as a site that changes: asked again each time
        # GitHub Pages sends Vary: Accept-Encoding, Vite's preview Vary: Origin; with the
        # latter the page kept at install was set apart from the page asked for, until
        # sw.js matched by the address alone (ignoreVary)
        self.send_header("Vary", "Accept-Encoding, Origin")
        super().end_headers()

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Site, directory=str(BUILD)))
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_address[1]}/"

TESTDATA = Path(__file__).resolve().parents[1] / "testdata"
STEP = TESTDATA / "mini_mold.step"
DXF = TESTDATA / "plate_drawing.dxf"
STL = TESTDATA / "ribbed_plate.stl"

# the installed app's launch queue, stubbed: the app's consumer is kept to be called
LAUNCH_STUB = """
Object.defineProperty(window, 'launchQueue', {
  configurable: true,
  value: { setConsumer(f) { window.__cadLaunch = f } },
})
"""


def status_has(page, text, timeout=120000):
    page.wait_for_function("t => document.querySelector('#hud-info').textContent.includes(t)", arg=text, timeout=timeout)


def open_input(page, path, text="三角形"):
    page.set_input_files("#file-input", str(path))
    status_has(page, path.name)
    status_has(page, text)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    context.add_init_script(LAUNCH_STUB)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ---- 1. the service worker takes the page over
    page.goto(URL)
    page.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller !== null", timeout=60000)
    # the first visit, the server down at once: the page kept at install opens
    Site.down = True
    page.reload()
    page.wait_for_selector("#file-input", state="attached", timeout=60000)
    page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=60000)
    Site.down = False
    print("1 the service worker controls the page; the page opens offline from the first visit")

    # ---- 2. a STEP, then the same in a new page: from the load cache
    open_input(page, STEP)
    open_input(page, DXF, "2D 図面")  # Pyodide and ezdxf fetched (and kept)
    page.reload()
    page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=60000)
    again = engine_net.upload(page, STEP).json()
    assert again.get("cached") is True, ("a new page, the same file: from the load cache", {k: again.get(k) for k in ("cached", "format", "partCount")})
    m = engine_net.api(page, "POST", f"/api/models/{again['id']}/measure", {"type": "face_info", "ref": {"partId": 0, "kind": "face", "id": 1}})
    assert m.status == 200 and m.json().get("type") == "face", (m.status, m.json())
    print("2 the same file again: cached, measured")

    # ---- 3. offline (the server down): the page and the files open from what was kept
    Site.down = True
    # an address never asked for online (as the app's start may come with ?…): the app's page
    page.goto(URL + "?from=offline")
    page.wait_for_selector("#file-input", state="attached", timeout=60000)
    page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=60000)
    open_input(page, STEP)
    up = engine_net.upload(page, STEP).json()
    m = engine_net.api(page, "POST", f"/api/models/{up['id']}/measure", {"type": "face_info", "ref": {"partId": 0, "kind": "face", "id": 1}})
    assert m.status == 200 and m.json().get("type") == "face", ("offline: OpenCASCADE from the kept copy", m.status, m.json())
    open_input(page, DXF, "2D 図面")
    print("3 offline: the page, a STEP measured, a DXF")

    # ---- 4. a file the PC opens with the app: opened, listed
    stl = base64.b64encode(STL.read_bytes()).decode()
    page.evaluate(
        """async ([name, b64]) => {
            const dir = await navigator.storage.getDirectory()
            const h = await dir.getFileHandle(name, { create: true })
            const w = await h.createWritable()
            await w.write(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)))
            await w.close()
            window.__cadLaunch({ files: [h] })
        }""",
        [STL.name, stl],
    )
    status_has(page, STL.name)
    status_has(page, "三角形")
    page.wait_for_timeout(300)  # the list is written after the open
    page.locator("#toolbar button[data-action='recent']").click()
    page.wait_for_selector("#recent-pop:not(.hidden)")
    rows = page.locator("#recent-pop-list .recent-name").all_text_contents()
    assert rows and rows[0] == STL.name, ("opened from the PC: on the recent list", rows)
    print("4 a file from the PC: opened, listed")

    Site.down = False
    assert not errors, errors
    print("WEB OFFLINE E2E OK")
    browser.close()
server.shutdown()
