/**
 * The 計測 list as a record to copy into a report or Excel (issue #23 item 8).
 *
 * A row shows its value first, with its unit ("20.000 mm"), a mark of its
 * kind (distance, ⌀, note), and what was measured on a second, smaller line
 * ("cavity_block 面#6 ↔ plate 面#6"). Each row copies its own line, the
 * list's head copies all of them: tab separated (種類, 値, 単位, 対象 A,
 * 対象 B), which Excel pastes into cells.
 *
 * The saved entries (sidecars) keep their form: a row is read out of an
 * entry's text and label as the measure tool writes them, so entries saved
 * before this change show the same way.
 */
import type { IconNode } from 'lucide'
import type { Measurement2D } from './drawing2d'
import { ICON, icon } from './icons'
import { LENGTH_UNIT, type EntryData } from './measure'

export type RowKind = 'distance' | 'diameter' | 'angle' | 'note' | 'other'

export interface RowView {
  kind: RowKind
  /** the number (or a note's text); '' when there is none */
  value: string
  unit: string
  /** the second line: what was measured */
  what: string
  /** for the copy: the two things measured (a diameter or a note has one) */
  a: string
  b: string
}

const KIND_NAME: Record<RowKind, string> = { distance: '距離', diameter: '直径', angle: '角度', note: '注記', other: '' }

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
  // "core_pin 円エッジ ⌀8.000 (L=25.133)", "円筒面 ⌀8.000"
  const dia = /^(.*?)\s*⌀([-\d.]+)(.*)$/.exec(d.text)
  if (d.labelText.startsWith('⌀') && dia) {
    const what = `${dia[1]}${dia[3]}`.trim()
    return { kind: 'diameter', value: dia[2], unit: LENGTH_UNIT, what, a: what, b: '' }
  }
  // "cavity_block 面#6 ∠ cavity_block 面#3 : 90.000°"
  const ang = /^(.*) ∠ (.*) : ([-\d.]+)°$/.exec(d.text)
  if (ang) return { kind: 'angle', value: ang[3], unit: '°', what: `${ang[1]} ∠ ${ang[2]}`, a: ang[1], b: ang[2] }
  // "cavity_block 面#6 ↔ plate 面#6 : 20.000"
  const dist = /^(.*) ↔ (.*) : ([-\d.]+)$/.exec(d.text)
  if (dist) {
    return { kind: 'distance', value: dist[3], unit: LENGTH_UNIT, what: `${dist[1]} ↔ ${dist[2]}`, a: dist[1], b: dist[2] }
  }
  return { kind: 'other', value: '', unit: '', what: d.text, a: d.text, b: '' }
}

/**
 * A drawing's measurement as a row: the distance, and its ΔX and ΔY on the
 * second line. No unit: a drawing's numbers are in its own unit (the DXF
 * does not always say which).
 */
export function drawingRow(m: Measurement2D): RowView {
  const dx = m.b.dxf[0] - m.a.dxf[0]
  const dy = m.b.dxf[1] - m.a.dxf[1]
  const fx = `ΔX ${Math.abs(dx).toFixed(3)}`
  const fy = `ΔY ${Math.abs(dy).toFixed(3)}`
  return { kind: 'distance', value: Math.hypot(dx, dy).toFixed(3), unit: '', what: `${fx}　${fy}`, a: fx, b: fy }
}

/** a cell of the copied text: a tab or a line break inside it would split the cells */
function cell(s: string): string {
  return s.replace(/[\t\r\n]+/g, ' ')
}

/** one row as a line of tab-separated cells */
export function rowLine(r: RowView): string {
  return [KIND_NAME[r.kind], r.value, r.unit, r.a, r.b].map(cell).join('\t')
}

/** the whole list: a head line, then a line per row (Excel pastes it into cells) */
export function listText(rows: readonly RowView[]): string {
  return ['種類\t値\t単位\t対象 A\t対象 B', ...rows.map(rowLine)].join('\n')
}

/** the mark of a row's kind (Lucide) */
const KIND_ICON: Record<RowKind, IconNode | null> = {
  distance: ICON.distance,
  diameter: ICON.diameter,
  angle: ICON.angle,
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
  // file-supplied text (a note): textContent only. A diameter shows its ⌀
  // (the copy keeps the bare number, for Excel)
  value.textContent = r.value ? `${r.kind === 'diameter' ? '⌀' : ''}${r.value}` : r.what
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
