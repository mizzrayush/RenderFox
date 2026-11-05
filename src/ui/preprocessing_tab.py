"""
Pre-processing tab for LOD generation, texture optimization, scene optimization,
model extraction, and format conversion.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QCheckBox, QSlider, QLabel, QComboBox, QPushButton,
                             QSpinBox, QDoubleSpinBox, QFormLayout, QTextEdit,
                             QFileDialog, QMessageBox, QProgressDialog, QLineEdit,
                             QListWidget, QListWidgetItem, QSplitter, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog,
                             QScrollArea, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from ..processing.lod_generator import LODGenerator, LODSettings, is_supported_format
from ..processing.model_extractor import ModelExtractor, ExtractedModel
from ..processing.format_converter import FormatConverter, SupportedFormat, get_format_info
from .model_viewer import ModelViewerWidget
from ..processing.texture_baker import TextureBakerThread
import os


class LODPreviewThread(QThread):
    """Thread for generating LOD previews."""
    
    preview_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, file_path, settings):
        super().__init__()
        self.file_path = file_path
        self.settings = settings
    
    def run(self):
        try:
            generator = LODGenerator(self.settings)
            # Use the correct preview method
            if hasattr(generator, 'preview_lod_reduction'):
                preview = generator.preview_lod_reduction(self.file_path)
            else:
                # Fallback only if method missing
                preview = []
            self.preview_ready.emit(preview)
        except Exception as e:
            self.error_occurred.emit(str(e))
class ModelExtractionThread(QThread):
    """Thread for extracting models from scenes without blocking UI."""
    
    extraction_complete = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, file_path, min_faces):
        super().__init__()
        self.file_path = file_path
        self.min_faces = min_faces
    
    def run(self):
        try:
            extractor = ModelExtractor()
            models = extractor.extract_from_scene(self.file_path, self.min_faces)
            self.extraction_complete.emit(models)
        except Exception as e:
            self.error_occurred.emit(str(e))

class FormatConversionThread(QThread):
    """Thread for batch format conversion."""
    
    # (what converted, what did not). One list before: convert_file() answers with a
    # dict, and a dict is truthy even when it says success=False, so every failure was
    # counted and shown as a converted file.
    conversion_complete = pyqtSignal(list, list)
    progress_update = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, input_files, output_dir, target_format, options=None, output_mode=0,
                 generate_lods=False):
        super().__init__()
        self.input_files = input_files
        self.output_dir = output_dir
        self.target_format = target_format
        self.options = options
        self.output_mode = output_mode
        self.generate_lods = generate_lods
    
    def _output_dir_for(self, input_file):
        if self.output_dir:
            return self.output_dir
        out_dir = os.path.dirname(input_file)
        if self.output_mode == 1: # _Processed
            out_dir = os.path.join(out_dir, "_Processed")
            if not os.path.exists(out_dir):
                try:
                    os.makedirs(out_dir)
                except OSError:
                    pass
        return out_dir

    def run(self):
        try:
            converter = FormatConverter()
            converted = []
            failed = []
            
            for i, input_file in enumerate(self.input_files):
                self.progress_update.emit(i, f"Converting {os.path.basename(input_file)}...")
                
                base_name = os.path.splitext(os.path.basename(input_file))[0]
                out_dir = self._output_dir_for(input_file)
                
                if self.generate_lods:
                    # "Generate LODs during conversion" used to be a checkbox nothing
                    # read; when it is ticked, the LOD chain is the job's output.
                    paths = converter.convert_with_lod_generation(
                        input_file, out_dir, self.target_format, options=self.options)
                    entry = {'input': input_file,
                             'output': ', '.join(os.path.basename(p) for p in paths),
                             'method': f'lod + {os.path.splitext(paths[0])[1].lstrip(".") if paths else "?"}'}
                    if paths:
                        converted.append(entry)
                    else:
                        entry['error'] = 'LOD generation produced no files'
                        failed.append(entry)
                    continue

                output_file = os.path.join(out_dir, f"{base_name}{self.target_format.value}")
                result = converter.convert_file(input_file, output_file, self.options)
                entry = {'input': input_file, 'output': output_file,
                         'method': result.get('method') or 'nothing'}
                entry['options_skipped'] = result.get('options_skipped') or []
                if result.get('success'):
                    converted.append(entry)
                else:
                    entry['error'] = result.get('message', 'Conversion failed')
                    failed.append(entry)
            
            self.conversion_complete.emit(converted, failed)
        except Exception as e:
            self.error_occurred.emit(str(e))

class PreProcessingTab(QWidget):
    """Enhanced pre-processing tab with model extraction, format conversion, and 3D preview."""
    
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.extracted_models = []
        self.lod_generator = LODGenerator()
        self.model_extractor = ModelExtractor()
        self.format_converter = FormatConverter()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the enhanced pre-processing UI."""
        layout = QHBoxLayout(self)
        
        # Create splitter for left panel and 3D viewer
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel with tabs
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(4, 4, 4, 4)
        
        # File Selection Group
        file_group = QGroupBox("Input File")
        file_layout = QHBoxLayout(file_group)
        file_layout.setSpacing(8)
        
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("Select a 3D model or scene file...")
        self.browse_file_btn = QPushButton("Browse...")
        self.browse_file_btn.clicked.connect(self.browse_file)
        
        file_layout.addWidget(self.file_path)
        file_layout.addWidget(self.browse_file_btn)
        
        left_layout.addWidget(file_group)
        
        # Output Settings
        self.output_settings_group = self.create_output_settings()
        left_layout.addWidget(self.output_settings_group)
        
        # Tabbed interface for different operations
        self.operation_tabs = QTabWidget()
        left_layout.addWidget(self.operation_tabs)
        
        # Tab 1: LOD Generation
        self.create_lod_tab()
        
        # Tab 2: Model Extraction
        self.create_extraction_tab()
        
        # Tab 3: Format Conversion
        self.create_conversion_tab()
        
        # Tab 4: Advanced Processing
        self.create_advanced_tab()

        # Tab 5: Texture Baking
        self.create_baking_tab()

        # There is no sixth tab. A batch pane here stamped every task completed and
        # wrote no file; Automation's Batch Operations is the one that runs, so
        # `library_tab` sends a file there instead.

        # Wrap left panel in scroll area so small screens never compress UI
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_panel)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        splitter.addWidget(left_scroll)
        
        # Right panel: 3D Model Viewer
        self.model_viewer = ModelViewerWidget()
        splitter.addWidget(self.model_viewer)
        
        # Set splitter proportions (50% left, 50% right)
        splitter.setSizes([550, 550])
    
    def load_model(self, file_path):
        """Load a model for processing."""
        if os.path.exists(file_path):
            self.current_file = file_path
            if hasattr(self, 'file_path'):
                self.file_path.setText(file_path)
            
            # Load into 3D viewer
            if hasattr(self, 'model_viewer'):
                self.model_viewer.load_model(file_path)
            # Trigger analysis or update UI as needed
            # self.update_file_info()

    def create_output_settings(self):
        """Create output settings group."""
        group = QGroupBox("Output Settings")
        layout = QVBoxLayout()
        
        self.output_folder_combo = QComboBox()
        self.output_folder_combo.addItems(["Same Folder (Default)", "Create '_Processed' Subfolder"])
        self.output_folder_combo.setToolTip("Choose where to save processed files.")
        
        layout.addWidget(QLabel("Save Location:"))
        layout.addWidget(self.output_folder_combo)
        
        group.setLayout(layout)
        return group

    def get_output_directory(self, original_path):
        """Generate output directory based on settings."""
        directory = os.path.dirname(original_path)
        
        if self.output_folder_combo.currentIndex() == 1: # _Processed Subfolder
            directory = os.path.join(directory, "_Processed")
            if not os.path.exists(directory):
                try:
                    os.makedirs(directory)
                except OSError:
                    pass
        
        return directory

    def create_lod_tab(self):
        """Create the LOD generation tab."""
        lod_widget = QWidget()
        layout = QVBoxLayout(lod_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # LOD Presets Group
        presets_group = QGroupBox("LOD Presets")
        presets_layout = QFormLayout(presets_group)
        presets_layout.setVerticalSpacing(10)
        presets_layout.setHorizontalSpacing(16)
        
        self.lod_preset = QComboBox()
        self.lod_preset.addItems([
            "Custom", "Game Assets", "Web/Mobile", "Architectural", "Product Viz", "VR/AR"
        ])
        self.lod_preset.currentTextChanged.connect(self.apply_lod_preset)
        presets_layout.addRow("Preset:", self.lod_preset)
        
        layout.addWidget(presets_group)
        
        # LOD Generation Group
        lod_group = QGroupBox("LOD Generation Settings")
        lod_layout = QFormLayout(lod_group)
        lod_layout.setVerticalSpacing(12)
        lod_layout.setHorizontalSpacing(16)
        
        self.enable_lod = QCheckBox("Generate LODs")
        self.enable_lod.toggled.connect(self.toggle_lod_controls)
        lod_layout.addRow(self.enable_lod)
        
        self.lod_levels = QSpinBox()
        self.lod_levels.setRange(1, 8)  # Increased max levels
        self.lod_levels.setValue(3)
        self.lod_levels.valueChanged.connect(self.update_lod_level_inputs)
        lod_layout.addRow("LOD Levels:", self.lod_levels)
        
        # Dynamic LOD Ratios Container
        self.lod_ratios_container = QWidget()
        self.lod_ratios_layout = QFormLayout(self.lod_ratios_container)
        self.lod_ratios_layout.setVerticalSpacing(10)
        self.lod_ratios_layout.setHorizontalSpacing(16)
        self.lod_ratios_layout.setContentsMargins(0, 4, 0, 4)
        lod_layout.addRow(self.lod_ratios_container)
        
        self.ratio_inputs = []  # Store references to spinboxes
        
        # LOD Preview area
        self.lod_preview = QTextEdit()
        self.lod_preview.setMinimumHeight(100)
        self.lod_preview.setMaximumHeight(180)
        self.lod_preview.setPlaceholderText("LOD preview will appear here when a file is selected...")
        lod_layout.addRow("Preview:", self.lod_preview)
        
        layout.addWidget(lod_group)
        
        # LOD Actions
        lod_actions = QHBoxLayout()
        self.generate_lods_btn = QPushButton("Generate LODs")
        self.generate_lods_btn.clicked.connect(self.generate_lods)
        self.generate_lods_btn.setEnabled(False)
        
        lod_actions.addWidget(self.generate_lods_btn)
        lod_actions.addStretch()
        
        layout.addLayout(lod_actions)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(lod_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.operation_tabs.addTab(scroll, "LOD Generation")
        
        # Initialize inputs
        self.update_lod_level_inputs(3)
        
        # Initially disable LOD controls
        self.toggle_lod_controls(False)

    def update_lod_level_inputs(self, count):
        """Update the number of ratio inputs based on LOD levels."""
        # Clear existing inputs
        while self.lod_ratios_layout.count():
            item = self.lod_ratios_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.ratio_inputs = []
        
        # Create new inputs
        for i in range(count):
            spin = QDoubleSpinBox()
            spin.setRange(0.01, 1.0)
            spin.setSingleStep(0.1)
            
            # Default values decreasing
            default_val = max(0.1, 1.0 - ((i + 1) * (1.0 / (count + 1))))
            spin.setValue(float(f"{default_val:.2f}"))
            
            spin.valueChanged.connect(self.update_lod_preview)
            self.lod_ratios_layout.addRow(f"Level {i} Ratio:", spin)
            self.ratio_inputs.append(spin)
            
        self.update_lod_preview()
    
    def create_extraction_tab(self):
        """Create the model extraction tab."""
        extract_widget = QWidget()
        layout = QVBoxLayout(extract_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Extraction Settings
        extract_group = QGroupBox("Extraction Settings")
        extract_layout = QFormLayout(extract_group)
        extract_layout.setVerticalSpacing(12)
        extract_layout.setHorizontalSpacing(16)
        
        self.min_faces_spin = QSpinBox()
        self.min_faces_spin.setRange(1, 10000)
        self.min_faces_spin.setValue(100)
        extract_layout.addRow("Min Faces:", self.min_faces_spin)
        
        extract_btn = QPushButton("Extract Models")
        extract_btn.clicked.connect(self.extract_models)
        extract_layout.addRow(extract_btn)
        
        layout.addWidget(extract_group)
        
        # Extracted Models List
        models_group = QGroupBox("Extracted Models")
        models_layout = QVBoxLayout(models_group)
        
        self.models_table = QTableWidget()
        self.models_table.setColumnCount(5)
        self.models_table.setHorizontalHeaderLabels([
            "Name", "Faces", "Vertices", "Volume", "Selected"
        ])
        self.models_table.horizontalHeader().setStretchLastSection(True)
        self.models_table.setMinimumHeight(160)
        models_layout.addWidget(self.models_table)
        
        # Model actions
        model_actions = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_models)
        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(self.select_no_models)
        self.export_selected_btn = QPushButton("Export Selected")
        self.export_selected_btn.clicked.connect(self.export_selected_models)
        
        model_actions.addWidget(self.select_all_btn)
        model_actions.addWidget(self.select_none_btn)
        model_actions.addWidget(self.export_selected_btn)
        model_actions.addStretch()
        
        models_layout.addLayout(model_actions)
        layout.addWidget(models_group)
        
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(extract_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.operation_tabs.addTab(scroll, "Model Extraction")
    
    def create_conversion_tab(self):
        """Create the format conversion tab."""
        convert_widget = QWidget()
        layout = QVBoxLayout(convert_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Format Selection
        format_group = QGroupBox("Format Conversion")
        format_layout = QFormLayout(format_group)
        format_layout.setVerticalSpacing(12)
        format_layout.setHorizontalSpacing(16)
        
        self.target_format = QComboBox()
        for fmt in SupportedFormat:
            format_info = get_format_info().get(fmt.value, {})
            display_name = f"{fmt.value.upper()} - {format_info.get('name', 'Unknown')}"
            self.target_format.addItem(display_name, fmt)
        format_layout.addRow("Target Format:", self.target_format)
        
        # Conversion Options
        self.scale_input = QDoubleSpinBox()
        self.scale_input.setRange(0.01, 100.0)
        self.scale_input.setValue(1.0)
        self.scale_input.setSingleStep(0.1)
        format_layout.addRow("Scale Factor:", self.scale_input)
        
        self.center_model = QCheckBox("Center Model")
        format_layout.addRow(self.center_model)
        
        self.normalize_size = QCheckBox("Normalize to Unit Size")
        format_layout.addRow(self.normalize_size)
        
        self.repair_mesh = QCheckBox("Repair Mesh")
        format_layout.addRow(self.repair_mesh)
        
        # Batch conversion with LOD
        self.convert_with_lod = QCheckBox("Generate LODs during conversion")
        format_layout.addRow(self.convert_with_lod)
        
        layout.addWidget(format_group)
        
        # Batch File Selection
        batch_group = QGroupBox("Batch Conversion")
        batch_layout = QVBoxLayout(batch_group)
        
        file_selection_layout = QHBoxLayout()
        self.add_files_btn = QPushButton("Add Files")
        self.add_files_btn.clicked.connect(self.add_conversion_files)
        self.clear_files_btn = QPushButton("Clear List")
        self.clear_files_btn.clicked.connect(self.clear_conversion_files)
        
        file_selection_layout.addWidget(self.add_files_btn)
        file_selection_layout.addWidget(self.clear_files_btn)
        file_selection_layout.addStretch()
        
        batch_layout.addLayout(file_selection_layout)
        
        self.conversion_files_list = QListWidget()
        self.conversion_files_list.setMinimumHeight(140)
        batch_layout.addWidget(self.conversion_files_list)
        
        # Conversion Actions
        convert_actions = QHBoxLayout()
        self.convert_batch_btn = QPushButton("Convert All")
        self.convert_batch_btn.clicked.connect(self.convert_batch_files)
        
        convert_actions.addWidget(self.convert_batch_btn)
        convert_actions.addStretch()
        
        batch_layout.addLayout(convert_actions)
        layout.addWidget(batch_group)
        
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(convert_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.operation_tabs.addTab(scroll, "Format Conversion")
    
    def create_advanced_tab(self):
        """Create the advanced processing tab."""
        advanced_widget = QWidget()
        layout = QVBoxLayout(advanced_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Texture Optimization Group
        texture_group = QGroupBox("Texture Optimization")
        texture_layout = QFormLayout(texture_group)
        texture_layout.setVerticalSpacing(12)
        texture_layout.setHorizontalSpacing(16)
        
        self.enable_texture_opt = QCheckBox("Optimize Textures")
        texture_layout.addRow(self.enable_texture_opt)
        
        self.texture_quality = QSlider(Qt.Orientation.Horizontal)
        self.texture_quality.setRange(1, 100)
        self.texture_quality.setValue(80)
        self.quality_label = QLabel("80%")
        self.texture_quality.valueChanged.connect(
            lambda v: self.quality_label.setText(f"{v}%"))
        
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(self.texture_quality)
        quality_layout.addWidget(self.quality_label)
        texture_layout.addRow("Quality:", quality_layout)
        
        self.texture_format = QComboBox()
        self.texture_format.addItems(["PNG", "JPEG", "WEBP", "Original"])
        texture_layout.addRow("Convert to:", self.texture_format)
        
        layout.addWidget(texture_group)
        
        # Scene Optimization Group
        scene_group = QGroupBox("Scene Optimization")
        scene_layout = QFormLayout(scene_group)
        scene_layout.setVerticalSpacing(12)
        scene_layout.setHorizontalSpacing(16)
        
        self.enable_scene_opt = QCheckBox("Optimize Scene")
        scene_layout.addRow(self.enable_scene_opt)
        
        self.remove_hidden = QCheckBox("Remove Hidden Objects")
        self.remove_hidden.setChecked(True)
        scene_layout.addRow(self.remove_hidden)
        
        self.merge_static = QCheckBox("Merge Static Meshes")
        scene_layout.addRow(self.merge_static)
        
        self.simplify_materials = QCheckBox("Simplify Materials")
        scene_layout.addRow(self.simplify_materials)
        
        layout.addWidget(scene_group)
        
        # Preview button
        preview_btn = QPushButton("Preview All Optimizations")
        preview_btn.clicked.connect(self.preview_optimizations)
        layout.addWidget(preview_btn)
        
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(advanced_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.operation_tabs.addTab(scroll, "Advanced")

    def create_baking_tab(self):
        """Create the texture baking tab."""
        baking_widget = QWidget()
        layout = QVBoxLayout(baking_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Input Selection
        input_group = QGroupBox("Baking Inputs")
        input_layout = QFormLayout(input_group)
        input_layout.setVerticalSpacing(12)
        input_layout.setHorizontalSpacing(16)
        
        self.high_poly_path = QLineEdit()
        self.high_poly_path.setPlaceholderText("Select High-Poly Mesh...")
        high_poly_btn = QPushButton("Browse...")
        high_poly_btn.clicked.connect(self.browse_high_poly)
        
        hp_layout = QHBoxLayout()
        hp_layout.addWidget(self.high_poly_path)
        hp_layout.addWidget(high_poly_btn)
        input_layout.addRow("High Poly:", hp_layout)
        
        self.low_poly_path = QLineEdit()
        self.low_poly_path.setPlaceholderText("Select Low-Poly Mesh (or use current input)...")
        low_poly_btn = QPushButton("Browse...")
        low_poly_btn.clicked.connect(self.browse_low_poly)
        
        lp_layout = QHBoxLayout()
        lp_layout.addWidget(self.low_poly_path)
        lp_layout.addWidget(low_poly_btn)
        input_layout.addRow("Low Poly:", lp_layout)
        
        layout.addWidget(input_group)
        
        # Baking Settings
        settings_group = QGroupBox("Baking Settings")
        settings_layout = QFormLayout(settings_group)
        settings_layout.setVerticalSpacing(12)
        settings_layout.setHorizontalSpacing(16)
        
        self.bake_res = QComboBox()
        self.bake_res.addItems(["512", "1024", "2048", "4096"])
        self.bake_res.setCurrentText("2048")
        settings_layout.addRow("Resolution:", self.bake_res)
        
        self.bake_normals = QCheckBox("Normal Map")
        self.bake_normals.setChecked(True)
        settings_layout.addRow(self.bake_normals)
        
        self.bake_diffuse = QCheckBox("Diffuse / Color Map")
        self.bake_diffuse.setChecked(True)
        settings_layout.addRow(self.bake_diffuse)
        
        self.bake_ao = QCheckBox("Ambient Occlusion")
        self.bake_ao.setChecked(True)
        settings_layout.addRow(self.bake_ao)
        
        layout.addWidget(settings_group)
        
        # Actions
        action_layout = QHBoxLayout()
        self.bake_btn = QPushButton("Bake Textures")
        self.bake_btn.clicked.connect(self.start_baking)
        action_layout.addWidget(self.bake_btn)
        
        layout.addLayout(action_layout)
        layout.addStretch()
        
        scroll = QScrollArea()
        scroll.setWidget(baking_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.operation_tabs.addTab(scroll, "Texture Baking")

    def browse_high_poly(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select High Poly Mesh", "", "3D Models (*.obj *.ply *.stl *.fbx *.glb *.gltf)")
        if path:
            self.high_poly_path.setText(path)
            if hasattr(self, 'viewer') and self.viewer:
                self.viewer.load_model(path)

    def browse_low_poly(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Low Poly Mesh", "", "3D Models (*.obj *.ply *.stl *.fbx *.glb *.gltf)")
        if path:
            self.low_poly_path.setText(path)
            if hasattr(self, 'viewer') and self.viewer:
                self.viewer.load_model(path)

    def start_baking(self):
        high_poly = self.high_poly_path.text()
        low_poly = self.low_poly_path.text()
        
        # Auto-fill low poly if empty and main file is loaded
        if not low_poly and self.current_file:
            low_poly = self.current_file
            self.low_poly_path.setText(low_poly)
            
        if not high_poly or not low_poly:
            QMessageBox.warning(self, "Missing Inputs", "Please select both High Poly and Low Poly meshes.")
            return
            
        output_dir = self.get_output_directory(low_poly)
        resolution = int(self.bake_res.currentText())
        
        options = {
            'normals': self.bake_normals.isChecked(),
            'diffuse': self.bake_diffuse.isChecked(),
            'ao': self.bake_ao.isChecked()
        }
        
        self.progress_dialog = QProgressDialog("Baking Textures...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()
        
        self.baking_thread = TextureBakerThread(high_poly, low_poly, output_dir, resolution, options)
        self.baking_thread.progress_update.connect(self.update_baking_progress)
        self.baking_thread.baking_complete.connect(self.baking_finished)
        self.baking_thread.error_occurred.connect(self.baking_error)
        self.baking_thread.start()
        
    def update_baking_progress(self, value, message):
        self.progress_dialog.setValue(value)
        self.progress_dialog.setLabelText(message)
        
    def baking_finished(self, success, results):
        self.progress_dialog.close()
        if success:
            msg = "Baking Successful!\n\nGenerated Maps:\n"
            for type_, path in results.items():
                msg += f"- {type_.title()}: {os.path.basename(path)}\n"
            QMessageBox.information(self, "Baking Complete", msg)
        else:
            QMessageBox.warning(self, "Baking Failed", "See error log for details.")

    def baking_error(self, message):
        self.progress_dialog.close()
        QMessageBox.critical(self, "Baking Error", f"An error occurred:\n{message}")
    def browse_file(self):
        """Browse for input 3D model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select 3D Model or Scene File",
            "", "3D Model Files (*.obj *.ply *.stl *.off *.dae *.gltf *.glb *.3mf *.fbx);;All Files (*)")
        
        if file_path:
            self.file_path.setText(file_path)
            self.current_file = file_path
            self.generate_lods_btn.setEnabled(True)
            
            # Load in 3D viewer
            self.model_viewer.load_model(file_path)
            
            # Update LOD preview if enabled
            if self.enable_lod.isChecked():
                self.update_lod_preview()
    
    def toggle_lod_controls(self, enabled):
        """Enable/disable LOD controls based on checkbox state."""
        # Keep controls enabled for editing
        self.lod_levels.setEnabled(True)
        self.lod_preview.setEnabled(True)
        
        for spin in self.ratio_inputs:
            spin.setEnabled(True)
        
        if self.current_file:
            self.update_lod_preview()
    
    def update_lod_preview(self):
        """Update the LOD preview based on current settings."""
        if not self.current_file:
            self.lod_preview.clear()
            return
        
        # Collect ratios from dynamic inputs
        ratios = [spin.value() for spin in self.ratio_inputs]
        
        # Create settings from UI
        settings = LODSettings(
            levels=self.lod_levels.value(),
            custom_ratios=ratios
        )
        
        # Start preview thread
        self.preview_thread = LODPreviewThread(self.current_file, settings)
        self.preview_thread.preview_ready.connect(self.display_lod_preview)
        self.preview_thread.error_occurred.connect(self.show_preview_error)
        self.preview_thread.start()
    
    def display_lod_preview(self, preview_data):
        """Display the LOD preview data."""
        if not preview_data:
            return
        
        # Handle error payloads
        first = preview_data[0]
        if isinstance(first, dict) and "error" in first:
            self.show_preview_error(first.get("error", "Unknown preview error"))
            return
        
        preview_text = "LOD Generation Preview:\n\n"
        for data in preview_data:
            # Safely extract values with sensible defaults
            level = data.get("level", "?")
            ratio = data.get("ratio", None)
            original_faces = data.get("original_faces", 0)
            target_faces = data.get("target_faces", 0)
            reduction = data.get("reduction_percentage")
            if reduction is None:
                reduction = data.get("face_reduction_percentage")
            if reduction is None and isinstance(ratio, (int, float)):
                reduction = (1 - ratio) * 100
            
            ratio_text = f"{ratio:.1%}" if isinstance(ratio, (int, float)) else "N/A"
            reduction_text = f"{reduction:.1f}%" if isinstance(reduction, (int, float)) else "N/A"
            
            preview_text += (
                f"LOD{level}: {target_faces:,} faces ("
                f"{ratio_text} of original, {reduction_text} reduction)\n"
            )
        
        self.lod_preview.setPlainText(preview_text)
    
    def show_preview_error(self, error_message):
        """Show preview error in the preview area."""
        self.lod_preview.setPlainText(f"Preview Error: {error_message}")
    
    def generate_lods(self):
        """Generate LOD files from the current input."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a 3D model file first.")
            return
        
        if not self.enable_lod.isChecked():
            QMessageBox.information(self, "LOD Generation Disabled",
                                   "Please enable LOD generation first.")
            return
        
        # Get output directory
        output_dir = self.get_output_directory(self.current_file)
        
        # Collect ratios from dynamic inputs
        ratios = [spin.value() for spin in self.ratio_inputs]
        
        # Create settings from UI
        settings = LODSettings(
            levels=self.lod_levels.value(),
            custom_ratios=ratios
        )
        
        # Show progress dialog
        progress = QProgressDialog("Generating LOD files...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        try:
            # Generate LODs
            generator = LODGenerator(settings)
            generated_files = generator.generate_lods(self.current_file, output_dir)
            
            progress.close()
            
            # Show success message
            if generated_files:
                files_list = "\n".join([os.path.basename(f) for f in generated_files])
                QMessageBox.information(self, "LOD Generation Complete",
                                       f"Successfully generated {len(generated_files)} LOD files:\n\n{files_list}")
            else:
                QMessageBox.warning(self, "LOD Generation Failed",
                                   "No LOD files were generated. Check the console for errors.")
                
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "LOD Generation Error",
                               f"Failed to generate LODs: {str(e)}")
    
    def apply_lod_preset(self, preset_name: str):
        """Apply predefined LOD preset configurations."""
        # Presets define levels and a list of ratios
        presets = {
            "Game Assets": {"levels": 4, "ratios": [0.75, 0.5, 0.25, 0.1]},
            "Web/Mobile": {"levels": 3, "ratios": [0.6, 0.3, 0.1]},
            "Architectural": {"levels": 3, "ratios": [0.9, 0.7, 0.4]},
            "Product Viz": {"levels": 2, "ratios": [0.8, 0.5]},
            "VR/AR": {"levels": 4, "ratios": [0.7, 0.4, 0.15, 0.05]}
        }
        
        if preset_name == "Custom":
            self.lod_levels.setEnabled(True)
            # Enable all current inputs
            for spin in self.ratio_inputs:
                spin.setEnabled(True)
            return

        if preset_name in presets:
            preset = presets[preset_name]
            # Set levels first, which regenerates the inputs
            self.lod_levels.setValue(preset["levels"])
            
            # Now set the values
            ratios = preset["ratios"]
            # Ensure we don't go out of bounds if preset mismatch
            for i, spin in enumerate(self.ratio_inputs):
                if i < len(ratios):
                    spin.setValue(ratios[i])
            
            if self.current_file:
                self.update_lod_preview()
    
    def extract_models(self):
        """Extract individual models from the current scene."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a scene file first.")
            return
        
        min_faces = self.min_faces_spin.value()
        
        # Show progress dialog
        progress = QProgressDialog("Extracting models from scene...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        # Start extraction thread
        self.extraction_thread = ModelExtractionThread(self.current_file, min_faces)
        self.extraction_thread.extraction_complete.connect(self.display_extracted_models)
        self.extraction_thread.error_occurred.connect(self.show_extraction_error)
        self.extraction_thread.finished.connect(progress.close)
        self.extraction_thread.start()
    
    def display_extracted_models(self, models: list):
        """Display the extracted models in the table."""
        self.extracted_models = models
        self.models_table.setRowCount(len(models))
        
        for row, model in enumerate(models):
            # Name
            self.models_table.setItem(row, 0, QTableWidgetItem(model.name))
            
            # Faces
            self.models_table.setItem(row, 1, QTableWidgetItem(f"{model.face_count:,}"))
            
            # Vertices
            self.models_table.setItem(row, 2, QTableWidgetItem(f"{model.vertex_count:,}"))
            
            # Volume
            volume_text = f"{model.volume:.2f}" if model.volume > 0 else "N/A"
            self.models_table.setItem(row, 3, QTableWidgetItem(volume_text))
            
            # Selected checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self.models_table.setCellWidget(row, 4, checkbox)
        
        # Auto-resize columns
        self.models_table.resizeColumnsToContents()
    
    def show_extraction_error(self, error_message: str):
        """Show extraction error message."""
        QMessageBox.warning(self, "Model Extraction Error", 
                           f"Failed to extract models: {error_message}")
    
    def select_all_models(self):
        """Select all extracted models."""
        for row in range(self.models_table.rowCount()):
            checkbox = self.models_table.cellWidget(row, 4)
            if checkbox:
                checkbox.setChecked(True)
    
    def select_no_models(self):
        """Deselect all extracted models."""
        for row in range(self.models_table.rowCount()):
            checkbox = self.models_table.cellWidget(row, 4)
            if checkbox:
                checkbox.setChecked(False)
    
    def export_selected_models(self):
        """Export the selected models."""
        selected_models = []
        for row in range(self.models_table.rowCount()):
            checkbox = self.models_table.cellWidget(row, 4)
            if checkbox and checkbox.isChecked():
                selected_models.append(self.extracted_models[row])
        
        if not selected_models:
            QMessageBox.information(self, "No Models Selected",
                                   "Please select at least one model to export.")
            return
        
        # Get output directory
        output_dir = self.get_output_directory(self.current_file)
        
        # Get export format
        format_choice, ok = QInputDialog.getItem(
            self, "Export Format", "Choose export format:",
            [fmt.value.upper() for fmt in SupportedFormat], 0, False)
        
        if not ok:
            return
        
        format_ext = f".{format_choice.lower()}"
        
        try:
            exported_files = self.model_extractor.export_selected_models(
                selected_models, output_dir, format_ext)
            
            QMessageBox.information(self, "Export Complete",
                                   f"Successfully exported {len(exported_files)} models.")
        except Exception as e:
            QMessageBox.critical(self, "Export Error",
                               f"Failed to export models: {str(e)}")
    
    def add_conversion_files(self):
        """Add files to the batch conversion list."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Files for Batch Conversion",
            "", "3D Model Files (*.obj *.ply *.stl *.off *.dae *.gltf *.glb *.3mf *.fbx);;All Files (*)")

        for file_path in files:
            if self.format_converter.is_format_supported(file_path):
                self.conversion_files_list.addItem(file_path)
        self._refresh_target_availability()

    def clear_conversion_files(self):
        """Clear the conversion files list."""
        self.conversion_files_list.clear()
        self._refresh_target_availability()

    def _refresh_target_availability(self):
        """Grey out the targets no library installed here can write from the loaded files.

        The picker listed every SupportedFormat whatever was installed, so a machine
        without an assimp build was still offered FBX and the whole batch came back as
        failures with the reason buried in a results dialog.
        """
        sources = {os.path.splitext(self.conversion_files_list.item(i).text())[1].lower()
                   for i in range(self.conversion_files_list.count())}
        model = self.target_format.model()
        if model is None:
            return

        for index in range(self.target_format.count()):
            fmt = self.target_format.itemData(index)
            blocker = None
            for source in sorted(sources):
                if not self.format_converter.can_convert(source, fmt.value):
                    blocker = self.format_converter.conversion_blocker(source, fmt.value)
                    break
            model.item(index).setEnabled(blocker is None)
            self.target_format.setItemData(index, blocker or '', Qt.ItemDataRole.ToolTipRole)

        current = self.target_format.currentIndex()
        if current >= 0 and not model.item(current).isEnabled():
            for index in range(self.target_format.count()):
                if model.item(index).isEnabled():
                    self.target_format.setCurrentIndex(index)
                    break
    
    def convert_batch_files(self):
        """Convert all files in the batch conversion list."""
        if self.conversion_files_list.count() == 0:
            QMessageBox.information(self, "No Files",
                                   "Please add files to convert first.")
            return
        
        # Get output directory
        output_dir = None
        
        # Get selected target format
        target_format = self.target_format.currentData()
        
        # Prepare conversion options
        options = {
            'scale': self.scale_input.value(),
            'center': self.center_model.isChecked(),
            'normalize': self.normalize_size.isChecked(),
            'repair': self.repair_mesh.isChecked(),
            'remove_duplicates': True
        }
        
        # Collect input files
        input_files = []
        for i in range(self.conversion_files_list.count()):
            input_files.append(self.conversion_files_list.item(i).text())
        
        # Show progress dialog
        progress = QProgressDialog("Converting files...", "Cancel", 0, len(input_files), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        # Start conversion thread
        output_mode = self.output_folder_combo.currentIndex()
        self.conversion_thread = FormatConversionThread(
            input_files, output_dir, target_format, options, output_mode,
            generate_lods=self.convert_with_lod.isChecked())
        self.conversion_thread.conversion_complete.connect(
            lambda converted, failed: self.show_conversion_complete(converted, failed, progress))
        self.conversion_thread.progress_update.connect(
            lambda i, msg: self.update_conversion_progress(progress, i, msg))
        self.conversion_thread.error_occurred.connect(
            lambda error: self.show_conversion_error(error, progress))
        self.conversion_thread.start()
    
    def update_conversion_progress(self, progress_dialog, current, message):
        """Update conversion progress."""
        progress_dialog.setValue(current)
        progress_dialog.setLabelText(message)
    
    def show_conversion_complete(self, converted_files, failed_files, progress_dialog):
        """Show the results the conversion actually reported."""
        progress_dialog.close()
        
        # The old version zipped the successes against the whole input list, so a row
        # only lined up when nothing failed, and 'method' was the literal
        # 'format_converter' rather than the library that did the work.
        errors = [f"{entry['input']}: {entry.get('error', 'Conversion failed')}"
                  for entry in failed_files]
        for entry in converted_files:
            if entry.get('options_skipped'):
                errors.append(f"{entry['input']}: written without "
                              f"{', '.join(entry['options_skipped'])} "
                              f"- the {entry.get('method', 'library')} used cannot apply them")
        
        results = {
            'total_files': len(converted_files) + len(failed_files),
            'successful': converted_files,
            'failed': failed_files,
            'errors': errors
        }
        
        # Show the new results dialog
        from src.ui.conversion_results_dialog import show_conversion_results
        show_conversion_results(results, self)

    def show_conversion_error(self, error_message, progress_dialog):
        """Show conversion error message."""
        progress_dialog.close()
        
        # Get the actual input files from the list widget
        input_files = []
        for i in range(self.conversion_files_list.count()):
            input_files.append(self.conversion_files_list.item(i).text())
        
        # Create results dictionary for failed conversion
        results = {
            'total_files': len(input_files),
            'successful': [],
            'failed': [{'input': f, 'output': None, 'error': error_message} 
                      for f in input_files],
            'errors': [error_message]
        }
        
        # Show the new results dialog
        from src.ui.conversion_results_dialog import show_conversion_results
        show_conversion_results(results, self)
    
    def preview_optimizations(self):
        """Preview all optimizations that will be applied."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a 3D model file first.")
            return
        
        # Analyze the current file
        try:
            analysis = self.lod_generator.analyze_mesh_quality(self.current_file)
            
            if "error" in analysis:
                QMessageBox.warning(self, "Analysis Error", analysis["error"])
                return
            
            # Show analysis results
            info_text = f"""Mesh Analysis for: {os.path.basename(self.current_file)}

Original Mesh Statistics:
• Vertices: {analysis['vertices']:,}
• Faces: {analysis['faces']:,}
• Edges: {analysis['edges']:,}
• Surface Area: {analysis['surface_area']:.2f}
• Is Watertight: {analysis['is_watertight']}
• Winding Consistent: {analysis['is_winding_consistent']}

Optimizations Enabled:
• LOD Generation: {'Yes' if self.enable_lod.isChecked() else 'No'}
• Texture Optimization: {'Yes' if self.enable_texture_opt.isChecked() else 'No'}
• Scene Optimization: {'Yes' if self.enable_scene_opt.isChecked() else 'No'}
"""
            
            QMessageBox.information(self, "Optimization Preview", info_text)
            
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", f"Failed to analyze mesh: {str(e)}")