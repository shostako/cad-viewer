/** 2D drawing viewer: pan/zoom via viewBox mutation + snap measurement.
 *
 * The backend SVG is injected as-is; we manipulate its viewBox for pan/zoom
 * (keeps getScreenCTM() exact) and append our own <g> for markers/dimensions
 * in the same coordinate space. Snap points carry both svg coords (display)
 * and dxf coords (exact measurement values).
 */

import { flipNearWhite, type ExportBackground } from './snapshot'

export interface SnapPoint {
  dxf: [number, number]
  svg: [number, number]
  kind: string
}

const SNAP_PX = 12
const SVG_NS = 'http://www.w3.org/2000/svg'

export class Drawing2D {
  private container: HTMLElement
  private hud: (msg: string) => void
  private svg: SVGSVGElement | null = null
  private overlayG: SVGGElement | null = null
  private snaps: SnapPoint[] = []
  private vb = { x: 0, y: 0, w: 1, h: 1 }
  private baseVb = { x: 0, y: 0, w: 1, h: 1 }
  private pendingSnap: SnapPoint | null = null
  measureMode = false

  constructor(container: HTMLElement, hud: (msg: string) => void) {
    this.container = container
    this.hud = hud
    this.bindEvents()
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

    this.overlayG = document.createElementNS(SVG_NS, 'g')
    // named so a white export can leave the measurement colours alone
    this.overlayG.setAttribute('class', 'overlay2d')
    this.svg.appendChild(this.overlayG)
    this.snaps = snaps
    this.pendingSnap = null
  }

  /** drop the drawing (the next load starts from an empty viewer) */
  clear(): void {
    this.container.replaceChildren()
    this.svg = null
    this.overlayG = null
    this.snaps = []
    this.pendingSnap = null
  }

  clearMeasurements(): void {
    if (this.overlayG) this.overlayG.innerHTML = ''
    this.pendingSnap = null
  }

  private applyViewBox(): void {
    this.svg?.setAttribute('viewBox', `${this.vb.x} ${this.vb.y} ${this.vb.w} ${this.vb.h}`)
    this.updateOverlayScale()
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
   * The drawing as on screen (current viewBox = current pan and zoom, with the
   * measurement overlay) rasterised at device-pixel resolution. 'white' gives
   * a white page with near-white lines turned black.
   */
  async snapshot(background: ExportBackground): Promise<HTMLCanvasElement> {
    const svg = this.svg
    if (!svg) throw new Error('図面が開かれていない')
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
    // a non-scaling stroke is measured in image pixels, which are device pixels here
    for (const el of Array.from(clone.querySelectorAll('[vector-effect="non-scaling-stroke"]'))) {
      el.setAttribute('stroke-width', String((Number(el.getAttribute('stroke-width')) || 1) * k))
    }
    if (background === 'white') whitenDrawing(clone)

    const url = URL.createObjectURL(
      new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }),
    )
    try {
      const img = new Image()
      img.src = url
      await img.decode()
      const out = document.createElement('canvas')
      out.width = w
      out.height = h
      const ctx = out.getContext('2d')
      if (!ctx) throw new Error('画像を作れない')
      // the page around the drawing: the container colour on screen
      ctx.fillStyle = background === 'white' ? '#ffffff' : getComputedStyle(this.container).backgroundColor
      ctx.fillRect(0, 0, w, h)
      ctx.drawImage(img, 0, 0, w, h)
      return out
    } finally {
      URL.revokeObjectURL(url)
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
      this.addMarker(snap)
      this.hud(`(${snap.dxf[0]}, ${snap.dxf[1]}) を選択 — 相手をクリック`)
      return
    }
    const a = this.pendingSnap
    this.pendingSnap = null
    this.addMarker(snap)
    const dx = snap.dxf[0] - a.dxf[0]
    const dy = snap.dxf[1] - a.dxf[1]
    const dist = Math.hypot(dx, dy)
    this.addDimension(a, snap, dist)
    this.hud(`距離 ${dist.toFixed(3)} (ΔX ${Math.abs(dx).toFixed(3)}, ΔY ${Math.abs(dy).toFixed(3)})`)
  }

  private addMarker(s: SnapPoint): SVGCircleElement {
    const c = document.createElementNS(SVG_NS, 'circle')
    c.setAttribute('cx', String(s.svg[0]))
    c.setAttribute('cy', String(s.svg[1]))
    c.setAttribute('fill', '#ffb020')
    c.classList.add('marker2d')
    this.overlayG?.appendChild(c)
    this.updateOverlayScale()
    return c
  }

  private addDimension(a: SnapPoint, b: SnapPoint, dist: number): void {
    const line = document.createElementNS(SVG_NS, 'line')
    line.setAttribute('x1', String(a.svg[0]))
    line.setAttribute('y1', String(a.svg[1]))
    line.setAttribute('x2', String(b.svg[0]))
    line.setAttribute('y2', String(b.svg[1]))
    line.setAttribute('stroke', '#ffd060')
    line.setAttribute('vector-effect', 'non-scaling-stroke')
    line.setAttribute('stroke-width', '1.5')
    this.overlayG?.appendChild(line)

    const text = document.createElementNS(SVG_NS, 'text')
    text.textContent = dist.toFixed(3)
    text.setAttribute('x', String((a.svg[0] + b.svg[0]) / 2))
    text.setAttribute('y', String((a.svg[1] + b.svg[1]) / 2))
    text.setAttribute('fill', '#ffd060')
    text.setAttribute('paint-order', 'stroke')
    text.setAttribute('stroke', '#1d2126')
    text.setAttribute('stroke-width', '3')
    text.classList.add('dimtext2d')
    this.overlayG?.appendChild(text)
    this.updateOverlayScale()
  }

  /** keep markers/text screen-constant across zoom levels */
  private updateOverlayScale(): void {
    if (!this.overlayG) return
    const u = this.unitsPerPx()
    for (const c of Array.from(this.overlayG.querySelectorAll('circle.marker2d'))) {
      c.setAttribute('r', String(5 * u))
    }
    for (const t of Array.from(this.overlayG.querySelectorAll('text.dimtext2d'))) {
      t.setAttribute('font-size', String(13 * u))
    }
  }
}

/**
 * White page for a drawing: the ezdxf background rect (a direct child of the
 * <svg>) turns white, and near-white drawing colours (ACI 7, drawn white on
 * the dark page) turn black, in <style> rules and in stroke / fill / style
 * attributes. The measurement overlay keeps its colours. Non-hex colours
 * (`white`, `rgb()`) are not changed: ezdxf writes hex.
 */
function whitenDrawing(svg: SVGSVGElement): void {
  const overlay = svg.querySelector('g.overlay2d')
  for (const st of Array.from(svg.querySelectorAll('style'))) {
    st.textContent = flipNearWhite(st.textContent ?? '')
  }
  for (const el of Array.from(svg.querySelectorAll('[stroke],[fill],[style]'))) {
    if (overlay?.contains(el)) continue
    for (const attr of ['stroke', 'fill', 'style']) {
      const v = el.getAttribute(attr)
      if (v) el.setAttribute(attr, flipNearWhite(v))
    }
  }
  svg.querySelector(':scope > rect')?.setAttribute('fill', '#ffffff')
}
