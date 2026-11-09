"""
Main window for RenderFox application.
"""

import os
import logging
from PyQt6.QtWidgets import (QMainWindow, QTabWidget, QTabBar, QVBoxLayout, 
                             QWidget, QMenuBar, QStatusBar, QMessageBox,
                             QStyleOptionTab, QStyle, QToolTip)
from PyQt6.QtCore import Qt, QSize, QRect, QPoint, QEvent
from PyQt6.QtGui import QAction, QIcon, QPainter, QColor, QPen

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
from ..utils.app_paths import bundled
from ..core.job_manager import JobManager
from ..core.asset_selection import AssetSelection
from .pipeline_editor_tab import PipelineEditorTab
from .rendering_tab import RenderingTab
from .feedback_dialog import FeedbackDialog
from .studio_header import StudioHeaderBar
from .styles import get_theme_stylesheet, MODERN_DARK_THEME
from .icon_provider import get_tab_icon, get_icon

logger = logging.getLogger(__name__)

class WorkspaceRailTabBar(QTabBar):
    """Continuous left workspace rail with grouped dividers and bottom-anchored settings."""

    TAB_H = 28
    DIV_H = 8
    SETTINGS_INDEX = 14
    DIVIDER_AFTER_INDICES = (2, 5, 8, 13)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspaceRailBar")
        self._hover_index = -1
        self.setMouseTracking(True)

    def _calc_tab_y(self, index: int) -> int:
        if index <= 2:
            return index * self.TAB_H
        elif index <= 5:
            return (3 * self.TAB_H + self.DIV_H) + (index - 3) * self.TAB_H
        elif index <= 8:
            return (6 * self.TAB_H + 2 * self.DIV_H) + (index - 6) * self.TAB_H
        elif index <= 13:
            return (9 * self.TAB_H + 3 * self.DIV_H) + (index - 9) * self.TAB_H
        else:
            normal_y = 14 * self.TAB_H + 4 * self.DIV_H
            bottom_y = self.height() - self.TAB_H - 4
            return max(normal_y, bottom_y)

    def sizeHint(self) -> QSize:
        sz = super().sizeHint()
        min_h = 15 * self.TAB_H + 4 * self.DIV_H + 8
        h = max(min_h, self.parent().height()) if self.parent() else min_h
        return QSize(sz.width(), h)

    def tabRect(self, index: int) -> QRect:
        r = super().tabRect(index)
        y = self._calc_tab_y(index)
        return QRect(r.x(), y, r.width(), self.TAB_H)

    def tabAt(self, pos: QPoint) -> int:
        for i in range(self.count()):
            if self.tabRect(i).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        hover = self.tabAt(pos)
        if hover != self._hover_index:
            self._hover_index = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        idx = self.tabAt(pos)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            super().mousePressEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            idx = self.tabAt(event.pos())
            if idx >= 0:
                tip = self.tabToolTip(idx)
                if tip:
                    QToolTip.showText(event.globalPos(), tip, self, self.tabRect(idx))
                    return True
            QToolTip.hideText()
            return True
        return super().event(event)

    def paintEvent(self, event):
        p = QPainter(self)
        is_light = self.palette().window().color().lightness() > 150
        rail_bg = QColor("#f0f2f5") if is_light else QColor("#12131a")
        rail_border = QColor("#d0d4dc") if is_light else QColor("#202330")
        divider_color = QColor("#d8dce6") if is_light else QColor("#252838")

        p.fillRect(self.rect(), rail_bg)
        p.setPen(rail_border)
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        for i in range(self.count()):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            opt.rect = self.tabRect(i)
            if i == self._hover_index and i != self.currentIndex():
                opt.state |= QStyle.StateFlag.State_MouseOver
            else:
                opt.state &= ~QStyle.StateFlag.State_MouseOver
            self.style().drawControl(QStyle.ControlElement.CE_TabBarTab, opt, p, self)

        # Draw group dividers
        p.setPen(QPen(divider_color, 1))
        for after_idx in (2, 5, 8, 13):
            if after_idx < self.count() - 1:
                r_prev = self.tabRect(after_idx)
                div_y = r_prev.bottom() + 4
                p.drawLine(6, div_y, self.width() - 6, div_y)

        # Divider above Settings if pinned to bottom
        if self.count() > self.SETTINGS_INDEX:
            sr = self.tabRect(self.SETTINGS_INDEX)
            r13 = self.tabRect(13)
            if sr.top() > r13.bottom() + self.DIV_H + 4:
                p.drawLine(6, sr.top() - 4, self.width() - 6, sr.top() - 4)

        p.end()


class MainWindow(QMainWindow):
    """Main application window with tabbed interface."""
    
    def minimumSizeHint(self) -> QSize:
        """Provide a sensible minimum size hint to prevent Windows OS geometry clamping."""
        return QSize(960, 580)
    
    def __init__(self):
        super().__init__()
        self.job_manager = JobManager()
        self.asset_selection = AssetSelection(self)
        self.init_ui()
        self.setup_menu()
        self.setup_status_bar()
        
        # Apply Saved Theme
        saved_theme = getattr(self, 'settings_tab', None)
        theme_name = self.settings_tab.settings.value("theme", "Dark") if hasattr(self, 'settings_tab') else "Dark"
        self.setStyleSheet(get_theme_stylesheet(theme_name))

        # The Performance pane's stored settings are read back here rather than in the pane's
        # own constructor: a pane built by a test, a screenshot run or a second window should
        # not become the thing that changes this process's priority class or pins its cores,
        # while a window the user opened is exactly that. With nothing stored no verb runs,
        # and the pane prints which controls it examined and which it had to apply.
        self.performance_tab.apply_stored_settings()
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("RenderFox")
        self.setMinimumSize(960, 580)
        self.setGeometry(100, 100, 1280, 820)
        
        # Explicitly set window icon to prevent it from reverting
        icon_path = bundled("icon.ico")
        if not os.path.exists(icon_path):
            icon_path = bundled(os.path.join("resources", "icon.ico"))
            
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning("Window icon not found at %s", icon_path)
        
        # Create central widget with tab layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Studio Top Navigation & Telemetry Header
        self.studio_header = StudioHeaderBar(self)
        layout.addWidget(self.studio_header)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("workspaceRail")
        self.tab_widget.setTabBar(WorkspaceRailTabBar(self.tab_widget))
        # Name the actual navigation bar as well as its container.  A stylesheet
        # selector rooted at the container also matched every nested editor tab bar,
        # which compressed labels such as Library > Collections into unreadable pills.
        self.tab_widget.tabBar().setObjectName("workspaceRailBar")
        # A vertical workspace rail keeps all capabilities one click away without
        # reducing the app to fifteen competing document tabs across the title bar.
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.West)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setMovable(False)
        self.tab_widget.setIconSize(QSize(18, 18))
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
        self.performance_tab = PerformanceTab(job_manager=self.job_manager)
        self.diagnostics_tab = DiagnosticsTab()
        self.scripting_tab = ScriptingTab(main_window=self)
        self.pipeline_tab = PipelineEditorTab()
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
        
        # Connect Studio Header signals
        self.asset_selection.changed.connect(self.studio_header.set_active_asset)
        self.tab_widget.currentChanged.connect(self.studio_header.set_active_workspace)
        self.studio_header.open_model_requested.connect(self.load_model_shortcut)
        self.studio_header.theme_toggle_requested.connect(self.toggle_next_theme)
        self.studio_header.handoff_requested.connect(self._handle_header_handoff)
        
        # Icon-only workspace rail: labels are deliberately in the tooltip so the
        # canvas stays clear.  Every former tab remains present and keyboard/menu
        # navigation still targets its widget directly.
        self._add_workspace(self.dashboard_tab, "batch_render", "Batch Render",
                            "Queue and send jobs to your installed DCC renderers.")
        self._add_workspace(self.library_tab, "library", "Library",
                            "Browse, tag, organize, and open your asset collection.")
        self._add_workspace(self.model_tab, "models", "Models",
                            "Inspect, convert, analyze, and prepare mesh assets.")
        self._add_workspace(self.mesh_tools_tab, "mesh_tools", "Mesh Tools",
                            "Repair, optimize, simplify, and edit mesh geometry.")
        self._add_workspace(self.point_clouds_tab, "point_clouds", "Point Clouds",
                            "Import, process, and convert point-cloud data.")
        self._add_workspace(self.preprocessing_tab, "preprocessing", "Pre-Processing",
                            "Prepare geometry and textures before your main operation.")
        self._add_workspace(self.postprocessing_tab, "postprocessing", "Post-Processing",
                            "Polish completed assets and organize deliverables.")
        self._add_workspace(self.rendering_tab, "rendering", "Rendering",
                            "Look-develop models and export viewport preview frames.")
        self._add_workspace(self.animation_tab, "animation", "Animation",
                            "Animate, preview, and export a timeline to H.264 MP4.")
        self._add_workspace(self.automation_tab, "automation", "Automation",
                            "Watch folders, schedule work, and run batch operations.")
        self._add_workspace(self.pipeline_tab, "pipeline", "Pipeline",
                            "Build and run reusable multi-step asset workflows.")
        self._add_workspace(self.scripting_tab, "scripting", "Scripting",
                            "Automate RenderFox through its supported rfx API.")
        self._add_workspace(self.performance_tab, "performance", "Performance",
                            "Tune RenderFox and measure system-aware workload results.")
        self._add_workspace(self.diagnostics_tab, "diagnostics", "Diagnostics",
                            "Review application health, logs, and machine checks.")
        self._add_workspace(self.settings_tab, "settings", "Settings",
                            "Set preferences, paths, themes, and application behavior.")
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
        dashboard_action.triggered.connect(lambda: self.switch_to_widget(self.dashboard_tab))
        view_menu.addAction(dashboard_action)
        
        models_view_action = QAction('Models', self)
        models_view_action.setShortcut('F7')
        models_view_action.triggered.connect(lambda: self.switch_to_widget(self.model_tab))
        view_menu.addAction(models_view_action)
        
        library_view_action = QAction('Library', self)
        library_view_action.setShortcut('F8')
        library_view_action.triggered.connect(lambda: self.switch_to_widget(self.library_tab))
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
        
        feedback_action = QAction('Send Feedback', self)
        feedback_action.triggered.connect(self.open_feedback)
        help_menu.addAction(feedback_action)
        
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

    def _add_workspace(self, widget, icon_name, title, description):
        """Add an icon-only workspace and expose its name and purpose on hover."""
        index = self.tab_widget.addTab(widget, get_tab_icon(icon_name), "")
        self.tab_widget.setTabToolTip(index, f"{title}\n{description}")
        self.tab_widget.setTabWhatsThis(index, f"{title}: {description}")

    def switch_to_widget(self, widget):
        """Select a workspace by identity, so navigation survives reordering."""
        self.tab_widget.setCurrentWidget(widget)
    
    def open_user_guide(self):
        """Open user guide."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
        dialog = QDialog(self)
        dialog.setWindowTitle("RenderFox User Guide")
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        
        guide_path = bundled("USER_GUIDE.md")
        if os.path.exists(guide_path):
            with open(guide_path, "r", encoding="utf-8") as f:
                content = f.read()
            browser.setMarkdown(content)
        else:
            browser.setPlainText(f"RenderFox User Guide file (USER_GUIDE.md) not found "
                                 f"at {guide_path}.")
            
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

        # A worker that is still running when the window goes posts its result into widgets
        # Qt has already destroyed, and Qt answers that with a heap fault rather than a
        # traceback. Every holder of a run is asked to stop it first, so a close in the
        # middle of a measure leaves nothing to deliver. The walk covers the whole tree
        # rather than the fifteen tabs, because the runs are not only in the tabs: the
        # Quality pane lives inside Models, the Open3D preview inside Mesh Tools and Point
        # Clouds, the tagger inside Library, and a dismissed dialog outlives its own
        # `exec()` as a child of the pane that opened it. Asking each object whether it
        # answers is the one list of holders that cannot forget a pane.
        for holder in [self] + self.findChildren(QWidget):
            if hasattr(holder, 'shutdown_runs'):
                holder.shutdown_runs()

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
        self.asset_selection.select(file_path)
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
        self.asset_selection.select(file_path)
        self.tab_widget.setCurrentWidget(self.point_clouds_tab)
        
        # Load the point cloud
        if hasattr(self.point_clouds_tab, 'load_point_cloud_file'):
            self.point_clouds_tab.load_point_cloud_file(file_path)
        elif hasattr(self.point_clouds_tab, 'load_model'):
            self.point_clouds_tab.load_model(file_path)

    def load_model_globally(self, file_path):
        """Load a model into all applicable tabs."""
        self.asset_selection.select(file_path)
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
        self.library_tab.model_selected.connect(self.asset_selection.select)

        # Direct loads in a workspace are just as meaningful as Library hand-offs.
        # Each pane emits only after it accepted the file; AssetSelection suppresses
        # duplicates, so an inter-workspace hand-off cannot create a feedback loop.
        for pane in (self.model_tab, self.point_clouds_tab, self.mesh_tools_tab,
                     self.preprocessing_tab, self.postprocessing_tab,
                     self.animation_tab, self.rendering_tab):
            pane.asset_loaded.connect(self.asset_selection.select)

        # Point Clouds Tab connections
        self.point_clouds_tab.mesh_generated.connect(self.open_in_mesh_tools)
        self.point_clouds_tab.add_to_library_requested.connect(self.library_tab.add_model_to_library)

        # Mesh Tools Tab connections
        self.mesh_tools_tab.add_to_library_requested.connect(self.library_tab.add_model_to_library)

    
    def open_in_animation(self, file_path):
        """Open a model file in the Animation tab."""
        self.asset_selection.select(file_path)
        self.tab_widget.setCurrentWidget(self.animation_tab)
        if hasattr(self.animation_tab, 'load_model_from_path'):
            self.animation_tab.load_model_from_path(file_path)

    def open_in_rendering(self, file_path):
        """Open a model file in the Rendering tab."""
        self.asset_selection.select(file_path)
        self.tab_widget.setCurrentWidget(self.rendering_tab)
        if hasattr(self.rendering_tab, 'set_model'):
            self.rendering_tab.set_model(file_path)

    def open_in_mesh_tools(self, file_path):
        """Open a model file in the Mesh Tools tab."""
        self.asset_selection.select(file_path)
        self.tab_widget.setCurrentWidget(self.mesh_tools_tab)
        if hasattr(self.mesh_tools_tab, 'load_mesh_file'):
            self.mesh_tools_tab.load_mesh_file(file_path)

    def open_in_preprocessing(self, file_path):
        """Open a model file in the Pre-processing tab."""
        self.asset_selection.select(file_path)
        self.tab_widget.setCurrentWidget(self.preprocessing_tab)
        if hasattr(self.preprocessing_tab, 'load_model'):
            self.preprocessing_tab.load_model(file_path)

    def open_in_postprocessing(self, file_path):
        """Open a file in the Post-processing tab."""
        self.asset_selection.select(file_path)
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

    def toggle_next_theme(self):
        """Cycle through available modern themes: Dark -> Midnight -> Light -> Dark."""
        current = self.settings_tab.settings.value("theme", "Dark") if hasattr(self, 'settings_tab') else "Dark"
        themes = ["Dark", "Midnight", "Light"]
        next_idx = (themes.index(current) + 1) % len(themes) if current in themes else 0
        next_theme = themes[next_idx]
        if hasattr(self, 'settings_tab'):
            self.settings_tab.settings.setValue("theme", next_theme)
        self.setStyleSheet(get_theme_stylesheet(next_theme))
        self.statusBar().showMessage(f"Theme switched to {next_theme}", 2000)

    def _handle_header_handoff(self, target: str, file_path: str):
        """Route active asset handoff to destination workspace."""
        if target == "models":
            self.open_in_model_viewer(file_path)
        elif target == "mesh_tools":
            self.open_in_mesh_tools(file_path)
        elif target == "preprocessing":
            self.open_in_preprocessing(file_path)
        elif target == "rendering":
            self.open_in_rendering(file_path)
        elif target == "animation":
            self.open_in_animation(file_path)
        elif target == "postprocessing":
            self.open_in_postprocessing(file_path)
