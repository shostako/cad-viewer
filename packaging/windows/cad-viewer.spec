# PyInstaller spec for the installed app (Windows, a folder: cad-viewer\cad-viewer.exe).
# Before it: the frontend built (frontend/dist) and the icon drawn (make_icon.py).
# Run from the repo's root:
#   pyinstaller --noconfirm --clean packaging/windows/cad-viewer.spec
# One folder, not one file: a one-file exe unpacks its 400 MB to a temporary
# folder at every start.
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
DIST = os.path.join(ROOT, "frontend", "dist")
ICON = os.path.join(SPECPATH, "cad-viewer.ico")
if not os.path.isfile(os.path.join(DIST, "index.html")):
    raise SystemExit("frontend/dist is missing: (cd frontend && npm ci && npm run build)")
if not os.path.isfile(ICON):
    raise SystemExit("cad-viewer.ico is missing: python packaging/windows/make_icon.py")

a = Analysis(
    [os.path.join(SPECPATH, "cad_viewer_app.py")],
    pathex=[os.path.join(ROOT, "backend")],
    datas=[(DIST, "frontend_dist"), (ICON, ".")],
    # the server's modules (imported after the environment is set), uvicorn's
    # (chosen by name at run time), the tray's Windows backend
    hiddenimports=collect_submodules("app") + collect_submodules("uvicorn") + ["pystray._win32"],
    hookspath=[os.path.join(SPECPATH, "hooks")],
    # only what is surely not used (the standard library stays whole: cutting a
    # part of it has broken imports elsewhere before)
    excludes=["pytest", "_pytest", "tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cad-viewer",
    icon=ICON,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="cad-viewer", upx=False)
