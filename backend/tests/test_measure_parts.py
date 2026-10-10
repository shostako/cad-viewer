"""A whole part as a measured entity (ref kind "part", the 選択 部品): the
distance between two parts (a clearance), against mini_mold.step's make
(testdata/make_step_assembly.py): the plate 0..100 x 0..60 x 0..15, a core
pin of radius 4 standing on it at (25, 30), z 15..40, the cavity block
30..70 x 15..45 x 15..35 (1 from the pin's side), also on the plate.

A part has no centre and no largest distance whatever its shape is: a part
that is one cylindrical face, or one circle, is still the whole part (a file
written in the test: those alone, beside a box).
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
    client, mid = mold[0], mold[1]
    r = client.post(f"/api/models/{mid}/measure", json=req)
    assert r.status_code == 200, r.text
    return r.json()


def _part(mold, p):
    """the one part the point lies in or on"""
    hits = [
        pid
        for pid in mold[2]
        if _post(mold, {"type": "distance", "a": {"kind": "point", "xyz": list(p)}, "b": {"partId": pid, "kind": "part", "id": 0}})["value"] < 1e-6
    ]
    assert len(hits) == 1, (p, hits)
    return {"partId": hits[0], "kind": "part", "id": 0}  # the id of a part pick (picking.ts)


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


def test_a_part_of_one_face_or_one_edge_is_still_a_part(tmp_path):
    """A part that is a single cylindrical face (an axis, as a face) or a single
    circle (a centre point, as an edge; or the farthest of its points): taken as
    the part, it has neither. IGES, which keeps a loose face and a loose curve
    as parts of their own (STEP gives them back as a shell and a compound)."""
    import math

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Cylinder, gp_Dir, gp_Pnt
    from OCP.IGESControl import IGESControl_Writer

    w = IGESControl_Writer("MM", 0)
    tube = gp_Cylinder(gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 5)
    w.AddShape(BRepBuilderAPI_MakeFace(tube, 0, 2 * math.pi, 0, 10).Face())  # the side of a tube, open
    w.AddShape(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(20, 0, 0), gp_Dir(0, 0, 1)), 3)).Edge())
    w.ComputeModel()
    path = tmp_path / "loose.igs"
    assert w.Write(str(path))
    client = TestClient(app)
    r = client.post("/api/models", files={"file": ("loose.igs", path.read_bytes(), "x")})
    assert r.status_code == 200, r.text
    meta = r.json()
    model = (client, meta["id"], [p["id"] for p in meta["parts"]])
    tube_part = _part(model, (5, 0, 5))
    ring_part = _part(model, (23, 0, 0))
    # the parts themselves are there: the shortest between them (from the tube's
    # side at x 5 to the ring at x 17)
    assert _post(model, {"type": "distance", "a": tube_part, "b": ring_part})["value"] == pytest.approx(12, abs=1e-6)
    r = _post(model, {"type": "distance", "a": tube_part, "b": ring_part, "mode": "centre"})
    assert r == {"type": "distance", "mode": "centre", "unavailable": "1 点目: 部品全体に中心はない"}, r
    r = _post(model, {"type": "distance", "a": ring_part, "b": tube_part, "mode": "centre"})
    assert r["unavailable"] == "1 点目: 部品全体に中心はない", r
    corner = {"kind": "point", "xyz": [40, 0, 0]}
    r = _post(model, {"type": "distance", "a": corner, "b": ring_part, "mode": "max"})
    assert r == {"type": "distance", "mode": "max", "unavailable": "2 点目: 部品全体の最大の距離は出さない（頂点か稜線を選ぶ）"}, r
