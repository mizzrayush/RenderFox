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

Run: python -X utf8 tests/test_automation_batch_contract.py
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

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

BATCH_IDS = ['file.copy', 'file.delete', 'file.move', 'processing.generate_lod',
             'system.run_command']


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
