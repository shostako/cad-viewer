"""厚肉 (thick.py, GET /thick and /thick.bin) against shapes of known walls.

Every expected value comes from how the shape was built (box sides, the step's
height, the boss's radius), never from the code under test. The grid's values
are estimates within about its pitch (the API says it); the places' diameters
are measured again exactly (to the surface), so they are held to the
tessellation's chord, not the pitch.
"""
import json
import pathlib
import struct
import tempfile

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

from app.main import app

TESTDATA = pathlib.Path(__file__).resolve().parents[2] / "testdata"


@pytest.fixture
def client():
    return TestClient(app)


def _box(x0, y0, z0, x1, y1, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _fuse(a, b):
    f = BRepAlgoAPI_Fuse(a, b)
    f.Build()
    return f.Shape()


def _step(shape) -> bytes:
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "s.step"
        assert w.Write(str(p)) == IFSelect_RetDone
        return p.read_bytes()


def _upload(client, name, data) -> str:
    r = client.post("/api/models", files={"file": (name, data, "x")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _thick(client, mid, **q):
    r = client.get(f"/api/models/{mid}/thick", params=q)
    assert r.status_code == 200, r.text
    return r.json()["parts"]


def _vertex_values(client, mid) -> dict[str, np.ndarray]:
    r = client.get(f"/api/models/{mid}/thick.bin")
    assert r.status_code == 200, r.text
    blob = r.content
    (n,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + n])
    return {
        name: np.frombuffer(blob, dtype=np.float32, count=b["count"], offset=4 + n + b["offset"])
        for name, b in header["buffers"].items()
    }


def test_uniform_plate_has_no_place(client):
    """an 80 x 40 x 2 plate: its general wall is 2, every face's too (its sides
    as well: the far side of a side face is the plate), and nothing is thick"""
    mid = _upload(client, "plate.step", _step(_box(0, 0, 0, 80, 40, 2)))
    (p,) = _thick(client, mid, ratio=1.5)
    assert p["status"] == "ok"
    assert abs(p["nominalAuto"] - 2) <= p["pitch"], p
    assert p["spots"] == [] and p["spotsMore"] == 0
    (v,) = _vertex_values(client, mid).values()
    assert len(v) > 0 and np.all(np.abs(v - 2) <= p["pitch"]), (v.min(), v.max())


def test_a_general_wall_given(client):
    """the same 2 mm plate with the general wall given as 1 mm: it is all 2
    across, twice that, so at 1.5 times it is one place (and the found wall stays)"""
    mid = _upload(client, "plate.step", _step(_box(0, 0, 0, 80, 40, 2)))
    (p,) = _thick(client, mid, ratio=1.5, nominal="0:1")
    assert p["nominal"] == 1 and abs(p["nominalAuto"] - 2) <= p["pitch"], p
    assert len(p["spots"]) == 1 and abs(p["spots"][0]["diameter"] - 2) <= 0.02 and abs(p["spots"][0]["ratio"] - 2) <= 0.02, p


def test_a_brep_part_closed_by_its_brep(client):
    """curved_part's body (testdata/make_step_assembly.py): a closed solid, as
    /properties says; its display mesh's curved seams leave hairline gaps a
    mesh check would call open. Its closure is the B-rep's: it is judged"""
    mid = _upload(client, "curved_part.step", (TESTDATA / "curved_part.step").read_bytes())
    props = {p["id"]: p for p in client.get(f"/api/models/{mid}/properties").json()["parts"]}
    assert all(p["closed"] for p in props.values())
    parts = _thick(client, mid)
    assert [p["status"] for p in parts] == ["ok"] * len(props), parts


def test_stepped_plate_the_thick_step_only(client):
    """1 mm over x 0..60 and a 6 mm step over x 60..80 (#59's 完了: only the
    6 mm step is thick). The general wall is the 1 mm one (its faces are the
    larger); the step is one place, its sphere 6 across inside the step"""
    shape = _fuse(_box(0, 0, 0, 60, 40, 1), _box(60, 0, 0, 80, 40, 6))
    mid = _upload(client, "stepped.step", _step(shape))
    (p,) = _thick(client, mid, ratio=1.5)
    assert abs(p["nominalAuto"] - 1) <= p["pitch"], p
    assert len(p["spots"]) == 1, p["spots"]
    s = p["spots"][0]
    assert abs(s["diameter"] - 6) <= 0.02, s
    x, y, z = s["center"]
    assert 63 - 0.02 <= x <= 77 + 0.02 and 3 - 0.02 <= y <= 37 + 0.02 and abs(z - 3) <= 0.02, s
    assert abs(s["ratio"] - s["diameter"] / p["nominal"]) <= 1e-3
    # where the sphere touches the surface: 3 away from its centre, the outward normal there
    touch, normal = np.array(s["surface"]), np.array(s["normal"])
    assert abs(np.linalg.norm(touch - np.array(s["center"])) - 3) <= 0.02, s
    assert abs(np.linalg.norm(normal) - 1) <= 1e-6 and np.dot(normal, touch - np.array(s["center"])) > 0, s
    # the general wall given (1 mm): 6 mm is thick at 4 times, not at 6.5 times
    assert len(_thick(client, mid, ratio=4, nominal="0:1")[0]["spots"]) == 1
    assert _thick(client, mid, ratio=6.5, nominal="0:1")[0]["spots"] == []
    # the faces' values: the thin faces 1, the step's top 6
    v = _vertex_values(client, mid)["p0:thick"]
    assert np.any(np.abs(v - 1) <= p["pitch"]) and np.any(np.abs(v - 6) <= 2 * p["pitch"]), (v.min(), v.max())


def test_boss_on_a_plate(client):
    """a ⌀8 x 6 boss on a 2 mm plate: the place is in the boss, its sphere 8
    across (the boss's diameter; the boss and the plate are 8 high), its
    centre on the boss's axis 4 up"""
    plate = _box(0, 0, 0, 40, 40, 2)
    boss = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(20, 20, 2), gp_Dir(0, 0, 1)), 4, 6).Shape()
    mid = _upload(client, "boss.step", _step(_fuse(plate, boss)))
    (p,) = _thick(client, mid, ratio=1.5)
    assert abs(p["nominalAuto"] - 2) <= p["pitch"], p
    assert len(p["spots"]) == 1, p["spots"]
    s = p["spots"][0]
    # the display mesh's cylinder is a polygon inside the circle: a little under 8
    assert 7.9 <= s["diameter"] <= 8.0 + 1e-6, s
    x, y, z = s["center"]
    assert abs(x - 20) <= 0.1 and abs(y - 20) <= 0.1 and abs(z - 4) <= 0.1, s


def test_a_mesh_part(client):
    """an STL plate 30 x 20 x 3: its wall from its triangles. A vertex takes its
    triangles' values: at the plate's edge, a side's too (a side 3 high, its
    spheres stopped by the faces beside it: a little under the wall, within
    two of the grid's steps)"""
    stl = trimesh.creation.box(extents=(30, 20, 3)).export(file_type="stl")
    mid = _upload(client, "plate.stl", stl)
    (p,) = _thick(client, mid)
    assert p["status"] == "ok" and abs(p["nominalAuto"] - 3) <= p["pitch"], p
    (v,) = _vertex_values(client, mid).values()
    assert np.all(np.abs(v - 3) <= 2 * p["pitch"]), (v.min(), v.max())


def test_overlapping_bodies_are_their_union(client):
    """an STL of two closed boxes laid over each other (x 0..20 and 10..30, both
    20 x 2): the part is their union, a 30 x 20 x 2 plate. Its general wall is
    2, and with 1 mm given it is all one place, a sphere 2 across (the crossings
    of both together would make a void of the overlap: two places)"""
    a = trimesh.creation.box(bounds=[[0, 0, 0], [20, 20, 2]])
    b = trimesh.creation.box(bounds=[[10, 0, 0], [30, 20, 2]])
    stl = trimesh.util.concatenate([a, b]).export(file_type="stl")
    mid = _upload(client, "overlap.stl", stl)
    (p,) = _thick(client, mid, ratio=1.5)
    assert p["status"] == "ok" and abs(p["nominalAuto"] - 2) <= p["pitch"], p
    (p,) = _thick(client, mid, ratio=1.5, nominal="0:1")
    # measured again to the union's outside (the faces inside it are not the surface)
    assert len(p["spots"]) == 1 and abs(p["spots"][0]["diameter"] - 2) <= 0.02, p["spots"]


def test_bodies_overlapping_along_the_rays(client):
    """two closed boxes one over the other, overlapping in height (z 0..3 and
    1..4, both 20 x 20): their union is a 4 mm slab. Paired over both, a
    column's crossings (0, 1, 3, 4) would make 1..3 a void, two 1 mm slabs; and
    the faces inside the union (z 1 and 3) are not its surface: the place's
    sphere is 4 across"""
    a = trimesh.creation.box(bounds=[[0, 0, 0], [20, 20, 3]])
    b = trimesh.creation.box(bounds=[[0, 0, 1], [20, 20, 4]])
    mid = _upload(client, "stacked.stl", trimesh.util.concatenate([a, b]).export(file_type="stl"))
    (p,) = _thick(client, mid, ratio=1.5)
    assert p["status"] == "ok" and abs(p["nominalAuto"] - 4) <= p["pitch"], p
    (p,) = _thick(client, mid, ratio=1.5, nominal="0:1")
    assert len(p["spots"]) == 1 and abs(p["spots"][0]["diameter"] - 4) <= 0.02, p["spots"]


def test_a_cavity_body_is_taken_away(client):
    """an STL box 20 x 20 x 10 with a box turned inside out within it (a closed
    void 10 x 10 x 6 in the middle): the walls round the void are 2 (top and
    bottom) and 5 (the sides). The largest sphere is in a corner column, against
    the two outer walls and the void's upright edge: 2 x 5√2 / (1 + √2) = 5.86
    across. Filled (the void not taken away), a sphere 10 across would fit"""
    outer = trimesh.creation.box(bounds=[[0, 0, 0], [20, 20, 10]])
    void = trimesh.creation.box(bounds=[[5, 5, 2], [15, 15, 8]])
    void.invert()
    stl = trimesh.util.concatenate([outer, void]).export(file_type="stl")
    mid = _upload(client, "void.stl", stl)
    (p,) = _thick(client, mid, ratio=1.5, nominal="0:1")
    assert p["status"] == "ok", p
    biggest = max(s["diameter"] for s in p["spots"])
    corner = 2 * 5 * 2**0.5 / (1 + 2**0.5)
    assert abs(biggest - corner) <= 0.02, (biggest, corner)


def test_the_model_grid_budget():
    """the parts share one budget by their boxes' volumes, each between its least and its most"""
    from app.thick import GRID_MAX, GRID_MIN, MODEL_GRID_MAX, grid_budgets

    b = grid_budgets({0: 1000.0, 1: 3000.0, 2: 0.0})
    assert b[1] == min(GRID_MAX, int(MODEL_GRID_MAX * 0.75)) and b[0] == min(GRID_MAX, int(MODEL_GRID_MAX * 0.25)), b
    assert b[2] == GRID_MIN
    # many parts: the least share goes down, the sum stays under the model's
    many = grid_budgets({k: 1.0 for k in range(100)})
    assert sum(many.values()) <= MODEL_GRID_MAX and len(set(many.values())) == 1, (sum(many.values()), set(many.values()))
    lopsided = grid_budgets({0: 1e9, **{k: 1e-3 for k in range(1, 200)}})
    assert sum(lopsided.values()) <= MODEL_GRID_MAX and lopsided[0] <= GRID_MAX, sum(lopsided.values())


def test_the_model_budget_coarsens_the_grids(client, monkeypatch):
    """a model's parts share its budget: with a small one, each part's grid
    (its box over its pitch, as thick.py lays it) fits in its share"""
    from app import thick

    monkeypatch.setattr(thick, "MODEL_GRID_MAX", 400_000)
    monkeypatch.setattr(thick, "GRID_MIN", 10_000)
    mid = _upload(client, "mini_mold.step", (TESTDATA / "mini_mold.step").read_bytes()[:-1] + b"\n\n")
    parts = _thick(client, mid)
    assert parts and all(p["status"] == "ok" for p in parts), parts
    # the four parts' boxes (make_step_assembly.py): plate 100 x 60 x 15, pins ⌀8 x 25, block 40 x 30 x 20
    boxes = {0: (100, 60, 15), 1: (8, 8, 25), 2: (8, 8, 25), 3: (40, 30, 20)}
    total = sum(a * b * c for a, b, c in boxes.values())
    for p in parts:
        size = np.array(boxes[p["id"]], dtype=float)
        points = np.prod(np.ceil(size / p["pitch"]) + 5)
        share = max(10_000, 400_000 * np.prod(size) / total)
        assert points <= share * 1.01, (p["id"], points, share)


def test_an_open_mesh_cannot_be_judged(client):
    """a box with one face gone: open, no values"""
    m = trimesh.creation.box(extents=(10, 10, 2))
    m.update_faces(np.arange(len(m.faces)) > 1)  # two triangles: one side gone
    mid = _upload(client, "open.stl", m.export(file_type="stl"))
    (p,) = _thick(client, mid)
    assert p["status"] == "open" and "spots" not in p, p
    (v,) = _vertex_values(client, mid).values()
    assert np.all(v == 0)


def test_mini_mold_parts_each_their_own_wall(client):
    """mini_mold (testdata/make_step_assembly.py): the plate 15 thick, the
    block 40 x 30 x 20 (its walls 20 at most), the pins ⌀8: each part's own"""
    mid = _upload(client, "mini_mold.step", (TESTDATA / "mini_mold.step").read_bytes())
    parts = {p["id"]: p for p in _thick(client, mid)}
    meta = client.get(f"/api/models/{mid}/mesh.bin")
    assert meta.status_code == 200
    plate = parts[0]
    assert abs(plate["nominalAuto"] - 15) <= plate["pitch"], plate
    pins = [p for p in parts.values() if abs(p["nominalAuto"] - 8) <= 2 * p["pitch"] + 0.25]
    assert len(pins) == 2, parts
    assert all(p["spots"] == [] for p in parts.values())


def test_bad_requests(client):
    mid = _upload(client, "plate.step", _step(_box(0, 0, 0, 10, 10, 2)))
    assert client.get(f"/api/models/{mid}/thick", params={"ratio": 0.5}).status_code == 422
    assert client.get(f"/api/models/{mid}/thick", params={"nominal": "x"}).status_code == 422
    assert client.get(f"/api/models/{mid}/thick", params={"nominal": "0:0"}).status_code == 422
    assert client.get("/api/models/nope/thick").status_code == 404
    dxf = _upload(client, "plate_drawing.dxf", (TESTDATA / "plate_drawing.dxf").read_bytes())
    assert client.get(f"/api/models/{dxf}/thick").status_code == 422
    assert client.get(f"/api/models/{dxf}/thick.bin").status_code == 422
