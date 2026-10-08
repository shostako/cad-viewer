"""Shared pytest fixtures.

Every test session runs against throwaway data directories. Without this, tests
that upload models and save sidecars write into the real backend/.sidecars (the
user's annotations and section state) and backend/.cache, and a cache entry
left by an earlier run decides which code path a test takes.

Session scope is required: module-scoped fixtures (e.g. the `model` uploads in
test_measure.py / test_drawing.py) are set up before any function-scoped
fixture, so a function-scoped patch would come too late for them.
"""
from __future__ import annotations

import pytest

from app import cache, main


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dirs(tmp_path_factory):
    root = tmp_path_factory.mktemp("data")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "SIDECAR_DIR", root / "sidecars")
        mp.setattr(cache, "CACHE_DIR", root / "cache")
        yield root
