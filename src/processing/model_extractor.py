"""
Model extractor for extracting individual models from complex scenes.
"""

import os
import logging
import trimesh
import numpy as np
from typing import List, Dict, Optional, Tuple, Union, Callable
from dataclasses import dataclass, field
from sklearn.cluster import DBSCAN
import json

# The packaged build has no console (`RenderFox.spec`: console=False), so the root logger is the
# only reader a batch extraction has left: it is the row that says which part was refused and
# why, when the pane's own table only counted what arrived.
logger = logging.getLogger(__name__)

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

def _material_label(mesh) -> str:
    """The name this part's material carries, or the reason it has none.

    Readers here hand one material per geometry, not per face - trimesh 4.7.4
    `TextureVisuals` has no `face_material` attribute (checked) - so a part's material is
    a single thing with a name, and that name is what 'material_based' extraction groups
    by.
    """
    material = getattr(getattr(mesh, 'visual', None), 'material', None)
    if material is None:
        return 'no material'
    name = getattr(material, 'name', None)
    return str(name) if name else type(material).__name__

def _safe_filename(name: str) -> str:
    """A part name turned into something a path can hold.

    Anything that is not a letter, a digit, space, dash or underscore is dropped, and a
    leading dot or space is dropped too - `..` and `folder/.` are both made of allowed
    characters and both escape the output folder when joined back onto a path.
    """
    cleaned = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip('. ')
    return cleaned or "unnamed_model"

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
        # What the last run examined, kept, dropped and whether it stopped. The pane
        # prints these instead of a count of rows, because "12 models extracted" said
        # nothing about the 40 parts that were below the minimum and went silently.
        self.summary: Dict[str, object] = {}

    def read_source(self, scene_file: str):
        """The file as a Scene if a reader here keeps its parts, else as one mesh.

        Both come from `FormatConverter`, the app's only reader. This used to call
        `trimesh.load` directly, which has no `.fbx` or `.dae` loader - so extraction was
        the one pane in Pre-Processing that could not open the formats its own Browse
        filter offered, and the failure arrived as "Unsupported scene type" rather than
        as the name of the library that could not read the file.
        """
        from .format_converter import FormatConverter
        converter = FormatConverter()
        scene, scene_note = converter.read_scene(scene_file)
        if scene is not None:
            return scene, scene_note

        mesh, mesh_note = converter.read_mesh(scene_file)
        if mesh is None:
            raise ValueError(
                f'no library here can open {os.path.basename(scene_file)} - '
                f'as a scene: {scene_note}; as one mesh: {mesh_note}')
        return mesh, f'{mesh_note} (as one mesh, the scene reader could not keep the parts: ' \
                    f'{scene_note})'

    def extract_from_scene(self, scene_file: str, min_faces: int = 10,
                          method: str = "connected_components",
                          progress: Optional[Callable[[int, int, str], None]] = None,
                          should_cancel: Optional[Callable[[], bool]] = None) -> List[ExtractedModel]:
        """
        Extract individual models from a scene file using various methods.

        Args:
            scene_file: Path to the scene file
            min_faces: Minimum face count to consider a model
            method: One of `extraction_methods`; anything else is refused by name
            progress: called as (parts_done, parts_total, sentence) after each part
            should_cancel: asked before each part; a stopped run returns the parts
                already split, and `summary['stopped']` says so

        Returns:
            List of extracted models
        """
        if method not in self.extraction_methods:
            raise ValueError(f'unknown extraction method {method!r} - this extractor has '
                             f'{", ".join(self.extraction_methods)}')

        source, carried = self.read_source(scene_file)
        notes: List[str] = []

        if isinstance(source, trimesh.Scene):
            extracted, stats = self._extract_from_scene_object(
                source, min_faces, method, progress, should_cancel, notes)
        elif isinstance(source, trimesh.Trimesh):
            extracted, stats = self._extract_from_single_mesh(
                source, min_faces, method, progress, should_cancel, notes)
        else:
            raise ValueError(f'{os.path.basename(scene_file)} was read as a '
                             f'{type(source).__name__}, which has no parts to extract')

        stats['read_with'] = carried
        stats['notes'] = notes
        stats['method'] = method
        stats['min_faces'] = min_faces
        self.summary = stats
        self.extracted_models = extracted
        return extracted
    
    def _extract_from_scene_object(self, scene: trimesh.Scene, min_faces: int,
                                   method: str,
                                   progress: Optional[Callable[[int, int, str], None]] = None,
                                   should_cancel: Optional[Callable[[], bool]] = None,
                                   notes: Optional[List[str]] = None):
        """Each geometry of the file split the way `method` says.

        The two single-mesh methods used to be answered by this file's default branch, so
        choosing 'geometric analysis' on a scene returned whole geometries and said nothing
        about it. They now run per geometry, which is what the words promise.
        'size_based' is the one method that has to see the whole scene at once, because it
        groups parts *against each other*.
        """
        geometries = [(name, mesh) for name, mesh in scene.geometry.items()
                      if isinstance(mesh, trimesh.Trimesh)]

        if method == 'size_based':
            groups = self._group_by_size(geometries)
            parts = [(f'{group}_{orig}_{i:03d}', mesh)
                     for group, members in groups.items()
                     for i, (orig, mesh) in enumerate(members)]
            return self._collect(parts, min_faces, progress, should_cancel,
                                 unit='size group')

        if method == 'material_based':
            # This build's readers hand one material per geometry, not one per face
            # (verified: trimesh 4.7.4 TextureVisuals has no face_material), so the parts
            # already are the material groups. Each is named after the material it carries.
            parts = [(f'{name} [{_material_label(mesh)}]', mesh) for name, mesh in geometries]
            return self._collect(parts, min_faces, progress, should_cancel, unit='material')

        return self._collect(
            [piece for name, mesh in geometries
             for piece in self._split_part(name, mesh, method, notes)],
            min_faces, progress, should_cancel, unit='part')

    def _extract_from_single_mesh(self, mesh: trimesh.Trimesh, min_faces: int,
                                  method: str,
                                  progress: Optional[Callable[[int, int, str], None]] = None,
                                  should_cancel: Optional[Callable[[], bool]] = None,
                                  notes: Optional[List[str]] = None):
        """One mesh, split into the pieces the method produces.

        'size_based' and 'material_based' need more than one mesh to group, so on a file
        the reader could only return as a single mesh they refuse with the reason instead
        of quietly producing the connected-components answer under another name.
        """
        if method in ('size_based', 'material_based'):
            raise ValueError(
                f'{method} needs a file whose parts survive the read; this one came back '
                f'as a single mesh, so there is nothing to group. Use '
                f'connected_components, spatial_clustering or geometric_analysis.')

        name = str(mesh.metadata.get('name') or 'mesh')
        pieces = self._split_part(name, mesh, method, notes)
        return self._collect(pieces, min_faces, progress, should_cancel, unit='piece')

    def _split_part(self, name: str, mesh: trimesh.Trimesh, method: str,
                    notes: Optional[List[str]] = None) -> List[Tuple[str, trimesh.Trimesh]]:
        """The pieces one geometry breaks into, each named after the part it came from.

        `notes` carries the sentences about how the split really went, so a method that
        cannot run on this build never reports its fallback under the chosen name.
        """
        if method == 'spatial_clustering':
            return [(f'{name}_Cluster_{i:03d}', cluster)
                    for i, cluster in enumerate(self._spatial_clustering(mesh, name, notes))]
        if method == 'geometric_analysis':
            return [(f'{name}_GeomSep_{i:03d}', piece)
                    for i, piece in enumerate(self._geometric_separation(mesh, name, notes))]
        components = mesh.split(only_watertight=False)
        if len(components) == 1:
            return [(name, components[0])]
        return [(f'{name}_part_{i:03d}', component)
                for i, component in enumerate(components)]

    def _collect(self, parts: List[Tuple[str, trimesh.Trimesh]], min_faces: int,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None,
                 unit: str = 'part'):
        """Filter by face count and count what the filter took, so the pane can say so.

        `dropped` is the number the old code threw away in silence: a scene of 40 pieces
        and a minimum of 100 faces could return 3 rows, and the only figure shown was 3.
        """
        extracted: List[ExtractedModel] = []
        stats = {'parts': len(parts), 'kept': 0, 'dropped': 0, 'stopped': False}
        total = len(parts)
        for index, (name, piece) in enumerate(parts, start=1):
            if should_cancel is not None and should_cancel():
                stats['stopped'] = True
                break
            if len(piece.faces) < min_faces:
                stats['dropped'] += 1
                continue
            extracted.append(self._create_extracted_model(name, piece))
            stats['kept'] += 1
            if progress is not None:
                progress(index, total,
                         f'{unit} {index} of {total}: {name} kept '
                         f'({len(piece.faces):,} faces)')
        return extracted, stats
    
    def _spatial_clustering(self, mesh: trimesh.Trimesh, name: str = 'mesh',
                            notes: Optional[List[str]] = None) -> List[trimesh.Trimesh]:
        """Every face of the mesh placed in exactly one group of nearby faces.

        The neighbours come from DBSCAN over the face centres, with `eps` taken from the
        mesh's own edge lengths. The two parameters this method used to run with - `eps` at
        a tenth of the bounding box and `min_samples=5` - put every face of a low-poly part
        outside every other face's neighbourhood, so DBSCAN called the whole part noise and
        skipped it: 'spatial_clustering' returned no models at all for one box, and kept 7
        faces out of 321 for the app's own sphere. `min_samples=1` makes the run a
        partition, so `min_faces` in `_collect` stays the only filter that can drop a group.
        """
        centers = mesh.triangles_center
        if len(centers) == 0:
            return []
        if not np.isfinite(centers).all():
            if notes is not None:
                notes.append(f'{name}: face centres are not finite, kept whole')
            return [mesh]
        eps = float(np.mean(mesh.edges_unique_length)) * 2.0
        if not np.isfinite(eps) or eps <= 0.0:
            if notes is not None:
                notes.append(f'{name}: every edge has zero length, so nothing can be '
                             f'grouped by distance - kept whole')
            return [mesh]
        labels = DBSCAN(eps=eps, min_samples=1).fit_predict(centers)
        groups = []
        for label in sorted(set(int(value) for value in labels)):
            # `submesh` takes a *sequence* of masks; a bare mask is read as one scalar
            # index and raises `len() of unsized object`.
            pieces = mesh.submesh([np.flatnonzero(labels == label)])
            for piece in (pieces if isinstance(pieces, list) else [pieces]):
                if len(piece.faces) > 0:
                    groups.append(piece)
        kept = sum(len(piece.faces) for piece in groups)
        if kept != len(mesh.faces) and notes is not None:
            notes.append(f'{name}: clustering kept {kept} of {len(mesh.faces)} faces')
        return groups

    def _geometric_separation(self, mesh: trimesh.Trimesh, name: str = 'mesh',
                              notes: Optional[List[str]] = None) -> List[trimesh.Trimesh]:
        """Convex parts of the mesh, or its connected components when this build cannot decompose.

        `convex_decomposition` needs the `vhacdx` package, which is not in this install, so
        the fallback is named in `notes` instead of being returned under the method's own
        name - the alternative was a silent `except:` that reported a shape split the
        reader never performed.
        """
        if mesh.is_convex:
            return [mesh]
        try:
            return [hull for hull in mesh.convex_decomposition() if len(hull.faces) > 0]
        except Exception as error:
            reason = str(error)
            if 'vhacdx' in reason:
                reason = ('this build has no `vhacdx` installed, so convex decomposition '
                          'cannot run')
            if notes is not None:
                notes.append(f'{name}: geometric analysis fell back to connectivity - '
                             f'{reason[:90]}')
            return mesh.split(only_watertight=False)

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
        
        # What this part's shader is called and what kind it is. The old line was
        # `len(mesh.visual.material)`, and trimesh's PBRMaterial and SimpleMaterial both
        # raise TypeError for len() (measured on 4.7.4) - so extracting any part that
        # carried a material killed the run before it could return a single row.
        material = getattr(getattr(mesh, 'visual', None), 'material', None)
        material_info = {
            "has_materials": material is not None,
            "material": _material_label(mesh),
            "material_type": type(material).__name__ if material is not None else None,
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
                             output_dir: str, format_ext: str = ".obj",
                             progress: Optional[Callable[[int, int, str], None]] = None,
                             should_cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """
        Export selected models to files and report every verdict, not only the successes.

        The old version returned the paths that worked and sent the failures to stdout, so
        a pane printing "Successfully exported 3 models" could have lost five to a writer
        that is not installed and nobody would ever see why. Writing also goes through
        `FormatConverter.write_mesh`, the app's one writer, so a format no library here
        produces is refused by name before a file is attempted.

        Args:
            models: List of models to export
            output_dir: Output directory
            format_ext: File format extension, e.g. '.obj'
            progress: called as (done, total, sentence) after each file lands
            should_cancel: asked before each file

        Returns:
            {'exported': [paths], 'failed': [(name, reason)], 'stopped': bool,
             'output_dir': str, 'format': str}
        """
        from .format_converter import FormatConverter
        converter = FormatConverter()
        os.makedirs(output_dir, exist_ok=True)
        verdict = {'exported': [], 'failed': [], 'stopped': False,
                   'output_dir': output_dir, 'format': format_ext}
        total = len(models)

        for index, model in enumerate(models, start=1):
            if should_cancel is not None and should_cancel():
                verdict['stopped'] = True
                break

            safe_name = _safe_filename(model.name)
            filepath = os.path.join(output_dir, f"{safe_name}{format_ext}")
            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(output_dir, f"{safe_name}_{counter:03d}{format_ext}")
                counter += 1

            ok, note = converter.write_mesh(model.mesh, filepath)
            if ok:
                verdict['exported'].append(filepath)
                if progress is not None:
                    progress(index, total,
                             f"{os.path.basename(filepath)} written "
                             f"({len(model.mesh.faces):,} faces)")
            else:
                verdict['failed'].append((model.name, note))
                if progress is not None:
                    progress(index, total, f"{model.name} refused: {note}")

        return verdict
    
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
            logger.warning("Failed to export report: %s", e)
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

    from .format_converter import FormatConverter
    supported_extensions = set(FormatConverter().readable_formats())

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
            verdict = extractor.export_selected_models(models, file_output_dir, ".obj")
            results[file_path] = verdict['exported']
            for name, reason in verdict['failed']:
                logger.warning("%s: %s was not written - %s", filename, name, reason)
            
            # Export extraction report
            report_path = os.path.join(file_output_dir, "extraction_report.json")
            extractor.export_extraction_report(models, report_path)
            
            logger.info("Extracted %d models from %s "
                        "(%d written, %d refused)",
                        len(models), filename,
                        len(verdict['exported']), len(verdict['failed']))
            
        except Exception as e:
            logger.warning("Failed to extract from %s: %s", filename, e)
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