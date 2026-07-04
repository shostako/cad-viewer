"""Binary mesh packing protocol.

Layout (little-endian):
    [uint32 headerLen][header JSON (utf-8)][buffer bytes...]

The header JSON describes each buffer section:
    {
      "buffers": {
        "positions": {"offset": 0, "length": N, "dtype": "float32", "itemSize": 3},
        "normals":   {...},
        "indices":   {"dtype": "uint32", "itemSize": 1},
        ...
      },
      "groups": [...]   # Phase 1+: faceRanges [{faceId, triStart, triCount}]
    }

Offsets are relative to the end of the header. This format extends cleanly
for Phase 1 (edge polylines, face ranges) without breaking Phase 0 clients.
"""
from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np

_DTYPES = {
    "float32": np.float32,
    "uint32": np.uint32,
}


def pack_buffers(
    buffers: dict[str, tuple[np.ndarray, int]],
    extra_header: dict[str, Any] | None = None,
) -> bytes:
    """Pack named numpy arrays into the binary protocol.

    buffers: name -> (array, itemSize). Arrays are flattened and must be
             float32 or uint32.
    """
    header: dict[str, Any] = {"buffers": {}}
    if extra_header:
        header.update(extra_header)

    chunks: list[bytes] = []
    offset = 0
    for name, (arr, item_size) in buffers.items():
        flat = np.ascontiguousarray(arr).ravel()
        dtype_name = flat.dtype.name
        if dtype_name not in _DTYPES:
            raise ValueError(f"unsupported dtype for buffer {name}: {dtype_name}")
        raw = flat.tobytes()
        header["buffers"][name] = {
            "offset": offset,
            "byteLength": len(raw),
            "count": int(flat.size),
            "dtype": dtype_name,
            "itemSize": item_size,
        }
        chunks.append(raw)
        offset += len(raw)

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(header_bytes)) + header_bytes + b"".join(chunks)


def pack_trimesh(mesh) -> tuple[bytes, dict[str, Any]]:
    """Pack a trimesh.Trimesh into the binary protocol.

    Returns (blob, meta) where meta contains display stats.
    """
    positions = np.asarray(mesh.vertices, dtype=np.float32)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    indices = np.asarray(mesh.faces, dtype=np.uint32)

    blob = pack_buffers(
        {
            "positions": (positions, 3),
            "normals": (normals, 3),
            "indices": (indices, 1),
        }
    )
    bbox = mesh.bounds  # (2, 3) min/max
    meta = {
        "vertexCount": int(len(positions)),
        "triangleCount": int(len(indices)),
        "bbox": {
            "min": [float(v) for v in bbox[0]],
            "max": [float(v) for v in bbox[1]],
        },
    }
    return blob, meta
