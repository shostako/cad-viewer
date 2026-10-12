"""Measurement API tests against known-truth geometry (mini_mold.step).

Geometry (see testdata/make_step_assembly.py):
  plate: box 100x60x15 at origin
  core_pin: cylinder r=4 h=25, at (25,30,15) and (75,30,15)
  cavity_block: box 40x30x20 at (30,15,15)
"""
import math
import pathlib
from collections import OrderedDict

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


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    """An empty model store and an empty disk cache for one test.

    The store is process-wide: without this, an earlier upload of the same file
    makes the next upload a store dedup hit, and the disk-cache-hit path these
    tests exist for is never taken. The module-scoped `model` entry comes back
    after the test (monkeypatch restores the store's internals).
    """
    from app import cache
    from app.store import store

    monkeypatch.setattr(store, "_models", OrderedDict())
    monkeypatch.setattr(store, "_by_hash", {})
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    return store


def _upload_via_disk_cache(client, store):
    """Upload mini_mold.step so that it takes the DISK-cache-hit path.

    The first upload parses and fills the disk cache. Dropping the live entry
    makes the re-upload miss the store dedup and hit the disk cache instead.
    """
    data = STEP.read_bytes()
    r1 = client.post("/api/models", files={"file": ("mini_mold.step", data, "x")})
    assert r1.status_code == 200
    assert r1.json()["cached"] is False, "first upload must parse, not hit a cache"
    store.remove(r1.json()["id"])
    r2 = client.post("/api/models", files={"file": ("mini_mold.step", data, "x")})
    assert r2.status_code == 200
    meta = r2.json()
    assert meta["cached"] is True
    entry = store.get(meta["id"])
    assert "raw" in entry.extra, "expected a disk-cache-hit entry carrying raw bytes"
    assert entry.brep is None, "a disk-cache hit has no live B-rep until the first measure"
    return meta, entry


def test_measure_after_cache_hit(model, fresh_state):
    """Cache-hit models must lazily rebuild B-rep handles for measurement."""
    client, _, pin_ids = model
    meta, entry = _upload_via_disk_cache(client, fresh_state)
    r = client.post(
        f"/api/models/{meta['id']}/measure",
        json={
            "type": "distance",
            "a": {"kind": "point", "xyz": [0, 0, 0]},
            "b": {"partId": pin_ids[0], "kind": "face", "id": 1},
        },
    )
    assert r.status_code == 200
    assert entry.brep is not None, "the measure must have rebuilt the B-rep"


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


def test_raw_bytes_released_after_lazy_reparse(fresh_state):
    """Regression: cache-hit entries kept the original upload bytes forever
    after the B-rep was lazily rebuilt, doubling memory for the LRU lifetime."""
    client = TestClient(app)
    meta, entry = _upload_via_disk_cache(client, fresh_state)
    mid = meta["id"]

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


# ---- the dimension line where the user clicked (nearA / nearB) ----------------


@pytest.fixture(scope="module")
def part_ids(model):
    """part name -> ids (the same file again: the store answers with the same model)"""
    client, _, _ = model
    r = client.post("/api/models", files={"file": ("mini_mold.step", STEP.read_bytes(), "x")})
    out: dict[str, list[int]] = {}
    for p in r.json()["parts"]:
        out.setdefault(p["name"], []).append(p["id"])
    return out


def _planar_face(model, part_id, axis, probe):
    """the planar face of a part square to `axis` (0, 1, 2), nearest the probe point"""
    best = None
    for fid in range(1, 7):
        ref = {"partId": part_id, "kind": "face", "id": fid}
        info = _measure(model, {"type": "face_info", "ref": ref})
        if info.get("surface") != "plane" or abs(abs(info["normal"][axis]) - 1) > 1e-9:
            continue
        d = _measure(model, {"type": "distance", "a": ref, "b": {"kind": "point", "xyz": probe}})["value"]
        if best is None or d < best[1]:
            best = (fid, d)
    assert best, ("no planar face", part_id, axis)
    return best[0]


def _tops(model, part_ids):
    plate, block = part_ids["plate"][0], part_ids["cavity_block"][0]
    a = {"partId": plate, "kind": "face", "id": _planar_face(model, plate, 2, [50, 30, 100])}
    b = {"partId": block, "kind": "face", "id": _planar_face(model, block, 2, [50, 30, 100])}
    return a, b


def test_faces_lists_every_face(model, part_ids):
    """measure "faces" (版の比較's 面の変化): every face of every part, in id
    order, each as face_info tells it; a face's centroid is on it (the plate's
    top at z 15, its area as face_info's)"""
    res = _measure(model, {"type": "faces"})
    assert res["type"] == "faces"
    by_part = {p["partId"]: p["faces"] for p in res["parts"]}
    plate = part_ids["plate"][0]
    faces = by_part[plate]
    assert [f["id"] for f in faces] == list(range(1, len(faces) + 1))
    top, _ = _tops(model, part_ids)
    one = _measure(model, {"type": "face_info", "ref": top})
    listed = faces[top["id"] - 1]
    assert listed["surface"] == "plane" and listed["area"] == pytest.approx(one["area"], rel=1e-12)
    assert listed["centroid"][2] == pytest.approx(15, abs=1e-9) and listed["centroid"] == pytest.approx(one["centroid"], abs=1e-12)


def test_plane_has_a_point_of_it(model, part_ids):
    """a plane's face_info gives a point of the plane (位置合わせ): the plate's
    top is at z 15, the block's at z 35"""
    for ref, z in zip(_tops(model, part_ids), (15, 35)):
        info = _measure(model, {"type": "face_info", "ref": ref})
        assert info["origin"][2] == pytest.approx(z, abs=1e-9)


def test_parallel_faces_line_through_the_click(model, part_ids):
    """plate top (z 15) and block top (z 35): 20 wherever they overlap; the line
    goes through the clicked point, square to both faces"""
    a, b = _tops(model, part_ids)
    res = _measure(model, {"type": "distance", "a": a, "b": b, "nearA": [60, 20, 15], "nearB": [40, 40, 35]})
    assert res["value"] == pytest.approx(20.0, abs=1e-9)
    assert res["pointA"] == pytest.approx([60, 20, 15], abs=1e-9)
    assert res["pointB"] == pytest.approx([60, 20, 35], abs=1e-9)
    # only the second click given: the line goes through it
    res = _measure(model, {"type": "distance", "a": a, "b": b, "nearB": [40, 40, 35]})
    assert res["pointA"] == pytest.approx([40, 40, 15], abs=1e-9)
    assert res["pointB"] == pytest.approx([40, 40, 35], abs=1e-9)
    # a click off the mesh's exact plane (display tessellation) is dropped onto it
    res = _measure(model, {"type": "distance", "a": a, "b": b, "nearA": [55, 25, 15.0004]})
    assert res["pointA"] == pytest.approx([55, 25, 15], abs=1e-9)


def test_parallel_faces_value_does_not_depend_on_the_click(model, part_ids):
    a, b = _tops(model, part_ids)
    plain = _measure(model, {"type": "distance", "a": a, "b": b})
    near = _measure(model, {"type": "distance", "a": a, "b": b, "nearA": [35, 18, 15]})
    assert plain["value"] == near["value"] == pytest.approx(20.0, abs=1e-9)


def test_parallel_faces_not_facing_keep_brepextrema(model, part_ids):
    """plate front (y 0, z 0..15) and block front (y 15, z 15..35) face each other
    only along z 15: a click elsewhere is not projected through, the line is one
    of BRepExtrema's (on that edge), the one nearest the clicks"""
    plate, block = part_ids["plate"][0], part_ids["cavity_block"][0]
    a = {"partId": plate, "kind": "face", "id": _planar_face(model, plate, 1, [50, -100, 7])}
    b = {"partId": block, "kind": "face", "id": _planar_face(model, block, 1, [50, -100, 25])}
    res = _measure(model, {"type": "distance", "a": a, "b": b, "nearA": [50, 0, 7], "nearB": [50, 15, 25]})
    assert res["value"] == pytest.approx(15.0, abs=1e-9)
    pa, pb = res["pointA"], res["pointB"]
    assert pa[1] == pytest.approx(0, abs=1e-9) and pb[1] == pytest.approx(15, abs=1e-9), (pa, pb)
    assert pa[2] == pytest.approx(15, abs=1e-6) and pb[2] == pytest.approx(15, abs=1e-6), (pa, pb)
    assert 30 - 1e-6 <= pa[0] <= 70 + 1e-6, pa


def test_nearest_of_brepextrema_solutions(model):
    """two pins' cylinders: the gap is 42 along the line through both axes; with
    the clicks given, the reported line is one of the solutions, near the clicks"""
    _, _, pin_ids = model
    fa, _ = _cylinder_face_id(model, pin_ids[0])
    fb, _ = _cylinder_face_id(model, pin_ids[1])
    req = {
        "type": "distance",
        "a": {"partId": pin_ids[0], "kind": "face", "id": fa},
        "b": {"partId": pin_ids[1], "kind": "face", "id": fb},
        "nearA": [29, 30, 20],
        "nearB": [71, 30, 20],
    }
    res = _measure(model, req)
    assert res["value"] == pytest.approx(42.0, abs=1e-9)
    # on the line through both axes (y 30), at the pins' facing sides
    assert res["pointA"][0] == pytest.approx(29, abs=1e-6) and res["pointB"][0] == pytest.approx(71, abs=1e-6)
    assert res["pointA"][1] == pytest.approx(30, abs=1e-6) and res["pointB"][1] == pytest.approx(30, abs=1e-6)
    # BRepExtrema gives this gap at the pins' two ends (z 15 and z 40): the one
    # nearer the clicks, whichever it lists first
    assert res["pointA"][2] == pytest.approx(15, abs=1e-6) and res["pointB"][2] == pytest.approx(15, abs=1e-6)
    res = _measure(model, {**req, "nearA": [29, 30, 38], "nearB": [71, 30, 38]})
    assert res["pointA"][2] == pytest.approx(40, abs=1e-6) and res["pointB"][2] == pytest.approx(40, abs=1e-6)


def test_line_through_the_click_must_realise_the_value(monkeypatch):
    """Planes only nearly parallel pass the parallel test, but drift apart
    across the faces: the line through the click is longer than the minimum
    there, so BRepExtrema's line is kept. Here the roof is tilted 0.01 rad and
    the parallel test loosened to let it in (the drift is far bigger than at the
    real threshold; the check that catches it is the same)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt

    from app import measure

    def square(origin, normal, xdir):
        """100 x 100 from the origin, along xdir and normal x xdir"""
        pln = gp_Pln(gp_Ax3(gp_Pnt(*origin), gp_Dir(*normal), gp_Dir(*xdir)))
        return BRepBuilderAPI_MakeFace(pln, 0, 100, 0, 100).Face()

    t = 0.01
    floor = square((0, 0, 0), (0, 0, 1), (1, 0, 0))
    # z = 10 at x 0, rising to 10 + 100 sin t: the minimum is 10, along the low edge
    roof = square((0, 0, 10), (-math.sin(t), 0, math.cos(t)), (math.cos(t), 0, math.sin(t)))
    shapes = {1: floor, 2: roof}
    monkeypatch.setattr(measure, "_resolve", lambda ref, meshes: shapes[ref["id"]])
    monkeypatch.setattr(measure, "PARALLEL_SIN", 0.1)
    # a click at x 80, where the roof is 10.8 above the floor
    res = measure.distance({"kind": "face", "id": 1}, {"kind": "face", "id": 2}, [], near_a=[80, 50, 0])
    assert res["value"] == pytest.approx(10.0, abs=1e-9)
    assert math.dist(res["pointA"], res["pointB"]) == pytest.approx(res["value"], abs=1e-9), res
    assert res["pointB"][0] == pytest.approx(0, abs=1e-6), ("on the roof's low edge", res)


def test_angle_between_square_faces(model, part_ids):
    """the block's top and its front side: 90 degrees (they meet: distance 0)"""
    block = part_ids["cavity_block"][0]
    top = {"partId": block, "kind": "face", "id": _planar_face(model, block, 2, [50, 30, 100])}
    front = {"partId": block, "kind": "face", "id": _planar_face(model, block, 1, [50, -100, 25])}
    res = _measure(model, {"type": "distance", "a": top, "b": front})
    assert res["value"] == pytest.approx(0.0, abs=1e-9)
    assert res["angle"] == pytest.approx(90.0, abs=1e-9)


def test_no_angle_for_parallel_or_curved(model, part_ids):
    """parallel planes have no angle to give; nor does a cylinder"""
    a, b = _tops(model, part_ids)
    assert "angle" not in _measure(model, {"type": "distance", "a": a, "b": b})
    _, _, pin_ids = model
    fa, _ = _cylinder_face_id(model, pin_ids[0])
    res = _measure(model, {"type": "distance", "a": a, "b": {"partId": pin_ids[0], "kind": "face", "id": fa}})
    assert "angle" not in res


def test_angle_tilted_planes_and_lines(monkeypatch):
    """built here: a floor, a roof tilted 30 degrees about y, a straight edge
    rising 20 degrees from the floor, another lying 50 degrees round from x.
    Plane to plane 30, edge to the floor 20, edge to edge (in the floor and
    rising) by their directions, and a tiny tilt kept exact"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt

    from app import measure

    def square(origin, normal, xdir):
        return BRepBuilderAPI_MakeFace(gp_Pln(gp_Ax3(gp_Pnt(*origin), gp_Dir(*normal), gp_Dir(*xdir))), 0, 10, 0, 10).Face()

    def edge(p, q):
        return BRepBuilderAPI_MakeEdge(gp_Pnt(*p), gp_Pnt(*q)).Edge()

    r = math.radians
    floor = square((0, 0, 0), (0, 0, 1), (1, 0, 0))
    roof = square((0, 0, 5), (-math.sin(r(30)), 0, math.cos(r(30))), (math.cos(r(30)), 0, math.sin(r(30))))
    rising = edge((20, 0, 0), (20 + math.cos(r(20)), 0, math.sin(r(20))))
    lying = edge((0, 20, 1), (math.cos(r(50)), 20 + math.sin(r(50)), 1))
    tiny = square((0, 0, 9), (-math.sin(1e-4), 0, math.cos(1e-4)), (math.cos(1e-4), 0, math.sin(1e-4)))
    shapes = {1: floor, 2: roof, 3: rising, 4: lying, 5: tiny}
    monkeypatch.setattr(measure, "_resolve", lambda ref, meshes: shapes[ref["id"]])

    def angle(i, j):
        return measure.distance({"kind": "face", "id": i}, {"kind": "face", "id": j}, []).get("angle")

    assert angle(1, 2) == pytest.approx(30.0, abs=1e-9)
    assert angle(2, 1) == pytest.approx(30.0, abs=1e-9)
    assert angle(3, 1) == pytest.approx(20.0, abs=1e-9), "a line to a plane"
    # rising lies in the xz plane at 20 degrees up, lying in a horizontal plane at 50 degrees round from x
    want = math.degrees(math.acos(abs(math.cos(r(20)) * math.cos(r(50)))))
    assert angle(3, 4) == pytest.approx(want, abs=1e-9), "two lines"
    assert angle(1, 5) == pytest.approx(math.degrees(1e-4), rel=1e-9), "a small angle stays exact"


@pytest.mark.parametrize("key", ["nearA", "nearB"])
@pytest.mark.parametrize("bad", [[1, 2], [1, "x", 3], "abc", {"x": 1}])
def test_a_bad_clicked_point_is_refused(model, key, bad):
    """a clicked point the UI never sends (a hand-made request): 422 that names it, not a 500"""
    r = model[0].post(
        f"/api/models/{model[1]}/measure",
        json={"type": "distance", "a": {"kind": "point", "xyz": [0, 0, 0]}, "b": {"kind": "point", "xyz": [3, 4, 0]}, key: bad},
    )
    assert r.status_code == 422 and key in r.text, (r.status_code, r.text)
