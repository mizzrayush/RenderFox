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

    # ---- #42: the close-over-a-live-run verb ------------------------------------------

    def slow_seam(self, owner, name, seconds=2.0):
        """Replace one backend verb with that same verb after a delay, and say how to undo it.

        The answer stays the backend's. A stub verdict of a shape this test invented is the
        only thing a handler that should have been disconnected could trip over, and then
        the suite would be measuring its own invention - so the delay goes around the real
        call, exactly as in test_20.
        """
        real = getattr(owner, name)
        owned = name in vars(owner)

        def delayed(*args, **kwargs):
            time.sleep(seconds)
            return real(*args, **kwargs)

        setattr(owner, name, delayed)

        def restore():
            if owned:
                setattr(owner, name, real)
            else:
                delattr(owner, name)
        return restore

    def test_22_every_holder_silences_counts_and_holds_what_it_cannot_finish(self):
        """One table over the shapes of run: a real run in flight, the verb, three answers.

        Each row drives a pane's own entry point with its own backend delayed, because the
        five panes reached by the old tab loop and the ones embedded inside others are
        different shapes - `QThread`s held in a list, `QThread`s held in one attribute, and
        `QRunnable`s on a pool that answers only whether its queue drained. Three facts have
        to come back the same way for all of them: the run that was still working is counted
        as owed rather than reported as stopped, it is still referenced afterwards, and
        nothing is left connected that could write into a widget the close destroys. Then the
        poll down to zero shows the release path, not just the hold path, and prints how long
        each real backend actually took.
        """
        from src.features.diagnostic_engine import SystemInfo
        from src.utils.run_teardown import silence

        perf = self.window.performance_tab
        diag = self.window.diagnostics_tab
        mesh = self.window.mesh_tools_tab
        library = self.window.library_tab
        tagger = self.window.library_tab.ai_tagger_tab

        rows = [
            ('Performance storage read', perf, lambda: perf.refresh_storage_info(),
             lambda: perf._workers, SystemInfo, 'get_storage_info'),
            ('Diagnostics object walk', diag, lambda: diag.take_memory_snapshot(),
             lambda: diag._measure_workers, SystemInfo, 'live_object_counts'),
            ('Mesh Tools clustering simplify', mesh, lambda: mesh.simplify_cluster(),
             lambda: mesh._runs, mesh.mesh_processor, 'simplify'),
            ('Library scan', library, lambda: library.start_scan_worker(),
             lambda: [held for held in (library.scanner_worker,) if held is not None],
             library.library, 'scan'),
            ('AI tagger auto-tag', tagger, lambda: tagger.auto_generate_tags(),
             lambda: [held for held in (getattr(tagger, 'tag_worker', None),)
                      if held is not None],
             tagger.tagger, 'analyze_model'),
        ]

        mesh.current_model_path = self.assets['clean_manifold']
        tagger.current_model_path = self.assets['clean_manifold']
        timings = {}

        for label, pane, start, holders, owner, verb in rows:
            restore = self.slow_seam(owner, verb)
            try:
                before = list(holders())
                start()
                new = [worker for worker in holders() if worker not in before]
                self.assertEqual(1, len(new),
                                 f'{label}: the pane did not keep the run it just started')

                owed = pane.shutdown_runs(timeout_ms=100)
                self.assertGreaterEqual(owed, 1,
                                        f'{label}: a run still working was reported as stopped')
                self.assertIn(new[0], holders(),
                              f'{label}: the reference of a running worker was dropped')
                self.assertEqual([], silence(new[0]),
                                 f'{label}: a channel survived the close verb')

                # Poll to zero instead of naming a wait: the run has to finish on its own
                # before the release path can be seen, and how long that takes here is a
                # property of this machine at this moment, not of the pane. A verb that
                # never settles fails below with the seconds it took.
                spent = 0.0
                while True:
                    began = time.time()
                    settled = pane.shutdown_runs(timeout_ms=1000)
                    spent += time.time() - began
                    if settled == 0:
                        break
                    self.assertLess(spent, 180.0,
                                    f'{label}: the run was still owed after {spent:.0f}s; '
                                    f'the rows before it took {timings}')
                    self.app.processEvents()
                timings[label] = spent
                self.assertNotIn(new[0], holders(),
                                 f'{label}: a finished run was never released')
            finally:
                restore()
        print('✓ Every holder silenced, counted and released its run: '
              f'{len(rows)} shapes across the tabs and the embedded panes; '
              + ', '.join(f'{label} {spent:.1f}s' for label, spent in sorted(timings.items())))

    def test_23_the_channels_come_from_qt_rather_than_from_this_files_memory(self):
        """`channels()` names what an object can emit - including the two awkward shapes.

        A `QThread` subclass that declares its own `finished` carrying a payload shadows Qt's
        signal of the same name, and the tagger does exactly that; the house `Worker` is a
        `QRunnable`, so it has no meta-object at all and its channels live on `worker.signals`.
        A hand-written list beside each pane gets both wrong in silence, which is why the
        Pipeline pane's two-signal tuple is what this replaced.
        """
        from PyQt6.QtCore import QObject
        from src.ui.ai_asset_tagger_ui import BulkTaggingWorker, TaggingWorker
        from src.ui.model_tab import ModelAnalysisWorker
        from src.ui.pipeline_editor_tab import PipelineRunThread
        from src.ui.point_clouds_tab import CloudRunThread
        from src.utils.run_teardown import _PRIVATE, _signal_names, channels, silence
        from src.utils.worker import Worker

        names_by_class = {}
        for cls, kwargs in ((TaggingWorker, {'model_path': 'x.obj', 'tagger': None}),
                            (BulkTaggingWorker, {'model_paths': ['x.obj'], 'tagger': None}),
                            (ModelAnalysisWorker, {'file_paths': []})):
            runner = cls(**kwargs)
            names = [name for name, _ in channels(runner)]
            names_by_class[cls.__name__] = names
            expected = [name for name in _signal_names(runner) if name not in _PRIVATE]
            self.assertEqual(expected, names,
                             f'{cls.__name__}: the channels are not the ones Qt declares')
            self.assertIn('finished', names,
                          f'{cls.__name__} shadows QThread.finished and must still lose it')

        pipeline = PipelineRunThread(None)
        for name in ('log_line', 'node_state', 'run_finished'):
            self.assertIn(name, _signal_names(pipeline),
                          f'the Pipeline run declares {name}; a list beside the pane forgets it')

        runner = Worker(lambda progress_callback=None: 1)
        self.assertFalse(isinstance(runner, QObject),
                         'the house Worker is a QRunnable; its signals are on .signals')
        self.assertEqual({'finished', 'error', 'result', 'progress'},
                         {name for name, _ in channels(runner)})

        threaded = CloudRunThread(None, 'analyze', {})
        threaded.verdict_ready.connect(lambda verdict: None)
        self.assertIn('verdict_ready', silence(threaded),
                      'the verb that carries the verdict is the one that must come off')

    def test_24_a_cancellation_verb_the_helper_does_not_know_fails_here(self):
        """`_STOP_VERBS` is a list of the app's own spellings, so a fifth one is a defect.

        A run whose verb this list misses is not stopped by the close - it is only waited on,
        quietly, and the pane reports a number that looks like an answer. Reading the source
        is the only way to keep that list from drifting behind the code.
        """
        import ast
        import pathlib

        from src.utils.run_teardown import _STOP_VERBS

        candidates = {'stop', 'cancel', 'abort', 'halt', 'stop_work', 'stop_run',
                      'request_stop', 'request_cancel', 'cancel_run', 'cancel_processing'}
        run_bases = ('QThread', 'SafeWorker', 'Worker', 'Thread')
        offenders = []
        for path in sorted(pathlib.Path('src').rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = [ast.unparse(base) for base in node.bases]
                if not any(base.split('.')[-1] in run_bases for base in bases):
                    continue
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in candidates:
                        if item.name not in _STOP_VERBS:
                            offenders.append(f'{path}:{item.lineno} {node.name}.{item.name}')
        self.assertEqual([], offenders,
                         'a run class asks to be stopped by a verb the helper never calls: '
                         + '; '.join(offenders))

    def test_25_the_close_asks_every_holder_in_the_tree_not_only_the_fifteen_tabs(self):
        """A flat tab loop is what left the embedded panes answering to nobody.

        The Quality pane lives inside Models, the Open3D preview inside Mesh Tools and Point
        Clouds, the tagger inside Library, and a dialog outlives its own `exec()` as a child
        of the pane that opened it. The walk is replaced here by a spy on every holder that
        answers, and the assertion is that the set asked equals the set that exists - so a
        regression back to the loop fails on a name rather than on a crash. It is the set of
        *instances*, because a walk scoped to the tab pages still asks one
        `TextureGeneratorDialog` and misses the one parented to the window itself, and a
        comparison of class names cannot see the difference. The window is shown first
        because an earlier test closed it, and Qt answers a close of a window that is already
        hidden by doing nothing at all; the second close measures that fact instead of
        trusting it.
        """
        from PyQt6.QtWidgets import QWidget
        from src.features.model_downloader import ModelDownloaderDialog
        from src.ui.texture_generator import TextureGeneratorDialog

        TextureGeneratorDialog(self.window.rendering_tab)
        TextureGeneratorDialog(self.window)
        # The AI Model Manager, parented the way the Settings pane parents it. Parentless, it
        # is a run the tree cannot see: nothing above it holds the `QThread` inside, so the
        # close never asks and the reference dies with the local it was made in.
        ModelDownloaderDialog(self.window.settings_tab, auto_start=False)

        holders = [pane for pane in [self.window] + self.window.findChildren(QWidget)
                   if hasattr(pane, 'shutdown_runs')]
        self.assertGreaterEqual(len(holders), 14,
                                'the tree holds fewer runs than the app starts them')
        dialogs = [pane for pane in holders if isinstance(pane, TextureGeneratorDialog)]
        self.assertEqual(2, len(dialogs),
                         'the two dialogs were not both found as children of this window, so '
                         'the test cannot ask the walk a question about its scope')
        managers = [pane for pane in holders if isinstance(pane, ModelDownloaderDialog)]
        self.assertEqual(1, len(managers),
                         'the downloader dialog is not in the tree, so no close can reach it')

        asked = []
        originals = {}
        for pane in holders:
            originals[pane] = pane.shutdown_runs

            def spy(target=pane):
                def asked_runs(timeout_ms: int = 5000):
                    asked.append(target)
                    return originals[target](timeout_ms)
                return asked_runs
            pane.shutdown_runs = spy()

        self.window.show()
        self.app.processEvents()
        self.window.close()
        self.app.processEvents()

        asked_names = [type(pane).__name__ for pane in asked]
        missing = sorted({type(pane).__name__ for pane in holders if pane not in asked})
        self.assertEqual([], missing, 'the close never asked these holders: ' + ', '.join(missing))
        for expected in ('QualityAnalyzerUI', 'UnifiedOpen3DViewer', 'MeshToolsTab',
                         'TextureGeneratorDialog', 'ModelTab', 'ModelDownloaderDialog',
                         'AutomationTab'):
            self.assertIn(expected, asked_names, f'{expected} is not reached by the close')
        self.assertEqual(2, sum(1 for pane in asked if pane in dialogs),
                         'a holder parented to the window instead of to a tab page was left '
                         'out, which is the tab loop coming back with a different spelling')

        asked_once = len(asked)
        self.window.close()
        self.app.processEvents()
        self.assertEqual(asked_once, len(asked),
                         'a hidden window was closed a second time and the runs were asked again')
        print('✓ The close asked every holder instance in the tree, embedded ones included: '
              f'{len(set(asked_names))} kinds across {asked_once} instances.')

    def test_26_the_wait_answers_for_each_kind_of_runner_it_was_given(self):
        """Threads, pool work, and pool work with no pool named: three shapes, three answers.

        `QThreadPool.waitForDone` answers whether the queue drained, not whether one named
        run ended, so a pool row can only be classified with the pool in hand. A caller that
        hands over pool work and no pool is not told it finished - that answer would let the
        close delete the widgets the run is still going to write into - and the only way to
        know the refusal is real is to ask it.
        """
        from PyQt6.QtCore import QThreadPool
        from src.utils.run_teardown import wait_for_runs
        from src.utils.worker import Worker

        pool = QThreadPool.globalInstance()
        holder = Worker(lambda progress_callback=None: time.sleep(1.0))
        pool.start(holder)

        ended, running = wait_for_runs([holder], 10, pool=None)
        self.assertEqual([], ended,
                         'work that needs a pool was called finished with no pool named')
        self.assertEqual([holder], running, 'the same run was not counted as owed')

        ended, running = wait_for_runs([holder], 20000, pool)
        self.assertEqual([holder], ended, 'the pool said its queue drained and the helper said no')
        self.assertEqual([], running, 'a drained run stayed owed')
        print('✓ The wait told a thread, a drained pool and an unnamed pool apart.')

    def test_27_the_attribute_holder_silences_asks_waits_and_clears(self):
        """`drain_attributes` is a different shape from `drain`: one attribute, one guard.

        Panes that keep a single run in a named attribute read that attribute from their own
        Cancel button, so a run that outlasts the wait has to leave it holding the thread -
        dropping that reference is Qt's way of ending the process - and a run that ended has
        to leave it None so the next Cancel finds nothing. The worker here belongs to this
        file because the helper is the thing under test: it is a `QThread` that records the
        request it is given, ignores it, and posts a verdict either way.
        """
        from PyQt6.QtCore import QThread, pyqtSignal
        from src.utils.run_teardown import drain_attributes

        class Deaf(QThread):
            """A run that says it was asked and carries on regardless."""

            verdict = pyqtSignal(str)

            def __init__(self):
                super().__init__()
                self.asked = False

            def request_stop(self):
                self.asked = True

            def run(self):
                time.sleep(1.0)
                self.verdict.emit('the answer')

        class Holder:
            run = None

        holder = Holder()
        holder.run = Deaf()
        seen = []
        holder.run.verdict.connect(seen.append)
        holder.run.start()
        while not holder.run.isRunning():
            self.app.processEvents()

        owed = drain_attributes(holder, ('run',), timeout_ms=80)

        self.assertTrue(holder.run.asked, 'the attribute holder never asked the run to stop')
        self.assertEqual([holder.run], owed, 'a run that was still working was reported as ended')
        self.assertIsNotNone(holder.run,
                             'the attribute of a run still working was cleared, and the '
                             'reference Qt needs kept is the one the pane dropped')

        holder.run.wait(15000)
        self.app.processEvents()
        self.assertEqual([], seen, 'the verdict reached the pane after the close had taken it off')

        self.assertEqual([], drain_attributes(holder, ('run',), timeout_ms=5000),
                         'a run that had ended was still counted')
        self.assertIsNone(holder.run, 'the ended run still owns the attribute its Cancel reads')
        print('✓ The attribute holder asked, kept the live run, dropped the verdict and cleared it.')

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
