# cad-viewer

自作CADビューア。STEP/IGES・STL/3MF・DXF/DWG の閲覧＋計測・注記・断面（形状編集はしない）。

## アーキテクチャ

```
[WSL2] FastAPI + OCP(OpenCASCADE) ──localhost──> [Windows] ブラウザ (Three.js + TypeScript)
        B-rep読込・テッセレーション・真値計測         描画・ピッキング・UI
```

設計原則: **メッシュは表示用の嘘、計測はB-repの真実**。
テッセレーションメッシュにはトポロジID（face/edge/vertex）を付与して配信し、計測は必ずサーバ側でOCCTの真値計算を行う。

## 起動（日常使い）

**Windows デスクトップの `cad-viewer.vbs` をダブルクリック** → backend が起動し、
既定ブラウザで開く（コンソール窓は出ない）。既に起動済みならブラウザを開くだけ（冪等）。
git pull などで frontend のソースが `dist` より新しければビルドし直し、start.sh が立てた
backend より backend のコードが新しければ backend を立て直す。

内部では frontend を同梱した backend を **1プロセス(:8008)** で立てている（Vite dev
サーバは不要）。WSL から直接なら:

```bash
./start.sh          # frontend/dist を配信する backend を :8008 で立て、ブラウザを開く
```

初回セットアップ（マルチPC再現）:
1. `backend/.venv` を用意（下の「開発」参照）、`frontend` で `npm install`
2. `launcher/cad-viewer.vbs` を Windows デスクトップにコピー
   （既定の WSL distro（`wsl.exe -l -v` で * の付いたもの）で起動するので編集は不要）
3. `./start.sh` を一度叩くと `frontend/dist` が自動ビルドされる

> single-server の仕組み: `frontend/dist` が存在すると `backend/app/main.py` が
> それを `/` にマウントして配信する（`/api/*` は既存ルートが優先）。dist が無い開発
> 時は下記の dev サーバ構成にフォールバックする。

## 画面の操作

| 操作 | マウス | キーボード |
|---|---|---|
| 回転 | 左ドラッグ | 矢印キー（押した側の面が見えてくる） |
| 移動 | 右ドラッグ | Shift + 矢印キー |
| 拡大・縮小 | ホイール（カーソルの下の点に向かって寄る） | ＋ ／ −（画面の中心に向かって） |
| 回転の中心 | モデルをダブルクリック（モードが「なし」のとき） | — |
| 全体表示 | 「全体表示」ボタン | F または Home |

全体表示はいまの向きのまま、見えている部品の全体が画面の約 9 割に収まるように寄せる（隠した部品は含めない）。新しいモデルを開いたときは斜め上からの向きで表示する。ダブルクリックした点は、向きと大きさを変えずに画面の中央へ滑らせ、以後の回転の中心になる。2D 図面では F・Home で図面全体を表示する。

右上の「表示」フォルダ:
- **グリッド**: 床の格子の表示・非表示
- **自動回転** と **回転速度**: 縦軸のまわりに回し続ける（ドラッグ中は止まる）
- **回転方式**: ターンテーブル（Z 軸を常に上に保つ。CAD の標準）／自由回転（上を越えて裏返せる）。
  自由回転で裏返した状態からターンテーブルに戻すと、Z 軸が上に戻るので画面が回って見える
- **視点**: 正面・背面・右・左・上・下・等角へ切り替える（上・下は +X が右）

グリッド・回転速度・回転方式はブラウザに記憶する。

## 開発

```bash
# リポのルートで実行する（cd はサブシェルの中だけで効く）

# backend — Python 3.11+ (新PCは 3.12 で動作確認済み)
(cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock)
(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8008)

# frontend（HMR 付き dev サーバ、別の端末で）
(cd frontend && npm ci)
(cd frontend && npm run dev)        # http://localhost:5173 （/api は 8008 にプロキシ）

# テスト
(cd backend && .venv/bin/pytest)
```

テストデータ生成: `backend/.venv/bin/python testdata/make_testdata.py`

## フェーズ計画

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | 骨組み＋STLビューア（アップロード→バイナリメッシュ配信→Three.js表示） | ✅ |
| 1 | STEP/IGES＋トポロジプロトコル（faceRanges/edges、XCAF色・アセンブリツリー、キャッシュ） | ✅ |
| 2 | ピッキング＋計測（スナップ、点間・エッジ長・面間・穴径） | ✅ |
| 3 | 断面＋注記（クリッピング、JSONサイドカー永続化） | ✅ |
| 4 | 2D（DXF/DWG→ODA変換）＋3MF | ✅ |
| 5 | 肉厚チェック（レイ法＋ローリングボール法）。性能チューニングは実データ待ち | ✅ |

詳細計画: 初期プラン参照（`~/.claude/plans/pc-cad-quizzical-barto.md`）

## バイナリメッシュプロトコル

`GET /api/models/{id}/mesh.bin` — `[uint32 headerLen][header JSON][buffers...]`
バッファは部品ごとに `p{id}:positions` / `p{id}:normals` / `p{id}:indices` / `p{id}:edges`（線分ペア）。
ヘッダに `parts`（name / color / faceRanges / edgeRanges）と `tree`（アセンブリ階層）。
STL等のメッシュ形式も同じ「1部品」形式に統一（フロントのデコードパスは1本）。
faceId/edgeId は `TopTools_IndexedMapOfShape` のindexで、サーバ側B-repと1:1対応（Phase 2の計測で使用）。

テッセレーション結果は `backend/.cache/` にディスクキャッシュされる（キー: ファイルsha256＋パラメータ）。

## 既知の注意点

- ヘッドレスChromium(SwiftShader)のスクショで右下に白矩形が出るが、WebGL合成アーティファクト（実ブラウザでは出ない）
- 断面キャップはステンシル方式（webgl_clipping_stencil）。three.jsバージョン更新で壊れる前科がある技術なので、更新時は必ずキャップの描画確認をすること。壊れたらGUIの「キャップ」をOFFにすればキャップなし断面で使える
- three.js はバージョン固定（クリッピング断面のステンシルキャップが更新で壊れる前科があるため）
- IGES など、面がバラバラのまま書き出されたファイルは、読み込み時に面を縫い合わせて 1 つの形にする（許容差 0.0001 → 0.001 → 0.01 mm の順に試し、すべて閉じたらソリッドにする。上限はモデルの対角の 1/10000）。小さい部品（対角 10 mm 未満）は 0.0001 mm の段だけを使うので、それより大きいすき間は閉じずにサーフェスのまま残る。色の違う面を縫った形は既定の色になる。縫い合わせに失敗したら、縫わずにそのまま開く。最上位のバラバラの曲線は「曲線（N 本）」の 1 部品にまとめ、黄色で描く。全体表示とサイズ表示は面を持つ形だけで決める（補助線の座標軸などで製品が小さく映らないように）
- 読み込みの結果（部品や面の番号）を変えたら `backend/app/cache.py` の `CACHE_VERSION` を上げる。上げないと、古いキャッシュのメッシュと計測時の読み直しで番号が食い違い、計測が別の面に当たる
