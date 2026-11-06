"""
Quality Analyzer - Production-Ready Score & Optimization Suggestions

This module analyzes 3D models and provides a comprehensive quality score (0-100)
along with specific issues detected and one-click fix suggestions.

Features:
- Production-ready score (0-100) with letter grade (A, B, C, D, F)
- Detailed issue detection (non-manifold geometry, UV problems, etc.)
- One-click fix suggestions
- Industry standards comparison (Unity, Unreal, mobile, VR)
- Quality reports with before/after metrics
- Batch quality auditing

Author: RenderFox Team
Date: October 2025
"""

import trimesh
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class QualityAnalyzer:
    """
    Analyze 3D models and provide production-ready quality scores.
    
    This is a unique feature that helps artists ensure their models meet
    professional standards before export or delivery.
    """
    
    # Industry standard thresholds
    STANDARDS = {
        'mobile_game': {
            'max_polygons': 5000,
            'max_vertices': 3000,
            'max_texture_size': 1024,
            'requires_lods': True,
            'requires_watertight': False
        },
        'pc_game': {
            'max_polygons': 50000,
            'max_vertices': 30000,
            'max_texture_size': 4096,
            'requires_lods': True,
            'requires_watertight': False
        },
        'vr': {
            'max_polygons': 10000,
            'max_vertices': 7000,
            'max_texture_size': 2048,
            'requires_lods': True,
            'requires_watertight': False
        },
        'film_vfx': {
            'max_polygons': 1000000,
            'max_vertices': 500000,
            'max_texture_size': 8192,
            'requires_lods': False,
            'requires_watertight': True
        },
        'architectural_viz': {
            'max_polygons': 100000,
            'max_vertices': 60000,
            'max_texture_size': 4096,
            'requires_lods': False,
            'requires_watertight': True
        }
    }

    # The fix names the Quality pane applies with one double-click. The pane builds its
    # dispatch table from this tuple, so a name cannot be promised here and refused there.
    ONE_CLICK_FIXES = ('repair_mesh', 'merge_vertices', 'remove_degenerate_faces',
                       'fix_normals', 'remesh', 'generate_uvs', 'pack_uvs')
    # Two of the nine names have a real backend, but in another pane, behind controls this
    # list has no room for. They say where to go instead of pretending not to exist.
    OWNED_ELSEWHERE = {
        'generate_lods': 'LOD levels are written by the Pre-Processing pane, which owns '
                         'the level-count controls this fix needs',
        'resize_texture': 'texture resolution is rewritten by the Pre-Processing pane\'s '
                          'texture optimizer, which owns the quality and format controls '
                          'this fix needs',
    }
    # The subset of the above that auto_repair (mesh_processor.py:811) provably runs: weld
    # duplicate vertices, drop null/folded/duplicate faces. Fix All marks only these rows,
    # so a suggestion it did not carry out still stands in the list.
    FIX_ALL_COVERS = ('repair_mesh', 'merge_vertices', 'remove_degenerate_faces')

    def __init__(self):
        """Initialize Quality Analyzer."""
        self.issue_fixes = self._load_fix_mappings()
    
    def analyze_quality(self, model_path: str, 
                       target_platform: str = 'pc_game') -> Dict[str, any]:
        """
        Analyze model quality and generate comprehensive report.
        
        Args:
            model_path: Path to 3D model file
            target_platform: Target platform ('mobile_game', 'pc_game', 'vr', 
                           'film_vfx', 'architectural_viz')
        
        Returns:
            Dictionary containing:
                - score: Overall quality score (0-100)
                - grade: Letter grade (A, B, C, D, F)
                - issues: List of detected issues
                - suggestions: List of fix suggestions
                - metrics: Detailed metrics
                - standards_compliance: Comparison against target platform
        """
        try:
            logger.info(f"Analyzing quality of: {model_path}")
            mesh = trimesh.load(model_path)
            
            # Handle Scene objects (e.g. GLB, GLTF)
            if isinstance(mesh, trimesh.Scene):
                # If scene has geometry, merge it into a single mesh for analysis
                if len(mesh.geometry) > 0:
                    mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
                else:
                    # Empty scene
                    return {
                        'score': 0,
                        'grade': 'F',
                        'issues': [{'severity': 'critical', 'type': 'empty_scene',
                                    'message': 'Empty scene (no geometry found)'}],
                        'suggestions': [{'issue_type': 'empty_scene',
                                         'description': 'Check model export settings',
                                         'one_click': False, 'other_pane': None,
                                         'priority': 'critical'}],
                        'metrics': {},
                        'standards_compliance': {}
                    }
            
            # Initialize score (start at 100, deduct points for issues)
            score = 100
            issues = []
            suggestions = []
            
            # Get target standards
            standards = self.STANDARDS.get(target_platform, self.STANDARDS['pc_game'])
            
            # 1. Polygon Count Check (0-20 points)
            poly_score, poly_issues = self._check_polygon_count(mesh, standards)
            score -= (20 - poly_score)
            issues.extend(poly_issues)
            
            # 2. Geometry Integrity Check (0-30 points)
            geo_score, geo_issues = self._check_geometry_integrity(mesh, standards)
            score -= (30 - geo_score)
            issues.extend(geo_issues)
            
            # 3. UV Mapping Check (0-15 points)
            uv_score, uv_issues = self._check_uv_mapping(mesh)
            score -= (15 - uv_score)
            issues.extend(uv_issues)
            
            # 4. Topology Quality Check (0-15 points)
            topo_score, topo_issues = self._check_topology(mesh)
            score -= (15 - topo_score)
            issues.extend(topo_issues)
            
            # 5. Texture/Material Check (0-10 points)
            tex_score, tex_issues = self._check_textures(mesh, standards)
            score -= (10 - tex_score)
            issues.extend(tex_issues)
            
            # 6. Performance Check (0-10 points)
            perf_score, perf_issues = self._check_performance(mesh, standards)
            score -= (10 - perf_score)
            issues.extend(perf_issues)
            
            # Ensure score is within bounds
            score = max(0, min(100, score))
            
            # Generate fix suggestions
            suggestions = self._generate_suggestions(issues)
            
            # Calculate grade
            grade = self._calculate_grade(score)
            
            # Detailed metrics
            metrics = self._gather_metrics(mesh)
            
            # Standards compliance
            compliance = self._check_standards_compliance(metrics, standards)
            
            result = {
                'score': score,
                'grade': grade,
                'issues': issues,
                'suggestions': suggestions,
                'metrics': metrics,
                'standards_compliance': compliance,
                'target_platform': target_platform,
                'model_path': model_path,
                # Sub-scores for UI breakdown
                'polygon_score': poly_score,
                'geometry_score': geo_score,
                'uv_score': uv_score,
                'topology_score': topo_score,
                'texture_score': tex_score,
                'performance_score': perf_score
            }
            
            logger.info(f"Quality analysis complete: Score={score}, Grade={grade}")
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing quality of {model_path}: {e}")
            return {
                'error': str(e),
                'score': 0,
                'grade': 'F',
                'issues': [{'type': 'error', 'message': str(e)}],
                'suggestions': []
            }
    
    def _check_polygon_count(self, mesh, standards: Dict) -> Tuple[int, List[Dict]]:
        """Check polygon count against standards."""
        score = 20
        issues = []
        
        poly_count = len(mesh.faces)
        max_polys = standards['max_polygons']
        
        if poly_count > max_polys * 2:
            score = 0
            issues.append({
                'severity': 'critical',
                'type': 'polygon_count',
                'message': f'Polygon count ({poly_count:,}) is {poly_count/max_polys:.1f}x over target ({max_polys:,})',
                'current': poly_count,
                'target': max_polys
            })
        elif poly_count > max_polys * 1.5:
            score = 5
            issues.append({
                'severity': 'high',
                'type': 'polygon_count',
                'message': f'Polygon count ({poly_count:,}) exceeds target by {(poly_count/max_polys-1)*100:.0f}%',
                'current': poly_count,
                'target': max_polys
            })
        elif poly_count > max_polys:
            score = 15
            issues.append({
                'severity': 'medium',
                'type': 'polygon_count',
                'message': f'Polygon count ({poly_count:,}) slightly over target ({max_polys:,})',
                'current': poly_count,
                'target': max_polys
            })
        
        return score, issues
    
    def _check_geometry_integrity(self, mesh, standards: Dict) -> Tuple[int, List[Dict]]:
        """Check mesh geometry integrity."""
        score = 30
        issues = []
        
        # Check if watertight (required for some platforms)
        if standards['requires_watertight'] and not mesh.is_watertight:
            score -= 15
            issues.append({
                'severity': 'critical',
                'type': 'non_watertight',
                'message': 'Mesh is not watertight (has holes or non-manifold edges)',
                'fix': 'repair_mesh'
            })
        
        # Check for degenerate faces
        if hasattr(mesh, 'area_faces'):
            degenerate_count = np.sum(mesh.area_faces < 1e-10)
            if degenerate_count > 0:
                score -= 5
                issues.append({
                    'severity': 'high',
                    'type': 'degenerate_faces',
                    'message': f'{degenerate_count} degenerate faces detected (zero area)',
                    'count': int(degenerate_count),
                    'fix': 'remove_degenerate_faces'
                })
        
        # Check for duplicate vertices
        try:
            test_mesh = mesh.copy()
            original_vert_count = len(test_mesh.vertices)
            test_mesh.merge_vertices()
            removed_verts = original_vert_count - len(test_mesh.vertices)
            if removed_verts > len(mesh.vertices) * 0.05:  # More than 5% duplicates
                score -= 5
                issues.append({
                    'severity': 'medium',
                    'type': 'duplicate_vertices',
                    'message': f'{removed_verts} duplicate vertices detected',
                    'count': removed_verts,
                    'fix': 'merge_vertices'
                })
        except:
            pass
        
        # Check for inverted normals
        if hasattr(mesh, 'face_normals'):
            # Simple heuristic: check if normals are consistent
            normals = mesh.face_normals
            if len(normals) > 0:
                avg_normal = np.mean(normals, axis=0)
                inconsistent = np.sum(np.dot(normals, avg_normal) < 0)
                if inconsistent > len(normals) * 0.1:  # More than 10% inconsistent
                    score -= 5
                    issues.append({
                        'severity': 'medium',
                        'type': 'inverted_normals',
                        'message': f'{inconsistent} faces may have inverted normals',
                        'count': int(inconsistent),
                        'fix': 'fix_normals'
                    })
        
        return score, issues
    
    def _check_uv_mapping(self, mesh) -> Tuple[int, List[Dict]]:
        """Check UV mapping quality."""
        score = 15
        issues = []
        
        # Check if UVs exist
        if not hasattr(mesh.visual, 'uv') or mesh.visual.uv is None or len(mesh.visual.uv) == 0:
            score = 0
            issues.append({
                'severity': 'high',
                'type': 'missing_uvs',
                'message': 'Model has no UV coordinates',
                'fix': 'generate_uvs'
            })
        else:
            uvs = mesh.visual.uv
            
            # Check for UVs outside 0-1 range
            out_of_bounds = np.sum((uvs < -0.01) | (uvs > 1.01)) # Allow small tolerance
            if out_of_bounds > 0:
                score -= 5
                issues.append({
                    'severity': 'medium',
                    'type': 'uv_bounds',
                    'message': f'{out_of_bounds} UV vertices are outside [0, 1] range',
                    'count': int(out_of_bounds),
                    'fix': 'pack_uvs'
                })
            
            # Check for inverted UV faces (potential overlap/flip)
            # Calculate signed area of UV triangles
            if len(mesh.faces) > 0:
                uv_faces = uvs[mesh.faces]
                # Edge vectors
                edge1 = uv_faces[:, 1] - uv_faces[:, 0]
                edge2 = uv_faces[:, 2] - uv_faces[:, 0]
                # 2D cross product (determinant)
                signed_area = edge1[:, 0] * edge2[:, 1] - edge1[:, 1] * edge2[:, 0]
                
                inverted_faces = np.sum(signed_area < 0)
                if inverted_faces > 0:
                    score -= 5
                    issues.append({
                        'severity': 'medium',
                        'type': 'inverted_uvs',
                        'message': f'{inverted_faces} faces have inverted UVs (potential overlap)',
                        'count': int(inverted_faces),
                        'fix': 'generate_uvs'
                    })
                
                # Check for zero area UV faces
                zero_area = np.sum(np.abs(signed_area) < 1e-6)
                if zero_area > 0:
                    score -= 5
                    issues.append({
                        'severity': 'medium',
                        'type': 'zero_area_uvs',
                        'message': f'{zero_area} faces have zero area in UV space',
                        'count': int(zero_area),
                        'fix': 'generate_uvs'
                    })
            
        return score, issues
    
    def _check_topology(self, mesh) -> Tuple[int, List[Dict]]:
        """Check mesh topology quality."""
        score = 15
        issues = []
        
        # Check triangle aspect ratio
        vertices = mesh.vertices
        faces = mesh.faces
        
        bad_triangles = 0
        for face in faces[:min(1000, len(faces))]:  # Sample first 1000 faces
            v0, v1, v2 = vertices[face]
            
            # Calculate edge lengths
            e0 = np.linalg.norm(v1 - v0)
            e1 = np.linalg.norm(v2 - v1)
            e2 = np.linalg.norm(v0 - v2)
            
            # Check aspect ratio
            max_edge = max(e0, e1, e2)
            min_edge = min(e0, e1, e2)
            
            if min_edge > 0 and max_edge / min_edge > 10:  # Very stretched
                bad_triangles += 1
        
        if bad_triangles > len(faces) * 0.1:  # More than 10% bad triangles
            score -= 10
            issues.append({
                'severity': 'high',
                'type': 'stretched_triangles',
                'message': f'Approximately {bad_triangles * len(faces) // 1000} stretched triangles detected',
                'fix': 'remesh'
            })
        elif bad_triangles > 0:
            score -= 5
            issues.append({
                'severity': 'medium',
                'type': 'stretched_triangles',
                'message': f'Some triangles have poor aspect ratio',
                'fix': 'remesh'
            })
        
        return score, issues
    
    def _check_textures(self, mesh, standards: Dict) -> Tuple[int, List[Dict]]:
        """Check texture/material quality."""
        score = 10
        issues = []
        
        # Check if materials exist
        if not hasattr(mesh.visual, 'material') or mesh.visual.material is None:
            score -= 5
            issues.append({
                'severity': 'low',
                'type': 'missing_materials',
                'message': 'Model has no materials assigned'
            })
        else:
            # Check texture resolution (if available)
            material = mesh.visual.material
            if hasattr(material, 'image') and material.image is not None:
                tex_size = material.image.size
                max_size = standards['max_texture_size']
                
                if max(tex_size) > max_size:
                    score -= 5
                    issues.append({
                        'severity': 'medium',
                        'type': 'texture_too_large',
                        'message': f'Texture resolution {tex_size} exceeds target {max_size}x{max_size}',
                        'current': tex_size,
                        'target': max_size,
                        'fix': 'resize_texture'
                    })
        
        return score, issues
    
    def _check_performance(self, mesh, standards: Dict) -> Tuple[int, List[Dict]]:
        """Check performance metrics."""
        score = 10
        issues = []
        
        # Check vertex count
        vert_count = len(mesh.vertices)
        max_verts = standards['max_vertices']
        
        if vert_count > max_verts * 1.5:
            score -= 5
            issues.append({
                'severity': 'medium',
                'type': 'vertex_count',
                'message': f'Vertex count ({vert_count:,}) exceeds target ({max_verts:,})',
                'current': vert_count,
                'target': max_verts
            })
        
        # Check if LODs are needed but missing
        if standards['requires_lods']:
            # Assume LODs are missing (would need to check in library metadata)
            issues.append({
                'severity': 'low',
                'type': 'missing_lods',
                'message': 'LOD levels recommended for this platform',
                'fix': 'generate_lods'
            })
        
        return score, issues
    
    def _generate_suggestions(self, issues: List[Dict]) -> List[Dict]:
        """Generate actionable fix suggestions from issues."""
        suggestions = []
        
        for issue in issues:
            if 'fix' in issue:
                fix_type = issue['fix']
                suggestion = {
                    'issue_type': issue['type'],
                    'fix_action': fix_type,
                    'description': self.issue_fixes.get(fix_type, 'Manual fix required'),
                    'one_click': fix_type in self.ONE_CLICK_FIXES,
                    'other_pane': self.OWNED_ELSEWHERE.get(fix_type),
                    'priority': issue['severity']
                }
                suggestions.append(suggestion)
        
        return suggestions
    
    def _calculate_grade(self, score: int) -> str:
        """Convert numeric score to letter grade."""
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'
    
    def _gather_metrics(self, mesh) -> Dict:
        """Gather detailed model metrics."""
        metrics = {
            'polygon_count': len(mesh.faces),
            'vertex_count': len(mesh.vertices),
            'edge_count': len(mesh.edges) if hasattr(mesh, 'edges') else 0,
            'is_watertight': mesh.is_watertight,
            'volume': float(mesh.volume) if mesh.is_volume else 0.0,
            'surface_area': float(mesh.area),
            'bounds': mesh.bounds.tolist() if hasattr(mesh.bounds, 'tolist') else mesh.bounds,
            'has_uvs': hasattr(mesh.visual, 'uv') and mesh.visual.uv is not None,
            'has_materials': hasattr(mesh.visual, 'material') and mesh.visual.material is not None
        }
        
        # Calculate poly density
        if metrics['volume'] > 0:
            metrics['poly_density'] = metrics['polygon_count'] / metrics['volume']
        
        return metrics
    
    def _check_standards_compliance(self, metrics: Dict, standards: Dict) -> Dict:
        """Check compliance against target platform standards."""
        compliance = {
            'polygon_count': metrics['polygon_count'] <= standards['max_polygons'],
            'vertex_count': metrics['vertex_count'] <= standards['max_vertices'],
            'watertight': not standards['requires_watertight'] or metrics['is_watertight'],
            'overall': True
        }
        
        compliance['overall'] = all([
            compliance['polygon_count'],
            compliance['vertex_count'],
            compliance['watertight']
        ])
        
        return compliance
    
    def _load_fix_mappings(self) -> Dict[str, str]:
        """Map issue types to fix descriptions."""
        return {
            'repair_mesh': 'Run Mesh Repair Tool to fix holes and non-manifold geometry',
            'merge_vertices': 'Merge duplicate vertices to optimize geometry',
            'remove_degenerate_faces': 'Remove zero-area triangles',
            'fix_normals': 'Recalculate and fix face normals',
            'generate_uvs': 'Generate UV coordinates automatically',
            'pack_uvs': 'Re-project UVs into one atlas with a border, replacing the '
                        'coordinates that lie outside [0, 1]',
            'generate_lods': 'Generate LOD levels for better performance',
            'remesh': 'Remesh to improve triangle quality',
            'resize_texture': 'Resize textures to target resolution'
        }
    
    def batch_analyze(self, model_paths: List[str], 
                     target_platform: str = 'pc_game',
                     progress_callback: Optional[Callable] = None) -> Dict[str, Dict]:
        """
        Batch analyze multiple models.
        
        Args:
            model_paths: List of model file paths
            target_platform: Target platform for all models
            progress_callback: Optional callback(current, total, filename)
        
        Returns:
            Dictionary mapping model_path -> quality analysis results
        """
        results = {}
        total = len(model_paths)
        
        logger.info(f"Starting batch quality analysis of {total} models")
        
        for i, model_path in enumerate(model_paths):
            try:
                analysis = self.analyze_quality(model_path, target_platform)
                results[model_path] = analysis
                
                if progress_callback:
                    progress_callback(i + 1, total, Path(model_path).name)
                    
            except Exception as e:
                logger.error(f"Failed to analyze {model_path}: {e}")
                results[model_path] = {'error': str(e), 'score': 0, 'grade': 'F'}
        
        logger.info(f"Batch quality analysis complete")
        return results
    
    def export_quality_report(self, results: Dict[str, Dict], output_path: str):
        """
        Export quality analysis results to HTML report.
        
        Args:
            results: Results from batch_analyze()
            output_path: Path to save HTML report
        """
        # The style block is kept as a literal and the count is substituted outside it:
        # this template used to end in `.format(len(results))`, and every CSS rule in it
        # is a brace, so the call raised KeyError: ' font-family' before the first line
        # was written. The report had never existed.
        head = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Quality Analysis Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }
                .model-card { background: white; margin: 15px 0; padding: 15px; 
                             border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
                .grade { font-size: 48px; font-weight: bold; display: inline-block; 
                        width: 80px; height: 80px; line-height: 80px; text-align: center; 
                        border-radius: 50%; margin-right: 20px; }
                .grade-A { background: #27ae60; color: white; }
                .grade-B { background: #3498db; color: white; }
                .grade-C { background: #f39c12; color: white; }
                .grade-D { background: #e67e22; color: white; }
                .grade-F { background: #e74c3c; color: white; }
                .issue { padding: 5px 10px; margin: 5px 0; border-left: 3px solid; }
                .critical { border-color: #e74c3c; background: #fadbd8; }
                .high { border-color: #e67e22; background: #fdebd0; }
                .medium { border-color: #f39c12; background: #fef5e7; }
                .low { border-color: #95a5a6; background: #ecf0f1; }
                .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
                .metric { background: #ecf0f1; padding: 10px; border-radius: 3px; }
            </style>
        </head>
        <body>
        """
        html = head + f"""
            <div class="header">
                <h1>Quality Analysis Report</h1>
                <p>Total models analyzed: {len(results)}</p>
            </div>
        """
        
        for model_path, analysis in results.items():
            model_name = Path(model_path).name
            if 'error' in analysis:
                # The count above already includes this model, so the report says what
                # happened to it instead of ending up with fewer cards than it promised.
                html += (f'<div class="model-card"><h2>{model_name}</h2>'
                         f'<p>Could not be analyzed: {analysis["error"]}</p></div>')
                continue
            
            score = analysis['score']
            grade = analysis['grade']
            issues = analysis.get('issues', [])
            metrics = analysis.get('metrics', {})
            
            html += f"""
            <div class="model-card">
                <div style="display: flex; align-items: center;">
                    <div class="grade grade-{grade}">{grade}</div>
                    <div>
                        <h2 style="margin: 0;">{model_name}</h2>
                        <p style="margin: 5px 0; font-size: 24px; color: #7f8c8d;">
                            Quality Score: {score}/100
                        </p>
                    </div>
                </div>
                
                <h3>Metrics</h3>
                <div class="metrics">
                    <div class="metric">
                        <strong>Polygons:</strong> {metrics.get('polygon_count', 0):,}
                    </div>
                    <div class="metric">
                        <strong>Vertices:</strong> {metrics.get('vertex_count', 0):,}
                    </div>
                    <div class="metric">
                        <strong>Watertight:</strong> {'Yes' if metrics.get('is_watertight') else 'No'}
                    </div>
                </div>
                
                <h3>Issues Detected ({len(issues)})</h3>
            """
            
            if issues:
                for issue in issues:
                    severity = issue.get('severity', 'low')
                    message = issue.get('message', '')
                    html += f'<div class="issue {severity}"><strong>{severity.upper()}:</strong> {message}</div>'
            else:
                html += '<p style="color: #27ae60;">No issues detected against these checks.</p>'
            
            html += "</div>"
        
        html += """
        </body>
        </html>
        """
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"Quality report exported to: {output_path}")


if __name__ == "__main__":
    # Demo usage
    analyzer = QualityAnalyzer()
    
    # Analyze single model
    result = analyzer.analyze_quality("path/to/model.obj", target_platform='mobile_game')
    print(f"Quality Score: {result['score']}/100")
    print(f"Grade: {result['grade']}")
    print(f"Issues: {len(result['issues'])}")
