#!/usr/bin/env python3
"""Codexレビュー指摘の取りこぼし監査。

Codex(chatgpt-codex-connector[bot])が付けた各インラインレビューコメントに、
リポジトリオーナーからの返信で**対応証跡**（バッククォート囲みのコミットSHA、
または Issue/PR 参照 `#N`）を含むものが一件でも紐づいているかを機械突合する。
"thanks" のような証跡なしの返信は「対応済み」と認めない。

返信の付いていないCodexコメント = 未処理 として列挙する。ゼロなら取りこぼしなし。
GitHubのコメントスレッド自体を台帳として使うので、別途の状態ファイルを持たない。

使い方:
    python3 scripts/audit_codex_review.py            # 全オープンPRを監査
    python3 scripts/audit_codex_review.py --pr 1     # PR #1 のみ
    python3 scripts/audit_codex_review.py --all      # クローズ済みPRも含める

終了コード: 未処理コメントが1件でもあれば 1、なければ 0（CI/フック向け）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

REPO = "shostako/cad-viewer"
CODEX_LOGIN = "chatgpt-codex-connector"

# 対応証跡パターン: コミットSHA（バッククォート囲みの7-40桁hex）または
# Issue/PR参照（#N）を含む返信だけを「対応済み」と認める。"thanks" のような
# 任意テキストの返信で未解決の指摘が監査から消えるのを防ぐ。
EVIDENCE = re.compile(r"`[0-9a-f]{7,40}`|#\d+", re.IGNORECASE)


def gh_json(path: str) -> list | dict:
    r = subprocess.run(
        ["gh", "api", path, "--paginate"], capture_output=True, text=True
    )
    if r.returncode != 0:
        sys.exit(f"gh api failed for {path}: {r.stderr.strip()}")
    # --paginate concatenates JSON arrays as separate top-level values; wrap them
    text = r.stdout.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # multiple arrays glued together -> merge
        merged: list = []
        dec = json.JSONDecoder()
        idx = 0
        while idx < len(text):
            obj, end = dec.raw_decode(text, idx)
            merged.extend(obj if isinstance(obj, list) else [obj])
            idx = end
            while idx < len(text) and text[idx] in " \n\r\t":
                idx += 1
        return merged


def repo_owner() -> str:
    return REPO.split("/")[0]


def target_prs(args) -> list[int]:
    if args.pr:
        return [args.pr]
    state = "all" if args.all else "open"
    prs = gh_json(f"repos/{REPO}/pulls?state={state}")
    return [p["number"] for p in prs]


def audit_pr(pr: int, owner: str) -> list[dict]:
    """Return the list of unaddressed Codex comments for one PR."""
    comments = gh_json(f"repos/{REPO}/pulls/{pr}/comments")
    codex_top = [
        c
        for c in comments
        if CODEX_LOGIN in c["user"]["login"] and not c.get("in_reply_to_id")
    ]
    # comment ids that received an owner reply carrying a valid evidence token
    # (commit SHA in backticks, or #N). A bare "thanks" does NOT count.
    addressed = {
        c["in_reply_to_id"]
        for c in comments
        if c.get("in_reply_to_id")
        and c["user"]["login"] == owner
        and EVIDENCE.search(c["body"] or "")
    }
    return [c for c in codex_top if c["id"] not in addressed]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pr", type=int, help="監査するPR番号（省略時は全PR）")
    ap.add_argument("--all", action="store_true", help="クローズ済みPRも含める")
    args = ap.parse_args()

    owner = repo_owner()
    prs = target_prs(args)
    if not prs:
        print("監査対象のPRなし。")
        return 0

    total_unaddressed = 0
    for pr in prs:
        unaddressed = audit_pr(pr, owner)
        codex_total = len(
            [
                c
                for c in gh_json(f"repos/{REPO}/pulls/{pr}/comments")
                if CODEX_LOGIN in c["user"]["login"] and not c.get("in_reply_to_id")
            ]
        )
        status = "OK" if not unaddressed else f"未処理 {len(unaddressed)} 件"
        print(f"PR #{pr}: Codex指摘 {codex_total} 件 / {status}")
        for c in unaddressed:
            print(f"    ✗ {c['path']}:{c.get('line')}  {c['html_url']}")
        total_unaddressed += len(unaddressed)

    print()
    if total_unaddressed:
        print(f"取りこぼし {total_unaddressed} 件。各コメントに証跡付きの返信"
              "（コミットSHAを `...` で囲む、または #N を含める）を打って紐づけろ。")
        return 1
    print("取りこぼしなし。全Codex指摘に対応証跡が紐づいている。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
