
import sys
import os
from PyQt6.QtWidgets import QApplication

# Mock pymeshlab if not available for UI testing
try:
    import pymeshlab
except ImportError:
    print("PyMeshLab not found, skipping backend test.")

# Add src to path
sys.path.append(os.getcwd())

try:
    from src.processing.texture_baker import TextureBaker
    print("TextureBaker imported successfully.")
    
    baker = TextureBaker()
    print("TextureBaker instantiated.")
    
    from src.ui.preprocessing_tab import PreProcessingTab
    print("PreProcessingTab imported.")
    
    app = QApplication(sys.argv)
    tab = PreProcessingTab()
    print("PreProcessingTab instantiated.")
    
    # Check if baking tab exists
    found = False
    for i in range(tab.operation_tabs.count()):
        if tab.operation_tabs.tabText(i) == "Texture Baking":
            found = True
            break
            
    if found:
        print("Texture Baking tab found in UI.")
    else:
        print("ERROR: Texture Baking tab NOT found.")
        
except Exception as e:
    print(f"Verification Failed: {e}")
    import traceback
    traceback.print_exc()
