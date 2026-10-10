"""The unit a file is written in (meta "fileUnit"): OCCT reads every length
into mm, and the viewer says beside its own display unit what the file was.

Files written here by OCCT itself, a box of 25.4 x 50.8 x 10 mm: in a STEP
and an IGES in inches and in mm. Whatever the file's unit, the model comes in
mm (the box's size); the unit is said on the first read and from the disk
cache. A mesh has no unit to say (null).
"""
import pathlib

import pytest
import trimesh
from fastapi.testclient import TestClient

from app.main import app

BOX = (25.4, 50.8, 10.0)


def _box():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(*BOX).Shape()


def _step(path: pathlib.Path, unit: str) -> bytes:
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    w = STEPControl_Writer()  # first: it sets the write.step.* defaults
    old = Interface_Static.CVal_s("write.step.unit")
    Interface_Static.SetCVal_s("write.step.unit", unit)
    try:
        w.Transfer(_box(), STEPControl_AsIs)
        w.Write(str(path))
    finally:
        Interface_Static.SetCVal_s("write.step.unit", old)
    return path.read_bytes()


def _iges(path: pathlib.Path, unit: str) -> bytes:
    from OCP.IGESControl import IGESControl_Writer

    w = IGESControl_Writer(unit, 1)  # 1: a B-rep solid (one part, nothing to sew)
    w.AddShape(_box())
    w.ComputeModel()
    assert w.Write(str(path))
    return path.read_bytes()


@pytest.mark.parametrize(
    "kind, unit, want, text",
    [("step", "INCH", "in", b"'INCH'"), ("step", "MM", "mm", b".MILLI."), ("igs", "IN", "in", b"INCH"), ("igs", "MM", "mm", b"MM")],
)
def test_the_files_unit_is_said(tmp_path, kind, unit, want, text):
    client = TestClient(app)
    path = tmp_path / f"unit_{unit}.{kind}"
    data = (_step if kind == "step" else _iges)(path, unit)
    assert text in data, "the file is written in that unit"
    data += b"\n" * 7  # its own bytes: a first read, not the disk cache of another test
    for first in (True, False):  # the first read, then the disk cache (another name: not the same entry)
        r = client.post("/api/models", files={"file": (f"{'a' if first else 'b'}_{path.name}", data, "x")})
        assert r.status_code == 200, r.text
        meta = r.json()
        assert meta["cached"] is (not first), meta.get("cached")
        assert meta["fileUnit"] == want, meta.get("fileUnit")
        # read into mm whatever the file's unit
        assert meta["bbox"]["max"] == pytest.approx(BOX, abs=1e-3) and meta["bbox"]["min"] == pytest.approx((0, 0, 0), abs=1e-3), meta["bbox"]


def test_a_mesh_has_no_unit():
    client = TestClient(app)
    stl = trimesh.creation.box(extents=(1, 2, 3)).export(file_type="stl")
    r = client.post("/api/models", files={"file": ("unit_box.stl", stl, "x")})
    assert r.status_code == 200 and r.json().get("fileUnit") is None, r.json()
