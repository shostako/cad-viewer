# CLAUDE.md

Claude Code（手元の CLI でも claude.ai/code のクラウドでも）がこのリポで作業するときの手引き。

## 概要

自作 CAD ビューア（閲覧専用・形状編集なし）。STEP/IGES・STL/3MF・DXF/DWG の閲覧、B-rep の真値での計測、注記、断面、肉厚チェック。利用者は射出成形の技術者（導光板、PMMA/PC）で、お客さんから受け取った CAD の確認が主な用途。

いまは改善を進めている最中で、計画と進み具合は GitHub の issue #8「ブラッシュアップ計画」にある。進め方は下の「改善の進め方」。

## コマンド

```bash
# リポのルートで実行する。cd はサブシェルの中だけで効く（続けて流してもずれない）

# セットアップ（backend の依存は requirements.lock から入れる）
(cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock)
(cd frontend && npm ci)
# E2E 用（CI と同じく backend の venv に入れる。chromium のシステム依存も入れる）
backend/.venv/bin/pip install playwright==1.58.0
backend/.venv/bin/python -m playwright install --with-deps chromium

# テストデータの生成（生成物は git に入れない。OCP を使うので backend の venv で）
for g in make_testdata make_step_assembly make_dxf make_iges_loose; do backend/.venv/bin/python testdata/$g.py; done

# 開発（2 プロセス。それぞれ別の端末で）
(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8008)
(cd frontend && npm run dev)        # :5173、/api は 8008 にプロキシ

# backend のテスト
(cd backend && .venv/bin/pytest -q -p no:cacheprovider)
(cd backend && .venv/bin/pytest tests/test_measure.py -k test_name)   # 1 本だけ

# frontend の型チェックとビルド
(cd frontend && npm run build)

# E2E（Playwright。各スクリプトは独立して動く。終了コード 0 で合格）
# backend と Vite の両方が要る。exec で立てるので、ジョブの pid がサーバー本体になる
# （npx 経由だと npx だけが止まり、Vite が残って次の --strictPort が衝突する）
(cd backend && exec .venv/bin/uvicorn app.main:app --port 8008) > /tmp/uvicorn.log 2>&1 &
(cd frontend && exec node_modules/.bin/vite --host 127.0.0.1 --port 5183 --strictPort) > /tmp/vite.log 2>&1 &
up() { curl -sf --connect-timeout 1 -m 3 http://127.0.0.1:8008/api/health >/dev/null && curl -sf --connect-timeout 1 -m 3 http://127.0.0.1:5183/ >/dev/null; }
for _ in $(seq 1 90); do up && break; sleep 1; done; up || echo "servers did not come up"
backend/.venv/bin/python e2e/test_stl_view.py    # 接続先は CAD_VIEWER_URL で変えられる（既定 http://127.0.0.1:5183）
for t in e2e/test_*.py; do backend/.venv/bin/python "$t" || echo "FAILED: $t"; done
kill %1 %2    # 止める
# E2E は backend/.sidecars/ にテストデータの分を書く。丸ごとは消さない（手元で開いた
# 実データの計測・注記も同じ場所にある）。消すのはテストデータの分だけ
for f in testdata/*.step testdata/*.stl testdata/*.dxf testdata/*.igs; do
  rm -f "backend/.sidecars/$(sha256sum "$f" | cut -c1-32).json"
done
```

CI（`.github/workflows/test.yml`）が PR と master で、pytest・ビルド・E2E を全部回す。E2E は 4 つの並列のジョブ（`e2e (0)`〜`e2e (3)`）に分け、名前順の一覧から 4 本おきに取る（1 つのジョブでは 40 分の打ち切りに迫った）。1 本あたりの打ち切りは 600 秒（`E2E_SCRIPT_TIMEOUT`。GitHub の実行機は速さが 2 倍ほど違い、遅い実行機では 300 秒に届く本がある）。

### 手元（WSL2 ＋ Windows）だけのもの

- `./start.sh` — 日常の起動。frontend を同梱した backend を :8008 で 1 プロセスとして立て、Windows のブラウザを開く。
  - ソースが `frontend/dist` より新しければビルドし直す。自分で立てた backend は、コードが新しければ立て直す（pid は `/tmp/cadviewer.pid`）。
  - 同時に 2 本走らないよう `flock` で順番に並べる。ログは `/tmp/cadviewer.log`。
  - 起動のたびにブラウザのタブを開くので、テストやスクリプトから呼ばない。
- `launcher/cad-viewer.vbs` — Windows のデスクトップ用。既定の WSL ディストロで start.sh を呼ぶ。
- WSL の mirrored モードでは、誰も聴いていない 127.0.0.1 のポートへの接続が拒否されずに待たされる。curl などには必ずタイムアウトを付ける（`--connect-timeout 1 -m 3`）。

## クラウド（claude.ai/code）で作業するとき

- 手元専用のもの（start.sh、launcher、Windows のブラウザ）は使わない。上の「コマンド」で venv を作り、uvicorn と Vite を自分で立てて、E2E はヘッドレスで回す。
- Playwright のブラウザが入っていなければ `python3 -m pip install playwright pillow && python3 -m playwright install --with-deps chromium`。ネットワークの制限で入らないときは、E2E は CI に任せ、PR の本文にそう書く。
- お客さんの CAD ファイルはリポにもクラウドにも置かない。実データでしか確かめられないことは、PR の本文に「手元で確認してほしいこと」として書き残す（手元に戻ったときに確かめる）。
- `.github/workflows/` は push できない（Claude の GitHub App に workflows 権限が無い）。CI を変えたいときは、PR の本文に案を書く。

## 改善の進め方（issue #8）

- **1 項目 1 PR。** 枝は master から切る（例: `feat/a1-fit-zoom-pivot`）。master に直接コミットしない。
- **設計の下書き** が `docs/designs/` にあるもの（A1、C1）は、そこから始める。下書きは批評の前の段階なので、実物のコードと照らして直してから実装する。
- **テスト** — 新しい振る舞いには E2E か pytest を付ける。
  - 合否の基準は、検査する対象のコードから導かない。画面への投影（`window.__cadProject`）、ピック（`__cadPick`）、画素、作り方の分かっている形状の寸法など、独立したものを使う。
  - 足したテストが壊れたコードを検出できるかを、作業ツリーの**複製**の上で変異（わざと壊した版）を入れて確かめる。作業ツリーそのものは壊さない。
  - 既存の pytest・E2E・ビルドが全部通ること。
- **PR** — 本文は日本語で、何を・なぜ・どう確かめたか。Codex が PR を開いた時点で自動でレビューする。
  - 指摘を直したら、そのインラインコメントに修正のコミット SHA をバッククォートで囲んで返信する（`scripts/audit_codex_review.py` がこれで対応済みを判定する）。
  - 誤検知だと判断したときは、`@codex` を付けて根拠を書く。
  - 直し終えたら、PR に `@claude` で再レビューを頼む。
- **マージ** — CI が緑で、レビューの指摘が片付いたら、squash でマージしてよい（ユーザー了承済み）。マージしたら issue #8 のチェックを更新する。
- **記録** — 作業の要点を `logs/yyyy-MM.md` に残す（`## yyyy-MM-dd 作業概要`）。後の作業で役に立つ教訓は、同じ日の節に「記憶候補」として書く（手元で取り込む）。

## 版と変更履歴

- 変更履歴は `CHANGELOG.md`（Keep a Changelog 1.1.0 の日本語版、セマンティック バージョニング、0.x 系）。利用者向けに、画面や振る舞いで何が変わったかを平易な日本語で書く。各版の先頭に要点を太字で 1 文、分類は 追加／変更／修正／削除、1 つの変更は 1〜2 行で PR の番号を付ける。関数名などの内部の話は書かない。
- 版の番号は、CHANGELOG の一番上の版、`backend/app/__init__.py` の `__version__`、`backend/pyproject.toml`、`frontend/package.json` と `package-lock.json`（先頭と `packages[""]`）でそろえる。`backend/tests/test_version.py` が確かめる。`GET /api/health` は `{"status": "ok", "version": …}` を返す。
- **機能の PR は CHANGELOG に触らない。** 並行の PR が同じ所に書いて衝突し、そのたびに CI をやり直すことになるため。
- **版を出すとき** は、版の PR（枝 `release/vX.Y.Z`）で次をする。
  - 前のタグから後にマージされた PR（`git log vPREV..origin/master --oneline`）を元に、CHANGELOG の先頭に `## [X.Y.Z] — yyyy-MM-dd`（出した日、東京時間）の節を書き、末尾に比較のリンクを足す。新しい機能があればマイナー、直しだけならパッチを上げる。
  - 版の番号を上げる。frontend の 2 つは `(cd frontend && npm version X.Y.Z --no-git-tag-version)` でそろう。
  - マージの直前に master が進んでいたら、載せ直して、増えた PR を節に足す（タグに入る変更と節をそろえる）。
  - マージしたら、ほかの PR をマージする前に、その squash のコミットに注釈付きタグを打って push する（`git tag -a vX.Y.Z <sha> -m "vX.Y.Z" && git push origin vX.Y.Z`）。先にほかの PR が入ると master の先頭が版のコミットでなくなり、先頭にタグを打つ取り違えが起きやすい（タグは必ず版の squash のコミットに打つ）。

## アーキテクチャ

```
[backend] FastAPI + OCP(OpenCASCADE) ──HTTP──> [frontend] ブラウザ (Three.js r185 + lil-gui + TypeScript)
          B-rep 読込・テッセレーション・真値計測           描画・ピッキング・UI
```

**設計原則: メッシュは表示用の嘘、計測は B-rep の真実。**
フロントのメッシュには faceId/edgeId（`TopTools_IndexedMapOfShape` の index）が付き、サーバ側の B-rep と 1:1 で対応する。点間・エッジ長・面間・穴径の計測は必ず `POST /api/models/{id}/measure` でサーバ側の OCCT が計算する。フロントで座標から寸法を出してはいけない。

例外は肉厚で、`GET /api/models/{id}/thickness.bin?method=ray|ball` が**表示用メッシュ**の上で trimesh＋embree を使って頂点ごとに出す（B-rep の真値ではない）。

### backend（`backend/app/`）

- `main.py` — 全 API ルート。`frontend/dist` があれば `/` に配信する（`/api/*` が優先）。B-rep は、ディスクキャッシュから復元したモデルでは初めての計測のときに読み直す（`_brep_meshes`）
- `loaders.py` → `tessellation.py` → `meshpack.py` — 形式ごとの読み込み → ID 付きのテッセレーション → バイナリ化
  - `tessellation.merge_loose_shapes` — 最上位のバラバラの面（IGES に多い）を縫い合わせて 1 つの形にし、閉じればソリッドにする。バラバラの曲線は「曲線（N 本）」の 1 部品にまとめる
- `measure.py` — OCCT での計測（distance、edge_info、face_info）
- `thickness.py` — 肉厚（レイ法とローリングボール法）。表示用メッシュで計算する
- `drawing.py` — DXF/DWG → SVG。DWG は ODA File Converter（無料、手動で入れる、再配布不可）が PATH に必要
- `cache.py` — テッセレーションの結果を `backend/.cache/` に保存する（キー: ファイルの sha256＋パラメータ＋`CACHE_VERSION`）
- `store.py` — 読み込んだモデルをメモリに置く（LRU、同じ中身は使い回す）
- 計測と注記は、モデルごとに `backend/.sidecars/` に JSON で保存する（サイドカー。`PUT /sidecar` でまとめて保存）。ファイル名は読み込んだファイルの中身の sha256 の先頭 32 文字なので、同じ中身なら名前や置き場所が変わっても戻る。断面や表示の状態は保存しない

### バイナリメッシュの形式

`GET /api/models/{id}/mesh.bin` — `[uint32 headerLen][header JSON][buffers...]`。
バッファは部品ごとに `p{id}:positions/normals/indices/edges/vertices`。`count` は要素の数ではなく数値の数（平たく並べた長さ）。ヘッダに `parts`（name/color/faceRanges/edgeRanges）と `tree`（アセンブリの階層）。STL などのメッシュ形式も同じ「1 部品」の形にそろえる（フロントの読み取りは `frontend/src/meshpack.ts` の 1 本だけ）。

### frontend（`frontend/src/`）

- `main.ts` — 入口と UI の組み立て（lil-gui の操作パネル、キー操作、読み込みの流れ、サイドカーの保存）。E2E 用の関数 `window.__cadProject` / `__cadPick` / `__cadView` / `__cadStallMeasure` / `__cadStallSidecar` をここで公開している（E2E が使う。消すな）
- `style.css` — 見た目の決まり（トークン）は先頭の `:root` の `--cv-*`（面・枠・文字の 3 段の灰・操作の青 1 色・データの色・文字の大きさ 11/12/13/15/17 px・角・影・右の列の幅 264 px）。色や大きさは値を直に書かずにここから取る（例外は記号の大きさ（一覧の × の 14 px など）と 2〜3 px の小さな角・線）。lil-gui も自分の CSS 変数（`--background-color` など）を通して同じトークンで塗る。3D の背景 `--cv-scene`（#1d2126）は E2E の画素の検査が使うので変えない
  - 配色のライト（`theme.ts`）は、`:root[data-theme='light']` で同じトークンを定義し直す（文字は面の上で 4.5:1 以上、線と印は 3D の背景の上で 3:1 以上）。3D と 2D の描画の色（背景・グリッド・計測の線と点・先選び・断面の枠・2D の頁）は CSS ではなく `theme.ts` の `PALETTES` にあり、材質に色を持つ所は `onTheme` で塗り直す。新しく 3D や 2D に色を足すときは、この表から取って `onTheme` で塗り直す。既定はダーク（E2E はダークで走る）
- `viewer.ts` — 描画、カメラ操作（ターンテーブル＝OrbitControls、自由回転＝TrackballControls）、視点の切り替え、自動回転、グリッド
- `picking.ts` / `measure.ts` / `section.ts` / `drawing2d.ts` — ピッキング、計測と注記、断面、2D 図面
- `api.ts` / `model.ts` / `tree.ts` — API の呼び出し、メッシュの読み取り結果、部品ツリー

## 既知の罠（変更時に壊しやすい）

- **three.js は 0.185.1 に固定（`^` なし）。** 断面キャップのステンシル方式が three.js の更新で壊れた前科がある。更新したら必ずキャップの描画を目で確かめる。壊れたら GUI の「キャップ」を OFF にすれば逃げられる
- **three-mesh-bvh は `computeBoundsTree({ indirect: true })` が必須**（picking.ts）。indirect でないと三角形が並べ替えられ、`hit.faceIndex` → faceRanges の対応が崩れる。E2E のピックのテストがこれを固定している
- **読み込みの結果（部品や面の番号）を変えたら `backend/app/cache.py` の `CACHE_VERSION` を上げる。** 上げないと、古いキャッシュのメッシュと計測時の読み直しで番号が食い違い、計測が別の面に当たる
- **lil-gui は自分のパネルの中の keydown を外へ流さない。** キー操作は `main.ts` で window の捕捉段階（capture）で受けている。bubbling に戻すと、視点ボタンを押した直後に矢印キーが効かなくなる
- pytest の `test_drawing.py` の DWG の案内のテストは、ODA File Converter が入っている環境（手元）では skip される。1 本の skip は正常。ODA の無いクラウドと CI では走る
- **テストは本番のデータ置き場に書かない。** pytest は `backend/tests/conftest.py` がセッション単位で `.sidecars` と `.cache` を一時ディレクトリに差し替えている。E2E は実際のサーバーを使うので `backend/.sidecars/` に書く。そこには手元で開いた実データの計測・注記も入るので、後片付けはテストデータの分だけにする（上の「コマンド」の手順。ファイル名は中身の sha256 の先頭 32 文字）。多くの E2E は自分専用のコピー（末尾に改行を足したもの）か `page.route` で共有のサイドカーを避けている
- ヘッドレス Chromium（SwiftShader）の写真で、操作パネルの近くや右下に白い四角が出るのは WebGL の合成の副作用で、実ブラウザでは出ない。絵文字が豆腐になるのもヘッドレスだけ。どちらもバグではない
- シェルで `cd dir && nohup cmd &` と書くと `&` が列全体にかかり、`$!` が cmd でなく中継のサブシェルの pid になる。`(cd dir || exit; nohup cmd & echo $!)` と分ける
- パイプは終了コードを飲む（pipefail は既定で off）。`cmd | tail && git commit` は cmd が失敗しても進む。終了コードは変数に取る
