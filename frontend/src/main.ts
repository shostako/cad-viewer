import './style.css'
import GUI from 'lil-gui'
import * as THREE from 'three'
import { uploadModel, fetchMesh, type ModelMeta } from './api'
import { MeasureTool } from './measure'
import { toModelData } from './model'
import { Picker } from './picking'
import { renderTree } from './tree'
import { Viewer } from './viewer'

const app = document.querySelector<HTMLDivElement>('#app')!
app.innerHTML = `
  <div id="viewport"></div>
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
  <input type="file" id="file-input" accept=".step,.stp,.iges,.igs,.stl,.3mf,.obj,.ply" hidden />
`

const viewport = document.querySelector<HTMLDivElement>('#viewport')!
const dropzone = document.querySelector<HTMLDivElement>('#dropzone')!
const hudInfo = document.querySelector<HTMLDivElement>('#hud-info')!
const fileInput = document.querySelector<HTMLInputElement>('#file-input')!
const treePanel = document.querySelector<HTMLDivElement>('#tree-panel')!
const treeBody = document.querySelector<HTMLDivElement>('#tree-body')!

const measurePanel = document.querySelector<HTMLDivElement>('#measure-panel')!
const measureList = document.querySelector<HTMLUListElement>('#measure-list')!

const viewer = new Viewer(viewport)
const picker = new Picker(viewer)
const measureTool = new MeasureTool(viewer)

const gui = new GUI({ title: '操作' })
const state = { measureMode: false }
const actions = {
  open: () => fileInput.click(),
  fit: () => viewer.fitToView(),
  clearMeasure: () => measureTool.clearAll(),
}
gui.add(actions, 'open').name('ファイルを開く')
gui.add(actions, 'fit').name('全体表示')
gui
  .add(state, 'measureMode')
  .name('計測モード')
  .onChange((on: boolean) => {
    if (!on) measureTool.cancelPending()
    viewport.style.cursor = on ? 'crosshair' : ''
  })
gui.add(actions, 'clearMeasure').name('計測クリア')

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

// click-to-measure (suppress when the user is orbiting)
let downAt: [number, number] | null = null
viewport.addEventListener('pointerdown', (e) => {
  downAt = [e.clientX, e.clientY]
})
viewport.addEventListener('pointerup', (e) => {
  if (!state.measureMode || !downAt) return
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
    const pack = await fetchMesh(meta.id)
    const model = toModelData(pack)
    viewer.setModel(model)
    picker.setModel(model.parts)
    measureTool.setModel(meta.id, meta.format === 'brep')

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
