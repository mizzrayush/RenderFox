"""
Advanced thumbnail generation system for 3D models in the Library Tab.
Supports multiple rendering backends and intelligent caching.
"""

import os
import hashlib
import threading
from typing import Optional, Dict, Any, Callable
from pathlib import Path
import numpy as np
from PIL import Image
import json

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QPixmap

try:
    import open3d as o3d
    import trimesh
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False

class ThumbnailCache:
    """Intelligent caching system for thumbnails with metadata."""
    
    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "cache_metadata.json"
        self.metadata = self._load_metadata()
        
    def _load_metadata(self) -> Dict[str, Any]:
        """Load cache metadata."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _save_metadata(self):
        """Save cache metadata."""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2)
        except Exception as e:
            print(f"Failed to save cache metadata: {e}")
    
    def _get_file_hash(self, file_path: str) -> str:
        """Generate hash for file based on path, size, and modification time."""
        try:
            stat = os.stat(file_path)
            hash_string = f"{file_path}_{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(hash_string.encode()).hexdigest()
        except Exception:
            return hashlib.md5(file_path.encode()).hexdigest()
    
    def get_thumbnail_path(self, file_path: str, size: tuple = (256, 256)) -> Optional[str]:
        """Get cached thumbnail path if it exists and is valid."""
        file_hash = self._get_file_hash(file_path)
        cache_key = f"{file_hash}_{size[0]}x{size[1]}"
        
        if cache_key in self.metadata:
            thumbnail_path = self.cache_dir / f"{cache_key}.png"
            if thumbnail_path.exists():
                return str(thumbnail_path)
        
        return None
    
    def store_thumbnail(self, file_path: str, thumbnail: QPixmap, size: tuple = (256, 256)) -> str:
        """Store thumbnail in cache and return path."""
        file_hash = self._get_file_hash(file_path)
        cache_key = f"{file_hash}_{size[0]}x{size[1]}"
        thumbnail_path = self.cache_dir / f"{cache_key}.png"
        
        # Save thumbnail
        if thumbnail.save(str(thumbnail_path), "PNG"):
            # Update metadata
            self.metadata[cache_key] = {
                'original_file': file_path,
                'size': size,
                'created': os.path.getmtime(file_path),
                'hash': file_hash
            }
            self._save_metadata()
            return str(thumbnail_path)
        
        return None
    
    def clear_invalid_entries(self):
        """Remove invalid cache entries."""
        to_remove = []
        for cache_key, info in self.metadata.items():
            thumbnail_path = self.cache_dir / f"{cache_key}.png"
            original_file = info.get('original_file', '')
            
            # Check if thumbnail file exists
            if not thumbnail_path.exists():
                to_remove.append(cache_key)
                continue
            
            # Check if original file still exists
            if not os.path.exists(original_file):
                to_remove.append(cache_key)
                try:
                    thumbnail_path.unlink()
                except Exception:
                    pass
                continue
            
            # Check if original file was modified
            current_hash = self._get_file_hash(original_file)
            if current_hash != info.get('hash', ''):
                to_remove.append(cache_key)
                try:
                    thumbnail_path.unlink()
                except Exception:
                    pass
        
        # Remove invalid entries
        for key in to_remove:
            del self.metadata[key]
        
        if to_remove:
            self._save_metadata()

class ThumbnailGenerationThread(QThread):
    """Thread for generating thumbnails without blocking the UI."""
    
    thumbnail_ready = pyqtSignal(str, QPixmap)  # file_path, thumbnail
    generation_failed = pyqtSignal(str, str)    # file_path, error_message
    progress_updated = pyqtSignal(str, int)     # file_path, progress_percent
    
    def __init__(self, file_path: str, size: tuple = (256, 256), 
                 render_mode: str = 'fill', use_lighting: bool = True):
        super().__init__()
        self.file_path = file_path
        self.size = size
        self.render_mode = render_mode
        self.use_lighting = use_lighting
        self._cancelled = False
    
    def cancel(self):
        """Cancel thumbnail generation."""
        self._cancelled = True
    
    def run(self):
        """Generate thumbnail in background thread."""
        if self._cancelled:
            return
        
        try:
            self.progress_updated.emit(self.file_path, 10)
            
            if not OPEN3D_AVAILABLE:
                self.generation_failed.emit(self.file_path, "Open3D not available")
                return
            
            if self._cancelled:
                return
            
            # Load model
            self.progress_updated.emit(self.file_path, 30)
            meshes = self._load_model()
            
            if not meshes or self._cancelled:
                self.generation_failed.emit(self.file_path, "Failed to load model")
                return
            
            self.progress_updated.emit(self.file_path, 60)
            
            # Generate thumbnail
            thumbnail = self._generate_thumbnail(meshes)
            
            if thumbnail and not self._cancelled:
                self.progress_updated.emit(self.file_path, 100)
                self.thumbnail_ready.emit(self.file_path, thumbnail)
            else:
                self.generation_failed.emit(self.file_path, "Failed to generate thumbnail")
                
        except Exception as e:
            if not self._cancelled:
                self.generation_failed.emit(self.file_path, str(e))
    
    def _load_model(self) -> list:
        """Load 3D model using trimesh and convert to Open3D."""
        try:
            scene_or_mesh = trimesh.load(self.file_path)
            meshes = []
            
            if isinstance(scene_or_mesh, trimesh.Scene):
                for name, geom in (scene_or_mesh.geometry or {}).items():
                    if isinstance(geom, trimesh.Trimesh) and len(geom.faces) > 0:
                        o3d_mesh = self._trimesh_to_open3d(geom)
                        if o3d_mesh is not None:
                            meshes.append(o3d_mesh)
            elif isinstance(scene_or_mesh, trimesh.Trimesh):
                if len(scene_or_mesh.faces) > 0:
                    o3d_mesh = self._trimesh_to_open3d(scene_or_mesh)
                    if o3d_mesh is not None:
                        meshes.append(o3d_mesh)
            
            return meshes
            
        except Exception as e:
            print(f"Failed to load model {self.file_path}: {e}")
            return []
    
    def _trimesh_to_open3d(self, trimesh_obj) -> Optional[object]:
        """Convert trimesh object to Open3D mesh."""
        try:
            # Create Open3D mesh
            o3d_mesh = o3d.geometry.TriangleMesh()
            o3d_mesh.vertices = o3d.utility.Vector3dVector(trimesh_obj.vertices)
            o3d_mesh.triangles = o3d.utility.Vector3iVector(trimesh_obj.faces)
            
            # Add vertex colors if available
            if hasattr(trimesh_obj.visual, 'vertex_colors'):
                colors = trimesh_obj.visual.vertex_colors
                if colors is not None and len(colors) > 0:
                    if colors.dtype == np.uint8:
                        colors = colors.astype(np.float64) / 255.0
                    if colors.shape[1] > 3:
                        colors = colors[:, :3]  # Remove alpha
                    o3d_mesh.vertex_colors = o3d.utility.Vector3dVector(colors)
            
            # Compute normals
            o3d_mesh.compute_vertex_normals()
            
            return o3d_mesh
            
        except Exception as e:
            print(f"Failed to convert trimesh to Open3D: {e}")
            return None
    
    def _generate_thumbnail(self, meshes: list) -> Optional[QPixmap]:
        """Generate thumbnail using Open3D."""
        if self._cancelled:
            return None
        
        vis = None
        try:
            # Create offscreen visualizer
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False, width=self.size[0], height=self.size[1])
            
            # Normalize meshes
            all_bounds = []
            for mesh in meshes:
                bounds = mesh.get_axis_aligned_bounding_box()
                all_bounds.extend([bounds.min_bound, bounds.max_bound])
            
            if all_bounds:
                all_bounds = np.array(all_bounds)
                min_bound = all_bounds.min(axis=0)
                max_bound = all_bounds.max(axis=0)
                center = (min_bound + max_bound) / 2
                size = np.max(max_bound - min_bound)
                
                for mesh in meshes:
                    mesh.translate(-center)
                    if size > 0:
                        mesh.scale(2.0 / size, center=[0, 0, 0])
            
            # Add meshes based on render mode
            if self.render_mode == 'wireframe':
                for mesh in meshes:
                    wireframe = o3d.geometry.LineSet.create_from_triangle_mesh(mesh)
                    wireframe.paint_uniform_color([0.0, 1.0, 0.0])
                    vis.add_geometry(wireframe)
            elif self.render_mode == 'points':
                for mesh in meshes:
                    if hasattr(mesh, 'sample_points_uniformly'):
                        pcd = mesh.sample_points_uniformly(number_of_points=10000)
                        vis.add_geometry(pcd)
            else:  # fill mode
                for mesh in meshes:
                    # Apply default color if no vertex colors
                    if not hasattr(mesh, 'vertex_colors') or len(mesh.vertex_colors) == 0:
                        mesh.paint_uniform_color([0.7, 0.7, 0.9])
                    vis.add_geometry(mesh)
            
            if self._cancelled:
                return None
            
            # Configure render settings
            render_opt = vis.get_render_option()
            render_opt.background_color = np.array([0.1, 0.1, 0.1])
            render_opt.light_on = self.use_lighting
            render_opt.point_size = 3.0
            render_opt.line_width = 1.0
            
            # Set optimal camera view
            ctr = vis.get_view_control()
            ctr.set_front([0.5, -0.5, -0.5])
            ctr.set_lookat([0, 0, 0])
            ctr.set_up([0, 1, 0])
            ctr.set_zoom(0.8)
            
            # Render
            vis.poll_events()
            vis.update_renderer()
            
            if self._cancelled:
                return None
            
            # Capture image
            image = vis.capture_screen_float_buffer(do_render=True)
            
            if image is not None:
                # Convert to QPixmap
                image_np = (np.asarray(image) * 255).astype(np.uint8)
                
                from PyQt6.QtGui import QImage
                height, width, channels = image_np.shape
                bytes_per_line = channels * width
                
                q_image = QImage(
                    image_np.data, 
                    width, 
                    height, 
                    bytes_per_line, 
                    QImage.Format.Format_RGB888
                )
                
                return QPixmap.fromImage(q_image)
            
            return None
            
        except Exception as e:
            print(f"Failed to generate thumbnail: {e}")
            return None
        finally:
            if vis is not None:
                try:
                    vis.destroy_window()
                except Exception:
                    pass

class ThumbnailGenerator(QObject):
    """Main thumbnail generator with queue management and caching."""
    
    thumbnail_ready = pyqtSignal(str, QPixmap)
    generation_failed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(str, int)
    
    def __init__(self, cache_dir: str = None):
        super().__init__()
        
        if cache_dir is None:
            cache_dir = os.path.join(os.path.expanduser("~"), ".renderfox", "thumbnails")
        
        self.cache = ThumbnailCache(cache_dir)
        self.generation_queue = []
        self.active_threads = {}
        self.max_concurrent = 3
        self.default_size = (256, 256)
        
        # Cleanup timer
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self._cleanup_cache)
        self.cleanup_timer.start(300000)  # 5 minutes
    
    def generate_thumbnail(self, file_path: str, size: tuple = None, 
                         render_mode: str = 'fill', use_lighting: bool = True,
                         force_regenerate: bool = False) -> bool:
        """Generate or retrieve thumbnail for a 3D model file."""
        if size is None:
            size = self.default_size
        
        # Check cache first (unless forced regeneration)
        if not force_regenerate:
            cached_path = self.cache.get_thumbnail_path(file_path, size)
            if cached_path:
                try:
                    pixmap = QPixmap(cached_path)
                    if not pixmap.isNull():
                        self.thumbnail_ready.emit(file_path, pixmap)
                        return True
                except Exception:
                    pass
        
        # Check if already in queue or being processed
        if file_path in self.active_threads:
            return False
        
        if file_path in [item[0] for item in self.generation_queue]:
            return False
        
        # Add to queue
        self.generation_queue.append((file_path, size, render_mode, use_lighting))
        self._process_queue()
        return True
    
    def _process_queue(self):
        """Process thumbnail generation queue."""
        if len(self.active_threads) >= self.max_concurrent:
            return
        
        if not self.generation_queue:
            return
        
        # Start next generation
        file_path, size, render_mode, use_lighting = self.generation_queue.pop(0)
        
        thread = ThumbnailGenerationThread(file_path, size, render_mode, use_lighting)
        thread.thumbnail_ready.connect(self._on_thumbnail_ready)
        thread.generation_failed.connect(self._on_generation_failed)
        thread.progress_updated.connect(self.progress_updated)
        thread.finished.connect(lambda: self._on_thread_finished(file_path))
        
        self.active_threads[file_path] = thread
        thread.start()
    
    def _on_thumbnail_ready(self, file_path: str, thumbnail: QPixmap):
        """Handle successful thumbnail generation."""
        # Store in cache
        self.cache.store_thumbnail(file_path, thumbnail)
        
        # Emit signal
        self.thumbnail_ready.emit(file_path, thumbnail)
    
    def _on_generation_failed(self, file_path: str, error: str):
        """Handle failed thumbnail generation."""
        self.generation_failed.emit(file_path, error)
    
    def _on_thread_finished(self, file_path: str):
        """Handle thread completion."""
        if file_path in self.active_threads:
            del self.active_threads[file_path]
        
        # Process next item in queue
        self._process_queue()
    
    def cancel_generation(self, file_path: str):
        """Cancel thumbnail generation for a specific file."""
        # Remove from queue
        self.generation_queue = [item for item in self.generation_queue if item[0] != file_path]
        
        # Cancel active thread
        if file_path in self.active_threads:
            self.active_threads[file_path].cancel()
    
    def cancel_all(self):
        """Cancel all thumbnail generation."""
        self.generation_queue.clear()
        
        for thread in self.active_threads.values():
            thread.cancel()
    
    def _cleanup_cache(self):
        """Periodic cache cleanup."""
        try:
            self.cache.clear_invalid_entries()
        except Exception as e:
            print(f"Cache cleanup failed: {e}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        cache_size = 0
        file_count = 0
        
        try:
            for file_path in self.cache.cache_dir.glob("*.png"):
                cache_size += file_path.stat().st_size
                file_count += 1
        except Exception:
            pass
        
        return {
            'file_count': file_count,
            'cache_size_mb': cache_size / (1024 * 1024),
            'cache_dir': str(self.cache.cache_dir)
        }
    
    def clear_cache(self):
        """Clear all cached thumbnails."""
        try:
            for file_path in self.cache.cache_dir.glob("*.png"):
                file_path.unlink()
            
            self.cache.metadata.clear()
            self.cache._save_metadata()
        except Exception as e:
            print(f"Failed to clear cache: {e}")