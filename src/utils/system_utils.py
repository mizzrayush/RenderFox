"""
System utilities and helpers for RenderFox.
"""

import os
import sys
import platform
import psutil
import subprocess
import threading
import time
import logging
import tempfile
import shutil
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from pathlib import Path
import json
from datetime import datetime, timedelta


@dataclass
class SystemInfo:
    """System information data class."""
    os_name: str
    os_version: str
    cpu_count: int
    cpu_freq: float
    memory_total: int
    memory_available: int
    gpu_info: List[Dict]
    python_version: str
    architecture: str


@dataclass
class ProcessInfo:
    """Process information for monitoring."""
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    status: str
    create_time: float


class SystemMonitor:
    """Monitor system resources."""
    
    def __init__(self):
        self.monitoring = False
        self.monitor_thread = None
        self.callbacks = []
        self.history = []
        self.max_history = 100
    
    def add_callback(self, callback):
        """Add callback for resource updates."""
        self.callbacks.append(callback)
    
    def start_monitoring(self, interval: float = 1.0):
        """Start system monitoring."""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop system monitoring."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
    
    def _monitor_loop(self, interval: float):
        """Main monitoring loop."""
        while self.monitoring:
            try:
                stats = self.get_system_stats()
                
                # Add to history
                stats['timestamp'] = time.time()
                self.history.append(stats)
                if len(self.history) > self.max_history:
                    self.history.pop(0)
                
                # Notify callbacks
                for callback in self.callbacks:
                    try:
                        callback(stats)
                    except Exception as e:
                        logging.warning(f"Monitor callback error: {e}")
                
                time.sleep(interval)
            except Exception as e:
                logging.error(f"Monitor loop error: {e}")
                time.sleep(interval)
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get current system statistics."""
        try:
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=None)
            
            stats = {
                'cpu_percent': cpu_percent,
                'cpu_count': psutil.cpu_count(),
                'memory_percent': memory.percent,
                'memory_used': memory.used,
                'memory_available': memory.available,
                'memory_total': memory.total,
                'swap_percent': psutil.swap_memory().percent,
                'disk_usage': {},
                'network_io': {},
                'load_average': None
            }
            
            # Get disk usage for relevant paths
            paths_to_check = ['/', 'C:\\', os.getcwd()]
            for path in paths_to_check:
                try:
                    if os.path.exists(path):
                        disk = psutil.disk_usage(path)
                        stats['disk_usage'][path] = {
                            'total': disk.total,
                            'used': disk.used,
                            'free': disk.free,
                            'percent': (disk.used / disk.total) * 100
                        }
                        break
                except Exception:
                    continue
            
            # Network I/O
            try:
                net_io = psutil.net_io_counters()
                if net_io:
                    stats['network_io'] = {
                        'bytes_sent': net_io.bytes_sent,
                        'bytes_recv': net_io.bytes_recv,
                        'packets_sent': net_io.packets_sent,
                        'packets_recv': net_io.packets_recv
                    }
            except Exception:
                pass
            
            # Load average (Unix-like systems)
            try:
                if hasattr(os, 'getloadavg'):
                    stats['load_average'] = os.getloadavg()
            except Exception:
                pass
            
            # Temperature (if available)
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    stats['temperatures'] = {}
                    for name, entries in temps.items():
                        stats['temperatures'][name] = [
                            {'label': entry.label or 'Unknown', 'current': entry.current}
                            for entry in entries
                        ]
            except Exception:
                pass
            
            return stats
        except Exception as e:
            logging.error(f"Error getting system stats: {e}")
            return {}
    
    def get_top_processes(self, limit: int = 10) -> List[ProcessInfo]:
        """Get top processes by CPU usage."""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status', 'create_time']):
                try:
                    info = proc.info
                    if info['memory_info']:
                        memory_mb = info['memory_info'].rss / 1024 / 1024
                    else:
                        memory_mb = 0
                    
                    processes.append(ProcessInfo(
                        pid=info['pid'],
                        name=info['name'] or 'Unknown',
                        cpu_percent=info['cpu_percent'] or 0,
                        memory_percent=info['memory_percent'] or 0,
                        memory_mb=memory_mb,
                        status=info['status'] or 'unknown',
                        create_time=info['create_time'] or 0
                    ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Sort by CPU usage
            processes.sort(key=lambda x: x.cpu_percent, reverse=True)
            return processes[:limit]
        
        except Exception as e:
            logging.error(f"Error getting top processes: {e}")
            return []
    
    def get_history_stats(self, minutes: int = 10) -> List[Dict]:
        """Get historical stats for the last N minutes."""
        cutoff_time = time.time() - (minutes * 60)
        return [stat for stat in self.history if stat.get('timestamp', 0) >= cutoff_time]


def get_system_info() -> SystemInfo:
    """Get comprehensive system information."""
    try:
        # Basic system info
        os_name = platform.system()
        os_version = platform.release()
        cpu_count = psutil.cpu_count()
        
        # CPU frequency
        try:
            cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0.0
        except Exception:
            cpu_freq = 0.0
        
        # Memory info
        memory = psutil.virtual_memory()
        memory_total = memory.total
        memory_available = memory.available
        
        # GPU info
        gpu_info = get_gpu_info()
        
        # Python info
        python_version = sys.version
        architecture = platform.machine()
        
        return SystemInfo(
            os_name=os_name,
            os_version=os_version,
            cpu_count=cpu_count,
            cpu_freq=cpu_freq,
            memory_total=memory_total,
            memory_available=memory_available,
            gpu_info=gpu_info,
            python_version=python_version,
            architecture=architecture
        )
    except Exception as e:
        logging.error(f"Error getting system info: {e}")
        # Return basic info if detailed info fails
        return SystemInfo(
            os_name=platform.system(),
            os_version=platform.release(),
            cpu_count=1,
            cpu_freq=0.0,
            memory_total=0,
            memory_available=0,
            gpu_info=[],
            python_version=sys.version,
            architecture=platform.machine()
        )


def get_gpu_info() -> List[Dict]:
    """Get GPU information."""
    gpus = []
    
    # Try nvidia-smi first
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu', 
             '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for i, line in enumerate(lines):
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 4:
                    gpu_info = {
                        'id': i,
                        'name': parts[0],
                        'memory_total': int(parts[1]) * 1024 * 1024,  # MB to bytes
                        'memory_used': int(parts[2]) * 1024 * 1024,
                        'memory_free': int(parts[3]) * 1024 * 1024,
                        'vendor': 'NVIDIA',
                        'temperature': None,
                        'utilization': None
                    }
                    
                    # Add temperature and utilization if available
                    if len(parts) > 4 and parts[4] != '[Not Supported]':
                        try:
                            gpu_info['temperature'] = float(parts[4])
                        except ValueError:
                            pass
                    
                    if len(parts) > 5 and parts[5] != '[Not Supported]':
                        try:
                            gpu_info['utilization'] = float(parts[5])
                        except ValueError:
                            pass
                    
                    gpus.append(gpu_info)
    except Exception:
        pass
    
    # Try AMD ROCm
    if not gpus:
        try:
            result = subprocess.run(['rocm-smi', '--showproductname', '--showmeminfo', '--json'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for gpu_id, gpu_data in data.items():
                    if gpu_id.startswith('card'):
                        gpus.append({
                            'id': len(gpus),
                            'name': gpu_data.get('Product Name', 'AMD GPU'),
                            'memory_total': gpu_data.get('VRAM Total', 0),
                            'memory_used': gpu_data.get('VRAM Used', 0),
                            'memory_free': gpu_data.get('VRAM Total', 0) - gpu_data.get('VRAM Used', 0),
                            'vendor': 'AMD'
                        })
        except Exception:
            pass
    
    # If no dedicated GPUs found, try Windows WMI for basic info
    if not gpus and platform.system() == 'Windows':
        try:
            import wmi
            c = wmi.WMI()
            for i, gpu in enumerate(c.Win32_VideoController()):
                if gpu.Name and 'Microsoft' not in gpu.Name:
                    memory_size = 0
                    try:
                        if gpu.AdapterRAM:
                            memory_size = int(gpu.AdapterRAM)
                    except:
                        pass
                    
                    gpus.append({
                        'id': i,
                        'name': gpu.Name,
                        'memory_total': memory_size,
                        'memory_used': 0,
                        'memory_free': memory_size,
                        'vendor': 'Unknown'
                    })
        except ImportError:
            # WMI not available
            pass
        except Exception:
            pass
    
    return gpus


def get_available_memory() -> int:
    """Get available system memory in bytes."""
    try:
        return psutil.virtual_memory().available
    except Exception:
        return 0


def get_cpu_count() -> int:
    """Get number of CPU cores."""
    try:
        return psutil.cpu_count()
    except Exception:
        return 1


def check_disk_space(path: str, required_bytes: int) -> Tuple[bool, int]:
    """Check if sufficient disk space is available."""
    try:
        if os.path.exists(path):
            disk_usage = psutil.disk_usage(path)
            available = disk_usage.free
            return available >= required_bytes, available
        return False, 0
    except Exception:
        return False, 0


def estimate_memory_usage(file_size: int, operation_type: str = 'basic') -> int:
    """Estimate memory usage for operations."""
    multipliers = {
        'basic': 1.5,
        'image_processing': 3.0,
        'video_processing': 5.0,
        '3d_processing': 4.0,
        'rendering': 6.0,
        'mesh_decimation': 3.5,
        'texture_processing': 4.0,
        'format_conversion': 2.0
    }
    
    multiplier = multipliers.get(operation_type, 2.0)
    return int(file_size * multiplier)


def can_handle_operation(file_size: int, operation_type: str = 'basic') -> bool:
    """Check if system can handle operation based on memory."""
    estimated_usage = estimate_memory_usage(file_size, operation_type)
    available_memory = get_available_memory()
    
    # Leave 20% memory buffer
    return estimated_usage < (available_memory * 0.8)


def cleanup_temp_files(older_than_hours: int = 24):
    """Clean up old temporary files."""
    try:
        temp_dir = tempfile.gettempdir()
        current_time = time.time()
        cutoff_time = current_time - (older_than_hours * 3600)
        
        cleaned_count = 0
        cleaned_size = 0
        
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.startswith('renderfox_') or file.startswith('rf_'):
                    file_path = os.path.join(root, file)
                    try:
                        if os.path.getmtime(file_path) < cutoff_time:
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            cleaned_count += 1
                            cleaned_size += file_size
                    except Exception:
                        continue
        
        return cleaned_count, cleaned_size
    
    except Exception as e:
        logging.error(f"Error cleaning temp files: {e}")
        return 0, 0


def get_temp_dir() -> str:
    """Get temporary directory for RenderFox."""
    temp_base = tempfile.gettempdir()
    renderfox_temp = os.path.join(temp_base, 'renderfox')
    
    try:
        os.makedirs(renderfox_temp, exist_ok=True)
        return renderfox_temp
    except Exception:
        return temp_base


def create_temp_file(suffix: str = '', prefix: str = 'rf_') -> str:
    """Create a temporary file and return its path."""
    temp_dir = get_temp_dir()
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=temp_dir)
    os.close(fd)  # Close the file descriptor, just return the path
    return path


class PerformanceTimer:
    """Performance timer context manager with additional features."""
    
    def __init__(self, name: str = "Operation", log_result: bool = False):
        self.name = name
        self.log_result = log_result
        self.start_time = None
        self.end_time = None
        self.start_memory = None
        self.end_memory = None
    
    def __enter__(self):
        self.start_time = time.time()
        try:
            process = psutil.Process()
            self.start_memory = process.memory_info().rss
        except Exception:
            self.start_memory = None
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        try:
            process = psutil.Process()
            self.end_memory = process.memory_info().rss
        except Exception:
            self.end_memory = None
        
        if self.log_result:
            elapsed = self.elapsed
            memory_delta = self.memory_delta
            
            log_msg = f"{self.name} completed in {format_duration(elapsed)}"
            if memory_delta is not None:
                if memory_delta > 0:
                    log_msg += f", memory increased by {format_bytes(memory_delta)}"
                else:
                    log_msg += f", memory decreased by {format_bytes(abs(memory_delta))}"
            
            logging.info(log_msg)
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0
    
    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return self.elapsed * 1000
    
    @property
    def memory_delta(self) -> Optional[int]:
        """Get memory usage change in bytes."""
        if self.start_memory is not None and self.end_memory is not None:
            return self.end_memory - self.start_memory
        return None


def run_command(command: List[str], cwd: Optional[str] = None, timeout: int = 300, 
               env: Optional[Dict[str, str]] = None) -> Tuple[bool, str, str]:
    """Run system command safely with enhanced options."""
    try:
        # Merge environment variables
        final_env = os.environ.copy()
        if env:
            final_env.update(env)
        
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=final_env
        )
        
        success = result.returncode == 0
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        
        return success, stdout, stderr
    
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout} seconds"
    except FileNotFoundError:
        return False, "", f"Command not found: {command[0] if command else 'unknown'}"
    except Exception as e:
        return False, "", str(e)


def find_executable(name: str) -> Optional[str]:
    """Find executable in application directories or system PATH."""
    try:
        # Check bundled / application directory first
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
            meipass_dir = getattr(sys, '_MEIPASS', app_dir)
        else:
            app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            meipass_dir = app_dir

        bundled_candidates = [
            os.path.join(app_dir, name),
            os.path.join(app_dir, "bin", name),
            os.path.join(app_dir, "ffmpeg", "bin", name),
            os.path.join(app_dir, "resources", "ffmpeg-2025-12-22-git-c50e5c7778-essentials_build", "bin", name),
            os.path.join(meipass_dir, name),
            os.path.join(meipass_dir, "bin", name),
            os.path.join(meipass_dir, "ffmpeg", "bin", name),
            os.path.join(meipass_dir, "resources", "ffmpeg-2025-12-22-git-c50e5c7778-essentials_build", "bin", name),
        ]
        if platform.system() == 'Windows' and not name.lower().endswith('.exe'):
            bundled_candidates.extend([f"{c}.exe" for c in bundled_candidates])

        for c in bundled_candidates:
            if os.path.isfile(c):
                return c

        # Use shutil.which for PATH lookup
        found = shutil.which(name)
        if found:
            return found
    except Exception:
        pass
    
    # Fallback for older Python versions or systems
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(['where', name], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        else:
            result = subprocess.run(['which', name], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
    except Exception:
        pass
    
    return None


def check_dependencies() -> Dict[str, bool]:
    """Check if required external dependencies are available."""
    dependencies = {
        'python': True,  # We're running Python
    }
    
    # Check executables
    executables = {
        'blender': ['blender', 'blender.exe'],
        'ffmpeg': ['ffmpeg', 'ffmpeg.exe'],
        'imagemagick': ['convert', 'convert.exe', 'magick', 'magick.exe'],
        'git': ['git', 'git.exe'],
        '7zip': ['7z', '7z.exe', '7za', '7za.exe']
    }
    
    for dep_name, possible_names in executables.items():
        dependencies[dep_name] = any(find_executable(name) for name in possible_names)
    
    # Check Python packages
    python_packages = {
        'pillow': ['PIL'],
        'opencv': ['cv2'],
        'numpy': ['numpy'],
        'trimesh': ['trimesh'],
        'psutil': ['psutil'],
        'pyqt6': ['PyQt6'],
        'sklearn': ['sklearn'],
        'scipy': ['scipy']
    }
    
    for dep_name, import_names in python_packages.items():
        try:
            for import_name in import_names:
                __import__(import_name)
            dependencies[dep_name] = True
        except ImportError:
            dependencies[dep_name] = False
    
    return dependencies


def get_optimal_thread_count(cpu_intensive: bool = True, max_threads: int = 16) -> int:
    """Get optimal thread count for operations."""
    cpu_count = get_cpu_count()
    
    if cpu_intensive:
        # For CPU-intensive tasks, use all cores but leave one for system
        optimal = max(1, cpu_count - 1)
    else:
        # For I/O-intensive tasks, can use more threads
        optimal = cpu_count * 2
    
    return min(optimal, max_threads)


def format_bytes(bytes_val: Union[int, float]) -> str:
    """Format bytes in human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format duration in human readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.1f}s"


def format_number(num: Union[int, float]) -> str:
    """Format large numbers with appropriate suffixes."""
    for unit in ['', 'K', 'M', 'B', 'T']:
        if abs(num) < 1000.0:
            return f"{num:.1f}{unit}"
        num /= 1000.0
    return f"{num:.1f}P"


def get_system_uptime() -> float:
    """Get system uptime in seconds."""
    try:
        return time.time() - psutil.boot_time()
    except Exception:
        return 0.0


def is_admin() -> bool:
    """Check if running with administrator privileges."""
    try:
        if platform.system() == 'Windows':
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception:
        return False


def get_process_by_name(name: str) -> List[ProcessInfo]:
    """Find processes by name."""
    processes = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status', 'create_time']):
            try:
                if name.lower() in proc.info['name'].lower():
                    memory_mb = proc.info['memory_info'].rss / 1024 / 1024 if proc.info['memory_info'] else 0
                    
                    processes.append(ProcessInfo(
                        pid=proc.info['pid'],
                        name=proc.info['name'] or 'Unknown',
                        cpu_percent=proc.info['cpu_percent'] or 0,
                        memory_percent=proc.info['memory_percent'] or 0,
                        memory_mb=memory_mb,
                        status=proc.info['status'] or 'unknown',
                        create_time=proc.info['create_time'] or 0
                    ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logging.error(f"Error finding processes by name '{name}': {e}")
    
    return processes


def kill_process_by_name(name: str, force: bool = False) -> int:
    """Kill processes by name. Returns number of processes killed."""
    killed_count = 0
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if name.lower() in proc.info['name'].lower():
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logging.error(f"Error killing processes by name '{name}': {e}")
    
    return killed_count


def create_system_report() -> Dict[str, Any]:
    """Create comprehensive system report."""
    info = get_system_info()
    dependencies = check_dependencies()
    monitor = SystemMonitor()
    stats = monitor.get_system_stats()
    
    return {
        'timestamp': datetime.now().isoformat(),
        'system_info': {
            'os': f"{info.os_name} {info.os_version}",
            'architecture': info.architecture,
            'python_version': info.python_version.split()[0],  # Just version number
            'cpu_count': info.cpu_count,
            'cpu_freq_mhz': info.cpu_freq,
            'memory_total_gb': round(info.memory_total / (1024**3), 2),
            'memory_available_gb': round(info.memory_available / (1024**3), 2),
            'gpus': info.gpu_info,
            'uptime_hours': round(get_system_uptime() / 3600, 1),
            'is_admin': is_admin()
        },
        'dependencies': dependencies,
        'current_stats': stats,
        'performance_recommendations': {
            'optimal_threads_cpu': get_optimal_thread_count(True),
            'optimal_threads_io': get_optimal_thread_count(False),
            'memory_available_for_operations': round(get_available_memory() * 0.8 / (1024**3), 2),
            'temp_dir': get_temp_dir()
        }
    }


class ResourceManager:
    """Manage system resources for operations."""
    
    def __init__(self, memory_limit_percent: float = 80.0):
        self.active_operations = []
        self.memory_limit_percent = memory_limit_percent
        self.memory_limit = get_available_memory() * (memory_limit_percent / 100.0)
        self._lock = threading.Lock()
    
    def can_start_operation(self, estimated_memory: int, operation_type: str = 'general') -> bool:
        """Check if operation can be started."""
        with self._lock:
            current_usage = sum(op.get('memory_usage', 0) for op in self.active_operations)
            
            # Additional checks based on operation type
            if operation_type == 'rendering':
                # Rendering operations need more headroom
                available = self.memory_limit * 0.7 - current_usage
            elif operation_type == 'batch':
                # Batch operations can use more memory
                available = self.memory_limit * 0.9 - current_usage
            else:
                available = self.memory_limit - current_usage
            
            return estimated_memory <= available
    
    def register_operation(self, operation_id: str, memory_usage: int, operation_type: str = 'general'):
        """Register active operation."""
        with self._lock:
            self.active_operations.append({
                'id': operation_id,
                'memory_usage': memory_usage,
                'operation_type': operation_type,
                'start_time': time.time()
            })
    
    def update_operation_memory(self, operation_id: str, new_memory_usage: int):
        """Update memory usage for an operation."""
        with self._lock:
            for op in self.active_operations:
                if op['id'] == operation_id:
                    op['memory_usage'] = new_memory_usage
                    break
    
    def unregister_operation(self, operation_id: str):
        """Unregister completed operation."""
        with self._lock:
            self.active_operations = [
                op for op in self.active_operations
                if op['id'] != operation_id
            ]
    
    def get_resource_status(self) -> Dict[str, Any]:
        """Get current resource usage status."""
        with self._lock:
            total_memory_used = sum(op.get('memory_usage', 0) for op in self.active_operations)
            
            return {
                'active_operations': len(self.active_operations),
                'memory_used': total_memory_used,
                'memory_used_mb': round(total_memory_used / (1024*1024), 1),
                'memory_available': self.memory_limit - total_memory_used,
                'memory_available_mb': round((self.memory_limit - total_memory_used) / (1024*1024), 1),
                'memory_limit': self.memory_limit,
                'memory_limit_mb': round(self.memory_limit / (1024*1024), 1),
                'memory_usage_percent': (total_memory_used / self.memory_limit) * 100 if self.memory_limit > 0 else 0,
                'operations': self.active_operations.copy()
            }
    
    def cleanup_stale_operations(self, max_age_hours: int = 24):
        """Clean up stale operations that might be stuck."""
        cutoff_time = time.time() - (max_age_hours * 3600)
        with self._lock:
            initial_count = len(self.active_operations)
            self.active_operations = [
                op for op in self.active_operations
                if op.get('start_time', time.time()) > cutoff_time
            ]
            cleaned = initial_count - len(self.active_operations)
            if cleaned > 0:
                logging.info(f"Cleaned up {cleaned} stale operations")


# Global resource manager instance
_resource_manager = None

def get_resource_manager() -> ResourceManager:
    """Get global resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager


# Utility functions for common operations
def ensure_directory(path: str) -> bool:
    """Ensure directory exists, create if not."""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"Failed to create directory {path}: {e}")
        return False


def safe_remove_file(path: str) -> bool:
    """Safely remove a file."""
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception as e:
        logging.error(f"Failed to remove file {path}: {e}")
        return False


def safe_copy_file(src: str, dst: str) -> bool:
    """Safely copy a file."""
    try:
        ensure_directory(os.path.dirname(dst))
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        logging.error(f"Failed to copy file {src} to {dst}: {e}")
        return False


def get_file_size(path: str) -> int:
    """Get file size safely."""
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def is_file_locked(file_path: str) -> bool:
    """Check if file is locked (being used by another process)."""
    if not os.path.exists(file_path):
        return False
    
    try:
        # Try to open the file for writing
        with open(file_path, 'r+b'):
            pass
        return False
    except (IOError, OSError):
        return True


"""
Utility functions for handling dependencies and system compatibility.
"""

import sys
import importlib
from typing import Dict, List, Tuple, Optional

class DependencyManager:
    """Manages optional dependencies and provides fallbacks."""
    
    def __init__(self):
        self.available_modules = {}
        self.missing_modules = {}
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check which optional dependencies are available."""
        optional_deps = {
            'psutil': 'Advanced process monitoring',
            'scikit-learn': 'ML-based model extraction',
            'PyOpenGL': 'Hardware-accelerated 3D rendering',
            'opencv-python': 'Advanced image processing',
            'open3d': 'Point cloud processing',
            'pymeshlab': 'Advanced mesh operations',
            'watchdog': 'File system monitoring',
            'playsound': 'Audio notifications',
            'requests': 'Online features and updates'
        }
        
        for module_name, description in optional_deps.items():
            try:
                module = importlib.import_module(module_name.replace('-', '_'))
                self.available_modules[module_name] = {
                    'module': module,
                    'description': description,
                    'version': getattr(module, '__version__', 'Unknown')
                }
            except ImportError:
                self.missing_modules[module_name] = description
    
    def is_available(self, module_name: str) -> bool:
        """Check if a module is available."""
        return module_name in self.available_modules
    
    def get_module(self, module_name: str):
        """Get a module if available, otherwise return None."""
        return self.available_modules.get(module_name, {}).get('module')
    
    def get_status_report(self) -> Dict[str, any]:
        """Get a comprehensive status report of dependencies."""
        return {
            'available': len(self.available_modules),
            'missing': len(self.missing_modules),
            'available_modules': self.available_modules,
            'missing_modules': self.missing_modules,
            'critical_missing': self._get_critical_missing()
        }
    
    def _get_critical_missing(self) -> List[str]:
        """Get list of critical missing dependencies."""
        critical = ['PyQt6', 'numpy', 'trimesh', 'Pillow']
        missing_critical = []
        
        for dep in critical:
            if not self.is_available(dep):
                missing_critical.append(dep)
        
        return missing_critical

# Global dependency manager instance
dependency_manager = DependencyManager()

def get_system_info() -> Dict[str, any]:
    """Get comprehensive system information."""
    info = {
        'python_version': sys.version,
        'platform': sys.platform,
        'dependencies': dependency_manager.get_status_report()
    }
    
    # Add psutil info if available
    psutil_module = dependency_manager.get_module('psutil')
    if psutil_module:
        try:
            info['system'] = {
                'cpu_count': psutil_module.cpu_count(),
                'memory_total_gb': round(psutil_module.virtual_memory().total / (1024**3), 2),
                'disk_free_gb': round(psutil_module.disk_usage('/').free / (1024**3), 2)
            }
        except Exception as e:
            info['system'] = {'error': str(e)}
    
    return info

def check_critical_dependencies() -> Tuple[bool, List[str]]:
    """Check if critical dependencies are available."""
    critical_missing = dependency_manager._get_critical_missing()
    return len(critical_missing) == 0, critical_missing

def safe_import(module_name: str, fallback_message: str = None):
    """Safely import a module with user-friendly error handling."""
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        if fallback_message:
            print(f"[Warning] {fallback_message}")
        else:
            print(f"[Warning] Optional module '{module_name}' not available: {e}")
        return None