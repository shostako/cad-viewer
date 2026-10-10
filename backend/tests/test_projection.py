"""Projected area along an axis (issue #47 item 4: the clamping-force estimate).

Expected areas come from how the shapes were built (box sides, where the
parts sit), never from the code under test.

mini_mold.step (testdata/make_step_assembly.py):
  plate 100 x 60 x 15 at the origin; core pins r 4, z 15..40 at (25, 30) and
  (75, 30); cavity block 40 x 30 x 20 at (30, 15, 15).
Its shadows:
  along Z: the plate covers everything             100 x 60 = 6000
  along X: plate 60 x 15 + block 30 x 20 + the pins' 8 x 5 above the block
           (both pins fall on the same rectangle)  900 + 600 + 40 = 1540
  along Y: plate 100 x 15 + block 40 x 20 + two pins 8 x 25, apart from the
           block (x 21..29, 71..79 vs 30..70)      1500 + 800 + 400 = 2700
"""
import io
import pathlib
import tempfile
from collections import OrderedDict

import pytest
import trimesh
from fastapi.testclient import TestClient
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

from app.main import app

TESTDATA = pathlib.Path(__file__).resolve().parents[2] / "testdata"
STEP = TESTDATA / "mini_mold.step"
DXF = TESTDATA / "plate_drawing.dxf"
REL = 5e-4  # the rasterised union: mini_mold lands within 0.03 %


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import cache
    from app.store import store

    monkeypatch.setattr(store, "_models", OrderedDict())
    monkeypatch.setattr(store, "_by_hash", {})
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    return TestClient(app)


def _upload(client, name, data):
    r = client.post("/api/models", files={"file": (name, data, "x")})
    assert r.status_code == 200, r.text
    return r.json()


def _area(client, mid, axis, parts=None):
    q = f"axis={axis}" + ("" if parts is None else f"&parts={parts}")
    r = client.get(f"/api/models/{mid}/projected_area?{q}")
    assert r.status_code == 200, r.text
    return r.json()


def _step_bytes(shape) -> bytes:
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "s.step"
        assert w.Write(str(p)) == IFSelect_RetDone
        return p.read_bytes()


def _ids(meta, name):
    return [p["id"] for p in meta["parts"] if p["name"] == name]


@pytest.mark.parametrize("axis, expected", [("Z", 6000.0), ("X", 1540.0), ("Y", 2700.0)])
def test_mini_mold_shadows(client, axis, expected):
    meta = _upload(client, "mini_mold.step", STEP.read_bytes())
    body = _area(client, meta["id"], axis)
    assert body["axis"] == axis
    assert body["area"] == pytest.approx(expected, rel=REL)
    assert body["parts"] == sorted(p["id"] for p in meta["parts"])


def test_only_the_given_parts(client):
    meta = _upload(client, "mini_mold.step", STEP.read_bytes())
    mid = meta["id"]
    plate, block, pins = _ids(meta, "plate"), _ids(meta, "cavity_block"), _ids(meta, "core_pin")
    assert len(plate) == 1 and len(block) == 1 and len(pins) == 2
    csv = lambda ids: ",".join(map(str, ids))  # noqa: E731
    # the plate alone along X: 60 x 15
    assert _area(client, mid, "X", csv(plate))["area"] == pytest.approx(900.0, rel=REL)
    # the two pins along Y: 2 x 8 x 25 (the plate and block left out)
    assert _area(client, mid, "Y", csv(pins))["area"] == pytest.approx(400.0, rel=REL)
    # the block and the pins along X: 30 x 20 + 8 x 5 above it, the pins counted once
    assert _area(client, mid, "X", csv(block + pins))["area"] == pytest.approx(640.0, rel=REL)
    # nothing visible: no shadow
    none = _area(client, mid, "Z", "")
    assert none["area"] == 0.0 and none["parts"] == []


def test_through_hole_stays_open(client):
    # 40 x 30 x 5 with a 10 x 10 window through it along Z: 1200 - 100
    frame = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(40, 30, 5).Shape(), BRepPrimAPI_MakeBox(gp_Pnt(15, 10, -1), 10, 10, 7).Shape()
    ).Shape()
    meta = _upload(client, "frame.step", _step_bytes(frame))
    assert _area(client, meta["id"], "Z")["area"] == pytest.approx(1100.0, rel=REL)
    # from the side the window is hidden behind the walls: 30 x 5 and 40 x 5
    assert _area(client, meta["id"], "X")["area"] == pytest.approx(150.0, rel=REL)
    assert _area(client, meta["id"], "Y")["area"] == pytest.approx(200.0, rel=REL)


def test_thin_plate_edge_on(client):
    # a 300 x 60 x 1 plate seen from its long edge: 300 x 1. The rasterising
    # error is about the outline's length times a pixel (projection.py), a
    # larger share of so thin a shadow than of the others
    meta = _upload(client, "thin.step", _step_bytes(BRepPrimAPI_MakeBox(300, 60, 1).Shape()))
    edge = _area(client, meta["id"], "Y")
    assert edge["area"] == pytest.approx(300.0, abs=2 * (300 + 1) * edge["pixel"])
    assert edge["area"] == pytest.approx(300.0, rel=3e-3)
    assert _area(client, meta["id"], "Z")["area"] == pytest.approx(18000.0, rel=REL)


def test_mesh_format(client):
    buf = io.BytesIO()
    trimesh.creation.box(extents=(10, 20, 30)).export(buf, file_type="stl")
    meta = _upload(client, "box.stl", buf.getvalue())
    assert _area(client, meta["id"], "X")["area"] == pytest.approx(600.0, rel=REL)
    assert _area(client, meta["id"], "Z")["area"] == pytest.approx(200.0, rel=REL)


def test_rejects(client):
    meta = _upload(client, "mini_mold.step", STEP.read_bytes())
    assert client.get(f"/api/models/{meta['id']}/projected_area?axis=W").status_code == 422
    assert client.get(f"/api/models/{meta['id']}/projected_area?parts=a,b").status_code == 422
    assert client.get("/api/models/nope/projected_area").status_code == 404
    drawing = _upload(client, "plate_drawing.dxf", DXF.read_bytes())
    assert client.get(f"/api/models/{drawing['id']}/projected_area").status_code == 422


def _wait(cond, what, timeout=10.0):
    import time

    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, what
        time.sleep(0.01)


def test_one_at_a_time_and_stale_requests_give_up(client):
    """A calculation in progress (the gate held here) makes the others wait. Of
    two waiting requests from one page, the older gives up (409) and the newer
    computes; another page's request is not given up for it. A request whose
    answer was computed meanwhile gets that answer."""
    import threading

    from app.main import _projection_gate
    from app.store import store

    meta = _upload(client, "mini_mold.step", STEP.read_bytes())
    mid = meta["id"]
    gate = _projection_gate(store.get(mid))
    out = {}

    def ask(tag, q):
        out[tag] = client.get(f"/api/models/{mid}/projected_area?{q}")

    gate.lock.acquire()  # a calculation in progress
    threads = []
    try:
        for tag, q in (("old", "axis=X&client=A"), ("other", "axis=Z&client=B"), ("new", "axis=Y&client=A")):
            n = gate.count
            t = threading.Thread(target=ask, args=(tag, q))
            t.start()
            threads.append(t)
            _wait(lambda: gate.count > n, f"{tag} never asked")  # in that order
        # all three wait: nothing has answered yet
        assert not out, out
    finally:
        gate.lock.release()
    for t in threads:
        t.join(timeout=60)
    assert out["old"].status_code == 409, out["old"].text
    assert out["new"].status_code == 200 and out["new"].json()["area"] == pytest.approx(2700.0, rel=REL)
    assert out["other"].status_code == 200 and out["other"].json()["area"] == pytest.approx(6000.0, rel=REL)
    # the page asks for X again: computed now (the given-up one left nothing behind)
    assert _area(client, mid, "X")["area"] == pytest.approx(1540.0, rel=REL)

    # an answer already there comes at once, without waiting for the gate, and
    # it still counts as the page asking again: the page's request waiting
    # behind the gate (the plate hidden) gives up once the page has gone back
    # to the known answer (the plate shown again)
    plate = _ids(meta, "plate")[0]
    rest = ",".join(str(p["id"]) for p in meta["parts"] if p["id"] != plate)
    gate.lock.acquire()
    try:
        n = gate.count
        t1 = threading.Thread(target=ask, args=("hidden", f"axis=Z&parts={rest}&client=D"))
        t1.start()
        _wait(lambda: gate.count > n, "the request without the plate never asked")
        n = gate.count
        ask("known", "axis=Z&client=D")  # all parts along Z: known, so no waiting here
        assert out["known"].status_code == 200 and out["known"].json()["area"] == pytest.approx(6000.0, rel=REL)
        assert gate.count > n, "a known answer must still take the page's ticket"
        assert "hidden" not in out, "the waiting request must still wait"
    finally:
        gate.lock.release()
    t1.join(timeout=60)
    assert out["hidden"].status_code == 409, out["hidden"].text
