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
