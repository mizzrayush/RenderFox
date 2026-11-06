"""Quality pane contract test.

The Quality tab is one of the app's two "tell me what is wrong with this model and fix
it" routes, and until this pass it could not do either half of that sentence:

  - the analysis thread was a `SafeWorker` subclass that emitted an `error` signal
    nothing ever raised into (`SafeWorker.run` emits `error_occurred`), so a model that
    could not be read left the progress bar spinning and the Analyze button disabled
    forever - and `finished` shadowed `QThread.finished`, the signal Qt itself emits;
  - `analyze_quality` catches its own failures and returns `{'error': ..., 'score': 0}`,
    which the pane painted as a grade of F for a model it had never opened;
  - the Fix list promised one click on `generate_lods` and could not do it, could not
    reach `fix_normals`, `generate_uvs` or `pack_uvs` although all four have real
    backends, and reported "not supported automatically yet" - a sentence about the
    pane, not about the app;
  - Fix All marked *every* row "(Applied)" after one auto-repair, so a UV suggestion
    looked done because a hole got closed;
  - Export Quality Report called `export_quality_report(analysis, path, model_path)`
    against a two-parameter function that wants `{path: analysis}` - a TypeError every
    single time, swallowed by the `except` that only logged. Repaired, the call reached
    the template and raised a second time: it ended in `.format(len(results))` over a
    block full of CSS braces, so it died on `KeyError: ' font-family'` before writing a
    line. The report had never existed, on any machine, since the button was added;
  - both Fix paths handed closures to the house `Worker`, which always injects
    `progress_callback`, and connected only `signals.result`, so the defect surfaced as
    a spinning bar rather than an error.

A mid-pass claim about PyMeshLab and doubled vertex lines did not survive re-measurement
and is not shipped - see `Test31RepeatedVertexLines`, which pins what the engine actually
answers instead. What the re-run did find is in `MeshUV.read_unprocessed`: the UV counter
and the UV stripper asked a `Scene` for `mesh.visual`, so every file with more than one
material was reported as having no texture coordinates at all.

This suite drives the real pane on offscreen Qt over real files, and requires each fix
name to leave a file on disk, name the pane that owns the ones it does not, or refuse
with the reason. Nothing here is asserted about a rendered image: no renderer runs on
this machine.

Run: python -X utf8 tests/test_quality_analyzer_contract.py
"""

import ast
import inspect
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import trimesh
from PyQt6.QtWidgets import QApplication, QMessageBox

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.features import quality_analyzer as QA_MODULE
from src.features.quality_analyzer import QualityAnalyzer
from src.processing import mesh_processor as MP
from src.processing.mesh_processor import MeshProcessor, MeshRepairer, MeshUV
from src.ui import quality_analyzer_ui as PANE
from src.ui.quality_analyzer_ui import (QualityAnalyzerUI, apply_fix_action,
                                        fix_output_path)

APP = QApplication.instance() or QApplication(sys.argv)

PANE_SOURCE = open(os.path.join(ROOT, 'src', 'ui', 'quality_analyzer_ui.py'),
                   encoding='utf-8').read()
ANALYZER_SOURCE = open(os.path.join(ROOT, 'src', 'features', 'quality_analyzer.py'),
                       encoding='utf-8').read()

PROCESSOR = MeshProcessor()
ANALYZER = QualityAnalyzer()


class RecordingDialogs:
    """Modal dialogs become data, so a refusal can be asserted instead of clicked away."""

    # The pane asks "Load the fixed model?" after every successful fix. Declining it by
    # default keeps one click equal to one assertion; test_31 turns it back on.
    DEFAULT_ANSWERS = {'Reload Model': QMessageBox.StandardButton.No}

    def __init__(self):
        self.messages = []
        self.answers = dict(self.DEFAULT_ANSWERS)
        self.install()

    def reset(self):
        del self.messages[:]
        self.answers = dict(self.DEFAULT_ANSWERS)

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

        def ask(parent, title, text, *args, **kwargs):
            recorder.messages.append(('question', title, str(text)))
            return recorder.answers.get(title, QMessageBox.StandardButton.Yes)

        QMessageBox.question = ask
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok

    def texts(self):
        return ' | '.join(text for _, _, text in self.messages)

    def titles(self):
        return [title for _, title, _ in self.messages]

    def last(self, kind):
        for entry in reversed(self.messages):
            if entry[0] == kind:
                return entry[2]
        return ''


DIALOGS = RecordingDialogs()


def bad_mesh(folder, name='flawed.obj'):
    """A real .obj: a cube missing one face, a doubled vertex, and a zero-area triangle.

    Built by hand rather than from trimesh primitives so the flaws are in the file the
    analyzer reads, not only in memory it was asked about. `trimesh.load` welds the two
    duplicate corners while it reads, which is why no test below depends on the
    duplicate-vertex row - the file still carries them, and the write paths prove it.
    """
    vertices = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
                [1, 0, 0], [0, 0, 0]]          # 8 (a doubled corner and a doubled origin)
    faces = [[0, 2, 1], [0, 3, 2],            # bottom, both triangles
             [4, 5, 6], [4, 6, 7],            # top
             [0, 1, 5], [0, 5, 4],            # front
             [2, 3, 7], [2, 7, 6],            # back
             [1, 2, 6],                       # right, one triangle of the two missing
             [0, 0, 1]]                       # zero-area: the same vertex twice
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(''.join(f'v {x} {y} {z}\n' for x, y, z in vertices))
        handle.write(''.join(f'f {a + 1} {b + 1} {c + 1}\n' for a, b, c in faces))
    return path


def cube_with_uvs(folder, name='textured.obj'):
    """A closed, well-formed cube - the mesh every one-click verb is expected to survive."""
    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    path = os.path.join(folder, name)
    mesh.export(path)
    return path


def read_rows(list_widget):
    """[(fix_action, row text)] for the rows a real analysis put in the widget."""
    out = []
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        suggestion = item.data(PANE.Qt.ItemDataRole.UserRole) or {}
        out.append((suggestion.get('fix_action'), item.text()))
    return out


class Test1FixVocabulary(unittest.TestCase):
    """The analyzer owns the fix names; the pane cannot promise one it cannot do."""

    def setUp(self):
        self.analyzer = QualityAnalyzer()

    def test_01_every_fix_name_an_issue_can_carry_has_a_destination(self):
        emitted = set()
        for match in re.finditer(r"'fix':\s*'([a-z_]+)'", ANALYZER_SOURCE):
            emitted.add(match.group(1))
        self.assertTrue(emitted, 'the analyzer emits no fix names at all - the pane is dead')
        unaccounted = sorted(emitted - set(QualityAnalyzer.ONE_CLICK_FIXES)
                             - set(QualityAnalyzer.OWNED_ELSEWHERE))
        self.assertEqual([], unaccounted,
                         'a check offers a fix the pane neither applies nor routes')

    def test_02_every_described_fix_is_one_an_issue_actually_offers(self):
        emitted = {m.group(1) for m in
                   re.finditer(r"'fix':\s*'([a-z_]+)'", ANALYZER_SOURCE)}
        described = set(self.analyzer.issue_fixes)
        self.assertEqual(sorted(emitted), sorted(described),
                         'the description list and the issue list disagree about the '
                         'vocabulary; a name in only one of them is a dead claim')

    def test_03_one_click_is_the_shared_tuple_not_a_second_list(self):
        for name in QualityAnalyzer.ONE_CLICK_FIXES:
            self.assertIn(name, self.analyzer.issue_fixes, name)
        suggestions = self.analyzer._generate_suggestions([
            {'type': 'polygon_count', 'severity': 'high', 'fix': 'generate_lods'},
            {'type': 'missing_uvs', 'severity': 'high', 'fix': 'generate_uvs'}])
        by_action = {s['fix_action']: s for s in suggestions}
        self.assertTrue(by_action['generate_uvs']['one_click'])
        self.assertFalse(by_action['generate_lods']['one_click'])
        self.assertIn('Pre-Processing', by_action['generate_lods']['other_pane'])

    def test_04_a_fix_with_no_verb_says_which_pane_has_it(self):
        for name, sentence in QualityAnalyzer.OWNED_ELSEWHERE.items():
            self.assertIn('Pre-Processing', sentence, name)
        self.assertEqual({'generate_lods', 'resize_texture'},
                         set(QualityAnalyzer.OWNED_ELSEWHERE),
                         'a routed-away fix name was added without its pane being named')

    def test_05_an_empty_scene_reports_rows_the_pane_can_render(self):
        """The scene branch used to hand the pane two lists of bare strings."""
        real_load = trimesh.load
        trimesh.load = lambda *a, **kw: trimesh.Scene()
        try:
            result = self.analyzer.analyze_quality('whatever.glb')
        finally:
            trimesh.load = real_load
        for row in result['issues']:
            self.assertIsInstance(row, dict, f'pane calls issue.get() on {row!r}')
            self.assertIn('type', row)
            self.assertIn('message', row)
        for row in result['suggestions']:
            self.assertIsInstance(row, dict)
            self.assertNotIn('fix_action', row,
                             'advice with no verb must not look like a double-clickable fix')
            self.assertFalse(row['one_click'])

    def test_06_a_model_that_cannot_be_read_is_an_error_not_a_grade(self):
        result = self.analyzer.analyze_quality(os.path.join(tempfile.gettempdir(),
                                                            'rf-never-written.obj'))
        self.assertIn('error', result)
        self.assertEqual(0, result['score'],
                         'the pane must be able to tell this from a model that scored 0')


class Test2FixBackends(unittest.TestCase):
    """Every name the pane can double-click reaches a backend and writes a file."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix='rf-quality-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_07_the_dispatch_table_covers_exactly_the_promised_names(self):
        self.assertEqual(set(PANE.FIX_VERBS), set(QualityAnalyzer.ONE_CLICK_FIXES),
                         'the pane and the analyzer disagree about what one click does')

    def test_08_each_one_click_fix_writes_a_file_the_app_can_read_back(self):
        """A fix is not done when bytes exist: the app's own analyzer has to score them.

        Measured before this pass, on this machine, with pymeshlab 2025.7: hand it a file
        that lists the same position twice and its filters wrote out-of-range face indices
        (the analyzer answered `index ... is out of bounds for axis 0`) or killed the
        process with 0xc0000005. Both fixtures are run through every verb here so neither
        answer can come back as a success.
        """
        fixtures = [('clean cube', cube_with_uvs(self.folder)),
                    ('repeated vertex lines', bad_mesh(self.folder, 'flawed.obj'))]
        for label, source in fixtures:
            for name in QualityAnalyzer.ONE_CLICK_FIXES:
                with self.subTest(fixture=label, fix=name):
                    target = fix_output_path(source, name).replace(
                        '.obj', f'_{label.split()[0]}.obj')
                    result = apply_fix_action(PROCESSOR, source, name, target)
                    self.assertTrue(result['success'], f"{name}: {result.get('error')}")
                    self.assertTrue(os.path.isfile(result['output_path']), name)
                    self.assertGreater(os.path.getsize(result['output_path']), 0, name)
                    reread = ANALYZER.analyze_quality(result['output_path'], 'film_vfx')
                    self.assertNotIn('error', reread,
                                     f'{name} wrote a file the app cannot read: '
                                     f'{reread.get("error")}')
                    self.assertGreater(reread['score'], 0, name)

    def test_09_the_two_uv_verbs_write_texture_coordinates_and_say_how_many(self):
        source = cube_with_uvs(self.folder, 'for_uv.obj')
        self.assertEqual(0, MeshUV.uv_rows(source), 'the fixture already has UVs')
        expected = {'generate_uvs': 'Basic', 'pack_uvs': 'Space-optimizing'}
        for name in ('generate_uvs', 'pack_uvs'):
            with self.subTest(fix=name):
                result = apply_fix_action(PROCESSOR, source, name)
                self.assertTrue(result['success'], result.get('error'))
                self.assertGreater(result['uv_rows_written'], 0, name)
                self.assertEqual(expected[name], result['layout'],
                                 'the pane ran a different layout than its row names')

    def test_10_pack_uvs_brings_an_out_of_range_atlas_back_inside(self):
        """`pack_uvs` is offered for UV vertices outside [0, 1]; that is the claim here."""
        mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        uv = np.array([[0.0, 0.0], [4.0, 0.0], [0.0, 4.0], [4.0, 4.0],
                       [2.0, 2.0], [3.0, 1.0]], dtype=np.float32)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv)
        source = os.path.join(self.folder, 'out_of_range.obj')
        mesh.export(source)
        result = apply_fix_action(PROCESSOR, source, 'pack_uvs')
        self.assertTrue(result['success'], result.get('error'))
        written = trimesh.load(result['output_path'], process=False)
        extent = written.visual.uv
        self.assertGreater(len(extent), 0)
        self.assertGreaterEqual(float(extent.min()), -1e-6,
                                'the atlas this writes still starts below zero')
        self.assertLessEqual(float(extent.max()), 1.0 + 1e-6,
                             'the coordinates a pack was asked for are still outside 0-1')

    def test_11_a_routed_fix_writes_nothing_and_names_the_pane(self):
        source = cube_with_uvs(self.folder, 'routed.obj')
        for name, sentence in QualityAnalyzer.OWNED_ELSEWHERE.items():
            with self.subTest(fix=name):
                result = apply_fix_action(PROCESSOR, source, name)
                self.assertFalse(result['success'])
                self.assertEqual(sentence, result['error'])
                self.assertFalse(os.path.exists(fix_output_path(source, name)))

    def test_12_a_name_no_backend_has_is_refused_by_that_name(self):
        source = cube_with_uvs(self.folder, 'unknown.obj')
        result = apply_fix_action(PROCESSOR, source, 'teleport_vertices')
        self.assertFalse(result['success'])
        self.assertIn('teleport_vertices', result['error'])
        self.assertIn('no backend', result['error'])

    def test_13_the_output_file_keeps_the_folder_that_contains_a_dot(self):
        """`split('.')` used to treat the extension as the last dot in the whole path."""
        folder = os.path.join(self.folder, 'models.v2')
        os.makedirs(folder, exist_ok=True)
        source = os.path.join(folder, 'cube.obj')
        cube_with_uvs(folder, 'cube.obj')
        self.assertEqual(os.path.join(folder, 'cube_remesh.obj'),
                         fix_output_path(source, 'remesh'))
        self.assertEqual(os.path.join(folder, 'cube_fixed_all.obj'),
                         fix_output_path(source, 'fixed_all'))

    def test_14_the_confirmation_sentence_names_every_filter_auto_repair_runs(self):
        body = inspect.getsource(MeshRepairer.auto_repair)
        filters = [name for name in
                   re.findall(r"apply_filter\('([a-z_]+)'", body)]
        self.assertGreater(len(filters), 1, 'the engine stopped using filters')
        words = {
            'meshing_remove_duplicate_vertices': 'weld duplicate vertices',
            'meshing_remove_null_faces': 'null',
            'meshing_remove_folded_faces': 'folded',
            'meshing_remove_duplicate_faces': 'duplicate faces',
            'meshing_re_orient_faces_coherently': 're-orient faces coherently',
            'meshing_close_holes': 'close holes',
            'meshing_remove_unreferenced_vertices': 'drop unreferenced vertices',
        }
        self.assertEqual(sorted(filters), sorted(words),
                         'auto_repair changed its filters; the pane\'s sentence and this '
                         'test are the two places that have to hear about it')
        for name in filters:
            self.assertIn(words[name], PANE.FIX_ALL_ASK, name)


class Test3QualityPane(unittest.TestCase):
    """The pane, driven the way a user drives it: set a model, click, wait, read."""

    def setUp(self):
        DIALOGS.reset()
        self.folder = tempfile.mkdtemp(prefix='rf-quality-pane-')
        self.tab = QualityAnalyzerUI()
        # Film/VFX is the platform whose standard asks for a watertight mesh, which is
        # what puts a repair_mesh row in the list for the flawed fixture.
        self.tab.platform_combo.setCurrentText('Film/VFX')
        self.tab.set_model(bad_mesh(self.folder))

    def tearDown(self):
        """Timers and threads first: a widget destroyed with a live worker is how a
        green suite exits 127 instead of 0."""
        self.tab.threadpool.waitForDone(15000)
        if getattr(self.tab, 'worker', None) is not None and self.tab.worker.isRunning():
            self.tab.worker.wait(15000)
        APP.processEvents()
        self.tab.close()
        APP.processEvents()
        shutil.rmtree(self.folder, ignore_errors=True)

    def analyze(self, seconds=60.0):
        end = time.time() + seconds
        self.tab.analyze_current_model()
        while time.time() < end:
            APP.processEvents()
            if self.tab.analysis_result is not None:
                return
            time.sleep(0.02)
        self.fail('the analysis never came back')

    def row_for(self, fix_action):
        for i in range(self.tab.suggestions_list.count()):
            item = self.tab.suggestions_list.item(i)
            suggestion = item.data(PANE.Qt.ItemDataRole.UserRole)
            if suggestion and suggestion.get('fix_action') == fix_action:
                return item
        return None

    def settle(self, seconds=90.0):
        end = time.time() + seconds
        self.tab.threadpool.waitForDone(int(seconds * 1000))
        while time.time() < end:
            APP.processEvents()
            if self.tab.progress_bar.isHidden():
                return
            time.sleep(0.02)
        APP.processEvents()

    def test_15_a_real_model_produces_the_issues_and_rows_it_claims(self):
        self.analyze()
        result = self.tab.analysis_result
        self.assertEqual('film_vfx', result['target_platform'])
        self.assertGreaterEqual(result['score'], 0)
        self.assertTrue(self.tab.issues_list.count(), 'no issue rows for a flawed mesh')
        actions = {a for a, _ in read_rows(self.tab.suggestions_list)}
        self.assertIn('repair_mesh', actions)
        self.assertIn('generate_uvs', actions)
        self.assertTrue(self.tab.fix_all_btn.isEnabled(),
                        'suggestions exist but Fix All is still disabled')
        self.assertTrue(self.tab.export_btn.isEnabled())
        self.assertTrue(self.tab.progress_bar.isHidden())

    def test_16_the_promise_is_carried_out_the_moment_the_row_is_double_clicked(self):
        self.analyze()
        item = self.row_for('remove_degenerate_faces')
        self.assertIsNotNone(item, 'the flawed mesh stopped offering remove_degenerate_faces')
        before = len(DIALOGS.messages)
        self.tab.apply_fix(item)
        self.assertFalse(self.tab.progress_bar.isHidden(),
                         'a fix that is running must show it')
        self.settle()
        written = fix_output_path(self.tab.current_model_path, 'remove_degenerate_faces')
        self.assertTrue(os.path.isfile(written), f'{written} was never written')
        self.assertIn('(Applied)', item.text())
        self.assertGreater(len(DIALOGS.messages), before, 'the fix finished silently')
        self.assertIn('remove_degenerate_faces', DIALOGS.last('information'))

    def test_17_fix_all_marks_only_the_rows_auto_repair_carried_out(self):
        self.analyze()
        actions = [a for a, _ in read_rows(self.tab.suggestions_list)]
        covered = [a for a in actions if a in QualityAnalyzer.FIX_ALL_COVERS]
        uncovered = [a for a in actions if a not in QualityAnalyzer.FIX_ALL_COVERS]
        self.assertTrue(covered and uncovered,
                        f'the fixture needs rows on both sides, got {actions}')

        self.tab.fix_all_issues()
        self.settle()

        written = fix_output_path(self.tab.current_model_path, 'fixed_all')
        self.assertTrue(os.path.isfile(written), 'Fix All did not write its file')
        for action in covered:
            self.assertIn('(Applied)', self.row_for(action).text(), action)
        for action in uncovered:
            self.assertNotIn('(Applied)', self.row_for(action).text(),
                             f'{action} was not part of auto_repair but is marked done')
        self.assertIn('Saved to', DIALOGS.last('information'))

    def test_18_the_engine_reports_what_it_removed_and_the_pane_shows_it(self):
        """`auto_repair` returns its own sentences; a pane that hides them says less
        than the backend knows. Both runs read the same file, so the two lists have to
        be the same words."""
        source = self.tab.current_model_path
        expected = PROCESSOR.repair(source, os.path.join(self.folder, 'engine.obj'),
                                    operation='auto')
        self.assertTrue(expected['success'], expected.get('error'))
        self.assertTrue(expected['operations'], 'the engine reported nothing it did')

        self.analyze()
        self.tab.fix_all_issues()
        self.settle()

        shown = DIALOGS.last('information')
        for sentence in expected['operations']:
            self.assertIn(sentence, shown, 'the pane dropped an operation the engine named')

    def test_19_a_fix_thread_that_dies_says_so_and_stops_the_bar(self):
        self.analyze()
        item = self.row_for('repair_mesh')
        boom = self.tab.processor

        class Exploding:
            def repair(self, *a, **kw):
                raise RuntimeError('the repairer fell over')

        self.tab.processor = Exploding()
        try:
            self.tab.apply_fix(item)
        finally:
            self.tab.processor = boom
        self.settle()
        self.assertTrue(self.tab.progress_bar.isHidden(),
                        'the fix died and the bar is still spinning')
        self.assertIn('The fix stopped before it wrote anything: RuntimeError: '
                      'the repairer fell over', DIALOGS.last('warning'))

    def test_20_a_row_that_is_advice_starts_no_thread(self):
        self.tab.set_model(bad_mesh(self.folder, 'advice.obj'))
        self.tab.suggestions_list.clear()
        item = PANE.QListWidgetItem('Manual check\n   → Check export settings')
        item.setData(PANE.Qt.ItemDataRole.UserRole,
                     {'description': 'Check model export settings', 'one_click': False})
        self.tab.suggestions_list.addItem(item)
        self.tab.apply_fix(item)
        self.assertTrue(self.tab.progress_bar.isHidden())
        self.assertIn('Check model export settings', DIALOGS.last('warning'))

    def test_21_the_analysis_thread_failure_channel_is_the_one_that_fires(self):
        original = PANE.QualityAnalyzer

        class Dead:
            def __init__(self, *a, **kw):
                pass

            def analyze_quality(self, model_path, target_platform=None):
                raise RuntimeError('the analyzer fell over')

        PANE.QualityAnalyzer = Dead
        try:
            self.tab.analyze_current_model()
            end = time.time() + 30
            while time.time() < end and self.tab.score_label.text() != 'Error':
                APP.processEvents()
                time.sleep(0.02)
        finally:
            PANE.QualityAnalyzer = original
        self.assertEqual('Error', self.tab.score_label.text(),
                         'error_occurred is not connected: the bar spins forever')
        self.assertIn('the analyzer fell over', self.tab.grade_label.text())
        self.assertTrue(self.tab.progress_bar.isHidden())
        self.assertTrue(self.tab.analyze_btn.isEnabled())

    def test_22_a_model_that_cannot_be_opened_is_not_graded(self):
        self.tab.set_model(os.path.join(self.folder, 'nothing.obj'))
        self.tab.analyze_current_model()
        end = time.time() + 30
        while time.time() < end and self.tab.score_label.text() != 'Error':
            APP.processEvents()
            time.sleep(0.02)
        self.assertEqual('Error', self.tab.score_label.text(),
                         'a file the app never read cannot be scored 0 and graded F')
        self.assertTrue(self.tab.analyze_btn.isEnabled())
        self.assertIsNone(self.tab.analysis_result)

    def test_23_no_subclass_signal_shadows_a_qthread_builtin(self):
        for name in ('finished', 'started', 'errored', 'quit'):
            self.assertNotIn(name, vars(PANE.QualityAnalysisWorker),
                             f'{name} is QThread\'s own signal; shadowing it hides Qt\'s')
        self.assertIn('error_occurred.connect', PANE_SOURCE)
        self.assertIn('analysis_done.connect', PANE_SOURCE)

    def test_24_every_function_handed_to_the_house_worker_takes_progress_callback(self):
        """`Worker.__init__` always injects the kwarg; a closure without it raises on
        the way in, which is how both Fix buttons were dead."""
        tree = ast.parse(PANE_SOURCE)
        passed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'Worker':
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Name):
                    passed.add(first.id)
        self.assertTrue(passed, 'the pane stopped using the house worker - re-read it')
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in passed:
                names = [a.arg for a in node.args.args]
                self.assertIn('progress_callback', names,
                              f'{node.name} would be called with an unexpected keyword')

    def test_25_every_worker_start_has_an_error_channel_attached(self):
        starts = PANE_SOURCE.count('self.threadpool.start(worker)')
        hooked = PANE_SOURCE.count('worker.signals.error.connect(self.on_fix_failed)')
        self.assertGreater(starts, 0)
        self.assertEqual(starts, hooked,
                         'a worker whose error channel is unconnected fails as a '
                         'progress bar that never stops')

    def test_26_export_writes_the_report_the_button_names(self):
        self.analyze()
        self.tab.export_report()
        expected = os.path.join(self.folder, 'flawed.quality_report.html')
        self.assertTrue(os.path.isfile(expected),
                        'Export used to raise TypeError and log it, writing nothing')
        with open(expected, encoding='utf-8') as handle:
            html = handle.read()
        self.assertIn('flawed.obj', html)
        self.assertIn(f"Quality Score: {self.tab.analysis_result['score']}/100", html)
        self.assertIn('Total models analyzed: 1', html)
        # The header count used to be made with `.format` over a template whose style
        # block is all braces, so the first rule read as a field name and the call
        # raised before anything was written. The style surviving is the proof it did not.
        self.assertIn('font-family: Arial', html, 'the report lost its own style block')
        self.assertIn('zero area', html.replace('-', ' '),
                      'the report left the issues the pane just listed out of it')
        self.assertNotIn('\U0001f3af', html, 'the report still carries the emoji header')
        self.assertIn('Report Exported', DIALOGS.titles())

    def test_27_export_without_an_analysis_writes_nothing(self):
        self.tab.export_report()
        self.assertEqual([], [f for f in os.listdir(self.folder)
                              if f.endswith('.quality_report.html')])

    def test_28_the_comparison_labels_report_a_model_that_could_not_be_read(self):
        """`update_info` used to index `result['metrics']`, KeyError on a failed file."""
        painted = []

        class Sink:
            def setText(self, text):
                painted.append(text)

        for analysis in ({'error': 'no such file', 'score': 0},
                         {'metrics': {'polygon_count': 12, 'vertex_count': 8,
                                      'is_watertight': True, 'volume': 1.0}}):
            # `self` is inert here: update_info touches only the label it is handed.
            PANE.ComparisonDialog.update_info(object(), Sink(), analysis)
        self.assertIn('Could not be analyzed: no such file', painted[0])
        self.assertIn('12', painted[1])
        self.assertIn('Yes', painted[1])

    def test_31_accepting_the_reload_moves_the_pane_onto_the_file_the_fix_wrote(self):
        """The other half of the fix: a user who says Yes is now looking at that file."""
        DIALOGS.answers['Reload Model'] = QMessageBox.StandardButton.Yes
        self.analyze()
        item = self.row_for('remove_degenerate_faces')
        source = self.tab.current_model_path
        written = fix_output_path(source, 'remove_degenerate_faces')
        self.tab.apply_fix(item)
        self.settle()
        self.assertTrue(os.path.isfile(written), f'{written} was never written')
        self.assertEqual(written, self.tab.current_model_path,
                         'the pane said it reloaded and stayed on the old file')
        end = time.time() + 60
        while time.time() < end and self.tab.analysis_result is None:
            APP.processEvents()
            time.sleep(0.02)
        self.assertIsNotNone(self.tab.analysis_result, 'the reloaded model was never scored')
        self.assertNotEqual(source, self.tab.analysis_result.get('model_path'),
                            'the new score is still the old file\'s')

    def test_37_fix_all_moves_the_pane_onto_the_file_it_repaired(self):
        """The second reload prompt, the one Fix All asks with, is the same promise."""
        DIALOGS.answers['Reload Model'] = QMessageBox.StandardButton.Yes
        self.analyze()
        source = self.tab.current_model_path
        written = fix_output_path(source, 'fixed_all')
        self.tab.fix_all_issues()
        self.settle()
        self.assertTrue(os.path.isfile(written), f'{written} was never written')
        self.assertEqual(written, self.tab.current_model_path,
                         'Fix All said it reloaded and stayed on the old file')
        end = time.time() + 60
        while time.time() < end and (self.tab.analysis_result is None
                                     or self.tab.analysis_result.get('model_path')
                                     == source):
            APP.processEvents()
            time.sleep(0.02)
        self.assertEqual(written, self.tab.analysis_result.get('model_path'),
                         'the score on screen is still the old file\'s')

    def test_38_an_issue_row_that_is_a_bare_sentence_is_still_painted(self):
        """`issues` is a list of dicts; a producer that hands back a sentence is wrong.

        The painter runs inside a Qt slot, so an AttributeError there is printed to a
        console nobody watches and the rest of the list never appears - the pane looks
        like a model with fewer problems than it has.
        """
        analysis = {'score': 40, 'grade': 'D', 'model_path': self.tab.current_model_path,
                    'issues': ['Empty scene (no geometry found)',
                               {'severity': 'critical', 'type': 'non_manifold_edges',
                                'message': '3 edges bound one face'}],
                    'suggestions': [], 'metrics': {}, 'standards_compliance': {}}
        for key in ('polygon_score', 'geometry_score', 'uv_score', 'topology_score',
                    'texture_score', 'performance_score'):
            analysis[key] = 1
        self.tab.on_analysis_complete(analysis)
        self.assertEqual(2, self.tab.issues_list.count(),
                         'the row after the bare sentence was never painted')
        self.assertIn('Empty scene', self.tab.issues_list.item(0).text())
        self.assertIn('Non Manifold Edges', self.tab.issues_list.item(1).text())


class Test29NoSecondRoute(unittest.TestCase):
    """One operation router: the pane must not re-implement what MeshProcessor does."""

    def test_29_the_pane_reaches_the_processor_and_meshuv_and_nothing_else(self):
        for verb in PANE.FIX_VERBS.values():
            self.assertIn(verb[0], ('repair', 'remesh', 'uv'), str(verb))
        # A comment may mention a library; an import is a pane doing geometry itself.
        tree = ast.parse(PANE_SOURCE)
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split('.')[0])
        borrowed = roots & {'pymeshlab', 'trimesh', 'numpy', 'open3d'}
        self.assertEqual(set(), borrowed,
                         'a pane that imports a geometry library is a second backend')
        self.assertNotIn('apply_filter', PANE_SOURCE,
                         'the filter names belong to MeshProcessor, which answers for them')
        # Every verb but 'uv' must be a real method on MeshProcessor.
        for method, kwargs in PANE.FIX_VERBS.values():
            if method == 'uv':
                continue
            self.assertTrue(callable(getattr(PROCESSOR, method)), method)
            if 'operation' in kwargs:
                signature = inspect.signature(getattr(PROCESSOR, method))
                self.assertIn('operation', signature.parameters)


class Test30VerbTable(unittest.TestCase):
    """A wrong operation name is invisible in a success box, so the call is recorded."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix='rf-quality-verbs-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_30_each_fix_name_calls_the_verb_and_the_knobs_it_claims(self):
        expected = {
            'repair_mesh': ('repair', {'operation': 'auto'}),
            'merge_vertices': ('repair', {'operation': 'remove_duplicates'}),
            'remove_degenerate_faces': ('repair', {'operation': 'remove_degenerate'}),
            'fix_normals': ('repair', {'operation': 'fix_normals'}),
            'remesh': ('remesh', {'method': 'uniform'}),
            'generate_uvs': ('uv', {'method': 'trivial', 'layout': 'Basic'}),
            'pack_uvs': ('uv', {'method': 'trivial', 'layout': 'Space-optimizing'}),
        }
        self.assertEqual(sorted(expected), sorted(QualityAnalyzer.ONE_CLICK_FIXES),
                         "this table and the analyzer's promise have to be one list")

        calls = []

        class Recorder:
            def repair(self, mesh_path, output_path, **kwargs):
                calls.append(('repair', kwargs))
                return {'success': True, 'output_path': output_path}

            def remesh(self, mesh_path, output_path, **kwargs):
                calls.append(('remesh', kwargs))
                return {'success': True, 'output_path': output_path}

        source = os.path.join(self.folder, 'in.obj')
        original = MeshUV.parametrize
        MeshUV.parametrize = staticmethod(
            lambda mesh_path, output_path, **kwargs: (
                calls.append(('uv', kwargs)), {'success': True, 'output_path': output_path})[1])
        try:
            for name in sorted(expected):
                with self.subTest(fix=name):
                    calls.clear()
                    apply_fix_action(Recorder(), source, name)
                    self.assertEqual([expected[name]], calls, name)
        finally:
            MeshUV.parametrize = original



class Test31RepeatedVertexLines(unittest.TestCase):
    """What the engine actually does with a file that lists the same position twice.

    A mid-pass probe made this shape look dangerous, so it is pinned by reading the
    loader's own answer rather than by trusting what the probe seemed to show. Measured on
    pymeshlab 2025.7 here: the doubled file loads whole, its face indices stay inside the
    vertex array, and every repair verb writes a file this app can analyze again - which is
    why the app hands PyMeshLab the user's file directly and keeps no pre-writing pass.
    This class is what would notice if a future build started to need one.
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix='rf-repeat-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def dup_textured_obj(self, name='textured_dup.obj'):
        """An .obj that repeats two vertex lines *and* carries texture coordinates.

        It is the harsher of the two repeated-position files: a corner that has its own
        texture row cannot be merged away without the UV table, so the loader has to keep
        all ten positions to keep the mesh meaningful.
        """
        vertices = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1], [1, 0, 0], [0, 0, 0]]
        uvs = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.5], [0.2, 0.8]]
        faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (8, 5, 4), (9, 1, 5)]

        # v/vt only - a third field would name a normal this file does not have - and every
        # corner names a row that exists: a reference past the last `vt` line makes the
        # reader throw the whole texture table away, fixture included.
        def corner(i):
            return f'{i + 1}/{i % len(uvs) + 1}'

        path = os.path.join(self.folder, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(''.join('v {} {} {}\n'.format(*t) for t in vertices))
            handle.write(''.join('vt {} {}\n'.format(*t) for t in uvs))
            handle.write(''.join('f {} {} {}\n'.format(corner(a), corner(b), corner(c))
                                 for a, b, c in faces))
        return path

    @staticmethod
    def listed_positions(path):
        with open(path, 'rb') as handle:
            return sum(1 for line in handle if line[:2] == b'v ')

    def test_32_the_loader_reads_every_position_a_file_lists_and_keeps_the_indices_in_range(
            self):
        for path, listed in ((bad_mesh(self.folder, 'plain_repeat.obj'), 10),
                             (self.dup_textured_obj(), 10),
                             (cube_with_uvs(self.folder, 'no_repeat.obj'), 8)):
            ms = MP.pymeshlab.MeshSet()
            ms.load_new_mesh(path)
            mesh = ms.current_mesh()
            with self.subTest(source=os.path.basename(path)):
                self.assertEqual(listed, self.listed_positions(path))
                self.assertEqual(listed, mesh.vertex_number(),
                                 'the loader dropped positions it was handed')
                faces = np.array(mesh.face_matrix())
                self.assertLess(int(faces.max()), listed,
                                'a face names a row past the vertex array')

    def test_33_the_weld_reports_the_positions_it_joined(self):
        result = apply_fix_action(PROCESSOR, bad_mesh(self.folder, 'weld.obj'),
                                  'merge_vertices')
        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(2, result['removed'],
                         'the file doubles one corner and one origin')
        positions = np.round(np.array(MeshUV.read_unprocessed(result['output_path']).vertices,
                                      dtype=np.float64), 9)
        self.assertEqual(len(positions), len(np.unique(positions, axis=0)),
                         'the file the fix wrote still repeats positions')

    def test_34_a_textured_file_keeps_its_texture_coordinates_through_a_fix(self):
        """Welding must not be paid for with the UVs, which the earlier round trip did."""
        source = self.dup_textured_obj('textured_weld.obj')
        before = MeshUV.uv_rows(source)
        self.assertGreater(before, 0, 'the fixture lost its vt lines')

        for verb in ('merge_vertices', 'repair_mesh', 'remove_degenerate_faces'):
            result = apply_fix_action(PROCESSOR, source, verb)
            with self.subTest(verb=verb):
                self.assertTrue(result['success'], result.get('error'))
                self.assertGreater(MeshUV.uv_rows(result['output_path']), 0,
                                   'the fix wrote a mesh with no texture coordinates in it')
                analysis = ANALYZER.analyze_quality(result['output_path'], 'film_vfx')
                self.assertNotIn('error', analysis, analysis.get('error'))
                self.assertGreater(analysis['score'], 0)

    def two_material_obj(self, name='two_material.obj'):
        """A file the reader hands back as a *scene*: one OBJ, two `usemtl` groups.

        PyMeshLab writes a material sidecar beside every .obj it saves, and a file with
        more than one material is the shape that sidecar turns into a scene - which is the
        case `uv_rows` and `strip` used to answer about the wrapper instead of the mesh.
        """
        folder = os.path.join(self.folder, 'scene')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'm.mtl'), 'w', encoding='utf-8') as handle:
            handle.write('newmtl A\nKd 1 0 0\nnewmtl B\nKd 0 1 0\n')
        path = os.path.join(folder, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('mtllib m.mtl\n'
                         'v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\n'
                         'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvt 0.5 0.5\nvt 0 0.5\n'
                         'usemtl A\nf 1/1 2/2 3/3\nusemtl B\nf 4/4 5/5 6/6\n')
        return path

    def test_35_the_uv_verbs_answer_about_the_mesh_inside_a_scene_shaped_file(self):
        """Counting or stripping texture coordinates must reach past the wrapper."""
        path = self.two_material_obj()
        self.assertIsInstance(trimesh.load(path, process=False), trimesh.Scene,
                              'the premise of this test is a file the reader wraps')
        self.assertGreater(MeshUV.uv_rows(path), 0,
                           'a file full of texture coordinates was counted as having none')

        result = MeshUV.strip(path, os.path.join(self.folder, 'stripped.obj'))
        self.assertTrue(result['success'], result.get('error'))
        self.assertGreater(result['uv_rows_before'], 0)
        self.assertEqual(0, result['uv_rows_after'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
