"""
Model extractor for extracting individual models from complex scenes.
"""

import os
import trimesh
import numpy as np
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from sklearn.cluster import DBSCAN
import json

@dataclass
class ExtractedModel:
    """Information about an extracted model."""
    name: str
    mesh: trimesh.Trimesh
    bounds: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
    face_count: int
    vertex_count: int
    volume: float
    surface_area: float
    center_of_mass: Tuple[float, float, float]
    bounding_box_size: Tuple[float, float, float]
    material_info: Dict = None

class ModelExtractor:
    """Extracts individual models from complex 3D scenes using advanced algorithms."""
    
    def __init__(self):
        self.extracted_models: List[ExtractedModel] = []
        self.extraction_methods = [
            "connected_components",
            "spatial_clustering", 
            "material_based",
            "size_based",
            "geometric_analysis"
        ]
    
    def extract_from_scene(self, scene_file: str, min_faces: int = 10, 
                          method: str = "connected_components") -> List[ExtractedModel]:
        """
        Extract individual models from a scene file using various methods.
        
        Args:
            scene_file: Path to the scene file
            min_faces: Minimum face count to consider a model
            method: Extraction method to use
            
        Returns:
            List of extracted models
        """
        try:
            # Load the scene
            scene = trimesh.load(scene_file)
            
            extracted = []
            
            if isinstance(scene, trimesh.Scene):
                # Handle scene with multiple objects
                extracted = self._extract_from_scene_object(scene, min_faces, method)
            elif isinstance(scene, trimesh.Trimesh):
                # Handle single mesh
                extracted = self._extract_from_single_mesh(scene, min_faces, method)
            else:
                raise ValueError("Unsupported scene type")
            
            self.extracted_models = extracted
            return extracted
            
        except Exception as e:
            raise ValueError(f"Failed to extract models from scene: {str(e)}")
    
    def _extract_from_scene_object(self, scene: trimesh.Scene, min_faces: int, 
                                  method: str) -> List[ExtractedModel]:
        """Extract models from a trimesh Scene object."""
        extracted = []
        
        if method == "connected_components":
            # Extract each geometry in the scene
            for name, mesh in scene.geometry.items():
                if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces) >= min_faces:
                    # Further split by connected components
                    components = mesh.split(only_watertight=False)
                    for i, component in enumerate(components):
                        if len(component.faces) >= min_faces:
                            model_name = f"{name}_part_{i:03d}" if len(components) > 1 else name
                            model = self._create_extracted_model(model_name, component)
                            extracted.append(model)
        
        elif method == "material_based":
            # Group by materials if available
            for name, mesh in scene.geometry.items():
                if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces) >= min_faces:
                    material_groups = self._group_by_materials(mesh)
                    for mat_name, mat_mesh in material_groups.items():
                        if len(mat_mesh.faces) >= min_faces:
                            model_name = f"{name}_{mat_name}"
                            model = self._create_extracted_model(model_name, mat_mesh)
                            extracted.append(model)
        
        elif method == "size_based":
            # Group by similar sizes
            all_meshes = []
            for name, mesh in scene.geometry.items():
                if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces) >= min_faces:
                    all_meshes.append((name, mesh))
            
            size_groups = self._group_by_size(all_meshes)
            for group_name, meshes in size_groups.items():
                for i, (orig_name, mesh) in enumerate(meshes):
                    model_name = f"{group_name}_{orig_name}_{i:03d}"
                    model = self._create_extracted_model(model_name, mesh)
                    extracted.append(model)
        
        else:
            # Default: simple extraction
            for name, mesh in scene.geometry.items():
                if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces) >= min_faces:
                    model = self._create_extracted_model(name, mesh)
                    extracted.append(model)
        
        return extracted
    
    def _extract_from_single_mesh(self, mesh: trimesh.Trimesh, min_faces: int, 
                                 method: str) -> List[ExtractedModel]:
        """Extract models from a single mesh."""
        extracted = []
        
        if method == "connected_components":
            components = mesh.split(only_watertight=False)
            for i, component in enumerate(components):
                if len(component.faces) >= min_faces:
                    name = f"Component_{i:03d}"
                    model = self._create_extracted_model(name, component)
                    extracted.append(model)
        
        elif method == "spatial_clustering":
            # Use spatial clustering to separate models
            clusters = self._spatial_clustering(mesh, min_faces)
            for i, cluster_mesh in enumerate(clusters):
                name = f"Cluster_{i:03d}"
                model = self._create_extracted_model(name, cluster_mesh)
                extracted.append(model)
        
        elif method == "geometric_analysis":
            # Advanced geometric analysis
            separated_meshes = self._geometric_separation(mesh, min_faces)
            for i, sep_mesh in enumerate(separated_meshes):
                name = f"GeomSep_{i:03d}"
                model = self._create_extracted_model(name, sep_mesh)
                extracted.append(model)
        
        else:
            # Default: just split by connected components
            components = mesh.split(only_watertight=False)
            for i, component in enumerate(components):
                if len(component.faces) >= min_faces:
                    name = f"Component_{i:03d}"
                    model = self._create_extracted_model(name, component)
                    extracted.append(model)
        
        return extracted
    
    def _spatial_clustering(self, mesh: trimesh.Trimesh, min_faces: int) -> List[trimesh.Trimesh]:
        """Use spatial clustering to separate models."""
        try:
            # Get face centers
            face_centers = mesh.triangles_center
            
            # Apply DBSCAN clustering
            clustering = DBSCAN(eps=np.mean(mesh.extents) * 0.1, min_samples=5)
            cluster_labels = clustering.fit_predict(face_centers)
            
            # Create separate meshes for each cluster
            clustered_meshes = []
            for cluster_id in set(cluster_labels):
                if cluster_id == -1:  # Skip noise
                    continue
                
                # Get faces belonging to this cluster
                cluster_faces = mesh.faces[cluster_labels == cluster_id]
                
                if len(cluster_faces) >= min_faces:
                    # Create new mesh with cluster faces
                    cluster_mesh = mesh.submesh([cluster_labels == cluster_id])
                    if isinstance(cluster_mesh, list):
                        clustered_meshes.extend(cluster_mesh)
                    else:
                        clustered_meshes.append(cluster_mesh)
            
            return clustered_meshes
            
        except Exception as e:
            print(f"Spatial clustering failed: {e}")
            return mesh.split(only_watertight=False)
    
    def _geometric_separation(self, mesh: trimesh.Trimesh, min_faces: int) -> List[trimesh.Trimesh]:
        """Advanced geometric separation based on shape analysis."""
        try:
            # Analyze convexity and separate non-convex parts
            if mesh.is_convex:
                return [mesh]
            
            # Try to separate based on concave regions
            separated = []
            
            # Use convex decomposition if available
            try:
                convex_hulls = mesh.convex_decomposition()
                for hull in convex_hulls:
                    if len(hull.faces) >= min_faces:
                        separated.append(hull)
            except:
                # Fallback to connected components
                separated = mesh.split(only_watertight=False)
            
            return [s for s in separated if len(s.faces) >= min_faces]
            
        except Exception as e:
            print(f"Geometric separation failed: {e}")
            return mesh.split(only_watertight=False)
    
    def _group_by_materials(self, mesh: trimesh.Trimesh) -> Dict[str, trimesh.Trimesh]:
        """Group mesh faces by materials."""
        material_groups = {}
        
        # Check if mesh has material information
        if hasattr(mesh.visual, 'material') and mesh.visual.material:
            # Group faces by material
            for mat_name, material in mesh.visual.material.items():
                # Find faces using this material
                # This is a simplified approach - actual implementation would depend on the mesh format
                material_groups[mat_name] = mesh  # Placeholder
        else:
            # No material info, return whole mesh
            material_groups["default"] = mesh
        
        return material_groups
    
    def _group_by_size(self, meshes: List[Tuple[str, trimesh.Trimesh]]) -> Dict[str, List[Tuple[str, trimesh.Trimesh]]]:
        """Group meshes by similar sizes."""
        size_groups = {"small": [], "medium": [], "large": []}
        
        # Calculate size thresholds
        all_volumes = [mesh.volume for name, mesh in meshes if mesh.is_volume]
        if not all_volumes:
            all_volumes = [mesh.area for name, mesh in meshes]
        
        if len(all_volumes) == 0:
            return {"default": meshes}
        
        small_threshold = np.percentile(all_volumes, 33)
        large_threshold = np.percentile(all_volumes, 67)
        
        for name, mesh in meshes:
            size_metric = mesh.volume if mesh.is_volume else mesh.area
            if size_metric <= small_threshold:
                size_groups["small"].append((name, mesh))
            elif size_metric >= large_threshold:
                size_groups["large"].append((name, mesh))
            else:
                size_groups["medium"].append((name, mesh))
        
        # Remove empty groups
        return {k: v for k, v in size_groups.items() if v}
    
    def _create_extracted_model(self, name: str, mesh: trimesh.Trimesh) -> ExtractedModel:
        """Create an ExtractedModel from a mesh."""
        # Calculate bounding box size
        bounds = mesh.bounds
        bbox_size = bounds[1] - bounds[0]
        
        # Get material information if available
        material_info = {}
        if hasattr(mesh.visual, 'material') and mesh.visual.material:
            material_info = {
                "has_materials": True,
                "material_count": len(mesh.visual.material)
            }
        
        return ExtractedModel(
            name=name,
            mesh=mesh,
            bounds=(bounds[0].tolist(), bounds[1].tolist()),
            face_count=len(mesh.faces),
            vertex_count=len(mesh.vertices),
            volume=float(mesh.volume) if mesh.is_volume else 0.0,
            surface_area=float(mesh.area),
            center_of_mass=mesh.center_mass.tolist(),
            bounding_box_size=bbox_size.tolist(),
            material_info=material_info
        )
    
    def export_selected_models(self, models: List[ExtractedModel], 
                             output_dir: str, format_ext: str = ".obj") -> List[str]:
        """
        Export selected models to files.
        
        Args:
            models: List of models to export
            output_dir: Output directory
            format_ext: File format extension
            
        Returns:
            List of exported file paths
        """
        os.makedirs(output_dir, exist_ok=True)
        exported_files = []
        
        for model in models:
            # Sanitize filename
            safe_name = "".join(c for c in model.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not safe_name:
                safe_name = "unnamed_model"
            
            filename = f"{safe_name}{format_ext}"
            filepath = os.path.join(output_dir, filename)
            
            # Handle duplicate names
            counter = 1
            while os.path.exists(filepath):
                filename = f"{safe_name}_{counter:03d}{format_ext}"
                filepath = os.path.join(output_dir, filename)
                counter += 1
            
            try:
                model.mesh.export(filepath)
                exported_files.append(filepath)
                print(f"Exported: {filename}")
            except Exception as e:
                print(f"Warning: Failed to export {model.name}: {str(e)}")
        
        return exported_files
    
    def filter_models_by_criteria(self, models: List[ExtractedModel], 
                                min_faces: int = 0, max_faces: int = float('inf'),
                                min_volume: float = 0.0, max_volume: float = float('inf'),
                                min_area: float = 0.0, max_area: float = float('inf')) -> List[ExtractedModel]:
        """Filter models by various criteria."""
        filtered = []
        for model in models:
            if (min_faces <= model.face_count <= max_faces and 
                min_volume <= model.volume <= max_volume and
                min_area <= model.surface_area <= max_area):
                filtered.append(model)
        return filtered
    
    def get_extraction_summary(self, models: List[ExtractedModel]) -> Dict:
        """Get summary statistics about extracted models."""
        if not models:
            return {"total_models": 0}
        
        face_counts = [m.face_count for m in models]
        volumes = [m.volume for m in models if m.volume > 0]
        areas = [m.surface_area for m in models]
        
        summary = {
            "total_models": len(models),
            "face_count": {
                "total": sum(face_counts),
                "min": min(face_counts),
                "max": max(face_counts),
                "mean": np.mean(face_counts),
                "median": np.median(face_counts)
            },
            "surface_area": {
                "total": sum(areas),
                "min": min(areas),
                "max": max(areas),
                "mean": np.mean(areas)
            }
        }
        
        if volumes:
            summary["volume"] = {
                "total": sum(volumes),
                "min": min(volumes),
                "max": max(volumes),
                "mean": np.mean(volumes)
            }
        
        return summary
    
    def export_extraction_report(self, models: List[ExtractedModel], 
                               output_path: str) -> bool:
        """Export a detailed report of the extraction process."""
        try:
            report = {
                "extraction_timestamp": trimesh.util.timestamp(),
                "total_models": len(models),
                "summary": self.get_extraction_summary(models),
                "models": []
            }
            
            for model in models:
                model_data = {
                    "name": model.name,
                    "face_count": model.face_count,
                    "vertex_count": model.vertex_count,
                    "volume": model.volume,
                    "surface_area": model.surface_area,
                    "bounds": model.bounds,
                    "center_of_mass": model.center_of_mass,
                    "bounding_box_size": model.bounding_box_size,
                    "material_info": model.material_info
                }
                report["models"].append(model_data)
            
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)
            
            return True
            
        except Exception as e:
            print(f"Failed to export report: {str(e)}")
            return False
    
    def analyze_extraction_quality(self, original_mesh: trimesh.Trimesh, 
                                 extracted_models: List[ExtractedModel]) -> Dict:
        """Analyze the quality of the extraction process."""
        total_extracted_faces = sum(m.face_count for m in extracted_models)
        total_extracted_volume = sum(m.volume for m in extracted_models if m.volume > 0)
        
        quality_metrics = {
            "face_preservation": total_extracted_faces / len(original_mesh.faces),
            "model_count": len(extracted_models),
            "average_model_size": total_extracted_faces / len(extracted_models) if extracted_models else 0,
            "extraction_efficiency": min(1.0, total_extracted_faces / len(original_mesh.faces))
        }
        
        if original_mesh.is_volume and total_extracted_volume > 0:
            quality_metrics["volume_preservation"] = total_extracted_volume / original_mesh.volume
        
        # Calculate size distribution
        face_counts = [m.face_count for m in extracted_models]
        if face_counts:
            quality_metrics["size_distribution"] = {
                "std_dev": float(np.std(face_counts)),
                "coefficient_of_variation": float(np.std(face_counts) / np.mean(face_counts))
            }
        
        return quality_metrics

# Utility functions
def batch_extract_models(input_directory: str, output_directory: str, 
                        min_faces: int = 10, method: str = "connected_components") -> Dict[str, List[str]]:
    """
    Batch extract models from all supported files in a directory.
    
    Args:
        input_directory: Directory containing scene files
        output_directory: Directory to save extracted models
        min_faces: Minimum face count for extraction
        method: Extraction method to use
        
    Returns:
        Dictionary mapping input files to lists of extracted model files
    """
    extractor = ModelExtractor()
    results = {}
    
    supported_extensions = ['.obj', '.ply', '.stl', '.gltf', '.glb', '.dae', '.fbx']
    
    for filename in os.listdir(input_directory):
        file_path = os.path.join(input_directory, filename)
        
        if not os.path.isfile(file_path):
            continue
        
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in supported_extensions:
            continue
        
        try:
            # Extract models
            models = extractor.extract_from_scene(file_path, min_faces, method)
            
            # Create output subdirectory for this file
            file_base = os.path.splitext(filename)[0]
            file_output_dir = os.path.join(output_directory, file_base)
            
            # Export models
            exported_files = extractor.export_selected_models(models, file_output_dir, ".obj")
            results[file_path] = exported_files
            
            # Export extraction report
            report_path = os.path.join(file_output_dir, "extraction_report.json")
            extractor.export_extraction_report(models, report_path)
            
            print(f"✓ Extracted {len(models)} models from {filename}")
            
        except Exception as e:
            print(f"✗ Failed to extract from {filename}: {str(e)}")
            results[file_path] = []
    
    return results

def preview_extraction(scene_file: str, min_faces: int = 10, 
                      method: str = "connected_components") -> Dict:
    """
    Preview what models would be extracted without actually extracting them.
    
    Args:
        scene_file: Path to scene file
        min_faces: Minimum face count
        method: Extraction method
        
    Returns:
        Dictionary with preview information
    """
    try:
        extractor = ModelExtractor()
        models = extractor.extract_from_scene(scene_file, min_faces, method)
        
        preview = {
            "total_models": len(models),
            "extraction_method": method,
            "models": []
        }
        
        for model in models:
            model_info = {
                "name": model.name,
                "face_count": model.face_count,
                "vertex_count": model.vertex_count,
                "volume": model.volume,
                "surface_area": model.surface_area,
                "bounding_box_size": model.bounding_box_size
            }
            preview["models"].append(model_info)
        
        return preview
        
    except Exception as e:
        return {"error": f"Preview failed: {str(e)}"}

def get_extraction_methods_info() -> Dict[str, str]:
    """Get information about available extraction methods."""
    return {
        "connected_components": "Separates meshes by connectivity - good for distinct objects",
        "spatial_clustering": "Groups nearby geometry using DBSCAN clustering",
        "material_based": "Separates based on material assignments",
        "size_based": "Groups objects by similar sizes",
        "geometric_analysis": "Advanced separation using convex decomposition"
    }