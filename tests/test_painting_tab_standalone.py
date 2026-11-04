import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.ui.painting_tab import PaintingTab

def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    painting_tab = PaintingTab()
    window.setCentralWidget(painting_tab)
    window.resize(1200, 800)
    window.show()
    
    # Try to load a dummy model if one exists, or just check if viewer initializes
    print("Standalone test started. Check if viewer initializes (black screen vs gray/grid).")
    
    # Mock loading a model (optional, just to trigger logic)
    # painting_tab.set_model("dummy.obj") 
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
