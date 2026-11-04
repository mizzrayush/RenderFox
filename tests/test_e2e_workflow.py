import os
import sys
import shutil
import unittest
import trimesh
import numpy as np
from pathlib import Path

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.processing.mesh_processor import MeshProcessor
from src.features.quality_analyzer import QualityAnalyzer

class TestEndToEndWorkflow(unittest.TestCase):
    def setUp(self):
        """Set up test environment."""
        self.test_dir = os.path.join(os.path.dirname(__file__), 'temp_e2e_data')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        self.processor = MeshProcessor()
        self.analyzer = QualityAnalyzer()
        
        # Create a dummy mesh (box)
        self.mesh = trimesh.creation.box(extents=[1, 1, 1])
        self.input_path = os.path.join(self.test_dir, 'input_box.obj')
        self.mesh.export(self.input_path)
        print(f"Created test mesh at {self.input_path}")

    def tearDown(self):
        """Clean up test environment."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print("Cleaned up test directory")

    def test_full_pipeline(self):
        """Test the full import -> process -> analyze -> export pipeline."""
        print("\n--- Starting End-to-End Pipeline Test ---")
        
        # 1. Import / Load
        print("1. Loading mesh...")
        # Use trimesh directly as MeshProcessor doesn't have a generic load_mesh
        loaded_mesh = trimesh.load(self.input_path)
        self.assertIsNotNone(loaded_mesh, "Failed to load mesh")
        initial_verts = len(loaded_mesh.vertices)
        print(f"   Loaded mesh with {initial_verts} vertices")
        
        # 2. Process (Scale)
        print("2. Processing mesh (Scaling)...")
        
        processed_path = os.path.join(self.test_dir, 'processed_box.obj')
        # Use transform (scale) as it's robust
        result = self.processor.transform(self.input_path, processed_path, operation='scale', scale_factor=0.5)
        
        self.assertTrue(result['success'], f"Processing failed: {result.get('error')}")
        print(f"   Processing successful: Scaled by {result.get('scale_factor')}")
        
        # 3. Analyze
        print("3. Analyzing quality...")
        analysis_result = self.analyzer.analyze_quality(processed_path)
        self.assertIsNotNone(analysis_result, "Analysis failed")
        self.assertIn('score', analysis_result, "Analysis result missing score")
        print(f"   Quality Score: {analysis_result['score']}")
        print(f"   Issues Found: {len(analysis_result.get('issues', []))}")
        
        # 4. Export / Verify
        print("4. Verifying output...")
        self.assertTrue(os.path.exists(processed_path), "Exported file does not exist")
        final_mesh = trimesh.load(processed_path)
        self.assertTrue(final_mesh.is_watertight, "Final mesh should be watertight (for a box)")
        
        print("--- End-to-End Pipeline Test Passed ---")

if __name__ == '__main__':
    unittest.main()
