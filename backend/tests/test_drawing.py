"""Drawing (DXF) route tests against known-truth plate_drawing.dxf.

Geometry: 200x100 outline, holes r=10 at (50,50) and (150,50), centerline y=50.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

DXF = pathlib.Path(__file__).parent.parent.parent / "testdata" / "plate_drawing.dxf"

pytestmark = pytest.mark.skipif(not DXF.exists(), reason="run testdata/make_dxf.py first")


@pytest.fixture(scope="module")
def model():
    client = TestClient(app)
    r = client.post("/api/models", files={"file": ("plate_drawing.dxf", DXF.read_bytes(), "x")})
    assert r.status_code == 200, r.text
    return client, r.json()


def test_drawing_meta(model):
    _, meta = model
    assert meta["format"] == "drawing"
    assert meta["bbox2d"]["min"] == [0.0, 0.0]
    assert meta["bbox2d"]["max"] == [200.0, 100.0]


def test_snap_points(model):
    _, meta = model
    snaps = meta["snapPoints"]
    dxf_pts = {tuple(s["dxf"]) for s in snaps}
    # polyline corners
    for corner in [(0, 0), (200, 0), (200, 100), (0, 100)]:
        assert corner in dxf_pts
    # hole centers
    assert (50, 50) in dxf_pts
    assert (150, 50) in dxf_pts
    # svg coord mapping follows the reported svgScale, y-flipped
    sx, sy = meta["svgScale"]
    by_dxf = {tuple(s["dxf"]): s["svg"] for s in snaps}
    assert by_dxf[(0, 0)] == [0.0, pytest.approx(100 * sy, abs=0.2)]
    assert by_dxf[(200, 100)] == [pytest.approx(200 * sx, abs=0.2), 0.0]
    assert by_dxf[(50, 50)] == [pytest.approx(50 * sx, abs=0.2), pytest.approx(50 * sy, abs=0.2)]


def test_drawing_svg(model):
    client, meta = model
    r = client.get(f"/api/models/{meta['id']}/drawing.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")
    # viewBox is widened 1% per side (boundary strokes must not clip);
    # snap svg coords still live in the unpadded content space
    sx, sy = meta["svgScale"]
    import re

    m = re.search(r'viewBox="(-?[\d.]+) (-?[\d.]+) ([\d.]+) ([\d.]+)"', r.text)
    assert m, "padded viewBox missing"
    vx, vy, vw, vh = (float(g) for g in m.groups())
    assert vx < 0 and vy < 0
    assert vw + 2 * vx == pytest.approx(200 * sx, rel=1e-6)
    assert vh + 2 * vy == pytest.approx(100 * sy, rel=1e-6)


def test_dwg_without_oda(model):
    client, _ = model
    from app.drawing import find_oda

    if find_oda():
        pytest.skip("ODA installed; guidance path not applicable")
    r = client.post("/api/models", files={"file": ("a.dwg", b"AC1027garbage", "x")})
    assert r.status_code == 422
    assert "ODA File Converter" in r.json()["detail"]


def test_thickness_rejected_for_drawing(model):
    """Regression: drawings have no mesh_blob; thickness must 422, not 500."""
    client, meta = model
    r = client.get(f"/api/models/{meta['id']}/thickness.bin")
    assert r.status_code == 422, (r.status_code, r.text[:200])


def test_snap_points_inside_blocks(tmp_path):
    """Regression: INSERT block contents are drawn in the SVG but their
    endpoints/centers were not snappable (only the insertion point was)."""
    import ezdxf

    doc = ezdxf.new()
    blk = doc.blocks.new(name="HOLE")
    blk.add_circle((0, 0), radius=5)
    blk.add_line((-5, 0), (5, 0))
    msp = doc.modelspace()
    msp.add_line((0, 0), (200, 0))  # base geometry so the bbox is sane
    # two inserts, one translated + scaled
    msp.add_blockref("HOLE", (50, 40))
    msp.add_blockref("HOLE", (150, 40), dxfattribs={"xscale": 2, "yscale": 2})
    path = tmp_path / "block_drawing.dxf"
    doc.saveas(path)

    client = TestClient(app)
    r = client.post("/api/models", files={"file": ("block_drawing.dxf", path.read_bytes(), "x")})
    assert r.status_code == 200, r.text
    snaps = r.json()["snapPoints"]
    pts = {(round(s["dxf"][0], 3), round(s["dxf"][1], 3)) for s in snaps}

    # circle center inside insert #1 (translated)
    assert (50.0, 40.0) in pts
    # circle quadrant of insert #1: (50+5, 40)
    assert (55.0, 40.0) in pts
    # scaled insert #2: quadrant at 150 + 5*2 = 160
    assert (160.0, 40.0) in pts
    # line endpoint inside scaled insert: 150 - 5*2 = 140
    assert (140.0, 40.0) in pts

