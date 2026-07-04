"""Measurement API tests against known-truth geometry (mini_mold.step).

Geometry (see testdata/make_step_assembly.py):
  plate: box 100x60x15 at origin
  core_pin: cylinder r=4 h=25, at (25,30,15) and (75,30,15)
  cavity_block: box 40x30x20 at (30,15,15)
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

STEP = pathlib.Path(__file__).parent.parent.parent / "testdata" / "mini_mold.step"

pytestmark = pytest.mark.skipif(not STEP.exists(), reason="run testdata/make_step_assembly.py first")


@pytest.fixture(scope="module")
def model():
    client = TestClient(app)
    r = client.post("/api/models", files={"file": ("mini_mold.step", STEP.read_bytes(), "x")})
    assert r.status_code == 200
    meta = r.json()
    parts = {p["id"]: p["name"] for p in meta["parts"]}
    pin_ids = [pid for pid, n in parts.items() if n == "core_pin"]
    return client, meta["id"], pin_ids


def _measure(model, req):
    client, mid, _ = model
    r = client.post(f"/api/models/{mid}/measure", json=req)
    assert r.status_code == 200, r.text
    return r.json()


def _cylinder_face_id(model, part_id):
    """Find the cylindrical face of a pin by probing its 3 faces."""
    for fid in (1, 2, 3):
        info = _measure(model, {"type": "face_info", "ref": {"partId": part_id, "kind": "face", "id": fid}})
        if info.get("surface") == "cylinder":
            return fid, info
    raise AssertionError("no cylindrical face found on pin")


def test_pin_diameter_exact(model):
    _, _, pin_ids = model
    fid, info = _cylinder_face_id(model, pin_ids[0])
    assert info["diameter"] == pytest.approx(8.0, abs=1e-9)
    # axis is vertical
    assert abs(info["axis"][2]) == pytest.approx(1.0, abs=1e-9)


def test_pin_axis_distance(model):
    """Distance between the two pin cylinder surfaces = 50 - 8 = 42 exactly."""
    _, _, pin_ids = model
    fa, _ = _cylinder_face_id(model, pin_ids[0])
    fb, _ = _cylinder_face_id(model, pin_ids[1])
    res = _measure(
        model,
        {
            "type": "distance",
            "a": {"partId": pin_ids[0], "kind": "face", "id": fa},
            "b": {"partId": pin_ids[1], "kind": "face", "id": fb},
        },
    )
    assert res["value"] == pytest.approx(42.0, abs=1e-9)


def test_circular_edge_info(model):
    """Pin top/bottom circular edges: length = 2*pi*4, diameter 8."""
    _, _, pin_ids = model
    import math

    found = False
    for eid in (1, 2, 3):
        info = _measure(model, {"type": "edge_info", "ref": {"partId": pin_ids[0], "kind": "edge", "id": eid}})
        if info.get("curve") == "circle":
            assert info["diameter"] == pytest.approx(8.0, abs=1e-9)
            assert info["length"] == pytest.approx(2 * math.pi * 4, abs=1e-9)
            found = True
    assert found


def test_point_to_point(model):
    res = _measure(
        model,
        {
            "type": "distance",
            "a": {"kind": "point", "xyz": [0, 0, 0]},
            "b": {"kind": "point", "xyz": [3, 4, 0]},
        },
    )
    assert res["value"] == pytest.approx(5.0, abs=1e-12)


def test_measure_on_mesh_format_rejected(model):
    client, _, _ = model
    import trimesh

    stl = trimesh.creation.box(extents=(1, 1, 1)).export(file_type="stl")
    r = client.post("/api/models", files={"file": ("box.stl", stl, "x")})
    mid = r.json()["id"]
    r = client.post(f"/api/models/{mid}/measure", json={"type": "distance", "a": {}, "b": {}})
    assert r.status_code == 422


def test_measure_after_cache_hit(model):
    """Cache-hit models must lazily rebuild B-rep handles for measurement."""
    client, _, pin_ids = model
    r = client.post("/api/models", files={"file": ("mini_mold.step", STEP.read_bytes(), "x")})
    meta = r.json()
    assert meta["cached"] is True
    r = client.post(
        f"/api/models/{meta['id']}/measure",
        json={
            "type": "distance",
            "a": {"kind": "point", "xyz": [0, 0, 0]},
            "b": {"partId": pin_ids[0], "kind": "face", "id": 1},
        },
    )
    assert r.status_code == 200


def test_vertex_ref_exact_distance(model):
    """Vertex topology refs must give exact B-rep distance (regression: the
    frontend used to flatten vertex picks to float32 'point' refs, losing
    precision on large-coordinate models). Plate is a 100x60x15 box: the
    max vertex-to-vertex distance is the space diagonal sqrt(100^2+60^2+15^2)."""
    client, mid, _ = model
    # find the plate part id (name == 'plate')
    r = client.get(f"/api/models/{mid}/mesh.bin")
    assert r.status_code == 200
    import json as _json
    import struct as _struct
    (hlen,) = _struct.unpack_from("<I", r.content, 0)
    header = _json.loads(r.content[4 : 4 + hlen])
    plate = next(p for p in header["parts"] if p["name"] == "plate")
    pid = plate["id"]

    # box has 8 vertices (TopTools map 1..8); brute-force the max pair distance
    best = 0.0
    for a in range(1, 9):
        for b in range(a + 1, 9):
            res = _measure(model, {
                "type": "distance",
                "a": {"partId": pid, "kind": "vertex", "id": a},
                "b": {"partId": pid, "kind": "vertex", "id": b},
            })
            best = max(best, res["value"])
    assert best == pytest.approx((100**2 + 60**2 + 15**2) ** 0.5, abs=1e-9)


def test_raw_bytes_released_after_lazy_reparse():
    """Regression: cache-hit entries kept the original upload bytes forever
    after the B-rep was lazily rebuilt, doubling memory for the LRU lifetime."""
    client = TestClient(app)
    data = STEP.read_bytes()
    from app.store import store as _store

    r1 = client.post("/api/models", files={"file": ("mini_mold.step", data, "x")})
    assert r1.status_code == 200
    # drop the live entry so the re-upload takes the DISK-cache-hit path
    # (same-process re-uploads are deduped by the store and never carry raw)
    _store.remove(r1.json()["id"])
    r2 = client.post("/api/models", files={"file": ("mini_mold.step", data, "x")})
    assert r2.status_code == 200
    mid = r2.json()["id"]

    entry = _store.get(mid)
    assert "raw" in entry.extra, "expected a disk-cache-hit entry carrying raw bytes"

    # trigger the lazy reparse via a measurement
    res = client.post(
        f"/api/models/{mid}/measure",
        json={"type": "distance",
              "a": {"kind": "point", "xyz": [0, 0, 0]},
              "b": {"kind": "point", "xyz": [1, 0, 0]}},
    )
    assert res.status_code == 200
    assert "raw" not in entry.extra, "upload bytes must be dropped after reparse"
    assert entry.brep is not None
