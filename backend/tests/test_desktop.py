"""The installed app's entry (app/desktop.py) and where the data goes (app/paths.py).

The whole start (the server, the second start, the data folder) is run as a
separate process, as the exe runs it (CAD_VIEWER_NO_TRAY, no browser): the
data folder is decided before the server's modules are imported, which an
import in this process (conftest's) would have done already. The exe itself is
tested on Windows by packaging/windows/smoke.py (.github/workflows/windows.yml).

Oracles: inch_block.step is a 25.4 x 50.8 x 12.7 box (testdata/make_step_assembly.py);
the folders are fresh, so what lands in them is the app's doing.
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

import pytest

from app import desktop, drawing

BACKEND = pathlib.Path(__file__).resolve().parent.parent
BOX = BACKEND.parent / "testdata" / "inch_block.step"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve(handler, port: int = 0):
    """a server on 127.0.0.1 in a thread (shut down by the caller)"""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Ours(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"status": "ok", "version": "0.0.0"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Other(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


# --- where the data goes ----------------------------------------------------


def test_data_dir():
    assert desktop.data_dir({"CAD_VIEWER_DATA_DIR": "/x/y"}, windows=True) == pathlib.Path("/x/y")
    assert desktop.data_dir({"LOCALAPPDATA": "/la"}, windows=True) == pathlib.Path("/la/cad-viewer")
    assert desktop.data_dir({"XDG_DATA_HOME": "/xdg"}, windows=False) == pathlib.Path("/xdg/cad-viewer")
    assert desktop.data_dir({}, windows=False) == pathlib.Path.home() / ".local" / "share" / "cad-viewer"


def test_paths(monkeypatch, tmp_path):
    from app import paths

    monkeypatch.delenv("CAD_VIEWER_DATA_DIR", raising=False)
    monkeypatch.delenv("CAD_VIEWER_DIST", raising=False)
    assert paths.data_dir("sidecars") == BACKEND / ".sidecars"
    assert paths.dist_dir() == BACKEND.parent / "frontend" / "dist"
    monkeypatch.setenv("CAD_VIEWER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAD_VIEWER_DIST", str(tmp_path / "web"))
    assert paths.data_dir("cache") == tmp_path / "cache"
    assert paths.dist_dir() == tmp_path / "web"


# --- the port ---------------------------------------------------------------


def test_answer():
    ours, other = serve(Ours), serve(Other)
    try:
        assert desktop.answer(ours.server_address[1]) == "ours"
        assert desktop.answer(other.server_address[1]) == "other"
        assert desktop.answer(free_port(), timeout=1) == "none"
    finally:
        ours.shutdown()
        other.shutdown()


def test_find_port():
    # free: claimed (listening, so a second claim fails)
    p = free_port()
    port, sock = desktop.find_port(p, tries=1)
    try:
        assert port == p and sock is not None and desktop.claim(p) is None
    finally:
        sock.close()
    # ours already there: no socket, the browser goes to it
    ours = serve(Ours)
    try:
        assert desktop.find_port(ours.server_address[1], tries=1) == (ours.server_address[1], None)
    finally:
        ours.shutdown()
    # another program's (answering, not as cad-viewer): the next port at once
    for _ in range(20):
        p = free_port()
        try:
            other = serve(Other, p)
        except OSError:
            continue
        if desktop.claim(p + 1) is None:  # the next one taken by chance: try another pair
            other.shutdown()
            continue
        break
    try:
        t = time.monotonic()
        port, sock = desktop.find_port(p, tries=2, wait=20)
        assert port == p + 1 and sock is not None and time.monotonic() - t < 5
        sock.close()
    finally:
        other.shutdown()


# --- the whole start, as the exe --------------------------------------------


def _start(env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import sys; from app.desktop import main; sys.exit(main())"],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _health(port: int, proc: subprocess.Popen, seconds: float = 60) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert proc.poll() is None, proc.stderr.read().decode(errors="replace")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                return json.loads(r.read())
        except OSError:
            time.sleep(0.3)
    raise AssertionError("no answer")


@pytest.mark.skipif(not BOX.exists(), reason="run testdata/make_step_assembly.py first")
def test_start_twice(tmp_path):
    """the data under the user's folder (XDG_DATA_HOME here, %LOCALAPPDATA% on
    Windows), the second start finds the first and exits"""
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CAD_VIEWER_")}
    env.update(XDG_DATA_HOME=str(tmp_path / "xdg"), LOCALAPPDATA=str(tmp_path / "la"),
               CAD_VIEWER_PORT=str(port), CAD_VIEWER_NO_BROWSER="1", CAD_VIEWER_NO_TRAY="1")
    folder = tmp_path / ("la" if os.name == "nt" else "xdg") / "cad-viewer"
    first = _start(env)
    try:
        assert _health(port, first)["status"] == "ok"
        boundary = uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="inch_block.step"\r\n\r\n'
        ).encode() + BOX.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/models", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=120) as r:
            model = json.loads(r.read())
        note = {"notes": [{"text": "注記"}]}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/models/{model['id']}/sidecar",
                                     data=json.dumps(note).encode(), method="PUT")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=30).read()
        sidecars = list((folder / "sidecars").glob("*.json"))
        assert len(sidecars) == 1 and json.loads(sidecars[0].read_text(encoding="utf-8")) == note
        assert list((folder / "cache").glob("*.bin")), "the cache in the user's folder"

        second = _start(env)
        assert second.wait(timeout=60) == 0
        log = (folder / "cad-viewer.log").read_text(encoding="utf-8")
        assert f"already running on {port}" in log, log
        assert first.poll() is None
    finally:
        first.terminate()
        first.wait(timeout=30)


# --- DWG's converter on Windows ---------------------------------------------


def test_find_oda_on_windows(tmp_path, monkeypatch):
    """where ODA's installer puts it (a folder per version), the newest by its
    numbers (26.10 after 26.4, not before as text), PATH first"""
    for version in ("25.12.0", "26.4.0", "26.10.0"):
        d = tmp_path / "pf" / "ODA" / f"ODAFileConverter {version}"
        d.mkdir(parents=True)
        (d / "ODAFileConverter.exe").write_bytes(b"")
    (tmp_path / "pf86").mkdir()
    monkeypatch.setattr(drawing.sys, "platform", "win32")
    monkeypatch.setattr(drawing.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    found = drawing.find_oda()
    assert found and pathlib.Path(found).parent.name == "ODAFileConverter 26.10.0", found
    monkeypatch.setattr(drawing.shutil, "which", lambda name: "C:/tools/ODAFileConverter.exe")
    assert drawing.find_oda() == "C:/tools/ODAFileConverter.exe"
    monkeypatch.setattr(drawing.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
    assert drawing.find_oda() is None
    monkeypatch.setattr(drawing.sys, "platform", "linux")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    assert drawing.find_oda() is None, "Linux: PATH only"


def test_dwg_on_windows_uses_the_found_converter(monkeypatch):
    """Windows: ezdxf is told where the converter is (it looks only at its own
    setting), and Qt is not sent to xcb (Windows' Qt has none)"""
    import ezdxf
    from ezdxf.addons import odafc

    seen = {}

    def readfile(path):
        seen["exe"] = ezdxf.options.get("odafc-addon", "win_exec_path")
        seen["qt"] = os.environ.get("QT_QPA_PLATFORM")
        raise RuntimeError("stop here")

    old = ezdxf.options.get("odafc-addon", "win_exec_path")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(drawing.sys, "platform", "win32")
    monkeypatch.setattr(drawing, "find_oda", lambda: r"C:\ODA\ODAFileConverter 26.4.0\ODAFileConverter.exe")
    monkeypatch.setattr(odafc, "readfile", readfile)
    try:
        with pytest.raises(drawing.DrawingLoadError, match="DWG変換失敗"):
            drawing.load_drawing(b"AC1027", "a.dwg")
    finally:
        ezdxf.options.set("odafc-addon", "win_exec_path", old)
    assert seen == {"exe": r"C:\ODA\ODAFileConverter 26.4.0\ODAFileConverter.exe", "qt": None}
