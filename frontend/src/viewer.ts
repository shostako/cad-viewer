import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { TrackballControls } from 'three/examples/jsm/controls/TrackballControls.js'
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js'
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { draftColors, draftColorsFlat, draftSine, triangleDraftSine, windingSign } from './draft'
import { MIN_FREE, type ScreenRect } from './freearea'
import type { ModelData, PartData } from './model'
import { paintLabels, type ExportBackground } from './snapshot'
import { thicknessColors } from './thickness'

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
/** share of the limiting dimension of the fit area a fit fills; the rest is margin */
const FIT_FILL = 0.88
/**
 * The furthest (share of the canvas width / height) a fit moves the view
 * centre from the canvas middle: a free area at least MIN_FREE wide has its
 * centre within this of the middle. A resize clamps to the same bound.
 */
const MAX_VIEW_SHIFT = (1 - MIN_FREE) / 2
/** direction (target -> camera) a freshly loaded model is seen from */
const LOAD_VIEW_DIR = new THREE.Vector3(1, -1, 0.7).normalize()
/** near = framed radius / NEAR_DIV, far = radius * FAR_MUL: the same 1e5 depth range as before, relative to the model */
const NEAR_DIV = 500
const FAR_MUL = 200
/** the wheel stops this many near-plane distances short of the point it zooms to */
const MIN_ZOOM_NEARS = 4
/** zooming out stops at this share of the far plane (camera to target) */
const MAX_ZOOM_FAR = 0.25
/** double-click pivot: slide duration, and how long the marker stays */
const PIVOT_MS = 250
const PIVOT_MARKER_MS = 1000
/** a press that moves further than this (px) is a drag, not a click */
export const DRAG_PX = 5
/** PNG export with 背景=白 */
const WHITE = new THREE.Color(0xffffff)
const GRID_DIVISIONS = 20
/** ground grid: centre lines, other lines */
const GRID_COLORS: [number, number] = [0x3a4250, 0x2a3038]
/** the same grid on a white export: the dark one would print as heavy lines */
const GRID_COLORS_ON_WHITE: [number, number] = [0xc0c6ce, 0xdde1e6]
/**
 * Parallel projection: the frustum half-height is this constant and the
 * camera's zoom carries the scale (visible half-height h = ORTHO_TOP / zoom),
 * so every size change, ours and the controls', is a zoom change.
 */
const ORTHO_TOP = 1
/** the parallel camera's depth range covers the model's sphere enlarged by this */
const DEPTH_PAD = 1.1
/** TrackballControls pan speed (perspective; normalised per frame in parallel) */
const TRACKBALL_PAN = 0.8

/**
 * How the model is drawn (表示スタイル); see setDisplayStyle.
 * - shaded-edges: faces and the B-rep edge lines (the default)
 * - shaded: faces only
 * - wireframe: edge lines only (the triangles for parts without edge lines, e.g. STL)
 * - xray: see-through faces with the edge lines, to look inside a mold assembly
 */
export const DISPLAY_STYLES = ['shaded-edges', 'shaded', 'wireframe', 'xray'] as const
export type DisplayStyle = (typeof DISPLAY_STYLES)[number]
/** face opacity in 半透明: a pin behind two walls of a block still shows */
const XRAY_OPACITY = 0.3
/**
 * Least WCAG relative luminance of an edge line in the see-through styles:
 * 3.5:1 against the background #1d2126 (luminance 0.015). The dark EDGE_COLOR
 * is almost the background, so with the faces gone or see-through it vanishes.
 */
const SEE_THROUGH_EDGE_MIN_LUMINANCE = 0.18

/**
 * How mouse drags and arrow keys rotate the view.
 * - turntable: world Z stays up on screen (CAD default; can't roll over the top)
 * - free: tumble in any direction, including over the top (trackball)
 */
export type RotateMode = 'turntable' | 'free'

export type ViewPreset = 'front' | 'back' | 'right' | 'left' | 'top' | 'bottom' | 'iso'

/**
 * - perspective: 透視 (nearer is larger)
 * - orthographic: 平行 (parallel edges stay parallel, sizes do not depend on
 *   depth: what a 2D drawing shows)
 */
export type Projection = 'perspective' | 'orthographic'

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
  private readonly persp: THREE.PerspectiveCamera
  /** frustum ±aspect x ±ORTHO_TOP; its distance to the target means nothing (keepOrthoDepth) */
  private readonly ortho = new THREE.OrthographicCamera(-1, 1, ORTHO_TOP, -ORTHO_TOP, 0.1, 1e6)
  private _projection: Projection = 'perspective'
  /**
   * Everything the scene can draw (all parts, hidden ones and loose curves
   * included, and the grid square), padded: the parallel camera keeps it all
   * between its near and far planes.
   */
  private depthSphere = new THREE.Sphere(new THREE.Vector3(), 1)
  private frameListeners: (() => void)[] = []
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
  /** size and placement of the current grid, so an export can build a recoloured copy */
  private gridSpec: { size: number; x: number; y: number; z: number } | null = null
  private _gridVisible = true
  private _rotateMode: RotateMode = 'turntable'
  /** pointers held down on the canvas — auto-rotate pauses so it doesn't fight the user */
  private heldPointers = new Set<number>()
  private lineMaterials: LineMaterial[] = []
  private partGroups = new Map<number, THREE.Group>()
  private partMeshes = new Map<number, THREE.Mesh>()
  /** per-triangle copies of mesh-format parts while the draft colouring is on */
  private flatCopies = new Map<number, THREE.Mesh>()
  private _displayStyle: DisplayStyle = 'shaded-edges'
  private styleListeners: (() => void)[] = []
  /** face parts that have edge lines: the lines, and their colour in the see-through styles */
  private partEdges = new Map<number, { lines: LineSegments2; material: LineMaterial; seeThroughColor: THREE.Color }>()
  private raycaster = new THREE.Raycaster()
  /** running double-click pivot slide (camera and target both move) */
  private viewAnim: {
    from: THREE.Vector3
    to: THREE.Vector3
    fromTarget: THREE.Vector3
    toTarget: THREE.Vector3
    start: number
  } | null = null
  private pivotMarker: CSS2DObject | null = null
  private pivotMarkerTimer: ReturnType<typeof setTimeout> | undefined
  private container: HTMLElement
  /**
   * The part of the canvas (canvas CSS px) a fit frames the model in, or null
   * for the whole canvas. modelW x modelH: the model's bounding box as seen
   * from the fit's direction (world units along the screen's right and up).
   * Read once per fit: later panel changes do not re-fit.
   */
  fitArea: (modelW: number, modelH: number) => ScreenRect | null = () => null
  /**
   * Canvas centre minus view centre (CSS px), set by each fit. The projection
   * is shifted by this (setViewOffset) so the orbit target, which stays on the
   * model, shows at the centre of the fit area: rotation, presets, zoom and
   * the double-click pivot all keep working around it. Kept in px across
   * resizes (the panels are fixed-size and anchored to the window edges).
   */
  private viewShift = new THREE.Vector2()
  /** canvas CSS size last applied by fitToContainer */
  private cssSize = new THREE.Vector2()

  constructor(container: HTMLElement) {
    this.scene.background = new THREE.Color(0x1d2126)

    this.persp = new THREE.PerspectiveCamera(50, 1, 0.1, 1e6)
    // CAD convention: Z-up. Keep world coordinates identical to server B-rep coords.
    // Set before the controls are built: OrbitControls takes its Z-up frame
    // from the camera it is made with, once (three r185), and keeps it when
    // its camera is swapped for the parallel one.
    this.persp.up.set(0, 0, 1)
    this.ortho.up.set(0, 0, 1)
    this.persp.position.set(80, -60, 50)

    // stencil: needed for section caps (three defaults stencil:false since r163)
    this.renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    container.appendChild(this.renderer.domElement)

    this.labelRenderer = new CSS2DRenderer()
    this.labelRenderer.domElement.style.position = 'absolute'
    this.labelRenderer.domElement.style.inset = '0'
    this.labelRenderer.domElement.style.pointerEvents = 'none'
    container.appendChild(this.labelRenderer.domElement)

    this.controls = new OrbitControls(this.persp, this.renderer.domElement)
    this.controls.enableDamping = true
    this.trackball = new TrackballControls(this.persp, this.renderer.domElement)
    // TrackballControls turns ~1 rad per half-width drag at speed 1; 4 roughly
    // matches the turntable's feel (one screen height = one turn)
    this.trackball.rotateSpeed = 4
    this.trackball.zoomSpeed = 1.2
    this.trackball.panSpeed = TRACKBALL_PAN
    this.trackball.enabled = false
    this.applyOrthoZoomLimits()
    // Track held pointers ourselves rather than the controls' start/end:
    // TrackballControls (three r185) handles pointercancel without an 'end',
    // so a touch/pen gesture cancelled by the OS would leave auto-rotate
    // paused for good. Release events are taken on window so a pointer let go
    // outside the canvas still counts.
    const canvas = this.renderer.domElement
    // where each held pointer went down: a drag that starts mid-pivot finishes
    // the slide first, so it orbits the new centre. A click does not: the
    // clicks of a second double-click must pick from the pose on screen.
    const downAt = new Map<number, [number, number]>()
    canvas.addEventListener('pointerdown', (e) => {
      this.heldPointers.add(e.pointerId)
      downAt.set(e.pointerId, [e.clientX, e.clientY])
    })
    canvas.addEventListener('pointermove', (e) => {
      const d = downAt.get(e.pointerId)
      if (d && this.viewAnim && Math.hypot(e.clientX - d[0], e.clientY - d[1]) > DRAG_PX) {
        this.finishViewAnim()
      }
    })
    const release = (e: PointerEvent) => {
      this.heldPointers.delete(e.pointerId)
      downAt.delete(e.pointerId)
    }
    window.addEventListener('pointerup', release)
    window.addEventListener('pointercancel', release)
    canvas.addEventListener('lostpointercapture', release)
    // a button held while the window loses focus (Alt+Tab) never sends pointerup
    window.addEventListener('blur', () => {
      this.heldPointers.clear()
      downAt.clear()
    })

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

    this.container = container
    new ResizeObserver(() => this.fitToContainer()).observe(container)
    this.fitToContainer()
    this.watchPixelRatio()

    let last = performance.now()
    this.renderer.setAnimationLoop((now: number) => {
      // clamp: a background tab resumes with a huge gap, which would jump the spin
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      if (this.viewAnim) this.stepViewAnim(now)
      else if (this.autoRotate && this.heldPointers.size === 0 && dt > 0) {
        this.rotateView((this.autoRotateSpeed * Math.PI / 180) * dt, 0)
      }
      this.activeControls().update()
      this.prepareCamera()
      this.renderer.render(this.scene, this.camera)
      this.labelRenderer.render(this.scene, this.camera)
      for (const fn of this.frameListeners) fn()
    })
  }

  /** the camera in use: perspective or parallel (setProjection) */
  get camera(): THREE.PerspectiveCamera | THREE.OrthographicCamera {
    return this._projection === 'orthographic' ? this.ortho : this.persp
  }

  get projection(): Projection {
    return this._projection
  }

  /** Called after every rendered frame (the axis triad follows the camera). */
  onFrame(fn: () => void): void {
    this.frameListeners.push(fn)
  }

  /**
   * Make the camera ready for a projection or a pick right now (straight
   * after an event, before the next frame): the parallel camera put back
   * behind everything (keepOrthoDepth), and the world matrices brought up to date.
   */
  prepareCamera(): void {
    this.keepOrthoDepth()
    this.camera.updateMatrixWorld()
  }

  /** World units per screen pixel at `at` (perspective: at that distance; parallel: everywhere). */
  worldPerPixel(at: THREE.Vector3): number {
    const h = this.halfHeight(this.camera.position.distanceTo(at))
    return (2 * h) / (this.renderer.domElement.clientHeight || 1)
  }

  /** half the visible height (world units) at `dist` from the camera; parallel: the same at any distance */
  private halfHeight(dist: number): number {
    if (this._projection === 'orthographic') return ORTHO_TOP / this.ortho.zoom
    return dist * Math.tan((this.persp.fov * Math.PI) / 360)
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

  /** whether any part has triangles (a curves-only model or an empty scene has none) */
  hasFaces(): boolean {
    for (const mesh of this.partMeshes.values()) if (mesh.geometry.index?.count) return true
    return false
  }

  /**
   * Colour a part mesh per vertex. The colour buffer is reused when it fits, so
   * dragging a slider refills it instead of allocating; the material switches
   * to vertex colours (a shader rebuild) only when it was not using them yet.
   * clippingPlanes stay on the material through that rebuild.
   */
  private applyVertexColors(mesh: THREE.Mesh, fill: (out: Float32Array) => void): void {
    const geo = mesh.geometry
    const count = geo.getAttribute('position').count
    let attr = geo.getAttribute('color') as THREE.BufferAttribute | undefined
    if (!attr || attr.count !== count || attr.itemSize !== 3) {
      attr = new THREE.BufferAttribute(new Float32Array(count * 3), 3)
      geo.setAttribute('color', attr)
    }
    fill(attr.array as Float32Array)
    attr.needsUpdate = true
    const mat = mesh.material as THREE.MeshStandardMaterial
    // once, before the colour turns white: XCAF or default colour to restore
    if (!mesh.userData.baseColor) mesh.userData.baseColor = mat.color.clone()
    if (!mat.vertexColors) {
      mat.vertexColors = true
      mat.needsUpdate = true
    }
    mat.color.set(0xffffff) // vertex colour x material colour: white passes it through
  }

  /** Thickness heatmap (thickness.ts): red to orange below the threshold, grey-blue to blue at and above it. */
  setThicknessColors(thickness: Map<number, Float32Array>, threshold: number): void {
    for (const [partId, t] of thickness) {
      const mesh = this.partMeshes.get(partId)
      if (!mesh) continue
      this.removeFlatCopy(partId) // the heatmap colours the part mesh itself
      // contract: one thickness value per display vertex
      if (t.length !== mesh.geometry.getAttribute('position').count) {
        console.warn(`thickness length mismatch for part ${partId} — skipped`)
        continue
      }
      this.applyVertexColors(mesh, (colors) => thicknessColors(t, threshold, colors))
    }
  }

  /**
   * Draft-angle colouring (draft.ts) on every part with faces. Hidden parts are
   * coloured too, so they are right when shown again; colours live on the
   * geometry, which the section's stencil meshes share but do not draw.
   * Mesh-format parts are coloured on their flat copy (see flatCopy).
   */
  setDraftColors(dir: readonly [number, number, number], requiredDeg: number): void {
    for (const [partId, mesh] of this.partMeshes) {
      if (!mesh.geometry.index?.count) continue // loose curves: nothing to colour
      if (mesh.userData.meshFormat) {
        const copy = this.flatCopy(partId, mesh)
        const positions = copy.geometry.getAttribute('position').array
        const sign = copy.userData.windingSign as 1 | -1
        this.applyVertexColors(copy, (out) => draftColorsFlat(positions, sign, dir, requiredDeg, out))
      } else {
        const normals = mesh.geometry.getAttribute('normal').array
        this.applyVertexColors(mesh, (out) => draftColors(normals, dir, requiredDeg, out))
      }
    }
  }

  /**
   * Sine of the draft angle at a point of triangle `tri` of a part (the value
   * under the cursor), by the rule the colouring on screen uses
   * (setDraftColors): a mesh-format part by the triangle's own normal from its
   * winding, times the part's winding sign, read from the flat copy the
   * colouring drew; a B-rep part by its display normals at the triangle's
   * vertices, blended with the point's barycentric `weights` (exact on a
   * planar face, where the three are the face's normal). null when the part
   * has no such triangle, or is a mesh-format part without its flat copy (the
   * draft colouring is off).
   */
  draftSineAt(
    partId: number,
    tri: number,
    weights: readonly [number, number, number],
    dir: readonly [number, number, number],
  ): number | null {
    const mesh = this.partMeshes.get(partId)
    const index = mesh?.geometry.index
    if (!mesh || !index || tri < 0 || (tri + 1) * 3 > index.count) return null
    if (mesh.userData.meshFormat) {
      const copy = this.flatCopies.get(partId)
      if (!copy) return null
      // the copy holds triangle k of the part as floats 9k .. 9k + 8 (flatCopy)
      const positions = copy.geometry.getAttribute('position').array
      return triangleDraftSine(positions, tri * 9, copy.userData.windingSign as 1 | -1, dir)
    }
    const normals = mesh.geometry.getAttribute('normal').array
    let x = 0
    let y = 0
    let z = 0
    for (let k = 0; k < 3; k++) {
      const v = index.getX(tri * 3 + k) * 3
      x += weights[k] * normals[v]
      y += weights[k] * normals[v + 1]
      z += weights[k] * normals[v + 2]
    }
    return draftSine(x, y, z, dir)
  }

  /**
   * A non-indexed copy of a mesh-format part (STL, 3MF, ...), one vertex triple
   * per triangle, drawn with flat shading and classified triangle by triangle
   * (draftColorsFlat), with the part's winding sign (windingSign).
   *
   * The display normals of those parts are averaged across edges shallower
   * than 30° (backend smooth_shade), so a large planar wall shares its corner
   * normals with the fillet next to it. Classified per vertex, the colour of
   * that corner then blends across the whole wall triangle: the top of an
   * under-drafted wall would read as enough. The triangles are the true shape
   * of a mesh file, so they are classified one by one and drawn flat. The copy
   * keeps no normals (flat shading takes the face from the screen-space
   * derivatives, facing the viewer either way), which saves a third of its
   * memory on a large STL.
   *
   * The part mesh stays in place for picking (its BVH and faceIndex) and the
   * section's stencil; it is only hidden while the copy is shown. The copy sits
   * in the part's group, so tree visibility and clipping (setClippingPlanes
   * walks the model group) apply to it too, and clearModel disposes it with
   * the group.
   */
  private flatCopy(partId: number, mesh: THREE.Mesh): THREE.Mesh {
    const have = this.flatCopies.get(partId)
    if (have) return have
    const pos = mesh.geometry.getAttribute('position').array
    const idx = mesh.geometry.index!.array
    const nTri = Math.floor(idx.length / 3)
    const P = new Float32Array(nTri * 9)
    for (let t = 0; t < nTri; t++) {
      for (let v = 0; v < 3; v++) {
        const a = idx[t * 3 + v] * 3
        P[t * 9 + v * 3] = pos[a]
        P[t * 9 + v * 3 + 1] = pos[a + 1]
        P[t * 9 + v * 3 + 2] = pos[a + 2]
      }
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(P, 3))
    const src = mesh.material as THREE.MeshStandardMaterial
    const mat = src.clone()
    // three switches to flat shading by itself for a geometry without normals
    // (WebGLPrograms); said here so the copy does not depend on that
    mat.flatShading = true
    mat.needsUpdate = true
    // the same plane objects as the part (clone() copies them), so a section
    // moved before the next setClippingPlanes still clips both alike
    mat.clippingPlanes = src.clippingPlanes
    const copy = new THREE.Mesh(geo, mat)
    copy.userData.windingSign = windingSign(P)
    copy.renderOrder = mesh.renderOrder
    mesh.parent!.add(copy)
    this.flatCopies.set(partId, copy)
    this.applyStyle(partId) // the copy is drawn in the current style, the part mesh hidden
    return copy
  }

  /** Drop the flat copy of a part (if any) and show the part mesh again. */
  private removeFlatCopy(partId: number): void {
    const copy = this.flatCopies.get(partId)
    if (!copy) return
    copy.parent?.remove(copy)
    copy.geometry.dispose()
    ;(copy.material as THREE.Material).dispose()
    this.flatCopies.delete(partId)
    this.applyStyle(partId) // the part mesh is drawn again, as the style says
  }

  /** Back to the part colours (thickness heatmap or draft colouring off). */
  clearVertexColors(): void {
    for (const partId of [...this.flatCopies.keys()]) this.removeFlatCopy(partId)
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

  /**
   * Show a new model. It is not framed here: the caller frames it with
   * frameNewModel() once this load's panels (tree, restored measurements,
   * 体積・重量 values, HUD) are on screen, so the one fit of a load keeps
   * clear of them.
   */
  setModel(model: ModelData): void {
    this.clearModel()
    for (const part of model.parts) this.addPart(part)
    this.buildGrid(this.modelBBox())
    this.updateDepthSphere()
  }

  /** depthSphere for the model just built (once per model: hiding parts must not move it) */
  private updateDepthSphere(): void {
    const box = new THREE.Box3().setFromObject(this.modelGroup)
    const g = this.gridSpec
    if (g) {
      box.expandByPoint(new THREE.Vector3(g.x - g.size / 2, g.y - g.size / 2, g.z))
      box.expandByPoint(new THREE.Vector3(g.x + g.size / 2, g.y + g.size / 2, g.z))
    }
    if (box.isEmpty()) this.depthSphere.set(new THREE.Vector3(), 1)
    else {
      box.getBoundingSphere(this.depthSphere)
      this.depthSphere.radius = Math.max(this.depthSphere.radius * DEPTH_PAD, 1e-6)
    }
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
      // 半透明 makes this transparent and double-sided: three would then draw
      // it in two passes (back faces, then front) and flag needsUpdate twice
      // every frame. With depth writes off one pass looks the same.
      forceSinglePass: true,
    })
    const mesh = new THREE.Mesh(geo, mat)
    // mesh formats (STL, 3MF, ...) carry no B-rep faces: their triangles are the shape
    mesh.userData.meshFormat = part.faceRanges.length === 0
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
      const lines = new LineSegments2(edgeGeo, edgeMat)
      group.add(lines)
      // loose curves keep their own colour and stay drawn in every style: the
      // lines are all there is of them
      if (!curveOnly) this.partEdges.set(part.id, { lines, material: edgeMat, seeThroughColor: edgeColorOnDark(color) })
    }

    this.partGroups.set(part.id, group)
    this.modelGroup.add(group)
    // a reload, a new file or a 2D -> 3D switch comes up in the chosen style
    this.applyStyle(part.id)
  }

  // ---- display style ----------------------------------------------------------

  get displayStyle(): DisplayStyle {
    return this._displayStyle
  }

  /** faces are not opaque: the dark edge colour and an opaque section cap would hide things */
  get seeThrough(): boolean {
    return this._displayStyle === 'wireframe' || this._displayStyle === 'xray'
  }

  /**
   * Faces are not drawn at all: ワイヤーフレーム on a model with B-rep edge
   * lines. Parts without them (STL, 3MF, ...) draw their triangles' edges
   * with the face material, so a heatmap still shows there.
   */
  get facesHidden(): boolean {
    return this._displayStyle === 'wireframe' && this.partEdges.size > 0
  }

  /** the part draws B-rep edge lines (loose curves and mesh formats do not count) */
  hasEdgeLines(partId: number): boolean {
    return this.partEdges.has(partId)
  }

  /**
   * Switch how the model is drawn. Only material flags, uniforms and
   * visibility change: no geometry is built, and nothing is added per frame.
   */
  setDisplayStyle(style: DisplayStyle): void {
    if (style === this._displayStyle) return
    this._displayStyle = style
    for (const id of this.partMeshes.keys()) this.applyStyle(id)
    for (const fn of this.styleListeners) fn()
  }

  /** called after every style switch (the section tool restyles its cap) */
  onDisplayStyleChange(fn: () => void): void {
    this.styleListeners.push(fn)
  }

  /**
   * The style's flags on one part. Owns visible / wireframe / transparent /
   * opacity / depthWrite of the face material and the edge lines' visibility
   * and colour; the thickness heatmap owns color / vertexColors, so the two
   * never undo each other.
   */
  private applyStyle(partId: number): void {
    const mesh = this.partMeshes.get(partId)
    if (!mesh) return
    const edges = this.partEdges.get(partId)
    const s = this._displayStyle
    const hasFaces = (mesh.geometry.index?.count ?? 0) > 0
    // Hidden faces stay pickable: the raycaster and the picker ignore
    // Object3D.visible (the picker filters on the part group, the tree's
    // switch). The section's stencil meshes are siblings, so caps still work.
    const facesShown = !(s === 'wireframe' && edges)
    // While the draft colouring shows a per-triangle copy of a mesh-format
    // part (flatCopy), the copy is what is drawn: it takes the style, and the
    // part mesh stays hidden (it is kept for picking only).
    const copy = this.flatCopies.get(partId)
    if (copy) {
      mesh.visible = false
      copy.visible = facesShown
    } else {
      mesh.visible = facesShown
    }
    for (const m of copy ? [mesh, copy] : [mesh]) {
      const mat = m.material as THREE.MeshStandardMaterial
      // no edge lines (STL): the triangles are the wireframe. three builds their
      // line index once per geometry and caches it; no geometry is made here.
      mat.wireframe = s === 'wireframe' && !edges && hasFaces
      const xray = s === 'xray'
      if (mat.transparent !== xray) {
        mat.transparent = xray
        // transparent picks the shader variant (the OPAQUE define): three only
        // re-derives the program on a version bump
        mat.needsUpdate = true
      }
      mat.opacity = xray ? XRAY_OPACITY : 1
      // no depth writes: the inner walls of the same solid show, whatever the
      // order of its triangles
      mat.depthWrite = !xray
    }
    if (edges) {
      edges.lines.visible = s !== 'shaded'
      if (this.seeThrough) edges.material.color.copy(edges.seeThroughColor)
      else edges.material.color.set(EDGE_COLOR)
    }
  }

  /**
   * Whether the display style draws the part's faces: not in ワイヤーフレーム
   * when the part has edge lines (a B-rep), which are drawn instead. The faces
   * stay pickable either way (applyStyle); what is read off them for the eye
   * (the values under the cursor) should come only from faces on screen.
   */
  facesDrawn(partId: number): boolean {
    const mesh = this.partMeshes.get(partId)
    if (!mesh) return false
    // the draft colouring's per-triangle copy is what is drawn while it exists
    return this.flatCopies.get(partId)?.visible ?? mesh.visible
  }

  isPartVisible(partId: number): boolean {
    return this.partGroups.get(partId)?.visible ?? false
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
    this.flatCopies.clear() // disposed with their groups above
    this.partEdges.clear()
    this.lineMaterials = []
    for (const child of [...this.overlay.children]) this.disposeOverlayObject(child)
    this.viewAnim = null
    this.removePivotMarker()
    if (this.gridHelper) {
      this.scene.remove(this.gridHelper)
      this.gridHelper.dispose()
      this.gridHelper = null
    }
    this.gridSpec = null
  }

  /** Zoom to fit the visible bodies, keeping the current view direction and roll. */
  fitToView(): void {
    const box = this.modelBBox()
    if (box.isEmpty()) return
    this.finishViewAnim()
    this.stopInertia()
    const forward = this.target.clone().sub(this.camera.position)
    if (forward.lengthSq() < 1e-20) forward.copy(LOAD_VIEW_DIR).negate()
    this.frameBox(box, forward.normalize())
    this.rememberFit()
  }

  /** The load fit: default oblique direction, Z up, framed in fitArea. */
  frameNewModel(): void {
    this.viewAnim = null
    this.stopInertia()
    this.camera.up.copy(WORLD_UP)
    const box = this.modelBBox()
    if (!box.isEmpty()) this.frameBox(box, LOAD_VIEW_DIR.clone().negate())
    this.rememberFit()
  }

  /** the view right after the last fit (fitToView / frameNewModel) */
  private lastFit: { target: THREE.Vector3; dir: THREE.Vector3; up: THREE.Vector3; dist: number; zoom: number } | null = null

  private rememberFit(): void {
    const cam = this.camera
    const target = this.target.clone()
    const off = target.clone().sub(cam.position)
    this.lastFit = { target, dir: off.clone().normalize(), up: cam.up.clone(), dist: off.length(), zoom: cam.zoom }
  }

  /**
   * Is the view still the one the last fit made (not turned, panned or
   * zoomed since)? Then a change of the panels can fit again without
   * undoing anything the user did. The parallel camera's position moves along
   * the view axis on every frame (keepOrthoDepth), so the distance only
   * counts in perspective; its zoom only in parallel.
   */
  get atLastFit(): boolean {
    const f = this.lastFit
    if (!f || this.viewAnim || this.autoRotate) return false
    const cam = this.camera
    const target = this.target
    const off = target.clone().sub(cam.position)
    const scale = Math.max(f.dist, 1e-9)
    if (target.distanceTo(f.target) > 1e-6 * scale) return false
    if (off.clone().normalize().dot(f.dir) < 1 - 1e-9) return false
    if (cam.up.distanceTo(f.up) > 1e-6) return false
    if (this._projection === 'orthographic') return Math.abs(cam.zoom / f.zoom - 1) < 1e-9
    return Math.abs(off.length() / scale - 1) < 1e-9
  }

  /**
   * Place the camera on `forward` so the box's 8 corners fill FIT_FILL of the
   * limiting dimension of the fit area (fitArea), centred in it with equal
   * margins on both axes.
   *
   * With camera C = centre + a*right + b*up + e*forward (e < 0: behind the
   * centre), a corner at (x, y, z) in the same axes is inside the shrunken
   * right plane when x - a <= kH*(z - e), i.e. a - kH*e >= x - kH*z. Making
   * both planes of a pair touch the box gives e for that axis; the axis that
   * needs the camera further back limits. The lateral offsets are then
   * re-centred, because perspective draws the near end larger.
   */
  private frameBox(input: THREE.Box3, forward: THREE.Vector3): void {
    const box = input.clone()
    let r = box.getSize(new THREE.Vector3()).length() / 2
    if (r < 1e-9) {
      box.expandByScalar(0.5) // a point: frame it as a 1-unit cube
      r = box.getSize(new THREE.Vector3()).length() / 2
    }
    const center = box.getCenter(new THREE.Vector3())
    const right = forward.clone().cross(this.camera.up)
    if (right.lengthSq() < 1e-24) {
      // looking along up: any vector square to forward will do
      right.set(1, 0, 0).cross(forward)
      if (right.lengthSq() < 1e-12) right.set(0, 1, 0).cross(forward)
    }
    right.normalize()
    const up = right.clone().cross(forward).normalize()

    const xs: number[] = []
    const ys: number[] = []
    const zs: number[] = []
    const q = new THREE.Vector3()
    for (let i = 0; i < 8; i++) {
      q.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z)
      q.sub(center)
      xs.push(q.dot(right))
      ys.push(q.dot(up))
      zs.push(q.dot(forward))
    }
    // the ResizeObserver may not have run yet (e.g. right after the 2D view hid the canvas)
    if (this.container.clientWidth !== this.cssSize.x || this.container.clientHeight !== this.cssSize.y) {
      this.fitToContainer()
    }
    const W = this.cssSize.x
    const H = this.cssSize.y
    let area: ScreenRect = { left: 0, top: 0, right: W, bottom: H }
    const boxW = Math.max(...xs) - Math.min(...xs)
    const boxH = Math.max(...ys) - Math.min(...ys)
    if (W > 0 && H > 0) area = this.fitArea(boxW, boxH) ?? area
    // the target goes to the area's centre (both cameras carry the shift)
    this.viewShift.set(W / 2 - (area.left + area.right) / 2, H / 2 - (area.top + area.bottom) / 2)
    this.applyViewShift()
    // the area's size as a share of the canvas height: one px is the same
    // length both ways on screen, in either projection
    const areaH = H > 0 ? (area.bottom - area.top) / H : 1
    const areaW = H > 0 ? (area.right - area.left) / H : this.persp.aspect
    // With the offset the area is symmetric about the camera axis, so its
    // half-size in slope is tan(fov/2) * size / H. For the whole canvas these
    // are the old kV and kV * aspect.
    const tanHalf = Math.tan((this.persp.fov * Math.PI) / 360)
    const kV = FIT_FILL * tanHalf * areaH
    const kH = FIT_FILL * tanHalf * areaW
    let mR = -Infinity
    let mL = -Infinity
    let mT = -Infinity
    let mB = -Infinity
    for (let k = 0; k < 8; k++) {
      mR = Math.max(mR, xs[k] - kH * zs[k])
      mL = Math.max(mL, -xs[k] - kH * zs[k])
      mT = Math.max(mT, ys[k] - kV * zs[k])
      mB = Math.max(mB, -ys[k] - kV * zs[k])
    }
    const near = r / NEAR_DIV
    let e = Math.min(-(mR + mL) / (2 * kH), -(mT + mB) / (2 * kV))
    // keep the nearest corner in front of the near plane (never binds for a real box)
    e = Math.min(e, Math.min(...zs) - MIN_ZOOM_NEARS * near)
    // the perspective depth range, kept in both projections: it also sets the
    // parallel zoom limits (orthoLimits)
    this.persp.near = near
    this.persp.far = Math.max(r * FAR_MUL, 2 * (-e + r))
    this.persp.updateProjectionMatrix()
    this.applyOrthoZoomLimits()
    if (this._projection === 'orthographic') return this.placeOrthoFit(center, forward, xs, ys, areaW, areaH)
    const a = centredOffset(xs, zs, e)
    const b = centredOffset(ys, zs, e)

    const target = center.addScaledVector(right, a).addScaledVector(up, b)
    this.persp.position.copy(target).addScaledVector(forward, e)
    this.setTarget(target)
  }

  /**
   * frameBox for the parallel camera. The projected size of the box does not
   * depend on where the camera is, and the 8 corners are symmetric about the
   * centre, so the box is centred when the target is its centre and fills
   * FIT_FILL of the limiting dimension when the visible half-height is the
   * larger half-extent over FIT_FILL. xs / ys: corner offsets from the centre
   * along screen right / up.
   */
  private placeOrthoFit(
    center: THREE.Vector3,
    forward: THREE.Vector3,
    xs: number[],
    ys: number[],
    areaW: number,
    areaH: number,
  ): void {
    const w = Math.max(...xs) - Math.min(...xs)
    const h = Math.max(...ys) - Math.min(...ys)
    const { hMin, hMax } = this.orthoLimits()
    // half the canvas height in world units such that the box fills FIT_FILL
    // of the fit area's limiting side (areaW / areaH: the area's size over the
    // canvas height; the view offset centres the area on the camera axis)
    const half = Math.max(h / (2 * areaH), w / (2 * areaW)) / FIT_FILL
    this.ortho.zoom = ORTHO_TOP / THREE.MathUtils.clamp(half, hMin, hMax)
    this.ortho.updateProjectionMatrix()
    // any point behind the centre: setTarget puts the camera at its depth
    this.ortho.position.copy(center).sub(forward)
    this.setTarget(center)
  }

  /** ground grid sized to the loaded model (built once per model, not per fit) */
  private buildGrid(box: THREE.Box3): void {
    if (this.gridHelper) {
      this.scene.remove(this.gridHelper)
      this.gridHelper.dispose()
      this.gridHelper = null
    }
    this.gridSpec = null
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z)
    const gridSize = Math.pow(10, Math.ceil(Math.log10(maxDim * 2)))
    this.gridSpec = { size: gridSize, x: center.x, y: center.y, z: box.min.z }
    this.gridHelper = this.makeGrid(GRID_COLORS)
    this.gridHelper.visible = this._gridVisible
    this.scene.add(this.gridHelper)
  }

  /** a grid at gridSpec in the given colours (not added to the scene) */
  private makeGrid(colors: [number, number]): THREE.GridHelper {
    const s = this.gridSpec!
    const grid = new THREE.GridHelper(s.size, GRID_DIVISIONS, ...colors)
    // GridHelper lies in XZ; rotate into XY plane for Z-up world
    grid.rotation.x = Math.PI / 2
    grid.position.set(s.x, s.y, s.z)
    return grid
  }

  // ---- zoom toward a point, double-click pivot ----------------------------

  /**
   * Zoom about the surface point under the cursor (`pickSurface`) or, over empty
   * space, the point under the cursor on the plane through the target square
   * to the view. Camera and target both scale about that point, so the view
   * direction is unchanged and the point stays under the cursor. scale < 1 zooms in.
   */
  zoomAt(ndc: THREE.Vector2, scale: number, pickSurface: (ndc: THREE.Vector2) => THREE.Vector3 | null): void {
    if (!(scale > 0) || scale === 1) return
    // finish a pivot slide first, then look under the cursor in that final pose
    this.finishViewAnim()
    this.prepareCamera()
    const p = pickSurface(ndc) ?? this.targetPlanePoint(ndc)
    const cam = this.camera.position
    const target = this.target.clone()
    let s = scale
    if (this._projection === 'orthographic') {
      // the visible height scales by s: the same stops as perspective (orthoLimits)
      const { hMin, hMax } = this.orthoLimits()
      const h = ORTHO_TOP / this.ortho.zoom
      if (s < 1) s = Math.min(1, Math.max(s, hMin / h))
      else s = Math.max(1, Math.min(s, hMax / h))
    } else if (s < 1) s = Math.min(1, Math.max(s, (this.persp.near * MIN_ZOOM_NEARS) / cam.distanceTo(p)))
    else s = Math.max(1, Math.min(s, (this.persp.far * MAX_ZOOM_FAR) / cam.distanceTo(target)))
    if (s === 1) return
    // Parallel too: the target's offset from p across the screen scales by s,
    // as does the visible height, so p keeps its place on screen. The camera's
    // depth is re-placed by setTarget.
    cam.sub(p).multiplyScalar(s).add(p)
    target.sub(p).multiplyScalar(s).add(p)
    if (this._projection === 'orthographic') {
      this.ortho.zoom /= s
      this.ortho.updateProjectionMatrix()
    }
    this.setTarget(target) // both schemes' targets + lookAt + update
  }

  private targetPlanePoint(ndc: THREE.Vector2): THREE.Vector3 {
    this.raycaster.setFromCamera(ndc, this.camera)
    const forward = this.target.clone().sub(this.camera.position).normalize()
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(forward, this.target)
    return this.raycaster.ray.intersectPlane(plane, new THREE.Vector3()) ?? this.target.clone()
  }

  /**
   * Make `point` the rotation centre: slide the view sideways (no turn, no
   * zoom) until it sits mid-screen.
   *
   * Parallel projection needs nothing else: there the camera sits behind
   * everything (near = half its depth margin, see keepOrthoDepth), so `depth`
   * below is the point's own depth and `to` lies on the point's view axis. The
   * camera-to-target vector stays along the view through the slide, the zoom
   * is untouched, and every frame re-places the depth.
   */
  orbitAround(point: THREE.Vector3): void {
    this.viewAnim = null // a second double-click starts from wherever the first one got to
    this.stopInertia()
    const from = this.camera.position.clone()
    const fromTarget = this.target.clone()
    const forward = fromTarget.clone().sub(from).normalize()
    const depth = Math.max(point.clone().sub(from).dot(forward), this.camera.near * MIN_ZOOM_NEARS)
    this.viewAnim = {
      from,
      to: point.clone().addScaledVector(forward, -depth),
      fromTarget,
      toTarget: point.clone(),
      start: performance.now(),
    }
    this.showPivotMarker(point)
  }

  private stepViewAnim(now: number): void {
    const a = this.viewAnim!
    const t = THREE.MathUtils.clamp((now - a.start) / PIVOT_MS, 0, 1)
    const k = t * t * (3 - 2 * t) // smoothstep
    this.camera.position.lerpVectors(a.from, a.to, k)
    const target = new THREE.Vector3().lerpVectors(a.fromTarget, a.toTarget, k)
    this.controls.target.copy(target)
    this.trackball.target.copy(target)
    this.camera.lookAt(target) // the loop's controls.update() follows
    if (t >= 1) this.viewAnim = null
  }

  /** Jump a running pivot slide to its end, so whatever interrupts it orbits the new centre. */
  private finishViewAnim(): void {
    const a = this.viewAnim
    if (!a) return
    this.viewAnim = null
    this.camera.position.copy(a.to)
    this.setTarget(a.toTarget)
  }

  private showPivotMarker(at: THREE.Vector3): void {
    this.removePivotMarker()
    // on the scene, not `overlay`: the overlay belongs to the measure tool
    this.pivotMarker = this.makeLabel('', at, 'pivot-marker')
    // a one-second fading cue, not content: a saved image leaves it out
    this.pivotMarker.element.dataset.noExport = ''
    this.scene.add(this.pivotMarker)
    this.pivotMarkerTimer = setTimeout(() => this.removePivotMarker(), PIVOT_MARKER_MS)
  }

  private removePivotMarker(): void {
    clearTimeout(this.pivotMarkerTimer)
    this.pivotMarkerTimer = undefined
    if (!this.pivotMarker) return
    this.scene.remove(this.pivotMarker)
    this.pivotMarker.element.remove()
    this.pivotMarker = null
  }

  /**
   * Size the renderers to the container, at the current devicePixelRatio.
   * setSize alone keeps the ratio the renderer was made with, but the ratio
   * changes with browser zoom and when the window moves to a monitor with
   * another scale: the canvas would stay blurry and an export too small.
   */
  private fitToContainer(): void {
    const w = this.container.clientWidth
    const h = this.container.clientHeight
    // hidden (2D drawing shown): keep the last size, so the aspect never
    // becomes NaN for the next 3D load
    if (w === 0 || h === 0) return
    const dpr = window.devicePixelRatio || 1
    if (this.renderer.getPixelRatio() !== dpr) this.renderer.setPixelRatio(dpr)
    this.cssSize.set(w, h)
    const aspect = w / h
    this.persp.aspect = aspect
    // the visible height stays, the width follows the window (as in perspective)
    this.ortho.left = -aspect * ORTHO_TOP
    this.ortho.right = aspect * ORTHO_TOP
    // the offset is in px of this size: re-apply it with the new one (it
    // updates both projection matrices)
    this.applyViewShift()
    this.renderer.setSize(w, h)
    this.labelRenderer.setSize(w, h)
    for (const m of this.lineMaterials) m.resolution.set(w, h)
    this.trackball.handleResize()
  }

  /**
   * Shift the projection by viewShift (clamped to the current size) without
   * zooming: setViewOffset with the full size equal to the view size only
   * translates the frustum window. The stored shift is never clamped, so
   * widening the window again restores it. Updates the projection matrix.
   */
  private applyViewShift(): void {
    const { x: w, y: h } = this.cssSize
    const sx = THREE.MathUtils.clamp(this.viewShift.x, -MAX_VIEW_SHIFT * w, MAX_VIEW_SHIFT * w)
    const sy = THREE.MathUtils.clamp(this.viewShift.y, -MAX_VIEW_SHIFT * h, MAX_VIEW_SHIFT * h)
    // both cameras: a projection switch keeps the view where it is
    for (const cam of [this.persp, this.ortho]) {
      if (w > 0 && h > 0 && (sx !== 0 || sy !== 0)) cam.setViewOffset(w, h, sx, sy, w, h)
      else cam.clearViewOffset()
    }
  }

  /**
   * A move to a monitor with another scale changes devicePixelRatio without
   * resizing the container, so the ResizeObserver does not fire. A media
   * query on the current resolution does; it is re-armed for the new value.
   */
  private watchPixelRatio(): void {
    const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
    mq.addEventListener(
      'change',
      () => {
        this.fitToContainer()
        this.watchPixelRatio()
      },
      { once: true },
    )
  }

  // ---- PNG export -----------------------------------------------------------

  /**
   * The current view as a canvas at the WebGL drawing-buffer size (CSS size x
   * pixel ratio), with the HTML labels painted on top.
   *
   * The renderer keeps preserveDrawingBuffer off (it costs every frame), so
   * the buffer is only defined until the frame is presented: render once here
   * and copy it in the same task, before the browser presents. A render target
   * with readRenderTargetPixels was not used: it would need the MSAA resolve,
   * the colour-space conversion and a y-flip that the canvas path does for us.
   */
  snapshot(background: ExportBackground): HTMLCanvasElement {
    const src = this.renderer.domElement
    if (this.renderer.getContext().isContextLost()) throw new Error('WebGL の描画が失われている（再読み込みしてほしい）')
    // the image is at the screen's current scale even if no resize or media
    // query event has reached us yet (resizing clears the buffer: the render
    // below draws it again)
    if (this.renderer.getPixelRatio() !== (window.devicePixelRatio || 1)) this.fitToContainer()
    const out = document.createElement('canvas')
    out.width = src.width
    out.height = src.height
    const ctx = out.getContext('2d')
    if (!ctx) throw new Error('画像を作れない')
    let restore = () => {}
    this.prepareCamera()
    try {
      if (background === 'white') restore = this.applyWhiteBackground()
      this.renderer.render(this.scene, this.camera)
      // same task as render(): without preserveDrawingBuffer the buffer is undefined once presented
      ctx.drawImage(src, 0, 0)
    } finally {
      restore()
      // the visible canvas holds the normal frame again (a hidden tab may not
      // run the loop for a while)
      this.renderer.render(this.scene, this.camera)
    }
    this.labelRenderer.render(this.scene, this.camera) // label positions for exactly this camera
    const rect = src.getBoundingClientRect()
    // scale from the real buffer and rect, not devicePixelRatio: they differ after a browser zoom
    paintLabels(ctx, this.labelRenderer.domElement, rect, out.width / rect.width, out.height / rect.height)
    return out
  }

  /**
   * White scene background and, if the grid is shown, a light copy of the
   * grid in its place. Returns the undo. The light grid is built before the
   * scene is touched, so a throw leaves nothing to undo.
   */
  private applyWhiteBackground(): () => void {
    const grid = this.gridHelper
    const light = grid?.visible && this.gridSpec ? this.makeGrid(GRID_COLORS_ON_WHITE) : null
    // the see-through styles draw edges light (the part colour) for the dark
    // screen; on a white page they would wash out, so they print dark like
    // the shaded style. Listed before anything is touched.
    const lifted = this.seeThrough ? [...this.partEdges.values()] : []
    const bg = this.scene.background
    this.scene.background = WHITE
    if (grid && light) {
      grid.visible = false
      this.scene.add(light)
    }
    for (const e of lifted) e.material.color.set(EDGE_COLOR)
    return () => {
      for (const e of lifted) e.material.color.copy(e.seeThroughColor)
      this.scene.background = bg // the same Color object as before
      if (grid && light) {
        this.scene.remove(light)
        light.dispose()
        grid.visible = true
      }
    }
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
    this.finishViewAnim()
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
    this.finishViewAnim()
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
    this.finishViewAnim()
    const { right, up } = this.screenAxes()
    const dist = this.camera.position.distanceTo(this.target)
    const viewHeight = 2 * this.halfHeight(dist)
    const move = right.multiplyScalar(dx * viewHeight).add(up.multiplyScalar(dy * viewHeight))
    this.camera.position.add(move)
    this.setTarget(this.target.clone().add(move))
  }

  /** factor < 1 moves closer, > 1 moves away (parallel: the visible height scales, the target stays) */
  zoom(factor: number): void {
    this.finishViewAnim()
    if (this._projection === 'orthographic') {
      // within the controls' own zoom limits, which OrbitControls re-applies
      // every frame: a value outside would snap back a frame later
      const { hMin, hMax } = this.orthoLimits()
      const h = THREE.MathUtils.clamp((ORTHO_TOP / this.ortho.zoom) * factor, hMin, hMax)
      this.ortho.zoom = ORTHO_TOP / h
      this.ortho.updateProjectionMatrix()
      return
    }
    const offset = this.camera.position.clone().sub(this.target)
    const minDist = this.persp.near * MIN_ZOOM_NEARS // same stop as the wheel
    const maxDist = Math.max(this.persp.far * MAX_ZOOM_FAR, offset.length())
    offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, minDist, maxDist))
    this.camera.position.copy(this.target).add(offset)
  }

  /** Jump to a standard view, keeping the current target and distance. */
  setView(preset: ViewPreset): void {
    this.finishViewAnim()
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
    this.keepOrthoDepth()
  }

  // ---- projection -----------------------------------------------------------

  /**
   * Switch between perspective and parallel projection, keeping the view:
   * the same target, direction and up (roll included), and the model at the
   * same size at the target. The parallel visible half-height is what
   * perspective shows at the target's distance d (h = d * tan(fov / 2)), and
   * back again the perspective camera goes to d = h / tan(fov / 2).
   */
  setProjection(p: Projection): void {
    if (p === this._projection) return
    this.finishViewAnim()
    this.stopInertia()
    const from = this.camera
    const target = this.target.clone()
    const offset = from.position.clone().sub(target)
    const d = offset.length()
    const dir = d > 0 ? offset.divideScalar(d) : LOAD_VIEW_DIR.clone()
    const t = Math.tan((this.persp.fov * Math.PI) / 360)
    const { hMin, hMax } = this.orthoLimits()
    const to = p === 'orthographic' ? this.ortho : this.persp
    if (p === 'orthographic') {
      this.ortho.zoom = ORTHO_TOP / THREE.MathUtils.clamp(d * t, hMin, hMax)
      this.ortho.updateProjectionMatrix()
      this.ortho.position.copy(target).addScaledVector(dir, d) // its depth: keepOrthoDepth
    } else {
      this.persp.position.copy(target).addScaledVector(dir, ORTHO_TOP / this.ortho.zoom / t)
      this.trackball.panSpeed = TRACKBALL_PAN
    }
    to.up.copy(from.up)
    this._projection = p
    // both controls drive the camera in use; neither keeps anything else of it
    // (three r185: OrbitControls' Z-up frame comes from the first camera, same up)
    this.controls.object = to
    this.trackball.object = to
    this.setTarget(target)
  }

  /**
   * Parallel zoom limits: the visible half-heights perspective shows at its
   * own wheel stops (MIN_ZOOM_NEARS near planes from the point, the far
   * plane share MAX_ZOOM_FAR), so both projections magnify over the same range.
   */
  private orthoLimits(): { hMin: number; hMax: number } {
    const t = Math.tan((this.persp.fov * Math.PI) / 360)
    return { hMin: MIN_ZOOM_NEARS * this.persp.near * t, hMax: MAX_ZOOM_FAR * this.persp.far * t }
  }

  /** the same limits as zoom values for both controls (middle drag, pinch); perspective ignores them */
  private applyOrthoZoomLimits(): void {
    const { hMin, hMax } = this.orthoLimits()
    for (const c of [this.controls, this.trackball]) {
      c.minZoom = ORTHO_TOP / hMax
      c.maxZoom = ORTHO_TOP / hMin
    }
  }

  /**
   * Parallel only: put the camera on its view axis behind everything the
   * scene can draw, and size near / far to that. Required, not cosmetic: a
   * parallel ray starts on the camera plane, so anything behind the camera
   * would be neither drawn nor pickable. With ext = target distance from the
   * depth sphere's centre + its radius, every drawable point lies 1..3 ext
   * in front of the camera.
   *
   * It also normalises the trackball's pan: in parallel projection
   * TrackballControls (three r185) moves the image by |eye| * panSpeed /
   * clientWidth px per dragged px, and |eye| here is 2 ext, which has nothing
   * to do with the scale on screen. This value gives the perspective
   * trackball's vertical rate, TRACKBALL_PAN / (2 tan(fov / 2)), on both axes.
   */
  private keepOrthoDepth(): void {
    if (this._projection !== 'orthographic') return
    const cam = this.ortho
    const target = this.target
    const f = target.clone().sub(cam.position)
    if (f.lengthSq() < 1e-20) cam.getWorldDirection(f)
    else f.normalize()
    const ext = target.distanceTo(this.depthSphere.center) + this.depthSphere.radius
    cam.position.copy(target).addScaledVector(f, -2 * ext)
    if (cam.near !== 0.5 * ext || cam.far !== 3.5 * ext) {
      cam.near = 0.5 * ext
      cam.far = 3.5 * ext
      cam.updateProjectionMatrix()
    }
    const t = Math.tan((this.persp.fov * Math.PI) / 360)
    this.trackball.panSpeed = (TRACKBALL_PAN * (this.renderer.domElement.clientWidth || 1)) / (2 * t * 2 * ext)
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

/**
 * The part colour, mixed toward white just enough to reach the luminance
 * floor on the dark background. Colours are linear (three's working space),
 * where relative luminance is a weighted sum, so the mix is linear too:
 * L + t(1 - L). Colours already above the floor are kept as they are. (A floor
 * on HSL lightness would leave a saturated dark blue at luminance 0.07, 1.9:1.)
 */
function edgeColorOnDark(c: THREE.Color): THREE.Color {
  const l = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
  if (l >= SEE_THROUGH_EDGE_MIN_LUMINANCE) return c.clone()
  const t = (SEE_THROUGH_EDGE_MIN_LUMINANCE - l) / (1 - l)
  return c.clone().lerp(WHITE, t)
}

/**
 * Lateral offset o that leaves equal margins on both sides: the largest and
 * smallest of (c - o) / (z - e) cancel. Each term falls as o grows, so the
 * sum is monotonic and bisection is exact enough after 60 steps.
 */
function centredOffset(cs: number[], zs: number[], e: number): number {
  let lo = Math.min(...cs)
  let hi = Math.max(...cs)
  for (let i = 0; i < 60; i++) {
    const o = (lo + hi) / 2
    let max = -Infinity
    let min = Infinity
    for (let k = 0; k < cs.length; k++) {
      const r = (cs[k] - o) / (zs[k] - e)
      if (r > max) max = r
      if (r < min) min = r
    }
    if (max + min > 0) lo = o
    else hi = o
  }
  return (lo + hi) / 2
}
