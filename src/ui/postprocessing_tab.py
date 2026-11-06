"""
Post-processing tab for managing rendered output processing.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QPushButton, QFileDialog, QFormLayout,
                             QCheckBox, QComboBox, QSlider, QSpinBox, QLineEdit,
                             QProgressBar, QTextEdit, QTabWidget, QListWidget,
                             QListWidgetItem, QMessageBox, QSplitter, QFrame,
                             QDoubleSpinBox, QColorDialog, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSettings
from src.core.worker_base import SafeWorker
from PyQt6.QtGui import QFont, QPixmap, QColor
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import threading

from ..core.models import PostProcessingSettings, RenderJob
from ..utils.run_teardown import drain_attributes
from ..processing.postprocessor import (PostProcessor, get_post_processing_presets, 
                                      estimate_processing_time, PostProcessingResult)
from .icon_provider import get_icon


class PostProcessingWorker(SafeWorker):
    """Worker thread for post-processing operations."""
    
    progress_updated = pyqtSignal(int, str)
    processing_completed = pyqtSignal(object)  # PostProcessingResult    
    def __init__(self, job: RenderJob, settings: PostProcessingSettings, output_files: List[str]):
        super().__init__()
        self.job = job
        self.settings = settings
        self.output_files = output_files
        self.processor = PostProcessor()
        self._cancel_event = threading.Event()
    
    def request_cancel(self):
        """Request cooperative cancellation of the processing."""
        self._cancel_event.set()
    
    def safe_run(self):
        """Execute post-processing in background thread."""
        self.progress_updated.emit(10, "Initializing post-processing...")
        
        # Estimate total time for progress tracking
        estimated_time = estimate_processing_time(self.output_files, self.settings)
        
        self.progress_updated.emit(20, "Processing files...")
        
        # Execute post-processing with progress callback and cancel support
        result = self.processor.process_job_output(
            self.job,
            self.settings,
            self.output_files,
            progress_cb=lambda pct, msg: self.progress_updated.emit(pct, msg),
            cancel_event=self._cancel_event
        )
        
        # If cancelled, ensure a clear message appended
        if self._cancel_event.is_set():
            if hasattr(result, 'errors'):
                result.errors.append("Processing was cancelled by user.")
        
        self.progress_updated.emit(100, "Post-processing completed!")
        self.processing_completed.emit(result)
        


class PostProcessingTab(QWidget):
    """Enhanced post-processing tab with full functionality."""
    
    processing_started = pyqtSignal()
    processing_completed = pyqtSignal(object)
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.current_settings = PostProcessingSettings()
        self.processor = PostProcessor()
        self.worker = None
        self.selected_files = []
        self.preview_files = []
        # Create main splitter
        # Initialize layout
        layout = QVBoxLayout(self)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter)
        
        # Left panel - Settings and controls
        left_panel = self.create_left_panel()
        self.splitter.addWidget(left_panel)
        
        # Right panel - Preview and results
        right_panel = self.create_right_panel()
        self.splitter.addWidget(right_panel)
        
        # Set splitter proportions
        self.splitter.setSizes([400, 800])
        
        # Setup preview timer
        self.setup_preview_timer()
        
    def load_file(self, file_path):
        """Load a file for post-processing."""
        if not os.path.exists(file_path):
            return
            
        if file_path not in self.selected_files:
            self.selected_files.append(file_path)
            if hasattr(self, 'file_list'):
                self.file_list.addItem(os.path.basename(file_path))
            self.update_file_info()
            self.update_preview_files()
            self.update_button_states()
    
    def create_left_panel(self) -> QWidget:
        """Create the left control panel."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # File selection section
        self.create_file_selection(layout)
        
        # Settings tabs
        self.create_settings_tabs(layout)
        
        # Preset management
        self.create_preset_section(layout)
        
        # Action buttons
        self.create_action_buttons(layout)
        
        scroll.setWidget(panel)
        return scroll
    
    def create_file_selection(self, layout: QVBoxLayout):
        """Create file selection section."""
        from .icon_provider import get_icon
        file_group = QGroupBox("Input Files")
        file_layout = QVBoxLayout(file_group)
        
        # File list
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(100)
        self.file_list.setMaximumHeight(140)
        self.file_list.itemSelectionChanged.connect(self.on_file_selection_changed)
        file_layout.addWidget(self.file_list)
        
        # File action buttons
        file_buttons = QHBoxLayout()
        
        self.add_files_btn = QPushButton("Add Files")
        self.add_files_btn.setIcon(get_icon("add"))
        self.add_files_btn.clicked.connect(self.add_files)
        
        self.add_folder_btn = QPushButton("Add Folder")
        self.add_folder_btn.setIcon(get_icon("folder"))
        self.add_folder_btn.clicked.connect(self.add_folder)
        
        self.remove_files_btn = QPushButton("Remove Selected")
        self.remove_files_btn.setIcon(get_icon("delete"))
        self.remove_files_btn.clicked.connect(self.remove_selected_files)
        self.remove_files_btn.setEnabled(False)
        
        self.clear_files_btn = QPushButton("Clear All")
        self.clear_files_btn.setIcon(get_icon("clean"))
        self.clear_files_btn.clicked.connect(self.clear_files)
        
        file_buttons.addWidget(self.add_files_btn)
        file_buttons.addWidget(self.add_folder_btn)
        file_buttons.addWidget(self.remove_files_btn)
        file_buttons.addWidget(self.clear_files_btn)
        
        file_layout.addLayout(file_buttons)
        
        # File info
        self.file_info_label = QLabel("No files selected")
        self.file_info_label.setStyleSheet("color: #8c93a8; font-size: 8.5pt;")
        file_layout.addWidget(self.file_info_label)
        
        layout.addWidget(file_group)
    
    def create_settings_tabs(self, layout: QVBoxLayout):
        """Create settings tab widget."""
        self.settings_tabs = QTabWidget()
        
        # Denoising tab
        self.create_denoising_tab()
        
        # Watermarking tab
        self.create_watermarking_tab()
        
        # Organization tab
        self.create_organization_tab()
        
        # Advanced tab
        self.create_advanced_tab()
        
        layout.addWidget(self.settings_tabs)
    
    def create_denoising_tab(self):
        """Create the denoising settings tab."""
        denoising_widget = QWidget()
        layout = QVBoxLayout(denoising_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Enable denoising
        self.enable_denoising = QCheckBox("Enable image denoising")
        self.enable_denoising.toggled.connect(self.update_settings)
        layout.addWidget(self.enable_denoising)
        
        # Denoising settings frame
        self.denoising_frame = QFrame()
        denoising_layout = QFormLayout(self.denoising_frame)
        denoising_layout.setVerticalSpacing(10)
        denoising_layout.setHorizontalSpacing(16)
        
        # Denoising method
        self.denoise_method = QComboBox()
        self.denoise_method.addItems([
            "OpenCV Non-Local Means",
            "OpenCV Gaussian", 
            "Bilateral Filter",
            "OpenImageDenoise (OIDN)"
        ])
        self.denoise_method.currentTextChanged.connect(self.update_settings)
        denoising_layout.addRow("Method:", self.denoise_method)
        
        # Denoising strength
        strength_layout = QHBoxLayout()
        self.denoise_strength = QSlider(Qt.Orientation.Horizontal)
        self.denoise_strength.setRange(1, 100)
        self.denoise_strength.setValue(50)
        self.denoise_strength.valueChanged.connect(self.update_settings)
        self.denoise_strength.valueChanged.connect(self.update_strength_label)
        
        self.strength_label = QLabel("50%")
        strength_layout.addWidget(self.denoise_strength)
        strength_layout.addWidget(self.strength_label)
        denoising_layout.addRow("Strength:", strength_layout)
        
        # Preserve details
        self.preserve_details = QCheckBox("Preserve original files")
        self.preserve_details.setChecked(True)
        self.preserve_details.toggled.connect(self.update_settings)
        denoising_layout.addRow(self.preserve_details)
        
        # Enable/disable frame based on checkbox
        self.enable_denoising.toggled.connect(self.denoising_frame.setEnabled)
        self.denoising_frame.setEnabled(False)
        
        layout.addWidget(self.denoising_frame)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(denoising_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Denoising")
    
    def create_watermarking_tab(self):
        """Create the watermarking settings tab."""
        watermark_widget = QWidget()
        layout = QVBoxLayout(watermark_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Enable watermarking
        self.enable_watermark = QCheckBox("Add watermark to images")
        self.enable_watermark.toggled.connect(self.update_settings)
        layout.addWidget(self.enable_watermark)
        
        # Watermarking settings frame
        self.watermark_frame = QFrame()
        watermark_layout = QFormLayout(self.watermark_frame)
        watermark_layout.setVerticalSpacing(10)
        watermark_layout.setHorizontalSpacing(16)
        
        # Watermark type
        self.watermark_type = QComboBox()
        self.watermark_type.addItems(["Text", "Logo"])
        self.watermark_type.currentTextChanged.connect(self.on_watermark_type_changed)
        watermark_layout.addRow("Type:", self.watermark_type)
        
        # Text watermark settings
        self.text_watermark_frame = QFrame()
        text_layout = QFormLayout(self.text_watermark_frame)
        text_layout.setVerticalSpacing(10)
        text_layout.setHorizontalSpacing(16)
        
        self.watermark_text = QLineEdit()
        self.watermark_text.setPlaceholderText("© Your Name 2025")
        self.watermark_text.textChanged.connect(self.update_settings)
        text_layout.addRow("Text:", self.watermark_text)
        
        # Font size
        self.watermark_font_size = QSpinBox()
        self.watermark_font_size.setRange(8, 72)
        self.watermark_font_size.setValue(12)
        self.watermark_font_size.valueChanged.connect(self.update_settings)
        text_layout.addRow("Font Size:", self.watermark_font_size)
        
        # Text color
        color_layout = QHBoxLayout()
        self.watermark_color = QLineEdit("#FFFFFF")
        self.watermark_color.setMaximumWidth(80)
        self.watermark_color.textChanged.connect(self.update_settings)
        
        self.color_picker_btn = QPushButton()
        self.color_picker_btn.setIcon(get_icon("edit"))
        self.color_picker_btn.setToolTip("Pick Color")
        self.color_picker_btn.setMaximumWidth(32)
        self.color_picker_btn.clicked.connect(self.pick_watermark_color)
        
        color_layout.addWidget(self.watermark_color)
        color_layout.addWidget(self.color_picker_btn)
        color_layout.addStretch()
        text_layout.addRow("Color:", color_layout)
        
        watermark_layout.addRow(self.text_watermark_frame)
        
        # Logo watermark settings
        self.logo_watermark_frame = QFrame()
        logo_layout = QFormLayout(self.logo_watermark_frame)
        logo_layout.setVerticalSpacing(10)
        logo_layout.setHorizontalSpacing(16)
        
        logo_path_layout = QHBoxLayout()
        self.watermark_logo = QLineEdit()
        self.watermark_logo.setPlaceholderText("Select logo image...")
        self.watermark_logo.textChanged.connect(self.update_settings)
        
        self.browse_logo_btn = QPushButton("Browse...")
        self.browse_logo_btn.clicked.connect(self.browse_logo)
        
        logo_path_layout.addWidget(self.watermark_logo)
        logo_path_layout.addWidget(self.browse_logo_btn)
        logo_layout.addRow("Logo:", logo_path_layout)
        
        watermark_layout.addRow(self.logo_watermark_frame)
        self.logo_watermark_frame.hide()
        
        # Common watermark settings
        # Position
        self.watermark_position = QComboBox()
        self.watermark_position.addItems([
            "top-left", "top-right", "bottom-left", "bottom-right", "center"
        ])
        self.watermark_position.setCurrentText("bottom-right")
        self.watermark_position.currentTextChanged.connect(self.update_settings)
        watermark_layout.addRow("Position:", self.watermark_position)
        
        # Opacity
        opacity_layout = QHBoxLayout()
        self.watermark_opacity = QSlider(Qt.Orientation.Horizontal)
        self.watermark_opacity.setRange(1, 100)
        self.watermark_opacity.setValue(70)
        self.watermark_opacity.valueChanged.connect(self.update_settings)
        self.watermark_opacity.valueChanged.connect(self.update_opacity_label)
        
        self.opacity_label = QLabel("70%")
        opacity_layout.addWidget(self.watermark_opacity)
        opacity_layout.addWidget(self.opacity_label)
        watermark_layout.addRow("Opacity:", opacity_layout)
        
        # Padding
        self.watermark_padding = QSpinBox()
        self.watermark_padding.setRange(0, 100)
        self.watermark_padding.setValue(10)
        self.watermark_padding.valueChanged.connect(self.update_settings)
        watermark_layout.addRow("Padding:", self.watermark_padding)
        
        # Enable/disable frame based on checkbox
        self.enable_watermark.toggled.connect(self.watermark_frame.setEnabled)
        self.watermark_frame.setEnabled(False)
        
        layout.addWidget(self.watermark_frame)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(watermark_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Watermark")
    
    def create_organization_tab(self):
        """Create the file organization settings tab."""
        org_widget = QWidget()
        layout = QVBoxLayout(org_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Auto-organize
        self.auto_organize = QCheckBox("Automatically organize output files")
        self.auto_organize.toggled.connect(self.update_settings)
        layout.addWidget(self.auto_organize)
        
        # Organization settings frame
        self.org_frame = QFrame()
        org_layout = QFormLayout(self.org_frame)
        org_layout.setVerticalSpacing(10)
        org_layout.setHorizontalSpacing(16)
        
        # Organization options
        self.create_subfolders = QCheckBox("Create subfolders for each job")
        self.create_subfolders.setChecked(True)
        self.create_subfolders.toggled.connect(self.update_settings)
        org_layout.addRow(self.create_subfolders)
        
        self.organize_by_date = QCheckBox("Organize by date")
        self.organize_by_date.toggled.connect(self.update_settings)
        org_layout.addRow(self.organize_by_date)
        
        self.organize_by_format = QCheckBox("Organize by file format")
        self.organize_by_format.toggled.connect(self.update_settings)
        org_layout.addRow(self.organize_by_format)
        
        # Organization pattern
        self.organization_pattern = QLineEdit()
        self.organization_pattern.setPlaceholderText("{job_name}_{timestamp}")
        self.organization_pattern.textChanged.connect(self.update_settings)
        org_layout.addRow("Filename Pattern:", self.organization_pattern)
        
        # Pattern help
        pattern_help = QLabel(
            "Available variables: {job_name}, {timestamp}, {frame}, {width}, {height}, {format}"
        )
        pattern_help.setStyleSheet("color: #8c93a8; font-size: 8.5pt;")
        pattern_help.setWordWrap(True)
        org_layout.addRow(pattern_help)
        
        # Enable/disable frame
        self.auto_organize.toggled.connect(self.org_frame.setEnabled)
        self.org_frame.setEnabled(False)
        
        layout.addWidget(self.org_frame)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(org_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Organization")
    
    def create_advanced_tab(self):
        """Create the advanced settings tab."""
        advanced_widget = QWidget()
        layout = QVBoxLayout(advanced_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Cleanup settings
        cleanup_group = QGroupBox("Cleanup")
        cleanup_layout = QFormLayout(cleanup_group)
        cleanup_layout.setVerticalSpacing(10)
        cleanup_layout.setHorizontalSpacing(16)
        
        self.cleanup_temp_files = QCheckBox("Clean up temporary files after processing")
        self.cleanup_temp_files.setChecked(True)
        self.cleanup_temp_files.toggled.connect(self.update_settings)
        cleanup_layout.addRow(self.cleanup_temp_files)
        
        layout.addWidget(cleanup_group)
        
        # Archive settings
        archive_group = QGroupBox("Archive")
        archive_layout = QFormLayout(archive_group)
        archive_layout.setVerticalSpacing(10)
        archive_layout.setHorizontalSpacing(16)
        
        self.archive_old_jobs = QCheckBox("Archive old render jobs")
        self.archive_old_jobs.toggled.connect(self.update_settings)
        archive_layout.addRow(self.archive_old_jobs)
        
        self.archive_after_days = QSpinBox()
        self.archive_after_days.setRange(1, 365)
        self.archive_after_days.setValue(30)
        self.archive_after_days.setSuffix(" days")
        self.archive_after_days.valueChanged.connect(self.update_settings)
        archive_layout.addRow("Archive after:", self.archive_after_days)
        
        self.compress_archives = QCheckBox("Compress archived files")
        self.compress_archives.setChecked(True)
        self.compress_archives.toggled.connect(self.update_settings)
        archive_layout.addRow(self.compress_archives)
        
        layout.addWidget(archive_group)
        
        # Performance settings
        perf_group = QGroupBox("Performance")
        perf_layout = QFormLayout(perf_group)
        perf_layout.setVerticalSpacing(10)
        perf_layout.setHorizontalSpacing(16)
        
        self.parallel_processing = QCheckBox("Enable parallel processing")
        self.parallel_processing.setChecked(True)
        self.parallel_processing.toggled.connect(self.update_settings)
        perf_layout.addRow(self.parallel_processing)
        
        self.max_threads = QSpinBox()
        self.max_threads.setRange(1, 16)
        self.max_threads.setValue(4)
        self.max_threads.valueChanged.connect(self.update_settings)
        perf_layout.addRow("Max Threads:", self.max_threads)
        
        layout.addWidget(perf_group)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(advanced_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_tabs.addTab(scroll, "Advanced")
    
    def create_preset_section(self, layout: QVBoxLayout):
        """Create preset management section."""
        preset_group = QGroupBox("Presets")
        preset_layout = QVBoxLayout(preset_group)
        
        # Preset selection
        preset_select_layout = QHBoxLayout()
        
        self.preset_combo = QComboBox()
        self.load_presets()
        self.preset_combo.currentTextChanged.connect(self.load_preset)
        
        self.save_preset_btn = QPushButton()
        self.save_preset_btn.setIcon(get_icon("backup"))
        self.save_preset_btn.setToolTip("Save current settings as preset")
        self.save_preset_btn.setMaximumWidth(32)
        self.save_preset_btn.clicked.connect(self.save_preset)
        
        self.delete_preset_btn = QPushButton()
        self.delete_preset_btn.setIcon(get_icon("delete"))
        self.delete_preset_btn.setToolTip("Delete selected preset")
        self.delete_preset_btn.setMaximumWidth(32)
        self.delete_preset_btn.clicked.connect(self.delete_preset)
        
        preset_select_layout.addWidget(QLabel("Preset:"))
        preset_select_layout.addWidget(self.preset_combo)
        preset_select_layout.addWidget(self.save_preset_btn)
        preset_select_layout.addWidget(self.delete_preset_btn)
        
        preset_layout.addLayout(preset_select_layout)
        
        layout.addWidget(preset_group)
    
    def create_action_buttons(self, layout: QVBoxLayout):
        """Create action buttons."""
        button_layout = QHBoxLayout()
        
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setIcon(get_icon("overlays"))
        self.preview_btn.clicked.connect(self.preview_processing)
        self.preview_btn.setEnabled(False)
        
        self.process_btn = QPushButton("Start Processing")
        self.process_btn.setIcon(get_icon("play"))
        self.process_btn.setProperty("primary", "true")
        self.process_btn.clicked.connect(self.start_processing)
        self.process_btn.setEnabled(False)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(get_icon("stop"))
        self.stop_btn.clicked.connect(self.cancel_processing)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        
        button_layout.addWidget(self.preview_btn)
        button_layout.addWidget(self.process_btn)
        button_layout.addWidget(self.stop_btn)
        
        layout.addLayout(button_layout)
    
    def create_right_panel(self) -> QWidget:
        """Create the right preview and results panel.""" 
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Preview area
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        # Preview controls
        preview_controls = QHBoxLayout()
        
        self.preview_file_combo = QComboBox()
        self.preview_file_combo.currentTextChanged.connect(self.update_preview)
        
        self.auto_preview = QCheckBox("Auto Preview")
        self.auto_preview.setChecked(True)
        
        preview_controls.addWidget(QLabel("File:"))
        preview_controls.addWidget(self.preview_file_combo)
        preview_controls.addWidget(self.auto_preview)
        preview_controls.addStretch()
        
        preview_layout.addLayout(preview_controls)
        
        # Preview display
        self.preview_label = QLabel("No preview available")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        self.preview_label.setStyleSheet("border: 1px dashed #2d3142; background-color: #14151b; color: #8c93a8; border-radius: 4px;")
        preview_layout.addWidget(self.preview_label)
        
        layout.addWidget(preview_group)
        
        # Results area
        results_group = QGroupBox("Processing Results")
        results_layout = QVBoxLayout(results_group)
        
        self.results_text = QTextEdit()
        self.results_text.setMaximumHeight(150)
        self.results_text.setReadOnly(True)
        results_layout.addWidget(self.results_text)
        
        layout.addWidget(results_group)
        
        return panel
    
    def create_status_area(self, layout: QVBoxLayout):
        """Create status and progress area."""
        status_frame = QFrame()
        status_layout = QVBoxLayout(status_frame)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        status_layout.addWidget(self.status_label)
        
        layout.addWidget(status_frame)
    
    def setup_preview_timer(self):
        """Setup timer for auto-preview."""
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)
    
    # ...existing code... (keeping all the existing event handlers and methods)
    
    def add_files(self):
        """Add image files for processing."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Image Files",
            "", "Image Files (*.png *.jpg *.jpeg *.tiff *.tif *.bmp *.exr);;All Files (*)"
        )
        
        for file_path in files:
            if file_path not in self.selected_files:
                self.selected_files.append(file_path)
                item = QListWidgetItem(os.path.basename(file_path))
                item.setToolTip(file_path)
                self.file_list.addItem(item)
        
        self.update_file_info()
        self.update_preview_files()
        self.update_button_states()
    
    def add_folder(self):
        """Add all image files from a folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            image_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.exr'}
            added_count = 0
            
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in image_extensions:
                        file_path = os.path.join(root, file)
                        if file_path not in self.selected_files:
                            self.selected_files.append(file_path)
                            item = QListWidgetItem(os.path.basename(file_path))
                            item.setToolTip(file_path)
                            self.file_list.addItem(item)
                            added_count += 1
            
            if added_count > 0:
                self.update_file_info()
                self.update_preview_files()
                self.update_button_states()
                self.status_label.setText(f"Added {added_count} files from folder")
    
    def remove_selected_files(self):
        """Remove selected files from the list."""
        for item in self.file_list.selectedItems():
            row = self.file_list.row(item)
            self.file_list.takeItem(row)
            if row < len(self.selected_files):
                self.selected_files.pop(row)
        
        self.update_file_info()
        self.update_preview_files()
        self.update_button_states()
    
    def clear_files(self):
        """Clear all files."""
        self.file_list.clear()
        self.selected_files.clear()
        self.update_file_info()
        self.update_preview_files()
        self.update_button_states()
    
    def on_file_selection_changed(self):
        """Handle file selection changes."""
        selected_items = self.file_list.selectedItems()
        self.remove_files_btn.setEnabled(len(selected_items) > 0)
    
    def update_file_info(self):
        """Update file information display."""
        count = len(self.selected_files)
        if count == 0:
            self.file_info_label.setText("No files selected")
        else:
            total_size = sum(os.path.getsize(f) for f in self.selected_files if os.path.exists(f))
            size_mb = total_size / (1024 * 1024)
            estimated_time = estimate_processing_time(self.selected_files, self.current_settings)
            
            self.file_info_label.setText(
                f"{count} file(s) • {size_mb:.1f} MB • Est. {estimated_time:.1f}s processing time"
            )
    
    def update_preview_files(self):
        """Update preview file combo box."""
        self.preview_file_combo.clear()
        for file_path in self.selected_files:
            self.preview_file_combo.addItem(os.path.basename(file_path), file_path)
    
    def update_button_states(self):
        """Update button enable/disable states."""
        has_files = len(self.selected_files) > 0
        inputs_valid, _ = self.validate_inputs()
        self.preview_btn.setEnabled(has_files and inputs_valid and self.worker is None)
        self.process_btn.setEnabled(has_files and inputs_valid and (self.worker is None))
        self.stop_btn.setEnabled(self.worker is not None)
        self.stop_btn.setVisible(self.worker is not None)
    
    def on_watermark_type_changed(self, type_name: str):
        """Handle watermark type selection change."""
        if type_name == "Text":
            self.text_watermark_frame.show()
            self.logo_watermark_frame.hide()
        else:
            self.text_watermark_frame.hide()
            self.logo_watermark_frame.show()
        # Ensure proper UI update
        self.watermark_frame.update()
        self.update_settings()
    
    def pick_watermark_color(self):
        """Open color picker for watermark color."""
        color = QColorDialog.getColor(QColor(self.watermark_color.text()))
        if color.isValid():
            self.watermark_color.setText(color.name())
    
    def browse_logo(self):
        """Browse for watermark logo."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo Image",
            "", "Image Files (*.png *.jpg *.jpeg *.bmp *.svg);;All Files (*)"
        )
        if file_path:
            self.watermark_logo.setText(file_path)
    
    def update_strength_label(self, value: int):
        """Update denoising strength label."""
        self.strength_label.setText(f"{value}%")
    
    def update_opacity_label(self, value: int):
        """Update watermark opacity label."""
        self.opacity_label.setText(f"{value}%")
    
    def _set_widget_valid(self, widget: QLineEdit, valid: bool, tooltip: str = ""):
        """Apply or clear invalid style on a line edit."""
        if valid:
            widget.setStyleSheet("")
            widget.setToolTip("")
        else:
            widget.setStyleSheet("border: 1px solid #d9534f;")
            widget.setToolTip(tooltip)
    
    def validate_inputs(self) -> Tuple[bool, List[str]]:
        """Validate organization pattern and watermark logo (if needed)."""
        errors: List[str] = []
        # Validate organization pattern
        self._org_pattern_valid = True
        pattern = self.organization_pattern.text().strip()
        if self.auto_organize.isChecked() and pattern:
            try:
                dummy = {
                    'job_name': 'Job', 'timestamp': '20250101_000000', 'frame': 1,
                    'width': 1920, 'height': 1080, 'format': 'png'
                }
                # Try formatting; any KeyError/ValueError indicates invalid placeholders/braces
                _ = pattern.format(**dummy)
            except Exception as e:
                self._org_pattern_valid = False
                errors.append("Invalid filename pattern. Allowed: {job_name}, {timestamp}, {frame}, {width}, {height}, {format}.")
        self._set_widget_valid(self.organization_pattern, self._org_pattern_valid,
                               "Invalid pattern. Allowed: {job_name}, {timestamp}, {frame}, {width}, {height}, {format}.")
        
        # Validate watermark logo when logo mode selected
        self._watermark_logo_valid = True
        if self.enable_watermark.isChecked() and self.watermark_type.currentText() == "Logo":
            logo_path = self.watermark_logo.text().strip()
            if not logo_path or not os.path.exists(logo_path):
                self._watermark_logo_valid = False
                errors.append("Logo file does not exist.")
            else:
                # Try lightweight check via QPixmap
                pix = QPixmap(logo_path)
                if pix.isNull():
                    self._watermark_logo_valid = False
                    errors.append("Logo file is not a valid image.")
        self._set_widget_valid(self.watermark_logo, self._watermark_logo_valid,
                               "Provide a valid image file for the logo watermark.")
        
        all_valid = self._org_pattern_valid and self._watermark_logo_valid
        return all_valid, errors
    
    def update_settings(self):
        """Update current settings from UI controls."""
        # Update PostProcessingSettings object
        self.current_settings.apply_denoising = self.enable_denoising.isChecked()
        self.current_settings.denoise_method = self.denoise_method.currentText()
        self.current_settings.denoise_strength = self.denoise_strength.value() / 100.0
        self.current_settings.preserve_details = self.preserve_details.isChecked()
        
        self.current_settings.add_watermark = self.enable_watermark.isChecked()
        self.current_settings.watermark_text = self.watermark_text.text()
        self.current_settings.watermark_logo = self.watermark_logo.text()
        self.current_settings.watermark_position = self.watermark_position.currentText()
        self.current_settings.watermark_opacity = self.watermark_opacity.value() / 100.0
        self.current_settings.watermark_font_size = self.watermark_font_size.value()
        self.current_settings.watermark_color = self.watermark_color.text()
        self.current_settings.watermark_padding = self.watermark_padding.value()
        
        self.current_settings.auto_organize = self.auto_organize.isChecked()
        self.current_settings.create_subfolders = self.create_subfolders.isChecked()
        self.current_settings.organize_by_date = self.organize_by_date.isChecked()
        self.current_settings.organize_by_format = self.organize_by_format.isChecked()
        self.current_settings.organization_pattern = self.organization_pattern.text()
        
        self.current_settings.cleanup_temp_files = self.cleanup_temp_files.isChecked()
        self.current_settings.archive_old_jobs = self.archive_old_jobs.isChecked()
        self.current_settings.archive_after_days = self.archive_after_days.value()
        self.current_settings.compress_archives = self.compress_archives.isChecked()
        
        # Performance
        self.current_settings.parallel_processing = self.parallel_processing.isChecked()
        self.current_settings.max_threads = self.max_threads.value()
        
        # Validate inputs
        valid, errors = self.validate_inputs()
        if not valid:
            self.status_label.setText("; ".join(errors))
        
        # Update file info with new time estimate
        self.update_file_info()
        
        # Update buttons based on validation and state
        self.update_button_states()
        
        # Auto-preview if enabled
        if self.auto_preview.isChecked() and self.selected_files:
            self.preview_timer.start(500)  # Delay to avoid too frequent updates
    
    def load_presets(self):
        """Load available presets."""
        # Load built-in presets
        built_in_presets = get_post_processing_presets()
        
        # Load custom presets from settings
        self.settings.beginGroup("PostProcessingPresets")
        custom_presets = self.settings.childKeys()
        self.settings.endGroup()
        
        self.preset_combo.clear()
        self.preset_combo.addItem("-- Select Preset --")
        
        # Add built-in presets
        for name in built_in_presets.keys():
            self.preset_combo.addItem(f"[Built-in] {name.title()}")
        
        # Add custom presets
        for name in custom_presets:
            self.preset_combo.addItem(f"[Custom] {name}")
    
    def load_preset(self, preset_name: str):
        """Load a preset configuration."""
        if preset_name.startswith("-- "):
            return
        
        try:
            if preset_name.startswith("[Built-in] "):
                # Built-in preset
                name = preset_name[11:].lower()
                presets = get_post_processing_presets()
                if name in presets:
                    settings = presets[name]
                    self.apply_settings_to_ui(settings)
            elif preset_name.startswith("[Custom] "):
                # Custom preset
                name = preset_name[9:]
                self.settings.beginGroup("PostProcessingPresets")
                settings_data = self.settings.value(name, "")
                self.settings.endGroup()
                
                if settings_data:
                    import json
                    settings_dict = json.loads(settings_data)
                    settings = PostProcessingSettings(**settings_dict)
                    self.apply_settings_to_ui(settings)
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Failed to load preset: {str(e)}")
    
    def apply_settings_to_ui(self, settings: PostProcessingSettings):
        """Apply settings to UI controls."""
        # Block signals to prevent recursive updates
        widgets = [
            self.enable_denoising, self.denoise_method, self.denoise_strength,
            self.preserve_details, self.enable_watermark, self.watermark_text,
            self.watermark_position, self.watermark_opacity, self.watermark_font_size,
            self.auto_organize, self.create_subfolders, self.organize_by_date,
            self.organize_by_format, self.cleanup_temp_files, self.archive_old_jobs,
            self.watermark_logo, self.watermark_color, self.watermark_padding,
            self.organization_pattern, self.compress_archives,
            self.parallel_processing, self.max_threads
        ]
        
        for widget in widgets:
            widget.blockSignals(True)
        
        try:
            # Apply settings
            self.enable_denoising.setChecked(settings.apply_denoising)
            self.denoise_method.setCurrentText(settings.denoise_method)
            self.denoise_strength.setValue(int(settings.denoise_strength * 100))
            self.preserve_details.setChecked(settings.preserve_details)
            
            self.enable_watermark.setChecked(settings.add_watermark)
            self.watermark_text.setText(settings.watermark_text)
            self.watermark_logo.setText(getattr(settings, 'watermark_logo', ''))
            self.watermark_position.setCurrentText(settings.watermark_position)
            self.watermark_opacity.setValue(int(settings.watermark_opacity * 100))
            self.watermark_font_size.setValue(settings.watermark_font_size)
            self.watermark_color.setText(getattr(settings, 'watermark_color', '#FFFFFF'))
            self.watermark_padding.setValue(getattr(settings, 'watermark_padding', 10))
            
            self.auto_organize.setChecked(settings.auto_organize)
            self.create_subfolders.setChecked(settings.create_subfolders)
            self.organize_by_date.setChecked(settings.organize_by_date)
            self.organize_by_format.setChecked(settings.organize_by_format)
            self.organization_pattern.setText(getattr(settings, 'organization_pattern', '{job_name}_{timestamp}'))
            
            self.cleanup_temp_files.setChecked(settings.cleanup_temp_files)
            self.archive_old_jobs.setChecked(settings.archive_old_jobs)
            self.archive_after_days.setValue(getattr(settings, 'archive_after_days', 30))
            self.compress_archives.setChecked(getattr(settings, 'compress_archives', True))
            
            # Performance
            self.parallel_processing.setChecked(getattr(settings, 'parallel_processing', True))
            self.max_threads.setValue(getattr(settings, 'max_threads', 4))
            
            # Update dependent UI states
            self.denoising_frame.setEnabled(settings.apply_denoising)
            self.watermark_frame.setEnabled(settings.add_watermark)
            self.org_frame.setEnabled(settings.auto_organize)
            
        finally:
            # Re-enable signals
            for widget in widgets:
                widget.blockSignals(False)
            
            # Update current settings
            self.update_settings()
    
    def save_preset(self):
        """Save current settings as a custom preset."""
        from PyQt6.QtWidgets import QInputDialog
        
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if ok and name:
            try:
                # Convert settings to dict for JSON serialization
                settings_dict = {
                    'apply_denoising': self.current_settings.apply_denoising,
                    'denoise_method': self.current_settings.denoise_method,
                    'denoise_strength': self.current_settings.denoise_strength,
                    'preserve_details': self.current_settings.preserve_details,
                    'add_watermark': self.current_settings.add_watermark,
                    'watermark_text': self.current_settings.watermark_text,
                    'watermark_logo': self.current_settings.watermark_logo,
                    'watermark_position': self.current_settings.watermark_position,
                    'watermark_opacity': self.current_settings.watermark_opacity,
                    'watermark_font_size': self.current_settings.watermark_font_size,
                    'watermark_color': self.current_settings.watermark_color,
                    'watermark_padding': self.current_settings.watermark_padding,
                    'auto_organize': self.current_settings.auto_organize,
                    'create_subfolders': self.current_settings.create_subfolders,
                    'organize_by_date': self.organize_by_date.isChecked(),
                    'organize_by_format': self.organize_by_format.isChecked(),
                    'organization_pattern': self.current_settings.organization_pattern,
                    'cleanup_temp_files': self.current_settings.cleanup_temp_files,
                    'archive_old_jobs': self.current_settings.archive_old_jobs,
                    'archive_after_days': self.current_settings.archive_after_days,
                    'compress_archives': self.current_settings.compress_archives,
                    'parallel_processing': self.current_settings.parallel_processing,
                    'max_threads': self.current_settings.max_threads,
                }
                
                settings_json = json.dumps(settings_dict)
                
                self.settings.beginGroup("PostProcessingPresets")
                self.settings.setValue(name, settings_json)
                self.settings.endGroup()
                
                # Reload presets
                self.load_presets()
                
                QMessageBox.information(self, "Preset Saved", f"Preset '{name}' saved successfully!")
                
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save preset: {str(e)}")
    
    def delete_preset(self):
        """Delete a custom preset."""
        current_preset = self.preset_combo.currentText()
        if current_preset.startswith("[Custom] "):
            name = current_preset[9:]
            
            reply = QMessageBox.question(
                self, "Delete Preset",
                f"Are you sure you want to delete preset '{name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.settings.beginGroup("PostProcessingPresets")
                self.settings.remove(name)
                self.settings.endGroup()
                
                self.load_presets()
                QMessageBox.information(self, "Preset Deleted", f"Preset '{name}' deleted successfully!")
    
    def preview_processing(self):
        """Preview processing results on a sample file."""
        if not self.selected_files:
            return
        
        # Use first selected file for preview
        sample_file = self.selected_files[0]
        
        try:
            self.status_label.setText("Generating preview...")
            
            # Create a temporary job for preview
            from ..core.models import RenderJob, SoftwareType
            
            temp_job = RenderJob(
                name="Preview",
                project_file=sample_file,
                output_path=os.path.dirname(sample_file),
                software_type=SoftwareType.BLENDER,  # Dummy value
                resolution=(1920, 1080),
                output_format="png"
            )
            
            # Process just this one file
            result = self.processor.process_job_output(
                temp_job, self.current_settings, [sample_file]
            )
            
            if result.success:
                self.results_text.append("Preview completed successfully")
                self.results_text.append(f"Processing time: {result.processing_time:.2f}s")
                if result.processed_files:
                    self.results_text.append(f"Preview file: {result.processed_files[0]}")
                    # Auto-populate preview list with preview output
                    self.preview_file_combo.clear()
                    for f in result.processed_files:
                        self.preview_file_combo.addItem(os.path.basename(f), f)
            else:
                self.results_text.append(f"Preview failed: {', '.join(result.errors)}")
            
            self.status_label.setText("Preview completed")
            
        except Exception as e:
            self.results_text.append(f"Preview error: {str(e)}")
            self.status_label.setText("Preview failed")
    
    def start_processing(self):
        """Start processing all selected files."""
        if not self.selected_files:
            return
        
        # Create dummy job for processing
        from ..core.models import RenderJob, SoftwareType
        
        dummy_job = RenderJob(
            name=f"Batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            project_file="",
            output_path=os.path.dirname(self.selected_files[0]) if self.selected_files else "",
            software_type=SoftwareType.BLENDER,
            resolution=(1920, 1080),
            output_format="png"
        )
        
        # Start worker thread
        self.worker = PostProcessingWorker(dummy_job, self.current_settings, self.selected_files.copy())
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.processing_completed.connect(self.on_processing_completed)
        self.worker.error_occurred.connect(self.on_processing_error)
        
        # Update UI for processing state
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.process_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        
        self.processing_started.emit()
        self.worker.start()
        self.update_button_states()
    
    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Ask the organise/archive/cleanup run to stop, silence it, and wait.

        `progress_updated` drives the bar and the status line, `processing_completed`
        writes the results box and reloads the file list, and `error_occurred` reports
        into the same box - so a run that answers after the tab is destroyed writes three
        widgets that no longer exist. This worker does have a cancellation, but spelled
        `request_cancel`, which is why the helper knows the app's four spellings instead
        of one; the close uses the same verb as the Stop button rather than inventing a
        second way out. Returns the runs still owed when the wait gave up.
        """
        return len(drain_attributes(self, ('worker',), timeout_ms))

    def cancel_processing(self):
        """Request cancellation of current processing."""
        if self.worker is not None:
            self.worker.request_cancel()
            self.stop_btn.setEnabled(False)
            self.status_label.setText("Cancelling...")
    
    def on_progress_updated(self, percentage: int, message: str):
        """Handle progress updates."""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(message)
    
    def on_processing_completed(self, result: PostProcessingResult):
        """Handle processing completion."""
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.stop_btn.setEnabled(False)
        
        # Clear worker reference
        self.worker = None
        
        # Display results
        self.results_text.clear()
        
        if result.success:
            self.results_text.append("Processing completed successfully!")
            self.results_text.append(f"Processed {len(result.processed_files)} files")
            self.results_text.append(f"Processing time: {result.processing_time:.2f} seconds")
            
            size_change = result.file_size_after - result.file_size_before
            if size_change != 0:
                sign = "+" if size_change > 0 else ""
                self.results_text.append(f"Size change: {sign}{size_change / (1024*1024):.1f} MB")
            
            self.results_text.append("\nProcessed files:")
            for file_path in result.processed_files[:10]:  # Show first 10
                self.results_text.append(f"  • {os.path.basename(file_path)}")
            
            if len(result.processed_files) > 10:
                self.results_text.append(f"  ... and {len(result.processed_files) - 10} more")
            
            # Auto-populate the selected and preview lists with outputs
            self.selected_files = result.processed_files.copy()
            self.file_list.clear()
            for f in self.selected_files:
                item = QListWidgetItem(os.path.basename(f))
                item.setToolTip(f)
                self.file_list.addItem(item)
            self.update_preview_files()
            # Select first file for preview
            if self.selected_files:
                self.preview_file_combo.setCurrentIndex(0)
                self.update_preview()
            
        else:
            self.results_text.append("Processing failed!")
            self.results_text.append("\nErrors:")
            for error in result.errors:
                self.results_text.append(f"  • {error}")
        
        self.status_label.setText("Processing completed")
        self.processing_completed.emit(result)
        self.update_button_states()
    
    def on_processing_error(self, error_message: str):
        """Handle processing errors."""
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.stop_btn.setEnabled(False)
        
        # Clear worker reference
        self.worker = None
        
        self.results_text.append(f"Processing error: {error_message}")
        self.status_label.setText("Processing failed")
        
        QMessageBox.critical(self, "Processing Error", error_message)
        self.update_button_states()
    
    def update_preview(self):
        """Update preview display."""
        current_file = self.preview_file_combo.currentData()
        if not current_file or not os.path.exists(current_file):
            self.preview_label.setText("No preview available")
            return
        
        try:
            # Load and display image
            pixmap = QPixmap(current_file)
            if not pixmap.isNull():
                # Scale to fit preview area
                scaled_pixmap = pixmap.scaled(
                    self.preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled_pixmap)
            else:
                self.preview_label.setText(f"Cannot preview file type: {os.path.splitext(current_file)[1]}\nThis tab only supports image files.")
        except Exception as e:
            self.preview_label.setText(f"Preview error: {str(e)}")
    
    def load_settings(self):
        """Load settings from QSettings."""
        self.settings.beginGroup("PostProcessing")
        
        # Load basic settings with defaults
        self.enable_denoising.setChecked(self.settings.value("apply_denoising", False, bool))
        self.denoise_method.setCurrentText(self.settings.value("denoise_method", "OpenCV Non-Local Means"))
        self.denoise_strength.setValue(self.settings.value("denoise_strength", 50, int))
        self.preserve_details.setChecked(self.settings.value("preserve_details", True, bool))
        
        self.enable_watermark.setChecked(self.settings.value("add_watermark", False, bool))
        self.watermark_text.setText(self.settings.value("watermark_text", "© RenderFox 2025"))
        self.watermark_logo.setText(self.settings.value("watermark_logo", ""))
        self.watermark_position.setCurrentText(self.settings.value("watermark_position", "bottom-right"))
        self.watermark_opacity.setValue(self.settings.value("watermark_opacity", 70, int))
        self.watermark_font_size.setValue(self.settings.value("watermark_font_size", 12, int))
        self.watermark_color.setText(self.settings.value("watermark_color", "#FFFFFF"))
        self.watermark_padding.setValue(self.settings.value("watermark_padding", 10, int))
        
        self.auto_organize.setChecked(self.settings.value("auto_organize", False, bool))
        self.create_subfolders.setChecked(self.settings.value("create_subfolders", True, bool))
        self.organize_by_date.setChecked(self.settings.value("organize_by_date", False, bool))
        self.organize_by_format.setChecked(self.settings.value("organize_by_format", False, bool))
        self.organization_pattern.setText(self.settings.value("organization_pattern", "{job_name}_{timestamp}"))
        
        self.cleanup_temp_files.setChecked(self.settings.value("cleanup_temp_files", True, bool))
        self.archive_old_jobs.setChecked(self.settings.value("archive_old_jobs", False, bool))
        self.archive_after_days.setValue(self.settings.value("archive_after_days", 30, int))
        self.compress_archives.setChecked(self.settings.value("compress_archives", True, bool))
        
        # Performance
        self.parallel_processing.setChecked(self.settings.value("parallel_processing", True, bool))
        self.max_threads.setValue(self.settings.value("max_threads", 4, int))
        
        self.settings.endGroup()
        
        # Update current settings and UI states
        self.update_settings()
    
    def save_settings(self):
        """Save current settings."""
        self.settings.beginGroup("PostProcessing")
        
        self.settings.setValue("apply_denoising", self.enable_denoising.isChecked())
        self.settings.setValue("denoise_method", self.denoise_method.currentText())
        self.settings.setValue("denoise_strength", self.denoise_strength.value())
        self.settings.setValue("preserve_details", self.preserve_details.isChecked())
        
        self.settings.setValue("add_watermark", self.enable_watermark.isChecked())
        self.settings.setValue("watermark_text", self.watermark_text.text())
        self.settings.setValue("watermark_logo", self.watermark_logo.text())
        self.settings.setValue("watermark_position", self.watermark_position.currentText())
        self.settings.setValue("watermark_opacity", self.watermark_opacity.value())
        self.settings.setValue("watermark_font_size", self.watermark_font_size.value())
        self.settings.setValue("watermark_color", self.watermark_color.text())
        self.settings.setValue("watermark_padding", self.watermark_padding.value())
        
        self.settings.setValue("auto_organize", self.auto_organize.isChecked())
        self.settings.setValue("create_subfolders", self.create_subfolders.isChecked())
        self.settings.setValue("organize_by_date", self.organize_by_date.isChecked())
        self.settings.setValue("organize_by_format", self.organize_by_format.isChecked())
        self.settings.setValue("organization_pattern", self.organization_pattern.text())
        
        self.settings.setValue("cleanup_temp_files", self.cleanup_temp_files.isChecked())
        self.settings.setValue("archive_old_jobs", self.archive_old_jobs.isChecked())
        self.settings.setValue("archive_after_days", self.archive_after_days.value())
        self.settings.setValue("compress_archives", self.compress_archives.isChecked())
        
        # Performance
        self.settings.setValue("parallel_processing", self.parallel_processing.isChecked())
        self.settings.setValue("max_threads", self.max_threads.value())
        
        self.settings.endGroup()
    
    def get_current_settings(self) -> PostProcessingSettings:
        """Get current post-processing settings."""
        return self.current_settings