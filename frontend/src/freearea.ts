/**
 * The part of the 3D view that no overlay panel covers, for 全体表示.
 *
 * Pure geometry (no DOM): main.ts measures the panels and viewer.ts frames
 * the model in the result. e2e/nav_common.py free_rect() is an independent
 * copy of the same rule; change both together.
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
 * The largest axis-aligned rectangle of a width x height canvas that no panel
 * overlaps, at least MIN_FREE of the canvas each way; null when there is none.
 * Each edge of a maximal free rectangle lies on the canvas edge or on a panel
 * edge, so trying every combination of those finds it ((n + 1)^4 candidates
 * for n panels). Equal areas: centre nearest the canvas centre, then the
 * smaller left, then the smaller top (a total order: the result does not
 * depend on the panel order).
 *
 * Why the largest rectangle and not per-side insets: every panel sits in a
 * corner, so a per-side rule would have to guess which side each one cuts.
 * The largest rectangle decides for all of them together and copes with
 * overlaps, wrapped text and a collapsed GUI. It depends only on the panels,
 * never on the model or the view direction, so F after a turn never moves
 * the model to another region of the screen.
 */
export function largestFreeRect(width: number, height: number, panels: ScreenRect[]): ScreenRect | null {
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
  let best: ScreenRect | null = null
  let bestKey: number[] = []
  for (const l of lefts) {
    for (const r of rights) {
      if (r - l < minW) continue
      for (const t of tops) {
        for (const b of bottoms) {
          if (b - t < minH) continue
          // strict: a panel that only touches an edge does not cover the rectangle
          if (clipped.some((p) => p.left < r && p.right > l && p.top < b && p.bottom > t)) continue
          // squared distance, not Math.hypot: the Python oracle gets the same doubles
          const dx = (l + r - width) / 2
          const dy = (t + b - height) / 2
          const key = [(r - l) * (b - t), -(dx * dx + dy * dy), -l, -t]
          if (!best || greater(key, bestKey)) {
            best = { left: l, top: t, right: r, bottom: b }
            bestKey = key
          }
        }
      }
    }
  }
  return best
}

/** lexicographic a > b */
function greater(a: number[], b: number[]): boolean {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] > b[i]
  }
  return false
}
