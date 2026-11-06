"""
The Diagnostics pane: system checks, health indicators, and the recorded error list.
"""

import datetime
import json
import logging
import os
import weakref
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
                             QPushButton, QComboBox, QLabel, QGroupBox, QFormLayout, 
                             QSpinBox, QDoubleSpinBox, QSlider, QTabWidget, QCheckBox,
                             QFrame, QGridLayout, QScrollArea, QTextEdit, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
                             QListWidget, QTreeWidget, QTreeWidgetItem, QPlainTextEdit,
                             QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QThreadPool
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter

# Import diagnostic engine
from ..features.diagnostic_engine import (
    DiagnosticEngine, SystemInfo, DependencyChecker, 
    HealthChecker, OpenGLInfo
)
from ..features.performance_analyzer import BenchmarkRunner, benchmark_engine
from ..utils.frame_clock import shared_clock
from ..utils.worker import Worker
from .icon_provider import get_icon

class LogSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for log messages."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_formats()
        
    def setup_formats(self):
        """Setup text formats for different log levels."""
        self.formats = {}
        
        # ERROR format
        error_format = QTextCharFormat()
        error_format.setForeground(QColor(220, 50, 47))  # Red
        error_format.setFontWeight(QFont.Weight.Bold)
        self.formats['ERROR'] = error_format
        
        # WARNING format
        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor(203, 75, 22))  # Orange
        self.formats['WARNING'] = warning_format
        
        # INFO format
        info_format = QTextCharFormat()
        info_format.setForeground(QColor(38, 139, 210))  # Blue
        self.formats['INFO'] = info_format
        
        # DEBUG format
        debug_format = QTextCharFormat()
        debug_format.setForeground(QColor(133, 153, 0))  # Green
        self.formats['DEBUG'] = debug_format
        
        # Timestamp format
        timestamp_format = QTextCharFormat()
        timestamp_format.setForeground(QColor(88, 110, 117))  # Gray
        self.formats['TIMESTAMP'] = timestamp_format
        
    def highlightBlock(self, text):
        """Highlight a block of text."""
        # Highlight timestamps
        if text.startswith('['):
            end_bracket = text.find(']')
            if end_bracket > 0:
                self.setFormat(0, end_bracket + 1, self.formats['TIMESTAMP'])
        
        # Highlight log levels
        for level in ['ERROR', 'WARNING', 'INFO', 'DEBUG']:
            if level in text:
                start = text.find(level)
                if start >= 0:
                    self.setFormat(start, len(level), self.formats[level])
                    break

class PaneLogHandler(logging.Handler):
    """Turns the app's own log records into rows in the Diagnostics log table.

    The table used to be filled by five lines written at startup - an OpenGL context
    that may not exist, a model nobody loaded, a GPU percentage nothing read - because
    no part of the app ever called its `add_log_entry`. This is the source that was
    missing. `emit` only re-emits a Qt signal, so a record logged on a worker thread
    reaches the table through the event loop rather than from that thread.

    It holds the pane weakly and looks the signal up when a record arrives. A bound
    signal kept its own reference to the receiver's Qt object, so a handler left on the
    root logger after its pane closed was a live reference into memory Qt had already
    handed to the next widget - which is how an exit-time log record segfaulted the
    process during testing.
    """

    def __init__(self, pane) -> None:
        super().__init__()
        self._pane = weakref.ref(pane)

    def emit(self, record) -> None:
        pane = self._pane()
        if pane is None:
            return
        try:
            pane.log_record.emit(record.levelname, record.name, record.getMessage())
        except (RuntimeError, TypeError):
            # The pane's Qt object is gone: a rebuilt window, or a record arriving after
            # teardown. A log line is never a reason to stop the app.
            pass

    def pane_alive(self) -> bool:
        """Whether the pane this handler belongs to is still there to receive a record."""
        return self._pane() is not None


def _detach_when_destroyed(root, handler):
    """The closure that takes a pane's log handler off the root logger when it dies.

    A bound method connected to the pane's own `destroyed` is never called: PyQt drops a
    slot whose receiver is the object being torn down, which is exactly the object whose
    death is being noticed. A plain closure over the handler does fire, and without it
    the root logger keeps a dead handler for every pane the app ever built.
    """

    def detach(_deleted=None):
        root.removeHandler(handler)

    return detach


class DiagnosticsTab(QWidget):
    """Diagnostics and logging interface."""
    
    log_message = pyqtSignal(str, str)  # level, message
    log_record = pyqtSignal(str, str, str)  # level, component, message
    diagnostic_completed = pyqtSignal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_entries = []
        self.max_log_entries = 10000
        self._benchmark_workers = []
        self._measure_workers = []
        self._report_paths = {}
        self._log_handler = None
        
        # Initialize diagnostic engine
        self.diagnostic_engine = DiagnosticEngine()
        
        self.init_ui()
        self.setup_connections()
        self.setup_logging()
        
    def init_ui(self):
        """Initialize the diagnostics interface."""
        main_layout = QVBoxLayout(self)
        
        # Create tab widget for different diagnostic areas
        self.diagnostics_tabs = QTabWidget()
        
        # Live Logs tab
        logs_tab = self.create_logs_tab()
        self.diagnostics_tabs.addTab(logs_tab, "Live Logs")
        
        # System Diagnostics tab
        system_tab = self.create_system_diagnostics_tab()
        self.diagnostics_tabs.addTab(system_tab, "System Check")
        
        # Debug Tools tab
        debug_tab = self.create_debug_tab()
        self.diagnostics_tabs.addTab(debug_tab, "Debug Tools")
        
        # Error Reports tab
        reports_tab = self.create_reports_tab()
        self.diagnostics_tabs.addTab(reports_tab, "Reports")
        
        # Log Analysis tab
        analysis_tab = self.create_analysis_tab()
        self.diagnostics_tabs.addTab(analysis_tab, "Analysis")
        
        main_layout.addWidget(self.diagnostics_tabs)
        
    def create_logs_tab(self):
        """Create live logs interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Log controls
        controls_group = QGroupBox("Log Controls")
        controls_layout = QHBoxLayout()
        
        # Log level filter
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        
        # Component filter
        self.component_filter_combo = QComboBox()
        self.component_filter_combo.addItems([
            "All Components", "3D Viewer", "Model Loader", "Renderer", 
            "File System", "GPU", "Memory", "UI", "Processing"
        ])
        
        # Search filter
        self.log_search_edit = QLineEdit()
        self.log_search_edit.setPlaceholderText("Search logs...")
        
        # Control buttons
        self.clear_logs_btn = QPushButton("Clear")
        self.clear_logs_btn.setIcon(get_icon("clean"))
        self.save_logs_btn = QPushButton("Save")
        self.save_logs_btn.setIcon(get_icon("backup"))
        self.pause_logs_btn = QPushButton("Pause")
        self.pause_logs_btn.setIcon(get_icon("clock"))
        self.auto_scroll_cb = QCheckBox("Auto-scroll")
        self.auto_scroll_cb.setChecked(True)
        
        controls_layout.addWidget(QLabel("Level:"))
        controls_layout.addWidget(self.log_level_combo)
        controls_layout.addWidget(QLabel("Component:"))
        controls_layout.addWidget(self.component_filter_combo)
        controls_layout.addWidget(self.log_search_edit)
        controls_layout.addStretch()
        controls_layout.addWidget(self.auto_scroll_cb)
        controls_layout.addWidget(self.pause_logs_btn)
        controls_layout.addWidget(self.clear_logs_btn)
        controls_layout.addWidget(self.save_logs_btn)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Log display
        self.log_display = QPlainTextEdit()
        self.log_display.setFont(QFont("Consolas", 10))
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumBlockCount(self.max_log_entries)
        
        # Apply syntax highlighting
        self.log_highlighter = LogSyntaxHighlighter(self.log_display.document())
        
        layout.addWidget(self.log_display)
        
        # Log statistics
        stats_layout = QHBoxLayout()
        
        self.log_count_label = QLabel("Total: 0")
        self.error_count_label = QLabel("Errors: 0")
        self.warning_count_label = QLabel("Warnings: 0")
        self.memory_usage_label = QLabel("Memory: 0 MB")
        
        stats_layout.addWidget(self.log_count_label)
        stats_layout.addWidget(self.error_count_label)
        stats_layout.addWidget(self.warning_count_label)
        stats_layout.addWidget(self.memory_usage_label)
        stats_layout.addStretch()
        
        layout.addLayout(stats_layout)
        
        return widget
        
    def create_system_diagnostics_tab(self):
        """Create system diagnostics interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Diagnostic controls
        controls_group = QGroupBox("System Diagnostics")
        controls_layout = QHBoxLayout()
        
        self.quick_check_btn = QPushButton("Quick Check")
        self.quick_check_btn.setIcon(get_icon("performance"))
        self.full_diagnostic_btn = QPushButton("Full Diagnostic")
        self.full_diagnostic_btn.setIcon(get_icon("diagnostics"))
        self.full_diagnostic_btn.setProperty("primary", "true")
        self.hardware_test_btn = QPushButton("Hardware Test")
        self.hardware_test_btn.setIcon(get_icon("scan"))
        self.dependency_check_btn = QPushButton("Dependency Check")
        self.dependency_check_btn.setIcon(get_icon("settings"))
        self.performance_test_btn = QPushButton("Performance Test")
        self.performance_test_btn.setIcon(get_icon("sparkles"))
        
        controls_layout.addWidget(self.quick_check_btn)
        controls_layout.addWidget(self.full_diagnostic_btn)
        controls_layout.addWidget(self.hardware_test_btn)
        controls_layout.addWidget(self.dependency_check_btn)
        controls_layout.addWidget(self.performance_test_btn)
        controls_layout.addStretch()
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Diagnostic results
        results_layout = QHBoxLayout()
        
        # System health overview
        health_group = QGroupBox("System Health")
        health_layout = QVBoxLayout()
        
        self.health_status = QLabel("Status: Ready for diagnostics")
        self.health_status.setStyleSheet("font-weight: bold; color: #2ecc71;")
        
        # Health indicators
        health_grid = QGridLayout()
        
        self.cpu_health = self.create_health_indicator("CPU", "Good")
        self.memory_health = self.create_health_indicator("Memory", "Good")
        self.storage_health = self.create_health_indicator("Storage", "Good")
        self.gpu_health = self.create_health_indicator("GPU", "Good")
        
        health_grid.addWidget(self.cpu_health, 0, 0)
        health_grid.addWidget(self.memory_health, 0, 1)
        health_grid.addWidget(self.storage_health, 1, 0)
        health_grid.addWidget(self.gpu_health, 1, 1)
        
        health_layout.addWidget(self.health_status)
        health_layout.addLayout(health_grid)
        
        health_group.setLayout(health_layout)
        results_layout.addWidget(health_group)
        
        # Diagnostic details
        details_group = QGroupBox("Diagnostic Details")
        details_layout = QVBoxLayout()
        
        self.diagnostic_results = QTextEdit()
        self.diagnostic_results.setReadOnly(True)
        self.diagnostic_results.setPlainText("Run diagnostics to see detailed results...")
        
        details_layout.addWidget(self.diagnostic_results)
        details_group.setLayout(details_layout)
        results_layout.addWidget(details_group)
        
        layout.addLayout(results_layout)
        
        # Issue resolution
        resolution_group = QGroupBox("Issue Resolution")
        resolution_layout = QVBoxLayout()
        
        self.issues_table = QTableWidget()
        self.issues_table.setColumnCount(4)
        self.issues_table.setHorizontalHeaderLabels(["Issue", "Severity", "Impact", "Action"])
        self.issues_table.setMaximumHeight(150)
        
        resolution_buttons = QHBoxLayout()
        self.auto_fix_btn = QPushButton("Auto Fix Issues")
        self.auto_fix_btn.setIcon(get_icon("clean"))
        self.auto_fix_btn.setProperty("primary", "true")
        self.manual_fix_btn = QPushButton("Manual Fix Guide")
        self.manual_fix_btn.setIcon(get_icon("help"))
        self.ignore_issue_btn = QPushButton("Ignore Selected")
        self.ignore_issue_btn.setIcon(get_icon("delete"))
        
        resolution_buttons.addWidget(self.auto_fix_btn)
        resolution_buttons.addWidget(self.manual_fix_btn)
        resolution_buttons.addWidget(self.ignore_issue_btn)
        resolution_buttons.addStretch()
        
        resolution_layout.addWidget(self.issues_table)
        resolution_layout.addLayout(resolution_buttons)
        
        resolution_group.setLayout(resolution_layout)
        layout.addWidget(resolution_group)
        
        return widget
        
    def create_debug_tab(self):
        """Create debug tools interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Debug controls
        controls_layout = QHBoxLayout()
        
        # Debug level
        debug_group = QGroupBox("Debug Settings")
        debug_form = QFormLayout()
        
        self.debug_level_combo = QComboBox()
        self.debug_level_combo.addItems(["Off", "Basic", "Verbose", "Trace"])
        
        self.debug_modules_edit = QLineEdit()
        self.debug_modules_edit.setPlaceholderText("module1,module2,...")
        
        self.breakpoint_enabled_cb = QCheckBox("Enable Breakpoints")
        self.memory_tracking_cb = QCheckBox("Memory Tracking")
        self.performance_profiling_cb = QCheckBox("Performance Profiling")
        
        debug_form.addRow("Debug Level:", self.debug_level_combo)
        debug_form.addRow("Debug Modules:", self.debug_modules_edit)
        debug_form.addRow(self.breakpoint_enabled_cb)
        debug_form.addRow(self.memory_tracking_cb)
        debug_form.addRow(self.performance_profiling_cb)
        
        debug_group.setLayout(debug_form)
        controls_layout.addWidget(debug_group)
        
        # Debug actions
        actions_group = QGroupBox("Debug Actions")
        actions_layout = QVBoxLayout()
        
        self.dump_state_btn = QPushButton("Dump Application State")
        self.dump_state_btn.setIcon(get_icon("camera"))
        self.trace_calls_btn = QPushButton("Trace Function Calls")
        self.trace_calls_btn.setIcon(get_icon("search"))
        self.memory_snapshot_btn = QPushButton("Memory Snapshot")
        self.memory_snapshot_btn.setIcon(get_icon("diagnostics"))
        self.force_crash_btn = QPushButton("Force Test Crash")
        self.force_crash_btn.setIcon(get_icon("warning"))
        self.generate_report_btn = QPushButton("Generate Debug Report")
        self.generate_report_btn.setIcon(get_icon("export"))
        
        actions_layout.addWidget(self.dump_state_btn)
        actions_layout.addWidget(self.trace_calls_btn)
        actions_layout.addWidget(self.memory_snapshot_btn)
        actions_layout.addWidget(self.force_crash_btn)
        actions_layout.addWidget(self.generate_report_btn)
        
        actions_group.setLayout(actions_layout)
        controls_layout.addWidget(actions_group)
        
        layout.addLayout(controls_layout)
        
        # Debug output
        output_group = QGroupBox("Debug Output")
        output_layout = QVBoxLayout()
        
        self.debug_output = QPlainTextEdit()
        self.debug_output.setFont(QFont("Consolas", 9))
        self.debug_output.setReadOnly(True)
        self.debug_output.setPlainText("Debug output will appear here...")
        
        output_layout.addWidget(self.debug_output)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        # Variable inspector
        inspector_group = QGroupBox("Variable Inspector")
        inspector_layout = QVBoxLayout()
        
        self.variable_tree = QTreeWidget()
        self.variable_tree.setHeaderLabels(["Variable", "Type", "Value"])
        self.variable_tree.setMaximumHeight(200)
        
        inspector_layout.addWidget(self.variable_tree)
        inspector_group.setLayout(inspector_layout)
        layout.addWidget(inspector_group)
        
        return widget
        
    def create_reports_tab(self):
        """Create error reports interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Report controls
        controls_group = QGroupBox("Error Reports")
        controls_layout = QHBoxLayout()
        
        self.generate_report_combo = QComboBox()
        self.generate_report_combo.addItems([
            "Crash Report", "Error Summary", "Performance Report", 
            "Memory Report", "System Report", "Custom Report"
        ])
        
        self.generate_btn = QPushButton("Generate Report")
        self.generate_btn.setIcon(get_icon("export"))
        self.generate_btn.setProperty("primary", "true")
        self.auto_reports_cb = QCheckBox("Auto-generate on errors")
        self.send_reports_cb = QCheckBox("Send reports for analysis")
        
        controls_layout.addWidget(QLabel("Report Type:"))
        controls_layout.addWidget(self.generate_report_combo)
        controls_layout.addWidget(self.generate_btn)
        controls_layout.addStretch()
        controls_layout.addWidget(self.auto_reports_cb)
        controls_layout.addWidget(self.send_reports_cb)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Reports list
        reports_layout = QHBoxLayout()
        
        # Report list
        list_group = QGroupBox("Generated Reports")
        list_layout = QVBoxLayout()
        
        self.reports_list = QListWidget()
        # The list used to open holding four reports dated 2024-08-29 that no code ever
        # wrote, and selecting one painted a crash that never happened. It now starts
        # empty and fills with the files this app actually exports, each remembering its
        # own path.
        self.reports_list.itemSelectionChanged.connect(self.preview_report)
        
        list_buttons = QHBoxLayout()
        self.view_report_btn = QPushButton("View")
        self.view_report_btn.setIcon(get_icon("models"))
        self.export_report_btn = QPushButton("Export")
        self.export_report_btn.setIcon(get_icon("export"))
        self.delete_report_btn = QPushButton("Delete")
        self.delete_report_btn.setIcon(get_icon("delete"))
        
        list_buttons.addWidget(self.view_report_btn)
        list_buttons.addWidget(self.export_report_btn)
        list_buttons.addWidget(self.delete_report_btn)
        list_buttons.addStretch()
        
        list_layout.addWidget(self.reports_list)
        list_layout.addLayout(list_buttons)
        
        list_group.setLayout(list_layout)
        reports_layout.addWidget(list_group)
        
        # Report preview
        preview_group = QGroupBox("Report Preview")
        preview_layout = QVBoxLayout()
        
        self.report_preview = QTextEdit()
        self.report_preview.setReadOnly(True)
        self.report_preview.setPlainText("Select a report to view its contents...")
        
        preview_layout.addWidget(self.report_preview)
        preview_group.setLayout(preview_layout)
        reports_layout.addWidget(preview_group)
        
        layout.addLayout(reports_layout)
        
        return widget
        
    def create_analysis_tab(self):
        """Create log analysis interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Analysis controls
        controls_group = QGroupBox("Log Analysis")
        controls_layout = QHBoxLayout()
        
        self.analysis_period_combo = QComboBox()
        self.analysis_period_combo.addItems([
            "Last Hour", "Last 6 Hours", "Last 24 Hours", 
            "Last Week", "Last Month", "Custom Range"
        ])
        
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setIcon(get_icon("chart"))
        self.analyze_btn.setProperty("primary", "true")
        self.export_analysis_btn = QPushButton("Export Analysis")
        self.export_analysis_btn.setIcon(get_icon("export"))
        
        controls_layout.addWidget(QLabel("Time Period:"))
        controls_layout.addWidget(self.analysis_period_combo)
        controls_layout.addWidget(self.analyze_btn)
        controls_layout.addWidget(self.export_analysis_btn)
        controls_layout.addStretch()
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Analysis results
        results_layout = QHBoxLayout()
        
        # Statistics
        stats_group = QGroupBox("Log Statistics")
        stats_layout = QFormLayout()
        
        self.total_logs_label = QLabel("0")
        self.error_rate_label = QLabel("0%")
        self.avg_response_label = QLabel("0ms")
        self.peak_memory_label = QLabel("0MB")
        self.crash_count_label = QLabel("0")
        
        stats_layout.addRow("Total Log Entries:", self.total_logs_label)
        stats_layout.addRow("Error Rate:", self.error_rate_label)
        stats_layout.addRow("Avg Response Time:", self.avg_response_label)
        stats_layout.addRow("Peak Memory Usage:", self.peak_memory_label)
        stats_layout.addRow("Application Crashes:", self.crash_count_label)
        
        stats_group.setLayout(stats_layout)
        results_layout.addWidget(stats_group)
        
        # Trends
        trends_group = QGroupBox("Trends & Patterns")
        trends_layout = QVBoxLayout()
        
        self.trends_display = QTextEdit()
        self.trends_display.setReadOnly(True)
        self.trends_display.setMaximumHeight(200)
        self.trends_display.setPlainText("Run analysis to see trends and patterns...")
        
        trends_layout.addWidget(self.trends_display)
        trends_group.setLayout(trends_layout)
        results_layout.addWidget(trends_group)
        
        layout.addLayout(results_layout)
        
        # Frequent issues
        issues_group = QGroupBox("Frequent Issues")
        issues_layout = QVBoxLayout()
        
        self.frequent_issues_table = QTableWidget()
        self.frequent_issues_table.setColumnCount(4)
        # The fourth column said "Suggested Fix" and was filled by three lines written
        # into this file - "Implement memory pooling", "Increase timeout values", "Add
        # input validation" - for problems the app had never reported. What a repeated
        # record does carry is the module that logged it, so the column now says that.
        self.frequent_issues_table.setHorizontalHeaderLabels([
            "Issue", "Frequency", "Last Seen", "Logged By"
        ])
        
        issues_layout.addWidget(self.frequent_issues_table)
        issues_group.setLayout(issues_layout)
        layout.addWidget(issues_group)
        
        return widget
        
    def create_health_indicator(self, name, status):
        """Create a health status indicator."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-weight: bold;")
        
        status_label = QLabel(status)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Color based on status
        if status == "Good":
            status_label.setStyleSheet("color: #2ecc71; font-weight: bold;")
        elif status == "Warning":
            status_label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
        layout.addWidget(name_label)
        layout.addWidget(status_label)
        
        return frame
        
    def setup_connections(self):
        """Setup signal connections."""
        # Log controls
        self.clear_logs_btn.clicked.connect(self.clear_logs)
        self.save_logs_btn.clicked.connect(self.save_logs)
        self.pause_logs_btn.clicked.connect(self.toggle_log_pause)
        self.log_level_combo.currentTextChanged.connect(self.filter_logs)
        self.log_search_edit.textChanged.connect(self.search_logs)
        
        # System diagnostics - Connect to engine methods
        self.quick_check_btn.clicked.connect(self.run_quick_check)
        self.full_diagnostic_btn.clicked.connect(self.run_full_diagnostic)
        self.hardware_test_btn.clicked.connect(self.run_hardware_test)
        self.dependency_check_btn.clicked.connect(self.run_dependency_check)
        self.performance_test_btn.clicked.connect(self.run_performance_test)
        
        # Debug tools
        self.dump_state_btn.clicked.connect(self.dump_application_state)
        self.memory_snapshot_btn.clicked.connect(self.take_memory_snapshot)
        self.generate_report_btn.clicked.connect(self.generate_debug_report)
        
        # Reports
        self.generate_btn.clicked.connect(self.generate_error_report)
        self.reports_list.itemSelectionChanged.connect(self.preview_report)
        
        # Analysis
        self.analyze_btn.clicked.connect(self.analyze_logs)
        
    def setup_logging(self):
        """Attach the app's real log records to this table, which starts it empty.

        The five lines this used to write described a session that had not happened:
        "OpenGL context initialized", "Loading model: test.obj", "GPU memory usage at
        85%". They also set the counts below the table, so the error rate was a
        percentage of a made-up sample.

        The guard is per pane, not per process. Checking the root logger for *any*
        handler of this kind meant that a second Diagnostics pane - the one a test
        builds, or the first one a rebuilt window replaces - attached nothing and its
        table stayed empty for the rest of the session.
        """
        self.log_record.connect(self.add_log_entry)
        if self._log_handler is not None:
            return
        self._log_handler = PaneLogHandler(self)
        logging.getLogger().addHandler(self._log_handler)
        # The handler outlives nothing: as soon as this pane's Qt object is destroyed it
        # is taken off the root logger, because a record arriving afterwards would be
        # delivered to a widget that no longer exists.
        self.destroyed.connect(_detach_when_destroyed(logging.getLogger(), self._log_handler))
        
    def add_log_entry(self, level, component, message):
        """Add a new log entry."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_text = f"[{timestamp}] {level}: [{component}] {message}"
        
        self.log_entries.append({
            'timestamp': timestamp,
            'level': level,
            'component': component,
            'message': message,
            'full_text': log_text
        })
        
        # The table's own limit, now enforced on the list too: the display capped its
        # blocks at max_log_entries while the list grew without one, so a long session
        # held every record twice and the analysis below counted lines no longer visible.
        if len(self.log_entries) > self.max_log_entries:
            del self.log_entries[:-self.max_log_entries]

        # Update display if not paused
        if not hasattr(self, 'log_paused') or not self.log_paused:
            self.log_display.appendPlainText(log_text)
            
            if self.auto_scroll_cb.isChecked():
                self.log_display.ensureCursorVisible()
        
        # Update statistics
        self.update_log_statistics()
        
        
    def _entry_matches_filters(self, level, component, message):
        """Check if a log entry matches current filters."""
        # Level filter
        target_level = self.log_level_combo.currentText()
        if target_level != "ALL" and level != target_level:
            return False
            
        # Component filter
        target_component = self.component_filter_combo.currentText()
        if target_component != "All Components" and component != target_component:
            return False
            
        # Search filter
        search_text = self.log_search_edit.text().lower()
        if search_text:
            # Search in message, component, and level
            if (search_text not in message.lower() and 
                search_text not in component.lower() and 
                search_text not in level.lower()):
                return False
                
        return True
        
    def clear_logs(self):
        """Clear all log entries."""
        self.log_entries.clear()
        self.log_display.clear()
        self.update_log_statistics()
        
    def save_logs(self):
        """Save logs to file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Logs", 
            f"renderfox_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            "Log Files (*.log);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    for entry in self.log_entries:
                        f.write(entry['full_text'] + '\n')
                QMessageBox.information(self, "Success", f"Logs saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save logs: {str(e)}")
                
    def toggle_log_pause(self):
        """Toggle log pause state."""
        self.log_paused = getattr(self, 'log_paused', False)
        self.log_paused = not self.log_paused
        
        if self.log_paused:
            self.pause_logs_btn.setText("Resume")
            self.pause_logs_btn.setIcon(get_icon("play"))
        else:
            self.pause_logs_btn.setText("Pause")
            self.pause_logs_btn.setIcon(get_icon("pause"))
            
    def filter_logs(self):
        """Filter logs based on level and component."""
        self._refresh_log_display()
        
    def search_logs(self):
        """Search logs for specific text."""
        self._refresh_log_display()

    def _refresh_log_display(self):
        """Rebuild log display based on current filters."""
        self.log_display.clear()
        
        # Filter entries
        visible_entries = []
        for entry in self.log_entries:
            if self._entry_matches_filters(entry['level'], entry['component'], entry['message']):
                visible_entries.append(entry['full_text'])
        
        # Update display (batch update for performance)
        if visible_entries:
            self.log_display.setPlainText('\n'.join(visible_entries))
            if self.auto_scroll_cb.isChecked():
                self.log_display.moveCursor(self.log_display.textCursor().MoveOperation.End)
        
    def update_log_statistics(self):
        """Update log statistics display."""
        total = len(self.log_entries)
        errors = len([e for e in self.log_entries if e['level'] == 'ERROR'])
        warnings = len([e for e in self.log_entries if e['level'] == 'WARNING'])
        
        self.log_count_label.setText(f"Total: {total}")
        self.error_count_label.setText(f"Errors: {errors}")
        self.warning_count_label.setText(f"Warnings: {warnings}")
        
    def run_quick_check(self):
        """Run quick system check using diagnostic engine."""
        self.health_status.setText("Status: Running quick check...")
        self.diagnostic_results.setPlainText("Analyzing system...")
        
        try:
            # Run actual diagnostics
            report = self.diagnostic_engine.get_full_system_report()
            
            # Format results
            cpu = report['cpu']
            memory = report['memory']
            health = report['health_checks']

            # The volume the app writes to and the verdict on it come from one check, so the
            # word at the start of the line and the figures after it are the same reading of
            # the same drive. A check that produced nothing prints that, rather than `[OK]`:
            # the old line said OK to anything that was not exactly "healthy", so a drive
            # reported as critical was shown with the same word as a warning.
            disk = health.get('disk') or {'status': None, 'message': 'no storage check ran'}
            words = {'healthy': '[OK]', 'warning': '[Warning]', 'critical': '[Critical]'}

            def mark(name):
                return words.get(health.get(name, {}).get('status'), '[Not checked]')

            # The same five lines, counted: a check that did not answer is not a pass, and
            # "all the checks that answered are fine" is not the sentence "all systems
            # operational" - which is what the old line said when a check was missing.
            checked = ('cpu', 'memory', 'disk', 'gpu', 'dependencies')
            overall = ('All systems operational'
                       if all(health.get(name, {}).get('status') == 'healthy'
                              for name in checked) else 'Issues detected')

            gpu_rows = report['gpu']
            gpu_name = (gpu_rows[0]['name'] if gpu_rows
                        else 'nothing identified one ('
                             + (report['gpu_reasons'][0] if report['gpu_reasons']
                                else 'no answer') + ')')

            results = f"""Quick System Check Results:

{mark('cpu')} CPU: {cpu['physical_cores']} cores, {cpu['current_frequency']} - Usage: {cpu['usage_percent']}%
{mark('memory')} Memory: {memory['used']} used / {memory['total']} total ({memory['percent']}%)
{mark('disk')} Storage: {disk['message']}
{mark('gpu')} GPU: {gpu_name}
{mark('dependencies')} Dependencies: {health.get('dependencies', {}).get('message', 'no dependency check ran')}

Overall Status: {overall}"""
            
            self.diagnostic_results.setPlainText(results)
            self.health_status.setText("Status: Quick check completed")
            
            # Update health indicators
            self.update_health_indicators(health)
            
        except Exception as e:
            self.diagnostic_results.setPlainText(f"Error running diagnostics: {str(e)}")
            self.health_status.setText("Status: Check failed")
    
    def update_health_indicators(self, health_checks):
        """Colour the four badges from the four checks they stand for.

        The CPU badge used to be painted from the memory check, so a machine short on memory
        showed a processor problem it never had, and a check that did not run at all was
        counted as a pass because its status defaulted to good. A badge with no reading
        behind it now says so.
        """
        verdicts = {'healthy': 'Good', 'warning': 'Warning', 'critical': 'Critical'}
        badges = ((self.cpu_health, 'cpu'), (self.memory_health, 'memory'),
                  (self.storage_health, 'disk'), (self.gpu_health, 'gpu'))
        for indicator, name in badges:
            status = health_checks.get(name, {}).get('status')
            self.update_health_indicator_status(
                indicator, verdicts.get(status, 'Not checked'))

    def update_health_indicator_status(self, indicator_frame, status):
        """Update a single health indicator's status."""
        # Get the status label (second child widget)
        layout = indicator_frame.layout()
        if layout and layout.count() >= 2:
            status_label = layout.itemAt(1).widget()
            if status_label:
                status_label.setText(status)

                # Update color based on status
                if status == "Good":
                    status_label.setStyleSheet("color: #2ecc71; font-weight: bold;")
                elif status == "Warning":
                    status_label.setStyleSheet("color: #f39c12; font-weight: bold;")
                elif status == "Not checked":
                    status_label.setStyleSheet("color: #7f8c8d; font-weight: bold;")
                else:
                    status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
    def run_full_diagnostic(self):
        """Run comprehensive system diagnostic using engine."""
        self.health_status.setText("Status: Running full diagnostic...")
        self.diagnostic_results.setPlainText("Running comprehensive analysis...")
        
        try:
            # Get full system report
            report = self.diagnostic_engine.get_full_system_report()
            
            # Build detailed results
            results = "=== FULL SYSTEM DIAGNOSTIC ===\n\n"
            
            # OS Information
            results += "=== OPERATING SYSTEM ===\n"
            os_info = report['os']
            results += f"OS: {os_info['os']} {os_info['os_release']}\n"
            results += f"Architecture: {os_info['architecture']}\n"
            results += f"Processor: {os_info['processor']}\n"
            results += f"Python: {os_info['python_version']}\n\n"
            
            # CPU Information
            results += "=== CPU ===\n"
            cpu = report['cpu']
            results += f"Cores: {cpu['physical_cores']} physical, {cpu['logical_cores']} logical\n"
            results += f"Frequency: {cpu['current_frequency']}\n"
            results += f"Usage: {cpu['usage_percent']}%\n\n"
            
            # Memory Information
            results += "=== MEMORY ===\n"
            mem = report['memory']
            results += f"Total: {mem['total']}\n"
            results += f"Available: {mem['available']}\n"
            results += f"Used: {mem['used']} ({mem['percent']}%)\n"
            results += f"Swap: {mem['swap_used']} / {mem['swap_total']}\n\n"

            # Storage - each volume, and the disk behind it when Windows can say
            results += "=== STORAGE ===\n"
            storage = report['storage']
            if not storage['volumes']:
                results += "No mounted volume answered.\n"
            for volume in storage['volumes']:
                results += (f"{volume['mountpoint']} [{volume['filesystem']}]: "
                            f"{volume['used_bytes'] / (1024 ** 3):.1f} GB used of "
                            f"{volume['total_bytes'] / (1024 ** 3):.1f} GB "
                            f"({volume['used_percent']}%) - "
                            f"{volume['media_type'] or 'disk kind unknown'}"
                            f"{', ' + volume['disk'] if volume['disk'] else ''}\n")
            for reason in storage['reasons']:
                results += f"Note: {reason}\n"
            results += (f"\nWhere the app writes: "
                        f"{report['health_checks']['disk']['message']}\n\n")
            
            # GPU Information - the same block of words the Performance pane prints
            results += "=== GPU ===\n"
            results += report.get('gpu_text', 'No GPU report in this file') + "\n\n"
            
            # OpenGL Information
            results += "=== OPENGL ===\n"
            opengl = report['opengl']
            if 'error' in opengl:
                results += f"Error: {opengl['error']}\n"
            else:
                results += f"Vendor: {opengl.get('vendor', 'Unknown')}\n"
                results += f"Renderer: {opengl.get('renderer', 'Unknown')}\n"
                results += f"Version: {opengl.get('version', 'Unknown')}\n"
            
            self.diagnostic_results.setPlainText(results)
            self.health_status.setText("Status: Full diagnostic completed")
            
            # Update health indicators
            self.update_health_indicators(report['health_checks'])
            
            # Get recommendations and show as issues
            recommendations = self.diagnostic_engine.get_recommendations(
                report['health_checks'])
            self.populate_issues_table(recommendations)
            
        except Exception as e:
            self.diagnostic_results.setPlainText(f"Error running full diagnostic: {str(e)}")
            self.health_status.setText("Status: Diagnostic failed")
    
    def populate_issues_table(self, recommendations):
        """Populate issues table with recommendations."""
        self.issues_table.setRowCount(len(recommendations))
        
        for row, rec in enumerate(recommendations):
            # Parse recommendation text
            if rec.startswith("Warning:") or "warning" in rec.lower():
                severity = "Warning"
                issue = rec.replace("Warning:", "").strip()
            elif rec.startswith("Good:") or "optimal" in rec.lower():
                severity = "Good"
                issue = rec.replace("Good:", "").strip()
            else:
                severity = "Info"
                issue = rec
            
            self.issues_table.setItem(row, 0, QTableWidgetItem(issue))
            self.issues_table.setItem(row, 1, QTableWidgetItem(severity))
            self.issues_table.setItem(row, 2, QTableWidgetItem("System"))
            self.issues_table.setItem(row, 3, QTableWidgetItem("Review system resources"))
        
    def run_hardware_test(self):
        """Time the engine's CPU and memory work off the interface thread.

        The two calls this replaces summed `math.sqrt` over a million integers and then
        graded the elapsed time Excellent/Good/Average on thresholds that the loop beat
        on every machine it has ever run on, so the line was a constant dressed as a
        verdict - and it did the summing on the interface thread, which is why the pane
        stopped answering while it thought it was measuring.
        """
        self.health_status.setText("Status: Running hardware test...")
        self.diagnostic_results.setPlainText("Benchmarking hardware...")
        self.run_engine_kinds(('cpu', 'memory'), self.show_hardware_test)

    def run_engine_kinds(self, kinds, receiver, readings=None):
        """One worker over the named kinds of work, with the failure channel connected.

        `readings`, when given, runs on the same worker thread: the machine figures and
        the timed work then come from one look at the machine rather than two, and the
        interface thread is asked for neither.
        """
        engine = benchmark_engine()

        def worker_func(progress_callback=None):
            results = [engine.run(kind, record=True, progress_callback=progress_callback)
                       for kind in kinds]
            return {'benchmarks': results,
                    'readings': readings() if readings is not None else None}

        worker = Worker(worker_func)
        worker.signals.result.connect(receiver)
        worker.signals.error.connect(self.on_benchmark_failed)
        self._benchmark_workers.append(worker)
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _live_readings():
        """The figures that describe the machine as it is, not as it was configured."""
        return {
            'cpu': SystemInfo.get_cpu_info(),
            'memory': SystemInfo.get_memory_info(),
            'frames': shared_clock().stats(),
        }

    def on_benchmark_failed(self, error):
        kind, value, _traceback = error
        self.diagnostic_results.setPlainText(f"Benchmark failed: {kind.__name__}: {value}")
        self.health_status.setText("Status: Test failed")

    def show_hardware_test(self, payload):
        results = payload['benchmarks']
        blocks = [BenchmarkRunner.describe(result) for result in results]
        refused = [result for result in results if result.get('ran') is None]
        closing = ("Nothing here is graded against another machine: the app has never "
                   "collected anybody else's result, so it compares this run with its "
                   "own earlier ones.")
        if refused:
            closing = (f"{len(refused)} of {len(results)} kinds did not run; their "
                       f"reasons are printed above.")
        self.diagnostic_results.setPlainText(
            "Hardware Performance Test Results:\n\n" + '\n\n'.join(blocks)
            + "\n\n" + closing)
        self.health_status.setText("Status: Hardware test completed")
    
    def run_dependency_check(self):
        """Check all dependencies using engine."""
        self.health_status.setText("Status: Checking dependencies...")
        
        try:
            deps = DependencyChecker.check_all_dependencies()
            
            results = "Dependency Check Results:\n\n=== REQUIRED PACKAGES ===\n"
            for pkg, info in deps['required'].items():
                status = '[Installed]' if info['installed'] else '[Missing]'
                version = info['version'] if info['version'] else 'N/A'
                results += f"{status} {pkg}: {version}\n"
            
            results += "\n=== OPTIONAL PACKAGES ===\n"
            for pkg, info in deps['optional'].items():
                status = '[Installed]' if info['installed'] else '[Not Installed]'
                version = info['version'] if info['version'] else 'Not installed'
                results += f"{status} {pkg}: {version}\n"
            
            self.diagnostic_results.setPlainText(results)
            self.health_status.setText("Status: Dependency check completed")
            
        except Exception as e:
            self.diagnostic_results.setPlainText(f"Error checking dependencies: {str(e)}")
            self.health_status.setText("Status: Check failed")
    
    def run_performance_test(self):
        """Every kind of work the engine performs, with the machine read in the same pass.

        Both halves used to be invented. The two ratings came from thresholds the loop
        always beat; the two lines under `SYSTEM INFORMATION` asked psutil twice from the
        interface thread, which is why the pane would not answer while it claimed to be
        measuring. The frame figures are new and they are the app's own views: a viewer
        that drew nothing says that, instead of a rate made by dividing one timer tick by
        the next - which the old code computed and never showed anyone.
        """
        self.health_status.setText("Status: Running performance tests...")
        self.diagnostic_results.setPlainText("Benchmarking system performance...")
        self.run_engine_kinds(BenchmarkRunner.KINDS, self.show_performance_test,
                              readings=self._live_readings)

    def show_performance_test(self, payload):
        results = payload['benchmarks']
        readings = payload['readings']
        cpu = readings['cpu']
        memory = readings['memory']
        frames = readings['frames']

        if frames['fps'] is None:
            frame_lines = (f"Frames: nothing measured - {frames['reason']}\n"
                           f"  frames finished since this pane opened: "
                           f"{frames['total_frames']}")
            if frames['failures']:
                frame_lines += (
                    f"\n  paints that raised: {frames['failures']}"
                    f"\n  last one said: {frames['last_failure']}")
        else:
            frame_lines = (
                f"Frames: {frames['fps']} fps from {frames['frames']} frames drawn by "
                f"{', '.join(frames['sources']) or 'no view'}; "
                f"{frames['frame_time_ms']} ms average, "
                f"{frames['slowest_frame_ms']} ms slowest, over the last "
                f"{frames['window_seconds']:g} s")

        blocks = [BenchmarkRunner.describe(result) for result in results]
        refused = [result for result in results if result.get('ran') is None]
        overall = (f"{len(results) - len(refused)} of {len(results)} kinds of work "
                   f"were timed")
        if refused:
            overall += f"; {len(refused)} did not run, each with its reason above"

        self.diagnostic_results.setPlainText(
            "Performance Test Results:\n\n" + '\n\n'.join(blocks)
            + "\n\n=== THIS MACHINE, WHILE IT WAS BEING TIMED ===\n"
            + f"CPU: {cpu['usage_percent']}% busy across {cpu['logical_cores']} "
              f"logical cores ({cpu['physical_cores']} physical), "
              f"{cpu['current_frequency']} now\n"
            + f"Memory: {memory['used']} used / {memory['total']} total "
              f"({memory['percent']}%)\n"
            + frame_lines
            + f"\n\nOverall: {overall}.")
        self.health_status.setText("Status: Performance test completed")
    
    def run_off_thread(self, measure, receiver, busy_text, sink=None):
        """Ask one question of the machine on a worker, with the failure channel connected.

        Every measurement this pane makes blocks: a drive scan, a WMI query, a walk of
        every live object. Run on the interface thread they stop the window from painting,
        which is how the pane came to look busy while it was only stuck. `measure` takes no
        arguments and runs on the worker; `receiver` gets its return value on this thread.
        """
        target = sink if sink is not None else self.debug_output
        target.setPlainText(busy_text)

        def worker_func(progress_callback=None):
            return measure()

        worker = Worker(worker_func)
        worker.signals.result.connect(receiver)
        worker.signals.error.connect(self.on_measurement_failed)
        self._measure_workers.append(worker)
        QThreadPool.globalInstance().start(worker)

    def on_measurement_failed(self, error):
        kind, value, _traceback = error
        self.debug_output.setPlainText(
            f"The measurement raised before it answered.\n\n"
            f"{kind.__name__}: {value}")

    def dump_application_state(self):
        """The state of this process, read from the process.

        The lines this replaced were a screenshot of a session that had not happened:
        `Windows 11` and `PyQt 6.5.2` on a machine running a different build of each,
        three loaded models nobody loaded, twelve active processes nobody counted, and
        `GPU Acceleration: Enabled` in a viewer that had not drawn. Every figure below
        comes from one worker-thread pass over this process, the panes under the same
        window, and the shared clock the 3D views stamp.
        """
        self.run_off_thread(self._state_readings, self.show_application_state,
                            "Reading this process, the panes beside it and this pane's own records...")

    def _state_readings(self):
        return {
            'build': SystemInfo.get_build_info(),
            'process': SystemInfo.get_process_info(),
            'memory': SystemInfo.get_memory_info(),
            'frames': shared_clock().stats(),
            'viewers': self._viewer_files(),
            'queue': self._queue_readings(),
            'error_log': self._error_log_readings(),
            'pane': {
                'log_rows': len(self.log_entries),
                'reports_written': len(self._report_paths),
                'filters': self.log_level_combo.currentText(),
            },
        }

    def _viewer_files(self):
        """The files the 3D views under this window are actually holding.

        Reached through the widget tree rather than a registry because the app has no
        registry: each view keeps its own path. A pane shown on its own has no views
        beside it and says that, instead of reporting an empty list as if the app had
        nothing open.
        """
        owner = self.window()
        if owner is self:
            return {'available': False,
                    'reason': 'this pane is not inside the main window, so it has no sibling views to ask'}
        holders = [child for child in owner.findChildren(QWidget)
                   if hasattr(child, 'current_file_path')]
        paths = [getattr(child, 'current_file_path', None) for child in holders]
        return {
            'available': True,
            'views': len(holders),
            'files': [str(path) for path in paths if path],
        }

    def _queue_readings(self):
        """What the job queue above this pane says, or why it cannot be asked."""
        owner = self.window()
        manager = getattr(owner, 'job_manager', None)
        if manager is None:
            return {'available': False,
                    'reason': f'the window above this pane is a {type(owner).__name__}, '
                              f'which holds no job queue'}
        try:
            stats = manager.get_queue_stats()
            durations = [job.end_time - job.start_time
                         for job in manager.get_all_jobs()
                         if getattr(job, 'start_time', None) and getattr(job, 'end_time', None)]
        except Exception as failed:
            return {'available': False, 'reason': f'{type(failed).__name__}: {failed}'}
        return {
            'available': True,
            'stats': stats,
            'finished_with_a_clock': len(durations),
            'mean_seconds': round(sum(durations) / len(durations), 2) if durations else None,
            'slowest_seconds': round(max(durations), 2) if durations else None,
        }

    def _error_log_readings(self):
        """The app's own error file: where it is, and how many records are in it."""
        log_file = self.diagnostic_engine.error_logger.log_file
        records = self.diagnostic_engine.error_logger.get_recent_errors(limit=1000)
        return {
            'path': str(log_file),
            'exists': log_file.exists(),
            'records': len(records),
            'types': sorted({str(row.get('type') or '') for row in records}),
        }

    @staticmethod
    def _fmt(value, suffix=''):
        return f"{value}{suffix}" if value is not None else "not reported"

    @staticmethod
    def _peak_phrase(process):
        """The peak resident size in one phrase, or the statement that it is missing.

        A single 'not reported' inside a sentence that ends in 'MB' reads as a figure,
        which is the mistake this whole pass is about; so the wording is chosen whole.
        """
        if process['peak_rss_mb'] is None:
            return "peak not reported"
        return f"{process['peak_rss_mb']} MB at its peak"

    def show_application_state(self, payload):
        build = payload['build']
        process = payload['process']
        memory = payload['memory']
        frames = payload['frames']
        viewers = payload['viewers']
        queue = payload['queue']
        error_log = payload['error_log']
        pane = payload['pane']

        running = ('a frozen build' if build['packaged'] else 'a source tree')
        lines = [
            f"Application State Dump - {datetime.datetime.now()}",
            "",
            "=== WHAT THIS PROCESS IS ===",
            f"Operating system: {build['os']} on {build['architecture']}",
            f"Processor: {build['processor']}",
            f"Python: {build['python']} ({build['python_implementation']}), {running}",
            f"Qt runtime: {self._fmt(build['qt_runtime'])}, PyQt: {self._fmt(build['pyqt'])}",
        ]
        if build.get('reason'):
            lines.append(f"  ({build['reason']})")

        lines += [
            "",
            "=== THIS PROCESS, READ AT THIS MOMENT ===",
            f"Process id: {process['pid']}, started {process['started_at']}, "
            f"running {process['uptime_seconds']} s",
            f"Resident memory: {process['rss_mb']} MB now, "
            f"{self._peak_phrase(process)}; virtual {process['vms_mb']} MB",
            f"Threads: {self._fmt(process['threads'])}, "
            f"open files: {self._fmt(process['open_files'])}, "
            f"live objects: {self._fmt(process['gc_objects'])}",
        ]
        for note in process['failures']:
            lines.append(f"  not reported: {note}")

        lines += [
            "",
            "=== THE 3D VIEWS UNDER THIS WINDOW ===",
            (f"{viewers['views']} view(s) found, {len(viewers['files'])} holding a file"
             if viewers['available'] else f"Views: {viewers['reason']}"),
        ]
        if viewers['available']:
            for path in viewers['files'][:12]:
                lines.append(f"  {os.path.basename(path)}  ({path})")
            if not viewers['files']:
                lines.append("  none: every view is showing nothing")
        lines.append(f"Frames: {self._frame_sentence(frames)}")

        lines += [
            "",
            "=== THE JOB QUEUE ===",
            (f"{queue['stats']['total']} job(s): "
             f"{queue['stats']['pending']} waiting, {queue['stats']['rendering']} running, "
             f"{queue['stats']['paused']} paused, {queue['stats']['completed']} finished, "
             f"{queue['stats']['failed']} failed"
             if queue['available'] else f"Queue: {queue['reason']}"),
        ]
        if queue['available']:
            lines.append(
                f"{queue['finished_with_a_clock']} job(s) carry both a start and an end time"
                if queue['mean_seconds'] is None else
                f"Finished jobs took {queue['mean_seconds']} s on average, "
                f"{queue['slowest_seconds']} s at the slowest")

        lines += [
            "",
            "=== WHAT THIS PANE HOLDS ===",
            f"Log records it has seen: {pane['log_rows']} (level filter set to "
            f"{pane['filters']}), reports it wrote this session: {pane['reports_written']}",
            f"Error log on disk: {error_log['records']} record(s) in {error_log['path']}"
            + ("" if error_log['exists'] else " (the file does not exist)"),
            f"This machine's memory: {memory['used']} used of {memory['total']} "
            f"({memory['percent']}%), swap {memory['swap_used']} of {memory['swap_total']}",
            "",
            "=== WHAT THIS DUMP DOES NOT ANSWER ===",
            "  Which models are open inside a view's scene: a view reports the file it "
            "reads, not the objects it built from it.",
            "  Whether a crash ended an earlier session: this process cannot see the one "
            "before it, and the error log above only holds what the app wrote.",
            "  Any figure for another machine: nothing here has ever left this one.",
        ]
        self.debug_output.setPlainText('\n'.join(lines))

    def _frame_sentence(self, frames):
        if frames['fps'] is None:
            return f"nothing measured - {frames['reason']}"
        return (f"{frames['fps']} fps from {frames['frames']} frame(s) drawn by "
                f"{', '.join(frames['sources']) or 'a view'}, "
                f"{frames['frame_time_ms']} ms average, "
                f"{frames['slowest_frame_ms']} ms slowest")

    def take_memory_snapshot(self):
        """Every live object in this process, counted by what it actually is.

        The snapshot this replaces was a price list: `3D Viewer: 245 MB`, `Textures: 89
        MB`, `Cache: 67 MB`, `Cached Models: 8`, plus advice to free two amounts nothing
        in the app measures. Memory is not tagged by the feature that asked for it, and
        the interpreter's allocation tracer is not started at launch, so there is no
        per-feature total to read; object counts and this process's resident size are
        what can be measured, and that is what is printed.
        """
        self.run_off_thread(lambda: SystemInfo.live_object_counts(limit=14),
                            self.show_memory_snapshot,
                            "Walking every live object in this process...")

    def show_memory_snapshot(self, payload):
        process = payload['process']
        memory = payload['machine_memory']
        lines = [
            f"Memory Snapshot - {datetime.datetime.now()}",
            "",
            "=== THIS PROCESS ===",
            f"Resident: {process['rss_mb']} MB now, {self._peak_phrase(process)}; "
            f"virtual {process['vms_mb']} MB",
            f"Threads: {self._fmt(process['threads'])}, "
            f"open files: {self._fmt(process['open_files'])}, "
            f"up since {process['started_at']} ({process['uptime_seconds']} s)",
        ]
        for note in process['failures']:
            lines.append(f"  not reported: {note}")
        lines += [
            "",
            f"=== ALIVE RIGHT NOW ({payload['scanned']} objects of "
            f"{payload['distinct_classes']} classes) ===",
        ]
        for name, count in payload['classes']:
            lines.append(f"  {count:>8}  {name}")
        lines += [
            "",
            "=== BUFFERS THAT STATE THEIR OWN SIZE ===",
            f"{payload['array_like_count']} object(s) of these types: "
            f"{payload['sized_types']}",
            f"Together they hold {payload['array_bytes']} bytes "
            f"({payload['array_mb']} MB).",
            "That is a floor, not a total: it counts only buffers whose type reports its "
            "own size, and none of the Python objects wrapped around them.",
            "",
            "=== THIS MACHINE ===",
            f"Physical memory: {memory['used']} used of {memory['total']}, "
            f"{memory['available']} marked available ({memory['percent']}% used)",
            f"Swap: {memory['swap_used']} of {memory['swap_total']} "
            f"({memory['swap_percent']}%)",
            "",
            "=== WHAT A PER-FEATURE BREAKDOWN WOULD NEED ===",
            "The interpreter tracer (tracemalloc) started before the first allocation, and "
            "a record of which feature asked for each block. Neither exists in this app, "
            "so the counts above are the whole honest answer.",
        ]
        self.debug_output.setPlainText('\n'.join(lines))

    def generate_debug_report(self):
        """Write the full system reading to a file and put that file in the list.

        The row this replaces named a report with no bytes behind it, so selecting it
        showed a crash that never happened. The list row now carries the path, and the
        preview reads the file.
        """
        self.run_off_thread(self.diagnostic_engine.export_report, self.show_debug_report,
                            "Taking the full system reading (drives, adapters and "
                            "dependencies included - a few seconds)...")

    def show_debug_report(self, report_path):
        """The file the engine just wrote, and the row in the list that points at it.

        The line this replaces was the busy message left on screen: the method added a
        list row and never said where the report went, so the pane kept claiming it was
        still taking the reading.
        """
        self._add_report_row(f"System Report - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
                             report_path)
        self.debug_output.setPlainText(
            f"Wrote the full system reading, {os.path.getsize(report_path)} bytes, to:\n"
            f"{report_path}\n\n"
            "The row added to the list points at this file, and the preview beside the "
            "list is showing it.")

    def generate_error_report(self):
        """Fill the report type the combo names, from figures the engine can read.

        `Custom Report` is on that list with nothing behind it, and the button used to
        answer by adding its name to the list anyway. Now it says which kinds the engine
        can fill and writes nothing.
        """
        report_type = self.generate_report_combo.currentText()
        rows = list(self.log_entries)
        self.run_off_thread(
            lambda: self.diagnostic_engine.export_error_report(report_type, rows),
            self.show_generated_report, f"Writing the {report_type}...")

    def show_generated_report(self, result):
        path = result.get('path')
        if not path:
            self.debug_output.setPlainText(
                f"No file was written.\n\n{result['reason']}\n\n"
                f"Each kind holds: " +
                '\n'.join(f"  {name}: {what}"
                          for name, what in self.diagnostic_engine.REPORT_KINDS.items()))
            return
        self._add_report_row(
            f"{result['report_type']} - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}", path)
        self.debug_output.setPlainText(
            f"Wrote {os.path.getsize(path)} bytes to:\n{path}\n\n"
            f"Its sections: {', '.join(result['sections'])}")

    def _add_report_row(self, name, path):
        """One row per file that exists, carrying the path of that file."""
        self.reports_list.addItem(name)
        row = self.reports_list.item(self.reports_list.count() - 1)
        row.setData(Qt.ItemDataRole.UserRole, path)
        self._report_paths[path] = name
        self.reports_list.setCurrentItem(row)

    def preview_report(self):
        """Show the file behind the selected row, as it is on disk.

        Selecting a row used to paint a fixed crash - a `mesh_processor.cpp` stack trace
        from C++ this app does not contain, with memory figures nobody read. There is no
        canned content left to show: the text below is the file, and if the file is gone
        the pane says where it was.
        """
        item = self.reports_list.currentItem()
        if item is None:
            self.report_preview.setPlainText(
                "Nothing selected. The list holds only reports this app wrote in this "
                "session; generate one and its file appears here.")
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            self.report_preview.setPlainText(
                f"'{item.text()}' has no file behind it. Rows written by earlier versions "
                f"of this pane were names only.")
            return
        if not os.path.exists(path):
            self.report_preview.setPlainText(
                f"The file this row points at is gone:\n{path}\n"
                f"Nothing in the app deleted it; the pane only reads it.")
            return
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                raw = handle.read()
        except OSError as failed:
            self.report_preview.setPlainText(f"Could not read {path}: {failed}")
            return
        try:
            body = json.dumps(json.loads(raw), indent=2)
            kind = "JSON"
        except ValueError:
            body, kind = raw, "plain text"
        shown = body[:200000]
        note = ("" if len(body) <= 200000 else
                f"\n\n[stopped at 200,000 of {len(body)} characters]")
        stamp = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        self.report_preview.setPlainText(
            f"{item.text()}\n"
            f"Read from: {path}\n"
            f"{os.path.getsize(path)} bytes on disk, last written {stamp:%Y-%m-%d %H:%M:%S}, "
            f"{kind} as the app wrote it.\n\n"
            f"{shown}{note}")

    def analyze_logs(self):
        """Count the records this pane actually holds, over the window it can cut.

        Every number this method used to print was written here: 1,247 records, a 2.3%
        error rate, a 156 ms response time, 1.8 GB peak, three named issues with
        frequencies and a fix each, and trends about a 14:30-15:00 anomaly that no
        record mentions. The records are the pane's own; the window, the counts and the
        repeats are arithmetic over them; the response time is the app's own job clock,
        and a crash that ended an earlier session stays unreachable because it is.
        """
        window_name = self.analysis_period_combo.currentText()
        rows = list(self.log_entries)

        def measure():
            cut = self.diagnostic_engine.rows_in_window(rows, window_name)
            summary = self.diagnostic_engine.summarise_log_rows(cut['rows'])
            return {
                'window': window_name,
                'seconds': cut['seconds'],
                'cutoff': cut['cutoff'],
                'unparsed': cut['unparsed'],
                'reason': cut['reason'],
                'summary': summary,
                'seen': len(rows),
                'queue': self._queue_readings(),
                'process': SystemInfo.get_process_info(),
                'error_log': self._error_log_readings(),
            }

        self.run_off_thread(measure, self.show_log_analysis,
                            f"Counting the records in the {window_name} window...",
                            sink=self.trends_display)

    def show_log_analysis(self, payload):
        summary = payload['summary']
        queue = payload['queue']
        process = payload['process']
        error_log = payload['error_log']

        if payload['reason']:
            for label in (self.total_logs_label, self.error_rate_label,
                          self.avg_response_label, self.peak_memory_label,
                          self.crash_count_label):
                label.setText("not measured")
            self.frequent_issues_table.setRowCount(0)
            self.trends_display.setPlainText(
                f"Nothing was counted.\n\n{payload['reason']}\n\n"
                f"The records this pane holds ({payload['seen']}) were left untouched, "
                f"because cutting them on a range nobody gave would be a made-up window.")
            return

        self.total_logs_label.setText(
            f"{summary['total']} of {payload['seen']} seen")
        self.error_rate_label.setText(
            f"{summary['error_rate_percent']}%" if summary['error_rate_percent'] is not None
            else "no records")
        if queue['available'] and queue['mean_seconds'] is not None:
            self.avg_response_label.setText(
                f"{queue['mean_seconds']} s over {queue['finished_with_a_clock']} finished job(s)")
        else:
            self.avg_response_label.setText(
                "no finished job" if queue['available'] else "not measured")
        self.peak_memory_label.setText(
            f"{process['peak_rss_mb']} MB in this process"
            if process['peak_rss_mb'] is not None else "peak not reported")
        if error_log['exists'] and error_log['records']:
            self.crash_count_label.setText(f"{error_log['records']} record(s)")
        else:
            self.crash_count_label.setText("nothing recorded")

        issues = [row for row in summary['repeated']
                  if row['level'] in ('ERROR', 'WARNING')]
        self.frequent_issues_table.setRowCount(len(issues))
        for row_number, issue in enumerate(issues):
            self.frequent_issues_table.setItem(row_number, 0,
                                               QTableWidgetItem(issue['message'][:120]))
            self.frequent_issues_table.setItem(row_number, 1,
                                               QTableWidgetItem(f"{issue['count']} times"))
            self.frequent_issues_table.setItem(
                row_number, 2, QTableWidgetItem(self._ago(issue['last_at'])))
            self.frequent_issues_table.setItem(
                row_number, 3, QTableWidgetItem(issue['component'] or 'no module name'))

        cut_at = (datetime.datetime.fromtimestamp(payload['cutoff'])
                  if payload['cutoff'] else None)
        lines = [
            f"Log Analysis - the {payload['window']} window, so only records the pane "
            f"stamped at or after " + (f"{cut_at:%Y-%m-%d %H:%M:%S}" if cut_at
                                       else "a time it could not read"),
            "",
            "=== WHAT THE RECORDS SAY ===",
            f"Records in the window: {summary['total']} of the {payload['seen']} this pane "
            f"has ever seen; it holds the first one at {self._fmt(summary['first_at'])} and "
            f"the last at {self._fmt(summary['last_at'])} "
            f"({self._fmt(summary['span_seconds'], ' s')} apart)",
            f"Levels: " + (', '.join(f"{name}: {count}" for name, count in summary['by_level'])
                           or "none"),
            f"Error rate: {self._fmt(summary['error_rate_percent'], '%')} - "
            f"{summary['errors']} ERROR of {summary['total']} records in this window",
            f"Modules: " + (', '.join(f"{name}: {count}"
                                      for name, count in summary['by_component']) or "none"),
            f"Messages that repeat: {len(summary['repeated'])}",
            "",
            "=== WHAT THE REPEATS ARE ===",
        ]
        if summary['repeated']:
            for issue in summary['repeated'][:12]:
                lines.append(f"  [{issue['level']}] {issue['message'][:110]} - "
                             f"{issue['count']} time(s), last {self._ago(issue['last_at'])}, "
                             f"from {issue['component'] or 'no module name'}")
        else:
            lines.append("  No message appears twice in this window, so nothing here is a pattern.")

        lines += [
            "",
            "=== THE APP'S OWN JOB CLOCK AND ERROR FILE ===",
            (f"{queue['stats']['total']} job(s) in the queue, "
             f"{queue['finished_with_a_clock']} of them carrying a start and an end time"
             if queue['available'] else f"Job clock: {queue['reason']}"),
            f"Error file: {error_log['path']} - "
            + (f"{error_log['records']} record(s)" if error_log['exists']
               else "does not exist yet"),
            f"This process: {process['rss_mb']} MB resident now, "
            f"{self._fmt(process['peak_rss_mb'])} MB at its peak",
            "",
            "=== WHAT THIS COUNT CANNOT REACH ===",
            "  Records logged before this pane opened: the list above is what this pane "
            "caught, and nothing older.",
            "  A crash that ended an earlier session: this count is only what the "
            "exception handler managed to write to the file above. A process the "
            "operating system killed, or one that died before the handler ran, leaves "
            "nothing here, so an empty file is not evidence of an uneventful session.",
            "  Response time of anything that is not a queued job: no other part of the "
            "app records how long it took.",
        ]
        if payload['unparsed']:
            lines.append(f"  {payload['unparsed']} record(s) carry a time this pane cannot read "
                         f"and were left out of the window.")
        self.trends_display.setPlainText('\n'.join(lines))

    @staticmethod
    def _ago(stamp):
        """How long ago a record's own time was, in the coarsest unit that still says something."""
        at = DiagnosticEngine.parse_row_time(stamp)
        if at is None:
            return "time unreadable"
        seconds = max(0.0, (datetime.datetime.now() - at).total_seconds())
        if seconds < 60:
            return f"{seconds:.0f} s ago"
        if seconds < 3600:
            return f"{seconds / 60:.0f} min ago"
        if seconds < 86400:
            return f"{seconds / 3600:.1f} h ago"
        return f"{seconds / 86400:.1f} days ago"
