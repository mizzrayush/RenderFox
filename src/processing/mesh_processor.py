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


class MeshMeasure:
    """Geometric and topological measurements that the summary statistics omit."""

    @staticmethod
    def load_single_mesh(mesh_path: str):
        """Load a file and flatten any scene into one triangle mesh."""
        if not TRIMESH_AVAILABLE:
            raise RuntimeError('Trimesh not available')
        data = trimesh.load(mesh_path)
        if isinstance(data, trimesh.Scene):
            geometries = [g for g in data.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not geometries:
                raise ValueError('File contains no triangle mesh')
            data = trimesh.util.concatenate(geometries)
        return data

    @staticmethod
    def boundary_loops(mesh: Any) -> List[List[int]]:
        """Return each open edge loop as the vertices bounding a hole.

        A boundary edge belongs to exactly one face, so the loops are the mesh's
        holes. Isolated vertices are excluded because they bound nothing.
        """
        import trimesh.graph as tg
        from trimesh.grouping import group_rows

        if not len(mesh.edges_sorted):
            return []
        boundary = mesh.edges_sorted[group_rows(mesh.edges_sorted, require_count=1)]
        if not len(boundary):
            return []

        nodes = np.unique(boundary)
        index = {int(node): position for position, node in enumerate(nodes)}
        relabelled = np.array([[index[int(a)], index[int(b)]] for a, b in boundary])
        labels = tg.connected_component_labels(edges=relabelled, node_count=len(nodes))
        return [
            [int(nodes[position]) for position in np.where(labels == label)[0]]
            for label in sorted(set(labels.tolist()))
        ]

    @staticmethod
    def measurements(mesh_path: str) -> Dict[str, Any]:
        """Volume, area, extents, topology and hole counts for a mesh."""
        try:
            mesh = MeshMeasure.load_single_mesh(mesh_path)
            loops = MeshMeasure.boundary_loops(mesh)
            bounds = mesh.bounds
            return {
                'success': True,
                'vertices': int(len(mesh.vertices)),
                'faces': int(len(mesh.faces)),
                'edges': int(len(mesh.edges_unique)),
                'volume': float(mesh.volume),
                'surface_area': float(mesh.area),
                'extents': [float(x) for x in mesh.extents],
                'min_bound': [float(x) for x in bounds[0]],
                'max_bound': [float(x) for x in bounds[1]],
                'centroid': [float(x) for x in mesh.centroid],
                'euler_number': int(mesh.euler_number),
                'body_count': int(mesh.body_count),
                'is_watertight': bool(mesh.is_watertight),
                'is_winding_consistent': bool(mesh.is_winding_consistent),
                'hole_count': len(loops),
                'hole_sizes': [len(loop) for loop in loops],
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def components(mesh_path: str) -> Dict[str, Any]:
        """Break the mesh into disconnected bodies and measure each one."""
        try:
            mesh = MeshMeasure.load_single_mesh(mesh_path)
            bodies = mesh.split(only_watertight=False)
            reports = []
            for i, body in enumerate(bodies):
                reports.append({
                    'index': i,
                    'faces': int(len(body.faces)),
                    'vertices': int(len(body.vertices)),
                    'volume': float(body.volume),
                    'surface_area': float(body.area),
                    'watertight': bool(body.is_watertight),
                })
            return {'success': True, 'body_count': len(reports), 'components': reports}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def curvature(mesh_path: str) -> Dict[str, Any]:
        """Discrete mean and Gaussian curvature statistics per vertex."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            result = {'success': True}
            for label, kind in (('mean', 'Mean Curvature'), ('gaussian', 'Gaussian Curvature')):
                ms.apply_filter('compute_scalar_by_discrete_curvature_per_vertex',
                                curvaturetype=kind)
                stats = ms.get_scalar_statistics_per_vertex()
                result[label] = {key: float(value) for key, value in stats.items()}
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def face_quality(mesh_path: str, bins: int = 10) -> Dict[str, Any]:
        """Distribution of the inradius/circumradius triangle quality metric.

        PyMeshLab normalises this metric so 1.0 is a perfect equilateral triangle
        and 0.0 is a collapsed one, which makes the low end of the distribution
        exactly where rendering artefacts come from.
        """
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            ms.apply_filter('compute_scalar_by_aspect_ratio_per_face',
                            metric='inradius/circumradius')
            values = np.asarray(ms.current_mesh().face_scalar_array(), dtype=float)
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                return {'success': False, 'error': 'Mesh has no measurable faces'}
            counts, edges = np.histogram(finite, bins=max(2, int(bins)), range=(0.0, 1.0))
            stats = ms.get_scalar_statistics_per_face()
            return {
                'success': True,
                'statistics': {key: float(value) for key, value in stats.items()},
                'counts': [int(c) for c in counts],
                'edges': [float(e) for e in edges],
                'good_faces': int(np.count_nonzero(finite >= 0.5)),
                'poor_faces': int(np.count_nonzero(finite < 0.2)),
                'total_faces': int(finite.size),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


class MeshSimplifier:
    """Simplify meshes using various algorithms."""
    
    @staticmethod
    def simplify_quadric(mesh_path: str, output_path: str, target_faces: int,
                         preserve_boundary: bool = False, preserve_normal: bool = False,
                         preserve_topology: bool = False, planar: bool = False,
                         planar_weight: float = 0.001,
                         quality_threshold: float = 0.3) -> Dict[str, Any]:
        """Collapse edges down to target_faces using quadric error metrics."""
        try:
            original_faces = MeshSimplifier._face_count(mesh_path)
            if original_faces is None:
                return {'success': False, 'error': 'Could not read mesh faces'}
            target_faces = int(max(1, min(target_faces, original_faces)))
        except Exception as e:
            return {'success': False, 'error': str(e)}

        if PYMESHLAB_AVAILABLE:
            try:
                ms = pymeshlab.MeshSet()
                ms.load_new_mesh(mesh_path)
                ms.apply_filter(
                    'meshing_decimation_quadric_edge_collapse',
                    targetfacenum=target_faces,
                    preserveboundary=bool(preserve_boundary),
                    preservenormal=bool(preserve_normal),
                    preservetopology=bool(preserve_topology),
                    planarquadric=bool(planar),
                    planarweight=float(planar_weight),
                    qualitythr=min(1.0, max(0.0, float(quality_threshold))),
                    autoclean=True,
                    optimalplacement=True,
                )
                ms.save_current_mesh(output_path)
                final_faces = ms.current_mesh().face_number()
                return MeshSimplifier._result(original_faces, final_faces, output_path)
            except Exception as e:
                return {'success': False, 'error': str(e)}

        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Neither PyMeshLab nor Trimesh available'}
        try:
            mesh = trimesh.load(mesh_path)
            if not hasattr(mesh, 'simplify_quadric_decimation'):
                return {'success': False, 'error': 'Simplification not supported'}
            # face_count is an absolute target, not a fraction.
            simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
            simplified.export(output_path)
            return MeshSimplifier._result(original_faces, len(simplified.faces), output_path)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def simplify_ratio(mesh_path: str, output_path: str, ratio: float) -> Dict[str, Any]:
        """Simplify mesh by reduction ratio (fraction of faces to keep)."""
        try:
            original_faces = MeshSimplifier._face_count(mesh_path)
            if original_faces is None:
                return {'success': False, 'error': 'Could not read mesh faces'}
            target_faces = max(1, int(original_faces * min(1.0, max(0.0, ratio))))
            return MeshSimplifier.simplify_quadric(mesh_path, output_path, target_faces)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def cluster_simplify(mesh_path: str, output_path: str, threshold: float) -> Dict[str, Any]:
        """Reduce face count by clustering vertices inside a grid of the given size."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            original_faces = ms.current_mesh().face_number()
            # The UI exposes a 0.001-1.0 fraction of the mesh diagonal; the filter
            # wants a percentage of the bounding-box diagonal.
            pct = max(0.01, min(100.0, float(threshold) * 100.0))
            ms.apply_filter('meshing_decimation_clustering',
                            threshold=pymeshlab.PercentageValue(pct))
            final_faces = ms.current_mesh().face_number()
            ms.save_current_mesh(output_path)
            return MeshSimplifier._result(original_faces, final_faces, output_path)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def planar_simplify(mesh_path: str, output_path: str, target_faces: int,
                        angle_threshold: float = 1.0) -> Dict[str, Any]:
        """Collapse aggressively on flat regions, keeping faces that span sharp angles."""
        return MeshSimplifier.simplify_quadric(
            mesh_path, output_path, target_faces,
            planar=True,
            planar_weight=MeshSimplifier._angle_to_planar_weight(angle_threshold),
        )

    @staticmethod
    def _angle_to_planar_weight(angle_deg: float) -> float:
        """Map an angle tolerance in degrees onto PyMeshLab's planarweight penalty.

        planarweight scales the dihedral-angle penalty when deciding whether two
        faces count as coplanar, so a wider accepted angle must produce a smaller
        weight. Clamped to the range the filter documents as usable.
        """
        angle_deg = max(0.1, float(angle_deg))
        return max(1e-6, min(1.0, 0.001 * (1.0 / angle_deg)))

    @staticmethod
    def _face_count(mesh_path: str):
        if PYMESHLAB_AVAILABLE:
            try:
                ms = pymeshlab.MeshSet()
                ms.load_new_mesh(mesh_path)
                return ms.current_mesh().face_number()
            except Exception:
                pass
        if TRIMESH_AVAILABLE:
            try:
                return len(trimesh.load(mesh_path).faces)
            except Exception:
                return None
        return None

    @staticmethod
    def _result(original_faces: int, final_faces: int, output_path: str) -> Dict[str, Any]:
        reduction = ((original_faces - final_faces) / original_faces) * 100 if original_faces else 0.0
        return {
            'success': True,
            'original_faces': original_faces,
            'output_faces': final_faces,
            'reduction': reduction,
            'output_path': output_path,
        }



class MeshSmoother:
    """Smooth mesh surfaces."""
    
    @staticmethod
    def laplacian_smooth(mesh_path: str, output_path: str, iterations: int = 5,
                         boundary: bool = True) -> Dict[str, Any]:
        """Apply Laplacian smoothing."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            # Apply Laplacian smoothing
            ms.apply_filter('apply_coord_laplacian_smoothing',
                            stepsmoothnum=max(1, int(iterations)),
                            boundary=bool(boundary))
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'iterations': iterations,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def depth_smooth(mesh_path: str, output_path: str, iterations: int = 3,
                     delta: float = 100.0) -> Dict[str, Any]:
        """Apply depth smoothing, which relaxes detail along the view depth axis."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            # stepsmoothnum is the iteration count; delta is a percentage of the
            # mesh diagonal controlling how far a vertex may move.
            ms.apply_filter('apply_coord_depth_smoothing',
                            stepsmoothnum=max(1, int(iterations)),
                            delta=pymeshlab.PercentageValue(max(1.0, min(100.0, float(delta)))))

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
    def fill_holes(mesh_path: str, output_path: str, max_hole_size: int = None) -> Dict[str, Any]:
        """Fill boundary holes, optionally capped to a maximum hole perimeter."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            before = ms.current_mesh().face_number()
            # maxholesize is the largest boundary (in edge count) the filter will cap.
            # Written as two literal calls so the filter schema test can read both.
            if max_hole_size is None:
                ms.apply_filter('meshing_close_holes')
            else:
                ms.apply_filter('meshing_close_holes',
                                maxholesize=int(max(3, min(1000, int(max_hole_size)))))
            after = ms.current_mesh().face_number()
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'filled_faces': max(0, after - before),
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def remove_duplicate_vertices(mesh_path: str, output_path: str, threshold: float = None) -> Dict[str, Any]:
        """Weld coincident vertices; a threshold welds everything within that fraction of the diagonal."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            
            original_vertices = ms.current_mesh().vertex_number()
            
            if threshold is not None:
                # meshing_remove_duplicate_vertices only welds exactly-equal vertices.
                # Anything with a tolerance is a merge-close-vertices operation.
                ms.apply_filter('meshing_merge_close_vertices',
                                threshold=pymeshlab.PercentageValue(
                                    max(0.0001, min(100.0, float(threshold) * 100.0))))
            else:
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
        """Drop zero-area and folded faces."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            original_faces = ms.current_mesh().face_number()
            ms.apply_filter('meshing_remove_null_faces')
            ms.apply_filter('meshing_remove_folded_faces')
            ms.apply_filter('meshing_remove_duplicate_faces')
            final_faces = ms.current_mesh().face_number()

            ms.save_current_mesh(output_path)

            return {
                'success': True,
                'removed': original_faces - final_faces,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def remove_unreferenced_vertices(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Delete vertices no face points at."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            original_vertices = ms.current_mesh().vertex_number()
            ms.apply_filter('meshing_remove_unreferenced_vertices')
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
    def repair_non_manifold_edges(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Remove or collapse edges shared by more than two faces."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            original_faces = ms.current_mesh().face_number()
            ms.apply_filter('meshing_repair_non_manifold_edges', method='Remove Faces')
            final_faces = ms.current_mesh().face_number()

            ms.save_current_mesh(output_path)

            return {
                'success': True,
                'removed': original_faces - final_faces,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def repair_non_manifold_vertices(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Split vertices whose fans are not manifold."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            original_vertices = ms.current_mesh().vertex_number()
            ms.apply_filter('meshing_repair_non_manifold_vertices', vertdispratio=0.1)
            final_vertices = ms.current_mesh().vertex_number()

            ms.save_current_mesh(output_path)

            return {
                'success': True,
                'added': final_vertices - original_vertices,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def make_manifold(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Repair non-manifold edges and vertices, then drop what is left over."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            original = ms.current_mesh().face_number()
            ms.apply_filter('meshing_repair_non_manifold_edges', method='Remove Faces')
            ms.apply_filter('meshing_repair_non_manifold_vertices', vertdispratio=0.1)
            ms.apply_filter('meshing_remove_duplicate_vertices')
            ms.apply_filter('meshing_remove_unreferenced_vertices')
            final = ms.current_mesh().face_number()

            ms.save_current_mesh(output_path)

            return {
                'success': True,
                'original_faces': original,
                'output_faces': final,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def invert_normals(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Flip every face orientation."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            ms.apply_filter('meshing_invert_face_orientation', forceflip=True, onlyselected=False)

            ms.save_current_mesh(output_path)

            return {'success': True, 'output_path': output_path}
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
        """Run the standard repair sequence in one pass, staying inside PyMeshLab.

        The previous version ping-ponged PyMeshLab -> trimesh -> PyMeshLab, which
        silently discarded UVs, vertex colours and normals on the round trip.
        """
        results = []

        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            def log_removal(label, before, after, unit):
                """Record how many elements the filter that just ran removed."""
                removed = before - after
                if removed:
                    results.append(f"{label} {removed} {unit}")
                return after

            v = ms.current_mesh().vertex_number()
            ms.apply_filter('meshing_remove_duplicate_vertices')
            v = log_removal('Welded duplicate vertices', v,
                            ms.current_mesh().vertex_number(), 'vertices')

            f = ms.current_mesh().face_number()
            ms.apply_filter('meshing_remove_null_faces')
            f = log_removal('Removed null faces', f, ms.current_mesh().face_number(), 'faces')
            ms.apply_filter('meshing_remove_folded_faces')
            f = log_removal('Removed folded faces', f, ms.current_mesh().face_number(), 'faces')
            ms.apply_filter('meshing_remove_duplicate_faces')
            f = log_removal('Removed duplicate faces', f, ms.current_mesh().face_number(), 'faces')

            ms.apply_filter('meshing_re_orient_faces_coherently')
            results.append("Re-oriented faces coherently")

            # Closing holes adds faces rather than removing them, so it is counted up.
            before = f
            ms.apply_filter('meshing_close_holes')
            f = ms.current_mesh().face_number()
            if f - before:
                results.append(f"Closed holes with {f - before} new faces")

            ms.apply_filter('meshing_remove_unreferenced_vertices')

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
    def uniform_remesh(mesh_path: str, output_path: str, target_edge_length: float,
                       iterations: int = 10, adaptive: bool = False) -> Dict[str, Any]:
        """Rebuild the surface with near-equal length edges."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            before = ms.current_mesh().face_number()
            
            # targetlen is a PercentageValue of the mesh bounding-box diagonal.
            # The UI slider is a fraction of that diagonal, hence the *100.
            pct = max(0.01, min(100.0, float(target_edge_length) * 100.0))
            ms.apply_filter(
                'meshing_isotropic_explicit_remeshing',
                targetlen=pymeshlab.PercentageValue(pct),
                iterations=max(1, int(iterations)),
                adaptive=bool(adaptive),
                featuredeg=30.0,
                splitflag=True,
                collapseflag=True,
                swapflag=True,
                smoothflag=True,
                reprojectflag=True,
            )
            after = ms.current_mesh().face_number()
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'original_faces': before,
                'output_faces': after,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def quad_remesh(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Pair triangles into quads."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}
        
        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            before = ms.current_mesh().face_number()
            
            ms.apply_filter('meshing_poly_to_tri')
            ms.apply_filter('meshing_tri_to_quad_by_smart_triangle_pairing')
            after = ms.current_mesh().face_number()
            
            ms.save_current_mesh(output_path)
            
            return {
                'success': True,
                'original_faces': before,
                'output_faces': after,
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def voronoi_filtering(mesh_path: str, output_path: str, threshold: float = 10.0) -> Dict[str, Any]:
        """Fair the mesh by Voronoi-based edge flipping."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)

            ms.apply_filter('generate_voronoi_filtering',
                            threshold=max(0.0, min(2000.0, float(threshold))))

            ms.save_current_mesh(output_path)

            return {
                'success': True,
                'output_faces': ms.current_mesh().face_number(),
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def subdivide(mesh_path: str, output_path: str, method: str = 'loop', levels: int = 1) -> Dict[str, Any]:
        """Refine the mesh by repeated subdivision."""
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        filters = {
            'loop': 'meshing_surface_subdivision_loop',
            'catmull-clark': 'meshing_surface_subdivision_catmull_clark',
            'catmull_clark': 'meshing_surface_subdivision_catmull_clark',
            'catmullclark': 'meshing_surface_subdivision_catmull_clark',
            'butterfly': 'meshing_surface_subdivision_butterfly',
            'midpoint': 'meshing_surface_subdivision_midpoint',
        }
        wanted = filters.get(str(method).lower())
        if wanted is None:
            return {'success': False,
                    'error': f"Unknown subdivision method: {method}. "
                             f"Supported: {', '.join(sorted(filters))}"}

        try:
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            before = ms.current_mesh().face_number()

            # Dispatched by alias so each apply_filter keeps a literal name;
            # a computed filter name cannot be checked against the installed schema.
            times = max(1, int(levels))
            if wanted == 'meshing_surface_subdivision_catmull_clark':
                ms.apply_filter('meshing_surface_subdivision_catmull_clark', iterations=times)
            elif wanted == 'meshing_surface_subdivision_butterfly':
                ms.apply_filter('meshing_surface_subdivision_butterfly', iterations=times)
            elif wanted == 'meshing_surface_subdivision_midpoint':
                ms.apply_filter('meshing_surface_subdivision_midpoint', iterations=times)
            else:
                ms.apply_filter('meshing_surface_subdivision_loop', iterations=times)
            after = ms.current_mesh().face_number()

            ms.save_current_mesh(output_path)

            return {
                'success': True,
                'original_faces': before,
                'output_faces': after,
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

    def export(self, mesh_path: str, output_path: str, include_normals: bool = True,
               include_textures: bool = True, include_colors: bool = True) -> Dict[str, Any]:
        """Write a mesh to output_path, converting format from the file extension.

        Normals are only selectable for OBJ: PLY, STL and OFF have no place to
        store per-vertex normals that a reader would not recompute anyway.
        """
        if not os.path.exists(mesh_path):
            return {'success': False, 'error': f'Source mesh not found: {mesh_path}'}
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}

        try:
            mesh = trimesh.load(mesh_path)
            if isinstance(mesh, trimesh.Scene):
                geometries = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
                if not geometries:
                    return {'success': False, 'error': 'File contains no triangle mesh'}
                mesh = trimesh.util.concatenate(geometries)

            if not (include_textures and include_colors):
                kept_colors = None
                if include_colors and mesh.visual.kind in ('vertex', 'face'):
                    kept_colors = np.array(mesh.visual.vertex_colors)
                mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh)
                if kept_colors is not None:
                    mesh.visual.vertex_colors = kept_colors

            kwargs = {}
            if os.path.splitext(output_path)[1].lower() == '.obj':
                kwargs['include_normals'] = bool(include_normals)
            mesh.export(output_path, **kwargs)
            return {'success': True, 'output_path': output_path}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def simplify(self, mesh_path: str, output_path: str, method: str = 'ratio', **kwargs) -> Dict[str, Any]:
        """Simplify mesh.

        method is one of: faces, ratio, clustering, planar.
        """
        if method == 'faces':
            return self.simplifier.simplify_quadric(
                mesh_path, output_path,
                target_faces=int(kwargs.get('target_faces', 1000)),
                preserve_boundary=bool(kwargs.get('preserve_boundary', False)),
                preserve_normal=bool(kwargs.get('preserve_normal', False)),
                preserve_topology=bool(kwargs.get('preserve_topology', False)),
                quality_threshold=float(kwargs.get('quality_threshold', 0.3)),
            )
        elif method == 'ratio':
            return self.simplifier.simplify_ratio(
                mesh_path, output_path, ratio=float(kwargs.get('ratio', 0.5)))
        elif method == 'clustering':
            return self.simplifier.cluster_simplify(
                mesh_path, output_path, threshold=float(kwargs.get('threshold', 0.01)))
        elif method == 'planar':
            return self.simplifier.planar_simplify(
                mesh_path, output_path,
                target_faces=int(kwargs.get('target_faces', 1000)),
                angle_threshold=float(kwargs.get('angle', 1.0)),
            )
        else:
            return {'success': False,
                    'error': f"Unknown method: {method} (expected faces, ratio, clustering or planar)"}
    
    def smooth(self, mesh_path: str, output_path: str, method: str = 'laplacian', **kwargs) -> Dict[str, Any]:
        """Smooth mesh.

        method is one of: laplacian, taubin, depth.
        """
        if method == 'laplacian':
            return self.smoother.laplacian_smooth(
                mesh_path, output_path,
                iterations=int(kwargs.get('iterations', 5)),
                boundary=bool(kwargs.get('boundary', True)),
            )
        elif method == 'taubin':
            return self.smoother.taubin_smooth(
                mesh_path, output_path,
                lambda_param=float(kwargs.get('lambda_param', 0.5)),
                mu_param=float(kwargs.get('mu_param', -0.53)),
                iterations=int(kwargs.get('iterations', 10)),
            )
        elif method == 'depth':
            return self.smoother.depth_smooth(
                mesh_path, output_path,
                iterations=int(kwargs.get('iterations', 3)),
                delta=float(kwargs.get('delta', 100.0)),
            )
        else:
            return {'success': False,
                    'error': f"Unknown method: {method} (expected laplacian, taubin or depth)"}
    
    def repair(self, mesh_path: str, output_path: str, operation: str = 'auto', **kwargs) -> Dict[str, Any]:
        """Repair mesh.

        operation is one of: auto, fill_holes, remove_duplicates, remove_degenerate,
        remove_unreferenced, fix_normals, invert_normals, repair_non_manifold_edges,
        repair_non_manifold_vertices, make_manifold.
        """
        if operation == 'auto':
            return self.repairer.auto_repair(mesh_path, output_path)
        elif operation == 'fill_holes':
            max_hole_size = kwargs.get('max_hole_size')
            return self.repairer.fill_holes(
                mesh_path, output_path,
                max_hole_size=None if max_hole_size is None else int(max_hole_size))
        elif operation == 'remove_duplicates':
            threshold = kwargs.get('threshold')
            return self.repairer.remove_duplicate_vertices(
                mesh_path, output_path,
                threshold=None if threshold is None else float(threshold))
        elif operation == 'remove_degenerate':
            return self.repairer.remove_degenerate_faces(mesh_path, output_path)
        elif operation == 'remove_unreferenced':
            return self.repairer.remove_unreferenced_vertices(mesh_path, output_path)
        elif operation == 'fix_normals':
            return self.repairer.fix_normals(mesh_path, output_path)
        elif operation == 'invert_normals':
            return self.repairer.invert_normals(mesh_path, output_path)
        elif operation == 'repair_non_manifold_edges':
            return self.repairer.repair_non_manifold_edges(mesh_path, output_path)
        elif operation == 'repair_non_manifold_vertices':
            return self.repairer.repair_non_manifold_vertices(mesh_path, output_path)
        elif operation == 'make_manifold':
            return self.repairer.make_manifold(mesh_path, output_path)
        else:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
    
    def remesh(self, mesh_path: str, output_path: str, method: str = 'uniform', **kwargs) -> Dict[str, Any]:
        """Remesh.

        method is one of: uniform, quad, voronoi, subdivision.
        """
        if method == 'uniform':
            return self.remesher.uniform_remesh(
                mesh_path, output_path,
                target_edge_length=float(kwargs.get('edge_length', 0.1)),
                iterations=int(kwargs.get('iterations', 10)),
                adaptive=bool(kwargs.get('adaptive', False)),
            )
        elif method == 'quad':
            return self.remesher.quad_remesh(mesh_path, output_path)
        elif method == 'voronoi':
            return self.remesher.voronoi_filtering(
                mesh_path, output_path,
                threshold=float(kwargs.get('threshold', 10.0)),
            )
        elif method == 'subdivision':
            return self.remesher.subdivide(
                mesh_path, output_path,
                method=str(kwargs.get('sub_method', 'loop')),
                levels=int(kwargs.get('levels', 1)),
            )
        else:
            return {'success': False,
                    'error': f"Unknown method: {method} (expected uniform, quad, voronoi or subdivision)"}
    
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
