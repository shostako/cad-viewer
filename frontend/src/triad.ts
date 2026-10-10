/** Axis triad in the bottom-left corner: X / Y / Z (red / green / blue) as the camera sees them.
 *
 * An SVG overlay beside the 3D canvas, not part of the three.js scene: it can
 * never be picked, framed by a fit or counted in the model's bounds, and a
 * PNG export (the canvas plus the label layer) leaves it out, like the other
 * navigation aids. Its clicks never reach the canvas or its controls.
 *
 * Clicking an axis end looks along that axis from that side, exactly as the
 * 視点 buttons do (+X = 右, -Y = 正面, +Z = 上, ...).
 */
import * as THREE from 'three'
import type { ViewPreset } from './viewer'

const SVG_NS = 'http://www.w3.org/2000/svg'
/** axis length in viewBox units (the box is -44..44, 1 unit = 1 CSS px) */
const AXIS_LEN = 30
const COLORS = ['#e5534b', '#57b85a', '#4d86f0']
const LETTERS = ['X', 'Y', 'Z']

interface End {
  axis: 0 | 1 | 2
  sign: 1 | -1
  view: ViewPreset
  title: string
  group: SVGGElement
  line: SVGLineElement
  disc: SVGCircleElement
  text: SVGTextElement | null
}

const ENDS: Pick<End, 'axis' | 'sign' | 'view' | 'title'>[] = [
  { axis: 0, sign: 1, view: 'right', title: '右から見る（+X）' },
  { axis: 0, sign: -1, view: 'left', title: '左から見る（−X）' },
  { axis: 1, sign: 1, view: 'back', title: '背面から見る（+Y）' },
  { axis: 1, sign: -1, view: 'front', title: '正面から見る（−Y）' },
  { axis: 2, sign: 1, view: 'top', title: '上から見る（+Z）' },
  { axis: 2, sign: -1, view: 'bottom', title: '下から見る（−Z）' },
]

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag)
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v))
  return el
}

export class AxisTriad {
  private readonly root: HTMLElement
  private readonly svgEl: SVGSVGElement
  private readonly ends: End[] = []
  private shown = false
  /** the camera rotation last drawn (null: draw on the next update) */
  private last: THREE.Quaternion | null = null
  /** paint order last applied (indices into ends, far to near) */
  private order = ''
  private readonly basis = new THREE.Matrix4()
  private readonly right = new THREE.Vector3()
  private readonly up = new THREE.Vector3()
  private readonly back = new THREE.Vector3()

  constructor(root: HTMLElement, onPick: (view: ViewPreset) => void) {
    this.root = root
    this.svgEl = svg('svg', { viewBox: '-44 -44 88 88', width: 88, height: 88 })
    this.svgEl.appendChild(svg('circle', { class: 'triad-bg', r: 43 }))
    for (const e of ENDS) {
      const positive = e.sign > 0
      const color = COLORS[e.axis]
      const name = `${positive ? '+' : '-'}${LETTERS[e.axis]}`
      const group = svg('g', { class: 'triad-end', 'data-axis': name, 'data-view': e.view, role: 'button', 'aria-label': e.title })
      const title = svg('title', {})
      title.textContent = e.title
      const line = svg('line', {
        x1: 0,
        y1: 0,
        stroke: color,
        'stroke-width': positive ? 2.5 : 1.5,
        'stroke-linecap': 'round',
        ...(positive ? {} : { opacity: 0.5 }),
      })
      const disc = positive
        ? svg('circle', { r: 8.5, fill: color })
        : // the background's colour (style.css --cv-scene: ダーク or ライト), a little see-through
          svg('circle', { r: 6, style: 'fill: var(--cv-scene); fill-opacity: 0.8', stroke: color, 'stroke-width': 1.5 })
      group.append(title, line, disc)
      let text: SVGTextElement | null = null
      if (positive) {
        text = svg('text', {
          fill: '#fff',
          'font-size': 10,
          'font-weight': 700,
          'text-anchor': 'middle',
          'dominant-baseline': 'central',
        })
        text.textContent = LETTERS[e.axis]
        group.appendChild(text)
      }
      group.addEventListener('click', () => onPick(e.view))
      this.ends.push({ ...e, group, line, disc, text })
      this.svgEl.appendChild(group)
    }
    root.appendChild(this.svgEl)
    // a right-click on a disc would open the browser's menu over the model
    root.addEventListener('contextmenu', (ev) => ev.preventDefault())
  }

  show(on: boolean): void {
    this.shown = on
    this.root.classList.toggle('hidden', !on)
    this.last = null
  }

  /** Redraw for the camera's world rotation (cheap when nothing turned). */
  update(q: THREE.Quaternion): void {
    if (!this.shown || (this.last && this.last.equals(q))) return
    this.last = (this.last ?? new THREE.Quaternion()).copy(q)
    // the camera's right / up / backward (towards the viewer) in world axes
    this.basis.makeRotationFromQuaternion(q).extractBasis(this.right, this.up, this.back)
    const depth: number[] = []
    for (const end of this.ends) {
      const i = end.axis
      // world axis i on screen: its right and up components; SVG y grows down
      const x = AXIS_LEN * end.sign * this.right.getComponent(i)
      const y = -AXIS_LEN * end.sign * this.up.getComponent(i)
      end.line.setAttribute('x2', x.toFixed(2))
      end.line.setAttribute('y2', y.toFixed(2))
      end.disc.setAttribute('cx', x.toFixed(2))
      end.disc.setAttribute('cy', y.toFixed(2))
      end.text?.setAttribute('x', x.toFixed(2))
      end.text?.setAttribute('y', y.toFixed(2))
      depth.push(end.sign * this.back.getComponent(i))
    }
    // SVG paints in document order: the nearest end goes last, on top (it
    // also wins the hit test). Re-append only when the order changes, so a
    // turning view does not rebuild the DOM (and drop :hover) every frame.
    const idx = this.ends.map((_, k) => k).sort((a, b) => depth[a] - depth[b])
    const order = idx.join()
    if (order !== this.order) {
      this.order = order
      for (const k of idx) this.svgEl.appendChild(this.ends[k].group)
    }
  }
}
