"""CAD viewer backend (FastAPI).

Run (dev):
    .venv/bin/uvicorn app.main:app --reload --port 8008
Frontend dev server (Vite) proxies /api to this port.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import __version__, cache, measure, projection, properties
from .drawing import DrawingLoadError, load_drawing
from .loaders import UnsupportedFormatError, classify, load_mesh
from .meshpack import pack_parts, pack_trimesh
from .store import ModelEntry, new_model_id, store
from .tessellation import BrepLoadError, load_brep

app = FastAPI(title="cad-viewer backend", version=__version__)

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
SIDECAR_DIR = Path(__file__).resolve().parent.parent / ".sidecars"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


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

    # identical content already in memory — reuse instead of duplicating
    existing = store.get_by_hash(content_hash)
    if existing is not None and existing.fmt == route:
        return {
            "id": existing.model_id,
            "name": existing.name,
            "format": existing.fmt,
            **({"cached": True} if route == "brep" else {}),
            **existing.meta,
        }

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
            # no "raw" here: brep handles are live, raw bytes would be dead weight
            extra={"filename": name, "cached": False, "hash": content_hash},
        )
        store.add(entry)
        return {"id": entry.model_id, "name": name, "format": route, "cached": False, **meta}

    if route == "drawing":
        try:
            svg, meta = load_drawing(data, name)
        except DrawingLoadError as e:
            raise HTTPException(422, str(e)) from e
        entry = ModelEntry(
            model_id=new_model_id(),
            name=name,
            fmt=route,
            meta=meta,
            extra={"svg": svg, "hash": content_hash},
        )
        store.add(entry)
        return {"id": entry.model_id, "name": name, "format": route, **meta}

    raise HTTPException(501, f"{route} route not implemented yet")


@app.get("/api/models/{model_id}/drawing.svg")
def get_drawing_svg(model_id: str) -> Response:
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    svg = entry.extra.get("svg")
    if not svg:
        raise HTTPException(404, "model has no drawing payload")
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/models/{model_id}/mesh.bin")
def get_mesh(model_id: str) -> Response:
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    if not entry.mesh_blob:
        raise HTTPException(404, "model has no mesh payload")
    return Response(content=entry.mesh_blob, media_type="application/octet-stream")


def _brep_meshes(entry: ModelEntry):
    """B-rep handles for measurement; lazily re-parsed after a cache hit.

    entry.lock serializes the re-parse: concurrent measure requests on a
    fresh cache-hit entry would otherwise both run the expensive load_brep.
    """
    with entry.lock:
        if entry.brep is None:
            raw = entry.extra.get("raw")
            if raw is None:
                raise HTTPException(
                    422, "model has no B-rep data (mesh formats can't be measured exactly)"
                )
            meshes, _tree, _defl = load_brep(raw, entry.extra["filename"])
            entry.brep = {"meshes": meshes}
            # brep handles are live now — keeping the original upload bytes
            # would double the entry's memory for its whole LRU lifetime
            # (uploads can be hundreds of MB). Fresh uploads never store them.
            entry.extra.pop("raw", None)
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


@app.get("/api/models/{model_id}/thickness.bin")
def get_thickness(model_id: str, method: str = "ray") -> Response:
    """Per-vertex wall thickness for every part (computed lazily, cached).

    method=ray  — fast inward-normal ray probe (default)
    method=ball — rolling ball (maximal tangent sphere), slower but exact
                  at rib junctions and oblique walls
    """
    if method not in ("ray", "ball"):
        raise HTTPException(422, "method must be 'ray' or 'ball'")
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    # drawings (DXF/DWG) have no mesh payload — decoding would raise
    # struct.error and surface as an uncontrolled 500
    if entry.fmt == "drawing" or not entry.mesh_blob:
        raise HTTPException(422, "thickness requires a 3D model (mesh or B-rep)")
    cache_key = f"thickness_blob_{method}"
    with entry.lock:
        blob = entry.extra.get(cache_key)
        if blob is not None:
            return Response(content=blob, media_type="application/octet-stream")
        import numpy as np

        from .meshpack import pack_buffers, unpack_parts
        from .thickness import vertex_thickness, vertex_thickness_ball

        compute = vertex_thickness_ball if method == "ball" else vertex_thickness

        # decode the entry's own mesh blob (works for mesh & brep alike)
        buffers = {}
        for part in unpack_parts(entry.mesh_blob)[1]:
            t = compute(part["positions"], part["normals"], part["indices"])
            # inf -> 0 sentinel (frontend treats <=0 as "no data")
            t[~np.isfinite(t)] = 0.0
            buffers[f"p{part['id']}:thickness"] = (t, 1)
        blob = pack_buffers(buffers)
        entry.extra[cache_key] = blob
    return Response(content=blob, media_type="application/octet-stream")


@app.get("/api/models/{model_id}/properties")
def get_properties(model_id: str) -> dict:
    """Volume, surface area and centre of mass per part, plus the closed parts' total.

    mm / mm² / mm³, unrounded. B-rep parts are integrated exactly on the
    B-rep; mesh formats on their triangles. A part that is not closed gets no
    volume (see properties.py for why the check is strict).
    """
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    if entry.fmt == "drawing" or not entry.mesh_blob:
        raise HTTPException(422, "properties require a 3D model (mesh or B-rep)")
    cached = entry.extra.get("properties")
    if cached is not None:
        return cached
    # Computed without entry.lock on purpose: a long integration must not hold
    # up measure requests. Two concurrent requests just compute the same pure
    # result twice. The B-rep re-parse after a cache hit locks by itself.
    if entry.fmt == "brep":
        try:
            meshes = _brep_meshes(entry)
        except BrepLoadError as e:
            raise HTTPException(422, str(e)) from e
        result = properties.brep_properties(meshes)
    else:
        result = properties.mesh_properties(entry.mesh_blob)
    entry.extra["properties"] = result
    return result


# projected areas kept per model (one per axis and set of visible parts)
_PROJECTION_CACHE_MAX = 32
# pages remembered per model for "a newer request from the same page"
_PROJECTION_CLIENTS_MAX = 64


class _ProjectionGate:
    """One projection at a time per model, and none that its page no longer wants.

    A calculation holds two bitmaps of up to 64 M and 16 M pixels for about a
    second (more on a large model). A user flipping the 型開き方向 or the parts
    shown asks again each time; the page shows only the latest answer. So the
    calculations run one after another, and a request still waiting when a
    newer one from the same page (its "client") has come gives up (409): the
    latest one does not wait behind work nobody will see. Requests from other
    pages (another tab) are never given up for this one's sake.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()  # held while computing
        self.guard = threading.Lock()  # for the counters below
        self.count = 0
        self.latest: dict[str, int] = {}  # client -> its newest ticket

    def ticket(self, client: str | None) -> int:
        with self.guard:
            self.count += 1
            if client:
                self.latest.pop(client, None)  # re-insert: the oldest page goes first
                self.latest[client] = self.count
                while len(self.latest) > _PROJECTION_CLIENTS_MAX:
                    self.latest.pop(next(iter(self.latest)))
            return self.count

    def superseded(self, client: str | None, ticket: int) -> bool:
        with self.guard:
            return bool(client) and self.latest.get(client, ticket) > ticket


_gates_guard = threading.Lock()


def _projection_gate(entry: ModelEntry) -> _ProjectionGate:
    with _gates_guard:
        gate = entry.extra.get("projection_gate")
        if gate is None:
            gate = entry.extra["projection_gate"] = _ProjectionGate()
        return gate


@app.get("/api/models/{model_id}/projected_area")
def get_projected_area(model_id: str, axis: str = "Z", parts: str | None = None, client: str | None = None) -> dict:
    """The model's shadow along an axis (X / Y / Z), for a clamping-force estimate.

    parts: comma-separated part ids to include (the visible ones); omitted for
    every part, empty for none. client: the asking page's id; a request of its
    still waiting for another calculation to end gives up (409) once the page
    has asked again (_ProjectionGate). mm², from the display mesh
    (projection.py): an estimate, like the wall thickness. "pixel" is the
    finer bitmap's pixel (mm).
    """
    if axis not in projection.AXES:
        raise HTTPException(422, "axis must be X, Y or Z")
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    if entry.fmt == "drawing" or not entry.mesh_blob:
        raise HTTPException(422, "projected area requires a 3D model (mesh or B-rep)")
    wanted: set[int] | None = None
    if parts is not None:
        try:
            wanted = {int(x) for x in parts.split(",") if x.strip()}
        except ValueError as e:
            raise HTTPException(422, "parts must be comma-separated part ids") from e
    from .meshpack import unpack_parts

    meshes = [p for p in unpack_parts(entry.mesh_blob)[1] if wanted is None or p["id"] in wanted]
    ids = sorted(p["id"] for p in meshes)
    key = f"projection:{axis}:{','.join(map(str, ids))}"
    cached = entry.extra.get(key)
    if cached is not None:
        return cached
    gate = _projection_gate(entry)
    ticket = gate.ticket(client)
    # not entry.lock: a measure request must not wait behind a projection
    with gate.lock:
        cached = entry.extra.get(key)  # computed while this one waited
        if cached is not None:
            return cached
        if gate.superseded(client, ticket):
            raise HTTPException(409, "superseded by a newer request from the same page")
        result = {
            **projection.projected_area([(p["positions"], p["indices"]) for p in meshes], axis),
            "parts": ids,
        }
        keys = [k for k in list(entry.extra) if k.startswith("projection:")]
        for k in keys[: max(0, len(keys) - _PROJECTION_CACHE_MAX + 1)]:
            entry.extra.pop(k, None)
        entry.extra[key] = result
    return result


def _sidecar_path(model_id: str) -> Path:
    entry = store.get(model_id)
    if entry is None:
        raise HTTPException(404, "model not found")
    content_hash = entry.extra.get("hash")
    if not content_hash:
        raise HTTPException(422, "model has no content hash")
    return SIDECAR_DIR / f"{content_hash}.json"


class _UnreadableSidecar(Exception):
    """A sidecar file is there but cannot be read as one (damaged, edited by hand)."""


def _read_sidecar(path: Path) -> dict | None:
    """The saved sidecar, or None when nothing is saved for the model."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as e:
        raise _UnreadableSidecar("文字コードが UTF-8 ではない") from e
    except OSError as e:
        raise _UnreadableSidecar(e.strerror or str(e)) from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise _UnreadableSidecar(f"JSON ではない、{e.lineno} 行目") from e
    if not isinstance(data, dict):
        raise _UnreadableSidecar("中身の形が違う")
    return data


@app.get("/api/models/{model_id}/sidecar")
def get_sidecar(model_id: str) -> dict:
    """{} when nothing is saved. A file that cannot be read is an error, not
    {}: the load then tells the user, instead of opening as if nothing had
    been saved (the next edit would save over the file without a word)."""
    path = _sidecar_path(model_id)
    try:
        return _read_sidecar(path) or {}
    except _UnreadableSidecar as e:
        raise HTTPException(500, f"保存ファイルが壊れている: {e}") from e


def _keep_unreadable(path: Path) -> None:
    """Move an unreadable sidecar aside before a save replaces it. The model
    opened without its entries (GET said why); the bytes may still be
    repaired by hand, so they stay, as <hash>.unreadable-<time>.json."""
    try:
        _read_sidecar(path)
        return  # missing or readable: replaced as usual
    except _UnreadableSidecar:
        pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    try:
        os.replace(path, path.with_name(f"{path.stem}.unreadable-{stamp}.json"))
    except FileNotFoundError:
        pass  # a concurrent save moved it already
    except OSError as e:
        # the save goes on (the user's new entries matter more), but leave a trace
        logging.getLogger(__name__).warning("could not keep unreadable sidecar %s: %s", path.name, e)


@app.put("/api/models/{model_id}/sidecar")
def put_sidecar(model_id: str, body: dict) -> dict:
    path = _sidecar_path(model_id)
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    # Unique temp file per request: a fixed <hash>.json.tmp name races when two
    # saves for the same content hash run concurrently (one request's replace()
    # removes the other's temp file -> FileNotFoundError / stale data).
    fd, tmp = tempfile.mkstemp(dir=SIDECAR_DIR, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False))
        _keep_unreadable(path)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"saved": True}


@app.delete("/api/models/{model_id}")
def delete_model(model_id: str) -> dict:
    if store.get(model_id) is None:
        raise HTTPException(404, "model not found")
    store.remove(model_id)
    return {"deleted": model_id}


# --- static frontend (production single-server mode) -------------------------
# When frontend/dist exists (built via `npm run build`), serve the SPA from this
# same server so the whole app runs as ONE process on port 8008 — no separate
# Vite dev server. Mounted LAST so every /api/* route above matches first;
# absent dist (dev mode) leaves this off and the Vite dev server proxies /api.
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="spa")
