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

内部では frontend を同梱した backend を **1プロセス(:8008)** で立てている（Vite dev
サーバは不要）。WSL から直接なら:

```bash
./start.sh          # frontend/dist を配信する backend を :8008 で立て、ブラウザを開く
```

初回セットアップ（マルチPC再現）:
1. `backend/.venv` を用意（下の「開発」参照）、`frontend` で `npm install`
2. `launcher/cad-viewer.vbs` を Windows デスクトップにコピー
   （WSL distro 名が `Ubuntu-24.04` 以外なら vbs 内を編集）
3. `./start.sh` を一度叩くと `frontend/dist` が自動ビルドされる

> single-server の仕組み: `frontend/dist` が存在すると `backend/app/main.py` が
> それを `/` にマウントして配信する（`/api/*` は既存ルートが優先）。dist が無い開発
> 時は下記の dev サーバ構成にフォールバックする。

## 開発

```bash
# backend (WSL2) — Python 3.11+ (新PCは 3.12 で動作確認済み)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/uvicorn app.main:app --reload --port 8008

# frontend（HMR 付き dev サーバ）
cd frontend
npm install
npm run dev        # http://localhost:5173 （/api は 8008 にプロキシ）

# テスト
cd backend && .venv/bin/pytest
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
