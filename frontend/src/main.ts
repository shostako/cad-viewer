import './style.css'
import GUI from 'lil-gui'
import * as THREE from 'three'
import {
  uploadModel,
  fetchMesh,
  fetchDrawingSvg,
  fetchThickness,
  fetchProperties,
  getSidecar,
  putSidecar,
  __stallNextMeasure,
  __stallNextSidecar,
  __stallNextProperties,
  type ModelMeta,
  type ModelProperties,
} from './api'
import { CursorTip, HoverProbe } from './cursortip'
import { DRAFT_MAX_DEG, PULL_DIRS, PULL_DIR_OPTIONS, draftTipText, renderDraftLegend, type PullDir } from './draft'
import { Drawing2D } from './drawing2d'
import { largestFreeRect, type ScreenRect } from './freearea'
import { MeasureTool, type EntryData } from './measure'
import { toModelData, type ModelData } from './model'
import { Picker } from './picking'
import { OTHER_RESIN, PropertiesPanel, RESIN_DENSITY, RESIN_NAMES } from './properties'
import { SectionTool, type Axis } from './section'
import { canvasToPng, downloadBlob, pngFileName, type ExportBackground } from './snapshot'
import { METHOD_NAMES, renderThicknessLegend, thicknessAt, thicknessTipText, type ThicknessMethod } from './thickness'
import { renderTree } from './tree'
import { AxisTriad } from './triad'
import { DISPLAY_STYLES, DRAG_PX, Viewer, type DisplayStyle, type Projection, type RotateMode, type ViewPreset } from './viewer'

const app = document.querySelector<HTMLDivElement>('#app')!
app.innerHTML = `
  <div id="viewport"></div>
  <div id="viewport2d" class="hidden"></div>
  <div id="dropzone" class="hidden">ここにドロップして読み込み</div>
  <div id="empty-hint">
    <div id="empty-title">CAD ファイルを開く</div>
    <button id="empty-open" type="button">ファイルを選ぶ</button>
    <div id="empty-drop">または、この画面にファイルをドロップ</div>
    <div id="empty-formats">STEP / IGES / STL / 3MF / OBJ / PLY / DXF / DWG</div>
  </div>
  <div id="tree-panel" class="hidden">
    <div id="tree-title">部品ツリー</div>
    <div id="tree-body"></div>
  </div>
  <div id="corner-br">
    <div id="measure-panel" class="hidden">
      <div id="measure-title">計測</div>
      <ul id="measure-list"></ul>
    </div>
    <div id="props-panel" class="hidden"></div>
  </div>
  <div id="triad" class="hidden"></div>
  <div id="hud">
    <div id="hud-title">cad-viewer</div>
    <div id="draft-legend" class="hidden"></div>
    <div id="thickness-legend" class="hidden"></div>
    <div id="hud-info">ファイルをドロップ、または「ファイルを開く」から選ぶ</div>
    <div id="hud-keys"></div>
  </div>
  <div id="undo-toast" class="hidden" role="status">
    <span id="undo-text"></span>
    <button id="undo-btn" type="button">元に戻す</button>
  </div>
  <input type="file" id="file-input" accept=".step,.stp,.iges,.igs,.stl,.3mf,.obj,.ply,.dxf,.dwg" hidden />
`

const viewport = document.querySelector<HTMLDivElement>('#viewport')!
const dropzone = document.querySelector<HTMLDivElement>('#dropzone')!
const hud = document.querySelector<HTMLDivElement>('#hud')!
const hudInfo = document.querySelector<HTMLDivElement>('#hud-info')!
const draftLegend = document.querySelector<HTMLDivElement>('#draft-legend')!
const thicknessLegend = document.querySelector<HTMLDivElement>('#thickness-legend')!
const fileInput = document.querySelector<HTMLInputElement>('#file-input')!
const treePanel = document.querySelector<HTMLDivElement>('#tree-panel')!
const treeBody = document.querySelector<HTMLDivElement>('#tree-body')!

const cornerBr = document.querySelector<HTMLDivElement>('#corner-br')!
const measurePanel = document.querySelector<HTMLDivElement>('#measure-panel')!
const measureList = document.querySelector<HTMLUListElement>('#measure-list')!

const viewport2d = document.querySelector<HTMLDivElement>('#viewport2d')!
const hudKeys = document.querySelector<HTMLDivElement>('#hud-keys')!
const emptyHint = document.querySelector<HTMLDivElement>('#empty-hint')!
document.querySelector('#empty-open')!.addEventListener('click', () => fileInput.click())
const propsEl = document.querySelector<HTMLDivElement>('#props-panel')!

const viewer = new Viewer(viewport)
// bottom left, outside #viewport: its clicks never reach the canvas (pick, pivot, controls)
const triadEl = document.querySelector<HTMLDivElement>('#triad')!
const triad = new AxisTriad(triadEl, (v) => viewer.setView(v))
viewer.onFrame(() => triad.update(viewer.camera.quaternion))
const picker = new Picker(viewer)
const measureTool = new MeasureTool(viewer)
const sectionTool = new SectionTool(viewer)
const drawing2d = new Drawing2D(viewport2d, (msg) => {
  hudInfo.textContent = msg
})

// how to move around, per view (HUD bottom left)
const KEYS_3D = [
  '左ドラッグ・矢印キー: 回転　右ドラッグ・Shift+矢印: 移動　ホイール（カーソルの位置へ）・＋／−: 拡大縮小',
  'ダブルクリック: そこを回転の中心に　F・Home: 全体表示',
]
const KEYS_2D = [
  'ドラッグ: 移動　ホイール（カーソルの位置へ）: 拡大縮小　F・Home: 全体表示',
  '計測モード: 端点・中心・四分円点にスナップして 2 点間の距離',
]
function setKeys(lines: string[]): void {
  hudKeys.replaceChildren()
  lines.forEach((line, i) => {
    if (i) hudKeys.appendChild(document.createElement('br'))
    hudKeys.appendChild(document.createTextNode(line))
  })
}
setKeys(KEYS_3D)

let is2D = false
/**
 * Switch between the 3D view and a 2D drawing. In 2D the 3D-only controls are
 * hidden (view, section, thickness, volume) and 注記 is disabled: the drawing
 * viewer only measures.
 */
function show2D(on: boolean): void {
  is2D = on
  viewport2d.classList.toggle('hidden', !on)
  viewport.classList.toggle('hidden', on)
  treePanel.classList.toggle('hidden', on || !treeBody.hasChildNodes())
  for (const f of folders3D) f.show(!on)
  const note = [...modeSelect.options].find((o) => o.text === '注記')
  if (note) note.disabled = on
  if (on && state.mode === '注記') modeCtl.setValue('なし')
  setKeys(on ? KEYS_2D : KEYS_3D)
  updateTriad()
}

/** whether a model or drawing is on screen, and its file name (for the PNG export) */
function setContentShown(on: boolean, fileName = ''): void {
  contentShown = on
  shownFileName = on ? fileName : ''
  savePngCtl.enable(on)
  updateTriad()
}

/**
 * The axis triad is shown with a 3D model only (not on the empty screen,
 * during a load, or on a drawing). While it is, the HUD moves right of it.
 */
function updateTriad(): void {
  const on = contentShown && !is2D
  triad.show(on)
  if (on) triad.update(viewer.camera.quaternion) // drawn now, not a frame later
  hud.classList.toggle('beside-triad', on)
  // now, not on the next frame: until then the HUD would keep the width it
  // had at its old left edge and reach under the right-hand column
  layoutCorner()
}

/** the "open / drop a file" card in the middle of an empty screen */
function showEmpty(on: boolean): void {
  emptyHint.classList.toggle('hidden', !on)
}
// whether a model or drawing is on screen: a failed load after the old one was
// torn down leaves an empty screen, which gets the card back
let contentShown = false
// file name of what is on screen (File.name, not meta.name: the backend
// answers a duplicate upload with the first upload's name)
let shownFileName = ''

let currentModelId: string | null = null
// Sidecar-save suppression during model teardown/restore. Generation-tagged
// (not a plain boolean) so a superseded load releases its own claim without
// clobbering a newer load's — a boolean got stuck true when the newer load
// failed before entering its own teardown, silently killing all saves.
let restoringOwner = 0 // 0 = not restoring; otherwise the loadGen that owns it

const gui = new GUI({ title: '操作' })
const state = { mode: 'なし' as 'なし' | '計測' | '注記' }
const actions = {
  open: () => fileInput.click(),
  // 3D keeps the view direction and fits the visible parts; 2D fits the whole drawing
  fit: () => (is2D ? drawing2d.fit() : viewer.fitToView()),
  // both can be undone: the 3D list, or a drawing's measurements
  clearMeasure: () => (is2D ? clearDrawingWithUndo() : deleteWithUndo(() => measureTool.clearAll())),
  // a function declaration below, so it is hoisted
  savePng: () => void savePng(),
}
gui.add(actions, 'open').name('ファイルを開く')
gui.add(actions, 'fit').name('全体表示')
const modeCtl = gui
  .add(state, 'mode', ['なし', '計測', '注記'])
  .name('モード')
  .onChange((mode: string) => {
    if (mode !== '計測') measureTool.cancelPending()
    drawing2d.measureMode = mode === '計測'
    viewport.style.cursor = mode === 'なし' ? '' : 'crosshair'
    viewport2d.style.cursor = mode === '計測' ? 'crosshair' : ''
  })
const modeSelect = modeCtl.domElement.querySelector('select')!
gui.add(actions, 'clearMeasure').name('計測クリア')

// ---- save the view as a PNG
// The background choice survives a reload, like the view preferences.
const EXPORT_PREFS_KEY = 'cad-viewer:export'
const exportPrefs = { background: 'screen' as ExportBackground }
try {
  const saved = JSON.parse(localStorage.getItem(EXPORT_PREFS_KEY) ?? '{}')
  if (saved.background === 'screen' || saved.background === 'white') exportPrefs.background = saved.background
} catch {
  /* defaults */
}
function saveExportPrefs(): void {
  try {
    localStorage.setItem(EXPORT_PREFS_KEY, JSON.stringify(exportPrefs))
  } catch {
    /* best-effort */
  }
}
// disabled until something is on screen (setContentShown)
const savePngCtl = gui.add(actions, 'savePng').name('画像を保存（PNG）').disable()
// a select, not a checkbox: E2E scripts click the first checkbox of the panel.
// Labelled 画像の背景 so nobody takes it for the screen's own background.
gui
  .add(exportPrefs, 'background', { 画面のまま: 'screen', 白: 'white' })
  .name('画像の背景')
  .onChange(saveExportPrefs)
let exporting = false
async function savePng(): Promise<void> {
  // the button is disabled then too; this also covers keyboard activation and races
  if (!contentShown || exporting) return
  exporting = true
  // name and time of the click, even if a load starts during a slow 2D decode
  const name = pngFileName(shownFileName, new Date())
  const bg = exportPrefs.background
  try {
    // clicks while this runs are dropped: say why nothing else happens
    hudInfo.textContent = '画像を作成中...'
    // 3D: no await before snapshot(), which renders and copies in one task
    const canvas = is2D ? await drawing2d.snapshot(bg) : viewer.snapshot(bg)
    downloadBlob(await canvasToPng(canvas), name)
    hudInfo.textContent = `画像を保存: ${name}`
  } catch (e) {
    hudInfo.textContent = `画像の保存に失敗: ${e instanceof Error ? e.message : e}`
  } finally {
    exporting = false
  }
}

// ---- display & view navigation
// Preferences survive a reload. Storage can be unavailable (private window,
// blocked site data) — fall back to defaults silently.
const VIEW_PREFS_KEY = 'cad-viewer:view'
const viewPrefs = {
  grid: true,
  autoRotate: false,
  speed: 30,
  rotateMode: 'turntable' as RotateMode,
  style: 'shaded-edges' as DisplayStyle,
  projection: 'perspective' as Projection,
}
try {
  const saved = JSON.parse(localStorage.getItem(VIEW_PREFS_KEY) ?? '{}')
  if (typeof saved.grid === 'boolean') viewPrefs.grid = saved.grid
  if (typeof saved.speed === 'number') viewPrefs.speed = saved.speed
  if (saved.rotateMode === 'turntable' || saved.rotateMode === 'free') viewPrefs.rotateMode = saved.rotateMode
  if ((DISPLAY_STYLES as readonly string[]).includes(saved.style)) viewPrefs.style = saved.style
  if (saved.projection === 'perspective' || saved.projection === 'orthographic') viewPrefs.projection = saved.projection
} catch {
  /* defaults */
}
function saveViewPrefs(): void {
  try {
    // auto-rotate is deliberately not remembered: a model that starts spinning
    // on open is a surprise, not a preference
    const { grid, speed, rotateMode, style, projection } = viewPrefs
    localStorage.setItem(VIEW_PREFS_KEY, JSON.stringify({ grid, speed, rotateMode, style, projection }))
  } catch {
    /* best-effort */
  }
}
viewer.gridVisible = viewPrefs.grid
viewer.autoRotateSpeed = viewPrefs.speed
viewer.setRotateMode(viewPrefs.rotateMode)
// before any model loads: addPart applies the current style to every new part
viewer.setDisplayStyle(viewPrefs.style)
viewer.setProjection(viewPrefs.projection)

const viewFolder = gui.addFolder('表示')
// "Pick a style, then turn the model to look" works without blurring the
// select: the arrows turn the view even while a GUI dropdown has the focus
// (isTextEntry), and never step its options.
viewFolder
  .add(viewPrefs, 'style', { '陰影＋稜線': 'shaded-edges', 陰影のみ: 'shaded', ワイヤーフレーム: 'wireframe', 半透明: 'xray' })
  .name('表示スタイル')
  .onChange((v: DisplayStyle) => {
    viewer.setDisplayStyle(v)
    saveViewPrefs()
    refreshHeatmapHud()
  })
viewFolder
  .add(viewPrefs, 'grid')
  .name('グリッド')
  .onChange((v: boolean) => {
    viewer.gridVisible = v
    saveViewPrefs()
  })
viewFolder
  .add(viewPrefs, 'autoRotate')
  .name('自動回転')
  .onChange((v: boolean) => (viewer.autoRotate = v))
viewFolder
  .add(viewPrefs, 'speed', 5, 120, 1)
  .name('回転速度 (°/秒)')
  .onChange((v: number) => {
    viewer.autoRotateSpeed = v
    saveViewPrefs()
  })
viewFolder
  .add(viewPrefs, 'rotateMode', { ターンテーブル: 'turntable', 自由回転: 'free' })
  .name('回転方式')
  .onChange((v: RotateMode) => {
    viewer.setRotateMode(v)
    saveViewPrefs()
  })
// one row (the column is tight on half a screen), before the 視点 sub-folder:
// lil-gui keeps the order things were added in. A select, so グリッド stays
// the panel's first checkbox.
viewFolder
  .add(viewPrefs, 'projection', { 透視: 'perspective', 平行: 'orthographic' })
  .name('投影')
  .onChange((v: Projection) => {
    viewer.setProjection(v)
    saveViewPrefs()
  })
const presetFolder = viewFolder.addFolder('視点')
const presetActions: Record<string, () => void> = {}
const presetNames: [ViewPreset, string][] = [
  ['front', '正面'],
  ['back', '背面'],
  ['right', '右'],
  ['left', '左'],
  ['top', '上'],
  ['bottom', '下'],
  ['iso', '等角'],
]
for (const [preset, label] of presetNames) {
  presetActions[preset] = () => viewer.setView(preset)
  presetFolder.add(presetActions, preset).name(label)
}

// keyboard navigation (3D only). Arrow keys move the CAMERA toward that side,
// so the face on that side comes into view; Shift slides instead of turning.
const KEY_TURN = (5 * Math.PI) / 180 // per keydown; key repeat makes it continuous
const KEY_PAN = 0.05 // fraction of the view height
const KEY_ZOOM = 0.9
function isTextEntry(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  // A lil-gui dropdown keeps focus after a pick, and also when its popup is
  // closed without a change (Escape, the same option again). Chrome then makes
  // the arrows step through the options: the view keys would silently change
  // a setting (型開き方向, モード, ...). The arrows navigate instead, and
  // preventDefault below keeps the closed select as it is. An open popup gets
  // its keys before the page does.
  if (el instanceof HTMLSelectElement) return !el.closest('.lil-gui')
  if (el.isContentEditable || el instanceof HTMLTextAreaElement) return true
  // sliders use the arrows themselves — leave those alone
  if (el.getAttribute('role') === 'slider') return true
  // checkboxes / buttons keep focus after a click — arrows must still navigate
  return el instanceof HTMLInputElement && !['checkbox', 'radio', 'button'].includes(el.type)
}
// capture phase: lil-gui stops keydown propagation inside its panel, so after
// clicking a view button the arrows would never reach a bubbling listener
window.addEventListener('keydown', onNavigationKey, { capture: true })
function onNavigationKey(e: KeyboardEvent): void {
  if (isTextEntry(e.target)) return
  // Ctrl+Z (Cmd+Z): put back the measurements just deleted, while that can be undone
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && (e.key === 'z' || e.key === 'Z')) {
    if (undoDelete()) e.preventDefault()
    return
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return
  if (e.key === 'Escape') {
    if (escapeMeasure()) e.preventDefault()
    return
  }
  if (e.key === 'f' || e.key === 'F' || e.key === 'Home') {
    actions.fit() // 2D too: fits the drawing
    e.preventDefault() // Home would scroll
    return
  }
  if (is2D) return
  const shift = e.shiftKey
  switch (e.key) {
    case 'ArrowLeft':
      shift ? viewer.pan(-KEY_PAN, 0) : viewer.rotateView(-KEY_TURN, 0)
      break
    case 'ArrowRight':
      shift ? viewer.pan(KEY_PAN, 0) : viewer.rotateView(KEY_TURN, 0)
      break
    case 'ArrowUp':
      shift ? viewer.pan(0, KEY_PAN) : viewer.rotateView(0, KEY_TURN)
      break
    case 'ArrowDown':
      shift ? viewer.pan(0, -KEY_PAN) : viewer.rotateView(0, -KEY_TURN)
      break
    case '+':
    case '=': // US layout: the + key without Shift
      viewer.zoom(KEY_ZOOM)
      break
    case '-':
      viewer.zoom(1 / KEY_ZOOM)
      break
    default:
      return
  }
  e.preventDefault()
}

const sectionFolder = gui.addFolder('断面')
sectionFolder.close()
sectionFolder
  .add(sectionTool, 'enabled')
  .name('有効')
  .listen() // state can change programmatically (2D switch) — keep UI in sync
  .onChange(() => sectionTool.update())
sectionFolder
  .add(sectionTool, 'axis', ['X', 'Y', 'Z'] as Axis[])
  .name('軸')
  .onChange(() => sectionTool.update())
sectionFolder
  .add(sectionTool, 'position', 0, 1, 0.01)
  .name('位置')
  .onChange(() => sectionTool.update())
sectionFolder
  .add(sectionTool, 'flip')
  .name('反転')
  .onChange(() => sectionTool.update())
sectionFolder
  .add(sectionTool, 'caps')
  .name('キャップ（切り口を塞ぐ）')
  .onChange(() => sectionTool.update())

// ---- per-vertex colouring: thickness heatmap and draft angle
// Both paint the same vertex colours, so only one is on at a time. The status
// line (#hud-info) shows the model summary; the heatmap writes its own line,
// which goes back to the summary when the heatmap goes away.

/** the status line of the loaded model (name, parts, tris, size) */
let modelSummary = ''
/** the last 肉厚 line updateThickness wrote; put back to modelSummary when the heatmap goes away */
let thicknessHud = ''
function setThicknessHud(text: string): void {
  thicknessHud = text
  hudInfo.textContent = text
}
function dropThicknessHud(): void {
  // only if nothing else (a measure result, an error) replaced it meanwhile
  if (thicknessHud && hudInfo.textContent === thicknessHud) hudInfo.textContent = modelSummary
  thicknessHud = ''
}
/**
 * Which feature's colours are on the meshes. Turning one feature off (or
 * changing its parameters while it is off) must not wipe the other's colours.
 */
type ColorOwner = 'none' | 'thickness' | 'draft'
let colorOwner: ColorOwner = 'none'
function releaseColors(owner: ColorOwner): void {
  if (colorOwner === owner) {
    viewer.clearVertexColors()
    colorOwner = 'none'
  }
}

// Draft direction and angle survive a reload; the on/off box does not (a model
// that opens already coloured would look like a broken file).
const DRAFT_PREFS_KEY = 'cad-viewer:draft'
const draftState = { enabled: false, dir: '+Z' as PullDir, required: 1 }
try {
  const saved = JSON.parse(localStorage.getItem(DRAFT_PREFS_KEY) ?? '{}') ?? {}
  if ((Object.keys(PULL_DIRS) as string[]).includes(saved.dir)) draftState.dir = saved.dir
  const r = saved.required
  if (typeof r === 'number' && Number.isFinite(r) && r >= 0 && r <= DRAFT_MAX_DEG) draftState.required = r
} catch {
  /* defaults */
}
/** /properties of the current model (the legend's note on open parts); null until it answers */
let modelProps: ModelProperties | null = null
function saveDraftPrefs(): void {
  try {
    const { dir, required } = draftState
    localStorage.setItem(DRAFT_PREFS_KEY, JSON.stringify({ dir, required }))
  } catch {
    /* best-effort */
  }
}

// ---- thickness heatmap
const thicknessState = { enabled: false, threshold: 1.5, method: 'ray' as ThicknessMethod }
const thicknessCache = new Map<string, Map<number, Float32Array>>()
/** the values the heatmap on screen was painted from (part id -> one per display vertex) */
let shownThickness: Map<number, Float32Array> | null = null
const HEATMAP_HUD = '肉厚ヒートマップ表示中'
function heatmapHud(): string {
  // B-rep faces are not drawn in ワイヤーフレーム, so their colours cannot show;
  // a mesh model (STL, ...) draws its triangles' edges in the colours instead.
  // The colours and the threshold are on the legend just above.
  const note = viewer.facesHidden ? '。ワイヤーフレームでは面を描かないので、色は陰影か半透明で見る' : ''
  return `${HEATMAP_HUD}（${METHOD_NAMES[thicknessState.method]}${note}）`
}
/** the heatmap goes away: its colours, its legend and its status line */
function clearThickness(): void {
  releaseColors('thickness')
  thicknessLegend.classList.add('hidden')
  dropThicknessHud()
  probe.refresh()
}
/** a style switch updates the note only while the HUD shows the heatmap message */
function refreshHeatmapHud(): void {
  // through setThicknessHud, so that turning the heatmap off still recognises
  // (and replaces) the line; not over a measure result that replaced it
  if (thicknessHud && hudInfo.textContent === thicknessHud) setThicknessHud(heatmapHud())
}
async function updateThickness(): Promise<void> {
  if (!currentModelId) return
  if (!thicknessState.enabled) {
    clearThickness()
    return
  }
  // Capture the request context: a slow fetch can resolve after the user has
  // switched models (or toggled off) — applying that late response would
  // recolor the wrong model and poison the (already cleared) cache.
  const requestedId = currentModelId
  const requestedGen = loadGen
  const requestedMethod = thicknessState.method // method can also change mid-flight
  try {
    let data = thicknessCache.get(requestedMethod)
    if (!data) {
      setThicknessHud(requestedMethod === 'ball' ? '肉厚計算中（ボール法、少し待て）...' : '肉厚計算中...')
      data = await fetchThickness(requestedId, requestedMethod)
      if (
        requestedGen !== loadGen ||
        requestedId !== currentModelId ||
        requestedMethod !== thicknessState.method ||
        !thicknessState.enabled
      )
        return // superseded: don't cache, don't recolor, don't touch the HUD
      thicknessCache.set(requestedMethod, data)
    }
    viewer.setThicknessColors(data, thicknessState.threshold)
    colorOwner = 'thickness'
    shownThickness = data
    // the method named is thicknessState.method, equal to requestedMethod here
    // (a fetch that a method change overtook returned above)
    renderThicknessLegend(thicknessLegend, thicknessState.threshold, thicknessState.method)
    thicknessLegend.classList.remove('hidden')
    setThicknessHud(heatmapHud())
    probe.refresh() // other values under a cursor that stays where it is
  } catch (e) {
    if (requestedGen !== loadGen || requestedId !== currentModelId) return // stale failure
    // the user moved on (抜き勾配 took over, toggled off, other 方式): a late error is noise
    if (!thicknessState.enabled || requestedMethod !== thicknessState.method) return
    thicknessHud = ''
    thicknessState.enabled = false
    // the colours of the 方式 shown before go with the box: no colours without their legend
    releaseColors('thickness')
    shownThickness = null
    thicknessLegend.classList.add('hidden')
    probe.refresh()
    hudInfo.textContent = `肉厚計算エラー: ${e instanceof Error ? e.message : e}`
  }
}
const thicknessFolder = gui.addFolder('肉厚')
thicknessFolder.close()
thicknessFolder
  .add(thicknessState, 'enabled')
  .name('ヒートマップ')
  .listen() // reset programmatically on errors / model switch / 抜き勾配 taking over
  .onChange((on: boolean) => {
    // one vertex-colour feature at a time: the heatmap takes over from the draft
    if (on && draftState.enabled) {
      draftState.enabled = false
      updateDraft()
    }
    void updateThickness()
  })
thicknessFolder
  .add(thicknessState, 'method', { レイ法: 'ray', 'ローリングボール法': 'ball' })
  .name('方式')
  .onChange(() => void updateThickness())
thicknessFolder
  .add(thicknessState, 'threshold', 0.1, 10, 0.1)
  .name('閾値 (mm)')
  .onChange(() => void updateThickness())

// ---- draft angle (抜き勾配)
function updateDraft(): void {
  // nothing to colour (empty, drawing, load in progress, curves only): the box
  // snaps back. lil-gui's setValue redraws the box after onChange returns.
  if (draftState.enabled && (is2D || !viewer.hasFaces())) draftState.enabled = false
  if (!draftState.enabled) {
    releaseColors('draft')
    draftLegend.classList.add('hidden')
    probe.refresh()
    return
  }
  viewer.setDraftColors(PULL_DIRS[draftState.dir], draftState.required)
  colorOwner = 'draft'
  renderLegend()
  draftLegend.classList.remove('hidden')
  probe.refresh()
}
function renderLegend(): void {
  // Parts with faces but no volume (open, mixed winding, ...): only closed
  // bodies are turned outward on load, so their front side is the file's.
  // Counted once /properties has answered; until then (or if it fails) no note.
  const unoriented = modelProps?.parts.filter((p) => p.volume === null && p.reason !== 'no_faces').length ?? 0
  renderDraftLegend(draftLegend, draftState.dir, draftState.required, unoriented)
}
const draftFolder = gui.addFolder('抜き勾配')
draftFolder.close()
draftFolder
  .add(draftState, 'enabled')
  .name('色分け')
  .listen() // reset programmatically on model switch / heatmap taking over
  .onChange((on: boolean) => {
    if (on && thicknessState.enabled) {
      // The draft takes over. An in-flight thickness fetch sees enabled=false
      // and is dropped. Clearing first keeps the meshes plain if the box snaps
      // back below (nothing to colour); otherwise updateDraft repaints them.
      thicknessState.enabled = false
      clearThickness()
    }
    updateDraft()
  })
draftFolder
  .add(draftState, 'dir', PULL_DIR_OPTIONS)
  .name('型開き方向')
  .onChange(() => {
    // the arrows on the still-focused select move the view (isTextEntry)
    saveDraftPrefs()
    updateDraft()
  })
draftFolder
  .add(draftState, 'required', 0, DRAFT_MAX_DEG, 0.1)
  .name('必要な勾配 (°)')
  .onChange(() => {
    saveDraftPrefs()
    updateDraft()
  })

// ---- the value under the cursor (#cursor-tip)
// While the heatmap or the draft colouring is on, the label beside the cursor
// says what the colour under it stands for: the thickness, or the draft angle
// and its class. Read from the triangle under the cursor by the rule that
// coloured it (the same vertex values, the same normals), so the number says
// what the colour says; where the colours blur across a triangle (a large
// face between thin and thick vertices, a curved B-rep face), it gives the
// value at that very point.
const cursorTip = new CursorTip(document.body)
const probe = new HoverProbe(viewport, cursorTip, valueUnderCursor)
function valueUnderCursor(clientX: number, clientY: number): string | null {
  if (is2D || colorOwner === 'none') return null
  const hit = picker.faceHit(toNdc(clientX, clientY))
  // off the model, or on a face the style does not draw (ワイヤーフレーム of a
  // B-rep part): faces stay pickable there, but no value for a blank spot
  if (!hit || !viewer.facesDrawn(hit.partId)) return null
  if (colorOwner === 'thickness') {
    const values = shownThickness?.get(hit.partId)
    return values ? thicknessTipText(thicknessAt(values, hit.vertices, hit.weights)) : null
  }
  const s = viewer.draftSineAt(hit.partId, hit.triangle, hit.weights, PULL_DIRS[draftState.dir])
  return s === null ? null : draftTipText(s, draftState.required)
}
// A still cursor sees something else when the view moves under it (keys,
// auto-rotate, the coast after a drag, a pivot slide): look again then. Not
// on every frame: OrbitControls moves the camera by rounding noise each frame,
// at rest too. "Moved" is measured from the camera of the last look, so a
// slow drift still adds up to a look.
const lookedCameraWorld = new THREE.Matrix4()
const lookedCameraProjection = new THREE.Matrix4()
viewer.onFrame(() => {
  const cam = viewer.camera
  if (nearlyEqual(cam.matrixWorld, lookedCameraWorld) && nearlyEqual(cam.projectionMatrix, lookedCameraProjection)) return
  lookedCameraWorld.copy(cam.matrixWorld)
  lookedCameraProjection.copy(cam.projectionMatrix)
  probe.refresh()
})
/**
 * Every element within 1e-9 of the larger magnitude (of 1 below that). The
 * rounding noise is about 1e-15 of it per frame (measured); a turn of 1e-9 rad
 * or a move of 1e-9 of the camera's distance from the origin is far under a
 * pixel, also on a model placed thousands of mm away from the origin.
 */
function nearlyEqual(a: THREE.Matrix4, b: THREE.Matrix4): boolean {
  for (let i = 0; i < 16; i++) {
    const x = a.elements[i]
    const y = b.elements[i]
    if (Math.abs(x - y) > 1e-9 * Math.max(1, Math.abs(x), Math.abs(y))) return false
  }
  return true
}

// ---- volume / area / weight
// Resin and specific gravity survive a reload, like the view preferences.
const PROPS_PREFS_KEY = 'cad-viewer:props'
const propsPrefs = { resin: 'PMMA', density: RESIN_DENSITY.PMMA }
try {
  const saved = JSON.parse(localStorage.getItem(PROPS_PREFS_KEY) ?? '{}')
  if (RESIN_NAMES.includes(saved.resin)) {
    propsPrefs.resin = saved.resin
    propsPrefs.density = RESIN_DENSITY[saved.resin]
  } else if (saved.resin === OTHER_RESIN && Number.isFinite(saved.density) && saved.density > 0) {
    propsPrefs.resin = OTHER_RESIN
    propsPrefs.density = saved.density
  }
} catch {
  /* defaults */
}
function savePropsPrefs(): void {
  try {
    localStorage.setItem(PROPS_PREFS_KEY, JSON.stringify(propsPrefs))
  } catch {
    /* best-effort */
  }
}

// The right-hand column: the GUI at the top (fixed, z 1001, grows as folders
// open) and the bottom-right stack under it (measure list, volume / weight).
// The stack keeps a usable minimum; when the column is too short for both, the
// GUI gives way and scrolls inside (lil-gui scrolls its children once the root
// has a max-height). Nothing in the stack ever sits under the GUI.
const COLUMN_MARGIN = 12 // #corner-br's distance from the bottom
const COLUMN_GAP = 8
const MEASURE_MIN_PX = 120 // the measure list's title and about three rows
const GUI_MIN_PX = 240 // below this the GUI stops giving way
const HUD_MIN_PX = 200 // below this the HUD stops wrapping and may meet the stack
function layoutCorner(): void {
  const h = window.innerHeight
  const measureShown = !measurePanel.classList.contains('hidden')
  // natural height: content and padding (scrollHeight) plus the border
  const measureNatural = measurePanel.scrollHeight + measurePanel.offsetHeight - measurePanel.clientHeight
  const measureMin = measureShown ? Math.min(measureNatural, MEASURE_MIN_PX) : 0
  const propsMin = propsPanel.minHeight()
  const stackMin = measureMin + propsMin + (measureMin && propsMin ? COLUMN_GAP : 0)
  const guiMax = Math.max(h - COLUMN_MARGIN - COLUMN_GAP - stackMin, GUI_MIN_PX)
  // never taller than the window (GUI_MIN_PX can exceed a tiny one)
  gui.domElement.style.maxHeight = stackMin ? `${Math.min(guiMax, h)}px` : ''
  const room = h - COLUMN_MARGIN - (gui.domElement.getBoundingClientRect().bottom + COLUMN_GAP)
  const propsShare = propsMin ? propsMin + COLUMN_GAP : 0
  measurePanel.style.maxHeight = `${Math.max(Math.min(0.4 * h, room - propsShare), measureMin)}px`
  const measureUsed = measureShown ? measurePanel.getBoundingClientRect().height + COLUMN_GAP : 0
  propsPanel.fitHeight(room - measureUsed)
  // the HUD (bottom left) wraps its lines rather than run under the right-hand
  // column on a narrow window (half a screen): the column starts at the GUI or
  // at the stack, whichever reaches further left (the stack is as wide as its
  // widest panel)
  const hudLeft = hud.getBoundingClientRect().left
  const columnLeft = Math.min(gui.domElement.getBoundingClientRect().left, cornerBr.getBoundingClientRect().left)
  hud.style.maxWidth = `${Math.max(columnLeft - COLUMN_GAP - hudLeft, HUD_MIN_PX)}px`
}
// From a ResizeObserver, lay out on the next frame: changing an observed
// element's size inside its own callback reports a "ResizeObserver loop" error.
// The layout settles in a frame or two (the second pass sets the same sizes).
let layoutQueued = false
function queueLayoutCorner(): void {
  if (layoutQueued) return
  layoutQueued = true
  requestAnimationFrame(() => {
    layoutQueued = false
    layoutCorner()
  })
}
const propsPanel = new PropertiesPanel(propsEl, (id) => viewer.isPartVisible(id), layoutCorner)
// Watch the GUI and the measure list only, never the props panel itself:
// fitHeight resizes the panel's table, and the panel reports its own changes.
// The list (ul) too: once the panel is capped, new entries only grow the list.
new ResizeObserver(queueLayoutCorner).observe(gui.domElement)
new ResizeObserver(queueLayoutCorner).observe(measurePanel)
new ResizeObserver(queueLayoutCorner).observe(measureList)
window.addEventListener('resize', layoutCorner)
// When the GUI has had to give way (it scrolls), bring a folder the user just
// opened into view once lil-gui's opening animation (300 ms) ends. A timer
// backs up the transitionend: with no transition (nothing to animate, reduced
// motion) the event never comes, and the listener must not stay behind.
const REVEAL_FALLBACK_MS = 450
gui.onOpenClose((changed) => {
  if (changed === gui || changed._closed) return
  const kids = changed.domElement.querySelector<HTMLElement>(':scope > .lil-children')
  const scroller = gui.domElement.querySelector<HTMLElement>(':scope > .lil-children')
  if (!kids || !scroller) return
  let done = false
  const reveal = (): void => {
    if (done) return
    done = true
    kids.removeEventListener('transitionend', onEnd)
    clearTimeout(timer)
    if (changed._closed) return
    const box = changed.domElement.getBoundingClientRect()
    const view = scroller.getBoundingClientRect()
    // scroll by the part hidden below, but never past the folder's title
    const by = Math.min(box.bottom - view.bottom, box.top - view.top)
    if (by > 0) scroller.scrollTop += by
  }
  const onEnd = (e: TransitionEvent): void => {
    if (e.target === kids) reveal()
  }
  kids.addEventListener('transitionend', onEnd)
  const timer = setTimeout(reveal, REVEAL_FALLBACK_MS)
})

/**
 * Panels over the 3D view a fit keeps the model clear of. The bottom-right
 * stack counts child by child: its own box would also cover the empty corner
 * beside the narrower child. Hidden panels measure 0 x 0 and drop out. Not
 * here: the empty-screen card (hidden whenever a model is shown), the drop
 * zone and the note box (both transient).
 * A new overlay panel goes here and in e2e/nav_common.py PANELS.
 */
const FIT_PANELS: HTMLElement[] = [gui.domElement, treePanel, hud, measurePanel, propsEl, triadEl]
viewer.fitArea = () => {
  // The right-hand column sizes its panels from ResizeObservers, a frame
  // after a change (a folder opened, a load filled the lists); a fit reads
  // the panels now, so it lays the column out for what is in it first.
  layoutCorner()
  const c = viewer.renderer.domElement.getBoundingClientRect()
  if (c.width === 0 || c.height === 0) return null
  const panels: ScreenRect[] = []
  for (const el of FIT_PANELS) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) {
      panels.push({ left: r.left - c.left, top: r.top - c.top, right: r.right - c.left, bottom: r.bottom - c.top })
    }
  }
  return largestFreeRect(c.width, c.height, panels)
}

const propsFolder = gui.addFolder('体積・重量')
propsFolder.close()
/** folders that only make sense for a 3D model (hidden on 2D drawings) */
const folders3D = [viewFolder, sectionFolder, thicknessFolder, draftFolder, propsFolder]
const resinCtl = propsFolder
  .add(propsPrefs, 'resin', [...RESIN_NAMES, OTHER_RESIN])
  .name('樹脂')
  .onChange((r: string) => {
    // その他 keeps the current value: it is what the user typed
    if (r !== OTHER_RESIN) {
      propsPrefs.density = RESIN_DENSITY[r]
      densityCtl.updateDisplay()
    }
    applyDensity()
  })
// min without max: lil-gui draws a slider only when both are set. step 0.001
// keeps values like 1.185 as typed.
const densityCtl = propsFolder
  .add(propsPrefs, 'density')
  .min(0.001)
  .step(0.001)
  .name('比重 (g/cm³)')
  .onChange(() => {
    // a typed value that differs from the resin's own is その他. Never guess a
    // resin from the value (ABS and PS are both 1.05).
    if (propsPrefs.resin !== OTHER_RESIN && propsPrefs.density !== RESIN_DENSITY[propsPrefs.resin]) {
      propsPrefs.resin = OTHER_RESIN
      resinCtl.updateDisplay()
    }
    applyDensity()
  })
function applyDensity(): void {
  propsPanel.setDensity(propsPrefs.density, propsPrefs.resin)
  savePropsPrefs()
}
applyDensity()

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown }

function settled<T>(p: Promise<T>): Promise<Settled<T>> {
  return p.then(
    (value) => ({ ok: true as const, value }),
    (error) => ({ ok: false as const, error }),
  )
}

/** p's outcome if it settles within ms, else null. ms <= 0: only if it has already settled. */
function within<T>(p: Promise<T>, ms: number): Promise<T | null> {
  // already settled: p is first in the race, so its reaction runs first
  if (ms <= 0) return Promise.race([p, Promise.resolve(null)])
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<null>((r) => (timer = setTimeout(() => r(null), ms)))
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer))
}

/**
 * How long (ms from the request) a load waits for the 体積・重量 values
 * before its fit. The values set the panel's final size (a table row per
 * part, the totals, notes), and the one fit of a load must keep clear of
 * that size, not of the small 計算中… box: an end of a long part would slide
 * under the panel when it grows. Usually they come with the mesh; a slow
 * one (a big B-rep re-read after a backend restart) is not waited for past
 * this, and its panel may still grow after the fit. E2E sets it
 * (__cadPropsWait) so that a check never depends on timing.
 */
const PROPS_WAIT_MS = 1500
let propsWaitMs = PROPS_WAIT_MS

// Latest properties request wins. Not tied to loadGen: a replacement upload
// that fails before the teardown bumps loadGen but leaves the current model on
// screen, and that model's answer must still be shown (not 計算中… for good).
let propsRequest = 0
/**
 * Show the 体積・重量 panel for modelId from a request already in flight.
 * done: its outcome when that is already known (the panel gets its final
 * size now); otherwise 計算中… until it comes.
 */
function showProperties(
  modelId: string,
  req: Promise<Settled<ModelProperties>>,
  done: Settled<ModelProperties> | null,
): void {
  const n = ++propsRequest
  const apply = (r: Settled<ModelProperties>): void => {
    if (n !== propsRequest || modelId !== currentModelId) return // superseded
    if (r.ok) {
      propsPanel.setData(r.value)
      modelProps = r.value
      if (draftState.enabled) renderLegend() // the note on open parts may be due now
    } else {
      propsPanel.showError(r.error instanceof Error ? r.error.message : String(r.error))
    }
  }
  if (done) {
    apply(done)
  } else {
    propsPanel.showLoading()
    void req.then(apply)
  }
}

// ---- sidecar persistence (auto-save, debounced)
// The pending payload is captured eagerly (target id + an entries snapshot)
// rather than re-read inside the timer, so it can be flushed synchronously on
// teardown. Otherwise, switching models within the 800ms debounce window drops
// the last edit — the timer is cleared and clearAll() wipes the entries before
// anything is written to the OLD model's sidecar.
let saveTimer: ReturnType<typeof setTimeout> | undefined
let pendingSave: { id: string; body: unknown } | undefined
// The sidecar PUT currently being written. A teardown flush must await THIS —
// not just a queued pendingSave — because a debounce-timer flush may have
// already fired the PUT and cleared pendingSave. Without it, a same-id reload
// can getSidecar() before that write lands and restore stale data.
let inFlightSave: Promise<void> = Promise.resolve()

async function flushSidecar(): Promise<void> {
  if (saveTimer !== undefined) {
    clearTimeout(saveTimer)
    saveTimer = undefined
  }
  if (pendingSave) {
    const save = pendingSave
    pendingSave = undefined
    const prev = inFlightSave
    inFlightSave = (async () => {
      await prev.catch(() => {}) // preserve write ordering; ignore prior failure
      try {
        await putSidecar(save.id, save.body)
      } catch {
        /* best-effort autosave; a failed write must not block teardown */
      }
    })()
  }
  await inFlightSave
}

measureTool.onChange(() => {
  if (restoringOwner !== 0 || !currentModelId) return
  clearTimeout(saveTimer)
  pendingSave = { id: currentModelId, body: { version: 1, entries: measureTool.toJSON() } }
  saveTimer = setTimeout(() => void flushSidecar(), 800)
})

// ---- annotation input (small floating text box at the click point)
/** the note being typed, if any: a new load commits it first (to its own model) */
let openNote: { commit: () => void } | null = null
function promptAnnotation(screenX: number, screenY: number, at: THREE.Vector3): void {
  openNote?.commit()
  const modelAtPrompt = currentModelId
  const input = document.createElement('input')
  input.type = 'text'
  input.className = 'note-input'
  input.placeholder = '注記を入力しEnter'
  input.style.left = `${screenX}px`
  input.style.top = `${screenY}px`
  document.body.appendChild(input)
  input.focus()
  let closed = false
  const done = (commit: boolean) => {
    if (closed) return
    closed = true
    if (openNote === handle) openNote = null
    const text = input.value.trim()
    input.remove() // fires blur synchronously — guarded by `closed`
    // the point belongs to the model clicked: never put it on another one
    if (commit && text && currentModelId === modelAtPrompt) measureTool.addAnnotation(text, at)
  }
  const handle = { commit: () => done(true) }
  openNote = handle
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') done(true)
    else if (e.key === 'Escape') done(false)
  })
  // A click elsewhere keeps what was typed (it used to throw it away
  // silently); only Esc discards it.
  input.addEventListener('blur', () => done(true))
}

measureTool.onChange(() => {
  const entries = measureTool.list()
  measurePanel.classList.toggle('hidden', entries.length === 0)
  measureList.innerHTML = ''
  for (const e of entries) {
    const li = document.createElement('li')
    const span = document.createElement('span')
    span.textContent = e.label
    const del = document.createElement('button')
    del.textContent = '×'
    pressOnce(del, () => deleteWithUndo(() => measureTool.remove(e.id)))
    li.append(span, del)
    measureList.appendChild(li)
  }
})

// ---- undo the last deletion (× or 計測クリア)
// One step back: the list as it was before the deletion, for UNDO_MS or until
// the list changes otherwise (a new measurement, a model switch). A dialog
// would stop the hand on every delete; an undo keeps the work safe without it.
// Putting the list back makes the autosave write it again.
const UNDO_MS = 8000
const undoToast = document.querySelector<HTMLDivElement>('#undo-toast')!
const undoText = document.querySelector<HTMLSpanElement>('#undo-text')!
const undoBtn = document.querySelector<HTMLButtonElement>('#undo-btn')!
/** entries: the 3D list before the deletion; drawing: a drawing's measurements (markup) */
let undoState: { modelId: string; entries?: EntryData[]; drawing?: string } | null = null
let undoTimer: ReturnType<typeof setTimeout> | undefined
/** set while this code changes the list itself: those changes keep the undo */
let undoOwnChange = false

/**
 * A button of the measure list or the undo toast acts on mousedown and keeps
 * the focus where it is. On click it came too late: a note being typed loses
 * the focus on mousedown and commits, the list is drawn again, and the button
 * under the mouse is a new one by the mouseup, so the first click did nothing
 * (and a commit also ends the undo the click was meant to use). The keyboard
 * (Enter / Space on a focused button) still works through click.
 */
function pressOnce(btn: HTMLButtonElement, act: () => void): void {
  btn.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return // the middle and right buttons do nothing here
    ev.preventDefault() // no focus change: a note being typed stays open
    act()
  })
  btn.addEventListener('click', (ev) => {
    if (ev.detail === 0) act() // from the keyboard; a mouse click acted on mousedown
  })
}

function dropUndo(): void {
  undoState = null
  clearTimeout(undoTimer)
  undoToast.classList.add('hidden')
}

/** Run a deletion; afterwards offer to put back what it removed. */
function deleteWithUndo(run: () => void): void {
  const before = measureTool.toJSON()
  undoOwnChange = true
  try {
    run()
  } finally {
    undoOwnChange = false
  }
  const removed = before.length - measureTool.list().length
  if (removed <= 0 || !currentModelId) return
  armUndo({ modelId: currentModelId, entries: before }, removed)
}

/** 計測クリア on a drawing: its measurements live in the drawing's overlay */
function clearDrawingWithUndo(): void {
  const snap = drawing2d.measurementsSnapshot()
  drawing2d.clearMeasurements()
  if (!snap || !currentModelId) return
  armUndo({ modelId: currentModelId, drawing: snap.html }, snap.count)
}

function armUndo(state: NonNullable<typeof undoState>, removed: number): void {
  undoState = state
  undoText.textContent = `${removed} 件の計測を消した`
  undoToast.classList.remove('hidden')
  placeUndoToast()
  clearTimeout(undoTimer)
  undoTimer = setTimeout(dropUndo, UNDO_MS)
}

/** Put the list back as it was before the last deletion. Returns whether it did. */
function undoDelete(): boolean {
  const u = undoState
  if (!u || u.modelId !== currentModelId) return false
  dropUndo()
  if (u.drawing !== undefined) {
    drawing2d.restoreMeasurements(u.drawing)
    hudInfo.textContent = '計測を元に戻した'
    return true
  }
  if (!u.entries) return false
  undoOwnChange = true
  let failed = 0
  try {
    failed = measureTool.replaceAll(u.entries)
  } finally {
    undoOwnChange = false
  }
  hudInfo.textContent = `計測を元に戻した（${u.entries.length - failed} 件）`
  return true
}

// Just above the HUD, from its left edge: clear of the panels at the top and
// of the right-hand column, also on half a screen.
function placeUndoToast(): void {
  if (undoToast.classList.contains('hidden')) return
  const r = hud.getBoundingClientRect()
  undoToast.style.left = `${r.left}px`
  undoToast.style.bottom = `${window.innerHeight - r.top + 8}px`
}
window.addEventListener('resize', placeUndoToast)
new ResizeObserver(placeUndoToast).observe(hud) // the HUD grows with its text and the legends
pressOnce(undoBtn, () => void undoDelete())
measureTool.onChange(() => {
  if (!undoOwnChange) dropUndo()
})
// a new measurement on a drawing ends its undo too (as in 3D)
drawing2d.onMeasurement(dropUndo)

/**
 * Esc in 計測 / 注記: first drop a chosen first point, then leave the mode.
 * Returns whether it did anything (the key is then consumed).
 */
function escapeMeasure(): boolean {
  if (state.mode === '計測') {
    if (is2D) {
      if (drawing2d.cancelPending()) return true
    } else if (measureTool.hasPending) {
      measureTool.cancelPending()
      hudInfo.textContent = '1 点目を取り消した（もう一度 Esc で計測をやめる）'
      return true
    }
  }
  if (state.mode === 'なし') return false
  modeCtl.setValue('なし')
  hudInfo.textContent = thicknessHud || modelSummary
  return true
}

/** client (page) pixel -> normalized device coords of the 3D canvas */
function toNdc(clientX: number, clientY: number): THREE.Vector2 {
  const rect = viewer.renderer.domElement.getBoundingClientRect()
  return new THREE.Vector2(
    ((clientX - rect.left) / rect.width) * 2 - 1,
    -((clientY - rect.top) / rect.height) * 2 + 1,
  )
}

// Wheel zooms toward what is under the cursor, in both rotate modes. Captured on
// the container so neither OrbitControls nor TrackballControls sees it: their own
// wheel zoom goes toward the orbit target, and OrbitControls' zoomToCursor steps by
// the target distance, so it walks through a nearer surface.
const WHEEL_STEP = 0.9 // scale per 100 px of wheel delta (one Chrome notch), same as the + key
function wheelScale(e: WheelEvent): number {
  // line mode (Firefox): one notch is 3 lines, so 100/3 per line matches Chrome's 100 px notch
  let d = e.deltaY * (e.deltaMode === 1 ? 100 / 3 : e.deltaMode === 2 ? 100 : 1)
  if (e.ctrlKey) d *= 10 // a trackpad pinch arrives as ctrl+wheel with small deltas
  d = THREE.MathUtils.clamp(d, -300, 300) // one event never jumps more than ~3 notches
  return Math.pow(WHEEL_STEP, -d / 100)
}
function onViewportWheel(e: WheelEvent): void {
  e.preventDefault()
  e.stopPropagation()
  const scale = wheelScale(e)
  if (scale === 1) return
  // zoomAt picks after finishing a running pivot slide, in the pose it zooms from
  viewer.zoomAt(toNdc(e.clientX, e.clientY), scale, (ndc) => picker.surfacePoint(ndc))
}
viewport.addEventListener('wheel', onViewportWheel, { capture: true, passive: false })
// The triad's discs sit over the model: a wheel (or a trackpad pinch, which
// would zoom the whole page) there zooms at the cursor as over the canvas.
// Between the discs the triad lets events through to the canvas.
triadEl.addEventListener('wheel', onViewportWheel, { passive: false })

// click-to-pick (suppress when the user is orbiting)
let downAt: [number, number] | null = null
// Furthest the pointer got from where it was pressed, for the last two
// left-button presses: a double-click only counts when both were clicks. The
// furthest point, not the release point, so a drag that comes back to where it
// started (the view has turned) is not taken for a click.
let travel = 0
let clickTravels: [number, number] = [Infinity, Infinity]
// Only the primary pointer counts: a second finger (pinch) would otherwise
// overwrite where the first one went down.
viewport.addEventListener('pointerdown', (e) => {
  if (!e.isPrimary) return
  downAt = [e.clientX, e.clientY]
  travel = 0
})
viewport.addEventListener('pointermove', (e) => {
  if (e.isPrimary && downAt) travel = Math.max(travel, Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]))
})
viewport.addEventListener('pointerup', (e) => {
  if (!e.isPrimary || !downAt) return
  const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1])
  downAt = null
  if (e.button === 0) clickTravels = [clickTravels[1], Math.max(travel, moved)]
  if (state.mode === 'なし') return
  if (moved > DRAG_PX || measureTool.busy) return
  const ndc = toNdc(e.clientX, e.clientY)
  const pick = picker.pick(ndc)
  if (!pick) return

  if (state.mode === '注記') {
    promptAnnotation(e.clientX, e.clientY, pick.point)
    return
  }

  if (!measureTool.available) {
    hudInfo.textContent = '計測はSTEP/IGESモデルのみ（メッシュ形式に真値はない）'
    return
  }
  measureTool
    .handlePick(pick)
    .then((msg) => {
      if (msg) hudInfo.textContent = msg
    })
    .catch((err) => {
      hudInfo.textContent = `計測エラー: ${err instanceof Error ? err.message : err}`
    })
})

// Double-click (mode なし only: in 計測/注記 both clicks are picks) makes that
// surface point the rotation centre.
viewport.addEventListener('dblclick', (e) => {
  if (state.mode !== 'なし' || e.button !== 0 || Math.max(...clickTravels) > DRAG_PX) return
  const ndc = toNdc(e.clientX, e.clientY)
  viewer.prepareCamera()
  const p = picker.surfacePoint(ndc)
  if (p) viewer.orbitAround(p)
})

/** the part tree (top left), for a model with more than one part or with B-rep faces */
function showTree(model: ModelData): void {
  if (model.parts.length > 1 || model.parts[0]?.faceRanges.length) {
    renderTree(treeBody, model.tree, (partId, visible) => {
      viewer.setPartVisible(partId, visible)
      propsPanel.refresh()
    })
    treePanel.classList.remove('hidden')
  } else {
    treePanel.classList.add('hidden')
  }
}

function fmtBBox(meta: ModelMeta): string {
  const d = meta.bbox.max.map((v, i) => v - meta.bbox.min[i])
  return d.map((v) => v.toFixed(1)).join(' × ')
}

// generation token: a newer loadFile call supersedes older in-flight ones
let loadGen = 0

async function loadFile(file: File): Promise<void> {
  openNote?.commit() // the old model is still current: the flush below saves it
  const gen = ++loadGen
  hudInfo.textContent = `読み込み中: ${file.name} ...`

  try {
    const meta = await uploadModel(file)
    if (gen !== loadGen) return // superseded by a newer load

    // --- teardown of the previous model -----------------------------------
    // ORDER MATTERS (sidecar corruption hazard):
    // 1. FLUSH any pending debounced save to the OLD model and AWAIT it — for a
    //    deduped/same-id reload the PUT must land before the getSidecar() below,
    //    or the GET races ahead and restores a sidecar missing the just-entered
    //    edit (which a later save then persists over)
    // 2. restoring=true so teardown emits can't schedule new saves
    // 3. only then swap currentModelId and clear tools
    // a note opened while the upload ran still belongs to the old model
    openNote?.commit()
    await flushSidecar()
    if (gen !== loadGen) return // flush await yielded — a newer load may have won
    restoringOwner = gen
    try {
      currentModelId = meta.id
      measureTool.clearAll()
      thicknessCache.clear()
      thicknessState.enabled = false
      draftState.enabled = false // direction and angle stay
      viewer.clearVertexColors()
      colorOwner = 'none'
      shownThickness = null
      draftLegend.classList.add('hidden')
      thicknessLegend.classList.add('hidden')
      probe.stop()
      thicknessHud = ''
      modelSummary = ''
      modelProps = null
      propsPanel.hide()
      // Clear the stale 3D scene for BOTH branches: while the new model's
      // fetch is in flight (or if it fails), the old geometry must not stay
      // visible and pickable — clicks on it would be saved under the NEW
      // model's sidecar with the old model's coordinates.
      viewer.clearModel()
      // the old drawing goes too: if the new load fails below, the screen must
      // be really empty (not the old drawing, still interactive, under the card)
      drawing2d.clear()
      setContentShown(false)
      picker.setModel([])
      treeBody.replaceChildren()
      treePanel.classList.add('hidden')

      if (meta.format === 'drawing') {
        const d = meta.bbox2d
          ? meta.bbox2d.max.map((v, i) => (v - meta.bbox2d!.min[i]).toFixed(1)).join(' × ')
          : '?'
        modelSummary = `${meta.name} — 2D図面, ${d} (計測モードで端点/中心スナップ)`
        const svg = await fetchDrawingSvg(meta.id)
        if (gen !== loadGen) return
        sectionTool.enabled = false
        sectionTool.update()
        drawing2d.load(svg, meta.snapPoints ?? [])
        show2D(true)
        setContentShown(true, file.name)
        showEmpty(false)
        hudInfo.textContent = modelSummary
        return
      }

      show2D(false)
      // known from the upload already: the heatmap / draft can restore it at any
      // point of the load
      const partInfo = meta.partCount > 1 ? `${meta.partCount} parts, ` : ''
      modelSummary =
        `${meta.name} — ${partInfo}${meta.triangleCount.toLocaleString()} tris, ` +
        `サイズ ${fmtBBox(meta)} (単位はファイル依存)`
      // The mesh, the sidecar and the 体積・重量 values at once. The restored
      // measurement list and the values panel are panels the one fit of this
      // load must keep clear of, so both are wanted before the fit. (The
      // flush above has already landed, so the sidecar GET reads it.)
      const propsStart = performance.now()
      const propsReq = settled(fetchProperties(meta.id))
      // A sidecar that cannot be read is treated like a missing one: the model
      // still loads, and the HUD gives the reason. Mostly the backend's 500
      // for a saved file that is damaged (it keeps that file aside when the
      // next edit saves); also a network error or a body that is not JSON.
      let restoreProblem = ''
      const sidecarReq = getSidecar(meta.id).catch((e: unknown): Record<string, unknown> => {
        restoreProblem = `計測・注記を読み込めなかった（${e instanceof Error ? e.message : e}）`
        return {}
      })
      const pack = await fetchMesh(meta.id)
      if (gen !== loadGen) return
      const sidecar = await sidecarReq
      if (gen !== loadGen) return
      const props = await within(propsReq, propsWaitMs - (performance.now() - propsStart))
      if (gen !== loadGen) return
      const model = toModelData(pack)
      // No await from here to frameNewModel(): no frame is drawn before the
      // fit, so the view never jumps from a provisional framing to the final one
      viewer.setModel(model)
      try {
        setContentShown(true, file.name)
        showEmpty(false)
        picker.setModel(model.parts)
        measureTool.setModel(meta.id, meta.format === 'brep', new Map(model.parts.map((p) => [p.id, p.name])))
        sectionTool.setModelBBox(meta.bbox.min, meta.bbox.max)
        // restore persisted measurements / annotations
        const entries = Array.isArray(sidecar.entries) ? (sidecar.entries as EntryData[]) : []
        const skipped = entries.length ? measureTool.restore(entries) : 0
        if (skipped) restoreProblem = `保存された計測・注記のうち ${skipped} 件を復元できなかった`
        showTree(model)
        // after setModel: isPartVisible is ready for the values
        showProperties(meta.id, propsReq, props)

        // the note goes on the line once; the heatmap and the draft colouring
        // restore the plain summary
        hudInfo.textContent = modelSummary + (restoreProblem ? ` — ${restoreProblem}` : '')
      } finally {
        // Every panel of this load is on screen (the HUD text too: it sets
        // the HUD's size). E2E waits for this HUD text, set in this same task.
        // In a finally: should a step above throw, the model on screen is
        // still framed, not left at the previous model's camera.
        viewer.frameNewModel()
      }
    } finally {
      // release only our own claim: a newer load may have taken ownership
      if (restoringOwner === gen) restoringOwner = 0
    }
  } catch (e) {
    hudInfo.textContent = `エラー: ${e instanceof Error ? e.message : e}`
    if (gen === loadGen && !contentShown) {
      show2D(false) // back to the plain empty screen, as at start-up
      showEmpty(true)
    }
  }
}

// --- drag & drop ---
let dragDepth = 0
window.addEventListener('dragenter', (e) => {
  e.preventDefault()
  dragDepth++
  dropzone.classList.remove('hidden')
})
window.addEventListener('dragleave', () => {
  dragDepth--
  if (dragDepth <= 0) {
    dragDepth = 0
    dropzone.classList.add('hidden')
  }
})
window.addEventListener('dragover', (e) => e.preventDefault())
window.addEventListener('drop', (e) => {
  e.preventDefault()
  dragDepth = 0
  dropzone.classList.add('hidden')
  const file = e.dataTransfer?.files[0]
  if (file) void loadFile(file)
})

// E2E test hooks
const testHooks = window as unknown as Record<string, unknown>
testHooks.__cadProject = (x: number, y: number, z: number) => {
  viewer.prepareCamera() // correct straight after an event, before the next frame
  const v = new THREE.Vector3(x, y, z).project(viewer.camera)
  const rect = viewer.renderer.domElement.getBoundingClientRect()
  return {
    x: rect.left + ((v.x + 1) / 2) * rect.width,
    y: rect.top + ((1 - v.y) / 2) * rect.height,
  }
}
testHooks.__cadStallMeasure = (ms: number) => __stallNextMeasure(ms)
testHooks.__cadView = () => {
  viewer.prepareCamera() // the pose the next frame draws (parallel: the camera's depth)
  return {
    position: viewer.camera.position.toArray(),
    up: viewer.camera.up.toArray(),
    target: viewer.target.toArray(),
    rotateMode: viewer.rotateMode,
    gridVisible: viewer.gridVisible,
    // of the camera in use
    near: viewer.camera.near,
    far: viewer.camera.far,
    displayStyle: viewer.displayStyle,
    projection: viewer.projection,
    // parallel: visible half-height = 1 / zoom (perspective: always 1)
    zoom: viewer.camera.zoom,
  }
}
// WebGL resource counters of the last frame: a style switch must build no geometry
testHooks.__cadRenderInfo = () => {
  const info = viewer.renderer.info
  return { geometries: info.memory.geometries, programs: info.programs?.length ?? 0, calls: info.render.calls }
}
testHooks.__cadStallSidecar = (ms: number) => __stallNextSidecar(ms)
testHooks.__cadStallProperties = (ms: number) => __stallNextProperties(ms)
// how long a load waits for the 体積・重量 values before its fit (no argument: the app's own)
testHooks.__cadPropsWait = (ms?: number) => {
  propsWaitMs = ms ?? PROPS_WAIT_MS
}
testHooks.__cadPick = (clientX: number, clientY: number) => {
  viewer.prepareCamera()
  const r = picker.pick(toNdc(clientX, clientY))
  return r ? { partId: r.partId, kind: r.kind, id: r.id, point: r.point.toArray() } : null
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0]
  if (file) void loadFile(file)
  fileInput.value = ''
})
