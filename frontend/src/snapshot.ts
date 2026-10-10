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
  return `${stampedName(sourceName, at)}.png`
}

/**
 * `<file name without its last extension>[_<what>]_<yyyyMMdd-HHmmss>`, local
 * time, without an extension (pngFileName's rules): the 記録's CSV and the
 * title of its page to print (the browser names the PDF after it).
 */
export function stampedName(sourceName: string, at: Date, what = ''): string {
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
  return what ? `${base}_${what}_${stamp}` : `${base}_${stamp}`
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

/** '#rgb' / '#rrggbb' (any case) -> 'rrggbb' lower case; anything else -> null */
function hex6(colour: string): string | null {
  const m = colour.trim().match(/^#([0-9a-f]{6}|[0-9a-f]{3})$/i)
  if (!m) return null
  const h = m[1].toLowerCase()
  return h.length === 3 ? [...h].map((c) => c + c).join('') : h
}

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const toSrgb = (c: number) => (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055)

/**
 * Brightest a drawing colour may be on a white page: relative luminance 0.18
 * is a 4.5:1 contrast against white ((1 + 0.05) / (0.18 + 0.05)), the WCAG
 * level for normal-size text, as drawings carry small text.
 */
export const MAX_LUMINANCE_ON_WHITE = 0.18

/**
 * A drawing's page colour made another one, in CSS text (a <style> rule or a
 * stroke / fill / style attribute): `page` (any case, #rgb too) becomes
 * `colour`, the other colours stay. The 2D viewer puts a drawing on the 3D
 * view's background this way: ezdxf fills WIPEOUT masks with its page colour
 * (#212830), and they must stay unseen on the new page too.
 */
export function swapPageColour(css: string, page: string | null, colour: string): string {
  const pageHex = page ? hex6(page) : null
  if (!pageHex) return css
  return css.replace(/#([0-9a-f]{6}|[0-9a-f]{3})\b/gi, (match) => (hex6(match) === pageHex ? colour : match))
}

/**
 * Drawing colours for a white page, in CSS text (a <style> rule or a
 * stroke / fill / style attribute):
 * - `page`, the drawing's page colour (on screen the 3D background #1d2126,
 *   see swapPageColour), becomes white: WIPEOUT masks are filled with it,
 *   unseen on screen, dark boxes on white;
 * - near-white (every channel >= 0xE0) becomes black: drawings use white for
 *   "the default colour" (ACI 7), drawn black on a white page as in CAD;
 * - other light colours (yellow, cyan, green ...: under 4.5:1 against white,
 *   about 1.07:1 for yellow) are darkened to that contrast with their hue
 *   kept, by scaling the linear RGB: #ffff00 -> #797900, #00ffff -> #008383.
 * Darker colours stay. 8-digit hex (#rrggbbaa) is left alone: \b fails inside it.
 */
export function toWhitePage(css: string, page: string | null = null): string {
  const pageHex = page ? hex6(page) : null
  return css.replace(/#([0-9a-f]{6}|[0-9a-f]{3})\b/gi, (match) => {
    const full = hex6(match)
    if (!full) return match
    if (full === pageHex) return '#ffffff'
    const ch = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
    if (Math.min(...ch) >= 0xe0) return '#000000'
    const lin = ch.map((c) => toLinear(c / 255))
    const lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    if (lum <= MAX_LUMINANCE_ON_WHITE) return match
    const k = MAX_LUMINANCE_ON_WHITE / lum
    // floor: rounding up could leave the colour just over the limit
    return '#' + lin.map((c) => Math.floor(toSrgb(c * k) * 255).toString(16).padStart(2, '0')).join('')
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

    let text = el.textContent ?? ''
    // canvas draws every space it is given; the page collapses runs of white
    // space (and drops them at the ends) unless white-space preserves them.
    // Raw text would be wider than the box and lose its end to the ellipsis.
    const collapse =
      style.getPropertyValue('white-space-collapse') ||
      (style.whiteSpace === 'normal' || style.whiteSpace === 'nowrap' ? 'collapse' : 'preserve')
    if (collapse === 'collapse') text = text.replace(/[ \t\n\r\f]+/g, ' ').trim()
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
