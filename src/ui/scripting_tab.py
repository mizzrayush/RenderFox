"""
Scripting tab for Python scripting, automation, and workflow creation.
"""

import os
import sys
import subprocess
import traceback
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
                             QPushButton, QComboBox, QLabel, QGroupBox, QFormLayout, 
                             QSpinBox, QDoubleSpinBox, QSlider, QTabWidget, QCheckBox,
                             QFrame, QGridLayout, QScrollArea, QTextEdit, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
                             QListWidget, QTreeWidget, QTreeWidgetItem, QPlainTextEdit,
                             QFileDialog, QMessageBox, QMenu, QMenuBar)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QProcess, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter, QAction
import keyword
import builtins
from .icon_provider import get_icon
from ..utils.run_teardown import drain_attributes

class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Python syntax highlighter for the code editor."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_formats()
        
    def setup_formats(self):
        """Setup text formats for Python syntax."""
        self.formats = {}
        
        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor(0, 0, 255))  # Blue
        keyword_format.setFontWeight(QFont.Weight.Bold)
        self.formats['keyword'] = keyword_format
        
        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor(163, 21, 21))  # Dark red
        self.formats['string'] = string_format
        
        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor(0, 128, 0))  # Green
        comment_format.setFontItalic(True)
        self.formats['comment'] = comment_format
        
        # Numbers
        number_format = QTextCharFormat()
        number_format.setForeground(QColor(255, 140, 0))  # Orange
        self.formats['number'] = number_format
        
        # Functions
        function_format = QTextCharFormat()
        function_format.setForeground(QColor(128, 0, 128))  # Purple
        function_format.setFontWeight(QFont.Weight.Bold)
        self.formats['function'] = function_format
        
    def highlightBlock(self, text):
        """Highlight a block of text."""
        # Keywords
        for keyword_text in keyword.kwlist:
            start = 0
            while True:
                start = text.find(keyword_text, start)
                if start == -1:
                    break
                # Check if it's a whole word
                if (start == 0 or not text[start-1].isalnum()) and \
                   (start + len(keyword_text) == len(text) or not text[start + len(keyword_text)].isalnum()):
                    self.setFormat(start, len(keyword_text), self.formats['keyword'])
                start += len(keyword_text)
        
        # Comments
        start = text.find('#')
        if start >= 0:
            self.setFormat(start, len(text) - start, self.formats['comment'])
        
        # Strings
        for quote in ['"', "'"]:
            start = 0
            while True:
                start = text.find(quote, start)
                if start == -1:
                    break
                end = text.find(quote, start + 1)
                if end == -1:
                    end = len(text)
                else:
                    end += 1
                self.setFormat(start, end - start, self.formats['string'])
                start = end
    

class ScriptingTab(QWidget):
    """Python scripting and automation interface."""
    
    script_executed = pyqtSignal(str, bool)
    automation_triggered = pyqtSignal(str, dict)
    
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.main_window = main_window
        
        from src.processing.script_engine import ScriptEngine
        self.script_engine = ScriptEngine(main_window)
        
        self.current_script_path = None
        self.executor = None
        
        self.init_ui()
        self.setup_connections()
        
    def init_ui(self):
        """Initialize the scripting interface."""
        main_layout = QVBoxLayout(self)
        
        # Create tab widget for different scripting areas
        self.scripting_tabs = QTabWidget()
        
        # Code Editor tab
        editor_tab = self.create_editor_tab()
        self.scripting_tabs.addTab(editor_tab, "Code Editor")
        
        # Script Library tab
        library_tab = self.create_library_tab()
        self.scripting_tabs.addTab(library_tab, "Script Library")
        
        # Automation tab
        automation_tab = self.create_automation_tab()
        self.scripting_tabs.addTab(automation_tab, "Automation")
        
        # API Reference tab
        api_tab = self.create_api_tab()
        self.scripting_tabs.addTab(api_tab, "API Reference")
        
        # Console tab
        console_tab = self.create_console_tab()
        self.scripting_tabs.addTab(console_tab, "Interactive Console")
        
        main_layout.addWidget(self.scripting_tabs)
        
    def populate_sample_scripts(self):  # ✅ ADD THIS METHOD HERE
        """Populate the script library from ScriptTemplates."""
        self.script_tree.clear()
        
        # Get templates from ScriptEngine
        templates = self.script_engine.templates.get_all_templates()
        
        # Group by category
        categories = {}
        for template in templates:
            cat = template['category']
            if cat not in categories:
                categories[cat] = QTreeWidgetItem([cat, "", ""])
                self.script_tree.addTopLevelItem(categories[cat])
            
            # Add template as child
            item = QTreeWidgetItem([
                template['name'],
                template['category'],
                template.get('modified', 'N/A')
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, template)
            categories[cat].addChild(item)
        
        self.script_tree.expandAll()
    
    def create_editor_tab(self):
        """Create the code editor interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Editor toolbar
        toolbar_layout = QHBoxLayout()
        
        from .icon_provider import get_icon
        self.new_script_btn = QPushButton("New")
        self.new_script_btn.setIcon(get_icon("add"))
        self.open_script_btn = QPushButton("Open")
        self.open_script_btn.setIcon(get_icon("folder"))
        self.save_script_btn = QPushButton("Save")
        self.save_script_btn.setIcon(get_icon("backup"))
        self.save_as_btn = QPushButton("Save As...")
        self.save_as_btn.setIcon(get_icon("backup"))
        
        toolbar_layout.addWidget(self.new_script_btn)
        toolbar_layout.addWidget(self.open_script_btn)
        toolbar_layout.addWidget(self.save_script_btn)
        toolbar_layout.addWidget(self.save_as_btn)
        toolbar_layout.addStretch()
        
        # Run controls
        self.run_script_btn = QPushButton("Run Script")
        self.run_script_btn.setProperty("primary", "true")
        self.stop_script_btn = QPushButton("Stop")
        self.stop_script_btn.setEnabled(False)
        
        toolbar_layout.addWidget(self.run_script_btn)
        toolbar_layout.addWidget(self.stop_script_btn)
        toolbar_layout.addWidget(self.stop_script_btn)
        
        layout.addLayout(toolbar_layout)
        
        # Editor and output splitter
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Code editor
        editor_group = QGroupBox("Python Script Editor")
        editor_layout = QVBoxLayout()
        
        # File info
        self.file_info_label = QLabel("New Script - Unsaved")
        self.file_info_label.setStyleSheet("font-weight: bold;")
        
        self.code_editor = QPlainTextEdit()
        self.code_editor.setFont(QFont("Consolas", 12))
        self.code_editor.setPlainText("""# RenderFox Script Template
# This script has access to the RenderFox API

# Import RenderFox modules
# from renderfox import models, processing, utils

def main():
    \"\"\"Main script function.\"\"\"
    print("Hello from RenderFox!")
    
    # Example: Get all loaded models
    # models = get_loaded_models()
    # print(f"Found {len(models)} loaded models")
    
    # Example: Process models
    # for model in models:
    #     print(f"Processing: {model.name}")
    #     # Add your processing logic here

if __name__ == "__main__":
    main()
""")
        
        # Apply syntax highlighting
        self.syntax_highlighter = PythonSyntaxHighlighter(self.code_editor.document())
        
        editor_layout.addWidget(self.file_info_label)
        editor_layout.addWidget(self.code_editor)
        
        editor_group.setLayout(editor_layout)
        splitter.addWidget(editor_group)
        
        # Output panel
        output_group = QGroupBox("Script Output")
        output_layout = QVBoxLayout()
        
        # Output controls
        output_controls = QHBoxLayout()
        self.clear_output_btn = QPushButton("Clear")
        self.clear_output_btn.setIcon(get_icon("delete"))
        self.save_output_btn = QPushButton("Save Output")
        self.save_output_btn.setIcon(get_icon("backup"))
        
        output_controls.addWidget(self.clear_output_btn)
        output_controls.addWidget(self.save_output_btn)
        output_controls.addStretch()
        
        self.output_display = QPlainTextEdit()
        self.output_display.setFont(QFont("Consolas", 10))
        self.output_display.setReadOnly(True)
        self.output_display.setMaximumHeight(200)
        
        output_layout.addLayout(output_controls)
        output_layout.addWidget(self.output_display)
        
        output_group.setLayout(output_layout)
        splitter.addWidget(output_group)
        
        splitter.setSizes([400, 200])
        layout.addWidget(splitter)
        
        return widget
        
    def create_library_tab(self):
        """Create script library interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        from .icon_provider import get_icon
        
        # Library controls
        controls_layout = QHBoxLayout()
        
        self.refresh_library_btn = QPushButton("Refresh")
        self.refresh_library_btn.setIcon(get_icon("refresh"))
        self.import_script_btn = QPushButton("Import Script")
        self.import_script_btn.setIcon(get_icon("import_model"))
        self.create_category_btn = QPushButton("New Category")
        self.create_category_btn.setIcon(get_icon("add"))
        self.delete_script_btn = QPushButton("Delete")
        self.delete_script_btn.setIcon(get_icon("delete"))
        
        controls_layout.addWidget(self.refresh_library_btn)
        controls_layout.addWidget(self.import_script_btn)
        controls_layout.addWidget(self.create_category_btn)
        controls_layout.addWidget(self.delete_script_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Library content
        library_layout = QHBoxLayout()
        
        # Script tree
        library_group = QGroupBox("Script Library")
        library_tree_layout = QVBoxLayout()
        self.script_tree = self.scripts_tree = QTreeWidget()
        self.script_tree.setHeaderLabels(["Script", "Category", "Modified"])
        self.populate_sample_scripts()
        library_tree_layout.addWidget(self.script_tree)
        library_group.setLayout(library_tree_layout)
        library_layout.addWidget(library_group)
        
        # Script preview
        preview_group = QGroupBox("Script Preview")
        preview_layout = QVBoxLayout()
        
        self.script_info_label = QLabel("Select a script to preview")
        self.script_preview = QPlainTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFont(QFont("Consolas", 10))
        
        preview_buttons = QHBoxLayout()
        self.load_to_editor_btn = QPushButton("Load to Editor")
        self.load_to_editor_btn.setIcon(get_icon("edit"))
        self.run_from_library_btn = QPushButton("Run Script")
        self.run_from_library_btn.setIcon(get_icon("play"))
        self.run_from_library_btn.setProperty("primary", "true")
        
        preview_buttons.addWidget(self.load_to_editor_btn)
        preview_buttons.addWidget(self.run_from_library_btn)
        preview_buttons.addStretch()
        
        preview_layout.addWidget(self.script_info_label)
        preview_layout.addWidget(self.script_preview)
        preview_layout.addLayout(preview_buttons)
        
        preview_group.setLayout(preview_layout)
        library_layout.addWidget(preview_group)
        
        layout.addLayout(library_layout)
        
        return widget
    

        
    def create_automation_tab(self):
        """Create automation workflow interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        from .icon_provider import get_icon
        
        # Automation controls
        controls_group = QGroupBox("Automation Controls")
        controls_layout = QHBoxLayout()
        
        self.create_workflow_btn = QPushButton("Create Workflow")
        self.create_workflow_btn.setIcon(get_icon("add"))
        self.schedule_script_btn = QPushButton("Schedule Script")
        self.schedule_script_btn.setIcon(get_icon("diagnostics"))
        self.batch_process_btn = QPushButton("Batch Process")
        self.batch_process_btn.setIcon(get_icon("batch_render"))
        self.workflow_editor_btn = QPushButton("Workflow Editor")
        self.workflow_editor_btn.setIcon(get_icon("edit"))
        
        controls_layout.addWidget(self.create_workflow_btn)
        controls_layout.addWidget(self.schedule_script_btn)
        controls_layout.addWidget(self.batch_process_btn)
        controls_layout.addWidget(self.workflow_editor_btn)
        controls_layout.addStretch()
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Workflows and triggers
        workflow_layout = QHBoxLayout()
        
        # Active workflows
        workflows_group = QGroupBox("Active Workflows")
        workflows_list_layout = QVBoxLayout()
        
        self.workflows_list = QListWidget()
        
        # Add sample workflows
        sample_workflows = [
            "Auto-convert OBJ to GLTF",
            "Generate LOD variants",
            "Cleanup temp files",
            "Performance monitoring",
            "Model validation"
        ]
        
        for workflow in sample_workflows:
            self.workflows_list.addItem(workflow)
            
        workflow_buttons = QHBoxLayout()
        self.start_workflow_btn = QPushButton("Start")
        self.start_workflow_btn.setIcon(get_icon("play"))
        self.start_workflow_btn.setProperty("primary", "true")
        self.stop_workflow_btn = QPushButton("Stop")
        self.stop_workflow_btn.setIcon(get_icon("stop"))
        self.edit_workflow_btn = QPushButton("Edit")
        self.edit_workflow_btn.setIcon(get_icon("edit"))
        
        workflow_buttons.addWidget(self.start_workflow_btn)
        workflow_buttons.addWidget(self.stop_workflow_btn)
        workflow_buttons.addWidget(self.edit_workflow_btn)
        
        workflows_list_layout.addWidget(self.workflows_list)
        workflows_list_layout.addLayout(workflow_buttons)
        
        workflows_group.setLayout(workflows_list_layout)
        workflow_layout.addWidget(workflows_group)
        
        # Triggers and events
        triggers_group = QGroupBox("Triggers & Events")
        triggers_layout = QFormLayout()
        
        # File system triggers
        self.watch_folder_cb = QCheckBox("Watch Folder for Changes")
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("Select folder to watch...")
        
        # Schedule triggers
        self.schedule_enabled_cb = QCheckBox("Scheduled Execution")
        self.schedule_interval_spin = QSpinBox()
        self.schedule_interval_spin.setRange(1, 1440)
        self.schedule_interval_spin.setValue(60)
        self.schedule_interval_spin.setSuffix(" minutes")
        
        # Event triggers
        self.model_loaded_cb = QCheckBox("On Model Loaded")
        self.batch_complete_cb = QCheckBox("On Batch Complete")
        self.error_occurred_cb = QCheckBox("On Error Occurred")
        
        triggers_layout.addRow(self.watch_folder_cb)
        triggers_layout.addRow("Folder Path:", self.folder_path_edit)
        triggers_layout.addRow(self.schedule_enabled_cb)
        triggers_layout.addRow("Interval:", self.schedule_interval_spin)
        triggers_layout.addRow(self.model_loaded_cb)
        triggers_layout.addRow(self.batch_complete_cb)
        triggers_layout.addRow(self.error_occurred_cb)
        
        triggers_group.setLayout(triggers_layout)
        workflow_layout.addWidget(triggers_group)
        
        layout.addLayout(workflow_layout)
        
        # Automation log
        log_group = QGroupBox("Automation Log")
        log_layout = QVBoxLayout()
        
        self.automation_log = QPlainTextEdit()
        self.automation_log.setMaximumHeight(150)
        self.automation_log.setReadOnly(True)
        self.automation_log.setPlainText("Automation system ready...")
        
        log_layout.addWidget(self.automation_log)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        return widget
        
    def create_api_tab(self):
        """Create API reference interface."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # API navigation
        nav_layout = QHBoxLayout()
        
        self.api_category_combo = QComboBox()
        self.api_category_combo.addItems([
            "Core API", "Model Operations", "Processing Functions", 
            "File Utilities", "Rendering", "Batch Operations", "UI Integration"
        ])
        
        self.search_api_edit = QLineEdit()
        self.search_api_edit.setPlaceholderText("Search API functions...")
        
        nav_layout.addWidget(QLabel("Category:"))
        nav_layout.addWidget(self.api_category_combo)
        nav_layout.addWidget(self.search_api_edit)
        nav_layout.addStretch()
        
        layout.addLayout(nav_layout)
        
        # API content
        api_content_layout = QHBoxLayout()
        
        # Function list
        functions_group = QGroupBox("Available Functions")
        functions_layout = QVBoxLayout()
        
        self.api_functions_list = QListWidget()
        
        # Add sample API functions
        self.populate_api_functions()
        
        functions_layout.addWidget(self.api_functions_list)
        functions_group.setLayout(functions_layout)
        api_content_layout.addWidget(functions_group)
        
        # Function documentation
        docs_group = QGroupBox("Documentation")
        docs_layout = QVBoxLayout()
        
        self.api_docs_display = QTextEdit()
        self.api_docs_display.setReadOnly(True)
        self.api_docs_display.setHtml("""
        <h3>RenderFox API Documentation</h3>
        <p>Select a function from the list to view its documentation.</p>
        
        <h4>Quick Start:</h4>
        <ul>
            <li><code>get_loaded_models()</code> - Get all loaded models</li>
            <li><code>load_model(path)</code> - Load a model from file</li>
            <li><code>convert_model(model, format)</code> - Convert model format</li>
            <li><code>generate_lod(model, levels)</code> - Generate LOD variants</li>
            <li><code>batch_process(models, operation)</code> - Process multiple models</li>
        </ul>
        """)
        
        # Insert code button
        self.insert_code_btn = QPushButton("Insert Code")
        self.insert_code_btn.setIcon(get_icon("paste"))
        
        docs_layout.addWidget(self.api_docs_display)
        docs_layout.addWidget(self.insert_code_btn)
        
        docs_group.setLayout(docs_layout)
        api_content_layout.addWidget(docs_group)
        
        layout.addLayout(api_content_layout)
        
        return widget
        
    def populate_api_functions(self):
        """Populate the API functions list."""
        self.api_functions_list.clear()
        
        # Basic API functions
        functions = [
            "load_model(file_path)",
            "get_library_models(tags=None)",
            "add_to_job_queue(model_path, **kwargs)",
            "convert_format(input_file, output_format)",
            "generate_lod(input_file, levels=3)",
            "batch_process(files, operation)",
            "log(message, level='INFO')"
        ]
        
        for func in functions:
            self.api_functions_list.addItem(func)

    def create_console_tab(self):
        """Create interactive Python console."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Console controls
        controls_layout = QHBoxLayout()
        
        self.reset_console_btn = QPushButton("Reset Console")
        self.reset_console_btn.setIcon(get_icon("refresh"))
        self.clear_console_btn = QPushButton("Clear")
        self.clear_console_btn.setIcon(get_icon("delete"))
        self.save_session_btn = QPushButton("Save Session")
        self.save_session_btn.setIcon(get_icon("backup"))
        
        controls_layout.addWidget(self.reset_console_btn)
        controls_layout.addWidget(self.clear_console_btn)
        controls_layout.addWidget(self.save_session_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Console output
        self.console_output = QPlainTextEdit()
        self.console_output.setFont(QFont("Consolas", 10))
        self.console_output.setReadOnly(True)
        self.console_output.setPlainText("Python 3.11 Interactive Console\nRenderFox API available\n>>> ")
        
        # Console input
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel(">>> "))
        
        self.console_input = QLineEdit()
        self.console_input.setFont(QFont("Consolas", 10))
        self.console_input.setPlaceholderText("Enter Python code...")
        
        self.execute_btn = QPushButton("Execute")
        
        input_layout.addWidget(self.console_input)
        input_layout.addWidget(self.execute_btn)
        
        layout.addWidget(self.console_output)
        layout.addLayout(input_layout)
        
        return widget
        

    # def populate_sample_scripts(self):
    #     """Populate the script library with sample scripts."""
    #     # Model Processing category
    #     model_processing = QTreeWidgetItem(["Model Processing", "", ""])
        
    #     batch_convert = QTreeWidgetItem(["Batch Format Converter", "Model Processing", "2024-08-29"])
    #     lod_generator = QTreeWidgetItem(["LOD Generator", "Model Processing", "2024-08-28"])
    #     texture_optimizer = QTreeWidgetItem(["Texture Optimizer", "Model Processing", "2024-08-27"])
        
    #     model_processing.addChild(batch_convert)
    #     model_processing.addChild(lod_generator)
    #     model_processing.addChild(texture_optimizer)
        
    #     # Utilities category
    #     utilities = QTreeWidgetItem(["Utilities", "", ""])
        
    #     file_organizer = QTreeWidgetItem(["File Organizer", "Utilities", "2024-08-26"])
    #     metadata_extractor = QTreeWidgetItem(["Metadata Extractor", "Utilities", "2024-08-25"])
    #     backup_tool = QTreeWidgetItem(["Backup Tool", "Utilities", "2024-08-24"])
        
    #     utilities.addChild(file_organizer)
    #     utilities.addChild(metadata_extractor)
    #     utilities.addChild(backup_tool)
        
    #     # Quality Assurance category
    #     qa = QTreeWidgetItem(["Quality Assurance", "", ""])
        
    #     model_validator = QTreeWidgetItem(["Model Validator", "Quality Assurance", "2024-08-23"])
    #     performance_tester = QTreeWidgetItem(["Performance Tester", "Quality Assurance", "2024-08-22"])
        
    #     qa.addChild(model_validator)
    #     qa.addChild(performance_tester)
        
    #     self.script_tree.addTopLevelItem(model_processing)
    #     self.script_tree.addTopLevelItem(utilities)
    #     self.script_tree.addTopLevelItem(qa)
        
    #     self.script_tree.expandAll()
        
    def populate_api_functions(self):
        """Populate API functions list."""
        api_functions = [
            "get_loaded_models()",
            "load_model(file_path)",
            "save_model(model, file_path)",
            "convert_model(model, target_format)",
            "generate_lod(model, levels)",
            "optimize_textures(model)",
            "validate_model(model)",
            "batch_process(models, operation)",
            "get_model_info(model)",
            "extract_metadata(model)",
            "create_render_job(model, settings)",
            "get_render_engines()",
            "set_render_settings(engine, settings)",
            "start_batch_render(jobs)",
            "get_processing_status()",
            "log_message(level, message)",
            "show_notification(title, message)",
            "get_app_settings()",
            "set_app_setting(key, value)"
        ]
        
        for func in api_functions:
            self.api_functions_list.addItem(func)
            
    def setup_connections(self):
        """Setup signal connections."""
        # Editor tab
        self.new_script_btn.clicked.connect(self.new_script)
        self.open_script_btn.clicked.connect(self.open_script)
        self.save_script_btn.clicked.connect(self.save_script)
        self.save_as_btn.clicked.connect(self.save_script_as)
        self.run_script_btn.clicked.connect(self.run_script)
        self.stop_script_btn.clicked.connect(self.stop_script)
        self.clear_output_btn.clicked.connect(self.clear_output)
        
        # Library tab
        self.script_tree.itemSelectionChanged.connect(self.preview_script)
        self.load_to_editor_btn.clicked.connect(self.load_script_to_editor)
        self.run_from_library_btn.clicked.connect(self.run_library_script)
        
        # API tab
        self.api_functions_list.itemSelectionChanged.connect(self.show_api_docs)
        self.insert_code_btn.clicked.connect(self.insert_api_code)
        
        # Console tab
        self.console_input.returnPressed.connect(self.execute_console_command)
        self.execute_btn.clicked.connect(self.execute_console_command)
        self.clear_console_btn.clicked.connect(self.clear_console)
        
    # def setup_script_environment(self):
    #     """Setup the script execution environment."""
    #     # Add RenderFox API to script globals
    #     self.script_globals.update({
    #         '__builtins__': builtins,
    #         'print': self.script_print,
    #         'get_loaded_models': self.api_get_loaded_models,
    #         'load_model': self.api_load_model,
    #         'convert_model': self.api_convert_model,
    #         'generate_lod': self.api_generate_lod,
    #         'batch_process': self.api_batch_process,
    #         # Add more API functions here
    #     })
        
    # def script_print(self, *args, **kwargs):
    #     """Custom print function for scripts."""
    #     message = ' '.join(str(arg) for arg in args)
    #     self.output_display.appendPlainText(message)
        
    # # API Functions (stubs - would be implemented to interact with actual RenderFox)
    # def api_get_loaded_models(self):
    #     """Get all loaded models."""
    #     return ["model1.obj", "model2.fbx", "model3.gltf"]
        
    # def api_load_model(self, file_path):
    #     """Load a model from file."""
    #     self.script_print(f"Loading model: {file_path}")
    #     return f"Model({file_path})"
        
    # def api_convert_model(self, model, target_format):
    #     """Convert model to target format."""
    #     self.script_print(f"Converting {model} to {target_format}")
    #     return f"Converted_{model}.{target_format}"
        
    # def api_generate_lod(self, model, levels):
    #     """Generate LOD variants."""
    #     self.script_print(f"Generating {levels} LOD levels for {model}")
    #     return [f"{model}_LOD{i}" for i in range(levels)]
        
    # def api_batch_process(self, models, operation):
    #     """Process multiple models."""
    #     self.script_print(f"Batch processing {len(models)} models with {operation}")
    #     return f"Processed {len(models)} models"
        
    def new_script(self):
        """Create a new script."""
        if self.code_editor.toPlainText().strip():
            reply = QMessageBox.question(self, "New Script", 
                                       "Current script has unsaved changes. Continue?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
                
        self.code_editor.clear()
        self.current_script_path = None
        self.file_info_label.setText("New Script - Unsaved")
        
    def open_script(self):
        """Open a script file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Script", "", "Python Files (*.py);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                self.code_editor.setPlainText(content)
                self.current_script_path = file_path
                self.file_info_label.setText(f"File: {os.path.basename(file_path)}")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open script: {str(e)}")
                
    def save_script(self):
        """Save the current script."""
        if self.current_script_path:
            self.save_script_to_path(self.current_script_path)
        else:
            self.save_script_as()
            
    def save_script_as(self):
        """Save script with a new name."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Script", "", "Python Files (*.py);;All Files (*)"
        )
        
        if file_path:
            self.save_script_to_path(file_path)
            
    def save_script_to_path(self, file_path):
        """Save script to specified path."""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.code_editor.toPlainText())
                
            self.current_script_path = file_path
            self.file_info_label.setText(f"File: {os.path.basename(file_path)} (Saved)")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save script: {str(e)}")
            
    def _execute_script_code(self, script_code: str):
        """Helper to execute script code."""
        if not script_code.strip():
            QMessageBox.warning(self, "Warning", "No script to execute!")
            return

        # Ensure engine exists
        if not hasattr(self, "script_engine") or self.script_engine is None:
            try:
                from src.processing.script_engine import ScriptEngine
                self.script_engine = ScriptEngine(self.main_window)
            except ImportError:
                QMessageBox.critical(self, "Error", "Script Engine not available.")
                return

        self.run_script_btn.setEnabled(False)
        self.stop_script_btn.setEnabled(True)
        self.output_display.clear()
        self.output_display.appendPlainText("=== Script Execution Started ===")
        
        # Switch to editor tab to show output
        self.scripting_tabs.setCurrentIndex(0)

        # Execute
        self.executor = self.script_engine.execute_script(script_code)
        self.executor.output_ready.connect(self.on_script_output)
        self.executor.error_occurred.connect(self.on_script_error)
        self.executor.execution_finished.connect(self.on_script_finished)
        self.executor.start()

    def run_script(self):
        """Run the current script from editor."""
        script_code = self.code_editor.toPlainText()
        self._execute_script_code(script_code)
    def on_script_finished(self, success, details):
        """Handle script completion."""
        self.run_script_btn.setEnabled(True)
        self.stop_script_btn.setEnabled(False)
        
        exec_time = details.get('execution_time', 0)
        
        if success:
            self.output_display.appendPlainText(f"=== Completed in {exec_time:.2f}s ===")
        else:
            self.output_display.appendPlainText("=== Script Execution Failed ===")
        
    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Ask a script still executing to stop, silence it, and wait for it to end.

        `output_ready`, `error_occurred` and `execution_finished` all write into the
        output pane, and a user script can run for its whole timeout - so this is the one
        run holder the close cannot be quick about. The executor's `stop` is the same
        request the Stop button already makes, and the handlers come off first either
        way: a script that finishes after the tab is gone would append its closing line to
        a text box that is no longer there. Returns the scripts still owed when the wait
        gave up.
        """
        return len(drain_attributes(self, ('executor',), timeout_ms))

    def stop_script(self):
        """Stop script execution."""
        if self.executor and self.executor.isRunning():
            self.script_engine.stop_execution()  # ✅ Use ScriptEngine method
            
        self.run_script_btn.setEnabled(True)
        self.stop_script_btn.setEnabled(False)
        self.output_display.appendPlainText("\n=== Script Execution Stopped ===")
        
    def on_script_output(self, output):
        """Handle script output."""
        self.output_display.appendPlainText(output)
        
    def on_script_error(self, error):
        """Handle script error."""
        self.output_display.appendPlainText(error)
        self.output_display.appendPlainText("An error occurred while executing the script.")
        
            
    def clear_output(self):
        """Clear the output display."""
        self.output_display.clear()
        
    def preview_script(self):
        """Preview selected script from library."""
        current_item = self.script_tree.currentItem()
        if not current_item or not current_item.parent():
            return
        
        # ✅ Get template from stored data
        template = current_item.data(0, Qt.ItemDataRole.UserRole)
        if template:
            self.script_preview.setPlainText(template['code'])
            self.script_info_label.setText(
                f"<b>{template['name']}</b><br>"
                f"<i>{template['description']}</i>"
            )
#     def preview_script(self):
#         """Preview selected script from library."""
#         current_item = self.script_tree.currentItem()
#         if current_item and current_item.parent():  # Only leaf items (scripts)
#             script_name = current_item.text(0)
            
#             # Sample script content based on name
#             sample_scripts = {
#                 "Batch Format Converter": '''"""
# Batch Format Converter
# Converts multiple models to a target format.
# """

# def batch_convert_models(source_folder, target_format):
#     """Convert all models in folder to target format."""
#     models = get_models_in_folder(source_folder)
    
#     for model in models:
#         print(f"Converting {model} to {target_format}")
#         converted = convert_model(model, target_format)
#         print(f"Saved: {converted}")
    
#     print(f"Converted {len(models)} models to {target_format}")

# # Usage
# batch_convert_models("./models/", "gltf")
# ''',
#                 "LOD Generator": '''"""
# LOD Generator
# Generates Level-of-Detail variants for models.
# """

# def generate_model_lods(model_path, lod_levels=[0.75, 0.5, 0.25]):
#     """Generate LOD variants for a model."""
#     model = load_model(model_path)
    
#     lod_models = []
#     for i, reduction in enumerate(lod_levels):
#         lod_model = reduce_model_complexity(model, reduction)
#         lod_path = f"{model_path}_LOD{i+1}"
#         save_model(lod_model, lod_path)
#         lod_models.append(lod_path)
#         print(f"Generated LOD {i+1}: {reduction*100}% complexity")
    
#     return lod_models

# # Usage
# lods = generate_model_lods("building.obj")
# print(f"Generated {len(lods)} LOD variants")
# '''
#             }
            
#             content = sample_scripts.get(script_name, f"# {script_name} script content would be here")
#             self.script_preview.setPlainText(content)
#             self.script_info_label.setText(f"Script: {script_name}")
            
    def load_script_to_editor(self):
        """Load selected script to editor."""
        current_item = self.script_tree.currentItem()
        if current_item and current_item.parent():
            content = self.script_preview.toPlainText()
            self.code_editor.setPlainText(content)
            self.scripting_tabs.setCurrentIndex(0)  # Switch to editor tab
            
    def run_library_script(self):
        """Run script from library."""
        current_item = self.script_tree.currentItem()
        if current_item and current_item.parent():
            # Get template from stored data or text
            template = current_item.data(0, Qt.ItemDataRole.UserRole)
            if template:
                content = template["code"]
            else:
                # Fallback if no data stored (legacy items)
                content = self.script_preview.toPlainText()
            
            if content:
                self._execute_script_code(content)
            
    def show_api_docs(self):
        """Show documentation for selected API function."""
        current_item = self.api_functions_list.currentItem()
        if not current_item:
            return
        
        # ✅ GET docs from ScriptEngine
        full_docs = self.script_engine.get_api_documentation()
        self.api_docs_display.setPlainText(full_docs)
#     def show_api_docs(self):
#         """Show documentation for selected API function."""
#         current_item = self.api_functions_list.currentItem()
#         if current_item:
#             func_name = current_item.text()
            
#             # Sample documentation
#             docs = {
#                 "get_loaded_models()": """
#                 <h3>get_loaded_models()</h3>
#                 <p><strong>Description:</strong> Returns a list of all currently loaded models in RenderFox.</p>
                
#                 <h4>Returns:</h4>
#                 <p><code>list</code> - List of model objects</p>
                
#                 <h4>Example:</h4>
#                 <pre><code>models = get_loaded_models()
# for model in models:
#     print(f"Model: {model.name}, Vertices: {model.vertex_count}")
# </code></pre>
#                 """,
#                 "load_model(file_path)": """
#                 <h3>load_model(file_path)</h3>
#                 <p><strong>Description:</strong> Loads a 3D model from the specified file path.</p>
                
#                 <h4>Parameters:</h4>
#                 <ul>
#                     <li><code>file_path</code> (str) - Path to the model file</li>
#                 </ul>
                
#                 <h4>Returns:</h4>
#                 <p><code>Model</code> - Loaded model object</p>
                
#                 <h4>Example:</h4>
#                 <pre><code>model = load_model("path/to/model.obj")
# print(f"Loaded: {model.name}")
# </code></pre>
#                 """
#             }
            
#             doc_content = docs.get(func_name, f"<h3>{func_name}</h3><p>Documentation not available.</p>")
#             self.api_docs_display.setHtml(doc_content)
            
    def insert_api_code(self):
        """Insert API code into editor."""
        current_item = self.api_functions_list.currentItem()
        if current_item:
            func_name = current_item.text()
            cursor = self.code_editor.textCursor()
            cursor.insertText(func_name)
            
    def execute_console_command(self):
        """Execute command in interactive console."""
        command = self.console_input.text().strip()
        if not command:
            return
        
        self.console_output.appendPlainText(f">>> {command}")
        
        try:
            # ✅ USE ScriptEngine API in globals
            console_globals = {
                'rfx': self.script_engine.api,
                'api': self.script_engine.api,
                '__builtins__': __builtins__
            }
            
            result = eval(command, console_globals)
            if result is not None:
                self.console_output.appendPlainText(str(result))
        except Exception as e:
            self.console_output.appendPlainText(f"Error: {str(e)}")
        
        self.console_input.clear()
        self.console_output.appendPlainText(">>> ")
        
    def clear_console(self):
        """Clear the console output."""
        self.console_output.clear()
        self.console_output.appendPlainText("Python 3.11 Interactive Console\nRenderFox API available\n>>> ")