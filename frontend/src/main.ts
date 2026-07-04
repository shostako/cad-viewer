import './style.css'
import GUI from 'lil-gui'
import * as THREE from 'three'
import {
  uploadModel,
  fetchMesh,
  fetchDrawingSvg,
  fetchThickness,
  getSidecar,
  putSidecar,
  type ModelMeta,
} from './api'
import { Drawing2D } from './drawing2d'
import { MeasureTool, type EntryData } from './measure'
import { toModelData } from './model'
import { Picker } from './picking'
import { SectionTool, type Axis } from './section'
import { renderTree } from './tree'
import { Viewer } from './viewer'

const app = document.querySelector<HTMLDivElement>('#app')!
app.innerHTML = `
  <div id="viewport"></div>
  <div id="viewport2d" class="hidden"></div>
  <div id="dropzone" class="hidden">ここにドロップして読み込み</div>
  <div id="tree-panel" class="hidden">
    <div id="tree-title">部品ツリー</div>
    <div id="tree-body"></div>
  </div>
  <div id="measure-panel" class="hidden">
    <div id="measure-title">計測</div>
    <ul id="measure-list"></ul>
  </div>
  <div id="hud">
    <div id="hud-title">cad-viewer</div>
    <div id="hud-info">STEP / IGES / STL / 3MF をドロップ、またはメニューから選択</div>
  </div>
  <input type="file" id="file-input" accept=".step,.stp,.iges,.igs,.stl,.3mf,.obj,.ply,.dxf,.dwg" hidden />
`

const viewport = document.querySelector<HTMLDivElement>('#viewport')!
const dropzone = document.querySelector<HTMLDivElement>('#dropzone')!
const hudInfo = document.querySelector<HTMLDivElement>('#hud-info')!
const fileInput = document.querySelector<HTMLInputElement>('#file-input')!
const treePanel = document.querySelector<HTMLDivElement>('#tree-panel')!
const treeBody = document.querySelector<HTMLDivElement>('#tree-body')!

const measurePanel = document.querySelector<HTMLDivElement>('#measure-panel')!
const measureList = document.querySelector<HTMLUListElement>('#measure-list')!

const viewport2d = document.querySelector<HTMLDivElement>('#viewport2d')!

const viewer = new Viewer(viewport)
const picker = new Picker(viewer)
const measureTool = new MeasureTool(viewer)
const sectionTool = new SectionTool(viewer)
const drawing2d = new Drawing2D(viewport2d, (msg) => {
  hudInfo.textContent = msg
})

let is2D = false
function show2D(on: boolean): void {
  is2D = on
  viewport2d.classList.toggle('hidden', !on)
  viewport.classList.toggle('hidden', on)
  treePanel.classList.toggle('hidden', on || !treeBody.hasChildNodes())
}

let currentModelId: string | null = null
let restoring = false

const gui = new GUI({ title: '操作' })
const state = { mode: 'なし' as 'なし' | '計測' | '注記' }
const actions = {
  open: () => fileInput.click(),
  fit: () => (is2D ? drawing2d.fit() : viewer.fitToView()),
  clearMeasure: () => {
    measureTool.clearAll()
    drawing2d.clearMeasurements()
  },
}
gui.add(actions, 'open').name('ファイルを開く')
gui.add(actions, 'fit').name('全体表示')
gui
  .add(state, 'mode', ['なし', '計測', '注記'])
  .name('モード')
  .onChange((mode: string) => {
    if (mode !== '計測') measureTool.cancelPending()
    drawing2d.measureMode = mode === '計測'
    viewport.style.cursor = mode === 'なし' ? '' : 'crosshair'
    viewport2d.style.cursor = mode === '計測' ? 'crosshair' : ''
  })
gui.add(actions, 'clearMeasure').name('計測クリア')

const sectionFolder = gui.addFolder('断面')
sectionFolder.close()
sectionFolder
  .add(sectionTool, 'enabled')
  .name('有効')
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

// ---- thickness heatmap
const thicknessState = { enabled: false, threshold: 1.5, method: 'ray' as 'ray' | 'ball' }
const thicknessCache = new Map<string, Map<number, Float32Array>>()
async function updateThickness(): Promise<void> {
  if (!currentModelId) return
  if (!thicknessState.enabled) {
    viewer.clearThicknessColors()
    return
  }
  try {
    let data = thicknessCache.get(thicknessState.method)
    if (!data) {
      hudInfo.textContent =
        thicknessState.method === 'ball' ? '肉厚計算中（ボール法、少し待て）...' : '肉厚計算中...'
      data = await fetchThickness(currentModelId, thicknessState.method)
      thicknessCache.set(thicknessState.method, data)
    }
    viewer.setThicknessColors(data, thicknessState.threshold)
    hudInfo.textContent = `肉厚ヒートマップ表示中（${
      thicknessState.method === 'ball' ? 'ローリングボール法' : 'レイ法'
    }、赤=閾値未満）`
  } catch (e) {
    thicknessState.enabled = false
    hudInfo.textContent = `肉厚計算エラー: ${e instanceof Error ? e.message : e}`
  }
}
const thicknessFolder = gui.addFolder('肉厚')
thicknessFolder.close()
thicknessFolder
  .add(thicknessState, 'enabled')
  .name('ヒートマップ')
  .onChange(() => void updateThickness())
thicknessFolder
  .add(thicknessState, 'method', { レイ法: 'ray', 'ローリングボール法': 'ball' })
  .name('方式')
  .onChange(() => void updateThickness())
thicknessFolder
  .add(thicknessState, 'threshold', 0.1, 10, 0.1)
  .name('閾値 (mm)')
  .onChange(() => void updateThickness())

// ---- sidecar persistence (auto-save, debounced)
let saveTimer: ReturnType<typeof setTimeout> | undefined
measureTool.onChange(() => {
  if (restoring || !currentModelId) return
  clearTimeout(saveTimer)
  const id = currentModelId
  saveTimer = setTimeout(() => {
    void putSidecar(id, { version: 1, entries: measureTool.toJSON() })
  }, 800)
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

// click-to-pick (suppress when the user is orbiting)
let downAt: [number, number] | null = null
viewport.addEventListener('pointerdown', (e) => {
  downAt = [e.clientX, e.clientY]
})
viewport.addEventListener('pointerup', (e) => {
  if (state.mode === 'なし' || !downAt) return
  const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1])
  downAt = null
  if (moved > 5 || measureTool.busy) return
  const rect = viewer.renderer.domElement.getBoundingClientRect()
  const ndc = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1,
  )
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

function fmtBBox(meta: ModelMeta): string {
  const d = meta.bbox.max.map((v, i) => v - meta.bbox.min[i])
  return d.map((v) => v.toFixed(1)).join(' × ')
}

async function loadFile(file: File): Promise<void> {
  hudInfo.textContent = `読み込み中: ${file.name} ...`
  try {
    const meta = await uploadModel(file)

    if (meta.format === 'drawing') {
      const svg = await fetchDrawingSvg(meta.id)
      drawing2d.load(svg, meta.snapPoints ?? [])
      show2D(true)
      currentModelId = meta.id
      const d = meta.bbox2d
        ? meta.bbox2d.max.map((v, i) => (v - meta.bbox2d!.min[i]).toFixed(1)).join(' × ')
        : '?'
      hudInfo.textContent = `${meta.name} — 2D図面, ${d} (計測モードで端点/中心スナップ)`
      return
    }

    show2D(false)
    thicknessCache.clear()
    thicknessState.enabled = false
    const pack = await fetchMesh(meta.id)
    const model = toModelData(pack)
    viewer.setModel(model)
    picker.setModel(model.parts)
    measureTool.setModel(meta.id, meta.format === 'brep')
    currentModelId = meta.id
    sectionTool.setModelBBox(meta.bbox.min, meta.bbox.max)

    // restore persisted measurements / annotations
    restoring = true
    try {
      const sidecar = await getSidecar(meta.id)
      const entries = (sidecar.entries ?? []) as EntryData[]
      if (entries.length) measureTool.restore(entries)
    } finally {
      restoring = false
    }

    if (model.parts.length > 1 || model.parts[0]?.faceRanges.length) {
      renderTree(treeBody, model.tree, (partId, visible) =>
        viewer.setPartVisible(partId, visible),
      )
      treePanel.classList.remove('hidden')
    } else {
      treePanel.classList.add('hidden')
    }

    const partInfo = meta.partCount > 1 ? `${meta.partCount} parts, ` : ''
    hudInfo.textContent =
      `${meta.name} — ${partInfo}${meta.triangleCount.toLocaleString()} tris, ` +
      `サイズ ${fmtBBox(meta)} (単位はファイル依存)`
  } catch (e) {
    hudInfo.textContent = `エラー: ${e instanceof Error ? e.message : e}`
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
  const v = new THREE.Vector3(x, y, z).project(viewer.camera)
  const rect = viewer.renderer.domElement.getBoundingClientRect()
  return {
    x: rect.left + ((v.x + 1) / 2) * rect.width,
    y: rect.top + ((1 - v.y) / 2) * rect.height,
  }
}
testHooks.__cadPick = (clientX: number, clientY: number) => {
  const rect = viewer.renderer.domElement.getBoundingClientRect()
  const ndc = new THREE.Vector2(
    ((clientX - rect.left) / rect.width) * 2 - 1,
    -((clientY - rect.top) / rect.height) * 2 + 1,
  )
  const r = picker.pick(ndc)
  return r ? { partId: r.partId, kind: r.kind, id: r.id, point: r.point.toArray() } : null
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0]
  if (file) void loadFile(file)
  fileInput.value = ''
})
