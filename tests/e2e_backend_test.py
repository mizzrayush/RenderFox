import os
import sys
import time
import trimesh
import numpy as np
from pathlib import Path

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.processing.mesh_processor import MeshProcessor
from src.features.quality_analyzer import QualityAnalyzer
from src.processing.format_converter import FormatConverter
from src.core.library_manager import LibraryManager

def create_test_mesh(path):
    """Create a simple test mesh (sphere)."""
    print(f"Creating test mesh at {path}...")
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    
    # Intentionally add some issues for testing
    # 1. Add a duplicate vertex
    mesh.vertices = np.vstack([mesh.vertices, mesh.vertices[0]])
    # 2. Add a degenerate face (using the duplicate vertex)
    mesh.faces = np.vstack([mesh.faces, [0, 1, len(mesh.vertices)-1]])
    
    mesh.export(path)
    print(f"Test mesh created: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
    return path

def test_mesh_processing(processor, input_path, output_dir):
    print("\n--- Testing Mesh Processing ---")
    
    # 1. Analysis
    print("Running Analysis...")
    stats = processor.analyze(input_path)
    if stats:
        print(f"Analysis successful: {stats.vertices} verts, {stats.faces} faces")
    else:
        print("Analysis failed!")
        return False

    # 2. Repair (Fix All)
    print("Running Auto-Repair...")
    repair_output = os.path.join(output_dir, "repaired.obj")
    start_time = time.time()
    result = processor.repair(input_path, repair_output, operation='auto')
    duration = time.time() - start_time
    
    if result.get('success'):
        print(f"Repair successful in {duration:.2f}s")
        print(f"Operations performed: {result.get('operations')}")
    else:
        print(f"Repair failed: {result.get('error')}")
        return False

    # 3. Simplification
    print("Running Simplification...")
    simplify_output = os.path.join(output_dir, "simplified.obj")
    # Use explicit face count to avoid potential ratio calculation issues in trimesh versions
    result = processor.simplify(repair_output, simplify_output, method='faces', target_faces=100)
    
    if result.get('success'):
        print(f"Simplification successful. Reduction: {result.get('reduction'):.1f}%")
    else:
        print(f"Simplification failed: {result.get('error')}")
        return False
        
    return True

def test_quality_analysis(analyzer, input_path):
    print("\n--- Testing Quality Analysis ---")
    
    print("Running Quality Analysis...")
    start_time = time.time()
    result = analyzer.analyze_quality(input_path, target_platform='pc_game')
    duration = time.time() - start_time
    
    score = result.get('score')
    grade = result.get('grade')
    issues = result.get('issues', [])
    
    print(f"Analysis complete in {duration:.2f}s")
    print(f"Score: {score}/100 (Grade: {grade})")
    print(f"Issues detected: {len(issues)}")
    
    # Verify sub-scores exist (our recent fix)
    if 'polygon_score' in result:
        print("Sub-scores verified present.")
    else:
        print("WARNING: Sub-scores missing from result!")
        
    return True

def test_format_conversion(converter, input_path, output_dir):
    print("\n--- Testing Format Conversion ---")
    
    output_path = os.path.join(output_dir, "converted.ply")
    print(f"Converting to PLY: {output_path}...")
    
    start_time = time.time()
    result = converter.convert_file(input_path, output_path)
    duration = time.time() - start_time
    
    if result.get('success'):
        print(f"Conversion successful in {duration:.2f}s")
        return True
    else:
        print(f"Conversion failed: {result.get('error')}")
        return False

def test_library_manager(library, input_path):
    print("\n--- Testing Library Manager ---")
    
    # 1. Add Folder
    test_folder = os.path.dirname(input_path)
    print(f"Adding folder to library: {test_folder}")
    library.add_folder(test_folder)
    
    # 2. Scan
    print("Scanning library...")
    library.scan()
    
    # 3. Get Models
    models = library.get_models()
    print(f"Found {len(models)} models in library")
    
    found = False
    for model in models:
        if os.path.basename(model['path']) == os.path.basename(input_path):
            found = True
            print(f"Verified model in library: {model['name']}")
            break
            
    if not found:
        print("WARNING: Test model not found in library after scan!")
        return False
        
    return True

def main():
    print("=== RenderFox Backend End-to-End Test ===\n")
    
    # Initialize QApplication for QPixmap support
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    
    # Setup
    test_dir = os.path.join(os.path.dirname(__file__), "test_data")
    os.makedirs(test_dir, exist_ok=True)
    
    input_mesh_path = os.path.join(test_dir, "test_sphere.obj")
    
    # Initialize components
    processor = MeshProcessor()
    analyzer = QualityAnalyzer()
    converter = FormatConverter()
    library = LibraryManager(db_path=os.path.join(test_dir, "test_library.db"))
    
    try:
        # Create Test Data
        create_test_mesh(input_mesh_path)
        
        # Run Tests
        success = True
        success &= test_mesh_processing(processor, input_mesh_path, test_dir)
        success &= test_quality_analysis(analyzer, input_mesh_path)
        success &= test_format_conversion(converter, input_mesh_path, test_dir)
        success &= test_library_manager(library, input_mesh_path)
        
        print("\n=== Test Summary ===")
        if success:
            print("[PASS] All backend workflows passed successfully!")
        else:
            print("[FAIL] Some tests failed.")
            
    except Exception as e:
        print(f"\n[ERROR] Critical Error during testing: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup (optional, maybe keep for inspection)
        print(f"\nTest artifacts located in: {test_dir}")

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open("tests/test_log.txt", "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

if __name__ == "__main__":
    sys.stdout = Logger()
    main()
