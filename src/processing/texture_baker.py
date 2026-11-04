"""
Texture Baking Module for RenderFox
===================================
Handles transfer of details (Normals, Color, AO) from High-Poly to Low-Poly meshes.
Uses PyMeshLab for processing.
"""

import os
import logging
from typing import Dict, Any, Optional, Tuple

try:
    import pymeshlab
    PYMESHLAB_AVAILABLE = True
except ImportError:
    PYMESHLAB_AVAILABLE = False

from PyQt6.QtCore import QObject, pyqtSignal, QThread

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
            Dict containing paths to generated textures.
        """
        if not PYMESHLAB_AVAILABLE:
            self.error_occurred.emit("PyMeshLab is not installed.")
            return {}

        results = {}
        base_name = os.path.splitext(os.path.basename(low_poly_path))[0]
        
        try:
            self.progress_update.emit(10, "Loading meshes...")
            
            # 1. Load Low Poly (Target)
            self.ms = pymeshlab.MeshSet()
            self.ms.load_new_mesh(low_poly_path) # Index 0
            
            # Check for UVs on Low Poly
            m = self.ms.current_mesh()
            if not m.has_wedge_tex_coord():
                self.progress_update.emit(15, "Generating UVs for Low Poly...")
                # Simple parametrization if missing
                # 'parametrization_trivial_per_triangle' is robust but fragmented
                # 'parametrization_flat_plane' is better for some shapes
                # Let's try a basic atlas generation
                try:
                    self.ms.apply_filter('compute_texcoord_parametrization_triangle_trivial_per_wedge', 
                                       textdim=resolution, border=0, method='Basic')
                except Exception as e:
                    logging.warning(f"UV Generation failed: {e}")
            
            # 2. Load High Poly (Source)
            self.ms.load_new_mesh(high_poly_path) # Index 1
            
            self.progress_update.emit(30, "Starting Bake...")
            
            # 3. Bake Normals
            if bake_normals:
                self.progress_update.emit(40, "Baking Normal Map...")
                normal_path = os.path.join(output_dir, f"{base_name}_normal.png")
                
                # Transfer attributes: Normal Map
                # Source: 1 (High), Target: 0 (Low)
                self.ms.apply_filter('transfer_attributes_to_texture_per_vertex', 
                                   sourcemesh=1, 
                                   targetmesh=0,
                                   attributeenum='Vertex Normal',
                                   textname=normal_path,
                                   textw=resolution,
                                   texth=resolution,
                                   overwrite=True,
                                   pullpush=True) # Fills gaps
                
                results['normal'] = normal_path
                
            # 4. Bake Diffuse / Vertex Color
            if bake_diffuse:
                self.progress_update.emit(60, "Baking Diffuse Map...")
                diffuse_path = os.path.join(output_dir, f"{base_name}_diffuse.png")
                
                # Transfer attributes: Color
                self.ms.apply_filter('transfer_attributes_to_texture_per_vertex', 
                                   sourcemesh=1, 
                                   targetmesh=0,
                                   attributeenum='Vertex Color', # Vertex Color
                                   textname=diffuse_path,
                                   textw=resolution,
                                   texth=resolution,
                                   overwrite=True,
                                   pullpush=True)
                
                results['diffuse'] = diffuse_path

            # 5. Bake AO (Ambient Occlusion)
            if bake_ao:
                self.progress_update.emit(80, "Baking Ambient Occlusion...")
                ao_path = os.path.join(output_dir, f"{base_name}_ao.png")
                
                # Calculate AO on High Poly first? Or transfer?
                # Usually better to calculate on High Poly then transfer.
                
                # Step A: Compute AO on High Poly (Index 1)
                self.ms.set_current_mesh(1)
                self.ms.apply_filter('compute_ambient_occlusion_per_vertex')
                
                # Step B: Transfer AO (which is stored as vertex quality/color usually, or specific AO attribute)
                # PyMeshLab's transfer filter usually transfers Color or Normal. 
                # Transferring AO specifically might require mapping AO to Vertex Color first.
                
                # Map AO to Vertex Color on High Poly
                # 'per_vertex_quality_to_color' (AO is often stored in Quality)
                self.ms.apply_filter('colorize_by_vertex_quality')
                
                # Step C: Transfer Color (now AO) to Texture on Low Poly
                self.ms.apply_filter('transfer_attributes_to_texture_per_vertex', 
                                   sourcemesh=1, 
                                   targetmesh=0,
                                   attributeenum='Vertex Color',
                                   textname=ao_path,
                                   textw=resolution,
                                   texth=resolution,
                                   overwrite=True,
                                   pullpush=True)
                                   
                results['ao'] = ao_path

            self.progress_update.emit(100, "Baking Complete!")
            self.baking_complete.emit(True, results)
            return results

        except Exception as e:
            logging.error(f"Baking failed: {e}")
            self.error_occurred.emit(str(e))
            self.baking_complete.emit(False, {})
            return {}

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
