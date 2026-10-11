/**
 * 配色 (ダーク / ライト): the app's look, the panels and the 3D / 2D views.
 *
 * The panels take their colours from style.css's tokens, which
 * `:root[data-theme='light']` redefines. The 3D and 2D views draw with the
 * palette here, and each part of the app that holds a colour in a material
 * repaints it from onTheme. The choice is kept in this browser; 'PC に合わせる'
 * follows the system's setting (prefers-color-scheme), also when it changes.
 * index.html sets data-theme before the first paint (no dark flash on a light
 * page), from the same key.
 */
export type Theme = 'dark' | 'light'
export type ThemeChoice = Theme | 'system'
export const THEME_CHOICES: Record<string, ThemeChoice> = {
  ダーク: 'dark',
  ライト: 'light',
  'PC に合わせる': 'system',
}
export const THEME_KEY = 'cad-viewer:theme'

export interface Palette {
  /** the 3D background (style.css --cv-scene) */
  scene: number
  /** the ground grid: centre lines, other lines */
  grid: [number, number]
  /** loose curves (parts with no faces) */
  curve: number
  /** what the cursor is on and the tree's highlighted part (style.css --cv-pick) */
  pick: number
  /** a dimension's line in 3D */
  dim: number
  /** a dimension's end points in 3D */
  marker: number
  /** the section plane's outline */
  sectionFrame: number
  /** the ring the 記録's images put on a place (style.css --cv-measure-ink) */
  ring: string
  /** the 2D drawing's page on screen (style.css --cv-page2d) */
  page2d: string
  /** the 2D measurements: the line and the value, the end points, the value's outline */
  dim2d: string
  marker2d: string
  halo2d: string
  /**
   * 版の比較 (compareview.ts): added, removed, unchanged. They are on lit faces
   * with no edge lines, so in the light theme each is darker, at 3:1 against
   * its background at least (the dark theme's are 2.4:1 to 1.8:1 on it)
   */
  compare: { added: number; removed: number; same: number }
  /**
   * アンダーカットの候補 (undercutview.ts): the candidates, the upper half's,
   * the lower half's, both halves'. As compare: lit faces, in the light theme
   * at 3:1 against its background at least
   */
  undercut: { candidate: number; up: number; down: number; both: number }
  /**
   * In 半透明 / ワイヤーフレーム the dark edge lines would vanish on the dark
   * background: they are lifted to a lighter shade of the part's colour. On
   * the light background the dark lines are what shows.
   */
  liftSeeThroughEdges: boolean
}

export const PALETTES: Record<Theme, Palette> = {
  dark: {
    scene: 0x1d2126,
    grid: [0x3a4250, 0x2a3038],
    curve: 0xe0b050,
    pick: 0x55d6ff,
    dim: 0xffd060,
    marker: 0xffb020,
    sectionFrame: 0xffd060,
    ring: '#ffd060',
    page2d: '#1d2126',
    dim2d: '#ffd060',
    marker2d: '#ffb020',
    halo2d: '#1d2126',
    compare: { added: 0x00a88f, removed: 0xe8590c, same: 0xa7adb4 },
    undercut: { candidate: 0xd6336c, up: 0x9fdcac, down: 0xa3bdf5, both: 0xa7adb4 },
    liftSeeThroughEdges: true,
  },
  // every colour at least 3:1 against the light background #e4e8ed (lines and
  // marks), the 2D value 4.5:1 against its white page
  light: {
    scene: 0xe4e8ed,
    grid: [0xa9b2bd, 0xc9d0d8],
    curve: 0x9a6a00,
    pick: 0x0a87b8,
    dim: 0x9a6a00,
    marker: 0xc05f00,
    sectionFrame: 0x9a6a00,
    ring: '#9a6a00',
    page2d: '#ffffff',
    dim2d: '#9a6a00',
    marker2d: '#c05f00',
    halo2d: '#ffffff',
    compare: { added: 0x008c76, removed: 0xd9480f, same: 0x7a8189 },
    undercut: { candidate: 0xc2255c, up: 0x2f8f3f, down: 0x3d6ad6, both: 0x7a8189 },
    liftSeeThroughEdges: false,
  },
}

const systemLight = (): boolean => {
  try {
    return window.matchMedia('(prefers-color-scheme: light)').matches
  } catch {
    return false
  }
}

/** the theme a choice comes to now */
export const resolveTheme = (choice: ThemeChoice): Theme =>
  choice === 'system' ? (systemLight() ? 'light' : 'dark') : choice

export function loadThemeChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'dark' || v === 'light' || v === 'system') return v
  } catch {
    /* storage unavailable: the default */
  }
  return 'dark'
}

function saveThemeChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_KEY, choice)
  } catch {
    /* best-effort */
  }
}

let choice: ThemeChoice = loadThemeChoice()
let theme: Theme = resolveTheme(choice)
// (no document under Node: tests/*.test.ts import modules that read the palette)
if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme
const listeners: ((p: Palette, t: Theme) => void)[] = []

export const currentTheme = (): Theme => theme
export const themeChoice = (): ThemeChoice => choice
/** the colours of the 3D / 2D views now */
export const palette = (): Palette => PALETTES[theme]

/** call `fn` whenever the theme changes (not now: read palette() for the start) */
export function onTheme(fn: (p: Palette, t: Theme) => void): void {
  listeners.push(fn)
}

function apply(): void {
  const next = resolveTheme(choice)
  if (next === theme) return
  theme = next
  document.documentElement.dataset.theme = theme
  for (const fn of listeners) fn(PALETTES[theme], theme)
}

/** choose the theme (kept in this browser) */
export function setThemeChoice(c: ThemeChoice): void {
  choice = c
  saveThemeChoice(c)
  apply()
}

// 'PC に合わせる' follows the system's setting when it changes
try {
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (choice === 'system') apply()
  })
} catch {
  /* no matchMedia: the choice stays as resolved */
}
