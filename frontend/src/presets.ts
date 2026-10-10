/**
 * 判定の基準 (issue #59 P1 10): the check conditions per material, the
 * thickness's lower limit and the draft a face needs, each with where it
 * comes from (its basis). Kept apart from the specific gravity (体積・重量's
 * 樹脂): choosing one does not choose the other.
 *
 * The app does not know a material's limits. Every material starts at the
 * app's own defaults (1.5 mm, 1.0°) with its basis 未設定, to be set from
 * one's own standard (社内の目安, a maker's design guide, ...). They are kept
 * in this browser; the 問題の一覧 and the 記録 say the one in use and its basis.
 */
import { DRAFT_MAX_DEG } from './draft'
import { RESIN_NAMES } from './properties'

export interface Basis {
  /** mm: thinner is 薄肉 */
  thin: number
  /** degrees: less is 勾配不足 */
  draft: number
  /** where the values come from ('' : not said) */
  source: string
}

/** the materials, as the 体積・重量 panel names its resins */
export const BASIS_MATERIALS: readonly string[] = RESIN_NAMES
export const BASIS_DEFAULT: Basis = { thin: 1.5, draft: 1.0, source: '' }
/** a basis not said */
export const BASIS_UNSET = '未設定'
export const THIN_MIN = 0.1
export const THIN_MAX = 10
const SOURCE_MAX = 200
const KEY = 'cad-viewer:check-basis'

export interface BasisStore {
  /** the material in use ('' : the values set by hand) */
  selected: string
  bases: Record<string, Basis>
}

/** to the folders' step (0.1): the value saved is the one the check uses */
export const toStep = (v: number): number => Math.round(v * 10) / 10

/** a thickness and a draft the folders accept, a basis of text */
export function validBasis(b: unknown): b is Basis {
  const x = b as Basis
  return (
    !!x &&
    typeof x.thin === 'number' &&
    Number.isFinite(x.thin) &&
    x.thin >= THIN_MIN &&
    x.thin <= THIN_MAX &&
    typeof x.draft === 'number' &&
    Number.isFinite(x.draft) &&
    x.draft >= 0 &&
    x.draft <= DRAFT_MAX_DEG &&
    typeof x.source === 'string'
  )
}

/** what this browser keeps (anything it cannot read: the defaults) */
export function loadBases(): BasisStore {
  const bases: Record<string, Basis> = Object.fromEntries(BASIS_MATERIALS.map((m) => [m, { ...BASIS_DEFAULT }]))
  let selected = ''
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? '{}') ?? {}
    for (const m of BASIS_MATERIALS) {
      const b = saved.bases?.[m]
      if (validBasis(b)) bases[m] = { thin: toStep(b.thin), draft: toStep(b.draft), source: b.source.slice(0, SOURCE_MAX) }
    }
    if (typeof saved.selected === 'string' && BASIS_MATERIALS.includes(saved.selected)) selected = saved.selected
  } catch {
    /* defaults (storage unavailable, or not JSON) */
  }
  return { selected, bases }
}

export function saveBases(store: BasisStore): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(store))
  } catch {
    /* best-effort */
  }
}

/** 「PC（根拠: 社内の目安）」「PP（根拠: 未設定）」: what the conditions say of the basis in use */
export function basisText(material: string, b: Basis): string {
  return `${material}（根拠: ${b.source.trim() || BASIS_UNSET}）`
}

export interface BasisPopHooks {
  /** the bases as edited: saved (the one in use is applied again) */
  save: (bases: Record<string, Basis>) => void
}

/**
 * The card of 基準を編集… (問題の一覧): a row a material, its thickness, its
 * draft and its basis. 保存 keeps them (and applies the one in use again);
 * values out of range are not saved (the card says which).
 */
export class BasisPop {
  readonly el: HTMLElement
  private readonly hooks: BasisPopHooks
  private readonly rows = new Map<string, { thin: HTMLInputElement; draft: HTMLInputElement; source: HTMLInputElement }>()
  private readonly note: HTMLElement

  constructor(el: HTMLElement, hooks: BasisPopHooks) {
    this.el = el
    this.hooks = hooks
    el.setAttribute('role', 'dialog')
    el.setAttribute('aria-labelledby', 'basis-title')
    const title = document.createElement('div')
    title.id = 'basis-title'
    title.textContent = '判定の基準'
    const lead = document.createElement('div')
    lead.className = 'basis-lead'
    lead.textContent = '材料ごとの肉厚の下限と必要な勾配。初めはどれもアプリの既定の値（根拠: 未設定）なので、社内の基準などで直して、根拠を書く'
    const table = document.createElement('table')
    table.className = 'basis-table'
    const head = document.createElement('tr')
    for (const h of ['材料', '肉厚 mm', '勾配 °', '根拠']) {
      const th = document.createElement('th')
      th.textContent = h
      head.appendChild(th)
    }
    const thead = document.createElement('thead')
    thead.appendChild(head)
    const tbody = document.createElement('tbody')
    for (const m of BASIS_MATERIALS) {
      const tr = document.createElement('tr')
      tr.dataset.material = m
      const name = document.createElement('td')
      name.textContent = m
      const num = (min: number, max: number, cls: string) => {
        const i = document.createElement('input')
        i.type = 'number'
        i.min = String(min)
        i.max = String(max)
        i.step = '0.1'
        i.className = cls
        return i
      }
      const thin = num(THIN_MIN, THIN_MAX, 'basis-thin')
      const draft = num(0, DRAFT_MAX_DEG, 'basis-draft')
      const source = document.createElement('input')
      source.type = 'text'
      source.className = 'basis-source'
      source.maxLength = SOURCE_MAX
      source.placeholder = BASIS_UNSET
      tr.appendChild(name)
      for (const input of [thin, draft, source]) {
        const td = document.createElement('td')
        td.appendChild(input)
        tr.appendChild(td)
      }
      tbody.appendChild(tr)
      this.rows.set(m, { thin, draft, source })
    }
    table.append(thead, tbody)
    this.note = document.createElement('div')
    this.note.id = 'basis-note'
    const buttons = document.createElement('div')
    buttons.className = 'report-buttons'
    const reset = document.createElement('button')
    reset.type = 'button'
    reset.id = 'basis-defaults'
    reset.textContent = '既定に戻す'
    reset.title = 'どの材料もアプリの既定の値（根拠: 未設定）にする（保存で決まる）'
    reset.addEventListener('click', () => this.fill(Object.fromEntries(BASIS_MATERIALS.map((m) => [m, { ...BASIS_DEFAULT }]))))
    const save = document.createElement('button')
    save.type = 'button'
    save.id = 'basis-save'
    save.textContent = '保存'
    save.addEventListener('click', () => this.trySave())
    buttons.append(reset, save)
    el.replaceChildren(title, lead, table, this.note, buttons)
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopPropagation()
      this.hide()
    })
  }

  get shown(): boolean {
    return !this.el.classList.contains('hidden')
  }

  show(bases: Record<string, Basis>): void {
    this.fill(bases)
    this.note.textContent = ''
    this.el.classList.remove('hidden')
  }

  hide(): void {
    this.el.classList.add('hidden')
  }

  private fill(bases: Record<string, Basis>): void {
    for (const [m, r] of this.rows) {
      const b = bases[m] ?? BASIS_DEFAULT
      r.thin.value = String(b.thin)
      r.draft.value = String(b.draft)
      r.source.value = b.source
    }
  }

  private trySave(): void {
    const out: Record<string, Basis> = {}
    const bad: string[] = []
    const rounded: string[] = []
    for (const [m, r] of this.rows) {
      const raw = { thin: Number(r.thin.value), draft: Number(r.draft.value) }
      // the folders' step: what is saved is what the check uses (and says)
      const b: Basis = { thin: toStep(raw.thin), draft: toStep(raw.draft), source: r.source.value.trim() }
      if (r.thin.value.trim() === '' || r.draft.value.trim() === '' || !validBasis(b)) {
        bad.push(m)
        continue
      }
      if (b.thin !== raw.thin) rounded.push(`${m} の肉厚 ${raw.thin} → ${b.thin}`)
      if (b.draft !== raw.draft) rounded.push(`${m} の勾配 ${raw.draft} → ${b.draft}`)
      out[m] = b
    }
    if (bad.length) {
      this.note.textContent = `保存しなかった: ${bad.join('・')} の値が範囲の外（肉厚 ${THIN_MIN}〜${THIN_MAX} mm、勾配 0〜${DRAFT_MAX_DEG}°）`
      return
    }
    this.hooks.save(out)
    this.fill(out)
    this.note.textContent = rounded.length ? `保存した（0.1 刻みに丸めた: ${rounded.join('、')}）` : '保存した'
  }
}
