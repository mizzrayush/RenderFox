"""
Texture Baking Module for RenderFox
===================================
Handles transfer of details (Normals, Color, AO) from High-Poly to Low-Poly meshes.
Uses PyMeshLab for processing.

Three facts about the installed PyMeshLab drive the shape of this module, and
each was measured against the library rather than assumed:

* `transfer_attributes_to_texture_per_vertex` rasterises into a texture that
  must already be attached to the target mesh. Without `set_texture_per_mesh`
  first, it raises "Mesh has no associated texture to overwrite".
* `textname` names that in-memory texture - it is not an output path, and a name
  the mesh does not know is accepted silently. A texture loaded from a file is
  keyed by its basename, and the dummy texture is always keyed
  `dummy_texture`; the image reaches the disk only through
  `Mesh.texture(name).save(path)`.
* transferring `attributeenum='Vertex Quality'` writes a black image whatever
  the scalar range, so AO is rasterised through vertex colours instead: colour
  the scalar with a luminance-monotone ramp, desaturate it, then stretch the
  measured band to the full 0-255 range.
"""

import os
import logging
from typing import Dict

from PIL import Image

try:
    import pymeshlab
    PYMESHLAB_AVAILABLE = True
except ImportError:
    PYMESHLAB_AVAILABLE = False

from PyQt6.QtCore import QObject, pyqtSignal, QThread

# MeshLab ramp whose perceived luminance rises monotonically with the scalar, so
# desaturating it cannot fold two different occlusion values into one grey.
AO_COLORMAP = 'Viridis'
AO_DESATURATION = 'Luminosity'


class TextureBaker(QObject):
    """
    Worker class for texture baking operations.
    Can be moved to a separate thread.
    """
    
    # Signals
    progress_update = pyqtSignal(int, str)
    baking_complete = pyqtSignal(bool, dict) # success, results dict
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.ms = None
        if PYMESHLAB_AVAILABLE:
            self.ms = pymeshlab.MeshSet()

    @property
    def target_mesh(self):
        return 0

    @property
    def source_mesh(self):
        return 1

    def bake(self, high_poly_path: str, low_poly_path: str, output_dir: str, 
             resolution: int = 1024, bake_normals: bool = True, 
             bake_diffuse: bool = True, bake_ao: bool = True) -> Dict[str, str]:
        """
        Perform baking operations.
        
        Args:
            high_poly_path: Path to source high-poly mesh
            low_poly_path: Path to target low-poly mesh
            output_dir: Directory to save textures
            resolution: Texture resolution (e.g., 1024, 2048)
            bake_normals: Whether to bake normal map
            bake_diffuse: Whether to bake diffuse/color map
            bake_ao: Whether to bake Ambient Occlusion
            
        Returns:
            Dict containing paths to generated textures. Only maps verified to
            exist on disk are included; success is False unless every requested
            map is there.
        """
        if not PYMESHLAB_AVAILABLE:
            self.error_occurred.emit("PyMeshLab is not installed.")
            return {}

        resolution = max(8, int(resolution))
        base_name = os.path.splitext(os.path.basename(low_poly_path))[0]
        requested = []
        if bake_normals:
            requested.append('normal')
        if bake_diffuse:
            requested.append('diffuse')
        if bake_ao:
            requested.append('ao')
        if not requested:
            self.error_occurred.emit("Nothing to bake: all three maps were turned off.")
            return {}

        results = {}
        failures = {}
        try:
            self.progress_update.emit(10, "Loading meshes...")
            os.makedirs(output_dir, exist_ok=True)

            # 1. Low Poly (Target), index 0. A texture needs UVs to rasterise into.
            self.ms = pymeshlab.MeshSet()
            self.ms.load_new_mesh(low_poly_path)
            if not self.ms.current_mesh().has_wedge_tex_coord():
                self.progress_update.emit(15, "Generating UVs for Low Poly...")
                self.ms.apply_filter(
                    'compute_texcoord_parametrization_triangle_trivial_per_wedge',
                    textdim=resolution, border=0, method='Basic')

            # 2. High Poly (Source), index 1.
            self.ms.load_new_mesh(high_poly_path)
            if self.ms.mesh_number() < 2:
                raise ValueError(f"Could not load the high-poly mesh: {high_poly_path}")

            self.progress_update.emit(30, "Starting Bake...")

            for index, kind in enumerate(requested):
                path = os.path.join(output_dir, f"{base_name}_{kind}.png")
                self.progress_update.emit(40 + index * 20, f"Baking {kind.title()} Map...")
                try:
                    self._bake_one(kind, path, resolution)
                except Exception as error:
                    logging.warning(f"{kind} bake failed: {error}")
                    failures[kind] = str(error).splitlines()[0]
                else:
                    results[kind] = path

            if failures:
                detail = "; ".join(f"{kind}: {why}" for kind, why in failures.items())
                self.progress_update.emit(100, "Baking incomplete")
                self.error_occurred.emit(f"Some maps could not be baked - {detail}")
                self.baking_complete.emit(False, results)
                return results

            self.progress_update.emit(100, "Baking Complete!")
            self.baking_complete.emit(True, results)
            return results

        except Exception as e:
            logging.error(f"Baking failed: {e}")
            self.error_occurred.emit(str(e))
            self.baking_complete.emit(False, results)
            return {}

    def _bake_one(self, kind: str, path: str, resolution: int) -> None:
        """Produce one map and confirm the file really landed."""
        if kind == 'normal':
            attribute = 'Vertex Normal'
        elif kind == 'diffuse':
            self.ms.set_current_mesh(self.source_mesh)
            if not self.ms.current_mesh().has_vertex_color():
                raise ValueError("the high-poly mesh has no vertex colors to bake")
            attribute = 'Vertex Color'
        elif kind == 'ao':
            self._bake_ao(path, resolution)
            return
        else:
            raise ValueError(f"unknown map kind {kind!r}")

        self._transfer(attribute, path, resolution)
        self._require_image(path)

    def _bake_ao(self, path: str, resolution: int) -> None:
        """Rasterise ambient occlusion as a full-range grayscale map."""
        self.ms.set_current_mesh(self.source_mesh)
        self.ms.apply_filter('compute_scalar_ambient_occlusion')
        # The raw occlusion scalar is an unbounded distance sum; only its order
        # matters, so stretch it across 0-1 before it becomes a colour.
        self.ms.apply_filter('compute_scalar_by_function_per_vertex', q='q', normalize=True)
        self.ms.apply_filter('compute_color_from_scalar_per_vertex', colormap=AO_COLORMAP)
        self.ms.apply_filter('apply_color_desaturation_per_vertex', method=AO_DESATURATION)

        # A monotone ramp still covers a band, not the whole byte range, so read
        # the band back off this mesh and levels-stretch it to 0-255.
        colors = self.ms.current_mesh().vertex_color_matrix()[:, :3]
        low = int(round(float(colors.min()) * 255.0))
        high = int(round(float(colors.max()) * 255.0))
        if high - low >= 2:
            self.ms.apply_filter('apply_color_level_adjustment_per_vertex',
                                 in_min=max(0, low), in_max=min(255, high),
                                 out_min=0, out_max=255)

        self._transfer('Vertex Color', path, resolution)
        self._require_image(path)

    def _transfer(self, attribute: str, path: str, resolution: int) -> None:
        """Rasterise one high-poly attribute into a fresh texture on the low poly.

        The blank texture is a file this method writes and removes itself. The
        alternative, `use_dummy_texture=True`, makes this build drop a
        `checkerboard.png` into the process working directory on the first bake
        of every run - invisible to the user until it litters their project.
        """
        self.ms.set_current_mesh(self.target_mesh)
        blank = f'{path}.blank.png'
        Image.new('RGB', (resolution, resolution), (0, 0, 0)).save(blank)
        try:
            self.ms.apply_filter('set_texture_per_mesh', textname=blank,
                                 use_dummy_texture=False)
            # This build keys a loaded texture by its file name, so the key is
            # the basename and each map gets its own raster.
            name = os.path.basename(blank)
            if name not in self.ms.current_mesh().textures():
                raise RuntimeError("PyMeshLab attached no texture to the target mesh")
            self.ms.apply_filter('transfer_attributes_to_texture_per_vertex',
                                 sourcemesh=self.source_mesh,
                                 targetmesh=self.target_mesh,
                                 attributeenum=attribute,
                                 textname=name,
                                 textw=resolution,
                                 texth=resolution,
                                 overwrite=True,
                                 pullpush=True)
            self.ms.current_mesh().texture(name).save(path)
        finally:
            if os.path.exists(blank):
                os.remove(blank)

    @staticmethod
    def _require_image(path: str) -> None:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise RuntimeError(f"PyMeshLab reported success but wrote no image at {path}")


class TextureBakerThread(QThread):
    """Thread wrapper for TextureBaker."""
    
    progress_update = pyqtSignal(int, str)
    baking_complete = pyqtSignal(bool, dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, high_poly, low_poly, output_dir, resolution, options):
        super().__init__()
        self.high_poly = high_poly
        self.low_poly = low_poly
        self.output_dir = output_dir
        self.resolution = resolution
        self.options = options
        self.baker = TextureBaker()
        
        # Forward signals
        self.baker.progress_update.connect(self.progress_update)
        self.baker.baking_complete.connect(self.baking_complete)
        self.baker.error_occurred.connect(self.error_occurred)
        
    def run(self):
        self.baker.bake(
            self.high_poly, 
            self.low_poly, 
            self.output_dir, 
            self.resolution,
            bake_normals=self.options.get('normals', True),
            bake_diffuse=self.options.get('diffuse', True),
            bake_ao=self.options.get('ao', True)
        )
