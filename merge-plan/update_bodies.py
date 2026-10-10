"""Add a 「Codex の指摘の直し」 section to the stacked PRs' bodies.

Idempotent: a body that already has the section is left as it is. The section
goes before the trailer (the "🤖 Generated with" line). Bodies go through
stdin (REST PATCH; gh is a snap and gh pr edit fails silently on GraphQL).
"""
import json
import subprocess
import sys

REPO = "shostako/cad-viewer"
HEAD = "## Codex の指摘の直し"
FIXES = {
    37: [
        "`7873985` キー操作の一覧で、ホイール（カーソルの位置へ）と＋／−（回転の中心へ）の拡大・縮小を 2 行に分けた"
        "（＋／−はカーソルの位置へは寄らない）。test_half_window で 2 つの行の文とキーを確かめる",
    ],
    38: [
        "`20ec8d3` 手で書き換えたサイドカーの、文（labelText・text）の欠けた計測でも一覧を止めない（欠けた文は空として読む）",
        "`20ec8d3` コピーは × と同じく mousedown で受ける。書きかけの注記があっても 1 回目でコピーされ、注記は開いたまま。"
        "test_measure_record に 2 つを足した",
    ],
    39: [
        "`2df7999` ボタンを 25 px にして、全部をツールバーの内側に収めた（26 px では中身が 260 px になり、内側の 252 px から"
        "はみ出して「?」が外に出ていた）。test_toolbar に、どのボタンもツールバーの内側にあることを足した",
    ],
    41: [
        "`72f6b81` 全体表示の途中に投影を切り替えたとき、動きを行き先まで進めてから「全体表示のままか」を読む（そのあとの H で収め直す）",
        "`72f6b81` 視点のボタンや全体表示の動きの途中のダブルクリックは、先に行き先まで進めてから点を拾う"
        "（回転の中心へ寄る動きの途中は今までどおり、その場から次を始める）。test_view_motion に 2 つを足した",
    ],
    43: [
        "`a29fb85` 下へずらすと画面の下を越える札は、重なる札の上へずらす（上にも収まらないときだけ下）。"
        "test_label_spread に、画面の下の近くで重なる札が 3 つとも画面の中に並ぶことを足した",
    ],
}
# sentences the fixes made inexact: (old, new)
EDITS = {
    43: [("触れなくなるまで下へずらす（margin-top）", "触れなくなるまで下へずらす（margin-top。下へずらすと画面の下を越えるときは上へ）")],
}


def gh(*args, stdin=None):
    r = subprocess.run(["gh", "api", *args], input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh api {' '.join(args)} failed: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


for pr, lines in FIXES.items():
    body = gh(f"repos/{REPO}/pulls/{pr}")["body"]
    if HEAD in body:
        print(f"#{pr}: already has the section")
        continue
    for old, new in EDITS.get(pr, []):
        if old not in body:
            sys.exit(f"#{pr}: the sentence to edit is not in the body: {old}")
        body = body.replace(old, new, 1)
    section = HEAD + "\n\n" + "\n".join(f"- {s}" for s in lines) + "\n\n"
    at = body.find("🤖 Generated with")
    body = body[:at] + section + body[at:] if at >= 0 else body.rstrip() + "\n\n" + section
    out = gh("-X", "PATCH", f"repos/{REPO}/pulls/{pr}", "--input", "-", stdin=json.dumps({"body": body}))
    ok = HEAD in out["body"]
    print(f"#{pr}: {'updated' if ok else 'NOT updated'}")
    if not ok:
        sys.exit(1)
