"""
AI Asset Tagger UI - Smart Tagging & Natural Language Search Interface

This UI provides an intuitive interface for AI-powered asset tagging,
natural language search, and intelligent tag suggestions.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                             QGroupBox, QComboBox, QCheckBox, QProgressBar,
                             QSplitter, QFrame, QTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QMenu, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from src.core.worker_base import SafeWorker
from PyQt6.QtGui import QFont, QColor, QAction
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                             QGroupBox, QComboBox, QCheckBox, QProgressBar,
                             QSplitter, QFrame, QTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QMenu, QScrollArea,
                             QFileDialog, QMessageBox)

from ..features.ai_asset_tagger import AIAssetTagger
from ..utils.run_teardown import drain_attributes, shutdown
from .icon_provider import get_icon

logger = logging.getLogger(__name__)


class TaggingWorker(SafeWorker):
    """Background worker for AI tagging."""
    finished = pyqtSignal(dict)  # Changed to dict to include full analysis
    progress = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, model_path: str, tagger: AIAssetTagger):
        super().__init__()
        self.model_path = model_path
        self.tagger = tagger
    
    def safe_run(self):
        self.progress.emit("Analyzing model geometry...")
        
        # Call analyze_model which returns full analysis including tags
        analysis = self.tagger.analyze_model(self.model_path)
        
        if 'error' in analysis:
            self.error.emit(analysis['error'])
        else:
            self.finished.emit(analysis)


class BulkTaggingWorker(SafeWorker):
    """Background worker for bulk tagging operations."""
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, model_paths: List[str], tagger: AIAssetTagger):
        super().__init__()
        self.model_paths = model_paths
        self.tagger = tagger
    
    def safe_run(self):
        total = len(self.model_paths)
        for i, model_path in enumerate(self.model_paths, 1):
            self.progress.emit(i, total, Path(model_path).name)
            self.tagger.generate_tags(model_path)
        self.finished.emit()


class AIAssetTaggerUI(QWidget):
    """
    AI Asset Tagger UI Component.
    
    Features:
    - Natural language search ("find all medieval weapons")
    - Automatic tag generation based on geometry
    - Smart tag suggestions
    - Tag management (add, remove, bulk edit)
    - Tag cloud visualization
    - Search history
    """
    
    tags_updated = pyqtSignal(list)  # Emit when tags change
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tagger = AIAssetTagger()
        self.current_model_path = None
        self.current_tags = []
        self.search_history = []
        self.init_ui()
        
        # Show AI model status
        self._show_ai_status()
    
    def _show_ai_status(self):
        """Show status message about AI model availability."""
        if self.tagger.use_clip:
            logger.info("AI tagging enabled with CLIP model")
        else:
            logger.warning("AI tagging disabled - using geometric analysis only")
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Search and tagging
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Tag management
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
    

    
    def _create_left_panel(self) -> QWidget:
        """Create left panel with search and auto-tagging."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
            # Natural Language Search
        search_group = QGroupBox("Natural Language Search")
        search_layout = QVBoxLayout()
        
        # Search input
        search_input_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Try: 'find all medieval weapons' or 'show organic characters'")
        self.search_input.returnPressed.connect(self.perform_search)
        search_input_layout.addWidget(self.search_input)
        
        search_btn = QPushButton("Search")
        search_btn.setIcon(get_icon("search"))
        search_btn.setProperty("primary", "true")
        search_btn.clicked.connect(self.perform_search)
        search_input_layout.addWidget(search_btn)
        
        search_layout.addLayout(search_input_layout)
        
        # Quick search examples
        examples_label = QLabel("Examples:")
        examples_label.setStyleSheet("color: #8c93a8; font-style: italic; margin-top: 5px;")
        search_layout.addWidget(examples_label)
        
        examples_layout = QHBoxLayout()
        examples = [
            "vehicles",
            "organic models", 
            "low-poly props",
            "architectural"
        ]
        
        for example in examples:
            btn = QPushButton(f"'{example}'")
            btn.clicked.connect(lambda checked, text=example: self.quick_search(text))
            examples_layout.addWidget(btn)
        
        examples_layout.addStretch()
        search_layout.addLayout(examples_layout)
        
        # Search results
        self.search_results = QTextEdit()
        self.search_results.setReadOnly(True)
        self.search_results.setMaximumHeight(150)
        self.search_results.setPlaceholderText("Search results will appear here...")
        search_layout.addWidget(self.search_results)
        
        # Search history
        history_label = QLabel("Recent Searches:")
        history_label.setStyleSheet("color: #8c93a8; margin-top: 5px;")
        search_layout.addWidget(history_label)
        
        self.search_history_list = QListWidget()
        self.search_history_list.setObjectName("search_history_list")
        self.search_history_list.setMaximumHeight(80)
        self.search_history_list.itemDoubleClicked.connect(self.repeat_search)
        search_layout.addWidget(self.search_history_list)
        
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # Auto-Tagging Section
        auto_tag_group = QGroupBox("Automatic Tagging")
        auto_tag_layout = QVBoxLayout()
        
        info_label = QLabel("Generate AI-powered tags based on model geometry and features")
        info_label.setStyleSheet("color: #8c93a8; margin-bottom: 10px;")
        info_label.setWordWrap(True)
        auto_tag_layout.addWidget(info_label)
        
        # Auto-tag button
        self.auto_tag_btn = QPushButton("Generate Tags Automatically")
        self.auto_tag_btn.setIcon(get_icon("sparkles"))
        self.auto_tag_btn.setProperty("primary", "true")
        self.auto_tag_btn.clicked.connect(self.auto_generate_tags)
        self.auto_tag_btn.setEnabled(False)
        auto_tag_layout.addWidget(self.auto_tag_btn)
        
        # Progress bar
        self.tag_progress = QProgressBar()
        self.tag_progress.setVisible(False)
        auto_tag_layout.addWidget(self.tag_progress)
        
        # Suggested tags display
        suggested_label = QLabel("Suggested Tags:")
        suggested_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        auto_tag_layout.addWidget(suggested_label)
        
        self.suggested_tags_list = QListWidget()
        self.suggested_tags_list.setObjectName("suggested_tags_list")
        self.suggested_tags_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.suggested_tags_list.setMaximumHeight(120)
        auto_tag_layout.addWidget(self.suggested_tags_list)
        
        # Add selected tags button
        add_tags_layout = QHBoxLayout()
        self.add_suggested_btn = QPushButton("Add Selected Tags")
        self.add_suggested_btn.setIcon(get_icon("add"))
        self.add_suggested_btn.clicked.connect(self.add_suggested_tags)
        self.add_suggested_btn.setEnabled(False)
        add_tags_layout.addWidget(self.add_suggested_btn)
        
        self.add_all_btn = QPushButton("Add All")
        self.add_all_btn.setIcon(get_icon("add"))
        self.add_all_btn.clicked.connect(self.add_all_suggested_tags)
        self.add_all_btn.setEnabled(False)
        add_tags_layout.addWidget(self.add_all_btn)
        
        auto_tag_layout.addLayout(add_tags_layout)
        
        auto_tag_group.setLayout(auto_tag_layout)
        layout.addWidget(auto_tag_group)
        
        # Bulk Operations
        bulk_group = QGroupBox("Bulk Operations")
        bulk_layout = QVBoxLayout()
        
        bulk_info = QLabel("Apply tags to multiple models at once")
        bulk_info.setStyleSheet("color: #8c93a8;")
        bulk_layout.addWidget(bulk_info)
        
        self.bulk_tag_btn = QPushButton("Bulk Auto-Tag Library")
        self.bulk_tag_btn.setIcon(get_icon("refresh"))
        self.bulk_tag_btn.clicked.connect(self.bulk_auto_tag)
        bulk_layout.addWidget(self.bulk_tag_btn)
        
        self.bulk_progress = QProgressBar()
        self.bulk_progress.setVisible(False)
        bulk_layout.addWidget(self.bulk_progress)
        
        self.bulk_status = QLabel("")
        self.bulk_status.setStyleSheet("color: #8c93a8; font-style: italic;")
        bulk_layout.addWidget(self.bulk_status)
        
        bulk_group.setLayout(bulk_layout)
        layout.addWidget(bulk_group)
        
        layout.addStretch()
        
        scroll_area.setWidget(panel)
        return scroll_area
    
    def _create_right_panel(self) -> QWidget:
        """Create right panel with tag management."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Current Model Tags
        current_tags_group = QGroupBox("Current Model Tags")
        current_tags_layout = QVBoxLayout()
        
        # Tag input
        add_tag_layout = QHBoxLayout()
        self.new_tag_input = QLineEdit()
        self.new_tag_input.setPlaceholderText("Add custom tag...")
        self.new_tag_input.returnPressed.connect(self.add_custom_tag)
        add_tag_layout.addWidget(self.new_tag_input)
        
        add_tag_btn = QPushButton("Add")
        add_tag_btn.setIcon(get_icon("add"))
        add_tag_btn.clicked.connect(self.add_custom_tag)
        add_tag_layout.addWidget(add_tag_btn)
        
        current_tags_layout.addLayout(add_tag_layout)
        
        # Current tags list
        self.current_tags_list = QListWidget()
        self.current_tags_list.setObjectName("current_tags_list")
        self.current_tags_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.current_tags_list.customContextMenuRequested.connect(self.show_tag_context_menu)
        current_tags_layout.addWidget(self.current_tags_list)
        
        # Tag actions
        tag_actions_layout = QHBoxLayout()
        
        self.remove_tag_btn = QPushButton("Remove Selected")
        self.remove_tag_btn.setIcon(get_icon("delete"))
        self.remove_tag_btn.clicked.connect(self.remove_selected_tags)
        tag_actions_layout.addWidget(self.remove_tag_btn)
        
        self.clear_tags_btn = QPushButton("Clear All")
        self.clear_tags_btn.setIcon(get_icon("clean"))
        self.clear_tags_btn.clicked.connect(self.clear_all_tags)
        tag_actions_layout.addWidget(self.clear_tags_btn)
        
        current_tags_layout.addLayout(tag_actions_layout)
        
        current_tags_group.setLayout(current_tags_layout)
        layout.addWidget(current_tags_group)
        
        # Tag Cloud / Popular Tags
        popular_group = QGroupBox("Tag Cloud (Popular Tags)")
        popular_layout = QVBoxLayout()
        
        self.tag_cloud = QListWidget()
        self.tag_cloud.setObjectName("tag_cloud")
        self.tag_cloud.itemDoubleClicked.connect(self.add_popular_tag)
        popular_layout.addWidget(self.tag_cloud)
        
        popular_info = QLabel("Double-click to add a popular tag")
        popular_info.setStyleSheet("color: #8c93a8; font-style: italic;")
        popular_layout.addWidget(popular_info)
        
        popular_group.setLayout(popular_layout)
        layout.addWidget(popular_group)
        
        # Statistics
        stats_group = QGroupBox("Tag Statistics")
        stats_layout = QVBoxLayout()
        
        self.stats_label = QLabel("No model selected")
        self.stats_label.setObjectName("stats_label")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("color: #8c93a8;")
        stats_layout.addWidget(self.stats_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        return scroll_area
    
    def set_model(self, model_path: str):
        """
        Set the current model to tag.
        
        Args:
            model_path: Path to the 3D model file
        """
        self.current_model_path = model_path
        self.auto_tag_btn.setEnabled(True)
        
        # Load existing tags
        self.load_current_tags()
        
        # Update popular tags
        self.update_tag_cloud()
        
        logger.info(f"Model set for tagging: {os.path.basename(model_path)}")
    
    def load_current_tags(self):
        """Load current tags for the model."""
        if not self.current_model_path:
            return
        
        try:
            self.current_tags = self.tagger.get_tags(self.current_model_path)
            self.refresh_current_tags_display()
            self.update_statistics()
        except Exception as e:
            logger.error(f"Failed to load tags: {e}")
    
    def refresh_current_tags_display(self):
        """Refresh the current tags display."""
        try:
            # Self-healing
            if getattr(self.current_tags_list, 'isHidden', lambda: True)():
                found = self.findChild(QListWidget, "current_tags_list")
                if found:
                    self.current_tags_list = found

            # Check if widget is still valid
            if not self.current_tags_list or not self.current_tags_list.isVisible():
                return
                
            self.current_tags_list.clear()
            
            for tag in self.current_tags:
                item = QListWidgetItem(f"🏷️ {tag}")
                self.current_tags_list.addItem(item)
        except RuntimeError:
            # Widget might be deleted
            logger.warning("Attempted to update deleted tags list widget - attempting recovery")
            try:
                found = self.findChild(QListWidget, "current_tags_list")
                if found:
                    self.current_tags_list = found
                    self.refresh_current_tags_display() # Retry
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error refreshing tags display: {e}")
    
    def auto_generate_tags(self):
        """Generate tags automatically using AI."""
        if not self.current_model_path:
            return
        
        self.auto_tag_btn.setEnabled(False)
        self.tag_progress.setVisible(True)
        self.tag_progress.setRange(0, 0)  # Indeterminate
        
        # Update button text to show AI is working
        if self.tagger.use_clip:
            self.auto_tag_btn.setText("🤖 AI Analyzing...")
        else:
            self.auto_tag_btn.setText("📐 Analyzing Geometry...")
        
        # Start tagging worker
        self.tag_worker = TaggingWorker(self.current_model_path, self.tagger)
        self.tag_worker.finished.connect(self.on_tagging_complete)
        self.tag_worker.progress.connect(self.on_tagging_progress)
        self.tag_worker.error.connect(self.on_tagging_error)
        self.tag_worker.start()
        
        logger.info(f"Starting auto-tagging for {Path(self.current_model_path).name}")
    
    def on_tagging_progress(self, message: str):
        """Handle progress updates during tagging."""
        # Could show this in a status label if desired
        logger.debug(message)
    
    def on_tagging_complete(self, analysis: Dict):
        """Handle tagging completion with full analysis results."""
        self.auto_tag_btn.setEnabled(True)
        self.tag_progress.setVisible(False)
        self.auto_tag_btn.setText("🤖 Generate Tags Automatically")
        
        # Extract tags from analysis
        suggested_tags = analysis.get('tags', [])
        
        # Display suggested tags
        self.suggested_tags_list.clear()
        
        for tag in suggested_tags:
            # Don't suggest tags that already exist
            if tag not in self.current_tags:
                item = QListWidgetItem(f"💡 {tag}")
                self.suggested_tags_list.addItem(item)
        
        self.add_suggested_btn.setEnabled(True)
        self.add_all_btn.setEnabled(True)
        
        # Show AI analysis results if available
        if analysis.get('ai_powered') and 'ai_category' in analysis:
            ai_category = analysis['ai_category']
            ai_confidence = analysis['ai_category_confidence']
            
            # Add AI info to suggested tags list
            ai_info = QListWidgetItem(f"AI detected: {ai_category} ({ai_confidence:.0%} confidence)")
            ai_info.setForeground(QColor('#27ae60'))
            font = ai_info.font()
            font.setBold(True)
            ai_info.setFont(font)
            self.suggested_tags_list.insertItem(0, ai_info)
            
            logger.info(f"AI tagging complete: {ai_category} ({ai_confidence:.0%}), {len(suggested_tags)} tags")
        else:
            logger.info(f"Auto-tagging complete: {len(suggested_tags)} tags suggested")
    
    def on_tagging_error(self, error_msg: str):
        """Handle tagging error."""
        self.auto_tag_btn.setEnabled(True)
        self.tag_progress.setVisible(False)
        self.auto_tag_btn.setText("Generate Tags Automatically")
        logger.error(f"Tagging error: {error_msg}")
        
        # Show error in suggested tags list
        self.suggested_tags_list.clear()
        error_item = QListWidgetItem(f"Error: {error_msg}")
        error_item.setForeground(QColor('#e74c3c'))
        self.suggested_tags_list.addItem(error_item)
    
    def add_suggested_tags(self):
        """Add selected suggested tags."""
        try:
            # Self-healing: try to recover widget if deleted
            if getattr(self.suggested_tags_list, 'isHidden', lambda: True)(): 
                # Check if we can find it by name
                found = self.findChild(QListWidget, "suggested_tags_list")
                if found:
                    self.suggested_tags_list = found
                    logger.info("Recovered suggested_tags_list widget reference")
            
            if not self.suggested_tags_list or not self.suggested_tags_list.isVisible():
                return
                
            selected_items = self.suggested_tags_list.selectedItems()
            
            for item in selected_items:
                tag = item.text().replace("💡 ", "").strip()
                if tag not in self.current_tags:
                    self.current_tags.append(tag)
                    self.tagger.add_tag(self.current_model_path, tag)
            
            self.refresh_current_tags_display()
            self.update_statistics()
            self.tags_updated.emit(self.current_tags)
            
            # Remove added tags from suggestions
            for item in selected_items:
                self.suggested_tags_list.takeItem(self.suggested_tags_list.row(item))
        except RuntimeError:
            logger.warning("Attempted to access deleted widget in add_suggested_tags - attempting recovery")
            try:
                found = self.findChild(QListWidget, "suggested_tags_list")
                if found:
                    self.suggested_tags_list = found
                    self.add_suggested_tags()  # Retry once
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error adding suggested tags: {e}")
    
    def add_all_suggested_tags(self):
        """Add all suggested tags."""
        try:
            if not self.suggested_tags_list or not self.suggested_tags_list.isVisible():
                return

            for i in range(self.suggested_tags_list.count()):
                item = self.suggested_tags_list.item(i)
                tag = item.text().replace("💡 ", "").strip()
                if tag not in self.current_tags:
                    self.current_tags.append(tag)
                    self.tagger.add_tag(self.current_model_path, tag)
            
            self.suggested_tags_list.clear()
            self.refresh_current_tags_display()
            self.update_statistics()
            self.tags_updated.emit(self.current_tags)
            
            self.add_suggested_btn.setEnabled(False)
            self.add_all_btn.setEnabled(False)
        except RuntimeError:
            logger.warning("Attempted to access deleted widget in add_all_suggested_tags")
        except Exception as e:
            logger.error(f"Error adding all suggested tags: {e}")
    
    def add_custom_tag(self):
        """Add a custom tag."""
        try:
            tag = self.new_tag_input.text().strip()
            
            if not tag or not self.current_model_path:
                return
            
            if tag not in self.current_tags:
                self.current_tags.append(tag)
                self.tagger.add_tag(self.current_model_path, tag)
                self.refresh_current_tags_display()
                self.update_statistics()
                self.tags_updated.emit(self.current_tags)
            
            self.new_tag_input.clear()
        except RuntimeError:
            logger.warning("Attempted to access deleted widget in add_custom_tag")
        except Exception as e:
            logger.error(f"Error adding custom tag: {e}")
    
    def remove_selected_tags(self):
        """Remove selected tags."""
        try:
            if not self.current_tags_list or not self.current_tags_list.isVisible():
                return

            selected_items = self.current_tags_list.selectedItems()
            
            for item in selected_items:
                tag = item.text().replace("🏷️ ", "").strip()
                if tag in self.current_tags:
                    self.current_tags.remove(tag)
                    self.tagger.remove_tag(self.current_model_path, tag)
            
            self.refresh_current_tags_display()
            self.update_statistics()
            self.tags_updated.emit(self.current_tags)
        except RuntimeError:
            logger.warning("Attempted to access deleted widget in remove_selected_tags")
        except Exception as e:
            logger.error(f"Error removing selected tags: {e}")
    
    def clear_all_tags(self):
        """Clear all tags."""
        try:
            if not self.current_tags_list:
                return

            self.current_tags.clear()
            # Clear from database/storage
            for i in range(self.current_tags_list.count()):
                item = self.current_tags_list.item(i)
                tag = item.text().replace("🏷️ ", "").strip()
                self.tagger.remove_tag(self.current_model_path, tag)
            
            self.refresh_current_tags_display()
            self.update_statistics()
            self.tags_updated.emit(self.current_tags)
        except RuntimeError:
            logger.warning("Attempted to access deleted widget in clear_all_tags")
        except Exception as e:
            logger.error(f"Error clearing all tags: {e}")
    
    def show_tag_context_menu(self, position):
        """Show context menu for tags."""
        try:
            if not self.current_tags_list or not self.current_tags_list.isVisible():
                return

            menu = QMenu()
            
            remove_action = QAction("Remove", self)
            remove_action.setIcon(get_icon("delete"))
            remove_action.triggered.connect(self.remove_selected_tags)
            menu.addAction(remove_action)
            
            menu.exec(self.current_tags_list.mapToGlobal(position))
        except RuntimeError:
            logger.warning("Attempted to show context menu on deleted widget")
    
    def perform_search(self):
        """Perform natural language search."""
        try:
            query = self.search_input.text().strip()
            
            if not query:
                return
            
            # Add to history
            if query not in self.search_history:
                self.search_history.insert(0, query)
                self.search_history = self.search_history[:10]  # Keep last 10
                self.update_search_history()
            
            # Perform search
            results = self.tagger.search_assets(query)
            
            # Display results
            if results:
                valid_results = []
                for result in results:
                    path = result.get('path', '')
                    if os.path.exists(path):
                        valid_results.append(result)
                
                if valid_results:
                    result_text = f"<h3>Found {len(valid_results)} matches for '{query}':</h3><ul>"
                    for result in valid_results[:20]:  # Show first 20
                        name = result.get('name') or os.path.basename(result.get('path', 'Unknown'))
                        result_text += f"<li>{name}</li>"
                    result_text += "</ul>"
                else:
                    result_text = f"<p>No valid matches found for '{query}' (some files might be missing)</p>"
            else:
                result_text = f"<p>No matches found for '{query}'</p>"
            
            self.search_results.setHtml(result_text)
            logger.info(f"Search '{query}' returned {len(results)} results")
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            self.search_results.setHtml(f"<p style='color: red;'>Search error: {e}</p>")
    
    def quick_search(self, query: str):
        """Perform a quick search."""
        self.search_input.setText(query)
        self.perform_search()
    
    def repeat_search(self, item: QListWidgetItem):
        """Repeat a search from history."""
        query = item.text()
        self.search_input.setText(query)
        self.perform_search()
    
    def update_search_history(self):
        """Update search history display."""
        try:
            if not self.search_history_list:
                return
            self.search_history_list.clear()
            
            for query in self.search_history:
                item = QListWidgetItem(query)
                self.search_history_list.addItem(item)
        except RuntimeError:
            logger.warning("Attempted to update deleted search history widget")
    
    def update_tag_cloud(self):
        """Update the tag cloud with popular tags."""
        try:
            if not self.tag_cloud:
                return

            popular_tags = self.tagger.get_popular_tags(limit=20)
            
            self.tag_cloud.clear()
            
            for tag, count in popular_tags:
                item = QListWidgetItem(f"{tag} ({count})")
                item.setIcon(get_icon("edit"))
                item.setData(Qt.ItemDataRole.UserRole, tag)
                self.tag_cloud.addItem(item)
                
        except RuntimeError:
            logger.warning("Attempted to update deleted tag cloud widget")
        except Exception as e:
            logger.error(f"Failed to update tag cloud: {e}")
    
    def add_popular_tag(self, item: QListWidgetItem):
        """Add a popular tag to current model."""
        try:
            tag = item.data(Qt.ItemDataRole.UserRole)
            
            if not self.current_model_path or not tag:
                return
            
            if tag not in self.current_tags:
                self.current_tags.append(tag)
                self.tagger.add_tag(self.current_model_path, tag)
                self.refresh_current_tags_display()
                self.update_statistics()
                self.tags_updated.emit(self.current_tags)
        except RuntimeError:
            logger.warning("Attempted to access deleted widget in add_popular_tag")
        except Exception as e:
            logger.error(f"Error adding popular tag: {e}")
    
    def update_statistics(self):
        """Update tag statistics display."""
        try:
            # Self-healing
            if getattr(self.stats_label, 'isHidden', lambda: True)():
                found = self.findChild(QLabel, "stats_label")
                if found:
                    self.stats_label = found

            if not self.stats_label or not self.stats_label.isVisible():
                return

            if not self.current_model_path:
                self.stats_label.setText("No model selected")
                return
            
            model_name = Path(self.current_model_path).name
            tag_count = len(self.current_tags)
            
            stats_text = f"<b>Model:</b> {model_name}<br>"
            stats_text += f"<b>Total Tags:</b> {tag_count}<br>"
            
            if self.current_tags:
                stats_text += f"<b>Tags:</b> {', '.join(self.current_tags[:5])}"
                if len(self.current_tags) > 5:
                    stats_text += f" (+{len(self.current_tags) - 5} more)"
            
            self.stats_label.setText(stats_text)
        except RuntimeError:
            logger.warning("Attempted to update deleted statistics label - attempting recovery")
            try:
                found = self.findChild(QLabel, "stats_label")
                if found:
                    self.stats_label = found
                    self.update_statistics() # Retry
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error updating statistics: {e}")
    
    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Silence the tagging run in flight and wait for it to end.

        This pane is embedded in the Library tab, so the close reaches it through the
        walk of the window's children rather than through the tab loop. Both workers
        declare their own `finished` carrying the analysis - which is why the helper reads
        the channels off the object instead of a list written beside this pane - and each
        one writes into widgets that go away with it: the tag list, the confidence bar,
        the bulk status line. Neither worker can be asked to stop, so the close waits;
        what outlasts the wait stays in `tag_worker` or `bulk_worker`, because the
        reference of a running thread is what keeps Qt from aborting.
        Returns the runs still owed when the wait gave up.
        """
        return len(drain_attributes(self, ('tag_worker', 'bulk_worker'), timeout_ms))

    def bulk_auto_tag(self):
        """Perform bulk auto-tagging on a directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory to Auto-Tag")
        if not dir_path:
            return
            
        self.bulk_status.setText("Scanning for models...")
        self.bulk_tag_btn.setEnabled(False)
        self.bulk_progress.setVisible(True)
        self.bulk_progress.setValue(0)
        
        # Find all models
        model_extensions = ['.obj', '.fbx', '.glb', '.gltf', '.ply', '.stl']
        model_paths = []
        
        try:
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in model_extensions):
                        model_paths.append(os.path.join(root, file))
        except Exception as e:
            logger.error(f"Error scanning directory: {e}")
            self.bulk_status.setText(f"Error scanning directory: {e}")
            self.bulk_tag_btn.setEnabled(True)
            return

        if not model_paths:
            self.bulk_status.setText("No 3D models found in directory.")
            self.bulk_tag_btn.setEnabled(True)
            self.bulk_progress.setVisible(False)
            return
            
        self.bulk_status.setText(f"Found {len(model_paths)} models. Starting auto-tagging...")
        self.bulk_progress.setRange(0, len(model_paths))
        
        # Start worker
        self.bulk_worker = BulkTaggingWorker(model_paths, self.tagger)
        self.bulk_worker.progress.connect(self.on_bulk_progress)
        self.bulk_worker.finished.connect(self.on_bulk_finished)
        self.bulk_worker.error.connect(self.on_bulk_error)
        self.bulk_worker.start()
        
    def on_bulk_progress(self, current, total, filename):
        """Handle bulk tagging progress."""
        self.bulk_progress.setValue(current)
        self.bulk_status.setText(f"Tagging {current}/{total}: {filename}")
        
    def on_bulk_finished(self):
        """Handle bulk tagging completion."""
        self.bulk_status.setText("Bulk tagging complete!")
        self.bulk_tag_btn.setEnabled(True)
        self.bulk_progress.setVisible(False)
        QMessageBox.information(self, "Success", "Bulk auto-tagging completed successfully!")
        
    def on_bulk_error(self, error_msg):
        """Handle bulk tagging error."""
        self.bulk_status.setText(f"Error: {error_msg}")
        self.bulk_tag_btn.setEnabled(True)
        logger.error(f"Bulk tagging error: {error_msg}")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    window = AIAssetTaggerUI()
    window.setWindowTitle("AI Asset Tagger")
    window.resize(1200, 800)
    window.show()
    
    # The loop's result is taken before the exit and the windows go through the drain `main.py`
    # runs: `sys.exit(app.exec())` carries this frame, and the window in it, into interpreter
    # finalization, where `QApplication` is already gone.
    code = app.exec()
    shutdown(app)
    sys.exit(code)
