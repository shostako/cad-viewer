/**
 * 確認の記録 (issue #59 P1 5): what was checked on a file, kept as a record:
 * a CSV for Excel (UTF-8 with a BOM: Excel then reads the Japanese) and a page
 * to print (A4; the browser's print saves it as a PDF).
 *
 * The record says the screen's values: the measure list's rows, the 問題の一覧's
 * rows, the 体積・重量 panel's values, each made by the function that makes it
 * on screen (the lists' own rows, PropertiesPanel.reportTables). A number is
 * kept as a number with its decimals (Num): the page groups its digits as the
 * panel does (12,345.678), the CSV does not (Excel reads it as a number).
 *
 * Each value says where it comes from (SOURCE): the B-rep's exact value, an
 * estimate on the display mesh, a value typed in, or an estimate made from it.
 * What is not on screen is not made for the record (the 問題の一覧 needs the
 * thickness, which can take a while): the record says it was not shown.
 */
import { fmtNum } from './sizes'

/** where a value comes from */
export const SOURCE = {
  brep: 'B-rep の真値',
  mesh: '表示用メッシュの近似',
  meshFile: 'メッシュの三角形から',
  drawing: '図面の値',
  input: '入力した値',
  estimate: '入力した値からの目安',
} as const

/** the page's foot: what each source means */
const SOURCE_NOTES: [string, string][] = [
  [SOURCE.brep, 'OpenCASCADE が B-rep（STEP・IGES の面と稜線）から計算した値'],
  [SOURCE.mesh, '画面に描くための三角形（表示用メッシュ）の上で計算した値。肉厚と抜き勾配はこれ'],
  [SOURCE.meshFile, 'STL などのメッシュ形式の三角形から計算した値（単位は mm とみなす）'],
  [SOURCE.drawing, 'DXF・DWG の図形の座標から計算した値'],
  [SOURCE.input, '画面で入力した条件（比重・型内圧）'],
  [SOURCE.estimate, '入力した値と近似の値から出した目安（型締力）'],
]

export type ReviewStatus = 'none' | 'ok' | 'check'
export const REVIEW_NAMES: Record<ReviewStatus, string> = { none: '未記入', ok: '確認済み', check: '要確認' }

export interface Review {
  status: ReviewStatus
  by: string
  comment: string
}

/** a number with its decimals: the page writes it grouped (fmtNum), the CSV plain */
export interface Num {
  n: number
  d: number
}
export type Cell = string | Num

export interface ReportTable {
  title: string
  /** a line under the title (the conditions of the checks) */
  note?: string
  head: string[]
  rows: Cell[][]
  /** said instead of an empty table */
  empty?: string
}

export interface Report {
  fileName: string
  /** for the CSV's name and the page's title (the PDF is named after it) */
  stem: string
  /** [item, value]: the file, its identity, when, the app, the unit */
  meta: [string, string][]
  review: Review
  tables: ReportTable[]
  /** the view as on screen (a PNG data URL); null: none */
  image: string | null
}

/** a Num as the page writes it */
const shown = (c: Cell): string => (typeof c === 'string' ? c : fmtNum(c.n, c.d))

/** a Num as the CSV writes it: plain digits, no sign on a zero */
function plain(c: Cell): string {
  if (typeof c === 'string') return c
  const t = c.n.toFixed(c.d)
  return /^-0\.?0*$/.test(t) ? t.slice(1) : t
}

/** 2026-10-10 21:05 (local time) */
export function reportTime(at: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${at.getFullYear()}-${p(at.getMonth() + 1)}-${p(at.getDate())} ${p(at.getHours())}:${p(at.getMinutes())}`
}

/** the 記録 table: the file and the review */
function recordRows(r: Report): string[][] {
  return [
    ...r.meta,
    ['判定', REVIEW_NAMES[r.review.status]],
    ['確認者', r.review.by],
    ['コメント', r.review.comment],
  ]
}

// ---------------------------------------------------------------- CSV

/**
 * A CSV field (RFC 4180): quoted when it holds a comma, a quote or a line
 * break. Text that Excel would run as a formula (=, +, -, @ first: a part's
 * name comes from the file) gets a ' first; a number stays a number.
 */
export function csvField(s: string): string {
  let v = s
  if (/^[=+\-@\t\r]/.test(v) && !/^[-+]?\d+(\.\d+)?$/.test(v)) v = `'${v}`
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
}

/**
 * The record as a CSV: one block a table (its title, its head, its rows, a
 * blank line), the record first. UTF-8 with a BOM and CRLF lines: Excel reads
 * the Japanese and the line breaks inside a comment.
 */
export function reportCsv(r: Report): string {
  const line = (cells: readonly Cell[]) => cells.map((c) => csvField(plain(c))).join(',')
  const out: string[] = ['確認の記録', line(['項目', '値']), ...recordRows(r).map(line), '']
  for (const t of r.tables) {
    out.push(t.title)
    if (t.note) out.push(line([t.note]))
    if (t.rows.length) out.push(line(t.head), ...t.rows.map(line))
    else if (t.empty) out.push(line([t.empty]))
    out.push('')
  }
  return '\ufeff' + out.join('\r\n')
}

// ---------------------------------------------------------------- the page

const esc = (s: string): string =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)

/** a number (a Num, or a string of digits): right-aligned on the page */
const isNumber = (c: Cell | undefined): boolean => c !== undefined && (typeof c !== 'string' || /^[-+]?[\d,]+(\.\d+)?$/.test(c))

function tableHtml(t: ReportTable): string {
  const note = t.note ? `<p class="note">${esc(t.note)}</p>` : ''
  if (!t.rows.length) {
    return `<section><h2>${esc(t.title)}</h2>${note}<p class="empty">${esc(t.empty ?? 'なし')}</p></section>`
  }
  // a head over numbers mostly goes right with them (判定できない puts a text in 値)
  const headNum = t.head.map((_, i) => {
    const cells = t.rows.map((row) => row[i]).filter((c) => c !== undefined && c !== '')
    return cells.length > 0 && cells.filter(isNumber).length * 2 > cells.length
  })
  const cls = (on: boolean) => (on ? ' class="num"' : '')
  const head = t.head.map((h, i) => `<th${cls(headNum[i])}>${esc(h)}</th>`).join('')
  const rows = t.rows.map((row) => `<tr>${row.map((c) => `<td${cls(isNumber(c))}>${esc(shown(c))}</td>`).join('')}</tr>`).join('')
  return `<section><h2>${esc(t.title)}</h2>${note}<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></section>`
}

/**
 * The page to print: A4 portrait. The head (the file, the review) and the
 * image keep together; a table may run onto the next page, never splitting a
 * row, its head line again at the top. On screen the sheet sits on a grey
 * desk with a button to print.
 */
export function reportHtml(r: Report): string {
  const meta = r.meta.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')
  const status = r.review.status
  const by = r.review.by ? esc(r.review.by) : '<span class="blank">（未記入）</span>'
  const comment = r.review.comment ? esc(r.review.comment) : '<span class="blank">（なし）</span>'
  const image = r.image
    ? `<figure><img src="${r.image}" alt="画面"><figcaption>記録を作ったときの画面</figcaption></figure>`
    : ''
  const sources = SOURCE_NOTES.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')
  return `<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(r.stem)}</title>
<style>
@page { size: A4 portrait; margin: 14mm 12mm; }
:root { color-scheme: light; --ink: #1d2126; --ink-2: #4a5360; --ink-3: #7a8494; --rule: #c9cfd8; --band: #f1f3f6; --ok: #1f7a4d; --check: #b3261e; }
* { box-sizing: border-box; }
html { background: #e6e8ec; }
body { margin: 0; color: var(--ink); font: 9.5pt/1.5 "Noto Sans JP", "Yu Gothic UI", "Yu Gothic", Meiryo, system-ui, sans-serif; }
.sheet { width: 210mm; min-height: 297mm; margin: 24px auto; padding: 14mm 12mm; background: #fff; box-shadow: 0 2px 12px rgb(0 0 0 / 18%); }
.bar { width: 210mm; margin: 16px auto -8px; display: flex; justify-content: flex-end; gap: 8px; }
.bar button { font: inherit; font-size: 10pt; padding: 6px 14px; border: 1px solid #2f6fd6; border-radius: 6px; background: #2f6fd6; color: #fff; cursor: pointer; }
header { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; border-bottom: 2px solid var(--ink); padding-bottom: 4px; margin-bottom: 8px; }
h1 { font-size: 15pt; margin: 0; }
header .file { font-size: 10.5pt; font-weight: 600; overflow-wrap: anywhere; text-align: right; }
.head { display: grid; grid-template-columns: 1fr 62mm; gap: 6mm; break-inside: avoid; }
.meta { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
.meta th { width: 38mm; text-align: left; font-weight: 500; color: var(--ink-2); padding: 1px 6px 1px 0; vertical-align: top; }
.meta td { padding: 1px 0; overflow-wrap: anywhere; }
.review { border: 1px solid var(--rule); border-radius: 4px; padding: 6px 8px; font-size: 8.5pt; }
.review .status { font-size: 12pt; font-weight: 700; margin-bottom: 2px; }
.review .status.ok { color: var(--ok); }
.review .status.check { color: var(--check); }
.review .by { color: var(--ink-2); }
.review .comment { margin-top: 4px; white-space: pre-wrap; overflow-wrap: anywhere; }
.blank { color: var(--ink-3); }
figure { margin: 8px 0 0; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 105mm; border: 1px solid var(--rule); }
figcaption { font-size: 7.5pt; color: var(--ink-3); }
section { margin-top: 10px; }
h2 { font-size: 10.5pt; margin: 0 0 2px; padding-left: 6px; border-left: 3px solid var(--ink); break-after: avoid; }
.note { margin: 0 0 3px; font-size: 8pt; color: var(--ink-2); break-after: avoid; }
.empty { margin: 0; font-size: 8.5pt; color: var(--ink-3); }
table { width: 100%; border-collapse: collapse; font-size: 8pt; }
thead { display: table-header-group; }
th, td { border-bottom: 1px solid var(--rule); padding: 2px 4px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
thead th { background: var(--band); font-weight: 600; border-bottom: 1px solid var(--ink-3); white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr { break-inside: avoid; }
footer { margin-top: 12px; padding-top: 4px; border-top: 1px solid var(--rule); font-size: 7.5pt; color: var(--ink-2); break-inside: avoid; }
footer dl { display: grid; grid-template-columns: max-content 1fr; gap: 0 8px; margin: 2px 0 0; }
footer dt { font-weight: 600; }
footer dd { margin: 0; }
@media print {
  html { background: none; }
  .bar { display: none; }
  .sheet { width: auto; min-height: 0; margin: 0; padding: 0; box-shadow: none; }
}
@media screen and (max-width: 840px) {
  .sheet, .bar { width: auto; margin-left: 16px; margin-right: 16px; }
  .head { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="bar"><button type="button" onclick="window.print()">印刷（PDF に保存）</button></div>
<main class="sheet">
<header><h1>確認の記録</h1><div class="file">${esc(r.fileName)}</div></header>
<div class="head">
<table class="meta"><tbody>${meta}</tbody></table>
<div class="review"><div class="status ${status}">${esc(REVIEW_NAMES[status])}</div><div class="by">確認者: ${by}</div><div class="comment">${comment}</div></div>
</div>
${image}
${r.tables.map(tableHtml).join('\n')}
<footer>値の出どころ<dl>${sources}</dl></footer>
</main>
</body>
</html>
`
}

// ---------------------------------------------------------------- the card

export interface ReportPopHooks {
  /** what the record will hold, one line (「計測 3 件・問題の一覧 14 行・…」) */
  summary: () => string
  csv: () => void
  page: () => void
  /** the review was changed (typed, chosen) */
  change: (r: Review) => void
}

/**
 * The card of 確認の記録 (操作パネル): the review (判定・確認者・コメント), what
 * the record will hold, and the two ways to keep it. The review is the
 * caller's (a new model starts blank; the name stays, main.ts).
 */
export class ReportPop {
  readonly el: HTMLElement
  private readonly hooks: ReportPopHooks
  private readonly status: HTMLSelectElement
  private readonly by: HTMLInputElement
  private readonly comment: HTMLTextAreaElement
  private readonly what: HTMLElement

  constructor(el: HTMLElement, hooks: ReportPopHooks) {
    this.el = el
    this.hooks = hooks
    el.setAttribute('role', 'dialog')
    el.setAttribute('aria-labelledby', 'report-title')
    const title = document.createElement('div')
    title.id = 'report-title'
    title.textContent = '確認の記録'
    this.status = document.createElement('select')
    this.status.id = 'report-status'
    for (const [v, name] of Object.entries(REVIEW_NAMES)) this.status.add(new Option(name, v))
    this.by = document.createElement('input')
    this.by.id = 'report-by'
    this.by.type = 'text'
    this.by.autocomplete = 'name'
    this.by.placeholder = '名前（次も使う）'
    this.comment = document.createElement('textarea')
    this.comment.id = 'report-comment'
    this.comment.rows = 3
    this.comment.placeholder = '気づいたこと（任意）'
    const field = (label: string, input: HTMLElement): HTMLLabelElement => {
      const l = document.createElement('label')
      l.className = 'report-field'
      const s = document.createElement('span')
      s.textContent = label
      l.append(s, input)
      return l
    }
    this.what = document.createElement('div')
    this.what.id = 'report-what'
    const buttons = document.createElement('div')
    buttons.className = 'report-buttons'
    const csv = document.createElement('button')
    csv.type = 'button'
    csv.id = 'report-csv'
    csv.textContent = 'CSV を保存'
    csv.title = 'Excel で開ける CSV（UTF-8・BOM 付き）を保存する'
    csv.addEventListener('click', () => this.hooks.csv())
    const page = document.createElement('button')
    page.type = 'button'
    page.id = 'report-page'
    page.textContent = '印刷用のページ'
    page.title = 'A4 の印刷用のページを新しいタブに開く（印刷で PDF に保存できる）'
    page.addEventListener('click', () => this.hooks.page())
    buttons.append(csv, page)
    el.replaceChildren(title, field('判定', this.status), field('確認者', this.by), field('コメント', this.comment), this.what, buttons)
    const changed = () => this.hooks.change(this.review)
    this.status.addEventListener('change', changed)
    this.by.addEventListener('input', changed)
    this.comment.addEventListener('input', changed)
    // Esc closes it, also from inside a field (the app's keys skip the fields)
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

  get review(): Review {
    return { status: this.status.value as ReviewStatus, by: this.by.value.trim(), comment: this.comment.value.trim() }
  }

  /** open with this review; the line of what goes in is made now */
  show(review: Review): void {
    this.status.value = review.status
    this.by.value = review.by
    this.comment.value = review.comment
    this.refresh()
    this.el.classList.remove('hidden')
  }

  /** say again what the record will hold (the lists changed) */
  refresh(): void {
    this.what.textContent = `載せるもの: ${this.hooks.summary()}`
  }

  hide(): void {
    this.el.classList.add('hidden')
  }
}
