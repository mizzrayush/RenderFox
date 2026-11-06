"""
Quality Analyzer UI - Professional Quality Scoring & Analysis Interface

This UI provides a comprehensive interface for analyzing 3D model quality,
showing production-ready scores, detailed issues, and one-click fixes.
"""

import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QComboBox, QGroupBox,
                             QProgressBar, QListWidget, QListWidgetItem,
                             QSplitter, QFrame, QScrollArea, QGridLayout, QDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from src.core.worker_base import SafeWorker
from PyQt6.QtGui import QFont, QColor, QPalette
import logging
from pathlib import Path
from typing import Optional, Dict

from ..features.quality_analyzer import QualityAnalyzer
from .unified_viewer import UnifiedOpen3DViewer
from ..processing.mesh_processor import MeshProcessor, MeshUV
from ..utils.worker import Worker
from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)

# Every fix name the analyzer promises as one-click, and the verb on the app's one
# operation router that carries it out. Keyed by QualityAnalyzer.ONE_CLICK_FIXES, which
# test_quality_analyzer_contract checks name-for-name, so a promise cannot outlive a verb.
FIX_VERBS = {
    'repair_mesh': ('repair', {'operation': 'auto'}),
    'merge_vertices': ('repair', {'operation': 'remove_duplicates'}),
    'remove_degenerate_faces': ('repair', {'operation': 'remove_degenerate'}),
    'fix_normals': ('repair', {'operation': 'fix_normals'}),
    'remesh': ('remesh', {'method': 'uniform'}),
    'generate_uvs': ('uv', {'method': 'trivial', 'layout': 'Basic'}),
    'pack_uvs': ('uv', {'method': 'trivial', 'layout': 'Space-optimizing'}),
}


def fix_output_path(model_path: str, fix_action: str) -> str:
    """The file this fix writes: beside the model, named for the fix, extension kept."""
    root, ext = os.path.splitext(model_path)
    return f"{root}_{fix_action}{ext}"


# auto_repair (mesh_processor.py:811) runs seven pymeshlab filters; this sentence names
# every one of them, and the contract suite reads the engine's source to keep it true.
FIX_ALL_ASK = ("This runs the app's full auto-repair: weld duplicate vertices, drop null, "
               "folded and duplicate faces, re-orient faces coherently, close holes and "
               "drop unreferenced vertices. The result is written to a new file beside "
               "this one; the original is not touched. Continue?")


def apply_fix_action(processor: MeshProcessor, model_path: str, fix_action: str,
                     output_path: Optional[str] = None) -> Dict:
    """Run one analyzer fix name on the backend that actually does it.

    Returns the engine's own dict. A name with no verb here, or one another pane owns,
    comes back as a refusal that says so - never as a success the run did not earn.
    """
    if fix_action in QualityAnalyzer.OWNED_ELSEWHERE:
        return {'success': False, 'error': QualityAnalyzer.OWNED_ELSEWHERE[fix_action]}

    verb = FIX_VERBS.get(fix_action)
    if not verb:
        return {'success': False,
                'error': f"no backend is registered for fix '{fix_action}'"}

    method, kwargs = verb
    target = output_path or fix_output_path(model_path, fix_action)
    if method == 'uv':
        return MeshUV.parametrize(model_path, target, **kwargs)
    return getattr(processor, method)(model_path, target, **kwargs)


class QualityAnalysisWorker(SafeWorker):
    """Background worker for quality analysis.

    `analysis_done` rather than `finished`: SafeWorker is a QThread, and a subclass
    signal named `finished` shadows the one Qt itself emits. The failure channel is
    SafeWorker's own `error_occurred`, which `run()` emits when `safe_run` raises -
    a second `error` signal here would be a channel nothing emits.
    """
    analysis_done = pyqtSignal(dict)

    def __init__(self, model_path: str, target_platform: str):
        super().__init__()
        self.model_path = model_path
        self.target_platform = target_platform
        self.analyzer = QualityAnalyzer()
    
    def safe_run(self):
        result = self.analyzer.analyze_quality(self.model_path, self.target_platform)
        self.analysis_done.emit(result)


class ComparisonDialog(QDialog):
    """Dialog for comparing original and optimized models."""
    def __init__(self, original_path, current_path, analyzer, parent=None):
        super().__init__(parent)
        self.original_path = original_path
        self.current_path = current_path
        self.analyzer = analyzer
        self.setWindowTitle("Model Comparison")
        self.resize(1000, 600)
        
        self.init_ui()
        self.load_data()
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        
        # Left: Original
        left_group = QGroupBox("Original Model")
        left_layout = QVBoxLayout()
        self.original_viewer = UnifiedOpen3DViewer()
        left_layout.addWidget(self.original_viewer, 1)
        self.original_info = QLabel("Loading metrics...")
        left_layout.addWidget(self.original_info)
        left_group.setLayout(left_layout)
        
        # Right: Current
        right_group = QGroupBox("Current Model")
        right_layout = QVBoxLayout()
        self.current_viewer = UnifiedOpen3DViewer()
        right_layout.addWidget(self.current_viewer, 1)
        self.current_info = QLabel("Loading metrics...")
        right_layout.addWidget(self.current_info)
        right_group.setLayout(right_layout)
        
        layout.addWidget(left_group)
        layout.addWidget(right_group)
        
    def load_data(self):
        # Load Viewers
        if self.original_path and os.path.exists(self.original_path):
            self.original_viewer.load_from_file(self.original_path)
            # Analyze metrics
            self.update_info(self.original_info,
                             self.analyzer.analyze_quality(self.original_path))
            
        if self.current_path and os.path.exists(self.current_path):
            self.current_viewer.load_from_file(self.current_path)
            self.update_info(self.current_info,
                             self.analyzer.analyze_quality(self.current_path))
            
    def update_info(self, label, analysis):
        """Paint what the analyzer measured, or the reason it measured nothing."""
        if analysis.get('error'):
            label.setText(f"Could not be analyzed: {analysis['error']}")
            return

        metrics = analysis.get('metrics', {})
        text = (f"<b>Polygons:</b> {metrics.get('polygon_count', 0):,}<br>"
                f"<b>Vertices:</b> {metrics.get('vertex_count', 0):,}<br>"
                f"<b>Watertight:</b> {'Yes' if metrics.get('is_watertight') else 'No'}<br>"
                f"<b>Volume:</b> {metrics.get('volume', 0):.4f}")
        label.setText(text)

class QualityAnalyzerUI(QWidget):
    """
    Quality Analyzer UI Component.
    
    Features:
    - Overall quality score with letter grade
    - Detailed issue breakdown
    - Standards compliance checker
    - One-click fix suggestions
    - Before/after comparison
    - Export quality report
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.analyzer = QualityAnalyzer()
        self.processor = MeshProcessor()
        self.threadpool = QThreadPool()
        self.current_model_path = None
        self.original_model_path = None
        self.analysis_result = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Analysis controls and score
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Issues and suggestions
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
    

    
    def _create_left_panel(self) -> QWidget:
        """Create left panel with controls and score display."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Analysis Controls
        controls_group = QGroupBox("Analysis Settings")
        controls_layout = QVBoxLayout()
        
        # Target platform selector
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("Target Platform:"))
        
        self.platform_combo = QComboBox()
        self.platform_combo.addItems([
            "Mobile Game",
            "PC Game", 
            "VR",
            "Film/VFX",
            "Architectural Viz"
        ])
        self.platform_combo.setCurrentText("PC Game")
        platform_layout.addWidget(self.platform_combo)
        controls_layout.addLayout(platform_layout)
        
        # Analyze button
        from .icon_provider import get_icon
        self.analyze_btn = QPushButton("Analyze Model")
        self.analyze_btn.setIcon(get_icon("diagnostics"))
        self.analyze_btn.setProperty("primary", "true")
        self.analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 10px;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        self.analyze_btn.clicked.connect(self.analyze_current_model)
        self.analyze_btn.setEnabled(False)
        controls_layout.addWidget(self.analyze_btn)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        controls_layout.addWidget(self.progress_bar)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Score Display
        self.score_group = QGroupBox("Quality Score")
        self.score_layout = QVBoxLayout()
        
        # Large score display
        self.score_label = QLabel("--")
        self.score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_label.setFont(QFont("Arial", 72, QFont.Weight.Bold))
        self.score_label.setStyleSheet("color: #95a5a6;")
        self.score_layout.addWidget(self.score_label)
        
        # Grade display
        self.grade_label = QLabel("Grade: -")
        self.grade_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grade_label.setFont(QFont("Arial", 24))
        self.grade_label.setStyleSheet("color: #7f8c8d;")
        self.score_layout.addWidget(self.grade_label)
        
        # Score breakdown
        self.breakdown_widget = QWidget()
        self.breakdown_layout = QGridLayout(self.breakdown_widget)
        self.breakdown_widget.setVisible(False)
        self.score_layout.addWidget(self.breakdown_widget)
        
        self.score_group.setLayout(self.score_layout)
        layout.addWidget(self.score_group)
        
        # Standards Compliance
        self.compliance_group = QGroupBox("Standards Compliance")
        self.compliance_layout = QVBoxLayout()
        self.compliance_text = QTextEdit()
        self.compliance_text.setReadOnly(True)
        self.compliance_text.setMaximumHeight(150)
        self.compliance_layout.addWidget(self.compliance_text)
        self.compliance_group.setLayout(self.compliance_layout)
        self.compliance_group.setVisible(False)
        from .icon_provider import get_icon
        layout.addWidget(self.compliance_group)
        
        layout.addStretch()
        
        # Export report button
        self.export_btn = QPushButton("Export Quality Report")
        self.export_btn.setIcon(get_icon("export"))
        self.export_btn.clicked.connect(self.export_report)
        self.export_btn.setEnabled(False)
        layout.addWidget(self.export_btn)
        
        scroll_area.setWidget(panel)
        return scroll_area
    
    def _create_right_panel(self) -> QWidget:
        """Create right panel with issues and suggestions."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        from .icon_provider import get_icon
        # Issues List
        issues_group = QGroupBox("Detected Issues")
        issues_layout = QVBoxLayout()
        
        self.issues_list = QListWidget()
        issues_layout.addWidget(self.issues_list)
        
        issues_group.setLayout(issues_layout)
        layout.addWidget(issues_group)
        
        # Suggestions List
        suggestions_group = QGroupBox("Fix Suggestions")
        suggestions_layout = QVBoxLayout()
        
        self.suggestions_list = QListWidget()
        self.suggestions_list.itemDoubleClicked.connect(self.apply_fix)
        suggestions_layout.addWidget(self.suggestions_list)
        
        hint_label = QLabel("Tip: Double-click a suggestion to apply the fix")
        hint_label.setStyleSheet("color: #8c93a8; font-style: italic; padding: 5px;")
        suggestions_layout.addWidget(hint_label)
        
        suggestions_group.setLayout(suggestions_layout)
        layout.addWidget(suggestions_group)
        
        # Quick Actions
        actions_layout = QHBoxLayout()
        
        self.fix_all_btn = QPushButton("Fix All Issues")
        self.fix_all_btn.setIcon(get_icon("mesh_tools"))
        self.fix_all_btn.setProperty("primary", "true")
        self.fix_all_btn.clicked.connect(self.fix_all_issues)
        self.fix_all_btn.setEnabled(False)
        actions_layout.addWidget(self.fix_all_btn)
        
        self.compare_btn = QPushButton("Compare Before/After")
        self.compare_btn.setIcon(get_icon("overlays"))
        self.compare_btn.clicked.connect(self.show_comparison)
        self.compare_btn.setEnabled(False)
        actions_layout.addWidget(self.compare_btn)
        
        layout.addLayout(actions_layout)
        
        return panel
    
    def set_model(self, model_path: str):
        """
        Set the current model to analyze.
        
        Args:
            model_path: Path to the 3D model file
        """
        if self.original_model_path is None:
            self.original_model_path = model_path
        self.current_model_path = model_path
        self.analyze_btn.setEnabled(True)
        self.analysis_result = None
        
        # Reset UI
        self.score_label.setText("--")
        self.score_label.setStyleSheet("color: #95a5a6;")
        self.grade_label.setText("Grade: -")
        self.issues_list.clear()
        self.suggestions_list.clear()
        self.compliance_group.setVisible(False)
        self.export_btn.setEnabled(False)
        self.fix_all_btn.setEnabled(False)
        
        logger.info(f"Model set for analysis: {Path(model_path).name}")
    
    def analyze_current_model(self):
        """Analyze the current model."""
        if not self.current_model_path:
            logger.warning("No model selected for analysis")
            return
        
        # Get platform mapping
        platform_map = {
            "Mobile Game": "mobile_game",
            "PC Game": "pc_game",
            "VR": "vr",
            "Film/VFX": "film_vfx",
            "Architectural Viz": "architectural_viz"
        }
        
        target_platform = platform_map.get(
            self.platform_combo.currentText(), 
            "pc_game"
        )
        
        # Disable controls
        self.analyze_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        
        # Start analysis in background
        self.worker = QualityAnalysisWorker(self.current_model_path, target_platform)
        self.worker.analysis_done.connect(self.on_analysis_complete)
        self.worker.error_occurred.connect(self.on_analysis_error)
        self.worker.start()
        
        logger.info(f"Starting quality analysis for {Path(self.current_model_path).name}")
    
    def on_analysis_complete(self, result: Dict):
        """Handle analysis completion."""
        # analyze_quality catches its own failures and returns {'error': ...} with a
        # score of 0. That is not a model that scored badly, it is a model the app never
        # read, so it goes to the failure handler instead of being painted as a verdict.
        if result.get('error'):
            self.on_analysis_error(result['error'])
            return

        self.analysis_result = result
        
        # Re-enable controls
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Update score display
        score = result.get('score', 0)
        grade = result.get('grade', 'F')
        
        self.score_label.setText(f"{score:.0f}")
        self.grade_label.setText(f"Grade: {grade}")
        
        # Color code the score
        if score >= 90:
            color = "#27ae60"  # Green
        elif score >= 75:
            color = "#f39c12"  # Orange
        elif score >= 60:
            color = "#e67e22"  # Dark orange
        else:
            color = "#e74c3c"  # Red
        
        self.score_label.setStyleSheet(f"color: {color};")
        self.grade_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        
        # Show score breakdown
        self._update_score_breakdown(result)
        
        # Update issues list
        self.issues_list.clear()
        issues = result.get('issues', [])
        for issue in issues:
            # An issue that is a bare sentence is a bug in whoever produced it, but this
            # loop is a Qt slot: raising here loses the rest of the list silently.
            fields = issue if hasattr(issue, 'get') else {'type': 'issue', 'message': str(issue)}
            title = fields.get('type', 'Issue').replace('_', ' ').title()
            description = fields.get('message', '')
            item = QListWidgetItem(f"• {title}: {description}")
            item.setData(Qt.ItemDataRole.UserRole, issue)

            # Color code by severity
            if fields.get('severity') == 'critical':
                item.setForeground(QColor("#ff4757"))
            elif fields.get('severity') == 'high':  # Changed from warning to match analyzer
                item.setForeground(QColor("#ffa502"))
            elif fields.get('severity') == 'medium':
                item.setForeground(QColor("#ffa502"))
            else:
                item.setForeground(QColor("#747d8c"))

            self.issues_list.addItem(item)
        
        # Update suggestions list
        self.suggestions_list.clear()
        suggestions = result.get('suggestions', [])
        for suggestion in suggestions:
            title = (suggestion.get('fix_action') or 'Manual check').replace('_', ' ').title()
            description = suggestion.get('description', '')
            # Add title to suggestion dict for apply_fix usage
            suggestion['title'] = title
            
            item = QListWidgetItem(f"• {title}\n   → {description}")
            item.setData(Qt.ItemDataRole.UserRole, suggestion)
            self.suggestions_list.addItem(item)
        
        # Update standards compliance
        self._update_standards_compliance(result)
        
        # Enable export and fix buttons
        self.export_btn.setEnabled(True)
        if suggestions:
            self.fix_all_btn.setEnabled(True)
        
        logger.info(f"Analysis complete: Score={score:.0f}, Grade={grade}, Issues={len(issues)}")
    
    def on_analysis_error(self, error_msg: str):
        """Handle analysis error."""
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        self.score_label.setText("Error")
        self.score_label.setStyleSheet("color: #e74c3c;")
        self.grade_label.setText(f"Analysis failed: {error_msg}")
        
        logger.error(f"Analysis error: {error_msg}")
    
    def _update_score_breakdown(self, result: Dict):
        """Update the score breakdown display."""
        # Clear existing breakdown
        for i in reversed(range(self.breakdown_layout.count())): 
            self.breakdown_layout.itemAt(i).widget().setParent(None)
        
        # Add category scores
        categories = [
            ("Polygon Count", "polygon_score", 20),
            ("Geometry", "geometry_score", 30),
            ("UV Mapping", "uv_score", 15),
            ("Topology", "topology_score", 15),
            ("Textures", "texture_score", 10),
            ("Performance", "performance_score", 10)
        ]
        
        for i, (name, key, max_score) in enumerate(categories):
            label = QLabel(f"{name}:")
            self.breakdown_layout.addWidget(label, i, 0)
            
            score = result.get(key, 0)
            score_label = QLabel(f"{score:.0f}/{max_score}")
            
            # Color code
            percent = (score / max_score * 100) if max_score > 0 else 0
            if percent >= 90:
                score_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            elif percent >= 70:
                score_label.setStyleSheet("color: #f39c12; font-weight: bold;")
            else:
                score_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            
            self.breakdown_layout.addWidget(score_label, i, 1)
        
        self.breakdown_widget.setVisible(True)
    
    def _update_standards_compliance(self, result: Dict):
        """Update standards compliance display."""
        compliance = result.get('standards_compliance', {})
        
        if not compliance:
            return
        
        text = "<h3>Standards Compliance Check:</h3><ul>"
        
        for standard, meets in compliance.items():
            status_txt = "PASS" if meets else "FAIL"
            color = "#2ed573" if meets else "#ff4757"
            text += f"<li><b style='color: {color};'>[{status_txt}]</b> {standard.replace('_', ' ').title()}</li>"
        
        text += "</ul>"
        
        self.compliance_text.setHtml(text)
        self.compliance_group.setVisible(True)
    
    def apply_fix(self, item: QListWidgetItem):
        """Apply a single fix suggestion."""
        suggestion = item.data(Qt.ItemDataRole.UserRole)
        
        if not suggestion:
            return

        fix_action = suggestion.get('fix_action')
        title = suggestion.get('title')

        logger.info(f"Applying fix: {title} ({fix_action})")

        if not fix_action:
            # A row the analyzer wrote as advice, not as something a verb can do.
            QMessageBox.warning(self, "No One-Click Fix",
                                suggestion.get('description', 'Manual fix required'))
            return

        if not self.current_model_path:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        def worker_func(processor, path, action, progress_callback=None):
            return apply_fix_action(processor, path, action)

        worker = Worker(worker_func, self.processor, self.current_model_path, fix_action)
        
        def on_result(result):
            self.progress_bar.setVisible(False)
            if result['success']:
                output_path = result['output_path']
                QMessageBox.information(self, "Fix Applied", f"Fix applied successfully!\nSaved to: {output_path}")
                item.setText(f"{title} (Applied)")
                item.setForeground(QColor("#2ed573"))
                
                # Ask to reload
                reply = QMessageBox.question(self, "Reload Model", "Load the fixed model?", 
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.set_model(output_path)
                    self.analyze_current_model()
            else:
                QMessageBox.warning(self, "Fix Failed", result.get('error', 'Unknown error'))
                
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self.on_fix_failed)
        self.threadpool.start(worker)

    def on_fix_failed(self, error):
        """Report what the fix thread died with, and stop the bar that was spinning."""
        kind, value, _traceback = error
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "Fix Failed",
                            f"The fix stopped before it wrote anything: "
                            f"{kind.__name__}: {value}")

    def fix_all_issues(self):
        """Apply the auto-repair every suggestion here leans on."""
        logger.info("Applying all fixes...")

        if not self.current_model_path:
            return

        reply = QMessageBox.question(self, "Fix All",
                                   FIX_ALL_ASK,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                                   
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        def worker_func(processor, path, progress_callback=None):
            return apply_fix_action(processor, path, 'repair_mesh',
                                    fix_output_path(path, 'fixed_all'))
            
        worker = Worker(worker_func, self.processor, self.current_model_path)
        
        def on_result(result):
            self.progress_bar.setVisible(False)
            if result['success']:
                output_path = result['output_path']
                # The engine's own sentences: what it removed, not what it was asked to.
                steps = '\n'.join(result.get('operations') or [])
                QMessageBox.information(self, "Success",
                                        f"Auto-repair complete!\nSaved to: {output_path}"
                                        + (f"\n\n{steps}" if steps else ""))
                
                # Mark only the rows auto_repair carried out; a UV or remesh suggestion
                # is not done because a hole got closed, and stays in the list unmarked.
                for i in range(self.suggestions_list.count()):
                    item = self.suggestions_list.item(i)
                    suggestion = item.data(Qt.ItemDataRole.UserRole)
                    if not suggestion:
                        continue
                    if suggestion.get('fix_action') not in QualityAnalyzer.FIX_ALL_COVERS:
                        continue
                    item.setText(f"{suggestion.get('title', 'Fix')} (Applied)")
                    item.setForeground(QColor("#2ed573"))
                
                self.fix_all_btn.setEnabled(False)
                
                # Ask to reload
                reply = QMessageBox.question(self, "Reload Model", "Load the fixed model?", 
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.set_model(output_path)
                    self.analyze_current_model()
            else:
                QMessageBox.warning(self, "Error", result.get('error', 'Unknown error'))
                
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self.on_fix_failed)
        self.threadpool.start(worker)

    def show_comparison(self):
        """Show before/after comparison."""
        if not self.current_model_path:
            return
            
        original = self.original_model_path if self.original_model_path else self.current_model_path
        
        dialog = ComparisonDialog(original, self.current_model_path, self.analyzer, self)
        dialog.exec()
    def export_report(self):
        """Export the analysis on screen as an HTML report."""
        if not self.analysis_result or not self.current_model_path:
            return

        output_path = Path(self.current_model_path).with_suffix('.quality_report.html')

        try:
            # batch shape: the report reads {model path: analysis}, not one analysis.
            self.analyzer.export_quality_report(
                {self.current_model_path: self.analysis_result}, str(output_path))
        except Exception as e:
            QMessageBox.warning(self, "Export Failed",
                                f"No report was written to {output_path}: "
                                f"{type(e).__name__}: {e}")
            logger.error(f"Failed to export report: {e}")
            return

        QMessageBox.information(self, "Report Exported",
                                f"Quality report written to: {output_path}")
        logger.info(f"Quality report exported to: {output_path}")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    window = QualityAnalyzerUI()
    window.setWindowTitle("Quality Analyzer")
    window.resize(1200, 800)
    window.show()
    
    # Set a test model
    # window.set_model("path/to/model.obj")
    
    sys.exit(app.exec())
