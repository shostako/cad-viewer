/** 2D drawing viewer: pan/zoom via viewBox mutation + snap measurement.
 *
 * The backend SVG is injected as-is, apart from its page colour (made the 3D
 * view's background), and pan/zoom changes its viewBox (keeps getScreenCTM()
 * exact). The measurements are drawn in a second <svg> laid over it, in screen
 * pixels, and placed again on every pan, zoom, fit and resize: markers, lines
 * and values keep their size at any zoom and window width. (Drawn in the
 * drawing's own units, a viewBox about 1e6 wide, a 13 px value needed a font
 * size of 1e4 units and more, which Chromium caps at 10000: the value shrank
 * on a window narrower than about 1330 px.) Snap points carry both svg coords
 * (display) and dxf coords (exact measurement values).
 */

import { swapPageColour, toWhitePage, type ExportBackground } from './snapshot'

export interface SnapPoint {
  dxf: [number, number]
  svg: [number, number]
  kind: string
}

/** A distance between two snap points; its values come from their dxf coords. */
export interface Measurement2D {
  a: SnapPoint
  b: SnapPoint
}

/** A measurement of the list: the id names its row (its ×). */
export interface Measurement2DEntry extends Measurement2D {
  id: number
}

/** The HUD line and the 計測 list row of a measurement: "距離 d (ΔX dx, ΔY dy)" */
export function measurementText(m: Measurement2D): string {
  const dx = m.b.dxf[0] - m.a.dxf[0]
  const dy = m.b.dxf[1] - m.a.dxf[1]
  return `距離 ${fmt(Math.hypot(dx, dy))} (ΔX ${fmt(Math.abs(dx))}, ΔY ${fmt(Math.abs(dy))})`
}

/** The page on screen: the 3D view's background (viewer.ts; #viewport2d in style.css too) */
const PAGE_COLOUR = '#1d2126'

const SNAP_PX = 12
const SVG_NS = 'http://www.w3.org/2000/svg'
// the measurement layer, in screen px
const MARKER_R = 5
const LINE_PX = 1.5
const FONT_PX = 13
const HALO_PX = 3
const MARKER_COLOUR = '#ffb020'
const DIM_COLOUR = '#ffd060'
/** the value's outline: it keeps the pale value readable on the white page of an export */
const HALO_COLOUR = '#1d2126'

export class Drawing2D {
  private container: HTMLElement
  private hud: (msg: string) => void
  private svg: SVGSVGElement | null = null
  /** the measurement layer over the drawing (screen px) and the group it draws in */
  private layer: SVGSVGElement | null = null
  private overlayG: SVGGElement | null = null
  private snaps: SnapPoint[] = []
  private vb = { x: 0, y: 0, w: 1, h: 1 }
  private baseVb = { x: 0, y: 0, w: 1, h: 1 }
  private pendingSnap: SnapPoint | null = null
  private items: Measurement2DEntry[] = []
  private nextId = 1
  private changeListeners: (() => void)[] = []
  measureMode = false

  constructor(container: HTMLElement, hud: (msg: string) => void) {
    this.container = container
    this.hud = hud
    this.bindEvents()
    // the viewBox is fitted into the box (meet): a resize moves the drawing on
    // screen, and the layer must follow it. Reported after layout, before paint.
    new ResizeObserver(() => this.renderOverlay()).observe(container)
  }

  load(svgText: string, snaps: SnapPoint[]): void {
    this.container.innerHTML = svgText
    this.svg = this.container.querySelector('svg')
    if (!this.svg) throw new Error('svg payload broken')
    this.svg.removeAttribute('width')
    this.svg.removeAttribute('height')
    this.svg.style.width = '100%'
    this.svg.style.height = '100%'
    this.svg.setAttribute('preserveAspectRatio', 'xMidYMid meet')

    const [x, y, w, h] = (this.svg.getAttribute('viewBox') ?? '0 0 1 1')
      .split(/\s+/)
      .map(Number)
    this.vb = { x, y, w, h }
    this.baseVb = { x, y, w, h }

    // The page is the 3D view's background: the drawing's own page colour
    // (ezdxf #212830, also the fill of WIPEOUT masks, which must stay unseen)
    // becomes it. The lines keep the drawing's colours: ezdxf draws them for a
    // dark page, colour 7 (white / black) in white, and the page is still dark.
    const page = this.svg.querySelector(':scope > rect')?.getAttribute('fill') ?? null
    recolour(this.svg, (css) => swapPageColour(css, page, PAGE_COLOUR))

    this.layer = svgEl('svg', { class: 'overlay2d-layer' })
    this.overlayG = svgEl('g', { class: 'overlay2d' })
    this.layer.appendChild(this.overlayG)
    this.container.appendChild(this.layer)
    this.snaps = snaps
    this.pendingSnap = null
    this.items = []
    this.emit()
  }

  /** drop the drawing (the next load starts from an empty viewer) */
  clear(): void {
    this.container.replaceChildren()
    this.svg = null
    this.layer = null
    this.overlayG = null
    this.snaps = []
    this.pendingSnap = null
    this.items = []
    this.emit()
  }

  /** called when the measurements change: one added, removed, cleared, restored, a load */
  onChange(fn: () => void): void {
    this.changeListeners.push(fn)
  }

  private emit(): void {
    for (const fn of this.changeListeners) fn()
  }

  /** the completed measurements, oldest first */
  measurements(): readonly Measurement2DEntry[] {
    return this.items
  }

  /** Delete one measurement (its × in the list). A chosen first point stays. */
  removeMeasurement(id: number): void {
    const i = this.items.findIndex((m) => m.id === id)
    if (i < 0) return
    this.items.splice(i, 1)
    this.renderOverlay()
    this.emit()
  }

  /** Delete every measurement (計測クリア), and a chosen first point. */
  clearMeasurements(): void {
    this.items = []
    this.pendingSnap = null
    this.renderOverlay()
    this.emit()
  }

  /** The completed measurements, to put back after a deletion (restoreMeasurements). */
  measurementsSnapshot(): Measurement2D[] {
    return this.items.map(({ a, b }) => ({ a, b }))
  }

  /**
   * Replace the measurements with a snapshot (the undo of a deletion), in its
   * order. A chosen first point stays: the user may have started the next
   * measurement before undoing.
   */
  restoreMeasurements(list: readonly Measurement2D[]): void {
    this.items = list.map(({ a, b }) => ({ id: this.nextId++, a, b }))
    this.renderOverlay()
    this.emit()
  }

  /** Drop a chosen first point (Esc). Returns whether there was one. */
  cancelPending(): boolean {
    if (!this.pendingSnap) return false
    this.pendingSnap = null
    this.renderOverlay()
    this.hud('1 点目を取り消した（もう一度 Esc で計測をやめる）')
    return true
  }

  private applyViewBox(): void {
    this.svg?.setAttribute('viewBox', `${this.vb.x} ${this.vb.y} ${this.vb.w} ${this.vb.h}`)
    this.renderOverlay()
  }

  /** svg-units per screen pixel (uniform thanks to preserveAspectRatio meet) */
  private unitsPerPx(): number {
    if (!this.svg) return 1
    const r = this.svg.getBoundingClientRect()
    return Math.max(this.vb.w / r.width, this.vb.h / r.height)
  }

  private clientToSvg(cx: number, cy: number): [number, number] {
    if (!this.svg) return [0, 0]
    const ctm = this.svg.getScreenCTM()
    if (!ctm) return [0, 0]
    const pt = new DOMPoint(cx, cy).matrixTransform(ctm.inverse())
    return [pt.x, pt.y]
  }

  private bindEvents(): void {
    let panning = false
    let last: [number, number] = [0, 0]
    let downAt: [number, number] | null = null

    this.container.addEventListener('pointerdown', (e) => {
      panning = true
      last = [e.clientX, e.clientY]
      downAt = [e.clientX, e.clientY]
      this.container.setPointerCapture(e.pointerId)
    })
    this.container.addEventListener('pointermove', (e) => {
      if (!panning || !this.svg) return
      const scale = this.unitsPerPx()
      this.vb.x -= (e.clientX - last[0]) * scale
      this.vb.y -= (e.clientY - last[1]) * scale
      last = [e.clientX, e.clientY]
      this.applyViewBox()
    })
    this.container.addEventListener('pointerup', (e) => {
      panning = false
      if (!downAt) return
      const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1])
      downAt = null
      if (moved <= 5 && this.measureMode) this.handleClick(e.clientX, e.clientY)
    })
    // don't leave the pan state stuck if the pointer stream is interrupted
    for (const ev of ['pointercancel', 'lostpointercapture'] as const) {
      this.container.addEventListener(ev, () => {
        panning = false
        downAt = null
      })
    }
    this.container.addEventListener('wheel', (e) => {
      if (!this.svg) return
      e.preventDefault()
      const factor = e.deltaY > 0 ? 1.2 : 1 / 1.2
      const [mx, my] = this.clientToSvg(e.clientX, e.clientY)
      this.vb.x = mx - (mx - this.vb.x) * factor
      this.vb.y = my - (my - this.vb.y) * factor
      this.vb.w *= factor
      this.vb.h *= factor
      this.applyViewBox()
    })
  }

  fit(): void {
    this.vb = { ...this.baseVb }
    this.applyViewBox()
  }

  /**
   * The drawing as on screen (current viewBox = current pan and zoom) with the
   * measurement layer on top, rasterised at device-pixel resolution. 'white'
   * gives a white page with the drawing colours made to read on it
   * (whitenDrawing); the measurements keep their colours on either page.
   */
  async snapshot(background: ExportBackground): Promise<HTMLCanvasElement> {
    const svg = this.svg
    const layer = this.layer
    if (!svg || !layer) throw new Error('図面が開かれていない')
    const rect = svg.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const w = Math.max(1, Math.round(rect.width * dpr))
    const h = Math.max(1, Math.round(rect.height * dpr))
    const k = w / rect.width
    // clone at the click: a load that starts during the async decode can't change it
    const clone = svg.cloneNode(true) as SVGSVGElement
    clone.removeAttribute('style')
    // the viewBox and preserveAspectRatio come along, so the mapping is the screen's
    clone.setAttribute('width', String(w))
    clone.setAttribute('height', String(h))
    // a standalone SVG image does not inherit the page font
    clone.setAttribute('font-family', getComputedStyle(svg).fontFamily)
    if (background === 'white') whitenDrawing(clone)

    // The measurements: the layer is in screen px, so its viewBox is its CSS
    // size and the image scales it to device px like the drawing. Where it is
    // on screen relative to the drawing, it is in the image.
    const lr = layer.getBoundingClientRect()
    const at = { x: (lr.left - rect.left) * k, y: (lr.top - rect.top) * k, w: lr.width * k, h: lr.height * k }
    let over: SVGSVGElement | null = null
    if (this.overlayG?.hasChildNodes() && lr.width > 0 && lr.height > 0) {
      over = layer.cloneNode(true) as SVGSVGElement
      over.removeAttribute('class')
      over.setAttribute('viewBox', `0 0 ${lr.width} ${lr.height}`)
      over.setAttribute('width', String(at.w))
      over.setAttribute('height', String(at.h))
      over.setAttribute('font-family', getComputedStyle(layer).fontFamily)
    }

    const urls: string[] = []
    const image = async (el: SVGSVGElement): Promise<HTMLImageElement> => {
      const url = URL.createObjectURL(
        new Blob([new XMLSerializer().serializeToString(el)], { type: 'image/svg+xml' }),
      )
      urls.push(url)
      const img = new Image()
      img.src = url
      await img.decode()
      return img
    }
    try {
      const img = await image(clone)
      const overImg = over ? await image(over) : null
      const out = document.createElement('canvas')
      out.width = w
      out.height = h
      const ctx = out.getContext('2d')
      if (!ctx) throw new Error('画像を作れない')
      // the page around the drawing: the container colour on screen
      ctx.fillStyle = background === 'white' ? '#ffffff' : getComputedStyle(this.container).backgroundColor
      ctx.fillRect(0, 0, w, h)
      ctx.drawImage(img, 0, 0, w, h)
      if (overImg) ctx.drawImage(overImg, at.x, at.y, at.w, at.h)
      return out
    } finally {
      for (const url of urls) URL.revokeObjectURL(url)
    }
  }

  private nearestSnap(cx: number, cy: number): SnapPoint | null {
    const [sx, sy] = this.clientToSvg(cx, cy)
    const maxDist = SNAP_PX * this.unitsPerPx()
    let best: SnapPoint | null = null
    let bestD = maxDist
    for (const s of this.snaps) {
      const d = Math.hypot(s.svg[0] - sx, s.svg[1] - sy)
      if (d < bestD) {
        bestD = d
        best = s
      }
    }
    return best
  }

  private handleClick(cx: number, cy: number): void {
    const snap = this.nearestSnap(cx, cy)
    if (!snap) {
      this.hud('スナップ点が近くにない（端点・中心・四分円点にスナップする）')
      return
    }
    if (!this.pendingSnap) {
      this.pendingSnap = snap
      this.renderOverlay()
      this.hud(`(${snap.dxf[0]}, ${snap.dxf[1]}) を選択 — 相手をクリック`)
      return
    }
    const m: Measurement2DEntry = { id: this.nextId++, a: this.pendingSnap, b: snap }
    this.pendingSnap = null
    this.items.push(m)
    this.renderOverlay()
    this.hud(measurementText(m))
    this.emit()
  }

  /** drawing user units -> layer px; null while the viewer is not laid out (hidden) */
  private drawingToLayer(): DOMMatrix | null {
    if (!this.svg || !this.layer || this.container.clientWidth === 0) return null
    const drawing = this.svg.getScreenCTM()
    const layer = this.layer.getScreenCTM()
    return drawing && layer ? layer.inverse().multiply(drawing) : null
  }

  /**
   * Draw the measurements and a chosen first point on the layer, where their
   * snap points are on screen now: after every change of the view (pan, zoom,
   * fit, resize) and of the measurements. Each measurement is a group of its
   * two markers, its line and its value, in the order they were made.
   */
  private renderOverlay(): void {
    const g = this.overlayG
    if (!g) return
    g.replaceChildren()
    const toLayer = this.drawingToLayer()
    if (!toLayer) return // drawn when the viewer is laid out (the resize observer)
    const at = (s: SnapPoint): [number, number] => {
      const p = new DOMPoint(s.svg[0], s.svg[1]).matrixTransform(toLayer)
      return [p.x, p.y]
    }
    for (const m of this.items) {
      const a = at(m.a)
      const b = at(m.b)
      const dim = svgEl('g', { class: 'dim2d' })
      const value = svgEl('text', {
        class: 'dimtext2d',
        // from the middle of the line, on it
        x: (a[0] + b[0]) / 2,
        y: (a[1] + b[1]) / 2,
        fill: DIM_COLOUR,
        'font-size': FONT_PX,
        stroke: HALO_COLOUR,
        'stroke-width': HALO_PX,
        'stroke-linejoin': 'round',
        'paint-order': 'stroke',
      })
      value.textContent = fmt(Math.hypot(m.b.dxf[0] - m.a.dxf[0], m.b.dxf[1] - m.a.dxf[1]))
      dim.append(
        marker(a),
        marker(b),
        svgEl('line', {
          class: 'dimline2d',
          x1: a[0],
          y1: a[1],
          x2: b[0],
          y2: b[1],
          stroke: DIM_COLOUR,
          'stroke-width': LINE_PX,
        }),
        value,
      )
      g.appendChild(dim)
    }
    if (this.pendingSnap) g.appendChild(marker(at(this.pendingSnap)))
  }
}

function fmt(v: number): string {
  return v.toFixed(3)
}

function svgEl<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number>,
): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag)
  for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, String(value))
  return el
}

function marker(at: [number, number]): SVGCircleElement {
  return svgEl('circle', { class: 'marker2d', cx: at[0], cy: at[1], r: MARKER_R, fill: MARKER_COLOUR })
}

/** Rewrite a drawing's colours: in its <style> rules and in its stroke / fill / style attributes. */
function recolour(svg: SVGSVGElement, map: (css: string) => string): void {
  for (const st of Array.from(svg.querySelectorAll('style'))) {
    st.textContent = map(st.textContent ?? '')
  }
  for (const el of Array.from(svg.querySelectorAll('[stroke],[fill],[style]'))) {
    for (const attr of ['stroke', 'fill', 'style']) {
      const v = el.getAttribute(attr)
      if (v) el.setAttribute(attr, map(v))
    }
  }
}

/**
 * White page for a drawing: the page rect (a direct child of the <svg>) turns
 * white, and the drawing colours go through toWhitePage (the page colour ->
 * white, so WIPEOUT masks vanish as on screen; near-white -> black; light
 * colours darkened). Non-hex colours (`white`, `rgb()`) are not changed:
 * ezdxf writes hex. The measurements are a layer of their own: not touched.
 */
function whitenDrawing(svg: SVGSVGElement): void {
  const bg = svg.querySelector(':scope > rect')
  const page = bg?.getAttribute('fill') ?? null
  recolour(svg, (css) => toWhitePage(css, page))
  bg?.setAttribute('fill', '#ffffff')
}
