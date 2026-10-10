"""The distance between centres and the largest distance (measure.distance
with mode "centre" / "max"), against known geometry.

mini_mold.step (testdata/make_step_assembly.py): the plate 0..100 x 0..60 x
0..15; two core pins, cylinders of radius 4 standing on the plate at (25, 30)
and (75, 30), z 15..40.
curved_part.step: the body's through hole of radius 3 at (12, 20); the boss, a
cone, at (38, 20); the dimple, a sphere of radius 4 centred at (52, 30, 12); the
nurbs_pin, a B-spline cylinder of radius 3 at (75, 20).
A pair of crossed cylinders is written here (their axes along Z and along X).

Each face, edge or vertex is found by a point known to lie on it (the B-rep
distance to it is 0), not by its number.
"""
import math
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

TESTDATA = pathlib.Path(__file__).parent.parent.parent / "testdata"
MOLD = TESTDATA / "mini_mold.step"
CURVED = TESTDATA / "curved_part.step"

pytestmark = pytest.mark.skipif(
    not (MOLD.exists() and CURVED.exists()), reason="run testdata/make_step_assembly.py first"
)


def _open(data: bytes, name: str):
    client = TestClient(app)
    r = client.post("/api/models", files={"file": (name, data, "x")})
    assert r.status_code == 200, r.text
    meta = r.json()
    return client, meta["id"], [p["id"] for p in meta["parts"]]


@pytest.fixture(scope="module")
def mold():
    return _open(MOLD.read_bytes(), "mini_mold.step")


@pytest.fixture(scope="module")
def curved():
    return _open(CURVED.read_bytes(), "curved_part.step")


def _post(model, req):
    client, mid, _ = model
    return client.post(f"/api/models/{mid}/measure", json=req)


def _ref(model, kind, p):
    """the one face, edge or vertex of that kind the point lies on (any part)"""
    hits = []
    for pid in model[2]:
        for i in range(1, 300):
            ref = {"partId": pid, "kind": kind, "id": i}
            r = _post(model, {"type": "distance", "a": {"kind": "point", "xyz": list(p)}, "b": ref})
            if r.status_code != 200:
                break
            if r.json()["value"] < 1e-6:
                hits.append(ref)
    assert len(hits) == 1, (kind, p, hits)
    return hits[0]


def _measure(model, a, b, mode, near_a=None):
    req = {"type": "distance", "a": a, "b": b, "mode": mode}
    if near_a is not None:
        req["nearA"] = list(near_a)
    r = _post(model, req)
    assert r.status_code == 200, r.text
    return r.json()


def _close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------- centres


def test_two_pins_centres(mold):
    """parallel axes: the pins' sides are 50 apart, across at the click; a
    rim's centre and the other pin's axis, and two rims' centres"""
    side1 = _ref(mold, "face", (21, 30, 25))
    side2 = _ref(mold, "face", (79, 30, 25))
    r = _measure(mold, side1, side2, "centre", near_a=(21, 30, 25))
    assert r["mode"] == "centre" and r["value"] == pytest.approx(50, abs=1e-9), r
    assert _close(r["pointA"], (25, 30, 25)) and _close(r["pointB"], (75, 30, 25)), r
    assert _close(r["delta"], (50, 0, 0)), r
    top1 = _ref(mold, "edge", (25, 34, 40))
    r = _measure(mold, top1, side2, "centre")
    assert r["value"] == pytest.approx(50, abs=1e-9) and _close(r["pointB"], (75, 30, 40)), r
    bottom2 = _ref(mold, "edge", (75, 34, 15))
    r = _measure(mold, top1, bottom2, "centre")
    assert r["value"] == pytest.approx(math.hypot(50, 25), abs=1e-9), r
    # the shortest as before: between the sides, 50 less the two radii
    r = _measure(mold, side1, side2, "min")
    assert r["value"] == pytest.approx(42, abs=1e-6), r


def test_curved_centres(curved):
    """the hole and the boss's cone (parallel axes), the dimple's sphere and the
    hole's axis (a point and an axis), the B-spline pin (recognised) and the hole"""
    hole = _ref(curved, "face", (12, 23, 5))
    boss = _ref(curved, "face", (38 + 6 - 4 * math.tan(math.radians(2)), 20, 14))
    dimple = _ref(curved, "face", (52, 30, 8))
    pin = _ref(curved, "face", (75, 23, 5))
    assert _measure(curved, hole, boss, "centre")["value"] == pytest.approx(26, abs=1e-9)
    r = _measure(curved, dimple, hole, "centre")
    assert r["value"] == pytest.approx(math.hypot(40, 10), abs=1e-9) and _close(r["pointB"], (12, 20, 12)), r
    assert _measure(curved, pin, hole, "centre")["value"] == pytest.approx(63, abs=1e-3)


def test_no_centre_is_said(mold):
    top = _ref(mold, "face", (8, 8, 15))
    side2 = _ref(mold, "face", (79, 30, 25))
    edge = _ref(mold, "edge", (50, 0, 15))
    r = _measure(mold, top, side2, "centre")
    assert r == {"type": "distance", "mode": "centre", "unavailable": "1 点目: 平面に中心はない"}, r
    r = _measure(mold, side2, edge, "centre")
    assert r["unavailable"] == "2 点目: 直線の稜線に中心はない" and "value" not in r, r


def test_crossed_axes_are_said(tmp_path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder

    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    b.Add(comp, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2, 10).Shape())
    b.Add(comp, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 20, 20), gp_Dir(1, 0, 0)), 2, 10).Shape())
    w = STEPControl_Writer()
    w.Transfer(comp, STEPControl_AsIs)
    path = tmp_path / "crossed.step"
    assert w.Write(str(path)) == IFSelect_RetDone
    model = _open(path.read_bytes(), "crossed.step")
    up = _ref(model, "face", (2, 0, 5))
    across = _ref(model, "face", (5, 22, 20))
    r = _measure(model, up, across, "centre")
    assert r["unavailable"] == "軸が平行でない（90.0°）", r


# ---------------------------------------------------------------- largest


def test_box_diagonal_largest(mold):
    """two edges of the plate along X, the top front one and the bottom back
    one: farthest at opposite ends, the plate's diagonal; a corner and an edge"""
    diag = math.sqrt(100**2 + 60**2 + 15**2)
    front_top = _ref(mold, "edge", (50, 0, 15))
    back_bottom = _ref(mold, "edge", (50, 60, 0))
    r = _measure(mold, front_top, back_bottom, "max")
    assert r["mode"] == "max" and r["value"] == pytest.approx(diag, abs=1e-9), r
    ends = {tuple(round(v, 6) for v in r["pointA"]), tuple(round(v, 6) for v in r["pointB"])}
    assert ends in ({(0, 0, 15), (100, 60, 0)}, {(100, 0, 15), (0, 60, 0)}), r
    corner = _ref(mold, "vertex", (0, 0, 0))
    back_top = _ref(mold, "edge", (50, 60, 15))
    r = _measure(mold, corner, back_top, "max")
    assert r["value"] == pytest.approx(diag, abs=1e-9) and _close(r["pointB"], (100, 60, 15)), r
    # the shortest of the same pair: the edge's nearest point
    assert _measure(mold, corner, back_top, "min")["value"] == pytest.approx(math.hypot(60, 15), abs=1e-6)


def test_two_rims_largest(mold):
    """the top rim of one pin and the bottom rim of the other: farthest at the
    far sides, 50 + 4 + 4 across and 25 up"""
    top1 = _ref(mold, "edge", (25, 34, 40))
    bottom2 = _ref(mold, "edge", (75, 34, 15))
    r = _measure(mold, top1, bottom2, "max")
    assert r["value"] == pytest.approx(math.hypot(58, 25), abs=1e-9), r
    assert _close(r["pointA"], (21, 30, 40)) and _close(r["pointB"], (79, 30, 15)), r


def test_a_face_has_no_largest(mold):
    top = _ref(mold, "face", (8, 8, 15))
    edge = _ref(mold, "edge", (50, 0, 15))
    r = _measure(mold, edge, top, "max")
    assert r == {"type": "distance", "mode": "max", "unavailable": "2 点目: 面の最大の距離は出さない（頂点か稜線を選ぶ）"}, r


def test_a_mode_must_be_known(mold):
    edge = _ref(mold, "edge", (50, 0, 15))
    r = _post(mold, {"type": "distance", "a": edge, "b": edge, "mode": "far"})
    assert r.status_code == 422, r.text
