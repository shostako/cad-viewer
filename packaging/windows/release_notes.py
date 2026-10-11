"""Print a version's section of CHANGELOG.md (the GitHub release's notes).

    python packaging/windows/release_notes.py 0.6.0 > notes.md
"""
import re
import sys
from pathlib import Path

version = sys.argv[1].lstrip("v")
text = Path(__file__).resolve().parent.parent.parent.joinpath("CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(rf"^## \[{re.escape(version)}\].*?$(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", text, re.S | re.M)
if not m:
    sys.exit(f"CHANGELOG.md has no section for {version}")
sys.stdout.reconfigure(encoding="utf-8")
print(m.group(1).strip())
