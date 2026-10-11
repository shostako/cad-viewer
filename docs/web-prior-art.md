# ブラウザだけで動く CAD ビューアの先行例と道具（Web 版のための調べ物）

Web 版（backend 無しで、ブラウザの中だけで動く版）の作り方を決めるときに調べたこと。2026-10-11 に、公開資料（README、文書、ソース、ブラウザの対応表）と手元の実測で調べた。作りの計画は [designs/web-version.md](designs/web-version.md)。

- 【実測】は手元の値（WSL2、Ryzen 7 7735HS、Node 22、1 スレッド）。
- 【推測】は判断で、出典は無い。
- それ以外は出典のある事実。

このアプリが採るもの:

- **OpenCASCADE は libcascade 3.0.2**（OCCT 8.0.1。opencascade.js を引き継いだもの）の single 版を、Web Worker の中で動かす。
  - 真値の計測に要る API が全部ある（XCAF での STEP と IGES の読み込み、`TopExp.MapShapes` の番号付け、BRepExtrema・BRepGProp・BRepAdaptor）。
  - 【実測】mini_mold.step の体積・重心が backend（OCP 7.9.3）と一致した。
  - クラス名も呼び方も OCP とほぼ同じなので、backend の Python をほぼ 1 対 1 で TypeScript に写せる。
- **スレッド（SharedArrayBuffer）は使わない。** 速さは 1.2〜1.3 倍にしかならないのに、COOP/COEP のヘッダが要る。GitHub Pages ではヘッダを付けられない。
- **肉厚**は three-mesh-bvh（今も使っている）、距離変換は自作の JS。
- **DXF** は Pyodide（ブラウザの Python）の上の ezdxf で、今と同じ SVG を出す。
- **DWG** はブラウザ版では扱わない。
- **保存**は IndexedDB。

## 1. ブラウザで OpenCASCADE を動かす手段

| 手段 | OCCT | wasm（素の大きさ／gzip）【実測】 | BRepExtrema・GProp・Adaptor | XCAF の読み込み（STEP / IGES） | カスタムビルド | ライセンス | 最終更新 | スレッド | メモリの上限 |
|---|---|---|---|---|---|---|---|---|---|
| opencascade.js 1.1.1 [2][3] | 7.4.0p1 | 65.9 MB | 旧 API | 未確認 | make.py | LGPL-2.1 | 2020-09 | 単一 | 未確認 |
| opencascade.js 2.0.0-beta [1][3] | 7.6.2 | 50.3／13.7 MB | ○ | ○ / ○ | YAML＋Docker | LGPL-2.1 | 2023-03 で止まっている | 選べる | 未確認 |
| **libcascade 3.0.2**（opencascade.js v3）[4][5] | **8.0.1** | 42.7／12.2 MB | ○【実測】 | ○ / ○【実測】 | `@libcascade/toolchain`（要らないクラスを削れる、C++ を足せる） | LGPL-2.1 WITH OCCT-exception | 2026-08 | single と multi | 4 GB |
| OCCT 公式の Emscripten ビルド [6][7][8] | 自分で選ぶ | リンクした分だけ | ○（C++ で書く） | ○ | CMake を自分で組む | LGPL-2.1＋例外 | 8.0.0 で WebGL のサンプルと wasm の CI がリポから外れた | 自分で選ぶ | 自分で選ぶ |
| occt-import-js 0.0.23 [9] | 7.6.1 | 7.6／3.1 MB | ×（B-rep を残さない。三角形を返すだけ） | 名前・色・階層・面ごとの三角形の範囲（エッジは無し） | CMake を自分で直す | LGPL-2.1 | 2024-12 | 単一 | 2 GB |
| replicad-opencascadejs 1.1.0 [10] | 8 系（libcascade） | 23.0／7.2 MB | ○ | STEPControl_Reader だけ。IGES 無し | YAML | LGPL-2.1 | 2026-09 | single と multi | 4 GB |
| Chili3D の chili-wasm [11] | 8.0.1 | 10.5／4.5 MB | ○（自前の C++ の層の中で） | ○ / ○ | 自前の CMake（約 100 行、`-Oz -flto`） | モジュールは LGPL-3.0、アプリは AGPL-3.0 | 2026-09 | 単一 | 4 GB |
| occt-wasm 5.7.0 [12] | 8.0.1 | 21.1／6.7 MB | 自前の層を通す | STEP ○ / IGES × | Rust の xtask と Docker | wasm は LGPL-2.1 | 2026-10 | 単一。Worker の入口あり | 記載なし |
| @bitbybit-dev/occt 1.4.1 [13] | 未確認 | 約 31 MB（32 bit・Memory64・Memory64＋スレッドの 3 種） | 独自の上位 API | STEP/IGES の入出力 | ― | ラッパは MIT、wasm は LGPL | 2026-10 | 3 種 | 64 bit 版あり |

- **スレッド**: libcascade の multi 版は COOP/COEP のヘッダを要る。速さは全体で 1.24 倍、STEP の読み込み＋メッシュで 1.33 倍。立ち上げは 39 % 遅く、メモリは約 96 MB 増える [4]。
  - GitHub Pages はヘッダを付けられない（運営は「時期未定」）[19]。
  - coi-serviceworker は Service Worker でヘッダを足して回避するが、初回に 1 回読み直しが要る。自前の Service Worker とも同居しにくい [18][19]。
- **メモリ**: wasm32 は 4 GB まで [16]。Memory64 は Chrome 133・Firefox 134 から使える。Safari はまだで、64 bit にすると遅くなる例もある [14][15]。
  - 【推測】成形品の顧客データ（数十 MB の STEP）なら 4 GB で足りる。
- **速さ**: libcascade の自前の計測では、重い処理で native の 1.1〜1.8 倍の時間がかかる。JS から C++ を 1 回呼ぶごとに約 265 ns かかる [4]。
  - 【実測】立ち上げ 0.9 秒、mini_mold.step の読み込み＋XCAF 177 ms、メッシュ 21 ms、BRepExtrema 8 ms。

## 2. ブラウザで STEP を開く既存の Web アプリ

| アプリ | 方式 | 計測 |
|---|---|---|
| Online 3D Viewer（3dviewer.net）[22] | occt-import-js を Worker で使う。受け取るのは JSON のメッシュ | メッシュの上（当たった点と面の法線から出す） |
| Chili3D [11] | 自前の C++ の層＋OCCT 8.0.1。B-rep を wasm の中に持ち続ける。保存は IndexedDB | 長さ・角度・面積・体積（BRepGProp、BRepExtrema） |
| CascadeStudio [23] | 本人が fork した opencascade.js を、要るクラスだけに削った。GitHub Pages で配る | 形を作る道具（【実測】wasm は gzip で 21.2 MB → 転送 6.6 MB） |
| replicad / bitbybit [10][13] | libcascade 系の自前ビルド／独自ビルド | 形を作る側の API |
| Innerscene STEP Viewer [24] | OpenCASCADE の WASM（約 7.6 MB。【推測】occt-import-js と同じ大きさ） | 定規（真値かは書いていない） |
| CascadeScope（Open Cascade SAS）[25] | WASM 版を公開。ソースは非公開 | 記載なし |

B-rep の真値で測る Web 版は Chili3D だけだった。

## 3. メッシュの上の問い合わせと距離変換

【実測】トーラスノット（閉じた管、肉厚 6）で測った。

| 処理 | 96,000 三角形 | 480,000 三角形 |
|---|---|---|
| three-mesh-bvh 0.9：BVH の構築（indirect） | 48 ms | 185 ms |
| three-mesh-bvh：`raycastFirst`（頂点の数のレイ） | 4.9 万本 296 ms | 24 万本 1,437 ms |
| three-mesh-bvh：`closestPointToPoint` | 40 万点 11.1 秒 | 40 万点 17.4 秒 |
| backend の trimesh＋embree：レイ | 115 ms（three-mesh-bvh の約 2.6 倍速い） | ― |
| backend の trimesh：`on_surface`（最近点） | 4.9 万点 14.6 秒（three-mesh-bvh の約 1/10） | ― |

| 距離変換（230³ = 1,220 万点）【実測】 | 時間 |
|---|---|
| 自作の JS（Felzenszwalb の分離型、60 行ほど） | 0.53〜0.55 秒 |
| scipy の `ndimage.distance_transform_edt` | 1.0〜1.3 秒（最大値は両方とも 46.00 で一致） |

【推測】レイ法は、頂点を Worker で分ければ今と同じくらいの速さになる。ボール法は、最近点が主なので今より速くなる見込み。

## 4. DXF をブラウザで描くライブラリ

| ライブラリ | 出力 | ブロック | HATCH | 文字 | 文字コード | ライセンス |
|---|---|---|---|---|---|---|
| dxf-parser 1.1.2 [30] | 読むだけ | ○ | × | TEXT と一部の MTEXT | ― | MIT、2022 |
| dxf 5.3.1 [31] | SVG | ○ | 描かない | 描かない | ― | MIT |
| dxf-viewer 1.0.49 [32] | WebGL | ○ | 一部 | TTF を指定 | **UTF-8 だけ** | MPL-2.0 |
| mlightcad cad-viewer 1.7.5 [33] | WebGL（SVG の書き出しあり） | ○ | ○ | ○ | ― | MIT（DWG は別の LibreDWG で、GPL） |
| **ezdxf 1.4.4 on Pyodide** [34] | SVG（backend と同じコード） | ○ | ○ | フォントの同梱が要る | ezdxf が処理する | MIT／MPL-2.0 |

- 【実測】Pyodide 314.0.7 の上で、backend と同じ `Frontend`＋`SVGBackend` が plate_drawing.dxf と colours_drawing.dxf から SVG を出した。
  - Pillow が要る。立ち上げは 1.9 秒、入れるのに 1.4 秒。
  - 配る量は約 13 MB。
- 【推測】日本の古い DXF は Shift-JIS のことがあるので、UTF-8 だけのライブラリは向かない。

## 5. ファイルの保存（ブラウザの対応 [21][35][36]）

| API | Chrome / Edge | Firefox | Safari | 使い道 |
|---|---|---|---|---|
| IndexedDB | ○ | ○ | ○ | サイドカー（計測・注記）。今と同じく中身の sha256 を鍵に |
| OPFS | 86 | 111 | 15.2 | 大きなバイナリ（テッセレーションのキャッシュ） |
| File System Access（ファイルを開き直す・上書きする） | 86 | × | × | 元のファイルの取っ手を残して開き直す |
| File Handling（インストールした PWA に .step を関連付ける） | 102 | × | × | エクスプローラーから開く |
| `navigator.storage.persist()` | 55 | 57 | 15.2 | 勝手に消されないようにする |

Safari は、7 日間操作が無いとスクリプトが作ったデータを消す [35]。【推測】利用者は Windows の Chrome か Edge を使うので、Chromium だけの API も実際に使える。

## 出典

1. donalffons/opencascade.js https://github.com/donalffons/opencascade.js
2. opencascade.js v1.1.1 の README https://github.com/donalffons/opencascade.js/tree/v1.1.1
3. npm opencascade.js https://www.npmjs.com/package/opencascade.js
4. taucad/opencascade.js（libcascade）の README と BENCHMARKS.md https://github.com/taucad/opencascade.js ／ https://libcascade.xyz/
5. npm libcascade https://www.npmjs.com/package/libcascade
6. OCCT の build の文書 https://github.com/Open-Cascade-SAS/OCCT/blob/master/dox/build/build_occt/building_occt.md
7. OCCT 7.9.3 の WebGL のサンプルと wasm の CI https://github.com/Open-Cascade-SAS/OCCT/tree/V7_9_3/samples/webgl
8. OCCT のサンプルを外したコミットとリリース https://github.com/Open-Cascade-SAS/OCCT/commit/a15fed9b ／ https://github.com/Open-Cascade-SAS/OCCT/releases
9. kovacsv/occt-import-js https://github.com/kovacsv/occt-import-js
10. replicad-opencascadejs https://github.com/sgenoud/replicad/tree/main/packages/replicad-opencascadejs
11. Chili3D https://github.com/xiangechen/chili3d
12. andymai/occt-wasm https://github.com/andymai/occt-wasm
13. bitbybit の occt https://github.com/bitbybit-dev/bitbybit/tree/master/packages/dev/occt
14. WebAssembly の機能の対応表 https://webassembly.org/features/
15. SpiderMonkey「Is Memory64 actually worth using?」https://spidermonkey.dev/blog/2025/01/15/is-memory64-actually-worth-using.html
16. V8「Up to 4GB of memory in WebAssembly」https://v8.dev/blog/4gb-wasm-memory
17. Emscripten の MAXIMUM_MEMORY https://emscripten.org/docs/tools_reference/settings_reference.html#maximum-memory
18. coi-serviceworker https://github.com/gzuidhof/coi-serviceworker
19. GitHub Community #13309（Pages の COOP/COEP）https://github.com/orgs/community/discussions/13309
20. Chrome「Document Isolation Policy」https://developer.chrome.com/blog/document-isolation-policy
21. MDN browser-compat-data https://github.com/mdn/browser-compat-data
22. Online3DViewer https://github.com/kovacsv/Online3DViewer/tree/master/source
23. CascadeStudio https://github.com/zalo/CascadeStudio
24. Innerscene STEP Viewer https://innerscene.com/tools/step-viewer
25. CascadeScope https://occt3d.com/dev/content/cascadescope-brepgraph-powered-3d-viewer/index.html
26. three-mesh-bvh https://github.com/gkjohnson/three-mesh-bvh
27. @dimforge/rapier3d https://www.npmjs.com/package/@dimforge/rapier3d
28. seung-lab/euclidean-distance-transform-3d https://github.com/seung-lab/euclidean-distance-transform-3d
29. distance-transform（npm）https://www.npmjs.com/package/distance-transform
30. dxf-parser https://github.com/gdsestimating/dxf-parser
31. skymakerolof/dxf https://github.com/skymakerolof/dxf
32. vagran/dxf-viewer https://github.com/vagran/dxf-viewer
33. mlightcad/cad-viewer https://github.com/mlightcad/cad-viewer
34. Pyodide https://www.npmjs.com/package/pyodide ／ ezdxf https://pypi.org/project/ezdxf/
35. MDN「Storage quotas and eviction criteria」https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria
36. MDN「Origin private file system」https://developer.mozilla.org/en-US/docs/Web/API/File_System_API/Origin_private_file_system
