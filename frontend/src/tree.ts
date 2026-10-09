/**
 * The part tree (top left): where work on single parts starts.
 *
 * A row has a box (shown / hidden), a mark in the colour the 3D view draws
 * the part in, the name, and a small number when other parts have the same
 * name (core_pin 1, core_pin 2, numbered down the tree). Two buttons show
 * while the pointer is on the row or the keyboard is in it: これだけ表示 (the
 * other parts are hidden) and この部品へ寄る (the view fits the part as 全体
 * 表示 fits the model; not for a hidden part). A group row does the same for
 * all the parts under it, and its box is half set while only some are shown.
 * The header folds the tree, gives the number of parts, and has 全部表示.
 *
 * The row under the pointer highlights its parts in the 3D view, only while
 * the pointer is on it; so does the row the keyboard is in (focus-visible). A
 * press on the row ends the highlight until the pointer moves again: the
 * click has acted, and the tint would only colour the part it now shows. The
 * other way, markFrom3D marks the row of the part under the cursor in the 3D
 * view.
 *
 * The E2E scripts find rows by their label: it holds the box, an empty colour
 * mark (<i>) and the name in a span, nothing else. The number and the buttons
 * sit beside the label.
 */
import type { TreeNodeData } from './model'

export interface PartTreeHooks {
  /** these parts were shown (true) or hidden (false) in the tree; its boxes already say so */
  setVisible(changes: ReadonlyMap<number, boolean>): void
  /** highlight these parts in the 3D view (empty: none) */
  highlight(partIds: readonly number[]): void
  /** この部品へ寄る: fit the view to these parts (the shown ones of a row) */
  zoomTo(partIds: readonly number[]): void
  /** the CSS colour the 3D view draws a part in */
  colorOf(partId: number): string
}

interface Row {
  el: HTMLDivElement
  box: HTMLInputElement
  zoom: HTMLButtonElement
  /** the parts under the row: its own for a part, all below it for a group */
  parts: number[]
  isGroup: boolean
}

// icons: 16 x 16, drawn in the button's text colour
const ONLY_ICON =
  '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4">' +
  '<g opacity=".45"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/>' +
  '<rect x="2" y="9" width="5" height="5" rx="1"/></g>' +
  '<rect x="9" y="9" width="5" height="5" rx="1" fill="currentColor"/></svg>'
const ZOOM_ICON =
  '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4">' +
  '<path d="M2 5.5V2h3.5M10.5 2H14v3.5M14 10.5V14h-3.5M5.5 14H2v-3.5"/>' +
  '<rect x="5.5" y="5.5" width="5" height="5" rx="1" fill="currentColor" stroke="none"/></svg>'
const FOLD_ICON =
  '<svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2">' +
  '<path d="M3.5 6l4.5 4.5L12.5 6"/></svg>'

const ZOOM_TITLE = { part: 'この部品へ寄る', group: 'このグループへ寄る', hidden: '隠している部品には寄れない' }

export class PartTree {
  private readonly panel: HTMLElement
  private readonly hooks: PartTreeHooks
  private readonly body: HTMLDivElement
  private readonly foldBtn: HTMLButtonElement
  private readonly countEl: HTMLSpanElement
  private readonly showAllBtn: HTMLButtonElement
  private rows: Row[] = []
  /** the row of each part */
  private partRows = new Map<number, Row>()
  /** shown or hidden, per part */
  private visible = new Map<number, boolean>()
  /** the row under the pointer; null after a press on it, until the pointer moves again */
  private pointerRow: Row | null = null
  /** the row the keyboard focus is in (focus-visible only: a click leaves focus behind too) */
  private keyRow: Row | null = null
  /** the row whose parts are highlighted now */
  private litRow: Row | null = null
  /** the row marked from the 3D view */
  private markedRow: Row | null = null
  private folded = false

  constructor(panel: HTMLElement, hooks: PartTreeHooks) {
    this.panel = panel
    this.hooks = hooks
    const head = document.createElement('div')
    head.id = 'tree-head'
    this.foldBtn = document.createElement('button')
    this.foldBtn.type = 'button'
    this.foldBtn.id = 'tree-fold'
    this.foldBtn.setAttribute('aria-controls', 'tree-body')
    this.foldBtn.innerHTML = `${FOLD_ICON}<span id="tree-title">部品ツリー</span>`
    this.foldBtn.addEventListener('click', () => this.setFolded(!this.folded))
    this.countEl = document.createElement('span')
    this.countEl.id = 'tree-count'
    this.showAllBtn = document.createElement('button')
    this.showAllBtn.type = 'button'
    this.showAllBtn.id = 'tree-show-all'
    this.showAllBtn.textContent = '全部表示'
    this.showAllBtn.title = '隠した部品を全部表示する'
    this.showAllBtn.addEventListener('click', () => this.apply(() => true))
    head.append(this.foldBtn, this.countEl, this.showAllBtn)
    this.body = document.createElement('div')
    this.body.id = 'tree-body'
    panel.replaceChildren(head, this.body)
    this.setFolded(false)
  }

  /** whether a tree is on the panel */
  get hasRows(): boolean {
    return this.rows.length > 0
  }

  /** Show the tree of a newly loaded model, every part shown. */
  show(tree: TreeNodeData): void {
    this.clear()
    // names used more than once get numbers, parts and groups apart
    const uses = new Map<string, number>()
    const count = (node: TreeNodeData): void => {
      const key = nameKey(node)
      uses.set(key, (uses.get(key) ?? 0) + 1)
      node.children?.forEach(count)
    }
    const top = tree.children ?? [] // the artificial "root" node is not shown; its children are
    top.forEach(count)
    const next = new Map<string, number>()
    const list = document.createElement('ul')
    list.className = 'tree-root'
    const add = (node: TreeNodeData, into: HTMLUListElement): number[] => {
      const key = nameKey(node)
      let num = 0
      if ((uses.get(key) ?? 0) > 1) {
        num = (next.get(key) ?? 0) + 1
        next.set(key, num)
      }
      const li = document.createElement('li')
      into.appendChild(li)
      const row = this.makeRow(node, num)
      li.appendChild(row.el)
      if (node.partId !== undefined) {
        row.parts.push(node.partId)
        this.partRows.set(node.partId, row)
        this.visible.set(node.partId, true)
      }
      if (node.children?.length) {
        const ul = document.createElement('ul')
        li.appendChild(ul)
        for (const child of node.children) row.parts.push(...add(child, ul))
      }
      return row.parts
    }
    for (const node of top) add(node, list)
    this.body.appendChild(list)
    const n = this.visible.size
    this.countEl.textContent = String(n)
    this.countEl.title = `部品 ${n} 個`
    this.sync()
  }

  /** No tree (a load in progress, a drawing, a model of one mesh). */
  clear(): void {
    this.body.replaceChildren()
    this.rows = []
    this.partRows.clear()
    this.visible.clear()
    this.pointerRow = null
    this.keyRow = null
    this.markedRow = null
    this.countEl.textContent = ''
    this.updateHighlight()
  }

  /**
   * Mark the row of the part under the cursor in the 3D view (null: none),
   * and scroll it into the tree's view if it is out of it.
   */
  markFrom3D(partId: number | null): void {
    const row = partId === null ? null : (this.partRows.get(partId) ?? null)
    if (row === this.markedRow) return
    this.markedRow?.el.classList.remove('under-cursor')
    this.markedRow = row
    if (!row) return
    row.el.classList.add('under-cursor')
    if (this.folded) return
    const view = this.body.getBoundingClientRect()
    const r = row.el.getBoundingClientRect()
    if (r.top < view.top) this.body.scrollTop -= view.top - r.top
    else if (r.bottom > view.bottom) this.body.scrollTop += r.bottom - view.bottom
  }

  /** Let go of the keyboard focus if it is in the tree (the panel is about to be hidden). */
  releaseFocus(): void {
    const el = document.activeElement
    if (el instanceof HTMLElement && this.panel.contains(el)) el.blur()
  }

  private setFolded(on: boolean): void {
    this.folded = on
    this.panel.classList.toggle('folded', on)
    this.foldBtn.setAttribute('aria-expanded', String(!on))
    this.foldBtn.title = on ? '部品ツリーを広げる' : '部品ツリーを畳む'
  }

  private makeRow(node: TreeNodeData, num: number): Row {
    const isGroup = node.partId === undefined
    const shown = num ? `${node.name} ${num}` : node.name
    const el = document.createElement('div')
    el.className = 'tree-row'
    const label = document.createElement('label')
    const box = document.createElement('input')
    box.type = 'checkbox'
    box.checked = true
    // the label's text is the bare name: a screen reader would read both core_pin rows alike
    if (num) box.setAttribute('aria-label', shown)
    label.appendChild(box)
    if (node.partId !== undefined) {
      const mark = document.createElement('i')
      mark.className = 'tree-mark'
      mark.style.backgroundColor = this.hooks.colorOf(node.partId)
      label.appendChild(mark)
    }
    const name = document.createElement('span')
    name.textContent = node.name
    label.appendChild(name)
    el.appendChild(label)
    if (num) {
      const n = document.createElement('small')
      n.className = 'tree-num'
      n.textContent = String(num)
      el.appendChild(n)
    }
    const actions = document.createElement('div')
    actions.className = 'tree-actions'
    const only = iconButton('tree-only', isGroup ? 'このグループだけ表示' : 'これだけ表示', `${shown} だけ表示`, ONLY_ICON)
    const zoom = iconButton('tree-zoom', isGroup ? ZOOM_TITLE.group : ZOOM_TITLE.part, `${shown} へ寄る`, ZOOM_ICON)
    actions.append(only, zoom)
    el.appendChild(actions)
    const row: Row = { el, box, zoom, parts: [], isGroup }
    this.rows.push(row)

    box.addEventListener('change', () => {
      const mine = new Set(row.parts)
      const on = box.checked
      this.apply((id, was) => (mine.has(id) ? on : was))
    })
    only.addEventListener('click', () => {
      const mine = new Set(row.parts)
      this.apply((id) => mine.has(id))
    })
    zoom.addEventListener('click', () => {
      const shownParts = row.parts.filter((id) => this.visible.get(id))
      if (shownParts.length) this.hooks.zoomTo(shownParts)
    })
    // the whole name on a row too narrow for it
    label.addEventListener('pointerenter', () => {
      label.title = name.scrollWidth > name.clientWidth ? shown : ''
    })
    el.addEventListener('pointerenter', (e) => {
      if (e.buttons === 0) this.setPointerRow(row)
    })
    el.addEventListener('pointermove', (e) => {
      if (e.buttons === 0 && this.pointerRow !== row) this.setPointerRow(row)
    })
    el.addEventListener('pointerleave', () => {
      if (this.pointerRow === row) this.setPointerRow(null)
    })
    el.addEventListener('pointerdown', () => this.setPointerRow(null))
    el.addEventListener('focusin', (e) => {
      this.keyRow = e.target instanceof Element && e.target.matches(':focus-visible') ? row : null
      this.updateHighlight()
    })
    el.addEventListener('focusout', (e) => {
      if (e.relatedTarget instanceof Node && el.contains(e.relatedTarget)) return
      if (this.keyRow === row) this.keyRow = null
      this.updateHighlight()
    })
    return row
  }

  private setPointerRow(row: Row | null): void {
    this.pointerRow = row
    this.updateHighlight()
  }

  /** the pointer's row first, else the keyboard's: its parts are highlighted */
  private updateHighlight(): void {
    const row = this.pointerRow ?? this.keyRow
    if (row === this.litRow) return
    this.litRow = row
    this.hooks.highlight(row ? row.parts : [])
  }

  /** Show / hide the parts as want says (was: shown now), then bring the boxes and buttons up to date. */
  private apply(want: (partId: number, was: boolean) => boolean): void {
    const changes = new Map<number, boolean>()
    for (const [id, was] of this.visible) {
      const on = want(id, was)
      if (on !== was) {
        this.visible.set(id, on)
        changes.set(id, on)
      }
    }
    this.sync()
    if (changes.size) this.hooks.setVisible(changes)
  }

  /** boxes (a group: set when all its parts are shown, half set when some are), 寄る, 全部表示 */
  private sync(): void {
    for (const row of this.rows) {
      let on = 0
      for (const id of row.parts) if (this.visible.get(id)) on++
      row.box.checked = on > 0
      row.box.indeterminate = on > 0 && on < row.parts.length
      row.zoom.disabled = on === 0
      row.zoom.title = on === 0 ? ZOOM_TITLE.hidden : row.isGroup ? ZOOM_TITLE.group : ZOOM_TITLE.part
      row.el.classList.toggle('off', on === 0)
    }
    this.showAllBtn.disabled = [...this.visible.values()].every((v) => v)
  }
}

function nameKey(node: TreeNodeData): string {
  return (node.partId === undefined ? 'g:' : 'p:') + node.name
}

function iconButton(cls: string, title: string, label: string, icon: string): HTMLButtonElement {
  const b = document.createElement('button')
  b.type = 'button'
  b.className = `tree-btn ${cls}`
  b.title = title
  b.setAttribute('aria-label', label)
  b.innerHTML = icon
  return b
}
