"""Disk cache for tessellation results.

Key: sha256(file bytes) + tessellation params. Value: packed blob + meta JSON.
Atomic writes (tmp + rename) so an interrupted write never leaves a bad entry.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
# bump when the binary protocol OR the tessellated output changes: the lazy
# B-rep re-parse must number parts / faces exactly like the cached mesh
CACHE_VERSION = 4  # 3: loose IGES faces are sewn into solids; 4: the meta says the file's unit


def cache_key(data: bytes, params: str) -> str:
    h = hashlib.sha256()
    h.update(data)
    h.update(f"|v{CACHE_VERSION}|{params}".encode())
    return h.hexdigest()[:32]


def get(key: str) -> tuple[bytes, dict[str, Any]] | None:
    blob_path = CACHE_DIR / f"{key}.bin"
    meta_path = CACHE_DIR / f"{key}.json"
    try:
        meta = json.loads(meta_path.read_text())
        blob = blob_path.read_bytes()
        return blob, meta
    except (OSError, json.JSONDecodeError):
        return None


def put(key: str, blob: bytes, meta: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for suffix, payload in ((".bin", blob), (".json", json.dumps(meta).encode())):
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=suffix + ".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            os.replace(tmp, CACHE_DIR / f"{key}{suffix}")
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
