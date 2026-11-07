"""
Unified Open3D Viewer Widget for RenderFox.
Designed to be embedded in Mesh Tools and Point Clouds tabs.
Provides a static preview with an option to launch a full interactive window.
"""

import os
import logging
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QSizePolicy, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize
from PyQt6.QtGui import QImage, QPixmap, QColor
from src.core.worker_base import SafeWorker
from ..utils.run_teardown import drain_attributes

try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False

# The packaged build has no console (`RenderFox.spec`: console=False), so the only report
# channel a failure has is the root logger the Diagnostics pane reads.
logger = logging.getLogger(__name__)

class PreviewWorker(SafeWorker):
    """Background worker to render the Open3D preview to an image."""
    image_ready = pyqtSignal(QImage)
    
    def __init__(self, geometry_list, width, height, settings):
        super().__init__()
        self.geometry_list = geometry_list
        self.width = width
        self.height = height
        self.settings = settings

    def safe_run(self):
        if not self.geometry_list:
            return

        vis = o3d.visualization.Visualizer()
        vis.create_window(visible=False, width=self.width, height=self.height)

        # Add geometries
        # Add geometries
        for geom in self.geometry_list:
            # Logic:
            # 1. If show_wireframe is True: Render ONLY wireframe (LineSet)
            # 2. If show_wireframe is False: Render Mesh (with optional colors)
            # 3. If show_edges is True (and not wireframe mode): Enable wireframe overlay
            
            if self.settings.get('show_wireframe', False):
                # Wireframe Mode: Convert to LineSet
                try:
                    if hasattr(geom, 'has_triangles') and geom.has_triangles():
                        line_set = o3d.geometry.LineSet.create_from_triangle_mesh(geom)
                        # Paint lines black or white depending on bg? Let's use a high contrast color or default
                        # Default is usually black lines. Let's make them light grey for dark bg
                        line_set.paint_uniform_color([0.8, 0.8, 0.8])
                        vis.add_geometry(line_set)
                    else:
                        # Point cloud or other
                        vis.add_geometry(geom)
                except Exception as e:
                    logger.warning("Wireframe conversion failed: %s", e)
                    vis.add_geometry(geom)
            else:
                # Solid Mode
                if not self.settings.get('show_colors', True):
                    # Grey mode
                    import copy
                    try:
                        geom_copy = copy.deepcopy(geom)
                    except:
                        geom_copy = geom
                    
                    if hasattr(geom_copy, 'paint_uniform_color'):
                        geom_copy.paint_uniform_color([0.7, 0.7, 0.7])
                    vis.add_geometry(geom_copy)
                else:
                    # Color mode
                    vis.add_geometry(geom)

        # Apply settings
        opt = vis.get_render_option()
        opt.background_color = np.asarray(self.settings.get('bg_color', [0.1, 0.1, 0.1]))
        opt.point_size = self.settings.get('point_size', 3.0)
        opt.line_width = self.settings.get('line_width', 1.0)
        opt.show_coordinate_frame = self.settings.get('show_axis', False)
        
        # Lighting
        opt.light_on = self.settings.get('use_lighting', True)
        
        # Advanced visualization
        # Note: mesh_show_wireframe controls the OVERLAY on the solid mesh
        opt.mesh_show_wireframe = self.settings.get('show_edges', False)
        opt.point_show_normal = self.settings.get('show_normals', False)

        # Camera setup (simple auto-center)
        vis.reset_view_point(True)
        
        # Render
        vis.poll_events()
        vis.update_renderer()
        
        # Capture
        image_float = vis.capture_screen_float_buffer(do_render=True)
        image_np = (np.asarray(image_float) * 255).astype(np.uint8)
        
        # Convert to QImage
        h, w, c = image_np.shape
        bytes_per_line = c * w
        q_img = QImage(image_np.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        self.image_ready.emit(q_img.copy())
        
        vis.destroy_window()

class UnifiedOpen3DViewer(QWidget):
    """
    A unified widget for viewing Meshes and Point Clouds using Open3D.
    Features:
    - Embedded static preview (non-blocking)
    - interactive popup window
    - Support for multiple geometries
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.geometries = []  # List of Open3D geometries
        self.current_settings = {
            'bg_color': [0.15, 0.15, 0.15],
            'point_size': 2.0,
            'line_width': 1.0,
            'show_axis': True,
            'use_lighting': True,
            'show_colors': True,
            'show_wireframe': False,
            'show_edges': False,
            'show_normals': False
        }
        self.preview_worker = None
        
        self.init_ui()

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Silence the preview render in flight and wait for it to finish.

        This widget is embedded - in Mesh Tools, in Point Clouds, in the Quality
        pane - so the tab that hosts it can be closed while its own `refresh_preview` is
        still off-screen rendering, and `image_ready` then writes a pixmap into a label
        that has already gone. The render takes one image and cannot be stopped part-way,
        so it is waited on; a render that outlasts the wait stays in `preview_worker`,
        because its reference is what keeps Qt from aborting on a live thread.
        Returns the previews still owed when the wait gave up.
        """
        return len(drain_attributes(self, ('preview_worker',), timeout_ms))

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Preview Container
        self.preview_frame = QFrame()
        self.preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_frame.setStyleSheet("background-color: #222; border-radius: 4px;")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        # Image Label
        self.image_label = QLabel("No Geometry Loaded")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("color: #888; font-size: 12px;")
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setMinimumHeight(300)
        # self.image_label.setScaledContents(True)
        preview_layout.addWidget(self.image_label)
        
        from .icon_provider import get_icon
        # Overlay Controls
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(5, 5, 5, 5)
        
        self.btn_refresh = QPushButton("Refresh Preview")
        self.btn_refresh.setIcon(get_icon("camera"))
        self.btn_refresh.setToolTip("Update the static preview")
        self.btn_refresh.clicked.connect(self.refresh_preview)
        
        self.btn_interactive = QPushButton("Interactive View")
        self.btn_interactive.setIcon(get_icon("models"))
        self.btn_interactive.setProperty("primary", "true")
        self.btn_interactive.setToolTip("Open full interactive 3D window")
        self.btn_interactive.clicked.connect(self.open_interactive_viewer)
        
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setIcon(get_icon("delete"))
        self.btn_clear.clicked.connect(self.clear)
        
        controls_layout.addWidget(self.btn_refresh)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_clear)
        controls_layout.addWidget(self.btn_interactive)
        
        layout.addWidget(self.preview_frame, 1)
        layout.addLayout(controls_layout)
        
        # Loading indicator
        self.progress = QProgressBar()
        self.progress.setRange(0, 0) # Indeterminate
        self.progress.setFixedHeight(2)
        self.progress.hide()
        layout.addWidget(self.progress)

        if not OPEN3D_AVAILABLE:
            self.image_label.setText("Open3D not installed.\nVisualization unavailable.")
            self.btn_refresh.setEnabled(False)
            self.btn_interactive.setEnabled(False)

    def add_geometry(self, geometry, clear_existing=True):
        """
        Add an Open3D geometry (Mesh or PointCloud).
        geometry: open3d.geometry.TriangleMesh or open3d.geometry.PointCloud
        """
        if not OPEN3D_AVAILABLE:
            return

        if clear_existing:
            self.geometries = []
            
        self.geometries.append(geometry)
        self.refresh_preview()

    def load_from_file(self, file_path):
        """Show a file as a surface if it has faces, as points if it has only points.

        The choice used to be `has_vertices()`, which is wrong in both directions on the
        files this pane works with. A scanned .ply has vertices and no triangles, so a faceless
        mesh was handed to the previewer, which renders a mesh by its triangles and showed a
        blank panel while the caller was told the load succeeded. And `PointCloud` has no
        `has_vertices` at all - only `has_points` - so every .pcd raised AttributeError inside
        here and answered False, which is why the Point Clouds pane could never show the files
        it exists for. Triangles are the one thing that separates the two kinds of file.
        """
        if not OPEN3D_AVAILABLE:
            return False

        try:
            mesh = o3d.io.read_triangle_mesh(file_path)
            if mesh.has_triangles():
                self.add_geometry(mesh)
                return True
            cloud = o3d.io.read_point_cloud(file_path)
            if cloud.has_points():
                self.add_geometry(cloud)
                return True
        except Exception as e:
            logger.warning("Failed to load %s: %s", file_path, e)
        return False

    def fit_to_view(self):
        """Render the preview again so the geometry fills the panel it is in now.

        The preview is a single static image, and its camera is re-framed to the geometry on
        every render, so the way this view "goes out of frame" is the panel being resized
        under a pixmap made for the old size. Re-rendering at the label's current size puts
        that right. False means there is no geometry to frame, which the button reports
        instead of showing the same picture twice.
        """
        if not self.geometries:
            return False
        self.refresh_preview()
        return True

    def preview_pixmap(self):
        """The image on screen, or None when there is nothing here to save."""
        pixmap = self.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        return pixmap

    def clear(self):
        self.geometries = []
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("No Geometry Loaded")

    def refresh_preview(self):
        """Trigger background render."""
        if not self.geometries or not OPEN3D_AVAILABLE:
            return

        if self.preview_worker and self.preview_worker.isRunning():
            return # Skip if busy

        self.progress.show()
        self.image_label.setText("Rendering Preview...")
        
        # Get current size
        w = self.image_label.width()
        h = self.image_label.height()
        
        # Clamp size to avoid massive renders
        w = min(w, 1920)
        h = min(h, 1080)
        
        self.preview_worker = PreviewWorker(self.geometries, w, h, self.current_settings)
        self.preview_worker.image_ready.connect(self._on_preview_ready)
        self.preview_worker.error_occurred.connect(self._on_preview_failed)
        self.preview_worker.finished.connect(self.progress.hide)
        self.preview_worker.start()

    def _on_preview_ready(self, q_img):
        self.image_label.setPixmap(QPixmap.fromImage(q_img))
        self.image_label.setText("")

    def _on_preview_failed(self, reason):
        """Say why the panel is empty.

        `PreviewWorker` already reports a failed render on `error_occurred`; nothing here
        was listening, so a render that died left the words "Rendering Preview..." on
        screen forever - the one state that reads as work in progress and is really work
        that stopped. Every pane that embeds this viewer inherits the sentence.
        """
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(f"Preview did not render: {reason}")

    def open_interactive_viewer(self):
        """Launch the blocking Open3D visualizer."""
        if not self.geometries or not OPEN3D_AVAILABLE:
            return
            
        def run_vis():
            vis = o3d.visualization.Visualizer()
            vis.create_window(window_name="RenderFox Interactive View", width=1280, height=720)
            
            for geom in self.geometries:
                vis.add_geometry(geom)
                
            # Apply settings
            opt = vis.get_render_option()
            opt.background_color = np.asarray(self.current_settings['bg_color'])
            opt.point_size = self.current_settings['point_size']
            opt.line_width = self.current_settings['line_width']
            opt.show_coordinate_frame = self.current_settings['show_axis']
            
            vis.run()
            vis.destroy_window()

        # Open3D run() blocks the thread. 
        # Ideally we run this in a separate process or thread, but Open3D GUI often needs main thread.
        # For now, we accept it blocks the UI (standard Open3D behavior without complex multiprocessing).
        # We can try running it directly.
        try:
            run_vis()
        except Exception as e:
            logger.warning("Interactive viewer error: %s", e)

    def set_point_size(self, size):
        self.current_settings['point_size'] = float(size)
        self.refresh_preview()

    def set_background_color(self, r, g, b):
        self.current_settings['bg_color'] = [r, g, b]
        self.refresh_preview()

    def set_show_colors(self, enabled):
        self.current_settings['show_colors'] = enabled
        self.refresh_preview()

    def set_show_wireframe(self, enabled):
        self.current_settings['show_wireframe'] = enabled
        self.refresh_preview()

    def set_show_edges(self, enabled):
        self.current_settings['show_edges'] = enabled
        self.refresh_preview()

    def set_show_normals(self, enabled):
        self.current_settings['show_normals'] = enabled
        self.refresh_preview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Optional: Auto-refresh on resize? Might be too heavy.

    def reset_view(self):
        """Reset the view to default (re-centers camera)."""
        self.refresh_preview()
