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

/** what each class is called, in the legend and in the value under the cursor */
export const DRAFT_CLASS_NAMES: Record<DraftClass, string> = {
  ok: '抜ける側',
  short: '勾配不足',
  opposite: '反対側',
}

/**
 * Sine of the draft angle for the normal (x, y, z), of any length: n·d / |n|.
 * A zero or NaN normal (degenerate triangle) has no direction: it counts as
 * a vertical wall (0). `len > 0` is false for NaN too.
 */
export function draftSine(x: number, y: number, z: number, dir: readonly [number, number, number]): number {
  const len = Math.sqrt(x * x + y * y + z * z)
  return len > 0 ? (x * dir[0] + y * dir[1] + z * dir[2]) / len : 0
}

/**
 * draftSine of the triangle at positions[o .. o + 8] (a, b, c), with the
 * normal (b - a) x (c - a) from its winding times `sign` (-1 for a part wound
 * inside out, see windingSign). The rule for mesh formats (draftColorsFlat).
 */
export function triangleDraftSine(
  positions: ArrayLike<number>,
  o: number,
  sign: 1 | -1,
  dir: readonly [number, number, number],
): number {
  const ux = positions[o + 3] - positions[o]
  const uy = positions[o + 4] - positions[o + 1]
  const uz = positions[o + 5] - positions[o + 2]
  const vx = positions[o + 6] - positions[o]
  const vy = positions[o + 7] - positions[o + 1]
  const vz = positions[o + 8] - positions[o + 2]
  const x = uy * vz - uz * vy
  const y = uz * vx - ux * vz
  const z = ux * vy - uy * vx
  return draftSine(sign * x, sign * y, sign * z, dir)
}

/**
 * The value under the cursor: the draft angle asin(s) to 0.1° and its class,
 * e.g. 「勾配 2.0°（抜ける側）」. A face looking away from the pull direction
 * gets a negative angle, with a real minus sign (U+2212, as the direction
 * labels); a value that rounds to 0 has none.
 */
export function draftTipText(s: number, requiredDeg: number): string {
  const deg = (Math.asin(Math.min(1, Math.max(-1, s))) * 180) / Math.PI
  const cls = draftClass(s, Math.sin((requiredDeg * Math.PI) / 180))
  const value = Math.abs(deg).toFixed(1)
  const sign = deg < 0 && value !== '0.0' ? '−' : ''
  return `勾配 ${sign}${value}°（${DRAFT_CLASS_NAMES[cls]}）`
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
  const rgb = classColours()
  const n = Math.min(normals.length, out.length) / 3
  for (let i = 0; i < n; i++) {
    const s = draftSine(normals[i * 3], normals[i * 3 + 1], normals[i * 3 + 2], dir)
    const c = rgb[draftClass(s, t)]
    out[i * 3] = c.r
    out[i * 3 + 1] = c.g
    out[i * 3 + 2] = c.b
  }
}

/**
 * Like draftColors, for a triangle list without an index (Viewer.flatCopy):
 * each triangle is classified by its own normal, (b - a) x (c - a) from its
 * winding, times `sign` (-1 for a part wound inside out, see windingSign), and
 * its three vertices get that colour. No normal array is kept for it.
 */
export function draftColorsFlat(
  positions: ArrayLike<number>,
  sign: 1 | -1,
  dir: readonly [number, number, number],
  requiredDeg: number,
  out: Float32Array,
): void {
  const t = Math.sin((requiredDeg * Math.PI) / 180)
  const rgb = classColours()
  const nTri = Math.floor(Math.min(positions.length, out.length) / 9)
  for (let k = 0; k < nTri; k++) {
    const o = k * 9
    const c = rgb[draftClass(triangleDraftSine(positions, o, sign, dir), t)]
    for (let v = 0; v < 3; v++) {
      out[o + v * 3] = c.r
      out[o + v * 3 + 1] = c.g
      out[o + v * 3 + 2] = c.b
    }
  }
}

/**
 * +1 when a triangle list (no index, 9 floats per triangle) is wound outward,
 * -1 when it is wound inside out. Mesh files (STL and the like) are loaded as
 * written, and some exporters write every triangle the other way round; the
 * part's volume then comes out the same (the backend takes its size), but the
 * winding says front where the back is, which swaps green and blue.
 *
 * The sign of the volume the triangles enclose (divergence theorem: the sum of
 * a·(b×c)/6) tells which: positive for outward winding. It is taken about the
 * bounding-box centre, so a mesh with a small gap, whose sum then depends on
 * the origin, still gets the sign of most of its surface. A part with no
 * volume (a flat sheet) counts as +1: the file decides, as the legend's note
 * says for open parts.
 */
export function windingSign(positions: ArrayLike<number>): 1 | -1 {
  const n = Math.floor(positions.length / 3)
  if (n === 0) return 1
  const lo = [Infinity, Infinity, Infinity]
  const hi = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 3; k++) {
      const v = positions[i * 3 + k]
      if (v < lo[k]) lo[k] = v
      if (v > hi[k]) hi[k] = v
    }
  }
  const cx = (lo[0] + hi[0]) / 2
  const cy = (lo[1] + hi[1]) / 2
  const cz = (lo[2] + hi[2]) / 2
  let six = 0 // six times the signed volume
  for (let o = 0; o + 9 <= positions.length; o += 9) {
    const ax = positions[o] - cx
    const ay = positions[o + 1] - cy
    const az = positions[o + 2] - cz
    const bx = positions[o + 3] - cx
    const by = positions[o + 4] - cy
    const bz = positions[o + 5] - cz
    const qx = positions[o + 6] - cx
    const qy = positions[o + 7] - cy
    const qz = positions[o + 8] - cz
    six += ax * (by * qz - bz * qy) + ay * (bz * qx - bx * qz) + az * (bx * qy - by * qx)
  }
  return six < 0 ? -1 : 1
}

function classColours(): Record<DraftClass, THREE.Color> {
  return {
    ok: new THREE.Color(DRAFT_COLORS.ok),
    short: new THREE.Color(DRAFT_COLORS.short),
    opposite: new THREE.Color(DRAFT_COLORS.opposite),
  }
}

/**
 * Legend: title with the direction and angle, one row per class (ok, short,
 * opposite), then a note when some parts have faces but no volume.
 *
 * unorientedParts: parts whose face orientation the backend could not confirm
 * (open surfaces, unsewn faces, mixed winding; /properties gives them no
 * volume). Closed bodies are turned outward (B-rep on load, mesh formats by
 * windingSign); on these parts the file decides which side is the front:
 * green and blue can be swapped.
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
    ['ok', `${DRAFT_CLASS_NAMES.ok}（${r}° 以上）`],
    ['short', `${DRAFT_CLASS_NAMES.short}（${r}° 未満${requiredDeg > 0 ? '。垂直な壁を含む' : ''}）`],
    [
      'opposite',
      `${DRAFT_CLASS_NAMES.opposite}（逆向きに ${r}° 以上。パーティングより反対側の面なら抜ける。型開き側にあれば逆勾配）`,
    ],
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
