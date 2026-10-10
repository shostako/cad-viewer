/**
 * The size a face or an edge has by its kind, as the backend measured it on
 * the B-rep (measure.py's face_info / edge_info), and how the list, the
 * labels and the hover say it:
 *
 * - ⌀: a whole circle or cylinder (a hole, a boss)
 * - R: a part of one (a fillet, a rounded corner), a torus's small radius (a
 *   fillet round a circle), or the radius of curvature at the clicked point
 *   (a B-spline face or edge that is none of these: "local")
 * - SR: a sphere
 * - 勾配: a cone's half angle (the draft of a drafted boss)
 */
import type { EdgeInfoResult, FaceInfoResult } from './api'

export type SizeMark = '⌀' | 'R' | 'SR' | '勾配'

export interface Size {
  mark: SizeMark
  /** mm, or degrees for 勾配 */
  value: number
  /** the kind as the list names it: 円エッジ, 円弧, 円筒面, ... */
  name: string
  /** the radius of curvature at the clicked point, not one of the whole face or edge */
  local: boolean
  /** a whole circle's centre: its label goes there */
  centre?: [number, number, number]
  /** the true surface's or curve's point at the click (a local radius) */
  at?: [number, number, number]
}

/** a length: mm, 3 decimals (the saved text of an entry; the screen shows showLen) */
export function fmt(v: number): string {
  return v.toFixed(3)
}

// ---- how measured numbers are shown (#59 P1 6)
// The operation panel's 単位 and 桁: they change the screen only. The saved
// entries (sidecars) keep their mm text and their numbers, the 記録 its mm.

export type LengthUnit = 'mm' | 'in'
export const LENGTH_UNITS: readonly LengthUnit[] = ['mm', 'in']
export const MM_PER_INCH = 25.4
/** the decimals one can choose */
export const DIGITS_MIN = 0
export const DIGITS_MAX = 6
export const DIGITS_DEFAULT = 3

/** the unit and the decimals measured numbers are shown in now */
export const shown = { unit: 'mm' as LengthUnit, digits: DIGITS_DEFAULT }

export function setShown(unit: LengthUnit, digits: number): void {
  shown.unit = LENGTH_UNITS.includes(unit) ? unit : 'mm'
  shown.digits = Number.isInteger(digits) ? Math.min(DIGITS_MAX, Math.max(DIGITS_MIN, digits)) : DIGITS_DEFAULT
}

/** v with d decimals; one that rounds to 0 has no sign */
function fixed(v: number, d: number): string {
  const t = v.toFixed(d)
  return /^-0\.?0*$/.test(t) ? t.slice(1) : t
}

/** a length (mm) as shown: the number in the unit shown, its decimals */
export function showLen(mm: number): string {
  return fixed(shown.unit === 'in' ? mm / MM_PER_INCH : mm, shown.digits)
}

/** an area (mm²) as shown */
export function showArea(mm2: number): string {
  return fixed(shown.unit === 'in' ? mm2 / (MM_PER_INCH * MM_PER_INCH) : mm2, shown.digits)
}

/** an angle (degrees) as shown, the number alone: the decimals of the lengths */
export function showDegNum(deg: number): string {
  return fixed(deg, shown.digits)
}

/** an angle as shown, with its ° */
export function showDeg(deg: number): string {
  return `${showDegNum(deg)}°`
}

/** what a length on the status line and beside the cursor adds when it is not in mm (those say no unit for mm) */
export const unitTag = (): string => (shown.unit === 'mm' ? '' : ` ${shown.unit}`)

/** the unit of a length as shown (mm, in) */
export const lenUnit = (): string => shown.unit

/** the unit of an area as shown (mm², in²) */
export const areaUnit = (): string => `${shown.unit}²`

/** a point as shown: (12.000, 20.000, 10.000) */
export function showPoint(p: readonly [number, number, number]): string {
  return `(${p.map(showLen).join(', ')})`
}

/** a size as shown: ⌀8.000, R5.000, SR4.000, 勾配 2.000° (the beside-the-cursor tip) */
export function showSize(s: Size): string {
  return s.mark === '勾配' ? `勾配 ${showDeg(s.value)}` : `${s.mark}${showLen(s.value)}`
}

const formatters = new Map<number, Intl.NumberFormat>()
/** ja-JP grouping, fixed number of decimals (the 体積・重量 panel's numbers, the 記録's page) */
export function fmtNum(x: number, digits: number): string {
  let f = formatters.get(digits)
  if (!f) {
    f = new Intl.NumberFormat('ja-JP', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    formatters.set(digits, f)
  }
  return f.format(x)
}

/** the unit of a measured area (lengths are LENGTH_UNIT, mm) */
export const AREA_UNIT = 'mm²'

/** an angle: degrees, 3 decimals, with its ° */
export function fmtDeg(v: number): string {
  return `${v.toFixed(3)}°`
}

/** what the list adds to a local radius's name */
export const LOCAL_NOTE = '（クリックした点）'

/** a point as text: (12.000, 20.000, 10.000) */
export function pointText(p: readonly [number, number, number]): string {
  return `(${p.map(fmt).join(', ')})`
}

/** the size as text: ⌀8.000, R5.000, SR4.000, 勾配 2.000° */
export function sizeText(s: Size): string {
  return s.mark === '勾配' ? `勾配 ${fmtDeg(s.value)}` : `${s.mark}${fmt(s.value)}`
}

// a backend before the "full" flag reported every circle as a whole one: so do they here
export function edgeSize(i: EdgeInfoResult): Size | null {
  if (i.curve === 'circle' && i.radius !== undefined) {
    return i.full === false
      ? { mark: 'R', value: i.radius, name: '円弧', local: false }
      : { mark: '⌀', value: i.diameter ?? 2 * i.radius, name: '円エッジ', local: false, centre: i.center }
  }
  if (i.localRadius !== undefined) return { mark: 'R', value: i.localRadius, name: 'エッジ', local: true, at: i.at }
  return null
}

export function faceSize(i: FaceInfoResult): Size | null {
  if (i.surface === 'cylinder' && i.radius !== undefined) {
    return i.full === false
      ? { mark: 'R', value: i.radius, name: '円筒面', local: false }
      : { mark: '⌀', value: i.diameter ?? 2 * i.radius, name: '円筒面', local: false }
  }
  if (i.surface === 'torus' && i.radius !== undefined) return { mark: 'R', value: i.radius, name: 'トーラス面', local: false }
  if (i.surface === 'sphere' && i.radius !== undefined) return { mark: 'SR', value: i.radius, name: '球面', local: false }
  if (i.surface === 'cone' && i.angle !== undefined) return { mark: '勾配', value: i.angle, name: '円錐面', local: false }
  if (i.localRadius !== undefined) return { mark: 'R', value: i.localRadius, name: '曲面', local: true, at: i.at }
  return null
}
