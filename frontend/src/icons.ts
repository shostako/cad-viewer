/**
 * The app's icons: Lucide (ISC license, bundled from npm: nothing is fetched
 * at run time, the same offline). Only the icons named here go into the
 * bundle.
 */
import {
  Angle,
  Box,
  Check,
  CircleHelp,
  Copy,
  Diameter,
  FolderOpen,
  ImageDown,
  MapPin,
  Rotate3d,
  Ruler,
  Scan,
  Slice,
  createElement,
  type IconNode,
} from 'lucide'

export const ICON = {
  open: FolderOpen,
  fit: Scan,
  rotate: Rotate3d,
  measure: Ruler,
  note: MapPin,
  section: Slice,
  style: Box,
  png: ImageDown,
  help: CircleHelp,
  distance: Ruler,
  diameter: Diameter,
  angle: Angle,
  copy: Copy,
  done: Check,
} satisfies Record<string, IconNode>

/** an icon as an <svg> in the text colour; decorative (the control carries the name) */
export function icon(node: IconNode, size = 16): SVGElement {
  return createElement(node, { width: size, height: size, 'stroke-width': 1.75, 'aria-hidden': 'true' })
}
