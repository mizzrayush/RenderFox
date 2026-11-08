import os
import sys
import subprocess
import shutil
from pathlib import Path

# Ensure UTF-8 output encoding
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def build_executable():
    """
    Build the RenderFox executable using PyInstaller.

    One command, one source of truth: `RenderFox.spec`. This script used to re-type the whole
    flag list here as well, and the two lists had already drifted - the spec shipped the assimp
    build and `pyassimp`, this one shipped neither, and neither shipped `USER_GUIDE.md`, which
    `src/ui/main_window.py:365` asks the package for by name.
    """
    print("[*] Starting RenderFox Build Process...")

    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print("[OK] PyInstaller is installed.")
    except ImportError:
        print("[!] PyInstaller is NOT installed. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller installed successfully.")

    base_dir = Path(__file__).parent.absolute()
    spec = base_dir / "RenderFox.spec"
    dist_dir = base_dir / "dist"
    build_dir = base_dir / "build"

    if not spec.exists():
        print(f"[ERROR] {spec} is not there, and it is the only place the package's contents "
              "are written down. Refusing to build from an invented list.")
        sys.exit(1)

    # Clean previous builds
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)

    print("[*] Cleaned previous build directories.")

    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec)]

    print(f"[*] Running PyInstaller with command:\n{' '.join(command)}")

    try:
        subprocess.check_call(command)
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build Failed with error code {e.returncode}")
        sys.exit(1)

    package = dist_dir / "RenderFox"
    print(f"\n[OK] Build Complete! Executable: {package / 'RenderFox.exe'}")

    # The package is only shippable if the reader's frozen answers are files on this disk, so
    # ask them of the folder just written rather than of the spec that was meant to write it.
    check = base_dir / "tools" / "check_package_layout.py"
    print(f"[*] Checking the shipped files against the paths {check.name} reads...")
    if subprocess.call([sys.executable, "-X", "utf8", str(check), str(package)]) != 0:
        print("[ERROR] The build is missing files the app asks for by name. See the list above.")
        sys.exit(1)

    print("[OK] Every file the app names is in the package. Ready for NSIS packaging.")


if __name__ == "__main__":
    build_executable()
