"""The installed app's entry (Windows): one local server, the browser, a tray icon.

Started from the Start menu (cad-viewer.exe, no console window):
- the data goes to the user's folder (%LOCALAPPDATA%\\cad-viewer: the cache, the
  sidecars with the measurements and notes, the log); the frontend bundled with
  the exe is served at /.
- the server listens on 127.0.0.1:8018, the same port every time: the browser
  keeps the app's settings (theme, materials, ...) per address. 8008 is a
  checkout's (start.sh in WSL, whose mirrored networking shares Windows'
  127.0.0.1). When 8018 is another program's, the next of 8019..8027.
- a second start finds the first one (its /api/health answers) and only opens
  the browser.
- the tray icon: open the browser, open the data folder, quit.

Environment (the smoke test's, packaging/windows/smoke.py): CAD_VIEWER_DATA_DIR,
CAD_VIEWER_PORT, CAD_VIEWER_NO_BROWSER=1, CAD_VIEWER_NO_TRAY=1 (no icon, the server
in the foreground). `cad-viewer.exe --self-check out.json` writes what the bundle
has (the libraries the app needs) and exits.

The server's modules are imported only after the environment is set
(paths.py reads it when they are imported).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8018
PORT_TRIES = 10  # 8018..8027
APP = "cad-viewer"
log = logging.getLogger(APP)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """the files shipped with the app (PyInstaller's folder, or the repo)"""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent


def data_dir(env=os.environ, windows: bool = os.name == "nt") -> Path:
    """the user's data: CAD_VIEWER_DATA_DIR, else %LOCALAPPDATA%\\cad-viewer
    ($XDG_DATA_HOME/cad-viewer, ~/.local/share/cad-viewer, elsewhere)"""
    if env.get("CAD_VIEWER_DATA_DIR"):
        return Path(env["CAD_VIEWER_DATA_DIR"])
    if windows:
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP


def frontend_dir() -> Path:
    """the built frontend: bundled (frontend_dist next to the exe's files) or the repo's"""
    if frozen():
        return bundle_dir() / "frontend_dist"
    return bundle_dir() / "frontend" / "dist"


# --- the port ---------------------------------------------------------------


def claim(port: int) -> socket.socket | None:
    """bind and listen on 127.0.0.1:port, or None when it is taken. Windows: the
    port only ours (SO_EXCLUSIVEADDRUSE), no other program can bind it over us"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        s.listen(128)
    except OSError:
        s.close()
        return None
    return s


def answer(port: int, timeout: float = 2.0) -> str:
    """what is on 127.0.0.1:port: "ours" (cad-viewer's /api/health answers),
    "other" (something else answers), "none" (nothing answers in time)"""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, ValueError, UnicodeDecodeError):
        return "other"
    except (OSError, urllib.error.URLError):
        return "none"
    ok = isinstance(body, dict) and body.get("status") == "ok" and "version" in body
    return "ours" if ok else "other"


def find_port(first: int, tries: int = PORT_TRIES, wait: float = 20.0) -> tuple[int, socket.socket | None]:
    """the first of first..first+tries-1 that is free (its socket, claimed) or
    already ours (None: open the browser there). A port taken but not answering
    yet may be ours starting up (two starts at once): waited for up to `wait`
    seconds before the next one."""
    for port in range(first, first + tries):
        s = claim(port)
        if s is not None:
            return port, s
        deadline = time.monotonic() + wait
        while True:
            what = answer(port)
            if what == "ours":
                return port, None
            if what == "other" or time.monotonic() > deadline:
                log.warning("port %d is another program's; trying the next", port)
                break
            time.sleep(0.5)
    raise RuntimeError(f"no port free in {first}..{first + tries - 1}")


# --- logging ----------------------------------------------------------------


class _ToLog:
    """sys.stdout / sys.stderr of a windowed exe (None there): into the log"""

    def __init__(self, level: int) -> None:
        self.level = level

    def write(self, text: str) -> int:
        for line in text.rstrip().splitlines():
            log.log(self.level, "%s", line)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def setup_logging(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{APP}.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    if sys.stdout is None:
        sys.stdout = _ToLog(logging.INFO)  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _ToLog(logging.ERROR)  # type: ignore[assignment]
    sys.excepthook = lambda t, v, tb: log.critical("uncaught", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.critical("uncaught in %s", a.thread, exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return path


# --- the self-check ---------------------------------------------------------


def _ocp_box_volume() -> float:
    """OpenCASCADE at work: a 1 x 2 x 3 box's volume (6)"""
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), props)
    return round(props.Mass(), 9)


def _embree() -> bool:
    """trimesh's rays on embree (trimesh falls back to slow ones silently)"""
    from trimesh.ray import ray_pyembree  # noqa: F401 — raises what is missing

    return bool(__import__("trimesh.ray", fromlist=["has_embree"]).has_embree)


def self_check(out: Path) -> int:
    """import what the app needs, write what was found (a windowed exe has no stdout)"""
    found: dict[str, object] = {"frozen": frozen(), "frontend": (frontend_dir() / "index.html").is_file()}
    rc = 0
    checks = {
        "version": lambda: __import__("app").__version__,
        "ocp_box_volume": _ocp_box_volume,
        "embree": _embree,
        "scipy": lambda: __import__("scipy").__version__,
        "ezdxf": lambda: __import__("ezdxf").__version__,
        "server": lambda: bool(__import__("app.main", fromlist=["app"]).app),
        "tray": lambda: __import__("pystray").Icon.__module__,
    }
    for name, get in checks.items():
        try:
            found[name] = get()
        except Exception as e:  # noqa: BLE001 — the check reports every failure
            found[name] = f"ERROR {type(e).__name__}: {e}"
            rc = 1
    if found.get("embree") is not True or found.get("ocp_box_volume") != 6.0 or not found["frontend"]:
        rc = 1
    out.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


# --- the tray ---------------------------------------------------------------


def _icon_image():
    from PIL import Image

    ico = bundle_dir() / "cad-viewer.ico"
    if ico.is_file():
        return Image.open(ico)
    return Image.new("RGB", (64, 64), (76, 154, 255))


def _open_folder(folder: Path) -> None:
    if os.name == "nt":
        os.startfile(folder)  # type: ignore[attr-defined]
    else:
        webbrowser.open(folder.as_uri())


def run_tray(url: str, folder: Path, server) -> None:
    """the icon in the notification area until 終了 (the server stops with it)"""
    import pystray

    def quit_app(icon, _item) -> None:
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("ブラウザで開く", lambda *_: webbrowser.open(url), default=True),
        pystray.MenuItem("データのフォルダを開く", lambda *_: _open_folder(folder)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", quit_app),
    )
    pystray.Icon(APP, _icon_image(), f"cad-viewer（{url}）", menu).run()


# --- main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--self-check"]:
        os.environ.setdefault("CAD_VIEWER_DIST", str(frontend_dir()))
        return self_check(Path(argv[1] if len(argv) > 1 else "self-check.json"))

    folder = data_dir()
    logfile = setup_logging(folder)
    from . import __version__

    log.info("cad-viewer %s starting (data %s)", __version__, folder)
    port, sock = find_port(int(os.environ.get("CAD_VIEWER_PORT") or PORT))
    url = f"http://127.0.0.1:{port}/"
    browser = not os.environ.get("CAD_VIEWER_NO_BROWSER")
    if sock is None:
        log.info("already running on %d: opening the browser", port)
        if browser:
            webbrowser.open(url)
        return 0
    if port != PORT and not os.environ.get("CAD_VIEWER_PORT"):
        log.warning("port %d was another program's: on %d (the browser's settings are kept per port)", PORT, port)

    os.environ["CAD_VIEWER_DATA_DIR"] = str(folder)
    os.environ["CAD_VIEWER_DIST"] = str(frontend_dir())
    import uvicorn

    from .main import app

    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))

    def open_when_up() -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.1)
        if server.started:
            log.info("serving %s (log %s)", url, logfile)
            if browser:
                webbrowser.open(url)

    threading.Thread(target=open_when_up, daemon=True).start()
    if os.environ.get("CAD_VIEWER_NO_TRAY"):
        server.run(sockets=[sock])
        return 0
    serving = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    serving.start()
    try:
        run_tray(url, folder, server)
    finally:
        server.should_exit = True
        serving.join(timeout=10)
    log.info("stopped")
    return 0
