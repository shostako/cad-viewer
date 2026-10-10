/**
 * The 計測 list as a record to copy into a report or Excel (issue #23 item 8).
 *
 * A row shows its value first, with its unit ("20.000 mm"), a mark of its
 * kind (distance, ⌀, R, angle, draft, area, perimeter, length, note), and what was measured on a
 * second, smaller line ("cavity_block 面#6 ↔ plate 面#6"). A third line says
 * where: a slanted distance's ΔX, ΔY and ΔZ, a whole circle's centre. Each row
 * copies its own line, the list's head copies all of them: tab separated
 * (種類, 値, 単位, 対象 A, 対象 B, ΔX, ΔY, ΔZ), which Excel pastes into cells.
 *
 * The saved entries (sidecars) keep their form: a row is read out of an
 * entry's text and label as the measure tool writes them, so entries saved
 * before this change show the same way.
 */
import type { IconNode } from 'lucide'
import type { Measurement2D } from './drawing2d'
import { ICON, icon } from './icons'
import { DISTANCE_MODE_NAMES, type EntryData } from './measure'
import { areaUnit, fmt, inFrameDir, lenUnit, showArea, showDegNum, showLen, showPoint, unitTag } from './sizes'

export type RowKind =
  | 'distance'
  | 'centre'
  | 'max'
  | 'diameter'
  | 'radius'
  | 'angle'
  | 'draft'
  | 'area'
  | 'perimeter'
  | 'length'
  | 'note'
  | 'other'

export interface RowView {
  kind: RowKind
  /** the number (or a note's text); '' when there is none */
  value: string
  unit: string
  /** shown before the number (⌀, R, SR, 勾配); the copy keeps the bare number, for Excel */
  mark?: string
  /** the second line: what was measured */
  what: string
  /** for the copy: the two things measured (a diameter or a note has one) */
  a: string
  b: string
  /** for the copy: a distance's ΔX, ΔY, ΔZ (sizes, no sign; a drawing has no ΔZ) */
  axes?: [string, string, string]
  /** the third line: where (a slanted distance's ΔX ΔY ΔZ, a whole circle's centre) */
  where?: string
  /**
   * The number itself, in mm, mm² or degrees (q): the one saved with the entry,
   * or read out of its saved text (3 decimals) for an entry saved before the
   * numbers were. value is it as shown (the display's unit and decimals); the
   * 記録 writes it as it is (recordCells).
   */
  num?: number
  q?: Quantity
  /** a distance's ΔX, ΔY, ΔZ in mm (signed, as saved) */
  delta?: [number, number, number]
  /** what was measured as saved (its numbers in mm: an edge's L): the 記録's 対象 A */
  aRecord?: string
}

/** what a number measures: a length (mm), an area (mm²), an angle (°) */
export type Quantity = 'len' | 'area' | 'deg'

/** a number as shown, with its unit */
function shownNum(q: Quantity, n: number): { value: string; unit: string } {
  if (q === 'area') return { value: showArea(n), unit: areaUnit() }
  if (q === 'deg') return { value: showDegNum(n), unit: '°' }
  return { value: showLen(n), unit: lenUnit() }
}

/** the unit a number is saved and recorded in */
const RECORD_UNIT: Record<Quantity, string> = { len: 'mm', area: 'mm²', deg: '°' }

/** a saved point (a sidecar anyone can edit: anything else reads as none) */
function xyzOf(v: unknown): [number, number, number] | null {
  return Array.isArray(v) && v.length === 3 && v.every((c) => typeof c === 'number' && Number.isFinite(c))
    ? (v as [number, number, number])
    : null
}

/**
 * ΔX ΔY ΔZ as the copy has them, and the third line when the distance is
 * slanted (along two axes or more). A no-break space ties each Δ to its
 * number: a narrow list wraps the line between them, never inside one.
 */
function axesOf(delta: [number, number, number]): { axes: [string, string, string]; where?: string; delta: [number, number, number] } {
  // along the axes of the frame shown (the model's own, or one chosen: 座標系)
  const along3 = inFrameDir(delta)
  const axes = along3.map((c) => showLen(Math.abs(c))) as [string, string, string]
  // slanted or not by the numbers themselves, not as shown: coarse decimals
  // (inches, 0 decimals) write small sides as 0 and would hide them
  const along = along3.filter((c) => Math.abs(c) >= SLANT_MM).length
  return along >= 2 ? { axes, where: `ΔX\u00a0${axes[0]}　ΔY\u00a0${axes[1]}　ΔZ\u00a0${axes[2]}`, delta } : { axes, delta }
}

/**
 * An edge's length in a size's text (「円エッジ (L=25.133)」) as shown: the
 * number saved with the entry (edgeLength), else the text's, in the display's
 * unit and decimals (「(L=0.9895 in)」). With mm and 3 decimals: the saved text.
 */
function edgeLengthShown(what: string, raw: EntryData): string {
  // at the end: the text ends with it (a part's name before could hold the same letters)
  const m = / \(L=([\d.]+)\)$/.exec(what)
  if (!m) return what
  const v = (raw as { edgeLength?: unknown }).edgeLength
  const n = typeof v === 'number' && Number.isFinite(v) ? v : Number(m[1])
  return `${what.slice(0, m.index)} (L=${showLen(n)}${unitTag()})`
}

/** a side of a distance at least this long (mm) makes it slanted: half the list's first 3 decimals */
const SLANT_MM = 5e-4

/** the number saved with the entry (value), else the one in its text */
function savedNum(raw: EntryData, inText: string): number {
  const v = (raw as { value?: unknown }).value
  return typeof v === 'number' && Number.isFinite(v) ? v : Number(inText)
}

const KIND_NAME: Record<RowKind, string> = {
  distance: '距離',
  centre: '中心間',
  max: '最大',
  diameter: '直径',
  radius: '半径',
  angle: '角度',
  draft: '勾配',
  area: '面積',
  perimeter: '周長',
  length: '長さ',
  note: '注記',
  other: '',
}

/** a 3D entry (as saved) as a row */
export function entryRow(raw: EntryData): RowView {
  // a sidecar is plain JSON anyone can edit: a missing or broken text reads as
  // empty (a row that throws here would stop the whole list being drawn)
  const d = {
    ...raw,
    text: typeof raw.text === 'string' ? raw.text : '',
    labelText: typeof raw.labelText === 'string' ? raw.labelText : '',
  }
  if (d.annotation) return { kind: 'note', value: d.labelText, unit: '', what: '', a: '', b: '' }
  // a face's area and outer loop, an edge's length (Enter on a first point):
  // the numbers are kept as they are; what was measured is the text before the
  // last 「 面積 」 (a part's name may have the word in it too)
  const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v)
  const before = (word: string) => {
    const k = d.text.lastIndexOf(` ${word} `)
    return k < 0 ? d.text : d.text.slice(0, k)
  }
  if (num(raw.area)) {
    const what = before('面積')
    return { kind: 'area', ...shownNum('area', raw.area!), num: raw.area!, q: 'area', what, a: what, b: '' }
  }
  if (num(raw.perimeter)) {
    const what = before('周長')
    const holes = Array.isArray(raw.holes) ? raw.holes.filter(num) : []
    return {
      kind: 'perimeter',
      ...shownNum('len', raw.perimeter!),
      num: raw.perimeter!,
      q: 'len',
      what,
      a: what,
      b: '',
      ...(holes.length ? { where: `内側の輪郭 ${holes.length} 個:\u00a0${holes.map((h) => showLen(h as number)).join('・')}` } : {}),
    }
  }
  if (num(raw.length)) {
    const what = before('長さ')
    return { kind: 'length', ...shownNum('len', raw.length!), num: raw.length!, q: 'len', what, a: what, b: '' }
  }
  // "core_pin 円エッジ ⌀8.000 (L=25.133)", "円筒面 ⌀8.000"
  const dia = /^(.*?)\s*⌀([-\d.]+)(.*)$/.exec(d.text)
  if (d.labelText.startsWith('⌀') && dia) {
    const saved = `${dia[1]}${dia[3]}`.trim()
    const what = edgeLengthShown(saved, raw)
    const centre = xyzOf(raw.centre)
    const n = savedNum(raw, dia[2])
    return {
      kind: 'diameter',
      ...shownNum('len', n),
      num: n,
      q: 'len',
      mark: '⌀',
      what,
      a: what,
      aRecord: saved,
      b: '',
      ...(centre ? { where: `中心\u00a0${showPoint(centre)}` } : {}),
    }
  }
  // "body 円筒面 R5.000", "body 円弧 R5.000 (L=7.854)", "body 球面 SR4.000",
  // "pin 曲面 R1.000（クリックした点）": the last R of the text (a part's name may have one)
  const rad = /^(.*) (S?R)([\d.]+)((?:（[^）]*）)?(?: \(L=[\d.]+\))?)$/.exec(d.text)
  if (/^S?R[\d.]+$/.test(d.labelText) && rad) {
    const saved = `${rad[1]}${rad[4]}`
    const what = edgeLengthShown(saved, raw)
    const n = savedNum(raw, rad[3])
    return { kind: 'radius', ...shownNum('len', n), num: n, q: 'len', mark: rad[2], what, a: what, aRecord: saved, b: '' }
  }
  // "body 円錐面 勾配 2.000°": a cone's half angle
  const draft = /^(.*) 勾配 ([\d.]+)°$/.exec(d.text)
  if (d.labelText.startsWith('勾配') && draft) {
    const n = savedNum(raw, draft[2])
    return { kind: 'draft', ...shownNum('deg', n), num: n, q: 'deg', mark: '勾配 ', what: draft[1], a: draft[1], b: '' }
  }
  // "cavity_block 面#6 ∠ cavity_block 面#3 : 90.000°"
  const ang = /^(.*) ∠ (.*) : ([-\d.]+)°$/.exec(d.text)
  if (ang) {
    const n = savedNum(raw, ang[3])
    return { kind: 'angle', ...shownNum('deg', n), num: n, q: 'deg', what: `${ang[1]} ∠ ${ang[2]}`, a: ang[1], b: ang[2] }
  }
  // "cavity_block 面#6 ↔ plate 面#6 : 20.000", "core_pin 面#1 ↔ core_pin 面#1 : 中心間 50.000"
  const dist = /^(.*) ↔ (.*) : (?:中心間 |最大 )?([-\d.]+)$/.exec(d.text)
  if (dist) {
    const delta = xyzOf(raw.delta)
    const mode = raw.mode === 'centre' || raw.mode === 'max' ? raw.mode : null
    const n = savedNum(raw, dist[3])
    return {
      kind: mode ?? 'distance',
      ...shownNum('len', n),
      num: n,
      q: 'len',
      // which distance, before the value (the copy has it in 種類): 「中心間 50.000」
      ...(mode ? { mark: `${DISTANCE_MODE_NAMES[mode]} ` } : {}),
      what: `${dist[1]} ↔ ${dist[2]}`,
      a: dist[1],
      b: dist[2],
      ...(delta ? axesOf(delta) : {}),
    }
  }
  return { kind: 'other', value: '', unit: '', what: d.text, a: d.text, b: '' }
}

/**
 * A drawing's measurement as a row: the distance, and its ΔX and ΔY on the
 * second line (and in the copy's ΔX, ΔY). No unit: a drawing's numbers are in
 * its own unit (the DXF does not always say which).
 */
export function drawingRow(m: Measurement2D): RowView {
  const dx = fmt(Math.abs(m.b.dxf[0] - m.a.dxf[0]))
  const dy = fmt(Math.abs(m.b.dxf[1] - m.a.dxf[1]))
  const value = Math.hypot(m.b.dxf[0] - m.a.dxf[0], m.b.dxf[1] - m.a.dxf[1]).toFixed(3)
  return { kind: 'distance', value, unit: '', what: `ΔX ${dx}　ΔY ${dy}`, a: '', b: '', axes: [dx, dy, ''] }
}

/** a cell of the copied text: a tab or a line break inside it would split the cells */
export function cell(s: string): string {
  return s.replace(/[\t\r\n]+/g, ' ')
}

/** the copy's columns (and the 記録's, report.ts) */
export const LIST_HEAD = ['種類', '値', '単位', '対象 A', '対象 B', 'ΔX', 'ΔY', 'ΔZ']

/** one row's cells, in LIST_HEAD's order, as shown (the copy) */
export function rowCells(r: RowView): string[] {
  return [KIND_NAME[r.kind], r.value, r.unit, r.a, r.b, ...(r.axes ?? ['', '', ''])]
}

/**
 * One row's cells for the 記録 (report.ts), in LIST_HEAD's order: the numbers
 * as they are (mm, mm², °), whatever the display's unit and decimals. A row
 * without a number (a note, a drawing's: its own unit) as shown.
 */
export function recordCells(r: RowView): (string | number)[] {
  if (r.num === undefined || !r.q) return rowCells(r)
  const d = r.delta ? r.delta.map((c) => Math.abs(c)) : ['', '', '']
  return [KIND_NAME[r.kind], r.num, RECORD_UNIT[r.q], r.aRecord ?? r.a, r.b, ...d]
}

/** words before a label's number that the list's mark leaves out */
const LABEL_WORD: Partial<Record<RowKind, string>> = { perimeter: '周長 ', length: '長さ ' }

/**
 * The 3D label of an entry as shown: its number in the display's unit and
 * decimals (「25.000 mm」「⌀0.3150 in」「中心間 26.000 mm」「90.000°」). With mm
 * and 3 decimals it reads as the saved label with its unit. A note is its own
 * text; an entry the list cannot read keeps its saved label.
 */
export function labelText(raw: EntryData): string {
  const saved = typeof raw.labelText === 'string' ? raw.labelText : ''
  if (raw.annotation) return saved
  const r = entryRow(raw)
  if (r.num === undefined || !r.q || !Number.isFinite(r.num)) {
    // a length says its unit (an angle has its °, an area its mm²)
    return /[°²]$/.test(saved) ? saved : `${saved} mm`
  }
  const word = LABEL_WORD[r.kind] ?? r.mark ?? ''
  return r.q === 'deg' ? `${word}${r.value}°` : `${word}${r.value} ${r.unit}`
}

/** one row as a line of tab-separated cells */
export function rowLine(r: RowView): string {
  return rowCells(r).map(cell).join('\t')
}

/** the whole list: a head line, then a line per row (Excel pastes it into cells) */
export function listText(rows: readonly RowView[]): string {
  return [LIST_HEAD.join('\t'), ...rows.map(rowLine)].join('\n')
}

/** the mark of a row's kind (Lucide) */
const KIND_ICON: Record<RowKind, IconNode | null> = {
  distance: ICON.distance,
  centre: ICON.centre,
  max: ICON.max,
  diameter: ICON.diameter,
  radius: ICON.radius,
  angle: ICON.angle,
  draft: ICON.draft,
  area: ICON.area,
  perimeter: ICON.perimeter,
  length: ICON.length,
  note: ICON.note,
  other: null,
}

/**
 * Put text on the clipboard. The async API needs a secure page (localhost
 * is one) and the page's focus; a hidden text area and execCommand stand in
 * when it is refused.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    ta.remove()
    return ok
  }
}

/** how long a copy button shows its tick */
const DONE_MS = 1500

/** show the tick on a copy control for a moment (it went to the clipboard) */
export function flashDone(el: HTMLElement, label: string): void {
  el.replaceChildren(icon(ICON.done, 14))
  el.classList.add('done')
  el.title = 'コピーした'
  clearTimeout(Number(el.dataset.doneTimer))
  el.dataset.doneTimer = String(
    setTimeout(() => {
      el.replaceChildren(icon(ICON.copy, 14))
      el.classList.remove('done')
      el.title = label
    }, DONE_MS),
  )
}

/**
 * A row of the list. The × is the row's only <button> (and its first): the
 * copy control is a span with the role of a button, so that "the row's
 * button" stays the ×.
 */
export function rowElement(
  r: RowView,
  remove: () => void,
  pressOnce: (b: HTMLButtonElement, fn: () => void) => void,
): HTMLLIElement {
  const li = document.createElement('li')
  li.className = 'm-row'
  li.dataset.kind = r.kind
  const mark = document.createElement('span')
  mark.className = 'm-icon'
  const kindIcon = KIND_ICON[r.kind]
  if (kindIcon) mark.appendChild(icon(kindIcon, 14))
  const main = document.createElement('span')
  main.className = 'm-main'
  const value = document.createElement('span')
  value.className = 'm-value'
  // file-supplied text (a note): textContent only. A diameter shows its ⌀, a
  // radius its R or SR (the copy keeps the bare number, for Excel)
  value.textContent = r.value ? `${r.mark ?? ''}${r.value}` : r.what
  if (r.unit) {
    const u = document.createElement('span')
    u.className = 'm-unit'
    u.textContent = r.unit === '°' ? '°' : ` ${r.unit}` // 90.000° (no space), 20.000 mm
    value.appendChild(u)
  }
  main.appendChild(value)
  if (r.value && r.what) {
    const what = document.createElement('span')
    what.className = 'm-what'
    what.textContent = r.what
    what.title = r.what
    main.appendChild(what)
  }
  if (r.value && r.where) {
    const where = document.createElement('span')
    where.className = 'm-where'
    where.textContent = r.where
    where.title = r.where
    main.appendChild(where)
  }
  const del = document.createElement('button')
  del.type = 'button'
  del.className = 'm-del'
  del.textContent = '×'
  del.title = '消す（消してから 8 秒は元に戻せる）'
  del.setAttribute('aria-label', '消す')
  pressOnce(del, remove)
  const cp = document.createElement('span')
  cp.className = 'm-copy'
  cp.setAttribute('role', 'button')
  cp.tabIndex = 0
  const label = '値をコピー（Excel に貼れる形）'
  cp.title = label
  cp.setAttribute('aria-label', '値をコピー')
  cp.appendChild(icon(ICON.copy, 14))
  const doCopy = async (): Promise<void> => {
    if (await copyText(rowLine(r))) flashDone(cp, label)
  }
  // on mousedown, as the × does: a click would first blur a note being typed,
  // whose commit draws the list again and takes this control away before the
  // click lands (no focus change: the note stays open)
  cp.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return
    e.preventDefault()
    void doCopy()
  })
  cp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      void doCopy()
    }
  })
  li.append(mark, main, del, cp)
  return li
}
