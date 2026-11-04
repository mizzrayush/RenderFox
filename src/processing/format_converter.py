"""
Format converter for batch converting between different 3D file formats.
Inspired by the robust Blendr Kraft cross format converter.
"""

import os
import sys
import tempfile
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# pyassimp looks for the assimp build in its own package folder and in every directory
# already on PATH (measured: pyassimp 5.2.5, helper.search_library). Nothing is in the
# package folder here, so the DLL in this app's lib/ has to be put on PATH before
# pyassimp is imported - and the candidate list has to include where a PyInstaller
# build actually unpacks it, because that is not three directories above __file__.
def _assimp_lib_dirs():
    roots = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        roots.append(meipass)
    if getattr(sys, 'frozen', False):
        roots.append(os.path.dirname(sys.executable))
    dirs = []
    for root in roots:
        candidate = os.path.join(root, 'lib')
        if os.path.isdir(candidate) and candidate not in dirs:
            dirs.append(candidate)
    # A folder that actually holds an assimp build first, so a stale lib/ alongside
    # the source cannot outrank the one the bundle shipped.
    dirs.sort(key=lambda d: 0 if any('assimp' in f.lower() and f.lower().endswith('.dll')
                                     for f in os.listdir(d)) else 1)
    return dirs


_ASSIMP_LIB_DIRS = _assimp_lib_dirs()
for _lib_dir in _ASSIMP_LIB_DIRS:
    if _lib_dir and _lib_dir not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _lib_dir + os.pathsep + os.environ.get('PATH', '')

# Try to import conversion libraries with proper error handling
try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

# Helper: a format as the capability table keys it - lower case, no leading dot.
def _extension(value: str) -> str:
    return (value or '').lower().lstrip('.')


# MeshLab's FBX reader does not report a malformed file - it takes an access violation
# and the process dies with it (measured: exit 0xC0000005 on a file that was merely
# named .fbx). assimp raises a catchable AssimpError for the same bytes. So two things
# have to be true: a file with no FBX header never reaches a reader, and for an .fbx
# source the library that fails cleanly is the one tried first.
_FBX_BINARY_MAGIC = b'Kaydara FBX'
_FBX_ASCII_MARKERS = (b'FBXHeaderExtension', b'; FBX')


def _looks_like_fbx(path: str) -> bool:
    try:
        with open(path, 'rb') as handle:
            head = handle.read(64)
    except OSError:
        return False
    return (head.startswith(_FBX_BINARY_MAGIC)
            or any(marker in head for marker in _FBX_ASCII_MARKERS))


# Helper: the folder a converted file lands in. dirname() is '' for a bare filename,
# and makedirs('') raises - which is what an output path typed without a folder did.
def _prepare_output_dir(output_file: str) -> None:
    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)


# Helper: the options that would actually change the file. A panel hands scale/center/
# normalize/repair whether or not the user touched them, and reporting "scale not
# applied" for the default 1.0 would be a warning about nothing.
def _meaningful_options(options: Optional[Dict]) -> List[str]:
    if not options:
        return []
    live = []
    scale = options.get('scale')
    if isinstance(scale, (int, float)) and float(scale) != 1.0:
        live.append('scale')
    live += [key for key in ('center', 'normalize', 'repair', 'remove_duplicates')
             if options.get(key)]
    return live


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

# pyassimp raises AssimpError, which inherits BaseException rather than Exception, so
# `except Exception` around an assimp call does not catch it: the failure left the
# converter and reached the UI as a traceback instead of a row that says it failed.
CONVERSION_ERRORS: Tuple[type, ...] = (Exception, pyassimp.AssimpError) if ASSIMP_AVAILABLE else (Exception,)

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
    
    # What each library can actually carry, measured on this machine against the
    # installed trimesh/pymeshlab/assimp build. tests/test_format_converter_contract.py
    # converts every pair this table implies and fails if a row stops being true, so
    # the claims here are not a wish list - see the module docstring of that file.
    #
    # trimesh reads and writes the same seven formats and cannot open .dae or .fbx at
    # all (.dae needs pycollada, which is not installed and is not needed: pymeshlab
    # reads both). pymeshlab opens everything but can only save the non-GL formats and
    # Collada - it has no glTF writer. assimp opens everything and is the *only* way
    # this app can produce an .fbx, but it has no .off writer.
    _CAPABILITIES = {
        'trimesh': {
            'read': {'obj', 'ply', 'stl', 'gltf', 'glb', 'off', '3mf'},
            'write': {'obj', 'ply', 'stl', 'gltf', 'glb', 'off', '3mf'},
            'applies_options': True,
        },
        'pymeshlab': {
            'read': {'obj', 'ply', 'stl', 'gltf', 'glb', 'dae', 'fbx', 'off', '3mf'},
            'write': {'obj', 'ply', 'stl', 'dae', 'off', '3mf'},
            'applies_options': False,
        },
        'assimp': {
            'read': {'obj', 'ply', 'stl', 'gltf', 'glb', 'dae', 'fbx', 'off', '3mf'},
            'write': {'obj', 'ply', 'stl', 'gltf', 'glb', 'dae', 'fbx', '3mf'},
            'applies_options': False,
        },
    }

    # pyassimp.export() wants the exporter's *id*, which is not always the extension:
    # the DLL this app ships reports gltf as "gltf2", glb as "glb2" and dae as "collada".
    # Handing it "dae" - the old behaviour - made the Collada exporter a no-op failure.
    _ASSIMP_EXPORT_IDS = {
        'obj': 'obj', 'ply': 'ply', 'stl': 'stl', 'gltf': 'gltf2', 'glb': 'glb2',
        'dae': 'collada', 'fbx': 'fbx', '3mf': '3mf',
    }

    # Tried in this order: the first library that can do the whole job wins, and trimesh
    # is first because it is the only one that can apply the conversion options the UI
    # collects (scale/center/normalize/repair).
    _METHOD_ORDER = ('trimesh', 'pymeshlab', 'assimp')

    # Sources whose first-choice reader can crash the process instead of raising; the
    # clean-failing library is tried before MeshLab for these.
    _CLEAN_FAILURE_FIRST = {'fbx': ('trimesh', 'assimp', 'pymeshlab')}

    # Kept for callers that read the matrix as data; derived from _CAPABILITIES so the
    # two cannot disagree.
    @classmethod
    def supported_conversions(cls) -> Dict[str, List[str]]:
        """source extension -> the target extensions a library here can reach."""
        return {f'.{src}': cls.supported_targets(f'.{src}') for src in cls._CAPABILITIES['trimesh']['read'] |
                cls._CAPABILITIES['pymeshlab']['read']}

    @classmethod
    def supported_targets(cls, source_format: str) -> List[str]:
        source = _extension(source_format)
        targets = set()
        for capability in cls._CAPABILITIES.values():
            if source in capability['read']:
                targets |= capability['write']
        targets.discard(source)
        return sorted(f'.{t}' for t in targets)
    
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
        """Target formats the libraries installed *here* can write from this source."""
        source = _extension(source_format)
        targets = set()
        for name, capability in self._CAPABILITIES.items():
            if self.libraries_status.get(name) and source in capability['read']:
                targets |= capability['write']
        targets.discard(source)
        return sorted(f'.{target}' for target in targets)

    def conversion_libraries(self, source_format: str, target_format: str) -> List[str]:
        """The libraries that can carry this whole pair here, in the order to try them.

        A single library does the read and the write: pymeshlab and assimp hand back a
        file from the scene they loaded, so a job split across two of them has no way to
        pass the mesh along.
        """
        source = _extension(source_format)
        target = _extension(target_format)
        if source == target:
            return []
        order = self._CLEAN_FAILURE_FIRST.get(source, self._METHOD_ORDER)
        return [name for name in order
                if self.libraries_status.get(name)
                and source in self._CAPABILITIES[name]['read']
                and target in self._CAPABILITIES[name]['write']]

    def _source_blocker(self, input_file: str) -> Optional[str]:
        """A reason not to hand this file to a reader, or None to go ahead.

        Only .fbx needs the check: without it a file that is merely named .fbx reaches
        MeshLab's FBX reader, which answers an access violation rather than an error.
        """
        if _extension(Path(input_file).suffix) == 'fbx' and not _looks_like_fbx(input_file):
            return (f'{os.path.basename(input_file)} has no FBX header - it is probably '
                    f'a different format with a changed extension')
        return None

    def conversion_blocker(self, source_format: str, target_format: str) -> str:
        """Why a pair cannot be done here, naming the library that would fix it."""
        source = _extension(source_format)
        target = _extension(target_format)
        here = ', '.join(self.get_available_libraries()) or 'none'
        if source == target:
            return f'{source} is already {target} - nothing to convert'
        able = [name for name, capability in self._CAPABILITIES.items()
                if source in capability['read'] and target in capability['write']]
        if not able:
            return (f'No library this app uses can write .{target} from .{source} '
                    f'(available: {here}).')
        reason = (f'.{target} from .{source} needs {" or ".join(able)}, which is not '
                  f'available here (available: {here}).')
        if 'assimp' in able:
            # The python binding is useless without the native library beside it, and
            # that is the one failure a user cannot diagnose from the traceback.
            looked = ', '.join(_ASSIMP_LIB_DIRS) or 'no lib/ folder in this install'
            reason += (' pyassimp needs an assimp build beside it - the package alone '
                       f'does not carry one. Looked in: {looked}.')
        return reason

    def can_convert(self, source_format: str, target_format: str) -> bool:
        """Check if conversion between formats is supported by what is installed"""
        return bool(self.conversion_libraries(source_format, target_format))
    
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

        blocked = self._source_blocker(input_file)
        if blocked:
            return {'success': False, 'message': blocked, 'method': None}
        
        source_ext = Path(input_file).suffix.lower()
        target_ext = Path(output_file).suffix.lower()
        
        candidates = self.conversion_libraries(source_ext, target_ext)
        if not candidates:
            return {
                'success': False,
                'message': self.conversion_blocker(source_ext, target_ext),
                'method': None
            }

        self.conversion_started.emit(input_file, target_ext, f"Using {candidates[0]}")

        requested = _meaningful_options(options)
        last_error = None

        for method_name in candidates:
            try:
                convert = getattr(self, f"_convert_with_{method_name}")
                result = convert(input_file, output_file, options or {})

                if result['success']:
                    # Only trimesh reads the mesh into something the options can touch;
                    # say which settings this file went out without, rather than let the
                    # panel imply it applied the ones the user ticked.
                    skipped = [key for key in requested
                               if not self._CAPABILITIES[method_name]['applies_options']]
                    result['method'] = method_name
                    result['options_skipped'] = skipped
                    message = f"Converted using {method_name}"
                    if skipped:
                        message += f" ({', '.join(skipped)} not applied)"
                    self.conversion_completed.emit(input_file, True, message)
                    return result

                last_error = result['message']

            except CONVERSION_ERRORS as e:
                last_error = f"{method_name} failed: {str(e)}"
                continue

        # Every library that could do the job tried and failed
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
            
            _prepare_output_dir(output_file)
            
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
            
            # mesh_number() is the 2025.7 name; number_of_meshes() raises here and
            # this fallback only runs when trimesh fails, so it never surfaced.
            if ms.mesh_number() == 0:
                return {'success': False, 'message': 'No mesh data found'}
            
            _prepare_output_dir(output_file)
            
            # Save to output format
            ms.save_current_mesh(output_file)
            
            return {'success': True, 'message': 'Conversion successful'}
            
        except Exception as e:
            return {'success': False, 'message': f'PyMeshLab conversion failed: {str(e)}'}
    
    def _convert_with_assimp(self, input_file: str, output_file: str, options: Dict) -> Dict[str, any]:
        """Convert using pyassimp - the only path here that can produce an .fbx."""
        if not ASSIMP_AVAILABLE:
            return {'success': False, 'message': 'Assimp not available'}

        target = _extension(Path(output_file).suffix)
        exporter = self._ASSIMP_EXPORT_IDS.get(target)
        if exporter is None:
            return {'success': False,
                    'message': f'assimp has no .{target} exporter (it writes '
                               f'{", ".join(sorted(self._ASSIMP_EXPORT_IDS))})'}

        try:
            _prepare_output_dir(output_file)

            # pyassimp.load() is a context manager, not a loader that hands back a
            # scene: the old `scene = pyassimp.load(path)` put a generator wrapper in
            # `scene`, passed it to aiExportScene, and assimp answered AssimpError -
            # which inherits BaseException, so it skipped the except below and left the
            # converter altogether. This path had never once succeeded.
            with pyassimp.load(input_file) as scene:
                if not scene or not getattr(scene, 'meshes', None):
                    return {'success': False, 'message': 'assimp loaded no mesh from this file'}
                pyassimp.export(scene, output_file, exporter)

            if not os.path.isfile(output_file) or os.path.getsize(output_file) == 0:
                return {'success': False, 'message': f'assimp wrote an empty .{target}'}

            return {'success': True, 'message': 'Conversion successful'}

        except CONVERSION_ERRORS as e:
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
                    'method': result.get('method', 'unknown'),
                    'options_skipped': result.get('options_skipped', [])
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
        
        # Which library actually carried these files. Reporting the first *installed*
        # library made the summary claim trimesh did work it never touched.
        results['processing_time'] = time.time() - start_time
        used = sorted({entry['method'] for entry in results['successful'] if entry['method']})
        results['library_used'] = ', '.join(used) if used else 'None'
        skipped = sorted({key for entry in results['successful'] for key in entry['options_skipped']})
        if skipped:
            results['options_skipped'] = skipped
            results['errors'].append(
                f"not applied by the libraries used: {', '.join(skipped)}")
        
        # Emit batch completion signal
        self.batch_completed.emit(results)
        
        return results
    
    def convert_with_lod_generation(self, input_file: str, output_dir: str,
                                  target_format: SupportedFormat, 
                                  lod_levels: List[float] = None,
                                  options: Dict = None) -> List[str]:
        """
        Convert a file and generate LOD versions in the target format.
        
        Args:
            input_file: Input file path
            output_dir: Output directory
            target_format: Target format
            lod_levels: List of LOD reduction ratios (default: [1.0, 0.75, 0.5, 0.25])
            options: The same conversion options a single convert_file() honours
            
        Returns:
            List of generated files
        """
        if lod_levels is None:
            lod_levels = [1.0, 0.75, 0.5, 0.25]
        
        if not TRIMESH_AVAILABLE:
            logger.warning("LOD generation requires trimesh library")
            return []
        
        try:
            # Load the mesh - through the same readers the preview uses, so an LOD
            # chain can be cut from a .fbx or .dae as well as from an .obj.
            mesh, _note = self._read_as_trimesh(input_file)
            
            if mesh is None:
                return []

            if _meaningful_options(options):
                mesh = self._apply_conversion_options(mesh, options)
            
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
                
                # Export LOD. trimesh has no .dae or .fbx writer, so a chain that can
                # only be saved as OBJ is not the target the caller asked for; hand
                # those two to the library that does have one.
                output_file = os.path.join(output_dir, f"{base_name}{lod_suffix}{target_format.value}")
                if _extension(target_format.value) in self._CAPABILITIES['trimesh']['write']:
                    lod_mesh.export(output_file)
                else:
                    scratch = os.path.join(output_dir, f".lod_scratch_{i}.obj")
                    try:
                        lod_mesh.export(scratch)
                        written = self.convert_file(scratch, output_file, None)
                    finally:
                        if os.path.isfile(scratch):
                            os.remove(scratch)
                    if not written['success']:
                        logger.warning(f"LOD {i} not written as {target_format.value}: {written['message']}")
                        continue
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
            
            # Remove duplicates. `remove_duplicate_faces` still answers but is
            # deprecated and its own message says it was to be removed in March 2024;
            # the failure below would return the untouched mesh, so the option would
            # stop working in silence rather than loudly.
            if options.get('remove_duplicates', False):
                processed_mesh.update_faces(processed_mesh.unique_faces())
                
        except Exception as e:
            logger.warning(f"Error applying conversion options: {e}")
            # Return original mesh if processing fails
            return mesh
        
        return processed_mesh
    
    def _read_as_trimesh(self, input_file: str) -> Tuple[Optional['trimesh.Trimesh'], str]:
        """The file as one mesh, from the first library here that can open it.

        Returns (mesh, what carried it) or (None, what was tried). trimesh has no reader
        for .dae or .fbx, so asking it directly was what made the two formats this tab
        advertises come back "Could not load mesh".
        """
        if not TRIMESH_AVAILABLE:
            return None, 'trimesh is not installed'

        blocked = self._source_blocker(input_file)
        if blocked:
            return None, blocked

        tried = []

        try:
            mesh = _as_trimesh(trimesh.load(input_file))
            if mesh is not None and len(mesh.vertices):
                return mesh, 'trimesh'
            tried.append('trimesh: no mesh')
        except CONVERSION_ERRORS as error:
            tried.append(f'trimesh: {str(error)[:60]}')

        if PYMESHLAB_AVAILABLE:
            try:
                mesh_set = pymeshlab.MeshSet()
                mesh_set.load_new_mesh(input_file)
                if mesh_set.mesh_number():
                    current = mesh_set.current_mesh()
                    if current.vertex_number():
                        return trimesh.Trimesh(
                            vertices=np.asarray(current.vertex_matrix(), dtype=np.float64),
                            faces=np.asarray(current.face_matrix(), dtype=np.int64),
                            process=False), 'pymeshlab'
                tried.append('pymeshlab: no mesh')
            except Exception as error:
                tried.append(f'pymeshlab: {str(error)[:60]}')

        if ASSIMP_AVAILABLE:
            try:
                with pyassimp.load(input_file) as scene:
                    parts = [trimesh.Trimesh(vertices=np.asarray(loaded.vertices, dtype=np.float64),
                                             faces=np.asarray(loaded.faces, dtype=np.int64),
                                             process=False)
                             for loaded in (scene.meshes or [])]
                mesh = trimesh.util.concatenate(parts) if parts else None
                if mesh is not None and len(mesh.vertices):
                    return mesh, 'assimp'
                tried.append('assimp: no mesh')
            except CONVERSION_ERRORS as error:
                tried.append(f'assimp: {str(error)[:60]}')

        return None, '; '.join(tried) or 'no library could open the file'

    def get_conversion_preview(self, input_file: str) -> Dict:
        """Preview information about a file for conversion."""
        try:
            mesh, opened_with = self._read_as_trimesh(input_file)
            if mesh is None:
                return {"error": f"Could not load mesh ({opened_with})"}

            return {
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "volume": float(mesh.volume) if mesh.is_volume else 0.0,
                "surface_area": float(mesh.area),
                "bounds": mesh.bounds.tolist(),
                "is_watertight": mesh.is_watertight,
                "opened_with": opened_with,
                "source_format": self.detect_format(input_file).value if self.detect_format(input_file) else "unknown"
            }

        except CONVERSION_ERRORS as e:
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
            },
            # The Pre-Processing tab builds its target list from this table, so a format
            # missing here is offered as "OFF - Unknown Format" to the user.
            '.off': {
                'name': 'OFF',
                'description': 'Plain mesh format from the Surface Tracking package',
                'supports_materials': False,
                'supports_animations': False,
                'binary': False
            },
            '.3mf': {
                'name': '3D Manufacturing Format',
                'description': 'Zipped model format used by 3D printing tools',
                'supports_materials': True,
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