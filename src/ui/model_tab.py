import sys
"""
Model tab for RenderFox - using OpenGL viewer for better performance and compatibility.
"""

import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                             QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem,
                             QGroupBox, QFormLayout, QLabel, QLineEdit, QComboBox,
                             QSpinBox, QDoubleSpinBox, QCheckBox, QTextEdit,
                             QProgressBar, QMessageBox, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView, QListWidget, QListWidgetItem,
                             QDialog, QDialogButtonBox, QScrollArea, QProgressDialog,
                             QColorDialog, QInputDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from src.core.worker_base import SafeWorker
from PyQt6.QtGui import QPixmap, QIcon, QColor, QFont

from .model_viewer import ModelViewerWidget
import trimesh
import json
from datetime import datetime
import numpy as np
from .quality_analyzer_ui import QualityAnalyzerUI
from .version_control_ui import VersionControlUI
from ..features.quality_analyzer import QualityAnalyzer
from ..features.version_control import AssetVersionControl
from .icon_provider import get_icon

# New imports for conversion wiring
from src.processing.format_converter import FormatConverter, SupportedFormat
from src.ui.conversion_results_dialog import show_conversion_results
from src.ui.painting_tab import PaintingTab
from .icon_provider import get_icon

# Helper to ensure we have a Trimesh instance from a trimesh.Scene or Trimesh
def _as_trimesh(obj):
    if isinstance(obj, trimesh.Trimesh):
        return obj
    if isinstance(obj, trimesh.Scene):
        try:
            dumped = obj.dump()
            if isinstance(dumped, (list, tuple)):
                return trimesh.util.concatenate(dumped) if dumped else None
            if isinstance(dumped, dict):
                return trimesh.util.concatenate(list(dumped.values())) if dumped else None
            if isinstance(dumped, trimesh.Trimesh):
                return dumped
        except Exception:
            pass
        try:
            geoms = list(obj.geometry.values()) if hasattr(obj, 'geometry') else []
            return trimesh.util.concatenate(geoms) if geoms else None
        except Exception:
            return None
    return None

class ModelAnalysisWorker(SafeWorker):
    """Worker thread for analyzing model files."""
    
    analysis_complete = pyqtSignal(dict)
    progress_updated = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths
    
    def safe_run(self):
        """Analyze the model files."""
        results = []
        total_files = len(self.file_paths)
        
        for i, file_path in enumerate(self.file_paths):
            self.progress_updated.emit(int((i / total_files) * 100))
            mesh_obj = trimesh.load(file_path)
            mesh = _as_trimesh(mesh_obj)
            if mesh is None:
                continue
            analysis = {
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'file_size_mb': os.path.getsize(file_path) / (1024 * 1024),
                'vertices': len(mesh.vertices),
                'faces': len(mesh.faces),
                'edges': len(mesh.edges),
                'surface_area': float(mesh.area),
                'volume': float(mesh.volume) if mesh.is_volume else 0.0,
                'is_watertight': mesh.is_watertight,
                'is_winding_consistent': mesh.is_winding_consistent,
                'bounds': mesh.bounds.tolist(),
                'center': mesh.center_mass.tolist(),
                'bounding_box_volume': mesh.bounding_box.volume,
                'convex_hull_volume': mesh.convex_hull.volume if hasattr(mesh, 'convex_hull') else 0.0,
                'has_uvs': hasattr(mesh.visual, 'uv') and mesh.visual.uv is not None,
                'has_vertex_colors': hasattr(mesh.visual, 'vertex_colors') and mesh.visual.vertex_colors is not None,
                'material_count': len(mesh.visual.material.materials) if hasattr(mesh.visual, 'material') and hasattr(mesh.visual.material, 'materials') else (1 if hasattr(mesh.visual, 'material') else 0),
                'texture_data': {
                    'Albedo': 1 if hasattr(mesh.visual.material, 'baseColorTexture') and mesh.visual.material.baseColorTexture else (1 if hasattr(mesh.visual.material, 'image') else 0),
                    'Normal': 1 if hasattr(mesh.visual.material, 'normalTexture') and mesh.visual.material.normalTexture else 0,
                    'Specular/Metallic': 1 if hasattr(mesh.visual.material, 'metallicRoughnessTexture') and mesh.visual.material.metallicRoughnessTexture else 0,
                    'Occlusion': 1 if hasattr(mesh.visual.material, 'occlusionTexture') and mesh.visual.material.occlusionTexture else 0,
                    'Emissive': 1 if hasattr(mesh.visual.material, 'emissiveTexture') and mesh.visual.material.emissiveTexture else 0
                }
            }
            results.append(analysis)

        
        self.progress_updated.emit(100)
        self.analysis_complete.emit({'results': results, 'total_analyzed': len(results)})

class ConverterThread(QThread):
    """Background thread to run batch conversions using FormatConverter."""
    results_ready = pyqtSignal(dict)
    progress_update = pyqtSignal(int, str)

    def __init__(self, input_files, output_dir, target_format: SupportedFormat, options=None):
        super().__init__()
        self.input_files = input_files
        self.output_dir = output_dir
        self.target_format = target_format
        self.options = options or {}

    def run(self):
        try:
            converter = FormatConverter()
            # Forward progress
            converter.conversion_progress.connect(
                lambda path, pct: self.progress_update.emit(pct, f"Converting {os.path.basename(path) if path else ''}...")
            )
            results = converter.batch_convert(self.input_files, self.output_dir, self.target_format, self.options)
            self.results_ready.emit(results)
        except Exception as e:
            self.results_ready.emit({
                'total_files': len(self.input_files),
                'successful': [],
                'failed': [{'input': f, 'output': None, 'error': str(e)} for f in self.input_files],
                'errors': [str(e)]
            })

class ModelFormatConverter(QDialog):
    """Dialog for converting model formats."""
    
    def __init__(self, parent=None, input_files=None):
        super().__init__(parent)
        self.input_files = input_files or []
        self.setWindowTitle("Model Format Converter")
        self.setModal(True)
        self.resize(520, 440)
        self._thread = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize the converter dialog UI."""
        layout = QVBoxLayout(self)
        
        # Input files section
        input_group = QGroupBox("Input Files")
        input_layout = QVBoxLayout()
        
        self.input_list = QListWidget()
        for file_path in self.input_files:
            self.input_list.addItem(os.path.basename(file_path))
        input_layout.addWidget(self.input_list)
        
        add_files_btn = QPushButton("Add Files...")
        add_files_btn.clicked.connect(self.add_input_files)
        input_layout.addWidget(add_files_btn)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # Conversion settings
        settings_group = QGroupBox("Conversion Settings")
        settings_layout = QFormLayout()
        
        self.output_format = QComboBox()
        # Populate from SupportedFormat to ensure compatibility with converter
        for fmt in [SupportedFormat.OBJ, SupportedFormat.STL, SupportedFormat.PLY,
                    SupportedFormat.GLB, SupportedFormat.GLTF, SupportedFormat.DAE, SupportedFormat.FBX]:
            self.output_format.addItem(fmt.value.upper(), fmt)
        settings_layout.addRow("Output Format:", self.output_format)
        
        self.output_dir = QLineEdit()
        output_btn = QPushButton("Browse...")
        output_btn.clicked.connect(self.browse_output_dir)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_dir)
        output_layout.addWidget(output_btn)
        settings_layout.addRow("Output Directory:", output_layout)
        
        # Conversion options (mapped to converter options where applicable)
        self.merge_objects = QCheckBox("Merge all objects into single file")
        settings_layout.addRow("", self.merge_objects)
        
        self.scale_factor = QDoubleSpinBox()
        self.scale_factor.setRange(0.001, 1000.0)
        self.scale_factor.setValue(1.0)
        self.scale_factor.setDecimals(3)
        settings_layout.addRow("Scale Factor:", self.scale_factor)
        
        self.apply_transform = QCheckBox("Apply transforms")
        self.apply_transform.setChecked(True)
        settings_layout.addRow("", self.apply_transform)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.start_conversion)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def add_input_files(self):
        """Add input files for conversion."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Model Files",
            "", "3D Models (*.obj *.stl *.ply *.glb *.gltf *.fbx *.dae *.x3d);;All Files (*)"
        )
        
        for file_path in files:
            if file_path not in self.input_files:
                self.input_files.append(file_path)
                self.input_list.addItem(os.path.basename(file_path))
    
    def browse_output_dir(self):
        """Browse for output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir.setText(dir_path)
    
    def start_conversion(self):
        """Start the format conversion process."""
        if not self.input_files:
            QMessageBox.warning(self, "No Files", "Please select input files for conversion.")
            return
        
        if not self.output_dir.text():
            QMessageBox.warning(self, "No Output Directory", "Please select an output directory.")
            return
        
        # Prepare options understood by FormatConverter
        options = {
            'scale': self.scale_factor.value()
            # 'center', 'normalize', 'repair' could be added later
        }
        
        target_format: SupportedFormat = self.output_format.currentData()
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        # Disable UI during conversion
        self.setEnabled(False)
        
        # Start background conversion
        self._thread = ConverterThread(self.input_files, self.output_dir.text(), target_format, options)
        self._thread.progress_update.connect(lambda pct, msg: self.progress_bar.setValue(pct))
        self._thread.results_ready.connect(self.on_conversion_finished)
        self._thread.finished.connect(lambda: self.setEnabled(True))
        self._thread.start()
    
    def on_conversion_finished(self, results: dict):
        """Handle conversion completion and show results dialog."""
        self.progress_bar.setVisible(False)
        show_conversion_results(results, self)
        # Keep dialog open for review; user can close manually

class ModelTab(QWidget):
    """Comprehensive model management tab using OpenGL viewer."""
    
    def __init__(self, parent=None, library_path='output'):
        super().__init__(parent)
        self.current_model_path = None
        self.model_library = []
        self.library_path = library_path
        self.quality_analyzer_engine = QualityAnalyzer()
        self.version_control_engine = AssetVersionControl(self.library_path)  # Use your library path
        self.init_ui()
        self.setup_connections()
    
    def init_ui(self):
        """Initialize the model tab UI."""
        main_layout = QHBoxLayout(self)
        
        # Create main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Model Browser & Tools
        left_panel = QWidget()
        left_panel.setMinimumWidth(300)
        left_panel.setMaximumWidth(400)
        left_layout = QVBoxLayout(left_panel)
        
        # Model Browser section
        browser_group = QGroupBox("Model Browser")
        browser_layout = QVBoxLayout()
        
        # Browser controls
        browser_controls = QHBoxLayout()
        self.load_model_btn = QPushButton("Load Model")
        self.load_model_btn.setIcon(get_icon("import_model"))
        self.load_folder_btn = QPushButton("Load Folder")
        self.load_folder_btn.setIcon(get_icon("import_folder"))
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(get_icon("refresh"))
        self.refresh_btn.setMaximumWidth(36)
        self.remove_model_btn = QPushButton()
        self.remove_model_btn.setIcon(get_icon("delete"))
        self.remove_model_btn.setMaximumWidth(36)
        
        browser_controls.addWidget(self.load_model_btn)
        browser_controls.addWidget(self.load_folder_btn)
        browser_controls.addWidget(self.refresh_btn)
        browser_controls.addWidget(self.remove_model_btn)
        browser_layout.addLayout(browser_controls)
        
        # Model tree
        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabels(["Name", "Type", "Size"])
        self.model_tree.setAlternatingRowColors(True)
        browser_layout.addWidget(self.model_tree)
        
        browser_group.setLayout(browser_layout)
        left_layout.addWidget(browser_group)
        
        # Model Tools section
        tools_group = QGroupBox("Model Tools")
        tools_layout = QVBoxLayout()
        
        # Analysis tools
        analysis_section = QVBoxLayout()
        analysis_label = QLabel("Analysis & Information")
        analysis_label.setStyleSheet("font-weight: bold; color: #4b7bec;")
        analysis_section.addWidget(analysis_label)
        
        self.analyze_btn = QPushButton("Analyze Selected")
        self.analyze_btn.setIcon(get_icon("diagnostics"))
        self.batch_analyze_btn = QPushButton("Batch Analysis")
        self.batch_analyze_btn.setIcon(get_icon("chart"))
        self.export_report_btn = QPushButton("Export Report")
        self.export_report_btn.setIcon(get_icon("export"))
        
        analysis_section.addWidget(self.analyze_btn)
        analysis_section.addWidget(self.batch_analyze_btn)
        analysis_section.addWidget(self.export_report_btn)
        tools_layout.addLayout(analysis_section)
        
        # Conversion tools
        conversion_section = QVBoxLayout()
        conversion_label = QLabel("Format Conversion")
        conversion_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        conversion_section.addWidget(conversion_label)
        
        self.convert_btn = QPushButton("Convert Format")
        self.convert_btn.setIcon(get_icon("refresh"))
        self.batch_convert_btn = QPushButton("Batch Convert")
        self.batch_convert_btn.setIcon(get_icon("batch_render"))
        
        conversion_section.addWidget(self.convert_btn)
        conversion_section.addWidget(self.batch_convert_btn)
        tools_layout.addLayout(conversion_section)
        
        # Optimization tools
        optimization_section = QVBoxLayout()
        optimization_label = QLabel("Optimization")
        optimization_label.setStyleSheet("font-weight: bold; color: #FF9800;")
        optimization_section.addWidget(optimization_label)
        
        self.simplify_btn = QPushButton("Simplify Mesh")
        self.simplify_btn.setIcon(get_icon("mesh_tools"))
        self.repair_btn = QPushButton("Repair Mesh")
        self.repair_btn.setIcon(get_icon("clean"))
        self.optimize_btn = QPushButton("Optimize")
        self.optimize_btn.setIcon(get_icon("performance"))
        
        optimization_section.addWidget(self.simplify_btn)
        optimization_section.addWidget(self.repair_btn)
        optimization_section.addWidget(self.optimize_btn)
        tools_layout.addLayout(optimization_section)
        
        tools_group.setLayout(tools_layout)
        left_layout.addWidget(tools_group)
        
        # Progress section
        progress_group = QGroupBox("Operations")
        progress_layout = QVBoxLayout()
        
        self.operation_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        progress_layout.addWidget(self.operation_label)
        progress_layout.addWidget(self.progress_bar)
        
        progress_group.setLayout(progress_layout)
        left_layout.addWidget(progress_group)
        
        splitter.addWidget(left_panel)
        
        # Right panel - Model Viewer & Details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Create tab widget for different views
        self.detail_tabs = QTabWidget()
        
        # 3D Viewer tab - Use OpenGL viewer
        self.model_viewer = ModelViewerWidget()
        self.detail_tabs.addTab(self.model_viewer, "3D Viewer")
        
        # Model Information tab
        info_widget = self.create_info_tab()
        self.detail_tabs.addTab(info_widget, "Information")
        
        # Analysis Results tab
        analysis_widget = self.create_analysis_tab()
        self.detail_tabs.addTab(analysis_widget, "Analysis")
        
        # Comparison tab
        comparison_widget = self.create_comparison_tab()
        self.detail_tabs.addTab(comparison_widget, "Compare")
        
        # Settings tab for OpenGL controls
        settings_widget = self.create_settings_tab()
        self.detail_tabs.addTab(settings_widget, "Settings")

        # Weight Painting tab
        self.painting_tab = PaintingTab()
        self.detail_tabs.addTab(self.painting_tab, "Painting")

        # Quality Analyzer tab
        self.quality_analyzer_tab = QualityAnalyzerUI()
        self.quality_analyzer_tab.analyzer = self.quality_analyzer_engine
        self.detail_tabs.addTab(self.quality_analyzer_tab, "Quality")

        # Version Control tab
        self.version_control_tab = VersionControlUI(library_path='output')
        self.version_control_tab.version_control = self.version_control_engine
        self.detail_tabs.addTab(self.version_control_tab, "Versions")
        
        right_layout.addWidget(self.detail_tabs)
        
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([350, 850])
        
        # Connect tab change signal (after all tabs are created)
        self.detail_tabs.currentChanged.connect(self.on_tab_changed)
    
    def _get_complexity_category(self, vertex_count):
        """Get complexity category based on vertex count."""
        if vertex_count < 1000:
            return "Low"
        elif vertex_count < 10000:
            return "Medium"
        elif vertex_count < 100000:
            return "High"
        else:
            return "Very High"

    def on_tab_changed(self, index):
        """Handle tab changes to update specific tabs like Painting."""
        if not hasattr(self, 'painting_tab') or not hasattr(self, 'detail_tabs'):
            return
            
        current_widget = self.detail_tabs.widget(index)
        if current_widget == self.painting_tab:
            if hasattr(self, 'current_model_path') and self.current_model_path:
                self.painting_tab.set_model(self.current_model_path)

    def _on_shader_changed(self, row):
        # 0: Wireframe, 1: Shaded, 2: Visualized, 3: Point Cloud
        self.viz_details_widget.setVisible(row == 2)
        if row == 0:
            self.model_viewer.set_render_mode("wireframe")
            self.analysis_list.blockSignals(True)
            self.analysis_list.setCurrentRow(0)
            self.analysis_list.blockSignals(False)
            self._on_analysis_changed(0)
        elif row == 1:
            self.model_viewer.set_render_mode("fill")
            self.analysis_list.blockSignals(True)
            self.analysis_list.setCurrentRow(0)
            self.analysis_list.blockSignals(False)
            self._on_analysis_changed(0)
        elif row == 2:
            self._on_viz_mode_changed(self.viz_combo.currentText())
        elif row == 3:
            self.model_viewer.set_render_mode("point_cloud")
            self.analysis_list.blockSignals(True)
            self.analysis_list.setCurrentRow(0)
            self.analysis_list.blockSignals(False)
            self._on_analysis_changed(0)

    def _on_viz_mode_changed(self, text):
        mode = text.strip().lower().replace(" ", "_")
        self.model_viewer.set_render_mode(mode)
        self.analysis_list.blockSignals(True)
        self.analysis_list.setCurrentRow(0)
        self.analysis_list.blockSignals(False)
        self._on_analysis_changed(0)

    def _on_analysis_changed(self, row):
        # 0: None, 1: Zebra, 2: Curvature
        self.zebra_details.setVisible(row == 1)
        self.curvature_details.setVisible(row == 2)
        
        if row == 1:
            self.model_viewer.set_render_mode("zebra")
            self.shader_list.blockSignals(True)
            self.shader_list.setCurrentRow(-1)
            self.shader_list.blockSignals(False)
            self.viz_details_widget.setVisible(False)
        elif row == 2:
            self.model_viewer.set_render_mode("curvature")
            self.shader_list.blockSignals(True)
            self.shader_list.setCurrentRow(-1)
            self.shader_list.blockSignals(False)
            self.viz_details_widget.setVisible(False)
        elif row == 0:
            # Revert to shader mode
            if self.shader_list.currentRow() == -1:
                self.shader_list.blockSignals(True)
                self.shader_list.setCurrentRow(1)
                self.shader_list.blockSignals(False)
                self.model_viewer.set_render_mode("fill")

    def create_settings_tab(self):
        """Create the OpenGL rendering settings tab."""
        widget = QWidget()
        
        # Create scrollable area for all the controls
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        
        # 1. Shaders Group
        shaders_group = QGroupBox("Shaders")
        shaders_layout = QVBoxLayout()
        
        self.shader_list = QListWidget()
        self.shader_list.addItems(["Wireframe", "Shaded", "Visualized", "Point Cloud"])
        self.shader_list.setFixedHeight(95) # Approx 4 items tall
        self.shader_list.setCurrentRow(1) # Default to Shaded
        self.shader_list.currentRowChanged.connect(self._on_shader_changed)
        shaders_layout.addWidget(self.shader_list)

        # Visualized details
        self.viz_details_widget = QWidget()
        viz_details_layout = QFormLayout(self.viz_details_widget)
        viz_details_layout.setContentsMargins(0, 0, 0, 0)
        self.viz_combo = QComboBox()
        self.viz_combo.addItems(["Vertex Colors", "Material IDs", "Albedo", "Normal", "Specular/Metallic", "Occlusion", "Emissive"])
        self.viz_combo.currentTextChanged.connect(self._on_viz_mode_changed)
        viz_details_layout.addRow("Viz Mode:", self.viz_combo)
        self.viz_details_widget.setVisible(False)
        shaders_layout.addWidget(self.viz_details_widget)

        shaders_group.setLayout(shaders_layout)
        layout.addWidget(shaders_group)

        # 2. Surface Analysis Group
        analysis_group = QGroupBox("Surface Analysis")
        analysis_layout = QVBoxLayout()
        
        self.analysis_list = QListWidget()
        self.analysis_list.addItems(["None", "Zebra", "Curvature Map"])
        self.analysis_list.setFixedHeight(75)
        self.analysis_list.setCurrentRow(0)
        self.analysis_list.currentRowChanged.connect(self._on_analysis_changed)
        analysis_layout.addWidget(self.analysis_list)

        # Zebra Details
        self.zebra_details = QWidget()
        zebra_layout = QFormLayout(self.zebra_details)
        zebra_layout.setContentsMargins(0, 0, 0, 0)
        self.zebra_dir_combo = QComboBox()
        self.zebra_dir_combo.addItems(["Horizontal", "Vertical"])
        self.zebra_dir_combo.currentIndexChanged.connect(lambda i: self.model_viewer.viewer_3d.set_zebra_direction(i) if hasattr(self.model_viewer, 'viewer_3d') else None)
        self.zebra_scale_spin = QDoubleSpinBox()
        self.zebra_scale_spin.setRange(0.1, 10.0)
        self.zebra_scale_spin.setValue(1.0)
        self.zebra_scale_spin.setSingleStep(0.1)
        self.zebra_scale_spin.valueChanged.connect(lambda v: self.model_viewer.viewer_3d.set_zebra_scale(v) if hasattr(self.model_viewer, 'viewer_3d') else None)
        zebra_layout.addRow("Direction:", self.zebra_dir_combo)
        zebra_layout.addRow("Scale:", self.zebra_scale_spin)
        self.zebra_details.setVisible(False)
        analysis_layout.addWidget(self.zebra_details)

        # Curvature Details
        self.curvature_details = QWidget()
        curvature_layout = QFormLayout(self.curvature_details)
        curvature_layout.setContentsMargins(0, 0, 0, 0)
        self.curvature_scale_spin = QDoubleSpinBox()
        self.curvature_scale_spin.setRange(0.1, 10.0)
        self.curvature_scale_spin.setValue(1.0)
        self.curvature_scale_spin.setSingleStep(0.1)
        self.curvature_scale_spin.valueChanged.connect(lambda v: self.model_viewer.viewer_3d.set_curvature_scale(v) if hasattr(self.model_viewer, 'viewer_3d') else None)
        curvature_layout.addRow("Scale:", self.curvature_scale_spin)
        self.curvature_details.setVisible(False)
        analysis_layout.addWidget(self.curvature_details)

        analysis_group.setLayout(analysis_layout)
        layout.addWidget(analysis_group)

        # 3. View Options
        options_group = QGroupBox("Options")
        options_layout = QFormLayout()

        self.show_edges_cb = QCheckBox("Show Edges")
        self.show_edges_cb.toggled.connect(lambda c: self.model_viewer.viewer_3d.set_show_edges(c) if hasattr(self.model_viewer, 'viewer_3d') else None)
        options_layout.addRow(self.show_edges_cb)

        self.show_hidden_edges_cb = QCheckBox("Show Hidden Edges")
        self.show_hidden_edges_cb.toggled.connect(lambda c: self.model_viewer.viewer_3d.set_show_hidden_edges(c) if hasattr(self.model_viewer, 'viewer_3d') else None)
        options_layout.addRow(self.show_hidden_edges_cb)

        self.show_grid_cb = QCheckBox("Show Grid & Axes")
        self.show_grid_cb.setChecked(False)
        self.show_grid_cb.toggled.connect(self.model_viewer.set_show_grid)
        options_layout.addRow(self.show_grid_cb)
        
        self.auto_rotate_cb = QCheckBox("Auto Rotate")
        self.auto_rotate_cb.setChecked(False)
        self.auto_rotate_cb.toggled.connect(lambda enabled: self.model_viewer.viewer_3d.set_auto_rotate(enabled) if hasattr(self.model_viewer, 'viewer_3d') and hasattr(self.model_viewer.viewer_3d, 'set_auto_rotate') else None)
        options_layout.addRow(self.auto_rotate_cb)
        
        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.5, 20.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setValue(1.0)
        self.line_width_spin.valueChanged.connect(self.model_viewer.set_line_width)
        options_layout.addRow("Line Width:", self.line_width_spin)
        
        self.point_size_spin = QDoubleSpinBox()
        self.point_size_spin.setRange(0.1, 20.0)
        self.point_size_spin.setSingleStep(0.5)
        self.point_size_spin.setValue(3.0)
        self.point_size_spin.valueChanged.connect(self.model_viewer.set_point_size)
        options_layout.addRow("Point Size:", self.point_size_spin)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # Lighting group
        light_group = QGroupBox("Lighting")
        light_layout = QFormLayout()
        
        self.lighting_enable_cb = QCheckBox("Enable Lighting")
        self.lighting_enable_cb.setChecked(True)
        self.lighting_enable_cb.toggled.connect(self.model_viewer.set_use_lighting)
        light_layout.addRow(self.lighting_enable_cb)
        
        self.ambient_spin = QDoubleSpinBox()
        self.ambient_spin.setRange(0.0, 2.0)
        self.ambient_spin.setSingleStep(0.05)
        self.ambient_spin.setValue(0.3)
        
        self.diffuse_spin = QDoubleSpinBox()
        self.diffuse_spin.setRange(0.0, 3.0)
        self.diffuse_spin.setSingleStep(0.1)
        self.diffuse_spin.setValue(1.0)
        
        self.specular_spin = QDoubleSpinBox()
        self.specular_spin.setRange(0.0, 3.0)
        self.specular_spin.setSingleStep(0.1)
        self.specular_spin.setValue(1.0)
        
        self.shininess_spin = QDoubleSpinBox()
        self.shininess_spin.setRange(1.0, 256.0)
        self.shininess_spin.setSingleStep(1.0)
        self.shininess_spin.setValue(32.0)
        
        # Wire changes together
        def apply_lighting_params():
            self.model_viewer.set_lighting_params(
                ambient=self.ambient_spin.value(),
                diffuse=self.diffuse_spin.value(),
                specular=self.specular_spin.value(),
                shininess=self.shininess_spin.value(),
            )
        for sp in (self.ambient_spin, self.diffuse_spin, self.specular_spin, self.shininess_spin):
            sp.valueChanged.connect(apply_lighting_params)
        
        light_layout.addRow("Ambient:", self.ambient_spin)
        light_layout.addRow("Diffuse:", self.diffuse_spin)
        light_layout.addRow("Specular:", self.specular_spin)
        light_layout.addRow("Shininess:", self.shininess_spin)
        
        light_group.setLayout(light_layout)
        layout.addWidget(light_group)
        
        # Materials group
        mat_group = QGroupBox("Materials & Data")
        mat_layout = QFormLayout()
        
        self.textures_cb = QCheckBox("Use Textures")
        self.textures_cb.setChecked(True)
        self.textures_cb.toggled.connect(self.model_viewer.set_use_textures)
        
        self.vcolors_cb = QCheckBox("Use Vertex Colors")
        self.vcolors_cb.setChecked(True)
        self.vcolors_cb.toggled.connect(self.model_viewer.set_use_vertex_colors)
        
        mat_layout.addRow(self.textures_cb)
        mat_layout.addRow(self.vcolors_cb)
        mat_group.setLayout(mat_layout)
        layout.addWidget(mat_group)
        
        # Colors group
        color_group = QGroupBox("Colors")
        color_layout = QFormLayout()
        
        # Wireframe color
        self.wire_color_preview = QLabel("  ")
        self.wire_color_preview.setFixedSize(36, 18)
        def set_wire_preview(color: QColor):
            self.wire_color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
        def pick_wire_color():
            col = QColorDialog.getColor(QColor(0, 255, 0), self, "Select Wireframe Color")
            if col.isValid():
                set_wire_preview(col)
                self.model_viewer.set_wire_color(col.red()/255.0, col.green()/255.0, col.blue()/255.0)
        wire_row = QHBoxLayout(); wire_btn = QPushButton("Choose..."); wire_btn.clicked.connect(pick_wire_color)
        wire_row.addWidget(self.wire_color_preview); wire_row.addWidget(wire_btn); wire_row.addStretch()
        color_layout.addRow("Wireframe:", wire_row)
        set_wire_preview(QColor(0, 255, 0))
        
        # Base/Default mesh color
        self.base_color_preview = QLabel("  ")
        self.base_color_preview.setFixedSize(36, 18)
        def set_base_preview(color: QColor):
            self.base_color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
        def pick_base_color():
            col = QColorDialog.getColor(QColor(179, 179, 230), self, "Select Default Mesh Color")
            if col.isValid():
                set_base_preview(col)
                self.model_viewer.set_base_color(col.red()/255.0, col.green()/255.0, col.blue()/255.0)
        base_row = QHBoxLayout(); base_btn = QPushButton("Choose..."); base_btn.clicked.connect(pick_base_color)
        base_row.addWidget(self.base_color_preview); base_row.addWidget(base_btn); base_row.addStretch()
        color_layout.addRow("Default Mesh:", base_row)
        set_base_preview(QColor(179, 179, 230))  # Light blue default

            # Point cloud color
        self.point_color_preview = QLabel("  ")
        self.point_color_preview.setFixedSize(36, 18)
        def set_point_preview(color: QColor):
            self.point_color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
        def pick_point_color():
            col = QColorDialog.getColor(QColor(255, 255, 0), self, "Select Point Cloud Color")
            if col.isValid():
                set_point_preview(col)
                self.model_viewer.set_point_color(col.red()/255.0, col.green()/255.0, col.blue()/255.0)
        point_row = QHBoxLayout(); point_btn = QPushButton("Choose..."); point_btn.clicked.connect(pick_point_color)
        point_row.addWidget(self.point_color_preview); point_row.addWidget(point_btn); point_row.addStretch()
        color_layout.addRow("Point Cloud:", point_row)
        set_point_preview(QColor(255, 255, 0))  # Yellow default      
        
        color_group.setLayout(color_layout)
        layout.addWidget(color_group)
        
        # View Controls group
        view_group = QGroupBox("View Controls")
        view_layout = QVBoxLayout()
        
        view_buttons_row1 = QHBoxLayout()
        reset_view_btn = QPushButton("Reset View")
        reset_view_btn.clicked.connect(self.model_viewer.viewer_3d.reset_view)
        
        clear_viewer_btn = QPushButton("Clear Viewer")
        clear_viewer_btn.clicked.connect(self.model_viewer.clear)
        
        view_buttons_row1.addWidget(reset_view_btn)
        view_buttons_row1.addWidget(clear_viewer_btn)
        view_layout.addLayout(view_buttons_row1)
        
        view_group.setLayout(view_layout)
        layout.addWidget(view_group)
        
        # Presets group
        """presets_group = QGroupBox("Presets")
        presets_layout = QVBoxLayout()
        
        presets_row1 = QHBoxLayout()
        preset_wireframe_btn = QPushButton("Wireframe")
        preset_wireframe_btn.clicked.connect(self.apply_wireframe_preset)
        
        preset_solid_btn = QPushButton("Solid")
        preset_solid_btn.clicked.connect(self.apply_solid_preset)
        
        presets_row1.addWidget(preset_wireframe_btn)
        presets_row1.addWidget(preset_solid_btn)
        presets_layout.addLayout(presets_row1)
        
        presets_row2 = QHBoxLayout()
        preset_debug_btn = QPushButton("Debug View")
        preset_debug_btn.clicked.connect(self.apply_debug_preset)
        
        presets_row2.addWidget(preset_debug_btn)
        presets_row2.addStretch()
        presets_layout.addLayout(presets_row2)
        
        presets_group.setLayout(presets_layout)
        layout.addWidget(presets_group)
        
        layout.addStretch()"""
        
        # Set up scroll area
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        main_layout = QVBoxLayout(widget)
        main_layout.addWidget(scroll_area)
        
        return widget
    
    def apply_wireframe_preset(self):
        """Apply wireframe viewing preset."""
        self.render_mode_combo.setCurrentText("Wireframe")
        self.lighting_enable_cb.setChecked(False)
        self.line_width_spin.setValue(1.5)
        
    def apply_solid_preset(self):
        """Apply solid/filled viewing preset."""
        self.render_mode_combo.setCurrentText("Fill")
        self.lighting_enable_cb.setChecked(True)
        self.textures_cb.setChecked(True)
        self.vcolors_cb.setChecked(True)
        
    def apply_debug_preset(self):
        """Apply debug viewing preset with wireframe overlay."""
        self.render_mode_combo.setCurrentText("Overlay")
        self.lighting_enable_cb.setChecked(True)
        self.line_width_spin.setValue(2.0)

    def create_info_tab(self):
        """Create the model information tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Basic information
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        
        self.file_name_label = QLabel("No model loaded")
        self.file_size_label = QLabel("-")
        self.file_format_label = QLabel("-")
        self.vertices_label = QLabel("-")
        self.faces_label = QLabel("-")
        self.edges_label = QLabel("-")
        
        basic_layout.addRow("File Name:", self.file_name_label)
        basic_layout.addRow("File Size:", self.file_size_label)
        basic_layout.addRow("Format:", self.file_format_label)
        basic_layout.addRow("Vertices:", self.vertices_label)
        basic_layout.addRow("Faces:", self.faces_label)
        basic_layout.addRow("Edges:", self.edges_label)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # Geometry information
        geometry_group = QGroupBox("Geometry")
        geometry_layout = QFormLayout()
        
        self.surface_area_label = QLabel("-")
        self.volume_label = QLabel("-")
        self.is_watertight_label = QLabel("-")
        self.bounds_label = QLabel("-")
        self.uv_label = QLabel("-")
        self.vcolors_label = QLabel("-")
        self.materials_label = QLabel("-")
        
        geometry_layout.addRow("Surface Area:", self.surface_area_label)
        geometry_layout.addRow("Volume:", self.volume_label)
        geometry_layout.addRow("Watertight:", self.is_watertight_label)
        geometry_layout.addRow("Bounds:", self.bounds_label)
        geometry_layout.addRow("UV Map:", self.uv_label)
        geometry_layout.addRow("Vertex Colors:", self.vcolors_label)
        geometry_layout.addRow("Materials:", self.materials_label)
        
        geometry_group.setLayout(geometry_layout)
        layout.addWidget(geometry_group)
        
        # Texture Data Group
        texture_group = QGroupBox("Texture Data")
        texture_layout = QFormLayout()
        
        self.tex_albedo_label = QLabel("-")
        self.tex_normal_label = QLabel("-")
        self.tex_specular_label = QLabel("-")
        self.tex_occlusion_label = QLabel("-")
        self.tex_emissive_label = QLabel("-")
        
        texture_layout.addRow("Albedo:", self.tex_albedo_label)
        texture_layout.addRow("Normal:", self.tex_normal_label)
        texture_layout.addRow("Specular/Metallic:", self.tex_specular_label)
        texture_layout.addRow("Occlusion:", self.tex_occlusion_label)
        texture_layout.addRow("Emissive:", self.tex_emissive_label)
        
        texture_group.setLayout(texture_layout)
        layout.addWidget(texture_group)
        
        layout.addStretch()
        return widget
    
    def create_analysis_tab(self):
        """Create the analysis results tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Analysis controls
        controls_layout = QHBoxLayout()
        
        self.analysis_type = QComboBox()
        self.analysis_type.addItems([
            "Quality Check", "Mesh Validation", "Performance Analysis",
            "Topology Analysis", "Material Analysis"
        ])
        
        run_analysis_btn = QPushButton("Run Analysis")
        run_analysis_btn.clicked.connect(self.run_detailed_analysis)
        
        export_analysis_btn = QPushButton("Export Results")
        export_analysis_btn.clicked.connect(self.export_current_analysis)
        
        controls_layout.addWidget(QLabel("Analysis Type:"))
        controls_layout.addWidget(self.analysis_type)
        controls_layout.addWidget(run_analysis_btn)
        controls_layout.addWidget(export_analysis_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Results display - Use text area instead of table for detailed analysis
        self.analysis_results = QTextEdit()
        self.analysis_results.setReadOnly(True)
        self.analysis_results.setPlainText("No analysis performed yet. Select a model and run analysis.")
        self.analysis_results.setFont(QFont("Consolas", 10))  # Monospace font for better formatting
        
        layout.addWidget(self.analysis_results)
        
        # Keep the old analysis table for compatibility (hidden by default)
        self.analysis_table = QTableWidget()
        self.analysis_table.setColumnCount(3)
        self.analysis_table.setHorizontalHeaderLabels(["Property", "Value", "Status"])
        self.analysis_table.horizontalHeader().setStretchLastSection(True)
        self.analysis_table.setVisible(False)  # Hidden by default
        layout.addWidget(self.analysis_table)
        
        return widget
    
    def create_comparison_tab(self):
        """Create the enhanced multi-model comparison tab with support for 3+ models."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Model management section
        management_group = QGroupBox("Model Management")
        management_layout = QVBoxLayout()
        
        # Model addition controls
        add_controls_layout = QHBoxLayout()
        
        # Direct file selection
        self.add_model_path = QLineEdit()
        self.add_model_path.setPlaceholderText("Select model file to add to comparison...")
        browse_add_btn = QPushButton("Browse")
        browse_add_btn.setIcon(get_icon("folder"))
        browse_add_btn.clicked.connect(self.browse_add_comparison_model)
        add_model_btn = QPushButton("Add Model")
        add_model_btn.setIcon(get_icon("add"))
        add_model_btn.setProperty("primary", "true")
        add_model_btn.clicked.connect(self.add_model_to_comparison)
        
        add_controls_layout.addWidget(QLabel("Add Model:"))
        add_controls_layout.addWidget(self.add_model_path)
        add_controls_layout.addWidget(browse_add_btn)
        add_controls_layout.addWidget(add_model_btn)
        management_layout.addLayout(add_controls_layout)
        
        # Quick actions
        quick_actions_layout = QHBoxLayout()
        use_current_btn = QPushButton("Add Current Model")
        use_current_btn.setIcon(get_icon("models"))
        use_current_btn.clicked.connect(self.add_current_to_multi_comparison)
        add_all_library_btn = QPushButton("Add All from Library")
        add_all_library_btn.setIcon(get_icon("library"))
        add_all_library_btn.clicked.connect(self.add_all_library_to_comparison)
        clear_all_btn = QPushButton("Clear All Models")
        clear_all_btn.setIcon(get_icon("delete"))
        clear_all_btn.clicked.connect(self.clear_all_comparison_models)
        
        quick_actions_layout.addWidget(use_current_btn)
        quick_actions_layout.addWidget(add_all_library_btn)
        quick_actions_layout.addStretch()
        quick_actions_layout.addWidget(clear_all_btn)
        management_layout.addLayout(quick_actions_layout)
        
        # Model list display
        self.comparison_models_list = QListWidget()
        self.comparison_models_list.setMaximumHeight(120)
        self.comparison_models_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        management_layout.addWidget(QLabel("Models in Comparison:"))
        management_layout.addWidget(self.comparison_models_list)
        
        # Model list controls
        list_controls_layout = QHBoxLayout()
        remove_selected_btn = QPushButton("Remove Selected")
        remove_selected_btn.setIcon(get_icon("delete"))
        remove_selected_btn.clicked.connect(self.remove_selected_comparison_models)
        move_up_btn = QPushButton("Move Up")
        move_up_btn.setIcon(get_icon("arrow_up"))
        move_up_btn.clicked.connect(self.move_comparison_model_up)
        move_down_btn = QPushButton("Move Down")
        move_down_btn.setIcon(get_icon("arrow_down"))
        move_down_btn.clicked.connect(self.move_comparison_model_down)
        
        list_controls_layout.addWidget(remove_selected_btn)
        list_controls_layout.addWidget(move_up_btn)
        list_controls_layout.addWidget(move_down_btn)
        list_controls_layout.addStretch()
        management_layout.addLayout(list_controls_layout)
        
        management_group.setLayout(management_layout)
        layout.addWidget(management_group)
        
        # Comparison controls
        controls_group = QGroupBox("Comparison Controls")
        controls_layout = QHBoxLayout()
        
        # Analysis options
        self.include_geometry_cb = QCheckBox("Geometry Properties")
        self.include_geometry_cb.setChecked(True)
        self.include_quality_cb = QCheckBox("Quality Metrics")
        self.include_quality_cb.setChecked(True)
        self.include_performance_cb = QCheckBox("Performance Data")
        self.include_performance_cb.setChecked(True)
        self.include_file_info_cb = QCheckBox("File Information")
        self.include_file_info_cb.setChecked(True)
        
        # Main compare button
        compare_all_btn = QPushButton("Compare All Models")
        compare_all_btn.setIcon(get_icon("overlays"))
        compare_all_btn.setProperty("primary", "true")
        compare_all_btn.clicked.connect(self.compare_all_models)
        
        controls_layout.addWidget(QLabel("Include:"))
        controls_layout.addWidget(self.include_geometry_cb)
        controls_layout.addWidget(self.include_quality_cb)
        controls_layout.addWidget(self.include_performance_cb)
        controls_layout.addWidget(self.include_file_info_cb)
        controls_layout.addStretch()
        controls_layout.addWidget(compare_all_btn)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Enhanced comparison results table with scrolling
        self.multi_comparison_table = QTableWidget()
        self.multi_comparison_table.setAlternatingRowColors(True)
        self.multi_comparison_table.setSortingEnabled(True)
        self.multi_comparison_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        # Set up table headers - will be populated when models are compared
        self.multi_comparison_table.setColumnCount(1)
        self.multi_comparison_table.setHorizontalHeaderLabels(["Property"])
        
        layout.addWidget(self.multi_comparison_table)
        
        # Analysis and export controls
        results_controls_layout = QHBoxLayout()
        
        # Statistics summary
        self.comparison_summary_label = QLabel("No models loaded for comparison")
        self.comparison_summary_label.setStyleSheet("background: #14151b; color: #8c93a8; padding: 8px; border: 1px solid #252836; border-radius: 4px;")
        
        # Export options
        export_comparison_btn = QPushButton("Export Comparison")
        export_comparison_btn.setIcon(get_icon("export"))
        export_comparison_btn.clicked.connect(self.export_multi_comparison_results)
        export_detailed_btn = QPushButton("Export Detailed Report")
        export_detailed_btn.setIcon(get_icon("export"))
        export_detailed_btn.clicked.connect(self.export_detailed_comparison_report)
        
        # Analysis tools
        find_best_btn = QPushButton("Find Best Model")
        find_best_btn.setIcon(get_icon("sparkles"))
        find_best_btn.clicked.connect(self.find_best_model)
        find_similar_btn = QPushButton("Find Similar Models")
        find_similar_btn.setIcon(get_icon("search"))
        find_similar_btn.clicked.connect(self.find_similar_models)
        
        results_controls_layout.addWidget(self.comparison_summary_label, 1)
        results_controls_layout.addWidget(find_best_btn)
        results_controls_layout.addWidget(find_similar_btn)
        results_controls_layout.addWidget(export_comparison_btn)
        results_controls_layout.addWidget(export_detailed_btn)
        
        layout.addLayout(results_controls_layout)
        
        # Initialize comparison models list
        self.comparison_models = []  # List of dicts with model data
        
        return widget
    
    def browse_add_comparison_model(self):
        """Browse for a model to add to comparison."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Model for Comparison",
            "", "3D Models (*.obj *.stl *.ply *.glb *.gltf *.fbx *.dae *.x3d);;All Files (*)"
        )
        
        if file_path:
            self.add_model_path.setText(file_path)
    
    def add_model_to_comparison(self):
        """Add a model to the comparison list."""
        file_path = self.add_model_path.text().strip()
        
        if not file_path:
            QMessageBox.warning(self, "No File Selected", "Please select a model file to add.")
            return
        
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "File Not Found", f"The selected file does not exist:\n{file_path}")
            return
        
        # Check if model is already in comparison
        for model in self.comparison_models:
            if model['path'] == file_path:
                QMessageBox.information(self, "Already Added", "This model is already in the comparison list.")
                return
        
        try:
            # Load and analyze the model
            self.operation_label.setText(f"Analyzing {os.path.basename(file_path)}...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            
            mesh_obj = trimesh.load(file_path)
            mesh = _as_trimesh(mesh_obj)
            
            if mesh is None:
                raise ValueError("Could not load as a valid mesh")
            
            # Create comprehensive model data
            model_data = {
                'path': file_path,
                'name': os.path.basename(file_path),
                'format': os.path.splitext(file_path)[1][1:].upper(),
                'file_size_mb': os.path.getsize(file_path) / (1024 * 1024),
                'vertices': len(mesh.vertices),
                'faces': len(mesh.faces),
                'edges': len(mesh.edges),
                'surface_area': float(mesh.area),
                'volume': float(mesh.volume) if mesh.is_volume else 0.0,
                'is_watertight': mesh.is_watertight,
                'is_winding_consistent': mesh.is_winding_consistent,
                'bounds': mesh.bounds.tolist(),
                'center': mesh.center_mass.tolist() if hasattr(mesh, 'center_mass') else [0.0, 0.0, 0.0],
                'bounding_box_volume': mesh.bounding_box.volume,
                'convex_hull_volume': mesh.convex_hull.volume if hasattr(mesh, 'convex_hull') else 0.0,
                # Performance metrics
                'estimated_memory_mb': (len(mesh.vertices) * 3 + len(mesh.faces) * 3) * 4 / (1024 * 1024),
                'complexity': self._get_complexity_category(len(mesh.vertices)),
                # Quality metrics
                'vertex_density': len(mesh.vertices) / mesh.area if mesh.area > 0 else 0,
                'face_density': len(mesh.faces) / mesh.area if mesh.area > 0 else 0,
                'added_timestamp': datetime.now().isoformat()
            }
            
            # Add face angle analysis if available
            if hasattr(mesh, 'face_angles'):
                face_angles = mesh.face_angles
                model_data.update({
                    'min_face_angle': float(np.rad2deg(np.min(face_angles))),
                    'max_face_angle': float(np.rad2deg(np.max(face_angles))),
                    'avg_face_angle': float(np.rad2deg(np.mean(face_angles))),
                    'degenerate_faces': int(np.sum(face_angles < np.deg2rad(1)))
                })
            
            self.comparison_models.append(model_data)
            self.update_comparison_models_list()
            self.add_model_path.clear()
            
            self.progress_bar.setVisible(False)
            self.operation_label.setText(f"Added {os.path.basename(file_path)} to comparison")
            
            QMessageBox.information(self, "Model Added", 
                f"Successfully added '{os.path.basename(file_path)}' to comparison.\n"
                f"Total models: {len(self.comparison_models)}")
        
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Failed to add model")
            QMessageBox.critical(self, "Error Adding Model", f"Failed to add model to comparison:\n{str(e)}")
    
    def add_current_to_multi_comparison(self):
        """Add the currently loaded model to comparison."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Current Model", "Please load a model first.")
            return
        
        self.add_model_path.setText(self.current_model_path)
        self.add_model_to_comparison()
    
    def add_all_library_to_comparison(self):
        """Add all models from the library to comparison."""
        if not self.model_library:
            QMessageBox.warning(self, "No Models in Library", "No models available in the library.")
            return
        
        reply = QMessageBox.question(
            self, "Add All Models", 
            f"Add all {len(self.model_library)} models from library to comparison?\n"
            "This may take some time for large libraries.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        added_count = 0
        failed_count = 0
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.model_library))
        
        for i, model_info in enumerate(self.model_library):
            self.progress_bar.setValue(i)
            file_path = model_info['path']
            
            # Skip if already in comparison
            if any(model['path'] == file_path for model in self.comparison_models):
                continue
            
            try:
                self.add_model_path.setText(file_path)
                self.add_model_to_comparison()  # This will handle the analysis
                added_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Failed to add {file_path}: {e}")
        
        self.progress_bar.setVisible(False)
        self.operation_label.setText(f"Added {added_count} models to comparison")
        
        QMessageBox.information(self, "Batch Add Complete", 
            f"Successfully added {added_count} models to comparison.\n"
            f"Failed: {failed_count}\n"
            f"Total models in comparison: {len(self.comparison_models)}")
    
    def update_comparison_models_list(self):
        """Update the comparison models list display."""
        self.comparison_models_list.clear()
        
        for i, model in enumerate(self.comparison_models):
            item_text = f"{i+1:2d}. {model['name']} ({model['vertices']:,} vertices, {model['file_size_mb']:.1f} MB)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.comparison_models_list.addItem(item)
        
        # Update summary
        if self.comparison_models:
            total_vertices = sum(m['vertices'] for m in self.comparison_models)
            total_faces = sum(m['faces'] for m in self.comparison_models)
            total_size = sum(m['file_size_mb'] for m in self.comparison_models)
            self.comparison_summary_label.setText(
                f"{len(self.comparison_models)} models | "
                f"{total_vertices:,} vertices | "
                f"{total_faces:,} faces | "
                f"{total_size:.1f} MB total"
            )
        else:
            self.comparison_summary_label.setText("No models loaded for comparison")
    
    def remove_selected_comparison_models(self):
        """Remove selected models from comparison."""
        selected_items = self.comparison_models_list.selectedItems()
        
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select models to remove.")
            return
        
        # Get indices to remove (in reverse order to maintain validity)
        indices_to_remove = sorted([item.data(Qt.ItemDataRole.UserRole) for item in selected_items], reverse=True)
        
        # Remove models
        for index in indices_to_remove:
            del self.comparison_models[index]
        
        self.update_comparison_models_list()
        self.operation_label.setText(f"Removed {len(indices_to_remove)} models from comparison")
    
    def move_comparison_model_up(self):
        """Move selected model up in the list."""
        selected_items = self.comparison_models_list.selectedItems()
        if len(selected_items) != 1:
            QMessageBox.warning(self, "Single Selection Required", "Please select exactly one model to move.")
            return
        
        index = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if index > 0:
            # Swap with previous
            self.comparison_models[index], self.comparison_models[index-1] = \
                self.comparison_models[index-1], self.comparison_models[index]
            self.update_comparison_models_list()
            # Re-select moved item
            self.comparison_models_list.setCurrentRow(index-1)
    
    def move_comparison_model_down(self):
        """Move selected model down in the list."""
        selected_items = self.comparison_models_list.selectedItems()
        if len(selected_items) != 1:
            QMessageBox.warning(self, "Single Selection Required", "Please select exactly one model to move.")
            return
        
        index = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if index < len(self.comparison_models) - 1:
            # Swap with next
            self.comparison_models[index], self.comparison_models[index+1] = \
                self.comparison_models[index+1], self.comparison_models[index]
            self.update_comparison_models_list()
            # Re-select moved item
            self.comparison_models_list.setCurrentRow(index+1)
    
    def clear_all_comparison_models(self):
        """Clear all models from comparison."""
        if not self.comparison_models:
            return
        
        reply = QMessageBox.question(
            self, "Clear All Models", 
            f"Remove all {len(self.comparison_models)} models from comparison?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.comparison_models.clear()
            self.update_comparison_models_list()
            self.multi_comparison_table.setRowCount(0)
            self.multi_comparison_table.setColumnCount(1)
            self.multi_comparison_table.setHorizontalHeaderLabels(["Property"])
            self.operation_label.setText("Cleared all comparison models")
    
    def compare_all_models(self):
        """Perform comprehensive comparison of all models."""
        if len(self.comparison_models) < 2:
            QMessageBox.warning(self, "Insufficient Models", 
                "Please add at least 2 models to perform comparison.")
            return
        
        try:
            self.operation_label.setText("Performing multi-model comparison...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            
            # Prepare comparison properties based on selected options
            comparison_properties = []
            
            if self.include_file_info_cb.isChecked():
                comparison_properties.extend([
                    ('File Name', 'name', str),
                    ('Format', 'format', str),
                    ('File Size (MB)', 'file_size_mb', lambda x: f"{x:.2f}"),
                ])
            
            if self.include_geometry_cb.isChecked():
                comparison_properties.extend([
                    ('Vertices', 'vertices', lambda x: f"{x:,}"),
                    ('Faces', 'faces', lambda x: f"{x:,}"),
                    ('Edges', 'edges', lambda x: f"{x:,}"),
                    ('Surface Area', 'surface_area', lambda x: f"{x:.4f}"),
                    ('Volume', 'volume', lambda x: f"{x:.4f}" if x > 0 else "N/A"),
                    ('Bounding Box Volume', 'bounding_box_volume', lambda x: f"{x:.4f}"),
                    ('Convex Hull Volume', 'convex_hull_volume', lambda x: f"{x:.4f}" if x > 0 else "N/A"),
                ])
            
            if self.include_quality_cb.isChecked():
                comparison_properties.extend([
                    ('Watertight', 'is_watertight', lambda x: "Yes" if x else "No"),
                    ('Winding Consistent', 'is_winding_consistent', lambda x: "Yes" if x else "No"),
                    ('Vertex Density', 'vertex_density', lambda x: f"{x:.2f}"),
                    ('Face Density', 'face_density', lambda x: f"{x:.2f}"),
                ])
                
                # Add face angle properties if available
                if any('min_face_angle' in model for model in self.comparison_models):
                    comparison_properties.extend([
                        ('Min Face Angle (°)', 'min_face_angle', lambda x: f"{x:.2f}" if x is not None else "N/A"),
                        ('Max Face Angle (°)', 'max_face_angle', lambda x: f"{x:.2f}" if x is not None else "N/A"),
                        ('Avg Face Angle (°)', 'avg_face_angle', lambda x: f"{x:.2f}" if x is not None else "N/A"),
                        ('Degenerate Faces', 'degenerate_faces', lambda x: f"{x:,}" if x is not None else "N/A"),
                    ])
            
            if self.include_performance_cb.isChecked():
                comparison_properties.extend([
                    ('Estimated Memory (MB)', 'estimated_memory_mb', lambda x: f"{x:.2f}"),
                    ('Complexity', 'complexity', str),
                ])
            
            # Set up table
            self.multi_comparison_table.setRowCount(len(comparison_properties))
            self.multi_comparison_table.setColumnCount(len(self.comparison_models) + 1)
            
            # Set headers
            headers = ['Property'] + [f"Model {i+1}\n({model['name']})" for i, model in enumerate(self.comparison_models)]
            self.multi_comparison_table.setHorizontalHeaderLabels(headers)
            
            # Populate table
            for row, (prop_name, prop_key, formatter) in enumerate(comparison_properties):
                # Property name
                prop_item = QTableWidgetItem(prop_name)
                prop_item.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                prop_item.setBackground(QColor(240, 240, 240))
                self.multi_comparison_table.setItem(row, 0, prop_item)
                
                # Model values
                values = []
                for col, model in enumerate(self.comparison_models):
                    value = model.get(prop_key, None)
                    if value is not None:
                        formatted_value = formatter(value)
                    else:
                        formatted_value = "N/A"
                    
                    values.append(value)
                    item = QTableWidgetItem(formatted_value)
                    
                    # Add color coding for numerical values
                    if prop_key in ['vertices', 'faces', 'file_size_mb', 'surface_area', 'volume']:
                        if value is not None and value != 0:
                            # Find min/max for color coding
                            valid_values = [v for v in values if v is not None and v != 0]
                            if len(valid_values) > 1:
                                min_val = min(valid_values)
                                max_val = max(valid_values)
                                if min_val != max_val:
                                    # Normalize to 0-1
                                    normalized = (value - min_val) / (max_val - min_val)
                                    if prop_key in ['vertices', 'faces', 'surface_area', 'volume']:
                                        # Green for higher values (better detail)
                                        green_intensity = int(220 + normalized * 25)
                                        item.setBackground(QColor(220, green_intensity, 220))
                                    elif prop_key == 'file_size_mb':
                                        # Red for higher values (larger files)
                                        red_intensity = int(220 + normalized * 25)
                                        item.setBackground(QColor(red_intensity, 220, 220))
                    
                    # Special coloring for quality metrics
                    elif prop_key in ['is_watertight', 'is_winding_consistent']:
                        if value:
                            item.setBackground(QColor(230, 245, 230))  # Light green for good
                        else:
                            item.setBackground(QColor(245, 230, 230))  # Light red for issues
                    
                    self.multi_comparison_table.setItem(row, col + 1, item)
            
            # Resize columns to fit content
            self.multi_comparison_table.resizeColumnsToContents()
            
            # Adjust first column to be wider for property names
            self.multi_comparison_table.setColumnWidth(0, 200)
            
            self.progress_bar.setVisible(False)
            self.operation_label.setText(f"Comparison complete - {len(self.comparison_models)} models analyzed")
            
            # Show completion message
            QMessageBox.information(self, "Comparison Complete", 
                f"Successfully compared {len(self.comparison_models)} models.\n"
                f"Check the comparison table for detailed analysis.\n\n"
                f"Properties analyzed: {len(comparison_properties)}")
            
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Comparison failed")
            QMessageBox.critical(self, "Comparison Error", f"Error performing comparison:\n{str(e)}")
    
    def find_best_model(self):
        """Analyze and find the 'best' model based on various criteria.""" 
        if len(self.comparison_models) < 2:
            QMessageBox.warning(self, "Insufficient Models", "Need at least 2 models to find the best.")
            return
        
        results = {}
        
        # 1. Highest Detail
        best_detail = max(self.comparison_models, key=lambda m: m.get('vertices', 0))
        results['highest_detail'] = (best_detail, f"{best_detail.get('vertices', 0):,} vertices")
        
        # 2. Smallest File
        best_small = min(self.comparison_models, key=lambda m: m.get('file_size_mb', float('inf')))
        results['smallest_file'] = (best_small, f"{best_small.get('file_size_mb', 0):.2f} MB")
        
        # 3. Best Quality (Watertight & Consistent)
        quality_models = [m for m in self.comparison_models 
                          if m.get('is_watertight', False) and m.get('is_winding_consistent', False)]
        if quality_models:
            best_quality = max(quality_models, key=lambda m: m.get('vertices', 0))
            results['best_quality'] = (best_quality, "Watertight & Consistent")
        else:
            watertight_models = [m for m in self.comparison_models if m.get('is_watertight', False)]
            if watertight_models:
                best_quality = max(watertight_models, key=lambda m: m.get('vertices', 0))
                results['best_quality'] = (best_quality, "Watertight only")
            else:
                best_quality = max(self.comparison_models, key=lambda m: m.get('vertices', 0))
                results['best_quality'] = (best_quality, "No quality guarantees")
                
        # 4. Most Efficient (Vertices per MB)
        best_efficient = max(self.comparison_models, 
                             key=lambda m: m.get('vertices', 0) / max(m.get('file_size_mb', 1), 0.1))
        ratio = best_efficient.get('vertices', 0) / max(best_efficient.get('file_size_mb', 1), 0.1)
        results['most_efficient'] = (best_efficient, f"{ratio:.0f} vertices/MB")
        
        # Display results
        result_text = "BEST MODEL ANALYSIS\n" + "="*50 + "\n\n"
        
        for criterion, (model, detail) in results.items():
            criterion_name = criterion.replace('_', ' ').title()
            result_text += f"{criterion_name}:\n"
            result_text += f"  Model: {model['name']}\n"
            result_text += f"  Value: {detail}\n"
            result_text += f"  Details: {model['vertices']:,} vertices, {model['file_size_mb']:.2f} MB\n\n"
        
        # Show in a dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Best Model Analysis")
        dialog.setModal(True)
        dialog.resize(600, 500)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(result_text)
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(text_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.exec()
    
    def find_similar_models(self):
        """Find models with similar characteristics."""
        if len(self.comparison_models) < 3:
            QMessageBox.warning(self, "Insufficient Models", "Need at least 3 models to find similarities.")
            return
        
        # Calculate similarity matrix based on vertex count, file size, and surface area
        similarity_groups = []
        
        # Define similarity thresholds
        vertex_threshold = 0.2  # 20% difference
        file_threshold = 0.3    # 30% difference
        area_threshold = 0.25   # 25% difference
        
        for i, model_a in enumerate(self.comparison_models):
            similar_models = [model_a]
            
            for j, model_b in enumerate(self.comparison_models):
                if i >= j:  # Skip self and already compared pairs
                    continue
                
                # Calculate relative differences
                vertex_diff = abs(model_a['vertices'] - model_b['vertices']) / max(model_a['vertices'], model_b['vertices'])
                file_diff = abs(model_a['file_size_mb'] - model_b['file_size_mb']) / max(model_a['file_size_mb'], model_b['file_size_mb'])
                area_diff = abs(model_a['surface_area'] - model_b['surface_area']) / max(model_a['surface_area'], model_b['surface_area'])
                
                # Check if models are similar
                if (vertex_diff < vertex_threshold and 
                    file_diff < file_threshold and 
                    area_diff < area_threshold):
                    similar_models.append(model_b)
            
            if len(similar_models) > 1:
                # Check if this group is already found (reverse order)
                group_names = {model['name'] for model in similar_models}
                already_found = any(group_names == {model['name'] for model in existing_group} 
                                  for existing_group in similarity_groups)
                if not already_found:
                    similarity_groups.append(similar_models)
        
        # Display results
        if not similarity_groups:
            QMessageBox.information(self, "No Similarities", 
                "No similar models found based on current criteria.\n"
                "Models are considered similar if they have <20% vertex difference, "
                "<30% file size difference, and <25% surface area difference.")
            return
        
        result_text = "SIMILAR MODELS ANALYSIS\n" + "="*50 + "\n\n"
        
        for i, group in enumerate(similarity_groups):
            result_text += f"Similar Group {i+1} ({len(group)} models):\n"
            result_text += "-" * 40 + "\n"
            
            for model in group:
                result_text += f"  • {model['name']}\n"
                result_text += f"    {model['vertices']:,} vertices, {model['file_size_mb']:.2f} MB, "
                result_text += f"Area: {model['surface_area']:.2f}\n"
            result_text += "\n"
        
        result_text += f"\nFound {len(similarity_groups)} groups of similar models.\n"
        result_text += "Consider keeping only one representative from each group to reduce redundancy."
        
        # Show in a dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Similar Models Analysis")
        dialog.setModal(True)
        dialog.resize(700, 500)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(result_text)
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(text_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.exec()
    
    def export_multi_comparison_results(self):
        """Export multi-model comparison results.""" 
        if not self.comparison_models or self.multi_comparison_table.rowCount() == 0:
            QMessageBox.warning(self, "No Comparison Data", "No comparison results to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Multi-Model Comparison", 
            f"multi_model_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv);;JSON Files (*.json);;Excel Files (*.xlsx)"
        )
        
        if file_path:
            try:
                # Gather comparison data
                comparison_data = {
                    'export_timestamp': datetime.now().isoformat(),
                    'total_models': len(self.comparison_models),
                    'model_paths': [model['path'] for model in self.comparison_models],
                    'comparison_matrix': []
                }
                
                # Extract table data
                for row in range(self.multi_comparison_table.rowCount()):
                    row_data = {
                        'property': self.multi_comparison_table.item(row, 0).text(),
                        'values': []
                    }
                    
                    for col in range(1, self.multi_comparison_table.columnCount()):
                        cell_item = self.multi_comparison_table.item(row, col)
                        row_data['values'].append(cell_item.text() if cell_item else "")
                    
                    comparison_data['comparison_matrix'].append(row_data)
                
                if file_path.endswith('.csv'):
                    import csv
                    with open(file_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        
                        # Write header
                        header = ['Property'] + [f"Model_{i+1}" for i in range(len(self.comparison_models))]
                        writer.writerow(header)
                        
                        # Write data
                        for row_data in comparison_data['comparison_matrix']:
                            writer.writerow([row_data['property']] + row_data['values'])
                
                elif file_path.endswith('.json'):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(comparison_data, f, indent=2, ensure_ascii=False)
                
                elif file_path.endswith('.xlsx'):
                    try:
                        import pandas as pd
                        
                        # Create DataFrame
                        data_dict = {'Property': [row_data['property'] for row_data in comparison_data['comparison_matrix']]}
                        for i, model in enumerate(self.comparison_models):
                            data_dict[f"Model_{i+1}_{model['name']}"] = [
                                row_data['values'][i] for row_data in comparison_data['comparison_matrix']
                            ]
                        
                        df = pd.DataFrame(data_dict)
                        df.to_excel(file_path, index=False)
                    except ImportError:
                        QMessageBox.warning(self, "Missing Dependency", 
                            "pandas is required for Excel export. Please install it:\npip install pandas openpyxl")
                        return
                
                QMessageBox.information(self, "Export Complete", f"Comparison results exported to:\n{file_path}")
                
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export comparison results:\n{str(e)}")
    
    def export_detailed_comparison_report(self):
        """Export a detailed HTML report with analysis.""" 
        if not self.comparison_models:
            QMessageBox.warning(self, "No Models", "No models to include in detailed report.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Detailed Comparison Report", 
            f"detailed_comparison_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
            "HTML Files (*.html)"
        )
        
        if file_path:
            try:
                # Generate comprehensive HTML report
                html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>RenderFox Multi-Model Comparison Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }}
        .summary {{ background-color: #f8f9fa; padding: 15px; margin: 20px 0; border-radius: 8px; border-left: 4px solid #007bff; }}
        .model-section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #dee2e6; padding: 8px; text-align: left; }}
        th {{ background-color: #f8f9fa; font-weight: bold; }}
        .good {{ background-color: #d4edda; }}
        .warning {{ background-color: #fff3cd; }}
        .error {{ background-color: #f8d7da; }}
        .stats {{ display: flex; flex-wrap: wrap; gap: 15px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #28a745; flex: 1; min-width: 200px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>RenderFox Multi-Model Comparison Report</h1>
        <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p>Total Models Analyzed: {len(self.comparison_models)}</p>
    </div>
    
    <div class="summary">
        <h2>Executive Summary</h2>
        <div class="stats">
            <div class="stat-card">
                <h4>Total Vertices</h4>
                <p>{sum(m['vertices'] for m in self.comparison_models):,}</p>
            </div>
            <div class="stat-card">
                <h4>Total Faces</h4>
                <p>{sum(m['faces'] for m in self.comparison_models):,}</p>
            </div>
            <div class="stat-card">
                <h4>Total File Size</h4>
                <p>{sum(m['file_size_mb'] for m in self.comparison_models):.2f} MB</p>
            </div>
            <div class="stat-card">
                <h4>Watertight Models</h4>
                <p>{sum(1 for m in self.comparison_models if m['is_watertight'])}/{len(self.comparison_models)}</p>
            </div>
        </div>
    </div>
    
    <h2>Detailed Model Information</h2>
"""
                
                # Add individual model sections
                for i, model in enumerate(self.comparison_models):
                    quality_class = "good" if model['is_watertight'] and model['is_winding_consistent'] else "warning" if model['is_watertight'] else "error"
                    
                    html_content += f"""
    <div class="model-section">
        <h3>Model {i+1}: {model['name']}</h3>
        <div class="stats">
            <div class="stat-card">
                <h4>Geometry</h4>
                <p>Vertices: {model['vertices']:,}<br>
                Faces: {model['faces']:,}<br>
                Surface Area: {model['surface_area']:.4f}</p>
            </div>
            <div class="stat-card">
                <h4>Quality</h4>
                <p class="{quality_class}">
                Watertight: {'Yes' if model['is_watertight'] else 'No'}<br>
                Winding: {'Consistent' if model['is_winding_consistent'] else 'Inconsistent'}<br>
                Complexity: {model['complexity']}</p>
            </div>
            <div class="stat-card">
                <h4>Performance</h4>
                <p>File Size: {model['file_size_mb']:.2f} MB<br>
                Memory Est.: {model['estimated_memory_mb']:.2f} MB<br>
                Efficiency: {model['vertices'] / max(model['file_size_mb'], 0.1):.0f} verts/MB</p>
            </div>
        </div>
    </div>
"""
                
                # Add comparison table if available
                if self.multi_comparison_table.rowCount() > 0:
                    html_content += """
    <h2>Detailed Comparison Matrix</h2>
    <table>
        <thead>
            <tr>
                <th>Property</th>
"""
                    
                    for i, model in enumerate(self.comparison_models):
                        html_content += f"<th>Model {i+1}<br>({model['name']})</th>\n"
                    
                    html_content += """
            </tr>
        </thead>
        <tbody>
"""
                    
                    for row in range(self.multi_comparison_table.rowCount()):
                        html_content += "<tr>\n"
                        
                        for col in range(self.multi_comparison_table.columnCount()):
                            cell_item = self.multi_comparison_table.item(row, col)
                            cell_text = cell_item.text() if cell_item else ""
                            
                            if col == 0:
                                html_content += f"<th>{cell_text}</th>\n"
                            else:
                                # Add color coding for specific properties
                                css_class = ""
                                if "Yes" in cell_text:
                                    css_class = "good"
                                elif "No" in cell_text:
                                    css_class = "error"
                                
                                html_content += f'<td class="{css_class}">{cell_text}</td>\n'
                        
                        html_content += "</tr>\n"
                    
                    html_content += """
        </tbody>
    </table>
"""
                
                html_content += """
    <div class="summary">
        <h2>Recommendations</h2>
        <ul>
"""
                
                # Generate recommendations
                highest_detail = max(self.comparison_models, key=lambda m: m['vertices'])
                smallest_file = min(self.comparison_models, key=lambda m: m['file_size_mb'])
                watertight_models = [m for m in self.comparison_models if m['is_watertight']]
                
                html_content += f"<li><strong>Highest Detail:</strong> {highest_detail['name']} ({highest_detail['vertices']:,} vertices)</li>\n"
                html_content += f"<li><strong>Most Compact:</strong> {smallest_file['name']} ({smallest_file['file_size_mb']:.2f} MB)</li>\n"
                
                if watertight_models:
                    best_quality = max(watertight_models, key=lambda m: m['vertices'])
                    html_content += f"<li><strong>Best Quality:</strong> {best_quality['name']} (watertight with {best_quality['vertices']:,} vertices)</li>\n"
                else:
                    html_content += "<li><strong>Quality Issue:</strong> No watertight models found - consider mesh repair</li>\n"
                
                html_content += """
        </ul>
    </div>
    
    <footer style="margin-top: 40px; padding: 20px; background-color: #f8f9fa; border-radius: 8px; text-align: center; color: #6c757d;">
        <p>Generated by RenderFox - Advanced 3D Model Analysis Tool</p>
    </footer>
</body>
</html>
"""
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                QMessageBox.information(self, "Report Generated", 
                    f"Detailed comparison report generated successfully!\n\n{file_path}\n\n"
                    "The report includes:\n"
                    "• Executive summary with key statistics\n"
                    "• Individual model analysis\n"
                    "• Detailed comparison matrix\n"
                    "• Quality assessments and recommendations")
                
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to generate detailed report:\n{str(e)}")
    
    # Remove the old 2-model comparison methods
    def browse_comparison_model(self, model_letter):
        """Legacy method - redirects to new multi-model system."""
        QMessageBox.information(self, "Upgraded Comparison", 
            "The comparison system has been upgraded to support multiple models!\n\n"
            "Use the 'Add Model' section above to add models for comparison.")
    
    def use_current_model(self, model_letter):
        """Legacy method - redirects to new multi-model system."""
        self.add_current_to_multi_comparison()
    
    def compare_models(self):
        """Legacy method - redirects to new multi-model system."""
        self.compare_all_models()
    
    def clear_comparison_table(self):
        """Clear the comparison table."""
        self.clear_all_comparison_models()

    def setup_connections(self):
        """Setup signal connections."""
        # Browser controls
        self.load_model_btn.clicked.connect(self.load_model)
        self.load_folder_btn.clicked.connect(self.load_folder)
        self.refresh_btn.clicked.connect(self.refresh_library)
        self.remove_model_btn.clicked.connect(self.remove_selected_model)
        
        # Model tree selection
        self.model_tree.itemClicked.connect(self.on_model_selected)
        self.model_tree.itemDoubleClicked.connect(self.on_model_double_clicked)
        
        # Analysis tools
        self.analyze_btn.clicked.connect(self.analyze_selected_model)
        self.batch_analyze_btn.clicked.connect(self.batch_analyze_models)
        self.export_report_btn.clicked.connect(self.export_analysis_report)
        
        # Conversion tools
        self.convert_btn.clicked.connect(self.convert_selected_model)
        self.batch_convert_btn.clicked.connect(self.batch_convert_models)
        
        # Optimization tools
        self.simplify_btn.clicked.connect(self.simplify_selected_model)
        self.repair_btn.clicked.connect(self.repair_selected_model)
        self.optimize_btn.clicked.connect(self.optimize_selected_model)
        
        # Model viewer signal
        self.model_viewer.model_loaded.connect(self.update_model_info)
    
    def run_detailed_analysis(self):
        """Run detailed analysis on current model."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to analyze.")
            return
        
        self.run_analysis_on_file(self.current_model_path)
    
    def run_analysis_on_file(self, file_path):
        """Run detailed analysis on a specific file."""
        try:
            mesh_obj = trimesh.load(file_path)
            mesh = _as_trimesh(mesh_obj)
            if mesh is None:
                raise ValueError("Could not read mesh from file (scene with no geometry or unsupported format)")
            
            analysis_type = self.analysis_type.currentText()
            if analysis_type == "Quality Check":
                results = self.perform_quality_check(mesh)
            elif analysis_type == "Mesh Validation":
                results = self.perform_mesh_validation(mesh)
            elif analysis_type == "Performance Analysis":
                results = self.perform_performance_analysis(mesh)
            elif analysis_type == "Topology Analysis":
                results = self.perform_topology_analysis(mesh)
            elif analysis_type == "Material Analysis":
                results = self.perform_material_analysis(file_path)
            else:
                results = "Analysis type not implemented yet."
            
            self.analysis_results.setPlainText(results)
        except Exception as e:
            self.analysis_results.setPlainText(f"Error during analysis: {str(e)}")
    
    def perform_quality_check(self, mesh):
        """Perform quality check analysis."""
        results = []
        results.append("=== MESH QUALITY CHECK ===\n")
        
        # Basic metrics
        results.append(f"Vertices: {len(mesh.vertices):,}")
        results.append(f"Faces: {len(mesh.faces):,}")
        results.append(f"Edges: {len(mesh.edges):,}")
        
        # Quality metrics
        results.append(f"\nQuality Metrics:")
        results.append(f"Watertight: {'✓' if mesh.is_watertight else '✗'}")
        results.append(f"Winding Consistent: {'✓' if mesh.is_winding_consistent else '✗'}")
        
        # Face quality
        if hasattr(mesh, 'face_angles'):
            face_angles = mesh.face_angles
            min_angle = np.rad2deg(np.min(face_angles))
            max_angle = np.rad2deg(np.max(face_angles))
            avg_angle = np.rad2deg(np.mean(face_angles))
            
            results.append(f"\nFace Angles:")
            results.append(f"Minimum: {min_angle:.2f}°")
            results.append(f"Maximum: {max_angle:.2f}°")
            results.append(f"Average: {avg_angle:.2f}°")
            
            # Check for degenerate faces
            degenerate_count = np.sum(face_angles < np.deg2rad(1))
            results.append(f"Degenerate faces (<1°): {degenerate_count}")
        
        return "\n".join(results)
    
    def perform_mesh_validation(self, mesh):
        """Perform mesh validation analysis."""
        results = []
        results.append("=== MESH VALIDATION ===\n")
        
        # Topology validation
        results.append("Topology Validation:")
        results.append(f"Is Volume: {'✓' if mesh.is_volume else '✗'}")
        results.append(f"Is Watertight: {'✓' if mesh.is_watertight else '✗'}")
        results.append(f"Winding Consistent: {'✓' if mesh.is_winding_consistent else '✗'}")
        
        # Geometry validation
        results.append(f"\nGeometry Validation:")
        results.append(f"Surface Area: {mesh.area:.4f}")
        results.append(f"Volume: {mesh.volume:.4f}" if mesh.is_volume else "Volume: N/A (not watertight)")
        
        # Check for issues
        results.append(f"\nPotential Issues:")
        
        # Duplicate vertices
        if hasattr(mesh, 'remove_duplicate_faces'):
            original_faces = len(mesh.faces)
            test_mesh = mesh.copy()
            test_mesh.remove_duplicate_faces()
            duplicate_faces = original_faces - len(test_mesh.faces)
            results.append(f"Duplicate faces: {duplicate_faces}")
        
        return "\n".join(results)
    
    def perform_performance_analysis(self, mesh):
        """Perform performance analysis."""
        results = []
        results.append("=== PERFORMANCE ANALYSIS ===\n")
        
        vertex_count = len(mesh.vertices)
        face_count = len(mesh.faces)
        
        # Performance categories
        if vertex_count < 1000:
            perf_category = "Low Detail"
        elif vertex_count < 10000:
            perf_category = "Medium Detail"
        elif vertex_count < 100000:
            perf_category = "High Detail"
        else:
            perf_category = "Very High Detail"
        
        results.append(f"Performance Category: {perf_category}")
        results.append(f"Vertex Count: {vertex_count:,}")
        results.append(f"Face Count: {face_count:,}")
        
        # Memory estimation
        vertex_memory = vertex_count * 3 * 4  # 3 floats per vertex
        face_memory = face_count * 3 * 4      # 3 ints per face
        total_memory_kb = (vertex_memory + face_memory) / 1024
        
        results.append(f"\nEstimated Memory Usage:")
        results.append(f"Vertices: {vertex_memory / 1024:.1f} KB")
        results.append(f"Faces: {face_memory / 1024:.1f} KB")
        results.append(f"Total: {total_memory_kb:.1f} KB")
        
        # LOD recommendations
        results.append(f"\nLOD Recommendations:")
        if vertex_count > 50000:
            results.append("• Consider creating lower detail LODs")
            results.append("• Recommended LOD levels: 3-4")
            results.append(f"• LOD1: ~{vertex_count // 2:,} vertices")
            results.append(f"• LOD2: ~{vertex_count // 4:,} vertices")
            results.append(f"• LOD3: ~{vertex_count // 8:,} vertices")
        else:
            results.append("• Model is suitable for direct use")
            results.append("• LODs may not be necessary")
        
        return "\n".join(results)
    
    def perform_topology_analysis(self, mesh):
        """Perform topology analysis."""
        results = []
        results.append("=== TOPOLOGY ANALYSIS ===\n")
        
        results.append(f"Euler Characteristic: V - E + F = {len(mesh.vertices)} - {len(mesh.edges)} + {len(mesh.faces)} = {len(mesh.vertices) - len(mesh.edges) + len(mesh.faces)}")
        
        # Genus calculation for closed surfaces
        if mesh.is_watertight:
            euler_char = len(mesh.vertices) - len(mesh.edges) + len(mesh.faces)
            genus = (2 - euler_char) // 2
            results.append(f"Genus: {genus}")
            
            if genus == 0:
                results.append("Topological equivalent to: Sphere")
            elif genus == 1:
                results.append("Topological equivalent to: Torus/Donut")
            else:
                results.append(f"Topological equivalent to: {genus}-torus")
        else:
            results.append("Genus: Cannot calculate (not watertight)")
        
        return "\n".join(results)

    def perform_material_analysis(self, file_path: str) -> str:
        """Analyze materials, textures, vertex colors and UVs for the current model."""
        lines = ["=== MATERIAL ANALYSIS ===\n"]
        try:
            scene_or_mesh = trimesh.load(file_path, process=False)
        except Exception as e:
            return f"Material analysis failed to load file: {e}"
        
        total_geoms = 0
        texture_geoms = 0
        vertex_color_geoms = 0
        uv_geoms = 0
        material_names = []
        texture_paths = []
        tex_sizes = []
        
        def inspect_mesh(name, m: trimesh.Trimesh):
            nonlocal total_geoms, texture_geoms, vertex_color_geoms, uv_geoms
            total_geoms += 1
            vis = getattr(m, 'visual', None)
            if vis is None:
                return
            kind = getattr(vis, 'kind', None)
            if kind == 'texture':
                texture_geoms += 1
            if getattr(vis, 'uv', None) is not None:
                uv_geoms += 1
            # Vertex colors
            try:
                vc = None
                if hasattr(vis, 'vertex_colors') and vis.vertex_colors is not None and len(vis.vertex_colors) == len(m.vertices):
                    vc = vis.vertex_colors
                if vc is not None:
                    vertex_color_geoms += 1
            except Exception:
                pass
            # Material info
            mat = getattr(vis, 'material', None)
            if mat is not None:
                mat_name = getattr(mat, 'name', None) or getattr(mat, 'material_name', None)
                if mat_name:
                    material_names.append(str(mat_name))
                # texture path if available
                img = getattr(mat, 'image', None)
                if img is not None:
                    try:
                        arr = np.array(img)
                        tex_sizes.append((arr.shape[1], arr.shape[0]))
                    except Exception:
                        pass
                tex_path = None
                for key in ('image_path', 'diffuseTexture', 'baseColorTexture', 'albedoTexture', 'colorTexture'):
                    if hasattr(mat, key):
                        val = getattr(mat, key)
                        if isinstance(val, str):
                            tex_path = val
                            break
                if tex_path:
                    texture_paths.append(tex_path)
        
        if isinstance(scene_or_mesh, trimesh.Scene):
            geoms = getattr(scene_or_mesh, 'geometry', {}) or {}
            for n, g in geoms.items():
                if isinstance(g, trimesh.Trimesh):
                    inspect_mesh(n, g)
        elif isinstance(scene_or_mesh, trimesh.Trimesh):
            inspect_mesh('mesh', scene_or_mesh)
        else:
            lines.append("Unsupported scene type for material analysis")
            return "\n".join(lines)
        
        lines.append(f"Geometry objects: {total_geoms}")
        lines.append(f"With textures: {texture_geoms}")
        lines.append(f"With vertex colors: {vertex_color_geoms}")
        lines.append(f"With UVs: {uv_geoms}")
        if material_names:
            unique_mats = sorted(set(material_names))
            lines.append(f"Materials: {', '.join(unique_mats)}")
        if texture_paths:
            uniq_tex = sorted(set(texture_paths))
            lines.append("Texture files (as referenced):")
            for p in uniq_tex[:20]:
                lines.append(f" • {p}")
            if len(uniq_tex) > 20:
                lines.append(f" ... and {len(uniq_tex)-20} more")
        if tex_sizes:
            try:
                avg_w = int(np.mean([w for (w, h) in tex_sizes]))
                avg_h = int(np.mean([h for (w, h) in tex_sizes]))
                lines.append(f"Average texture size: {avg_w}x{avg_h}")
            except Exception:
                pass
        lines.append("\nNotes:")
        lines.append(" • Trimesh collapses scenes to single mesh in some loaders; per-material details may be limited.")
        lines.append(" • For full material fidelity, consider converting to GLB/GLTF and previewing textures in the 3D viewer.")
        return "\n".join(lines)
    
    def load_model(self):
        """Load a 3D model from file dialog."""
        # ...existing code...
    
    def load_model_file(self, file_path):
        """Load a model file directly (called from other tabs)."""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Error", f"File not found:\n{file_path}")
            return
        
        try:
            # Load using the model viewer
            if hasattr(self, 'model_viewer') and self.model_viewer:
                self.model_viewer.load_model(file_path)
                
                # Update info display
                file_name = os.path.basename(file_path)
                self.update_model_info(file_path)
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"Model loaded successfully!\n\nFile: {file_name}"
                )
            else:
                QMessageBox.warning(self, "Error", "Model viewer not initialized!")
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load model:\n{str(e)}"
            )
    
    def update_model_info(self, file_path):
        """Update model information display."""
        try:
            import trimesh
            mesh = trimesh.load(file_path)
            
            info = f"""
Model Information:
━━━━━━━━━━━━━━━━━━━━━━━━
File: {os.path.basename(file_path)}
Vertices: {len(mesh.vertices):,}
Faces: {len(mesh.faces):,}
Bounds: {mesh.bounds}
Volume: {mesh.volume:.2f}
Is Watertight: {mesh.is_watertight}
            """
            
            if hasattr(self, 'model_info_text'):
                self.model_info_text.setPlainText(info.strip())
                
        except Exception as e:
            print(f"Error updating model info: {e}")
    
    def load_model(self, file_path=None):
        """Load a single model file."""
        # Handle signal argument (bool)
        if isinstance(file_path, bool):
            file_path = None
            
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Load Model", "", 
                "3D Models (*.obj *.stl *.ply *.glb *.gltf *.fbx *.dae *.x3d);;All Files (*)"
            )
        
        if file_path:
            self.load_model_in_viewer(file_path)
            self.add_model_to_library(file_path)

    def load_folder(self):
        """Load all models from a selected folder."""
        folder_path = QFileDialog.getExistingDirectory(self, "Load Models from Folder")
        
        if folder_path:
            # Find all supported model files
            supported_extensions = ['.obj', '.stl', '.ply', '.glb', '.gltf', '.fbx', '.dae', '.x3d']
            model_files = []
            
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in supported_extensions):
                        model_files.append(os.path.join(root, file))
            
            if model_files:
                # Add all found models to library
                for model_file in model_files:
                    self.add_model_to_library(model_file)
                
                QMessageBox.information(self, "Folder Loaded", 
                                      f"Loaded {len(model_files)} model files from folder.")
            else:
                QMessageBox.warning(self, "No Models Found", 
                                  "No supported 3D model files found in the selected folder.")
    
    def add_model_to_library(self, file_path):
        """Add a model to the library."""
        if file_path not in [item['path'] for item in self.model_library]:
            model_info = {
                'path': file_path,
                'name': os.path.basename(file_path),
                'size': os.path.getsize(file_path),
                'type': os.path.splitext(file_path)[1][1:].upper(),
                'added': datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            self.model_library.append(model_info)
            self.update_model_tree()
    
    def update_model_tree(self):
        """Update the model tree display."""
        self.model_tree.clear()
        
        for model_info in self.model_library:
            item = QTreeWidgetItem()
            item.setText(0, model_info['name'])
            item.setText(1, model_info['type'])
            item.setText(2, f"{model_info['size'] / (1024*1024):.1f} MB")
            item.setData(0, Qt.ItemDataRole.UserRole, model_info['path'])
            self.model_tree.addTopLevelItem(item)
        
        # Adjust column widths
        for i in range(3):
            self.model_tree.resizeColumnToContents(i)
    
    def on_model_selected(self, item):
        """Handle model selection in tree."""
        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        print(f"DEBUG: on_model_selected: {file_path}", flush=True)
        if file_path:
            self.current_model_path = file_path
            # Always load the selected model, freeing any previously loaded content first
            self.load_model_in_viewer(file_path)
            self.update_model_info_labels(file_path)
            
            # Update Painting Tab if it's the current tab
            if hasattr(self, 'painting_tab') and self.detail_tabs.currentWidget() == self.painting_tab:
                print(f"DEBUG: Updating Painting Tab with selected model: {file_path}")
                self.painting_tab.set_model(file_path)
    
    def on_model_double_clicked(self, item):
        """Handle model double-click in tree."""
        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        if file_path:
            # Double-click also loads the model (viewer is cleared within load_model_in_viewer)
            self.load_model_in_viewer(file_path)
    
    def load_model_in_viewer(self, file_path):
        """Load a model in the 3D viewer."""
        # Clear any existing model first
        self.model_viewer.clear()
        
        self.current_model_path = file_path
        self.operation_label.setText(f"Loading: {os.path.basename(file_path)}...")
        
        success = self.model_viewer.load_model(file_path)
        
        if success:
            self.operation_label.setText(f"Loaded: {os.path.basename(file_path)}")
            try:
                self.quality_analyzer_tab.set_model(file_path)
                self.version_control_tab.load_model(file_path)
                if hasattr(self, 'painting_tab'):
                    self.painting_tab.set_model(file_path)
            except Exception as e:
                print(f"Error updating features: {e}")
        else:
            self.operation_label.setText("Failed to load model")
            QMessageBox.warning(self, "Load Error", 
                              f"Failed to load model: {os.path.basename(file_path)}")
    
    def update_model_info(self, model_info):
        """Update model information display."""
        if self.current_model_path:
            self.update_model_info_labels(self.current_model_path, model_info)
    
    def update_model_info_labels(self, file_path, model_info=None):
        """Update the information labels."""
        self.file_name_label.setText(os.path.basename(file_path))
        self.file_size_label.setText(f"{os.path.getsize(file_path) / (1024*1024):.2f} MB")
        self.file_format_label.setText(os.path.splitext(file_path)[1][1:].upper())
        
        if model_info:
            self.vertices_label.setText(f"{model_info.get('vertices', 0):,}")
            self.faces_label.setText(f"{model_info.get('faces', 0):,}")
            self.edges_label.setText(f"{model_info.get('edges', 0):,}")
            self.surface_area_label.setText(f"{model_info.get('surface_area', 0):.2f}")
            self.volume_label.setText(f"{model_info.get('volume', 0):.2f}")
            self.is_watertight_label.setText("Yes" if model_info.get('is_watertight', False) else "No")
            
            bounds = model_info.get('bounds', [[0,0,0], [0,0,0]])
            bounds_text = f"X: {bounds[0][0]:.2f} to {bounds[1][0]:.2f}, " \
                         f"Y: {bounds[0][1]:.2f} to {bounds[1][1]:.2f}, " \
                         f"Z: {bounds[0][2]:.2f} to {bounds[1][2]:.2f}"
            self.bounds_label.setText(bounds_text)
            self.uv_label.setText('Yes' if model_info.get('has_uvs') else 'No')
            self.vcolors_label.setText('Yes' if model_info.get('has_vertex_colors') else 'No')
            self.materials_label.setText(str(model_info.get('material_count', 0)))
            
            tex_data = model_info.get('texture_data', {})
            if hasattr(self, 'tex_albedo_label'):
                self.tex_albedo_label.setText(str(tex_data.get('Albedo', 0)))
                self.tex_normal_label.setText(str(tex_data.get('Normal', 0)))
                self.tex_specular_label.setText(str(tex_data.get('Specular/Metallic', 0)))
                self.tex_occlusion_label.setText(str(tex_data.get('Occlusion', 0)))
                self.tex_emissive_label.setText(str(tex_data.get('Emissive', 0)))
            
            tex_data = model_info.get('texture_data', {})
            self.tex_albedo_label.setText(str(tex_data.get('Albedo', 0)))
            self.tex_normal_label.setText(str(tex_data.get('Normal', 0)))
            self.tex_specular_label.setText(str(tex_data.get('Specular/Metallic', 0)))
            self.tex_occlusion_label.setText(str(tex_data.get('Occlusion', 0)))
            self.tex_emissive_label.setText(str(tex_data.get('Emissive', 0)))
        else:
            self.vertices_label.setText("-")
            self.faces_label.setText("-")
            self.edges_label.setText("-")
            self.surface_area_label.setText("-")
            self.volume_label.setText("-")
            self.is_watertight_label.setText("-")
            self.bounds_label.setText("-")
            self.uv_label.setText("-")
            self.vcolors_label.setText("-")
            self.materials_label.setText("-")
        
        if hasattr(self, 'tex_albedo_label'):
            self.tex_albedo_label.setText("-")
            self.tex_normal_label.setText("-")
            self.tex_specular_label.setText("-")
            self.tex_occlusion_label.setText("-")
            self.tex_emissive_label.setText("-")
    
    def analyze_selected_model(self):
        """Analyze the currently selected model."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to analyze.")
            return
        
        self.operation_label.setText("Analyzing model...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Start analysis in thread
        self.analysis_worker = ModelAnalysisWorker([self.current_model_path])
        self.analysis_worker.analysis_complete.connect(self.on_analysis_complete)
        self.analysis_worker.error_occurred.connect(self.on_analysis_error)
        self.analysis_worker.start()
    
    def batch_analyze_models(self):
        """Analyze all models in the library."""
        if not self.model_library:
            QMessageBox.warning(self, "No Models", "No models loaded in library.")
            return
        
        file_paths = [item['path'] for item in self.model_library]
        
        self.operation_label.setText("Running batch analysis...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        
        # Start batch analysis
        self.analysis_worker = ModelAnalysisWorker(file_paths)
        self.analysis_worker.analysis_complete.connect(self.on_batch_analysis_complete)
        self.analysis_worker.progress_updated.connect(self.progress_bar.setValue)
        self.analysis_worker.error_occurred.connect(self.on_analysis_error)
        self.analysis_worker.start()
    
    def on_analysis_complete(self, results):
        """Handle analysis completion."""
        self.progress_bar.setVisible(False)
        self.operation_label.setText("Analysis complete")
        
        if results['results']:
            analysis = results['results'][0]
            self.populate_analysis_table(analysis)
    
    def on_batch_analysis_complete(self, results):
        """Handle batch analysis completion."""
        self.progress_bar.setVisible(False)
        self.operation_label.setText(f"Batch analysis complete - {results['total_analyzed']} models")
        
        # Show summary dialog
        QMessageBox.information(self, "Batch Analysis Complete",
                              f"Successfully analyzed {results['total_analyzed']} models.\n"
                              "Results are available in the Analysis tab.")
    
    def on_analysis_error(self, error_message):
        """Handle analysis errors."""
        self.progress_bar.setVisible(False)
        self.operation_label.setText("Analysis failed")
        QMessageBox.warning(self, "Analysis Error", error_message)
    
    def populate_analysis_table(self, analysis):
        """Populate the analysis table with results."""
        self.analysis_table.setRowCount(0)
        
        properties = [
            ("Vertices", f"{analysis['vertices']:,}", "✓"),
            ("Faces", f"{analysis['faces']:,}", "✓"),
            ("Edges", f"{analysis['edges']:,}", "✓"),
            ("Surface Area", f"{analysis['surface_area']:.2f}", "✓"),
            ("Volume", f"{analysis['volume']:.2f}", "✓"),
            ("Watertight", "Yes" if analysis['is_watertight'] else "No", 
             "✓" if analysis['is_watertight'] else "⚠"),
            ("Winding Consistent", "Yes" if analysis['is_winding_consistent'] else "No",
             "✓" if analysis['is_winding_consistent'] else "⚠"),
        ]
        
        for i, (prop, value, status) in enumerate(properties):
            self.analysis_table.insertRow(i)
            self.analysis_table.setItem(i, 0, QTableWidgetItem(prop))
            self.analysis_table.setItem(i, 1, QTableWidgetItem(value))
            self.analysis_table.setItem(i, 2, QTableWidgetItem(status))
    
    def convert_selected_model(self):
        """Convert the selected model format."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to convert.")
            return
        
        converter = ModelFormatConverter(self, [self.current_model_path])
        converter.exec()
    
    def batch_convert_models(self):
        """Batch convert multiple models."""
        if not self.model_library:
            QMessageBox.warning(self, "No Models", "No models loaded in library.")
            return
        
        file_paths = [item['path'] for item in self.model_library]
        converter = ModelFormatConverter(self, file_paths)
        converter.exec()
    
    def simplify_selected_model(self):
        """Simplify the selected model mesh."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to simplify.")
            return
        
        # Get simplification parameters from user
        face_count, ok = QInputDialog.getInt(
            self, "Mesh Simplification", 
            "Target number of faces:", 
            min=100, max=1000000, value=5000
        )
        
        if not ok:
            return
        
        try:
            self.operation_label.setText("Simplifying mesh...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            
            # Load the mesh
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            
            if mesh is None:
                raise Exception("Could not load mesh")
            
            original_faces = len(mesh.faces)
            
            # Simplify using trimesh
            simplified = mesh.simplify_quadric_decimation(face_count)
            
            if simplified is None or len(simplified.faces) >= original_faces:
                QMessageBox.warning(self, "Simplification Failed", "Could not simplify the mesh.")
                return
            
            # Save simplified mesh
            base_name = os.path.splitext(self.current_model_path)[0]
            output_path = f"{base_name}_simplified.obj"
            
            simplified.export(output_path)
            
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Simplification complete")
            
            reduction = ((original_faces - len(simplified.faces)) / original_faces) * 100
            
            QMessageBox.information(
                self, "Simplification Complete", 
                f"Simplified from {original_faces:,} to {len(simplified.faces):,} faces "
                f"({reduction:.1f}% reduction)\n\nSaved as: {output_path}"
            )
            
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Simplification failed")
            QMessageBox.warning(self, "Simplification Error", f"Failed to simplify mesh: {str(e)}")
    
    def repair_selected_model(self):
        """Repair the selected model mesh."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to repair.")
            return
        
        try:
            self.operation_label.setText("Repairing mesh...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            
            # Load the mesh
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            
            if mesh is None:
                raise Exception("Could not load mesh")
            
            original_watertight = mesh.is_watertight
            original_faces = len(mesh.faces)
            original_vertices = len(mesh.vertices)
            
            # Apply various repair operations
            repairs_applied = []
            
            # Remove duplicate vertices
            mesh.remove_duplicate_faces()
            if len(mesh.vertices) < original_vertices:
                repairs_applied.append(f"Removed {original_vertices - len(mesh.vertices)} duplicate vertices")
            
            # Remove degenerate faces
            initial_face_count = len(mesh.faces)
            mesh.remove_degenerate_faces()
            if len(mesh.faces) < initial_face_count:
                repairs_applied.append(f"Removed {initial_face_count - len(mesh.faces)} degenerate faces")
            
            # Fill holes (if possible)
            if not mesh.is_watertight:
                try:
                    mesh.fill_holes()
                    if mesh.is_watertight:
                        repairs_applied.append("Filled holes to make mesh watertight")
                except:
                    pass
            
            # Fix winding
            if not mesh.is_winding_consistent:
                try:
                    mesh.fix_normals()
                    if mesh.is_winding_consistent:
                        repairs_applied.append("Fixed face winding")
                except:
                    pass
            
            # Save repaired mesh
            base_name = os.path.splitext(self.current_model_path)[0]
            output_path = f"{base_name}_repaired.obj"
            
            mesh.export(output_path)
            
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Repair complete")
            
            # Show results
            result_msg = f"Mesh repair completed!\n\n"
            result_msg += f"Original: {original_faces:,} faces, Watertight: {original_watertight}\n"
            result_msg += f"Repaired: {len(mesh.faces):,} faces, Watertight: {mesh.is_watertight}\n\n"
            
            if repairs_applied:
                result_msg += "Repairs applied:\n" + "\n".join(f"• {repair}" for repair in repairs_applied)
            else:
                result_msg += "No repairs were needed."
            
            result_msg += f"\n\nSaved as: {output_path}"
            
            QMessageBox.information(self, "Repair Complete", result_msg)
            
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Repair failed")
            QMessageBox.warning(self, "Repair Error", f"Failed to repair mesh: {str(e)}")
    
    def optimize_selected_model(self):
        """Optimize the selected model for better performance."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to optimize.")
            return
        
        try:
            self.operation_label.setText("Optimizing mesh...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            
            # Load the mesh
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            
            if mesh is None:
                raise Exception("Could not load mesh")
            
            original_vertices = len(mesh.vertices)
            original_faces = len(mesh.faces)
            optimizations = []
            
            # Remove duplicate vertices and merge close ones
            mesh.remove_duplicate_faces()
            mesh.merge_vertices()
            if len(mesh.vertices) < original_vertices:
                optimizations.append(f"Merged {original_vertices - len(mesh.vertices)} duplicate/close vertices")
            
            # Remove unreferenced vertices
            mesh.remove_unreferenced_vertices()
            
            # Optimize vertex order for better cache performance
            # This is a simple reordering - more sophisticated algorithms exist
            if hasattr(mesh, 'permute_vertices'):
                try:
                    mesh.permute_vertices()
                    optimizations.append("Reordered vertices for better cache performance")
                except:
                    pass
            
            # Update normals
            mesh.vertex_normals
            optimizations.append("Recalculated vertex normals")
            
            # Convex hull optimization option
            reply = QMessageBox.question(
                self, "Convex Hull", 
                "Create convex hull version? (Simpler but less detailed)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            convex_hull_mesh = None
            if reply == QMessageBox.StandardButton.Yes:
                convex_hull_mesh = mesh.convex_hull
                optimizations.append("Created convex hull version")
            
            # Save optimized mesh
            base_name = os.path.splitext(self.current_model_path)[0]
            output_path = f"{base_name}_optimized.obj"
            
            mesh.export(output_path)
            
            # Save convex hull if created
            if convex_hull_mesh is not None:
                hull_path = f"{base_name}_convex_hull.obj"
                convex_hull_mesh.export(hull_path)
                optimizations.append(f"Saved convex hull as: {hull_path}")
            
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Optimization complete")
            
            # Show results
            result_msg = f"Mesh optimization completed!\n\n"
            result_msg += f"Original: {original_vertices:,} vertices, {original_faces:,} faces\n"
            result_msg += f"Optimized: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces\n\n"
            
            if optimizations:
                result_msg += "Optimizations applied:\n" + "\n".join(f"• {opt}" for opt in optimizations)
            
            result_msg += f"\n\nSaved as: {output_path}"
            
            QMessageBox.information(self, "Optimization Complete", result_msg)
            
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.operation_label.setText("Optimization failed")
            QMessageBox.warning(self, "Optimization Error", f"Failed to optimize mesh: {str(e)}")
    
    def export_current_analysis(self):
        """Export current analysis results."""
        if self.analysis_table.rowCount() == 0:
            QMessageBox.warning(self, "No Analysis", "No analysis results to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Analysis", "", "JSON Files (*.json);;CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                data = []
                for row in range(self.analysis_table.rowCount()):
                    property_name = self.analysis_table.item(row, 0).text()
                    value = self.analysis_table.item(row, 1).text()
                    status = self.analysis_table.item(row, 2).text()
                    data.append({
                        'property': property_name,
                        'value': value,
                        'status': status
                    })
                
                if file_path.endswith('.json'):
                    with open(file_path, 'w') as f:
                        json.dump({
                            'model': os.path.basename(self.current_model_path) if self.current_model_path else 'Unknown',
                            'analysis_date': datetime.now().isoformat(),
                            'results': data
                        }, f, indent=2)
                else:  # CSV
                    import csv
                    with open(file_path, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=['property', 'value', 'status'])
                        writer.writeheader()
                        writer.writerows(data)
                
                QMessageBox.information(self, "Export Complete", f"Analysis results exported to {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export: {str(e)}")
    
    def export_analysis_report(self):
        """Export comprehensive analysis report."""
        if not self.model_library:
            QMessageBox.warning(self, "No Models", "No models to include in report.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", "", "HTML Files (*.html);;JSON Files (*.json)"
        )
        
        if file_path:
            try:
                # Analyze all models first
                all_analyses = []
                for model_info in self.model_library:
                    try:
                        mesh_obj = trimesh.load(model_info['path'])
                        mesh = _as_trimesh(mesh_obj)
                        if mesh is not None:
                            analysis = {
                                'file_name': model_info['name'],
                                'file_path': model_info['path'],
                                'file_size_mb': model_info['size'] / (1024 * 1024),
                                'vertices': len(mesh.vertices),
                                'faces': len(mesh.faces),
                                'edges': len(mesh.edges),
                                'surface_area': float(mesh.area),
                                'volume': float(mesh.volume) if mesh.is_volume else 0.0,
                                'is_watertight': mesh.is_watertight,
                                'is_winding_consistent': mesh.is_winding_consistent,
                                'bounds': mesh.bounds.tolist(),
                                'center': mesh.center_mass.tolist()
                            }
                            all_analyses.append(analysis)
                    except Exception as e:
                        print(f"Error analyzing {model_info['path']}: {e}")
                
                if file_path.endswith('.html'):
                    # Generate HTML report
                    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>RenderFox Model Analysis Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .summary {{ background-color: #e8f4f8; padding: 15px; margin: 20px 0; }}
        .model-section {{ margin: 20px 0; padding: 15px; border: 1px solid #ccc; }}
    </style>
</head>
<body>
    <h1>RenderFox Model Analysis Report</h1>
    <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="summary">
        <h2>Summary</h2>
        <p>Total Models Analyzed: {len(all_analyses)}</p>
        <p>Total Vertices: {sum(a['vertices'] for a in all_analyses):,}</p>
        <p>Total Faces: {sum(a['faces'] for a in all_analyses):,}</p>
        <p>Watertight Models: {sum(1 for a in all_analyses if a['is_watertight'])}</p>
    </div>
    
    <h2>Detailed Analysis</h2>
    <table>
        <tr>
            <th>Model</th>
            <th>Vertices</th>
            <th>Faces</th>
            <th>Surface Area</th>
            <th>Volume</th>
            <th>Watertight</th>
            <th>File Size (MB)</th>
        </tr>
"""
                    for analysis in all_analyses:
                        html_content += f"""
        <tr>
            <td>{analysis['file_name']}</td>
            <td>{analysis['vertices']:,}</td>
            <td>{analysis['faces']:,}</td>
            <td>{analysis['surface_area']:.2f}</td>
            <td>{analysis['volume']:.2f}</td>
            <td>{'Yes' if analysis['is_watertight'] else 'No'}</td>
            <td>{analysis['file_size_mb']:.2f}</td>
        </tr>
"""
                    html_content += """
    </table>
</body>
</html>
"""
                    with open(file_path, 'w') as f:
                        f.write(html_content)
                else:
                    # JSON export
                    report_data = {
                        'report_date': datetime.now().isoformat(),
                        'total_models': len(all_analyses),
                        'summary': {
                            'total_vertices': sum(a['vertices'] for a in all_analyses),
                            'total_faces': sum(a['faces'] for a in all_analyses),
                            'watertight_count': sum(1 for a in all_analyses if a['is_watertight'])
                        },
                        'models': all_analyses
                    }
                    with open(file_path, 'w') as f:
                        json.dump(report_data, f, indent=2)
                
                QMessageBox.information(self, "Export Complete", f"Analysis report exported to {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export report: {str(e)}")
    
    def add_current_to_comparison(self):
        """Add current model to comparison table."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to add to comparison.")
            return
        
        # Check if model is already in comparison
        for row in range(self.comparison_table.rowCount()):
            if self.comparison_table.item(row, 0).text() == os.path.basename(self.current_model_path):
                QMessageBox.information(self, "Already Added", "This model is already in the comparison table.")
                return
        
        try:
            # Load and analyze the model
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            if mesh is None:
                QMessageBox.warning(self, "Error", "Could not analyze the current model.")
                return
            
            # Add row to comparison table
            row_count = self.comparison_table.rowCount()
            self.comparison_table.insertRow(row_count)
            
            # Fill in the data
            self.comparison_table.setItem(row_count, 0, QTableWidgetItem(os.path.basename(self.current_model_path)))
            self.comparison_table.setItem(row_count, 1, QTableWidgetItem(f"{len(mesh.vertices):,}"))
            self.comparison_table.setItem(row_count, 2, QTableWidgetItem(f"{len(mesh.faces):,}"))
            self.comparison_table.setItem(row_count, 3, QTableWidgetItem(f"{os.path.getsize(self.current_model_path) / (1024*1024):.1f} MB"))
            
            # Resize columns to fit content
            self.comparison_table.resizeColumnsToContents()
            
            QMessageBox.information(self, "Added", "Model added to comparison table.")
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add model to comparison: {str(e)}")
    
    def clear_comparison_table(self):
        """Clear the comparison table."""
        self.comparison_table.setRowCount(0)
    
    def refresh_library(self):
        """Refresh the model library."""
        # Verify all files still exist
        self.model_library = [item for item in self.model_library 
                             if os.path.exists(item['path'])]
        self.update_model_tree()
        self.operation_label.setText("Library refreshed")
    
    def remove_selected_model(self):
        """Remove selected model from library."""
        current_item = self.model_tree.currentItem()
        if current_item:
            file_path = current_item.data(0, Qt.ItemDataRole.UserRole)
            
            # If this is the currently loaded model, clear the viewer
            if self.current_model_path == file_path:
                self.model_viewer.clear()
                self.current_model_path = None
                self.operation_label.setText("Model viewer cleared")
                # Clear the info labels
                self.clear_model_info_labels()
            
            # Remove from library
            self.model_library = [item for item in self.model_library 
                                 if item['path'] != file_path]
            self.update_model_tree()
            self.operation_label.setText("Model removed from library")
    
    def clear_model_info_labels(self):
        """Clear all model information labels."""
        self.file_name_label.setText("No model loaded")
        self.file_size_label.setText("-")
        self.file_format_label.setText("-")
        self.vertices_label.setText("-")
        self.faces_label.setText("-")
        self.edges_label.setText("-")
        self.surface_area_label.setText("-")
        self.volume_label.setText("-")
        self.is_watertight_label.setText("-")
        self.bounds_label.setText("-")
        self.uv_label.setText("-")
        self.vcolors_label.setText("-")
        self.materials_label.setText("-")