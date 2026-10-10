"""What a coordinate system is taken from (#59 P1 7): a straight edge's ends
and direction, a plane's normal out of the solid.

Against mini_mold.step's make (testdata/make_step_assembly.py): the plate
0..100 x 0..60 x 0..15. Its faces' normals point out of it (the top +Z, the
bottom -Z, the front -Y, the right +X); an edge along X runs between x 0 and
100 and its direction is the way from its start to its end. The faces of a
box come with their planes' own normals both ways (OCCT reverses some faces
to turn them out): each still says the normal out of the solid.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

MOLD = pathlib.Path(__file__).parent.parent.parent / "testdata" / "mini_mold.step"

pytestmark = pytest.mark.skipif(not MOLD.exists(), reason="run testdata/make_step_assembly.py first")


def _open(data: bytes, name: str):
    client = TestClient(app)
    r = client.post("/api/models", files={"file": (name, data, "x")})
    assert r.status_code == 200, r.text
    meta = r.json()
    return client, meta["id"], [p["id"] for p in meta["parts"]]


def _post(model, req):
    client, mid, _ = model
    r = client.post(f"/api/models/{mid}/measure", json=req)
    assert r.status_code == 200, r.text
    return r.json()


def _ref(model, kind, p):
    """the one face or edge of that kind the point lies on (any part)"""
    client, mid, parts = model
    hits = []
    for pid in parts:
        for i in range(1, 300):
            ref = {"partId": pid, "kind": kind, "id": i}
            r = client.post(f"/api/models/{mid}/measure", json={"type": "distance", "a": {"kind": "point", "xyz": list(p)}, "b": ref})
            if r.status_code != 200:
                break
            if r.json()["value"] < 1e-6:
                hits.append(ref)
    assert len(hits) == 1, (kind, p, hits)
    return hits[0]


@pytest.fixture(scope="module")
def mold():
    return _open(MOLD.read_bytes(), "mini_mold.step")


@pytest.mark.parametrize(
    "point, normal",
    [((90, 50, 15), (0, 0, 1)), ((50, 30, 0), (0, 0, -1)), ((80, 0, 7), (0, -1, 0)), ((100, 30, 7), (1, 0, 0)), ((0, 30, 7), (-1, 0, 0))],
)
def test_a_planes_normal_points_out(mold, point, normal):
    info = _post(mold, {"type": "face_info", "ref": _ref(mold, "face", point)})
    assert info["surface"] == "plane" and info["normal"] == pytest.approx(normal, abs=1e-12), info


def test_a_straight_edge_says_its_ends_and_direction(mold):
    info = _post(mold, {"type": "edge_info", "ref": _ref(mold, "edge", (50, 0, 15))})
    assert info["curve"] == "line" and info["length"] == pytest.approx(100), info
    ends = sorted([tuple(round(v, 9) for v in info["start"]), tuple(round(v, 9) for v in info["end"])])
    assert ends == [(0, 0, 15), (100, 0, 15)], info
    run = [e - s for s, e in zip(info["start"], info["end"])]
    assert [r / 100 for r in run] == pytest.approx(info["direction"], abs=1e-12), info
    assert abs(info["direction"][0]) == pytest.approx(1) and "localRadius" not in info, info

