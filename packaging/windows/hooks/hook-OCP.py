# OpenCASCADE (cadquery-ocp-novtk): its DLLs are in the wheel's delvewheel folder
# next to the package (cadquery_ocp_novtk.libs), which OCP/__init__.py adds to the
# DLL search path at import. Collected to the same place in the bundle.
from PyInstaller.utils.hooks import collect_delvewheel_libs_directory

datas, binaries = collect_delvewheel_libs_directory("OCP", libdir_name="cadquery_ocp_novtk.libs")
