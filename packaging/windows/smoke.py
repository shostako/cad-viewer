"""Smoke test of the built app (the exe, not the source): run on Windows after
PyInstaller, and on the installed copy after the installer.

    python packaging/windows/smoke.py <cad-viewer.exe> [--quick]

Oracles (none from the app's code): inch_block.step (testdata/make_step_assembly.py)
is a 25.4 x 50.8 x 12.7 mm box (its volume 16387.064 mm³, its wall 12.7);
plate_drawing.dxf (make_dxf.py) is 200 x 100. The data folder is a fresh one,
so what lands in it is the app's doing.

--quick (the installed copy): the self-check and one model only.
Only the standard library: it runs on the build's Python or any other.
"""
from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTDATA = ROOT / "testdata"
PORT = 18018  # not the app's own 8018: a copy the user started is left alone


def fail(msg: str) -> None:
    print("SMOKE FAILED:", msg)
    sys.exit(1)


def get(url: str, timeout: float = 30) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def get_json(url: str, timeout: float = 120):
    return json.loads(get(url, timeout).decode("utf-8"))


def upload(base: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{base}/api/models", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def put_json(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), method="PUT")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_up(base: str, proc: subprocess.Popen, seconds: float = 120) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            fail(f"the app exited ({proc.returncode}) before it answered")
        try:
            return get_json(f"{base}/api/health", timeout=2)
        except (OSError, ValueError):
            time.sleep(0.5)
    fail(f"no answer from {base} in {seconds} s")
    raise AssertionError


def self_check(exe: Path, work: Path) -> None:
    out = work / "self-check.json"
    rc = subprocess.run([str(exe), "--self-check", str(out)], timeout=300).returncode
    found = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    print("self-check:", rc, json.dumps(found, ensure_ascii=True))
    if rc != 0:
        fail("the self-check")
    if not found.get("frozen") or found.get("ocp_box_volume") != 6.0 or found.get("embree") is not True:
        fail("the self-check's findings")


def start(exe: Path, data: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ, CAD_VIEWER_DATA_DIR=str(data), CAD_VIEWER_PORT=str(port),
               CAD_VIEWER_NO_BROWSER="1", CAD_VIEWER_NO_TRAY="1")
    return subprocess.Popen([str(exe)], env=env)


def main() -> None:
    exe = Path(sys.argv[1]).resolve()
    quick = "--quick" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="cad-viewer-smoke-"))
    data = work / "data"
    self_check(exe, work)

    proc = start(exe, data, PORT)
    procs = [proc]
    try:
        base = f"http://127.0.0.1:{PORT}"
        health = wait_up(base, proc)
        print("health:", health)
        page = get(f"{base}/").decode("utf-8")
        if "<script" not in page:
            fail("the page at / is not the frontend")
        script = page.split('src="', 1)[1].split('"', 1)[0]
        if len(get(base + script)) < 10000:
            fail(f"the frontend's script {script}")

        box = upload(base, TESTDATA / "inch_block.step")
        props = get_json(f"{base}/api/models/{box['id']}/properties")
        volume = props["total"]["volume"]
        if abs(volume - 25.4 * 50.8 * 12.7) > 1e-3:
            fail(f"the box's volume {volume}")
        print("STEP: volume", volume)
        if quick:
            print("SMOKE OK (quick)")
            return

        thick = get_json(f"{base}/api/models/{box['id']}/thick")
        wall = thick["parts"][0]["nominal"]
        if abs(wall - 12.7) > 0.5:
            fail(f"the box's wall {wall}")
        ray = get(f"{base}/api/models/{box['id']}/thickness.bin?method=ray", timeout=120)
        if len(ray) < 24 * 4:
            fail("the ray thickness")
        print("thick: wall", wall, "ray bytes", len(ray))

        note = {"notes": [{"text": "日本語の注記 ⌀6"}]}
        put_json(f"{base}/api/models/{box['id']}/sidecar", note)
        back = get_json(f"{base}/api/models/{box['id']}/sidecar")
        if back != note:
            fail(f"the sidecar came back {back}")
        files = list((data / "sidecars").glob("*.json"))
        if len(files) != 1 or json.loads(files[0].read_text(encoding="utf-8")) != note:
            fail(f"the sidecar in the data folder: {files}")
        if not list((data / "cache").glob("*.bin")):
            fail("no cache in the data folder")
        print("sidecar and cache in", data)

        dxf = upload(base, TESTDATA / "plate_drawing.dxf")
        if dxf["format"] != "drawing" or dxf["bbox2d"]["max"] != [200.0, 100.0]:
            fail(f"the drawing {dxf.get('format')} {dxf.get('bbox2d')}")
        print("DXF:", dxf["bbox2d"])

        # a second start: finds the first, opens the browser (not here), exits
        second = start(exe, data, PORT)
        procs.append(second)
        try:
            rc = second.wait(timeout=60)
        except subprocess.TimeoutExpired:
            fail("the second start did not exit")
        if rc != 0 or "already running" not in (data / "cad-viewer.log").read_text(encoding="utf-8"):
            fail(f"the second start ({rc})")
        print("second start: found the first")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=30)

    # the port taken by another program (it answers, not as cad-viewer): the next one
    other = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    proc = start(exe, work / "data2", PORT)
    try:
        health = wait_up(f"http://127.0.0.1:{PORT + 1}", proc)
        print("port taken: on", PORT + 1, health)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        other.shutdown()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
