"""The version number is written in several places, and they must agree.

The newest section of CHANGELOG.md names the current version. A release PR
raises it together with app.__version__ (which GET /api/health reports),
backend/pyproject.toml and frontend/package.json / package-lock.json. The
CHANGELOG's own order and its compare links are checked here too: nothing else
reads them.
"""
import json
import re
import tomllib
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
REPO = "https://github.com/shostako/cad-viewer"

# "## [0.4.0] — 2026-10-10": SemVer without leading zeros, an em dash, an ISO date
SECTION = re.compile(r"## \[((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\] — (\d{4}-\d{2}-\d{2})")
LINK = re.compile(r"\[(\d+\.\d+\.\d+)\]: (\S+)")


def _changelog() -> list[str]:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()


def _sections() -> list[tuple[str, date]]:
    """(version, date) of each section, top to bottom."""
    out = []
    for line in _changelog():
        if line.startswith("## "):
            m = SECTION.fullmatch(line)
            # feature PRs leave the CHANGELOG alone (no "Unreleased" section):
            # a release PR writes the whole section of its version
            assert m, f"CHANGELOG.md: not a version heading: {line!r}"
            out.append((m[1], date.fromisoformat(m[2])))
    assert out, "CHANGELOG.md has no version section"
    return out


def _semver(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(x) for x in version.split("."))
    return major, minor, patch


def test_versions_agree():
    pkg = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    found = {
        "CHANGELOG.md (newest section)": _sections()[0][0],
        "backend/app/__init__.py": __version__,
        "backend/pyproject.toml": pyproject["project"]["version"],
        "frontend/package.json": pkg["version"],
        "frontend/package-lock.json": lock["version"],
        'frontend/package-lock.json packages[""]': lock["packages"][""]["version"],
    }
    assert len(set(found.values())) == 1, found


def test_health_and_openapi_report_the_version():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}
    assert client.get("/openapi.json").json()["info"]["version"] == __version__


def test_changelog_newest_first():
    sections = _sections()
    versions = [_semver(v) for v, _ in sections]
    assert all(a > b for a, b in zip(versions, versions[1:])), [v for v, _ in sections]
    dates = [d for _, d in sections]
    assert all(a >= b for a, b in zip(dates, dates[1:])), [str(d) for d in dates]


def test_changelog_compare_links():
    """Each version links to its changes since the version below it (the
    oldest one to its own tree), and nothing else is linked as a version."""
    versions = [v for v, _ in _sections()]
    want = [(new, f"{REPO}/compare/v{old}...v{new}") for new, old in zip(versions, versions[1:])]
    want.append((versions[-1], f"{REPO}/tree/v{versions[-1]}"))
    got = [(m[1], m[2]) for line in _changelog() if (m := LINK.fullmatch(line))]
    assert sorted(got) == sorted(want)
