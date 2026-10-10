"""A whole part as a measured entity (ref kind "part", the 選択 部品): the
distance between two parts (a clearance), against mini_mold.step's make
(testdata/make_step_assembly.py): the plate 0..100 x 0..60 x 0..15, a core
pin of radius 4 standing on it at (25, 30), z 15..40, the cavity block
30..70 x 15..45 x 15..35 (1 from the pin's side), also on the plate.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

MOLD = pathlib.Path(__file__).parent.parent.parent / "testdata" / "mini_mold.step"

pytestmark = pytest.mark.skipif(not MOLD.exists(), reason="run testdata/make_step_assembly.py first")


@pytest.fixture(scope="module")
def mold():
    client = TestClient(app)
    r = client.post("/api/models", files={"file": ("mini_mold.step", MOLD.read_bytes(), "x")})
    assert r.status_code == 200, r.text
    meta = r.json()
    return client, meta["id"], [p["id"] for p in meta["parts"]]


def _post(mold, req):
    client, mid, _ = mold
    r = client.post(f"/api/models/{mid}/measure", json=req)
    assert r.status_code == 200, r.text
    return r.json()


def _part(mold, p):
    """the one part the point lies in or on"""
    hits = [
        pid
        for pid in mold[2]
        if _post(mold, {"type": "distance", "a": {"kind": "point", "xyz": list(p)}, "b": {"partId": pid, "kind": "part", "id": pid}})["value"] < 1e-6
    ]
    assert len(hits) == 1, (p, hits)
    return {"partId": hits[0], "kind": "part", "id": hits[0]}


def test_clearance_between_parts(mold):
    pin = _part(mold, (25, 30, 40))  # the first pin's top
    block = _part(mold, (50, 30, 35))  # the block's top
    plate = _part(mold, (50, 30, 0))  # the plate's bottom
    r = _post(mold, {"type": "distance", "a": pin, "b": block})
    assert r["value"] == pytest.approx(1.0, abs=1e-6), r
    assert abs(r["pointA"][0] - 29) < 1e-6 and abs(r["pointB"][0] - 30) < 1e-6, r
    assert _post(mold, {"type": "distance", "a": pin, "b": plate})["value"] == pytest.approx(0, abs=1e-6)


def test_a_part_has_no_centre_nor_largest(mold):
    pin = _part(mold, (25, 30, 40))
    block = _part(mold, (50, 30, 35))
    r = _post(mold, {"type": "distance", "a": pin, "b": block, "mode": "centre"})
    assert r == {"type": "distance", "mode": "centre", "unavailable": "1 点目: 部品全体に中心はない"}, r
    r = _post(mold, {"type": "distance", "a": pin, "b": block, "mode": "max"})
    assert r["unavailable"] == "1 点目: 部品全体の最大の距離は出さない（頂点か稜線を選ぶ）", r
