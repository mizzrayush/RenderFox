"""
RenderFox Advanced Mesh Processor
Provides comprehensive mesh processing, repair, optimization, and analysis tools.
"""

import os
import numpy as np
import tempfile
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import json

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

try:
    import pymeshlab
    PYMESHLAB_AVAILABLE = True
except ImportError:
    PYMESHLAB_AVAILABLE = False

from PyQt6.QtCore import QObject, pyqtSignal, QThread


@dataclass
class MeshStatistics:
    """Container for mesh statistics."""
    vertices: int
    faces: int
    edges: int
    is_watertight: bool
    is_manifold: bool
    volume: float
    surface_area: float
    bounding_box: Tuple[float, float, float]
    has_textures: bool
    has_normals: bool
    has_colors: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'vertices': self.vertices,
            'faces': self.faces,
            'edges': self.edges,
            'is_watertight': self.is_watertight,
            'is_manifold': self.is_manifold,
            'volume': self.volume,
            'surface_area': self.surface_area,
            'bounding_box': self.bounding_box,
            'has_textures': self.has_textures,
            'has_normals': self.has_normals,
            'has_colors': self.has_colors
        }


class TempFileManager:
    """Context manager for temporary file handling."""
    
    def __init__(self):
        self.temp_files = []
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        
    def get_temp_path(self, suffix='.obj'):
        """Create a temp file and return its path."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self.temp_files.append(path)
        return path
        
    def cleanup(self):
        """Remove all tracked temporary files."""
        for path in self.temp_files:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

class MeshAnalyzer:
    """Analyze mesh properties and quality."""
    
    @staticmethod
    def analyze_mesh(mesh_path: str) -> Optional[MeshStatistics]:
        """Analyze a mesh file and return statistics."""
        if not TRIMESH_AVAILABLE:
            return None
        
        try:
            mesh = trimesh.load(mesh_path)
            
            # Handle Scene objects (GLB/GLTF)
            if isinstance(mesh, trimesh.Scene):
                if len(mesh.geometry) == 0:
                    raise ValueError("Scene is empty")
                # Concatenate all geometries
                geometries = list(mesh.geometry.values())
                if len(geometries) == 1:
                    mesh = geometries[0]
                else:
                    mesh = trimesh.util.concatenate(geometries)
            
            # Calculate statistics
            vertices = len(mesh.vertices) if hasattr(mesh, 'vertices') else 0
            faces = len(mesh.faces) if hasattr(mesh, 'faces') else 0
            edges = len(mesh.edges) if hasattr(mesh, 'edges') else 0
            
            is_watertight = mesh.is_watertight if hasattr(mesh, 'is_watertight') else False
            is_manifold = mesh.is_winding_consistent if hasattr(mesh, 'is_winding_consistent') else False
            
            volume = float(mesh.volume) if hasattr(mesh, 'volume') else 0.0
            surface_area = float(mesh.area) if hasattr(mesh, 'area') else 0.0
            
            bounds = mesh.bounds if hasattr(mesh, 'bounds') else [[0, 0, 0], [0, 0, 0]]
            bbox_size = tuple(bounds[1] - bounds[0])
            
            has_textures = hasattr(mesh, 'visual') and hasattr(mesh.visual, 'uv')
            has_normals = hasattr(mesh, 'vertex_normals')
            has_colors = hasattr(mesh, 'visual') and hasattr(mesh.visual, 'vertex_colors')
            
            return MeshStatistics(
                vertices=vertices,
                faces=faces,
                edges=edges,
                is_watertight=is_watertight,
                is_manifold=is_manifold,
                volume=volume,
                surface_area=surface_area,
                bounding_box=bbox_size,
                has_textures=has_textures,
                has_normals=has_normals,
                has_colors=has_colors
            )
        except Exception as e:
            print(f"Error analyzing mesh: {e}")
            return None
    
    @staticmethod
    def detect_issues(mesh_path: str) -> List[Dict[str, str]]:
        """Detect common mesh issues."""
        issues = []
        
        if not TRIMESH_AVAILABLE:
            return [{'type': 'Error', 'description': 'Trimesh not available'}]
        
        try:
            mesh = trimesh.load(mesh_path)
            
            # Check for non-manifold edges
            if hasattr(mesh, 'is_winding_consistent') and not mesh.is_winding_consistent:
                issues.append({
                    'type': 'Non-Manifold',
                    'severity': 'High',
                    'description': 'Mesh has non-manifold edges',
                    'fix': 'Use mesh repair tools'
                })
            
            # Check for holes
            if hasattr(mesh, 'is_watertight') and not mesh.is_watertight:
                issues.append({
                    'type': 'Not Watertight',
                    'severity': 'Medium',
                    'description': 'Mesh has holes or gaps',
                    'fix': 'Fill holes or repair mesh'
                })
            
            # Check for degenerate faces
            if hasattr(mesh, 'faces'):
                face_areas = mesh.area_faces if hasattr(mesh, 'area_faces') else []
                degenerate = sum(1 for area in face_areas if area < 1e-10)
                if degenerate > 0:
                    issues.append({
                        'type': 'Degenerate Faces',
                        'severity': 'Low',
                        'description': f'{degenerate} faces with near-zero area',
                        'fix': 'Remove degenerate faces'
                    })
            
            # Check for isolated vertices
            if hasattr(mesh, 'vertices') and hasattr(mesh, 'faces'):
                used_vertices = set(mesh.faces.flatten())
                isolated = len(mesh.vertices) - len(used_vertices)
                if isolated > 0:
                    issues.append({
                        'type': 'Isolated Vertices',
                        'severity': 'Low',
                        'description': f'{isolated} vertices not used by any face',
                        'fix': 'Remove isolated vertices'
                    })
            
        except Exception as e:
            issues.append({
                'type': 'Error',
                'severity': 'Critical',
                'description': f'Failed to analyze mesh: {str(e)}',
                'fix': 'Check file integrity'
            })
        
        return issues


class MeshSimplifier:
    """Simplify meshes using various algorithms."""
    
    @staticmethod
    def simplify_quadric(mesh_path: str, output_path: str, target_faces: int) -> Dict[str, Any]:
        """Simplify mesh using quadric edge collapse."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            original_faces = len(mesh.faces)
            
            if hasattr(mesh, 'simplify_quadric_decimation'):
                # Trimesh expects a percentage (0.0 - 1.0) of faces to keep
                percent = min(1.0, max(0.0, target_faces / original_faces))
                simplified = mesh.simplify_quadric_decimation(percent)
            else:
                return {'success': False, 'error': 'Simplification not supported'}
            
            simplified.export(output_path)
            
            return {
                'success': True,
                'original_faces': original_faces,
                'output_faces': len(simplified.faces),
                'reduction': ((original_faces - len(simplified.faces)) / original_faces) * 100,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def simplify_ratio(mesh_path: str, output_path: str, ratio: float) -> Dict[str, Any]:
        """Simplify mesh by reduction ratio."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            original_faces = len(mesh.faces)
            target_faces = int(original_faces * ratio)
            
            return MeshSimplifier.simplify_quadric(mesh_path, output_path, target_faces)
        except Exception as e:
            return {'success': False, 'error': str(e)}


class MeshSmoother:
    """Smooth mesh surfaces."""
    
    @staticmethod
    def laplacian_smooth(mesh_path: str, output_path: str, iterations: int = 5) -> Dict[str, Any]:
        """Apply Laplacian smoothing."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Apply Laplacian smoothing
            ms.apply_filter('apply_coord_laplacian_smoothing', stepsmoothnum=iterations)
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'iterations': iterations,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def taubin_smooth(mesh_path: str, output_path: str, lambda_param: float = 0.5, mu_param: float = -0.53, iterations: int = 10) -> Dict[str, Any]:
        """Apply Taubin smoothing (preserves volume better)."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Apply Taubin smoothing
            ms.apply_filter('apply_coord_taubin_smoothing', 
                          lambda_=lambda_param, 
                          mu=mu_param, 
                          stepsmoothnum=iterations)
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'iterations': iterations,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


class MeshRepairer:
    """Repair common mesh issues."""
    
    @staticmethod
    def fill_holes(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Fill holes in mesh."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Close holes
            ms.apply_filter('meshing_close_holes')
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def remove_duplicate_vertices(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Remove duplicate vertices."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            original_vertices = ms.current_mesh().vertex_number()
            
            # Remove duplicate vertices
            ms.apply_filter('meshing_remove_duplicate_vertices')
            
            final_vertices = ms.current_mesh().vertex_number()
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'removed': original_vertices - final_vertices,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def remove_degenerate_faces(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Remove degenerate faces."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            original_faces = len(mesh.faces)
            
            # Remove degenerate faces
            mesh.remove_degenerate_faces()
            
            mesh.export(output_path)
            
            return {
                'success': True,
                'removed': original_faces - len(mesh.faces),
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def fix_normals(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Fix face normals (orient consistently)."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            
            # Fix normals
            mesh.fix_normals()
            
            mesh.export(output_path)
            
            return {
                'success': True,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def auto_repair(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Automatically repair common mesh issues (Optimized)."""
        results = []
        
        if not (TRIMESH_AVAILABLE and PYMESHLAB_AVAILABLE):
            return {'success': False, 'error': 'Both Trimesh and PyMeshLab required'}
            
        try:
            # 1. Load with PyMeshLab (for duplicate vertices)
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Remove duplicate vertices
            original_verts = ms.current_mesh().vertex_number()
            ms.apply_filter('meshing_remove_duplicate_vertices')
            new_verts = ms.current_mesh().vertex_number()
            if original_verts != new_verts:
                results.append(f"Removed {original_verts - new_verts} duplicate vertices")
            
            # 2. Convert to Trimesh (for degenerate faces)
            # In-memory transfer: PyMeshLab -> Trimesh
            m = ms.current_mesh()
            # Note: vertex_matrix() returns numpy array of vertices
            # face_matrix() returns numpy array of faces
            mesh = trimesh.Trimesh(vertices=m.vertex_matrix(), faces=m.face_matrix())
            
            # Remove degenerate faces
            original_faces = len(mesh.faces)
            mesh.remove_degenerate_faces()
            if len(mesh.faces) != original_faces:
                results.append(f"Removed {original_faces - len(mesh.faces)} degenerate faces")
            
            # 3. Convert back to PyMeshLab (for filling holes)
            # In-memory transfer: Trimesh -> PyMeshLab
            ms = pymeshlab.MeshSet()
            m_pym = pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces)
            ms.add_mesh(m_pym)
            
            # Fill holes
            ms.apply_filter('meshing_close_holes')
            results.append("Filled holes")
            
            # Save final result
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'operations': results,
                'output_path': output_path
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    

class MeshRemesher:
    """Remesh operations."""
    
    @staticmethod
    def uniform_remesh(mesh_path: str, output_path: str, target_edge_length: float) -> Dict[str, Any]:
        """Create uniform remesh."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Isotropic remeshing
            ms.apply_filter('meshing_isotropic_explicit_remeshing', 
                          targetlen=pymeshlab.AbsoluteValue(target_edge_length))
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def quad_remesh(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Convert to quad mesh."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Turn into quad mesh
            ms.apply_filter('meshing_poly_to_tri')
            ms.apply_filter('meshing_tri_to_quad')
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


class MeshTransformer:
    """Transform mesh geometry."""
    
    @staticmethod
    def translate(mesh_path: str, output_path: str, translation: List[float]) -> Dict[str, Any]:
        """Translate mesh by [x, y, z] vector."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            mesh.vertices += np.array(translation, dtype=float)
            mesh.export(output_path)
            
            return {
                'success': True,
                'translation': translation,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def scale(mesh_path: str, output_path: str, scale_factor: float) -> Dict[str, Any]:
        """Scale mesh uniformly."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            mesh.apply_scale(scale_factor)
            mesh.export(output_path)
            
            return {
                'success': True,
                'scale_factor': scale_factor,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def center(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Center mesh at origin."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            centroid = mesh.centroid
            mesh.vertices -= centroid
            mesh.export(output_path)
            
            return {
                'success': True,
                'original_center': tuple(centroid),
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def rotate(mesh_path: str, output_path: str, rotation: List[float]) -> Dict[str, Any]:
        """Rotate mesh using Euler angles (degrees)."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            
            # Create rotation matrix from Euler angles
            # rotation is [x, y, z] in degrees
            matrix = trimesh.transformations.compose_matrix(
                angles=np.radians(rotation),
                translate=None,
                scale=None
            )
            
            mesh.apply_transform(matrix)
            mesh.export(output_path)
            
            return {
                'success': True,
                'rotation': rotation,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def auto_align(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Auto-align mesh using PCA (Principal Component Analysis)."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            
            # 1. Center the mesh
            mesh.vertices -= mesh.centroid
            
            # 2. Compute Principal Components (Eigenvectors of covariance matrix)
            # Trimesh has a built-in method for this, but let's do it explicitly for control
            # or use mesh.principal_inertia_vectors
            
            # Get vertices
            points = mesh.vertices
            
            # Compute covariance matrix
            covariance = np.cov(points.T)
            
            # Compute eigenvectors
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            
            # Sort eigenvectors by eigenvalues (largest to smallest)
            # The last one is the largest in eigh
            idx = eigenvalues.argsort()[::-1]
            eigenvectors = eigenvectors[:, idx]
            
            # Create rotation matrix to align eigenvectors to world axes
            # World axes: X=[1,0,0], Y=[0,1,0], Z=[0,0,1]
            # We want the largest variation (PC1) to be along X, PC2 along Y, etc.
            
            # The rotation matrix R should satisfy: R * eigenvectors = Identity
            # So R = eigenvectors.T
            
            rotation_matrix = np.eye(4)
            rotation_matrix[:3, :3] = eigenvectors.T
            
            # Apply transform
            mesh.apply_transform(rotation_matrix)
            
            # Re-center just in case
            mesh.vertices -= mesh.centroid
            
            mesh.export(output_path)
            
            return {
                'success': True,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def normalize_scale(mesh_path: str, output_path: str, target_size: float = 1.0) -> Dict[str, Any]:
        """Normalize mesh to fit in unit cube."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            mesh = trimesh.load(mesh_path)
            
            # Get bounding box
            bounds = mesh.bounds
            size = bounds[1] - bounds[0]
            max_dim = max(size)
            
            # Scale to target size
            scale_factor = target_size / max_dim
            mesh.apply_scale(scale_factor)
            
            mesh.export(output_path)
            
            return {
                'success': True,
                'scale_factor': scale_factor,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


class MeshProcessor(QObject):
    """Main mesh processor coordinating all mesh operations."""
    
    processing_progress = pyqtSignal(int, str)
    processing_complete = pyqtSignal(bool, dict)
    
    def __init__(self):
        super().__init__()
        self.analyzer = MeshAnalyzer()
        self.simplifier = MeshSimplifier()
        self.smoother = MeshSmoother()
        self.repairer = MeshRepairer()
        self.remesher = MeshRemesher()
        self.transformer = MeshTransformer()
    
    def analyze(self, mesh_path: str) -> Optional[MeshStatistics]:
        """Analyze mesh and return statistics."""
        return self.analyzer.analyze_mesh(mesh_path)

    def load_mesh(self, mesh_path: str) -> Optional[Any]:
        """Load a mesh file and return the mesh object."""
        if not TRIMESH_AVAILABLE:
            return None
        try:
            mesh = trimesh.load(mesh_path)
            
            # Handle Scene objects (GLB/GLTF)
            if isinstance(mesh, trimesh.Scene):
                if len(mesh.geometry) == 0:
                    raise ValueError("Scene is empty")
                # Concatenate all geometries
                geometries = list(mesh.geometry.values())
                if len(geometries) == 1:
                    mesh = geometries[0]
                else:
                    mesh = trimesh.util.concatenate(geometries)
            
            return mesh
        except Exception as e:
            print(f"Error loading mesh: {e}")
            return None
    
    def detect_issues(self, mesh_path: str) -> List[Dict[str, str]]:
        """Detect mesh issues."""
        return self.analyzer.detect_issues(mesh_path)
    
    def simplify(self, mesh_path: str, output_path: str, method: str = 'ratio', **kwargs) -> Dict[str, Any]:
        """Simplify mesh."""
        if method == 'ratio':
            ratio = kwargs.get('ratio', 0.5)
            return self.simplifier.simplify_ratio(mesh_path, output_path, ratio)
        elif method == 'faces':
            target_faces = kwargs.get('target_faces', 1000)
            return self.simplifier.simplify_quadric(mesh_path, output_path, target_faces)
        else:
            return {'success': False, 'error': f'Unknown method: {method}'}
    
    def smooth(self, mesh_path: str, output_path: str, method: str = 'laplacian', **kwargs) -> Dict[str, Any]:
        """Smooth mesh."""
        if method == 'laplacian':
            iterations = kwargs.get('iterations', 5)
            return self.smoother.laplacian_smooth(mesh_path, output_path, iterations)
        elif method == 'taubin':
            iterations = kwargs.get('iterations', 10)
            return self.smoother.taubin_smooth(mesh_path, output_path, iterations=iterations)
        else:
            return {'success': False, 'error': f'Unknown method: {method}'}
    
    def repair(self, mesh_path: str, output_path: str, operation: str = 'auto') -> Dict[str, Any]:
        """Repair mesh."""
        if operation == 'auto':
            return self.repairer.auto_repair(mesh_path, output_path)
        elif operation == 'fill_holes':
            return self.repairer.fill_holes(mesh_path, output_path)
        elif operation == 'remove_duplicates':
            return self.repairer.remove_duplicate_vertices(mesh_path, output_path)
        elif operation == 'remove_degenerate':
            return self.repairer.remove_degenerate_faces(mesh_path, output_path)
        elif operation == 'fix_normals':
            return self.repairer.fix_normals(mesh_path, output_path)
        else:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
    
    def remesh(self, mesh_path: str, output_path: str, method: str = 'uniform', **kwargs) -> Dict[str, Any]:
        """Remesh."""
        if method == 'uniform':
            edge_length = kwargs.get('edge_length', 0.1)
            return self.remesher.uniform_remesh(mesh_path, output_path, edge_length)
        elif method == 'quad':
            return self.remesher.quad_remesh(mesh_path, output_path)
        else:
            return {'success': False, 'error': f'Unknown method: {method}'}
    
    def transform(self, mesh_path: str, output_path: str, operation: str = 'scale', **kwargs) -> Dict[str, Any]:
        """Transform mesh."""
        if operation == 'scale':
            scale_factor = kwargs.get('scale_factor', 1.0)
            return self.transformer.scale(mesh_path, output_path, scale_factor)
        elif operation == 'rotate':
            rotation = kwargs.get('rotation', [0, 0, 0])
            return self.transformer.rotate(mesh_path, output_path, rotation)
        elif operation == 'translate':
            translation = kwargs.get('translation', [0, 0, 0])
            return self.transformer.translate(mesh_path, output_path, translation)
        elif operation == 'center':
            return self.transformer.center(mesh_path, output_path)
        elif operation == 'normalize':
            target_size = kwargs.get('target_size', 1.0)
            return self.transformer.normalize_scale(mesh_path, output_path, target_size)
        elif operation == 'auto_align':
            return self.transformer.auto_align(mesh_path, output_path)
        else:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
