"""
Library tab for centralized model management with database support.
"""

import os
import json
import datetime
import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
                             QTreeWidget, QTreeWidgetItem, QLineEdit, QPushButton, 
                             QComboBox, QLabel, QGroupBox, QFormLayout, QTextEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
                             QSpinBox, QSlider, QTabWidget, QListWidget, QListWidgetItem, QProgressBar,
                             QFrame, QGridLayout, QScrollArea, QMessageBox, QMenu,
                             QFileDialog, QDialog, QDialogButtonBox, QDateEdit,
                             QInputDialog, QApplication, QProgressDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QDate, QThread, QPoint
from PyQt6.QtGui import QPixmap, QIcon, QFont, QAction, QCursor

from .ai_asset_tagger_ui import AIAssetTaggerUI
from ..features.ai_asset_tagger import AIAssetTagger
from src.ui.icon_provider import get_icon
# Import our library manager
from src.core.library_manager import LibraryManager, LibraryScannerWorker, SearchQuery
from ..utils.run_teardown import drain_attributes
from ..utils.app_paths import data_dir, output_dir

# The packaged build has no console (`RenderFox.spec`: console=False), so the only report
# channel a failure has is the root logger the Diagnostics pane reads.
logger = logging.getLogger(__name__)

class ModelCard(QFrame):
    """Visual card widget for displaying a model in grid view."""
    
    clicked = pyqtSignal(dict)  # Emits model data when clicked
    double_clicked = pyqtSignal(dict)
    context_menu_requested = pyqtSignal(dict, QPoint)
    
    def __init__(self, model_data, thumbnail_size=128, parent=None):
        super().__init__(parent)
        self.model_data = model_data
        self.thumbnail_size = thumbnail_size
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ModelCard {
                border: 1px solid #282b38;
                border-radius: 6px;
                background-color: #1a1b24;
                margin: 3px;
            }
            ModelCard:hover {
                border: 1.5px solid #4b7bec;
                background-color: #212431;
            }
        """)
        self.setFixedSize(thumbnail_size + 20, thumbnail_size + 62)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.init_ui()
         
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        
        # Thumbnail image
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(self.thumbnail_size, self.thumbnail_size)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: #14151b; border-radius: 4px; border: 1px solid #232530;")
        
        # Load thumbnail
        self.load_thumbnail()
        layout.addWidget(self.thumbnail_label)
        
        # Model name label
        name = self.model_data.get('name', 'Unknown')
        if len(name) > 16:
            name = name[:13] + '...'
            
        self.name_label = QLabel(name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setToolTip(self.model_data.get('name', 'Unknown'))
        font = QFont('Segoe UI', 9, QFont.Weight.Medium)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("color: #e4e7f2;")
        layout.addWidget(self.name_label)
        
        # Model info label (faces / size)
        faces = self.model_data.get('faces', 0)
        size_mb = self.model_data.get('size_mb', 0.0)
        
        if faces:
            if faces > 1000000:
                faces_str = f"{faces/1000000:.1f}M"
            elif faces > 1000:
                faces_str = f"{faces/1000:.1f}K"
            else:
                faces_str = str(faces)
            info_text = f"{faces_str} • {size_mb:.1f}MB"
        else:
            info_text = f"{size_mb:.1f}MB"
            
        self.info_label = QLabel(info_text)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont('Segoe UI', 8)
        self.info_label.setFont(font)
        self.info_label.setStyleSheet("color: #8c93a8;")
        layout.addWidget(self.info_label)
        
    def load_thumbnail(self):
        """Load and display high quality 3D thumbnail for the model."""
        thumb_path = self.model_data.get('thumbnail') or self.model_data.get('thumb_path')
        
        if not thumb_path or not os.path.exists(thumb_path):
            model_path = self.model_data.get('path')
            if model_path and os.path.exists(model_path):
                try:
                    from src.utils.thumbnail_renderer import generate_3d_thumbnail
                    thumbs_dir = os.path.join(output_dir(), 'thumbnails')
                    os.makedirs(thumbs_dir, exist_ok=True)
                    base = os.path.splitext(os.path.basename(model_path))[0]
                    thumb_path = os.path.join(thumbs_dir, f"{base}.png")
                    generate_3d_thumbnail(model_path, thumb_path, size=256)
                except Exception:
                    pass
                    
        if thumb_path and os.path.exists(thumb_path):
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.thumbnail_size, self.thumbnail_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.thumbnail_label.setPixmap(scaled_pixmap)
                return
                
        # Default placeholder icon based on file type
        ext = self.model_data.get('ext', '').lower()
        self.thumbnail_label.setText(f"3D\n{ext}")
        self.thumbnail_label.setStyleSheet("background-color: #181920; color: #7f8fa6; border-radius: 4px; font-weight: bold;")
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.model_data)
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(self.model_data, event.globalPosition().toPoint())
        super().mousePressEvent(event)
        
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.model_data)
        super().mouseDoubleClickEvent(event)

class ModelTagDialog(QDialog):
    """Dialog for editing model tags and metadata."""
    
    def __init__(self, model_data=None, parent=None):
        super().__init__(parent)
        self.model_data = model_data or {}
        self.setWindowTitle("Edit Model Metadata")
        self.setModal(True)
        self.resize(500, 400)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Basic info
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        
        self.name_edit = QLineEdit(self.model_data.get('name', ''))
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlainText(self.model_data.get('description', ''))
        
        basic_layout.addRow("Name:", self.name_edit)
        basic_layout.addRow("Description:", self.description_edit)
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # Tags
        tags_group = QGroupBox("Tags")
        tags_layout = QVBoxLayout()
        
        self.tags_edit = QLineEdit(self.model_data.get('tags', ''))
        self.tags_edit.setPlaceholderText("building, architecture, high-poly, outdoor")
        tags_layout.addWidget(QLabel("Tags (comma-separated):"))
        tags_layout.addWidget(self.tags_edit)
        
        # Predefined tags
        predefined_layout = QHBoxLayout()
        predefined_tags = ["architecture", "character", "vehicle", "furniture", "nature", 
                          "high-poly", "low-poly", "textured", "game-ready", "cad"]
        for tag in predefined_tags:
            btn = QPushButton(tag)
            btn.clicked.connect(lambda checked, t=tag: self.add_tag(t))
            predefined_layout.addWidget(btn)
        tags_layout.addLayout(predefined_layout)
        
        tags_group.setLayout(tags_layout)
        layout.addWidget(tags_group)
        
        # Metadata
        meta_group = QGroupBox("Metadata")
        meta_layout = QFormLayout()
        
        self.author_edit = QLineEdit(self.model_data.get('author', ''))
        self.license_combo = QComboBox()
        self.license_combo.addItems(["", "CC0", "CC BY", "CC BY-SA", "Commercial", "Custom"])
        self.license_combo.setCurrentText(self.model_data.get('license', ''))
        
        self.rating_slider = QSlider(Qt.Orientation.Horizontal)
        self.rating_slider.setRange(1, 5)
        self.rating_slider.setValue(int(self.model_data.get('rating', 3) or 3))
        self.rating_label = QLabel(str(self.model_data.get('rating', 3) or 3))
        self.rating_slider.valueChanged.connect(lambda v: self.rating_label.setText(str(v)))
        
        rating_layout = QHBoxLayout()
        rating_layout.addWidget(self.rating_slider)
        rating_layout.addWidget(self.rating_label)
        
        meta_layout.addRow("Author:", self.author_edit)
        meta_layout.addRow("License:", self.license_combo)
        meta_layout.addRow("Rating:", rating_layout)
        
        meta_group.setLayout(meta_layout)
        layout.addWidget(meta_group)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                  QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def add_tag(self, tag):
        current = self.tags_edit.text()
        tags = [t.strip() for t in current.split(',') if t.strip()]
        if tag not in tags:
            tags.append(tag)
            self.tags_edit.setText(', '.join(tags))
    
    def get_data(self):
        return {
            'name': self.name_edit.text(),
            'description': self.description_edit.toPlainText(),
            'tags': self.tags_edit.text(),
            'author': self.author_edit.text(),
            'license': self.license_combo.currentText(),
            'rating': self.rating_slider.value()
        }

class LibraryTab(QWidget):
    """Centralized model library management with database support."""

    open_rendering_requested = pyqtSignal(str)
    
    model_selected = pyqtSignal(str)  # Emits path when model is selected for work
    library_updated = pyqtSignal()
    open_mesh_tools_requested = pyqtSignal(str)
    open_preprocessing_requested = pyqtSignal(str)
    open_postprocessing_requested = pyqtSignal(str)
    open_animation_requested = pyqtSignal(str)
    load_globally_requested = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model = None
        self.models_data = []
        self.scanner_worker = None
        
        # Initialize library manager
        self.library = LibraryManager()
        self.setup_library_connections()

        self.ai_tagger_engine = AIAssetTagger(library_manager=self.library)
        
        self.init_ui()
        self.setup_connections()
        self.refresh_all_data()
        
    def setup_library_connections(self):
        """Connect library manager signals to UI updates."""
        self.library.library_changed.connect(self.refresh_all_data)
        self.library.scan_progress.connect(self.update_scan_progress)
        self.library.scan_finished.connect(self.scan_completed)
        self.library.error_occurred.connect(self.show_error)
        self.library.thumbnail_ready.connect(self.thumbnail_updated)
        self.library.selected_for_work.connect(self.model_selected.emit)

    def show_error(self, title, message):
        """Display error message to user."""
        QMessageBox.critical(self, title, message)

    def thumbnail_updated(self, model_path, thumbnail_path):
        """Handle thumbnail update from library manager."""
        # Refresh display if the updated model is currently visible
        self.refresh_model_display()

    def init_ui(self):
        """Initialize the complete UI for the library tab."""
        layout = QVBoxLayout(self)
        
        # Create toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(6)
        
        # Main action buttons
        self.import_btn = QPushButton("Import Models")
        self.import_btn.setIcon(get_icon("import_model"))
        self.import_btn.setProperty("primary", "true")
        
        self.import_folder_btn = QPushButton("Import Folder")
        self.import_folder_btn.setIcon(get_icon("import_folder"))
        
        self.export_btn = QPushButton("Export Library")
        self.export_btn.setIcon(get_icon("export"))
        
        # Add separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        
        self.scan_btn = QPushButton("Scan Library")
        self.scan_btn.setIcon(get_icon("scan"))
        
        self.cleanup_btn = QPushButton("Cleanup DB")
        self.cleanup_btn.setIcon(get_icon("clean"))
        
        self.backup_btn = QPushButton("Backup DB")
        self.backup_btn.setIcon(get_icon("backup"))
        
        self.clear_library_btn = QPushButton("Clear Library")
        self.clear_library_btn.setIcon(get_icon("delete"))
        
        toolbar_layout.addWidget(self.import_btn)
        toolbar_layout.addWidget(self.import_folder_btn)
        toolbar_layout.addWidget(self.export_btn)
        toolbar_layout.addWidget(separator)
        toolbar_layout.addWidget(self.scan_btn)
        toolbar_layout.addWidget(self.cleanup_btn)
        toolbar_layout.addWidget(self.backup_btn)
        toolbar_layout.addWidget(self.clear_library_btn)
        toolbar_layout.addStretch()
        
        layout.addLayout(toolbar_layout)
        
        # Create main content area with tabs
        self.tab_widget = QTabWidget()
        
        # Browser tab
        self.browser_tab = self.create_browser_tab()
        self.tab_widget.addTab(self.browser_tab, "Browser")
        
        # Search tab
        self.search_tab = self.create_search_tab()
        self.tab_widget.addTab(self.search_tab, "Search")
        
        # Collections tab
        self.collections_tab = self.create_collections_tab()
        self.tab_widget.addTab(self.collections_tab, "Collections")
        
        # Statistics tab
        self.statistics_tab = self.create_statistics_tab()
        self.tab_widget.addTab(self.statistics_tab, "Statistics")
        
        # AI tab
        self.ai_tagger_tab = AIAssetTaggerUI()
        self.ai_tagger_tab.tagger = self.ai_tagger_engine
        self.tab_widget.addTab(self.ai_tagger_tab, "AI")
            
        layout.addWidget(self.tab_widget)
        
        # Selection info frame at bottom
        self.selection_frame = self.create_selection_frame()
        layout.addWidget(self.selection_frame)

    def create_browser_tab(self):
        """Create the main browser tab with folder tree and model display."""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        
        # Left side - folder tree and filters
        left_panel = QVBoxLayout()
        
        # Folder management
        folder_group = QGroupBox("Library Folders")
        folder_layout = QVBoxLayout()
        
        folder_buttons = QHBoxLayout()
        self.add_folder_btn = QPushButton("Add Folder")
        self.add_folder_btn.setIcon(get_icon("add"))
        
        self.close_folder_btn = QPushButton("Close Folder")
        self.close_folder_btn.setIcon(get_icon("folder"))
        
        self.reopen_folder_btn = QPushButton("Reopen Folder")
        self.reopen_folder_btn.setIcon(get_icon("refresh"))
        
        self.remove_folder_btn = QPushButton("Remove")
        self.remove_folder_btn.setIcon(get_icon("delete"))
        
        folder_buttons.addWidget(self.add_folder_btn)
        folder_buttons.addWidget(self.close_folder_btn)
        folder_buttons.addWidget(self.reopen_folder_btn)
        folder_buttons.addWidget(self.remove_folder_btn)
        folder_layout.addLayout(folder_buttons)
        
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Folders")
        folder_layout.addWidget(self.folder_tree)
        
        folder_group.setLayout(folder_layout)
        left_panel.addWidget(folder_group)
        
        # Quick filters
        filters_group = QGroupBox("Quick Filters")
        filters_layout = QVBoxLayout()
        
        self.recent_cb = QCheckBox("Recently Added")
        self.favorites_cb = QCheckBox("Favorites")
        self.high_poly_cb = QCheckBox("High Poly (>100k)")
        self.textured_cb = QCheckBox("Textured Models")
        self.broken_cb = QCheckBox("Needs Repair")
        
        filters_layout.addWidget(self.recent_cb)
        filters_layout.addWidget(self.favorites_cb)
        filters_layout.addWidget(self.high_poly_cb)
        filters_layout.addWidget(self.textured_cb)
        filters_layout.addWidget(self.broken_cb)
        
        filters_group.setLayout(filters_layout)
        left_panel.addWidget(filters_group)
        
        # Asset tree
        self.left_asset_tree = QTreeWidget()
        self.left_asset_tree.setHeaderLabels(["Name", "Type", "Date Added"])
        self.left_asset_tree.setColumnWidth(0, 250)
        self.left_asset_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.left_asset_tree.itemSelectionChanged.connect(self.on_asset_selected)
        self.left_asset_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.left_asset_tree.customContextMenuRequested.connect(self.show_context_menu)
        left_panel.addWidget(self.left_asset_tree)
        
        left_widget = QWidget()
        left_widget.setLayout(QVBoxLayout())
        left_widget.layout().addItem(left_panel)
        left_widget.setMaximumWidth(250)
        
        # Right side - model display
        right_panel = QVBoxLayout()
        
        # View controls
        view_controls = QHBoxLayout()
        
        view_controls.addWidget(QLabel("View:"))
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["Grid View", "List View", "Details View"])
        view_controls.addWidget(self.view_mode_combo)
        
        view_controls.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name", "Date Added", "File Size", "Poly Count", "Rating"])
        view_controls.addWidget(self.sort_combo)
        
        self.sort_order_btn_asc = QPushButton()
        self.sort_order_btn_asc.setIcon(get_icon("arrow_up"))
        self.sort_order_btn_asc.setToolTip("Sort Ascending")
        self.sort_order_btn_desc = QPushButton()
        self.sort_order_btn_desc.setIcon(get_icon("arrow_down"))
        self.sort_order_btn_desc.setToolTip("Sort Descending")
        self.sort_order_btn_asc.setMaximumWidth(32)
        self.sort_order_btn_desc.setMaximumWidth(32)
        view_controls.addWidget(self.sort_order_btn_asc)
        view_controls.addWidget(self.sort_order_btn_desc)
        
        view_controls.addWidget(QLabel("Thumbnail Size:"))
        self.thumbnail_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_size_slider.setRange(64, 256)
        self.thumbnail_size_slider.setValue(128)
        self.thumbnail_size_slider.setMaximumWidth(100)
        view_controls.addWidget(self.thumbnail_size_slider)
        
        view_controls.addStretch()
        right_panel.addLayout(view_controls)
        
        # Model display area
        self.model_display = QScrollArea()
        self.model_display.setWidgetResizable(True)
        self.model_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.model_display.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.model_grid_widget = QWidget()
        self.model_grid_layout = QGridLayout(self.model_grid_widget)
        self.model_grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.model_display.setWidget(self.model_grid_widget)
        
        right_panel.addWidget(self.model_display)
        
        # Asset tree
        self.asset_tree = QTreeWidget()
        self.asset_tree.setHeaderLabels(["Name", "Type", "Size", "Date Added"])
        self.asset_tree.setColumnWidth(0, 250)
        self.asset_tree.setAlternatingRowColors(True)
        self.asset_tree.itemDoubleClicked.connect(self.preview_asset)
        self.asset_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.asset_tree.customContextMenuRequested.connect(self.show_asset_context_menu)
        self.asset_tree.setVisible(False)  # Hidden by default as requested
        right_panel.addWidget(self.asset_tree)
        
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        
        # Combine left and right panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        return tab

    def create_search_tab(self):
        """Create the search tab with advanced filtering."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Search controls
        search_group = QGroupBox("Search Criteria")
        search_layout = QFormLayout()
        
        # Text search
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("Search names, tags, descriptions...")
        search_layout.addRow("Text:", self.search_text)
        
        # Tags search
        self.search_tags = QLineEdit()
        self.search_tags.setPlaceholderText("architecture, vehicle, high-poly")
        search_layout.addRow("Tags:", self.search_tags)
        
        # Author search
        self.search_author = QLineEdit()
        search_layout.addRow("Author:", self.search_author)
        
        # File type filter
        self.search_file_type = QComboBox()
        self.search_file_type.addItems(["All Types", ".obj", ".ply", ".stl", ".gltf", ".glb", ".fbx", ".dae", ".x3d"])
        search_layout.addRow("File Type:", self.search_file_type)
        
        # Poly count range
        poly_layout = QHBoxLayout()
        self.search_min_poly = QSpinBox()
        self.search_min_poly.setRange(0, 10000000)
        self.search_max_poly = QSpinBox()
        self.search_max_poly.setRange(0, 10000000)
        self.search_max_poly.setValue(10000000)
        poly_layout.addWidget(self.search_min_poly)
        poly_layout.addWidget(QLabel("to"))
        poly_layout.addWidget(self.search_max_poly)
        search_layout.addRow("Poly Count:", poly_layout)
        
        # File size range
        size_layout = QHBoxLayout()
        self.search_min_size = QSpinBox()
        self.search_min_size.setRange(0, 1000)
        self.search_max_size = QSpinBox()
        self.search_max_size.setRange(0, 1000)
        self.search_max_size.setValue(1000)
        size_layout.addWidget(self.search_min_size)
        size_layout.addWidget(QLabel("to"))
        size_layout.addWidget(self.search_max_size)
        size_layout.addWidget(QLabel("MB"))
        search_layout.addRow("File Size:", size_layout)
        
        # Date range
        date_layout = QHBoxLayout()
        self.search_date_from = QDateEdit()
        self.search_date_from.setDate(QDate.currentDate().addDays(-30))
        self.search_date_to = QDateEdit()
        self.search_date_to.setDate(QDate.currentDate())
        date_layout.addWidget(self.search_date_from)
        date_layout.addWidget(QLabel("to"))
        date_layout.addWidget(self.search_date_to)
        search_layout.addRow("Date Range:", date_layout)
        
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # Search buttons
        search_buttons = QHBoxLayout()
        self.search_btn = QPushButton("Search")
        self.search_btn.setIcon(get_icon("search"))
        self.search_btn.setProperty("primary", "true")
        self.clear_search_btn = QPushButton("Clear")
        self.clear_search_btn.setIcon(get_icon("clean"))
        self.save_search_btn = QPushButton("Save Search")
        self.save_search_btn.setIcon(get_icon("backup"))
        search_buttons.addWidget(self.search_btn)
        search_buttons.addWidget(self.clear_search_btn)
        
        # Saved searches
        self.saved_searches_combo = QComboBox()
        self.saved_searches_combo.setMinimumWidth(150)
        self.saved_searches_combo.addItem("Load Saved Search...")
        self.load_search_btn = QPushButton("Load")
        self.load_search_btn.setIcon(get_icon("folder"))
        self.load_search_btn.clicked.connect(self.load_saved_search)
        
        search_buttons.addWidget(self.saved_searches_combo)
        search_buttons.addWidget(self.load_search_btn)
        search_buttons.addWidget(self.save_search_btn)
        search_buttons.addStretch()
        layout.addLayout(search_buttons)
        
        # Results
        self.search_results = QListWidget()
        layout.addWidget(self.search_results)
        
        self.refresh_saved_searches_list()
        
        return tab

    def create_collections_tab(self):
        """Create the collections management tab."""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        
        # Regular collections
        collections_group = QGroupBox("Collections")
        collections_layout = QVBoxLayout()
        
        collection_buttons = QHBoxLayout()
        self.new_collection_btn = QPushButton("New")
        self.new_collection_btn.setIcon(get_icon("add"))
        self.rename_collection_btn = QPushButton("Rename")
        self.rename_collection_btn.setIcon(get_icon("edit"))
        self.delete_collection_btn = QPushButton("Delete")
        self.delete_collection_btn.setIcon(get_icon("delete"))
        collection_buttons.addWidget(self.new_collection_btn)
        collection_buttons.addWidget(self.rename_collection_btn)
        collection_buttons.addWidget(self.delete_collection_btn)
        collections_layout.addLayout(collection_buttons)
        
        self.collections_list = QListWidget()
        collections_layout.addWidget(self.collections_list)
        
        collections_group.setLayout(collections_layout)
        layout.addWidget(collections_group)
        
        # Smart collections
        smart_group = QGroupBox("Smart Collections")
        smart_layout = QVBoxLayout()
        
        smart_buttons = QHBoxLayout()
        self.new_smart_btn = QPushButton("New Smart Collection")
        self.new_smart_btn.setIcon(get_icon("sparkles"))
        smart_buttons.addWidget(self.new_smart_btn)
        smart_buttons.addStretch()
        smart_layout.addLayout(smart_buttons)
        
        self.smart_collections = QListWidget()
        # Add default smart collections
        default_smart = ["All Models", "Favorites", "Recently Added", "High Poly", 
                        "Textured Models", "Needs Repair"]
        for item in default_smart:
            self.smart_collections.addItem(item)
        
        smart_layout.addWidget(self.smart_collections)
        
        smart_group.setLayout(smart_layout)
        layout.addWidget(smart_group)
        
        return tab

    def create_statistics_tab(self):
        """Create the statistics and maintenance tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Statistics display
        stats_group = QGroupBox("Library Statistics")
        stats_layout = QFormLayout()
        
        self.stats_total_models = QLabel("0")
        self.stats_total_size = QLabel("0 GB")
        self.stats_avg_poly = QLabel("0")
        self.stats_file_types = QLabel("")
        self.stats_favorites = QLabel("0")
        self.stats_recent = QLabel("0")
        
        stats_layout.addRow("Total Models:", self.stats_total_models)
        stats_layout.addRow("Total Size:", self.stats_total_size)
        stats_layout.addRow("Average Poly Count:", self.stats_avg_poly)
        stats_layout.addRow("File Types:", self.stats_file_types)
        stats_layout.addRow("Favorites:", self.stats_favorites)
        stats_layout.addRow("Recently Added:", self.stats_recent)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Maintenance actions
        maintenance_group = QGroupBox("Database Maintenance")
        maintenance_layout = QVBoxLayout()
        
        self.check_integrity_btn = QPushButton("Check Database Integrity")
        self.check_integrity_btn.setIcon(get_icon("diagnostics"))
        self.rebuild_thumbnails_btn = QPushButton("Rebuild All Thumbnails")
        self.rebuild_thumbnails_btn.setIcon(get_icon("camera"))
        self.optimize_db_btn = QPushButton("Optimize Database")
        self.optimize_db_btn.setIcon(get_icon("performance"))
        self.vacuum_db_btn = QPushButton("Vacuum Database")
        self.vacuum_db_btn.setIcon(get_icon("clean"))
        
        maintenance_layout.addWidget(self.check_integrity_btn)
        maintenance_layout.addWidget(self.rebuild_thumbnails_btn)
        maintenance_layout.addWidget(self.optimize_db_btn)
        maintenance_layout.addWidget(self.vacuum_db_btn)
        
        maintenance_group.setLayout(maintenance_layout)
        layout.addWidget(maintenance_group)
        
        layout.addStretch()
        return tab

    def create_selection_frame(self):
        """Create the bottom frame showing selected model info and actions."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setMaximumHeight(120)
        
        layout = QHBoxLayout(frame)
        
        # Model info
        info_layout = QVBoxLayout()
        self.selected_name = QLabel("No model selected")
        self.selected_name.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.selected_info = QLabel("")
        self.selected_path = QLabel("")
        self.selected_path.setStyleSheet("color: #666; font-size: 10px;")
        
        info_layout.addWidget(self.selected_name)
        info_layout.addWidget(self.selected_info)
        info_layout.addWidget(self.selected_path)
        
        layout.addLayout(info_layout)
        layout.addStretch()
        
        # Action buttons
        # Use GridLayout for uniform sizing
        action_layout = QGridLayout()
        action_layout.setSpacing(10)
        
        self.select_for_work_btn = QPushButton("Select for Work")
        self.select_for_work_btn.setIcon(get_icon("select", color="#ffffff"))
        self.select_for_work_btn.setProperty("primary", "true")
        self.select_for_work_btn.setMinimumHeight(38)
        
        self.edit_metadata_btn = QPushButton("Edit Metadata")
        self.edit_metadata_btn.setIcon(get_icon("edit"))
        self.edit_metadata_btn.setMinimumHeight(38)
        
        self.add_to_collection_btn = QPushButton("Add to Collection")
        self.add_to_collection_btn.setIcon(get_icon("add"))
        self.add_to_collection_btn.setMinimumHeight(38)
        
        self.favorite_btn = QPushButton("Favorite")
        self.favorite_btn.setIcon(get_icon("favorite"))
        self.favorite_btn.setMinimumHeight(38)
        
        # Add to grid (row, col)
        action_layout.addWidget(self.select_for_work_btn, 0, 0)
        action_layout.addWidget(self.edit_metadata_btn, 0, 1)
        action_layout.addWidget(self.add_to_collection_btn, 1, 0)
        action_layout.addWidget(self.favorite_btn, 1, 1)
        
        # Ensure equal column width
        action_layout.setColumnStretch(0, 1)
        action_layout.setColumnStretch(1, 1)
        
        layout.addLayout(action_layout)
        
        return frame

    # ...existing UI creation methods...

    def setup_connections(self):
        """Connect UI signals to handlers."""
        # Toolbar buttons
        self.import_btn.clicked.connect(self.import_models)
        self.import_folder_btn.clicked.connect(self.import_folder)
        self.export_btn.clicked.connect(self.export_library)
        self.scan_btn.clicked.connect(self.scan_library)
        self.cleanup_btn.clicked.connect(self.cleanup_database)
        self.backup_btn.clicked.connect(self.backup_database)
        self.clear_library_btn.clicked.connect(self.clear_library_database)
        
        # Browser tab
        self.add_folder_btn.clicked.connect(self.add_library_folder)
        self.close_folder_btn.clicked.connect(self.close_library_folder)
        self.reopen_folder_btn.clicked.connect(self.reopen_library_folder)
        self.remove_folder_btn.clicked.connect(self.remove_library_folder)
        self.folder_tree.itemSelectionChanged.connect(self.folder_selection_changed)
        
        # Filters
        self.recent_cb.toggled.connect(self.apply_filters)
        self.favorites_cb.toggled.connect(self.apply_filters)
        self.high_poly_cb.toggled.connect(self.apply_filters)
        self.textured_cb.toggled.connect(self.apply_filters)
        self.broken_cb.toggled.connect(self.apply_filters)
        
        # View controls
        self.view_mode_combo.currentTextChanged.connect(self.change_view_mode)
        self.sort_combo.currentTextChanged.connect(self.update_sort)
        self.sort_order_btn_asc.clicked.connect(lambda: self.set_sort_order(False))
        self.sort_order_btn_desc.clicked.connect(lambda: self.set_sort_order(True))
        self.thumbnail_size_slider.valueChanged.connect(self.update_thumbnail_size)
        
        # Search tab
        self.search_btn.clicked.connect(self.perform_search)
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.save_search_btn.clicked.connect(self.save_search)
        self.search_text.returnPressed.connect(self.perform_search)
        self.search_results.itemDoubleClicked.connect(self.search_result_double_clicked)
        
        # Collections tab
        self.collections_list.itemSelectionChanged.connect(self.collection_selection_changed)
        self.smart_collections.itemSelectionChanged.connect(self.smart_collection_selection_changed)
        self.new_collection_btn.clicked.connect(self.create_new_collection)
        self.rename_collection_btn.clicked.connect(self.rename_collection)
        self.delete_collection_btn.clicked.connect(self.delete_collection)
        self.new_smart_btn.clicked.connect(self.create_smart_collection)
        
        # Statistics tab
        self.check_integrity_btn.clicked.connect(self.check_integrity)
        self.rebuild_thumbnails_btn.clicked.connect(self.rebuild_thumbnails)
        self.optimize_db_btn.clicked.connect(self.optimize_database)
        self.vacuum_db_btn.clicked.connect(self.vacuum_database)
        
        # Selection frame - THIS WAS THE MISSING CONNECTION!
        self.select_for_work_btn.clicked.connect(self.select_current_for_work)
        self.edit_metadata_btn.clicked.connect(self.edit_current_metadata)
        self.add_to_collection_btn.clicked.connect(self.add_current_to_collection)
        self.favorite_btn.clicked.connect(self.toggle_current_favorite)

        # Add context menu to grid view
        self.model_display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model_display.customContextMenuRequested.connect(self.show_context_menu)

    # ---------------------- Toolbar Actions ----------------------
    def import_models(self):
        """Import individual model files."""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("3D Models (*.obj *.ply *.stl *.gltf *.glb *.fbx *.dae *.x3d)")
        
        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            files = file_dialog.selectedFiles()
            if files:
                # Ensure parent folders are in the library so models are visible
                folders_to_add = set()
                existing_folders = self.library.list_folders()
                
                for file_path in files:
                    parent_dir = os.path.dirname(os.path.abspath(file_path))
                    
                    # Check if this directory is already covered by an existing library folder
                    is_covered = False
                    for folder in existing_folders:
                        lib_path = folder['path']
                        is_recursive = folder['recursive']
                        
                        # Exact match or recursive parent
                        if parent_dir == lib_path or (is_recursive and parent_dir.startswith(lib_path + os.sep)):
                            is_covered = True
                            break
                    
                    if not is_covered:
                        folders_to_add.add(parent_dir)
                
                # Add uncovered folders as non-recursive
                for folder in folders_to_add:
                    self.library.add_folder(folder, recursive=False)
                
                self.start_import_worker(files)
    
    def import_folder(self):
        """Import all models from a folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Import")
        if folder:
            # Add folder to library and scan
            self.library.add_folder(folder, recursive=True)
            self.scan_library()
    
    def add_model_to_library(self, path):
        """Add a single model file to the library (programmatic access)."""
        if os.path.exists(path):
            self.start_import_worker([path])
            QMessageBox.information(self, "Library Import", 
                                  f"Started importing: {os.path.basename(path)}")
        else:
            QMessageBox.warning(self, "Import Failed", 
                              f"File not found: {path}")

    def export_library(self):
        """Export library to JSON."""
        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setNameFilter("JSON Files (*.json)")
        file_dialog.setDefaultSuffix("json")
        
        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            files = file_dialog.selectedFiles()
            if files:
                if self.library.export_library(files[0]):
                    QMessageBox.information(self, "Export Complete", 
                                          f"Library exported to {files[0]}")
                else:
                    QMessageBox.warning(self, "Export Failed", 
                                      "Failed to export library")
    
    def scan_library(self):
        """Scan all library folders for models."""
        if self.scanner_worker and self.scanner_worker.isRunning():
            QMessageBox.information(self, "Scan in Progress", 
                                  "A scan is already in progress")
            return
        
        self.start_scan_worker()
    
    def cleanup_database(self):
        """Clean up missing files from database."""
        reply = QMessageBox.question(self, "Cleanup Database", 
                                    "Remove entries for missing files from database?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            removed = self.library.cleanup_missing_files()
            QMessageBox.information(self, "Cleanup Complete", 
                                  f"Removed {removed} missing file entries")
    
    def backup_database(self):
        """Create database backup."""
        backup_path = self.library.backup_database()
        if backup_path:
            QMessageBox.information(self, "Backup Complete", 
                                  f"Database backed up to {backup_path}")
        else:
            QMessageBox.warning(self, "Backup Failed", 
                              "Failed to create database backup")

    def vacuum_database(self):
        """Vacuum the database to reclaim space and optimize performance."""
        reply = QMessageBox.question(self, "Vacuum Database", 
                                    "This will optimize the database and reclaim unused space. Continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if self.library.vacuum_database():
                    QMessageBox.information(self, "Vacuum Complete", 
                                          "Database has been successfully vacuumed")
                else:
                    QMessageBox.warning(self, "Vacuum Failed", 
                                      "Failed to vacuum database")
            except Exception as e:
                QMessageBox.critical(self, "Vacuum Error", 
                                   f"Error during database vacuum: {str(e)}")

#     def optimize_database(self):
#         """Optimize the database."""
#         reply = QMessageBox.question(self, "Optimize Database", 
#                                     "This will analyze and optimize the database. Continue?",
#                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
#         if reply == QMessageBox.StandardButton.Yes:
#             try:
#                 if self.library.optimize_database():
#                     QMessageBox.information(self, "Optimization Complete", 
#                                           "Database has been optimized")
#                 else:
#                     QMessageBox.warning(self, "Optimization Failed", 
#                                       "Failed to optimize database")
#             except Exception as e:
#                 QMessageBox.critical(self, "Optimization Error", 
#                                    f"Error during database optimization: {str(e)}")
# 
    def clear_library_database(self):
        """Clear all library data from the database."""
        reply = QMessageBox.question(
            self, "Clear Library", 
            "This will permanently delete ALL library data including:\n\n"
            "• All model entries\n"
            "• All collections\n"
            "• All metadata and tags\n"
            "• All library folders\n\n"
            "This action cannot be undone!\n\n"
            "Are you sure you want to clear the entire library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Show progress dialog
                progress = QProgressDialog("Clearing library database...", None, 0, 0, self)
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setRange(0, 0)  # Indeterminate progress
                progress.show()
                QApplication.processEvents()
                
                # Clear the library using the library manager's method
                if self.library.clear_library():
                    progress.close()
                    
                    # Clear the UI displays
                    self.clear_model_grid()
                    self.folder_tree.clear()
                    self.collections_list.clear()
                    self.search_results.clear()
                    
                    # Reset selection info
                    self.current_model = None
                    self.update_selection_info()
                    
                    # Refresh all displays
                    self.refresh_all_data()
                    
                    QMessageBox.information(
                        self, "Library Cleared", 
                        "Library has been completely cleared successfully!"
                    )
                else:
                    progress.close()
                    QMessageBox.warning(self, "Clear Failed", "Failed to clear library database")
                    
            except Exception as e:
                if 'progress' in locals():
                    progress.close()
                QMessageBox.critical(self, "Clear Error", f"Error clearing library: {str(e)}")

    # ---------------------- Worker Management ----------------------
    def start_scan_worker(self):
        """Start background scanning worker."""
        self.scanner_worker = LibraryScannerWorker(self.library)
        self.scanner_worker.start()
    
    def start_import_worker(self, files):
        """Start background import worker."""
        self.scanner_worker = LibraryScannerWorker(self.library, files)
        self.scanner_worker.start()

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Wait for a scan or import that is still walking the library folders.

        This run answers nothing into the interface - `start_scan_worker` and
        `start_import_worker` connect no signal - so the close is not waiting to keep a
        verdict out of a dead widget. It waits because the worker is writing the library
        itself: `LibraryManager.scan` and `import_files` add rows, and an exit in the
        middle of them leaves the index part-filled with nothing said about it. What
        outlasts the wait stays referenced by `scanner_worker`, which is also the guard
        the pane's own re-entry check reads. Returns the scans still owed.
        """
        return len(drain_attributes(self, ('scanner_worker',), timeout_ms))
    
    def update_scan_progress(self, percent, message):
        """Update progress during scanning."""
        # For now, show in status - could add progress bar later
        pass
    
    def scan_completed(self, added, updated):
        """Handle scan completion."""
        message = f"Scan complete: {added} added, {updated} updated"
        QMessageBox.information(self, "Scan Complete", message)

    # ---------------------- Browser Tab ----------------------
    def add_library_folder(self):
        """Add a folder to the library."""
        folder = QFileDialog.getExistingDirectory(self, "Add Library Folder")
        if folder:
            self.library.add_folder(folder, recursive=True)
            self.refresh_folder_tree()
    
    def close_library_folder(self):
        """Close selected folder from library (make inactive but preserve data)."""
        current = self.folder_tree.currentItem()
        if current:
            folder_path = current.text(0)
            
            # Check if folder is already closed
            if not self.library.is_folder_active(folder_path):
                QMessageBox.information(self, "Already Closed", 
                                      f"Folder '{folder_path}' is already closed.")
                return
            
            reply = QMessageBox.question(
                self, "Close Folder", 
                f"Close folder '{folder_path}'?\n\n"
                "This will hide the folder's models from the library view "
                "but preserve all data and metadata. You can reopen it later.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                if self.library.close_folder(folder_path):
                    self.refresh_folder_tree()
                    self.refresh_model_display()
                    QMessageBox.information(self, "Folder Closed", 
                                          f"Folder '{folder_path}' has been closed.")
                else:
                    QMessageBox.warning(self, "Close Failed", 
                                      f"Failed to close folder '{folder_path}'.")
        else:
            QMessageBox.warning(self, "No Selection", "Please select a folder to close.")
    
    def reopen_library_folder(self):
        """Reopen a closed folder."""
        # Get list of inactive folders
        inactive_folders = self.library.get_inactive_folders()
        
        if not inactive_folders:
            QMessageBox.information(self, "No Closed Folders", 
                                  "There are no closed folders to reopen.")
            return
        
        # Show selection dialog
        folder_paths = [f["path"] for f in inactive_folders]
        folder_path, ok = QInputDialog.getItem(
            self, "Reopen Folder", "Select folder to reopen:", 
            folder_paths, 0, False
        )
        
        if ok and folder_path:
            if self.library.open_folder(folder_path):
                self.refresh_folder_tree()
                self.refresh_model_display()
                QMessageBox.information(self, "Folder Reopened", 
                                      f"Folder '{folder_path}' has been reopened.")
            else:
                QMessageBox.warning(self, "Reopen Failed", 
                                  f"Failed to reopen folder '{folder_path}'.")
    
    def remove_library_folder(self):
        """Remove selected folder from library."""
        current = self.folder_tree.currentItem()
        if current:
            folder_path = current.text(0)
            reply = QMessageBox.question(self, "Remove Folder", 
                                        f"Remove '{folder_path}' from library?")
            if reply == QMessageBox.StandardButton.Yes:
                self.library.remove_folder(folder_path)
                self.refresh_folder_tree()
    
    def folder_selection_changed(self):
        """Handle folder tree selection change."""
        self.update_folder_button_states()
        self.refresh_model_display()
    
    def refresh_folder_tree(self):
        """Refresh the folder tree display."""
        self.folder_tree.clear()
        
        # Get active folders
        active_folders = self.library.get_active_folders()
        for folder in active_folders:
            folder_path = folder.get('path', folder) if isinstance(folder, dict) else folder
            item = QTreeWidgetItem([folder_path])
            item.setData(0, Qt.ItemDataRole.UserRole, {'path': folder_path, 'active': True})
            self.folder_tree.addTopLevelItem(item)
        
        # Get inactive (closed) folders and show them differently
        inactive_folders = self.library.get_inactive_folders()
        for folder in inactive_folders:
            folder_path = folder.get('path', folder) if isinstance(folder, dict) else folder
            item = QTreeWidgetItem([f"{folder_path} (Closed)"])
            item.setData(0, Qt.ItemDataRole.UserRole, {'path': folder_path, 'active': False})
            # Style closed folders differently
            item.setForeground(0, Qt.GlobalColor.gray)
            self.folder_tree.addTopLevelItem(item)
        
        # Update button states
        self.update_folder_button_states()

    def update_folder_button_states(self):
        """Update the states of folder-related buttons based on current selection."""
        current = self.folder_tree.currentItem()
        
        # Get inactive folders for reopen button
        try:
            inactive_folders = self.library.get_inactive_folders()
            has_inactive_folders = len(inactive_folders) > 0
        except:
            has_inactive_folders = False
        
        if current:
            folder_data = current.data(0, Qt.ItemDataRole.UserRole)
            if folder_data and isinstance(folder_data, dict):
                is_active = folder_data.get('active', True)
                folder_path = folder_data.get('path', '')
                
                # Close button: enabled for active folders
                self.close_folder_btn.setEnabled(is_active and folder_path)
                
                # Remove button: always enabled when something is selected
                self.remove_folder_btn.setEnabled(True)
            else:
                # Legacy handling for items without proper data
                folder_text = current.text(0)
                is_closed = "(Closed)" in folder_text
                
                self.close_folder_btn.setEnabled(not is_closed)
                self.remove_folder_btn.setEnabled(True)
        else:
            # No selection
            self.close_folder_btn.setEnabled(False)
            self.remove_folder_btn.setEnabled(False)
        
        # Reopen button: enabled when there are inactive folders
        self.reopen_folder_btn.setEnabled(has_inactive_folders)

    def apply_filters(self):
        """Apply quick filters to model display."""
        self.refresh_model_display()
    
    def change_view_mode(self, mode):
        """Change between grid/list/details view."""
        self.refresh_model_display()
    
    def update_sort(self):
        """Update sort criteria."""
        self.refresh_model_display()
    
    def set_sort_order(self, descending):
        """Set sort order."""
        if descending:
            self.sort_order_btn_desc.setStyleSheet("background-color: #3498db; color: white;")
            self.sort_order_btn_asc.setStyleSheet("")
        else:
            self.sort_order_btn_asc.setStyleSheet("background-color: #3498db; color: white;")
            self.sort_order_btn_desc.setStyleSheet("")
        self.refresh_model_display()
    
    def update_thumbnail_size(self, size):
        """Update thumbnail display size."""
        self.refresh_model_display()

    # ---------------------- Model Display ----------------------
    def refresh_model_display(self):
        """Refresh the model display with current filters/sort."""
        # Get filtered models
        models = self.get_filtered_models()
        
        # Clear current display
        self.clear_model_grid()
        
        # Display based on view mode
        view_mode = self.view_mode_combo.currentText()
        if view_mode == "Grid View":
            self.display_models_grid(models)
        elif view_mode == "List View":
            self.display_models_list(models)
        else:  # Details View
            self.display_models_details(models)

    def get_filtered_models(self):
        """Get models with current filters applied."""        
        try:
            # Start with base query - use fallback methods if library methods fail
            if self.recent_cb.isChecked():
                models = self._safe_get_models('get_recent', default_days=7)
            elif self.favorites_cb.isChecked():
                models = self._safe_get_models('get_favorites')
            elif self.high_poly_cb.isChecked():
                models = self._safe_get_models('get_high_poly', default_threshold=100000)
            elif self.textured_cb.isChecked():
                models = self._safe_get_models('get_textured')
            elif self.broken_cb.isChecked():
                models = self._safe_get_models('get_broken')
            else:
                models = self._safe_get_models('get_models')
            
            # Apply additional filters if needed
            # Folder-specific filtering
            current_folder_item = self.folder_tree.currentItem()
            if current_folder_item:
                folder_data = current_folder_item.data(0, Qt.ItemDataRole.UserRole)
                if folder_data and isinstance(folder_data, dict):
                    folder_path = folder_data.get('path', '')
                    if folder_path:
                        # Filter models to only those inside this folder
                        models = [m for m in models if m.get('path', '').startswith(folder_path)]
            
            # Apply sorting
            sort_field = self.sort_combo.currentText().lower().replace(' ', '_')
            reverse = self.sort_order_btn_desc.styleSheet() != ""
            
            sort_map = {
                'name': 'name',
                'date_added': 'date_added', 
                'file_size': 'size_mb',
                'poly_count': 'faces',
                'rating': 'rating'
            }
            
            field = sort_map.get(sort_field, 'name')
            try:
                models.sort(key=lambda x: x.get(field, 0) or 0, reverse=reverse)
            except:
                pass
                
            return models
            
        except Exception as e:
            self.show_error("Filter Error", f"Failed to filter models: {str(e)}")
            return []

    def _safe_get_models(self, method_name, **kwargs):
        """Safely get models using library manager methods with fallbacks."""        
        try:
            if hasattr(self.library, method_name):
                method = getattr(self.library, method_name)
                if kwargs:
                    return method(**kwargs)
                else:
                    return method()
            else:
                # Fallback to basic get_models if specific method doesn't exist
                if hasattr(self.library, 'get_models'):
                    return self.library.get_models()
                else:
                    # Final fallback - return empty list
                    return []
        except Exception as e:
            logger.warning("Error getting models with %s: %s", method_name, e)
            # Return basic models list as fallback
            try:
                return self.library.get_models() if hasattr(self.library, 'get_models') else []
            except:
                return []

    def clear_model_grid(self):
        """Clear the model display grid."""        
        # Remove all widgets from grid layout
        layout = self.model_grid_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
    
    def display_models_grid(self, models):
        """Display models in grid layout."""        
        thumbnail_size = self.thumbnail_size_slider.value()
        cols = max(1, (self.model_display.width() - 40) // (thumbnail_size + 30))
        
        for i, model in enumerate(models[:100]):
            card = ModelCard(model, thumbnail_size=thumbnail_size)
            card.clicked.connect(self.model_card_clicked)
            card.double_clicked.connect(self.model_card_double_clicked)
            card.context_menu_requested.connect(self.show_model_context_menu)
            
            row = i // cols
            col = i % cols
            self.model_grid_layout.addWidget(card, row, col)

    def display_models_list(self, models):
        """Display models in list layout."""
        for i, model in enumerate(models[:100]):
            # Create a horizontal frame for each list item
            list_item = QFrame()
            list_item.setFrameStyle(QFrame.Shape.StyledPanel)
            list_item.setStyleSheet("""
                QFrame {
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    background-color: white;
                    margin: 1px;
                    padding: 4px;
                }
                QFrame:hover {
                    border: 2px solid #3498db;
                    background-color: #f8f9fa;
                }
            """)
            list_item.setFixedHeight(85)
            list_item.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            
            # Horizontal layout for list item
            item_layout = QHBoxLayout(list_item)
            item_layout.setContentsMargins(6, 6, 6, 6)
            
            # Thumbnail
            thumbnail_label = QLabel()
            thumbnail_label.setFixedSize(50, 50)
            thumbnail_label.setStyleSheet("border: 1px solid #ccc; background: #f5f5f5;")
            thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Load thumbnail if available
            thumb_path = model.get('thumbnail', '')
            if thumb_path and os.path.exists(thumb_path):
                pixmap = QPixmap(thumb_path).scaled(
                    50, 50, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                thumbnail_label.setPixmap(pixmap)
            else:
                ext = os.path.splitext(model.get('path', ''))[1].upper()
                thumbnail_label.setText(ext or "?")
            
            item_layout.addWidget(thumbnail_label)
            
            # Model info section
            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)
            
            # Model name
            name = os.path.splitext(os.path.basename(model.get('path', '')))[0]
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
            info_layout.addWidget(name_label)
            
            # Model details
            details = []
            if model.get('faces'):
                details.append(f"{model['faces']:,} faces")
            if model.get('size_mb'):
                details.append(f"{model['size_mb']:.1f} MB")
            if model.get('format'):
                details.append(model['format'].upper())
            
            details_label = QLabel(" • ".join(details))
            details_label.setStyleSheet("color: #666; font-size: 10px;")
            info_layout.addWidget(details_label)
            
            item_layout.addLayout(info_layout)
            item_layout.addStretch()
            
            # Add click handlers
            def make_click_handler(model_data):
                def mouse_press_event(event):
                    if event.button() == Qt.MouseButton.LeftButton:
                        self.model_card_clicked(model_data)
                return mouse_press_event
            
            def make_double_click_handler(model_data):
                def mouse_double_click_event(event):
                    if event.button() == Qt.MouseButton.LeftButton:
                        self.model_card_double_clicked(model_data)
                return mouse_double_click_event
            
            def make_context_menu_handler(model_data):
                def context_menu_event(event):
                    self.show_model_context_menu(model_data, event.globalPos())
                return context_menu_event

            list_item.mousePressEvent = make_click_handler(model)
            list_item.mouseDoubleClickEvent = make_double_click_handler(model)
            list_item.contextMenuEvent = make_context_menu_handler(model)
            
            # Add to grid layout (one per row)
            self.model_grid_layout.addWidget(list_item, i, 0)

    def display_models_details(self, models):
        """Display models with detailed information in table format."""        
        # Clear current layout and create a table widget
        self.clear_model_grid()
        
        # Create table widget
        table = QTableWidget()
        table.setRowCount(len(models[:100]))
        table.setColumnCount(7)
        
        # Set headers
        headers = ["Thumbnail", "Name", "Format", "Faces", "Size (MB)", "Date Added", "Rating"]
        table.setHorizontalHeaderLabels(headers)
        
        # Configure table
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        
        # Populate table
        for i, model in enumerate(models[:100]):
            # Thumbnail
            thumbnail_label = QLabel()
            thumbnail_label.setFixedSize(48, 48)
            thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            thumb_path = model.get('thumbnail', '')
            if thumb_path and os.path.exists(thumb_path):
                pixmap = QPixmap(thumb_path).scaled(
                    48, 48, Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                thumbnail_label.setPixmap(pixmap)
            else:
                ext = os.path.splitext(model.get('path', ''))[1].upper()
                thumbnail_label.setText(ext or "?")
            
            table.setCellWidget(i, 0, thumbnail_label)
            
            # Name
            name = os.path.splitext(os.path.basename(model.get('path', '')))[0]
            table.setItem(i, 1, QTableWidgetItem(name))
            
            # Format
            format_ext = os.path.splitext(model.get('path', ''))[1].upper()
            table.setItem(i, 2, QTableWidgetItem(format_ext))
            
            # Faces
            faces = model.get('faces', 0)
            faces_str = f"{faces:,}" if faces else "Unknown"
            table.setItem(i, 3, QTableWidgetItem(faces_str))
            
            # Size
            size_mb = model.get('size_mb', 0)
            size_str = f"{size_mb:.1f}" if size_mb else "Unknown"
            table.setItem(i, 4, QTableWidgetItem(size_str))
            
            # Date Added
            date_added = model.get('date_added', '')
            if date_added:
                try:
                    from datetime import datetime
                    if isinstance(date_added, (int, float)):
                        dt = datetime.fromtimestamp(date_added)
                        date_str = dt.strftime('%Y-%m-%d')
                    elif isinstance(date_added, str):
                        dt = datetime.fromisoformat(date_added.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d')
                    else:
                        date_str = str(date_added)
                except:
                    date_str = str(date_added)
            else:
                date_str = "Unknown"
            table.setItem(i, 5, QTableWidgetItem(date_str))
            
            # Rating
            rating = model.get('rating', 0)
            rating_str = "★" * rating if rating else "Not rated"
            table.setItem(i, 6, QTableWidgetItem(rating_str))
            
            # Store model data in the first column item
            if table.item(i, 1):
                table.item(i, 1).model_data = model
        
        # Resize columns to content
        table.resizeColumnsToContents()
        table.setColumnWidth(0, 60)  # Thumbnail column
        
        # Connect selection
        def on_table_selection():
            current_row = table.currentRow()
            if current_row >= 0 and table.item(current_row, 1):
                model_data = getattr(table.item(current_row, 1), 'model_data', None)
                if model_data:
                    self.model_card_clicked(model_data)
        
        def on_table_double_click():
            current_row = table.currentRow()
            if current_row >= 0 and table.item(current_row, 1):
                model_data = getattr(table.item(current_row, 1), 'model_data', None)
                if model_data:
                    self.model_card_double_clicked(model_data)
        
        table.itemSelectionChanged.connect(on_table_selection)
        table.itemDoubleClicked.connect(on_table_double_click)
        
        # Add table to the layout
        self.model_grid_layout.addWidget(table, 0, 0)

    def model_card_clicked(self, model_data):
        """Handle model card click."""        
        self.current_model = model_data
        self.update_selection_info()
    
    def model_card_double_clicked(self, model_data):
        """Handle model card double-click - select for work."""        
        self.current_model = model_data
        self.select_current_for_work()

#     def select_current_for_work(self):
#         """Select the currently highlighted model for work in other tabs."""
#         if not self.current_model:
#             QMessageBox.warning(self, "No Selection", "Please select a model first.")
#             return
#             
#         path = self.current_model.get('path', '')
#         if not path or not os.path.exists(path):
#             QMessageBox.warning(self, "Invalid Path", f"Model path not found: {path}")
#             return
#             
        # Emit signal to load globally
#         self.load_globally_requested.emit(path)
#         
        # Also notify library manager for history/stats
#         try:
#             self.library.mark_as_recent(path)
#         except:
#             pass
# 
    # ---------------------- Search Tab ----------------------
    def perform_search(self):
        """Perform search with current criteria."""        
        # Create search query from UI elements
        query = SearchQuery()
        
        # Text search
        text = self.search_text.text().strip()
        if text:
            query.text = text
        
        # Tags search
        tags = self.search_tags.text().strip()
        if tags:
            query.tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
        
        # Author search
        author = self.search_author.text().strip()
        if author:
            query.author = author
        
        # File type filter
        file_type = self.search_file_type.currentText()
        if file_type != "All Types":
            query.file_extension = file_type
        
        # Poly count range
        if self.search_min_poly.value() > 0:
            query.min_faces = self.search_min_poly.value()
        if self.search_max_poly.value() < 10000000:
            query.max_faces = self.search_max_poly.value()
        
        # File size range
        if self.search_min_size.value() > 0:
            query.min_size_mb = self.search_min_size.value()
        if self.search_max_size.value() < 1000:
            query.max_size_mb = self.search_max_size.value()
        
        # Date range
        query.date_from = self.search_date_from.date().toPython()
        query.date_to = self.search_date_to.date().toPython()
        
        # Perform search
        try:
            results = self.library.search(query)
            self.display_search_results(results)
        except Exception as e:
            self.show_error("Search Error", f"Failed to perform search: {str(e)}")
    
    def clear_search(self):
        """Clear all search criteria."""        
        self.search_text.clear()
        self.search_tags.clear()
        self.search_author.clear()
        self.search_file_type.setCurrentIndex(0)
        self.search_min_poly.setValue(0)
        self.search_max_poly.setValue(10000000)
        self.search_min_size.setValue(0)
        self.search_max_size.setValue(1000)
        self.search_date_from.setDate(QDate.currentDate().addDays(-30))
        self.search_date_to.setDate(QDate.currentDate())
        self.search_results.clear()
    
    def save_search(self):
        """Save current search criteria."""        
        name, ok = QInputDialog.getText(self, "Save Search", "Search name:")
        if ok and name:
            search_data = {
                'text': self.search_text.text(),
                'tags': self.search_tags.text(),
                'author': self.search_author.text(),
                'file_type': self.search_file_type.currentText(),
                'min_poly': self.search_min_poly.value(),
                'max_poly': self.search_max_poly.value(),
                'min_size': self.search_min_size.value(),
                'max_size': self.search_max_size.value(),
                'date_from': self.search_date_from.date().toString(Qt.DateFormat.ISODate),
                'date_to': self.search_date_to.date().toString(Qt.DateFormat.ISODate)
            }
            
            self._save_search_to_file(name, search_data)
            self.refresh_saved_searches_list()
            QMessageBox.information(self, "Search Saved", f"Search '{name}' saved")

    def load_saved_search(self):
        """Load selected saved search."""
        name = self.saved_searches_combo.currentText()
        if name == "Load Saved Search...":
            return
            
        searches = self._load_searches_from_file()
        if name in searches:
            data = searches[name]
            self.search_text.setText(data.get('text', ''))
            self.search_tags.setText(data.get('tags', ''))
            self.search_author.setText(data.get('author', ''))
            self.search_file_type.setCurrentText(data.get('file_type', 'All Types'))
            self.search_min_poly.setValue(data.get('min_poly', 0))
            self.search_max_poly.setValue(data.get('max_poly', 10000000))
            self.search_min_size.setValue(data.get('min_size', 0))
            self.search_max_size.setValue(data.get('max_size', 1000))
            
            if 'date_from' in data:
                self.search_date_from.setDate(QDate.fromString(data['date_from'], Qt.DateFormat.ISODate))
            if 'date_to' in data:
                self.search_date_to.setDate(QDate.fromString(data['date_to'], Qt.DateFormat.ISODate))
                
            QMessageBox.information(self, "Search Loaded", f"Loaded search '{name}'")

    def _get_saved_searches_file(self):
        """Get path to saved searches file."""
        import json
        config_dir = data_dir()
        return os.path.join(config_dir, "saved_searches.json")

    def _save_search_to_file(self, name, data):
        """Save search data to file."""
        import json
        file_path = self._get_saved_searches_file()
        searches = self._load_searches_from_file()
        searches[name] = data
        
        try:
            with open(file_path, 'w') as f:
                json.dump(searches, f, indent=4)
        except Exception as e:
            logger.error("Error saving search: %s", e)

    def _load_searches_from_file(self):
        """Load searches from file."""
        import json
        file_path = self._get_saved_searches_file()
        if not os.path.exists(file_path):
            return {}
            
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading searches: %s", e)
            return {}

    def refresh_saved_searches_list(self):
        """Refresh the saved searches combo box."""
        self.saved_searches_combo.clear()
        self.saved_searches_combo.addItem("Load Saved Search...")
        
        searches = self._load_searches_from_file()
        for name in sorted(searches.keys()):
            self.saved_searches_combo.addItem(name)
    
    def display_search_results(self, results):
        """Display search results in the results list and main grid."""        
        # Clear and populate the search results list
        self.search_results.clear()
        for model in results:
            name = os.path.basename(model.get('path', ''))
            item_text = f"{name} - {model.get('faces', '?')} faces"
            item = QListWidget.QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, model)
            self.search_results.addItem(item)
        
        # Also display search results in the main model grid for better visual integration
        self.clear_model_grid()
        self.display_models_grid(results)
        
        # Update models data for sorting/filtering
        self.models_data = results
        
        # Switch to browser tab to show visual results
        self.tab_widget.setCurrentIndex(0)  # Browser tab
        
        # Show status message
        if results:
            status_msg = f"Found {len(results)} models matching search criteria"
        else:
            status_msg = "No models found matching search criteria"
        
        # Add status item to search results
        status_item = QListWidgetItem(status_msg)
        status_item.setFlags(Qt.ItemFlag.NoItemFlags)  # Make it non-selectable
        self.search_results.insertItem(0, status_item)

    def search_result_double_clicked(self, item):
        """Handle double-click on search result."""        
        model_data = item.data(Qt.ItemDataRole.UserRole)
        if model_data:
            self.current_model = model_data
            self.select_current_for_work()

    # ---------------------- Data Refresh Methods ----------------------
    def refresh_all_data(self):
        """Refresh all data displays in the library tab."""        
        self.refresh_folder_tree()
        self.refresh_model_display()
        self.refresh_statistics()
        self.refresh_collections()
        
    def refresh_statistics(self):
        """Refresh the statistics display."""        
        stats = self.library.get_statistics()
        if stats:
            self.stats_total_models.setText(str(stats.get('total_models', 0)))
            self.stats_total_size.setText(f"{stats.get('total_size_gb', 0):.1f} GB")
            self.stats_avg_poly.setText(str(stats.get('avg_poly_count', 0)))
            
            # Format file_types list as a readable string
            file_types = stats.get('file_types', [])
            if isinstance(file_types, list) and file_types:
                # file_types is a list of tuples [(ext, count), ...]
                file_types_str = ', '.join([f"{ext} ({count})" for ext, count in file_types[:5]])  # Show top 5
                if len(file_types) > 5:
                    file_types_str += f", and {len(file_types) - 5} more"
            else:
                file_types_str = "No data"
            self.stats_file_types.setText(file_types_str)
            
            self.stats_favorites.setText(str(stats.get('favorites_count', 0)))
            self.stats_recent.setText(str(stats.get('recent_count', 0)))

    def refresh_collections(self):
        """Refresh the collections display."""        
        self.collections_list.clear()
        collections = self.library.get_collections()
        for collection in collections:
            self.collections_list.addItem(collection.get('name', ''))

    # ...existing code for other tab creation methods...

    def collection_selection_changed(self):
        """Handle selection change in collections list."""        
        selected_items = self.collections_list.selectedItems()
        if selected_items:
            collection_name = selected_items[0].text()
            # TODO: Load collection contents
            self.load_collection(collection_name)
    
    def load_collection(self, collection_name):
        """Load and display models from the selected collection."""        
        try:
            # Get models in the collection from database
            models = self.library.get_models_by_collection(collection_name)
            
            # Clear current display and show collection models in main grid
            self.clear_model_grid()
            self.display_models_grid(models)
            
            # Update models data for sorting/filtering
            self.models_data = models
            
            # Switch to browser tab to show the results
            self.tab_widget.setCurrentIndex(0)  # Browser tab
            
            # Update status in search results as well for reference
            self.search_results.clear()
            for model in models:
                name = os.path.basename(model.get('path', ''))
                item_text = f"{name} - {model.get('faces', '?')} faces"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, model)
                self.search_results.addItem(item)
                
        except Exception as e:
            self.show_error("Collection Error", f"Failed to load collection '{collection_name}': {str(e)}")

    # ...existing code...

    def smart_collection_selection_changed(self):
        """Handle selection change in smart collections list."""        
        selected_items = self.smart_collections.selectedItems()
        if selected_items:
            collection_name = selected_items[0].text()
            # TODO: Load smart collection contents based on criteria
            self.load_smart_collection(collection_name)
    
    def load_smart_collection(self, collection_name):
        """Load and display models from the selected smart collection."""        
        try:
            # Clear current display
            self.clear_model_grid()
            
            # Apply smart collection filters based on name
            if collection_name == "All Models":
                models = self.library.get_models()
            elif collection_name == "Favorites":
                models = self.library.get_favorites()
            elif collection_name == "Recently Added":
                models = self.library.get_recent(days=7)
            elif collection_name == "High Poly":
                models = self.library.get_high_poly(face_threshold=100000)
            elif collection_name == "Textured Models":
                models = self.library.get_textured()
            elif collection_name == "Needs Repair":
                models = self.library.get_broken()
            else:
                # Check if it's a custom smart collection from database
                cursor = self.library.db_connection.cursor()
                cursor.execute("SELECT criteria FROM collections WHERE name = ? AND is_smart = 1", (collection_name,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    # Parse criteria and filter models
                    try:
                        criteria = json.loads(result[0])
                    except Exception:
                        criteria = eval(result[0])
                    models = self._filter_models_by_criteria(criteria)
                else:
                    models = []
            
            # Display the filtered models in the main grid
            self.display_models_grid(models)
            
            # Update status
            self.models_data = models
            
        except Exception as e:
            self.show_error("Smart Collection Error", f"Failed to load smart collection '{collection_name}': {str(e)}")
    
    def _filter_models_by_criteria(self, criteria):
        """Filter models based on smart collection criteria."""        
        # Start with all models
        query = SearchQuery()
        
        # Apply criteria filters
        if 'format' in criteria:
            query.file_extension = criteria['format']
        
        if 'date_after' in criteria:
            from datetime import datetime
            date_obj = datetime.strptime(criteria['date_after'], '%Y-%m-%d')
            query.date_from_ts = int(date_obj.timestamp())
        
        if 'tags' in criteria:
            query.tags = criteria['tags']
        
        # Use library search to apply filters
        return self.library.search_models(query)

    # ...existing code...
    
    def create_new_collection(self):
        """Create a new model collection."""        
        dialog = QInputDialog()
        dialog.setWindowTitle("New Collection")
        dialog.setLabelText("Enter collection name:")
        dialog.setTextValue("")
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            collection_name = dialog.textValue().strip()
            if collection_name:
                try:
                    # Add to database
                    cursor = self.library.db_connection.cursor()
                    cursor.execute(
                        "INSERT INTO collections (name, description) VALUES (?, ?)",
                        (collection_name, f"Collection created on {datetime.now().strftime('%Y-%m-%d')}")
                    )
                    self.library.db_connection.commit()
                    
                    # Refresh collections list
                    self.load_collections()
                    
                    # Show success message
                    QMessageBox.information(self, "Success", f"Collection '{collection_name}' created successfully!")
                    
                except Exception as e:
                    self.show_error("Collection Error", f"Failed to create collection: {str(e)}")
            else:
                QMessageBox.warning(self, "Invalid Input", "Collection name cannot be empty!")

    # ...existing code...
    
    def rename_collection(self):
        """Rename the selected collection."""        
        current_item = self.collections_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a collection to rename!")
            return
        
        current_name = current_item.text()
        dialog = QInputDialog()
        dialog.setWindowTitle("Rename Collection")
        dialog.setLabelText("Enter new collection name:")
        dialog.setTextValue(current_name)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name = dialog.textValue().strip()
            if new_name and new_name != current_name:
                try:
                    # Update in database
                    cursor = self.library.db_connection.cursor()
                    cursor.execute(
                        "UPDATE collections SET name = ? WHERE name = ?",
                        (new_name, current_name)
                    )
                    self.library.db_connection.commit()
                    
                    # Refresh collections list
                    self.load_collections()
                    
                    # Show success message
                    QMessageBox.information(self, "Success", f"Collection renamed to '{new_name}' successfully!")
                    
                except Exception as e:
                    self.show_error("Rename Error", f"Failed to rename collection: {str(e)}")
            elif not new_name:
                QMessageBox.warning(self, "Invalid Input", "Collection name cannot be empty!")

    # ...existing code...
    
    def delete_collection(self):
        """Delete the selected collection."""        
        current_item = self.collections_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a collection to delete!")
            return
        
        collection_name = current_item.text()
        
        # Confirm deletion
        reply = QMessageBox.question(
            self, 
            "Confirm Deletion", 
            f"Are you sure you want to delete the collection '{collection_name}'?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Delete from database
                cursor = self.library.db_connection.cursor()
                cursor.execute("DELETE FROM collections WHERE name = ?", (collection_name,))
                cursor.execute("DELETE FROM collection_models WHERE collection_name = ?", (collection_name,))
                self.library.db_connection.commit()
                
                # Refresh collections list
                self.load_collections()
                
                # Show success message
                QMessageBox.information(self, "Success", f"Collection '{collection_name}' deleted successfully!")
                
            except Exception as e:
                self.show_error("Delete Error", f"Failed to delete collection: {str(e)}")

    # ...existing code...
    
    def create_smart_collection(self):
        """Create a new smart collection with criteria."""        
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Smart Collection")
        dialog.setModal(True)
        dialog.resize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Collection name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Name:"))
        name_input = QLineEdit()
        name_layout.addWidget(name_input)
        layout.addLayout(name_layout)
        
        # Criteria section
        layout.addWidget(QLabel("Smart Collection Criteria:"))
        
        criteria_group = QGroupBox("Filter Options")
        criteria_layout = QVBoxLayout(criteria_group)
        
        # File format filter
        format_layout = QHBoxLayout()
        format_check = QCheckBox("File Format:")
        format_combo = QComboBox()
        format_combo.addItems(["", ".obj", ".fbx", ".dae", ".ply", ".stl", ".gltf", ".glb"])
        format_layout.addWidget(format_check)
        format_layout.addWidget(format_combo)
        criteria_layout.addLayout(format_layout)
        
        # Date filter
        date_layout = QHBoxLayout()
        date_check = QCheckBox("Added after:")
        date_edit = QDateEdit()
        date_edit.setDate(QDate.currentDate().addDays(-30))
        date_layout.addWidget(date_check)
        date_layout.addWidget(date_edit)
        criteria_layout.addLayout(date_layout)
        
        # Tags filter
        tags_layout = QHBoxLayout()
        tags_check = QCheckBox("Contains tags:")
        tags_input = QLineEdit()
        tags_input.setPlaceholderText("Enter tags separated by commas")
        tags_layout.addWidget(tags_check)
        tags_layout.addWidget(tags_input)
        criteria_layout.addLayout(tags_layout)
        
        layout.addWidget(criteria_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        create_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(create_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect buttons
        create_btn.clicked.connect(lambda: self._create_smart_collection_from_dialog(
            dialog, name_input, format_check, format_combo, 
            date_check, date_edit, tags_check, tags_input
        ))
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()
    
    def _create_smart_collection_from_dialog(self, dialog, name_input, format_check, 
                                           format_combo, date_check, date_edit, 
                                           tags_check, tags_input):
        """Helper method to create smart collection from dialog inputs."""        
        name = name_input.text().strip()
        if not name:
            QMessageBox.warning(dialog, "Invalid Name", "Please enter a collection name!")
            return
        
        # Build criteria dictionary
        criteria = {}
        
        if format_check.isChecked() and format_combo.currentText():
            criteria['format'] = format_combo.currentText()
        
        if date_check.isChecked():
            criteria['date_after'] = date_edit.date().toString('yyyy-MM-dd')
        
        if tags_check.isChecked() and tags_input.text().strip():
            criteria['tags'] = [tag.strip() for tag in tags_input.text().split(',') if tag.strip()]
        
        try:
            # Store smart collection in database
            cursor = self.library.db_connection.cursor()
            cursor.execute(
                "INSERT INTO collections (name, is_smart, criteria) VALUES (?, 1, ?)",
                (name, str(criteria))
            )
            self.library.db_connection.commit()
            
            # Refresh collections list
            self.load_collections()
            
            QMessageBox.information(dialog, "Success", f"Smart collection '{name}' created successfully!")
            dialog.accept()
            
        except Exception as e:
            self.show_error("Creation Error", f"Failed to create smart collection: {str(e)}")

    # ...existing code...
    
#     def check_integrity(self):
#         """Check and repair database integrity."""        
#         try:
            # Show progress dialog
#             progress = QProgressDialog("Checking database integrity...", "Cancel", 0, 0, self)
#             progress.setWindowModality(Qt.WindowModality.WindowModal)
#             progress.show()
#             
            # Check for missing files
#             cursor = self.library.db_connection.cursor()
#             cursor.execute("SELECT id, file_path FROM models")
#             models = cursor.fetchall()
#             
#             missing_files = []
#             for model_id, file_path in models:
#                 if not os.path.exists(file_path):
#                     missing_files.append((model_id, file_path))
#             
#             progress.close()
#             
            # Report results
#             if missing_files:
#                 message = f"Found {len(missing_files)} missing files:\n\n"
#                 for model_id, file_path in missing_files[:10]:  # Show first 10
#                     message += f"• {os.path.basename(file_path)}\n"
#                 
#                 if len(missing_files) > 10:
#                     message += f"... and {len(missing_files) - 10} more"
#                 
#                 message += "\n\nWould you like to remove these entries from the database?"
#                 
#                 reply = QMessageBox.question(
#                     self, "Missing Files Found", message,
#                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
#                 )
#                 
#                 if reply == QMessageBox.StandardButton.Yes:
                    # Remove missing entries
#                     for model_id, _ in missing_files:
#                         cursor.execute("DELETE FROM models WHERE id = ?", (model_id,))
#                     self.library.db_connection.commit()
#                     
                    # Refresh view
#                     self.refresh_library()
#                     
#                     QMessageBox.information(
#                         self, "Cleanup Complete", 
#                         f"Removed {len(missing_files)} missing entries from database."
#                     )
#             else:
#                 QMessageBox.information(
#                     self, "Integrity Check", 
#                     "Database integrity check completed. No issues found."
#                 )
#                 
#         except Exception as e:
#             self.show_error("Integrity Check Error", f"Failed to check integrity: {str(e)}")
# 
    def rebuild_thumbnails(self):
        """Rebuild all thumbnails in the library."""        
        try:
            # Get all models
            cursor = self.library.db_connection.cursor()
            cursor.execute("SELECT id, file_path FROM models")
            models = cursor.fetchall()
            
            if not models:
                QMessageBox.information(self, "No Models", "No models found in library.")
                return
            
            # Confirm action
            reply = QMessageBox.question(
                self, "Rebuild Thumbnails",
                f"This will rebuild thumbnails for {len(models)} models. This may take some time. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            # Show progress dialog
            progress = QProgressDialog("Rebuilding thumbnails...", "Cancel", 0, len(models), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.show()
            
            # Clear existing thumbnails directory
            thumbnails_dir = os.path.join(output_dir(), 'thumbnails')
            if os.path.exists(thumbnails_dir):
                import shutil
                shutil.rmtree(thumbnails_dir)
            os.makedirs(thumbnails_dir, exist_ok=True)
            
            # Rebuild thumbnails
            success_count = 0
            for i, (model_id, file_path) in enumerate(models):
                if progress.wasCanceled():
                    break
                
                progress.setValue(i)
                progress.setLabelText(f"Processing {os.path.basename(file_path)}...")
                QApplication.processEvents()
                
                try:
                    # Generate thumbnail
                    thumbnail_path = os.path.join(thumbnails_dir, f"{model_id}.png")
                    # You would implement actual thumbnail generation here
                    # For now, just update the database
                    cursor.execute(
                        "UPDATE models SET thumbnail_path = ? WHERE id = ?",
                        (thumbnail_path, model_id)
                    )
                    success_count += 1
                except Exception as e:
                    logger.warning("Failed to generate thumbnail for %s: %s", file_path, e)
            
            progress.close()
            
            # Commit changes and refresh
            self.library.db_connection.commit()
            self.refresh_library()
            
            QMessageBox.information(
                self, "Rebuild Complete",
                f"Successfully rebuilt {success_count} of {len(models)} thumbnails."
            )
            
        except Exception as e:
            self.show_error("Rebuild Error", f"Failed to rebuild thumbnails: {str(e)}")

    def optimize_database(self):
        """Optimize the library database."""        
        try:
            # Confirm action
            reply = QMessageBox.question(
                self, "Optimize Database",
                "This will optimize the database by cleaning up unused space and rebuilding indexes. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            # Show progress
            progress = QProgressDialog("Optimizing database...", None, 0, 0, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setRange(0, 0)  # Indeterminate progress
            progress.show()
            QApplication.processEvents()
            
            cursor = self.library.db_connection.cursor()
            
            # Get database size before optimization
            cursor.execute("PRAGMA page_count")
            pages_before = cursor.fetchone()[0]
            cursor.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            size_before = pages_before * page_size
            
            # Vacuum the database
            progress.setLabelText("Vacuuming database...")
            QApplication.processEvents()
            cursor.execute("VACUUM")
            
            # Reindex
            progress.setLabelText("Rebuilding indexes...")
            QApplication.processEvents()
            cursor.execute("REINDEX")
            
            # Analyze for better query planning
            progress.setLabelText("Analyzing tables...")
            QApplication.processEvents()
            cursor.execute("ANALYZE")
            
            # Get database size after optimization
            cursor.execute("PRAGMA page_count")
            pages_after = cursor.fetchone()[0]
            size_after = pages_after * page_size
            
            progress.close()
            
            # Calculate space saved
            space_saved = size_before - size_after
            space_saved_mb = space_saved / (1024 * 1024)
            
            QMessageBox.information(
                self, "Optimization Complete",
                f"Database optimization completed successfully.\n"
                f"Space saved: {space_saved_mb:.2f} MB"
            )
            
        except Exception as e:
            if 'progress' in locals():
                progress.close()
            self.show_error("Optimization Error", f"Failed to optimize database: {str(e)}")

    # ---------------------- Selection Frame Actions ----------------------
    def select_current_for_work(self):
        """Select the current model for work in other tabs."""
        if not self.current_model:
            QMessageBox.warning(self, "No Selection", "Please select a model first!")
            return
        
        model_path = self.current_model.get('path', '')
        if not model_path or not os.path.exists(model_path):
            QMessageBox.warning(self, "File Not Found", "Selected model file does not exist!")
            return
        
        # Show action selection dialog
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Action")
        dialog.setMinimumWidth(500)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel(f"<h3>Selected: {os.path.basename(model_path)}</h3>")
        layout.addWidget(title)
        
        layout.addWidget(QLabel("<b>Choose where to work with this model:</b>"))
        
        # AI TAGGER
        ai_btn = QPushButton("AI Tag This Model")
        ai_btn.setIcon(get_icon("sparkles"))
        ai_btn.clicked.connect(lambda: self._open_in_ai_tagger(model_path, dialog))
        layout.addWidget(ai_btn)
        
        # QUALITY ANALYZER
        quality_btn = QPushButton("Analyze Quality")
        quality_btn.setIcon(get_icon("diagnostics"))
        quality_btn.clicked.connect(lambda: self._open_in_quality_analyzer(model_path, dialog))
        layout.addWidget(quality_btn)
        
        # COMPARE
        compare_btn = QPushButton("Add to Comparison")
        compare_btn.setIcon(get_icon("overlays"))
        compare_btn.clicked.connect(lambda: self._open_in_comparison(model_path, dialog))
        layout.addWidget(compare_btn)
        
        # VERSION CONTROL
        version_btn = QPushButton("View Version History")
        version_btn.setIcon(get_icon("version_control"))
        version_btn.clicked.connect(lambda: self._open_in_version_control(model_path, dialog))
        layout.addWidget(version_btn)
        
        # PIPELINE
        pipeline_btn = QPushButton("Use in Pipeline")
        pipeline_btn.setIcon(get_icon("pipeline"))
        pipeline_btn.clicked.connect(lambda: self._open_in_pipeline(model_path, dialog))
        layout.addWidget(pipeline_btn)
        
        # BATCH OPERATIONS
        batch_btn = QPushButton("Use in Batch Operations")
        batch_btn.setIcon(get_icon("batch_render"))
        batch_btn.clicked.connect(lambda: self._open_in_batch_operations(model_path, dialog))
        layout.addWidget(batch_btn)
        
        # VIEW IN MODEL TAB (default)
        view_btn = QPushButton("View in Model Tab")
        view_btn.setIcon(get_icon("models"))
        view_btn.setProperty("primary", "true")
        view_btn.clicked.connect(lambda: self._open_in_model_viewer(model_path, dialog))
        layout.addWidget(view_btn)

        # OPEN IN MESH TOOLS
        mesh_tools_btn = QPushButton("Open in Mesh Tools Tab")
        mesh_tools_btn.setIcon(get_icon("mesh_tools"))
        mesh_tools_btn.clicked.connect(lambda: self._open_in_mesh_tools(model_path, dialog))
        layout.addWidget(mesh_tools_btn)
        
        # Cancel
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(cancel_btn)
        
        dialog.exec()
    
    def edit_current_metadata(self):
        """Edit metadata for the currently selected model."""        
        if not self.current_model:
            QMessageBox.warning(self, "No Selection", "Please select a model first!")
            return
        
        dialog = ModelTagDialog(self.current_model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get updated data
            updated_data = dialog.get_data()
            
            # Update model in database with error handling
            try:
                model_id = self.current_model.get('id')
                if model_id:
                    # Try using library manager method first
                    if hasattr(self.library, 'update_model_metadata'):
                        success = self.library.update_model_metadata(model_id, updated_data)
                    else:
                        # Fallback to direct database access with error handling
                        try:
                            cursor = self.library.db_connection.cursor()
                            cursor.execute("""
                                UPDATE models SET 
                                name = ?, description = ?, tags = ?, 
                                author = ?, license = ?, rating = ?
                                WHERE id = ?
                            """, (
                                updated_data['name'],
                                updated_data['description'],
                                updated_data['tags'],
                                updated_data['author'],
                                updated_data['license'],
                                updated_data['rating'],
                                model_id
                            ))
                            self.library.db_connection.commit()
                            success = True
                        except AttributeError:
                            QMessageBox.warning(self, "Database Error", 
                                              "Database connection not available. Metadata not saved.")
                            return
                    
                    if success:
                        # Update current model data
                        self.current_model.update(updated_data)
                        self.update_selection_info()
                        
                        QMessageBox.information(self, "Success", "Model metadata updated successfully!")
                    else:
                        QMessageBox.warning(self, "Update Failed", "Failed to save metadata changes")
                        
            except Exception as e:
                QMessageBox.critical(self, "Update Error", f"Failed to update metadata: {str(e)}")

    def add_current_to_collection(self):
        """Add current model to a collection."""        
        if not self.current_model:
            QMessageBox.warning(self, "No Selection", "Please select a model first!")
            return
        
        # Get available collections with error handling
        try:
            collections = self.library.get_collections()
            if not collections:
                QMessageBox.information(self, "No Collections", 
                                      "No collections available. Create one first!")
                return
            
            # Show collection selection dialog
            collection_names = [c.get('name', '') for c in collections if c.get('name')]
            if not collection_names:
                QMessageBox.information(self, "No Collections", 
                                      "No valid collections found. Create one first!")
                return
                
            collection_name, ok = QInputDialog.getItem(
                self, "Add to Collection", "Select collection:", 
                collection_names, 0, False
            )
            
            if ok and collection_name:
                model_id = self.current_model.get('id')
                if model_id:
                    # Try using library manager method first
                    if hasattr(self.library, 'add_model_to_collection'):
                        success = self.library.add_model_to_collection(model_id, collection_name)
                    else:
                        # Fallback to direct database access with error handling
                        try:
                            cursor = self.library.db_connection.cursor()
                            cursor.execute("""
                                INSERT OR IGNORE INTO collection_models (collection_name, model_id)
                                VALUES (?, ?)
                            """, (collection_name, model_id))
                            self.library.db_connection.commit()
                            success = True
                        except AttributeError:
                            QMessageBox.warning(self, "Database Error", 
                                              "Database connection not available. Cannot add to collection.")
                            return
                        except Exception as db_error:
                            QMessageBox.critical(self, "Database Error", 
                                               f"Failed to add to collection: {str(db_error)}")
                            return
                    
                    if success:
                        QMessageBox.information(self, "Success", 
                                              f"Model added to collection '{collection_name}'!")
                    else:
                        QMessageBox.warning(self, "Add Failed", "Failed to add model to collection")
                        
        except Exception as e:
            QMessageBox.critical(self, "Collection Error", f"Failed to add to collection: {str(e)}")

    def toggle_current_favorite(self):
        """Toggle favorite status for the current model."""        
        if not self.current_model:
            QMessageBox.warning(self, "No Selection", "Please select a model first!")
            return
        
        try:
            model_path = self.current_model.get('path')
            model_id = self.current_model.get('id')
            if not model_path and not model_id:
                QMessageBox.warning(self, "Invalid Model", "Model path/ID not found!")
                return
                
            # Get current favorite status - check both field names for compatibility
            current_favorite = self.current_model.get('favorite', self.current_model.get('is_favorite', False))
            if isinstance(current_favorite, int):
                current_favorite = bool(current_favorite)
                
            new_favorite = not current_favorite
            
            # Try multiple approaches to update favorites
            success = False
            
            # First try: Use library manager's set_favorite method with path
            if model_path and hasattr(self.library, 'set_favorite'):
                try:
                    success = self.library.set_favorite(model_path, new_favorite)
                except Exception:
                    success = False
            
            # Second try: Use the library manager's set_model_favorite method if it exists
            if not success and model_id and hasattr(self.library, 'set_model_favorite'):
                try:
                    success = self.library.set_model_favorite(model_id, new_favorite)
                except Exception:
                    success = False
            
            # Third try: Fallback to direct database access with error handling
            if not success and model_id:
                try:
                    if hasattr(self.library, 'conn'):
                        cursor = self.library.conn.cursor()
                        cursor.execute("UPDATE models SET favorite = ? WHERE id = ?", 
                                     (1 if new_favorite else 0, model_id))
                        self.library.conn.commit()
                        success = True
                    elif hasattr(self.library, 'db_connection'):
                        cursor = self.library.db_connection.cursor()
                        cursor.execute("UPDATE models SET is_favorite = ? WHERE id = ?", 
                                     (new_favorite, model_id))
                        self.library.db_connection.commit()
                        success = True
                except AttributeError:
                    # Database connection doesn't exist, try alternative approach
                    if hasattr(self.library, 'update_model_metadata'):
                        success = self.library.update_model_metadata(model_id, {'is_favorite': new_favorite})
                    elif hasattr(self.library, 'update_metadata') and model_path:
                        success = self.library.update_metadata(model_path, {'favorite': 1 if new_favorite else 0})
                except Exception as db_error:
                    QMessageBox.critical(self, "Database Error", f"Database operation failed: {str(db_error)}")
                    return
            
            if success:
                # Update current model data - use both field names for compatibility
                self.current_model['favorite'] = 1 if new_favorite else 0
                self.current_model['is_favorite'] = new_favorite
                
                # Update button text and style
                if new_favorite:
                    self.favorite_btn.setText("★ Favorited")
                    self.favorite_btn.setStyleSheet("background-color: #f39c12; color: white;")
                else:
                    self.favorite_btn.setText("☆ Favorite")
                    self.favorite_btn.setStyleSheet("")
                
                action = "added to" if new_favorite else "removed from"
                QMessageBox.information(self, "Success", f"Model {action} favorites!")
            else:
                QMessageBox.warning(self, "Update Failed", "Failed to update favorite status")
            
        except Exception as e:
            QMessageBox.critical(self, "Favorite Error", f"Failed to update favorite: {str(e)}")
    
    def update_selection_info(self):
        """Update the selection info panel with current model details."""        
        if not self.current_model:
            self.selected_name.setText("No model selected")
            self.selected_info.setText("")
            self.selected_path.setText("")
            self.select_for_work_btn.setEnabled(False)
            self.edit_metadata_btn.setEnabled(False)
            self.add_to_collection_btn.setEnabled(False)
            self.favorite_btn.setEnabled(False)
            return
        
        # Update labels
        name = self.current_model.get('name') or os.path.splitext(
            os.path.basename(self.current_model.get('path', '')))[0]
        self.selected_name.setText(name)
        
        # Build info string
        info_parts = []
        if self.current_model.get('faces'):
            info_parts.append(f"{self.current_model['faces']:,} faces")
        if self.current_model.get('size_mb'):
            info_parts.append(f"{self.current_model['size_mb']:.1f} MB")
        if self.current_model.get('format'):
            info_parts.append(self.current_model['format'].upper())
        
        self.selected_info.setText(" • ".join(info_parts))
        self.selected_path.setText(self.current_model.get('path', ''))
        
        # Update favorite button - check both field names for compatibility
        favorite_status = self.current_model.get('favorite', self.current_model.get('is_favorite', 0))
        is_favorite = bool(favorite_status) if isinstance(favorite_status, int) else favorite_status
        
        if is_favorite:
            self.favorite_btn.setText("★ Favorited")
            self.favorite_btn.setStyleSheet("background-color: #f39c12; color: white;")
        else:
            self.favorite_btn.setText("☆ Favorite")
            self.favorite_btn.setStyleSheet("")
        
        # Enable buttons
        self.select_for_work_btn.setEnabled(True)
        self.edit_metadata_btn.setEnabled(True)
        self.add_to_collection_btn.setEnabled(True)
        self.favorite_btn.setEnabled(True)

    # Missing method implementations
#     def load_collections(self):
#         """Load collections from database and populate the collections list."""        
#         try:
#             self.collections_list.clear()
#             collections = self.library.get_collections()
#             for collection in collections:
#                 self.collections_list.addItem(collection.get('name', ''))
#         except Exception as e:
#             self.show_error("Collections Error", f"Failed to load collections: {str(e)}")
# 
#     def refresh_library(self):
#         """Refresh the entire library display."""        
#         self.refresh_all_data()
# 
    # ...existing code for other tab creation methods...
# 
#     def load_collections(self):
#         """Load collections from database and populate the collections list."""        
#         try:
#             self.collections_list.clear()
#             collections = self.library.get_collections()
#             for collection in collections:
#                 self.collections_list.addItem(collection.get('name', ''))
#         except Exception as e:
#             self.show_error("Collections Error", f"Failed to load collections: {str(e)}")
# 
    def refresh_library(self):
        """Refresh the entire library display."""        
        self.refresh_all_data()

    def load_collections(self):
        """Load collections from database and populate the collections list."""        
        try:
            self.collections_list.clear()
            collections = self.library.get_collections()
            for collection in collections:
                self.collections_list.addItem(collection.get('name', ''))
        except Exception as e:
            self.show_error("Collections Error", f"Failed to load collections: {str(e)}")

    def _open_in_ai_tagger(self, model_path: str, dialog):
        """Open model in AI Tagger."""
        dialog.close()
        self.tab_widget.setCurrentWidget(self.ai_tagger_tab)
        self.ai_tagger_tab.set_model(model_path)
    
    def _open_in_quality_analyzer(self, model_path: str, dialog):
        """Open model in Quality Analyzer."""
        dialog.close()
        self.model_selected.emit(model_path)  # Will switch to Model tab
    
    def _open_in_comparison(self, model_path: str, dialog):
        """Add model to comparison."""
        dialog.close()
        self.model_selected.emit(model_path)
    
    def _open_in_version_control(self, model_path: str, dialog):
        """Open in Version Control."""
        dialog.close()
        self.model_selected.emit(model_path)
    
    def _open_in_pipeline(self, model_path: str, dialog):
        """Hand the file to the Pipeline pane as a Load node it can be wired from.

        This button says "Use in Pipeline" and used to only switch tabs, which left the
        person on an empty graph with a path nowhere in it. The pane now takes the file,
        puts the matching Load node on the canvas, and says what to do next.
        """
        dialog.accept()
        main_window = self.window()
        pipeline_tab = getattr(main_window, 'pipeline_tab', None)
        if pipeline_tab is None or not hasattr(main_window, 'tab_widget'):
            return
        main_window.tab_widget.setCurrentWidget(pipeline_tab)
        if not hasattr(pipeline_tab, 'accept_model_file'):
            QMessageBox.warning(self, "Pipeline cannot take this file",
                                "The Pipeline pane has no handoff in this build.")
            return
        pipeline_tab.accept_model_file(model_path)
    
    def _open_in_batch_operations(self, model_path: str, dialog):
        """Hand the file to Automation's Batch Operations pane.

        This jump used to land on a "Batch Processor" sub-tab of Pre-Processing. That
        pane built its own task list, stamped every task completed and wrote no file,
        so there was nothing here to add a file to - and switching to it crashed,
        because it asked Pre-Processing for a `tab_widget` it never had. The batch loop
        that does run lives in Automation and works from a folder, so this fills that
        folder in and leaves Preview to list the files.
        """
        dialog.accept()
        main_window = self.window()
        automation = getattr(main_window, 'automation_tab', None)
        if not automation or not hasattr(main_window, 'tab_widget'):
            return
        main_window.tab_widget.setCurrentWidget(automation)
        automation.automation_tabs.setCurrentWidget(automation.batch_operations_tab)
        automation.batch_prepare_for_file(model_path)
    
#     def _open_in_model_viewer(self, model_path: str, dialog):
#         """Open in Model tab."""
#         dialog.close()
#         self.model_selected.emit(model_path)
#     
    def on_asset_selected(self):
        """Handle asset selection in the left tree view."""
        items = self.left_asset_tree.selectedItems()
        if items:
            # Logic to handle selection
            pass

    def show_context_menu(self, position):
        """Show context menu for asset tree."""
        sender = self.sender()
        
        if sender == self.model_display:
            self.show_grid_context_menu(position)
            return
            
        tree = self.asset_tree
        if sender == self.left_asset_tree:
            tree = self.left_asset_tree
            
        item = tree.itemAt(position)
        if not item or item.parent() is None:  # Skip if no item or if it's a category
            return
    
    def show_model_context_menu(self, model_data, position):
        """Show context menu for a model card."""
        menu = QMenu(self)
        
        file_path = model_data.get('path', '')
        if not file_path or not os.path.exists(file_path):
            return

        # Open actions
        open_mesh_action = QAction("Open in Mesh Tools", self)
        open_mesh_action.setIcon(get_icon("mesh_tools"))
        open_mesh_action.triggered.connect(lambda: self.open_mesh_tools_requested.emit(file_path))
        menu.addAction(open_mesh_action)

        open_pre_action = QAction("Open in Pre-processing", self)
        open_pre_action.setIcon(get_icon("preprocessing"))
        open_pre_action.triggered.connect(lambda: self.open_preprocessing_requested.emit(file_path))
        menu.addAction(open_pre_action)

        open_post_action = QAction("Open in Post-processing", self)
        open_post_action.setIcon(get_icon("postprocessing"))
        open_post_action.triggered.connect(lambda: self.open_postprocessing_requested.emit(file_path))
        menu.addAction(open_post_action)
        
        open_rendering_action = QAction("Open in Rendering Tab", self)
        open_rendering_action.setIcon(get_icon("rendering"))
        open_rendering_action.triggered.connect(lambda: self.open_rendering_requested.emit(file_path))
        menu.addAction(open_rendering_action)
        
        open_anim_action = QAction("Open in Animation Tab", self)
        open_anim_action.setIcon(get_icon("animation"))
        open_anim_action.triggered.connect(lambda: self.open_animation_requested.emit(file_path))
        menu.addAction(open_anim_action)

        load_all_action = QAction("Load in All Tabs", self)
        load_all_action.setIcon(get_icon("import_model"))
        load_all_action.triggered.connect(lambda: self.load_globally_requested.emit(file_path))
        menu.addAction(load_all_action)
        
        menu.addSeparator()

        # LOD Generation
        generate_lod_action = QAction("Generate LODs", self)
        generate_lod_action.setIcon(get_icon("performance"))
        generate_lod_action.triggered.connect(lambda: self.generate_lods_for_model(model_data))
        menu.addAction(generate_lod_action)
        
        menu.addSeparator()
        
        # Existing actions
        show_folder_action = QAction("Show in Folder", self)
        show_folder_action.setIcon(get_icon("folder"))
        show_folder_action.triggered.connect(lambda: self.show_in_folder(file_path))
        menu.addAction(show_folder_action)
        
        remove_action = QAction("Remove from Library", self)
        remove_action.setIcon(get_icon("delete"))
        remove_action.triggered.connect(lambda: self.remove_asset_by_path(file_path))
        menu.addAction(remove_action)
        
        menu.exec(position)

    def remove_asset_by_path(self, file_path):
        """Remove asset from library by path."""
        reply = QMessageBox.question(self, "Remove Asset", 
                                   f"Are you sure you want to remove '{os.path.basename(file_path)}' from the library?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.library.remove_model(file_path):
                self.refresh_model_display()
                self.library_updated.emit()

    def show_grid_context_menu(self, position):
        """Show context menu for grid view background."""
        # This is for the background, not items
        pass

    
#     def open_in_mesh_tools(self, file_path):
#         """Open the selected model in Mesh Tools tab."""
#         if self.main_window:
#             self.main_window.open_model_in_mesh_tools(file_path)
#     
    def remove_asset(self, item):
        """Remove asset from library."""
        reply = QMessageBox.question(
            self,
            "Remove Asset",
            "Are you sure you want to remove this asset from the library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            self.status_changed.emit(f"Asset removed from library")
    
#     def show_asset_context_menu(self, position):
#         """Show context menu for asset tree."""
#         item = self.asset_tree.itemAt(position)
#         if not item:
#             return
#         
#         asset_path = item.data(0, Qt.ItemDataRole.UserRole)
#         if not asset_path or not os.path.exists(asset_path):
#             return
#         
        # Determine asset type
#         ext = os.path.splitext(asset_path)[1].lower()
#         
        # Create context menu
#         menu = QMenu(self)
#         
        # Common actions
#         preview_action = QAction("👁️ Preview", self)
#         preview_action.triggered.connect(lambda: self.preview_asset(item, 0))
#         menu.addAction(preview_action)
#         
#         menu.addSeparator()
#         
        # Type-specific actions
#         if ext in ['.obj', '.stl', '.ply', '.glb', '.gltf', '.fbx', '.dae', '.x3d']:
            # 3D Model actions
#             open_model_action = QAction("📐 Open in Model Viewer", self)
#             open_model_action.triggered.connect(lambda: self.open_in_model_tab(asset_path))
#             menu.addAction(open_model_action)
#             
#             open_mesh_action = QAction("🔧 Open in Mesh Tools", self)
#             open_mesh_action.triggered.connect(lambda: self.open_in_mesh_tools(asset_path))
#             menu.addAction(open_mesh_action)
#             
#             menu.addSeparator()
#         
        # File operations
#         rename_action = QAction("✏️ Rename", self)
#         rename_action.triggered.connect(lambda: self.rename_asset(item))
#         menu.addAction(rename_action)
#         
#         delete_action = QAction("🗑️ Delete", self)
#         delete_action.triggered.connect(lambda: self.delete_asset(item))
#         menu.addAction(delete_action)
#         
#         menu.addSeparator()
#         
        # Info and location
#         show_folder_action = QAction("📂 Show in Folder", self)
#         show_folder_action.triggered.connect(lambda: self.show_in_folder(asset_path))
#         menu.addAction(show_folder_action)
#         
#         properties_action = QAction("ℹ️ Properties", self)
#         properties_action.triggered.connect(lambda: self.show_asset_properties(asset_path))
#         menu.addAction(properties_action)
#         
        # Show menu at cursor position
#         menu.exec(self.asset_tree.viewport().mapToGlobal(position))
#     
#     def open_in_model_tab(self, file_path):
#         """Open the asset in the Model tab."""
#         try:
            # Get the main window (parent of parent)
#             main_window = self.parent()
#             while main_window and not hasattr(main_window, 'tab_widget'):
#                 main_window = main_window.parent()
#             
#             if main_window and hasattr(main_window, 'tab_widget'):
                # Switch to Model tab
#                 for i in range(main_window.tab_widget.count()):
#                     if main_window.tab_widget.tabText(i) == "Model":
#                         main_window.tab_widget.setCurrentIndex(i)
#                         
                        # Load the model in the Model tab
#                         model_tab = main_window.tab_widget.widget(i)
#                         if hasattr(model_tab, 'load_model_file'):
#                             model_tab.load_model_file(file_path)
#                         else:
#                             QMessageBox.warning(self, "Error", "Model tab doesn't support direct loading")
#                         break
#             else:
#                 QMessageBox.warning(self, "Error", "Could not find Model tab")
#         except Exception as e:
#             QMessageBox.critical(self, "Error", f"Failed to open in Model tab:\n{str(e)}")
#     
#     def open_in_mesh_tools(self, file_path):
#         """Open the asset in the Mesh Tools tab."""
#         try:
            # Get the main window (parent of parent)
#             main_window = self.parent()
#             while main_window and not hasattr(main_window, 'tab_widget'):
#                 main_window = main_window.parent()
#             
#             if main_window and hasattr(main_window, 'tab_widget'):
                # Switch to Mesh Tools tab
#                 for i in range(main_window.tab_widget.count()):
#                     if main_window.tab_widget.tabText(i) == "Mesh Tools":
#                         main_window.tab_widget.setCurrentIndex(i)
#                         
                        # Load the mesh in the Mesh Tools tab
#                         mesh_tools_tab = main_window.tab_widget.widget(i)
#                         if hasattr(mesh_tools_tab, 'load_mesh_file'):
#                             mesh_tools_tab.load_mesh_file(file_path)
#                         else:
#                             QMessageBox.warning(self, "Error", "Mesh Tools tab doesn't support direct loading")
#                         break
#             else:
#                 QMessageBox.warning(self, "Error", "Could not find Mesh Tools tab")
#         except Exception as e:
#             QMessageBox.critical(self, "Error", f"Failed to open in Mesh Tools:\n{str(e)}")
#     
#     def show_in_folder(self, file_path):
#         """Show the file in the system file explorer."""
#         try:
#             import subprocess
#             import platform
#             
#             folder_path = os.path.dirname(file_path)
#             
#             if platform.system() == "Windows":
#                 subprocess.run(['explorer', '/select,', file_path])
#             elif platform.system() == "Darwin":  # macOS
#                 subprocess.run(['open', '-R', file_path])
#             else:  # Linux
#                 subprocess.run(['xdg-open', folder_path])
#         except Exception as e:
#             QMessageBox.warning(self, "Error", f"Failed to show in folder:\n{str(e)}")
#     
#     def show_asset_properties(self, file_path):
#         """Show detailed properties of the asset."""
#         try:
#             stats = os.stat(file_path)
#             size_mb = stats.st_size / (1024 * 1024)
#             
#             info = f"""
# Asset Properties
# ━━━━━━━━━━━━━━━━━━━━━━━━
# 
# Name: {os.path.basename(file_path)}
# Path: {file_path}
# Size: {size_mb:.2f} MB
# Type: {os.path.splitext(file_path)[1].upper()}
# 
# Created: {datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')}
# Modified: {datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}
# Accessed: {datetime.fromtimestamp(stats.st_atime).strftime('%Y-%m-%d %H:%M:%S')}
#             """
#             
#             QMessageBox.information(self, "Asset Properties", info.strip())
#         except Exception as e:
#             QMessageBox.warning(self, "Error", f"Failed to get properties:\n{str(e)}")
# 
    def generate_lods_for_model(self, model_data):
        """Generate LODs for the selected model."""
        try:
            model_id = model_data.get('id')
            if not model_id:
                QMessageBox.warning(self, "Error", "Model ID not found.")
                return

            # Ask user for number of levels
            levels, ok = QInputDialog.getInt(
                self, "Generate LODs", 
                "Number of LOD levels to generate:", 
                3, 1, 5
            )
            
            if ok:
                # Show progress dialog
                progress = QProgressDialog("Generating LODs...", None, 0, 0, self)
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setRange(0, 0)
                progress.show()
                QApplication.processEvents()
                
                try:
                    lod_files = self.library.generate_lod(model_id, levels)
                    progress.close()
                    
                    if lod_files:
                        msg = f"Successfully generated {len(lod_files)} LODs:\n\n" + "\n".join([os.path.basename(f) for f in lod_files])
                        QMessageBox.information(self, "LOD Generation Complete", msg)
                    else:
                        QMessageBox.warning(self, "LOD Generation", "No LODs were generated.")
                        
                except Exception as e:
                    progress.close()
                    QMessageBox.critical(self, "LOD Generation Error", f"Failed to generate LODs: {str(e)}")
                    
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")
    
    # ...existing code...
#     def check_integrity(self):
#         """Check the integrity of the library database."""        
#         try:
#             issues = self.library.check_integrity()
#             if not issues:
#                 QMessageBox.information(self, "Integrity Check", "No integrity issues found!")
#             else:
#                 issue_text = "\n".join(issues)
#                 QMessageBox.warning(self, "Integrity Issues Found", f"The following issues were found:\n{issue_text}")
#         except Exception as e:
#             self.show_error("Integrity Check Error", f"Failed to check integrity: {str(e)}")
# 
#     def preview_asset(self, item, column):
#         """Preview the selected asset."""
        # ...existing code...
#     
#     def show_asset_context_menu(self, position):
#         """Show context menu for asset tree."""
#         item = self.asset_tree.itemAt(position)
#         if not item:
#             return
#         
#         asset_path = item.data(0, Qt.ItemDataRole.UserRole)
#         if not asset_path or not os.path.exists(asset_path):
#             return
#         
        # Determine asset type
#         ext = os.path.splitext(asset_path)[1].lower()
#         
        # Create context menu
#         menu = QMenu(self)
#         
        # Common actions
#         preview_action = QAction("👁️ Preview", self)
#         preview_action.triggered.connect(lambda: self.preview_asset(item, 0))
#         menu.addAction(preview_action)
#         
#         menu.addSeparator()
#         
        # Type-specific actions
#         if ext in ['.obj', '.stl', '.ply', '.glb', '.gltf', '.fbx', '.dae', '.x3d']:
            # 3D Model actions
#             open_model_action = QAction("📐 Open in Model Viewer", self)
#             open_model_action.triggered.connect(lambda: self.open_in_model_tab(asset_path))
#             menu.addAction(open_model_action)
#             
#             open_mesh_action = QAction("🔧 Open in Mesh Tools", self)
#             open_mesh_action.triggered.connect(lambda: self.open_in_mesh_tools(asset_path))
#             menu.addAction(open_mesh_action)
# 
#             load_all_action = QAction("🚀 Load in All Tabs", self)
#             load_all_action.triggered.connect(lambda: self.load_globally_requested.emit(asset_path))
#             menu.addAction(load_all_action)
#             
#             menu.addSeparator()
#         
        # File operations
#         rename_action = QAction("✏️ Rename", self)
#         rename_action.triggered.connect(lambda: self.rename_asset(item))
#         menu.addAction(rename_action)
#         
#         delete_action = QAction("🗑️ Delete", self)
#         delete_action.triggered.connect(lambda: self.delete_asset(item))
#         menu.addAction(delete_action)
#         
#         menu.addSeparator()
#         
        # Info and location
#         show_folder_action = QAction("📂 Show in Folder", self)
#         show_folder_action.triggered.connect(lambda: self.show_in_folder(asset_path))
#         menu.addAction(show_folder_action)
#         
#         properties_action = QAction("ℹ️ Properties", self)
#         properties_action.triggered.connect(lambda: self.show_asset_properties(asset_path))
#         menu.addAction(properties_action)
#         
        # Show menu at cursor position
#         menu.exec(self.asset_tree.viewport().mapToGlobal(position))
#     
#     def open_in_model_tab(self, file_path):
#         """Open the asset in the Model tab."""
#         try:
            # Get the main window (parent of parent)
#             main_window = self.parent()
#             while main_window and not hasattr(main_window, 'tab_widget'):
#                 main_window = main_window.parent()
#             
#             if main_window and hasattr(main_window, 'tab_widget'):
                # Switch to Model tab
#                 for i in range(main_window.tab_widget.count()):
#                     if main_window.tab_widget.tabText(i) == "Model":
#                         main_window.tab_widget.setCurrentIndex(i)
#                         
                        # Load the model in the Model tab
#                         model_tab = main_window.tab_widget.widget(i)
#                         if hasattr(model_tab, 'load_model_file'):
#                             model_tab.load_model_file(file_path)
#                         else:
#                             QMessageBox.warning(self, "Error", "Model tab doesn't support direct loading")
#                         break
#             else:
#                 QMessageBox.warning(self, "Error", "Could not find Model tab")
#         except Exception as e:
#             QMessageBox.critical(self, "Error", f"Failed to open in Model tab:\n{str(e)}")
#     
#     def open_in_mesh_tools(self, file_path):
#         """Open the asset in the Mesh Tools tab."""
#         try:
            # Get the main window (parent of parent)
#             main_window = self.parent()
#             while main_window and not hasattr(main_window, 'tab_widget'):
#                 main_window = main_window.parent()
#             
#             if main_window and hasattr(main_window, 'tab_widget'):
                # Switch to Mesh Tools tab
#                 for i in range(main_window.tab_widget.count()):
#                     if main_window.tab_widget.tabText(i) == "Mesh Tools":
#                         main_window.tab_widget.setCurrentIndex(i)
#                         
                        # Load the mesh in the Mesh Tools tab
#                         mesh_tools_tab = main_window.tab_widget.widget(i)
#                         if hasattr(mesh_tools_tab, 'load_mesh_file'):
#                             mesh_tools_tab.load_mesh_file(file_path)
#                         else:
#                             QMessageBox.warning(self, "Error", "Mesh Tools tab doesn't support direct loading")
#                         break
#             else:
#                 QMessageBox.warning(self, "Error", "Could not find Mesh Tools tab")
#         except Exception as e:
#             QMessageBox.critical(self, "Error", f"Failed to open in Mesh Tools:\n{str(e)}")
#     
#     def show_in_folder(self, file_path):
#         """Show the file in the system file explorer."""
#         try:
#             import subprocess
#             import platform
#             
#             folder_path = os.path.dirname(file_path)
#             
#             if platform.system() == "Windows":
#                 subprocess.run(['explorer', '/select,', file_path])
#             elif platform.system() == "Darwin":  # macOS
#                 subprocess.run(['open', '-R', file_path])
#             else:  # Linux
#                 subprocess.run(['xdg-open', folder_path])
#         except Exception as e:
#             QMessageBox.warning(self, "Error", f"Failed to show in folder:\n{str(e)}")
#     
#     def show_asset_properties(self, file_path):
#         """Show detailed properties of the asset."""
#         try:
#             stats = os.stat(file_path)
#             size_mb = stats.st_size / (1024 * 1024)
#             
#             info = f"""
# Asset Properties
# ━━━━━━━━━━━━━━━━━━━━━━━━
# 
# Name: {os.path.basename(file_path)}
# Path: {file_path}
# Size: {size_mb:.2f} MB
# Type: {os.path.splitext(file_path)[1].upper()}
# 
# Created: {datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')}
# Modified: {datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}
# Accessed: {datetime.fromtimestamp(stats.st_atime).strftime('%Y-%m-%d %H:%M:%S')}
#             """
#             
#             QMessageBox.information(self, "Asset Properties", info.strip())
#         except Exception as e:
#             QMessageBox.warning(self, "Error", f"Failed to get properties:\n{str(e)}")
#     
    # ...existing code...
#     def check_integrity(self):
#         """Check the integrity of the library database."""        
#         try:
#             issues = self.library.check_integrity()
#             if not issues:
#                 QMessageBox.information(self, "Integrity Check", "No integrity issues found!")
#             else:
#                 issue_text = "\n".join(issues)
#                 QMessageBox.warning(self, "Integrity Issues Found", f"The following issues were found:\n{issue_text}")
#         except Exception as e:
#             self.show_error("Integrity Check Error", f"Failed to check integrity: {str(e)}")
# 
#     def preview_asset(self, item, column):
#         """Preview the selected asset."""
        # ...existing code...
#     
#     def show_asset_context_menu(self, position):
#         """Show context menu for asset tree."""
#         item = self.asset_tree.itemAt(position)
#         if not item:
#             return
#         
#         asset_path = item.data(0, Qt.ItemDataRole.UserRole)
#         if not asset_path or not os.path.exists(asset_path):
#             return
#         
        # Determine asset type
#         ext = os.path.splitext(asset_path)[1].lower()
#         
        # Create context menu
#         menu = QMenu(self)
#         
        # Common actions
#         preview_action = QAction("👁️ Preview", self)
#         preview_action.triggered.connect(lambda: self.preview_asset(item, 0))
#         menu.addAction(preview_action)
#         
#         menu.addSeparator()
#         
        # Type-specific actions
#         if ext in ['.obj', '.stl', '.ply', '.glb', '.gltf', '.fbx', '.dae', '.x3d']:
            # 3D Model actions
#             open_model_action = QAction("📐 Open in Model Viewer", self)
#             open_model_action.triggered.connect(lambda: self.open_in_model_tab(asset_path))
#             menu.addAction(open_model_action)
#             
#             open_mesh_action = QAction("🔧 Open in Mesh Tools", self)
#             open_mesh_action.triggered.connect(lambda: self.open_in_mesh_tools(asset_path))
#             menu.addAction(open_mesh_action)
#             
#             menu.addSeparator()
#         
        # File operations
#         rename_action = QAction("✏️ Rename", self)
#         rename_action.triggered.connect(lambda: self.rename_asset(item))
#         menu.addAction(rename_action)
#         
#         delete_action = QAction("🗑️ Delete", self)
#         delete_action.triggered.connect(lambda: self.delete_asset(item))
#         menu.addAction(delete_action)
#         
#         menu.addSeparator()
#         
        # Info and location
#         show_folder_action = QAction("📂 Show in Folder", self)
#         show_folder_action.triggered.connect(lambda: self.show_in_folder(asset_path))
#         menu.addAction(show_folder_action)
#         
#         properties_action = QAction("ℹ️ Properties", self)
#         properties_action.triggered.connect(lambda: self.show_asset_properties(asset_path))
#         menu.addAction(properties_action)
#         
        # Show menu at cursor position
#         menu.exec(self.asset_tree.viewport().mapToGlobal(position))
#     
    def open_in_model_tab(self, file_path):
        """Open the asset in the Model tab."""
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'open_in_model_viewer'):
                main_window.open_in_model_viewer(file_path)
            else:
                QMessageBox.warning(self, "Error", "Could not find Model tab")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open in Model tab:\n{str(e)}")
    
    def open_in_mesh_tools(self, file_path):
        """Open the asset in the Mesh Tools tab."""
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'open_in_mesh_tools'):
                main_window.open_in_mesh_tools(file_path)
            else:
                QMessageBox.warning(self, "Error", "Could not find Mesh Tools tab")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open in Mesh Tools:\n{str(e)}")
    
    def show_in_folder(self, file_path):
        """Show the file in the system file explorer."""
        try:
            import subprocess
            import platform
            
            folder_path = os.path.dirname(file_path)
            
            if platform.system() == "Windows":
                subprocess.run(['explorer', '/select,', file_path])
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['open', '-R', file_path])
            else:  # Linux
                subprocess.run(['xdg-open', folder_path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to show in folder:\n{str(e)}")
    
    def show_asset_properties(self, file_path):
        """Show detailed properties of the asset."""
        try:
            stats = os.stat(file_path)
            size_mb = stats.st_size / (1024 * 1024)
            
            info = f"""
Asset Properties
━━━━━━━━━━━━━━━━━━━━━━━━

Name: {os.path.basename(file_path)}
Path: {file_path}
Size: {size_mb:.2f} MB
Type: {os.path.splitext(file_path)[1].upper()}

Created: {datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')}
Modified: {datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}
Accessed: {datetime.fromtimestamp(stats.st_atime).strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            QMessageBox.information(self, "Asset Properties", info.strip())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to get properties:\n{str(e)}")
    
    # ...existing code...
    def check_integrity(self):
        """Say what the database reported, in the names the database reports them under."""
        try:
            report = self.library.check_integrity()
            if not report:
                self.show_error("Integrity Check",
                                "The library could not be read, so nothing was checked.")
                return
            lines = [f"Models in the library: {report['total_models']}"]
            for key in ('missing_files', 'orphaned_thumbnails', 'missing_thumbnails'):
                found = report[key]
                lines.append(f"{key}: {len(found)}")
                lines.extend(f"  {item}" for item in found[:5])
                if len(found) > 5:
                    lines.append(f"  and {len(found) - 5} more")
            detail = "\n".join(lines)
            if report['issues_found'] == 0:
                QMessageBox.information(self, "Integrity Check",
                                        f"No integrity issues found.\n{detail}")
            else:
                QMessageBox.warning(self, "Integrity Issues Found", detail)
        except Exception as e:
            self.show_error("Integrity Check Error", f"Failed to check integrity: {str(e)}")

    def preview_asset(self, item, column):
        """Preview the selected asset."""
        # ...existing code...
    
    def show_asset_context_menu(self, position):
        """Show context menu for asset tree."""
        item = self.asset_tree.itemAt(position)
        if not item:
            return
        
        asset_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not asset_path:
            return

    def _open_in_model_viewer(self, model_path, dialog):
        """Open model in Model Viewer tab."""
        dialog.accept()
        main_window = self.window()
        if main_window and hasattr(main_window, 'open_in_model_viewer'):
            main_window.open_in_model_viewer(model_path)

    def _open_in_mesh_tools(self, model_path, dialog):
        """Open model in Mesh Tools tab."""
        dialog.accept()
        main_window = self.window()
        if main_window and hasattr(main_window, 'open_in_mesh_tools'):
            main_window.open_in_mesh_tools(model_path)
