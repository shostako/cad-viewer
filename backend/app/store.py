"""In-memory model store with LRU eviction and content-hash dedup.

Entries can be heavy (packed mesh blob, raw file bytes, OCCT shapes), so the
store keeps at most MAX_ENTRIES models — least-recently-used beyond that are
evicted. Re-uploading identical content under the same name reuses the
existing entry instead of duplicating it (the index is keyed by the content
hash and the name: the name is shown, and names a mesh's one part).
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

MAX_ENTRIES = 16


@dataclass
class ModelEntry:
    model_id: str
    name: str
    fmt: str
    meta: dict[str, Any]
    # packed binary mesh payload (see meshpack.py)
    mesh_blob: bytes = b""
    # server-side B-rep handles (PartMesh list with TopoDS maps)
    brep: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
    # serializes heavy lazy work on this entry (brep re-parse, thickness)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelStore:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._lock = threading.Lock()
        self._models: OrderedDict[str, ModelEntry] = OrderedDict()
        self._by_hash: dict[tuple[str, str], str] = {}
        self._max = max_entries

    def add(self, entry: ModelEntry) -> None:
        with self._lock:
            self._models[entry.model_id] = entry
            self._models.move_to_end(entry.model_id)
            content_hash = entry.extra.get("hash")
            if content_hash:
                self._by_hash[(content_hash, entry.name)] = entry.model_id
            while len(self._models) > self._max:
                _mid, evicted = self._models.popitem(last=False)
                self._drop_hash(evicted)

    def get(self, model_id: str) -> ModelEntry | None:
        with self._lock:
            entry = self._models.get(model_id)
            if entry is not None:
                self._models.move_to_end(model_id)
            return entry

    def get_by_hash(self, content_hash: str, name: str) -> ModelEntry | None:
        """the entry of this content opened under this name, if it is still here"""
        with self._lock:
            model_id = self._by_hash.get((content_hash, name))
            if model_id is None:
                return None
            entry = self._models.get(model_id)
            if entry is not None:
                self._models.move_to_end(model_id)
            return entry

    def remove(self, model_id: str) -> None:
        with self._lock:
            entry = self._models.pop(model_id, None)
            if entry is not None:
                self._drop_hash(entry)

    def _drop_hash(self, entry: ModelEntry) -> None:
        content_hash = entry.extra.get("hash")
        if content_hash:
            key = (content_hash, entry.name)
            if self._by_hash.get(key) == entry.model_id:
                del self._by_hash[key]

    def list_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"id": e.model_id, "name": e.name, "format": e.fmt, **e.meta}
                for e in self._models.values()
            ]


def new_model_id() -> str:
    return uuid.uuid4().hex[:12]


store = ModelStore()
