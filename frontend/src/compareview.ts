/**
 * 版の比較 on screen (docs/designs/compare.md): the Worker's finer meshes
 * (compare.ts) coloured by how much was added or removed, the legend, and the
 * value under the cursor.
 *
 * "a" is the version open in the app, "b" the file opened to compare with it.
 * Which of them is the new one is the user's (the compared file is the previous
 * version or the next). A point's change is its distance to the other version,
 * + where the new version has material the old one does not (added), - where
 * the old one has material the new one does not (removed): on the new
 * version's surface, + outside the old version; on the old one's, + inside the
 * new version.
 */
import * as THREE from 'three'

import { placesOfParts, type Comparison, type Place, type Sampled, type Surface } from './compare.ts'
import type { CompareReply } from './compareworker.ts'
import { palette } from './theme.ts'

/** the compared file is the previous version of the one open, or the next */
export type CompareRole = 'previous' | 'next'
/** 重ねる: the new version, and of the old one what was removed; or one version alone */
export type CompareShow = 'overlay' | 'new' | 'old'

/**
 * added: a blue-green; removed: a red-orange (told apart also with red-green
 * colour blindness); unchanged: grey. The theme's (theme.ts PALETTES): the
 * light theme's are darker
 */
export function compareColors(): { added: THREE.Color; removed: THREE.Color; same: THREE.Color } {
  const c = palette().compare
  return { added: new THREE.Color(c.added), removed: new THREE.Color(c.removed), same: new THREE.Color(c.same) }
}
/** how much of the colour a change just over the tolerance gets (the rest grows to the largest change) */
const MIN_MIX = 0.35
/** the removed parts of the old version over the new one (重ねる) */
const GHOST_ALPHA = 0.55

const css = (c: THREE.Color) => `#${c.getHexString()}`

/** the comparison in the Worker; cancel() stops it (the promise then never settles) */
export function runCompare(a: Surface[], b: Surface[]): { promise: Promise<Comparison>; cancel(): void } {
  const worker = new Worker(new URL('./compareworker.ts', import.meta.url), { type: 'module' })
  const promise = new Promise<Comparison>((resolve, reject) => {
    worker.onmessage = (e: MessageEvent<CompareReply>) => {
      worker.terminate()
      const r = e.data
      if (r.ok) resolve(r.result)
      else reject(new Error(r.error))
    }
    worker.onerror = (e) => {
      worker.terminate()
      reject(new Error(e.message || '比較の計算が止まった'))
    }
  })
  // copies: the meshes on screen keep their arrays
  const copy = (parts: Surface[]): Surface[] =>
    parts.map((s) => ({ positions: Float32Array.from(s.positions), normals: Float32Array.from(s.normals), indices: Uint32Array.from(s.indices) }))
  const ca = copy(a), cb = copy(b)
  const transfer = [...ca, ...cb].flatMap((s) => [(s.positions as Float32Array).buffer, (s.normals as Float32Array).buffer, (s.indices as Uint32Array).buffer])
  worker.postMessage({ a: ca, b: cb }, transfer)
  return { promise, cancel: () => worker.terminate() }
}

/** a version's change per vertex: its offset as is on the new version, turned over on the old one */
function changeOf(s: Sampled, isNew: boolean): Float32Array {
  if (isNew) return s.offset
  const out = new Float32Array(s.offset.length)
  for (let i = 0; i < out.length; i++) out[i] = -s.offset[i]
  return out
}

/**
 * The colour of a change: grey within the tolerance (and where it is not
 * known), else the added or removed colour, from MIN_MIX of it just over the
 * tolerance to all of it at `max`.
 */
export function changeColor(
  c: number,
  tol: number,
  max: number,
  out: THREE.Color,
  colors: ReturnType<typeof compareColors> = compareColors(),
): THREE.Color {
  if (!(Math.abs(c) > tol)) return out.copy(colors.same)
  const f = max > tol ? Math.min(1, (Math.abs(c) - tol) / (max - tol)) : 1
  return out.copy(colors.same).lerp(c > 0 ? colors.added : colors.removed, MIN_MIX + (1 - MIN_MIX) * f)
}

export interface CompareStats {
  /** the largest addition (mm, >= 0) and removal (mm, <= 0) on either version */
  added: number
  removed: number
}

export function statsOf(changes: Float32Array[]): CompareStats {
  let added = 0, removed = 0
  for (const ch of changes) {
    for (const c of ch) {
      if (c > added) added = c
      if (c < removed) removed = c
    }
  }
  return { added, removed }
}

/** mm with 2 decimals, the sign always shown */
export function signed(c: number): string {
  return `${c > 0 ? '+' : c < 0 ? '−' : '±'}${Math.abs(c).toFixed(2)}`
}

/** the tolerance to start from: what the two display meshes can be apart on the same curved face (their deflections), at least 0.01 mm */
export function startTolerance(deflA: number, deflB: number): number {
  const t = Math.max(0.01, deflA + deflB)
  const p = 10 ** (Math.floor(Math.log10(t)) - 1) // two significant digits, up
  return Math.ceil(t / p - 1e-9) * p
}

interface Side {
  sampled: Sampled
  change: Float32Array
  mesh: THREE.Mesh
  ghost: boolean
}

export class CompareView {
  readonly result: Comparison
  role: CompareRole = 'previous'
  show: CompareShow = 'overlay'
  tolerance: number
  private sides: { a: Side | null; b: Side | null } = { a: null, b: null }
  private raycaster = new THREE.Raycaster()

  constructor(result: Comparison, tolerance: number) {
    this.result = result
    this.tolerance = tolerance
  }

  /** which of a / b is the new version */
  get newSide(): 'a' | 'b' {
    return this.role === 'previous' ? 'a' : 'b'
  }

  get oldSide(): 'a' | 'b' {
    return this.role === 'previous' ? 'b' : 'a'
  }

  changes(): { a: Float32Array; b: Float32Array } {
    const n = this.newSide
    return { a: changeOf(this.result.a, n === 'a'), b: changeOf(this.result.b, n === 'b') }
  }

  stats(): CompareStats {
    const ch = this.changes()
    return statsOf([ch.a, ch.b])
  }

  /**
   * The places that changed, the largest change first: what was added, on the
   * new version's surface where it is outside the old one; what was removed,
   * on the old version's where it is outside the new one (each change once:
   * the other side of it is inside the other version, hidden). Their peak is
   * the largest change there (removed: negative).
   */
  places(): { added: Place[]; removed: Place[] } {
    const ch = this.changes()
    const tol = this.tolerance
    const n = this.newSide, o = this.oldSide
    const added = placesOfParts(this.result[n], (i) => ch[n][i] > tol, (i) => ch[n][i]).sort((a, b) => b.peak - a.peak)
    const removed = placesOfParts(this.result[o], (i) => ch[o][i] < -tol, (i) => -ch[o][i])
      .map((q) => ({ ...q, peak: -q.peak }))
      .sort((a, b) => a.peak - b.peak)
    return { added, removed }
  }

  /** the scale's end: the largest change either way (both versions, one scale) */
  private scaleMax(): number {
    const s = this.stats()
    return Math.max(s.added, -s.removed)
  }

  /**
   * The meshes to show for the current role, show and tolerance (new ones:
   * the caller puts them on screen and disposes the last ones, dispose()).
   */
  build(): THREE.Mesh[] {
    this.dispose()
    const ch = this.changes()
    const max = this.scaleMax()
    const out: THREE.Mesh[] = []
    const add = (key: 'a' | 'b', ghost: boolean) => {
      const sampled = this.result[key]
      const mesh = meshOf(sampled, ch[key], this.tolerance, max, ghost)
      mesh.name = `compare-${key}${ghost ? '-ghost' : ''}`
      this.sides[key] = { sampled, change: ch[key], mesh, ghost }
      out.push(mesh)
    }
    if (this.show === 'overlay') {
      add(this.newSide, false)
      add(this.oldSide, true)
    } else add(this.show === 'new' ? this.newSide : this.oldSide, false)
    return out
  }

  dispose(): void {
    for (const key of ['a', 'b'] as const) {
      const s = this.sides[key]
      if (!s) continue
      s.mesh.geometry.disposeBoundsTree?.()
      s.mesh.geometry.dispose()
      ;(s.mesh.material as THREE.Material).dispose()
      this.sides[key] = null
    }
  }

  /**
   * The change at the surface under the cursor (ndc), as the colour there says
   * it: the nearest drawn surface (an old version's surface where nothing was
   * removed is not drawn over the new one; the section's cut-away side is not
   * drawn either). null off the meshes.
   */
  valueAt(ndc: THREE.Vector2, camera: THREE.Camera): string | null {
    const meshes = (['a', 'b'] as const).map((k) => this.sides[k]).filter((s): s is Side => s !== null)
    for (const s of meshes) if (!s.mesh.geometry.boundsTree) s.mesh.geometry.computeBoundsTree?.({ indirect: true })
    this.raycaster.setFromCamera(ndc, camera)
    const hits = this.raycaster.intersectObjects(
      meshes.map((s) => s.mesh),
      false,
    )
    for (const hit of hits) {
      const side = meshes.find((s) => s.mesh === hit.object)!
      if (!hit.face) continue
      // a surface the section cut away is not seen (a ray does not know the clipping: as picking.ts)
      const clip = (side.mesh.material as THREE.Material).clippingPlanes
      if (clip?.some((p) => p.distanceToPoint(hit.point) < 0)) continue
      const { a, b, c } = hit.face
      const w = new THREE.Vector3()
      THREE.Triangle.getBarycoord(
        hit.point,
        new THREE.Vector3().fromBufferAttribute(side.mesh.geometry.getAttribute('position') as THREE.BufferAttribute, a),
        new THREE.Vector3().fromBufferAttribute(side.mesh.geometry.getAttribute('position') as THREE.BufferAttribute, b),
        new THREE.Vector3().fromBufferAttribute(side.mesh.geometry.getAttribute('position') as THREE.BufferAttribute, c),
        w,
      )
      const v = w.x * side.change[a] + w.y * side.change[b] + w.z * side.change[c]
      if (Number.isNaN(v)) return null
      // the ghost shows only what was removed
      if (side.ghost && !(v < -this.tolerance)) continue
      const which = (side.mesh.name.startsWith(`compare-${this.newSide}`) ? '新しい版' : '前の版') + 'の面'
      if (Math.abs(v) <= this.tolerance) return `差 ${signed(v)} mm（許容 ±${this.tolerance} mm の中、${which}）`
      return `${v > 0 ? '足された' : '削られた'} ${signed(v)} mm（${which}）`
    }
    return null
  }
}

/** a version's finer mesh, coloured (ghost: only what was removed, see-through) */
function meshOf(s: Sampled, change: Float32Array, tol: number, max: number, ghost: boolean): THREE.Mesh {
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(s.positions, 3))
  geo.setAttribute('normal', new THREE.BufferAttribute(s.normals, 3))
  geo.setIndex(new THREE.BufferAttribute(s.indices, 1))
  const n = change.length
  const size = ghost ? 4 : 3
  const colors = new Float32Array(n * size)
  const c = new THREE.Color()
  const theme = compareColors()
  for (let i = 0; i < n; i++) {
    changeColor(change[i], tol, max, c, theme)
    colors[size * i] = c.r
    colors[size * i + 1] = c.g
    colors[size * i + 2] = c.b
    if (ghost) colors[size * i + 3] = change[i] < -tol ? GHOST_ALPHA : 0
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, size))
  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.1,
    roughness: 0.65,
    side: THREE.DoubleSide,
    // as the parts' faces (viewer.addPart): a little back, for the lines over them
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
    ...(ghost ? { transparent: true, depthWrite: false } : {}),
  })
  const mesh = new THREE.Mesh(geo, mat)
  if (ghost) mesh.renderOrder = 1 // after the new version
  return mesh
}

/** a changed place's line: 「足された +2.00 mm（100.5 mm²）」 */
export function changeText(kind: 'added' | 'removed', q: Place): string {
  return `${kind === 'added' ? '足された' : '削られた'} ${signed(q.peak)} mm（${q.area.toFixed(1)} mm²）`
}

/** the legend's 変わった所へ: a press goes to the next place of the kind; its state beside the button */
export interface CompareNav {
  go(kind: 'added' | 'removed'): void
  /** 「2/3 ・ +2.00 mm」, or '' before the first press */
  state(kind: 'added' | 'removed'): string
  /** how many places of the kind (0: no button) */
  count(kind: 'added' | 'removed'): number
}

/** the legend: the colour bar from the largest removal to the largest addition, and what the colours mean */
export function renderCompareLegend(
  el: HTMLElement,
  view: CompareView,
  names: { a: string; b: string },
  note: string,
  nav: CompareNav | null = null,
): void {
  const s = view.stats()
  const max = Math.max(s.added, -s.removed, view.tolerance)
  const tol = view.tolerance
  const title = document.createElement('div')
  title.className = 'thick-title'
  title.textContent = `版の比較（新しい版 ${names[view.newSide]}、前の版 ${names[view.oldSide]}）`
  const bar = document.createElement('div')
  bar.className = 'thick-bar'
  const c = new THREE.Color()
  const theme = compareColors()
  const stops: string[] = []
  for (let k = 0; k <= 20; k++) {
    const v = -max + (2 * max * k) / 20
    stops.push(`${css(changeColor(v, tol, max, c, theme))} ${(k / 20) * 100}%`)
  }
  bar.style.background = `linear-gradient(to right, ${stops.join(', ')})`
  const ticks = document.createElement('div')
  ticks.className = 'thick-ticks'
  for (const [text, at] of [
    [`${signed(-max)}`, '0%'],
    ['0', '50%'],
    [`${signed(max)} mm`, '100%'],
  ] as const) {
    const tick = document.createElement('span')
    tick.className = 'thick-tick'
    tick.dataset.at = at
    tick.style.left = at
    tick.textContent = text
    ticks.appendChild(tick)
  }
  const row = (color: THREE.Color, text: string, kind?: 'added' | 'removed') => {
    const r = document.createElement('div')
    r.className = 'draft-row'
    const sw = document.createElement('span')
    sw.className = 'draft-swatch'
    sw.style.background = css(color)
    const t = document.createElement('span')
    t.textContent = text
    r.append(sw, t)
    if (kind && nav && nav.count(kind) > 0) {
      // 変わった所へ (as the other legends' この色の面へ: spotnav.ts)
      const b = document.createElement('button')
      b.type = 'button'
      b.className = 'go-btn'
      b.dataset.go = `compare-${kind}`
      b.textContent = '変わった所へ'
      b.title = `${kind === 'added' ? '足された' : '削られた'}所へ、差の大きい順に寄る（押すたびに次。${nav.count(kind)} 所）`
      b.addEventListener('click', (e) => {
        e.stopPropagation()
        nav.go(kind)
      })
      const st = document.createElement('span')
      st.className = 'go-state'
      st.dataset.go = `compare-${kind}`
      st.textContent = nav.state(kind)
      r.append(b, st)
    }
    return r
  }
  const rows = [
    title,
    bar,
    ticks,
    row(theme.added, `足された（新しい版にだけある）最大 ${signed(s.added)} mm`, 'added'),
    row(theme.removed, `削られた（前の版にだけある）最大 ${signed(s.removed)} mm`, 'removed'),
    row(theme.same, `変わっていない（許容 ±${tol} mm の中）`),
  ]
  if (note) {
    const n = document.createElement('div')
    n.className = 'compare-note'
    n.textContent = note
    rows.push(n)
  }
  el.replaceChildren(...rows)
}
