"""
Weight Painting Tab for RenderFox.
Allows users to paint vertex weights for optimization and other processes.
"""

import os
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QSlider, QComboBox, QGroupBox, 
                             QSplitter, QFrame, QSpinBox, QDoubleSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal
from .model_viewer import ModelViewer3D

class WeightPaintingTab(QWidget):
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
        title_label = QLabel("Weight Painting")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        sidebar_layout.addWidget(title_label)
        
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
        splitter.addWidget(sidebar)
        
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
        # We need to access the internal viewer_3d widget if ModelViewer3D is a wrapper, 
        # but ModelViewer3D inherits QOpenGLWidget directly based on previous file content.
        # However, we need to intercept events.
        # Let's use an event filter.
        self.viewer.installEventFilter(self)
        self.is_painting = False

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
                # Assuming single mesh for now or need to map wrapper weights to viewer meshes
                # For simplicity, we'll just initialize with zeros in viewer if wrapper has no weights
                # or if we need to transfer them.
                # TODO: Implement proper weight transfer from wrapper to viewer meshes
                pass
            
    def update_brush_settings(self):
        """Update brush settings in the viewer (to be implemented)."""
        size = self.brush_size_slider.value()
        strength = self.brush_strength_slider.value() / 100.0
        mode = self.brush_mode_combo.currentText()
        # print(f"Brush Update: Size={size}, Strength={strength}, Mode={mode}")

    def perform_painting(self, pos):
        # Get settings
        radius = self.brush_size_slider.value() / 100.0 # Scale down
        strength = self.brush_strength_slider.value() / 100.0
        mode = self.brush_mode_combo.currentText()
        
        x = int(pos.x())
        y = int(pos.y())
        
        mesh_idx, vert_idx, dist = self.viewer.get_vertex_at_screen_pos(x, y)
        
        # print(f"Painting at {x},{y} -> Mesh: {mesh_idx}, Vert: {vert_idx}, Dist: {dist}")
        
        if mesh_idx != -1:
            self.viewer.apply_weight(mesh_idx, vert_idx, strength, radius, mode)
        else:
            print("No vertex found under cursor.")
        
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
        print("DEBUG: Executing Fill All (1.0)")
        print(f"DEBUG: Viewer Valid: {self.viewer.isValid()}")
        print(f"DEBUG: Mesh Count: {len(self.viewer.meshes)}")
        
        for i, mesh in enumerate(self.viewer.meshes):
            has_weights = 'weights' in mesh
            has_vbo = mesh.get('vbo') is not None
            print(f"DEBUG: Mesh {i} - Has Weights: {has_weights}, Has VBO: {has_vbo}")
            
            if has_weights:
                mesh['weights'][:] = 1.0
                if has_vbo and self.viewer.isValid():
                    print(f"DEBUG: Updating VBO for mesh {i}")
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
        """Save weights back to the model wrapper."""
        if self.model_wrapper:
            # Aggregate weights from all meshes?
            # For now, just take the first one or handle multi-mesh
            all_weights = []
            for mesh in self.viewer.meshes:
                if 'weights' in mesh:
                    all_weights.append(mesh['weights'])
            
            if all_weights:
                # Concatenate if multiple meshes (assuming order matches)
                self.model_wrapper.weights = np.vstack(all_weights)
                print("Weights saved to model wrapper.")
            else:
                print("No weights to save.")
