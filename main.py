#!/usr/bin/env python3
"""
RenderFox Advanced Batch Renderer
A cross-platform batch rendering manager for 3D artists.
"""

import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
import os

# Suppress TensorFlow/Keras logs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' 
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QSplashScreen
from PyQt6.QtCore import Qt
# from src.ui.main_window import MainWindow  # Moved inside main()
from src.utils.telemetry import get_telemetry


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception handler to catch unhandled errors."""
    # Ignore keyboard interrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"CRITICAL ERROR: {error_msg}", file=sys.stderr)
    
    # Log to telemetry
    try:
        get_telemetry().log_error("crash", str(exc_value), {"traceback": error_msg})
    except:
        pass

    # Show error dialog
    app = QApplication.instance()
    if app:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("RenderFox Crash Reporter")
        msg.setText("An unexpected error occurred.")
        msg.setInformativeText(str(exc_value))
        msg.setDetailedText(error_msg)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()


def main():
    """Main entry point for RenderFox application."""
    # Set AppUserModelID for Windows Taskbar Icon - MUST be before QApplication
    import ctypes
    
    myappid = 'renderfox.studio.app.v1.0.1_refresh' # Changed to force icon refresh
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    sys.excepthook = global_exception_handler
    app = QApplication(sys.argv)
    app.setApplicationName("RenderFox")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("RenderFox Studio")
    
    # AppUserModelID moved to start of main

    # Set application icon
    # Check root and resources folder
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "icon.ico")
    
    if not os.path.exists(icon_path):
        icon_path = os.path.join(base_dir, "resources", "icon.ico")
        
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        print(f"DEBUG: Icon loaded from {icon_path}")
    else:
        print(f"DEBUG: Icon NOT found at {icon_path}")

    # Splash Screen
    splash_path = os.path.join(base_dir, "resources", "splash.png")
    if os.path.exists(splash_path):
        splash_pix = QPixmap(splash_path)
        # Scale if too large (optional, but good for 4k images)
        if splash_pix.width() > 800:
            splash_pix = splash_pix.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation)
            
        splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
        splash.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        splash.setEnabled(False)
        splash.showMessage("Initializing RenderFox...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, Qt.GlobalColor.white)
        splash.show()
        app.processEvents()
    else:
        splash = None
        print(f"Warning: Splash screen not found at {splash_path}")

    # Check for installer model download flag
    if "--download-models" in sys.argv:
        try:
            from src.features.model_downloader import ModelDownloaderDialog
            downloader = ModelDownloaderDialog()
            if downloader.exec():
                print("Models downloaded successfully.")
                sys.exit(0)
            else:
                print("Model download cancelled or failed.")
                sys.exit(1)
        except Exception as e:
            print(f"Error launching downloader: {e}")
            sys.exit(1)
    
    # Register Automation Actions
    # Before the window, because the Automation tab fills its task-type list from the
    # registry while it constructs; registered after, a pcd.* action is in no list the
    # user can reach - on this start or any other.
    # No engine is started here on purpose. The tab owns the app's one engine, and a
    # second instance reads the same tasks file and gives every task its own calendar,
    # so a saved schedule would fire once per live engine.
    try:
        from src.features.automation_engine import ActionRegistry
        from src.processing.point_cloud_processor import PointCloudProcessor
        
        # Create a headless processor for automation
        processor = PointCloudProcessor()
        
        # Register actions - the list comes from the module that answers the verbs, so a
        # point cloud operation cannot be in the pane and missing from Automation. The six
        # calls this replaced wrote their specs as bare types ({'file_path': str}) while
        # ActionRegistry.validate reads rule dicts, so calling any of them raised
        # "type object 'str' has no attribute 'get'" outside execute's own try: the six
        # actions were in the task list and none of them could ever run.
        registered_point_cloud = 0
        for action_id, func, description, params, batch in processor.automation_actions():
            ActionRegistry.register(action_id, func, description, params, batch=batch)
            registered_point_cloud += 1
        print(f"{registered_point_cloud} point cloud automation actions registered.")
        
        print("Core automation actions registered.")

    except Exception as e:
        print(f"Failed to register automation actions: {e}")

    # Create main window
    # Import here to allow splash screen to show first
    from src.ui.main_window import MainWindow
    main_window = MainWindow()
    

    main_window.showMaximized()
    
    # Force Windows native window & taskbar icon
    if sys.platform == 'win32' and os.path.exists(icon_path):
        try:
            hwnd = int(main_window.winId())
            # Load 32x32 for big icon (taskbar / Alt+Tab) and 16x16 for small icon (titlebar)
            hicon_big = ctypes.windll.user32.LoadImageW(
                None, os.path.abspath(icon_path), 1, 32, 32, 0x00000010
            )
            hicon_small = ctypes.windll.user32.LoadImageW(
                None, os.path.abspath(icon_path), 1, 16, 16, 0x00000010
            )
            WM_SETICON = 0x0080
            if hicon_big:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)
            if hicon_small:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)
        except Exception:
            pass
    
    if 'splash' in locals() and splash:
        splash.finish(main_window)
    
    # Start the application event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()