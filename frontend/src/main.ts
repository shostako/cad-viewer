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
import { CursorTip, HoverProbe, type TipContent } from './cursortip'
import { DRAFT_MAX_DEG, PULL_DIRS, PULL_DIR_OPTIONS, draftTipText, renderDraftLegend, type PullDir } from './draft'
import { Drawing2D, type Measurement2D } from './drawing2d'
import { fitRect, type ScreenRect } from './freearea'
import { KeyHelp } from './help'
import { ICON, icon } from './icons'
import { LoadCard, failureReason, type LoadStep } from './loadcard'
import { MeasureTool, type EntryData } from './measure'
import { copyText, drawingRow, entryRow, listText, rowElement, type RowView } from './measurelist'
import { toModelData, type ModelData } from './model'
import { Picker, type FaceHit, type PickResult } from './picking'
import { DiameterCache, Preselect } from './preselect'
import { OTHER_RESIN, PropertiesPanel, RESIN_DENSITY, RESIN_NAMES } from './properties'
import { SectionTool, type Axis } from './section'
import { canvasToPng, downloadBlob, pngFileName, type ExportBackground } from './snapshot'
import { METHOD_NAMES, renderThicknessLegend, thicknessAt, thicknessTipText, type ThicknessMethod } from './thickness'
import { PartTree } from './tree'
import { Toolbar, type Mode } from './toolbar'
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
    <div id="empty-formats" aria-label="開ける形式">${['STEP', 'IGES', 'STL', '3MF', 'OBJ', 'PLY', 'DXF', 'DWG']
      .map((f) => `<span>${f}</span>`)
      .join('')}</div>
  </div>
  <div id="load-card" class="hidden"></div>
  <div id="tree-panel" class="hidden"></div>
  <div id="toolbar"></div>
  <div id="corner-br">
    <div id="measure-panel" class="hidden">
      <div id="measure-head">
        <span id="measure-title">計測</span>
        <span id="measure-count"></span>
        <button id="measure-copy-all" type="button" title="すべてコピー（Excel に貼れる形: 種類・値・単位・対象 A・対象 B）"></button>
      </div>
      <ul id="measure-list"></ul>
    </div>
    <div id="props-panel" class="hidden"></div>
  </div>
  <div id="triad" class="hidden"></div>
  <div id="hud">
    <div id="draft-legend" class="hidden"></div>
    <div id="thickness-legend" class="hidden"></div>
    <div id="hud-line">
      <div id="hud-info">ファイルをドロップするか、「ファイルを選ぶ」で開く</div>
      <button id="help-open" type="button" title="キー操作の一覧（?）" aria-label="キー操作の一覧">?</button>
    </div>
  </div>
  <div id="help-card" class="hidden"></div>
  <button id="panels-show" class="hidden" type="button" title="パネルを出す（H）">パネルを出す</button>
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
const toolbarEl = document.querySelector<HTMLDivElement>('#toolbar')!

const cornerBr = document.querySelector<HTMLDivElement>('#corner-br')!
const measurePanel = document.querySelector<HTMLDivElement>('#measure-panel')!
const measureList = document.querySelector<HTMLUListElement>('#measure-list')!

const viewport2d = document.querySelector<HTMLDivElement>('#viewport2d')!
const emptyHint = document.querySelector<HTMLDivElement>('#empty-hint')!
document.querySelector('#empty-open')!.addEventListener('click', () => fileInput.click())
// a failed load's card stands in for the open card until it is closed
const loadCardEl = document.querySelector<HTMLDivElement>('#load-card')!
const loadCard = new LoadCard(
  loadCardEl,
  () => fileInput.click(),
  () => {
    if (!contentShown) showEmpty(true)
  },
  placeCentreCards,
)
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
// the part tree (top left): shows / hides parts, highlights the part of the
// row under the pointer, fits the view to one part
const partTree = new PartTree(treePanel, {
  setVisible: (changes) => {
    for (const [id, on] of changes) viewer.setPartVisible(id, on)
    propsPanel.refresh()
    probe.refresh() // a part under a still cursor may have gone (its row mark, its value)
  },
  highlight: (ids) => viewer.setHighlight(ids),
  zoomTo: (ids) => viewer.fitToParts(ids),
  colorOf: (id) => `#${viewer.partColor(id)?.getHexString() ?? '8fb4d8'}`,
})

// what the mouse and the keys do (? or the ? at the end of the status line):
// a card above the status line, which used to carry these lines all the time
const helpCard = document.querySelector<HTMLDivElement>('#help-card')!
const keyHelp = new KeyHelp(helpCard, document.querySelector<HTMLButtonElement>('#help-open')!, (on) => {
  if (on) placeHelp()
})

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
  treePanel.classList.toggle('hidden', on || !partTree.hasRows)
  for (const f of folders3D) f.show(!on)
  const note = [...modeSelect.options].find((o) => o.text === '注記')
  if (note) note.disabled = on
  if (on && state.mode === '注記') modeCtl.setValue('なし')
  keyHelp.setView(on)
  updateTriad()
  refreshToolbar()
}

/** whether a model or drawing is on screen, and its file name (for the PNG export) */
function setContentShown(on: boolean, fileName = ''): void {
  contentShown = on
  shownFileName = on ? fileName : ''
  updateTriad()
  refreshToolbar()
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
  applyFolders(on)
  placeCentreCards()
}

/** room kept between a centre card and the operation panel, and the window's edge */
const CARD_MARGIN = 16
/**
 * The cards in the middle (the open card, the load card) go in the middle of
 * the part of the window left of the operation panel, so that the panel never
 * covers them (on half a screen it would cover a third of a card in the
 * window's middle). Too narrow a part for the card: the middle of the window,
 * over the panel. Vertically always the middle of the window.
 */
function placeCentreCards(): void {
  const panel = gui.domElement.getBoundingClientRect()
  for (const card of [emptyHint, loadCardEl]) {
    if (card.classList.contains('hidden')) continue
    const w = card.offsetWidth
    const roomLeft = panel.width > 0 ? panel.left : window.innerWidth
    const fits = roomLeft >= w + 2 * CARD_MARGIN
    card.style.left = `${fits ? roomLeft / 2 : window.innerWidth / 2}px`
    card.classList.toggle('over-panel', !fits)
  }
}
window.addEventListener('resize', placeCentreCards)
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
/** the toolbar (made once the GUI's controls exist; refreshToolbar waits for it) */
let toolbar: Toolbar | null = null
const state = { mode: 'なし' as 'なし' | '計測' | '注記' }
const actions = {
  open: () => fileInput.click(),
  // 3D keeps the view direction and fits the visible parts; 2D fits the whole drawing
  fit: () => (is2D ? drawing2d.fit() : viewer.fitToView()),
  // both can be undone: the 3D list, or a drawing's measurements
  clearMeasure: () => {
    if (is2D) deleteDrawingWithUndo(() => drawing2d.clearMeasurements())
    else deleteWithUndo(() => measureTool.clearAll()) // drops a chosen first point too
    // a line asking for that point's partner is stale: back to the mode's hint
    if (modeHud && hudInfo.textContent === modeHud) showModeHint()
  },
  // a function declaration below, so it is hoisted
  savePng: () => void savePng(),
}
// ファイルを開く, 全体表示 and 画像を保存 are on the toolbar (and the empty
// screen's card, F, the drop): the panel keeps what the toolbar has not
const modeCtl = gui
  .add(state, 'mode', ['なし', '計測', '注記'])
  .name('モード')
  .onChange((mode: string) => {
    if (mode !== '計測') measureTool.cancelPending()
    drawing2d.measureMode = mode === '計測'
    viewport.style.cursor = mode === 'なし' ? '' : 'crosshair'
    viewport2d.style.cursor = mode === '計測' ? 'crosshair' : ''
    showModeHint()
    // the highlight, the label and the tree's row mark follow the mode at
    // once, also under a still cursor (a hover pick waiting after a slow one
    // looks again now: its last label must not come back without its highlight)
    forgetHoverPick()
    probe.refresh()
    refreshToolbar()
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
// folded at first: the toolbar switches the style (W), and the column is
// short on half a screen. The folder memory keeps it the way the user leaves it.
viewFolder.close()
// "Pick a style, then turn the model to look" works without blurring the
// select: the arrows turn the view even while a GUI dropdown has the focus
// (isTextEntry), and never step its options.
const STYLE_NAMES: Record<DisplayStyle, string> = {
  'shaded-edges': '陰影＋稜線',
  shaded: '陰影のみ',
  wireframe: 'ワイヤーフレーム',
  xray: '半透明',
}
const styleCtl = viewFolder
  .add(viewPrefs, 'style', Object.fromEntries(DISPLAY_STYLES.map((v) => [STYLE_NAMES[v], v])))
  .name('表示スタイル')
  .onChange((v: DisplayStyle) => {
    viewer.setDisplayStyle(v)
    saveViewPrefs()
    refreshHeatmapHud()
    refreshToolbar()
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
  .onChange((v: boolean) => {
    viewer.autoRotate = v
    speedCtl.show(v)
  })
// the speed matters only while turning: shown with 自動回転 on (a row less in
// the column on half a screen; auto-rotate always starts off)
const speedCtl = viewFolder
  .add(viewPrefs, 'speed', 5, 120, 1)
  .name('回転速度 (°/秒)')
  .onChange((v: number) => {
    viewer.autoRotateSpeed = v
    saveViewPrefs()
  })
speedCtl.show(viewPrefs.autoRotate)
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
// the seven buttons in rows of four (style.css): a row each took seven rows of
// the column on half a screen. Their names stay (the E2E finds them by name).
presetFolder.domElement.classList.add('cv-views')
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
    // a card first (the key list, a failed load's): it is what the eye is on
    if (keyHelp.shown) {
      keyHelp.show(false)
      e.preventDefault()
    } else if (loadCard.failed) {
      loadCard.close()
      e.preventDefault()
    } else if (escapeMeasure()) e.preventDefault()
    return
  }
  if (e.key === '?') {
    if (!e.repeat) keyHelp.show(!keyHelp.shown)
    e.preventDefault()
    return
  }
  // the toolbar's keys (a letter typed into a note never comes here: isTextEntry)
  const letter = e.key.length === 1 ? e.key.toLowerCase() : ''
  if (letter === 'm' || letter === 'n' || letter === 's' || letter === 'w') {
    if (!e.repeat) toolbarKey(letter)
    e.preventDefault()
    return
  }
  if (e.key === 'h' || e.key === 'H') {
    // one toggle per press: a held key's auto-repeat would flash the panels
    if (!e.repeat) setPanelsHidden(!panelsHidden)
    e.preventDefault()
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
  .onChange((on: boolean) => {
    // put in: the side the camera is on goes, the cut faces the camera
    if (on) sectionTool.faceCamera(viewer.camera.position)
    sectionTool.update()
    refreshToolbar()
  })
sectionFolder
  .add(sectionTool, 'axis', ['X', 'Y', 'Z'] as Axis[])
  .name('軸')
  .onChange(() => {
    // from the middle of the model along the new axis (a fraction carried over
    // reads as an odd number of mm), the cut toward the camera
    sectionTool.position = 0.5
    sectionTool.faceCamera(viewer.camera.position)
    sectionRange()
    sectionTool.update()
  })
// in the model's units (mm) along the axis, over the model's extent
const sectionPosCtl = sectionFolder
  .add(sectionTool, 'mm', 0, 1, 0.01)
  .name('位置 (mm)')
  .onChange(() => sectionTool.update())
/** the position's slider spans the model along the section's axis */
function sectionRange(): void {
  const [lo, hi] = sectionTool.range()
  sectionPosCtl.min(lo).max(hi > lo ? hi : lo + 1)
  sectionPosCtl.updateDisplay()
}
sectionFolder
  .add(sectionTool, 'flip')
  .name('反転')
  .listen() // 有効 and 軸 set it toward the camera
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
// The status line in 計測 / 注記 says what the next click does: the first
// point, then (after it, from the click) its partner. When the mode goes, a
// line that only told what to click goes too, back to the line under it (the
// heatmap's or the model's); a result (距離 ...) stays. 2D drawings keep their
// own lines (drawing2d.ts).
const MEASURE_HINT = '計測: クリックで 1 点目（Esc でやめる）'
const MEASURE_MESH_HINT = '計測はSTEP/IGESモデルのみ（メッシュ形式に真値はない）'
const NOTE_HINT = '注記: クリックした点に注記を付ける（Esc でやめる）'
/** the last 計測 / 注記 line that only says what to click; '' when none is shown */
let modeHud = ''
/** the line the hint was added to (a load's summary), to go back to; '' for the usual one */
let modeBase = ''
/** base: the line the hint was added to, to go back to ('' for the usual one) */
function setModeHud(text: string, base = ''): void {
  modeHud = text
  modeBase = base
  hudInfo.textContent = text
}
/** what the mode asks the next click for ('' in なし) */
function modeHint(): string {
  if (state.mode === '計測') return measureTool.available ? MEASURE_HINT : MEASURE_MESH_HINT
  if (state.mode === '注記') return NOTE_HINT
  return ''
}
function showModeHint(): void {
  if (modeHud && hudInfo.textContent === modeHud) hudInfo.textContent = modeBase || thicknessHud || modelSummary
  modeHud = ''
  modeBase = ''
  // a 3D model on screen (not the empty screen, a load or a drawing)
  if (!contentShown || is2D) return
  const hint = modeHint()
  if (hint) setModeHud(hint)
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

// ---- what is under the cursor (#cursor-tip, the preselection highlight, the part tree's row)
// One look per frame at most (HoverProbe). In 計測 / 注記 (3D), what a click
// there would pick is highlighted and named beside the cursor
// (pickUnderCursor). Otherwise one ray serves two uses: in なし the part under
// the cursor has its row marked in the part tree, and while the heatmap or the
// draft colouring is on, the label says what the colour under the cursor
// stands for (valueAt). Where a click would pick a B-rep entity in 計測 /
// 注記, its name wins over the value: a measurement aims at an entity, and one
// label stays readable. Where it would not (a mesh model, a measurement in
// flight), the value shows as in なし.
const cursorTip = new CursorTip(document.body)
const probe = new HoverProbe(viewport, cursorTip, underCursor)
const preselect = new Preselect(viewer)
// an answer for the entity under a still cursor: its label gets the ⌀ now
const diameters = new DiameterCache(() => probe.refresh())
probe.onStop(() => {
  preselect.hide()
  diameters.rest(null)
  lastPickTip = null
  clearTimeout(hoverPickTimer)
  partTree.markFrom3D(null)
})
function underCursor(clientX: number, clientY: number): TipContent {
  if (state.mode !== 'なし' && !is2D && contentShown) {
    const picked = pickUnderCursor(clientX, clientY)
    if (picked !== null) {
      partTree.markFrom3D(null) // 計測 / 注記 point at faces, edges and vertices, not at parts
      return picked
    }
  } else lastPickTip = null
  preselect.hide()
  diameters.rest(null)
  // 計測 / 注記 point at faces, edges and vertices, not at parts: the row mark is for なし
  const markRow = !is2D && state.mode === 'なし' && partTree.hasRows
  const giveValue = !is2D && colorOwner !== 'none'
  const hit = markRow || giveValue ? picker.faceHit(toNdc(clientX, clientY)) : null
  partTree.markFrom3D(markRow && hit ? hit.partId : null)
  return giveValue ? valueAt(hit) : null
}
/**
 * In 半透明 / ワイヤーフレーム a pick scans every drawn edge and vertex
 * (Picker.snapDrawnLines). Once per click that is fine; on hover it could run
 * on every frame (the cursor moves, the view turns), and on a model with many
 * edges each scan takes milliseconds. So in those styles the hover waits after
 * each pick HOVER_PICK_WAIT times as long as the pick took (a pick of 1 ms:
 * every frame; of 25 ms: every 125 ms, a fifth of the time), shows the last
 * pick meanwhile, and looks at where the cursor is when the wait is over.
 */
const HOVER_PICK_WAIT = 4
let hoverPickReady = 0
let hoverPickTimer: ReturnType<typeof setTimeout> | undefined
/** what the last hover pick showed (kept on screen while the next one waits) */
let lastPickTip: TipContent = null
/** the highlight goes, and the next hover looks at once (no wait, no last label) */
function forgetHoverPick(): void {
  preselect.hide()
  lastPickTip = null
  hoverPickReady = 0
  clearTimeout(hoverPickTimer)
}
/**
 * 計測 / 注記: the pick a click here would make (the click's own call,
 * picker.pick at this point with the same snap radii), highlighted, and its
 * name as the measure list gives it, with the exact ⌀ of a circular edge or a
 * cylindrical face once the backend has told it. null (no highlight) where a
 * click picks no B-rep entity: off the model, while a measurement is in flight
 * (busy: the click is dropped), in 計測 on a mesh model (the click only says
 * it cannot measure), on a face of a mesh model (no entity to show).
 */
function pickUnderCursor(clientX: number, clientY: number): TipContent {
  const live = !measureTool.busy && (state.mode === '注記' || measureTool.available)
  let pick: PickResult | null = null
  if (live) {
    const now = performance.now()
    if (viewer.seeThrough && now < hoverPickReady) {
      clearTimeout(hoverPickTimer)
      hoverPickTimer = setTimeout(() => probe.refresh(), hoverPickReady - now)
      return lastPickTip
    }
    pick = picker.pick(toNdc(clientX, clientY))
    const end = performance.now()
    hoverPickReady = viewer.seeThrough ? end + HOVER_PICK_WAIT * (end - now) : 0
  }
  lastPickTip = pickTip(pick)
  return lastPickTip
}
function pickTip(pick: PickResult | null): TipContent {
  if (!pick || pick.id < 1) return null // the caller hides the highlight
  preselect.show(pick, state.mode === '計測' ? measureTool.pendingPoint : null)
  if (!preselect.shown) return null
  diameters.rest(pick)
  const d = diameters.get(pick)
  return { text: measureTool.label(pick) + (d === null ? '' : ` ⌀${d.toFixed(3)}`), kind: 'pick' }
}
// The value: the thickness, or the draft angle and its class. Read from the
// triangle under the cursor by the rule that coloured it (the same vertex
// values, the same normals), so the number says what the colour says; where
// the colours blur across a triangle (a large face between thin and thick
// vertices, a curved B-rep face), it gives the value at that very point.
function valueAt(hit: FaceHit | null): string | null {
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
const COLUMN_MARGIN = 12 // #corner-br's distance from the bottom (style.css --cv-edge)
const COLUMN_GAP = 8
/**
 * The measure list's least height: its title and its first two rows whole
 * (a row wraps to two lines within the column's one width: about the room
 * three one-line rows took before). Measured, not a constant: the rows'
 * height depends on the text and the font.
 */
function measureMinPx(): number {
  const cs = getComputedStyle(measurePanel)
  const frame =
    parseFloat(cs.paddingTop) +
    parseFloat(cs.paddingBottom) +
    parseFloat(cs.borderTopWidth) +
    parseFloat(cs.borderBottomWidth)
  // the head: 計測, the count and すべてコピー
  const head = measurePanel.querySelector<HTMLElement>('#measure-head')
  const titleH = head ? head.offsetHeight + parseFloat(getComputedStyle(head).marginBottom) : 0
  let rows = 0
  for (const li of Array.from(measureList.children).slice(0, 2)) rows += (li as HTMLElement).offsetHeight
  return Math.ceil(frame + titleH + rows)
}
// below this the GUI stops giving way: its title and about five rows (the
// toolbar above it took 44 px of the column, and the column's least height
// stays about what it was)
const GUI_MIN_PX = 160
const HUD_MIN_PX = 200 // below this the HUD stops wrapping and may meet the stack
function layoutCorner(): void {
  const h = window.innerHeight
  const measureShown = !measurePanel.classList.contains('hidden')
  // natural height: content and padding (scrollHeight) plus the border
  const measureNatural = measurePanel.scrollHeight + measurePanel.offsetHeight - measurePanel.clientHeight
  const measureMin = measureShown ? Math.min(measureNatural, measureMinPx()) : 0
  const propsMin = propsPanel.minHeight()
  const stackMin = measureMin + propsMin + (measureMin && propsMin ? COLUMN_GAP : 0)
  // the GUI sits COLUMN_MARGIN below the window's top, as the stack sits above its bottom
  const guiTop = gui.domElement.getBoundingClientRect().top
  const guiMax = Math.max(h - guiTop - COLUMN_MARGIN - COLUMN_GAP - stackMin, GUI_MIN_PX)
  // never taller than the window (GUI_MIN_PX can exceed a tiny one)
  gui.domElement.style.maxHeight = stackMin ? `${Math.min(guiMax, h - guiTop)}px` : ''
  const room = h - COLUMN_MARGIN - (gui.domElement.getBoundingClientRect().bottom + COLUMN_GAP)
  const propsShare = propsMin ? propsMin + COLUMN_GAP : 0
  measurePanel.style.maxHeight = `${Math.max(Math.min(0.4 * h, room - propsShare), measureMin)}px`
  const measureUsed = measureShown ? measurePanel.getBoundingClientRect().height + COLUMN_GAP : 0
  propsPanel.fitHeight(room - measureUsed)
  // the HUD (bottom left) wraps its lines rather than run under the right-hand
  // column on a narrow window (half a screen)
  const hudLeft = hud.getBoundingClientRect().left
  hud.style.maxWidth = `${Math.max(columnLeft() - COLUMN_GAP - hudLeft, HUD_MIN_PX)}px`
  placeHelp()
}
/**
 * Where the right-hand column starts: at the GUI or at the stack, whichever
 * reaches further left (the stack is as wide as its widest panel).
 */
function columnLeft(): number {
  // (a hidden GUI or stack measures 0 x 0 at the origin: not a left edge)
  const lefts = [gui.domElement, cornerBr].map((el) => el.getBoundingClientRect()).filter((r) => r.width > 0)
  return lefts.length ? Math.min(...lefts.map((r) => r.left)) : window.innerWidth - COLUMN_MARGIN
}
/** the smallest room the key list is squeezed into (it scrolls below this) */
const HELP_MIN_PX = 160
/**
 * The key list sits above the status line and the axis triad, from the
 * window's left edge to the right-hand column (like the status line, never
 * under the column). Placed again when any of them moves or grows.
 */
function placeHelp(): void {
  if (!keyHelp.shown) return
  const tops = [hud, triadEl].map((el) => el.getBoundingClientRect()).filter((r) => r.height > 0)
  const above = Math.min(...tops.map((r) => r.top))
  helpCard.style.bottom = `${window.innerHeight - above + COLUMN_GAP}px`
  helpCard.style.maxHeight = `${Math.max(above - COLUMN_GAP - COLUMN_MARGIN, HELP_MIN_PX)}px`
  helpCard.style.maxWidth = `${Math.max(columnLeft() - COLUMN_GAP - COLUMN_MARGIN, HELP_MIN_PX)}px`
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
// the panel's left edge sets where the centre cards go (also when it hides)
new ResizeObserver(() => placeCentreCards()).observe(gui.domElement)
new ResizeObserver(queueLayoutCorner).observe(measurePanel)
new ResizeObserver(queueLayoutCorner).observe(measureList)
// the status line grows and shrinks with its text (and the legends above it)
new ResizeObserver(() => placeHelp()).observe(hud)
window.addEventListener('resize', layoutCorner)
placeCentreCards() // the open card, now that the operation panel is in place
// When the GUI has had to give way (it scrolls), bring a folder the user just
// opened into view once lil-gui's opening animation (300 ms) ends. A timer
// backs up the transitionend: with no transition (nothing to animate, reduced
// motion) the event never comes, and the listener must not stay behind.
const REVEAL_FALLBACK_MS = 450
// ---- the folders are left the way the user left them (表示 and 視点 start
// open, the rest closed), across reloads. On the empty screen they are all
// folded (nothing to set yet: the open card is what matters); a model or a
// drawing brings them back.
const FOLDERS_KEY = 'cad-viewer:folders'
const savedFolders: Record<string, boolean> = {}
try {
  const saved = JSON.parse(localStorage.getItem(FOLDERS_KEY) ?? '{}')
  for (const [k, v] of Object.entries(saved ?? {})) if (typeof v === 'boolean') savedFolders[k] = v
} catch {
  /* storage unavailable or damaged: the defaults */
}
/** the folders remembered, with the state each is built in (set once all exist) */
let folderDefaults = new Map<GUI, boolean>()
/** while the app itself folds or unfolds them (the empty screen): not the user's choice */
let foldingByApp = false
function rememberFolder(f: GUI): void {
  if (foldingByApp || !folderDefaults.has(f)) return
  savedFolders[f._title] = !f._closed
  try {
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(savedFolders))
  } catch {
    /* best-effort */
  }
}
/** every folder folded (the empty screen), or each the way it was left */
function applyFolders(empty: boolean): void {
  foldingByApp = true
  try {
    for (const [f, byDefault] of folderDefaults) {
      // 視点 sits in 表示: folding 表示 hides it, and it keeps its own state
      const open = empty && f !== presetFolder ? false : (savedFolders[f._title] ?? byDefault)
      f.open(open)
    }
  } finally {
    foldingByApp = false
  }
}
gui.onOpenClose((changed) => {
  rememberFolder(changed)
  // the app's own folding scrolls nothing (a remembered 断面 would pull the
  // panel down to it on every load)
  if (foldingByApp || changed === gui || changed._closed) return
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
const panelsShow = document.querySelector<HTMLButtonElement>('#panels-show')!
const FIT_PANELS: HTMLElement[] = [toolbarEl, gui.domElement, treePanel, hud, measurePanel, propsEl, triadEl, panelsShow]
viewer.fitArea = (modelW, modelH) => {
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
  return fitRect(c.width, c.height, panels, modelW, modelH)
}

// ---- hide the panels for a while (H, or the button in the GUI's title bar)
// On half a screen the panels cover about half the canvas; hidden, the model
// gets the whole of it. Hidden: the GUI, the part tree, the measure list and
// the volume panel (the status line with its ?, the legends and the axis
// triad stay). Not remembered: a reload shows them again.
let panelsHidden = false
const panelsHide = document.createElement('button')
panelsHide.type = 'button'
panelsHide.id = 'panels-hide'
panelsHide.textContent = '隠す'
panelsHide.title = 'パネルを隠してモデルを大きく見る（H）'
// a child of the GUI's root, not of its title (a button inside the title
// button would fold the GUI too); placed over the title's right end by CSS
gui.domElement.append(panelsHide)
function setPanelsHidden(hidden: boolean): void {
  if (hidden === panelsHidden) return
  // a view the user has not moved since its fit is fitted again into the
  // area the panels now leave (the same parts: この部品へ寄る's stay framed);
  // a moved view is left as it is
  viewer.settleView() // a fit still on its way counts as made
  const refit = !is2D && contentShown && viewer.atLastFit
  // a tree row the keyboard is on would keep its part highlighted, unseen
  if (hidden) partTree.releaseFocus()
  panelsHidden = hidden
  document.body.classList.toggle('panels-hidden', hidden)
  panelsShow.classList.toggle('hidden', !hidden)
  layoutCorner()
  if (refit) viewer.refit()
}
panelsHide.addEventListener('click', () => setPanelsHidden(true))
panelsShow.addEventListener('click', () => setPanelsHidden(false))

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

// ---- the toolbar (top of the right-hand column) and its keys M N S W
function setMode(mode: Mode): void {
  if (state.mode !== mode) modeCtl.setValue(mode)
}
function toggleSection(): void {
  if (!contentShown || is2D) return
  sectionTool.enabled = !sectionTool.enabled
  if (sectionTool.enabled) sectionTool.faceCamera(viewer.camera.position)
  sectionTool.update()
  refreshToolbar()
}
/** the next display style, in the select's order */
function nextStyle(): void {
  const i = DISPLAY_STYLES.indexOf(viewPrefs.style)
  styleCtl.setValue(DISPLAY_STYLES[(i + 1) % DISPLAY_STYLES.length])
}
toolbar = new Toolbar(toolbarEl, (action) => {
  switch (action) {
    case 'open':
      return actions.open()
    case 'fit':
      return actions.fit()
    case 'mode-none':
      return setMode('なし')
    case 'mode-measure':
      return setMode('計測')
    case 'mode-note':
      return setMode('注記')
    case 'section':
      return toggleSection()
    case 'style':
      return nextStyle()
    case 'png':
      return actions.savePng()
    case 'help':
      return keyHelp.show(!keyHelp.shown)
  }
})
/** M and N switch a mode on, or back to 回転 when it is on; S cuts; W the next style */
function toolbarKey(letter: 'm' | 'n' | 's' | 'w'): void {
  if (letter === 's') return toggleSection()
  if (letter === 'w') {
    if (!is2D) nextStyle()
    return
  }
  if (!contentShown) return
  if (letter === 'm') setMode(state.mode === '計測' ? 'なし' : '計測')
  else if (!is2D) setMode(state.mode === '注記' ? 'なし' : '注記')
}
function refreshToolbar(): void {
  if (!toolbar) return // still being set up
  toolbar.update({
    content: contentShown,
    is2D,
    mode: state.mode,
    canMeasure: is2D || measureTool.available,
    section: sectionTool.enabled,
    style: STYLE_NAMES[viewPrefs.style],
  })
}
measureTool.onChange(refreshToolbar) // a model's B-rep (or none) comes with setModel
refreshToolbar()

// every folder exists now: remember these, folded on the empty screen we start on
folderDefaults = new Map(
  [viewFolder, presetFolder, sectionFolder, thicknessFolder, draftFolder, propsFolder].map((f) => [f, !f._closed]),
)
applyFolders(!contentShown)

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

/**
 * The 計測 list: the 3D entries, or the measurements of a drawing (a load
 * empties both, so one of the two is always empty). A drawing's rows have the
 * class m2d and give the distance with its ΔX and ΔY, as the HUD does.
 */
function renderMeasureList(): void {
  const entries = measureTool.list()
  const dims = drawing2d.measurements()
  measurePanel.classList.toggle('hidden', entries.length + dims.length === 0)
  measureList.replaceChildren()
  listRows = []
  setHotEntry(null)
  for (const e of entries) {
    const row = entryRow(e.data)
    listRows.push(row)
    const li = rowElement(row, () => deleteWithUndo(() => measureTool.remove(e.id)), pressOnce)
    li.dataset.entryId = String(e.id)
    // the row under the pointer lights its label, line and points in 3D
    li.addEventListener('pointerenter', () => setHotEntry(e.id))
    li.addEventListener('pointerleave', () => setHotEntry(null))
    measureList.appendChild(li)
  }
  for (const m of dims) {
    const row = drawingRow(m)
    listRows.push(row)
    const li = rowElement(row, () => deleteDrawingWithUndo(() => drawing2d.removeMeasurement(m.id)), pressOnce)
    li.classList.add('m2d')
    measureList.appendChild(li)
  }
  measureCount.textContent = String(listRows.length)
}
/** the rows on show, for すべてコピー */
let listRows: RowView[] = []
const measureCount = document.querySelector<HTMLSpanElement>('#measure-count')!
const copyAll = document.querySelector<HTMLButtonElement>('#measure-copy-all')!
function copyAllLabel(done: boolean): void {
  const text = document.createElement('span')
  text.textContent = done ? 'コピーした' : 'すべてコピー'
  copyAll.replaceChildren(icon(done ? ICON.done : ICON.copy, 13), text)
  copyAll.classList.toggle('done', done)
}
copyAllLabel(false)
let copyAllTimer: ReturnType<typeof setTimeout> | undefined
copyAll.addEventListener('click', async () => {
  if (!listRows.length || !(await copyText(listText(listRows)))) return
  copyAllLabel(true)
  clearTimeout(copyAllTimer)
  copyAllTimer = setTimeout(() => copyAllLabel(false), 1500)
})
/**
 * One measurement lit at a time: its 3D label, line and points, and its row
 * (the pointer is on the row, or on the label in 3D). null: none.
 */
let hotEntry: number | null = null
function setHotEntry(id: number | null): void {
  if (id === hotEntry) return
  hotEntry = id
  measureTool.setHot(id)
  for (const li of measureList.querySelectorAll<HTMLElement>('li.hot')) li.classList.remove('hot')
  if (id !== null) measureList.querySelector(`li[data-entry-id="${id}"]`)?.classList.add('hot')
}
// a label under the pointer lights its row (labels take no clicks: a click
// there still reaches the model, to measure or to turn the view)
let labelHoverQueued = false
let labelHoverAt: [number, number] | null = null
viewport.addEventListener('pointermove', (e) => {
  labelHoverAt = [e.clientX, e.clientY]
  if (labelHoverQueued) return
  labelHoverQueued = true
  requestAnimationFrame(() => {
    labelHoverQueued = false
    if (labelHoverAt && !is2D) setHotEntry(measureTool.entryAt(...labelHoverAt))
  })
})
viewport.addEventListener('pointerleave', () => {
  labelHoverAt = null
  setHotEntry(null)
})
measureTool.onChange(renderMeasureList)
drawing2d.onChange(renderMeasureList)

// ---- undo the last deletion (× or 計測クリア)
// One step back: the list as it was before the deletion, for UNDO_MS or until
// the list changes otherwise (a new measurement, a model switch). A dialog
// would stop the hand on every delete; an undo keeps the work safe without it.
// Putting the list back makes the autosave write it again.
const UNDO_MS = 8000
const undoToast = document.querySelector<HTMLDivElement>('#undo-toast')!
const undoText = document.querySelector<HTMLSpanElement>('#undo-text')!
const undoBtn = document.querySelector<HTMLButtonElement>('#undo-btn')!
/** the list before the deletion: entries (3D), or drawing (a drawing's measurements) */
let undoState: { modelId: string; entries?: EntryData[]; drawing?: Measurement2D[] } | null = null
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

/** The same for a drawing's measurements (計測クリア or a row's × on a drawing). */
function deleteDrawingWithUndo(run: () => void): void {
  const before = drawing2d.measurementsSnapshot()
  undoOwnChange = true
  try {
    run()
  } finally {
    undoOwnChange = false
  }
  const removed = before.length - drawing2d.measurements().length
  if (removed <= 0 || !currentModelId) return
  armUndo({ modelId: currentModelId, drawing: before }, removed)
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
    undoOwnChange = true
    try {
      drawing2d.restoreMeasurements(u.drawing)
    } finally {
      undoOwnChange = false
    }
    hudInfo.textContent = `計測を元に戻した（${u.drawing.length} 件）`
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
// on a drawing too: a new measurement, a load (the same drawing again as well)
drawing2d.onChange(() => {
  if (!undoOwnChange) dropUndo()
})

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
      // a hint like the others: the mode's line goes with the mode
      setModeHud('1 点目を取り消した（クリックで 1 点目、もう一度 Esc で計測をやめる）')
      probe.refresh() // the dotted line from that point goes now, not at the next move
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
    hudInfo.textContent = MEASURE_MESH_HINT
    return
  }
  measureTool
    .handlePick(pick)
    .then((msg) => {
      if (!msg) return
      // the first point's line asks for the partner: it goes with the mode;
      // a result stays
      if (measureTool.pendingPoint) setModeHud(msg)
      else hudInfo.textContent = msg
    })
    .catch((err) => {
      hudInfo.textContent = `計測エラー: ${err instanceof Error ? err.message : err}`
    })
    // a cursor moved while the measurement was in flight (no highlight then:
    // a click would have been dropped) gets its highlight now
    .finally(() => probe.refresh())
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
    partTree.show(model.tree) // after viewer.setModel: the marks take the parts' colours from it
    treePanel.classList.remove('hidden')
  } else {
    partTree.clear()
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
  // the card in the middle: it takes the place of the open card (or of the
  // card of a load that failed), and stays over the old model until it goes
  loadCard.start(file)
  showEmpty(false)
  let step: LoadStep = 'send'
  const reach = (s: LoadStep) => {
    if (gen !== loadGen) return // a newer load owns the card
    step = s
    loadCard.step(s)
  }

  try {
    const meta = await uploadModel(file, (sent) => {
      if (gen !== loadGen) return
      if (sent >= 1) reach('convert') // all of it is up: the backend converts it now
      else loadCard.sent(sent)
    })
    if (gen !== loadGen) return // superseded by a newer load
    reach('prepare')

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
      preselect.setModel([])
      diameters.setModel(null)
      thicknessHud = ''
      modeHud = ''
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
      partTree.clear()
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
        loadCard.hide()
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
        preselect.setModel(model.parts)
        // a mesh model has no B-rep to ask for a diameter
        diameters.setModel(meta.format === 'brep' ? meta.id : null)
        measureTool.setModel(meta.id, meta.format === 'brep', new Map(model.parts.map((p) => [p.id, p.name])))
        sectionTool.setModelBBox(meta.bbox.min, meta.bbox.max)
        sectionRange()
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
        // a mode chosen before the load (or kept from the last model) says what
        // to click on this one, after the summary (E2E waits for the summary)
        const hint = modeHint()
        if (hint) setModeHud(`${hudInfo.textContent} — ${hint}`, hudInfo.textContent)
        loadCard.hide()
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
    if (gen !== loadGen) return // a newer load owns the screen and the card
    const reason = failureReason(e, file.name, step)
    hudInfo.textContent = `エラー: ${file.name} を開けなかった — ${reason}`
    // what the backend said, for whoever looks into it (詳細を見る)
    const detail = e instanceof Error ? e.message : String(e)
    loadCard.fail(file.name, reason, detail)
    // Nothing on screen (the old model went before the failure, or there was
    // none): the plain empty screen, as at start-up. The failed card has
    // 別のファイルを選ぶ; closing it brings back the open card.
    if (!contentShown) show2D(false)
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
  return {
    geometries: info.memory.geometries,
    programs: info.programs?.length ?? 0,
    calls: info.render.calls,
    // frames drawn so far: they stop while nothing changes
    frames: viewer.frameCount,
  }
}
testHooks.__cadStallSidecar = (ms: number) => __stallNextSidecar(ms)
// presets and fits move smoothly for the user; off under automation unless turned on here
testHooks.__cadViewMotion = (on: boolean) => viewer.setViewMotion(on)
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
