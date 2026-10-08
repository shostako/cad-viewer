import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { TrackballControls } from 'three/examples/jsm/controls/TrackballControls.js'
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js'
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import type { ModelData, PartData } from './model'

const DEFAULT_PART_COLOR = 0x8fb4d8
const EDGE_COLOR = 0x20262e
/** loose curves (parts with no faces) — the dark edge color would vanish on the background */
const CURVE_COLOR = 0xe0b050
const WORLD_UP = new THREE.Vector3(0, 0, 1)
/**
 * Keep the turntable camera this far (rad, ~0.06 deg) from the poles: lookAt
 * with up=Z degenerates there. The top / bottom presets stop at the same
 * margin, so a key turn right after them doesn't snap.
 */
const POLE_MARGIN = 1e-3

/**
 * How mouse drags and arrow keys rotate the view.
 * - turntable: world Z stays up on screen (CAD default; can't roll over the top)
 * - free: tumble in any direction, including over the top (trackball)
 */
export type RotateMode = 'turntable' | 'free'

export type ViewPreset = 'front' | 'back' | 'right' | 'left' | 'top' | 'bottom' | 'iso'

/** camera direction (from target) and screen-up for each standard view (Z-up world) */
const PRESETS: Record<ViewPreset, { dir: [number, number, number]; up: [number, number, number] }> = {
  front: { dir: [0, -1, 0], up: [0, 0, 1] },
  back: { dir: [0, 1, 0], up: [0, 0, 1] },
  right: { dir: [1, 0, 0], up: [0, 0, 1] },
  left: { dir: [-1, 0, 0], up: [0, 0, 1] },
  // top / bottom: +X stays to the right, as on a drawing
  top: { dir: [0, 0, 1], up: [0, 1, 0] },
  bottom: { dir: [0, 0, -1], up: [0, -1, 0] },
  iso: { dir: [1, -1, 1], up: [0, 0, 1] },
}

export class Viewer {
  readonly scene = new THREE.Scene()
  readonly camera: THREE.PerspectiveCamera
  readonly renderer: THREE.WebGLRenderer
  /** turntable controls (world Z up) */
  readonly controls: OrbitControls
  /** free-rotation controls; enabled only in 'free' rotate mode */
  readonly trackball: TrackballControls
  /** spin the view around the vertical axis (deg/s) when autoRotate is on */
  autoRotate = false
  autoRotateSpeed = 30
  readonly labelRenderer: CSS2DRenderer
  /** overlay group for dimensions / markers / annotations */
  readonly overlay = new THREE.Group()
  private modelGroup = new THREE.Group()
  private gridHelper: THREE.GridHelper | null = null
  private _gridVisible = true
  private _rotateMode: RotateMode = 'turntable'
  /** pointers held down on the canvas — auto-rotate pauses so it doesn't fight the user */
  private heldPointers = new Set<number>()
  private lineMaterials: LineMaterial[] = []
  private partGroups = new Map<number, THREE.Group>()
  private partMeshes = new Map<number, THREE.Mesh>()

  constructor(container: HTMLElement) {
    this.scene.background = new THREE.Color(0x1d2126)

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1e6)
    // CAD convention: Z-up. Keep world coordinates identical to server B-rep coords.
    this.camera.up.set(0, 0, 1)
    this.camera.position.set(80, -60, 50)

    // stencil: needed for section caps (three defaults stencil:false since r163)
    this.renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    container.appendChild(this.renderer.domElement)

    this.labelRenderer = new CSS2DRenderer()
    this.labelRenderer.domElement.style.position = 'absolute'
    this.labelRenderer.domElement.style.inset = '0'
    this.labelRenderer.domElement.style.pointerEvents = 'none'
    container.appendChild(this.labelRenderer.domElement)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.trackball = new TrackballControls(this.camera, this.renderer.domElement)
    // TrackballControls turns ~1 rad per half-width drag at speed 1; 4 roughly
    // matches the turntable's feel (one screen height = one turn)
    this.trackball.rotateSpeed = 4
    this.trackball.zoomSpeed = 1.2
    this.trackball.panSpeed = 0.8
    this.trackball.enabled = false
    // Track held pointers ourselves rather than the controls' start/end:
    // TrackballControls (three r185) handles pointercancel without an 'end',
    // so a touch/pen gesture cancelled by the OS would leave auto-rotate
    // paused for good. Release events are taken on window so a pointer let go
    // outside the canvas still counts.
    const canvas = this.renderer.domElement
    canvas.addEventListener('pointerdown', (e) => {
      this.heldPointers.add(e.pointerId)
    })
    const release = (e: PointerEvent) => {
      this.heldPointers.delete(e.pointerId)
    }
    window.addEventListener('pointerup', release)
    window.addEventListener('pointercancel', release)
    canvas.addEventListener('lostpointercapture', release)
    // a button held while the window loses focus (Alt+Tab) never sends pointerup
    window.addEventListener('blur', () => this.heldPointers.clear())

    // CAD-ish lighting: hemisphere + key + fill
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2))
    const key = new THREE.DirectionalLight(0xffffff, 1.4)
    key.position.set(1, -1.5, 2)
    this.scene.add(key)
    const fill = new THREE.DirectionalLight(0xffffff, 0.5)
    fill.position.set(-1.5, 1, -1)
    this.scene.add(fill)

    this.scene.add(this.modelGroup)
    this.scene.add(this.overlay)

    const resize = () => {
      const w = container.clientWidth
      const h = container.clientHeight
      this.camera.aspect = w / h
      this.camera.updateProjectionMatrix()
      this.renderer.setSize(w, h)
      this.labelRenderer.setSize(w, h)
      for (const m of this.lineMaterials) m.resolution.set(w, h)
      this.trackball.handleResize()
    }
    new ResizeObserver(resize).observe(container)
    resize()

    let last = performance.now()
    this.renderer.setAnimationLoop((now: number) => {
      // clamp: a background tab resumes with a huge gap, which would jump the spin
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      if (this.autoRotate && this.heldPointers.size === 0 && dt > 0) {
        this.rotateView((this.autoRotateSpeed * Math.PI / 180) * dt, 0)
      }
      this.activeControls().update()
      this.renderer.render(this.scene, this.camera)
      this.labelRenderer.render(this.scene, this.camera)
    })
  }

  getPartMesh(partId: number): THREE.Mesh | undefined {
    return this.partMeshes.get(partId)
  }

  getPartMeshes(): ReadonlyMap<number, THREE.Mesh> {
    return this.partMeshes
  }

  /**
   * Bounds used to frame the model. Bodies only, when there are any: loose
   * curves in a file are often construction lines (e.g. coordinate axes) far
   * larger than the part, and framing them would shrink the part to a speck.
   */
  modelBBox(): THREE.Box3 {
    const box = new THREE.Box3()
    for (const [id, mesh] of this.partMeshes) {
      if (mesh.geometry.index?.count && this.partGroups.get(id)?.visible !== false) {
        box.expandByObject(mesh)
      }
    }
    return box.isEmpty() ? new THREE.Box3().setFromObject(this.modelGroup) : box
  }

  /** Thickness heatmap: red below threshold, grading to base blue when thick. */
  setThicknessColors(thickness: Map<number, Float32Array>, threshold: number): void {
    for (const [partId, t] of thickness) {
      const mesh = this.partMeshes.get(partId)
      if (!mesh) continue
      // contract: one thickness value per display vertex
      if (t.length !== mesh.geometry.getAttribute('position').count) {
        console.warn(`thickness length mismatch for part ${partId} — skipped`)
        continue
      }
      const n = t.length
      const colors = new Float32Array(n * 3)
      for (let i = 0; i < n; i++) {
        const v = t[i]
        let r = 0.55
        let g = 0.62
        let b = 0.75 // no-data: neutral gray-blue
        if (v > 0) {
          const u = Math.min(v / (2 * threshold), 1)
          if (u < 0.5) {
            // thin: red -> yellow
            const k = u / 0.5
            r = 1
            g = 0.15 + 0.75 * k
            b = 0.08
          } else {
            // ok: yellow -> steel blue
            const k = (u - 0.5) / 0.5
            r = 1 - 0.65 * k
            g = 0.9 - 0.35 * k
            b = 0.08 + 0.72 * k
          }
        }
        colors[i * 3] = r
        colors[i * 3 + 1] = g
        colors[i * 3 + 2] = b
      }
      mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      const mat = mesh.material as THREE.MeshStandardMaterial
      if (!mesh.userData.baseColor) mesh.userData.baseColor = mat.color.clone()
      mat.vertexColors = true
      mat.color.set(0xffffff)
      mat.needsUpdate = true
    }
  }

  clearThicknessColors(): void {
    for (const mesh of this.partMeshes.values()) {
      const mat = mesh.material as THREE.MeshStandardMaterial
      if (mat.vertexColors) {
        mat.vertexColors = false
        if (mesh.userData.baseColor) mat.color.copy(mesh.userData.baseColor)
        mat.needsUpdate = true
      }
    }
  }

  /** Apply clipping planes to every model material (mesh + edge lines). */
  setClippingPlanes(planes: THREE.Plane[]): void {
    const list = planes.length ? planes : null
    this.modelGroup.traverse((o) => {
      if (o instanceof THREE.Mesh || o instanceof LineSegments2) {
        ;(o.material as THREE.Material).clippingPlanes = list
      }
    })
  }

  /** Create a screen-space label attached to a 3D point. */
  makeLabel(text: string, position: THREE.Vector3, className = 'dim-label'): CSS2DObject {
    const div = document.createElement('div')
    div.className = className
    div.textContent = text
    const label = new CSS2DObject(div)
    label.position.copy(position)
    return label
  }

  disposeOverlayObject(obj: THREE.Object3D): void {
    this.overlay.remove(obj)
    obj.traverse((o) => {
      if (o instanceof THREE.Mesh || o instanceof THREE.Line || o instanceof LineSegments2) {
        o.geometry.dispose()
        ;(o.material as THREE.Material).dispose()
      }
      if (o instanceof CSS2DObject) o.element.remove()
    })
  }

  setModel(model: ModelData): void {
    this.clearModel()
    for (const part of model.parts) this.addPart(part)
    this.fitToView()
  }

  private addPart(part: PartData): void {
    const group = new THREE.Group()
    group.name = part.name
    group.userData.partId = part.id

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(part.positions, 3))
    geo.setAttribute('normal', new THREE.BufferAttribute(part.normals, 3))
    geo.setIndex(new THREE.BufferAttribute(part.indices, 1))

    const color = part.color
      ? new THREE.Color().setRGB(part.color[0], part.color[1], part.color[2])
      : new THREE.Color(DEFAULT_PART_COLOR)
    const mat = new THREE.MeshStandardMaterial({
      color,
      metalness: 0.1,
      roughness: 0.65,
      side: THREE.DoubleSide,
      // pull faces slightly back so overlaid edges win the depth fight
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    })
    const mesh = new THREE.Mesh(geo, mat)
    group.add(mesh)
    this.partMeshes.set(part.id, mesh)

    if (part.edges.length >= 6) {
      const edgeGeo = new LineSegmentsGeometry()
      // pass the typed array directly — Array.from() would box millions of
      // floats into JS numbers on large assemblies (memory blowup / tab freeze)
      edgeGeo.setPositions(part.edges)
      const curveOnly = part.indices.length === 0
      const edgeMat = new LineMaterial({ color: curveOnly ? CURVE_COLOR : EDGE_COLOR, linewidth: 1.5 })
      const size = new THREE.Vector2()
      this.renderer.getSize(size)
      edgeMat.resolution.copy(size)
      this.lineMaterials.push(edgeMat)
      group.add(new LineSegments2(edgeGeo, edgeMat))
    }

    this.partGroups.set(part.id, group)
    this.modelGroup.add(group)
  }

  setPartVisible(partId: number, visible: boolean): void {
    const g = this.partGroups.get(partId)
    if (g) g.visible = visible
  }

  clearModel(): void {
    for (const child of [...this.modelGroup.children]) {
      this.modelGroup.remove(child)
      child.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof LineSegments2) {
          o.geometry.dispose()
          ;(o.material as THREE.Material).dispose()
        }
      })
    }
    this.partGroups.clear()
    this.partMeshes.clear()
    this.lineMaterials = []
    for (const child of [...this.overlay.children]) this.disposeOverlayObject(child)
    if (this.gridHelper) {
      this.scene.remove(this.gridHelper)
      this.gridHelper.dispose()
      this.gridHelper = null
    }
  }

  fitToView(): void {
    const box = this.modelBBox()
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z)
    const dist = maxDim / (2 * Math.tan((this.camera.fov * Math.PI) / 360))

    const dir = new THREE.Vector3(1, -1, 0.7).normalize()
    this.stopInertia()
    this.camera.up.copy(WORLD_UP)
    this.camera.position.copy(center).addScaledVector(dir, dist * 1.5)
    this.camera.near = maxDim / 1000
    this.camera.far = maxDim * 100
    this.camera.updateProjectionMatrix()
    this.setTarget(center)

    // ground grid sized to the model
    if (this.gridHelper) {
      this.scene.remove(this.gridHelper)
      this.gridHelper.dispose()
    }
    const gridSize = Math.pow(10, Math.ceil(Math.log10(maxDim * 2)))
    this.gridHelper = new THREE.GridHelper(gridSize, 20, 0x3a4250, 0x2a3038)
    // GridHelper lies in XZ; rotate into XY plane for Z-up world
    this.gridHelper.rotation.x = Math.PI / 2
    this.gridHelper.position.set(center.x, center.y, box.min.z)
    this.gridHelper.visible = this._gridVisible
    this.scene.add(this.gridHelper)
  }

  // ---- grid ---------------------------------------------------------------

  get gridVisible(): boolean {
    return this._gridVisible
  }

  set gridVisible(v: boolean) {
    this._gridVisible = v
    if (this.gridHelper) this.gridHelper.visible = v
  }

  // ---- view navigation ----------------------------------------------------

  get rotateMode(): RotateMode {
    return this._rotateMode
  }

  /**
   * Point the view orbits around. Each control scheme keeps its own copy (a
   * trackball pan moves only the trackball's), so read the active one and
   * hand it over on a mode switch.
   */
  get target(): THREE.Vector3 {
    return this.activeControls().target
  }

  setRotateMode(mode: RotateMode): void {
    if (mode === this._rotateMode) return
    this.stopInertia()
    const target = this.target.clone() // from the scheme being switched away from
    this._rotateMode = mode
    this.controls.target.copy(target)
    this.trackball.target.copy(target)
    this.trackball.enabled = mode === 'free'
    this.controls.enabled = mode === 'turntable'
    if (mode === 'turntable') {
      // the turntable assumes Z up: undo any roll left over from free
      // rotation, and step off the poles where lookAt degenerates
      this.camera.up.copy(WORLD_UP)
      this.rotateView(0, 0)
    }
    this.camera.lookAt(target)
    this.activeControls().update()
  }

  /**
   * Orbit the camera around the target. azimuth turns about the vertical axis,
   * elevation tilts up/down (radians). Positive values move the CAMERA right /
   * up, so the face on that side of the model comes into view.
   */
  rotateView(azimuth: number, elevation: number): void {
    const target = this.target
    const offset = this.camera.position.clone().sub(target)
    const r = offset.length()
    if (r === 0) return
    if (this._rotateMode === 'turntable') {
      // camera right = +azimuth around +Z (counter-clockwise seen from above)
      offset.applyAxisAngle(WORLD_UP, azimuth)
      const phi = THREE.MathUtils.clamp(
        Math.acos(THREE.MathUtils.clamp(offset.z / r, -1, 1)) - elevation,
        POLE_MARGIN,
        Math.PI - POLE_MARGIN,
      )
      const theta = Math.atan2(offset.y, offset.x)
      offset.set(r * Math.sin(phi) * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi))
    } else {
      const { right, up } = this.screenAxes()
      const q = new THREE.Quaternion()
        .setFromAxisAngle(up, azimuth)
        .multiply(new THREE.Quaternion().setFromAxisAngle(right, -elevation))
      offset.applyQuaternion(q)
      this.camera.up.copy(up).applyQuaternion(q).normalize()
    }
    this.camera.position.copy(target).add(offset)
    this.camera.lookAt(target)
  }

  /** Slide the view across the screen; dx/dy are fractions of the view height. */
  pan(dx: number, dy: number): void {
    const { right, up } = this.screenAxes()
    const dist = this.camera.position.distanceTo(this.target)
    const viewHeight = 2 * dist * Math.tan((this.camera.fov * Math.PI) / 360)
    const move = right.multiplyScalar(dx * viewHeight).add(up.multiplyScalar(dy * viewHeight))
    this.camera.position.add(move)
    this.setTarget(this.target.clone().add(move))
  }

  /** factor < 1 moves closer, > 1 moves away */
  zoom(factor: number): void {
    const offset = this.camera.position.clone().sub(this.target)
    const minDist = this.camera.near * 2
    offset.setLength(Math.max(offset.length() * factor, minDist))
    this.camera.position.copy(this.target).add(offset)
  }

  /** Jump to a standard view, keeping the current target and distance. */
  setView(preset: ViewPreset): void {
    this.stopInertia()
    const p = PRESETS[preset]
    const dir = new THREE.Vector3(...p.dir).normalize()
    const dist = this.camera.position.distanceTo(this.target) || 1
    if (this._rotateMode === 'turntable') {
      this.camera.up.copy(WORLD_UP)
      if (Math.abs(dir.z) > 0.999) {
        // Straight down/up is the turntable's pole, where lookAt with up=Z
        // has no answer. Step off it so the screen-up lands on the preset's
        // up (+X stays right): screen-up ~ -sign(dir.z) * nudge, hence the sign.
        dir.addScaledVector(new THREE.Vector3(...p.up), -Math.sign(dir.z) * POLE_MARGIN).normalize()
      }
    } else {
      this.camera.up.set(...p.up)
    }
    this.camera.position.copy(this.target).addScaledVector(dir, dist)
    this.camera.lookAt(this.target)
    this.activeControls().update()
  }

  private activeControls(): OrbitControls | TrackballControls {
    return this._rotateMode === 'free' ? this.trackball : this.controls
  }

  private setTarget(t: THREE.Vector3): void {
    this.controls.target.copy(t)
    this.trackball.target.copy(t)
    this.camera.lookAt(t)
    this.activeControls().update()
  }

  /** camera right / up directions on screen, orthonormal */
  private screenAxes(): { right: THREE.Vector3; up: THREE.Vector3 } {
    const forward = this.target.clone().sub(this.camera.position).normalize()
    const right = forward.clone().cross(this.camera.up).normalize()
    if (right.lengthSq() < 1e-12) right.set(1, 0, 0) // looking along up: pick any
    const up = right.clone().cross(forward).normalize()
    return { right, up }
  }

  /**
   * End the coast of a drag that just ended. Without this, a preset view or
   * fit set during the coast drifts away as the leftover spin is applied.
   * Callers overwrite the camera right after, so how the coast ends doesn't
   * matter as long as nothing is left pending.
   */
  private stopInertia(): void {
    // only the active scheme: update() on the inactive one would re-aim the
    // camera at its stale target (and OrbitControls assumes Z up)
    if (this._rotateMode === 'turntable') {
      if (this.controls.enableDamping) {
        // OrbitControls has no public "stop": with damping off, update()
        // applies the pending delta in one step (fast-forwards the coast)
        // and clears it
        this.controls.enableDamping = false
        this.controls.update()
        this.controls.enableDamping = true
      }
      return
    }
    // TrackballControls keeps its coast in private fields (three r185, which
    // package.json pins). Touch them only if they are there: if a three update
    // renames them, a stale coast is far better than every preset throwing.
    const tb = this.trackball as unknown as Record<string, unknown>
    if (typeof tb._lastAngle === 'number') tb._lastAngle = 0
    for (const [from, to] of [
      ['_moveCurr', '_movePrev'],
      ['_panEnd', '_panStart'],
      ['_zoomEnd', '_zoomStart'],
    ]) {
      const src = tb[from]
      const dst = tb[to]
      if (src instanceof THREE.Vector2 && dst instanceof THREE.Vector2) dst.copy(src)
    }
  }
}
