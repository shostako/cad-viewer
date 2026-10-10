/**
 * 材料と用途: one material chosen drives the specific gravity (体積・重量),
 * the 判定の基準 (the 肉厚 folder's 閾値, the 抜き勾配 folder's 必要な勾配) and
 * the 記録. 用途 says what the model is looked at for:
 * - 射出成形: a moulded part. The resins; every check is there.
 * - 一般: a structure in general (machined metal, a bought part, ...). The
 *   metals and the resins; the moulding's own rows (抜き勾配, 問題の一覧, the
 *   projected area and the clamping force) are hidden.
 *
 * Every material has the general standards built in (BUILTIN, the values and
 * where they come from: docs/material-basis.md). They can be edited (the card
 * of 基準を編集…), and 既定に戻す puts them back, one material or all. The
 * edits are kept in this browser and can be written to a file and read back.
 */
import { DRAFT_MAX_DEG } from './draft'

export type Use = 'molding' | 'general'
export const USE_NAMES: Record<string, Use> = { 射出成形: 'molding', 一般: 'general' }
export const USE_LABEL: Record<Use, string> = { molding: '射出成形', general: '一般' }
export type MaterialKind = 'resin' | 'metal'

/** what a material says to the app */
export interface MaterialValues {
  /** specific gravity (g/cm³) */
  density: number
  /** mm: thinner is 薄肉 */
  thin: number
  /** degrees: less is 勾配不足 (a resin's; null: a metal, not moulded) */
  draft: number | null
  /** times the general wall: a sphere this much across or more is 厚肉 (a resin's; null: a metal) */
  thick: number | null
  /** where the values come from (shown with the conditions; '' : not said) */
  source: string
}

interface MaterialDef extends MaterialValues {
  name: string
  kind: MaterialKind
}

/** a resin's draft: the least of the makers' (Covestro, Celanese, DuPont for deep parts) and the guides' */
const DRAFT = 0.5
/** a resin's 厚肉: DuPont's junction to avoid (a rib as thick as the wall, its root R half the wall: a circle 1.5 x the wall) */
const THICK = 1.5
/** a metal's least wall: machining, Protolabs Network's recommended (0.5 mm possible) */
const METAL_THIN = 0.8
const METAL_SOURCE = 'Protolabs Network の切削の最小肉厚（推奨）'

/** The general standards (docs/material-basis.md has each value's source, with the page) */
const BUILTIN: readonly MaterialDef[] = [
  { name: 'PMMA', kind: 'resin', density: 1.19, thin: 0.64, draft: DRAFT, thick: THICK, source: 'Protolabs の肉厚の表（下端）・各社の勾配の最小・DuPont の厚肉' },
  { name: 'PC', kind: 'resin', density: 1.2, thin: 1.0, draft: DRAFT, thick: THICK, source: 'Protolabs・Fictiv の肉厚（下端）・Covestro の勾配・DuPont の厚肉' },
  { name: 'ABS', kind: 'resin', density: 1.05, thin: 1.14, draft: DRAFT, thick: THICK, source: 'Protolabs の肉厚の表（下端）・勾配・DuPont の厚肉' },
  { name: 'PP', kind: 'resin', density: 0.9, thin: 0.89, draft: DRAFT, thick: THICK, source: 'Protolabs の肉厚の表（下端）・Fictiv の勾配・DuPont の厚肉' },
  { name: 'PA66', kind: 'resin', density: 1.14, thin: 1.0, draft: DRAFT, thick: THICK, source: '旭化成 レオナの設計基準（肉厚）・各社の勾配・DuPont の厚肉' },
  { name: 'POM', kind: 'resin', density: 1.41, thin: 0.76, draft: DRAFT, thick: THICK, source: 'Protolabs の肉厚の表（下端）・Celanese の勾配・DuPont の厚肉' },
  { name: 'PS', kind: 'resin', density: 1.05, thin: 0.89, draft: DRAFT, thick: THICK, source: 'Protolabs の肉厚の表（下端）・勾配・DuPont の厚肉' },
  { name: 'SS400', kind: 'metal', density: 7.85, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: 'S45C', kind: 'metal', density: 7.85, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: 'SUS304', kind: 'metal', density: 7.93, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: 'A5052', kind: 'metal', density: 2.68, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: 'A6061', kind: 'metal', density: 2.7, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: '銅 C1100', kind: 'metal', density: 8.89, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: '黄銅 C3604', kind: 'metal', density: 8.5, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
  { name: '純チタン 2 種', kind: 'metal', density: 4.51, thin: METAL_THIN, draft: null, thick: null, source: METAL_SOURCE },
]
const BY_NAME = new Map(BUILTIN.map((m) => [m.name, m]))
export const RESINS: readonly string[] = BUILTIN.filter((m) => m.kind === 'resin').map((m) => m.name)
export const METALS: readonly string[] = BUILTIN.filter((m) => m.kind === 'metal').map((m) => m.name)
/** the materials a 用途 offers, in the order of the select */
export const materialsFor = (use: Use): readonly string[] => (use === 'molding' ? RESINS : [...METALS, ...RESINS])
export const kindOf = (name: string): MaterialKind | null => BY_NAME.get(name)?.kind ?? null
export const isMaterial = (name: unknown): name is string => typeof name === 'string' && BY_NAME.has(name)

/** a material's general standard (a copy) */
export function builtin(name: string): MaterialValues {
  const m = BY_NAME.get(name)
  if (!m) throw new Error(`no material ${name}`)
  return { density: m.density, thin: m.thin, draft: m.draft, thick: m.thick, source: m.source }
}

export const DENSITY_MIN = 0.1
export const DENSITY_MAX = 25
export const THIN_MIN = 0.1
export const THIN_MAX = 10
export const SOURCE_MAX = 200
export const THICK_MIN = 1.05
export const THICK_MAX = 10
/** not said: the conditions say so */
export const BASIS_UNSET = '未設定'

/** the steps the folders take: 閾値 0.01 mm, 必要な勾配 0.1°, 比重 0.001, 厚肉 0.05 倍 */
export const thinStep = (v: number): number => Math.round(v * 100) / 100
export const thickStep = (v: number): number => Math.round(v * 20) / 20
export const draftStep = (v: number): number => Math.round(v * 10) / 10
export const densityStep = (v: number): number => Math.round(v * 1000) / 1000

/** a material's values the app accepts (a metal has no draft, a resin one in range) */
export function validValues(name: string, v: unknown): v is MaterialValues {
  const x = v as MaterialValues
  const kind = kindOf(name)
  const num = (n: unknown, lo: number, hi: number) => typeof n === 'number' && Number.isFinite(n) && n >= lo && n <= hi
  return (
    !!x &&
    kind !== null &&
    num(x.density, DENSITY_MIN, DENSITY_MAX) &&
    num(x.thin, THIN_MIN, THIN_MAX) &&
    (kind === 'metal' ? x.draft === null : num(x.draft, 0, DRAFT_MAX_DEG)) &&
    (kind === 'metal' ? x.thick === null : num(x.thick, THICK_MIN, THICK_MAX)) &&
    typeof x.source === 'string'
  )
}

/** at the folders' steps, the basis trimmed: what is saved is what the checks use */
export function stepped(v: MaterialValues): MaterialValues {
  return {
    density: densityStep(v.density),
    thin: thinStep(v.thin),
    draft: v.draft === null ? null : draftStep(v.draft),
    thick: v.thick === null ? null : thickStep(v.thick),
    source: v.source.trim().slice(0, SOURCE_MAX),
  }
}

export const sameValues = (a: MaterialValues, b: MaterialValues): boolean =>
  a.density === b.density && a.thin === b.thin && a.draft === b.draft && a.thick === b.thick && a.source === b.source

/** a material's values as kept before 厚肉 came (no thick): the general standard's thick */
const withThick = (name: string, v: unknown): unknown =>
  v && typeof v === 'object' && !('thick' in v) && isMaterial(name) ? { ...v, thick: builtin(name).thick } : v

export interface MaterialStore {
  use: Use
  /** the material chosen, for each 用途 (a resin can be both's) */
  chosen: Record<Use, string>
  /** the values edited away from the general standards */
  edits: Record<string, MaterialValues>
  /** 判定の基準 follows the material (false: the 閾値 and the 必要な勾配 as set by hand) */
  follow: boolean
  /** a specific gravity typed by hand for the material in use (null: the material's) */
  density: number | null
}

const KEY = 'cad-viewer:materials'
/** before materials: the 判定の基準's edits (its card was presets.ts) and the 体積・重量 resin */
const OLD_BASIS_KEY = 'cad-viewer:check-basis'
const OLD_PROPS_KEY = 'cad-viewer:props'

export const freshStore = (): MaterialStore => ({
  use: 'molding',
  chosen: { molding: 'PMMA', general: 'SS400' },
  edits: {},
  follow: true,
  density: null,
})

/** a material's values now: its edit, or its general standard */
export const valuesOf = (s: MaterialStore, name: string): MaterialValues => (s.edits[name] ? { ...s.edits[name] } : builtin(name))
export const isEdited = (s: MaterialStore, name: string): boolean => !!s.edits[name]
/** the material in use */
export const current = (s: MaterialStore): string => s.chosen[s.use]

/** keep an edit only where it differs from the general standard */
export function setValues(s: MaterialStore, name: string, v: MaterialValues): void {
  if (sameValues(v, builtin(name))) delete s.edits[name]
  else s.edits[name] = { ...v }
}

function readEdits(raw: unknown): Record<string, MaterialValues> {
  const out: Record<string, MaterialValues> = {}
  if (!raw || typeof raw !== 'object') return out
  for (const [name, v0] of Object.entries(raw as Record<string, unknown>)) {
    const v = withThick(name, v0)
    if (isMaterial(name) && validValues(name, v)) {
      const sv = stepped(v)
      if (!sameValues(sv, builtin(name))) out[name] = sv
    }
  }
  return out
}

/**
 * What this browser keeps (anything it cannot read: the defaults). The first
 * time, what the app kept before materials comes along: the 判定の基準's
 * edited rows (an untouched row, 1.5 mm / 1.0° / 未設定, is not an edit) and
 * the 体積・重量 resin (その他's typed gravity as a gravity by hand).
 */
export function loadMaterials(): MaterialStore {
  const s = freshStore()
  try {
    const raw = localStorage.getItem(KEY)
    if (raw !== null) {
      const saved = JSON.parse(raw) ?? {}
      if (saved.use === 'molding' || saved.use === 'general') s.use = saved.use
      for (const use of ['molding', 'general'] as const) {
        const m = saved.chosen?.[use]
        if (isMaterial(m) && materialsFor(use).includes(m)) s.chosen[use] = m
      }
      s.edits = readEdits(saved.edits)
      if (typeof saved.follow === 'boolean') s.follow = saved.follow
      if (typeof saved.density === 'number' && Number.isFinite(saved.density) && saved.density >= DENSITY_MIN && saved.density <= DENSITY_MAX)
        s.density = densityStep(saved.density)
      return s
    }
    const basis = JSON.parse(localStorage.getItem(OLD_BASIS_KEY) ?? '{}') ?? {}
    for (const [name, b] of Object.entries((basis.bases ?? {}) as Record<string, Record<string, unknown>>)) {
      if (!RESINS.includes(name) || !b) continue
      const untouched = b.thin === 1.5 && b.draft === 1 && String(b.source ?? '').trim() === ''
      const v = { density: builtin(name).density, thin: b.thin, draft: b.draft, thick: builtin(name).thick, source: String(b.source ?? '') }
      if (!untouched && validValues(name, v)) setValues(s, name, stepped(v as MaterialValues))
    }
    const props = JSON.parse(localStorage.getItem(OLD_PROPS_KEY) ?? '{}') ?? {}
    if (RESINS.includes(props.resin)) s.chosen.molding = props.resin
    else if (props.resin === 'その他' && typeof props.density === 'number' && props.density >= DENSITY_MIN && props.density <= DENSITY_MAX)
      s.density = densityStep(props.density)
    if (RESINS.includes(basis.selected)) s.chosen.molding = basis.selected
  } catch {
    /* defaults (storage unavailable, or not JSON) */
  }
  return s
}

export function saveMaterials(s: MaterialStore): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* best-effort */
  }
}

/** 「PMMA（根拠: …）」: what the conditions say of the basis in use */
export function basisText(name: string, v: MaterialValues): string {
  return `${name}（根拠: ${v.source.trim() || BASIS_UNSET}）`
}

/** a file of the materials' values (書き出す): every material's, edited or not */
export function materialsFile(s: MaterialStore): string {
  const materials = Object.fromEntries([...METALS, ...RESINS].map((m) => [m, valuesOf(s, m)]))
  return JSON.stringify({ app: 'cad-viewer', kind: 'materials', version: 1, materials }, null, 2) + '\n'
}

/**
 * The values in a file of materials (読み込む): the materials it has and the
 * app knows, each checked as the card checks it. A name the app does not know
 * or a row out of range is listed, not taken.
 */
export function readMaterialsFile(text: string): { values: Record<string, MaterialValues>; skipped: string[] } {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error('JSON として読めない')
  }
  const d = data as { kind?: unknown; materials?: unknown }
  if (!d || d.kind !== 'materials' || !d.materials || typeof d.materials !== 'object') throw new Error('材料の基準のファイルではない')
  const values: Record<string, MaterialValues> = {}
  const skipped: string[] = []
  for (const [name, v0] of Object.entries(d.materials as Record<string, unknown>)) {
    const v = withThick(name, v0) // a file written before 厚肉 came
    if (isMaterial(name) && validValues(name, v)) values[name] = stepped(v)
    else skipped.push(name)
  }
  return { values, skipped }
}

/** 1.5 → 「1.5」, 0.64 → 「0.64」: a length of the 閾値's 0.01 mm steps, as short as it reads */
export const fmtThin = (v: number): string => (Math.abs(v * 10 - Math.round(v * 10)) < 1e-6 ? v.toFixed(1) : v.toFixed(2))
