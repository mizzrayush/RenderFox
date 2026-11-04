
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

    # Define paths
    base_dir = Path(__file__).parent.absolute()
    main_script = base_dir / "main.py"
    icon_path = base_dir / "resources" / "icon.ico"  # Assuming an icon exists, or we'll skip
    dist_dir = base_dir / "dist"
    build_dir = base_dir / "build"
    
    # Clean previous builds
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)
        
    print("[*] Cleaned previous build directories.")

    # PyInstaller arguments
    args = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--name=RenderFox",
        "--windowed",  # No console window
        "--onedir",    # Folder output (easier for debugging than --onefile)
        # "--onefile", # Uncomment for single file exe (slower startup)
        
        # Add data directories
        f"--add-data={base_dir / 'src'}{os.pathsep}src",
        f"--add-data={base_dir / 'resources'}{os.pathsep}resources",
        
        # Hidden imports (often needed for these libs)
        "--hidden-import=pymeshlab",
        "--hidden-import=trimesh",
        "--hidden-import=open3d",
        "--hidden-import=torch",
        "--hidden-import=transformers",
        "--hidden-import=transformers.models.clip",
        "--hidden-import=transformers.models.clip.modeling_clip",
        "--hidden-import=transformers.models.clip.processing_clip",
        "--hidden-import=transformers.models.clip.tokenization_clip",
        "--hidden-import=huggingface_hub",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PyQt6.QtSvg",
        "--hidden-import=PyQt6.QtSvgWidgets",
        "--hidden-import=PyQt6.QtOpenGL",
        "--hidden-import=PyQt6.QtOpenGLWidgets",
        "--hidden-import=scipy.spatial.transform._rotation_groups",
        "--hidden-import=sklearn.utils._typedefs",
        "--hidden-import=sklearn.neighbors._partition_nodes",
        "--hidden-import=sklearn.externals.array_api_compat.numpy.fft",
        "--hidden-import=sklearn.externals.array_api_compat.numpy",
        "--hidden-import=sklearn._cyutility",
        "--hidden-import=sklearn.utils._cython_blas",
        "--hidden-import=sklearn.neighbors.quad_tree",
        "--hidden-import=sklearn.tree._utils",
        "--hidden-import=sklearn.utils._heap",
        "--hidden-import=sklearn.utils._sorting",
        "--hidden-import=sklearn.utils._vector_sentinel",
        "--hidden-import=sklearn.metrics._pairwise_distances_reduction",
        "--hidden-import=sklearn.metrics._dist_metrics",
        "--hidden-import=sklearn.tree._partitioner",
        "--hidden-import=sklearn.tree._criterion",
        "--hidden-import=sklearn.tree._splitter",
        "--hidden-import=sklearn.tree._tree",
        
        # Exclude unnecessary modules to save space
        "--exclude-module=tkinter",
        "--exclude-module=matplotlib",
        "--exclude-module=notebook",
        "--exclude-module=PyQt5",
        "--exclude-module=PySide6",
        
        str(main_script)
    ]
    
    # Add icon if it exists
    if icon_path.exists():
        args.insert(4, f"--icon={icon_path}")
    else:
        print("[!] Icon file not found at resources/icon.ico. Using default icon.")

    print(f"[*] Running PyInstaller with command:\n{' '.join(args)}")
    
    try:
        subprocess.check_call(args)
        print("\n[OK] Build Complete!")
        print(f"[*] Executable is located at: {dist_dir / 'RenderFox' / 'RenderFox.exe'}")
        print("[*] Ready for NSIS packaging.")
        
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build Failed with error code {e.returncode}")
        sys.exit(1)

if __name__ == "__main__":
    build_executable()
