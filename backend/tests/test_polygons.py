"""Faces of more than three corners in OBJ, PLY and OFF, cut along their shape (#87).

The answers come from how the shapes are made: a prism over a polygon has the
polygon's area times its height for volume, and the caps and the sides for
area. The polygons start at a corner that does not see every other one, so a
fan from it (what trimesh makes) reaches out of the face.
"""
from __future__ import annotations

import io
import struct

import pytest
import trimesh

from app import polygons
from app.loaders import load_mesh

# an L of area 64, from a corner that does not see the far end of the L: the
# fan from there is wrong
L = [(10, 4), (4, 4), (4, 10), (0, 10), (0, 0), (10, 0)]
# a comb of four slots (area 9 x 5 - 4 x 4), from a slot's bottom corner
COMB = [(1, 1), (1, 5), (0, 5), (0, 0), (9, 0), (9, 5), (8, 5), (8, 1), (7, 1), (7, 5), (6, 5),
        (6, 1), (5, 1), (5, 5), (4, 5), (4, 1), (3, 1), (3, 5), (2, 5), (2, 1)]
# a 10 x 10 square with a 4 x 4 hole, the hole joined to the outside by a cut
# (its two ends twice, at the same places)
BRIDGED = [(0, 5), (0, 0), (10, 0), (10, 10), (0, 10), (0, 5), (3, 5), (3, 7), (7, 7), (7, 3), (3, 3), (3, 5)]
# the same L from its first outer corner: concave, but the fan is right
STAR = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]


def signed_area(P, tris) -> float:
    s = 0.0
    for a, b, c in tris:
        s += ((P[b][0] - P[a][0]) * (P[c][1] - P[a][1]) - (P[b][1] - P[a][1]) * (P[c][0] - P[a][0])) / 2
    return s


def flat(poly2d):
    return [(float(x), float(y), 0.0) for x, y in poly2d]


@pytest.mark.parametrize("poly2d, area", [(L, 64), (COMB, 29), (BRIDGED, 84), (STAR, 64)])
@pytest.mark.parametrize("clockwise", [False, True])
def test_a_face_is_cut_along_its_shape(poly2d, area, clockwise):
    P = flat(poly2d[::-1] if clockwise else poly2d)
    tris = polygons.triangulate(P, list(range(len(P))))
    assert len(tris) == len(P) - 2
    sign = -1 if clockwise else 1
    # every triangle turns the face's way and they add up to the face: no
    # triangle out of the face, none over another
    for t in tris:
        assert sign * signed_area(P, [t]) > 0, t
    assert signed_area(P, tris) == pytest.approx(sign * area, rel=1e-12)


def test_a_right_fan_is_kept():
    P = flat(STAR)
    assert polygons.triangulate(P, list(range(6))) == [(0, i, i + 1) for i in range(1, 5)]
    # a convex face, and one not quite flat (a corner lifted)
    sq = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 5.0, 0.3), (0.0, 5.0, 0.0)]
    assert polygons.triangulate(sq, [0, 1, 2, 3]) == [(0, 1, 2), (0, 2, 3)]


def test_a_face_that_crosses_itself_is_a_fan():
    P = flat([(0, 0), (4, 4), (4, 0), (0, 4)])
    assert polygons.triangulate(P, [0, 1, 2, 3]) == [(0, 1, 2), (0, 2, 3)]


def test_a_face_off_the_plane():
    # the L tilted out of the xy plane (so the largest axis of its normal is not z)
    import math

    c, s = math.cos(1.1), math.sin(1.1)
    P = [(x, y * c, y * s) for x, y in L]
    tris = polygons.triangulate(P, list(range(6)))
    area = 0.0
    for a, b, cc in tris:
        u = [P[b][k] - P[a][k] for k in range(3)]
        v = [P[cc][k] - P[a][k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        assert n[2] > 0  # turns the face's way (its normal has +z, as the untilted L's)
        area += math.sqrt(sum(x * x for x in n)) / 2
    assert area == pytest.approx(64, rel=1e-12)


# ---- files ----------------------------------------------------------------------

def prism(poly2d, h):
    """vertices and faces (outward) of a prism over a counter-clockwise polygon"""
    n = len(poly2d)
    V = [(float(x), float(y), 0.0) for x, y in poly2d] + [(float(x), float(y), float(h)) for x, y in poly2d]
    # both caps from the polygon's first corner (the bottom one turned over)
    F = [[0, *range(n - 1, 0, -1)], list(range(n, 2 * n))]
    F += [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    return V, F


def obj(V, F) -> bytes:
    return ("".join("v %r %r %r\n" % v for v in V) + "".join("f " + " ".join(str(i + 1) for i in f) + "\n" for f in F)).encode()


def off(V, F) -> bytes:
    body = "".join("%r %r %r\n" % v for v in V) + "".join("%d %s\n" % (len(f), " ".join(map(str, f))) for f in F)
    return ("OFF\n# a comment\n%d %d 0\n" % (len(V), len(F)) + body).encode()


PLY_HEAD = ("ply\nformat {fmt} 1.0\nelement vertex {nv}\nproperty double x\nproperty double y\nproperty double z\n"
            "element face {nf}\nproperty list uchar int vertex_indices\nend_header\n")


def ply_text(V, F) -> bytes:
    body = "".join("%r %r %r\n" % v for v in V) + "".join("%d %s\n" % (len(f), " ".join(map(str, f))) for f in F)
    return (PLY_HEAD.format(fmt="ascii", nv=len(V), nf=len(F)) + body).encode()


def ply_binary(V, F) -> bytes:
    head = PLY_HEAD.format(fmt="binary_little_endian", nv=len(V), nf=len(F)).encode()
    return head + b"".join(struct.pack("<3d", *v) for v in V) + b"".join(struct.pack("<B%di" % len(f), len(f), *f) for f in F)


WRITERS = {"obj": obj, "off": off, "ply": ply_text, "binary.ply": ply_binary}


def perimeter(poly2d) -> float:
    n = len(poly2d)
    return sum(((poly2d[i][0] - poly2d[(i + 1) % n][0]) ** 2 + (poly2d[i][1] - poly2d[(i + 1) % n][1]) ** 2) ** 0.5 for i in range(n))


@pytest.mark.parametrize("fmt", list(WRITERS))
@pytest.mark.parametrize("poly2d, area", [(L, 64), (COMB, 29)])
def test_a_prism_over_a_concave_face(fmt, poly2d, area):
    V, F = prism(poly2d, 3)
    m = load_mesh(WRITERS[fmt](V, F), "part." + fmt)
    assert m.volume == pytest.approx(3 * area, rel=1e-12)
    assert m.area == pytest.approx(2 * area + 3 * perimeter(poly2d), rel=1e-12)
    # the caps' triangles turn as the caps do (out of the part)
    for f, n in zip(m.faces, m.face_normals):
        z = m.vertices[f][:, 2]
        if (z == 0).all():
            assert n[2] == pytest.approx(-1)
        elif (z == 3).all():
            assert n[2] == pytest.approx(1)


@pytest.mark.parametrize("fmt", list(WRITERS))
def test_a_prism_over_a_face_with_a_hole(fmt):
    # the cap is one face with its hole joined by a cut; the hole's walls are
    # separate quads (inward), and there are no walls along the cut
    n = len(BRIDGED)
    V = [(float(x), float(y), 0.0) for x, y in BRIDGED] + [(float(x), float(y), 2.0) for x, y in BRIDGED]
    F = [[0, *range(n - 1, 0, -1)], list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        if {i, j} in ({5, 6}, {11, 0}):
            continue  # along the cut
        F.append([i, j, n + j, n + i])
    m = load_mesh(WRITERS[fmt](V, F), "part." + fmt)
    assert m.volume == pytest.approx(2 * 84, rel=1e-12)


@pytest.mark.parametrize("fmt", list(WRITERS))
def test_right_fans_are_trimeshs(fmt):
    """A file whose faces' fans are all right is trimesh's mesh as it was (when
    trimesh reads the file: it does not read some, below)."""
    V, F = prism(STAR, 3)
    data = WRITERS[fmt](V, F)
    try:
        before = trimesh.load(io.BytesIO(data), file_type="ply" if fmt.endswith("ply") else fmt)
    except Exception:
        pytest.skip("trimesh does not read this file")
    assert polygons.refit(data, fmt.split(".")[-1], len(before.faces)) is None
    m = load_mesh(data, "part." + fmt)
    assert m.volume == pytest.approx(3 * 64, rel=1e-12)


@pytest.mark.parametrize("fmt", ["off", "binary.ply"])
def test_files_trimesh_does_not_read(fmt):
    """trimesh 4.12 does not read an OFF of faces of different corner counts
    (one of more than four), nor a binary PLY of different corner counts: they
    are read as the Web version reads them. If trimesh comes to read them, this
    says so (the fallback may then go)."""
    V, F = prism(STAR, 3)
    data = WRITERS[fmt](V, F)
    with pytest.raises(Exception):
        trimesh.load(io.BytesIO(data), file_type="ply" if fmt.endswith("ply") else fmt)
    assert load_mesh(data, "part." + fmt).volume == pytest.approx(3 * 64, rel=1e-12)


def test_triangles_only_are_left_alone():
    # every face a triangle: the faces are not read again (the cheap count says so)
    V, F = prism(L, 3)
    tris = [t for f in F for t in polygons.triangulate(V, f)]
    data = obj(V, tris)
    assert polygons._file_faces(data, "obj") == len(tris)
    assert polygons.refit(data, "obj", len(tris)) is None


def test_a_file_this_cannot_read_keeps_trimeshs_error():
    data = b"not an off file at all"
    with pytest.raises(Exception) as theirs:
        trimesh.load(io.BytesIO(data), file_type="off")
    with pytest.raises(Exception) as ours:
        load_mesh(data, "x.off")
    assert type(ours.value) is type(theirs.value) and str(ours.value) == str(theirs.value)
