/**
 * The card of 材料の基準 (基準を編集…): a row a material of the 用途 in use,
 * its specific gravity, its least wall, its draft (a resin's) and where they
 * come from. A row edited away from the general standard is marked, and its
 * ↺ puts the standard back; 既定に戻す puts back every row. 書き出す writes
 * every material's values to a file, 読み込む takes a file's into the rows.
 * Nothing is kept until 保存; values out of range are not saved (the card says
 * which), values finer than the folders' steps are saved at the step.
 */
import { DRAFT_MAX_DEG } from './draft'
import {
  BASIS_UNSET,
  DENSITY_MAX,
  DENSITY_MIN,
  SOURCE_MAX,
  THICK_MAX,
  THICK_MIN,
  THIN_MAX,
  THIN_MIN,
  builtin,
  kindOf,
  readMaterialsFile,
  sameValues,
  stepped,
  validValues,
  type MaterialValues,
} from './materials'
import { downloadBlob } from './snapshot'

export interface MaterialPopHooks {
  /** every material's values as edited (the card's rows, and the others as they were): saved. Returns the file of them (書き出す) */
  save: (values: Record<string, MaterialValues>) => string
}

interface RowInputs {
  tr: HTMLTableRowElement
  density: HTMLInputElement
  thin: HTMLInputElement
  draft: HTMLInputElement | null
  thick: HTMLInputElement | null
  source: HTMLInputElement
  reset: HTMLButtonElement
}

export const MATERIALS_FILE_NAME = 'cad-viewer-材料の基準.json'

export class MaterialPop {
  readonly el: HTMLElement
  private readonly hooks: MaterialPopHooks
  private readonly tbody = document.createElement('tbody')
  private readonly note: HTMLElement
  private readonly lead: HTMLElement
  private readonly fileInput = document.createElement('input')
  private rows = new Map<string, RowInputs>()
  /** every material's values the card holds (the rows shown are written back into it) */
  private working: Record<string, MaterialValues> = {}

  constructor(el: HTMLElement, hooks: MaterialPopHooks) {
    this.el = el
    this.hooks = hooks
    el.setAttribute('role', 'dialog')
    el.setAttribute('aria-labelledby', 'basis-title')
    const title = document.createElement('div')
    title.id = 'basis-title'
    title.textContent = '材料の基準'
    this.lead = document.createElement('div')
    this.lead.className = 'basis-lead'
    const table = document.createElement('table')
    table.className = 'basis-table'
    const head = document.createElement('tr')
    for (const h of ['材料', '比重', '肉厚 mm', '勾配 °', '厚肉 倍', '根拠', '']) {
      const th = document.createElement('th')
      th.textContent = h
      head.appendChild(th)
    }
    const thead = document.createElement('thead')
    thead.appendChild(head)
    table.append(thead, this.tbody)
    this.note = document.createElement('div')
    this.note.id = 'basis-note'
    this.note.setAttribute('aria-live', 'polite')
    const button = (id: string, text: string, title: string, run: () => void) => {
      const b = document.createElement('button')
      b.type = 'button'
      b.id = id
      b.textContent = text
      b.title = title
      b.addEventListener('click', run)
      return b
    }
    this.fileInput.type = 'file'
    this.fileInput.accept = '.json,application/json'
    this.fileInput.hidden = true
    this.fileInput.id = 'basis-file'
    this.fileInput.addEventListener('change', () => void this.readFile())
    const files = document.createElement('div')
    files.className = 'report-buttons basis-files'
    files.append(
      button('basis-export', '書き出す', 'どの材料の値もファイルに書き出す（いま保存してある値）', () => this.writeFile()),
      button('basis-import', '読み込む…', '書き出したファイルの値を表に入れる（保存で決まる）', () => this.fileInput.click()),
      this.fileInput,
    )
    const buttons = document.createElement('div')
    buttons.className = 'report-buttons'
    buttons.append(
      button('basis-defaults', '既定に戻す', 'どの材料も一般的な基準の値に戻す（保存で決まる）', () => {
        for (const name of this.rows.keys()) this.fillRow(name, builtin(name))
        this.note.textContent = ''
      }),
      button('basis-save', '保存', '表の値を保存して、使っている材料の値を判定に入れ直す', () => this.trySave()),
    )
    el.replaceChildren(title, this.lead, table, this.note, files, buttons)
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

  /**
   * Show the rows of these materials (the 用途's) at the values given (every
   * material's: the file and 保存 carry the others along unchanged). `saved`:
   * the file of the values kept (materials.ts materialsFile), what 書き出す writes.
   */
  show(names: readonly string[], values: Record<string, MaterialValues>, saved: string): void {
    this.working = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, { ...v }]))
    this.savedFile = saved
    this.lead.textContent =
      '材料ごとの比重、肉厚の下限、必要な勾配と厚肉の倍率（樹脂）と根拠。初めは一般的な基準（出典は根拠に）。社内の基準などで直せる。直した行には印が付き、↺ でその行を既定に戻せる'
    this.tbody.replaceChildren()
    this.rows.clear()
    // 金属 and 樹脂 under a heading each, when both are there (一般)
    const kinds = new Set(names.map((n) => kindOf(n)))
    let last: string | null = null
    for (const name of names) {
      const kind = kindOf(name)
      if (kinds.size > 1 && kind !== last) {
        const tr = document.createElement('tr')
        tr.className = 'basis-group'
        const th = document.createElement('th')
        th.colSpan = 7
        th.textContent = kind === 'metal' ? '金属' : '樹脂'
        tr.appendChild(th)
        this.tbody.appendChild(tr)
        last = kind
      }
      this.addRow(name)
    }
    for (const name of names) this.fillRow(name, this.working[name] ?? builtin(name))
    this.note.textContent = ''
    this.el.classList.remove('hidden')
  }

  hide(): void {
    this.el.classList.add('hidden')
  }

  /** the file as saved (書き出す writes the values kept, not the card's unsaved ones) */
  private savedFile = ''

  private addRow(name: string): void {
    const kind = kindOf(name)
    const tr = document.createElement('tr')
    tr.dataset.material = name
    tr.dataset.kind = kind ?? ''
    const cell = (child: Node | string) => {
      const td = document.createElement('td')
      td.append(child)
      tr.appendChild(td)
      return td
    }
    const num = (min: number, max: number, step: string, cls: string) => {
      const i = document.createElement('input')
      i.type = 'number'
      i.min = String(min)
      i.max = String(max)
      i.step = step
      i.className = cls
      const what: Record<string, string> = { 'basis-density': '比重', 'basis-thin': '肉厚の下限', 'basis-draft': '勾配', 'basis-thick': '厚肉の倍率' }
      i.setAttribute('aria-label', `${name} ${what[cls]}`)
      return i
    }
    cell(name)
    const density = num(DENSITY_MIN, DENSITY_MAX, '0.01', 'basis-density')
    const thin = num(THIN_MIN, THIN_MAX, '0.01', 'basis-thin')
    const draft = kind === 'resin' ? num(0, DRAFT_MAX_DEG, '0.1', 'basis-draft') : null
    const thick = kind === 'resin' ? num(THICK_MIN, THICK_MAX, '0.05', 'basis-thick') : null
    const source = document.createElement('input')
    source.type = 'text'
    source.className = 'basis-source'
    source.maxLength = SOURCE_MAX
    source.placeholder = BASIS_UNSET
    source.setAttribute('aria-label', `${name} 根拠`)
    const reset = document.createElement('button')
    reset.type = 'button'
    reset.className = 'basis-reset'
    reset.textContent = '↺'
    reset.title = `${name} を一般的な基準の値に戻す（保存で決まる）`
    reset.setAttribute('aria-label', reset.title)
    reset.addEventListener('click', () => this.fillRow(name, builtin(name)))
    cell(density)
    cell(thin)
    for (const [input, why] of [
      [draft, '金属は成形しないので勾配を見ない'],
      [thick, '金属は成形しないので厚肉（ヒケ・ボイド）を見ない'],
    ] as const) {
      if (input) cell(input)
      else {
        const td = cell('—')
        td.className = 'basis-none'
        td.title = why
      }
    }
    cell(source)
    cell(reset)
    const row: RowInputs = { tr, density, thin, draft, thick, source, reset }
    for (const i of [density, thin, draft, thick, source]) i?.addEventListener('input', () => this.mark(name))
    this.rows.set(name, row)
    this.tbody.appendChild(tr)
  }

  private fillRow(name: string, v: MaterialValues): void {
    const r = this.rows.get(name)
    if (!r) return
    r.density.value = String(v.density)
    r.thin.value = String(v.thin)
    if (r.draft) r.draft.value = String(v.draft ?? '')
    if (r.thick) r.thick.value = String(v.thick ?? '')
    r.source.value = v.source
    r.source.title = v.source // the whole of it (the field shows its start)
    this.mark(name)
  }

  /** the row's values as typed (null: one is empty or not a number) */
  private read(name: string): MaterialValues | null {
    const r = this.rows.get(name)!
    const n = (i: HTMLInputElement) => (i.value.trim() === '' ? NaN : Number(i.value))
    const v: MaterialValues = {
      density: n(r.density),
      thin: n(r.thin),
      draft: r.draft ? n(r.draft) : null,
      thick: r.thick ? n(r.thick) : null,
      source: r.source.value,
    }
    return validValues(name, v) ? v : null
  }

  /** the row's mark: edited away from the general standard (↺ puts it back) */
  private mark(name: string): void {
    const r = this.rows.get(name)!
    const v = this.read(name)
    const edited = !v || !sameValues(stepped(v), builtin(name))
    r.tr.classList.toggle('edited', edited)
    r.reset.disabled = !edited
  }

  private trySave(): void {
    const out: Record<string, MaterialValues> = { ...this.working }
    const bad: string[] = []
    const rounded: string[] = []
    for (const name of this.rows.keys()) {
      const raw = this.read(name)
      if (!raw) {
        bad.push(name)
        continue
      }
      const v = stepped(raw)
      if (v.density !== raw.density) rounded.push(`${name} の比重 ${raw.density} → ${v.density}`)
      if (v.thin !== raw.thin) rounded.push(`${name} の肉厚 ${raw.thin} → ${v.thin}`)
      if (v.draft !== raw.draft) rounded.push(`${name} の勾配 ${raw.draft} → ${v.draft}`)
      if (v.thick !== raw.thick) rounded.push(`${name} の厚肉 ${raw.thick} → ${v.thick}`)
      out[name] = v
    }
    if (bad.length) {
      this.note.textContent = `保存しなかった: ${bad.join('・')} の値が範囲の外（比重 ${DENSITY_MIN}〜${DENSITY_MAX}、肉厚 ${THIN_MIN}〜${THIN_MAX} mm、勾配 0〜${DRAFT_MAX_DEG}°、厚肉 ${THICK_MIN}〜${THICK_MAX} 倍）`
      return
    }
    this.working = out
    this.savedFile = this.hooks.save(out)
    for (const name of this.rows.keys()) this.fillRow(name, out[name])
    this.note.textContent = rounded.length ? `保存した（刻みに丸めた: ${rounded.join('、')}）` : '保存した'
  }

  private writeFile(): void {
    downloadBlob(new Blob([this.savedFile], { type: 'application/json' }), MATERIALS_FILE_NAME)
    this.note.textContent = `書き出した: ${MATERIALS_FILE_NAME}（保存してある値）`
  }

  private async readFile(): Promise<void> {
    const f = this.fileInput.files?.[0]
    this.fileInput.value = '' // the same file again is a change too
    if (!f) return
    try {
      const { values, skipped } = readMaterialsFile(await f.text())
      Object.assign(this.working, values)
      const shown = Object.keys(values).filter((name) => this.rows.has(name))
      for (const name of shown) this.fillRow(name, values[name])
      const n = Object.keys(values).length
      this.note.textContent =
        `読み込んだ: ${n} 材料（表にあるのは ${shown.length}。保存で決まる）` + (skipped.length ? `。読めなかった: ${skipped.join('・')}` : '')
    } catch (e) {
      this.note.textContent = `読み込めなかった: ${e instanceof Error ? e.message : String(e)}`
    }
  }
}
