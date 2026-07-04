"""CAD viewer backend (FastAPI).

Run (dev):
    .venv/bin/uvicorn app.main:app --reload --port 8008
Frontend dev server (Vite) proxies /api to this port.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response

from . import cache
from .loaders import UnsupportedFormatError, classify, load_mesh
from .meshpack import pack_parts, pack_trimesh
from .store import ModelEntry, new_model_id, store
from .tessellation import BrepLoadError, load_brep

app = FastAPI(title="cad-viewer backend")

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


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
                extra={"raw": data, "filename": name, "cached": True},
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
            extra={"raw": data, "filename": name, "cached": False},
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


@app.delete("/api/models/{model_id}")
def delete_model(model_id: str) -> dict:
    if store.get(model_id) is None:
        raise HTTPException(404, "model not found")
    store.remove(model_id)
    return {"deleted": model_id}
