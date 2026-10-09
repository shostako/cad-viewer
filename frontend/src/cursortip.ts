/**
 * The small label that follows the cursor over the 3D view (#cursor-tip), and
 * the hover logic that fills it: the value under the cursor while the
 * thickness heatmap or the draft colouring is on, and in 計測 / 注記 what a
 * click would pick (preselect.ts).
 *
 * The label never takes the pointer (pointer-events: none), so it is never in
 * the way of a click, a drag or the wheel. It lives outside the canvas and
 * outside the CSS2D label layer: a PNG export and the canvas pixels never see it.
 */

/** distance (px) from the cursor's hot spot to the label, right and down; left and up near the window's edges */
const OFFSET_X = 14
const OFFSET_Y = 18
const EDGE_PX = 4

export class CursorTip {
  readonly el: HTMLDivElement

  constructor(parent: HTMLElement) {
    this.el = document.createElement('div')
    this.el.id = 'cursor-tip'
    this.el.className = 'hidden'
    parent.appendChild(this.el)
  }

  get shown(): boolean {
    return !this.el.classList.contains('hidden')
  }

  /**
   * Show `text` beside the cursor at client (x, y), kept inside the window.
   * kind: a class for the label's look ('pick': the name of what a click
   * would pick, framed in the highlight's colour); none for a value.
   */
  show(text: string, x: number, y: number, kind = ''): void {
    if (this.el.textContent !== text) this.el.textContent = text
    if (this.el.dataset.kind !== kind) this.el.dataset.kind = kind
    this.el.classList.remove('hidden')
    const w = this.el.offsetWidth
    const h = this.el.offsetHeight
    let left = x + OFFSET_X
    let top = y + OFFSET_Y
    if (left + w > window.innerWidth - EDGE_PX) left = x - OFFSET_X - w
    if (top + h > window.innerHeight - EDGE_PX) top = y - OFFSET_Y / 2 - h
    this.el.style.left = `${Math.max(left, EDGE_PX)}px`
    this.el.style.top = `${Math.max(top, EDGE_PX)}px`
  }

  hide(): void {
    this.el.classList.add('hidden')
  }
}

/** What the tip says: a value, or text with a CursorTip kind; null: nothing (the tip hides) */
export type TipContent = string | { text: string; kind: string } | null

/**
 * Shows in a CursorTip what `describe` says is under the cursor over `target`
 * (null: nothing to say, the tip hides), looked up at most once per animation
 * frame for the last cursor position.
 *
 * The tip goes away while a button is held (a drag turns or slides the view,
 * and the touch of a finger is no hover), on a wheel turn, and when the cursor
 * leaves `target`; it comes back with the next move of the cursor. Call
 * refresh() when what is under a still cursor may have changed (the view
 * moved, the colouring changed). What `describe` draws besides the tip (the
 * preselection highlight) goes with it: onStop.
 */
export class HoverProbe {
  /** client px of the last hover move; null while there is none to show for */
  private at: [number, number] | null = null
  private queued = false
  private readonly tip: CursorTip
  private readonly describe: (clientX: number, clientY: number) => TipContent
  private readonly stopListeners: (() => void)[] = []

  constructor(target: HTMLElement, tip: CursorTip, describe: (clientX: number, clientY: number) => TipContent) {
    this.tip = tip
    this.describe = describe
    target.addEventListener('pointermove', (e) => {
      if (!e.isPrimary) return
      if (e.buttons !== 0 || e.pointerType === 'touch') return this.stop()
      this.at = [e.clientX, e.clientY]
      this.refresh()
    })
    target.addEventListener('pointerdown', () => this.stop())
    target.addEventListener('pointerleave', () => this.stop())
    // capture: the view's own wheel handler stops the event on its way down
    target.addEventListener('wheel', () => this.stop(), { capture: true, passive: true })
  }

  /** Look again at the last cursor position, on the next frame. */
  refresh(): void {
    if (!this.at || this.queued) return
    this.queued = true
    requestAnimationFrame(() => {
      this.queued = false
      const at = this.at
      if (!at) return
      const out = this.describe(at[0], at[1])
      if (out === null) this.tip.hide()
      else if (typeof out === 'string') this.tip.show(out, at[0], at[1])
      else this.tip.show(out.text, at[0], at[1], out.kind)
    })
  }

  /** Hide the tip until the cursor moves over `target` again. */
  stop(): void {
    this.at = null
    this.tip.hide()
    for (const fn of this.stopListeners) fn()
  }

  /** Called on every stop (a press, a drag, a wheel turn, the cursor leaving, stop()). */
  onStop(fn: () => void): void {
    this.stopListeners.push(fn)
  }
}
