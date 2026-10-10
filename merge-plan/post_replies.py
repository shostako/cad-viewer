"""Post the replies to the Codex inline comments (replies.json).

Idempotent: a comment that already has a reply quoting the fix SHA is skipped.
The body goes through stdin (gh is a snap and cannot read the scratchpad).
Each SHA must be on the PR's head branch on GitHub before its reply goes out.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = "shostako/cad-viewer"
replies = json.loads((Path(__file__).parent / "replies.json").read_text())


def gh(*args, stdin=None):
    r = subprocess.run(["gh", "api", *args], input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh api {' '.join(args)} failed: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


heads = {}
failed = 0
for rp in replies:
    pr, cid, sha = rp["pr"], rp["id"], rp["sha"]
    if pr not in heads:
        head = gh(f"repos/{REPO}/pulls/{pr}")["head"]["sha"]
        heads[pr] = head
    # the fix must be in the PR's head on GitHub (pushed), or the SHA in the reply points nowhere
    cmp = gh(f"repos/{REPO}/compare/{sha}...{heads[pr]}")
    if cmp["status"] not in ("ahead", "identical"):
        print(f"PR {pr} {cid}: {sha} is not in the head {heads[pr][:7]} ({cmp['status']}), not posted")
        failed += 1
        continue
    comments = gh(f"repos/{REPO}/pulls/{pr}/comments?per_page=100")
    if any(c.get("in_reply_to_id") == cid and f"`{sha}`" in c["body"] for c in comments):
        print(f"PR {pr} {cid}: already answered with {sha}")
        continue
    out = gh(
        "-X", "POST", f"repos/{REPO}/pulls/{pr}/comments/{cid}/replies", "--input", "-",
        stdin=json.dumps({"body": rp["body"]}),
    )
    print(f"PR {pr} {cid}: posted {out['html_url']}")
sys.exit(1 if failed else 0)
