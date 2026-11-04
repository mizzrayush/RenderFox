"""
Profile LOD Generation
Measures the performance of the LOD generation process.
"""

import sys
import os
import time
import tempfile
import trimesh
import numpy as np

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.processing.lod_generator import LODGenerator, LODSettings

def create_dummy_mesh(output_path, vertices=10000):
    """Create a dummy mesh for testing."""
    print(f"Creating dummy mesh with {vertices} vertices...")
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    # Subdivide to get more vertices if needed
    while len(mesh.vertices) < vertices:
        mesh = mesh.subdivide()
    
    mesh.export(output_path)
    print(f"Saved dummy mesh to {output_path} ({len(mesh.vertices)} vertices, {len(mesh.faces)} faces)")
    return len(mesh.vertices)

def profile_lod():
    print("Profiling LOD Generation...")
    
    # Configure settings
    settings = LODSettings(
        levels=3,
        high_quality_ratio=0.75,
        medium_quality_ratio=0.5,
        low_quality_ratio=0.25
    )
    
    generator = LODGenerator(settings)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, "test_mesh.obj")
        create_dummy_mesh(input_path, vertices=50000)
        
        print(f"\nGenerating {settings.levels} LOD levels...")
        start_time = time.time()
        
        # Use generate_lods
        result_files = generator.generate_lods(input_path, output_dir=temp_dir)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        print(f"\nTotal time: {total_time:.4f} seconds")
        print(f"Average time per level: {total_time / settings.levels:.4f} seconds")
        
        for i, file_path in enumerate(result_files):
            print(f"LOD {i+1}: {os.path.basename(file_path)}")

if __name__ == "__main__":
    profile_lod()
