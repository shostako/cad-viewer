"""The backend's answers for files, for comparing the Web version's engine
(frontend/src/local/) with them: frontend/tests/*.test.ts run this.

    backend/.venv/bin/python scripts/engine_golden.py FILE...
    backend/.venv/bin/python scripts/engine_golden.py --routes FILE...   (thickness, 厚肉, projected area)

Prints JSON: per file, what POST /api/models says (vertexCount, triangleCount,
bbox) and GET /properties, or the error. The same code as the routes
(loaders.load_mesh, meshpack.pack_trimesh, properties.mesh_properties), without
the server.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402

from app import measure, properties  # noqa: E402
from app.loaders import classify, load_mesh  # noqa: E402
from app.meshpack import pack_parts, pack_trimesh  # noqa: E402
from app.tessellation import load_brep  # noqa: E402


def _centre_of(shape) -> list[float]:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    x0, y0, z0, x1, y1, z1 = box.Get()
    return [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]


def measures(meshes) -> list[dict]:
    """measurement requests over the whole model and the backend's answers
    (measure.run, as POST /measure; an error as its 422 detail)"""
    reqs: list[dict] = []
    for m in meshes:
        pid = m.part.part_id
        ref = lambda kind, i: {"partId": pid, "kind": kind, "id": i}  # noqa: E731
        nf, ne, nv = m.face_map.Extent(), m.edge_map.Extent(), m.vertex_map.Extent()
        for f in range(1, nf + 1):
            reqs.append({"type": "face_info", "ref": ref("face", f), "near": _centre_of(m.face_map.FindKey(f))})
        for e in range(1, ne + 1):
            reqs.append({"type": "edge_info", "ref": ref("edge", e), "near": _centre_of(m.edge_map.FindKey(e))})
        for v in range(1, nv + 1):
            reqs.append({"type": "vertex_info", "ref": ref("vertex", v)})
        for f in range(2, nf + 1):
            reqs.append({"type": "distance", "a": ref("face", 1), "b": ref("face", f),
                         "nearA": _centre_of(m.face_map.FindKey(1)), "nearB": _centre_of(m.face_map.FindKey(f))})
            reqs.append({"type": "distance", "a": ref("face", f), "b": ref("face", 1), "mode": "centre",
                         "nearA": _centre_of(m.face_map.FindKey(f))})
        for a in range(1, min(ne, 5) + 1):
            for b in range(1, min(ne, 5) + 1):
                reqs.append({"type": "distance", "a": ref("edge", a), "b": ref("edge", b), "mode": "max"})
                reqs.append({"type": "distance", "a": ref("edge", a), "b": ref("edge", b), "mode": "centre"})
        for e in range(1, min(ne, 3) + 1):
            for f in range(1, nf + 1):
                # a straight edge and a plane: their angle (90 less the angle to the normal)
                reqs.append({"type": "distance", "a": ref("edge", e), "b": ref("face", f),
                             "nearA": _centre_of(m.edge_map.FindKey(e)), "nearB": _centre_of(m.face_map.FindKey(f))})
        if nv >= 1:
            for f in range(1, nf + 1):
                # a point and an axis or a centre
                reqs.append({"type": "distance", "a": ref("vertex", 1), "b": ref("face", f), "mode": "centre"})
        if nv >= 1 and ne >= 1:
            reqs.append({"type": "distance", "a": ref("vertex", 1), "b": ref("edge", ne), "mode": "max"})
            reqs.append({"type": "distance", "a": ref("vertex", 1), "b": ref("edge", ne)})
        if nf >= 1:
            reqs.append({"type": "distance", "a": {"kind": "point", "xyz": [1.5, -2.5, 3.5]}, "b": ref("face", nf)})
    small = [m for m in meshes if m.face_map.Extent() <= 6]
    for i, ma in enumerate(small):
        for mb in small[i + 1:]:
            for fa in range(1, ma.face_map.Extent() + 1):
                for fb in range(1, mb.face_map.Extent() + 1):
                    # two parts' faces' centres: parallel axes, crossed ones, a point and an axis
                    reqs.append({"type": "distance", "mode": "centre",
                                 "a": {"partId": ma.part.part_id, "kind": "face", "id": fa},
                                 "b": {"partId": mb.part.part_id, "kind": "face", "id": fb},
                                 "nearA": _centre_of(ma.face_map.FindKey(fa))})
    if len(meshes) >= 2:
        a, b = meshes[0].part.part_id, meshes[-1].part.part_id
        reqs.append({"type": "distance", "a": {"partId": a, "kind": "part", "id": 0}, "b": {"partId": b, "kind": "part", "id": 0}})
        reqs.append({"type": "distance", "a": {"partId": a, "kind": "part", "id": 0}, "b": {"partId": b, "kind": "face", "id": 1}, "mode": "centre"})
        reqs.append({"type": "distance", "a": {"partId": a, "kind": "face", "id": 1}, "b": {"partId": b, "kind": "face", "id": 1}})
    # the errors, worded as the backend words them
    reqs += [
        {"type": "face_info", "ref": {"partId": 0, "kind": "face", "id": 9999}},
        {"type": "face_info", "ref": {"partId": 99, "kind": "face", "id": 1}},
        {"type": "face_info", "ref": {"kind": "face", "id": 1}},
        {"type": "vertex_info", "ref": {"kind": "point", "xyz": [0, 0, 0]}},
        {"type": "distance", "a": {"partId": 0, "kind": "face", "id": 1}, "b": {"partId": 0, "kind": "face", "id": 1}, "mode": "far"},
        {"type": "face_info", "ref": {"partId": 0, "kind": "face", "id": 1}, "near": [0, 0]},
        {"type": "nothing"},
    ]
    out = []
    for r in reqs:
        try:
            out.append({"request": r, "answer": measure.run(r, meshes)})
        except measure.MeasureError as e:
            out.append({"request": r, "error": str(e)})
    return out


def brep(path: Path) -> dict:
    """a STEP/IGES file: what the tessellation gives, part by part"""
    info: dict = {}
    try:
        meshes, tree, defl = load_brep(path.read_bytes(), path.name, info)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    blob, meta = pack_parts(meshes, tree, defl)
    parts = []
    for m in meshes:
        bb = m.positions.reshape(-1, 3)
        parts.append({
            "id": m.part.part_id,
            "name": m.part.name,
            "color": list(m.part.color) if m.part.color else None,
            "faces": m.face_map.Extent(),
            "edges": m.edge_map.Extent(),
            "vertices": m.vertex_map.Extent(),
            "faceIds": [r["faceId"] for r in m.face_ranges],
            "edgeIds": [r["edgeId"] for r in m.edge_ranges],
            "edgeSegments": [r["segCount"] for r in m.edge_ranges],
            "edgeEnds": [[m.edge_positions[2 * r["segStart"]].astype(float).round(4).tolist(),
                          m.edge_positions[2 * (r["segStart"] + r["segCount"]) - 1].astype(float).round(4).tolist()]
                         for r in m.edge_ranges],
            "triangles": int(len(m.indices)),
            "bbox": [bb.min(axis=0).tolist(), bb.max(axis=0).tolist()] if len(bb) else None,
            "vertexPositions": m.vertex_positions.astype(float).round(5).tolist(),
        })
    return {
        "tree": tree.to_dict(),
        "fileUnit": info.get("fileUnit"),
        "deflection": defl,
        "bbox": meta["bbox"],
        "parts": parts,
        "properties": properties.brep_properties(meshes),
        "measures": measures(meshes),
    }


def triangles(mesh) -> list:
    """the triangles by their corners' places, each from its least corner (the
    turn kept), sorted: the same set, whatever order each engine makes them in
    (how a face of more than three corners is cut, #87)"""
    out = []
    for tri in np.round(np.asarray(mesh.vertices)[np.asarray(mesh.faces)], 4).tolist():
        k = min(range(3), key=lambda i: tri[i])
        out.append(tri[k:] + tri[:k])
    return sorted(out)


def answer(path: Path) -> dict:
    data = path.read_bytes()
    if classify(path.name) == "brep":
        return brep(path)
    if classify(path.name) != "mesh":
        return {"error": "not a mesh format"}
    try:
        mesh = load_mesh(data, path.name)
    except Exception as e:  # noqa: BLE001 — reported as the route would
        return {"error": f"failed to parse mesh: {e}"}
    blob, meta = pack_trimesh(mesh, name=path.name)
    # the display mesh's vertices with their normals, rounded and sorted (the
    # order is the engine's own; the set must be the same)
    pn = np.hstack([np.asarray(mesh.vertices), np.asarray(mesh.vertex_normals)])
    return {
        "vertexCount": meta["vertexCount"],
        "triangleCount": meta["triangleCount"],
        "bbox": meta["bbox"],
        "vertices": sorted(np.round(pn, 4).tolist()),
        "triangles": triangles(mesh),
        "properties": properties.mesh_properties(blob),
    }


def routes(path: Path) -> dict:
    """the backend's own routes for the file (FastAPI's TestClient): the display
    mesh, the thickness (ray, ball), 厚肉 (/thick, /thick.bin), the projected area"""
    import struct
    import tempfile

    os.environ.setdefault("CAD_VIEWER_DATA_DIR", tempfile.mkdtemp(prefix="cad-golden-"))
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    up = c.post("/api/models", files={"file": (path.name, path.read_bytes(), "x")})
    if up.status_code != 200:
        return {"error": up.text}
    mid = up.json()["id"]

    def unpack(blob: bytes) -> dict:
        (hl,) = struct.unpack_from("<I", blob, 0)
        head = json.loads(blob[4 : 4 + hl])
        out = {"parts": head.get("parts", [])}
        for name, d in head["buffers"].items():
            fmt = "f" if d["dtype"] == "float32" else "I"
            out[name] = list(struct.unpack_from(f"<{d['count']}{fmt}", blob, 4 + hl + d["offset"]))
        return out

    mesh = unpack(c.get(f"/api/models/{mid}/mesh.bin").content)
    out = {"mesh": {k: v for k, v in mesh.items() if k == "parts" or k.endswith((":positions", ":normals", ":indices"))}}
    for method in ("ray", "ball"):
        out[f"thickness_{method}"] = unpack(c.get(f"/api/models/{mid}/thickness.bin?method={method}").content)
    out["thick"] = c.get(f"/api/models/{mid}/thick?ratio=1.5").json()
    out["thick_low"] = c.get(f"/api/models/{mid}/thick?ratio=1.1").json()
    out["thick_bin"] = unpack(c.get(f"/api/models/{mid}/thick.bin").content)
    out["projected"] = {ax: c.get(f"/api/models/{mid}/projected_area?axis={ax}").json() for ax in "XYZ"}
    # along a direction of its own (one picked from a face or an edge)
    out["projected"]["dir"] = c.get(f"/api/models/{mid}/projected_area?dir=1,2,3").json()
    return out


# OCCT's readers write to the C stdout (IGES: "Total number of loaded entities"):
# that goes to stderr while reading, so stdout carries only the JSON
sys.stdout.flush()
saved = os.dup(1)
os.dup2(2, 1)
try:
    if sys.argv[1:2] == ["--routes"]:
        answers = {p: routes(Path(p)) for p in sys.argv[2:]}
    else:
        answers = {p: answer(Path(p)) for p in sys.argv[1:]}
finally:
    sys.stdout.flush()
    os.dup2(saved, 1)
print(json.dumps(answers))
