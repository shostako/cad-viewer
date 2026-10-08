"""Loose IGES faces are sewn into one body; loose curves become one part.

The fixtures are written on the fly with OCCT's IGES writer, so the expected
values (box size, volume) come from the construction, not from the code under
test.
"""
import pathlib
import struct
import json
from collections import OrderedDict

import numpy as np
import pytest
from fastapi.testclient import TestClient

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec
from OCP.IGESControl import IGESControl_Writer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

from app.main import app

BOX = (10.0, 20.0, 30.0)


def _write_iges(
    tmp_path: pathlib.Path,
    *,
    faces_one_by_one: bool,
    mode: int = 0,
    open_box: bool = False,
    size=BOX,
    top_gap: float = 0.0,
) -> bytes:
    """A 10x20x30 box as IGES plus two loose lines (coordinate-axis style).

    mode 0 writes trimmed surfaces (no solid). faces_one_by_one adds each face
    as its own entity — what CAD exports usually look like (the reader then
    reports one part per face). open_box drops the top face, so the faces
    cannot close into a solid. top_gap lifts the top face by that much,
    leaving a slit all around it.
    """
    box = BRepPrimAPI_MakeBox(*size).Shape()
    w = IGESControl_Writer("MM", mode)
    if faces_one_by_one:
        e = TopExp_Explorer(box, TopAbs_FACE)
        n = 0
        while e.More():
            n += 1
            face = e.Current()
            if top_gap and _is_top(face, size[2]):
                t = gp_Trsf()
                t.SetTranslation(gp_Vec(0, 0, top_gap))
                face = BRepBuilderAPI_Transform(face, t, True).Shape()
            if not (open_box and n == 6):
                w.AddShape(face)
            e.Next()
    else:
        w.AddShape(box)
    w.AddShape(BRepBuilderAPI_MakeEdge(gp_Pnt(-50, 0, 0), gp_Pnt(50, 0, 0)).Edge())
    w.AddShape(BRepBuilderAPI_MakeEdge(gp_Pnt(0, -50, 0), gp_Pnt(0, 50, 0)).Edge())
    w.ComputeModel()
    path = tmp_path / "box.igs"
    assert w.Write(str(path))
    return path.read_bytes()


def _is_top(face, height) -> bool:
    box = Bnd_Box()
    BRepBndLib.Add_s(face, box)
    zmin = box.Get()[2]
    return abs(zmin - height) < 1e-6


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh store and disk cache: the same IGES bytes recur across tests."""
    from app import cache
    from app.store import store

    monkeypatch.setattr(store, "_models", OrderedDict())
    monkeypatch.setattr(store, "_by_hash", {})
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    return TestClient(app)


def _upload(client, data):
    r = client.post("/api/models", files={"file": ("box.igs", data, "x")})
    assert r.status_code == 200, r.text
    return r.json()


def _mesh(client, mid):
    blob = client.get(f"/api/models/{mid}/mesh.bin").content
    (hlen,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + hlen])
    base = 4 + hlen

    def buf(name, dtype):
        d = header["buffers"][name]
        # "count" is the number of scalars (flattened), not of items
        flat = np.frombuffer(blob, dtype=dtype, count=d["count"], offset=base + d["offset"])
        return flat.reshape(-1, d["itemSize"])

    return header, buf


def _face_ids_by_normal(header, buf, part_id):
    """faceId -> outward normal (unit, rounded) for a box part"""
    normals = buf(f"p{part_id}:normals", np.float32)
    indices = buf(f"p{part_id}:indices", np.uint32).reshape(-1, 3)  # packed flat, 3 per triangle
    part = next(p for p in header["parts"] if p["id"] == part_id)
    out = {}
    for fr in part["faceRanges"]:
        tri = indices[fr["triStart"]]
        out[fr["faceId"]] = tuple(np.round(normals[tri[0]]).astype(int))
    return out


def _measure_faces(client, mid, part_id, fa, fb):
    r = client.post(
        f"/api/models/{mid}/measure",
        json={
            "type": "distance",
            "a": {"partId": part_id, "kind": "face", "id": fa},
            "b": {"partId": part_id, "kind": "face", "id": fb},
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["value"]


@pytest.mark.parametrize("faces_one_by_one", [True, False], ids=["face-per-entity", "compound-of-faces"])
def test_loose_faces_become_one_solid(client, tmp_path, faces_one_by_one):
    meta = _upload(client, _write_iges(tmp_path, faces_one_by_one=faces_one_by_one))
    names = [p["name"] for p in meta["parts"]]
    assert names == ["ソリッド", "曲線（2 本）"], names
    assert [c["name"] for c in meta["tree"]["children"]] == names

    header, buf = _mesh(client, meta["id"])
    solid = header["parts"][0]
    assert len(solid["faceRanges"]) == 6
    # bbox reports the body, not the 100 mm construction lines
    assert meta["bbox"]["min"] == pytest.approx([0, 0, 0])
    assert meta["bbox"]["max"] == pytest.approx(list(BOX))

    # one sewn body: opposite faces measure the exact box size
    by_normal = {n: fid for fid, n in _face_ids_by_normal(header, buf, 0).items()}
    for axis, size in enumerate(BOX):
        plus = tuple(1 if i == axis else 0 for i in range(3))
        minus = tuple(-1 if i == axis else 0 for i in range(3))
        assert _measure_faces(client, meta["id"], 0, by_normal[plus], by_normal[minus]) == pytest.approx(size)


def test_loose_curves_are_drawn(client, tmp_path):
    meta = _upload(client, _write_iges(tmp_path, faces_one_by_one=True))
    header, buf = _mesh(client, meta["id"])
    curves = header["parts"][1]
    assert curves["name"] == "曲線（2 本）"
    edges = buf("p1:edges", np.float32)
    assert len(curves["edgeRanges"]) == 2 and len(edges) >= 4  # 2 lines x (>=1 segment = 2 points)
    xs = edges[:, 0]
    assert xs.min() == pytest.approx(-50) and xs.max() == pytest.approx(50)


def test_open_faces_stay_a_surface(client, tmp_path):
    meta = _upload(client, _write_iges(tmp_path, faces_one_by_one=True, open_box=True))
    assert [p["name"] for p in meta["parts"]] == ["サーフェス", "曲線（2 本）"]
    header, _ = _mesh(client, meta["id"])
    assert len(header["parts"][0]["faceRanges"]) == 5


def test_solid_iges_is_left_alone(client, tmp_path):
    """mode 1 writes a real solid: nothing to sew, the solid keeps its own part."""
    meta = _upload(client, _write_iges(tmp_path, faces_one_by_one=False, mode=1))
    names = [p["name"] for p in meta["parts"]]
    assert names[-1] == "曲線（2 本）"
    assert len(names) == 2 and names[0] not in ("ソリッド", "サーフェス"), names


def test_cache_hit_reparse_numbers_faces_the_same(client, tmp_path):
    """The lazy B-rep re-parse after a disk-cache hit must sew to the same face
    numbering as the cached mesh, or measurements land on the wrong faces."""
    from app.store import store

    data = _write_iges(tmp_path, faces_one_by_one=True)
    first = _upload(client, data)
    header, buf = _mesh(client, first["id"])
    by_normal = {n: fid for fid, n in _face_ids_by_normal(header, buf, 0).items()}
    store.remove(first["id"])

    again = _upload(client, data)
    assert again["cached"] is True
    assert store.get(again["id"]).brep is None  # the measure below re-parses
    # face ids taken from the CACHED mesh still name the same faces
    assert _measure_faces(client, again["id"], 0, by_normal[(0, 0, 1)], by_normal[(0, 0, -1)]) == pytest.approx(BOX[2])
    assert _measure_faces(client, again["id"], 0, by_normal[(1, 0, 0)], by_normal[(-1, 0, 0)]) == pytest.approx(BOX[0])


def test_sewing_cap_ignores_unrelated_geometry(client, tmp_path):
    """A 5 mm body with a 0.005 mm slit must keep the slit even though the file
    also holds 100 mm construction lines: the tolerance cap comes from the faces
    being sewn (diag 8.7 mm -> cap ~0.0009 mm), not from the whole file (which
    would allow 0.01 mm and weld the slit shut)."""
    data = _write_iges(tmp_path, faces_one_by_one=True, size=(5.0, 5.0, 5.0), top_gap=0.005)
    meta = _upload(client, data)
    names = [p["name"] for p in meta["parts"]]
    # the lifted top stays apart: open surfaces, no solid
    assert names[-1] == "曲線（2 本）"
    assert all(n.startswith("サーフェス") for n in names[:-1]) and len(names) >= 2, names


def test_small_body_without_gap_still_closes(client, tmp_path):
    """the same small body with no slit closes at the small cap"""
    data = _write_iges(tmp_path, faces_one_by_one=True, size=(5.0, 5.0, 5.0))
    meta = _upload(client, data)
    assert [p["name"] for p in meta["parts"]] == ["ソリッド", "曲線（2 本）"]
