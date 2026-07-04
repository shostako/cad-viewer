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


def pack_parts(meshes, tree, deflection: float) -> tuple[bytes, dict[str, Any]]:
    """Pack tessellated B-rep parts (see tessellation.PartMesh) into the protocol.

    Buffers are namespaced per part: "p{id}:positions", "p{id}:normals",
    "p{id}:indices", "p{id}:edges". The header carries parts metadata
    (name, color, faceRanges, edgeRanges) and the assembly tree.
    """
    buffers: dict[str, tuple[np.ndarray, int]] = {}
    parts_meta: list[dict[str, Any]] = []
    total_tris = 0
    total_verts = 0
    gmin = np.full(3, np.inf)
    gmax = np.full(3, -np.inf)

    for m in meshes:
        pid = m.part.part_id
        buffers[f"p{pid}:positions"] = (m.positions.astype(np.float32), 3)
        buffers[f"p{pid}:normals"] = (m.normals.astype(np.float32), 3)
        buffers[f"p{pid}:indices"] = (m.indices.astype(np.uint32), 1)
        buffers[f"p{pid}:edges"] = (m.edge_positions.astype(np.float32), 3)
        buffers[f"p{pid}:vertices"] = (
            (
                m.vertex_positions
                if m.vertex_positions is not None
                else np.empty((0, 3))
            ).astype(np.float32),
            3,
        )
        parts_meta.append(
            {
                "id": pid,
                "name": m.part.name,
                "color": list(m.part.color) if m.part.color else None,
                "faceRanges": m.face_ranges,
                "edgeRanges": m.edge_ranges,
            }
        )
        total_tris += len(m.indices)
        total_verts += len(m.positions)
        if len(m.positions):
            gmin = np.minimum(gmin, m.positions.min(axis=0))
            gmax = np.maximum(gmax, m.positions.max(axis=0))

    header_extra = {
        "parts": parts_meta,
        "tree": tree.to_dict(),
        "deflection": deflection,
    }
    blob = pack_buffers(buffers, extra_header=header_extra)
    meta = {
        "vertexCount": int(total_verts),
        "triangleCount": int(total_tris),
        "partCount": len(parts_meta),
        "bbox": {
            "min": [float(v) for v in gmin],
            "max": [float(v) for v in gmax],
        },
        "tree": tree.to_dict(),
        "parts": [
            {"id": p["id"], "name": p["name"], "color": p["color"]} for p in parts_meta
        ],
    }
    return blob, meta


def pack_trimesh(mesh, name: str = "mesh") -> tuple[bytes, dict[str, Any]]:
    """Pack a trimesh.Trimesh as a single anonymous part (unified format).

    Uses the same per-part namespaced layout as pack_parts so the frontend
    has exactly one decoding path.
    """
    positions = np.asarray(mesh.vertices, dtype=np.float32)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    indices = np.asarray(mesh.faces, dtype=np.uint32)

    part_meta = {
        "id": 0,
        "name": name,
        "color": None,
        "faceRanges": [],
        "edgeRanges": [],
    }
    tree = {"name": "root", "children": [{"name": name, "partId": 0}]}
    blob = pack_buffers(
        {
            "p0:positions": (positions, 3),
            "p0:normals": (normals, 3),
            "p0:indices": (indices, 1),
            "p0:edges": (np.empty((0, 3), dtype=np.float32), 3),
            "p0:vertices": (np.empty((0, 3), dtype=np.float32), 3),
        },
        extra_header={"parts": [part_meta], "tree": tree},
    )
    bbox = mesh.bounds  # (2, 3) min/max
    meta = {
        "vertexCount": int(len(positions)),
        "triangleCount": int(len(indices)),
        "partCount": 1,
        "bbox": {
            "min": [float(v) for v in bbox[0]],
            "max": [float(v) for v in bbox[1]],
        },
        "tree": tree,
        "parts": [{"id": 0, "name": name, "color": None}],
    }
    return blob, meta
