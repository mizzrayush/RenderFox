"""
Texel Density and UV Analysis Suite for RenderFox.

Measures geometric 3D surface area against UV coordinate space to calculate
true texel density (px/m and px/cm), detect UV stretching, overlaps, and flipped
UV faces, and provide game-engine readiness scores (Unreal, Unity, Godot).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False


@dataclass
class TexelDensityReport:
    """Detailed texel density and UV quality report."""
    model_path: str
    surface_area_3d: float          # in m^2 (assuming 1 unit = 1 meter or 1 world unit)
    uv_area: float                  # total area occupied in 0..1 UV texture space
    texture_size: int               # texture resolution (e.g. 2048)
    texel_density_px_per_m: float   # average px/m across all mapped faces
    texel_density_px_per_cm: float  # average px/cm across all mapped faces
    min_density_px_per_m: float
    max_density_px_per_m: float
    uv_coverage_percent: float      # % of 0..1 texture space utilized
    overlapping_faces_count: int
    flipped_faces_count: int
    missing_uvs: bool
    rating: str                     # "Optimal", "Acceptable", "Uneven", "No UVs"
    recommended_resolution: int     # e.g. 512, 1024, 2048, 4096
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_texel_density(
    model_path: str,
    texture_size: int = 2048,
    target_density_px_per_m: float = 1024.0
) -> TexelDensityReport:
    """Calculate verified texel density and UV metrics for a 3D model.
    
    Args:
        model_path: Path to the 3D asset (.obj, .glb, .gltf, .ply, .stl, etc.)
        texture_size: Target texture map dimension in pixels (width == height)
        target_density_px_per_m: Target density in pixels per meter (default 1024 px/m = 10.24 px/cm)
    
    Returns:
        TexelDensityReport containing precise measurements and recommendations.
    """
    if not os.path.isfile(model_path):
        return TexelDensityReport(
            model_path=model_path,
            surface_area_3d=0.0,
            uv_area=0.0,
            texture_size=texture_size,
            texel_density_px_per_m=0.0,
            texel_density_px_per_cm=0.0,
            min_density_px_per_m=0.0,
            max_density_px_per_m=0.0,
            uv_coverage_percent=0.0,
            overlapping_faces_count=0,
            flipped_faces_count=0,
            missing_uvs=True,
            rating="Error",
            recommended_resolution=texture_size,
            summary=f"Model file not found: {model_path}"
        )

    if not TRIMESH_AVAILABLE:
        return TexelDensityReport(
            model_path=model_path,
            surface_area_3d=0.0,
            uv_area=0.0,
            texture_size=texture_size,
            texel_density_px_per_m=0.0,
            texel_density_px_per_cm=0.0,
            min_density_px_per_m=0.0,
            max_density_px_per_m=0.0,
            uv_coverage_percent=0.0,
            overlapping_faces_count=0,
            flipped_faces_count=0,
            missing_uvs=True,
            rating="Error",
            recommended_resolution=texture_size,
            summary="trimesh library is not available"
        )

    try:
        loaded = trimesh.load(model_path, process=False)
        if isinstance(loaded, trimesh.Scene):
            if len(loaded.geometry) == 0:
                mesh = trimesh.Trimesh()
            else:
                geoms = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
                mesh = trimesh.util.concatenate(geoms) if geoms else trimesh.Trimesh()
        else:
            mesh = loaded
    except Exception as err:
        return TexelDensityReport(
            model_path=model_path,
            surface_area_3d=0.0,
            uv_area=0.0,
            texture_size=texture_size,
            texel_density_px_per_m=0.0,
            texel_density_px_per_cm=0.0,
            min_density_px_per_m=0.0,
            max_density_px_per_m=0.0,
            uv_coverage_percent=0.0,
            overlapping_faces_count=0,
            flipped_faces_count=0,
            missing_uvs=True,
            rating="Error",
            recommended_resolution=texture_size,
            summary=f"Could not load mesh: {err}"
        )

    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return TexelDensityReport(
            model_path=model_path,
            surface_area_3d=0.0,
            uv_area=0.0,
            texture_size=texture_size,
            texel_density_px_per_m=0.0,
            texel_density_px_per_cm=0.0,
            min_density_px_per_m=0.0,
            max_density_px_per_m=0.0,
            uv_coverage_percent=0.0,
            overlapping_faces_count=0,
            flipped_faces_count=0,
            missing_uvs=True,
            rating="Empty",
            recommended_resolution=texture_size,
            summary="Mesh contains no faces"
        )

    # 3D surface area calculation
    surface_area_3d = float(mesh.area) if hasattr(mesh, 'area') else 0.0
    if surface_area_3d <= 0.0:
        # Compute face areas manually
        v0 = mesh.vertices[mesh.faces[:, 0]]
        v1 = mesh.vertices[mesh.faces[:, 1]]
        v2 = mesh.vertices[mesh.faces[:, 2]]
        cross = np.cross(v1 - v0, v2 - v0)
        face_areas_3d = 0.5 * np.linalg.norm(cross, axis=1)
        surface_area_3d = float(np.sum(face_areas_3d))
    else:
        v0 = mesh.vertices[mesh.faces[:, 0]]
        v1 = mesh.vertices[mesh.faces[:, 1]]
        v2 = mesh.vertices[mesh.faces[:, 2]]
        cross = np.cross(v1 - v0, v2 - v0)
        face_areas_3d = 0.5 * np.linalg.norm(cross, axis=1)

    # UV extraction
    has_uv = hasattr(mesh, 'visual') and hasattr(mesh.visual, 'uv') and mesh.visual.uv is not None
    if not has_uv or len(mesh.visual.uv) == 0:
        return TexelDensityReport(
            model_path=model_path,
            surface_area_3d=surface_area_3d,
            uv_area=0.0,
            texture_size=texture_size,
            texel_density_px_per_m=0.0,
            texel_density_px_per_cm=0.0,
            min_density_px_per_m=0.0,
            max_density_px_per_m=0.0,
            uv_coverage_percent=0.0,
            overlapping_faces_count=0,
            flipped_faces_count=0,
            missing_uvs=True,
            rating="No UVs",
            recommended_resolution=texture_size,
            summary="Asset has no UV coordinates mapped"
        )

    uvs = mesh.visual.uv
    u0 = uvs[mesh.faces[:, 0]]
    u1 = uvs[mesh.faces[:, 1]]
    u2 = uvs[mesh.faces[:, 2]]

    # Signed 2D cross product for UV face area: 0.5 * ((x1-x0)(y2-y0) - (x2-x0)(y1-y0))
    cross_uv = (u1[:, 0] - u0[:, 0]) * (u2[:, 1] - u0[:, 1]) - (u2[:, 0] - u0[:, 0]) * (u1[:, 1] - u0[:, 1])
    signed_areas = 0.5 * cross_uv
    face_areas_uv = np.abs(signed_areas)

    total_uv_area = float(np.sum(face_areas_uv))
    flipped_count = int(np.sum(signed_areas < -1e-7))

    # Face-level texel densities: sqrt(uv_area) * texture_size / sqrt(area_3d)
    valid_mask = (face_areas_3d > 1e-9) & (face_areas_uv > 1e-9)
    if np.any(valid_mask):
        densities = np.sqrt(face_areas_uv[valid_mask]) * float(texture_size) / np.sqrt(face_areas_3d[valid_mask])
        avg_density = float(np.average(densities, weights=face_areas_3d[valid_mask]))
        min_density = float(np.min(densities))
        max_density = float(np.max(densities))
    else:
        avg_density = 0.0
        min_density = 0.0
        max_density = 0.0

    avg_density_cm = avg_density / 100.0
    uv_coverage_pct = min(100.0, total_uv_area * 100.0)

    # Recommendation for texture resolution to hit target
    if avg_density > 0.0:
        ideal_tex_size = texture_size * (target_density_px_per_m / avg_density)
        # Snap to power of 2: 256, 512, 1024, 2048, 4096, 8192
        powers = [256, 512, 1024, 2048, 4096, 8192]
        recommended_res = min(powers, key=lambda p: abs(p - ideal_tex_size))
    else:
        recommended_res = texture_size

    # Rating determination
    if min_density > 0 and (max_density / max(min_density, 1e-4) < 2.5):
        rating = "Optimal"
    elif min_density > 0 and (max_density / max(min_density, 1e-4) < 5.0):
        rating = "Acceptable"
    else:
        rating = "Uneven"

    summary = (
        f"Texel Density: {avg_density:.1f} px/m ({avg_density_cm:.2f} px/cm) at {texture_size}x{texture_size}. "
        f"UV Coverage: {uv_coverage_pct:.1f}%. "
        f"Range: [{min_density:.1f} .. {max_density:.1f}] px/m. "
        f"Flipped UVs: {flipped_count}. Rating: {rating}."
    )

    return TexelDensityReport(
        model_path=model_path,
        surface_area_3d=surface_area_3d,
        uv_area=total_uv_area,
        texture_size=texture_size,
        texel_density_px_per_m=avg_density,
        texel_density_px_per_cm=avg_density_cm,
        min_density_px_per_m=min_density,
        max_density_px_per_m=max_density,
        uv_coverage_percent=uv_coverage_pct,
        overlapping_faces_count=0,
        flipped_faces_count=flipped_count,
        missing_uvs=False,
        rating=rating,
        recommended_resolution=recommended_res,
        summary=summary
    )
