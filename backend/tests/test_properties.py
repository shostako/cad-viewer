"""Volume / area / centre of mass (C1).

Every expected value comes from how the shape was built (box sides, cylinder
radius and height), never from the code under test.
"""
import math
import pathlib
from collections import OrderedDict

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Pnt
from OCP.IGESControl import IGESControl_Writer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound

from app import properties
from app.loaders import load_mesh
from app.main import app
from app.meshpack import pack_trimesh

REL = 1e-9
TESTDATA = pathlib.Path(__file__).resolve().parents[2] / "testdata"
STEP = TESTDATA / "mini_mold.step"
DXF = TESTDATA / "plate_drawing.dxf"


def approx(x, rel=REL):
    return pytest.approx(x, rel=rel, abs=1e-9)


def box(dx=10.0, dy=20.0, dz=30.0, at=(1.0, 2.0, 3.0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def compound(*shapes):
    c = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(c)
    for s in shapes:
        b.Add(c, s)
    return c


def faces(shape):
    out = []
    e = TopExp_Explorer(shape, TopAbs_FACE)
    while e.More():
        out.append(e.Current())
        e.Next()
    return out


def zmin(shape):
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    return b.Get()[2]


def open_shell():
    """the 10x20x30 box at (1,2,3) without its top face, sewn into one open shell"""
    sew = BRepBuilderAPI_Sewing(1e-6)
    for f in faces(box()):
        if abs(zmin(f) - 33.0) > 1e-6:  # the top face sits at z = 3 + 30 (Bnd_Box adds a tolerance)
            sew.Add(f)
    sew.Perform()
    shell = sew.SewedShape()
    assert shell.ShapeType() == TopAbs_SHELL
    return TopoDS.Shell_s(shell)


# ---- B-rep, pure functions ------------------------------------------------------
def test_box():
    r = properties.brep_part_properties(box())
    assert r["closed"] and r["reason"] is None
    assert r["volume"] == approx(6000)
    assert r["area"] == approx(2 * (10 * 20 + 10 * 30 + 20 * 30))
    assert r["centerOfMass"] == [approx(6), approx(12), approx(18)]


def test_cylinder_is_exact():
    r = properties.brep_part_properties(BRepPrimAPI_MakeCylinder(4, 25).Shape())
    assert r["volume"] == approx(math.pi * 16 * 25)
    assert r["area"] == approx(2 * math.pi * 4 * 25 + 2 * math.pi * 16)
    assert r["centerOfMass"] == [approx(0), approx(0), approx(12.5)]


def test_reversed_solid_counts_positive():
    r = properties.brep_part_properties(box().Reversed())
    assert r["volume"] == approx(6000)
    assert r["centerOfMass"] == [approx(6), approx(12), approx(18)]


def test_hollow_solid():
    outer = BRepPrimAPI_MakeBox(100, 100, 100).Shape()
    inner = BRepPrimAPI_MakeBox(gp_Pnt(25, 25, 25), 50, 50, 50).Shape()
    r = properties.brep_part_properties(BRepAlgoAPI_Cut(outer, inner).Shape())
    assert r["volume"] == approx(100**3 - 50**3)
    assert r["area"] == approx(6 * 100**2 + 6 * 50**2)


def test_closed_shell_outside_a_solid():
    e = TopExp_Explorer(box(), TopAbs_SHELL)
    r = properties.brep_part_properties(e.Current())
    assert r["closed"] and r["volume"] == approx(6000)


def test_open_shell_has_no_volume():
    r = properties.brep_part_properties(open_shell())
    assert not r["closed"] and r["volume"] is None and r["reason"] == "open"
    assert r["area"] == approx(2200 - 200)


def test_loose_face_has_no_volume():
    r = properties.brep_part_properties(faces(box())[0])
    assert r["reason"] == "open" and r["volume"] is None


def test_solid_from_open_shell_is_open():
    solid = BRepBuilderAPI_MakeSolid(open_shell()).Solid()
    r = properties.brep_part_properties(solid)
    assert r["reason"] == "open" and r["volume"] is None


def test_solid_plus_loose_face_is_open():
    far_face = faces(box(at=(100, 0, 0)))[0]
    r = properties.brep_part_properties(compound(box(), far_face))
    assert r["reason"] == "open" and r["volume"] is None


def test_curves_only():
    edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0)).Edge()
    r = properties.brep_part_properties(compound(edge))
    assert r["reason"] == "no_faces" and r["area"] == 0.0 and r["volume"] is None


def test_two_bodies_weighted_centroid():
    small = box(10, 10, 10, at=(0, 0, 0))  # 1000, centroid (5, 5, 5)
    big = box(20, 20, 20, at=(100, 0, 0))  # 8000, centroid (110, 10, 10)
    r = properties.brep_part_properties(compound(small, big))
    assert r["volume"] == approx(9000)
    want = [(1000 * 5 + 8000 * 110) / 9000, (1000 * 5 + 8000 * 10) / 9000, (1000 * 5 + 8000 * 10) / 9000]
    assert r["centerOfMass"] == [approx(w) for w in want]


# ---- mesh formats ------------------------------------------------------------------
def _mesh_props(mesh: trimesh.Trimesh):
    stl = mesh.export(file_type="stl")
    blob, _meta = pack_trimesh(load_mesh(stl, "x.stl"))
    return properties.mesh_properties(blob)["parts"][0]


def test_mesh_box_merges_split_vertices():
    r = _mesh_props(trimesh.creation.box(extents=(10, 20, 30)))
    assert r["closed"] and r["volume"] == approx(6000, 1e-6)
    assert r["area"] == approx(2200, 1e-6)


def test_mesh_open_box():
    m = trimesh.creation.box(extents=(10, 20, 30))
    keep = m.face_normals[:, 2] < 0.5  # drop the top (+Z, 10x20) face
    r = _mesh_props(trimesh.Trimesh(m.vertices, m.faces[keep], process=False))
    assert r["reason"] == "open" and r["volume"] is None
    assert r["area"] == approx(2000, 1e-6)


def test_mesh_inverted_box():
    m = trimesh.creation.box(extents=(10, 20, 30))
    m.invert()
    r = _mesh_props(m)
    assert r["volume"] == approx(6000, 1e-6)


def test_mesh_closed_but_flat_is_degenerate():
    """a square seen from both sides (each side split on a different diagonal):
    every edge shared by exactly two faces, consistent winding, volume 0"""
    pos = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], dtype=np.float32)
    idx = np.array([[0, 1, 2], [0, 2, 3], [1, 0, 3], [1, 3, 2]], dtype=np.uint32)
    r = properties.mesh_part_properties(pos, idx)
    assert r["reason"] == "degenerate" and r["volume"] is None


def test_mesh_mixed_winding():
    """a closed box with one triangle flipped"""
    m = trimesh.creation.box(extents=(10, 20, 30))
    f = m.faces.copy()
    f[0] = f[0][::-1]
    r = properties.mesh_part_properties(m.vertices.astype(np.float32), f.astype(np.uint32))
    assert r["reason"] == "winding" and r["volume"] is None


def test_mesh_cylinder():
    n = 32
    r = _mesh_props(trimesh.creation.cylinder(radius=4, height=25, sections=n))
    assert r["volume"] == approx(0.5 * n * 16 * math.sin(2 * math.pi / n) * 25, 1e-6)


# ---- API ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    """fresh store and disk cache: the same bytes recur across tests"""
    from app import cache
    from app.store import store

    monkeypatch.setattr(store, "_models", OrderedDict())
    monkeypatch.setattr(store, "_by_hash", {})
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    return TestClient(app)


def _upload(client, name, data):
    r = client.post("/api/models", files={"file": (name, data, "x")})
    assert r.status_code == 200, r.text
    return r.json()


MOLD = {  # make_step_assembly.py
    "plate": (100 * 60 * 15, 2 * (100 * 60 + 100 * 15 + 60 * 15), (50, 30, 7.5)),
    "core_pin": (math.pi * 16 * 25, 2 * math.pi * 4 * 25 + 2 * math.pi * 16, None),
    "cavity_block": (40 * 30 * 20, 2 * (40 * 30 + 40 * 20 + 30 * 20), (50, 30, 25)),
}
PIN_CENTRES = [(25, 30, 27.5), (75, 30, 27.5)]


def _check_mold(body):
    assert body["source"] == "brep" and body["units"] == "mm"
    parts = body["parts"]
    assert sorted(p["name"] for p in parts) == ["cavity_block", "core_pin", "core_pin", "plate"]
    pins = []
    for p in parts:
        v, a, c = MOLD[p["name"]]
        assert p["closed"] and p["volume"] == approx(v) and p["area"] == approx(a), p
        if c is None:
            pins.append(p["centerOfMass"])
        else:
            assert p["centerOfMass"] == [approx(x) for x in c]
    assert sorted(pins) == [[approx(x) for x in c] for c in PIN_CENTRES]
    vs = [MOLD["plate"][0], MOLD["core_pin"][0], MOLD["core_pin"][0], MOLD["cavity_block"][0]]
    cs = [(50, 30, 7.5), *PIN_CENTRES, (50, 30, 25)]
    vt = sum(vs)
    t = body["total"]
    assert t["volume"] == approx(vt)
    assert t["area"] == approx(MOLD["plate"][1] + 2 * MOLD["core_pin"][1] + MOLD["cavity_block"][1])
    assert t["centerOfMass"] == [approx(sum(v * c[i] for v, c in zip(vs, cs)) / vt) for i in range(3)]
    assert t["closedParts"] == 4 and t["openParts"] == 0


@pytest.mark.skipif(not STEP.exists(), reason="run testdata/make_step_assembly.py first")
def test_api_mini_mold(client):
    meta = _upload(client, "mini_mold.step", STEP.read_bytes())
    r = client.get(f"/api/models/{meta['id']}/properties")
    assert r.status_code == 200, r.text
    _check_mold(r.json())


@pytest.mark.skipif(not STEP.exists(), reason="run testdata/make_step_assembly.py first")
def test_api_after_disk_cache_hit(client):
    from app.store import store

    data = STEP.read_bytes()
    first = _upload(client, "mini_mold.step", data)
    client.delete(f"/api/models/{first['id']}")
    meta = _upload(client, "mini_mold.step", data)
    assert meta["cached"] is True
    entry = store.get(meta["id"])
    assert entry.brep is None  # served from the disk cache: no B-rep yet
    r = client.get(f"/api/models/{meta['id']}/properties")
    assert r.status_code == 200, r.text
    _check_mold(r.json())
    assert entry.brep is not None and "raw" not in entry.extra


@pytest.mark.skipif(not STEP.exists(), reason="run testdata/make_step_assembly.py first")
def test_api_result_is_cached_per_entry(client, monkeypatch):
    calls = []
    real = properties.brep_properties

    def counting(meshes):
        calls.append(1)
        return real(meshes)

    monkeypatch.setattr(properties, "brep_properties", counting)
    meta = _upload(client, "mini_mold.step", STEP.read_bytes())
    for _ in range(2):
        assert client.get(f"/api/models/{meta['id']}/properties").status_code == 200
    assert len(calls) == 1


def test_api_stl(client):
    stl = trimesh.creation.box(extents=(10, 20, 30)).export(file_type="stl")
    meta = _upload(client, "box.stl", stl)
    body = client.get(f"/api/models/{meta['id']}/properties").json()
    assert body["source"] == "mesh"
    assert body["parts"][0]["volume"] == approx(6000, 1e-6)
    assert body["total"]["volume"] == approx(6000, 1e-6)


@pytest.mark.skipif(not DXF.exists(), reason="run testdata/make_dxf.py first")
def test_api_drawing_is_422(client):
    meta = _upload(client, "plate_drawing.dxf", DXF.read_bytes())
    assert client.get(f"/api/models/{meta['id']}/properties").status_code == 422


def test_api_unknown_model_is_404(client):
    assert client.get("/api/models/nope/properties").status_code == 404


def _iges(tmp_path, *, open_box):
    """the 10x20x30 box written face by face, plus two loose lines (as in test_sewing)"""
    w = IGESControl_Writer("MM", 0)
    for f in faces(BRepPrimAPI_MakeBox(10, 20, 30).Shape()):
        if open_box and abs(zmin(f) - 30) < 1e-6:
            continue
        w.AddShape(f)
    w.AddShape(BRepBuilderAPI_MakeEdge(gp_Pnt(-50, 0, 0), gp_Pnt(50, 0, 0)).Edge())
    w.AddShape(BRepBuilderAPI_MakeEdge(gp_Pnt(0, -50, 0), gp_Pnt(0, 50, 0)).Edge())
    w.ComputeModel()
    path = tmp_path / "box.igs"
    assert w.Write(str(path))
    return path.read_bytes()


@pytest.mark.parametrize("open_box", [False, True], ids=["closed", "open"])
def test_api_iges_after_sewing(client, tmp_path, open_box):
    meta = _upload(client, "box.igs", _iges(tmp_path, open_box=open_box))
    body = client.get(f"/api/models/{meta['id']}/properties").json()
    by_name = {p["name"]: p for p in body["parts"]}
    curves = by_name["曲線（2 本）"]
    assert curves["reason"] == "no_faces" and curves["area"] == 0.0
    if open_box:
        s = by_name["サーフェス"]
        assert s["reason"] == "open" and s["area"] == approx(2200 - 200)
        assert body["total"]["volume"] is None
        assert body["total"]["closedParts"] == 0 and body["total"]["openParts"] == 2
    else:
        s = by_name["ソリッド"]
        assert s["closed"] and s["volume"] == approx(6000, 1e-6)
        assert body["total"]["closedParts"] == 1 and body["total"]["openParts"] == 1


# ---- orientation (review of #12): the signed volume integral must not cancel


def _flipped_shell(flip_index):
    """the 10x20x30 box at (1,2,3) as one shell, with one face turned around.
    Topologically still closed (BRep_Tool.IsClosed ignores orientation)."""
    from OCP.TopoDS import TopoDS_Shell

    b = BRep_Builder()
    sh = TopoDS_Shell()
    b.MakeShell(sh)
    for i, f in enumerate(faces(box())):
        b.Add(sh, f.Reversed() if i == flip_index else f)
    return sh


@pytest.mark.parametrize("flip", [0, 5])
def test_brep_solid_with_a_flipped_face_has_no_volume(flip):
    from OCP.TopoDS import TopoDS_Solid

    b = BRep_Builder()
    solid = TopoDS_Solid()
    b.MakeSolid(solid)
    b.Add(solid, _flipped_shell(flip))
    r = properties.brep_part_properties(solid)
    # without the check it read 4000 mm3 (the flipped 10x20 face cancels) as closed
    assert r["volume"] is None and r["reason"] == properties.WINDING, r
    assert r["area"] == approx(2200)


def test_brep_free_shell_with_a_flipped_face_has_no_volume():
    r = properties.brep_part_properties(_flipped_shell(2))
    assert r["volume"] is None and r["reason"] == properties.WINDING, r


def _boxes_mesh(*specs):
    """trimesh boxes: (extents, centre, inverted)"""
    parts = []
    for extents, centre, inverted in specs:
        m = trimesh.creation.box(extents=extents)
        m.apply_translation(centre)
        if inverted:
            m.invert()
        parts.append(m)
    m = trimesh.util.concatenate(parts)
    return m.vertices.astype(np.float32), m.faces.astype(np.uint32)


def test_mesh_separate_inverted_body_is_added():
    """6000 (outward) + a separate 1000 turned inside out: 7000, not 6000 - 1000"""
    pos, idx = _boxes_mesh(((10, 20, 30), (0, 0, 0), False), ((10, 10, 10), (50, 0, 0), True))
    r = properties.mesh_part_properties(pos, idx)
    assert r["closed"] and r["volume"] == approx(7000), r
    assert r["centerOfMass"] == [approx(50 * 1000 / 7000), approx(0), approx(0)]


def test_mesh_cavity_is_still_subtracted_next_to_an_inverted_body():
    """a 4x4x4 cavity (facing inward, inside the 6000 box) is subtracted; the
    separate inverted 1000 is added: 6000 - 64 + 1000"""
    pos, idx = _boxes_mesh(
        ((10, 20, 30), (0, 0, 0), False), ((4, 4, 4), (0, 0, 0), True), ((10, 10, 10), (50, 0, 0), True)
    )
    r = properties.mesh_part_properties(pos, idx)
    assert r["closed"] and r["volume"] == approx(6936), r
    assert r["centerOfMass"][0] == approx(50 * 1000 / 6936)


def test_overlapping_solids_are_summed_not_united():
    """known limit, pinned: two overlapping 10x20x30 boxes in one part count twice"""
    r = properties.brep_part_properties(compound(box(), box(at=(6.0, 2.0, 3.0))))
    assert r["closed"] and r["volume"] == approx(12000), r


def test_total_area_counts_open_parts_too():
    closed = {"closed": True, "volume": 6000.0, "area": 2200.0, "centerOfMass": [0, 0, 0], "reason": None}
    open_ = {"closed": False, "volume": None, "area": 2000.0, "centerOfMass": None, "reason": "open"}
    curves = {"closed": False, "volume": None, "area": 0.0, "centerOfMass": None, "reason": "no_faces"}
    t = properties._model("brep", [closed, open_, curves])["total"]
    assert t["volume"] == approx(6000) and t["area"] == approx(4200), t
    assert t["closedParts"] == 1 and t["openParts"] == 2
    t = properties._model("brep", [open_])["total"]
    assert t["volume"] is None and t["area"] == approx(2000), t
