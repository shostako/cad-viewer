/**
 * アンダーカットの候補 on screen (docs/designs/undercut.md): the Worker's finer
 * meshes (undercut.ts) coloured by which half of the mold reaches each point,
 * the legend, and the class under the cursor.
 */
import * as THREE from 'three'

import type { Surface } from './compare.ts'
import { DOWN, UP, undercutArea, type Reach, type ReachPart } from './undercut.ts'
import type { ReachReply } from './undercutworker.ts'
import { palette } from './theme.ts'

/**
 * The colours (the theme's: theme.ts PALETTES): neither half reaches, a strong
 * red-purple apart from the draft's and the heatmap's colours; the upper half
 * only, the draft's 抜ける側 green; the lower half only, the draft's 反対側
 * blue (both paler in the dark theme); both halves (a wall along the pull), grey
 */
export function undercutColors(): { candidate: THREE.Color; up: THREE.Color; down: THREE.Color; both: THREE.Color } {
  const c = palette().undercut
  return { candidate: new THREE.Color(c.candidate), up: new THREE.Color(c.up), down: new THREE.Color(c.down), both: new THREE.Color(c.both) }
}

const css = (c: THREE.Color) => `#${c.getHexString()}`

export function reachColor(r: number, colors: ReturnType<typeof undercutColors> = undercutColors()): THREE.Color {
  return r === 0 ? colors.candidate : r === UP ? colors.up : r === DOWN ? colors.down : colors.both
}

export function reachText(r: number): string {
  if (r === 0) return 'アンダーカットの候補（上にも下にも抜けない）'
  if (r === UP) return '上の型で抜ける'
  if (r === DOWN) return '下の型で抜ける'
  return '上下どちらにも抜ける（型開き方向に沿った面）'
}

/** the reach in the Worker; cancel() stops it (the promise then never settles) */
export function runReach(parts: Surface[], dir: readonly [number, number, number]): { promise: Promise<Reach>; cancel(): void } {
  const worker = new Worker(new URL('./undercutworker.ts', import.meta.url), { type: 'module' })
  const promise = new Promise<Reach>((resolve, reject) => {
    worker.onmessage = (e: MessageEvent<ReachReply>) => {
      worker.terminate()
      const r = e.data
      if (r.ok) resolve(r.result)
      else reject(new Error(r.error))
    }
    worker.onerror = (e) => {
      worker.terminate()
      reject(new Error(e.message || 'アンダーカットの計算が止まった'))
    }
  })
  // copies: the meshes on screen keep their arrays
  const copies = parts.map((s) => ({ positions: Float32Array.from(s.positions), normals: Float32Array.from(s.normals), indices: Uint32Array.from(s.indices) }))
  worker.postMessage({ parts: copies, dir: [...dir] }, copies.flatMap((s) => [s.positions.buffer, s.normals.buffer, s.indices.buffer]))
  return { promise, cancel: () => worker.terminate() }
}

export class UndercutView {
  readonly reach: Reach
  /** the part each of reach.parts is */
  readonly partIds: number[]
  private meshes: THREE.Mesh[] = []
  private raycaster = new THREE.Raycaster()

  constructor(reach: Reach, partIds: number[]) {
    this.reach = reach
    this.partIds = partIds
  }

  /** the meshes to show (new ones: the caller puts them on screen; dispose() frees them), each with its part's id */
  build(): THREE.Mesh[] {
    this.dispose()
    this.meshes = this.reach.parts.map((p, k) => {
      const mesh = meshOf(p)
      mesh.name = `undercut-${this.partIds[k]}`
      mesh.userData.partId = this.partIds[k]
      return mesh
    })
    return this.meshes
  }

  dispose(): void {
    for (const m of this.meshes) {
      m.geometry.disposeBoundsTree?.()
      m.geometry.dispose()
      ;(m.material as THREE.Material).dispose()
    }
    this.meshes = []
  }

  /** the area of the undercut candidates of the parts shown (mm²) */
  area(visible: (partId: number) => boolean): number {
    let a = 0
    this.reach.parts.forEach((p, k) => {
      if (visible(this.partIds[k])) a += undercutArea(p)
    })
    return a
  }

  /** the class at the surface under the cursor (ndc): the drawn surface nearest, the section's cut-away side skipped; null off the parts */
  valueAt(ndc: THREE.Vector2, camera: THREE.Camera): string | null {
    const shown = this.meshes.filter((m) => m.visible)
    for (const m of shown) if (!m.geometry.boundsTree) m.geometry.computeBoundsTree?.({ indirect: true })
    this.raycaster.setFromCamera(ndc, camera)
    for (const hit of this.raycaster.intersectObjects(shown, false)) {
      if (!hit.face) continue
      const clip = ((hit.object as THREE.Mesh).material as THREE.Material).clippingPlanes
      if (clip?.some((p) => p.distanceToPoint(hit.point) < 0)) continue
      const mesh = hit.object as THREE.Mesh
      const part = this.reach.parts[this.meshes.indexOf(mesh)]
      // the vertex of the triangle nearest the point (a class does not blend)
      const pos = mesh.geometry.getAttribute('position') as THREE.BufferAttribute
      let best = hit.face.a
      let bestD = Infinity
      for (const v of [hit.face.a, hit.face.b, hit.face.c]) {
        const d = new THREE.Vector3().fromBufferAttribute(pos, v).distanceToSquared(hit.point)
        if (d < bestD) (bestD = d), (best = v)
      }
      return reachText(part.reach[best])
    }
    return null
  }
}

function meshOf(p: ReachPart): THREE.Mesh {
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(p.positions, 3))
  geo.setAttribute('normal', new THREE.BufferAttribute(p.normals, 3))
  geo.setIndex(new THREE.BufferAttribute(p.indices, 1))
  const colors = new Float32Array(p.reach.length * 3)
  const theme = undercutColors()
  for (let i = 0; i < p.reach.length; i++) {
    const c = reachColor(p.reach[i], theme)
    colors[3 * i] = c.r
    colors[3 * i + 1] = c.g
    colors[3 * i + 2] = c.b
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.1,
    roughness: 0.65,
    side: THREE.DoubleSide,
    // as the parts' faces (viewer.addPart)
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  })
  return new THREE.Mesh(geo, mat)
}

/** the legend: the four classes, the candidates' area, and what the check does not see */
export function renderUndercutLegend(el: HTMLElement, dirLabel: string, area: number): void {
  const title = document.createElement('div')
  title.className = 'draft-title'
  title.textContent = `アンダーカットの候補（型開き方向 ${dirLabel}）`
  const row = (color: THREE.Color, text: string) => {
    const r = document.createElement('div')
    r.className = 'draft-row'
    const sw = document.createElement('span')
    sw.className = 'draft-swatch'
    sw.style.background = css(color)
    const t = document.createElement('span')
    t.textContent = text
    r.append(sw, t)
    return r
  }
  const note = document.createElement('div')
  note.className = 'compare-note'
  note.textContent =
    '型開き方向へまっすぐ開く 2 枚の型として、面の各点から上と下へ光線を飛ばし、同じ部品に当たるかで見る。パーティング面の位置、スライドの向き、無理抜きできるかは見ていない'
  const c = undercutColors()
  el.replaceChildren(
    title,
    row(c.candidate, `アンダーカットの候補（上にも下にも抜けない）${area > 0 ? ` ${area.toFixed(1)} mm²` : ' なし'}`),
    row(c.up, '上の型で抜ける'),
    row(c.down, '下の型で抜ける'),
    row(c.both, '上下どちらにも抜ける（型開き方向に沿った面）'),
    note,
  )
}
