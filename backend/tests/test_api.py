import json
import pathlib
import struct

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _upload_box(client, extents=(10, 20, 30)):
    box = trimesh.creation.box(extents=extents)
    stl = box.export(file_type="stl")
    r = client.post("/api/models", files={"file": ("box.stl", stl, "model/stl")})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_and_meta(client):
    meta = _upload_box(client)
    assert meta["format"] == "mesh"
    assert meta["triangleCount"] == 12
    assert meta["bbox"]["min"] == [-5.0, -10.0, -15.0]
    assert meta["bbox"]["max"] == [5.0, 10.0, 15.0]


def _parse_blob(blob):
    (hlen,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + hlen])
    base = 4 + hlen

    def buf(name, dtype):
        d = header["buffers"][name]
        return np.frombuffer(blob, dtype=dtype, count=d["count"], offset=base + d["offset"])

    return header, buf


def test_mesh_binary_protocol(client):
    meta = _upload_box(client)
    r = client.get(f"/api/models/{meta['id']}/mesh.bin")
    assert r.status_code == 200
    header, buf = _parse_blob(r.content)

    assert set(header["buffers"]) == {
        "p0:positions",
        "p0:normals",
        "p0:indices",
        "p0:edges",
        "p0:vertices",
    }
    assert len(header["parts"]) == 1

    positions = buf("p0:positions", np.float32).reshape(-1, 3)
    assert positions.min(axis=0).tolist() == [-5.0, -10.0, -15.0]
    assert positions.max(axis=0).tolist() == [5.0, 10.0, 15.0]

    indices = buf("p0:indices", np.uint32)
    assert indices.max() < len(positions)
    assert len(indices) == meta["triangleCount"] * 3


STEP_ASSEMBLY = pathlib.Path(__file__).parent.parent.parent / "testdata" / "mini_mold.step"


@pytest.mark.skipif(not STEP_ASSEMBLY.exists(), reason="run testdata/make_step_assembly.py first")
def test_step_assembly(client):
    r = client.post(
        "/api/models",
        files={"file": ("mini_mold.step", STEP_ASSEMBLY.read_bytes(), "application/step")},
    )
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["format"] == "brep"
    assert meta["partCount"] == 4
    names = sorted(p["name"] for p in meta["parts"])
    assert names == ["cavity_block", "core_pin", "core_pin", "plate"]
    # colors survived the XCAF round-trip
    pin = next(p for p in meta["parts"] if p["name"] == "core_pin")
    assert pin["color"] is not None and pin["color"][0] > 0.5  # reddish
    # assembly bbox: plate 100x60x15 + pin height 25 on top
    assert meta["bbox"]["max"][0] == pytest.approx(100, abs=1)
    assert meta["bbox"]["max"][2] == pytest.approx(40, abs=1)

    header, buf = _parse_blob(client.get(f"/api/models/{meta['id']}/mesh.bin").content)
    part0 = header["parts"][0]
    assert part0["faceRanges"], "faceRanges must be present for B-rep parts"
    assert part0["edgeRanges"], "edgeRanges must be present for B-rep parts"
    # per-part buffers exist
    for p in header["parts"]:
        for section in ("positions", "normals", "indices", "edges"):
            assert f"p{p['id']}:{section}" in header["buffers"]
    # face ranges tile the index buffer exactly
    idx_count = header["buffers"]["p0:indices"]["count"]
    assert sum(fr["triCount"] for fr in part0["faceRanges"]) * 3 == idx_count


@pytest.mark.skipif(not STEP_ASSEMBLY.exists(), reason="run testdata/make_step_assembly.py first")
def test_step_cache_hit(client):
    data = STEP_ASSEMBLY.read_bytes()
    r1 = client.post("/api/models", files={"file": ("mini_mold.step", data, "application/step")})
    r2 = client.post("/api/models", files={"file": ("mini_mold.step", data, "application/step")})
    assert r2.json()["cached"] is True
    assert r1.json()["bbox"] == r2.json()["bbox"]
    # cached blob is byte-identical
    b1 = client.get(f"/api/models/{r1.json()['id']}/mesh.bin").content
    b2 = client.get(f"/api/models/{r2.json()['id']}/mesh.bin").content
    assert b1 == b2


def test_unsupported_extension(client):
    r = client.post("/api/models", files={"file": ("a.xyz", b"data", "application/octet-stream")})
    assert r.status_code == 415


def test_broken_step(client):
    r = client.post("/api/models", files={"file": ("a.step", b"garbage", "application/step")})
    assert r.status_code == 422


def test_missing_model(client):
    assert client.get("/api/models/nope/mesh.bin").status_code == 404


def test_3mf_roundtrip(client):
    import trimesh

    box = trimesh.creation.box(extents=(10, 20, 30))
    data = trimesh.exchange.export.export_mesh(box, file_obj=None, file_type="3mf")
    r = client.post("/api/models", files={"file": ("box.3mf", data, "model/3mf")})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["format"] == "mesh"
    assert meta["triangleCount"] == 12


def test_store_lru_eviction_and_dedup(client):
    from app.store import ModelStore, ModelEntry

    s = ModelStore(max_entries=3)
    for i in range(5):
        s.add(ModelEntry(model_id=f"m{i}", name=f"n{i}", fmt="mesh", meta={}, extra={"hash": f"h{i}"}))
    assert s.get("m0") is None and s.get("m1") is None  # evicted
    assert s.get("m4") is not None
    assert s.get_by_hash("h0") is None  # hash index cleaned up
    assert s.get_by_hash("h3").model_id == "m3"


def test_upload_dedup_same_content(client):
    meta1 = _upload_box(client)
    meta2 = _upload_box(client)  # identical bytes
    assert meta1["id"] == meta2["id"], "identical content must reuse the entry"
