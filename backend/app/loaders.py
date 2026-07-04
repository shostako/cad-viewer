"""Format-dispatching model loaders.

Phase 0: STL (+3MF/OBJ/PLY come free via trimesh).
Phase 1: STEP/IGES via OCP (tessellation.py).
Phase 4: DXF/DWG (2D pipeline, separate route).
"""
from __future__ import annotations

import io
from pathlib import Path

import trimesh

# formats trimesh handles directly (mesh route)
MESH_EXTS = {".stl", ".3mf", ".obj", ".ply", ".off", ".glb", ".gltf"}
# B-rep route (Phase 1)
BREP_EXTS = {".step", ".stp", ".iges", ".igs"}
# 2D route (Phase 4)
DRAWING_EXTS = {".dxf", ".dwg"}


class UnsupportedFormatError(Exception):
    pass


def classify(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in MESH_EXTS:
        return "mesh"
    if ext in BREP_EXTS:
        return "brep"
    if ext in DRAWING_EXTS:
        return "drawing"
    raise UnsupportedFormatError(f"unsupported file extension: {ext}")


def load_mesh(data: bytes, filename: str) -> trimesh.Trimesh:
    ext = Path(filename).suffix.lower().lstrip(".")
    loaded = trimesh.load(io.BytesIO(data), file_type=ext)
    if isinstance(loaded, trimesh.Scene):
        # flatten multi-body scenes (3MF etc.) into a single mesh for Phase 0
        loaded = loaded.to_mesh()
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise ValueError("no triangle geometry found in file")
    return loaded
