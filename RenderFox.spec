# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\MyApps\\RenderFox\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\MyApps\\RenderFox\\src', 'src'), ('D:\\MyApps\\RenderFox\\resources', 'resources'), ('D:\\MyApps\\RenderFox\\lib\\assimp-vc143-mt.dll', 'lib')],
    hiddenimports=['pymeshlab', 'trimesh', 'pyassimp', 'open3d', 'torch', 'transformers', 'transformers.models.clip', 'transformers.models.clip.modeling_clip', 'transformers.models.clip.processing_clip', 'transformers.models.clip.tokenization_clip', 'huggingface_hub', 'PIL', 'PIL.Image', 'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'scipy.spatial.transform._rotation_groups', 'sklearn.utils._typedefs', 'sklearn.neighbors._partition_nodes', 'sklearn.externals.array_api_compat.numpy.fft', 'sklearn.externals.array_api_compat.numpy', 'sklearn._cyutility', 'sklearn.utils._cython_blas', 'sklearn.neighbors.quad_tree', 'sklearn.tree._utils', 'sklearn.utils._heap', 'sklearn.utils._sorting', 'sklearn.utils._vector_sentinel', 'sklearn.metrics._pairwise_distances_reduction', 'sklearn.metrics._dist_metrics', 'sklearn.tree._partitioner', 'sklearn.tree._criterion', 'sklearn.tree._splitter', 'sklearn.tree._tree'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'notebook', 'PyQt5', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RenderFox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:\\MyApps\\RenderFox\\resources\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RenderFox',
)
