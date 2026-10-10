"""A distance along the axes ("delta") and a vertex's point (vertex_info),
against known geometry: mini_mold.step.

Geometry (testdata/make_step_assembly.py):
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
    assert r.status_code == 200, r.text
    meta = r.json()
    return client, meta["id"], {p["name"]: p["id"] for p in meta["parts"]}


def _post(model, req):
    client, mid, _ = model
    return client.post(f"/api/models/{mid}/measure", json=req)


def _on(model, part, kind, p):
    """the face, edge or vertex of the part the point lies on"""
    pid = model[2][part]
    hits = []
    for i in range(1, 200):
        ref = {"partId": pid, "kind": kind, "id": i}
        r = _post(model, {"type": "distance", "a": {"kind": "point", "xyz": list(p)}, "b": ref})
        if r.status_code != 200:
            break
        if r.json()["value"] < 1e-9:
            hits.append(ref)
    assert len(hits) == 1, (part, kind, p, hits)
    return hits[0]


def test_points_delta(model):
    r = _post(model, {"type": "distance", "a": {"kind": "point", "xyz": [0, 0, 0]}, "b": {"kind": "point", "xyz": [3, 4, 0]}})
    res = r.json()
    assert res["value"] == pytest.approx(5.0, abs=1e-12)
    assert res["delta"] == pytest.approx([3, 4, 0], abs=1e-12)


def test_delta_runs_from_a_to_b(model):
    """the block's top (z 35) to the plate's top (z 15): straight down"""
    a = _on(model, "cavity_block", "face", (50, 30, 35))
    b = _on(model, "plate", "face", (90, 10, 15))
    res = _post(model, {"type": "distance", "a": a, "b": b, "nearA": [50, 30, 35]}).json()
    assert res["value"] == pytest.approx(20.0, abs=1e-9)
    assert res["delta"] == pytest.approx([0, 0, -20], abs=1e-9)
    assert res["delta"] == pytest.approx([q - p for p, q in zip(res["pointA"], res["pointB"])], abs=1e-12)


def test_vertices_delta(model):
    """the plate's top front right corner to the block's: 30 back in X, 15 in Y, 20 up"""
    a = _on(model, "plate", "vertex", (100, 0, 15))
    b = _on(model, "cavity_block", "vertex", (70, 15, 35))
    res = _post(model, {"type": "distance", "a": a, "b": b}).json()
    assert res["delta"] == pytest.approx([-30, 15, 20], abs=1e-9)
    assert res["value"] == pytest.approx((30**2 + 15**2 + 20**2) ** 0.5, abs=1e-9)


def test_vertex_point(model):
    ref = _on(model, "cavity_block", "vertex", (70, 15, 35))
    res = _post(model, {"type": "vertex_info", "ref": ref}).json()
    assert res == {"type": "vertex", "point": pytest.approx([70, 15, 35], abs=1e-12)}


def test_vertex_info_of_a_face_is_refused(model):
    ref = _on(model, "plate", "face", (90, 10, 15))
    assert _post(model, {"type": "vertex_info", "ref": ref}).status_code == 422
