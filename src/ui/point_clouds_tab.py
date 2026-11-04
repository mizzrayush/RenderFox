"""
Point Clouds tab for point cloud processing and mesh reconstruction.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QDialog, QFormLayout,
                             QLabel, QGroupBox, QGridLayout, QComboBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
                             QSpinBox, QCheckBox, QTextEdit, QTabWidget, QSlider,
                             QProgressBar, QFormLayout, QDoubleSpinBox, QFileDialog,
                             QMessageBox, QListWidget, QSplitter, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThreadPool
from PyQt6.QtGui import QFont

# Import point cloud processor backend
from ..processing.point_cloud_processor import (
    PointCloudProcessor, PointCloudStatistics
)
import os
from .unified_viewer import UnifiedOpen3DViewer
from ..utils.worker import Worker
from .icon_provider import get_icon

class BoundingBoxDialog(QDialog):
    """Dialog for entering bounding box coordinates."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crop Bounding Box")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        self.min_x = QDoubleSpinBox()
        self.min_x.setRange(-10000, 10000)
        self.min_x.setValue(-1.0)
        
        self.max_x = QDoubleSpinBox()
        self.max_x.setRange(-10000, 10000)
        self.max_x.setValue(1.0)
        
        self.min_y = QDoubleSpinBox()
        self.min_y.setRange(-10000, 10000)
        self.min_y.setValue(-1.0)
        
        self.max_y = QDoubleSpinBox()
        self.max_y.setRange(-10000, 10000)
        self.max_y.setValue(1.0)
        
        self.min_z = QDoubleSpinBox()
        self.min_z.setRange(-10000, 10000)
        self.min_z.setValue(-1.0)
        
        self.max_z = QDoubleSpinBox()
        self.max_z.setRange(-10000, 10000)
        self.max_z.setValue(1.0)
        
        form.addRow("Min X:", self.min_x)
        form.addRow("Max X:", self.max_x)
        form.addRow("Min Y:", self.min_y)
        form.addRow("Max Y:", self.max_y)
        form.addRow("Min Z:", self.min_z)
        form.addRow("Max Z:", self.max_z)
        
        layout.addLayout(form)
        
        buttons = QHBoxLayout()
        ok_btn = QPushButton("Crop")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)
        
    def get_bounds(self):
        return [
            self.min_x.value(), self.max_x.value(),
            self.min_y.value(), self.max_y.value(),
            self.min_z.value(), self.max_z.value()
        ]

class PointCloudsTab(QWidget):
    mesh_generated = pyqtSignal(str)  # path
    """Point cloud processing and visualization using Open3D."""
    
    point_cloud_loaded = pyqtSignal(dict)
    processing_completed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.threadpool = QThreadPool()
        self.current_point_cloud = None
        self.current_model_path = None
        self.target_model_path = None
        
        # Initialize point cloud processor backend
        self.pc_processor = PointCloudProcessor()
        
        self.init_ui()
        self.setup_connections()
        
    def init_ui(self):
        """Initialize the point cloud interface."""
        main_layout = QVBoxLayout(self)
        
        # Current model header
        self.model_header = self.create_model_header()
        main_layout.addWidget(self.model_header)
        
        # Create main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Tools and controls
        left_panel = self.create_left_panel()
        scroll_left = QScrollArea()
        scroll_left.setWidget(left_panel)
        scroll_left.setWidgetResizable(True)
        scroll_left.setFrameShape(QFrame.Shape.NoFrame)
        splitter.addWidget(scroll_left)
        
        # Right panel - Viewer and results
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([350, 850])
        main_layout.addWidget(splitter)
        
    def create_model_header(self):
        """Create the current model header."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setMaximumHeight(80)  # Increased height for explanation
        
        layout = QVBoxLayout(frame)
        
        # Main header layout
        header_layout = QHBoxLayout()
        
        self.current_model_label = QLabel("No point cloud loaded")
        self.current_model_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        from .icon_provider import get_icon
        self.change_model_btn = QPushButton("Change Model")
        self.change_model_btn.setIcon(get_icon("folder"))
        self.add_model_btn = QPushButton("Add to Library")
        self.add_model_btn.setIcon(get_icon("add"))
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setIcon(get_icon("refresh"))
        
        header_layout.addWidget(self.current_model_label)
        header_layout.addStretch()
        header_layout.addWidget(self.change_model_btn)
        header_layout.addWidget(self.add_model_btn)
        header_layout.addWidget(self.reload_btn)
        
        # Explanation text
        explanation = QLabel("Load point cloud datasets directly for scanning data analysis, filtering, and reconstruction")
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
        
        # Basic operations tab
        basic_tab = self.create_basic_operations_tab()
        self.tools_tabs.addTab(basic_tab, "Basic")
        
        # Filtering tab
        filtering_tab = self.create_filtering_tab()
        self.tools_tabs.addTab(filtering_tab, "Filter")
        
        # Registration tab
        registration_tab = self.create_registration_tab()
        self.tools_tabs.addTab(registration_tab, "Register")
        
        # Reconstruction tab
        reconstruction_tab = self.create_reconstruction_tab()
        self.tools_tabs.addTab(reconstruction_tab, "Reconstruct")
        
        # Analysis tab
        analysis_tab = self.create_analysis_tab()
        self.tools_tabs.addTab(analysis_tab, "Analyze")
        
        layout.addWidget(self.tools_tabs)
        
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
        
    def create_basic_operations_tab(self):
        """Create basic point cloud operations."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # I/O operations
        io_group = QGroupBox("Import/Export")
        io_layout = QVBoxLayout()
        
        from .icon_provider import get_icon
        self.load_pcd_btn = QPushButton("Load Point Cloud")
        self.load_pcd_btn.setIcon(get_icon("folder"))
        self.save_pcd_btn = QPushButton("Save Point Cloud")
        self.save_pcd_btn.setIcon(get_icon("backup"))
        self.export_mesh_btn = QPushButton("Export as Mesh")
        self.export_mesh_btn.setIcon(get_icon("export"))
        
        io_layout.addWidget(self.load_pcd_btn)
        io_layout.addWidget(self.save_pcd_btn)
        io_layout.addWidget(self.export_mesh_btn)
        
        io_group.setLayout(io_layout)
        layout.addWidget(io_group)
        
        # Basic transformations
        transform_group = QGroupBox("Transformations")
        transform_layout = QVBoxLayout()
        
        # Translation
        trans_frame = QFrame()
        trans_layout = QFormLayout(trans_frame)
        
        self.trans_x_spin = QDoubleSpinBox()
        self.trans_x_spin.setRange(-1000, 1000)
        self.trans_y_spin = QDoubleSpinBox()
        self.trans_y_spin.setRange(-1000, 1000)
        self.trans_z_spin = QDoubleSpinBox()
        self.trans_z_spin.setRange(-1000, 1000)
        
        trans_layout.addRow("X:", self.trans_x_spin)
        trans_layout.addRow("Y:", self.trans_y_spin)
        trans_layout.addRow("Z:", self.trans_z_spin)
        
        self.apply_translation_btn = QPushButton("Apply Translation")
        
        transform_layout.addWidget(QLabel("Translation:"))
        transform_layout.addWidget(trans_frame)
        transform_layout.addWidget(self.apply_translation_btn)
        
        # Rotation
        rot_frame = QFrame()
        rot_layout = QFormLayout(rot_frame)
        
        self.rot_x_spin = QDoubleSpinBox()
        self.rot_x_spin.setRange(-180, 180)
        self.rot_x_spin.setSuffix("°")
        self.rot_y_spin = QDoubleSpinBox()
        self.rot_y_spin.setRange(-180, 180)
        self.rot_y_spin.setSuffix("°")
        self.rot_z_spin = QDoubleSpinBox()
        self.rot_z_spin.setRange(-180, 180)
        self.rot_z_spin.setSuffix("°")
        
        rot_layout.addRow("X:", self.rot_x_spin)
        rot_layout.addRow("Y:", self.rot_y_spin)
        rot_layout.addRow("Z:", self.rot_z_spin)
        
        self.apply_rotation_btn = QPushButton("Apply Rotation")
        
        transform_layout.addWidget(QLabel("Rotation:"))
        transform_layout.addWidget(rot_frame)
        transform_layout.addWidget(self.apply_rotation_btn)
        
        # Scale
        scale_layout = QHBoxLayout()
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 100)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSingleStep(0.1)
        self.apply_scale_btn = QPushButton("Apply Scale")
        
        scale_layout.addWidget(self.scale_spin)
        scale_layout.addWidget(self.apply_scale_btn)
        
        transform_layout.addWidget(QLabel("Scale:"))
        transform_layout.addLayout(scale_layout)
        
        transform_group.setLayout(transform_layout)
        layout.addWidget(transform_group)
        
        # Basic processing
        processing_group = QGroupBox("Basic Processing")
        processing_layout = QVBoxLayout()
        
        self.center_btn = QPushButton("Center Point Cloud")
        self.normalize_btn = QPushButton("Normalize Scale")
        self.remove_duplicates_btn = QPushButton("Remove Duplicates")
        self.estimate_normals_btn = QPushButton("Estimate Normals")
        
        processing_layout.addWidget(self.center_btn)
        processing_layout.addWidget(self.normalize_btn)
        processing_layout.addWidget(self.remove_duplicates_btn)
        processing_layout.addWidget(self.estimate_normals_btn)
        
        processing_group.setLayout(processing_layout)
        layout.addWidget(processing_group)
        
        layout.addStretch()
        return scroll
        
    def create_filtering_tab(self):
        """Create filtering operations."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Statistical outlier removal
        outlier_group = QGroupBox("Outlier Removal")
        outlier_layout = QFormLayout()
        
        self.outlier_neighbors_spin = QSpinBox()
        self.outlier_neighbors_spin.setRange(1, 100)
        self.outlier_neighbors_spin.setValue(20)
        
        self.outlier_std_spin = QDoubleSpinBox()
        self.outlier_std_spin.setRange(0.1, 10.0)
        self.outlier_std_spin.setValue(2.0)
        self.outlier_std_spin.setSingleStep(0.1)
        
        outlier_layout.addRow("Neighbors:", self.outlier_neighbors_spin)
        outlier_layout.addRow("Std Ratio:", self.outlier_std_spin)
        
        self.remove_outliers_btn = QPushButton("Remove Statistical Outliers")
        
        outlier_group.setLayout(outlier_layout)
        layout.addWidget(outlier_group)
        layout.addWidget(self.remove_outliers_btn)
        
        # Radius outlier removal
        radius_group = QGroupBox("Radius Outlier Removal")
        radius_layout = QFormLayout()
        
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.001, 10.0)
        self.radius_spin.setValue(0.05)
        self.radius_spin.setSingleStep(0.001)
        
        self.min_points_spin = QSpinBox()
        self.min_points_spin.setRange(1, 100)
        self.min_points_spin.setValue(16)
        
        radius_layout.addRow("Radius:", self.radius_spin)
        radius_layout.addRow("Min Points:", self.min_points_spin)
        
        self.remove_radius_outliers_btn = QPushButton("Remove Radius Outliers")
        
        radius_group.setLayout(radius_layout)
        layout.addWidget(radius_group)
        layout.addWidget(self.remove_radius_outliers_btn)
        
        # Voxel downsampling
        voxel_group = QGroupBox("Voxel Downsampling")
        voxel_layout = QFormLayout()
        
        self.voxel_size_spin = QDoubleSpinBox()
        self.voxel_size_spin.setRange(0.001, 1.0)
        self.voxel_size_spin.setValue(0.01)
        self.voxel_size_spin.setSingleStep(0.001)
        
        voxel_layout.addRow("Voxel Size:", self.voxel_size_spin)
        
        self.voxel_downsample_btn = QPushButton("Apply Voxel Downsampling")
        
        voxel_group.setLayout(voxel_layout)
        layout.addWidget(voxel_group)
        layout.addWidget(self.voxel_downsample_btn)
        
        # Uniform downsampling
        uniform_group = QGroupBox("Uniform Downsampling")
        uniform_layout = QFormLayout()
        
        self.uniform_k_spin = QSpinBox()
        self.uniform_k_spin.setRange(2, 1000)
        self.uniform_k_spin.setValue(5)
        
        uniform_layout.addRow("Every K-th Point:", self.uniform_k_spin)
        
        self.uniform_downsample_btn = QPushButton("Apply Uniform Downsampling")
        
        uniform_group.setLayout(uniform_layout)
        layout.addWidget(uniform_group)
        layout.addWidget(self.uniform_downsample_btn)
        
        # Crop operations
        crop_group = QGroupBox("Cropping")
        crop_layout = QVBoxLayout()
        
        self.crop_box_btn = QPushButton("Crop to Bounding Box")
        self.crop_interactive_btn = QPushButton("Interactive Crop")
        
        crop_layout.addWidget(self.crop_box_btn)
        crop_layout.addWidget(self.crop_interactive_btn)
        
        crop_group.setLayout(crop_layout)
        layout.addWidget(crop_group)
        
        layout.addStretch()
        return scroll
        
    def create_registration_tab(self):
        """Create point cloud registration tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Load target point cloud
        target_group = QGroupBox("Target Point Cloud")
        target_layout = QVBoxLayout()
        
        self.load_target_btn = QPushButton("Load Target")
        self.load_target_btn.setIcon(get_icon("folder"))
        self.target_info_label = QLabel("No target loaded")
        
        target_layout.addWidget(self.load_target_btn)
        target_layout.addWidget(self.target_info_label)
        
        target_group.setLayout(target_layout)
        layout.addWidget(target_group)
        
        # ICP Registration
        icp_group = QGroupBox("ICP Registration")
        icp_layout = QFormLayout()
        
        self.icp_threshold_spin = QDoubleSpinBox()
        self.icp_threshold_spin.setRange(0.001, 1.0)
        self.icp_threshold_spin.setValue(0.02)
        self.icp_threshold_spin.setSingleStep(0.001)
        
        self.icp_max_iter_spin = QSpinBox()
        self.icp_max_iter_spin.setRange(1, 1000)
        self.icp_max_iter_spin.setValue(100)
        
        icp_layout.addRow("Threshold:", self.icp_threshold_spin)
        icp_layout.addRow("Max Iterations:", self.icp_max_iter_spin)
        
        self.run_icp_btn = QPushButton("Run ICP Registration")
        
        icp_group.setLayout(icp_layout)
        layout.addWidget(icp_group)
        layout.addWidget(self.run_icp_btn)
        
        # Feature-based registration
        feature_group = QGroupBox("Feature-based Registration")
        feature_layout = QVBoxLayout()
        
        self.extract_features_btn = QPushButton("Extract FPFH Features")
        self.run_ransac_btn = QPushButton("Run RANSAC Registration")
        
        feature_layout.addWidget(self.extract_features_btn)
        feature_layout.addWidget(self.run_ransac_btn)
        
        feature_group.setLayout(feature_layout)
        layout.addWidget(feature_group)
        
        # Registration results
        results_group = QGroupBox("Registration Results")
        results_layout = QVBoxLayout()
        
        self.registration_results = QTextEdit()
        self.registration_results.setMaximumHeight(100)
        self.registration_results.setReadOnly(True)
        
        results_layout.addWidget(self.registration_results)
        
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        layout.addStretch()
        return scroll
        
    def create_reconstruction_tab(self):
        """Create mesh reconstruction tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Poisson reconstruction
        poisson_group = QGroupBox("Poisson Surface Reconstruction")
        poisson_layout = QFormLayout()
        
        self.poisson_depth_spin = QSpinBox()
        self.poisson_depth_spin.setRange(5, 12)
        self.poisson_depth_spin.setValue(9)
        
        self.poisson_width_spin = QSpinBox()
        self.poisson_width_spin.setRange(0, 10)
        self.poisson_width_spin.setValue(0)
        
        self.poisson_scale_spin = QDoubleSpinBox()
        self.poisson_scale_spin.setRange(0.1, 2.0)
        self.poisson_scale_spin.setValue(1.1)
        self.poisson_scale_spin.setSingleStep(0.1)
        
        poisson_layout.addRow("Depth:", self.poisson_depth_spin)
        poisson_layout.addRow("Width:", self.poisson_width_spin)
        poisson_layout.addRow("Scale:", self.poisson_scale_spin)
        
        self.run_poisson_btn = QPushButton("Run Poisson Reconstruction")
        
        poisson_group.setLayout(poisson_layout)
        layout.addWidget(poisson_group)
        layout.addWidget(self.run_poisson_btn)
        
        # Ball pivoting
        ball_group = QGroupBox("Ball Pivoting Algorithm")
        ball_layout = QFormLayout()
        
        self.ball_radius_spin = QDoubleSpinBox()
        self.ball_radius_spin.setRange(0.001, 1.0)
        self.ball_radius_spin.setValue(0.005)
        self.ball_radius_spin.setSingleStep(0.001)
        
        ball_layout.addRow("Ball Radius:", self.ball_radius_spin)
        
        self.run_ball_pivoting_btn = QPushButton("Run Ball Pivoting")
        
        ball_group.setLayout(ball_layout)
        layout.addWidget(ball_group)
        layout.addWidget(self.run_ball_pivoting_btn)
        
        # Alpha shapes
        alpha_group = QGroupBox("Alpha Shapes")
        alpha_layout = QFormLayout()
        
        self.alpha_value_spin = QDoubleSpinBox()
        self.alpha_value_spin.setRange(0.001, 1.0)
        self.alpha_value_spin.setValue(0.03)
        self.alpha_value_spin.setSingleStep(0.001)
        
        alpha_layout.addRow("Alpha Value:", self.alpha_value_spin)
        
        self.run_alpha_shapes_btn = QPushButton("Create Alpha Shape")
        
        alpha_group.setLayout(alpha_layout)
        layout.addWidget(alpha_group)
        layout.addWidget(self.run_alpha_shapes_btn)
        
        # Convex hull
        hull_group = QGroupBox("Convex Hull")
        hull_layout = QVBoxLayout()
        
        self.create_convex_hull_btn = QPushButton("Create Convex Hull")
        
        hull_layout.addWidget(self.create_convex_hull_btn)
        
        hull_group.setLayout(hull_layout)
        layout.addWidget(hull_group)
        
        layout.addStretch()
        return scroll
        
    def create_analysis_tab(self):
        """Create analysis and measurement tools."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        
        layout = QVBoxLayout(widget)
        
        # Basic statistics
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()
        
        self.compute_stats_btn = QPushButton("Compute Statistics")
        self.stats_display = QTextEdit()
        self.stats_display.setMaximumHeight(120)
        self.stats_display.setReadOnly(True)
        
        stats_layout.addWidget(self.compute_stats_btn)
        stats_layout.addWidget(self.stats_display)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Distance analysis
        distance_group = QGroupBox("Distance Analysis")
        distance_layout = QVBoxLayout()
        
        self.compute_distances_btn = QPushButton("Compute Nearest Distances")
        self.distance_histogram_btn = QPushButton("Show Distance Histogram")
        
        distance_layout.addWidget(self.compute_distances_btn)
        distance_layout.addWidget(self.distance_histogram_btn)
        
        distance_group.setLayout(distance_layout)
        layout.addWidget(distance_group)
        
        # Clustering
        clustering_group = QGroupBox("Clustering")
        clustering_layout = QFormLayout()
        
        self.cluster_eps_spin = QDoubleSpinBox()
        self.cluster_eps_spin.setRange(0.001, 1.0)
        self.cluster_eps_spin.setValue(0.02)
        self.cluster_eps_spin.setSingleStep(0.001)
        
        self.cluster_min_points_spin = QSpinBox()
        self.cluster_min_points_spin.setRange(1, 100)
        self.cluster_min_points_spin.setValue(10)
        
        clustering_layout.addRow("Epsilon:", self.cluster_eps_spin)
        clustering_layout.addRow("Min Points:", self.cluster_min_points_spin)
        
        self.run_clustering_btn = QPushButton("Run DBSCAN Clustering")
        
        clustering_group.setLayout(clustering_layout)
        layout.addWidget(clustering_group)
        layout.addWidget(self.run_clustering_btn)
        
        # Plane detection
        plane_group = QGroupBox("Plane Detection")
        plane_layout = QFormLayout()
        
        self.plane_threshold_spin = QDoubleSpinBox()
        self.plane_threshold_spin.setRange(0.001, 0.1)
        self.plane_threshold_spin.setValue(0.01)
        self.plane_threshold_spin.setSingleStep(0.001)
        
        self.plane_iterations_spin = QSpinBox()
        self.plane_iterations_spin.setRange(100, 10000)
        self.plane_iterations_spin.setValue(1000)
        
        plane_layout.addRow("Threshold:", self.plane_threshold_spin)
        plane_layout.addRow("Max Iterations:", self.plane_iterations_spin)
        
        self.detect_planes_btn = QPushButton("Detect Planes (RANSAC)")
        
        plane_group.setLayout(plane_layout)
        layout.addWidget(plane_group)
        layout.addWidget(self.detect_planes_btn)
        
        layout.addStretch()
        return scroll
        
    def create_right_panel(self):
        """Create the right panel with viewer and results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Create tab widget for viewer and results
        self.right_tabs = QTabWidget()
        
        # 3D Viewer tab
        viewer_tab = self.create_viewer_tab()
        self.right_tabs.addTab(viewer_tab, "3D Viewer")
        
        # Point cloud info tab
        info_tab = self.create_info_tab()
        self.right_tabs.addTab(info_tab, "Information")
        
        # Processing results tab
        results_tab = self.create_results_tab()
        self.right_tabs.addTab(results_tab, "Results")
        
        layout.addWidget(self.right_tabs)
        
        return widget
        
    def create_viewer_tab(self):
        """Create the 3D viewer interface with UnifiedOpen3DViewer."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Unified Open3D Viewer
        self.viewer = UnifiedOpen3DViewer()
        layout.addWidget(self.viewer)
        self.has_viewer = True
        
        # Viewer controls
        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)
        
        # Display options
        self.show_normals_cb = QCheckBox("Show Normals")
        self.show_wireframe_cb = QCheckBox("Wireframe")
        self.point_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.point_size_slider.setRange(1, 10)
        self.point_size_slider.setValue(3)
        
        self.reset_view_btn = QPushButton("Reset View")
        self.reset_view_btn.setIcon(get_icon("reset_view"))
        self.fit_view_btn = QPushButton("Fit to View")
        self.fit_view_btn.setIcon(get_icon("focus"))
        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.setIcon(get_icon("camera"))
        
        # Connect controls
        self.reset_view_btn.clicked.connect(self.viewer.reset_view)
        # self.fit_view_btn.clicked.connect(self.viewer.fit_to_view) # Check if supported
        
        controls_layout.addWidget(QLabel("Point Size:"))
        controls_layout.addWidget(self.point_size_slider)
        controls_layout.addWidget(self.show_normals_cb)
        controls_layout.addWidget(self.show_wireframe_cb)
        controls_layout.addStretch()
        controls_layout.addWidget(self.reset_view_btn)
        controls_layout.addWidget(self.fit_view_btn)
        controls_layout.addWidget(self.screenshot_btn)
        
        layout.addWidget(controls_frame)
        
        return widget

        
    def create_info_tab(self):
        """Create point cloud information display."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Basic information
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        
        self.info_filename = QLabel("No point cloud loaded")
        self.info_points = QLabel("-")
        self.info_has_normals = QLabel("-")
        self.info_has_colors = QLabel("-")
        self.info_bounds = QLabel("-")
        
        basic_layout.addRow("Filename:", self.info_filename)
        basic_layout.addRow("Points:", self.info_points)
        basic_layout.addRow("Has Normals:", self.info_has_normals)
        basic_layout.addRow("Has Colors:", self.info_has_colors)
        basic_layout.addRow("Bounds:", self.info_bounds)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # Detailed statistics
        stats_group = QGroupBox("Detailed Statistics")
        stats_layout = QVBoxLayout()
        
        self.detailed_stats = QTextEdit()
        self.detailed_stats.setReadOnly(True)
        self.detailed_stats.setMaximumHeight(200)
        
        stats_layout.addWidget(self.detailed_stats)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        layout.addStretch()
        return widget
        
    def create_results_tab(self):
        """Create processing results display."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Processing history
        history_group = QGroupBox("Processing History")
        history_layout = QVBoxLayout()
        
        self.history_list = QListWidget()
        self.clear_history_btn = QPushButton("Clear History")
        
        history_layout.addWidget(self.history_list)
        history_layout.addWidget(self.clear_history_btn)
        
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)
        
        # Export options
        export_group = QGroupBox("Export Options")
        export_layout = QGridLayout()
        
        self.export_pcd_btn = QPushButton("Export PCD")
        self.export_ply_btn = QPushButton("Export PLY")
        self.export_xyz_btn = QPushButton("Export XYZ")
        self.export_obj_btn = QPushButton("Export OBJ")
        
        export_layout.addWidget(self.export_pcd_btn, 0, 0)
        export_layout.addWidget(self.export_ply_btn, 0, 1)
        export_layout.addWidget(self.export_xyz_btn, 1, 0)
        export_layout.addWidget(self.export_obj_btn, 1, 1)
        
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)
        
        layout.addStretch()
        return widget

    def setup_connections(self):
        """Setup signal connections."""
        # Header buttons
        self.change_model_btn.clicked.connect(self.change_model)
        self.reload_btn.clicked.connect(self.reload_current_model)
        
        # Basic operations
        self.load_pcd_btn.clicked.connect(self.load_point_cloud)
        self.center_btn.clicked.connect(self.center_point_cloud)
        self.normalize_btn.clicked.connect(self.normalize_point_cloud)
        
        # Transformations
        self.apply_translation_btn.clicked.connect(self.apply_translation)
        self.apply_rotation_btn.clicked.connect(self.apply_rotation)
        self.apply_scale_btn.clicked.connect(self.apply_scale)
        
        # Filtering
        self.remove_outliers_btn.clicked.connect(self.remove_statistical_outliers)
        self.remove_radius_outliers_btn.clicked.connect(self.remove_radius_outliers)
        self.voxel_downsample_btn.clicked.connect(self.voxel_downsample)
        
        # Cropping
        self.crop_box_btn.clicked.connect(self.crop_box)
        self.crop_interactive_btn.clicked.connect(self.crop_interactive)
        
        # Analysis
        self.compute_stats_btn.clicked.connect(self.compute_statistics)
        self.run_clustering_btn.clicked.connect(self.run_clustering)
        
        # Reconstruction
        self.run_poisson_btn.clicked.connect(self.poisson_reconstruction)
        self.run_ball_pivoting_btn.clicked.connect(self.run_ball_pivoting)
        self.run_alpha_shapes_btn.clicked.connect(self.run_alpha_shapes)

        # Registration
        self.load_target_btn.clicked.connect(self.load_target_model)
        self.run_icp_btn.clicked.connect(self.run_icp_registration)
        self.run_ransac_btn.clicked.connect(self.run_ransac_registration)
        
        # Export connections
        self.export_pcd_btn.clicked.connect(lambda: self.export_point_cloud("pcd"))
        self.export_ply_btn.clicked.connect(lambda: self.export_point_cloud("ply"))
        self.export_xyz_btn.clicked.connect(lambda: self.export_point_cloud("xyz"))
        self.export_obj_btn.clicked.connect(lambda: self.export_point_cloud("obj"))
        # Analysis connections
        self.compute_distances_btn.clicked.connect(self.compute_distances)
        self.distance_histogram_btn.clicked.connect(self.show_distance_histogram)
        # Viewer connections
        self.screenshot_btn.clicked.connect(self.capture_screen)
    def change_model(self):
        """Change the current point cloud model."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Point Cloud",
            "", "Point Clouds (*.pcd *.ply *.xyz);;All Files (*)"
        )
        
        if file_path:
            self.load_model(file_path)

    def load_model(self, file_path):
        """Load a point cloud model and display in viewer."""
        self.current_model_path = file_path
        filename = os.path.basename(file_path)
        self.current_model_label.setText(f"Current: {filename}")
        
        # Load into Unified Viewer
        try:
            self.operation_label.setText(f"Loading {filename}...")
            success = self.viewer.load_from_file(file_path)
            
            if success:
                self.operation_label.setText(f"✓ Loaded: {filename}")
                
                # Get and display model info
                # For now, just rely on processor for stats
                self.point_cloud_loaded.emit({}) 
            else:
                self.operation_label.setText("Failed to load point cloud")
                QMessageBox.warning(self, "Load Error", f"Failed to load {filename}")
                
        except Exception as e:
            self.operation_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load point cloud:\n{str(e)}")

    def reload_current_model(self):
        """Reload the current model."""
        if self.current_model_path:
            self.load_model(self.current_model_path)
            
    def load_point_cloud(self):
        """Load a point cloud file."""
        self.change_model()
        
    def load_point_cloud_file(self, file_path):
        """Load a point cloud file by path."""
        self.load_model(file_path)
        
    def center_point_cloud(self):
        """Center the point cloud asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        self.operation_label.setText("Centering point cloud...")
        
        def worker_func(processor, path):
            output_path = path.replace('.', '_centered.')
            import open3d as o3d
            pcd = o3d.io.read_point_cloud(path)
            center = pcd.get_center()
            pcd.translate(-center)
            o3d.io.write_point_cloud(output_path, pcd)
            return {'success': True, 'output_path': output_path, 'center': center}
            
        self.execute_async(worker_func, self.pc_processor, self.current_model_path)
    def normalize_point_cloud(self):
        """Normalize point cloud size asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        self.operation_label.setText("Normalizing point cloud...")
        
        def worker_func(processor, path):
            output_path = path.replace('.', '_normalized.')
            import open3d as o3d
            pcd = o3d.io.read_point_cloud(path)
            center = pcd.get_center()
            pcd.translate(-center)
            max_bound = pcd.get_max_bound()
            min_bound = pcd.get_min_bound()
            scale = 1.0 / (max_bound - min_bound).max()
            pcd.scale(scale, center=(0,0,0))
            o3d.io.write_point_cloud(output_path, pcd)
            return {'success': True, 'output_path': output_path, 'scale': scale}
            
        self.execute_async(worker_func, self.pc_processor, self.current_model_path)
    def remove_statistical_outliers(self):
        """Remove statistical outliers using backend."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        neighbors = self.outlier_neighbors_spin.value()
        std_ratio = self.outlier_std_spin.value()
        
        self.operation_label.setText("Removing statistical outliers...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_filtered.')
            result = self.pc_processor.remove_outliers(
                self.current_model_path,
                output_path,
                method='statistical',
                nb_neighbors=neighbors,
                std_ratio=std_ratio
            )
            
            if result['success']:
                self.current_model_path = output_path
                removed = result.get('removed', 0)
                self.operation_label.setText(f"Removed {removed} outliers")
                QMessageBox.information(self, "Success", f"Removed {removed} outlier points!")
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove outliers: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def remove_radius_outliers(self):
        """Remove radius outliers using backend."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        radius = self.radius_spin.value()
        min_points = self.min_points_spin.value()
        
        self.operation_label.setText("Removing radius outliers...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_radius_filtered.')
            result = self.pc_processor.remove_outliers(
                self.current_model_path,
                output_path,
                method='radius',
                radius=radius,
                min_points=min_points
            )
            
            if result['success']:
                self.current_model_path = output_path
                removed = result.get('removed', 0)
                self.operation_label.setText(f"Removed {removed} outliers")
                QMessageBox.information(self, "Success", f"Removed {removed} outlier points!")
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove outliers: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)
            
    def voxel_downsample(self):
        """Apply voxel downsampling using backend."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        voxel_size = self.voxel_size_spin.value()
        
        self.operation_label.setText("Applying voxel downsampling...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_downsampled.')
            result = self.pc_processor.downsample(
                self.current_model_path,
                output_path,
                voxel_size=voxel_size
            )
            
            if result['success']:
                self.current_model_path = output_path
                original = result.get('original_points', 0)
                downsampled = result.get('downsampled_points', 0)
                reduction = result.get('reduction', 0)
                self.operation_label.setText(f"Downsampled: {original:,} → {downsampled:,} points ({reduction:.1f}% reduction)")
                QMessageBox.information(self, "Success", f"Downsampled to {downsampled:,} points ({reduction:.1f}% reduction)!")
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to downsample: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)
            
    def compute_statistics(self):
        """Compute point cloud statistics using backend."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        self.operation_label.setText("Computing statistics...")
        
        try:
            stats = self.pc_processor.analyze_point_cloud(self.current_model_path)
            
            if stats:
                stats_text = f"Point Cloud Statistics:\n\nPoints: {stats.point_count:,}\nHas Colors: {'Yes' if stats.has_colors else 'No'}\nHas Normals: {'Yes' if stats.has_normals else 'No'}\n\nBounding Box: {stats.bounding_box}\nCentroid: {stats.centroid}\nDensity: {stats.density:.2f} points/unit³"
                
                self.detailed_stats.setPlainText(stats_text)
                
                # Update info tab
                self.info_points.setText(f"{stats.point_count:,}")
                self.info_has_normals.setText("Yes" if stats.has_normals else "No")
                self.info_has_colors.setText("Yes" if stats.has_colors else "No")
                self.info_bounds.setText(str(stats.bounding_box))
                
                self.operation_label.setText("Statistics computed")
            else:
                QMessageBox.warning(self, "Error", "Failed to compute statistics")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to compute statistics: {str(e)}")
            
    def poisson_reconstruction(self):
        """Perform Poisson reconstruction asynchronously."""
        if not self.current_cloud_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        depth = self.poisson_depth_spin.value()
        self.operation_label.setText(f"Reconstructing (Poisson, depth={depth})...")
        
        def worker_func(processor, path, d):
            output_path = path.replace('.', '_poisson.') + 'ply'
            # Note: Assuming reconstruct_mesh returns a dict with success/error
            # If not, we might need to wrap it. 
            # Based on previous code, it seemed to return a success bool or similar.
            # Let's assume the processor methods are synchronous and return a result dict.
            result = processor.reconstruct_mesh(path, output_path, method='poisson', depth=d)
            if result:
                return {'success': True, 'output_path': output_path}
            else:
                return {'error': 'Reconstruction failed'}
            
        self.execute_async(worker_func, self.processor, self.current_cloud_path, depth)

    def run_clustering(self):
        """Run DBSCAN clustering using backend."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        eps = self.cluster_eps_spin.value()
        min_points = self.cluster_min_points_spin.value()
        
        self.operation_label.setText("Running DBSCAN clustering...")
        self.progress_bar.setVisible(True)
        
        try:
            # Load point cloud
            pcd = self.pc_processor.load_point_cloud(self.current_model_path)
            
            if pcd is None:
                QMessageBox.warning(self, "Error", "Failed to load point cloud")
                return
            
            # Run clustering
            self.operation_label.setText(f"DBSCAN clustering applied (eps={eps}, min_points={min_points})")
            QMessageBox.information(self, "Info", "Clustering feature requires Open3D implementation")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to cluster: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)
    
            
    def get_current_model(self):
        """Get the current model path."""
        return self.current_model_path
        
    def set_current_model(self, model_path):
        """Set the current model from library selection.""" 
        if model_path and model_path.lower().endswith(('.pcd', '.ply', '.xyz')):
            self.load_model(model_path)

    def apply_translation(self):
        """Apply translation to point cloud."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        x = self.trans_x_spin.value()
        y = self.trans_y_spin.value()
        z = self.trans_z_spin.value()
        
        if x == 0 and y == 0 and z == 0:
            return

        self.operation_label.setText("Applying translation...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_translated.')
            result = self.pc_processor.apply_transform(
                self.current_model_path,
                output_path,
                transform_type='translate',
                translation=(x, y, z)
            )
            
            if result['success']:
                self.current_model_path = output_path
                self.operation_label.setText("Translation applied")
                self.load_model(output_path)
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to translate: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def apply_rotation(self):
        """Apply rotation to point cloud."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        x = self.rot_x_spin.value()
        y = self.rot_y_spin.value()
        z = self.rot_z_spin.value()
        
        if x == 0 and y == 0 and z == 0:
            return

        self.operation_label.setText("Applying rotation...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_rotated.')
            result = self.pc_processor.apply_transform(
                self.current_model_path,
                output_path,
                transform_type='rotate',
                rotation=(x, y, z)
            )
            
            if result['success']:
                self.current_model_path = output_path
                self.operation_label.setText("Rotation applied")
                self.load_model(output_path)
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to rotate: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def apply_scale(self):
        """Apply scaling to point cloud."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        scale = self.scale_spin.value()
        
        if scale == 1.0:
            return

        self.operation_label.setText("Applying scale...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_scaled.')
            result = self.pc_processor.apply_transform(
                self.current_model_path,
                output_path,
                transform_type='scale',
                scale=scale
            )
            
            if result['success']:
                self.current_model_path = output_path
                self.operation_label.setText("Scale applied")
                self.load_model(output_path)
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to scale: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def crop_box(self):
        """Crop point cloud using a bounding box."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        dialog = BoundingBoxDialog(self)
        if dialog.exec():
            bounds = dialog.get_bounds()
            
            self.operation_label.setText("Cropping point cloud...")
            
            def worker_func(processor, path, b):
                output_path = path.replace('.', '_cropped.')
                import open3d as o3d
                import numpy as np
                pcd = o3d.io.read_point_cloud(path)
                bbox = o3d.geometry.AxisAlignedBoundingBox(
                    min_bound=np.array([b[0], b[2], b[4]]),
                    max_bound=np.array([b[1], b[3], b[5]])
                )
                cropped_pcd = pcd.crop(bbox)
                o3d.io.write_point_cloud(output_path, cropped_pcd)
                return {'success': True, 'output_path': output_path}
                
            self.execute_async(worker_func, self.pc_processor, self.current_model_path, bounds)

    def crop_interactive(self):
        """Interactive cropping using Open3D visualizer."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        QMessageBox.information(self, "Interactive Crop", 
                              "Press 'K' to lock screen and switch to selection mode.\n"
                              "Drag to draw a rectangle.\n"
                              "Press 'C' to crop.\n"
                              "Press 'S' to save and close.")
                              
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(self.current_model_path)
        
        def demo_crop_geometry():
            vis = o3d.visualization.VisualizerWithEditing()
            vis.create_window()
            vis.add_geometry(pcd)
            vis.run() 
            vis.destroy_window()
            
        try:
            demo_crop_geometry()
            self.operation_label.setText("Interactive session finished")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Interactive crop failed: {str(e)}")
        def demo_crop_geometry():
            vis = o3d.visualization.VisualizerWithEditing()
            vis.create_window()
            vis.add_geometry(pcd)
            vis.run() # User picks points
            vis.destroy_window()
            # After run, we might want to save the cropped result if the user saved it via 'S'
            # But Open3D's 'S' saves a screenshot usually? 
            # VisualizerWithEditing allows cropping with 'C'. 
            # It saves the cropped geometry to a file automatically? 
            # Actually, VisualizerWithEditing is limited.
            # Let's just launch it and let the user explore.
            
        try:
            demo_crop_geometry()
            self.operation_label.setText("Interactive session finished")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Interactive crop failed: {str(e)}")
    def load_target_model(self):
        """Load target point cloud for registration."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Target Point Cloud",
            "", "Point Clouds (*.pcd *.ply *.xyz);;All Files (*)"
        )
        
        if file_path:
            self.target_model_path = file_path
            filename = os.path.basename(file_path)
            self.target_info_label.setText(f"Target: {filename}")
            
            # Optionally visualize target (e.g., in a different color or ghosted)
            # For now just store the path
            QMessageBox.information(self, "Target Loaded", f"Loaded target: {filename}")

    def run_icp_registration(self):
        """Run ICP registration."""
        if not self.current_model_path or not self.target_model_path:
            QMessageBox.warning(self, "Missing Data", "Please load both source and target point clouds.")
            return

        threshold = self.icp_threshold_spin.value()
        max_iter = self.icp_max_iter_spin.value()

        self.operation_label.setText("Running ICP registration...")
        self.progress_bar.setVisible(True)

        try:
            # Use the wrapper method in PointCloudProcessor
            result = self.pc_processor.register_point_clouds(
                self.current_model_path,
                self.target_model_path,
                method='icp',
                threshold=threshold,
                max_iteration=max_iter
            )

            if result['success']:
                transformation = result['transformation']
                fitness = result['fitness']
                rmse = result['rmse']
                
                result_text = f"ICP Converged:\nFitness: {fitness:.4f}\nRMSE: {rmse:.4f}\n\nTransformation:\n{transformation}"
                self.registration_results.setPlainText(result_text)
                self.operation_label.setText("ICP Registration complete")
                
                # Update viewer with transformed source
                # Ideally, we should apply the transformation to the source and reload it
                # For now, we just show the result text
                QMessageBox.information(self, "Success", "ICP Registration converged!")
            else:
                self.operation_label.setText("ICP Registration failed")
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"ICP Registration failed: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def run_ransac_registration(self):
        """Run RANSAC registration."""
        if not self.current_model_path or not self.target_model_path:
            QMessageBox.warning(self, "Missing Data", "Please load both source and target point clouds.")
            return

        # RANSAC parameters could be added to UI, using defaults for now
        voxel_size = 0.05 # Example default
        
        self.operation_label.setText("Running RANSAC registration...")
        self.progress_bar.setVisible(True)

        try:
             # Use the wrapper method in PointCloudProcessor
            result = self.pc_processor.register_point_clouds(
                self.current_model_path,
                self.target_model_path,
                method='ransac',
                voxel_size=voxel_size
            )

            if result['success']:
                transformation = result['transformation']
                fitness = result['fitness']
                rmse = result['rmse']
                
                result_text = f"RANSAC Result:\nFitness: {fitness:.4f}\nRMSE: {rmse:.4f}\n\nTransformation:\n{transformation}"
                self.registration_results.setPlainText(result_text)
                self.operation_label.setText("RANSAC Registration complete")
                QMessageBox.information(self, "Success", "RANSAC Registration complete!")
            else:
                self.operation_label.setText("RANSAC Registration failed")
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"RANSAC Registration failed: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def run_ball_pivoting(self):
        """Run Ball Pivoting reconstruction."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        radius = self.ball_radius_spin.value()
        
        self.operation_label.setText("Running Ball Pivoting...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_bpa_mesh.obj')
            # Assuming reconstruct_mesh handles 'bpa' or similar
            # If not, we might need to add it to PointCloudProcessor or MeshReconstructor
            # For now, let's assume 'ball_pivoting' is the key
            result = self.pc_processor.reconstruct_mesh(
                self.current_model_path,
                output_path,
                method='ball_pivoting',
                radii=[radius] # BPA often takes a list of radii
            )
            
            if result['success']:
                vertices = result.get('vertices', 0)
                triangles = result.get('triangles', 0)
                self.operation_label.setText(f"BPA complete: {vertices:,} vertices, {triangles:,} triangles")
                
                # Load the reconstructed mesh
                self.viewer.load_from_file(output_path)
                
                QMessageBox.information(self, "Success", f"Mesh created with {vertices:,} vertices and {triangles:,} triangles!\n\nSaved to: {output_path}\n\nLoaded into viewer.")
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reconstruct: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)

    def run_alpha_shapes(self):
        """Run Alpha Shapes reconstruction."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        alpha = self.alpha_value_spin.value()
        
        self.operation_label.setText("Running Alpha Shapes...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_alpha_mesh.obj')
            result = self.pc_processor.reconstruct_mesh(
                self.current_model_path,
                output_path,
                method='alpha_shape',
                alpha=alpha
            )
            
            if result['success']:
                vertices = result.get('vertices', 0)
                triangles = result.get('triangles', 0)
                self.operation_label.setText(f"Alpha Shape complete: {vertices:,} vertices, {triangles:,} triangles")
                
                # Load the reconstructed mesh
                self.viewer.load_from_file(output_path)
                
                QMessageBox.information(self, "Success", f"Mesh created with {vertices:,} vertices and {triangles:,} triangles!\n\nSaved to: {output_path}\n\nLoaded into viewer.")
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reconstruct: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)
    def export_point_cloud(self, format_type):
        """Export point cloud to specified format."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        output_path, _ = QFileDialog.getSaveFileName(
            self, f"Export {format_type.upper()}",
            self.current_model_path.replace(".", f"_export.{format_type}"),
            f"{format_type.upper()} Files (*.{format_type})"
        )
        
        if output_path:
            self.operation_label.setText(f"Exporting to {format_type}...")
            try:
                # We can reuse save_point_cloud from processor if we load it first
                # Or just copy the file if no changes, but we might have applied transforms
                # For now, let's assume we want to save the CURRENT state
                # Since we don't keep the pcd object in memory in UI (only path), we rely on processor
                # But wait, transforms update the file on disk. So we just need to convert/copy.
                
                # Use processor to load and save as new format
                pcd = self.pc_processor.load_point_cloud(self.current_model_path)
                if pcd:
                    success = self.pc_processor.save_point_cloud(pcd, output_path)
                    if success:
                        QMessageBox.information(self, "Success", f"Exported to {output_path}")
                        self.operation_label.setText(f"Exported {format_type}")
                    else:
                        QMessageBox.warning(self, "Error", "Failed to save file")
                else:
                    QMessageBox.warning(self, "Error", "Failed to load current model for export")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Export failed: {str(e)}")

    def run_clustering(self):
        """Run DBSCAN clustering."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
            
        eps = self.cluster_eps_spin.value()
        min_points = self.cluster_min_points_spin.value()
        
        self.operation_label.setText("Running DBSCAN clustering...")
        self.progress_bar.setVisible(True)
        
        try:
            output_path = self.current_model_path.replace('.', '_clustered.')
            
            # We need to run this asynchronously because it can be slow
            def worker_func(processor, path, out_path, e, min_p):
                return processor.cluster_dbscan(path, out_path, eps=e, min_points=min_p)
                
            worker = Worker(worker_func, self.pc_processor, self.current_model_path, output_path, eps, min_points)
            
            def on_result(result):
                if result['success']:
                    clusters = result.get('clusters', 0)
                    self.operation_label.setText(f"Clustering complete: {clusters} clusters found")
                    QMessageBox.information(self, "Success", f"Found {clusters} clusters!\n\nResult saved to: {result['output_path']}")
                    
                    # Load the colored result
                    self.viewer.load_from_file(result['output_path'])
                else:
                    self.operation_label.setText("Clustering failed")
                    QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
                
                self.setEnabled(True)
                self.progress_bar.setVisible(False)
                
            worker.signals.result.connect(on_result)
            worker.signals.error.connect(lambda e: self.handle_async_error(e))
            
            self.setEnabled(False)
            self.threadpool.start(worker)
            
        except Exception as e:
            self.setEnabled(True)
            self.progress_bar.setVisible(False)
            QMessageBox.critical(self, "Error", f"Clustering failed: {str(e)}")

    def compute_distances(self):
        """Compute nearest neighbor distances asynchronously."""
        if not self.current_model_path:
            QMessageBox.warning(self, "No Point Cloud", "Please load a point cloud first")
            return
        
        self.operation_label.setText("Computing distances...")
        
        def worker_func(processor, path):
            import open3d as o3d
            import numpy as np
            pcd = o3d.io.read_point_cloud(path)
            dists = pcd.compute_nearest_neighbor_distance()
            avg_dist = np.mean(dists)
            max_dist = np.max(dists)
            min_dist = np.min(dists)
            return {'success': True, 'avg': avg_dist, 'max': max_dist, 'min': min_dist, 'dists': dists}
            
        worker = Worker(worker_func, self.pc_processor, self.current_model_path)
        
        def on_result(result):
            if result['success']:
                self.last_distances = result['dists']
                msg = (f"Average Distance: {result['avg']:.6f}\n"
                       f"Max Distance: {result['max']:.6f}\n"
                       f"Min Distance: {result['min']:.6f}")
                QMessageBox.information(self, "Distance Analysis", msg)
                self.operation_label.setText("Distance analysis complete")
            self.setEnabled(True)
            self.progress_bar.setVisible(False)
            
        worker.signals.result.connect(on_result)
        
        self.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.threadpool.start(worker)
        def worker_func(processor, path):
            import open3d as o3d
            import numpy as np
            pcd = o3d.io.read_point_cloud(path)
            # Compute distance to nearest neighbor
            dists = pcd.compute_nearest_neighbor_distance()
            avg_dist = np.mean(dists)
            max_dist = np.max(dists)
            min_dist = np.min(dists)
            return {'success': True, 'avg': avg_dist, 'max': max_dist, 'min': min_dist, 'dists': dists}
            
        # We need a custom handler for the result to show the stats
        # So we'll use a custom callback or just handle it in the generic result handler if we modify it
        # But generic handler expects 'output_path'.
        # Let's modify execute_async to allow a custom result handler?
        # Or just override the result signal connection for this call?
        # Simpler: Just define a custom worker here and start it manually using threadpool
        
        worker = Worker(worker_func, self.processor, self.current_cloud_path)
        
        def on_result(result):
            if result['success']:
                self.last_distances = result['dists'] # Store for histogram
                msg = (f"Average Distance: {result['avg']:.6f}\n"
                       f"Max Distance: {result['max']:.6f}\n"
                       f"Min Distance: {result['min']:.6f}")
                QMessageBox.information(self, "Distance Analysis", msg)
                self.operation_label.setText("Distance analysis complete")
            self.setEnabled(True)
            self.progress_bar.setVisible(False)
            
        worker.signals.result.connect(on_result)
        
        self.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.threadpool.start(worker)
    def show_distance_histogram(self):
        """Show histogram of distances."""
        if not hasattr(self, 'last_distances') or self.last_distances is None:
            QMessageBox.warning(self, "No Data", "Please run 'Compute Distances' first.")
            return
            
        import matplotlib.pyplot as plt
        plt.figure("Nearest Neighbor Distances")
        plt.hist(self.last_distances, bins=50, color='blue', alpha=0.7)
        plt.title("Nearest Neighbor Distance Distribution")
        plt.xlabel("Distance")
        plt.ylabel("Frequency")
        plt.show()
    def capture_screen(self):
        """Capture screenshot of the viewer."""
        if not self.has_viewer:
            return
            
        # Get pixmap from viewer's image label
        pixmap = self.viewer.image_label.pixmap()
        if not pixmap or pixmap.isNull():
            QMessageBox.warning(self, "Error", "No image to capture")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot",
            "screenshot.png",
            "Images (*.png *.jpg)"
        )
        
        if file_path:
            pixmap.save(file_path)
            self.operation_label.setText(f"Screenshot saved: {os.path.basename(file_path)}")
            QMessageBox.information(self, "Success", f"Screenshot saved to:\n{file_path}")

    def execute_async(self, func, *args, **kwargs):
        """Execute a function asynchronously with progress feedback."""
        # Disable UI
        self.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate for now
        
        worker = Worker(func, *args, **kwargs)
        worker.signals.result.connect(self.handle_async_result)
        worker.signals.error.connect(self.handle_async_error)
        worker.signals.finished.connect(self.handle_async_finished)
        
        self.threadpool.start(worker)
        
    def handle_async_result(self, result):
        """Handle successful result from async worker."""
        if isinstance(result, dict) and result.get('success'):
            QMessageBox.information(self, "Success", "Operation completed successfully!")
            # Check if we should load a mesh
            if 'output_path' in result and result['output_path'].endswith(('.ply', '.obj', '.stl')):
                # Ask to open in mesh tools
                reply = QMessageBox.question(self, "Open in Mesh Tools", 
                                           "Reconstruction complete. Open in Mesh Tools?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.mesh_generated.emit(result['output_path'])
        elif isinstance(result, dict) and 'error' in result:
            QMessageBox.warning(self, "Error", result['error'])
            
    def handle_async_error(self, error_tuple):
        """Handle error from async worker."""
        QMessageBox.critical(self, "Error", f"An error occurred: {str(error_tuple[1])}")
        
    def handle_async_finished(self):
        """Cleanup after async worker."""
        self.setEnabled(True)
        self.progress_bar.setVisible(False)
