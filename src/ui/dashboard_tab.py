"""
Dashboard tab for job queue management.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QProgressBar, QLabel, QFileDialog, QDialog,
                             QFormLayout, QLineEdit, QComboBox, QSpinBox,
                             QCheckBox, QDialogButtonBox, QMessageBox, QGroupBox,
                             QMenu, QApplication)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QAction

from ..core.models import RenderJob, SoftwareType, JobStatus, Priority
from ..core.job_manager import JobManager
from ..processing.render_engines import DEFAULT_IMAGE_FORMATS, image_format_choices
from .icon_provider import get_icon
import json
import os
from datetime import datetime

class AddJobDialog(QDialog):
    """Dialog for adding a new render job."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Render Job")
        self.setModal(True)
        self.resize(450, 400)
        self.available_software = {}
        self.init_ui()
        self.refresh_software_detection()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Form layout
        form_layout = QFormLayout()
        
        # Job name
        self.name_edit = QLineEdit()
        form_layout.addRow("Job Name:", self.name_edit)
        
        # Project file
        file_layout = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(self.browse_btn)
        form_layout.addRow("Project File:", file_layout)
        
        # Software type with enhanced selection
        software_layout = QVBoxLayout()
        self.software_combo = QComboBox()
        self.software_status_label = QLabel("")
        self.software_status_label.setStyleSheet("color: #666; font-size: 10px;")
        
        refresh_software_btn = QPushButton("Refresh")
        refresh_software_btn.setIcon(get_icon("refresh"))
        refresh_software_btn.setMaximumWidth(85)
        refresh_software_btn.clicked.connect(self.refresh_software_detection)
        
        software_row = QHBoxLayout()
        software_row.addWidget(self.software_combo)
        software_row.addWidget(refresh_software_btn)
        
        software_layout.addLayout(software_row)
        software_layout.addWidget(self.software_status_label)
        
        form_layout.addRow("Render Engine:", software_layout)
        
        # Resolution
        resolution_layout = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 8192)
        self.width_spin.setValue(1920)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 8192)
        self.height_spin.setValue(1080)
        resolution_layout.addWidget(self.width_spin)
        resolution_layout.addWidget(QLabel("x"))
        resolution_layout.addWidget(self.height_spin)
        
        # Resolution presets
        preset_combo = QComboBox()
        preset_combo.addItems(["Custom", "720p", "1080p", "1440p", "4K"])
        preset_combo.currentTextChanged.connect(self.apply_resolution_preset)
        resolution_layout.addWidget(preset_combo)
        
        form_layout.addRow("Resolution:", resolution_layout)
        
        # Output format
        self.format_combo = QComboBox()
        self.software_combo.currentIndexChanged.connect(self.update_format_choices)
        self.update_format_choices()
        form_layout.addRow("Output Format:", self.format_combo)
        
        # Output path
        output_layout = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_btn = QPushButton("Browse...")
        self.output_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(self.output_btn)
        form_layout.addRow("Output Path:", output_layout)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                     QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def update_format_choices(self):
        """Offer only the formats the chosen engine can be told about.

        Each renderer names an image format its own way - Blender takes `JPEG`,
        Maya takes a number - and one list for all four engines means an option
        that dies inside the render software minutes after the job starts. With no
        engine selected yet there is nothing to translate against, so the app's own
        list stands.
        """
        software_type = self.software_combo.currentData()
        choices = image_format_choices(software_type) if software_type else []
        if not choices:
            choices = list(DEFAULT_IMAGE_FORMATS)
        previous = self.format_combo.currentText() if self.format_combo.count() else None
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        self.format_combo.addItems(choices)
        if previous in choices:
            self.format_combo.setCurrentText(previous)
        self.format_combo.blockSignals(False)

    def refresh_software_detection(self):
        """Refresh the software detection and update the combo box."""
        try:
            from ..processing.render_engines import detect_available_software
            self.available_software = detect_available_software()
            
            # Clear and repopulate combo box
            self.software_combo.clear()
            
            available_count = 0
            for software_type in SoftwareType:
                is_available = software_type in self.available_software
                version = self.available_software.get(software_type, "Not Found")
                
                if is_available:
                    display_text = f"{software_type.value.title()} ({version})"
                    available_count += 1
                else:
                    display_text = f"{software_type.value.title()} (Not Detected)"
                
                self.software_combo.addItem(display_text, software_type)
                
                # Disable unavailable options
                if not is_available:
                    item = self.software_combo.model().item(self.software_combo.count() - 1)
                    item.setEnabled(False)
            
            # Update status label
            if available_count > 0:
                self.software_status_label.setText(f"{available_count} render engine(s) ready")
                self.software_status_label.setStyleSheet("color: #2ed573; font-size: 10px;")
            else:
                self.software_status_label.setText("No render engines detected. Please install Blender, Maya, etc.")
                self.software_status_label.setStyleSheet("color: #ff4757; font-size: 10px;")
            
            # Select first available option
            for i in range(self.software_combo.count()):
                software_type = self.software_combo.itemData(i)
                if software_type in self.available_software:
                    self.software_combo.setCurrentIndex(i)
                    break

            # The engine list is what the format list is drawn from.
            self.update_format_choices()
                    
        except Exception as e:
            self.software_status_label.setText(f"Error detecting software: {str(e)}")
            self.software_status_label.setStyleSheet("color: #ff4757; font-size: 10px;")
    
    def apply_resolution_preset(self, preset_name: str):
        """Apply resolution preset."""
        presets = {
            "720p": (1280, 720),
            "1080p": (1920, 1080),
            "1440p": (2560, 1440),
            "4K": (3840, 2160)
        }
        
        if preset_name in presets:
            width, height = presets[preset_name]
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
    
    def validate_and_accept(self):
        """Validate form data before accepting."""
        # Check required fields
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Invalid Input", "Please enter a job name.")
            return
        
        if not self.file_edit.text().strip():
            QMessageBox.warning(self, "Invalid Input", "Please select a project file.")
            return
        
        if not self.output_edit.text().strip():
            QMessageBox.warning(self, "Invalid Input", "Please select an output path.")
            return
        
        # Check if project file exists
        if not os.path.exists(self.file_edit.text()):
            QMessageBox.warning(self, "File Not Found", "The selected project file does not exist.")
            return
        
        # Check if selected software is available
        selected_software = self.software_combo.currentData()
        if selected_software not in self.available_software:
            QMessageBox.warning(self, "Software Not Available", 
                              f"The selected render engine ({selected_software.value.title()}) is not available.\n"
                              "Please install the software or select a different engine.")
            return
        
        # Check if output directory exists
        output_dir = os.path.dirname(self.output_edit.text())
        if output_dir and not os.path.exists(output_dir):
            reply = QMessageBox.question(self, "Create Directory", 
                                       f"Output directory does not exist:\n{output_dir}\n\nCreate it?")
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to create directory:\n{str(e)}")
                    return
            else:
                return
        
        self.accept()
    
    def browse_file(self):
        """Browse for project file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Project File",
            "", "All Files (*)")
        if file_path:
            self.file_edit.setText(file_path)
            if not self.name_edit.text():
                # Auto-fill name from filename
                import os
                name = os.path.splitext(os.path.basename(file_path))[0]
                self.name_edit.setText(name)
    
    def browse_output(self):
        """Browse for output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_edit.setText(dir_path)
    
    def get_job_data(self):
        """Get job data from the form."""
        return {
            'name': self.name_edit.text().strip(),
            'project_file': self.file_edit.text().strip(),
            'software_type': self.software_combo.currentData(),
            'resolution': (self.width_spin.value(), self.height_spin.value()),
            'output_format': self.format_combo.currentText(),
            'output_path': self.output_edit.text().strip()
        }

class RenderPresetDialog(QDialog):
    """Dialog for applying render presets to jobs."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apply Render Preset")
        self.setModal(True)
        self.resize(350, 200)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Preset selection
        form_layout = QFormLayout()
        
        self.preset_combo = QComboBox()
        presets = {
            "Preview": "Low quality for quick previews (640x480, 32 samples)",
            "Draft": "Medium quality for review (1280x720, 64 samples)", 
            "Final": "High quality for final output (1920x1080, 128 samples)",
            "4K Ultra": "Ultra high quality 4K (3840x2160, 256 samples)"
        }
        
        for preset, description in presets.items():
            self.preset_combo.addItem(f"{preset} - {description}", preset)
        
        form_layout.addRow("Preset:", self.preset_combo)
        
        # Options
        self.override_resolution = QCheckBox("Override Resolution")
        self.override_resolution.setChecked(True)
        form_layout.addRow("", self.override_resolution)
        
        self.override_quality = QCheckBox("Override Quality Settings")
        self.override_quality.setChecked(True)
        form_layout.addRow("", self.override_quality)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                     QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def get_preset_data(self):
        """Get the selected preset data."""
        preset_name = self.preset_combo.currentData()
        
        preset_configs = {
            "Preview": {"resolution": (640, 480), "samples": 32, "quality": 50},
            "Draft": {"resolution": (1280, 720), "samples": 64, "quality": 75},
            "Final": {"resolution": (1920, 1080), "samples": 128, "quality": 95},
            "4K Ultra": {"resolution": (3840, 2160), "samples": 256, "quality": 100}
        }
        
        config = preset_configs.get(preset_name, preset_configs["Final"])
        
        return {
            "preset_name": preset_name,
            "config": config,
            "override_resolution": self.override_resolution.isChecked(),
            "override_quality": self.override_quality.isChecked()
        }

class DashboardTab(QWidget):
    """Dashboard tab for job queue management."""
    
    def __init__(self, job_manager=None):
        super().__init__()
        self.job_manager = job_manager if job_manager is not None else JobManager()
        self.setup_ui()
        self.connect_signals()
        
        # Load available software on startup
        self.refresh_software_status()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Header
        header = QLabel("RenderFox Batch Renderer")
        header.setStyleSheet("font-size: 24px; font-weight: bold; margin: 10px;")
        layout.addWidget(header)
        
        # Stats cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        # Job queue stats
        self.pending_jobs_card = self.create_stat_card("Pending Jobs", "0", "#3498db")
        self.active_jobs_card = self.create_stat_card("Active Jobs", "0", "#2ecc71") 
        self.completed_jobs_card = self.create_stat_card("Completed", "0", "#27ae60")
        
        stats_layout.addWidget(self.pending_jobs_card)
        stats_layout.addWidget(self.active_jobs_card)
        stats_layout.addWidget(self.completed_jobs_card)
        
        layout.addLayout(stats_layout)
        
        # Software availability section
        software_group = QGroupBox("Available Software")
        software_layout = QVBoxLayout()
        
        self.software_status_widget = QWidget()
        self.software_status_layout = QVBoxLayout(self.software_status_widget)
        software_layout.addWidget(self.software_status_widget)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh Software Detection")
        refresh_btn.setIcon(get_icon("refresh"))
        refresh_btn.clicked.connect(self.refresh_software_status)
        software_layout.addWidget(refresh_btn)
        
        software_group.setLayout(software_layout)
        layout.addWidget(software_group)
        
        # Control buttons
        control_layout = QHBoxLayout()
        
        self.add_job_btn = QPushButton("Add Job")
        self.remove_job_btn = QPushButton("Remove Job")
        
        # Batch operations dropdown
        self.batch_btn = QPushButton("Batch Operations")
        self.batch_menu = QMenu(self)
        
        # Selection operations
        select_all_action = QAction("Select All", self)
        select_all_action.triggered.connect(self.select_all_jobs)
        self.batch_menu.addAction(select_all_action)
        
        select_none_action = QAction("Select None", self)
        select_none_action.triggered.connect(self.select_no_jobs)
        self.batch_menu.addAction(select_none_action)
        
        invert_selection_action = QAction("Invert Selection", self)
        invert_selection_action.triggered.connect(self.invert_selection)
        self.batch_menu.addAction(invert_selection_action)
        
        self.batch_menu.addSeparator()
        
        # Bulk operations
        delete_selected_action = QAction("Delete Selected Jobs", self)
        delete_selected_action.triggered.connect(self.delete_selected_jobs)
        self.batch_menu.addAction(delete_selected_action)
        
        pause_selected_action = QAction("Pause Selected Jobs", self)
        pause_selected_action.triggered.connect(self.pause_selected_jobs)
        self.batch_menu.addAction(pause_selected_action)
        
        resume_selected_action = QAction("Resume Selected Jobs", self)
        resume_selected_action.triggered.connect(self.resume_selected_jobs)
        self.batch_menu.addAction(resume_selected_action)
        
        self.batch_menu.addSeparator()
        
        # Priority operations
        priority_high_action = QAction("Set Priority: High", self)
        priority_high_action.triggered.connect(lambda: self.set_selected_priority(Priority.HIGH))
        self.batch_menu.addAction(priority_high_action)
        
        priority_normal_action = QAction("Set Priority: Normal", self)
        priority_normal_action.triggered.connect(lambda: self.set_selected_priority(Priority.NORMAL))
        self.batch_menu.addAction(priority_normal_action)
        
        priority_low_action = QAction("Set Priority: Low", self)
        priority_low_action.triggered.connect(lambda: self.set_selected_priority(Priority.LOW))
        self.batch_menu.addAction(priority_low_action)
        
        self.batch_menu.addSeparator()
        
        # Preset operations
        apply_preset_action = QAction("Apply Render Preset...", self)
        apply_preset_action.triggered.connect(self.apply_render_preset_to_selected)
        self.batch_menu.addAction(apply_preset_action)
        
        self.batch_menu.addSeparator()
        
        # Import/Export operations
        export_jobs_action = QAction("Export Selected Jobs...", self)
        export_jobs_action.triggered.connect(self.export_selected_jobs)
        self.batch_menu.addAction(export_jobs_action)
        
        import_jobs_action = QAction("Import Jobs...", self)
        import_jobs_action.triggered.connect(self.import_jobs)
        self.batch_menu.addAction(import_jobs_action)
        
        self.batch_menu.addSeparator()
        
        # Cleanup operations
        clear_completed_action = QAction("Clear Completed Jobs", self)
        clear_completed_action.triggered.connect(self.clear_completed_jobs)
        self.batch_menu.addAction(clear_completed_action)
        
        clear_failed_action = QAction("Clear Failed Jobs", self)
        clear_failed_action.triggered.connect(self.clear_failed_jobs)
        self.batch_menu.addAction(clear_failed_action)
        
        self.batch_btn.setMenu(self.batch_menu)
        
        self.start_btn = QPushButton("Start Queue")
        self.stop_btn = QPushButton("Stop Queue")
        self.pause_btn = QPushButton("Pause Job")
        self.resume_btn = QPushButton("Resume Job")
        
        control_layout.addWidget(self.add_job_btn)
        control_layout.addWidget(self.remove_job_btn)
        control_layout.addWidget(self.batch_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.resume_btn)
        
        layout.addLayout(control_layout)
        
        # Job table
        self.job_table = QTableWidget()
        self.job_table.setColumnCount(8)
        self.job_table.setHorizontalHeaderLabels([
            "Select", "Name", "Software", "Status", "Progress", "Priority", "Resolution", "Created"
        ])
        
        # Set column widths
        header = self.job_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.job_table.setColumnWidth(0, 50)  # Select column
        self.job_table.setColumnWidth(4, 100)  # Progress column
        
        self.job_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.job_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.job_table)
        
        # Status info
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.queue_progress = QProgressBar()
        self.queue_progress.setVisible(False)
        
        status_layout.addWidget(QLabel("Status:"))
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.queue_progress)
        
        layout.addLayout(status_layout)
        
        self.setLayout(layout)
    
    def connect_signals(self):
        """Setup signal connections."""
        # Button connections
        self.add_job_btn.clicked.connect(self.add_new_job)
        self.remove_job_btn.clicked.connect(self.remove_selected_job)
        self.start_btn.clicked.connect(self.start_queue)
        self.stop_btn.clicked.connect(self.stop_queue)
        self.pause_btn.clicked.connect(self.pause_selected_job)
        self.resume_btn.clicked.connect(self.resume_selected_job)
        
        # Job manager connections
        self.job_manager.job_added.connect(self.refresh_table)
        self.job_manager.job_updated.connect(self.refresh_table)
        self.job_manager.job_removed.connect(self.refresh_table)
        self.job_manager.queue_updated.connect(self.update_status)
        # Every frame the renderer reports is a job_updated, so the bar and the
        # status line follow the render instead of waiting for a poll of their own.
        self.job_manager.job_updated.connect(self.update_progress)
        self.job_manager.job_updated.connect(self.update_status)
        # The queue can stop itself (Pause queue on error), and the user then has
        # to see that it stopped rather than a bar frozen where it was.
        self.job_manager.processing_stopped.connect(self.on_queue_stopped)
        
        # Connect stats updates to all job changes
        self.job_manager.job_added.connect(self.update_stats_cards)
        self.job_manager.job_updated.connect(self.update_stats_cards)
        self.job_manager.job_removed.connect(self.update_stats_cards)
    
    def add_new_job(self):
        """Add a new render job."""
        dialog = AddJobDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            job_data = dialog.get_job_data()
            
            # Validate required fields
            if not job_data['name'] or not job_data['project_file']:
                QMessageBox.warning(self, "Invalid Job", 
                                   "Please provide job name and project file.")
                return
            
            # Create and add job
            job = RenderJob(
                id="",  # Will be auto-generated
                name=job_data['name'],
                project_file=job_data['project_file'],
                software_type=job_data['software_type'],
                resolution=job_data['resolution'],
                output_format=job_data['output_format'],
                output_path=job_data['output_path']
            )
            
            self.job_manager.add_job(job)
    
    def remove_selected_job(self):
        """Remove the selected job."""
        current_row = self.job_table.currentRow()
        if current_row >= 0:
            job_id = self.job_table.item(current_row, 1).data(Qt.ItemDataRole.UserRole)
            self.job_manager.remove_job(job_id)
    
    def start_queue(self):
        """Start processing the job queue."""
        self.job_manager.start_processing()
        self.queue_progress.setVisible(True)
    
    def stop_queue(self):
        """Stop processing the job queue."""
        self.job_manager.stop_processing()
        self.queue_progress.setVisible(False)

    def on_queue_stopped(self):
        """The queue can stop itself, and the bar has to show that it did.

        "Pause queue on error" ends the run without a Stop click, so hiding the
        bar cannot live only in `stop_queue`.
        """
        self.queue_progress.setVisible(False)
        self.update_status()
    
    def selected_job_id(self):
        """The id stored on the row the cursor is on.

        Column 0 is the select checkbox (a `QCheckBox` cell widget, so `item()`
        there is None) and column 1 is the name, which carries the job id in its
        UserRole - the same pair `remove_selected_job` and `get_selected_jobs`
        already read.
        """
        row = self.job_table.currentRow()
        if row < 0:
            return None
        item = self.job_table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def pause_selected_job(self):
        """Pause the selected job."""
        job_id = self.selected_job_id()
        if job_id is None:
            self.status_label.setText("Select a rendering job to pause")
            return
        if not self.job_manager.pause_job(job_id):
            self.status_label.setText("Only a job that is rendering can be paused")

    def resume_selected_job(self):
        """Resume the selected job."""
        job_id = self.selected_job_id()
        if job_id is None:
            self.status_label.setText("Select a paused job to resume")
            return
        if not self.job_manager.resume_job(job_id):
            self.status_label.setText("Only a paused job can be resumed")
    
    def get_selected_jobs(self):
        """Get all currently selected jobs."""
        selected_jobs = []
        for row in range(self.job_table.rowCount()):
            checkbox = self.job_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                job_id = self.job_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
                job = self.job_manager.get_job(job_id)
                if job:
                    selected_jobs.append(job)
        return selected_jobs
    
    def select_all_jobs(self):
        """Select all jobs in the table."""
        for row in range(self.job_table.rowCount()):
            checkbox = self.job_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(True)
    
    def select_no_jobs(self):
        """Deselect all jobs in the table."""
        for row in range(self.job_table.rowCount()):
            checkbox = self.job_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(False)
    
    def invert_selection(self):
        """Invert the current selection."""
        for row in range(self.job_table.rowCount()):
            checkbox = self.job_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(not checkbox.isChecked())
    
    def delete_selected_jobs(self):
        """Delete all selected jobs."""
        selected_jobs = self.get_selected_jobs()
        if not selected_jobs:
            QMessageBox.information(self, "No Selection", "No jobs selected for deletion.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete {len(selected_jobs)} selected job(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for job in selected_jobs:
                self.job_manager.remove_job(job.id)
            QMessageBox.information(self, "Jobs Deleted", f"Successfully deleted {len(selected_jobs)} job(s).")
    
    def pause_selected_jobs(self):
        """Pause all selected jobs."""
        selected_jobs = self.get_selected_jobs()
        if not selected_jobs:
            QMessageBox.information(self, "No Selection", "No jobs selected for pausing.")
            return
        
        paused_count = 0
        for job in selected_jobs:
            if self.job_manager.pause_job(job.id):
                paused_count += 1
        
        QMessageBox.information(self, "Jobs Paused", f"Successfully paused {paused_count} job(s).")
    
    def resume_selected_jobs(self):
        """Resume all selected jobs."""
        selected_jobs = self.get_selected_jobs()
        if not selected_jobs:
            QMessageBox.information(self, "No Selection", "No jobs selected for resuming.")
            return
        
        resumed_count = 0
        for job in selected_jobs:
            if self.job_manager.resume_job(job.id):
                resumed_count += 1
        
        QMessageBox.information(self, "Jobs Resumed", f"Successfully resumed {resumed_count} job(s).")
    
    def set_selected_priority(self, priority: Priority):
        """Set priority for all selected jobs."""
        selected_jobs = self.get_selected_jobs()
        if not selected_jobs:
            QMessageBox.information(self, "No Selection", "No jobs selected for priority change.")
            return
        
        for job in selected_jobs:
            job.priority = priority
            self.job_manager.job_updated.emit(job)
        
        QMessageBox.information(self, "Priority Updated", 
                              f"Successfully updated priority to {priority.value} for {len(selected_jobs)} job(s).")
        self.refresh_table()
    
    def apply_render_preset_to_selected(self):
        """Apply render preset to selected jobs."""
        selected_jobs = self.get_selected_jobs()
        if not selected_jobs:
            QMessageBox.information(self, "No Selection", "No jobs selected for preset application.")
            return
        
        dialog = RenderPresetDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            preset_data = dialog.get_preset_data()
            config = preset_data["config"]
            
            for job in selected_jobs:
                if preset_data["override_resolution"]:
                    job.resolution = config["resolution"]
                
                if preset_data["override_quality"]:
                    # Update render settings if they exist
                    if hasattr(job, 'render_settings') and job.render_settings:
                        job.render_settings.samples = config["samples"]
                        job.render_settings.quality = config["quality"]
                
                self.job_manager.job_updated.emit(job)
            
            QMessageBox.information(self, "Preset Applied", 
                                  f"Successfully applied '{preset_data['preset_name']}' preset to {len(selected_jobs)} job(s).")
            self.refresh_table()
    
    def export_selected_jobs(self):
        """Export selected jobs to JSON file."""
        selected_jobs = self.get_selected_jobs()
        if not selected_jobs:
            QMessageBox.information(self, "No Selection", "No jobs selected for export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Jobs", 
            f"renderfox_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                export_data = {
                    "export_date": datetime.now().isoformat(),
                    "renderfox_version": "1.0.0",
                    "jobs": []
                }
                
                for job in selected_jobs:
                    job_data = {
                        "name": job.name,
                        "project_file": job.project_file,
                        "software_type": job.software_type.value,
                        "resolution": job.resolution,
                        "output_format": job.output_format,
                        "output_path": job.output_path,
                        "priority": job.priority.value,
                        "generate_lods": job.generate_lods,
                        "optimize_textures": job.optimize_textures,
                        "optimize_scene": job.optimize_scene,
                        "apply_denoising": job.apply_denoising,
                        "add_watermark": job.add_watermark,
                        "auto_organize": job.auto_organize
                    }
                    
                    if job.frame_range:
                        job_data["frame_range"] = job.frame_range
                    
                    export_data["jobs"].append(job_data)
                
                with open(file_path, 'w') as f:
                    json.dump(export_data, f, indent=2)
                
                QMessageBox.information(self, "Export Complete", 
                                      f"Successfully exported {len(selected_jobs)} job(s) to {file_path}")
            
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export jobs: {str(e)}")
    
    def import_jobs(self):
        """Import jobs from JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Jobs", "", "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    import_data = json.load(f)
                
                if "jobs" not in import_data:
                    QMessageBox.critical(self, "Import Error", "Invalid job file format.")
                    return
                
                imported_count = 0
                for job_data in import_data["jobs"]:
                    try:
                        job = RenderJob(
                            id="",  # Will be auto-generated
                            name=job_data.get("name", "Imported Job"),
                            project_file=job_data.get("project_file", ""),
                            software_type=SoftwareType(job_data.get("software_type", "blender")),
                            resolution=tuple(job_data.get("resolution", [1920, 1080])),
                            output_format=job_data.get("output_format", "png"),
                            output_path=job_data.get("output_path", ""),
                            priority=Priority(job_data.get("priority", "normal")),
                            generate_lods=job_data.get("generate_lods", False),
                            optimize_textures=job_data.get("optimize_textures", False),
                            optimize_scene=job_data.get("optimize_scene", False),
                            apply_denoising=job_data.get("apply_denoising", False),
                            add_watermark=job_data.get("add_watermark", False),
                            auto_organize=job_data.get("auto_organize", True)
                        )
                        
                        if "frame_range" in job_data:
                            job.frame_range = tuple(job_data["frame_range"])
                        
                        self.job_manager.add_job(job)
                        imported_count += 1
                        
                    except Exception as e:
                        print(f"Error importing job: {e}")
                        continue
                
                QMessageBox.information(self, "Import Complete", 
                                      f"Successfully imported {imported_count} job(s) from {os.path.basename(file_path)}")
            
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import jobs: {str(e)}")
    
    def clear_completed_jobs(self):
        """Clear all completed jobs."""
        completed_jobs = [job for job in self.job_manager.get_all_jobs() 
                         if job.status == JobStatus.COMPLETED]
        
        if not completed_jobs:
            QMessageBox.information(self, "No Completed Jobs", "No completed jobs to clear.")
            return
        
        reply = QMessageBox.question(
            self, "Clear Completed Jobs",
            f"Are you sure you want to clear {len(completed_jobs)} completed job(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for job in completed_jobs:
                self.job_manager.remove_job(job.id)
            QMessageBox.information(self, "Jobs Cleared", f"Successfully cleared {len(completed_jobs)} completed job(s).")
    
    def clear_failed_jobs(self):
        """Clear all failed jobs."""
        failed_jobs = [job for job in self.job_manager.get_all_jobs() 
                      if job.status == JobStatus.FAILED]
        
        if not failed_jobs:
            QMessageBox.information(self, "No Failed Jobs", "No failed jobs to clear.")
            return
        
        reply = QMessageBox.question(
            self, "Clear Failed Jobs",
            f"Are you sure you want to clear {len(failed_jobs)} failed job(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for job in failed_jobs:
                self.job_manager.remove_job(job.id)
            QMessageBox.information(self, "Jobs Cleared", f"Successfully cleared {len(failed_jobs)} failed job(s).")

    def refresh_table(self):
        """Refresh the job table."""
        jobs = self.job_manager.get_all_jobs()
        self.job_table.setRowCount(len(jobs))
        
        for row, job in enumerate(jobs):
            # Select checkbox
            checkbox = QCheckBox()
            self.job_table.setCellWidget(row, 0, checkbox)
            
            # Name
            name_item = QTableWidgetItem(job.name)
            name_item.setData(Qt.ItemDataRole.UserRole, job.id)
            self.job_table.setItem(row, 1, name_item)
            
            # Software
            self.job_table.setItem(row, 2, QTableWidgetItem(job.software_type.value.title()))
            
            # Status
            status_item = QTableWidgetItem(job.status.value.title())
            status_color = self.get_status_color(job.status)
            status_item.setBackground(status_color)
            self.job_table.setItem(row, 3, status_item)
            
            # Progress
            progress_item = QTableWidgetItem(f"{job.progress:.1f}%")
            self.job_table.setItem(row, 4, progress_item)
            
            # Priority
            priority_item = QTableWidgetItem(job.priority.value.title())
            priority_colors = {
                Priority.LOW: QColor(180, 180, 180),
                Priority.NORMAL: QColor(255, 255, 255),
                Priority.HIGH: QColor(255, 200, 200)
            }
            priority_item.setBackground(priority_colors.get(job.priority, QColor(255, 255, 255)))
            self.job_table.setItem(row, 5, priority_item)
            
            # Resolution
            resolution_text = f"{job.resolution[0]}x{job.resolution[1]}"
            self.job_table.setItem(row, 6, QTableWidgetItem(resolution_text))
            
            # Created
            created_text = job.created_at.strftime("%Y-%m-%d %H:%M")
            self.job_table.setItem(row, 7, QTableWidgetItem(created_text))
        
        # Update stats cards after table refresh
        self.update_stats_cards()
    
    def get_status_color(self, status: JobStatus) -> QColor:
        """Get color for job status."""
        color_map = {
            JobStatus.PENDING: QColor(200, 200, 200),
            JobStatus.PROCESSING: QColor(255, 255, 0),
            JobStatus.RENDERING: QColor(0, 255, 0),
            JobStatus.COMPLETED: QColor(0, 200, 0),
            JobStatus.FAILED: QColor(255, 0, 0),
            JobStatus.CANCELLED: QColor(255, 100, 100),
            JobStatus.PAUSED: QColor(255, 165, 0)
        }
        return color_map.get(status, QColor(255, 255, 255))
    
    def update_progress(self):
        """The queue bar tracks the job the queue is rendering."""
        running = self.job_manager.running_jobs()
        self.queue_progress.setValue(int(running[0].progress) if running else 0)

    def update_status(self):
        """One line that says what the queue is doing, including how many jobs."""
        running = self.job_manager.running_jobs()
        if running:
            extra = f" (+{len(running) - 1} more)" if len(running) > 1 else ""
            self.status_label.setText(f"Processing: {running[0].name}{extra}")
        elif self.job_manager.is_processing:
            self.status_label.setText("Processing queue...")
        else:
            self.status_label.setText("Ready")
    
    def refresh_software_status(self):
        """Refresh the software status display."""
        # Clear existing status
        for i in reversed(range(self.software_status_layout.count())):
            widget = self.software_status_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # Add new status
        software_status = self.job_manager.get_software_status()
        for software, status in software_status.items():
            status_label = QLabel(f"{software}: {'Available' if status else 'Not Available'}")
            self.software_status_layout.addWidget(status_label)
    
    def create_stat_card(self, title, value, color):
        """Create a statistics card widget."""
        card = QWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 16px; color: {color};")
        
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        
        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        
        return card
    
    def update_stats_cards(self):
        """Update statistics cards with current job counts."""
        stats = self.job_manager.get_queue_stats()
        
        # Update pending jobs card
        pending_label = self.pending_jobs_card.findChild(QLabel)
        if pending_label:
            for child in self.pending_jobs_card.findChildren(QLabel):
                if child.styleSheet() and "24px" in child.styleSheet():
                    child.setText(str(stats['pending']))
                    break
        
        # Update active jobs card  
        for child in self.active_jobs_card.findChildren(QLabel):
            if child.styleSheet() and "24px" in child.styleSheet():
                child.setText(str(stats['rendering'] + stats['paused']))
                break
        
        # Update completed jobs card
        for child in self.completed_jobs_card.findChildren(QLabel):
            if child.styleSheet() and "24px" in child.styleSheet():
                child.setText(str(stats['completed']))
                break