import json
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


def test_mesh_binary_protocol(client):
    meta = _upload_box(client)
    r = client.get(f"/api/models/{meta['id']}/mesh.bin")
    assert r.status_code == 200
    blob = r.content

    (hlen,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + hlen])
    bufs = header["buffers"]
    assert set(bufs) == {"positions", "normals", "indices"}

    base = 4 + hlen
    pos_desc = bufs["positions"]
    positions = np.frombuffer(
        blob, dtype=np.float32, count=pos_desc["count"], offset=base + pos_desc["offset"]
    ).reshape(-1, 3)
    assert positions.min(axis=0).tolist() == [-5.0, -10.0, -15.0]
    assert positions.max(axis=0).tolist() == [5.0, 10.0, 15.0]

    idx_desc = bufs["indices"]
    indices = np.frombuffer(
        blob, dtype=np.uint32, count=idx_desc["count"], offset=base + idx_desc["offset"]
    )
    assert indices.max() < len(positions)
    assert len(indices) == meta["triangleCount"] * 3


def test_unsupported_extension(client):
    r = client.post("/api/models", files={"file": ("a.xyz", b"data", "application/octet-stream")})
    assert r.status_code == 415


def test_brep_not_implemented_yet(client):
    r = client.post("/api/models", files={"file": ("a.step", b"ISO-10303-21;", "application/step")})
    assert r.status_code == 501


def test_missing_model(client):
    assert client.get("/api/models/nope/mesh.bin").status_code == 404
