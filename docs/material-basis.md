# 材料の一般的な基準（出典）

アプリの「材料の基準」（操作パネルの 材料 の ✎、問題の一覧 の 基準を編集…）に初めから入っている値と、その出典。調べた日は 2026-10-11。値は `frontend/src/materials.ts` の `BUILTIN` にある。

## アプリが使う値

| 材料 | 種類 | 比重 | 肉厚の下限 mm | 必要な勾配 ° | 厚肉 倍 | 根拠の欄 |
|---|---|---|---|---|---|---|
| PMMA | 樹脂 | 1.19 | 0.64 | 0.5 | 1.5 | Protolabs の肉厚の表（下端）・各社の勾配の最小・DuPont の厚肉 |
| PC | 樹脂 | 1.20 | 1.0 | 0.5 | 1.5 | Protolabs・Fictiv の肉厚（下端）・Covestro の勾配・DuPont の厚肉 |
| ABS | 樹脂 | 1.05 | 1.14 | 0.5 | 1.5 | Protolabs の肉厚の表（下端）・勾配・DuPont の厚肉 |
| PP | 樹脂 | 0.90 | 0.89 | 0.5 | 1.5 | Protolabs の肉厚の表（下端）・Fictiv の勾配・DuPont の厚肉 |
| PA66 | 樹脂 | 1.14 | 1.0 | 0.5 | 1.5 | 旭化成 レオナの設計基準（肉厚）・各社の勾配・DuPont の厚肉 |
| POM | 樹脂 | 1.41 | 0.76 | 0.5 | 1.5 | Protolabs の肉厚の表（下端）・Celanese の勾配・DuPont の厚肉 |
| PS | 樹脂 | 1.05 | 0.89 | 0.5 | 1.5 | Protolabs の肉厚の表（下端）・勾配・DuPont の厚肉 |
| SS400 | 金属 | 7.85 | 0.8 | — | — | Protolabs Network の切削の最小肉厚（推奨） |
| S45C | 金属 | 7.85 | 0.8 | — | — | 同上 |
| SUS304 | 金属 | 7.93 | 0.8 | — | — | 同上 |
| A5052 | 金属 | 2.68 | 0.8 | — | — | 同上 |
| A6061 | 金属 | 2.70 | 0.8 | — | — | 同上 |
| 銅 C1100 | 金属 | 8.89 | 0.8 | — | — | 同上 |
| 黄銅 C3604 | 金属 | 8.50 | 0.8 | — | — | 同上 |
| 純チタン 2 種 | 金属 | 4.51 | 0.8 | — | — | 同上 |

- 樹脂の肉厚の下限は、推奨の肉厚の範囲の下端。PC は Covestro が「1.5 mm 未満を薄肉」と呼ぶが、推奨範囲の下端ではないので 1.0 にした（ほかの材料と同じ決め方）。
- 金属は成形しないので勾配を持たない。用途が「一般」のときは抜き勾配を見ない。
- 厚肉（一般部の肉厚に対する比）は 1.5 倍以上（下の 2 節）。DuPont の図の「避けるべき例」（リブを壁と同じ厚さにして根元の R を 0.5T にすると、交わりに入る円が 1.5T）がちょうど 1.5 倍なので、それを拾うように「以上」にした。推奨どおりのリブ（壁の 1/2〜2/3）の根元は 1.11〜1.35 倍に収まり、拾わない。金属は成形しないので持たない

以下は調べた内容のまま。出典の番号 [n] は 4 節の一覧。

- 「検索のみ」と書いたものは、検索エンジンの要約でしか確かめられず、本文を開けなかった値。表の代表値には使っていない。
- 「計算」と書いたものは、資料の値ではなく計算した値。

## 1. 樹脂の表

| 材料 | 比重 | 推奨肉厚 mm | 肉厚の下限の候補 mm | 勾配の最小°（シボなし） | 出典 |
|---|---|---|---|---|---|
| PMMA | 1.19（一般グレード）。耐衝撃グレードは 1.16〜1.18 | 0.64〜12.7 [16]、0.64〜3.81 [20]。メーカーの資料は見つからない | **0.64**（2 つの資料の下端が一致） | **0.5**。[20] は 0.5〜1° とし、鏡面の光学部品はもっと要ると書く。メーカーの値は見つからない | [11] p.6、[12] p.5–6、[16]、[20] |
| PC | 1.20（1,200 kg/m³） | 1.02〜3.81 [16]、1.0〜4.0 [19]。Covestro は範囲を出していない。1.5 未満を薄肉と呼び、高性能な成形機が要ることがあるとする [1] p.20。中粘度の PC は室温で約 3/16 in（約 4.8 mm）を超えると衝撃強さが急に落ちる（臨界肉厚）[1] p.20 | **1.0**（汎用ガイドの下端）。メーカーの「薄肉」の定義に合わせるなら 1.5 | **0.5**（PC 系の多くの材料で 0.5° 以上。形が許せば 1°）[1] p.32 | [1]、[3]、[16]、[19] |
| ABS | 1.04 [13]（ミスミの ABS 板は 1.05 [30]） | 1.14〜3.56 [16]、1.2〜3.5 [19] | **1.14** | **0.5**。[16] は垂直面 0.5°、[19] は硬い材料（ABS、PC）で 0.5〜2° とする。メーカーの値は見つからない | [13]、[16]、[19] |
| PP | 0.90（ホモポリマー） | 0.89〜3.81 [16]、0.64〜3.81 [17][18]、0.8〜3.8 [19] | **0.89**（[16] による。資料で 0.64〜0.89 に割れる。5 節） | **0.5**。[19] は半硬質の材料（PP、PE）で 0.5〜1.5° とする | [14]、[16]〜[19] |
| PA66 | 1.14 | 通常 1〜3 [7] p.2（旭化成、レオナ）。0.76〜2.92 [16]、0.8〜3.0 [19] | **1.0**（メーカー [7] を採る） | **0.5**（代表）。DuPont（Zytel）は深さ 25 mm 未満で 0〜1/8°、それより深いと 1/4〜1/2° [4] Table 3.01。旭化成は箱形のキャビティ側で最低 1°、底のリブ 0.5°、壁の縦リブ 0.25° [7] p.2–3 | [4]、[7]、[8]、[16]、[19] |
| POM | 1.41（コポリマー）。ホモポリマー（Delrin）は 1.42（検索のみ） | 0.76〜3.05 [16]。メーカーの値は見つからない | **0.76** | **0.5**。Celanese（Celcon、コポリマー）は 1/2〜1° を勧める [5] p.4-8。DuPont（Delrin、ホモポリマー）は深さ 25 mm 未満で 0〜1/4°、それより深いと 1/2° [4] Table 3.01 | [4]、[5]、[6]、[16] |
| PS | 1.05（GPPS） | 0.89〜3.81 [16][18] | **0.89** | **0.5**（[16] の垂直面の値。PS 固有の値は見つからない） | [15]、[16]、[18] |

### 代表値の選び方

- **比重**: 材料メーカーのデータシート（ISO 1183）の値を採った。どの材料も、アプリの値と一致するか、差は 0.01 以下（5 節）。
- **肉厚の下限**: 7 材料を 1 つの表で並べた資料は Protolabs [16] しかない。そこで [16] の下端を基本にした。メーカーの値がある PA66 だけは、旭化成 [7] の「通常 1〜3 mm」の下端（1.0）を採った。PC は Covestro の「1.5 mm 未満は薄肉」[1] がアプリの「薄肉」の意味にいちばん近い。ただし推奨範囲の下端ではないので、別案にとどめた。
- **勾配の最小**: 資料ごとの最小値はだいたい 0.5° でそろう（Covestro [1]、Envalior [9]、Protolabs [16]、Celanese [5] の下端、DuPont の深い場合 [4]）。そこで 7 材料とも 0.5° を採った。DuPont と旭化成は、浅い形やリブならもっと小さくてよいとしている（PA66・POM の欄）。0.5° は誤検出を少し許す側の値になる。

### シボ（表面の模様）があるとき

| 資料 | 内容 |
|---|---|
| Covestro [1] p.32 | 基本の 1° に、シボの深さ 0.001 in（0.025 mm）ごとに 1° を足す（経験則） |
| DuPont [4] Table 3.01 の注 | シボ面は、シボの深さ 0.025 mm ごとに 1° を足す |
| Envalior [9] | シボの深さ 0.1 mm ごとに 0.4° を足す（0.025 mm あたりにすると 0.1°） |
| 旭化成 [7] p.3 | レザー模様は種類によって抜きにくい。少なくとも 6° 以上 |
| Protolabs [16] | 軽いシボ PM-T1 は最低 3°、PM-T2 は最低 5° 以上 |

代表は「深さ 0.025 mm ごとに +1°」とする。2 社（Covestro、DuPont）が一致しているから。Envalior の値はその 1/10 で、桁が合わない（5 節）。

### リブの厚さ（一般肉厚に対する比）

| 資料 | 内容 |
|---|---|
| Covestro [1] p.25 Table 2-1（PC、PC 系） | Makrolon（充填材なし）: ヒケが最小なら 50%（高光沢なら 40%）、少しのヒケを許すなら 66%。充填材入りの Makrolon は 60% と 75% |
| DuPont [4] p.27 | 補強する壁の 1/2〜2/3 |
| 旭化成 [7] p.3（PA66） | 根元の肉厚の約 1/2。根元は壁の 1/2、先端は最低 1 mm |
| Celanese [5] p.4-4（POM） | 収縮の大きい樹脂でヒケをなくすには、隣の壁の 50% |
| Envalior [10] | 一般肉厚の約 50〜60%。根元の R は肉厚の 25〜50%。50% を超えると肉がたまる |
| Fictiv [19] | 50〜65% |

---

## 2. 厚肉の目安（一般部に対する比）

### 資料ごとの記述

| 資料 | 言っていること | 1.5 倍との関係 |
|---|---|---|
| DuPont [4] p.27（Fig. 4.07）、p.11（Fig. 3.03） | リブと壁の交わりに円を描いて、厚さを比べる。リブの厚さを壁と同じ（T）にして根元の R を 0.5T にすると、円の直径は 1.5T（壁より 50% 厚い）。R を 0.5T より大きくしても角はあまり強くならず、円が大きくなってボイドの恐れが増す。そのためリブは壁の 1/2〜2/3 にする | **1.5T は「避けるべき例」として出てくる。** 1.5 倍は「明らかに厚い」の線として使える。ただし許してよい上限としては書かれていない |
| Covestro [1] p.20–21 | 収縮の小さい材料（非晶性の多く、充填材入り）は、一般肉厚の変化が約 25% までなら、充填・反り・外観の大きな問題は出ない。充填材なしの結晶性樹脂は、その約半分しか許さない。リブなどの突起は壁より薄くする | 一般部どうしの変化の上限は非晶性で約 1.25 倍、結晶性で約 1.12 倍（半分から計算）。1.5 倍より厳しい |
| 旭化成 [7] p.2（PA66） | 肉厚の変化はおおむね ±20% 以内 | 約 1.2 倍。1.5 倍より厳しい |
| Envalior [10] | リブの根元の R が肉厚の 50% を超えると肉がたまり、残留応力・ボイド・ヒケの恐れがある | 比の数字は出していない |
| Protolabs [17] | どの壁も、隣の壁の 40〜60% より薄くしない | 厚い側と薄い側の比で 1.67〜2.5 倍までを許す。1.5 倍よりゆるい |
| Fictiv [19] | 一般肉厚の変化は ±10%。変化部は 3:1 まで（何の比かは書いていない） | ±10% は約 1.1 倍。「3:1」は肉厚の比か、テーパーの長さの比かが読み取れない |

### リブの根元にできる内接円（計算）

DuPont の考え方（交わりの内接円で比べる）を、2D の T 字の断面で計算した。壁の厚さ T、リブの厚さ k·T、根元の R を f·T とする。円は壁の裏面に接し、両側の R の円弧に接するとした。

式: D/T = 2(a² + 1 + 2f)/(2 + 4f)、ただし a = k/2 + f。格子での総当たりと 0.01T 以内で一致した。

| リブ厚/T | R = 0.125T | R = 0.25T | R = 0.5T |
|---|---|---|---|
| 0.5 | 1.11 | 1.17 | 1.28 |
| 0.6 | 1.15 | 1.20 | 1.32 |
| 0.67 | 1.17 | 1.23 | 1.35 |
| 0.75 | 1.20 | 1.26 | 1.38 |
| 1.0 | 1.31 | 1.38 | **1.50** |

L 字の角（外側がピン角、内側が R）も同じように計算した。R = 0 で 1.17T、R = 0.5T で 1.34T、R = T で 1.51T。

### まとめ（1.5 倍を支えるか）

- **1.5 倍を直接支える資料は DuPont [4] の図だけ。** ただしそれは「悪い例がちょうど 1.5T」という書き方で、上限の規定ではない。「1.5 倍を超えたら厚肉」とすると、その悪い例（ちょうど 1.50）は拾わない。
- 推奨どおりのリブ（壁の 1/2〜2/3、R 0.125〜0.5T）でも、根元は 1.11〜1.35T になる。1.5 倍なら、正しく設計したリブの根元は拾わない。この点は 1.5 倍の利点。
- リブを壁と同じ厚さにしても、R が 0.25T 以下なら 1.31〜1.38T で、1.5 倍では拾わない。内接円の比だけでは、正しいリブ（〜1.35）と厚すぎるリブ（1.31〜）を分けられない。2 つの範囲が重なっている。
- メーカーの「一般肉厚の変化」の上限は 1.2〜1.25 倍（結晶性は約 1.12 倍）。これは一般部どうしの比較で、交わりの内接円とは別のものを測っている。
- 提案（資料の値ではない）: 初期値は 1.5 倍のままにする（ボイドの恐れの線。誤検出が少ない）。ヒケを見たいときのために、1.25〜1.3 倍の「注意」の段を別に置く。結晶性（PP、PA66、POM）は非晶性より小さい比にする、という案もある（Covestro [1] の「約半分」に基づく）。

---

## 3. 金属の表

| 材料（規格の記号） | 密度 g/cm³（代表） | 資料の値 | 出典 |
|---|---|---|---|
| SS400（JIS G 3101） | **7.85** | ミスミ 7.87 [22][23]。日本製鉄の H 形鋼の表から逆算すると 7.85（計算。200×200: 63.53 cm² → 49.9 kg/m）[29]。JIS G 3101 自体は密度を決めていない | [22]、[23]、[29] |
| S45C（JIS G 4051） | **7.85** | Xometry 7.85 [31]。ミスミは S45C を載せず、S50C を 7.87 とする [23] | [23]、[31] |
| SUS304（JIS G 4304/4305） | **7.93** | 日本製鉄 7.93 [24] p.4、ミスミ 7.93 [22] | [22]、[24] |
| A5052 | **2.68** | ミスミ 2.68（A5052P）[22][23] | [22]、[23] |
| A6061 | **2.70** | ミスミ 2.7（A6061P）[22][23] | [22]、[23] |
| 銅 C1100（タフピッチ銅） | **8.89** | ミスミ 8.89（C1100P）[22][23]。CDA の C11000 は 8.91（0.322 lb/in³）[27] | [22]、[27] |
| 黄銅 **C3604**（快削黄銅棒、JIS H 3250） | **8.50** | CDA の C36000（成分が近い米国の快削黄銅）8.5（0.307 lb/in³）[27]。C3604 そのものの値は一次に近い資料で確認できなかった（イプロスの 8.5 は検索のみ） | [27] |
| （参考）黄銅 C2801 | 8.43 / 8.39 | ミスミ 8.43（C2801P）[22]。CDA の C28000 は 8.39（0.303 lb/in³）[27] | [22]、[27] |
| チタン **純チタン 2 種**（JIS H 4600 TP340、棒は TB340） | **4.51** | ミスミ 4.51（TP340H）[22]、日本製鉄 4.51 [25] | [22]、[25] |
| （参考）Ti-6Al-4V（64 チタン） | 4.43 | NBK 4.43 [26] | [26] |

選んだ理由:

- 黄銅は C3604 にした。機械加工品（切削）で最もよく使う黄銅だから。板の C2801 は参考として残した。
- チタンは純チタン 2 種にした。ミスミが「最も多く使われている汎用チタン材料」としているから [22]。

### 切削（機械加工）の最小肉厚

- Protolabs Network（旧 Hubs）[28]: 金属は推奨 0.8 mm、可能なのは 0.5 mm（個別に判断）。プラスチックは推奨 1.5 mm、可能なのは 1.0 mm。
- 材料ごとの値（アルミ、鋼、チタンで分けたもの）は、加工業者のブログにしか見つからなかった。いずれも検索のみなので載せない。
- 金属 8 種の共通値としては、**0.8 mm（推奨）** が候補になる。

---

## 4. 出典の一覧

| 番号 | 名前 | URL | 場所 |
|---|---|---|---|
| [1] | Covestro LLC, *Engineering Polymers Part and Mold Design – Thermoplastics: A Design Guide*（PDF、2015 作成） | https://solutions.covestro.com/-/media/covestro/solution-center/brands/downloads/imported/1557214249.pdf | Chapter 2: Wall Thickness p.19–21（臨界肉厚、薄肉 1.5 mm、変化 25%）、Ribs p.24–25（Table 2-1、Fig. 2-10）、Draft p.32（Fig. 2-24、シボ）。ページは冊子の印刷ページ |
| [2] | Covestro, COV-203 *Design Guidelines for Makrolon® Thermally Conductive (TC) Polycarbonate Grades*（2022-08） | https://i4ptoeu.covestro.com/caps/HeatsinkScreenerUsingMakrolon/pdf/COV-203%20Design%20Guidelines%20for%20Makrolon%20TC%20Grades%20081922.pdf | p.1 Design Considerations（TC グレード専用。5 節） |
| [3] | Covestro, Makrolon® 2405 製品ページ | https://solutions.covestro.com/en/products/makrolon/makrolon-2405_00945088-00009643 | Other properties: Density 1,200 kg/m³（ISO 1183-1） |
| [4] | DuPont Engineering Polymers, *General Design Principles – Module I*（PDF、2001。ステレンボッシュ大学の掲載品） | https://academic.sun.ac.za/mad/catalogs/dfmguidelines/dupontgeneraldesignprinciples.pdf | Uniform Walls p.11（Fig. 3.03）、Draft p.12（Table 3.01）、Ribs p.27（Fig. 4.07） |
| [5] | Celanese, *Processing and Troubleshooting Guide – Celcon® Acetal Copolymer*（2014） | https://www.celanese.com/-/media/Engineered%20Materials/Files/Product%20Technical%20Guides/POM-044_Celcon_ProcessingGuideTG_AM_0913.pdf | p.4-4（Wall Thickness、リブ 50%）、p.4-8（Draft） |
| [6] | Celanese, Celcon® M25 データシート（polymerfilms 社の掲載品） | https://polymerfilms.com/wp-content/uploads/2023/07/Acetal_CelconM25-Datasheet.pdf | Density 1410 kg/m³（ISO 1183） |
| [7] | 旭化成「レオナの製品設計基準」（LE1-1.pdf） | https://www.asahi-kasei-plastics.com/wp-content/uploads/2022/11/LE1-1.pdf | p.2「射出成形品設計の 5 原則」、p.3（シボ・リブの勾配、リブ厚） |
| [8] | DuPont, Zytel® 101L NC010 Technical Data（UL Prospector の写し、Protolabs の掲載品） | https://protolabs.com/media/tcebrq5j/zytel-101l.pdf | Physical: Density 1.14（ISO 1183） |
| [9] | Envalior, Design guide "Draft angle" | https://www.envalior.com/en-us/draft-angle | 本文 |
| [10] | Envalior, Design guide "Corrugations, ribs and gussets" | https://www.envalior.com/en-us/corrugations-ribs-and-gussets | 本文 |
| [11] | 住友化学「メタクリル樹脂成形材料 スミペックス®」（PDF、2017） | https://www.sumitomo-chem.co.jp/products/files/docs/e72422b36ef358c1ac2a5c4fbf6420e4.pdf | PDF p.6 物性表: 比重 1.19（ISO 1183 / JIS K7112 A 法） |
| [12] | クラレ「PARAPET™ Catalog」（2023） | https://methacrylate.kuraray.com/content/dam/methacrylate/en/documents/parapet_en.pdf | PDF p.5（一般グレード 1.19）、p.6（GR 系 1.16〜1.18） |
| [13] | INEOS Styrolution, Terluran® GP-22 Technical Data（UL Prospector の写し、2023-09-29 更新、Protolabs の掲載品） | https://protolabs.com/media/wyxjrany/terluran-gp-22.pdf | Physical: Density 1.04（ISO 1183） |
| [14] | LyondellBasell, Moplen HP500N 製品ページ | https://www.lyondellbasell.com/en/polymers/p/Moplen-HP500N/e8c2d3bb-d271-459f-a439-629a5d85a7da | Typical properties: Density 0.90 g/cm³（試験法の記載なし） |
| [15] | TotalEnergies, Polystyrene Crystal 1540 データシート | https://polymers.totalenergies.com/sites/g/files/wompnd5016/files/site_collection_documents/Technical%20Datasheets/1540-EU-EN.pdf | Density 1.05（ISO 1183） |
| [16] | Protolabs, "Design Guidelines: Plastic Injection Molding" | https://protolabs.com/services/injection-molding/plastic-injection-molding/design-guidelines | 肉厚の表（in と mm）、Draft の一覧 |
| [17] | Protolabs, "Improving Part Design with Uniform Wall Thickness" | https://www.protolabs.com/resources/design-tips/improving-part-design-with-uniform-wall-thickness/ | Plastic Wall Thickness Chart、隣の壁の 40〜60% |
| [18] | Protolabs（英国）, "Solving Wall Thickness Issues in Moulded Parts" | https://www.protolabs.com/en-gb/resources/design-tips/solving-wall-thickness-issues-in-moulded-parts/ | Recommended Wall Thickness by Plastic Type（mm） |
| [19] | Fictiv, "Injection Molding Specifications" | https://www.fictiv.com/specifications/injection-molding | 材料別の肉厚、±10%、リブ 50〜65%、材料の分類別の勾配 |
| [20] | Fictiv, "Acrylic Injection Molding" | https://www.fictiv.com/?p=11423 | 肉厚 0.025〜0.150 in、勾配 0.5〜1°、R |
| [21] | MONOist「肉厚と抜き勾配を押さえるべし！」成型部品設計のツボ（1）2/3（2007-09-20） | https://monoist.itmedia.co.jp/mn/articles/0709/20/news124_2.html | 一般値: 肉厚 1.5〜3.5 mm、キャビティ・コア 1° 以上、ボス・リブ 0.5° 以上（材料別ではない。表には使っていない） |
| [22] | ミスミ 素材情報「金属プレート」特性値 | https://jp.misumi-ec.com/maker/misumi/mech_material/products/properties/metal/plate/ | 「金属プレート 特性値」の表: 比重（20℃） |
| [23] | ミスミ 素材情報「金属 丸棒・パイプ」特性値 | https://jp.misumi-ec.com/maker/misumi/mech_material/products/properties/metal/roundbar_pipe/ | 「丸棒・パイプ 特性値」の表: 比重（20℃） |
| [24] | 日本製鉄 カタログ S008「ステンレス冷延鋼板」 | https://www.nipponsteel.com/product/catalog_download/__icsFiles/afieldfile/2025/10/06/S008.pdf | PDF p.4 鋼種の表: SUS304 の密度 7.93 |
| [25] | 日本製鉄 TranTixxii コラム「チタンとステンレスの違いとは？」 | https://www.nipponsteel.com/product/trantixxii/column/titanium-stainless.html | 本文: 純チタンの密度 4.51 g/cm³ |
| [26] | NBK（鍋屋バイテック）「チタンの特性」 | https://www.nbk1560.com/images/ja-JP/product/contents/tokusei_titan_enedzi_NBK/tokusei_titan_enedzi_NBK_1.pdf | 物性の表: 比重 TW340 4.51、Ti-6Al-4V 4.43 |
| [27] | Copper Development Association, Alloy data（C11000 / C28000 / C36000） | https://alloys.copper.org/alloy/C11000 、 https://alloys.copper.org/alloy/C28000 、 https://alloys.copper.org/alloy/C36000 | Physical Properties: Density、Specific Gravity |
| [28] | Protolabs Network（旧 Hubs）, "How to design parts for CNC machining" | https://hubs.com/knowledge-base/how-design-parts-cnc-machining | Minimum wall thickness |
| [29] | 日本製鉄「建築用材ハンドブック」H 形鋼（3-28.pdf） | https://www.nipponsteel.com/product/construction/handbook/pdf/3-28.pdf | 寸法の表: 200×200×8×12 の断面積 63.53 cm²、単位質量 49.9 kg/m（密度は逆算） |
| [30] | ミスミ 素材情報「樹脂」 | https://jp.misumi-ec.com/maker/misumi/mech_material/products/properties/resin/ | 「樹脂プレート 全材質 その他」の表: ABS 1.05、ポリアセタール 1.41（ASTM D792） |
| [31] | Xometry, S45C Datasheet | https://xometry.asia/wp-content/uploads/2021/03/1773390136-S45C-Datasheet.pdf | Physical properties: Density 7.85 g/cm³ |

---

## 5. 気になった点

### アプリの今の比重との比較

- 7 材料とも資料と合う。ずれと言えるものは無い。
- ABS は資料で 1.04（Terluran GP-22）と 1.05（ミスミの板）に分かれる。グレードで 0.01 程度動く。
- POM の 1.41 はコポリマー（Duracon、Celcon）の値。ホモポリマー（Delrin）なら 1.42（検索のみ）。
- PP の 0.90 はホモポリマーの値。
- ガラス繊維やタルクの入ったグレードは比重が大きく変わる。数値は今回調べていない。

### 資料どうしで割れたもの

1. **PP の肉厚の下端。** Protolabs の自社のページの間で割れている。[16] は 0.035 in（0.89 mm）、[17] は 0.025 in（0.64 mm）、[18] は 0.635 mm。Fictiv [19] は 0.8 mm。表では [16] の 0.89 を採った。
2. **PMMA の肉厚の上端。** Protolabs [16] は 12.7 mm、Fictiv [20] は 3.81 mm。アプリは下限しか使わないので、影響しない。
3. **シボの勾配。** Covestro [1] と DuPont [4] は深さ 0.025 mm ごとに +1°。Envalior [9] は 0.1 mm ごとに +0.4°（0.025 mm あたり 0.1°）で、1/10 の値になる。Envalior の記述が誤記かどうかは、資料からは判断できない。
4. **旭化成の箱形の勾配**（[7] p.2）。「深さ 50〜100 mm では 1.5°、100 mm 以上で 1°」と、深いほうが小さい値になっている。原文どおり載せた。誤記の可能性がある。
5. **PA66・POM の勾配の最小。** DuPont [4] は浅い形（深さ 25 mm 未満）なら 0〜1/8°（Zytel）、0〜1/4°（Delrin）でよいとする。旭化成 [7] は箱形のキャビティ側で 1° 以上とする。表の代表 0.5° はその間の値になる。
6. **SS400 の密度。** ミスミは 7.87、H 形鋼の表の逆算は 7.85。銅は 8.89（ミスミ）と 8.91（CDA）。C2801 は 8.43（ミスミ）と 8.39（CDA）。どれも差は 0.5% 以下。

### メーカーの資料が取れなかったもの

- 樹脂メーカーの設計資料で数値まで確かめられたのは、PC（Covestro）、PA66（旭化成、DuPont）、POM（Celanese、DuPont）だけ。**PMMA・ABS・PP・PS は、汎用の設計ガイド（Protolabs、Fictiv）で埋めた。**
- PMMA について、2 件の手がかりを見つけた。どちらも本文を開けず、未確認のまま。
  - 住友化学スミペックスの金型設計の資料に「抜き勾配 0.8〜2.0°（製品の長さによる）、通常 1°」とある、という検索結果があった。掲載先は Knowde で、取得できなかった。
  - PlasticsToday の「By Design: Designing with acrylic」も、光学部品の勾配に触れているらしい。取得は拒否された。
  - 導光板の用途では、この 2 件をメーカーに直接確かめる価値がある。
- ポリプラスチックス（ジュラコン）の抜き勾配の頁（旧 polyplastics.com/jp/support/mold/duracon/pom08c.html）は、「少なくとも 1/4〜1/2°、できれば 1°」と書いているという検索結果があった。サイトはダイセル（hpps.daicel.com）に移っていて、本文を確かめられなかった。
- 三菱ケミカル（アクリペット）と旭化成（デルペット、テナック）は、設計の資料が資料請求か登録の後ろにあった。

### 厚肉の比について（アプリ側への注意）

- 2 節の比は、どれも「内接円（球）の直径」か「一般部どうしの肉厚」の比。アプリのローリングボール法の値は、内接球に近い。そのため 2 節の比較がそのまま当てはまる。
- 一般にレイ法（面から法線の向きに光線を飛ばす方法）では、リブの裏の面から飛ばした光線がリブの中を通ってリブの先まで届く。測る値は壁の厚さ＋リブの高さになりやすい。レイ法の値に同じ比を当てると、リブの裏がほぼ全部「厚肉」になるおそれがある。アプリのコードは読んでいないので、実装で確かめてほしい。
- 2 節の計算は 2D の T 字の断面。リブの交差やリブと側壁の角では、3D の内接球はもっと大きくなる。

### その他

- Covestro の TC（熱伝導）グレード用の資料 [2] には、一般肉厚 2.5〜4.0 mm（流動長が短ければ 1.5 mm も可）、勾配 2.0° 以上が望ましい、リブと壁の比 0.8 でも成形できた、とある。TC グレード専用なので表には使っていない。
- PC の臨界肉厚（約 4.8 mm。超えると衝撃に弱くなる）[1] は、厚すぎる側の目安になる。厚い PC 部品で使えるかもしれない。
