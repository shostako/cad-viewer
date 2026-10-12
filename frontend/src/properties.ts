/** Volume / area / weight panel (bottom right).
 *
 * The server sends exact per-part values (GET /properties); this panel sums
 * the parts that are visible in the tree, and turns volume into a weight with
 * the specific gravity of the material in use (materials.ts), or one typed by hand. A part without a volume (open, curves
 * only, ...) is listed but never counted: a partial total would understate
 * the weight without saying so.
 *
 * Below the weight: the projected area along the mold-opening direction (the
 * draft analysis's setting) of the visible parts, and the clamping force it
 * takes at the chosen cavity pressure (issue #47 item 4). The area comes from
 * the display mesh (GET /projected_area): an estimate, like the thickness.
 */
import type { ModelProperties, PartProperties, PropsReason } from './api'
import { SOURCE, type Cell, type ReportTable } from './report'
import { fmtNum } from './sizes'

export const REASON_TEXT: Record<PropsReason, string> = {
  open: '閉じていない',
  no_faces: '面がない',
  degenerate: '厚みがない',
  winding: '面の向きが不揃い',
  failed: '計算できない',
}

export { fmtNum }

/** grams from mm³ and g/cm³ */
export const massGrams = (mm3: number, density: number): number => (mm3 / 1000) * density

/** standard gravity: 1 tf = 9806.65 N */
const G = 9.80665
/** clamping force from a projected area (mm²) and a cavity pressure (MPa = N/mm²) */
export function clampForce(areaMm2: number, mpa: number): { kN: number; tf: number } {
  const newtons = areaMm2 * mpa
  return { kN: newtons / 1000, tf: newtons / (1000 * G) }
}

/** 40 / 37.5 / 0.25: as typed, without trailing zeros */
export const fmtPressure = (mpa: number): string => String(Number(mpa.toFixed(3)))

/** what the projected-area rows show: `axis` names the pull direction (Z, −X, 選んだ向き, ...) */
export type ProjectionState =
  | { state: 'loading'; axis: string }
  | { state: 'ok'; axis: string; area: number }
  | { state: 'error'; axis: string; message: string }

/**
 * what the weight, the projected area and the clamping force are of (#59 P1):
 * the parts shown as modelled; a runner, a sprue and the other cavities of a
 * multi-cavity mould are not in them. The 記録's note, and the values' tooltips
 */
export const SCOPE_NOTE = '重量・投影面積・型締力は、表示している部品の分だけ（ランナー・スプルーは入らない。多数個取りなら取り数を掛ける）'
/** the same on a value's tooltip */
const SCOPE_TIP = 'ランナー・スプルーの分は入らない（多数個取りなら取り数を掛ける）'

/** what the projected area is, on its row's tooltip */
export const projectionTitle = (axis: string): string =>
  `投影面積: 型開き方向（${axis}）へ投影した、表示している部品の影の面積。表示用メッシュから出す目安（B-rep の真値ではない）。${SCOPE_TIP}`

/** 1.19 / 1.20 / 0.90 / 1.234: three decimals, one trailing zero dropped */
export function fmtDensity(d: number): string {
  const s = d.toFixed(3)
  return s.endsWith('0') ? s.slice(0, -1) : s
}

const noVolume = (reason: PropsReason | null): string => `体積なし（${REASON_TEXT[reason ?? 'open']}）`

export interface PropsView {
  /** table rows (visible parts), or null for a one-part model */
  rows: PartProperties[] | null
  title: string
  total: { volume: number | null; area: number | null; reason: PropsReason | null }
  notes: string[]
}

/** what to show for these data, given which parts are visible */
export function buildView(d: ModelProperties, isVisible: (id: number) => boolean): PropsView {
  const n = d.parts.length
  const visible = d.parts.filter((p) => isVisible(p.id))
  const withVolume = visible.filter((p) => p.volume !== null)
  const notes: string[] = []
  const none = { volume: null, area: null, reason: null }
  let view: PropsView
  if (n === 1) {
    const p = visible[0]
    view = p
      ? {
          rows: null,
          title: '',
          total: { volume: p.volume, area: p.reason === 'no_faces' ? null : p.area, reason: p.reason },
          notes,
        }
      : { rows: null, title: '表示中の部品なし', total: none, notes }
  } else if (visible.length === 0) {
    view = { rows: [], title: '表示中の部品なし', total: none, notes }
  } else {
    // volume / weight: the parts with a volume; area: every part with faces
    // (an open surface has an area too), the same rule as the backend total
    const withArea = visible.filter((p) => p.area !== null && p.reason !== 'no_faces')
    view = {
      rows: visible,
      title: `合計（表示中 ${visible.length}/${n} 部品）`,
      total: {
        volume: withVolume.length ? withVolume.reduce((s, p) => s + p.volume!, 0) : null,
        area: withArea.length ? withArea.reduce((s, p) => s + p.area!, 0) : null,
        reason: null,
      },
      notes,
    }
    // parts whose computation failed have no area either: say so separately,
    // or the "面積は含める" note would be wrong for them
    const failed = visible.filter((p) => p.reason === 'failed').length
    // parts without faces (curves only) have neither volume nor area: the row
    // says so, and they change no total
    const noFaces = visible.filter((p) => p.reason === 'no_faces').length
    const k = visible.length - withVolume.length - failed - noFaces
    if (k > 0) notes.push(`体積なしの ${k} 部品は体積・重量の合計に含めない（面積は含める）`)
    if (failed > 0) notes.push(`計算できなかった ${failed} 部品は合計に含めない`)
  }
  if (d.source === 'mesh') notes.push('メッシュの三角形から計算（単位は mm とみなす）')
  return view
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, id?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag)
  if (id) e.id = id
  if (text !== undefined) e.textContent = text
  return e
}

/** the parts table never gets shorter than this (about two rows) */
const TABLE_MIN_PX = 44
/** whether the parts table is open (it starts folded: the total is what one reads first) */
const PARTS_OPEN_KEY = 'cad-viewer:props-parts'

function loadPartsOpen(): boolean {
  try {
    return localStorage.getItem(PARTS_OPEN_KEY) === '1'
  } catch {
    return false // storage unavailable (private window, blocked site data)
  }
}

export class PropertiesPanel {
  private root: HTMLElement
  private isVisible: (id: number) => boolean
  private onLayout: () => void
  private data: ModelProperties | null = null
  private density = 1.19
  private material = 'PMMA'
  /** the gravity was typed by hand (the material's own is another) */
  private densityByHand = false
  /** the material's values are its general standard (not edited) */
  private densityStandard = true
  private queued = false

  private densityEl = el('span', 'props-density')
  private statusEl = el('div', 'props-status')
  private wrap = el('div', 'props-parts-wrap')
  private tbody = el('tbody')
  private totalEl = el('div', 'props-total')
  private totalTitle = el('div', 'props-total-title')
  private totalVolume = el('dd', 'props-total-volume')
  private totalArea = el('dd', 'props-total-area')
  private totalMass = el('dd', 'props-total-mass')
  private projLabel = el('dt', 'props-proj-label')
  private totalProj = el('dd', 'props-total-proj')
  private clampLabel = el('dt', 'props-clamp-label')
  private totalClamp = el('dd', 'props-total-clamp')
  private projection: ProjectionState | null = null
  private pressure = 40
  /** the projected-area row folded away (a short window): the force's row stays */
  private compact = false
  /** that row's height with its gap, last seen while shown */
  private projRowPx = 20
  private noteEl = el('div', 'props-note')
  /** 部品ごとの値（N 部品）: opens and folds the parts table */
  private partsToggle = el('button', 'props-parts-toggle')
  private partsOpen = loadPartsOpen()

  constructor(root: HTMLElement, isVisible: (id: number) => boolean, onLayout: () => void) {
    this.root = root
    this.isVisible = isVisible
    this.onLayout = onLayout
    const head = el('div', 'props-head')
    head.append(el('span', undefined, '体積・重量'), this.densityEl)
    const table = el('table', 'props-parts')
    const tr = el('tr')
    for (const h of ['部品', '体積 cm³', '表面積 cm²', '重量 g']) tr.appendChild(el('th', undefined, h))
    table.append(el('thead'), this.tbody)
    table.tHead!.appendChild(tr)
    this.wrap.appendChild(table)
    const dl = el('dl')
    dl.append(el('dt', undefined, '体積'), this.totalVolume)
    dl.append(el('dt', undefined, '表面積'), this.totalArea)
    dl.append(el('dt', undefined, '重量'), this.totalMass)
    dl.append(this.projLabel, this.totalProj, this.clampLabel, this.totalClamp)
    this.totalEl.append(this.totalTitle, dl)
    this.partsToggle.type = 'button'
    this.partsToggle.setAttribute('aria-controls', 'props-parts-wrap')
    this.partsToggle.addEventListener('click', () => {
      this.partsOpen = !this.partsOpen
      try {
        localStorage.setItem(PARTS_OPEN_KEY, this.partsOpen ? '1' : '0')
      } catch {
        /* best-effort */
      }
      if (this.data) this.render()
    })
    // the total first; the parts table below it, folded until asked for
    root.replaceChildren(head, this.statusEl, this.totalEl, this.noteEl, this.partsToggle, this.wrap)
    root.classList.add('hidden') // no onLayout here: the caller is still being constructed
  }

  showLoading(): void {
    this.data = null
    this.showStatus('計算中…')
  }

  showError(msg: string): void {
    this.data = null
    this.showStatus(`計算できない: ${msg}`)
  }

  setData(d: ModelProperties): void {
    this.data = d
    this.render()
  }

  /** drop the data and hide (model teardown, 2D drawing) */
  hide(): void {
    this.data = null
    this.root.classList.add('hidden')
    this.onLayout()
  }

  /**
   * The specific gravity the weight is from, and the material it is of:
   * byHand, typed for it in the 比重 field; standard, the material's general
   * standard (not edited in 材料の基準).
   */
  setDensity(density: number, material: string, byHand: boolean, standard: boolean): void {
    this.density = density
    this.material = material
    this.densityByHand = byHand
    this.densityStandard = standard
    this.densityEl.textContent = `${material} ${fmtDensity(density)} g/cm³${byHand ? '（手入力）' : ''}`
    if (this.data) this.refresh()
  }

  /**
   * The panel's values for the 記録 (report.ts), the numbers and decimals the
   * panel shows: the total of the visible parts (and each one's, in an
   * assembly), the resin, the projected area and the clamping force. null
   * while there are none (being computed, failed, hidden).
   */
  reportTables(): ReportTable[] | null {
    const d = this.data
    if (!d || this.root.classList.contains('hidden')) return null
    const v = buildView(d, this.isVisible)
    const src = d.source === 'mesh' ? SOURCE.meshFile : SOURCE.brep
    const num = (x: number | null, digits: number): Cell => (x === null ? '—' : { n: x, d: digits })
    const t = v.total
    const volume: Cell = t.volume !== null ? { n: t.volume / 1000, d: 3 } : t.reason ? noVolume(t.reason) : '—'
    const densityFrom = this.densityByHand
      ? `${SOURCE.input}（${this.material} に手で）`
      : `材料 ${this.material} の値（${this.densityStandard ? '一般的な基準' : '直した値'}）`
    const rows: Cell[][] = [
      ['体積', volume, 'cm³', src],
      ['表面積', num(t.area === null ? null : t.area / 100, 2), 'cm²', src],
      ['比重', fmtDensity(this.density), 'g/cm³', densityFrom],
      ['重量', num(t.volume === null ? null : massGrams(t.volume, this.density), 2), 'g', `${src} × 比重`],
    ]
    const p = this.projection
    if (p) {
      const mpa = fmtPressure(this.pressure)
      if (p.state === 'ok') {
        const f = clampForce(p.area, this.pressure)
        rows.push(
          ['投影面積', { n: p.area / 100, d: 2 }, 'cm²', `${SOURCE.mesh}（型開き ${p.axis}）`],
          ['型内圧', mpa, 'MPa', SOURCE.input],
          ['型締力', { n: f.kN, d: 1 }, 'kN', SOURCE.estimate],
          ['型締力', { n: f.tf, d: 1 }, 'tf', SOURCE.estimate],
        )
      } else {
        rows.push(
          ['投影面積', p.state === 'loading' ? '計算中' : '計算できない', 'cm²', `${SOURCE.mesh}（型開き ${p.axis}）`],
          ['型内圧', mpa, 'MPa', SOURCE.input],
        )
      }
    }
    const note = [v.title, ...v.notes, SCOPE_NOTE].filter(Boolean).join(' ／ ')
    const tables: ReportTable[] = [{ title: '体積・重量', note, head: ['項目', '値', '単位', '出どころ'], rows }]
    if (v.rows?.length) {
      tables.push({
        title: '部品ごとの体積・重量',
        head: ['部品', '体積 cm³', '表面積 cm²', '重量 g', '出どころ'],
        rows: v.rows.map((r) => {
          const area = r.reason === 'no_faces' ? null : r.area
          return [
            r.name,
            r.volume !== null ? { n: r.volume / 1000, d: 3 } : noVolume(r.reason),
            num(area === null ? null : area / 100, 2),
            num(r.volume === null ? null : massGrams(r.volume, this.density), 2),
            src,
          ]
        }),
      })
    }
    return tables
  }

  /** cavity pressure (MPa) for the clamping force */
  setPressure(mpa: number): void {
    this.pressure = mpa
    if (this.data) this.refresh()
  }

  /**
   * the projected area of the visible parts (null: none to show). Drawn at
   * once, not on the next microtask: a load fits the view right after asking,
   * and the rows must already take their room then.
   */
  setProjection(p: ProjectionState | null): void {
    this.projection = p
    if (this.data) this.render()
  }

  /**
   * Fold the projected-area row away (on), or show it again; for the corner
   * layout, which folds it before the GUI would have to shrink past its minimum.
   */
  setCompact(on: boolean): void {
    if (on === this.compact) return
    if (on && !this.totalProj.classList.contains('hidden')) {
      this.projRowPx = this.totalProj.offsetHeight + 2 // the dl's row gap
    }
    this.compact = on
    if (this.data) this.renderProjection()
  }

  /** what showing the folded row again would add to the panel (0 when it is not folded) */
  foldedPx(): number {
    return this.compact && this.projection && this.data && !this.root.classList.contains('hidden') ? this.projRowPx : 0
  }

  /** re-render once for any number of calls in the same task (a tree group toggles its children one by one) */
  refresh(): void {
    if (this.queued) return
    this.queued = true
    queueMicrotask(() => {
      this.queued = false
      if (this.data) this.render()
    })
  }

  /** cap the table so the whole panel fits in maxPanelPx; the total stays visible */
  fitHeight(maxPanelPx: number): void {
    if (this.root.classList.contains('hidden')) return
    const rest = this.root.offsetHeight - this.wrap.offsetHeight
    this.wrap.style.maxHeight = `${Math.max(maxPanelPx - rest, TABLE_MIN_PX)}px`
  }

  /** the smallest height fitHeight can leave the panel at (0 while hidden) */
  minHeight(): number {
    if (this.root.classList.contains('hidden')) return 0
    const rest = this.root.offsetHeight - this.wrap.offsetHeight
    return rest + (this.wrap.classList.contains('hidden') ? 0 : TABLE_MIN_PX)
  }

  private showStatus(text: string): void {
    this.statusEl.textContent = text
    this.statusEl.classList.remove('hidden')
    this.wrap.classList.add('hidden')
    this.partsToggle.classList.add('hidden')
    this.totalEl.classList.add('hidden')
    this.noteEl.classList.add('hidden')
    this.root.classList.remove('hidden')
    this.onLayout()
  }

  private render(): void {
    const d = this.data!
    const v = buildView(d, this.isVisible)
    this.statusEl.classList.add('hidden')
    this.root.classList.remove('hidden')

    const rows = v.rows?.length ?? 0
    this.partsToggle.classList.toggle('hidden', rows === 0)
    this.partsToggle.textContent = `部品ごとの値（${rows} 部品）`
    this.partsToggle.setAttribute('aria-expanded', String(this.partsOpen))
    this.wrap.classList.toggle('hidden', rows === 0 || !this.partsOpen)
    this.tbody.replaceChildren()
    for (const p of v.rows ?? []) {
      const tr = el('tr')
      tr.dataset.partId = String(p.id)
      const name = el('td', undefined, p.name) // file-supplied text: textContent only
      name.className = 'name'
      name.title = p.name
      tr.append(name, ...this.cells(p.volume, p.reason === 'no_faces' ? null : p.area, p.reason))
      this.tbody.appendChild(tr)
    }

    this.totalEl.classList.remove('hidden')
    this.totalTitle.textContent = v.title
    this.totalTitle.classList.toggle('hidden', !v.title)
    const t = v.total
    if (t.volume !== null) {
      // the cm³ first; the mm³ beside it, smaller (one line in the 264 px column)
      const mm3 = el('span', undefined, `（${fmtNum(t.volume, t.volume < 100 ? 2 : 0)} mm³）`)
      mm3.className = 'sub'
      this.totalVolume.replaceChildren(`${fmtNum(t.volume / 1000, 3)} cm³`, mm3)
    } else {
      this.totalVolume.textContent = t.reason ? noVolume(t.reason) : '—'
    }
    this.totalArea.textContent = t.area !== null ? `${fmtNum(t.area / 100, 2)} cm²` : '—'
    this.totalMass.textContent = t.volume !== null ? `${fmtNum(massGrams(t.volume, this.density), 2)} g` : '—'
    this.totalMass.title = `表示している部品の重量。ショット重量には、${SCOPE_TIP}`
    this.renderProjection()

    this.noteEl.textContent = v.notes.join(' ／ ')
    this.noteEl.classList.toggle('hidden', v.notes.length === 0)
    this.onLayout()
  }

  /**
   * Two rows, one line each (the column is 264 px): 投影 59.99 cm²（Z・目安）
   * and 型締力 240.0 kN（24.5 tf・40 MPa）. Labels of three characters at most:
   * the volume's value leaves the label column 49 px, and 投影面積 would wrap.
   */
  private renderProjection(): void {
    const p = this.projection
    for (const e of [this.clampLabel, this.totalClamp]) e.classList.toggle('hidden', !p)
    for (const e of [this.projLabel, this.totalProj]) e.classList.toggle('hidden', !p || this.compact)
    if (!p) return
    const sub = (text: string): HTMLSpanElement => {
      const s = el('span', undefined, text)
      s.className = 'sub'
      return s
    }
    const mpa = `${fmtPressure(this.pressure)} MPa`
    this.projLabel.textContent = '投影' // 投影面積 (the tooltip says so)
    this.clampLabel.textContent = '型締力'
    this.totalProj.title = projectionTitle(p.axis)
    if (p.state === 'ok') {
      const cm2 = `${fmtNum(p.area / 100, 2)} cm²`
      this.totalProj.replaceChildren(cm2, sub(`（${p.axis}・目安）`))
      const f = clampForce(p.area, this.pressure)
      this.totalClamp.replaceChildren(`${fmtNum(f.kN, 1)} kN`, sub(`（${fmtNum(f.tf, 1)} tf・${mpa}）`))
      // the folded row's value stays at hand
      this.totalClamp.title = `投影面積 ${cm2}（${p.axis}・目安）× 型内圧 ${mpa}。${SCOPE_TIP}`
    } else {
      const what = p.state === 'loading' ? '計算中…' : '計算できない'
      this.totalProj.replaceChildren(what, sub(`（${p.axis}・目安）`))
      if (p.state === 'error') this.totalProj.title = `計算できない: ${p.message}`
      this.totalClamp.replaceChildren('—', sub(`（${mpa}）`))
      this.totalClamp.title = p.state === 'loading' ? '投影面積を計算中' : `投影面積を計算できない: ${p.message}`
    }
  }

  private cells(volume: number | null, area: number | null, reason: PropsReason | null): HTMLTableCellElement[] {
    const td = (text: string, cls: string, none = false) => {
      const c = el('td', undefined, text)
      c.className = none ? `${cls} none` : cls
      return c
    }
    return [
      volume !== null ? td(fmtNum(volume / 1000, 3), 'vol') : td(noVolume(reason), 'vol', true),
      area !== null ? td(fmtNum(area / 100, 2), 'area') : td('—', 'area', true),
      volume !== null ? td(fmtNum(massGrams(volume, this.density), 2), 'mass') : td('—', 'mass', true),
    ]
  }
}
