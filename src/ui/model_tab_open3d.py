"""
Model tab for RenderFox - centralizes all model-related functionality.
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
from PyQt6.QtGui import QPixmap, QIcon, QColor

from .model_viewer import ModelViewerWidget
from .model_viewer_open3d import ModelViewerWidget_Open3D
import trimesh
import json
from datetime import datetime
import numpy as np

# New imports for conversion wiring
from src.processing.format_converter import FormatConverter, SupportedFormat
from src.ui.conversion_results_dialog import show_conversion_results
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

# --- Helpers for Open3D conversion (optional at runtime) ---

def _trimesh_to_open3d(mesh):
    try:
        import open3d as o3d
    except Exception:
        return None
    try:
        o3 = o3d.geometry.TriangleMesh()
        o3.vertices = o3d.utility.Vector3dVector(np.asarray(mesh.vertices))
        o3.triangles = o3d.utility.Vector3iVector(np.asarray(mesh.faces))
        if mesh.vertex_normals is not None and len(mesh.vertex_normals) == len(mesh.vertices):
            o3.vertex_normals = o3d.utility.Vector3dVector(np.asarray(mesh.vertex_normals))
        if hasattr(mesh, 'visual') and getattr(mesh.visual, 'uv', None) is not None:
            try:
                o3.triangle_uvs = o3d.utility.Vector2dVector(np.asarray(mesh.visual.uv))
            except Exception:
                pass
        o3.compute_vertex_normals()
        return o3
    except Exception:
        return None

def _open3d_to_trimesh(o3):
    try:
        import open3d as o3d  # noqa
        verts = np.asarray(o3.vertices)
        faces = np.asarray(o3.triangles)
        tm = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        try:
            tm.vertex_normals  # force compute if needed
        except Exception:
            pass
        return tm
    except Exception:
        return None

class ModelAnalysisWorker(QThread):
    """Worker thread for analyzing model files."""
    
    analysis_complete = pyqtSignal(dict)
    progress_updated = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths
    
    def run(self):
        """Analyze the model files."""
        results = []
        total_files = len(self.file_paths)
        
        for i, file_path in enumerate(self.file_paths):
            try:
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
                    'convex_hull_volume': mesh.convex_hull.volume if hasattr(mesh, 'convex_hull') else 0.0
                }
                results.append(analysis)
            except Exception as e:
                self.error_occurred.emit(f"Error analyzing {file_path}: {str(e)}")
        
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
    """Comprehensive model management tab."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model_path = None
        self.model_library = []
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
        self.load_model_btn.setProperty("primary", "true")
        self.load_folder_btn = QPushButton("Load Folder")
        self.load_folder_btn.setIcon(get_icon("folder"))
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(get_icon("refresh"))
        self.refresh_btn.setToolTip("Refresh List")
        self.refresh_btn.setMaximumWidth(36)
        self.remove_model_btn = QPushButton()
        self.remove_model_btn.setIcon(get_icon("delete"))
        self.remove_model_btn.setToolTip("Remove Selected")
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
        
        # 3D Viewer tab - Use Open3D viewer
        self.model_viewer = ModelViewerWidget_Open3D()
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
        
        # Settings tab (new)
        settings_widget = self.create_settings_tab()
        self.detail_tabs.addTab(settings_widget, "Settings")
        
        right_layout.addWidget(self.detail_tabs)
        
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([350, 850])
    
    def create_settings_tab(self):
        """Create the comprehensive rendering/material settings tab with all Open3D controls."""
        widget = QWidget()
        
        # Create scrollable area for all the controls
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        
        # Render Mode group - Enhanced with points/vertices
        render_group = QGroupBox("Render Mode")
        render_layout = QFormLayout()
        
        self.render_mode_combo = QComboBox()
        self.render_mode_combo.addItems(["Fill", "Wireframe", "Points", "Overlay"])
        self.render_mode_combo.currentTextChanged.connect(
            lambda txt: self.model_viewer.set_render_mode(txt.lower())
        )
        render_layout.addRow("Mode:", self.render_mode_combo)
        
        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.5, 20.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setValue(1.0)
        self.line_width_spin.valueChanged.connect(self.model_viewer.set_line_width)
        render_layout.addRow("Line Width:", self.line_width_spin)
        
        self.point_size_spin = QDoubleSpinBox()
        self.point_size_spin.setRange(1.0, 50.0)
        self.point_size_spin.setSingleStep(0.5)
        self.point_size_spin.setValue(3.0)
        self.point_size_spin.valueChanged.connect(self.model_viewer.set_point_size)
        render_layout.addRow("Point Size:", self.point_size_spin)
        
        render_group.setLayout(render_layout)
        layout.addWidget(render_group)
        
        # Visualization Elements group
        viz_group = QGroupBox("Visualization Elements")
        viz_layout = QFormLayout()
        
        self.show_coord_frame_cb = QCheckBox("Show Coordinate Frame")
        self.show_coord_frame_cb.setChecked(False)
        self.show_coord_frame_cb.toggled.connect(self.model_viewer.set_show_coordinate_frame)
        viz_layout.addRow(self.show_coord_frame_cb)
        
        self.show_bbox_cb = QCheckBox("Show Bounding Box")
        self.show_bbox_cb.setChecked(False)
        self.show_bbox_cb.toggled.connect(self.model_viewer.set_show_bounding_box)
        viz_layout.addRow(self.show_bbox_cb)
        
        self.show_normals_cb = QCheckBox("Show Normal Vectors")
        self.show_normals_cb.setChecked(False)
        self.show_normals_cb.toggled.connect(self.model_viewer.set_show_normals)
        viz_layout.addRow(self.show_normals_cb)
        
        # Auto-rotation control
        self.auto_rotate_cb = QCheckBox("Auto Rotate")
        self.auto_rotate_cb.setChecked(False)
        self.auto_rotate_cb.toggled.connect(self.model_viewer.viewer_3d.set_auto_rotate)
        viz_layout.addRow(self.auto_rotate_cb)
        
        viz_group.setLayout(viz_layout)
        layout.addWidget(viz_group)
        
        # Lighting group - Enhanced
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
        
        # Colors group - Enhanced
        color_group = QGroupBox("Colors")
        color_layout = QFormLayout()
        
        # Background color
        self.bg_color_preview = QLabel("  ")
        self.bg_color_preview.setFixedSize(36, 18)
        def set_bg_preview(color: QColor):
            self.bg_color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
        def pick_bg_color():
            col = QColorDialog.getColor(QColor(25, 25, 25), self, "Select Background Color")
            if col.isValid():
                set_bg_preview(col)
                self.model_viewer.set_background_color(col.red()/255.0, col.green()/255.0, col.blue()/255.0)
        bg_row = QHBoxLayout(); bg_btn = QPushButton("Choose..."); bg_btn.clicked.connect(pick_bg_color)
        bg_row.addWidget(self.bg_color_preview); bg_row.addWidget(bg_btn); bg_row.addStretch()
        color_layout.addRow("Background:", bg_row)
        set_bg_preview(QColor(25, 25, 25))  # Dark gray default
        
        # Wireframe color
        self.wire_color_preview = QLabel("  ")
        self.wire_color_preview.setFixedSize(36, 18)
        def set_wire_preview(color: QColor):
            self.wire_color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
        def pick_wire_color():
            col = QColorDialog.getColor(QColor(0, 255, 0), self, "Select Wireframe Color")
            if col.isValid():
                set_wire_preview(col)
                self.model_viewer.set_wireframe_color(col.red()/255.0, col.green()/255.0, col.blue()/255.0)
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
                self.model_viewer.set_mesh_color(col.red()/255.0, col.green()/255.0, col.blue()/255.0)
        base_row = QHBoxLayout(); base_btn = QPushButton("Choose..."); base_btn.clicked.connect(pick_base_color)
        base_row.addWidget(self.base_color_preview); base_row.addWidget(base_btn); base_row.addStretch()
        color_layout.addRow("Default Mesh:", base_row)
        set_base_preview(QColor(179, 179, 230))  # Light blue default
        
        color_group.setLayout(color_layout)
        layout.addWidget(color_group)
        
        # View Controls group
        view_group = QGroupBox("View Controls")
        view_layout = QVBoxLayout()
        
        view_buttons_row1 = QHBoxLayout()
        reset_view_btn = QPushButton("Reset View")
        reset_view_btn.clicked.connect(self.model_viewer.viewer_3d.reset_view)
        
        refresh_preview_btn = QPushButton("Refresh Preview")
        refresh_preview_btn.clicked.connect(self.model_viewer.viewer_3d.refresh_preview)
        
        view_buttons_row1.addWidget(reset_view_btn)
        view_buttons_row1.addWidget(refresh_preview_btn)
        view_layout.addLayout(view_buttons_row1)
        
        view_buttons_row2 = QHBoxLayout()
        open_3d_btn = QPushButton("Open 3D Viewer")
        open_3d_btn.clicked.connect(self.model_viewer.viewer_3d.open_3d_viewer)
        
        export_image_btn = QPushButton("Export Image")
        export_image_btn.clicked.connect(self.model_viewer.viewer_3d.export_image)
        
        view_buttons_row2.addWidget(open_3d_btn)
        view_buttons_row2.addWidget(export_image_btn)
        view_layout.addLayout(view_buttons_row2)
        
        view_group.setLayout(view_layout)
        layout.addWidget(view_group)
        
        # Quality & Performance group
        quality_group = QGroupBox("Quality & Performance")
        quality_layout = QFormLayout()
        
        # Anti-aliasing (note: would need Open3D implementation)
        self.antialiasing_cb = QCheckBox("Anti-aliasing (if available)")
        self.antialiasing_cb.setChecked(True)
        quality_layout.addRow(self.antialiasing_cb)
        
        # Face culling
        self.cull_backfaces_cb = QCheckBox("Cull Back Faces")
        self.cull_backfaces_cb.setChecked(False)
        quality_layout.addRow(self.cull_backfaces_cb)
        
        # Smooth shading
        self.smooth_shading_cb = QCheckBox("Smooth Shading")
        self.smooth_shading_cb.setChecked(True)
        quality_layout.addRow(self.smooth_shading_cb)
        
        quality_group.setLayout(quality_layout)
        layout.addWidget(quality_group)
        
        # Presets group
        presets_group = QGroupBox("Presets")
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
        preset_points_btn = QPushButton("Point Cloud")
        preset_points_btn.clicked.connect(self.apply_points_preset)
        
        preset_debug_btn = QPushButton("Debug View")
        preset_debug_btn.clicked.connect(self.apply_debug_preset)
        
        presets_row2.addWidget(preset_points_btn)
        presets_row2.addWidget(preset_debug_btn)
        presets_layout.addLayout(presets_row2)
        
        presets_group.setLayout(presets_layout)
        layout.addWidget(presets_group)
        
        layout.addStretch()
        
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
        self.show_coord_frame_cb.setChecked(True)
        self.line_width_spin.setValue(1.5)
        
    def apply_solid_preset(self):
        """Apply solid/filled viewing preset."""
        self.render_mode_combo.setCurrentText("Fill")
        self.lighting_enable_cb.setChecked(True)
        self.textures_cb.setChecked(True)
        self.vcolors_cb.setChecked(True)
        self.show_coord_frame_cb.setChecked(False)
        
    def apply_points_preset(self):
        """Apply point cloud viewing preset."""
        self.render_mode_combo.setCurrentText("Points")
        self.lighting_enable_cb.setChecked(False)
        self.point_size_spin.setValue(5.0)
        self.show_coord_frame_cb.setChecked(True)
        
    def apply_debug_preset(self):
        """Apply debug viewing preset with all visualization aids."""
        self.render_mode_combo.setCurrentText("Overlay")
        self.lighting_enable_cb.setChecked(True)
        self.show_coord_frame_cb.setChecked(True)
        self.show_bbox_cb.setChecked(True)
        self.show_normals_cb.setChecked(True)
        self.line_width_spin.setValue(2.0)
    
    def create_info_tab(self):
        """Create the model information tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Basic information
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        
        self.info_filename = QLabel("-")
        self.info_filesize = QLabel("-")
        self.info_format = QLabel("-")
        self.info_vertices = QLabel("-")
        self.info_faces = QLabel("-")
        self.info_edges = QLabel("-")
        
        basic_layout.addRow("Filename:", self.info_filename)
        basic_layout.addRow("File Size:", self.info_filesize)
        basic_layout.addRow("Format:", self.info_format)
        basic_layout.addRow("Vertices:", self.info_vertices)
        basic_layout.addRow("Faces:", self.info_faces)
        basic_layout.addRow("Edges:", self.info_edges)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # Geometric properties
        geo_group = QGroupBox("Geometric Properties")
        geo_layout = QFormLayout()
        
        self.info_surface_area = QLabel("-")
        self.info_volume = QLabel("-")
        self.info_bounds = QLabel("-")
        self.info_center = QLabel("-")
        self.info_watertight = QLabel("-")
        
        geo_layout.addRow("Surface Area:", self.info_surface_area)
        geo_layout.addRow("Volume:", self.info_volume)
        geo_layout.addRow("Bounding Box:", self.info_bounds)
        geo_layout.addRow("Center:", self.info_center)
        geo_layout.addRow("Watertight:", self.info_watertight)
        
        geo_group.setLayout(geo_layout)
        layout.addWidget(geo_group)
        
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
        
        controls_layout.addWidget(QLabel("Analysis Type:"))
        controls_layout.addWidget(self.analysis_type)
        controls_layout.addWidget(run_analysis_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Results display
        self.analysis_results = QTextEdit()
        self.analysis_results.setReadOnly(True)
        self.analysis_results.setPlainText("No analysis performed yet. Select a model and run analysis.")
        
        layout.addWidget(self.analysis_results)
        
        return widget
    
    def create_comparison_tab(self):
        """Create the model comparison tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Comparison controls
        controls_layout = QHBoxLayout()
        
        self.model_a_path = QLineEdit()
        self.model_a_path.setPlaceholderText("Select first model...")
        browse_a_btn = QPushButton("Browse A")
        browse_a_btn.clicked.connect(lambda: self.browse_comparison_model('A'))
        
        self.model_b_path = QLineEdit()
        self.model_b_path.setPlaceholderText("Select second model...")
        browse_b_btn = QPushButton("Browse B")
        browse_b_btn.clicked.connect(lambda: self.browse_comparison_model('B'))
        
        compare_btn = QPushButton("Compare Models")
        compare_btn.clicked.connect(self.compare_models)
        
        controls_layout.addWidget(QLabel("Model A:"))
        controls_layout.addWidget(self.model_a_path)
        controls_layout.addWidget(browse_a_btn)
        controls_layout.addWidget(QLabel("Model B:"))
        controls_layout.addWidget(self.model_b_path)
        controls_layout.addWidget(browse_b_btn)
        controls_layout.addWidget(compare_btn)
        
        layout.addLayout(controls_layout)
        
        # Comparison results table
        self.comparison_table = QTableWidget()
        self.comparison_table.setColumnCount(3)
        self.comparison_table.setHorizontalHeaderLabels(["Property", "Model A", "Model B"])
        self.comparison_table.horizontalHeader().setStretchLastSection(True)
        
        layout.addWidget(self.comparison_table)
        
        return widget
    
    def setup_connections(self):
        """Setup signal connections."""
        # Browser connections
        self.load_model_btn.clicked.connect(self.load_single_model)
        self.load_folder_btn.clicked.connect(self.load_model_folder)
        self.refresh_btn.clicked.connect(self.refresh_model_tree)
        self.remove_model_btn.clicked.connect(self.remove_selected_model)
        self.model_tree.itemSelectionChanged.connect(self.on_model_selected)
        
        # Tool connections
        self.analyze_btn.clicked.connect(self.analyze_selected_model)
        self.batch_analyze_btn.clicked.connect(self.batch_analyze_models)
        self.export_report_btn.clicked.connect(self.export_analysis_report)
        self.convert_btn.clicked.connect(self.convert_selected_model)
        self.batch_convert_btn.clicked.connect(self.batch_convert_models)
        self.simplify_btn.clicked.connect(self.simplify_selected_model)
        self.repair_btn.clicked.connect(self.repair_selected_model)
        self.optimize_btn.clicked.connect(self.optimize_selected_model)
        
        # Model viewer connections
        self.model_viewer.viewer_3d.model_loaded.connect(self.update_model_info)
        self.model_viewer.cleared.connect(self.on_viewer_cleared)
    
    def load_single_model(self):
        """Load a single model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load 3D Model",
            "", "3D Models (*.obj *.stl *.ply *.glb *.gltf *.fbx *.dae *.x3d);;All Files (*)"
        )
        
        if file_path:
            self.add_model_to_tree(file_path)
            self.load_model_in_viewer(file_path)
    
    def load_model_folder(self):
        """Load all models from a folder."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Model Folder")
        
        if folder_path:
            self.scan_folder_for_models(folder_path)
    
    def scan_folder_for_models(self, folder_path):
        """Scan folder for 3D model files."""
        model_extensions = {'.obj', '.stl', '.ply', '.glb', '.gltf', '.fbx', '.dae', '.x3d'}
        
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if any(file.lower().endswith(ext) for ext in model_extensions):
                    file_path = os.path.join(root, file)
                    self.add_model_to_tree(file_path)
    
    def add_model_to_tree(self, file_path):
        """Add a model to the tree widget."""
        if any(item.data(0, Qt.ItemDataRole.UserRole) == file_path 
               for item in self.get_all_tree_items()):
            return  # Already exists
        
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].upper()
        file_size = self.format_file_size(os.path.getsize(file_path))
        
        item = QTreeWidgetItem([file_name, file_ext, file_size])
        item.setData(0, Qt.ItemDataRole.UserRole, file_path)
        
        self.model_tree.addTopLevelItem(item)
        self.model_library.append(file_path)
    
    def get_all_tree_items(self):
        """Get all items from the tree widget."""
        items = []
        root = self.model_tree.invisibleRootItem()
        for i in range(root.childCount()):
            items.append(root.child(i))
        return items
    
    def format_file_size(self, size_bytes):
        """Format file size in human readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
    
    def refresh_model_tree(self):
        """Refresh the model tree."""
        # Clear viewer first to free any GL resources
        self.model_viewer.clear()
        self.clear_info()
        self.current_model_path = None
        
        # Then clear the tree and library
        self.model_tree.clear()
        self.model_library.clear()

    def remove_selected_model(self):
        """Remove the selected model from the list and clear viewer if open.
        Prompts to delete the file from disk as well.
        """
        selected_items = self.model_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a model to remove.")
            return
        item = selected_items[0]
        file_path = item.data(0, Qt.ItemDataRole.UserRole)

        # If it's currently open, clear viewer and info first to release any handles
        if self.current_model_path == file_path:
            self.model_viewer.clear()
            self.clear_info()
            self.current_model_path = None

        # Ask whether to delete from disk
        delete_from_disk = QMessageBox.question(
            self,
            "Delete Model",
            f"Remove from list: {os.path.basename(file_path)}\n\nDo you also want to delete the file from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No
        )
        
        if delete_from_disk == QMessageBox.StandardButton.Cancel:
            return

        # Remove from tree
        index = self.model_tree.indexOfTopLevelItem(item)
        if index >= 0:
            self.model_tree.takeTopLevelItem(index)
        # Remove from library list
        try:
            self.model_library.remove(file_path)
        except ValueError:
            pass

        # Optionally delete the file from disk
        if delete_from_disk == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.operation_label.setText(f"Deleted: {os.path.basename(file_path)}")
                else:
                    self.operation_label.setText("File already removed from disk")
            except Exception as e:
                QMessageBox.warning(self, "Delete Failed", f"Could not delete file:\n{e}")
                self.operation_label.setText("Delete failed")
        else:
            self.operation_label.setText(f"Removed from list: {os.path.basename(file_path)}")

    def clear_info(self):
        """Clear the information tab labels."""
        self.info_filename.setText("-")
        self.info_filesize.setText("-")
        self.info_format.setText("-")
        self.info_vertices.setText("-")
        self.info_faces.setText("-")
        if hasattr(self, 'info_edges'):
            self.info_edges.setText("-")
        self.info_surface_area.setText("-")
        self.info_volume.setText("-")
        self.info_bounds.setText("-")
        if hasattr(self, 'info_center'):
            self.info_center.setText("-")
        if hasattr(self, 'info_watertight'):
            self.info_watertight.setText("-")

    def on_viewer_cleared(self):
        """Handle viewer cleared signal to reset model info and state."""
        self.clear_info()
        self.operation_label.setText("Viewer cleared")
        self.current_model_path = None

    def on_model_selected(self):
        """Handle model selection in tree."""
        selected_items = self.model_tree.selectedItems()
        if not selected_items:
            # No selection - clear viewer
            if self.current_model_path is not None:
                self.model_viewer.clear()
                self.clear_info()
                self.current_model_path = None
            return
            
        file_path = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        
        # If selecting the same model, do nothing
        if self.current_model_path == file_path:
            return
            
        # Always clear the current viewer first to ensure proper cleanup
        self.operation_label.setText("Clearing previous model...")
        self.model_viewer.clear()
        self.clear_info()
        
        # Small delay to ensure cleanup is complete before loading new model
        QTimer.singleShot(100, lambda: self._load_selected_model(file_path))
    
    def _load_selected_model(self, file_path):
        """Load the selected model after ensuring cleanup is complete."""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "File Not Found", f"Model file not found:\n{file_path}")
            return
            
        self.current_model_path = file_path
        self.operation_label.setText("Loading model...")
        
        success = self.model_viewer.load_model(file_path)
        
        if success:
            self.operation_label.setText(f"Loaded: {os.path.basename(file_path)}")
        else:
            self.operation_label.setText(f"Failed to load: {os.path.basename(file_path)}")
            # Clear the current model path since loading failed
            self.current_model_path = None
    
    def load_model_in_viewer(self, file_path):
        """Load model in the 3D viewer. Ensures only one model is displayed."""
        # Clear first to free any GL resources from the previous model
        self.model_viewer.clear()
        self.current_model_path = file_path
        self.operation_label.setText("Loading model...")
        success = self.model_viewer.load_model(file_path)
        
        if success:
            self.operation_label.setText(f"Loaded: {os.path.basename(file_path)}")
        else:
            self.operation_label.setText(f"Failed to load: {os.path.basename(file_path)}")
    
    def update_model_info(self, model_info):
        """Update the model information display."""
        if self.current_model_path:
            # Update basic info
            self.info_filename.setText(os.path.basename(self.current_model_path))
            self.info_filesize.setText(self.format_file_size(os.path.getsize(self.current_model_path)))
            self.info_format.setText(os.path.splitext(self.current_model_path)[1].upper())
            self.info_vertices.setText(f"{model_info['vertices']:,}")
            self.info_faces.setText(f"{model_info['faces']:,}")
            # New: edges
            if hasattr(self, 'info_edges'):
                self.info_edges.setText(f"{model_info.get('edges', 0):,}")
            
            # Update geometric properties
            self.info_surface_area.setText(f"{model_info['surface_area']:.2f}")
            self.info_volume.setText(f"{model_info['volume']:.2f}" if model_info['volume'] > 0 else "N/A")
            
            bounds = model_info['bounds']
            bounds_text = f"({bounds[0][0]:.2f}, {bounds[0][1]:.2f}, {bounds[0][2]:.2f}) to ({bounds[1][0]:.2f}, {bounds[1][1]:.2f}, {bounds[1][2]:.2f})"
            self.info_bounds.setText(bounds_text)
            
            # New: center and watertight
            if hasattr(self, 'info_center'):
                center = model_info.get('center', [0.0, 0.0, 0.0])
                self.info_center.setText(f"({center[0]:.2f}, {center[1]:.2f}, {center[2]:.2f})")
            if hasattr(self, 'info_watertight'):
                self.info_watertight.setText("Yes" if model_info.get('is_watertight', False) else "No")
    
    def analyze_selected_model(self):
        """Analyze the currently selected model."""
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
        """Analyze materials, textures, vertex colors and UVs for the current model.
        Tries to open as Scene to inspect per-geometry materials; falls back to mesh.visual.
        """
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
                        import numpy as _np
                        arr = _np.array(img)
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
    
    def run_detailed_analysis(self):
        """Run detailed analysis on current model."""
        if self.current_model_path:
            self.run_analysis_on_file(self.current_model_path)
        else:
            QMessageBox.warning(self, "No Model", "Please select a model to analyze.")
    
    def browse_comparison_model(self, model_letter):
        """Browse for comparison model."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"Select Model {model_letter}",
            "", "3D Models (*.obj *.stl *.ply *.glb *.gltf *.fbx *.dae *.x3d);;All Files (*)"
        )
        
        if file_path:
            if (model_letter == 'A'):
                self.model_a_path.setText(file_path)
            else:
                self.model_b_path.setText(file_path)
    
    def compare_models(self):
        """Compare two models."""
        path_a = self.model_a_path.text()
        path_b = self.model_b_path.text()
        
        if not path_a or not path_b:
            QMessageBox.warning(self, "Missing Models", "Please select both models for comparison.")
            return
        
        try:
            mesh_a_obj = trimesh.load(path_a)
            mesh_b_obj = trimesh.load(path_b)
            mesh_a = _as_trimesh(mesh_a_obj)
            mesh_b = _as_trimesh(mesh_b_obj)
            if mesh_a is None or mesh_b is None:
                raise ValueError("One or both models couldn't be read as meshes")
            
            # Populate comparison table
            self.comparison_table.setRowCount(0)
            
            comparisons = [
                ("Vertices", f"{len(mesh_a.vertices):,}", f"{len(mesh_b.vertices):,}"),
                ("Faces", f"{len(mesh_a.faces):,}", f"{len(mesh_b.faces):,}"),
                ("Surface Area", f"{mesh_a.area:.4f}", f"{mesh_b.area:.4f}"),
                ("Volume", f"{mesh_a.volume:.4f}" if mesh_a.is_volume else "N/A", 
                          f"{mesh_b.volume:.4f}" if mesh_b.is_volume else "N/A"),
                ("Watertight", "Yes" if mesh_a.is_watertight else "No",
                             "Yes" if mesh_b.is_watertight else "No"),
                ("File Size", self.format_file_size(os.path.getsize(path_a)),
                            self.format_file_size(os.path.getsize(path_b)))
            ]
            
            for i, (prop, val_a, val_b) in enumerate(comparisons):
                self.comparison_table.insertRow(i)
                self.comparison_table.setItem(i, 0, QTableWidgetItem(prop))
                self.comparison_table.setItem(i, 1, QTableWidgetItem(val_a))
                self.comparison_table.setItem(i, 2, QTableWidgetItem(val_b))
        
        except Exception as e:
            QMessageBox.critical(self, "Comparison Error", f"Error comparing models: {str(e)}")
    
    def batch_analyze_models(self):
        """Perform batch analysis on multiple models."""
        if not self.model_library:
            QMessageBox.information(self, "No Models", "Please load some models first.")
            return
        
        self.progress_bar.setVisible(True)
        self.operation_label.setText("Running batch analysis...")
        
        # Start analysis worker
        self.analysis_worker = ModelAnalysisWorker(self.model_library)
        self.analysis_worker.progress_updated.connect(self.progress_bar.setValue)
        self.analysis_worker.analysis_complete.connect(self.on_batch_analysis_complete)
        self.analysis_worker.error_occurred.connect(self.on_analysis_error)
        self.analysis_worker.start()
    
    def on_batch_analysis_complete(self, results):
        """Handle batch analysis completion."""
        self.progress_bar.setVisible(False)
        self.operation_label.setText(f"Analyzed {results['total_analyzed']} models")
        
        # Show results summary
        summary = f"Batch Analysis Complete\n\n"
        summary += f"Total models analyzed: {results['total_analyzed']}\n\n"
        
        if results['results']:
            avg_vertices = np.mean([r['vertices'] for r in results['results']])
            avg_faces = np.mean([r['faces'] for r in results['results']])
            total_size = sum([r['file_size_mb'] for r in results['results']])
            
            summary += f"Average vertices: {avg_vertices:.0f}\n"
            summary += f"Average faces: {avg_faces:.0f}\n"
            summary += f"Total size: {total_size:.1f} MB\n"
        
        QMessageBox.information(self, "Batch Analysis Complete", summary)
    
    def on_analysis_error(self, error_message):
        """Handle analysis errors."""
        QMessageBox.warning(self, "Analysis Error", error_message)
    
    def export_analysis_report(self):
        """Export analysis report to file."""
        if not self.model_library:
            QMessageBox.information(self, "No Data", "No models to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Analysis Report",
            f"model_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;Text Files (*.txt)"
        )
        
        if file_path:
            try:
                # Generate comprehensive report
                report_data = {
                    'export_timestamp': datetime.now().isoformat(),
                    'total_models': len(self.model_library),
                    'models': []
                }
                
                # Analyze each model for the report
                for model_path in self.model_library:
                    try:
                        mesh_obj = trimesh.load(model_path)
                        mesh = _as_trimesh(mesh_obj)
                        if mesh is None:
                            continue
                            
                        model_data = {
                            'file_path': model_path,
                            'file_name': os.path.basename(model_path),
                            'file_size_mb': os.path.getsize(model_path) / (1024 * 1024),
                            'vertices': len(mesh.vertices),
                            'faces': len(mesh.faces),
                            'edges': len(mesh.edges),
                            'surface_area': float(mesh.area),
                            'volume': float(mesh.volume) if mesh.is_volume else 0.0,
                            'is_watertight': mesh.is_watertight,
                            'is_winding_consistent': mesh.is_winding_consistent,
                            'bounds': mesh.bounds.tolist(),
                            'center': mesh.center_mass.tolist(),
                            'format': os.path.splitext(model_path)[1].upper()
                        }
                        report_data['models'].append(model_data)
                    except Exception as e:
                        # Add error entry for failed models
                        report_data['models'].append({
                            'file_path': model_path,
                            'file_name': os.path.basename(model_path),
                            'error': str(e)
                        })
                
                # Export based on file extension
                if file_path.lower().endswith('.json'):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(report_data, f, indent=2, ensure_ascii=False)
                else:
                    # Export as text
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(f"RenderFox Model Analysis Report\n")
                        f.write(f"Generated: {report_data['export_timestamp']}\n")
                        f.write(f"Total Models: {report_data['total_models']}\n\n")
                        
                        for model in report_data['models']:
                            if 'error' in model:
                                f.write(f"[Error] {model['file_name']}: {model['error']}\n")
                            else:
                                f.write(f"[OK] {model['file_name']}\n")
                                f.write(f"   Format: {model['format']}\n")
                                f.write(f"   Size: {model['file_size_mb']:.2f} MB\n")
                                f.write(f"   Vertices: {model['vertices']:,}\n")
                                f.write(f"   Faces: {model['faces']:,}\n")
                                f.write(f"   Watertight: {'Yes' if model['is_watertight'] else 'No'}\n")
                                f.write(f"   Surface Area: {model['surface_area']:.2f}\n")
                                if model['volume'] > 0:
                                    f.write(f"   Volume: {model['volume']:.2f}\n")
                                f.write("\n")
                
                QMessageBox.information(self, "Export Complete", 
                    f"Analysis report exported successfully!\n\nFile: {file_path}\n"
                    f"Models analyzed: {len([m for m in report_data['models'] if 'error' not in m])}")
                    
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Failed to export report:\n{str(e)}")
    
    def convert_selected_model(self):
        """Convert the selected model format."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to convert.")
            return
        
        dialog = ModelFormatConverter(self, [self.current_model_path])
        dialog.exec()
    
    def batch_convert_models(self):
        """Batch convert multiple models."""
        if not self.model_library:
            QMessageBox.information(self, "No Models", "Please load some models first.")
            return
        
        dialog = ModelFormatConverter(self, self.model_library)
        dialog.exec()
    
    def simplify_selected_model(self):
        """Simplify the selected model using available backends (Open3D or PyMeshLab)."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to simplify.")
            return
        
        # Load mesh
        try:
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            if mesh is None:
                raise ValueError("Unsupported or empty model")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load mesh: {e}")
            return
        
        # Ask user for target percentage
        percent, ok = QInputDialog.getDouble(self, "Simplify Mesh", "Target face count (% of current):", 50.0, 1.0, 100.0, 1)
        if not ok:
            return
        target_faces = max(10, int(len(mesh.faces) * (percent / 100.0)))
        
        # Try Open3D decimation first
        simplified = None
        backend = None
        try:
            o3_in = _trimesh_to_open3d(mesh)
            if o3_in is not None:
                o3_out = o3_in.simplify_quadric_decimation(target_number_of_triangles=int(target_faces))
                o3_out.remove_degenerate_triangles()
                o3_out.remove_duplicated_triangles()
                o3_out.remove_duplicated_vertices()
                o3_out.remove_non_manifold_edges()
                o3_out.compute_vertex_normals()
                tm = _open3d_to_trimesh(o3_out)
                if tm is not None and len(tm.faces) > 0:
                    simplified = tm
                    backend = 'Open3D'
        except Exception:
            simplified = None
        
        # Try PyMeshLab as a fallback
        if simplified is None:
            try:
                import pymeshlab as ml
                ms = ml.MeshSet()
                # pymeshlab expects a path or an ml.Mesh
                # Create temporary mesh from vertices/faces
                m = ml.Mesh(np.array(mesh.vertices, dtype=np.float64), np.array(mesh.faces, dtype=np.int32))
                ms.add_mesh(m, 'in')
                ms.apply_filter('meshing_decimation_quadric_edge_collapse', targetfacenum=int(target_faces), preservenormal=True)
                m_out = ms.current_mesh()
                v = np.array(m_out.vertex_matrix(), dtype=np.float64)
                f = np.array(m_out.face_matrix(), dtype=np.int64)
                tm = trimesh.Trimesh(vertices=v, faces=f, process=False)
                simplified = tm
                backend = 'PyMeshLab'
            except Exception:
                simplified = None
        
        if simplified is None:
            QMessageBox.information(self, "Simplify", "No simplification backend available. Install open3d or pymeshlab to enable decimation.")
            return
        
        # Save result
        base, ext = os.path.splitext(self.current_model_path)
        out_path, _ = QFileDialog.getSaveFileName(self, "Save Simplified Mesh", f"{base}_simplified{ext}",
                                                  "3D Models (*.obj *.stl *.ply *.glb *.gltf);;All Files (*)")
        if not out_path:
            return
        try:
            simplified.export(out_path)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save simplified mesh: {e}")
            return
        
        QMessageBox.information(self, "Simplify Complete", f"Simplified with {backend}: {len(mesh.faces):,} -> {len(simplified.faces):,} faces\nSaved to: {out_path}")
        
        # Offer to load
        self.add_model_to_tree(out_path)
        self.load_model_in_viewer(out_path)
    
    def repair_selected_model(self):
        """Repair the selected model using trimesh and optional pymeshfix."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to repair.")
            return
        try:
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            if mesh is None:
                raise ValueError("Unsupported or empty model")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load mesh: {e}")
            return
        
        before_faces = len(mesh.faces)
        before_verts = len(mesh.vertices)
        before_wt = mesh.is_watertight
        
        # In-place repairs (best-effort)
        try:
            mesh.remove_duplicate_faces()
        except Exception:
            pass
        try:
            mesh.remove_degenerate_faces()
        except Exception:
            pass
        try:
            mesh.remove_unreferenced_vertices()
        except Exception:
            pass
        try:
            trimesh.repair.fix_normals(mesh)
        except Exception:
            pass
        try:
            # may not be available in some versions
            if hasattr(trimesh.repair, 'fill_holes'):
                trimesh.repair.fill_holes(mesh)
        except Exception:
            pass
        
        # Optional watertight repair via pymeshfix
        improved_mesh = mesh
        try:
            from pymeshfix import MeshFix  # optional
            mf = MeshFix(np.asarray(mesh.vertices), np.asarray(mesh.faces))
            mf.repair(verbose=False)
            v2, f2 = mf.return_mesh()
            if v2 is not None and f2 is not None and len(f2) > 0:
                improved_mesh = trimesh.Trimesh(vertices=v2, faces=f2, process=False)
        except Exception:
            pass
        
        try:
            improved_mesh.process(validate=True)
        except Exception:
            pass
        try:
            trimesh.repair.fix_normals(improved_mesh)
        except Exception:
            pass
        
        after_faces = len(improved_mesh.faces)
        after_verts = len(improved_mesh.vertices)
        after_wt = improved_mesh.is_watertight
        
        # Save result
        base, ext = os.path.splitext(self.current_model_path)
        out_path, _ = QFileDialog.getSaveFileName(self, "Save Repaired Mesh", f"{base}_repaired{ext}",
                                                  "3D Models (*.obj *.stl *.ply *.glb *.gltf);;All Files (*)")
        if not out_path:
            return
        try:
            improved_mesh.export(out_path)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save repaired mesh: {e}")
            return
        
        msg = ["Repair Complete:"]
        msg.append(f"Vertices: {before_verts:,} -> {after_verts:,}")
        msg.append(f"Faces: {before_faces:,} -> {after_faces:,}")
        msg.append(f"Watertight: {'Yes' if before_wt else 'No'} -> {'Yes' if after_wt else 'No'}")
        msg.append(f"Saved to: {out_path}")
        QMessageBox.information(self, "Repair", "\n".join(msg))
        
        # Load result
        self.add_model_to_tree(out_path)
        self.load_model_in_viewer(out_path)
    
    def optimize_selected_model(self):
        """Optimize the selected model: cleanup, center, normals, optional scale normalization."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Model", "Please select a model to optimize.")
            return
        try:
            mesh_obj = trimesh.load(self.current_model_path)
            mesh = _as_trimesh(mesh_obj)
            if mesh is None:
                raise ValueError("Unsupported or empty model")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load mesh: {e}")
            return
        
        # Ask whether to normalize scale to unit box
        normalize = QMessageBox.question(self, "Normalize Scale", "Normalize model to unit bounding box?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        
        before_faces = len(mesh.faces)
        before_verts = len(mesh.vertices)
        
        # Cleanup
        try:
            mesh.process()
        except Exception:
            pass
        for fn in (
            getattr(mesh, 'remove_duplicate_faces', None),
            getattr(mesh, 'remove_degenerate_faces', None),
            getattr(mesh, 'remove_unreferenced_vertices', None)
        ):
            try:
                if fn:
                    fn()
            except Exception:
                pass
        
        # Center model at origin
        try:
            mesh.apply_translation(-mesh.center_mass)
        except Exception:
            pass
        
        # Normalize scale
        if normalize:
            try:
                bounds = mesh.bounds
                size = np.max(bounds[1] - bounds[0])
                if size > 0:
                    mesh.apply_scale(1.0 / size)
            except Exception:
                pass
        
        # Recompute normals
        try:
            trimesh.repair.fix_normals(mesh)
        except Exception:
            pass
        
        after_faces = len(mesh.faces)
        after_verts = len(mesh.vertices)
        
        # Save
        base, ext = os.path.splitext(self.current_model_path)
        suffix = "_optimized_norm" if normalize else "_optimized"
        out_path, _ = QFileDialog.getSaveFileName(self, "Save Optimized Mesh", f"{base}{suffix}{ext}",
                                                  "3D Models (*.obj *.stl *.ply *.glb *.gltf);;All Files (*)")
        if not out_path:
            return
        try:
            mesh.export(out_path)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save optimized mesh: {e}")
            return
        
        QMessageBox.information(self, "Optimize", f"Optimized model saved.\nVertices: {before_verts:,} -> {after_verts:,}\nFaces: {before_faces:,} -> {after_faces:,}\nSaved to: {out_path}")
        
        self.add_model_to_tree(out_path)
        self.load_model_in_viewer(out_path)