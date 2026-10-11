# 肉厚まわりの先行例（市販・有名ソフトの公開資料）

このアプリの肉厚・厚肉・肉厚の変わり目の作りを決めるときに調べた、他社の処理。どれも公開資料（ヘルプ、API 文書、技術資料、特許、論文）から読める範囲。2026-10-11 に調べた。

このアプリが採ったもの:

- **厚肉**（問題の一覧、#78）: 球の方法で、一般部の肉厚に対する比（初めは 1.5 倍以上）。Moldflow の Design Adviser の「とても厚い」（公称の +50 %）と同じ線。一般部は面積で重みを付けた最頻値（富士ゼロックスの特許の決め方に近い）
- **面ごとの肉厚**（ヒートマップの方式「面ごと」、#79）: 1 つの面が厚さの違う所にまたがるときは厚い側の値。SOLIDWORKS の肉厚のレポートが、またがる面を「より重大な範囲」に入れるのと同じ
- **肉厚の変わり目**（ヒートマップの方式「一般部との比」）: 一覧ではなく、一般部からのずれの色分け（±20 %・±50 %）。Moldflow の Design Adviser の既定の帯と同じ。変わり目の一覧を出す製品はほとんど無く、リブの付け根を変わり目から除くと書いた製品も見つからなかった

以下は調べた内容のまま。

## 1. 製品ごとの表

| 製品 | 方式 | 厚肉の判定 | 変わり目の機能（有無と定義） | 表示 | 出典 |
|---|---|---|---|---|---|
| **Onshape** Thickness analysis | Rolling ball（最大内接球の直径）と Ray（法線方向の光線）を選ぶ | 既定のしきい値は無い。凡例の上下限をユーザーが決める。範囲外は専用色。「Dim colors scale」で 3 色表示にできる | **有り（唯一、変わり目そのものを出す）**。「Rolling ball gradient (%)」「Ray gradient (%)」。定義は「表面上をある方向へ動いたときの肉厚の最大の増減量 ÷ その方向の測地距離」。無次元で % 表示。ブログは「その点の肉厚に対する %」と書いていて、ヘルプと食い違う。既定のしきい値は無い | 点ごとの連続の色。球の分布は「どの部品でも連続」、レイの分布は「角の近くで不連続」とヘルプに明記 | [S37][S38] |
| **SOLIDWORKS** Thickness Analysis（Utilities） | 非公開（テッセレーションの上で計算。解像度 Low/Medium/High とテッセレーションのサイズを選ぶ） | Target thickness と Thick region limit をユーザーが絶対値で入れる（既定値の記載は無い） | 無し | Continuous（グラデーション）か Discrete（色の帯の数を指定）。カーソルで値を出す。レポートは面ごとに集計する | [S1][S2][S3][S4] |
| SOLIDWORKS Plastics Nominal Wall Thickness Advisor | 非公開 | 公称肉厚を自動で求め、そこからのずれ（%）か値をコンターで出す | 無し（公称からのずれで見せるだけ） | コンター | [S5][S6] |
| SOLIDWORKS DFMXpress | 非公開 | 最小・最大肉厚のルール。最小は 2.0 mm を推奨。最大の推奨値は書いていない | 無し | ルール違反の箇所を一覧 | [S7][S8] |
| **Siemens NX** Check Wall Thickness（Mold Wizard 他） | API の列挙は Ray / RollingBall / VectorProject。RollingBall では点を選ぶと球を作る・動的な球を出す設定がある。レイのベクトルを表示できる | 平均・最小・最大の肉厚を返す（NX 1847 から）。Molded Part Design の Moldability Validation が thin walls / thick walls を色で出す（しきい値の値は見つからない） | 見つからない | 色分け。対向側のメッシュ要素やレイを表示できる | [S9][S10][S11] |
| **PTC Creo** 3D Thickness | 長く Ray tracing だけ（凡例は 3 色）。Creo+ 2026-05 で Rolling ball を追加して既定にし、凡例も連続の色にした | 上限・下限を入れる。Creo 6.0 で Threshold angle を追加（定義は本文を読めず未確認） | 見つからない | 2026-05 以降はフルカラーの凡例 | [S12][S13] |
| **Autodesk Moldflow**（Adviser / Insight）Design Adviser | Dual Domain は表裏の要素を組にして（mesh matching）その距離。3D は maximal ball（角では球が小さくなり薄く出る、と明記） | **公称肉厚に対する比**。Nominal wall thickness 結果が公称肉厚を自動で求め（方法は非公開）、既定で ±20 %（黄・シアン）と ±50 %（赤・青）で帯を変える。帯は変更できる | 自動の検出は無い。ヘルプは「厚い所と薄い所が隣り合う所を見よ」と目視を促すだけ | 要素ごとの 5 色の帯か、値 | [S14][S15][S17] |
| Moldflow Sink marks estimate | 流動解析の結果 | ― | ― リブの付け根の裏のヒケは**これで拾う**（下の 2 章） | ヒケの深さ・陰影表示 | [S16] |
| Autodesk Simulation DFM（2014〜2016、旧製品） | 非公開 | 「薄すぎ」「厚すぎ」の警告。推奨最小は 0.9 mm。厚すぎの値は書いていない | 「Part shows high thickness variation」（公称肉厚のばらつきの検査。定義は非公開） | 赤で強調。局所肉厚のカラーマップ | [S18] |
| **Autodesk Fusion** Design Advice（Design Extension） | 非公開 | Plastic Rule の Thickness Range（最小・最大の絶対値）を外れた所を Too Thin / Too Thick | 「Large Thickness Variation」。Plastic Rule の Thickness Variation（最大の %）を超えた所。**何に対する % かは公開資料に無い**（API の説明文も最大肉厚の説明の写し間違い） | 「Alerts Only」（警告の所を赤で重ねる）と「Full Range」（赤＝厚い〜濃い青＝薄いのグラデーション）。警告は領域ごとの一覧 | [S19][S20][S21] |
| **Altair Inspire Mold 2026 / Inspire Cast** | 非公開 | Critical Areas は肉厚の分布を**球**で見せる。黄＝平均に近い、赤＝最大・最小に近い。Thickness はヒートマップとスライダー | 無し。Quick 解析の Thickness 結果の説明に「急な肉厚変化は冷却のむらを生み、ヒケの原因」とあるだけ | 球の表示、ヒートマップ | [S22][S23][S24] |
| Moldex3D | ヒケは保圧解析の結果（sink mark indicator と変位）として出す | 形状だけの肉厚チェックの公開資料は見つからない | 見つからない | ― | [S25] |
| **Elysium CADdoctor**／CADmeister／iCAD | CADdoctor は中立面の自動作成で「板厚変化部やボス・リブを適切に接続する」と書くだけ。CADmeister は「薄肉厚肉検査」の機能があることだけ分かった。iCAD は見つからない | 見つからない | 見つからない | CADmeister はグラデーション表示 | [S26][S27] |
| **Materialise Magics** | 非公開。オンラインの i.materialise はボクセル法（向きで結果が変わると明記） | 見つからない | 見つからない | Magics Print は「marking」（箇所と肉厚の一覧）か「gradient」（連続の色） | [S28] |
| **Hexagon** VGSTUDIO MAX | Ray（探索角の中で対向面までの最短距離を探し、反対側から元の点へ戻れるかを確かめる）と Sphere（各位置で最大の球）。レイは平行な面の工業製品向き、球は有機的な形向き | 最小・最大・平均・ばらつきに許容値。ノイズのフィルタ | 見つからない | 色分け。範囲で部品を分ける | [S29][S30] |
| Hexagon（ITI）CADfix 13 | Medial Fields（中立軸変換の近似）で 3D の肉厚の場を作る | 肉厚の極小・極大を探す。しきい値より厚い領域を点群で出す | 見つからない | 点群 | [S31] |
| GeomCaliper（Geometric/HCL、CATIA・Creo のアドオン） | Normal ray と Rolling sphere。「稜線の小さな肉厚を無視する」設定 | 最小・最大を入れて色分け | 見つからない | 色の帯 | [S11] |
| Cimatron 2026（参考：金型 CAD） | Sphere と Ray を切り替え。Sphere は「最大肉厚の領域の検出に向く」、Ray は「最小肉厚の領域の検出に向く」と明記。鋭い稜線の扱いを 3 つから選ぶ（下の 3 章） | 色の範囲をユーザーが決める。最大肉厚の位置に半透明の球とラベルを出す | 無し | 色分け。点を選ぶとラベル | [S32][S33][S34] |
| Kisters 3DViewStation（参考：CAD ビューア） | Ray-based と Rolling ball | 色の範囲。「Apply quantiles」で上下 5 % を外して色を付ける | 無し | 三角形の重心ごとに計算し、三角形の上で補間して塗る。レイで結果を検証する設定 | [S35] |
| SpinFire Insight（参考：CAD ビューア） | 性能のためにレイ法 | 色の範囲をユーザーが決める（5 色＋範囲外の 2 色） | 無し。ただし「肉厚が変わる所を検出して三角形を細かくする」（色の質のため） | 点ごとの色。細分化のレベルを選ぶ | [S36] |
| **CADEX MTK**（DFM の SDK） | Voxelization（既定）か Ray marching（向かい合う 2 面の角度の許容 70°） | 絶対値：MinWallThickness 1.0 mm、MaxWallThickness 4.0 mm（既定） | 「Irregular wall thickness」：\|D − D_avg\| / D_avg ≤ U_D。D は壁の 2 面の間の距離、D_avg は**中央値**、U_D の既定は 0.2 | 違反した壁の 2 面を issue として返す（面単位） | [S39][S40][S42] |
| **DFMPro**（Geometric、現 HCL） | 自社の特許では、三角形化したモデルの内側に接する球で肉厚を出す | 材料ごとの公称肉厚の範囲チェック（2011 年に追加） | 2011 年の 3.1 で「sudden wall thickness variation」チェックを追加。製品での定義・既定値は非公開。自社の特許の定義は「点 P を囲む三角形の中心の肉厚と P の肉厚との差の最大」 | ルール違反の一覧 | [S43][S44][S45] |
| aPriori（原価見積り） | 非公開（注記に「サンプリング／レイトレーシングの誤差」とある） | 公称肉厚を分布から求める式を公開（下の 4 章） | 見つからない | 指定の肉厚範囲の所に赤い球 | [S46] |
| Protolabs（自動見積りの DFM） | 非公開 | 「Required Change: Thick Area」。同じ解説に材料別の推奨肉厚の表がある（PC 1.016〜3.81 mm、アクリル 0.635〜12.7 mm など）。判定の式は非公開 | 見つからない | 3D の画面で箇所を示し、直すべき肉厚の値を出す | [S47][S48] |
| Fictiv（自動 DFM） | 非公開 | 「Thickness Review」がヒケ・反りの恐れのある厚い所をヒートマップで出す | 見つからない | ヒートマップ | [S49] |
| Xometry／Hubs（Protolabs Network） | 自動 DFM の肉厚判定の公開記述は見つからない | ― | ― | ― | ― |
| 富士ゼロックスの特許 US9200891B1 | 格子点から法線方向に仮想の光線を出し、交わる面までの距離 | **基本肉厚に対する比**：基本肉厚×A〜基本肉厚×A+B の範囲を確認部位として色分け（A・B は既定の定数、値は書いていない） | 無し | 確認部位をあらかじめ決めた幅ごとの色で示す | [S50] |
| 論文：Inui ら 2018（JCDE） | 縮む球の方法（三角形の重心から大きな球を始め、小さくしていく） | 収縮量＝肉厚×収縮率（PC は 0.5〜0.7 %）。近傍より収縮量が 0.001 mm を超えて大きい三角形をヒケ候補にする | 近傍との比較そのものが変わり目の検出に当たる（下の 2 章） | 三角形ごと | [S51] |
| 論文：Baltadouros & Duflou 2026（arXiv、査読前） | 成形は球（法線の線分上に候補の中心を並べる近似）、切削はレイ | 最大肉厚のしきい値（事例は 5.0 mm） | 「隣り合う面の組の肉厚の相対差が許容値を超えたら非一様」。事例の許容値は 60 % | 面ごと。肉厚の帯（ゾーン）に分けて統計を出す | [S52] |

表に入れきれない補足：
- NX のヘルプ・API 文書は現在ログインが要る。上の内容は検索結果の抜粋と旧版の API 文書の見出しから。既定の方式（Ray とする抜粋があった）は本文で確かめられていない [S9]。
- Creo の記事 CS240806 は本文を取得できず、検索の抜粋（「Creo 6.0 で Threshold angle」「最小肉厚は測れない」）だけ [S13]。
- Fusion の Plastic Rule の既定値（材料ごとの範囲や変動 %）は公開資料で見つからない。

---

## 2. 「肉厚の変わり目」：各社の定義とリブの付け根の扱い

### 2.1 変わり目そのものを出すもの

| 出所 | 何を何で割るか | 距離の決め方 | しきい値の既定値 |
|---|---|---|---|
| Onshape（gradient） | 肉厚の最大の増減量 ÷ 測地距離（ヘルプ）。ブログは「その点の肉厚に対する %」 | 表面上の無限小の移動（測地的な微分） | 無し（凡例の範囲をユーザーが決める） |
| DFMPro（製品） | 非公開（「sudden wall thickness variation」） | 非公開 | 非公開 |
| Geometric の特許 US8219230B2 | 差（比ではない）。偏差 = max{ t_i − t }（t は点 P の肉厚、t_i は P を囲む三角形の中心の肉厚） | P を囲む三角形（メッシュの 1 周の近傍） | 記載無し |
| Baltadouros & Duflou 2026 | 隣り合う 2 面の肉厚の相対差 | 面の重心の k-d 木で「空間的に隣り合う」面の組 | ユーザーが決める（事例は 60 %） |
| Inui ら 2018 | 収縮量（肉厚×収縮率）の差。両隣より 0.001 mm を超えて大きいこと | 1〜2 mm 以内の三角形。両隣が挟む角が 165° 超、法線の差が 25° 未満（平らな所だけ） | 論文中の値 |

### 2.2 「基準からのずれ」で見せるもの（変わり目そのものではない）

- Moldflow：公称肉厚から ±20 % / ±50 %（既定、変更可）。隣り合う厚薄は人が見て探す [S14]。
- CADEX MTK：壁ごとに中央値からのずれが 20 % を超えたら Irregular wall thickness [S40][S39]。
- SOLIDWORKS Plastics：公称からのずれ（%）のコンター [S5]。
- Fusion：Thickness Variation（%）を超えた領域が Large Thickness Variation。基準は非公開 [S19]。
- Autodesk Simulation DFM：「high thickness variation」。定義は非公開 [S18]。

### 2.3 リブの付け根

- **はっきり拾うもの**
  - Moldflow の Sink marks estimate は「裏面のリブ・ボス・内側のフィレットが起こすヒケ」を出す。「局所の厚肉が起こすヒケは出さない」と書いてあり、リブの付け根と単なる厚肉を別の結果に分けている。目安として「リブが主壁の 60 % 以下なら目立つヒケは出にくい」 [S16]。
  - Inui ら 2018 は、リブの接続部の裏側を「近くの壁より少し厚い所」として拾う。リブ専用の規則は無く、肉厚の差だけで出てくる [S51]。
- **変わり目の検出とは別のルールで扱うもの**
  - CADEX MTK はリブを特徴として認識し、リブ厚 / 壁厚の比を 0.4〜0.6（既定）、付け根の R を壁厚の 0.25 倍以上（既定）で判定する。Irregular wall thickness は「壁＝2 面の組」の単位で、リブの付け根を変わり目として扱う記述は無い [S39][S41]。
  - DFMPro はリブの推奨寸法のルールを持つ。自社の特許には「リブ厚 / 公称肉厚がしきい値未満」の規則の例がある [S44][S45]。
- **除外すると明記したもの**：見つからない。角を除く設定は多い（3 章）が、どれも凸の稜線（外側の角）の話で、リブの付け根（凹の隅）の話ではない。
- **記述が無いもの**：Onshape と Fusion は、勾配や変動の警告がリブの付け根でどうなるかを書いていない。【推測】球の方法の勾配は付け根で肉厚が急に増えるので高く出るはずで、Onshape の gradient はリブの付け根を「変わり目」として拾う側だと考える。
- Baltadouros & Duflou は、隣り合う面の相対差を空間的なつながりで絞らずに全部出し、設計者が見て判断する方針を明記している [S52]。

---

## 3. 方式（レイ・球）の使い分けと、角・稜線の扱い

### 3.1 各社の方式と使い分け

| 製品 | 用意している方式 | 既定・使い分けの説明 |
|---|---|---|
| Onshape | 球、レイ（＋それぞれの勾配） | 球の分布は連続、レイは角で不連続。レイは「細く見えても、視線が通れば長いレイになる」 [S37][S38] |
| Creo | レイ → 2026-05 に球を追加 | 球を既定にした（「複雑な形で正確で滑らか」） [S12] |
| NX | Ray / RollingBall / VectorProject | 利用者の談：一定肉厚のモデルにはレイ、鋳物には球（Chrysler の例） [S11][S9] |
| Moldflow | Dual Domain（表裏の距離）／3D（maximal ball） | 薄いシェル状の部品は Dual Domain、局所的に厚い部品は 3D [S15] |
| Cimatron | 球／レイ | 球は最大肉厚の検出、レイは最小肉厚の検出 [S32] |
| VGSTUDIO MAX | レイ／球 | レイは平行な面の工業製品、球は有機的・枝分かれのある形 [S29][S30] |
| Kisters 3DViewStation | レイ／球 | 両方を同じ画面で選ぶ。プリセットあり [S35] |
| SpinFire | レイだけ | 性能のため [S36] |
| CADEX MTK | ボクセル（既定）／Ray marching | ボクセルは頑健だが重く、ボクセル 1 つより薄い所は落ちる。Ray marching は速いが壊れたメッシュに弱い [S42] |
| DFMPro（特許） | 球 | 薄肉・厚肉とも球 [S45] |
| Baltadouros & Duflou | 球（成形）／レイ（切削） | 工程で方式を選ぶ [S52] |

### 3.2 角・稜線の扱い

球の方法は凸の稜線で肉厚が 0 に向かう（Cimatron「稜線の上では 0」[S33]、Moldflow「3D では角が薄く出る」[S15]、Baltadouros「凸の稜線と角で系統的に小さく出る」[S52]）。レイの方法は角の近くで値が飛ぶ（Onshape [S37]）。各社の対策は次のとおり。

| 製品 | 設定・方法 | 既定 |
|---|---|---|
| SOLIDWORKS | 「Treat corners as zero thickness」：鋭い角を薄い所として扱わない（「すべての角を一様な肉厚とみなす」）。Show thick regions のときだけ出る | 記載無し（API では treatcornerzero の真偽） [S1][S4] |
| Cimatron | 球の方法で稜線の近くを 3 通りから選ぶ。Extrapolate（稜線に近い点を無視し、隣の点と同じ肉厚にする）／Sphere Size（そのままの値）／Neutral Color（中立の色で塗る） | Sphere Size [S33] |
| Kisters 3DViewStation | 球の方法の Angle tolerance：「とても小さな球を作る、許容値より小さな角を無視する」 | 25.0 [S35] |
| GeomCaliper | 稜線の小さな肉厚を無視する | 記載無し [S11] |
| Geometric の特許 | 角の領域は「隣接する面を無視して」避ける。側面に当たって小さくなる球は薄肉の計算に使わない | ― [S45] |
| Baltadouros & Duflou | 外形の境界に近い面の球の肉厚の平均×edge factor より小さい面を「信頼できない」として外す（事例では面の 6.2 % を除外） | edge factor はユーザーが決める [S52] |
| CADEX MTK（Ray marching） | 向かい合う 2 面の角度が許容値以下のときだけ「壁」とみなす。π/2 より大きくすると直交する稜線同士も壁と組む | 70° [S42] |
| VGSTUDIO MAX（レイ） | 探索角の中で最短距離を探し、反対側から元の点へ戻れることを確かめる | 記載無し [S29] |
| Kisters（球） | 「Validate result」：レイで結果を確かめる（閉じていない形などを見つける） | 有効 [S35] |
| Creo | Threshold angle（Creo 6.0 から） | 定義・既定は未確認 [S13] |
| Moldflow | 対策の設定は無い。Dual Domain なら角も一般部と同じ肉厚になる、と方式の違いとして説明 | ― [S15] |

---

## 4. 厚肉の上限の決め方（絶対値か比か）と既定値

### 4.1 絶対値で決めるもの

- SOLIDWORKS：Thick region limit をユーザーが入れる。既定値の記載は無い [S1]。
- DFMXpress：最大肉厚をユーザーが入れる（入力範囲 1.0〜100000）。最小の推奨は 2.0 mm、最大の推奨値は書いていない [S7][S8]。
- Fusion：Plastic Rule の Thickness Range の上限（材料ごとのルールで持つ） [S19][S20]。
- CADEX MTK：MaxWallThickness 4.0 mm（既定） [S39]。
- Protolabs：判定の式は非公開。同じ解説に材料別の推奨肉厚（PC 1.016〜3.81 mm、アクリル 0.635〜12.7 mm、ABS 1.143〜3.556 mm など） [S47]。
- DFMPro：材料ごとの公称肉厚の範囲（材料の追加・範囲の編集ができる） [S43]。
- Creo、Cimatron、Kisters、SpinFire、VGSTUDIO MAX、Onshape：色の範囲や許容値をユーザーが決める。既定値は無い。
- Baltadouros & Duflou：最大肉厚のしきい値（事例は 5.0 mm） [S52]。

### 4.2 公称肉厚（一般部）に対する比で決めるもの

- Moldflow：公称＋20 % で「厚い」、＋50 % で「とても厚い」（既定、変更可） [S14]。
- CADEX MTK：中央値からのずれ 20 % 超（Irregular wall thickness。厚い側・薄い側の両方） [S40]。
- SOLIDWORKS Plastics：公称からのずれ（%） [S5]。
- 富士ゼロックスの特許：基本肉厚×A〜基本肉厚×A+B を確認部位にする（A・B の値は書いていない） [S50]。
- Altair Critical Areas：平均肉厚に近いか、最大・最小に近いかで球の色を変える（数値の基準は書いていない） [S22][S24]。

### 4.3 公称肉厚（一般部）の決め方

| 出所 | 決め方 |
|---|---|
| CADEX MTK | 中央値（median） [S39] |
| aPriori | 肉厚の標準偏差 σ と縦横比で式を切り替える。(1) σ > 0.50 mm（ばらつき大）：「表面積で厚い方の 20 % を除いた中の最大値」（Min 80 Thickness）。(2) ばらつきが小・中で、高さ（型開き方向）/ 長さ ≥ 0.50：平均＋4σ。(3) それ以外で σ ≤ 0.30 mm：平均＋3σ。(4) それ以外で 0.30 < σ ≤ 0.50 mm：(1) と (3) の平均。計算値が実測の最大を超えたら最大に丸める（しきい値は 2021 R1 の既定） [S46] |
| 富士ゼロックスの特許 | 肉厚ごとの面積を集計する。最も面積の大きい肉厚が 2 位の 2 倍以上なら、それを基本肉厚にする。そうでなければ立ち壁を除いて同じ判定をする。平面部と立ち壁では平面部の肉厚を基本とする [S50] |
| Moldflow、SOLIDWORKS Plastics | 自動で求める（方法は非公開） [S14][S6] |
| Fusion | Plastic Rule の Thickness（設計者がルールで与える） [S20] |
| Altair | 平均肉厚 [S22] |

---

## 5. 面ごとに塗るか、点ごとに連続で塗るか

- **点ごと（三角形・頂点・要素ごと）の連続の色**が大半：SOLIDWORKS（Continuous / Discrete）、Onshape、Creo+、Fusion の Full Range、Moldflow（要素ごと）、Kisters（三角形の重心で計算し補間）、SpinFire（肉厚が変わる所で細分化）、Magics の gradient、Cimatron、Inui ら [S1][S37][S12][S19][S14][S35][S36][S28][S32][S51]。
- **面ごとの集計**：
  - SOLIDWORKS のレポートは肉厚の範囲ごとに面の数と面積を数える。**1 つの面が 2 つ以上の範囲にまたがるときは、より重大な方の範囲に入れる**。重大な面を共有するフィーチャーはすべて重大なフィーチャーとする [S3]。
  - CADEX MTK は違反した壁の 2 面を issue として返す [S40]。
  - 富士ゼロックスの特許は面ごと・肉厚ごとの面積を集計して基本肉厚を決める [S50]。
  - Baltadouros & Duflou の切削の側は、STEP の面ごとに対応する三角形のレイの肉厚の平均を取る（成形の側は三角形ごとに判定してから肉厚の帯に分ける） [S52]。
- 1 つの面が厚さの違う所にまたがるときの扱いを書いているのは、SOLIDWORKS のレポート（重大な方へ）と、平均を取る Baltadouros & Duflou の切削の側だけ。ほかは見つからない。

---

## 6. 出典

- [S1] SOLIDWORKS Help 2022「Displaying Areas of a Part That Are Less Than and Greater Than a Specified Thickness Range」 https://help.solidworks.com/2022/English/SolidWorks/sldworks/t_displaying_areas_part_greater_than_less_than.htm （手順 2 の Treat corners as zero thickness、Color Settings、Performance/Accuracy）
- [S2] SOLIDWORKS Help 2012「Running Thickness Analysis」 https://help.solidworks.com/2012/English/SolidWorks/swutilities/Running_Thickness_Analysis.htm
- [S3] SOLIDWORKS Help 2017「Thickness Analysis Reports」 https://help.solidworks.com/2017/English/SolidWorks/sldworks/r_thickness_analysis_reports.htm （Analysis Details の Thickness range）
- [S4] SOLIDWORKS 2022 What's New「Thickness Analysis Resolution」 https://help.solidworks.com/2022/English/WhatsNew/c_wn2022_utilities_thickness_analysis_res.htm ／ API「RunThickAnalysis2」 https://help.solidworks.com/2022/English/api/swutilitiesapi/SolidWorks.Interop.gtswutilities~SolidWorks.Interop.gtswutilities.IThicknessAnalysis~RunThickAnalysis2.html
- [S5] SOLIDWORKS Plastics Help 2020「Nominal Wall Thickness PropertyManager」 https://help.solidworks.com/2020/English/swplastics/r_nominal_wall_thickness.htm
- [S6] SOLIDWORKS 2015 What's New「Nominal Wall Thickness Advisor」 https://help.solidworks.com/2015/English/WhatsNew/wn_2014_nominal_wall_thickness_advisor.htm
- [S7] DFMXpress Help 2019「Injection Molding Rules」 https://help.solidworks.com/2019/English/SolidWorks/dfmxpress/c_Injection_Molding_Rules.htm
- [S8] DFMXpress Help 2016「Rule Parameters」 https://help.solidworks.com/2016/english/SolidWorks/dfmxpress/r_settings.htm
- [S9] NXOpen API「WallThicknessCheckerBuilder」（NX 10〜1899。現在はログインが要る。検索結果の抜粋で確認） https://docs.plm.automation.siemens.com/data_services/resources/nx/12/nx_api/custom/en_US/nxopen_python_ref/NXOpen.Tooling.WallThicknessCheckerBuilder.html
- [S10] Siemens ブログ「Auto draft calculation（NX 2023-12）」の Moldability Validation の節 https://blogs.sw.siemens.com/designcenter/auto-draft-calculation-nx-jan-2024/
- [S11] Digital Engineering 24/7「Measuring Wall Thickness」（GeomCaliper の紹介、Chrysler の利用者の談） https://www.digitalengineering247.com/de/measuring-wall-thickness ／ GeomCaliper の製品ページ https://geomcaliper-geometricglobal.tangence.com
- [S12] PTC Creo+ What's New 2026-05「Improved 3D Thickness Analysis」 https://support.ptc.com/help/creo/creo_plus/usascii/whats_new/analysis_3d_thickness.html
- [S13] PTC Article CS240806（3D Thickness の Tolerance・Post-processing・Threshold Angle。本文は取得できず、検索の抜粋のみ） https://www.ptc.com/en/support/article/CS240806
- [S14] Moldflow Help 2015「Nominal wall thickness result」 https://help.autodesk.com/cloudhelp/2015/ENU/MoldflowComm/files/GUID-FE962B8F-3F96-410E-94D4-98D06811215F.htm （Using this result、Things to look for）
- [S15] Moldflow Help 2015「Understanding thickness calculation」 https://help.autodesk.com/cloudhelp/2015/ENU/MoldflowComm/files/GUID-618D6B2E-E5F9-4232-8CBA-EAF4EE8FA7FD.htm
- [S16] Moldflow Adviser 2016「Sink marks estimate and Sink marks shaded results」 https://help.autodesk.com/cloudhelp/2016/ENU/MoldflowAdviser-UsersGuide/files/GUID-EA834EAD-7E16-4096-BF77-BE2391A46FE4.htm ／ Moldflow Insight 2018「Sink marks estimate result」 https://help.autodesk.com/cloudhelp/2018/ENU/MoldflowInsight/files/GUID-E37E12FE-DE85-4173-BCD9-064513224425.htm
- [S17] Moldflow Adviser 2015「Design Adviser analysis」 https://help.autodesk.com/cloudhelp/2015/ENU/MoldflowAdvisor/files/GUID-D0A0D7D9-9F3D-48C7-8734-11DC53DF9E1B.htm
- [S18] Autodesk Simulation DFM 2016「Wall thickness」 https://help.autodesk.com/cloudhelp/2016/ENU/DFM/files/GUID-CFC1BEF6-FD8D-4A66-9D16-5A6BBFEA7BBA.htm
- [S19] Fusion Help「Analyze a solid body to identify manufacturability concerns」 https://help.autodesk.com/cloudhelp/ENU/Fusion-Model/files/SLD-USE-DESIGN-ADVICE.htm （Review detailed Thickness results）
- [S20] Fusion Help「Plastic rules」 https://help.autodesk.com/cloudhelp/ENU/Fusion-Model/files/SLD-SETUP-PLASTIC-RULES.htm ／「Design Advice」 https://help.autodesk.com/cloudhelp/ENU/Fusion-Model/files/SLD-DESIGN-ADVICE.htm
- [S21] Fusion API「PlasticRule」 https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_PlasticRule.htm ／「PlasticRule.thicknessVariation」 https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_PlasticRule_thicknessVariation.htm
- [S22] Altair Inspire Mold 2026 Help「Part Cavity」（Part Analysis の Critical Areas と Thickness） https://help.altair.com/mold/en_us/topics/mold/cavity/cavity_c-2.htm
- [S23] Altair Inspire Mold 2026 Help「Quick Molding Analysis」（Quick Result Types の Thickness） https://help.altair.com/mold/en_us/topics/mold/analysis/molding_analysis_quick_c.htm ／ Release Notes 2026 https://help.altair.com/mold/whatsnew/InspireMold_2026_ReleaseNotes_English.pdf （p.1 Part Analysis）
- [S24] Altair Inspire Cast 2025 Help「Thickness Analysis」 https://2025.help.altair.com/2025/cast/en_us/topics/cast/casting/thickness_analysis_t.htm
- [S25] Moldex3D Pack の製品ページ（sink mark indicator。検索の抜粋のみ） https://www.moldex3d.com/products/software/moldex3d/pack/
- [S26] エリジオン「CADdoctor EX6.0」リリース（中立面オプション） https://www.atpress.ne.jp/news/44050
- [S27] MONOist「CADmeister V11.1 を発表」（薄肉厚肉検査の表示改善） https://monoist.itmedia.co.jp/mn/articles/1702/10/news052.html
- [S28] Materialise Magics Print のチュートリアル（marking と gradient。検索の抜粋のみ） https://reseller.materialise.com/en/academy-software/resources/magics-print/tutorial-how-to-analyze-builds ／ i.materialise「Wall thickness analysis」（ボクセル。検索の抜粋のみ） https://i.materialise.com/learn/wall-thickness-analysis
- [S29] Volume Graphics「Spheres and Rays: Wall Thickness Analysis」 https://volumegraphics.hexagon.com/en/explore-nde/our-stories/spheres-and-rays-wall-thickness-analysis.html
- [S30] Volume Graphics「Wall Thickness Analysis」（機能ページ） https://volumegraphics.hexagon.com/en/products/software-features/wall-thickness-analysis.html
- [S31] ITI「CADfix 13 Unveils Medial Fields」 https://www.iti-global.com/resource-center/blog/revolutionizing-3d-modeling-cadfix-13-unveils-medial-fields/
- [S32] Cimatron 2026 Help「Wall Thickness Analysis: Options and Results」 https://help.cimatron.com/en/2026/wall_thickness_analysis_options_and_results.htm
- [S33] Cimatron 2026 Help「Wall Thickness Analysis: 3D Sphere Analysis」 https://help.cimatron.com/en/2026/wall_thickness_analysis_3d_sphere_analysis.htm
- [S34] Cimatron 2026 Help「Wall Thickness Analysis: 3D Ray Analysis」 https://help.cimatron.com/en/2026/wall_thickness_analysis_3d_ray_analysis.htm
- [S35] Kisters 3DViewStation WebViewer Help「Wall Thickness: Heat Map」 https://help-viewer.kisters.de/webviewer/en/3dvs_wv_tut_functions_wallthicknessheatmap.php （Toolpane Settings の表、Difference between ray based and rolling ball）
- [S36] SpinFire Insight Docs「Wall Thickness Analysis」 https://docs.techsoft3d.com/spinfire/insight/spinfire_insight_functions/3d_documents/3d_analysis/wall_thickness_analysis.html
- [S37] Onshape Help「Thickness Analysis」（2026-10-09 更新） https://cad.onshape.com/help/Content/View/thickness_analysis.htm （Method の一覧、Thickness gradient の節）
- [S38] Onshape ブログ「Enhance Your Design Process with Thickness Analysis」（2024-11-04） https://www.onshape.com/en/blog/thickness-analysis
- [S39] CADEX MTK「DFMMolding_AnalyzerParameters」 https://docs.cadexsoft.com/mtk/classcadex_1_1_d_f_m_molding___analyzer_parameters
- [S40] CADEX MTK「DFMMolding_IrregularWallThicknessIssue」 https://docs.cadexsoft.com/mtk/classcadex_1_1_d_f_m_molding___irregular_wall_thickness_issue
- [S41] CADEX MTK「DFMMolding_IrregularThicknessRibIssue」 https://docs.cadexsoft.com/mtk/classcadex_1_1_d_f_m_molding___irregular_thickness_rib_issue
- [S42] CADEX MTK「Wall Thickness Analysis」 https://docs.cadexsoft.com/mtk/mtk_wall_thickness ／「WallThickness_RayMarchingParameters」 https://docs.cadexsoft.com/mtk/classcadex_1_1_wall_thickness___ray_marching_parameters ／「Molding DFM」 https://docs.cadexsoft.com/mtk/mtk_molding_dfm
- [S43] Digital Engineering 24/7「Geometric Adds Tolerance and Material Based Checks to DFMPro」（2011-09-26） https://www.digitalengineering247.com/article/geometric-adds-tolerance-and-material-based-checks-to-dfmpro
- [S44] Geometric「DFMPro for Injection Molding」（スライド、2009） https://www.slideshare.net/slideshow/dfmpro-for-injection-molding-oct09/2350887
- [S45] 特許 US8219230B2「Manufacturability evaluation of injection molded plastic models using a CAD based DFX evaluation system」（Geometric Ltd.、優先日 2009-10-19） https://patents.google.com/patent/US8219230B2/en （FIG. 11・FIG. 12 の説明、式 (1)）
- [S46] aPriori Cost Model Guide 2021 R1「Nominal Wall Thickness」 https://docs.apriori.com/Collateral/Documents/English-US/online_help/2021_R1/COST_MODEL_GUIDE/AP_CMG0849Nominal_Wall_Thickness.html ／ 2024 R1 SP3 のリリースノート（赤い球の表示。検索の抜粋のみ） https://docs.apriori.com/en/Pro/current/app/rn/24-1-x-x/24-1-3-0/pg-plastic-molding.htm
- [S47] Protolabs「Solving Wall Thickness Issues in Molded Parts」 https://www.protolabs.com/resources/design-tips/solving-wall-thickness-issues-in-molded-parts/ （Required Change: Thick Area、Recommended Wall Thickness by Plastic Type）
- [S48] Protolabs「Navigating Manufacturing Analysis」 https://www.protolabs.com/resources/design-tips/navigating-manufacturing-analysis/
- [S49] Fictiv「Announcing Fictiv's Automated Injection Molding DFM」 https://www.fictiv.com/articles/announcing-fictivs-automated-injection-molding-dfm （Thickness Review）
- [S50] 特許 US9200891B1「Molding wall thickness recognition apparatus…」（Fuji Xerox、優先日 2014-06-30） https://patents.google.com/patent/US9200891
- [S51] M. Inui, S. Onishi, N. Umezu, "Visualization of potential sink marks using thickness analysis of finely tessellated solid model", JCDE 5(4) 409–418, 2018. doi:10.1016/j.jcde.2018.02.003 https://academic.oup.com/jcde/article/5/4/409/5728988
- [S52] S. Baltadouros, J. R. Duflou, "Process-Aware Thickness Analysis in CAD Models using Hybrid Geometric Methods", arXiv:2609.15245（2026-09-14、査読前。参考文献に未完成の項目がある） https://arxiv.org/abs/2609.15245 （3.1 Molding Analysis、表 1・3）
