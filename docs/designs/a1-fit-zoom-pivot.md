> **A1（issue #8） の設計の下書き（2026-10-08、手元のセッションで作成）。**
> 実装（クラウドのセッション）で今のコードと照らし、次の点を直してから作った。本文は下書きのまま残す。
> - 本文の `e2e/test_navigation.py` は、CI の 1 本あたりの打ち切りを超えたため、`test_nav_fit.py`・`test_nav_wheel.py`・`test_nav_pivot.py` の 3 本（共通部品は `nav_common.py`）に分けた。
> - §2.6 の `feat/iges-sewing` との合流は不要（#9 で `modelBBox()` は master に入っている）。
> - ダブルクリックの「ドラッグの除外」は、押した点と離した点の距離では足りない。§4.1 C5 のとおり
>   40 px 動かして 1 px の所へ戻すドラッグは 1 px と測られ、クリックと見なされる。押している間に
>   押した点から最も離れた距離（`pointermove` で取る）で判定する。C5 はこの抜けを捕まえる。
> - C7（自動回転中のダブルクリック）は、回っている間にカーソルの下の点が動くので、事前に `__cadPick` した点とは
>   一致しない。中心が板の上面（z = 15）の SURFACE の近くに移り、そのまま中心で回ることを確かめる形にした。
> - §4.2 の床の格子の検査は、近くの床の 50 mm の格子線が細い範囲にかからなかった（0 画素）。測る前に F で
>   全体表示し直してから − を 3 回押す（毎回同じ視点になる）。
> - E2E は backend の venv の Python で回す（CLAUDE.md）。ポート・作業ツリーのパスは手元のもので、使わない。

# A1 design: 全体表示 (fit), zoom toward the cursor, double-click to set the rotation center

## 0. What I checked before writing this
I ran these probes against the worktree at `http://127.0.0.1:5191`. I started Vite on that port and left it running.
- **Wheel interception works for both controls.** A `wheel` listener on `#viewport` with `{capture: true, passive: false}` that calls `preventDefault()` and `stopPropagation()` stops both OrbitControls and TrackballControls from zooming. The camera distance stayed the same: turntable moved by 7e-13, which is OrbitControls' own per-frame rounding, and free mode did not move at all. With the listener's blocking switched off, both controls zoom as usual.
- **Double-click reaches the viewport.** `dblclick` arrives at `#viewport` with target `CANVAS`, `button === 0` and `detail === 2`, even though the controls call `setPointerCapture`.
- **Cursor coordinates are whole pixels.** Chrome rounds `WheelEvent.clientX/Y` to integers (640.4 becomes 640), so the tests must round cursor positions before using them.
- **Canvas pixels can be read reliably.** Calling `canvas.toDataURL()` inside `requestAnimationFrame` returns the frame that was just drawn. This gives a pixel check that does not include the DOM panels.
- **Panel positions at 1280×800 with mini_mold:**
  - lil-gui panel: x 1020–1265, y 0–497.
  - `#tree-panel`: x 12–192, y 12–161.
  - `#hud`: x 12–529, y 717–788.
- **Simulation of the fit in Python, using the same math as below.** "Fill" means how much of the canvas width or height the model's box takes up on screen.

| Model, view | Today | Centred on the box centre only | Closed form, no centring step | This design |
|---|---|---|---|---|
| Runner block 298×27.5×4.5, iso | 33% fill | margins L355 / R77 px | vertical margins T107 / B271 px | 88% width, margins 77/77 and 142/142 px |
| mini_mold, iso | 50% × 62% | — | — | 79% × 88%, margins equal on both axes |

- **Problem found in `test_view_controls.py`.** Its fixed "bare floor" patch (2–27% W, 22–34% H) would be about 14% covered by the plate at the new fit, so the grid-off pixel check would fail. Section 4.2 fixes it.
- **The other existing tests are safe.** All world points they click (for example (50,30,35) → (575,133) and (90,10,15) → (723,476)) still land in the canvas, clear of the panels.

## 1. Behaviour

### 1.1 全体表示 (fit)
- **Same entry for all triggers.** The 全体表示 button, `F`/`f` and `Home` all call `actions.fit()`. In 3D this is `viewer.fitToView()`; in 2D it is `drawing2d.fit()`, so the keys also work on drawings.
- **The view direction does not change.** The camera's forward direction and its roll (`camera.up`) stay the same in both rotate modes. Only the camera position, the target, near and far change.
- **Loading a model uses the default view.** A new model is shown from direction (1,−1,0.7), seen from target to camera, with Z up in both modes, and is framed the same way. This replaces today's `fitToView()` call inside `setModel()`.
- **What is framed.** The 8 corners of `modelBBox()`: bodies only, visible parts only. This is the same as the `feat/iges-sewing` version (see 2.6).
- **How tight.** The limiting dimension fills exactly `FIT_FILL = 0.88` of the viewport: equal margins on both sides, and the aspect ratio and real view direction are used. The other dimension is centred with equal margins.
- **Near/far planes.** These are recomputed on every fit. `near = r/500`, `far = max(200·r, 2·(dist + r))`, where `r` is half the diagonal of the framed box. This keeps today's 1e5 depth ratio but makes it relative to what is framed.
- **Grid.** Built once in `setModel()` from the loaded model's box (same size formula as today), not on every fit. Hiding parts and pressing F does not move the floor.
- **Inertia and the pivot animation.** Fit stops any drag "coast" (`stopInertia()`) and finishes a running pivot animation first. Auto-rotate keeps going.

### 1.2 Mouse wheel zoom (both rotate modes, all モード)
- **One capture-phase listener for both modes.** It is on `#viewport`, so neither controls object sees wheel events any more.
- **The zoom point.** It is the first visible surface point under the cursor. "Visible" means a visible part and not on the clipped side of a section, the same rule as picking but without snapping. If nothing is under the cursor, it is the point under the cursor on the plane through the target, perpendicular to the view direction.
- **How the camera moves.** Camera and target are both scaled about the zoom point P by the same factor s: `C' = P + s(C−P)`, `T' = P + s(T−P)`. Then `T'−C' = s(T−C)`, so the direction and roll are unchanged, P stays on exactly the same pixel, and the orbit target is pulled toward what you zoomed into. Each step is applied at once.
- **Step size.** `s = 0.9^(−d/100)`. `d` is `deltaY`, converted from lines (×16) or pages (×100), multiplied by 10 when `ctrlKey` is held (trackpad pinch), and clamped to ±300 per event. One Chrome notch (100) gives 0.9, the same as the `+` key.
- **The camera cannot pass the point.** The scaling never reaches P, and it is clamped so that `|C'−P| ≥ 4·near`. If that limit is already reached, the step does nothing. Zooming out is clamped so that `|C'−T'| ≤ far/4`.
- **What still zooms toward the target, unchanged:** middle-button drag (both controls), touch pinch, and the `+`/`−` keys. `+`/`−` gets an extra zoom-out clamp at `far/4`.
- **No effect on other tools.** The wheel changes only the camera, so measure, annotation, section and auto-rotate are untouched. In 2D, `#viewport` is hidden, so `drawing2d` keeps its own wheel handler.

### 1.3 Double-click to set the rotation center
- **When it works.** Only when モード is なし, only for the left button, and only if both clicks of the double-click moved 5 px or less between press and release. The movement check stops a drag ending near its start from turning into a pivot. In 計測 and 注記 modes the two clicks stay ordinary picks.
- **Where it picks.** The same visible-surface rule as the wheel, through `picker.surfacePoint`. On empty space nothing happens: no marker and no camera change.
- **The animation.**
  - It lasts `PIVOT_MS = 250` with a smoothstep ease.
  - The target moves from T0 to P. The camera moves from C0 to `C1 = P − f·d`, where `d = max((P−C0)·f, 4·near)` is P's depth.
  - So the camera only slides parallel to the screen: no turn, no zoom, and P's apparent size is unchanged.
  - Every in-between pose looks along f, because `lerp(T) − lerp(C) = f·lerp(d0, d)`.
- **The marker.** A ring is placed at P (a `CSS2DObject`, class `pivot-marker`, always drawn on top). It fades by opacity and is removed after `PIVOT_MARKER_MS = 1000`. A new double-click replaces it, and `clearModel` removes it.
- **Interruptions.**
  - Any pointerdown on the canvas, the wheel, arrow keys, `+`/`−`, presets, fit, or switching rotate mode first **finishes** the animation: it jumps to the end pose so the new center is kept. Then that action runs.
  - A second double-click starts again from the current in-between pose, with no jump.
  - Loading a model or `clearModel` **drops** the animation.
  - Auto-rotate pauses while the animation runs.
- **Both modes.** The new target is written into both `controls.target` and `trackball.target`, so later drags orbit around P in either mode.

### 1.4 Keys and hint text
- `F`, `f` and `Home` are checked in `onNavigationKey` **before** the `is2D` early return, and after the text-entry and modifier checks. They are ignored in the note text box, lil-gui text inputs and selects, and with Ctrl/Meta/Alt. `preventDefault()` is called, so `Home` does not scroll.
- `#hud-keys` becomes two lines:
  - `左ドラッグ・矢印キー: 回転　右ドラッグ・Shift+矢印: 移動　ホイール（カーソルの位置へ）・＋／−: 拡大縮小`
  - `ダブルクリック: そこを回転の中心に　F・Home: 全体表示`

### 1.5 How the new behaviour meets existing features
| Feature | What happens |
|---|---|
| Turntable (OrbitControls, damping on) | Wheel and pivot change position and target directly. `update()` re-reads the offset every frame, and a running coast continues around the new target. |
| Free rotation (TrackballControls) | Same. Its own wheel zoom is never reached. Roll is kept by fit, zoom and pivot. |
| Presets | Unchanged: they keep the target and distance. After a tight fit, a preset can crop a long part; press F. This is deliberate, because presets keep their existing behaviour. Possible follow-up: "preset + fit". |
| Arrow keys, Shift+arrow, `+`/`−` | Unchanged, apart from finishing the animation first and the `far/4` clamp on `−`. After a double-click they rotate around P and zoom toward P. |
| Auto-rotate | Paused during the pivot animation, then spins around the new target. Wheel and fit work while spinning. |
| 計測 / 注記 | Wheel works in every mode; double-click is ignored. The pointerup click-pick logic is unchanged (see 2.3). |
| Section | The zoom point and pivot ignore clipped hits (`firstVisibleHit`). Fit frames the whole visible bodies, not the half that remains. |
| Thickness heatmap, sidecars | Not touched. |
| 2D drawing | F, Home and the button fit the drawing. The 3D wheel and double-click are not active (viewport hidden). The resize guard (2.1) keeps `camera.aspect` valid while hidden. |
| Model reload | Default iso direction, Z up, framed. The animation is dropped and the marker removed. |

## 2. Code changes

### 2.1 `frontend/src/viewer.ts`

**New constants**
```ts
/** share of the limiting viewport dimension a fit fills; the rest is margin */
const FIT_FILL = 0.88
/** direction (target -> camera) a freshly loaded model is seen from */
const LOAD_VIEW_DIR = new THREE.Vector3(1, -1, 0.7).normalize()
/** near = framed radius / NEAR_DIV, far = radius * FAR_MUL: the same 1e5 depth range as before, relative to the model */
const NEAR_DIV = 500
const FAR_MUL = 200
/** the wheel stops this many near-plane distances short of the point it zooms to */
const MIN_ZOOM_NEARS = 4
/** zooming out stops at this share of the far plane (camera to target) */
const MAX_ZOOM_FAR = 0.25
const PIVOT_MS = 250
const PIVOT_MARKER_MS = 1000
```

**`modelBBox()`**: copy it word for word from `feat/iges-sewing`, including the doc comment, so the later merge sees the same change on both sides.
```ts
  /**
   * Bounds used to frame the model. Bodies only, when there are any: loose
   * curves in a file are often construction lines (e.g. coordinate axes) far
   * larger than the part, and framing them would shrink the part to a speck.
   */
  modelBBox(): THREE.Box3 {
    const box = new THREE.Box3()
    for (const [id, mesh] of this.partMeshes) {
      if (mesh.geometry.index?.count && this.partGroups.get(id)?.visible !== false) {
        box.expandByObject(mesh)
      }
    }
    return box.isEmpty() ? new THREE.Box3().setFromObject(this.modelGroup) : box
  }
```

**`setModel(model)`**: `clearModel()`, then `addPart` for each part, then `this.buildGrid(this.modelBBox())`, then `this.resetView()`. `buildGrid(box)` is today's grid block moved out of `fitToView` unchanged. It returns early if the box is empty.

**Fit methods**
```ts
  /** Zoom to fit the visible bodies, keeping the current view direction and roll. */
  fitToView(): void {
    const box = this.modelBBox()
    if (box.isEmpty()) return
    this.finishViewAnim()
    this.stopInertia()
    const forward = this.target.clone().sub(this.camera.position)
    if (forward.lengthSq() < 1e-20) forward.copy(LOAD_VIEW_DIR).negate()
    this.frameBox(box, forward.normalize())
  }

  /** View for a freshly loaded model: default oblique direction, Z up. */
  private resetView(): void {
    this.viewAnim = null
    this.stopInertia()
    this.camera.up.copy(WORLD_UP)
    const box = this.modelBBox()
    if (!box.isEmpty()) this.frameBox(box, LOAD_VIEW_DIR.clone().negate())
  }
```

`frameBox(box, forward)` does the following.

Setup:
- Screen axes match three's `lookAt`: `right = normalize(forward × camera.up)`. If `|forward × up| < 1e-12`, use any vector perpendicular to forward. Then `up = right × forward`.
- `center = box centre`; `r = |size| / 2`. If `r < 1e-9`, expand the box by 0.5 so the model is framed as a 1-unit cube, and recompute r.
- For each of the 8 corners q (minus the centre): `x = q·right`, `y = q·up`, `z = q·forward`.
- `tanV = tan(fov/2)`, `kV = FIT_FILL·tanV`, `kH = kV·camera.aspect`.

The math:
- Each side of the shrunken frustum is a plane through the camera. With `C = center + a·right + b·up + e·forward` (e < 0 means the camera is behind the centre), the right-side condition `X ≤ kH·Z` for every corner becomes `a − kH·e ≥ mR`, where `mR = max(x − kH·z)`. In the same way, `mL = max(−x − kH·z)`, `mT = max(y − kV·z)`, `mB = max(−y − kV·z)`.
- Making both planes of a pair touch the box gives:
  - `eH = −(mR + mL) / (2·kH)`
  - `eV = −(mT + mB) / (2·kV)`
  - `e = min(eH, eV)`: the axis that needs the camera further back is the limiting one. Its two planes touch the box, so its margins are equal and it fills exactly 0.88.
- `near = r / NEAR_DIV`. Then `e = min(e, min(z) − MIN_ZOOM_NEARS·near)`. This guard keeps the nearest corner in front of the near plane; it never applies to a real box.
- Perspective draws the near end larger. So instead of the closed-form a and b, use `a = centredOffset(xs, zs, e)` and `b = centredOffset(ys, zs, e)`. Lateral position does not change the depths, so the limiting axis stays exact and the other axis gets equal margins. Re-centring keeps the fit inside 0.88, because the new extreme lies between the two old ones.

Result:
- `target = center + a·right + b·up`; `camera.position = target + e·forward`.
- `camera.near = near`; `camera.far = max(r·FAR_MUL, 2·(−e + r))`; `updateProjectionMatrix()`; `setTarget(target)`.
- `camera.up` is not touched. Only `resetView` sets it.

```ts
/**
 * Lateral offset o that leaves equal margins on both sides: the largest and
 * smallest of (c - o) / (z - e) cancel. Each term falls as o grows, so the
 * sum is monotonic and bisection is exact enough after 60 steps.
 */
function centredOffset(cs: number[], zs: number[], e: number): number {
  let lo = Math.min(...cs)
  let hi = Math.max(...cs)
  for (let i = 0; i < 60; i++) {
    const o = (lo + hi) / 2
    let max = -Infinity
    let min = Infinity
    for (let k = 0; k < cs.length; k++) {
      const r = (cs[k] - o) / (zs[k] - e)
      if (r > max) max = r
      if (r < min) min = r
    }
    if (max + min > 0) lo = o
    else hi = o
  }
  return (lo + hi) / 2
}
```

**Zoom toward a point**
```ts
  /**
   * Zoom about `anchor` (the surface point under the cursor) or, over empty
   * space, the point under the cursor on the plane through the target square
   * to the view. Camera and target both scale about that point, so the view
   * direction is unchanged and the point stays under the cursor. scale < 1 zooms in.
   */
  zoomAt(ndc: THREE.Vector2, scale: number, anchor: THREE.Vector3 | null): void {
    if (!(scale > 0) || scale === 1) return
    this.finishViewAnim()
    this.camera.updateMatrixWorld()
    const p = anchor ?? this.targetPlanePoint(ndc)
    const cam = this.camera.position
    const target = this.target.clone()
    let s = scale
    if (s < 1) s = Math.min(1, Math.max(s, (this.camera.near * MIN_ZOOM_NEARS) / cam.distanceTo(p)))
    else s = Math.max(1, Math.min(s, (this.camera.far * MAX_ZOOM_FAR) / cam.distanceTo(target)))
    if (s === 1) return
    cam.sub(p).multiplyScalar(s).add(p)
    target.sub(p).multiplyScalar(s).add(p)
    this.setTarget(target) // both schemes' targets + lookAt + update
  }

  private targetPlanePoint(ndc: THREE.Vector2): THREE.Vector3 {
    this.raycaster.setFromCamera(ndc, this.camera) // new private Raycaster field
    const forward = this.target.clone().sub(this.camera.position).normalize()
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(forward, this.target)
    return this.raycaster.ray.intersectPlane(plane, new THREE.Vector3()) ?? this.target.clone()
  }
```
In `zoom(factor)`, the keyboard zoom: call `finishViewAnim()` first and add the maximum `this.camera.far * MAX_ZOOM_FAR`. The existing minimum `near*2` stays.

**Pivot animation and marker**
```ts
  private viewAnim: { from: THREE.Vector3; to: THREE.Vector3; fromTarget: THREE.Vector3; toTarget: THREE.Vector3; start: number } | null = null
  private pivotMarker: CSS2DObject | null = null
  private pivotMarkerTimer: ReturnType<typeof setTimeout> | undefined

  /** Make `point` the rotation centre: slide the view sideways (no turn, no zoom) until it sits mid-screen. */
  orbitAround(point: THREE.Vector3): void {
    this.viewAnim = null // a second double-click starts from wherever the first one got to
    this.stopInertia()
    const from = this.camera.position.clone()
    const fromTarget = this.target.clone()
    const forward = fromTarget.clone().sub(from).normalize()
    const depth = Math.max(point.clone().sub(from).dot(forward), this.camera.near * MIN_ZOOM_NEARS)
    this.viewAnim = { from, to: point.clone().addScaledVector(forward, -depth), fromTarget, toTarget: point.clone(), start: performance.now() }
    this.showPivotMarker(point)
  }

  private stepViewAnim(now: number): void {
    const a = this.viewAnim!
    const t = THREE.MathUtils.clamp((now - a.start) / PIVOT_MS, 0, 1)
    const k = t * t * (3 - 2 * t)
    this.camera.position.lerpVectors(a.from, a.to, k)
    const target = new THREE.Vector3().lerpVectors(a.fromTarget, a.toTarget, k)
    this.controls.target.copy(target)
    this.trackball.target.copy(target)
    this.camera.lookAt(target) // the loop's controls.update() follows
    if (t >= 1) this.viewAnim = null
  }

  /** Jump a running pivot animation to its end, so whatever interrupts it orbits the new centre. */
  private finishViewAnim(): void {
    const a = this.viewAnim
    if (!a) return
    this.viewAnim = null
    this.camera.position.copy(a.to)
    this.setTarget(a.toTarget)
  }
```
- `showPivotMarker(at)`: call `removePivotMarker()`, then `this.makeLabel('', at, 'pivot-marker')`, add it to `this.scene` (not `overlay`, which belongs to the measure tool), and set a `setTimeout(removePivotMarker, PIVOT_MARKER_MS)`.
- `removePivotMarker()`: clear the timer, `scene.remove(marker)`, `marker.element.remove()`, set the field to null.

**Other edits in `viewer.ts`**
- **Animation loop:**
  ```ts
  if (this.viewAnim) this.stepViewAnim(now)
  else if (this.autoRotate && this.heldPointers.size === 0 && dt > 0) this.rotateView(...)
  ```
  then `activeControls().update()` as today.
- **Canvas `pointerdown` listener** (already registered after the controls): also call `this.finishViewAnim()`. The controls only store screen coordinates on pointerdown, so finishing afterwards is safe.
- **Call `finishViewAnim()` first in:** `rotateView`, `pan`, `zoom`, `zoomAt`, `setView`, `fitToView`, `setRotateMode`.
- **`clearModel()`:** `this.viewAnim = null; this.removePivotMarker()`.
- **`resize()`:** `if (w === 0 || h === 0) return`. While the 2D drawing is shown, keep the last size, so `camera.aspect` never becomes NaN for the next 3D load.

### 2.2 `frontend/src/picking.ts`
Split the hit selection out of `pick()`. `pick()` behaviour stays the same.
```ts
  /** First hit the user can see: a visible part, not on the clipped-away side of a section. */
  private firstVisibleHit(ndc: THREE.Vector2): THREE.Intersection | null {
    // body = today's setFromCamera / visible filter / intersectObjects / clipping find
  }

  /** Surface point under the cursor, without snapping: zoom point and rotation centre. */
  surfacePoint(ndc: THREE.Vector2): THREE.Vector3 | null {
    return this.firstVisibleHit(ndc)?.point.clone() ?? null
  }
```
`pick()` starts with `const hit = this.firstVisibleHit(ndc); if (!hit) return null`, and the rest is unchanged.

### 2.3 `frontend/src/main.ts`
- **Add a `toNdc(clientX, clientY)` helper** based on the canvas rectangle. Use it in the pointerup pick, `__cadPick` and the new handlers.
- **Wheel**, placed near the click-to-pick block:
  ```ts
  // Wheel zooms toward what is under the cursor, in both rotate modes. Captured on
  // the container so neither OrbitControls nor TrackballControls sees it: their own
  // wheel zoom goes toward the orbit target, and OrbitControls' zoomToCursor steps by
  // the target distance, so it walks through a nearer surface.
  viewport.addEventListener('wheel', (e) => {
    e.preventDefault()
    e.stopPropagation()
    const scale = wheelScale(e)
    if (scale === 1) return
    const ndc = toNdc(e.clientX, e.clientY)
    viewer.camera.updateMatrixWorld() // keys may have moved the camera since the last frame
    viewer.zoomAt(ndc, scale, picker.surfacePoint(ndc))
  }, { capture: true, passive: false })

  const WHEEL_STEP = 0.9 // scale per 100 px of wheel delta (one Chrome notch), same as the + key
  function wheelScale(e: WheelEvent): number {
    let d = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1)
    if (e.ctrlKey) d *= 10 // a trackpad pinch arrives as ctrl+wheel with small deltas
    d = THREE.MathUtils.clamp(d, -300, 300) // one event never jumps more than ~3 notches
    return Math.pow(WHEEL_STEP, -d / 100)
  }
  ```
- **Click tracking:** add `let clickMoves: [number, number] = [Infinity, Infinity]`. Rework pointerup so that the movement is measured before the mode check:
  ```ts
  if (!downAt) return
  const moved = Math.hypot(...)
  downAt = null
  if (e.button === 0) clickMoves = [clickMoves[1], moved]
  if (state.mode === 'なし') return
  if (moved > 5 || measureTool.busy) return
  // ...rest unchanged
  ```
- **Double-click:**
  ```ts
  // Double-click (mode なし only: in 計測/注記 both clicks are picks) makes that
  // surface point the rotation centre. Both clicks must be clicks, not the end of a drag.
  viewport.addEventListener('dblclick', (e) => {
    if (state.mode !== 'なし' || e.button !== 0 || Math.max(...clickMoves) > 5) return
    const ndc = toNdc(e.clientX, e.clientY)
    viewer.camera.updateMatrixWorld()
    const p = picker.surfacePoint(ndc)
    if (p) viewer.orbitAround(p)
  })
  ```
- **`onNavigationKey`:** first return on `isTextEntry(e.target) || e.ctrlKey || e.metaKey || e.altKey`. Then:
  ```ts
  if (e.key === 'f' || e.key === 'F' || e.key === 'Home') { actions.fit(); e.preventDefault(); return }
  if (is2D) return
  ```
  The arrow and `+`/`−` switch follows unchanged. Comment for the `actions.fit` button: 3D keeps the direction; 2D fits the whole drawing.
- **`#hud-keys`:** the two lines from 1.4, joined with `<br />`.
- **Test hooks:**
  - `__cadView` also returns `near: viewer.camera.near, far: viewer.camera.far`. The new keys are additive and backward compatible.
  - `__cadProject` and `__cadPick` call `viewer.camera.updateMatrixWorld()` first, so they are correct straight after an event, before the next render.

### 2.4 `frontend/src/style.css`
```css
/* rotation-centre marker after a double-click: fades out, never takes clicks.
   Animate opacity only: CSS2DRenderer owns `transform`. */
.pivot-marker {
  width: 14px;
  height: 14px;
  border: 2px solid #ffd060;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.6);
  pointer-events: none;
  animation: pivot-fade 1s ease-out forwards;
}
@keyframes pivot-fade {
  0%, 60% { opacity: 1; }
  100% { opacity: 0; }
}
```

### 2.5 Documentation
- **README 画面の操作 table:**

  | 操作 | マウス | キーボード |
  |---|---|---|
  | 回転 | 左ドラッグ | 矢印キー（押した側の面が見えてくる） |
  | 移動 | 右ドラッグ | Shift + 矢印キー |
  | 拡大・縮小 | ホイール（カーソルの下の点に向かって寄る） | ＋ ／ −（画面の中心に向かって） |
  | 回転の中心 | モデルをダブルクリック（モードが「なし」のとき） | — |
  | 全体表示 | 「全体表示」ボタン | F または Home |

  Add under it: 「全体表示はいまの向きのまま、見えている部品の全体が画面の約 9 割に収まるように寄せる（隠した部品は含めない）。新しいモデルを開いたときは斜め上からの向きで表示する。」
- **`e2e/README.md`:** add `test_navigation.py` to the list, and note that it writes its STL boxes to a temporary directory.

### 2.6 Merging with `feat/iges-sewing` (not merged yet)
That branch rewrites `modelBBox()` and changes the first line of `fitToView` to `const box = this.modelBBox()`.
- A1 copies the `modelBBox()` hunk word for word, so that part merges cleanly.
- `fitToView` may give a one-line conflict. Resolve it by taking A1's body.
- A1 does not need the branch's `CURVE_COLOR` change.

## 3. Edge cases
- **Round parts at an angle.** The box corners lie outside the silhouette, so the model fills a little under 88%. Accepted: the spec says to frame `modelBBox()`. For box-like parts such as the runner, the fit is exact.
- **Single-point or zero-size box:** expanded to a 1-unit cube, so there is no division by zero.
- **Flat part seen edge-on:** one axis has zero extent, so the other axis limits. No special case is needed.
- **All parts hidden:** `modelBBox()` falls back to the whole group, the same as on the sewing branch.
- **Hide parts, fit, then show them again:** near/far are now sized to the smaller visible set, so far may clip the re-shown parts. Pressing F again fixes it.
- **Very small or very large models:** near/far scale with r, so a 0.05 mm part and a 5 m part both draw. The tests cover both.
- **Camera forward parallel to `camera.up`:** cannot happen in turntable (pole margin). In free mode, any perpendicular vector is used.
- **Wheel during a drag, coast or auto-rotate:** the coast continues around the new target. There is no jump, because each step is one scaling about a fixed point.
- **Wheel when the zoom point is closer than `4·near`:** zoom-in does nothing and zoom-out still works.
- **Cursor moving between the model and empty space while scrolling:** the zoom point switches type, but every step is still a valid scaling, so the camera never jumps.
- **High-resolution, accelerated or trackpad wheels:** the delta is converted, multiplied for ctrl-pinch and clamped per event.
- **Horizontal-only wheel** (`deltaY = 0`): does nothing.
- **Section caps:** the cap is not a mesh the picker sees, so on a cap the zoom point or pivot is the first unclipped part surface behind it. This is the same as measure and annotation picks today. Accepted.
- **Pivot point closer than `4·near`:** the camera backs off along the view axis to `4·near`, a slight zoom-out.
- **Double-click on empty space, a hidden part, or during a load** (picker emptied): nothing happens.
- **Double-click over a 3D label:** the label layer has `pointer-events: none`, so the surface behind it is picked.
- **Double-click on a panel** (tree, HUD, GUI, measure list): these sit outside `#viewport`, so they never fire it.
- **A drag ending at its start, followed by a click:** rejected by `clickMoves`.
- **2D mode:** wheel and double-click on the 3D view are inactive. F and Home fit the drawing. The resize guard keeps the aspect valid for the next 3D load.
- **Floating panels over the canvas corners:** the fit uses the whole canvas, so lil-gui (245×497 px at the top right) can cover a corner of the model. Accepted; the GUI can be collapsed. For the runner's default view, both ends stay clear of the panels.
- **Presets after a tight fit can crop a long part:** existing behaviour, kept on purpose (see 1.5).

## 4. Test plan

### 4.1 New `e2e/test_navigation.py`
Uses the system Python with Playwright, viewport 1280×800, `CAD_VIEWER_URL`, `localStorage` cleared, page errors and console errors collected and asserted empty at the end.

**Test data.** `box_stl(path, lo, hi)` writes a 12-triangle ASCII STL into a temporary directory:
- `runner.stl`: (0,0,0)–(298, 27.5, 4.5)
- `tiny.stl`: (0,0,0)–(0.05, 0.03, 0.02)
- `huge.stl`: (0,0,0)–(5000, 3000, 2000)

`mini_mold.step` and `plate_drawing.dxf` come from `testdata/`.

**Expected values used by the checks.** None of them come from the code under test:
- Known box corners projected through `__cadProject`.
- Picker hits from `__cadPick`.
- Camera state from `__cadView`, including the new near/far.
- Fixed constants from the specification: the load direction (1,−1,0.7) and Z up.
- Box sizes taken from `make_step_assembly.py`. The bodies left visible after hiding the plate span (21,15,15)–(79,45,40).
- Canvas pixels.

**Helpers:**
- `settle()`: wait for two animation frames.
- `rect(lo, hi)`: bounding rectangle of the 8 projected corners.
- `fill_check(lo, hi)`:
  - `lim = max(w/W, h/H)` must be in [0.86, 0.90].
  - All corners must be inside the canvas.
  - `|left − right| ≤ 0.01·W` and `|top − bottom| ≤ 0.01·H`.
- `depth_check(lo, hi)`: every corner's depth `(Pk − C)·f` must be in `(near, far)`.
- `same_dir(a, b)`: dot product ≥ 1−1e−9, and `up` within 1e−6.
- `plane_point(cx, cy)`: the point on the target plane under a pixel. Let `f = norm(T−C)`, `r = norm(f × up)`, `u = r × f`. Project T, `T + L·r` and `T + L·u`. Points on that plane project linearly, so solve the 2×2 system for α and β, then `A = T + α·r + β·u`.

**A. Fit**
1. **Default view of the runner.** Load `runner.stl`. Check `fill_check(runner)`, `offset_dir == norm(1,−1,0.7)`, `up == Z`, and `depth_check`.
2. **Pixel check of the runner.** Turn the grid off with the GUI checkbox. Read the canvas with `toDataURL()` inside `requestAnimationFrame`. The rectangle of pixels that differ from the background by more than 6 must match `rect(runner)` within ±3 px. Turn the grid back on.
3. **Fit keeps the direction.** For each of 正面, 上, 右, 等角 and 左:
   - Click the preset, then press `-` three times and `Shift+ArrowRight` twice so the view is no longer fitted.
   - Record the direction and up, then fit, cycling through `f`, `Home`, `F` and the 全体表示 button. Focus is still on a GUI button at this point.
   - Check `fill_check`, `same_dir` and `depth_check`.
4. **Narrow viewport.** Resize to 600×900, wait 300 ms, press `f`, and run `fill_check`; here the width limits and the aspect is below 1. Resize back to 1280×800, press `f`, and run `fill_check` again.
5. **Free rotation keeps the roll.** Select 自由回転. Press `ArrowUp` 20 times and `ArrowRight` 5 times so the view is rolled, then `-` three times. Record the direction and up, press `f`, then check `fill_check` and `same_dir`. Up must still be away from Z. Switch back to ターンテーブル.
6. **Height-limited view and hidden parts.**
   - Load `mini_mold.step`, choose 右, press `f`: `fill_check((0,0,0),(100,60,40))` (here the height limits).
   - Uncheck `plate` in the tree, press `f`: `fill_check((21,15,15),(79,45,40))`. Check `plate` again.
7. **Near and far follow the model.** Load `tiny.stl`, run `fill_check` and `depth_check`. Then load `huge.stl` and run them again.
8. **Loading resets the direction.** In 自由回転, tilt the view, then load `runner.stl` again: direction is the load direction, up is Z, and `fill_check` passes. Switch back to ターンテーブル.
9. **2D drawing.**
   - Load the DXF and record `vb0` (the svg `viewBox`).
   - Wheel on `#viewport2d`; the viewBox must change. Press `f`; it must equal `vb0`. Repeat with `Home`.
   - Then load `mini_mold.step` and check `fill_check`. This catches a NaN aspect after 2D.
10. **F is ignored in the note text box.** In 注記 mode, click the model; `.note-input` appears. Type `f`; `__cadView` must not change. Press Escape (nothing is saved) and switch back to なし.

**B. Wheel zoom**, for both ターンテーブル and 自由回転. In free mode, first press `ArrowUp` 7 times and `ArrowRight` 3 times so up is not Z, then `f`.
1. **Zoom toward a surface.**
   - Cursor = rounded `project(90,10,15)`. `P = __cadPick(cursor)`; it must have `kind == 'face'` and lie within 1 mm of (90,10,15), the plate top.
   - Five times `wheel(0,−100)`, then `settle()`. After each step: `|project(P) − cursor| ≤ 0.5 px`; `|C−P|` shrinks by a factor in [0.8, 0.97]; `same_dir`.
   - Five times `wheel(0,+100)`: position and target must return to the start within 1e−4.
2. **Zoom over empty space.**
   - Cursor = (640, 22); `__cadPick` there must be null. Compute `A = plane_point(cursor)`.
   - Three times `wheel(0,−100)`. Each time: `|project(A) − cursor| ≤ 0.5 px`; the new target lies on the line through A and T with `|T'−A| / |T−A| = |C'−A| / |C−A|` within 1e−6; `same_dir`.
   - Three times `wheel(0,+100)`: back to the start.
3. **The zoom stops in front of the surface.**
   - At the surface cursor, 60 times `wheel(0,−300)`. Every 10 events, check that P is still within 1 px of the cursor.
   - At the end: P's depth is greater than near; two more wheel-ups do not move the camera (change below 1e−9); `__cadPick(cursor).point` is within 1e−3 of P, so the same surface is still the first thing hit.
   - Then 80 times `wheel(0,+300)`: the distance stops growing, and every model corner's depth is less than far.
   - Press `f`.
4. **Section.** Turn on 断面 (X at 0.5, keeps x ≤ 50). At the cursor for `project(90,10,15)`, which is now on the clipped side, take `Q = __cadPick`. The expected zoom point is Q's point if it is a face hit (also assert its x ≤ 50), otherwise `plane_point`. After `wheel(−100)`, the expected point stays at the cursor. Turn 断面 off.
5. **The page does not scroll:** `document.scrollingElement.scrollTop == 0`.

**C. Double-click pivot**, for both modes. Set up with 等角 (or the tilted view in free mode), then `f`.
1. **The main check.**
   - Cursor = rounded `project(90,10,15)`. `P = __cadPick(cursor).point` (a face hit). Record C0, T0, f0 and u0, and `depth = (P−C0)·f0`.
   - Install a sampler in the page that records `performance.now()`, `__cadProject(P)` and `__cadView()` every animation frame. Then `page.mouse.dblclick(cursor)`, wait 700 ms, and stop the sampler.
   - Final pose: target equals P within 1e−4; `project(P)` is at the canvas centre within 0.5 px; `same_dir(f0, u0)`; `|C1−P|` equals `depth` within a relative 1e−6.
   - Samples: every sample has the same direction as f0 (1e−9). P's distance from the centre never increases (0.5 px slack). At least 2 samples are between 10% and 90% of the way. The time from the first moving sample to the settled pose is between 100 and 600 ms.
   - Marker: `.pivot-marker` is present right after the double-click. Once settled, its centre is within 3 px of the canvas centre. It is gone 2 s later.
2. **Later rotations turn around P.** Press `ArrowRight` 3 times: `project(P)` stays at the centre within 0.5 px. Drag the mouse 200 px horizontally and wait 800 ms: still at the centre within 1 px. This checks that the active controls object has P as its target.
3. **Empty space:** double-click at (640, 22). Position and target are unchanged, and there is no marker.
4. **Mode gating:** in 計測, double-click `project(50,30,35)`. The target is unchanged. Press 計測クリア and switch back to なし.
5. **Drag guard:** press at X, move 40 px away and back to X+1, release, then click at X straight away. The target is unchanged.
6. **Interrupted animation:** double-click another face point Q, then immediately press `ArrowRight`. After 400 ms the target equals Q and `project(Q)` is at the centre.
7. **Auto-rotate:** turn 自動回転 on and double-click P'. After 600 ms the target equals P'. Over the next 500 ms, `project(P')` stays at the centre within 1 px while the direction turns by more than 3°. Turn 自動回転 off.
8. **Section:** with 断面 on, double-click at `project(90,10,15)`. If the pick there is a face hit, the target equals that point and its x ≤ 50 + 1e−6. Otherwise nothing changes. Turn 断面 off.
9. **Reload during the animation:** double-click, then immediately load `runner.stl`. After loading: the load direction and `fill_check(runner)` hold, and no errors.

At the end, remove `cad-viewer:view` from `localStorage`.

### 4.2 Change to `test_view_controls.py`
Replace the fixed `floor_ink` crop with one computed at run time, beside the model:
- x from 8 to `min(projected x of the mini_mold corners (0,0,0)–(100,60,40)) − 8` (about 126 px)
- y from the tree panel's bottom + 8 to the HUD's top − 8

Assert that this area is at least 60 px wide and 200 px tall. The ink comparisons stay the same. The implementer should confirm `ink_on > 50` at the new fit; if it is not, press `-` a few times before measuring both the on and off states. No other existing test needs to change.

### 4.3 Bugs the tests must catch
| Bug | Caught by |
|---|---|
| Old fit (largest dimension × 1.5) | A1, A3 (runner filled 33%) |
| Aspect ignored (tanH = tanV) | A1, A4 |
| Width and height swapped | A6 (右 view, height-limited) |
| No centring step | A1 margins (155 to 278 px unequal for the runner) |
| Fit resets the direction | A3 |
| Fit resets `camera.up` to Z in free mode | A5 |
| `modelBBox` ignores hidden parts | A6, hidden plate |
| Fixed near/far, or kept from the previous model | A7 (tiny then huge) |
| F/Home not bound, or 3D only | A3, A9 |
| F fires while typing a note | A10 |
| Wheel still reaches the controls | B1 |
| Wheel zoom point always on the target plane | B1 (P is about 36 mm nearer than the target plane) |
| Empty-space zoom goes toward the target | B2 |
| No zoom-in clamp | B3 (P's depth falls below near) |
| No zoom-out clamp | B3 (model beyond far) |
| Wheel changes the view direction | B1, B2 |
| Only one controls object's target updated | B1 free mode, C2 |
| Clipped hits used as the zoom point or pivot | B4, C8 |
| Pivot jumps instead of animating | C1 samples |
| Pivot turns the camera instead of sliding | C1 per-sample direction |
| Pivot changes the zoom | C1 `|C1−P|` |
| Pivot not limited to モード なし | C4 |
| Pivot on empty space | C3 |
| Marker missing, or never removed | C1 |
| An interruption cancels instead of finishing | C6 |
| Auto-rotate fights the animation | C7 |
| Animation keeps running after a reload | C9 |
| Drag guard missing | C5 |

### 4.4 Commands for the implementer
- Type check: `(cd frontend && npx tsc --noEmit -p .)`. Build: `(cd frontend && npm run build)`.
- Backend tests: run `/home/shostako/ClaudeCode/cad-viewer/backend/.venv/bin/pytest -q -p no:cacheprovider tests` with the working directory `/home/shostako/.cache/cad-viewer-wt/a1/backend`. The backend is unchanged; this is a sanity run.
- Every E2E script with `CAD_VIEWER_URL=http://127.0.0.1:5191 timeout 300 python3 e2e/<test>.py`, capturing each exit code: `test_navigation`, `test_view_controls`, `test_stl_view`, `test_step_view`, `test_measure`, `test_measure_cancel_busy`, `test_mesh_annotation`, `test_section_annotation`, `test_sidecar_flush`, `test_sidecar_flush_inflight`, `test_sidecar_isolation`, `test_drawing2d`.

### Files touched
- `/home/shostako/.cache/cad-viewer-wt/a1/frontend/src/viewer.ts`
- `/home/shostako/.cache/cad-viewer-wt/a1/frontend/src/picking.ts`
- `/home/shostako/.cache/cad-viewer-wt/a1/frontend/src/main.ts`
- `/home/shostako/.cache/cad-viewer-wt/a1/frontend/src/style.css`
- `/home/shostako/.cache/cad-viewer-wt/a1/README.md`
- `/home/shostako/.cache/cad-viewer-wt/a1/e2e/README.md`
- `/home/shostako/.cache/cad-viewer-wt/a1/e2e/test_view_controls.py`
- `/home/shostako/.cache/cad-viewer-wt/a1/e2e/test_navigation.py` (new)
