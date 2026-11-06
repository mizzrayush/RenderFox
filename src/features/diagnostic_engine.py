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
            log_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'logs')
        
        self.log_dir = Path(log_dir)
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


class PerformanceBenchmark:
    """Simple performance benchmarking."""
    
    @staticmethod
    def benchmark_cpu() -> Dict[str, Any]:
        """Benchmark CPU performance."""
        import time
        import math
        
        start = time.time()
        
        # Simple calculation benchmark
        result = 0
        for i in range(1000000):
            result += math.sqrt(i)
        
        elapsed = time.time() - start
        
        score = 1000 / elapsed  # Higher is better
        
        return {
            'elapsed_time': f"{elapsed:.3f}s",
            'score': f"{score:.2f}",
            'rating': 'Excellent' if score > 100 else 'Good' if score > 50 else 'Average'
        }
    
    @staticmethod
    def benchmark_memory() -> Dict[str, Any]:
        """Benchmark memory performance."""
        import time
        
        start = time.time()
        
        # Memory allocation benchmark
        data = [list(range(1000)) for _ in range(1000)]
        
        elapsed = time.time() - start
        
        score = 1000 / elapsed
        
        return {
            'elapsed_time': f"{elapsed:.3f}s",
            'score': f"{score:.2f}",
            'rating': 'Excellent' if score > 200 else 'Good' if score > 100 else 'Average'
        }


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