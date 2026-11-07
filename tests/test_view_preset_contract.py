"""The Presets buttons, the Scripting list, the load verdict: three claims, each checked at the
control that makes it.

This file exists because three controls in this app described a capability without touching it.
The Model pane's Settings tab carried a **Presets** group written inside a triple-quoted string
expression - valid Python that builds nothing - and its three handlers set
`self.render_mode_combo`, a widget that exists nowhere in the tree, so even if the buttons had
been built, the first click would have raised `AttributeError` out of a Qt slot. The Scripting
pane's "Available Functions" list was nineteen hand-typed names, fifteen of which the script
engine has never heard of, and pressing *Insert Code* puts the selected line straight into the
editor the user runs. And `load_model_file` - the path the Operating System's "Open with" and the
Library pane's double-click take - called `update_model_info(file_path)` on a slot that reads
`model_info.get('vertices')`, so a model that loaded was reported as
`Failed to load model: 'str' object has no attribute 'get'`.

What is asked here is the same three facts, asked of the real widgets: a click moves the control
the pane shows *and* the state the viewer paints from, so the preset cannot be a picture of a
change; every name in the scripting list resolves on the very object the executor injects as
`rfx`, because the list is that object's surface read off it rather than typed under it; and the
load path reports the viewer's answer, not its own hope - the success box only when the viewer
said yes, the not-found box when the file is not there.

The viewer's `load_model` is the one thing stubbed below (`test_13`, `test_14`), and it is stubbed
with a return value the pane reads: what is under test is whether the pane reports the answer it
got, which is the half that was broken. Whether an OBJ can be read at all is asked by the reader
suites. `paintGL` has never run on this machine and never runs here either - `test_06` reads the
mode word out of the paint's own source, which is a statement about the code, not a rendered
frame. The integrity dialog is called as the plain function it is on a stub with the report dict
the backend really returns, for the same reason `tests/test_run_teardown_contract.py` avoids C++
frames: a defect that aborts the process is a defect nobody can read.

Two of the hazards of that rule are answered here rather than assumed away, both found by planting
the defects rather than by reading them. The load path's last resort is `QMessageBox.critical`,
which is a modal box, and offscreen a modal box with no event loop never returns - the sweep entry
that removes the existence check hung the suite for twenty-five minutes before this was measured,
so `test_12` to `test_14` capture all three boxes. And the str that the load path used to hand the
info labels is emitted only after the pane's receiver is dropped, because a signal retyped to
`pyqtSignal(str)` would pass the path straight to a slot that reads `.get`, and an exception
inside a Qt slot ends the process instead of naming a test.

Run: python -X utf8 tests/test_view_preset_contract.py
"""

import inspect
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from src.ui.library_tab import LibraryTab
from src.ui.model_tab import ModelTab
from src.ui.model_viewer import ModelViewer3D, ModelViewerWidget
from src.ui.scripting_tab import ScriptingTab

DATA = os.path.join(os.path.dirname(__file__), 'test_data')
SPHERE = os.path.join(DATA, 'test_sphere.obj')

# The row the Settings tab's Shaders list shows -> the word the viewer's paint branches on.
ROW_MODES = {0: 'wireframe', 1: 'fill', 3: 'point_cloud', 4: 'overlay'}


class _Captured:
    """A QMessageBox that remembers what a pane tried to say."""

    def __init__(self):
        self.calls = []

    def __call__(self, parent, title, text, *args, **kwargs):
        self.calls.append((title, text))
        return QMessageBox.StandardButton.Ok


class TestModelPanePresets(unittest.TestCase):
    """The Presets group and the Shaders rows, on a Model pane built the way the window builds it."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.out = tempfile.mkdtemp(prefix='renderfox_presets_')
        cls.tab = ModelTab(library_path=cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tab.shutdown_runs()
        cls.tab.close()
        cls.tab.deleteLater()
        cls.app.processEvents()

    def settings_widget(self):
        for index in range(self.tab.detail_tabs.count()):
            if self.tab.detail_tabs.tabText(index) == 'Settings':
                return self.tab.detail_tabs.widget(index)
        self.fail('the Settings tab of the Model pane is gone')

    def button(self, label):
        for btn in self.settings_widget().findChildren(QPushButton):
            if btn.text() == label:
                return btn
        self.fail(f'no button labelled {label!r} on the Settings tab')

    def test_01_the_three_preset_buttons_are_built_and_each_one_is_connected(self):
        """A group that paints no widgets is not a group, so look for the buttons themselves."""
        for label, handler in (('Wireframe', 'apply_wireframe_preset'),
                               ('Solid', 'apply_solid_preset'),
                               ('Debug View', 'apply_debug_preset')):
            btn = self.button(label)
            self.assertTrue(btn.receivers(btn.clicked), f'{label} is a button nothing listens to')
            self.assertTrue(hasattr(self.tab, handler), f'{handler} is gone from the pane')

    def test_02_wireframe_preset_moves_the_row_the_pane_shows_and_the_state_the_viewer_paints(self):
        self.tab.lighting_enable_cb.setChecked(True)
        self.tab.line_width_spin.setValue(4.0)
        self.tab.shader_list.setCurrentRow(1)
        self.button('Wireframe').click()
        self.assertEqual(0, self.tab.shader_list.currentRow(),
                         'the pane still shows Shaded while claiming the wireframe preset')
        self.assertFalse(self.tab.lighting_enable_cb.isChecked())
        self.assertEqual(1.5, self.tab.line_width_spin.value())
        viewer = self.tab.model_viewer.viewer_3d
        self.assertEqual('wireframe', viewer.render_mode)
        self.assertFalse(viewer.use_lighting)
        self.assertEqual(1.5, viewer.line_width)

    def test_03_solid_preset_turns_the_three_data_switches_on_together(self):
        self.tab.lighting_enable_cb.setChecked(False)
        self.tab.textures_cb.setChecked(False)
        self.tab.vcolors_cb.setChecked(False)
        self.app.processEvents()
        self.button('Solid').click()
        self.assertEqual(1, self.tab.shader_list.currentRow())
        viewer = self.tab.model_viewer.viewer_3d
        self.assertEqual('fill', viewer.render_mode)
        self.assertTrue(viewer.use_lighting)
        self.assertTrue(self.tab.textures_cb.isChecked())
        self.assertTrue(self.tab.vcolors_cb.isChecked())
        # The checkboxes are only a preset if the switches reach the state the paint reads.
        self.assertTrue(viewer.use_textures, 'the box says textures, the shader is told none')
        self.assertTrue(viewer.use_vertex_colors, 'the box says vertex colours, the shader is told none')

    def test_04_debug_preset_reaches_the_viewer_through_the_row_it_selects(self):
        self.tab.line_width_spin.setValue(1.0)
        self.button('Debug View').click()
        self.assertEqual(4, self.tab.shader_list.currentRow())
        self.assertEqual('overlay', self.tab.model_viewer.viewer_3d.render_mode)
        self.assertEqual(2.0, self.tab.line_width_spin.value())

    def test_05_no_handler_reads_a_widget_the_pane_never_makes(self):
        """The old handlers named `render_mode_combo`; naming a control is not having one."""
        for name in ('shader_list', 'lighting_enable_cb', 'line_width_spin', 'textures_cb',
                     'vcolors_cb'):
            self.assertTrue(hasattr(self.tab, name), f'the presets read {name}, the pane has it not')
        self.assertFalse(hasattr(self.tab, 'render_mode_combo'),
                         'a control no widget owns is back on the pane')
        for source in (self.tab.apply_wireframe_preset, self.tab.apply_solid_preset,
                       self.tab.apply_debug_preset):
            self.assertNotIn('render_mode_combo', inspect.getsource(source))

    def test_06_overlay_is_a_mode_the_paint_branches_on_and_a_row_can_reach(self):
        """The row is only honest if a mode the drawing code knows is what it selects."""
        rows = [self.tab.shader_list.item(i).text() for i in range(self.tab.shader_list.count())]
        self.assertEqual(['Wireframe', 'Shaded', 'Visualized', 'Point Cloud', 'Overlay'], rows)
        paint = inspect.getsource(ModelViewer3D.paintGL)
        for row, mode in ROW_MODES.items():
            self.assertIn(f"'{mode}'", paint,
                          f'row {row} selects {mode!r}, which no paint branch knows')
        for row, mode in ROW_MODES.items():
            self.tab.shader_list.setCurrentRow(row)
            self.assertEqual(mode, self.tab.model_viewer.viewer_3d.render_mode,
                             f'row {row} did not reach the viewer')

    def test_07_the_visualized_row_still_opens_its_own_details_and_no_other_row_does(self):
        """Asked of the widget's own hidden flag: a page that is not showing hides everything on it."""
        self.tab.shader_list.setCurrentRow(2)
        self.app.processEvents()
        self.assertFalse(self.tab.viz_details_widget.isHidden())
        for row in (0, 1, 3, 4):
            self.tab.shader_list.setCurrentRow(row)
            self.app.processEvents()
            self.assertTrue(self.tab.viz_details_widget.isHidden(),
                            f'row {row} left the Visualized details open')


class TestScriptingSurfaceIsTheEngine(unittest.TestCase):
    """The pane lists what `rfx` answers to, so an inserted line is a line that runs."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.tab = ScriptingTab()

    @classmethod
    def tearDownClass(cls):
        cls.tab.close()
        cls.tab.deleteLater()
        cls.app.processEvents()

    def items(self):
        listing = self.tab.api_functions_list
        return [listing.item(i).text() for i in range(listing.count())]

    def test_08_the_list_is_the_engine_s_own_surface_and_every_row_resolves(self):
        self.assertEqual(self.tab.script_engine.api_surface(), self.items(),
                         'the pane typed its own list instead of reading the engine')
        for call in self.items():
            self.assertTrue(call.startswith('rfx.'), f'{call} is not spelled the way a script calls it')
            name = call[len('rfx.'):].split('(')[0]
            self.assertTrue(callable(getattr(self.tab.script_engine.api, name, None)),
                            f'{call} names nothing the injected api object answers to')

    def test_09_the_names_the_engine_does_not_have_are_gone(self):
        listed = ' '.join(self.items())
        for invented in ('get_loaded_models', 'save_model', 'convert_model', 'optimize_textures',
                         'validate_model', 'get_model_info', 'extract_metadata', 'create_render_job',
                         'get_render_engines', 'set_render_settings', 'start_batch_render',
                         'get_processing_status', 'show_notification', 'get_app_settings',
                         'set_app_setting'):
            self.assertNotIn(invented, listed, f'{invented}() is still offered and nothing runs it')

    def test_10_the_pane_s_parameters_are_the_parameters_the_method_declares(self):
        """A row the user inserts has to match the signature, defaults and all."""
        api = self.tab.script_engine.api
        for call in self.items():
            name = call[len('rfx.'):].split('(')[0]
            parameters = list(inspect.signature(getattr(api, name)).parameters)
            shown = call.split('(', 1)[1][:-1]
            for declared in parameters:
                self.assertIn(declared, shown, f'{call} hides the parameter {declared}')

    def test_11_the_documentation_names_the_same_calls_as_the_list(self):
        docs = self.tab.api_docs_display.toPlainText()
        for call in self.items():
            self.assertIn(call, docs, f'the list offers {call} and the docs never mention it')

    def test_19_the_surface_is_the_eleven_calls_and_is_still_there_when_a_method_is_renamed(self):
        """Written out, because a surface read off the object answers [] when the object goes empty.

        `api_surface()` builds its lines from `inspect.getmembers`, so it is honest about whatever
        is there - including nothing. These eleven lines are the scripting surface the app ships:
        a name that leaves it, a default that stops being shown, or a `**kwargs` that is printed as
        a positional all mean a script the pane offered no longer runs.
        """
        expected = [
            "rfx.add_to_job_queue(model_path, software='blender', output_path=None, **settings)",
            'rfx.bake_texture(high_poly, low_poly, output_dir, resolution=2048, maps=None)',
            'rfx.batch_process(files, operation, **kwargs)',
            'rfx.clear_results()',
            'rfx.convert_format(input_file, output_format, output_file=None)',
            'rfx.generate_lod(input_file, levels=3, ratios=None)',
            'rfx.get_library_models(tags=None, format_filter=None)',
            'rfx.get_results()',
            'rfx.load_model(file_path)',
            "rfx.log(message, level='INFO')",
            'rfx.set_lighting(rotation=0.0, blur=0.0, intensity=1.0, light_influence=0.0)',
        ]
        self.assertEqual(expected, self.tab.script_engine.api_surface())
        self.assertEqual(expected, self.items())


class TestLoadReportsTheViewer(unittest.TestCase):
    """`load_model_file` says what the viewer answered - the file it was given and no more."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.out = tempfile.mkdtemp(prefix='renderfox_loadverdict_')
        cls.tab = ModelTab(library_path=cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tab.shutdown_runs()
        cls.tab.close()
        cls.tab.deleteLater()
        cls.app.processEvents()

    def captured_boxes(self):
        """All three boxes the pane can open, including `critical`.

        The load path's last resort is `QMessageBox.critical`, and a static message box with no
        event loop running offscreen does not return: the mutation sweep that took the file
        existence check out hung here for twenty-five minutes instead of failing. A test that can
        only report by hanging reports nothing.
        """
        boxes = {name: _Captured() for name in ('information', 'warning', 'critical')}
        patches = [mock.patch.object(QMessageBox, name, box) for name, box in boxes.items()]
        for patch in patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in patches])
        return boxes

    def test_12_a_path_that_is_not_there_is_refused_before_anything_is_claimed(self):
        boxes = self.captured_boxes()
        missing = os.path.join(self.out, 'not_here.obj')
        self.tab.load_model_file(missing)
        self.assertEqual([('Error', f'File not found:\n{missing}')], boxes['warning'].calls)
        self.assertEqual([], boxes['information'].calls + boxes['critical'].calls)

    def test_13_the_success_box_only_arrives_when_the_viewer_said_yes(self):
        boxes = self.captured_boxes()
        with mock.patch.object(ModelViewerWidget, 'load_model', return_value=True):
            self.tab.load_model_file(SPHERE)
        self.assertEqual([], boxes['warning'].calls + boxes['critical'].calls)
        self.assertEqual(1, len(boxes['information'].calls), str(boxes['information'].calls))
        title, text = boxes['information'].calls[0]
        self.assertIn('test_sphere.obj', text, f'the verdict does not name the file: {text}')
        self.assertEqual(SPHERE, self.tab.current_model_path,
                         'the pane claims a load it did not record as the model it holds')

    def test_14_a_viewer_that_refuses_is_not_reported_as_a_load(self):
        boxes = self.captured_boxes()
        with mock.patch.object(ModelViewerWidget, 'load_model', return_value=False):
            self.tab.load_model_file(SPHERE)
        self.assertEqual([], boxes['information'].calls,
                         'the pane promised a load the viewer denied')
        self.assertEqual([], boxes['critical'].calls)
        titles = [title for title, _ in boxes['warning'].calls]
        self.assertIn('Load Error', titles, str(boxes['warning'].calls))

    def test_15_the_info_labels_are_filled_from_the_dict_the_viewer_emits(self):
        """The slot takes the viewer's measurements; a path handed to it used to crash the load.

        The str is emitted after the pane's own receiver is dropped, so the typed signal is what
        refuses it. Left connected, a retyped `pyqtSignal(str)` would hand the path to the slot,
        the slot would raise inside a Qt callback, and PyQt would end the process instead of
        naming the test - the shape `REPAIR_LOG` calls a crashing defect nobody can read.
        """
        info = {'vertices': 4, 'faces': 4, 'edges': 6, 'surface_area': 1.5, 'volume': 0.25,
                'is_watertight': True, 'bounds': [[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]],
                'has_uvs': False, 'has_vertex_colors': False, 'material_count': 0,
                'texture_data': {}}
        self.tab.current_model_path = SPHERE
        self.assertTrue(self.tab.model_viewer.receivers(self.tab.model_viewer.model_loaded),
                        'nothing listens to the load the viewer reports')
        self.tab.model_viewer.model_loaded.emit(info)
        self.app.processEvents()
        self.assertEqual('4', self.tab.vertices_label.text())
        self.assertEqual('4', self.tab.faces_label.text())
        self.assertEqual('Yes', self.tab.is_watertight_label.text())
        with self.assertRaises(AttributeError):
            self.tab.update_model_info(SPHERE)
        self.tab.model_viewer.model_loaded.disconnect()
        with self.assertRaises(TypeError):
            self.tab.model_viewer.model_loaded.emit(SPHERE)


class TestIntegrityDialogNamesTheReport(unittest.TestCase):
    """The database answers in categories; the dialog has to say those and their counts."""

    class FakeLibrary:
        def __init__(self, report):
            self._report = report

        def check_integrity(self):
            return dict(self._report)

    class FakePane:
        library = None

        def show_error(self, title, text):
            self.calls.append((title, text))

    def ask(self, report):
        captured = _Captured()
        pane = self.FakePane()
        pane.calls = []
        pane.library = self.FakeLibrary(report)
        with mock.patch.object(QMessageBox, 'information', captured), \
                mock.patch.object(QMessageBox, 'warning', captured):
            LibraryTab.check_integrity(pane)
        return pane.calls + captured.calls

    def test_16_categories_and_counts_arrive_and_not_the_key_names_alone(self):
        """`"\\n".join(a_dict)` lists the keys, which is not what was found."""
        report = {'missing_files': ['a.obj', 'b.obj'], 'orphaned_thumbnails': [],
                  'missing_thumbnails': ['c.obj'], 'total_models': 3, 'issues_found': 3}
        rows = self.ask(report)
        self.assertEqual(1, len(rows), str(rows))
        title, text = rows[0]
        self.assertEqual('Integrity Issues Found', title)
        for expected in ('missing_files: 2', 'missing_thumbnails: 1', 'orphaned_thumbnails: 0',
                         'Models in the library: 3', 'a.obj', 'c.obj'):
            self.assertIn(expected, text, f'{expected} is missing from: {text}')

    def test_20_a_long_category_is_counted_and_then_truncated(self):
        """Five paths is what the dialog shows; the rest it has to say it left out."""
        many = [f'gone{i}.obj' for i in range(7)]
        report = {'missing_files': many, 'orphaned_thumbnails': [], 'missing_thumbnails': [],
                  'total_models': 7, 'issues_found': 7}
        title, text = self.ask(report)[0]
        self.assertEqual('Integrity Issues Found', title)
        for shown in many[:5]:
            self.assertIn(shown, text, f'{shown} is one of the five the dialog promised')
        self.assertNotIn('gone5.obj', text, 'the sixth path is printed after all')
        self.assertIn('and 2 more', text, f'nothing says two were left out: {text}')

    def test_17_a_clean_database_says_clean(self):
        report = {'missing_files': [], 'orphaned_thumbnails': [], 'missing_thumbnails': [],
                  'total_models': 2, 'issues_found': 0}
        title, text = self.ask(report)[0]
        self.assertEqual('Integrity Check', title)
        self.assertIn('No integrity issues found.', text)
        self.assertIn('Models in the library: 2', text)

    def test_18_a_library_that_could_not_be_read_is_not_called_clean(self):
        """The backend answers {} after an exception, which is no answer at all."""
        title, text = self.ask({})[0]
        self.assertEqual('Integrity Check', title)
        self.assertIn('could not be read', text, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
