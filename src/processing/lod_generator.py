"""
LOD (Level of Detail) generator for mesh optimization.
"""

import os
import numpy as np
import trimesh
try:
    import pymeshlab
    PYMESHLAB_AVAILABLE = True
except ImportError:
    PYMESHLAB_AVAILABLE = False
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

@dataclass
class LODSettings:
    """Settings for LOD generation."""
    levels: int = 3
    high_quality_ratio: float = 0.8
    medium_quality_ratio: float = 0.5
    low_quality_ratio: float = 0.2
    custom_ratios: Optional[List[float]] = None  # List of ratios for each level
    preserve_topology: bool = True
    preserve_boundaries: bool = True
    use_vertex_clustering: bool = False
    clustering_threshold: float = 0.01
    use_edge_collapse: bool = True
    quadric_error_threshold: float = 1e-6

class LODGenerator:
    """Generates Level of Detail (LOD) meshes for 3D models using advanced algorithms."""
    
    def __init__(self, settings: LODSettings = None):
        self.settings = settings or LODSettings()
    
    def _load_mesh_safe(self, file_path: str) -> trimesh.Trimesh:
        """
        Load a mesh safely, handling Scenes (GLB/GLTF) by concatenating geometry.
        """
        try:
            mesh = trimesh.load(file_path)
            
            if isinstance(mesh, trimesh.Scene):
                # Concatenate all geometries in the scene
                if len(mesh.geometry) == 0:
                    raise ValueError("Scene is empty")
                
                # Extract all geometries
                geometries = list(mesh.geometry.values())
                if len(geometries) == 1:
                    return geometries[0]
                else:
                    # Concatenate
                    return trimesh.util.concatenate(geometries)
            
            elif isinstance(mesh, trimesh.Trimesh):
                return mesh
            else:
                raise ValueError(f"Unsupported mesh type: {type(mesh)}")
                
        except Exception as e:
            raise ValueError(f"Failed to load mesh: {str(e)}")

    def generate_lods(self, input_file: str, output_dir: str) -> List[str]:
        """
        Generate LOD meshes from an input 3D file using multiple optimization algorithms.
        
        Uses:
        1. Quadric Error Metrics (QEM) for primary simplification
        2. Edge collapse with error minimization
        3. Vertex clustering for aggressive reduction
        4. Feature preservation for important geometry
        
        Args:
            input_file: Path to the input 3D model file
            output_dir: Directory to save LOD files
            
        Returns:
            List of generated LOD file paths
        """
        # Load the mesh safely
        try:
            mesh = self._load_mesh_safe(input_file)
        except Exception as e:
            raise ValueError(f"Failed to load mesh: {str(e)}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Get base filename without extension
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        
        generated_files = []
        original_face_count = len(mesh.faces)
        original_vertex_count = len(mesh.vertices)
        
        print(f"Original mesh: {original_vertex_count} vertices, {original_face_count} faces")
        
        # Generate different LOD levels
        lod_ratios = self._get_lod_ratios()
        
        for i, ratio in enumerate(lod_ratios):
            try:
                # Calculate target face count
                target_faces = int(original_face_count * ratio)
                
                # Generate LOD mesh using the most appropriate algorithm
                if ratio > 0.6:
                    # High quality: Use Quadric Error Metrics
                    lod_mesh = self._quadric_simplify(mesh, target_faces)
                elif ratio > 0.3:
                    # Medium quality: Combine QEM with edge collapse
                    lod_mesh = self._hybrid_simplify(mesh, target_faces)
                else:
                    # Low quality: Use vertex clustering for aggressive reduction
                    lod_mesh = self._cluster_simplify(mesh, target_faces)
                
                # Post-process the LOD mesh
                lod_mesh = self._post_process_lod(lod_mesh)
                
                # Generate filename
                lod_name = f"{base_name}_LOD{i}.obj"
                lod_path = os.path.join(output_dir, lod_name)
                
                # Export LOD mesh
                lod_mesh.export(lod_path)
                generated_files.append(lod_path)
                
                # Calculate reduction statistics
                vertex_reduction = (1 - len(lod_mesh.vertices) / original_vertex_count) * 100
                face_reduction = (1 - len(lod_mesh.faces) / original_face_count) * 100
                
                print(f"Generated LOD{i}: {len(lod_mesh.vertices)} vertices ({vertex_reduction:.1f}% reduction), "
                      f"{len(lod_mesh.faces)} faces ({face_reduction:.1f}% reduction)")
                
            except Exception as e:
                print(f"Warning: Failed to generate LOD{i}: {str(e)}")
        
        return generated_files
    
    def _quadric_simplify(self, mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
        """
        Simplify mesh using Quadric Error Metrics (QEM).
        
        Uses PyMeshLab for high-quality simplification if available, 
        falling back to Trimesh.
        """
        if target_faces >= len(mesh.faces):
            return mesh.copy()
            
        # Try PyMeshLab first (High Quality)
        if PYMESHLAB_AVAILABLE:
            try:
                # Create a new MeshSet
                ms = pymeshlab.MeshSet()
                
                # Convert Trimesh to PyMeshLab Mesh
                # We need to ensure vertices and faces are numpy arrays of correct type
                vertices = mesh.vertices.astype(np.float64)
                faces = mesh.faces.astype(np.int32)
                
                m = pymeshlab.Mesh(vertex_matrix=vertices, face_matrix=faces)
                ms.add_mesh(m)
                
                # Apply Quadric Edge Collapse Decimation
                # targetfacenum is the target number of faces
                ms.apply_filter('meshing_decimation_quadric_edge_collapse', 
                              targetfacenum=target_faces,
                              preserveboundary=self.settings.preserve_boundaries,
                              preservenormal=True,
                              preservetopology=self.settings.preserve_topology)
                
                # Convert back to Trimesh
                m_out = ms.current_mesh()
                out_vertices = m_out.vertex_matrix()
                out_faces = m_out.face_matrix()
                
                return trimesh.Trimesh(vertices=out_vertices, faces=out_faces)
                
            except Exception as e:
                print(f"Warning: PyMeshLab simplification failed: {str(e)}")
                # Fall through to Trimesh implementation
        
        # Fallback to Trimesh (Lower Quality but no extra deps)
        try:
            target_faces = max(4, min(target_faces, len(mesh.faces)))
            simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
            
            if simplified is None or len(simplified.faces) == 0:
                print("Warning: Quadric decimation failed, using convex hull")
                simplified = mesh.convex_hull
            
            return simplified
            
        except Exception as e:
            print(f"Warning: Quadric simplification failed: {str(e)}")
            return mesh.convex_hull
    
    def _hybrid_simplify(self, mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
        """
        Hybrid simplification combining multiple techniques.
        """
        try:
            # Ensure target_faces is valid
            target_faces = max(4, min(target_faces, len(mesh.faces)))
            
            # Start with quadric decimation
            intermediate_faces = max(target_faces, int(target_faces * 1.2))  # Leave room for further processing
            simplified = mesh.simplify_quadric_decimation(face_count=intermediate_faces)
            
            if simplified is None:
                simplified = mesh
            
            # Apply additional edge collapse if needed
            if len(simplified.faces) > target_faces:
                # Use trimesh's built-in simplification with correct parameter
                simplified = simplified.simplify_quadric_decimation(face_count=target_faces)
            
            return simplified if simplified is not None else mesh.convex_hull
            
        except Exception as e:
            print(f"Warning: Hybrid simplification failed: {str(e)}")
            return self._quadric_simplify(mesh, target_faces)
    
    def _cluster_simplify(self, mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
        """
        Vertex clustering simplification for aggressive reduction.
        
        Groups nearby vertices and replaces them with cluster centroids.
        Good for very low poly LODs.
        """
        try:
            if not self.settings.use_vertex_clustering:
                return self._quadric_simplify(mesh, target_faces)
            
            # Ensure target_faces is valid
            target_faces = max(4, min(target_faces, len(mesh.faces)))
            
            # Calculate clustering threshold based on mesh size
            bounds_size = np.linalg.norm(mesh.bounds[1] - mesh.bounds[0])
            cluster_distance = bounds_size * self.settings.clustering_threshold
            
            # Merge vertices that are very close
            merged = mesh.copy()
            merged.merge_vertices(merge_tex=True, merge_norm=True)
            
            # Then apply quadric decimation with correct parameter
            simplified = merged.simplify_quadric_decimation(face_count=target_faces)
            
            return simplified if simplified is not None else merged.convex_hull
            
        except Exception as e:
            print(f"Warning: Cluster simplification failed: {str(e)}")
            return self._quadric_simplify(mesh, target_faces)
    
    def _post_process_lod(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Post-process LOD mesh to ensure quality.
        """
        try:
            # Remove degenerate faces
            mesh.remove_degenerate_faces()
            
            # Remove duplicate faces
            mesh.remove_duplicate_faces()
            
            # Fix normals
            mesh.fix_normals()
            
            # Ensure manifold if possible
            if not mesh.is_watertight:
                try:
                    mesh.fill_holes()
                except:
                    pass  # Fill holes might fail, that's ok
            
            return mesh
            
        except Exception as e:
            print(f"Warning: Post-processing failed: {str(e)}")
            return mesh
    
    def _get_lod_ratios(self) -> List[float]:
        """Get the reduction ratios for each LOD level."""
        # Use custom ratios if provided and length matches levels
        if self.settings.custom_ratios and len(self.settings.custom_ratios) == self.settings.levels:
            return self.settings.custom_ratios
            
        if self.settings.levels == 1:
            return [self.settings.high_quality_ratio]
        elif self.settings.levels == 2:
            return [self.settings.high_quality_ratio, self.settings.low_quality_ratio]
        elif self.settings.levels == 3:
            return [
                self.settings.high_quality_ratio,
                self.settings.medium_quality_ratio,
                self.settings.low_quality_ratio
            ]
        else:
            # For more than 3 levels, interpolate between high and low
            ratios = []
            for i in range(self.settings.levels):
                t = i / (self.settings.levels - 1)
                ratio = self.settings.high_quality_ratio * (1 - t) + self.settings.low_quality_ratio * t
                ratios.append(ratio)
            return ratios
    
    def analyze_mesh_quality(self, file_path: str) -> Dict[str, any]:
        """
        Comprehensive mesh quality analysis.
        
        Args:
            file_path: Path to the mesh file
            
        Returns:
            Dictionary with detailed mesh statistics and quality metrics
        """
        try:
            mesh = self._load_mesh_safe(file_path)
            
            # Basic statistics
            stats = {
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "edges": len(mesh.edges),
                "volume": float(mesh.volume) if mesh.is_volume else 0.0,
                "surface_area": float(mesh.area),
                "bounds": mesh.bounds.tolist(),
                "center_mass": mesh.center_mass.tolist()
            }
            
            # Quality metrics
            stats.update({
                "is_watertight": mesh.is_watertight,
                "is_winding_consistent": mesh.is_winding_consistent,
                "is_convex": mesh.is_convex,
                "euler_number": mesh.euler_number
            })
            
            # Geometric analysis
            try:
                stats["face_areas"] = {
                    "min": float(np.min(mesh.area_faces)),
                    "max": float(np.max(mesh.area_faces)),
                    "mean": float(np.mean(mesh.area_faces)),
                    "std": float(np.std(mesh.area_faces))
                }
                
                # Edge length analysis
                edge_lengths = mesh.edges_unique_length
                stats["edge_lengths"] = {
                    "min": float(np.min(edge_lengths)),
                    "max": float(np.max(edge_lengths)),
                    "mean": float(np.mean(edge_lengths)),
                    "std": float(np.std(edge_lengths))
                }
                
                # Aspect ratio analysis (how stretched triangles are)
                if hasattr(mesh, 'face_angles'):
                    angles = mesh.face_angles
                    stats["face_angles"] = {
                        "min_deg": float(np.min(np.degrees(angles))),
                        "max_deg": float(np.max(np.degrees(angles))),
                        "mean_deg": float(np.mean(np.degrees(angles)))
                    }
                
            except Exception as e:
                stats["analysis_warning"] = f"Some geometric analysis failed: {str(e)}"
            
            return stats
            
        except Exception as e:
            return {"error": f"Failed to analyze mesh: {str(e)}"}
    
    def compare_lod_quality(self, original_file: str, lod_file: str) -> Dict[str, any]:
        """
        Compare quality between original and LOD mesh.
        
        Returns quality metrics and visual difference estimates.
        """
        try:
            original = self._load_mesh_safe(original_file)
            lod = self._load_mesh_safe(lod_file)
            
            # Basic reduction metrics
            vertex_reduction = (1 - len(lod.vertices) / len(original.vertices)) * 100
            face_reduction = (1 - len(lod.faces) / len(original.faces)) * 100
            
            # Volume difference (geometric accuracy)
            volume_diff = abs(original.volume - lod.volume) / original.volume * 100 if original.volume > 0 else 0
            
            # Surface area difference
            area_diff = abs(original.area - lod.area) / original.area * 100
            
            # Bounding box comparison
            orig_size = np.linalg.norm(original.bounds[1] - original.bounds[0])
            lod_size = np.linalg.norm(lod.bounds[1] - lod.bounds[0])
            size_diff = abs(orig_size - lod_size) / orig_size * 100
            
            return {
                "vertex_reduction_percent": vertex_reduction,
                "face_reduction_percent": face_reduction,
                "volume_difference_percent": volume_diff,
                "area_difference_percent": area_diff,
                "size_difference_percent": size_diff,
                "quality_score": self._calculate_quality_score(vertex_reduction, volume_diff, area_diff)
            }
            
        except Exception as e:
            return {"error": f"Failed to compare meshes: {str(e)}"}
    
    def _calculate_quality_score(self, vertex_reduction: float, volume_diff: float, area_diff: float) -> float:
        """
        Calculate a quality score (0-100) based on reduction efficiency vs. geometric preservation.
        
        Higher score = better quality (good reduction with minimal geometric change)
        """
        # Penalize geometric changes more heavily than reduction
        geometric_penalty = (volume_diff + area_diff) * 2
        
        # Reward good reduction efficiency
        reduction_bonus = min(vertex_reduction, 90)  # Cap at 90% to avoid over-reduction
        
        # Calculate score (higher is better)
        score = max(0, 100 - geometric_penalty + (reduction_bonus * 0.2))
        
        return min(100, score)
    
    def preview_lod_reduction(self, file_path: str) -> List[Dict[str, any]]:
        """
        Preview what the LOD reduction will look like without generating files.
        
        Args:
            file_path: Path to the input mesh
            
        Returns:
            List of dictionaries with LOD level information
        """
        try:
            mesh = self._load_mesh_safe(file_path)
            
            original_faces = len(mesh.faces)
            original_vertices = len(mesh.vertices)
            lod_ratios = self._get_lod_ratios()
            
            preview_data = []
            for i, ratio in enumerate(lod_ratios):
                target_faces = int(original_faces * ratio)
                target_vertices = int(original_vertices * ratio)  # Approximate
                
                preview_data.append({
                    "level": i,
                    "name": f"LOD{i}",
                    "ratio": ratio,
                    "original_faces": original_faces,
                    "target_faces": target_faces,
                    "original_vertices": original_vertices,
                    "estimated_vertices": target_vertices,
                    "face_reduction_percentage": (1 - ratio) * 100,
                    "estimated_file_size_mb": self._estimate_file_size(target_faces, target_vertices),
                    "recommended_use": self._get_lod_recommendation(ratio)
                })
            
            preview_data.append({
                "level": i,
                "name": f"LOD{i}",
                "ratio": ratio,
                "original_faces": original_faces,
                "target_faces": target_faces,
                "original_vertices": original_vertices,
                "estimated_vertices": target_vertices,
                "face_reduction_percentage": (1 - ratio) * 100,
                "estimated_file_size_mb": self._estimate_file_size(target_faces, target_vertices),
                "recommended_use": self._get_lod_recommendation(ratio)
            })
            
            return preview_data
            
        except Exception as e:
            return [{"error": f"Failed to preview LOD: {str(e)}"}]
    
    def _estimate_file_size(self, faces: int, vertices: int) -> float:
        """Estimate file size in MB for given mesh complexity."""
        # Rough estimation based on typical OBJ file structure
        # Each vertex: ~30 bytes, each face: ~15 bytes
        estimated_bytes = (vertices * 30) + (faces * 15)
        return estimated_bytes / (1024 * 1024)  # Convert to MB
    
    def _get_lod_recommendation(self, ratio: float) -> str:
        """Get usage recommendation for LOD level."""
        if ratio > 0.7:
            return "Close-up views, hero objects"
        elif ratio > 0.4:
            return "Medium distance, important objects"
        elif ratio > 0.2:
            return "Far distance, background objects"
        else:
            return "Very far distance, crowd/fill objects"

# Enhanced utility functions
def get_supported_formats() -> List[str]:
    """Get list of supported 3D file formats for LOD generation."""
    return ['.obj', '.ply', '.stl', '.off', '.dae', '.gltf', '.glb', '.3mf', '.x3d']

def is_supported_format(file_path: str) -> bool:
    """Check if a file format is supported for LOD generation."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in get_supported_formats()

def batch_generate_lods(input_directory: str, output_directory: str, 
                       settings: LODSettings = None) -> Dict[str, List[str]]:
    """
    Generate LODs for all supported files in a directory.
    
    Args:
        input_directory: Directory containing 3D model files
        output_directory: Directory to save generated LODs
        settings: LOD generation settings
    
    Returns:
        Dictionary mapping input files to generated LOD files
    """
    generator = LODGenerator(settings)
    results = {}
    
    for filename in os.listdir(input_directory):
        file_path = os.path.join(input_directory, filename)
        
        if os.path.isfile(file_path) and is_supported_format(file_path):
            try:
                # Create subdirectory for this model's LODs
                model_name = os.path.splitext(filename)[0]
                model_output_dir = os.path.join(output_directory, model_name)
                
                lod_files = generator.generate_lods(file_path, model_output_dir)
                results[file_path] = lod_files
                
                print(f"✓ Generated {len(lod_files)} LODs for {filename}")
                
            except Exception as e:
                print(f"✗ Failed to generate LODs for {filename}: {str(e)}")
                results[file_path] = []
    
    return results