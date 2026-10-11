"""The installed app's entry, for PyInstaller (cad-viewer.spec): see backend/app/desktop.py."""
import multiprocessing
import sys

from app.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
