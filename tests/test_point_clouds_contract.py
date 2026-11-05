"""
Point Clouds pane contract test.

Every control in the pane is driven through the real widget path and has to leave a file,
a measured count or an honest sentence behind. This suite exists because the pane used to
answer with its own private copy of the work: click handlers that `import open3d` inline,
`self.processor` and `self.current_cloud_path` read but never assigned, three bodies written
twice in the same class (`run_clustering`, `compute_distances`, `crop_interactive`'s inner
`demo_crop_geometry`), `path.replace('.', '_x.')` to name an output, a blocking
`matplotlib.pyplot.show()` for the histogram, and fourteen controls that moved nothing: ten
buttons, `Fit to View` (whose connect was commented out with "Check if supported" because
the viewer had no such method), the point-size slider and both display checkboxes.
`self.current_cloud_path` is why 'Poisson Reconstruction' raised AttributeError on its first
line, and `compute_distances`' second copy is why 'Compute Nearest Distances' raised it too -
that body does not stop after the first `threadpool.start`, it continues into the duplicate,
and an exception in a slot is answered by PyQt6 with a process abort.

The first live run of the rewritten pane found two more, neither visible to a reader:
`QProgressDialog.wasClosed` is not a method PyQt6 exposes, so every verdict raised inside
the slot before it could report anything - the file was written and the pane said nothing -
and a verb that measured its own result answered "ended without reporting a result" for the
verb that started it, because the pane could not tell which thread a signal came from.
Both are pinned below by mutation, not by reading.

Run: python -X utf8 tests/test_point_clouds_contract.py
"""

import ast
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import open3d as o3d
from PIL import Image
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QDoubleSpinBox, QFileDialog,
                             QProgressDialog, QPushButton, QSpinBox, QMessageBox)

# open3d prints a warning every time a faceless .ply is opened by its mesh reader, which is
# what this pane does on purpose (a scan has vertices and no triangles). The suite's own
# verdicts are the thing worth reading.
o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.processing.format_converter import FormatConverter
from src.processing.point_cloud_processor import PointCloudProcessor
from src.ui import point_clouds_tab as PANE
from src.ui.point_clouds_tab import (BoundingBoxDialog, CloudRunThread, OP_NAMES,
                                     RUNNING_TEXT, VERB_OUTPUT_FILES, PointCloudsTab)

def read_source(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


PANE_SOURCE = read_source('src', 'ui', 'point_clouds_tab.py')
VIEWER_SOURCE = read_source('src', 'ui', 'unified_viewer.py')

APP = QApplication.instance() or QApplication(sys.argv)
SLOT_FAULTS = []


def _keep_slot_fault(kind, value, trace):
    """PyQt6 aborts the process on an exception raised inside a slot, so a defect that
    bites there would kill the run before unittest printed a single FAIL line. Keep the
    fault and let the test that was running name it."""
    SLOT_FAULTS.append(''.join(traceback.format_exception(kind, value, trace)))


sys.excepthook = _keep_slot_fault

RNG = np.random.default_rng(11)


def pane_names_used():
    """Every identifier and imported module the pane's code mentions.

    Grepping the file for forbidden words finds them in the module docstring, which names the
    defects this rewrite deleted. The parse tree holds code only, so the scan can keep naming
    `open3d` in prose and still fail the moment a click handler imports it.
    """
    names = set()
    for node in ast.walk(ast.parse(PANE_SOURCE)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split('.')[0])
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def pane_chains(scope=None):
    """Dotted attribute chains used in the whole file, or inside one class.

    Scoping matters: the worker holding `self.processor` is the design, while the pane reading
    `self.processor` - an attribute assigned nowhere - is the crash that started this rewrite.
    """
    tree = ast.parse(PANE_SOURCE)
    root = tree
    if scope is not None:
        root = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.ClassDef) and node.name == scope), None)
        if root is None:
            raise AssertionError(f'the pane no longer defines {scope}')
    chains = set()
    for node in ast.walk(root):
        if isinstance(node, ast.Attribute):
            parts, cursor = [], node
            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                parts.append(cursor.id)
            chains.add('.'.join(reversed(parts)))
    return chains


def pane_replace_literals():
    """String literals the code hands to a `.replace(...)` call."""
    literals = []
    for node in ast.walk(ast.parse(PANE_SOURCE)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'replace':
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literals.append(arg.value)
    return literals


def write_cloud(path, points, colors=None):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=np.float64))
    cloud.colors = o3d.utility.Vector3dVector(
        np.asarray(colors, dtype=np.float64) if colors is not None
        else np.asarray(points, dtype=np.float64)[:, ::-1] % 1.0)
    if not o3d.io.write_point_cloud(path, cloud):
        raise RuntimeError(f'could not write the fixture {path}')
    return path


def cloud_count(path):
    """The points in a file, counted by the reader this app uses - not by the pane."""
    return len(o3d.io.read_point_cloud(path).points)


def mesh_counts(path):
    mesh, _ = FormatConverter().read_mesh(path)
    return len(mesh.vertices), len(mesh.faces)


def _ancestors(widget):
    out, current = [], widget.parentWidget()
    while current is not None:
        out.append(current)
        current = current.parentWidget()
    return out


def cancel_button_of(dialog):
    """The Cancel the user actually presses.

    `QProgressDialog.cancel()` exists in this PyQt6 build and hides the dialog without
    emitting `canceled`, so calling it would leave a running worker untouched and let a
    Cancel that reaches nothing pass.
    """
    for button in dialog.findChildren(QPushButton):
        if button.text() == 'Cancel':
            return button
    raise AssertionError('the progress dialog has no Cancel button to press')


# The buttons this suite drives, with what each one has to leave behind. `suffix` is the
# part of the output name the backend builds, `fragment` is words the sentence must contain,
# and `adopts` says whether the file it wrote becomes the pane's current model.
CLOUD_VERBS = [
    ('voxel_downsample_btn', 'voxel', 'downsampled', 'voxel 0.01', True),
    ('remove_outliers_btn', 'outliers_statistical', 'filtered', 'removed', True),
    ('remove_radius_outliers_btn', 'outliers_radius', 'radius_filtered', 'removed', True),
    ('uniform_downsample_btn', 'uniform', 'uniform', 'every 5th point', True),
    ('center_btn', 'center', 'centered', 'moved by', True),
    ('normalize_btn', 'normalize', 'normalized', 'scaled by', True),
    ('remove_duplicates_btn', 'dedup', 'deduped', 'coincident points removed', True),
    ('estimate_normals_btn', 'normals', 'normals', 'normals on', True),
    ('apply_translation_btn', 'translate', 'translate', 'moved by', True),
    ('apply_rotation_btn', 'rotate', 'rotate', 'turned', True),
    ('apply_scale_btn', 'scale', 'scale', 'scaled by', True),
]

SURFACE_BUTTONS = [
    ('create_convex_hull_btn', 'hull'),
    ('run_ball_pivoting_btn', 'ball_pivoting'),
    ('run_poisson_btn', 'poisson'),
    ('run_alpha_shapes_btn', 'alpha_shape'),
]

# The numbers each action is run with: the same ones the pane's controls hold for that verb
# (test_05 and test_15 set them by spin box), so the task path measures the run the button
# makes. A verb left out works on its backend default.
AUTOMATION_ARGS = {
    'voxel': {'voxel_size': 0.01},
    'uniform': {'every_k': 5},
    'outliers_radius': {'nb_points': 3},
    'normals': {'knn': 8},
    'crop': {'min_bound': [0.25, 0.25, 0.25], 'max_bound': [0.75, 0.75, 0.75]},
    'translate': {'dx': 1.0},
    'rotate': {'rx': 30.0},
    'scale': {'factor': 2.0},
    'cluster': {'eps': 0.2, 'min_points': 5},
    'poisson': {'depth': 6},
    'alpha_shape': {'alpha': 0.1},
    'export': {'extension': '.ply'},
    'register_icp': {'threshold': 0.02, 'max_iteration': 100},
}

# Everything the pane offers by button. A control outside this list is a control nobody
# tested, which the ground rules treat as a defect.
DRIVEN_BUTTONS = {name for name, _, _, _, _ in CLOUD_VERBS} | {
    name for name, _ in SURFACE_BUTTONS} | {
    'load_pcd_btn', 'save_pcd_btn', 'export_mesh_btn', 'change_model_btn', 'reload_btn',
    'add_model_btn', 'crop_box_btn', 'crop_interactive_btn', 'load_target_btn',
    'run_icp_btn', 'extract_features_btn', 'run_ransac_btn', 'compute_stats_btn',
    'compute_distances_btn', 'distance_histogram_btn', 'run_clustering_btn',
    'detect_planes_btn', 'export_pcd_btn', 'export_ply_btn', 'export_xyz_btn',
    'export_obj_btn', 'clear_history_btn', 'reset_view_btn', 'fit_view_btn',
    'screenshot_btn'}


class RecordingDialogs:
    """Modal dialogs become data, so a refusal can be asserted instead of clicked away."""

    def __init__(self):
        self.messages = []
        self.question_answer = QMessageBox.StandardButton.No

    def install(self):
        recorder = self

        def make(kind):
            def show(parent, title, text, *args, **kwargs):
                recorder.messages.append((kind, title, str(text)))
                return QMessageBox.StandardButton.Ok
            return show

        QMessageBox.information = make('information')
        QMessageBox.warning = make('warning')
        QMessageBox.critical = make('critical')
        QMessageBox.question = lambda *a, **kw: recorder.question_answer
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok

    def kinds(self, *wanted):
        return [text for kind, _, text in self.messages if kind in wanted]

    def errors(self):
        return self.kinds('warning', 'critical')

    def texts(self):
        return ' | '.join(text for _, _, text in self.messages)


DIALOGS = RecordingDialogs()
DIALOGS.install()


class FileChoosers:
    """Open and Save dialogs answer from a script: cancel, a fixed name, or the suggestion."""

    def __init__(self):
        self.open_answer = ('', '')
        self.save_mode = 'suggested'
        self.save_answer = None
        self.asked_suggested = []

    def install(self):
        choosers = self

        def get_open(parent, title, *args, **kwargs):
            return choosers.open_answer

        def get_save(parent, title, suggested='*', *args, **kwargs):
            choosers.asked_suggested.append(suggested)
            if choosers.save_mode == 'cancel':
                return ('', '')
            if choosers.save_mode == 'answer':
                return (choosers.save_answer, '')
            return (suggested, '')

        QFileDialog.getOpenFileName = get_open
        QFileDialog.getSaveFileName = get_save

    def reset(self):
        self.open_answer = ('', '')
        self.save_mode = 'suggested'
        self.save_answer = None
        self.asked_suggested = []


CHOOSERS = FileChoosers()
CHOOSERS.install()

EMBEDDED_DIALOGS = []


def _accept_dialog_exec(self):
    """`exec()` becomes "the user pressed Ok", with the widget kept for inspection."""
    EMBEDDED_DIALOGS.append(self)
    return 1


REAL_DIALOG_EXEC = QDialog.exec
QDialog.exec = _accept_dialog_exec


class StalledThread(CloudRunThread):
    """A worker that waits to be told to finish, then does the real run.

    It is held at the dialog so a Cancel, a second click and a verdict that never arrives
    can each be measured. The verdict it eventually posts is the backend's own - a stub
    verdict of the right shape is how a suite ends up testing its own invention.
    """

    release = None
    silent = False

    def run(self):
        if StalledThread.release is not None:
            StalledThread.release.wait(30)
        if not StalledThread.silent:
            CloudRunThread.run(self)


class WatchingProcessor:
    """Stands in for the backend only long enough to prove Cancel reaches a running verb."""

    def __init__(self):
        self.saw_cancel_request = False

    def run(self, operation, params, should_cancel=None):
        for _ in range(3000):
            if should_cancel is not None and should_cancel():
                self.saw_cancel_request = True
                return {'operation': operation, 'success': False, 'stopped': True,
                        'error': f'{operation} was stopped before it wrote anything',
                        'files': [], 'measure': {}}
            time.sleep(0.005)
        return {'operation': operation, 'success': False, 'stopped': False,
                'error': 'the stand-in backend was never asked to stop', 'files': []}


class PointCloudsContract(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='clouds_contract_')
        cls.points = RNG.random((900, 3))
        cls.source = write_cloud(os.path.join(cls.work, 'source.ply'), cls.points)
        cls.target = write_cloud(os.path.join(cls.work, 'target.ply'),
                                 cls.points + np.array([0.04, 0.0, 0.0]))
        with open(os.path.join(cls.work, 'notes.txt'), 'w', encoding='utf-8') as handle:
            handle.write('not a cloud\n')
        cls.tab = PointCloudsTab()
        cls.real_processor = cls.tab.pc_processor

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        del SLOT_FAULTS[:]
        del DIALOGS.messages[:]
        del EMBEDDED_DIALOGS[:]
        CHOOSERS.reset()
        self.tab.pc_processor = self.real_processor
        PANE.CloudRunThread = CloudRunThread
        StalledThread.release = None
        StalledThread.silent = False
        self.reset_controls()
        self.case = tempfile.mkdtemp(prefix='clouds_case_', dir=self.work)
        self.scan = os.path.join(self.case, 'scan.ply')
        shutil.copyfile(self.source, self.scan)
        self.load(self.scan)

    def reset_controls(self):
        """One tab serves the whole suite, so every test starts on the pane's own defaults.

        Without this, the numbers one test typed are the numbers the next test is refused
        for, and a failure names a button that was never touched.
        """
        for name, value in (
                ('voxel_size_spin', 0.01), ('uniform_k_spin', 5), ('normals_knn_spin', 30),
                ('trans_x_spin', 0.0), ('trans_y_spin', 0.0), ('trans_z_spin', 0.0),
                ('rot_x_spin', 0.0), ('rot_y_spin', 0.0), ('rot_z_spin', 0.0),
                ('scale_spin', 1.0), ('outlier_neighbors_spin', 20), ('outlier_std_spin', 2.0),
                ('radius_spin', 0.05), ('min_points_spin', 16), ('icp_threshold_spin', 0.02),
                ('icp_max_iter_spin', 100), ('feature_voxel_spin', 0.0),
                ('poisson_depth_spin', 9), ('poisson_width_spin', 0), ('poisson_scale_spin', 1.1),
                ('ball_radius_spin', 0.0), ('alpha_value_spin', 0.03),
                ('cluster_eps_spin', 0.02), ('cluster_min_points_spin', 10),
                ('plane_threshold_spin', 0.01), ('plane_ransac_n_spin', 3),
                ('plane_iterations_spin', 1000), ('point_size_box', 3.0)):
            self.set_spin(name, value)
        self.tab.point_size_slider.blockSignals(True)
        self.tab.point_size_slider.setValue(3)
        self.tab.point_size_slider.blockSignals(False)
        for box in (self.tab.show_normals_cb, self.tab.show_wireframe_cb,
                    self.tab.poisson_linear_fit_cb):
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self.tab.poisson_trim_cb.blockSignals(True)
        self.tab.poisson_trim_cb.setChecked(True)
        self.tab.poisson_trim_cb.blockSignals(False)
        self.tab.surface_format_combo.setCurrentText('.ply')
        self.tab.target_model_path = None
        self.tab.target_info_label.setText('No target loaded')

    def tearDown(self):
        self.assertEqual(SLOT_FAULTS, [], f'a slot raised: {SLOT_FAULTS}')
        shutil.rmtree(self.case, ignore_errors=True)

    # ---- the helpers every test is measured with --------------------------------

    def drain(self, timeout=240.0):
        """Wait for the pane's workers, the ones it starts while waiting, and the viewer."""
        deadline = time.time() + timeout
        while True:
            busy = False
            for worker in list(self.tab._workers):
                if worker.isRunning():
                    busy = True
            for worker in list(self.tab._workers):
                self.assertTrue(worker.wait(60000), f'{worker} never finished')
            preview = self.tab.viewer.preview_worker
            if preview is not None and preview.isRunning():
                busy = True
                preview.wait(60000)
            APP.processEvents()
            if not self.tab._workers and not busy:
                return
            if time.time() > deadline:
                self.fail('the pane never stops starting workers')

    def spin(self, seconds=0.3):
        deadline = time.time() + seconds
        while time.time() < deadline:
            APP.processEvents()
            time.sleep(0.01)

    def load(self, path):
        self.tab.load_point_cloud_file(path)
        self.drain()

    def files(self):
        return sorted(f for f in os.listdir(self.case) if f != 'scan.ply')

    def click(self, name):
        getattr(self.tab, name).click()
        self.drain()

    def click_now(self, name):
        """Click and stop at the dialog, before the verdict is allowed to land."""
        getattr(self.tab, name).click()
        deadline = time.time() + 30
        while self.tab._active_thread is None and time.time() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertIsNotNone(self.tab._active_thread, f'{name} never started a run')

    def label(self):
        return self.tab.operation_label.text()

    def history(self):
        return [self.tab.history_list.item(i).text()
                for i in range(self.tab.history_list.count())]

    def set_spin(self, name, value):
        box = getattr(self.tab, name)
        if isinstance(box, QSpinBox):
            box.setValue(int(value))
        elif isinstance(box, QDoubleSpinBox):
            box.setValue(float(value))
        else:
            self.fail(f'{name} is a {type(box).__name__}, not a number box')

    # ---- 1. every control the pane shows is a control this suite drives ---------

    def test_01_every_button_in_the_pane_is_accounted_for(self):
        named = {}
        for attr, value in list(vars(self.tab).items()):
            if isinstance(value, QPushButton):
                named[id(value)] = attr
        embedded = set(self.tab.viewer.findChildren(QPushButton))
        anonymous, shown = [], set()
        for button in self.tab.findChildren(QPushButton):
            if button in embedded:
                continue          # the shared viewer's own buttons, covered by its panes
            if any(isinstance(a, QProgressDialog) for a in _ancestors(button)):
                continue          # the Cancel of a modal dialog, not a control of this pane
            name = named.get(id(button))
            if name is None:
                anonymous.append(button.text())
            else:
                shown.add(name)
        self.assertEqual(anonymous, [],
                         'buttons built inside a builder and never stored cannot be tested')
        self.assertEqual(sorted(shown - DRIVEN_BUTTONS), [],
                         'these controls exist in the pane and no test touches them')
        self.assertEqual(sorted(DRIVEN_BUTTONS - shown), [],
                         'the suite names buttons the pane no longer has')

    def test_02_the_pane_keeps_its_own_copy_of_the_math(self):
        """A second implementation of an operation is how a pane ends up reporting numbers
        the backend never measured, and how `self.processor` comes to be read while still
        never assigned."""
        own_math = {'open3d', 'o3d', 'numpy', 'np', 'matplotlib', 'pyplot', 'plt', 'scipy',
                    'trimesh'}
        self.assertEqual(sorted(pane_names_used() & own_math), [],
                         'the pane imports a math library and measures for itself again')

        tab = pane_chains('PointCloudsTab')
        for stale in ('self.processor', 'self.current_cloud_path', 'self.current_mesh_path'):
            self.assertNotIn(stale, tab, f'{stale} is read by the pane and assigned nowhere')

        backend_calls = sorted(c for c in tab if c.startswith('self.pc_processor.')
                               and c != 'self.pc_processor')
        self.assertEqual(backend_calls, ['self.pc_processor.output_path',
                                         'self.pc_processor.readable_formats',
                                         'self.pc_processor.surface_formats',
                                         'self.pc_processor.surface_target'],
                         'the pane reaches for a backend method outside the verbs it owns')
        for chain in backend_calls + ['self.processor.run']:
            name = chain.split('.')[-1]
            owner = PointCloudProcessor
            self.assertTrue(callable(getattr(owner, name, None)),
                            f'the pane calls {chain}, which the backend does not have')
        self.assertIn('self.processor.run', pane_chains('CloudRunThread'),
                      'the worker no longer asks the backend for the verdict')

        # `path.replace('.', '_x.')` rewrites every dot on disk, including the ones in a
        # folder called `v1.2`; output names come from the backend's own `output_path`.
        self.assertEqual([lit for lit in pane_replace_literals() if '.' in lit], [],
                         'a file name is being rebuilt by replacing dots')

        # ...and one name only, because a verb's file is the backend's decision
        # (`PointCloudProcessor.target_path`). The single name the pane may hand a verb is
        # the one a person typed in the Export dialog. A second copy of a derived name
        # agrees with the backend by accident, so no test can tell it from one that stops
        # agreeing - which is how a pane ends up writing a file nobody reported.
        params_that_name = [node.lineno for node in ast.walk(ast.parse(PANE_SOURCE))
                            if isinstance(node, ast.Dict) and any(
                                isinstance(key, ast.Constant)
                                and key.value in ('output_path', 'plane_path', 'rest_path')
                                for key in node.keys if key is not None)]
        self.assertEqual(len(params_that_name), 1,
                         f'the pane names a verb output at lines {params_that_name}, where '
                         f'the backend already names it')

    def test_03_loading_measures_the_file_it_shows(self):
        self.assertEqual(self.tab.current_model_path, self.scan)
        self.assertEqual(self.label(), '900 points measured', self.label())
        self.assertEqual(self.tab.info_points.text(), '900')
        block = self.tab.detailed_stats.toPlainText()
        stats = self.real_processor.run('analyze', {'file_path': self.scan})['measure']
        for line in self.tab._statistics_block(stats['statistics'], stats.get('bytes')):
            self.assertIn(line, block, f'{line!r} is missing from the Statistics report')
        self.assertIn(self.tab.info_bounds.text(), block)

    def test_04_a_file_that_is_not_a_cloud_is_refused_by_name(self):
        before = self.tab.current_model_path
        self.load(os.path.join(self.work, 'notes.txt'))
        self.assertEqual(self.tab.current_model_path, before,
                         'the header moved to a file the viewer could not show')
        self.assertIn('notes.txt', self.label())
        self.assertTrue(DIALOGS.kinds('warning'), 'an unreadable file reported nothing')

    # ---- 5. the cloud verbs: a file, a number off that file, a sentence --------

    def test_05_each_cloud_verb_writes_the_file_it_names(self):
        configure = {
            'remove_radius_outliers_btn': lambda: self.set_spin('min_points_spin', 3),
            'apply_translation_btn': lambda: [self.set_spin(f'trans_{a}_spin', 1.0)
                                              for a in 'xyz'],
            'apply_rotation_btn': lambda: self.set_spin('rot_x_spin', 30.0),
            'apply_scale_btn': lambda: self.set_spin('scale_spin', 2.0),
            'estimate_normals_btn': lambda: self.set_spin('normals_knn_spin', 8),
        }
        for name, verb, suffix, fragment, adopts in CLOUD_VERBS:
            with self.subTest(verb=verb):
                self.load(self.scan)
                if name in configure:
                    configure[name]()
                before_files = set(self.files())
                self.click(name)
                landed = set(self.files()) - before_files
                self.assertEqual(len(landed), 1, f'{verb} wrote {sorted(landed)}')
                written = os.path.join(self.case, landed.pop())
                self.assertIn(f'_{suffix}.ply', written,
                              f'{verb} did not write the name the pane offered')
                self.assertGreater(os.path.getsize(written), 0, f'{verb} wrote an empty file')
                self.assertIn(fragment, self.label(), f'{verb} reported {self.label()!r}')
                self.assertFalse(self.label().endswith('...'),
                                 f'{verb} left a running sentence standing')
                self.assertEqual(self.history()[-1].split(':')[0], OP_NAMES[verb],
                                 self.history())
                if adopts:
                    self.assertEqual(self.tab.current_model_path, written,
                                     f'{verb} wrote a cloud the pane then ignored')
                    self.assertEqual(self.tab.info_points.text(), f'{cloud_count(written):,}',
                                     f'{verb}: the Points field does not match '
                                     f'{os.path.basename(written)}')
                else:
                    self.assertEqual(self.tab.current_model_path, self.scan)

    def test_06_the_counts_in_the_sentence_are_the_counts_in_the_file(self):
        self.set_spin('voxel_size_spin', 0.1)
        self.click('voxel_downsample_btn')
        written = self.tab.current_model_path
        self.assertIn(f'kept {cloud_count(written):,} of', self.label(), self.label())
        self.assertIn('900', self.label(), 'the sentence did not say what it was kept out of')
        self.assertIn('0.1', self.label(), 'the voxel size typed never reached the sentence')

    def test_07_runs_chain_onto_what_the_previous_run_wrote(self):
        """Downsample, filter, reconstruct only works if each step reads the last file."""
        self.set_spin('voxel_size_spin', 0.05)
        self.click('voxel_downsample_btn')
        first = self.tab.current_model_path
        self.assertEqual(os.path.basename(first), 'scan_downsampled.ply')
        self.set_spin('min_points_spin', 3)
        self.click('remove_radius_outliers_btn')
        second = self.tab.current_model_path
        self.assertEqual(os.path.basename(second), 'scan_downsampled_radius_filtered.ply')
        self.click('create_convex_hull_btn')
        self.assertEqual(self.tab.current_model_path, second,
                         'a surface became the current cloud')
        self.assertEqual(self.tab.last_surface_path,
                         os.path.join(self.case, 'scan_downsampled_radius_filtered_hull.ply'),
                         'the surface the hull wrote was not remembered')
        self.assertTrue(os.path.isfile(self.tab.last_surface_path))

    # ---- 8. refusals: a reason, no file, no move on ---------------------------

    def test_08_a_refusal_names_the_reason_and_writes_nothing(self):
        refusals = [
            ('voxel_downsample_btn', lambda: self.set_spin('voxel_size_spin', 0.0),
             'a voxel edge of 0.0 is not a length'),
            ('uniform_downsample_btn', lambda: self.set_spin('uniform_k_spin', 1),
             'keeping every 1-th point keeps them all'),
            ('apply_translation_btn', lambda: [self.set_spin(f'trans_{a}_spin', 0.0)
                                               for a in 'xyz'],
             'moving by (0, 0, 0)'),
            ('apply_rotation_btn', None, 'turning by (0, 0, 0)'),
            ('apply_scale_btn', lambda: self.set_spin('scale_spin', 1.0),
             'a scale of 1 leaves every point where it is'),
            ('estimate_normals_btn', lambda: self.set_spin('normals_knn_spin', 4000),
             'needs a cloud of at least 4000 points and this one has 900'),
            ('remove_radius_outliers_btn', lambda: self.set_spin('min_points_spin', 900),
             'would hold no points'),
            ('run_clustering_btn', lambda: [self.set_spin('cluster_eps_spin', 0.0001),
                                            self.set_spin('cluster_min_points_spin', 40)],
             'noise'),
            ('run_alpha_shapes_btn', lambda: self.set_spin('alpha_value_spin', 0.0001),
             'no faces at all'),
        ]
        for name, setting, phrase in refusals:
            with self.subTest(button=name):
                self.load(self.scan)
                if setting:
                    setting()
                del DIALOGS.messages[:]
                before = self.tab.current_model_path
                files_before = self.files()
                self.click(name)
                self.assertEqual(self.files(), files_before,
                                 'a refused run still wrote a file')
                self.assertEqual(self.tab.current_model_path, before,
                                 'a refused run moved the current model anyway')
                self.assertTrue(DIALOGS.kinds('warning'),
                                 f'{name} refused without saying so: {self.label()!r}')
                self.assertIn(phrase, DIALOGS.texts(), DIALOGS.texts())
                self.assertIn(phrase, self.label(), self.label())
                # A condition the backend knows about is a refusal, not a crash. Without this
                # the suite accepts `normals did not finish: RuntimeError: <the same words>`
                # and the pane's own guard can disappear while the sentence survives.
                self.assertNotIn('did not finish', DIALOGS.texts(),
                                 f'{name} met a known condition and called it a crash')

    def test_09_every_verb_refuses_without_a_loaded_cloud(self):
        self.tab.current_model_path = None
        for name, _, _, _, _ in CLOUD_VERBS:
            with self.subTest(button=name):
                del DIALOGS.messages[:]
                getattr(self.tab, name).click()
                self.drain()
                self.assertIn('Load a point cloud first', DIALOGS.texts(),
                              f'{name} answered with no cloud loaded')

    def test_10_the_crop_dialog_opens_on_the_box_the_cloud_fills(self):
        self.click('crop_box_btn')
        self.assertEqual(len(EMBEDDED_DIALOGS), 1, 'the crop button did not open a dialog')
        dialog = EMBEDDED_DIALOGS[0]
        self.assertIsInstance(dialog, BoundingBoxDialog)
        stats = self.real_processor.run('analyze', {'file_path': self.scan})['measure']
        centre = stats['statistics']['centroid']
        extent = stats['statistics']['bounding_box']
        # The dialog lays one axis out as a Min row above a Max row, so the boxes interleave:
        # [min x, max x, min y, max y, min z, max z].
        expected = []
        for index in range(3):
            expected.append(centre[index] - extent[index] / 2.0)
            expected.append(centre[index] + extent[index] / 2.0)
        for spin, want in zip(dialog._spins, expected):
            self.assertAlmostEqual(spin.value(), want, places=5,
                                   msg='the box did not start on the measured bounds')
            self.assertEqual(spin.maximum(), 1e12,
                             'a survey scan in metres cannot be entered at all')
        self.assertIn('box kept', self.label(), self.label())
        self.assertIn('scan_cropped.ply', self.files())

    def test_11_an_impossible_crop_is_refused_not_emptied(self):
        def flip(dialog):
            for index in (0, 2, 4):
                dialog._spins[index].setValue(50.0)
            return 1

        def exec_flip(self):
            EMBEDDED_DIALOGS.append(self)
            return flip(self)

        QDialog.exec = exec_flip
        try:
            del DIALOGS.messages[:]
            self.click('crop_box_btn')
        finally:
            QDialog.exec = _accept_dialog_exec
        self.assertIn('smaller', DIALOGS.texts(), DIALOGS.texts())
        self.assertNotIn('scan_cropped.ply', self.files())
        self.assertEqual(self.tab.current_model_path, self.scan)

    # ---- 12. planes, distances, histogram, clustering -------------------------

    def test_12_planes_write_two_clouds_that_add_up(self):
        self.click('detect_planes_btn')
        self.assertEqual(self.files(), ['scan_off_plane.ply', 'scan_plane.ply'])
        on = cloud_count(os.path.join(self.case, 'scan_plane.ply'))
        off = cloud_count(os.path.join(self.case, 'scan_off_plane.ply'))
        self.assertEqual(on + off, 900, 'the two files do not hold the cloud they split')
        self.assertIn(f'{on:,} on it, {off:,} off it', self.label(), self.label())
        self.assertIn('Plane equation', self.tab.stats_display.toPlainText(),
                      'the Analyze tab is where this button lives and where its report is')
        self.assertEqual(self.tab.registration_results.toPlainText(), '',
                         'the report went to a different tab again')
        self.assertEqual(self.tab.current_model_path, self.scan, 'a split took over the pane')

    def test_13_distances_then_the_histogram_that_uses_them(self):
        del DIALOGS.messages[:]
        self.click('distance_histogram_btn')
        self.assertIn("Run 'Compute Nearest Distances' first", DIALOGS.texts())
        self.assertEqual(self.tab.histogram_view.toPlainText(), '')

        self.click('compute_distances_btn')
        measure = self.tab.last_distances
        self.assertEqual(len(measure['histogram']['counts']), 10,
                         'the backend promised ten bins')
        self.click('distance_histogram_btn')
        view = self.tab.histogram_view.toPlainText()
        self.assertEqual(len([line for line in view.splitlines() if '|' in line]), 10, view)
        for count in measure['histogram']['counts']:
            self.assertIn(f'{count:,}', view, 'a bin the backend measured is not drawn')
        self.assertIn('samples in 10 bins', view)
        self.assertIn('Histogram of', self.label(), self.label())

    def test_14_clustering_writes_the_labels_it_counts(self):
        self.set_spin('cluster_eps_spin', 0.2)
        self.set_spin('cluster_min_points_spin', 5)
        self.click('run_clustering_btn')
        self.assertIn('scan_clustered.ply', self.files(), self.files())
        self.assertIn('clusters', self.label(), self.label())
        self.assertIn(self.tab.current_model_path,
                      [os.path.join(self.case, 'scan_clustered.ply')])

    # ---- 15. surfaces --------------------------------------------------------

    def test_15_each_surface_verb_writes_a_mesh_the_app_reads_back(self):
        self.assertEqual(self.tab.surface_format_combo.currentText(), '.ply',
                         'the opening choice is not the format this app always reads back')
        configure = {
            'run_poisson_btn': lambda: self.set_spin('poisson_depth_spin', 6),
            # 0.1 is this cloud's own spacing: at the pane's default 0.03 the alpha shape
            # answers with four faces, and at 0.0001 with none (pinned in test_08).
            'run_alpha_shapes_btn': lambda: self.set_spin('alpha_value_spin', 0.1),
        }
        for name, verb in SURFACE_BUTTONS:
            with self.subTest(verb=verb):
                self.load(self.scan)
                if name in configure:
                    configure[name]()
                self.click(name)
                expected = f'scan_{verb}.ply'
                self.assertIn(expected, self.files(), f'{verb} wrote {self.files()}')
                written = os.path.join(self.case, expected)
                vertices, faces = mesh_counts(written)
                self.assertGreater(faces, 0, f'{verb} left a mesh with no faces')
                self.assertEqual(self.tab.last_surface_path, written)
                self.assertIn(f'{vertices:,} vertices, {faces:,} faces', self.label(),
                              f'{verb} reported {self.label()!r}')
                info = self.tab.info_surface.text()
                self.assertIn(expected, info, info)
                self.assertIn(f'{faces:,} faces', info, info)
                self.assertEqual(self.tab.current_model_path, self.scan,
                                 f'{verb} made the surface the current cloud')

    def test_16_the_surface_format_chosen_is_the_surface_written(self):
        index = next(i for i in range(self.tab.surface_format_combo.count())
                     if self.tab.surface_format_combo.itemText(i) == '.stl')
        self.tab.surface_format_combo.setCurrentIndex(index)
        self.click('create_convex_hull_btn')
        self.assertIn('scan_hull.stl', self.files(), self.files())
        self.assertEqual(self.tab.last_surface_path,
                         os.path.join(self.case, 'scan_hull.stl'))

    def test_17_export_as_mesh_needs_a_surface_and_then_hands_one_over(self):
        del DIALOGS.messages[:]
        self.click('export_mesh_btn')
        self.assertIn('No surface has been built', DIALOGS.texts())
        self.assertEqual(self.files(), [])

        self.set_spin('poisson_depth_spin', 6)
        self.click('run_poisson_btn')
        target = os.path.join(self.case, 'given_mesh.stl')
        CHOOSERS.save_mode = 'answer'
        CHOOSERS.save_answer = target
        emitted = []
        self.tab.mesh_generated.connect(lambda path: emitted.append(path))
        DIALOGS.question_answer = QMessageBox.StandardButton.Yes
        try:
            self.click('export_mesh_btn')
        finally:
            self.tab.mesh_generated.disconnect()
            DIALOGS.question_answer = QMessageBox.StandardButton.No
            CHOOSERS.save_mode = 'suggested'
        vertices, faces = mesh_counts(target)
        self.assertGreater(faces, 0, 'the exported mesh has no faces')
        self.assertIn('Surface exported', self.label(), self.label())
        self.assertEqual(emitted, [target],
                         'the pane exported a mesh and never offered it to Mesh Tools')

    def test_18_a_surface_survives_a_reload_and_a_new_cloud_forgets_it(self):
        self.click('create_convex_hull_btn')
        surface = self.tab.last_surface_path
        self.tab.reload_btn.click()
        self.drain()
        self.assertEqual(self.tab.last_surface_path, surface,
                         'reloading the same cloud forgot the surface built from it')
        self.load(self.target)
        self.assertIsNone(self.tab.last_surface_path,
                          'a different cloud kept the surface made from the first one')

    # ---- 19. registration ----------------------------------------------------

    def test_19_registration_needs_two_clouds_and_reports_the_fit(self):
        del DIALOGS.messages[:]
        self.click('run_icp_btn')
        self.assertIn('Alignment needs two clouds', DIALOGS.texts())
        self.assertEqual(self.files(), [])

        CHOOSERS.open_answer = (self.target, '')
        self.click('load_target_btn')
        self.assertIn('target.ply', self.tab.target_info_label.text())
        self.click('extract_features_btn')
        self.assertEqual(self.files(), [], 'a feature pass wrote a file it cannot need')
        self.assertIn('source and', self.label(), self.label())
        self.assertIn('FPFH features', self.tab.registration_results.toPlainText())
        before = set(self.files())
        self.click('run_icp_btn')
        landed = set(self.files()) - before
        self.assertEqual(len(landed), 1, sorted(landed))
        written = os.path.join(self.case, landed.pop())
        self.assertIn('register_icp', written)
        self.assertGreater(cloud_count(written), 0)
        self.assertIn('fitness', self.label(), self.label())
        self.assertIn('Transformation applied',
                      self.tab.registration_results.toPlainText())
        self.click('run_ransac_btn')
        self.assertIn('fitness', self.label(), self.label())

    # ---- 20. export ----------------------------------------------------------

    def test_20_export_writes_the_file_and_reads_back_except_for_obj(self):
        buttons = {'.pcd': 'export_pcd_btn', '.ply': 'export_ply_btn',
                   '.xyz': 'export_xyz_btn', '.obj': 'export_obj_btn'}
        for extension, name in buttons.items():
            with self.subTest(extension=extension):
                self.load(self.scan)
                self.click(name)
                expected = f'scan_export{extension}'
                self.assertIn(expected, self.files(), self.files())
                written = os.path.join(self.case, expected)
                self.assertGreater(os.path.getsize(written), 0)
                if extension == '.obj':
                    self.assertIn('positions only', self.label(),
                                  'an OBJ with no faces was reported as if it were a mesh')
                else:
                    self.assertEqual(cloud_count(written), 900,
                                     f'{extension} did not hold the cloud it was given')
                    self.assertNotIn('positions only', self.label())
                self.assertEqual(self.tab.current_model_path, self.scan,
                                 'an export became the current model')

    def test_21_a_cancelled_save_dialog_writes_nothing(self):
        CHOOSERS.save_mode = 'cancel'
        self.click('export_ply_btn')
        self.assertEqual(self.files(), [])
        self.assertEqual(self.label(), '900 points measured', self.label())

    def test_22_save_reuses_the_name_the_pane_suggested(self):
        self.click('export_pcd_btn')
        self.assertEqual(self.tab.current_model_path, self.scan)
        self.assertIn('scan_export.pcd', self.files(), self.files())
        self.click('save_pcd_btn')
        self.assertIn('scan_export.ply', self.files(), self.files())

    # ---- 23. progress, cancel, and the two signal-ordering defects -----------

    def test_23_the_dialog_counts_files_not_hope(self):
        for name, operation, maximum in (('voxel_downsample_btn', 'voxel', 1),
                                         ('detect_planes_btn', 'planes', 2),
                                         ('compute_stats_btn', 'analyze', 1)):
            with self.subTest(operation=operation):
                PANE.CloudRunThread = StalledThread
                StalledThread.release = threading.Event()
                try:
                    self.click_now(name)
                    dialog = self.tab._run_progress
                    self.assertIsNotNone(dialog, f'{operation} started without a dialog')
                    self.assertEqual(dialog.maximum(), maximum,
                                     f'{operation} promised {dialog.maximum()} files, '
                                     f'not {VERB_OUTPUT_FILES[operation]}')
                    self.assertEqual(dialog.value(), 0)
                    self.assertEqual(dialog.labelText(), RUNNING_TEXT[operation])
                    self.assertEqual(self.label(), RUNNING_TEXT[operation])
                finally:
                    StalledThread.release.set()
                    PANE.CloudRunThread = CloudRunThread
                    self.drain()

    def test_24_cancel_reaches_the_run_and_says_what_stopped(self):
        watcher = WatchingProcessor()
        self.tab.pc_processor = watcher
        history_before = self.history()
        dialog = None
        try:
            self.click_now('voxel_downsample_btn')
            dialog = self.tab._run_progress
            cancel_button_of(dialog).click()
            deadline = time.time() + 60
            while self.tab._active_thread is not None and time.time() < deadline:
                APP.processEvents()
                time.sleep(0.01)
            self.assertTrue(self.tab._active_thread is None, 'the cancelled run never ended')
            self.spin(0.5)
            self.assertTrue(watcher.saw_cancel_request, 'Cancel never reached the backend')
            self.assertIn('Stopped', self.label(), self.label())
            self.assertIn('stopped before it wrote anything', DIALOGS.texts())
            self.assertFalse(dialog.isVisible(), 'the dialog stayed open after the verdict')
            self.assertEqual(self.history(), history_before,
                             'a cancelled run logged a finished operation')
        finally:
            self.tab.pc_processor = self.real_processor

    def test_25_a_second_click_names_the_run_already_in_flight(self):
        PANE.CloudRunThread = StalledThread
        StalledThread.release = threading.Event()
        try:
            self.click_now('voxel_downsample_btn')
            del DIALOGS.messages[:]
            workers_before = len(self.tab._workers)
            self.tab.center_btn.click()
            self.spin(0.3)
            self.assertIn('is still running', DIALOGS.texts(), DIALOGS.texts())
            self.assertIn(RUNNING_TEXT['voxel'], DIALOGS.texts(), DIALOGS.texts())
            self.assertIn(RUNNING_TEXT['center'].lower(), DIALOGS.texts(), DIALOGS.texts())
            self.assertEqual(len(self.tab._workers), workers_before,
                             'the second click started a thread anyway')
        finally:
            StalledThread.release.set()
            PANE.CloudRunThread = CloudRunThread
            self.drain()

    def test_26_a_thread_that_reports_nothing_is_reported_by_the_pane(self):
        """`finished` without `verdict_ready` must still close the dialog and say so."""
        PANE.CloudRunThread = StalledThread
        StalledThread.release = threading.Event()
        StalledThread.silent = True
        try:
            self.tab.voxel_downsample_btn.click()
            # Grabbed before the thread has a chance to end, because `_end_run` is the very
            # handler that empties `self._run_progress`.
            dialog = self.tab._run_progress
            self.assertIsNotNone(dialog, 'the click started a run with no dialog')
            deadline = time.time() + 30
            while self.tab._active_thread is not None and time.time() < deadline:
                APP.processEvents()
                time.sleep(0.01)
            self.spin(0.5)
            self.assertIn('ended without reporting a result', self.label(), self.label())
            self.assertTrue(DIALOGS.kinds('warning'), 'a silent thread reported nothing')
            self.assertIsNone(self.tab._active_thread, 'the pane still thinks it is running')
            self.assertFalse(dialog.isVisible(), 'the dialog outlived the thread')
        finally:
            StalledThread.release.set()
            PANE.CloudRunThread = CloudRunThread
            self.drain()

    def test_27_a_verb_that_measures_its_result_reports_one_verdict(self):
        """The follow-up measure must not be mistaken for the verb ending silently."""
        history_before = self.history()
        self.click('voxel_downsample_btn')
        self.assertNotIn('ended without reporting a result', DIALOGS.texts(),
                         DIALOGS.texts())
        self.assertIn('voxel 0.01', self.label(), self.label())
        self.assertEqual(len(self.history()), len(history_before) + 1, self.history())
        self.assertNotIn('Measuring', self.label())

    # ---- 28. the viewer ------------------------------------------------------

    def test_28_the_point_size_box_and_slider_agree_both_ways(self):
        self.tab.point_size_slider.setValue(7)
        self.drain()
        self.assertEqual(self.tab.point_size_box.value(), 7.0)
        self.assertEqual(self.tab.viewer.current_settings['point_size'], 7.0)
        # A value outside the slider is kept, not quietly rewritten - and the slider says
        # it cannot show it rather than pretending it still matches the box.
        self.tab.point_size_box.setValue(150.0)
        self.drain()
        self.assertEqual(self.tab.point_size_box.value(), 150.0)
        self.assertEqual(self.tab.point_size_slider.value(), 10)
        self.assertEqual(self.tab.viewer.current_settings['point_size'], 150.0)
        self.tab.point_size_box.setValue(0.0)
        self.drain()
        self.assertEqual(self.tab.point_size_box.value(), 0.0)
        self.assertEqual(self.tab.point_size_slider.value(), 1)
        self.assertEqual(self.tab.viewer.current_settings['point_size'], 0.0)

    def test_29_the_display_toggles_reach_the_render_settings(self):
        self.tab.show_normals_cb.setChecked(True)
        self.drain()
        self.assertTrue(self.tab.viewer.current_settings['show_normals'])
        self.tab.show_wireframe_cb.setChecked(True)
        self.drain()
        self.assertTrue(self.tab.viewer.current_settings['show_wireframe'])
        self.tab.reset_view_btn.click()
        self.drain()
        self.assertFalse(self.tab.viewer.current_settings['show_normals'])
        self.assertFalse(self.tab.viewer.current_settings['show_wireframe'])
        self.assertEqual(self.tab.point_size_box.value(), 3.0)
        self.assertEqual(self.tab.point_size_slider.value(), 3)
        self.assertIn('defaults', self.label(), self.label())

    def test_30_fit_and_screenshot_say_what_actually_happened(self):
        self.tab.viewer.geometries = []
        del DIALOGS.messages[:]
        self.tab.fit_view_btn.click()
        self.assertIn('no geometry in the viewer', DIALOGS.texts())
        self.load(self.scan)
        self.tab.fit_view_btn.click()
        self.assertIn('re-rendering', self.label(),
                      'a render on a background thread was claimed as already done')
        self.drain()
        hidden = self.tab.viewer.preview_pixmap
        self.tab.viewer.preview_pixmap = lambda: None
        try:
            del DIALOGS.messages[:]
            self.click('screenshot_btn')
            self.assertIn('no rendered preview', DIALOGS.texts(),
                          'a screenshot claimed a file it could not have written')
            self.assertEqual([f for f in os.listdir(self.case) if f.endswith('.png')], [])
        finally:
            self.tab.viewer.preview_pixmap = hidden

    def test_31_a_preview_that_failed_says_why_instead_of_still_rendering(self):
        self.assertIn('error_occurred.connect', VIEWER_SOURCE,
                      'the viewer is back to swallowing a failed render')
        self.assertIn('_on_preview_failed', VIEWER_SOURCE)
        self.tab.viewer._on_preview_failed('no OpenGL here')
        self.assertIn('Preview did not render: no OpenGL here',
                      self.tab.viewer.image_label.text())

    def test_32_a_screenshot_saves_the_picture_that_is_on_screen(self):
        shot = os.path.join(self.case, 'shot.png')
        self.tab.viewer.image_label.setPixmap(QPixmap(64, 48))
        CHOOSERS.save_mode = 'answer'
        CHOOSERS.save_answer = shot
        self.click('screenshot_btn')
        self.assertTrue(os.path.isfile(shot), self.label())
        self.assertIn('Screenshot saved', self.label(), self.label())
        with Image.open(shot) as picture:
            self.assertEqual(picture.size, (64, 48))
        self.assertIn('Screenshot saved', self.history()[-1])

    # ---- 33. the rest of the pane -------------------------------------------

    def test_33_add_to_library_hands_over_the_current_file(self):
        seen = []
        self.tab.add_to_library_requested.connect(lambda path: seen.append(path))
        try:
            self.click('add_model_btn')
        finally:
            self.tab.add_to_library_requested.disconnect()
        self.assertEqual(seen, [self.scan])
        self.assertIn('handed to the Library pane', self.label())
        self.tab.current_model_path = None
        del DIALOGS.messages[:]
        self.tab.add_model_btn.click()
        self.assertIn('Load a point cloud first', DIALOGS.texts())

    def test_34_clear_history_empties_the_list_it_filled(self):
        self.click('center_btn')
        self.assertTrue(self.history())
        self.tab.clear_history_btn.click()
        self.assertEqual(self.tab.history_list.count(), 0)
        self.assertEqual(self.label(), 'History cleared')

    def test_35_interactive_crop_promises_the_window_it_opens(self):
        requested = []
        original = self.tab._run

        def spy(operation, params, sentence=None, silent=False):
            requested.append(operation)
            return False

        self.tab._run = spy
        try:
            self.click('crop_interactive_btn')
        finally:
            self.tab._run = original
        self.assertEqual(requested, ['pick'], 'the interactive crop asked for no picking run')
        text = DIALOGS.texts()
        self.assertIn('Press Q', text, text)
        self.assertNotIn("'S'", text, 'the old instructions promised a key that does nothing')
        self.assertIn('refused', text, text)

    def test_36_main_window_wires_this_pane_to_its_neighbours(self):
        source = read_source('src', 'ui', 'main_window.py')
        self.assertIn('point_clouds_tab.mesh_generated.connect', source,
                      'a surface built here no longer reaches Mesh Tools')
        self.assertIn('point_clouds_tab.add_to_library_requested.connect', source,
                      'the Add to Library button emits into the void again')

    def test_37_every_verb_here_is_a_verb_the_scheduler_can_run(self):
        """A pane whose work cannot be automated is a pane the user has to sit in front of."""
        registered = {row[0] for row in PointCloudProcessor.AUTOMATION_TABLE}
        pane_verbs = {verb for verb in VERB_OUTPUT_FILES if verb != 'pick'}
        self.assertEqual(pane_verbs - registered, set(),
                         f'these verbs have a button and no action: {pane_verbs - registered}')
        self.assertNotIn('pick', registered, 'a verb that opens a window is scheduled for 3am')

    def test_38_the_surface_list_is_the_mesh_writer_list(self):
        """The Reconstruct tab must not offer a format the app's own writer refuses."""
        self.assertEqual(
            list(self.tab.surface_format_combo.itemText(i)
                 for i in range(self.tab.surface_format_combo.count())),
            sorted(FormatConverter().mesh_write_formats()))
        self.assertEqual(self.tab._cloud_filter().count('*'),
                         len(self.real_processor.readable_formats()) + 1)
        # Asked of a pane as the main window builds it. The shared one has been through
        # `reset_controls`, so reading its combo here would only prove the suite can set a value.
        fresh = PointCloudsTab()
        try:
            self.assertEqual(fresh.surface_format_combo.currentText(), '.ply',
                             'the format on screen when the pane opens is one this app '
                             'cannot read back')
        finally:
            fresh.deleteLater()

    # ---- 39, 40. what the scheduler actually runs -----------------------------

    def test_39_every_registered_action_leaves_the_files_it_claims(self):
        """A nightly task is judged by the files on disk, not by a return code.

        Automation and Batch hand one `output_dir` to every verb and never a file name, so
        the naming rule lives in the backend (`target_path`). Every action the registry is
        built from is called here the way the task runner calls it, and everything the
        verdict claims is read back off the disk: the file has to exist, sit in the folder
        that was named, not be the file that was read, and hold the number of points or
        faces the verdict says it holds.
        """
        processor = PointCloudProcessor()
        out = os.path.join(self.case, 'out')
        os.makedirs(out)
        inputs = {os.path.normcase(self.scan), os.path.normcase(self.target)}
        actions = processor.automation_actions()
        # The verb is the table's first column, not the tail of the action id: `pcd.filter_
        # statistical` is the verb `outliers_statistical`, and the ids are what the task pane
        # shows while the verbs are what the backend, the verdict and this suite name.
        verbs = {action_id: verb for verb, action_id, _, _, _ in
                 PointCloudProcessor.AUTOMATION_TABLE}
        self.assertEqual(len(actions), len(PointCloudProcessor.AUTOMATION_TABLE),
                         'the launcher list and the table are no longer the same size')
        self.assertEqual({action_id for action_id, *_ in actions}, set(verbs),
                         'the registry is handed an id the table does not declare')
        self.assertEqual(set(AUTOMATION_ARGS) - set(verbs.values()), set(),
                         'a task parameter names a verb that does not exist')
        for action_id, launcher, description, spec, batch in actions:
            verb = verbs[action_id]
            with self.subTest(action=action_id):
                self.assertTrue(description, f'{action_id} is offered with no description')
                args = {}
                for name in spec:
                    if name == 'target_path' and 'source_path' in spec:
                        args[name] = self.target
                    elif name in ('file_path', 'source_path'):
                        args[name] = self.scan
                    elif name == 'output_dir':
                        args[name] = out
                args.update(AUTOMATION_ARGS.get(verb, {}))
                verdict = launcher(**args)
                self.assertTrue(verdict['success'],
                                f'{action_id} refused a healthy cloud: {verdict["error"]}')
                self.assertEqual(verdict['operation'], verb,
                                 f'{action_id} reported a verdict for {verdict["operation"]}')
                files = verdict['files']
                self.assertEqual(len(files), VERB_OUTPUT_FILES[verb],
                                 f'{action_id} claimed {len(files)} files and this verb '
                                 f'writes {VERB_OUTPUT_FILES[verb]}')
                for path in files:
                    self.assertTrue(os.path.isfile(path),
                                    f'{action_id} reported {path}, which is not on disk')
                    self.assertNotIn(os.path.normcase(path), inputs,
                                     f'{action_id} wrote over the file it read')
                    if 'output_dir' in spec:
                        self.assertEqual(os.path.normcase(os.path.dirname(path)),
                                         os.path.normcase(out),
                                         f'{action_id} wrote outside the folder the task named')
                if verb in PointCloudProcessor.SURFACE_VERBS:
                    vertices, faces = mesh_counts(files[0])
                    self.assertGreater(faces, 0, f'{action_id} wrote a surface with no faces')
                    self.assertEqual((vertices, faces),
                                     (verdict['measure']['vertices'],
                                      verdict['measure']['faces']),
                                     f'{action_id} reported a mesh the file does not match')
                elif files:
                    counted = sum(cloud_count(path) for path in files)
                    self.assertEqual(counted, verdict['points_after'],
                                     f'{action_id} reported {verdict["points_after"]} points; '
                                     f'the files hold {counted}')

        del_before = self.files()
        unnamed = processor.automation_action('center', 'cloud')()
        self.assertFalse(unnamed['success'], 'a task with no file still reported a run')
        self.assertIn('no file was named', unnamed['error'])
        ghost = os.path.join(self.case, 'never-made')
        missing_folder = processor.automation_action('center', 'cloud')(
            file_path=self.scan, output_dir=ghost)
        self.assertFalse(missing_folder['success'], 'a task into a folder that is not there ran')
        self.assertIn('not a folder', missing_folder['error'])
        self.assertFalse(os.path.exists(ghost), 'the run made the folder it refused over')
        self.assertEqual(self.files(), del_before, 'a refused task still left a file')

    def test_40_one_folder_of_scans_survives_a_task_run_over_it(self):
        """The name a task gives its output must never be the name of its input.

        `pcd.center` over `D:\\scans` used to answer `scan.ply` for `scan.ply`: the scheduled
        run replaced the scan, and two verbs in one folder overwrote each other whatever the
        order they ran in. The file here is deliberately named `site.1.ply` - a dot that is
        not the extension, which is what a `path.replace('.', '_x.')` name rebuilt into a
        folder that does not exist.
        """
        folder = os.path.join(self.case, 'nightly')
        os.makedirs(folder)
        scan = os.path.join(folder, 'site.1.ply')
        shutil.copyfile(self.source, scan)
        with open(scan, 'rb') as handle:
            original = handle.read()
        processor = PointCloudProcessor()
        names = []
        for verb, shape, extra in (('center', 'cloud', {}),
                                   ('normalize', 'cloud', {}),
                                   ('voxel', 'cloud', {'voxel_size': 0.01}),
                                   ('planes', 'split', {}),
                                   ('export', 'export', {'extension': '.ply'}),
                                   ('hull', 'surface', {})):
            verdict = processor.automation_action(verb, shape)(
                file_path=scan, output_dir=folder, **extra)
            self.assertTrue(verdict['success'], f'{verb} refused: {verdict["error"]}')
            names.extend(os.path.basename(path) for path in verdict['files'])
        self.assertEqual(len(set(names)), len(names),
                         f'two verbs wrote the same file: {sorted(names)}')
        self.assertNotIn('site.1.ply', names, 'a verb named its output after the file it read')
        with open(scan, 'rb') as handle:
            self.assertEqual(handle.read(), original,
                             'the task rewrote the scan it was given')
        self.assertEqual(sorted(names), sorted(n for n in os.listdir(folder)
                                               if n != 'site.1.ply'),
                         'files are in the folder that no verdict reported')


if __name__ == '__main__':
    unittest.main(verbosity=2)
