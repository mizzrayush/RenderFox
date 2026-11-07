"""
Settings tab for application configuration with persistent storage and advanced options.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLineEdit, QLabel, QPushButton, QFileDialog,
                             QFormLayout, QSpinBox, QCheckBox, QComboBox,
                             QScrollArea, QMessageBox, QTabWidget, QSlider,
                             QDoubleSpinBox, QTextEdit, QListWidget, QListWidgetItem,
                             QFrame)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication
import os
import json
import logging
from ..core.models import SoftwareConfiguration, SoftwareType, AppSettings
from .icon_provider import get_icon
from .styles import AVAILABLE_THEMES, get_theme_stylesheet, MODERN_DARK_THEME, MODERN_LIGHT_THEME, MODERN_MIDNIGHT_THEME

# The packaged build has no console (`RenderFox.spec`: console=False), so the only report
# channel a failure has is the root logger the Diagnostics pane reads.
logger = logging.getLogger(__name__)

class SettingsTab(QWidget):
    """Enhanced settings tab with comprehensive configuration options."""
    
    settings_changed = pyqtSignal()
    theme_changed = pyqtSignal(str)  # New signal for theme changes
    CONFIG_FILE = 'config.json'
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.app_settings = AppSettings()
        self.software_configs = {}
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Initialize the enhanced settings UI."""
        layout = QVBoxLayout(self)
        
        # Create tabbed interface for different setting categories
        self.settings_tabs = QTabWidget()
        layout.addWidget(self.settings_tabs)
        
        # Tab 1: Software Configuration
        self.create_software_tab()
        
        # Tab 2: Directories and Paths
        self.create_directories_tab()
        
        # Tab 3: Rendering Settings
        self.create_rendering_tab()
        
        # Tab 4: User Interface
        self.create_ui_tab()
        
        # Tab 5: Performance
        self.create_performance_tab()
        
        # Tab 6: Advanced
        self.create_advanced_tab()
        
        # Bottom action buttons
        self.create_action_buttons(layout)
    
    def create_software_tab(self):
        """Create the software configuration tab."""
        software_widget = QWidget()
        layout = QVBoxLayout(software_widget)
        
        # Software detection section
        detection_group = QGroupBox("Software Detection")
        detection_layout = QVBoxLayout(detection_group)
        
        detect_button_layout = QHBoxLayout()
        self.auto_detect_btn = QPushButton("Auto-Detect All Software")
        self.auto_detect_btn.setIcon(get_icon("scan"))
        self.auto_detect_btn.clicked.connect(self.auto_detect_software)
        self.refresh_status_btn = QPushButton("Refresh Status")
        self.refresh_status_btn.setIcon(get_icon("refresh"))
        self.refresh_status_btn.clicked.connect(self.refresh_software_status)
        
        detect_button_layout.addWidget(self.auto_detect_btn)
        detect_button_layout.addWidget(self.refresh_status_btn)
        detect_button_layout.addStretch()
        detection_layout.addLayout(detect_button_layout)
        
        # Software status display
        self.software_status = QTextEdit()
        self.software_status.setMaximumHeight(100)
        self.software_status.setReadOnly(True)
        detection_layout.addWidget(self.software_status)
        
        layout.addWidget(detection_group)
        
        # Individual software configuration
        config_group = QGroupBox("Software Executable Paths")
        config_layout = QFormLayout(config_group)
        config_layout.setVerticalSpacing(12)
        config_layout.setHorizontalSpacing(16)
        
        # Create path inputs for each software type
        self.software_paths = {}
        for software_type in SoftwareType:
            path_layout = QHBoxLayout()
            
            path_input = QLineEdit()
            path_input.setPlaceholderText(f"Path to {software_type.value.title()} executable")
            
            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(lambda checked, st=software_type: self.browse_executable(st))
            
            test_btn = QPushButton("Test")
            test_btn.clicked.connect(lambda checked, st=software_type: self.test_software(st))
            
            path_layout.addWidget(path_input)
            path_layout.addWidget(browse_btn)
            path_layout.addWidget(test_btn)
            
            config_layout.addRow(f"{software_type.value.title()}:", path_layout)
            self.software_paths[software_type] = path_input
        
        layout.addWidget(config_group)
        
        # Additional software settings
        additional_group = QGroupBox("Additional Software Settings")
        additional_layout = QFormLayout(additional_group)
        additional_layout.setVerticalSpacing(12)
        additional_layout.setHorizontalSpacing(16)
        
        self.timeout_minutes = QSpinBox()
        self.timeout_minutes.setRange(1, 1440)  # 1 minute to 24 hours
        self.timeout_minutes.setValue(60)
        self.timeout_minutes.setMaximumWidth(140)
        self.timeout_minutes.setSuffix(" min")
        additional_layout.addRow("Render Timeout:", self.timeout_minutes)
        
        self.memory_limit = QSpinBox()
        self.memory_limit.setRange(0, 64000)  # 0 = no limit, up to 64GB
        self.memory_limit.setValue(4096)
        self.memory_limit.setMaximumWidth(140)
        self.memory_limit.setSuffix(" MB")
        additional_layout.addRow("Memory Limit (0=unlimited):", self.memory_limit)
        
        self.verify_software = QCheckBox("Verify software availability on startup")
        self.verify_software.setChecked(True)
        additional_layout.addRow(self.verify_software)
        
        layout.addWidget(additional_group)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(software_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Software")
    
    def create_directories_tab(self):
        """Create the directories and paths tab."""
        dirs_widget = QWidget()
        layout = QVBoxLayout(dirs_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Default directories
        dirs_group = QGroupBox("Default Directories")
        dirs_layout = QFormLayout(dirs_group)
        dirs_layout.setVerticalSpacing(12)
        dirs_layout.setHorizontalSpacing(16)
        
        # Project directory
        project_layout = QHBoxLayout()
        self.project_dir = QLineEdit()
        self.browse_project_btn = QPushButton("Browse...")
        self.browse_project_btn.clicked.connect(self.browse_project_dir)
        project_layout.addWidget(self.project_dir)
        project_layout.addWidget(self.browse_project_btn)
        dirs_layout.addRow("Default Project Directory:", project_layout)
        
        # Output directory
        output_layout = QHBoxLayout()
        self.default_output = QLineEdit()
        self.browse_output_btn = QPushButton("Browse...")
        self.browse_output_btn.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(self.default_output)
        output_layout.addWidget(self.browse_output_btn)
        dirs_layout.addRow("Default Output Directory:", output_layout)
        
        # Temporary directory
        temp_layout = QHBoxLayout()
        self.temp_dir = QLineEdit()
        self.browse_temp_btn = QPushButton("Browse...")
        self.browse_temp_btn.clicked.connect(self.browse_temp_dir)
        temp_layout.addWidget(self.temp_dir)
        temp_layout.addWidget(self.browse_temp_btn)
        dirs_layout.addRow("Temporary Directory:", temp_layout)
        
        # Archive directory
        archive_layout = QHBoxLayout()
        self.archive_dir = QLineEdit()
        self.browse_archive_btn = QPushButton("Browse...")
        self.browse_archive_btn.clicked.connect(self.browse_archive_dir)
        archive_layout.addWidget(self.archive_dir)
        archive_layout.addWidget(self.browse_archive_btn)
        dirs_layout.addRow("Archive Directory:", archive_layout)
        
        layout.addWidget(dirs_group)
        
        # File management settings
        file_group = QGroupBox("File Management")
        file_layout = QFormLayout(file_group)
        file_layout.setVerticalSpacing(12)
        file_layout.setHorizontalSpacing(16)
        
        self.auto_create_dirs = QCheckBox("Automatically create output directories")
        self.auto_create_dirs.setChecked(True)
        file_layout.addRow(self.auto_create_dirs)
        
        self.organize_by_date = QCheckBox("Organize outputs by date")
        file_layout.addRow(self.organize_by_date)
        
        self.organize_by_project = QCheckBox("Organize outputs by project")
        self.organize_by_project.setChecked(True)
        file_layout.addRow(self.organize_by_project)
        
        self.backup_projects = QCheckBox("Backup project files before processing")
        file_layout.addRow(self.backup_projects)
        
        self.max_backups = QSpinBox()
        self.max_backups.setRange(1, 100)
        self.max_backups.setValue(5)
        self.max_backups.setMaximumWidth(120)
        file_layout.addRow("Max backup files to keep:", self.max_backups)
        
        layout.addWidget(file_group)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(dirs_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Directories")
    
    def create_rendering_tab(self):
        """Create the rendering settings tab."""
        render_widget = QWidget()
        layout = QVBoxLayout(render_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Performance settings
        perf_group = QGroupBox("Performance Settings")
        perf_layout = QFormLayout(perf_group)
        perf_layout.setVerticalSpacing(12)
        perf_layout.setHorizontalSpacing(16)
        
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 16)
        self.max_concurrent.setValue(1)
        self.max_concurrent.setMaximumWidth(120)
        perf_layout.addRow("Max Concurrent Jobs:", self.max_concurrent)
        
        self.cpu_priority = QComboBox()
        self.cpu_priority.addItems(["Low", "Below Normal", "Normal", "Above Normal", "High"])
        self.cpu_priority.setCurrentText("Normal")
        self.cpu_priority.setMaximumWidth(220)
        perf_layout.addRow("CPU Priority:", self.cpu_priority)
        
        self.use_gpu = QCheckBox("Enable GPU acceleration when available")
        self.use_gpu.setChecked(True)
        perf_layout.addRow(self.use_gpu)
        
        self.thread_count = QSpinBox()
        self.thread_count.setRange(0, 64)  # 0 = auto
        self.thread_count.setValue(0)
        self.thread_count.setMaximumWidth(120)
        perf_layout.addRow("Thread Count (0=auto):", self.thread_count)
        
        layout.addWidget(perf_group)
        
        # Queue management
        queue_group = QGroupBox("Queue Management")
        queue_layout = QFormLayout(queue_group)
        queue_layout.setVerticalSpacing(12)
        queue_layout.setHorizontalSpacing(16)
        
        self.auto_start = QCheckBox("Auto-start queue when jobs are added")
        queue_layout.addRow(self.auto_start)
        
        self.auto_retry = QCheckBox("Auto-retry failed jobs")
        queue_layout.addRow(self.auto_retry)
        
        self.max_retries = QSpinBox()
        self.max_retries.setRange(1, 10)
        self.max_retries.setValue(3)
        self.max_retries.setMaximumWidth(120)
        queue_layout.addRow("Max retry attempts:", self.max_retries)
        
        self.pause_on_error = QCheckBox("Pause queue on error")
        queue_layout.addRow(self.pause_on_error)
        
        self.save_queue_state = QCheckBox("Save queue state on exit")
        self.save_queue_state.setChecked(True)
        queue_layout.addRow(self.save_queue_state)
        
        layout.addWidget(queue_group)
        
        # Default render settings
        defaults_group = QGroupBox("Default Render Settings")
        defaults_layout = QFormLayout(defaults_group)
        defaults_layout.setVerticalSpacing(12)
        defaults_layout.setHorizontalSpacing(16)
        
        self.default_resolution = QComboBox()
        self.default_resolution.addItems([
            "1920x1080 (1080p)", "2560x1440 (1440p)", "3840x2160 (4K)",
            "1280x720 (720p)", "1600x900", "Custom"
        ])
        self.default_resolution.setMaximumWidth(260)
        defaults_layout.addRow("Default Resolution:", self.default_resolution)
        
        self.default_format = QComboBox()
        self.default_format.addItems(["PNG", "JPEG", "EXR", "TIFF"])
        self.default_format.setMaximumWidth(260)
        defaults_layout.addRow("Default Output Format:", self.default_format)
        
        self.default_quality = QSlider(Qt.Orientation.Horizontal)
        self.default_quality.setRange(1, 100)
        self.default_quality.setValue(85)
        self.default_quality.setMaximumWidth(280)
        self.quality_label = QLabel("85%")
        self.default_quality.valueChanged.connect(
            lambda v: self.quality_label.setText(f"{v}%"))
        
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(self.default_quality)
        quality_layout.addWidget(self.quality_label)
        quality_layout.addStretch()
        defaults_layout.addRow("Default Quality:", quality_layout)
        
        layout.addWidget(defaults_group)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(render_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Rendering")
    
    def create_ui_tab(self):
        """Create the user interface settings tab."""
        ui_widget = QWidget()
        layout = QVBoxLayout(ui_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Appearance settings
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance_group)
        appearance_layout.setVerticalSpacing(14)
        appearance_layout.setHorizontalSpacing(18)
        appearance_layout.setContentsMargins(14, 18, 14, 14)
        
        self.theme = QComboBox()
        self.theme.setMaximumWidth(260)
        self.theme.addItems(AVAILABLE_THEMES)
        self.theme.currentTextChanged.connect(self.apply_theme)  # Connect to theme application
        appearance_layout.addRow("Theme:", self.theme)
        
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(10)
        self.font_size.setMaximumWidth(120)
        self.font_size.valueChanged.connect(self.apply_font_size)  # Connect font changes
        appearance_layout.addRow("Font Size:", self.font_size)
        
        self.show_tooltips = QCheckBox("Show tooltips")
        self.show_tooltips.setChecked(True)
        appearance_layout.addRow(self.show_tooltips)
        
        self.animate_ui = QCheckBox("Enable UI animations")
        self.animate_ui.setChecked(True)
        appearance_layout.addRow(self.animate_ui)
        
        layout.addWidget(appearance_group)
        
        # Behavior settings
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QFormLayout(behavior_group)
        behavior_layout.setVerticalSpacing(14)
        behavior_layout.setHorizontalSpacing(18)
        behavior_layout.setContentsMargins(14, 18, 14, 14)
        
        self.confirm_deletions = QCheckBox("Confirm before deleting jobs")
        self.confirm_deletions.setChecked(True)
        behavior_layout.addRow(self.confirm_deletions)
        
        self.remember_window_state = QCheckBox("Remember window size and position")
        self.remember_window_state.setChecked(True)
        behavior_layout.addRow(self.remember_window_state)
        
        self.auto_save_workspace = QCheckBox("Auto-save workspace")
        self.auto_save_workspace.setChecked(True)
        behavior_layout.addRow(self.auto_save_workspace)
        
        self.auto_save_interval = QSpinBox()
        self.auto_save_interval.setRange(30, 3600)  # 30 seconds to 1 hour
        self.auto_save_interval.setValue(300)  # 5 minutes
        self.auto_save_interval.setMaximumWidth(140)
        self.auto_save_interval.setSuffix(" s")
        behavior_layout.addRow("Auto-save interval:", self.auto_save_interval)
        
        layout.addWidget(behavior_group)
        
        # Notifications
        notif_group = QGroupBox("Notifications")
        notif_layout = QFormLayout(notif_group)
        notif_layout.setVerticalSpacing(12)
        notif_layout.setHorizontalSpacing(18)
        notif_layout.setContentsMargins(14, 18, 14, 14)
        
        self.notify_completion = QCheckBox("Notify on job completion")
        self.notify_completion.setChecked(True)
        notif_layout.addRow(self.notify_completion)
        
        self.notify_errors = QCheckBox("Notify on errors")
        self.notify_errors.setChecked(True)
        notif_layout.addRow(self.notify_errors)
        
        self.notify_queue_empty = QCheckBox("Notify when queue is empty")
        notif_layout.addRow(self.notify_queue_empty)
        
        self.sound_notifications = QCheckBox("Sound notifications")
        notif_layout.addRow(self.sound_notifications)
        
        self.system_tray = QCheckBox("Minimize to system tray")
        notif_layout.addRow(self.system_tray)
        
        layout.addWidget(notif_group)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(ui_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Interface")
    
    def create_performance_tab(self):
        """Create the performance settings tab."""
        perf_widget = QWidget()
        layout = QVBoxLayout(perf_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Update intervals
        update_group = QGroupBox("Update Intervals")
        update_layout = QFormLayout(update_group)
        update_layout.setVerticalSpacing(12)
        update_layout.setHorizontalSpacing(16)
        
        self.ui_update_interval = QSpinBox()
        self.ui_update_interval.setRange(100, 5000)
        self.ui_update_interval.setValue(1000)
        self.ui_update_interval.setMaximumWidth(140)
        self.ui_update_interval.setSuffix(" ms")
        update_layout.addRow("UI Update Interval:", self.ui_update_interval)
        
        self.progress_update_interval = QSpinBox()
        self.progress_update_interval.setRange(100, 2000)
        self.progress_update_interval.setValue(500)
        self.progress_update_interval.setMaximumWidth(140)
        self.progress_update_interval.setSuffix(" ms")
        update_layout.addRow("Progress Update Interval:", self.progress_update_interval)
        
        layout.addWidget(update_group)
        
        # Memory management
        memory_group = QGroupBox("Memory Management")
        memory_layout = QFormLayout(memory_group)
        memory_layout.setVerticalSpacing(12)
        memory_layout.setHorizontalSpacing(16)
        
        self.cache_preview_images = QCheckBox("Cache preview images")
        self.cache_preview_images.setChecked(True)
        memory_layout.addRow(self.cache_preview_images)
        
        self.max_cache_size = QSpinBox()
        self.max_cache_size.setRange(100, 10000)
        self.max_cache_size.setValue(1000)
        self.max_cache_size.setMaximumWidth(140)
        self.max_cache_size.setSuffix(" MB")
        memory_layout.addRow("Max Cache Size:", self.max_cache_size)
        
        self.cleanup_on_exit = QCheckBox("Cleanup temporary files on exit")
        self.cleanup_on_exit.setChecked(True)
        memory_layout.addRow(self.cleanup_on_exit)
        
        layout.addWidget(memory_group)
        
        # System monitoring
        monitor_group = QGroupBox("System Monitoring")
        monitor_layout = QFormLayout(monitor_group)
        monitor_layout.setVerticalSpacing(12)
        monitor_layout.setHorizontalSpacing(16)
        
        self.monitor_cpu = QCheckBox("Monitor CPU usage")
        self.monitor_cpu.setChecked(True)
        monitor_layout.addRow(self.monitor_cpu)
        
        self.monitor_memory = QCheckBox("Monitor memory usage")
        self.monitor_memory.setChecked(True)
        monitor_layout.addRow(self.monitor_memory)
        
        self.monitor_gpu = QCheckBox("Monitor GPU usage")
        monitor_layout.addRow(self.monitor_gpu)
        
        self.log_performance = QCheckBox("Log performance metrics")
        monitor_layout.addRow(self.log_performance)
        
        layout.addWidget(monitor_group)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(perf_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Performance")
    
    def create_advanced_tab(self):
        """Create the advanced settings tab."""
        advanced_widget = QWidget()
        main_layout = QVBoxLayout(advanced_widget)
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # Content widget for scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        
        # Logging settings
        logging_group = QGroupBox("Logging")
        logging_layout = QFormLayout(logging_group)
        logging_layout.setVerticalSpacing(12)
        logging_layout.setHorizontalSpacing(16)
        
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level.setCurrentText("INFO")
        self.log_level.setMaximumWidth(220)
        logging_layout.addRow("Log Level:", self.log_level)
        
        self.save_logs = QCheckBox("Save logs to file")
        self.save_logs.setChecked(True)
        logging_layout.addRow(self.save_logs)
        
        self.max_log_files = QSpinBox()
        self.max_log_files.setRange(1, 100)
        self.max_log_files.setValue(10)
        self.max_log_files.setMaximumWidth(120)
        logging_layout.addRow("Max log files to keep:", self.max_log_files)
        
        self.log_rotation_size = QSpinBox()
        self.log_rotation_size.setRange(1, 1000)
        self.log_rotation_size.setValue(10)
        self.log_rotation_size.setMaximumWidth(120)
        self.log_rotation_size.setSuffix(" MB")
        logging_layout.addRow("Log rotation size:", self.log_rotation_size)
        
        layout.addWidget(logging_group)
        
        # Development settings
        dev_group = QGroupBox("Development")
        dev_layout = QFormLayout(dev_group)
        dev_layout.setVerticalSpacing(12)
        dev_layout.setHorizontalSpacing(16)
        
        self.debug_mode = QCheckBox("Debug mode (verbose logging)")
        dev_layout.addRow(self.debug_mode)
        
        self.experimental_features = QCheckBox("Enable experimental features")
        dev_layout.addRow(self.experimental_features)
        
        self.telemetry_enabled = QCheckBox("Enable anonymous telemetry")
        self.telemetry_enabled.setChecked(True)
        dev_layout.addRow(self.telemetry_enabled)
        
        self.crash_reporting = QCheckBox("Enable crash reporting")
        self.crash_reporting.setChecked(True)
        dev_layout.addRow(self.crash_reporting)
        
        layout.addWidget(dev_group)
        
        # AI Model Configuration
        ai_group = QGroupBox("AI Model Configuration")
        ai_layout = QFormLayout(ai_group)
        ai_layout.setVerticalSpacing(12)
        ai_layout.setHorizontalSpacing(16)
        
        self.local_ai_model_path = QLineEdit()
        self.local_ai_model_path.setPlaceholderText("Path to local CLIP model (optional)")
        self.local_ai_model_path.setMinimumWidth(300)  # Make it wider as requested
        
        ai_model_browse_btn = QPushButton("Browse...")
        ai_model_browse_btn.clicked.connect(self.browse_ai_model)
        
        ai_path_layout = QHBoxLayout()
        ai_path_layout.addWidget(self.local_ai_model_path)
        ai_path_layout.addWidget(ai_model_browse_btn)
        
        ai_layout.addRow("Local Model Path:", ai_path_layout)
        ai_layout.addRow(QLabel("<small>Leave empty to download automatically</small>"))
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter API Key (e.g., Stability AI)")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setMaximumWidth(360)
        ai_layout.addRow("API Key (Online Mode):", self.api_key_input)
        
        self.download_models_btn = QPushButton("Download AI Models (Offline)")
        self.download_models_btn.setIcon(get_icon("import_model"))
        self.download_models_btn.clicked.connect(self.download_ai_models)
        self.download_models_btn.setMaximumWidth(260)
        ai_layout.addRow(self.download_models_btn)
        
        layout.addWidget(ai_group)
        
        # Updates
        update_group = QGroupBox("Updates")
        update_layout = QFormLayout(update_group)
        update_layout.setVerticalSpacing(12)
        update_layout.setHorizontalSpacing(16)
        
        self.check_updates = QCheckBox("Check for updates on startup")
        self.check_updates.setChecked(True)
        update_layout.addRow(self.check_updates)
        update_layout.addRow(self.check_updates)
        
        self.auto_update = QCheckBox("Automatically download updates")
        update_layout.addRow(self.auto_update)
        
        self.update_channel = QComboBox()
        self.update_channel.addItems(["Stable", "Beta", "Alpha"])
        update_layout.addRow("Update Channel:", self.update_channel)
        
        layout.addWidget(update_group)
        
        # Network settings
        network_group = QGroupBox("Network")
        network_layout = QFormLayout(network_group)
        
        self.proxy_enabled = QCheckBox("Use proxy server")
        network_layout.addRow(self.proxy_enabled)
        
        self.proxy_host = QLineEdit()
        self.proxy_host.setPlaceholderText("proxy.example.com")
        network_layout.addRow("Proxy Host:", self.proxy_host)
        
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(8080)
        network_layout.addRow("Proxy Port:", self.proxy_port)
        
        layout.addWidget(network_group)
        layout.addStretch()
        
        # Set scroll widget
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        
        self.settings_tabs.addTab(advanced_widget, "Advanced")
    
    def create_action_buttons(self, layout):
        """Create action buttons at the bottom."""
        buttons_layout = QHBoxLayout()
        
        self.export_settings_btn = QPushButton("Export Settings")
        self.export_settings_btn.setIcon(get_icon("export"))
        self.export_settings_btn.clicked.connect(self.export_settings)
        
        self.import_settings_btn = QPushButton("Import Settings")
        self.import_settings_btn.setIcon(get_icon("import_folder"))
        self.import_settings_btn.clicked.connect(self.import_settings)
        
        buttons_layout.addWidget(self.export_settings_btn)
        buttons_layout.addWidget(self.import_settings_btn)
        buttons_layout.addStretch()
        
        self.validate_btn = QPushButton("Validate Settings")
        self.validate_btn.setIcon(get_icon("select"))
        self.validate_btn.clicked.connect(self.validate_settings)
        
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setIcon(get_icon("backup"))
        self.save_btn.setProperty("primary", "true")
        self.save_btn.clicked.connect(self.save_settings)
        
        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.setIcon(get_icon("refresh"))
        self.reset_btn.clicked.connect(self.reset_settings)
        
        buttons_layout.addWidget(self.validate_btn)
        buttons_layout.addWidget(self.save_btn)
        buttons_layout.addWidget(self.reset_btn)
        
        layout.addLayout(buttons_layout)
    
    def download_ai_models(self):
        """Open the AI Model Manager dialog.

        The dialog is parented so the window's close walk reaches it, and it is kept on the
        pane rather than in a local: a download that outlasted the dialog's own stop waits
        inside `thread`, and the reference that holds it has to outlive the call.
        """
        from ..features.model_downloader import ModelDownloaderDialog
        self.model_manager = ModelDownloaderDialog(self, auto_start=False)
        self.model_manager.exec()

    def browse_ai_model(self):
        """Browse for local AI model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select AI Model File",
            "", "Model Files (*.pt *.pth *.bin);;All Files (*)")
        
        if file_path:
            self.local_ai_model_path.setText(file_path)

    def browse_executable(self, software_type: SoftwareType):
        """Browse for software executable."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"Select {software_type.value.title()} Executable",
            "", "Executable Files (*.exe);;All Files (*)")
        
        if file_path:
            self.software_paths[software_type].setText(file_path)
    
    def test_software(self, software_type: SoftwareType):
        """Test if software is working correctly."""
        path = self.software_paths[software_type].text()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Test Failed", 
                               f"{software_type.value.title()} executable not found.")
            return
        
        # Import here to avoid circular imports
        from ..processing.render_engines import create_render_engine
        
        try:
            engine = create_render_engine(software_type, path)
            if engine and engine.is_available():
                version = engine.get_version()
                QMessageBox.information(self, "Test Successful",
                                       f"{software_type.value.title()} is working correctly.\n"
                                       f"Version: {version}")
            else:
                QMessageBox.warning(self, "Test Failed",
                                   f"{software_type.value.title()} failed to respond correctly.")
        except Exception as e:
            QMessageBox.critical(self, "Test Error",
                               f"Error testing {software_type.value.title()}:\n{str(e)}")
    
    def browse_project_dir(self):
        """Browse for default project directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Default Project Directory")
        if dir_path:
            self.project_dir.setText(dir_path)
    
    def browse_output_dir(self):
        """Browse for default output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Default Output Directory")
        if dir_path:
            self.default_output.setText(dir_path)
    
    def browse_temp_dir(self):
        """Browse for temporary directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Temporary Directory")
        if dir_path:
            self.temp_dir.setText(dir_path)
    
    def browse_archive_dir(self):
        """Browse for archive directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Archive Directory")
        if dir_path:
            self.archive_dir.setText(dir_path)
    
    def auto_detect_software(self):
        """Automatically detect installed software."""
        from ..processing.render_engines import detect_available_software
        
        detected_software = detect_available_software()
        detected_count = 0
        
        for software_type, version in detected_software.items():
            path_input = self.software_paths.get(software_type)
            if path_input and not path_input.text():
                # Try to find the actual executable path
                common_paths = self._get_common_software_paths(software_type)
                for path in common_paths:
                    if os.path.exists(path):
                        path_input.setText(path)
                        detected_count += 1
                        break
        
        self.refresh_software_status()
        
        if detected_count > 0:
            QMessageBox.information(self, "Auto-Detection Complete",
                                   f"Found {detected_count} software installation(s).")
        else:
            QMessageBox.information(self, "Auto-Detection Complete",
                                   "No software installations found in common locations.")
    
    def _get_common_software_paths(self, software_type: SoftwareType) -> list:
        """Get common installation paths for software."""
        paths = {
            SoftwareType.BLENDER: [
                r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe"
            ],
            SoftwareType.MAYA: [
                r"C:\Program Files\Autodesk\Maya2024\bin\maya.exe",
                r"C:\Program Files\Autodesk\Maya2023\bin\maya.exe",
                r"C:\Program Files\Autodesk\Maya2022\bin\maya.exe"
            ],
            SoftwareType.UNREAL: [
                r"C:\Program Files\Epic Games\UE_5.3\Engine\Binaries\Win64\UnrealEditor.exe",
                r"C:\Program Files\Epic Games\UE_5.2\Engine\Binaries\Win64\UnrealEditor.exe",
                r"C:\Program Files\Epic Games\UE_5.1\Engine\Binaries\Win64\UnrealEditor.exe"
            ],
            SoftwareType.CINEMA4D: [
                r"C:\Program Files\Maxon Cinema 4D 2024\cinema4d.exe",
                r"C:\Program Files\Maxon Cinema 4D R25\cinema4d.exe",
                r"C:\Program Files\MAXON\Cinema 4D R23\cinema4d.exe"
            ]
        }
        return paths.get(software_type, [])
    
    def refresh_software_status(self):
        """Refresh the software status display."""
        from ..processing.render_engines import detect_available_software
        
        try:
            available_software = detect_available_software()
            
            status_text = "Software Detection Status:\n\n"
            for software_type in SoftwareType:
                if (software_type in available_software):
                    version = available_software[software_type]
                    status_text += f"✓ {software_type.value.title()}: {version}\n"
                else:
                    status_text += f"✗ {software_type.value.title()}: Not detected\n"
            
            self.software_status.setPlainText(status_text)
            
        except Exception as e:
            self.software_status.setPlainText(f"Error detecting software: {str(e)}")
    
    def validate_settings(self):
        """Validate current settings."""
        errors = []
        warnings = []
        
        # Validate software paths
        for software_type, path_input in self.software_paths.items():
            path = path_input.text().strip()
            if path and not os.path.exists(path):
                errors.append(f"{software_type.value.title()} executable not found: {path}")
        
        # Validate directories
        directories = {
            "Project": self.project_dir.text(),
            "Output": self.default_output.text(),
            "Temporary": self.temp_dir.text(),
            "Archive": self.archive_dir.text()
        }
        
        for dir_name, dir_path in directories.items():
            if dir_path and not os.path.exists(dir_path):
                warnings.append(f"{dir_name} directory does not exist: {dir_path}")
        
        # Performance validation
        if self.max_concurrent.value() > 4:
            warnings.append("High concurrent job count may affect system performance")
        
        if self.memory_limit.value() > 0 and self.memory_limit.value() < 1024:
            warnings.append("Memory limit is very low, may cause render failures")
        
        # Show validation results
        if errors:
            QMessageBox.critical(self, "Validation Errors",
                               f"Found {len(errors)} error(s):\n\n" + "\n".join(errors))
        elif warnings:
            QMessageBox.warning(self, "Validation Warnings",
                               f"Found {len(warnings)} warning(s):\n\n" + "\n".join(warnings))
        else:
            QMessageBox.information(self, "Validation Successful",
                                   "All settings are valid!")
    
    def load_settings(self):
        """Load settings from JSON config file."""
        settings_data = {}
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    settings_data = json.load(f)
            except Exception as e:
                logger.error("Error loading config.json: %s", e)
        
        # Load Software Settings
        software_settings = settings_data.get("software", {})
        for software_type, path_input in self.software_paths.items():
            path = software_settings.get(software_type.value, "")
            # Fallback to QSettings if JSON is empty
            if not path:
                path = self.settings.value(f"Software/{software_type.value}_path", "")
            path_input.setText(path)
        
        self.timeout_minutes.setValue(int(software_settings.get("timeout_minutes", 60)))
        self.memory_limit.setValue(int(software_settings.get("memory_limit", 4096)))
        self.verify_software.setChecked(bool(software_settings.get("verify_software", True)))
        
        # Load Directories
        dir_settings = settings_data.get("directories", {})
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        
        self.project_dir.setText(dir_settings.get("project_dir", project_root))
        self.default_output.setText(dir_settings.get("output_dir", os.path.join(project_root, "output")))
        
        import tempfile
        self.temp_dir.setText(dir_settings.get("temp_dir", tempfile.gettempdir()))
        self.archive_dir.setText(dir_settings.get("archive_dir", os.path.join(project_root, "archive")))
        
        self.auto_create_dirs.setChecked(bool(dir_settings.get("auto_create_dirs", True)))
        self.organize_by_date.setChecked(bool(dir_settings.get("organize_by_date", False)))
        self.organize_by_project.setChecked(bool(dir_settings.get("organize_by_project", True)))
        self.backup_projects.setChecked(bool(dir_settings.get("backup_projects", False)))
        self.max_backups.setValue(int(dir_settings.get("max_backups", 5)))
        
        # Load other categories
        self.load_performance_settings(settings_data.get("performance", {}))
        self.load_ui_settings(settings_data.get("ui", {}))
        self.load_advanced_settings(settings_data.get("advanced", {}))
        
        # Refresh software status after loading
        self.refresh_software_status()
    
    def load_performance_settings(self, settings):
        """Load performance-related settings."""
        self.max_concurrent.setValue(int(settings.get("max_concurrent", 1)))
        self.cpu_priority.setCurrentText(settings.get("cpu_priority", "Normal"))
        self.use_gpu.setChecked(bool(settings.get("use_gpu", True)))
        self.thread_count.setValue(int(settings.get("thread_count", 0)))
        
        self.auto_start.setChecked(bool(settings.get("auto_start", False)))
        self.auto_retry.setChecked(bool(settings.get("auto_retry", False)))
        self.max_retries.setValue(int(settings.get("max_retries", 3)))
        self.pause_on_error.setChecked(bool(settings.get("pause_on_error", False)))
        self.save_queue_state.setChecked(bool(settings.get("save_queue_state", True)))
        
        self.default_resolution.setCurrentText(settings.get("default_resolution", "1920x1080 (1080p)"))
        self.default_format.setCurrentText(settings.get("default_format", "PNG"))
        self.default_quality.setValue(int(settings.get("default_quality", 85)))
        
        self.ui_update_interval.setValue(int(settings.get("ui_update_interval", 1000)))
        self.progress_update_interval.setValue(int(settings.get("progress_update_interval", 500)))
        self.cache_preview_images.setChecked(bool(settings.get("cache_preview_images", True)))
        self.max_cache_size.setValue(int(settings.get("max_cache_size", 1000)))
        self.cleanup_on_exit.setChecked(bool(settings.get("cleanup_on_exit", True)))
        
        self.monitor_cpu.setChecked(bool(settings.get("monitor_cpu", True)))
        self.monitor_memory.setChecked(bool(settings.get("monitor_memory", True)))
        self.monitor_gpu.setChecked(bool(settings.get("monitor_gpu", False)))
        self.log_performance.setChecked(bool(settings.get("log_performance", False)))
    
    def load_ui_settings(self, settings):
        """Load UI-related settings."""
        # Load theme and apply it
        theme = settings.get("theme", "Dark")
        self.theme.setCurrentText(theme)
        self.apply_theme(theme)
        
        # Load font size and apply it
        font_size = int(settings.get("font_size", 10))
        self.font_size.setValue(font_size)
        self.apply_font_size(font_size)
        
        self.show_tooltips.setChecked(bool(settings.get("show_tooltips", True)))
        self.animate_ui.setChecked(bool(settings.get("animate_ui", True)))
        
        self.confirm_deletions.setChecked(bool(settings.get("confirm_deletions", True)))
        self.remember_window_state.setChecked(bool(settings.get("remember_window_state", True)))
        self.auto_save_workspace.setChecked(bool(settings.get("auto_save_workspace", True)))
        self.auto_save_interval.setValue(int(settings.get("auto_save_interval", 300)))
        
        self.notify_completion.setChecked(bool(settings.get("notify_completion", True)))
        self.notify_errors.setChecked(bool(settings.get("notify_errors", True)))
        self.notify_queue_empty.setChecked(bool(settings.get("notify_queue_empty", False)))
        self.sound_notifications.setChecked(bool(settings.get("sound_notifications", False)))
        self.system_tray.setChecked(bool(settings.get("system_tray", False)))
    
    def load_advanced_settings(self, settings):
        """Load advanced settings."""
        self.log_level.setCurrentText(settings.get("log_level", "INFO"))
        self.save_logs.setChecked(bool(settings.get("save_logs", True)))
        self.max_log_files.setValue(int(settings.get("max_log_files", 10)))
        self.log_rotation_size.setValue(int(settings.get("log_rotation_size", 10)))
        
        self.debug_mode.setChecked(bool(settings.get("debug_mode", False)))
        self.experimental_features.setChecked(bool(settings.get("experimental_features", False)))
        self.telemetry_enabled.setChecked(bool(settings.get("telemetry_enabled", True)))
        self.crash_reporting.setChecked(bool(settings.get("crash_reporting", True)))
        
        self.check_updates.setChecked(bool(settings.get("check_updates", True)))
        self.auto_update.setChecked(bool(settings.get("auto_update", False)))
        self.update_channel.setCurrentText(settings.get("update_channel", "Stable"))
        
        self.proxy_enabled.setChecked(bool(settings.get("proxy_enabled", False)))
        self.proxy_host.setText(settings.get("proxy_host", ""))
        self.proxy_port.setValue(int(settings.get("proxy_port", 8080)))
        self.local_ai_model_path.setText(settings.get("local_ai_model_path", ""))
        self.api_key_input.setText(settings.get("api_key", ""))
    
    def save_performance_settings(self):
        """Save performance-related settings."""
        self.settings.beginGroup("Performance")
        self.settings.setValue("max_concurrent", self.max_concurrent.value())
        self.settings.setValue("cpu_priority", self.cpu_priority.currentText())
        self.settings.setValue("use_gpu", self.use_gpu.isChecked())
        self.settings.setValue("thread_count", self.thread_count.value())
        
        self.settings.setValue("auto_start", self.auto_start.isChecked())
        self.settings.setValue("auto_retry", self.auto_retry.isChecked())
        self.settings.setValue("max_retries", self.max_retries.value())
        self.settings.setValue("pause_on_error", self.pause_on_error.isChecked())
        self.settings.setValue("save_queue_state", self.save_queue_state.isChecked())
        
        self.settings.setValue("default_resolution", self.default_resolution.currentText())
        self.settings.setValue("default_format", self.default_format.currentText())
        self.settings.setValue("default_quality", self.default_quality.value())
        
        self.settings.setValue("ui_update_interval", self.ui_update_interval.value())
        self.settings.setValue("progress_update_interval", self.progress_update_interval.value())
        self.settings.setValue("cache_preview_images", self.cache_preview_images.isChecked())
        self.settings.setValue("max_cache_size", self.max_cache_size.value())
        self.settings.setValue("cleanup_on_exit", self.cleanup_on_exit.isChecked())
        
        self.settings.setValue("monitor_cpu", self.monitor_cpu.isChecked())
        self.settings.setValue("monitor_memory", self.monitor_memory.isChecked())
        self.settings.setValue("monitor_gpu", self.monitor_gpu.isChecked())
        self.settings.setValue("log_performance", self.log_performance.isChecked())
        self.settings.endGroup()

    def save_ui_settings(self):
        """Save UI settings."""
        self.settings.beginGroup("UI")
        self.settings.setValue("theme", self.theme.currentText())
        self.settings.setValue("font_size", self.font_size.value())
        self.settings.setValue("show_tooltips", self.show_tooltips.isChecked())
        self.settings.setValue("animate_ui", self.animate_ui.isChecked())
        self.settings.setValue("confirm_deletions", self.confirm_deletions.isChecked())
        self.settings.setValue("remember_window_state", self.remember_window_state.isChecked())
        self.settings.setValue("auto_save_workspace", self.auto_save_workspace.isChecked())
        self.settings.setValue("auto_save_interval", self.auto_save_interval.value())
        self.settings.setValue("notify_completion", self.notify_completion.isChecked())
        self.settings.setValue("notify_errors", self.notify_errors.isChecked())
        self.settings.setValue("notify_queue_empty", self.notify_queue_empty.isChecked())
        self.settings.setValue("sound_notifications", self.sound_notifications.isChecked())
        self.settings.setValue("system_tray", self.system_tray.isChecked())
        self.settings.endGroup()

    def save_settings(self, show_confirmation=True):
        """Save current settings to JSON config file."""
        settings_data = self._collect_all_settings()
        
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(settings_data, f, indent=2)
            
            # Also save to QSettings for legacy support/backup
            self._save_to_qsettings()
            
            # Emit signal that settings changed
            self.settings_changed.emit()
            
            if show_confirmation:
                QMessageBox.information(self, "Settings Saved",
                                       "Settings have been saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed",
                               f"Failed to save settings: {str(e)}")

    def _save_to_qsettings(self):
        """Save current settings to QSettings (backup)."""
        # Save software settings
        self.settings.beginGroup("Software")
        for software_type, path_input in self.software_paths.items():
            self.settings.setValue(f"{software_type.value}_path", path_input.text())
        
        self.settings.setValue("timeout_minutes", self.timeout_minutes.value())
        self.settings.setValue("memory_limit", self.memory_limit.value())
        self.settings.setValue("verify_software", self.verify_software.isChecked())
        self.settings.endGroup()
        
        # Save directories
        self.settings.beginGroup("Directories")
        self.settings.setValue("project_dir", self.project_dir.text())
        self.settings.setValue("output_dir", self.default_output.text())
        self.settings.setValue("temp_dir", self.temp_dir.text())
        self.settings.setValue("archive_dir", self.archive_dir.text())
        self.settings.setValue("auto_create_dirs", self.auto_create_dirs.isChecked())
        self.settings.setValue("organize_by_date", self.organize_by_date.isChecked())
        self.settings.setValue("organize_by_project", self.organize_by_project.isChecked())
        self.settings.setValue("backup_projects", self.backup_projects.isChecked())
        self.settings.setValue("max_backups", self.max_backups.value())
        self.settings.endGroup()
        
        # Save other categories (simplified for backup)
        self.settings.beginGroup("UI")
        self.settings.setValue("theme", self.theme.currentText())
        self.settings.endGroup()
    
    def save_advanced_settings(self):
        """Save advanced settings."""
        self.settings.beginGroup("Advanced")
        self.settings.setValue("log_level", self.log_level.currentText())
        self.settings.setValue("save_logs", self.save_logs.isChecked())
        self.settings.setValue("max_log_files", self.max_log_files.value())
        self.settings.setValue("log_rotation_size", self.log_rotation_size.value())
        self.settings.setValue("debug_mode", self.debug_mode.isChecked())
        self.settings.setValue("experimental_features", self.experimental_features.isChecked())
        self.settings.setValue("telemetry_enabled", self.telemetry_enabled.isChecked())
        self.settings.setValue("crash_reporting", self.crash_reporting.isChecked())
        self.settings.setValue("check_updates", self.check_updates.isChecked())
        self.settings.setValue("auto_update", self.auto_update.isChecked())
        self.settings.setValue("update_channel", self.update_channel.currentText())
        self.settings.setValue("proxy_enabled", self.proxy_enabled.isChecked())
        self.settings.setValue("proxy_host", self.proxy_host.text())
        self.settings.setValue("proxy_port", self.proxy_port.value())
        self.settings.setValue("local_ai_model_path", self.local_ai_model_path.text())
        self.settings.setValue("api_key", self.api_key_input.text())
        self.settings.endGroup()
        
        # Update telemetry manager
        try:
            from ..utils.telemetry import get_telemetry
            get_telemetry().update_settings()
        except Exception as e:
            logger.warning("Failed to update telemetry settings: %s", e)
    
    def export_settings(self):
        """Export settings to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Settings", "renderfox_settings.json",
            "JSON Files (*.json);;All Files (*)")
        
        if file_path:
            try:
                settings_data = self._collect_all_settings()
                with open(file_path, 'w') as f:
                    json.dump(settings_data, f, indent=2)
                
                QMessageBox.information(self, "Export Successful",
                                       f"Settings exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed",
                                   f"Failed to export settings: {str(e)}")
    
    def import_settings(self):
        """Import settings from a JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Settings", "",
            "JSON Files (*.json);;All Files (*)")
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    settings_data = json.load(f)
                
                self._apply_imported_settings(settings_data)
                QMessageBox.information(self, "Import Successful",
                                       f"Settings imported from {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Import Failed",
                                   f"Failed to import settings: {str(e)}")
    
    def _collect_all_settings(self) -> dict:
        """Collect all current settings into a dictionary."""
        settings_data = {
            "software": {},
            "directories": {},
            "performance": {},
            "ui": {},
            "advanced": {}
        }
        
        # Collect software settings
        for software_type, path_input in self.software_paths.items():
            settings_data["software"][software_type.value] = path_input.text()
        
        settings_data["software"]["timeout_minutes"] = self.timeout_minutes.value()
        settings_data["software"]["memory_limit"] = self.memory_limit.value()
        settings_data["software"]["verify_software"] = self.verify_software.isChecked()
        
        # Collect directories
        settings_data["directories"]["project_dir"] = self.project_dir.text()
        settings_data["directories"]["output_dir"] = self.default_output.text()
        settings_data["directories"]["temp_dir"] = self.temp_dir.text()
        settings_data["directories"]["archive_dir"] = self.archive_dir.text()
        settings_data["directories"]["auto_create_dirs"] = self.auto_create_dirs.isChecked()
        settings_data["directories"]["organize_by_date"] = self.organize_by_date.isChecked()
        settings_data["directories"]["organize_by_project"] = self.organize_by_project.isChecked()
        settings_data["directories"]["backup_projects"] = self.backup_projects.isChecked()
        settings_data["directories"]["max_backups"] = self.max_backups.value()
        
        # Collect performance settings
        perf = settings_data["performance"]
        perf["max_concurrent"] = self.max_concurrent.value()
        perf["cpu_priority"] = self.cpu_priority.currentText()
        perf["use_gpu"] = self.use_gpu.isChecked()
        perf["thread_count"] = self.thread_count.value()
        perf["auto_start"] = self.auto_start.isChecked()
        perf["auto_retry"] = self.auto_retry.isChecked()
        perf["max_retries"] = self.max_retries.value()
        perf["pause_on_error"] = self.pause_on_error.isChecked()
        perf["save_queue_state"] = self.save_queue_state.isChecked()
        perf["default_resolution"] = self.default_resolution.currentText()
        perf["default_format"] = self.default_format.currentText()
        perf["default_quality"] = self.default_quality.value()
        perf["ui_update_interval"] = self.ui_update_interval.value()
        perf["progress_update_interval"] = self.progress_update_interval.value()
        perf["cache_preview_images"] = self.cache_preview_images.isChecked()
        perf["max_cache_size"] = self.max_cache_size.value()
        perf["cleanup_on_exit"] = self.cleanup_on_exit.isChecked()
        perf["monitor_cpu"] = self.monitor_cpu.isChecked()
        perf["monitor_memory"] = self.monitor_memory.isChecked()
        perf["monitor_gpu"] = self.monitor_gpu.isChecked()
        perf["log_performance"] = self.log_performance.isChecked()
        
        # Collect UI settings
        ui = settings_data["ui"]
        ui["theme"] = self.theme.currentText()
        ui["font_size"] = self.font_size.value()
        ui["show_tooltips"] = self.show_tooltips.isChecked()
        ui["animate_ui"] = self.animate_ui.isChecked()
        ui["confirm_deletions"] = self.confirm_deletions.isChecked()
        ui["remember_window_state"] = self.remember_window_state.isChecked()
        ui["auto_save_workspace"] = self.auto_save_workspace.isChecked()
        ui["auto_save_interval"] = self.auto_save_interval.value()
        ui["notify_completion"] = self.notify_completion.isChecked()
        ui["notify_errors"] = self.notify_errors.isChecked()
        ui["notify_queue_empty"] = self.notify_queue_empty.isChecked()
        ui["sound_notifications"] = self.sound_notifications.isChecked()
        ui["system_tray"] = self.system_tray.isChecked()
        
        # Collect advanced settings
        adv = settings_data["advanced"]
        adv["log_level"] = self.log_level.currentText()
        adv["save_logs"] = self.save_logs.isChecked()
        adv["max_log_files"] = self.max_log_files.value()
        adv["log_rotation_size"] = self.log_rotation_size.value()
        adv["debug_mode"] = self.debug_mode.isChecked()
        adv["experimental_features"] = self.experimental_features.isChecked()
        adv["telemetry_enabled"] = self.telemetry_enabled.isChecked()
        adv["crash_reporting"] = self.crash_reporting.isChecked()
        adv["check_updates"] = self.check_updates.isChecked()
        adv["auto_update"] = self.auto_update.isChecked()
        adv["update_channel"] = self.update_channel.currentText()
        adv["proxy_enabled"] = self.proxy_enabled.isChecked()
        adv["proxy_host"] = self.proxy_host.text()
        adv["proxy_port"] = self.proxy_port.value()
        adv["local_ai_model_path"] = self.local_ai_model_path.text()
        adv["api_key"] = self.api_key_input.text()
        
        return settings_data
    
    def _apply_imported_settings(self, settings_data: dict):
        """Apply imported settings to the UI controls."""
        # Apply software settings
        if "software" in settings_data:
            software_settings = settings_data["software"]
            for software_type, path_input in self.software_paths.items():
                if software_type.value in software_settings:
                    path_input.setText(software_settings[software_type.value])
            
            if "timeout_minutes" in software_settings:
                self.timeout_minutes.setValue(int(software_settings["timeout_minutes"]))
            if "memory_limit" in software_settings:
                self.memory_limit.setValue(int(software_settings["memory_limit"]))
            if "verify_software" in software_settings:
                self.verify_software.setChecked(bool(software_settings["verify_software"]))
        
        # Apply directories
        if "directories" in settings_data:
            dirs = settings_data["directories"]
            self.project_dir.setText(dirs.get("project_dir", ""))
            self.default_output.setText(dirs.get("output_dir", ""))
            self.temp_dir.setText(dirs.get("temp_dir", ""))
            self.archive_dir.setText(dirs.get("archive_dir", ""))
            self.auto_create_dirs.setChecked(bool(dirs.get("auto_create_dirs", True)))
            self.organize_by_date.setChecked(bool(dirs.get("organize_by_date", False)))
            self.organize_by_project.setChecked(bool(dirs.get("organize_by_project", True)))
            self.backup_projects.setChecked(bool(dirs.get("backup_projects", False)))
            self.max_backups.setValue(int(dirs.get("max_backups", 5)))
            
        # Apply performance settings
        if "performance" in settings_data:
            self.load_performance_settings(settings_data["performance"])
            
        # Apply UI settings
        if "ui" in settings_data:
            self.load_ui_settings(settings_data["ui"])
            
        # Apply advanced settings
        if "advanced" in settings_data:
            self.load_advanced_settings(settings_data["advanced"])
    
    def reset_settings(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(self, "Reset Settings",
                                   "Are you sure you want to reset all settings to defaults?\n"
                                   "This cannot be undone.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            # Clear QSettings
            self.settings.clear()
            
            # Reset all UI controls to defaults
            for path_input in self.software_paths.values():
                path_input.clear()
            
            # Reload default values
            self.load_settings()
            
            QMessageBox.information(self, "Settings Reset",
                                   "All settings have been reset to defaults.")
    
    def get_current_settings(self) -> dict:
        """Get current settings as a dictionary for use by other components."""
        return self._collect_all_settings()
    
    def apply_theme(self, theme_name):
        """Apply the selected theme to the application."""
        try:
            app = QApplication.instance()
            if app is None:
                return
            
            stylesheet = get_theme_stylesheet(theme_name)
            app.setStyleSheet(stylesheet)
            
            # Also update any open top-level windows
            for widget in app.topLevelWidgets():
                if widget.isWindow():
                    widget.setStyleSheet(stylesheet)
            
            # Emit signal so other components can update
            self.theme_changed.emit(theme_name)
            
        except Exception as e:
            logger.warning("Error applying theme: %s", e)
    
    def apply_dark_theme(self, app):
        """Apply dark theme stylesheet."""
        stylesheet = get_theme_stylesheet("Dark")
        app.setStyleSheet(stylesheet)
    
    def apply_light_theme(self, app):
        """Apply light theme stylesheet."""
        stylesheet = get_theme_stylesheet("Light")
        app.setStyleSheet(stylesheet)
    
    def apply_auto_theme(self, app):
        """Apply theme based on system settings."""
        stylesheet = get_theme_stylesheet("Auto")
        app.setStyleSheet(stylesheet)
    
    def apply_font_size(self, size):
        """Apply font size changes to the application."""
        try:
            app = QApplication.instance()
            if app is None:
                return
            
            font = app.font()
            font.setPointSize(size)
            app.setFont(font)
            
        except Exception as e:
            logger.warning("Error applying font size: %s", e)
