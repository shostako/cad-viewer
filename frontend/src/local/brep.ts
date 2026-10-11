/**
 * STEP/IGES in the Web version: read with OpenCASCADE in WebAssembly
 * (libcascade, OCCT 8), tessellated with topology IDs. A port of
 * backend/app/tessellation.py, step for step, so a model has the same parts,
 * tree, and face / edge / vertex numbers (TopExp.MapShapes' order) as the
 * checkout's backend gives it. Change one, change the other.
 *
 * OCCT objects live in the WebAssembly heap, and embind frees one only on
 * .delete() (occtbag.ts). The ones made per node or per triangle are deleted
 * as soon as they are read (a model of a million nodes would otherwise fill
 * the heap); the ones per face or per edge go in that face's or edge's bag; the
 * rest of a load in the load's bag (k), out of which the model's own (its parts'
 * shapes and maps) are taken before it is emptied.
 */
import { Bag, withBag, type Keep } from './occtbag.ts'

/* eslint-disable @typescript-eslint/no-explicit-any */
type OC = any

export class BrepLoadError extends Error {}

export type RGB = [number, number, number]

export interface BrepPart {
  id: number
  name: string
  shape: any
  color: RGB | null
}

export interface TreeNode {
  name: string
  partId?: number
  children?: TreeNode[]
}

export interface PartMesh {
  part: BrepPart
  positions: Float32Array
  normals: Float32Array
  indices: Uint32Array
  faceRanges: { faceId: number; triStart: number; triCount: number }[]
  edgePositions: Float32Array
  edgeRanges: { edgeId: number; segStart: number; segCount: number }[]
  /** row i is vertexId i + 1 */
  vertexPositions: Float32Array
  /** the B-rep's numbering (TopTools_IndexedMapOfShape), for measuring */
  faceMap: any
  edgeMap: any
  vertexMap: any
}

const STEP_UNITS: Record<string, string> = {
  millimetre: 'mm', millimeter: 'mm', centimetre: 'cm', centimeter: 'cm', metre: 'm', meter: 'm',
  micrometre: 'µm', micrometer: 'µm', inch: 'in', foot: 'ft', kilometre: 'km', mil: 'mil',
}
const IGES_UNITS: Record<number, string> = { 1: 'in', 2: 'mm', 4: 'ft', 5: 'mi', 6: 'm', 7: 'km', 8: 'mil', 9: 'µm', 10: 'cm', 11: 'µin' }

// sewing (tessellation.py's SEW_TOLERANCES, SEW_MAX_REL)
const SEW_TOLERANCES = [1e-4, 1e-3, 1e-2]
const SEW_MAX_REL = 1e-4

// ---- reading ------------------------------------------------------------------

function labelName(oc: OC, k: Keep, label: any): string {
  // FindAttribute's out-parameter comes back in its result (as the attribute's own type)
  const found = label.FindAttribute(k(oc.TDataStd_Name.GetID()))
  k(found?.anAttribute)
  try {
    if (!found?.returnValue) return ''
    // the extended (UTF-16) string through an ASCII one with no replacement
    // character: OCCT converts it to UTF-8 then (ToExtString and Value are not
    // bound in this build)
    const ascii = k(new oc.TCollection_AsciiString(k(found.anAttribute.Get()), '\0'))
    return String(ascii.ToCString())
  } catch {
    return ''
  }
}

function stepUnit(oc: OC, k: Keep, reader: any): string | null {
  const lengths = k(new oc.NCollection_Sequence_TCollection_AsciiString())
  const angles = k(new oc.NCollection_Sequence_TCollection_AsciiString())
  const solid = k(new oc.NCollection_Sequence_TCollection_AsciiString())
  k(reader.ChangeReader()).FileUnits(lengths, angles, solid)
  const names: string[] = []
  for (let i = 1; i <= lengths.Length(); i++) {
    const raw = String(k(lengths.Value(i)).ToCString()).trim()
    const name = STEP_UNITS[raw.toLowerCase()] ?? raw
    if (name && !names.includes(name)) names.push(name)
  }
  return names.join('・') || null
}

function igesUnit(k: Keep, reader: any): string | null {
  const gs = k(k(reader.IGESModel()).GlobalSection())
  const flag = gs.UnitFlag()
  if (IGES_UNITS[flag]) return IGES_UNITS[flag]
  const name = k(gs.UnitName())
  const text = name ? String(name.ToCString()).trim() : ''
  return text || null
}

function safeUnit(read: () => string | null): string | null {
  try {
    return read()
  } catch {
    return null
  }
}

/** the file as an XCAF document; info.fileUnit: the length unit it is written in (OCCT reads it into mm) */
export function readDocument(oc: OC, k: Keep, bytes: Uint8Array, filename: string, info: { fileUnit?: string | null } = {}): any {
  const ext = filename.slice(filename.lastIndexOf('.') + 1).toLowerCase()
  // a short fixed name: a long one has made a reader find nothing before (an old opencascade.js)
  const path = `/m.${ext}`
  oc.FS.writeFile(path, bytes)
  try {
    const doc = k(new oc.TDocStd_Document(k(new oc.TCollection_ExtendedString('XmlXCAF'))))
    if (ext === 'step' || ext === 'stp') {
      const reader = k(new oc.STEPCAFControl_Reader())
      reader.SetColorMode(true)
      reader.SetNameMode(true)
      if (reader.ReadFile(path) !== 'IFSelect_RetDone') throw new BrepLoadError('STEP read failed (file corrupt or unsupported)')
      if (!reader.Transfer(doc, k(new oc.Message_ProgressRange()))) throw new BrepLoadError('STEP transfer failed')
      info.fileUnit = safeUnit(() => stepUnit(oc, k, reader))
    } else if (ext === 'iges' || ext === 'igs') {
      const reader = k(new oc.IGESCAFControl_Reader())
      reader.SetColorMode(true)
      reader.SetNameMode(true)
      if (reader.ReadFile(path) !== 'IFSelect_RetDone') throw new BrepLoadError('IGES read failed (file corrupt or unsupported)')
      if (!reader.Transfer(doc, k(new oc.Message_ProgressRange()))) throw new BrepLoadError('IGES transfer failed')
      info.fileUnit = safeUnit(() => igesUnit(k, reader))
    } else {
      throw new BrepLoadError(`not a B-rep format: .${ext}`)
    }
    return doc
  } finally {
    try {
      oc.FS.unlink(path)
    } catch {
      // already gone
    }
  }
}

/** the XCAF assembly flattened into located leaf parts and a display tree (tessellation.extract_parts) */
export function extractParts(oc: OC, k: Keep, doc: any): [BrepPart[], TreeNode] {
  const shapeTool = k(oc.XCAFDoc_DocumentTool.ShapeTool(k(doc.Main())))
  const parts: BrepPart[] = []
  const root: TreeNode = { name: 'root', children: [] }

  const labelColor = (label: any): RGB | null => {
    for (const ctype of [oc.XCAFDoc_ColorType.XCAFDoc_ColorSurf, oc.XCAFDoc_ColorType.XCAFDoc_ColorGen]) {
      const colorLabel = k(new oc.TDF_Label())
      if (oc.XCAFDoc_ColorTool.GetColor(label, ctype, colorLabel)) {
        const c = k(new oc.Quantity_Color())
        if (oc.XCAFDoc_ColorTool.GetColor(colorLabel, c)) return [c.Red(), c.Green(), c.Blue()]
      }
    }
    return null
  }

  const visit = (label: any, loc: any, node: TreeNode, inherited: RGB | null, nameOverride: string | null = null): void => {
    let rawName = labelName(oc, k, label)
    // instance labels carry auto-generated names like "=>[0:1:1:2]": ignored
    if (rawName.startsWith('=>')) rawName = ''
    const name = nameOverride || rawName || 'part'
    const color = labelColor(label) ?? inherited

    const ref = k(new oc.TDF_Label())
    if (oc.XCAFDoc_ShapeTool.GetReferredShape(label, ref)) {
      // an instance: follow the reference, its location composed
      const instLoc = k(oc.XCAFDoc_ShapeTool.GetLocation(label))
      visit(ref, k(loc.Multiplied(instLoc)), node, color, rawName || null)
      return
    }
    if (oc.XCAFDoc_ShapeTool.IsAssembly(label)) {
      const comps = k(new oc.NCollection_Sequence_TDF_Label())
      oc.XCAFDoc_ShapeTool.GetComponents(label, comps, false)
      const sub: TreeNode = { name, children: [] }
      node.children!.push(sub)
      for (let i = 1; i <= comps.Length(); i++) visit(k(comps.Value(i)), loc, sub, color)
      return
    }
    const shape = k(new oc.TopoDS_Shape())
    if (!oc.XCAFDoc_ShapeTool.GetShape(label, shape) || shape.IsNull()) return
    const located = k(shape.Moved(loc, true))
    const part: BrepPart = { id: parts.length, name, shape: located, color }
    parts.push(part)
    node.children!.push({ name, partId: part.id })
  }

  const free = k(new oc.NCollection_Sequence_TDF_Label())
  shapeTool.GetFreeShapes(free)
  for (let i = 1; i <= free.Length(); i++) visit(k(free.Value(i)), k(new oc.TopLoc_Location()), root, null)
  if (!parts.length) throw new BrepLoadError('no shapes found in file')
  return [parts, root]
}

// ---- loose shapes ------------------------------------------------------------

const contains = (oc: OC, k: Keep, shape: any, kind: any) => k(new oc.TopExp_Explorer(shape, kind, oc.TopAbs_ShapeEnum.TopAbs_SHAPE)).More()

function isSheet(oc: OC, k: Keep, shape: any): boolean {
  const E = oc.TopAbs_ShapeEnum
  const t = shape.ShapeType()
  if (t === E.TopAbs_FACE || t === E.TopAbs_SHELL) return true
  return t === E.TopAbs_COMPOUND && contains(oc, k, shape, E.TopAbs_FACE) && !contains(oc, k, shape, E.TopAbs_SOLID)
}

function isCurve(oc: OC, k: Keep, shape: any): boolean {
  const E = oc.TopAbs_ShapeEnum
  const t = shape.ShapeType()
  if (t === E.TopAbs_EDGE || t === E.TopAbs_WIRE) return true
  return t === E.TopAbs_COMPOUND && !contains(oc, k, shape, E.TopAbs_FACE) && contains(oc, k, shape, E.TopAbs_EDGE)
}

function faceTotal(oc: OC, k: Keep, shapes: any[]): number {
  let n = 0
  for (const s of shapes) {
    const e = k(new oc.TopExp_Explorer(s, oc.TopAbs_ShapeEnum.TopAbs_FACE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE))
    for (; e.More(); e.Next()) n++
  }
  return n
}

/** loose top-level faces sewn into bodies, loose curves gathered into one part (tessellation.merge_loose_shapes) */
export function mergeLooseShapes(oc: OC, k: Keep, parts: BrepPart[], tree: TreeNode): [BrepPart[], TreeNode] {
  const topIds = (tree.children ?? []).filter((c) => c.partId !== undefined).map((c) => c.partId!)
  const byId = new Map(parts.map((p) => [p.id, p]))
  let sheets = topIds.map((i) => byId.get(i)!).filter((p) => isSheet(oc, k, p.shape))
  let curves = topIds.map((i) => byId.get(i)!).filter((p) => isCurve(oc, k, p.shape))
  if (faceTotal(oc, k, sheets.map((p) => p.shape)) < 2) sheets = []
  if (curves.length < 2) curves = []
  if (!sheets.length && !curves.length) return [parts, tree]

  let bodies: any[] = []
  if (sheets.length) {
    try {
      bodies = sew(oc, k, sheets.map((p) => p.shape))
    } catch {
      return [parts, tree]
    }
    if (!bodies.length) return [parts, tree]
  }
  const merged = new Set([...sheets, ...curves].map((p) => p.id))
  const newParts: BrepPart[] = []
  const newTree: TreeNode = { name: tree.name, children: [] }
  const add = (name: string, shape: any, color: RGB | null) => {
    const part: BrepPart = { id: newParts.length, name, shape, color }
    newParts.push(part)
    newTree.children!.push({ name, partId: part.id })
  }
  const copyNode = (node: TreeNode): TreeNode => {
    if (node.partId !== undefined) {
      const old = byId.get(node.partId)!
      const part: BrepPart = { id: newParts.length, name: old.name, shape: old.shape, color: old.color }
      newParts.push(part)
      return { name: node.name, partId: part.id }
    }
    return { name: node.name, children: (node.children ?? []).map(copyNode) }
  }
  for (const child of tree.children ?? []) {
    if (child.partId !== undefined && merged.has(child.partId)) continue
    newTree.children!.push(copyNode(child))
  }
  const SOLID = oc.TopAbs_ShapeEnum.TopAbs_SOLID
  if (bodies.length) {
    const solids = bodies.filter((b) => b.ShapeType() === SOLID).length
    const color = commonColor(sheets)
    bodies.forEach((body, i) => {
      const kind = body.ShapeType() === SOLID ? 'ソリッド' : 'サーフェス'
      const sameKind = kind === 'ソリッド' ? solids : bodies.length - solids
      add(sameKind > 1 ? `${kind} ${i + 1}` : kind, body, color)
    })
  }
  if (curves.length) {
    const builder = k(new oc.BRep_Builder())
    const compound = k(new oc.TopoDS_Compound())
    builder.MakeCompound(compound)
    for (const p of curves) builder.Add(compound, p.shape)
    add(`曲線（${curves.length} 本）`, compound, commonColor(curves))
  }
  return [newParts, newTree]
}

function commonColor(parts: BrepPart[]): RGB | null {
  const keys = new Set(parts.map((p) => (p.color ? p.color.join(',') : 'none')))
  return keys.size === 1 ? parts[0].color : null
}

function shapeDiagonal(oc: OC, k: Keep, shapes: any[]): number {
  const box = k(new oc.Bnd_Box())
  for (const s of shapes) oc.BRepBndLib.Add(s, box, true)
  if (box.IsVoid()) return 0
  const lo = k(box.CornerMin()), hi = k(box.CornerMax())
  return Math.hypot(hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z())
}

function isClosedShell(oc: OC, shape: any): boolean {
  return shape.ShapeType() === oc.TopAbs_ShapeEnum.TopAbs_SHELL && oc.BRep_Tool.IsClosed(shape)
}

function topLevel(oc: OC, k: Keep, shape: any): any[] {
  if (!shape || shape.IsNull()) return []
  if (shape.ShapeType() !== oc.TopAbs_ShapeEnum.TopAbs_COMPOUND) return [shape]
  const out: any[] = []
  const it = k(new oc.TopoDS_Iterator(shape, true, true))
  for (; it.More(); it.Next()) out.push(...topLevel(oc, k, k(it.Value())))
  return out
}

/** faces sewn into bodies, each shell settled at the smallest tolerance that closes it (tessellation._sew) */
function sew(oc: OC, k: Keep, shapes: any[]): any[] {
  const cap = Math.max(shapeDiagonal(oc, k, shapes) * SEW_MAX_REL, SEW_TOLERANCES[0]) * (1 + 1e-9)
  const settled: any[] = []
  let pending = [...shapes]
  for (const tol of SEW_TOLERANCES.filter((t) => t <= cap)) {
    const sewing = k(new oc.BRepBuilderAPI_Sewing(tol, true, true, true, false))
    for (const s of pending) sewing.Add(s)
    sewing.Perform(k(new oc.Message_ProgressRange()))
    const bodies = topLevel(oc, k, k(sewing.SewedShape()))
    if (!bodies.length) throw new Error(`sewing at ${tol} returned no shape`)
    settled.push(...bodies.filter((b) => isClosedShell(oc, b)))
    pending = bodies.filter((b) => !isClosedShell(oc, b))
    if (!pending.length) break
  }
  return [...settled, ...pending].map((b) => close(oc, k, b))
}

function volumeOf(oc: OC, k: Keep, shape: any): number {
  const props = k(new oc.GProp_GProps())
  oc.BRepGProp.VolumeProperties(shape, props, false, false, false)
  return props.Mass()
}

/** a closed shell as an outward-facing solid; anything else unchanged */
function close(oc: OC, k: Keep, body: any): any {
  if (!isClosedShell(oc, body)) return body
  try {
    const solid = k(k(new oc.BRepBuilderAPI_MakeSolid(k(oc.TopoDS.Shell(body)))).Solid())
    const fix = k(new oc.ShapeFix_Solid())
    fix.Init(solid)
    fix.Perform(k(new oc.Message_ProgressRange()))
    let result = k(fix.Solid())
    const volume = volumeOf(oc, k, result)
    if (Math.abs(volume) < 1e-12) return body
    if (volume < 0) result = k(result.Reversed())
    return result
  } catch {
    return body
  }
}

// ---- meshing -----------------------------------------------------------------

export function combinedDeflection(oc: OC, k: Keep, parts: BrepPart[], relative = 1e-3): number {
  const diag = shapeDiagonal(oc, k, parts.map((p) => p.shape))
  if (diag === 0) return 0.1
  return Math.max(diag * relative, 1e-6)
}

function shapeMap(oc: OC, k: Keep, shape: any, kind: any): any {
  const map = k(new oc.NCollection_IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher())
  oc.TopExp.MapShapes(shape, kind, map)
  return map
}

/** a part's display mesh, every triangle and edge segment tagged with its B-rep face / edge (tessellation.tessellate_part) */
export function tessellatePart(oc: OC, k: Keep, part: BrepPart, linDeflection: number, angDeflection = 0.35): PartMesh {
  const E = oc.TopAbs_ShapeEnum
  const shape = part.shape
  new oc.BRepMesh_IncrementalMesh(shape, linDeflection, false, angDeflection, true).delete()

  const faceMap = shapeMap(oc, k, shape, E.TopAbs_FACE)
  const pos: number[] = []
  const nrm: number[] = []
  const tris: number[] = []
  const faceRanges: PartMesh['faceRanges'] = []
  let vertOffset = 0
  let triOffset = 0
  for (let fi = 1; fi <= faceMap.Size(); fi++) withBag((f) => {
    const face = f(oc.TopoDS.Face(f(faceMap.FindKey(fi))))
    const loc = f(new oc.TopLoc_Location())
    const tri = f(oc.BRep_Tool.Triangulation(face, loc, 0))
    if (!tri || tri.IsNull?.() || tri.NbTriangles() === 0) return
    const trsf = f(loc.Transformation())
    const nNodes = tri.NbNodes()
    for (let i = 1; i <= nNodes; i++) {
      const p = tri.Node(i)
      const q = p.Transformed(trsf)
      pos.push(q.X(), q.Y(), q.Z())
      q.delete()
      p.delete()
    }
    // per-node normals (OCCT computes them on the triangulation), turned by the location
    oc.BRepLib_ToolTriangulatedShape.ComputeNormals(face, tri)
    const r = [1, 2, 3].map((row) => [1, 2, 3].map((col) => trsf.Value(row, col)))
    const reversed = face.Orientation() === oc.TopAbs_Orientation.TopAbs_REVERSED
    const sign = reversed ? -1 : 1
    for (let i = 1; i <= nNodes; i++) {
      const d = tri.Normal(i)
      const x = d.X(), y = d.Y(), z = d.Z()
      d.delete()
      nrm.push(
        sign * (r[0][0] * x + r[0][1] * y + r[0][2] * z),
        sign * (r[1][0] * x + r[1][1] * y + r[1][2] * z),
        sign * (r[2][0] * x + r[2][1] * y + r[2][2] * z),
      )
    }
    const nTris = tri.NbTriangles()
    for (let i = 1; i <= nTris; i++) {
      const t = tri.Triangle(i)
      const a = t.Value(1) - 1, b = t.Value(2) - 1, c = t.Value(3) - 1
      t.delete()
      if (reversed) tris.push(a + vertOffset, c + vertOffset, b + vertOffset)
      else tris.push(a + vertOffset, b + vertOffset, c + vertOffset)
    }
    faceRanges.push({ faceId: fi, triStart: triOffset, triCount: nTris })
    vertOffset += nNodes
    triOffset += nTris
  })

  // edges: the polyline on an adjacent face's triangulation; a free curve sampled
  const edgeMap = shapeMap(oc, k, shape, E.TopAbs_EDGE)
  // only the edge loop needs it (the face / edge / vertex maps are kept)
  const ancestors = k(new oc.NCollection_IndexedDataMap_TopoDS_Shape_NCollection_List_TopoDS_Shape_TopTools_ShapeMapHasher())
  oc.TopExp.MapShapesAndAncestors(shape, E.TopAbs_EDGE, E.TopAbs_FACE, ancestors)
  const segs: number[] = []
  const edgeRanges: PartMesh['edgeRanges'] = []
  let segOffset = 0
  for (let ei = 1; ei <= edgeMap.Size(); ei++) withBag((e) => {
    const edge = e(oc.TopoDS.Edge(e(edgeMap.FindKey(ei))))
    let pl = edgePolyline(oc, e, edge, ancestors)
    if (pl === null && faceCount(e, edge, ancestors) === 0) pl = curvePolyline(oc, e, edge, linDeflection, angDeflection)
    if (pl === null || pl.length < 6) return
    const n = pl.length / 3
    for (let i = 0; i + 1 < n; i++) segs.push(pl[3 * i], pl[3 * i + 1], pl[3 * i + 2], pl[3 * i + 3], pl[3 * i + 4], pl[3 * i + 5])
    edgeRanges.push({ edgeId: ei, segStart: segOffset, segCount: n - 1 })
    segOffset += n - 1
  })

  // vertices: the B-rep's exact points (snap targets)
  const vertexMap = shapeMap(oc, k, shape, E.TopAbs_VERTEX)
  const verts = new Float32Array(vertexMap.Size() * 3)
  for (let vi = 1; vi <= vertexMap.Size(); vi++) withBag((v) => {
    const p = v(oc.BRep_Tool.Pnt(v(oc.TopoDS.Vertex(v(vertexMap.FindKey(vi))))))
    verts.set([p.X(), p.Y(), p.Z()], 3 * (vi - 1))
  })
  return {
    part,
    positions: Float32Array.from(pos),
    normals: Float32Array.from(nrm),
    indices: Uint32Array.from(tris),
    faceRanges,
    edgePositions: Float32Array.from(segs),
    edgeRanges,
    vertexPositions: verts,
    faceMap,
    edgeMap,
    vertexMap,
  }
}

/** the faces an edge bounds (MapShapesAndAncestors also lists edges that bound none, with an empty list) */
function facesOf(k: Keep, edge: any, ancestors: any): any | null {
  const i = ancestors.FindIndex(edge)
  return i > 0 ? k(ancestors.FindFromIndex(i)) : null
}

function faceCount(k: Keep, edge: any, ancestors: any): number {
  return facesOf(k, edge, ancestors)?.Size() ?? 0
}

function edgePolyline(oc: OC, k: Keep, edge: any, ancestors: any): number[] | null {
  const faces = facesOf(k, edge, ancestors)
  if (!faces || faces.Size() === 0) return null
  const face = k(oc.TopoDS.Face(k(faces.First())))
  const loc = k(new oc.TopLoc_Location())
  const tri = k(oc.BRep_Tool.Triangulation(face, loc, 0))
  if (!tri || tri.IsNull?.()) return null
  const poly = k(oc.BRep_Tool.PolygonOnTriangulation(edge, tri, loc))
  if (!poly || poly.IsNull?.()) return null
  const trsf = k(loc.Transformation())
  const nodes = k(poly.Nodes())
  const out: number[] = []
  for (let i = nodes.Lower(); i <= nodes.Upper(); i++) {
    const p = tri.Node(nodes.Value(i))
    const q = p.Transformed(trsf)
    out.push(q.X(), q.Y(), q.Z())
    q.delete()
    p.delete()
  }
  return out
}

function curvePolyline(oc: OC, k: Keep, edge: any, lin: number, ang: number): number[] | null {
  if (oc.BRep_Tool.Degenerated(edge)) return null
  try {
    const curve = k(new oc.BRepAdaptor_Curve(edge))
    // three arguments: with six, the overload taken is the one with a parameter
    // range (first, last) in second and third place
    const disc = k(new oc.GCPnts_TangentialDeflection(curve, ang, lin))
    const n = disc.NbPoints()
    if (n < 2) return null
    const out: number[] = []
    for (let i = 1; i <= n; i++) {
      const p = disc.Value(i)
      out.push(p.X(), p.Y(), p.Z())
      p.delete()
    }
    return out
  } catch {
    return null
  }
}

// ---- top level -----------------------------------------------------------------

/** bytes -> located parts -> tessellated meshes + tree (tessellation.load_brep) */
export function loadBrep(oc: OC, bytes: Uint8Array, filename: string, info: { fileUnit?: string | null } = {}): { meshes: PartMesh[]; tree: TreeNode; deflection: number } {
  const bag = new Bag()
  const k = bag.k
  try {
    const doc = readDocument(oc, k, bytes, filename, info)
    let [parts, tree] = extractParts(oc, k, doc)
    ;[parts, tree] = mergeLooseShapes(oc, k, parts, tree)
    const deflection = combinedDeflection(oc, k, parts)
    const meshes = parts.map((p) => tessellatePart(oc, k, p, deflection))
    // the model's own, kept with it (deleted when the model is: backend.ts)
    for (const m of meshes) bag.spare(m.part.shape, m.faceMap, m.edgeMap, m.vertexMap)
    return { meshes, tree, deflection }
  } finally {
    bag.free()
  }
}
