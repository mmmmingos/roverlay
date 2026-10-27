"""Build dist/Roverlay/Roverlay.exe (a one-folder app) and dist/Roverlay-<version>-windows.zip.

Run from the repo root: .venv/Scripts/python.exe scripts/build.py
The model and llama.cpp are not bundled: Roverlay downloads them on first run (about 6 GB).
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from roverlay.config import VERSION  # noqa: E402

args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "Roverlay",
    "--icon", str(ROOT / "roverlay" / "assets" / "icon.ico"),
    "--add-data", f"{ROOT / 'roverlay' / 'ui'};roverlay/ui",
    "--add-data", f"{ROOT / 'roverlay' / 'assets'};roverlay/assets",
    "--collect-all", "webview",
    "--collect-all", "clr_loader",
    "--collect-all", "pythonnet",
    "--collect-all", "uiautomation",
    "--collect-submodules", "comtypes",
    "--hidden-import", "pystray._win32",
    "--paths", str(ROOT),
    str(ROOT / "scripts" / "launch.py"),
]
subprocess.run(args, cwd=ROOT, check=True)
dist = ROOT / "dist"
archive = shutil.make_archive(str(dist / f"Roverlay-{VERSION}-windows"), "zip", dist, "Roverlay")
print("built", dist / "Roverlay" / "Roverlay.exe")
print("zipped", archive)
