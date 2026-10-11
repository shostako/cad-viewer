# ezdxf (DXF/DWG -> SVG): its data files (fonts and the like) are read at run time.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("ezdxf")
hiddenimports = collect_submodules("ezdxf.addons.drawing") + collect_submodules("ezdxf.fonts")
