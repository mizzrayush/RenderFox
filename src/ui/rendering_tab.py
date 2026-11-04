"""
Rendering Tab for RenderFox v2.0
================================
A professional-grade Studio environment for Look Development, Lighting, and Rendering.
This module implements a robust, fixed-layout workspace consistent with the rest of the application.

Architecture:
- Main Class: RenderingTab (QWidget)
- Layout: QSplitter (Viewport | Tool Panel)
- Tool Panel: QTabWidget (Materials, Lighting, Camera, Settings)
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QFrame, QToolBar, QStatusBar,
    QPushButton, QComboBox, QSlider, QGroupBox, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QSizePolicy, QFileDialog,
    QDoubleSpinBox, QSpinBox, QCheckBox, QColorDialog
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QColor

# Import Core Systems
from .model_viewer import ModelViewer3D
from .rendering.node_graph import NodeGraphWidget
from ..core.material_data import Material
from .texture_generator import TextureGeneratorDialog
from .icon_provider import get_icon

# ============================================================================
# STYLES
# ============================================================================

STYLESHEET_PANEL = """
    QGroupBox {
        border: 1px solid #444;
        border-radius: 4px;
        margin-top: 20px;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 5px;
        color: #AAA;
    }
"""

STYLESHEET_BUTTON_PRIMARY = """
    QPushButton {
        background-color: #2196F3;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #1976D2;
    }
    QPushButton:pressed {
        background-color: #0D47A1;
    }
"""

STYLESHEET_BUTTON_SECONDARY = """
    QPushButton {
        background-color: #424242;
        color: white;
        border: 1px solid #616161;
        padding: 6px 12px;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #616161;
    }
"""

# ============================================================================
# SUB-PANELS
# ============================================================================

class BasePanel(QWidget):
    """Base class for all rendering panels with common functionality."""
    
    def __init__(self, title):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # Header
        header = QLabel(title)
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFF; margin-bottom: 10px;")
        self.layout.addWidget(header)
        
    def add_section(self, title):
        """Add a collapsible section (GroupBox)."""
        group = QGroupBox(title)
        group.setStyleSheet(STYLESHEET_PANEL)
        layout = QVBoxLayout(group)
        self.layout.addWidget(group)
        return layout

    def create_texture_slot(self, label_text, key):
        """Create a row with a label, file path display, and load button."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        label = QLabel(label_text)
        label.setMinimumWidth(100)
        
        path_display = QLabel("No texture")
        path_display.setStyleSheet("color: #888; font-style: italic;")
        path_display.setMinimumWidth(120)
        
        btn = QPushButton("Load...")
        btn.setStyleSheet(STYLESHEET_BUTTON_SECONDARY)
        btn.setFixedWidth(60)
        btn.clicked.connect(lambda: self.load_texture(key, path_display))
        
        layout.addWidget(label)
        layout.addWidget(path_display)
        layout.addWidget(btn)
        
        # Store references
        if not hasattr(self, 'texture_slots'):
            self.texture_slots = {}
        self.texture_slots[key] = {'path': None, 'display': path_display}
        
        return container

    def load_texture(self, key, display_label):
        """Open file dialog to load a texture."""
        path, _ = QFileDialog.getOpenFileName(
            self, f"Load {key} Texture", "", 
            "Images (*.png *.jpg *.jpeg *.tga *.bmp);;All Files (*.*)"
        )
        if path:
            filename = os.path.basename(path)
            display_label.setText(filename)
            display_label.setStyleSheet("color: #FFF;")
            self.texture_slots[key]['path'] = path
            self.update_material()

    def create_row(self, label_text, widget):
        """Create a labeled row."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setMinimumWidth(100)
        layout.addWidget(label)
        layout.addWidget(widget)
        return container

class MaterialEditorPanel(BasePanel):
    """Panel for Material Node Graph and Properties."""
    
    material_updated = pyqtSignal(dict) # Emits dict of properties
    
    def __init__(self):
        super().__init__("Material Editor")
        self.init_ui()
        
    def init_ui(self):
        # Preview Section
        preview_layout = self.add_section("Preview")
        preview_box = QLabel("Material Preview\n(Sphere)")
        preview_box.setFixedSize(150, 150)
        preview_box.setStyleSheet("background: #222; border: 1px solid #444; border-radius: 75px;")
        preview_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_box, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Properties Section
        props_layout = self.add_section("Surface Properties")
        
        # Base Color
        self.color_btn = QPushButton()
        self.color_btn.setStyleSheet("background-color: #FFF; border: none; height: 20px;")
        props_layout.addWidget(self.create_row("Base Color:", self.color_btn))
        
        # Metallic
        self.metallic = QSlider(Qt.Orientation.Horizontal)
        props_layout.addWidget(self.create_row("Metallic:", self.metallic))
        
        # Roughness
        self.roughness = QSlider(Qt.Orientation.Horizontal)
        self.roughness.setValue(50)
        props_layout.addWidget(self.create_row("Roughness:", self.roughness))
        
        # Texture Maps Section
        
        # AI Texture Generation
        ai_layout = self.add_section("AI Texture Generator")
        self.gen_tex_btn = QPushButton("Generate / Load Texture")
        self.gen_tex_btn.setIcon(get_icon("sparkles", color="#ffffff"))
        self.gen_tex_btn.setProperty("primary", "true")
        self.gen_tex_btn.clicked.connect(self.open_texture_generator)
        ai_layout.addWidget(self.gen_tex_btn)
        
        tex_layout = self.add_section("Texture Maps")
        
        tex_layout.addWidget(self.create_texture_slot("Albedo:", "albedo"))
        tex_layout.addWidget(self.create_texture_slot("Normal:", "normal"))
        tex_layout.addWidget(self.create_texture_slot("Metallic:", "metallic"))
        tex_layout.addWidget(self.create_texture_slot("Roughness:", "roughness"))
        tex_layout.addWidget(self.create_texture_slot("Occlusion:", "occlusion"))
        tex_layout.addWidget(self.create_texture_slot("Emissive:", "emissive"))
        
        # Node Graph
        graph_layout = self.add_section("Node Graph")
        
        # Create Node Graph Widget
        self.node_graph = NodeGraphWidget()
        self.node_graph.setMinimumHeight(300)
        
        # Initialize with default material
        default_mat = Material.create_default()
        self.node_graph.set_material(default_mat)
        self.node_graph.material_changed.connect(self.update_material)
        
        graph_layout.addWidget(self.node_graph)
        
        self.layout.addStretch()
        
    def update_material(self):
        """Update the viewport based on material graph."""
        if not self.node_graph.material: return
        
        # Simple graph parser: Find Principled BSDF connected to Output
        # In a real engine, we'd traverse from Output backwards
        
        base_color = [0.8, 0.8, 0.8]
        metallic = 0.0
        roughness = 0.5
        
        for node in self.node_graph.material.nodes:
            if node.type.value == "Principled BSDF":
                # Get values from sockets (indices based on creation order in material_data.py)
                # 0: Base Color, 1: Metallic, 2: Roughness
                
                # Base Color
                val = node.inputs[0].value
                if val: base_color = val
                
                # Metallic
                val = node.inputs[1].value
                if val is not None: metallic = float(val)
                
                # Roughness
                val = node.inputs[2].value
                if val is not None: roughness = float(val)
                
        # Emit update
        data = {
            'base_color': base_color,
            'metallic': metallic,
            'roughness': roughness
        }
        
        # Add texture paths if available
        if hasattr(self, 'texture_slots'):
            for key, slot in self.texture_slots.items():
                if slot['path']:
                    data[f'{key}_texture'] = slot['path']
                    
        self.material_updated.emit(data)


    def open_texture_generator(self):
        """Open the AI Texture Generator dialog."""
        dialog = TextureGeneratorDialog(self)
        dialog.texture_ready.connect(self.apply_generated_texture)
        dialog.exec()
        
    def apply_generated_texture(self, file_path, slot_name="albedo"):
        """Apply the generated texture to the specified slot."""
        if not file_path or not os.path.exists(file_path):
            return
            
        # Use the slot name provided by the dialog
        if hasattr(self, 'texture_slots') and slot_name in self.texture_slots:
            slot = self.texture_slots[slot_name]
            slot['path'] = file_path
            slot['display'].setText(os.path.basename(file_path))
            slot['display'].setStyleSheet("color: #FFF;")
            self.update_material()
            
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Texture Applied", f"Applied texture to {slot_name.title()} slot:\n{os.path.basename(file_path)}")
        else:
            print(f"Error: Slot '{slot_name}' not found in texture_slots: {list(self.texture_slots.keys())}")

class LightingPanel(BasePanel):
    """Panel for Lighting and Environment controls."""
    
    lighting_updated = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__("Lighting & Environment")
        
        # Local state for 5 lights (matching ModelViewer3D defaults)
        self.current_light_index = 0
        self.lights = [
            {'name': 'Sun (Main)', 'pos': [5.0, 5.0, 5.0], 'color': [1.0, 1.0, 1.0], 'intensity': 1.0, 'enabled': True},
            {'name': 'Fill Light', 'pos': [-5.0, 5.0, -5.0], 'color': [0.8, 0.8, 1.0], 'intensity': 0.0, 'enabled': False},
            {'name': 'Back Light', 'pos': [0.0, 5.0, -5.0], 'color': [1.0, 0.9, 0.8], 'intensity': 0.0, 'enabled': False},
            {'name': 'Extra Light 1', 'pos': [0.0, 0.0, 0.0], 'color': [1.0, 1.0, 1.0], 'intensity': 0.0, 'enabled': False},
            {'name': 'Extra Light 2', 'pos': [0.0, 0.0, 0.0], 'color': [1.0, 1.0, 1.0], 'intensity': 0.0, 'enabled': False},
        ]
        
        self.init_ui()
        
    def init_ui(self):
        # Environment Section
        env_layout = self.add_section("Environment (HDRI)")
        
        self.hdri_path = QPushButton("Load HDRI...")
        self.hdri_path.setStyleSheet(STYLESHEET_BUTTON_SECONDARY)
        self.hdri_path.clicked.connect(self.load_hdri)
        env_layout.addWidget(self.create_row("Map:", self.hdri_path))
        
        self.env_strength = QDoubleSpinBox()
        self.env_strength.setValue(1.0)
        self.env_strength.valueChanged.connect(lambda: self.emit_update(env_only=True))
        env_layout.addWidget(self.create_row("Global Strength:", self.env_strength))

        # HDRI Advanced Settings
        self.env_rotation_y = QSlider(Qt.Orientation.Horizontal)
        self.env_rotation_y.setRange(0, 360)
        self.env_rotation_y.valueChanged.connect(lambda: self.emit_update(env_only=True))
        env_layout.addWidget(self.create_row("Rotation Y:", self.env_rotation_y))

        self.env_blur = QDoubleSpinBox()
        self.env_blur.setRange(0.0, 5.0)
        self.env_blur.setSingleStep(0.1)
        self.env_blur.valueChanged.connect(lambda: self.emit_update(env_only=True))
        env_layout.addWidget(self.create_row("Blur:", self.env_blur))

        self.bg_intensity = QDoubleSpinBox()
        self.bg_intensity.setRange(0.0, 10.0)
        self.bg_intensity.setValue(1.0)
        self.bg_intensity.setSingleStep(0.1)
        self.bg_intensity.valueChanged.connect(lambda: self.emit_update(env_only=True))
        env_layout.addWidget(self.create_row("Background Brightness:", self.bg_intensity))

        self.light_influence = QDoubleSpinBox()
        self.light_influence.setRange(0.0, 10.0)
        self.light_influence.setValue(1.0)
        self.light_influence.setSingleStep(0.1)
        self.light_influence.valueChanged.connect(lambda: self.emit_update(env_only=True))
        env_layout.addWidget(self.create_row("Lighting Influence:", self.light_influence))
        
        # Light Selector
        light_sel_layout = self.add_section("Light Source")
        
        self.light_selector = QComboBox()
        for i, light in enumerate(self.lights):
            self.light_selector.addItem(light['name'], i)
        self.light_selector.currentIndexChanged.connect(self.change_light_selection)
        light_sel_layout.addWidget(self.create_row("Selected Light:", self.light_selector))
        
        # Light Properties
        props_layout = self.add_section("Light Properties")
        
        self.light_enable = QCheckBox("Enable Light")
        self.light_enable.toggled.connect(self.on_param_changed)
        props_layout.addWidget(self.light_enable)
        
        self.light_color_btn = QPushButton()
        self.light_color_btn.setStyleSheet("background-color: #FFF; border: none; height: 20px;")
        self.light_color_btn.clicked.connect(self.pick_light_color)
        props_layout.addWidget(self.create_row("Color:", self.light_color_btn))
        
        self.light_intensity = QDoubleSpinBox()
        self.light_intensity.setRange(0.0, 10.0)
        self.light_intensity.setSingleStep(0.1)
        self.light_intensity.valueChanged.connect(self.on_param_changed)
        props_layout.addWidget(self.create_row("Intensity:", self.light_intensity))
        
        # Position
        pos_layout = self.add_section("Position")
        
        self.pos_x = QDoubleSpinBox()
        self.pos_x.setRange(-100, 100)
        self.pos_x.valueChanged.connect(self.on_param_changed)
        pos_layout.addWidget(self.create_row("X:", self.pos_x))
        
        self.pos_y = QDoubleSpinBox()
        self.pos_y.setRange(-100, 100)
        self.pos_y.valueChanged.connect(self.on_param_changed)
        pos_layout.addWidget(self.create_row("Y:", self.pos_y))
        
        self.pos_z = QDoubleSpinBox()
        self.pos_z.setRange(-100, 100)
        self.pos_z.valueChanged.connect(self.on_param_changed)
        pos_layout.addWidget(self.create_row("Z:", self.pos_z))
        
        self.layout.addStretch()
        
        # Initialize UI with first light
        self.update_ui_from_data()
        
    def load_hdri(self):
        """Open file dialog to select HDRI/Image."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Environment Map", "", 
            "Images (*.png *.jpg *.jpeg *.hdr *.exr);;All Files (*.*)"
        )
        if path:
            self.hdri_path.setText(os.path.basename(path))
            # Emit update with new path
            self.emit_update(hdri_path=path)

    def change_light_selection(self, index):
        """Switch the UI to show the selected light's data."""
        self.current_light_index = index
        self.update_ui_from_data()
        
    def update_ui_from_data(self):
        """Update UI controls from the current light data."""
        data = self.lights[self.current_light_index]
        
        # Block signals to prevent feedback loop
        self.block_signals(True)
        
        self.light_enable.setChecked(data['enabled'])
        self.light_intensity.setValue(data['intensity'])
        self.pos_x.setValue(data['pos'][0])
        self.pos_y.setValue(data['pos'][1])
        self.pos_z.setValue(data['pos'][2])
        
        # Update color button
        c = data['color']
        col = QColor.fromRgbF(c[0], c[1], c[2])
        self.light_color_btn.setStyleSheet(f"background-color: {col.name()}; border: 1px solid #555;")
        
        self.block_signals(False)
        
    def block_signals(self, block):
        self.light_enable.blockSignals(block)
        self.light_intensity.blockSignals(block)
        self.pos_x.blockSignals(block)
        self.pos_y.blockSignals(block)
        self.pos_z.blockSignals(block)
        
    def pick_light_color(self):
        """Open color picker for light."""
        current = self.lights[self.current_light_index]['color']
        col = QColorDialog.getColor(QColor.fromRgbF(*current), self, "Select Light Color")
        if col.isValid():
            self.lights[self.current_light_index]['color'] = [col.redF(), col.greenF(), col.blueF()]
            self.update_ui_from_data()
            self.emit_update()

    def on_param_changed(self):
        """Update local data from UI and emit change."""
        idx = self.current_light_index
        self.lights[idx]['enabled'] = self.light_enable.isChecked()
        self.lights[idx]['intensity'] = self.light_intensity.value()
        self.lights[idx]['pos'] = [self.pos_x.value(), self.pos_y.value(), self.pos_z.value()]
        self.emit_update()

    def emit_update(self, env_only=False, hdri_path=None):
        """Emit the current lighting state."""
        if hdri_path:
             data = {'hdri_path': hdri_path}
        elif env_only:
            data = {
                'env_strength': self.env_strength.value(),
                'env_rotation': self.env_rotation_y.value(),
                'env_blur': self.env_blur.value(),
                'bg_intensity': self.bg_intensity.value(),
                'light_influence': self.light_influence.value()
            }
        else:
            idx = self.current_light_index
            l = self.lights[idx]
            # If disabled, send 0 intensity, but keep the stored intensity value for UI
            intensity = l['intensity'] if l['enabled'] else 0.0
            
            data = {
                'light_index': idx,
                'pos': l['pos'],
                'color': l['color'],
                'intensity': intensity,
                'env_strength': self.env_strength.value(),
                'env_rotation': self.env_rotation_y.value(),
                'env_blur': self.env_blur.value(),
                'bg_intensity': self.bg_intensity.value(),
                'light_influence': self.light_influence.value()
            }
        self.lighting_updated.emit(data)

class CameraPanel(BasePanel):
    """Panel for Camera and Post-Processing."""
    
    camera_updated = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__("Camera Settings")
        self.init_ui()
        
    def init_ui(self):
        # Lens
        lens_layout = self.add_section("Lens")
        
        self.fov = QSlider(Qt.Orientation.Horizontal)
        self.fov.setRange(10, 120)
        self.fov.setValue(45)
        self.fov.valueChanged.connect(self.emit_update)
        lens_layout.addWidget(self.create_row("Field of View:", self.fov))
        
        self.dof_enable = QCheckBox("Depth of Field")
        self.dof_enable.toggled.connect(self.emit_update)
        lens_layout.addWidget(self.dof_enable)
        
        self.focus_dist = QDoubleSpinBox()
        self.focus_dist.setRange(0.1, 100.0)
        self.focus_dist.setValue(10.0)
        self.focus_dist.valueChanged.connect(self.emit_update)
        lens_layout.addWidget(self.create_row("Focus Distance:", self.focus_dist))
        
        self.aperture = QDoubleSpinBox()
        self.aperture.setRange(0.1, 32.0)
        self.aperture.setValue(2.8)
        self.aperture.valueChanged.connect(self.emit_update)
        lens_layout.addWidget(self.create_row("Aperture (f-stop):", self.aperture))
        
        # Post-Processing
        post_layout = self.add_section("Post-Processing")
        
        self.exposure = QDoubleSpinBox()
        self.exposure.setRange(0.1, 5.0)
        self.exposure.setSingleStep(0.1)
        self.exposure.setValue(1.0)
        self.exposure.valueChanged.connect(self.emit_update)
        post_layout.addWidget(self.create_row("Exposure:", self.exposure))
        
        self.gamma = QDoubleSpinBox()
        self.gamma.setRange(0.1, 3.0)
        self.gamma.setSingleStep(0.1)
        self.gamma.setValue(2.2)
        self.gamma.valueChanged.connect(self.emit_update)
        post_layout.addWidget(self.create_row("Gamma:", self.gamma))
        
        self.contrast = QDoubleSpinBox()
        self.contrast.setRange(0.0, 2.0)
        self.contrast.setSingleStep(0.1)
        self.contrast.setValue(1.0)
        self.contrast.valueChanged.connect(self.emit_update)
        post_layout.addWidget(self.create_row("Contrast:", self.contrast))
        
        self.saturation = QDoubleSpinBox()
        self.saturation.setRange(0.0, 2.0)
        self.saturation.setSingleStep(0.1)
        self.saturation.setValue(1.0)
        self.saturation.valueChanged.connect(self.emit_update)
        post_layout.addWidget(self.create_row("Saturation:", self.saturation))
        
        self.vignette_enable = QCheckBox("Vignette")
        self.vignette_enable.toggled.connect(self.emit_update)
        post_layout.addWidget(self.vignette_enable)
        
        self.vignette_intensity = QDoubleSpinBox()
        self.vignette_intensity.setRange(0.0, 1.0)
        self.vignette_intensity.setSingleStep(0.1)
        self.vignette_intensity.setValue(0.5)
        self.vignette_intensity.valueChanged.connect(self.emit_update)
        post_layout.addWidget(self.create_row("Vignette Intensity:", self.vignette_intensity))
        
        self.layout.addStretch()

    def emit_update(self):
        """Emit current camera settings."""
        data = {
            'fov': self.fov.value(),
            'dof_enabled': self.dof_enable.isChecked(),
            'focus_dist': self.focus_dist.value(),
            'aperture': self.aperture.value(),
            'exposure': self.exposure.value(),
            'gamma': self.gamma.value(),
            'contrast': self.contrast.value(),
            'saturation': self.saturation.value(),
            'vignette_enabled': self.vignette_enable.isChecked(),
            'vignette_intensity': self.vignette_intensity.value()
        }
        self.camera_updated.emit(data)

class RenderSettingsPanel(BasePanel):
    """Panel for the resolution and file format of this tab's preview render."""

    # The label the user reads, and what it means at the two places it has to go:
    # the size the file is written at, and the tag Qt's image writer is told.
    RESOLUTIONS = {"1920x1080 (HD)": (1920, 1080),
                   "3840x2160 (4K)": (3840, 2160),
                   "1280x720 (HD)": (1280, 720)}
    FORMATS = {"PNG Sequence": ('png', 'PNG'), "JPG Sequence": ('jpg', 'JPG')}

    render_requested = pyqtSignal()

    def __init__(self):
        super().__init__("Render Settings")
        self.init_ui()

    def init_ui(self):
        # Output
        out_layout = self.add_section("Output")

        self.res_combo = QComboBox()
        self.res_combo.addItems(list(self.RESOLUTIONS) + ["Custom"])
        out_layout.addWidget(self.create_row("Resolution:", self.res_combo))

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(self.FORMATS))
        out_layout.addWidget(self.create_row("Format:", self.format_combo))

        # Quality
        qual_layout = self.add_section("Quality")

        self.denoise = QCheckBox("Use AI Denoising")
        self.denoise.setChecked(True)
        qual_layout.addWidget(self.denoise)

        self.render_btn = QPushButton("Render Image")
        self.render_btn.setMinimumHeight(40)
        self.render_btn.setStyleSheet(STYLESHEET_BUTTON_PRIMARY)
        self.render_btn.clicked.connect(self.render_requested.emit)
        self.layout.addWidget(self.render_btn)

        self.layout.addStretch()

    def values(self, viewport_size):
        """(size, extension, Qt tag, denoise) for the settings as they stand.

        "Custom" means the viewport's own size: the resolution the file is written
        at has to come from something real, and the pane is the only other thing
        here that knows how big the picture is.
        """
        size = self.RESOLUTIONS.get(self.res_combo.currentText())
        if size is None:
            size = (max(1, viewport_size.width()), max(1, viewport_size.height()))
        extension, tag = self.FORMATS.get(self.format_combo.currentText(),
                                          self.FORMATS["PNG Sequence"])
        return size, extension, tag, self.denoise.isChecked()

# ============================================================================
# MAIN RENDERING TAB
# ============================================================================

class RenderingTab(QWidget):
    """
    The main container for the Rendering Studio.
    Uses a fixed QSplitter layout for consistency with other tabs.
    """
    
    
    status_message = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.model_path = None
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar
        self.create_toolbar(layout)
        
        # Main Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter)
        
        # 1. Central Viewport Area
        self.viewport_container = QWidget()
        viewport_layout = QVBoxLayout(self.viewport_container)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        
        self.viewport = ModelViewer3D()
        viewport_layout.addWidget(self.viewport)
        
        self.splitter.addWidget(self.viewport_container)
        
        # 2. Right Tool Panel (Tabbed)
        self.tool_panel = QTabWidget()
        self.tool_panel.setStyleSheet("""
            QTabWidget::pane { border: none; background: #252526; }
            QTabBar::tab { background: #333; color: #AAA; padding: 8px 12px; }
            QTabBar::tab:selected { background: #252526; color: #FFF; border-top: 2px solid #2196F3; }
        """)
        
        # Add Sub-Panels
        self.material_panel = MaterialEditorPanel()
        self.material_panel.material_updated.connect(self.on_material_updated)
        
        self.tool_panel.addTab(self.create_scrollable(self.material_panel), "Materials")
        
        self.lighting_panel = LightingPanel()
        self.lighting_panel.lighting_updated.connect(self.on_lighting_updated)
        self.tool_panel.addTab(self.create_scrollable(self.lighting_panel), "Lighting")
        
        self.camera_panel = CameraPanel()
        self.camera_panel.camera_updated.connect(self.on_camera_updated)
        self.tool_panel.addTab(self.create_scrollable(self.camera_panel), "Camera")
        
        self.settings_panel = RenderSettingsPanel()
        self.settings_panel.render_requested.connect(self.render_frame)
        self.tool_panel.addTab(self.create_scrollable(self.settings_panel), "Settings")
        
        self.splitter.addWidget(self.tool_panel)
        
        # Set initial sizes (70% Viewport, 30% Tools)
        self.splitter.setSizes([800, 350])
        
        # Status Bar removed (using MainWindow's status bar)
        # self.status_bar = QStatusBar()
        # self.status_bar.showMessage("Ready. OpenGL 3.3 Context Active.")
        # layout.addWidget(self.status_bar)
        
    def create_scrollable(self, widget):
        """Wrap a widget in a scroll area."""
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll
        
    def create_toolbar(self, parent_layout):
        """Create the main rendering toolbar."""
        toolbar = QToolBar("Rendering Tools")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)
        parent_layout.addWidget(toolbar)
        
        # Render Modes with crisp vector icons
        modes = [("Wireframe", "wireframe", 'wireframe'), ("Solid", "solid", 'solid'),
                 ("Material", "material", 'material'), ("Rendered", "rendered", 'rendered')]
        for label, icon_name, mode in modes:
            action = toolbar.addAction(label)
            action.setIcon(get_icon(icon_name))
            action.triggered.connect(lambda checked=False, m=mode: self.set_view_mode(m))

        toolbar.addSeparator()

        # View Controls
        action_reset = toolbar.addAction("Reset View")
        action_reset.setIcon(get_icon("reset_view"))
        action_reset.triggered.connect(self.reset_view)

        toolbar.addSeparator()

        # Tools
        action_snap = toolbar.addAction("Snapshot")
        action_snap.setIcon(get_icon("camera"))
        action_snap.triggered.connect(self.snapshot)

        action_grid = toolbar.addAction("Toggle Grid")
        action_grid.setIcon(get_icon("grid"))
        action_grid.triggered.connect(self.toggle_grid)

        action_overlays = toolbar.addAction("Toggle Overlays")
        action_overlays.setIcon(get_icon("overlays"))
        action_overlays.triggered.connect(self.toggle_overlays)

        toolbar.addSeparator()
        action_export = toolbar.addAction("Export Scene")
        action_export.setIcon(get_icon("export"))
        action_export.triggered.connect(self.export_scene)
        
        # Spacer
        empty = QWidget()
        empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(empty)
        
        # Render Button
        btn_render = QPushButton("Render Frame")
        btn_render.setIcon(get_icon("rendering", color="#ffffff"))
        btn_render.setProperty("primary", "true")
        btn_render.clicked.connect(self.render_frame)
        toolbar.addWidget(btn_render)

    def set_view_mode(self, mode):
        """Switch the viewport between the four looks the toolbar offers.

        These are the viewport's own switches, and `rendered` is the clean plate:
        textured, lit, grid and axis labels off, which is what the frame is when it
        is meant to be judged rather than worked on. There is no second renderer
        behind this tab, so no mode here means sampling, ray tracing or denoising -
        those are the queue's and the DCC's job.
        """
        self.viewport.set_render_mode('wireframe' if mode == 'wireframe' else 'fill')
        self.viewport.set_use_textures(mode in ('material', 'rendered'))
        self.viewport.set_use_vertex_colors(mode != 'solid')
        if mode == 'rendered':
            self.viewport.set_show_grid(False)
            self.viewport.set_show_overlays(False)
        self.status_message.emit(f"Viewport: {mode.title()}")

    def reset_view(self):
        """Put the camera and the model transform back where they started."""
        self.viewport.reset_view()
        self.status_message.emit("View reset")

    def toggle_grid(self):
        show = not getattr(self.viewport, 'show_grid', False)
        self.viewport.set_show_grid(show)
        self.status_message.emit(f"Grid: {'on' if show else 'off'}")

    def toggle_overlays(self):
        show = not getattr(self.viewport, 'show_overlays', True)
        self.viewport.set_show_overlays(show)
        self.status_message.emit(f"Overlays: {'on' if show else 'off'}")

    def _output_seed(self):
        """Where a picture from this tab should land: beside the model, if there is one."""
        return os.path.dirname(os.path.abspath(self.model_path)) if self.model_path else os.getcwd()

    def _frame_name(self, extension):
        stem = os.path.splitext(os.path.basename(self.model_path))[0] if self.model_path else 'render'
        return f"{stem}_0001.{extension}"

    def _grab_view(self, size):
        """The viewport, at exactly the requested size.

        The pane is rarely the aspect ratio the settings ask for, so the image is
        scaled to cover the box and the overflow is cropped from the centre: the
        file is the resolution it claims, and the pixels are not stretched to get
        there.
        """
        image = self.viewport.grab().toImage()
        if image.isNull():
            return None
        scaled = image.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        left = max(0, (scaled.width() - size[0]) // 2)
        top = max(0, (scaled.height() - size[1]) // 2)
        return scaled.copy(left, top, size[0], size[1])

    def snapshot(self):
        """Save what the viewport shows right now, at its own size, as a PNG."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Viewport Snapshot", os.path.join(self._output_seed(), 'snapshot.png'),
            "PNG image (*.png)")
        if not path:
            return
        image = self.viewport.grab().toImage()
        if image.isNull() or not image.save(path, 'PNG'):
            self.status_message.emit(f"Snapshot could not be written to {path}")
            return
        self.status_message.emit(f"Snapshot saved to {path}")

    def render_frame(self):
        """Write the current view as one frame of the chosen sequence.

        This is the tab's own render: the OpenGL view, at the resolution and format
        the Settings pane asks for, denoised through the same OpenCV pass the
        Post-Processing tab uses when the box is ticked. It is a frame of a
        lookdev preview, not a Cycles picture, and it is reported as what it is -
        the file, at the size it has.
        """
        size, extension, tag, denoise = self.settings_panel.values(self.viewport.size())
        directory = QFileDialog.getExistingDirectory(self, "Choose an output folder",
                                                     self._output_seed())
        if not directory:
            self.status_message.emit("Render stopped: no output folder chosen")
            return
        path = os.path.join(directory, self._frame_name(extension))
        image = self._grab_view(size)
        if image is None:
            self.status_message.emit("Nothing to render: the viewport has no image")
            return
        if not image.save(path, tag):
            self.status_message.emit(f"Render failed: {path} could not be written")
            return
        cleaned = self._denoise_in_place(path) if denoise else False
        self.status_message.emit(
            f"Rendered {os.path.basename(path)} ({size[0]}x{size[1]}"
            f"{', denoised' if cleaned else ', as rendered'})")

    def _denoise_in_place(self, path):
        """Denoise the frame through the Post-Processing tab's own pass, or keep the raw one.

        The denoiser writes to the path it is handed, so a failure part-way through
        would otherwise destroy the frame that was already on disk - and the file has
        to keep its real extension, or OpenCV has no writer to pick.
        """
        head, extension = os.path.splitext(path)
        temporary = f"{head}.denoising{extension}"
        try:
            from ..processing.postprocessor import ImageDenoiser
            done = ImageDenoiser().denoise_image(path, temporary)
        except Exception as error:
            print(f"Denoising unavailable: {error}")
            done = False
        if done and os.path.isfile(temporary):
            os.replace(temporary, path)
            return True
        if os.path.isfile(temporary):
            os.remove(temporary)
        return False

        
    def set_model(self, model_path):
        """Load a model into the viewport."""
        self.model_path = model_path
        self.viewport.load_model(model_path)
        self.status_message.emit(f"Loaded model: {os.path.basename(model_path)}")
        
    def on_material_updated(self, data):
        """Handle material updates from the panel."""
        if 'base_color' in data:
            c = data['base_color']
            self.viewport.set_base_color(c[0], c[1], c[2])
            
        if 'metallic' in data:
            # ModelViewer3D doesn't have metallic/roughness yet, but we can map them
            # For now, let's map roughness to shininess (inverse)
            r = data['roughness']
            shininess = (1.0 - r) * 128.0
            self.viewport.set_lighting_params(shininess=shininess)
            
        # Handle Texture Updates
        if 'albedo_texture' in data:
            self.viewport.set_material_texture('albedo', data['albedo_texture'])
        if 'normal_texture' in data:
            self.viewport.set_material_texture('normal', data['normal_texture'])
        if 'metallic_texture' in data:
            self.viewport.set_material_texture('metallic', data['metallic_texture'])
        if 'roughness_texture' in data:
            self.viewport.set_material_texture('roughness', data['roughness_texture'])
        if 'occlusion_texture' in data:
            self.viewport.set_material_texture('occlusion', data['occlusion_texture'])
        if 'emissive_texture' in data:
            self.viewport.set_material_texture('emissive', data['emissive_texture'])
            
        self.viewport.update()
        
    def on_lighting_updated(self, data):
        """Handle lighting updates from the panel."""
        # HDRI Path
        if 'hdri_path' in data:
            self.viewport.load_environment_map(data['hdri_path'])
            return

        # Environment Strength -> Ambient
        if 'env_strength' in data:
            strength = data['env_strength']
            # We now use light_influence for ambient, but keep strength as a global multiplier if needed
            # For now, let's map light_influence to ambient if present, otherwise use strength
            light_inf = data.get('light_influence', 1.0)
            self.viewport.set_lighting_params(ambient=0.2 * strength * light_inf)
            
        # HDRI Advanced Params
        if 'env_rotation' in data:
            self.viewport.set_env_params(
                rotation=data.get('env_rotation'),
                blur=data.get('env_blur'),
                bg_intensity=data.get('bg_intensity')
            )
            
        # Multi-Light Update
        if 'light_index' in data:
            idx = data['light_index']
            
            # Position
            if 'pos' in data:
                pos = data['pos']
                self.viewport.set_light_position(pos[0], pos[1], pos[2], index=idx)
                
            # Color and Intensity
            color = data.get('color')
            intensity = data.get('intensity')
            
            if color is not None or intensity is not None:
                # Convert color list to numpy array if needed, but set_light_params handles it
                self.viewport.set_light_params(index=idx, color=color, intensity=intensity)
            
        self.viewport.update()

    def on_camera_updated(self, data):
        """Handle camera updates from the panel."""
        # Lens
        if 'fov' in data:
            self.viewport.set_camera_params(fov=data['fov'])
        
        # Post-Processing (Exposure, Gamma, etc.)
        self.viewport.set_post_process_params(
            exposure=data.get('exposure'),
            gamma=data.get('gamma'),
            saturation=data.get('saturation'),
            contrast=data.get('contrast'),
            vignette_enabled=data.get('vignette_enabled'),
            vignette_intensity=data.get('vignette_intensity')
        )
        
        self.viewport.update()

    def export_scene(self):
        """Export the current scene to a 3D file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Scene", "", 
            "GLTF Binary (*.glb);;GLTF (*.gltf);;OBJ (*.obj);;All Files (*.*)"
        )
        if not path:
            return
            
        # Gather material data
        # We can get it from the panel or assume the viewport has the latest
        # For now, let's grab from panel via a direct access or signal?
        # Better: The viewport already has the visual state, but we need the raw data.
        # Let's ask the material panel for current state.
        
        # Hack: Just use default or what we can scrape. 
        # Ideally we should store the current material data in RenderingTab.
        # Let's try to get it from the material panel if possible, or just pass empty for now 
        # and let the viewer handle it (it has some state).
        
        # Actually, let's just pass the base color from the viewport if we can, 
        # or better, get it from the material panel.
        
        # For this implementation, we will trust the ModelViewer3D's export_scene 
        # to handle the mesh. We need to pass the material properties.
        # We can access self.material_panel.node_graph.material... but that's complex.
        
        # Let's just trigger the export on the viewport for now.
        
        # Collect basic material info from panel UI controls for simplicity
        mat_data = {
            'base_color': [1.0, 1.0, 1.0] # Default
        }
        # Try to read from panel
        try:
            # This relies on the panel having these attributes
            # We can't easily access them without public getters, but we can try
            pass
        except:
            pass
            
        success = self.viewport.export_scene(path, mat_data)
        if success:
            self.status_message.emit(f"Scene exported to {os.path.basename(path)}")
        else:
            self.status_message.emit("Export failed.")
