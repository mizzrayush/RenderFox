"""
RenderFox Automation Engine
Provides task scheduling, workflow automation, batch processing, and trigger-based actions.
"""

import os
import time
import json
import logging
import fnmatch
import inspect
import calendar
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import queue
import schedule
import uuid

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from ..utils.app_paths import data_dir

# The packaged build has no console (`RenderFox.spec`: console=False), so the root logger is the
# only reader these threads have: the scheduler loop, the directory watcher and the task/workflow
# files all run where no pane is attached, and a failure here would otherwise be unrecoverable
# silence - a task that never ran, or a saved task list that never loaded.
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class TriggerType(Enum):
    """Automation trigger types."""
    TIME_BASED = "time_based"
    FILE_WATCH = "file_watch"
    EVENT_BASED = "event_based"
    CONDITION = "condition"
    MANUAL = "manual"


def app_data_dir() -> str:
    """The folder RenderFox keeps its own state in, as the library and telemetry do.

    Tasks and workflows used to be written relative to the working directory, so the app
    only found its saved work when it happened to be started from the right folder, and a
    packaged build pointed at ``sys._MEIPASS`` wrote into a temporary directory.
    ``src/utils/app_paths.py`` gives that answer once for the app now, so this is the same
    folder under the name this module's callers already use.
    """
    return data_dir()



class ActionRegistry:
    """Registry for automation actions."""
    
    _actions: Dict[str, Callable] = {}
    _descriptions: Dict[str, str] = {}
    _param_specs: Dict[str, Dict] = {}
    # What each parameter holds when nothing is sent for it, read off the action's own
    # signature when it is registered. The pane that builds a field per parameter shows
    # these, so the default a person reads is the default the call would use.
    _param_defaults: Dict[str, Dict[str, Any]] = {}
    # An action that says how a batch feeds it one file - (the parameter the file goes
    # into, the parameter the output folder goes into, or None when it leaves no file of
    # its own) - can be repeated over a list. The rest cannot be, so they are not offered.
    _batch_specs: Dict[str, Any] = {}
    # The extension a batch gives the file this action writes, when the action's own output
    # is not the format it was read in (a thumbnail of a .obj is a .png, not a .obj).
    _batch_extensions: Dict[str, str] = {}
    
    @classmethod
    def register(cls, action_id: str, func: Callable, description: str = "", params: Dict = None,
                 batch: Any = None, batch_extension: str = ""):
        """Register a new action, and say whether a batch of files can use it."""
        cls._actions[action_id] = func
        cls._descriptions[action_id] = description
        cls._param_specs[action_id] = params or {}
        cls._param_defaults[action_id] = cls._signature_defaults(func, params or {})
        cls._batch_specs[action_id] = tuple(batch) if batch else None
        cls._batch_extensions[action_id] = str(batch_extension or '').strip().lstrip('.').lower()
        logger.debug("Registered action: %s", action_id)
        
    @classmethod
    def get_action(cls, action_id: str) -> Optional[Callable]:
        """Get action callable by ID."""
        return cls._actions.get(action_id)

    @staticmethod
    def _signature_defaults(func: Callable, spec: Dict) -> Dict[str, Any]:
        """What each registered parameter holds when nothing is sent for it.

        The action's own python signature is the only thing that knows, so the default a
        pane promises and the default the call uses cannot drift apart. Handing the
        numbers to the registration line is how those two disagree.
        """
        try:
            parameters = inspect.signature(func).parameters
        except (TypeError, ValueError):
            return {}
        return {name: item.default for name, item in parameters.items()
                if name in spec and item.default is not inspect.Parameter.empty}
        
    @classmethod
    def get_all_actions(cls) -> Dict[str, Dict]:
        """Get all registered actions with metadata."""
        return {
            aid: {
                'description': cls._descriptions.get(aid, ''),
                'parameters': cls._param_specs.get(aid, {})
            }
            for aid in cls._actions.keys()
        }
    
    @classmethod
    def validate(cls, action_id: str, params: Dict[str, Any]) -> List[str]:
        """Every way this parameter set fails this action, each one a sentence.

        The registry is the only place that knows what an action takes, so the task pane,
        the workflow builder and `execute` itself all read their complaints from here
        instead of each keeping a private copy of the rules.
        """
        if action_id not in cls._actions:
            return [f"nothing is registered as '{action_id}', so there is no step that can run it"]
        spec = cls._param_specs.get(action_id) or {}
        checks = {'str': str, 'int': int, 'float': (int, float), 'bool': bool}
        params = params or {}
        complaints = []
        for name, rule in spec.items():
            if rule.get('required') and name not in params:
                complaints.append(f"{action_id} needs a value for '{name}'")
            elif name in params:
                expected = checks.get(rule.get('type'))
                if expected and not isinstance(params[name], expected):
                    complaints.append(f"'{name}' must be {rule.get('type')}, "
                                      f"not {type(params[name]).__name__}")
        unknown = sorted(key for key in params if key not in spec)
        if unknown:
            complaints.append(f"{action_id} has no parameter named: " + ', '.join(unknown))
        return complaints

    @classmethod
    def execute(cls, action_id: str, **kwargs) -> Dict[str, Any]:
        """Run an action, or report the first reason it would not run."""
        complaints = cls.validate(action_id, kwargs)
        if complaints:
            return {'success': False, 'error': complaints[0]}
        try:
            result = cls._actions[action_id](**kwargs)
        except Exception as error:
            return {'success': False, 'error': str(error)}
        if isinstance(result, dict) and 'success' in result:
            return result
        return {'success': True, 'result': result}

    @classmethod
    def register_default_actions(cls):
        """Register the actions a task or a workflow step is allowed to name.

        Each one reports what it can prove rather than what it intended: a copy is
        confirmed by the bytes at the destination, a command is judged by its exit
        code, and the two processing actions name the files they actually wrote.
        """
        import shutil

        def copy_file(source: str, destination: str):
            if not os.path.isfile(source):
                raise FileNotFoundError(f"there is no file to copy at {source}")
            folder = os.path.dirname(destination)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)  # a pipeline stages into a folder it creates
            size = os.path.getsize(source)
            shutil.copy2(source, destination)
            if not os.path.isfile(destination) or os.path.getsize(destination) != size:
                raise RuntimeError(f"{destination} is not a full copy of {source}")
            return f"Copied {os.path.basename(source)} ({size} bytes) to {destination}"

        cls.register("file.copy", copy_file, "Copy a file", {
            "source": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        }, batch=('source', 'destination'))

        def move_file(source: str, destination: str):
            if not os.path.isfile(source):
                raise FileNotFoundError(f"there is no file to move at {source}")
            folder = os.path.dirname(destination)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)  # a pipeline stages into a folder it creates
            shutil.move(source, destination)
            if os.path.exists(source) or not os.path.isfile(destination):
                raise RuntimeError(f"{source} is still where it was and {destination} is not a file")
            return f"Moved {os.path.basename(source)} to {destination}"

        cls.register("file.move", move_file, "Move a file", {
            "source": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        }, batch=('source', 'destination'))

        def delete_file(path: str):
            if os.path.isdir(path):
                raise IsADirectoryError(f"{path} is a folder; this action deletes single files")
            if not os.path.exists(path):
                raise FileNotFoundError(f"{path} is already gone")
            size = os.path.getsize(path)
            os.remove(path)
            if os.path.exists(path):
                raise RuntimeError(f"{path} was not deleted")
            return f"Deleted {path} ({size} bytes)"

        cls.register("file.delete", delete_file, "Delete a file", {
            "path": {"type": "str", "required": True}
        }, batch=('path', None))

        def run_command(command: str):
            try:
                completed = subprocess.run(command, shell=True, capture_output=True,
                                           text=True, timeout=300)
            except subprocess.TimeoutExpired:
                return {'success': False,
                        'error': 'the command was still running after 300 seconds and was killed'}
            output = ((completed.stdout or '') + (completed.stderr or '')).strip()
            tail = output[-400:] if output else ''
            if completed.returncode != 0:
                return {'success': False, 'exit_code': completed.returncode,
                        'error': f"the command exited {completed.returncode}: "
                                 f"{tail or 'it printed nothing'}"}
            return {'success': True, 'exit_code': 0,
                    'result': tail or 'the command exited 0 and printed nothing'}

        cls.register("system.run_command", run_command,
                     "Run a shell command; its exit code is the verdict", {
            "command": {"type": "str", "required": True}
        }, batch=('command', None))

        # --- Processing Actions ---

        def bake_texture(high_poly: str, low_poly: str, output_dir: str, resolution: int = 2048):
            from ..processing.texture_baker import TextureBaker
            for path, label in ((high_poly, 'high-poly'), (low_poly, 'low-poly')):
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"the {label} model is not a file: {path}")
            baker = TextureBaker()
            complaints = []
            baker.error_occurred.connect(lambda message: complaints.append(message))
            maps = baker.bake(high_poly, low_poly, output_dir, int(resolution), True, True, True) or {}
            written = {kind: path for kind, path in maps.items()
                       if os.path.isfile(path) and os.path.getsize(path) > 0}
            if not written:
                return {'success': False,
                        'error': f"no baked map could be read back for "
                                 f"{os.path.basename(low_poly)}: "
                                 + (complaints[-1] if complaints else 'the baker gave no reason')}
            return {'success': True,
                    'result': f"Baked {len(written)} map(s) for {os.path.basename(low_poly)}: "
                              + ', '.join(sorted(written)),
                    'maps': written}

        cls.register("processing.bake_texture", bake_texture, "Bake textures", {
            "high_poly": {"type": "str", "required": True},
            "low_poly": {"type": "str", "required": True},
            "output_dir": {"type": "str", "required": True},
            "resolution": {"type": "int", "required": False}
        })

        def pack_texture_channels(output_path: str, red: str = "", green: str = "",
                                  blue: str = "", alpha: str = ""):
            """Write an ORM/mask PNG and return the backend's read-back verdict."""
            from ..processing.texture_packer import ChannelPacker
            verdict = ChannelPacker.pack(output_path, {
                'red': red or None, 'green': green or None,
                'blue': blue or None, 'alpha': alpha or None,
            })
            if not verdict.success:
                return {'success': False, 'error': verdict.message}
            return {'success': True, 'result': verdict.message,
                    'output_path': verdict.output_path, 'size': verdict.size}

        cls.register("processing.pack_texture_channels", pack_texture_channels,
                     "Pack texture masks into an RGBA PNG", {
                         "output_path": {"type": "str", "required": True},
                         "red": {"type": "str", "required": False},
                         "green": {"type": "str", "required": False},
                         "blue": {"type": "str", "required": False},
                         "alpha": {"type": "str", "required": False},
                     })

        def compress_geometry_meshopt(input_path: str, output_path: str):
            from ..processing.geometry_compression import GeometryCompressor
            verdict = GeometryCompressor.compress_meshopt(input_path, output_path)
            return ({'success': True, 'result': verdict.message, 'output_path': verdict.output_path}
                    if verdict.success else {'success': False, 'error': verdict.message})

        cls.register("processing.compress_geometry_meshopt", compress_geometry_meshopt,
                     "Compress glTF geometry with Meshopt", {
                         "input_path": {"type": "str", "required": True},
                         "output_path": {"type": "str", "required": True},
                     })

        def generate_lod(input_file: str, output_dir: str, levels: int = 3):
            from ..processing.lod_generator import LODGenerator, LODSettings
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            levels = max(1, int(levels))
            files = LODGenerator(LODSettings(levels=levels)).generate_lods(input_file, output_dir) or []
            written = [path for path in files
                       if os.path.isfile(path) and os.path.getsize(path) > 0]
            if not written:
                return {'success': False,
                        'error': f"no LOD file was written for {os.path.basename(input_file)}"}
            return {'success': True,
                    'result': f"Wrote {len(written)} LOD(s) into {output_dir}: "
                              + ', '.join(os.path.basename(path) for path in written),
                    'files': written}

        cls.register("processing.generate_lod", generate_lod, "Generate LODs", {
            "input_file": {"type": "str", "required": True},
            "output_dir": {"type": "str", "required": True},
            "levels": {"type": "int", "required": False}
        }, batch=('input_file', 'output_dir'))

        # --- The mesh operations a batch can run over a folder of models ---
        #
        # Each one calls the same backend the single-model panes call, and each one reads
        # its own numbers back from the file it wrote rather than from what it asked for.

        def landed(path: str):
            """The size of the file this action was meant to leave behind, or None."""
            try:
                size = os.path.getsize(path)
            except OSError:
                return None
            return size if size else None

        def convert_format(input_file: str, destination: str, output_format: str = '',
                           preserve_materials: bool = True):
            from ..processing.format_converter import FormatConverter
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            source_ext = os.path.splitext(input_file)[1].lower()
            target_ext = os.path.splitext(destination)[1].lower()
            if not target_ext:
                raise ValueError(f"{destination} names no extension, so there is no format "
                                 "to convert to")
            if target_ext == source_ext:
                return {'success': False,
                        'error': f"{os.path.basename(destination)} would be written as "
                                 f"{target_ext}, the format it already is - set output_format "
                                 f"(for example \"glb\") to name the format to convert to"}
            outcome = FormatConverter().convert_file(
                input_file, destination,
                {'preserve_materials': bool(preserve_materials)}) or {}
            if not outcome.get('success'):
                return {'success': False,
                        'error': outcome.get('message') or 'the converter gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported converted but is not a file "
                                 "with bytes in it"}
            skipped = outcome.get('options_skipped') or []
            line = (f"Converted {os.path.basename(input_file)} to {os.path.basename(destination)} "
                    f"({size} bytes) with {outcome.get('method') or 'the first library that worked'}")
            if skipped:
                line += f"; {', '.join(skipped)} not applied"
            if outcome.get('content'):
                line += f"; {outcome['content']}"
            return {'success': True, 'result': line, 'output_path': destination}

        cls.register("processing.convert_format", convert_format,
                     "Convert a model to the format the destination extension names", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "output_format": {"type": "str", "required": False},
            # The words the batch pane has carried since the baseline: a checkbox here is
            # the same control, and the row it draws says "Preserve Materials", not the
            # parameter name.
            "preserve_materials": {"type": "bool", "required": False,
                                   "label": "Preserve Materials"}
        }, batch=('input_file', 'destination'))

        def simplify_to_faces(input_file: str, destination: str, target_faces: int = 10000,
                              preserve_boundary: bool = False, preserve_normal: bool = False,
                              preserve_topology: bool = False, quality_threshold: float = 0.3):
            from ..processing.mesh_processor import MeshSimplifier
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            outcome = MeshSimplifier.simplify_quadric(
                input_file, destination, target_faces=int(target_faces),
                preserve_boundary=bool(preserve_boundary),
                preserve_normal=bool(preserve_normal),
                preserve_topology=bool(preserve_topology),
                quality_threshold=float(quality_threshold)) or {}
            if not outcome.get('success'):
                return {'success': False, 'error': outcome.get('error') or 'the simplifier gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported simplified but is not a file "
                                 "with bytes in it"}
            return {'success': True,
                    'result': f"{os.path.basename(input_file)}: {outcome.get('original_faces')} "
                              f"-> {outcome.get('output_faces')} faces "
                              f"({outcome.get('reduction', 0):.1f}% off), {size} bytes",
                    'output_path': destination,
                    'output_faces': outcome.get('output_faces')}

        cls.register("processing.simplify_to_faces", simplify_to_faces,
                     "Collapse faces down to a fixed number", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "target_faces": {"type": "int", "required": False},
            "preserve_boundary": {"type": "bool", "required": False},
            "preserve_normal": {"type": "bool", "required": False},
            "preserve_topology": {"type": "bool", "required": False},
            "quality_threshold": {"type": "float", "required": False}
        }, batch=('input_file', 'destination'))

        def simplify_by_ratio(input_file: str, destination: str, ratio: float = 0.5):
            from ..processing.mesh_processor import MeshSimplifier
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            # The backend keeps a fraction it is handed by clamping it into 0..1, and a
            # sentence that prints the number asked for after that would report a
            # reduction that never happened. So a number that is not a fraction is
            # answered here, before the file is written.
            if not 0 < float(ratio) <= 1:
                return {'success': False,
                        'error': f"ratio {ratio} is not a fraction of the faces a mesh has; "
                                 "give a number above 0 and up to 1"}
            outcome = MeshSimplifier.simplify_ratio(
                input_file, destination, ratio=float(ratio)) or {}
            if not outcome.get('success'):
                return {'success': False, 'error': outcome.get('error') or 'the simplifier gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported simplified but is not a file "
                                 "with bytes in it"}
            return {'success': True,
                    'result': f"{os.path.basename(input_file)}: kept {ratio} of "
                              f"{outcome.get('original_faces')} faces -> "
                              f"{outcome.get('output_faces')} ({size} bytes)",
                    'output_path': destination,
                    'output_faces': outcome.get('output_faces')}

        cls.register("processing.simplify_by_ratio", simplify_by_ratio,
                     "Collapse faces down to a fraction of what they were", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "ratio": {"type": "float", "required": False}
        }, batch=('input_file', 'destination'))

        def repair_mesh(input_file: str, destination: str):
            from ..processing.mesh_processor import MeshRepairer
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            outcome = MeshRepairer.auto_repair(input_file, destination) or {}
            if not outcome.get('success'):
                return {'success': False, 'error': outcome.get('error') or 'the repairer gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported repaired but is not a file "
                                 "with bytes in it"}
            done = outcome.get('operations') or []
            return {'success': True,
                    'result': f"Repaired {os.path.basename(input_file)} into "
                              f"{os.path.basename(destination)} ({size} bytes): "
                              + ('; '.join(done) if done else 'nothing had to be changed'),
                    'output_path': destination, 'operations': done}

        cls.register("processing.repair_mesh", repair_mesh,
                     "Run the whole repair pass: weld, drop bad faces, re-orient, close holes", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        }, batch=('input_file', 'destination'))

        def weld_vertices(input_file: str, destination: str, threshold: float = None):
            from ..processing.mesh_processor import MeshRepairer
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            outcome = MeshRepairer.remove_duplicate_vertices(
                input_file, destination,
                threshold=None if threshold is None else float(threshold)) or {}
            if not outcome.get('success'):
                return {'success': False, 'error': outcome.get('error') or 'the welder gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported welded but is not a file "
                                 "with bytes in it"}
            removed = outcome.get('removed')
            how = ('exactly equal vertices' if threshold is None else
                   f'within {threshold} of the bounding diagonal')
            return {'success': True,
                    'result': f"Welded {removed} vertices in {os.path.basename(input_file)} "
                              f"({how}); {os.path.basename(destination)} is {size} bytes",
                    'output_path': destination, 'removed': removed}

        cls.register("processing.weld_vertices", weld_vertices,
                     "Merge the vertices that sit on top of each other", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "threshold": {"type": "float", "required": False}
        }, batch=('input_file', 'destination'))

        def center_pivot(input_file: str, destination: str):
            from ..processing.mesh_processor import MeshTransformer
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            outcome = MeshTransformer.center(input_file, destination) or {}
            if not outcome.get('success'):
                return {'success': False, 'error': outcome.get('error') or 'the mover gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported centred but is not a file "
                                 "with bytes in it"}
            moved = outcome.get('original_center')
            where = ('(%s)' % ', '.join('%.3f' % value for value in moved)) if moved else 'unknown'
            return {'success': True,
                    'result': f"Moved {os.path.basename(input_file)} so its centre sits at the "
                              f"origin (it was {where}); {os.path.basename(destination)} is "
                              f"{size} bytes",
                    'output_path': destination}

        cls.register("processing.center_pivot", center_pivot,
                     "Put the mesh centre on the origin", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        }, batch=('input_file', 'destination'))

        def normalize_size(input_file: str, destination: str, target_size: float = 1.0):
            from ..processing.mesh_processor import MeshTransformer
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            if float(target_size) <= 0:
                return {'success': False,
                        'error': f'target_size {target_size} is not a size; give a number '
                                 'greater than zero'}
            outcome = MeshTransformer.normalize_scale(
                input_file, destination, target_size=float(target_size)) or {}
            if not outcome.get('success'):
                return {'success': False, 'error': outcome.get('error') or 'the scaler gave no reason'}
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported scaled but is not a file "
                                 "with bytes in it"}
            return {'success': True,
                    'result': f"Scaled {os.path.basename(input_file)} by "
                              f"{outcome.get('scale_factor'):.5f} so its longest side is "
                              f"{target_size} units; {os.path.basename(destination)} is "
                              f"{size} bytes",
                    'output_path': destination}

        cls.register("processing.normalize_size", normalize_size,
                     "Scale a model so its longest side is a given length", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "target_size": {"type": "float", "required": False}
        }, batch=('input_file', 'destination'))

        def generate_uvs(input_file: str, destination: str, method: str = 'trivial'):
            """Unwrap into real texture coordinates and prove the file kept them.

            PyMeshLab is called with literal filter names because the installed build is
            the only authority on them; the two below are the ones measured against this
            build. The Voronoi atlas filter is deliberately not used - it brought the
            interpreter down on a plain cube, which is not a result to put in a batch.
            """
            import trimesh
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            extension = os.path.splitext(destination)[1].lower()
            if extension not in ('.obj', '.ply'):
                return {'success': False,
                        'error': f"{os.path.basename(destination)} is {extension or 'extensionless'}, "
                                 "which cannot hold UVs - this build writes texture coordinates "
                                 "into .obj or .ply (PyMeshLab has no glb/gltf writer)"}
            try:
                import pymeshlab
            except ImportError:
                return {'success': False, 'error': 'PyMeshLab is not installed, so nothing can unwrap'}
            ms = pymeshlab.MeshSet()
            try:
                ms.load_new_mesh(input_file)
                if method == 'trivial':
                    ms.apply_filter('compute_texcoord_parametrization_triangle_trivial_per_wedge')
                elif method == 'flat_plane':
                    ms.apply_filter('compute_texcoord_parametrization_flat_plane_per_wedge')
                else:
                    return {'success': False,
                            'error': f"generate_uvs offers 'trivial' (one patch per face) and "
                                     f"'flat_plane' (one projection); '{method}' is neither"}
                ms.save_current_mesh(destination)
            except Exception as error:
                return {'success': False, 'error': f"the unwrap failed on "
                                                   f"{os.path.basename(input_file)}: {error}"}
            finally:
                del ms
            size = landed(destination)
            if size is None:
                return {'success': False,
                        'error': f"{destination} was reported unwrapped but is not a file "
                                 "with bytes in it"}
            try:
                unwrapped = trimesh.load(destination, process=False)
                points = getattr(unwrapped.visual, 'uv', None)
                count = len(points) if points is not None else 0
            except Exception as error:
                return {'success': False,
                        'error': f"{destination} cannot be read back to check its UVs: {error}"}
            if not count:
                return {'success': False,
                        'error': f"{destination} reads back with no texture coordinates, "
                                 "so the unwrap did not land"}
            return {'success': True,
                    'result': f"Unwrapped {os.path.basename(input_file)} ({method} UVs, "
                              f"{count} coordinates) into {os.path.basename(destination)} "
                              f"({size} bytes)",
                    'output_path': destination, 'uv_points': count}

        cls.register("processing.generate_uvs", generate_uvs,
                     "Generate UVs and read them back from the written file", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "method": {"type": "str", "required": False}
        }, batch=('input_file', 'destination'))

        def make_thumbnail(input_file: str, destination: str, size: int = 256):
            from ..utils.thumbnail_renderer import generate_3d_thumbnail
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            if os.path.splitext(destination)[1].lower() != '.png':
                return {'success': False,
                        'error': f"{os.path.basename(destination)} is not a .png, and the "
                                 "picture this action writes is always a PNG"}
            try:
                size = int(size)
            except (TypeError, ValueError):
                return {'success': False, 'error': f"size {size!r} is not a number of pixels"}
            if not 16 <= size <= 4096:
                return {'success': False,
                        'error': f"size {size} is not an image this app will draw; pick "
                                 "between 16 and 4096 pixels"}
            outcome = generate_3d_thumbnail(input_file, destination, size=size) or {}
            bytes_written = landed(destination)
            if not outcome.get('success') or bytes_written is None:
                return {'success': False,
                        'error': outcome.get('error') or
                                 f"{destination} is not a file with bytes in it"}
            if not outcome.get('rendered'):
                return {'success': False,
                        'error': f"the picture was drawn but {os.path.basename(input_file)} "
                                 "contributed no triangles to it: "
                                 f"{outcome.get('error') or 'the mesh could not be read'}"}
            faces = int(outcome.get('faces') or 0)
            return {'success': True,
                    'result': f"Thumbnail of {os.path.basename(input_file)} written to "
                              f"{os.path.basename(destination)} ({bytes_written} bytes, "
                              f"{size}x{size}, {faces} triangles drawn)",
                    'output_path': destination, 'faces_drawn': faces}

        cls.register("file.thumbnail", make_thumbnail,
                     "Draw a model into a PNG preview image", {
            "input_file": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True},
            "size": {"type": "int", "required": False}
        }, batch=('input_file', 'destination'), batch_extension='png')


    @classmethod
    def batch_actions(cls) -> Dict[str, str]:
        """Every action that can run once per file, with the description it carries."""
        return {action_id: cls._descriptions.get(action_id, '')
                for action_id in sorted(cls._actions) if cls._batch_specs.get(action_id)}

    @classmethod
    def batch_binding(cls, action_id: str):
        """How a batch feeds this action one file, or None when it cannot have one."""
        return cls._batch_specs.get(action_id)

    @classmethod
    def batch_extension(cls, action_id: str) -> str:
        """The extension a batch gives this action's output, or '' when it keeps the file's own."""
        return cls._batch_extensions.get(action_id, '')

    @classmethod
    def parameter_names(cls, action_id: str) -> list:
        """The parameters this action was registered with, by name."""
        return sorted(cls._param_specs.get(action_id) or {})

    @classmethod
    def parameter_defaults(cls, action_id: str) -> Dict[str, Any]:
        """The value each parameter holds when the call sends nothing for it."""
        return dict(cls._param_defaults.get(action_id) or {})

    @classmethod
    def param_form(cls, action_id: str) -> list:
        """One field per parameter a batch cannot fill for itself, as the action declares it.

        The file the loop is holding goes into the binding's first parameter and the output
        folder into its second, so a field for either would only let a person overrule the
        value the batch already knows. `command` is the exception: the batch only puts the
        path into the text, and the text has to be written by someone first.
        """
        spec = cls._param_specs.get(action_id) or {}
        binding = cls._batch_specs.get(action_id)
        defaults = cls.parameter_defaults(action_id)
        fields = []
        for name in sorted(spec):
            if binding and len(binding) == 2:
                item_param, folder_param = binding
                if name == folder_param or (name == item_param and item_param != 'command'):
                    continue
            fields.append({'name': name,
                           'type': str(spec[name].get('type') or 'str'),
                           'label': spec[name].get('label'),
                           'required': bool(spec[name].get('required')),
                           'default': defaults.get(name)})
        return fields

    @classmethod
    def bind_batch_params(cls, action_id: str, item: str, output_dir: str = '',
                          params: Optional[Dict] = None):
        """The exact kwargs this file will be run with, or the reason there are none.

        Nothing here runs. Preview and the real batch both come through this method, so
        what Preview shows is the call that will be made rather than a description of it.
        """
        binding = cls._batch_specs.get(action_id)
        if binding is None:
            return None, (f"nothing can run a batch of files as '{action_id}', because that "
                          "action never said how it takes one file at a time")
        if not item or not os.path.isfile(item):
            return None, f"{item or 'the source'} is not a file right now"
        if len(binding) != 2:
            return None, (f"{action_id} registered the batch binding {binding}, which is not a file parameter and an output parameter")
        item_param, folder_param = binding
        merged = dict(params or {})
        if item_param == 'command':
            command = str(merged.get('command') or '')
            if '{file}' not in command:
                return None, ("the command needs {file} in it, so that each file in the "
                              "batch becomes the thing the command runs on")
            merged['command'] = command.replace('{file}', f'"{item}"' if ' ' in item else item)
        else:
            merged[item_param] = item
            if folder_param:
                folder = (output_dir or '').strip()
                if not folder:
                    return None, (f"{action_id} leaves a file behind, so it needs an output "
                                  "folder chosen before it runs")
                if not os.path.isdir(folder):
                    return None, (f"the output folder {folder} is not a folder - make it, or "
                                  "choose somewhere that already exists")
                name = os.path.basename(item)
                # A conversion says the format it wants in output_format; an action whose
                # output is always a different kind of file (a thumbnail) says so when it
                # registered. Either way the destination is named before the run, so the
                # overwrite rule and Preview both speak about the file that will exist.
                extension = (str(merged.get('output_format') or '').strip().lstrip('.').lower()
                             or cls._batch_extensions.get(action_id, ''))
                if folder_param == 'destination' and extension:
                    name = '%s.%s' % (os.path.splitext(name)[0], extension)
                merged[folder_param] = (os.path.join(folder, name)
                                        if folder_param == 'destination' else folder)
                if folder_param == 'destination' and (
                        os.path.normcase(merged['destination']) == os.path.normcase(item)):
                    return None, (f"{os.path.basename(item)} already sits in {folder}; "
                                  "this would write the file onto itself")
        complaints = cls.validate(action_id, merged)
        if complaints:
            return None, complaints[0]
        return merged, None


class WorkflowStep:
    """One step: a registry action, the parameters for it, and what to do if it fails."""

    ON_ERROR = ('stop', 'continue', 'retry')

    def __init__(self, name: str, action: str, parameters: Dict = None,
                 on_error: str = "stop", max_retries: int = 3):
        self.step_id = str(uuid.uuid4())
        self.name = name
        self.action = action  # an id ActionRegistry resolves
        self.parameters = parameters or {}
        self.on_error = on_error if on_error in self.ON_ERROR else 'stop'
        try:
            self.max_retries = max(0, int(max_retries))
        except (TypeError, ValueError):
            self.max_retries = 3
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None

    def to_dict(self) -> Dict:
        """Store what a step *is*; a step's run-time status belongs to the run, not the file."""
        return {
            'step_id': self.step_id,
            'name': self.name,
            'action': self.action,
            'parameters': self.parameters,
            'on_error': self.on_error,
            'max_retries': self.max_retries
        }

    @staticmethod
    def from_dict(data: Dict) -> 'WorkflowStep':
        data = data or {}
        step = WorkflowStep(
            name=data.get('name') or data.get('action') or 'Step',
            action=data.get('action') or '',
            parameters=data.get('parameters') or {},
            on_error=data.get('on_error', 'stop'),
            max_retries=data.get('max_retries', 3)
        )
        step.step_id = data.get('step_id') or str(uuid.uuid4())
        return step


@dataclass
class AutomationTask:
    """Container for automation task."""
    task_id: str
    name: str
    task_type: str
    parameters: Dict[str, Any]
    schedule_time: Optional[str] = None
    enabled: bool = True
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'task_id': self.task_id,
            'name': self.name,
            'task_type': self.task_type,
            'parameters': self.parameters,
            'schedule_time': self.schedule_time,
            'enabled': self.enabled,
            'status': self.status.value,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'result': self.result,
            'error': self.error
        }


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'AutomationTask':
        """Rebuild a saved task; a record with no id or no name is not a task."""
        task = AutomationTask(
            task_id=data['task_id'],
            name=data['name'],
            task_type=data.get('task_type', ''),
            parameters=data.get('parameters') or {},
            schedule_time=data.get('schedule_time'),
            enabled=bool(data.get('enabled', True)),
            status=TaskStatus(data.get('status', 'pending')),
            created_at=data.get('created_at', time.time()),
        )
        task.started_at = data.get('started_at')
        task.completed_at = data.get('completed_at')
        task.result = data.get('result')
        task.error = data.get('error')
        return task



class Workflow:
    """A named list of steps, plus the verdict of the last run."""

    def __init__(self, name: str, description: str = ""):
        self.workflow_id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self.created_at = datetime.now()
        self.modified_at = datetime.now()
        self.status = TaskStatus.PENDING
        self.current_step = 0
        self.started_at = None
        self.error = None

    def add_step(self, step: WorkflowStep):
        """Append a step and note the edit."""
        self.steps.append(step)
        self.modified_at = datetime.now()

    def remove_step(self, step_id: str):
        """Drop the step carrying this id."""
        self.steps = [s for s in self.steps if s.step_id != step_id]
        self.modified_at = datetime.now()

    def to_dict(self) -> Dict:
        return {
            'workflow_id': self.workflow_id,
            'name': self.name,
            'description': self.description,
            'steps': [step.to_dict() for step in self.steps],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'modified_at': self.modified_at.isoformat() if self.modified_at else None,
            'status': self.status.value,
            'current_step': self.current_step,
            'started_at': self.started_at,
            'error': self.error
        }

    @staticmethod
    def _stamp(value):
        """A timestamp read back from disk, or this moment when the record carries none."""
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return datetime.now()

    @staticmethod
    def from_dict(data: Dict) -> 'Workflow':
        data = data or {}
        workflow = Workflow(
            name=data.get('name') or 'Untitled workflow',
            description=data.get('description') or ''
        )
        workflow.workflow_id = data.get('workflow_id') or str(uuid.uuid4())
        for step_data in data.get('steps', []):
            workflow.add_step(WorkflowStep.from_dict(step_data))
        workflow.status = TaskStatus(data.get('status', 'pending'))
        workflow.current_step = data.get('current_step', 0)
        saved_start = data.get('started_at')
        if isinstance(saved_start, (int, float)):
            workflow.started_at = saved_start
        workflow.error = data.get('error')
        workflow.created_at = Workflow._stamp(data.get('created_at'))
        workflow.modified_at = Workflow._stamp(data.get('modified_at'))
        return workflow


SCHEDULE_UNITS = ('seconds', 'minutes', 'hours', 'days')

#: The schedule strings the Automation tab composes and this class understands:
#:   hourly / daily / weekly            plain intervals
#:   HH:MM                              every day at that time
#:   weekly@HH:MM / monthly@HH:MM       every 7 days / every month at that time
#:   every_N_unit                       N >= 1, unit in SCHEDULE_UNITS
#:   once:YYYY-MM-DDTHH:MM              one shot, then forgotten


def _time_part(spec: str) -> str:
    """The HH:MM inside a schedule string, or an empty string."""
    if '@' in spec:
        return spec.split('@', 1)[1]
    return spec if len(spec) == 5 and spec[2] == ':' else ''


def _monthly_occurrence(day: int, hour: int, minute: int, after: datetime) -> datetime:
    """The next run on `day` - or that month's last day - strictly after `after`."""
    candidate = after.replace(day=min(day, calendar.monthrange(after.year, after.month)[1]),
                              hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > after:
        return candidate
    year, month = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
    return datetime(year, month, min(day, calendar.monthrange(year, month)[1]), hour, minute)


class TaskScheduler(QObject):
    """Hand tasks to the `schedule` library and run what is due on a polling thread."""

    def __init__(self):
        super().__init__()
        self.scheduled_tasks: Dict[str, schedule.Job] = {}
        self.is_running = False
        self._scheduler_thread = None
        # A scheduler of this instance's own. The `schedule` module's default is a
        # module global, so a second engine would run this one's jobs as well and a
        # task would fire once per live engine.
        self._jobs = schedule.Scheduler()

    def schedule_task(self, task_id: str, schedule_time: str, callback: Callable) -> bool:
        """Register one task. False means this app cannot honour that schedule."""
        spec = (schedule_time or '').strip().lower()
        if not spec or callback is None:
            return False

        self.cancel_task(task_id)
        # `schedule` has no try/except of its own: a callback that raises skips
        # _schedule_next_run(), which leaves that job due forever - and being first in the
        # sorted list each pass, it starves every other job behind it. One broken task
        # would quietly stop every schedule in the app, so nothing reaches the library raw.
        callback = self._guarded(task_id, callback)

        try:
            if spec == 'hourly':
                job = self._jobs.every().hour.do(callback)
            elif spec == 'daily':
                job = self._jobs.every().day.do(callback)
            elif spec == 'weekly':
                job = self._jobs.every().week.do(callback)
            elif _time_part(spec):
                clock = _time_part(spec)
                if spec.startswith('weekly@'):
                    # This build of `schedule` only allows .at() on days, hours and
                    # minutes, so a weekly job at a time is seven days at that time.
                    job = self._jobs.every(7).days.at(clock).do(callback)
                elif spec.startswith('monthly@'):
                    hour, minute = (int(part) for part in clock.split(':')[:2])
                    now = datetime.now()
                    first = _monthly_occurrence(now.day, hour, minute, now)
                    return self._schedule_absolute(
                        task_id, first, callback,
                        lambda past: _monthly_occurrence(first.day, hour, minute, past))
                else:
                    job = self._jobs.every().day.at(clock).do(callback)
            elif spec.startswith('every_'):
                parts = spec.split('_')
                if len(parts) != 3 or parts[2] not in SCHEDULE_UNITS:
                    return False
                interval = int(parts[1])
                if interval < 1:
                    # schedule.every(0) never returns: it spins forever in
                    # _schedule_next_run and freezes whichever thread asked for it.
                    return False
                job = getattr(self._jobs.every(interval), parts[2]).do(callback)
            elif spec.startswith('once:'):
                when = datetime.fromisoformat(spec[5:])
                if when <= datetime.now():
                    return False
                return self._schedule_absolute(task_id, when, callback, None)
            else:
                return False
        except Exception as error:
            logger.warning("Could not schedule task %s as %r: %s", task_id, schedule_time, error)
            return False

        self.scheduled_tasks[task_id] = job
        return True

    def _schedule_absolute(self, task_id: str, when: datetime, callback: Callable,
                           rearm) -> bool:
        """Fire at an exact moment; `schedule` has no absolute API and no month unit.

        `rearm` turns the moment that just fired into the next one, or is None for a
        one-off job that takes itself out of the registry once it has run.
        """
        delay = (when - datetime.now()).total_seconds()
        if delay <= 0:
            if rearm is None:
                return False
            when = rearm(when)
            delay = (when - datetime.now()).total_seconds()

        def fire():
            finished = self.scheduled_tasks.pop(task_id, None)
            if finished is not None:
                self._jobs.cancel_job(finished)
            try:
                callback()
            finally:
                if rearm is not None:
                    self._schedule_absolute(task_id, rearm(when), callback, rearm)

        job = self._jobs.every(max(1, int(delay))).seconds.do(fire)
        job.next_run = when
        self.scheduled_tasks[task_id] = job
        return True

    @staticmethod
    def _guarded(task_id: str, callback: Callable) -> Callable:
        """Let the failure be reported here rather than inside the scheduler loop."""
        def run():
            try:
                callback()
            except Exception as error:
                logger.warning("Scheduled task %s raised: %s", task_id, error)
        return run

    def next_run(self, task_id: str):
        """When this task is next due, or None when nothing is waiting for it."""
        job = self.scheduled_tasks.get(task_id)
        return job.next_run if job is not None else None

    def cancel_task(self, task_id: str) -> bool:
        """Take a task out of the schedule registry."""
        job = self.scheduled_tasks.pop(task_id, None)
        if job is None:
            return False
        self._jobs.cancel_job(job)
        return True

    def start_scheduler(self):
        """Start the polling thread that runs whatever is due."""
        if self.is_running:
            return
        self.is_running = True
        self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self):
        """Stop the polling thread."""
        self.is_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=3)
            self._scheduler_thread = None

    def _run_scheduler(self):
        """Run the schedule library until asked to stop."""
        while self.is_running:
            try:
                self._jobs.run_pending()
            except Exception as error:
                logger.error("Scheduler error: %s", error)
            # Ten short sleeps rather than one long one: stop_scheduler() sets a
            # flag and joins, so a full second of sleep makes every teardown wait.
            for _ in range(10):
                if not self.is_running:
                    break
                time.sleep(0.1)



WATCH_EVENTS = ('created', 'modified', 'deleted', 'moved')


def _glob_list(patterns) -> List[str]:
    """Turn one filter field into a list of globs.

    The Automation tab's filters are typed by hand, so "*.obj, *.fbx", "obj fbx" and
    ".obj" are three ways of asking for the same files. A bare extension gets the star
    and the dot it needs; "*" and "*.*" mean "everything" and drop out of the list.
    """
    if patterns is None:
        return []
    if isinstance(patterns, str):
        pieces = patterns.replace(';', ',').replace('|', ',').split(',')
    else:
        pieces = [str(p) for p in patterns]

    globs = []
    for piece in pieces:
        for token in piece.split():
            token = token.strip().strip('"').strip("'")
            if not token or token in ('*', '*.*'):
                continue
            if '*' in token or '?' in token or '[' in token:
                globs.append(token)
            elif token.startswith('.'):
                globs.append('*' + token)
            else:
                globs.append('*.' + token)
    return globs


def _name_matches(filename: str, globs: List[str]) -> bool:
    """An empty glob list is "no filter", which matches every file."""
    if not globs:
        return True
    return any(fnmatch.fnmatch(filename, pattern) for pattern in globs)


def _is_excluded(filename: str, globs: List[str]) -> bool:
    """The exclude field asks the opposite question: no patterns means exclude nothing."""
    if not globs:
        return False
    return any(fnmatch.fnmatch(filename, pattern) for pattern in globs)


def _event_set(event_type) -> set:
    """Which of the four events one watched directory should report."""
    if event_type is None:
        return {'created'}
    if isinstance(event_type, str):
        if event_type in ('any', 'all'):
            return set(WATCH_EVENTS)
        return {event_type}
    events = set()
    for item in event_type:
        if item in ('any', 'all'):
            return set(WATCH_EVENTS)
        if item in WATCH_EVENTS:
            events.add(item)
    return events


class FileWatcher(QObject):
    """Watch directories for file changes."""

    file_created = pyqtSignal(str)  # file_path
    file_modified = pyqtSignal(str)  # file_path
    file_deleted = pyqtSignal(str)  # file_path
    file_moved = pyqtSignal(str, str)  # old_path, new_path

    def __init__(self, poll_seconds: float = 2.0):
        super().__init__()
        self.watched_directories: Dict[str, Dict[str, Any]] = {}
        self.is_watching = False
        self.poll_seconds = poll_seconds
        self._watcher_thread = None
        self._path_signals = {
            'created': self.file_created,
            'modified': self.file_modified,
            'deleted': self.file_deleted,
        }

    def watch_directory(self, directory: str, callback: Callable = None,
                        file_pattern: str = "*", event_type: Any = "created",
                        exclude_patterns: Any = "", min_size_kb: float = 0) -> str:
        """Watch one directory for file events and return its normalised path.

        callback is optional: the four signals are the API the Automation tab uses, and
        a tab that only wants the log should not have to invent a no-op function.
        """
        if not directory:
            raise ValueError("No directory given to watch")
        path = os.path.abspath(directory)
        if not os.path.isdir(path):
            raise ValueError(f"Cannot watch {path}: not a directory")

        info = self.watched_directories.get(path)
        if info is None:
            info = {'callbacks': [], 'last_modified': {}, 'pending_gone': {}}
            self.watched_directories[path] = info
        info['file_pattern'] = _glob_list(file_pattern)
        info['exclude_patterns'] = _glob_list(exclude_patterns)
        info['min_size_kb'] = float(min_size_kb or 0)
        info['events'] = _event_set(event_type)
        # Record the baseline here rather than on the thread's first pass: a file that
        # lands between this call and that pass is an event, not part of what was
        # already there. Re-registering a folder re-baselines it with its new filters.
        info['pending_gone'] = {}
        info['last_modified'] = self._snapshot(path, info)

        if callback is not None:
            info['callbacks'].append(callback)

        if not self.is_watching:
            self.start_watching()
        return path

    def is_watched(self, directory: str) -> bool:
        """Whether this exact directory is already in the watch list."""
        if not directory:
            return False
        return os.path.abspath(directory) in self.watched_directories

    def unwatch_directory(self, directory: str):
        """Stop watching directory."""
        if not directory:
            return
        self.watched_directories.pop(os.path.abspath(directory), None)

    def start_watching(self):
        """Start file watcher thread."""
        if self.is_watching:
            return

        self.is_watching = True
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def stop_watching(self):
        """Stop file watcher."""
        self.is_watching = False
        if self._watcher_thread:
            self._watcher_thread.join(timeout=2)
            self._watcher_thread = None

    def _snapshot(self, directory: str, info: Dict[str, Any]) -> Dict[str, tuple]:
        """Every file in this folder that passes its filters, as path -> (mtime, size)."""
        found: Dict[str, tuple] = {}
        smallest = float(info['min_size_kb']) * 1024.0
        for filename in os.listdir(directory):
            if not _name_matches(filename, info['file_pattern']):
                continue
            if _is_excluded(filename, info['exclude_patterns']):
                continue
            filepath = os.path.join(directory, filename)
            try:
                if not os.path.isfile(filepath):
                    continue
                stat = os.stat(filepath)
            except OSError:
                continue
            if stat.st_size < smallest:
                continue
            found[filepath] = (stat.st_mtime, stat.st_size)
        return found

    def _diff(self, info: Dict[str, Any], current: Dict[str, tuple]) -> List[tuple]:
        """What changed since the last pass, as (event, path, other_path) tuples.

        A file that left one path and appeared at another with the same mtime and size is
        reported as moved rather than deleted plus created; that is the only way a polling
        watcher can tell the two apart, and it is what the tab's "File Moved" checkbox
        asks for.

        A vanishing is held for one pass before it is called a deletion. os.listdir can
        catch a rename halfway through, with the old name already gone and the new one not
        yet visible, and without the hold that single rename is announced twice, as a
        deletion now and a creation one poll later. The price is that a real deletion
        reaches the log one poll late; the alternative is a log that lies about renames.

        The folder's baseline was recorded when it was registered, so what was already on
        disk when watching started is never announced as created.
        """
        known = info['last_modified']
        holds = info['pending_gone']

        appeared = [p for p in current if p not in known]
        vanished = [p for p in known if p not in current]

        events: List[tuple] = []
        # Last pass's open questions are answered first: a held path whose exact bytes have
        # surfaced elsewhere was a rename, never a deletion.
        for old in list(holds):
            match = next((p for p in appeared
                          if p != old and current[p] == holds[old]), None)
            if match is None:
                events.append(('deleted', old, None))
            else:
                appeared.remove(match)
                events.append(('moved', match, old))
            holds.pop(old)

        # A vanishing in this pass has one pass to produce a twin before it is called a loss.
        for old in list(vanished):
            match = next((p for p in appeared if current[p] == known[old]), None)
            if match is None:
                holds[old] = known[old]
                vanished.remove(old)
                continue
            appeared.remove(match)
            vanished.remove(old)
            events.append(('moved', match, old))

        for new in appeared:
            events.append(('created', new, None))
        for path in current:
            if path in known and current[path][0] > known[path][0]:
                events.append(('modified', path, None))

        info['last_modified'] = dict(current)
        return events

    def _watch_loop(self):
        """Poll every watched folder and report what changed."""
        while self.is_watching:
            for directory in list(self.watched_directories):
                if not os.path.isdir(directory):
                    continue
                try:
                    info = self.watched_directories.get(directory)
                    if info is None:
                        continue
                    current = self._snapshot(directory, info)
                    for event, path, other in self._diff(info, current):
                        self._report(path, event, other)
                except Exception as e:
                    logger.warning("Error watching directory %s: %s", directory, e)

            time.sleep(self.poll_seconds)

    def _report(self, file_path: str, event: str, other_path: str = None):
        """Tell both APIs about one change: the Qt signal and the python callback.

        Only the callback used to be reached, so the signals the Automation tab connects
        to had no emitter anywhere in the class. Events the folder was not asked to
        report are dropped here rather than at each caller.
        """
        info = self.watched_directories.get(os.path.dirname(file_path))
        if info is None or event not in info['events']:
            return

        if event == 'moved':
            self.file_moved.emit(other_path or '', file_path)
        else:
            self._path_signals[event].emit(file_path)

        for callback in list(info['callbacks']):
            try:
                callback(file_path, event)
            except Exception as error:
                logger.warning("Watch callback failed for %s: %s", file_path, error)

class WorkflowExecutor:
    """Run a workflow's steps in order, honouring each step's own error policy."""

    def __init__(self, task_executor=None):
        self.task_executor = task_executor

    def execute_workflow(self, workflow: Workflow, callback: Optional[Callable] = None,
                         progress: Optional[Callable] = None,
                         should_stop: Optional[Callable] = None) -> bool:
        """Every step in order, then one honest verdict.

        The loop used to call `step.get('name')` on `WorkflowStep` objects, so the first
        step raised AttributeError inside the worker thread and no workflow could ever
        finish - and because the engine emitted `workflow_completed` with three arguments
        into a two-argument signal, nothing reached the pane either way.
        """
        total = len(workflow.steps)
        if total == 0:
            return self._finish(workflow, callback, False,
                                {'workflow': workflow.name,
                                 'error': 'this workflow has no steps to run'})

        completed = 0
        tolerated = []
        for index, step in enumerate(workflow.steps):
            if should_stop and should_stop():
                step.status = TaskStatus.CANCELLED
                return self._finish(workflow, callback, False, {
                    'workflow': workflow.name, 'stopped': True,
                    'error': f"stopped before '{step.name}' (step {index + 1} of {total})",
                    'steps_completed': completed}, status=TaskStatus.CANCELLED)

            if progress:
                progress(index + 1, total, step.name)
            workflow.current_step = index + 1
            step.error = None
            step.result = None
            step.status = TaskStatus.RUNNING

            attempts = 0
            while True:
                outcome = ActionRegistry.execute(step.action, **step.parameters)
                step.result = outcome
                if outcome.get('success'):
                    step.status = TaskStatus.COMPLETED
                    completed += 1
                    break
                attempts += 1
                step.error = str(outcome.get('error') or 'the action gave no reason')
                step.status = TaskStatus.FAILED
                if step.on_error == 'retry' and attempts <= step.max_retries:
                    continue
                break

            if step.status == TaskStatus.COMPLETED:
                continue
            if step.on_error == 'continue':
                tolerated.append(f"{step.name}: {step.error}")
                continue
            return self._finish(workflow, callback, False, {
                'workflow': workflow.name, 'failed_step': step.name,
                'error': step.error, 'steps_completed': completed,
                'tolerated_failures': list(tolerated)})

        return self._finish(workflow, callback, True, {
            'workflow': workflow.name, 'steps_completed': completed,
            'total_steps': total, 'tolerated_failures': tolerated})

    @staticmethod
    def _finish(workflow: Workflow, callback, success: bool, result: Dict,
                status=None) -> bool:
        """Record the verdict on the workflow, then hand it to whoever asked."""
        result = dict(result, success=success)
        workflow.status = status or (TaskStatus.COMPLETED if success else TaskStatus.FAILED)
        workflow.error = None if success else result.get('error')
        if callback:
            callback(success, result)
        return success


# The most files one batch will work on at once. The pane's thread box is deliberately
# wider than this so a typed extreme is accepted there and capped here - the runner is the
# real bound, not the widget, and an out-of-range number is made safe rather than clamped away.
MAX_BATCH_WORKERS = 16


class BatchProcessor(QObject):
    """Run one action over a list of items, and stop or pause when it is asked to.

    An item only counts as done when the action says it did. The loop used to record a
    success whenever the callable came back without raising, and registry actions answer
    `{'success': False, 'error': ...}` instead of raising - so a batch in which every
    file failed reported every file as processed, and the pane printed the total.

    `workers` chooses how many files run at once. One worker is the plain sequential loop;
    more than one feeds that many threads from a single queue, each taking its own item -
    never two threads over one loaded model, because the mesh loaders are not reentrant.
    Either way a pause or a stop only bites between items, and the results come back in the
    order the files were given.
    """

    progress_updated = pyqtSignal(int, int, str)  # current, total, the item about to run
    batch_completed = pyqtSignal(dict)            # one summary of the whole run

    def __init__(self):
        super().__init__()
        self.current_batch = None
        self.is_processing = False
        self._stop = False
        self._pause = False

    @property
    def is_paused(self) -> bool:
        """Whether a run is holding at an item boundary."""
        return self._pause

    def request_stop(self):
        """Let the item in hand finish, then start no more."""
        self._stop = True
        self._pause = False

    def set_paused(self, paused: bool):
        """Hold the run at the next item boundary, or let it go again."""
        self._pause = bool(paused)

    def _hold(self):
        """Wait out a pause; asking to stop cuts a pause short."""
        while self._pause and not self._stop:
            time.sleep(0.05)

    def process_batch(self, items: List[Any], operation: Callable,
                     progress_callback: Optional[Callable] = None,
                     workers: int = 1) -> List[Dict[str, Any]]:
        """Every item through `operation`, then one summary that tells the truth about it.

        A pause or a stop only bites between items. An action that already started - a
        copy halfway through, a command still running - finishes first, because pulling
        the rug out from under those is how a file gets left half-written. `workers` over
        one runs that many files at once through `_run_parallel`; the sequential loop below
        is the one-worker path, and walks an empty list when the parallel runner has already
        filled the results.
        """
        items = list(items or [])
        total = len(items)
        effective = self._effective_workers(workers, total)
        results: List[Dict[str, Any]] = []
        self.is_processing = True
        self._stop = False
        self._pause = False
        self.current_batch = {'total': total, 'done': 0, 'item': None,
                                'started_at': time.time()}
        try:
            if effective > 1:
                self._run_parallel(items, operation, progress_callback, effective, results)
                sequential_items = []
            else:
                sequential_items = items
            for index, item in enumerate(sequential_items):
                self._hold()
                if self._stop:
                    break
                self.current_batch['item'] = str(item)
                self.progress_updated.emit(index + 1, total, str(item))
                try:
                    outcome = operation(item)
                except Exception as error:
                    results.append({'item': item, 'success': False, 'error': str(error)})
                else:
                    if isinstance(outcome, dict) and outcome.get('success') is False:
                        results.append({
                            'item': item, 'success': False,
                            'error': str(outcome.get('error') or
                                         'the action said no and gave no reason')})
                    else:
                        results.append({'item': item, 'success': True, 'result': outcome})
                self.current_batch['done'] = index + 1
                if progress_callback:
                    progress_callback(index + 1, total, item)
        finally:
            ran = len(results)
            summary = {'results': results, 'total': total, 'ran': ran, 'workers': effective,
                       'succeeded': sum(1 for one in results if one['success']),
                       'failed': sum(1 for one in results if not one['success']),
                       'not_run': total - ran, 'stopped': ran < total}
            # Posted before the flags fall, in this order on purpose: a reader that polls
            # ``is_processing`` and then looks at the pane is on the main thread, and the
            # slot that writes the pane's last line is queued behind this emit. Clear the
            # flags first and the run reports itself over while the notification ending it
            # has not even been posted, which is how a batch pane can say "Stopping -" over
            # a run that already stopped.
            self.batch_completed.emit(summary)
            self.current_batch = None
            self.is_processing = False
            self._stop = False
            self._pause = False
        return results

    @staticmethod
    def _effective_workers(workers: Any, total: int) -> int:
        """How many files to run at once: at least one, never past the cap or the list.

        A typed extreme is capped here rather than refused, and a zero or a nonsense value
        falls back to the sequential path. Capping by `total` keeps the count the summary
        names honest - three files cannot keep four workers busy.
        """
        try:
            asked = int(workers)
        except (TypeError, ValueError):
            asked = 1
        return max(1, min(asked, MAX_BATCH_WORKERS, total or 1))

    @staticmethod
    def _judge(item: Any, operation: Callable) -> Dict[str, Any]:
        """One item's verdict, judged exactly as the sequential loop judges it."""
        try:
            outcome = operation(item)
        except Exception as error:
            return {'item': item, 'success': False, 'error': str(error)}
        if isinstance(outcome, dict) and outcome.get('success') is False:
            return {'item': item, 'success': False,
                    'error': str(outcome.get('error') or
                                 'the action said no and gave no reason')}
        return {'item': item, 'success': True, 'result': outcome}

    def _run_parallel(self, items: List[Any], operation: Callable,
                      progress_callback: Optional[Callable], workers: int,
                      results: List[Dict[str, Any]]):
        """Feed `workers` threads from one queue and collect their verdicts in input order.

        Each worker takes its own item, so no two threads share one loaded model. Results
        land in index-keyed slots under a lock and are read out in the order the files were
        given, whichever worker finishes first. The threads are joined before this returns,
        so the caller's summary counts a settled run.
        """
        total = len(items)
        work: queue.Queue = queue.Queue()
        for index, item in enumerate(items):
            work.put((index, item))
        state = {'work': work, 'operation': operation, 'total': total,
                 'progress_callback': progress_callback, 'slots': [None] * total,
                 'lock': threading.Lock(), 'done': 0}
        threads = [threading.Thread(target=self._parallel_worker, args=(state,),
                                    daemon=True, name='_batch_worker')
                   for _ in range(workers)]
        for one in threads:
            one.start()
        for one in threads:
            one.join()
        results.extend(one for one in state['slots'] if one is not None)

    def _parallel_worker(self, state: Dict[str, Any]):
        """Take items off the queue until it is empty or the run is asked to stop.

        Pause and stop are read before the next item is taken, so a file already in hand
        finishes - the same boundary the sequential loop keeps.
        """
        work = state['work']
        operation = state['operation']
        total = state['total']
        while True:
            self._hold()
            if self._stop:
                return
            try:
                index, item = work.get_nowait()
            except queue.Empty:
                return
            record = self._judge(item, operation)
            with state['lock']:
                state['slots'][index] = record
                state['done'] += 1
                count = state['done']
                self.current_batch['done'] = count
                self.current_batch['item'] = str(item)
            self.progress_updated.emit(count, total, str(item))
            if state['progress_callback']:
                state['progress_callback'](count, total, item)
            work.task_done()


class ConditionEvaluator:
    """Evaluate conditions for trigger-based automation."""
    
    @staticmethod
    def evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Evaluate a condition."""
        condition_type = condition.get('type')
        
        if condition_type == 'file_exists':
            filepath = condition.get('filepath')
            return os.path.exists(filepath)
        
        elif condition_type == 'file_size':
            filepath = condition.get('filepath')
            operator = condition.get('operator', '>')
            threshold = condition.get('threshold', 0)
            
            if not os.path.exists(filepath):
                return False
            
            size = os.path.getsize(filepath)
            
            if operator == '>':
                return size > threshold
            elif operator == '<':
                return size < threshold
            elif operator == '==':
                return size == threshold
            
        elif condition_type == 'time_range':
            start_time = condition.get('start_time')
            end_time = condition.get('end_time')
            current_time = datetime.now().time()
            
            start = datetime.strptime(start_time, '%H:%M').time()
            end = datetime.strptime(end_time, '%H:%M').time()
            
            return start <= current_time <= end
        
        elif condition_type == 'variable':
            var_name = condition.get('variable')
            operator = condition.get('operator', '==')
            value = condition.get('value')
            
            if var_name not in context:
                return False
            
            var_value = context[var_name]
            
            if operator == '==':
                return var_value == value
            elif operator == '!=':
                return var_value != value
            elif operator == '>':
                return var_value > value
            elif operator == '<':
                return var_value < value
        
        return False


#: How long AutomationEngine.stop() waits for one worker thread. A file that takes
#: longer is left to finish on its own - the thread holds the engine alive, so it still
#: has something to report to; what must not happen is the engine going away under it.
WORKER_SHUTDOWN_WAIT = 5.0


class AutomationEngine(QObject):
    """Main automation engine coordinating all automation features."""
    
    task_started = pyqtSignal(str)  # task_id
    task_progress = pyqtSignal(str, int, str)  # task_id, progress, message
    task_completed = pyqtSignal(str, bool, dict)  # task_id, success, result
    workflow_started = pyqtSignal(str)  # workflow_id
    workflow_completed = pyqtSignal(str, dict)  # workflow_id, result
    workflow_failed = pyqtSignal(str, str)  # workflow_id, error
    workflow_progress = pyqtSignal(str, int, int, str)  # workflow_id, current_step, total_steps, step_name
    
    def __init__(self):
        super().__init__()
        self.scheduler = TaskScheduler()
        self.file_watcher = FileWatcher()
        self.workflow_executor = WorkflowExecutor(self)
        self.batch_processor = BatchProcessor()
        self.condition_evaluator = ConditionEvaluator()
        
        self.tasks: Dict[str, AutomationTask] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.triggers: Dict[str, Dict[str, Any]] = {}

        # Workflows the user asked to stop; the worker checks this before
        # each step, because a python thread cannot be killed from outside.
        self._stopped: set = set()
        # Every worker thread started since, kept so stop() can wait for it. A thread
        # that outlives the engine goes on posting its verdicts into whatever was
        # listening when it started - which by then may be nothing.
        self._worker_threads: List[threading.Thread] = []
        
        # Load saved workflows and tasks
        ActionRegistry.register_default_actions()
        self._load_workflows()
        self._load_tasks()
        self._stats_lock = threading.Lock()
        self._load_stats()
    
    def _stats_file(self) -> str:
        return os.path.join(app_data_dir(), 'automation_stats.json')

    def _load_stats(self):
        """Today's counters, or a fresh day when the file cannot be read."""
        try:
            with open(self._stats_file(), encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = None
        self._stats = data if isinstance(data, dict) else {}

    def _note_finished(self, success):
        """Count one run that ended; two threads closing together lose neither."""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._stats_lock:
            if self._stats.get('date') != today:
                self._stats = {'date': today, 'completed': 0, 'failed': 0}
            key = 'completed' if success else 'failed'
            self._stats[key] = int(self._stats.get(key, 0)) + 1
            try:
                with open(self._stats_file(), 'w', encoding='utf-8') as handle:
                    json.dump(self._stats, handle)
            except OSError:
                pass

    @property
    def completed_today(self):
        """Runs that ended with what they were asked for, on this date only."""
        today = datetime.now().strftime('%Y-%m-%d')
        if self._stats.get('date') != today:
            return 0
        return int(self._stats.get('completed', 0))

    def _tasks_file(self) -> str:
        return os.path.join(app_data_dir(), 'tasks.json')

    def _save_tasks(self):
        """Write every task, with its schedule and its last verdict."""
        try:
            data = [task.to_dict() for task in self.tasks.values()]
            with open(self._tasks_file(), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2)
        except Exception as error:
            logger.error("Could not save tasks: %s", error)

    def _load_tasks(self):
        """Read the tasks back and put the ones that are due on the scheduler.

        A one-off whose moment has already passed cannot fire, so it comes back
        CANCELLED rather than as something the user might still wait for.
        """
        path = self._tasks_file()
        if not os.path.exists(path):
            return

        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except Exception as error:
            logger.error("Could not read %s: %s", path, error)
            return

        if not isinstance(data, list):
            logger.error("Ignoring %s: expected a list of task records", path)
            return

        for record in data:
            try:
                task = AutomationTask.from_dict(record)
            except Exception as error:
                logger.error("Skipping an unreadable task record: %s", error)
                continue
            self.tasks[task.task_id] = task
            if task.enabled and task.schedule_time and not self.schedule_task(task.task_id, task.schedule_time):
                task.status = TaskStatus.CANCELLED

        if data:
            self._save_tasks()


    def create_task(self, name: str, task_type: str, parameters: Dict[str, Any],
                    enabled: bool = True) -> str:
        """Store a task. Putting it on the calendar is `schedule_task`'s job."""
        # A millisecond stamp, walked forward while it is taken. The old retry reused a
        # counter that only changes once the task is stored, so a second collision looped.
        stamp = int(time.time() * 1000)
        task_id = f"task_{stamp}"
        while task_id in self.tasks:
            stamp += 1
            task_id = f"task_{stamp}"

        self.tasks[task_id] = AutomationTask(
            task_id=task_id,
            name=name,
            task_type=task_type,
            parameters=parameters or {},
            enabled=enabled
        )
        self._save_tasks()
        return task_id

    def update_task(self, task_id: str, name: str = None, task_type: str = None,
                    parameters: Dict[str, Any] = None, enabled: bool = None) -> bool:
        """Change the parts of a task that were given and leave the rest alone."""
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if name is not None:
            task.name = name
        if task_type is not None:
            task.task_type = task_type
        if parameters is not None:
            task.parameters = parameters
        if enabled is not None:
            task.enabled = enabled
            if not enabled:
                self.scheduler.cancel_task(task_id)
                if task.status == TaskStatus.SCHEDULED:
                    task.status = TaskStatus.CANCELLED
        self._save_tasks()
        return True


    def execute_task(self, task_id: str) -> bool:
        """Run one task now. The action's own verdict decides the status."""
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if not task.enabled:
            self.task_completed.emit(task_id, False, {'error': f"'{task.name}' is disabled"})
            return False

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self.task_started.emit(task_id)

        try:
            result = self._execute_task_type(task)
        except Exception as error:
            success = False
            result = {'success': False, 'error': str(error)}
        else:
            success = bool(result.get('success', False)) if isinstance(result, dict) else result is not None
            if not success and isinstance(result, dict) and not result.get('error'):
                result = dict(result, error='the action reported no reason')

        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.completed_at = time.time()
        task.result = result
        task.error = None if success else str(result.get('error'))
        self._save_tasks()
        self._note_finished(bool(success))
        self.task_completed.emit(task_id, success, result)
        return success

    def run_task(self, task_id: str) -> bool:
        """Start one task on a worker thread the close can wait for.

        `execute_task` is the whole verb, and a run begun off the interface belongs in the
        same list every other run this engine starts is in: `stop` joins exactly
        `_worker_threads`, and `live_work` is what the close asks before it cuts anything
        off. Claimed here rather than on the thread for the reason `run_batch` gives - the
        button can be pressed twice before a thread has had a chance to run. A disabled task
        is refused by `execute_task` before it claims any status, so this claims none either:
        a run that never started must not be left looking, to `live_work` and to the row,
        like it is still going.
        """
        task = self.tasks.get(task_id)
        if task is None or task.status is TaskStatus.RUNNING:
            return False
        if task.enabled:
            task.status = TaskStatus.RUNNING
        self._spawn(self.execute_task, (task_id,))
        return True

    def schedule_task(self, task_id: str, schedule_time: str) -> bool:
        """Put an existing task on the scheduler and remember when it is due."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        def execute_callback():
            self.execute_task(task_id)

        if not self.scheduler.schedule_task(task_id, schedule_time, execute_callback):
            return False

        task.schedule_time = schedule_time
        task.status = TaskStatus.SCHEDULED
        self._save_tasks()
        return True

    def cancel_task(self, task_id: str) -> bool:
        """Take a task off the scheduler; it stays saved and can be scheduled again."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        self.scheduler.cancel_task(task_id)
        task.schedule_time = None
        task.status = TaskStatus.CANCELLED
        self._save_tasks()
        return True

    def delete_task(self, task_id: str) -> bool:
        """Remove a task from the scheduler, the table and the file."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        self.scheduler.cancel_task(task_id)
        del self.tasks[task_id]
        self._save_tasks()
        return True

    def set_task_enabled(self, task_id: str, enabled: bool) -> bool:
        """Enable or disable a task, keeping the scheduler in step with it."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        task.enabled = enabled
        if not enabled:
            self.scheduler.cancel_task(task_id)
            if task.status == TaskStatus.SCHEDULED:
                task.status = TaskStatus.CANCELLED
        elif task.schedule_time:
            self.schedule_task(task_id, task.schedule_time)
        self._save_tasks()
        return True

    def next_run(self, task_id: str):
        """When this task is next due, or None."""
        return self.scheduler.next_run(task_id)


    def create_workflow(self, name: str, description: str,
                       steps: List[Dict[str, Any]]) -> str:
        """Store a workflow built from step records, and return the id it owns."""
        workflow = Workflow(name=name, description=description or '')
        self._apply_steps(workflow, steps)
        self.workflows[workflow.workflow_id] = workflow
        self._save_workflows()
        return workflow.workflow_id

    def update_workflow(self, workflow_id: str, name: str = None, description: str = None,
                        steps: List[Dict[str, Any]] = None) -> bool:
        """Change the parts that were given; leave the rest of the workflow alone."""
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return False
        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if steps is not None:
            self._apply_steps(workflow, steps)
        workflow.modified_at = datetime.now()
        self._save_workflows()
        return True

    @staticmethod
    def _apply_steps(workflow: Workflow, steps: List[Dict[str, Any]]):
        workflow.steps = []
        for record in steps or []:
            workflow.add_step(WorkflowStep.from_dict(record)
                              if isinstance(record, dict) else record)

    def delete_workflow(self, workflow_id: str) -> bool:
        """Take a workflow out of the list and the file."""
        if workflow_id not in self.workflows:
            return False
        self.stop_workflow(workflow_id)
        del self.workflows[workflow_id]
        self._save_workflows()
        return True

    def duplicate_workflow(self, workflow_id: str) -> Optional[str]:
        """Copy a workflow, steps and all, under a fresh id."""
        source = self.workflows.get(workflow_id)
        if source is None:
            return None
        copy = Workflow.from_dict(source.to_dict())
        copy.workflow_id = str(uuid.uuid4())
        copy.name = f"{source.name} copy"
        copy.status = TaskStatus.PENDING
        copy.error = None
        copy.current_step = 0
        for step in copy.steps:
            step.step_id = str(uuid.uuid4())
        self.workflows[copy.workflow_id] = copy
        self._save_workflows()
        return copy.workflow_id

    @staticmethod
    def workflow_problems(name: str, steps: List[Dict[str, Any]]) -> List[str]:
        """Every reason this workflow could not run, said before any of it runs."""
        complaints = []
        if not (name or '').strip():
            complaints.append('a workflow needs a name')
        if not steps:
            complaints.append('a workflow needs at least one step to run')
        for index, record in enumerate(steps or [], start=1):
            action = (record.get('action') or '').strip()
            label = (record.get('name') or '').strip() or f"step {index}"
            if not action:
                complaints.append(f"'{label}' names no action")
                continue
            for one in ActionRegistry.validate(action, record.get('parameters') or {}):
                complaints.append(f"'{label}': {one}")
            if (record.get('on_error') or 'stop') not in WorkflowStep.ON_ERROR:
                complaints.append(f"'{label}' has on_error "
                                  f"'{record.get('on_error')}', which is not one of "
                                  f"{', '.join(WorkflowStep.ON_ERROR)}")
        return complaints

    def execute_workflow(self, workflow_id: str) -> bool:
        """Run a stored workflow on its own thread; the signals carry the verdict."""
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return False
        if not workflow.steps:
            self.workflow_failed.emit(workflow_id, 'this workflow has no steps to run')
            return False

        self._stopped.discard(workflow_id)
        workflow.status = TaskStatus.RUNNING
        workflow.error = None
        workflow.current_step = 0
        workflow.started_at = time.time()
        self.workflow_started.emit(workflow_id)

        def progress(current, total, step_name):
            self.workflow_progress.emit(workflow_id, current, total, step_name)

        def completion(success, result):
            self._save_workflows()
            self._note_finished(bool(success))
            if success:
                self.workflow_completed.emit(workflow_id, result)
            else:
                reason = result.get('error') or 'the workflow failed'
                if result.get('stopped'):
                    self.workflow_completed.emit(workflow_id, result)
                else:
                    self.workflow_failed.emit(workflow_id, reason)

        self._spawn(self.workflow_executor.execute_workflow,
                    (workflow, completion, progress,
                     lambda: workflow_id in self._stopped))
        return True

    def stop_workflow(self, workflow_id: str) -> bool:
        """Ask a running workflow to stop at the next step boundary."""
        if workflow_id not in self.workflows:
            return False
        self._stopped.add(workflow_id)
        return True
    
    def create_trigger(self, name: str, trigger_type: TriggerType, 
                      config: Dict[str, Any], action: Callable) -> str:
        """Create an automation trigger."""
        trigger_id = f"trigger_{int(time.time() * 1000)}"
        
        self.triggers[trigger_id] = {
            'name': name,
            'type': trigger_type,
            'config': config,
            'action': action,
            'enabled': True
        }
        
        # Setup trigger based on type
        if trigger_type == TriggerType.TIME_BASED:
            schedule_time = config.get('schedule')
            self.scheduler.schedule_task(trigger_id, schedule_time, action)
        
        elif trigger_type == TriggerType.FILE_WATCH:
            directory = config.get('directory')
            if not directory or not os.path.isdir(directory):
                raise ValueError(f"File watch trigger '{name}' needs an existing directory")
            file_pattern = config.get('file_pattern', '*')
            event_type = config.get('event_type', 'created')
            
            def file_callback(filepath, event):
                action(filepath, event)
            
            self.file_watcher.watch_directory(directory, file_callback, file_pattern, event_type)
        
        return trigger_id
    
    def disable_trigger(self, trigger_id: str) -> bool:
        """Disable a trigger."""
        if trigger_id not in self.triggers:
            return False
        
        self.triggers[trigger_id]['enabled'] = False
        return True
    
    def _spawn(self, target: Callable, args: tuple) -> threading.Thread:
        """Start a worker thread and keep hold of it until it is finished."""
        self._worker_threads = [one for one in self._worker_threads if one.is_alive()]
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._worker_threads.append(thread)
        thread.start()
        return thread

    def batch_process(self, items: List[Any], operation: Callable,
                     progress_callback: Optional[Callable] = None,
                     workers: int = 1) -> List[Dict[str, Any]]:
        """Process items in batch."""
        return self.batch_processor.process_batch(items, operation, progress_callback,
                                                  workers=workers)
    
    def run_batch(self, items: List[Any], operation: Callable, workers: int = 1) -> bool:
        """Repeat one action over many files on a worker thread; its signals tell the tale.

        The processor is claimed here rather than on the thread, because the click that
        starts a batch can land twice before a thread has had a chance to run.
        """
        if self.batch_processor.is_processing or not items:
            return False
        self.batch_processor.is_processing = True
        self._spawn(self._run_batch, (list(items), operation, workers))
        return True

    def _run_batch(self, items: List[Any], operation: Callable, workers: int = 1):
        """The worker's whole job: run the batch, and never leave it claimed."""
        try:
            ran = self.batch_processor.process_batch(items, operation, workers=workers)
            self._note_finished(bool(ran) and len(ran) == len(items)
                                and all(one['success'] for one in ran))
        finally:
            self.batch_processor.is_processing = False

    def stop_batch(self) -> bool:
        """Ask a running batch to stop between files; the file in hand finishes first."""
        if not self.batch_processor.is_processing:
            return False
        self.batch_processor.request_stop()
        return True

    def pause_batch(self, paused: bool = True) -> bool:
        """Hold a running batch at the next file, or let it go again."""
        if not self.batch_processor.is_processing:
            return False
        self.batch_processor.set_paused(paused)
        return True

    def start(self):
        """Start automation engine."""
        self.scheduler.start_scheduler()
        # File watcher starts automatically when directories are added
    
    def live_work(self):
        """What a close would cut off, named the way the run was named to the user."""
        running = []
        for workflow in self.workflows.values():
            if workflow.status is TaskStatus.RUNNING:
                running.append("workflow '%s'" % workflow.name)
        for task in self.tasks.values():
            if task.status is TaskStatus.RUNNING:
                running.append("task '%s'" % task.name)
        if self.batch_processor.is_processing:
            running.append('a batch of files')
        return running

    def stop(self):
        """Stop automation engine, and wait for the work it started."""
        self.scheduler.stop_scheduler()
        self.file_watcher.stop_watching()
        self.batch_processor.request_stop()
        for thread in list(self._worker_threads):
            thread.join(timeout=WORKER_SHUTDOWN_WAIT)
        self._worker_threads = [one for one in self._worker_threads if one.is_alive()]
    
    def _execute_task_type(self, task: AutomationTask) -> Dict[str, Any]:
        """Run the task's action id through the registry; task_type *is* the action id."""
        if not task.task_type:
            return {'success': False, 'error': 'this task has no action chosen'}
        return ActionRegistry.execute(task.task_type, **task.parameters)

    def _workflows_file(self) -> str:
        return os.path.join(app_data_dir(), 'workflows.json')

    def _save_workflows(self):
        """Write every workflow, keyed by id, with its steps."""
        try:
            data = {wid: workflow.to_dict() for wid, workflow in self.workflows.items()}
            with open(self._workflows_file(), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2)
        except Exception as error:
            logger.error("Could not save workflows: %s", error)

    def _load_workflows(self):
        """Rebuild saved workflows through `Workflow.from_dict`.

        This used to call `Workflow(workflow_id=..., steps=..., enabled=...,
        created_at=...)`, which is not that constructor: every record raised TypeError
        into the except, so a workflow that had been saved was silently never seen again.
        """
        path = self._workflows_file()
        if not os.path.exists(path):
            return

        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            for wid, record in (data or {}).items():
                self.workflows[wid] = Workflow.from_dict(record)
        except Exception as error:
            logger.error("Could not read workflows from %s: %s", path, error)
