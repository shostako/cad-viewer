# CLAUDE.md

Claude Code（手元の CLI でも claude.ai/code のクラウドでも）がこのリポで作業するときの手引き。

## 概要

自作 CAD ビューア（閲覧専用・形状編集なし）。STEP/IGES・STL/3MF・DXF/DWG の閲覧、B-rep の真値での計測、注記、断面、肉厚チェック。利用者は射出成形の技術者（導光板、PMMA/PC）で、お客さんから受け取った CAD の確認が主な用途。

いまは改善を進めている最中で、計画と進み具合は GitHub の issue #59（受入確認・見積もり・改訂確認の要件。P1 は済み、残りは P2）と #47（ブラッシュアップ 3。残りは項目 8 の版の比較で、#59 の P2 と同じ物）にある。最初の計画の #8 は 10-12 に閉じた。進め方は下の「改善の進め方」。

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
(cd frontend && npm run build:web)   # Web 版（frontend/dist-web、backend 無し）
(cd frontend && npm test)            # Web 版の計算を backend と突き合わせる（backend/.venv が要る）

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

CI（`.github/workflows/test.yml`）が PR と master で、pytest・ビルド・E2E を全部回す（Windows のインストール版は別の `windows.yml`、下の節）。Web 版は、`npm test` と、`e2e (web 0)`〜`e2e (web 3)` のジョブ（Web 版を Vite の開発サーバーで配り、backend を立てずに `e2e/web_scripts.txt` の本を 4 本おきに流す。打ち切りは 40 分。段が進んだら一覧に足す）。master に入ると `pages.yml` が Web 版を GitHub Pages に配る。E2E は 4 つの並列のジョブ（`e2e (0)`〜`e2e (3)`）に分け、名前順の一覧から 4 本おきに取る（1 つのジョブでは 40 分の打ち切りに迫った）。1 本あたりの打ち切りは 600 秒（`E2E_SCRIPT_TIMEOUT`。GitHub の実行機は速さが 2 倍ほど違い、遅い実行機では 300 秒に届く本がある）。

### Windows のインストール版

- 入口は `backend/app/desktop.py`。:8018 で立て（8008 は WSL の start.sh の分）、データは `%LOCALAPPDATA%\cad-viewer`（`app/paths.py` が `CAD_VIEWER_DATA_DIR` と `CAD_VIEWER_DIST` を読む）、通知領域にアイコン（pystray）。2 つ目の起動はブラウザを開くだけ。
- 固め方は `packaging/windows/`（PyInstaller の spec と取り込みの hooks、Inno Setup の台本、`smoke.py`）。`.github/workflows/windows.yml` が、それを触る PR で作って試し、版のタグで GitHub の Releases に載せる。
- 手元で固めるには Windows 側の Python 3.12 が要る。WSL のツリーは C: 側にコピーしてから回す（UNC の上では回さない）。exe の確かめは `smoke.py <exe>`（自己点検 `--self-check`、STEP・肉厚・厚肉・サイドカー・DXF、2 つ目の起動、ポートが埋まっているとき）。
- 依存を足したら Windows の exe でも試す。delvewheel の DLL の置き場（`*.libs`）や、`importlib.metadata` で自分の版を読むパッケージは、hooks が要ることがある（embreex がそうだった）。

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

## 改善の進め方（issue #59・#47）

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
- **マージ** — CI が緑で、レビューの指摘が片付いたら、squash でマージしてよい（ユーザー了承済み）。マージしたら、計画の issue（#59・#47）のチェックを PR の番号付きで更新する。
- **記録** — 作業の要点を `logs/yyyy-MM.md` に残す（`## yyyy-MM-dd 作業概要`）。後の作業で役に立つ教訓は、同じ日の節に「記憶候補」として書く（手元で取り込む）。

## 版と変更履歴

- 変更履歴は `CHANGELOG.md`（Keep a Changelog 1.1.0 の日本語版、セマンティック バージョニング、0.x 系）。利用者向けに、画面や振る舞いで何が変わったかを平易な日本語で書く。各版の先頭に要点を太字で 1 文、分類は 追加／変更／修正／削除、1 つの変更は 1〜2 行で PR の番号を付ける。関数名などの内部の話は書かない。
- 版の番号は、CHANGELOG の一番上の版、`backend/app/__init__.py` の `__version__`、`backend/pyproject.toml`、`frontend/package.json` と `package-lock.json`（先頭と `packages[""]`）でそろえる。`backend/tests/test_version.py` が確かめる。`GET /api/health` は `{"status": "ok", "app": "cad-viewer", "version": …}` を返す（`app` はインストール版の 2 回目の起動が 1 回目を見分ける印）。
- **機能の PR は CHANGELOG に触らない。** 並行の PR が同じ所に書いて衝突し、そのたびに CI をやり直すことになるため。
- **版を出すとき** は、版の PR（枝 `release/vX.Y.Z`）で次をする。
  - 前のタグから後にマージされた PR（`git log vPREV..origin/master --oneline`）を元に、CHANGELOG の先頭に `## [X.Y.Z] — yyyy-MM-dd`（出した日、東京時間）の節を書き、末尾に比較のリンクを足す。新しい機能があればマイナー、直しだけならパッチを上げる。
  - 版の番号を上げる。frontend の 2 つは `(cd frontend && npm version X.Y.Z --no-git-tag-version)` でそろう。
  - マージの直前に master が進んでいたら、載せ直して、増えた PR を節に足す（タグに入る変更と節をそろえる）。
  - マージしたら、ほかの PR をマージする前に、その squash のコミットに注釈付きタグを打って push する（`git tag -a vX.Y.Z <sha> -m "vX.Y.Z" && git push origin vX.Y.Z`）。先にほかの PR が入ると master の先頭が版のコミットでなくなり、先頭にタグを打つ取り違えが起きやすい（タグは必ず版の squash のコミットに打つ）。
  - タグを push すると `windows.yml` が Windows のインストーラーを作り、その版の Release（無ければ CHANGELOG の節から作る）に載せる。終わったら Release に `cad-viewer-setup-X.Y.Z.exe` が付いたかを確かめる。

## アーキテクチャ

```
[backend] FastAPI + OCP(OpenCASCADE) ──HTTP──> [frontend] ブラウザ (Three.js r185 + lil-gui + TypeScript)
          B-rep 読込・テッセレーション・真値計測           描画・ピッキング・UI
```

**設計原則: メッシュは表示用の嘘、計測は B-rep の真実。**
フロントのメッシュには faceId/edgeId（`TopTools_IndexedMapOfShape` の index）が付き、サーバ側の B-rep と 1:1 で対応する。点間・エッジ長・面間・穴径の計測は必ず `POST /api/models/{id}/measure` でサーバ側の OCCT が計算する。フロントで座標から寸法を出してはいけない。

例外は肉厚で、`GET /api/models/{id}/thickness.bin?method=ray|ball` が**表示用メッシュ**の上で trimesh＋embree を使って頂点ごとに出す（B-rep の真値ではない）。

### backend（`backend/app/`）

- `paths.py` — データ（`.cache`・`.sidecars`）と frontend の置き場所。手元のツリーではリポの中、インストール版では環境変数で指された所
- `desktop.py` — Windows のインストール版の入口（上の「Windows のインストール版」）
- `main.py` — 全 API ルート。`frontend/dist` があれば `/` に配信する（`/api/*` が優先）。B-rep は、ディスクキャッシュから復元したモデルでは初めての計測のときに読み直す（`_brep_meshes`）
- `loaders.py` → `tessellation.py` → `meshpack.py` — 形式ごとの読み込み → ID 付きのテッセレーション → バイナリ化
  - `polygons.py` — OBJ・PLY・OFF の角が 4 つ以上の面の分け方（#87）。trimesh は先頭の角からの扇形で分けるので、凹んだ面で扇形が面の外に出るときだけ、ファイルの面を自分で読み直して耳切りで分ける。trimesh が読めないファイル（角の数がまちまちの OFF と二進の PLY）も、ここで Web 版と同じに読む。Web 版の `local/polygons.ts` と同じ手順（1 歩ずつそろえてある。変えるなら両方）
  - `tessellation.merge_loose_shapes` — 最上位のバラバラの面（IGES に多い）を縫い合わせて 1 つの形にし、閉じればソリッドにする。バラバラの曲線は「曲線（N 本）」の 1 部品にまとめる
- `measure.py` — OCCT での計測（distance、edge_info、face_info、faces：全部の面の face_info）
- `thickness.py` — 肉厚（レイ法とローリングボール法）。表示用メッシュで計算する
- `projection.py` — 投影面積（型締力の目安）。表示用メッシュの影をビットマップに塗って数える。向きは X・Y・Z か、任意の向き（`dir=x,y,z`。向きに垂直な 2 本の軸は `basis`、Web 版の `local/projection.ts` と同じ作り方）
- `thick.py` — 厚肉（`GET /thick`・`/thick.bin`）。部品の中に格子を並べ、表面までの距離（scipy の距離変換）から、面ごとの肉厚・一般部の肉厚（面の最頻値）・肉だまり（一般部の何倍もの球が入る所）を出す。格子はモデルごとに覚える（`entry.extra["thick_fields"]`）。B-rep の部品が閉じているかは `/properties` の判定に任せる（表示用メッシュは曲面の継ぎ目に髪の毛ほどの隙間があり、三角形で見ると開いて見える）。`/properties` はロックの外で先に呼ぶ（B-rep の読み直しが `entry.lock` を取るので、中で呼ぶと止まる）
- `drawing.py` — DXF/DWG → SVG。DWG は ODA File Converter（無料、手動で入れる、再配布不可）が PATH に必要。日本語の字（#90）: ezdxf は PC に無いフォントを DejaVu Sans に置き換え、フォントに無い字を四角で描く（書式でフォントを指定した MTEXT は 1 字も描かない）。日本語を描くスタイルと MTEXT のフォント指定のうち、日本語の無い物を、`CJK_FONTS` の最初に見つかった物に差し替える（ラテン文字だけのスタイルは変えない）。`CAD_VIEWER_FONT_DIRS` で足したフォントの置き場も見る（テストと Web 版は Noto Sans JP）。R2007 より前の DXF で文字コードの宣言（`$DWGCODEPAGE`）が無く、文字が Shift_JIS と読めて仮名か全角を含むものは、ANSI_932 として読む（宣言が無いと ezdxf は ANSI_1252 で読み、日本語が全部化ける）。ezdxf が曲線を作れない SPLINE（同じ所の通過点が続くとゼロ除算）は、続いた点を除く→だめなら同じ画層・色・線種の折れ線に置き換える→点が 2 つ未満なら外す。それ以外の描画の失敗も 500 でなく 422 で理由を返す
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
- `frame.ts` — 座標系（3 回のクリック）と、抜き勾配の型開き方向を面・稜線から選ぶ 1 回のクリック（`startPull`）。どちらも backend の B-rep の真値（vertex_info・edge_info・face_info）から向きを取る。main の配線（クリック、Esc、先選び）は `frameTool.active` を見て両方に効く
- `materials.ts` / `materialpop.ts` — 材料と用途（射出成形／一般）。材料ごとの一般的な基準（比重・肉厚の下限・勾配と根拠。出典は `docs/material-basis.md`）、直した値の保存、材料の基準のカード。判定の基準の初めは材料に合わせる（PMMA 0.64 mm・0.5°）。1.5 mm・1.0° を前提に書いた E2E は `nav_common.classic_basis` で「手で決める」を明示してから始める
- `api.ts` / `model.ts` / `tree.ts` — API の呼び出し、メッシュの読み取り結果、部品ツリー
- `compare.ts` / `compareworker.ts` / `compareview.ts` — 版の比較（`docs/designs/compare.md`）。2 つの版の表示用メッシュを細かく割り、相手の面までの距離と、外か中か（角度で重み付けした擬似法線）を Worker で出す。backend には無い（手元の版も Web 版もブラウザの中で同じ計算をする）。比べている間、viewer は開いている版の面を隠して比較の面（`setStandIn`）を出す
- `align.ts` / `aligntool.ts` — 版の比較の位置合わせ（`docs/designs/align.md`）。両方の版で同じ基準（平面・軸・円・点。値は `face_info`・`edge_info`・`vertex_info` の B-rep の真値）を同じ順に選び、選んだ順を優先に比べる版を動かす（3-2-1）。`align.ts` は解き方だけ（DOM なし、単体テスト）、`aligntool.ts` はクリックの段取り。比べる版の上のクリックは、`viewer.standInParts` が作る面と稜線に、それ用の `Picker`（`PickSource` を渡す）で拾う。動かした比べる版で比べ直す（main の `runComparison`）
- `facecompare.ts` — 版の比較の面の変化（`docs/designs/compare-faces.md`）。計測の問い `{"type": "faces"}`（全部の面の `face_info` と番号。backend の `measure.faces`、Web 版の `Measurer.faces`）の答えを 2 つの版で組にし、同じ・動いた・大きさ・形・片方だけに分ける。比べる版の面は位置合わせの動きで移してから。純粋（DOM なし、単体テスト）
- `autoalign.ts` / `alignworker.ts` — 版の比較の自動の合わせ（`docs/designs/align.md` の段 2）。ファイルのままの位置・主軸を重ねる置き方・基準の合わせ（回りが残れば、その軸のまわりに回した物も）から、点から面の ICP で詰める（Worker、three-mesh-bvh）。重みの幅を許容まで狭め、最後は許容の中の点だけ（形の変更は合わせに使わない）。同じくらい合う置き方（対称な形）は全部返し、動きの小さい順に並べる
- `undercut.ts` / `undercutworker.ts` / `undercutview.ts` — アンダーカットの候補（`docs/designs/undercut.md`）。部品ごとに、細かく割った面の点から型開き方向の上下へ光線を飛ばし、同じ部品に当たるかで分ける（Worker、three-mesh-bvh、backend には無い）。表示は版の比較と同じく `setStandIn`（面に部品の番号を持たせ、`setPartVisible` で一緒に出し入れする。隠したモデルのピックは効くので、計測はそのまま使える）。光線の出発点は、面から法線の向きに少し離し、面の中へも少しずらす（縁や角の点から出す光線は境目をなぞって、隣の床などに当たる）。問題の一覧の「アンダーカット」は `undercutPlaces` で所にまとめる。光線の計算は、色の表示と問題の一覧で共用する（main の `reachNow`。鍵はモデルと型開き方向）
- `engine.ts` — 計算をどこでするか（Web 版の境目、`docs/designs/web-version.md`）。`api.ts` はここを通してだけ backend の道（`/api/...`）を呼ぶ。HttpEngine（fetch と、送った量の分かる XMLHttpRequest）と、Web 版の LocalEngine（`local/`）。どちらかはビルドで決まる（`VITE_CAD_ENGINE=local`、`npm run build:web`）。`api.ts` に `fetch` を直に書き足さない
- `local/` — Web 版の計算（Worker の中の backend）。`backend.ts` が backend と同じ道・状態コード・本文で答える。まだ無い道は 501 と「Web 版ではまだ使えない」。backend の Python を写したもの（`meshload.ts`＝loaders、`polygons.ts`＝polygons、`smooth.ts`＝trimesh の smooth_shade、`meshprops.ts`＝properties のメッシュの分、`brep.ts`＝tessellation、`measure.ts`＝measure、`brepprops.ts`＝properties の B-rep の分、`thickness.ts`＝thickness（embree の代わりに three-mesh-bvh。隣の面に沿って出るレイを embree は当たりとして拾い、three-mesh-bvh は拾わないので、角の頂点だけ Web 版に値が出る）、`thick.ts`＝thick（距離変換は Felzenszwalb の方法）、`projection.ts`＝projection。2D 図面は写さず、`drawing.ts` が backend の `drawing.py` そのものを Pyodide（314.0.7）の上の ezdxf 1.4.4 で動かす（SVG は backend と一字まで同じ）。Pyodide とその部品・ezdxf・フォント・`drawing.py` は `frontend/scripts/web-assets.mjs` が `web-public/py/` に置く（git に入れない。`npm run dev:web`／`build:web` が呼ぶ。版と sha256 はそこで固定。ezdxf の版は `backend/requirements.lock` とそろえる）。STEP/IGES の読み込みは `meshcache.ts` が OPFS に残し（キーは中身＋`CACHE_VERSION`＋版）、当たれば B-rep は計測と体積のときに読み直す（backend の `_brep_meshes` と同じ）。アプリとしての仕掛け（Service Worker の登録、`launchQueue`）は `src/webapp.ts`。Service Worker の本体は `frontend/scripts/sw.js` で、`vite.config.ts` がビルドのときに `dist-web/sw.js` に書く（ネットを先に見て、無ければ取っておいた物。開発サーバーでは動かない）。manifest とアイコンは `frontend/web-public/`（`py/` だけ git に入れない）。ビルドしたものの E2E は `e2e/test_web_offline.py`（`CAD_VIEWER_WEB_BUILD` にビルドの置き場 `frontend/dist-web` を渡すと、自分で配り、「オフライン」は配るのを止めて試す。Playwright の `set_offline` は Worker の通信を切らない。無ければ飛ばす）STEP/IGES は libcascade 3.0.2（OCCT 8.0.1 の WASM、版は固定、初めの STEP/IGES のときに 43 MB（gzip 12 MB）を読む）なので、**backend の計算を変えたら、ここも同じに変える**（部品や面の番号を変えたら `brep.ts` も。CACHE_VERSION と同じ理由）。libcascade の作法: 列挙は名前の文字列（`'GeomAbs_Circle'`）、数の出力の引数は結果のオブジェクトで返る（`LowerDistanceParameters()` は `{U, V}`）、オブジェクトの出力の引数はその場で埋まる、同じ引数の数の多重定義は思った方が選ばれないことがある（`GCPnts_TangentialDeflection` は 3 引数で呼ぶ）、テンプレートの別名は長い名前でしか無いことがある（`Extrema_ExtPC`）。`frontend/tests/*.test.ts`（`npm test`）が、同じファイルを `scripts/engine_golden.py`（backend の手続き）と突き合わせる（計測は、モデルの全部の面・稜線・頂点にかけた問いと答えで）。Node が TS をそのまま走らせるので、`local/` の中の import には `.ts` を付ける

## 既知の罠（変更時に壊しやすい）

- **three.js は 0.185.1 に固定（`^` なし）。** 断面キャップのステンシル方式が three.js の更新で壊れた前科がある。更新したら必ずキャップの描画を目で確かめる。壊れたら GUI の「キャップ」を OFF にすれば逃げられる
- **three-mesh-bvh は `computeBoundsTree({ indirect: true })` が必須**（picking.ts）。indirect でないと三角形が並べ替えられ、`hit.faceIndex` → faceRanges の対応が崩れる。E2E のピックのテストがこれを固定している
- **読み込みの結果（部品や面の番号）を変えたら `backend/app/cache.py` の `CACHE_VERSION` を上げる。** 上げないと、古いキャッシュのメッシュと計測時の読み直しで番号が食い違い、計測が別の面に当たる。Web 版の `frontend/src/local/meshcache.ts` の `CACHE_VERSION` も同じ値に上げる（`npm test` がそろっているかを確かめる）
- **lil-gui は自分のパネルの中の keydown を外へ流さない。** キー操作は `main.ts` で window の捕捉段階（capture）で受けている。bubbling に戻すと、視点ボタンを押した直後に矢印キーが効かなくなる
- pytest の `test_drawing.py` の DWG の案内のテストは、ODA File Converter が入っている環境（手元）では skip される。1 本の skip は正常。ODA の無いクラウドと CI では走る
- **テストは本番のデータ置き場に書かない。** pytest は `backend/tests/conftest.py` がセッション単位で `.sidecars` と `.cache` を一時ディレクトリに差し替えている。E2E は実際のサーバーを使うので `backend/.sidecars/` に書く。そこには手元で開いた実データの計測・注記も入るので、後片付けはテストデータの分だけにする（上の「コマンド」の手順。ファイル名は中身の sha256 の先頭 32 文字）。多くの E2E は自分専用のコピー（末尾に改行を足したもの）か `page.route` で共有のサイドカーを避けている
- ヘッドレス Chromium（SwiftShader）の写真で、操作パネルの近くや右下に白い四角が出るのは WebGL の合成の副作用で、実ブラウザでは出ない。絵文字が豆腐になるのもヘッドレスだけ。どちらもバグではない
- シェルで `cd dir && nohup cmd &` と書くと `&` が列全体にかかり、`$!` が cmd でなく中継のサブシェルの pid になる。`(cd dir || exit; nohup cmd & echo $!)` と分ける
- **E2E は、アプリの道（`/api/...`）を `page.route`・`page.on("request")`・`page.request` で直に触らない。** `e2e/engine_net.py`（`Net.of(page).route` など、`engine_net.api`・`upload`）を使う。Web 版（`CAD_VIEWER_ENGINE=local`）には HTTP が無く、ページの中の Engine の前で同じことをする。手元の版では `page.route` などそのまま
- **`vite preview` は `server.proxy` を受け継ぐ。** Web 版（mode web）は proxy を空にしてある。外すと、Web 版の E2E の補助が手元で動いている backend（:8008）に届き、本番のサイドカーの置き場にテストの分を書く（一度やった）
- パイプは終了コードを飲む（pipefail は既定で off）。`cmd | tail && git commit` は cmd が失敗しても進む。終了コードは変数に取る
