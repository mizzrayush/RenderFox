"""
3D Thumbnail Renderer for RenderFox
Generates high-quality, shaded isometric 3D thumbnails with studio 3-point lighting,
depth-sorted polygons, ambient occlusion, ground contact shadows, and format badges.
Hardware-independent software rasterizer that runs reliably in any environment.
"""

import os
import sys
import numpy as np
from typing import Optional

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

from PyQt6.QtGui import (
    QImage, QPainter, QColor, QPolygonF, QPen, QBrush, 
    QRadialGradient, QLinearGradient, QFont
)
from PyQt6.QtCore import QPointF, Qt, QCoreApplication


def generate_3d_thumbnail(
    model_path: str, 
    output_path: str, 
    size: int = 256,
    bg_color: str = "#181a22",
    accent_color: tuple = (145, 175, 225)
) -> dict:
    """
    Generate a high-contrast, shaded 3D preview thumbnail for a 3D model or point cloud.

    'rendered' says whether the model itself is in the picture. Without it a caller cannot
    tell a thumbnail of the asset from the fallback wireframe badge, and reporting the
    badge as the model is exactly the kind of claim this app is meant to stop making.
    'faces' is how many triangles reached the image, so a dense model that should have been
    decimated before drawing cannot quietly be drawn whole.
    """
    render_error = ""
    faces_drawn = 0
    try:
        if QCoreApplication.instance() is None:
            # QImage and QPainter abort the process when there is no application to draw
            # with, which is a worse answer than saying the picture could not be made.
            return {'success': False, 'rendered': False,
                    'error': 'there is no running application to draw the image with'}
        try:
            size = int(size)
        except (TypeError, ValueError):
            return {'success': False, 'rendered': False,
                    'error': f'size {size!r} is not a number of pixels'}
        if not 16 <= size <= 4096:
            # The floor is not taste: the background grid divides by size // 8, and the
            # ceiling is what this function is willing to allocate as one ARGB32 image.
            # A caller that passes a number outside this range gets a verdict, not an
            # allocation failure inside Qt - a failed QImage aborts the whole process.
            return {'success': False, 'rendered': False,
                    'error': f'size {size} is outside the 16..4096 pixels this can draw'}
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor(bg_color))
        
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Studio dark background vignette
        grad = QRadialGradient(size / 2.0, size / 2.0, size * 0.72)
        grad.setColorAt(0.0, QColor("#222634"))
        grad.setColorAt(0.7, QColor("#161820"))
        grad.setColorAt(1.0, QColor("#0f1016"))
        painter.fillRect(0, 0, size, size, QBrush(grad))
        
        # Subtle viewport floor grid lines
        painter.setPen(QPen(QColor(255, 255, 255, 8), 1))
        step = size // 8
        for i in range(step, size, step):
            painter.drawLine(0, i, size, i)
            painter.drawLine(i, 0, i, size)
            
        # Ground contact shadow
        shadow_grad = QRadialGradient(size / 2.0, size * 0.82, size * 0.38)
        shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 180))
        shadow_grad.setColorAt(0.5, QColor(0, 0, 0, 90))
        shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(shadow_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(size / 2.0, size * 0.82), size * 0.38, size * 0.09)
        
        mesh_rendered = False
        
        if TRIMESH_AVAILABLE and os.path.exists(model_path):
            try:
                loaded = trimesh.load(model_path)
                if isinstance(loaded, trimesh.Scene):
                    geoms = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
                    mesh = trimesh.util.concatenate(geoms) if geoms else None
                else:
                    mesh = loaded
                    
                if mesh and hasattr(mesh, 'vertices') and len(mesh.vertices) > 0 and hasattr(mesh, 'faces') and len(mesh.faces) > 0:
                    # Simplify dense meshes for instantaneous thumbnail generation
                    if len(mesh.faces) > 2500:
                        try:
                            # face_count, not percent: the first positional argument is the
                            # fraction of faces to keep, and 2500 of those is no simplification.
                            mesh = mesh.simplify_quadric_decimation(face_count=2500)
                        except Exception:
                            pass
                            
                    verts = np.array(mesh.vertices, dtype=np.float64)
                    faces = np.array(mesh.faces)
                    faces_drawn = len(faces)
                    
                    # Center and scale to unit cube [-0.5, 0.5]
                    bbox_min = verts.min(axis=0)
                    bbox_max = verts.max(axis=0)
                    center = (bbox_min + bbox_max) / 2.0
                    scale = np.max(bbox_max - bbox_min)
                    if scale == 0: 
                        scale = 1.0
                    verts = (verts - center) / scale
                    
                    # Standard 3D DCC Isometric View (Pitch = 22°, Yaw = -35°)
                    pitch = np.radians(22)
                    yaw = np.radians(-35)
                    
                    Rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
                    Ry = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
                    R = Rx @ Ry
                    rot_verts = verts @ R.T
                    
                    # Screen projection coordinates
                    screen_x = size / 2.0 + rot_verts[:, 0] * (size * 0.72)
                    screen_y = size / 2.0 - rot_verts[:, 1] * (size * 0.72)
                    screen_z = rot_verts[:, 2]
                    
                    # Compute face centers and normals for lighting
                    v0 = rot_verts[faces[:, 0]]
                    v1 = rot_verts[faces[:, 1]]
                    v2 = rot_verts[faces[:, 2]]
                    
                    face_z = (screen_z[faces[:, 0]] + screen_z[faces[:, 1]] + screen_z[faces[:, 2]]) / 3.0
                    
                    # Normal calculation in rotated view space
                    normals = np.cross(v1 - v0, v2 - v0)
                    norm_len = np.linalg.norm(normals, axis=1, keepdims=True)
                    norm_len[norm_len == 0] = 1.0
                    normals = normals / norm_len
                    
                    # Studio 3-point lighting setup
                    key_light = np.array([0.55, 0.75, 0.5])
                    key_light /= np.linalg.norm(key_light)
                    fill_light = np.array([-0.6, 0.25, 0.3])
                    fill_light /= np.linalg.norm(fill_light)
                    rim_light = np.array([0.0, -0.8, -0.6])
                    rim_light /= np.linalg.norm(rim_light)
                    
                    key_dot = np.maximum(0.0, np.dot(normals, key_light))
                    fill_dot = np.maximum(0.0, np.dot(normals, fill_light))
                    rim_dot = np.maximum(0.0, np.dot(normals, rim_light))
                    
                    # Back-to-front depth sorting (Painter's algorithm)
                    sort_idx = np.argsort(face_z)
                    
                    base_r, base_g, base_b = accent_color
                    
                    for fi in sort_idx:
                        # Back-face culling check
                        if normals[fi, 2] < -0.05:
                            continue
                            
                        intensity = 0.22 + 0.65 * key_dot[fi] + 0.22 * fill_dot[fi] + 0.15 * rim_dot[fi]
                        intensity = min(1.0, max(0.0, intensity))
                        
                        r = int(min(255, base_r * intensity))
                        g = int(min(255, base_g * intensity))
                        b = int(min(255, base_b * intensity))
                        
                        poly = QPolygonF([
                            QPointF(screen_x[faces[fi, 0]], screen_y[faces[fi, 0]]),
                            QPointF(screen_x[faces[fi, 1]], screen_y[faces[fi, 1]]),
                            QPointF(screen_x[faces[fi, 2]], screen_y[faces[fi, 2]])
                        ])
                        
                        painter.setBrush(QBrush(QColor(r, g, b)))
                        painter.setPen(QPen(QColor(max(0, r - 30), max(0, g - 30), max(0, b - 30), 80), 0.5))
                        painter.drawPolygon(poly)
                        
                    mesh_rendered = True
                else:
                    render_error = f"{os.path.basename(model_path)} holds no triangle mesh"
                    
            except Exception as e:
                # Mesh load failed, fall back to isometric wireframe badge
                render_error = f"the model could not be read: {e}"
        elif not TRIMESH_AVAILABLE:
            render_error = "Trimesh is not installed, so no model can be read"
        else:
            render_error = f"there is no file at {model_path}"
                
        # If geometry rendering was not possible, draw an elegant isometric 3D wireframe box
        if not mesh_rendered:
            cx, cy = size / 2.0, size / 2.0
            r = size * 0.28
            
            # Draw isometric box
            top_face = QPolygonF([
                QPointF(cx, cy - r),
                QPointF(cx + r * 0.866, cy - r * 0.5),
                QPointF(cx, cy),
                QPointF(cx - r * 0.866, cy - r * 0.5)
            ])
            left_face = QPolygonF([
                QPointF(cx - r * 0.866, cy - r * 0.5),
                QPointF(cx, cy),
                QPointF(cx, cy + r),
                QPointF(cx - r * 0.866, cy + r * 0.5)
            ])
            right_face = QPolygonF([
                QPointF(cx, cy),
                QPointF(cx + r * 0.866, cy - r * 0.5),
                QPointF(cx + r * 0.866, cy + r * 0.5),
                QPointF(cx, cy + r)
            ])
            
            painter.setBrush(QBrush(QColor("#353b48")))
            painter.setPen(QPen(QColor("#57606f"), 1.5))
            painter.drawPolygon(top_face)
            
            painter.setBrush(QBrush(QColor("#2f3542")))
            painter.drawPolygon(left_face)
            
            painter.setBrush(QBrush(QColor("#1e272e")))
            painter.drawPolygon(right_face)
            
        # Draw sleek format badge at top-right
        ext = os.path.splitext(model_path)[1].upper().replace('.', '') or '3D'
        badge_w, badge_h = 46, 20
        badge_x, badge_y = size - badge_w - 10, 10
        
        painter.setBrush(QBrush(QColor(22, 26, 36, 220)))
        painter.setPen(QPen(QColor(75, 123, 236, 200), 1))
        painter.drawRoundedRect(int(badge_x), int(badge_y), badge_w, badge_h, 4, 4)
        
        painter.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        painter.setPen(QColor(210, 225, 255))
        painter.drawText(int(badge_x), int(badge_y), badge_w, badge_h, Qt.AlignmentFlag.AlignCenter, ext)
        
        painter.end()
        if not img.save(output_path, "PNG"):
            return {'success': False, 'rendered': mesh_rendered,
                    'error': f'{output_path} could not be written as a PNG'}
        return {'success': True,
                'rendered': mesh_rendered,
                'faces': faces_drawn if mesh_rendered else 0,
                'error': '' if mesh_rendered else render_error}
        
    except Exception as e:
        return {'success': False, 'rendered': False, 'error': str(e)}
