# embree (trimesh's fast rays, the 肉厚 heatmap and 厚肉): its DLLs are in the
# wheel's delvewheel folder embreex.libs; its __init__ reads its own version
# from the package's metadata; its extension modules import each other (rtcore).
from PyInstaller.utils.hooks import collect_delvewheel_libs_directory, collect_submodules, copy_metadata

datas, binaries = collect_delvewheel_libs_directory("embreex")
datas += copy_metadata("embreex")
hiddenimports = collect_submodules("embreex")
