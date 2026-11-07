"""
3D Model viewer widget with fallback for when OpenGL is not available.
"""

import os
import logging
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QCheckBox, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QWheelEvent, QMouseEvent, QPixmap, QPainter, QPen, QColor, QImage
import trimesh

from ..utils import frame_clock

# Try to import OpenGL - if it fails, we'll use a simple fallback viewer
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtOpenGL import (
        QOpenGLBuffer,
        QOpenGLVertexArrayObject,
        QOpenGLShaderProgram,
        QOpenGLShader,
        QOpenGLTexture
    )
    from PyQt6.QtGui import QMatrix4x4, QVector3D, QSurfaceFormat, QVector4D, QOpenGLContext
    from OpenGL.GL import *
    import ctypes
    OPENGL_AVAILABLE = True
except ImportError:
    OPENGL_AVAILABLE = False
    # Create a dummy QOpenGLWidget class for fallback
    from PyQt6.QtWidgets import QWidget as QOpenGLWidget

logger = logging.getLogger(__name__)

class SimpleModelViewer(QWidget):
    """Simple fallback model viewer when OpenGL is not available."""
    
    model_loaded = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mesh = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Info display
        self.info_display = QTextEdit()
        self.info_display.setMaximumHeight(200)
        self.info_display.setReadOnly(True)
        layout.addWidget(self.info_display)
        
        # Placeholder for 3D view
        self.placeholder_label = QLabel("3D Preview Unavailable")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                color: #ffffff;
                font-size: 14px;
                border: 2px dashed #555555;
                min-height: 300px;
            }
        """)
        layout.addWidget(self.placeholder_label)
    
    def _load_gl_texture(self, img):
        if not OPENGL_AVAILABLE or img is None:
            return None
        try:
            from PIL import Image
            if not isinstance(img, np.ndarray):
                img = Image.fromarray(np.array(img)) if not isinstance(img, Image.Image) else img
                img = img.convert('RGBA')
                img_data = np.array(img, dtype=np.uint8)
            else:
                if img.ndim == 2:  # grayscale
                    img = np.stack([img, img, img, np.full_like(img, 255)], axis=-1)
                if img.shape[-1] == 3:
                    alpha = np.full((img.shape[0], img.shape[1], 1), 255, dtype=img.dtype)
                    img = np.concatenate([img, alpha], axis=-1)
                img_data = img.astype(np.uint8)
            
            tex = np.array([0], dtype=np.uint32)
            glGenTextures(1, tex)
            texture_id = int(tex[0])
            glBindTexture(GL_TEXTURE_2D, texture_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img_data.shape[1], img_data.shape[0], 0, GL_RGBA, GL_UNSIGNED_BYTE, img_data.tobytes())
            glGenerateMipmap(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, 0)
            return texture_id
        except Exception:
            return None

    def load_model(self, file_path: str) -> bool:
        """Load a model and display its information."""
        try:
            mesh = trimesh.load(file_path)
            
            if isinstance(mesh, trimesh.Scene):
                try:
                    dumped = mesh.dump()
                    if isinstance(dumped, (list, tuple)):
                        mesh = trimesh.util.concatenate(dumped) if dumped else None
                    elif isinstance(dumped, dict):
                        mesh = trimesh.util.concatenate(list(dumped.values())) if dumped else None
                    elif isinstance(dumped, trimesh.Trimesh):
                        mesh = dumped
                    else:
                        mesh = None
                except Exception:
                    mesh = None
            if not isinstance(mesh, trimesh.Trimesh) or mesh is None:
                return False
            
            self.mesh = mesh
            
            # Additional metrics
            euler_number = mesh.euler_number
            center_mass = mesh.center_mass.tolist() if hasattr(mesh, 'center_mass') else [0.0, 0.0, 0.0]
            
            # Display model information
            info_text = f"""Model Information:
File: {os.path.basename(file_path)}
Vertices: {len(mesh.vertices):,}
Faces: {len(mesh.faces):,}
Surface Area: {mesh.area:.2f}
Volume: {(mesh.volume if mesh.is_volume else 0.0):.2f}
Is Watertight: {mesh.is_watertight}
Euler Number: {euler_number}
Center of Mass: [{center_mass[0]:.2f}, {center_mass[1]:.2f}, {center_mass[2]:.2f}]
Bounds: 
  Min: [{mesh.bounds[0][0]:.2f}, {mesh.bounds[0][1]:.2f}, {mesh.bounds[0][2]:.2f}]
  Max: [{mesh.bounds[1][0]:.2f}, {mesh.bounds[1][1]:.2f}, {mesh.bounds[1][2]:.2f}]

Note: Install PyOpenGL packages for 3D preview:
pip install PyOpenGL PyOpenGL-accelerate
"""
            
            self.info_display.setPlainText(info_text)
            self.placeholder_label.setText("3D Preview Unavailable\n(Install PyOpenGL for 3D rendering)")

            # Emit model info
            model_info = {
                'vertices': len(mesh.vertices),
                'faces': len(mesh.faces),
                'edges': len(mesh.edges) if hasattr(mesh, 'edges') else 0,
                'bounds': mesh.bounds.tolist(),
                'center': mesh.center_mass.tolist() if hasattr(mesh, 'center_mass') else [0.0, 0.0, 0.0],
                'is_watertight': bool(mesh.is_watertight),
                'volume': float(mesh.volume) if mesh.is_volume else 0.0,
                'surface_area': float(mesh.area)
            }
            self.model_loaded.emit(model_info)
            
            return True
            
        except Exception as e:
            self.info_display.setPlainText(f"Error loading model: {str(e)}")
            return False
    
    def set_wireframe_mode(self, enabled: bool):
        """Dummy method for compatibility."""
        pass
    
    def set_auto_rotate(self, enabled: bool):
        """Dummy method for compatibility."""
        pass
    
    def reset_view(self):
        """Dummy method for compatibility."""
        pass

    def clear(self):
        """Clear the loaded model and reset UI."""
        self.mesh = None
        self.info_display.setPlainText("No model loaded.")
        self.placeholder_label.setText("3D Preview Unavailable\n(Install PyOpenGL for 3D rendering)")

class ModelViewer3D(QOpenGLWidget):
    """3D model viewer using OpenGL (only available when PyOpenGL is installed)."""
    
    model_loaded = pyqtSignal(dict)
    # On the class, not in `__init__`: that method returns before its attribute block when
    # PyOpenGL is missing, and the first paint reads this name either way.
    _last_paint_failure = None

    def __init__(self, parent=None):
        super().__init__(parent)
        if not OPENGL_AVAILABLE:
            return
            
        # Request an OpenGL 3.3 Compatibility profile for broader driver support
        try:
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
            fmt.setDepthBufferSize(24)
            fmt.setStencilBufferSize(8)
            # Optional: enable debug context if supported (ignored if unavailable)
            try:
                fmt.setOption(QSurfaceFormat.FormatOption.DebugContext, on=True)
            except Exception:
                pass
            self.setFormat(fmt)
        except Exception:
            pass

        # Support multiple submeshes with their own materials
        self.meshes = []  # each entry: { 'vertices': np, 'normals': np, 'colors': np|None, 'uvs': np|None, 'weights': np|None, 'indices': np, 'vao':..., 'vbo':..., 'ebo':..., 'texture': int|None, 'has_texture': bool, 'has_colors': bool, 'has_weights': bool }
        
        # Camera parameters
        self.camera_distance = 5.0
        self.camera_rotation_x = 0.0
        self.camera_rotation_y = 0.0
        self.last_mouse_pos = None
        
        # Model transform
        self.model_scale = 1.0
        self.model_rotation_x = 0.0
        self.model_rotation_y = 0.0
        self.model_rotation_z = 0.0
        self.model_translation_x = 0.0
        self.model_translation_y = 0.0
        self.model_translation_z = 0.0
        
        # Rendering options
        self.render_mode = 'fill'  # 'fill' | 'wireframe' | 'overlay' | 'point_cloud'
        self.show_edges = False
        self.show_hidden_edges = False
        self.show_overlays = True
        self.zebra_direction = 0  # 0: Horizontal, 1: Vertical
        self.zebra_scale = 1.0
        self.curvature_scale = 1.0
        
        self.use_lighting = True
        self.use_textures = True
        self.use_vertex_colors = True
        self.line_width = 1.0
        self.point_size = 3.0  # Point size for point cloud rendering
        
        # Grid and axis display
        self.show_grid = False
        self.grid_size = 50
        self.grid_spacing = 0.5
        self.axis_length = 5.0
        self.grid_extent = 25.0
        self.grid_color = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        self.axis_colors = {
            'x': np.array([1.0, 0.0, 0.0], dtype=np.float32),  # Red for X
            'y': np.array([0.0, 1.0, 0.0], dtype=np.float32),  # Green for Y
            'z': np.array([0.0, 0.0, 1.0], dtype=np.float32)   # Blue for Z
        }
        
        # Lighting parameters (Multi-Light Support)
        self.use_lighting = True
        self.ambient_intensity = 0.2
        self.diffuse_intensity = 0.8
        self.specular_intensity = 0.5
        self.shininess = 32.0
        
        # Light Arrays (Max 5 lights)
        # Index 0 is always the "Sun" (Main Light)
        self.num_lights = 1
        self.light_positions = np.array([
            [5.0, 5.0, 5.0],   # Sun
            [-5.0, 5.0, -5.0], # Fill
            [0.0, 5.0, -5.0],  # Back
            [0.0, 0.0, 0.0],   # Extra 1
            [0.0, 0.0, 0.0]    # Extra 2
        ], dtype=np.float32)
        
        self.light_colors = np.array([
            [1.0, 1.0, 1.0], # Sun (White)
            [0.8, 0.8, 1.0], # Fill (Cool)
            [1.0, 0.9, 0.8], # Back (Warm)
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0]
        ], dtype=np.float32)
        
        self.light_intensities = np.array([1.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32) # Only Sun active by default
        self.base_color = np.array([0.7, 0.7, 0.9], dtype=np.float32)
        self.wire_color = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        self.point_color = np.array([1.0, 1.0, 0.0], dtype=np.float32)  # Yellow default for point cloud
        
        # Camera & Post-Processing
        self.camera_fov = 45.0
        self.exposure = 1.0
        self.gamma = 2.2
        self.contrast = 1.0
        self.saturation = 1.0
        self.vignette_enabled = False
        self.vignette_intensity = 0.5
        
        # Environment Settings
        self.env_rotation_y = 0.0
        self.env_blur = 0.0
        self.env_bg_intensity = 1.0
        
        # Weight Painting
        self.show_weights = False
        
        # OpenGL objects
        self.shader_program = None
        
        # Auto-rotation
        self.auto_rotate = False
        self.rotation_timer = QTimer()
        self.rotation_timer.timeout.connect(self.auto_rotation_step)
        
        self.gl_ready = False
        self.pending_model_path = None
        # Track if the current framebuffer has a depth buffer
        self.has_depth_buffer = None

    def _clear_meshes(self):
        """Free GL buffers and textures for meshes."""
        if not OPENGL_AVAILABLE:
            return
        # Only attempt to free when a valid context exists
        if not self.isValid():
            self.meshes = []
            return
            
        # Check if we are already in a context
        already_current = False
        if self.context() and self.context() == QOpenGLContext.currentContext():
            already_current = True
            
        try:
            if not already_current:
                self.makeCurrent()
            for m in self.meshes:
                try:
                    # Delete Qt VAO/VBO/EBO
                    if m.get('vao'):
                        try:
                            m['vao'].destroy()
                        except Exception:
                            pass
                    if m.get('vbo'):
                        try:
                            m['vbo'].destroy()
                        except Exception:
                            pass
                    if m.get('ebo'):
                        try:
                            m['ebo'].destroy()
                        except Exception:
                            pass
                    # Delete raw VAO if we created one
                    if m.get('raw_vao'):
                        try:
                            rid = np.array([int(m['raw_vao'])], dtype=np.uint32)
                            glDeleteVertexArrays(1, rid)
                        except Exception:
                            pass
                    # Delete texture if any
                    if m.get('texture'):
                        try:
                            tex_id = int(m['texture'])
                            glDeleteTextures(1, np.array([tex_id], dtype=np.uint32))
                        except Exception:
                            pass
                except Exception:
                    pass
        finally:
            try:
                if not already_current:
                    self.doneCurrent()
            except Exception:
                pass
        self.meshes = []

    def _load_gl_texture(self, img):
        if img is None: return None
        try:
            from PIL import Image
            if not isinstance(img, np.ndarray):
                img = Image.fromarray(np.array(img)) if not isinstance(img, Image.Image) else img
                img = img.convert('RGBA')
                img_data = np.array(img, dtype=np.uint8)
            else:
                if img.ndim == 2:  # grayscale
                    img = np.stack([img, img, img, np.full_like(img, 255)], axis=-1)
                if img.shape[-1] == 3:
                    alpha = np.full((img.shape[0], img.shape[1], 1), 255, dtype=img.dtype)
                    img = np.concatenate([img, alpha], axis=-1)
                img_data = img.astype(np.uint8)
            
            tex = np.array([0], dtype=np.uint32)
            glGenTextures(1, tex)
            texture_id = int(tex[0])
            glBindTexture(GL_TEXTURE_2D, texture_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img_data.shape[1], img_data.shape[0], 0, GL_RGBA, GL_UNSIGNED_BYTE, img_data.tobytes())
            glGenerateMipmap(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, 0)
            return texture_id
        except Exception:
            return None

    def load_model(self, file_path: str) -> bool:
        """Load a 3D model file with materials and vertex colors."""
        if not OPENGL_AVAILABLE:
            return False
            
        # Check validity and queue if necessary
        if not self.isValid():
            self.pending_model_path = file_path
            return True
            
        # If valid but not ready, also queue (or just wait for paintGL)
        if not self.gl_ready:
             self.pending_model_path = file_path
             return True
             
        # Check if we are already in a context (e.g. called from paintGL)
        already_current = False
        if self.context() and self.context() == QOpenGLContext.currentContext():
            already_current = True
            
        try:
            scene_or_mesh = trimesh.load(file_path)
            meshes = []
            if isinstance(scene_or_mesh, trimesh.Scene):
                # Preserve per-geometry instead of concatenating
                for name, geom in (scene_or_mesh.geometry or {}).items():
                    if isinstance(geom, trimesh.Trimesh) and len(geom.faces) > 0:
                        meshes.append(geom.copy())
            elif isinstance(scene_or_mesh, trimesh.Trimesh):
                if len(scene_or_mesh.faces) > 0:
                    meshes.append(scene_or_mesh.copy())
            else:
                return False
            
            if not meshes:
                return False
            
            # Store original meshes for export (these will be normalized below)
            self.original_meshes = meshes
            
            # Normalize all meshes into view collectively
            all_bounds = np.array([m.bounds for m in meshes])
            min_corner = np.min(all_bounds[:, 0, :], axis=0)
            max_corner = np.max(all_bounds[:, 1, :], axis=0)
            size = float(np.max(max_corner - min_corner))
            center = (min_corner + max_corner) / 2.0
            
            for m in meshes:
                if size > 0:
                    m.apply_scale(2.0 / size)
                    m.apply_translation(-center)
            
            self._clear_meshes()
            if self.isValid() and not already_current:
                self.makeCurrent()
            
            # Build GL buffers per mesh
            for m in meshes:
                vertices = m.vertices.astype(np.float32)
                normals = m.vertex_normals.astype(np.float32)
                # Enhanced vertex color detection
                colors = None
                has_colors = False

                # 1) Try to load vertex colors directly from OBJ file if available
                if file_path.lower().endswith('.obj'):
                    try:
                        colors = self._load_obj_vertex_colors(file_path, len(vertices))
                        if colors is not None:
                            has_colors = True
                    except Exception:
                        pass

                # 2) Best-effort: convert visuals (material/texture) to vertex colors
                if colors is None:
                    try:
                        if hasattr(m, 'visual') and m.visual is not None:
                            vis_color = m.visual.to_color() if hasattr(m.visual, 'to_color') else None
                            if vis_color is not None and hasattr(vis_color, 'vertex_colors'):
                                vc = vis_color.vertex_colors
                                if vc is not None and vc.ndim == 2 and vc.shape[0] == len(vertices):
                                    if vc.dtype != np.float32 and np.max(vc) > 1.0:
                                        vc = vc.astype(np.float32) / 255.0
                                    colors = vc[:, :4].astype(np.float32)
                                    has_colors = True
                    except Exception:
                        colors = None
                        has_colors = False

                # 3) Direct vertex_colors from loader
                if colors is None:
                    try:
                        if hasattr(m, 'visual') and hasattr(m.visual, 'vertex_colors') and m.visual.vertex_colors is not None:
                            vc = m.visual.vertex_colors
                            # Ensure Nx4 RGBA in 0..1
                            if vc.ndim == 2 and vc.shape[0] == len(vertices):
                                if vc.dtype != np.float32 and np.max(vc) > 1.0:
                                    vc = vc.astype(np.float32) / 255.0
                                colors = vc[:, :4].astype(np.float32)
                                has_colors = True
                    except Exception:
                        colors = None
                        has_colors = False

                # 4) Face colors -> expand to per-vertex (common for OBJ material colors)
                if colors is None:
                    try:
                        if hasattr(m, 'visual') and hasattr(m.visual, 'face_colors') and m.visual.face_colors is not None:
                            fc = m.visual.face_colors
                            if fc is not None and fc.ndim == 2 and fc.shape[0] == len(m.faces):
                                if fc.dtype != np.float32 and np.max(fc) > 1.0:
                                    fc = fc.astype(np.float32) / 255.0
                                # Initialize with base color
                                colors = np.tile(np.array([*self.base_color, 1.0], dtype=np.float32), (len(vertices), 1))
                                # Map face color to its three vertices
                                idx = m.faces.reshape(-1)
                                col_rep = np.repeat(fc[:, :4], 3, axis=0)
                                colors[idx] = col_rep
                                has_colors = True
                    except Exception:
                        colors = None
                        has_colors = False

                # 5) Fallback to material diffuse/base color if still no colors
                if colors is None:
                    try:
                        if hasattr(m, 'visual') and hasattr(m.visual, 'material') and m.visual.material is not None:
                            mat = m.visual.material
                            mat_color = None
                            # Try common fields across SimpleMaterial/PBR
                            for key in ('diffuse', 'baseColorFactor', 'color', 'Kd', 'kd', 'diffuse_color', 'albedo'):
                                val = getattr(mat, key, None)
                                if val is None and hasattr(mat, 'properties') and isinstance(mat.properties, dict):
                                    val = mat.properties.get(key)
                                if val is not None:
                                    mat_color = np.array(val, dtype=np.float32).flatten()
                                    break
                            if mat_color is not None:
                                # Normalize to RGB in 0..1
                                if mat_color.size >= 3:
                                    rgb = mat_color[:3]
                                    if np.max(rgb) > 1.0:
                                        rgb = rgb / 255.0
                                    colors = np.tile(np.append(rgb, 1.0), (len(vertices), 1)).astype(np.float32)
                                    has_colors = True
                    except Exception:
                        pass

                # UVs and textures
                uvs = None
                texture_id = None
                has_texture = False
                try:
                    if self.use_textures and hasattr(m, 'visual') and hasattr(m.visual, 'uv') and m.visual.uv is not None:
                        uv = m.visual.uv
                        if uv is not None and len(uv) == len(vertices):
                            uvs = uv.astype(np.float32)
                        # Try to fetch image from material
                        img = None
                        if hasattr(m, 'visual') and hasattr(m.visual, 'material') and hasattr(m.visual.material, 'image'):
                            img = m.visual.material.image
                        if img is None and hasattr(m, 'visual') and hasattr(m.visual, 'material') and hasattr(m.visual.material, 'image_base64'):
                            # Some trimesh materials store base64; trimesh usually decodes, but keep a fallback
                            pass
                        if img is not None:
                            # Convert PIL or array to RGBA
                            try:
                                from PIL import Image
                                if not isinstance(img, np.ndarray):
                                    img = Image.fromarray(np.array(img)) if not isinstance(img, Image.Image) else img
                                    img = img.convert('RGBA')
                                    img_data = np.array(img, dtype=np.uint8)
                                else:
                                    if img.ndim == 2:  # grayscale
                                        img = np.stack([img, img, img, np.full_like(img, 255)], axis=-1)
                                    if img.shape[-1] == 3:
                                        alpha = np.full((img.shape[0], img.shape[1], 1), 255, dtype=img.dtype)
                                        img = np.concatenate([img, alpha], axis=-1)
                                    img_data = img.astype(np.uint8)
                                # Upload texture
                                tex = np.array([0], dtype=np.uint32)
                                glGenTextures(1, tex)
                                texture_id = int(tex[0])
                                glBindTexture(GL_TEXTURE_2D, texture_id)
                                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
                                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
                                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
                                glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
                                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img_data.shape[1], img_data.shape[0], 0, GL_RGBA, GL_UNSIGNED_BYTE, img_data.tobytes())
                                glGenerateMipmap(GL_TEXTURE_2D)
                                glBindTexture(GL_TEXTURE_2D, 0)
                                has_texture = True
                            except Exception as _:
                                texture_id = None
                                has_texture = False
                except Exception:
                    uvs = None
                    has_texture = False
                    texture_id = None
                
                # Load additional PBR textures
                normal_tex = None
                metallic_tex = None
                occlusion_tex = None
                emissive_tex = None
                
                try:
                    if hasattr(m, 'visual') and hasattr(m.visual, 'material'):
                        mat = m.visual.material
                        # Normal
                        if hasattr(mat, 'normalTexture') and mat.normalTexture:
                            normal_tex = self._load_gl_texture(mat.normalTexture)
                        # Metallic/Roughness
                        if hasattr(mat, 'metallicRoughnessTexture') and mat.metallicRoughnessTexture:
                            metallic_tex = self._load_gl_texture(mat.metallicRoughnessTexture)
                        # Occlusion
                        if hasattr(mat, 'occlusionTexture') and mat.occlusionTexture:
                            occlusion_tex = self._load_gl_texture(mat.occlusionTexture)
                        # Emissive
                        if hasattr(mat, 'emissiveTexture') and mat.emissiveTexture:
                            emissive_tex = self._load_gl_texture(mat.emissiveTexture)
                except Exception:
                    pass
                
                faces = m.faces.astype(np.uint32)
                # Build interleaved buffer: pos(3) normal(3) color(4) uv(2)
                if colors is None:
                    colors = np.tile(np.append(self.base_color, 1.0), (len(vertices), 1)).astype(np.float32)
                if uvs is None:
                    uvs = np.zeros((len(vertices), 2), dtype=np.float32)
                
                # Initialize weights (default 0.0)
                weights = np.zeros((len(vertices), 1), dtype=np.float32)
                
                # Build interleaved buffer: pos(3) normal(3) color(4) uv(2) weight(1)
                interleaved = np.column_stack((vertices, normals, colors, uvs, weights)).astype(np.float32)
                
                # Create VAO/VBO/EBO
                vao = QOpenGLVertexArrayObject()
                vao_ok = vao.create()
                raw_vao_id = None
                if vao_ok:
                    vao.bind()
                else:
                    # If Qt VAO not available, try raw VAO
                    try:
                        tmp = np.array([0], dtype=np.uint32)
                        glGenVertexArrays(1, tmp)
                        raw_vao_id = int(tmp[0])
                        glBindVertexArray(raw_vao_id)
                    except Exception:
                        raw_vao_id = None
                
                # Ensure a VAO is bound (some drivers ignore Qt bind without error)
                try:
                    bound = glGetIntegerv(GL_VERTEX_ARRAY_BINDING)
                    if (isinstance(bound, (list, tuple, np.ndarray)) and int(bound[0]) == 0) or (isinstance(bound, int) and bound == 0):
                        if raw_vao_id is None:
                            tmp = np.array([0], dtype=np.uint32)
                            glGenVertexArrays(1, tmp)
                            raw_vao_id = int(tmp[0])
                        glBindVertexArray(raw_vao_id)
                except Exception:
                    pass
                
                vbo = QOpenGLBuffer()
                vbo.create()
                vbo.bind()  # Bind ARRAY_BUFFER
                vbo.allocate(interleaved.tobytes(), interleaved.nbytes)
                
                ebo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
                ebo.create()
                ebo.bind()  # Bind ELEMENT_ARRAY_BUFFER
                face_data = faces.flatten().astype(np.uint32)
                ebo.allocate(face_data.tobytes(), face_data.nbytes)
                
                # IMPORTANT: Some drivers require rebinding the VBO before setting attrib pointers
                vbo.bind()
                
                stride = (3 + 3 + 4 + 2 + 1) * 4
                glEnableVertexAttribArray(0)
                glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
                glEnableVertexAttribArray(1)
                glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(3 * 4))
                glEnableVertexAttribArray(2)
                glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(6 * 4))
                glEnableVertexAttribArray(3)
                glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(10 * 4))
                glEnableVertexAttribArray(4)
                glVertexAttribPointer(4, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12 * 4))
                
                # Unbind VAO
                try:
                    if raw_vao_id is not None:
                        glBindVertexArray(0)
                    elif vao_ok:
                        vao.release()
                except Exception:
                    pass
                
                self.meshes.append({
                    'vertices': vertices,
                    'normals': normals,
                    'colors': colors,
                    'uvs': uvs,
                    'indices': faces,
                    'vao': vao if vao_ok else None,
                    'raw_vao': raw_vao_id,
                    'vbo': vbo,
                    'ebo': ebo,
                    'normal_tex': normal_tex,
                    'metallic_tex': metallic_tex,
                    'occlusion_tex': occlusion_tex,
                    'emissive_tex': emissive_tex,
                    'texture': texture_id,
                    'has_texture': has_texture,
                    'has_colors': has_colors,
                    'weights': weights
                })
            
            # Compile shaders if needed
            if self.shader_program is None and self.isValid():
                self.create_shaders()
            
            # If shader program didn't link, refuse and let caller fallback
            if self.shader_program is None:
                return False
            
            # Emit model info using combined counts
            total_vertices = int(np.sum([len(m['vertices']) for m in self.meshes]))
            total_faces = int(np.sum([len(m['indices']) for m in self.meshes]))
            # Use first mesh's trimesh for properties
            m0 = meshes[0]
            model_info = {
                'vertices': total_vertices,
                'faces': total_faces,
                'edges': len(m0.edges) if hasattr(m0, 'edges') else 0,
                'bounds': np.array([min_corner, max_corner]).tolist(),
                'center': getattr(m0, 'center_mass', np.zeros(3)).tolist() if hasattr(m0, 'center_mass') else [0.0, 0.0, 0.0],
                'is_watertight': bool(m0.is_watertight),
                'volume': float(m0.volume) if m0.is_volume else 0.0,
                'surface_area': float(sum([mm.area for mm in meshes]))
            }
            self.model_loaded.emit(model_info)
            
            if self.isValid() and not already_current:
                self.doneCurrent()
            
            self.update()
            return True
            
        except Exception as e:
            logger.warning("Error loading model: %s", str(e))
            return False
    
    def _load_obj_vertex_colors(self, file_path: str, expected_vertices: int) -> np.ndarray:
        """Enhanced OBJ vertex color parsing for files from Shapr3D and other tools.
        
        Returns vertex colors as Nx4 RGBA array in range [0,1], or None if not found.
        """
        try:
            vertex_colors = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.split()
                    if not parts:
                        continue
                    
                    # Standard vertex lines: "v x y z [r g b]"
                    if parts[0] == 'v' and len(parts) >= 6:
                        try:
                            # Extract RGB values (positions 4, 5, 6 after x, y, z)
                            r, g, b = float(parts[3]), float(parts[4]), float(parts[5])
                            
                            # Normalize if values are in 0-255 range
                            if r > 1.0 or g > 1.0 or b > 1.0:
                                r, g, b = r / 255.0, g / 255.0, b / 255.0
                            
                            # Clamp to [0,1] range
                            r = max(0.0, min(1.0, r))
                            g = max(0.0, min(1.0, g))
                            b = max(0.0, min(1.0, b))
                            
                            vertex_colors.append([r, g, b, 1.0])
                        except (ValueError, IndexError):
                            # If parsing fails, use default color
                            vertex_colors.append([0.7, 0.7, 0.9, 1.0])
                    
                    # Alternative format: "v x y z" followed by "vc r g b" 
                    elif parts[0] == 'vc' and len(parts) >= 4:
                        try:
                            r, g, b = float(parts[1]), float(parts[2]), float(parts[3])
                            
                            # Normalize if values are in 0-255 range
                            if r > 1.0 or g > 1.0 or b > 1.0:
                                r, g, b = r / 255.0, g / 255.0, b / 255.0
                            
                            # Replace the last color if we have one, otherwise add
                            if vertex_colors:
                                vertex_colors[-1] = [r, g, b, 1.0]
                            else:
                                vertex_colors.append([r, g, b, 1.0])
                        except (ValueError, IndexError):
                            continue
                    
                    # Standard vertex without color
                    elif parts[0] == 'v' and len(parts) >= 4:
                        # Add default color for vertex without color info
                        vertex_colors.append([0.7, 0.7, 0.9, 1.0])
            
            # Validate we got the expected number of colors
            if len(vertex_colors) == expected_vertices and len(vertex_colors) > 0:
                # Check if we actually have varying colors (not all default)
                colors_array = np.array(vertex_colors, dtype=np.float32)
                
                # If all colors are very similar (all default), return None
                if np.allclose(colors_array[:, :3], [0.7, 0.7, 0.9], atol=0.01):
                    return None
                
                return colors_array
            
            return None
            
        except Exception as e:
            logger.warning("Error reading OBJ vertex colors: %s", e)
            return None
            
    def export_scene(self, output_path: str, material_data: dict = None) -> bool:
        """Export the current scene with applied materials."""
        if not hasattr(self, 'original_meshes') or not self.original_meshes:
            logger.warning("Scene export to %s refused: nothing is loaded", output_path)
            return False
            
        try:
            # Create a combined scene
            scene = trimesh.Scene()
            
            for i, m in enumerate(self.original_meshes):
                mesh_copy = m.copy()
                
                # Apply material if provided
                if material_data:
                    if 'base_color' in material_data:
                        c = material_data['base_color']
                        # Trimesh visual color
                        mesh_copy.visual.face_colors = [int(c[0]*255), int(c[1]*255), int(c[2]*255), 255]
                
                # Export weights as vertex colors if available
                if hasattr(m, 'weights') and m.weights is not None:
                    # Map weights to colors (heatmap)
                    # Simple mapping: Blue (0) -> Red (1)
                    import matplotlib.cm
                    cmap = matplotlib.cm.get_cmap('jet')
                    colors = cmap(m.weights)[:, :3] * 255
                    # Add alpha
                    colors = np.column_stack((colors, np.full(len(colors), 255)))
                    mesh_copy.visual.vertex_colors = colors.astype(np.uint8)
                
                # OVERRIDE with Painted Vertex Colors if available in OpenGL mesh
                # We assume self.meshes corresponds to self.original_meshes by index
                gl_mesh = None
                if i < len(self.meshes):
                    gl_mesh = self.meshes[i]
                
                if gl_mesh and 'colors' in gl_mesh:
                    # gl_mesh['colors'] is (N, 4) float 0-1
                    # Convert to (N, 4) uint8 0-255
                    painted_colors = (gl_mesh['colors'] * 255).astype(np.uint8)
                    mesh_copy.visual.vertex_colors = painted_colors

                scene.add_geometry(mesh_copy)
            
            scene.export(output_path)
            return True
            
        except Exception as e:
            logger.warning("Scene export to %s failed: %s", output_path, e)
            return False

    def initializeGL(self):
        """Initialize OpenGL context."""
        if not OPENGL_AVAILABLE:
            return
            
        try:
            # Print GL diagnostics
            try:
                vendor = glGetString(GL_VENDOR)
                renderer = glGetString(GL_RENDERER)
                version = glGetString(GL_VERSION)
                vendor_s = vendor.decode('utf-8') if isinstance(vendor, (bytes, bytearray)) else str(vendor)
                renderer_s = renderer.decode('utf-8') if isinstance(renderer, (bytes, bytearray)) else str(renderer)
                version_s = version.decode('utf-8') if isinstance(version, (bytes, bytearray)) else str(version)
                profile_mask = 0
                try:
                    pm = glGetIntegerv(GL_CONTEXT_PROFILE_MASK)
                    profile_mask = int(pm[0] if isinstance(pm, (list, tuple, np.ndarray)) else pm)
                except Exception:
                    pass
                logger.info("OpenGL Info -> Version: %s, Renderer: %s, Vendor: %s, ProfileMask: 0x%08X",
                            version_s, renderer_s, vendor_s, profile_mask)
            except Exception:
                pass

            # Detect depth buffer availability and enable depth test accordingly
            try:
                depth_bits = glGetIntegerv(GL_DEPTH_BITS)
                self.has_depth_buffer = int(depth_bits) > 0
            except Exception:
                self.has_depth_buffer = False
            if self.has_depth_buffer:
                glEnable(GL_DEPTH_TEST)
            else:
                try:
                    glDisable(GL_DEPTH_TEST)
                except Exception:
                    pass
            glEnable(GL_CULL_FACE)
            # Enable program point size for robust point rendering in core profile
            try:
                glEnable(GL_PROGRAM_POINT_SIZE)
            except Exception:
                pass
            glClearColor(0.2, 0.2, 0.2, 1.0)
            
            self.create_shaders()

            # Setup grid if needed
            if  self.show_grid:
                self.setup_grid_buffers()

            self.gl_ready = self.shader_program is not None
            
        except Exception as e:
            logger.warning("initializeGL failed: %s", e)
            self.gl_ready = False
        self.pending_model_path = None

    def create_shaders(self):
        """Create OpenGL shader program supporting colors and textures."""
        if not OPENGL_AVAILABLE:
            return
            
        vertex_shader = """
        #version 330 core
        layout (location = 0) in vec3 position;
        layout (location = 1) in vec3 normal;
        layout (location = 2) in vec4 color;
        layout (location = 3) in vec2 uv;
        layout (location = 4) in float vertex_weight;
        
        uniform mat4 mvp;
        uniform mat4 model;
        uniform float env_rotation_y;
        
        out vec3 v_normal;
        out vec3 v_pos;
        out vec4 v_color;
        out vec2 v_uv;
        out float v_weight;
        
        void main() {
            gl_Position = mvp * vec4(position, 1.0);
            v_normal = mat3(model) * normal;
            v_pos = vec3(model * vec4(position, 1.0));
            v_color = color;
            v_uv = uv;
            v_weight = vertex_weight;
        }
        """

        fragment_shader = """
        #version 330 core
        in vec3 v_normal;
        in vec3 v_pos;
        in vec4 v_color;
        in vec2 v_uv;
        in float v_weight;
        
        out vec4 frag_color;
        
        // Lighting
        #define MAX_LIGHTS 5
        uniform int num_lights;
        uniform vec3 light_pos[MAX_LIGHTS];
        uniform vec3 light_color[MAX_LIGHTS];
        uniform float light_intensity[MAX_LIGHTS];
        
        uniform vec3 view_pos;
        uniform bool use_lighting;
        uniform bool use_textures;
        uniform bool use_vertex_colors;
        uniform bool has_texture;
        uniform vec3 base_color;
        uniform vec3 wire_color;
        uniform vec3 point_color;
        uniform float ambient_intensity;
        uniform float diffuse_intensity;
        uniform float specular_intensity;
        uniform float shininess;
        uniform bool wireframe_pass;
        uniform bool point_mode;
        uniform bool skybox_mode;
        uniform int viz_mode; // 0=Default, 1=UV, 2=VColor, 3=MatID
        uniform int material_id;
        
        // Weight Painting
        uniform bool show_weights;
        
        // Post-Processing
        uniform float exposure;
        uniform float gamma;
        uniform float contrast;
        uniform float saturation;
        uniform bool vignette_enabled;
        uniform float vignette_intensity;
        
        // Environment
        uniform float env_blur;
        uniform float env_bg_intensity;
        
        uniform sampler2D tex0;
        uniform sampler2D tex_normal;
        uniform sampler2D tex_metallic;
        uniform sampler2D tex_occlusion;
        uniform sampler2D tex_emissive;
        
        uniform bool has_normal_map;
        uniform bool has_metallic_map;
        uniform bool has_occlusion_map;
        uniform bool has_emissive_map;
        
        // Surface Analysis
        uniform int zebra_direction;
        uniform float zebra_scale;
        uniform float curvature_scale;
        
        vec3 get_random_color(int id) {
            float r = fract(sin(float(id) * 12.9898) * 43758.5453);
            float g = fract(sin(float(id) * 78.233) * 43758.5453);
            float b = fract(sin(float(id) * 37.719) * 43758.5453);
            return vec3(r, g, b);
        }

        vec3 get_heat_map_color(float value) {
            // Blue (0.0) -> Cyan (0.25) -> Green (0.5) -> Yellow (0.75) -> Red (1.0)
            vec3 color = vec3(0.0);
            if (value < 0.25) {
                color = mix(vec3(0.0, 0.0, 1.0), vec3(0.0, 1.0, 1.0), value * 4.0);
            } else if (value < 0.5) {
                color = mix(vec3(0.0, 1.0, 1.0), vec3(0.0, 1.0, 0.0), (value - 0.25) * 4.0);
            } else if (value < 0.75) {
                color = mix(vec3(0.0, 1.0, 0.0), vec3(1.0, 1.0, 0.0), (value - 0.5) * 4.0);
            } else {
                color = mix(vec3(1.0, 1.0, 0.0), vec3(1.0, 0.0, 0.0), (value - 0.75) * 4.0);
            }
            return color;
        }
        
        void main() {
            if (skybox_mode) {
                // Simple blur simulation using bias (requires mipmaps)
                vec4 tex_color = texture(tex0, v_uv, env_blur);
                frag_color = tex_color * env_bg_intensity;
                return;
            }

            vec3 color = base_color;
            if (use_textures && has_texture) {
                color = texture(tex0, v_uv).rgb;
            } else if (use_vertex_colors) {
                color = v_color.rgb;
            }
            
            // Weight Painting Overlay
            if (show_weights) {
                vec3 weight_color = get_heat_map_color(v_weight);
                // Blend weight color with base color (70% weight, 30% base)
                color = mix(color, weight_color, 0.7);
            }
            
            vec3 final_rgb = color;
            
            // Visualization Modes
            if (viz_mode == 1) { // UV Map
                final_rgb = vec3(v_uv.x, v_uv.y, 0.0);
            } else if (viz_mode == 2) { // Vertex Colors
                final_rgb = v_color.rgb;
            } else if (viz_mode == 3) { // Material IDs
                final_rgb = get_random_color(material_id);
            } else if (viz_mode == 4) { // Albedo
                final_rgb = texture(tex0, v_uv).rgb;
            } else if (viz_mode == 5) { // Normal
                final_rgb = has_normal_map ? texture(tex_normal, v_uv).rgb : vec3(0.5, 0.5, 1.0);
            } else if (viz_mode == 6) { // Specular/Metallic
                final_rgb = has_metallic_map ? texture(tex_metallic, v_uv).rgb : vec3(0.0);
            } else if (viz_mode == 7) { // Occlusion
                final_rgb = has_occlusion_map ? texture(tex_occlusion, v_uv).rgb : vec3(1.0);
            } else if (viz_mode == 8) { // Emissive
                final_rgb = has_emissive_map ? texture(tex_emissive, v_uv).rgb : vec3(0.0);
            } else if (viz_mode == 9) { // Zebra Map
                vec3 view_dir = normalize(view_pos - v_pos);
                vec3 norm = normalize(v_normal);
                vec3 ref_dir = reflect(-view_dir, norm);
                float coord = (zebra_direction == 0) ? ref_dir.y : ref_dir.x; 
                float pattern = fract(coord * zebra_scale * 10.0);
                float intensity = smoothstep(0.4, 0.6, pattern);
                final_rgb = vec3(intensity);
            } else if (viz_mode == 10) { // Curvature Map
                vec3 norm = normalize(v_normal);
                vec3 dx = dFdx(norm);
                vec3 dy = dFdy(norm);
                float curvature = length(dx) + length(dy);
                curvature = clamp(curvature * curvature_scale * 10.0, 0.0, 1.0);
                final_rgb = get_heat_map_color(curvature);
            }
            if (use_lighting && !wireframe_pass && !point_mode && viz_mode == 0) {
                vec3 ambient = ambient_intensity * color;
                vec3 norm = normalize(v_normal);
                vec3 view_dir = normalize(view_pos - v_pos);
                
                vec3 total_diffuse = vec3(0.0);
                vec3 total_specular = vec3(0.0);
                
                for(int i = 0; i < num_lights; i++) {
                    vec3 light_dir = normalize(light_pos[i] - v_pos);
                    float diff = max(dot(norm, light_dir), 0.0);
                    vec3 diffuse = light_intensity[i] * diff * light_color[i];
                    
                    vec3 reflect_dir = reflect(-light_dir, norm);
                    float spec = pow(max(dot(view_dir, reflect_dir), 0.0), shininess);
                    vec3 specular = light_intensity[i] * spec * light_color[i];
                    
                    total_diffuse += diffuse;
                    total_specular += specular;
                }
                
                final_rgb = ambient + (total_diffuse * diffuse_intensity * color) + (total_specular * specular_intensity);
            }
            
            // --- Post-Processing ---
            if (!wireframe_pass && !point_mode) {
                // 1. Exposure
                final_rgb *= exposure;
                
                // 2. Contrast
                final_rgb = (final_rgb - 0.5) * contrast + 0.5;
                
                // 3. Saturation
                float luminance = dot(final_rgb, vec3(0.2126, 0.7152, 0.0722));
                final_rgb = mix(vec3(luminance), final_rgb, saturation);
                
                // 4. Vignette
                if (vignette_enabled) {
                    vec2 uv = v_uv * 2.0 - 1.0;
                    float d = length(uv);
                    float v = smoothstep(1.0, 1.0 - vignette_intensity, d);
                    final_rgb *= v;
                }
                
                // 5. Gamma Correction
                final_rgb = pow(final_rgb, vec3(1.0 / gamma));
            }

            if (wireframe_pass) {
                frag_color = vec4(wire_color, 1.0);
            } else if (point_mode) {
                frag_color = vec4(point_color, 1.0);  // Use point color in point cloud mode
            } else {
                frag_color = vec4(final_rgb, 1.0);
            }
        }
        """
        
        try:
            self.shader_program = QOpenGLShaderProgram()
            if not self.shader_program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex_shader):
                logger.warning("Vertex shader compile failed: %s", self.shader_program.log())
                self.shader_program = None
                return
            if not self.shader_program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment_shader):
                logger.warning("Fragment shader compile failed: %s", self.shader_program.log())
                self.shader_program = None
                return
            if not self.shader_program.link():
                logger.warning("Shader link failed: %s", self.shader_program.log())
                self.shader_program = None
                return
        except Exception as e:
            logger.warning("Shader compilation exception: %s", e)
            self.shader_program = None
    
    def paintGL(self):
        """Render the scene with optional overlay wireframe."""
        # Process pending model load
        if hasattr(self, 'pending_model_path') and self.pending_model_path:
            path = self.pending_model_path
            self.pending_model_path = None
            self.load_model(path)
            # load_model calls update(), so we might return or continue. 
            
        if not OPENGL_AVAILABLE:
            frame_clock.note_blocked(
                'PyOpenGL could not be imported, so this viewer draws no frames')
            return
            
        try:
            # Ensure depth buffer knowledge (in case of context re-creation)
            if self.has_depth_buffer is None:
                try:
                    self.has_depth_buffer = int(glGetIntegerv(GL_DEPTH_BITS)) > 0
                except Exception:
                    self.has_depth_buffer = False
            mask = GL_COLOR_BUFFER_BIT | (GL_DEPTH_BUFFER_BIT if self.has_depth_buffer else 0)
            try:
                glClear(mask)
            except Exception:
                # Fallback: clear color only if clearing depth is invalid
                try:
                    glClear(GL_COLOR_BUFFER_BIT)
                except Exception:
                    pass
            
            # Require a valid shader, but allow rendering even if no meshes are loaded (for grid/axes)
            if self.shader_program is None:
                return
            
            # Bind program and set up matrices/uniforms first
            self.shader_program.bind()

            # Set up matrices
            model_matrix = QMatrix4x4()
            model_matrix.translate(self.model_translation_x, self.model_translation_y, self.model_translation_z)
            model_matrix.rotate(self.model_rotation_x, 1, 0, 0)
            model_matrix.rotate(self.model_rotation_y, 0, 1, 0)
            model_matrix.rotate(self.model_rotation_z, 0, 0, 1)
            model_matrix.scale(self.model_scale)
            
            view_matrix = QMatrix4x4()
            view_matrix.translate(0, 0, -self.camera_distance)
            view_matrix.rotate(self.camera_rotation_x, 1, 0, 0)
            view_matrix.rotate(self.camera_rotation_y, 0, 1, 0)
            
            proj_matrix = QMatrix4x4()
            proj_matrix.perspective(self.camera_fov, self.width() / self.height() if self.height() > 0 else 1.0, 0.1, 1000.0)
            
            # Render Skybox first (if loaded)
            self.render_skybox(view_matrix, proj_matrix)
            
            # Calculate MVP matrix
            mvp_matrix = proj_matrix * view_matrix * model_matrix
            
            # Re-bind shader (render_skybox might have unbound it or changed state)
            self.shader_program.bind()
            
            # Common uniforms
            self.shader_program.setUniformValue("mvp", mvp_matrix)
            self.shader_program.setUniformValue("model", model_matrix)
            self.shader_program.setUniformValue("view_pos", QVector3D(0.0, 0.0, self.camera_distance))
            self.shader_program.setUniformValue("use_lighting", bool(self.use_lighting))
            self.shader_program.setUniformValue("use_textures", bool(self.use_textures))
            self.shader_program.setUniformValue("use_vertex_colors", bool(self.use_vertex_colors))
            self.shader_program.setUniformValue("use_vertex_colors", bool(self.use_vertex_colors))
            self.shader_program.setUniformValue("show_weights", bool(getattr(self, 'show_weights', False)))
            self.shader_program.setUniformValue("base_color", QVector3D(*self.base_color))
            self.shader_program.setUniformValue("wire_color", QVector3D(*self.wire_color))
            self.shader_program.setUniformValue("point_color", QVector3D(*self.point_color))
            self.shader_program.setUniformValue("ambient_intensity", float(self.ambient_intensity))
            self.shader_program.setUniformValue("diffuse_intensity", float(self.diffuse_intensity))
            self.shader_program.setUniformValue("specular_intensity", float(self.specular_intensity))
            self.shader_program.setUniformValue("shininess", float(self.shininess))
            self.shader_program.setUniformValue("point_mode", False)
            self.shader_program.setUniformValue("skybox_mode", False)
            
            # Set Visualization Mode
            viz_mode = 0
            if self.render_mode == 'uv_map': viz_mode = 1
            elif self.render_mode == 'vertex_colors': 
                # Use Lit mode (0) but force vertex colors
                viz_mode = 0 
                self.shader_program.setUniformValue("use_vertex_colors", True)
            elif self.render_mode == 'material_ids': viz_mode = 3
            elif self.render_mode == 'zebra': viz_mode = 9
            elif self.render_mode == 'curvature': viz_mode = 10
            self.shader_program.setUniformValue("viz_mode", viz_mode)
            
            # Set Viz Mode for textures (map string to int)
            if self.render_mode == 'albedo': viz_mode = 4
            elif self.render_mode == 'normal': viz_mode = 5
            elif self.render_mode == 'specular/metallic': viz_mode = 6
            elif self.render_mode == 'occlusion': viz_mode = 7
            elif self.render_mode == 'emissive': viz_mode = 8
            self.shader_program.setUniformValue("viz_mode", viz_mode)
            
            # Post-Processing Uniforms
            self.shader_program.setUniformValue("exposure", float(self.exposure))
            self.shader_program.setUniformValue("gamma", float(self.gamma))
            self.shader_program.setUniformValue("contrast", float(self.contrast))
            self.shader_program.setUniformValue("saturation", float(self.saturation))
            self.shader_program.setUniformValue("vignette_enabled", bool(self.vignette_enabled))
            self.shader_program.setUniformValue("vignette_intensity", float(self.vignette_intensity))
            
            # Environment Uniforms
            self.shader_program.setUniformValue("env_rotation_y", float(self.env_rotation_y))
            self.shader_program.setUniformValue("env_blur", float(self.env_blur))
            self.shader_program.setUniformValue("env_bg_intensity", float(self.env_bg_intensity))
            
            # Surface Analysis Uniforms
            self.shader_program.setUniformValue("zebra_direction", int(self.zebra_direction))
            self.shader_program.setUniformValue("zebra_scale", float(self.zebra_scale))
            self.shader_program.setUniformValue("curvature_scale", float(self.curvature_scale))
            
            # Pass Light Arrays
            self.shader_program.setUniformValue("num_lights", self.num_lights)
            # Pass arrays as flat lists or individual uniforms if PyOpenGL wrapper supports it
            # For simplicity with QOpenGLShaderProgram, we iterate
            for i in range(self.num_lights):
                self.shader_program.setUniformValue(f"light_pos[{i}]", QVector3D(*self.light_positions[i]))
                self.shader_program.setUniformValue(f"light_color[{i}]", QVector3D(*self.light_colors[i]))
                self.shader_program.setUniformValue(f"light_intensity[{i}]", float(self.light_intensities[i]))

            if self.meshes:
                # First pass: fill (if mode is fill or overlay)
                if self.render_mode in ('fill', 'overlay', 'uv_map', 'vertex_colors', 'material_ids', 'triangles', 'albedo', 'normal', 'specular/metallic', 'occlusion', 'emissive', 'zebra', 'curvature'):
                    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
                    self.shader_program.setUniformValue("wireframe_pass", False)
                    for m in self.meshes:
                        self.shader_program.setUniformValue("has_texture", bool(self.use_textures and m.get('has_texture', False)))
                        # Bind texture if any
                        if self.use_textures and m.get('texture') and m.get('has_texture'):
                            glActiveTexture(GL_TEXTURE0)
                            glBindTexture(GL_TEXTURE_2D, int(m['texture']))
                            self.shader_program.setUniformValue("tex0", 0)
                        else:
                            glActiveTexture(GL_TEXTURE0)
                            glBindTexture(GL_TEXTURE_2D, 0)
                        
                        # Bind PBR Textures
                        # Normal (Tex1)
                        if m.get('normal_tex'):
                            glActiveTexture(GL_TEXTURE1)
                            glBindTexture(GL_TEXTURE_2D, int(m['normal_tex']))
                            self.shader_program.setUniformValue("tex_normal", 1)
                            self.shader_program.setUniformValue("has_normal_map", True)
                        else:
                            glActiveTexture(GL_TEXTURE1)
                            glBindTexture(GL_TEXTURE_2D, 0)
                            self.shader_program.setUniformValue("has_normal_map", False)
                            
                        # Metallic (Tex2)
                        if m.get('metallic_tex'):
                            glActiveTexture(GL_TEXTURE2)
                            glBindTexture(GL_TEXTURE_2D, int(m['metallic_tex']))
                            self.shader_program.setUniformValue("tex_metallic", 2)
                            self.shader_program.setUniformValue("has_metallic_map", True)
                        else:
                            glActiveTexture(GL_TEXTURE2)
                            glBindTexture(GL_TEXTURE_2D, 0)
                            self.shader_program.setUniformValue("has_metallic_map", False)
                            
                        # Occlusion (Tex3)
                        if m.get('occlusion_tex'):
                            glActiveTexture(GL_TEXTURE3)
                            glBindTexture(GL_TEXTURE_2D, int(m['occlusion_tex']))
                            self.shader_program.setUniformValue("tex_occlusion", 3)
                            self.shader_program.setUniformValue("has_occlusion_map", True)
                        else:
                            glActiveTexture(GL_TEXTURE3)
                            glBindTexture(GL_TEXTURE_2D, 0)
                            self.shader_program.setUniformValue("has_occlusion_map", False)
                            
                        # Emissive (Tex4)
                        if m.get('emissive_tex'):
                            glActiveTexture(GL_TEXTURE4)
                            glBindTexture(GL_TEXTURE_2D, int(m['emissive_tex']))
                            self.shader_program.setUniformValue("tex_emissive", 4)
                            self.shader_program.setUniformValue("has_emissive_map", True)
                        else:
                            glActiveTexture(GL_TEXTURE4)
                            glBindTexture(GL_TEXTURE_2D, 0)
                            self.shader_program.setUniformValue("has_emissive_map", False)
                        # Bind appropriate VAO
                        if m.get('raw_vao'):
                            glBindVertexArray(int(m['raw_vao']))
                            glDrawElements(GL_TRIANGLES, len(m['indices'].flatten()), GL_UNSIGNED_INT, ctypes.c_void_p(0))
                            glBindVertexArray(0)
                        else:
                            m['vao'].bind()
                            glDrawElements(GL_TRIANGLES, len(m['indices'].flatten()), GL_UNSIGNED_INT, ctypes.c_void_p(0))
                            m['vao'].release()
                        if m.get('texture'):
                            glBindTexture(GL_TEXTURE_2D, 0)
                
                # Second pass: wireframe overlay or wireframe only
                do_wireframe = self.render_mode in ('wireframe', 'overlay', 'triangles') or self.show_edges
                if do_wireframe:
                    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
                    glLineWidth(float(self.line_width))
                    self.shader_program.setUniformValue("wireframe_pass", True)
                    
                    if self.show_hidden_edges:
                        glDisable(GL_DEPTH_TEST)
                        
                    for m in self.meshes:
                        # no texture needed for wireframe pass
                        glBindTexture(GL_TEXTURE_2D, 0)
                        if m.get('raw_vao'):
                            glBindVertexArray(int(m['raw_vao']))
                            glDrawElements(GL_TRIANGLES, len(m['indices'].flatten()), GL_UNSIGNED_INT, ctypes.c_void_p(0))
                            glBindVertexArray(0)
                        else:
                            m['vao'].bind()
                            glDrawElements(GL_TRIANGLES, len(m['indices'].flatten()), GL_UNSIGNED_INT, ctypes.c_void_p(0))
                            m['vao'].release()
                            
                    if self.show_hidden_edges:
                        glEnable(GL_DEPTH_TEST)
                        
                    self.shader_program.setUniformValue("wireframe_pass", False)
                    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
                
                # Third pass: point cloud
                if self.render_mode in ('point_cloud', 'overlay'):
                    glPolygonMode(GL_FRONT_AND_BACK, GL_POINT)
                    glPointSize(float(self.point_size))
                    self.shader_program.setUniformValue("point_mode", True)
                    for m in self.meshes:
                        if m.get('raw_vao'):
                            glBindVertexArray(int(m['raw_vao']))
                            glDrawArrays(GL_POINTS, 0, len(m['vertices']))
                            glBindVertexArray(0)
                        else:
                            m['vao'].bind()
                            glDrawArrays(GL_POINTS, 0, len(m['vertices']))
                            m['vao'].release()
                    self.shader_program.setUniformValue("point_mode", False)

            # Release program at the very end
            self.shader_program.release()

            # Draw visual brush cursor if in weight painting mode
            if hasattr(self, 'weight_painting_mode') and self.weight_painting_mode and self.last_mouse_pos:
                # Simple 2D overlay circle at mouse position
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor(255, 255, 255, 150), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                
                # Draw circle centered at mouse pos
                radius = getattr(self, 'brush_radius', 50)
                center = self.last_mouse_pos
                painter.drawEllipse(center, radius, radius)
                painter.end()

            # 2D overlay: draw XYZ axis labels in RGB using QPainter
            show_labels = getattr(self, 'show_overlays', True)
            try:
                from PyQt6.QtGui import QVector4D
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                # Helper to project 3D to screen
                def project(pt3):
                    v = QVector4D(pt3[0], pt3[1], pt3[2], 1.0)
                    v = mvp_matrix * v
                    if v.w() == 0:
                        return None
                    x_ndc = v.x() / v.w()
                    y_ndc = v.y() / v.w()
                    # Map to window coords (origin top-left)
                    x = (x_ndc * 0.5 + 0.5) * self.width()
                    y = (1.0 - (y_ndc * 0.5 + 0.5)) * self.height()
                    return int(x), int(y)

                origin = project((0.0, 0.0, 0.0))
                px = project((self.axis_length, 0.0, 0.0))
                py = project((0.0, self.axis_length, 0.0))
                pz = project((0.0, 0.0, self.axis_length))
                
                # Draw axes lines and labels if projected points are valid
                if show_labels and origin and px:
                    painter.setPen(QPen(QColor(self.axis_colors['x']), 2))
                    painter.drawLine(*origin, *px)
                    painter.drawText(px[0], px[1], "X")
                if show_labels and origin and py:
                    painter.setPen(QPen(QColor(self.axis_colors['y']), 2))
                    painter.drawLine(*origin, *py)
                    painter.drawText(py[0], py[1], "Y")
                if show_labels and origin and pz:
                    painter.setPen(QPen(QColor(self.axis_colors['z']), 2))
                    painter.drawLine(*origin, *pz)
                    painter.drawText(pz[0], pz[1], "Z")
                    
                painter.end()
            except Exception as e:
                # Painter errors are non-critical
                pass

            name = self.objectName() or f'{type(self).__name__} at 0x{id(self):x}'
            frame_clock.note_frame(name)
                
        except Exception as e:
            frame_clock.note_failure(e)
            self._report_paint_failure(e)

    def _report_paint_failure(self, error) -> None:
        """Say once why the paint raised, not once per frame.

        `paintGL` runs at the frame rate, so an exception here repeats on every repaint. A
        log line per repeat fills the Diagnostics table's 10,000-row cap in under three minutes
        at 60 fps - 167 seconds - and pushes the first, the only one that explains anything, off
        the end. A reason that differs from the last one still gets written.
        """
        reason = f'{type(error).__name__}: {error}'
        if reason == self._last_paint_failure:
            return
        self._last_paint_failure = reason
        logger.warning("paintGL failed: %s", reason)

    def resizeGL(self, width, height):
        """Handle window resize."""
        if not OPENGL_AVAILABLE:
            return
        
        # Only call glViewport if we have a valid GL context
        if not self.isValid():
            return
        
        try:
            self.makeCurrent()
            glViewport(0, 0, width, height)
            self.doneCurrent()
        except Exception as e:
            # Silently ignore GL errors during resize (context might not be ready yet)
            pass
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming."""
        delta = event.angleDelta().y() / 120.0
        self.camera_distance *= (0.9 if delta > 0 else 1.1)
        self.camera_distance = max(0.1, min(20.0, self.camera_distance))
        self.update()
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press."""
        # Left click: Rotation (default) or Custom (if overridden)
        # Right click: Rotation (alternative)
        # Middle click: Pan
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_mouse_pos = event.position()
            self.mouse_mode = 'rotate'
        elif event.button() == Qt.MouseButton.RightButton:
            self.last_mouse_pos = event.position()
            self.mouse_mode = 'rotate'
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.last_mouse_pos = event.position()
            self.mouse_mode = 'pan'
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse movement for rotation and panning."""
        if self.last_mouse_pos is not None:
            dx = event.position().x() - self.last_mouse_pos.x()
            dy = event.position().y() - self.last_mouse_pos.y()
            
            if getattr(self, 'mouse_mode', 'rotate') == 'rotate':
                self.camera_rotation_y += dx * 0.5
                self.camera_rotation_x += dy * 0.5
            elif getattr(self, 'mouse_mode', 'rotate') == 'pan':
                # Simple panning approximation
                pan_speed = self.camera_distance * 0.002
                self.camera_target_x -= dx * pan_speed
                self.camera_target_y += dy * pan_speed
            
            self.last_mouse_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release."""
        self.last_mouse_pos = None
        self.mouse_mode = None
    
    def set_show_edges(self, enabled: bool):
        self.show_edges = enabled
        self.update()

    def set_show_hidden_edges(self, enabled: bool):
        self.show_hidden_edges = enabled
        self.update()

    def set_zebra_direction(self, direction: int):
        self.zebra_direction = direction
        self.update()

    def set_zebra_scale(self, scale: float):
        self.zebra_scale = scale
        self.update()

    def set_curvature_scale(self, scale: float):
        self.curvature_scale = scale
        self.update()

    def set_wireframe_mode(self, enabled: bool):
        """Toggle wireframe rendering."""
        self.wireframe_mode = enabled
        self.update()
        
    def set_render_mode(self, mode: str):
        """Set render mode."""
        self.render_mode = mode
        self.update()
    
    def set_auto_rotate(self, enabled: bool):
        """Toggle auto-rotation."""
        self.auto_rotate = enabled
        if enabled:
            self.rotation_timer.start(16)
        else:
            self.rotation_timer.stop()
    
    def auto_rotation_step(self):
        """Perform one step of auto-rotation."""
        self.model_rotation_y += 1.0
        if self.model_rotation_y >= 360.0:
            self.model_rotation_y = 0.0
        self.update()
    
    def create_grid_geometry(self):
        """Create professional 3D grid and axis geometry."""
        vertices = []
        colors = []
        
        # Create XZ plane grid (horizontal)
        for i in range(self.grid_size + 1):
            offset = -self.grid_extent + i * self.grid_spacing
            is_center = abs(offset) < 1e-6
            
            # X-direction lines (parallel to X axis)
            vertices.extend([[-self.grid_extent, 0, offset], [self.grid_extent, 0, offset]])
            col_xz_x = self.axis_colors['x'] if is_center else self.grid_color
            colors.extend([[*col_xz_x, 1.0], [*col_xz_x, 1.0]])
            
            # Z-direction lines (parallel to Z axis)
            vertices.extend([[offset, 0, -self.grid_extent], [offset, 0, self.grid_extent]])
            col_xz_z = self.axis_colors['z'] if is_center else self.grid_color
            colors.extend([[*col_xz_z, 1.0], [*col_xz_z, 1.0]])
        
        # Create XY plane grid (vertical, facing Z)
        for i in range(self.grid_size + 1):
            offset = -self.grid_extent + i * self.grid_spacing
            is_center = abs(offset) < 1e-6
            
            # X-direction lines in XY plane
            vertices.extend([[-self.grid_extent, offset, 0], [self.grid_extent, offset, 0]])
            col_xy_x = self.axis_colors['x'] if is_center else self.grid_color
            colors.extend([[*col_xy_x, 0.3], [*col_xy_x, 0.3]])  # Dimmer plane
            
            # Y-direction lines in XY plane
            vertices.extend([[offset, -self.grid_extent, 0], [offset, self.grid_extent, 0]])
            col_xy_y = self.axis_colors['y'] if is_center else self.grid_color
            colors.extend([[*col_xy_y, 0.3], [*col_xy_y, 0.3]])  # Dimmer plane
        
        # Create YZ plane grid (vertical, facing X)
        for i in range(self.grid_size + 1):
            offset = -self.grid_extent + i * self.grid_spacing
            is_center = abs(offset) < 1e-6
            
            # Y-direction lines in YZ plane
            vertices.extend([[0, -self.grid_extent, offset], [0, self.grid_extent, offset]])
            col_yz_y = self.axis_colors['y'] if is_center else self.grid_color
            colors.extend([[*col_yz_y, 0.3], [*col_yz_y, 0.3]])  # Dimmer plane
            
            # Z-direction lines in YZ plane
            vertices.extend([[0, offset, -self.grid_extent], [0, offset, self.grid_extent]])
            col_yz_z = self.axis_colors['z'] if is_center else self.grid_color
            colors.extend([[*col_yz_z, 0.3], [*col_yz_z, 0.3]])  # Dimmer plane
        
        # Create main axes with proper colors (shorter center axes for emphasis)
        vertices.extend([[0, 0, 0], [self.axis_length, 0, 0]])
        colors.extend([[*self.axis_colors['x'], 1.0], [*self.axis_colors['x'], 1.0]])
        vertices.extend([[0, 0, 0], [0, self.axis_length, 0]])
        colors.extend([[*self.axis_colors['y'], 1.0], [*self.axis_colors['y'], 1.0]])
        vertices.extend([[0, 0, 0], [0, 0, self.axis_length]])
        colors.extend([[*self.axis_colors['z'], 1.0], [*self.axis_colors['z'], 1.0]])
        
        # Add negative axes (dimmer)
        vertices.extend([[0, 0, 0], [-self.axis_length/2, 0, 0]])
        colors.extend([[*self.axis_colors['x'], 0.5], [*self.axis_colors['x'], 0.5]])
            
        vertices.extend([[0, 0, 0], [0, -self.axis_length/2, 0]])
        colors.extend([[*self.axis_colors['y'], 0.5], [*self.axis_colors['y'], 0.5]])
        vertices.extend([[0, 0, 0], [0, 0, -self.axis_length/2]])
        colors.extend([[*self.axis_colors['z'], 0.5], [*self.axis_colors['z'], 0.5]])
        
        return np.array(vertices, dtype=np.float32), np.array(colors, dtype=np.float32)
    
    def setup_grid_buffers(self):
        """Setup OpenGL buffers for grid and axes."""
        if not self.show_grid or not self.isValid():
            return
            
        vertices, colors = self.create_grid_geometry()
        
        # Create grid VAO/VBO
        if not hasattr(self, 'grid_vao'):
            self.grid_vao = QOpenGLVertexArrayObject()
            self.grid_vao.create()
            self.grid_vbo = QOpenGLBuffer()
            self.grid_vbo.create()
        
        self.grid_vao.bind()
        self.grid_vbo.bind()
        
        # Interleave position and color data
        interleaved = np.column_stack((vertices, colors)).astype(np.float32)
        self.grid_vbo.allocate(interleaved.tobytes(), interleaved.nbytes)
        
        stride = 7 * 4  # 3 pos + 4 color floats
        
        # Position attribute
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        
        # Color attribute (RGBA now)
        glEnableVertexAttribArray(2)
        glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(3 * 4))
        
        # Unbind for safety
        try:
            self.grid_vao.release()
        except Exception:
            pass
        self.grid_vertex_count = len(vertices)
    
    def render_grid_and_axes(self):
        """Render grid and axes with labels."""
        if not self.show_grid or not hasattr(self, 'grid_vao'):
            return

        # Temporarily override uniforms for clean colored grid lines
        try:
            # Force vertex colors and disable lighting for the grid pass
            self.shader_program.setUniformValue("use_vertex_colors", True)
            self.shader_program.setUniformValue("use_lighting", False)
            # Ensure grid isn't tinted by point cloud mode
            prev_point_mode = (self.render_mode == 'point_cloud')
            prev_use_textures = bool(self.use_textures)
            self.shader_program.setUniformValue("point_mode", False)
            self.shader_program.setUniformValue("wireframe_pass", False)
            self.shader_program.setUniformValue("use_textures", False)
            self.shader_program.setUniformValue("has_texture", False)
        except Exception:
            prev_point_mode = False
            prev_use_textures = False

        # Enable blending for transparency
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)  

        # Disable depth test for grid to always show it
        depth_was_enabled = glIsEnabled(GL_DEPTH_TEST)
        if depth_was_enabled:
            glDisable(GL_DEPTH_TEST)
        
        # Set line width for grid
        glLineWidth(1.0)

        # Render grid and axes
        self.grid_vao.bind()
        glDrawArrays(GL_LINES, 0, self.grid_vertex_count)
        self.grid_vao.release()
        
        # Re-enable depth test if it was enabled
        if depth_was_enabled:
            glEnable(GL_DEPTH_TEST)

        # Disable blending
        glDisable(GL_BLEND)

        # Restore lighting and vertex color flags and point/texture modes
        try:
            self.shader_program.setUniformValue("use_lighting", bool(self.use_lighting))
            self.shader_program.setUniformValue("use_vertex_colors", bool(self.use_vertex_colors))
            self.shader_program.setUniformValue("point_mode", prev_point_mode)
            self.shader_program.setUniformValue("use_textures", prev_use_textures)
        except Exception:
            pass
    
    def set_show_grid(self, show: bool):
        """Toggle grid and axes display."""
        self.show_grid = show
        if show and self.isValid():
            self.makeCurrent()
            self.setup_grid_buffers()
            self.doneCurrent()
        self.update()   

    def set_show_overlays(self, show: bool):
        """Toggle the drawn-over UI: the axis labels beside the model."""
        self.show_overlays = bool(show)
        self.update()

    def reset_view(self):
        """Reset camera and model transforms."""
        self.camera_distance = 5.0
        self.camera_rotation_x = 0.0
        self.camera_rotation_y = 0.0
        self.model_rotation_x = 0.0
        self.model_rotation_y = 0.0
        self.model_rotation_z = 0.0
        self.model_scale = 1.0
        self.update()

    def clear(self):
        """Clear the loaded mesh and GL buffers (if any)."""
        self._clear_meshes()
        self.update()

    @staticmethod
    def _read_texture_file(file_path: str):
        """Read a texture file into RGBA bytes, releasing the file on the way out.

        Pillow keeps a file open from Image.open until close, and a texture this app still
        has open is a texture Blender or Unity cannot re-export over.
        """
        from PIL import Image
        img = Image.open(file_path)
        try:
            return np.array(img.convert('RGBA'), dtype=np.uint8)
        finally:
            img.close()

    def set_material_texture(self, texture_type: str, file_path: str):
        """Read a texture file, then assign it to every mesh the viewer holds.

        The read comes before the GL gate so a wrong path is reported whether or not a
        context is up; only the upload needs one.
        """
        try:
            img_data = self._read_texture_file(file_path)
        except Exception as e:
            logger.warning("Failed to load texture: %s (%s)", file_path, e)
            return
        if not self.isValid() or not self.gl_ready:
            return

        try:
            texture_id = self._load_gl_texture(img_data)
            
            if texture_id is None:
                logger.warning("Failed to load texture: %s", file_path)
                return
                
            self.makeCurrent()
            
            # Assign to all meshes
            for m in self.meshes:
                if texture_type == 'albedo':
                    m['texture'] = texture_id
                    m['has_texture'] = True
                elif texture_type == 'normal':
                    m['normal_tex'] = texture_id
                elif texture_type == 'metallic':
                    m['metallic_tex'] = texture_id
                elif texture_type == 'roughness':
                    # We use the same texture for metallic/roughness (GLTF standard)
                    # But if loaded separately, we might need to handle channel packing.
                    # For simplicity, let's assume the user provides a packed map or we just use it as is.
                    # If we want to support separate maps, we'd need shader changes to read from different channels.
                    # For now, let's map 'roughness' to the metallic slot as well, assuming it's a combined map or the user knows.
                    # Or better, let's just map it to metallic_tex and rely on the shader using it.
                    m['metallic_tex'] = texture_id
                elif texture_type == 'occlusion':
                    m['occlusion_tex'] = texture_id
                elif texture_type == 'emissive':
                    m['emissive_tex'] = texture_id
            
            self.update()
            
        except Exception as e:
            logger.warning("Error setting material texture: %s", e)

    def set_render_mode(self, mode: str):
        """Set render mode."""
        self.render_mode = mode
        self.update()
    
    def set_use_vertex_colors(self, enabled: bool):
        self.use_vertex_colors = bool(enabled)
        self.update()
    
    def set_wire_color(self, r: float, g: float, b: float):
        self.wire_color = np.array([r, g, b], dtype=np.float32)
        self.update()
    
    def set_base_color(self, r: float, g: float, b: float):
        self.base_color = np.array([r, g, b], dtype=np.float32)
        self.update()
    
    def set_line_width(self, width: float):
        self.line_width = float(width)
        self.update()

    def set_use_lighting(self, enabled: bool):
        self.use_lighting = enabled
        self.update()
        
    def set_use_textures(self, enabled: bool):
        self.use_textures = enabled
        self.update()
        
    def set_use_vertex_colors(self, enabled: bool):
        self.use_vertex_colors = enabled
        self.update()

    def set_point_color(self, r: float, g: float, b: float):
        """Set point color for point cloud rendering."""
        self.point_color = np.array([r, g, b], dtype=np.float32)
        self.update()

    def set_camera_params(self, fov=None):
        """Update camera lens parameters."""
        if fov is not None:
            self.camera_fov = float(fov)
        self.update()

    def set_post_process_params(self, exposure=None, gamma=None, saturation=None, contrast=None, vignette_enabled=None, vignette_intensity=None):
        """Update post-processing parameters."""
        if exposure is not None: self.exposure = float(exposure)
        if gamma is not None: self.gamma = float(gamma)
        if saturation is not None: self.saturation = float(saturation)
        if contrast is not None: self.contrast = float(contrast)
        if vignette_enabled is not None: self.vignette_enabled = bool(vignette_enabled)
        if vignette_intensity is not None: self.vignette_intensity = float(vignette_intensity)
        self.update()

    def set_env_params(self, rotation=None, blur=None, bg_intensity=None):
        """Update environment settings."""
        if rotation is not None: self.env_rotation_y = float(rotation)
        if blur is not None: self.env_blur = float(blur)
        if bg_intensity is not None: self.env_bg_intensity = float(bg_intensity)
        self.update()

    def load_environment_map(self, file_path: str):
        """Load an environment map (skybox) from an image file."""
        if not OPENGL_AVAILABLE or not self.isValid():
            return
            
        try:
            self.makeCurrent()
            
            # Load image using QImage
            image = QImage(file_path)
            if image.isNull():
                logger.warning("Failed to load environment map: %s", file_path)
                return
                
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            
            # Create texture
            self.env_texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            self.env_texture.setData(image)
            self.env_texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
            self.env_texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            self.env_texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            
            self.has_env_map = True
            self.doneCurrent()
            self.update()
            
        except Exception as e:
            logger.warning("Error loading environment map: %s", e)

    def create_skybox_geometry(self):
        """Create a large cube for the skybox."""
        # Simple cube vertices (CCW winding)
        vertices = np.array([
            # Front
            -1.0, -1.0,  1.0,
             1.0, -1.0,  1.0,
             1.0,  1.0,  1.0,
            -1.0,  1.0,  1.0,
            # Back
            -1.0, -1.0, -1.0,
            -1.0,  1.0, -1.0,
             1.0,  1.0, -1.0,
             1.0, -1.0, -1.0,
        ], dtype=np.float32) * 50.0 # Large scale
        
        indices = np.array([
            0, 1, 2, 2, 3, 0, # Front
            1, 7, 6, 6, 2, 1, # Right
            7, 4, 5, 5, 6, 7, # Back
            4, 0, 3, 3, 5, 4, # Left
            3, 2, 6, 6, 5, 3, # Top
            4, 7, 1, 1, 0, 4  # Bottom
        ], dtype=np.uint32)
        
        self.skybox_vao = QOpenGLVertexArrayObject()
        self.skybox_vao.create()
        self.skybox_vao.bind()
        
        self.skybox_vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.skybox_vbo.create()
        self.skybox_vbo.bind()
        self.skybox_vbo.allocate(vertices.tobytes(), vertices.nbytes)
        
        self.skybox_ebo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        self.skybox_ebo.create()
        self.skybox_ebo.bind()
        self.skybox_ebo.allocate(indices.tobytes(), indices.nbytes)
        
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * 4, ctypes.c_void_p(0))
        
        self.skybox_vao.release()
        self.skybox_vbo.release()
        self.skybox_ebo.release()
        self.skybox_indices_count = len(indices)

    def render_skybox(self, view_matrix, proj_matrix):
        """Render the skybox background."""
        if not hasattr(self, 'has_env_map') or not self.has_env_map:
            return
            
        if not hasattr(self, 'skybox_vao'):
            self.create_skybox_geometry()
            
        glDepthMask(GL_FALSE) # Don't write to depth buffer
        
        self.shader_program.bind()
        self.shader_program.setUniformValue("use_lighting", False)
        self.shader_program.setUniformValue("use_textures", True)
        self.shader_program.setUniformValue("has_texture", True)
        self.shader_program.setUniformValue("skybox_mode", True)
        
        # Remove translation from view matrix for skybox
        view_no_trans = QMatrix4x4(view_matrix)
        view_no_trans.setColumn(3, QVector4D(0, 0, 0, 1))
        
        # Apply environment rotation
        model_rot = QMatrix4x4()
        model_rot.rotate(self.env_rotation_y, 0, 1, 0)
        
        mvp = proj_matrix * view_no_trans * model_rot
        self.shader_program.setUniformValue("mvp", mvp)
        
        self.env_texture.bind()
        self.shader_program.setUniformValue("tex0", 0)
        
        self.skybox_vao.bind()
        glDrawElements(GL_TRIANGLES, self.skybox_indices_count, GL_UNSIGNED_INT, ctypes.c_void_p(0))
        self.skybox_vao.release()
        
        self.env_texture.release()
        self.shader_program.setUniformValue("skybox_mode", False)
        glDepthMask(GL_TRUE)

    def get_vertex_at_screen_pos(self, x: int, y: int) -> tuple[int, int, float]:
        """
        Get the vertex index and mesh index at the given screen coordinates.
        Returns (mesh_index, vertex_index, depth) or (-1, -1, 1.0) if no hit.
        """
        if not self.meshes or not self.shader_program:
            return -1, -1, 1.0
            
        # 1. Unproject screen point to ray
        # Viewport
        viewport = np.array([0, 0, self.width(), self.height()], dtype=np.int32)
        
        # Matrices
        model_matrix = QMatrix4x4()
        model_matrix.translate(self.model_translation_x, self.model_translation_y, self.model_translation_z)
        model_matrix.rotate(self.model_rotation_x, 1, 0, 0)
        model_matrix.rotate(self.model_rotation_y, 0, 1, 0)
        model_matrix.rotate(self.model_rotation_z, 0, 0, 1)
        model_matrix.scale(self.model_scale)
        
        view_matrix = QMatrix4x4()
        view_matrix.translate(0, 0, -self.camera_distance)
        view_matrix.rotate(self.camera_rotation_x, 1, 0, 0)
        view_matrix.rotate(self.camera_rotation_y, 0, 1, 0)
        
        proj_matrix = QMatrix4x4()
        proj_matrix.perspective(self.camera_fov, self.width() / self.height() if self.height() > 0 else 1.0, 0.1, 1000.0)
        
        mvp = proj_matrix * view_matrix * model_matrix
        
        # Ray origin (camera position in model space)
        # Invert ModelView matrix to get camera pos in local space
        mv = view_matrix * model_matrix
        inv_mv, _ = mv.inverted()
        ray_origin = inv_mv * QVector3D(0, 0, 0)
        
        # Ray direction
        # Unproject screen point to near and far planes
        # Y is flipped in screen coords vs OpenGL
        win_y = self.height() - y
        
        # This is a simplified raycast - for precise vertex picking, we iterate vertices
        # and check distance to ray, or use color picking buffer.
        # For performance with dense meshes, we'll use a screen-space distance check 
        # on projected vertices (brute force for now, spatial index later if needed).
        
        best_dist = float('inf')
        best_mesh_idx = -1
        best_vert_idx = -1
        
        # Optimization: Only check vertices if we have a reasonable number, otherwise need acceleration structure
        # For now, limit to checking if total vertices < 50k for real-time performance
        
        # Construct MVP matrix as numpy array for fast multiplication
        mvp_data = np.array(mvp.data(), dtype=np.float32).reshape(4, 4).T
        
        for m_idx, mesh in enumerate(self.meshes):
            verts = mesh['vertices']
            # Add w=1 component
            ones = np.ones((len(verts), 1), dtype=np.float32)
            verts_4d = np.hstack([verts, ones])
            
            # Project all vertices to clip space
            clip_pos = verts_4d @ mvp_data
            
            # Perspective division
            w = clip_pos[:, 3]
            # Avoid division by zero and points behind camera
            mask = w > 0.001
            
            if not np.any(mask):
                continue
                
            ndc = clip_pos[mask, :3] / w[mask, np.newaxis]
            
            # Viewport transform to screen space
            screen_x = (ndc[:, 0] + 1) * 0.5 * self.width()
            screen_y = (ndc[:, 1] + 1) * 0.5 * self.height()
            
            # Calculate distance to mouse position
            dx = screen_x - x
            dy = screen_y - win_y
            dists_sq = dx*dx + dy*dy
            
            # Find closest vertex in screen space
            min_idx_masked = np.argmin(dists_sq)
            min_dist_sq = dists_sq[min_idx_masked]
            
            # Threshold (e.g., 100 pixels radius = 10000 sq pixels) - Increased from 50
            if min_dist_sq < 10000: # 100^2
                # Check depth (z-buffer) to ensure we pick visible vertex
                # This simple check doesn't account for occlusion by other faces
                # But it's a start.
                
                # Map back to original index
                # We need the index in the original 'verts' array
                # 'mask' is a boolean array. We need the index of the True value at min_idx_masked
                true_indices = np.where(mask)[0]
                real_idx = true_indices[min_idx_masked]
                
                # Check if this is closer to camera than previous best
                depth = ndc[min_idx_masked, 2]
                
                if min_dist_sq < best_dist: # Prioritize screen closeness first
                     best_dist = min_dist_sq
                     best_mesh_idx = m_idx
                     best_vert_idx = real_idx
    

        return best_mesh_idx, best_vert_idx, best_dist

    def apply_weight(self, mesh_idx: int, vert_idx: int, weight: float, radius: float, mode: str = "Add"):
        """
        Apply weight to a vertex and its neighbors within radius.
        mode: "Add", "Subtract", "Smooth"
        """
        if mesh_idx < 0 or mesh_idx >= len(self.meshes):
            return
            
        mesh = self.meshes[mesh_idx]
        if 'weights' not in mesh:
            return
            
        # Get target vertex position
        target_pos = mesh['vertices'][vert_idx]
        
        # Find neighbors within radius (naive brute force for now)
        # TODO: Use KDTree or Octree for performance on large meshes
        verts = mesh['vertices']
        dists = np.linalg.norm(verts - target_pos, axis=1)
        mask = dists <= radius
        
        # Calculate falloff (linear)
        falloff = 1.0 - (dists[mask] / radius)
        falloff = np.clip(falloff, 0.0, 1.0)
        
        # Update weights
        current_weights = mesh['weights'][mask].flatten()
        new_weights = current_weights.copy()
        
        strength = weight # Base strength passed in
        
        if mode == "Add":
            new_weights += strength * falloff
        elif mode == "Subtract":
            new_weights -= strength * falloff
        elif mode == "Smooth":
            # Simple average with neighbors
            avg_weight = np.mean(current_weights)
            new_weights = current_weights * (1.0 - strength) + avg_weight * strength
            
        new_weights = np.clip(new_weights, 0.0, 1.0)
        
        # Apply back to mesh weights
        # Ensure shape match (N, 1)
        mesh['weights'][mask] = new_weights.reshape(-1, 1)
        
        # Update VBO
        # We need to update the weight attribute in the VBO
        # Stride is (3+3+4+2+1)*4 = 52 bytes
        # Weight offset is 12*4 = 48 bytes
        
        vbo = mesh.get('vbo')
        if vbo is not None:
            try:
                if not self.isValid():
                    return
            except Exception as e:
                logger.warning("Error checking viewer validity: %s", e)
                return
                
            self.makeCurrent()
            vbo.bind()
            
            # We only update the changed vertices to save bandwidth
            # But mapping buffer might be slow if done frequently.
            # For now, let's try mapping the whole buffer if it's not too huge, 
            # or just using glBufferSubData for the specific range if contiguous (it's not).
            
            # Better approach: Keep a CPU-side interleaved buffer and update it, then re-upload?
            # Or just update the specific float at the offset for each vertex.
            
            # For immediate feedback, we'll iterate and use glBufferSubData for each vertex
            # This is slow for many vertices. 
            # Optimization: Re-upload the whole buffer might be faster than thousands of small calls.
            
            # Let's reconstruct the interleaved data for the affected vertices and upload chunks?
            # Actually, for a brush stroke, re-uploading the whole buffer is probably fine for <100k verts.
            
            # Re-interleave everything (slow-ish but correct)
            # interleaved = np.column_stack((mesh['vertices'], mesh['normals'], mesh['colors'], mesh['uvs'], mesh['weights'])).astype(np.float32)
            # mesh['vbo'].write(0, interleaved.tobytes(), interleaved.nbytes)
            
            # Optimization: Just update the weights?
            # We can't easily update just weights because they are interleaved.
            # We have to update the whole buffer or use strided writes (not standard).
            
            # Let's try the full update for now and see performance.
            interleaved = np.column_stack((
                mesh['vertices'], 
                mesh['normals'], 
                mesh['colors'], 
                mesh['uvs'], 
                mesh['weights']
            )).astype(np.float32)
            
            mesh['vbo'].write(0, interleaved.tobytes(), interleaved.nbytes)
            
            mesh['vbo'].release()
            self.doneCurrent()

    def apply_color(self, mesh_idx: int, vert_idx: int, color: list, radius: float, mode: str = "Mix"):
        """
        Apply color to a vertex and its neighbors within radius.
        color: [r, g, b] (0.0-1.0)
        mode: "Mix", "Add", "Subtract"
        """
        if mesh_idx < 0 or mesh_idx >= len(self.meshes):
            return
            
        mesh = self.meshes[mesh_idx]
        if 'colors' not in mesh:
            # Initialize if missing (should be handled elsewhere but safety first)
            num_verts = len(mesh['vertices'])
            mesh['colors'] = np.ones((num_verts, 4), dtype=np.float32)
            
        # Get target vertex position
        target_pos = mesh['vertices'][vert_idx]
        
        # Find neighbors within radius
        verts = mesh['vertices']
        dists = np.linalg.norm(verts - target_pos, axis=1)
        mask = dists <= radius
        
        # Calculate falloff (linear)
        falloff = 1.0 - (dists[mask] / radius)
        falloff = np.clip(falloff, 0.0, 1.0)
        
        # Reshape falloff for broadcasting (N, 1)
        falloff = falloff.reshape(-1, 1)
        
        # Update colors
        # We only touch RGB, leave Alpha as 1.0
        current_colors = mesh['colors'][mask][:, :3]
        target_color = np.array(color[:3], dtype=np.float32)
        
        new_colors = current_colors.copy()
        
        # Strength is implicit in falloff for now, or we could add a strength param
        # Assuming falloff acts as the "amount" to mix
        
        if mode == "Mix":
            # Lerp: current * (1 - falloff) + target * falloff
            new_colors = current_colors * (1.0 - falloff) + target_color * falloff
        elif mode == "Add":
            new_colors += target_color * falloff
        elif mode == "Subtract":
            new_colors -= target_color * falloff
            
        new_colors = np.clip(new_colors, 0.0, 1.0)
        
        # Apply back to mesh colors
        mesh['colors'][mask, :3] = new_colors
        
        # Update VBO
        vbo = mesh.get('vbo')
        if vbo is not None:
            try:
                if not self.isValid():
                    return
            except Exception:
                return
                
            self.makeCurrent()
            vbo.bind()
            
            interleaved = np.column_stack((
                mesh['vertices'], 
                mesh['normals'], 
                mesh['colors'], 
                mesh['uvs'], 
                mesh['weights']
            )).astype(np.float32)
            
            vbo.write(0, interleaved.tobytes(), interleaved.nbytes)
            
            vbo.release()
            self.doneCurrent()
            
        self.update()

    def export_model(self, file_path: str) -> bool:
        """Export the current model with vertex colors/weights to a file."""
        if not self.meshes:
            logger.warning("Model export to %s refused: nothing is loaded", file_path)
            return False
            
        try:
            import trimesh
            import numpy as np
            
            # Create a list of trimesh objects
            export_meshes = []
            
            for mesh_data in self.meshes:
                vertices = mesh_data['vertices']
                faces = mesh_data['faces']
                
                # Create mesh
                mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
                
                # Apply vertex colors if they exist
                if 'colors' in mesh_data:
                    # Convert 0-1 float to 0-255 uint8
                    colors = (mesh_data['colors'] * 255).astype(np.uint8)
                    mesh.visual.vertex_colors = colors
                
                # TODO: Handle weights if exporting to a format that supports them (like custom glTF extras)
                # For now, we primarily care about vertex colors for visual export
                
                export_meshes.append(mesh)
            
            if len(export_meshes) == 1:
                scene = export_meshes[0]
            else:
                scene = trimesh.Scene(export_meshes)
                
            # Export
            scene.export(file_path)
            return True
            
        except Exception as e:
            logger.warning("Model export to %s failed: %s", file_path, e)
            return False

class ModelViewerWidget(QWidget):
    """Complete model viewer widget with controls."""
    
    model_loaded = pyqtSignal(dict)  # Add missing signal
    cleared = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Use the appropriate viewer based on OpenGL availability
        if (OPENGL_AVAILABLE):
            self.viewer_3d = ModelViewer3D()
        else:
            self.viewer_3d = SimpleModelViewer()
            
        self._using_fallback = not OPENGL_AVAILABLE
        self._load_seq = 0  # cancels stale pending loads
        self.init_ui()
        self.setup_connections()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # 3D viewer
        layout.addWidget(self.viewer_3d, 1)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # View controls
        self.wireframe_cb = QCheckBox("Wireframe")
        self.auto_rotate_cb = QCheckBox("Auto Rotate")
        self.reset_view_btn = QPushButton("Reset View")
        self.clear_view_btn = QPushButton("Clear Viewer")
        
        # Disable controls if OpenGL is not available
        if not OPENGL_AVAILABLE:
            self.wireframe_cb.setEnabled(False)
            self.auto_rotate_cb.setEnabled(False)
            self.reset_view_btn.setEnabled(False)
        
        controls_layout.addWidget(self.wireframe_cb)
        controls_layout.addWidget(self.auto_rotate_cb)
        controls_layout.addWidget(self.reset_view_btn)
        controls_layout.addWidget(self.clear_view_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Info panel
        self.info_label = QLabel("No model loaded")
        self.info_label.setStyleSheet("background: #1d1d1d; padding: 5px; margin: 2px;")
        layout.addWidget(self.info_label)
        
        # Show OpenGL status
        if not OPENGL_AVAILABLE:
            status_label = QLabel("PyOpenGL not installed - 3D preview unavailable")
            status_label.setStyleSheet("background: #ffeecc; color: #cc6600; padding: 5px; margin: 2px;")
            layout.addWidget(status_label)
    
    def setup_connections(self):
        """Setup signal connections."""
        # Map single checkbox to fill/wireframe modes
        self.wireframe_cb.toggled.connect(lambda on: self.set_render_mode('wireframe' if on else 'fill'))
        self.auto_rotate_cb.toggled.connect(self.viewer_3d.set_auto_rotate)
        self.reset_view_btn.clicked.connect(self.viewer_3d.reset_view)
        self.clear_view_btn.clicked.connect(self.clear)
        # Forward the model_loaded signal from internal viewer
        self.viewer_3d.model_loaded.connect(self.model_loaded.emit)
        self.viewer_3d.model_loaded.connect(self.update_model_info)
    
    # Expose controls for settings tab
    def set_material_texture(self, texture_type: str, file_path: str):
        """Assign a texture file to the mesh the inner viewer is showing."""
        if hasattr(self.viewer_3d, 'set_material_texture'):
            self.viewer_3d.set_material_texture(texture_type, file_path)

    def set_render_mode(self, mode: str):
        if hasattr(self.viewer_3d, 'set_render_mode'):
            self.viewer_3d.set_render_mode(mode)
    
    def set_use_lighting(self, enabled: bool):
        if hasattr(self.viewer_3d, 'set_use_lighting'):
            self.viewer_3d.set_use_lighting(enabled)
    
    def set_use_textures(self, enabled: bool):
        if hasattr(self.viewer_3d, 'set_use_textures'):
            self.viewer_3d.set_use_textures(enabled)
    
    def set_use_vertex_colors(self, enabled: bool):
        if hasattr(self.viewer_3d, 'set_use_vertex_colors'):
            self.viewer_3d.set_use_vertex_colors(enabled)
    
    def set_light_position(self, x: float, y: float, z: float):
        if hasattr(self.viewer_3d, 'set_light_position'):
            self.viewer_3d.set_light_position(x, y, z)
    
    def set_lighting_params(self, ambient: float = None, diffuse: float = None, specular: float = None, shininess: float = None):
        if hasattr(self.viewer_3d, 'set_lighting_params'):
            self.viewer_3d.set_lighting_params(ambient, diffuse, specular, shininess)
    
    def set_wire_color(self, r: float, g: float, b: float):
        if hasattr(self.viewer_3d, 'set_wire_color'):
            self.viewer_3d.set_wire_color(r, g, b)
    
    def set_base_color(self, r: float, g: float, b: float):
        if hasattr(self.viewer_3d, 'set_base_color'):
            self.viewer_3d.set_base_color(r, g, b)
    
    def set_line_width(self, width: float):
        if hasattr(self.viewer_3d, 'set_line_width'):
            self.viewer_3d.set_line_width(width)
    
    def set_point_size(self, size: float):
        """Set point size for point cloud rendering."""
        if hasattr(self.viewer_3d, 'point_size'):
            self.viewer_3d.point_size = float(size)
            if hasattr(self.viewer_3d, 'update'):
                self.viewer_3d.update()
    
    def set_point_color(self, r: float, g: float, b: float):
        """Set point color for point cloud rendering."""
        if hasattr(self.viewer_3d, 'set_point_color'):
            self.viewer_3d.set_point_color(r, g, b)

    def set_show_grid(self, show: bool):
        """Toggle grid and axes display."""
        if hasattr(self.viewer_3d, 'set_show_grid'):
            self.viewer_3d.set_show_grid(show)

    def load_model(self, file_path: str) -> bool:
        """Load a model file with automatic retry until GL is ready.
        Returns True if a load was started successfully, False if immediate failure (e.g., fallback also failed).
        """
        # Cancel any previous pending attempts
        self._load_seq += 1
        current_seq = self._load_seq
        
        # If we're already using fallback, just load immediately there
        if self._using_fallback:
            success = self.viewer_3d.load_model(file_path)
            if not success:
                self.info_label.setText("Failed to load model")
            return success
        
        # Try repeatedly until GL context is valid and ready, then load.
        def attempt(retries_left=200):  # up to ~10 seconds total at 50ms
            if current_seq != self._load_seq:
                return  # canceled by a newer request or clear()
            try_ready = hasattr(self.viewer_3d, 'isValid') and self.viewer_3d.isValid() and getattr(self.viewer_3d, 'gl_ready', False)
            if not try_ready:
                if retries_left > 0:
                    QTimer.singleShot(50, lambda: attempt(retries_left - 1))
                else:
                    # Give up without switching to fallback; caller can retry later
                    self.info_label.setText("Viewer not ready. Please try again.")
                return
            # GL is ready, perform the actual load
            ok = self.viewer_3d.load_model(file_path)
            if not ok:
                # Do not switch to fallback automatically; just report failure
                self.info_label.setText("Failed to load model")
        
        attempt()
        return True
    
    def _switch_to_fallback(self):
        """Replace the GL viewer with the simple fallback at runtime."""
        try:
            layout = self.layout()
            if layout is None:
                return
            # Remove old viewer widget
            layout.removeWidget(self.viewer_3d)
            self.viewer_3d.setParent(None)
            self.viewer_3d.deleteLater()
            # Create fallback viewer and insert
            self.viewer_3d = SimpleModelViewer()
            layout.insertWidget(0, self.viewer_3d, 1)
            # Reconnect signals
            self.wireframe_cb.setEnabled(False)
            self.auto_rotate_cb.setEnabled(False)
            self.reset_view_btn.setEnabled(False)
            self.viewer_3d.model_loaded.connect(self.model_loaded.emit)
            self.viewer_3d.model_loaded.connect(self.update_model_info)
            self._using_fallback = True
        except Exception as e:
            logger.error("Failed to switch to fallback viewer: %s", e)
    
    def update_model_info(self, info: dict):
        """Update model information display."""
        text = f"Vertices: {info['vertices']:,} | Faces: {info['faces']:,} | "
        text += f"Surface Area: {info['surface_area']:.2f}"
        if info.get('volume', 0) > 0:
            text += f" | Volume: {info['volume']:.2f}"
        
        self.info_label.setText(text)
    
    def clear(self):
        """Clear viewer and info panel, emit cleared signal."""
        try:
            # Cancel pending loads
            self._load_seq += 1
            if hasattr(self.viewer_3d, 'clear'):
                self.viewer_3d.clear()
            self.info_label.setText("No model loaded")
            self.cleared.emit()
        except Exception as e:
            logger.error("Viewer clear failed: %s", e)


    def apply_color(self, mesh_idx: int, vert_idx: int, color: list, radius: float, mode: str = "Mix"):
        """
        Apply color to a vertex and its neighbors within radius.
        color: [r, g, b] in 0-1 range
        mode: "Mix", "Add", "Subtract"
        """
        if mesh_idx < 0 or mesh_idx >= len(self.meshes):
            return
            
        mesh = self.meshes[mesh_idx]
        if 'colors' not in mesh:
            return
            
        # Get target vertex position
        target_pos = mesh['vertices'][vert_idx]
        
        # Find neighbors within radius (naive)
        verts = mesh['vertices']
        dists = np.linalg.norm(verts - target_pos, axis=1)
        mask = dists <= radius
        
        # Calculate falloff
        falloff = 1.0 - (dists[mask] / radius)
        falloff = np.clip(falloff, 0.0, 1.0)
        
        # Update colors
        # colors are Nx4 (RGBA)
        current_colors = mesh['colors'][mask]
        new_colors = current_colors.copy()
        
        brush_color = np.array(color, dtype=np.float32)
        
        # Apply per vertex based on falloff strength
        # We iterate or vectorize. Vectorized is better.
        # falloff is (M,)
        # brush_color is (3,)
        
        # Expand falloff for RGB broadcasting
        alpha = falloff[:, np.newaxis] # (M, 1)
        
        if mode == "Mix":
            # Linear interpolation: Current * (1-alpha) + Brush * alpha
            # Only affect RGB, keep A=1.0 or preserve? Let's preserve A.
            new_colors[:, :3] = current_colors[:, :3] * (1.0 - alpha) + brush_color * alpha
            
        elif mode == "Add":
            new_colors[:, :3] += brush_color * alpha
            
        elif mode == "Subtract":
            new_colors[:, :3] -= brush_color * alpha
            
        new_colors[:, :3] = np.clip(new_colors[:, :3], 0.0, 1.0)
        
        # Apply back
        mesh['colors'][mask] = new_colors
        
        # Update VBO
        vbo = mesh.get('vbo')
        if vbo:
            try:
                if not self.isValid(): return
                self.makeCurrent()
                vbo.bind()
                
                # Re-interleave
                interleaved = np.column_stack((
                    mesh['vertices'], 
                    mesh['normals'], 
                    mesh['colors'], 
                    mesh['uvs'], 
                    mesh['weights']
                )).astype(np.float32)
                
                vbo.write(0, interleaved.tobytes(), interleaved.nbytes)
                vbo.release()
                self.doneCurrent()
            except Exception:
                pass
        
        self.update()
