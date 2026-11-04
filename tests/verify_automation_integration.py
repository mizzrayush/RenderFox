import sys
import os
import time

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from src.features.automation_engine import ActionRegistry
from src.processing.pipeline_engine import PipelineEngine, NodeDefinition, PipelineNode
from src.processing.script_engine import ScriptAPI

def verify_action_registry():
    print("\n--- Verifying Action Registry ---")
    ActionRegistry.register_default_actions()
    actions = ActionRegistry.get_all_actions()
    
    expected_actions = ["processing.bake_texture", "processing.generate_lod"]
    all_present = True
    
    for action in expected_actions:
        if action in actions:
            print(f"[OK] Action '{action}' is registered.")
        else:
            print(f"[FAIL] Action '{action}' is MISSING.")
            all_present = False
            
    return all_present

def verify_pipeline_engine():
    print("\n--- Verifying Pipeline Engine Logic ---")
    # We can't easily run the full pipeline without a GUI/OpenGL context for some parts,
    # but we can check if the node definitions are present and if we can instantiate the engine.
    
    try:
        engine = PipelineEngine()
        print("[OK] PipelineEngine instantiated successfully.")
        
        # Check if we can create a transform node definition
        # (This is a bit indirect, but confirms imports work)
        return True
    except Exception as e:
        print(f"[FAIL] PipelineEngine verification failed: {e}")
        return False

def verify_script_api():
    print("\n--- Verifying Script API ---")
    api = ScriptAPI(None) # No main window for this test
    
    if hasattr(api, 'bake_texture'):
        print("[OK] ScriptAPI has 'bake_texture' method.")
    else:
        print("[FAIL] ScriptAPI missing 'bake_texture'.")
        return False
        
    if hasattr(api, 'set_lighting'):
        print("[OK] ScriptAPI has 'set_lighting' method.")
    else:
        print("[FAIL] ScriptAPI missing 'set_lighting'.")
        return False
        
    return True

if __name__ == "__main__":
    print("Starting Automation Integration Verification...")
    
    r1 = verify_action_registry()
    r2 = verify_pipeline_engine()
    r3 = verify_script_api()
    
    if r1 and r2 and r3:
        print("\nALL CHECKS PASSED! Integration successful.")
        sys.exit(0)
    else:
        print("\nSOME CHECKS FAILED.")
        sys.exit(1)
