"""
Texture Generator Dialog for RenderFox
Allows users to generate textures using AI or load existing ones.
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QSpinBox, QCheckBox, QFileDialog,
    QFrame, QGroupBox, QMessageBox, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap
from ..features.texture_engine import TextureGenerationThread
from ..processing.texture_packer import ChannelPacker
from ..utils.run_teardown import drain_attributes
from .icon_provider import get_icon

class TextureGeneratorDialog(QDialog):
    """
    Dialog for generating textures or loading custom ones.
    """
    
    texture_ready = pyqtSignal(str, str)  # Emits (path, slot_name)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Texture Generator")
        self.setMinimumWidth(500)
        self.generated_image_path = None
        self.thread = None
        self.init_ui()

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Silence a generation in flight and wait for the request to come back.

        The dialog is modal, so the main window cannot be closed under it - but it
        outlives its own `exec()`, because the Rendering tab is its parent, and
        `progress_update` writes the bar and the button's caption while
        `generation_finished` writes the preview. A generation asked for and then
        dismissed is therefore still connected to widgets the close destroys. The engine
        takes its cancellation through `cancel`, which is one of the four spellings the
        helper knows, so the request is made before the wait rather than the wait standing
        in for it. Returns the generations still owed.
        """
        return len(drain_attributes(self, ('thread',), timeout_ms))
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header = QLabel("Create or Load Texture")
        header.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(header)
        
        # Model Selection
        model_group = QGroupBox("AI Model Configuration")
        model_layout = QHBoxLayout(model_group)
        
        self.model_path_input = QLineEdit()
        self.model_path_input.setPlaceholderText("Default (Auto-download)")
        self.model_path_input.setReadOnly(True)
        model_layout.addWidget(self.model_path_input)
        
        self.browse_model_btn = QPushButton("Select File...")
        self.browse_model_btn.clicked.connect(self.browse_model_file)
        model_layout.addWidget(self.browse_model_btn)
        
        self.browse_model_dir_btn = QPushButton("Select Folder...")
        self.browse_model_dir_btn.clicked.connect(self.browse_model_dir)
        model_layout.addWidget(self.browse_model_dir_btn)
        
        layout.addWidget(model_group)
        
        # AI Generation Section
        gen_group = QGroupBox("AI Texture Generation")
        gen_layout = QVBoxLayout(gen_group)
        
        # Prompt
        prompt_layout = QVBoxLayout()
        prompt_layout.addWidget(QLabel("Prompt:"))
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("e.g., rusty metal plate, seamless brick wall, oak wood grain...")
        prompt_layout.addWidget(self.prompt_input)
        gen_layout.addLayout(prompt_layout)
        
        # Settings Row
        settings_layout = QHBoxLayout()
        
        # Mode
        mode_layout = QVBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Offline (Local)", "Online (API)"])
        mode_layout.addWidget(self.mode_combo)
        settings_layout.addLayout(mode_layout)
        
        # Size
        size_layout = QVBoxLayout()
        size_layout.addWidget(QLabel("Size:"))
        self.size_combo = QComboBox()
        self.size_combo.addItems(["512x512", "1024x1024"])
        size_layout.addWidget(self.size_combo)
        settings_layout.addLayout(size_layout)
        
        gen_layout.addLayout(settings_layout)
        
        # Generate Button
        self.generate_btn = QPushButton("Generate Texture")
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #6200ea;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #7c4dff;
            }
        """)
        self.generate_btn.clicked.connect(self.generate_texture)
        gen_layout.addWidget(self.generate_btn)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        gen_layout.addWidget(self.progress_bar)
        
        layout.addWidget(gen_group)
        
        # OR Separator
        or_layout = QHBoxLayout()
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        line1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        or_label = QLabel("OR")
        or_label.setStyleSheet("color: #888; font-weight: bold;")
        
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        line2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        or_layout.addWidget(line1)
        or_layout.addWidget(or_label)
        or_layout.addWidget(line2)
        layout.addLayout(or_layout)
        
        # Manual Load Section
        load_group = QGroupBox("Load Custom Image")
        load_layout = QHBoxLayout(load_group)
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select an image file...")
        self.path_input.setReadOnly(True)
        load_layout.addWidget(self.path_input)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_image)
        load_layout.addWidget(self.browse_btn)
        
        layout.addWidget(load_group)

        # Channel packing is a file operation, not a fake material setting: the
        # source masks stay visible and the resulting PNG is read back by the backend.
        pack_group = QGroupBox("Pack Texture Channels")
        pack_layout = QVBoxLayout(pack_group)
        pack_layout.addWidget(QLabel("Create an ORM or mask texture from equally sized source images."))
        self.channel_inputs = {}
        for channel, label in (("red", "Red / Occlusion"), ("green", "Green / Roughness"),
                               ("blue", "Blue / Metallic"), ("alpha", "Alpha")):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{label}:"))
            field = QLineEdit()
            field.setReadOnly(True)
            field.setPlaceholderText("Optional source image")
            self.channel_inputs[channel] = field
            row.addWidget(field)
            browse = QPushButton("Browse...")
            browse.clicked.connect(lambda checked=False, key=channel: self.browse_channel(key))
            row.addWidget(browse)
            pack_layout.addLayout(row)
        self.pack_channels_btn = QPushButton("Pack Channels to PNG...")
        self.pack_channels_btn.setIcon(get_icon("pipeline"))
        self.pack_channels_btn.clicked.connect(self.pack_channels)
        pack_layout.addWidget(self.pack_channels_btn)
        layout.addWidget(pack_group)
        
        # Footer / Options
        footer_layout = QHBoxLayout()
        
        # Slot Selection
        slot_layout = QHBoxLayout()
        slot_layout.addWidget(QLabel("Apply to Slot:"))
        self.slot_combo = QComboBox()
        self.slot_combo.addItems(["Albedo", "Normal", "Roughness", "Metallic", "Occlusion", "Emissive"])
        slot_layout.addWidget(self.slot_combo)
        footer_layout.addLayout(slot_layout)
        
        footer_layout.addSpacing(20)
        
        self.auto_apply_cb = QCheckBox("Auto-apply")
        self.auto_apply_cb.setChecked(True)
        footer_layout.addWidget(self.auto_apply_cb)
        
        footer_layout.addStretch()
        
        self.use_btn = QPushButton("Use Texture")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self.accept_texture)
        footer_layout.addWidget(self.use_btn)
        
        layout.addLayout(footer_layout)
        
    def browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Texture", "", "Images (*.png *.jpg *.jpeg *.tga *.bmp)"
        )
        if file_path:
            self.path_input.setText(file_path)
            self.generated_image_path = file_path
            self.use_btn.setEnabled(True)
            self.use_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")

    def browse_channel(self, channel):
        """Choose the source for one output component of a packed mask."""
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose {channel.title()} Channel Source", "",
            "Images (*.png *.jpg *.jpeg *.tga *.bmp);;All Files (*.*)")
        if path:
            self.channel_inputs[channel].setText(path)

    def pack_channels(self):
        """Write a channel-packed PNG after the backend validates every input."""
        output, _ = QFileDialog.getSaveFileName(
            self, "Save Packed Texture", "packed_orm.png", "PNG Image (*.png)")
        if not output:
            return
        if not output.lower().endswith('.png'):
            output += '.png'
        sources = {name: field.text().strip() or None
                   for name, field in self.channel_inputs.items()}
        result = ChannelPacker.pack(output, sources)
        if not result.success:
            QMessageBox.warning(self, "Channel Packing", result.message)
            return
        self.generated_image_path = result.output_path
        self.path_input.setText(result.output_path)
        self.use_btn.setEnabled(True)
        QMessageBox.information(self, "Channel Packing", result.message)

    def browse_model_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select AI Model File", "", "Model Files (*.safetensors *.ckpt);;All Files (*.*)"
        )
        if file_path:
            self.model_path_input.setText(file_path)

    def browse_model_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select AI Model Folder")
        if dir_path:
            self.model_path_input.setText(dir_path)

    def generate_texture(self):
        prompt = self.prompt_input.text().strip()
        if not prompt:
            QMessageBox.warning(self, "Missing Prompt", "Please enter a description for the texture.")
            return
            
        # Get Mode
        mode = self.mode_combo.currentText()
        
        # Get settings
        size_str = self.size_combo.currentText()
        width = 512 if "512" in size_str else 1024
        height = width
        
        # Get Model Path
        model_path = self.model_path_input.text()
        if not model_path or model_path == "Default (Auto-download)":
            model_path = None

        # UI State
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generating... (This may take a while)")
        
        # Determine Mode
        engine_mode = "online" if mode == "Online (API)" else "offline"
        
        # Get API Key if needed
        api_key = None
        if engine_mode == "online":
            from PyQt6.QtCore import QSettings
            settings = QSettings("RenderFox", "RenderFox")
            api_key = settings.value("Advanced/api_key", "")
            
            if not api_key:
                QMessageBox.warning(self, "Missing API Key", 
                                  "Please go to Settings > Advanced > AI Configuration and enter your API Key.")
                return

        # Start Thread
        self.thread = TextureGenerationThread(
            prompt, 
            width=width, 
            height=height, 
            model_path=model_path,
            mode=engine_mode,
            api_key=api_key
        )
        self.thread.progress_update.connect(self.update_progress)
        self.thread.generation_finished.connect(self.on_generation_finished)
        self.thread.error_occurred.connect(self.on_generation_error)
        self.thread.start()
        
    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.generate_btn.setText(message)
        
    def on_generation_finished(self, filepath):
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate Texture")
        
        self.generated_image_path = filepath
        self.path_input.setText(filepath)
        self.use_btn.setEnabled(True)
        self.use_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        
        QMessageBox.information(self, "Success", "Texture generated successfully!")
        
        if self.auto_apply_cb.isChecked():
            self.accept_texture()
            
    def on_generation_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate Texture")
        QMessageBox.critical(self, "Generation Failed", f"Error: {error_msg}")

    def accept_texture(self):
        if self.generated_image_path and os.path.exists(self.generated_image_path):
            slot = self.slot_combo.currentText().lower()
            self.texture_ready.emit(self.generated_image_path, slot)
            self.accept()
