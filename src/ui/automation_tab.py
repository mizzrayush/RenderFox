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
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QTime, QDate
from PyQt6.QtGui import QFont, QColor, QIcon
from .icon_provider import get_icon

# Import automation engine
from ..features.automation_engine import (
    AutomationEngine, FileWatcher, WorkflowStep, ActionRegistry
)


BACKUP_SUBFOLDER = ".renderfox_backups"


class AutomationTab(QWidget):
    """Automation and workflow management interface."""
    
    auto_actions_finished = pyqtSignal(str, list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Initialize automation engine
        self.automation_engine = AutomationEngine()
        self.file_watcher = FileWatcher()
        # Workflows and batches both run inside the engine; the pane only reports what it started.
        
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
        
        engine_processor = self.automation_engine.batch_processor
        engine_processor.progress_updated.connect(self.on_batch_progress)
        engine_processor.batch_completed.connect(self.on_batch_completed_engine)
        
        self.active_workflows = {}
        self.watch_requests = {}
        self._library = None
        self._task_rows = []
        self.current_task_id = None
        self._rebuilding_list = False
        self.current_workflow_id = None
        self._workflow_rows = []
        self._running_workflow = None
        self.init_ui()
        self.setup_connections()
        self.refresh_workflow_list()
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
        self.new_workflow_btn.setToolTip("Clear the editor and start a workflow")
        
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
        self.load_workflow_btn.setToolTip("Read a workflow file into the app")
        
        self.save_workflow_btn = QPushButton("Save")
        self.save_workflow_btn.setIcon(get_icon("backup"))
        self.save_workflow_btn.setToolTip("Store this workflow in the app")
        
        toolbar_row2.addWidget(self.load_workflow_btn)
        toolbar_row2.addWidget(self.save_workflow_btn)
        workflows_layout.addLayout(toolbar_row2)
        
        # Workflows list (expanding to fill left column)
        self.workflows_list = QListWidget()
        self.workflows_list.setAlternatingRowColors(True)
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
        self.steps_table.setColumnCount(5)
        self.steps_table.setHorizontalHeaderLabels(["#", "Step", "Action", "Parameters",
                                                    "On error"])
        self.steps_table.setMinimumHeight(240)
        self.steps_table.setAlternatingRowColors(True)
        self.steps_table.verticalHeader().setDefaultSectionSize(34)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.horizontalHeader().setStretchLastSection(False)
        self.steps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.steps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.steps_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.steps_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.setColumnWidth(1, 150)
        self.steps_table.setColumnWidth(2, 230)
        self.steps_table.setColumnWidth(4, 110)
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
        self.run_workflow_btn.setToolTip("Save this workflow and run it")
        self.test_workflow_btn.setToolTip("Check every step without running any of it")
        self.run_workflow_btn.setProperty("primary", "true")
        
        self.stop_workflow_btn = QPushButton("Stop")
        self.stop_workflow_btn.setIcon(get_icon("delete"))
        self.stop_workflow_btn.setToolTip("Stop after the step now running")
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
        """Batch pane: one registry action repeated over a list of real files.

        Every control here changes a call the app can make: the operations are the
        registry's own, `Files` picks which files a folder gives up, `Parameters` is read
        by the same parser the task editor uses, and Preview prints the exact arguments
        each file would get. What this tab used to hold - five source types, nine
        operation names, a target-format list and a LOD group - matched no action
        anywhere in the app, and Start Batch fell over on a progress value the file
        only ever mentioned and never assigned.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.controls_group = QGroupBox("Batch Operation Setup")
        controls_layout = QGridLayout()

        controls_layout.addWidget(QLabel("Source:"), 0, 0)
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItems(["Folder", "Model Library"])
        controls_layout.addWidget(self.source_type_combo, 0, 1)

        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Folder the files are read from...")
        controls_layout.addWidget(self.source_path_edit, 0, 2)

        self.browse_source_btn = QPushButton("Browse")
        self.browse_source_btn.setIcon(get_icon("folder"))
        controls_layout.addWidget(self.browse_source_btn, 0, 3)

        controls_layout.addWidget(QLabel("Files:"), 1, 0)
        self.file_types_edit = QLineEdit()
        self.file_types_edit.setPlaceholderText(
            ".obj .fbx, or * for every file - blank means every model format")
        controls_layout.addWidget(self.file_types_edit, 1, 1, 1, 3)

        controls_layout.addWidget(QLabel("Operation:"), 2, 0)
        self.operation_combo = QComboBox()
        self._fill_batch_operations()
        controls_layout.addWidget(self.operation_combo, 2, 1, 1, 3)

        controls_layout.addWidget(QLabel("Output:"), 3, 0)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Folder the results go to...")
        controls_layout.addWidget(self.output_path_edit, 3, 1, 1, 2)

        self.browse_output_btn = QPushButton("Browse")
        self.browse_output_btn.setIcon(get_icon("folder"))
        controls_layout.addWidget(self.browse_output_btn, 3, 3)

        controls_layout.addWidget(QLabel("Parameters:"), 4, 0)
        self.batch_params_edit = QLineEdit()
        self.batch_params_edit.setPlaceholderText(
            '"levels": 2   or   "command": "py export.py {file}"')
        controls_layout.addWidget(self.batch_params_edit, 4, 1, 1, 3)

        self.recursive_cb = QCheckBox("Include subfolders")
        self.recursive_cb.setChecked(True)
        self.overwrite_cb = QCheckBox("Replace a file already in the output folder")
        self.backup_cb = QCheckBox(f"Copy each file into {BACKUP_SUBFOLDER} first")
        self.backup_cb.setChecked(True)
        controls_layout.addWidget(self.recursive_cb, 5, 0, 1, 4)
        controls_layout.addWidget(self.overwrite_cb, 6, 0, 1, 4)
        controls_layout.addWidget(self.backup_cb, 7, 0, 1, 4)

        self.batch_hint_label = QLabel()
        self.batch_hint_label.setWordWrap(True)
        controls_layout.addWidget(self.batch_hint_label, 8, 0, 1, 4)

        self.controls_group.setLayout(controls_layout)
        layout.addWidget(self.controls_group)

        execution_group = QGroupBox("Batch Execution")
        execution_layout = QVBoxLayout()

        progress_layout = QHBoxLayout()
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 100)
        self.batch_progress.setValue(0)
        self.batch_status_label = QLabel("Nothing has run yet.")
        progress_layout.addWidget(self.batch_progress)
        progress_layout.addWidget(self.batch_status_label)
        execution_layout.addLayout(progress_layout)

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

        self.batch_log = QPlainTextEdit()
        self.batch_log.setMaximumHeight(160)
        self.batch_log.setReadOnly(True)
        execution_layout.addWidget(self.batch_log)

        execution_group.setLayout(execution_layout)
        layout.addWidget(execution_group)

        self._update_batch_controls()

        return widget

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
        self.save_workflow_btn.clicked.connect(self.save_workflow)
        self.load_workflow_btn.clicked.connect(self.load_workflow_file)
        self.duplicate_workflow_btn.clicked.connect(self.duplicate_selected_workflow)
        self.delete_workflow_btn.clicked.connect(self.delete_selected_workflow)
        self.run_workflow_btn.clicked.connect(self.run_workflow)
        self.test_workflow_btn.clicked.connect(self.test_workflow)
        self.stop_workflow_btn.clicked.connect(self.stop_workflow_run)
        self.add_step_btn.clicked.connect(lambda checked=False: self.add_workflow_step())
        self.remove_step_btn.clicked.connect(self.remove_workflow_step)
        self.move_up_btn.clicked.connect(lambda checked=False: self.move_workflow_step(True))
        self.move_down_btn.clicked.connect(lambda checked=False: self.move_workflow_step(False))
        
        # Batch operations
        self.source_type_combo.currentTextChanged.connect(self._update_batch_controls)
        self.operation_combo.currentIndexChanged.connect(self._update_batch_controls)
        self.start_batch_btn.clicked.connect(self.start_batch_operation)
        self.pause_batch_btn.clicked.connect(self.toggle_batch_pause)
        self.stop_batch_btn.clicked.connect(self.stop_batch_operation)
        self.preview_batch_btn.clicked.connect(self.preview_batch)
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
        
    # --- Workflow Builder ------------------------------------------------------
    def refresh_workflow_list(self):
        """Rebuild the list from the engine, which is where workflows live.

        The pane used to open on names no object anywhere described, so it could show a
        workflow nothing could run while hiding every one the user had saved. Rebuilding
        is also silent: clearing the list leaves a stale current row, and a handler that
        read it would put the editor back on a workflow the user had just left.
        """
        wanted = self.current_workflow_id
        self._rebuilding_list = True
        try:
            self._workflow_rows = [workflow.workflow_id for workflow in
                                   sorted(self.automation_engine.workflows.values(),
                                          key=lambda item: item.created_at)]
            self.workflows_list.clear()
            for workflow_id in self._workflow_rows:
                workflow = self.automation_engine.workflows[workflow_id]
                self.workflows_list.addItem(f"{workflow.name} [{workflow.status.value}]")
        finally:
            self._rebuilding_list = False
        if wanted in self._workflow_rows:
            self.workflows_list.setCurrentRow(self._workflow_rows.index(wanted))
        self.update_dashboard_metrics()

    def _step_action_combo(self, action_id=''):
        """A step's Action cell: only ids the registry can actually run."""
        combo = QComboBox()
        for one_id, label in self._task_action_choices():
            combo.addItem(label, one_id)
        index = combo.findData(action_id)
        if index < 0 and action_id:
            combo.insertItem(0, action_id, action_id)
            index = 0
        combo.setCurrentIndex(index)
        return combo

    def _step_error_combo(self, on_error='stop'):
        """A step's On error cell: the three policies the executor really honours."""
        combo = QComboBox()
        for policy in WorkflowStep.ON_ERROR:
            combo.addItem(policy, policy)
        index = combo.findData(on_error)
        combo.setCurrentIndex(index if index >= 0 else 0)
        return combo

    def add_workflow_step(self, name='', action_id='file.copy', parameters='{}',
                          on_error='stop'):
        """Append one step row: a name, a known action, its parameters, its policy."""
        row = self.steps_table.rowCount()
        self.steps_table.insertRow(row)
        self.steps_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.steps_table.setItem(row, 1, QTableWidgetItem(name))
        self.steps_table.setCellWidget(row, 2, self._step_action_combo(action_id))
        self.steps_table.setItem(row, 3, QTableWidgetItem(parameters))
        self.steps_table.setCellWidget(row, 4, self._step_error_combo(on_error))

    def _renumber_steps(self):
        """Keep the row numbers the table claims, after a removal or a move."""
        for row in range(self.steps_table.rowCount()):
            item = self.steps_table.item(row, 0)
            if item is None:
                self.steps_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            else:
                item.setText(str(row + 1))

    def _step_record(self, row):
        """One row as the engine stores it, plus the first reason it cannot run."""
        name_item = self.steps_table.item(row, 1)
        action_combo = self.steps_table.cellWidget(row, 2)
        params_item = self.steps_table.item(row, 3)
        error_combo = self.steps_table.cellWidget(row, 4)
        name = (name_item.text().strip() if name_item else '') or f"step {row + 1}"
        action = action_combo.currentData() if action_combo is not None else ''
        params, problem = self._parse_parameters(params_item.text() if params_item else '')
        if problem:
            return None, f"'{name}': {problem}"
        return ({'name': name, 'action': action, 'parameters': params,
                 'on_error': error_combo.currentData() if error_combo else 'stop'}, None)

    def _workflow_records(self):
        """The whole table as engine records, or the first row that is not one."""
        records = []
        for row in range(self.steps_table.rowCount()):
            record, problem = self._step_record(row)
            if problem:
                return None, problem
            records.append(record)
        return records, None

    def _fill_steps(self, records):
        """Rebuild the table from records - the only way to reorder rows of combo boxes."""
        self.steps_table.setRowCount(0)
        for record in records:
            self.add_workflow_step(record.get('name') or '', record.get('action') or '',
                                   json.dumps(record.get('parameters') or {}),
                                   record.get('on_error') or 'stop')

    def load_workflow_details(self):
        """Put the selected stored workflow in the editor, read from the engine."""
        if self._rebuilding_list:
            return
        row = self.workflows_list.currentRow()
        if not 0 <= row < len(self._workflow_rows):
            return
        workflow = self.automation_engine.workflows.get(self._workflow_rows[row])
        if workflow is None:
            return
        self.current_workflow_id = workflow.workflow_id
        self.workflow_name_edit.setText(workflow.name)
        self.workflow_description_edit.setPlainText(workflow.description or '')
        self._fill_steps([step.to_dict() for step in workflow.steps])

    def new_workflow(self):
        """Clear the editor and detach it from any workflow that is stored."""
        self._rebuilding_list = True
        try:
            self.current_workflow_id = None
            self.workflow_name_edit.clear()
            self.workflow_description_edit.clear()
            self.steps_table.setRowCount(0)
            self.workflows_list.clearSelection()
        finally:
            self._rebuilding_list = False
        self.workflow_name_edit.setFocus()

    def store_workflow(self):
        """Write the editor into the engine, and the engine into its own file.

        Returns the id it is stored under, or None once the reason has been said. Every
        reason comes from `workflow_problems`, so the pane and the engine refuse the same
        set of workflows.
        """
        name = self.workflow_name_edit.text().strip()
        description = self.workflow_description_edit.toPlainText().strip()
        records, problem = self._workflow_records()
        if problem is None:
            complaints = self.automation_engine.workflow_problems(name, records)
            problem = '\n'.join(complaints) if complaints else None
        if problem:
            QMessageBox.warning(self, "This workflow cannot run", problem)
            return None
        workflow_id = self.current_workflow_id
        if workflow_id in self.automation_engine.workflows:
            self.automation_engine.update_workflow(workflow_id, name=name,
                                                   description=description, steps=records)
        else:
            workflow_id = self.automation_engine.create_workflow(name, description, records)
            self.current_workflow_id = workflow_id
        self.refresh_workflow_list()
        return workflow_id

    def save_workflow(self):
        """The Save button: store the editor, then say what was stored."""
        workflow_id = self.store_workflow()
        if workflow_id:
            self._log_activity(f"Saved workflow "
                               f"'{self.workflow_name_edit.text().strip()}' with "
                               f"{self.steps_table.rowCount()} step(s)")

    def run_workflow(self):
        """Store what is on screen, then have the engine run that id.

        Running the *stored* workflow is the point: it is the same record the file holds
        and the same id the engine reports its verdict under. The path this replaced
        built a workflow object here and handed it to a method that wants an id, while a
        separate worker-thread class - built by nobody - slept 500 ms per step and
        reported success.
        """
        workflow_id = self.store_workflow()
        if workflow_id is None:
            return
        if not self.automation_engine.execute_workflow(workflow_id):
            self._log_activity(f"Workflow '{self._workflow_name(workflow_id)}' "
                               "was not started")

    def test_workflow(self):
        """Say what would happen, without running any of it."""
        records, problem = self._workflow_records()
        name = self.workflow_name_edit.text().strip()
        complaints = [] if problem else self.automation_engine.workflow_problems(name, records)
        if problem or complaints:
            QMessageBox.warning(self, "This workflow cannot run",
                                problem or '\n'.join(complaints))
            return
        order = '; '.join(f"{index}. {record['name']} runs {record['action']} "
                          f"(on error: {record['on_error']})"
                          for index, record in enumerate(records, 1))
        QMessageBox.information(self, "Test passed",
                                f"'{name}' would run {len(records)} step(s) in this order:\n"
                                + order)

    def stop_workflow_run(self):
        """Ask the running workflow to leave the steps it has not reached alone."""
        workflow_id = self._running_workflow
        if workflow_id is None:
            QMessageBox.warning(self, "Nothing is running",
                                "This pane has no workflow running that could be stopped.")
            return
        name = self._workflow_name(workflow_id)
        if self.automation_engine.stop_workflow(workflow_id):
            self._log_activity(f"Asking workflow '{name}' to stop at its next step")
        else:
            self._log_activity(f"Workflow '{name}' is no longer in the engine; "
                               "forgetting it here")
            self._finish_run(workflow_id)

    def duplicate_selected_workflow(self):
        """Copy the stored workflow the pane is on; the copy gets its own id."""
        workflow_id = self.current_workflow_id
        copy_id = self.automation_engine.duplicate_workflow(workflow_id) if workflow_id else None
        if copy_id is None:
            QMessageBox.warning(self, "Nothing to duplicate",
                                "Save a workflow first - there is nothing stored to copy.")
            return
        self.current_workflow_id = copy_id
        self.refresh_workflow_list()
        self._log_activity(f"Duplicated to "
                           f"'{self.automation_engine.workflows[copy_id].name}'")

    def delete_selected_workflow(self):
        """Take the stored workflow out of the list, the engine and the file."""
        workflow_id = self.current_workflow_id
        if workflow_id is None:
            QMessageBox.warning(self, "Nothing to delete",
                                "Select a saved workflow, or Save this one first.")
            return
        name = self._workflow_name(workflow_id)
        answer = QMessageBox.question(self, "Delete workflow",
                                      f"Delete '{name}'? It leaves the app and its file too.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.automation_engine.delete_workflow(workflow_id):
            self._log_activity(f"Deleted workflow '{name}'")
        else:
            self._log_activity(f"'{name}' was already not in the engine")
        self.new_workflow()
        self.refresh_workflow_list()

    def remove_workflow_step(self):
        """Drop the chosen step row and renumber what is left."""
        row = self.steps_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No step chosen", "Pick the step row to remove.")
            return
        self.steps_table.removeRow(row)
        self._renumber_steps()

    def move_workflow_step(self, up):
        """Swap the chosen step with its neighbour, in the order the engine will run."""
        row = self.steps_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No step chosen", "Pick the step row to move.")
            return
        target = row - 1 if up else row + 1
        if target < 0 or target >= self.steps_table.rowCount():
            QMessageBox.warning(self, "Nowhere to move",
                                f"Step {row + 1} is already at the "
                                f"{'top' if up else 'bottom'} of the run.")
            return
        records, problem = self._workflow_records()
        if problem:
            QMessageBox.warning(self, "This workflow cannot run", problem)
            return
        records[row], records[target] = records[target], records[row]
        self._fill_steps(records)
        self.steps_table.setCurrentCell(target, 1)

    @staticmethod
    def _workflow_file_records(data):
        """Every importable workflow in a file, whichever shape it arrived in."""
        if isinstance(data, dict):
            if 'steps' in data:
                return [data]
            return [one for one in data.values()
                    if isinstance(one, dict) and 'steps' in one]
        if isinstance(data, list):
            return [one for one in data if isinstance(one, dict) and 'steps' in one]
        return []

    def load_workflow_file(self):
        """Read a workflow file into the app; anything that cannot run is refused by name."""
        path, _ = QFileDialog.getOpenFileName(self, "Load a workflow file", "",
                                              "Workflow JSON (*.json);;All files (*.*)")
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot read that file",
                                f"{os.path.basename(path)}: {error}")
            return
        records = self._workflow_file_records(data)
        if not records:
            QMessageBox.warning(self, "No workflow in that file",
                                f"{os.path.basename(path)} holds no record with a list "
                                "of steps.")
            return
        loaded = []
        refused = []
        for record in records:
            name = record.get('name') or ''
            steps = record.get('steps') or []
            complaints = self.automation_engine.workflow_problems(name, steps)
            if complaints:
                refused.append(f"'{name or 'unnamed'}': " + '; '.join(complaints))
                continue
            loaded.append(self.automation_engine.create_workflow(
                name, record.get('description') or '', steps))
        if loaded:
            self.current_workflow_id = loaded[0]
            self.refresh_workflow_list()
            self._log_activity(f"Loaded {len(loaded)} workflow(s) from "
                               f"{os.path.basename(path)}")
        if refused:
            QMessageBox.warning(self, "Refused by the registry", '\n'.join(refused))

    def _workflow_name(self, workflow_id, result=None):
        workflow = self.automation_engine.workflows.get(workflow_id)
        if workflow is not None:
            return workflow.name
        return (result or {}).get('workflow') or workflow_id

    def on_workflow_started(self, workflow_id):
        """The engine's worker has begun; note it and hand Stop to the user."""
        self._running_workflow = workflow_id
        name = self._workflow_name(workflow_id)
        self.active_workflows[workflow_id] = name
        self._log_activity(f"Workflow '{name}' started")
        self.run_workflow_btn.setEnabled(False)
        self.save_workflow_btn.setEnabled(False)
        self.stop_workflow_btn.setEnabled(True)
        self.update_dashboard_metrics()

    def on_workflow_progress(self, workflow_id, current, total, step_name):
        """Which step the worker is on, in the log this pane owns."""
        self._log_activity(f"'{self._workflow_name(workflow_id)}' "
                           f"step {current}/{total}: {step_name}")

    def on_workflow_completed_engine(self, workflow_id, result):
        """The verdict as the run really found it: no modal, just what happened."""
        self._finish_run(workflow_id)
        name = self._workflow_name(workflow_id, result)
        done = result.get('steps_completed', 0)
        if result.get('stopped'):
            self._log_activity(f"Workflow '{name}' stopped after {done} step(s)")
        else:
            tolerated = result.get('tolerated_failures') or []
            line = (f"Workflow '{name}' completed {done}/"
                    f"{result.get('total_steps', done)} step(s)")
            if tolerated:
                line += f", tolerating {len(tolerated)} failure(s): " + '; '.join(tolerated)
            self._log_activity(line)
        self.refresh_workflow_list()

    def on_workflow_failed(self, workflow_id, error):
        self._finish_run(workflow_id)
        self._log_activity(f"Workflow '{self._workflow_name(workflow_id)}' "
                           f"FAILED: {error or 'no reason given'}")
        self.refresh_workflow_list()

    def _finish_run(self, workflow_id):
        """Give the controls back once a run is over, however it ended."""
        self.active_workflows.pop(workflow_id, None)
        self._running_workflow = None
        self.run_workflow_btn.setEnabled(True)
        self.save_workflow_btn.setEnabled(True)
        self.stop_workflow_btn.setEnabled(False)
        self.update_dashboard_metrics()

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

    # --- Batch Operations --------------------------------------------------------
    def _fill_batch_operations(self):
        """The operations that can be repeated one file at a time, taken from the registry."""
        self.operation_combo.clear()
        for action_id, description in ActionRegistry.batch_actions().items():
            label = f"{action_id} - {description}" if description else action_id
            self.operation_combo.addItem(label, action_id)

    def _batch_action(self):
        return self.operation_combo.currentData()

    def _batch_hint(self, action_id):
        """What this operation will do with a file, said from the binding the engine uses."""
        binding = ActionRegistry.batch_binding(action_id)
        if not binding or len(binding) != 2:
            return (f"{action_id or 'this operation'} does not say how a batch hands it one "
                    'file, so it cannot be repeated here.')
        item_param, folder_param = binding
        if item_param == 'command':
            return ("Runs one command once per file. Write {file} where the file's path "
                    "should appear; the command's exit code is the verdict.")
        if folder_param == 'destination':
            return (f"Reads each file as {item_param} and writes it into the output "
                    f"folder under its own name as {folder_param}.")
        if folder_param:
            return (f"Reads each file as {item_param} and puts whatever it writes in the "
                    f"output folder given as {folder_param}.")
        return f"Runs on each file as {item_param}, and leaves no file of its own."

    def _update_batch_controls(self, *_ignored):
        """Enable only the fields the chosen source and operation can actually use."""
        action = self._batch_action()
        binding = ActionRegistry.batch_binding(action) if action else None
        folder_source = self.source_type_combo.currentText() == 'Folder'
        self.source_path_edit.setEnabled(folder_source)
        self.browse_source_btn.setEnabled(folder_source)
        self.recursive_cb.setEnabled(folder_source)
        writes_a_file = bool(binding and binding[1])
        self.output_path_edit.setEnabled(writes_a_file)
        self.browse_output_btn.setEnabled(writes_a_file)
        self.backup_cb.setEnabled(True)
        self.overwrite_cb.setEnabled(bool(binding and binding[1] == 'destination'))
        self.batch_hint_label.setText(self._batch_hint(action))

    def _batch_extensions(self):
        """The extensions the filter names, or None when it asks for every file."""
        raw = self.file_types_edit.text().strip()
        if not raw:
            from ..core.library_manager import SUPPORTED_MODEL_EXTS
            return {ext.lower() for ext in SUPPORTED_MODEL_EXTS}
        wanted = set()
        for token in raw.replace(',', ' ').replace(';', ' ').replace('|', ' ').split():
            token = token.strip().lstrip('*').lower()
            if not token:
                return None  # a bare * is "every file, whatever it is"
            wanted.add(token if token.startswith('.') else '.' + token)
        return wanted

    def _walk_batch_folder(self, folder, wanted):
        """Every file the folder holds that the filter accepts, backups left out."""
        found = []
        if self.recursive_cb.isChecked():
            for root, dirs, names in os.walk(folder):
                dirs[:] = [one for one in dirs if one != BACKUP_SUBFOLDER]
                found.extend(os.path.join(root, name) for name in names)
        else:
            found = [os.path.join(folder, name) for name in os.listdir(folder)
                     if os.path.isfile(os.path.join(folder, name))]
        if wanted is None:
            return found
        return [path for path in found if os.path.splitext(path)[1].lower() in wanted]

    def collect_batch_items(self):
        """The files this batch would run on, or the reason it has none."""
        folder_source = self.source_type_combo.currentText() == 'Folder'
        wanted = self._batch_extensions()
        if folder_source:
            folder = self.source_path_edit.text().strip()
            if not folder:
                return [], 'choose the folder the files come from'
            if not os.path.isdir(folder):
                return [], f'{folder} is not a folder'
            try:
                found = self._walk_batch_folder(folder, wanted)
            except OSError as error:
                return [], f'{folder} could not be read: {error}'
        else:
            try:
                rows = self._library_instance().get_models() or []
            except Exception as error:
                return [], f'the model library could not be read: {error}'
            found = [str(row.get('path') or '') for row in rows]
            if wanted is not None:
                found = [path for path in found
                         if os.path.splitext(path)[1].lower() in wanted]
        items = sorted({os.path.normpath(path) for path in found
                        if path and os.path.isfile(path)})
        if not items:
            where = 'that folder' if folder_source else 'the library'
            return [], (f'no file in {where} matches: it looks empty, or nothing in it '
                        'has an extension the filter names')
        return items, None

    def _batch_plan(self):
        """What would run, and everything that stops it - Preview and Start both come here.

        Every file is bound through the same call the batch will make, so the preview
        reads as the plan it is rather than as a description of a plan.
        """
        action = self._batch_action()
        output_dir = self.output_path_edit.text().strip()
        switches = {'overwrite': self.overwrite_cb.isChecked(),
                    'backup': self.backup_cb.isChecked()}
        if not action:
            return {'lines': ['choose an operation first'], 'ready': [],
                    'blocked': ['choose an operation first'], 'action': None,
                    'output_dir': output_dir, 'params': {}, 'switches': switches}
        binding = ActionRegistry.batch_binding(action)
        if not binding or len(binding) != 2:
            why = (f"{action} does not say how a batch hands it one file, so it "
                   "cannot be repeated over a list")
            return {'lines': [why], 'ready': [], 'blocked': [why], 'action': action,
                    'output_dir': output_dir, 'params': {}, 'switches': switches}
        params, complaint = self._parse_parameters(self.batch_params_edit.text())
        if complaint:
            return {'lines': [complaint], 'ready': [], 'blocked': [complaint],
                    'action': action, 'output_dir': output_dir, 'params': {},
                    'switches': switches}
        items, why = self.collect_batch_items()
        if why:
            return {'lines': [why], 'ready': [], 'blocked': [why], 'action': action,
                    'output_dir': output_dir, 'params': params, 'switches': switches}

        ready, blocked = [], []
        for item in items:
            kwargs, problem = ActionRegistry.bind_batch_params(
                action, item, output_dir, params)
            if problem:
                blocked.append(f'{os.path.basename(item)}: {problem}')
                continue
            destination = kwargs.get('destination')
            if destination and not switches['overwrite'] and os.path.exists(destination):
                blocked.append(f"{os.path.basename(item)}: {destination} is already there, "
                               'and overwrite is off')
                continue
            ready.append((item, kwargs))

        lines = [f'{len(ready)} file(s) would run as {action}']
        lines.append('output: ' + (output_dir or '(not chosen)') if binding[1]
                     else 'output: (this action writes no file)')
        lines.append('backup: ' + ('on' if switches['backup'] else 'off'))
        lines.append('parameters: ' + (json.dumps(params) if params else '(none)'))
        lines.append('overwrite: ' + ('on' if switches['overwrite'] else 'off')
                     if binding[1] == 'destination' else
                     'overwrite: (this action names no single output file)')
        for item, kwargs in ready[:200]:
            target = (kwargs.get('destination') or kwargs.get('output_dir')
                      or kwargs.get('command') or '(in place)')
            lines.append(f'  {os.path.basename(item)} -> {target}')
        if len(ready) > 200:
            lines.append(f'  ... and {len(ready) - 200} more')
        lines.extend(f'  cannot run - {one}' for one in blocked[:50])
        if len(blocked) > 50:
            lines.append(f'  ... and {len(blocked) - 50} more that cannot run')
        return {'lines': lines, 'ready': ready, 'blocked': blocked, 'action': action,
                'output_dir': output_dir, 'params': params, 'switches': switches}

    def preview_batch(self):
        """Print the plan and run none of it."""
        plan = self._batch_plan()
        self.batch_log.setPlainText('\n'.join(plan['lines']))
        if not plan['ready']:
            self.batch_status_label.setText('Preview: nothing can run yet.')
            QMessageBox.warning(self, 'Preview', plan['blocked'][0] if plan['blocked']
                                else 'there is nothing to preview')
            return
        note = f"Preview only - nothing was run. {len(plan['ready'])} file(s) ready"
        if plan['blocked']:
            note += f", {len(plan['blocked'])} cannot"
        self.batch_status_label.setText(note)

    def _batch_operation(self, action, output_dir, params, switches):
        """The one call every file gets, with the switches read once at the start."""
        def run_one(item):
            kwargs, why = ActionRegistry.bind_batch_params(action, item, output_dir, params)
            if why:
                return {'success': False, 'error': why}
            destination = kwargs.get('destination')
            if destination and not switches['overwrite'] and os.path.exists(destination):
                return {'success': False,
                        'error': f'{destination} is already there, and overwrite is off'}
            if switches['backup']:
                note = self._auto_backup(item)
                if not note.startswith('auto backup: copied to '):
                    return {'success': False, 'error': f'left alone - {note}'}
            return ActionRegistry.execute(action, **kwargs)
        return run_one

    def _set_batch_running(self, running):
        """A running batch cannot be retuned: the setup group closes until it reports."""
        self.controls_group.setEnabled(not running)
        self.start_batch_btn.setEnabled(not running)
        self.preview_batch_btn.setEnabled(not running)
        self.pause_batch_btn.setEnabled(running)
        self.stop_batch_btn.setEnabled(running)

    def start_batch_operation(self):
        """Run the plan on the engine's thread; every number on screen comes back from it."""
        plan = self._batch_plan()
        self.batch_log.setPlainText('\n'.join(plan['lines']))
        if not plan['ready']:
            self.batch_status_label.setText('Nothing ran.')
            QMessageBox.warning(self, 'Batch', plan['blocked'][0] if plan['blocked']
                                else 'there is nothing to run')
            return
        if plan['blocked']:
            self.batch_status_label.setText('Nothing was started.')
            QMessageBox.warning(
                self, 'Batch',
                f"{len(plan['blocked'])} of the {len(plan['ready']) + len(plan['blocked'])} "
                "files cannot run. Nothing was started - a batch that stops halfway "
                "leaves you guessing which files it got to. Fix those (overwrite is the "
                "usual one) or leave them out of the folder, then start again.")
            return
        items = [item for item, _ in plan['ready']]
        operation = self._batch_operation(plan['action'], plan['output_dir'],
                                          plan['params'], plan['switches'])
        if not self.automation_engine.run_batch(items, operation):
            self.batch_status_label.setText('A batch is already running.')
            QMessageBox.warning(self, 'Batch',
                                'a batch is already running - wait for it, or stop it first')
            return
        self._set_batch_running(True)
        self.batch_status_label.setText(
            f"Running {plan['action']} over {len(items)} file(s)...")

    def toggle_batch_pause(self):
        """Hold the batch at the next file, or let it go again."""
        processor = self.automation_engine.batch_processor
        hold = not processor.is_paused
        if not self.automation_engine.pause_batch(hold):
            self.batch_status_label.setText('Nothing is running to pause.')
            return
        self.pause_batch_btn.setText('Resume' if hold else 'Pause')
        self.batch_status_label.setText(
            'Paused - no new file starts until you resume.' if hold else 'Resumed.')

    def stop_batch_operation(self):
        """Ask for a stop; the file in hand finishes before the batch halts."""
        if not self.automation_engine.stop_batch():
            self.batch_status_label.setText('Nothing is running to stop.')
            return
        self.batch_status_label.setText('Stopping - the file in hand finishes first.')

    def on_batch_progress(self, current, total, current_file):
        """The file the batch is working on now."""
        if total <= 0:
            return
        self.batch_progress.setValue(int(current / total * 100))
        self.batch_status_label.setText(
            f"Processing {current}/{total}: {os.path.basename(str(current_file))}")

    @staticmethod
    def _batch_verdict(result):
        """What the action itself said it did."""
        if isinstance(result, dict):
            inner = result.get('result')
            if isinstance(inner, str):
                return inner
            if inner is None:
                return 'it gave no report'
            return json.dumps(inner, default=str)
        return str(result) if result is not None else 'it gave no report'

    def on_batch_completed_engine(self, summary):
        """One line per file, then the count the engine actually reached."""
        self._set_batch_running(False)
        self.pause_batch_btn.setText('Pause')
        lines = []
        for record in summary.get('results') or []:
            name = os.path.basename(str(record.get('item')))
            if record.get('success'):
                lines.append(f"  ok - {name}: {self._batch_verdict(record.get('result'))}")
            else:
                lines.append(f"  failed - {name}: {record.get('error')}")
        total = summary.get('total') or 0
        ran = summary.get('ran', len(summary.get('results') or []))
        succeeded = summary.get('succeeded', 0)
        failed = summary.get('failed', 0)
        self.batch_progress.setValue(int(round(ran / total * 100)) if total else 0)
        if summary.get('stopped'):
            head = (f'Stopped after {ran} of {total}: {succeeded} ok, {failed} failed, '
                    f'{total - ran} never ran')
        elif not total:
            head = 'Ran nothing - there were no files to work on'
        else:
            head = f'Finished {total} file(s): {succeeded} ok, {failed} failed'
        self.batch_status_label.setText(head)
        self.batch_log.appendPlainText('\n'.join(lines) + ('\n' if lines else '') + head)

    def browse_source_folder(self):
        """Put a picked folder where the batch reads its files from."""
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            self.source_path_edit.setText(folder)

    def browse_output_folder(self):
        """Put a picked folder where the batch writes its results."""
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
        return ActionRegistry.validate(action_id, params)

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