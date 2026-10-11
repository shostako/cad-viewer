"""Where the app keeps its data and finds its frontend.

A checkout keeps them in the repo: backend/.cache, backend/.sidecars and
frontend/dist. The installed app (app/desktop.py) points them elsewhere before it
imports the server: CAD_VIEWER_DATA_DIR (the user's folder, on Windows
%LOCALAPPDATA%\\cad-viewer) and CAD_VIEWER_DIST (the frontend bundled with it).
Read once, when cache.py and main.py are imported.
"""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent


def data_dir(name: str) -> Path:
    """the folder for one kind of data ("cache", "sidecars")"""
    root = os.environ.get("CAD_VIEWER_DATA_DIR")
    return Path(root) / name if root else _BACKEND / f".{name}"


def dist_dir() -> Path:
    """the built frontend (served at / when it is there)"""
    d = os.environ.get("CAD_VIEWER_DIST")
    return Path(d) if d else _BACKEND.parent / "frontend" / "dist"
