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
                        angle_threshold: float = 1.0, preserve_border: bool = False,
                        preserve_normal: bool = False,
                        preserve_topology: bool = False) -> Dict[str, Any]:
        """Collapse aggressively on flat regions, keeping faces that span sharp angles.

        The three `preserve_*` flags go to the same quadric filter this calls; they are here
        because the filter takes them and the Simplify node offers them, and a knob that was
        accepted and dropped on the way down is the thing a person cannot see.
        """
        return MeshSimplifier.simplify_quadric(
            mesh_path, output_path, target_faces,
            preserve_boundary=preserve_border, preserve_normal=preserve_normal,
            preserve_topology=preserve_topology,
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
    def _vector(value, what: str) -> np.ndarray:
        """One float or three, as a length-3 array. A wrong shape names what it got."""
        if value is None:
            raise ValueError(f'{what} is missing')
        try:
            if np.isscalar(value):
                return np.full(3, float(value))
            parts = [float(v) for v in value]
        except TypeError:
            raise ValueError(f'{what} must be a number or three numbers, got {value!r}')
        except (ValueError, IndexError):
            raise ValueError(f'{what} must be a number or three numbers, got {value!r}')
        if len(parts) == 1:
            return np.full(3, parts[0])
        if len(parts) != 3:
            raise ValueError(f'{what} needs 3 numbers, got {len(parts)}: {parts}')
        return np.array(parts, dtype=float)

    @staticmethod
    def scale(mesh_path: str, output_path: str, scale_factor: float,
              origin: List[float] = (0.0, 0.0, 0.0)) -> Dict[str, Any]:
        """Scale a mesh by one factor or one per axis, about a point that stays put.

        `scale_factor` takes a number (uniform) or three numbers (per axis) - trimesh
        broadcasts a length-3 array over the vertices, which is what measured the extents
        of a unit box to [2, 1, 3] from [2, 2, 2]. `origin` is the anchor: without it the
        scale also moves the model, which is the usual way a pipeline loses its place.
        """
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}

        try:
            factors = MeshTransformer._vector(scale_factor, 'scale factor')
            anchor = MeshTransformer._vector(origin, 'scale origin')
            mesh = trimesh.load(mesh_path)
            before = [float(x) for x in mesh.extents]
            mesh.vertices = (np.asarray(mesh.vertices, dtype=float) - anchor) * factors + anchor
            mesh.export(output_path)

            return {
                'success': True,
                'scale_factor': scale_factor,
                'applied_factors': [float(x) for x in factors],
                'origin': [float(x) for x in anchor],
                'extents_before': before,
                'extents_after': [float(x) for x in mesh.extents],
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def center(mesh_path: str, output_path: str, mode: str = 'mass',
               axes: List[bool] = (True, True, True)) -> Dict[str, Any]:
        """Move a chosen centre of the mesh onto the origin, on the axes asked for.

        The three modes are three different points and all three are what a modeller means
        by "centre": `mass` is the surface centroid (what this method used to do), `bounds`
        is the middle of the bounding box, and `vertices` is the mean of the vertex
        positions - a scanned model with one dense patch and a sparse one puts those three
        in different places.
        """
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}

        modes = ('mass', 'bounds', 'vertices')
        if mode not in modes:
            return {'success': False,
                    'error': f'Unknown centering mode: {mode}. Supported: {", ".join(modes)}'}
        try:
            wanted = MeshTransformer._vector(
                [1.0 if (flag is True or (isinstance(flag, str) and flag.lower() in ('1', 'true')))
                 else 0.0 for flag in axes], 'center axes')
        except (TypeError, ValueError):
            return {'success': False, 'error': f'center axes must be three flags, got {axes!r}'}

        try:
            mesh = trimesh.load(mesh_path)
            if mode == 'mass':
                centre = np.asarray(mesh.centroid, dtype=float)
            elif mode == 'bounds':
                bounds = np.asarray(mesh.bounds, dtype=float)
                centre = (bounds[0] + bounds[1]) / 2.0
            else:
                centre = np.asarray(mesh.vertices, dtype=float).mean(axis=0)

            shift = centre * wanted
            mesh.vertices -= shift
            mesh.export(output_path)

            return {
                'success': True,
                'mode': mode,
                'axes': [bool(x) for x in wanted],
                'original_center': tuple(centre),
                'moved': [float(x) for x in shift],
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def rotate(mesh_path: str, output_path: str, rotation: List[float],
               origin: List[float] = (0.0, 0.0, 0.0)) -> Dict[str, Any]:
        """Rotate mesh using Euler angles (degrees) about a point.

        `origin` is the pivot. Without it a 90-degree turn moves a model that was standing
        at x=5 over to z=-5, which is why a pipeline's "rotate" step used to need a "center"
        step bolted in front of it.
        """
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        
        try:
            angles = MeshTransformer._vector(rotation, 'rotation')
            pivot = MeshTransformer._vector(origin, 'rotation origin')
            mesh = trimesh.load(mesh_path)
            centre_before = [float(x) for x in mesh.centroid]
            
            # Create rotation matrix from Euler angles
            # rotation is [x, y, z] in degrees
            matrix = trimesh.transformations.compose_matrix(
                angles=np.radians(angles),
                translate=None,
                scale=None
            )
            
            mesh.apply_translation(-pivot)
            mesh.apply_transform(matrix)
            mesh.apply_translation(pivot)
            mesh.export(output_path)
            
            return {
                'success': True,
                'rotation': [float(x) for x in angles],
                'origin': [float(x) for x in pivot],
                'centroid_before': centre_before,
                'centroid_after': [float(x) for x in mesh.centroid],
                'extents_after': [float(x) for x in mesh.extents],
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def align_to_plane(mesh_path: str, output_path: str, axis: str = 'z',
                       face: str = 'min', offset: float = 0.0) -> Dict[str, Any]:
        """Sit the chosen side of the model on a plane at `offset` along `axis`.

        This is the step that puts an asset on the ground of a scene, or its back against a
        wall, without guessing which axis a given exporter calls up.
        """
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}

        axes = {'x': 0, 'y': 1, 'z': 2}
        faces = ('min', 'max', 'center')
        key = str(axis).lower()
        chosen = str(face).lower()
        if key not in axes:
            return {'success': False,
                    'error': f'Unknown align axis: {axis}. Supported: {", ".join(sorted(axes))}'}
        if chosen not in faces:
            return {'success': False,
                    'error': f'Unknown align face: {face}. Supported: {", ".join(faces)}'}
        try:
            shift = float(offset)
        except (TypeError, ValueError):
            return {'success': False, 'error': f'align offset must be a number, got {offset!r}'}

        try:
            mesh = trimesh.load(mesh_path)
            bounds = np.asarray(mesh.bounds, dtype=float)
            index = axes[key]
            if chosen == 'min':
                current = bounds[0][index]
            elif chosen == 'max':
                current = bounds[1][index]
            else:
                current = (bounds[0][index] + bounds[1][index]) / 2.0

            move = np.zeros(3)
            move[index] = shift - current
            mesh.vertices += move
            mesh.export(output_path)

            after = np.asarray(mesh.bounds, dtype=float)
            return {
                'success': True,
                'axis': key,
                'face': chosen,
                'offset': shift,
                'moved': [float(x) for x in move],
                'bound_after': float(after[1 if chosen == 'max' else 0][index]),
                'extents_after': [float(x) for x in mesh.extents],
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def mirror(mesh_path: str, output_path: str, axis: str = 'x', weld: bool = False,
               weld_threshold: float = 0.001) -> Dict[str, Any]:
        """Add the mirrored half of the model, optionally welding the seam it creates.

        The mirrored copy has its face order flipped as well as its positions negated;
        without that the half that was pointing outward points inward and every game engine
        in the world culls it. `weld` goes through the one welder this app has
        (`MeshRepairer.remove_duplicate_vertices`), whose threshold is a fraction of the
        bounding diagonal, so 0.001 means "vertices within a tenth of a percent of the
        model's size are the same vertex".
        """
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}

        axes = {'x': 0, 'y': 1, 'z': 2}
        key = str(axis).lower()
        if key not in axes:
            return {'success': False,
                    'error': f'Unknown mirror axis: {axis}. Supported: {", ".join(sorted(axes))}'}

        try:
            mesh = trimesh.load(mesh_path)
            before_faces = int(len(mesh.faces))
            flipped = mesh.copy()
            sign = np.ones(3)
            sign[axes[key]] = -1.0
            flipped.vertices = np.asarray(flipped.vertices, dtype=float) * sign
            # negating one axis reverses the winding of every triangle; reversing the index
            # order puts it back, and the volume sign below is how that is checked.
            flipped.faces = np.asarray(flipped.faces)[:, ::-1]
            joined = trimesh.util.concatenate([mesh, flipped])
            joined.export(output_path)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        verdict = {
            'success': True,
            'axis': key,
            'welded': bool(weld),
            'faces_before': before_faces,
            'faces_after': int(len(joined.faces)),
            'watertight': bool(joined.is_watertight),
            'winding_consistent': bool(joined.is_winding_consistent),
            'volume': float(joined.volume),
            'output_path': output_path,
        }
        if not weld:
            return verdict

        welded = MeshRepairer.remove_duplicate_vertices(output_path, output_path,
                                                       threshold=weld_threshold)
        if not welded.get('success'):
            verdict['success'] = False
            verdict['error'] = ('the mirrored halves were written but the seam did not weld: '
                                + str(welded.get('error')))
            return verdict
        try:
            check = trimesh.load(output_path)
            verdict.update({'faces_after': int(len(check.faces)),
                            'vertices_after': int(len(check.vertices)),
                            'watertight': bool(check.is_watertight),
                            'volume': float(check.volume),
                            'welded_vertices': welded.get('removed')})
        except Exception as e:
            verdict['success'] = False
            verdict['error'] = f'the welded file could not be read back: {e}'
        return verdict


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


class MeshUV:
    """The two texture-coordinate parametrizations this build can actually run.

    Measured on pymeshlab 2025.7 with `tools/probe_backend_safety.py` and a per-parameter
    probe, not read out of the MeshLab menus:

    * `compute_texcoord_parametrization_triangle_trivial_per_wedge` takes `textdim`,
      `border` and `method` (whose only values are 'Basic' and 'Space-optimizing' - the
      binding answers "Enum 'Wrap' not found. Possible values are 'Basic';
      'Space-optimizing';"). `textdim` and `border` are not cosmetic: on a 2x3x4 box the UV
      extent goes 0.9961 -> 0.8750 when `border` goes 2 -> 64 at textdim 512, and the
      filter raises "Texture Dimension has an incorrect value" for 0 and
      "Inter-Triangle border has an incorrect value" for a negative border.
    * `compute_texcoord_parametrization_flat_plane_per_wedge` takes neither - it answers
      "Parameter textdim not found" - so the size knobs are reported as not applied.
    * `generate_voronoi_atlas_parametrization` runs and writes **no** texture coordinates
      (0 wedge rows), so it is not offered as a method.
    * `compute_texcoord_parametrization_harmonic` refuses a closed mesh with "can be
      applied only on meshes that have a boundary", so it is not offered either.
    * `meshing_tex_remove` and `compute_texcoord_parametrization_simple_symmetric_per_wedge`
      do not exist in this build; removal goes through trimesh, which writes 0 `vt` lines
      for a box that had 36.
    """

    METHODS = ('trivial', 'flat_plane')
    LAYOUTS = ('Basic', 'Space-optimizing')
    # Named here so a caller that was offered one of them by an older build gets this
    # sentence rather than a silent fallback.
    NOT_AVAILABLE = {
        'smart': 'no smart-project unwrap exists in pymeshlab 2025.7; the two parametrizers '
                 'here are trivial and flat_plane',
        'cube': 'the only box-style parametrizer, generate_voronoi_atlas_parametrization, '
                'runs but writes 0 texture coordinates in this build',
        'sphere': 'compute_texcoord_parametrization_harmonic is the closest thing to a '
                  'spherical unwrap and it refuses any mesh without a boundary',
        'cylinder': 'no cylindrical parametrizer exists in pymeshlab 2025.7',
        'voronoi': 'generate_voronoi_atlas_parametrization runs but writes 0 texture '
                   'coordinates in this build',
        'harmonic': 'compute_texcoord_parametrization_harmonic refuses a closed mesh ("can '
                    'be applied only on meshes that have a boundary")',
    }

    @staticmethod
    def read_unprocessed(mesh_path: str):
        """The one mesh in a file, exactly as it is stored.

        A textured .obj written by PyMeshLab names a material sidecar, and this reader
        hands such a file back as a scene - so counting texture coordinates or painting
        over them has to reach inside it first, or the answer is about the wrapper.
        """
        mesh = trimesh.load(mesh_path, process=False)
        if isinstance(mesh, trimesh.Scene):
            meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                raise ValueError('File contains no triangle mesh')
            mesh = trimesh.util.concatenate(meshes)
        return mesh

    @staticmethod
    def uv_rows(mesh_path: str) -> Optional[int]:
        """Texture-coordinate rows in the file as an exporter would read it, or None."""
        if not TRIMESH_AVAILABLE:
            return None
        try:
            mesh = MeshUV.read_unprocessed(mesh_path)
        except Exception:
            return None
        coords = getattr(mesh.visual, 'uv', None)
        if coords is None:
            return 0
        try:
            return int(len(coords))
        except TypeError:
            return 0

    @staticmethod
    def strip(mesh_path: str, output_path: str) -> Dict[str, Any]:
        """Write the mesh back with its texture coordinates gone, and count what was lost."""
        if not TRIMESH_AVAILABLE:
            return {'success': False, 'error': 'Trimesh not available'}
        try:
            before = MeshUV.uv_rows(mesh_path)
            mesh = MeshUV.read_unprocessed(mesh_path)
            mesh.visual = trimesh.visual.TextureVisuals()
            mesh.export(output_path)
            after = MeshUV.uv_rows(output_path)
            if before is None or after is None:
                return {'success': False,
                        'error': 'the texture coordinates could not be counted on both '
                                 'sides of the write'}
            return {'success': True, 'uv_rows_before': before, 'uv_rows_after': after,
                    'output_path': output_path}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def parametrize(mesh_path: str, output_path: str, method: str = 'trivial',
                    texture_size: int = 2048, border_pixels: int = 2,
                    layout: str = 'Basic') -> Dict[str, Any]:
        """Generate texture coordinates with one of the two methods that produce them.

        Every MeshSet here is brand new. Reusing one across calls is what made the older
        parametrization code crash the process on a mesh that already had wedges.
        """
        if not PYMESHLAB_AVAILABLE:
            return {'success': False, 'error': 'PyMeshLab not available'}

        chosen = str(method).lower()
        if chosen not in MeshUV.METHODS:
            hint = MeshUV.NOT_AVAILABLE.get(chosen)
            return {'success': False,
                    'error': f'Unknown UV method: {method}. Supported here: '
                             f'{", ".join(MeshUV.METHODS)}.'
                             + (f' {chosen} is not offered because {hint}.' if hint else '')}

        try:
            size = int(texture_size)
            border = int(border_pixels)
        except (TypeError, ValueError):
            return {'success': False,
                    'error': f'texture size and border must be whole numbers, got '
                             f'{texture_size!r} and {border_pixels!r}'}
        if chosen == 'trivial':
            # pymeshlab segfaults on nothing here, it raises - but only after it has done
            # the work, so the bounds are checked first and said in the app's own words.
            if size < 1:
                return {'success': False,
                        'error': f'texture size must be 1 or more; {size} is refused by the '
                                 f'filter as "Texture Dimension has an incorrect value"'}
            if border < 0:
                return {'success': False,
                        'error': f'border pixels cannot be negative ({border})'}
            wanted_layout = str(layout)
            if wanted_layout not in MeshUV.LAYOUTS:
                return {'success': False,
                        'error': f'Unknown UV layout: {layout}. The filter takes exactly: '
                                 f'{", ".join(MeshUV.LAYOUTS)}'}
        else:
            wanted_layout = str(layout)
            if wanted_layout not in MeshUV.LAYOUTS:
                wanted_layout = 'Basic'

        try:
            before = MeshUV.uv_rows(mesh_path)
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(mesh_path)
            faces = ms.current_mesh().face_number()
            ignored = []
            if chosen == 'trivial':
                ms.apply_filter(
                    'compute_texcoord_parametrization_triangle_trivial_per_wedge',
                    textdim=size, border=border, method=wanted_layout)
            else:
                ms.apply_filter('compute_texcoord_parametrization_flat_plane_per_wedge')
                ignored = ['texture_size', 'border_pixels']
            ms.save_current_mesh(output_path)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        after = MeshUV.uv_rows(output_path)
        verdict = {
            'success': True,
            'method': chosen,
            'layout': wanted_layout if chosen == 'trivial' else None,
            'faces': int(faces),
            'uv_rows_before': before,
            'uv_rows_written': after,
            'knobs_not_applied': ignored,
            'output_path': output_path,
        }
        if not after:
            verdict['success'] = False
            verdict['error'] = (f'{chosen} ran and the file it wrote has no texture '
                                f'coordinates in it')
        return verdict


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
            origin = kwargs.get('origin', (0.0, 0.0, 0.0))
            return self.transformer.scale(mesh_path, output_path, scale_factor, origin)
        elif operation == 'rotate':
            rotation = kwargs.get('rotation', [0, 0, 0])
            origin = kwargs.get('origin', (0.0, 0.0, 0.0))
            return self.transformer.rotate(mesh_path, output_path, rotation, origin)
        elif operation == 'translate':
            translation = kwargs.get('translation', [0, 0, 0])
            return self.transformer.translate(mesh_path, output_path, translation)
        elif operation == 'center':
            return self.transformer.center(mesh_path, output_path,
                                          mode=kwargs.get('mode', 'mass'),
                                          axes=kwargs.get('axes', (True, True, True)))
        elif operation == 'align':
            return self.transformer.align_to_plane(
                mesh_path, output_path,
                axis=kwargs.get('axis', 'z'),
                face=kwargs.get('face', 'min'),
                offset=kwargs.get('offset', 0.0))
        elif operation == 'mirror':
            return self.transformer.mirror(
                mesh_path, output_path,
                axis=kwargs.get('axis', 'x'),
                weld=bool(kwargs.get('weld', False)),
                weld_threshold=float(kwargs.get('weld_threshold', 0.001)))
        elif operation == 'normalize':
            target_size = kwargs.get('target_size', 1.0)
            return self.transformer.normalize_scale(mesh_path, output_path, target_size)
        elif operation == 'auto_align':
            return self.transformer.auto_align(mesh_path, output_path)
        else:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
