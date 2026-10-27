/**
 * The Web version's 2D drawings (src/local/drawing.ts: the backend's own
 * drawing.py in Pyodide) against the backend's (load_drawing in CPython, given
 * the Web version's fonts only): the same SVG to the byte and the same meta
 * (box, scale, snap points), and the errors in the backend's words. DWG: not
 * opened, said so.
 *
 *   npm test   (testdata/make_dxf.py first; node scripts/web-assets.mjs, which npm run
 *               build:web / dev:web run; the backend's venv: backend/.venv or CAD_VIEWER_PYTHON)
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { LocalBackend, memoryStore } from '../src/local/backend.ts'
import { mayHaveJapanese, pyodideRenderer } from '../src/local/drawing.ts'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONT = path.resolve(HERE, '..')
const ROOT = path.resolve(FRONT, '..')
const PYTHON = process.env.CAD_VIEWER_PYTHON ?? path.join(ROOT, 'backend', '.venv', 'bin', 'python')
const PY = path.join(FRONT, 'web-public', 'py') + path.sep
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'cad-viewer-drawing-'))
// a drawing with nothing drawn: the backend's own error
fs.writeFileSync(path.join(TMP, 'empty.dxf'), '0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n')
// the Japanese ones last: the drawings before them must not need the Japanese font.
// sjis_drawing.dxf: Shift_JIS naming no code page, and SPLINEs ezdxf cannot make a curve of
const JAPANESE = ['japanese_drawing.dxf', 'sjis_drawing.dxf']
const FILES = [
  ...['plate_drawing.dxf', 'colours_drawing.dxf'].map((f) => path.join(ROOT, 'testdata', f)),
  path.join(TMP, 'empty.dxf'),
  ...JAPANESE.map((f) => path.join(ROOT, 'testdata', f)),
]
/** a drawing's routes besides its SVG (the 3D ones, a wrong one, its sidecar) */
const ROUTES = [
  'GET mesh.bin', 'POST measure', 'GET thickness.bin', 'GET thickness.bin?method=ball', 'GET thick', 'GET thick.bin',
  'GET properties', 'GET projected_area?axis=Z', 'GET nothing', 'GET sidecar',
]
const ready = fs.existsSync(PYTHON) && fs.existsSync(path.join(PY, 'manifest.json')) && FILES.every((f) => fs.existsSync(f))

const golden: Record<string, any> = ready
  ? JSON.parse(
      execFileSync(
        PYTHON,
        [
          '-c',
          `import json, os, sys, tempfile
os.environ["CAD_VIEWER_DATA_DIR"] = tempfile.mkdtemp()  # not the real sidecars
os.environ["CAD_VIEWER_FONT_DIRS"] = ${JSON.stringify(PY)}  # the Web version's Japanese font (drawing.py adds it when needed)
sys.path.insert(0, ${JSON.stringify(path.join(ROOT, 'backend'))})
import shutil
from ezdxf.fonts import fonts
# the fonts the Web version starts with, and only those: DejaVu Sans (the PC's would draw a
# text in its own fallback font: GitHub's runner's is not DejaVu Sans). The Japanese font is
# added from CAD_VIEWER_FONT_DIRS for a drawing with Japanese, as the Web version adds it
start = tempfile.mkdtemp()
shutil.copy(os.path.join(${JSON.stringify(PY)}, "DejaVuSans.ttf"), start)
fonts.font_manager.clear()
fonts.font_manager.build([start], support_dirs=False)
from fastapi.testclient import TestClient
from app.drawing import DrawingLoadError, load_drawing
from app.main import app
client = TestClient(app)
out = {}
for p in sys.argv[1:]:
    data = open(p, 'rb').read()
    try:
        svg, meta = load_drawing(data, p.rsplit('/', 1)[-1])
    except DrawingLoadError as e:
        out[p] = {"error": str(e)}
        continue
    out[p] = {"svg": svg, "meta": meta, "routes": {}}
    # a drawing's other routes, as the backend's own routes answer them
    mid = client.post("/api/models", files={"file": (p.rsplit('/', 1)[-1], data)}).json()["id"]
    for route in ${JSON.stringify(ROUTES)}:
        method, what = route.split(" ")
        r = client.request(method, f"/api/models/{mid}/{what}", json={"type": "distance"} if method == "POST" else None)
        out[p]["routes"][route] = [r.status_code, r.json()]
print(json.dumps(out))`,
          ...FILES,
        ],
        { encoding: 'utf-8', maxBuffer: 1 << 26 },
      ),
    )
  : {}

/** the files the renderer read from web-public/py */
const reads: string[] = []
const backend = ready
  ? new LocalBackend(
      memoryStore(),
      '0.0.0',
      null,
      pyodideRenderer(PY, async (opts) => (await import('pyodide')).loadPyodide(opts), async (f) => (reads.push(f), new Uint8Array(fs.readFileSync(PY + f)))),
    )
  : null
const JAPANESE_FONT = 'NotoSansJP-Regular.otf'

for (const file of FILES) {
  test(`${path.basename(file)}: as the backend draws it`, { skip: !ready && 'no backend venv, testdata or web-public/py' }, async () => {
    const want = golden[file]
    const japanese = JAPANESE.includes(path.basename(file))
    const up = await backend!.handle('POST', '/api/models', { name: path.basename(file), bytes: new Uint8Array(fs.readFileSync(file)).buffer })
    // the Japanese font read for a drawing with Japanese in it only, once (for the first)
    assert.equal(reads.filter((f) => f === JAPANESE_FONT).length, japanese ? 1 : 0, `${JAPANESE_FONT} read`)
    if (want.error) {
      assert.equal(up.status, 422)
      assert.equal((up.body as any).detail, want.error)
      return
    }
    assert.equal(up.status, 200, JSON.stringify(up.body))
    const meta = up.body as any
    assert.equal(meta.format, 'drawing')
    for (const k of Object.keys(want.meta)) assert.deepEqual(meta[k], want.meta[k], k)
    const svg = await backend!.handle('GET', `/api/models/${meta.id}/drawing.svg`)
    assert.equal(svg.kind, 'text')
    assert.equal(svg.body, want.svg, 'the SVG to the byte')
    // its other routes (it has no 3D) as the backend answers them, to the letter
    for (const route of ROUTES) {
      const [method, what] = route.split(' ')
      const r = await backend!.handle(method, `/api/models/${meta.id}/${what}`, method === 'POST' ? { type: 'distance' } : undefined)
      assert.deepEqual([r.status, r.body], want.routes[route], route)
    }
  })
}

test('DWG: not in the Web version, said so', { skip: !ready && 'no web-public/py' }, async () => {
  const up = await backend!.handle('POST', '/api/models', { name: 'a.dwg', bytes: new TextEncoder().encode('AC1027').buffer })
  assert.equal(up.status, 422)
  assert.match((up.body as any).detail, /Web 版では DWG を開けない/)
})

test('which drawings may have Japanese in them (the Japanese font loaded for those)', () => {
  const ascii = (t: string) => new TextEncoder().encode(t)
  assert.equal(mayHaveJapanese(ascii('0\nSECTION\n2\nENTITIES\n1\nGATE A\n')), false)
  assert.equal(mayHaveJapanese(ascii('1\n\\U+30C6\n')), true, "DXF's Unicode escape")
  assert.equal(mayHaveJapanese(ascii('1\n\\M+18341\n')), true, "DXF's multi-byte escape")
  assert.equal(mayHaveJapanese(new TextEncoder().encode('1\n寸法\n')), true, 'UTF-8')
  assert.equal(mayHaveJapanese(Uint8Array.of(0x31, 0x0a, 0x90, 0xa1, 0x96, 0x40)), true, 'Shift_JIS')
  const plate = path.join(ROOT, 'testdata', 'plate_drawing.dxf')
  if (fs.existsSync(plate)) assert.equal(mayHaveJapanese(new Uint8Array(fs.readFileSync(plate))), false, 'plate_drawing.dxf')
})

test('a drawing with Japanese after one that named the Japanese font: drawn as on its own', { skip: !ready && 'no backend venv, testdata or web-public/py' }, async () => {
  // a drawing without Japanese that asks for Noto Sans JP (a style on its file, an MTEXT on
  // its family) before the font is loaded: ezdxf remembers both as missing
  const named = path.join(TMP, 'named_font.dxf')
  execFileSync(PYTHON, ['-c', `import ezdxf
doc = ezdxf.new("R2010")
doc.styles.new("N", dxfattribs={"font": "NotoSansJP-Regular.otf"})
msp = doc.modelspace()
msp.add_text("GATE", height=5, dxfattribs={"style": "N"})
msp.add_mtext("\\\\fNoto Sans JP;GATE", dxfattribs={"char_height": 5, "insert": (0, 10)})
doc.saveas(${JSON.stringify(named)})`])
  const japanese = path.join(ROOT, 'testdata', 'japanese_drawing.dxf')
  // a page of its own: Python started afresh
  const fresh = new LocalBackend(memoryStore(), '0.0.0', null, pyodideRenderer(PY, async (opts) => (await import('pyodide')).loadPyodide(opts), async (f) => new Uint8Array(fs.readFileSync(PY + f))))
  const first = await fresh.handle('POST', '/api/models', { name: 'named_font.dxf', bytes: new Uint8Array(fs.readFileSync(named)).buffer })
  assert.equal(first.status, 200, JSON.stringify(first.body))
  const up = await fresh.handle('POST', '/api/models', { name: 'japanese_drawing.dxf', bytes: new Uint8Array(fs.readFileSync(japanese)).buffer })
  assert.equal(up.status, 200, JSON.stringify(up.body))
  const svg = await fresh.handle('GET', `/api/models/${(up.body as any).id}/drawing.svg`)
  assert.equal(svg.body, golden[japanese].svg, 'as when it is the first drawing with Japanese')
})
