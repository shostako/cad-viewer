/**
 * The legends' buttons that go to the places their colours point at (issue
 * #47 item 7; the places come from spots.ts): 肉厚's 薄い所へ, and on
 * 抜き勾配's 勾配不足 and 反対側 rows この色の面へ. Each press goes to the next
 * place (after the last, the first again); next to the button the legend says
 * which of how many, and what it measures there.
 *
 * The list is made at the press (a model can have many vertices: not on every
 * step of the threshold slider) and holds while what it was made from holds:
 * the colours on screen, their settings and the visible parts. When those
 * change, the next press starts again from the first place, and the marker of
 * the old list goes (reset).
 */
import { DRAFT_CLASS_NAMES } from './draft'
import { draftSpots, spotText, thinSpots, type Spot } from './spots'
import type { Viewer } from './viewer'

export type SpotKind = 'thin' | 'short' | 'opposite'

export interface SpotSource {
  /** what the heatmap on screen was painted from, or null when it is off */
  thin(): { values: ReadonlyMap<number, ArrayLike<number>>; threshold: number } | null
  /** the draft colouring's pull direction and required angle, or null when it is off */
  draft(): { dir: readonly [number, number, number]; required: number } | null
}

/** what the test hook reports (window.__cadSpot) */
export interface SpotInfo {
  kind: SpotKind
  index: number
  count: number
  spot: Spot
  text: string
}

const BUTTON: Record<SpotKind, string> = { thin: '薄い所へ', short: 'この色の面へ', opposite: 'この色の面へ' }
const TITLE: Record<SpotKind, string> = {
  thin: '閾値より薄い所へ、薄い順に寄る（押すたびに次）',
  short: `${DRAFT_CLASS_NAMES.short}の面へ、大きい順に寄る（押すたびに次）`,
  opposite: `${DRAFT_CLASS_NAMES.opposite}の面へ、大きい順に寄る（押すたびに次）`,
}

export class SpotNav {
  private kind: SpotKind | null = null
  private key = ''
  private list: Spot[] = []
  private index = -1
  /** numbers for the heatmap's value maps (a new map is a new heatmap) */
  private readonly mapIds = new WeakMap<object, number>()
  private nextMapId = 1
  private readonly states = new Map<SpotKind, HTMLElement>()

  private readonly viewer: Viewer
  private readonly source: SpotSource

  constructor(viewer: Viewer, source: SpotSource) {
    this.viewer = viewer
    this.source = source
  }

  /** the inputs of a list of this kind, as a string; null when that colouring is off */
  private keyOf(kind: SpotKind): string | null {
    const parts = `${this.viewer.modelGen}:${this.viewer
      .spotParts()
      .map((p) => p.partId)
      .join(',')}`
    if (kind === 'thin') {
      const t = this.source.thin()
      if (!t) return null
      let id = this.mapIds.get(t.values)
      if (id === undefined) this.mapIds.set(t.values, (id = this.nextMapId++))
      return `thin|${id}|${t.threshold}|${parts}`
    }
    const d = this.source.draft()
    if (!d) return null
    return `${kind}|${d.dir.join(',')}|${d.required}|${parts}`
  }

  /** the list of `kind` for what is on screen now (made again if that changed) */
  private listFor(kind: SpotKind): Spot[] | null {
    const key = this.keyOf(kind)
    if (key === null) return null
    if (this.kind !== kind || this.key !== key) {
      this.viewer.clearSpot()
      const parts = this.viewer.spotParts()
      if (kind === 'thin') {
        const t = this.source.thin()!
        this.list = thinSpots(parts, t.values, t.threshold)
      } else {
        const d = this.source.draft()!
        this.list = draftSpots(parts, d.dir, d.required, kind)
      }
      this.kind = kind
      this.key = key
      this.index = -1
    }
    return this.list
  }

  /** go to the next place of `kind` (the button's press) */
  next(kind: SpotKind): void {
    const list = this.listFor(kind)
    if (!list) return
    if (list.length) {
      this.index = (this.index + 1) % list.length
      const s = list[this.index]
      this.viewer.goToSpot(s, spotText(kind, s))
    }
    this.showStates()
  }

  /**
   * The colours or the parts changed (or went): if the list no longer holds,
   * forget it and take its marker away. Called after a change of settings,
   * of the visible parts, and when a colouring is turned off.
   */
  revalidate(): void {
    if (this.kind === null) return
    if (this.keyOf(this.kind) === this.key) return
    this.viewer.clearSpot()
    this.kind = null
    this.key = ''
    this.list = []
    this.index = -1
    this.showStates()
  }

  /** the place gone to last, for the E2E (null: none since the last change) */
  current(): SpotInfo | null {
    if (this.kind === null || this.index < 0 || this.keyOf(this.kind) !== this.key) return null
    const spot = this.list[this.index]
    return { kind: this.kind, index: this.index, count: this.list.length, spot, text: spotText(this.kind, spot) }
  }

  /** the button and its state for the thickness legend (call after renderThicknessLegend) */
  decorateThickness(legend: HTMLElement): void {
    const row = document.createElement('div')
    row.className = 'go-row'
    row.append(...this.control('thin'))
    legend.appendChild(row)
    this.revalidate()
    this.showStates()
  }

  /** the buttons and their states on the draft legend's 勾配不足 and 反対側 rows (after renderDraftLegend) */
  decorateDraft(legend: HTMLElement): void {
    for (const kind of ['short', 'opposite'] as const) {
      const row = legend.querySelector<HTMLElement>(`.draft-row[data-cls="${kind}"]`)
      if (row) row.append(...this.control(kind))
    }
    this.revalidate()
    this.showStates()
  }

  private control(kind: SpotKind): HTMLElement[] {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'go-btn'
    button.dataset.go = kind
    button.textContent = BUTTON[kind]
    button.title = TITLE[kind]
    button.addEventListener('click', (e) => {
      e.stopPropagation()
      this.next(kind)
    })
    const state = document.createElement('span')
    state.className = 'go-state'
    state.dataset.go = kind
    this.states.set(kind, state)
    return [button, state]
  }

  /** each state says where its list is: which place of how many, or that there is none */
  private showStates(): void {
    for (const [kind, el] of this.states) {
      if (!el.isConnected) {
        this.states.delete(kind)
        continue
      }
      el.textContent = this.kind === kind ? this.stateText(kind) : ''
    }
  }

  private stateText(kind: SpotKind): string {
    const n = this.list.length
    if (!n) return kind === 'thin' ? '値のある点が無い' : 'この色の面は無い'
    if (this.index < 0) return ''
    const s = this.list[this.index]
    if (kind === 'thin') {
      const t = this.source.thin()
      // none thinner than the threshold: the list is the one thinnest point
      if (t && n === 1 && s.value >= t.threshold) return `閾値より薄い所は無い。いちばん薄い所 ${spotText(kind, s)}`
    }
    return `${this.index + 1}/${n} ・ ${spotText(kind, s)}`
  }
}
