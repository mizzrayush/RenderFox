"""
LOD (Level of Detail) generator for mesh optimization.
"""

import os
import logging
import numpy as np
import trimesh
try:
    import pymeshlab
    PYMESHLAB_AVAILABLE = True
except ImportError:
    PYMESHLAB_AVAILABLE = False
import json
from typing import List, Tuple, Dict, Optional, Callable, Any
from dataclasses import dataclass

# The packaged build has no console (`RenderFox.spec`: console=False), so the root logger is the
# only reader of the simplification routes that quietly give up: each one below answers with a
# convex hull or an unprocessed mesh, and without this record nothing says the LOD is not the
# decimation it was asked for.
logger = logging.getLogger(__name__)

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
        """The file as one mesh, asked of the converter's reader.

        Delegated on purpose. This used to be a second loader that only trimesh could
        serve, while the format list below promised .fbx and .dae - neither of which
        trimesh can open - so every FBX job died here with "file_type 'fbx' not
        supported". One reader, one answer.
        """
        from .format_converter import FormatConverter
        mesh, carried = FormatConverter().read_mesh(file_path)
        if mesh is None:
            raise ValueError(f"Failed to load mesh: {carried}")
        return mesh

    def generate_lods(self, input_file: str, output_dir: str,
                      progress: Optional[Callable[[int, int, str], None]] = None,
                      should_cancel: Optional[Callable[[], bool]] = None) -> List[str]:
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
            progress: called as (levels_done, levels_total, sentence) after each level is
                on disk, so a caller can show a number that means files written
            should_cancel: asked before each level. Returning True stops the chain and
                the levels already written are still returned - a stopped run is a
                partial run, not a failure, and the caller can say how far it got.
            
        Returns:
            List of generated LOD file paths
        """
        # Load the mesh safely
        try:
            mesh = self._load_mesh_safe(input_file)
        except Exception as e:
            raise ValueError(f"Failed to load mesh: {str(e)}")
        
        os.makedirs(output_dir, exist_ok=True)
        self.errors = []
        
        # Get base filename without extension
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        
        generated_files = []
        original_face_count = len(mesh.faces)
        original_vertex_count = len(mesh.vertices)
        
        logger.info("Original mesh %s: %d vertices, %d faces",
                    base_name, original_vertex_count, original_face_count)
        
        # Generate different LOD levels
        lod_ratios = self._get_lod_ratios()
        
        for i, ratio in enumerate(lod_ratios):
            try:
                if should_cancel is not None and should_cancel():
                    break

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
                
                logger.info("Generated LOD%d: %d vertices (%.1f%% reduction), "
                            "%d faces (%.1f%% reduction)",
                            i, len(lod_mesh.vertices), vertex_reduction,
                            len(lod_mesh.faces), face_reduction)

                if progress is not None:
                    progress(len(generated_files), len(lod_ratios),
                             f"LOD{i} written - {len(lod_mesh.faces):,} faces "
                             f"({face_reduction:.1f}% off)")
                
            except Exception as e:
                self.errors.append(f"LOD{i} (ratio {ratio:.2f}): {e}")
                logger.warning("Failed to generate LOD%d: %s", i, e)
        
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
                logger.warning("PyMeshLab simplification failed, using Trimesh: %s", e)
                # Fall through to Trimesh implementation
        
        # Fallback to Trimesh (Lower Quality but no extra deps)
        try:
            target_faces = max(4, min(target_faces, len(mesh.faces)))
            simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
            
            if simplified is None or len(simplified.faces) == 0:
                logger.warning("Quadric decimation failed, using convex hull")
                simplified = mesh.convex_hull
            
            return simplified
            
        except Exception as e:
            logger.warning("Quadric simplification failed, using convex hull: %s", e)
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
            logger.warning("Hybrid simplification failed, using quadric route: %s", e)
            return self._quadric_simplify(mesh, target_faces)
    
    def _cluster_simplify(self, mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
        """
        Vertex clustering simplification for aggressive reduction.
        
        Groups nearby vertices and replaces them with cluster centroids.
        Good for very low poly LODs.
        """
        try:
            # Vertex clustering requested for this pass
            
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
            logger.warning("Cluster simplification failed, using quadric route: %s", e)
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
            logger.warning("Post-processing failed, the LOD is the raw simplification: %s", e)
            return mesh
    
    @property
    def lod_ratios(self) -> List[float]:
        """The fraction of the faces each level is aimed at, in level order.

        Public because a caller has to be able to say what it asked for before it reports
        what it got: the Pipeline's Generate LOD node names these numbers next to the face
        counts it measured off each written file, and a list it could not read would have to
        be re-derived by guessing at `_get_lod_ratios`'s branches.
        """
        return self._get_lod_ratios()

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
    """Formats a model here could be read from - asked of the converter, not hand-typed.

    The list used to name .dae, .x3d and .fbx beside the seven trimesh reads. Nothing
    could open those three through this module, so a picker built from it offered files
    that were always going to fail, and .x3d is not readable by any library here at all.
    """
    from .format_converter import FormatConverter
    return FormatConverter().readable_formats()

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
                
                logger.info("Generated %d LODs for %s", len(lod_files), filename)
                
            except Exception as e:
                logger.warning("Failed to generate LODs for %s: %s", filename, e)
                results[file_path] = []
    
    return results

def generate_engine_lod_group(
    input_file: str,
    output_dir: str,
    lod_levels: int = 4,
    reduction_curve: str = "exponential",
    engine: str = "unreal"
) -> Dict[str, Any]:
    """Generate engine-ready LOD group with standardized naming and JSON manifest.
    
    Creates:
      [ModelName]_LOD0.[ext], [ModelName]_LOD1.[ext], ...
      [ModelName]_lod_manifest.json
    """
    os.makedirs(output_dir, exist_ok=True)
    base_name, ext = os.path.splitext(os.path.basename(input_file))
    
    # Calculate reduction ratios
    lod_levels = max(1, min(int(lod_levels or 4), 8))
    if reduction_curve == "linear":
        ratios = [max(0.05, 1.0 - (i / max(1, lod_levels))) for i in range(lod_levels)]
    elif reduction_curve == "half":
        ratios = [max(0.05, 1.0 / (2 ** i)) for i in range(lod_levels)]
    else:
        ratios = [max(0.05, 0.5 ** (i * 0.75)) for i in range(lod_levels)]
    ratios[0] = 1.0
    
    settings = LODSettings(levels=len(ratios), custom_ratios=ratios)
    generator = LODGenerator(settings)
    generated = generator.generate_lods(input_file, output_dir)
    
    renamed = []
    level_info = []
    for i, file_path in enumerate(generated):
        target_name = f"{base_name}_LOD{i}{ext}"
        target_path = os.path.join(output_dir, target_name)
        if file_path != target_path and os.path.exists(file_path):
            if os.path.exists(target_path):
                os.remove(target_path)
            os.replace(file_path, target_path)
            renamed.append(target_path)
        else:
            renamed.append(file_path)
            
        faces_count = 0
        verts_count = 0
        try:
            m = trimesh.load(target_path, process=False)
            faces_count = len(m.faces) if hasattr(m, 'faces') else 0
            verts_count = len(m.vertices) if hasattr(m, 'vertices') else 0
        except Exception:
            pass
            
        screen_size = round(1.0 / (2 ** i), 3) if i > 0 else 1.0
        level_info.append({
            "level": i,
            "filename": os.path.basename(target_path),
            "ratio": ratios[i],
            "target_screen_size": screen_size,
            "faces": faces_count,
            "vertices": verts_count
        })
        
    manifest = {
        "asset": base_name,
        "source_file": os.path.basename(input_file),
        "target_engine": engine,
        "lod_count": len(renamed),
        "levels": level_info
    }
    manifest_path = os.path.join(output_dir, f"{base_name}_lod_manifest.json")
    try:
        with open(manifest_path, 'w', encoding='utf-8') as mf:
            json.dump(manifest, mf, indent=2)
    except Exception:
        pass
        
    return {
        "success": len(renamed) > 0,
        "output_files": renamed,
        "manifest_path": manifest_path,
        "levels_created": len(renamed),
        "summary": f"Generated {len(renamed)} engine LODs for {base_name} with manifest."
    }
