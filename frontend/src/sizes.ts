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

/** a length: mm, 3 decimals */
export function fmt(v: number): string {
  return v.toFixed(3)
}

/** an angle: degrees, 3 decimals, with its ° */
export function fmtDeg(v: number): string {
  return `${v.toFixed(3)}°`
}

/** what the list adds to a local radius's name */
export const LOCAL_NOTE = '（クリックした点）'

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
