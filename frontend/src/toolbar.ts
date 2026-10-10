/**
 * The toolbar at the top of the right-hand column (issue #23 item 10): the
 * operations used most, one click each, their keys in the titles.
 *
 *   開く · 全体表示 | 回転 · 計測 · 注記 | 断面 · 表示スタイル · 画像を保存 · ?
 *
 * The mode in use is pressed (aria-pressed), and so is 断面 while it cuts.
 * The operation panel keeps all of these as well (the E2E presses them
 * there, by name); every button here carries data-action.
 */
import type { IconNode } from 'lucide'
import { ICON, icon } from './icons'

export type Mode = 'なし' | '計測' | '注記'

export type ToolbarAction = 'open' | 'fit' | 'mode-none' | 'mode-measure' | 'mode-note' | 'section' | 'style' | 'png' | 'help'

export interface ToolbarState {
  /** a model or a drawing is on screen */
  content: boolean
  is2D: boolean
  mode: Mode
  /** the model has a B-rep (a mesh has no exact values to measure) */
  canMeasure: boolean
  section: boolean
  /** the display style's name, for the title */
  style: string
}

const LAYOUT: (ToolbarAction | '|')[] = [
  'open',
  'fit',
  '|',
  'mode-none',
  'mode-measure',
  'mode-note',
  '|',
  'section',
  'style',
  'png',
  'help',
]

const ICONS: Record<ToolbarAction, IconNode> = {
  open: ICON.open,
  fit: ICON.fit,
  'mode-none': ICON.rotate,
  'mode-measure': ICON.measure,
  'mode-note': ICON.note,
  section: ICON.section,
  style: ICON.style,
  png: ICON.png,
  help: ICON.help,
}

/** the short name (aria-label) of each button */
const NAMES: Record<ToolbarAction, string> = {
  open: 'ファイルを開く',
  fit: '全体表示',
  'mode-none': '回転',
  'mode-measure': '計測',
  'mode-note': '注記',
  section: '断面',
  style: '表示スタイル',
  png: '画像を保存',
  help: 'キー操作',
}

export class Toolbar {
  readonly el: HTMLElement
  private buttons = new Map<ToolbarAction, HTMLButtonElement>()

  constructor(el: HTMLElement, run: (action: ToolbarAction) => void) {
    this.el = el
    el.setAttribute('role', 'toolbar')
    el.setAttribute('aria-label', 'よく使う操作')
    let group: HTMLElement | null = null
    for (const item of LAYOUT) {
      if (item === '|') {
        const sep = document.createElement('span')
        sep.className = 'tb-sep'
        el.appendChild(sep)
        continue
      }
      const b = document.createElement('button')
      b.type = 'button'
      b.dataset.action = item
      b.setAttribute('aria-label', NAMES[item])
      b.appendChild(icon(ICONS[item]))
      b.addEventListener('click', () => {
        if (!b.disabled) run(item)
      })
      this.buttons.set(item, b)
      // the three modes sit in one segment
      if (item.startsWith('mode-')) {
        if (!group) {
          group = document.createElement('span')
          group.className = 'tb-group'
          group.setAttribute('role', 'group')
          group.setAttribute('aria-label', 'モード')
          el.appendChild(group)
        }
        group.appendChild(b)
      } else {
        el.appendChild(b)
      }
    }
  }

  button(action: ToolbarAction): HTMLButtonElement {
    return this.buttons.get(action)!
  }

  /** follow the app: what can be pressed, what is pressed, what the titles say */
  update(s: ToolbarState): void {
    const model3D = s.content && !s.is2D
    const set = (a: ToolbarAction, title: string, enabled = true, pressed?: boolean): void => {
      const b = this.button(a)
      b.title = title
      b.disabled = !enabled
      // a button that cannot be pressed does not look pressed (回転 on the empty screen)
      if (pressed === undefined) b.removeAttribute('aria-pressed')
      else b.setAttribute('aria-pressed', String(pressed && enabled))
    }
    set('open', 'ファイルを開く')
    set('fit', '全体表示（F・Home）', s.content)
    set('mode-none', '回転（計測・注記をやめる。Esc）', s.content, s.mode === 'なし')
    // a mesh model: pressable (the status line then says why), but looks off
    const measureOff = model3D && !s.canMeasure
    set(
      'mode-measure',
      measureOff ? '計測（M）: STEP・IGES のモデルだけ（メッシュ形式には真値が無い）' : '計測（M）',
      s.content,
      s.mode === '計測',
    )
    this.button('mode-measure').classList.toggle('off', measureOff)
    set('mode-note', s.is2D ? '注記（N）: 図面では使えない' : '注記（N）', s.content && !s.is2D, s.mode === '注記')
    set('section', s.section ? '断面（S）: 切っている' : '断面（S）', model3D, s.section)
    set('style', `表示スタイル: ${s.style}（W で順に切り替え）`, !s.is2D)
    set('png', '画像を保存（PNG）', s.content)
    set('help', 'キー操作の一覧（?）')
  }
}
