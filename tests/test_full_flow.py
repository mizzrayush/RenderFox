"""
Full Integration Test
Simulates a complete user workflow to verify system integrity.
"""

import sys
import os
import time
import tempfile
import shutil
import trimesh
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import MeshRepairer directly
from src.processing.mesh_processor import MeshRepairer, MeshProcessor
from src.features.ai_asset_tagger import AIAssetTagger
from src.processing.lod_generator import LODGenerator
from src.features.version_control import AssetVersionControl

def create_broken_mesh(path):
    """Create a mesh with holes and duplicates."""
    print(f"Creating broken mesh at {path}...")
    # Create a simple cube
    mesh = trimesh.creation.box(extents=(1, 1, 1))
    
    # Add duplicate vertices
    mesh.vertices = np.vstack([mesh.vertices, mesh.vertices[0]])
    mesh.faces = np.vstack([mesh.faces, [len(mesh.vertices)-1, 0, 1]])
    
    # Remove a face to create a hole
    mesh.faces = mesh.faces[:-2]
    
    mesh.export(path)
    return path

def test_full_flow():
    print("Starting Full Integration Test...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 1. Setup
        input_path = os.path.join(temp_dir, "broken_model.obj")
        create_broken_mesh(input_path)
        
        # 2. Repair (MeshRepairer)
        print("\n[Step 1] Repairing Mesh...")
        repair_output = os.path.join(temp_dir, "repaired_model.obj")
        
        # Use MeshRepairer.auto_repair
        result = MeshRepairer.auto_repair(input_path, repair_output)
        
        if result['success']:
            print("✅ Repair successful")
            print(f"Operations: {result.get('operations')}")
        else:
            print(f"❌ Repair failed: {result.get('error')}")
            return False

        # 3. AI Tagging (AIAssetTagger)
        print("\n[Step 2] Generating AI Tags...")
        try:
            tagger = AIAssetTagger()
            if tagger.model is None and tagger.processor is None:
                 print("⚠️ AI Model not loaded (skipping inference test)")
            else:
                tags = tagger.generate_tags(repair_output)
                print(f"✅ Generated tags: {tags}")
        except Exception as e:
            print(f"⚠️ Tagging skipped/failed (expected if no model): {e}")

        # 4. LOD Generation (LODGenerator)
        print("\n[Step 3] Generating LODs...")
        lod_gen = LODGenerator()
        lods = lod_gen.generate_lods(repair_output, temp_dir)
        
        if lods:
            print(f"✅ Generated {len(lods)} LODs")
            for lod in lods:
                print(f"  - {os.path.basename(lod)}")
        else:
            print("❌ LOD generation failed")
            return False

        # 5. Version Control (AssetVersionControl)
        print("\n[Step 4] Committing Version...")
        vc_dir = os.path.join(temp_dir, ".renderfox_vc")
        vc = AssetVersionControl(vc_dir)
        
        try:
            version_id = vc.save_version(repair_output, "Integration Test Commit")
            history = vc.get_version_history(repair_output)

            # The two lines this replaces printed a check mark over whatever came back, and what
            # came back was `Committed version: None` and `History entries: 0` - the file the
            # repairer had just written is a multi-material .obj, which is a Scene, and nothing
            # here asked. Now every claim this step makes is one it checks.
            if version_id is None or len(history) != 1:
                print(f"❌ Version control committed nothing: id={version_id}, "
                      f"rows={len(history)}")
                return False

            row = history[0]
            snapshot_name = os.path.basename(row['snapshot_path'] or '')
            strays = [n for n in os.listdir(os.path.join(vc_dir, '.versions', 'snapshots'))
                      if n != snapshot_name]
            if strays:
                print(f"❌ Snapshots with no row pointing at them: {strays}")
                return False
            if not os.path.exists(row['snapshot_path']):
                print(f"❌ The row names a snapshot that is not on disk: "
                      f"{row['snapshot_path']}")
                return False
            if not row['polygon_count'] or not row['vertex_count']:
                print(f"❌ The committed repair recorded no geometry: "
                      f"{row['polygon_count']} faces, {row['vertex_count']} vertices")
                return False

            print(f"✅ Committed version {version_id}: {row['polygon_count']} faces, "
                  f"{row['vertex_count']} vertices, 1 row")
        except Exception as e:
            print(f"❌ Version control failed: {e}")
            return False

        print("\n🎉 Full Integration Test Passed!")
        return True

if __name__ == "__main__":
    sys.exit(0 if test_full_flow() else 1)
