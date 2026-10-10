"""The size of a curved face or edge, told by its kind (measure.face_info,
measure.edge_info), against known geometry: curved_part.step.

Geometry (testdata/make_step_assembly.py, make_curved_part):
  body: block 60 x 40 x 10 from the origin, its 4 vertical edges rounded R5;
        a through hole ⌀6 at (12, 20); a boss at (38, 20) on the top, radius 6
        at its foot, 8 high, 2° draft, its foot rounded R1; a dimple: a sphere
        of radius 4 centred at (52, 30, 12)
  nurbs_pin: a cylinder of radius 3, 10 high at (75, 20), its top edge rounded
        R1, all turned into B-splines

Each face or edge is found by a point known to lie on it (the B-rep distance
to it is 0), not by its number.
"""
import math
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

STEP = pathlib.Path(__file__).parent.parent.parent / "testdata" / "curved_part.step"

pytestmark = pytest.mark.skipif(not STEP.exists(), reason="run testdata/make_step_assembly.py first")

DEG = math.pi / 180
C45 = math.cos(45 * DEG)
# the boss's rounding: the tube's centre is 1 above the top (z 11) and 1 off the
# drafted side, whose radius is 6 at the top and shrinks by tan 2° a mm upwards
BOSS_TUBE = 6 - math.tan(2 * DEG) + 1 / math.cos(2 * DEG)

POINTS = {
    # body
    "corner": ("body", "face", (5 - 5 * C45, 5 - 5 * C45, 5)),  # round the corner at (5, 5)
    "hole": ("body", "face", (12, 23, 5)),  # a quarter turn from the seam (x 15)
    "boss_round": ("body", "face", (38 + BOSS_TUBE - C45, 20, 11 - C45)),
    "dimple": ("body", "face", (52, 30, 8)),  # its bottom
    "boss_side": ("body", "face", (38 + 6 - 4 * math.tan(2 * DEG), 20, 14)),  # halfway up
    "top": ("body", "face", (30, 35, 10)),
    "bottom": ("body", "face", (30, 35, 0)),
    "corner_arc": ("body", "edge", (5 - 5 * C45, 5 - 5 * C45, 10)),  # the corner's top edge
    "hole_rim": ("body", "edge", (12, 23, 10)),  # off the seam's end (a vertex)
    # nurbs_pin
    "pin_side": ("nurbs_pin", "face", (75, 23, 5)),
    "pin_round": ("nurbs_pin", "face", (75 + 2 + C45, 20, 9 + C45)),  # the tube's centre: radius 2 at z 9
    "pin_rim": ("nurbs_pin", "edge", (75, 23, 0)),  # the bottom edge, off the seam's end
}


@pytest.fixture(scope="module")
def model():
    client = TestClient(app)
    r = client.post("/api/models", files={"file": ("curved_part.step", STEP.read_bytes(), "x")})
    assert r.status_code == 200, r.text
    meta = r.json()
    parts = {p["name"]: p["id"] for p in meta["parts"]}
    assert set(parts) == {"body", "nurbs_pin"}, parts
    return client, meta["id"], parts


def _post(model, req):
    client, mid, _ = model
    return client.post(f"/api/models/{mid}/measure", json=req)


def _ref(model, name):
    """the face or edge the named point lies on"""
    part, kind, p = POINTS[name]
    pid = model[2][part]
    hits = []
    for i in range(1, 200):
        ref = {"partId": pid, "kind": kind, "id": i}
        r = _post(model, {"type": "distance", "a": {"kind": "point", "xyz": list(p)}, "b": ref})
        if r.status_code != 200:
            break
        if r.json()["value"] < 1e-6:
            hits.append(ref)
    assert len(hits) == 1, (name, hits)
    return hits[0]


def _info(model, name, near=None):
    _, kind, p = POINTS[name]
    req = {"type": f"{kind}_info", "ref": _ref(model, name)}
    if near is not None:
        req["near"] = list(near)
    r = _post(model, req)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_whole_cylinder_is_a_hole(model):
    info = _info(model, "hole")
    assert info["surface"] == "cylinder" and info["full"] is True
    assert info["diameter"] == pytest.approx(6.0, abs=1e-9)
    assert "recognized" not in info


def test_a_part_of_a_cylinder_is_a_rounding(model):
    info = _info(model, "corner")
    assert info["surface"] == "cylinder" and info["full"] is False
    assert info["radius"] == pytest.approx(5.0, abs=1e-9)


def test_a_torus_tells_its_small_radius(model):
    info = _info(model, "boss_round")
    assert info["surface"] == "torus"
    assert info["radius"] == pytest.approx(1.0, abs=1e-9)
    assert info["majorRadius"] == pytest.approx(BOSS_TUBE, abs=1e-6)


def test_a_sphere(model):
    info = _info(model, "dimple")
    assert info["surface"] == "sphere" and info["radius"] == pytest.approx(4.0, abs=1e-9)
    assert info["center"] == pytest.approx([52, 30, 12], abs=1e-9)


def test_a_cone_tells_its_half_angle(model):
    info = _info(model, "boss_side")
    assert info["surface"] == "cone"
    assert info["angle"] == pytest.approx(2.0, abs=1e-9)


def test_a_cone_narrowing_along_its_axis(monkeypatch):
    """OCCT keeps a cone that narrows along its axis with a negative half angle
    (one made in memory; a STEP file always gives it positive): the draft is
    the same size either way."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
    from OCP.GeomAbs import GeomAbs_Cone
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from app import measure

    boss = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 6, 6 - 8 * math.tan(2 * DEG), 8).Shape()
    ex = TopExp_Explorer(boss, TopAbs_FACE)
    side = None
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        if BRepAdaptor_Surface(f).GetType() == GeomAbs_Cone:
            side = f
        ex.Next()
    assert side is not None and BRepAdaptor_Surface(side).Cone().SemiAngle() < 0, "the case this is about"
    monkeypatch.setattr(measure, "_resolve", lambda ref, meshes: side)
    info = measure.face_info({}, [])
    assert info["surface"] == "cone" and info["angle"] == pytest.approx(2.0, abs=1e-9)


def test_a_plane_has_no_radius(model):
    info = _info(model, "top", near=POINTS["top"][2])
    assert info["surface"] == "plane"
    assert not {"radius", "localRadius"} & set(info), info


def test_circle_edges_whole_and_part(model):
    rim = _info(model, "hole_rim")
    assert rim["curve"] == "circle" and rim["full"] is True and rim["diameter"] == pytest.approx(6.0, abs=1e-9)
    arc = _info(model, "corner_arc")
    assert arc["curve"] == "circle" and arc["full"] is False and arc["radius"] == pytest.approx(5.0, abs=1e-9)
    assert arc["length"] == pytest.approx(math.pi / 2 * 5, abs=1e-9)


def test_a_bspline_cylinder_is_recognised(model):
    info = _info(model, "pin_side")
    assert info["recognized"] is True and info["surface"] == "cylinder" and info["full"] is True
    assert info["diameter"] == pytest.approx(6.0, abs=1e-6)


def test_a_bspline_circle_is_recognised(model):
    info = _info(model, "pin_rim")
    assert info["recognized"] is True and info["curve"] == "circle" and info["full"] is True
    assert info["radius"] == pytest.approx(3.0, abs=1e-6)


def test_the_radius_of_curvature_at_the_click(model):
    """a rounding no recogniser knows (a torus as B-splines): its radius at the click"""
    near = POINTS["pin_round"][2]
    info = _info(model, "pin_round", near=near)
    assert info["surface"] == "bsplinesurface" and "recognized" not in info
    assert info["localRadius"] == pytest.approx(1.0, abs=1e-6)
    # "at" is the true surface's point at the click: 1 from the tube's centre circle
    x, y, z = info["at"]
    assert math.hypot(math.hypot(x - 75, y - 20) - 2, z - 9) == pytest.approx(1.0, abs=1e-6)
    assert math.dist(info["at"], near) < 1e-3
    # the same click on another spot of the rounding: the same radius
    other = (75, 20 - 2 - C45, 9 + C45)
    r = _post(model, {"type": "face_info", "ref": _ref(model, "pin_round"), "near": list(other)})
    assert r.json()["localRadius"] == pytest.approx(1.0, abs=1e-6)


def test_no_radius_of_curvature_without_a_click(model):
    info = _info(model, "pin_round")
    assert "localRadius" not in info


def test_a_straight_bspline_edge_has_no_radius(model):
    """the pin's seam: a straight line written as a B-spline"""
    pid = model[2]["nurbs_pin"]
    seen = 0
    for i in range(1, 50):
        r = _post(model, {"type": "edge_info", "ref": {"partId": pid, "kind": "edge", "id": i}, "near": [78, 20, 5]})
        if r.status_code != 200:
            break
        info = r.json()
        if info["curve"] == "bsplinecurve":
            seen += 1
            assert "localRadius" not in info, info
    assert seen >= 1


@pytest.mark.parametrize("near", [[1, 2], [1, "x", 3], [1, 2, float("nan")], "abc", {"x": 1}])
def test_a_bad_click_is_refused(model, near):
    ref = _ref(model, "hole")
    # NaN cannot travel as JSON: send it as the literal Python's json writes
    client, mid, _ = model
    import json

    r = client.post(
        f"/api/models/{mid}/measure",
        content=json.dumps({"type": "face_info", "ref": ref, "near": near}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422, r.text


# the body's outline (top and bottom): 60 x 40 with its 4 vertical edges rounded R5
OUTLINE = 2 * (60 - 10) + 2 * (40 - 10) + 2 * math.pi * 5


def test_a_face_tells_its_outer_loop_and_its_holes(model):
    """the top: the rounded outline; inside it the boss's foot (its rounding
    meets the top at the tube's radius), the dimple (a sphere of radius 4 2 mm
    above: a circle of radius sqrt(12)) and the through hole (radius 3)"""
    info = _info(model, "top")
    assert info["perimeter"] == pytest.approx(OUTLINE, abs=1e-6)
    want = sorted([2 * math.pi * BOSS_TUBE, 2 * math.pi * math.sqrt(12), 2 * math.pi * 3], reverse=True)
    assert info["holes"] == pytest.approx(want, abs=1e-6), info["holes"]
    bottom = _info(model, "bottom")
    assert bottom["perimeter"] == pytest.approx(OUTLINE, abs=1e-6)
    assert bottom["holes"] == pytest.approx([2 * math.pi * 3], abs=1e-6), bottom["holes"]
    # the area: the outline's, less the holes cut in it (the bottom: only the through hole)
    assert bottom["area"] == pytest.approx(60 * 40 - (4 - math.pi) * 25 - math.pi * 9, abs=1e-6)


def test_a_cylinder_face_loop_leaves_out_its_seam(model):
    """the through hole's wall: its loop is the two circles; the seam it is cut along is not counted"""
    info = _info(model, "hole")
    assert info["perimeter"] == pytest.approx(2 * 2 * math.pi * 3, abs=1e-6)
    assert info["holes"] == []
