"""
Mesh Tools tab for PyMeshLab-based advanced mesh processing.
"""

import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
                             QPushButton, QComboBox, QLabel, QGroupBox, QFormLayout, 
                             QSpinBox, QDoubleSpinBox, QSlider, QTabWidget, QCheckBox,
                             QFrame, QGridLayout, QScrollArea, QTextEdit, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
                             QFileDialog, QMessageBox, QListWidget, QTreeWidget)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThreadPool
from PyQt6.QtGui import QFont, QColor

# Import mesh processor backend
from ..processing.mesh_processor import (
    MeshProcessor, MeshAnalyzer, MeshMeasure, MeshStatistics
)
from .unified_viewer import UnifiedOpen3DViewer
from ..utils.worker import Worker
from ..utils.run_teardown import drain
from .icon_provider import get_icon

class MeshToolsTab(QWidget):
    """Advanced mesh processing tools using PyMeshLab."""

    add_to_library_requested = pyqtSignal(str)
    
    mesh_processed = pyqtSignal(str)
    operation_completed = pyqtSignal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.threadpool = QThreadPool()
        self.mesh_processor = MeshProcessor()
        self.current_mesh = None
        self.current_model_path = None
        self.processing_history = []
        self.undo_steps = []
        self._pending_source = None
        self._pending_label = "Mesh operation"
        self._runs = []

        # Current model header
        # Initialize layout
        main_layout = QVBoxLayout(self)

        self.model_header = self.create_model_header()
        main_layout.addWidget(self.model_header)

        # Create main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Tools
        left_panel = self.create_left_panel()
        scroll_left = QScrollArea()
        scroll_left.setWidget(left_panel)
        scroll_left.setWidgetResizable(True)
        scroll_left.setFrameShape(QFrame.Shape.NoFrame)
        splitter.addWidget(scroll_left)

        # Right panel - Preview and results
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([380, 820])
        main_layout.addWidget(splitter)

    # ---- the one way a started run is held and released -------------------------

    def _keep_worker(self, worker):
        """Hold a started operation until the pool says it is done.

        Both paths here - the read-only measurements and `execute_async`, which every
        real mesh operation goes through - handed a local `Worker` to this pane's own
        pool and forgot it. Nothing was left that a close could take the handlers off of,
        and those handlers rewrite the mesh, the history list and the undo stack when the
        answer lands. The run releases itself through its own `finished`, so the list does
        not grow with every operation of a long session.
        """
        self._runs.append(worker)
        worker.signals.finished.connect(lambda: self._release_worker(worker))
        return worker

    def _release_worker(self, worker):
        """Let a run go when it says it is done - once, whoever else let go first.

        The removal is guarded because `shutdown_runs` releases the same worker on its way
        out; a second `list.remove` of it raises inside a slot, and PyQt answers an
        exception that escapes a slot by ending the process.
        """
        if worker in self._runs:
            self._runs.remove(worker)

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Silence every mesh operation in flight and wait for this pane's own pool.

        A pymeshlab filter on a real model runs for tens of seconds, and its answer is
        applied by reloading the result into the viewer, so a close that let it report
        would write into a destroyed viewer rather than merely print late. These are
        `QRunnable`s on a pool this pane owns, so there is no stop to ask of one and the
        pool answers only whether its queue drained - which, for a run longer than the
        wait, it has not. What has not drained stays in `_runs`.
        Returns the operations still owed when the wait gave up.
        """
        return len(drain(self._runs, timeout_ms, self.threadpool))

    def create_model_header(self):
        """Create the current model header."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setMaximumHeight(80)  # Increased height for explanation
        
        layout = QVBoxLayout(frame)
        
        # Main header layout
        header_layout = QHBoxLayout()
        
        self.current_model_label = QLabel("No mesh loaded")
        self.current_model_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        from .icon_provider import get_icon
        self.change_model_btn = QPushButton("Change Model")
        self.change_model_btn.setIcon(get_icon("folder"))
        self.change_model_btn.clicked.connect(self.select_and_load_model)
        self.add_model_btn = QPushButton("Add to Library")
        self.add_model_btn.setIcon(get_icon("add"))
        self.add_model_btn.clicked.connect(self.add_to_library)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setIcon(get_icon("refresh"))
        self.reload_btn.clicked.connect(lambda: self.load_mesh_file(self.current_model_path) if self.current_model_path else None)
        self.save_mesh_btn = QPushButton("Save Mesh")
        self.save_mesh_btn.setIcon(get_icon("backup"))
        self.save_mesh_btn.clicked.connect(self.save_mesh)
        
        header_layout.addWidget(self.current_model_label)
        header_layout.addStretch()
        header_layout.addWidget(self.change_model_btn)
        header_layout.addWidget(self.add_model_btn)
        header_layout.addWidget(self.reload_btn)
        header_layout.addWidget(self.save_mesh_btn)
        
        # Explanation text
        explanation = QLabel("Select a 3D model from the Library tab or load one above to process with advanced mesh tools")
        explanation.setStyleSheet("color: #8c93a8; font-size: 8.5pt;")
        explanation.setWordWrap(True)
        
        layout.addLayout(header_layout)
        layout.addWidget(explanation)
        
        return frame
        
    def create_left_panel(self):
        """Create the left tools panel."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Create tab widget for different tool categories
        self.tools_tabs = QTabWidget()
        
        # Repair tab
        repair_tab = self.create_repair_tab()
        self.tools_tabs.addTab(repair_tab, "Repair")
        
        # Simplify tab
        simplify_tab = self.create_simplify_tab()
        self.tools_tabs.addTab(simplify_tab, "Simplify")
        
        # Smooth tab
        smooth_tab = self.create_smooth_tab()
        self.tools_tabs.addTab(smooth_tab, "Smooth")
        
        # Remesh tab
        remesh_tab = self.create_remesh_tab()
        self.tools_tabs.addTab(remesh_tab, "Remesh")
        
        # Analysis tab
        analysis_tab = self.create_analysis_tab()
        self.tools_tabs.addTab(analysis_tab, "Analyze")
        
        # Transform tab
        transform_tab = self.create_transform_tab()
        self.tools_tabs.addTab(transform_tab, "Transform")
        
        layout.addWidget(self.tools_tabs)
        
        # Output Settings
        self.output_settings_group = self.create_output_settings()
        layout.addWidget(self.output_settings_group)
        
        # Progress section
        progress_group = QGroupBox("Operations")
        progress_layout = QVBoxLayout()
        
        self.operation_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        progress_layout.addWidget(self.operation_label)
        progress_layout.addWidget(self.progress_bar)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        return widget

    def create_output_settings(self):
        """Create output settings group."""
        group = QGroupBox("Output Settings")
        layout = QVBoxLayout()
        
        self.output_folder_combo = QComboBox()
        self.output_folder_combo.addItems(["Same Folder (Default)", "Create '_Processed' Subfolder"])
        self.output_folder_combo.setToolTip("Choose where to save processed files.")
        
        layout.addWidget(QLabel("Save Location:"))
        layout.addWidget(self.output_folder_combo)
        
        group.setLayout(layout)
        return group

    def get_output_path(self, original_path, suffix):
        """Generate output path based on settings."""
        directory = os.path.dirname(original_path)
        filename = os.path.basename(original_path)
        name, ext = os.path.splitext(filename)
        
        if self.output_folder_combo.currentIndex() == 1: # _Processed Subfolder
            directory = os.path.join(directory, "_Processed")
            if not os.path.exists(directory):
                try:
                    os.makedirs(directory)
                except OSError:
                    pass # Fallback to same folder if permission denied
        
        return os.path.join(directory, f"{name}{suffix}{ext}")
        
    def create_repair_tab(self):
        """Create mesh repair tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Hole filling
        holes_group = QGroupBox("Hole Filling")
        holes_layout = QVBoxLayout()
        
        # Close holes
        self.close_holes_btn = QPushButton("Close All Holes")
        self.close_holes_btn.setToolTip("Automatically detect and close all holes in the mesh.")
        self.close_holes_btn.clicked.connect(self.close_holes)
        self.close_small_holes_btn = QPushButton("Close Small Holes Only")
        self.close_small_holes_btn.setToolTip("Close holes smaller than the specified edge count.")
        self.close_small_holes_btn.clicked.connect(self.close_small_holes)
        
        holes_small_layout = QHBoxLayout()
        self.max_hole_size_spin = QSpinBox()
        self.max_hole_size_spin.setRange(3, 1000)
        self.max_hole_size_spin.setValue(30)
        holes_small_layout.addWidget(QLabel("Max Hole Size:"))
        holes_small_layout.addWidget(self.max_hole_size_spin)
        holes_small_layout.addWidget(QLabel("edges"))
        
        holes_layout.addWidget(self.close_holes_btn)
        holes_layout.addLayout(holes_small_layout)
        holes_layout.addWidget(self.close_small_holes_btn)
        
        holes_group.setLayout(holes_layout)
        layout.addWidget(holes_group)
        
        # Manifold repair
        manifold_group = QGroupBox("Manifold Repair")
        manifold_layout = QVBoxLayout()
        
        self.make_manifold_btn = QPushButton("Make Manifold")
        self.make_manifold_btn.setToolTip("Repair the mesh to make it watertight and manifold.")
        self.make_manifold_btn.clicked.connect(self.make_manifold)
        self.remove_non_manifold_btn = QPushButton("Remove Non-Manifold Edges")
        self.remove_non_manifold_btn.setToolTip("Remove edges that share more than two faces.")
        self.remove_non_manifold_btn.clicked.connect(self.remove_non_manifold_edges)
        self.remove_non_manifold_vertices_btn = QPushButton("Remove Non-Manifold Vertices")
        self.remove_non_manifold_vertices_btn.setToolTip("Remove vertices that connect non-manifold geometry.")
        self.remove_non_manifold_vertices_btn.clicked.connect(self.remove_non_manifold_vertices)
        
        manifold_layout.addWidget(self.make_manifold_btn)
        manifold_layout.addWidget(self.remove_non_manifold_btn)
        manifold_layout.addWidget(self.remove_non_manifold_vertices_btn)
        
        manifold_group.setLayout(manifold_layout)
        layout.addWidget(manifold_group)
        
        # Cleanup operations
        cleanup_group = QGroupBox("Cleanup")
        cleanup_layout = QVBoxLayout()
        
        self.remove_duplicates_btn = QPushButton("Remove Duplicate Vertices")
        self.remove_duplicates_btn.setToolTip("Merge vertices that are within the specified threshold.")
        self.remove_duplicates_btn.clicked.connect(self.remove_duplicate_vertices)
        self.remove_degenerate_btn = QPushButton("Remove Degenerate Faces")
        self.remove_degenerate_btn.setToolTip("Remove faces with zero area or duplicate vertices.")
        self.remove_degenerate_btn.clicked.connect(self.remove_degenerate_faces)
        self.remove_unreferenced_btn = QPushButton("Remove Unreferenced Vertices")
        self.remove_unreferenced_btn.setToolTip("Remove vertices that are not part of any face.")
        self.remove_unreferenced_btn.clicked.connect(self.remove_unreferenced_vertices)
        self.fix_normals_btn = QPushButton("Fix Face Normals")
        self.fix_normals_btn.setToolTip("Unify face normals to point outwards.")
        self.fix_normals_btn.clicked.connect(self.fix_face_normals)
        self.invert_normals_btn = QPushButton("Invert All Normals")
        self.invert_normals_btn.setToolTip("Flip the direction of all face normals.")
        self.invert_normals_btn.clicked.connect(self.invert_normals)
        
        cleanup_layout.addWidget(self.remove_duplicates_btn)
        cleanup_layout.addWidget(self.remove_degenerate_btn)
        cleanup_layout.addWidget(self.remove_unreferenced_btn)
        cleanup_layout.addWidget(self.fix_normals_btn)
        cleanup_layout.addWidget(self.invert_normals_btn)
        
        cleanup_group.setLayout(cleanup_layout)
        layout.addWidget(cleanup_group)
        
        # Duplicate threshold
        threshold_layout = QHBoxLayout()
        self.duplicate_threshold_spin = QDoubleSpinBox()
        self.duplicate_threshold_spin.setRange(0.0001, 1.0)
        self.duplicate_threshold_spin.setValue(0.0001)
        self.duplicate_threshold_spin.setDecimals(6)
        threshold_layout.addWidget(QLabel("Duplicate Threshold:"))
        threshold_layout.addWidget(self.duplicate_threshold_spin)
        layout.addLayout(threshold_layout)
        
        layout.addStretch()
        return scroll
        
    def create_simplify_tab(self):
        """Create mesh simplification tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Quadric edge collapse
        quadric_group = QGroupBox("Quadric Edge Collapse")
        quadric_layout = QFormLayout()
        
        self.target_faces_spin = QSpinBox()
        self.target_faces_spin.setRange(100, 10000000)
        self.target_faces_spin.setValue(5000)
        
        self.target_percentage_spin = QDoubleSpinBox()
        self.target_percentage_spin.setRange(1.0, 100.0)
        self.target_percentage_spin.setValue(50.0)
        self.target_percentage_spin.setSuffix("%")
        
        self.quality_threshold_spin = QDoubleSpinBox()
        self.quality_threshold_spin.setRange(0.1, 1.0)
        self.quality_threshold_spin.setValue(0.3)
        self.quality_threshold_spin.setSingleStep(0.1)
        
        self.preserve_boundary_cb = QCheckBox("Preserve Boundary")
        self.preserve_boundary_cb.setChecked(True)
        
        self.preserve_normal_cb = QCheckBox("Preserve Normal")
        self.preserve_normal_cb.setChecked(True)
        
        self.preserve_topology_cb = QCheckBox("Preserve Topology")
        self.preserve_topology_cb.setChecked(False)
        
        self.percentage_target_cb = QCheckBox("Use Target Percentage")
        self.percentage_target_cb.setToolTip(
            "Reduce by a percentage of the original face count instead of an absolute target.")
        self.percentage_target_cb.setChecked(False)
        
        quadric_layout.addRow("Target Faces:", self.target_faces_spin)
        quadric_layout.addRow(self.percentage_target_cb)
        quadric_layout.addRow("Target Percentage:", self.target_percentage_spin)
        quadric_layout.addRow("Quality Threshold:", self.quality_threshold_spin)
        quadric_layout.addRow(self.preserve_boundary_cb)
        quadric_layout.addRow(self.preserve_normal_cb)
        quadric_layout.addRow(self.preserve_topology_cb)
        
        self.percentage_target_cb.toggled.connect(self.on_percentage_target_toggled)
        self.on_percentage_target_toggled(False)
        
        self.simplify_quadric_btn = QPushButton("Apply Quadric Simplification")
        self.simplify_quadric_btn.setToolTip("Reduce face count using Quadric Error Metrics (high quality).")
        self.simplify_quadric_btn.clicked.connect(self.simplify_quadric)
        
        quadric_group.setLayout(quadric_layout)
        layout.addWidget(quadric_group)
        layout.addWidget(self.simplify_quadric_btn)
        
        # Clustering decimation
        cluster_group = QGroupBox("Clustering Decimation")
        cluster_layout = QFormLayout()
        
        self.cluster_threshold_spin = QDoubleSpinBox()
        self.cluster_threshold_spin.setRange(0.001, 1.0)
        self.cluster_threshold_spin.setValue(0.05)
        self.cluster_threshold_spin.setSingleStep(0.001)
        
        cluster_layout.addRow("Cluster Threshold:", self.cluster_threshold_spin)
        
        self.simplify_cluster_btn = QPushButton("Apply Clustering Decimation")
        self.simplify_cluster_btn.setToolTip("Reduce face count by clustering vertices (fast, lower quality).")
        self.simplify_cluster_btn.clicked.connect(self.simplify_cluster)
        
        cluster_group.setLayout(cluster_layout)
        layout.addWidget(cluster_group)
        layout.addWidget(self.simplify_cluster_btn)
        
        # Planar simplification
        planar_group = QGroupBox("Planar Simplification")
        planar_layout = QFormLayout()
        
        self.planar_target_faces_spin = QSpinBox()
        self.planar_target_faces_spin.setRange(100, 10000000)
        self.planar_target_faces_spin.setValue(5000)
        
        self.planar_angle_spin = QDoubleSpinBox()
        self.planar_angle_spin.setRange(0.1, 30.0)
        self.planar_angle_spin.setValue(1.0)
        self.planar_angle_spin.setSuffix("°")
        
        planar_layout.addRow("Target Faces:", self.planar_target_faces_spin)
        planar_layout.addRow("Angle Threshold:", self.planar_angle_spin)
        
        self.simplify_planar_btn = QPushButton("Apply Planar Simplification")
        self.simplify_planar_btn.setToolTip("Reduce face count on flat surfaces.")
        self.simplify_planar_btn.clicked.connect(self.simplify_planar)
        
        planar_group.setLayout(planar_layout)
        layout.addWidget(planar_group)
        layout.addWidget(self.simplify_planar_btn)
        
        layout.addStretch()
        return scroll
        
    def create_smooth_tab(self):
        """Create mesh smoothing tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Laplacian smoothing
        laplacian_group = QGroupBox("Laplacian Smoothing")
        laplacian_layout = QFormLayout()
        
        self.laplacian_steps_spin = QSpinBox()
        self.laplacian_steps_spin.setRange(1, 50)
        self.laplacian_steps_spin.setValue(3)
        
        self.laplacian_boundary_cb = QCheckBox("Smooth Boundary")
        self.laplacian_boundary_cb.setChecked(False)
        
        laplacian_layout.addRow("Smoothing Steps:", self.laplacian_steps_spin)
        laplacian_layout.addRow(self.laplacian_boundary_cb)
        
        self.smooth_laplacian_btn = QPushButton("Apply Laplacian Smoothing")
        
        self.smooth_laplacian_btn.clicked.connect(self.smooth_laplacian)
        laplacian_group.setLayout(laplacian_layout)
        layout.addWidget(laplacian_group)
        layout.addWidget(self.smooth_laplacian_btn)
        
        # Taubin smoothing
        taubin_group = QGroupBox("Taubin Smoothing")
        taubin_layout = QFormLayout()
        
        self.taubin_lambda_spin = QDoubleSpinBox()
        self.taubin_lambda_spin.setRange(0.01, 1.0)
        self.taubin_lambda_spin.setValue(0.5)
        self.taubin_lambda_spin.setSingleStep(0.01)
        
        self.taubin_mu_spin = QDoubleSpinBox()
        self.taubin_mu_spin.setRange(-1.0, -0.01)
        self.taubin_mu_spin.setValue(-0.53)
        self.taubin_mu_spin.setSingleStep(0.01)
        
        self.taubin_steps_spin = QSpinBox()
        self.taubin_steps_spin.setRange(1, 50)
        self.taubin_steps_spin.setValue(10)
        
        taubin_layout.addRow("Lambda:", self.taubin_lambda_spin)
        taubin_layout.addRow("Mu:", self.taubin_mu_spin)
        taubin_layout.addRow("Steps:", self.taubin_steps_spin)
        
        self.smooth_taubin_btn = QPushButton("Apply Taubin Smoothing")
        
        self.smooth_taubin_btn.clicked.connect(self.smooth_taubin)
        taubin_group.setLayout(taubin_layout)
        layout.addWidget(taubin_group)
        layout.addWidget(self.smooth_taubin_btn)
        
        # Depth smoothing
        depth_group = QGroupBox("Depth Smoothing")
        depth_layout = QFormLayout()
        
        self.depth_steps_spin = QSpinBox()
        self.depth_steps_spin.setRange(1, 20)
        self.depth_steps_spin.setValue(3)
        
        self.depth_threshold_spin = QDoubleSpinBox()
        self.depth_threshold_spin.setRange(1.0, 100.0)
        self.depth_threshold_spin.setValue(100.0)
        self.depth_threshold_spin.setSuffix("%")
        self.depth_threshold_spin.setSingleStep(0.1)
        
        depth_layout.addRow("Smoothing Steps:", self.depth_steps_spin)
        depth_layout.addRow("Delta Strength:", self.depth_threshold_spin)
        
        self.smooth_depth_btn = QPushButton("Apply Depth Smoothing")
        
        self.smooth_depth_btn.clicked.connect(self.smooth_depth)
        depth_group.setLayout(depth_layout)
        layout.addWidget(depth_group)
        layout.addWidget(self.smooth_depth_btn)
        
        layout.addStretch()
        return scroll
        
    def create_remesh_tab(self):
        """Create remeshing tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Uniform remeshing
        uniform_group = QGroupBox("Uniform Remeshing")
        uniform_layout = QFormLayout()
        
        self.target_length_spin = QDoubleSpinBox()
        self.target_length_spin.setRange(0.001, 10.0)
        self.target_length_spin.setValue(0.1)
        self.target_length_spin.setSingleStep(0.001)
        
        self.iterations_spin = QSpinBox()
        self.iterations_spin.setRange(1, 20)
        self.iterations_spin.setValue(3)
        
        self.adaptive_cb = QCheckBox("Adaptive Size")
        self.adaptive_cb.setChecked(True)
        
        uniform_layout.addRow("Target Edge Length:", self.target_length_spin)
        uniform_layout.addRow("Iterations:", self.iterations_spin)
        uniform_layout.addRow(self.adaptive_cb)
        
        self.remesh_uniform_btn = QPushButton("Apply Uniform Remeshing")
        
        self.remesh_uniform_btn.clicked.connect(self.remesh_uniform)
        uniform_group.setLayout(uniform_layout)
        layout.addWidget(uniform_group)
        layout.addWidget(self.remesh_uniform_btn)
        
        # Voronoi remeshing
        voronoi_group = QGroupBox("Voronoi Remeshing")
        voronoi_layout = QFormLayout()
        
        self.voronoi_threshold_spin = QDoubleSpinBox()
        self.voronoi_threshold_spin.setRange(0.0, 2000.0)
        self.voronoi_threshold_spin.setValue(10.0)
        self.voronoi_threshold_spin.setSingleStep(1.0)
        self.voronoi_threshold_spin.setToolTip(
            "Planarity threshold for the Voronoi-based decimation. 0 keeps every facet.")
        
        voronoi_layout.addRow("Planarity Threshold:", self.voronoi_threshold_spin)
        
        self.remesh_voronoi_btn = QPushButton("Apply Voronoi Remeshing")
        
        self.remesh_voronoi_btn.clicked.connect(self.remesh_voronoi)
        voronoi_group.setLayout(voronoi_layout)
        layout.addWidget(voronoi_group)
        layout.addWidget(self.remesh_voronoi_btn)
        
        # Loop subdivision
        subdivision_group = QGroupBox("Subdivision")
        subdivision_layout = QFormLayout()
        
        self.subdivision_type_combo = QComboBox()
        self.subdivision_type_combo.addItems(["Loop", "Catmull-Clark", "Butterfly"])
        
        self.subdivision_levels_spin = QSpinBox()
        self.subdivision_levels_spin.setRange(1, 4)
        self.subdivision_levels_spin.setValue(1)
        
        subdivision_layout.addRow("Type:", self.subdivision_type_combo)
        subdivision_layout.addRow("Levels:", self.subdivision_levels_spin)
        
        self.apply_subdivision_btn = QPushButton("Apply Subdivision")
        
        self.apply_subdivision_btn.clicked.connect(self.apply_subdivision)
        subdivision_group.setLayout(subdivision_layout)
        layout.addWidget(subdivision_group)
        layout.addWidget(self.apply_subdivision_btn)
        
        layout.addStretch()
        return scroll
        
    def create_analysis_tab(self):
        """Create mesh analysis tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Quality metrics
        quality_group = QGroupBox("Quality Metrics")
        quality_layout = QVBoxLayout()
        
        self.compute_quality_btn = QPushButton("Compute Mesh Quality")
        self.quality_histogram_btn = QPushButton("Show Quality Histogram")
        
        self.quality_results = QTextEdit()
        self.quality_results.setMaximumHeight(120)
        self.quality_results.setReadOnly(True)
        
        self.compute_quality_btn.clicked.connect(self.compute_mesh_quality)
        self.quality_histogram_btn.clicked.connect(self.show_quality_histogram)
        
        quality_layout.addWidget(self.compute_quality_btn)
        quality_layout.addWidget(self.quality_histogram_btn)
        quality_layout.addWidget(self.quality_results)
        
        quality_group.setLayout(quality_layout)
        layout.addWidget(quality_group)
        
        # Geometric measurements
        measurements_group = QGroupBox("Measurements")
        measurements_layout = QVBoxLayout()
        
        self.compute_volume_btn = QPushButton("Compute Volume")
        self.compute_area_btn = QPushButton("Compute Surface Area")
        self.compute_curvature_btn = QPushButton("Compute Curvature")
        self.geometric_info_btn = QPushButton("Geometric Information")
        
        self.compute_volume_btn.clicked.connect(self.compute_volume)
        self.compute_area_btn.clicked.connect(self.compute_surface_area)
        self.compute_curvature_btn.clicked.connect(self.compute_curvature)
        self.geometric_info_btn.clicked.connect(self.show_geometric_info)
        
        measurements_layout.addWidget(self.compute_volume_btn)
        measurements_layout.addWidget(self.compute_area_btn)
        measurements_layout.addWidget(self.compute_curvature_btn)
        measurements_layout.addWidget(self.geometric_info_btn)
        
        measurements_group.setLayout(measurements_layout)
        layout.addWidget(measurements_group)
        
        # Topology analysis
        topology_group = QGroupBox("Topology Analysis")
        topology_layout = QVBoxLayout()
        
        self.check_manifold_btn = QPushButton("Check Manifold")
        self.check_watertight_btn = QPushButton("Check Watertight")
        self.count_components_btn = QPushButton("Count Components")
        self.find_holes_btn = QPushButton("Find Holes")
        
        self.check_manifold_btn.clicked.connect(self.check_manifold)
        self.check_watertight_btn.clicked.connect(self.check_watertight)
        self.count_components_btn.clicked.connect(self.count_components)
        self.find_holes_btn.clicked.connect(self.find_holes)
        
        topology_layout.addWidget(self.check_manifold_btn)
        topology_layout.addWidget(self.check_watertight_btn)
        topology_layout.addWidget(self.count_components_btn)
        topology_layout.addWidget(self.find_holes_btn)
        
        topology_group.setLayout(topology_layout)
        layout.addWidget(topology_group)
        
        layout.addStretch()
        return scroll
        
    def create_transform_tab(self):
        """Create transformation tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Basic transforms
        basic_group = QGroupBox("Basic Transformations")
        basic_layout = QFormLayout()
        
        # Translation
        trans_layout = QHBoxLayout()
        self.trans_x_spin = QDoubleSpinBox()
        self.trans_x_spin.setRange(-1000, 1000)
        self.trans_y_spin = QDoubleSpinBox()
        self.trans_y_spin.setRange(-1000, 1000)
        self.trans_z_spin = QDoubleSpinBox()
        self.trans_z_spin.setRange(-1000, 1000)
        
        trans_layout.addWidget(self.trans_x_spin)
        trans_layout.addWidget(self.trans_y_spin)
        trans_layout.addWidget(self.trans_z_spin)
        
        # Rotation
        rot_layout = QHBoxLayout()
        self.rot_x_spin = QDoubleSpinBox()
        self.rot_x_spin.setRange(-180, 180)
        self.rot_x_spin.setSuffix("°")
        self.rot_y_spin = QDoubleSpinBox()
        self.rot_y_spin.setRange(-180, 180)
        self.rot_y_spin.setSuffix("°")
        self.rot_z_spin = QDoubleSpinBox()
        self.rot_z_spin.setRange(-180, 180)
        self.rot_z_spin.setSuffix("°")
        
        rot_layout.addWidget(self.rot_x_spin)
        rot_layout.addWidget(self.rot_y_spin)
        rot_layout.addWidget(self.rot_z_spin)
        
        # Scale
        scale_layout = QHBoxLayout()
        self.scale_x_spin = QDoubleSpinBox()
        self.scale_x_spin.setRange(0.01, 100)
        self.scale_x_spin.setValue(1.0)
        self.scale_y_spin = QDoubleSpinBox()
        self.scale_y_spin.setRange(0.01, 100)
        self.scale_y_spin.setValue(1.0)
        self.scale_z_spin = QDoubleSpinBox()
        self.scale_z_spin.setRange(0.01, 100)
        self.scale_z_spin.setValue(1.0)
        
        self.uniform_scale_cb = QCheckBox("Uniform")
        self.uniform_scale_cb.setChecked(True)
        
        scale_layout.addWidget(self.scale_x_spin)
        scale_layout.addWidget(self.scale_y_spin)
        scale_layout.addWidget(self.scale_z_spin)
        scale_layout.addWidget(self.uniform_scale_cb)
        
        basic_layout.addRow("Translation (X,Y,Z):", trans_layout)
        basic_layout.addRow("Rotation (X,Y,Z):", rot_layout)
        basic_layout.addRow("Scale (X,Y,Z):", scale_layout)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # Transform buttons
        transform_buttons = QHBoxLayout()
        self.apply_transform_btn = QPushButton("Apply Transform")
        self.apply_transform_btn.clicked.connect(self.apply_transform)
        self.reset_transform_btn = QPushButton("Reset")
        self.reset_transform_btn.clicked.connect(self.reset_transform)
        transform_buttons.addWidget(self.apply_transform_btn)
        transform_buttons.addWidget(self.reset_transform_btn)
        layout.addLayout(transform_buttons)
        
        # Special operations
        special_group = QGroupBox("Special Operations")
        special_layout = QVBoxLayout()
        
        self.center_mesh_btn = QPushButton("Center Mesh")
        self.center_mesh_btn.clicked.connect(self.center_mesh)
        self.normalize_size_btn = QPushButton("Normalize Size")
        self.normalize_size_btn.clicked.connect(self.normalize_size)
        self.flip_normals_btn = QPushButton("Flip Normals")
        self.flip_normals_btn.clicked.connect(self.invert_normals) # Reusing existing method
        self.auto_align_btn = QPushButton("Auto-Align to Axes")
        self.auto_align_btn.setToolTip("Automatically align mesh using Principal Component Analysis (PCA)")
        self.auto_align_btn.clicked.connect(self.auto_align_mesh)
        self.matrix_transform_btn = QPushButton("Matrix Transform...")
        self.matrix_transform_btn.clicked.connect(self.matrix_transform)
        
        special_layout.addWidget(self.center_mesh_btn)
        special_layout.addWidget(self.normalize_size_btn)
        special_layout.addWidget(self.flip_normals_btn)
        special_layout.addWidget(self.auto_align_btn)
        special_layout.addWidget(self.matrix_transform_btn)
        
        special_group.setLayout(special_layout)
        layout.addWidget(special_group)
        
        layout.addStretch()
        return scroll
        
    def create_right_panel(self):
        """Create the right panel with preview and results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Create tab widget
        self.right_tabs = QTabWidget()
        
        # Preview tab
        preview_tab = self.create_preview_tab()
        self.right_tabs.addTab(preview_tab, "Preview")
        
        # Information tab
        info_tab = self.create_info_tab()
        self.right_tabs.addTab(info_tab, "Information")
        
        # History tab
        history_tab = self.create_history_tab()
        self.right_tabs.addTab(history_tab, "History")
        
        # Export tab
        export_tab = self.create_export_tab()
        self.right_tabs.addTab(export_tab, "Export")
        
        layout.addWidget(self.right_tabs)
        
        return widget
        
    def create_preview_tab(self):
        """Create mesh preview interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Preview placeholder
        self.viewer = UnifiedOpen3DViewer()
        layout.addWidget(self.viewer)
        
        # Preview controls
        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)
        
        self.wireframe_cb = QCheckBox("Wireframe")
        self.wireframe_cb.toggled.connect(lambda c: self.viewer.set_show_wireframe(c))
        
        self.show_edges_cb = QCheckBox("Show Edges")
        self.show_edges_cb.toggled.connect(lambda c: self.viewer.set_show_edges(c))
        
        self.show_normals_cb = QCheckBox("Show Normals")
        self.show_normals_cb.toggled.connect(lambda c: self.viewer.set_show_normals(c))
        
        self.show_colors_cb = QCheckBox("Show Colors")
        self.show_colors_cb.setChecked(True)
        self.show_colors_cb.toggled.connect(lambda c: self.viewer.set_show_colors(c))
        
        self.reset_view_btn = QPushButton("Reset View")
        self.reset_view_btn.setIcon(get_icon("reset_view"))
        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.setIcon(get_icon("camera"))
        
        self.reset_view_btn.clicked.connect(self.reset_view)
        self.screenshot_btn.clicked.connect(self.take_screenshot)
        
        controls_layout.addWidget(self.wireframe_cb)
        controls_layout.addWidget(self.show_edges_cb)
        controls_layout.addWidget(self.show_normals_cb)
        controls_layout.addWidget(self.show_colors_cb)
        controls_layout.addStretch()
        controls_layout.addWidget(self.reset_view_btn)
        controls_layout.addWidget(self.screenshot_btn)
        
        layout.addWidget(controls_frame)
        
        return widget
        
    def create_info_tab(self):
        """Create mesh information display."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Basic info
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        
        self.info_filename = QLabel("No mesh loaded")
        self.info_vertices = QLabel("-")
        self.info_faces = QLabel("-")
        self.info_edges = QLabel("-")
        self.info_components = QLabel("-")
        self.info_manifold = QLabel("-")
        self.info_watertight = QLabel("-")
        
        basic_layout.addRow("Filename:", self.info_filename)
        basic_layout.addRow("Vertices:", self.info_vertices)
        basic_layout.addRow("Faces:", self.info_faces)
        basic_layout.addRow("Edges:", self.info_edges)
        basic_layout.addRow("Components:", self.info_components)
        basic_layout.addRow("Manifold:", self.info_manifold)
        basic_layout.addRow("Watertight:", self.info_watertight)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # Detailed analysis
        analysis_group = QGroupBox("Detailed Analysis")
        analysis_layout = QVBoxLayout()
        
        self.detailed_analysis = QTextEdit()
        self.detailed_analysis.setReadOnly(True)
        self.detailed_analysis.setMaximumHeight(200)
        
        analysis_layout.addWidget(self.detailed_analysis)
        
        analysis_group.setLayout(analysis_layout)
        layout.addWidget(analysis_group)
        
        layout.addStretch()
        return widget
        
    def create_history_tab(self):
        """Create processing history display."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # History list
        history_group = QGroupBox("Processing History")
        history_layout = QVBoxLayout()
        
        self.history_list = QListWidget()
        self.clear_history_btn = QPushButton("Clear History")
        self.undo_last_btn = QPushButton("Undo Last Operation")
        
        self.clear_history_btn.clicked.connect(self.clear_history)
        self.undo_last_btn.clicked.connect(self.undo_last)
        
        history_layout.addWidget(self.history_list)
        
        history_buttons = QHBoxLayout()
        history_buttons.addWidget(self.undo_last_btn)
        history_buttons.addWidget(self.clear_history_btn)
        history_layout.addLayout(history_buttons)
        
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)
        
        layout.addStretch()
        return widget
        
    def create_export_tab(self):
        """Create export options."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Export formats
        export_group = QGroupBox("Export Formats")
        export_layout = QGridLayout()
        
        self.export_obj_btn = QPushButton("Export OBJ")
        self.export_ply_btn = QPushButton("Export PLY")
        self.export_stl_btn = QPushButton("Export STL")
        self.export_off_btn = QPushButton("Export OFF")
        
        self.export_obj_btn.clicked.connect(lambda: self.export_to_format(".obj"))
        self.export_ply_btn.clicked.connect(lambda: self.export_to_format(".ply"))
        self.export_stl_btn.clicked.connect(lambda: self.export_to_format(".stl"))
        self.export_off_btn.clicked.connect(lambda: self.export_to_format(".off"))
        
        export_layout.addWidget(self.export_obj_btn, 0, 0)
        export_layout.addWidget(self.export_ply_btn, 0, 1)
        export_layout.addWidget(self.export_stl_btn, 1, 0)
        export_layout.addWidget(self.export_off_btn, 1, 1)
        
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)
        
        # Export options
        options_group = QGroupBox("Export Options")
        options_layout = QFormLayout()
        
        self.export_normals_cb = QCheckBox("Include Normals")
        self.export_normals_cb.setToolTip("Written as vn lines in OBJ; other formats recompute normals.")
        self.export_textures_cb = QCheckBox("Include Textures")
        self.export_textures_cb.setToolTip("Unchecking drops UVs and the material file.")
        self.export_colors_cb = QCheckBox("Include Vertex Colors")
        
        options_layout.addRow(self.export_normals_cb)
        options_layout.addRow(self.export_textures_cb)
        options_layout.addRow(self.export_colors_cb)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        layout.addStretch()
        return widget

    def compute_mesh_quality(self):
        """Compute mesh quality metrics using backend."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Computing mesh quality...")
        
        try:
            # Use mesh processor to analyze
            stats = self.mesh_processor.analyze(self.current_model_path)
            
            if stats:
                quality_text = f"""Mesh Statistics:

Vertices: {stats.vertices:,}
Faces: {stats.faces:,}
Edges: {stats.edges:,}

Topology:
✓ Watertight: {'Yes' if stats.is_watertight else 'No'}
✓ Manifold: {'Yes' if stats.is_manifold else 'No'}

Geometry:
Volume: {stats.volume:.4f} cubic units
Surface Area: {stats.surface_area:.4f} square units
Bounding Box: {stats.bounding_box}

Attributes:
Textures: {'Yes' if stats.has_textures else 'No'}
Normals: {'Yes' if stats.has_normals else 'No'}
Colors: {'Yes' if stats.has_colors else 'No'}"""
                
                self.quality_results.setPlainText(quality_text)
                
                # Update info tab
                self.info_vertices.setText(f"{stats.vertices:,}")
                self.info_faces.setText(f"{stats.faces:,}")
                self.info_edges.setText(f"{stats.edges:,}")
                self.info_manifold.setText("Yes" if stats.is_manifold else "No")
                self.info_watertight.setText("Yes" if stats.is_watertight else "No")
                
                self.operation_label.setText("Quality metrics computed")
            else:
                QMessageBox.warning(self, "Error", "Failed to analyze mesh")
        except Exception as e:
            self.operation_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to compute quality: {str(e)}")
            
    def check_manifold(self):
        """Check if mesh is manifold."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Checking manifold...")
        
        try:
            # Detect issues
            issues = self.mesh_processor.detect_issues(self.current_model_path)
            
            if issues:
                issues_text = "Detected Issues:\n\n"
                for issue in issues:
                    severity = issue.get('severity', 'Unknown')
                    desc = issue.get('description', 'No description')
                    fix = issue.get('fix', 'No fix available')
                    issues_text += f"[{severity}] {desc}\n  → Fix: {fix}\n\n"
                
                self.detailed_analysis.setPlainText(issues_text)
                self.operation_label.setText(f"Found {len(issues)} issue(s)")
                QMessageBox.warning(self, "Issues Found",
                                    f"Found {len(issues)} issue(s). Check Detailed Analysis.")
            else:
                self.detailed_analysis.setPlainText("No issues detected.")
                self.operation_label.setText("No issues detected")
                QMessageBox.information(self, "Success", "Mesh has no detectable issues!")
        except Exception as e:
            self.operation_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to check manifold: {str(e)}")

    def run_measurement(self, label, measure, format_result):
        """Run a read-only measurement off the UI thread and show its report."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return

        self.operation_label.setText(f"{label}...")
        self.progress_bar.setVisible(True)
        model_path = self.current_model_path

        def worker_func(progress_callback=None):
            return measure(model_path)

        def show_result(result):
            self.detailed_analysis.setPlainText(format_result(result))

        worker = Worker(worker_func)
        worker.signals.result.connect(show_result)
        worker.signals.error.connect(self.on_operation_error)
        worker.signals.finished.connect(self.on_measurement_finished)
        self._keep_worker(worker)
        self.threadpool.start(worker)

    def on_measurement_finished(self):
        """Finish a read-only measurement without reloading the mesh."""
        self.progress_bar.setVisible(False)
        self.operation_label.setText("Measurement complete")

    @staticmethod
    def _requirement(result):
        """Return the backend error as a report when a measurement failed."""
        if result.get('success'):
            return None
        return f"Measurement failed: {result.get('error', 'Unknown error')}"

    @staticmethod
    def _histogram(counts, edges, width=34):
        """Render a measurement distribution as text bars."""
        peak = max(counts) if counts else 0
        lines = []
        for i, count in enumerate(counts):
            bar = "#" * (int(round(count / peak * width)) if peak else 0)
            lines.append(f"{edges[i]:.2f}-{edges[i + 1]:.2f} | {bar} {count:,}")
        return "\n".join(lines)

    def show_quality_histogram(self):
        """Face-shape quality distribution using inradius/circumradius."""
        self.run_measurement(
            "Measuring face quality",
            MeshMeasure.face_quality,
            lambda r: self._format_quality(r)
        )

    def _format_quality(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        stats = result['statistics']
        total = result['total_faces']
        good = result['good_faces']
        poor = result['poor_faces']
        return (
            "Face shape quality (1.00 = equilateral, 0.00 = collapsed)\n\n"
            f"Faces measured: {total:,}\n"
            f"Average quality: {stats['avg']:.3f}\n"
            f"Median quality:  {stats['med']:.3f}\n"
            f"Worst quality:   {stats['min']:.4f}\n\n"
            f"Good (>= 0.50): {good:,} ({good / total:.1%})\n"
            f"Poor (< 0.20):  {poor:,} ({poor / total:.1%})\n\n"
            + self._histogram(result['counts'], result['edges'])
        )

    def compute_volume(self):
        """Mesh volume, with the watertight guarantee the number depends on."""
        self.run_measurement("Computing volume", MeshMeasure.measurements,
                             self._format_volume)

    def _format_volume(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        note = ("Watertight: the volume is the enclosed solid."
                if result['is_watertight'] else
                "Not watertight: volume is computed on the open shell and will be wrong.")
        return (f"Volume: {result['volume']:.6f} cubic units\n"
                f"Surface area: {result['surface_area']:.6f} square units\n"
                f"Holes: {result['hole_count']}\n\n{note}")

    def compute_surface_area(self):
        """Total triangle area."""
        self.run_measurement("Computing surface area", MeshMeasure.measurements,
                             self._format_area)

    def _format_area(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        faces = result['faces']
        lines = [f"Surface area: {result['surface_area']:.6f} square units",
                 f"Faces: {faces:,}"]
        if faces:
            lines.append(f"Average face area: {result['surface_area'] / faces:.8f}")
        return "\n".join(lines)

    def compute_curvature(self):
        """Discrete mean and Gaussian curvature statistics."""
        self.run_measurement("Computing curvature", MeshMeasure.curvature,
                             self._format_curvature)

    def _format_curvature(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        lines = ["Discrete curvature per vertex\n"]
        for key, name in (('mean', 'Mean curvature'), ('gaussian', 'Gaussian curvature')):
            stats = result[key]
            lines.append(
                f"{name}:\n"
                f"  min  {stats['min']:.5f}\n"
                f"  mean {stats['avg']:.5f}\n"
                f"  max  {stats['max']:.5f}\n"
                f"  std  {stats['stddev']:.5f}\n"
            )
        lines.append("Sharp edges show up as large spreads between min and max.")
        return "\n".join(lines)

    def show_geometric_info(self):
        """Bounding box, extents, centroid and topology."""
        self.run_measurement("Gathering geometry", MeshMeasure.measurements,
                             self._format_geometry)

    def _format_geometry(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        return (
            "Geometric information\n\n"
            f"Vertices: {result['vertices']:,}   Faces: {result['faces']:,}   "
            f"Edges: {result['edges']:,}\n"
            f"Extents: {result['extents'][0]:.4f} x {result['extents'][1]:.4f} x "
            f"{result['extents'][2]:.4f}\n"
            f"Min corner:  {result['min_bound']}\n"
            f"Max corner:  {result['max_bound']}\n"
            f"Centroid:    {result['centroid']}\n"
            f"Euler number: {result['euler_number']}   Bodies: {result['body_count']}\n"
            f"Watertight: {'Yes' if result['is_watertight'] else 'No'}   "
            f"Holes: {result['hole_count']}"
        )

    def check_watertight(self):
        """Whether the mesh encloses a solid."""
        self.run_measurement("Checking watertightness", MeshMeasure.measurements,
                             self._format_watertight)

    def _format_watertight(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        if result['is_watertight']:
            return "Mesh is watertight: every edge is shared by exactly two faces."
        return (
            f"Mesh is NOT watertight.\n\n"
            f"Open edge loops (holes): {result['hole_count']}\n"
            f"Hole sizes (vertices): {result['hole_sizes'][:20]}"
        )

    def count_components(self):
        """Disconnected bodies and how big each one is."""
        self.run_measurement("Counting components", MeshMeasure.components,
                             self._format_components)

    def _format_components(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        bodies = sorted(result['components'], key=lambda b: b['faces'], reverse=True)
        lines = [f"Disconnected bodies: {result['body_count']}\n"]
        for body in bodies[:25]:
            lines.append(
                f"Body {body['index']}: {body['faces']:,} faces, "
                f"{body['volume']:.4f} volume, "
                f"{'watertight' if body['watertight'] else 'open'}"
            )
        if len(bodies) > 25:
            lines.append(f"... and {len(bodies) - 25} more")
        return "\n".join(lines)

    def find_holes(self):
        """Open edge loops, largest first."""
        self.run_measurement("Finding holes", MeshMeasure.measurements,
                             self._format_holes)

    def _format_holes(self, result):
        failed = self._requirement(result)
        if failed:
            return failed
        sizes = sorted(result['hole_sizes'], reverse=True)
        if not sizes:
            return "No holes found: every edge is shared by two faces."
        return (
            f"Holes found: {len(sizes)}\n"
            f"Largest hole: {sizes[0]} boundary vertices\n"
            f"Smallest hole: {sizes[-1]} boundary vertices\n\n"
            f"Loop sizes (vertices): {sizes[:30]}"
            + ("\n... showing 30 largest" if len(sizes) > 30 else "")
        )

    def on_uniform_scale_toggled(self, checked):
        """Handle uniform scale checkbox."""
        if checked:
            # Sync all scale values to X
            x_val = self.scale_x_spin.value()
            self.scale_y_spin.setValue(x_val)
            self.scale_z_spin.setValue(x_val)
            
            # Connect signals to sync
            self.scale_x_spin.valueChanged.connect(self.sync_uniform_scale)
        else:
            # Disconnect sync signals
            try:
                self.scale_x_spin.valueChanged.disconnect(self.sync_uniform_scale)
            except:
                pass
                
    def sync_uniform_scale(self, value):
        """Sync scale values when uniform scaling is enabled."""
        if self.uniform_scale_cb.isChecked():
            self.scale_y_spin.setValue(value)
            self.scale_z_spin.setValue(value)
            
    def add_to_history(self, operation):
        """Add operation to processing history."""
        self.processing_history.append(operation)
        self.history_list.addItem(f"{len(self.processing_history)}. {operation}")
        
    def get_current_model(self):
        """Get the current model path."""
        return self.current_model_path
        
    def set_current_model(self, model_path):
        """Set the current model from library selection.""" 
        if model_path and model_path.lower().endswith(('.obj', '.ply', '.stl', '.off')):
            self.load_model(model_path)
            
    def load_model(self, file_path):
        """Load a model for processing."""
        if not os.path.exists(file_path):
            return
            
        self.current_model_path = file_path
        self.current_model_label.setText(os.path.basename(file_path))
        
        # Load mesh for processing
        self.load_mesh_file(file_path)

    def load_mesh_file(self, file_path, notify=True):
        """Load a mesh file directly (called from other tabs)."""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Error", f"File not found:\n{file_path}")
            return
        
        try:
            # Load the mesh using mesh processor
            mesh = self.mesh_processor.load_mesh(file_path)
            
            if mesh:
                self.current_mesh = mesh
                self.current_model_path = file_path
                
                # Update UI
                self.update_mesh_info()
                self.update_operation_history()
                
                # Update Viewer
                self.viewer.load_from_file(file_path)
                
                # Update status
                file_name = os.path.basename(file_path)
                self.operation_label.setText(f"Loaded: {file_name}")
                
                if notify:
                    QMessageBox.information(
                        self,
                        "Success",
                        f"Mesh loaded successfully!\n\nFile: {file_name}\n"
                        f"Vertices: {len(mesh.vertices):,}\n"
                        f"Faces: {len(mesh.faces):,}"
                    )
            else:
                QMessageBox.warning(self, "Error", "Failed to load mesh!")
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load mesh:\n{str(e)}"
            )

    def select_and_load_model(self):
        """Open file dialog to select and load a model."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select 3D Model", "", 
            "3D Models (*.obj *.ply *.stl *.off *.xyz *.pcd);;All Files (*)"
        )
        if file_path:
            self.load_mesh_file(file_path)
    def add_to_library(self):
        """Request adding current model to library."""
        if self.current_model_path and os.path.exists(self.current_model_path):
            self.add_to_library_requested.emit(self.current_model_path)
        else:
            QMessageBox.warning(self, "No Model", "No model loaded to add to library.")

    def on_percentage_target_toggled(self, checked):
        """Show which of the two quadric target controls the button will honour."""
        self.target_faces_spin.setEnabled(not checked)
        self.target_percentage_spin.setEnabled(checked)

    def simplify_quadric(self):
        """Apply quadric simplification using worker thread."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        faces_in_mesh = len(self.current_mesh.faces) if self.current_mesh is not None else 0
        if self.percentage_target_cb.isChecked():
            percent = self.target_percentage_spin.value()
            target_faces = max(1, int(round(faces_in_mesh * percent / 100.0)))
            self.operation_label.setText(
                f"Simplifying to {percent:g}% of {faces_in_mesh:,} faces...")
        else:
            target_faces = self.target_faces_spin.value()
            self.operation_label.setText(f"Simplifying to {target_faces:,} faces...")
            
        preserve_boundary = self.preserve_boundary_cb.isChecked()
        preserve_normal = self.preserve_normal_cb.isChecked()
        preserve_topology = self.preserve_topology_cb.isChecked()
        quality_threshold = self.quality_threshold_spin.value()
        
        output_path = self.get_output_path(self.current_model_path, "_simplified")
        
        def worker_func(processor, path, out_path, faces, boundary, normal, topology, quality, **kwargs):
            result = processor.simplify(
                path,
                out_path,
                method='faces',
                target_faces=faces,
                preserve_boundary=boundary,
                preserve_normal=normal,
                preserve_topology=topology,
                quality_threshold=quality
            )
            return result

        # Execute async
        self.execute_async(
            worker_func, 
            self.mesh_processor, 
            self.current_model_path,
            output_path,
            target_faces,
            preserve_boundary,
            preserve_normal,
            preserve_topology,
            quality_threshold
        )

    def close_holes(self):
        """Close holes asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        max_size = self.max_hole_size_spin.value()
        self.operation_label.setText("Closing holes...")
        
        output_path = self.get_output_path(self.current_model_path, "_closed")
        
        def worker_func(processor, path, out_path, size, **kwargs):
            result = processor.repair(path, out_path, operation='fill_holes', max_hole_size=size)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, max_size)

    def make_manifold(self):
        """Make manifold asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Making manifold...")
        
        output_path = self.get_output_path(self.current_model_path, "_manifold")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='make_manifold')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def simplify_cluster(self):
        """Clustering decimation asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        threshold = self.cluster_threshold_spin.value()
        self.operation_label.setText("Clustering decimation...")
        
        output_path = self.get_output_path(self.current_model_path, "_cluster")
        
        def worker_func(processor, path, out_path, thresh, **kwargs):
            result = processor.simplify(path, out_path, method='clustering', threshold=thresh)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, threshold)

    def smooth_laplacian(self):
        """Laplacian smoothing asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        steps = self.laplacian_steps_spin.value()
        boundary = self.laplacian_boundary_cb.isChecked()
        self.operation_label.setText("Laplacian smoothing...")
        
        output_path = self.get_output_path(self.current_model_path, "_smooth")
        
        def worker_func(processor, path, out_path, s, b, **kwargs):
            result = processor.smooth(path, out_path, method='laplacian', iterations=s, boundary=b)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, steps, boundary)

    def smooth_taubin(self):
        """Taubin smoothing asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        steps = self.taubin_steps_spin.value()
        lam = self.taubin_lambda_spin.value()
        mu = self.taubin_mu_spin.value()
        self.operation_label.setText("Taubin smoothing...")
        
        output_path = self.get_output_path(self.current_model_path, "_taubin")
        
        def worker_func(processor, path, out_path, s, l, m, **kwargs):
            result = processor.smooth(path, out_path, method='taubin', iterations=s, lambda_param=l, mu_param=m)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, steps, lam, mu)

    def smooth_depth(self):
        """Depth smoothing asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        steps = self.depth_steps_spin.value()
        threshold = self.depth_threshold_spin.value()
        self.operation_label.setText("Depth smoothing...")
        
        output_path = self.get_output_path(self.current_model_path, "_depth")
        
        def worker_func(processor, path, out_path, s, t, **kwargs):
            result = processor.smooth(path, out_path, method='depth', iterations=s, delta=t)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, steps, threshold)

    def remesh_uniform(self):
        """Uniform remeshing asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        length = self.target_length_spin.value()
        iters = self.iterations_spin.value()
        adaptive = self.adaptive_cb.isChecked()
        self.operation_label.setText("Uniform remeshing...")
        
        output_path = self.get_output_path(self.current_model_path, "_remesh")
        
        def worker_func(processor, path, out_path, l, i, a, **kwargs):
            result = processor.remesh(path, out_path, method='uniform', edge_length=l, iterations=i, adaptive=a)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, length, iters, adaptive)

    def remesh_voronoi(self):
        """Voronoi remeshing asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        threshold = self.voronoi_threshold_spin.value()
        self.operation_label.setText("Voronoi remeshing...")
        
        output_path = self.get_output_path(self.current_model_path, "_voronoi")
        
        def worker_func(processor, path, out_path, t, **kwargs):
            result = processor.remesh(path, out_path, method='voronoi', threshold=t)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, threshold)

    def apply_subdivision(self):
        """Subdivision asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        method = self.subdivision_type_combo.currentText().lower()
        levels = self.subdivision_levels_spin.value()
        self.operation_label.setText("Subdividing...")
        
        output_path = self.get_output_path(self.current_model_path, "_subdiv")
        
        def worker_func(processor, path, out_path, m, l, **kwargs):
            result = processor.remesh(path, out_path, method='subdivision', sub_method=m, levels=l)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, method, levels)

    def save_mesh(self):
        """Save the current mesh to a file."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "No mesh loaded to save.")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Mesh", self.current_model_path, 
            "3D Models (*.obj *.ply *.stl *.off);;All Files (*)"
        )
        
        if file_path:
            try:
                result = self.mesh_processor.export(
                    self.current_model_path, file_path,
                    include_normals=self.export_normals_cb.isChecked(),
                    include_textures=self.export_textures_cb.isChecked(),
                    include_colors=self.export_colors_cb.isChecked(),
                )
                if not result.get('success'):
                    QMessageBox.critical(self, "Error",
                                         f"Failed to save mesh: {result.get('error', 'Unknown error')}")
                    return
                self.operation_label.setText(f"Saved to {os.path.basename(file_path)}")
                self.add_to_history(f"Save ({os.path.splitext(file_path)[1] or '.obj'})")
                QMessageBox.information(self, "Success", f"Mesh saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save mesh: {str(e)}")

    def close_small_holes(self):
        """Close small holes asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        max_size = self.max_hole_size_spin.value()
        self.operation_label.setText("Closing small holes...")
        
        output_path = self.get_output_path(self.current_model_path, "_closed_small")
        
        def worker_func(processor, path, out_path, size, **kwargs):
            result = processor.repair(path, out_path, operation='fill_holes', max_hole_size=size)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, max_size)

    def remove_non_manifold_edges(self):
        """Remove non-manifold edges asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Removing non-manifold edges...")
        
        output_path = self.get_output_path(self.current_model_path, "_manifold_edges")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='repair_non_manifold_edges')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def remove_non_manifold_vertices(self):
        """Remove non-manifold vertices asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Removing non-manifold vertices...")
        
        output_path = self.get_output_path(self.current_model_path, "_manifold_verts")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='repair_non_manifold_vertices')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def remove_duplicate_vertices(self):
        """Remove duplicate vertices asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        threshold = self.duplicate_threshold_spin.value()
        self.operation_label.setText("Removing duplicate vertices...")
        
        output_path = self.get_output_path(self.current_model_path, "_dedup")
        
        def worker_func(processor, path, out_path, thresh, **kwargs):
            result = processor.repair(path, out_path, operation='remove_duplicates', threshold=thresh)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, threshold)

    def remove_degenerate_faces(self):
        """Remove degenerate faces asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Removing degenerate faces...")
        
        output_path = self.get_output_path(self.current_model_path, "_no_degen")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='remove_degenerate')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def remove_unreferenced_vertices(self):
        """Remove unreferenced vertices asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Removing unreferenced vertices...")
        
        output_path = self.get_output_path(self.current_model_path, "_clean_verts")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='remove_unreferenced')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def fix_face_normals(self):
        """Fix face normals asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Fixing face normals...")
        
        output_path = self.get_output_path(self.current_model_path, "_fixed_normals")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='fix_normals')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def invert_normals(self):
        """Invert normals asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Inverting normals...")
        
        output_path = self.get_output_path(self.current_model_path, "_inverted")
        
        def worker_func(processor, path, out_path, **kwargs):
            result = processor.repair(path, out_path, operation='invert_normals')
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def simplify_planar(self):
        """Planar simplification asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        angle = self.planar_angle_spin.value()
        target_faces = self.planar_target_faces_spin.value()
        self.operation_label.setText("Planar simplification...")
        
        output_path = self.get_output_path(self.current_model_path, "_planar")
        
        def worker_func(processor, path, out_path, ang, faces, **kwargs):
            result = processor.simplify(path, out_path, method='planar', angle=ang, target_faces=faces)
            return result
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path,
                           output_path, angle, target_faces)

    def apply_transform(self):
        """Apply translation, rotation, and scale."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        # Gather parameters
        tx, ty, tz = self.trans_x_spin.value(), self.trans_y_spin.value(), self.trans_z_spin.value()
        rx, ry, rz = self.rot_x_spin.value(), self.rot_y_spin.value(), self.rot_z_spin.value()
        sx, sy, sz = self.scale_x_spin.value(), self.scale_y_spin.value(), self.scale_z_spin.value()
        
        # We handle operations sequentially: Scale -> Rotate -> Translate
        # For simplicity in this async model, we might chain them or just do one complex op.
        # But MeshProcessor.transform takes one operation type.
        # Let's do a sequence if needed, or update MeshProcessor to handle matrix.
        # For now, let's prioritize Rotation since that's what the user wants.
        
        # If rotation is non-zero, apply it
        if abs(rx) > 0.001 or abs(ry) > 0.001 or abs(rz) > 0.001:
            self.operation_label.setText("Applying rotation...")
            output_path = self.get_output_path(self.current_model_path, "_rotated")
            
            def worker_func(processor, path, out_path, rot, **kwargs):
                return processor.transform(path, out_path, operation='rotate', rotation=rot)
                
            self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, [rx, ry, rz])
            return

        # If scale is non-1, apply it (Uniform only for now as per UI default)
        if abs(sx - 1.0) > 0.001:
            self.operation_label.setText("Applying scale...")
            output_path = self.get_output_path(self.current_model_path, "_scaled")
            
            def worker_func(processor, path, out_path, s, **kwargs):
                return processor.transform(path, out_path, operation='scale', scale_factor=s)
                
            self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, sx)
            return

        # If translation is non-zero
        if abs(tx) > 0.001 or abs(ty) > 0.001 or abs(tz) > 0.001:
            self.operation_label.setText("Applying translation...")
            output_path = self.get_output_path(self.current_model_path, "_translated")
            
            def worker_func(processor, path, out_path, trans, **kwargs):
                return processor.transform(path, out_path, operation='translate', translation=trans)
                
            self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path, [tx, ty, tz])
            return
        
        QMessageBox.information(self, "Info", "No transformation parameters were specified (Rotation, Scale, or Translation).")

    def auto_align_mesh(self):
        """Auto-align mesh to axes."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Auto-aligning mesh...")
        output_path = self.get_output_path(self.current_model_path, "_aligned")
        
        def worker_func(processor, path, out_path, **kwargs):
            return processor.transform(path, out_path, operation='auto_align')
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def center_mesh(self):
        """Center mesh at origin."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Centering mesh...")
        output_path = self.get_output_path(self.current_model_path, "_centered")
        
        def worker_func(processor, path, out_path, **kwargs):
            return processor.transform(path, out_path, operation='center')
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def normalize_size(self):
        """Normalize mesh size."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return
            
        self.operation_label.setText("Normalizing size...")
        output_path = self.get_output_path(self.current_model_path, "_normalized")
        
        def worker_func(processor, path, out_path, **kwargs):
            return processor.transform(path, out_path, operation='normalize')
            
        self.execute_async(worker_func, self.mesh_processor, self.current_model_path, output_path)

    def reset_transform(self):
        """Reset transform values."""
        self.trans_x_spin.setValue(0.0)
        self.trans_y_spin.setValue(0.0)
        self.trans_z_spin.setValue(0.0)
        
        self.rot_x_spin.setValue(0.0)
        self.rot_y_spin.setValue(0.0)
        self.rot_z_spin.setValue(0.0)
        
        self.scale_x_spin.setValue(1.0)
        self.scale_y_spin.setValue(1.0)
        self.scale_z_spin.setValue(1.0)
        self.uniform_scale_cb.setChecked(True)

    def matrix_transform(self):
        """Matrix transform placeholder."""
        QMessageBox.information(self, "Coming Soon", "Matrix transformation will be available in a future update.")

    def update_mesh_info(self):
        """Update mesh information display."""
        if not self.current_mesh:
            return
            
        self.info_filename.setText(os.path.basename(self.current_model_path))
        self.info_vertices.setText(f"{len(self.current_mesh.vertices):,}")
        self.info_faces.setText(f"{len(self.current_mesh.faces):,}")
        self.info_edges.setText(f"{len(self.current_mesh.edges):,}")
        
        # Check properties if available
        is_watertight = getattr(self.current_mesh, 'is_watertight', False)
        is_manifold = getattr(self.current_mesh, 'is_winding_consistent', False)
        
        self.info_watertight.setText("Yes" if is_watertight else "No")
        self.info_manifold.setText("Yes" if is_manifold else "No")
        # Handle body count safely
        try:
            components = self.current_mesh.body_count
        except:
            components = 1
        self.info_components.setText(str(components))

    def update_operation_history(self):
        """Update the operation history list."""
        self.history_list.clear()
        for i, op in enumerate(self.processing_history):
            self.history_list.addItem(f"{i+1}. {op}")

    def execute_async(self, func, *args, **kwargs):
        """Execute a function asynchronously, remembering its input for undo."""
        self._pending_source = self.current_model_path
        self._pending_label = self.operation_label.text().rstrip(".") or "Mesh operation"
        worker = Worker(func, *args, **kwargs)
        worker.signals.result.connect(self.on_operation_completed)
        worker.signals.error.connect(self.on_operation_error)
        worker.signals.finished.connect(self.on_operation_finished)
        self._keep_worker(worker)
        self.threadpool.start(worker)
        
    def on_operation_completed(self, result):
        """Handle async operation completion."""
        if isinstance(result, dict):
            if result.get('success'):
                output_path = result.get('output_path')
                if output_path:
                    self.operation_label.setText(
                        f"{self._pending_label}: {os.path.basename(output_path)}")
                    self.undo_steps.append((self._pending_source, self._pending_label))
                    self.add_to_history(f"{self._pending_label} -> {os.path.basename(output_path)}")
                    self.load_mesh_file(output_path, notify=False)
                else:
                    self.operation_label.setText("Operation completed successfully")
            else:
                self.operation_label.setText(f"Error: {result.get('error', 'Unknown error')}")

    def undo_last(self):
        """Reload the mesh as it was before the last completed operation."""
        if not self.undo_steps:
            QMessageBox.information(self, "Undo", "There is nothing to undo.")
            return

        source, label = self.undo_steps.pop()
        if self.processing_history:
            self.processing_history.pop()
            self.update_operation_history()

        if source and os.path.exists(source):
            self.load_mesh_file(source, notify=False)
            self.operation_label.setText(f"Undo {label}: {os.path.basename(source)}")
        else:
            self.operation_label.setText(f"Undo failed for {label}: file no longer exists")

    def clear_history(self):
        """Drop the recorded operations and the undo trail with them."""
        self.processing_history.clear()
        self.undo_steps.clear()
        self.history_list.clear()
        self.operation_label.setText("History cleared")

    def export_to_format(self, extension):
        """Write the current mesh in one format, honouring the export options."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Mesh", "Please load a mesh first")
            return

        suggested = os.path.splitext(self.current_model_path)[0] + extension
        file_path, _ = QFileDialog.getSaveFileName(
            self, f"Export {extension.upper()}", suggested,
            f"{extension.upper()} files (*{extension})")
        if not file_path:
            return
        if not file_path.lower().endswith(extension):
            file_path += extension

        result = self.mesh_processor.export(
            self.current_model_path, file_path,
            include_normals=self.export_normals_cb.isChecked(),
            include_textures=self.export_textures_cb.isChecked(),
            include_colors=self.export_colors_cb.isChecked())
        if result.get('success'):
            self.add_to_history(f"Exported {os.path.basename(file_path)}")
            self.operation_label.setText(f"Exported {os.path.basename(file_path)}")
            QMessageBox.information(self, "Success", f"Exported to:\n{file_path}")
        else:
            QMessageBox.critical(self, "Error", f"Export failed: {result.get('error')}")

    def reset_view(self):
        """Re-render the preview from the default camera."""
        self.viewer.reset_view()
        self.operation_label.setText("View reset")

    def take_screenshot(self):
        """Save the preview image that is currently on screen."""
        pixmap = self.viewer.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.information(self, "Screenshot", "There is no preview image to save yet.")
            return

        base = os.path.splitext(self.current_model_path or "renderfox_preview")[0] + "_preview.png"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Preview", base, "PNG (*.png)")
        if not file_path:
            return
        if not file_path.lower().endswith(".png"):
            file_path += ".png"

        if pixmap.save(file_path, "PNG"):
            self.operation_label.setText(f"Preview saved to {os.path.basename(file_path)}")
        else:
            QMessageBox.critical(self, "Error", "Could not write the image file.")
        
    def on_operation_error(self, error_msg):
        """Handle async operation error."""
        self.operation_label.setText(f"Error: {error_msg}")
        self.progress_bar.setVisible(False)
        
    def on_operation_finished(self):
        """Handle async operation finish."""
        self.progress_bar.setVisible(False)

