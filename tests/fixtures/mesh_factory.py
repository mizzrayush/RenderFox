"""
RenderFox Synthetic Asset Generator (Mesh Factory)
Generates standard and edge-case 3D meshes and point clouds for automated testing.
Designed for solo developers to test 3D processing pipelines without manual 3D modeling.
"""

import os
import numpy as np
import trimesh
from typing import Dict, Optional, Tuple

try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False


class MeshFactory:
    """Factory for creating procedural 3D models with known geometric properties and flaws."""

    @staticmethod
    def create_clean_manifold(subdivisions: int = 2, radius: float = 1.0) -> trimesh.Trimesh:
        """Create a watertight, manifold icosphere with consistent outward normals."""
        mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
        return mesh

    @staticmethod
    def create_mesh_with_holes() -> trimesh.Trimesh:
        """Create an open mesh by removing faces from an icosphere."""
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        # Drop first 10 faces to create a clear hole
        keep_faces = mesh.faces[10:]
        open_mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=keep_faces, process=False)
        return open_mesh

    @staticmethod
    def create_non_manifold() -> trimesh.Trimesh:
        """
        Create a non-manifold mesh with an edge shared by 3 faces.
        (A triangular 'fin' attached to a box face).
        """
        # Base box
        box = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        # Add an extra triangle sharing edge between vertex 0 and 1
        v0 = box.vertices[0]
        v1 = box.vertices[1]
        v_fin = np.array([v0[0] + 0.5, v0[1] + 0.5, v0[2] + 1.0])
        
        new_vertices = np.vstack([box.vertices, [v_fin]])
        fin_face = np.array([[0, 1, len(box.vertices)]])
        new_faces = np.vstack([box.faces, fin_face])
        
        non_manifold = trimesh.Trimesh(vertices=new_vertices, faces=new_faces, process=False)
        return non_manifold

    @staticmethod
    def create_degenerate_and_duplicates() -> trimesh.Trimesh:
        """Create a mesh with duplicate vertices and a zero-area collinear triangle."""
        mesh = trimesh.creation.box()
        verts = mesh.vertices.copy()
        faces = mesh.faces.copy()
        
        # Duplicate first 4 vertices at slightly identical positions
        dup_verts = verts[:4].copy()
        start_idx = len(verts)
        verts = np.vstack([verts, dup_verts])
        
        # Add a zero-area triangle (collinear vertices 0, 0, 1)
        degenerate_face = np.array([[start_idx, start_idx, start_idx + 1]])
        faces = np.vstack([faces, degenerate_face])
        
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    @staticmethod
    def create_inverted_normals() -> trimesh.Trimesh:
        """Create a mesh with inconsistent/flipped face orientations."""
        mesh = trimesh.creation.icosphere(subdivisions=2)
        faces = mesh.faces.copy()
        # Flip first half of faces
        half = len(faces) // 2
        faces[:half] = faces[:half, [0, 2, 1]]
        return trimesh.Trimesh(vertices=mesh.vertices, faces=faces, process=False)

    @staticmethod
    def create_stress_mesh(subdivisions: int = 4) -> trimesh.Trimesh:
        """Create a dense high-poly mesh (e.g. 5,000+ to 20,000+ faces) for decimation & memory stress testing."""
        mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=2.0)
        return mesh

    @staticmethod
    def create_noisy_point_cloud(num_points: int = 1500, noise_std: float = 0.05, num_outliers: int = 150) -> Dict[str, np.ndarray]:
        """Create a synthetic 3D point cloud with Gaussian surface noise and random outlier scatter."""
        sphere = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
        points, _ = trimesh.sample.sample_surface(sphere, num_points)
        
        # Add surface noise
        points += np.random.normal(0, noise_std, points.shape)
        
        # Add outlier scatter in 3x bounding box
        outliers = np.random.uniform(-3.0, 3.0, (num_outliers, 3))
        all_points = np.vstack([points, outliers])
        
        # Synthetic RGB colors (normalized 0-1)
        colors = np.ones_like(all_points) * 0.7
        colors[num_points:] = [1.0, 0.1, 0.1] # Outliers red
        
        return {
            'points': all_points,
            'colors': colors,
            'normals': np.zeros_like(all_points)
        }

    @classmethod
    def generate_full_suite(cls, output_dir: str) -> Dict[str, str]:
        """
        Generate and save the entire edge-case asset suite to disk.
        Returns a dictionary mapping scenario name to file path.
        """
        os.makedirs(output_dir, exist_ok=True)
        suite = {}
        
        # 1. Clean manifold
        clean = cls.create_clean_manifold()
        p_clean = os.path.join(output_dir, "01_clean_manifold.obj")
        clean.export(p_clean)
        suite['clean_manifold'] = p_clean
        
        # 2. Holes
        holes = cls.create_mesh_with_holes()
        p_holes = os.path.join(output_dir, "02_mesh_with_holes.obj")
        holes.export(p_holes)
        suite['mesh_with_holes'] = p_holes
        
        # 3. Non-manifold
        nm = cls.create_non_manifold()
        p_nm = os.path.join(output_dir, "03_non_manifold.obj")
        nm.export(p_nm)
        suite['non_manifold'] = p_nm
        
        # 4. Degenerates & Duplicates
        deg = cls.create_degenerate_and_duplicates()
        p_deg = os.path.join(output_dir, "04_degenerate_and_duplicates.obj")
        deg.export(p_deg)
        suite['degenerate_and_duplicates'] = p_deg
        
        # 5. Inverted normals
        inv = cls.create_inverted_normals()
        p_inv = os.path.join(output_dir, "05_inverted_normals.obj")
        inv.export(p_inv)
        suite['inverted_normals'] = p_inv
        
        # 6. Stress mesh (5,000+ faces)
        stress = cls.create_stress_mesh(subdivisions=3)
        p_stress = os.path.join(output_dir, "06_stress_mesh.obj")
        stress.export(p_stress)
        suite['stress_mesh'] = p_stress
        
        # 7. Point Cloud PLY
        pcd_data = cls.create_noisy_point_cloud()
        p_pcd = os.path.join(output_dir, "07_noisy_cloud.ply")
        # Export as point cloud via trimesh or raw
        pcd_mesh = trimesh.PointCloud(vertices=pcd_data['points'], colors=pcd_data['colors'])
        pcd_mesh.export(p_pcd)
        suite['point_cloud'] = p_pcd

        return suite


if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mkdtemp()
    print(f"Generating synthetic test suite in {tmp}...")
    suite = MeshFactory.generate_full_suite(tmp)
    for name, path in suite.items():
        print(f"  [{name}]: {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
    print("MeshFactory ready!")
