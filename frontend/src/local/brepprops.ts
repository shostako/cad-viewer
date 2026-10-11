/**
 * Volume, area and centre of mass of a B-rep part in the Web version
 * (backend/app/properties.py's brep_part_properties, step for step): exact,
 * by OCCT's integration on the true surfaces. As strict as there: an open
 * shell, a loose face or a wrongly oriented shell gives no volume at all.
 */
import type { PartProps, Vec3 } from './meshprops.ts'

/* eslint-disable @typescript-eslint/no-explicit-any */
type OC = any

const DEGENERATE_REL = 1e-9

function shapes(oc: OC, shape: any, kind: string, avoid = 'TopAbs_SHAPE'): any[] {
  const out: any[] = []
  const e = new oc.TopExp_Explorer(shape, kind, avoid)
  for (; e.More(); e.Next()) out.push(e.Current())
  return out
}

/** signed volume and centroid (OCCT handles hollow solids by shell orientation) */
function volume(oc: OC, shape: any): [number, Vec3] {
  const props = new oc.GProp_GProps()
  oc.BRepGProp.VolumeProperties(shape, props, false, false, false)
  const c = props.CentreOfMass()
  return [props.Mass(), [c.X(), c.Y(), c.Z()]]
}

/** sum of |V| and the |V|-weighted centroid: a body turned inside out must not cancel another */
function combine(bodies: [number, Vec3][]): [number, Vec3 | null] {
  const total = bodies.reduce((s, [v]) => s + Math.abs(v), 0)
  if (total <= 0) return [0, null]
  return [total, [0, 1, 2].map((i) => bodies.reduce((s, [v, c]) => s + Math.abs(v) * c[i], 0) / total) as Vec3]
}

function diag(oc: OC, shape: any): number {
  const box = new oc.Bnd_Box()
  oc.BRepBndLib.Add(shape, box, true)
  if (box.IsVoid()) return 0
  const lo = box.CornerMin(), hi = box.CornerMax()
  return Math.hypot(hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z())
}

/** a closed shell whose faces disagree on which side is outside */
function mixedOrientation(oc: OC, shell: any): boolean {
  const sas = new oc.ShapeAnalysis_Shell()
  sas.LoadShells(shell)
  return Boolean(sas.CheckOrientedShells(shell, true, false))
}

/** a hollow solid whose inner shell is oriented like the outer one (OCCT would add the cavity) */
function cavityFacingOut(oc: OC, shells: any[]): boolean {
  if (shells.length < 2) return false
  const signed = shells.map((s) => volume(oc, s)[0])
  let outer = 0
  for (let k = 1; k < signed.length; k++) if (Math.abs(signed[k]) > Math.abs(signed[outer])) outer = k
  const tiny = Math.abs(signed[outer]) * 1e-9
  return signed.some((v, k) => k !== outer && Math.abs(v) > tiny && v * signed[outer] > 0)
}

function part(closed: boolean, vol: number | null, area: number | null, com: Vec3 | null, reason: PartProps['reason']): PartProps {
  return { closed, volume: vol, area, centerOfMass: com, reason }
}

export function brepPartProperties(oc: OC, shape: any): PartProps {
  try {
    if (!shapes(oc, shape, 'TopAbs_FACE').length) return part(false, null, 0, null, 'no_faces')
    const props = new oc.GProp_GProps()
    oc.BRepGProp.SurfaceProperties(shape, props, false, false)
    const area = props.Mass()
    const bodies: [number, Vec3][] = []
    let open = false
    let mixed = false
    for (const solid of shapes(oc, shape, 'TopAbs_SOLID')) {
      const shells = shapes(oc, solid, 'TopAbs_SHELL')
      if (shells.length && shells.every((s) => oc.BRep_Tool.IsClosed(s))) {
        if (shells.some((s) => mixedOrientation(oc, s)) || cavityFacingOut(oc, shells)) mixed = true
        else bodies.push(volume(oc, solid))
      } else open = true
    }
    for (const shell of shapes(oc, shape, 'TopAbs_SHELL', 'TopAbs_SOLID')) {
      if (!oc.BRep_Tool.IsClosed(shell)) open = true
      else if (mixedOrientation(oc, shell)) mixed = true
      else bodies.push(volume(oc, shell))
    }
    if (shapes(oc, shape, 'TopAbs_FACE', 'TopAbs_SHELL').length) open = true
    if (open) return part(false, null, area, null, 'open')
    if (mixed) return part(false, null, area, null, 'winding')
    const [vol, com] = combine(bodies)
    if (vol <= DEGENERATE_REL * diag(oc, shape) ** 3) return part(false, null, area, null, 'degenerate')
    return part(true, vol, area, com, null)
  } catch {
    return part(false, null, null, null, 'failed')
  }
}
