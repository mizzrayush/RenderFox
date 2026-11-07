"""
RenderFox Script Engine
Provides Python script execution, API access, and script management for the Scripting Tab.
"""

import os
import sys
import json
import inspect
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from io import StringIO
import sqlite3

from PyQt6.QtCore import QObject, pyqtSignal, QThread


class ModelWrapper:
    """Wrapper for 3D model manipulation in scripts."""
    
    def __init__(self, mesh, file_path: str):
        self.mesh = mesh
        self.file_path = file_path
    
    def simplify(self, ratio: float = 0.5):
        """Simplify the mesh."""
        if hasattr(self.mesh, 'simplify_quadric_decimation'):
            target_faces = int(len(self.mesh.faces) * ratio)
            self.mesh = self.mesh.simplify_quadric_decimation(target_faces)
        return self

    def smooth(self, iterations: int = 1):
        """Smooth the mesh."""
        if hasattr(self.mesh, 'smooth'):
            self.mesh.smooth(iterations=iterations)
        return self
    
    def scale(self, factor: float):
        """Scale the mesh."""
        if hasattr(self.mesh, 'apply_scale'):
            self.mesh.apply_scale(factor)
        return self
    
    def center(self):
        """Center the mesh at origin."""
        if hasattr(self.mesh, 'vertices'):
            import numpy as np
            centroid = np.mean(self.mesh.vertices, axis=0)
            self.mesh.vertices -= centroid
        return self
    
    def save(self, output_path: str):
        """Save the mesh to file."""
        if hasattr(self.mesh, 'export'):
            self.mesh.export(output_path)
        return output_path
    
    def get_stats(self) -> Dict[str, Any]:
        """Get mesh statistics."""
        stats = {
            'vertices': len(self.mesh.vertices) if hasattr(self.mesh, 'vertices') else 0,
            'faces': len(self.mesh.faces) if hasattr(self.mesh, 'faces') else 0,
        }
        
        if hasattr(self.mesh, 'is_watertight'):
            stats['watertight'] = self.mesh.is_watertight
        if hasattr(self.mesh, 'volume'):
            stats['volume'] = float(self.mesh.volume)
        if hasattr(self.mesh, 'area'):
            stats['area'] = float(self.mesh.area)
        
        return stats


class ScriptAPI:
    """
    RenderFox Python API for user scripts.
    Provides safe access to application functionality.
    """
    
    def __init__(self, main_window=None):
        self.main_window = main_window
        self._current_model = None
        self._results = []
        
    def load_model(self, file_path: str):
        """Load a 3D model file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Model file not found: {file_path}")
        
        try:
            import trimesh
            mesh = trimesh.load(file_path)
            self._current_model = ModelWrapper(mesh, file_path)
            return self._current_model
        except Exception as e:
            raise RuntimeError(f"Failed to load model: {e}")
    
    def get_library_models(self, tags: Optional[List[str]] = None, 
                          format_filter: Optional[str] = None) -> List[Dict]:
        """Get models from library with optional filters."""
        if not self.main_window:
            return []
        
        try:
            if hasattr(self.main_window, 'library_tab') and hasattr(self.main_window.library_tab, 'library'):
                library_manager = self.main_window.library_tab.library
            elif hasattr(self.main_window, 'library_manager'):
                library_manager = self.main_window.library_manager
            else:
                return []
            
            if hasattr(library_manager, 'get_models'):
                models = library_manager.get_models()
            elif hasattr(library_manager, 'get_all_models'):
                models = library_manager.get_all_models()
            else:
                models = []
            
            # Apply filters
            if tags:
                models = [m for m in models if any(tag in str(m.get('tags', '')) for tag in tags)]
            if format_filter:
                models = [m for m in models if str(m.get('ext', '')).lower().endswith(format_filter.lower().replace('.', ''))]
            
            return models
        except Exception:
            return []
    
    def add_to_job_queue(self, model_path: str, software: str = "blender", 
                         output_path: Optional[str] = None, **settings):
        """Add a render job to the queue."""
        if not self.main_window:
            raise RuntimeError("No main window context available")
        
        from src.core.models import RenderJob, RenderStatus
        
        job = RenderJob(
            input_file=model_path,
            output_file=output_path or model_path.replace('.blend', '_render.png'),
            software=software,
            status=RenderStatus.PENDING
        )
        
        # Apply custom settings
        for key, value in settings.items():
            if hasattr(job, key):
                setattr(job, key, value)
        
        self.main_window.job_manager.add_job(job)
        return job.id
    
    def convert_format(self, input_file: str, output_format: str, 
                       output_file: Optional[str] = None) -> str:
        """Convert model to different format."""
        from src.processing.format_converter import FormatConverter
        
        converter = FormatConverter()
        
        if not output_file:
            base = os.path.splitext(input_file)[0]
            output_file = f"{base}.{str(output_format).lstrip('.')}"
        
        # `converter.convert()` does not exist - the API is convert_file, and it answers
        # with a dict, so the documented rfx.convert_format() raised AttributeError on
        # every call and a failure used to report nothing about why.
        result = converter.convert_file(input_file, output_file)
        
        if result['success']:
            return output_file
        raise RuntimeError(f"Format conversion failed: {result['message']}")
    
    def generate_lod(self, input_file: str, levels: int = 3, 
                     ratios: Optional[List[float]] = None) -> List[str]:
        """Generate LOD levels for a model."""
        from src.processing.lod_generator import LODGenerator
        
        generator = LODGenerator()
        
        if not ratios:
            ratios = [0.75, 0.5, 0.25][:levels]
        
        output_files = []
        for i, ratio in enumerate(ratios):
            base = os.path.splitext(input_file)[0]
            output_file = f"{base}_LOD{i+1}.obj"
            
            result = generator.generate_single_lod(input_file, output_file, ratio)
            if result['success']:
                output_files.append(output_file)
        
        return output_files
    
    def batch_process(self, files: List[str], operation: Callable, **kwargs) -> List[Any]:
        """Process multiple files with a custom operation."""
        results = []
        for file in files:
            try:
                result = operation(file, **kwargs)
                results.append({'file': file, 'success': True, 'result': result})
            except Exception as e:
                results.append({'file': file, 'success': False, 'error': str(e)})
        
        return results
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message."""
        print(f"[{level}] {message}")
        self._results.append(f"[{level}] {message}")
    
    def get_results(self) -> List[str]:
        """Get accumulated results."""
        return self._results.copy()
    
    def clear_results(self):
        """Clear accumulated results."""
        self._results.clear()

    def bake_texture(self, high_poly: str, low_poly: str, output_dir: str, 
                    resolution: int = 2048, maps: List[str] = None) -> bool:
        """
        Bake textures from high poly to low poly mesh.
        maps: List of map types ['normal', 'diffuse', 'ao']. Default: all.
        """
        try:
            from src.processing.texture_baker import TextureBaker
            baker = TextureBaker()
            
            if maps is None:
                maps = ['normal', 'diffuse', 'ao']
                
            bake_normals = 'normal' in maps
            bake_diffuse = 'diffuse' in maps
            bake_ao = 'ao' in maps
            
            baker.bake(high_poly, low_poly, output_dir, resolution, 
                      bake_normals, bake_diffuse, bake_ao)
            return True
        except Exception as e:
            self.log(f"Baking failed: {str(e)}", "ERROR")
            return False

    def set_lighting(self, rotation: float = 0.0, blur: float = 0.0, 
                    intensity: float = 1.0, light_influence: float = 0.0):
        """
        Set advanced lighting parameters for the viewport.
        """
        if not self.main_window:
            return
            
        # Access the rendering tab via main window
        # Assuming main_window has a 'rendering_tab' attribute or we can find it
        try:
            # This depends on how main_window exposes tabs. 
            # Let's assume standard access pattern or signal
            if hasattr(self.main_window, 'rendering_tab'):
                self.main_window.rendering_tab.update_lighting(
                    rotation, blur, intensity, light_influence
                )
                self.log(f"Lighting updated: Rot={rotation}, Blur={blur}")
            else:
                self.log("Rendering tab not accessible", "WARNING")
        except Exception as e:
            self.log(f"Failed to set lighting: {str(e)}", "ERROR")
    



class ScriptExecutor(QThread):
    """Thread for executing user scripts safely."""
    
    output_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    execution_finished = pyqtSignal(bool, dict)
    
    def __init__(self, script_code: str, api: ScriptAPI, timeout: int = 300):
        super().__init__()
        self.script_code = script_code
        self.api = api
        self.timeout = timeout
        self._stop_requested = False
    
    def run(self):
        """Execute the script in a controlled environment."""
        start_time = datetime.now()
        
        # Redirect stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        
        try:
            # Create restricted globals
            safe_globals = {
                '__builtins__': {
                    'print': print,
                    'len': len,
                    'range': range,
                    'enumerate': enumerate,
                    'zip': zip,
                    'map': map,
                    'filter': filter,
                    'str': str,
                    'int': int,
                    'float': float,
                    'bool': bool,
                    'list': list,
                    'dict': dict,
                    'tuple': tuple,
                    'set': set,
                    'abs': abs,
                    'min': min,
                    'max': max,
                    'sum': sum,
                    'round': round,
                    'sorted': sorted,
                    'reversed': reversed,
                    'True': True,
                    'False': False,
                    'None': None,
                },
                'rfx': self.api,
                'api': self.api,
            }
            
            # Execute script
            exec(self.script_code, safe_globals)
            
            # Get output
            output = sys.stdout.getvalue()
            errors = sys.stderr.getvalue()
            
            if output:
                self.output_ready.emit(output)
            if errors:
                self.error_occurred.emit(errors)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            self.execution_finished.emit(True, {
                'execution_time': execution_time,
                'output': output,
                'errors': errors
            })
            
        except Exception as e:
            error_msg = f"Script execution failed:\n{traceback.format_exc()}"
            self.error_occurred.emit(error_msg)
            self.execution_finished.emit(False, {
                'error': str(e),
                'traceback': traceback.format_exc()
            })
        
        finally:
            # Restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    def stop(self):
        """Request script execution to stop."""
        self._stop_requested = True
        self.terminate()


class ScriptLibrary:
    """Manages script storage, categorization, and retrieval."""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'scripts.db')
        
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the scripts database."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                code TEXT NOT NULL,
                category TEXT,
                tags TEXT,
                created_at TEXT,
                modified_at TEXT,
                execution_count INTEGER DEFAULT 0,
                favorite BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS script_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_id INTEGER,
                executed_at TEXT,
                execution_time REAL,
                success BOOLEAN,
                output TEXT,
                error TEXT,
                FOREIGN KEY (script_id) REFERENCES scripts(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_script(self, name: str, code: str, description: str = "", 
                   category: str = "General", tags: Optional[List[str]] = None) -> int:
        """Save a script to the library."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        tags_str = ",".join(tags) if tags else ""
        now = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO scripts (name, description, code, category, tags, created_at, modified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, description, code, category, tags_str, now, now))
        
        script_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return script_id
    
    def update_script(self, script_id: int, **kwargs):
        """Update an existing script."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        allowed_fields = ['name', 'description', 'code', 'category', 'tags', 'favorite']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in kwargs:
                updates.append(f"{field} = ?")
                value = kwargs[field]
                if field == 'tags' and isinstance(value, list):
                    value = ",".join(value)
                values.append(value)
        
        if updates:
            updates.append("modified_at = ?")
            values.append(datetime.now().isoformat())
            values.append(script_id)
            
            query = f"UPDATE scripts SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()
        
        conn.close()
    
    def delete_script(self, script_id: int):
        """Delete a script from the library."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
        cursor.execute("DELETE FROM script_history WHERE script_id = ?", (script_id,))
        
        conn.commit()
        conn.close()
    
    def get_script(self, script_id: int) -> Optional[Dict]:
        """Get a script by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM scripts WHERE id = ?", (script_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_dict(row)
        return None
    
    def get_all_scripts(self, category: Optional[str] = None, 
                       favorite_only: bool = False) -> List[Dict]:
        """Get all scripts, optionally filtered."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM scripts WHERE 1=1"
        params = []
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if favorite_only:
            query += " AND favorite = 1"
        
        query += " ORDER BY modified_at DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row) for row in rows]
    
    def search_scripts(self, search_term: str) -> List[Dict]:
        """Search scripts by name, description, or tags."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = '''
            SELECT * FROM scripts 
            WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
            ORDER BY modified_at DESC
        '''
        search_pattern = f"%{search_term}%"
        
        cursor.execute(query, (search_pattern, search_pattern, search_pattern))
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row) for row in rows]
    
    def log_execution(self, script_id: int, execution_time: float, 
                     success: bool, output: str = "", error: str = ""):
        """Log script execution to history."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Add to history
        cursor.execute('''
            INSERT INTO script_history (script_id, executed_at, execution_time, success, output, error)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (script_id, datetime.now().isoformat(), execution_time, success, output, error))
        
        # Increment execution count
        cursor.execute('''
            UPDATE scripts SET execution_count = execution_count + 1 WHERE id = ?
        ''', (script_id,))
        
        conn.commit()
        conn.close()
    
    def get_execution_history(self, script_id: int, limit: int = 10) -> List[Dict]:
        """Get execution history for a script."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM script_history 
            WHERE script_id = ? 
            ORDER BY executed_at DESC 
            LIMIT ?
        ''', (script_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._history_row_to_dict(row) for row in rows]
    
    def get_categories(self) -> List[str]:
        """Get all unique categories."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT category FROM scripts ORDER BY category")
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        return categories
    
    def _row_to_dict(self, row) -> Dict:
        """Convert database row to dictionary."""
        return {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'code': row[3],
            'category': row[4],
            'tags': row[5].split(',') if row[5] else [],
            'created_at': row[6],
            'modified_at': row[7],
            'execution_count': row[8],
            'favorite': bool(row[9])
        }
    
    def _history_row_to_dict(self, row) -> Dict:
        """Convert history row to dictionary."""
        return {
            'id': row[0],
            'script_id': row[1],
            'executed_at': row[2],
            'execution_time': row[3],
            'success': bool(row[4]),
            'output': row[5],
            'error': row[6]
        }


class ScriptTemplates:
    """Provides pre-built script templates for common tasks."""
    
    @staticmethod
    def get_all_templates() -> List[Dict[str, str]]:
        """Get all available templates."""
        return [
            {
                'name': 'Batch Convert Models',
                'category': 'Conversion',
                'description': 'Convert multiple models to a different format',
                'code': '''# Batch Format Conversion
import os

# Configuration
input_folder = "path/to/input/models"
output_format = "obj"

# Get all model files
input_files = [f for f in os.listdir(input_folder) if f.endswith(('.fbx', '.dae', '.3ds'))]

# Convert each file
for file in input_files:
    input_path = os.path.join(input_folder, file)
    try:
        output_path = rfx.convert_format(input_path, output_format)
        rfx.log(f"Converted: {file} -> {output_path}", "SUCCESS")
    except Exception as e:
        rfx.log(f"Failed: {file} - {str(e)}", "ERROR")
'''
            },
            {
                'name': 'Generate LODs for Library',
                'category': 'Optimization',
                'description': 'Generate LOD levels for all models in library',
                'code': '''# Generate LODs for Library Models
# Get models from library
models = rfx.get_library_models(tags=['high-poly'])

for model in models:
    model_path = model['file_path']
    rfx.log(f"Processing: {model['name']}")
    
    try:
        lod_files = rfx.generate_lod(model_path, levels=3, ratios=[0.75, 0.5, 0.25])
        rfx.log(f"Generated {len(lod_files)} LOD levels", "SUCCESS")
    except Exception as e:
        rfx.log(f"LOD generation failed: {str(e)}", "ERROR")
'''
            },
            {
                'name': 'Model Quality Analysis',
                'category': 'Analysis',
                'description': 'Analyze and report model quality metrics',
                'code': '''# Model Quality Analysis
model_path = "path/to/model.obj"

# Load model
model = rfx.load_model(model_path)

# Get statistics
stats = model.get_stats()

# Report
rfx.log("=== Model Analysis ===")
rfx.log(f"Vertices: {stats['vertices']:,}")
rfx.log(f"Faces: {stats['faces']:,}")
if 'watertight' in stats:
    rfx.log(f"Watertight: {stats['watertight']}")
if 'volume' in stats:
    rfx.log(f"Volume: {stats['volume']:.2f}")
if 'area' in stats:
    rfx.log(f"Surface Area: {stats['area']:.2f}")
'''
            },
            {
                'name': 'Batch Simplify and Export',
                'category': 'Processing',
                'description': 'Simplify multiple models and export',
                'code': '''# Batch Simplification
import os

input_folder = "path/to/input"
output_folder = "path/to/output"
simplify_ratio = 0.5

os.makedirs(output_folder, exist_ok=True)

# Process each model
for file in os.listdir(input_folder):
    if not file.endswith(('.obj', '.ply', '.stl')):
        continue
    
    input_path = os.path.join(input_folder, file)
    output_path = os.path.join(output_folder, file)
    
    try:
        # Load, simplify, and save
        model = rfx.load_model(input_path)
        model.simplify(ratio=simplify_ratio).save(output_path)
        rfx.log(f"Simplified: {file}", "SUCCESS")
    except Exception as e:
        rfx.log(f"Failed: {file} - {str(e)}", "ERROR")
'''
            },
            {
                'name': 'Auto-Tag Models by Size',
                'category': 'Library',
                'description': 'Automatically tag models based on complexity',
                'code': '''# Auto-Tag Models by Complexity
models = rfx.get_library_models()

for model in models:
    try:
        mesh = rfx.load_model(model['file_path'])
        stats = mesh.get_stats()
        
        vertex_count = stats['vertices']
        
        # Determine tag based on vertex count
        if vertex_count < 10000:
            complexity = 'low-poly'
        elif vertex_count < 50000:
            complexity = 'medium-poly'
        else:
            complexity = 'high-poly'
        
        rfx.log(f"{model['name']}: {vertex_count:,} vertices -> {complexity}")
        
    except Exception as e:
        rfx.log(f"Failed to process {model['name']}: {str(e)}", "ERROR")
'''
            },
            {
                'name': 'Batch Render Queue',
                'category': 'Rendering',
                'description': 'Add multiple models to render queue',
                'code': '''# Batch Add to Render Queue
models = rfx.get_library_models(tags=['render-ready'])

for model in models:
    model_path = model['file_path']
    output_path = model_path.replace('.blend', '_render.png')
    
    try:
        job_id = rfx.add_to_job_queue(
            model_path=model_path,
            software='blender',
            output_path=output_path,
            resolution_x=1920,
            resolution_y=1080
        )
        rfx.log(f"Added to queue: {model['name']} (Job ID: {job_id})")
    except Exception as e:
        rfx.log(f"Failed: {model['name']} - {str(e)}", "ERROR")
'''
            }
        ]
    
    @staticmethod
    def get_template(name: str) -> Optional[Dict[str, str]]:
        """Get a specific template by name."""
        templates = ScriptTemplates.get_all_templates()
        for template in templates:
            if template['name'] == name:
                return template
        return None


class ScriptEngine:
    """Main script engine coordinating all scripting functionality."""
    
    def __init__(self, main_window=None):
        self.main_window = main_window
        self.api = ScriptAPI(main_window)
        self.library = ScriptLibrary()
        self.templates = ScriptTemplates()
        self.current_executor = None
    
    def execute_script(self, code: str, timeout: int = 300) -> ScriptExecutor:
        """Execute a script and return the executor thread."""
        self.current_executor = ScriptExecutor(code, self.api, timeout)
        return self.current_executor
    
    def stop_execution(self):
        """Stop current script execution."""
        if self.current_executor and self.current_executor.isRunning():
            self.current_executor.stop()
    
    def validate_script(self, code: str) -> Dict[str, Any]:
        """Validate script syntax without executing."""
        try:
            compile(code, '<string>', 'exec')
            return {'valid': True, 'error': None}
        except SyntaxError as e:
            return {
                'valid': False,
                'error': str(e),
                'line': e.lineno,
                'offset': e.offset
            }
    
    def api_surface(self) -> List[str]:
        """The calls a script can make, read off the object the executor hands it as `rfx`.

        The Scripting pane lists these and inserts the selected one into the editor, so each
        line here has to run: the name and every parameter come from the method itself.
        """
        calls = []
        for name, method in inspect.getmembers(self.api, predicate=inspect.ismethod):
            if name.startswith('_'):
                continue
            parts = []
            for parameter in inspect.signature(method).parameters.values():
                if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                    parts.append('**' + parameter.name)
                elif parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                    parts.append('*' + parameter.name)
                elif parameter.default is inspect.Parameter.empty:
                    parts.append(parameter.name)
                else:
                    parts.append(f'{parameter.name}={parameter.default!r}')
            calls.append(f'rfx.{name}({", ".join(parts)})')
        return calls

    def get_api_documentation(self) -> str:
        """Get comprehensive API documentation."""
        return """
# RenderFox Scripting API Documentation

## Main API Object: `rfx` or `api`

### Model Loading and Manipulation

**load_model(file_path: str) -> ModelWrapper**
Load a 3D model file and return a wrapper object.

Example:
```python
model = rfx.load_model("path/to/model.obj")
```

### Library Access

**get_library_models(tags=None, format_filter=None) -> List[Dict]**
Get models from the library with optional filters.

Example:
```python
# Get all models
models = rfx.get_library_models()

# Get models with specific tag
high_poly = rfx.get_library_models(tags=['high-poly'])

# Get OBJ models only
obj_models = rfx.get_library_models(format_filter='obj')
```

### Job Queue Management

**add_to_job_queue(model_path, software='blender', output_path=None, **settings) -> int**
Add a render job to the processing queue.

Example:
```python
job_id = rfx.add_to_job_queue(
    model_path="model.blend",
    software="blender",
    output_path="render.png",
    resolution_x=1920,
    resolution_y=1080
)
```

### Format Conversion

**convert_format(input_file, output_format, output_file=None) -> str**
Convert a model to a different format.

Example:
```python
output = rfx.convert_format("model.fbx", "obj")
```

### LOD Generation

**generate_lod(input_file, levels=3, ratios=None) -> List[str]**
Generate Level of Detail models.

Example:
```python
lod_files = rfx.generate_lod("model.obj", levels=3, ratios=[0.75, 0.5, 0.25])
```

### Batch Processing

**batch_process(files, operation, **kwargs) -> List[Any]**
Process multiple files with a custom operation.

### Logging

**log(message, level='INFO')**
Log a message to the output.

**get_results() -> List[str]**
Get accumulated log messages.

**clear_results()**
Clear accumulated messages.

## ModelWrapper Methods

**simplify(ratio=0.5) -> ModelWrapper**
Simplify the mesh by reducing polygon count.

**smooth(iterations=1) -> ModelWrapper**
Smooth the mesh surface.

**scale(factor) -> ModelWrapper**
Scale the mesh uniformly.

**center() -> ModelWrapper**
Center the mesh at the origin.

**save(output_path) -> str**
Save the mesh to a file.

**get_stats() -> Dict**
Get mesh statistics (vertices, faces, volume, etc.)

## Example Scripts

### Basic Model Processing
```python
# Load model
model = rfx.load_model("input.obj")

# Process
model.center().scale(2.0).simplify(0.5).smooth(3)

# Save
model.save("output.obj")

# Get info
stats = model.get_stats()
rfx.log(f"Processed model: {stats['vertices']} vertices, {stats['faces']} faces")
```

### Batch Conversion
```python
import os

input_folder = "models/"
for file in os.listdir(input_folder):
    if file.endswith('.fbx'):
        input_path = os.path.join(input_folder, file)
        rfx.convert_format(input_path, 'obj')
        rfx.log(f"Converted: {file}")
```
"""
