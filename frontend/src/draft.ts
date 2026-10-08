/**
 * Draft-angle analysis (抜き勾配): classify each display vertex by how far its
 * face leans toward the mold-opening (pull) direction.
 *
 * The angle between a face and the pull direction d is the draft angle
 * α = asin(n·d) for the face normal n: 90° for a face looking straight along d,
 * 0° for a wall parallel to d, negative for faces looking away. asin is
 * monotonic, so the classes compare sines and never call it.
 *
 * Works on the display mesh: planar B-rep faces have their own vertices (normal
 * = face normal, crisp colours), curved B-rep faces are approximated per
 * vertex, mesh formats are classified per triangle (Viewer.flatCopy).
 * Orientation alone cannot see undercuts (faces hidden behind other geometry
 * along d), nor which side of the parting line a face is on.
 */
import * as THREE from 'three'

export type PullDir = '+Z' | '-Z' | '+X' | '-X' | '+Y' | '-Y'

/** unit pull directions in model (= world) coordinates */
export const PULL_DIRS: Record<PullDir, readonly [number, number, number]> = {
  '+Z': [0, 0, 1],
  '-Z': [0, 0, -1],
  '+X': [1, 0, 0],
  '-X': [-1, 0, 0],
  '+Y': [0, 1, 0],
  '-Y': [0, -1, 0],
}

/** on-screen labels: a real minus sign (U+2212), the stored values stay ASCII */
export const PULL_DIR_LABELS: Record<PullDir, string> = {
  '+Z': '+Z',
  '-Z': '−Z',
  '+X': '+X',
  '-X': '−X',
  '+Y': '+Y',
  '-Y': '−Y',
}

/** lil-gui dropdown options: label -> stored value */
export const PULL_DIR_OPTIONS: Record<string, PullDir> = Object.fromEntries(
  (Object.keys(PULL_DIR_LABELS) as PullDir[]).map((d) => [PULL_DIR_LABELS[d], d]),
)

export const DRAFT_MAX_DEG = 10

export type DraftClass = 'ok' | 'short' | 'opposite'

/**
 * sRGB hex. The mesh gets them through THREE.Color (linear) and the lighting
 * then shades them; the legend swatch shows the unshaded colour.
 */
export const DRAFT_COLORS: Record<DraftClass, number> = {
  ok: 0x3ccf5a, // green: releases toward the pull direction
  short: 0xff5a2a, // red-orange: not enough draft (vertical walls included)
  opposite: 0x4a7dff, // blue: faces the other mold half
}

/**
 * Tolerance in sine: a face exactly at the required angle must count as
 * enough, but float noise in the normals (1e-9 or so) would drop it to short.
 */
const EPS = 1e-6

/** s = n·d (sine of the draft angle), sinRequired = sin(required angle) */
export function draftClass(s: number, sinRequired: number): DraftClass {
  if (s >= sinRequired - EPS) return 'ok'
  if (s <= -sinRequired + EPS) return 'opposite'
  return 'short'
}

/**
 * Fill `out` (3 floats per vertex, linear RGB) with the class colour of every
 * vertex. `normals` must be world normals: the part meshes carry no transform
 * (tessellation bakes the placements into positions and normals). If a group
 * transform is ever added, pass the normals through the normal matrix first.
 */
export function draftColors(
  normals: ArrayLike<number>,
  dir: readonly [number, number, number],
  requiredDeg: number,
  out: Float32Array,
): void {
  const t = Math.sin((requiredDeg * Math.PI) / 180)
  const rgb: Record<DraftClass, THREE.Color> = {
    ok: new THREE.Color(DRAFT_COLORS.ok),
    short: new THREE.Color(DRAFT_COLORS.short),
    opposite: new THREE.Color(DRAFT_COLORS.opposite),
  }
  const n = Math.min(normals.length, out.length) / 3
  for (let i = 0; i < n; i++) {
    const x = normals[i * 3]
    const y = normals[i * 3 + 1]
    const z = normals[i * 3 + 2]
    const len = Math.sqrt(x * x + y * y + z * z)
    // a zero or NaN normal (degenerate triangle) has no direction: treat it as
    // a vertical wall. `len > 0` is false for NaN too.
    const s = len > 0 ? (x * dir[0] + y * dir[1] + z * dir[2]) / len : 0
    const c = rgb[draftClass(s, t)]
    out[i * 3] = c.r
    out[i * 3 + 1] = c.g
    out[i * 3 + 2] = c.b
  }
}

/**
 * Legend: title with the direction and angle, one row per class (ok, short,
 * opposite), then a note when some parts have faces but no volume.
 *
 * unorientedParts: parts whose face orientation the backend could not confirm
 * (open surfaces, unsewn faces, mixed winding; /properties gives them no
 * volume). Only closed bodies are turned outward on load, so on these parts
 * the file decides which side is the front: green and blue can be swapped.
 * Red (|n·d| below the required sine) does not depend on the sign.
 */
export function renderDraftLegend(
  el: HTMLElement,
  dir: PullDir,
  requiredDeg: number,
  unorientedParts = 0,
): void {
  const r = requiredDeg.toFixed(1)
  const title = document.createElement('div')
  title.className = 'draft-title'
  title.textContent = `抜き勾配（型開き ${PULL_DIR_LABELS[dir]}、必要 ${r}°）`
  // At 0° a vertical wall (exactly 0°) already counts as enough. Blue says
  // nothing about the parting line: a face on the far side of it releases in
  // the other half, a wall on the pull side leaning the wrong way is a reverse
  // draft that neither half releases. Orientation cannot tell the two apart.
  const rows: [DraftClass, string][] = [
    ['ok', `抜ける側（${r}° 以上）`],
    ['short', `勾配不足（${r}° 未満${requiredDeg > 0 ? '。垂直な壁を含む' : ''}）`],
    ['opposite', `反対側（逆向きに ${r}° 以上。パーティングより反対側の面なら抜ける。型開き側にあれば逆勾配）`],
  ]
  const children: HTMLElement[] = [title]
  for (const [cls, text] of rows) {
    const row = document.createElement('div')
    row.className = 'draft-row'
    row.dataset.cls = cls
    const swatch = document.createElement('span')
    swatch.className = 'draft-swatch'
    swatch.style.background = '#' + DRAFT_COLORS[cls].toString(16).padStart(6, '0')
    const label = document.createElement('span')
    label.textContent = text
    row.append(swatch, label)
    children.push(row)
  }
  if (unorientedParts > 0) {
    const note = document.createElement('div')
    note.className = 'draft-note'
    note.textContent =
      `注: 体積の出ない部品が ${unorientedParts} 個（閉じていない など）。` +
      'その面は表裏がファイルのままなので、緑と青が逆のことがある（赤はそのまま正しい）'
    children.push(note)
  }
  el.replaceChildren(...children)
}
