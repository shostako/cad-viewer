# Web 版（ブラウザだけで動く版）の計画

2026-10-11。ユーザーの「Web アプリ版とインストール版を作りたい」の 2 つ目。インストール版（#83）は backend をそのまま固めた。Web 版は backend を無くし、計算を全部ブラウザの中でする。調べた結果は [../web-prior-art.md](../web-prior-art.md)。

## 何のためか

- **URL を渡すだけで使える。** インストールが要らず、Windows の権限にも署名の警告にも引っかからない。
- **お客さんの CAD がどこにも出ていかない。** 配るのは静的なファイル（GitHub Pages）だけで、開いたファイルはブラウザのタブの中で読む。サーバーで受け取る作りにすると、他人の機密の CAD を預かることになる。インストール版と同じく、手元だけで閉じる。
- **機能は手元の版と同じにする**（ユーザーの「基本全部」）。違うのは DWG だけ（ODA File Converter は外の exe なので、ブラウザでは動かせない）。

## 作り

```
[frontend] main.ts ほか（変えない）
   │  api.ts の 13 の関数（今は fetch で /api を呼ぶ）
   ▼
 Engine（新しい境目）
   ├─ HttpEngine   今の backend を呼ぶ（手元の版・インストール版）
   └─ LocalEngine  Web Worker の中で計算する（Web 版）
        ├─ libcascade 3.0.2（OCCT 8.0.1 の WASM、single 版）: STEP/IGES の読み込み、ID 付きのテッセレーション、計測、体積
        ├─ three-mesh-bvh: 肉厚（レイ・ボール）、厚肉の格子の中の判定
        ├─ 自作の距離変換（Felzenszwalb）: 厚肉
        ├─ Pyodide＋ezdxf: DXF → SVG（DXF を開いたときだけ読み込む）
        └─ IndexedDB: サイドカー（鍵は今と同じ、中身の sha256 の先頭 32 文字）
```

- **境目は `api.ts` の 1 枚。** frontend で backend を呼んでいるのは `api.ts` だけ（fetch は 9 か所）。
  - 13 の関数: 読み込み、メッシュ、図面の SVG、計測 4 種（距離・エッジ・面・頂点）、肉厚、サイドカーの読み、サイドカーの書き、厚肉、投影面積、体積・重量。
  - これらが呼ぶ backend の道は `/api/models`（POST）、`mesh.bin`、`drawing.svg`、`measure`、`thickness.bin`・`thick.bin`、`sidecar`（GET・PUT）、`thick`、`projected_area`、`properties`。
  - `Engine` は、この道をそのまま受ける。パス・メソッド・状態コード・本文が同じなので、`api.ts` は答えも誤りも 1 通りに読める。HttpEngine は fetch で、LocalEngine は Worker の中の同じ道で答える。
  - E2E が道で止めたり答えたりする仕組みも、両方の版で同じに作れる。
  - 読み込みだけは `Engine.upload` を別に持つ。送った量（`onSent`）は道の形では表せないので、HttpEngine は XMLHttpRequest で送る。LocalEngine は送る物が無いので、すぐに `onSent(1)` を返してから Worker で読む。
  - E2E が使う `__stallNext*`（計測・サイドカー・投影面積・体積の答えを遅らせる）は `api.ts` に残す。`api.ts` は Engine の手前の共通の層なので、どちらの Engine でも効く。
  - どちらの実装を使うかはビルドで決める（`VITE_CAD_ENGINE=local`）。main.ts・viewer.ts などは触らない。
- **Worker の中で動かす。** OCCT の計算は同期で長い（大きな STEP の読み込みに数秒）。メインのスレッドで回すと画面が止まる。Worker なら、止まった計算を `terminate` して作り直せる。昔の WASM 版では BRepExtrema が戻らなくなる面の組があった（原因は分かっていない）。
- **backend の Python を TypeScript に写す。** 計算の中身は backend と同じにする。
  - libcascade のクラス名と呼び方は OCP とほぼ同じなので、`tessellation.py`・`measure.py`・`properties.py` はほぼ 1 対 1 で写せる。
  - numpy や scipy に頼っている所（`thick.py`・`projection.py`・`thickness.py`）は、型付き配列で書き直す。
  - 面・エッジ・頂点の番号は、同じ `TopExp.MapShapes` の順で付けるので backend と同じになる。
- **配る大きさ**: libcascade は gzip で 12 MB。初めて開くときに 1 回だけ落とし、その後はブラウザのキャッシュから読む。
  - Pyodide＋ezdxf の約 13 MB は、DXF を開いたときだけ落とす。
  - 大きさや速さが問題になったら、使うクラスが固まった段階で `@libcascade/toolchain` で削る（全部入りの 42.7 MB から、一桁 MB を見込む）。
- **スレッドは使わない。** 速さは 1.2〜1.3 倍にしかならないのに、COOP/COEP のヘッダが要る（GitHub Pages では付けられない）。
- **libcascade が止まったときの逃げ道**: 保守しているのは小さな組織なので、版を固定して wasm をリポの外に保管しておく。行き詰まったら、Chili3D と同じやり方（OCCT 8.0.1 を約 100 行の CMake で自分でビルドする、gzip 4.5 MB）に移る。

## 段取り（1 段 1 PR。上から順に）

| 段 | 中身 | 終わったときに Web 版でできること |
|---|---|---|
| W1（#85） | `Engine` の境目を切る（HttpEngine だけ。13 の関数が全部 `Engine` を通る） | 今と同じ（全部の E2E が通る） |
| W2 | LocalEngine の土台（Worker、`src/local/`）、メッシュの形式（STL/OBJ/PLY/OFF/3MF：読み込み、30° で頂点を分けるなめらかな陰影、体積・重心）、サイドカーを IndexedDB に。Web 版のビルド（`npm run build:web`）と GitHub Pages への配信（`pages.yml`）。CI に Web 版の E2E のジョブと、backend との突き合わせ（`npm test`） | URL で開いて、STL を見る・断面・注記・体積 |
| W3 | STEP/IGES（libcascade）。XCAF の名前・色・階層、ID 付きのテッセレーション、バラバラの面の縫い合わせ、単位、曲線の部品 | STEP/IGES を見る・部品ツリー |
| W4 | 計測（`measure.py`：距離 3 種、エッジ・面・頂点の情報）と、B-rep の体積・重心（`properties.py`）。E2E の差し替え（`page.route` の代わりに、道で止める・答える仕組みを両方の版で）。W3 までは、Web 版で通る E2E に差し替えの要る本が無かったので、計測の本が通り始めるここに回した | 真値の計測、体積・重量 |
| W5 | 肉厚（レイ法・ボール法）、厚肉（`thick.py`：格子、距離変換、面ごとの肉厚、一般部、肉だまり）、投影面積 | 肉厚のヒートマップ、問題の一覧、型締力の目安 |
| W6 | DXF（Pyodide＋ezdxf、フォントの同梱） | 2D 図面 |
| W7 | 仕上げ: 読み込みのキャッシュ（OPFS）、オフライン（Service Worker）、Chromium での「開き直し」（File System Access）とファイルの関連付け（File Handling） | 2 回目から速い、ネットが無くても開ける |

段ごとに、その段の機能の E2E を Web 版でも回すようにする（下の「確かめ方」）。W7 の後で、手元の版と Web 版の E2E が両方とも全部通るのが「全部」。

## 確かめ方

- **同じ E2E を 2 つの版に流す。** E2E は Playwright で画面を操作して、画面への投影・ピック・画素・既知の寸法で合否を決めている。backend の作りには頼っていないので、そのまま Web 版にも流せる。
  - backend の API に直に触る所（サイドカーの差し替え、計測などを止める `page.route`、`put_sidecar`）は、W4 で、道で止める・答える共通の補助に移す。HttpEngine では `page.route` のまま、LocalEngine ではページの中の Engine の前で同じことをする（Playwright の `expose_binding` で Python の手続きを呼ぶ）。
  - Web 版のジョブは CI の `e2e (web)`。Web 版を `vite preview` で配り、backend を立てずに、`e2e/web_scripts.txt` に並べた本を流す。段ごとに、この一覧を増やしていく。
- **2 つの計算を突き合わせる。** testdata の各ファイルについて、backend（Python＋OCP 7.9.3）と LocalEngine（TS＋libcascade、OCCT 8.0.1）の答えを並べる。比べるのは、部品・面・エッジの数、計測の値、体積、肉厚、厚肉。
  - `frontend/tests/*.test.ts`（`npm test`、Node の組み込みの test）が、同じファイルを `scripts/engine_golden.py`（backend のルートと同じ手続き）と LocalEngine の両方に読ませて比べる。
  - 2 つは別の言語・別の版の OCCT で書いた別の実装なので、互いが独立した基準になる。
  - Node で LocalEngine を動かすスクリプトにして、CI で回す。
  - 【実測】mini_mold.step の体積 116513.2741 と重心 (50, 30, 11.536) は、もう一致している。
- **変異**: 今と同じく、足したテストが壊れたコードを見つけるかを、作業ツリーの複製で確かめる。

## 決めたこと・決めていないこと

- 決めた（調べた結果から）:
  - libcascade の single 版を Worker で動かす。
  - DXF は Pyodide＋ezdxf。
  - サイドカーは IndexedDB。
  - 配信は GitHub Pages（`https://shostako.github.io/cad-viewer/`）。
- 後で決める（その段で、実物で測ってから）:
  - 大きなモデル（数十万三角形、数百部品）の速さとメモリ。
  - テッセレーションを JS で回すか C++ に移すか。
  - Pyodide を常に読むか、DXF の時だけ読むか。
- 前の WASM 版（別のリポ `cad-viewer-wasm`、opencascade.js 1.1.1、OCCT 7.4）は使わない（ユーザーの指示）。移植で踏んだ罠のうち、今も効くもの:
  - Vite が `.wasm` の import を ESM として扱って壊す（`?url` で URL として受け取る）。
  - 仮想のファイルの名前を短くする。
  - `FS.writeFile` はバイト列をコピーさせる（`canOwn` を使わない）。
