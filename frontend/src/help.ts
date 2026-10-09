/**
 * The key list (? key, or the ? at the end of the status line): what the mouse
 * and the keys do, in the 3D view or on a 2D drawing.
 *
 * It replaces the two or three lines of key help that the status card (bottom
 * left) always showed: on half a screen they took room from the model, and
 * nobody reads them after the first day.
 *
 * Not modal: the mouse and the view keys keep working while it is open, so
 * one can try what it says. It closes with ? again, Esc, its × or the ?
 * button. Placed by the caller (main.ts places it above the status card).
 */
import { version } from '../package.json'

/** a key or a mouse action; an array is keys pressed together (Shift + 矢印) */
type Key = string | string[]
interface Row {
  what: string
  /** any one of these */
  keys: Key[]
}
interface Group {
  title: string
  rows: Row[]
  note?: string
}

const TOOLS: Row[] = [
  { what: '計測の 1 点目を取り消す・計測と注記をやめる', keys: ['Esc'] },
  { what: '消した計測を元に戻す', keys: [['Ctrl', 'Z']] },
  { what: 'パネルを隠す・出す', keys: ['H'] },
  { what: 'この一覧を開く・閉じる', keys: ['?'] },
]

const HELP_3D: Group[] = [
  {
    title: '視点',
    rows: [
      { what: '回転', keys: ['左ドラッグ', '←→↑↓'] },
      { what: '移動', keys: ['右ドラッグ', ['Shift', '矢印']] },
      { what: '拡大・縮小（カーソルの位置へ）', keys: ['ホイール', '+', '−'] },
      { what: 'そこを回転の中心にする', keys: ['ダブルクリック'] },
      { what: '全体表示', keys: ['F', 'Home'] },
    ],
  },
  { title: '道具', rows: TOOLS },
]

const HELP_2D: Group[] = [
  {
    title: '図面',
    rows: [
      { what: '移動', keys: ['ドラッグ'] },
      { what: '拡大・縮小（カーソルの位置へ）', keys: ['ホイール'] },
      { what: '全体表示', keys: ['F', 'Home'] },
    ],
    note: '計測のクリックは、12 px 以内の端点・中心・四分円点にスナップする',
  },
  { title: '道具', rows: TOOLS.map((r) => (r.keys[0] === 'Esc' ? { ...r, what: '計測の 1 点目を取り消す・計測をやめる' } : r)) },
]

function kbd(text: string): HTMLElement {
  const k = document.createElement('kbd')
  k.textContent = text
  return k
}

function span(cls: string, text: string): HTMLSpanElement {
  const s = document.createElement('span')
  s.className = cls
  s.textContent = text
  return s
}

export class KeyHelp {
  private card: HTMLElement
  private body: HTMLElement
  private button: HTMLButtonElement
  private onShow: (on: boolean) => void

  /**
   * card: the (hidden) card; it gets its head, the list (#help-keys) and the
   * version. button: the ? that opens it. onShow: after it opened or closed
   * (the caller places it).
   */
  constructor(card: HTMLElement, button: HTMLButtonElement, onShow: (on: boolean) => void) {
    this.card = card
    this.button = button
    this.onShow = onShow
    const head = document.createElement('div')
    head.id = 'help-head'
    const title = span('', 'キー操作')
    title.id = 'help-title'
    const hint = document.createElement('span')
    hint.id = 'help-hint'
    hint.append(kbd('?'), ' で開閉')
    const close = document.createElement('button')
    close.type = 'button'
    close.id = 'help-close'
    close.textContent = '×'
    close.title = '閉じる（Esc）'
    close.setAttribute('aria-label', '閉じる')
    close.addEventListener('click', () => this.show(false))
    head.append(title, hint, close)
    this.body = document.createElement('div')
    this.body.id = 'help-keys'
    const foot = document.createElement('div')
    foot.id = 'help-foot'
    foot.textContent = `cad-viewer ${version}`
    card.setAttribute('role', 'dialog')
    card.setAttribute('aria-labelledby', 'help-title')
    card.replaceChildren(head, this.body, foot)
    button.setAttribute('aria-controls', card.id)
    button.setAttribute('aria-expanded', 'false')
    button.addEventListener('click', () => this.show(!this.shown))
    this.setView(false)
  }

  get shown(): boolean {
    return !this.card.classList.contains('hidden')
  }

  /** the list for the 3D view, or for a 2D drawing */
  setView(is2D: boolean): void {
    this.body.replaceChildren()
    for (const g of is2D ? HELP_2D : HELP_3D) {
      const sec = document.createElement('section')
      sec.className = 'help-group'
      sec.appendChild(span('help-group-title', g.title))
      for (const r of g.rows) {
        const row = document.createElement('div')
        row.className = 'help-row'
        const keys = document.createElement('span')
        keys.className = 'help-keys'
        r.keys.forEach((k, i) => {
          if (i) keys.appendChild(span('help-or', '/'))
          if (typeof k === 'string') keys.appendChild(kbd(k))
          else
            k.forEach((part, j) => {
              if (j) keys.appendChild(span('help-plus', '+'))
              keys.appendChild(kbd(part))
            })
        })
        row.append(span('help-what', r.what), keys)
        sec.appendChild(row)
      }
      if (g.note) sec.appendChild(span('help-note', g.note))
      this.body.appendChild(sec)
    }
  }

  show(on: boolean): void {
    if (on === this.shown) return
    // the keyboard is in the card (its ×): it would be left in a hidden element
    if (!on && this.card.contains(document.activeElement)) this.button.focus({ preventScroll: true })
    this.card.classList.toggle('hidden', !on)
    this.button.setAttribute('aria-expanded', String(on))
    this.onShow(on)
  }
}
