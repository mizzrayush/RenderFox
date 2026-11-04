import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ui.settings_tab import SettingsTab

def test_theme_toggle():
    print("Testing Theme Toggle...")
    app = QApplication.instance() or QApplication(sys.argv)
    
    settings_tab = SettingsTab()
    
    # Test Dark Theme
    print("Applying Dark Theme...")
    settings_tab.apply_theme("Dark")
    style = app.styleSheet()
    if "#15161c" in style:
        print("PASS: Modern Dark theme applied successfully.")
    else:
        print("FAIL: Modern Dark theme not applied.")
        
    # Test Light Theme
    print("Applying Light Theme...")
    settings_tab.apply_theme("Light")
    style = app.styleSheet()
    if "#eef1f6" in style and "#2563eb" in style:
        print("PASS: Modern Light theme applied successfully.")
    else:
        print("FAIL: Modern Light theme not applied.")
        
    # Test Midnight Theme
    print("Applying Midnight Theme...")
    settings_tab.apply_theme("Midnight")
    style = app.styleSheet()
    if "#090d16" in style and "#4f46e5" in style:
        print("PASS: Modern Midnight theme applied successfully.")
    else:
        print("FAIL: Modern Midnight theme not applied.")
        
    # Test Auto Theme (defaults to Dark on non-Windows/failure or system setting)
    print("Applying Auto Theme...")
    settings_tab.apply_theme("Auto")
    style = app.styleSheet()
    if style:
        print("PASS: Auto theme logic executed successfully.")
    else:
        print("FAIL: Auto theme returned empty stylesheet.")

if __name__ == "__main__":
    test_theme_toggle()
