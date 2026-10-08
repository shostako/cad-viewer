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
import { DRAFT_MAX_DEG, PULL_DIRS, PULL_DIR_OPTIONS, renderDraftLegend, type PullDir } from './draft'
import { Drawing2D } from './drawing2d'
import { largestFreeRect, type ScreenRect } from './freearea'
import { MeasureTool, type EntryData } from './measure'
import { toModelData, type ModelData } from './model'
import { Picker } from './picking'
import { OTHER_RESIN, PropertiesPanel, RESIN_DENSITY, RESIN_NAMES } from './properties'
import { SectionTool, type Axis } from './section'
import { canvasToPng, downloadBlob, pngFileName, type ExportBackground } from './snapshot'
import { renderTree } from './tree'
import { DRAG_PX, Viewer, type RotateMode, type ViewPreset } from './viewer'

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
  <div id="hud">
    <div id="hud-title">cad-viewer</div>
    <div id="draft-legend" class="hidden"></div>
    <div id="hud-info">ファイルをドロップ、または「ファイルを開く」から選ぶ</div>
    <div id="hud-keys"></div>
  </div>
  <input type="file" id="file-input" accept=".step,.stp,.iges,.igs,.stl,.3mf,.obj,.ply,.dxf,.dwg" hidden />
`

const viewport = document.querySelector<HTMLDivElement>('#viewport')!
const dropzone = document.querySelector<HTMLDivElement>('#dropzone')!
const hud = document.querySelector<HTMLDivElement>('#hud')!
const hudInfo = document.querySelector<HTMLDivElement>('#hud-info')!
const draftLegend = document.querySelector<HTMLDivElement>('#draft-legend')!
const fileInput = document.querySelector<HTMLInputElement>('#file-input')!
const treePanel = document.querySelector<HTMLDivElement>('#tree-panel')!
const treeBody = document.querySelector<HTMLDivElement>('#tree-body')!

const hud = document.querySelector<HTMLDivElement>('#hud')!
const cornerBr = document.querySelector<HTMLDivElement>('#corner-br')!
const measurePanel = document.querySelector<HTMLDivElement>('#measure-panel')!
const measureList = document.querySelector<HTMLUListElement>('#measure-list')!

const viewport2d = document.querySelector<HTMLDivElement>('#viewport2d')!
const hudKeys = document.querySelector<HTMLDivElement>('#hud-keys')!
const emptyHint = document.querySelector<HTMLDivElement>('#empty-hint')!
document.querySelector('#empty-open')!.addEventListener('click', () => fileInput.click())
const propsEl = document.querySelector<HTMLDivElement>('#props-panel')!

const viewer = new Viewer(viewport)
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
}

/** whether a model or drawing is on screen, and its file name (for the PNG export) */
function setContentShown(on: boolean, fileName = ''): void {
  contentShown = on
  shownFileName = on ? fileName : ''
  savePngCtl.enable(on)
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
  clearMeasure: () => {
    measureTool.clearAll()
    drawing2d.clearMeasurements()
  },
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
}
try {
  const saved = JSON.parse(localStorage.getItem(VIEW_PREFS_KEY) ?? '{}')
  if (typeof saved.grid === 'boolean') viewPrefs.grid = saved.grid
  if (typeof saved.speed === 'number') viewPrefs.speed = saved.speed
  if (saved.rotateMode === 'turntable' || saved.rotateMode === 'free') viewPrefs.rotateMode = saved.rotateMode
} catch {
  /* defaults */
}
function saveViewPrefs(): void {
  try {
    // auto-rotate is deliberately not remembered: a model that starts spinning
    // on open is a surprise, not a preference
    const { grid, speed, rotateMode } = viewPrefs
    localStorage.setItem(VIEW_PREFS_KEY, JSON.stringify({ grid, speed, rotateMode }))
  } catch {
    /* best-effort */
  }
}
viewer.gridVisible = viewPrefs.grid
viewer.autoRotateSpeed = viewPrefs.speed
viewer.setRotateMode(viewPrefs.rotateMode)

const viewFolder = gui.addFolder('表示')
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
  if (isTextEntry(e.target) || e.ctrlKey || e.metaKey || e.altKey) return
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
const thicknessState = { enabled: false, threshold: 1.5, method: 'ray' as 'ray' | 'ball' }
const thicknessCache = new Map<string, Map<number, Float32Array>>()
async function updateThickness(): Promise<void> {
  if (!currentModelId) return
  if (!thicknessState.enabled) {
    releaseColors('thickness')
    dropThicknessHud()
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
    setThicknessHud(
      `肉厚ヒートマップ表示中（${requestedMethod === 'ball' ? 'ローリングボール法' : 'レイ法'}、赤=閾値未満）`,
    )
  } catch (e) {
    if (requestedGen !== loadGen || requestedId !== currentModelId) return // stale failure
    // the user moved on (抜き勾配 took over, toggled off, other 方式): a late error is noise
    if (!thicknessState.enabled || requestedMethod !== thicknessState.method) return
    thicknessHud = ''
    thicknessState.enabled = false
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
    return
  }
  viewer.setDraftColors(PULL_DIRS[draftState.dir], draftState.required)
  colorOwner = 'draft'
  renderLegend()
  draftLegend.classList.remove('hidden')
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
      releaseColors('thickness')
      dropThicknessHud()
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
const FIT_PANELS: HTMLElement[] = [gui.domElement, treePanel, hud, measurePanel, propsEl]
viewer.fitArea = () => {
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

// Latest properties request wins. Not tied to loadGen: a replacement upload
// that fails before the teardown bumps loadGen but leaves the current model on
// screen, and that model's answer must still be shown (not 計算中… for good).
let propsRequest = 0
async function updateProperties(modelId: string): Promise<void> {
  const req = ++propsRequest
  propsPanel.showLoading()
  try {
    const p = await fetchProperties(modelId)
    if (req !== propsRequest || modelId !== currentModelId) return // superseded
    propsPanel.setData(p)
    modelProps = p
    if (draftState.enabled) renderLegend() // the note on open parts may be due now
  } catch (e) {
    if (req !== propsRequest || modelId !== currentModelId) return
    propsPanel.showError(e instanceof Error ? e.message : String(e))
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
function promptAnnotation(screenX: number, screenY: number, at: THREE.Vector3): void {
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
    const text = input.value.trim()
    input.remove() // fires blur synchronously — guarded by `closed`
    if (commit && text) measureTool.addAnnotation(text, at)
  }
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') done(true)
    else if (e.key === 'Escape') done(false)
  })
  input.addEventListener('blur', () => done(false))
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
    del.addEventListener('click', () => measureTool.remove(e.id))
    li.append(span, del)
    measureList.appendChild(li)
  }
})

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
viewport.addEventListener(
  'wheel',
  (e) => {
    e.preventDefault()
    e.stopPropagation()
    const scale = wheelScale(e)
    if (scale === 1) return
    // zoomAt picks after finishing a running pivot slide, in the pose it zooms from
    viewer.zoomAt(toNdc(e.clientX, e.clientY), scale, (ndc) => picker.surfacePoint(ndc))
  },
  { capture: true, passive: false },
)

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
  viewer.camera.updateMatrixWorld()
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
      draftLegend.classList.add('hidden')
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
      // Both GETs at once: the restored measurement list is a panel the one
      // fit of this load must keep clear of, so the sidecar is needed before
      // the fit. (The flush above has already landed, so the GET reads it.)
      const sidecarReq = getSidecar(meta.id)
      // awaited below; this only stops an unhandled rejection if the mesh fails first
      sidecarReq.catch(() => {})
      const pack = await fetchMesh(meta.id)
      if (gen !== loadGen) return
      const sidecar = await sidecarReq
      if (gen !== loadGen) return
      const model = toModelData(pack)
      // No await from here to frameNewModel(): no frame is drawn before the
      // fit, so the view never jumps from a provisional framing to the final one
      viewer.setModel(model)
      setContentShown(true, file.name)
      showEmpty(false)
      picker.setModel(model.parts)
      measureTool.setModel(meta.id, meta.format === 'brep')
      sectionTool.setModelBBox(meta.bbox.min, meta.bbox.max)
      // restore persisted measurements / annotations
      const entries = (sidecar.entries ?? []) as EntryData[]
      if (entries.length) measureTool.restore(entries)
      showTree(model)
      // after setModel: isPartVisible is ready when the values arrive. They
      // always arrive after the fit below (a later task), which does not wait
      // for them: the panel shows 計算中… at the fit and is not re-framed.
      void updateProperties(meta.id)

      hudInfo.textContent = modelSummary
      // every panel of this load is on screen (the HUD text too: it sets the
      // HUD's size). E2E waits for this HUD text, set in this same task.
      viewer.frameNewModel()
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
  viewer.camera.updateMatrixWorld() // correct straight after an event, before the next frame
  const v = new THREE.Vector3(x, y, z).project(viewer.camera)
  const rect = viewer.renderer.domElement.getBoundingClientRect()
  return {
    x: rect.left + ((v.x + 1) / 2) * rect.width,
    y: rect.top + ((1 - v.y) / 2) * rect.height,
  }
}
testHooks.__cadStallMeasure = (ms: number) => __stallNextMeasure(ms)
testHooks.__cadView = () => ({
  position: viewer.camera.position.toArray(),
  up: viewer.camera.up.toArray(),
  target: viewer.target.toArray(),
  rotateMode: viewer.rotateMode,
  gridVisible: viewer.gridVisible,
  near: viewer.camera.near,
  far: viewer.camera.far,
})
testHooks.__cadStallSidecar = (ms: number) => __stallNextSidecar(ms)
testHooks.__cadStallProperties = (ms: number) => __stallNextProperties(ms)
testHooks.__cadPick = (clientX: number, clientY: number) => {
  viewer.camera.updateMatrixWorld()
  const r = picker.pick(toNdc(clientX, clientY))
  return r ? { partId: r.partId, kind: r.kind, id: r.id, point: r.point.toArray() } : null
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0]
  if (file) void loadFile(file)
  fileInput.value = ''
})
