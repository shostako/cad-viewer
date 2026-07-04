"""CAD viewer backend (FastAPI).

Run (dev):
    .venv/bin/uvicorn app.main:app --reload --port 8008
Frontend dev server (Vite) proxies /api to this port.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response

from . import cache, measure
from .loaders import UnsupportedFormatError, classify, load_mesh
from .meshpack import pack_parts, pack_trimesh
from .store import ModelEntry, new_model_id, store
from .tessellation import BrepLoadError, load_brep

app = FastAPI(title="cad-viewer backend")

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
SIDECAR_DIR = Path(__file__).resolve().parent.parent / ".sidecars"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/models")
def list_models() -> list[dict]:
    return store.list_meta()


@app.post("/api/models")
async def upload_model(file: UploadFile) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large")
    if not data:
        raise HTTPException(400, "empty file")
    name = file.filename or "model"

    try:
        route = classify(name)
    except UnsupportedFormatError as e:
        raise HTTPException(415, str(e)) from e

    content_hash = hashlib.sha256(data).hexdigest()[:32]

    if route == "mesh":
        try:
            mesh = load_mesh(data, name)
        except Exception as e:
            raise HTTPException(422, f"failed to parse mesh: {e}") from e
        blob, meta = pack_trimesh(mesh, name=name)
        entry = ModelEntry(
            model_id=new_model_id(),
            name=name,
            fmt=route,
            meta=meta,
            mesh_blob=blob,
            extra={"hash": content_hash},
        )
        store.add(entry)
        return {"id": entry.model_id, "name": name, "format": route, **meta}

    if route == "brep":
        key = cache.cache_key(data, "defl_rel=1e-3;ang=0.35")
        cached = cache.get(key)
        if cached is not None:
            blob, meta = cached
            entry = ModelEntry(
                model_id=new_model_id(),
                name=name,
                fmt=route,
                meta=meta,
                mesh_blob=blob,
                # raw bytes kept for lazy B-rep re-parse on first measure (Phase 2)
                extra={"raw": data, "filename": name, "cached": True, "hash": content_hash},
            )
            store.add(entry)
            return {"id": entry.model_id, "name": name, "format": route, "cached": True, **meta}

        try:
            meshes, tree, defl = load_brep(data, name)
        except BrepLoadError as e:
            raise HTTPException(422, str(e)) from e
        blob, meta = pack_parts(meshes, tree, defl)
        cache.put(key, blob, meta)
        entry = ModelEntry(
            model_id=new_model_id(),
            name=name,
            fmt=route,
            meta=meta,
            mesh_blob=blob,
            brep={"meshes": meshes},  # Phase 2: face/edge maps for measurement
            extra={"raw": data, "filename": name, "cached": False, "hash": content_hash},
        )
        store.add(entry)
        return {"id": entry.model_id, "name": name, "format": route, "cached": False, **meta}

    # drawing route arrives in Phase 4
    raise HTTPException(501, f"{route} route not implemented yet")


@app.get("/api/models/{model_id}/mesh.bin")
def get_mesh(model_id: str) -> Response:
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    if not entry.mesh_blob:
        raise HTTPException(404, "model has no mesh payload")
    return Response(content=entry.mesh_blob, media_type="application/octet-stream")


def _brep_meshes(entry: ModelEntry):
    """B-rep handles for measurement; lazily re-parsed after a cache hit."""
    if entry.brep is None:
        raw = entry.extra.get("raw")
        if raw is None:
            raise HTTPException(422, "model has no B-rep data (mesh formats can't be measured exactly)")
        meshes, _tree, _defl = load_brep(raw, entry.extra["filename"])
        entry.brep = {"meshes": meshes}
    return entry.brep["meshes"]


@app.post("/api/models/{model_id}/measure")
def measure_model(model_id: str, request: dict) -> dict:
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    if entry.fmt != "brep":
        raise HTTPException(422, "measurement requires a B-rep model (STEP/IGES)")
    try:
        return measure.run(request, _brep_meshes(entry))
    except measure.MeasureError as e:
        raise HTTPException(422, str(e)) from e


def _sidecar_path(model_id: str) -> Path:
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    content_hash = entry.extra.get("hash")
    if not content_hash:
        raise HTTPException(422, "model has no content hash")
    return SIDECAR_DIR / f"{content_hash}.json"


@app.get("/api/models/{model_id}/sidecar")
def get_sidecar(model_id: str) -> dict:
    path = _sidecar_path(model_id)
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@app.put("/api/models/{model_id}/sidecar")
def put_sidecar(model_id: str, body: dict) -> dict:
    path = _sidecar_path(model_id)
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False))
    tmp.replace(path)
    return {"saved": True}


@app.delete("/api/models/{model_id}")
def delete_model(model_id: str) -> dict:
    if store.get(model_id) is None:
        raise HTTPException(404, "model not found")
    store.remove(model_id)
    return {"deleted": model_id}
