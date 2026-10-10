# handoff/old-pc-2026-10-10

旧PC（WSL）の手元にしか無かったものの退避。master には入れない。

- `rr-cache/` — git rerere の記録。積み重ねの PR（#31〜#46）を順にマージするときの衝突の解き方。マージの段取りは issue #23 のコメント（2026-10-10）と `merge-plan/runbook.md`
- `merge-plan/` — マージの手順（`runbook.md`）、載せ直し（`restack.sh`）、0.5.0 の CHANGELOG の下書き、PR の本文と作り方、Codex への返信（済み）
  - `restack.sh` と `push_stack.sh` は作業ツリーを `CAD_VIEWER_WT`（既定: 今いるリポ）、backend の pytest を `PYTEST`（既定: `backend/` から見た `.venv/bin/pytest`）で受け取る
  - 積み重ねの各段は `plan/00-master`〜`plan/16-release` の枝（origin に push 済み）
- `logs/2026-10-10.md` — 作業ログの 10-10 の節（記憶候補を含む）。`logs/2026-10.md` の末尾に足す分

## 受け取る側（新PCでも、どこでも）

```bash
git fetch origin handoff/old-pc-2026-10-10
git archive FETCH_HEAD rr-cache | tar -x -C "$(git rev-parse --git-common-dir)"
git config rerere.enabled true
```

merge-plan とログは `git archive FETCH_HEAD merge-plan logs | tar -x -C <置き場所>` で取り出せる。
