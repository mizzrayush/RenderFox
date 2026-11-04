"""
Format converter for batch converting between different 3D file formats.
Inspired by the robust Blendr Kraft cross format converter.
"""

import os
import sys
import tempfile
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# Add lib directory to PATH for DLL loading
lib_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'lib')
if os.path.exists(lib_dir) and lib_dir not in os.environ.get('PATH', ''):
    os.environ['PATH'] = lib_dir + os.pathsep + os.environ.get('PATH', '')

# Try to import conversion libraries with proper error handling
try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

# Helper: ensure we return a trimesh.Trimesh from a trimesh.Scene or Trimesh
def _as_trimesh(obj):
    if not TRIMESH_AVAILABLE:
        return None
    if isinstance(obj, trimesh.Trimesh):
        return obj
    if isinstance(obj, trimesh.Scene):
        # Try dump() variations and geometry dict
        try:
            dumped = obj.dump()
            if isinstance(dumped, (list, tuple)):
                return trimesh.util.concatenate(dumped) if dumped else None
            if isinstance(dumped, dict):
                return trimesh.util.concatenate(list(dumped.values())) if dumped else None
            if isinstance(dumped, trimesh.Trimesh):
                return dumped
        except Exception as e:
            logger.debug(f"Failed to dump scene in _as_trimesh: {e}")
        try:
            geoms = list(obj.geometry.values()) if hasattr(obj, 'geometry') else []
            return trimesh.util.concatenate(geoms) if geoms else None
        except Exception:
            return None
    return None

try:
    import pymeshlab
    PYMESHLAB_AVAILABLE = True
except ImportError:
    PYMESHLAB_AVAILABLE = False

try:
    import pyassimp
    ASSIMP_AVAILABLE = True
except ImportError:
    ASSIMP_AVAILABLE = False
except Exception as e:
    # Handle other errors like library not found
    logger.warning(f"Assimp library issue: {e}")
    ASSIMP_AVAILABLE = False

class SupportedFormat(Enum):
    """Supported 3D file formats for conversion."""
    OBJ = ".obj"
    PLY = ".ply"
    STL = ".stl"
    GLTF = ".gltf"
    GLB = ".glb"
    DAE = ".dae"
    FBX = ".fbx"
    OFF = ".off"
    THREE_MF = ".3mf"

@dataclass
class ConversionJob:
    """Represents a format conversion job."""
    input_file: str
    output_file: str
    source_format: SupportedFormat
    target_format: SupportedFormat
    options: Dict = None

class FormatConverter(QObject):
    """Converts 3D models between different file formats with robust error handling."""
    
    # Class variable to track if libraries have been initialized
    _libraries_initialized = False
    _shared_libraries_status = None
    
    # Signals for progress tracking
    conversion_started = pyqtSignal(str, str, str)  # input_file, output_format, method
    conversion_progress = pyqtSignal(str, int)  # file_path, progress
    conversion_completed = pyqtSignal(str, bool, str)  # file_path, success, message
    batch_completed = pyqtSignal(dict)  # results summary
    
    # Format compatibility matrix
    SUPPORTED_CONVERSIONS = {
        # Source format: [supported target formats]
        '.fbx': ['.obj', '.gltf', '.glb', '.dae', '.ply', '.stl'],
        '.obj': ['.fbx', '.gltf', '.glb', '.ply', '.stl', '.dae'],
        '.gltf': ['.obj', '.fbx', '.glb', '.ply', '.stl'],
        '.glb': ['.obj', '.fbx', '.gltf', '.ply', '.stl'],
        '.dae': ['.obj', '.gltf', '.glb', '.ply', '.stl'],
        '.ply': ['.obj', '.stl', '.gltf', '.glb'],
        '.stl': ['.obj', '.ply', '.gltf', '.glb']
    }
    
    def __init__(self):
        super().__init__()
        self.conversion_jobs: List[ConversionJob] = []
        
        # Initialize libraries status only once
        if not FormatConverter._libraries_initialized:
            FormatConverter._shared_libraries_status = {
                'trimesh': TRIMESH_AVAILABLE,
                'pymeshlab': PYMESHLAB_AVAILABLE,
                'assimp': ASSIMP_AVAILABLE
            }
            
            # Print library status only once
            available_libs = [lib for lib in FormatConverter._shared_libraries_status 
                            if FormatConverter._shared_libraries_status[lib]]
            logger.info(f"Available conversion libraries: {', '.join(available_libs) if available_libs else 'None'}")
            
            FormatConverter._libraries_initialized = True
        
        # Use shared libraries status
        self.libraries_status = FormatConverter._shared_libraries_status
    
    def get_available_libraries(self) -> List[str]:
        """Get list of available conversion libraries"""
        return [lib for lib, available in self.libraries_status.items() if available]
    
    def get_supported_formats(self) -> List[str]:
        """Get list of supported file formats."""
        return [fmt.value for fmt in SupportedFormat]
    
    def get_supported_targets(self, source_format: str) -> List[str]:
        """Get supported target formats for a source format"""
        return self.SUPPORTED_CONVERSIONS.get(source_format.lower(), [])
    
    def can_convert(self, source_format: str, target_format: str) -> bool:
        """Check if conversion between formats is supported"""
        source_ext = source_format.lower()
        target_ext = target_format.lower()
        
        if source_ext == target_ext:
            return False  # No need to convert to same format
        
        return target_ext in self.SUPPORTED_CONVERSIONS.get(source_ext, [])
    
    def is_format_supported(self, file_path: str) -> bool:
        """Check if a file format is supported."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.get_supported_formats()
    
    def detect_format(self, file_path: str) -> Optional[SupportedFormat]:
        """Detect the format of a file."""
        ext = os.path.splitext(file_path)[1].lower()
        for fmt in SupportedFormat:
            if fmt.value == ext:
                return fmt
        return None
    
    def convert_file(self, input_file: str, output_file: str, options: Dict = None) -> Dict[str, any]:
        """
        Convert a single file to another format with robust error handling.
        
        Args:
            input_file: Path to input file
            output_file: Path to output file
            options: Conversion options
            
        Returns:
            Dictionary with conversion results
        """
        if not os.path.exists(input_file):
            return {
                'success': False,
                'message': 'Input file not found',
                'method': None
            }
        
        source_ext = Path(input_file).suffix.lower()
        target_ext = Path(output_file).suffix.lower()
        
        if not self.can_convert(source_ext, target_ext):
            return {
                'success': False,
                'message': f'Conversion from {source_ext} to {target_ext} not supported',
                'method': None
            }
        
        self.conversion_started.emit(input_file, target_ext, "Determining method...")
        
        # Try conversion methods in order of preference
        conversion_methods = [
            ('trimesh', self._convert_with_trimesh),
            ('pymeshlab', self._convert_with_pymeshlab),
            ('assimp', self._convert_with_assimp)
        ]
        
        last_error = None
        
        for method_name, method_func in conversion_methods:
            if not self.libraries_status.get(method_name, False):
                continue
            
            try:
                self.conversion_started.emit(input_file, target_ext, f"Using {method_name}")
                
                result = method_func(input_file, output_file, options or {})
                
                if result['success']:
                    result['method'] = method_name
                    self.conversion_completed.emit(input_file, True, f"Converted using {method_name}")
                    return result
                else:
                    last_error = result['message']
                    
            except Exception as e:
                last_error = f"{method_name} failed: {str(e)}"
                continue
        
        # All methods failed
        error_msg = last_error or "All conversion methods failed"
        self.conversion_completed.emit(input_file, False, error_msg)
        return {
            'success': False,
            'message': error_msg,
            'method': None
        }
    
    def _convert_with_trimesh(self, input_file: str, output_file: str, options: Dict) -> Dict[str, any]:
        """Convert using trimesh library"""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'message': 'Trimesh not available'}
        
        try:
            # Load the mesh/scene
            mesh_or_scene = trimesh.load(input_file)
            
            # Normalize to a single mesh
            mesh = _as_trimesh(mesh_or_scene)
            if mesh is None:
                return {'success': False, 'message': 'Could not load as mesh'}
            
            # Apply options if provided
            if options:
                mesh = self._apply_conversion_options(mesh, options)
            
            # Create output directory
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Export the mesh
            mesh.export(output_file)
            
            return {'success': True, 'message': 'Conversion successful'}
            
        except Exception as e:
            return {'success': False, 'message': f'Trimesh conversion failed: {str(e)}'}
    
    def _convert_with_pymeshlab(self, input_file: str, output_file: str, options: Dict) -> Dict[str, any]:
        """Convert using pymeshlab library"""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'message': 'PyMeshLab not available'}
        
        try:
            # Create a new MeshSet
            ms = pymeshlab.MeshSet()
            
            # Load the input file
            ms.load_new_mesh(input_file)
            
            # Apply any necessary processing
            if ms.number_of_meshes() == 0:
                return {'success': False, 'message': 'No mesh data found'}
            
            # Create output directory
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Save to output format
            ms.save_current_mesh(output_file)
            
            return {'success': True, 'message': 'Conversion successful'}
            
        except Exception as e:
            return {'success': False, 'message': f'PyMeshLab conversion failed: {str(e)}'}
    
    def _convert_with_assimp(self, input_file: str, output_file: str, options: Dict) -> Dict[str, any]:
        """Convert using pyassimp library"""
        if not ASSIMP_AVAILABLE:
            return {'success': False, 'message': 'Assimp not available'}
        
        try:
            # Load scene with assimp
            scene = pyassimp.load(input_file)
            
            if not scene:
                return {'success': False, 'message': 'Failed to load scene with Assimp'}
            
            # Create output directory
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Export scene (Note: pyassimp export functionality is limited)
            pyassimp.export(scene, output_file, Path(output_file).suffix[1:])
            
            # Release the scene
            pyassimp.release(scene)
            
            return {'success': True, 'message': 'Conversion successful'}
            
        except Exception as e:
            return {'success': False, 'message': f'Assimp conversion failed: {str(e)}'}
    
    def batch_convert(self, input_files: List[str], output_dir: str,
                     target_format: SupportedFormat, options: Dict = None) -> Dict[str, any]:
        """
        Batch convert multiple files to a target format.
        
        Args:
            input_files: List of input file paths
            output_dir: Output directory
            target_format: Target format to convert to
            options: Conversion options
            
        Returns:
            Dictionary with batch conversion results
        """
        import time
        start_time = time.time()
        
        os.makedirs(output_dir, exist_ok=True)
        
        results = {
            'total_files': len(input_files),
            'successful': [],
            'failed': [],
            'errors': []
        }
        
        for i, input_file in enumerate(input_files):
            if not self.is_format_supported(input_file):
                error_msg = f"Skipping unsupported file: {input_file}"
                results['failed'].append({
                    'input': input_file,
                    'output': None,
                    'error': error_msg
                })
                results['errors'].append(error_msg)
                continue
            
            # Update progress
            progress = int((i / len(input_files)) * 100)
            self.conversion_progress.emit(input_file, progress)
            
            # Generate output filename
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            output_file = os.path.join(output_dir, f"{base_name}{target_format.value}")
            
            # Convert file
            result = self.convert_file(input_file, output_file, options)
            
            if result['success']:
                results['successful'].append({
                    'input': input_file,
                    'output': output_file,
                    'method': result.get('method', 'unknown')
                })
            else:
                results['failed'].append({
                    'input': input_file,
                    'output': output_file,
                    'error': result['message']
                })
                results['errors'].append(f"{input_file}: {result['message']}")
        
        # Final progress update
        self.conversion_progress.emit("", 100)
        
        # Add timing and library information
        results['processing_time'] = time.time() - start_time
        available_libs = self.get_available_libraries()
        results['library_used'] = available_libs[0] if available_libs else 'None'
        
        # Emit batch completion signal
        self.batch_completed.emit(results)
        
        return results
    
    def convert_with_lod_generation(self, input_file: str, output_dir: str,
                                  target_format: SupportedFormat, 
                                  lod_levels: List[float] = None) -> List[str]:
        """
        Convert a file and generate LOD versions in the target format.
        
        Args:
            input_file: Input file path
            output_dir: Output directory
            target_format: Target format
            lod_levels: List of LOD reduction ratios (default: [1.0, 0.75, 0.5, 0.25])
            
        Returns:
            List of generated files
        """
        if lod_levels is None:
            lod_levels = [1.0, 0.75, 0.5, 0.25]
        
        if not TRIMESH_AVAILABLE:
            logger.warning("LOD generation requires trimesh library")
            return []
        
        try:
            # Load the mesh
            mesh_obj = trimesh.load(input_file)
            mesh = _as_trimesh(mesh_obj)
            
            if mesh is None:
                return []
            
            os.makedirs(output_dir, exist_ok=True)
            generated_files = []
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            
            for i, ratio in enumerate(lod_levels):
                # Generate LOD mesh
                if ratio == 1.0:
                    lod_mesh = mesh.copy()
                    lod_suffix = ""
                else:
                    target_faces = max(4, int(len(mesh.faces) * ratio))  # Minimum 4 faces
                    try:
                        lod_mesh = mesh.simplify_quadric_decimation(target_faces)
                        if lod_mesh is None or len(lod_mesh.faces) == 0:
                            # Fallback to convex hull if simplification fails
                            lod_mesh = mesh.convex_hull
                    except Exception as e:
                        logger.debug(f"LOD simplification failed, falling back to convex hull: {e}")
                        # Final fallback
                        lod_mesh = mesh.convex_hull
                    lod_suffix = f"_LOD{i}"
                
                # Export LOD
                output_file = os.path.join(output_dir, f"{base_name}{lod_suffix}{target_format.value}")
                lod_mesh.export(output_file)
                generated_files.append(output_file)
            
            return generated_files
            
        except Exception as e:
            logger.error(f"Error in LOD conversion: {str(e)}")
            return []
    
    def _apply_conversion_options(self, mesh: 'trimesh.Trimesh', options: Dict) -> 'trimesh.Trimesh':
        """Apply conversion options to a mesh."""
        processed_mesh = mesh.copy()
        
        try:
            # Scale option
            if 'scale' in options:
                scale = options['scale']
                if isinstance(scale, (int, float)):
                    processed_mesh.apply_scale(scale)
                elif isinstance(scale, (list, tuple)) and len(scale) == 3:
                    processed_mesh.apply_scale(scale)
            
            # Center option
            if options.get('center', False):
                processed_mesh.apply_translation(-processed_mesh.center_mass)
            
            # Normalize option (fit to unit cube)
            if options.get('normalize', False):
                extents = processed_mesh.extents
                max_extent = max(extents)
                if max_extent > 0:
                    processed_mesh.apply_scale(1.0 / max_extent)
            
            # Repair option
            if options.get('repair', False):
                processed_mesh.fill_holes()
                processed_mesh.fix_normals()
            
            # Remove duplicates
            if options.get('remove_duplicates', False):
                processed_mesh.remove_duplicate_faces()
                
        except Exception as e:
            logger.warning(f"Error applying conversion options: {e}")
            # Return original mesh if processing fails
            return mesh
        
        return processed_mesh
    
    def get_conversion_preview(self, input_file: str) -> Dict:
        """Get preview information about a file for conversion."""
        try:
            if TRIMESH_AVAILABLE:
                mesh_obj = trimesh.load(input_file)
                mesh = _as_trimesh(mesh_obj)
                
                if mesh is None:
                    return {"error": "Could not load mesh"}
                
                return {
                    "vertices": len(mesh.vertices),
                    "faces": len(mesh.faces),
                    "volume": float(mesh.volume) if mesh.is_volume else 0.0,
                    "surface_area": float(mesh.area),
                    "bounds": mesh.bounds.tolist(),
                    "is_watertight": mesh.is_watertight,
                    "source_format": self.detect_format(input_file).value if self.detect_format(input_file) else "unknown"
                }
            else:
                return {"error": "No conversion libraries available for preview"}
                
        except Exception as e:
            return {"error": f"Failed to analyze file: {str(e)}"}
    
    def get_format_info(self, file_format: str) -> Dict[str, any]:
        """Get information about a specific format"""
        format_info = {
            '.fbx': {
                'name': 'Autodesk FBX',
                'description': 'Industry standard for 3D content exchange',
                'supports_materials': True,
                'supports_animations': True,
                'binary': True
            },
            '.obj': {
                'name': 'Wavefront OBJ',
                'description': 'Simple, widely supported mesh format',
                'supports_materials': True,
                'supports_animations': False,
                'binary': False
            },
            '.gltf': {
                'name': 'GL Transmission Format',
                'description': 'Modern web-optimized 3D format',
                'supports_materials': True,
                'supports_animations': True,
                'binary': False
            },
            '.glb': {
                'name': 'GL Transmission Format Binary',
                'description': 'Binary version of GLTF',
                'supports_materials': True,
                'supports_animations': True,
                'binary': True
            },
            '.dae': {
                'name': 'COLLADA',
                'description': 'XML-based interchange format',
                'supports_materials': True,
                'supports_animations': True,
                'binary': False
            },
            '.ply': {
                'name': 'Polygon File Format',
                'description': 'Simple format for storing 3D data',
                'supports_materials': False,
                'supports_animations': False,
                'binary': True
            },
            '.stl': {
                'name': 'Stereolithography',
                'description': '3D printing standard format',
                'supports_materials': False,
                'supports_animations': False,
                'binary': True
            }
        }
        
        return format_info.get(file_format.lower(), {
            'name': 'Unknown Format',
            'description': 'Format information not available',
            'supports_materials': False,
            'supports_animations': False,
            'binary': False
        })

# Legacy function for backward compatibility
def get_format_info() -> Dict[str, Dict]:
    """Get information about supported formats."""
    converter = FormatConverter()
    formats = {}
    for fmt in SupportedFormat:
        formats[fmt.value] = converter.get_format_info(fmt.value)
    return formats