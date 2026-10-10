/**
 * The app's icons: Lucide (ISC license, bundled from npm: nothing is fetched
 * at run time, the same offline). Only the icons named here go into the
 * bundle.
 */
import {
  Angle,
  Box,
  Check,
  ChevronDown,
  CircleHelp,
  Cone,
  Copy,
  Diameter,
  FolderOpen,
  ImageDown,
  MapPin,
  Radius,
  Rotate3d,
  Ruler,
  Scan,
  Slice,
  createElement,
  type IconNode,
} from 'lucide'

export const ICON = {
  open: FolderOpen,
  recent: ChevronDown,
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
  radius: Radius,
  angle: Angle,
  draft: Cone,
  copy: Copy,
  done: Check,
} satisfies Record<string, IconNode>

/** an icon as an <svg> in the text colour; decorative (the control carries the name) */
export function icon(node: IconNode, size = 16): SVGElement {
  return createElement(node, { width: size, height: size, 'stroke-width': 1.75, 'aria-hidden': 'true' })
}
