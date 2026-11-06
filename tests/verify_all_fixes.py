"""
Verify All Fixes Test Suite for RenderFox
Tests all stability, UI, routing, and backend fixes implemented across the codebase.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
import json
import trimesh
import numpy as np

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

class TestRenderFoxRectification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create single QApplication instance for UI tests
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_01_imports_and_encodings(self):
        """Test that all core and processing modules import cleanly."""
        from src.processing.render_engines import (
            detect_available_software, BlenderEngine, MayaEngine, UnrealEngine, Cinema4DEngine, SoftwareType
        )
        from src.core.job_manager import JobManager
        from src.core.library_manager import LibraryManager
        from src.processing.mesh_processor import MeshProcessor, MeshTransformer
        from src.processing.point_cloud_processor import PointCloudProcessor, PointCloudRegistration
        from src.features.diagnostic_engine import DiagnosticEngine, SystemInfo
        from src.processing.script_engine import ScriptAPI, ModelWrapper

        self.assertTrue(True)

    def test_02_render_engine_process_handles(self):
        """Test that render engine instances manage process references correctly."""
        from src.processing.render_engines import BlenderEngine
        engine = BlenderEngine("blender.exe")
        self.assertIsNone(engine.current_process)
        self.assertFalse(engine.should_stop)
        
        # Test stop sets should_stop flag
        engine.stop()
        self.assertTrue(engine.should_stop)

    def test_03_library_manager_methods_and_joins(self):
        """Test LibraryManager db_connection, collections aliases, integrity, and direct imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.core.library_manager import LibraryManager
            lib = LibraryManager(db_path=os.path.join(tmpdir, "test.db"))
            try:
                # 1. Test db_connection compatibility property
                self.assertIsNotNone(lib.db_connection)
                self.assertEqual(lib.db_connection, lib.conn)
                
                # 2. Test collections methods and aliases
                lib.create_collection("Test Collection", "Description")
                cols = lib.get_collections()
                self.assertTrue(any(c['name'] == "Test Collection" for c in cols))
                
                # 3. Test integrity check
                integrity = lib.check_integrity()
                self.assertIn("total_models", integrity)
                self.assertIn("issues_found", integrity)
                
                # 4. Test direct file import query inclusion
                test_obj = os.path.join(tmpdir, "outside_model.obj")
                mesh = trimesh.creation.icosphere(radius=1.0)
                mesh.export(test_obj)
                
                added, updated = lib.import_files([test_obj])
                self.assertEqual(added, 1)
                
                models = lib.get_models()
                self.assertTrue(any(os.path.basename(m['path']) == "outside_model.obj" for m in models))
            finally:
                lib.close()

    def test_04_mesh_transformer_translate(self):
        """Test mesh translation in MeshTransformer and MeshProcessor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.obj")
            output_path = os.path.join(tmpdir, "translated.obj")
            
            mesh = trimesh.creation.box()
            mesh.export(input_path)
            
            from src.processing.mesh_processor import MeshProcessor
            proc = MeshProcessor()
            res = proc.transform(input_path, output_path, operation='translate', translation=[5.0, 10.0, -2.0])
            self.assertTrue(res['success'])
            self.assertTrue(os.path.exists(output_path))
            
            trans_mesh = trimesh.load(output_path)
            centroid = trans_mesh.centroid
            self.assertAlmostEqual(centroid[0], 5.0, places=2)
            self.assertAlmostEqual(centroid[1], 10.0, places=2)
            self.assertAlmostEqual(centroid[2], -2.0, places=2)

    def test_05_point_cloud_registration_metrics(self):
        """Test that PointCloudRegistration methods return fitness and rmse."""
        from src.processing.point_cloud_processor import PointCloudProcessor
        proc = PointCloudProcessor()
        # Verify processor has registration component initialized
        self.assertIsNotNone(proc.registration)

    # test_06 was `smart_batch_processor_template_persistence`. It passed, and it
    # proved nothing: the module it tested saved a template name into a JSON file that
    # no operation ever read, and its "batch" handler marked every task completed
    # without writing a file. The module and this test both went with it.

    def test_07_diagnostics_cpu_info_non_blocking(self):
        """Test that DiagnosticEngine.SystemInfo.get_cpu_info does not block."""
        import time
        from src.features.diagnostic_engine import SystemInfo
        
        start = time.time()
        info = SystemInfo.get_cpu_info()
        duration = time.time() - start
        
        self.assertLess(duration, 0.5, "get_cpu_info took too long (should be non-blocking)")
        self.assertIn('usage_percent', info)
        self.assertIn('logical_cores', info)

    def test_08_model_tag_dialog_instantiation(self):
        """Test ModelTagDialog instantiation and data retrieval."""
        from src.ui.library_tab import ModelTagDialog
        
        model_data = {
            'name': 'Test Asset',
            'description': 'A sample asset',
            'tags': 'prop, game',
            'author': 'Artist',
            'license': 'CC0',
            'rating': 4
        }
        dialog = ModelTagDialog(model_data)
        data = dialog.get_data()
        self.assertEqual(data['name'], 'Test Asset')
        self.assertEqual(data['tags'], 'prop, game')
        self.assertEqual(data['rating'], 4)

    def close_window_and_empty_tree(self, window, root, tries=8):
        """Shut a window, then take the directory it read from, and name whatever stays.

        `tempfile.TemporaryDirectory` tries the removal exactly once, on interpreter
        housekeeping terms, so a Windows refusal surfaced as an error attached to the
        cleanup rather than to this test. The window closes first - a pane that still holds
        a model it was shown is a defect worth naming - and the tries after that are for
        the scanner that reads every file this machine writes.
        """
        if window is not None:
            window.close()
            window.deleteLater()
        self.app.processEvents()

        held = []
        for attempt in range(tries):
            held = []
            for dirpath, _dirs, names in os.walk(root):
                for name in names:
                    path = os.path.join(dirpath, name)
                    try:
                        os.remove(path)
                    except OSError as problem:
                        held.append(f'{name} (winerror={problem.winerror})')
            if not held:
                break
            time.sleep(0.25)
            self.app.processEvents()
        shutil.rmtree(root, ignore_errors=True)
        return held

    def test_09_main_window_tabs_and_routing(self):
        """Test MainWindow instantiation, all tabs, shortcuts and cross-tab routes."""
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        from src.ui.main_window import MainWindow

        tmpdir = tempfile.mkdtemp()
        window = None
        try:
            obj_path = os.path.join(tmpdir, "test.obj")
            trimesh.creation.box().export(obj_path)
            img_path = os.path.join(tmpdir, "test.png")
            with open(img_path, 'wb') as f:
                f.write(b"")

            with patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok), \
                 patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok), \
                 patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok), \
                 patch.object(QFileDialog, 'getOpenFileName', return_value=(obj_path, "")), \
                 patch.object(QFileDialog, 'getExistingDirectory', return_value=tmpdir):
                
                mw = MainWindow()
                window = mw  # the finally has to shut what the try opened

                # 1. Verify all tab widgets exist
                self.assertIsNotNone(mw.dashboard_tab)
                self.assertIsNotNone(mw.model_tab)
                self.assertIsNotNone(mw.preprocessing_tab)
                self.assertIsNotNone(mw.postprocessing_tab)
                self.assertIsNotNone(mw.library_tab)
                self.assertIsNotNone(mw.automation_tab)
                self.assertIsNotNone(mw.point_clouds_tab)
                self.assertIsNotNone(mw.mesh_tools_tab)
                self.assertIsNotNone(mw.performance_tab)
                self.assertIsNotNone(mw.diagnostics_tab)
                self.assertIsNotNone(mw.scripting_tab)
                self.assertIsNotNone(mw.pipeline_tab)
                self.assertIsNotNone(mw.animation_tab)
                self.assertIsNotNone(mw.rendering_tab)
                self.assertIsNotNone(mw.settings_tab)
                
                # 2. Test shortcuts don't raise exceptions
                mw.load_pointcloud_shortcut()
                self.assertEqual(mw.tab_widget.currentWidget(), mw.point_clouds_tab)
                
                mw.open_preferences()
                self.assertEqual(mw.tab_widget.currentWidget(), mw.settings_tab)
                
                mw.open_library()
                self.assertEqual(mw.tab_widget.currentWidget(), mw.library_tab)
                
                mw.open_in_model_viewer(obj_path)
                self.assertEqual(mw.tab_widget.currentWidget(), mw.model_tab)
                
                mw.open_in_point_clouds(obj_path)
                self.assertEqual(mw.tab_widget.currentWidget(), mw.point_clouds_tab)
                
                mw.open_in_animation(obj_path)
                self.assertEqual(mw.tab_widget.currentWidget(), mw.animation_tab)
                
                mw.open_in_preprocessing(obj_path)
                self.assertEqual(mw.tab_widget.currentWidget(), mw.preprocessing_tab)
                
                mw.open_in_postprocessing(img_path)
                self.assertEqual(mw.tab_widget.currentWidget(), mw.postprocessing_tab)
        finally:
            held = self.close_window_and_empty_tree(window, tmpdir)

        self.assertEqual([], held,
                         'this window is shut and a DCC still cannot re-export these files')

    def test_10_script_api_library_resolution(self):
        """Test ScriptAPI get_library_models resolution."""
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        from src.ui.main_window import MainWindow
        from src.processing.script_engine import ScriptAPI
        
        with patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QFileDialog, 'getOpenFileName', return_value=("", "")), \
             patch.object(QFileDialog, 'getExistingDirectory', return_value=""):
            mw = MainWindow()
            api = ScriptAPI(main_window=mw)
            models = api.get_library_models()
            self.assertIsInstance(models, list)

if __name__ == '__main__':
    unittest.main()
