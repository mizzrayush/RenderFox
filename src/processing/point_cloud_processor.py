"""
RenderFox Point Cloud Processor
Provides point cloud loading, processing, filtering, and mesh reconstruction.

This module is the only place in the app that touches Open3D for point clouds. The
Point Clouds pane asks it for one thing at a time - a verb and two paths - and gets
back a verdict built from the file that ended up on disk, never from the object that
was held in memory while it was written.
"""

import os
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False


# What `o3d.io.read_point_cloud` opens on this build, checked one extension at a time by
# tests/test_point_clouds_contract.py. The pane's browse filters used to name formats no
# reader here can open, so a user could pick a file that was always going to fail.
READABLE_EXTENSIONS = ('.pcd', '.ply', '.xyz', '.pts')
# What `o3d.io.write_point_cloud` answers True to, measured the same way. `.obj` is not one
# of them - the writer here does that file itself, as a vertex list (see `write_points`).
WRITABLE_EXTENSIONS = ('.pcd', '.ply', '.xyz', '.pts')
VERTEX_ONLY_OBJ = '.obj'


def cloud_output_path(source_path: str, suffix: str, extension: Optional[str] = None) -> str:
    """The derived file beside its source: `scan.ply` + `centered` -> `scan_centered.ply`.

    Every caller used to build this with `path.replace('.', '_centered.')`, which rewrites
    *every* dot in the string - `D:\\scans\\v1.2\\site.ply` came back as
    `D:\\scans\\v1_2\\site_centered.ply`, a folder that does not exist, so the write failed
    and the run reported a file it never made. Only the last dot of the file name is the
    extension, and `os.path.splitext` is the one function that knows that.
    """
    folder = os.path.dirname(source_path)
    stem, _ = os.path.splitext(os.path.basename(source_path))
    name = f'{stem}_{suffix}{extension or os.path.splitext(source_path)[1] or ".ply"}'
    return os.path.join(folder, name) if folder else name


def cluster_palette(count: int) -> np.ndarray:
    """`count` colours that are the same on every run, one per cluster.

    The labels used to be coloured through `matplotlib.pyplot`, which pulls a GUI backend
    into a worker thread for four lines of arithmetic and left the picture depending on
    which pyplot backend answered. Three phase-shifted cosines are deterministic, need no
    import, and keep neighbouring clusters visibly apart.
    """
    count = max(int(count), 1)
    hues = np.arange(count, dtype=float) / count
    angles = 2.0 * np.pi * hues
    rgb = np.stack([np.cos(angles), np.cos(angles - 2.0 * np.pi / 3.0),
                    np.cos(angles + 2.0 * np.pi / 3.0)], axis=1)
    return np.clip(0.5 + 0.45 * rgb, 0.0, 1.0)


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
    """Read and write the files a point cloud comes in."""

    @staticmethod
    def load(file_path: str) -> Optional[Any]:
        """The cloud in `file_path`, or None for a reason `read_report` states."""
        return PointCloudLoader.read_report(file_path)[0]

    @staticmethod
    def read_report(file_path: str) -> Tuple[Optional[Any], Optional[str]]:
        """`(cloud, None)` or `(None, the sentence that says why there is no cloud).

        `o3d.io.read_point_cloud` does not raise on a missing or unreadable file - it
        answers with a cloud holding no points. Every caller here tested that result with
        `is None`, so a file that was not there at all was reported as a loaded cloud with
        zero points and the operation that followed died on the arithmetic
        (`downsample` divided the reduction by a point count of zero). The distinction
        belongs to the reader, so the reader makes it.
        """
        if not OPEN3D_AVAILABLE:
            return None, ('Open3D is not installed here, so no point cloud file can be '
                          'read - install the open3d package this pane is built on')
        if not os.path.isfile(file_path):
            return None, f'there is no file at {file_path}'
        try:
            pcd = o3d.io.read_point_cloud(file_path)
        except Exception as e:
            return None, f'{os.path.basename(file_path)} could not be read as a point cloud: {e}'
        points = len(pcd.points)
        if points == 0:
            return None, (f'{os.path.basename(file_path)} holds no points - Open3D read it '
                          'and found an empty or unsupported file')
        return pcd, None

    @staticmethod
    def save(pcd: Any, output_path: str) -> bool:
        """Write the cloud and say whether the file is there afterwards.

        The old version returned True whenever `write_point_cloud` did not raise; Open3D
        answers False for a folder that is missing or an extension it cannot write, so a
        failed save was reported as a saved file. The proof is the file itself.
        """
        if not OPEN3D_AVAILABLE or pcd is None:
            return False
        if not o3d.io.write_point_cloud(output_path, pcd):
            return False
        return os.path.isfile(output_path)


class PointCloudAnalyzer:
    """Measure what is actually in a cloud."""

    @staticmethod
    def analyze(pcd: Any) -> PointCloudStatistics:
        """Count, colours, normals, extent, centre and density of `pcd`.

        A cloud with no extent (all points in one place, or one point) has no volume, so
        its density is reported as 0.0 rather than the division by zero the old version
        hid behind a bare `except`.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so a cloud cannot be measured')
        points = np.asarray(pcd.points)
        bbox = pcd.get_axis_aligned_bounding_box()
        bbox_size = tuple(float(v) for v in bbox.get_extent())
        volume = bbox_size[0] * bbox_size[1] * bbox_size[2]
        return PointCloudStatistics(
            point_count=len(points),
            has_colors=pcd.has_colors(),
            has_normals=pcd.has_normals(),
            bounding_box=bbox_size,
            centroid=tuple(float(v) for v in pcd.get_center()),
            density=(len(points) / volume) if volume > 0 else 0.0,
        )


class PointCloudFilter:
    """Thin, raising wrappers over the Open3D cleaning operations.

    Each used to catch its own exception, print one line to standard output and answer
    None. The printout never reaches a user and the None reached the pane as
    "Downsampling failed", which is not a reason. They raise now and the processor turns
    the exception into the sentence the user reads.
    """

    @staticmethod
    def voxel_downsample(pcd: Any, voxel_size: float = 0.05) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        return pcd.voxel_down_sample(voxel_size=float(voxel_size))

    @staticmethod
    def uniform_downsample(pcd: Any, every_k: int) -> Any:
        """Keep every k-th point, which is what the pane's "Every K-th Point" asks for.

        There was no such method, so the button behind it had nothing to call. Note this
        is not Open3D's `farthest_point_down_sample`, which needs a target count rather
        than a step.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        step = max(int(every_k), 1)
        keep = np.arange(0, len(pcd.points), step)
        if len(keep) == 0:
            raise RuntimeError(f'keeping every {step}-th point of this cloud leaves nothing')
        return pcd.select_by_index(keep)

    @staticmethod
    def remove_duplicated(pcd: Any) -> Any:
        """One point per coincident position.

        The name on Open3D 0.19 is `remove_duplicated_points`; `remove_duplicates` - what
        the pane assumed - does not exist on a PointCloud here.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        return pcd.remove_duplicated_points()

    @staticmethod
    def statistical_outlier_removal(pcd: Any, nb_neighbors: int = 20, std_ratio: float = 2.0) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        kept, _ = pcd.remove_statistical_outlier(nb_neighbors=int(nb_neighbors),
                                                 std_ratio=float(std_ratio))
        return kept

    @staticmethod
    def radius_outlier_removal(pcd: Any, nb_points: int = 16, radius: float = 0.05) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        kept, _ = pcd.remove_radius_outlier(nb_points=int(nb_points), radius=float(radius))
        return kept

    @staticmethod
    def crop_box(pcd: Any, min_bound: Tuple[float, float, float],
                 max_bound: Tuple[float, float, float]) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        bbox = o3d.geometry.AxisAlignedBoundingBox(min_bound=min_bound, max_bound=max_bound)
        return pcd.crop(bbox)


class PointCloudTransformer:
    """Apply geometric transformations."""

    @staticmethod
    def translate(pcd: Any, translation: Tuple[float, float, float]) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        return pcd.translate(np.asarray(translation, dtype=float))

    @staticmethod
    def rotate(pcd: Any, rotation: Tuple[float, float, float]) -> Any:
        """Euler angles in degrees about the cloud's own centre."""
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        matrix = pcd.get_rotation_matrix_from_xyz(np.radians(np.asarray(rotation, dtype=float)))
        return pcd.rotate(matrix, center=pcd.get_center())

    @staticmethod
    def scale(pcd: Any, scale_factor: float) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        return pcd.scale(float(scale_factor), center=pcd.get_center())

    @staticmethod
    def centered(pcd: Any) -> Any:
        """Move the centroid to the origin; returns the offset it removed."""
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        center = np.asarray(pcd.get_center())
        pcd.translate(-center)
        return center

    @staticmethod
    def to_unit_extent(pcd: Any) -> float:
        """Centre on the origin and scale the longest side of the box to 1.0."""
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        PointCloudTransformer.centered(pcd)
        extent = np.asarray(pcd.get_max_bound()) - np.asarray(pcd.get_min_bound())
        longest = float(extent.max())
        if longest <= 0.0:
            raise RuntimeError('every point of this cloud is in the same place, so it has '
                               'no extent to normalise against')
        factor = 1.0 / longest
        pcd.scale(factor, center=(0.0, 0.0, 0.0))
        return factor


class PointCloudNormalEstimator:
    """Estimate and orient normals."""

    @staticmethod
    def estimate_normals(pcd: Any, search_param_knn: int = 30,
                         search_param_radius: Optional[float] = None) -> None:
        """Neighbours per point come from the caller; a too-large knn is refused.

        `orient_normals_consistent_tangent_plane` needs at least as many neighbours as the
        search takes, and on a small cloud it throws - which the old wrapper printed and
        turned into False, so the pane read "Normal estimation failed" with no hint that
        the number typed was bigger than the cloud.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so normals cannot be estimated')
        points = len(pcd.points)
        knn = max(int(search_param_knn), 3)
        if knn > points:
            raise RuntimeError(
                f'{knn} neighbours needs a cloud of at least {knn} points and this one has '
                f'{points}; lower "Neighbours" or merge clouds first')
        if search_param_radius:
            pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(
                radius=float(search_param_radius), max_nn=knn))
        else:
            pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamKNN(knn=knn))
        pcd.orient_normals_consistent_tangent_plane(k=knn)


class MeshReconstructor:
    """Reconstruct mesh from point cloud."""

    @staticmethod
    def poisson_reconstruction(pcd: Any, depth: int = 9,
                               width: int = 0, scale: float = 1.1,
                               linear_fit: bool = False) -> Tuple[Any, Any]:
        """Poisson surface reconstruction.

        This used to call `pcd.create_from_point_cloud_poisson(...)`, which is not a
        method of a PointCloud on Open3D 0.19 - the factory is on TriangleMesh. The
        AttributeError was caught, printed and returned as None, so the pane's headline
        "Run Poisson Reconstruction" could only ever answer "Poisson reconstruction
        failed" and no user could tell that the surface had never been attempted. The
        `width` and `linear_fit` the pane's own boxes set were dropped on the way.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so no surface can be built')
        if not pcd.has_normals():
            PointCloudNormalEstimator.estimate_normals(pcd)
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd, depth=int(depth), width=float(width), scale=float(scale),
            linear_fit=bool(linear_fit))
        return mesh, densities

    @staticmethod
    def trim_by_density(mesh: Any, densities: Any, quantiles: Tuple[float, float] = (0.01, 0.99)) -> Any:
        """Cut the Poisson blob's low-confidence shell, keeping the measured surface.

        Poisson answers with a closed surface that pads every open boundary with a
        near-zero-density skin. The pane's Depth control is about the octree, not the
        extent, so the file a user got was bigger than the scan and looked like a
        reconstruction artefact in Blender. Open3D's own documented way to drop it is the
        density percentiles.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        values = np.asarray(densities)
        if len(values) == 0 or len(values) != len(mesh.vertices):
            raise RuntimeError('the densities do not line up with the mesh vertices')
        low, high = quantiles
        keep = np.nonzero((values >= np.quantile(values, low)) &
                          (values <= np.quantile(values, high)))[0]
        if len(keep) < 3:
            raise RuntimeError(f'the density trim left {len(keep)} vertices - not enough to '
                               'form a surface, so the untrimmed mesh is kept instead')
        return mesh.select_by_index(keep)

    @staticmethod
    def ball_pivoting(pcd: Any, radii: Optional[List[float]] = None) -> Any:
        """Ball pivoting, with radii derived from the cloud when none are given."""
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so no surface can be built')
        if not pcd.has_normals():
            PointCloudNormalEstimator.estimate_normals(pcd)
        if not radii:
            distances = np.asarray(pcd.compute_nearest_neighbor_distance())
            if len(distances) == 0:
                raise RuntimeError('this cloud is a single point, so no ball radius can be '
                                   'measured from it')
            average = float(np.mean(distances))
            radii = [average, average * 2, average * 4]
        return o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
            pcd, o3d.utility.DoubleVector([float(r) for r in radii]))

    @staticmethod
    def alpha_shape(pcd: Any, alpha: float = 0.03) -> Any:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so no surface can be built')
        return o3d.geometry.TriangleMesh.create_from_point_cloud_alpha_shape(
            pcd, float(alpha))

    @staticmethod
    def convex_hull(pcd: Any) -> Any:
        """The tightest closed shell around the cloud.

        `PointCloud.compute_convex_hull()` answers with a `(mesh, hull_point_indices)`
        tuple on 0.19; taking element 0 is the mesh. `convex_hull` - the name this module
        first reached for - is not a method of a PointCloud here.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so no hull can be built')
        if len(pcd.points) < 4:
            raise RuntimeError(f'a convex hull needs at least 4 points and this cloud has '
                               f'{len(pcd.points)}')
        mesh, _indices = pcd.compute_convex_hull()
        return mesh


class PointCloudSegmenter:
    """Segment point clouds."""

    @staticmethod
    def plane_segmentation(pcd: Any, distance_threshold: float = 0.01,
                           ransac_n: int = 3, num_iterations: int = 1000
                           ) -> Tuple[Any, Any, Tuple[float, float, float, float]]:
        """`(plane inliers, everything else, the plane equation)`.

        The plane equation was computed and thrown away before; it is the only number that
        says *which* plane was found, so the pane can name the floor it split off.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        if len(pcd.points) < ransac_n:
            raise RuntimeError(
                f'plane fitting picks {ransac_n} points at a time and this cloud has only '
                f'{len(pcd.points)}')
        plane_model, inliers = pcd.segment_plane(distance_threshold=float(distance_threshold),
                                                 ransac_n=int(ransac_n),
                                                 num_iterations=int(num_iterations))
        inlier_cloud = pcd.select_by_index(inliers)
        outlier_cloud = pcd.select_by_index(inliers, invert=True)
        return inlier_cloud, outlier_cloud, tuple(float(v) for v in plane_model)

    @staticmethod
    def dbscan_clustering(pcd: Any, eps: float = 0.02, min_points: int = 10) -> np.ndarray:
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here')
        return np.asarray(pcd.cluster_dbscan(eps=float(eps), min_points=int(min_points),
                                             print_progress=False))


class PointCloudRegistration:
    """Register/align point clouds."""

    @staticmethod
    def icp_registration(source: Any, target: Any, threshold: float = 0.02,
                         max_iteration: int = 50) -> Dict[str, Any]:
        """ICP (Iterative Closest Point) registration.

        Fitness and inlier RMSE are measured against the *moved* source, not the original
        one. `registration_icp` reports the numbers for its last iteration's threshold,
        which is a number about the search, not about how well the two clouds now line up;
        evaluating twice on the same distance is what makes the sentence the pane prints
        mean something.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so clouds cannot be aligned')
        criteria = o3d.pipelines.registration.ICPConvergenceCriteria(
            max_iteration=int(max_iteration))
        reg_p2p = o3d.pipelines.registration.registration_icp(
            source, target, float(threshold), np.eye(4),
            o3d.pipelines.registration.TransformationEstimationPointToPoint(), criteria)
        moved = o3d.geometry.PointCloud(source)
        moved.transform(reg_p2p.transformation)
        evaluation = o3d.pipelines.registration.evaluate_registration(
            moved, target, float(threshold))
        return {
            'transformation': reg_p2p.transformation,
            'fitness': float(evaluation.fitness),
            'rmse': float(evaluation.inlier_rmse),
            'correspondences': int(len(evaluation.correspondence_set)),
        }

    @staticmethod
    def average_spacing(pcd: Any) -> float:
        """Mean nearest-neighbour distance, the only scale number a cloud gives up itself."""
        distances = np.asarray(pcd.compute_nearest_neighbor_distance())
        if len(distances) == 0:
            raise RuntimeError('a single point has no neighbour to measure a distance to')
        return float(np.mean(distances))

    @staticmethod
    def features(source: Any, target: Any, voxel_size: float) -> Dict[str, Any]:
        """Downsample both clouds once at a scale that suits them and count the descriptors.

        The pane's "Extract FPFH Features" button had no method behind it and the RANSAC
        call used a fixed voxel of 0.05 whatever the cloud was - for a 200 m scan that is
        the whole cloud kept, for a 2 mm macro it is nothing left at all. One voxel now
        feeds both, and the numbers it produced are what the button reports.
        """
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so features cannot be computed')
        voxel = float(voxel_size)
        if voxel <= 0.0:
            raise RuntimeError('the voxel edge handed to the feature pass is not a length')
        source_down = source.voxel_down_sample(voxel)
        target_down = target.voxel_down_sample(voxel)
        if len(source_down.points) < 3 or len(target_down.points) < 3:
            raise RuntimeError(
                f'a voxel of {voxel:g} leaves {len(source_down.points)} source and '
                f'{len(target_down.points)} target points - nothing to match between them')
        radius_normal = voxel * 2.0
        for cloud in (source_down, target_down):
            cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
                radius=radius_normal, max_nn=30))
        radius_feature = voxel * 5.0
        param = o3d.geometry.KDTreeSearchParamHybrid(radius=radius_feature, max_nn=100)
        source_fpfh = o3d.pipelines.registration.compute_fpfh_feature(source_down, param)
        target_fpfh = o3d.pipelines.registration.compute_fpfh_feature(target_down, param)
        return {
            'voxel_size': voxel,
            'source_points': len(source_down.points),
            'target_points': len(target_down.points),
            'source_descriptors': int(np.asarray(source_fpfh.data).shape[0]),
            'target_descriptors': int(np.asarray(target_fpfh.data).shape[0]),
            'distance_threshold': voxel * 1.5,
            '_source_down': source_down,
            '_target_down': target_down,
            '_source_fpfh': source_fpfh,
            '_target_fpfh': target_fpfh,
        }

    @staticmethod
    def ransac_registration(source: Any, target: Any, voxel_size: float = 0.05) -> Dict[str, Any]:
        """Global RANSAC registration on FPFH features."""
        if not OPEN3D_AVAILABLE:
            raise RuntimeError('Open3D is not installed here, so clouds cannot be aligned')
        prepared = PointCloudRegistration.features(source, target, voxel_size)
        source_down, target_down = prepared['_source_down'], prepared['_target_down']
        source_fpfh, target_fpfh = prepared['_source_fpfh'], prepared['_target_fpfh']
        distance_threshold = prepared['distance_threshold']
        result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            source_down, target_down, source_fpfh, target_fpfh, True,
            distance_threshold,
            o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
            3, [
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(distance_threshold)
            ],
            o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999))
        moved = o3d.geometry.PointCloud(source_down)
        moved.transform(result.transformation)
        evaluation = o3d.pipelines.registration.evaluate_registration(
            moved, target_down, distance_threshold)
        return {
            'transformation': result.transformation,
            'fitness': float(evaluation.fitness),
            'rmse': float(evaluation.inlier_rmse),
            'correspondences': int(len(evaluation.correspondence_set)),
            'voxel_size': voxel_size,
            'distance_threshold': distance_threshold,
        }


class PointCloudProcessor:
    """The one object a caller asks for a point-cloud verdict.

    There is no Qt in this class any more. It was a QObject with two signals nobody
    emitted and nobody connected, so the automation launcher had to import PyQt before it
    could process a file. Every call answers, in the caller's thread, with a dict of
    numbers measured off the file that ended up on disk - the pane owns the threading, the
    dialogs and the sentences built from those numbers.
    """

    # The verbs this module answers. The pane's buttons name one each; a name missing here
    # is a button that cannot be wired, and a name here with no button is dead code.
    OPERATIONS = (
        'analyze', 'center', 'normalize', 'dedup', 'voxel', 'uniform',
        'outliers_statistical', 'outliers_radius', 'crop', 'translate', 'rotate', 'scale',
        'normals', 'planes', 'cluster', 'hull', 'poisson', 'ball_pivoting', 'alpha_shape',
        'features', 'register_icp', 'register_ransac', 'distances', 'export', 'pick',
    )

    # The verbs that answer with a surface rather than another cloud. The pane routes these
    # to its "Export as Mesh" hand-off instead of making them the current model, and the
    # automation adapter names their files after the surface format instead of the cloud's.
    SURFACE_VERBS = ('hull', 'poisson', 'ball_pivoting', 'alpha_shape')

    # What Automation and a workflow step may run, built from the verbs themselves:
    # (verb, action id, the description the task pane shows, extra parameters and their
    # types, and how the action takes its file). Nothing here opens a window, so `pick` is
    # not in it - a scheduled task that waits for someone to left-click would run at 3am
    # and report nothing.
    AUTOMATION_TABLE = (
        ('analyze', 'pcd.analyze', 'Measure a cloud: count, colours, normals, extent, '
                                    'centre, density', {}, 'read'),
        ('distances', 'pcd.distances', 'Nearest-neighbour distance statistics of a cloud',
                                       {}, 'read'),
        ('center', 'pcd.center', 'Move a cloud so its centre is the origin', {}, 'cloud'),
        ('normalize', 'pcd.normalize', 'Centre a cloud and scale its longest side to 1',
                                       {}, 'cloud'),
        ('dedup', 'pcd.dedup', 'Drop the points that sit on top of each other', {}, 'cloud'),
        ('voxel', 'pcd.voxel', 'Voxel downsampling - one point per voxel cube',
                               {'voxel_size': 'float'}, 'cloud'),
        ('uniform', 'pcd.uniform', 'Keep every K-th point', {'every_k': 'int'}, 'cloud'),
        ('outliers_statistical', 'pcd.filter_statistical', 'Remove statistical outliers',
         {'nb_neighbors': 'int', 'std_ratio': 'float'}, 'cloud'),
        ('outliers_radius', 'pcd.filter_radius', 'Remove points with too few neighbours '
                                                 'within a radius',
         {'radius': 'float', 'nb_points': 'int'}, 'cloud'),
        ('normals', 'pcd.normals', 'Estimate and orient normals, saved into the file',
                                   {'knn': 'int'}, 'cloud'),
        ('crop', 'pcd.crop', 'Keep the points inside a box given in the file\'s own units',
                             {'min_bound': 'list', 'max_bound': 'list'}, 'cloud'),
        ('translate', 'pcd.translate', 'Move a cloud by x, y and z',
                                       {'dx': 'float', 'dy': 'float', 'dz': 'float'}, 'cloud'),
        ('rotate', 'pcd.rotate', 'Turn a cloud about its own centre, in degrees',
                                 {'rx': 'float', 'ry': 'float', 'rz': 'float'}, 'cloud'),
        ('scale', 'pcd.scale', 'Scale a cloud about its own centre', {'factor': 'float'},
                               'cloud'),
        ('cluster', 'pcd.cluster', 'DBSCAN clustering, one colour per group',
                                   {'eps': 'float', 'min_points': 'int'}, 'cloud'),
        ('planes', 'pcd.planes', 'Split the largest plane off a cloud into two files',
         {'distance_threshold': 'float', 'ransac_n': 'int', 'num_iterations': 'int'},
         'split'),
        ('hull', 'pcd.hull', 'Convex hull of a cloud, as a surface file',
         {'extension': 'str'}, 'surface'),
        ('poisson', 'pcd.poisson', 'Poisson surface reconstruction of a cloud',
         {'depth': 'int', 'width': 'int', 'scale': 'float', 'linear_fit': 'bool',
          'trim': 'bool', 'extension': 'str'}, 'surface'),
        ('ball_pivoting', 'pcd.ball_pivoting', 'Ball pivoting surface of a cloud',
         {'ball_radius': 'float', 'extension': 'str'}, 'surface'),
        ('alpha_shape', 'pcd.alpha_shape', 'Alpha shape surface of a cloud',
         {'alpha': 'float', 'extension': 'str'}, 'surface'),
        ('export', 'pcd.export', 'Rewrite a cloud as another point-cloud file',
                                 {'extension': 'str'}, 'export'),
        ('features', 'pcd.features', 'Count FPFH descriptors between two clouds',
                                     {'voxel_size': 'float'}, 'pair'),
        ('register_icp', 'pcd.register_icp', 'Align one cloud onto another by ICP',
         {'threshold': 'float', 'max_iteration': 'int'}, 'pair'),
        ('register_ransac', 'pcd.register_ransac', 'Global RANSAC alignment of two clouds',
                                                   {'voxel_size': 'float'}, 'pair'),
    )

    # Per shape: the parameter a batch feeds one file into (None when the verb cannot take
    # a batch because it needs two named clouds), and the parameter an output folder goes
    # into (None when the verb leaves no file of its own).
    _SHAPES = {'read': ('file_path', None),
               'cloud': ('file_path', 'output_dir'),
               'surface': ('file_path', 'output_dir'),
               'split': ('file_path', 'output_dir'),
               'export': ('file_path', 'output_dir'),
               'pair': (None, None)}

    def __init__(self):
        self.loader = PointCloudLoader()
        self.analyzer = PointCloudAnalyzer()
        self.filter = PointCloudFilter()
        self.transformer = PointCloudTransformer()
        self.normal_estimator = PointCloudNormalEstimator()
        self.reconstructor = MeshReconstructor()
        self.segmenter = PointCloudSegmenter()
        self.registration = PointCloudRegistration()
        # The feature pass the user ran, remembered for the registration that uses it.
        self.prepared = None

    # ---- the vocabulary this module owns ---------------------------------------

    @staticmethod
    def readable_formats() -> List[str]:
        """Extensions a point cloud can be opened from here, measured on this build."""
        return list(READABLE_EXTENSIONS)

    @staticmethod
    def writable_formats() -> List[str]:
        """Extensions a cloud can be written to - and the one file this module writes."""
        return list(WRITABLE_EXTENSIONS) + [VERTEX_ONLY_OBJ]

    @staticmethod
    def output_path(source_path: str, suffix: str, extension: Optional[str] = None) -> str:
        return cloud_output_path(source_path, suffix, extension)

    def target_path(self, params: Dict[str, Any], source_path: str, suffix: str,
                    extension: Optional[str] = None) -> str:
        """The file this verb writes: its own name, in the folder the task named or beside
        the source.

        Automation and Batch hand one `output_dir` to every verb and never a file name, so
        the folder has to be honoured without the caller inventing names. The task callable
        used to build them itself as `stem + extension`, which for a cloud already sitting in
        that folder is the source file - a scheduled `pcd.center` over `D:\\scans` rewrote the
        scans in place, and two verbs in one folder overwrote each other whatever the order.
        One rule here means the button, the task and the batch all name the same file.

        The only name a verb does not choose for itself is one a person typed: `op_export`
        reads the `output_path` a Save dialog returned before it asks anything of this
        method. Nothing else may hand a file name in, because a caller that re-derives the
        name here can drift from it without any test being able to see the difference.
        """
        path = self.output_path(source_path, suffix, extension)
        folder = params.get('output_dir')
        return os.path.join(folder, os.path.basename(path)) if folder else path

    def surface_formats(self) -> List[str]:
        """Extensions a reconstructed surface can be saved as on this machine.

        Asked of ``FormatConverter``, which is the app's only mesh writer, so the pane's
        "Save as" choices are the formats that genuinely take the file rather than a list
        of names this build cannot honour.
        """
        try:
            from .format_converter import FormatConverter
            return list(FormatConverter().mesh_write_formats())
        except Exception:
            return ['.ply', '.obj', '.stl']

    @staticmethod
    def surface_target(source_path: str, extension: str = '.ply') -> str:
        """Where a surface built from this cloud goes, keeping the cloud's folder."""
        if not extension:
            extension = '.ply'
        if not extension.startswith('.'):
            extension = '.' + extension
        return cloud_output_path(source_path, 'mesh', extension.lower())

    def automation_action(self, operation, shape):
        """The callable the registry runs for one verb.

        A task calls an action with keyword arguments and, in a batch, one file at a time,
        while a verb takes a params dict. This is the thin edge between the two: it checks
        the file the task named and the folder it named, and hands both to the verb, which
        decides what its own output file is called (`target_path`). The verdict that comes
        back is the same dict the pane reports, so a nightly batch says the same thing about
        a scan as the button does.
        """
        def action(**kwargs):
            params = dict(kwargs)
            source = params.get('file_path') or params.get('source_path')
            if not source:
                return self._refuse(operation, 'no file was named to read')
            folder = params.get('output_dir')
            if folder and not os.path.isdir(folder):
                return self._refuse(operation, f'{folder} is not a folder on this disk, so '
                                               f'nothing can be written into it')
            if shape == 'export' and not folder:
                # `op_export` writes only where it is told, and a task has no dialog to be
                # told from, so beside the source is the one name this can choose.
                params['output_path'] = self.output_path(source, 'export',
                                                         params.get('extension') or '.ply')
            return self.run(operation, params)
        return action

    def automation_actions(self):
        """Every verb this module answers, in the shape `ActionRegistry.register` takes.

        The launcher used to name six processor methods by hand - `load_point_cloud`,
        `save_point_cloud`, `reconstruct_mesh` - and all six stopped existing when this
        module became verb-based. The AttributeError landed in the launcher's own `except`,
        which printed one line nobody read: the app started with no point-cloud action
        registered at all, and the Automation pane offered none. Building the list from the
        table above makes that drift impossible.
        """
        actions = []
        for verb, action_id, description, extra, shape in self.AUTOMATION_TABLE:
            item_param, folder_param = self._SHAPES[shape]
            spec = {}
            if shape == 'pair':
                spec['source_path'] = {'type': 'str', 'required': True}
                spec['target_path'] = {'type': 'str', 'required': True}
            else:
                spec['file_path'] = {'type': 'str', 'required': True}
            if folder_param:
                spec[folder_param] = {'type': 'str', 'required': False}
            for name, kind in extra.items():
                spec[name] = {'type': kind, 'required': False}
            batch = (item_param, folder_param) if item_param else None
            actions.append((action_id, self.automation_action(verb, shape), description,
                            spec, batch))
        return actions

    # ---- the envelope every verb answers with ----------------------------------

    def _base(self, operation: str) -> Dict[str, Any]:
        return {'operation': operation, 'success': False, 'stopped': False, 'error': None,
                'output_path': None, 'files': [], 'points_before': None,
                'points_after': None, 'measure': {}}

    def _refuse(self, operation: str, error: str, stopped: bool = False,
                **fields: Any) -> Dict[str, Any]:
        verdict = self._base(operation)
        verdict['error'] = error
        verdict['stopped'] = bool(stopped)
        verdict.update(fields)
        return verdict

    def _accepted(self, operation: str, **fields: Any) -> Dict[str, Any]:
        verdict = self._base(operation)
        verdict['success'] = True
        verdict.update(fields)
        return verdict

    def _cancelled(self, should_cancel) -> bool:
        return bool(should_cancel and should_cancel())

    # ---- reading and writing, with the proof asked of the file ------------------

    def read_cloud(self, file_path: str) -> Tuple[Optional[Any], Optional[str]]:
        """`(cloud, None)` or `(None, why there is no cloud)`. The pane's only reader."""
        return PointCloudLoader.read_report(file_path)

    def write_points(self, cloud: Any, output_path: str) -> Tuple[Optional[int], Optional[str]]:
        """Write a cloud, then count the points the file on disk gives back.

        `o3d.io.write_point_cloud` answers False for a folder that is missing or an
        extension it does not know, and the old wrapper returned True whenever the call
        did not raise - so a run that wrote nothing still told the user which file to go
        and open. The count is taken from the written file, so the number is the file's.
        """
        name = os.path.basename(output_path)
        folder = os.path.dirname(os.path.abspath(output_path))
        if not os.path.isdir(folder):
            return None, f'{folder} is not a folder on this disk, so {name} cannot be written'
        if len(cloud.points) == 0:
            return None, f'{name} would hold no points, so there is nothing to write'
        extension = os.path.splitext(output_path)[1].lower()
        if extension == VERTEX_ONLY_OBJ:
            return self._write_vertex_obj(cloud, output_path)
        if extension not in WRITABLE_EXTENSIONS:
            return None, (f'a cloud cannot be written as {extension} here - Open3D answers '
                          f'{", ".join(WRITABLE_EXTENSIONS)}')
        if not PointCloudLoader.save(cloud, output_path):
            return None, f'{name} was not written'
        read_back, error = PointCloudLoader.read_report(output_path)
        if error:
            return None, f'{name} was written but reads back as nothing: {error}'
        return len(read_back.points), None

    @staticmethod
    def _write_vertex_obj(cloud: Any, output_path: str) -> Tuple[Optional[int], Optional[str]]:
        """A vertex-only .obj: the one way a cloud leaves for a tool that only opens Wavefront.

        Open3D writes no .obj for a cloud, and this app's mesh reader refuses a file with
        no faces by design, so the verdict that comes back says the file is for the other
        software and counts the `v` lines it actually wrote.
        """
        name = os.path.basename(output_path)
        points = np.asarray(cloud.points, dtype=float)
        try:
            with open(output_path, 'w', encoding='utf-8', newline='\n') as handle:
                handle.write('# RenderFox point cloud - positions only, no faces\n')
                for row in points:
                    handle.write('v %.6f %.6f %.6f\n' % (row[0], row[1], row[2]))
        except OSError as error:
            return None, f'{name} was not written: {error}'
        with open(output_path, encoding='utf-8') as handle:
            written = handle.read().splitlines()
        counted = [line for line in written if line.startswith('v ')]
        if len(counted) != len(points):
            return None, f'{name} holds {len(counted)} vertex lines, not the {len(points)} ' \
                         f'points this cloud has'
        return len(counted), None

    def write_surface(self, mesh: Any, output_path: str,
                      should_cancel=None) -> Tuple[Optional[int], Optional[int], Optional[str]]:
        """An open3d surface out through the app's own mesh writer, counted from the file.

        Reconstruction used to call `o3d.io.write_triangle_mesh` and report success
        whatever it answered, counting the vertices of the object still in memory. Now
        `FormatConverter` - the writer every other pane reads through - makes the file,
        and the vertex and face counts come off reading it back, so a surface no pane here
        can open is never reported as a result.
        """
        if len(mesh.triangles) == 0:
            return None, None, ('the surface this produced has no faces at all, so nothing '
                                'here could open it as a mesh - it was not written')
        if self._cancelled(should_cancel):
            return None, None, None
        import trimesh
        from .format_converter import FormatConverter
        built = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=float),
                                faces=np.asarray(mesh.triangles, dtype=np.int64),
                                process=False)
        if mesh.has_vertex_colors():
            built.visual.vertex_colors = (np.asarray(mesh.vertex_colors) * 255).astype(np.uint8)
        ok, message = FormatConverter().write_mesh(built, output_path)
        if not ok:
            return None, None, message
        read_back, opened_with = FormatConverter().read_mesh(output_path)
        if read_back is None:
            return None, None, f'{os.path.basename(output_path)} was written but cannot be ' \
                              f'opened again here: {opened_with}'
        return len(read_back.vertices), len(read_back.faces), None

    # ---- the verbs -------------------------------------------------------------

    def op_analyze(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        if not path:
            return self._refuse('analyze', 'no file was named to measure')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('analyze', error)
        stats = self.analyzer.analyze(cloud)
        return self._accepted(
            'analyze', points_before=stats.point_count, points_after=stats.point_count,
            measure={'statistics': stats.to_dict(), 'bytes': os.path.getsize(path)})

    def op_center(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('center', error)
        before = len(cloud.points)
        output_path = self.target_path(params, path, 'centered')
        offset = self.transformer.centered(cloud)
        written, error = self.write_points(cloud, output_path)
        if error:
            return self._refuse('center', error, output_path=output_path)
        return self._accepted('center', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'moved_by': [float(v) for v in offset]})

    def op_normalize(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('normalize', error)
        before = len(cloud.points)
        output_path = self.target_path(params, path, 'normalized')
        factor = self.transformer.to_unit_extent(cloud)
        written, error = self.write_points(cloud, output_path)
        if error:
            return self._refuse('normalize', error, output_path=output_path)
        return self._accepted('normalize', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'scale': factor})

    def op_dedup(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('dedup', error)
        before = len(cloud.points)
        output_path = self.target_path(params, path, 'deduped')
        kept = self.filter.remove_duplicated(cloud)
        written, error = self.write_points(kept, output_path)
        if error:
            return self._refuse('dedup', error, output_path=output_path)
        return self._accepted('dedup', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'removed': before - written})

    def op_voxel(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('voxel', error)
        before = len(cloud.points)
        voxel = float(params.get('voxel_size', 0.05))
        if voxel <= 0.0:
            return self._refuse('voxel', f'a voxel edge of {voxel} is not a length',
                                measure={'voxel_size': voxel})
        output_path = self.target_path(params, path, 'downsampled')
        kept = self.filter.voxel_downsample(cloud, voxel)
        written, error = self.write_points(kept, output_path)
        if error:
            return self._refuse('voxel', error, output_path=output_path)
        return self._accepted('voxel', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'voxel_size': voxel,
                                       'removed': before - written,
                                       'reduction': (before - written) / before * 100.0})

    def op_uniform(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('uniform', error)
        before = len(cloud.points)
        step = int(params.get('every_k', 5))
        if step < 2:
            return self._refuse('uniform',
                                f'keeping every {step}-th point keeps them all, which is not '
                                f'a reduction', measure={'every_k': step})
        output_path = self.target_path(params, path, 'uniform')
        kept = self.filter.uniform_downsample(cloud, step)
        written, error = self.write_points(kept, output_path)
        if error:
            return self._refuse('uniform', error, output_path=output_path)
        return self._accepted('uniform', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'every_k': step, 'removed': before - written})

    def _outliers(self, operation, params, kind):
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse(operation, error)
        before = len(cloud.points)
        output_path = self.target_path(
            params, path, 'filtered' if kind == 'statistical' else 'radius_filtered')
        if kind == 'statistical':
            kept = self.filter.statistical_outlier_removal(
                cloud, nb_neighbors=int(params.get('nb_neighbors', 20)),
                std_ratio=float(params.get('std_ratio', 2.0)))
            measure = {'nb_neighbors': int(params.get('nb_neighbors', 20)),
                       'std_ratio': float(params.get('std_ratio', 2.0))}
        else:
            kept = self.filter.radius_outlier_removal(
                cloud, nb_points=int(params.get('nb_points', 16)),
                radius=float(params.get('radius', 0.05)))
            measure = {'nb_points': int(params.get('nb_points', 16)),
                       'radius': float(params.get('radius', 0.05))}
        written, error = self.write_points(kept, output_path)
        if error:
            return self._refuse(operation, error, output_path=output_path)
        measure['removed'] = before - written
        return self._accepted(operation, output_path=output_path, files=[output_path],
                              points_before=before, points_after=written, measure=measure)

    def op_outliers_statistical(self, params, should_cancel):
        return self._outliers('outliers_statistical', params, 'statistical')

    def op_outliers_radius(self, params, should_cancel):
        return self._outliers('outliers_radius', params, 'radius')

    def _transform(self, operation, params, apply_to, describe):
        """Move the cloud in space without changing its points, then write it back.

        The three verbs below differ only in what they ask of the file, so the read, the
        empty-result guard and the proof-of-write live here once.
        """
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse(operation, error)
        before = len(cloud.points)
        output_path = self.target_path(params, path, operation)
        try:
            measure = apply_to(cloud)
        except ValueError as problem:
            return self._refuse(operation, str(problem), output_path=output_path)
        if len(cloud.points) != before:
            return self._refuse(operation, f'{describe} changed the point count, which a '
                                          f'{operation} never does', output_path=output_path)
        written, error = self.write_points(cloud, output_path)
        if error:
            return self._refuse(operation, error, output_path=output_path,
                                points_before=before)
        return self._accepted(operation, output_path=output_path, files=[output_path],
                              points_before=before, points_after=written, measure=measure)

    def op_translate(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        try:
            # An axis the task does not name is not moved, which is what its parameter spec
            # promises (all three optional); a pane supplies all three and changes nothing.
            offset = [float(params.get(axis, 0.0)) for axis in ('dx', 'dy', 'dz')]
        except (TypeError, ValueError) as problem:
            return self._refuse('translate', f'dx, dy and dz each need a number: {problem}')
        if all(value == 0.0 for value in offset):
            return self._refuse('translate', 'moving by (0, 0, 0) leaves the cloud exactly '
                                            'where it is, so there is nothing to write')

        def apply_to(cloud):
            self.transformer.translate(cloud, offset)
            return {'offset': offset}

        return self._transform('translate', params, apply_to, 'the move')

    def op_rotate(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        try:
            angles = [float(params.get(axis, 0.0)) for axis in ('rx', 'ry', 'rz')]
        except (TypeError, ValueError) as problem:
            return self._refuse('rotate', f'rx, ry and rz each need an angle in degrees: '
                                         f'{problem}')
        if all(value == 0.0 for value in angles):
            return self._refuse('rotate', 'turning by (0, 0, 0) leaves the cloud exactly as '
                                         'it is, so there is nothing to write')

        def apply_to(cloud):
            self.transformer.rotate(cloud, angles)
            return {'degrees': angles}

        return self._transform('rotate', params, apply_to, 'the turn')

    def op_scale(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        try:
            factor = float(params['factor'])
        except (KeyError, TypeError, ValueError) as problem:
            return self._refuse('scale', f'the scale needs one number: {problem}')
        if factor <= 0.0:
            return self._refuse('scale', f'a scale of {factor} would flatten the cloud to '
                                        f'nothing - use a number above zero')
        if factor == 1.0:
            return self._refuse('scale', 'a scale of 1 leaves every point where it is, so '
                                        'there is nothing to write')

        def apply_to(cloud):
            before_center = np.asarray(cloud.get_center(), dtype=float)
            self.transformer.scale(cloud, factor)
            extent = np.asarray(
                cloud.get_axis_aligned_bounding_box().get_extent(), dtype=float)
            if np.any(extent == 0.0):
                raise ValueError('this cloud is flat on an axis, so scaling it cannot be '
                                 'measured on that axis')
            return {'factor': factor,
                    'centre': [float(v) for v in before_center],
                    'extent': [float(v) for v in extent]}

        return self._transform('scale', params, apply_to, 'the scale')

    def op_crop(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('crop', error)
        before = len(cloud.points)
        try:
            min_bound = [float(v) for v in params['min_bound']]
            max_bound = [float(v) for v in params['max_bound']]
        except (KeyError, TypeError, ValueError) as problem:
            return self._refuse('crop', f'the box needs a min_bound and a max_bound of three '
                                        f'numbers each: {problem}')
        if len(min_bound) != 3 or len(max_bound) != 3:
            return self._refuse('crop', 'a box is three axes: min_bound and max_bound each '
                                        'need exactly 3 numbers')
        if any(high <= low for low, high in zip(min_bound, max_bound)):
            return self._refuse('crop', 'every edge of the box has to run from a smaller '
                                       'number to a bigger one')
        output_path = self.target_path(params, path, 'cropped')
        kept = self.filter.crop_box(cloud, min_bound, max_bound)
        written, error = self.write_points(kept, output_path)
        if error:
            return self._refuse('crop', error, output_path=output_path,
                                points_before=before)
        return self._accepted('crop', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'min_bound': min_bound, 'max_bound': max_bound,
                                       'removed': before - written})

    def op_normals(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('normals', error)
        before = len(cloud.points)
        knn = int(params.get('knn', 30))
        if knn > before:
            # open3d answers a neighbourhood larger than the cloud by quietly using every
            # point it has, so the number typed would not be the number used. The cloud's
            # size is the thing the user cannot see from a scan, so it is said out loud.
            return self._refuse('normals', f'{knn} neighbours needs a cloud of at least '
                                           f'{knn} points and this one has {before}')
        output_path = self.target_path(params, path, 'normals')
        self.normal_estimator.estimate_normals(cloud, search_param_knn=knn)
        written, error = self.write_points(cloud, output_path)
        if error:
            return self._refuse('normals', error, output_path=output_path)
        read_back, error = PointCloudLoader.read_report(output_path)
        if not read_back.has_normals():
            return self._refuse('normals', f'{os.path.basename(output_path)} was written '
                                           'without any normals on it',
                                output_path=output_path)
        return self._accepted('normals', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'knn': knn})

    def op_planes(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('planes', error)
        before = len(cloud.points)
        plane_path = self.target_path(params, path, 'plane')
        rest_path = self.target_path(params, path, 'off_plane')
        inliers, outliers, equation = self.segmenter.plane_segmentation(
            cloud, distance_threshold=float(params.get('distance_threshold', 0.01)),
            ransac_n=int(params.get('ransac_n', 3)),
            num_iterations=int(params.get('num_iterations', 1000)))
        on_plane, error = self.write_points(inliers, plane_path)
        if error:
            return self._refuse('planes', error, points_before=before)
        if self._cancelled(should_cancel):
            return self._refuse('planes', f'the run was stopped after the plane was written '
                                         f'to {os.path.basename(plane_path)}', stopped=True,
                                output_path=plane_path, files=[plane_path],
                                points_after=on_plane)
        off_plane, error = self.write_points(outliers, rest_path)
        if error:
            return self._refuse('planes', error, output_path=plane_path,
                                files=[plane_path], points_after=on_plane)
        return self._accepted('planes', output_path=plane_path,
                              files=[plane_path, rest_path], points_before=before,
                              points_after=on_plane + off_plane,
                              measure={'plane_equation': list(equation),
                                       'on_plane': on_plane, 'off_plane': off_plane,
                                       'distance_threshold': float(
                                           params.get('distance_threshold', 0.01)),
                                       'num_iterations': int(params.get('num_iterations', 1000))})

    def op_cluster(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('cluster', error)
        before = len(cloud.points)
        eps = float(params.get('eps', 0.02))
        min_points = int(params.get('min_points', 10))
        output_path = self.target_path(params, path, 'clustered')
        labels = self.segmenter.dbscan_clustering(cloud, eps=eps, min_points=min_points)
        if len(labels) == 0:
            return self._refuse('cluster', 'the clustering returned a label for no point at all')
        clusters = int(len(set(int(v) for v in labels if v >= 0)))
        noise = int(np.count_nonzero(labels < 0))
        if clusters == 0:
            # Nothing met the density test. Writing an all-black cloud and calling it a
            # result would be a claim; the numbers say what happened instead.
            return self._refuse('cluster',
                                f'no group of {min_points} points sits within {eps:g} of each '
                                f'other, so all {before} points are noise - raise "Min Points" '
                                f'no further or widen Epsilon',
                                points_before=before,
                                measure={'eps': eps, 'min_points': min_points, 'noise': noise})
        colours = cluster_palette(clusters)
        paint = np.zeros((len(labels), 3))
        for index in range(clusters):
            paint[labels == index] = colours[index]
        paint[labels < 0] = 0.0
        cloud.colors = o3d.utility.Vector3dVector(paint)
        written, error = self.write_points(cloud, output_path)
        if error:
            return self._refuse('cluster', error, output_path=output_path)
        return self._accepted('cluster', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'clusters': clusters, 'noise': noise, 'eps': eps,
                                       'min_points': min_points})

    def op_hull(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('hull', error)
        extension = params.get('extension') or '.ply'
        output_path = self.target_path(params, path, 'hull', extension)
        mesh = self.reconstructor.convex_hull(cloud)
        vertices, faces, error = self.write_surface(mesh, output_path, should_cancel)
        if error:
            return self._refuse('hull', error, output_path=output_path)
        if vertices is None:
            return self._refuse('hull', 'the run was stopped before any surface was written',
                                stopped=True)
        return self._accepted('hull', output_path=output_path, files=[output_path],
                              points_before=len(cloud.points),
                              measure={'vertices': vertices, 'faces': faces})

    def _surface(self, operation, params, build, should_cancel):
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse(operation, error)
        extension = params.get('extension') or '.ply'
        output_path = self.target_path(params, path, operation, extension)
        mesh, densities = build(cloud)
        vertices, faces, error = self.write_surface(mesh, output_path, should_cancel)
        if error:
            return self._refuse(operation, error, output_path=output_path)
        if vertices is None:
            return self._refuse(operation, 'the run was stopped before any surface was '
                                           'written', stopped=True)
        return self._accepted(operation, output_path=output_path, files=[output_path],
                              points_before=len(cloud.points),
                              measure={'vertices': vertices, 'faces': faces})

    def op_poisson(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        def build(cloud):
            mesh, densities = self.reconstructor.poisson_reconstruction(
                cloud, depth=int(params.get('depth', 9)),
                width=float(params.get('width', 0)),
                scale=float(params.get('scale', 1.1)),
                linear_fit=bool(params.get('linear_fit', False)))
            if params.get('trim'):
                mesh = self.reconstructor.trim_by_density(mesh, densities)
            return mesh, densities
        return self._surface('poisson', params, build, should_cancel)

    def op_ball_pivoting(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        def build(cloud):
            radius = params.get('ball_radius')
            radii = None if not radius else [float(radius)]
            return self.reconstructor.ball_pivoting(cloud, radii), None
        return self._surface('ball_pivoting', params, build, should_cancel)

    def op_alpha_shape(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        def build(cloud):
            return self.reconstructor.alpha_shape(cloud, float(params.get('alpha', 0.03))), None
        return self._surface('alpha_shape', params, build, should_cancel)

    def op_features(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        source_path, target_path = params.get('source_path'), params.get('target_path')
        source, error = self.read_cloud(source_path)
        if error:
            return self._refuse('features', f'source: {error}')
        target, error = self.read_cloud(target_path)
        if error:
            return self._refuse('features', f'target: {error}')
        voxel = params.get('voxel_size')
        if voxel in (None, 0, 0.0):
            voxel = self.registration.average_spacing(source) * 1.5
        prepared = self.registration.features(source, target, float(voxel))
        self.prepared = {'source_path': source_path, 'target_path': target_path,
                         'voxel_size': prepared['voxel_size']}
        ready = {key: value for key, value in prepared.items() if not key.startswith('_')}
        return self._accepted('features', measure=ready)

    def _register(self, operation, params, method, should_cancel):
        source_path, target_path = params.get('source_path'), params.get('target_path')
        source, error = self.read_cloud(source_path)
        if error:
            return self._refuse(operation, f'source: {error}')
        target, error = self.read_cloud(target_path)
        if error:
            return self._refuse(operation, f'target: {error}')
        if method == 'icp':
            result = self.registration.icp_registration(
                source, target, threshold=float(params.get('threshold', 0.02)),
                max_iteration=int(params.get('max_iteration', 100)))
        else:
            voxel = params.get('voxel_size')
            if not voxel and self.prepared and self.prepared.get('source_path') == source_path \
                    and self.prepared.get('target_path') == target_path:
                voxel = self.prepared['voxel_size']
            if not voxel:
                voxel = self.registration.average_spacing(source) * 1.5
            result = self.registration.ransac_registration(source, target, float(voxel))
        output_path = self.target_path(params, source_path, operation)
        if self._cancelled(should_cancel):
            return self._refuse(operation, 'stopped before the aligned cloud was written',
                                stopped=True, measure={
                                    k: v for k, v in result.items()
                                    if k != 'transformation'})
        source.transform(result['transformation'])
        written, error = self.write_points(source, output_path)
        if error:
            return self._refuse(operation, error, output_path=output_path)
        measure = {key: value for key, value in result.items() if key != 'transformation'}
        measure['transformation'] = np.asarray(result['transformation']).tolist()
        return self._accepted(operation, output_path=output_path, files=[output_path],
                              points_after=written, measure=measure)

    def op_register_icp(self, params, should_cancel):
        return self._register('register_icp', params, 'icp', should_cancel)

    def op_register_ransac(self, params, should_cancel):
        return self._register('register_ransac', params, 'ransac', should_cancel)

    def op_distances(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('distances', error)
        distances = np.asarray(cloud.compute_nearest_neighbor_distance())
        if len(distances) == 0:
            return self._refuse('distances', 'one point has no neighbour to measure to')
        counts, edges = np.histogram(distances, bins=10)
        return self._accepted('distances', points_before=len(cloud.points),
                              measure={'samples': int(len(distances)),
                                       'minimum': float(distances.min()),
                                       'average': float(distances.mean()),
                                       'maximum': float(distances.max()),
                                       'histogram': {'counts': [int(c) for c in counts],
                                                     'edges': [float(e) for e in edges]}})

    def op_export(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('export', error)
        output_path = params.get('output_path')
        if not output_path and params.get('output_dir'):
            output_path = self.target_path(params, path, 'export', params.get('extension'))
        if not output_path:
            return self._refuse('export', 'no file name was given to export to')
        before = len(cloud.points)
        written, error = self.write_points(cloud, output_path)
        if error:
            return self._refuse('export', error, output_path=output_path)
        extension = os.path.splitext(output_path)[1].lower()
        return self._accepted('export', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'extension': extension,
                                       'readable_here': extension != VERTEX_ONLY_OBJ})

    def op_pick(self, params: Dict[str, Any], should_cancel) -> Dict[str, Any]:
        """Select points in an Open3D window and write what was picked.

        The window belongs to Open3D, not to Qt, so it runs on the pane's worker and the
        Qt UI stays alive while it is open. `VisualizerWithEditing` crops nothing by itself
        and writes nothing itself - it only remembers the points the user clicked - so the
        file is written from those indices here, and the pane's instructions say the same.
        """
        path = params.get('file_path')
        cloud, error = self.read_cloud(path)
        if error:
            return self._refuse('pick', error)
        if not OPEN3D_AVAILABLE:
            return self._refuse('pick', 'Open3D is not installed here, so no selection '
                                        'window can be opened')
        if self._cancelled(should_cancel):
            return self._refuse('pick', 'stopped before the window opened', stopped=True)
        before = len(cloud.points)
        vis = o3d.visualization.VisualizerWithEditing()
        try:
            vis.create_window(window_name='RenderFox - click the points to keep',
                              width=1024, height=768, visible=True)
            vis.add_geometry(cloud)
            vis.run()
            indices = list(vis.get_picked_points())
        except Exception as problem:
            return self._refuse('pick', f'the selection window could not be opened on this '
                                        f'machine: {problem}')
        finally:
            try:
                vis.destroy_window()
            except Exception:
                pass
        if not indices:
            return self._refuse('pick', 'no point was picked, so there is nothing to write - '
                                        'the window was closed with an empty selection')
        if self._cancelled(should_cancel):
            return self._refuse('pick', f'the run was stopped after {len(indices)} points '
                                        f'were picked, before any file was written',
                                stopped=True, points_before=before)
        selected = cloud.select_by_index(np.asarray(indices, dtype=int))
        output_path = self.target_path(params, path, 'selected')
        written, error = self.write_points(selected, output_path)
        if error:
            return self._refuse('pick', error, output_path=output_path, points_before=before)
        return self._accepted('pick', output_path=output_path, files=[output_path],
                              points_before=before, points_after=written,
                              measure={'picked': len(indices)})

    # ---- the door the pane and the automation launcher both come through --------

    def run(self, operation: str, params: Optional[Dict[str, Any]] = None,
            should_cancel=None) -> Dict[str, Any]:
        """Answer one verb with one verdict. Never raises.

        Every path out of here is a dict with `success`, `stopped` and either an
        `output_path` the file is really at or an `error` that says why there is none. The
        pane's worker posts that dict straight to the handler, so a raise in the middle of
        an operation would leave a modal dialog waiting for a verdict that never comes.
        """
        params = dict(params or {})
        if operation not in self.OPERATIONS:
            return self._refuse(operation, f"nothing here answers to '{operation}' - the "
                                           f"verbs are {', '.join(self.OPERATIONS)}")
        handler = getattr(self, f'op_{operation}')
        if self._cancelled(should_cancel):
            return self._refuse(operation, 'stopped before it started, so nothing was written',
                                stopped=True)
        try:
            verdict = handler(params, should_cancel)
        except Exception as problem:
            return self._refuse(operation, f'{operation} did not finish: '
                                           f'{type(problem).__name__}: {problem}')
        verdict['operation'] = operation
        verdict.setdefault('stopped', False)
        if verdict.get('success') and verdict.get('error'):
            # A result cannot both be a result and say what went wrong.
            verdict['success'] = False
        return verdict
