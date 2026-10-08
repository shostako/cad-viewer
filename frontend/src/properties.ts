/** Volume / area / weight panel (bottom right).
 *
 * The server sends exact per-part values (GET /properties); this panel sums
 * the parts that are visible in the tree, and turns volume into a weight with
 * the chosen resin's specific gravity. A part without a volume (open, curves
 * only, ...) is listed but never counted: a partial total would understate
 * the weight without saying so.
 */
import type { ModelProperties, PartProperties, PropsReason } from './api'

/** specific gravity (g/cm³) of common moulding resins */
export const RESIN_DENSITY: Record<string, number> = {
  PMMA: 1.19,
  PC: 1.2,
  ABS: 1.05,
  PP: 0.9,
  PA66: 1.14,
  POM: 1.41,
  PS: 1.05,
}
export const RESIN_NAMES = Object.keys(RESIN_DENSITY)
export const OTHER_RESIN = 'その他'

export const REASON_TEXT: Record<PropsReason, string> = {
  open: '閉じていない',
  no_faces: '面がない',
  degenerate: '厚みがない',
  winding: '面の向きが不揃い',
  failed: '計算できない',
}

const formatters = new Map<number, Intl.NumberFormat>()
/** ja-JP grouping, fixed number of decimals */
export function fmtNum(x: number, digits: number): string {
  let f = formatters.get(digits)
  if (!f) {
    f = new Intl.NumberFormat('ja-JP', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    formatters.set(digits, f)
  }
  return f.format(x)
}

/** grams from mm³ and g/cm³ */
export const massGrams = (mm3: number, density: number): number => (mm3 / 1000) * density

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

export class PropertiesPanel {
  private root: HTMLElement
  private isVisible: (id: number) => boolean
  private onLayout: () => void
  private data: ModelProperties | null = null
  private density = RESIN_DENSITY.PMMA
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
  private noteEl = el('div', 'props-note')

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
    this.totalEl.append(this.totalTitle, dl)
    root.replaceChildren(head, this.statusEl, this.wrap, this.totalEl, this.noteEl)
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

  setDensity(density: number, resin: string): void {
    this.density = density
    this.densityEl.textContent =
      resin === OTHER_RESIN ? `比重 ${fmtDensity(density)} g/cm³` : `${resin} ${fmtDensity(density)} g/cm³`
    if (this.data) this.refresh()
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
    this.wrap.style.maxHeight = `${Math.max(maxPanelPx - rest, 44)}px`
  }

  private showStatus(text: string): void {
    this.statusEl.textContent = text
    this.statusEl.classList.remove('hidden')
    this.wrap.classList.add('hidden')
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

    this.wrap.classList.toggle('hidden', !v.rows || v.rows.length === 0)
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
    this.totalVolume.textContent =
      t.volume !== null
        ? `${fmtNum(t.volume / 1000, 3)} cm³（${fmtNum(t.volume, t.volume < 100 ? 2 : 0)} mm³）`
        : t.reason
          ? noVolume(t.reason)
          : '—'
    this.totalArea.textContent = t.area !== null ? `${fmtNum(t.area / 100, 2)} cm²` : '—'
    this.totalMass.textContent = t.volume !== null ? `${fmtNum(massGrams(t.volume, this.density), 2)} g` : '—'

    this.noteEl.textContent = v.notes.join(' ／ ')
    this.noteEl.classList.toggle('hidden', v.notes.length === 0)
    this.onLayout()
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
