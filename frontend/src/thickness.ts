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

export type ThicknessMethod = 'ray' | 'ball' | 'face' | 'ratio'

export const METHOD_NAMES: Record<ThicknessMethod, string> = {
  ray: 'レイ法',
  ball: 'ローリングボール法',
  face: '面ごと',
  ratio: '一般部との比',
}

/** the values a method paints: 一般部との比 is 面ごと's, compared with each part's general wall */
export const methodValues = (m: ThicknessMethod): 'ray' | 'ball' | 'face' => (m === 'ratio' ? 'face' : m)

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
/**
 * 厚肉 (面ごと): at the 厚肉 limit (ratio x the general wall) and beyond, the
 * 厚肉 sphere's purple (checklist.ts KIND_COLOR thick, #9b4dca in sRGB)
 */
const THICK_PURPLE: RGB = [0.331, 0.074, 0.591]

/**
 * Write the colour of thickness v (mm) under `threshold` (mm) to out[o],
 * out[o + 1], out[o + 2]; at `thick` (mm, the 厚肉 limit) and over, purple.
 */
export function thicknessColor(v: number, threshold: number, out: Float32Array | number[], o = 0, thick: number | null = null): void {
  // `v > 0` is false for NaN too
  if (!(v > 0)) put(out, o, NO_DATA, NO_DATA, 0)
  else if (thick !== null && v >= thick) put(out, o, THICK_PURPLE, THICK_PURPLE, 0)
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
export function thicknessColors(values: ArrayLike<number>, threshold: number, out: Float32Array, thick: number | null = null): void {
  const n = Math.min(values.length, Math.floor(out.length / 3))
  for (let i = 0; i < n; i++) thicknessColor(values[i], threshold, out, i * 3, thick)
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

// ---- 一般部との比 (the thickness transitions' view, as Moldflow's Design
// Adviser shows them): each face against its part's general wall, in five bands

/** the bands' edges, % off the general wall (Moldflow's own: 20 and 50) */
export interface DeviationBands {
  small: number
  large: number
}

/** the five bands, thin to thick: the wall's thin side warm (as 薄肉), the thick side purple (as 厚肉) */
const DEVIATION: readonly RGB[] = [
  RED, // more than large % thinner
  ORANGE, // small to large % thinner
  [0.25, 0.5, 0.27], // within small %: the general wall (a green)
  [0.5, 0.33, 0.78], // small to large % thicker (a light purple)
  THICK_PURPLE, // more than large % thicker
]

/** the band (0..4) of thickness v against `nominal`; -1: no value */
export function deviationBand(v: number, nominal: number, bands: DeviationBands): number {
  if (!(v > 0) || !(nominal > 0)) return -1
  const d = (v / nominal - 1) * 100
  if (d < -bands.large) return 0
  if (d < -bands.small) return 1
  if (d <= bands.small) return 2
  if (d <= bands.large) return 3
  return 4
}

/** deviationBand's colour for every value (no value, or no general wall: データなし) */
export function deviationColors(values: ArrayLike<number>, nominal: number | null, bands: DeviationBands, out: Float32Array): void {
  const n = Math.min(values.length, Math.floor(out.length / 3))
  for (let i = 0; i < n; i++) {
    const b = nominal === null ? -1 : deviationBand(values[i], nominal, bands)
    const c = b < 0 ? NO_DATA : DEVIATION[b]
    put(out, i * 3, c, c, 0)
  }
}

/** 「2.95 mm（一般部の +48 %）」 */
export function deviationTipText(v: number | null, nominal: number | null): string {
  if (v === null) return 'データなし'
  if (!nominal) return `${v.toFixed(2)} mm`
  const d = Math.round((v / nominal - 1) * 100)
  return `${v.toFixed(2)} mm（一般部の ${d > 0 ? '+' : d < 0 ? '−' : '±'}${Math.abs(d)} %）`
}

/** the legend of 一般部との比: its five bands, the general wall (`wall`: 「部品ごと」 or a length) */
export function renderDeviationLegend(el: HTMLElement, bands: DeviationBands, wall: string): void {
  const title = document.createElement('div')
  title.className = 'thick-title'
  title.textContent = `肉厚（一般部との比、面ごと。一般部 ${wall}）`
  const { small: s, large: l } = bands
  const labels = [`−${l} % より薄い`, `−${l}〜−${s} %`, `±${s} %（一般部）`, `+${s}〜+${l} %`, `+${l} % より厚い`]
  const rows: HTMLElement[] = [title]
  labels.forEach((text, i) => {
    const row = document.createElement('div')
    row.className = 'draft-row deviation-band'
    row.dataset.band = String(i)
    const sw = document.createElement('span')
    sw.className = 'draft-swatch'
    sw.style.background = css(DEVIATION[i])
    const label = document.createElement('span')
    label.textContent = text
    row.append(sw, label)
    rows.push(row)
  })
  const none = document.createElement('div')
  none.className = 'draft-row'
  const sw = document.createElement('span')
  sw.className = 'draft-swatch'
  sw.style.background = css(NO_DATA)
  const label = document.createElement('span')
  label.textContent = 'データなし（測れない小さな面・判定できない部品）'
  none.append(sw, label)
  rows.push(none)
  el.replaceChildren(...rows)
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
/**
 * the legend; with 面ごと, `thick` says the 厚肉 band (its ratio and the
 * general wall it is of: 「部品ごと」 or a length)
 */
export function renderThicknessLegend(
  el: HTMLElement,
  threshold: number,
  method: ThicknessMethod,
  thick: { ratio: number; wall: string } | null = null,
): void {
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
  label.textContent =
    method === 'face'
      ? 'データなし（測れない小さな面・判定できない部品）'
      : method === 'ball'
        ? // the vertices no tangent sphere fits at (#63): most of a STEP / IGES model's
          // flat faces and convex curved ones. The face's own value is 面ごと's
          'データなし（球の入らない頂点: 角・出っ張った稜線と曲面、平らな面の縁。平らな面の中は「面ごと（形の中から）」で見る）'
        : 'データなし（光線が抜けた点・角）'
  none.append(swatch, label)
  const rows: HTMLElement[] = [title, bar, ticks]
  if (thick) {
    const t = document.createElement('div')
    t.className = 'draft-row thick-band'
    const sw = document.createElement('span')
    sw.className = 'draft-swatch'
    sw.style.background = css(THICK_PURPLE)
    const tl = document.createElement('span')
    tl.textContent = `厚肉: 一般部（${thick.wall}）の ${String(Number(thick.ratio.toFixed(2)))} 倍以上`
    t.append(sw, tl)
    rows.push(t)
  }
  rows.push(none)
  el.replaceChildren(...rows)
}
