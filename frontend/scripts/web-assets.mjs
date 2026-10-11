// The Web version's Python for its 2D drawings (docs/designs/web-version.md, W6):
// Pyodide and the packages backend/app/drawing.py needs, put in web-public/py/
// (served with the page; not in git). Run by npm run dev:web and build:web.
//
// - Pyodide itself, from node_modules/pyodide (its version pinned in package.json)
// - its packages numpy, Pillow, fonttools, pyparsing, typing-extensions: the wheels
//   its lock file names, from Pyodide's CDN, checked against the lock's sha256
// - ezdxf 1.4.4, the backend's (requirements.lock), from PyPI, checked against its sha256
// - DejaVu Sans, the font the backend's ezdxf draws a drawing's plain text with
// - Noto Sans JP (SIL OFL 1.1, its licence beside it), the font a drawing's Japanese
//   is drawn with (backend/app/drawing.py's CJK_FONTS; issue #90): loaded only for
//   a drawing that may have Japanese in it (src/local/drawing.ts)
// - backend/app/drawing.py itself: the Web version runs the backend's own code
//
// Idempotent: a file already there with the right hash is not fetched again.
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONT = path.resolve(HERE, '..')
const OUT = path.join(FRONT, 'web-public', 'py')
const PYODIDE = path.join(FRONT, 'node_modules', 'pyodide')
const version = JSON.parse(fs.readFileSync(path.join(PYODIDE, 'package.json'), 'utf-8')).version
const CDN = `https://cdn.jsdelivr.net/pyodide/v${version}/full/`
const PACKAGES = ['numpy', 'pillow', 'fonttools', 'pyparsing', 'typing-extensions']
const EZDXF = {
  file: 'ezdxf-1.4.4-py3-none-any.whl',
  url: 'https://files.pythonhosted.org/packages/a0/09/5ecb6f82d35a2f4a4334d0a608fcf764827fa69dccdf5987ce309c16b6c1/ezdxf-1.4.4-py3-none-any.whl',
  sha256: '666edda631ba717270293b734f5d58dd97a1d1aba4787187f09d0cc584645865',
}

// notofonts/noto-cjk, the release Sans2.004: Noto Sans JP, the Japanese subset (4.5 MB)
const NOTO = 'https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/'
const JAPANESE_FONT = {
  file: 'NotoSansJP-Regular.otf',
  url: `${NOTO}Sans/SubsetOTF/JP/NotoSansJP-Regular.otf`,
  sha256: 'dff723ba59d57d136764a04b9b2d03205544f7cd785a711442d6d2d085ac5073',
}
const JAPANESE_FONT_LICENSE = {
  file: 'NotoSansJP-LICENSE.txt',
  url: `${NOTO}LICENSE`,
  sha256: '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2',
}

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex')

// the backend's ezdxf, the one its drawings are made with: the same version here
const lockLine = fs.readFileSync(path.join(FRONT, '..', 'backend', 'requirements.lock'), 'utf-8').match(/^ezdxf==(\S+)/m)
if (!lockLine || !EZDXF.file.startsWith(`ezdxf-${lockLine[1]}-`)) {
  throw new Error(`web-assets: ezdxf ${lockLine?.[1]} in backend/requirements.lock, ${EZDXF.file} here: change EZDXF (its url and sha256 from PyPI)`)
}

async function fetchChecked(url, hash, dest) {
  if (fs.existsSync(dest) && sha256(fs.readFileSync(dest)) === hash) return
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: ${res.status}`)
  const buf = Buffer.from(await res.arrayBuffer())
  if (sha256(buf) !== hash) throw new Error(`${url}: sha256 ${sha256(buf)}, not ${hash}`)
  fs.writeFileSync(`${dest}.tmp`, buf)
  fs.renameSync(`${dest}.tmp`, dest)
  console.log(`web-assets: ${path.basename(dest)} (${(buf.length / 1e6).toFixed(1)} MB)`)
}

function copy(src, dest) {
  const buf = fs.readFileSync(src)
  if (fs.existsSync(dest) && sha256(fs.readFileSync(dest)) === sha256(buf)) return
  fs.writeFileSync(dest, buf)
}

fs.mkdirSync(OUT, { recursive: true })
for (const f of ['pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json']) copy(path.join(PYODIDE, f), path.join(OUT, f))
const lock = JSON.parse(fs.readFileSync(path.join(PYODIDE, 'pyodide-lock.json'), 'utf-8'))
for (const name of PACKAGES) {
  const p = lock.packages[name]
  if (!p) throw new Error(`pyodide ${version} has no package ${name}`)
  await fetchChecked(CDN + p.file_name, p.sha256, path.join(OUT, p.file_name))
}
await fetchChecked(EZDXF.url, EZDXF.sha256, path.join(OUT, EZDXF.file))
for (const f of [JAPANESE_FONT, JAPANESE_FONT_LICENSE]) await fetchChecked(f.url, f.sha256, path.join(OUT, f.file))
copy(path.join(FRONT, 'node_modules', 'dejavu-fonts-ttf', 'ttf', 'DejaVuSans.ttf'), path.join(OUT, 'DejaVuSans.ttf'))
copy(path.join(FRONT, '..', 'backend', 'app', 'drawing.py'), path.join(OUT, 'drawing.py'))
// what the worker loads (names, in order)
fs.writeFileSync(
  path.join(OUT, 'manifest.json'),
  JSON.stringify({ packages: PACKAGES, wheel: EZDXF.file, font: 'DejaVuSans.ttf', japaneseFont: JAPANESE_FONT.file, module: 'drawing.py' }, null, 1),
)
