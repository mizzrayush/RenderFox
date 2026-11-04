#!/usr/bin/env python3
"""
Test script to verify Assimp DLL integration and format converter functionality.
"""

import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.processing.format_converter import FormatConverter

def test_assimp_dll():
    """Test if Assimp DLL is properly loaded and functional"""
    print("=== Testing Assimp DLL Integration ===\n")
    
    # Create format converter instance
    converter = FormatConverter()
    
    # Check library availability
    print("Library Status:")
    for lib, status in converter.libraries_status.items():
        status_text = "✓ Available" if status else "✗ Not Available"
        print(f"  {lib}: {status_text}")
    
    print(f"\nAvailable conversion libraries: {converter.get_available_libraries()}")
    print(f"Supported formats: {converter.get_supported_formats()}")
    
    # Test Assimp specifically
    if converter.libraries_status['assimp']:
        print("\n=== Assimp Library Test ===")
        try:
            import pyassimp
            print("✓ pyassimp imported successfully")
            
            # Try to get version info
            try:
                version = pyassimp.get_version()
                print(f"✓ Assimp version: {version}")
            except:
                print("ℹ Version info not available")
            
            # Check DLL path
            lib_dir = os.path.join(os.path.dirname(__file__), 'lib')
            dll_path = os.path.join(lib_dir, 'assimp-vc143-mt.dll')
            print(f"✓ DLL path: {dll_path}")
            print(f"✓ DLL exists: {os.path.exists(dll_path)}")
            print(f"✓ Lib directory in PATH: {lib_dir in os.environ.get('PATH', '')}")
            
        except Exception as e:
            print(f"✗ Assimp test failed: {e}")
    else:
        print("\n✗ Assimp not available for testing")
    
    # Test format compatibility
    print("\n=== Format Compatibility Test ===")
    test_conversions = [
        ('.fbx', '.obj'),
        ('.obj', '.gltf'),
        ('.gltf', '.ply'),
        ('.stl', '.obj')
    ]
    
    for source, target in test_conversions:
        can_convert = converter.can_convert(source, target)
        status = "✓" if can_convert else "✗"
        print(f"  {source} → {target}: {status}")
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    test_assimp_dll()