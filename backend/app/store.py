"""In-memory model store.

Phase 0: holds trimesh meshes loaded from uploaded files.
Phase 1+: will also hold TopoDS_Shape and topology ID maps for B-rep models.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelEntry:
    model_id: str
    name: str
    fmt: str
    meta: dict[str, Any]
    # Phase 0: packed binary mesh payload (see meshpack.py)
    mesh_blob: bytes = b""
    # Phase 1+: server-side B-rep handles (TopoDS_Shape, ID maps)
    brep: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class ModelStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: dict[str, ModelEntry] = {}

    def add(self, entry: ModelEntry) -> None:
        with self._lock:
            self._models[entry.model_id] = entry

    def get(self, model_id: str) -> ModelEntry | None:
        with self._lock:
            return self._models.get(model_id)

    def remove(self, model_id: str) -> None:
        with self._lock:
            self._models.pop(model_id, None)

    def list_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"id": e.model_id, "name": e.name, "format": e.fmt, **e.meta}
                for e in self._models.values()
            ]


def new_model_id() -> str:
    return uuid.uuid4().hex[:12]


store = ModelStore()
