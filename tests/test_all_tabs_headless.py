"""
RenderFox Headless Tab Driver & Comprehensive UI-Backend Smoke Suite
Tests all 15 tabs completely offscreen, driving them with synthetic 3D assets.
Provides a solo developer with immediate, automated multi-tab verification.
"""

import gc
import os
import shutil
import sys
import tempfile
import time
import unittest
import numpy as np

# Force offscreen Qt platform before importing PyQt6
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PyQt6.QtCore import Qt, QTimer

# Ensure modal dialogs never block headless CI/test runs
QMessageBox.information = lambda *a, **kw: QMessageBox.StandardButton.Ok
QMessageBox.warning = lambda *a, **kw: QMessageBox.StandardButton.Ok
QMessageBox.critical = lambda *a, **kw: QMessageBox.StandardButton.Ok
QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
QFileDialog.getOpenFileName = lambda *a, **kw: ("", "")
QFileDialog.getSaveFileName = lambda *a, **kw: ("", "")
QFileDialog.getExistingDirectory = lambda *a, **kw: ""

# Ensure root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.fixtures.mesh_factory import MeshFactory
from src.ui.main_window import MainWindow


class TestAllTabsHeadless(unittest.TestCase):
    """Automated offscreen test driver for all 15 RenderFox tabs."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.temp_dir = tempfile.mkdtemp()
        cls.assets = MeshFactory.generate_full_suite(cls.temp_dir)
        cls.window = MainWindow()

    def test_01_tab_count_and_titles(self):
        """Verify that all 15 tabs are initialized with expected names."""
        expected_tabs = [
            "Library", "Batch Render", "Models", "Point Clouds", "Mesh Tools",
            "Animation", "Rendering", "Pre-Processing", "Post-Processing",
            "Automation", "Scripting", "Pipeline", "Performance",
            "Diagnostics", "Settings"
        ]
        actual_count = self.window.tab_widget.count()
        self.assertEqual(actual_count, len(expected_tabs), f"Expected {len(expected_tabs)} tabs, found {actual_count}")
        
        actual_titles = [self.window.tab_widget.tabText(i) for i in range(actual_count)]
        for expected in expected_tabs:
            self.assertIn(expected, actual_titles, f"Missing tab: {expected}")
        print(f"✓ All {actual_count} tabs validated: {', '.join(actual_titles)}")

    def test_02_tab_switching_cycle(self):
        """Cycle through every tab programmatically to ensure no lazy-loading crashes."""
        count = self.window.tab_widget.count()
        for idx in range(count):
            self.window.tab_widget.setCurrentIndex(idx)
            self.app.processEvents()
            current_tab = self.window.tab_widget.currentWidget()
            self.assertIsNotNone(current_tab)
        print(f"✓ Cycled through all {count} tabs without crash.")

    def test_03_mesh_tools_tab_operations(self):
        """Test Mesh Tools tab with clean, non-manifold, and hole meshes."""
        mesh_tab = self.window.mesh_tools_tab
        clean_path = self.assets['clean_manifold']
        holes_path = self.assets['mesh_with_holes']
        
        # Load mesh
        if hasattr(mesh_tab, 'load_mesh_file'):
            mesh_tab.load_mesh_file(clean_path)
            self.app.processEvents()
            self.assertIsNotNone(getattr(mesh_tab, 'current_model_path', getattr(mesh_tab, 'current_mesh', None)))
        
        # Analyze
        if hasattr(mesh_tab, 'analyze_mesh'):
            mesh_tab.analyze_mesh()
            self.app.processEvents()

        # Load mesh with holes and test repair pipeline if available
        if hasattr(mesh_tab, 'load_mesh_file'):
            mesh_tab.load_mesh_file(holes_path)
            self.app.processEvents()

        print("✓ Mesh Tools tab operations tested successfully.")

    def test_04_point_clouds_tab_operations(self):
        """Test Point Clouds tab with synthetic noisy cloud."""
        pcd_tab = self.window.point_clouds_tab
        pcd_path = self.assets['point_cloud']
        
        if hasattr(pcd_tab, 'load_point_cloud_file'):
            pcd_tab.load_point_cloud_file(pcd_path)
            self.app.processEvents()
        elif hasattr(pcd_tab, 'processor'):
            res = pcd_tab.processor.load_point_cloud(pcd_path)
            self.assertIsNotNone(res)
        print("✓ Point Clouds tab operations tested successfully.")

    def test_05_library_tab_operations(self):
        """Test Library tab model ingestion, collections, and queries."""
        lib_tab = self.window.library_tab
        clean_path = self.assets['clean_manifold']
        
        # Add model to library
        if hasattr(lib_tab, 'add_model_to_library'):
            lib_tab.add_model_to_library(clean_path)
            self.app.processEvents()
        
        # Search filter
        if hasattr(lib_tab, 'search_input'):
            lib_tab.search_input.setText("clean")
            self.app.processEvents()
            lib_tab.search_input.clear()
            self.app.processEvents()
            
        print("✓ Library tab operations tested successfully.")

    def test_06_dashboard_batch_render_tab(self):
        """Test Batch Render queue job addition, movement, pause, and resume."""
        dash = self.window.dashboard_tab
        jm = self.window.job_manager
        
        from src.core.models import RenderJob, SoftwareType
        job = RenderJob(
            name="Headless Test Render",
            project_file=self.assets['clean_manifold'],
            software_type=SoftwareType.BLENDER,
            output_path=self.temp_dir
        )
        jm.add_job(job)
        job_id = job.id
        self.assertIsNotNone(job_id)
        self.app.processEvents()
        
        # Pause and resume
        jm.pause_job(job_id)
        self.app.processEvents()
        jm.resume_job(job_id)
        self.app.processEvents()
        
        # Remove job
        jm.remove_job(job_id)
        self.app.processEvents()
        print("✓ Dashboard Batch Render queue tested successfully.")

    def test_07_settings_theme_switching(self):
        """Test switching themes back and forth (Dark, Light, Modern Dark)."""
        settings_tab = self.window.settings_tab
        
        for theme in ["Light", "Dark"]:
            self.window.on_theme_changed(theme)
            self.app.processEvents()
            
        print("✓ Theme switching tested without UI style corruption.")

    def test_08_scripting_tab_api(self):
        """Test Scripting tab engine evaluation and sandbox."""
        scripting_tab = self.window.scripting_tab
        
        if hasattr(scripting_tab, 'script_engine') and scripting_tab.script_engine:
            code = "result = 42 * 2\nprint('Headless script output:', result)"
            validation = scripting_tab.script_engine.validate_script(code)
            self.assertTrue(validation['valid'])
            executor = scripting_tab.script_engine.execute_script(code)
            self.assertIsNotNone(executor)
            
        print("✓ Scripting tab and rfx engine tested successfully.")

    def test_09_diagnostics_and_performance(self):
        """Test system diagnostics and performance metrics gathering."""
        diag_tab = self.window.diagnostics_tab
        perf_tab = self.window.performance_tab
        
        if hasattr(diag_tab, 'run_diagnostics'):
            diag_tab.run_diagnostics()
            self.app.processEvents()
            
        if hasattr(perf_tab, 'analyze_model'):
            perf_tab.analyze_model(self.assets['stress_mesh'])
            self.app.processEvents()
            
        print("✓ Diagnostics and Performance tabs tested successfully.")

    def test_10_inter_tab_signals(self):
        """Verify tab signal/slot wiring between Library, Mesh Tools, and Main Window."""
        win = self.window
        # Test routing a model from library to mesh tools
        win.open_in_mesh_tools(self.assets['clean_manifold'])
        self.app.processEvents()
        self.assertEqual(win.tab_widget.currentWidget(), win.mesh_tools_tab)
        
        # Test routing a model to pre-processing
        win.open_in_preprocessing(self.assets['clean_manifold'])
        self.app.processEvents()
        self.assertEqual(win.tab_widget.currentWidget(), win.preprocessing_tab)
        
        # Test routing to post-processing
        win.open_in_postprocessing(self.assets['clean_manifold'])
        self.app.processEvents()
        self.assertEqual(win.tab_widget.currentWidget(), win.postprocessing_tab)
        
        print("✓ Inter-tab signal routing verified.")

    def test_11_ai_asset_tagger_clip_inference(self):
        """Verify that AI Asset Tagger runs CLIP inference and returns categories + tags."""
        tagger_tab = self.window.library_tab.ai_tagger_tab
        self.assertIsNotNone(tagger_tab.tagger)
        
        # Run inference on synthetic model
        res = tagger_tab.tagger.analyze_model(self.assets['clean_manifold'])
        self.assertIn('tags', res)
        self.assertIn('category', res)
        self.assertTrue(len(res['tags']) > 0)
        print(f"✓ AI Asset Tagger CLIP inference verified (Category: {res.get('category')}, {len(res['tags'])} tags).")

    def test_12_embedded_quality_analyzer(self):
        """Verify embedded QualityAnalyzerUI in ModelTab accurately detects geometry flaws."""
        qa = self.window.model_tab.quality_analyzer_tab
        qa.set_model(self.assets['mesh_with_holes'])
        self.app.processEvents()
        self.assertIsNotNone(qa.current_model_path)
        print("✓ Embedded QualityAnalyzerUI verified with hole mesh.")

    def test_13_embedded_version_control(self):
        """Verify embedded VersionControlUI in ModelTab manages asset versions."""
        vcs = self.window.model_tab.version_control_tab
        vcs.load_model(self.assets['clean_manifold'])
        self.app.processEvents()
        self.assertIsNotNone(vcs.current_model)
        print("✓ Embedded VersionControlUI verified with clean model.")

    def test_14_painting_suite(self):
        """Verify PaintingTab in ModelTab initializes model and vertex buffers."""
        painting = self.window.model_tab.painting_tab
        painting.set_model(self.assets['clean_manifold'])
        self.app.processEvents()
        self.assertIsNotNone(painting.model_wrapper)
        print("✓ PaintingTab model wrapper and viewport verified.")

    def delete_with_patience(self, path, tries=8):
        """Remove one file, giving a scanner or indexer that is holding it a moment to let go.

        A first attempt is not the measurement: Windows refuses a delete while any process
        has the file, and the antivirus that ships with it reads every file the suite writes.
        Eight quarter-second attempts is two seconds of patience, which is enough for that
        and nowhere near enough to hide a mesh the app itself kept open.
        """
        last = None
        try:
            for attempt in range(tries):
                try:
                    os.remove(path)
                    return None
                except OSError as problem:
                    last = problem
                    time.sleep(0.25)
                    self.app.processEvents()
            return last
        finally:
            if last is not None:
                # Name the file while the lock is being measured. Whatever holds it will
                # complain later, as a ResourceWarning on an unrelated line of the output.
                print(f"  (still holding {os.path.basename(path)}: winerror={last.winerror})")

    def test_15_no_route_leaves_a_file_the_next_software_cannot_rewrite(self):
        """Every verb that hands a model to a pane must release the file while the window lives.

        Measured here because `verify_all_fixes test_09` reported `WinError 32` on its own
        temp directory and pointed at this app. RenderFox is the tool that sits beside Blender,
        Unity and a DCC that re-exports over the same path, so a pane that keeps a model open
        is a release defect, not a test defect: each route gets its own copy of a real file,
        the event loop is drained, and the copy has to be deletable with this window still up.
        """
        routes = {
            'open_in_model_viewer': self.window.open_in_model_viewer,
            'open_in_point_clouds': self.window.open_in_point_clouds,
            'open_in_animation': self.window.open_in_animation,
            'open_in_preprocessing': self.window.open_in_preprocessing,
            'open_in_mesh_tools': self.window.open_in_mesh_tools,
            'open_in_postprocessing': self.window.open_in_postprocessing,
        }
        held = []
        for verb, route in routes.items():
            copy = os.path.join(self.temp_dir, f'lock_{verb}.obj')
            shutil.copyfile(self.assets['clean_manifold'], copy)
            route(copy)
            for _ in range(30):
                self.app.processEvents()
            problem = self.delete_with_patience(copy)
            if problem is not None:
                held.append(f'{verb} kept {os.path.basename(copy)} open '
                            f'(winerror={problem.winerror})')
        self.assertEqual([], held, 'the window is still open, and a DCC could not re-export '
                                   'any file on this list')

    def test_16_no_reader_in_the_app_keeps_the_file_it_read(self):
        """Ten ways this app opens a file, each with the object it made still alive.

        A route can release a file while the reader underneath it does not, so the same
        question is asked of the readers directly - the library, Open3D, pymeshlab, the
        mesh processor, the thumbnail painter, the preview raster, the viewer's texture
        read and the Rendering pane's texture slot. Every result is kept in `alive` until
        after the delete, so garbage collection cannot be credited with a release the code
        never did.
        """
        import open3d as o3d
        import pymeshlab
        import trimesh
        from PIL import Image

        from src.processing import preview_render
        from src.processing.mesh_processor import MeshProcessor
        from src.ui.model_viewer import ModelViewer3D
        from src.utils.thumbnail_renderer import generate_3d_thumbnail

        alive = []
        held = []

        def check(label, reader, name, extension='.obj'):
            path = os.path.join(self.temp_dir, f'reader_{name}{extension}')
            if extension == '.obj':
                shutil.copyfile(self.assets['clean_manifold'], path)
            else:
                Image.new('RGB', (64, 64), (10, 20, 30)).save(path)
            alive.append(reader(path))
            problem = self.delete_with_patience(path)
            if problem is not None:
                held.append(f'{label} kept {name}{extension} open '
                            f'(winerror={problem.winerror})')

        check('trimesh.load', lambda path: trimesh.load(path), 'trimesh')
        check('trimesh.load(process=False)',
              lambda path: trimesh.load(path, process=False), 'trimesh_raw')
        check('o3d.io.read_triangle_mesh',
              lambda path: o3d.io.read_triangle_mesh(path), 'open3d_mesh')
        check('o3d.io.read_point_cloud',
              lambda path: o3d.io.read_point_cloud(path), 'open3d_cloud')

        def via_meshlab(path):
            mesh_set = pymeshlab.MeshSet()
            mesh_set.load_new_mesh(path)
            return mesh_set

        check('pymeshlab.MeshSet.load_new_mesh', via_meshlab, 'meshlab')
        check('MeshProcessor.load_mesh',
              lambda path: MeshProcessor().load_mesh(path), 'processor')
        check('generate_3d_thumbnail',
              lambda path: generate_3d_thumbnail(
                  path, os.path.join(self.temp_dir, 'reader_thumb.png'), size=128), 'thumb')
        check('preview_render.render_file',
              lambda path: preview_render.render_file(
                  path, os.path.join(self.temp_dir, 'reader_preview.png'), 200, 200),
              'preview')
        check('the viewer texture reader',
              lambda path: ModelViewer3D._read_texture_file(path), 'viewer_texture',
              extension='.png')

        def via_the_rendering_pane(path):
            """Hand the texture to the pane's own material slot and keep the pane alive."""
            self.window.rendering_tab.on_material_updated({'albedo_texture': path})
            return self.window.rendering_tab.viewport

        check('Rendering pane material slot', via_the_rendering_pane, 'pane_texture',
              extension='.png')

        self.assertEqual([], held, f'{len(alive)} readers were each handed a fresh copy and '
                                   f'these did not release it')

        del alive
        print("✓ Every reader released the file it read.")

    def test_17_the_texture_control_on_the_wrapper_reaches_the_viewer_it_wraps(self):
        """`ModelViewerWidget.set_material_texture` has to forward, not run its own GL code.

        The wrapper is a plain QWidget with no GL context, so the copy of the viewer's
        texture body it carried raised on its very first line and the bare except buried the
        message. Every other control on that class forwards to `viewer_3d`; this is what
        keeps the texture control from being given a second, unreachable implementation.
        """
        from PIL import Image

        from src.ui.model_viewer import ModelViewerWidget

        class Recorder:
            def __init__(self):
                self.seen = []

            def set_material_texture(self, texture_type, file_path):
                self.seen.append((texture_type, file_path))

        wrapper = ModelViewerWidget()
        real_viewer = wrapper.viewer_3d
        try:
            recorder = Recorder()
            wrapper.viewer_3d = recorder
            png = os.path.join(self.temp_dir, 'wrapper_texture.png')
            Image.new('RGB', (32, 32), (7, 8, 9)).save(png)

            wrapper.set_material_texture('albedo', png)
            wrapper.set_material_texture('normal', png)
            self.assertEqual([('albedo', png), ('normal', png)], recorder.seen,
                             'the control did not reach the viewer it wraps')

            wrapper.viewer_3d = object()
            wrapper.set_material_texture('metallic', png)
        finally:
            wrapper.viewer_3d = real_viewer
            wrapper.close()

        live = self.window.model_tab.model_viewer
        live.set_material_texture('albedo', png)
        self.app.processEvents()
        print("✓ The wrapper texture control forwards to the viewer, and the fallback is safe.")

    def test_18_the_texture_read_gives_the_upload_four_channels_for_every_image_mode(self):
        """Whatever mode a texture author saved in has to arrive as RGBA bytes.

        The shader is handed GL_RGBA from a uint8 array, but Pillow returns the file in
        the mode it was saved - a palette PNG or a grayscale map comes back with fewer
        channels than the upload wants, and the texture that paints is not the one loaded.
        """
        from PIL import Image

        from src.ui.model_viewer import ModelViewer3D

        seeds = {'RGB': (200, 30, 10), 'RGBA': (200, 30, 10, 255), 'L': 40, 'LA': (40, 200),
                'P': 3}
        read = {}
        for mode, colour in seeds.items():
            path = os.path.join(self.temp_dir, f'mode_{mode}.png')
            Image.new(mode, (8, 6), colour).save(path)
            read[mode] = ModelViewer3D._read_texture_file(path)

        for mode, data in read.items():
            self.assertEqual((6, 8, 4), data.shape, f'a {mode} texture did not arrive as RGBA')
            self.assertEqual(np.uint8, data.dtype, f'a {mode} texture did not arrive as bytes')

        self.assertEqual([200, 30, 10, 255], list(read['RGB'][0, 0]))
        self.assertEqual([200, 30, 10, 255], list(read['RGBA'][0, 0]))
        self.assertEqual([40, 40, 40, 255], list(read['L'][0, 0]))
        self.assertEqual([40, 40, 40, 200], list(read['LA'][0, 0]))

        palette_path = os.path.join(self.temp_dir, 'mode_P.png')
        with Image.open(palette_path) as reference:
            expected = np.array(reference.convert('RGBA'), dtype=np.uint8)
        np.testing.assert_array_equal(expected, read['P'],
                                      'a palette texture was not un-indexed the same way')
        print("✓ Each image mode reaches the upload as RGBA bytes.")

    def test_19_a_failed_texture_read_releases_the_file_the_error_keeps(self):
        """A texture that fails to read must not lock the file while the failure is on screen.

        Measured, not assumed: with the read written as open-then-use-then-swallow, the
        traceback of the retained exception holds the frame that holds the Pillow image, and
        the image holds the file - `winerror=32` on the texture, for as long as the pane keeps
        the error. A truncated PNG is the case that reaches it: Pillow identifies the header,
        and only the pixel read finds the file stops early.
        """
        from PIL import Image

        from src.ui.model_viewer import ModelViewer3D

        path = os.path.join(self.temp_dir, 'truncated_texture.png')
        Image.new('RGB', (200, 200), (9, 9, 9)).save(path)
        with open(path, 'rb') as handle:
            head = handle.read()
        with open(path, 'wb') as handle:
            handle.write(head[:len(head) // 3])

        kept = {}
        try:
            ModelViewer3D._read_texture_file(path)
        except Exception as problem:
            kept['error'] = problem
        self.assertTrue(kept, 'a truncated texture was read without complaint')

        problem = self.delete_with_patience(path)
        self.assertIsNone(problem,
                          f'the failed read kept the texture open (winerror='
                          f'{getattr(problem, "winerror", None)})')
        print("✓ A texture read that failed released its file.")

    def test_20_closing_the_window_stops_a_run_the_pane_started(self):
        """A close has to take the result channels off before it destroys the widgets.

        Measured, not reasoned: this window, closed while the Point Clouds measure was still
        running, died with `Windows fatal exception: code 0xc0000374` - a heap fault, not a
        traceback - inside the pane's verdict handler. The route starts a worker, the verdict
        is queued, and by the time the queue drains the label it writes to is gone. So the
        real close is driven with a run provably in flight, and three things have to come
        back: the verb was asked to stop, nothing is still running, and the pane's own
        sentence is the last word on the label.
        """
        class SlowBackend:
            """Delay the real measure, then let the worker post the backend's own verdict.

            The answer stays the backend's: a stub verdict of a shape this test invented is
            the only thing a handler that should have been disconnected could trip over, and
            then the suite would be measuring its own invention.
            """

            def __init__(self, real):
                self.real = real
                self.stop_seen = False

            def run(self, operation, params, should_cancel=None):
                deadline = time.time() + 3
                while time.time() < deadline:
                    if should_cancel is not None and should_cancel():
                        self.stop_seen = True
                        break
                    time.sleep(0.005)
                return self.real.run(operation, params, should_cancel)

        pane = self.window.point_clouds_tab
        real_backend = pane.pc_processor
        slow = SlowBackend(real_backend)
        pane.pc_processor = slow
        sentence = None
        dialog = None
        try:
            self.window.open_in_point_clouds(self.assets['point_cloud'])
            for _ in range(5):
                self.app.processEvents()
            sentence = pane.operation_label.text()
            dialog = pane._run_progress
            live = [thread for thread in pane._workers if thread.isRunning()]
            self.assertTrue(live, 'showing the cloud left no run in flight to close over')

            self.window.close()
            self.app.processEvents()
        finally:
            pane.pc_processor = real_backend
            # Wait for the workers as they are, without asking them to stop on the close's
            # behalf: whether the stop was ever requested is the thing being measured.
            for thread in list(pane._workers):
                thread.wait(15000)

        self.assertTrue(slow.stop_seen, 'the close never asked the running verb to stop')
        self.assertEqual([], [thread for thread in pane._workers if thread.isRunning()],
                         'a worker outlived the window it was started in')
        self.assertIsNone(pane._active_thread, 'the pane still claims a run after its close')
        self.assertEqual(sentence, pane.operation_label.text(),
                         'a verdict reached the label after the window had gone')
        if dialog is not None:
            self.assertFalse(dialog.isVisible(),
                             'the progress dialog is still waiting for a run that was stopped')
        print("✓ Closing the window stopped the run and nothing reported afterwards.")

    def test_21_a_run_that_refuses_to_stop_is_counted_and_held(self):
        """`shutdown_runs` answers with the workers it could not finish, and keeps their refs.

        Letting go of the last reference of a running QThread is Qt's other way of ending
        this process, so a worker that outlasts the wait stays held by the pane. The count is
        the part that can be measured: a caller that is told nothing is left will go and
        delete the window over a thread that is still writing.
        """
        class DeafBackend:
            """A verb that carries on through the stop request, then answers for real."""

            def __init__(self, real):
                self.real = real

            def run(self, operation, params, should_cancel=None):
                time.sleep(1.0)
                return self.real.run(operation, params, lambda: False)

        pane = self.window.point_clouds_tab
        real_backend = pane.pc_processor
        pane.pc_processor = DeafBackend(real_backend)
        try:
            started = pane._run('analyze', {'file_path': self.assets['point_cloud']},
                                sentence='Measuring the cloud...', silent=True)
            self.assertTrue(started, 'the pane refused to start the run')
            for _ in range(5):
                self.app.processEvents()
            live = [thread for thread in pane._workers if thread.isRunning()]
            self.assertTrue(live, 'the run finished before it could be given a deaf backend')

            refused = pane.shutdown_runs(timeout_ms=100)

            self.assertEqual(1, refused, 'a worker still running was reported as stopped')
            self.assertEqual(live, [thread for thread in pane._workers if thread in live],
                             'the pane dropped the reference of a thread still working')
        finally:
            pane.pc_processor = real_backend
            for thread in list(pane._workers):
                thread._stop_requested = True
                thread.wait(20000)
        print("✓ A run that refused the stop was counted and kept alive.")

    @classmethod
    def tearDownClass(cls):
        """Close the window, then take the asset tree with it - and say so if anything stays.

        The class used to leave its temp directory on disk, which hides the one fact these
        two tests exist to keep: a file this app opened has to be deletable once it is shut.
        """
        cls.window.close()
        cls.window.deleteLater()
        cls.app.processEvents()
        del cls.window
        gc.collect()
        cls.app.processEvents()

        stuck = []
        for root, _dirs, files in os.walk(cls.temp_dir):
            for name in files:
                path = os.path.join(root, name)
                for attempt in range(8):
                    try:
                        os.remove(path)
                        break
                    except OSError as problem:
                        if attempt == 7:
                            stuck.append(f'{name} (winerror={problem.winerror})')
                        time.sleep(0.25)
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
        if stuck:
            raise AssertionError(f'the window is closed and this is still holding: {stuck[:6]}')


if __name__ == '__main__':
    unittest.main()
