"""The backend's answers for files, for comparing the Web version's engine
(frontend/src/local/) with them: frontend/tests/*.test.ts run this.

    backend/.venv/bin/python scripts/engine_golden.py FILE...

Prints JSON: per file, what POST /api/models says (vertexCount, triangleCount,
bbox) and GET /properties, or the error. The same code as the routes
(loaders.load_mesh, meshpack.pack_trimesh, properties.mesh_properties), without
the server.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import properties  # noqa: E402
from app.loaders import classify, load_mesh  # noqa: E402
from app.meshpack import pack_trimesh  # noqa: E402


def answer(path: Path) -> dict:
    data = path.read_bytes()
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


print(json.dumps({p: answer(Path(p)) for p in sys.argv[1:]}))
