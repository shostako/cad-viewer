import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { MeshPack } from './meshpack'

export class Viewer {
  readonly scene = new THREE.Scene()
  readonly camera: THREE.PerspectiveCamera
  readonly renderer: THREE.WebGLRenderer
  readonly controls: OrbitControls
  private modelGroup = new THREE.Group()
  private gridHelper: THREE.GridHelper | null = null

  constructor(container: HTMLElement) {
    this.scene.background = new THREE.Color(0x1d2126)

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1e6)
    // CAD convention: Z-up. Keep world coordinates identical to server B-rep coords.
    this.camera.up.set(0, 0, 1)
    this.camera.position.set(80, -60, 50)

    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    container.appendChild(this.renderer.domElement)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true

    // CAD-ish lighting: hemisphere + key + fill
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2))
    const key = new THREE.DirectionalLight(0xffffff, 1.4)
    key.position.set(1, -1.5, 2)
    this.scene.add(key)
    const fill = new THREE.DirectionalLight(0xffffff, 0.5)
    fill.position.set(-1.5, 1, -1)
    this.scene.add(fill)

    this.scene.add(this.modelGroup)

    const resize = () => {
      const w = container.clientWidth
      const h = container.clientHeight
      this.camera.aspect = w / h
      this.camera.updateProjectionMatrix()
      this.renderer.setSize(w, h)
    }
    new ResizeObserver(resize).observe(container)
    resize()

    this.renderer.setAnimationLoop(() => {
      this.controls.update()
      this.renderer.render(this.scene, this.camera)
    })
  }

  /** Replace current model with mesh from the binary protocol. */
  setModel(pack: MeshPack): THREE.Mesh {
    this.clearModel()

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pack.buffers.positions, 3))
    geo.setAttribute('normal', new THREE.BufferAttribute(pack.buffers.normals, 3))
    geo.setIndex(new THREE.BufferAttribute(pack.buffers.indices as Uint32Array, 1))

    const mat = new THREE.MeshStandardMaterial({
      color: 0x8fb4d8,
      metalness: 0.1,
      roughness: 0.65,
      side: THREE.DoubleSide,
    })
    const mesh = new THREE.Mesh(geo, mat)
    this.modelGroup.add(mesh)

    this.fitToView()
    return mesh
  }

  clearModel(): void {
    for (const child of [...this.modelGroup.children]) {
      this.modelGroup.remove(child)
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose()
        ;(child.material as THREE.Material).dispose()
      }
    }
    if (this.gridHelper) {
      this.scene.remove(this.gridHelper)
      this.gridHelper.dispose()
      this.gridHelper = null
    }
  }

  fitToView(): void {
    const box = new THREE.Box3().setFromObject(this.modelGroup)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z)
    const dist = maxDim / (2 * Math.tan((this.camera.fov * Math.PI) / 360))

    const dir = new THREE.Vector3(1, -1, 0.7).normalize()
    this.camera.position.copy(center).addScaledVector(dir, dist * 1.5)
    this.camera.near = maxDim / 1000
    this.camera.far = maxDim * 100
    this.camera.updateProjectionMatrix()
    this.controls.target.copy(center)
    this.controls.update()

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
    this.scene.add(this.gridHelper)
  }
}
