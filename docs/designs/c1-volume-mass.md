> **C1（issue #8） の設計の下書き（2026-10-08、手元のセッションで作成）。**
> 実装（クラウドのセッション）で今のコードと照らし、次の点を直してから作った。本文は下書きのまま残す。
> - §0 の早送り・手元のパスは不要（master に #9 が入っている）。E2E は backend の venv の Python で回す。
> - B-rep の「厚みがない」の判定（|V| ≤ 1e-9·対角³）は、OCCT で作れる薄い箱（厚み 1e-6 mm でも V/対角³ ≈ 3.5e-8）
>   では起きない。pytest はメッシュの「表裏 2 枚の正方形」（閉じていて向きも揃い、体積 0）で確かめる。
>   §4.1 の表に無い「面の向きが不揃い」のメッシュ（三角形を 1 枚裏返した箱）も足した。
> - `PropertiesPanel` の constructor から `onLayout` を呼ばない。呼ぶと `fitCornerStack` が、まだ代入されていない
>   `propsPanel`（const の TDZ）に触れて起動時に落ちる。
> - E2E の 4（比重欄で矢印キー）で、OrbitControls の減衰が毎フレーム 1e-12 ほど位置を丸めるので、完全一致でなく 1e-6 で比べる。
> - 面積の `SkipShared` は使わない（既定の False）。2 つの殻が共有する面は実データにもテストにも無く、変異（True → False）を
>   入れても何も落ちなかった。体積は塊を現れた回数だけ足すので、面積もそれに揃える。
> - A1（#11）を先にマージしたので、HUD は 2 行、`__cadView` は near/far を返す。

# C1 設計: 体積・表面積・重量（比重からショット重量の目安）

## 0. 前提: worktree が 1 コミット遅れている

worktree の HEAD は `d3b7ca1`、`origin/master` は `3d81e74`（#9 IGES の縫い合わせ）。まず早送りすること。

```
git -C /home/shostako/.cache/cad-viewer-wt/c1 merge --ff-only origin/master
```

この設計は縫い合わせ後の挙動を前提にしている。縫い合わせ後、ばらばらの IGES 面は「ソリッド」になり、開いた面のまとまりは「サーフェス」、ばらばらの曲線は「曲線（N 本）」という 1 部品になる。下の IGES の API テストはこれに依存する。

E2E `test_iges_sewing.py` は `backend/.venv` を探すが、worktree にはない。先に次のコマンドで素材を作っておく。

```
/home/shostako/ClaudeCode/cad-viewer/backend/.venv/bin/python testdata/make_iges_loose.py
```

作られる `testdata/loose_faces_box.igs` は git の追跡対象外。

**環境で実際に確かめたこと**（OCP 7.9.3.1、trimesh 4.12.2、lil-gui 0.21.0）:

| 確認内容 | 結果 |
|---|---|
| `BRepGProp.VolumeProperties_s` / `SurfaceProperties_s`（既定のガウス積分）の精度 | 円柱 r4 h25 の体積・面積とも相対誤差 ≤ 1e-15 |
| mini_mold の部品 | 体積 90000 / 1256.637 / 1256.637 / 24000、面積 16800 / 728.849 / 728.849 / 5200、重心 (50,30,7.5) (25,30,27.5) (75,30,27.5) (50,30,25) |
| 中空ソリッド（100³ の立方体から中央の 50³ を Cut） | 体積 875000、面積 75000、閉じた殻 2 枚 |
| 裏返したソリッド | 体積が負（-6000）。重心は正しいまま |
| `BRep_Tool.IsClosed_s(shell)` | 円柱・球・円錐・トーラスの殻は True（縫い目・退化辺を正しく扱う）、開いた殻は False |
| `IsClosed_s(solid)` | MakeCylinder のソリッドで **False** を返す。使えない。殻ごとに確かめる |
| メッシュ blob（`smooth_shade` で鋭い辺の頂点が分かれている） | `process=False` では閉じていない判定。`process=True`（位置で頂点を併合）にすると STL の箱は閉じた判定・体積 6000.0。裏返した箱は -6000 |
| lil-gui 1280×800（初期状態） | `.lil-gui` のルートは x 1020–1265、y 0–497（「表示」と「視点」が開いている）。1 行は約 24px。HUD は x 12–480、y 717–788 |

---

## 1. 挙動

### 1.1 Backend: `GET /api/models/{id}/properties`

- 404: モデルがない。422: 図面（`fmt == "drawing"` またはメッシュ blob がない）、または B-rep の再読込で `BrepLoadError`。
- 応答。長さは mm、値は丸めずに返す。

```json
{
  "source": "brep" | "mesh",
  "units": "mm",
  "parts": [
    {"id": 0, "name": "plate", "closed": true, "volume": 90000.0, "area": 16800.0,
     "centerOfMass": [50.0, 30.0, 7.5], "reason": null}
  ],
  "total": {"volume": 116513.27, "area": 23257.70, "centerOfMass": [x, y, z],
            "closedParts": 4, "openParts": 0}
}
```

- `reason` は `"open"`（開いている）、`"no_faces"`（面がない）、`"degenerate"`（厚みがない）、`"winding"`（面の向きが不揃い。メッシュのみ）、`"failed"`（OCCT の例外）のいずれか、または null。`volume`/`centerOfMass` は `closed` のときだけ値を持つ。`area` は `no_faces` で 0.0、`failed` で null。
- `total` は閉じた部品だけを合計する（体積・面積・重心は体積で重み付け）。閉じた部品がなければ volume/area/centerOfMass は null。全部品が対象で、表示中かどうかはサーバには分からない。
- **B-rep の部品**（`PartMesh.part.shape`。ディスクキャッシュに当たったときは `_brep_meshes(entry)` で遅延して再読込する。計測と同じ経路）:
  - 面が 1 枚もない → `area 0.0`、`reason "no_faces"`。
  - `area` は `SurfaceProperties_s(shape, props, True)`。`SkipShared` を有効にすると、2 つの殻が共有する面は 1 回だけ数える。
  - 体積を持つ塊:
    - 各 SOLID: 殻がすべて `IsClosed_s` なら塊として数える。そうでなければ「開いている」。
    - ソリッドに属さない各 SHELL（`TopExp_Explorer(shape, SHELL, SOLID)`）: 閉じていれば塊、開いていれば「開いている」。STEP の shell-based surface model に閉じた殻が来る場合にも体積を出せる。
    - 殻に属さない FACE（`TopExp_Explorer(shape, FACE, SHELL).More()`）が 1 枚でもあれば「開いている」。
    - 部品内のばらばらの線・点は無視する（作図線とみなす）。
  - **判定は厳しめにする**: 部品のどこかが開いていれば、部品全体を `volume null`、`reason "open"` とする。体積が一部抜けた値は重量を黙って少なく見せるため、出さない。
  - 体積 = Σ|V_i|（ソリッドごとの `VolumeProperties_s`。中空は OCCT が殻の向きで処理する）。重心 = Σ|V_i|·c_i / Σ|V_i|。塊ごとに絶対値を取るので、裏返った塊が別の塊の体積を打ち消すことはない。
  - Σ|V| ≤ 1e-9 · diag³（diag は部品の Bnd_Box の対角線）なら `reason "degenerate"`。
  - 部品ごとに `try/except Exception`。OCCT の失敗は `reason "failed"` にし、ほかの部品は計算を続ける。
- **メッシュ形式**（STL/3MF/OBJ/PLY/OFF/GLB）: blob を部品ごとに読み戻し、`trimesh.Trimesh(positions.astype(float64), indices.astype(int64), process=True)` を作る。表示用に分けた頂点を位置で併合し直すため。`area = m.area` は常に出す。順に判定する。
  - `not m.is_watertight` → `open`
  - `not m.is_winding_consistent` → `winding`
  - |V| ≤ 1e-9·diag³ → `degenerate`
  - それ以外は `volume = abs(m.volume)`、`centerOfMass = m.center_mass`。中空の STL は内側の殻が裏向きで符号が付いており、正しく差し引かれる。
- **キャッシュ**: 結果は `entry.extra["properties"]` に置く。キャッシュに無い場合だけ計算する。計算中は `entry.lock` を持たない（再読込のときは `_brep_meshes` が自分でロックする）。こうすると、大きな GProp の計算中も計測要求が待たされない。同時に 2 件来れば、同じ純粋な結果を 2 回計算するだけで害はない。

### 1.2 Frontend

- **GUI フォルダ「体積・重量」**: 「肉厚」の後ろに追加し、初期状態は閉じる。中身は 2 つ。
  - `樹脂`: 選択肢 `['PMMA','PC','ABS','PP','PA66','POM','PS','その他']`。プリセットを選ぶと比重をその値（1.19 / 1.20 / 1.05 / 0.90 / 1.14 / 1.41 / 1.05）にし、比重欄の表示を更新する。「その他」は今の比重をそのまま残す。
  - `比重 (g/cm³)`: 数値欄。`.min(0.001).step(0.001)`。max は付けない。min と max の両方を付けると lil-gui がスライダーを出すため。step 0.001 なら、1.185 のような入力値が丸められない。入力した値が選択中の樹脂の比重と違えば、樹脂を「その他」にして `updateDisplay()` する。比重の値から別の樹脂を自動で選ぶことはしない。ABS と PS が同じ 1.05 で決められないため。
  - 樹脂と比重は localStorage のキー `cad-viewer:props`（`{resin, density}`）に保存する。読み書きは try/catch で囲む。読み込み時の検証: resin が一覧にあること、density が有限かつ正であること。resin がプリセットなら、そのプリセットの比重を使う。既定は PMMA / 1.19。
- **パネル `#props-panel`**（右下の積み重ね。§2.4）。中身は次のとおり。
  - 見出し行: 「体積・重量」と、右寄せの `PMMA 1.19 g/cm³`。その他のときは `比重 1.234 g/cm³`。
  - 状態表示: `計算中…` または `計算できない: <detail>`。
  - 部品表（モデルの部品が 2 つ以上のときだけ）: **表示中の**部品を部品 id 順に並べる。列は `部品 | 体積 cm³ | 表面積 cm² | 重量 g`。体積のない部品は、体積欄が `体積なし（閉じていない）`（理由により `面がない`／`厚みがない`／`面の向きが不揃い`／`計算できない`）、重量欄が `—`、表面積欄は値（`no_faces` なら `—`）。
  - 合計欄:
    - 部品が 2 つ以上のとき: 見出し `合計（表示中 V/N 部品）`。表示中の部品がなければ `表示中の部品なし`。対象は「表示中かつ体積がある」部品の集合 C。
    - 部品が 1 つのとき: 見出しなし。その部品自身の値を出す。開いていれば `体積なし（閉じていない）`、表面積、`—`。ツリーで隠されていれば `表示中の部品なし` とダッシュ。
    - 体積 `116.513 cm³（116,513 mm³）`、表面積 `234.58 cm²`、重量 `138.65 g`。C が空なら `—`。
  - 注記行（合っているものだけ ` ／ ` でつなぐ）: `体積なしの k 部品は合計に含めない`（k = 表示中 − 体積あり > 0 のとき）、`メッシュの三角形から計算（単位は mm とみなす）`（`source === 'mesh'` のとき）。
- **数値の書式**: `Intl.NumberFormat('ja-JP')`、小数の桁は固定。
  - cm³ = mm³/1000 を小数 3 桁
  - mm³ は整数。100 未満なら小数 2 桁
  - cm² = mm²/100 を小数 2 桁
  - g = (mm³/1000)·比重 を小数 2 桁
  - 比重は `toFixed(3)` から末尾の 0 を 1 つ削る（1.19 / 1.20 / 0.90 / 1.234）
- **更新のきっかけ**:
  - 3D モデルを読み込んだとき: 後片付けでパネルを隠し、`setModel` の後で `計算中…` にしてから取得する。
  - ツリーで部品の表示を切り替えたとき: `queueMicrotask` で描画を 1 回にまとめる。グループのチェックが子へ連鎖して `change` が何度も出ても、描画は 1 回で済む。
  - 樹脂・比重を変えたとき。
- **2D 図面**: パネルを隠し、取得もしない。古い応答は世代番号で捨てる（§2.3）。

### 1.3 既存機能との関係

| 機能 | 関係 |
|---|---|
| ターンテーブル／自由回転、自動回転、視点、全体表示 | なし。パネルはカメラに依存しない DOM の重ね表示。自動回転を一時停止させる「押されたポインタ」はキャンバスの `pointerdown` だけを見るので、パネルを押しても止まらない（正しい） |
| キーボード操作 | 比重欄は lil-gui の `<input type=text>` なので `isTextEntry` が true を返し、矢印・＋・− は欄に入る（lil-gui は ArrowUp/Down で値を step ずつ増減する）。視点は動かない。樹脂欄は `<select>` で、回転方式の選択欄と同じ扱い。キャプチャ段階のリスナーは変更しない |
| 計測／注記モード | パネルは `#viewport` の外の兄弟要素なので、パネルをクリックしてもピックされない。パネルの矩形の中ではドラッグしても回転しない（計測パネルと同じ）。パネルは `user-select: text` にし、数値を Excel に写せるようにする |
| 計測パネル | 同じ右下の積み重ねに入れ、計測パネルを上、体積パネルを下に置く。重ならない |
| 断面 | 見た目だけ。値は常に部品全体のもの（README に書く） |
| 肉厚 | 関係なし |
| モデルの再読込（同じファイルで同じ id になる場合も） | 世代番号を上げてパネルを隠し、取り直す。サーバ側のキャッシュに当たるので速い |
| 読み込み失敗 | 後片付けの前（アップロード時）なら、古いモデルと古いパネルをそのまま残す。後片付けの後なら、パネルは隠れたまま |
| モデルの LRU 追い出し | 404 になり、`計算できない: model not found` と出す |

---

## 2. ファイルごとの変更

### 2.1 Backend

**`backend/app/meshpack.py`**: `unpack_parts(blob: bytes) -> tuple[dict, list[dict]]` を追加する。`pack_parts`/`pack_trimesh` の逆で、各要素は `{"id", "name", "positions" (N,3) f32, "normals" (N,3) f32, "indices" (M,3) u32}`。`np.frombuffer` の読み取り専用ビューを返す。`get_thickness` の読み戻しを置き換え、出力は 1 バイトも変えない。

**`backend/app/properties.py`**（新規）。冒頭の docstring には「なぜ厳しく判定するか（部分的な体積は重量を黙って少なく見せる）」と「なぜメッシュは併合するか」を書く。

```python
OPEN, NO_FACES, DEGENERATE, WINDING, FAILED = "open", "no_faces", "degenerate", "winding", "failed"
_DEGENERATE_REL = 1e-9  # body volume <= this * bbox_diag**3 -> flat, not a solid

def _shapes(shape, kind, avoid=TopAbs_SHAPE) -> list[TopoDS_Shape]
def _volume(shape) -> tuple[float, tuple[float, float, float]]   # signed V, centroid
def _combine(bodies) -> tuple[float, list[float] | None]          # sum|V|, |V|-weighted centroid
def brep_part_properties(shape: TopoDS_Shape) -> dict             # closed/volume/area/centerOfMass/reason
def mesh_part_properties(positions, indices) -> dict
def _model(source: str, parts: list[dict]) -> dict                # adds units + total
def brep_properties(meshes: list[PartMesh]) -> dict               # [{"id": m.part.part_id, "name": m.part.name, **brep_part_properties(m.part.shape)}]
def mesh_properties(blob: bytes) -> dict                          # via meshpack.unpack_parts
```

返すのはすべて Python の float / list。NaN は出さない（体積が 0 なら重心は None）。

**`backend/app/main.py`**: `from . import cache, measure, properties` とし、`properties.brep_properties(...)` を属性経由で呼ぶ（テストで monkeypatch できるように）。

```python
@app.get("/api/models/{model_id}/properties")
def get_properties(model_id: str) -> dict:
    entry = store.get(model_id); 404 if None
    if entry.fmt == "drawing" or not entry.mesh_blob: 422 "properties require a 3D model (mesh or B-rep)"
    cached = entry.extra.get("properties"); if cached is not None: return cached
    if entry.fmt == "brep":
        try: meshes = _brep_meshes(entry)
        except BrepLoadError as e: raise HTTPException(422, str(e)) from e
        result = properties.brep_properties(meshes)
    else:
        result = properties.mesh_properties(entry.mesh_blob)
    entry.extra["properties"] = result   # comment: computed without entry.lock on purpose (see 1.1)
    return result
```

`get_thickness` は `meshpack.unpack_parts` を使うよう書き換える。

### 2.2 Frontend の型と取得（`api.ts`）

```ts
export type PropsReason = 'open' | 'no_faces' | 'degenerate' | 'winding' | 'failed'
export interface PartProperties { id: number; name: string; closed: boolean; volume: number | null
  area: number | null; centerOfMass: [number, number, number] | null; reason: PropsReason | null }
export interface ModelProperties { source: 'brep' | 'mesh'; units: 'mm'; parts: PartProperties[]
  total: { volume: number | null; area: number | null; centerOfMass: [number, number, number] | null
           closedParts: number; openParts: number } }
let _stallNextPropertiesMs = 0
export function __stallNextProperties(ms: number): void   // one-shot, like __stallNextMeasure
export async function fetchProperties(modelId: string): Promise<ModelProperties>  // throws Error(detail)
```

### 2.3 `frontend/src/properties.ts`（新規）と `viewer.ts`／`main.ts`

**`properties.ts`**:

```ts
export const RESIN_DENSITY: Record<string, number> = { PMMA: 1.19, PC: 1.2, ABS: 1.05, PP: 0.9, PA66: 1.14, POM: 1.41, PS: 1.05 }
export const RESIN_NAMES = Object.keys(RESIN_DENSITY)
export const OTHER_RESIN = 'その他'
export const REASON_TEXT: Record<PropsReason, string> = { open: '閉じていない', no_faces: '面がない',
  degenerate: '厚みがない', winding: '面の向きが不揃い', failed: '計算できない' }
export function fmtNum(x: number, digits: number): string        // Intl ja-JP, fixed digits (cached formatters)
export const massGrams = (mm3: number, density: number) => (mm3 / 1000) * density
export function fmtDensity(d: number): string
export interface PropsView { rows: PartProperties[] | null; title: string
  total: { volume: number | null; area: number | null; reason: PropsReason | null }; notes: string[] }
export function buildView(d: ModelProperties, isVisible: (id: number) => boolean): PropsView
export class PropertiesPanel {
  constructor(root: HTMLElement, isVisible: (id: number) => boolean, onLayout: () => void)
  showLoading(): void; setData(d: ModelProperties): void; showError(msg: string): void
  hide(): void                       // drop data + .hidden
  setDensity(density: number, resin: string): void
  refresh(): void                    // queueMicrotask-coalesced render
  fitHeight(maxPanelPx: number): void // wrap.style.maxHeight = max(maxPanel - (root.offsetHeight - wrap.offsetHeight), 44)
}
```

`buildView` の規則（§1.2 のとおり）:
- N = 部品数、V = `parts.filter(p => isVisible(p.id))`、C = `V.filter(p => p.volume !== null)`。
- N === 1 のとき: `rows = null`。その部品が表示中なら、その部品の値（体積、面積（`no_faces` なら null）、理由）。隠れていれば見出し `表示中の部品なし`。
- N > 1 のとき: `rows = V`。合計は Σ_C。見出し `合計（表示中 ${V.length}/${N} 部品）`。V が空なら `表示中の部品なし`。V.length > C.length なら注記を足す。
- メッシュの注記は `source === 'mesh'` で常に付ける。

DOM は constructor の中で一度だけ作る: head、status、`#props-parts-wrap > table#props-parts`（thead + tbody）、`#props-total`（`#props-total-title`、`dl` に `#props-total-volume` / `-area` / `-mass`）、`#props-note`。表の行は `tr[data-part-id]`、セルは `td.name`（`title` 属性に名前）/`.vol`/`.area`/`.mass`。値の無いセルには `.none` を付ける。**部品名はファイル由来なので、必ず `textContent` で入れる。`innerHTML` は使わない。** 描画のたびに最後に `onLayout()` を呼ぶ。

**`viewer.ts`**: `isPartVisible(partId: number): boolean { return this.partGroups.get(partId)?.visible ?? false }` を追加する。

**`main.ts`**:
1. HTML: `#measure-panel` と新しい `<div id="props-panel" class="hidden"></div>` を `<div id="corner-br">` で包む。順序は計測が先、体積が後。
2. `const propsPanel = new PropertiesPanel(propsEl, (id) => viewer.isPartVisible(id), fitCornerStack)`。
3. GUI（`propsPrefs` の読み込み・保存は `viewPrefs` と同じ形）:

```ts
const propsFolder = gui.addFolder('体積・重量'); propsFolder.close()
const resinCtl = propsFolder.add(propsPrefs, 'resin', [...RESIN_NAMES, OTHER_RESIN]).name('樹脂')
  .onChange((r: string) => { if (r !== OTHER_RESIN) { propsPrefs.density = RESIN_DENSITY[r]; densityCtl.updateDisplay() } applyDensity() })
const densityCtl = propsFolder.add(propsPrefs, 'density').min(0.001).step(0.001).name('比重 (g/cm³)')
  .onChange(() => { if (propsPrefs.resin !== OTHER_RESIN && propsPrefs.density !== RESIN_DENSITY[propsPrefs.resin]) {
      propsPrefs.resin = OTHER_RESIN; resinCtl.updateDisplay() } applyDensity() })
function applyDensity() { propsPanel.setDensity(propsPrefs.density, propsPrefs.resin); savePropsPrefs() }
applyDensity()  // initial
```

4. 取得（`updateThickness` と同じ世代番号の確認）:

```ts
async function updateProperties(modelId: string, gen: number): Promise<void> {
  propsPanel.showLoading()
  try { const p = await fetchProperties(modelId)
        if (gen !== loadGen || modelId !== currentModelId) return; propsPanel.setData(p) }
  catch (e) { if (gen !== loadGen || modelId !== currentModelId) return
              propsPanel.showError(e instanceof Error ? e.message : String(e)) }
}
```

5. `loadFile`:
   - 後片付け: `viewer.clearThicknessColors()` の隣で `propsPanel.hide()`。
   - 3D の経路: `sectionTool.setModelBBox(...)` の後、`getSidecar` を待つ前に `void updateProperties(meta.id, gen)`。待たないので読み込みは遅れない。
   - `renderTree` のコールバック: `(id, v) => { viewer.setPartVisible(id, v); propsPanel.refresh() }`。
6. テスト用フック: `testHooks.__cadStallProperties = (ms: number) => __stallNextProperties(ms)`。

### 2.4 配置（`style.css` と `main.ts` の `fitCornerStack`）

lil-gui は z-index 1001 の固定配置で右上にあり、フォルダを開くと下に伸びる（1280×800 の初期状態で y 497 まで、新しいフォルダを開くと約 570 まで）。右下のパネルと同じ列を使うので、高さを制限しないと GUI の下に潜る。

```css
#corner-br { position:absolute; right:12px; bottom:12px; display:flex; flex-direction:column;
  align-items:flex-end; gap:8px; pointer-events:none }
#corner-br > * { pointer-events:auto }
#measure-panel  /* drop position/right/bottom; keep the rest (max-height 40vh, overflow-y auto) */
#props-panel { min-width:220px; max-width:360px; color/background/border/radius/padding/font-size as #measure-panel;
  user-select:text }  /* + .hidden { display:none } */
#props-head (flex, space-between, 12px 600 accent #8fd8a8, letter-spacing .08em); #props-density (400, #9aa6b4)
#props-parts-wrap { overflow-y:auto; margin-bottom:6px }
#props-parts { border-collapse:collapse; width:100%; font-size:12px; font-variant-numeric:tabular-nums }
  th (sticky top, opaque bg, #7f8b99, right), td right nowrap padding-left 8px,
  td.name left max-width 120px ellipsis, td.none left 11px #9aa6b4 white-space normal
#props-total dl { display:grid; grid-template-columns:auto 1fr; gap:2px 12px }  dd right
#props-note { font-size:11px; color:#7f8b99; margin-top:4px }
```

```ts
// keep the bottom-right stack below the GUI column (fixed, z 1001, grows as folders open)
function fitCornerStack(): void {
  const guiBottom = gui.domElement.getBoundingClientRect().bottom
  const measure = measurePanel.classList.contains('hidden') ? 0 : measurePanel.getBoundingClientRect().height + 8
  propsPanel.fitHeight(window.innerHeight - 12 - (guiBottom + 8) - measure)
}
new ResizeObserver(fitCornerStack).observe(gui.domElement)
new ResizeObserver(fitCornerStack).observe(measurePanel)
window.addEventListener('resize', fitCornerStack)
```

監視するのは GUI のルートと計測パネル**だけ**にし、体積パネル自身は監視しない。`fitHeight` が書き換えるのは体積パネル内の表の枠だけなので、自分の変更で再び呼ばれる循環（「ResizeObserver loop」のエラーで、E2E の `errors` が赤になる）が起きない。表の枠は最小 44px（見出し＋1 行）で、それを下回る分はスクロールする。

---

## 3. 境界条件

| 条件 | 扱い |
|---|---|
| 部品が裏返っている（体積が負） | 塊ごとに `abs`。重心は正しいまま |
| 中空ソリッド | OCCT が殻の向きで差し引く。テストあり |
| 閉じた殻がソリッドに入っていない（STEP の surface model、縫えたが MakeSolid に失敗） | 体積を出す |
| 閉じた殻だが体積が約 0 | `degenerate` |
| ソリッド＋ばらばらの面、または殻に隙間のあるソリッド | 部品全体を `open` |
| 線・点だけの部品（IGES の「曲線（N 本）」） | `no_faces`、面積 0、表では `—` |
| 1 部品に複数ソリッド、アセンブリで同じ部品を複数配置 | 合計する（配置ごとに 1 回） |
| 部品どうしが重なっている | 重なりを差し引かずに足す（README に書く） |
| メッシュ: 非多様体（辺を 3 枚以上の面が共有）、穴 | `open` |
| メッシュ: 向きの混在 | `winding` |
| メッシュ: 裏返し | `abs` |
| メッシュ: 別々の塊で向きが逆のもの | 中空と見分けられない。符号付きの合計を使う（記録しておく） |
| 単位 | B-rep は OCCT が読込時に mm へ換算済み。メッシュは mm とみなし、パネルに注記する（GLB/GLTF は本来 m 単位） |
| float32 の blob の精度 | 相対誤差は約 1e-7。STL はもともと float32 |
| OCCT の例外 | その部品だけ `failed`。B-rep の再読込に失敗したら 422 |
| 同時に来た要求 | 重複計算するだけで害はない。B-rep の再読込は `entry.lock` で直列化される |
| 古い応答（別のモデルや図面へ切り替えた後） | `gen`/`currentModelId` で捨てる |
| 比重の入力 | NaN は lil-gui が無視する。≤ 0 は min 0.001 で止める。入力中の "1." は 1 として扱い、樹脂は「その他」になる |
| localStorage が使えない・壊れている | 既定値（PMMA）。書き込み失敗は黙って無視 |
| 部品名に `<script>` などが含まれる | `textContent` で入れるので害はない |
| 部品が数百ある | 描画は 1 回にまとめる。表の枠がスクロールし、合計は見えたまま |
| 1280×800 で GUI フォルダを開き、計測項目もある | 表の枠が最小高さまで縮む。それでも足りなければ GUI の下に一部潜る（極端な場合として許容） |

---

## 4. テスト計画

### 4.1 Backend: `backend/tests/test_properties.py`

期待値はすべて形状の作り方から求め、計算対象のコードから取らない。許容は相対 1e-9（メッシュの円柱だけ 1e-6）。

**純粋関数**（OCP の形状を直接作る）:

| テスト | 期待値 | 捕まえる変異 |
|---|---|---|
| 箱 10×20×30（`gp_Pnt(1,2,3)` に置く） | V 6000、A 2200、重心 (6,12,18)、closed | 体積に面積を返す、重心の取り違え |
| 円柱 r4 h25 | V π·16·25、A 232π、重心 (0,0,12.5) | 積分の近似が粗い |
| 裏返した箱 | V +6000、重心 (6,12,18) | `abs` の抜け |
| 中空ソリッド（Cut） | V 875000、A 75000 | 外側の殻しか見ない |
| ソリッドに入っていない閉じた殻（箱の殻を取り出す） | V 6000、closed | 閉じた殻を扱わない |
| 開いた殻（面 5 枚を縫う。外すのは bbox の zmin が 30 の天面） | open、A 2000 | 開いた殻に体積を出す |
| ばらばらの面 1 枚 | open | — |
| 開いた殻から作ったソリッド（`BRepBuilderAPI_MakeSolid(open_shell)`） | open | `IsClosed(solid)` を頼る、殻ごとの確認の抜け |
| ソリッド＋ばらばらの面の Compound | open | 厳しい判定の抜け |
| 辺の Compound | `no_faces`、A 0 | — |
| 箱 2 つの Compound（1000 と 8000、離して置く） | V 9000、重心 = 重み付き平均 | 重み付けの抜け |
| メッシュ（`pack_trimesh(load_mesh(stl))` → `mesh_properties`）: 箱 | 6000 | 頂点の併合の抜け |
| メッシュ: 開いた箱 | open、A 1600 | — |
| メッシュ: 裏返した箱 | +6000 | — |
| メッシュ: `trimesh.creation.cylinder(4, 25, sections=32)` | 0.5·32·16·sin(2π/32)·25（相対 1e-6） | — |

**API**:

| テスト | 内容 | 捕まえる変異 |
|---|---|---|
| mini_mold | 4 部品を名前で照合。体積・面積・重心を個別に確認。合計 V 116513.27…、A 23257.70…、重心 = Σ V_i c_i / Σ V_i。`source "brep"`、`units "mm"` | — |
| ディスクキャッシュに当たった再読込 | アップロード → DELETE → 再アップロード（`cached` が True、`store.get(id).brep is None`）→ GET で同じ値 → その後 `brep is not None` かつ `"raw"` が `extra` にない | 再読込の経路が壊れる |
| エントリごとのキャッシュ | DELETE → 再アップロードで新しいエントリを作り、`properties.brep_properties` を数える関数で monkeypatch する。GET 2 回で呼び出しは 1 回 | キャッシュを使わない |
| STL | `source "mesh"`、V 6000 | — |
| DXF（`testdata/plate_drawing.dxf`） | 422 | 図面で 422 にならない |
| 存在しない id | 404 | — |
| IGES（`IGESControl_Writer("MM", 0)` で面を 1 枚ずつ書き、線 2 本を足す。`test_sewing` と同じやり方でローカルに作る） | 閉じた箱 → 「ソリッド」部品の V 6000 と「曲線（2 本）」の `no_faces`。天面を外した箱 → 「サーフェス」の open、A 2000。合計の `openParts` も確認 | — |

store は使い回され、同じ内容のアップロードは同じエントリになるので、数える系のテストは必ず DELETE してから再アップロードする。

### 4.2 E2E: `e2e/test_properties.py`

ビューポートは 1280×900（GUI フォルダと計測パネルを開いても、重ならないことを確かめられる高さ）。`CAD_VIEWER_URL` は 5193 に向け、プロキシ先は backend 8018。

**期待値**:
- 部品の体積 V: plate 100·60·15、core_pin π·4²·25、cavity_block 40·30·20。
- 面積 A: 2(ab+ac+bc)、および 2π·4·25+2π·4²。
- 樹脂ごとの比重の表をテスト内に持つ。
- STL 素材: テスト内で ASCII STL を書く（箱 10×20×30。四角形の頂点は外から見て反時計回り。天面ありと天面なしの 2 本）。`tempfile.mkdtemp()` に置き、最後に削除する。

**数値の確認**:
- 正規表現で桁数を確かめる: 体積 `([\d,]+\.\d{3}) cm³（([\d,]+) mm³）`、`[\d,]+\.\d{2} cm²`、`[\d,]+\.\d{2} g`。
- そのうえで |表示値 − 期待値| ≤ 0.5·10⁻ᵈ + 1e-9 を確かめる。

**手順**（最初に `localStorage.removeItem('cad-viewer:props')`、最後にも消す。`errors` は空であること）:

1. 初期ページで `#props-panel` が隠れている。GUI フォルダ「体積・重量」が閉じている（lil-gui の閉じた状態を示す class）。
2. mini_mold を読み込み、合計体積に数字が出るまで待つ。
   - 見出しが `PMMA 1.19 g/cm³`。
   - 4 行。名前ごとの (体積, 面積, 重量 @1.19) を期待値と照合する（core_pin は 2 行）。
   - 合計: 116.513 cm³（116,513 mm³）、234.58 cm²、138.65 g。見出し `合計（表示中 4/4 部品）`。注記なし。
3. 表示切り替え:
   - ツリーで `plate` を外す → 3 行、合計 = 2·V_pin + V_block、`3/4`。
   - 続けて `core_pin` を 1 つ外す → 2 行、`2/4`。
   - ルート `mini_mold` を外す → 表が隠れ、`表示中の部品なし`、合計は `—`。
   - ルートを戻す → 4/4 と最初の合計に戻る。
4. 樹脂:
   - フォルダの見出しをクリックして開く。
   - `樹脂` で PC を選ぶ → 比重欄が 1.2、見出しが `PC 1.20`、重量が V·1.20 になる。PP でも同様（0.90）。
   - `比重` 欄に 1.234 を入れて Enter → `樹脂` 欄の表示が「その他」、重量 = V·1.234。
   - 「その他」をはっきり選び直しても 1.234 のまま。
   - キーボード: 比重欄をクリックし、ArrowLeft/ArrowRight を押す → `__cadView().position` が変わらない（期待値はカメラの状態）。
5. 配置（フォルダを開いた状態と閉じた状態の両方）:
   - 計測モードで計測を 1 件作る（`test_measure` と同じ 2 点。`__cadProject` で座標を求める）。
   - 矩形 `#props-panel`、`#measure-panel`、`#hud`、`.lil-gui`（GUI のルート）のどの 2 つも重ならない。
   - パネルの下端 ≤ innerHeight − 12 + 0.5。
   - `#props-total` の矩形がパネルの矩形の中に収まっている。
   - 計測モードのまま体積パネルの中央をクリックしても、計測一覧の件数と HUD が変わらない。
   - 最後に × で計測を削除する（サイドカーを元に戻すため）。
6. 断面を有効にする → 合計が変わらない。無効に戻す。
7. 再読込（`page.goto` → mini_mold）:
   - 「その他」と 1.234 を覚えている（select の値、input の値、`比重 1.234` という見出し）。
   - 重量が 1.234 で計算されている。
   - PMMA に戻す。
8. メッシュ:
   - 閉じた箱の STL → 表が隠れ、見出しなし。6.000 cm³（6,000 mm³）、22.00 cm²、7.14 g（@1.19）。注記に `mm とみなす` を含む。
   - 天面なしの STL → 体積が `体積なし（閉じていない）`、20.00 cm²、重量 `—`。
9. 図面:
   - `plate_drawing.dxf` を読み込む → パネルが隠れる。
   - 読み込み中に `/properties` への要求が 0 件（`page.on('request')` で数える）。
10. 古い応答（新しいページで）:
    - `__cadStallProperties(2000)` → mini_mold を読み込む → `計算中…` が見える。
    - すぐに DXF を読み込み、`2D図面` を待つ → 2500ms 待つ → パネルが隠れたまま。
11. 体積のない部品が混ざる場合（新しいページで）:
    - `page.route('**/api/models/*/properties')` で `route.fetch()` の応答を受け、最初の core_pin を `volume null, closed false, reason "open", centerOfMass null` に書き換えて `route.fulfill(json=...)` で返す。
    - その行に `体積なし（閉じていない）`、面積 7.29、重量 `—`。
    - 合計 = V_plate + V_pin + V_block → 115.257 cm³。面積 = 16800 + A_pin + 5200 → 227.29 cm²。
    - 見出し `4/4`、注記 `体積なしの 1 部品は合計に含めない`。

**捕まえる変異**（手順の番号）:

| 変異 | 捕まえる手順 |
|---|---|
| backend が体積に面積を返す、または円柱の積分が誤り | 2 |
| cm³ を /100 で換算、または cm² を /1000 で換算 | 2, 8 |
| 重量が比重を無視する（1.0 のまま） | 2 |
| 合計に隠れた部品を含める、または表示切り替えで再描画しない | 3 |
| microtask でまとめる処理が壊れ、連鎖した切り替えが反映されない | 3 |
| プリセットを選んでも比重が変わらない | 4 |
| 入力しても「その他」に切り替わらない | 4 |
| 比重欄で矢印キーが視点を動かす | 4 |
| パネルが GUI・HUD・計測パネルと重なる、または `fitCornerStack` がない | 5 |
| パネルのクリックでピックされる | 5 |
| 断面で値が変わる | 6 |
| 設定を保存・読み込みしない | 7 |
| メッシュの頂点を併合しない（閉じた STL が「体積なし」になる） | 8 |
| メッシュの注記がない | 8 |
| 開いたメッシュに体積を出す | 8 |
| 2D 図面でパネルを出す、または図面で取得する | 9 |
| 世代番号の確認がない | 10 |
| null の体積を 0 として合計に含める、または注記がない、または面積に体積なしの部品を含める | 11 |

### 4.3 既存の確認

- `tsc --noEmit`、`npm run build`、backend の pytest 全件（縫い合わせのテストを含む）。
- **既存 E2E 全件**を 5193/8018 で流す。3D モデルでは常に右下に新しいパネルが出て、キャンバスの一部を覆うため。
  - 確認済みの座標: `test_view_controls` の (640,760)、(400,600)→(900,300)、床の格子を数える左上の範囲。`test_measure` で (90,10,15) を投影した点 ≈ (737,560)。いずれもパネルより左（x ≥ 約 908）なので当たらない。
  - 計測パネルを積み重ねの中へ移したので、計測一覧を使うテスト（`#measure-list li`）も流して確かめる。
- 変異テストは、作業コピーを backend 8018 に向けて行う（backend 側を変異させるなら 8019）。

---

## 5. ドキュメント

**README.md** に「## 体積・重量」節を追加する（短く）。
- 右下のパネルに、表示中の部品の体積・表面積・重量と、その合計を出す。ツリーで隠した部品は合計から外れる。
- 重量 = cm³ × 比重。樹脂のプリセットと「その他」がある。樹脂と比重はブラウザに記憶する。
- STEP/IGES は OCCT で B-rep から厳密に計算する（表示用メッシュの粗さに左右されない）。メッシュ形式は三角形から計算し、mm とみなす。
- 閉じていない部品・線だけの部品は「体積なし」とし、合計に含めない。
- 重なった部品は差し引かずに足す。断面は見た目だけ。
- ショット重量の目安にするなら、ランナー・スプルーの分を別に足すこと。
- API: `GET /api/models/{id}/properties`（mm³・mm²・重心）。

**e2e/README.md** の実行一覧に `python3 e2e/test_properties.py` を追加し、`/properties` を持つ backend が要ることを書く。テスト用フックの説明に `__cadStallProperties` を足す。
