"""
RenderFox Point Cloud Processor
Provides point cloud loading, processing, filtering, and mesh reconstruction.
"""

import os
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import json

try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class PointCloudStatistics:
    """Container for point cloud statistics."""
    point_count: int
    has_colors: bool
    has_normals: bool
    bounding_box: Tuple[float, float, float]
    centroid: Tuple[float, float, float]
    density: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'point_count': self.point_count,
            'has_colors': self.has_colors,
            'has_normals': self.has_normals,
            'bounding_box': self.bounding_box,
            'centroid': self.centroid,
            'density': self.density
        }


class PointCloudLoader:
    """Load point cloud from various formats."""
    
    @staticmethod
    def load(file_path: str) -> Optional[Any]:
        """Load point cloud from file."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            pcd = o3d.io.read_point_cloud(file_path)
            return pcd
        except Exception as e:
            print(f"Error loading point cloud: {e}")
            return None
    
    @staticmethod
    def save(pcd: Any, output_path: str) -> bool:
        """Save point cloud to file."""
        if not OPEN3D_AVAILABLE:
            return False
        
        try:
            o3d.io.write_point_cloud(output_path, pcd)
            return True
        except Exception as e:
            print(f"Error saving point cloud: {e}")
            return False


class PointCloudAnalyzer:
    """Analyze point cloud properties."""
    
    @staticmethod
    def analyze(pcd: Any) -> Optional[PointCloudStatistics]:
        """Analyze point cloud and return statistics."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            points = np.asarray(pcd.points)
            point_count = len(points)
            
            has_colors = pcd.has_colors()
            has_normals = pcd.has_normals()
            
            # Bounding box
            bbox = pcd.get_axis_aligned_bounding_box()
            bbox_size = tuple(bbox.get_extent())
            
            # Centroid
            centroid = tuple(pcd.get_center())
            
            # Estimate density (points per cubic unit)
            volume = bbox_size[0] * bbox_size[1] * bbox_size[2]
            density = point_count / volume if volume > 0 else 0
            
            return PointCloudStatistics(
                point_count=point_count,
                has_colors=has_colors,
                has_normals=has_normals,
                bounding_box=bbox_size,
                centroid=centroid,
                density=density
            )
        except Exception as e:
            print(f"Error analyzing point cloud: {e}")
            return None

    @staticmethod
    def calculate_fitness(source: Any, target: Any, max_correspondence_distance: float) -> float:
        """Calculate fitness score (inlier ratio)."""
        if not OPEN3D_AVAILABLE:
            return 0.0
        try:
            # Evaluate registration
            evaluation = o3d.pipelines.registration.evaluate_registration(
                source, target, max_correspondence_distance)
            return evaluation.fitness
        except Exception as e:
            print(f"Error calculating fitness: {e}")
            return 0.0

    @staticmethod
    def calculate_rmse(source: Any, target: Any, max_correspondence_distance: float) -> float:
        """Calculate RMSE of inliers."""
        if not OPEN3D_AVAILABLE:
            return 0.0
        try:
            evaluation = o3d.pipelines.registration.evaluate_registration(
                source, target, max_correspondence_distance)
            return evaluation.inlier_rmse
        except Exception as e:
            print(f"Error calculating RMSE: {e}")
            return 0.0


class PointCloudFilter:
    """Filter and clean point clouds."""
    
    @staticmethod
    def voxel_downsample(pcd: Any, voxel_size: float = 0.05) -> Optional[Any]:
        """Downsample using voxel grid."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            downsampled = pcd.voxel_down_sample(voxel_size=voxel_size)
            return downsampled
        except Exception as e:
            print(f"Error downsampling: {e}")
            return None
    
    @staticmethod
    def statistical_outlier_removal(pcd: Any, nb_neighbors: int = 20, std_ratio: float = 2.0) -> Optional[Any]:
        """Remove statistical outliers."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            filtered, _ = pcd.remove_statistical_outlier(
                nb_neighbors=nb_neighbors,
                std_ratio=std_ratio
            )
            return filtered
        except Exception as e:
            print(f"Error removing outliers: {e}")
            return None
    
    @staticmethod
    def radius_outlier_removal(pcd: Any, nb_points: int = 16, radius: float = 0.05) -> Optional[Any]:
        """Remove radius-based outliers."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            filtered, _ = pcd.remove_radius_outlier(
                nb_points=nb_points,
                radius=radius
            )
            return filtered
        except Exception as e:
            print(f"Error removing outliers: {e}")
            return None
    
    @staticmethod
    def crop_box(pcd: Any, min_bound: Tuple[float, float, float], 
                 max_bound: Tuple[float, float, float]) -> Optional[Any]:
        """Crop point cloud to bounding box."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            bbox = o3d.geometry.AxisAlignedBoundingBox(
                min_bound=min_bound,
                max_bound=max_bound
            )
            cropped = pcd.crop(bbox)
            return cropped
        except Exception as e:
            print(f"Error cropping: {e}")
            return None

class PointCloudTransformer:
    """Apply geometric transformations."""
    
    @staticmethod
    def translate(pcd: Any, translation: Tuple[float, float, float]) -> Optional[Any]:
        """Translate point cloud."""
        if not OPEN3D_AVAILABLE:
            return None
        try:
            return pcd.translate(translation)
        except Exception as e:
            print(f"Error translating: {e}")
            return None

    @staticmethod
    def rotate(pcd: Any, rotation: Tuple[float, float, float]) -> Optional[Any]:
        """Rotate point cloud (Euler angles in degrees)."""
        if not OPEN3D_AVAILABLE:
            return None
        try:
            # Convert degrees to radians
            R = pcd.get_rotation_matrix_from_xyz(np.radians(rotation))
            return pcd.rotate(R, center=(0, 0, 0))
        except Exception as e:
            print(f"Error rotating: {e}")
            return None

    @staticmethod
    def scale(pcd: Any, scale_factor: float) -> Optional[Any]:
        """Scale point cloud."""
        if not OPEN3D_AVAILABLE:
            return None
        try:
            return pcd.scale(scale_factor, center=pcd.get_center())
        except Exception as e:
            print(f"Error scaling: {e}")
            return None


class PointCloudNormalEstimator:
    """Estimate normals for point clouds."""
    
    @staticmethod
    def estimate_normals(pcd: Any, search_param_knn: int = 30, 
                        search_param_radius: Optional[float] = None) -> bool:
        """Estimate normals using KNN or radius search."""
        if not OPEN3D_AVAILABLE:
            return False
        
        try:
            if search_param_radius:
                pcd.estimate_normals(
                    search_param=o3d.geometry.KDTreeSearchParamHybrid(
                        radius=search_param_radius,
                        max_nn=search_param_knn
                    )
                )
            else:
                pcd.estimate_normals(
                    search_param=o3d.geometry.KDTreeSearchParamKNN(
                        knn=search_param_knn
                    )
                )
            
            pcd.orient_normals_consistent_tangent_plane(k=search_param_knn)
            return True
        except Exception as e:
            print(f"Error estimating normals: {e}")
            return False


class MeshReconstructor:
    """Reconstruct mesh from point cloud."""
    
    @staticmethod
    def poisson_reconstruction(pcd: Any, depth: int = 9, 
                               width: int = 0, scale: float = 1.1,
                               linear_fit: bool = False) -> Optional[Tuple[Any, Any]]:
        """Poisson surface reconstruction."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            # Ensure normals exist
            if not pcd.has_normals():
                PointCloudNormalEstimator.estimate_normals(pcd)
            
            mesh, densities = pcd.create_from_point_cloud_poisson(
                depth=depth,
                width=width,
                scale=scale,
                linear_fit=linear_fit
            )
            
            return mesh, densities
        except Exception as e:
            print(f"Error in Poisson reconstruction: {e}")
            return None
    
    @staticmethod
    def ball_pivoting(pcd: Any, radii: Optional[List[float]] = None) -> Optional[Any]:
        """Ball pivoting algorithm reconstruction."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            # Ensure normals exist
            if not pcd.has_normals():
                PointCloudNormalEstimator.estimate_normals(pcd)
            
            if radii is None:
                # Estimate good radii
                distances = pcd.compute_nearest_neighbor_distance()
                avg_dist = np.mean(distances)
                radii = [avg_dist, avg_dist * 2, avg_dist * 4]
            
            mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
                pcd,
                o3d.utility.DoubleVector(radii)
            )
            
            return mesh
        except Exception as e:
            print(f"Error in ball pivoting: {e}")
            return None
    
    @staticmethod
    def alpha_shape(pcd: Any, alpha: float = 0.03) -> Optional[Any]:
        """Alpha shape reconstruction."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_alpha_shape(
                pcd, alpha
            )
            return mesh
        except Exception as e:
            print(f"Error in alpha shape: {e}")
            return None


class PointCloudSegmenter:
    """Segment point clouds."""
    
    @staticmethod
    def plane_segmentation(pcd: Any, distance_threshold: float = 0.01,
                          ransac_n: int = 3, num_iterations: int = 1000) -> Optional[Tuple[Any, Any]]:
        """Segment largest plane using RANSAC."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            plane_model, inliers = pcd.segment_plane(
                distance_threshold=distance_threshold,
                ransac_n=ransac_n,
                num_iterations=num_iterations
            )
            
            inlier_cloud = pcd.select_by_index(inliers)
            outlier_cloud = pcd.select_by_index(inliers, invert=True)
            
            return inlier_cloud, outlier_cloud
        except Exception as e:
            print(f"Error in plane segmentation: {e}")
            return None
    
    @staticmethod
    def dbscan_clustering(pcd: Any, eps: float = 0.02, min_points: int = 10) -> Optional[np.ndarray]:
        """DBSCAN clustering."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            labels = np.array(pcd.cluster_dbscan(
                eps=eps,
                min_points=min_points,
                print_progress=False
            ))
            return labels
        except Exception as e:
            print(f"Error in DBSCAN: {e}")
            return None


class PointCloudRegistration:
    """Register/align point clouds."""
    
    @staticmethod
    def icp_registration(source: Any, target: Any, threshold: float = 0.02,
                        max_iteration: int = 50) -> Optional[Dict[str, Any]]:
        """ICP (Iterative Closest Point) registration."""
        if not OPEN3D_AVAILABLE:
            return None
        
        try:
            trans_init = np.eye(4)
            
            reg_p2p = o3d.pipelines.registration.registration_icp(
                source, target, threshold, trans_init,
                o3d.pipelines.registration.TransformationEstimationPointToPoint(),
                o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iteration)
            )
            
            return {
                'transformation': reg_p2p.transformation,
                'fitness': float(getattr(reg_p2p, 'fitness', 0.0)),
                'rmse': float(getattr(reg_p2p, 'inlier_rmse', 0.0))
            }
        except Exception as e:
            print(f"Error in ICP: {e}")
            return None

    @staticmethod
    def ransac_registration(source: Any, target: Any, voxel_size: float = 0.05) -> Optional[Dict[str, Any]]:
        """Global RANSAC registration."""
        if not OPEN3D_AVAILABLE:
            return None
            
        try:
            # Downsample
            source_down = source.voxel_down_sample(voxel_size)
            target_down = target.voxel_down_sample(voxel_size)
            
            # Estimate normals
            radius_normal = voxel_size * 2
            source_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius_normal, max_nn=30))
            target_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius_normal, max_nn=30))
            
            # Compute FPFH features
            radius_feature = voxel_size * 5
            source_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
                source_down, o3d.geometry.KDTreeSearchParamHybrid(radius=radius_feature, max_nn=100))
            target_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
                target_down, o3d.geometry.KDTreeSearchParamHybrid(radius=radius_feature, max_nn=100))
            
            # RANSAC
            distance_threshold = voxel_size * 1.5
            result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
                source_down, target_down, source_fpfh, target_fpfh, True,
                distance_threshold,
                o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
                3, [
                    o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                    o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(distance_threshold)
                ], o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999)
            )
            
            return {
                'transformation': result.transformation,
                'fitness': float(getattr(result, 'fitness', 0.0)),
                'rmse': float(getattr(result, 'inlier_rmse', 0.0))
            }
            
        except Exception as e:
            print(f"Error in RANSAC: {e}")
            return None


class PointCloudProcessor(QObject):
    """Main point cloud processor coordinating all operations."""
    
    processing_progress = pyqtSignal(int, str)
    processing_complete = pyqtSignal(bool, dict)
    
    def __init__(self):
        super().__init__()
        self.loader = PointCloudLoader()
        self.analyzer = PointCloudAnalyzer()
        self.filter = PointCloudFilter()
        self.transformer = PointCloudTransformer()
        self.normal_estimator = PointCloudNormalEstimator()
        self.reconstructor = MeshReconstructor()
        self.segmenter = PointCloudSegmenter()
        self.registration = PointCloudRegistration()
    
    def load_point_cloud(self, file_path: str) -> Optional[Any]:
        """Load point cloud from file."""
        return self.loader.load(file_path)
    
    def save_point_cloud(self, pcd: Any, output_path: str) -> bool:
        """Save point cloud to file."""
        return self.loader.save(pcd, output_path)
    
    def analyze_point_cloud(self, file_path: str) -> Optional[PointCloudStatistics]:
        """Analyze point cloud file."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return None
        return self.analyzer.analyze(pcd)
    
    def downsample(self, file_path: str, output_path: str, voxel_size: float = 0.05) -> Dict[str, Any]:
        """Downsample point cloud."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        original_count = len(pcd.points)
        downsampled = self.filter.voxel_downsample(pcd, voxel_size)
        
        if downsampled is None:
            return {'success': False, 'error': 'Downsampling failed'}
        
        new_count = len(downsampled.points)
        success = self.save_point_cloud(downsampled, output_path)
        
        return {
            'success': success,
            'original_points': original_count,
            'downsampled_points': new_count,
            'reduction': ((original_count - new_count) / original_count) * 100,
            'output_path': output_path
        }
    
    def remove_outliers(self, file_path: str, output_path: str, 
                       method: str = 'statistical', **kwargs) -> Dict[str, Any]:
        """Remove outliers from point cloud."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        original_count = len(pcd.points)
        
        if method == 'statistical':
            filtered = self.filter.statistical_outlier_removal(
                pcd,
                nb_neighbors=kwargs.get('nb_neighbors', 20),
                std_ratio=kwargs.get('std_ratio', 2.0)
            )
        elif method == 'radius':
            filtered = self.filter.radius_outlier_removal(
                pcd,
                nb_points=kwargs.get('nb_points', 16),
                radius=kwargs.get('radius', 0.05)
            )
        else:
            return {'success': False, 'error': f'Unknown method: {method}'}
        
        if filtered is None:
            return {'success': False, 'error': 'Outlier removal failed'}
        
        new_count = len(filtered.points)
        success = self.save_point_cloud(filtered, output_path)
        
        return {
            'success': success,
            'original_points': original_count,
            'filtered_points': new_count,
            'removed': original_count - new_count,
            'output_path': output_path
        }
    
    def reconstruct_mesh(self, file_path: str, output_path: str,
                        method: str = 'poisson', **kwargs) -> Dict[str, Any]:
        """Reconstruct mesh from point cloud."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        if method == 'poisson':
            result = self.reconstructor.poisson_reconstruction(
                pcd,
                depth=kwargs.get('depth', 9),
                scale=kwargs.get('scale', 1.1)
            )
            if result is None:
                return {'success': False, 'error': 'Poisson reconstruction failed'}
            mesh, densities = result
            
        elif method == 'ball_pivoting':
            mesh = self.reconstructor.ball_pivoting(
                pcd,
                radii=kwargs.get('radii', None)
            )
            if mesh is None:
                return {'success': False, 'error': 'Ball pivoting failed'}
                
        elif method == 'alpha_shape':
            mesh = self.reconstructor.alpha_shape(
                pcd,
                alpha=kwargs.get('alpha', 0.03)
            )
            if mesh is None:
                return {'success': False, 'error': 'Alpha shape failed'}
        else:
            return {'success': False, 'error': f'Unknown method: {method}'}
        
        # Save mesh
        try:
            if OPEN3D_AVAILABLE:
                o3d.io.write_triangle_mesh(output_path, mesh)
            return {
                'success': True,
                'vertices': len(mesh.vertices),
                'triangles': len(mesh.triangles),
                'output_path': output_path
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def estimate_normals(self, file_path: str, output_path: str, knn: int = 30) -> Dict[str, Any]:
        """Estimate normals for point cloud."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        success = self.normal_estimator.estimate_normals(pcd, search_param_knn=knn)
        
        if success:
            save_success = self.save_point_cloud(pcd, output_path)
            return {
                'success': save_success,
                'output_path': output_path
            }
        else:
            return {'success': False, 'error': 'Normal estimation failed'}
    
    def segment_plane(self, file_path: str, inlier_path: str, outlier_path: str,
                     distance_threshold: float = 0.01) -> Dict[str, Any]:
        """Segment largest plane from point cloud."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        result = self.segmenter.plane_segmentation(pcd, distance_threshold=distance_threshold)
        if result is None:
            return {'success': False, 'error': 'Plane segmentation failed'}
        
        inlier_cloud, outlier_cloud = result
        
        inlier_success = self.save_point_cloud(inlier_cloud, inlier_path)
        outlier_success = self.save_point_cloud(outlier_cloud, outlier_path)
        
        return {
            'success': inlier_success and outlier_success,
            'inlier_points': len(inlier_cloud.points),
            'outlier_points': len(outlier_cloud.points),
            'inlier_path': inlier_path,
            'outlier_path': outlier_path
        }

    def cluster_dbscan(self, file_path: str, output_path: str, eps: float = 0.02, min_points: int = 10) -> Dict[str, Any]:
        """Cluster point cloud using DBSCAN."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        labels = self.segmenter.dbscan_clustering(pcd, eps, min_points)
        if labels is None:
            return {'success': False, 'error': 'Clustering failed'}
            
        max_label = labels.max()
        if max_label < 0:
             return {'success': True, 'clusters': 0, 'output_path': file_path, 'message': 'No clusters found'}

        # Colorize
        try:
            import matplotlib.pyplot as plt
            colors = plt.get_cmap("tab20")(labels / (max_label if max_label > 0 else 1))
            colors[labels < 0] = 0  # set noise to black
            pcd.colors = o3d.utility.Vector3dVector(colors[:, :3])
        except ImportError:
            # Fallback if matplotlib is not available
            colors = np.random.rand(max_label + 1, 3)
            point_colors = np.zeros((len(labels), 3))
            for i in range(max_label + 1):
                point_colors[labels == i] = colors[i]
            pcd.colors = o3d.utility.Vector3dVector(point_colors)
        
        success = self.save_point_cloud(pcd, output_path)
        
        return {
            'success': success,
            'clusters': int(max_label + 1),
            'output_path': output_path
        }

    def apply_transform(self, file_path: str, output_path: str, 
                       transform_type: str, **kwargs) -> Dict[str, Any]:
        """Apply geometric transformation."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
        
        if transform_type == 'translate':
            pcd = self.transformer.translate(pcd, kwargs.get('translation', (0, 0, 0)))
        elif transform_type == 'rotate':
            pcd = self.transformer.rotate(pcd, kwargs.get('rotation', (0, 0, 0)))
        elif transform_type == 'scale':
            pcd = self.transformer.scale(pcd, kwargs.get('scale', 1.0))
        else:
            return {'success': False, 'error': f'Unknown transform: {transform_type}'}
            
        if pcd is None:
            return {'success': False, 'error': 'Transformation failed'}
            
        success = self.save_point_cloud(pcd, output_path)
        return {
            'success': success,
            'output_path': output_path
        }

    def crop_point_cloud(self, file_path: str, output_path: str, 
                        min_bound: Tuple[float, float, float],
                        max_bound: Tuple[float, float, float]) -> Dict[str, Any]:
        """Crop point cloud."""
        pcd = self.load_point_cloud(file_path)
        if pcd is None:
            return {'success': False, 'error': 'Failed to load point cloud'}
            
        try:
            cropped_pcd = self.filter.crop_box(pcd, min_bound, max_bound)
            
            if cropped_pcd is None:
                return {'success': False, 'error': 'Cropping failed'}
                
            success = self.save_point_cloud(cropped_pcd, output_path)
            
            return {
                'success': success,
                'output_path': output_path,
                'points': len(cropped_pcd.points)
            }
        except Exception as e:
            return {'success': False, 'error': f'Cropping failed: {str(e)}'}

    def register_point_clouds(self, source_path: str, target_path: str, output_path: str,
                            method: str = 'icp', **kwargs) -> Dict[str, Any]:
        """Register two point clouds."""
        source = self.load_point_cloud(source_path)
        target = self.load_point_cloud(target_path)
        
        if source is None or target is None:
            return {'success': False, 'error': 'Failed to load point clouds'}
            
        try:
            reg_result = None
            
            if method == 'icp':
                threshold = kwargs.get('threshold', 0.02)
                max_iter = kwargs.get('max_iteration', 50)
                reg_result = self.registration.icp_registration(
                    source, target, threshold, max_iter
                )
            elif method == 'ransac':
                voxel_size = kwargs.get('voxel_size', 0.05)
                reg_result = self.registration.ransac_registration(
                    source, target, voxel_size
                )
                
            if reg_result is None or 'transformation' not in reg_result:
                return {'success': False, 'error': 'Registration failed'}
                
            transformation = reg_result['transformation']
            fitness = reg_result.get('fitness', 0.0)
            rmse = reg_result.get('rmse', 0.0)
            
            # Apply transformation
            source.transform(transformation)
            
            # Save registered source
            success = self.save_point_cloud(source, output_path)
            
            return {
                'success': success,
                'output_path': output_path,
                'transformation': transformation.tolist() if hasattr(transformation, 'tolist') else transformation,
                'fitness': fitness,
                'rmse': rmse
            }
        except Exception as e:
            return {'success': False, 'error': f'Registration failed: {str(e)}'}
