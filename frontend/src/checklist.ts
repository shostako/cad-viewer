/**
 * 問題の一覧 (issue #59 P1 1): what a molding check finds on the visible
 * parts, in one list to go through:
 *
 * - 薄肉: walls thinner than the 肉厚 threshold. A place is a run of thin
 *   vertices (spots.ts thinSpots); its value is the thinnest there.
 * - 勾配不足: faces short of the required draft for the pull direction. A
 *   place is a B-rep face, or a run of triangles of a mesh-format part
 *   (spots.ts draftSpots); its value is the draft angle at its marker.
 * - 反対側: faces that look away from the pull direction. The other mold half
 *   releases them: listed to check the parting, not as faults by themselves.
 *
 * What cannot be judged is counted apart (判定できない), never as fine:
 *
 * - a part without a volume (not closed, faces turned both ways, flat: the
 *   体積・重量 panel's reasons). Its inside is not known, so neither the
 *   thickness across its walls nor which way its faces look out: none of its
 *   places is listed.
 * - the vertices whose thickness has no value (the ray left the shape, no
 *   ball fits: the heatmap's データなし), counted by part.
 *
 * The conditions are the 肉厚 and 抜き勾配 folders' (the threshold and the
 * method; the pull direction and the required draft): the list says them.
 */
import { DRAFT_CLASS_NAMES, DRAFT_COLORS } from './draft'
import { ICON, icon } from './icons'
import { fmtNum } from './properties'
import { draftSpots, spotText, thinSpots, type Spot, type SpotPart } from './spots'
import { ONLY_ICON } from './tree'

export type CheckKind = 'thin' | 'short' | 'opposite'

export const CHECK_KIND_NAMES: Record<CheckKind, string> = {
  thin: '薄肉',
  short: DRAFT_CLASS_NAMES.short,
  opposite: DRAFT_CLASS_NAMES.opposite,
}

/** what the checks judge by; null: that check is not made */
export interface CheckConditions {
  thin: { threshold: number; methodName: string } | null
  draft: { dirLabel: string; dir: readonly [number, number, number]; required: number } | null
}

export interface CheckRow {
  kind: CheckKind
  spot: Spot
}

/** a part that cannot be judged (and why), or the vertices of a part without a thickness */
export interface Undecided {
  partId: number
  why: string
}

export interface CheckResult {
  /** 薄肉 (the thinnest first), then 勾配不足 and 反対側 (the largest first) */
  rows: CheckRow[]
  undecided: Undecided[]
}

/** the rows of one kind shown at most (the rest are counted: 「ほか 12 所」) */
export const CHECK_ROWS_MAX = 50

/**
 * Run the checks. `unjudged(partId)`: why a part cannot be judged at all, or
 * null. `values`: the thickness per vertex and part (the heatmap's: no value
 * is not > 0), for conditions.thin.
 */
export function runChecks(
  parts: readonly SpotPart[],
  unjudged: (partId: number) => string | null,
  conditions: CheckConditions,
  values: ReadonlyMap<number, ArrayLike<number>> | null,
): CheckResult {
  const judged: SpotPart[] = []
  const undecided: Undecided[] = []
  for (const part of parts) {
    const why = unjudged(part.partId)
    if (why) undecided.push({ partId: part.partId, why })
    else judged.push(part)
  }
  const rows: CheckRow[] = []
  if (conditions.thin && values) {
    const { threshold } = conditions.thin
    // thinSpots gives the one thinnest point when nothing is under the threshold: not a problem
    for (const spot of thinSpots(judged, values, threshold)) if (spot.value < threshold) rows.push({ kind: 'thin', spot })
    for (const part of judged) {
      const v = values.get(part.partId)
      const n = Math.floor(part.positions.length / 3)
      let none = 0
      for (let i = 0; i < n; i++) if (!v || !(v[i] > 0) || !Number.isFinite(v[i])) none++
      if (none) undecided.push({ partId: part.partId, why: `肉厚の値が出ない頂点 ${none} / ${n} 個` })
    }
  }
  if (conditions.draft) {
    const { dir, required } = conditions.draft
    for (const kind of ['short', 'opposite'] as const) {
      for (const spot of draftSpots(judged, dir, required, kind)) rows.push({ kind, spot })
    }
  }
  return { rows, undecided }
}

/** 「肉厚 1.5 mm 未満（レイ法）」「型開き +Z」「勾配 1.0° 未満」 */
function conditionItems(c: CheckConditions): string[] {
  const parts: string[] = []
  if (c.thin) parts.push(`肉厚 ${c.thin.threshold.toFixed(1)} mm 未満（${c.thin.methodName}）`)
  if (c.draft) parts.push(`型開き ${c.draft.dirLabel}`, `勾配 ${c.draft.required.toFixed(1)}° 未満`)
  return parts
}

/** 「肉厚 1.5 mm 未満（レイ法）・型開き +Z・勾配 1.0° 未満」 */
export function conditionsText(c: CheckConditions): string {
  return conditionItems(c).join('・')
}

/** v with d decimals; one that rounds to 0 has no sign (「0.0」, not 「-0.0」) */
function fixed(v: number, d: number): string {
  const t = v.toFixed(d)
  return /^-0\.?0*$/.test(t) ? t.slice(1) : t
}

/** where a place is, on its row: 「(25.0, 30.0, 15.0)」 (the copy has 3 decimals) */
function shortPoint(p: readonly number[]): string {
  return `(${p.map((v) => fixed(v, 1)).join(', ')})`
}

export interface CheckPanelHooks {
  /** go to the place (and show the colours of its kind) */
  go(row: CheckRow): void
  /** show the part alone */
  only(partId: number): void
  /** the part's name (as the part tree says it) */
  partName(partId: number): string
}

/** the colour mark of a row's kind: the colouring's own colour */
const KIND_COLOR: Record<CheckKind | 'undecided', string> = {
  thin: '#d90805', // the heatmap's red (thickness.ts RED)
  short: `#${DRAFT_COLORS.short.toString(16).padStart(6, '0')}`,
  opposite: `#${DRAFT_COLORS.opposite.toString(16).padStart(6, '0')}`,
  undecided: '#8c9ebf', // the heatmap's データなし (thickness.ts NO_DATA)
}

/**
 * The card in the right-hand column: its head (the counts, すべてコピー),
 * the conditions, then a row a place (its value, its part and where), the
 * places of a kind at most CHECK_ROWS_MAX, and the parts that could not be
 * judged. A row goes to its place; its button shows its part alone.
 */
export class CheckPanel {
  private readonly el: HTMLElement
  private readonly hooks: CheckPanelHooks
  private result: CheckResult | null = null
  private conditions: CheckConditions | null = null
  private current: CheckRow | null = null

  constructor(el: HTMLElement, hooks: CheckPanelHooks) {
    this.el = el
    this.hooks = hooks
  }

  get shown(): boolean {
    return !this.el.classList.contains('hidden')
  }

  /** the list on screen (the E2E reads it: window.__cadCheck) */
  get state(): { result: CheckResult | null; conditions: CheckConditions | null; current: CheckRow | null } {
    return { result: this.result, conditions: this.conditions, current: this.current }
  }

  hide(): void {
    this.el.classList.add('hidden')
    this.el.replaceChildren()
    this.result = null
    this.conditions = null
    this.current = null
  }

  /** a line instead of the list while it is being made (「肉厚を計算中…」) */
  showBusy(text: string): void {
    this.result = null
    this.current = null
    this.el.replaceChildren(this.head(null), line('check-busy', text))
    this.el.classList.remove('hidden')
  }

  show(result: CheckResult, conditions: CheckConditions): void {
    this.result = result
    this.conditions = conditions
    this.current = null
    const list = document.createElement('ul')
    list.className = 'check-list'
    for (const kind of ['thin', 'short', 'opposite'] as const) {
      const rows = result.rows.filter((r) => r.kind === kind)
      for (const row of rows.slice(0, CHECK_ROWS_MAX)) list.appendChild(this.placeRow(row))
      if (rows.length > CHECK_ROWS_MAX) {
        const more = line('check-more', `${CHECK_KIND_NAMES[kind]}: ほか ${rows.length - CHECK_ROWS_MAX} 所`)
        list.appendChild(wrapLi(more))
      }
    }
    for (const u of result.undecided) list.appendChild(this.undecidedRow(u))
    const body: HTMLElement[] = [this.head(result), items('check-counts', this.countItems(result)), items('check-conditions', conditionItems(conditions))]
    if (list.children.length) body.push(list)
    else body.push(line('check-none', 'この条件では見つからなかった'))
    this.el.replaceChildren(...body)
    this.el.classList.remove('hidden')
  }

  /** mark the row gone to last (null: none) */
  setCurrent(row: CheckRow | null): void {
    this.current = row
    for (const li of Array.from(this.el.querySelectorAll<HTMLElement>('.check-list li'))) {
      li.classList.toggle('current', !!row && (li as HTMLElement & { row?: CheckRow }).row === row)
    }
  }

  /** the whole list as tab-separated lines with a head line (Excel splits them into cells) */
  tsv(): string {
    const r = this.result
    if (!r || !this.conditions) return ''
    const cond = conditionsText(this.conditions)
    const out = [['種類', '値', '単位', '部品', 'X', 'Y', 'Z', '面積 (mm²)', '条件'].join('\t')]
    for (const row of r.rows) {
      const s = row.spot
      const value = row.kind === 'thin' ? fixed(s.value, 3) : fixed(s.value, 2)
      const unit = row.kind === 'thin' ? 'mm' : '°'
      const area = row.kind === 'thin' ? '' : s.area.toFixed(1)
      out.push([CHECK_KIND_NAMES[row.kind], value, unit, this.hooks.partName(s.partId), ...s.at.map((v) => fixed(v, 3)), area, cond].join('\t'))
    }
    for (const u of r.undecided) out.push(['判定できない', u.why, '', this.hooks.partName(u.partId), '', '', '', '', cond].join('\t'))
    return out.join('\n')
  }

  private head(result: CheckResult | null): HTMLElement {
    const head = document.createElement('div')
    head.className = 'check-head'
    const title = document.createElement('span')
    title.className = 'check-title'
    title.textContent = '問題の一覧'
    head.appendChild(title)
    if (!result) return head
    const copy = document.createElement('button')
    copy.type = 'button'
    copy.className = 'check-copy-all'
    copy.title = 'すべてコピー（Excel に貼れる形: 種類・値・単位・部品・X・Y・Z・面積・条件）'
    copy.append(icon(ICON.copy, 13), document.createTextNode('すべてコピー'))
    copy.addEventListener('click', () => {
      void navigator.clipboard.writeText(this.tsv()).then(
        () => flash(copy),
        () => undefined,
      )
    })
    head.appendChild(copy)
    return head
  }

  /** 「薄肉 3」「勾配不足 6」「反対側 6」「判定できない 1」 (the kinds checked) */
  private countItems(result: CheckResult): string[] {
    const n = (k: CheckKind) => result.rows.filter((r) => r.kind === k).length
    const parts = (['thin', 'short', 'opposite'] as const)
      .filter((k) => (k === 'thin' ? this.conditions?.thin : this.conditions?.draft))
      .map((k) => `${CHECK_KIND_NAMES[k]} ${n(k)}`)
    if (result.undecided.length) parts.push(`判定できない ${result.undecided.length}`)
    return parts
  }

  private placeRow(row: CheckRow): HTMLLIElement {
    const s = row.spot
    const li = document.createElement('li') as HTMLLIElement & { row?: CheckRow }
    li.row = row
    li.dataset.kind = row.kind
    const go = document.createElement('button')
    go.type = 'button'
    go.className = 'check-go'
    go.title = 'この所へ寄る'
    const mark = document.createElement('span')
    mark.className = 'check-mark'
    mark.style.background = KIND_COLOR[row.kind]
    const main = document.createElement('span')
    main.className = 'check-main'
    const value = document.createElement('span')
    value.className = 'check-value'
    value.textContent = spotText(row.kind, s)
    if (row.kind !== 'thin') {
      const area = document.createElement('span')
      area.className = 'check-area'
      area.textContent = ` ${fmtNum(s.area, 1)} mm²`
      value.appendChild(area)
    }
    const what = document.createElement('span')
    what.className = 'check-what'
    const face = s.faceId === null ? '' : ` 面#${s.faceId}`
    what.textContent = `${CHECK_KIND_NAMES[row.kind]} · ${this.hooks.partName(s.partId)}${face}`
    const where = document.createElement('span')
    where.className = 'check-where'
    where.textContent = shortPoint(s.at)
    main.append(value, what, where)
    go.append(mark, main)
    go.addEventListener('click', () => this.hooks.go(row))
    li.append(go, this.onlyButton(s.partId))
    return li
  }

  private undecidedRow(u: Undecided): HTMLLIElement {
    const li = document.createElement('li')
    li.dataset.kind = 'undecided'
    const mark = document.createElement('span')
    mark.className = 'check-mark'
    mark.style.background = KIND_COLOR.undecided
    const main = document.createElement('span')
    main.className = 'check-main'
    const value = document.createElement('span')
    value.className = 'check-value'
    value.textContent = '判定できない'
    const what = document.createElement('span')
    what.className = 'check-what'
    what.textContent = `${this.hooks.partName(u.partId)} · ${u.why}`
    main.append(value, what)
    const box = document.createElement('span')
    box.className = 'check-go check-static'
    box.append(mark, main)
    li.append(box, this.onlyButton(u.partId))
    return li
  }

  private onlyButton(partId: number): HTMLButtonElement {
    const b = document.createElement('button')
    b.type = 'button'
    b.className = 'check-only'
    b.title = 'この部品だけ表示'
    b.setAttribute('aria-label', `${this.hooks.partName(partId)} だけ表示`)
    b.innerHTML = ONLY_ICON // the part tree's これだけ表示: the same picture for the same act
    b.addEventListener('click', (e) => {
      e.stopPropagation()
      this.hooks.only(partId)
    })
    return b
  }
}

function line(cls: string, text: string): HTMLElement {
  const d = document.createElement('div')
  d.className = cls
  d.textContent = text
  return d
}

/** a line of items joined by 「・」 that wraps between them, never inside one */
function items(cls: string, texts: string[]): HTMLElement {
  const d = document.createElement('div')
  d.className = cls
  texts.forEach((t, i) => {
    const span = document.createElement('span')
    span.className = 'check-item'
    span.textContent = i < texts.length - 1 ? `${t}・` : t
    d.appendChild(span)
  })
  return d
}

function wrapLi(child: HTMLElement): HTMLLIElement {
  const li = document.createElement('li')
  li.className = 'check-more-row'
  li.appendChild(child)
  return li
}

/** the copy's tick for a moment */
function flash(el: HTMLElement): void {
  el.classList.add('done')
  setTimeout(() => el.classList.remove('done'), 1200)
}
