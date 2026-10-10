## 何を

版 0.5.0 を出す PR。CHANGELOG.md に 0.5.0 の節を足し、版を 0.5.0 にそろえる（frontend/package.json、package-lock.json の 2 か所、backend/app/__init__.py、backend/pyproject.toml）。

0.5.0 に入るもの: #31（2D 図面の寸法と計測の一覧）、#32（見た目の決まり）、#34（寸法線をクリックした所に）、#35（部品ツリー）、#37〜#45（右半分の窓、写せる計測の一覧、ツールバーとキー、断面を mm で、視点の動き、描画を止める、札の重なり、タブの題名、角度）。#33 はテストだけなので書いていない。

## なぜ

issue #23 の後半と「あとで」の分がそろったところで版を区切る（CLAUDE.md の「版と変更履歴」の手順。機能の PR は CHANGELOG に触らず、版の PR で書く）。

## どう確かめたか

- backend/tests/test_version.py が通る（6 か所の版、CHANGELOG の見出しの順と日付、比較のリンク）
- 版の表示（キー操作の一覧の下）は frontend/package.json の版を読む

## マージのあと

- この PR の squash のコミットに `git tag -a v0.5.0 <sha> -m "v0.5.0"` → `git push origin v0.5.0`
- 日付（2026-10-10）は、マージする日がずれたらその日に直す

## 積み重ね（スタック）について

- この PR のベースは #45 の枝 `stack/15-angle`。積み重ねの最後で、全部がマージされてから master に載せ直して CI を回す
- マージの順: #36 → #33 → #32 → #31 → #34 → #35 → #37 → #38 → #39 → #40 → #41 → #42 → #43 → #44 → #45 → この PR

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01CHPHRwsceopmPgHJS2ZD4n
