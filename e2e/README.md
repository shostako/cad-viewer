# E2E テスト（Playwright）

前提: uvicorn (port 8008) と Vite dev server (port 5183) が起動済みで、`testdata/` に素材があること。
素材は生成物で git には入っていない（`test_iges_sewing.py` の IGES だけは、無ければテストが自分で作る）。

```bash
# 素材の生成（backend の venv で。OCP を使う）
backend/.venv/bin/python testdata/make_testdata.py       # ribbed_plate.stl
backend/.venv/bin/python testdata/make_step_assembly.py  # mini_mold.step
backend/.venv/bin/python testdata/make_dxf.py            # plate_drawing.dxf
backend/.venv/bin/python testdata/make_iges_loose.py     # loose_faces_box.igs

# サーバ起動
(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8008) &
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5183 --strictPort) &

# 実行（システム Python の playwright を使う。各スクリプトは独立している）
for t in e2e/test_*.py; do python3 "$t" || echo "FAILED: $t"; done
```

接続先を変えるときは `CAD_VIEWER_URL` で上書きする（既定 `http://127.0.0.1:5183`）。

注意:
- ヘッドレスChromium(SwiftShader)ではlil-gui付近に白矩形のWebGL合成アーティファクトが出る（実ブラウザでは出ない）
- 計測・注記・サイドカー系のテストはサイドカーに書き込むため、`backend/.sidecars/` を消せばクリーンに戻る
- テストは `window.__cadProject` / `__cadPick` / `__cadView` フック（main.ts）でワールド座標からクリック位置を決定論的に導出し、カメラの状態を読む（`__cadView` は near / far も返す）
- `test_navigation.py`（全体表示・ホイールの拡大縮小・ダブルクリックの回転の中心）は、検査用の箱の STL を一時ディレクトリに書いて使い、最後に消す
- `test_properties.py`（体積・重量のパネル）は `/properties` を持つ backend が要る。`window.__cadStallProperties(ms)` で次の 1 回の取得を遅らせ、古い応答を捨てることを確かめる
