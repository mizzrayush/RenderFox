"""
Benchmark Data Transfer
Compares File I/O vs In-Memory transfer between Trimesh and PyMeshLab.
"""

import sys
import os
import time
import tempfile
import trimesh
import pymeshlab
import numpy as np

def create_dummy_mesh(vertices=100000):
    """Create a dummy mesh."""
    print(f"Creating dummy mesh with {vertices} vertices...")
    mesh = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    return mesh

def benchmark_file_io(mesh, temp_dir):
    """Benchmark File I/O transfer."""
    print("\nBenchmarking File I/O Transfer...")
    start_time = time.time()
    
    # Trimesh -> File
    temp_path = os.path.join(temp_dir, "transfer_test.obj")
    mesh.export(temp_path)
    
    # File -> PyMeshLab
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(temp_path)
    
    # PyMeshLab -> File
    output_path = os.path.join(temp_dir, "transfer_out.obj")
    ms.save_current_mesh(output_path)
    
    # File -> Trimesh
    result_mesh = trimesh.load(output_path)
    
    end_time = time.time()
    print(f"File I/O Time: {end_time - start_time:.4f} seconds")
    return end_time - start_time

def benchmark_memory(mesh):
    """Benchmark In-Memory transfer."""
    print("\nBenchmarking In-Memory Transfer...")
    start_time = time.time()
    
    # Trimesh -> PyMeshLab
    # Extract data
    vertices = mesh.vertices
    faces = mesh.faces
    
    # Create PyMeshLab mesh
    m = pymeshlab.Mesh(vertex_matrix=vertices, face_matrix=faces)
    ms = pymeshlab.MeshSet()
    ms.add_mesh(m)
    
    # PyMeshLab -> Trimesh
    # Extract data
    out_m = ms.current_mesh()
    out_vertices = out_m.vertex_matrix()
    out_faces = out_m.face_matrix()
    
    # Create Trimesh
    result_mesh = trimesh.Trimesh(vertices=out_vertices, faces=out_faces)
    
    end_time = time.time()
    print(f"In-Memory Time: {end_time - start_time:.4f} seconds")
    return end_time - start_time

def run_benchmark():
    mesh = create_dummy_mesh(vertices=100000)
    print(f"Mesh has {len(mesh.vertices)} vertices and {len(mesh.faces)} faces")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        io_time = benchmark_file_io(mesh, temp_dir)
        mem_time = benchmark_memory(mesh)
        
        print(f"\nSpeedup: {io_time / mem_time:.2f}x")

if __name__ == "__main__":
    run_benchmark()
