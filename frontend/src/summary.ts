/**
 * The status line of an opened file (the HUD's line): its name, its parts and
 * triangles, and its size.
 *
 * STEP and IGES are read into mm: OCCT converts the file's own unit (m, inch,
 * …) into its session's, mm. The mesh formats (STL, 3MF, OBJ, PLY) keep the
 * file's numbers as they are (an STL has no unit at all), so no unit is
 * claimed for them. A drawing's numbers are in its own unit too.
 */
import type { ModelMeta } from './api'
import { LENGTH_UNIT } from './measure'

/** the box's sides, 1 decimal: 100.0 × 60.0 × 40.0 */
function sides(min: readonly number[], max: readonly number[]): string {
  return max.map((v, i) => (v - min[i]).toFixed(1)).join(' × ')
}

/** what a mesh format's size says instead of a unit */
export const FILE_UNIT_NOTE = '（単位はファイルのまま）'

/** a 3D model: "mini_mold.step — 4 部品・304 三角形・100.0 × 60.0 × 40.0 mm" */
export function modelSummaryText(meta: ModelMeta): string {
  const parts = meta.partCount > 1 ? `${meta.partCount} 部品・` : ''
  const unit = meta.format === 'brep' ? ` ${LENGTH_UNIT}` : FILE_UNIT_NOTE
  return `${meta.name} — ${parts}${meta.triangleCount.toLocaleString()} 三角形・${sides(meta.bbox.min, meta.bbox.max)}${unit}`
}

/** a drawing: "plate_drawing.dxf — 2D 図面・100.0 × 60.0（計測で端点・中心に吸い付く）" */
export function drawingSummaryText(meta: ModelMeta): string {
  const size = meta.bbox2d ? sides(meta.bbox2d.min, meta.bbox2d.max) : '?'
  return `${meta.name} — 2D 図面・${size}（計測で端点・中心に吸い付く）`
}
