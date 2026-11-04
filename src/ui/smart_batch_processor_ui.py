"""
Smart Batch Processor UI - AI-Powered Batch Operations Interface

This UI provides an intelligent interface for batch processing 3D models with
AI-powered parameter suggestions, live preview, and advanced progress tracking.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                             QGroupBox, QComboBox, QCheckBox, QProgressBar,
                             QSplitter, QFrame, QTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSpinBox, QDoubleSpinBox,
                             QFileDialog, QMessageBox, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from src.core.worker_base import SafeWorker
from PyQt6.QtGui import QFont, QColor, QIcon
import logging
from pathlib import Path
from typing import List, Dict, Optional

from ..features.smart_batch_processor import SmartBatchProcessor, BatchOperation, BatchTask
from .icon_provider import get_icon

logger = logging.getLogger(__name__)


class BatchProcessingWorker(SafeWorker):
    """Background worker for batch processing."""
    progress = pyqtSignal(int, int, dict)  # current, total, task_info
    finished = pyqtSignal(dict)  # summary
    error = pyqtSignal(str)
    
    def __init__(self, tasks: List[BatchTask], processor: SmartBatchProcessor):
        super().__init__()
        self.tasks = tasks
        self.processor = processor
        self._is_running = True
    
    def safe_run(self):
        def progress_callback(current, total, task_info):
            if self._is_running:
                self.progress.emit(current, total, task_info)
        
        summary = self.processor.execute_batch(
            self.tasks,
            progress_callback=progress_callback,
            parallel=True
        )
        self.finished.emit(summary)
    
    def stop(self):
        self._is_running = False


class SmartBatchProcessorUI(QWidget):
    """
    Smart Batch Processor UI Component.
    
    Features:
    - Select multiple models for batch processing
    - Choose operation (LOD generation, format conversion, optimization, etc.)
    - AI-powered parameter suggestions
    - Live preview of changes
    - Progress tracking with ETA
    - Template system for common workflows
    - Undo/Redo support
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.processor = SmartBatchProcessor(max_workers=4)
        self.selected_models = []
        self.current_tasks = []
        self.preview_data = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Model selection and operation setup
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Preview and progress
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
    

    
    def _create_left_panel(self) -> QWidget:
        """Create left panel with model selection and operation setup."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        from .icon_provider import get_icon
        # Model Selection
        model_group = QGroupBox("Model Selection")
        model_layout = QVBoxLayout()
        
        # Add models buttons
        buttons_layout = QHBoxLayout()
        
        add_files_btn = QPushButton("Add Files")
        add_files_btn.setIcon(get_icon("add"))
        add_files_btn.clicked.connect(self.add_files)
        buttons_layout.addWidget(add_files_btn)
        
        add_folder_btn = QPushButton("Add Folder")
        add_folder_btn.setIcon(get_icon("folder"))
        add_folder_btn.clicked.connect(self.add_folder)
        buttons_layout.addWidget(add_folder_btn)
        
        clear_btn = QPushButton("Clear")
        clear_btn.setIcon(get_icon("delete"))
        clear_btn.clicked.connect(self.clear_models)
        buttons_layout.addWidget(clear_btn)
        
        model_layout.addLayout(buttons_layout)
        
        # Model list
        self.model_list = QListWidget()
        self.model_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.model_list.setStyleSheet("""
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #ecf0f1;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        model_layout.addWidget(self.model_list)
        
        # Model count
        self.model_count_label = QLabel("0 models selected")
        self.model_count_label.setStyleSheet("font-weight: 600; color: #8c93a8;")
        model_layout.addWidget(self.model_count_label)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # Operation Selection
        operation_group = QGroupBox("Batch Operation")
        operation_layout = QVBoxLayout()
        
        op_label = QLabel("Select operation to perform:")
        operation_layout.addWidget(op_label)
        
        # Templates
        template_layout = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.addItem("Select Template...")
        self.template_combo.currentTextChanged.connect(self._load_template)
        
        self.save_template_btn = QPushButton()
        self.save_template_btn.setIcon(get_icon("backup"))
        self.save_template_btn.setToolTip("Save current settings as template")
        self.save_template_btn.clicked.connect(self._save_template)
        self.save_template_btn.setMaximumWidth(32)
        
        self.delete_template_btn = QPushButton()
        self.delete_template_btn.setIcon(get_icon("delete"))
        self.delete_template_btn.setToolTip("Delete selected template")
        self.delete_template_btn.clicked.connect(self._delete_template)
        self.delete_template_btn.setMaximumWidth(32)
        
        template_layout.addWidget(self.template_combo)
        template_layout.addWidget(self.save_template_btn)
        template_layout.addWidget(self.delete_template_btn)
        
        operation_layout.addLayout(template_layout)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        operation_layout.addWidget(line)
        
        self.operation_combo = QComboBox()
        self.operation_combo.addItem("Generate LODs", BatchOperation.GENERATE_LODS)
        self.operation_combo.addItem("Convert Format", BatchOperation.CONVERT_FORMAT)
        self.operation_combo.addItem("Optimize Mesh", BatchOperation.OPTIMIZE_MESH)
        self.operation_combo.addItem("Generate UVs", BatchOperation.GENERATE_UVS)
        self.operation_combo.addItem("Repair Mesh", BatchOperation.REPAIR_MESH)
        self.operation_combo.addItem("Scale Model", BatchOperation.SCALE_MODEL)
        self.operation_combo.addItem("Center Pivot", BatchOperation.CENTER_PIVOT)
        self.operation_combo.addItem("Merge Vertices", BatchOperation.MERGE_VERTICES)
        self.operation_combo.addItem("Reduce Polygons", BatchOperation.REDUCE_POLYGONS)
        self.operation_combo.addItem("Export Thumbnails", BatchOperation.EXPORT_THUMBNAILS)
        self.operation_combo.currentIndexChanged.connect(self.on_operation_changed)
        operation_layout.addWidget(self.operation_combo)
        
        operation_group.setLayout(operation_layout)
        layout.addWidget(operation_group)
        
        # AI Parameter Suggestions
        ai_group = QGroupBox("AI Parameter Suggestions")
        ai_layout = QVBoxLayout()
        
        ai_info = QLabel("Analyze models and get AI-powered parameter recommendations")
        ai_info.setStyleSheet("color: #8c93a8;")
        ai_info.setWordWrap(True)
        ai_layout.addWidget(ai_info)
        
        self.analyze_btn = QPushButton("Analyze & Suggest Parameters")
        self.analyze_btn.setIcon(get_icon("sparkles"))
        self.analyze_btn.clicked.connect(self.analyze_and_suggest)
        self.analyze_btn.setEnabled(False)
        ai_layout.addWidget(self.analyze_btn)
        
        # Suggestions display
        self.suggestions_text = QTextEdit()
        self.suggestions_text.setReadOnly(True)
        self.suggestions_text.setMaximumHeight(120)
        self.suggestions_text.setPlaceholderText("AI suggestions will appear here...")
        ai_layout.addWidget(self.suggestions_text)
        
        ai_group.setLayout(ai_layout)
        layout.addWidget(ai_group)
        
        # Parameters Section (dynamic based on operation)
        params_group = QGroupBox("Operation Parameters")
        params_layout = QVBoxLayout()
        
        # Scrollable parameters area
        self.params_scroll = QScrollArea()
        self.params_scroll.setWidgetResizable(True)
        self.params_widget = QWidget()
        self.params_layout = QVBoxLayout(self.params_widget)
        self.params_scroll.setWidget(self.params_widget)
        
        params_layout.addWidget(self.params_scroll)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # Initialize parameters for default operation
        self.update_parameters_ui()
        
        # Load templates
        self._load_templates_to_ui()
        
        scroll_area.setWidget(panel)
        return scroll_area
    
    def _create_right_panel(self) -> QWidget:
        """Create right panel with preview and progress."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Preview Section
        preview_group = QGroupBox("Live Preview")
        preview_layout = QVBoxLayout()
        
        preview_info = QLabel("Preview changes before applying to all models")
        preview_info.setStyleSheet("color: #8c93a8;")
        preview_layout.addWidget(preview_info)
        
        self.preview_btn = QPushButton("Generate Preview")
        self.preview_btn.setIcon(get_icon("overlays"))
        self.preview_btn.clicked.connect(self.generate_preview)
        self.preview_btn.setEnabled(False)
        preview_layout.addWidget(self.preview_btn)
        
        # Preview results
        self.preview_results = QTextEdit()
        self.preview_results.setReadOnly(True)
        self.preview_results.setPlaceholderText("Preview results will appear here...")
        preview_layout.addWidget(self.preview_results)
        
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)
        
        # Batch Execution
        batch_group = QGroupBox("Batch Execution")
        batch_layout = QVBoxLayout()
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Batch")
        self.start_btn.setIcon(get_icon("play"))
        self.start_btn.setProperty("primary", "true")
        self.start_btn.clicked.connect(self.start_batch)
        self.start_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(get_icon("pause"))
        self.pause_btn.setEnabled(False)
        action_layout.addWidget(self.pause_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(get_icon("stop"))
        self.stop_btn.setEnabled(False)
        action_layout.addWidget(self.stop_btn)
        
        batch_layout.addLayout(action_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        batch_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Ready to start")
        self.status_label.setStyleSheet("color: #8c93a8; font-style: italic;")
        batch_layout.addWidget(self.status_label)
        
        # ETA label
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: #45aaf2; font-weight: bold;")
        batch_layout.addWidget(self.eta_label)
        
        batch_group.setLayout(batch_layout)
        layout.addWidget(batch_group)
        
        # Task Progress Table
        tasks_group = QGroupBox("Task Progress")
        tasks_layout = QVBoxLayout()
        
        self.tasks_table = QTableWidget()
        self.tasks_table.setColumnCount(4)
        self.tasks_table.setHorizontalHeaderLabels(["Model", "Operation", "Status", "Result"])
        self.tasks_table.horizontalHeader().setStretchLastSection(True)
        self.tasks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tasks_layout.addWidget(self.tasks_table)
        
        tasks_group.setLayout(tasks_layout)
        layout.addWidget(tasks_group)
        
        # Summary
        summary_group = QGroupBox("Batch Summary")
        summary_layout = QVBoxLayout()
        
        self.summary_label = QLabel("No batch executed yet")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #8c93a8;")
        summary_layout.addWidget(self.summary_label)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        return panel
    
    def add_files(self):
        """Add model files to batch."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select 3D Model Files",
            "",
            "3D Models (*.obj *.fbx *.glb *.gltf *.stl *.ply *.dae);;All Files (*.*)"
        )
        
        for file in files:
            if file not in self.selected_models:
                self.selected_models.append(file)
                self.model_list.addItem(Path(file).name)
        
        self.update_model_count()
    
    def add_folder(self):
        """Add all models from a folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        
        if folder:
            extensions = ['.obj', '.fbx', '.glb', '.gltf', '.stl', '.ply', '.dae']
            for ext in extensions:
                for file in Path(folder).rglob(f'*{ext}'):
                    file_str = str(file)
                    if file_str not in self.selected_models:
                        self.selected_models.append(file_str)
                        self.model_list.addItem(file.name)
        
        self.update_model_count()
    
    def clear_models(self):
        """Clear all selected models."""
        self.selected_models.clear()
        self.model_list.clear()
        self.update_model_count()
    
    def update_model_count(self):
        """Update model count display."""
        count = len(self.selected_models)
        self.model_count_label.setText(f"{count} model{'s' if count != 1 else ''} selected")
        
        # Enable/disable buttons
        has_models = count > 0
        self.analyze_btn.setEnabled(has_models)
        self.preview_btn.setEnabled(has_models)
        self.start_btn.setEnabled(has_models)
    
    def on_operation_changed(self):
        """Handle operation change."""
        self.update_parameters_ui()
        self.suggestions_text.clear()
    
    def update_parameters_ui(self):
        """Update parameters UI based on selected operation."""
        # Clear existing parameters
        while self.params_layout.count():
            child = self.params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        operation = self.operation_combo.currentData()
        
        # Create parameter widgets based on operation
        if operation == BatchOperation.GENERATE_LODS:
            self._add_lod_parameters()
        elif operation == BatchOperation.CONVERT_FORMAT:
            self._add_convert_parameters()
        elif operation == BatchOperation.OPTIMIZE_MESH:
            self._add_optimize_parameters()
        elif operation == BatchOperation.REDUCE_POLYGONS:
            self._add_reduce_parameters()
        elif operation == BatchOperation.SCALE_MODEL:
            self._add_scale_parameters()
        elif operation == BatchOperation.GENERATE_UVS:
            self._add_uv_parameters()
        else:
            info_label = QLabel("No additional parameters required")
            info_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
            self.params_layout.addWidget(info_label)
        
        self.params_layout.addStretch()
    
    def _add_lod_parameters(self):
        """Add LOD generation parameters."""
        lod_levels_label = QLabel("LOD Levels:")
        self.lod_levels_spin = QSpinBox()
        self.lod_levels_spin.setRange(1, 5)
        self.lod_levels_spin.setValue(3)
        self.params_layout.addWidget(lod_levels_label)
        self.params_layout.addWidget(self.lod_levels_spin)
        
        preserve_label = QLabel("Preserve Topology:")
        self.preserve_topology_check = QCheckBox()
        self.preserve_topology_check.setChecked(True)
        self.params_layout.addWidget(preserve_label)
        self.params_layout.addWidget(self.preserve_topology_check)
    
    def _add_convert_parameters(self):
        """Add format conversion parameters."""
        format_label = QLabel("Output Format:")
        self.output_format_combo = QComboBox()
        self.output_format_combo.addItems(['glb', 'gltf', 'obj', 'fbx', 'stl', 'ply'])
        self.params_layout.addWidget(format_label)
        self.params_layout.addWidget(self.output_format_combo)
        
        self.export_materials_check = QCheckBox("Export Materials")
        self.export_materials_check.setChecked(True)
        self.params_layout.addWidget(self.export_materials_check)
        
        self.export_normals_check = QCheckBox("Export Normals")
        self.export_normals_check.setChecked(True)
        self.params_layout.addWidget(self.export_normals_check)
    
    def _add_optimize_parameters(self):
        """Add mesh optimization parameters."""
        self.merge_vertices_check = QCheckBox("Merge Vertices")
        self.merge_vertices_check.setChecked(True)
        self.params_layout.addWidget(self.merge_vertices_check)
        
        self.remove_degenerate_check = QCheckBox("Remove Degenerate Faces")
        self.remove_degenerate_check.setChecked(True)
        self.params_layout.addWidget(self.remove_degenerate_check)
        
        self.fix_normals_check = QCheckBox("Fix Normals")
        self.fix_normals_check.setChecked(True)
        self.params_layout.addWidget(self.fix_normals_check)
    
    def _add_reduce_parameters(self):
        """Add polygon reduction parameters."""
        target_label = QLabel("Target Polygon Count:")
        self.target_polygons_spin = QSpinBox()
        self.target_polygons_spin.setRange(100, 1000000)
        self.target_polygons_spin.setValue(10000)
        self.target_polygons_spin.setSingleStep(1000)
        self.params_layout.addWidget(target_label)
        self.params_layout.addWidget(self.target_polygons_spin)
        
        ratio_label = QLabel("Or Reduction Ratio (0-1):")
        self.reduction_ratio_spin = QDoubleSpinBox()
        self.reduction_ratio_spin.setRange(0.01, 0.99)
        self.reduction_ratio_spin.setValue(0.5)
        self.reduction_ratio_spin.setSingleStep(0.1)
        self.params_layout.addWidget(ratio_label)
        self.params_layout.addWidget(self.reduction_ratio_spin)
    
    def _add_scale_parameters(self):
        """Add scale parameters."""
        scale_label = QLabel("Target Size (units):")
        self.target_size_spin = QDoubleSpinBox()
        self.target_size_spin.setRange(0.01, 1000.0)
        self.target_size_spin.setValue(1.0)
        self.target_size_spin.setSingleStep(0.1)
        self.params_layout.addWidget(scale_label)
        self.params_layout.addWidget(self.target_size_spin)
        
        self.uniform_scale_check = QCheckBox("Uniform Scale")
        self.uniform_scale_check.setChecked(True)
        self.params_layout.addWidget(self.uniform_scale_check)
    
    def _add_uv_parameters(self):
        """Add UV generation parameters."""
        method_label = QLabel("UV Method:")
        self.uv_method_combo = QComboBox()
        self.uv_method_combo.addItems(['smart_uv', 'cube_projection', 'cylinder_projection', 'sphere_projection'])
        self.params_layout.addWidget(method_label)
        self.params_layout.addWidget(self.uv_method_combo)
        
        self.skip_existing_check = QCheckBox("Skip Models with Existing UVs")
        self.skip_existing_check.setChecked(True)
        self.params_layout.addWidget(self.skip_existing_check)
    
    def get_current_parameters(self) -> Dict:
        """Get current parameter values."""
        operation = self.operation_combo.currentData()
        params = {}
        
        if operation == BatchOperation.GENERATE_LODS:
            params = {
                'lod_levels': self.lod_levels_spin.value(),
                'preserve_topology': self.preserve_topology_check.isChecked()
            }
        elif operation == BatchOperation.CONVERT_FORMAT:
            params = {
                'output_format': self.output_format_combo.currentText(),
                'export_materials': self.export_materials_check.isChecked(),
                'export_normals': self.export_normals_check.isChecked()
            }
        elif operation == BatchOperation.OPTIMIZE_MESH:
            params = {
                'merge_vertices': self.merge_vertices_check.isChecked(),
                'remove_degenerate': self.remove_degenerate_check.isChecked(),
                'fix_normals': self.fix_normals_check.isChecked()
            }
        elif operation == BatchOperation.REDUCE_POLYGONS:
            params = {
                'target_polygon_count': self.target_polygons_spin.value(),
                'reduction_ratio': self.reduction_ratio_spin.value()
            }
        elif operation == BatchOperation.SCALE_MODEL:
            params = {
                'target_size': self.target_size_spin.value(),
                'uniform_scale': self.uniform_scale_check.isChecked()
            }
        elif operation == BatchOperation.GENERATE_UVS:
            params = {
                'method': self.uv_method_combo.currentText(),
                'skip_existing': self.skip_existing_check.isChecked()
            }
        
        return params
    
    def analyze_and_suggest(self):
        """Analyze models and get AI parameter suggestions."""
        if not self.selected_models:
            return
        
        operation = self.operation_combo.currentData()
        self.analyze_btn.setEnabled(False)
        self.suggestions_text.setPlainText("Analyzing models...")
        
        try:
            suggestions = self.processor.analyze_and_suggest_parameters(
                self.selected_models,
                operation
            )
            
            # Display suggestions
            if suggestions:
                confidence = suggestions.get('confidence', 0) * 100
                reasoning = suggestions.get('reasoning', 'No reasoning provided')
                
                text = f"<h3>AI Suggestions (Confidence: {confidence:.0f}%)</h3>"
                text += f"<p><b>Reasoning:</b> {reasoning}</p>"
                text += "<p><b>Suggested Parameters:</b></p><ul>"
                
                for key, value in suggestions.items():
                    if key not in ['confidence', 'reasoning']:
                        text += f"<li><b>{key}:</b> {value}</li>"
                
                text += "</ul>"
                text += "<p><i>Tip: You can adjust these or use them as-is</i></p>"
                
                self.suggestions_text.setHtml(text)
                logger.info(f"AI suggestions generated with {confidence:.0f}% confidence")
            else:
                self.suggestions_text.setPlainText("No suggestions available for this operation")
        
        except Exception as e:
            self.suggestions_text.setHtml(f"<p style='color: red;'>Error: {e}</p>")
            logger.error(f"Failed to generate suggestions: {e}")
        
        finally:
            self.analyze_btn.setEnabled(True)
    
    def generate_preview(self):
        """Generate preview for first model."""
        if not self.selected_models:
            return
        
        operation = self.operation_combo.currentData()
        parameters = self.get_current_parameters()
        
        self.preview_btn.setEnabled(False)
        self.preview_results.setPlainText("Generating preview...")
        
        try:
            # Preview first model
            preview = self.processor.preview_operation(
                self.selected_models[0],
                operation,
                parameters
            )
            
            if preview.get('preview_successful'):
                before = preview['before']
                after = preview['after']
                changes = preview['changes']
                
                text = f"<h3>Preview Results for: {Path(self.selected_models[0]).name}</h3>"
                
                text += "<table border='1' cellpadding='5' style='border-collapse: collapse;'>"
                text += "<tr><th>Metric</th><th>Before</th><th>After</th><th>Change</th></tr>"
                
                text += f"<tr><td>Polygons</td><td>{before['polygon_count']:,}</td><td>{after['polygon_count']:,}</td>"
                text += f"<td style='color: {'red' if changes['polygons_delta'] < 0 else 'green'}'>{changes['polygons_delta']:+,} ({changes['polygons_percent']:+.1f}%)</td></tr>"
                
                text += f"<tr><td>Vertices</td><td>{before['vertex_count']:,}</td><td>{after['vertex_count']:,}</td>"
                text += f"<td style='color: {'red' if changes['vertices_delta'] < 0 else 'green'}'>{changes['vertices_delta']:+,}</td></tr>"
                
                text += f"<tr><td>Watertight</td><td>{'Yes' if before['is_watertight'] else 'No'}</td><td>{'Yes' if after['is_watertight'] else 'No'}</td><td>-</td></tr>"
                
                text += f"<tr><td>Has UVs</td><td>{'Yes' if before['has_uvs'] else 'No'}</td><td>{'Yes' if after['has_uvs'] else 'No'}</td><td>-</td></tr>"
                
                text += "</table>"
                
                text += "<p><i>This preview shows the effect on the first model. Similar results expected for other models.</i></p>"
                
                self.preview_results.setHtml(text)
                logger.info("Preview generated successfully")
            else:
                error = preview.get('error', 'Unknown error')
                self.preview_results.setHtml(f"<p style='color: red;'>Preview failed: {error}</p>")
        
        except Exception as e:
            self.preview_results.setHtml(f"<p style='color: red;'>Error: {e}</p>")
            logger.error(f"Failed to generate preview: {e}")
        
        finally:
            self.preview_btn.setEnabled(True)
    
    def start_batch(self):
        """Start batch processing."""
        if not self.selected_models:
            QMessageBox.warning(self, "No Models", "Please select models to process")
            return
        
        operation = self.operation_combo.currentData()
        parameters = self.get_current_parameters()
        
        # Create tasks
        self.current_tasks = []
        for model_path in self.selected_models:
            # Generate output path
            output_dir = Path(model_path).parent / "batch_output"
            output_dir.mkdir(exist_ok=True)
            output_path = str(output_dir / Path(model_path).name)
            
            task = BatchTask(
                model_path=model_path,
                operation=operation,
                parameters=parameters,
                output_path=output_path
            )
            self.current_tasks.append(task)
        
        # Update UI
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.current_tasks))
        
        # Setup tasks table
        self.tasks_table.setRowCount(len(self.current_tasks))
        for i, task in enumerate(self.current_tasks):
            self.tasks_table.setItem(i, 0, QTableWidgetItem(Path(task.model_path).name))
            self.tasks_table.setItem(i, 1, QTableWidgetItem(operation.value))
            self.tasks_table.setItem(i, 2, QTableWidgetItem("Pending"))
            self.tasks_table.setItem(i, 3, QTableWidgetItem("-"))
        
        # Start worker
        self.batch_worker = BatchProcessingWorker(self.current_tasks, self.processor)
        self.batch_worker.progress.connect(self.on_batch_progress)
        self.batch_worker.finished.connect(self.on_batch_finished)
        self.batch_worker.error.connect(self.on_batch_error)
        self.batch_worker.start()
        
        self.status_label.setText("Processing batch...")
        logger.info(f"Started batch processing of {len(self.current_tasks)} models")
    
    def on_batch_progress(self, current: int, total: int, task_info: dict):
        """Handle batch progress update."""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processing {current}/{total}: {task_info.get('model', '')}")
        
        # Update task table
        # (Implementation depends on task_info structure)
    
    def on_batch_finished(self, summary: dict):
        """Handle batch completion."""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        
        completed = summary.get('completed', 0)
        failed = summary.get('failed', 0)
        duration = summary.get('duration', 0)
        
        summary_text = f"<h3>Batch Complete!</h3>"
        summary_text += f"<p><b>Completed:</b> {completed}/{completed + failed}</p>"
        summary_text += f"<p><b>Failed:</b> {failed}</p>"
        summary_text += f"<p><b>Duration:</b> {duration:.1f} seconds</p>"
        
        self.summary_label.setText(summary_text)
        self.status_label.setText("Batch completed")
        
        logger.info(f"Batch completed: {completed} succeeded, {failed} failed")
        
        QMessageBox.information(self, "Batch Complete", 
                               f"Processed {completed + failed} models\n"
                               f"Success: {completed}\nFailed: {failed}")
    
    def on_batch_error(self, error_msg: str):
        """Handle batch error."""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"Error: {error_msg}")
        logger.error(f"Batch error: {error_msg}")
        QMessageBox.critical(self, "Batch Error", f"An error occurred:\n{error_msg}")

    # =========================================================================
    # TEMPLATE MANAGEMENT
    # =========================================================================
    
    def _get_templates_file(self) -> Path:
        """Get path to templates file."""
        import json
        config_dir = Path.home() / ".renderfox"
        config_dir.mkdir(exist_ok=True)
        return config_dir / "batch_templates.json"

    def _load_templates_from_file(self) -> Dict:
        """Load templates from JSON file."""
        import json
        file_path = self._get_templates_file()
        if not file_path.exists():
            return {}
            
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load templates: {e}")
            return {}

    def _save_templates_to_file(self, templates: Dict):
        """Save templates to JSON file."""
        import json
        file_path = self._get_templates_file()
        try:
            with open(file_path, 'w') as f:
                json.dump(templates, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save templates: {e}")
            QMessageBox.warning(self, "Error", f"Failed to save templates: {e}")

    def _load_templates_to_ui(self):
        """Load templates into combo box."""
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("Select Template...")
        
        templates = self._load_templates_from_file()
        for name in sorted(templates.keys()):
            self.template_combo.addItem(name)
            
        self.template_combo.blockSignals(False)

    def _save_template(self):
        """Save current settings as a template."""
        from PyQt6.QtWidgets import QInputDialog
        
        name, ok = QInputDialog.getText(self, "Save Template", "Template Name:")
        if ok and name:
            templates = self._load_templates_from_file()
            
            # Get current settings
            settings = {
                'operation': self.operation_combo.currentData().value,
                'parameters': self.get_current_parameters()
            }
            
            templates[name] = settings
            self._save_templates_to_file(templates)
            self._load_templates_to_ui()
            
            # Select the new template
            index = self.template_combo.findText(name)
            if index >= 0:
                self.template_combo.setCurrentIndex(index)
                
            QMessageBox.information(self, "Success", f"Template '{name}' saved")

    def _load_template(self, name: str):
        """Load settings from selected template."""
        if name == "Select Template...":
            return
            
        templates = self._load_templates_from_file()
        if name in templates:
            settings = templates[name]
            
            # Set operation
            op_value = settings.get('operation')
            index = -1
            for i in range(self.operation_combo.count()):
                if self.operation_combo.itemData(i).value == op_value:
                    index = i
                    break
            
            if index >= 0:
                self.operation_combo.setCurrentIndex(index)
                # Force UI update for parameters
                self.update_parameters_ui()
                
                # Set parameters
                params = settings.get('parameters', {})
                self._apply_parameters(params)

    def _delete_template(self):
        """Delete selected template."""
        name = self.template_combo.currentText()
        if name == "Select Template...":
            return
            
        reply = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete template '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            templates = self._load_templates_from_file()
            if name in templates:
                del templates[name]
                self._save_templates_to_file(templates)
                self._load_templates_to_ui()

    def _apply_parameters(self, params: Dict):
        """Apply parameters to UI widgets."""
        # Helper to safely set widget values
        try:
            # LODs
            if 'lod_levels' in params: self.lod_levels_spin.setValue(params['lod_levels'])
            if 'preserve_topology' in params: self.preserve_topology_check.setChecked(params['preserve_topology'])
            
            # Convert
            if 'output_format' in params: self.output_format_combo.setCurrentText(params['output_format'])
            if 'export_materials' in params: self.export_materials_check.setChecked(params['export_materials'])
            if 'export_normals' in params: self.export_normals_check.setChecked(params['export_normals'])
            
            # Optimize
            if 'merge_vertices' in params: self.merge_vertices_check.setChecked(params['merge_vertices'])
            if 'remove_degenerate' in params: self.remove_degenerate_check.setChecked(params['remove_degenerate'])
            if 'fix_normals' in params: self.fix_normals_check.setChecked(params['fix_normals'])
            
            # Reduce
            if 'target_polygon_count' in params: self.target_polygons_spin.setValue(params['target_polygon_count'])
            if 'reduction_ratio' in params: self.reduction_ratio_spin.setValue(params['reduction_ratio'])
            
            # Scale
            if 'target_size' in params: self.target_size_spin.setValue(params['target_size'])
            if 'uniform_scale' in params: self.uniform_scale_check.setChecked(params['uniform_scale'])
            
            # UVs
            if 'method' in params: self.uv_method_combo.setCurrentText(params['method'])
            if 'skip_existing' in params: self.skip_existing_check.setChecked(params['skip_existing'])
            
        except Exception as e:
            logger.error(f"Error applying parameters: {e}")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    window = SmartBatchProcessorUI()
    window.setWindowTitle("Smart Batch Processor")
    window.resize(1400, 900)
    window.show()
    
    sys.exit(app.exec())
