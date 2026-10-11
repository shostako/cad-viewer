"""The backend's answers for files, for comparing the Web version's engine
(frontend/src/local/) with them: frontend/tests/*.test.ts run this.

    backend/.venv/bin/python scripts/engine_golden.py FILE...

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

from app import properties  # noqa: E402
from app.loaders import classify, load_mesh  # noqa: E402
from app.meshpack import pack_parts, pack_trimesh  # noqa: E402
from app.tessellation import load_brep  # noqa: E402


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
    }


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
        "properties": properties.mesh_properties(blob),
    }


# OCCT's readers write to the C stdout (IGES: "Total number of loaded entities"):
# that goes to stderr while reading, so stdout carries only the JSON
sys.stdout.flush()
saved = os.dup(1)
os.dup2(2, 1)
try:
    answers = {p: answer(Path(p)) for p in sys.argv[1:]}
finally:
    sys.stdout.flush()
    os.dup2(saved, 1)
print(json.dumps(answers))
