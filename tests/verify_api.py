"""
Verify Scripting API
Tests the Python scripting engine bindings and context availability.
"""

import sys
import os
import time

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.processing.script_engine import ScriptEngine
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication

def test_api():
    print("Testing Scripting API...")
    
    # Create dummy app
    app = QApplication(sys.argv)
    
    # Initialize engine
    engine = ScriptEngine()
    
    # Helper to run script synchronously
    def run_sync(code):
        executor = engine.execute_script(code)
        
        results = {}
        
        def on_finished(success, data):
            results['success'] = success
            results['data'] = data
            
        executor.execution_finished.connect(on_finished)
        
        # Run synchronously for testing
        executor.run()
        
        return results

    # Test 1: Basic execution
    print("\nTest 1: Basic Execution")
    result = run_sync("print('Hello from script!')")
    
    if result.get('success'):
        print("✅ Basic execution passed")
        print(f"Output: {result['data'].get('output', '').strip()}")
    else:
        print(f"❌ Basic execution failed: {result.get('data', {}).get('error')}")
        
    # Test 2: API Availability
    print("\nTest 2: API Availability")
    script = """
print(f"API object available: {api is not None}")
print(f"RFX object available: {rfx is not None}")
"""
    result = run_sync(script)
    
    if result.get('success'):
        output = result['data'].get('output', '')
        if "API object available: True" in output and "RFX object available: True" in output:
            print("✅ API binding passed")
        else:
            print(f"❌ API binding failed. Output:\n{output}")
    else:
        print(f"❌ API binding failed: {result.get('data', {}).get('error')}")

    # Test 3: Math operations (checking builtins)
    print("\nTest 3: Builtins")
    script = """
x = 10
y = 20
print(f"Sum: {x + y}")
print(f"Max: {max(x, y)}")
"""
    result = run_sync(script)
    
    if result.get('success'):
        output = result['data'].get('output', '')
        if "Sum: 30" in output and "Max: 20" in output:
            print("✅ Builtins passed")
        else:
            print(f"❌ Builtins failed. Output:\n{output}")
    else:
        print(f"❌ Builtins failed: {result.get('data', {}).get('error')}")

if __name__ == "__main__":
    test_api()
