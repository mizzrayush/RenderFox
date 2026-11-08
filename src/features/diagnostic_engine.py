"""
RenderFox Diagnostic Engine
Provides system diagnostics, health checks, and performance analysis.
"""

import os
import sys
import platform
import shutil
import subprocess
import psutil
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import traceback

from ..utils.frame_clock import shared_clock
from ..utils.app_paths import output_dir

try:
    import GPUtil
    GPU_UTIL_AVAILABLE = True
except ImportError:
    GPU_UTIL_AVAILABLE = False

try:
    from OpenGL import GL
    OPENGL_AVAILABLE = True
except ImportError:
    OPENGL_AVAILABLE = False


class SystemInfo:
    """Collects system information."""
    
    @staticmethod
    def get_os_info() -> Dict[str, Any]:
        """Get operating system information."""
        return {
            'os': platform.system(),
            'os_version': platform.version(),
            'os_release': platform.release(),
            'architecture': platform.machine(),
            'processor': platform.processor(),
            'python_version': sys.version,
            'python_implementation': platform.python_implementation()
        }
    
    @staticmethod
    def get_build_info() -> Dict[str, Any]:
        """Which interpreter and which Qt this process is really running on.

        The Diagnostics state dump used to print `Windows 11`, `Python 3.11.5` and
        `PyQt Version: 6.5.2` as three lines of text. Two of the three were wrong on
        this machine, which is how a build claim should be treated: read it, or do not
        print it.
        """
        try:
            from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
            qt = {'qt_runtime': QT_VERSION_STR, 'pyqt': PYQT_VERSION_STR}
        except ImportError as failed:
            qt = {'qt_runtime': None, 'pyqt': None,
                  'reason': f'PyQt6 could not be imported: {failed}'}
        os_info = SystemInfo.get_os_info()
        return {
            'os': f"{os_info['os']} {os_info['os_release']} "
                  f"(build {os_info['os_version']})",
            'architecture': os_info['architecture'],
            'processor': os_info['processor'] or 'not reported by the platform module',
            'python': os_info['python_version'].split()[0],
            'python_implementation': os_info['python_implementation'],
            'packaged': bool(getattr(sys, 'frozen', False)),
            **qt,
        }

    @staticmethod
    def get_process_info() -> Dict[str, Any]:
        """What this process costs, read at the moment it was asked.

        `uptime_seconds` is the process's own start time, so a dump says how long this
        session ran rather than how long a machine has been up. Figures a call refuses
        come back as None with the reason in `failures`, never as a plausible number.
        """
        import gc
        import time as _time
        process = psutil.Process(os.getpid())
        info = process.memory_info()
        started = process.create_time()
        now = _time.time()
        failures = []
        try:
            threads = process.num_threads()
        except psutil.Error as failed:
            threads = None
            failures.append(f'thread count: {failed}')
        peak_bytes = getattr(info, 'peak_wset', None)
        if peak_bytes is None:
            peak_bytes = getattr(info, 'peak_rss', None)
        if peak_bytes is None:
            failures.append(
                'peak resident size: this platform\'s process memory record has no '
                f'peak field (fields present: {", ".join(info._fields)})')
        try:
            open_files = len(process.open_files())
        except (psutil.AccessDenied, psutil.Error, OSError) as failed:
            open_files = None
            failures.append(f'open files: {failed}')
        return {
            'pid': process.pid,
            'started_at': datetime.fromtimestamp(started).isoformat(timespec='seconds'),
            'uptime_seconds': round(now - started, 1),
            'rss_mb': round(info.rss / (1024 * 1024), 1),
            'vms_mb': round(info.vms / (1024 * 1024), 1),
            'peak_rss_mb': round(peak_bytes / (1024 * 1024), 1) if peak_bytes else None,
            'threads': threads,
            'open_files': open_files,
            'gc_objects': len(gc.get_objects()),
            'failures': failures,
        }

    @staticmethod
    def live_object_counts(limit: int = 12) -> Dict[str, Any]:
        """Every live object in this process, counted by the class it actually is.

        The memory snapshot this replaces printed a price list - `3D Viewer: 245 MB`,
        `Textures: 89 MB` - for components that never reported a figure and in a unit
        (bytes per feature) nothing in this app is able to measure: allocations are not
        tagged by the code that asked for them. Counts are measurable, so this counts.

        Walking every object takes a fraction of a second and must not happen on the
        interface thread; the pane runs it on a worker. Array bytes are summed only from
        objects that state their own size (`numpy.ndarray.nbytes`, `bytes`, `bytearray`),
        which is a floor for the heap, not a total, and is labelled as such.

        The size lookup is a type test, never an attribute probe: a `getattr(obj,
        'nbytes')` over every live object asks a `ctypes` lazy library for a DLL called
        'nbytes' and raises FileNotFoundError out of the middle of a memory snapshot.
        """
        import gc
        from collections import Counter

        try:
            import numpy
            array_types = (numpy.ndarray, bytes, bytearray, memoryview)
        except ImportError:
            array_types = (bytes, bytearray, memoryview)

        counts = Counter()
        array_bytes = 0
        arrays = 0
        scanned = 0
        for obj in gc.get_objects():
            counts[type(obj).__name__] += 1
            scanned += 1
            if isinstance(obj, array_types):
                arrays += 1
                array_bytes += getattr(obj, 'nbytes', None) or len(obj)
        return {
            'scanned': scanned,
            'classes': counts.most_common(limit),
            'distinct_classes': len(counts),
            'array_like_count': arrays,
            'array_bytes': array_bytes,
            'array_mb': round(array_bytes / (1024 * 1024), 1),
            'sized_types': ', '.join(t.__name__ for t in array_types),
            'process': SystemInfo.get_process_info(),
            'machine_memory': SystemInfo.get_memory_info(),
        }

    @staticmethod
    def get_cpu_info() -> Dict[str, Any]:
        """Core counts, clock speed, and how busy the cores are over a measured window.

        `psutil.cpu_percent(interval=None)` means "since the last time you asked", so it
        answers 0.0 the first time and, after that, whatever gap the caller happened to
        leave - the Diagnostics pane printed that as a fact. Both figures here come from one
        fifth of a second of watching, and the overall figure is the mean of the per-core
        figures from the same window rather than a second question.
        """
        per_core = psutil.cpu_percent(interval=0.2, percpu=True)
        usage = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
        cpu_freq = psutil.cpu_freq()
        return {
            'physical_cores': psutil.cpu_count(logical=False),
            'logical_cores': psutil.cpu_count(logical=True),
            'current_frequency': f"{cpu_freq.current:.2f} MHz" if cpu_freq else "Unknown",
            'max_frequency': f"{cpu_freq.max:.2f} MHz" if cpu_freq else "Unknown",
            'usage_percent': usage,
            'per_core_usage': per_core
        }
    
    @staticmethod
    def get_memory_info() -> Dict[str, Any]:
        """Get RAM information."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            'total': f"{mem.total / (1024**3):.2f} GB",
            'available': f"{mem.available / (1024**3):.2f} GB",
            'used': f"{mem.used / (1024**3):.2f} GB",
            'percent': mem.percent,
            'swap_total': f"{swap.total / (1024**3):.2f} GB",
            'swap_used': f"{swap.used / (1024**3):.2f} GB",
            'swap_percent': swap.percent
        }
    
    @staticmethod
    def working_volume(storage: Dict[str, Any],
                       path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The volume in `storage` a write to `path` lands on, or None if no mount carries it.

        `psutil.disk_usage('/')` on Windows is the drive the process happened to start on,
        which is not where a render lands, and it never said which drive it was - so every
        caller that needs "is there room for this output" asks here instead, and the answer
        is a row that names its own mount point. The longest matching prefix wins, because
        `C:\\` is a volume and `C:\\MyApps` is not.
        """
        from ..utils.file_utils import get_temp_directory
        target = os.path.abspath(path or get_temp_directory()).upper()
        best = None
        for volume in storage['volumes']:
            mount = volume['mountpoint'].upper().rstrip('\\/')
            if target.startswith(mount) and (best is None
                                             or len(mount) > len(best['mountpoint'])):
                best = volume
        return best

    @staticmethod
    def get_storage_info() -> Dict[str, Any]:
        """Every mounted volume, with the sizes read from the OS and the disk behind each one.

        The sizes always come from psutil. The disk name and whether it is a solid state
        drive come from Windows, which is the only part that can fail to answer; when it
        does, the reason is listed instead of a guess. A caller that wants one volume asks
        `working_volume` rather than taking the first row.
        """
        volumes = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (PermissionError, OSError):
                continue
            volumes.append({
                'mountpoint': partition.mountpoint,
                'device': partition.device,
                'filesystem': partition.fstype,
                'total_bytes': usage.total,
                'used_bytes': usage.used,
                'free_bytes': usage.free,
                'used_percent': usage.percent,
                'media_type': None,
                'disk': None,
            })

        reasons: List[str] = []
        disks = SystemInfo._cim_rows(SystemInfo.CIM_DISK)
        if disks['reason']:
            reasons.append(f'which kind of disk: {disks["reason"]}')
        else:
            by_device = {str(entry.get('DeviceId')): entry for entry in disks['rows']}
            if not by_device:
                reasons.append('which kind of disk: Windows listed no physical disk')
            partitions = SystemInfo._cim_rows(SystemInfo.CIM_PARTITIONS)
            if partitions['reason']:
                reasons.append(f'which disk a drive letter sits on: {partitions["reason"]}')
            letter_to_device = {str(entry.get('DriveLetter')): str(entry.get('DiskNumber'))
                                for entry in partitions['rows'] if entry.get('DriveLetter')}
            for volume in volumes:
                letter = volume['mountpoint'][:1].upper()
                device = letter_to_device.get(letter)
                if device is None:
                    reasons.append(f"which kind of disk: no partition carries the drive letter "
                                   f"{letter!r} for {volume['mountpoint']}, so that volume is "
                                   f"left unlabelled")
                    continue
                entry = by_device.get(device)
                if entry is None:
                    reasons.append(f'which kind of disk: {letter}: sits on disk {device}, '
                                   f'which Windows did not list')
                    continue
                raw = entry.get('MediaType')
                name = SystemInfo.MEDIA_TYPES.get(raw)
                volume['media_type'] = name or f'disk kind {raw}'
                volume['disk'] = entry.get('FriendlyName')
                if name is None:
                    reasons.append(f'which kind of disk: Windows reported kind {raw} for '
                                   f"{entry.get('FriendlyName')}, which this app has no name "
                                   f"for")
        return {'volumes': volumes, 'reasons': reasons}

    
    @staticmethod
    def get_gpu_info() -> List[Dict[str, Any]]:
        """The display adapters in this machine, and which check identified each one.

        Two questions used to be confused here: which adapter is fitted (Windows knows that)
        and how hard it is working right now (only GPUtil asks, and only for adapters whose
        vendor tool is on PATH). A machine can answer one and not the other, so a figure
        nothing read stays blank with the reason beside it rather than becoming 0.
        """
        return SystemInfo.get_gpu_report()['adapters']

    @staticmethod
    def get_gpu_report() -> Dict[str, Any]:
        """The display adapters fitted here, their current load when a reader reports it,
        and a reason for everything that could not be read.

        `load_reason` says in its own field why no adapter carries current figures, so a
        caller does not have to search the notes for its own answer.
        """
        reasons: List[str] = []
        adapters: List[Dict[str, Any]] = []

        answer = SystemInfo._cim_rows(SystemInfo.CIM_GPU)
        if answer['reason']:
            reasons.append(f'adapter identity: {answer["reason"]}')
        for entry in answer['rows']:
            adapters.append({
                'name': entry.get('Name') or 'unnamed adapter',
                'vendor': entry.get('AdapterCompatibility') or 'unknown',
                'driver': entry.get('DriverVersion'),
                'adapter_ram_mb': (round(int(entry['AdapterRAM']) / (1024 * 1024))
                                   if entry.get('AdapterRAM') else None),
                'resolution': (f"{entry['CurrentHorizontalResolution']}x"
                               f"{entry['CurrentVerticalResolution']}"
                               if entry.get('CurrentHorizontalResolution') else None),
                'live': None,
                'source': 'PowerShell CIM Win32_VideoController',
            })
        if adapters and any(adapter['adapter_ram_mb'] for adapter in adapters):
            reasons.append('adapter memory: Windows keeps this figure in a 32-bit field that '
                           'vendors fill in inconsistently (an integrated adapter often '
                           'reports the slice carved out for it rather than what it can '
                           'address), so the panes print it as a recorded figure and never as '
                           "the adapter's capacity")

        if not adapters:
            live, live_reason = SystemInfo._gputil_adapters()
            if live_reason:
                reasons.append(f'adapter identity: {live_reason}')
            for gpu in live:
                adapters.append({'name': gpu.name, 'vendor': 'unknown',
                                 'driver': gpu.driver,
                                 'adapter_ram_mb': round(gpu.memoryTotal) if gpu.memoryTotal else None,
                                 'resolution': None, 'live': None, 'source': 'GPUtil'})

        if not adapters and OPENGL_AVAILABLE:
            try:
                gl = OpenGLInfo.get_opengl_info()
            except Exception as failed:
                gl = {'error': f'{type(failed).__name__}: {failed}'}
            if 'error' not in gl and gl.get('renderer'):
                adapters.append({'name': gl['renderer'], 'vendor': gl.get('vendor'),
                                 'driver': None, 'adapter_ram_mb': None,
                                 'resolution': None, 'live': None,
                                 'source': 'OpenGL context (name only - the driver and '
                                           'memory of the adapter that owns the context '
                                           'were not readable)'})
            else:
                reasons.append(f'adapter identity: no reader answered ({gl.get("error", "no renderer")})')
        elif not adapters:
            reasons.append('adapter identity: this build asks Windows through PowerShell '
                           'and PyOpenGL; neither is available here')

        load_reason = SystemInfo._attach_live(adapters)
        if load_reason:
            reasons.append(f'current load: {load_reason}')
        return {'adapters': adapters, 'reasons': reasons, 'load_reason': load_reason,
                'text': SystemInfo._gpu_text(adapters, reasons),
                'identity_source': adapters[0]['source'] if adapters else None}

    @staticmethod
    def _gpu_text(adapters: List[Dict[str, Any]], reasons: List[str]) -> str:
        """The one block of words every pane prints for the same adapters.

        Two panes used to write out the adapter list themselves, and only one skipped a
        field it could not read, so the Diagnostics report printed an empty memory line for
        the same machine the Performance pane stayed quiet about.
        """
        if not adapters:
            return 'No display adapter was enumerated.\n' + '\n'.join(reasons)
        lines = []
        for index, adapter in enumerate(adapters, start=1):
            lines.append(f"Adapter {index}: {adapter['name']}")
            lines.append(f"   Vendor: {adapter['vendor'] or 'not reported'}")
            if adapter['driver']:
                lines.append(f"   Driver: {adapter['driver']}")
            if adapter['adapter_ram_mb'] is not None:
                lines.append(f"   Memory Windows records: {adapter['adapter_ram_mb']} MB "
                             f"(Windows keeps this in a 32-bit field that vendors fill in "
                             f"inconsistently, so it is not the adapter's usable capacity)")
            if adapter['resolution']:
                lines.append(f"   Desktop resolution: {adapter['resolution']}")
            live = adapter['live']
            if live:
                lines.append(f"   Right now: {live['load_percent']}% busy, "
                             f"{live['memory_percent']}% of its memory in use, "
                             f"{live['temperature_c']} degC "
                             f"(read from {live['reader']})")
            else:
                lines.append('   Right now: no reader reports this adapter\'s load')
            if adapter.get('live_unmatched'):
                lines.append(f"   Matched: {adapter['live_unmatched']}")
            lines.append(f"   Identified by: {adapter['source']}")
            lines.append('')
        lines.extend(f'Note: {reason}' for reason in reasons)
        return '\n'.join(lines).rstrip()

    MEDIA_TYPES = {3: 'HDD', 4: 'SSD', 5: 'Storage class memory'}
    CIM_GPU = ('Get-CimInstance Win32_VideoController | Select-Object Name,'
               'AdapterCompatibility,DriverVersion,AdapterRAM,VideoProcessor,'
               'CurrentHorizontalResolution,CurrentVerticalResolution '
               '| ConvertTo-Json -Compress')
    CIM_DISK = ('Get-CimInstance -ClassName MSFT_PhysicalDisk '
                '-Namespace root/Microsoft/Windows/Storage | Select-Object '
                'DeviceId,FriendlyName,MediaType,Bus,Size | ConvertTo-Json -Compress')
    CIM_PARTITIONS = ('Get-Partition | Select-Object DiskNumber,DriveLetter,Type '
                      '| ConvertTo-Json -Compress')

    @staticmethod
    def _cim_rows(command: str, timeout: float = 20.0) -> Dict[str, Any]:
        """One PowerShell CIM query, answered as rows or as the reason there are none."""
        if platform.system() != 'Windows':
            return {'rows': [], 'reason': f'{platform.system()} has no CIM path; '
                                          f'this reader is Windows-only'}
        shell = shutil.which('powershell') or shutil.which('pwsh')
        if shell is None:
            return {'rows': [], 'reason': 'neither powershell nor pwsh is on PATH'}
        try:
            answer = subprocess.run([shell, '-NoProfile', '-Command', command],
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'rows': [], 'reason': f'PowerShell did not answer within {timeout:g} s'}
        except OSError as failed:
            return {'rows': [], 'reason': f'PowerShell could not start: {failed}'}
        if answer.returncode != 0:
            first = (answer.stderr or answer.stdout or '').strip().splitlines()
            return {'rows': [], 'reason': f'PowerShell returned {answer.returncode}: '
                                          f'{first[0] if first else "no message"}'}
        text = (answer.stdout or '').strip()
        if not text:
            return {'rows': [], 'reason': 'PowerShell answered no rows'}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as bad:
            return {'rows': [], 'reason': f'PowerShell answered text that is not JSON: {bad}'}
        return {'rows': parsed if isinstance(parsed, list) else [parsed], 'reason': ''}

    @staticmethod
    def _gputil_adapters() -> tuple:
        """The adapters GPUtil can talk to, or why it answered none."""
        if not GPU_UTIL_AVAILABLE:
            return [], 'GPUtil is not installed'
        try:
            return list(GPUtil.getGPUs()), ''
        except Exception as failed:
            return [], f'GPUtil raised {type(failed).__name__}: {failed}'

    @staticmethod
    def _attach_live(adapters: List[Dict[str, Any]]) -> Optional[str]:
        """Put the current load, memory and temperature figures onto the adapter they belong to.

        Returns the sentence explaining why nothing was attached, or None when every adapter
        got its own reading.
        """
        live, why = SystemInfo._gputil_adapters()
        if not live:
            return why or ('GPUtil is installed but answered no adapter - it reads NVIDIA '
                           'through nvidia-smi, AMD through rocm-smi and Intel through '
                           'intel_gpu_top, and none of those works on this machine')
        for index, adapter in enumerate(adapters):
            gpu = live[index] if index < len(live) else None
            if gpu is None:
                adapter['live_unmatched'] = (f'GPUtil answered {len(live)} adapter(s) and '
                                             f'Windows records {len(adapters)}')
                continue
            adapter['live'] = {'load_percent': round(gpu.load * 100, 1),
                               'memory_percent': round(gpu.memoryUtil * 100, 1),
                               'temperature_c': round(gpu.temperature, 1),
                               'memory_used_mb': round(gpu.memoryUsed),
                               'reader': 'GPUtil'}
        if len(live) != len(adapters):
            return (f'GPUtil answered {len(live)} adapter(s) and Windows records '
                    f'{len(adapters)}; figures were matched in order, which is only safe '
                    f'when both lists are one adapter')
        return None

    @staticmethod
    def live_gpu_sample(adapter_name: Optional[str] = None) -> Dict[str, Any]:
        """What one adapter is doing now, or the reason this machine does not say.

        GPUtil runs a helper program for each of these figures, so this is the only GPU
        question the per-second monitor is allowed to ask, and `get_gpu_report()` - which
        also queries Windows for the adapters and costs about two seconds - stays the
        identity reader behind the Detect button. A figure GPUtil leaves out is returned
        as None with its name in `reason`, never as a zero: this machine has one Intel
        adapter and GPUtil answers no adapter at all here, so a monitored zero would be a
        number about hardware that was never asked.

        `adapter_name` is the device box's choice, matched case-insensitively against the
        names GPUtil answers for. It is matched rather than indexed because that list is
        GPUtil's own order and the pane's list comes off Windows - two orders that only
        agree when there is one adapter. A name that matches nothing is refused; the
        figures are never quietly taken from a different adapter than the one asked for.
        """
        adapters, why = SystemInfo._gputil_adapters()
        if not adapters:
            return {'load_percent': None, 'memory_percent': None, 'temperature_c': None,
                    'memory_used_mb': None, 'reader': 'GPUtil',
                    'reason': why or 'GPUtil answered no adapter'}

        wanted = (adapter_name or '').strip().lower()
        chosen = adapters
        if wanted and wanted != 'auto select':
            chosen = [entry for entry in adapters if wanted in (entry.name or '').lower()]
            if not chosen:
                return {'load_percent': None, 'memory_percent': None,
                        'temperature_c': None, 'memory_used_mb': None,
                        'reader': 'GPUtil', 'asked_for': adapter_name,
                        'reason': (f'GPUtil answered no adapter called {adapter_name!r}; it '
                                   f'answers for '
                                   f'{", ".join(repr(entry.name) for entry in adapters)} - '
                                   f'the figures of another adapter are not handed over')}
        gpu = chosen[0]
        sample = {'reader': 'GPUtil', 'reason': '', 'adapter': gpu.name}
        missing = []
        for key, attr, scale in (('load_percent', 'load', 100.0),
                                 ('memory_percent', 'memoryUtil', 100.0)):
            value = getattr(gpu, attr, None)
            if value is None:
                sample[key] = None
                missing.append(attr)
            else:
                sample[key] = round(value * scale, 1)
        used = getattr(gpu, 'memoryUsed', None)
        sample['memory_used_mb'] = None if used is None else round(used)
        if used is None:
            missing.append('memoryUsed')
        temperature = getattr(gpu, 'temperature', None)
        if temperature is None or temperature < 0:
            sample['temperature_c'] = None
            missing.append('temperature')
        else:
            sample['temperature_c'] = round(temperature, 1)

        if missing:
            sample['reason'] = ('GPUtil answered this adapter but not '
                                + ', '.join(missing))
        if len(adapters) > 1:
            named = (f'GPUtil answered {len(adapters)} adapters and these figures are '
                     f'those of {gpu.name}')
            unneeded = (f'GPUtil answered {len(adapters)} adapters, none was chosen, '
                        f'and these figures are the first of them')
            extra = named if wanted else unneeded
            sample['reason'] = f'{sample["reason"]}; {extra}' if sample['reason'] else extra
        return sample


class DependencyChecker:
    """Checks for required and optional dependencies."""
    
    REQUIRED_PACKAGES = [
        'PyQt6',
        'trimesh',
        'numpy',
        'psutil'
    ]
    
    OPTIONAL_PACKAGES = [
        'pymeshlab',
        'pyassimp',
        'open3d',
        'GPUtil',
        'pillow',
        'matplotlib',
        'scipy',
        'scikit-learn',
        'torch',
        'transformers'
    ]

    MODULE_NAMES = {
        'pillow': 'PIL',
        'scikit-learn': 'sklearn',
    }

    @staticmethod
    def check_package(package_name: str) -> Dict[str, Any]:
        """Whether a library is on this machine and which version of it, without importing it.

        The name a library is installed under is frequently not the name its code answers
        to: `pillow` ships `PIL` and `scikit-learn` ships `sklearn`. The old check imported
        the name it was given, so this machine was told twice that a library it has is
        missing, and paid seven seconds - torch and open3d load inside the check - to be
        told the rest. Looking the name up in the package records answers both: nothing is
        executed, so a library that is present but fails only when it loads is reported as
        present, which is the narrower claim the check can actually support.
        """
        import importlib.metadata
        import importlib.util

        module_name = DependencyChecker.MODULE_NAMES.get(
            package_name, package_name.replace('-', '_'))
        try:
            present = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            present = False
        try:
            version = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            version = None

        return {
            'installed': present or version is not None,
            'version': version,
            'status': 'OK' if present or version is not None else 'Not Installed'
        }
    
    @classmethod
    def check_all_dependencies(cls) -> Dict[str, Dict[str, Any]]:
        """Check all required and optional dependencies."""
        results = {
            'required': {},
            'optional': {}
        }
        
        for package in cls.REQUIRED_PACKAGES:
            results['required'][package] = cls.check_package(package)
        
        for package in cls.OPTIONAL_PACKAGES:
            results['optional'][package] = cls.check_package(package)
        
        return results


class OpenGLInfo:
    """Get OpenGL information."""
    
    @staticmethod
    def get_opengl_info() -> Dict[str, Any]:
        """Get OpenGL capabilities."""
        if not OPENGL_AVAILABLE:
            return {'error': 'PyOpenGL not installed'}
        
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtOpenGLWidgets import QOpenGLWidget
            
            # Create temporary OpenGL context
            app = QApplication.instance()
            if app is None:
                return {'error': 'QApplication not initialized'}
            
            widget = QOpenGLWidget()
            widget.makeCurrent()
            
            info = {
                'vendor': GL.glGetString(GL.GL_VENDOR).decode(),
                'renderer': GL.glGetString(GL.GL_RENDERER).decode(),
                'version': GL.glGetString(GL.GL_VERSION).decode(),
                'shading_language_version': GL.glGetString(GL.GL_SHADING_LANGUAGE_VERSION).decode(),
                'extensions_count': GL.glGetIntegerv(GL.GL_NUM_EXTENSIONS),
                'max_texture_size': GL.glGetIntegerv(GL.GL_MAX_TEXTURE_SIZE),
                'max_viewport_dims': GL.glGetIntegerv(GL.GL_MAX_VIEWPORT_DIMS)
            }
            
            widget.doneCurrent()
            return info
            
        except Exception as e:
            return {'error': f'Failed to get OpenGL info: {str(e)}'}


class HealthChecker:
    """The verdicts the Diagnostics pane prints beside each reading of this machine."""

    @staticmethod
    def check_cpu_usage(cpu: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """How busy the cores are, judged from the reading the pane already shows.

        The pane had a CPU row and a CPU badge with no verdict behind either: both printed
        the memory check's word, so a machine with an idle processor and a ram-starved one
        looked identical. The figures come from `get_cpu_info` so the number in the sentence
        and the number in the report are the same sample.
        """
        cpu = cpu or SystemInfo.get_cpu_info()
        usage = cpu['usage_percent']
        status = 'critical' if usage > 95 else 'warning' if usage > 85 else 'healthy'
        return {
            'status': status,
            'usage_percent': usage,
            'logical_cores': cpu['logical_cores'],
            'message': f"CPU {usage}% busy across {cpu['logical_cores']} logical cores"
        }

    @staticmethod
    def check_memory_usage() -> Dict[str, Any]:
        """Check if memory usage is healthy."""
        mem = psutil.virtual_memory()
        
        status = 'healthy'
        if mem.percent > 90:
            status = 'critical'
        elif mem.percent > 75:
            status = 'warning'
        
        return {
            'status': status,
            'usage_percent': mem.percent,
            'available_gb': mem.available / (1024**3),
            'message': f"Memory usage at {mem.percent}%"
        }
    
    @staticmethod
    def check_disk_space(storage: Optional[Dict[str, Any]] = None,
                         path: Optional[str] = None) -> Dict[str, Any]:
        """Room left on the volume a write to `path` lands on, and which volume that was.

        This used to measure `psutil.disk_usage('/')`. On Windows that is the drive the
        process happened to start on, so the verdict could be about a volume the app never
        writes to, and the number arrived without a name: on the machine this was built on
        the start-up drive is 25.8% full and the drive the app stages renders on is 90.8%,
        which is the difference between "all right" and "run out of room". The check now
        reads the same rows the panes do, so the word and the figures beside it are one
        volume.
        """
        storage = storage or SystemInfo.get_storage_info()
        volume = SystemInfo.working_volume(storage, path)
        if volume is None:
            return {
                'status': 'warning',
                'mountpoint': None,
                'disk': None,
                'media_type': None,
                'free_gb': None,
                'used_percent': None,
                'message': 'no mounted volume carries '
                           + (path or 'the directory the app writes to')
                           + ', so free space was not measured',
            }

        status = 'healthy'
        if volume['used_percent'] > 95:
            status = 'critical'
        elif volume['used_percent'] > 85:
            status = 'warning'

        where = volume['mountpoint']
        if volume['disk']:
            where += f" ({volume['disk']})"
        return {
            'status': status,
            'mountpoint': volume['mountpoint'],
            'disk': volume['disk'],
            'media_type': volume['media_type'],
            'free_gb': volume['free_bytes'] / (1024**3),
            'used_percent': volume['used_percent'],
            'message': f"{volume['free_bytes'] / (1024**3):.1f} GB free on {where} "
                       f"({volume['used_percent']}% used)",
        }
    
    @staticmethod
    def check_gpu_availability(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Whether this machine has a display adapter, and whether anything reads what it is doing.

        The old version said "1 GPU(s) available" about a row of placeholder text, so the
        Diagnostics pane called a machine healthy without knowing which graphics chip was in
        it. Those two are separate questions and an adapter nothing can read the load of is
        still fitted here, so the message says which of the two was answered.
        """
        report = report or SystemInfo.get_gpu_report()
        adapters = report['adapters']
        count = len(adapters)
        plural = '' if count == 1 else 's'
        if not adapters:
            return {'status': 'warning',
                    'message': 'Nothing identified a display adapter in this machine. '
                               + '; '.join(report['reasons'])}

        named = ', '.join(str(adapter['name']) for adapter in adapters)
        what = 'it is' if count == 1 else 'they are'
        if report.get('load_reason'):
            return {'status': 'healthy',
                    'message': f"{count} display adapter{plural} identified here: {named}. "
                               f"Nothing reports what {what} doing right now, because "
                               f"{report['load_reason']}"}

        for adapter in adapters:
            live = adapter['live'] or {}
            temperature = live.get('temperature_c')
            if temperature is not None and temperature > 85:
                return {'status': 'warning',
                        'message': f"{adapter['name']} is running hot: {temperature:g} degC"}
        read = [str(adapter['name']) for adapter in adapters if adapter['live']]
        if not read:
            return {'status': 'healthy',
                    'message': f"{count} display adapter{plural} identified here: {named}. "
                               f"None of them has a source for its current figures"}
        if len(read) == count:
            return {'status': 'healthy',
                    'message': f"{count} display adapter{plural} identified here, each with "
                               f"its current figures: {named}"}
        return {'status': 'healthy',
                'message': f"{count} display adapter{plural} identified here: {named}. "
                           f"Current figures only for: {', '.join(read)}"}
    
    @staticmethod
    def check_dependencies() -> Dict[str, Any]:
        """Check if all required dependencies are installed."""
        deps = DependencyChecker.check_all_dependencies()
        
        missing_required = [pkg for pkg, info in deps['required'].items() 
                          if not info['installed']]
        
        if missing_required:
            return {
                'status': 'critical',
                'message': f"Missing required packages: {', '.join(missing_required)}"
            }
        
        missing_optional = [pkg for pkg, info in deps['optional'].items() 
                          if not info['installed']]
        
        if missing_optional:
            return {
                'status': 'warning',
                'message': f"Missing optional packages: {', '.join(missing_optional[:3])}..."
            }
        
        return {
            'status': 'healthy',
            'message': 'All dependencies installed'
        }
    
    @classmethod
    def run_all_checks(cls, storage: Optional[Dict[str, Any]] = None,
                       gpu_report: Optional[Dict[str, Any]] = None,
                       cpu: Optional[Dict[str, Any]] = None
                       ) -> Dict[str, Dict[str, Any]]:
        """Run every health check.

        The three checks that measure this machine's hardware can be handed a reading taken a
        moment ago, because asking costs a second or two each and the Diagnostics pane should
        show its figures and its verdicts from the same look at the machine. Called with
        nothing, each check measures for itself.
        """
        return {
            'cpu': cls.check_cpu_usage(cpu),
            'memory': cls.check_memory_usage(),
            'disk': cls.check_disk_space(storage),
            'gpu': cls.check_gpu_availability(gpu_report),
            'dependencies': cls.check_dependencies()
        }


class ErrorLogger:
    """Logs and retrieves application errors."""
    
    def __init__(self, log_dir: Optional[str] = None):
        if log_dir is None:
            log_dir = os.path.join(output_dir(), 'logs')
        
        self.log_dir = Path(os.path.normpath(log_dir))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / 'errors.log'
    
    def log_error(self, error_type: str, message: str, traceback_str: Optional[str] = None):
        """Log an error to the error log."""
        timestamp = datetime.now().isoformat()
        
        log_entry = {
            'timestamp': timestamp,
            'type': error_type,
            'message': message,
            'traceback': traceback_str
        }
        
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def get_recent_errors(self, limit: int = 50) -> List[Dict]:
        """Get recent errors from the log."""
        if not self.log_file.exists():
            return []
        
        errors = []
        with open(self.log_file, 'r') as f:
            for line in f:
                try:
                    errors.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        
        # Return most recent errors
        return errors[-limit:]
    
    def clear_logs(self):
        """Clear the error log."""
        if self.log_file.exists():
            self.log_file.unlink()


class DiagnosticEngine:
    """Main diagnostic engine coordinating all diagnostic features."""
    
    def __init__(self):
        self.error_logger = ErrorLogger()
    
    def get_full_system_report(self) -> Dict[str, Any]:
        """Everything the Diagnostics pane shows, measured in one pass.

        The adapter and volume readings are taken once here and handed to the health checks,
        so a row's figures and the verdict beside it come from the same look at the machine
        rather than two looks a second apart.
        """
        storage = SystemInfo.get_storage_info()
        gpu = SystemInfo.get_gpu_report()
        cpu = SystemInfo.get_cpu_info()
        return {
            'timestamp': datetime.now().isoformat(),
            'os': SystemInfo.get_os_info(),
            'cpu': cpu,
            'memory': SystemInfo.get_memory_info(),
            'storage': storage,
            'gpu': gpu['adapters'],
            'gpu_text': gpu['text'],
            'gpu_reasons': gpu['reasons'],
            'gpu_load_reason': gpu['load_reason'],
            'opengl': OpenGLInfo.get_opengl_info(),
            'dependencies': DependencyChecker.check_all_dependencies(),
            'health_checks': HealthChecker.run_all_checks(storage, gpu, cpu),
            'recent_errors': self.error_logger.get_recent_errors(limit=10)
        }
    
    def export_report(self, output_path: Optional[str] = None) -> str:
        """Export diagnostic report to JSON file."""
        report = self.get_full_system_report()
        
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(self.error_logger.log_dir, f'diagnostic_report_{timestamp}.json')
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        return output_path

    REPORT_KINDS = {
        'Crash Report': 'the records this app wrote to its error log, and the process as it '
                        'stood when the report was asked for',
        'Error Summary': 'every ERROR and WARNING record the Diagnostics pane has seen, grouped',
        'Performance Report': 'machine readings taken now, plus the frames this app\'s own views drew',
        'Memory Report': 'this process\'s resident size and a count of the objects alive in it',
        'System Report': 'the same full system reading every other pane shows',
    }

    LOG_WINDOWS = {
        'Last Hour': 3600.0,
        'Last 6 Hours': 6 * 3600.0,
        'Last 24 Hours': 24 * 3600.0,
        'Last Week': 7 * 24 * 3600.0,
        'Last Month': 30 * 24 * 3600.0,
    }

    @staticmethod
    def parse_row_time(value):
        """The instant a log row says it happened, or None when it does not say."""
        if not value:
            return None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @classmethod
    def rows_in_window(cls, rows: List[Dict[str, Any]],
                       window_name: str) -> Dict[str, Any]:
        """The records whose own timestamp falls inside the window the pane named.

        `Custom Range` is on the pane's list with no picker behind it, so it answers with
        a refusal instead of quietly standing for the whole log - which is what the
        version this replaced did, while printing a percentage over the lot.
        """
        if window_name not in DiagnosticEngine.LOG_WINDOWS:
            return {'rows': [], 'seconds': None, 'cutoff': None, 'unparsed': 0,
                    'reason': f"'{window_name}' needs a start and an end, and this pane has "
                              f"no control that asks for either. The windows it can cut are "
                              f"{', '.join(DiagnosticEngine.LOG_WINDOWS)}."}
        import time as _time
        seconds = DiagnosticEngine.LOG_WINDOWS[window_name]
        cutoff = _time.time() - seconds
        kept, unparsed = [], 0
        for row in rows:
            at = cls.parse_row_time(row.get('timestamp'))
            if at is None or at.timestamp() < cutoff:
                if at is None:
                    unparsed += 1
                continue
            kept.append(row)
        return {'rows': kept, 'seconds': seconds, 'cutoff': cutoff,
                'unparsed': unparsed, 'reason': None}

    @classmethod
    def summarise_log_rows(cls, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Count what a list of log records says, without adding a claim to it.

        `rows` are the dicts the Diagnostics pane keeps (`timestamp`, `level`,
        `component`, `message`). Everything returned is a count or a time read off those
        rows: the analysis this replaces printed 1,247 records, a 2.3% error rate and a
        156 ms response time that were not measurements of anything.
        """
        from collections import Counter

        levels = Counter(str(row.get('level') or '') for row in rows)
        components = Counter(str(row.get('component') or '') for row in rows)
        grouped = Counter(
            (str(row.get('level') or ''), str(row.get('message') or '')) for row in rows)
        times = [cls.parse_row_time(row.get('timestamp')) for row in rows]
        stamps = [at for at in times if at is not None]

        repeated = []
        for (level, message), count in grouped.most_common():
            if count < 2:
                continue
            seen = [cls.parse_row_time(row.get('timestamp')) for row in rows
                    if str(row.get('level') or '') == level
                    and str(row.get('message') or '') == message]
            valid = [at for at in seen if at is not None]
            owner = next((str(row.get('component') or '') for row in rows
                          if str(row.get('level') or '') == level
                          and str(row.get('message') or '') == message), '')
            repeated.append({
                'level': level,
                'message': message,
                'component': owner,
                'count': count,
                'first_at': min(valid).strftime('%Y-%m-%d %H:%M:%S') if valid else None,
                'last_at': max(valid).strftime('%Y-%m-%d %H:%M:%S') if valid else None,
            })

        total = len(rows)
        errors = levels.get('ERROR', 0)
        return {
            'total': total,
            'errors': errors,
            'warnings': levels.get('WARNING', 0),
            'by_level': levels.most_common(),
            'by_component': components.most_common(8),
            'error_rate_percent': round(100.0 * errors / total, 1) if total else None,
            'repeated': repeated[:20],
            'first_at': min(stamps).strftime('%Y-%m-%d %H:%M:%S') if stamps else None,
            'last_at': max(stamps).strftime('%Y-%m-%d %H:%M:%S') if stamps else None,
            'span_seconds': round(max(stamps).timestamp() - min(stamps).timestamp(), 1)
                            if stamps else None,
            'rows_without_a_readable_time': len(rows) - len(stamps),
        }

    def export_error_report(self, report_type: str,
                            log_rows: Optional[List[Dict[str, Any]]] = None,
                            output_path: Optional[str] = None) -> Dict[str, Any]:
        """Write one report file and answer with where it is, or why nothing was written.

        The Reports list used to gain a row for a file no code had created, and selecting
        that row painted a crash carrying a `mesh_processor.cpp` stack trace out of a C++
        build this app does not contain. A row now appears only after a real file exists,
        and the preview reads that file off the disk.
        """
        if report_type not in DiagnosticEngine.REPORT_KINDS:
            return {'report_type': report_type, 'path': None,
                    'reason': f"'{report_type}' is not a report this engine can fill. The "
                              f"kinds it knows are {', '.join(DiagnosticEngine.REPORT_KINDS)}."}

        rows = log_rows or []
        errors = self.error_logger.get_recent_errors(limit=1000)
        payload = {
            'report_type': report_type,
            'what_this_report_is': DiagnosticEngine.REPORT_KINDS[report_type],
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'build': SystemInfo.get_build_info(),
        }
        if report_type in ('Crash Report', 'Error Summary'):
            payload['error_log'] = {
                'path': str(self.error_logger.log_file),
                'exists': self.error_logger.log_file.exists(),
                'records': errors,
            }
            payload['records_the_pane_saw'] = self.summarise_log_rows(rows)
            if not rows:
                payload['records_the_pane_saw']['note'] = (
                    'this pane only sees records logged while it exists, and it has seen none')
        if report_type == 'Crash Report':
            payload['process'] = SystemInfo.get_process_info()
        elif report_type == 'Performance Report':
            payload['cpu'] = SystemInfo.get_cpu_info()
            payload['memory'] = SystemInfo.get_memory_info()
            payload['process'] = SystemInfo.get_process_info()
            payload['frames'] = shared_clock().stats()
            payload['gpu'] = SystemInfo.live_gpu_sample()
        elif report_type == 'Memory Report':
            payload['memory'] = SystemInfo.get_memory_info()
            payload['objects'] = SystemInfo.live_object_counts()
        elif report_type == 'System Report':
            payload['system'] = self.get_full_system_report()

        if output_path is None:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe = ''.join(c for c in report_type if c.isalnum() or c in ' -_')
            file_name = f"report_{safe.strip().lower().replace(' ', '_')}_{stamp}.json"
            output_path = os.path.join(self.error_logger.log_dir, file_name)

        with open(output_path, 'w') as handle:
            json.dump(payload, handle, indent=2, default=str)
        return {'report_type': report_type, 'path': output_path,
                'bytes': os.path.getsize(output_path),
                'sections': [key for key in payload if key != 'report_type']}
    
    def get_recommendations(self, health: Optional[Dict[str, Any]] = None) -> List[str]:
        """What the health checks say is wrong, one line each, in the words the table shows.

        The lines start `Warning:` or `Good:` because that is how the Diagnostics table
        decides which column to file a line under; the earlier ones began with a picture
        character, so every line - including "all systems healthy" - landed in the table as
        unclassified. Pass the checks already run for this report so the advice and the
        figures on screen are the same measurement.
        """
        health = health or HealthChecker.run_all_checks()
        recommendations = []

        for name in ('cpu', 'memory', 'disk', 'gpu', 'dependencies'):
            check = health.get(name)
            if check and check['status'] != 'healthy':
                recommendations.append(f"Warning: {check['message']}")

        if not recommendations:
            recommendations.append("Good: every check this app makes about this machine "
                                   "came back within its limits")
        return recommendations