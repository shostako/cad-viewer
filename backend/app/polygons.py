"""The faces of more than three corners in OBJ, PLY and OFF, cut into triangles
along their shape (#87).

trimesh cuts every such face as a fan from its first corner. That is right for a
convex face, and for any face whose every corner can be seen from the first
one, but when the first corner does not see them all, the fan reaches out of the
face and lays triangles over each other: the shape on the screen, the area and
the projected area (so the clamping force) come out wrong. (The volume stays
right: a flat face's triangles out of it cancel.)

So a face keeps its fan when the fan is right (every one of its triangles turns
the face's way, which is when the triangles cover the face once, without
gaps or overlaps), and is cut by ear clipping when it is not. The Web version
does the same in frontend/src/local/polygons.ts: the two are written to be one
procedure, step for step, so that both versions cut a face into the same
triangles (frontend/tests/local_mesh.test.ts compares them).

load_mesh keeps trimesh's own reading of a file and asks refit() only when
trimesh made more triangles than the file has faces (so there are faces of more
than three corners). refit() reads the file's faces itself (the same reading as
the Web version's meshload.ts) and makes the mesh again, from those, only when
one of the faces has a wrong fan. A file trimesh does not read at all (some of
faces of different corner counts) is read by read_mesh() the same way.
"""
from __future__ import annotations

import logging
import re
import struct

import numpy as np
import trimesh

log = logging.getLogger(__name__)

POLYGON_EXTS = {"obj", "ply", "off"}


# ---- one face -------------------------------------------------------------------

def triangulate(P, poly: list[int]) -> list[tuple[int, int, int]]:
    """The triangles of one face (corner indices into P, in the face's order).

    P: the positions, P[i] = (x, y, z). The triangles turn the face's way.
    """
    k = len(poly)
    if k < 3:
        return []
    if k == 3:
        return [(poly[0], poly[1], poly[2])]
    fan = _fan(poly)
    # the face's normal (Newell's method: also for a face not quite flat)
    nx = ny = nz = 0.0
    for i in range(k):
        p, q = P[poly[i]], P[poly[(i + 1) % k]]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    nn = nx * nx + ny * ny + nz * nz
    if nn == 0:
        return fan  # no area: nothing to cut along
    tol = 1e-9 * nn
    if all(_turn(P[a], P[b], P[c], nx, ny, nz) >= -tol for a, b, c in fan):
        return fan
    return _ear_clip(P, poly, nx, ny, nz)


def _fan(poly: list[int]) -> list[tuple[int, int, int]]:
    """trimesh's triangles of a face: a fan from its first corner"""
    return [(poly[0], poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)]


def _turn(a, b, c, nx: float, ny: float, nz: float) -> float:
    """(b - a) x (c - a), along the normal: > 0 when a b c turns the face's way"""
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return (uy * vz - uz * vy) * nx + (uz * vx - ux * vz) * ny + (ux * vy - uy * vx) * nz


def _ear_clip(P, poly: list[int], nx: float, ny: float, nz: float) -> list[tuple[int, int, int]]:
    """Ear clipping on the face seen along its normal's largest axis.

    A corner is an ear when it turns the face's way and no other corner that
    does not (only those can be inside: if a corner is inside a simple
    polygon's triangle, one of those is) lies in or on its triangle. If no
    corner is an ear (the face crosses itself), the rest is a fan. A face with
    a hole joined to the outside by a cut (the cut's ends twice, at the same
    places) is cut right too: 20,000 random ones were, in testing (#87).
    """
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    # drop the largest axis; the other two in cyclic order keep the turn's sign
    if ax >= ay and ax >= az:
        iu, iv, s = 1, 2, nx
    elif ay >= az:
        iu, iv, s = 2, 0, ny
    else:
        iu, iv, s = 0, 1, nz
    sign = 1.0 if s > 0 else -1.0
    eps = 1e-10 * abs(s)
    U = [P[i][iu] for i in poly]
    V = [P[i][iv] for i in poly]

    def cross(a: int, b: int, c: int) -> float:
        return sign * ((U[b] - U[a]) * (V[c] - V[a]) - (V[b] - V[a]) * (U[c] - U[a]))

    L = list(range(len(poly)))  # the corners left, by their place in poly
    out: list[tuple[int, int, int]] = []

    def is_ear(i: int) -> bool:
        m = len(L)
        a, b, c = L[(i - 1) % m], L[i], L[(i + 1) % m]
        if cross(a, b, c) <= eps:
            return False
        for j in range(m):
            p = L[j]
            if p in (a, b, c):
                continue
            if cross(L[(j - 1) % m], p, L[(j + 1) % m]) > eps:
                continue  # a corner that turns the face's way: not inside
            if cross(a, b, p) >= -eps and cross(b, c, p) >= -eps and cross(c, a, p) >= -eps:
                return False
        return True

    i = 0
    misses = 0
    while len(L) > 3:
        m = len(L)
        if is_ear(i):
            a, b, c = L[(i - 1) % m], L[i], L[(i + 1) % m]
            out.append((poly[a], poly[b], poly[c]))
            del L[i]
            # the corner before may have become an ear: look at it next
            i = (i - 1) % (m - 1)
            misses = 0
        else:
            i = (i + 1) % m
            misses += 1
            if misses >= m:
                # no ear: the face crosses itself; the rest as a fan
                out.extend((poly[L[0]], poly[L[j]], poly[L[j + 1]]) for j in range(1, len(L) - 1))
                return out
    out.append((poly[L[0]], poly[L[1]], poly[L[2]]))
    return out


# ---- the file's faces, read as the Web version reads them (meshload.ts) ----------

def read_polygons(data: bytes, ext: str) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    """the positions and the faces (corner indices) of an OBJ, PLY or OFF file"""
    if ext == "obj":
        return _read_obj(data.decode("utf-8", errors="replace"))
    if ext == "off":
        return _read_off(data.decode("utf-8", errors="replace"))
    if ext == "ply":
        return _read_ply(data)
    raise ValueError(f"not a polygon format: .{ext}")


def _read_obj(s: str):
    P: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for raw in re.split(r"\r?\n", s):
        line = raw.strip()
        if line.startswith("v "):
            w = line.split()
            P.append((float(w[1]), float(w[2]), float(w[3])))
        elif line.startswith("f "):
            nv = len(P)
            vs = []
            for tok in line.split()[1:]:
                i = int(tok.split("/")[0])
                vs.append(nv + i if i < 0 else i - 1)
            faces.append(vs)
    return P, faces


def _read_off(s: str):
    lines = [re.sub(r"#.*", "", ln).strip() for ln in re.split(r"\r?\n", s)]
    tokens = " ".join(ln for ln in lines if ln).split()
    at = 0
    if re.fullmatch(r"[A-Z]*OFF", tokens[0]):
        at += 1
    nv, nf = int(tokens[at]), int(tokens[at + 1])
    at += 3  # and the edge count
    vals = [float(t) for t in tokens[at : at + 3 * nv]]
    P = [(vals[3 * i], vals[3 * i + 1], vals[3 * i + 2]) for i in range(nv)]
    at += 3 * nv
    faces = []
    for _ in range(nf):
        k = int(tokens[at])
        faces.append([int(t) for t in tokens[at + 1 : at + 1 + k]])
        at += 1 + k
    return P, faces


_PLY_TYPES = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}


def _read_ply(data: bytes):
    head = data[:65536].decode("latin1")
    end = head.find("end_header")
    if not head.startswith("ply") or end < 0:
        raise ValueError("not a PLY file")
    body_at = head.index("\n", end) + 1
    fmt = "ascii"
    elements: list[tuple[str, int, list[tuple[str, str, str | None]]]] = []
    for line in re.split(r"\r?\n", head[:end]):
        w = line.split()
        if not w:
            continue
        if w[0] == "format":
            fmt = w[1]
        elif w[0] == "element":
            elements.append((w[1], int(w[2]), []))
        elif w[0] == "property" and elements:
            if w[1] == "list":
                elements[-1][2].append((w[4], w[3], w[2]))
            else:
                elements[-1][2].append((w[2], w[1], None))
    P: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []

    def take(el: str, values: dict) -> None:
        if el == "vertex":
            P.append((float(values["x"]), float(values["y"]), float(values["z"])))
        elif el == "face":
            vs = values.get("vertex_indices", values.get("vertex_index"))
            if vs is not None:
                faces.append([int(v) for v in vs])

    if fmt == "ascii":
        tokens = data[body_at:].decode("utf-8", errors="replace").split()
        at = 0
        for name, count, props in elements:
            for _ in range(count):
                values: dict = {}
                for pname, _ptype, ctype in props:
                    if ctype:
                        k = int(float(tokens[at]))
                        values[pname] = [float(t) for t in tokens[at + 1 : at + 1 + k]]
                        at += 1 + k
                    else:
                        values[pname] = float(tokens[at])
                        at += 1
                take(name, values)
    else:
        order = "<" if fmt == "binary_little_endian" else ">"
        at = body_at

        def read(t: str):
            nonlocal at
            code = _PLY_TYPES.get(t)
            if code is None:
                raise ValueError(f"PLY: unknown type {t}")
            (v,) = struct.unpack_from(order + code, data, at)
            at += struct.calcsize(code)
            return v

        for name, count, props in elements:
            for _ in range(count):
                values = {}
                for pname, ptype, ctype in props:
                    if ctype:
                        k = read(ctype)
                        values[pname] = [read(ptype) for _ in range(k)]
                    else:
                        values[pname] = read(ptype)
                take(name, values)
    return P, faces


# ---- the mesh again, when a face's fan is wrong ----------------------------------

def _file_faces(data: bytes, ext: str) -> int | None:
    """how many faces the file has, cheaply (without reading them)"""
    if ext == "obj":
        return len(re.findall(rb"^[ \t]*f[ \t]", data, flags=re.MULTILINE))
    if ext == "ply":
        m = re.search(rb"^element[ \t]+face[ \t]+(\d+)", data[:65536], flags=re.MULTILINE)
        return int(m.group(1)) if m else None
    if ext == "off":
        text = re.sub(rb"#[^\n]*", b"", data[:4096])
        w = text.split()
        if w and re.fullmatch(rb"[A-Z]*OFF", w[0]):
            w = w[1:]
        return int(w[1]) if len(w) > 1 else None
    return None


def _cut(P, polys: list[list[int]]) -> tuple[list[tuple[int, int, int]], bool]:
    """every face's triangles, and whether a face's fan was wrong"""
    tris: list[tuple[int, int, int]] = []
    fixed = False
    n = len(P)
    for poly in polys:
        if any(not 0 <= i < n for i in poly):
            raise ValueError("a face refers to a vertex the file does not have")
        t = triangulate(P, poly)
        if len(poly) > 3 and t != _fan(poly):
            fixed = True
        tris.extend(t)
    return tris, fixed


def _mesh(P, tris) -> trimesh.Trimesh:
    # as trimesh.load makes it (process=True: vertices at one place merged)
    return trimesh.Trimesh(vertices=np.asarray(P, dtype=np.float64).reshape(-1, 3), faces=np.asarray(tris, dtype=np.int64).reshape(-1, 3))


def read_mesh(data: bytes, ext: str) -> trimesh.Trimesh | None:
    """The mesh of a file that trimesh does not read, read as the Web version
    reads it; None when this cannot read it either (or it has no triangles).

    trimesh 4.12 fails on an OFF whose faces have different numbers of corners,
    one of them more than four (its fan is made of the corner indices as text),
    and on a binary PLY whose faces have different numbers of corners (it reads
    every face as long as the first). meshload.ts reads both.
    """
    if ext not in POLYGON_EXTS:
        return None
    try:
        P, polys = read_polygons(data, ext)
        tris, _ = _cut(P, polys)
    except Exception as e:
        log.warning("could not read the faces of a .%s file: %s", ext, e)
        return None
    return _mesh(P, tris) if tris else None


def refit(data: bytes, ext: str, triangles: int) -> trimesh.Trimesh | None:
    """The mesh made again from the file's faces, cut along their shape; None
    when trimesh's own (a fan for every face) is already right.

    triangles: how many triangles trimesh made of the file.
    """
    if ext not in POLYGON_EXTS:
        return None
    faces = _file_faces(data, ext)
    if faces is None or triangles <= faces:
        return None  # every face a triangle
    try:
        P, polys = read_polygons(data, ext)
        tris, fixed = _cut(P, polys)
    except Exception as e:  # a file trimesh read and this does not: keep trimesh's
        log.warning("could not read the faces of a .%s file again: %s", ext, e)
        return None
    return _mesh(P, tris) if fixed else None
