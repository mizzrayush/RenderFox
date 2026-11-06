"""
Version Control UI - Git-like Version Control for 3D Assets

This UI provides a comprehensive version control interface for 3D models with
visual timeline, comparison tools, and rollback capabilities.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                             QGroupBox, QComboBox, QCheckBox, QProgressBar,
                             QSplitter, QFrame, QTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSpinBox, QDoubleSpinBox,
                             QFileDialog, QMessageBox, QScrollArea, QDialog,
                             QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
                             QInputDialog, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QAction
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from .unified_viewer import UnifiedOpen3DViewer
from ..features.version_control import (AssetVersionControl, NOT_COMPARABLE, describe_metrics,
                                        describe_polygon_count, describe_volume,
                                        describe_watertight)
from .icon_provider import get_icon

logger = logging.getLogger(__name__)


class VersionComparisonDialog(QDialog):
    """Dialog for comparing two versions with visual diff."""
    
    def __init__(self, comparison_data: Dict, path1: str = None, path2: str = None, parent=None):
        super().__init__(parent)
        self.path1 = path1
        self.path2 = path2
        self.comparison_data = comparison_data
        self.setWindowTitle("Version Comparison")
        self.setMinimumSize(800, 600)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the comparison dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("Version Comparison")
        header.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header.setStyleSheet("color: #e8ebf5; padding: 10px;")
        layout.addWidget(header)
        
        if 'error' in self.comparison_data:
            error_label = QLabel(f"Error: {self.comparison_data['error']}")
            error_label.setStyleSheet("color: #ff4757; padding: 20px;")
            layout.addWidget(error_label)
            return
            
        # Visual Comparison (New)
        if self.path1 and self.path2:
            visual_group = QGroupBox("Visual Comparison")
            visual_layout = QHBoxLayout()
            
            # Left: Version 1
            v1_layout = QVBoxLayout()
            v1_label = QLabel(f"Version {self.comparison_data['version1']['version_number']}")
            v1_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v1_label.setStyleSheet("font-weight: bold;")
            self.viewer1 = UnifiedOpen3DViewer()
            self.viewer1.load_from_file(self.path1)
            v1_layout.addWidget(v1_label)
            v1_layout.addWidget(self.viewer1)
            
            # Right: Version 2
            v2_layout = QVBoxLayout()
            v2_label = QLabel(f"Version {self.comparison_data['version2']['version_number']}")
            v2_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v2_label.setStyleSheet("font-weight: bold;")
            self.viewer2 = UnifiedOpen3DViewer()
            self.viewer2.load_from_file(self.path2)
            v2_layout.addWidget(v2_label)
            v2_layout.addWidget(self.viewer2)
            
            visual_layout.addLayout(v1_layout)
            visual_layout.addLayout(v2_layout)
            visual_group.setLayout(visual_layout)
            layout.addWidget(visual_group, 1) # Give it stretch
        
        # Version info
        info_layout = QHBoxLayout()
        
        v1 = self.comparison_data['version1']
        v2 = self.comparison_data['version2']
        
        v1_group = QGroupBox(f"Version {v1['version_number']}")
        v1_layout = QVBoxLayout()
        v1_layout.addWidget(QLabel(f"<b>Timestamp:</b> {v1['timestamp'][:19]}"))
        v1_layout.addWidget(QLabel(f"<b>Message:</b> {v1['commit_message']}"))
        v1_group.setLayout(v1_layout)
        info_layout.addWidget(v1_group)
        
        arrow_label = QLabel("→")
        arrow_label.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        arrow_label.setStyleSheet("color: #4b7bec;")
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(arrow_label)
        
        v2_group = QGroupBox(f"Version {v2['version_number']}")
        v2_layout = QVBoxLayout()
        v2_layout.addWidget(QLabel(f"<b>Timestamp:</b> {v2['timestamp'][:19]}"))
        v2_layout.addWidget(QLabel(f"<b>Message:</b> {v2['commit_message']}"))
        v2_group.setLayout(v2_layout)
        info_layout.addWidget(v2_group)
        
        layout.addLayout(info_layout)
        
        # Changes table
        changes_group = QGroupBox("Geometry Changes")
        changes_layout = QVBoxLayout()
        
        changes_table = QTableWidget()
        changes_table.setColumnCount(5)
        changes_table.setHorizontalHeaderLabels(["Metric", "Version 1", "Version 2", "Delta", "Change %"])
        changes_table.horizontalHeader().setStretchLastSection(True)
        changes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        changes = self.comparison_data['changes']
        
        # Polygons
        changes_table.insertRow(0)
        poly_delta = changes['polygons']['delta']
        poly_percent = changes['polygons']['percent']
        changes_table.setItem(0, 0, QTableWidgetItem("Polygons"))
        changes_table.setItem(0, 1, QTableWidgetItem(f"{changes['polygons']['v1']:,}"))
        changes_table.setItem(0, 2, QTableWidgetItem(f"{changes['polygons']['v2']:,}"))
        delta_item = QTableWidgetItem(f"{poly_delta:+,}")
        delta_item.setForeground(QColor('red' if poly_delta > 0 else 'green' if poly_delta < 0 else 'gray'))
        changes_table.setItem(0, 3, delta_item)
        percent_item = QTableWidgetItem(f"{poly_percent:+.1f}%")
        percent_item.setForeground(QColor('red' if poly_delta > 0 else 'green' if poly_delta < 0 else 'gray'))
        changes_table.setItem(0, 4, percent_item)
        
        # Vertices
        changes_table.insertRow(1)
        vert_delta = changes['vertices']['delta']
        vert_percent = changes['vertices']['percent']
        changes_table.setItem(1, 0, QTableWidgetItem("Vertices"))
        changes_table.setItem(1, 1, QTableWidgetItem(f"{changes['vertices']['v1']:,}"))
        changes_table.setItem(1, 2, QTableWidgetItem(f"{changes['vertices']['v2']:,}"))
        delta_item = QTableWidgetItem(f"{vert_delta:+,}")
        delta_item.setForeground(QColor('red' if vert_delta > 0 else 'green' if vert_delta < 0 else 'gray'))
        changes_table.setItem(1, 3, delta_item)
        percent_item = QTableWidgetItem(f"{vert_percent:+.1f}%")
        percent_item.setForeground(QColor('red' if vert_delta > 0 else 'green' if vert_delta < 0 else 'gray'))
        changes_table.setItem(1, 4, percent_item)
        
        # Volume
        changes_table.insertRow(2)
        vol_delta = changes['volume']['delta']
        changes_table.setItem(2, 0, QTableWidgetItem("Volume"))
        changes_table.setItem(2, 1, QTableWidgetItem(describe_volume(changes['volume']['v1'])))
        changes_table.setItem(2, 2, QTableWidgetItem(describe_volume(changes['volume']['v2'])))
        delta_item = QTableWidgetItem(describe_volume(vol_delta, signed=True))
        delta_item.setForeground(QColor('blue'))
        changes_table.setItem(2, 3, delta_item)
        changes_table.setItem(2, 4, QTableWidgetItem("-"))
        
        changes_table.resizeColumnsToContents()
        changes_layout.addWidget(changes_table)
        
        changes_group.setLayout(changes_layout)
        layout.addWidget(changes_group)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

class CommitDialog(QDialog):
    """Dialog for committing a new version."""
    
    def __init__(self, model_name: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.setWindowTitle("Commit Version")
        self.setMinimumSize(500, 300)
        self.init_ui()
    
    def init_ui(self):
        """Initialize commit dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel(f"Commit New Version: {self.model_name}")
        header.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        header.setStyleSheet("color: #e8ebf5; padding: 10px;")
        layout.addWidget(header)
        
        # Commit message
        msg_label = QLabel("Commit Message:")
        msg_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(msg_label)
        
        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText("Describe the changes made to this model...\n\nExample: Optimized mesh, reduced polygon count by 30%")
        self.message_edit.setMaximumHeight(150)
        layout.addWidget(self.message_edit)
        
        # Author
        author_layout = QHBoxLayout()
        author_label = QLabel("Author:")
        author_label.setStyleSheet("font-weight: bold;")
        author_layout.addWidget(author_label)
        
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("Your name")
        self.author_edit.setText("User")
        author_layout.addWidget(self.author_edit)
        
        layout.addLayout(author_layout)
        
        # Info
        info_label = QLabel("Tip: Write clear commit messages to track changes over time")
        info_label.setStyleSheet("color: #8c93a8; font-style: italic; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_commit_data(self) -> Dict:
        """Get commit data."""
        return {
            'message': self.message_edit.toPlainText(),
            'author': self.author_edit.text()
        }


class VersionControlUI(QWidget):
    """
    Version Control UI Component.
    
    Features:
    - Timeline view of all versions
    - Commit new versions with messages
    - Compare any two versions
    - Restore previous versions
    - Tag important versions
    - Export version history
    - Visual diff viewer
    """
    
    version_restored = pyqtSignal(str)  # Emitted when version is restored
    
    def __init__(self, library_path: str, parent=None):
        super().__init__(parent)
        self.version_control = AssetVersionControl(library_path)
        self.current_model = None
        self.version_history = []
        self.selected_versions = []  # For comparison
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Model selection and actions
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Version timeline and details
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
    

    
    def _create_left_panel(self) -> QWidget:
        """Create left panel with model selection and actions."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        from .icon_provider import get_icon
        # Model Selection
        model_group = QGroupBox("Current Model")
        model_layout = QVBoxLayout()
        
        # Select model button
        select_btn = QPushButton("Select Model")
        select_btn.setIcon(get_icon("folder"))
        select_btn.clicked.connect(self.select_model)
        model_layout.addWidget(select_btn)
        
        # Current model display
        self.model_label = QLabel("No model selected")
        self.model_label.setStyleSheet("""
            background-color: #1e202a;
            color: #dcdfe8;
            padding: 12px;
            border-radius: 4px;
            font-weight: 500;
        """)
        self.model_label.setWordWrap(True)
        model_layout.addWidget(self.model_label)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # Quick Actions
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout()
        
        # Commit new version
        self.commit_btn = QPushButton("Commit New Version")
        self.commit_btn.setIcon(get_icon("backup"))
        self.commit_btn.setProperty("primary", "true")
        self.commit_btn.clicked.connect(self.commit_version)
        self.commit_btn.setEnabled(False)
        actions_layout.addWidget(self.commit_btn)
        
        # Compare versions
        self.compare_btn = QPushButton("Compare Selected Versions")
        self.compare_btn.setIcon(get_icon("overlays"))
        self.compare_btn.clicked.connect(self.compare_versions)
        self.compare_btn.setEnabled(False)
        actions_layout.addWidget(self.compare_btn)
        
        # Export timeline
        export_btn = QPushButton("Export Timeline (HTML)")
        export_btn.setIcon(get_icon("export"))
        export_btn.clicked.connect(self.export_timeline)
        export_btn.setEnabled(False)
        self.export_btn = export_btn
        actions_layout.addWidget(export_btn)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)
        
        # Version Statistics
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()
        
        self.stats_label = QLabel("Select a model to view statistics")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("color: #8c93a8;")
        stats_layout.addWidget(self.stats_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Branch selector (future feature)
        branch_group = QGroupBox("Branch")
        branch_layout = QVBoxLayout()
        
        branch_info = QLabel("Current Branch:")
        branch_layout.addWidget(branch_info)
        
        self.branch_combo = QComboBox()
        self.branch_combo.addItem("main")
        self.branch_combo.setEnabled(False)
        branch_layout.addWidget(self.branch_combo)
        
        branch_group.setLayout(branch_layout)
        layout.addWidget(branch_group)
        
        layout.addStretch()
        
        scroll_area.setWidget(panel)
        
        return scroll_area
    
    def _create_right_panel(self) -> QWidget:
        """Create right panel with version timeline."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Timeline header
        timeline_header = QLabel("Version Timeline")
        timeline_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #dcdfe8; padding: 6px 0;")
        layout.addWidget(timeline_header)
        
        # Timeline filter
        filter_layout = QHBoxLayout()
        
        filter_label = QLabel("Filter:")
        filter_layout.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All Versions", "Tagged Only", "Recent (30 days)"])
        self.filter_combo.currentIndexChanged.connect(self.refresh_timeline)
        filter_layout.addWidget(self.filter_combo)
        
        filter_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setIcon(get_icon("refresh"))
        refresh_btn.clicked.connect(self.refresh_timeline)
        filter_layout.addWidget(refresh_btn)
        
        layout.addLayout(filter_layout)
        
        # Version tree/list
        self.version_tree = QTreeWidget()
        self.version_tree.setHeaderLabels(["Version", "Timestamp", "Message", "Metrics", "Tags"])
        self.version_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.version_tree.setAlternatingRowColors(True)
        self.version_tree.itemSelectionChanged.connect(self.on_version_selection_changed)
        self.version_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.version_tree.customContextMenuRequested.connect(self.show_version_context_menu)
        
        # Set column widths
        self.version_tree.setColumnWidth(0, 100)
        self.version_tree.setColumnWidth(1, 180)
        self.version_tree.setColumnWidth(2, 300)
        self.version_tree.setColumnWidth(3, 200)
        
        layout.addWidget(self.version_tree)
        
        # Version details
        details_group = QGroupBox("Version Details")
        details_layout = QVBoxLayout()
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        self.details_text.setPlaceholderText("Select a version to view details...")

        self.version_picture = QLabel("No version selected")
        self.version_picture.setFixedSize(150, 150)
        self.version_picture.setWordWrap(True)
        self.version_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_picture.setStyleSheet(
            "background-color: #14151b; border-radius: 4px; border: 1px solid #232530;")

        details_row = QHBoxLayout()
        details_row.addWidget(self.version_picture)
        details_row.addWidget(self.details_text, 1)
        details_layout.addLayout(details_row)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Action buttons for selected version
        action_layout = QHBoxLayout()
        
        self.restore_btn = QPushButton("Restore This Version")
        self.restore_btn.setIcon(get_icon("refresh"))
        self.restore_btn.clicked.connect(self.restore_version)
        self.restore_btn.setEnabled(False)
        action_layout.addWidget(self.restore_btn)
        
        self.tag_btn = QPushButton("Add Tag")
        self.tag_btn.setIcon(get_icon("add"))
        self.tag_btn.clicked.connect(self.add_tag)
        self.tag_btn.setEnabled(False)
        action_layout.addWidget(self.tag_btn)
        
        layout.addLayout(action_layout)
        
        return panel
    
    def select_model(self):
        """Select a model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select 3D Model",
            "",
            "3D Models (*.obj *.fbx *.glb *.gltf *.stl *.ply *.dae);;All Files (*.*)"
        )
        
        if file_path:
            self.load_model(file_path)
    
    def load_model(self, model_path: str):
        """Load a model and its version history."""
        self.current_model = model_path
        model_name = Path(model_path).name
        
        self.model_label.setText(f"{model_name}\n{model_path}")
        
        # Enable buttons
        self.commit_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        
        # Load version history
        self.refresh_timeline()
        
        logger.info(f"Loaded model: {model_name}")
    
    def refresh_timeline(self):
        """Refresh the version timeline."""
        if not self.current_model:
            return
        
        self.version_tree.clear()
        
        # Get version history
        self.version_history = self.version_control.get_version_history(self.current_model)
        
        # Update statistics
        total_versions = len(self.version_history)
        if total_versions > 0:
            first_version = self.version_history[-1]
            latest_version = self.version_history[0]
            
            stats_text = f"<b>Total Versions:</b> {total_versions}<br>"
            stats_text += f"<b>First:</b> {first_version['timestamp'][:19]}<br>"
            stats_text += f"<b>Latest:</b> {latest_version['timestamp'][:19]}<br>"
            
            # Polygon count evolution
            if total_versions > 1:
                first_polygons = first_version['polygon_count']
                latest_polygons = latest_version['polygon_count']
                if first_polygons is None or latest_polygons is None:
                    # A point cloud has no faces, so there is no change between two of them to
                    # report as one. Saying so is the answer; the arithmetic below is not run.
                    stats_text += f"<b>Polygon Evolution:</b> {NOT_COMPARABLE}"
                else:
                    poly_change = latest_polygons - first_polygons
                    poly_percent = (poly_change / first_polygons * 100) if first_polygons > 0 else 0
                    color = 'red' if poly_change > 0 else 'green' if poly_change < 0 else 'gray'
                    stats_text += f"<b>Polygon Evolution:</b> <span style='color: {color}'>{poly_change:+,} ({poly_percent:+.1f}%)</span>"
            
            self.stats_label.setText(stats_text)
        else:
            self.stats_label.setText("No versions found for this model")
        
        # Populate tree
        for version in self.version_history:
            item = QTreeWidgetItem()
            
            # Version number
            item.setText(0, f"v{version['version_number']}")
            
            # Timestamp
            timestamp = version['timestamp'][:19].replace('T', ' ')
            item.setText(1, timestamp)
            
            # Commit message
            message = version['commit_message']
            if len(message) > 50:
                message = message[:47] + "..."
            item.setText(2, message)
            
            # Metrics
            metrics = describe_metrics(version)
            item.setText(3, metrics)
            
            # Tags (would need to query tags table)
            item.setText(4, "")
            
            # Store version ID in item
            item.setData(0, Qt.ItemDataRole.UserRole, version['id'])
            
            # Color code based on changes
            polygons_delta = version.get('polygons_delta')
            if polygons_delta is not None and polygons_delta < 0:
                item.setForeground(3, QColor('#27ae60'))  # Green for reduction
            elif polygons_delta is not None and polygons_delta > 0:
                item.setForeground(3, QColor('#e74c3c'))  # Red for increase
            
            self.version_tree.addTopLevelItem(item)
        
        logger.info(f"Timeline refreshed: {total_versions} versions")
    
    def on_version_selection_changed(self):
        """Handle version selection change."""
        selected_items = self.version_tree.selectedItems()
        
        if not selected_items:
            self.details_text.clear()
            self._show_version_picture(None)
            self.restore_btn.setEnabled(False)
            self.tag_btn.setEnabled(False)
            self.compare_btn.setEnabled(False)
            return
        
        # Enable buttons
        self.restore_btn.setEnabled(len(selected_items) == 1)
        self.tag_btn.setEnabled(len(selected_items) == 1)
        self.compare_btn.setEnabled(len(selected_items) == 2)
        
        # Show details of first selected version
        version_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        version = next((v for v in self.version_history if v['id'] == version_id), None)
        
        if version:
            details = f"<h3>Version {version['version_number']}</h3>"
            details += f"<p><b>ID:</b> {version['id']}</p>"
            details += f"<p><b>Timestamp:</b> {version['timestamp'][:19].replace('T', ' ')}</p>"
            details += f"<p><b>Author:</b> {version.get('author', 'Unknown')}</p>"
            details += f"<p><b>Branch:</b> {version.get('branch', 'main')}</p>"
            details += f"<hr>"
            details += f"<p><b>Commit Message:</b></p>"
            details += f"<p>{version['commit_message']}</p>"
            details += f"<hr>"
            details += f"<p><b>Metrics:</b></p>"
            details += f"<p>• Polygons: {describe_polygon_count(version)}"
            if version.get('polygons_delta'):
                details += f" ({version['polygons_delta']:+,})"
            details += "</p>"
            details += f"<p>• Vertices: {version['vertex_count']:,}</p>"
            details += f"<p>• File Size: {version['file_size'] / 1024:.1f} KB</p>"
            watertight = describe_watertight(version)
            answer_mark = {'Yes': '✓ ', 'No': '✗ '}.get(watertight, '')
            details += f"<p>• Watertight: {answer_mark}{watertight}</p>"
            
            self.details_text.setHtml(details)

        self._show_version_picture(version)

    def _show_version_picture(self, version):
        """Paint the picture the selected row records, or say which kind of nothing there is.

        Every row this backend writes carries a `thumbnail_path` (`version_control.py:193`,
        `:702`, `:712`), and until this change nothing in `src/ui` read it - a grep over the
        tree at HEAD returns the Library's own different column and a signal argument, no
        widget - while this module's header promises a timeline with thumbnails; the row's own
        picture belongs beside its numbers. The three refusals are three different facts: no row
        is selected, the picture was never drawn, and it was drawn and the file has gone.

        A refusal needs no call of its own to take the previous picture down. Measured here on
        Qt 6.7.1: `setText` with a sentence clears the label's pixmap, `setText('')` does not,
        and `setPixmap` clears the text - so the sentence *is* the withdrawal, and the only way
        a picture comes back is the branch that paints one. The suite pins those three answers
        instead of trusting them to stay.
        """
        if version is None:
            self.version_picture.setText('No version selected')
            return
        path = version.get('thumbnail_path')
        if not path:
            self.version_picture.setText('This version has no picture')
            return
        picture = QPixmap(str(path))
        if picture.isNull():
            self.version_picture.setText('Its picture file could not be read')
            return
        self.version_picture.setPixmap(picture.scaled(
            148, 148, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def commit_version(self):
        """Commit a new version."""
        if not self.current_model:
            return
        
        model_name = Path(self.current_model).name
        dialog = CommitDialog(model_name, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            commit_data = dialog.get_commit_data()
            
            # Save version
            try:
                version_id = self.version_control.save_version(
                    self.current_model,
                    commit_message=commit_data['message'],
                    author=commit_data['author']
                )
                
                if version_id:
                    QMessageBox.information(
                        self,
                        "Version Committed",
                        f"New version saved successfully!\nVersion ID: {version_id}"
                    )
                    self.refresh_timeline()
                    logger.info(f"Version committed: {version_id}")
                else:
                    # `save_version` answers None for four different facts, and this pane used
                    # to name one of them whatever had happened. It asks the backend which.
                    verdict = self.version_control.explain_no_commit(self.current_model)
                    QMessageBox.warning(
                        self,
                        "Nothing Committed",
                        verdict['reason']
                    )
                    logger.warning(f"Commit recorded nothing for {model_name}: {verdict['kind']}")
            except ValueError as e:
                QMessageBox.warning(self, "File Too Large", str(e))
            except IOError as e:
                QMessageBox.critical(self, "Disk Error", str(e))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save version: {str(e)}")
    
    def compare_versions(self):
        """Compare two selected versions."""
        selected_items = self.version_tree.selectedItems()
        
        if len(selected_items) != 2:
            QMessageBox.warning(
                self,
                "Invalid Selection",
                "Please select exactly 2 versions to compare"
            )
            return
        
        version1_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        version2_id = selected_items[1].data(0, Qt.ItemDataRole.UserRole)
        
        # Ensure version1 is older
        if version1_id > version2_id:
            version1_id, version2_id = version2_id, version1_id
        
        # Get comparison
        comparison = self.version_control.compare_versions(version1_id, version2_id)
        
        # Get paths for visual comparison
        v1 = next((v for v in self.version_history if v['id'] == version1_id), None)
        v2 = next((v for v in self.version_history if v['id'] == version2_id), None)
        
        path1 = v1['snapshot_path'] if v1 else None
        path2 = v2['snapshot_path'] if v2 else None
        
        # Show comparison dialog
        dialog = VersionComparisonDialog(comparison, path1, path2, self)
        dialog.exec()
        
        logger.info(f"Compared versions {version1_id} and {version2_id}")
    def restore_version(self):
        """Restore a selected version."""
        selected_items = self.version_tree.selectedItems()
        
        if len(selected_items) != 1:
            return
        
        version_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        version = next((v for v in self.version_history if v['id'] == version_id), None)
        
        if not version:
            return
        
        # Confirm restore
        reply = QMessageBox.question(
            self,
            "Confirm Restore",
            f"Are you sure you want to restore to version {version['version_number']}?\n\n"
            f"Message: {version['commit_message']}\n"
            f"Timestamp: {version['timestamp'][:19]}\n\n"
            f"Note: The current file will be backed up automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = self.version_control.restore_version(version_id)
            
            if success:
                QMessageBox.information(
                    self,
                    "Version Restored",
                    f"Version {version['version_number']} restored successfully!\n\n"
                    f"The current version was automatically backed up."
                )
                self.refresh_timeline()
                self.version_restored.emit(self.current_model)
                logger.info(f"Version {version_id} restored")
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore version. Check logs for details."
                )
    
    def add_tag(self):
        """Add a tag to a version."""
        selected_items = self.version_tree.selectedItems()
        
        if len(selected_items) != 1:
            return
        
        version_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        
        # Get tag name
        tag_name, ok = QInputDialog.getText(
            self,
            "Add Tag",
            "Enter tag name:",
            QLineEdit.EchoMode.Normal,
            ""
        )
        
        if ok and tag_name:
            self.version_control.add_tag(version_id, tag_name)
            QMessageBox.information(
                self,
                "Tag Added",
                f"Tag '{tag_name}' added to version"
            )
            self.refresh_timeline()
            logger.info(f"Tag '{tag_name}' added to version {version_id}")
    
    def export_timeline(self):
        """Export timeline to HTML."""
        if not self.current_model:
            return
        
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Timeline",
            f"timeline_{Path(self.current_model).stem}.html",
            "HTML Files (*.html)"
        )
        
        if output_path:
            self.version_control.export_version_timeline(self.current_model, output_path)
            
            reply = QMessageBox.information(
                self,
                "Timeline Exported",
                f"Timeline exported to:\n{output_path}\n\nWould you like to open it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                import webbrowser
                webbrowser.open(output_path)
            
            logger.info(f"Timeline exported to {output_path}")
    
    def show_version_context_menu(self, position):
        """Show context menu for version items."""
        item = self.version_tree.itemAt(position)
        if not item:
            return
        
        selected_items = self.version_tree.selectedItems()
        menu = QMenu(self)
        
        # Standard actions for single selection
        if len(selected_items) == 1:
            restore_action = QAction("Restore This Version", self)
            restore_action.setIcon(get_icon("refresh"))
            restore_action.triggered.connect(self.restore_version)
            menu.addAction(restore_action)
            
            tag_action = QAction("Add Tag", self)
            tag_action.setIcon(get_icon("add"))
            tag_action.triggered.connect(self.add_tag)
            menu.addAction(tag_action)
            
            menu.addSeparator()
            
            # Comparison actions
            version_id = item.data(0, Qt.ItemDataRole.UserRole)
            current_idx = -1
            
            # Find index in history
            for i, v in enumerate(self.version_history):
                if v['id'] == version_id:
                    current_idx = i
                    break
            
            # Compare with Previous (if not the oldest)
            if current_idx != -1 and current_idx < len(self.version_history) - 1:
                prev_version = self.version_history[current_idx + 1]
                action = QAction(f"Compare with Previous (v{prev_version['version_number']})", self)
                action.setIcon(get_icon("overlays"))
                action.triggered.connect(lambda: self._compare_specific(version_id, prev_version['id']))
                menu.addAction(action)
                
            # Compare with Latest (if not the latest)
            if current_idx > 0:
                latest_version = self.version_history[0]
                action = QAction(f"Compare with Latest (v{latest_version['version_number']})", self)
                action.setIcon(get_icon("overlays"))
                action.triggered.connect(lambda: self._compare_specific(version_id, latest_version['id']))
                menu.addAction(action)

        # Actions for exactly 2 selections
        elif len(selected_items) == 2:
            compare_action = QAction("Compare Selected Versions", self)
            compare_action.setIcon(get_icon("overlays"))
            compare_action.triggered.connect(self.compare_versions)
            menu.addAction(compare_action)
        
        menu.exec(self.version_tree.viewport().mapToGlobal(position))

    def _compare_specific(self, v1_id, v2_id):
        """Helper to compare two specific versions by ID."""
        # Ensure v1 is older
        if v1_id > v2_id:
            v1_id, v2_id = v2_id, v1_id
            
        comparison = self.version_control.compare_versions(v1_id, v2_id)
        
        v1 = next((v for v in self.version_history if v['id'] == v1_id), None)
        v2 = next((v for v in self.version_history if v['id'] == v2_id), None)
        
        path1 = v1['snapshot_path'] if v1 else None
        path2 = v2['snapshot_path'] if v2 else None
        
        dialog = VersionComparisonDialog(comparison, path1, path2, self)
        dialog.exec()


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    # Use a test library path
    library_path = Path(__file__).parent.parent.parent / "output"
    
    window = VersionControlUI(str(library_path))
    window.setWindowTitle("Version Control System")
    window.resize(1400, 900)
    window.show()
    
    sys.exit(app.exec())
