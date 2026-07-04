"""Thickness tests against known geometry."""
import json
import struct

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from app.main import app
from app.thickness import vertex_thickness


def test_plate_thickness_direct():
    """10x10x2 box: flat-shaded (per-face normals) vertices measure exactly 2 / 10."""
    box = trimesh.creation.box(extents=(10, 10, 2))
    # facet-shaded copy: duplicate vertices per face so normals are face normals
    box = box.copy()
    box.unmerge_vertices()
    t = vertex_thickness(
        np.asarray(box.vertices, dtype=np.float32),
        np.asarray(box.vertex_normals, dtype=np.float32),
        np.asarray(box.faces, dtype=np.uint32),
    )
    finite = t[np.isfinite(t)]
    assert len(finite) == len(t)
    # every ray crosses either the 2mm or the 10mm dimension
    assert set(np.round(np.unique(finite), 3)) <= {2.0, 10.0}
    assert (np.round(finite, 3) == 2.0).sum() > 0


def test_thickness_endpoint():
    client = TestClient(app)
    box = trimesh.creation.box(extents=(10, 10, 2))
    stl = box.export(file_type="stl")
    r = client.post("/api/models", files={"file": ("plate.stl", stl, "x")})
    mid = r.json()["id"]

    r = client.get(f"/api/models/{mid}/thickness.bin")
    assert r.status_code == 200
    blob = r.content
    (hlen,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + hlen])
    d = header["buffers"]["p0:thickness"]
    t = np.frombuffer(blob, dtype=np.float32, count=d["count"], offset=4 + hlen + d["offset"])
    assert d["count"] == r0_vertex_count(client, mid)
    vals = set(np.round(t[t > 0], 3))
    assert vals <= {2.0, 10.0}


def r0_vertex_count(client, mid):
    meta = [m for m in client.get("/api/models").json() if m["id"] == mid][0]
    return meta["vertexCount"]
