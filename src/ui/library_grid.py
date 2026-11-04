"""
Advanced model library grid widget with thumbnail support, filtering, and smart collections.
This is the main grid view for the Library Tab.
"""

import os
import json
from typing import List, Dict, Any, Optional, Set
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
                             QGridLayout, QLabel, QPushButton, QFrame, QMenu,
                             QProgressBar, QCheckBox, QSpinBox, QComboBox,
                             QLineEdit, QGroupBox, QSplitter, QListWidget,
                             QListWidgetItem, QMessageBox, QInputDialog)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread, QObject
from PyQt6.QtGui import QPixmap, QAction, QFont, QPalette, QColor

from ..core.thumbnail_generator import ThumbnailGenerator
from ..core.library_manager import LibraryManager

class ModelItemWidget(QFrame):
    """Individual model item widget with thumbnail and metadata."""
    
    item_clicked = pyqtSignal(str)  # file_path
    item_double_clicked = pyqtSignal(str)
    item_right_clicked = pyqtSignal(str, object)  # file_path, position
    selection_changed = pyqtSignal(str, bool)  # file_path, selected
    
    def __init__(self, file_path: str, metadata: Dict[str, Any] = None):
        super().__init__()
        self.file_path = file_path
        self.metadata = metadata or {}
        self.is_selected = False
        self.thumbnail_requested = False
        
        self.setup_ui()
        self.setup_style()
    
    def setup_ui(self):
        """Setup the UI for the model item."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # Thumbnail area
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(128, 128)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                border: 2px solid #444444;
                background-color: #2a2a2a;
                border-radius: 4px;
            }
        """)
        self.thumbnail_label.setText("Loading...")
        layout.addWidget(self.thumbnail_label)
        
        # Progress bar for thumbnail generation
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(4)
        layout.addWidget(self.progress_bar)
        
        # File name
        filename = os.path.basename(self.file_path)
        self.name_label = QLabel(filename)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(40)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        self.name_label.setFont(font)
        layout.addWidget(self.name_label)
        
        # Metadata info
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setMaximumHeight(60)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(8)
        self.info_label.setFont(font)
        self.update_info_display()
        layout.addWidget(self.info_label)
        
        # Selection checkbox
        self.selection_checkbox = QCheckBox()
        self.selection_checkbox.setVisible(False)
        self.selection_checkbox.toggled.connect(self.on_selection_toggled)
        layout.addWidget(self.selection_checkbox)
    
    def setup_style(self):
        """Setup the visual style."""
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.update_selection_style()
    
    def update_info_display(self):
        """Update the metadata info display."""
        info_parts = []
        
        if 'format' in self.metadata:
            info_parts.append(f"Format: {self.metadata['format'].upper()}")
        
        if 'vertices' in self.metadata:
            vertices = self.metadata['vertices']
            if vertices >= 1000000:
                info_parts.append(f"Vertices: {vertices/1000000:.1f}M")
            elif vertices >= 1000:
                info_parts.append(f"Vertices: {vertices/1000:.1f}K")
            else:
                info_parts.append(f"Vertices: {vertices}")
        
        if 'faces' in self.metadata:
            faces = self.metadata['faces']
            if faces >= 1000000:
                info_parts.append(f"Faces: {faces/1000000:.1f}M")
            elif faces >= 1000:
                info_parts.append(f"Faces: {faces/1000:.1f}K")
            else:
                info_parts.append(f"Faces: {faces}")
        
        if 'file_size' in self.metadata:
            size = self.metadata['file_size']
            if size >= 1024*1024:
                info_parts.append(f"Size: {size/(1024*1024):.1f}MB")
            elif size >= 1024:
                info_parts.append(f"Size: {size/1024:.1f}KB")
            else:
                info_parts.append(f"Size: {size}B")
        
        self.info_label.setText("\n".join(info_parts))
    
    def set_thumbnail(self, pixmap: QPixmap):
        """Set the thumbnail image."""
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.thumbnail_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)
        else:
            self.thumbnail_label.setText("No Preview")
        
        self.progress_bar.setVisible(False)
    
    def set_thumbnail_progress(self, progress: int):
        """Update thumbnail generation progress."""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(progress)
    
    def set_thumbnail_error(self, error: str):
        """Handle thumbnail generation error."""
        self.thumbnail_label.setText("Preview\nFailed")
        self.progress_bar.setVisible(False)
    
    def set_selected(self, selected: bool):
        """Set selection state."""
        if self.is_selected != selected:
            self.is_selected = selected
            self.selection_checkbox.setChecked(selected)
            self.update_selection_style()
            self.selection_changed.emit(self.file_path, selected)
    
    def update_selection_style(self):
        """Update visual style based on selection."""
        if self.is_selected:
            self.setStyleSheet("""
                ModelItemWidget {
                    border: 2px solid #0078d4;
                    background-color: #1a1a1a;
                    border-radius: 6px;
                }
            """)
        else:
            self.setStyleSheet("""
                ModelItemWidget {
                    border: 1px solid #444444;
                    background-color: #1e1e1e;
                    border-radius: 4px;
                }
                ModelItemWidget:hover {
                    border: 1px solid #666666;
                    background-color: #252525;
                }
            """)
    
    def set_selection_mode(self, enabled: bool):
        """Show/hide selection checkbox."""
        self.selection_checkbox.setVisible(enabled)
    
    def on_selection_toggled(self, checked: bool):
        """Handle selection checkbox toggle."""
        self.set_selected(checked)
    
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.item_clicked.emit(self.file_path)
        elif event.button() == Qt.MouseButton.RightButton:
            self.item_right_clicked.emit(self.file_path, event.globalPosition().toPoint())
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Handle double-click events."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.item_double_clicked.emit(self.file_path)
        super().mouseDoubleClickEvent(event)

class ModelGridWidget(QScrollArea):
    """Scrollable grid widget for displaying model items."""
    
    item_clicked = pyqtSignal(str)
    item_double_clicked = pyqtSignal(str)
    item_right_clicked = pyqtSignal(str, object)
    selection_changed = pyqtSignal(list)  # list of selected file paths
    
    def __init__(self):
        super().__init__()
        self.model_items = {}  # file_path -> ModelItemWidget
        self.selected_items = set()
        self.selection_mode = False
        self.grid_columns = 5
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the grid UI."""
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Main widget and layout
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        
        self.setWidget(self.grid_widget)
    
    def add_model_item(self, file_path: str, metadata: Dict[str, Any] = None):
        """Add a model item to the grid."""
        if file_path in self.model_items:
            return  # Already exists
        
        item_widget = ModelItemWidget(file_path, metadata)
        item_widget.item_clicked.connect(self.on_item_clicked)
        item_widget.item_double_clicked.connect(self.item_double_clicked)
        item_widget.item_right_clicked.connect(self.item_right_clicked)
        item_widget.selection_changed.connect(self.on_item_selection_changed)
        item_widget.set_selection_mode(self.selection_mode)
        
        # Calculate grid position
        index = len(self.model_items)
        row = index // self.grid_columns
        col = index % self.grid_columns
        
        self.grid_layout.addWidget(item_widget, row, col)
        self.model_items[file_path] = item_widget
    
    def remove_model_item(self, file_path: str):
        """Remove a model item from the grid."""
        if file_path in self.model_items:
            widget = self.model_items[file_path]
            self.grid_layout.removeWidget(widget)
            widget.deleteLater()
            del self.model_items[file_path]
            
            if file_path in self.selected_items:
                self.selected_items.remove(file_path)
            
            self._reorganize_grid()
    
    def clear_grid(self):
        """Clear all items from the grid."""
        for widget in self.model_items.values():
            widget.deleteLater()
        
        self.model_items.clear()
        self.selected_items.clear()
    
    def _reorganize_grid(self):
        """Reorganize grid layout after item removal."""
        items = list(self.model_items.items())
        
        # Remove all widgets from layout
        for _, widget in items:
            self.grid_layout.removeWidget(widget)
        
        # Re-add in correct positions
        for index, (file_path, widget) in enumerate(items):
            row = index // self.grid_columns
            col = index % self.grid_columns
            self.grid_layout.addWidget(widget, row, col)
    
    def set_grid_columns(self, columns: int):
        """Set number of grid columns."""
        if columns != self.grid_columns:
            self.grid_columns = max(1, columns)
            self._reorganize_grid()
    
    def set_selection_mode(self, enabled: bool):
        """Enable/disable selection mode."""
        self.selection_mode = enabled
        for widget in self.model_items.values():
            widget.set_selection_mode(enabled)
    
    def select_all(self):
        """Select all items."""
        for widget in self.model_items.values():
            widget.set_selected(True)
    
    def clear_selection(self):
        """Clear all selections."""
        for widget in self.model_items.values():
            widget.set_selected(False)
    
    def get_selected_items(self) -> List[str]:
        """Get list of selected file paths."""
        return list(self.selected_items)
    
    def set_thumbnail(self, file_path: str, pixmap: QPixmap):
        """Set thumbnail for a specific item."""
        if file_path in self.model_items:
            self.model_items[file_path].set_thumbnail(pixmap)
    
    def set_thumbnail_progress(self, file_path: str, progress: int):
        """Update thumbnail progress for a specific item."""
        if file_path in self.model_items:
            self.model_items[file_path].set_thumbnail_progress(progress)
    
    def set_thumbnail_error(self, file_path: str, error: str):
        """Handle thumbnail error for a specific item."""
        if file_path in self.model_items:
            self.model_items[file_path].set_thumbnail_error(error)
    
    def on_item_clicked(self, file_path: str):
        """Handle item click."""
        if not self.selection_mode:
            # Clear other selections
            for widget in self.model_items.values():
                if widget.file_path != file_path:
                    widget.set_selected(False)
            
            # Select clicked item
            if file_path in self.model_items:
                self.model_items[file_path].set_selected(True)
        
        self.item_clicked.emit(file_path)
    
    def on_item_selection_changed(self, file_path: str, selected: bool):
        """Handle item selection change."""
        if selected:
            self.selected_items.add(file_path)
        else:
            self.selected_items.discard(file_path)
        
        self.selection_changed.emit(list(self.selected_items))

class FilterWidget(QGroupBox):
    """Advanced filtering widget for the model library."""
    
    filters_changed = pyqtSignal(dict)  # filter criteria
    
    def __init__(self):
        super().__init__("Filters")
        self.setup_ui()
        self.connect_signals()
    
    def setup_ui(self):
        """Setup filter UI."""
        layout = QVBoxLayout(self)
        
        # Format filter
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "All Formats", "OBJ", "PLY", "STL", "GLB", "GLTF", 
            "FBX", "DAE", "3MF", "OFF"
        ])
        format_layout.addWidget(self.format_combo)
        layout.addLayout(format_layout)
        
        # Complexity filter
        complexity_layout = QVBoxLayout()
        complexity_layout.addWidget(QLabel("Vertex Count:"))
        
        vertex_range_layout = QHBoxLayout()
        self.min_vertices = QSpinBox()
        self.min_vertices.setMaximum(10000000)
        self.min_vertices.setSuffix(" min")
        vertex_range_layout.addWidget(self.min_vertices)
        
        self.max_vertices = QSpinBox()
        self.max_vertices.setMaximum(10000000)
        self.max_vertices.setValue(10000000)
        self.max_vertices.setSuffix(" max")
        vertex_range_layout.addWidget(self.max_vertices)
        
        complexity_layout.addLayout(vertex_range_layout)
        layout.addLayout(complexity_layout)
        
        # File size filter
        size_layout = QVBoxLayout()
        size_layout.addWidget(QLabel("File Size (MB):"))
        
        size_range_layout = QHBoxLayout()
        self.min_size = QSpinBox()
        self.min_size.setMaximum(10000)
        self.min_size.setSuffix(" MB min")
        size_range_layout.addWidget(self.min_size)
        
        self.max_size = QSpinBox()
        self.max_size.setMaximum(10000)
        self.max_size.setValue(10000)
        self.max_size.setSuffix(" MB max")
        size_range_layout.addWidget(self.max_size)
        
        size_layout.addLayout(size_range_layout)
        layout.addLayout(size_layout)
        
        # Date filter
        date_layout = QVBoxLayout()
        date_layout.addWidget(QLabel("Added:"))
        self.date_combo = QComboBox()
        self.date_combo.addItems([
            "Any Time", "Today", "This Week", "This Month", "This Year"
        ])
        date_layout.addWidget(self.date_combo)
        layout.addLayout(date_layout)
        
        # Reset button
        self.reset_btn = QPushButton("Reset Filters")
        layout.addWidget(self.reset_btn)
    
    def connect_signals(self):
        """Connect filter signals."""
        self.format_combo.currentTextChanged.connect(self.emit_filters)
        self.min_vertices.valueChanged.connect(self.emit_filters)
        self.max_vertices.valueChanged.connect(self.emit_filters)
        self.min_size.valueChanged.connect(self.emit_filters)
        self.max_size.valueChanged.connect(self.emit_filters)
        self.date_combo.currentTextChanged.connect(self.emit_filters)
        self.reset_btn.clicked.connect(self.reset_filters)
    
    def emit_filters(self):
        """Emit current filter criteria."""
        filters = {
            'format': self.format_combo.currentText(),
            'min_vertices': self.min_vertices.value(),
            'max_vertices': self.max_vertices.value(),
            'min_size_mb': self.min_size.value(),
            'max_size_mb': self.max_size.value(),
            'date_range': self.date_combo.currentText()
        }
        self.filters_changed.emit(filters)
    
    def reset_filters(self):
        """Reset all filters to default."""
        self.format_combo.setCurrentText("All Formats")
        self.min_vertices.setValue(0)
        self.max_vertices.setValue(10000000)
        self.min_size.setValue(0)
        self.max_size.setValue(10000)
        self.date_combo.setCurrentText("Any Time")

class CollectionWidget(QGroupBox):
    """Smart collections widget."""
    
    collection_selected = pyqtSignal(str)  # collection name
    collection_created = pyqtSignal(str, dict)  # name, criteria
    collection_deleted = pyqtSignal(str)  # collection name
    
    def __init__(self):
        super().__init__("Collections")
        self.collections = {}  # name -> criteria
        self.setup_ui()
        self.load_collections()
    
    def setup_ui(self):
        """Setup collections UI."""
        layout = QVBoxLayout(self)
        
        # Collection list
        self.collection_list = QListWidget()
        self.collection_list.itemClicked.connect(self.on_collection_clicked)
        layout.addWidget(self.collection_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self.add_collection)
        button_layout.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self.edit_collection)
        button_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_collection)
        button_layout.addWidget(self.delete_btn)
        
        layout.addLayout(button_layout)
        
        # Add default collections
        self.add_default_collections()
    
    def add_default_collections(self):
        """Add default smart collections."""
        default_collections = {
            "All Models": {},
            "High Poly (>100K vertices)": {"min_vertices": 100000},
            "Low Poly (<10K vertices)": {"max_vertices": 10000},
            "Large Files (>10MB)": {"min_size_mb": 10},
            "Recent Models": {"date_range": "This Week"},
            "OBJ Files": {"format": "OBJ"},
            "STL Files": {"format": "STL"}
        }
        
        for name, criteria in default_collections.items():
            self.add_collection_item(name, criteria, is_default=True)
    
    def add_collection_item(self, name: str, criteria: dict, is_default: bool = False):
        """Add collection to the list."""
        self.collections[name] = criteria
        
        item = QListWidgetItem(name)
        if is_default:
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
        
        self.collection_list.addItem(item)
    
    def on_collection_clicked(self, item: QListWidgetItem):
        """Handle collection selection."""
        collection_name = item.text()
        self.collection_selected.emit(collection_name)
    
    def add_collection(self):
        """Add new collection."""
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        if ok and name:
            if name not in self.collections:
                # For now, create empty collection - could open criteria dialog
                self.add_collection_item(name, {})
                self.collection_created.emit(name, {})
                self.save_collections()
    
    def edit_collection(self):
        """Edit selected collection."""
        current_item = self.collection_list.currentItem()
        if current_item:
            # Could open criteria editor dialog
            pass
    
    def delete_collection(self):
        """Delete selected collection."""
        current_item = self.collection_list.currentItem()
        if current_item:
            name = current_item.text()
            if name not in ["All Models"]:  # Don't delete default collections
                reply = QMessageBox.question(
                    self, "Delete Collection",
                    f"Delete collection '{name}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    row = self.collection_list.row(current_item)
                    self.collection_list.takeItem(row)
                    del self.collections[name]
                    self.collection_deleted.emit(name)
                    self.save_collections()
    
    def get_collection_criteria(self, name: str) -> dict:
        """Get criteria for a collection."""
        return self.collections.get(name, {})
    
    def save_collections(self):
        """Save collections to file."""
        try:
            config_dir = os.path.join(os.path.expanduser("~"), ".renderfox")
            os.makedirs(config_dir, exist_ok=True)
            
            collections_file = os.path.join(config_dir, "collections.json")
            with open(collections_file, 'w') as f:
                json.dump(self.collections, f, indent=2)
        except Exception as e:
            print(f"Failed to save collections: {e}")
    
    def load_collections(self):
        """Load collections from file."""
        try:
            config_dir = os.path.join(os.path.expanduser("~"), ".renderfox")
            collections_file = os.path.join(config_dir, "collections.json")
            
            if os.path.exists(collections_file):
                with open(collections_file, 'r') as f:
                    saved_collections = json.load(f)
                
                for name, criteria in saved_collections.items():
                    if name not in self.collections:  # Don't override defaults
                        self.add_collection_item(name, criteria)
        except Exception as e:
            print(f"Failed to load collections: {e}")

class LibraryGridWidget(QWidget):
    """Main library grid widget combining all components."""
    
    model_selected = pyqtSignal(str)  # file_path
    model_opened = pyqtSignal(str)    # file_path
    
    def __init__(self, library_manager: LibraryManager):
        super().__init__()
        self.library_manager = library_manager
        self.thumbnail_generator = ThumbnailGenerator()
        self.current_models = []  # Current filtered list
        self.setup_ui()
        self.connect_signals()
        self.load_initial_models()
    
    def setup_ui(self):
        """Setup the main UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Left sidebar with filters and collections
        sidebar = QWidget()
        sidebar.setMaximumWidth(300)
        sidebar_layout = QVBoxLayout(sidebar)
        
        # Collections
        self.collection_widget = CollectionWidget()
        sidebar_layout.addWidget(self.collection_widget)
        
        # Filters
        self.filter_widget = FilterWidget()
        sidebar_layout.addWidget(self.filter_widget)
        
        sidebar_layout.addStretch()
        
        # Main content area
        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        
        # Toolbar
        toolbar_layout = QHBoxLayout()
        
        # Grid size control
        toolbar_layout.addWidget(QLabel("Grid Size:"))
        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(2, 10)
        self.grid_size_spin.setValue(5)
        self.grid_size_spin.valueChanged.connect(self.on_grid_size_changed)
        toolbar_layout.addWidget(self.grid_size_spin)
        
        toolbar_layout.addStretch()
        
        # Selection controls
        self.selection_btn = QPushButton("Select Mode")
        self.selection_btn.setCheckable(True)
        self.selection_btn.toggled.connect(self.on_selection_mode_toggled)
        toolbar_layout.addWidget(self.selection_btn)
        
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.model_grid.select_all)
        self.select_all_btn.setVisible(False)
        toolbar_layout.addWidget(self.select_all_btn)
        
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self.model_grid.clear_selection)
        self.clear_selection_btn.setVisible(False)
        toolbar_layout.addWidget(self.clear_selection_btn)
        
        main_layout.addLayout(toolbar_layout)
        
        # Model grid
        self.model_grid = ModelGridWidget()
        main_layout.addWidget(self.model_grid)
        
        # Status bar
        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)
        
        # Create splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(main_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
    
    def connect_signals(self):
        """Connect all signals."""
        # Grid signals
        self.model_grid.item_clicked.connect(self.model_selected)
        self.model_grid.item_double_clicked.connect(self.model_opened)
        self.model_grid.selection_changed.connect(self.on_selection_changed)
        
        # Filter signals
        self.filter_widget.filters_changed.connect(self.apply_filters)
        
        # Collection signals
        self.collection_widget.collection_selected.connect(self.apply_collection)
        
        # Thumbnail signals
        self.thumbnail_generator.thumbnail_ready.connect(self.model_grid.set_thumbnail)
        self.thumbnail_generator.progress_updated.connect(self.model_grid.set_thumbnail_progress)
        self.thumbnail_generator.generation_failed.connect(self.model_grid.set_thumbnail_error)
    
    def load_initial_models(self):
        """Load initial model list."""
        try:
            models = self.library_manager.get_all_models()
            self.display_models(models)
            self.status_label.setText(f"Loaded {len(models)} models")
        except Exception as e:
            self.status_label.setText(f"Error loading models: {e}")
    
    def display_models(self, models: List[Dict[str, Any]]):
        """Display models in the grid."""
        self.model_grid.clear_grid()
        self.current_models = models
        
        for model in models:
            file_path = model['file_path']
            self.model_grid.add_model_item(file_path, model)
            
            # Request thumbnail
            self.thumbnail_generator.generate_thumbnail(file_path)
    
    def apply_filters(self, filters: dict):
        """Apply filters to model list."""
        # Get base model list from current collection or all models
        base_models = self.current_models
        
        filtered_models = []
        for model in base_models:
            if self._model_matches_filters(model, filters):
                filtered_models.append(model)
        
        self.display_models(filtered_models)
        self.status_label.setText(f"Showing {len(filtered_models)} of {len(base_models)} models")
    
    def apply_collection(self, collection_name: str):
        """Apply collection filter."""
        criteria = self.collection_widget.get_collection_criteria(collection_name)
        
        if collection_name == "All Models":
            models = self.library_manager.get_all_models()
        else:
            models = self.library_manager.get_all_models()
            filtered_models = []
            for model in models:
                if self._model_matches_filters(model, criteria):
                    filtered_models.append(model)
            models = filtered_models
        
        self.display_models(models)
        self.status_label.setText(f"Collection: {collection_name} ({len(models)} models)")
    
    def _model_matches_filters(self, model: Dict[str, Any], filters: dict) -> bool:
        """Check if model matches filter criteria."""
        # Format filter
        if filters.get('format') and filters['format'] != "All Formats":
            model_format = model.get('format', '').upper()
            if model_format != filters['format'].upper():
                return False
        
        # Vertex count filter
        vertices = model.get('vertices', 0)
        if vertices < filters.get('min_vertices', 0):
            return False
        if vertices > filters.get('max_vertices', float('inf')):
            return False
        
        # File size filter
        size_mb = model.get('file_size', 0) / (1024 * 1024)
        if size_mb < filters.get('min_size_mb', 0):
            return False
        if size_mb > filters.get('max_size_mb', float('inf')):
            return False
        
        # Date filter would require implementation
        
        return True
    
    def on_grid_size_changed(self, columns: int):
        """Handle grid size change."""
        self.model_grid.set_grid_columns(columns)
    
    def on_selection_mode_toggled(self, enabled: bool):
        """Handle selection mode toggle."""
        self.model_grid.set_selection_mode(enabled)
        self.select_all_btn.setVisible(enabled)
        self.clear_selection_btn.setVisible(enabled)
    
    def on_selection_changed(self, selected_paths: List[str]):
        """Handle selection change."""
        count = len(selected_paths)
        if count > 0:
            self.status_label.setText(f"{count} models selected")
        else:
            self.status_label.setText("Ready")
    
    def refresh_library(self):
        """Refresh the entire library."""
        self.library_manager.scan_library()
        self.load_initial_models()
    
    def get_selected_models(self) -> List[str]:
        """Get currently selected model paths."""
        return self.model_grid.get_selected_items()