"""
Advanced 3D Model viewer using Open3D with comprehensive features and controls.
"""

import os
import numpy as np
import tempfile
import threading
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QCheckBox, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QWheelEvent, QMouseEvent, QPixmap
import trimesh

# Try to import Open3D
try:
    import open3d as o3d
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="open3d")
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False

class ModelViewer3D_Open3D(QWidget):
    """Advanced 3D model viewer using Open3D with comprehensive features."""
    
    model_loaded = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        if not OPEN3D_AVAILABLE:
            self.init_fallback_ui()
            return
            
        # Model data
        self.meshes = []  # List of Open3D geometries
        self.wireframe_meshes = []  # Separate wireframe geometries for color control
        self.original_meshes = []  # Store original mesh state for rotation reset
        self.current_file_path = None
        self.model_bounds = None
        
        # Store original colors and textures for proper toggling
        self.original_vertex_colors = []  # Store original vertex colors for each mesh
        self.original_textures = []  # Store original texture info
        self.has_vertex_colors = []  # Track which meshes have vertex colors
        self.has_textures = []  # Track which meshes have textures
        
        # Rendering settings
        self.render_mode = 'fill'  # 'fill', 'wireframe', 'points', 'overlay'
        self.use_lighting = True
        self.use_vertex_colors = True
        self.use_textures = True
        self.show_coordinate_frame = False
        self.show_bounding_box = False
        self.show_normals = False
        self.point_size = 3.0
        self.line_width = 1.0
        
        # Colors
        self.background_color = [0.1, 0.1, 0.1]  # Dark gray
        self.mesh_color = [0.7, 0.7, 0.9]  # Light blue
        self.wireframe_color = [0.0, 1.0, 0.0]  # Green
        self.point_color = [1.0, 1.0, 1.0]  # White
        
        # Lighting parameters
        self.ambient_light = 0.3
        self.diffuse_light = 0.7
        self.specular_light = 0.5
        
        # Auto-rotation
        self.auto_rotate = False
        self.rotation_speed = 1.0
        self.rotation_angle = 0.0  # Current rotation angle
        self.rotation_timer = QTimer()
        self.rotation_timer.timeout.connect(self.auto_rotation_step)
        
        # Visualization objects
        self.coordinate_frame = None
        self.bounding_box_lines = None
        self.normal_lines = None
        
        self.init_ui()
    
    def init_fallback_ui(self):
        """Initialize fallback UI when Open3D is not available."""
        layout = QVBoxLayout(self)
        
        self.info_display = QTextEdit()
        self.info_display.setMaximumHeight(200)
        self.info_display.setReadOnly(True)
        layout.addWidget(self.info_display)
        
        fallback_label = QLabel("Open3D Viewer Unavailable")
        fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fallback_label.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                color: #ffffff;
                font-size: 16px;
                border: 2px dashed #555555;
                min-height: 400px;
            }
        """)
        layout.addWidget(fallback_label)
        
        status_label = QLabel("Install Open3D for advanced 3D preview:\npip install open3d")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet("color: #cc6600; padding: 10px;")
        layout.addWidget(status_label)
    
    def init_ui(self):
        """Initialize the main UI."""
        layout = QVBoxLayout(self)
        
        # Create preview area for thumbnail
        self.preview_label = QLabel("No model loaded")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(400)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 2px solid #444444;
                font-size: 14px;
            }
        """)
        layout.addWidget(self.preview_label)
        
        # Control buttons
        controls_layout = QHBoxLayout()
        
        self.open_viewer_btn = QPushButton("Open 3D Viewer")
        self.open_viewer_btn.clicked.connect(self.open_3d_viewer)
        self.open_viewer_btn.setEnabled(False)
        
        self.refresh_btn = QPushButton("Refresh Preview")
        self.refresh_btn.clicked.connect(self.refresh_preview)
        self.refresh_btn.setEnabled(False)
        
        self.export_image_btn = QPushButton("Export Image")
        self.export_image_btn.clicked.connect(self.export_image)
        self.export_image_btn.setEnabled(False)
        
        controls_layout.addWidget(self.open_viewer_btn)
        controls_layout.addWidget(self.refresh_btn)
        controls_layout.addWidget(self.export_image_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Info panel
        self.info_label = QLabel("No model loaded")
        self.info_label.setStyleSheet("background: #f0f0f0; padding: 5px; margin: 2px;")
        layout.addWidget(self.info_label)
    
    def load_model(self, file_path: str) -> bool:
        """Load a 3D model file using Open3D."""
        if not OPEN3D_AVAILABLE:
            return False
        
        try:
            self.current_file_path = file_path
            self.meshes = []
            
            # Try loading with trimesh first for better format support
            try:
                scene_or_mesh = trimesh.load(file_path)
                meshes_data = []
                
                if isinstance(scene_or_mesh, trimesh.Scene):
                    for name, geom in (scene_or_mesh.geometry or {}).items():
                        if isinstance(geom, trimesh.Trimesh) and len(geom.faces) > 0:
                            meshes_data.append(geom)
                elif isinstance(scene_or_mesh, trimesh.Trimesh):
                    if len(scene_or_mesh.faces) > 0:
                        meshes_data.append(scene_or_mesh)
                
                # Convert trimesh to Open3D
                for trimesh_obj in meshes_data:
                    o3d_mesh = self._trimesh_to_open3d(trimesh_obj)
                    if o3d_mesh is not None:
                        self.meshes.append(o3d_mesh)
                        
            except Exception:
                # Fallback to direct Open3D loading
                try:
                    mesh = o3d.io.read_triangle_mesh(file_path)
                    if len(mesh.vertices) > 0:
                        self.meshes.append(mesh)
                    else:
                        # Try as point cloud
                        pcd = o3d.io.read_point_cloud(file_path)
                        if len(pcd.points) > 0:
                            self.meshes.append(pcd)
                except Exception:
                    pass
            
            if not self.meshes:
                return False
            
            # Process loaded meshes and store original color/texture state
            total_vertices = 0
            total_faces = 0
            all_bounds = []
            
            # Clear previous state
            self.original_vertex_colors = []
            self.original_textures = []
            self.has_vertex_colors = []
            self.has_textures = []
            
            for i, mesh in enumerate(self.meshes):
                # Center and normalize
                if hasattr(mesh, 'vertices'):
                    total_vertices += len(mesh.vertices)
                    if hasattr(mesh, 'triangles'):
                        total_faces += len(mesh.triangles)
                elif hasattr(mesh, 'points'):
                    total_vertices += len(mesh.points)
                
                # Compute bounds
                if hasattr(mesh, 'get_min_bound') and hasattr(mesh, 'get_max_bound'):
                    min_bound = mesh.get_min_bound()
                    max_bound = mesh.get_max_bound()
                    all_bounds.extend([min_bound, max_bound])
                
                # Ensure normals
                if hasattr(mesh, 'compute_vertex_normals'):
                    mesh.compute_vertex_normals()
                
                # Store original vertex colors if they exist
                has_vertex_colors = False
                original_vertex_colors = None
                if hasattr(mesh, 'vertex_colors') and len(mesh.vertex_colors) > 0:
                    original_vertex_colors = np.asarray(mesh.vertex_colors).copy()
                    has_vertex_colors = True
                    print(f"Mesh {i}: Found {len(original_vertex_colors)} vertex colors")
                
                self.original_vertex_colors.append(original_vertex_colors)
                self.has_vertex_colors.append(has_vertex_colors)
                
                # Store original texture info (placeholder for now)
                # Open3D doesn't have direct texture support like trimesh, but we can check for texture coordinates
                has_textures = False
                original_textures = None
                if hasattr(mesh, 'triangle_uvs') and len(mesh.triangle_uvs) > 0:
                    has_textures = True
                    original_textures = {'uvs': np.asarray(mesh.triangle_uvs).copy()}
                    print(f"Mesh {i}: Found texture coordinates")
                
                self.original_textures.append(original_textures)
                self.has_textures.append(has_textures)
                
                # Apply default material only if no vertex colors exist
                if (not has_vertex_colors and hasattr(mesh, 'vertex_colors') and 
                    len(mesh.vertex_colors) == 0 and hasattr(mesh, 'paint_uniform_color')):
                    mesh.paint_uniform_color(self.mesh_color)
                    print(f"Mesh {i}: Applied default color (no vertex colors found)")
            
            # Compute overall bounds
            if all_bounds:
                all_bounds = np.array(all_bounds)
                self.model_bounds = [all_bounds.min(axis=0), all_bounds.max(axis=0)]
                
                # Normalize all meshes
                center = (self.model_bounds[0] + self.model_bounds[1]) / 2
                size = np.max(self.model_bounds[1] - self.model_bounds[0])
                
                for mesh in self.meshes:
                    mesh.translate(-center)
                    if size > 0:
                        mesh.scale(2.0 / size, center=[0, 0, 0])
            
            # Store original meshes for rotation reset
            self.original_meshes = []
            for mesh in self.meshes:
                original_mesh = mesh.__copy__()
                self.original_meshes.append(original_mesh)
            
            # Generate preview
            self.generate_preview()
            
            # Enable controls
            self.open_viewer_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.export_image_btn.setEnabled(True)
            
            # Emit model info
            model_info = {
                'vertices': total_vertices,
                'faces': total_faces,
                'edges': 0,  # Open3D doesn't directly provide edges
                'bounds': self.model_bounds if self.model_bounds else [[0,0,0], [1,1,1]],
                'center': [0.0, 0.0, 0.0],  # Normalized to origin
                'is_watertight': self._check_watertight(),
                'volume': self._compute_volume(),
                'surface_area': self._compute_surface_area()
            }
            self.model_loaded.emit(model_info)
            
            return True
            
        except Exception as e:
            print(f"Error loading model with Open3D: {str(e)}")
            return False
    
    def _trimesh_to_open3d(self, trimesh_obj):
        """Convert trimesh object to Open3D mesh with vertex colors."""
        try:
            # Create Open3D mesh
            o3d_mesh = o3d.geometry.TriangleMesh()
            o3d_mesh.vertices = o3d.utility.Vector3dVector(trimesh_obj.vertices)
            o3d_mesh.triangles = o3d.utility.Vector3iVector(trimesh_obj.faces)
            
            # Handle vertex colors - improved extraction
            vertex_colors_found = False
            if hasattr(trimesh_obj, 'visual') and trimesh_obj.visual is not None:
                try:
                    vertex_colors = None
                    
                    # Method 1: Direct vertex colors
                    if hasattr(trimesh_obj.visual, 'vertex_colors') and trimesh_obj.visual.vertex_colors is not None:
                        vc = trimesh_obj.visual.vertex_colors
                        if len(vc) == len(trimesh_obj.vertices):
                            vertex_colors = vc
                            print(f"Method 1: Found {len(vc)} direct vertex colors")
                    
                    # Method 2: Convert from ColorVisuals
                    if vertex_colors is None:
                        try:
                            if hasattr(trimesh_obj.visual, 'to_color'):
                                color_visual = trimesh_obj.visual.to_color()
                                if hasattr(color_visual, 'vertex_colors') and color_visual.vertex_colors is not None:
                                    vc = color_visual.vertex_colors
                                    if len(vc) == len(trimesh_obj.vertices):
                                        vertex_colors = vc
                                        print(f"Method 2: Converted to {len(vc)} vertex colors")
                        except Exception as e:
                            print(f"Method 2 failed: {e}")
                    
                    # Method 3: Face colors to vertex colors (interpolate)
                    if vertex_colors is None and hasattr(trimesh_obj.visual, 'face_colors'):
                        fc = trimesh_obj.visual.face_colors
                        if fc is not None and len(fc) == len(trimesh_obj.faces):
                            print(f"Method 3: Converting {len(fc)} face colors to vertex colors")
                            # Create vertex colors by averaging face colors
                            vertex_colors = np.zeros((len(trimesh_obj.vertices), 4), dtype=np.float64)
                            vertex_count = np.zeros(len(trimesh_obj.vertices), dtype=np.int32)
                            
                            for i, face in enumerate(trimesh_obj.faces):
                                face_color = fc[i] if fc[i].dtype == np.float64 else fc[i].astype(np.float64) / 255.0
                                for vertex_idx in face:
                                    vertex_colors[vertex_idx] += face_color
                                    vertex_count[vertex_idx] += 1
                            
                            # Average the colors
                            for i in range(len(vertex_colors)):
                                if vertex_count[i] > 0:
                                    vertex_colors[i] /= vertex_count[i]
                    
                    # Method 4: Try material colors
                    if vertex_colors is None and hasattr(trimesh_obj.visual, 'material'):
                        material = trimesh_obj.visual.material
                        if hasattr(material, 'main_color') and material.main_color is not None:
                            main_color = material.main_color
                            if main_color.dtype == np.uint8:
                                main_color = main_color.astype(np.float64) / 255.0
                            # Apply single color to all vertices
                            vertex_colors = np.tile(main_color, (len(trimesh_obj.vertices), 1))
                            print(f"Method 4: Applied material color to {len(trimesh_obj.vertices)} vertices")
                    
                    # Apply vertex colors if found
                    if vertex_colors is not None:
                        # Ensure proper format
                        if vertex_colors.dtype == np.uint8:
                            vertex_colors = vertex_colors.astype(np.float64) / 255.0
                        
                        # Ensure RGB format (drop alpha if present)
                        if vertex_colors.shape[1] > 3:
                            vertex_colors = vertex_colors[:, :3]
                        elif vertex_colors.shape[1] < 3:
                            # If grayscale, replicate to RGB
                            vertex_colors = np.tile(vertex_colors, (1, 3))
                        
                        # Clamp values to [0,1] range
                        vertex_colors = np.clip(vertex_colors, 0.0, 1.0)
                        
                        o3d_mesh.vertex_colors = o3d.utility.Vector3dVector(vertex_colors)
                        vertex_colors_found = True
                        print(f"Successfully applied {len(vertex_colors)} vertex colors to Open3D mesh")
                        
                        # Debug: print color range
                        if len(vertex_colors) > 0:
                            print(f"Color range: R[{vertex_colors[:, 0].min():.3f}-{vertex_colors[:, 0].max():.3f}] "
                                  f"G[{vertex_colors[:, 1].min():.3f}-{vertex_colors[:, 1].max():.3f}] "
                                  f"B[{vertex_colors[:, 2].min():.3f}-{vertex_colors[:, 2].max():.3f}]")
                
                except Exception as e:
                    print(f"Warning: Could not extract vertex colors: {e}")
            
            if not vertex_colors_found:
                print("No vertex colors found - will use default material color")
            
            # Compute normals
            o3d_mesh.compute_vertex_normals()
            
            return o3d_mesh
            
        except Exception as e:
            print(f"Error converting trimesh to Open3D: {e}")
            return None
    
    def _create_wireframe_meshes(self):
        """Create wireframe line sets with custom color for each mesh."""
        self.wireframe_meshes = []
        
        for i, mesh in enumerate(self.meshes):
            if not hasattr(mesh, 'triangles') or len(mesh.triangles) == 0:
                self.wireframe_meshes.append(None)
                continue
                
            try:
                # Create wireframe from mesh edges
                wireframe = o3d.geometry.LineSet.create_from_triangle_mesh(mesh)
                # Apply wireframe color
                wireframe.paint_uniform_color(self.wireframe_color)
                self.wireframe_meshes.append(wireframe)
                print(f"Created wireframe for mesh {i} with color {self.wireframe_color}")
            except Exception as e:
                print(f"Failed to create wireframe for mesh {i}: {e}")
                self.wireframe_meshes.append(None)
    
    def _apply_render_settings(self, vis):
        """Apply current render settings to visualizer."""
        render_opt = vis.get_render_option()
        
        # Background
        render_opt.background_color = np.array(self.background_color)
        
        # Lighting
        render_opt.light_on = self.use_lighting
        
        # Point and line settings
        render_opt.point_size = self.point_size
        render_opt.line_width = self.line_width
        
        # Render mode specific settings
        if self.render_mode == 'wireframe':
            # Remove existing meshes and add wireframes only
            for mesh in self.meshes:
                vis.remove_geometry(mesh, reset_bounding_box=False)
            
            # Create and add wireframes if not already created
            if not self.wireframe_meshes or len(self.wireframe_meshes) != len(self.meshes):
                self._create_wireframe_meshes()
            
            # Add wireframes
            for wireframe in self.wireframe_meshes:
                if wireframe is not None:
                    vis.add_geometry(wireframe, reset_bounding_box=False)
                    
        elif self.render_mode == 'points':
            # Convert meshes to point clouds
            for i, mesh in enumerate(self.meshes):
                vis.remove_geometry(mesh, reset_bounding_box=False)
                if hasattr(mesh, 'sample_points_uniformly'):
                    pcd = mesh.sample_points_uniformly(number_of_points=10000)
                    pcd.paint_uniform_color(self.point_color)
                    vis.add_geometry(pcd, reset_bounding_box=False)
                    
        elif self.render_mode == 'overlay':
            # Show both fill and wireframe
            # Ensure meshes are added
            for mesh in self.meshes:
                vis.add_geometry(mesh, reset_bounding_box=False)
            
            # Create and add wireframes
            if not self.wireframe_meshes or len(self.wireframe_meshes) != len(self.meshes):
                self._create_wireframe_meshes()
            
            for wireframe in self.wireframe_meshes:
                if wireframe is not None:
                    vis.add_geometry(wireframe, reset_bounding_box=False)
                    
        else:  # 'fill' mode
            # Show only filled surfaces
            for mesh in self.meshes:
                vis.add_geometry(mesh, reset_bounding_box=False)
            render_opt.mesh_show_wireframe = False
    
    def generate_preview(self):
        """Generate a preview thumbnail of the model."""
        if not self.meshes:
            return
        
        vis = None
        try:
            # Create offscreen visualizer
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False, width=400, height=300)
            
            # Add geometries based on render mode
            if self.render_mode == 'wireframe':
                # Create and add wireframes only
                if not self.wireframe_meshes or len(self.wireframe_meshes) != len(self.meshes):
                    self._create_wireframe_meshes()
                
                for wireframe in self.wireframe_meshes:
                    if wireframe is not None:
                        vis.add_geometry(wireframe)
                        
            elif self.render_mode == 'points':
                # Convert to point clouds
                for i, mesh in enumerate(self.meshes):
                    if hasattr(mesh, 'sample_points_uniformly'):
                        pcd = mesh.sample_points_uniformly(number_of_points=10000)
                        # Use vertex colors if available, otherwise point color
                        if (self.use_vertex_colors and i < len(self.has_vertex_colors) and 
                            self.has_vertex_colors[i] and i < len(self.original_vertex_colors) and 
                            self.original_vertex_colors[i] is not None):
                            # Sample colors from original vertex colors
                            colors = self.original_vertex_colors[i]
                            if len(colors) > 0:
                                # Sample colors to match point cloud
                                indices = np.random.choice(len(colors), min(len(pcd.points), len(colors)), replace=True)
                                pcd.colors = o3d.utility.Vector3dVector(colors[indices])
                        else:
                            pcd.paint_uniform_color(self.point_color)
                        vis.add_geometry(pcd)
                        
            elif self.render_mode == 'overlay':
                # Add both meshes and wireframes
                for mesh in self.meshes:
                    vis.add_geometry(mesh)
                
                if not self.wireframe_meshes or len(self.wireframe_meshes) != len(self.meshes):
                    self._create_wireframe_meshes()
                
                for wireframe in self.wireframe_meshes:
                    if wireframe is not None:
                        vis.add_geometry(wireframe)
                        
            else:  # 'fill' mode
                for mesh in self.meshes:
                    vis.add_geometry(mesh)
            
            # Apply basic render settings
            render_opt = vis.get_render_option()
            render_opt.background_color = np.array(self.background_color)
            
            # Smart lighting: disable for vertex colors in fill mode to show true colors
            if self.render_mode == 'fill' and self.use_vertex_colors:
                # Check if any mesh has vertex colors
                has_any_vertex_colors = any(self.has_vertex_colors) if self.has_vertex_colors else False
                if has_any_vertex_colors:
                    render_opt.light_on = False  # Disable lighting to show true vertex colors
                    print("Disabled lighting to show vertex colors")
                else:
                    render_opt.light_on = self.use_lighting
            else:
                render_opt.light_on = self.use_lighting
                
            render_opt.point_size = self.point_size
            render_opt.line_width = self.line_width
            
            # Set camera view
            ctr = vis.get_view_control()
            ctr.set_front([0.5, -0.5, -0.5])
            ctr.set_lookat([0, 0, 0])
            ctr.set_up([0, 1, 0])
            ctr.set_zoom(0.8)
            
            # Render
            vis.poll_events()
            vis.update_renderer()
            
            # Capture image as numpy array
            image = vis.capture_screen_float_buffer(do_render=True)
            
            # Convert to QPixmap directly without temporary files
            if image is not None:
                image_np = (np.asarray(image) * 255).astype(np.uint8)
                
                # Convert directly to QPixmap using QImage
                from PyQt6.QtGui import QImage
                height, width, channels = image_np.shape
                bytes_per_line = channels * width
                
                # Create QImage from numpy array
                q_image = QImage(
                    image_np.data, 
                    width, 
                    height, 
                    bytes_per_line, 
                    QImage.Format.Format_RGB888
                )
                
                # Convert to QPixmap
                pixmap = QPixmap.fromImage(q_image)
                
                # Scale and display
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        self.preview_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.preview_label.setPixmap(scaled_pixmap)
                else:
                    self.preview_label.setText("Preview\nGeneration\nFailed")
            else:
                self.preview_label.setText("Preview\nGeneration\nFailed")
            
        except Exception as e:
            print(f"Failed to generate preview: {e}")
            self.preview_label.setText("Preview\nGeneration\nFailed")
        finally:
            # Ensure the visualizer is properly destroyed
            if vis is not None:
                try:
                    vis.destroy_window()
                except Exception:
                    pass
    
    def open_3d_viewer(self):
        """Open the interactive 3D viewer window."""
        if not self.meshes:
            return
        
        try:
            # Create visualizer
            vis = o3d.visualization.Visualizer()
            vis.create_window(
                window_name=f"RenderFox - {os.path.basename(self.current_file_path) if self.current_file_path else 'Model'}",
                width=1000,
                height=800
            )
            
            # Add all geometries
            for mesh in self.meshes:
                vis.add_geometry(mesh)
            
            # Add optional visualization elements
            if self.show_coordinate_frame:
                if self.coordinate_frame is None:
                    self.coordinate_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.5)
                vis.add_geometry(self.coordinate_frame)
            
            if self.show_bounding_box and self.model_bounds:
                if self.bounding_box_lines is None:
                    self._create_bounding_box()
                if self.bounding_box_lines:
                    vis.add_geometry(self.bounding_box_lines)
            
            # Apply render settings
            self._apply_render_settings(vis)
            
            # Set initial view
            ctr = vis.get_view_control()
            ctr.set_front([0.5, -0.5, -0.5])
            ctr.set_lookat([0, 0, 0])
            ctr.set_up([0, 1, 0])
            ctr.set_zoom(0.8)
            
            # Run viewer
            vis.run()
            vis.destroy_window()
            
        except Exception as e:
            print(f"Failed to open 3D viewer: {e}")
    
    def _create_bounding_box(self):
        """Create bounding box visualization."""
        if not self.model_bounds:
            return
        
        try:
            # Create bounding box as line set
            points = []
            lines = []
            
            min_bound, max_bound = self.model_bounds
            
            # Define 8 corners of bounding box
            corners = [
                [min_bound[0], min_bound[1], min_bound[2]],
                [max_bound[0], min_bound[1], min_bound[2]],
                [max_bound[0], max_bound[1], min_bound[2]],
                [min_bound[0], max_bound[1], min_bound[2]],
                [min_bound[0], min_bound[1], max_bound[2]],
                [max_bound[0], min_bound[1], max_bound[2]],
                [max_bound[0], max_bound[1], max_bound[2]],
                [min_bound[0], max_bound[1], max_bound[2]]
            ]
            
            # Define 12 edges
            edges = [
                [0, 1], [1, 2], [2, 3], [3, 0],  # Bottom face
                [4, 5], [5, 6], [6, 7], [7, 4],  # Top face
                [0, 4], [1, 5], [2, 6], [3, 7]   # Vertical edges
            ]
            
            self.bounding_box_lines = o3d.geometry.LineSet()
            self.bounding_box_lines.points = o3d.utility.Vector3dVector(corners)
            self.bounding_box_lines.lines = o3d.utility.Vector2iVector(edges)
            self.bounding_box_lines.paint_uniform_color([1, 0, 0])  # Red
            
        except Exception as e:
            print(f"Failed to create bounding box: {e}")
    
    def _check_watertight(self):
        """Check if the model is watertight."""
        for mesh in self.meshes:
            if hasattr(mesh, 'is_watertight'):
                try:
                    return mesh.is_watertight()
                except:
                    pass
        return False
    
    def _compute_volume(self):
        """Compute total volume of all meshes."""
        total_volume = 0.0
        for mesh in self.meshes:
            if hasattr(mesh, 'get_volume'):
                try:
                    total_volume += mesh.get_volume()
                except:
                    pass
        return float(total_volume)
    
    def _compute_surface_area(self):
        """Compute total surface area of all meshes."""
        total_area = 0.0
        for mesh in self.meshes:
            if hasattr(mesh, 'get_surface_area'):
                try:
                    total_area += mesh.get_surface_area()
                except:
                    pass
        return float(total_area)
    
    def refresh_preview(self):
        """Refresh the preview thumbnail."""
        self.generate_preview()
    
    def export_image(self):
        """Export current view as image."""
        # Implementation for exporting rendered image
        pass
    
    def clear(self):
        """Clear the loaded model."""
        self.meshes = []
        self.current_file_path = None
        self.model_bounds = None
        self.coordinate_frame = None
        self.bounding_box_lines = None
        self.normal_lines = None
        
        self.preview_label.clear()
        self.preview_label.setText("No model loaded")
        self.info_label.setText("No model loaded")
        
        self.open_viewer_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.export_image_btn.setEnabled(False)
    
    def auto_rotation_step(self):
        """Perform auto-rotation step by rotating just the model geometry."""
        if not self.auto_rotate or not self.meshes:
            return
        
        # Increment rotation angle
        self.rotation_angle += self.rotation_speed * 2.0  # degrees per step
        if self.rotation_angle >= 360.0:
            self.rotation_angle = 0.0
        
        # Create small rotation increment around Y axis
        angle_increment = np.radians(self.rotation_speed * 2.0)
        rotation_matrix = np.array([
            [np.cos(angle_increment), 0, np.sin(angle_increment)],
            [0, 1, 0],
            [-np.sin(angle_increment), 0, np.cos(angle_increment)]
        ])
        
        # Apply incremental rotation to all meshes (no reset needed)
        for mesh in self.meshes:
            if hasattr(mesh, 'rotate'):
                mesh.rotate(rotation_matrix, center=[0, 0, 0])
        
        # Also rotate wireframes if they exist
        for wireframe in self.wireframe_meshes:
            if wireframe is not None and hasattr(wireframe, 'rotate'):
                wireframe.rotate(rotation_matrix, center=[0, 0, 0])
        
        # Only regenerate preview occasionally to show rotation (every 10 steps = ~1 second)
        if int(self.rotation_angle) % 20 == 0:
            self.generate_preview()
            print(f"Auto-rotation: {self.rotation_angle:.1f}°")
    
    # Settings methods (matching current interface)
    def set_render_mode(self, mode: str):
        """Set render mode and refresh preview."""
        if mode.lower() in ['fill', 'wireframe', 'points', 'overlay']:
            self.render_mode = mode.lower()
            print(f"Set render mode to: {self.render_mode}")
            
            # Clear wireframes to ensure fresh generation
            if self.render_mode in ['wireframe', 'overlay']:
                self.wireframe_meshes = []
            
            # Refresh preview to show changes
            self.generate_preview()
    
    def set_use_lighting(self, enabled: bool):
        """Toggle lighting."""
        self.use_lighting = bool(enabled)
    
    def set_use_vertex_colors(self, enabled: bool):
        """Toggle vertex colors with proper state management."""
        self.use_vertex_colors = bool(enabled)
        
        # Apply to existing meshes
        for i, mesh in enumerate(self.meshes):
            if not hasattr(mesh, 'vertex_colors'):
                continue
                
            if enabled:
                # Restore original vertex colors if they exist
                if (i < len(self.has_vertex_colors) and self.has_vertex_colors[i] and 
                    i < len(self.original_vertex_colors) and self.original_vertex_colors[i] is not None):
                    mesh.vertex_colors = o3d.utility.Vector3dVector(self.original_vertex_colors[i])
                    print(f"Restored original vertex colors for mesh {i}")
                else:
                    # No original vertex colors, clear current colors to show material
                    mesh.vertex_colors = o3d.utility.Vector3dVector(np.empty((0, 3)))
                    print(f"No vertex colors to restore for mesh {i}, using material color")
            else:
                # Apply uniform mesh color (override vertex colors)
                if hasattr(mesh, 'paint_uniform_color'):
                    mesh.paint_uniform_color(self.mesh_color)
                    print(f"Applied uniform mesh color to mesh {i}")
        
        # Refresh preview to show changes
        self.generate_preview()
    
    def set_use_textures(self, enabled: bool):
        """Toggle textures with proper state management."""
        self.use_textures = bool(enabled)
        
        # Apply to existing meshes
        for i, mesh in enumerate(self.meshes):
            if enabled:
                # Restore original texture coordinates if they exist
                if (i < len(self.has_textures) and self.has_textures[i] and 
                    i < len(self.original_textures) and self.original_textures[i] is not None):
                    # Restore UV coordinates
                    if 'uvs' in self.original_textures[i]:
                        if hasattr(mesh, 'triangle_uvs'):
                            mesh.triangle_uvs = o3d.utility.Vector2dVector(self.original_textures[i]['uvs'])
                            print(f"Restored texture coordinates for mesh {i}")
                else:
                    print(f"No texture coordinates to restore for mesh {i}")
            else:
                # Clear texture coordinates
                if hasattr(mesh, 'triangle_uvs'):
                    mesh.triangle_uvs = o3d.utility.Vector2dVector(np.empty((0, 2)))
                    print(f"Cleared texture coordinates for mesh {i}")
        
        # Refresh preview to show changes
        self.generate_preview()
    
    def set_show_coordinate_frame(self, enabled: bool):
        """Toggle coordinate frame display."""
        self.show_coordinate_frame = bool(enabled)
    
    def set_show_bounding_box(self, enabled: bool):
        """Toggle bounding box display."""
        self.show_bounding_box = bool(enabled)
    
    def set_show_normals(self, enabled: bool):
        """Toggle normal vectors display."""
        self.show_normals = bool(enabled)
    
    def set_point_size(self, size: float):
        """Set point size for point cloud rendering."""
        self.point_size = float(size)
    
    def set_line_width(self, width: float):
        """Set line width for wireframe rendering."""
        self.line_width = float(width)
    
    def set_background_color(self, r: float, g: float, b: float):
        """Set background color."""
        self.background_color = [r, g, b]
    
    def set_mesh_color(self, r: float, g: float, b: float):
        """Set default mesh color and apply it if vertex colors are disabled."""
        self.mesh_color = [r, g, b]
        
        # Apply to existing meshes if vertex colors are disabled
        if not self.use_vertex_colors:
            for i, mesh in enumerate(self.meshes):
                if hasattr(mesh, 'paint_uniform_color'):
                    mesh.paint_uniform_color(self.mesh_color)
                    print(f"Applied new mesh color to mesh {i}")
            
            # Refresh preview to show changes
            self.generate_preview()
    
    def set_wireframe_color(self, r: float, g: float, b: float):
        """Set wireframe color and regenerate wireframes."""
        self.wireframe_color = [r, g, b]
        # Clear existing wireframes to force regeneration with new color
        self.wireframe_meshes = []
        print(f"Set wireframe color to [{r:.2f}, {g:.2f}, {b:.2f}]")
        
        # Refresh preview if we're in wireframe or overlay mode
        if self.render_mode in ['wireframe', 'overlay']:
            self.generate_preview()
    
    def set_lighting_params(self, ambient: float = None, diffuse: float = None, specular: float = None, shininess: float = None):
        """Set lighting parameters."""
        if ambient is not None:
            self.ambient_light = float(ambient)
        if diffuse is not None:
            self.diffuse_light = float(diffuse)
        if specular is not None:
            self.specular_light = float(specular)
    
    def set_auto_rotate(self, enabled: bool):
        """Toggle auto-rotation."""
        self.auto_rotate = enabled
        if enabled:
            print("Auto-rotation enabled")
            self.rotation_timer.start(100)  # 10 FPS - more reasonable for preview updates
        else:
            print("Auto-rotation disabled")
            self.rotation_timer.stop()
            # Reset rotation angle when disabled
            self.rotation_angle = 0.0
    
    def reset_view(self):
        """Reset view parameters."""
        # This would reset camera in the actual viewer
        pass


class ModelViewerWidget_Open3D(QWidget):
    """Complete Open3D model viewer widget with enhanced controls."""
    
    cleared = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Use Open3D viewer
        self.viewer_3d = ModelViewer3D_Open3D()
        self._load_seq = 0
        
        self.init_ui()
        self.setup_connections()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # 3D viewer
        layout.addWidget(self.viewer_3d, 1)
        
        # Basic controls (keep existing for compatibility)
        controls_layout = QHBoxLayout()
        
        self.wireframe_cb = QCheckBox("Wireframe")
        self.auto_rotate_cb = QCheckBox("Auto Rotate")
        self.reset_view_btn = QPushButton("Reset View")
        self.clear_view_btn = QPushButton("Clear Viewer")
        
        controls_layout.addWidget(self.wireframe_cb)
        controls_layout.addWidget(self.auto_rotate_cb)
        controls_layout.addWidget(self.reset_view_btn)
        controls_layout.addWidget(self.clear_view_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Info panel
        self.info_label = QLabel("No model loaded")
        self.info_label.setStyleSheet("background: #f0f0f0; padding: 5px; margin: 2px;")
        layout.addWidget(self.info_label)
    
    def setup_connections(self):
        """Setup signal connections."""
        self.wireframe_cb.toggled.connect(lambda on: self.set_render_mode('wireframe' if on else 'fill'))
        self.auto_rotate_cb.toggled.connect(self.viewer_3d.set_auto_rotate)
        self.reset_view_btn.clicked.connect(self.viewer_3d.reset_view)
        self.clear_view_btn.clicked.connect(self.clear)
        self.viewer_3d.model_loaded.connect(self.update_model_info)
    
    def load_model(self, file_path: str) -> bool:
        """Load a model file."""
        self._load_seq += 1
        success = self.viewer_3d.load_model(file_path)
        if not success:
            self.info_label.setText("Failed to load model")
        return success
    
    def update_model_info(self, info: dict):
        """Update model information display."""
        text = f"Vertices: {info['vertices']:,} | Faces: {info['faces']:,} | "
        text += f"Surface Area: {info['surface_area']:.2f}"
        if info.get('volume', 0) > 0:
            text += f" | Volume: {info['volume']:.2f}"
        
        self.info_label.setText(text)
    
    def clear(self):
        """Clear viewer and info panel."""
        self._load_seq += 1
        self.viewer_3d.clear()
        self.info_label.setText("No model loaded")
        self.cleared.emit()
    
    # Expose all viewer methods for settings tab
    def set_render_mode(self, mode: str):
        self.viewer_3d.set_render_mode(mode)
    
    def set_use_lighting(self, enabled: bool):
        self.viewer_3d.set_use_lighting(enabled)
    
    def set_use_textures(self, enabled: bool):
        self.viewer_3d.set_use_textures(enabled)
    
    def set_use_vertex_colors(self, enabled: bool):
        self.viewer_3d.set_use_vertex_colors(enabled)
    
    def set_show_coordinate_frame(self, enabled: bool):
        self.viewer_3d.set_show_coordinate_frame(enabled)
    
    def set_show_bounding_box(self, enabled: bool):
        self.viewer_3d.set_show_bounding_box(enabled)
    
    def set_show_normals(self, enabled: bool):
        self.viewer_3d.set_show_normals(enabled)
    
    def set_point_size(self, size: float):
        self.viewer_3d.set_point_size(size)
    
    def set_line_width(self, width: float):
        self.viewer_3d.set_line_width(width)
    
    def set_background_color(self, r: float, g: float, b: float):
        self.viewer_3d.set_background_color(r, g, b)
    
    def set_mesh_color(self, r: float, g: float, b: float):
        self.viewer_3d.set_mesh_color(r, g, b)
    
    def set_wireframe_color(self, r: float, g: float, b: float):
        self.viewer_3d.set_wireframe_color(r, g, b)
    
    def set_lighting_params(self, ambient: float = None, diffuse: float = None, specular: float = None, shininess: float = None):
        self.viewer_3d.set_lighting_params(ambient, diffuse, specular, shininess)