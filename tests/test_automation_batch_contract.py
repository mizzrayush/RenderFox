"""Phase 6d contract: the Batch Operations pane runs a real batch, and says what it did.

What this suite exists to keep out of the app:

  * `start_batch_operation` read `self.batch_progress_value` and `self.batch_timer`,
    neither of which the file ever assigned, so every click after the source check died
    on AttributeError. Nothing in the app had ever run a batch.
  * The operation combo held nine names - Format Conversion, LOD Generation, Texture
    Optimization, Model Validation, Metadata Extraction, Thumbnail Generation, File
    Organization, Quality Analysis, Custom Script - and no action registered anywhere
    answered to any of them. The source combo held five sources, three of which the pane
    had no way to reach.
  * Pause, Stop and Preview were built and never connected to anything.
  * `BatchProcessor.process_batch` called an item a success whenever the callable
    returned without raising. Registry actions answer `{'success': False, 'error': ...}`
    instead of raising, so a batch in which every file failed reported every file done,
    and the pane printed "Batch operation completed!" over it.
  * The pane built its own private `BatchProcessor` and listened to that, while every
    run would have happened on the engine's - so progress could never have arrived.
  * `on_batch_progress` divided by `total` with no guard, and there is no pause or stop
    in the old processor at all.

Phase 6f added the operations a batch was actually missing - convert, simplify, repair,
weld, centre, scale, unwrap and thumbnail - and the rule that names the file each one
leaves behind. The tests below run them over real meshes on disk and read the answers
back out of the written files, because an action that reports a face count it asked for
rather than one it measured is exactly the bug this suite was written to catch.

Run: python -X utf8 tests/test_automation_batch_contract.py
"""

import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest

import trimesh

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from src.features import automation_engine as engine_module
from src.features.automation_engine import (
    ActionRegistry, AutomationEngine, BatchProcessor)
from src.ui.automation_tab import BACKUP_SUBFOLDER, AutomationTab

APP = QApplication.instance() or QApplication([])

# Every action the registry declares it can repeat over files, sorted as it offers them.
BATCH_IDS = ['file.copy', 'file.delete', 'file.move', 'file.thumbnail',
             'processing.center_pivot', 'processing.convert_format',
             'processing.generate_lod', 'processing.generate_uvs',
             'processing.normalize_size', 'processing.repair_mesh',
             'processing.simplify_by_ratio', 'processing.simplify_to_faces',
             'processing.weld_vertices', 'system.run_command']
# The 6f additions, which a test below runs one file at a time over real meshes.
MESH_IDS = ['processing.convert_format', 'processing.simplify_to_faces',
            'processing.simplify_by_ratio', 'processing.repair_mesh',
            'processing.weld_vertices', 'processing.center_pivot',
            'processing.normalize_size', 'processing.generate_uvs', 'file.thumbnail']


class FakeLibrary:
    """The library as the pane sees it: one call that answers with rows."""

    def __init__(self, rows=(), error=None):
        self.rows = list(rows)
        self.error = error

    def get_models(self, limit=1000):
        if self.error:
            raise RuntimeError(self.error)
        return list(self.rows)


def register_probe(action_id, func, params=None, batch=None, case=None):
    """Put an action in the registry for the duration of one test."""
    ActionRegistry.register(action_id, func, 'probe', params or {}, batch=batch)

    def pop():
        ActionRegistry._actions.pop(action_id, None)
        ActionRegistry._batch_specs.pop(action_id, None)
        ActionRegistry._batch_extensions.pop(action_id, None)
        ActionRegistry._descriptions.pop(action_id, None)
        ActionRegistry._param_specs.pop(action_id, None)

    if case is not None:
        case.addCleanup(pop)
    return pop


class DirCase(unittest.TestCase):
    """A folder of files on disk, shared by the cases below."""

    def drain(self):
        """Deliver every queued signal while this case's objects are still alive.

        A worker thread posts its verdict to the event loop rather than handing it over
        itself. If the case is collected first, that queued call points at a processor
        python has already freed, and on Windows the process dies on the next pass of
        the loop instead of failing a test.
        """
        for _ in range(6):
            APP.processEvents()
            time.sleep(0.02)
            APP.processEvents()

    def make(self, folder, name, text='v 0 0 0\n'):
        path = os.path.join(folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def read(self, path):
        with open(path, encoding='utf-8') as handle:
            return handle.read()

    # --- real meshes, so an action can be measured against what it wrote --------
    def cube(self, folder, name='hero.obj', translated=None):
        """A twelve-face box. Small enough to check by hand, real enough to load."""
        mesh = trimesh.creation.box()
        if translated is not None:
            mesh.apply_translation(translated)
        path = os.path.join(folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mesh.export(path)
        return path

    def sphere(self, folder, name='hero.obj', subdivisions=3, radius=1.0):
        """A dense mesh - what a simplifier is actually asked to reduce."""
        path = os.path.join(folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        trimesh.creation.icosphere(subdivisions=subdivisions,
                                   radius=radius).export(path)
        return path

    def count(self, path, what='faces'):
        """How many faces or vertices the file on disk really has."""
        loaded = trimesh.load(path, process=False)
        return len(getattr(loaded, what))


class BindingCase(DirCase):
    """The registry decides what a batch may be; the pane only reads that decision."""

    @classmethod
    def setUpClass(cls):
        ActionRegistry.register_default_actions()

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_6d_bind_')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.out = os.path.join(self.work, 'out')
        os.makedirs(self.out)
        self.hero = self.make(self.work, 'hero.obj')

    def test_01_only_actions_that_take_one_file_at_a_time_are_offered(self):
        """Baking needs a high-poly and a low-poly at once, so it is not a batch."""
        offered = ActionRegistry.batch_actions()
        self.assertEqual(sorted(offered), BATCH_IDS, sorted(offered))
        self.assertNotIn('processing.bake_texture', offered)

    def test_02_a_batch_description_travels_with_the_action(self):
        self.assertEqual(ActionRegistry.batch_actions()['file.copy'], 'Copy a file')

    def test_03_the_file_goes_into_the_parameter_that_takes_it(self):
        kwargs, why = ActionRegistry.bind_batch_params('file.copy', self.hero, self.out)
        self.assertIsNone(why, why)
        self.assertEqual(kwargs['source'], self.hero)
        self.assertEqual(kwargs['destination'], os.path.join(self.out, 'hero.obj'))

    def test_04_an_action_that_cannot_repeat_keeps_its_reason(self):
        kwargs, why = ActionRegistry.bind_batch_params('processing.bake_texture',
                                                      self.hero, self.out)
        self.assertIsNone(kwargs)
        self.assertIn('processing.bake_texture', why)

    def test_05_a_writing_action_without_an_output_folder_is_refused(self):
        for action, missing in (('file.copy', 'output folder'), ('file.move', 'output folder'),
                                ('processing.generate_lod', 'output folder')):
            kwargs, why = ActionRegistry.bind_batch_params(action, self.hero, '')
            self.assertIsNone(kwargs, action)
            self.assertIn(missing, why, why)
            # a folder that was never chosen is a different complaint from a folder that
            # went missing, and only the first one names the action that needs it
            self.assertIn(action, why, why)
            self.assertIn('chosen', why, why)

    def test_06_an_output_folder_that_does_not_exist_is_named(self):
        ghost = os.path.join(self.work, 'ghost')
        kwargs, why = ActionRegistry.bind_batch_params('file.copy', self.hero, ghost)
        self.assertIsNone(kwargs)
        self.assertIn(ghost, why)
        self.assertIn('is not a folder', why)

    def test_07_a_file_cannot_be_copied_onto_itself(self):
        kwargs, why = ActionRegistry.bind_batch_params('file.copy', self.hero, self.work)
        self.assertIsNone(kwargs)
        self.assertIn('onto itself', why)

    def test_08_an_action_that_writes_no_file_needs_no_output_folder(self):
        kwargs, why = ActionRegistry.bind_batch_params('file.delete', self.hero)
        self.assertIsNone(why, why)
        self.assertEqual(kwargs, {'path': self.hero})

    def test_09_a_command_without_the_file_in_it_is_refused(self):
        kwargs, why = ActionRegistry.bind_batch_params('system.run_command', self.hero,
                                                        '', {'command': 'python build.py'})
        self.assertIsNone(kwargs)
        self.assertIn('{file}', why)

    def test_10_the_placeholder_becomes_this_file(self):
        kwargs, why = ActionRegistry.bind_batch_params(
            'system.run_command', self.hero, '', {'command': 'python build.py {file}'})
        self.assertIsNone(why, why)
        self.assertEqual(kwargs['command'], f'python build.py {self.hero}')

    def test_11_a_path_with_a_space_is_quoted_for_the_shell(self):
        spaced = self.make(self.work, 'deep space', 'hero.obj')
        kwargs, why = ActionRegistry.bind_batch_params(
            'system.run_command', spaced, '', {'command': 'build {file}'})
        self.assertIsNone(why, why)
        self.assertEqual(kwargs['command'], f'build "{spaced}"')

    def test_12_a_parameter_the_action_does_not_take_blocks_the_file(self):
        kwargs, why = ActionRegistry.bind_batch_params('file.delete', self.hero, '',
                                                       {'levels': 3})
        self.assertIsNone(kwargs)
        self.assertIn('levels', why)

    def test_13_a_file_that_is_not_there_anymore_is_refused_by_name(self):
        gone = os.path.join(self.work, 'gone.obj')
        kwargs, why = ActionRegistry.bind_batch_params('file.delete', gone)
        self.assertIsNone(kwargs)
        self.assertIn('gone.obj', why)

    def test_14_binding_does_not_touch_the_disk(self):
        """Preview comes through this method, so binding must not be allowed to write."""
        target = os.path.join(self.out, 'hero.obj')
        ActionRegistry.bind_batch_params('file.copy', self.hero, self.out)
        self.assertFalse(os.path.exists(target))
        self.assertEqual(os.listdir(self.out), [])


class ProcessorCase(DirCase):
    """The loop that repeats one action, and the verdict it reports."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_6d_proc_')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.items = ['a.obj', 'b.obj', 'c.obj']
        self.addCleanup(self.drain)
        self.processor = BatchProcessor()
        self.summaries = []
        self.progress = []
        self.processor.batch_completed.connect(self.summaries.append)
        self.processor.progress_updated.connect(
            lambda current, total, item: self.progress.append((current, total, item)))

    def test_15_every_file_is_handed_to_the_callable(self):
        seen = []
        self.processor.process_batch(self.items, lambda item: seen.append(item))
        self.assertEqual(seen, self.items)

    def test_16_an_action_that_says_no_is_a_failed_file_not_a_successful_one(self):
        """The bug this whole suite exists for: refusals used to be counted as done."""
        self.processor.process_batch(
            self.items,
            lambda item: {'success': False, 'error': 'the loader gave up'})
        summary = self.summaries[-1]
        self.assertEqual(summary['succeeded'], 0, summary)
        self.assertEqual(summary['failed'], 3, summary)
        self.assertEqual([one['error'] for one in summary['results']],
                         ['the loader gave up'] * 3)

    def test_17_a_refusal_that_gives_no_reason_still_says_which_file_it_was(self):
        self.processor.process_batch(['x.obj'], lambda item: {'success': False})
        record = self.summaries[-1]['results'][0]
        self.assertFalse(record['success'])
        self.assertIn('no reason', record['error'])

    def test_18_a_returned_report_is_kept_verbatim(self):
        self.processor.process_batch(['x.obj'],
                                     lambda item: {'success': True, 'result': 'Copied 12 bytes'})
        self.assertEqual(self.summaries[-1]['results'][0]['result'],
                         {'success': True, 'result': 'Copied 12 bytes'})

    def test_19_a_callable_that_raises_is_one_failed_file_not_a_dead_loop(self):
        self.processor.process_batch(self.items,
                                     lambda item: (_ for _ in ()).throw(OSError('disk is gone')))
        summary = self.summaries[-1]
        self.assertEqual(summary['failed'], 3, summary)
        self.assertEqual(summary['succeeded'], 0, summary)

    def test_20_the_summary_counts_the_run_it_just_did(self):
        def half(item):
            return {'success': item.endswith('a.obj')}
        self.processor.process_batch(self.items, half)
        summary = self.summaries[-1]
        self.assertEqual((summary['total'], summary['ran'], summary['succeeded'],
                          summary['failed'], summary['not_run'], summary['stopped']),
                         (3, 3, 1, 2, 0, False), summary)

    def test_21_progress_names_each_file_before_it_runs(self):
        self.processor.process_batch(self.items, lambda item: None)
        self.assertEqual(self.progress, [(1, 3, 'a.obj'), (2, 3, 'b.obj'),
                                         (3, 3, 'c.obj')])

    def test_22_an_old_style_progress_callback_still_arrives(self):
        seen = []
        self.processor.process_batch(self.items, lambda item: None,
                                     progress_callback=lambda c, t, item: seen.append((c, t)))
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_23_no_files_is_reported_as_nothing_run(self):
        self.processor.process_batch([], lambda item: None)
        summary = self.summaries[-1]
        self.assertEqual((summary['total'], summary['ran'], summary['stopped']), (0, 0, False))

    def test_24_a_stop_is_honoured_at_the_next_file(self):
        gate = threading.Event()
        self.addCleanup(gate.set)

        def slow(item):
            gate.wait(5)
            return {'success': True}

        thread = threading.Thread(target=self.processor.process_batch,
                                  args=(self.items, slow), daemon=True)
        thread.start()
        while not self.progress:
            APP.processEvents()
            time.sleep(0.02)
        self.processor.request_stop()
        gate.set()
        thread.join(10)
        APP.processEvents()
        summary = self.summaries[-1]
        self.assertEqual(summary['ran'], 1, summary)
        self.assertEqual(summary['not_run'], 2, summary)
        self.assertTrue(summary['stopped'], summary)
        self.assertFalse(self.processor.is_processing)

    def test_25_a_pause_holds_the_run_and_a_resume_finishes_it(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        started = []

        def slow(item):
            started.append(item)
            gate.wait(5)
            return {'success': True}

        thread = threading.Thread(target=self.processor.process_batch,
                                  args=(self.items, slow), daemon=True)
        thread.start()
        while not started:
            APP.processEvents()
            time.sleep(0.02)
        self.processor.set_paused(True)
        gate.set()
        APP.processEvents()
        deadline = time.time() + 3
        while len(started) < 2 and time.time() < deadline:
            APP.processEvents()
            time.sleep(0.02)
        self.assertEqual(len(started), 1, 'a paused batch started another file')
        self.assertTrue(self.processor.is_paused)
        self.processor.set_paused(False)
        thread.join(10)
        APP.processEvents()
        self.assertEqual(started, self.items)
        self.assertFalse(self.summaries[-1]['stopped'])

    def test_26_a_stop_requested_while_paused_ends_the_run(self):
        """A parked batch is not a trapped one: Stop still gets through."""
        gate = threading.Event()
        self.addCleanup(gate.set)
        started = []

        def slow(item):
            started.append(item)
            gate.wait(5)
            return {'success': True}

        thread = threading.Thread(target=self.processor.process_batch,
                                  args=(self.items, slow), daemon=True)
        thread.start()
        while not started:
            APP.processEvents()
            time.sleep(0.02)
        self.processor.set_paused(True)
        gate.set()
        deadline = time.time() + 3
        while not self.processor.is_paused and time.time() < deadline:
            APP.processEvents()
            time.sleep(0.02)
        self.assertTrue(self.processor.is_paused, 'the run never reached its pause')
        self.processor.request_stop()
        thread.join(10)
        APP.processEvents()
        summary = self.summaries[-1]
        self.assertEqual(summary['ran'], 1, summary)
        self.assertEqual(summary['not_run'], 2, summary)
        self.assertTrue(summary['stopped'], summary)

    def test_27_the_processor_is_free_again_after_a_run(self):
        self.processor.process_batch(['a.obj'], lambda item: None)
        self.assertFalse(self.processor.is_processing)
        self.assertIsNone(self.processor.current_batch)
        self.assertFalse(self.processor.is_paused)


class EngineRunCase(DirCase):
    """The engine owns the thread; the pane only reports what its signals say."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='renderfox_6d_home_')
        self.previous = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: self.home
        self.work = tempfile.mkdtemp(prefix='renderfox_6d_run_')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(shutil.rmtree, self.home, True)
        self.addCleanup(lambda: setattr(engine_module, 'app_data_dir', self.previous))
        self.addCleanup(self.drain)
        self.engine = AutomationEngine()
        self.addCleanup(self.engine.stop)
        self.finished = []
        self.engine.batch_processor.batch_completed.connect(
            lambda summary: self.finished.append(summary))

    def wait(self, want, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            APP.processEvents()
            if want():
                return True
            time.sleep(0.02)
        return False

    def test_28_a_run_happens_on_a_thread_and_reports_when_it_is_done(self):
        box = []
        self.assertTrue(self.engine.run_batch(['a.obj', 'b.obj'],
                                              lambda item: box.append(item) or {'success': True}))
        self.assertTrue(self.wait(lambda: len(self.finished) == 1), 'no completion arrived')
        self.assertEqual(sorted(box), ['a.obj', 'b.obj'])
        self.assertEqual(self.finished[-1]['succeeded'], 2)

    def test_29_a_second_batch_is_refused_while_one_is_running(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        started = []

        def slow(item):
            started.append(item)
            gate.wait(5)
            return {'success': True}

        self.assertTrue(self.engine.run_batch(['a.obj'], slow))
        self.assertTrue(self.wait(lambda: bool(started)))
        self.assertFalse(self.engine.run_batch(['b.obj'], lambda item: None),
                         'two batches share one processor and one progress bar')

    def test_29b_a_stopped_engine_leaves_no_batch_behind(self):
        """A worker outliving its engine reports into objects python has already freed.

        Three files that each take two seconds: stop() asks for the run to end, so it
        owes the one file in hand and nothing after it. Without either half of that,
        this test still has a live thread - or a full list - to notice.
        """
        started = []

        def slow(item):
            started.append(item)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                time.sleep(0.05)
            return {'success': True}

        self.assertTrue(self.engine.run_batch(['a.obj', 'b.obj', 'c.obj'], slow))
        self.assertTrue(self.wait(lambda: bool(started)), 'the batch never began')
        before = {one.name for one in threading.enumerate()}
        self.engine.stop()
        left = [one.name for one in threading.enumerate()
                if one.name not in before and '_run_batch' in one.name and one.is_alive()]
        self.assertEqual(left, [], 'a batch thread outlived engine.stop()')
        self.assertFalse(self.engine.batch_processor.is_processing,
                         'the processor stayed claimed after its engine stopped')
        self.assertTrue(self.wait(lambda: bool(self.finished)),
                        'the verdict stop() waited for never arrived')
        summary = self.finished[-1]
        self.assertTrue(summary['stopped'], summary)
        self.assertEqual(summary['ran'], 1, summary)
        self.assertEqual(summary['not_run'], 2, summary)

    def test_30_an_empty_batch_never_starts(self):
        self.assertFalse(self.engine.run_batch([], lambda item: None))
        self.assertFalse(self.engine.batch_processor.is_processing)

    def test_31_stop_and_pause_are_only_answered_while_a_batch_runs(self):
        self.assertFalse(self.engine.stop_batch())
        self.assertFalse(self.engine.pause_batch(True))

    def test_32_the_engine_gives_its_items_to_the_actions_it_was_asked_to_use(self):
        """`batch_process` is the plain-python door; it must judge outcomes the same way."""
        results = self.engine.batch_process(
            ['a.obj', 'b.obj'], lambda item: {'success': False, 'error': 'nope'})
        self.assertEqual([one['success'] for one in results], [False, False])


class PaneCase(DirCase):
    """The Batch tab the user clicks, over a real folder of real files."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix='renderfox_6d_panehome_')
        cls.previous_data_dir = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: cls.home
        cls.previous_boxes = (QMessageBox.information, QMessageBox.critical,
                              QMessageBox.warning, QMessageBox.question)
        cls.popups = []
        QMessageBox.information = lambda *a, **k: cls.popups.append(('information', a))
        QMessageBox.critical = lambda *a, **k: cls.popups.append(('critical', a))
        QMessageBox.warning = lambda *a, **k: cls.popups.append(('warning', a))
        QMessageBox.question = lambda *a, **k: (cls.popups.append(('question', a)),
                                                QMessageBox.StandardButton.Yes)[1]

    @classmethod
    def tearDownClass(cls):
        engine_module.app_data_dir = cls.previous_data_dir
        (QMessageBox.information, QMessageBox.critical, QMessageBox.warning,
         QMessageBox.question) = cls.previous_boxes
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_6d_pane_')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.src = os.path.join(self.work, 'models')
        self.out = os.path.join(self.work, 'out')
        os.makedirs(self.src)
        os.makedirs(self.out)
        for name in ('tasks.json', 'workflows.json'):
            path = os.path.join(self.home, name)
            if os.path.exists(path):
                os.remove(path)
        self.popups.clear()
        self.tab = AutomationTab()
        self.addCleanup(self.drain)
        self.addCleanup(self.tab.automation_engine.stop)
        self.addCleanup(self.set_free)
        self.tab._library = FakeLibrary()

    # --- helpers ---------------------------------------------------------------
    def set_free(self):
        """No batch thread may outlive the test that started it."""
        processor = self.tab.automation_engine.batch_processor
        processor.request_stop()
        processor.set_paused(False)

    def pick(self, combo, data):
        for row in range(combo.count()):
            if combo.itemData(row) == data:
                combo.setCurrentIndex(row)
                APP.processEvents()
                return
        raise AssertionError(f'{data} is not offered')

    def configure(self, operation='file.copy', folder=None,
                  output=None, params=None, kinds=None, recursive=None,
                  overwrite=None, backup=None, library=False):
        self.tab.source_type_combo.setCurrentText('Model Library' if library else 'Folder')
        if operation:
            self.pick(self.tab.operation_combo, operation)
        if folder is not None:
            self.tab.source_path_edit.setText(folder)
        if output is not None:
            self.tab.output_path_edit.setText(output)
        if params is not None:
            self.tab.batch_params_edit.setText(params)
        if kinds is not None:
            self.tab.file_types_edit.setText(kinds)
        if recursive is not None:
            self.tab.recursive_cb.setChecked(recursive)
        if overwrite is not None:
            self.tab.overwrite_cb.setChecked(overwrite)
        if backup is not None:
            self.tab.backup_cb.setChecked(backup)
        self.tab._update_batch_controls()

    def ready_folder(self, *names, **kw):
        """A folder of files, and the pane pointed at it with no backup noise."""
        paths = [self.make(self.src, name) for name in names]
        settings = {'operation': 'file.copy', 'folder': self.src, 'output': self.out,
                    'backup': False, 'overwrite': False}
        settings.update(kw)
        self.configure(**settings)
        return paths

    def spin(self, want, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            APP.processEvents()
            if want():
                return True
            time.sleep(0.02)
        return False

    def settle(self):
        processor = self.tab.automation_engine.batch_processor
        self.assertTrue(self.spin(lambda: not processor.is_processing),
                        'the batch never reported')
        APP.processEvents()

    def slow_probe(self, action_id='probe.slow'):
        """An action that holds each file until the test lets it go."""
        started = []
        gate = threading.Event()
        self.addCleanup(gate.set)

        def hold(path=None, **kwargs):
            started.append(path)
            gate.wait(10)
            return {'success': True, 'result': 'took my time'}

        register_probe(action_id, hold,
                       {'path': {'type': 'str', 'required': True}},
                       batch=('path', None), case=self)
        self.tab._fill_batch_operations()
        return started, gate

    def log_lines(self):
        return self.tab.batch_log.toPlainText().splitlines()

    def warnings(self):
        return [str(args[2]) for kind, args in self.popups if kind == 'warning']

    def tab_source(self):
        with open(os.path.join(ROOT, 'src', 'ui', 'automation_tab.py'),
                  encoding='utf-8') as handle:
            return handle.read()

    def batch_source(self):
        """Only the Batch tab and the methods behind it."""
        source = self.tab_source()
        parts = []
        for first, last in (('    def create_batch_operations_tab(self):',
                             '    def create_scheduler_tab(self):'),
                            ('    # --- Batch Operations',
                             '    def _task_action_choices(self):')):
            start = source.index(first)
            parts.append(source[start:source.index(last, start)])
        return '\n'.join(parts)

    # --- what the pane offers --------------------------------------------------
    def test_33_every_batch_button_has_a_job(self):
        for name in ('start_batch_btn', 'pause_batch_btn', 'stop_batch_btn',
                    'preview_batch_btn', 'browse_source_btn', 'browse_output_btn'):
            button = getattr(self.tab, name)
            self.assertTrue(button.receivers(button.clicked), f'{name} is still a dead button')
        self.assertTrue(self.tab.source_type_combo.receivers(
            self.tab.source_type_combo.currentTextChanged))
        self.assertTrue(self.tab.operation_combo.receivers(
            self.tab.operation_combo.currentIndexChanged))

    def test_34_the_operation_list_is_the_registrys_own(self):
        """Nine names no action answered to used to fill this combo."""
        offered = [self.tab.operation_combo.itemData(row)
                   for row in range(self.tab.operation_combo.count())]
        self.assertEqual(offered, BATCH_IDS, offered)
        labels = [self.tab.operation_combo.itemText(row)
                  for row in range(self.tab.operation_combo.count())]
        self.assertIn('Copy a file', ' '.join(labels), labels)

    def test_35_an_action_that_cannot_take_one_file_is_not_offered(self):
        offered = [self.tab.operation_combo.itemData(row)
                   for row in range(self.tab.operation_combo.count())]
        self.assertNotIn('processing.bake_texture', offered)

    def test_36_the_source_list_is_two_things_the_pane_can_reach(self):
        self.assertEqual([self.tab.source_type_combo.itemText(row)
                          for row in range(self.tab.source_type_combo.count())],
                         ['Folder', 'Model Library'])

    def test_37_a_library_source_closes_the_folder_fields(self):
        self.configure(library=True)
        self.assertFalse(self.tab.source_path_edit.isEnabled())
        self.assertFalse(self.tab.browse_source_btn.isEnabled())
        self.assertFalse(self.tab.recursive_cb.isEnabled())
        self.configure(library=False)
        self.assertTrue(self.tab.source_path_edit.isEnabled())

    def test_38_an_action_that_writes_no_file_closes_the_output_fields(self):
        self.configure(operation='file.delete', folder=self.src)
        self.assertFalse(self.tab.output_path_edit.isEnabled())
        self.assertFalse(self.tab.browse_output_btn.isEnabled())
        self.assertFalse(self.tab.overwrite_cb.isEnabled())
        self.configure(operation='file.copy', folder=self.src, output=self.out)
        self.assertTrue(self.tab.output_path_edit.isEnabled())
        # overwrite only means something where one named file lands, and it can already exist
        self.assertTrue(self.tab.overwrite_cb.isEnabled())
        self.configure(operation='processing.generate_lod', folder=self.src, output=self.out)
        self.assertTrue(self.tab.output_path_edit.isEnabled())
        self.assertFalse(self.tab.overwrite_cb.isEnabled(),
                         'a folder-filling action never has one file in the way')

    def test_39_the_hint_names_the_parameters_the_action_will_get(self):
        self.configure(operation='file.copy', folder=self.src, output=self.out)
        hint = self.tab.batch_hint_label.text()
        self.assertIn('source', hint)
        self.assertIn('destination', hint)
        self.configure(operation='system.run_command', folder=self.src)
        self.assertIn('{file}', self.tab.batch_hint_label.text())

    def test_40_the_pane_opens_claiming_nothing(self):
        self.assertEqual(self.tab.batch_log.toPlainText(), '')
        self.assertEqual(self.tab.batch_status_label.text(), 'Nothing has run yet.')
        self.assertEqual(self.tab.batch_progress.value(), 0)
        self.assertFalse(self.tab.pause_batch_btn.isEnabled())
        self.assertFalse(self.tab.stop_batch_btn.isEnabled())

    def test_41_no_invented_operation_or_source_names_are_left_in_the_code(self):
        for ghost in ('Format Conversion', 'Texture Optimization', 'Metadata Extraction',
                      'Thumbnail Generation', 'Quality Analysis', 'Custom Script',
                      'Selected Models', 'Search Results', 'File List', 'Model Validation',
                      'parallel_processing_cb', 'max_threads_spin', 'target_format_combo',
                      'batch_progress_value', 'batch_timer'):
            self.assertNotIn(ghost, self.batch_source(), ghost)

    # --- which files a source gives up -----------------------------------------
    def test_42_a_blank_filter_means_the_model_formats_the_app_knows(self):
        self.make(self.src, 'a.obj')
        self.make(self.src, 'b.txt')
        self.make(self.src, 'c.fbx')
        self.configure(folder=self.src, kinds=None)
        items, why = self.tab.collect_batch_items()
        self.assertIsNone(why, why)
        self.assertEqual([os.path.basename(one) for one in items], ['a.obj', 'c.fbx'])

    def test_43_the_filter_can_ask_for_other_files(self):
        self.make(self.src, 'a.obj')
        self.make(self.src, 'b.txt')
        self.configure(folder=self.src, kinds='.txt, *.cfg')
        self.make(self.src, 'c.cfg')
        items, why = self.tab.collect_batch_items()
        self.assertIsNone(why, why)
        self.assertEqual(sorted(os.path.basename(one) for one in items), ['b.txt', 'c.cfg'])

    def test_44_a_star_takes_every_file_in_the_folder(self):
        for name in ('a.obj', 'b.txt', 'readme.md'):
            self.make(self.src, name)
        self.configure(folder=self.src, kinds='*')
        items, why = self.tab.collect_batch_items()
        self.assertIsNone(why, why)
        self.assertEqual(len(items), 3, items)

    def test_45_subfolders_follow_the_recursive_switch(self):
        self.make(self.src, 'a.obj')
        self.make(os.path.join(self.src, 'nested'), 'hero2.obj')
        self.configure(folder=self.src, recursive=True)
        deep, _ = self.tab.collect_batch_items()
        self.assertEqual(len(deep), 2, deep)
        self.configure(folder=self.src, recursive=False)
        flat, _ = self.tab.collect_batch_items()
        self.assertEqual([os.path.basename(one) for one in flat], ['a.obj'], flat)

    def test_46_the_backup_folder_is_never_offered_as_input(self):
        self.make(self.src, 'a.obj')
        self.make(os.path.join(self.src, BACKUP_SUBFOLDER), 'a.obj')
        self.configure(folder=self.src, kinds='*')
        items, why = self.tab.collect_batch_items()
        self.assertEqual([os.path.basename(one) for one in items], ['a.obj'], items)

    def test_47_a_source_that_is_not_there_is_named_instead_of_run(self):
        ghost = os.path.join(self.work, 'ghost')
        self.configure(folder=ghost)
        items, why = self.tab.collect_batch_items()
        self.assertEqual(items, [])
        self.assertIn(ghost, why)

    def test_48_a_folder_with_nothing_wanted_says_so(self):
        self.make(self.src, 'notes.txt')
        self.configure(folder=self.src)
        items, why = self.tab.collect_batch_items()
        self.assertEqual(items, [])
        self.assertIn('no file in that folder matches', why)

    def test_49_no_folder_chosen_is_a_complaint_not_a_crash(self):
        self.configure(folder='')
        items, why = self.tab.collect_batch_items()
        self.assertEqual((items, why), ([], 'choose the folder the files come from'))

    def test_50_a_library_source_reads_the_rows_the_library_answers_with(self):
        hero = self.make(self.src, 'hero.obj')
        self.make(self.src, 'gone.obj')
        self.tab._library = FakeLibrary([{'path': hero}, {'path': os.path.join(self.src,
                                                                              'gone.obj')}])
        os.remove(os.path.join(self.src, 'gone.obj'))
        self.configure(library=True, operation='file.copy', output=self.out)
        items, why = self.tab.collect_batch_items()
        self.assertIsNone(why, why)
        self.assertEqual([os.path.normpath(one) for one in items], [os.path.normpath(hero)])

    def test_51_a_library_that_raises_becomes_a_complaint(self):
        self.tab._library = FakeLibrary(error='the database is locked')
        self.configure(library=True, operation='file.copy', output=self.out)
        items, why = self.tab.collect_batch_items()
        self.assertEqual(items, [])
        self.assertIn('locked', why)

    # --- preview: the plan, with nothing run -----------------------------------
    def test_52_preview_lists_every_call_and_makes_none_of_them(self):
        self.ready_folder('a.obj', 'b.obj')
        self.tab.preview_batch_btn.click()
        log = self.tab.batch_log.toPlainText()
        self.assertIn('2 file(s) would run as file.copy', log)
        self.assertIn('a.obj -> ' + os.path.join(self.out, 'a.obj'), log)
        self.assertIn('Preview only', self.tab.batch_status_label.text())
        self.assertEqual(os.listdir(self.out), [], 'preview wrote something')

    def test_53_preview_shows_which_files_cannot_run_and_why(self):
        self.ready_folder('a.obj', 'b.obj')
        self.make(self.out, 'a.obj', 'OLD')
        self.tab.preview_batch_btn.click()
        log = self.tab.batch_log.toPlainText()
        self.assertIn('1 file(s) would run as file.copy', log)
        self.assertIn('cannot run', log)
        self.assertIn('overwrite is off', log)
        self.assertIn('1 cannot', self.tab.batch_status_label.text())

    def test_54_preview_of_a_source_that_cannot_run_says_so_and_writes_nothing(self):
        self.configure(folder=os.path.join(self.work, 'ghost'), output=self.out)
        self.tab.preview_batch_btn.click()
        self.assertIn('Preview: nothing can run yet.', self.tab.batch_status_label.text())
        self.assertEqual(len(self.warnings()), 1, self.warnings())
        self.assertIn('ghost', self.warnings()[0])

    def test_55_parameters_are_read_as_data_by_the_same_parser_the_tasks_use(self):
        self.ready_folder('hero.obj', operation='processing.generate_lod',
                          params='"levels": 2')
        plan = self.tab._batch_plan()
        self.assertEqual(plan['params'], {'levels': 2})
        self.assertEqual(plan['ready'][0][1], {'input_file': plan['ready'][0][0],
                                               'output_dir': self.out, 'levels': 2})
        self.configure(params='levels = two')
        plan = self.tab._batch_plan()
        self.assertEqual(plan['ready'], [])
        self.assertIn('name/value pairs', plan['blocked'][0])

    def test_56_a_command_batch_is_previewed_once_per_file(self):
        self.ready_folder('a.obj', 'b.obj', operation='system.run_command',
                          params='"command": "build.py {file}"')
        self.tab.preview_batch_btn.click()
        log = self.tab.batch_log.toPlainText()
        self.assertIn('build.py ' + os.path.join(self.src, 'a.obj'), log)
        self.assertIn('build.py ' + os.path.join(self.src, 'b.obj'), log)

    # --- running ---------------------------------------------------------------
    def test_57_a_copy_batch_puts_every_file_in_the_output_folder(self):
        self.ready_folder('a.obj', 'b.obj')
        self.tab.start_batch_btn.click()
        self.settle()
        self.assertEqual(sorted(os.listdir(self.out)), ['a.obj', 'b.obj'])
        self.assertEqual(self.tab.batch_status_label.text(),
                         'Finished 2 file(s): 2 ok, 0 failed')
        self.assertEqual(self.tab.batch_progress.value(), 100)

    def test_58_the_log_says_what_each_action_reported(self):
        self.ready_folder('a.obj')
        self.tab.start_batch_btn.click()
        self.settle()
        line = [one for one in self.log_lines() if one.startswith('  ok')][-1]
        self.assertIn('Copied', line, line)
        self.assertIn('bytes', line, line)

    def test_59_a_batch_where_every_file_fails_does_not_say_completed(self):
        def refuse(path=None, **kwargs):
            return {'success': False, 'error': 'the exporter said no'}

        register_probe('probe.refuse', refuse, {'path': {'type': 'str', 'required': True}},
                       batch=('path', None), case=self)
        self.tab._fill_batch_operations()
        self.ready_folder('a.obj', 'b.obj', operation='probe.refuse', output=None)
        self.tab.start_batch_btn.click()
        self.settle()
        self.assertEqual(self.tab.batch_status_label.text(),
                         'Finished 2 file(s): 0 ok, 2 failed')
        self.assertNotIn('completed', self.tab.batch_status_label.text().lower())
        text = self.tab.batch_log.toPlainText()
        self.assertIn('the exporter said no', text)
        self.assertNotIn('successfully', text.lower())

    def test_60_start_refuses_to_run_a_batch_that_stops_halfway(self):
        self.ready_folder('a.obj', 'b.obj')
        kept = self.make(self.out, 'a.obj', 'OLD')
        self.tab.start_batch_btn.click()
        self.assertFalse(self.tab.automation_engine.batch_processor.is_processing)
        self.assertEqual(len(self.warnings()), 1, self.warnings())
        self.assertIn('cannot run', self.warnings()[0])
        self.assertEqual(self.read(kept), 'OLD')
        self.assertFalse(os.path.exists(os.path.join(self.out, 'b.obj')),
                         'the half of the batch that could run was run anyway')
        self.assertEqual(self.tab.batch_status_label.text(), 'Nothing was started.')

    def test_61_overwrite_on_replaces_the_file_in_the_output_folder(self):
        self.ready_folder('a.obj', overwrite=True)
        kept = self.make(self.out, 'a.obj', 'OLD')
        self.tab.start_batch_btn.click()
        self.settle()
        self.assertEqual(self.read(kept), 'v 0 0 0\n')

    def test_62_a_move_batch_empties_the_source_folder(self):
        self.ready_folder('a.obj', 'b.obj', operation='file.move')
        self.tab.start_batch_btn.click()
        self.settle()
        self.assertEqual(sorted(os.listdir(self.src)), [])
        self.assertEqual(sorted(os.listdir(self.out)), ['a.obj', 'b.obj'])

    def test_63_a_delete_batch_with_backup_keeps_a_copy_of_every_file(self):
        self.ready_folder('a.obj', 'b.obj', operation='file.delete', backup=True)
        self.tab.start_batch_btn.click()
        self.settle()
        self.assertEqual(sorted(os.listdir(self.src)), [BACKUP_SUBFOLDER])
        kept = os.listdir(os.path.join(self.src, BACKUP_SUBFOLDER))
        self.assertEqual(sorted(kept), ['a.obj', 'b.obj'], kept)
        self.assertEqual(self.tab.batch_status_label.text(),
                         'Finished 2 file(s): 2 ok, 0 failed')

    def test_64_a_delete_batch_without_backup_writes_no_anything(self):
        self.ready_folder('a.obj', operation='file.delete', backup=False)
        self.tab.start_batch_btn.click()
        self.settle()
        self.assertEqual(sorted(os.listdir(self.src)), [])
        self.assertFalse(os.path.isdir(os.path.join(self.src, BACKUP_SUBFOLDER)))

    def test_65_a_file_that_vanishes_before_its_turn_is_one_failed_file(self):
        doomed = self.make(self.src, 'doomed.obj')
        self.make(self.src, 'stays.obj')
        self.ready_folder(operation='file.delete', backup=False)
        operation = self.tab._batch_operation('file.delete', '', {},
                                              {'overwrite': True, 'backup': False})
        os.remove(doomed)
        outcome = operation(doomed)
        self.assertFalse(outcome['success'])
        self.assertIn('not a file', outcome['error'])

    def test_66_the_switches_are_read_once_at_the_start(self):
        """Toggling a box mid-run must not change what the batch believes."""
        self.ready_folder('a.obj')
        self.make(self.out, 'a.obj', 'OLD')
        operation = self.tab._batch_operation('file.copy', self.out, {},
                                              {'overwrite': False, 'backup': False})
        self.tab.overwrite_cb.setChecked(True)
        self.tab.backup_cb.setChecked(True)
        outcome = operation(os.path.join(self.src, 'a.obj'))
        self.assertFalse(outcome['success'])
        self.assertIn('overwrite is off', outcome['error'])
        self.assertFalse(os.path.isdir(os.path.join(self.src, BACKUP_SUBFOLDER)),
                         'the backup box was flipped after the run was planned')

    # --- a run in progress -----------------------------------------------------
    def test_67_the_setup_closes_while_a_batch_runs(self):
        started, gate = self.slow_probe()
        self.ready_folder('a.obj', 'b.obj', operation='probe.slow', output=None)
        self.tab.start_batch_btn.click()
        self.assertTrue(self.spin(lambda: len(started) == 1))
        self.assertFalse(self.tab.controls_group.isEnabled())
        self.assertFalse(self.tab.start_batch_btn.isEnabled())
        self.assertFalse(self.tab.preview_batch_btn.isEnabled())
        self.assertTrue(self.tab.stop_batch_btn.isEnabled())
        self.assertTrue(self.tab.pause_batch_btn.isEnabled())
        gate.set()
        self.settle()
        self.assertTrue(self.tab.controls_group.isEnabled())
        self.assertTrue(self.tab.start_batch_btn.isEnabled())

    def test_68_the_progress_bar_tracks_the_real_count(self):
        started, gate = self.slow_probe()
        self.ready_folder('a.obj', 'b.obj', 'c.obj', operation='probe.slow', output=None)
        self.tab.start_batch_btn.click()
        self.assertTrue(self.spin(lambda: self.tab.batch_progress.value() == 33))
        self.assertIn('Processing 1/3', self.tab.batch_status_label.text())
        gate.set()
        self.settle()
        self.assertEqual(self.tab.batch_progress.value(), 100)
        self.assertEqual(len(started), 3, started)

    def test_69_stop_starts_no_more_files(self):
        started, gate = self.slow_probe()
        self.ready_folder('a.obj', 'b.obj', 'c.obj', operation='probe.slow', output=None)
        self.tab.start_batch_btn.click()
        self.assertTrue(self.spin(lambda: len(started) == 1))
        self.tab.stop_batch_btn.click()
        gate.set()
        self.settle()
        self.assertEqual(len(started), 1, started)
        self.assertEqual(self.tab.batch_status_label.text(),
                         'Stopped after 1 of 3: 1 ok, 0 failed, 2 never ran')
        self.assertEqual(self.tab.batch_progress.value(), 33)

    def test_70_pause_holds_the_next_file_until_you_resume(self):
        started, gate = self.slow_probe()
        self.ready_folder('a.obj', 'b.obj', operation='probe.slow', output=None)
        self.tab.start_batch_btn.click()
        self.assertTrue(self.spin(lambda: len(started) == 1))
        self.tab.pause_batch_btn.click()
        self.assertEqual(self.tab.pause_batch_btn.text(), 'Resume')
        gate.set()
        APP.processEvents()
        time.sleep(0.4)
        self.assertEqual(len(started), 1, 'a paused batch started another file')
        self.tab.pause_batch_btn.click()
        self.assertEqual(self.tab.pause_batch_btn.text(), 'Pause')
        self.settle()
        self.assertEqual(len(started), 2, started)

    def test_71_a_second_start_is_refused_while_one_is_running(self):
        started, gate = self.slow_probe()
        self.ready_folder('a.obj', 'b.obj', operation='probe.slow', output=None)
        self.tab.start_batch_btn.click()
        self.assertTrue(self.spin(lambda: len(started) == 1))
        self.tab.start_batch_operation()
        self.assertIn('already running', ' '.join(self.warnings()))
        self.assertEqual(len(started), 1, started)
        gate.set()
        self.settle()

    def test_72_stop_and_pause_answer_only_a_running_batch(self):
        self.tab.stop_batch_btn.setEnabled(True)
        self.tab.stop_batch_operation()
        self.assertEqual(self.tab.batch_status_label.text(), 'Nothing is running to stop.')
        self.tab.pause_batch_btn.setEnabled(True)
        self.tab.toggle_batch_pause()
        self.assertEqual(self.tab.batch_status_label.text(), 'Nothing is running to pause.')

    # --- the plumbing that made the old pane unable to report anything ----------
    def test_73_the_pane_listens_to_the_processor_that_actually_runs(self):
        processor = self.tab.automation_engine.batch_processor
        self.assertTrue(processor.receivers(processor.progress_updated))
        self.assertTrue(processor.receivers(processor.batch_completed))
        self.assertFalse(hasattr(self.tab, 'batch_processor'),
                         'a private second processor hears nothing that runs')

    def test_74_progress_with_no_total_leaves_the_bar_alone(self):
        self.tab.on_batch_progress(1, 0, os.path.join(self.src, 'a.obj'))
        self.assertEqual(self.tab.batch_progress.value(), 0)

    def test_75_the_browse_buttons_put_the_chosen_folder_where_it_is_used(self):
        previous = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: self.out)
        self.addCleanup(setattr, QFileDialog, 'getExistingDirectory', previous)
        self.tab.browse_source_btn.click()
        self.assertEqual(self.tab.source_path_edit.text(), self.out)
        self.tab.browse_output_btn.click()
        self.assertEqual(self.tab.output_path_edit.text(), self.out)

    def test_76_an_unbound_action_cannot_crash_the_plan(self):
        """A stale combo entry says why it cannot run instead of raising."""
        register_probe('probe.unbound', lambda **kw: {'success': True},
                       {'path': {'type': 'str', 'required': True}}, batch=None, case=self)
        self.tab.operation_combo.addItem('probe.unbound', 'probe.unbound')
        self.pick(self.tab.operation_combo, 'probe.unbound')
        self.ready_folder('a.obj')
        self.pick(self.tab.operation_combo, 'probe.unbound')
        plan = self.tab._batch_plan()
        self.assertEqual(plan['ready'], [])
        self.assertIn('one file', plan['blocked'][0])
        self.tab.preview_batch()
        self.tab.start_batch_operation()
        self.assertFalse(self.tab.automation_engine.batch_processor.is_processing)

    def test_77_the_backup_switch_is_read_once_at_the_start(self):
        """Both directions: a flipped box changes nothing the plan already settled.

        The overwrite refusal returns before the backup step, so a test that only checks
        the refusal would never reach the line that decides whether to copy.
        """
        self.ready_folder('a.obj')
        planned_off = self.tab._batch_operation('file.copy', self.out, {},
                                                {'overwrite': True, 'backup': False})
        self.tab.backup_cb.setChecked(True)
        outcome = planned_off(os.path.join(self.src, 'a.obj'))
        self.assertTrue(outcome['success'], outcome)
        self.assertFalse(os.path.isdir(os.path.join(self.src, BACKUP_SUBFOLDER)),
                         'a box flipped after the plan made a backup folder anyway')

        self.ready_folder('b.obj')
        planned_on = self.tab._batch_operation('file.copy', self.out, {},
                                               {'overwrite': True, 'backup': True})
        self.tab.backup_cb.setChecked(False)
        outcome = planned_on(os.path.join(self.src, 'b.obj'))
        self.assertTrue(outcome['success'], outcome)
        self.assertTrue(os.path.isfile(os.path.join(self.src, BACKUP_SUBFOLDER, 'b.obj')),
                        'the backup the plan promised was not made')

    def test_78_preview_lists_a_file_the_registry_refuses(self):
        """A parameter the action never mentions is a blocked line, not a crash.

        Without this the plan reaches for `kwargs.get` on the None the registry answered
        with. That raises inside a Qt slot, and PyQt6 aborts the process on an unhandled
        exception there (0xC0000409) rather than failing a test, so the handler is called
        directly - `test_33` already proves the button is connected to it.
        """
        self.ready_folder('a.obj', 'b.obj', params='"levels": 2')
        plan = self.tab._batch_plan()
        self.assertEqual(plan['ready'], [], plan)
        self.assertEqual(len(plan['blocked']), 2, plan['blocked'])
        self.tab.preview_batch()
        log = self.tab.batch_log.toPlainText()
        self.assertIn('0 file(s) would run as file.copy', log)
        self.assertIn('levels', log)
        self.assertEqual(len(self.warnings()), 1, self.warnings())
        self.assertEqual(self.tab.batch_status_label.text(), 'Preview: nothing can run yet.')

    def test_79_preview_blocks_a_copy_that_would_land_on_its_own_file(self):
        self.ready_folder('a.obj', 'b.obj', output=self.src)
        plan = self.tab._batch_plan()
        self.assertEqual(plan['ready'], [], plan)
        self.tab.preview_batch()
        log = self.tab.batch_log.toPlainText()
        self.assertIn('onto itself', log)
        self.assertIn('cannot run', log)
        self.assertEqual(self.tab.batch_status_label.text(), 'Preview: nothing can run yet.')
        self.assertEqual(sorted(os.listdir(self.src)), ['a.obj', 'b.obj'], 'preview wrote something')

    # --- a batch of real meshes -------------------------------------------------
    def test_80_a_conversion_names_the_file_it_will_leave_behind(self):
        """The destination is renamed at bind time, so Preview speaks of that file.

        Without this the plan promised `hero.obj` while `hero.stl` appeared, and the
        overwrite switch checked a name nothing ever wrote.
        """
        self.cube(self.src, 'hero.obj')
        self.configure(operation='processing.convert_format', folder=self.src,
                       output=self.out, params='"output_format": "stl"', backup=False)
        plan = self.tab._batch_plan()
        self.assertEqual(len(plan['ready']), 1, plan)
        self.assertEqual(plan['ready'][0][1]['destination'],
                         os.path.join(self.out, 'hero.stl'))
        self.assertIn('hero.stl', '\n'.join(plan['lines']))

    def test_81_a_thumbnail_destination_is_named_as_a_picture(self):
        self.cube(self.src, 'hero.obj')
        self.configure(operation='file.thumbnail', folder=self.src, output=self.out,
                       backup=False)
        plan = self.tab._batch_plan()
        self.assertEqual(plan['ready'][0][1]['destination'],
                         os.path.join(self.out, 'hero.png'))
        self.assertIn('.png', self.tab.batch_hint_label.text())

    def test_82_only_an_action_that_takes_a_format_is_offered_one(self):
        self.configure(operation='file.copy', folder=self.src, output=self.out)
        self.assertNotIn('output_format', self.tab.batch_hint_label.text())
        self.configure(operation='processing.convert_format', folder=self.src,
                       output=self.out)
        self.assertIn('output_format', self.tab.batch_hint_label.text())

    def test_83_a_conversion_batch_writes_every_file_and_reports_its_bytes(self):
        for name in ('a.obj', 'b.obj'):
            self.cube(self.src, name)
        self.configure(operation='processing.convert_format', folder=self.src,
                       output=self.out, params='"output_format": "stl"', backup=False)
        self.tab.start_batch_operation()
        self.settle()
        self.assertEqual(sorted(os.listdir(self.out)), ['a.stl', 'b.stl'])
        self.assertEqual(self.tab.batch_status_label.text(),
                         'Finished 2 file(s): 2 ok, 0 failed')
        log = self.tab.batch_log.toPlainText()
        for name in ('a', 'b'):
            self.assertIn(f'ok - {name}.obj: Converted {name}.obj to {name}.stl', log)
            self.assertEqual(self.count(os.path.join(self.out, f'{name}.stl')), 12,
                             'the written file is not the mesh the log says it is')

    def test_84_the_overwrite_switch_reads_the_renamed_destination(self):
        self.cube(self.src, 'hero.obj')
        already = os.path.join(self.out, 'hero.stl')
        with open(already, 'w', encoding='utf-8') as handle:
            handle.write('mine')
        self.configure(operation='processing.convert_format', folder=self.src,
                       output=self.out, params='"output_format": "stl"',
                       overwrite=False, backup=False)
        plan = self.tab._batch_plan()
        self.assertEqual(plan['ready'], [], plan)
        self.assertIn('already there', plan['blocked'][0])
        self.tab.start_batch_operation()
        self.assertEqual(self.read(already), 'mine', 'a blocked batch overwrote it')
        self.assertEqual(self.tab.batch_status_label.text(), 'Nothing ran.')
        self.assertIn('hero.obj: ', self.warnings()[-1])
        self.assertIn('already there', self.warnings()[-1])

    def test_85_an_action_that_says_no_is_two_failed_files_not_a_completed_run(self):
        for name in ('a.obj', 'b.obj'):
            self.cube(self.src, name)
        self.configure(operation='file.thumbnail', folder=self.src, output=self.out,
                       params='"size": 4', backup=False)
        self.tab.start_batch_operation()
        self.settle()
        self.assertEqual(self.tab.batch_status_label.text(),
                         'Finished 2 file(s): 0 ok, 2 failed')
        log = self.tab.batch_log.toPlainText()
        self.assertIn('failed - a.obj:', log)
        self.assertIn('not an image this app will draw', log)
        self.assertEqual(os.listdir(self.out), [], 'the refused thumbnail wrote a file')

    def test_86_a_file_picked_elsewhere_fills_the_fields_the_batch_reads(self):
        path = self.cube(os.path.join(self.src, 'deep'), 'hero.obj')
        self.tab.batch_prepare_for_file(path)
        self.assertEqual(self.tab.source_type_combo.currentText(), 'Folder')
        self.assertEqual(self.tab.source_path_edit.text(), os.path.dirname(path))
        self.assertEqual(self.tab.file_types_edit.text(), '.obj')
        self.assertFalse(self.tab.recursive_cb.isChecked())
        self.assertEqual(self.tab.batch_status_label.text(), 'Nothing has run yet.')
        items, why = self.tab.collect_batch_items()
        self.assertIsNone(why, why)
        self.assertEqual([os.path.normpath(one) for one in items],
                         [os.path.normpath(path)])

    def test_87_the_library_jump_lands_on_the_pane_that_runs(self):
        """`Use in Batch Operations` used to raise AttributeError on the way.

        It switched Pre-Processing to a sub-tab through a `tab_widget` that pane never
        had. The jump now walks to Automation's own batch tab, which is the one with the
        batch loop, the contract suite and the real actions behind it.
        """
        from PyQt6.QtWidgets import QLabel, QTabWidget
        from src.ui.library_tab import LibraryTab

        class Window:
            pass

        class Jump:
            def __init__(self, window):
                self._window = window

            def window(self):
                return self._window

        class Dialog:
            accepted = False

            def accept(self):
                Dialog.accepted = True

        window = Window()
        window.tab_widget = QTabWidget()
        window.automation_tab = AutomationTab()
        away = QLabel('the tab the user was already on')
        window.tab_widget.addTab(away, 'Library')
        window.tab_widget.addTab(window.automation_tab, 'Automation')
        window.tab_widget.setCurrentWidget(away)
        self.assertIs(window.tab_widget.currentWidget(), away,
                      'a one-tab window proves nothing: the jump has to move something')
        path = self.cube(self.src, 'hero.obj')

        LibraryTab._open_in_batch_operations(Jump(window), path, Dialog())

        self.assertTrue(Dialog.accepted)
        self.assertIs(window.tab_widget.currentWidget(), window.automation_tab)
        self.assertIs(window.automation_tab.automation_tabs.currentWidget(),
                      window.automation_tab.batch_operations_tab)
        self.assertEqual(window.automation_tab.file_types_edit.text(), '.obj')

    def test_88_the_pane_that_claimed_a_batch_is_gone_from_the_app(self):
        """No second batch implementation is left to disagree with the one that runs."""
        for path in (os.path.join('src', 'features', 'smart_batch_processor.py'),
                     os.path.join('src', 'ui', 'smart_batch_processor_ui.py')):
            self.assertFalse(os.path.exists(os.path.join(ROOT, path)),
                             f'{path} is still in the app')
        sources = []
        for folder, _dirs, names in os.walk(os.path.join(ROOT, 'src')):
            for name in names:
                if name.endswith('.py'):
                    with open(os.path.join(folder, name), encoding='utf-8') as handle:
                        sources.append((name, handle.read()))
        for name, text in sources:
            self.assertNotIn('smart_batch_processor', text, f'{name} still imports it')
        with open(os.path.join(ROOT, 'src', 'ui', 'preprocessing_tab.py'),
                  encoding='utf-8') as handle:
            preprocessing = handle.read()
        self.assertNotIn('batch_processor_tab', preprocessing)
        self.assertNotIn('SmartBatchProcessorUI', preprocessing)
        with open(os.path.join(ROOT, 'src', 'ui', 'library_tab.py'),
                  encoding='utf-8') as handle:
            library = handle.read()
        self.assertNotIn('preprocessing_tab.tab_widget', library)
        self.assertNotIn('_open_in_batch_processor', library)
        # Nothing is queued by this app, so nothing may promise a queue.
        self.assertNotIn('Add to Batch Queue', library)


class MeshOperationCase(DirCase):
    """Each 6f action over one real file, with every number read back from the result.

    A batch is only as honest as the call it repeats, and the failure mode this guards
    against is the one the deleted batch pane had: reporting the settings it was asked
    for as if they were the file it produced. So each test below opens the written file
    and compares what is in it to what the action claimed.
    """

    @classmethod
    def setUpClass(cls):
        ActionRegistry.register_default_actions()

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_6f_mesh_')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.out = os.path.join(self.work, 'out')
        os.makedirs(self.out)

    def run_action(self, action_id, source, destination, **params):
        return ActionRegistry.execute(action_id, input_file=source,
                                      destination=destination, **params)

    def test_89_every_offered_action_takes_the_file_as_input_file(self):
        for action_id in MESH_IDS:
            self.assertEqual(ActionRegistry.batch_binding(action_id),
                             ('input_file', 'destination'), action_id)

    def test_90_convert_writes_the_format_the_destination_names(self):
        source = self.cube(self.work, 'hero.obj')
        destination = os.path.join(self.out, 'hero.stl')
        outcome = self.run_action('processing.convert_format', source, destination)
        self.assertTrue(outcome['success'], outcome)
        self.assertIn(str(os.path.getsize(destination)), outcome['result'])
        self.assertEqual(self.count(destination), 12, outcome['result'])
        self.assertEqual(outcome['output_path'], destination)

    def test_91_a_conversion_to_the_format_it_already_is_is_refused_by_name(self):
        source = self.cube(self.work, 'hero.obj')
        destination = os.path.join(self.out, 'hero.obj')
        outcome = self.run_action('processing.convert_format', source, destination)
        self.assertFalse(outcome['success'])
        self.assertIn('output_format', outcome['error'])
        self.assertFalse(os.path.exists(destination), 'a refusal still wrote the file')

    def test_92_a_format_parameter_renames_the_destination(self):
        source = self.cube(self.work, 'hero.obj')
        kwargs, why = ActionRegistry.bind_batch_params(
            'processing.convert_format', source, self.out, {'output_format': 'glb'})
        self.assertIsNone(why, why)
        self.assertEqual(kwargs['destination'], os.path.join(self.out, 'hero.glb'))
        # Nothing asked for a format, so the name is kept - and the action then says no
        # to the file that name describes, rather than quietly rewriting it in place.
        kwargs, _why = ActionRegistry.bind_batch_params(
            'processing.convert_format', source, self.out, {})
        self.assertEqual(kwargs['destination'], os.path.join(self.out, 'hero.obj'))
        refused = ActionRegistry.execute('processing.convert_format', **kwargs)
        self.assertFalse(refused['success'], refused)

    def test_93_a_thumbnail_is_named_and_drawn_as_a_png(self):
        self.assertEqual(ActionRegistry.batch_extension('file.thumbnail'), 'png')
        source = self.cube(self.work, 'hero.obj')
        kwargs, why = ActionRegistry.bind_batch_params(
            'file.thumbnail', source, self.out, {})
        self.assertIsNone(why, why)
        self.assertEqual(kwargs['destination'], os.path.join(self.out, 'hero.png'))
        self.assertNotIn('output_format', ActionRegistry.parameter_names('file.thumbnail'))

        outcome = self.run_action('file.thumbnail', source, kwargs['destination'], size=64)
        self.assertTrue(outcome['success'], outcome)
        with open(kwargs['destination'], 'rb') as handle:
            drawn = handle.read()
        self.assertEqual(drawn[:8], b'\x89PNG\r\n\x1a\n', 'not a PNG at all')
        self.assertEqual(struct.unpack('>II', drawn[16:24]), (64, 64),
                         'the image is not the size the action reported')

    def test_94_a_thumbnail_says_no_when_the_file_has_no_mesh_in_it(self):
        source = self.make(self.work, 'empty.obj', '# nothing but a comment\n')
        outcome = self.run_action('file.thumbnail', source,
                           os.path.join(self.out, 'empty.png'), size=64)
        self.assertFalse(outcome['success'])
        self.assertIn('no triangles', outcome['error'])

    def test_95_a_thumbnail_refuses_a_name_or_a_size_it_cannot_draw(self):
        source = self.cube(self.work, 'hero.obj')
        wrong_name = os.path.join(self.out, 'hero.jpg')
        outcome = self.run_action('file.thumbnail', source, wrong_name, size=64)
        self.assertFalse(outcome['success'])
        self.assertIn('.png', outcome['error'])
        self.assertFalse(os.path.exists(wrong_name))
        for size in (4, 9000):
            refused = self.run_action('file.thumbnail', source,
                               os.path.join(self.out, 'hero.png'), size=size)
            self.assertFalse(refused['success'], size)
            self.assertIn('16 and 4096', refused['error'])
            self.assertFalse(os.path.exists(os.path.join(self.out, 'hero.png')), size)

    def test_96_simplify_reports_the_faces_the_written_file_has(self):
        source = self.sphere(self.work, 'ball.obj', subdivisions=3)
        destination = os.path.join(self.out, 'ball.obj')
        original = self.count(source)
        # 197 and not 200: the filter lands on 196 for this mesh, which is the only reason
        # this test can tell "the number the file has" from "the number it was asked for".
        outcome = self.run_action('processing.simplify_to_faces', source, destination,
                           target_faces=197)
        self.assertTrue(outcome['success'], outcome)
        kept = self.count(destination)
        self.assertNotEqual(kept, 197,
                            'this build now lands exactly on the target, so the test can no '
                            'longer separate a measured face count from a requested one')
        self.assertEqual(outcome['output_faces'], kept, outcome['result'])
        self.assertEqual(original, 1280, 'the mesh this test authoring made changed')
        self.assertIn(f'{original} -> {kept}', outcome['result'])
        self.assertLess(kept, original)

    def test_97_simplify_by_ratio_reports_the_faces_the_written_file_has(self):
        source = self.sphere(self.work, 'ball.obj', subdivisions=2)
        destination = os.path.join(self.out, 'ball.obj')
        original = self.count(source)
        outcome = self.run_action('processing.simplify_by_ratio', source, destination, ratio=0.5)
        self.assertTrue(outcome['success'], outcome)
        kept = self.count(destination)
        self.assertEqual(outcome['output_faces'], kept, outcome['result'])
        self.assertIn(str(original), outcome['result'])
        self.assertLess(kept, original)
        self.assertGreater(kept, 0)

    def test_98_repair_leaves_a_mesh_and_lists_the_steps_it_ran(self):
        source = self.sphere(self.work, 'ball.obj', subdivisions=1)
        destination = os.path.join(self.out, 'ball.obj')
        outcome = self.run_action('processing.repair_mesh', source, destination)
        self.assertTrue(outcome['success'], outcome)
        self.assertIn(str(os.path.getsize(destination)), outcome['result'])
        self.assertGreater(self.count(destination), 0, 'the repaired file has no mesh in it')
        for step in outcome['operations']:
            self.assertIn(step, outcome['result'])

    def test_99_weld_reports_the_vertices_the_written_file_lost(self):
        vertices = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        source = os.path.join(self.work, 'doubled.obj')
        trimesh.Trimesh(vertices=vertices, faces=[[0, 2, 3], [1, 2, 3]],
                       process=False).export(source)
        destination = os.path.join(self.out, 'doubled.obj')
        outcome = self.run_action('processing.weld_vertices', source, destination)
        self.assertTrue(outcome['success'], outcome)
        before, after = self.count(source, 'vertices'), self.count(destination, 'vertices')
        self.assertEqual(outcome['removed'], before - after, outcome['result'])
        self.assertLessEqual(after, before)
        self.assertIn('exactly equal vertices', outcome['result'])
        with_threshold = self.run_action('processing.weld_vertices', source,
                                  os.path.join(self.out, 'loose.obj'), threshold=1.0)
        self.assertTrue(with_threshold['success'], with_threshold)
        self.assertIn('within 1.0 of the bounding diagonal', with_threshold['result'])

    def test_100_centering_moves_the_mesh_it_says_it_moved(self):
        source = self.cube(self.work, 'hero.obj', translated=(10.0, 5.0, -2.0))
        destination = os.path.join(self.out, 'hero.obj')
        outcome = self.run_action('processing.center_pivot', source, destination)
        self.assertTrue(outcome['success'], outcome)
        centre = trimesh.load(destination, process=False).centroid
        self.assertTrue(max(abs(value) for value in centre) < 1e-6, centre)
        self.assertIn('10.000', outcome['result'])

    def test_101_normalizing_makes_the_side_it_names_the_length_it_names(self):
        source = self.sphere(self.work, 'ball.obj', subdivisions=1, radius=3.0)
        destination = os.path.join(self.out, 'ball.obj')
        outcome = self.run_action('processing.normalize_size', source, destination, target_size=2.0)
        self.assertTrue(outcome['success'], outcome)
        longest = max(trimesh.load(destination, process=False).bounding_box.extents)
        self.assertAlmostEqual(longest, 2.0, places=6, msg=outcome['result'])
        refused = self.run_action('processing.normalize_size', source,
                           os.path.join(self.out, 'nothing.obj'), target_size=0)
        self.assertFalse(refused['success'])
        self.assertIn('target_size', refused['error'])
        self.assertFalse(os.path.exists(os.path.join(self.out, 'nothing.obj')))

    def test_102_an_unwrap_is_proved_by_the_coordinates_in_the_file(self):
        source = self.cube(self.work, 'hero.obj')
        for method in ('trivial', 'flat_plane'):
            destination = os.path.join(self.out, f'{method}.obj')
            outcome = self.run_action('processing.generate_uvs', source, destination, method=method)
            self.assertTrue(outcome['success'], (method, outcome))
            unwrapped = trimesh.load(destination, process=False)
            self.assertEqual(len(unwrapped.visual.uv), outcome['uv_points'], outcome['result'])
            self.assertGreater(outcome['uv_points'], 0)
            self.assertIn(method, outcome['result'])
        ply = self.run_action('processing.generate_uvs', source, os.path.join(self.out, 'hero.ply'))
        self.assertTrue(ply['success'], ply)

    def test_103_an_unwrap_refuses_a_format_that_cannot_hold_texture_coordinates(self):
        source = self.cube(self.work, 'hero.obj')
        stl = os.path.join(self.out, 'hero.stl')
        outcome = self.run_action('processing.generate_uvs', source, stl)
        self.assertFalse(outcome['success'])
        self.assertIn('.obj or .ply', outcome['error'])
        self.assertFalse(os.path.exists(stl), 'a refused unwrap wrote a file')

    def test_104_an_unwrap_names_the_methods_it_offers(self):
        source = self.cube(self.work, 'hero.obj')
        outcome = self.run_action('processing.generate_uvs', source,
                           os.path.join(self.out, 'hero.obj'), method='atlas')
        self.assertFalse(outcome['success'])
        self.assertIn("'trivial'", outcome['error'])
        self.assertIn("'flat_plane'", outcome['error'])
        self.assertIn("'atlas'", outcome['error'])

    def test_105_a_missing_file_is_named_by_the_action_that_could_not_read_it(self):
        gone = os.path.join(self.work, 'gone.obj')
        for action_id in MESH_IDS:
            outcome = self.run_action(action_id, gone, os.path.join(self.out, 'hero.out'))
            self.assertFalse(outcome['success'], action_id)
            self.assertIn('gone.obj', outcome['error'], action_id)

    def test_106_a_parameter_the_action_does_not_take_is_refused_before_it_runs(self):
        source = self.cube(self.work, 'hero.obj')
        outcome = ActionRegistry.execute('processing.convert_format', input_file=source,
                                         destination=os.path.join(self.out, 'hero.stl'),
                                         target_faces=500)
        self.assertFalse(outcome['success'])
        self.assertIn('no parameter named', outcome['error'])
        self.assertFalse(os.path.exists(os.path.join(self.out, 'hero.stl')))

    def test_107_the_renderer_says_whether_the_model_reached_the_image(self):
        """The action's verdict is only as good as the renderer's own answer.

        A thumbnail always produces a PNG - the fallback draws a wireframe badge when
        there is nothing to read - so `rendered` is the only thing that keeps a badge
        from being reported as the asset.
        """
        from src.utils.thumbnail_renderer import generate_3d_thumbnail

        drawn = generate_3d_thumbnail(self.cube(self.work, 'hero.obj'),
                                      os.path.join(self.out, 'hero.png'), size=64)
        self.assertTrue(drawn['success'], drawn)
        self.assertTrue(drawn['rendered'], drawn)
        self.assertEqual(drawn['error'], '', drawn)

        badge = generate_3d_thumbnail(self.make(self.work, 'empty.obj', '# nothing\n'),
                                      os.path.join(self.out, 'empty.png'), size=64)
        self.assertTrue(badge['success'], badge)
        self.assertFalse(badge['rendered'], badge)
        self.assertIn('holds no triangle mesh', badge['error'])

    def test_108_a_dense_mesh_still_gives_a_picture_of_itself(self):
        """The thumbnail pass thins a heavy mesh before drawing it.

        `simplify_quadric_decimation`'s first positional argument is a *percentage*, not
        a face count, and 2500% is not a thing - so the count has to be passed by name or
        the densest models are the ones that stop drawing.
        """
        from src.utils.thumbnail_renderer import generate_3d_thumbnail

        dense = self.sphere(self.work, 'ball.obj', subdivisions=5)
        self.assertGreater(self.count(dense), 2500, 'this test lost its dense mesh')
        outcome = generate_3d_thumbnail(dense, os.path.join(self.out, 'ball.png'), size=128)
        self.assertTrue(outcome['success'], outcome)
        self.assertTrue(outcome['rendered'], outcome)
        self.assertGreater(outcome['faces'], 0,
                           'the verdict claims a picture with no triangles in it')
        self.assertLessEqual(outcome['faces'], 2500,
                             f"the picture was made from {outcome['faces']} triangles, so the "
                             "dense-mesh pass never ran and the heaviest models are drawn whole")
        self.assertIn('triangles drawn',
                      self.run_action('file.thumbnail', dense,
                                      os.path.join(self.out, 'action.png'),
                                      size=128)['result'])
        self.assertEqual(struct.unpack('>II', open(os.path.join(self.out, 'ball.png'),
                                                   'rb').read()[16:24]), (128, 128))

    def test_109_the_drawing_function_refuses_a_canvas_it_cannot_allocate(self):
        """The renderer keeps its own size bound, so a bad number cannot kill the app.

        QImage of a size Qt cannot give, followed by a QPainter on it, is a process abort
        (exit 0xc0000409) rather than a Python error - so the bound that protects the
        batch's policy sentence is not enough on its own, and this is the test that says
        the drawing function will not be handed a canvas it has to fail on.
        """
        from src.utils.thumbnail_renderer import generate_3d_thumbnail

        source = self.cube(self.work, 'hero.obj')
        destination = os.path.join(self.out, 'hero.png')
        for size in (8, 'large'):
            outcome = generate_3d_thumbnail(source, destination, size=size)
            self.assertFalse(outcome['success'], size)
            self.assertFalse(outcome['rendered'], size)
            self.assertIn(str(size) if isinstance(size, int) else 'number of pixels',
                          outcome['error'])
            self.assertFalse(os.path.exists(destination), f'{size} still wrote a file')


if __name__ == '__main__':
    unittest.main(verbosity=2)
