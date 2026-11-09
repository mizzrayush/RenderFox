"""
Weight Painting Tab for RenderFox.
Allows users to paint vertex weights for optimization and other processes.
"""
import sys

import os
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QSlider, QComboBox, QGroupBox, 
                             QSplitter, QFrame, QSpinBox, QDoubleSpinBox, QColorDialog, QScrollArea, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from .model_viewer import ModelViewer3D

class PaintingTab(QWidget):
    """
    Tab for interactive weight painting on 3D models.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_wrapper = None
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI layout."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Splitter for Sidebar and Viewport
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- Sidebar (Controls) ---
        sidebar = QWidget()
        sidebar.setMinimumWidth(250)
        sidebar.setMaximumWidth(300)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Painting Suite")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        sidebar_layout.addWidget(title_label)
        
        # Painting Mode Selector
        mode_group = QGroupBox("Painting Mode")
        mode_layout = QVBoxLayout()
        self.paint_mode_combo = QComboBox()
        self.paint_mode_combo.addItems(["Weight Painting", "Vertex Painting"])
        self.paint_mode_combo.currentTextChanged.connect(self.change_paint_mode)
        mode_layout.addWidget(self.paint_mode_combo)
        mode_group.setLayout(mode_layout)
        sidebar_layout.addWidget(mode_group)
        
        # Brush Settings Group
        brush_group = QGroupBox("Brush Settings")
        brush_layout = QVBoxLayout()
        
        # Brush Size
        brush_layout.addWidget(QLabel("Size:"))
        self.brush_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_size_slider.setRange(1, 100)
        self.brush_size_slider.setValue(10)
        self.brush_size_slider.valueChanged.connect(self.update_brush_settings)
        brush_layout.addWidget(self.brush_size_slider)
        
        # Brush Strength
        brush_layout.addWidget(QLabel("Strength:"))
        self.brush_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_strength_slider.setRange(1, 100)
        self.brush_strength_slider.setValue(50)
        self.brush_strength_slider.valueChanged.connect(self.update_brush_settings)
        brush_layout.addWidget(self.brush_strength_slider)
        
        # Brush Mode
        brush_layout.addWidget(QLabel("Mode:"))
        self.brush_mode_combo = QComboBox()
        self.brush_mode_combo.addItems(["Add", "Subtract", "Smooth"])
        self.brush_mode_combo.currentTextChanged.connect(self.update_brush_settings)
        brush_layout.addWidget(self.brush_mode_combo)
        
        brush_group.setLayout(brush_layout)
        sidebar_layout.addWidget(brush_group)
        
        # Color Settings Group (Hidden by default)
        self.color_group = QGroupBox("Color Settings")
        color_layout = QVBoxLayout()
        
        self.color_btn = QPushButton()
        self.color_btn.setStyleSheet("background-color: #FF0000; border: none; height: 30px;")
        self.color_btn.clicked.connect(self.pick_color)
        color_layout.addWidget(QLabel("Brush Color:"))
        color_layout.addWidget(self.color_btn)
        
        self.color_group.setLayout(color_layout)
        sidebar_layout.addWidget(self.color_group)
        self.color_group.setVisible(False) # Hidden initially (Weight Paint mode)
        
        # Operations Group
        ops_group = QGroupBox("Operations")
        ops_layout = QVBoxLayout()
        
        self.clear_weights_btn = QPushButton("Clear Weights")
        self.clear_weights_btn.clicked.connect(self.clear_weights)
        ops_layout.addWidget(self.clear_weights_btn)
        
        self.fill_weights_btn = QPushButton("Fill All (1.0)")
        self.fill_weights_btn.clicked.connect(self.fill_weights)
        ops_layout.addWidget(self.fill_weights_btn)
        
        ops_group.setLayout(ops_layout)
        sidebar_layout.addWidget(ops_group)
        
        # Save/Export Group
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout()
        
        self.save_weights_btn = QPushButton("Save Weights to Model")
        self.save_weights_btn.clicked.connect(self.save_weights)
        export_layout.addWidget(self.save_weights_btn)
        
        export_group.setLayout(export_layout)
        sidebar_layout.addWidget(export_group)
        
        # Spacer
        sidebar_layout.addStretch()
        
        # Add sidebar to splitter
        scroll = QScrollArea()
        scroll.setWidget(sidebar)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(250)
        splitter.addWidget(scroll)
        
        # --- Viewport Area ---
        viewport_container = QWidget()
        viewport_layout = QVBoxLayout(viewport_container)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        
        # Dedicated Model Viewer
        self.viewer = ModelViewer3D()
        # Enable weight visualization by default in this tab
        self.viewer.show_weights = True
        viewport_layout.addWidget(self.viewer)
        
        # Add viewport to splitter
        splitter.addWidget(viewport_container)
        
        # Set initial splitter sizes (25% sidebar, 75% viewport)
        splitter.setSizes([250, 800])
        
        # Connect viewer mouse events
        self.viewer.installEventFilter(self)
        self.is_painting = False
        self.brush_color = [1.0, 0.0, 0.0] # Default Red

    def eventFilter(self, source, event):
        if source == self.viewer:
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    # Only paint on Left Click
                    self.is_painting = True
                    self.perform_painting(event.position())
                    return True # Consume event
                # Allow Right/Middle click to pass through for navigation
                return False
            elif event.type() == event.Type.MouseMove:
                if self.is_painting:
                    self.perform_painting(event.position())
                    return True # Consume
            elif event.type() == event.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.is_painting = False
                    return True # Consume
        return super().eventFilter(source, event)

    def change_paint_mode(self, mode):
        """Switch between Weight and Vertex painting modes."""
        is_weight = (mode == "Weight Painting")
        
        # Update Viewer
        self.viewer.show_weights = is_weight
        
        if is_weight:
            # Weight Paint: Show Fill (Lit) + Weight Overlay
            self.viewer.set_render_mode("fill")
        else:
            # Vertex Paint: Show Vertex Colors (Unlit)
            self.viewer.set_render_mode("vertex_colors")
            
            # FORCE VISIBILITY CHECK
            # If colors are dark/black, reset to white
            for mesh in self.viewer.meshes:
                reset_colors = False
                if 'colors' not in mesh:
                    reset_colors = True
                else:
                    colors = mesh['colors']
                    if colors.size > 0:
                        mean_val = np.mean(colors[:, :3])
                        if mean_val < 0.1: # Too dark
                            reset_colors = True
                
                if reset_colors:
                    num_verts = len(mesh['vertices'])
                    mesh['colors'] = np.ones((num_verts, 4), dtype=np.float32)
                    
                    if mesh.get('vbo') and self.viewer.isValid():
                        self.viewer.makeCurrent()
                        mesh['vbo'].bind()
                        interleaved = np.column_stack((
                            mesh['vertices'], 
                            mesh['normals'], 
                            mesh['colors'], 
                            mesh['uvs'], 
                            mesh['weights']
                        )).astype(np.float32)
                        mesh['vbo'].write(0, interleaved.tobytes(), interleaved.nbytes)
                        mesh['vbo'].release()
                        self.viewer.doneCurrent()
            
        self.viewer.update()
        
        # Update UI Controls
        if hasattr(self, 'color_group'):
            self.color_group.setVisible(not is_weight)

    def pick_color(self):
        """Open color picker."""
        # Convert current list [r,g,b] to QColor
        c = self.brush_color
        initial = QColor.fromRgbF(c[0], c[1], c[2])
        
        col = QColorDialog.getColor(initial, self, "Select Brush Color")
        if col.isValid():
            self.brush_color = [col.redF(), col.greenF(), col.blueF()]
            self.color_btn.setStyleSheet(f"background-color: {col.name()}; border: none; height: 30px;")

    def set_model(self, model_or_wrapper):
        """Set the model to paint on."""
        
        if isinstance(model_or_wrapper, str):
            # It's a file path
            class SimpleWrapper:
                def __init__(self, path):
                    self.file_path = path
                    self.weights = None
            self.model_wrapper = SimpleWrapper(model_or_wrapper)
        else:
            self.model_wrapper = model_or_wrapper

        if self.model_wrapper and hasattr(self.model_wrapper, 'file_path') and self.model_wrapper.file_path:
            self.viewer.load_model(self.model_wrapper.file_path)
            # Load existing weights if present in wrapper
            if hasattr(self.model_wrapper, 'weights') and self.model_wrapper.weights is not None:
                pass
            
            # Ensure Vertex Colors are Visible (White)
            # If colors exist but are all black/dark, reset them to white
            for mesh in self.viewer.meshes:
                reset_colors = False
                if 'colors' not in mesh:
                    reset_colors = True
                else:
                    # Check mean brightness
                    colors = mesh['colors']
                    if colors.size > 0:
                        mean_val = np.mean(colors[:, :3])
                        if mean_val < 0.1: # Too dark
                            reset_colors = True
                
                if reset_colors:
                    num_verts = len(mesh['vertices'])
                    mesh['colors'] = np.ones((num_verts, 4), dtype=np.float32)
                    
                    # Update VBO
                    if mesh.get('vbo') and self.viewer.isValid():
                        self.viewer.makeCurrent()
                        mesh['vbo'].bind()
                        interleaved = np.column_stack((
                            mesh['vertices'], 
                            mesh['normals'], 
                            mesh['colors'], 
                            mesh['uvs'], 
                            mesh['weights']
                        )).astype(np.float32)
                        mesh['vbo'].write(0, interleaved.tobytes(), interleaved.nbytes)
                        mesh['vbo'].release()
                        self.viewer.doneCurrent()
            
            self.viewer.update()
            
    def update_brush_settings(self):
        """Update brush settings on the tab and viewer."""
        self.brush_size = self.brush_size_slider.value()
        self.brush_strength = self.brush_strength_slider.value() / 100.0
        self.brush_mode = self.brush_mode_combo.currentText()
        if hasattr(self.viewer, 'brush_size'):
            self.viewer.brush_size = self.brush_size
        if hasattr(self.viewer, 'brush_strength'):
            self.viewer.brush_strength = self.brush_strength
        if hasattr(self.viewer, 'brush_mode'):
            self.viewer.brush_mode = self.brush_mode

    def perform_painting(self, pos):
        # Get settings
        radius = self.brush_size_slider.value() / 100.0 # Scale down
        strength = self.brush_strength_slider.value() / 100.0
        mode = self.brush_mode_combo.currentText()
        
        x = int(pos.x())
        y = int(pos.y())
        
        mesh_idx, vert_idx, dist = self.viewer.get_vertex_at_screen_pos(x, y)
        
        if mesh_idx != -1:
            if self.paint_mode_combo.currentText() == "Vertex Painting":
                # Use brush color and "Mix" mode for now (or map Add/Sub)
                # Strength acts as opacity/flow
                # We pass 'Mix' as default for color painting usually
                self.viewer.apply_color(mesh_idx, vert_idx, self.brush_color, radius, "Mix")
            else:
                self.viewer.apply_weight(mesh_idx, vert_idx, strength, radius, mode)

    def clear_weights(self):
        """Clear all weights to 0."""
        for mesh in self.viewer.meshes:
            if 'weights' in mesh:
                mesh['weights'][:] = 0.0
                if mesh.get('vbo') and self.viewer.isValid():
                    self.viewer.makeCurrent()
                    mesh['vbo'].bind()
                    interleaved = np.column_stack((
                        mesh['vertices'], 
                        mesh['normals'], 
                        mesh['colors'], 
                        mesh['uvs'], 
                        mesh['weights']
                        )).astype(np.float32)
                    mesh['vbo'].write(0, interleaved.tobytes(), interleaved.nbytes)
                    mesh['vbo'].release()
                    self.viewer.doneCurrent()
        self.viewer.update()
        
    def fill_weights(self):
        """Fill all weights to 1."""
        
        for i, mesh in enumerate(self.viewer.meshes):
            has_weights = 'weights' in mesh
            has_vbo = mesh.get('vbo') is not None
            
            if has_weights:
                mesh['weights'][:] = 1.0
                if has_vbo and self.viewer.isValid():
                    self.viewer.makeCurrent()
                    mesh['vbo'].bind()
                    interleaved = np.column_stack((
                        mesh['vertices'], 
                        mesh['normals'], 
                        mesh['colors'], 
                        mesh['uvs'], 
                        mesh['weights']
                    )).astype(np.float32)
                    mesh['vbo'].write(0, interleaved.tobytes(), interleaved.nbytes)
                    mesh['vbo'].release()
                    self.viewer.doneCurrent()
        self.viewer.update()
        
    def save_weights(self):
        """Export the painted model to a file."""
        # Rename button text if needed, but keeping method name for compatibility
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Export Painted Model", 
            "", 
            "3D Models (*.glb *.obj *.ply);;All Files (*)"
        )
        
        if file_path:
            success = self.viewer.export_model(file_path)
            if success:
                QMessageBox.information(self, "Success", f"Model exported successfully to:\n{file_path}")
            else:
                QMessageBox.critical(
                    self, "Error",
                    "Failed to export model. The reason is in the Diagnostics log.")
