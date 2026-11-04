"""
Automation tab for workflow automation, batch processing, and task scheduling.
"""

import os
import json
import sys
import shutil
import threading
import subprocess
import ast
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
                             QPushButton, QComboBox, QLabel, QGroupBox, QFormLayout, 
                             QSpinBox, QDoubleSpinBox, QSlider, QTabWidget, QCheckBox,
                             QFrame, QGridLayout, QScrollArea, QTextEdit, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
                             QListWidget, QTreeWidget, QTreeWidgetItem, QPlainTextEdit,
                             QFileDialog, QMessageBox, QTimeEdit, QDateEdit)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QTime, QDate
from PyQt6.QtGui import QFont, QColor, QIcon
from .icon_provider import get_icon

# Import automation engine
from ..features.automation_engine import (
    AutomationEngine, FileWatcher, WorkflowExecutor,
    Workflow, WorkflowStep, BatchProcessor, ActionRegistry
)


BACKUP_SUBFOLDER = ".renderfox_backups"


class WorkflowExecutionThread(QThread):
    """Thread for executing automation workflows."""
    
    progress_updated = pyqtSignal(int, str)
    workflow_completed = pyqtSignal(bool, str)
    
    def __init__(self, workflow_data):
        super().__init__()
        self.workflow_data = workflow_data
        
    def run(self):
        """Execute the workflow."""
        try:
            steps = self.workflow_data.get('steps', [])
            total_steps = len(steps)
            
            for i, step in enumerate(steps):
                step_name = step.get('name', f'Step {i+1}')
                self.progress_updated.emit(int((i / total_steps) * 100), f"Executing: {step_name}")
                
                # Real execution
                action_id = step.get('action') or step.get('task_type')
                params = step.get('parameters', {})
                
                if action_id:
                    result = ActionRegistry.execute(action_id, **params)
                    if not result.get('success', False):
                        raise Exception(result.get('error', 'Unknown error'))
                else:
                    # Simulation fallback
                    self.msleep(500)
                
            self.progress_updated.emit(100, "Workflow completed")
            self.workflow_completed.emit(True, "Workflow completed successfully")
            
        except Exception as e:
            self.workflow_completed.emit(False, f"Workflow failed: {str(e)}")

class AutomationTab(QWidget):
    """Automation and workflow management interface."""
    
    workflow_started = pyqtSignal(str)
    auto_actions_finished = pyqtSignal(str, list)
    workflow_completed = pyqtSignal(str, bool)
    task_scheduled = pyqtSignal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Initialize automation engine
        self.automation_engine = AutomationEngine()
        self.file_watcher = FileWatcher()
        self.workflow_executor = WorkflowExecutor()
        self.batch_processor = BatchProcessor()
        
        # Connect engine signals
        self.automation_engine.workflow_started.connect(self.on_workflow_started)
        self.automation_engine.workflow_completed.connect(self.on_workflow_completed_engine)
        self.automation_engine.workflow_failed.connect(self.on_workflow_failed)
        self.automation_engine.workflow_progress.connect(self.on_workflow_progress)
        
        self.automation_engine.task_started.connect(self.on_task_started)
        self.automation_engine.task_completed.connect(self.on_task_completed)
        
        self.file_watcher.file_created.connect(self.on_file_created)
        self.file_watcher.file_modified.connect(self.on_file_modified)
        self.file_watcher.file_deleted.connect(self.on_file_deleted)
        self.file_watcher.file_moved.connect(self.on_file_moved)
        self.auto_actions_finished.connect(self.on_auto_actions_finished)
        
        self.batch_processor.progress_updated.connect(self.on_batch_progress)
        self.batch_processor.batch_completed.connect(self.on_batch_completed_engine)
        
        self.active_workflows = {}
        self.watch_requests = {}
        self._library = None
        self._task_rows = []
        self.current_task_id = None
        self.init_ui()
        self.setup_connections()
        self.load_sample_data()
        self.refresh_task_table()
        self._update_schedule_controls()

        # The engine's polling thread is what makes a schedule happen at all.
        self.automation_engine.start()

        # Dashboard update timer
        self.dashboard_timer = QTimer()
        self.dashboard_timer.timeout.connect(self.update_dashboard_metrics)
        self.dashboard_timer.start(2000)


    def init_ui(self):
        """Initialize the automation interface."""
        main_layout = QVBoxLayout(self)
        
        # Create tab widget for different automation areas
        self.automation_tabs = QTabWidget()
        
        # Workflow Builder tab
        builder_tab = self.create_workflow_builder_tab()
        self.automation_tabs.addTab(builder_tab, "Workflow Builder")
        
        # Batch Operations tab
        batch_tab = self.create_batch_operations_tab()
        self.automation_tabs.addTab(batch_tab, "Batch Operations")
        
        # Task Scheduler tab
        scheduler_tab = self.create_scheduler_tab()
        self.automation_tabs.addTab(scheduler_tab, "Task Scheduler")
        
        # File Watcher tab
        watcher_tab = self.create_file_watcher_tab()
        self.automation_tabs.addTab(watcher_tab, "File Watcher")
        
        # Automation Monitor tab
        monitor_tab = self.create_monitor_tab()
        self.automation_tabs.addTab(monitor_tab, "Monitor")
        
        main_layout.addWidget(self.automation_tabs)
        
    def create_workflow_builder_tab(self):
        """Create spacious, master-detail workflow builder interface."""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        
        # --- Left Panel: Saved Workflows & Management ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        workflows_group = QGroupBox("Saved Workflows")
        workflows_layout = QVBoxLayout(workflows_group)
        workflows_layout.setSpacing(8)
        workflows_layout.setContentsMargins(10, 14, 10, 10)
        
        # Action buttons toolbar
        toolbar_row1 = QHBoxLayout()
        toolbar_row1.setSpacing(6)
        self.new_workflow_btn = QPushButton("New")
        self.new_workflow_btn.setIcon(get_icon("add"))
        self.new_workflow_btn.setToolTip("Create new workflow")
        
        self.duplicate_workflow_btn = QPushButton("Duplicate")
        self.duplicate_workflow_btn.setIcon(get_icon("models"))
        self.duplicate_workflow_btn.setToolTip("Duplicate selected workflow")
        
        self.delete_workflow_btn = QPushButton("Delete")
        self.delete_workflow_btn.setIcon(get_icon("delete"))
        self.delete_workflow_btn.setToolTip("Delete selected workflow")
        
        toolbar_row1.addWidget(self.new_workflow_btn)
        toolbar_row1.addWidget(self.duplicate_workflow_btn)
        toolbar_row1.addWidget(self.delete_workflow_btn)
        workflows_layout.addLayout(toolbar_row1)
        
        toolbar_row2 = QHBoxLayout()
        toolbar_row2.setSpacing(6)
        self.load_workflow_btn = QPushButton("Load")
        self.load_workflow_btn.setIcon(get_icon("folder"))
        self.load_workflow_btn.setToolTip("Load workflow from file")
        
        self.save_workflow_btn = QPushButton("Save")
        self.save_workflow_btn.setIcon(get_icon("backup"))
        self.save_workflow_btn.setToolTip("Save workflow to file")
        
        toolbar_row2.addWidget(self.load_workflow_btn)
        toolbar_row2.addWidget(self.save_workflow_btn)
        workflows_layout.addLayout(toolbar_row2)
        
        # Workflows list (expanding to fill left column)
        self.workflows_list = QListWidget()
        self.workflows_list.setAlternatingRowColors(True)
        self.workflows_list.addItems([
            "Model Conversion Pipeline",
            "Batch LOD Generation",
            "Texture Optimization",
            "Quality Assurance Check",
            "Daily Report Generation"
        ])
        workflows_layout.addWidget(self.workflows_list)
        
        left_layout.addWidget(workflows_group)
        splitter.addWidget(left_panel)
        
        # --- Right Panel: Workflow Editor & Step Sequence ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        
        details_group = QGroupBox("Workflow Editor")
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(10)
        details_layout.setContentsMargins(12, 14, 12, 12)
        
        # Info header (Name & Description)
        info_layout = QFormLayout()
        info_layout.setVerticalSpacing(8)
        info_layout.setHorizontalSpacing(16)
        
        self.workflow_name_edit = QLineEdit()
        self.workflow_name_edit.setPlaceholderText("Enter workflow name...")
        
        self.workflow_description_edit = QTextEdit()
        self.workflow_description_edit.setMinimumHeight(44)
        self.workflow_description_edit.setMaximumHeight(56)
        self.workflow_description_edit.setPlaceholderText("Enter workflow description...")
        
        info_layout.addRow("Name:", self.workflow_name_edit)
        info_layout.addRow("Description:", self.workflow_description_edit)
        details_layout.addLayout(info_layout)
        
        # Steps section header
        steps_header = QHBoxLayout()
        steps_label = QLabel("Workflow Execution Steps:")
        steps_label.setStyleSheet("font-weight: 600; font-size: 10pt;")
        steps_header.addWidget(steps_label)
        steps_header.addStretch()
        details_layout.addLayout(steps_header)
        
        # Steps Table (Expanding vertical height for plenty of visible rows!)
        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(4)
        self.steps_table.setHorizontalHeaderLabels(["#", "Action", "Parameters", "Condition"])
        self.steps_table.setMinimumHeight(240)
        self.steps_table.setAlternatingRowColors(True)
        self.steps_table.verticalHeader().setDefaultSectionSize(34)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.horizontalHeader().setStretchLastSection(False)
        self.steps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.steps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.steps_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.setColumnWidth(1, 180)
        self.steps_table.setColumnWidth(3, 140)
        details_layout.addWidget(self.steps_table)
        
        # Bottom controls toolbar
        bottom_toolbar = QHBoxLayout()
        bottom_toolbar.setSpacing(8)
        
        # Step modification buttons
        self.add_step_btn = QPushButton("Add Step")
        self.add_step_btn.setIcon(get_icon("add"))
        self.remove_step_btn = QPushButton("Remove Step")
        self.remove_step_btn.setIcon(get_icon("delete"))
        self.move_up_btn = QPushButton("Move Up")
        self.move_up_btn.setIcon(get_icon("arrow_up"))
        self.move_down_btn = QPushButton("Move Down")
        self.move_down_btn.setIcon(get_icon("arrow_down"))
        
        bottom_toolbar.addWidget(self.add_step_btn)
        bottom_toolbar.addWidget(self.remove_step_btn)
        bottom_toolbar.addWidget(self.move_up_btn)
        bottom_toolbar.addWidget(self.move_down_btn)
        bottom_toolbar.addStretch()
        
        # Execution buttons
        self.test_workflow_btn = QPushButton("Test Workflow")
        self.test_workflow_btn.setIcon(get_icon("diagnostics"))
        
        self.run_workflow_btn = QPushButton("Run Workflow")
        self.run_workflow_btn.setIcon(get_icon("rendering"))
        self.run_workflow_btn.setProperty("primary", "true")
        
        self.stop_workflow_btn = QPushButton("Stop")
        self.stop_workflow_btn.setIcon(get_icon("delete"))
        self.stop_workflow_btn.setEnabled(False)
        
        bottom_toolbar.addWidget(self.test_workflow_btn)
        bottom_toolbar.addWidget(self.run_workflow_btn)
        bottom_toolbar.addWidget(self.stop_workflow_btn)
        
        details_layout.addLayout(bottom_toolbar)
        right_layout.addWidget(details_group)
        splitter.addWidget(right_panel)
        
        splitter.setSizes([300, 800])
        main_layout.addWidget(splitter)
        
        return widget
        
    def create_batch_operations_tab(self):
        """Create batch operations interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Batch controls
        controls_group = QGroupBox("Batch Operation Setup")
        controls_layout = QGridLayout()
        
        # Source selection
        controls_layout.addWidget(QLabel("Source:"), 0, 0)
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItems([
            "Folder", "File List", "Model Library", "Search Results", "Selected Models"
        ])
        controls_layout.addWidget(self.source_type_combo, 0, 1)
        
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Select source folder or files...")
        controls_layout.addWidget(self.source_path_edit, 0, 2)
        
        self.browse_source_btn = QPushButton("Browse")
        self.browse_source_btn.setIcon(get_icon("folder"))
        controls_layout.addWidget(self.browse_source_btn, 0, 3)
        
        # Operation selection
        controls_layout.addWidget(QLabel("Operation:"), 1, 0)
        self.operation_combo = QComboBox()
        self.operation_combo.addItems([
            "Format Conversion", "LOD Generation", "Texture Optimization", 
            "Model Validation", "Metadata Extraction", "Thumbnail Generation",
            "File Organization", "Quality Analysis", "Custom Script"
        ])
        controls_layout.addWidget(self.operation_combo, 1, 1, 1, 2)
        
        # Output settings
        controls_layout.addWidget(QLabel("Output:"), 2, 0)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Select output folder...")
        controls_layout.addWidget(self.output_path_edit, 2, 1, 1, 2)
        
        self.browse_output_btn = QPushButton("Browse")
        self.browse_output_btn.setIcon(get_icon("folder"))
        controls_layout.addWidget(self.browse_output_btn, 2, 3)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Operation parameters
        params_layout = QHBoxLayout()
        
        # General parameters
        general_group = QGroupBox("General Parameters")
        general_form = QFormLayout()
        
        self.recursive_cb = QCheckBox("Process Subfolders")
        self.recursive_cb.setChecked(True)
        
        self.overwrite_cb = QCheckBox("Overwrite Existing Files")
        
        self.backup_cb = QCheckBox("Create Backup")
        self.backup_cb.setChecked(True)
        
        self.parallel_processing_cb = QCheckBox("Parallel Processing")
        self.parallel_processing_cb.setChecked(True)
        
        self.max_threads_spin = QSpinBox()
        self.max_threads_spin.setRange(1, 16)
        self.max_threads_spin.setValue(4)
        
        general_form.addRow(self.recursive_cb)
        general_form.addRow(self.overwrite_cb)
        general_form.addRow(self.backup_cb)
        general_form.addRow(self.parallel_processing_cb)
        general_form.addRow("Max Threads:", self.max_threads_spin)
        
        general_group.setLayout(general_form)
        params_layout.addWidget(general_group)
        
        # Operation-specific parameters
        specific_group = QGroupBox("Operation Parameters")
        specific_layout = QVBoxLayout()
        
        # Format conversion parameters
        self.format_group = QGroupBox("Format Conversion")
        format_layout = QFormLayout()
        
        self.target_format_combo = QComboBox()
        self.target_format_combo.addItems([
            "OBJ", "FBX", "GLTF", "GLB", "DAE", "3DS", "PLY", "STL"
        ])
        
        self.preserve_materials_cb = QCheckBox("Preserve Materials")
        self.preserve_materials_cb.setChecked(True)
        
        self.optimize_geometry_cb = QCheckBox("Optimize Geometry")
        
        format_layout.addRow("Target Format:", self.target_format_combo)
        format_layout.addRow(self.preserve_materials_cb)
        format_layout.addRow(self.optimize_geometry_cb)
        
        self.format_group.setLayout(format_layout)
        specific_layout.addWidget(self.format_group)
        
        # LOD parameters
        self.lod_group = QGroupBox("LOD Generation")
        lod_layout = QFormLayout()
        
        self.lod_levels_spin = QSpinBox()
        self.lod_levels_spin.setRange(1, 10)
        self.lod_levels_spin.setValue(3)
        
        self.lod_reduction_spin = QDoubleSpinBox()
        self.lod_reduction_spin.setRange(0.1, 0.9)
        self.lod_reduction_spin.setValue(0.5)
        self.lod_reduction_spin.setSingleStep(0.1)
        
        lod_layout.addRow("LOD Levels:", self.lod_levels_spin)
        lod_layout.addRow("Reduction Factor:", self.lod_reduction_spin)
        
        self.lod_group.setLayout(lod_layout)
        self.lod_group.setVisible(False)
        specific_layout.addWidget(self.lod_group)
        
        specific_group.setLayout(specific_layout)
        params_layout.addWidget(specific_group)
        
        layout.addLayout(params_layout)
        
        # Batch execution
        execution_group = QGroupBox("Batch Execution")
        execution_layout = QVBoxLayout()
        
        # Progress and status
        progress_layout = QHBoxLayout()
        
        self.batch_progress = QProgressBar()
        self.batch_status_label = QLabel("Ready to start batch operation")
        
        progress_layout.addWidget(self.batch_progress)
        progress_layout.addWidget(self.batch_status_label)
        
        execution_layout.addLayout(progress_layout)
        
        # Control buttons
        batch_controls = QHBoxLayout()
        
        self.start_batch_btn = QPushButton("Start Batch")
        self.start_batch_btn.setIcon(get_icon("batch_render"))
        self.start_batch_btn.setProperty("primary", "true")
        
        self.pause_batch_btn = QPushButton("Pause")
        self.pause_batch_btn.setIcon(get_icon("clock"))
        self.pause_batch_btn.setEnabled(False)
        
        self.stop_batch_btn = QPushButton("Stop")
        self.stop_batch_btn.setIcon(get_icon("delete"))
        self.stop_batch_btn.setEnabled(False)
        
        self.preview_batch_btn = QPushButton("Preview")
        self.preview_batch_btn.setIcon(get_icon("models"))
        
        batch_controls.addWidget(self.start_batch_btn)
        batch_controls.addWidget(self.pause_batch_btn)
        batch_controls.addWidget(self.stop_batch_btn)
        batch_controls.addWidget(self.preview_batch_btn)
        batch_controls.addStretch()
        
        execution_layout.addLayout(batch_controls)
        
        # Batch log
        self.batch_log = QPlainTextEdit()
        self.batch_log.setMaximumHeight(100)
        self.batch_log.setReadOnly(True)
        self.batch_log.setPlainText("Batch operation log will appear here...")
        
        execution_layout.addWidget(self.batch_log)
        
        execution_group.setLayout(execution_layout)
        layout.addWidget(execution_group)
        
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll
        
    def create_scheduler_tab(self):
        """Create task scheduler interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Scheduler controls
        controls_group = QGroupBox("Task Scheduler")
        controls_layout = QHBoxLayout()
        
        self.create_task_btn = QPushButton("Create Task")
        self.create_task_btn.setIcon(get_icon("add"))
        self.create_task_btn.setProperty("primary", "true")
        self.edit_task_btn = QPushButton("Edit Task")
        self.edit_task_btn.setIcon(get_icon("edit"))
        self.delete_task_btn = QPushButton("Delete Task")
        self.delete_task_btn.setIcon(get_icon("delete"))
        self.enable_task_btn = QPushButton("Enable")
        self.enable_task_btn.setIcon(get_icon("clean"))
        self.disable_task_btn = QPushButton("Disable")
        self.disable_task_btn.setIcon(get_icon("delete"))
        
        controls_layout.addWidget(self.create_task_btn)
        controls_layout.addWidget(self.edit_task_btn)
        controls_layout.addWidget(self.delete_task_btn)
        controls_layout.addWidget(self.enable_task_btn)
        controls_layout.addWidget(self.disable_task_btn)
        controls_layout.addStretch()
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Scheduled tasks and task editor
        scheduler_layout = QHBoxLayout()
        
        # Task list
        tasks_group = QGroupBox("Scheduled Tasks")
        tasks_layout = QVBoxLayout()
        
        self.scheduled_tasks_table = QTableWidget()
        self.scheduled_tasks_table.setColumnCount(6)
        self.scheduled_tasks_table.setHorizontalHeaderLabels([
            "Task Name", "Type", "Schedule", "Next Run", "Status", "Last Result"
        ])
        
        
        tasks_layout.addWidget(self.scheduled_tasks_table)
        tasks_group.setLayout(tasks_layout)
        scheduler_layout.addWidget(tasks_group)
        
        # Task editor
        editor_group = QGroupBox("Task Editor")
        editor_layout = QVBoxLayout()
        
        # Task details
        task_form = QFormLayout()
        
        self.task_name_edit = QLineEdit()
        self.task_name_edit.setPlaceholderText("Enter task name...")
        
        self.task_type_combo = QComboBox()
        for action_id, label in self._task_action_choices():
            self.task_type_combo.addItem(label, action_id)
        self.task_type_combo.setToolTip("The action this task runs, as the registry names it.")


        self.task_enabled_cb = QCheckBox("Task Enabled")
        self.task_enabled_cb.setChecked(True)
        
        task_form.addRow("Task Name:", self.task_name_edit)
        task_form.addRow("Task Type:", self.task_type_combo)
        task_form.addRow(self.task_enabled_cb)
        
        editor_layout.addLayout(task_form)
        
        # Schedule settings
        schedule_group = QGroupBox("Schedule Settings")
        schedule_layout = QFormLayout()
        
        self.schedule_type_combo = QComboBox()
        self.schedule_type_combo.addItems([
            "One Time", "Hourly", "Daily", "Weekly", "Monthly", "Repeated interval"
        ])

        # "One Time" beside today's date is a moment that has usually already gone by, so
        # the pane would open refusing its own Save click. Daily is the first choice that
        # is valid exactly as these fields are showing it.
        self.schedule_type_combo.setCurrentText("Daily")

        self.schedule_time_edit = QTimeEdit()
        self.schedule_time_edit.setTime(QTime(9, 0))

        self.schedule_date_edit = QDateEdit()
        self.schedule_date_edit.setDate(QDate.currentDate())

        self.repeat_interval_spin = QSpinBox()
        self.repeat_interval_spin.setRange(1, 999)
        self.repeat_interval_spin.setValue(1)

        self.repeat_unit_combo = QComboBox()
        self.repeat_unit_combo.addItems(["Minutes", "Hours", "Days"])

        schedule_layout.addRow("Schedule Type:", self.schedule_type_combo)
        schedule_layout.addRow("Time:", self.schedule_time_edit)
        schedule_layout.addRow("Date:", self.schedule_date_edit)
        schedule_layout.addRow("Repeat Every:", self.repeat_interval_spin)
        schedule_layout.addRow("Unit:", self.repeat_unit_combo)


        schedule_group.setLayout(schedule_layout)
        editor_layout.addWidget(schedule_group)
        
        # Task actions
        actions_group = QGroupBox("Task Actions")
        actions_layout = QVBoxLayout()
        
        self.task_actions_edit = QPlainTextEdit()
        self.task_actions_edit.setMaximumHeight(100)
        self.task_actions_edit.setPlaceholderText("Parameters as name/value pairs, e.g. \"levels\": 3")
        
        actions_layout.addWidget(self.task_actions_edit)
        actions_group.setLayout(actions_layout)
        editor_layout.addWidget(actions_group)
        
        # Task buttons
        task_buttons = QHBoxLayout()
        self.save_task_btn = QPushButton("Save Task")
        self.save_task_btn.setIcon(get_icon("backup"))
        self.save_task_btn.setProperty("primary", "true")
        self.test_task_btn = QPushButton("Test Task")
        self.test_task_btn.setIcon(get_icon("diagnostics"))
        self.run_now_btn = QPushButton("Run Now")
        self.run_now_btn.setIcon(get_icon("rendering"))
        
        task_buttons.addWidget(self.save_task_btn)
        task_buttons.addWidget(self.test_task_btn)
        task_buttons.addWidget(self.run_now_btn)
        task_buttons.addStretch()
        
        editor_layout.addLayout(task_buttons)
        
        editor_group.setLayout(editor_layout)
        scheduler_layout.addWidget(editor_group)
        
        layout.addLayout(scheduler_layout)
        
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll
        
    def create_file_watcher_tab(self):
        """Create file watcher interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Watcher controls
        controls_group = QGroupBox("File Watcher Settings")
        controls_layout = QHBoxLayout()
        
        self.add_watch_btn = QPushButton("Add Watch Folder")
        self.add_watch_btn.setIcon(get_icon("folder"))
        self.remove_watch_btn = QPushButton("Remove Watch")
        self.remove_watch_btn.setIcon(get_icon("delete"))
        self.start_watching_btn = QPushButton("Start Watching")
        self.start_watching_btn.setProperty("primary", "true")
        self.stop_watching_btn = QPushButton("Stop Watching")
        self.stop_watching_btn.setEnabled(False)
        
        controls_layout.addWidget(self.add_watch_btn)
        controls_layout.addWidget(self.remove_watch_btn)
        controls_layout.addWidget(self.start_watching_btn)
        controls_layout.addWidget(self.stop_watching_btn)
        controls_layout.addStretch()
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Watch folders and settings
        watcher_layout = QHBoxLayout()
        
        # Watch folders list
        folders_group = QGroupBox("Watched Folders")
        folders_layout = QVBoxLayout()
        
        self.watch_folders_table = QTableWidget()
        self.watch_folders_table.setColumnCount(4)
        self.watch_folders_table.setHorizontalHeaderLabels([
            "Folder Path", "File Filter", "Actions", "Status"
        ])
        
        
        folders_layout.addWidget(self.watch_folders_table)
        folders_group.setLayout(folders_layout)
        watcher_layout.addWidget(folders_group)
        
        # Watcher settings
        settings_group = QGroupBox("Watcher Configuration")
        settings_layout = QVBoxLayout()
        
        # File filters
        filters_form = QFormLayout()
        
        self.file_extensions_edit = QLineEdit()
        self.file_extensions_edit.setText("*.obj,*.fbx,*.gltf,*.dae")
        self.file_extensions_edit.setPlaceholderText("*.obj,*.fbx,*.gltf")
        
        self.exclude_patterns_edit = QLineEdit()
        self.exclude_patterns_edit.setPlaceholderText("*_temp,*_backup")
        
        self.min_file_size_spin = QSpinBox()
        self.min_file_size_spin.setRange(0, 999999)
        self.min_file_size_spin.setValue(1)
        self.min_file_size_spin.setSuffix(" KB")
        
        filters_form.addRow("File Extensions:", self.file_extensions_edit)
        filters_form.addRow("Exclude Patterns:", self.exclude_patterns_edit)
        filters_form.addRow("Min File Size:", self.min_file_size_spin)
        
        settings_layout.addLayout(filters_form)
        
        # Watch events
        events_group = QGroupBox("Watch Events")
        events_layout = QFormLayout()
        
        self.watch_created_cb = QCheckBox("File Created")
        self.watch_created_cb.setChecked(True)
        
        self.watch_modified_cb = QCheckBox("File Modified")
        self.watch_modified_cb.setChecked(True)
        
        self.watch_deleted_cb = QCheckBox("File Deleted")
        
        self.watch_moved_cb = QCheckBox("File Moved")
        
        events_layout.addRow(self.watch_created_cb)
        events_layout.addRow(self.watch_modified_cb)
        events_layout.addRow(self.watch_deleted_cb)
        events_layout.addRow(self.watch_moved_cb)
        
        events_group.setLayout(events_layout)
        settings_layout.addWidget(events_group)
        
        # Actions
        actions_group = QGroupBox("Auto Actions")
        actions_layout = QFormLayout()
        
        self.auto_import_cb = QCheckBox("Auto Import to Library")
        self.auto_import_cb.setChecked(True)
        
        self.auto_validate_cb = QCheckBox("Auto Validate Models")
        
        self.auto_thumbnail_cb = QCheckBox("Auto Generate Thumbnails")
        
        self.auto_backup_cb = QCheckBox("Auto Backup Files")
        
        self.run_script_cb = QCheckBox("Run Custom Script")
        
        self.script_path_edit = QLineEdit()
        self.script_path_edit.setPlaceholderText("Path to custom script...")
        
        actions_layout.addRow(self.auto_import_cb)
        actions_layout.addRow(self.auto_validate_cb)
        actions_layout.addRow(self.auto_thumbnail_cb)
        actions_layout.addRow(self.auto_backup_cb)
        actions_layout.addRow(self.run_script_cb)
        actions_layout.addRow("Script Path:", self.script_path_edit)
        
        actions_group.setLayout(actions_layout)
        settings_layout.addWidget(actions_group)
        
        settings_group.setLayout(settings_layout)
        watcher_layout.addWidget(settings_group)
        
        layout.addLayout(watcher_layout)
        
        # File events log
        log_group = QGroupBox("File Events Log")
        log_layout = QVBoxLayout()
        
        self.file_events_log = QPlainTextEdit()
        self.file_events_log.setMaximumHeight(120)
        self.file_events_log.setReadOnly(True)
        self.file_events_log.setPlainText("File watcher events will appear here...")
        
        log_layout.addWidget(self.file_events_log)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll
        
    def create_monitor_tab(self):
        """Create automation monitoring interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Monitor overview
        overview_layout = QHBoxLayout()
        
        # Status cards
        status_group = QGroupBox("Automation Status")
        status_layout = QGridLayout()
        
        # Active workflows card
        workflows_card = self.create_status_card("Active Workflows", "0", "#2196F3")
        self.active_workflows_label = workflows_card.findChild(QLabel, "status_value_active_workflows")
        status_layout.addWidget(workflows_card, 0, 0)
        
        # Scheduled tasks card
        tasks_card = self.create_status_card("Scheduled Tasks", "0", "#4CAF50")
        self.scheduled_tasks_label = tasks_card.findChild(QLabel, "status_value_scheduled_tasks")
        status_layout.addWidget(tasks_card, 0, 1)
        
        # File watchers card
        watchers_card = self.create_status_card("File Watchers", "0", "#FF9800")
        self.file_watchers_label = watchers_card.findChild(QLabel, "status_value_file_watchers")
        status_layout.addWidget(watchers_card, 1, 0)
        
        # Completed today card
        completed_card = self.create_status_card("Completed Today", "0", "#9C27B0")
        self.completed_today_label = completed_card.findChild(QLabel, "status_value_completed_today")
        status_layout.addWidget(completed_card, 1, 1)
        
        status_group.setLayout(status_layout)
        overview_layout.addWidget(status_group)
        
        # Recent activity
        activity_group = QGroupBox("Recent Activity")
        activity_layout = QVBoxLayout()
        
        self.activity_list = QListWidget()
        
        # Add sample activities
        recent_activities = [
            "Workflow 'Model Conversion' started",
            "Task 'Daily Backup' completed successfully",
            "New file detected: building.obj",
            "Task 'Quality Check' failed - see logs",
            "LOD generation completed for 5 models",
            "Batch operation: 12/20 files processed"
        ]
        
        for activity in recent_activities:
            self.activity_list.addItem(activity)
            
        self.activity_list.clear() # Clear sample data
        activity_layout.addWidget(self.activity_list)
        activity_group.setLayout(activity_layout)
        overview_layout.addWidget(activity_group)
        
        layout.addLayout(overview_layout)
        
        # Detailed monitoring
        details_tabs = QTabWidget()
        
        # Active processes tab
        processes_tab = self.create_processes_monitor()
        details_tabs.addTab(processes_tab, "Active Processes")
        
        # Performance metrics tab
        metrics_tab = self.create_metrics_monitor()
        details_tabs.addTab(metrics_tab, "Performance")
        
        # Error log tab
        errors_tab = self.create_errors_monitor()
        details_tabs.addTab(errors_tab, "Errors & Warnings")
        
        layout.addWidget(details_tabs)
        
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll
        
    def create_status_card(self, title, value, color):
        """Create a status card widget."""
        card = QFrame()
        card.setFrameStyle(QFrame.Shape.StyledPanel)
        card.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {color};
                border-radius: 8px;
                background-color: rgba{self.hex_to_rgba(color, 0.1)};
                padding: 10px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-weight: bold; color: #666;")
        
        value_label = QLabel(value)
        value_label.setObjectName(f"status_value_{title.replace(' ', '_').lower()}")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")
        
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        
        return card
        
    def hex_to_rgba(self, hex_color, alpha):
        """Convert hex color to RGBA string."""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"({r}, {g}, {b}, {alpha})"
        
    def create_processes_monitor(self):
        """Create active processes monitoring widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.processes_table = QTableWidget()
        self.processes_table.setColumnCount(6)
        self.processes_table.setHorizontalHeaderLabels([
            "Process ID", "Name", "Progress", "Status", "Started", "ETA"
        ])
        
        # Add sample processes
        self.processes_table.setRowCount(3)
        
        sample_processes = [
            ("WF001", "Model Conversion Pipeline", "65%", "Running", "14:30:15", "2 min"),
            ("BT002", "Batch LOD Generation", "23%", "Running", "14:45:22", "8 min"),
            ("TS003", "Scheduled Cleanup", "100%", "Completed", "14:00:00", "Done")
        ]
        
        for row, (pid, name, progress, status, started, eta) in enumerate(sample_processes):
            self.processes_table.setItem(row, 0, QTableWidgetItem(pid))
            self.processes_table.setItem(row, 1, QTableWidgetItem(name))
            self.processes_table.setItem(row, 2, QTableWidgetItem(progress))
            self.processes_table.setItem(row, 3, QTableWidgetItem(status))
            self.processes_table.setItem(row, 4, QTableWidgetItem(started))
            self.processes_table.setItem(row, 5, QTableWidgetItem(eta))
        
        layout.addWidget(self.processes_table)
        
        # Process controls
        controls_layout = QHBoxLayout()
        self.refresh_processes_btn = QPushButton("Refresh")
        self.refresh_processes_btn.setIcon(get_icon("refresh"))
        self.kill_process_btn = QPushButton("Kill Process")
        self.kill_process_btn.setIcon(get_icon("delete"))
        self.process_details_btn = QPushButton("Details")
        self.process_details_btn.setIcon(get_icon("diagnostics"))
        
        controls_layout.addWidget(self.refresh_processes_btn)
        controls_layout.addWidget(self.kill_process_btn)
        controls_layout.addWidget(self.process_details_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        return widget
        
    def create_metrics_monitor(self):
        """Create performance metrics monitoring widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Metrics summary
        metrics_layout = QGridLayout()
        
        self.cpu_usage_label = QLabel("CPU Usage: 45%")
        self.memory_usage_label = QLabel("Memory: 2.1 GB")
        self.disk_io_label = QLabel("Disk I/O: 15 MB/s")
        self.active_threads_label = QLabel("Active Threads: 8")
        
        metrics_layout.addWidget(self.cpu_usage_label, 0, 0)
        metrics_layout.addWidget(self.memory_usage_label, 0, 1)
        metrics_layout.addWidget(self.disk_io_label, 1, 0)
        metrics_layout.addWidget(self.active_threads_label, 1, 1)
        
        layout.addLayout(metrics_layout)
        
        # Performance history (placeholder)
        history_label = QLabel("Performance history charts would be displayed here")
        history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        history_label.setStyleSheet("border: 1px dashed #ccc; padding: 50px;")
        
        layout.addWidget(history_label)
        
        return widget
        
    def create_errors_monitor(self):
        """Create errors and warnings monitoring widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Error summary
        summary_layout = QHBoxLayout()
        
        self.errors_count_label = QLabel("Errors: 2")
        self.errors_count_label.setStyleSheet("color: #ff4757; font-weight: bold;")
        
        self.warnings_count_label = QLabel("Warnings: 5")
        self.warnings_count_label.setStyleSheet("color: #ffa502; font-weight: bold;")
        
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setIcon(get_icon("clean"))
        self.export_log_btn = QPushButton("Export Log")
        self.export_log_btn.setIcon(get_icon("export"))
        
        summary_layout.addWidget(self.errors_count_label)
        summary_layout.addWidget(self.warnings_count_label)
        summary_layout.addStretch()
        summary_layout.addWidget(self.clear_log_btn)
        summary_layout.addWidget(self.export_log_btn)
        
        layout.addLayout(summary_layout)
        
        # Error log display
        self.error_log_display = QPlainTextEdit()
        self.error_log_display.setReadOnly(True)
        self.error_log_display.setPlainText("""[14:30:15] ERROR: Failed to convert model.obj - Invalid file format
[14:25:22] WARNING: Large file detected (>100MB) - may affect performance
[14:20:45] ERROR: Script execution failed - Permission denied
[14:15:30] WARNING: Low disk space in output directory
[14:10:12] WARNING: GPU memory usage above 90%
[14:05:33] WARNING: Network connection unstable
[14:00:01] WARNING: Scheduled task delayed due to system load""")
        
        layout.addWidget(self.error_log_display)
        
        return widget
        

    def setup_connections(self):
        """Setup signal connections."""
        # Workflow builder
        self.workflows_list.itemSelectionChanged.connect(self.load_workflow_details)
        self.new_workflow_btn.clicked.connect(self.new_workflow)
        self.run_workflow_btn.clicked.connect(self.run_workflow)
        self.add_step_btn.clicked.connect(self.add_workflow_step)
        
        # Batch operations
        self.operation_combo.currentTextChanged.connect(self.update_operation_params)
        self.start_batch_btn.clicked.connect(self.start_batch_operation)
        self.browse_source_btn.clicked.connect(self.browse_source_folder)
        self.browse_output_btn.clicked.connect(self.browse_output_folder)
        
        # Scheduler
        self.create_task_btn.clicked.connect(self.new_task)
        self.save_task_btn.clicked.connect(self.save_scheduled_task)
        self.edit_task_btn.clicked.connect(self.load_task_details)
        self.delete_task_btn.clicked.connect(self.delete_scheduled_task)
        self.enable_task_btn.clicked.connect(lambda checked=False: self.set_task_enabled(True))
        self.disable_task_btn.clicked.connect(lambda checked=False: self.set_task_enabled(False))
        self.test_task_btn.clicked.connect(self.test_task)
        self.run_now_btn.clicked.connect(self.run_task_now)
        self.scheduled_tasks_table.itemSelectionChanged.connect(self.load_task_details)
        self.schedule_type_combo.currentTextChanged.connect(self._update_schedule_controls)


        # File watcher
        self.add_watch_btn.clicked.connect(self.add_watch_folder)
        self.start_watching_btn.clicked.connect(self.start_file_watching)
        self.stop_watching_btn.clicked.connect(self.stop_file_watching)
        self.remove_watch_btn.clicked.connect(self.remove_watch_folder)
        
    def load_sample_data(self):
        """Load sample workflow data."""
        # Sample workflow steps
        self.steps_table.setRowCount(4)
        
        steps = [
            ("1", "Load Models", "source_folder='./input'", "Always"),
            ("2", "Validate", "check_geometry=True", "If valid"),
            ("3", "Convert Format", "target='gltf'", "Always"),
            ("4", "Save Results", "output_folder='./output'", "Always")
        ]
        
        for row, (step, action, params, condition) in enumerate(steps):
            self.steps_table.setItem(row, 0, QTableWidgetItem(step))
            self.steps_table.setItem(row, 1, QTableWidgetItem(action))
            self.steps_table.setItem(row, 2, QTableWidgetItem(params))
            self.steps_table.setItem(row, 3, QTableWidgetItem(condition))
            
    def load_workflow_details(self):
        """Load details for selected workflow."""
        current_item = self.workflows_list.currentItem()
        if current_item:
            workflow_name = current_item.text()
            # Remove emoji prefix for name
            clean_name = workflow_name.split(' ', 1)[1] if ' ' in workflow_name else workflow_name
            self.workflow_name_edit.setText(clean_name)
            self.workflow_description_edit.setPlainText(f"Description for {clean_name}")
            
    def new_workflow(self):
        """Create a new workflow."""
        self.workflow_name_edit.clear()
        self.workflow_description_edit.clear()
        self.steps_table.setRowCount(0)
        
    def run_workflow(self):
        """Run the selected workflow."""
        workflow_name = self.workflow_name_edit.text()
        if not workflow_name:
            QMessageBox.warning(self, "Warning", "Please select or create a workflow first!")
            return
        
        # Create workflow from UI data
        workflow = Workflow(
            name=workflow_name,
            description=self.workflow_description_edit.toPlainText()
        )
        
        # Add steps from table
        for row in range(self.steps_table.rowCount()):
            step_name = self.steps_table.item(row, 1).text() if self.steps_table.item(row, 1) else "Step"
            step_params = self.steps_table.item(row, 2).text() if self.steps_table.item(row, 2) else "{}"
            
            params, problem = self._parse_parameters(step_params)
            if problem:
                QMessageBox.warning(self, "Warning", f"Step '{step_name}': {problem}")
                return
            step = WorkflowStep(
                name=step_name,
                action=step_name.lower().replace(' ', '_'),
                parameters=params
            )
            workflow.add_step(step)
        
        # Execute workflow using automation engine
        self.run_workflow_btn.setEnabled(False)
        self.stop_workflow_btn.setEnabled(True)
        
        self.automation_engine.execute_workflow(workflow)
        
    def on_workflow_started(self, workflow_id):
        """Handle workflow started signal from engine."""
        self.batch_log.appendPlainText(f"Workflow {workflow_id} started...")
        if hasattr(self, 'activity_list'):
             timestamp = datetime.now().strftime("%H:%M:%S")
             self.activity_list.addItem(f"[{timestamp}] Workflow {workflow_id} started")
        
    def on_workflow_completed_engine(self, workflow_id, results):
        """Handle workflow completion from engine."""
        self.run_workflow_btn.setEnabled(True)
        self.stop_workflow_btn.setEnabled(False)
        if hasattr(self, 'activity_list'):
             timestamp = datetime.now().strftime("%H:%M:%S")
             self.activity_list.addItem(f"[{timestamp}] Workflow {workflow_id} completed")
        QMessageBox.information(self, "Success", f"Workflow completed!\nResults: {results}")
        
    def on_workflow_failed(self, workflow_id, error):
        """Handle workflow failure from engine."""
        self.run_workflow_btn.setEnabled(True)
        self.stop_workflow_btn.setEnabled(False)
        if hasattr(self, 'activity_list'):
             timestamp = datetime.now().strftime("%H:%M:%S")
             self.activity_list.addItem(f"[{timestamp}] Workflow {workflow_id} failed: {error}")
        QMessageBox.critical(self, "Error", f"Workflow failed: {error}")
        
    def on_workflow_progress(self, workflow_id, step_index, total_steps, step_name):
        """Handle workflow progress from engine."""
        progress = int((step_index / total_steps) * 100)
        self.batch_progress.setValue(progress)
        self.batch_status_label.setText(f"Step {step_index}/{total_steps}: {step_name}")
        
    def on_task_started(self, task_id):
        """Note that a run began; the verdict arrives on task_completed."""
        task = self.automation_engine.tasks.get(task_id)
        self._log_activity(f"Task '{task.name if task else task_id}' started")

    def on_task_completed(self, task_id, success, result):
        """Report what a run really did, from whichever thread asked for it."""
        task = self.automation_engine.tasks.get(task_id)
        name = task.name if task else task_id
        detail = result.get('result') if isinstance(result, dict) else result
        if success:
            self._log_activity(f"Task '{name}' completed: {detail or 'it printed nothing'}")
        else:
            reason = result.get('error') if isinstance(result, dict) else result
            self._log_activity(f"Task '{name}' FAILED: {reason or 'no reason given'}")
        self.refresh_task_table()

    def _log_activity(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.activity_list.addItem(f"[{stamp}] {message}")


    def on_file_created(self, file_path):
        """One new file in a watched folder: log it, then run the Auto Actions."""
        self._log_watch_event('created', file_path)
        self._run_auto_actions(file_path)

    def on_file_modified(self, file_path):
        self._log_watch_event('modified', file_path)
        self._run_auto_actions(file_path)

    def on_file_deleted(self, file_path):
        self._log_watch_event('deleted', file_path)

    def on_file_moved(self, old_path, new_path):
        self._log_watch_event('moved', f"{old_path} -> {new_path}")
        self._run_auto_actions(new_path)

    def _log_watch_event(self, event, detail):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.file_events_log.appendPlainText(f"[{timestamp}] File {event}: {detail}")

    def on_auto_actions_finished(self, file_path, outcomes):
        """Put a worker's action results in the same log as the events that caused them."""
        for line in outcomes:
            self.file_events_log.appendPlainText(f"    {line}")

    def _auto_action_settings(self):
        """Snapshot the Auto Actions pane here so the worker thread never reads a widget."""
        return {
            'import': self.auto_import_cb.isChecked(),
            'validate': self.auto_validate_cb.isChecked(),
            'thumbnail': self.auto_thumbnail_cb.isChecked(),
            'backup': self.auto_backup_cb.isChecked(),
            'script': self.script_path_edit.text().strip() if self.run_script_cb.isChecked() else '',
        }

    def _auto_action_summary(self):
        labels = [(self.auto_import_cb, 'Import'), (self.auto_validate_cb, 'Validate'),
                  (self.auto_thumbnail_cb, 'Thumbnail'), (self.auto_backup_cb, 'Backup'),
                  (self.run_script_cb, 'Script')]
        chosen = [label for box, label in labels if box.isChecked()]
        return ', '.join(chosen) if chosen else 'None'

    def _run_auto_actions(self, file_path):
        """Run the checked actions in a worker and report back through a signal.

        Import, validate and thumbnail each load the mesh, which takes seconds on a real
        model; doing that inside the event slot would freeze the window on every file the
        watcher finds.
        """
        settings = self._auto_action_settings()
        if not any(settings.values()):
            return
        threading.Thread(target=self._emit_auto_actions, args=(file_path, settings),
                         daemon=True).start()

    def _emit_auto_actions(self, file_path, settings):
        try:
            outcomes = self._perform_auto_actions(file_path, settings)
        except Exception as error:
            outcomes = [f"auto actions failed: {error}"]
        self.auto_actions_finished.emit(file_path, outcomes)

    def _perform_auto_actions(self, file_path, settings):
        """Do every checked action and return one truthful line about each."""
        outcomes = []
        if settings['import']:
            outcomes.append(self._auto_import(file_path))
        if settings['validate']:
            outcomes.append(self._auto_validate(file_path))
        if settings['thumbnail']:
            outcomes.append(self._auto_thumbnail(file_path))
        if settings['backup']:
            outcomes.append(self._auto_backup(file_path))
        if settings['script']:
            outcomes.append(self._auto_run_script(file_path, settings['script']))
        return outcomes

    def _library_instance(self):
        """The library the auto actions write to, built on first use.

        Assigning `self._library` before the first event hands the actions a different
        database - which is how the contract tests keep out of the user's real library.
        """
        if self._library is None:
            from ..core.library_manager import LibraryManager
            self._library = LibraryManager()
        return self._library

    def _auto_import(self, file_path):
        """Add the file through the same call the Library tab's own import uses."""
        ext = os.path.splitext(file_path)[1].lower()
        try:
            from ..core.library_manager import SUPPORTED_MODEL_EXTS
            manager = self._library_instance()
        except Exception as error:
            return f"auto import failed: {error}"
        if ext not in SUPPORTED_MODEL_EXTS:
            return f"auto import: skipped, {ext or 'no extension'} is not a model format"
        try:
            added, updated = manager.import_files([file_path])
        except Exception as error:
            return f"auto import failed: {error}"
        if added:
            return "auto import: added to library"
        if updated:
            return "auto import: updated in library"
        return "auto import: nothing added - the library could not read this file"

    def _auto_validate(self, file_path):
        try:
            from ..features.quality_analyzer import QualityAnalyzer
            report = QualityAnalyzer().analyze_quality(file_path)
        except Exception as error:
            return f"auto validate failed: {error}"
        if not isinstance(report, dict) or 'score' not in report:
            return "auto validate: no report - the analyser could not read this file"
        issues = report.get('issues') or []
        return (f"auto validate: {report['score']}/100 grade {report.get('grade', '?')}, "
                f"{len(issues)} issue(s)")

    def _auto_thumbnail(self, file_path):
        """Rebuild this model's thumbnail where the Library tab reads it from."""
        try:
            path = self._library_instance().refresh_thumbnail(file_path)
        except Exception as error:
            return f"auto thumbnail failed: {error}"
        if path and os.path.isfile(path):
            return f"auto thumbnail: {os.path.basename(path)} ({os.path.getsize(path)} bytes)"
        return "auto thumbnail: nothing rendered - this build cannot shade a preview"

    def _auto_backup(self, file_path):
        folder = os.path.join(os.path.dirname(file_path) or '.', BACKUP_SUBFOLDER)
        try:
            os.makedirs(folder, exist_ok=True)
            target = os.path.join(folder, os.path.basename(file_path))
            shutil.copy2(file_path, target)
            if os.path.getsize(target) != os.path.getsize(file_path):
                return f"auto backup: {os.path.basename(target)} is a different size than the original"
            return f"auto backup: copied to {folder}"
        except Exception as error:
            return f"auto backup failed: {error}"

    def _auto_run_script(self, file_path, script_path):
        """Run the user's own script with the watched file as its argument."""
        if not os.path.isfile(script_path):
            return f"custom script: {script_path} is not a file"
        python = sys.executable
        if getattr(sys, 'frozen', False):
            python = shutil.which('python') or shutil.which('python3') or shutil.which('py')
            if not python:
                return "custom script: the packaged app found no Python interpreter to run it"
        try:
            done = subprocess.run([python, script_path, file_path], capture_output=True,
                                  text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return "custom script: timed out after 300s"
        except Exception as error:
            return f"custom script failed: {error}"
        if done.returncode == 0:
            lines = (done.stdout or '').strip().splitlines()
            return "custom script: ok" + (f" - {lines[-1]}" if lines else '')
        lines = (done.stderr or done.stdout or '').strip().splitlines()
        return f"custom script exited {done.returncode}" + (f": {lines[-1]}" if lines else '')

    def on_batch_progress(self, current, total, current_file):
        """Handle batch processing progress."""
        progress = int((current / total) * 100)
        self.batch_progress.setValue(progress)
        self.batch_status_label.setText(f"Processing {current}/{total}: {current_file}")
        
    def on_batch_completed_engine(self, results):
        """Handle batch completion from engine."""
        self.start_batch_btn.setEnabled(True)
        self.pause_batch_btn.setEnabled(False)
        self.stop_batch_btn.setEnabled(False)
        self.batch_status_label.setText("Batch operation completed!")
        self.batch_log.appendPlainText(f"Completed: {results}")
        

    def add_workflow_step(self):
        """Add a new workflow step."""
        row = self.steps_table.rowCount()
        self.steps_table.setRowCount(row + 1)
        
        self.steps_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.steps_table.setItem(row, 1, QTableWidgetItem("New Action"))
        self.steps_table.setItem(row, 2, QTableWidgetItem("parameters"))
        self.steps_table.setItem(row, 3, QTableWidgetItem("Always"))
        
    def update_operation_params(self):
        """Update operation parameters based on selected operation."""
        operation = self.operation_combo.currentText()
        
        # Hide all parameter groups
        self.format_group.setVisible(False)
        self.lod_group.setVisible(False)
        
        # Show relevant parameter group
        if operation == "Format Conversion":
            self.format_group.setVisible(True)
        elif operation == "LOD Generation":
            self.lod_group.setVisible(True)
            
    def start_batch_operation(self):
        """Start batch operation."""
        source = self.source_path_edit.text()
        if not source:
            QMessageBox.warning(self, "Warning", "Please select a source folder!")
            return
            
        self.start_batch_btn.setEnabled(False)
        self.pause_batch_btn.setEnabled(True)
        self.stop_batch_btn.setEnabled(True)
        if self.batch_progress_value >= 100:
            self.batch_timer.stop()
            self.start_batch_btn.setEnabled(True)
            self.pause_batch_btn.setEnabled(False)
            self.stop_batch_btn.setEnabled(False)
            self.batch_status_label.setText("Batch operation completed!")
            self.batch_log.appendPlainText("Batch operation completed successfully.")
            
    def browse_source_folder(self):
        """Browse for source folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            self.source_path_edit.setText(folder)
            
    def browse_output_folder(self):
        """Browse for output folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_path_edit.setText(folder)
            
    def _task_action_choices(self):
        """The actions a task can name, read from the registry rather than typed here."""
        choices = []
        for action_id, meta in sorted(ActionRegistry.get_all_actions().items()):
            description = (meta.get('description') or '').strip()
            choices.append((action_id, f"{action_id} - {description}" if description else action_id))
        return choices

    def _parse_parameters(self, text):
        """Read the parameters box as a JSON object; nothing is evaluated.

        This cell used to be handed to eval(), so a pasted line or a workflow file from
        anywhere could run any python the app had the rights to.
        """
        raw = (text or '').strip()
        if not raw:
            return {}, None
        candidates = [raw] if raw.startswith('{') else [raw, '{' + raw + '}']
        for candidate in candidates:
            for loader in (json.loads, ast.literal_eval):
                try:
                    value = loader(candidate)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(value, dict):
                    return {str(key): item for key, item in value.items()}, None
        return None, ('the parameters are not a set of name/value pairs. Try '
                      '"levels": 3 or {"path": "D:/models/hero.obj"}')

    def _validate_parameters(self, action_id, params):
        """What the registry would refuse, said before it gets the chance."""
        spec = (ActionRegistry.get_all_actions().get(action_id) or {}).get('parameters') or {}
        checks = {'str': str, 'int': int, 'float': (int, float), 'bool': bool}
        complaints = []
        for name, rule in spec.items():
            if rule.get('required') and name not in params:
                complaints.append(f"{action_id} needs a value for '{name}'")
            elif name in params:
                expected = checks.get(rule.get('type'))
                if expected and not isinstance(params[name], expected):
                    complaints.append(f"'{name}' must be {rule.get('type')}, "
                                      f"not {type(params[name]).__name__}")
        unknown = sorted(key for key in params if key not in spec)
        if unknown:
            complaints.append(f"{action_id} has no parameter named: " + ', '.join(unknown))
        return complaints

    def _task_schedule_spec(self):
        """Compose the schedule string the engine reads, or say why there is not one."""
        kind = self.schedule_type_combo.currentText()
        clock = self.schedule_time_edit.time().toString('HH:mm')
        if kind == 'One Time':
            when = f"{self.schedule_date_edit.date().toString('yyyy-MM-dd')}T{clock}"
            if datetime.strptime(when, '%Y-%m-%dT%H:%M') <= datetime.now():
                return None, (f"{when} has already passed. Choose a moment in the future, "
                              "or leave the task unscheduled and run it by hand.")
            return f"once:{when}", None
        if kind == 'Hourly':
            return 'hourly', None
        if kind in ('Daily', 'Weekly', 'Monthly'):
            return f"{kind.lower()}@{clock}", None
        if kind == 'Repeated interval':
            return (f"every_{self.repeat_interval_spin.value()}_"
                    f"{self.repeat_unit_combo.currentText().lower()}"), None
        return None, f"'{kind}' is not a schedule this app knows."

    def _update_schedule_controls(self):
        """Turn off the fields the chosen schedule type cannot use."""
        kind = self.schedule_type_combo.currentText()
        self.schedule_date_edit.setEnabled(kind == 'One Time')
        self.schedule_time_edit.setEnabled(kind in ('One Time', 'Daily', 'Weekly', 'Monthly'))
        repeated = kind == 'Repeated interval'
        self.repeat_interval_spin.setEnabled(repeated)
        self.repeat_unit_combo.setEnabled(repeated)

    def _selected_task_id(self):
        row = self.scheduled_tasks_table.currentRow()
        if 0 <= row < len(self._task_rows):
            return self._task_rows[row]
        return None

    def refresh_task_table(self):
        """Rebuild the list from the engine, which is where the tasks live."""
        tasks = sorted(self.automation_engine.tasks.values(), key=lambda item: item.created_at)
        self._task_rows = [task.task_id for task in tasks]
        self.scheduled_tasks_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            if task.error:
                outcome = task.error
            elif isinstance(task.result, dict):
                outcome = str(task.result.get('result') or task.result.get('error') or '')
            else:
                outcome = str(task.result or '')
            next_run = self.automation_engine.next_run(task.task_id)
            cells = [task.name, task.task_type, task.schedule_time or 'not scheduled',
                     next_run.strftime('%Y-%m-%d %H:%M') if next_run else '-',
                     task.status.value + ('' if task.enabled else ' (disabled)'), outcome]
            for column, value in enumerate(cells):
                self.scheduled_tasks_table.setItem(row, column, QTableWidgetItem(value))
        self.update_dashboard_metrics()

    def new_task(self):
        """Clear the editor so a task can be written from scratch."""
        self.current_task_id = None
        self.task_name_edit.clear()
        self.task_actions_edit.clear()
        self.task_enabled_cb.setChecked(True)
        self.schedule_type_combo.setCurrentText('Daily')
        self.scheduled_tasks_table.clearSelection()
        self.task_name_edit.setFocus()

    def save_scheduled_task(self):
        """Write the editor's task into the engine and put it on the schedule."""
        name = self.task_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Warning", "Give the task a name before saving it.")
            return
        action_id = self.task_type_combo.currentData()
        if not action_id:
            QMessageBox.warning(self, "Warning",
                                "No actions are registered, so there is nothing to run.")
            return
        params, problem = self._parse_parameters(self.task_actions_edit.toPlainText())
        if problem:
            QMessageBox.warning(self, "Warning", problem)
            return
        complaints = self._validate_parameters(action_id, params)
        if complaints:
            QMessageBox.warning(self, "Warning", "\n".join(complaints))
            return
        spec, schedule_problem = self._task_schedule_spec()
        if schedule_problem:
            QMessageBox.warning(self, "Warning", schedule_problem)
            return

        enabled = self.task_enabled_cb.isChecked()
        if self.current_task_id in self.automation_engine.tasks:
            task_id = self.current_task_id
            self.automation_engine.update_task(task_id, name=name, task_type=action_id,
                                               parameters=params, enabled=enabled)
        else:
            task_id = self.automation_engine.create_task(name, action_id, params, enabled=enabled)
            self.current_task_id = task_id

        self.automation_engine.cancel_task(task_id)
        if enabled and not self.automation_engine.schedule_task(task_id, spec):
            self.refresh_task_table()
            QMessageBox.warning(self, "Warning",
                                f"The task is saved, but '{spec}' is not a schedule this app "
                                "can honour, so it will not run on its own.")
            return
        self.refresh_task_table()

    def load_task_details(self):
        """Point the editor at the selected task."""
        task_id = self._selected_task_id()
        task = self.automation_engine.tasks.get(task_id) if task_id else None
        if task is None:
            return
        self.current_task_id = task.task_id
        self.task_name_edit.setText(task.name)
        index = self.task_type_combo.findData(task.task_type)
        if index >= 0:
            self.task_type_combo.setCurrentIndex(index)
        self.task_enabled_cb.setChecked(task.enabled)
        self.task_actions_edit.setPlainText(
            json.dumps(task.parameters, indent=2) if task.parameters else '')

    def delete_scheduled_task(self):
        """Take the selected task off the schedule and out of the file."""
        task_id = self._selected_task_id()
        task = self.automation_engine.tasks.get(task_id) if task_id else None
        if task is None:
            QMessageBox.warning(self, "Warning", "Select a task in the list first.")
            return
        answer = QMessageBox.question(
            self, "Delete Task", f"Delete the scheduled task '{task.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.automation_engine.delete_task(task_id)
        if self.current_task_id == task_id:
            self.current_task_id = None
        self.refresh_task_table()

    def set_task_enabled(self, enabled):
        """Enable or disable the selected task, and its schedule with it."""
        task_id = self._selected_task_id()
        if task_id is None or not self.automation_engine.set_task_enabled(task_id, enabled):
            QMessageBox.warning(self, "Warning", "Select a task in the list first.")
            return
        if self.current_task_id == task_id:
            self.task_enabled_cb.setChecked(enabled)
        self.refresh_task_table()

    def test_task(self):
        """Say whether the editor's task could run, without running it."""
        action_id = self.task_type_combo.currentData()
        params, problem = self._parse_parameters(self.task_actions_edit.toPlainText())
        complaints = [problem] if problem else self._validate_parameters(action_id, params)
        spec, schedule_problem = self._task_schedule_spec()
        if schedule_problem:
            complaints.append(schedule_problem)
        if complaints:
            QMessageBox.warning(self, "Task cannot run", "\n".join(complaints))
            return
        name = self.task_name_edit.text().strip() or '(no name)'
        QMessageBox.information(
            self, "Task is ready",
            f"'{name}' would run {action_id} with {json.dumps(params) or 'no parameters'}, "
            + (f"on the schedule {spec}." if spec else "and only when you press Run Now."))

    def run_task_now(self):
        """Run the selected task on a worker thread; the verdict comes back by signal."""
        task_id = self._selected_task_id()
        if task_id is None:
            QMessageBox.warning(self, "Warning", "Select a task in the list first.")
            return
        threading.Thread(target=self.automation_engine.execute_task,
                         args=(task_id,), daemon=True).start()


    def add_watch_folder(self):
        """Add a folder to the watch list, with the filter the settings pane shows."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Watch")
        if not folder:
            return

        file_filter = self.file_extensions_edit.text().strip() or "*"
        self.watch_requests[folder] = file_filter

        row = self._watch_row(folder)
        if row is None:
            row = self.watch_folders_table.rowCount()
            self.watch_folders_table.insertRow(row)
            self.watch_folders_table.setItem(row, 0, QTableWidgetItem(folder))
            self.watch_folders_table.setItem(row, 2, QTableWidgetItem(self._auto_action_summary()))
            self.watch_folders_table.setItem(row, 3, QTableWidgetItem("Ready"))

        self.watch_folders_table.setItem(row, 1, QTableWidgetItem(file_filter))
        self.watch_folders_table.item(row, 2).setText(self._auto_action_summary())

        if self.file_watcher.is_watching:
            try:
                self._register_watch(folder)
                self.file_events_log.appendPlainText(f"Now watching {folder}.")
            except ValueError as error:
                self.watch_folders_table.item(row, 3).setText("Missing folder")
                self.file_events_log.appendPlainText(f"Not watching {folder}: {error}")

    def _watch_row(self, folder):
        for row in range(self.watch_folders_table.rowCount()):
            item = self.watch_folders_table.item(row, 0)
            if item and item.text() == folder:
                return row
        return None

    def remove_watch_folder(self):
        """Take the selected folder off the watch list and out of the running watcher."""
        row = self.watch_folders_table.currentRow()
        if row < 0:
            self.file_events_log.appendPlainText("Select a folder in the list first.")
            return
        folder = self.watch_folders_table.item(row, 0).text()
        self.watch_folders_table.removeRow(row)
        self.watch_requests.pop(folder, None)
        self.file_watcher.unwatch_directory(folder)
        self.file_events_log.appendPlainText(f"Removed {folder} from the watch list.")
        self.update_dashboard_metrics()

    def _watch_settings(self):
        """The Watcher Configuration pane, as the arguments the engine takes."""
        events = []
        if self.watch_created_cb.isChecked():
            events.append('created')
        if self.watch_modified_cb.isChecked():
            events.append('modified')
        if self.watch_deleted_cb.isChecked():
            events.append('deleted')
        if self.watch_moved_cb.isChecked():
            events.append('moved')
        return {
            'file_pattern': self.file_extensions_edit.text().strip() or '*',
            'event_type': events,
            'exclude_patterns': self.exclude_patterns_edit.text().strip(),
            'min_size_kb': self.min_file_size_spin.value(),
        }

    def _register_watch(self, folder):
        """Give one folder its filters and mark it watched."""
        settings = self._watch_settings()
        self.file_watcher.watch_directory(
            folder, None, settings['file_pattern'], settings['event_type'],
            settings['exclude_patterns'], settings['min_size_kb'])
        row = self._watch_row(folder)
        if row is not None:
            self.watch_folders_table.item(row, 3).setText("Watching")
            self.watch_folders_table.item(row, 1).setText(settings['file_pattern'])

    def start_file_watching(self):
        """Hand every listed folder to the real watcher, using this pane's settings."""
        if not self.watch_requests:
            self.file_events_log.appendPlainText("Nothing to watch - use Add Watch Folder first.")
            return

        settings = self._watch_settings()
        if not settings['event_type']:
            self.file_events_log.appendPlainText(
                "No watch events selected - tick at least one under Watch Events.")
            return

        registered = 0
        for folder in list(self.watch_requests):
            try:
                self._register_watch(folder)
                registered += 1
            except ValueError as error:
                row = self._watch_row(folder)
                if row is not None:
                    self.watch_folders_table.item(row, 3).setText("Missing folder")
                self.file_events_log.appendPlainText(f"Not watching {folder}: {error}")

        if registered == 0:
            return

        self.file_watcher.start_watching()
        self.start_watching_btn.setEnabled(False)
        self.stop_watching_btn.setEnabled(True)
        self.file_events_log.appendPlainText(
            f"Watching {registered} folder(s) for {', '.join(settings['event_type'])} "
            f"(filter {settings['file_pattern']}, over {settings['min_size_kb']} KB; "
            f"auto actions: {self._auto_action_summary().lower()}).")
        self.update_dashboard_metrics()

    def stop_file_watching(self):
        """Stop the watcher and say so in the log the events go to."""
        self.file_watcher.stop_watching()
        self.start_watching_btn.setEnabled(True)
        self.stop_watching_btn.setEnabled(False)
        for folder in self.watch_requests:
            row = self._watch_row(folder)
            if row is not None:
                self.watch_folders_table.item(row, 3).setText("Stopped")
        self.file_events_log.appendPlainText("File watching stopped.")
        self.update_dashboard_metrics()

    def update_dashboard_metrics(self):
        """Update dashboard status cards with real data."""
        # Active Workflows
        active_count = len(self.active_workflows)
        if hasattr(self, 'active_workflows_label'):
            self.active_workflows_label.setText(str(active_count))
        
        # Scheduled Tasks
        task_count = len(self.automation_engine.tasks)
        if hasattr(self, 'scheduled_tasks_label'):
            self.scheduled_tasks_label.setText(str(task_count))
        
        # File Watchers
        watcher_count = len(self.file_watcher.watched_directories)
        if hasattr(self, 'file_watchers_label'):
            self.file_watchers_label.setText(str(watcher_count))