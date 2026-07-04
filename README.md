# cad-viewer

自作CADビューア。STEP/IGES・STL/3MF・DXF/DWG の閲覧＋計測・注記・断面（形状編集はしない）。

## アーキテクチャ

```
[WSL2] FastAPI + OCP(OpenCASCADE) ──localhost──> [Windows] ブラウザ (Three.js + TypeScript)
        B-rep読込・テッセレーション・真値計測         描画・ピッキング・UI
```

設計原則: **メッシュは表示用の嘘、計測はB-repの真実**。
テッセレーションメッシュにはトポロジID（face/edge/vertex）を付与して配信し、計測は必ずサーバ側でOCCTの真値計算を行う。

## 開発

```bash
# backend (WSL2)
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/uvicorn app.main:app --reload --port 8008

# frontend
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
| 5 | 肉厚チェック＋性能 | — |

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
- three.js はバージョン固定（クリッピング断面のステンシルキャップが更新で壊れる前科があるため）
