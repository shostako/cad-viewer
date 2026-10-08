/** Save the current view as a PNG: file name, download, and painting the HTML labels.
 *
 * Pure DOM helpers (no three.js): the 3D and 2D viewers build the canvas, this
 * module turns it into a file. Labels (CSS2DRenderer elements) are HTML on top
 * of the WebGL canvas, so they are not in its pixels: paintLabels redraws them
 * into the export from their computed style and on-screen position.
 */

/** 'screen': the background as on screen; 'white': a white page for documents */
export type ExportBackground = 'screen' | 'white'

const FALLBACK_BASE = 'cad-viewer'

/**
 * `<file name without its last extension>_<yyyyMMdd-HHmmss>.png`, local time.
 * Only the last extension goes (`a.b.step` -> `a.b`); characters Windows does
 * not allow in a file name become `_`.
 */
export function pngFileName(sourceName: string, at: Date): string {
  const dot = sourceName.lastIndexOf('.')
  let base = dot >= 0 ? sourceName.slice(0, dot) : sourceName
  base = base.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, '_')
  // Windows drops trailing dots and spaces itself, and `.step` leaves nothing
  base = base.replace(/[. ]+$/, '')
  if (!base) base = FALLBACK_BASE
  const p = (n: number) => String(n).padStart(2, '0')
  const stamp =
    `${at.getFullYear()}${p(at.getMonth() + 1)}${p(at.getDate())}` +
    `-${p(at.getHours())}${p(at.getMinutes())}${p(at.getSeconds())}`
  return `${base}_${stamp}.png`
}

/** Hand a blob to the browser as a download (no dialog; the browser picks the folder). */
export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // revoking at once can cancel the download in some browsers; a late revoke only frees memory
  setTimeout(() => URL.revokeObjectURL(url), 30000)
}

/** canvas -> PNG blob. toBlob gives null when the canvas is too large or memory runs out. */
export function canvasToPng(c: HTMLCanvasElement): Promise<Blob> {
  return new Promise((ok, ng) =>
    c.toBlob((b) => (b ? ok(b) : ng(new Error('PNG を作れない（画像が大きすぎる）'))), 'image/png'),
  )
}

/**
 * Turn near-white hex colours (every channel >= 0xE0) into black: drawings
 * use white for "the default colour" (ACI 7), which vanishes on a white page.
 * The minimum channel, not the luminance, decides, so the yellow #ffd060 stays.
 * 8-digit hex (#rrggbbaa) is left alone: \b fails inside it.
 */
export function flipNearWhite(css: string): string {
  return css.replace(/#([0-9a-f]{6}|[0-9a-f]{3})\b/gi, (match, hex: string) => {
    const full = hex.length === 3 ? [...hex].map((c) => c + c).join('') : hex
    const ch = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
    return Math.min(...ch) >= 0xe0 ? '#000000' : match
  })
}

/** alpha of a computed CSS colour ('rgb(...)', 'rgba(...)', 'transparent') */
function cssAlpha(color: string): number {
  if (color === 'transparent') return 0
  const m = color.match(/rgba?\(([^)]*)\)/)
  if (!m) return 1
  const parts = m[1].split(/[\s,/]+/).filter(Boolean)
  if (parts.length < 4) return 1
  const a = parts[3]
  return a.endsWith('%') ? parseFloat(a) / 100 : parseFloat(a)
}

function px(v: string): number {
  return parseFloat(v) || 0
}

/**
 * Paint the visible labels of a CSS2DRenderer layer into `ctx`, where the
 * canvas covers `origin` (client rect) at sx x sy canvas pixels per CSS px.
 *
 * Reproduced: position (from getBoundingClientRect, so the renderer's
 * transform is included), background, uniform border, corner radius, opacity,
 * font, colour, padding and text-overflow: ellipsis. Paint order follows the
 * z-index CSS2DRenderer sets (renderOrder, then distance). Elements marked
 * data-no-export (the fading rotation-centre ring) are skipped.
 *
 * Known gaps: canvas has no font-variant-numeric, so tabular digits can sit
 * ~1 px off (the clip keeps them in the box); with opacity < 1 the background
 * and the text blend separately (every current label is opaque).
 */
export function paintLabels(
  ctx: CanvasRenderingContext2D,
  layer: HTMLElement,
  origin: DOMRect,
  sx: number,
  sy: number,
): void {
  const items: { el: HTMLElement; style: CSSStyleDeclaration; rect: DOMRect; z: number; i: number }[] = []
  Array.from(layer.children).forEach((el, i) => {
    if (!(el instanceof HTMLElement) || el.hasAttribute('data-no-export')) return
    const style = getComputedStyle(el)
    if (style.display === 'none' || style.visibility === 'hidden' || !(Number(style.opacity) > 0)) return
    const rect = el.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return
    items.push({ el, style, rect, z: Number(style.zIndex) || 0, i })
  })
  // stable on DOM order for equal z, as the browser stacks them
  items.sort((a, b) => a.z - b.z || a.i - b.i)
  const range = document.createRange()
  for (const { el, style, rect } of items) {
    ctx.save()
    ctx.setTransform(sx, 0, 0, sy, -origin.left * sx, -origin.top * sy)
    ctx.globalAlpha = Number(style.opacity)
    const { left, top, width: w, height: h } = rect
    const rRaw = style.borderTopLeftRadius
    const rCss = rRaw.endsWith('%') ? (parseFloat(rRaw) / 100) * Math.min(w, h) : px(rRaw)
    const rad = Math.max(0, Math.min(rCss, w / 2, h / 2))

    if (cssAlpha(style.backgroundColor) > 0) {
      ctx.beginPath()
      ctx.roundRect(left, top, w, h, rad)
      ctx.fillStyle = style.backgroundColor
      ctx.fill()
    }
    // borders are assumed uniform (all current labels are); the top one stands for all
    const bw = px(style.borderTopWidth)
    if (bw > 0 && style.borderTopStyle !== 'none' && cssAlpha(style.borderTopColor) > 0) {
      ctx.beginPath()
      ctx.roundRect(left + bw / 2, top + bw / 2, w - bw, h - bw, Math.max(0, rad - bw / 2))
      ctx.lineWidth = bw
      ctx.strokeStyle = style.borderTopColor
      ctx.stroke()
    }

    const text = el.textContent ?? ''
    if (text) {
      const bl = px(style.borderLeftWidth)
      const br = px(style.borderRightWidth)
      const bt = px(style.borderTopWidth)
      const bb = px(style.borderBottomWidth)
      // clip to the padding box, as overflow: hidden does on screen
      ctx.beginPath()
      ctx.rect(left + bl, top + bt, w - bl - br, h - bt - bb)
      ctx.clip()
      ctx.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
      ctx.fillStyle = style.color
      ctx.textBaseline = 'alphabetic'
      ctx.textAlign = 'left'
      const contentLeft = left + bl + px(style.paddingLeft)
      const contentTop = top + bt + px(style.paddingTop)
      const contentW = w - bl - br - px(style.paddingLeft) - px(style.paddingRight)
      const contentH = h - bt - bb - px(style.paddingTop) - px(style.paddingBottom)
      const metrics = ctx.measureText(text)
      const asc = metrics.fontBoundingBoxAscent
      const desc = metrics.fontBoundingBoxDescent
      // where the browser actually laid the text out: the line box top plus the
      // font ascent is the baseline, the same font metrics the page used
      range.selectNodeContents(el)
      const tr = range.getBoundingClientRect()
      let x = contentLeft
      let y = contentTop + (contentH + asc - desc) / 2
      if (tr.width > 0 || tr.height > 0) {
        x = tr.left
        y = tr.top + asc
      }
      let shown = text
      if (style.textOverflow === 'ellipsis' && metrics.width > contentW + 0.5) {
        // longest code-point prefix that still fits with the ellipsis
        const cps = [...text]
        let lo = 0
        let hi = cps.length
        while (lo < hi) {
          const mid = Math.ceil((lo + hi) / 2)
          if (ctx.measureText(cps.slice(0, mid).join('') + '…').width <= contentW) lo = mid
          else hi = mid - 1
        }
        shown = cps.slice(0, lo).join('') + '…'
      }
      ctx.fillText(shown, x, y)
    }
    ctx.restore()
  }
}
