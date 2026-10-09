/**
 * The card in the middle of the screen while a file loads, and when it could
 * not be opened (#load-card).
 *
 * Loading: the file's name and size, the step it is at (送信 → 形状の変換 →
 * 表示の準備) and a bar: the share sent while the file goes up, then a moving
 * bar while the backend converts the shape and the page builds the view.
 * Failed: what went wrong in plain words, the file's name, the backend's own
 * message behind 詳細を見る, and 別のファイルを選ぶ / 閉じる.
 *
 * Its own element, not the empty screen's card (#empty-hint): that one comes
 * and goes with what is on screen; this one with a load.
 */
import { UploadError } from './api'

export type LoadStep = 'send' | 'convert' | 'prepare'

const STEPS: [LoadStep, string][] = [
  ['send', '送信'],
  ['convert', '形状の変換'],
  ['prepare', '表示の準備'],
]

/** a triangle with an exclamation mark (drawn here: no icon set yet) */
const WARNING_SVG =
  '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2"' +
  ' stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 22 20.5H2Z"/><path d="M12 10v4.5"/>' +
  '<path d="M12 17.5h.01"/></svg>'

/** 39 KB, 1.2 MB: the size as the file's owner reads it */
export function fileSizeText(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export class LoadCard {
  private readonly el: HTMLElement
  private readonly icon: HTMLElement
  private readonly title: HTMLElement
  private readonly file: HTMLElement
  private readonly fill: HTMLElement
  private readonly steps: HTMLOListElement
  private readonly reason: HTMLElement
  private readonly detail: HTMLElement
  private readonly more: HTMLButtonElement

  private readonly place: () => void

  /**
   * el: the card's element (filled here). onAnother: 別のファイルを選ぶ
   * (open the file dialog). onClose: the failed card was closed. place: puts
   * the card where it goes on screen (called whenever it shows or changes size).
   */
  constructor(el: HTMLElement, onAnother: () => void, onClose: () => void, place: () => void) {
    this.el = el
    this.place = place
    el.innerHTML = `
      <div id="load-icon" aria-hidden="true"></div>
      <div id="load-title"></div>
      <div id="load-file"></div>
      <div id="load-bar"><div id="load-bar-fill"></div></div>
      <ol id="load-steps"></ol>
      <div id="load-reason"></div>
      <pre id="load-detail" class="hidden"></pre>
      <div id="load-actions">
        <button id="load-another" type="button">別のファイルを選ぶ</button>
        <button id="load-more" type="button">詳細を見る</button>
        <button id="load-close" type="button">閉じる</button>
      </div>`
    const q = <T extends HTMLElement>(sel: string) => el.querySelector<T>(sel)!
    this.icon = q('#load-icon')
    this.title = q('#load-title')
    this.file = q('#load-file')
    this.fill = q('#load-bar-fill')
    this.steps = q<HTMLOListElement>('#load-steps')
    this.reason = q('#load-reason')
    this.detail = q('#load-detail')
    this.more = q<HTMLButtonElement>('#load-more')
    for (const [step, label] of STEPS) {
      const li = document.createElement('li')
      li.dataset.step = step
      li.textContent = label
      this.steps.appendChild(li)
    }
    q('#load-another').addEventListener('click', onAnother)
    q('#load-close').addEventListener('click', () => {
      this.hide()
      onClose()
    })
    this.more.addEventListener('click', () => {
      const open = this.detail.classList.toggle('hidden') === false
      this.more.textContent = open ? '詳細を隠す' : '詳細を見る'
    })
  }

  get failed(): boolean {
    return !this.el.classList.contains('hidden') && this.el.classList.contains('failed')
  }

  /** a load begins: the file, at 送信 with nothing sent yet */
  start(file: File): void {
    this.el.classList.remove('hidden', 'failed')
    this.el.setAttribute('role', 'status')
    this.icon.innerHTML = '<div class="load-spinner"></div>'
    this.title.textContent = '読み込み中'
    this.file.textContent = `${file.name}（${fileSizeText(file.size)}）`
    this.reason.textContent = ''
    this.detail.textContent = ''
    this.detail.classList.add('hidden')
    this.more.textContent = '詳細を見る'
    this.step('send')
    this.sent(0)
    this.place()
  }

  /** the share of the file sent so far (0..1), while at 送信 */
  sent(fraction: number): void {
    this.fill.style.width = `${Math.round(Math.min(Math.max(fraction, 0), 1) * 100)}%`
  }

  /** the load has reached `step`: the ones before it are done */
  step(step: LoadStep): void {
    const at = STEPS.findIndex(([s]) => s === step)
    this.steps.querySelectorAll('li').forEach((li, i) => {
      li.className = i < at ? 'done' : i === at ? 'active' : ''
    })
    // after the upload the time left is unknown: a moving bar
    this.el.classList.toggle('indeterminate', step !== 'send')
    if (step !== 'send') this.fill.style.width = ''
  }

  /** the load failed: reason in plain words, detail = the original message */
  fail(fileName: string, reason: string, detail: string): void {
    this.el.classList.remove('hidden', 'indeterminate')
    this.el.classList.add('failed')
    this.el.setAttribute('role', 'alert')
    this.icon.innerHTML = WARNING_SVG
    this.title.textContent = 'ファイルを開けなかった'
    this.file.textContent = fileName
    this.reason.textContent = reason
    this.detail.textContent = detail
    this.detail.classList.add('hidden')
    this.more.textContent = '詳細を見る'
    this.more.hidden = detail === ''
    this.place()
  }

  hide(): void {
    this.el.classList.add('hidden')
    this.el.classList.remove('failed', 'indeterminate')
  }
}

const FORMAT_NAMES: Record<string, string> = {
  step: 'STEP',
  stp: 'STEP',
  iges: 'IGES',
  igs: 'IGES',
  stl: 'STL',
  '3mf': '3MF',
  obj: 'OBJ',
  ply: 'PLY',
  dxf: 'DXF',
  dwg: 'DWG',
}

/**
 * Why a load failed, in words for the person who chose the file, from the
 * error and the step it happened at (after the upload: the shape or the
 * drawing did not arrive).
 */
export function failureReason(e: unknown, fileName: string, step: LoadStep): string {
  const ext = fileName.includes('.') ? fileName.split('.').pop()!.toLowerCase() : ''
  const kind = FORMAT_NAMES[ext] ?? 'この形式'
  if (e instanceof UploadError) {
    switch (e.status) {
      case 0:
        return 'backend につながらない。backend が動いているか確かめる'
      case 400:
        return 'ファイルが空（0 バイト）'
      case 413:
        return 'ファイルが大きすぎる（500 MB まで）'
      case 415:
        return 'この形式には対応していない（STEP / IGES / STL / 3MF / OBJ / PLY / DXF / DWG）'
      case 422:
        // the drawing loader already says why in Japanese (e.g. DWG without the converter)
        if (/[\u3040-\u30ff\u4e00-\u9fff]/.test(e.message)) return e.message
        return `${kind} として読めない。ファイルが壊れているか、対応していない書き方の可能性がある`
      default:
        return `backend で問題が起きた（HTTP ${e.status}）`
    }
  }
  if (step === 'prepare') return '形状を受け取れなかった。通信が切れたか、backend が止まった可能性がある'
  return '読み込みの途中で問題が起きた'
}
