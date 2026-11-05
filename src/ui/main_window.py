"""
Main window for RenderFox application.
"""

import os
from PyQt6.QtWidgets import (QMainWindow, QTabWidget, QVBoxLayout, 
                             QWidget, QMenuBar, QStatusBar, QMessageBox)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QIcon

from .dashboard_tab import DashboardTab
from .preprocessing_tab import PreProcessingTab
from .postprocessing_tab import PostProcessingTab
from .model_tab import ModelTab
from .animation_tab import AnimationTab
from .settings_tab import SettingsTab
from .library_tab import LibraryTab
from .automation_tab import AutomationTab
from .point_clouds_tab import PointCloudsTab
from .mesh_tools_tab import MeshToolsTab
from .performance_tab import PerformanceTab
from .diagnostics_tab import DiagnosticsTab
from .scripting_tab import ScriptingTab
from ..core.job_manager import JobManager
from .pipeline_editor_tab import PipelineEditorTab
from .rendering_tab import RenderingTab
from .feedback_dialog import FeedbackDialog
from .styles import get_theme_stylesheet, MODERN_DARK_THEME
from .icon_provider import get_tab_icon, get_icon

class MainWindow(QMainWindow):
    """Main application window with tabbed interface."""
    
    def minimumSizeHint(self) -> QSize:
        """Provide a sensible minimum size hint to prevent Windows OS geometry clamping."""
        return QSize(960, 580)
    
    def __init__(self):
        super().__init__()
        self.job_manager = JobManager()
        self.init_ui()
        self.setup_menu()
        self.setup_status_bar()
        
        # Apply Saved Theme
        saved_theme = getattr(self, 'settings_tab', None)
        theme_name = self.settings_tab.settings.value("theme", "Dark") if hasattr(self, 'settings_tab') else "Dark"
        self.setStyleSheet(get_theme_stylesheet(theme_name))
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("RenderFox")
        self.setMinimumSize(960, 580)
        self.setGeometry(100, 100, 1280, 820)
        
        # Explicitly set window icon to prevent it from reverting
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        icon_path = os.path.join(base_dir, "icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(base_dir, "resources", "icon.ico")
            
        if os.path.exists(icon_path):
            print(f"DEBUG: MainWindow setting icon from {icon_path}")
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"DEBUG: MainWindow icon NOT found at {icon_path}")
        
        # Create central widget with tab layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.dashboard_tab = DashboardTab(self.job_manager)
        self.model_tab = ModelTab()
        self.preprocessing_tab = PreProcessingTab()
        self.postprocessing_tab = PostProcessingTab()
        self.library_tab = LibraryTab()
        self.automation_tab = AutomationTab()
        self.point_clouds_tab = PointCloudsTab()
        self.mesh_tools_tab = MeshToolsTab()
        self.performance_tab = PerformanceTab()
        self.diagnostics_tab = DiagnosticsTab()
        self.scripting_tab = ScriptingTab(main_window=self)
        self.pipeline_tab = PipelineEditorTab(self.job_manager)
        self.animation_tab = AnimationTab()
        self.rendering_tab = RenderingTab()
        self.settings_tab = SettingsTab()
        
        # Connect tab signals for inter-tab communication
        # Connect tab signals for inter-tab communication
        self.setup_tab_connections()
        
        # Connect Rendering Tab status message
        self.rendering_tab.status_message.connect(self.statusBar().showMessage)
        
        # Connect settings tab signals
        self.settings_tab.theme_changed.connect(self.on_theme_changed)
        
        # Add tabs with vector icons and clean industry typography
        self.tab_widget.addTab(self.library_tab, get_tab_icon("library"), "Library")
        self.tab_widget.addTab(self.dashboard_tab, get_tab_icon("batch_render"), "Batch Render")
        self.tab_widget.addTab(self.model_tab, get_tab_icon("models"), "Models")
        self.tab_widget.addTab(self.point_clouds_tab, get_tab_icon("point_clouds"), "Point Clouds")
        self.tab_widget.addTab(self.mesh_tools_tab, get_tab_icon("mesh_tools"), "Mesh Tools")
        self.tab_widget.addTab(self.animation_tab, get_tab_icon("animation"), "Animation")
        self.tab_widget.addTab(self.rendering_tab, get_tab_icon("rendering"), "Rendering")
        self.tab_widget.addTab(self.preprocessing_tab, get_tab_icon("preprocessing"), "Pre-Processing")
        self.tab_widget.addTab(self.postprocessing_tab, get_tab_icon("postprocessing"), "Post-Processing")
        self.tab_widget.addTab(self.automation_tab, get_tab_icon("automation"), "Automation")
        self.tab_widget.addTab(self.scripting_tab, get_tab_icon("scripting"), "Scripting")
        self.tab_widget.addTab(self.pipeline_tab, get_tab_icon("pipeline"), "Pipeline")
        self.tab_widget.addTab(self.performance_tab, get_tab_icon("performance"), "Performance")
        self.tab_widget.addTab(self.diagnostics_tab, get_tab_icon("diagnostics"), "Diagnostics")
        self.tab_widget.addTab(self.settings_tab, get_tab_icon("settings"), "Settings")
        # This is just for any additional handling needed
    
    def setup_menu(self):
        """Setup the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        new_job_action = QAction('New Job', self)
        new_job_action.setShortcut('Ctrl+N')
        new_job_action.triggered.connect(self.dashboard_tab.add_new_job)
        file_menu.addAction(new_job_action)
        
        file_menu.addSeparator()
        
        # Add model-related menu items
        load_model_action = QAction('Load Model...', self)
        load_model_action.setShortcut('Ctrl+O')
        load_model_action.triggered.connect(self.load_model_shortcut)
        file_menu.addAction(load_model_action)
        
        load_model_folder_action = QAction('Load Model Folder...', self)
        load_model_folder_action.setShortcut('Ctrl+Shift+O')
        load_model_folder_action.triggered.connect(self.load_model_folder_shortcut)
        file_menu.addAction(load_model_folder_action)
        
        # Point cloud loading
        load_pointcloud_action = QAction('Load Point Cloud...', self)
        load_pointcloud_action.setShortcut('Ctrl+P')
        load_pointcloud_action.triggered.connect(self.load_pointcloud_shortcut)
        file_menu.addAction(load_pointcloud_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu('Edit')
        
        preferences_action = QAction('Preferences...', self)
        preferences_action.setShortcut('Ctrl+,')
        preferences_action.triggered.connect(self.open_preferences)
        edit_menu.addAction(preferences_action)
        
        # Queue menu
        queue_menu = menubar.addMenu('Queue')
        
        start_action = QAction('Start Queue', self)
        start_action.setShortcut('F5')
        start_action.triggered.connect(self.job_manager.start_processing)
        queue_menu.addAction(start_action)
        
        stop_action = QAction('Stop Queue', self)
        stop_action.setShortcut('F6')
        stop_action.triggered.connect(self.job_manager.stop_processing)
        queue_menu.addAction(stop_action)
        
        queue_menu.addSeparator()
        
        automation_action = QAction('Setup Automation...', self)
        automation_action.setShortcut('Ctrl+Shift+A')
        automation_action.triggered.connect(self.open_automation)
        queue_menu.addAction(automation_action)
        
        # Models menu
        models_menu = menubar.addMenu('Models')
        
        analyze_action = QAction('Analyze Selected Model', self)
        analyze_action.setShortcut('Ctrl+A')
        analyze_action.triggered.connect(self.analyze_model_shortcut)
        models_menu.addAction(analyze_action)
        
        batch_analyze_action = QAction('Batch Analysis', self)
        batch_analyze_action.setShortcut('Ctrl+Shift+B')
        batch_analyze_action.triggered.connect(self.batch_analyze_shortcut)
        models_menu.addAction(batch_analyze_action)
        
        models_menu.addSeparator()
        
        convert_action = QAction('Convert Format...', self)
        convert_action.setShortcut('Ctrl+T')
        convert_action.triggered.connect(self.convert_model_shortcut)
        models_menu.addAction(convert_action)
        
        mesh_tools_action = QAction('Mesh Tools...', self)
        mesh_tools_action.setShortcut('Ctrl+M')
        mesh_tools_action.triggered.connect(self.open_mesh_tools)
        models_menu.addAction(mesh_tools_action)
        
        # Tools menu
        tools_menu = menubar.addMenu('Tools')
        
        scripting_action = QAction('Script Editor...', self)
        scripting_action.setShortcut('F4')
        scripting_action.triggered.connect(self.open_scripting)
        tools_menu.addAction(scripting_action)
        
        performance_action = QAction('Performance Monitor...', self)
        performance_action.setShortcut('F3')
        performance_action.triggered.connect(self.open_performance)
        tools_menu.addAction(performance_action)
        
        diagnostics_action = QAction('System Diagnostics...', self)
        diagnostics_action.setShortcut('F2')
        diagnostics_action.triggered.connect(self.open_diagnostics)
        tools_menu.addAction(diagnostics_action)
        
        tools_menu.addSeparator()
        
        library_action = QAction('Model Library...', self)
        library_action.setShortcut('Ctrl+L')
        library_action.triggered.connect(self.open_library)
        tools_menu.addAction(library_action)
        
        # View menu
        view_menu = menubar.addMenu('View')
        
        dashboard_action = QAction('Dashboard', self)
        dashboard_action.setShortcut('F1')
        dashboard_action.triggered.connect(lambda: self.switch_to_tab(0))
        view_menu.addAction(dashboard_action)
        
        models_view_action = QAction('Models', self)
        models_view_action.setShortcut('F7')
        models_view_action.triggered.connect(lambda: self.switch_to_tab(1))
        view_menu.addAction(models_view_action)
        
        library_view_action = QAction('Library', self)
        library_view_action.setShortcut('F8')
        library_view_action.triggered.connect(lambda: self.switch_to_tab(2))
        view_menu.addAction(library_view_action)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        user_guide_action = QAction('User Guide', self)
        user_guide_action.triggered.connect(self.open_user_guide)
        help_menu.addAction(user_guide_action)
        
        api_docs_action = QAction('API Documentation', self)
        api_docs_action.triggered.connect(self.open_api_docs)
        help_menu.addAction(api_docs_action)
        
        help_menu.addSeparator()
        
        about_action = QAction('About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def load_model_shortcut(self):
        """Load model via keyboard shortcut."""
        self.tab_widget.setCurrentWidget(self.model_tab)
        if hasattr(self.model_tab, 'load_model'):
            self.model_tab.load_model()
        elif hasattr(self.model_tab, 'load_single_model'):
            self.model_tab.load_single_model()
    
    def load_model_folder_shortcut(self):
        """Load model folder via keyboard shortcut."""
        self.tab_widget.setCurrentWidget(self.model_tab)
        if hasattr(self.model_tab, 'load_folder'):
            self.model_tab.load_folder()
        elif hasattr(self.model_tab, 'load_model_folder'):
            self.model_tab.load_model_folder()
    
    def load_pointcloud_shortcut(self):
        """Load point cloud via keyboard shortcut."""
        self.tab_widget.setCurrentWidget(self.point_clouds_tab)
        self.point_clouds_tab.load_point_cloud()
    
    def analyze_model_shortcut(self):
        """Analyze model via keyboard shortcut."""
        self.tab_widget.setCurrentWidget(self.model_tab)
        self.model_tab.analyze_selected_model()
    
    def batch_analyze_shortcut(self):
        """Batch analyze models via keyboard shortcut."""
        self.tab_widget.setCurrentWidget(self.model_tab)
        self.model_tab.batch_analyze_models()
    
    def convert_model_shortcut(self):
        """Convert model via keyboard shortcut."""
        self.tab_widget.setCurrentWidget(self.model_tab)
        self.model_tab.convert_selected_model()
    
    def open_preferences(self):
        """Open preferences dialog."""
        self.tab_widget.setCurrentWidget(self.settings_tab)
    
    def open_automation(self):
        """Open automation setup."""
        self.tab_widget.setCurrentWidget(self.automation_tab)
    
    def open_mesh_tools(self):
        """Open mesh tools."""
        self.tab_widget.setCurrentWidget(self.mesh_tools_tab)
    
    def open_scripting(self):
        """Open scripting editor."""
        self.tab_widget.setCurrentWidget(self.scripting_tab)
    
    def open_performance(self):
        """Open performance monitor."""
        self.tab_widget.setCurrentWidget(self.performance_tab)
    
    def open_diagnostics(self):
        """Open diagnostics."""
        self.tab_widget.setCurrentWidget(self.diagnostics_tab)
    
    def open_library(self):
        """Open model library."""
        self.tab_widget.setCurrentWidget(self.library_tab)
    
    def switch_to_tab(self, index):
        """Switch to a specific tab."""
        self.tab_widget.setCurrentIndex(index)
    
    def open_user_guide(self):
        """Open user guide."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
        dialog = QDialog(self)
        dialog.setWindowTitle("RenderFox User Guide")
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        
        guide_path = os.path.join(os.getcwd(), "USER_GUIDE.md")
        if os.path.exists(guide_path):
            with open(guide_path, "r", encoding="utf-8") as f:
                content = f.read()
            browser.setMarkdown(content)
        else:
            browser.setPlainText("RenderFox User Guide file (USER_GUIDE.md) not found.")
            
        layout.addWidget(browser)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()
    
    def open_api_docs(self):
        """Open API Documentation."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
        dialog = QDialog(self)
        dialog.setWindowTitle("RenderFox Scripting API Documentation")
        dialog.resize(750, 550)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        docs = (
            "# RenderFox Scripting API (rfx)\n\n"
            "The `rfx` object is available in the Scripting tab for automation.\n\n"
            "### Available Methods:\n"
            "- `rfx.load_model(path)`: Load 3D model and return ModelWrapper\n"
            "- `rfx.get_library_models(tags=None, format_filter=None)`: Retrieve model metadata dicts\n"
            "- `rfx.add_to_job_queue(path, software='blender')`: Add background render job\n"
            "- `rfx.convert_format(input_path, output_path)`: Convert model formats\n"
            "- `rfx.generate_lods(path, levels=3)`: Create LOD series\n"
            "- `rfx.analyze_quality(path)`: Analyze geometry and return quality report\n"
            "- `rfx.repair_mesh(path, output_path)`: Auto-fix holes and duplicate vertices\n\n"
            "### ModelWrapper Methods:\n"
            "- `model.simplify(ratio=0.5)`\n"
            "- `model.smooth(iterations=1)`\n"
            "- `model.scale(factor=2.0)`\n"
            "- `model.center()`\n"
            "- `model.save(output_path)`\n"
            "- `model.get_stats()`\n"
        )
        browser.setMarkdown(docs)
        layout.addWidget(browser)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()
    
    def setup_status_bar(self):
        """Setup the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # Connect to job manager signals
        self.job_manager.queue_updated.connect(self.update_status)
    
    def update_status(self):
        """Update status bar with queue information."""
        jobs = self.job_manager.get_all_jobs()
        pending_count = sum(1 for job in jobs if job.status.value == "pending")
        total_count = len(jobs)
        
        if self.job_manager.is_processing:
            status_text = f"Processing queue - {pending_count} pending of {total_count} total jobs"
        else:
            status_text = f"Ready - {pending_count} pending of {total_count} total jobs"
        
        self.status_bar.showMessage(status_text)
    
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(self, "About RenderFox",
                         "RenderFox Advanced Batch Renderer v1.0.0\n\n"
                         "A cross-platform batch rendering manager for 3D artists.\n"
                         "Built with Python and PyQt6.")
    
    def closeEvent(self, event):
        """Handle application close event."""
        # Check for active jobs
        if self.job_manager.is_processing:
            reply = QMessageBox.question(self, 'Exit RenderFox',
                                       'Rendering is in progress. Are you sure you want to exit?',
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            
            self.job_manager.stop_processing()

        # Automation runs on its own threads: a close without this question would
        # cut a batch mid-file, and stop() is what ends the scheduler's polling.
        engine = self.automation_tab.automation_engine
        live = engine.live_work()
        if live:
            reply = QMessageBox.question(
                self, 'Exit RenderFox',
                'Automation is still running:\n  %s\n\nExit anyway?' % '\n  '.join(live),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        engine.stop()

        # Auto-save settings if enabled
        if hasattr(self, 'settings_tab') and hasattr(self.settings_tab, 'auto_save_workspace'):
            if self.settings_tab.auto_save_workspace.isChecked():
                try:
                    self.settings_tab.save_settings(show_confirmation=False)
                except TypeError:
                    self.settings_tab.save_settings()
        
        event.accept()

    def open_in_model_viewer(self, file_path):
        """Open a model file in the Model Viewer tab."""
        self.tab_widget.setCurrentWidget(self.model_tab)
        
        # Load the model in Model Viewer
        if hasattr(self.model_tab, 'load_model_file'):
            self.model_tab.load_model_file(file_path)
        elif hasattr(self.model_tab, 'load_model'):
            self.model_tab.load_model(file_path)
        else:
            QMessageBox.information(
                self, 
                "Model Viewer", 
                f"Opening model in Model Viewer:\n{file_path}"
            )
            
    def open_in_point_clouds(self, file_path):
        """Open a point cloud file in the Point Clouds tab."""
        self.tab_widget.setCurrentWidget(self.point_clouds_tab)
        
        # Load the point cloud
        if hasattr(self.point_clouds_tab, 'load_point_cloud_file'):
            self.point_clouds_tab.load_point_cloud_file(file_path)
        elif hasattr(self.point_clouds_tab, 'load_model'):
            self.point_clouds_tab.load_model(file_path)

    def load_model_globally(self, file_path):
        """Load a model into all applicable tabs."""
        # 1. Model Viewer
        if hasattr(self.model_tab, 'load_model_file'):
            self.model_tab.load_model_file(file_path)
        elif hasattr(self.model_tab, 'load_model'):
            self.model_tab.load_model(file_path)
            
        # 2. Mesh Tools
        if hasattr(self.mesh_tools_tab, 'load_mesh_file'):
            self.mesh_tools_tab.load_mesh_file(file_path)
            
        # 3. Pre-processing
        if hasattr(self.preprocessing_tab, 'load_model'):
            self.preprocessing_tab.load_model(file_path)
            
        # 4. Post-processing (add to list)
        if hasattr(self.postprocessing_tab, 'load_file'):
            self.postprocessing_tab.load_file(file_path)
            
        # Switch to Model Viewer as primary view
        self.tab_widget.setCurrentWidget(self.model_tab)
        
        QMessageBox.information(self, "Global Load", 
                              f"Model loaded in all tabs:\n{file_path}")

    def setup_tab_connections(self):
        """Connect signals between tabs."""
        # Library Tab connections
        self.library_tab.open_mesh_tools_requested.connect(self.open_in_mesh_tools)
        self.library_tab.open_preprocessing_requested.connect(self.open_in_preprocessing)
        self.library_tab.open_postprocessing_requested.connect(self.open_in_postprocessing)
        self.library_tab.open_rendering_requested.connect(self.open_in_rendering)
        self.library_tab.open_animation_requested.connect(self.open_in_animation)
        self.library_tab.load_globally_requested.connect(self.load_model_globally)

        # Point Clouds Tab connections
        self.point_clouds_tab.mesh_generated.connect(self.open_in_mesh_tools)

        # Mesh Tools Tab connections
        self.mesh_tools_tab.add_to_library_requested.connect(self.library_tab.add_model_to_library)

    
    def open_in_animation(self, file_path):
        """Open a model file in the Animation tab."""
        self.tab_widget.setCurrentWidget(self.animation_tab)
        if hasattr(self.animation_tab, 'load_model_from_path'):
            self.animation_tab.load_model_from_path(file_path)

    def open_in_rendering(self, file_path):
        """Open a model file in the Rendering tab."""
        self.tab_widget.setCurrentWidget(self.rendering_tab)
        if hasattr(self.rendering_tab, 'set_model'):
            self.rendering_tab.set_model(file_path)

    def open_in_mesh_tools(self, file_path):
        """Open a model file in the Mesh Tools tab."""
        self.tab_widget.setCurrentWidget(self.mesh_tools_tab)
        if hasattr(self.mesh_tools_tab, 'load_mesh_file'):
            self.mesh_tools_tab.load_mesh_file(file_path)

    def open_in_preprocessing(self, file_path):
        """Open a model file in the Pre-processing tab."""
        self.tab_widget.setCurrentWidget(self.preprocessing_tab)
        if hasattr(self.preprocessing_tab, 'load_model'):
            self.preprocessing_tab.load_model(file_path)

    def open_in_postprocessing(self, file_path):
        """Open a file in the Post-processing tab."""
        self.tab_widget.setCurrentWidget(self.postprocessing_tab)
        if hasattr(self.postprocessing_tab, 'load_file'):
            self.postprocessing_tab.load_file(file_path)

    def open_feedback(self):
        """Open the feedback dialog."""
        dialog = FeedbackDialog(self)
        dialog.exec()

    def on_theme_changed(self, theme_name):
        """Handle theme change signal."""
        self.setStyleSheet(get_theme_stylesheet(theme_name))
