"""
Performance tab for GPU acceleration, monitoring, and optimization.
"""

import os
import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
                             QPushButton, QComboBox, QLabel, QGroupBox, QFormLayout, 
                             QSpinBox, QDoubleSpinBox, QSlider, QTabWidget, QCheckBox,
                             QFrame, QGridLayout, QScrollArea, QTextEdit, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
                             QListWidget, QTreeWidget, QTreeWidgetItem, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, pyqtSlot, QThreadPool
from PyQt6.QtGui import QFont, QColor, QPainter
import psutil
import gc
import sys
from PyQt6.QtWidgets import QMessageBox
import platform
from .icon_provider import get_icon

# Try to import GPUtil for GPU monitoring
try:
    import GPUtil
    GPUTIL_AVAILABLE = True
except ImportError:
    GPUTIL_AVAILABLE = False

# Import performance analyzer backend
from ..features.performance_analyzer import (
    PerformanceAnalyzer, BenchmarkRunner
)
from ..utils.worker import Worker
from ..utils.run_teardown import drain

GPU_POWER_NOTE = ("Nothing here measures what power the graphics chip draws - the tool that "
                  "reports how busy it is, its memory and its temperature does not report "
                  "power")
GPU_NOT_READ_NOTE = "not measured yet - press Detect GPU Hardware"

class SystemMonitorWidget(QWidget):
    """Real-time system monitoring widget."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.cpu_history = []
        self.memory_history = []
        self.gpu_history = []
        self.max_history = 60  # 60 seconds of history
        
        # Timer for updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(1000)  # Update every second
        
    def update_data(self):
        """Update monitoring data."""
        # CPU usage
        cpu_percent = psutil.cpu_percent()
        self.cpu_history.append(cpu_percent)
        if len(self.cpu_history) > self.max_history:
            self.cpu_history.pop(0)
            
        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        self.memory_history.append(memory_percent)
        if len(self.memory_history) > self.max_history:
            self.memory_history.pop(0)
            
        # GPU usage
        gpu_percent = 0
        if GPUTIL_AVAILABLE:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_percent = gpus[0].load * 100
            except Exception:
                pass
        
        self.gpu_history.append(gpu_percent)
        if len(self.gpu_history) > self.max_history:
            self.gpu_history.pop(0)
            
        self.update()
        
    def paintEvent(self, event):
        """Paint the monitoring graphs."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(240, 240, 240))
        
        if not self.cpu_history:
            return
            
        width = self.width()
        height = self.height()
        
        # Draw three graphs vertically
        graph_height = height // 3
        
        # CPU graph
        self.draw_graph(painter, self.cpu_history, 0, 0, width, graph_height, 
                       QColor(255, 100, 100), "CPU")
        
        # Memory graph
        self.draw_graph(painter, self.memory_history, 0, graph_height, width, graph_height,
                       QColor(100, 255, 100), "Memory")
        
        # GPU graph
        self.draw_graph(painter, self.gpu_history, 0, 2 * graph_height, width, graph_height,
                       QColor(100, 100, 255), "GPU")
        
    def draw_graph(self, painter, data, x, y, width, height, color, label):
        """Draw a single monitoring graph."""
        if len(data) < 2:
            return
            
        painter.fillRect(x, y, width, height, QColor(250, 250, 250))
        painter.setPen(Qt.GlobalColor.black)
        painter.drawRect(x, y, width, height)
        
        # Draw label
        painter.drawText(x + 5, y + 15, label)
        
        # Draw current value
        current_value = data[-1] if data else 0
        painter.drawText(x + width - 50, y + 15, f"{current_value:.1f}%")
        
        # Draw graph lines
        painter.setPen(color)
        points_per_pixel = len(data) / width
        
        for i in range(1, len(data)):
            x1 = x + int(i / points_per_pixel)
            y1 = y + height - int((data[i-1] / 100) * (height - 20))
            x2 = x + int((i+1) / points_per_pixel)
            y2 = y + height - int((data[i] / 100) * (height - 20))
            
            if x1 < x + width and x2 < x + width:
                painter.drawLine(x1, y1, x2, y2)

class PerformanceTab(QWidget):
    """Performance monitoring and GPU acceleration controls."""
    
    performance_updated = pyqtSignal(dict)
    gpu_settings_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_settings = {}
        self.benchmark_results = []
        self._workers = []
        self.gpu_report = None
        self.storage_info = None
        
        # Initialize performance analyzer backend
        self.performance_analyzer = PerformanceAnalyzer()
        
        self.init_ui()
        self.setup_connections()
        self.start_monitoring()

    # ---- the one way a started run is held and released -------------------------

    def _keep_worker(self, worker):
        """Hold a started run until it says it is done.

        Without the reference this pane has nothing to take the handlers off of when the
        window closes, and a run still queued at that moment writes its measurement into
        labels Qt has already destroyed. The run releases itself through its own
        `finished`, so a long session does not accumulate every measurement it made.
        """
        self._workers.append(worker)
        worker.signals.finished.connect(lambda: self._release_worker(worker))
        return worker

    def _release_worker(self, worker):
        """Let a run go when it says it is done - once, whoever else let go first.

        The removal is guarded because `shutdown_runs` releases the same worker on its way
        out; a second `list.remove` of it raises inside a slot, and PyQt answers an
        exception that escapes a slot by ending the process.
        """
        if worker in self._workers:
            self._workers.remove(worker)

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Silence every run this pane started and wait for the pool that runs them.

        The measurements arrive through `result`, fail through `error`, and drive the bar
        through `progress` - three channels into widgets that are on their way out. These
        runs are `QRunnable`s on the shared pool rather than threads, so there is no stop
        to ask of one and the wait is the only question a pool answers: did its queue
        drain. What has not drained stays held here.
        Returns the runs still owed to the pool when the wait gave up.
        """
        return len(drain(self._workers, timeout_ms, QThreadPool.globalInstance()))
        
    def init_ui(self):
        """Initialize the performance interface."""
        main_layout = QVBoxLayout(self)
        
        # Create tab widget for different performance areas
        self.performance_tabs = QTabWidget()
        
        # GPU Acceleration tab
        gpu_tab = self.create_gpu_tab()
        self.performance_tabs.addTab(gpu_tab, "GPU Acceleration")
        
        # System Monitor tab
        monitor_tab = self.create_monitor_tab()
        self.performance_tabs.addTab(monitor_tab, "System Monitor")
        
        # Benchmarks tab
        benchmark_tab = self.create_benchmark_tab()
        self.performance_tabs.addTab(benchmark_tab, "Benchmarks")
        
        # Optimization tab
        optimization_tab = self.create_optimization_tab()
        self.performance_tabs.addTab(optimization_tab, "Optimization")
        
        # Memory Management tab
        memory_tab = self.create_memory_tab()
        self.performance_tabs.addTab(memory_tab, "Memory")
        
        main_layout.addWidget(self.performance_tabs)
        
    def create_gpu_tab(self):
        """Create GPU acceleration settings."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)
        
        # GPU Detection
        detection_group = QGroupBox("GPU Detection")
        detection_layout = QVBoxLayout()
        
        self.detect_gpu_btn = QPushButton("Detect GPU Hardware")
        self.detect_gpu_btn.setIcon(get_icon("scan"))
        self.detect_gpu_btn.setProperty("primary", "true")
        self.gpu_info_display = QTextEdit()
        self.gpu_info_display.setMinimumHeight(180)
        self.gpu_info_display.setMaximumHeight(350)
        self.gpu_info_display.setReadOnly(True)
        self.gpu_info_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.gpu_info_display.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.gpu_info_display.setPlainText("Click 'Detect GPU Hardware' to scan for available GPUs...")
        
        detection_layout.addWidget(self.detect_gpu_btn)
        detection_layout.addWidget(self.gpu_info_display)
        
        detection_group.setLayout(detection_layout)
        layout.addWidget(detection_group)
        
        # GPU Settings
        settings_group = QGroupBox("GPU Acceleration Settings")
        settings_layout = QFormLayout()
        settings_layout.setVerticalSpacing(12)
        settings_layout.setHorizontalSpacing(16)
        
        # Enable GPU acceleration
        self.enable_gpu_cb = QCheckBox("Enable GPU Acceleration")
        self.enable_gpu_cb.setChecked(False)
        self.enable_gpu_cb.toggled.connect(self.toggle_gpu_acceleration)
        
        # GPU device selection
        self.gpu_device_combo = QComboBox()
        self.gpu_device_combo.addItems(["Auto Select", "NVIDIA RTX 4080", "AMD RX 7800 XT", "Intel Arc A750"])
        self.gpu_device_combo.setEnabled(False)
        
        # Memory allocation
        self.gpu_memory_spin = QSpinBox()
        self.gpu_memory_spin.setRange(512, 24576)
        self.gpu_memory_spin.setValue(4096)
        self.gpu_memory_spin.setSuffix(" MB")
        self.gpu_memory_spin.setEnabled(False)
        
        # Compute capability
        self.compute_capability_combo = QComboBox()
        self.compute_capability_combo.addItems(["Auto", "CUDA 11.8", "CUDA 12.0", "OpenCL 3.0", "Vulkan"])
        self.compute_capability_combo.setEnabled(False)
        
        # Precision mode
        self.precision_combo = QComboBox()
        self.precision_combo.addItems(["Mixed Precision", "FP32", "FP16", "INT8"])
        self.precision_combo.setEnabled(False)
        
        settings_layout.addRow(self.enable_gpu_cb)
        settings_layout.addRow("GPU Device:", self.gpu_device_combo)
        settings_layout.addRow("Memory Allocation:", self.gpu_memory_spin)
        settings_layout.addRow("Compute API:", self.compute_capability_combo)
        settings_layout.addRow("Precision:", self.precision_combo)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # GPU Operations
        operations_group = QGroupBox("GPU-Accelerated Operations")
        operations_layout = QVBoxLayout()
        
        # Checkboxes for different operations
        self.gpu_rendering_cb = QCheckBox("GPU Rendering")
        self.gpu_denoising_cb = QCheckBox("GPU Image Denoising")
        self.gpu_mesh_processing_cb = QCheckBox("GPU Mesh Processing")
        self.gpu_format_conversion_cb = QCheckBox("GPU Format Conversion")
        self.gpu_lod_generation_cb = QCheckBox("GPU LOD Generation")
        
        operations_layout.addWidget(self.gpu_rendering_cb)
        operations_layout.addWidget(self.gpu_denoising_cb)
        operations_layout.addWidget(self.gpu_mesh_processing_cb)
        operations_layout.addWidget(self.gpu_format_conversion_cb)
        operations_layout.addWidget(self.gpu_lod_generation_cb)
        
        operations_group.setLayout(operations_layout)
        layout.addWidget(operations_group)
        
        # GPU Status
        status_group = QGroupBox("GPU Status")
        status_layout = QFormLayout()

        # Nothing has been read for these four rows at pane start. They used to be filled
        # with "45%", "6,847 MB", "72 degC", "285W" every two seconds, on a machine whose
        # utilisation no installed reader can answer for.
        self.gpu_utilization_label = QLabel(GPU_NOT_READ_NOTE)
        self.gpu_memory_used_label = QLabel(GPU_NOT_READ_NOTE)
        self.gpu_temperature_label = QLabel(GPU_NOT_READ_NOTE)
        self.gpu_power_label = QLabel(GPU_POWER_NOTE)
        
        status_layout.addRow("GPU Utilization:", self.gpu_utilization_label)
        status_layout.addRow("Memory Used:", self.gpu_memory_used_label)
        status_layout.addRow("Temperature:", self.gpu_temperature_label)
        status_layout.addRow("Power Draw:", self.gpu_power_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        layout.addStretch()
        scroll.setWidget(widget)
        return scroll
        
    def create_monitor_tab(self):
        """Create system monitoring interface."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Real-time graphs
        graphs_group = QGroupBox("Real-time System Monitoring")
        graphs_layout = QVBoxLayout()
        
        self.system_monitor = SystemMonitorWidget()
        graphs_layout.addWidget(self.system_monitor)
        
        graphs_group.setLayout(graphs_layout)
        layout.addWidget(graphs_group)
        
        # System Information
        info_layout = QHBoxLayout()
        
        # CPU Info
        cpu_group = QGroupBox("CPU Information")
        cpu_layout = QFormLayout()
        
        self.cpu_model_label = QLabel("Detecting...")
        self.cpu_cores_label = QLabel("-")
        self.cpu_threads_label = QLabel("-")
        self.cpu_frequency_label = QLabel("-")
        
        cpu_layout.addRow("Model:", self.cpu_model_label)
        cpu_layout.addRow("Cores:", self.cpu_cores_label)
        cpu_layout.addRow("Threads:", self.cpu_threads_label)
        cpu_layout.addRow("Frequency:", self.cpu_frequency_label)
        
        cpu_group.setLayout(cpu_layout)
        info_layout.addWidget(cpu_group)
        
        # Populate CPU Info
        try:
            self.cpu_model_label.setText(platform.processor())
            self.cpu_cores_label.setText(str(psutil.cpu_count(logical=False)))
            self.cpu_threads_label.setText(str(psutil.cpu_count(logical=True)))
            freq = psutil.cpu_freq()
            if freq:
                self.cpu_frequency_label.setText(f"{freq.current:.0f} MHz")
        except Exception as e:
            pass
        
        # Memory Info
        memory_group = QGroupBox("Memory Information")
        memory_layout = QFormLayout()
        
        self.memory_total_label = QLabel("-")
        self.memory_available_label = QLabel("-")
        self.memory_used_label = QLabel("-")
        self.memory_cached_label = QLabel("-")
        
        memory_layout.addRow("Total:", self.memory_total_label)
        memory_layout.addRow("Available:", self.memory_available_label)
        memory_layout.addRow("Used:", self.memory_used_label)
        memory_layout.addRow("Cached:", self.memory_cached_label)
        
        memory_group.setLayout(memory_layout)
        info_layout.addWidget(memory_group)
        
        # Storage Info
        storage_group = QGroupBox("Storage Information")
        storage_layout = QFormLayout()
        
        self.storage_total_label = QLabel("-")
        self.storage_used_label = QLabel("-")
        self.storage_free_label = QLabel("-")
        self.storage_type_label = QLabel("-")
        
        storage_layout.addRow("Total:", self.storage_total_label)
        storage_layout.addRow("Used:", self.storage_used_label)
        storage_layout.addRow("Free:", self.storage_free_label)
        storage_layout.addRow("Type:", self.storage_type_label)
        
        storage_group.setLayout(storage_layout)
        info_layout.addWidget(storage_group)
        
        layout.addLayout(info_layout)
        
        # Process Monitor
        process_group = QGroupBox("Process Monitor")
        process_layout = QVBoxLayout()
        
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(4)
        self.process_table.setHorizontalHeaderLabels(["Process", "CPU %", "Memory", "Status"])
        self.process_table.setMaximumHeight(150)
        
        process_layout.addWidget(self.process_table)
        process_group.setLayout(process_layout)
        layout.addWidget(process_group)
        
        layout.addStretch()
        scroll.setWidget(widget)
        return scroll
        
    def create_benchmark_tab(self):
        """Create benchmarking interface."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Benchmark Controls
        controls_group = QGroupBox("Benchmark Controls")
        controls_layout = QHBoxLayout()
        
        self.benchmark_cpu_btn = QPushButton("CPU Benchmark")
        self.benchmark_cpu_btn.setIcon(get_icon("performance"))
        self.benchmark_geometry_btn = QPushButton("Geometry Benchmark")
        self.benchmark_geometry_btn.setIcon(get_icon("rendered"))
        self.benchmark_memory_btn = QPushButton("Memory Benchmark")
        self.benchmark_memory_btn.setIcon(get_icon("diagnostics"))
        self.benchmark_storage_btn = QPushButton("Storage Benchmark")
        self.benchmark_storage_btn.setIcon(get_icon("backup"))
        self.benchmark_full_btn = QPushButton("Full System Benchmark")
        self.benchmark_full_btn.setIcon(get_icon("sparkles"))
        self.benchmark_full_btn.setProperty("primary", "true")
        
        controls_layout.addWidget(self.benchmark_cpu_btn)
        controls_layout.addWidget(self.benchmark_geometry_btn)
        controls_layout.addWidget(self.benchmark_memory_btn)
        controls_layout.addWidget(self.benchmark_storage_btn)
        controls_layout.addWidget(self.benchmark_full_btn)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Benchmark Progress
        progress_group = QGroupBox("Benchmark Progress")
        progress_layout = QVBoxLayout()
        
        self.benchmark_progress = QProgressBar()
        self.benchmark_status = QLabel("Ready to run benchmarks")
        
        progress_layout.addWidget(self.benchmark_progress)
        progress_layout.addWidget(self.benchmark_status)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # Benchmark Results
        results_layout = QHBoxLayout()
        
        # Results table
        results_group = QGroupBox("Benchmark Results")
        results_table_layout = QVBoxLayout()
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        # The columns are the measurement, not a verdict about it. "Performance" and
        # "Rank" used to hold "Excellent" and "Top 1%": the first was a threshold the
        # work always beat, the second a percentile against results RenderFox has never
        # collected from anyone. The engine words these cells (row_cells), because a
        # table column is a claim and the claim belongs beside the number.
        self.results_table.setHorizontalHeaderLabels(
            ["Kind", "What ran", "Measured", "Against this app's own earlier runs"])
        
        results_table_layout.addWidget(self.results_table)
        results_group.setLayout(results_table_layout)
        results_layout.addWidget(results_group)
        
        # Performance comparison
        comparison_group = QGroupBox("Performance Comparison")
        comparison_layout = QVBoxLayout()
        
        self.comparison_chart = QLabel("Run benchmarks to see performance comparison")
        self.comparison_chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.comparison_chart.setMinimumHeight(200)
        self.comparison_chart.setStyleSheet("border: 1px solid #252836; background: #14151b; color: #8c93a8; border-radius: 4px;")
        
        comparison_layout.addWidget(self.comparison_chart)
        comparison_group.setLayout(comparison_layout)
        results_layout.addWidget(comparison_group)
        
        layout.addLayout(results_layout)
        
        # Export results
        export_layout = QHBoxLayout()
        self.export_results_btn = QPushButton("Export Results")
        self.export_results_btn.setIcon(get_icon("export"))
        self.clear_results_btn = QPushButton("Clear Results")
        self.clear_results_btn.setIcon(get_icon("delete"))
        export_layout.addWidget(self.export_results_btn)
        export_layout.addWidget(self.clear_results_btn)
        export_layout.addStretch()
        layout.addLayout(export_layout)
        
        layout.addStretch()
        scroll.setWidget(widget)
        return scroll
        
    def create_optimization_tab(self):
        """Create optimization settings."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Performance Profiles
        profiles_group = QGroupBox("Performance Profiles")
        profiles_layout = QVBoxLayout()
        
        # Profile selection
        profile_selection = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItems([
            "Balanced", "Performance", "Quality", "Power Saving", "Custom"
        ])
        
        self.apply_profile_btn = QPushButton("Apply Profile")
        self.save_profile_btn = QPushButton("Save Custom Profile")
        
        profile_selection.addWidget(QLabel("Profile:"))
        profile_selection.addWidget(self.profile_combo)
        profile_selection.addWidget(self.apply_profile_btn)
        profile_selection.addWidget(self.save_profile_btn)
        profile_selection.addStretch()
        
        profiles_layout.addLayout(profile_selection)
        profiles_group.setLayout(profiles_layout)
        layout.addWidget(profiles_group)
        
        # Threading optimization
        threading_group = QGroupBox("Threading & Parallelization")
        threading_layout = QFormLayout()
        
        self.max_threads_spin = QSpinBox()
        self.max_threads_spin.setRange(1, 64)
        self.max_threads_spin.setValue(8)
        
        self.thread_priority_combo = QComboBox()
        self.thread_priority_combo.addItems(["Low", "Normal", "High", "Real-time"])
        self.thread_priority_combo.setCurrentText("Normal")
        
        self.multiprocessing_cb = QCheckBox("Enable Multiprocessing")
        self.multiprocessing_cb.setChecked(True)
        
        self.affinity_cb = QCheckBox("Set CPU Affinity")
        
        threading_layout.addRow("Max Threads:", self.max_threads_spin)
        threading_layout.addRow("Thread Priority:", self.thread_priority_combo)
        threading_layout.addRow(self.multiprocessing_cb)
        threading_layout.addRow(self.affinity_cb)
        
        threading_group.setLayout(threading_layout)
        layout.addWidget(threading_group)
        
        # Memory optimization
        memory_opt_group = QGroupBox("Memory Optimization")
        memory_opt_layout = QFormLayout()
        
        self.memory_limit_spin = QSpinBox()
        self.memory_limit_spin.setRange(512, 32768)
        self.memory_limit_spin.setValue(8192)
        self.memory_limit_spin.setSuffix(" MB")
        
        self.garbage_collection_combo = QComboBox()
        self.garbage_collection_combo.addItems(["Automatic", "Manual", "Aggressive"])
        
        self.memory_mapping_cb = QCheckBox("Use Memory Mapping")
        self.memory_mapping_cb.setChecked(True)
        
        self.swap_usage_cb = QCheckBox("Allow Swap Usage")
        
        memory_opt_layout.addRow("Memory Limit:", self.memory_limit_spin)
        memory_opt_layout.addRow("Garbage Collection:", self.garbage_collection_combo)
        memory_opt_layout.addRow(self.memory_mapping_cb)
        memory_opt_layout.addRow(self.swap_usage_cb)
        
        memory_opt_group.setLayout(memory_opt_layout)
        layout.addWidget(memory_opt_group)
        
        # Cache optimization
        cache_group = QGroupBox("Cache Optimization")
        cache_layout = QFormLayout()
        
        self.cache_size_spin = QSpinBox()
        self.cache_size_spin.setRange(64, 4096)
        self.cache_size_spin.setValue(512)
        self.cache_size_spin.setSuffix(" MB")
        
        self.cache_policy_combo = QComboBox()
        self.cache_policy_combo.addItems(["LRU", "LFU", "FIFO", "Random"])
        
        self.preload_cache_cb = QCheckBox("Preload Common Assets")
        self.compress_cache_cb = QCheckBox("Compress Cache Data")
        
        cache_layout.addRow("Cache Size:", self.cache_size_spin)
        cache_layout.addRow("Cache Policy:", self.cache_policy_combo)
        cache_layout.addRow(self.preload_cache_cb)
        cache_layout.addRow(self.compress_cache_cb)
        
        cache_group.setLayout(cache_layout)
        layout.addWidget(cache_group)
        
        # I/O optimization
        io_group = QGroupBox("I/O Optimization")
        io_layout = QFormLayout()
        
        self.buffer_size_spin = QSpinBox()
        self.buffer_size_spin.setRange(4, 1024)
        self.buffer_size_spin.setValue(64)
        self.buffer_size_spin.setSuffix(" KB")
        
        self.async_io_cb = QCheckBox("Enable Async I/O")
        self.async_io_cb.setChecked(True)
        
        self.batch_operations_cb = QCheckBox("Batch File Operations")
        self.batch_operations_cb.setChecked(True)
        
        io_layout.addRow("Buffer Size:", self.buffer_size_spin)
        io_layout.addRow(self.async_io_cb)
        io_layout.addRow(self.batch_operations_cb)
        
        io_group.setLayout(io_layout)
        layout.addWidget(io_group)
        
        layout.addStretch()
        return scroll
        
    def create_memory_tab(self):
        """Create memory management interface."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Memory Usage Overview
        overview_group = QGroupBox("Memory Usage Overview")
        overview_layout = QGridLayout()
        
        # Memory stats cards
        self.total_memory_card = self.create_memory_card("Total Memory", "16.0 GB", "#3498db")
        self.used_memory_card = self.create_memory_card("Used Memory", "8.5 GB", "#e74c3c")
        self.available_memory_card = self.create_memory_card("Available", "7.5 GB", "#2ecc71")
        self.cached_memory_card = self.create_memory_card("Cached", "2.3 GB", "#f39c12")
        
        overview_layout.addWidget(self.total_memory_card, 0, 0)
        overview_layout.addWidget(self.used_memory_card, 0, 1)
        overview_layout.addWidget(self.available_memory_card, 0, 2)
        overview_layout.addWidget(self.cached_memory_card, 0, 3)
        
        overview_group.setLayout(overview_layout)
        layout.addWidget(overview_group)
        
        # Memory Management Tools
        tools_layout = QHBoxLayout()
        
        from .icon_provider import get_icon
        # Cleanup tools
        cleanup_group = QGroupBox("Memory Cleanup")
        cleanup_layout = QVBoxLayout()
        
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setIcon(get_icon("delete"))
        self.force_gc_btn = QPushButton("Force Garbage Collection")
        self.force_gc_btn.setIcon(get_icon("refresh"))
        self.trim_memory_btn = QPushButton("Trim Working Set")
        self.trim_memory_btn.setIcon(get_icon("cut"))
        self.analyze_memory_btn = QPushButton("Analyze Memory Usage")
        self.analyze_memory_btn.setIcon(get_icon("diagnostics"))
        
        cleanup_layout.addWidget(self.clear_cache_btn)
        cleanup_layout.addWidget(self.force_gc_btn)
        cleanup_layout.addWidget(self.trim_memory_btn)
        cleanup_layout.addWidget(self.analyze_memory_btn)
        
        cleanup_group.setLayout(cleanup_layout)
        tools_layout.addWidget(cleanup_group)
        
        # Memory Allocation
        allocation_group = QGroupBox("Memory Allocation")
        allocation_layout = QFormLayout()
        
        self.heap_size_spin = QSpinBox()
        self.heap_size_spin.setRange(256, 16384)
        self.heap_size_spin.setValue(2048)
        self.heap_size_spin.setSuffix(" MB")
        
        self.stack_size_spin = QSpinBox()
        self.stack_size_spin.setRange(1, 64)
        self.stack_size_spin.setValue(8)
        self.stack_size_spin.setSuffix(" MB")
        
        self.pool_size_spin = QSpinBox()
        self.pool_size_spin.setRange(64, 4096)
        self.pool_size_spin.setValue(512)
        self.pool_size_spin.setSuffix(" MB")
        
        allocation_layout.addRow("Heap Size:", self.heap_size_spin)
        allocation_layout.addRow("Stack Size:", self.stack_size_spin)
        allocation_layout.addRow("Memory Pool:", self.pool_size_spin)
        
        allocation_group.setLayout(allocation_layout)
        tools_layout.addWidget(allocation_group)
        
        layout.addLayout(tools_layout)
        
        # Memory Monitor
        monitor_group = QGroupBox("Memory Monitor")
        monitor_layout = QVBoxLayout()
        
        self.memory_processes_table = QTableWidget()
        self.memory_processes_table.setColumnCount(4)
        self.memory_processes_table.setHorizontalHeaderLabels([
            "Component", "Memory Usage", "Peak Usage", "Allocations"
        ])
        
        monitor_layout.addWidget(self.memory_processes_table)
        monitor_group.setLayout(monitor_layout)
        layout.addWidget(monitor_group)
        
        layout.addStretch()
        scroll.setWidget(widget)
        return scroll
        
    def create_memory_card(self, title, value, color):
        """Create a memory statistics card."""
        card = QFrame()
        card.setFrameStyle(QFrame.Shape.StyledPanel)
        card.setStyleSheet(f"QFrame {{ border: 2px solid {color}; border-radius: 8px; padding: 10px; }}")
        
        layout = QVBoxLayout(card)
        
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 12px; color: #666;")
        
        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {color};")
        
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        
        return card
        
    def setup_connections(self):
        """Setup signal connections."""
        # GPU tab
        self.detect_gpu_btn.clicked.connect(self.detect_gpu_hardware)
        self.enable_gpu_cb.toggled.connect(self.toggle_gpu_acceleration)
        
        # Benchmark tab
        self.benchmark_cpu_btn.clicked.connect(self.run_cpu_benchmark)
        self.benchmark_geometry_btn.clicked.connect(self.run_geometry_benchmark)
        self.benchmark_full_btn.clicked.connect(self.run_full_benchmark)
        
        # Optimization tab
        self.apply_profile_btn.clicked.connect(self.apply_performance_profile)
        
        # Memory tab
        self.clear_cache_btn.clicked.connect(self.clear_memory_cache)
        self.force_gc_btn.clicked.connect(self.force_garbage_collection)
        self.analyze_memory_btn.clicked.connect(self.analyze_memory_usage)
        
    def start_monitoring(self):
        """Start system monitoring."""
        # Connect performance analyzer signals
        self.performance_analyzer.monitor.metrics_updated.connect(self.on_metrics_updated)
        
        # Start backend monitoring
        self.performance_analyzer.start_monitoring(interval_ms=1000)
        
        self.update_system_info()
        self.refresh_storage_info()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_system_info)
        self.update_timer.start(2000)  # Update every 2 seconds
    
    @pyqtSlot(dict)
    def on_metrics_updated(self, metrics):
        """Paint what the monitor actually measured.

        This used to write `metrics['gpu_percent']` - a 0.0 the backend defaults when no
        reader answered - into the GPU rows, and the 2-second timer overwrote it with
        invented figures. GPU rows come from the adapter report now, because that is the
        only place that knows whether a reader said anything.
        """
        memory_used_gb = metrics['memory_used_mb'] / 1024
        self.used_memory_card.findChild(QLabel).setText(f"{memory_used_gb:.1f} GB")

        # Emit signal for other components
        self.performance_updated.emit(metrics)
        
    def detect_gpu_hardware(self):
        """Ask the machine which display adapters it has, and what can be read off them now.

        Each question to Windows costs about a second, so they run on a background thread
        and only when this button is pressed; the answer is kept for the status rows until
        the next press.
        """
        self.detect_gpu_btn.setEnabled(False)
        self.gpu_info_display.setPlainText("Asking Windows which adapters are present...")

        def worker_func(progress_callback=None):
            from ..features.diagnostic_engine import SystemInfo
            return SystemInfo.get_gpu_report()

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_gpu_report)
        worker.signals.error.connect(self.on_machine_reader_failed)
        worker.signals.finished.connect(lambda: self.detect_gpu_btn.setEnabled(True))
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_gpu_report(self, report: dict) -> None:
        """Paint the adapter answer, and name what could not be read instead of showing zero."""
        self.gpu_report = report
        self.gpu_info_display.setPlainText(report['text'])

        adapters = report['adapters']
        live = adapters[0]['live'] if adapters else None
        if live:
            self.gpu_utilization_label.setText(f"{live['load_percent']}% busy")
            self.gpu_memory_used_label.setText(
                f"{live['memory_used_mb']} MB "
                f"({live['memory_percent']}% of the memory Windows records here)")
            self.gpu_temperature_label.setText(f"{live['temperature_c']} degC")
        else:
            reason = report.get('load_reason') or (
                'no adapter was identified, so there is nothing to measure'
                if not adapters else
                'nothing on this machine reports what this adapter is doing')
            for label in (self.gpu_utilization_label, self.gpu_memory_used_label,
                          self.gpu_temperature_label):
                label.setText(reason)
        self.gpu_power_label.setText(GPU_POWER_NOTE)

    def refresh_storage_info(self) -> None:
        """Read the volumes and the disk behind them once, on a background thread."""
        def worker_func(progress_callback=None):
            from ..features.diagnostic_engine import SystemInfo
            return SystemInfo.get_storage_info()

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_storage_info)
        worker.signals.error.connect(self.on_machine_reader_failed)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_storage_info(self, storage: dict) -> None:
        """Keep the answer; the monitor timer paints it, so nothing blocks on Windows again."""
        self.storage_info = storage
        self.paint_storage_info()

    def paint_storage_info(self) -> None:
        """Fill the Storage rows from the last volume reading.

        This measured the drive the process happened to start on and never said which drive
        that was. It now shows the volume the app's own output directory sits on - the one a
        render can run out of room on - picked by the same helper the storage health check
        uses, with its letter printed beside every figure.
        """
        if self.storage_info is None:
            return
        from ..features.diagnostic_engine import SystemInfo
        volume = SystemInfo.working_volume(self.storage_info)
        if volume is None:
            for label in (self.storage_total_label, self.storage_used_label,
                          self.storage_free_label):
                label.setText('no mounted volume carries the app output directory')
            self.storage_type_label.setText('unknown - no volume was listed')
            return
        self.storage_total_label.setText(
            f"{volume['total_bytes'] / (1024 ** 3):.1f} GB ({volume['mountpoint']})")
        self.storage_used_label.setText(
            f"{volume['used_bytes'] / (1024 ** 3):.1f} GB ({volume['used_percent']}% full)")
        self.storage_free_label.setText(f"{volume['free_bytes'] / (1024 ** 3):.1f} GB")
        kind = volume['media_type']
        if kind:
            self.storage_type_label.setText(
                kind + (f" - {volume['disk']}" if volume['disk'] else ''))
        else:
            self.storage_type_label.setText(
                self.storage_info['reasons'][0] if self.storage_info['reasons']
                else 'nothing reports what kind of disk this is')

    def on_machine_reader_failed(self, error) -> None:
        """A reader that raised is reported as failed, not as a zero."""
        kind, value, _traceback = error
        self.gpu_info_display.setPlainText(
            f"Machine reader failed: {kind.__name__}: {value}")
        for label in (self.storage_total_label, self.storage_used_label,
                      self.storage_free_label, self.storage_type_label):
            label.setText(f'reader failed: {kind.__name__}: {value}')
        
    def toggle_gpu_acceleration(self, enabled):
        """Toggle GPU acceleration controls."""
        self.gpu_device_combo.setEnabled(enabled)
        self.gpu_memory_spin.setEnabled(enabled)
        self.compute_capability_combo.setEnabled(enabled)
        self.precision_combo.setEnabled(enabled)
        
        if enabled:
            self.detect_gpu_hardware()
            
    def run_cpu_benchmark(self):
        """Time square matrix multiplies, which is the work this kind performs."""
        self.start_benchmark('cpu', 'CPU')

    def run_geometry_benchmark(self):
        """Time point-cloud normal estimation through Open3D, and say which device ran it.

        This button was labelled GPU Benchmark while the work behind it was Open3D's
        CPU build. The engine's refusal for a `gpu` kind is what that label deserved, so
        the label names the work now and the row names the device that answered.
        """
        self.start_benchmark('geometry', 'Geometry')

    def start_benchmark(self, kind, label):
        """Run one kind in a worker thread; the interface thread times nothing itself.

        The two methods this replaces passed a `worker_func()` that took no
        `progress_callback`, which is the one argument this app's Worker always supplies,
        and never connected `signals.error`, so a failure left the bar indeterminate
        forever. Both are handled here.
        """
        self.benchmark_status.setText(f"Running {label.lower()} benchmark...")
        # Qt throws away setValue while minimum == maximum, so a busy bar cannot report numbers.
        self.benchmark_progress.setRange(0, 100)
        self.benchmark_progress.setValue(0)
        self.set_benchmark_buttons_enabled(False)
        engine = self.performance_analyzer.benchmark

        def worker_func(progress_callback=None):
            return engine.run(kind, record=True, progress_callback=progress_callback)

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_benchmark_result)
        worker.signals.error.connect(self.on_benchmark_failed)
        worker.signals.progress.connect(self.benchmark_progress.setValue)
        worker.signals.finished.connect(self.finish_benchmark)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def set_benchmark_buttons_enabled(self, enabled):
        for button in (self.benchmark_cpu_btn, self.benchmark_geometry_btn,
                       self.benchmark_memory_btn, self.benchmark_storage_btn,
                       self.benchmark_full_btn):
            button.setEnabled(enabled)

    def show_benchmark_result(self, result):
        """Paint the engine's own cells, including the one that says the work did not run."""
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        for column, text in enumerate(BenchmarkRunner.row_cells(result)):
            self.results_table.setItem(row, column, QTableWidgetItem(text))
        self.benchmark_results.append(result)
        self.paint_comparison(result)
        if result.get('ran') is None:
            self.benchmark_status.setText(
                f"{result.get('kind')} benchmark did not run: {result.get('reason')}")
        else:
            self.benchmark_status.setText(
                f"{result.get('kind')} benchmark finished: {result.get('ran')}")

    def paint_comparison(self, result):
        """The app's own earlier runs of this work, which is the only series it owns."""
        kind = result.get('kind')
        if result.get('ran') is None:
            self.comparison_chart.setText('nothing to compare - this work did not run')
            return
        stored = self.performance_analyzer.benchmark.history.recent_runs(kind)
        if stored['reason']:
            self.comparison_chart.setText(
                f"the stored runs could not be read: {stored['reason']}")
            return
        unit = result.get('comparison_unit', '')
        lines = [f"RenderFox's own runs of the {kind} work on this machine", '']
        if not stored['runs']:
            lines.append('this run was not recorded, so there is no series yet')
        for entry in stored['runs']:
            lines.append(f"{entry.get('at')} - {entry.get('value')} {unit}")
        lines.extend(['',
                      'No other machine is in this list. The app has never collected '
                      "anybody else's result, so it cannot rank this one against a field."])
        self.comparison_chart.setText('\n'.join(lines))

    def on_benchmark_failed(self, error):
        kind, value, _traceback = error
        self.benchmark_status.setText(f"benchmark failed: {kind.__name__}: {value}")

    def finish_benchmark(self):
        self.benchmark_progress.setRange(0, 100)
        self.benchmark_progress.setValue(100)
        self.set_benchmark_buttons_enabled(True)

    def run_full_benchmark(self):
        """Every kind the engine performs, in one worker, with its refusals kept."""
        self.benchmark_status.setText(
            'Running every benchmark this engine performs...')
        # Qt throws away setValue while minimum == maximum, so a busy bar cannot report numbers.
        self.benchmark_progress.setRange(0, 100)
        self.benchmark_progress.setValue(0)
        self.set_benchmark_buttons_enabled(False)
        engine = self.performance_analyzer.benchmark

        def worker_func(progress_callback=None):
            return engine.run_all(record=True, progress_callback=progress_callback)

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_full_benchmark)
        worker.signals.error.connect(self.on_benchmark_failed)
        worker.signals.progress.connect(self.benchmark_progress.setValue)
        worker.signals.finished.connect(self.finish_benchmark)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_full_benchmark(self, summary):
        for kind in BenchmarkRunner.KINDS:
            self.show_benchmark_result(summary['kinds'][kind])
        refused = summary['refused']
        self.benchmark_status.setText(
            f"measured {', '.join(summary['performed']) or 'nothing'}"
            + (f"; refused {len(refused)}: {'; '.join(refused)}" if refused else ''))
        
    def apply_performance_profile(self):
        """Apply the selected performance profile."""
        profile = self.profile_combo.currentText()
        
        if profile == "Performance":
            self.max_threads_spin.setValue(16)
            self.memory_limit_spin.setValue(12288)
            self.cache_size_spin.setValue(1024)
        elif profile == "Quality":
            self.max_threads_spin.setValue(8)
            self.memory_limit_spin.setValue(8192)
            self.cache_size_spin.setValue(512)
        elif profile == "Power Saving":
            self.max_threads_spin.setValue(4)
            self.memory_limit_spin.setValue(4096)
            self.cache_size_spin.setValue(256)
        
    def update_system_info(self):
        """Update system information."""
        try:
            # CPU info
            cpu_info = psutil.cpu_freq()
            if cpu_info:
                self.cpu_frequency_label.setText(f"{cpu_info.current:.0f} MHz")
            
            self.cpu_cores_label.setText(str(psutil.cpu_count(logical=False)))
            self.cpu_threads_label.setText(str(psutil.cpu_count(logical=True)))
            
            # Memory info
            memory = psutil.virtual_memory()
            self.memory_total_label.setText(f"{memory.total / (1024**3):.1f} GB")
            self.memory_available_label.setText(f"{memory.available / (1024**3):.1f} GB")
            self.memory_used_label.setText(f"{memory.used / (1024**3):.1f} GB")
            
            # Storage info - the volume the app writes to, with the media type the device
            # store reported for the disk behind it. The device store costs about two
            # seconds, so it is read once in a worker (refresh_storage_info) and this
            # timer only paints what came back.
            self.paint_storage_info()

        except Exception as e:
            print(f"Error updating system info: {e}")
            
    def clear_memory_cache(self):
        """Clear memory cache and garbage collect."""
        # Measure before
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024
        
        # 1. Force Garbage Collection
        gc.collect()
        
        # 2. Clear Performance Analyzer History
        self.performance_analyzer.clear_all_data()
        
        # 3. Clear internal caches if possible (placeholder for future app-wide cache manager)
        # For now, we just rely on GC and clearing history
        
        # Measure after
        mem_after = process.memory_info().rss / 1024 / 1024
        freed = mem_before - mem_after
        
        QMessageBox.information(
            self,
            "Memory Cleared",
            f"Cache cleared and garbage collection run.\n\n"
            f"Memory Freed: {freed:.2f} MB\n"
            f"Current Usage: {mem_after:.2f} MB"
        )
        
        self.analyze_memory_usage()
    def force_garbage_collection(self):
        """Force garbage collection."""
        import gc
        gc.collect()
        self.analyze_memory_usage()
        
    def analyze_memory_usage(self):
        """Analyze current memory usage with real data."""
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # Update memory processes table with real process data
        self.memory_processes_table.setRowCount(0)
        
        # Helper to add row
        def add_row(component, usage_mb, peak_mb, notes):
            row = self.memory_processes_table.rowCount()
            self.memory_processes_table.insertRow(row)
            self.memory_processes_table.setItem(row, 0, QTableWidgetItem(component))
            self.memory_processes_table.setItem(row, 1, QTableWidgetItem(f"{usage_mb:.1f} MB"))
            self.memory_processes_table.setItem(row, 2, QTableWidgetItem(f"{peak_mb:.1f} MB"))
            self.memory_processes_table.setItem(row, 3, QTableWidgetItem(notes))
            
        # 1. RSS (Resident Set Size) - Physical Memory
        rss_mb = mem_info.rss / 1024 / 1024
        add_row("Application (RSS)", rss_mb, rss_mb, "Physical Memory")
        
        # 2. VMS (Virtual Memory Size)
        vms_mb = mem_info.vms / 1024 / 1024
        add_row("Virtual Memory (VMS)", vms_mb, vms_mb, "Virtual Address Space")
        
        # 3. Python Objects (GC)
        gc_objects = len(gc.get_objects())
        add_row("Python Objects", 0, 0, f"{gc_objects:,} objects tracked by GC")
        
        # 4. Performance History
        history_len = len(self.performance_analyzer.monitor.metrics_history)
        add_row("Performance History", 0, 0, f"{history_len} data points")
        
        # 5. System Total
        sys_mem = psutil.virtual_memory()
        add_row("System Total Used", sys_mem.used / 1024 / 1024, 0, f"{sys_mem.percent}% Load")
