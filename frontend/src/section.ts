/** Section (clipping plane) tool.
 *
 * Uncapped clipping — the model is hollow at the cut. Stencil caps are a
 * known-fragile three.js technique (breaks across versions); they can be added
 * later behind this same interface. three.js version is pinned in package.json.
 */
import * as THREE from 'three'
import type { Viewer } from './viewer'

export type Axis = 'X' | 'Y' | 'Z'

const NORMALS: Record<Axis, THREE.Vector3> = {
  X: new THREE.Vector3(-1, 0, 0),
  Y: new THREE.Vector3(0, -1, 0),
  Z: new THREE.Vector3(0, 0, -1),
}

export class SectionTool {
  enabled = false
  axis: Axis = 'X'
  /** 0..1 position across the model bbox along the axis */
  position = 0.5
  flip = false

  private viewer: Viewer
  private plane = new THREE.Plane(NORMALS.X.clone(), 0)
  private helper: THREE.PlaneHelper | null = null
  private bbox = new THREE.Box3()

  constructor(viewer: Viewer) {
    this.viewer = viewer
    viewer.renderer.localClippingEnabled = true
  }

  setModelBBox(min: number[], max: number[]): void {
    this.bbox.set(new THREE.Vector3(...min), new THREE.Vector3(...max))
    this.update()
  }

  update(): void {
    if (!this.enabled) {
      this.viewer.setClippingPlanes([])
      this.removeHelper()
      return
    }
    const n = NORMALS[this.axis].clone()
    if (this.flip) n.negate()

    const axisIdx = { X: 0, Y: 1, Z: 2 }[this.axis]
    const lo = this.bbox.min.getComponent(axisIdx)
    const hi = this.bbox.max.getComponent(axisIdx)
    const coord = lo + (hi - lo) * this.position
    // plane: n·p + d = 0 passing through coord on the axis
    const pointOnPlane = new THREE.Vector3()
    this.bbox.getCenter(pointOnPlane)
    pointOnPlane.setComponent(axisIdx, coord)
    this.plane.setFromNormalAndCoplanarPoint(n, pointOnPlane)

    this.viewer.setClippingPlanes([this.plane])
    this.showHelper()
  }

  private showHelper(): void {
    this.removeHelper()
    const size = this.bbox.getSize(new THREE.Vector3()).length() * 0.75
    this.helper = new THREE.PlaneHelper(this.plane, size, 0xffd060)
    ;(this.helper.material as THREE.Material).opacity = 0.15
    this.viewer.scene.add(this.helper)
  }

  private removeHelper(): void {
    if (this.helper) {
      this.viewer.scene.remove(this.helper)
      this.helper.dispose()
      this.helper = null
    }
  }
}
