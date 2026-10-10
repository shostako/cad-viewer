/** Section (clipping plane) tool with stencil caps.
 *
 * Caps use the classic webgl_clipping_stencil technique: clipped back faces
 * increment the stencil, front faces decrement, and a plane quad drawn where
 * stencil != 0 fills the cut. Stencil meshes live inside each part's group so
 * the assembly-tree visibility toggles them for free. The technique is
 * version-fragile — three.js is pinned in package.json, and `caps` can be
 * switched off as a fallback.
 *
 * Display styles: the stencil meshes are siblings of the face mesh, so they
 * keep counting when ワイヤーフレーム hides the faces. In 陰影＋稜線 / 陰影のみ the
 * cap is opaque, as always. In ワイヤーフレーム / 半透明 it is translucent: the
 * point of those styles is to see what is inside the mold, and an opaque cap
 * would hide exactly the inner parts behind the cut (in ワイヤーフレーム it would
 * be the only opaque surface, hiding the lines behind it). Denser than the
 * faces, the cut still reads as material, and the stencil keeps the tint inside
 * the cross-section. A transparent cap is drawn in three's transparent pass,
 * still after the stencil meshes (opaque pass, renderOrder 1), and nothing in
 * between writes the stencil, so the cut stays closed.
 */
import * as THREE from 'three'
import { onTheme, palette } from './theme'
import type { Viewer } from './viewer'

const CAP_COLOR = 0x9aa4b0
/** cap opacity in the see-through styles: denser than the faces (0.3), so the cut reads as material without hiding what is behind it */
const CAP_SEE_THROUGH_OPACITY = 0.5

export type Axis = 'X' | 'Y' | 'Z'

const NORMALS: Record<Axis, THREE.Vector3> = {
  X: new THREE.Vector3(-1, 0, 0),
  Y: new THREE.Vector3(0, -1, 0),
  Z: new THREE.Vector3(0, 0, -1),
}
const AXIS_INDEX: Record<Axis, number> = { X: 0, Y: 1, Z: 2 }
/** the plane's frame: a thin outline just outside the model's cross-section, in the palette's sectionFrame */
const FRAME_OPACITY = 0.55

export class SectionTool {
  enabled = false
  axis: Axis = 'X'
  /** 0..1 position across the model bbox along the axis (shown in mm: see mm) */
  position = 0.5
  /** keep the upper side of the plane (the default keeps the lower one) */
  flip = false
  caps = true

  private viewer: Viewer
  private plane = new THREE.Plane(NORMALS.X.clone(), 0)
  private helper: THREE.LineLoop | null = null
  private bbox = new THREE.Box3()
  private stencilMeshes: THREE.Mesh[] = []
  private capMesh: THREE.Mesh | null = null

  constructor(viewer: Viewer) {
    this.viewer = viewer
    viewer.renderer.localClippingEnabled = true
    viewer.onDisplayStyleChange(() => this.styleCap())
    onTheme((p) => (this.helper?.material as THREE.LineBasicMaterial | undefined)?.color.set(p.sectionFrame))
  }

  /** the model's extent along the axis: the plane's range (model units, mm) */
  range(): [number, number] {
    if (this.bbox.isEmpty()) return [0, 1] // no model yet
    const i = AXIS_INDEX[this.axis]
    return [this.bbox.min.getComponent(i), this.bbox.max.getComponent(i)]
  }

  /** where the plane is along the axis, in model units (mm) */
  get mm(): number {
    const [lo, hi] = this.range()
    return lo + (hi - lo) * this.position
  }

  set mm(v: number) {
    const [lo, hi] = this.range()
    this.position = hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0.5
  }

  /**
   * Cut away the side the camera is on, so that the cut faces it. Called
   * when the section is put in and when its axis changes; 反転 stays the
   * user's until then. (Before, the side was fixed per axis: along Y, from
   * the opening view, the cut faced away and nothing seemed to happen.)
   */
  faceCamera(camera: THREE.Vector3): void {
    // the default normal (-axis) keeps the lower side: right while the camera is above the plane
    this.flip = camera.getComponent(AXIS_INDEX[this.axis]) < this.mm
  }

  setModelBBox(min: number[], max: number[]): void {
    this.bbox.set(new THREE.Vector3(...min), new THREE.Vector3(...max))
    this.teardownCaps() // stale stencil meshes reference the previous model
    this.update()
  }

  update(): void {
    if (!this.enabled) {
      this.viewer.setClippingPlanes([])
      this.removeHelper()
      this.teardownCaps()
      return
    }
    const n = NORMALS[this.axis].clone()
    if (this.flip) n.negate()

    // plane: n·p + d = 0 passing through mm on the axis
    const pointOnPlane = new THREE.Vector3()
    this.bbox.getCenter(pointOnPlane)
    pointOnPlane.setComponent(AXIS_INDEX[this.axis], this.mm)
    this.plane.setFromNormalAndCoplanarPoint(n, pointOnPlane)

    this.viewer.setClippingPlanes([this.plane])
    this.showHelper()

    if (this.caps) {
      if (this.stencilMeshes.length === 0) this.buildCaps()
      this.placeCap()
    } else {
      this.teardownCaps()
    }
  }

  // ---- stencil caps -------------------------------------------------

  private buildCaps(): void {
    for (const mesh of this.viewer.getPartMeshes().values()) {
      const parent = mesh.parent
      if (!parent) continue
      for (const [side, op] of [
        [THREE.BackSide, THREE.IncrementWrapStencilOp],
        [THREE.FrontSide, THREE.DecrementWrapStencilOp],
      ] as const) {
        const mat = new THREE.MeshBasicMaterial()
        mat.depthWrite = false
        mat.depthTest = false
        mat.colorWrite = false
        mat.stencilWrite = true
        mat.stencilFunc = THREE.AlwaysStencilFunc
        mat.side = side
        mat.clippingPlanes = [this.plane]
        mat.stencilFail = op
        mat.stencilZFail = op
        mat.stencilZPass = op
        const sm = new THREE.Mesh(mesh.geometry, mat)
        sm.renderOrder = 1
        parent.add(sm)
        this.stencilMeshes.push(sm)
      }
    }

    const size = this.bbox.getSize(new THREE.Vector3()).length() * 1.5
    const capMat = new THREE.MeshStandardMaterial({
      color: CAP_COLOR,
      metalness: 0.1,
      roughness: 0.75,
      stencilWrite: true,
      stencilRef: 0,
      stencilFunc: THREE.NotEqualStencilFunc,
      stencilFail: THREE.ReplaceStencilOp,
      stencilZFail: THREE.ReplaceStencilOp,
      stencilZPass: THREE.ReplaceStencilOp,
      side: THREE.DoubleSide,
      // translucent in the see-through styles: one pass, as for the faces
      forceSinglePass: true,
    })
    this.capMesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), capMat)
    this.capMesh.renderOrder = 1.1
    const renderer = this.viewer.renderer
    this.capMesh.onAfterRender = () => renderer.clearStencil()
    this.viewer.scene.add(this.capMesh)
    this.styleCap()
  }

  /** opaque cap in the shaded styles, translucent in the see-through ones (see the file comment) */
  private styleCap(): void {
    const mat = this.capMesh?.material as THREE.MeshStandardMaterial | undefined
    if (!mat) return
    const see = this.viewer.seeThrough
    if (mat.transparent !== see) {
      mat.transparent = see
      mat.needsUpdate = true // a program parameter (OPAQUE): three does not notice by itself
    }
    mat.opacity = see ? CAP_SEE_THROUGH_OPACITY : 1
    mat.depthWrite = !see
  }

  private placeCap(): void {
    if (!this.capMesh) return
    const po = new THREE.Vector3()
    this.plane.coplanarPoint(po)
    this.capMesh.position.copy(po)
    this.capMesh.lookAt(po.clone().sub(this.plane.normal))
  }

  private teardownCaps(): void {
    for (const sm of this.stencilMeshes) {
      sm.parent?.remove(sm)
      ;(sm.material as THREE.Material).dispose() // geometry is shared with the part mesh
    }
    this.stencilMeshes = []
    if (this.capMesh) {
      this.viewer.scene.remove(this.capMesh)
      this.capMesh.geometry.dispose()
      ;(this.capMesh.material as THREE.Material).dispose()
      this.capMesh = null
    }
  }

  /**
   * The plane shown as a thin frame around the model's cross-section (the
   * box's extent in the other two axes, a little outside it). It used to be
   * a filled square 1.5 times the model's diagonal, which drew the eye away
   * from the cut.
   */
  private showHelper(): void {
    this.removeHelper()
    const i = AXIS_INDEX[this.axis]
    const [u, v] = [0, 1, 2].filter((k) => k !== i)
    const lo = this.bbox.min
    const hi = this.bbox.max
    const pad = 0.03 * this.bbox.getSize(new THREE.Vector3()).length()
    const at = this.mm
    const corners = [
      [lo.getComponent(u) - pad, lo.getComponent(v) - pad],
      [hi.getComponent(u) + pad, lo.getComponent(v) - pad],
      [hi.getComponent(u) + pad, hi.getComponent(v) + pad],
      [lo.getComponent(u) - pad, hi.getComponent(v) + pad],
    ].map(([a, b]) => {
      const p = new THREE.Vector3()
      p.setComponent(i, at)
      p.setComponent(u, a)
      p.setComponent(v, b)
      return p
    })
    const geo = new THREE.BufferGeometry().setFromPoints(corners)
    const mat = new THREE.LineBasicMaterial({ color: palette().sectionFrame, transparent: true, opacity: FRAME_OPACITY })
    this.helper = new THREE.LineLoop(geo, mat)
    this.helper.name = 'section-frame'
    this.viewer.scene.add(this.helper)
  }

  private removeHelper(): void {
    if (this.helper) {
      this.viewer.scene.remove(this.helper)
      this.helper.geometry.dispose()
      ;(this.helper.material as THREE.Material).dispose()
      this.helper = null
    }
  }
}
