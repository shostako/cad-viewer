# E2E テスト（Playwright）

前提: uvicorn (port 8008) と Vite dev server (port 5183) が起動済みで、`testdata/` に素材があること。
素材は生成物で git には入っていない（`test_iges_sewing.py` の IGES と `test_png_export.py` の `colours_drawing.dxf` は、無ければテストが backend の venv で自分で作る）。

```bash
# 素材の生成（backend の venv で。OCP を使う）
backend/.venv/bin/python testdata/make_testdata.py       # ribbed_plate.stl
backend/.venv/bin/python testdata/make_step_assembly.py  # mini_mold.step
backend/.venv/bin/python testdata/make_dxf.py            # plate_drawing.dxf, colours_drawing.dxf
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
- `test_nav_fit.py`（全体表示）・`test_nav_wheel.py`（ホイールの拡大縮小）・`test_nav_pivot.py`（ダブルクリックの回転の中心）は、共通の部品を `nav_common.py` から使う。検査用の箱の STL は一時ディレクトリに書いて使い、最後に消す。1 本にまとめると CI の 1 本あたりの打ち切り（300 秒）を超えたので分けてある。1 本は目安 2 分以内に収める
- `test_properties.py`（体積・重量のパネル）は `/properties` を持つ backend が要る。`window.__cadStallProperties(ms)` で次の 1 回の取得を遅らせ、古い応答を捨てることを確かめる
- `test_view_modes.py`（空の画面の案内、2D 図面で 3D 用の項目を隠す）は、メッシュの取得をわざと失敗させる（`page.route` で中断）ことで、前のモデルを片付けたあとの失敗で案内が戻ることを確かめる
- `test_png_export.py`（画像を保存）は、devicePixelRatio 2・時間帯 Asia/Tokyo のブラウザで、Playwright のダウンロードの仕組みで PNG を受け取り、画素を調べる。mini_mold.step は末尾に改行を足した自分専用のコピーを一時ディレクトリに作って使う（別のモデル id とサイドカーになり、共有の backend のサイドカーに触れない）。DXF は `plate.drawing.dxf` という名前のコピーで、ファイル名の規則（最後の拡張子だけを除く）を確かめる。`colours_drawing.dxf`（WIPEOUT と黄・シアンの線と文字）で、白の書き出しの色の扱いを確かめる。途中で CDP の `Emulation.setDeviceMetricsOverride` で devicePixelRatio を 1 にし（倍率の違うモニターへの移動に当たる）、画面の canvas と画像の大きさが付いてくることを確かめて 2 に戻す。期待値は、画面に出ているフレーム（canvas の toDataURL）、`__cadProject` の投影、ezdxf の背景の矩形からの DXF→SVG の対応、パネルとラベルの矩形、ラベルの中の語の DOM の範囲、白との明暗の比（WCAG の相対輝度）から出す。保存した PNG は `/tmp/cad_viewer_png_*.png` に残る
- `test_draft_angle.py`（抜き勾配）は `nav_common.py` の部品を使う。キャンバスの画素を `toDataURL`（`requestAnimationFrame` の中）で読み、支配的な色の成分（緑・赤・青）で判定する。サンプル点は `__cadProject` で投影し、`__cadPick` でその面が見えていることを確かめる。サイドカーの取得は `page.route` で空にする（共有の backend に残った計測の印が写り込むため）。勾配がちょうど 2° の錐台、壁の勾配 1° に R3 のフィレット（6 枚）が続く棒、底のない錐台（閉じていない形）の STL を一時ディレクトリに書き、6 つの型開き方向、メッシュ形式の三角形ごとの判定（勾配不足の壁が上まで赤い）、閉じていない部品の凡例の注を確かめる。肉厚との競合は `thickness.bin` の要求を `page.route` で止めて確かめ（方式の切り替えのあとの古い要求の失敗も）、止めた要求を中断する手順の "Failed to load resource" だけはエラーから除く。読み込み中に色分けを入れたときは `mesh.bin` を止めて確かめる。サイドカーの保存も `page.route` で止め、共有の backend に書かない
