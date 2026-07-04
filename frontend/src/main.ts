import './style.css'
import GUI from 'lil-gui'
import { uploadModel, fetchMesh, type ModelMeta } from './api'
import { toModelData } from './model'
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

const viewer = new Viewer(viewport)

const gui = new GUI({ title: '操作' })
const actions = {
  open: () => fileInput.click(),
  fit: () => viewer.fitToView(),
}
gui.add(actions, 'open').name('ファイルを開く')
gui.add(actions, 'fit').name('全体表示')

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

fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0]
  if (file) void loadFile(file)
  fileInput.value = ''
})
