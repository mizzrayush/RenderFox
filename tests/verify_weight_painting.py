
import sys
import os
import numpy as np
import trimesh
from PyQt6.QtWidgets import QApplication
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ui.model_viewer import ModelViewer3D

def verify_weight_painting():
    app = QApplication(sys.argv)
    
    # Create viewer
    viewer = ModelViewer3D()
    
    # Create a simple dummy mesh
    # Triangle: (0,0,0), (1,0,0), (0,1,0)
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0]
    ], dtype=np.float32)
    
    faces = np.array([[0, 1, 2]], dtype=np.int32)
    
    # Manually add mesh to viewer to avoid file loading
    mesh_data = {
        'vertices': vertices,
        'normals': np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype=np.float32),
        'colors': np.array([[1, 1, 1, 1]] * 3, dtype=np.float32),
        'uvs': np.array([[0, 0]] * 3, dtype=np.float32),
        'indices': faces,
        'weights': np.zeros((3, 1), dtype=np.float32),
        'has_weights': True
    }
    
    viewer.meshes.append(mesh_data)
    
    print("Initial weights:")
    print(mesh_data['weights'])
    
    # Test apply_weight
    # Apply weight to vertex 0 (0,0,0) with radius 0.5
    # Vertex 1 is at dist 1.0 (outside)
    # Vertex 2 is at dist 1.0 (outside)
    
    print("\nApplying weight 1.0 to vertex 0 with radius 1.5...")
    # Radius 1.5 covers all vertices
    # Dist to 0: 0.0 -> Falloff 1.0
    # Dist to 1: 1.0 -> Falloff 1.0 - (1.0/1.5) = 0.333
    # Dist to 2: 1.0 -> Falloff 0.333
    
    viewer.apply_weight(0, 0, 1.0, 1.5, "Add")
    
    print("Weights after Add:")
    print(mesh_data['weights'])
    
    # Verify values
    w0 = mesh_data['weights'][0][0]
    w1 = mesh_data['weights'][1][0]
    
    if abs(w0 - 1.0) < 0.001:
        print("Vertex 0 weight correct (1.0)")
    else:
        print(f"Vertex 0 weight incorrect: {w0}")
        
    if abs(w1 - 0.333) < 0.01:
        print("Vertex 1 weight correct (~0.333)")
    else:
        print(f"Vertex 1 weight incorrect: {w1}")
        
    # Test Subtract
    print("\nSubtracting weight 0.5 from vertex 0 with radius 0.1...")
    viewer.apply_weight(0, 0, 0.5, 0.1, "Subtract")
    
    print("Weights after Subtract:")
    print(mesh_data['weights'])
    
    if mesh_data['weights'][0][0] < 0.6:
        print("Vertex 0 weight reduced successfully")
    
    # Test Smooth
    # Reset weights for smooth test
    mesh_data['weights'] = np.array([[1.0], [0.0], [0.5]], dtype=np.float32)
    print("\nReset weights for Smooth test:")
    print(mesh_data['weights'])
    
    print("Smoothing around vertex 0 with radius 2.0...")
    # Avg of 1.0, 0.0, 0.5 is 0.5
    # Strength 1.0 -> should become 0.5
    viewer.apply_weight(0, 0, 1.0, 2.0, "Smooth")
    
    print("Weights after Smooth:")
    print(mesh_data['weights'])
    
    print("\nVerification complete.")

if __name__ == "__main__":
    verify_weight_painting()
