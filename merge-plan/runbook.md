# マージの手順（リポを公開して CI が動いてから）

順番（変えない）: #36 → #33 → #32 → #31 → #34 → #35 → 積み重ね 9 本（項目 7 → 8 の後半 → 10 → 断面 → 視点の動き → 描画を止める → 札 → タブの題名 → 角度）→ 版 0.5.0 の PR

- 衝突の解き方は git rerere が覚えている（plan 作業ツリーで squash を順に積んだときに記録済み）。載せ直しは `restack.sh` で
- 各段の状態は `plan/NN-*` の枝（手元）。plan/06 と plan/15 で E2E 全本を通してある

## 既存の 6 本（#36, #33, #32, #31, #34, #35）

1. `git fetch origin`。master に対して衝突していれば（`gh pr view N --json mergeable`）、PR の枝を master に載せ直す
   - `restack.sh <PRの枝> <その枝が土台にしていた master のコミット>`（`git merge-base origin/<PRの枝> <前の master>`。rerere が解く）
   - #35 は #32 のあとなので、載せ直したら d736787（ツリーの色をトークンに寄せる）を cherry-pick して足す
2. tsc と backend の pytest を手元で（restack.sh が流す）。push は `--force-with-lease`
3. CI（pytest・build・e2e (0)〜(3)）が緑になるのを待つ: `gh pr checks N --watch --interval 60`
4. `@claude` のレビュー（#33, #34, #35, #36 はまだ。Actions で動くので公開まで頼めなかった）。指摘を直し、インラインには SHA で返信
5. `gh pr merge N --squash`（`--delete-branch` は付けない。フックが止める）
6. #36 のあと: タグ v0.1.0〜v0.4.0（#36 の本文のコマンド。v0.4.0 は #36 の squash のコミット）→ `git push origin --tags`
7. issue #23 のチェック: #32 → 5、#31 → 12、#34 → 8（前半。後半は積み重ねの 8 の後半）、#35 → 11、#33 は 7 の準備

## 積み重ねの 9 本

ひとつ前がマージされたら:
1. その PR のベースを master に替える: `gh api -X PATCH repos/shostako/cad-viewer/pulls/N -f base=master`
2. 枝を master に載せ直す（ひとつ前の枝の分を落とす）: `restack.sh <枝> <ひとつ前の枝の、マージ前の先頭>`
3. CI → `@claude` → マージ（上の 3〜5 と同じ）
4. issue #23: 項目 7・8・10 のチェック、「あとで」の行の更新。#8 の D1 のチェック（描画を止める）

## 版 0.5.0

1. master から `release/v0.5.0`
2. `merge-plan/changelog-0.5.0.md` の PR 番号と日付を埋めて CHANGELOG.md の先頭（0.4.0 の上）へ。末尾の比較リンクに `[0.5.0]` を足す
3. 版を 5 か所（frontend/package.json、package-lock.json の 2 か所、backend/app/__init__.py、backend/pyproject.toml）で 0.5.0 に。`backend/tests/test_version.py` が通る
4. PR → CI → マージ → その squash のコミットに `git tag -a v0.5.0 <sha> -m v0.5.0` → `git push origin v0.5.0`

## 後片付け

- 手元の枝: int/open-prs、plan/*、feat/u7-half-window などの古い（int を土台にした）枝は消さずに残してよい（`git branch -D` はフックが止める）
- 立てたままの Vite・backend（5395/8048、5397/8058、5461/8068、5463/8078、5385 など）を止める
- リモートの `stack/base` は積み重ねの最初の PR の土台。項目 7 の PR のベースを master に替えたら用は済む
