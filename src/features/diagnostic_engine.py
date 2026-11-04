"""
RenderFox Diagnostic Engine
Provides system diagnostics, health checks, and performance analysis.
"""

import os
import sys
import platform
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
        """Get CPU information."""
        cpu_freq = psutil.cpu_freq()
        return {
            'physical_cores': psutil.cpu_count(logical=False),
            'logical_cores': psutil.cpu_count(logical=True),
            'current_frequency': f"{cpu_freq.current:.2f} MHz" if cpu_freq else "Unknown",
            'max_frequency': f"{cpu_freq.max:.2f} MHz" if cpu_freq else "Unknown",
            'usage_percent': psutil.cpu_percent(interval=None),
            'per_core_usage': psutil.cpu_percent(interval=None, percpu=True)
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
    def get_disk_info() -> List[Dict[str, Any]]:
        """Get disk information."""
        disks = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disks.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': partition.fstype,
                    'total': f"{usage.total / (1024**3):.2f} GB",
                    'used': f"{usage.used / (1024**3):.2f} GB",
                    'free': f"{usage.free / (1024**3):.2f} GB",
                    'percent': usage.percent
                })
            except (PermissionError, OSError):
                continue
        return disks
    
    @staticmethod
    def get_gpu_info() -> List[Dict[str, Any]]:
        """Get GPU information."""
        gpus = []
        
        if GPU_UTIL_AVAILABLE:
            try:
                gpu_list = GPUtil.getGPUs()
                for gpu in gpu_list:
                    gpus.append({
                        'id': gpu.id,
                        'name': gpu.name,
                        'driver': gpu.driver,
                        'memory_total': f"{gpu.memoryTotal} MB",
                        'memory_used': f"{gpu.memoryUsed} MB",
                        'memory_free': f"{gpu.memoryFree} MB",
                        'load': f"{gpu.load * 100:.1f}%",
                        'temperature': f"{gpu.temperature}°C"
                    })
            except Exception as e:
                # Don't fail completely, just log or ignore
                pass
                
        # Fallback: Try to detect GPU via other methods if GPUtil failed or found nothing
        if not gpus:
            if platform.system() == "Windows":
                try:
                    result = subprocess.run(
                        ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                        capture_output=True, text=True, timeout=5
                    )
                    gpu_names = [line.strip() for line in result.stdout.split('\n') 
                                if line.strip() and line.strip() != 'Name']
                    for name in gpu_names:
                        gpus.append({'name': name, 'details': 'Limited info (install GPUtil for more)'})
                except Exception:
                    pass
            
            # OpenGL Fallback (New)
            if not gpus and OPENGL_AVAILABLE:
                try:
                    gl_info = OpenGLInfo.get_opengl_info()
                    if 'renderer' in gl_info and 'error' not in gl_info:
                         gpus.append({
                            'name': gl_info['renderer'],
                            'vendor': gl_info.get('vendor', 'Unknown'),
                            'version': gl_info.get('version', 'Unknown'),
                            'details': 'Detected via OpenGL Context'
                        })
                except Exception:
                    pass
            
            if not gpus:
                gpus.append({'name': 'Unknown GPU', 'details': 'Install GPUtil package for GPU monitoring'})
        
        return gpus


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
    
    @staticmethod
    def check_package(package_name: str) -> Dict[str, Any]:
        """Check if a package is installed and get its version."""
        try:
            if package_name == 'pyassimp':
                import pyassimp
                version = getattr(pyassimp, '__version__', 'Unknown')
            else:
                module = __import__(package_name.replace('-', '_'))
                version = getattr(module, '__version__', 'Unknown')
            
            return {
                'installed': True,
                'version': version,
                'status': 'OK'
            }
        except ImportError:
            return {
                'installed': False,
                'version': None,
                'status': 'Not Installed'
            }
        except Exception as e:
            return {
                'installed': False,
                'version': None,
                'status': f'Error: {str(e)}'
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
    """Performs health checks on the application."""
    
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
    def check_disk_space() -> Dict[str, Any]:
        """Check if disk space is adequate."""
        try:
            usage = psutil.disk_usage('/')
            
            status = 'healthy'
            if usage.percent > 95:
                status = 'critical'
            elif usage.percent > 85:
                status = 'warning'
            
            return {
                'status': status,
                'usage_percent': usage.percent,
                'free_gb': usage.free / (1024**3),
                'message': f"Disk usage at {usage.percent}%"
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f"Failed to check disk space: {str(e)}"
            }
    
    @staticmethod
    def check_gpu_availability() -> Dict[str, Any]:
        """Check if GPU is available and healthy."""
        gpus = SystemInfo.get_gpu_info()
        
        if not gpus or 'error' in gpus[0]:
            return {
                'status': 'warning',
                'message': 'No GPU detected or GPU monitoring unavailable'
            }
        
        # Check GPU temperature if available
        for gpu in gpus:
            if 'temperature' in gpu:
                try:
                    temp = float(gpu['temperature'].replace('°C', ''))
                    if temp > 85:
                        return {
                            'status': 'warning',
                            'message': f"GPU temperature high: {temp}°C"
                        }
                except:
                    pass
        
        return {
            'status': 'healthy',
            'message': f"{len(gpus)} GPU(s) available"
        }
    
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
    def run_all_checks(cls) -> Dict[str, Dict[str, Any]]:
        """Run all health checks."""
        return {
            'memory': cls.check_memory_usage(),
            'disk': cls.check_disk_space(),
            'gpu': cls.check_gpu_availability(),
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
        """Generate a complete system diagnostic report."""
        return {
            'timestamp': datetime.now().isoformat(),
            'os': SystemInfo.get_os_info(),
            'cpu': SystemInfo.get_cpu_info(),
            'memory': SystemInfo.get_memory_info(),
            'disk': SystemInfo.get_disk_info(),
            'gpu': SystemInfo.get_gpu_info(),
            'opengl': OpenGLInfo.get_opengl_info(),
            'dependencies': DependencyChecker.check_all_dependencies(),
            'health_checks': HealthChecker.run_all_checks(),
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
    
    def get_recommendations(self) -> List[str]:
        """Get recommendations based on system analysis."""
        recommendations = []
        health = HealthChecker.run_all_checks()
        
        if health['memory']['status'] != 'healthy':
            recommendations.append(f"⚠️ {health['memory']['message']}")
        
        if health['disk']['status'] != 'healthy':
            recommendations.append(f"⚠️ {health['disk']['message']}")
        
        if health['gpu']['status'] == 'warning':
            recommendations.append(f"⚠️ {health['gpu']['message']}")
        
        if health['dependencies']['status'] != 'healthy':
            recommendations.append(f"⚠️ {health['dependencies']['message']}")
        
        if not recommendations:
            recommendations.append("✅ All systems are healthy!")
        
        return recommendations