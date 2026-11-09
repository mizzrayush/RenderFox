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
from ..processing.lod_generator import (LODGenerator, LODSettings, is_supported_format,
                                        get_supported_formats)
from ..processing.model_extractor import (ModelExtractor, ExtractedModel,
                                          get_extraction_methods_info)
from ..processing.format_converter import FormatConverter, SupportedFormat, get_format_info
from ..processing.scene_optimizer import SceneOptimizer
from ..processing.texture_optimizer import TextureOptimizer, available_formats
from .model_viewer import ModelViewerWidget
from ..processing.texture_baker import TextureBakerThread
from ..utils.run_teardown import drain
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
class LodGenerationThread(QThread):
    """Writes the LOD chain away from the click handler.

    generate_lods() used to run inside the button behind a dialog it never updated: the
    window froze for the whole chain and the Cancel button was wired to nothing. The
    dialog's range is the number of levels, its value is the number of files on disk, and
    a stop returns what got written instead of pretending nothing happened.
    """

    stage = pyqtSignal(int, int, str)             # written, asked, sentence
    finished_with = pyqtSignal(list, list, bool)  # files, per-level failures, stopped
    error_occurred = pyqtSignal(str)

    def __init__(self, file_path, output_dir, settings):
        super().__init__()
        self.file_path = file_path
        self.output_dir = output_dir
        self.settings = settings
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            generator = LODGenerator(self.settings)
            files = generator.generate_lods(
                self.file_path, self.output_dir,
                progress=lambda done, total, text: self.stage.emit(done, total, text),
                should_cancel=lambda: self._stop_requested)
            self.finished_with.emit(files, list(generator.errors), bool(self._stop_requested))
        except Exception as e:
            self.error_occurred.emit(str(e))


class ModelExtractionThread(QThread):
    """Splits a scene into parts away from the click handler.

    The pane used to show a QProgressDialog with no range and a Cancel that did nothing,
    then print the row count. Progress is now parts done of parts found, and a stop
    reports what it reached.
    """

    stage = pyqtSignal(int, int, str)
    extraction_complete = pyqtSignal(list, dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, file_path, min_faces, method='connected_components'):
        super().__init__()
        self.file_path = file_path
        self.min_faces = min_faces
        self.method = method
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            extractor = ModelExtractor()
            models = extractor.extract_from_scene(
                self.file_path, self.min_faces, self.method,
                progress=lambda done, total, text: self.stage.emit(done, total, text),
                should_cancel=lambda: self._stop_requested)
            self.extraction_complete.emit(models, dict(extractor.summary))
        except Exception as e:
            self.error_occurred.emit(str(e))

class FormatConversionThread(QThread):
    """Thread for batch format conversion."""

    # (what converted, what did not). One list before: convert_file() answers with a
    # dict, and a dict is truthy even when it says success=False, so every failure was
    # counted and shown as a converted file.
    conversion_complete = pyqtSignal(list, list, bool)
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
        self._stop_requested = False

    def request_stop(self):
        """Ask for a stop between files; the conversion in hand is allowed to finish."""
        self._stop_requested = True

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
            stopped = False

            for i, input_file in enumerate(self.input_files):
                if self._stop_requested:
                    # The files behind the stop are named as never run, so the results
                    # dialog adds up to the list the user put in.
                    for skipped in self.input_files[i:]:
                        failed.append({'input': skipped, 'output': None,
                                       'error': 'not run - the batch was stopped'})
                    stopped = True
                    break

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
                entry['coverage'] = result.get('coverage')
                if result.get('success'):
                    converted.append(entry)
                else:
                    entry['error'] = result.get('message', 'Conversion failed')
                    failed.append(entry)
            
            self.conversion_complete.emit(converted, failed, stopped)
        except Exception as e:
            self.error_occurred.emit(str(e))

class _ExportThread(QThread):
    """Writes the ticked parts so the dialog's Cancel means something.

    A handful of small meshes is quick, but an extracted scene can be hundreds of parts
    and every one of them is a file write; on the click handler that froze the window and
    the Cancel button was decoration.
    """

    stage = pyqtSignal(int, int, str)
    finished_with = pyqtSignal(dict, bool)
    error = pyqtSignal(str)

    def __init__(self, models, output_dir, format_ext):
        super().__init__()
        self.models = models
        self.output_dir = output_dir
        self.format_ext = format_ext
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            verdict = ModelExtractor().export_selected_models(
                self.models, self.output_dir, self.format_ext,
                progress=lambda done, total, text: self.stage.emit(done, total, text),
                should_cancel=lambda: self._stop_requested)
            self.finished_with.emit(verdict, bool(self._stop_requested))
        except Exception as e:
            self.error.emit(str(e))


class OptimizationThread(QThread):
    """Runs the Advanced pane's preview and both optimisers away from the click handler.

    `operation` is 'preview', 'textures' or 'scene'. A preview measures and writes
    nothing. When both switches are armed the texture run goes first and the scene run
    takes the model the texture run wrote: two independent copies of one file would
    leave the user choosing which half of the work survived.
    """

    stage = pyqtSignal(int, int, str)
    finished_with = pyqtSignal(str, object)
    error = pyqtSignal(str)

    def __init__(self, operation, file_path, output_dir, settings):
        super().__init__()
        self.operation = operation
        self.file_path = file_path
        self.output_dir = output_dir
        self.settings = settings
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def _preview(self):
        """One read of the file, counted both ways the pane's switches can act on it."""
        optimizer = TextureOptimizer()
        scene, carried = optimizer.converter.read_scene(self.file_path)
        if scene is None:
            return {'error': f'cannot read {os.path.basename(self.file_path)}: {carried}'}
        rows = []
        for entry in optimizer.find_textures(scene):
            image = entry['image']
            rows.append({'name': entry['name'], 'part': entry['part'],
                         'slot': entry['slot'], 'size': image.size,
                         'format': image.format or 'PNG', 'shared_by': entry['shared_by'],
                         'bytes': optimizer.baseline_bytes(image)})
        payload = {'file': os.path.basename(self.file_path),
                   'textures': rows, 'read_with': carried,
                   'scene': SceneOptimizer(optimizer.converter)
                   .analyze_scene(scene, self.file_path, carried)}
        if self._stop_requested:
            payload['stopped'] = True
        return payload

    def run(self):
        try:
            if self.operation == 'preview':
                self.finished_with.emit('preview', self._preview())
                return
            reports = []
            source = self.file_path
            if self.settings['textures']:
                report = TextureOptimizer().optimize(
                    source, self.output_dir,
                    quality=self.settings['quality'], target=self.settings['target'],
                    max_size=self.settings['max_size'],
                    progress=lambda done, total, text: self.stage.emit(done, total, text),
                    should_cancel=lambda: self._stop_requested)
                reports.append(('textures', report))
                source = report.model_output or source
            if not self._stop_requested and self.settings['scene']:
                report = SceneOptimizer().optimize(
                    source, self.output_dir,
                    remove_hidden=self.settings['remove_hidden'],
                    merge_static=self.settings['merge_static'],
                    simplify_materials=self.settings['simplify_materials'],
                    progress=lambda done, total, text: self.stage.emit(done, total, text),
                    should_cancel=lambda: self._stop_requested)
                reports.append(('scene', report))
            self.finished_with.emit(self.operation, reports)
        except Exception as e:
            self.error.emit(f'{type(e).__name__}: {e}')


class PreProcessingTab(QWidget):
    """Enhanced pre-processing tab with model extraction, format conversion, and 3D preview."""

    asset_loaded = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.extracted_models = []
        self.lod_progress = None
        self.lod_thread = None
        self.extraction_progress = None
        self.extraction_thread = None
        self.conversion_thread = None
        self.conversion_progress = None
        self.optimization_thread = None
        self.optimization_progress = None
        self.baking_thread = None
        self.progress_dialog = None
        self.bake_message = None
        self._workers = []
        self.lod_generator = LODGenerator()
        self.model_extractor = ModelExtractor()
        self.format_converter = FormatConverter()
        self.init_ui()

    def _keep_worker(self, thread):
        """Hold every started worker until it says it is done.

        Reassigning `self.<run>_thread` throws away the previous worker's last Python
        reference; if that one is still running, Qt answers a destroyed running QThread by
        terminating the process - so loading a new file while a preview is still running
        would close the whole app, with no error to read. The list keeps it alive, and its
        own `finished` signal is what releases it.
        """
        self._workers.append(thread)
        thread.finished.connect(lambda: self._release_worker(thread))
        return thread

    def _release_worker(self, thread):
        """Let a worker go when it says it is done - once, whoever else let go first.

        The removal has to be guarded because `shutdown_runs` releases the same thread from
        the list on its way out; a second `list.remove` of the same worker raises inside a
        slot, and PyQt answers an exception that escapes a slot by ending the process.
        """
        if thread in self._workers:
            self._workers.remove(thread)

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Stop every run this pane started, and make sure none of them reports again.

        This pane starts seven kinds of worker and each one writes to different widgets, so
        a verdict that arrives after the window is gone is delivered into memory Qt has
        already freed - which ends the process with a heap fault, not a traceback. The
        channels therefore come off first, the stop is asked second, and a worker that
        outlasts the wait stays in `_workers`, because its reference is the only thing
        between this process and Qt's abort. The dialogs go with the runs they were
        tracking, so a close does not leave a Cancel button waiting on an answer that will
        never come. Returns the workers this pane still cannot let go of.
        """
        running = drain(self._workers, timeout_ms)
        for name in ('lod_thread', 'extraction_thread', 'conversion_thread',
                     'optimization_thread', 'baking_thread', '_export_thread',
                     'lod_progress', 'extraction_progress', 'conversion_progress',
                     'optimization_progress', 'progress_dialog', 'bake_message'):
            held = getattr(self, name, None)
            if isinstance(held, QProgressDialog):
                held.close()
            setattr(self, name, None)
        return len(running)

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
        """Take the model the Library or a browse dialog chose, and mean it everywhere.

        This used to set current_file and stop. A model could arrive from the Library,
        show in the viewer, and leave Generate LODs greyed out - only this pane's own
        Browse button enabled it - while the conversion picker kept offering targets that
        belonged to whichever file was loaded before it.
        """
        if not file_path or not os.path.exists(file_path):
            return
        self.current_file = file_path
        self.file_path.setText(file_path)
        self.model_viewer.load_model(file_path)
        self.asset_loaded.emit(file_path)
        self.toggle_lod_controls(self.enable_lod.isChecked())
        self._forget_previous_run()
        self._refresh_target_availability()
        self._refresh_optimization_buttons()

    def _forget_previous_run(self):
        """Drop every report and part that belongs to the file this one replaced.

        They used to survive a load, so the Advanced pane could still be showing the byte
        counts of the file before it, and Export could write the parts of that earlier file
        into the folder of this one.
        """
        self.extracted_models = []
        self.models_table.setRowCount(0)
        self.extraction_summary_label.setText('')
        self.opt_results.setPlainText('')


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

        # The extractor has always had five methods; the pane used to run the first one
        # whatever the file was, so three of the module's behaviours were unreachable.
        self.extraction_method = QComboBox()
        for method_id, description in get_extraction_methods_info().items():
            self.extraction_method.addItem(f"{method_id} - {description}", method_id)
        extract_layout.addRow("Method:", self.extraction_method)

        self.extract_btn = QPushButton("Extract Models")
        self.extract_btn.clicked.connect(self.extract_models)
        extract_layout.addRow(self.extract_btn)
        
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

        # What the run counted, in the extractor's own numbers. Left empty until a run
        # finishes - a pane that opens with "0 parts" would be inventing a result.
        self.extraction_summary_label = QLabel("")
        self.extraction_summary_label.setWordWrap(True)
        models_layout.addWidget(self.extraction_summary_label)
        
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
        # The box is the typable twin of the slider and takes numbers the slider has no
        # notch for; the optimizer applies the nearest setting the encoders accept and
        # says so in the report. PNG ignores it - it is lossless - which the tooltip says.
        self.texture_quality_value = QSpinBox()
        self.texture_quality_value.setRange(1, 1000)
        self.texture_quality_value.setValue(80)
        self.texture_quality_value.setSuffix("%")
        self.texture_quality_value.setToolTip(
            "Lossy formats only. PNG is lossless, so this changes nothing for it.")
        self.texture_quality.valueChanged.connect(
            lambda v: _sync_quietly(self.texture_quality_value, v))
        self.texture_quality_value.valueChanged.connect(
            lambda v: _sync_quietly(self.texture_quality, min(max(v, 1), 100)))
        
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(self.texture_quality)
        quality_layout.addWidget(self.texture_quality_value)
        texture_layout.addRow("Quality:", quality_layout)
        
        self.texture_max_size = QSpinBox()
        self.texture_max_size.setRange(0, 65536)
        self.texture_max_size.setSingleStep(512)
        self.texture_max_size.setValue(0)
        self.texture_max_size.setSuffix(" px")
        self.texture_max_size.setSpecialValueText("No cap")
        self.texture_max_size.setToolTip(
            "Textures wider than this are rescaled to it. 'No cap' leaves every "
            "texture at the size it came with.")
        texture_layout.addRow("Max size:", self.texture_max_size)
        
        self.texture_format = QComboBox()
        # Asked of the installed Pillow build, so "Convert to: WEBP" is an offer this
        # machine can keep. A choice it cannot encode is greyed with the reason.
        for choice in available_formats():
            self.texture_format.addItem(choice)
        for index in range(self.texture_format.count()):
            reason = available_formats()[self.texture_format.itemText(index)]
            if reason:
                self.texture_format.model().item(index).setEnabled(False)
                self.texture_format.setItemData(index, reason, Qt.ItemDataRole.ToolTipRole)
        first_open = next((i for i in range(self.texture_format.count())
                           if self.texture_format.model().item(i).isEnabled()), 0)
        self.texture_format.setCurrentIndex(first_open)
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
        
        # What the two groups can see, before and after. Like the LOD preview, it stays
        # empty until asked - a pane that opened with numbers nobody read would be a guess.
        self.opt_results = QTextEdit()
        self.opt_results.setMinimumHeight(100)
        self.opt_results.setMaximumHeight(180)
        self.opt_results.setReadOnly(True)
        self.opt_results.setPlaceholderText(
            "Preview counts the textures and parts a file carries. Apply writes the "
            "optimized copy and lists what changed.")
        layout.addWidget(self.opt_results)
        
        # Actions
        action_layout = QHBoxLayout()
        self.opt_preview_btn = QPushButton("Preview All Optimizations")
        self.opt_preview_btn.clicked.connect(self.preview_optimizations)
        action_layout.addWidget(self.opt_preview_btn)
        
        self.opt_apply_btn = QPushButton("Apply Optimizations")
        self.opt_apply_btn.clicked.connect(self.apply_optimizations)
        action_layout.addWidget(self.opt_apply_btn)
        layout.addLayout(action_layout)
        
        # The switches stay set-up-able while off, the same way the LOD pane's do; what
        # they really gate is Apply, so ticking one changes something you can see.
        for switch in (self.enable_texture_opt, self.enable_scene_opt):
            switch.toggled.connect(lambda _: self._refresh_optimization_buttons())
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
        
        # What the baker landed, in its own words. Empty until a run ends, so the pane
        # never opens with a result nobody asked for.
        self.bake_summary_label = QLabel("")
        self.bake_summary_label.setWordWrap(True)
        layout.addWidget(self.bake_summary_label)
        
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
        path, _ = QFileDialog.getOpenFileName(
            self, "Select High Poly Mesh", "", self.readable_filter("High Poly Mesh"))
        if path:
            self.high_poly_path.setText(path)
            self.model_viewer.load_model(path)

    def browse_low_poly(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Low Poly Mesh", "", self.readable_filter("Low Poly Mesh"))
        if path:
            self.low_poly_path.setText(path)
            self.model_viewer.load_model(path)

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

        missing = [os.path.basename(p) for p in (high_poly, low_poly) if not os.path.isfile(p)]
        if missing:
            sentence = f"Baking did not start - {', '.join(missing)} is not a file on this disk."
            self.bake_summary_label.setText(sentence)
            QMessageBox.warning(self, "Baking Did Not Start", sentence)
            return

        output_dir = self.get_output_directory(low_poly)
        resolution = int(self.bake_res.currentText())
        
        options = {
            'normals': self.bake_normals.isChecked(),
            'diffuse': self.bake_diffuse.isChecked(),
            'ao': self.bake_ao.isChecked()
        }
        
        self.bake_message = None
        self.bake_btn.setEnabled(False)
        self.progress_dialog = QProgressDialog("Baking Textures...", "Cancel", 0, 100, self)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()

        self.baking_thread = self._keep_worker(TextureBakerThread(
            high_poly, low_poly, output_dir, resolution, options))
        self.baking_thread.progress_update.connect(self.update_baking_progress)
        self.baking_thread.baking_complete.connect(self.baking_finished)
        self.baking_thread.error_occurred.connect(self.baking_error)
        # The button says Cancel, so it has to reach the worker. The map already
        # rasterising is allowed to finish - stopping a PyMeshLab filter mid-call
        # leaves the MeshSet in a state this build cannot recover - and the maps
        # behind it are reported as never run.
        self.progress_dialog.canceled.connect(self.baking_thread.request_stop)
        self.baking_thread.start()
        
    def update_baking_progress(self, value, message):
        self._show_stage(self.progress_dialog, value, 100, message)

    def baking_error(self, message):
        """Keep the baker's own sentence; it is the only one that names the cause.

        Every failure path emits this before its verdict, so `baking_finished` stays
        quiet when a message has already arrived here - two boxes for one failure
        leave the user guessing which one was the real complaint.
        """
        self.bake_message = message
        self.bake_summary_label.setText(message)
        progress, self.progress_dialog = self.progress_dialog, None
        if progress is not None:
            progress.close()
        self.bake_btn.setEnabled(True)
        QMessageBox.warning(self, "Baking Error", message)

    def baking_finished(self, success, results):
        self.bake_btn.setEnabled(True)
        progress, self.progress_dialog = self.progress_dialog, None
        if progress is not None:
            progress.close()
        landed = ', '.join(f"{kind.title()}: {os.path.basename(path)}"
                           for kind, path in results.items())
        if success:
            self.bake_summary_label.setText(
                f"Baked {len(results)} map(s){': ' + landed if landed else ''}")
            QMessageBox.information(self, "Baking Complete",
                                    f"Baked {len(results)} map(s).\n\n{landed}")
            return
        if self.bake_message:
            return
        self.bake_summary_label.setText(
            f"Baking ended short: {len(results)} map(s) on disk"
            + (f" ({landed})" if landed else ""))
        QMessageBox.warning(self, "Baking Failed",
                           f"Only {len(results)} of the requested maps were written.")
    def readable_filter(self, label="3D Model Files"):
        """The browse filter, built from what a reader here can actually open.

        These lists used to be typed out and they drifted: they named extensions no
        library installed here can read, so a picker let a user choose a file that was
        always going to fail on open. The extensions are asked of the converter now.
        """
        exts = ' '.join(f'*{ext}' for ext in self.format_converter.readable_formats())
        return f'{label} ({exts});;All Files (*)'

    def browse_file(self):
        """Browse for input 3D model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select 3D Model or Scene File", "", self.readable_filter())
        if file_path:
            self.load_model(file_path)

    def toggle_lod_controls(self, enabled):
        """What the switch decides, and what it deliberately leaves alone.

        The level count and the per-level ratios stay editable with the switch off, so a
        run can be set up before it is armed. What the switch really controls is
        Generate: it only answers while the switch is on and a file is loaded, so ticking
        it changes something the user can see instead of being decoration.
        """
        for widget in [self.lod_levels, self.lod_preview] + list(self.ratio_inputs):
            widget.setEnabled(True)
        self.generate_lods_btn.setEnabled(bool(enabled) and bool(self.current_file))
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
        self.preview_thread = self._keep_worker(
            LODPreviewThread(self.current_file, settings))
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
        """Write the LOD chain for the loaded model, off the click handler."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a 3D model file first.")
            return

        if not self.enable_lod.isChecked():
            QMessageBox.information(self, "LOD Generation Disabled",
                                   "Please enable LOD generation first.")
            return

        if not is_supported_format(self.current_file):
            QMessageBox.warning(self, "Cannot read this file",
                                f"{os.path.basename(self.current_file)} is not a format any "
                                f"library here can open. Convert it to one of "
                                f"{', '.join(get_supported_formats())} first.")
            return

        output_dir = self.get_output_directory(self.current_file)
        ratios = [spin.value() for spin in self.ratio_inputs]
        settings = LODSettings(levels=self.lod_levels.value(), custom_ratios=ratios)

        progress = QProgressDialog("Generating LOD files...", "Cancel",
                                   0, settings.levels, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        self.lod_progress = progress
        self.lod_thread = self._keep_worker(
            LodGenerationThread(self.current_file, output_dir, settings))
        self.lod_thread.stage.connect(self.lod_stage)
        self.lod_thread.finished_with.connect(self.lods_written)
        self.lod_thread.error_occurred.connect(self.lod_generation_failed)
        progress.canceled.connect(self.lod_thread.request_stop)
        self.generate_lods_btn.setEnabled(False)
        self.lod_thread.start()

    def _show_stage(self, progress, done, max_total, sentence):
        """Move a dialog that the pump inside `setValue` may already have finished.

        `QProgressDialog.setValue` runs an event loop, so a worker's terminal signal can be
        delivered - and the handler that nulls the dialog attribute run - between two lines
        of a stage handler. Each handler therefore works from the reference it was handed,
        never from the attribute the pump can have set to None underneath it.
        """
        if progress is None:
            return
        progress.setMaximum(max(max_total, 1))
        progress.setValue(done)
        progress.setLabelText(sentence)

    def lod_stage(self, written, asked, sentence):
        """The number shown is files on disk, not a guess about how far along it feels."""
        self._show_stage(self.lod_progress, written, asked, sentence)

    def lods_written(self, files, errors, stopped):
        self.generate_lods_btn.setEnabled(True)
        progress, self.lod_progress = self.lod_progress, None
        if progress is not None:
            progress.close()
        names = "\n".join(os.path.basename(f) for f in files) or "nothing"
        tail = ""
        if errors:
            tail = "\n\nLevels that failed:\n" + "\n".join(f"- {e}" for e in errors)

        if stopped:
            QMessageBox.warning(self, "LOD generation stopped",
                                f"Stopped after {len(files)} of the levels asked for."
                                f"\n\nFiles written:\n{names}{tail}")
        elif files and not errors:
            QMessageBox.information(self, "LOD Generation Complete",
                                   f"Successfully generated {len(files)} LOD files:\n\n{names}")
        elif files:
            QMessageBox.warning(self, "LOD generation incomplete",
                                f"Wrote {len(files)} level(s).\n\nFiles:\n{names}{tail}")
        else:
            QMessageBox.warning(self, "LOD Generation Failed",
                                f"No LOD files were written.{tail}")

    def lod_generation_failed(self, message):
        self.generate_lods_btn.setEnabled(True)
        progress, self.lod_progress = self.lod_progress, None
        if progress is not None:
            progress.close()
        QMessageBox.critical(self, "LOD Generation Error",
                           f"Failed to generate LODs: {message}")


    
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
        """Split the loaded scene into parts, off the click handler."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a scene file first.")
            return

        self.extraction_progress = QProgressDialog("Extracting models from scene...",
                                                   "Cancel", 0, 1, self)
        self.extraction_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.extraction_progress.setMinimumDuration(0)
        self.extraction_progress.show()

        self.extraction_thread = self._keep_worker(ModelExtractionThread(
            self.current_file, self.min_faces_spin.value(),
            self.extraction_method.currentData()))
        self.extraction_thread.stage.connect(self.extraction_stage)
        self.extraction_thread.extraction_complete.connect(self.display_extracted_models)
        self.extraction_thread.error_occurred.connect(self.show_extraction_error)
        self.extraction_progress.canceled.connect(self.extraction_thread.request_stop)
        self.extract_btn.setEnabled(False)
        self.extraction_thread.start()

    def extraction_stage(self, done, total, sentence):
        """Parts looked at, not a percentage guessed at."""
        self._show_stage(self.extraction_progress, done, total, sentence)

    def display_extracted_models(self, models: list, summary: dict):
        """Fill the table and say what the run counted.

        The row count alone used to be the whole report, so a scene of 40 parts and a
        minimum of 100 faces showed 3 rows with no hint that 37 were dropped by the
        filter the user set.
        """
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

        progress, self.extraction_progress = self.extraction_progress, None
        if progress is not None:
            progress.close()
        self.extract_btn.setEnabled(True)
        self.extraction_summary_label.setText(_extraction_sentence(models, summary))

    def show_extraction_error(self, error_message: str):
        """Report a failed extraction and leave the table as it was."""
        self.extract_btn.setEnabled(True)
        progress, self.extraction_progress = self.extraction_progress, None
        if progress is not None:
            progress.close()
        self.extraction_summary_label.setText(f"Extraction failed: {error_message}")
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
        """Write the ticked parts and report each verdict the writer gave."""
        selected_models = []
        for row in range(self.models_table.rowCount()):
            checkbox = self.models_table.cellWidget(row, 4)
            if checkbox and checkbox.isChecked():
                selected_models.append(self.extracted_models[row])

        if not selected_models:
            QMessageBox.information(self, "No Models Selected",
                                   "Please select at least one model to export.")
            return
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Load a model first - the parts go in its output folder.")
            return

        output_dir = self.get_output_directory(self.current_file)

        # Only the formats a trimesh object in memory can be saved as. The list used to
        # be every SupportedFormat, so .dae and .fbx were offered here and every click
        # died inside trimesh with 'fbx exporter not available'.
        writable = self.format_converter.mesh_write_formats()
        if not writable:
            QMessageBox.warning(self, "No writer installed",
                                "trimesh is not available, so nothing can be exported.")
            return

        labels = {ext.upper().lstrip('.'): ext for ext in writable}
        format_choice, ok = QInputDialog.getItem(
            self, "Export Format", "Choose export format:", sorted(labels), 0, False)

        if not ok:
            return

        format_ext = labels[format_choice]
        progress = QProgressDialog("Exporting parts...", "Cancel", 0,
                                   len(selected_models), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        worker = self._keep_worker(_ExportThread(selected_models, output_dir, format_ext))
        self._export_thread = worker
        worker.stage.connect(lambda done, total, text: (
            progress.setMaximum(max(total, 1)), progress.setValue(done),
            progress.setLabelText(text)))
        progress.canceled.connect(worker.request_stop)
        worker.finished_with.connect(
            lambda verdict, stopped: self._export_reported(verdict, stopped, progress))
        worker.error.connect(lambda message: self._export_failed(message, progress))
        worker.start()

    def _export_reported(self, verdict, stopped, progress):
        progress.close()
        self.extraction_summary_label.setText(
            _export_sentence(verdict, stopped, len(verdict['exported']) + len(verdict['failed'])))
        written = verdict['exported']
        refused = verdict['failed']
        if not written and refused:
            QMessageBox.warning(self, "Nothing was written",
                                "\n".join(f"{name}: {why}" for name, why in refused[:8]))
        elif refused or stopped:
            QMessageBox.warning(
                self, "Export finished with problems",
                f"{len(written)} file(s) written to {verdict['output_dir']}"
                + (" - the run was stopped early" if stopped else "")
                + "\n\n" + "\n".join(f"{name}: {why}" for name, why in refused[:8]))
        else:
            QMessageBox.information(
                self, "Export Complete",
                f"Successfully exported {len(written)} models to "
                f"{verdict['output_dir']}")

    def _export_failed(self, message, progress):
        progress.close()
        self.extraction_summary_label.setText(f"Export failed: {message}")
        QMessageBox.critical(self, "Export Error", f"Failed to export models: {message}")
    
    def add_conversion_files(self):
        """Add files to the batch conversion list."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Files for Batch Conversion", "", self.readable_filter())

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
        progress.setMinimumDuration(0)
        progress.show()

        # Start conversion thread
        output_mode = self.output_folder_combo.currentIndex()
        self.conversion_progress = progress
        self.conversion_thread = self._keep_worker(FormatConversionThread(
            input_files, output_dir, target_format, options, output_mode,
            generate_lods=self.convert_with_lod.isChecked()))
        progress.canceled.connect(self.conversion_thread.request_stop)
        self.conversion_thread.conversion_complete.connect(
            lambda converted, failed, stopped: self.show_conversion_complete(
                converted, failed, stopped, progress))
        self.conversion_thread.progress_update.connect(
            lambda i, msg: self.update_conversion_progress(progress, i, msg))
        self.conversion_thread.error_occurred.connect(
            lambda error: self.show_conversion_error(error, progress))
        self.convert_batch_btn.setEnabled(False)
        self.conversion_thread.start()

    def update_conversion_progress(self, progress_dialog, current, message):
        """Update conversion progress."""
        progress_dialog.setValue(current)
        progress_dialog.setLabelText(message)

    def show_conversion_complete(self, converted_files, failed_files, stopped,
                                 progress_dialog):
        """Show the results the conversion actually reported."""
        self.convert_batch_btn.setEnabled(True)
        progress_dialog.close()

        # The old version zipped the successes against the whole input list, so a row
        # only lined up when nothing failed, and 'method' was the literal
        # 'format_converter' rather than the library that did the work.
        errors = [f"{entry['input']}: {entry.get('error', 'Conversion failed')}"
                  for entry in failed_files]
        if stopped:
            errors.insert(0, f"The run was stopped after {len(converted_files)} file(s); "
                             f"the files listed as 'not run' were never attempted.")
        for entry in converted_files:
            if entry.get('options_skipped'):
                errors.append(f"{entry['input']}: written without "
                              f"{', '.join(entry['options_skipped'])} "
                              f"- the {entry.get('method', 'library')} used cannot apply them")

        results = {
            'total_files': len(converted_files) + len(failed_files),
            'successful': converted_files,
            'failed': failed_files,
            'stopped': stopped,
            'errors': errors
        }

        # Show the new results dialog
        from src.ui.conversion_results_dialog import show_conversion_results
        show_conversion_results(results, self)

    def show_conversion_error(self, error_message, progress_dialog):
        """Show conversion error message."""
        self.convert_batch_btn.setEnabled(True)
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
    
    def _advanced_settings(self):
        """The pane's controls as the two backends are called, with no invented values."""
        return {
            'textures': self.enable_texture_opt.isChecked(),
            'quality': self.texture_quality_value.value(),
            'target': self.texture_format.currentText(),
            'max_size': self.texture_max_size.value() or None,
            'scene': self.enable_scene_opt.isChecked(),
            'remove_hidden': self.remove_hidden.isChecked(),
            'merge_static': self.merge_static.isChecked(),
            'simplify_materials': self.simplify_materials.isChecked(),
        }

    def _refresh_optimization_buttons(self):
        """Apply answers only when a switch is armed and a file is loaded.

        The settings themselves stay editable with both switches off, the way the LOD
        pane's are, so a run can be set up before it is armed.
        """
        armed = self.enable_texture_opt.isChecked() or self.enable_scene_opt.isChecked()
        self.opt_apply_btn.setEnabled(bool(armed and self.current_file))
        self.opt_preview_btn.setEnabled(bool(self.current_file))

    def preview_optimizations(self):
        """Count what the two groups could act on, and write nothing."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a 3D model file first.")
            return
        self._run_optimization('preview', self._advanced_settings())

    def apply_optimizations(self):
        """Run the armed groups and list what each one measured before and after."""
        if not self.current_file:
            QMessageBox.information(self, "No File Selected",
                                   "Please select a 3D model file first.")
            return
        settings = self._advanced_settings()
        if not settings['textures'] and not settings['scene']:
            QMessageBox.information(self, "Nothing armed",
                                   "Neither 'Optimize Textures' nor 'Optimize Scene' is "
                                   "ticked, so there is nothing to apply.")
            return
        operation = ('both' if settings['textures'] and settings['scene']
                     else 'textures' if settings['textures'] else 'scene')
        self._run_optimization(operation, settings)

    def _run_optimization(self, operation, settings):
        progress = QProgressDialog(
            "Measuring the file..." if operation == 'preview' else "Applying optimizations...",
            "Cancel", 0, 1, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        self.optimization_progress = progress
        self.optimization_thread = self._keep_worker(OptimizationThread(
            operation, self.current_file,
            self.get_output_directory(self.current_file), settings))
        self.optimization_thread.stage.connect(self._optimization_stage)
        self.optimization_thread.finished_with.connect(self._optimization_reported)
        self.optimization_thread.error.connect(self._optimization_failed)
        progress.canceled.connect(self.optimization_thread.request_stop)
        self.opt_preview_btn.setEnabled(False)
        self.opt_apply_btn.setEnabled(False)
        self.optimization_thread.start()

    def _optimization_stage(self, done, total, sentence):
        self._show_stage(self.optimization_progress, done, total, sentence)

    def _optimization_reported(self, operation, payload):
        self._end_optimization_run()
        if operation == 'preview':
            text = _preview_text(payload)
            self.opt_results.setPlainText(text)
            if 'error' in payload:
                QMessageBox.warning(self, "Preview Error", payload['error'])
            return
        stopped = any(report.stopped for _, report in payload)
        text = _optimization_text(payload, stopped)
        self.opt_results.setPlainText(text)
        if not any(report.results for _, report in payload):
            QMessageBox.warning(self, "Optimization wrote nothing", text)

    def _optimization_failed(self, message):
        self._end_optimization_run()
        self.opt_results.setPlainText(f"The run stopped: {message}")
        QMessageBox.critical(self, "Optimization Error", message)

    def _end_optimization_run(self):
        progress, self.optimization_progress = self.optimization_progress, None
        if progress is not None:
            progress.close()
        self._refresh_optimization_buttons()


def _sync_quietly(target, value):
    """Move one half of a paired control without the other half echoing the move back.

    A slider and its typable box are each connected to the other, so a plain `setValue` on
    the echo path overwrites what was just typed - 500 in the box came back as the slider's
    own 100 - and the echo is the only reason to block its signals here.
    """
    was_open = target.blockSignals(True)
    target.setValue(value)
    target.blockSignals(was_open)


def _preview_text(payload) -> str:
    """The preview thread's counts, in the order the pane's two groups ask about them."""
    name = payload.get('file', 'this file')
    if 'error' in payload:
        return f"Preview of {name} failed: {payload['error']}"
    textures, scene = payload['textures'], payload['scene']

    lines = [f"Preview of {name} - read with {payload['read_with'] or 'unknown'}"]
    if textures:
        total = sum(row['bytes'] for row in textures)
        lines.append(f"Textures: {len(textures)} distinct image(s), {total:,} bytes as "
                     f"this Pillow build encodes them")
        for row in textures:
            shared = (f", on {row['shared_by']} part(s)" if row['shared_by'] > 1 else '')
            lines.append(f"  {row['part']} / {row['slot']}: {row['size'][0]}x{row['size'][1]} "
                         f"{row['format']}, {row['bytes']:,} bytes{shared}")
    else:
        lines.append("Textures: no material in this file references an image, so the "
                     "texture group has nothing to encode")

    lines.append(f"Scene: {scene['parts']} placed part(s), {scene['faces']:,} faces, "
                 f"{scene['distinct_materials']} distinct look(s)")
    if scene['batches']:
        lines.append(f"  merge static meshes: {scene['parts_in_batches']} part(s) in "
                     f"{scene['batches']} batch(es) would leave {scene['parts_after_merge']}")
    else:
        lines.append("  merge static meshes: no two parts share a material and a "
                     "transform, so nothing would batch")
    if scene['hidden_flagged']:
        lines.append(f"  remove hidden: {scene['hidden_flagged']} flagged ({scene['hidden_source']}), "
                     f"{scene['hidden_matching_parts']} of them match a part here")
    else:
        lines.append("  remove hidden: nothing in this file is flagged hidden")
    if scene['nothing_to_render']:
        lines.append(f"  {scene['nothing_to_render']} part(s) carry no geometry to draw")
    if scene['material_names'] != scene['distinct_materials']:
        lines.append(f"  simplify materials: {scene['material_names']} name(s) over "
                     f"{scene['distinct_materials']} look(s) would collapse to one label each")
    return "\n".join(lines)


def _optimization_text(reports, stopped) -> str:
    """Each run's own lines, under a heading that says which group wrote them."""
    headers = {'textures': 'Texture optimization', 'scene': 'Scene optimization'}
    blocks = []
    for kind, report in reports:
        body = report.lines()
        head = headers[kind]
        if kind == 'textures' and report.results:
            head += (f" - {report.bytes_from:,} -> {report.bytes_to:,} bytes "
                     f"({report.bytes_to - report.bytes_from:+,})")
        blocks.append(f"{head}:\n" + "\n".join(f"  {line}" for line in body))
    text = "\n\n".join(blocks)
    if stopped:
        text += ("\n\nStopped by Cancel. Everything listed above was written before the "
                 "stop; the rest was never attempted.")
    return text

def _extraction_sentence(models, summary) -> str:
    """One line in the extractor's own numbers, or the reason there are none."""
    if not summary:
        return f"{len(models)} part(s) ready to export."
    kept = summary.get('kept', len(models))
    dropped = summary.get('dropped', 0)
    parts = summary.get('parts', 0)
    text = (f"{summary.get('method', 'connected_components')}: {parts} piece(s) produced, "
            f"{kept} kept, {dropped} below the {summary.get('min_faces', '?')}-face minimum"
            f" - read with {summary.get('read_with', 'unknown')}")
    if summary.get('stopped'):
        text += "; stopped by Cancel, the parts behind it were not looked at"
    for note in summary.get('notes') or []:
        # A method that could not run on this build says which one did, so the pane never
        # prints "geometric_analysis" over what was really a connectivity split.
        text += f"; {note}"
    return text


def _export_sentence(verdict, stopped, attempted) -> str:
    """What the export actually wrote, and what it refused."""
    written = len(verdict['exported'])
    refused = len(verdict['failed'])
    text = f"{written} of {attempted} part(s) written to {verdict['output_dir']}"
    if refused:
        text += f"; {refused} refused ({verdict['failed'][0][0]}: {verdict['failed'][0][1]})"
    if stopped:
        text += "; stopped by Cancel before the rest"
    return text
