/**
 * The part of the 3D view that no overlay panel covers, for 全体表示.
 *
 * Pure geometry (no DOM): main.ts measures the panels, viewer.ts measures the
 * model as seen from the fit's direction and frames it in the result.
 * e2e/nav_common.py free_rect() is an independent copy of the same rule;
 * change both together.
 */

/** A rectangle in CSS px, origin top left. */
export interface ScreenRect {
  left: number
  top: number
  right: number
  bottom: number
}

/** Share of the canvas width and height the free area must keep; below it a fit uses the whole canvas. */
export const MIN_FREE = 0.4

/**
 * How much larger another free rectangle must show the model than the largest
 * one does, for a fit to use it instead (see fitRect).
 */
export const SWITCH_GAIN = 1.1

/**
 * Every axis-aligned rectangle of a width x height canvas that no panel
 * overlaps and that keeps at least MIN_FREE of the canvas each way, with each
 * edge on the canvas edge or on a panel edge ((n + 1)^4 tries for n panels).
 * Each maximal free rectangle is among them; so are some smaller ones, which
 * never win in fitRect (a rectangle around one shows the model as large, and
 * is larger).
 */
export function freeRects(width: number, height: number, panels: ScreenRect[]): ScreenRect[] {
  const clipped: ScreenRect[] = []
  for (const p of panels) {
    const r = {
      left: Math.max(p.left, 0),
      top: Math.max(p.top, 0),
      right: Math.min(p.right, width),
      bottom: Math.min(p.bottom, height),
    }
    if (r.right > r.left && r.bottom > r.top) clipped.push(r)
  }
  const lefts = [0, ...clipped.map((p) => p.right)]
  const rights = [width, ...clipped.map((p) => p.left)]
  const tops = [0, ...clipped.map((p) => p.bottom)]
  const bottoms = [height, ...clipped.map((p) => p.top)]
  const minW = MIN_FREE * width
  const minH = MIN_FREE * height
  const out: ScreenRect[] = []
  for (const l of lefts) {
    for (const r of rights) {
      if (r - l < minW) continue
      for (const t of tops) {
        for (const b of bottoms) {
          if (b - t < minH) continue
          // strict: a panel that only touches an edge does not cover the rectangle
          if (clipped.some((p) => p.left < r && p.right > l && p.top < b && p.bottom > t)) continue
          out.push({ left: l, top: t, right: r, bottom: b })
        }
      }
    }
  }
  return out
}

/**
 * The area a fit frames the model in: of the free rectangles (freeRects), the
 * largest one, unless another shows the model at least SWITCH_GAIN times as
 * large; then the one that shows it largest. null when there is no free
 * rectangle (the fit uses the whole canvas).
 *
 * modelW x modelH: the model's bounding box as seen from the fit's direction
 * (its extent along the screen's right and up; any unit, only the ratio
 * counts). A fit fills a share of the area's limiting side, so a rectangle
 * shows the model at min(width / modelW, height / modelH).
 *
 * Ties: the largest rectangle is the one with the largest area, then the
 * centre nearest the canvas centre, then the smaller left, then the smaller
 * top; the one that shows the model largest breaks ties by the same keys
 * after its size. Both are total orders: the result does not depend on the
 * panel order.
 *
 * Why not always the largest rectangle (the rule before): a long product
 * beside narrower panels would get a squat rectangle and look small. Why not
 * always the one that shows the model largest: a gain of a few pixels would
 * move the model to another region of the screen, and F after a small turn
 * could jump it back and forth. Every panel sits in a corner, so whole
 * rectangles (not per-side insets) also cope with overlaps, wrapped text and
 * a collapsed GUI.
 */
export function fitRect(
  width: number,
  height: number,
  panels: ScreenRect[],
  modelW: number,
  modelH: number,
): ScreenRect | null {
  const rects = freeRects(width, height, panels)
  if (rects.length === 0) return null
  // squared distance, not Math.hypot: the Python oracle gets the same doubles
  const place = (r: ScreenRect) => {
    const dx = (r.left + r.right - width) / 2
    const dy = (r.top + r.bottom - height) / 2
    return [(r.right - r.left) * (r.bottom - r.top), -(dx * dx + dy * dy), -r.left, -r.top]
  }
  // a zero extent does not limit (a flat part seen edge-on)
  const shows = (r: ScreenRect) =>
    Math.min(modelW > 0 ? (r.right - r.left) / modelW : Infinity, modelH > 0 ? (r.bottom - r.top) / modelH : Infinity)
  const largest = best(rects, place)
  const biggest = best(rects, (r) => [shows(r), ...place(r)])
  return shows(biggest) >= SWITCH_GAIN * shows(largest) ? biggest : largest
}

/** the rectangle with the lexicographically greatest key */
function best(rects: ScreenRect[], key: (r: ScreenRect) => number[]): ScreenRect {
  let out = rects[0]
  let outKey = key(out)
  for (const r of rects.slice(1)) {
    const k = key(r)
    if (greater(k, outKey)) {
      out = r
      outKey = k
    }
  }
  return out
}

/** lexicographic a > b */
function greater(a: number[], b: number[]): boolean {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] > b[i]
  }
  return false
}
