/**
 * 2D drawings (DXF) in the Web version: the backend's own backend/app/drawing.py,
 * run in Pyodide (Python in WebAssembly) with ezdxf, so a drawing's SVG and its
 * snap points are the backend's to the byte. DWG is not opened (its converter,
 * the ODA File Converter, is a program on the PC).
 *
 * Pyodide and the packages are served with the page (web-public/py/, from
 * scripts/web-assets.mjs) and loaded on the first drawing (about 20 MB, cached
 * by the browser after). The Japanese font (Noto Sans JP, 4.5 MB; drawing.py
 * draws a drawing's Japanese with it, issue #90) only for a drawing that may
 * have Japanese in it.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface DrawingAnswer {
  svg: string
  meta: Record<string, unknown>
}

/** turns a drawing's bytes into its SVG and meta, or throws DrawingLoadError with the backend's message */
export type DrawingRenderer = (bytes: Uint8Array, filename: string) => Promise<DrawingAnswer>

export class DrawingLoadError extends Error {}

interface Manifest {
  packages: string[]
  wheel: string
  font: string
  /** the font for Japanese (drawing.py's CJK_FONTS' first) */
  japaneseFont?: string
  module: string
}

/**
 * a drawing that may have Japanese in it: a byte past ASCII (UTF-8, Shift_JIS,
 * a binary DXF), or DXF's escapes for one (\U+30C6, \M+18341)
 */
export function mayHaveJapanese(bytes: Uint8Array): boolean {
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i]
    if (b >= 0x80) return true
    if (b === 0x5c && i + 2 < bytes.length && (bytes[i + 1] === 0x55 || bytes[i + 1] === 0x4d) && bytes[i + 2] === 0x2b) return true
  }
  return false
}

/**
 * a renderer on Pyodide. base: where web-public/py's files are (a URL, or a
 * folder when run in Node); loadPyodide: pyodide's (passed in: the page's
 * Worker and the tests load it each their own way)
 */
export function pyodideRenderer(base: string, loadPyodide: (opts: any) => Promise<any>, read: (name: string) => Promise<Uint8Array>): DrawingRenderer {
  let ready: Promise<any> | null = null
  let manifest: Manifest | null = null
  let japanese: Promise<void> | null = null
  const start = async () => {
    manifest = JSON.parse(new TextDecoder().decode(await read('manifest.json'))) as Manifest
    const py = await loadPyodide({ indexURL: base, packageCacheDir: base, lockFileURL: `${base}pyodide-lock.json` })
    await py.loadPackage(manifest.packages)
    py.unpackArchive(await read(manifest.wheel), 'wheel')
    py.FS.mkdirTree('/fonts')
    py.FS.writeFile(`/fonts/${manifest.font}`, await read(manifest.font))
    py.FS.mkdirTree('/app')
    py.FS.writeFile('/app/drawing.py', await read(manifest.module))
    py.runPython(`
import sys
sys.path.insert(0, '/app')
import ezdxf.fonts.fonts as _ff
# the fonts are the ones put here (there are no system fonts to look for)
_ff.font_manager.clear()
_ff.font_manager.build(['/fonts'], support_dirs=False)
import json, drawing
def _render(data, name):
    try:
        svg, meta = drawing.load_drawing(bytes(data), name)
    except drawing.DrawingLoadError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"svg": svg, "meta": meta})
`)
    return py
  }
  /** the Japanese font among the fonts (once): ezdxf's list of them made again */
  const addJapanese = (py: any) =>
    (japanese ??= (async () => {
      const name = manifest?.japaneseFont
      if (!name) return
      py.FS.writeFile(`/fonts/${name}`, await read(name))
      py.runPython("_ff.font_manager.build(['/fonts'], support_dirs=False)")
    })().catch((e) => {
      japanese = null // try again next time
      throw e
    }))
  return async (bytes, filename) => {
    const py = await (ready ??= start().catch((e) => {
      ready = null // try again next time
      throw e
    }))
    if (mayHaveJapanese(bytes)) await addJapanese(py)
    const render = py.globals.get('_render')
    const data = py.toPy(bytes)
    try {
      const out = JSON.parse(render(data, filename))
      if (out.error !== undefined) throw new DrawingLoadError(out.error)
      return out as DrawingAnswer
    } finally {
      data.destroy()
      render.destroy()
    }
  }
}
