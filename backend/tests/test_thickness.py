"""Thickness tests against known geometry."""
import json
import struct

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from app.main import app
from app.thickness import vertex_thickness


def test_plate_thickness_direct():
    """10x10x2 box: flat-shaded (per-face normals) vertices measure exactly 2 / 10."""
    box = trimesh.creation.box(extents=(10, 10, 2))
    # facet-shaded copy: duplicate vertices per face so normals are face normals
    box = box.copy()
    box.unmerge_vertices()
    t = vertex_thickness(
        np.asarray(box.vertices, dtype=np.float32),
        np.asarray(box.vertex_normals, dtype=np.float32),
        np.asarray(box.faces, dtype=np.uint32),
    )
    finite = t[np.isfinite(t)]
    assert len(finite) == len(t)
    # every ray crosses either the 2mm or the 10mm dimension
    assert set(np.round(np.unique(finite), 3)) <= {2.0, 10.0}
    assert (np.round(finite, 3) == 2.0).sum() > 0


def test_thickness_endpoint():
    client = TestClient(app)
    box = trimesh.creation.box(extents=(10, 10, 2))
    stl = box.export(file_type="stl")
    r = client.post("/api/models", files={"file": ("plate.stl", stl, "x")})
    mid = r.json()["id"]

    r = client.get(f"/api/models/{mid}/thickness.bin")
    assert r.status_code == 200
    blob = r.content
    (hlen,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + hlen])
    d = header["buffers"]["p0:thickness"]
    t = np.frombuffer(blob, dtype=np.float32, count=d["count"], offset=4 + hlen + d["offset"])
    assert d["count"] == r0_vertex_count(client, mid)
    vals = set(np.round(t[t > 0], 3))
    assert vals <= {2.0, 10.0}


def r0_vertex_count(client, mid):
    meta = [m for m in client.get("/api/models").json() if m["id"] == mid][0]
    return meta["vertexCount"]


# ---------------------------------------------------------------- rolling ball


def _facet_arrays(mesh):
    import trimesh.graph

    m = trimesh.graph.smooth_shade(mesh, angle=np.radians(30))
    return (
        np.asarray(m.vertices, dtype=np.float32),
        np.asarray(m.vertex_normals, dtype=np.float32),
        np.asarray(m.faces, dtype=np.uint32),
    )


def test_ball_equals_ray_on_parallel_plate():
    """Parallel walls: tangent sphere diameter == ray distance == 2."""
    from app.thickness import vertex_thickness, vertex_thickness_ball

    plate = trimesh.creation.box(extents=(10, 10, 2)).subdivide().subdivide()
    pos, nrm, idx = _facet_arrays(plate)
    t_ray = vertex_thickness(pos, nrm, idx)
    t_ball = vertex_thickness_ball(pos, nrm, idx)

    # interior top/bottom face vertices (away from the sides)
    interior = (
        (np.abs(np.abs(pos[:, 2]) - 1.0) < 1e-6)
        & (np.abs(pos[:, 0]) < 4.0)
        & (np.abs(pos[:, 1]) < 4.0)
    )
    assert interior.sum() > 0
    assert np.allclose(t_ray[interior], 2.0, atol=1e-3)
    assert np.allclose(t_ball[interior], 2.0, atol=0.02)


def test_ball_correct_on_wedge():
    """Wedge (slanted wall): ray overestimates, ball matches theory.

    Wedge angle θ with cosθ = 10/√164 (rise 8 over run 10):
      ray  = z / cosθ          (perpendicular chord to the bottom)
      ball = 2z / (1 + cosθ)   (max tangent sphere diameter)
    """
    from app.thickness import vertex_thickness, vertex_thickness_ball

    verts = [(0, 0, 0), (10, 0, 0), (10, 0, 8), (0, 10, 0), (10, 10, 0), (10, 10, 8)]
    faces = [
        (0, 1, 2),
        (3, 5, 4),
        (0, 3, 1),
        (1, 3, 4),  # bottom
        (0, 2, 3),
        (2, 5, 3),  # slanted
        (1, 4, 2),
        (2, 4, 5),  # back
    ]
    wedge = trimesh.Trimesh(vertices=verts, faces=faces)
    wedge.fix_normals()
    wedge = wedge.subdivide().subdivide().subdivide()
    pos, nrm, idx = _facet_arrays(wedge)
    t_ray = vertex_thickness(pos, nrm, idx)
    t_ball = vertex_thickness_ball(pos, nrm, idx)

    cos_t = 10.0 / np.sqrt(164.0)
    slant_n = np.array([-8.0, 0.0, 10.0]) / np.sqrt(164.0)
    # interior vertices on the slanted face; z capped so the inward ray and
    # the tangent sphere stay clear of the back wall (theory assumes only
    # slant + bottom are involved — valid for z <= ~4.8 on this wedge)
    on_slant = (nrm @ slant_n) > 0.999
    interior = (
        on_slant
        & (pos[:, 2] > 2.0)
        & (pos[:, 2] < 4.5)
        & (pos[:, 1] > 2.0)
        & (pos[:, 1] < 8.0)
    )
    assert interior.sum() > 0

    z = pos[interior, 2].astype(np.float64)
    expect_ray = z / cos_t
    expect_ball = 2.0 * z / (1.0 + cos_t)

    finite = np.isfinite(t_ray[interior])
    assert np.allclose(t_ray[interior][finite], expect_ray[finite], rtol=0.03)
    assert np.allclose(t_ball[interior][finite], expect_ball[finite], rtol=0.03)
    # ball must be strictly below ray on the slanted wall (the whole point)
    assert (t_ball[interior][finite] < t_ray[interior][finite] * 0.95).all()


def test_thickness_endpoint_ball_method():
    client = TestClient(app)
    box = trimesh.creation.box(extents=(10, 10, 2))
    stl = box.export(file_type="stl")
    mid = client.post("/api/models", files={"file": ("p.stl", stl, "x")}).json()["id"]

    r = client.get(f"/api/models/{mid}/thickness.bin?method=ball")
    assert r.status_code == 200
    assert client.get(f"/api/models/{mid}/thickness.bin?method=nope").status_code == 422


def test_ball_gives_no_value_where_no_sphere_fits():
    """On a sharp edge or at a corner no tangent sphere fits inside: no value
    (0, shown as データなし), not a sliver the width of the search's
    tolerance (that one showed as a wall 0.0015 mm thin, issue #63)."""
    from app.thickness import vertex_thickness_ball

    def no_value(t):
        # 0 from the sphere, +inf from a ray that found no wall (the endpoint sends both as 0)
        return (t == 0) | ~np.isfinite(t)

    # a thin plate whose display mesh has corners only
    pos, nrm, idx = _facet_arrays(trimesh.creation.box(extents=(20, 20, 1.2)))
    t = vertex_thickness_ball(pos, nrm, idx)
    assert np.all(no_value(t)), t
    # a finer one: no value on the edges of its top, 1 mm inside them
    plate = trimesh.creation.box(extents=(40, 40, 1)).subdivide().subdivide().subdivide()
    pos, nrm, idx = _facet_arrays(plate)
    t = vertex_thickness_ball(pos, nrm, idx)
    top = np.abs(pos[:, 2] - 0.5) < 1e-6
    rim = top & ((np.abs(np.abs(pos[:, 0]) - 20) < 1e-6) | (np.abs(np.abs(pos[:, 1]) - 20) < 1e-6))
    inside = top & (np.abs(pos[:, 0]) < 15) & (np.abs(pos[:, 1]) < 15)
    assert rim.sum() > 0 and inside.sum() > 0
    assert np.all(no_value(t[rim])), t[rim]
    assert np.allclose(t[inside], 1.0, atol=0.02), t[inside]


def test_ball_gives_no_value_on_a_shallow_crease():
    """A sphere at a vertex on a shallow convex crease (the ridge of a roof
    whose two faces are 40° apart) cuts the other face next to it at any size,
    so none fits there: no value. A tolerance on the distance lets it 'fit'
    up to tol / (1 - cos 40°), several times the tolerance (Codex on #64), on
    a body long enough for the search to reach that size. The roof away from
    the ridge measures through the body."""
    from app.thickness import vertex_thickness_ball

    h = 10 + 20 * np.tan(np.radians(20))  # each roof face 20° from level
    pts = [(x, y, z) for y in (0, 200) for x, z in ((0, 0), (40, 0), (40, 10), (20, h), (0, 10))]
    house = trimesh.convex.convex_hull(np.array(pts, dtype=float)).subdivide().subdivide().subdivide()
    pos, nrm, idx = _facet_arrays(house)
    t = vertex_thickness_ball(pos, nrm, idx)
    ridge = (np.abs(pos[:, 0] - 20) < 1e-6) & (np.abs(pos[:, 2] - h) < 1e-6) & (pos[:, 1] > 1) & (pos[:, 1] < 199)
    roof = (pos[:, 0] > 5) & (pos[:, 0] < 15) & (pos[:, 1] > 20) & (pos[:, 1] < 180) & (pos[:, 2] > 10.5)
    assert ridge.sum() > 0 and roof.sum() > 0
    assert np.all((t[ridge] == 0) | ~np.isfinite(t[ridge])), t[ridge]
    assert np.all(t[roof] > 1), t[roof]


def _ringed_cylinder(r, h, sections=32, rings=10):
    """a closed cylinder whose side has rings of vertices on the circle all the way up"""
    verts, faces = [], []
    for k in range(rings + 1):
        z = -h / 2 + h * k / rings
        verts += [(r * np.cos(2 * np.pi * i / sections), r * np.sin(2 * np.pi * i / sections), z) for i in range(sections)]
    bottom, top = len(verts), len(verts) + 1
    verts += [(0, 0, -h / 2), (0, 0, h / 2)]
    for k in range(rings):
        for i in range(sections):
            a, b = k * sections + i, k * sections + (i + 1) % sections
            faces += [(a, b, b + sections), (a, b + sections, a + sections)]
    for i in range(sections):
        faces += [(bottom, (i + 1) % sections, i), (top, rings * sections + i, rings * sections + (i + 1) % sections)]
    m = trimesh.Trimesh(vertices=verts, faces=faces)
    m.fix_normals()
    return m


def test_ball_gives_no_false_thin_value_on_a_cylinder():
    """The side of a cylinder (r 5) in 32 flat strips, its vertices on the
    circle: a sphere tangent at a vertex cuts the strips next to it by
    t (1 - cos 5.6°), so the tolerance used to stop it at about 0.1 mm, a wall
    that is not there. Each side vertex has either no value or about the
    diameter (#63)."""
    from app.thickness import vertex_thickness_ball

    pos, nrm, idx = _facet_arrays(_ringed_cylinder(5, 20))
    t = vertex_thickness_ball(pos, nrm, idx)
    side = (np.abs(nrm[:, 2]) < 0.1) & (np.abs(pos[:, 2]) < 9)
    assert side.sum() > 0
    ok = (t[side] == 0) | ~np.isfinite(t[side]) | (t[side] > 0.9 * 10)
    assert np.all(ok), t[side][~ok]
