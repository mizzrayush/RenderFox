"""
RenderFox Performance Analyzer
Provides real-time performance monitoring, profiling, and optimization recommendations.
"""

import time
import psutil
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from collections import deque
import json
import os
import numpy as np

try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False

try:
    import GPUtil
    GPU_UTIL_AVAILABLE = True
except ImportError:
    GPU_UTIL_AVAILABLE = False

from PyQt6.QtCore import QObject, pyqtSignal, QTimer


@dataclass
class PerformanceMetrics:
    """Container for performance metrics at a point in time."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    gpu_percent: float = 0.0
    gpu_memory_percent: float = 0.0
    fps: float = 0.0
    frame_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_used_mb': self.memory_used_mb,
            'gpu_percent': self.gpu_percent,
            'gpu_memory_percent': self.gpu_memory_percent,
            'fps': self.fps,
            'frame_time_ms': self.frame_time_ms
        }


@dataclass
class ProfileResult:
    """Result from profiling a function or operation."""
    function_name: str
    call_count: int
    total_time: float
    average_time: float
    min_time: float
    max_time: float
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'function_name': self.function_name,
            'call_count': self.call_count,
            'total_time': self.total_time,
            'average_time': self.average_time,
            'min_time': self.min_time,
            'max_time': self.max_time,
            'timestamp': self.timestamp
        }


class PerformanceMonitor(QObject):
    """Real-time performance monitoring with history tracking."""
    
    metrics_updated = pyqtSignal(dict)  # Emits current metrics
    
    def __init__(self, history_size: int = 300):
        super().__init__()
        self.history_size = history_size
        self.metrics_history: deque = deque(maxlen=history_size)
        self.is_monitoring = False
        self.update_interval = 1000  # ms
        
        # Monitoring timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_metrics)
        
        # FPS tracking
        self._frame_times = deque(maxlen=60)
        self._last_frame_time = time.time()
        
    def start_monitoring(self, interval_ms: int = 1000):
        """Start real-time monitoring."""
        self.update_interval = interval_ms
        self.is_monitoring = True
        self.timer.start(interval_ms)
        
    def stop_monitoring(self):
        """Stop monitoring."""
        self.is_monitoring = False
        self.timer.stop()
        
    def _update_metrics(self):
        """Update and emit current metrics."""
        metrics = self.get_current_metrics()
        self.metrics_history.append(metrics)
        self.metrics_updated.emit(metrics.to_dict())
        
    def get_current_metrics(self) -> PerformanceMetrics:
        """Get current system performance metrics."""
        # CPU and Memory
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_used_mb = memory.used / (1024 * 1024)
        
        # GPU metrics
        gpu_percent = 0.0
        gpu_memory_percent = 0.0
        
        if GPU_UTIL_AVAILABLE:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    gpu_percent = gpu.load * 100
                    gpu_memory_percent = gpu.memoryUtil * 100
            except Exception:
                pass
        
        # FPS calculation
        current_time = time.time()
        frame_time = current_time - self._last_frame_time
        self._last_frame_time = current_time
        self._frame_times.append(frame_time)
        
        avg_frame_time = sum(self._frame_times) / len(self._frame_times) if self._frame_times else 0.016
        fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0.0
        
        return PerformanceMetrics(
            timestamp=time.time(),
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used_mb=memory_used_mb,
            gpu_percent=gpu_percent,
            gpu_memory_percent=gpu_memory_percent,
            fps=fps,
            frame_time_ms=avg_frame_time * 1000
        )
    
    def get_metrics_history(self, last_n: Optional[int] = None) -> List[PerformanceMetrics]:
        """Get historical metrics."""
        if last_n:
            return list(self.metrics_history)[-last_n:]
        return list(self.metrics_history)
    
    def get_average_metrics(self, last_n: int = 60) -> Dict[str, float]:
        """Get average metrics over last N samples."""
        recent = self.get_metrics_history(last_n)
        
        if not recent:
            return {
                'cpu_percent': 0.0,
                'memory_percent': 0.0,
                'gpu_percent': 0.0,
                'fps': 0.0
            }
        
        return {
            'cpu_percent': sum(m.cpu_percent for m in recent) / len(recent),
            'memory_percent': sum(m.memory_percent for m in recent) / len(recent),
            'gpu_percent': sum(m.gpu_percent for m in recent) / len(recent),
            'fps': sum(m.fps for m in recent) / len(recent),
            'frame_time_ms': sum(m.frame_time_ms for m in recent) / len(recent)
        }
    
    def get_peak_metrics(self) -> Dict[str, float]:
        """Get peak values from history."""
        if not self.metrics_history:
            return {
                'cpu_percent': 0.0,
                'memory_percent': 0.0,
                'gpu_percent': 0.0,
                'memory_used_mb': 0.0
            }
        
        return {
            'cpu_percent': max(m.cpu_percent for m in self.metrics_history),
            'memory_percent': max(m.memory_percent for m in self.metrics_history),
            'gpu_percent': max(m.gpu_percent for m in self.metrics_history),
            'memory_used_mb': max(m.memory_used_mb for m in self.metrics_history)
        }
    
    def clear_history(self):
        """Clear metrics history."""
        self.metrics_history.clear()


class FunctionProfiler:
    """Profile individual function performance."""
    
    def __init__(self):
        self.profiles: Dict[str, List[float]] = {}
        self._active_timers: Dict[str, float] = {}
        
    def start_profile(self, function_name: str):
        """Start profiling a function."""
        self._active_timers[function_name] = time.perf_counter()
        
    def end_profile(self, function_name: str):
        """End profiling and record time."""
        if function_name not in self._active_timers:
            return
        
        elapsed = time.perf_counter() - self._active_timers[function_name]
        
        if function_name not in self.profiles:
            self.profiles[function_name] = []
        
        self.profiles[function_name].append(elapsed)
        del self._active_timers[function_name]
        
    def get_profile_result(self, function_name: str) -> Optional[ProfileResult]:
        """Get profiling results for a function."""
        if function_name not in self.profiles or not self.profiles[function_name]:
            return None
        
        times = self.profiles[function_name]
        
        return ProfileResult(
            function_name=function_name,
            call_count=len(times),
            total_time=sum(times),
            average_time=sum(times) / len(times),
            min_time=min(times),
            max_time=max(times),
            timestamp=time.time()
        )
    
    def get_all_results(self) -> List[ProfileResult]:
        """Get all profiling results."""
        results = []
        for func_name in self.profiles.keys():
            result = self.get_profile_result(func_name)
            if result:
                results.append(result)
        return results
    
    def clear_profile(self, function_name: str):
        """Clear profile data for a function."""
        if function_name in self.profiles:
            del self.profiles[function_name]
            
    def clear_all(self):
        """Clear all profile data."""
        self.profiles.clear()
        self._active_timers.clear()


class BottleneckDetector:
    """Detect performance bottlenecks."""
    
    def __init__(self):
        self.thresholds = {
            'cpu_high': 80.0,
            'memory_high': 85.0,
            'gpu_high': 90.0,
            'fps_low': 30.0,
            'frame_time_high': 33.0  # ms (corresponds to 30 FPS)
        }
        
    def analyze_metrics(self, metrics: PerformanceMetrics) -> List[Dict[str, str]]:
        """Analyze metrics and detect bottlenecks."""
        bottlenecks = []
        
        # CPU bottleneck
        if metrics.cpu_percent > self.thresholds['cpu_high']:
            bottlenecks.append({
                'type': 'CPU',
                'severity': 'High' if metrics.cpu_percent > 95 else 'Medium',
                'value': f"{metrics.cpu_percent:.1f}%",
                'description': 'CPU usage is high. Consider optimizing CPU-heavy operations.',
                'recommendation': 'Use multi-threading, optimize algorithms, or reduce processing complexity.'
            })
        
        # Memory bottleneck
        if metrics.memory_percent > self.thresholds['memory_high']:
            bottlenecks.append({
                'type': 'Memory',
                'severity': 'High' if metrics.memory_percent > 95 else 'Medium',
                'value': f"{metrics.memory_percent:.1f}%",
                'description': 'Memory usage is high. System may start swapping.',
                'recommendation': 'Free up memory, close unused applications, or upgrade RAM.'
            })
        
        # GPU bottleneck
        if metrics.gpu_percent > self.thresholds['gpu_high']:
            bottlenecks.append({
                'type': 'GPU',
                'severity': 'High' if metrics.gpu_percent > 95 else 'Medium',
                'value': f"{metrics.gpu_percent:.1f}%",
                'description': 'GPU is heavily loaded. Rendering may be slow.',
                'recommendation': 'Reduce polygon count, optimize shaders, or lower resolution.'
            })
        
        # FPS bottleneck
        if metrics.fps > 0 and metrics.fps < self.thresholds['fps_low']:
            bottlenecks.append({
                'type': 'FPS',
                'severity': 'Medium',
                'value': f"{metrics.fps:.1f} FPS",
                'description': 'Frame rate is low. User experience may be affected.',
                'recommendation': 'Optimize rendering pipeline, reduce scene complexity, or enable LOD.'
            })
        
        # Frame time bottleneck
        if metrics.frame_time_ms > self.thresholds['frame_time_high']:
            bottlenecks.append({
                'type': 'Frame Time',
                'severity': 'Medium',
                'value': f"{metrics.frame_time_ms:.1f}ms",
                'description': 'Frame rendering is taking too long.',
                'recommendation': 'Profile rendering code, optimize draw calls, or use instancing.'
            })
        
        return bottlenecks
    
    def get_performance_score(self, metrics: PerformanceMetrics) -> int:
        """Calculate overall performance score (0-100)."""
        score = 100
        
        # Deduct points for high resource usage
        if metrics.cpu_percent > self.thresholds['cpu_high']:
            score -= (metrics.cpu_percent - self.thresholds['cpu_high']) * 0.5
        
        if metrics.memory_percent > self.thresholds['memory_high']:
            score -= (metrics.memory_percent - self.thresholds['memory_high']) * 0.4
        
        if metrics.gpu_percent > self.thresholds['gpu_high']:
            score -= (metrics.gpu_percent - self.thresholds['gpu_high']) * 0.6
        
        # Deduct points for low FPS
        if metrics.fps > 0 and metrics.fps < 60:
            score -= (60 - metrics.fps) * 0.3
        
        return max(0, min(100, int(score)))


class OptimizationSuggester:
    """Suggest optimizations based on performance analysis."""
    
    @staticmethod
    def get_suggestions(metrics: PerformanceMetrics, bottlenecks: List[Dict]) -> List[Dict[str, str]]:
        """Get optimization suggestions."""
        suggestions = []
        
        # General suggestions based on metrics
        if metrics.cpu_percent > 70:
            suggestions.append({
                'category': 'CPU Optimization',
                'priority': 'High',
                'suggestion': 'Enable multi-threading for batch operations',
                'impact': 'Can reduce CPU load by 30-50%',
                'difficulty': 'Medium'
            })
            
            suggestions.append({
                'category': 'CPU Optimization',
                'priority': 'Medium',
                'suggestion': 'Use LOD (Level of Detail) for distant objects',
                'impact': 'Reduces polygon processing load',
                'difficulty': 'Easy'
            })
        
        if metrics.memory_percent > 75:
            suggestions.append({
                'category': 'Memory Optimization',
                'priority': 'High',
                'suggestion': 'Enable memory pooling and object reuse',
                'impact': 'Can reduce memory usage by 20-40%',
                'difficulty': 'Medium'
            })
            
            suggestions.append({
                'category': 'Memory Optimization',
                'priority': 'Medium',
                'suggestion': 'Implement texture compression',
                'impact': 'Reduces texture memory by 50-75%',
                'difficulty': 'Easy'
            })
        
        if metrics.gpu_percent > 80:
            suggestions.append({
                'category': 'GPU Optimization',
                'priority': 'High',
                'suggestion': 'Use GPU instancing for repeated objects',
                'impact': 'Can improve GPU performance by 40-60%',
                'difficulty': 'Hard'
            })
            
            suggestions.append({
                'category': 'GPU Optimization',
                'priority': 'High',
                'suggestion': 'Optimize shader complexity',
                'impact': 'Reduces GPU computation time',
                'difficulty': 'Medium'
            })
        
        if metrics.fps > 0 and metrics.fps < 30:
            suggestions.append({
                'category': 'Rendering Optimization',
                'priority': 'Critical',
                'suggestion': 'Enable frustum culling and occlusion culling',
                'impact': 'Can double or triple FPS',
                'difficulty': 'Medium'
            })
            
            suggestions.append({
                'category': 'Rendering Optimization',
                'priority': 'High',
                'suggestion': 'Reduce draw calls by batching geometry',
                'impact': 'Improves rendering efficiency by 30-50%',
                'difficulty': 'Medium'
            })
        
        # Add suggestions based on specific bottlenecks
        for bottleneck in bottlenecks:
            if bottleneck['type'] == 'Memory' and bottleneck['severity'] == 'High':
                suggestions.append({
                    'category': 'Emergency Memory Fix',
                    'priority': 'Critical',
                    'suggestion': 'Clear model cache and reload only active scenes',
                    'impact': 'Immediate memory relief',
                    'difficulty': 'Easy'
                })
        
        return suggestions


class PerformanceLogger:
    """Log performance data for analysis."""
    
    def __init__(self, log_dir: Optional[str] = None):
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'performance_logs')
        
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
    def log_metrics(self, metrics: PerformanceMetrics, session_name: str = "default"):
        """Log metrics to file."""
        log_file = os.path.join(self.log_dir, f"{session_name}_{datetime.now().strftime('%Y%m%d')}.json")
        
        # Read existing data
        data = []
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    data = json.load(f)
            except:
                data = []
        
        # Append new metrics
        data.append(metrics.to_dict())
        
        # Write back
        with open(log_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def log_profile_results(self, results: List[ProfileResult], session_name: str = "default"):
        """Log profiling results."""
        log_file = os.path.join(self.log_dir, f"profiles_{session_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        
        data = [result.to_dict() for result in results]
        
        with open(log_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_session_logs(self, session_name: str = "default") -> List[Dict]:
        """Get logs for a session."""
        log_file = os.path.join(self.log_dir, f"{session_name}_{datetime.now().strftime('%Y%m%d')}.json")
        
        if not os.path.exists(log_file):
            return []
        
        try:
            with open(log_file, 'r') as f:
                return json.load(f)
        except:
            return []


class BenchmarkRunner:
    """Run system benchmarks."""
    
    @staticmethod
    def run_cpu_benchmark(duration: float = 2.0) -> Dict[str, Any]:
        """Run CPU benchmark (matrix multiplication)."""
        start_time = time.time()
        operations = 0
        
        # Matrix size
        N = 256
        
        while time.time() - start_time < duration:
            # CPU intensive task: Matrix multiplication
            A = np.random.rand(N, N)
            B = np.random.rand(N, N)
            np.dot(A, B)
            operations += 1
            
        elapsed = time.time() - start_time
        ops_per_sec = operations / elapsed
        score = int(ops_per_sec * 1000)
        
        return {
            'type': 'CPU',
            'score': score,
            'operations': operations,
            'elapsed': elapsed,
            'description': f'Matrix multiplication ({N}x{N})'
        }

    @staticmethod
    def run_gpu_benchmark() -> Dict[str, Any]:
        """Run GPU benchmark."""
        if not OPEN3D_AVAILABLE:
             return {'error': 'Open3D not available for GPU benchmark'}
             
        try:
            # Create a large point cloud
            points = np.random.rand(500000, 3)
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(points)
            
            start_time = time.time()
            # Heavy operation: Normal estimation (uses OpenMP/GPU if available in O3D build)
            pcd.estimate_normals()
            elapsed = time.time() - start_time
            
            score = int(500000 / elapsed / 100) 
            
            return {
                'type': 'GPU',
                'score': score,
                'elapsed': elapsed,
                'description': 'Normal estimation on 500k points'
            }
        except Exception as e:
             return {'error': str(e)}


class PerformanceAnalyzer:
    """Main performance analyzer coordinating all performance monitoring features."""
    
    def __init__(self):
        self.monitor = PerformanceMonitor()
        self.profiler = FunctionProfiler()
        self.bottleneck_detector = BottleneckDetector()
        self.optimization_suggester = OptimizationSuggester()
        self.optimization_suggester = OptimizationSuggester()
        self.logger = PerformanceLogger()
        self.benchmark = BenchmarkRunner()
        
    def start_monitoring(self, interval_ms: int = 1000):
        """Start real-time monitoring."""
        self.monitor.start_monitoring(interval_ms)
        
    def stop_monitoring(self):
        """Stop monitoring."""
        self.monitor.stop_monitoring()
        
    def get_current_analysis(self) -> Dict[str, Any]:
        """Get complete current performance analysis."""
        metrics = self.monitor.get_current_metrics()
        bottlenecks = self.bottleneck_detector.analyze_metrics(metrics)
        score = self.bottleneck_detector.get_performance_score(metrics)
        suggestions = self.optimization_suggester.get_suggestions(metrics, bottlenecks)
        
        return {
            'timestamp': metrics.timestamp,
            'metrics': metrics.to_dict(),
            'bottlenecks': bottlenecks,
            'performance_score': score,
            'suggestions': suggestions,
            'average_metrics': self.monitor.get_average_metrics(),
            'peak_metrics': self.monitor.get_peak_metrics()
        }
    
    def get_historical_analysis(self, last_n: int = 300) -> Dict[str, Any]:
        """Get historical performance analysis."""
        history = self.monitor.get_metrics_history(last_n)
        
        if not history:
            return {
                'data_points': 0,
                'history': [],
                'trends': {}
            }
        
        # Calculate trends
        cpu_trend = [m.cpu_percent for m in history]
        memory_trend = [m.memory_percent for m in history]
        gpu_trend = [m.gpu_percent for m in history]
        fps_trend = [m.fps for m in history]
        
        return {
            'data_points': len(history),
            'history': [m.to_dict() for m in history],
            'trends': {
                'cpu': {
                    'average': sum(cpu_trend) / len(cpu_trend),
                    'peak': max(cpu_trend),
                    'current': cpu_trend[-1] if cpu_trend else 0
                },
                'memory': {
                    'average': sum(memory_trend) / len(memory_trend),
                    'peak': max(memory_trend),
                    'current': memory_trend[-1] if memory_trend else 0
                },
                'gpu': {
                    'average': sum(gpu_trend) / len(gpu_trend),
                    'peak': max(gpu_trend),
                    'current': gpu_trend[-1] if gpu_trend else 0
                },
                'fps': {
                    'average': sum(fps_trend) / len(fps_trend) if any(fps_trend) else 0,
                    'minimum': min(fps_trend) if any(fps_trend) else 0,
                    'current': fps_trend[-1] if fps_trend else 0
                }
            }
        }
    
    def start_profiling(self, function_name: str):
        """Start profiling a function."""
        self.profiler.start_profile(function_name)
        
    def end_profiling(self, function_name: str):
        """End profiling a function."""
        self.profiler.end_profile(function_name)
        
    def get_profiling_results(self) -> List[ProfileResult]:
        """Get all profiling results."""
        return self.profiler.get_all_results()
    
    def export_performance_report(self, output_path: Optional[str] = None) -> str:
        """Export comprehensive performance report."""
        analysis = self.get_current_analysis()
        historical = self.get_historical_analysis()
        profiling = [r.to_dict() for r in self.get_profiling_results()]
        
        report = {
            'report_date': datetime.now().isoformat(),
            'current_analysis': analysis,
            'historical_data': historical,
            'profiling_results': profiling
        }
        
        if output_path is None:
            output_path = os.path.join(
                self.logger.log_dir,
                f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        return output_path
    
    def clear_all_data(self):
        """Clear all performance data."""
        self.monitor.clear_history()
        self.profiler.clear_all()
