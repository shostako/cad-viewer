# E2E テスト（Playwright）

前提: uvicorn (port 8008) と Vite dev server (port 5183) が起動済みで、
`testdata/` に `ribbed_plate.stl`（make_testdata.py）と `mini_mold.step`（make_step_assembly.py）があること。

```bash
# サーバ起動
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8008 &
cd frontend && npm run dev -- --port 5183 --strictPort &

# 実行（システムPythonのplaywrightを使用）
python3 e2e/test_stl_view.py
python3 e2e/test_step_view.py
python3 e2e/test_measure.py
python3 e2e/test_section_annotation.py
```

注意:
- ヘッドレスChromium(SwiftShader)ではlil-gui付近に白矩形のWebGL合成アーティファクトが出る（実ブラウザでは出ない）
- `test_section_annotation.py` はサイドカーに書き込むため、`backend/.sidecars/` を消せばクリーンに戻る
- テストは `window.__cadProject` / `__cadPick` フック（main.ts）でワールド座標からクリック位置を決定論的に導出する
