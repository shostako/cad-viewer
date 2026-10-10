/**
 * Thickness heatmap (肉厚): the colour of a wall thickness, the legend, and
 * the value under the cursor.
 *
 * The heatmap is for finding walls thinner than the threshold, so the colours
 * break there: below it they are hot (deep red up to half the threshold, then
 * red to orange), at or above it cool (a grey-blue that grades into the blue
 * of a thick wall at twice the threshold and beyond). Nothing below the
 * threshold shares a hue with anything above it.
 *
 * The values come per display vertex (thickness.bin: one per vertex of a
 * part's display mesh). 0 or less (and NaN) means no value: a ray that left
 * the solid, or a sharp corner where no rolling ball fits (backend
 * thickness.py).
 */
import * as THREE from 'three'
import { fmtThin } from './materials'

export type ThicknessMethod = 'ray' | 'ball'

export const METHOD_NAMES: Record<ThicknessMethod, string> = {
  ray: 'レイ法',
  ball: 'ローリングボール法',
}

type RGB = readonly [number, number, number]

// Linear RGB, three's working space: the mesh takes these as vertex colours
// and lighting shades them; the legend shows them unshaded (in sRGB).
/** at 0 */
const DEEP_RED: RGB = [0.5, 0.0, 0.0]
/** at half the threshold */
const RED: RGB = [0.85, 0.03, 0.02]
/** just under the threshold */
const ORANGE: RGB = [1.0, 0.27, 0.0]
/**
 * at the threshold: the cool side starts as a pale grey-blue (a little toward
 * lavender, apart from NO_DATA) and grades into the thick end. Paler than the
 * default part colour too, so a wall just over the threshold never passes for
 * an uncoloured part.
 */
const GREY_BLUE: RGB = [0.66, 0.64, 0.9]
/** twice the threshold and beyond (the colour the heatmap has always had there) */
const THICK_BLUE: RGB = [0.35, 0.55, 0.8]
/** a vertex without a value */
const NO_DATA: RGB = [0.55, 0.62, 0.75]

/** Write the colour of thickness v (mm) under `threshold` (mm) to out[o], out[o + 1], out[o + 2]. */
export function thicknessColor(v: number, threshold: number, out: Float32Array | number[], o = 0): void {
  // `v > 0` is false for NaN too
  if (!(v > 0)) put(out, o, NO_DATA, NO_DATA, 0)
  else rampColor(threshold > 0 ? v / threshold : Infinity, out, o)
}

/** the colour of a thickness that is f times the threshold (f >= 0) */
function rampColor(f: number, out: Float32Array | number[], o = 0): void {
  if (f < 0.5) put(out, o, DEEP_RED, RED, f / 0.5)
  else if (f < 1) put(out, o, RED, ORANGE, (f - 0.5) / 0.5)
  else if (f < 2) put(out, o, GREY_BLUE, THICK_BLUE, f - 1)
  else put(out, o, THICK_BLUE, THICK_BLUE, 0)
}

function put(out: Float32Array | number[], o: number, a: RGB, b: RGB, k: number): void {
  out[o] = a[0] + (b[0] - a[0]) * k
  out[o + 1] = a[1] + (b[1] - a[1]) * k
  out[o + 2] = a[2] + (b[2] - a[2]) * k
}

/** thicknessColor for every value: `out` holds 3 floats per value */
export function thicknessColors(values: ArrayLike<number>, threshold: number, out: Float32Array): void {
  const n = Math.min(values.length, Math.floor(out.length / 3))
  for (let i = 0; i < n; i++) thicknessColor(values[i], threshold, out, i * 3)
}

/**
 * Thickness at a point of a triangle: its three vertex values blended with
 * the point's barycentric weights, as the GPU blends the vertex colours.
 * Vertices without a value are left out and the others' weights scaled up to
 * a sum of 1; null when none of the three has a value.
 */
export function thicknessAt(
  values: ArrayLike<number>,
  vertices: readonly [number, number, number],
  weights: readonly [number, number, number],
): number | null {
  let sum = 0
  let wsum = 0
  for (let k = 0; k < 3; k++) {
    const v = values[vertices[k]]
    if (!(v > 0)) continue // no value (also out of range: undefined)
    sum += weights[k] * v
    wsum += weights[k]
  }
  return wsum > 0 ? sum / wsum : null
}

/** the text of the value under the cursor: 「1.20 mm」, or that there is none */
export function thicknessTipText(v: number | null): string {
  return v === null ? 'データなし' : `${v.toFixed(2)} mm`
}

/** a length on the legend: the threshold moves in 0.01 mm steps (1.5, 0.64; twice them 3.0, 1.28) */
const mm = fmtThin

/** CSS colour (sRGB hex) of a linear colour, as the screen shows it unshaded */
function css(c: ArrayLike<number>): string {
  return '#' + new THREE.Color().setRGB(c[0], c[1], c[2], THREE.LinearSRGBColorSpace).getHexString()
}

/**
 * The legend's colour bar, 0 to twice the threshold, left to right. The
 * colours depend on the thickness as a share of the threshold only, so the
 * bar is the same for every threshold (the ticks carry the numbers). Sampled
 * finely enough that the browser's sRGB blend between stops matches the
 * mesh's linear one; two stops at 50 % draw the break at the threshold.
 */
function barGradient(): string {
  const STEPS = 10 // per half
  const c = [0, 0, 0]
  const stops: string[] = []
  for (let i = 0; i <= 2 * STEPS; i++) {
    const f = i / STEPS // thickness / threshold
    const pos = `${(f / 2) * 100}%`
    if (i === STEPS) {
      rampColor(1 - 1e-9, c) // the orange end of the thin side
      stops.push(`${css(c)} ${pos}`)
    }
    rampColor(f, c)
    stops.push(`${css(c)} ${pos}`)
  }
  return `linear-gradient(to right, ${stops.join(', ')})`
}

/**
 * Legend: the method and the threshold, the colour bar with mm ticks at 0, the
 * threshold and twice the threshold, and the colour of a point without a value.
 */
export function renderThicknessLegend(el: HTMLElement, threshold: number, method: ThicknessMethod): void {
  const title = document.createElement('div')
  title.className = 'thick-title'
  title.textContent = `肉厚（${METHOD_NAMES[method]}、閾値 ${mm(threshold)} mm 未満が赤・橙）`
  const bar = document.createElement('div')
  bar.className = 'thick-bar'
  bar.style.background = barGradient()
  const ticks = document.createElement('div')
  ticks.className = 'thick-ticks'
  const labels: [string, string][] = [
    ['0', '0%'],
    [mm(threshold), '50%'],
    [`${mm(2 * threshold)} mm`, '100%'],
  ]
  for (const [text, at] of labels) {
    const tick = document.createElement('span')
    tick.className = 'thick-tick'
    tick.dataset.at = at
    tick.style.left = at
    tick.textContent = text
    ticks.appendChild(tick)
  }
  const none = document.createElement('div')
  none.className = 'draft-row'
  const swatch = document.createElement('span')
  swatch.className = 'draft-swatch'
  swatch.style.background = css(NO_DATA)
  const label = document.createElement('span')
  label.textContent = 'データなし（光線が抜けた点・角）'
  none.append(swatch, label)
  el.replaceChildren(title, bar, ticks, none)
}
