"""Phase 6e contract: the Monitor pane reports what the engine is really doing.

What this suite exists to keep out of the app:

  * The pane opened with six invented activity lines and then called `.clear()` on the
    list in the same breath - a decoration that proved nothing.
  * Active Processes had three hardcoded rows (WF001 Model Conversion Pipeline at 65%,
    BT002, TS003) that no engine ever produced, and Refresh, Kill Process and Details
    were built with no connect at all.
  * The Performance tab was four fixed strings - CPU 45%, Memory 2.1 GB, Disk I/O
    15 MB/s, Active Threads 8 - plus a label saying charts "would be displayed here".
  * Errors & Warnings claimed "Errors: 2 / Warnings: 5" over a log pre-filled with seven
    invented failures, and Clear Log and Export Log were dead buttons.
  * The Completed Today card was created and never written to: `update_dashboard_metrics`
    updated three of the four cards and left that one on its initial "0" forever.
  * `BatchProcessor.current_batch` was created with `done: 0` and `done` was never
    advanced, so an outside reader saw a run that could not progress.
  * `Workflow` had no start time at all, so a row for a running workflow could not say
    when it began, and nothing in the app ever counted a finished run.
  * `closeEvent` asked only about render jobs and never stopped the automation engine, so
    closing the window cut a batch mid-file and left the scheduler polling.

Run: python -X utf8 tests/test_automation_monitor_contract.py
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import types
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
import psutil

from src.features import automation_engine as engine_module
from src.features.automation_engine import (
    ActionRegistry, AutomationEngine, AutomationTask, BatchProcessor, TaskStatus,
    Workflow, WorkflowStep)
from src.ui import automation_tab as tab_module
from src.ui.automation_tab import AutomationTab

APP = QApplication.instance() or QApplication([])

PANE_SOURCE = open(os.path.join(ROOT, 'src', 'ui', 'automation_tab.py'),
                   encoding='utf-8').read()
MAIN_SOURCE = open(os.path.join(ROOT, 'src', 'ui', 'main_window.py'),
                   encoding='utf-8').read()

_DEFAULT = object()

SLOT_FAULTS = []


def _keep_slot_fault(kind, value, trace):
    """PyQt6 aborts the process on an exception raised inside a slot, so a defect that
    bites there would kill the run before unittest printed a single FAIL line. Keep the
    fault instead and let the test that was running report it by name."""
    SLOT_FAULTS.append(''.join(traceback.format_exception(kind, value, trace)))


sys.excepthook = _keep_slot_fault


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


class WatchedCase(unittest.TestCase):
    """Fails the test that was running for any exception a Qt slot was about to swallow."""

    def setUp(self):
        del SLOT_FAULTS[:]
        self.addCleanup(self.report_slot_faults)
        super().setUp()

    def report_slot_faults(self):
        faults = list(SLOT_FAULTS)
        del SLOT_FAULTS[:]
        if faults:
            self.fail('an exception escaped into a Qt slot instead of failing here:\n%s'
                      % '\n'.join(faults))


class PaneHome(WatchedCase):
    """One pane, one private app-data folder, dialogs recorded instead of shown."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix='renderfox_6e_home_')
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
        super().setUp()
        for name in os.listdir(self.home):
            path = os.path.join(self.home, name)
            if os.path.isfile(path):
                os.remove(path)
        self.src = os.path.join(self.home, 'src_files')
        self.out = os.path.join(self.home, 'out_files')
        os.makedirs(self.src, exist_ok=True)
        os.makedirs(self.out, exist_ok=True)
        self.popups.clear()
        self.tab = AutomationTab()
        self.engine = self.tab.automation_engine
        self.addCleanup(self.tab.automation_engine.stop)

    def popup_text(self):
        return ' | '.join(str(one[1]) for one in self.popups)

    def dialogs(self, kind):
        return [one for one in self.popups if one[0] == kind]

    def activity_lines(self):
        return [self.tab.activity_list.item(index).text()
                for index in range(self.tab.activity_list.count())]

    def problem_lines(self):
        text = self.tab.error_log_display.toPlainText()
        return text.splitlines() if text else []

    def cells(self, row):
        return [self.tab.processes_table.item(row, column).text()
                for column in range(6)]

    def make(self, name):
        return self.write(self.home, name)

    def write(self, folder, name):
        path = os.path.join(folder, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('v 0 0 0\n')
        return path

    def spin(self, want, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            APP.processEvents()
            if want():
                return True
            time.sleep(0.02)
        return False

    def wait_for_batch(self):
        self.assertTrue(self.spin(lambda: not self.engine.batch_processor.is_processing),
                        'the batch never reported')

    def instrument(self, process=None, counters=_DEFAULT):
        """Point the pane at a process and a disk that answer exactly like psutil."""
        real = tab_module.psutil
        used = FakeProcess() if process is None else process
        held = FakeCounters(1024 * 1024, 0) if counters is _DEFAULT else counters
        tab_module.psutil = FakePsutil(used, held)
        self.addCleanup(setattr, tab_module, 'psutil', real)
        self.tab._ps_process = used

    def point_at_folder_copy(self, operation='file.copy'):
        """The batch tab aimed at a folder of .obj files, copying into self.out."""
        self.tab.source_type_combo.setCurrentText('Folder')
        for row in range(self.tab.operation_combo.count()):
            if self.tab.operation_combo.itemData(row) == operation:
                self.tab.operation_combo.setCurrentIndex(row)
                break
        else:
            raise AssertionError('%s is not offered' % operation)
        self.tab.source_path_edit.setText(self.src)
        self.tab.output_path_edit.setText(self.out)
        self.tab.file_types_edit.setText('obj')
        self.tab.overwrite_cb.setChecked(False)
        self.tab.backup_cb.setChecked(False)
        self.tab._update_batch_controls()

    def save_as(self, path):
        previous = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (path, 'Text files (*.txt)'))
        self.addCleanup(setattr, QFileDialog, 'getSaveFileName', previous)

    def add_workflow(self, name, status, steps=2, started_at=None, current=0):
        workflow = Workflow(name)
        workflow.steps = [WorkflowStep('step%d' % index, 'file.delete',
                                       {'path': 'p%d' % index})
                          for index in range(steps)]
        workflow.status = status
        workflow.started_at = started_at
        workflow.current_step = current
        self.engine.workflows[workflow.workflow_id] = workflow
        return workflow

    def add_task(self, task_id, name, **fields):
        task = AutomationTask(task_id, name=name, task_type='file.delete',
                              parameters={'path': 'gone'})
        for key, value in fields.items():
            setattr(task, key, value)
        self.engine.tasks[task_id] = task
        return task

    def live_batch(self, **fields):
        batch = {'total': 4, 'done': 2, 'item': 'hero.obj', 'started_at': time.time()}
        batch.update(fields)
        self.engine.batch_processor.current_batch = batch
        return batch


class NothingInventedCase(PaneHome):
    """The pane must open with nothing in it that the engine did not produce."""

    def test_01_the_activity_list_starts_empty(self):
        self.assertEqual(self.tab.activity_list.count(), 0,
                         'the list opened with lines no run ever wrote')

    def test_02_the_processes_table_starts_with_no_rows(self):
        self.assertEqual(self.tab.processes_table.rowCount(), 0)
        self.assertEqual(self.tab._process_keys, [])

    def test_03_no_metric_label_is_born_with_a_number(self):
        for name in ('cpu_usage_label', 'memory_usage_label', 'disk_io_label',
                     'active_threads_label'):
            line = [one for one in PANE_SOURCE.split('\n')
                    if 'self.%s = QLabel(' % name in one]
            self.assertEqual(len(line), 1, name)
            self.assertFalse(any(ch.isdigit() for ch in line[0]), line[0])

    def test_04_the_error_log_starts_empty_and_counts_zero(self):
        self.assertEqual(self.tab.error_log_display.toPlainText(), '')
        self.assertEqual(self.tab.errors_count_label.text(), 'Errors: 0')
        self.assertEqual(self.tab.warnings_count_label.text(), 'Warnings: 0')
        self.assertEqual(self.tab._problems, [])

    def test_05_no_invented_string_survives_in_the_pane_source(self):
        for ghost in ('WF001', 'BT002', 'TS003', 'Model Conversion Pipeline',
                      'Daily Backup', 'building.obj', 'CPU Usage: 45%', '2.1 GB',
                      '15 MB/s', 'Active Threads: 8', 'Errors: 2', 'Warnings: 5',
                      'would be displayed here', '14:30:15', 'recent_activities',
                      'sample_processes'):
            self.assertNotIn(ghost, PANE_SOURCE, ghost)

    def test_06_every_monitor_control_reaches_a_handler(self):
        for name in ('refresh_processes_btn', 'kill_process_btn', 'process_details_btn',
                     'clear_log_btn', 'export_log_btn'):
            button = getattr(self.tab, name)
            self.assertGreater(button.receivers(button.clicked), 0, name)

    def test_07_the_dashboard_has_no_hasattr_escape_hatches(self):
        block = PANE_SOURCE[PANE_SOURCE.index('def update_dashboard_metrics'):]
        self.assertNotIn('hasattr', block,
                         'a guarded card can silently stop being written')


class StatusCardsCase(PaneHome):
    """Each card names the state it is really reading."""

    def test_08_active_workflows_counts_what_the_engine_says_is_running(self):
        self.add_workflow('Alpha', TaskStatus.RUNNING)
        self.add_workflow('Beta', TaskStatus.COMPLETED)
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.active_workflows_label.text(), '1')

    def test_09_a_workflow_the_engine_has_never_run_is_not_an_active_one(self):
        self.add_workflow('Ghost', TaskStatus.PENDING)
        self.add_workflow('Also Idle', TaskStatus.FAILED)
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.active_workflows_label.text(), '0',
                         'the card counted runs the engine never started')

    def test_10_scheduled_tasks_counts_schedules_not_every_task(self):
        self.add_task('t-sched', 'Nightly', schedule_time='daily at 03:00')
        self.add_task('t-plain', 'Once')
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.scheduled_tasks_label.text(), '1')

    def test_11_file_watchers_counts_the_folders_actually_watched(self):
        folder = tempfile.mkdtemp(prefix='renderfox_6e_watch_')
        self.addCleanup(shutil.rmtree, folder, True)
        before = len(self.tab.file_watcher.watched_directories)
        self.tab.file_watcher.watch_directory(folder, lambda path: None)
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.file_watchers_label.text(), str(before + 1))

    def test_12_completed_today_reads_the_engines_counter(self):
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.completed_today_label.text(), '0')
        self.engine._note_finished(True)
        self.engine._note_finished(False)
        self.engine._note_finished(True)
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.completed_today_label.text(), '2',
                         'a run that failed is not one that completed')

    def test_13_yesterdays_counter_is_not_todays(self):
        self.engine._stats = {'date': '2001-01-01', 'completed': 7, 'failed': 0}
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.completed_today_label.text(), '0')


class LiveBatchCase(WatchedCase):
    """The engine's own record of the batch in progress, which the Monitor reads."""

    def collect(self, processor):
        seen = []
        processor.progress_updated.connect(
            lambda current, total, name: seen.append(dict(processor.current_batch)))
        return seen

    def test_14_the_record_counts_each_file_as_it_finishes(self):
        processor = BatchProcessor()
        seen = self.collect(processor)
        results = processor.process_batch(['a', 'b', 'c'], lambda one: {'success': True})
        self.assertEqual([entry['done'] for entry in seen], [0, 1, 2])
        self.assertEqual([entry['item'] for entry in seen], ['a', 'b', 'c'])
        self.assertEqual([entry['total'] for entry in seen], [3, 3, 3])
        self.assertEqual(len(results), 3)
        self.assertIsInstance(seen[0]['started_at'], float)

    def test_15_a_refused_file_still_counts_as_a_file_that_ran(self):
        processor = BatchProcessor()
        seen = self.collect(processor)
        processor.process_batch(['a', 'b'], lambda one: {'success': False, 'error': 'no'})
        self.assertEqual(seen[-1]['done'], 1)
        self.assertEqual(seen[-1]['item'], 'b')

    def test_16_the_record_is_gone_once_the_run_is_over(self):
        processor = BatchProcessor()
        self.collect(processor)
        processor.process_batch(['a'], lambda one: {'success': True})
        self.assertIsNone(processor.current_batch)

    def test_17_a_stopped_batch_stops_counting_at_the_file_it_reached(self):
        processor = BatchProcessor()
        seen = self.collect(processor)

        def stop_after_second(item):
            if item == 'b':
                processor.request_stop()
            return {'success': True}

        results = processor.process_batch(['a', 'b', 'c'], stop_after_second)
        self.assertEqual(len(results), 2)
        self.assertEqual([entry['done'] for entry in seen], [0, 1])
        self.assertEqual([entry['item'] for entry in seen], ['a', 'b'])


class ProcessRowsCase(PaneHome):
    """Active Processes lists only runs the engine says are happening."""

    def cells(self, row):
        return [self.tab.processes_table.item(row, column).text()
                for column in range(6)]

    def test_18_only_a_running_workflow_gets_a_row(self):
        running = self.add_workflow('Alpha', TaskStatus.RUNNING, steps=3, current=1,
                                    started_at=100.0)
        self.add_workflow('Beta', TaskStatus.COMPLETED, started_at=50.0)
        self.tab.rebuild_process_table()
        self.assertEqual(self.tab.processes_table.rowCount(), 1)
        self.assertEqual(self.cells(0)[:4],
                         [running.workflow_id[:8], 'Alpha', '1/3', 'Running'])

    def test_19_the_batch_row_shows_the_files_the_processor_counted(self):
        self.live_batch(total=7, done=3, item='ship.fbx', started_at=200.0)
        self.tab.rebuild_process_table()
        self.assertEqual(self.cells(0)[1:4], ['Batch', '3/7', 'Running'])
        self.assertEqual(self.cells(0)[4],
                         time.strftime('%H:%M:%S', time.localtime(200.0)))

    def test_20_a_paused_batch_is_named_as_paused(self):
        self.live_batch()
        self.engine.batch_processor.set_paused(True)
        self.addCleanup(self.engine.batch_processor.set_paused, False)
        self.tab.rebuild_process_table()
        self.assertEqual(self.cells(0)[3], 'Paused')

    def test_21_a_running_task_gets_a_row(self):
        self.add_task('t-run', 'Nightly', status=TaskStatus.RUNNING, started_at=300.0)
        self.tab.rebuild_process_table()
        self.assertEqual(self.cells(0)[1:4], ['Nightly', '0/1', 'Running'])

    def test_22_rows_are_ordered_by_the_time_each_run_started(self):
        self.add_workflow('Late', TaskStatus.RUNNING, started_at=300.0)
        self.add_task('t-early', 'Early', status=TaskStatus.RUNNING, started_at=100.0)
        self.live_batch(started_at=200.0)
        self.tab.rebuild_process_table()
        self.assertEqual([one.split(':')[0] for one in self.tab._process_keys],
                         ['task', 'batch', 'workflow'])

    def test_23_a_run_that_already_ended_loses_its_row(self):
        self.add_workflow('Done', TaskStatus.COMPLETED, started_at=100.0)
        self.tab.rebuild_process_table()
        self.assertEqual(self.tab.processes_table.rowCount(), 0)
        self.assertEqual(self.tab._process_keys, [])

    def test_24_rebuild_keeps_the_row_you_had_chosen(self):
        first = self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=900.0)
        self.tab.rebuild_process_table()
        self.tab.processes_table.setCurrentCell(0, 0)
        self.add_workflow('Zulu', TaskStatus.RUNNING, started_at=200.0)
        self.tab.rebuild_process_table()
        chosen = self.tab.processes_table.currentRow()
        self.assertGreaterEqual(chosen, 0, 'the rebuild dropped the row you had chosen')
        self.assertEqual(self.tab._process_keys[chosen], 'workflow:' + first.workflow_id)

    def test_25_refresh_rebuilds_from_what_the_engine_says_now(self):
        self.tab.refresh_processes_btn.click()
        self.assertEqual(self.tab.processes_table.rowCount(), 0)
        self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=100.0)
        self.tab.refresh_processes_btn.click()
        self.assertEqual(self.tab.processes_table.rowCount(), 1)


class PaceCase(unittest.TestCase):
    """The Started and ETA columns, from the run's own numbers."""

    def row(self, **fields):
        record = {'done': 1, 'total': 4, 'started_at': 100.0}
        record.update(fields)
        return record

    def test_26_the_pace_is_unknown_until_a_unit_finishes(self):
        self.assertEqual(AutomationTab._eta_text(self.row(done=0), now=160.0), 'unknown')

    def test_27_the_pace_is_unknown_without_a_start(self):
        self.assertEqual(AutomationTab._eta_text(self.row(started_at=None), now=160.0),
                         'unknown')

    def test_28_the_runs_own_pace_sets_the_estimate(self):
        record = self.row(done=2, total=4, started_at=100.0)
        self.assertEqual(AutomationTab._eta_text(record, now=110.0), '0m 10s left')

    def test_29_a_run_past_its_last_unit_is_called_finishing(self):
        self.assertEqual(AutomationTab._eta_text(self.row(done=4, total=4), now=160.0),
                         'finishing')

    def test_30_the_started_column_shows_the_recorded_moment(self):
        self.assertEqual(AutomationTab._started_text(200.0),
                         time.strftime('%H:%M:%S', time.localtime(200.0)))
        self.assertEqual(AutomationTab._started_text(None), 'unknown')


class KillCase(PaneHome):
    """Kill Process stops the run really selected, or says why it will not."""

    def select(self, index=0):
        self.tab.rebuild_process_table()
        self.assertGreater(self.tab.processes_table.rowCount(), index,
                           'the run never got a row to select')
        self.tab.processes_table.setCurrentCell(index, 0)

    def test_31_kill_with_nothing_running_says_there_is_nothing_to_stop(self):
        self.tab.kill_process_btn.click()
        self.assertEqual(len(self.dialogs('information')), 1)
        self.assertIn('Nothing is running', self.popup_text())
        self.assertFalse(self.engine._stopped)
        self.assertFalse(self.engine.batch_processor._stop)

    def test_32_kill_asks_the_engine_to_stop_the_selected_workflow(self):
        workflow = self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=100.0)
        self.select()
        self.tab.kill_process_btn.click()
        self.assertIn(workflow.workflow_id, self.engine._stopped)
        self.assertIn("Stop asked for 'Alpha' - the step in hand finishes first",
                      ' '.join(self.activity_lines()))

    def test_33_kill_asks_the_processor_to_stop_a_running_batch(self):
        self.live_batch()
        self.engine.batch_processor.is_processing = True
        self.select()
        self.tab.kill_process_btn.click()
        self.assertTrue(self.engine.batch_processor._stop)
        self.assertIn('Stop asked for', ' '.join(self.activity_lines()))

    def test_34_a_paused_batch_is_still_stoppable(self):
        self.live_batch()
        processor = self.engine.batch_processor
        processor.is_processing = True
        processor.set_paused(True)
        self.select()
        self.tab.kill_process_btn.click()
        self.assertTrue(processor._stop)
        self.assertFalse(processor.is_paused)

    def test_35_killing_a_task_is_refused_and_says_why(self):
        self.add_task('t1', 'Nightly', status=TaskStatus.RUNNING, started_at=100.0)
        self.select()
        self.tab.kill_process_btn.click()
        self.assertEqual(len(self.dialogs('warning')), 1)
        self.assertIn('cannot be cancelled', self.popup_text())
        self.assertFalse(self.engine.batch_processor._stop)
        self.assertFalse(self.engine._stopped)

    def test_36_a_run_that_ended_first_is_reported_as_already_finished(self):
        self.live_batch()
        self.engine.batch_processor.is_processing = False
        self.select()
        self.tab.kill_process_btn.click()
        self.assertIn('had already finished when the click landed', self.popup_text())
        self.assertEqual(self.activity_lines(), [])

    def test_37_kill_refreshes_the_table_it_just_changed(self):
        self.live_batch()
        self.engine.batch_processor.is_processing = True
        self.select()
        self.tab.kill_process_btn.click()
        self.assertEqual(len(self.tab._process_keys),
                         self.tab.processes_table.rowCount())


class DetailsCase(PaneHome):
    """Details reports the run's own numbers, including the ones it does not have."""

    def show(self, index=0):
        self.tab.rebuild_process_table()
        self.assertGreater(self.tab.processes_table.rowCount(), index,
                           'the run never got a row')
        self.tab.processes_table.setCurrentCell(index, 0)
        self.popups.clear()
        self.tab.process_details_btn.click()
        self.assertEqual(len(self.dialogs('information')), 1, 'Details showed no dialog')
        return str(self.dialogs('information')[-1][1])

    def test_38_details_with_no_selection_says_so(self):
        self.tab.process_details_btn.click()
        self.assertIn('No run is selected', self.popup_text())

    def test_39_a_workflow_is_named_and_its_steps_are_counted(self):
        workflow = self.add_workflow('Alpha', TaskStatus.RUNNING, steps=3,
                                     started_at=200.0, current=1)
        text = self.show()
        self.assertIn('Name: Alpha', text)
        self.assertIn('Kind: workflow', text)
        self.assertIn('Id: %s' % workflow.workflow_id, text)
        self.assertIn('Finished: 1 of 3', text)
        self.assertIn('Started: %s'
                      % time.strftime('%H:%M:%S', time.localtime(200.0)), text)
        self.assertIn('Estimated finish: ', text)

    def test_40_a_batch_shows_the_file_it_is_holding(self):
        self.live_batch(item='big.obj', done=3, total=5)
        text = self.show()
        self.assertIn('In hand: big.obj', text)
        self.assertIn('Finished: 3 of 5', text)
        self.assertIn('Kind: batch', text)

    def test_41_a_paused_batch_is_reported_as_paused(self):
        self.live_batch()
        self.engine.batch_processor.set_paused(True)
        self.assertIn('Status: Paused', self.show())

    def test_42_a_task_says_its_stop_is_not_there(self):
        self.add_task('t1', 'Nightly', status=TaskStatus.RUNNING, started_at=100.0)
        text = self.show()
        self.assertIn('Stop: ', text)
        self.assertIn('cannot be cancelled here', text)
        self.assertIn('In hand: file.delete', text)

    def test_43_a_run_that_recorded_no_start_says_unknown(self):
        self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=None)
        self.assertIn('Started: unknown', self.show())

    def test_44_details_reports_only_the_selected_row(self):
        self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=100.0)
        self.add_workflow('Zulu', TaskStatus.RUNNING, started_at=900.0)
        text = self.show(1)
        self.assertIn('Name: Zulu', text)
        self.assertNotIn('Name: Alpha', text)


class FakeCounters:
    """What psutil.disk_io_counters answers with, to the byte."""

    def __init__(self, read_bytes=0, write_bytes=0):
        self.read_bytes = read_bytes
        self.write_bytes = write_bytes


class FakeProcess:
    """The two numbers the pane asks a process for."""

    def __init__(self, cpu=12.5, rss=200 * 1024 * 1024):
        self.cpu_value = cpu
        self.rss_value = rss

    def cpu_percent(self, interval=None):
        return self.cpu_value

    def memory_info(self):
        return types.SimpleNamespace(rss=self.rss_value)


class ExplodingProcess(FakeProcess):
    def cpu_percent(self, interval=None):
        raise psutil.Error('no counters on this machine')


class FakePsutil:
    Error = psutil.Error

    def __init__(self, process, counters):
        self.the_process = process
        self.the_counters = counters

    def Process(self):
        return self.the_process

    def disk_io_counters(self):
        return self.the_counters


class MetricsCase(PaneHome):
    """The Performance labels are psutil's own numbers, or a sentence saying there are none."""

    def test_45_the_first_cpu_poll_admits_it_has_no_number_yet(self):
        self.instrument()
        self.tab._cpu_measured = False
        self.tab.refresh_metrics()
        self.assertEqual(self.tab.cpu_usage_label.text(), "This app's CPU: measuring")
        self.tab.refresh_metrics()
        self.assertEqual(self.tab.cpu_usage_label.text(),
                         "This app's CPU: 12.5% of one core")

    def test_46_memory_is_the_processors_own_resident_bytes(self):
        self.instrument(FakeProcess(rss=200 * 1024 * 1024))
        self.tab.refresh_metrics()
        self.assertEqual(self.tab.memory_usage_label.text(), "This app's memory: 200.0 MB")

    def test_47_threads_are_the_ones_python_says_are_alive(self):
        self.instrument()
        self.tab.refresh_metrics()
        self.assertEqual(self.tab.active_threads_label.text(),
                         'Threads alive: %d' % threading.active_count())

    def test_48_disk_traffic_needs_two_samples_before_it_claims_a_rate(self):
        self.instrument(counters=FakeCounters(1024 * 1024, 0))
        self.tab._io_sample = None
        self.assertEqual(self.tab._disk_traffic_text(), 'Disk traffic: measuring')

    def test_49_the_rate_is_the_bytes_moved_since_the_last_sample(self):
        self.instrument(counters=FakeCounters(2 * 1024 * 1024, 0))
        self.tab._io_sample = (0, time.time() - 2.0)
        text = self.tab._disk_traffic_text()
        self.assertIn('MB/s', text)
        rate = float(text.split(': ')[1].split()[0])
        self.assertAlmostEqual(rate, 1.0, delta=0.2)

    def test_50_a_counter_that_never_went_backwards_is_not_called_traffic(self):
        self.instrument(counters=FakeCounters(0, 0))
        self.tab._io_sample = (1024 * 1024, time.time() - 1.0)
        text = self.tab._disk_traffic_text()
        self.assertEqual(text, 'Disk traffic: 0.00 MB/s')

    def test_51_a_system_that_reports_no_disk_counters_says_so(self):
        self.instrument(counters=None)
        self.assertEqual(self.tab._disk_traffic_text(),
                         'Disk traffic: not reported by this system')

    def test_52_a_failed_read_is_named_a_failed_read(self):
        self.instrument(ExplodingProcess())
        self.tab.refresh_metrics()
        self.assertIn('could not be read', self.tab.cpu_usage_label.text())
        self.assertIn('could not be read', self.tab.memory_usage_label.text())
        self.assertIn('could not be counted', self.tab.active_threads_label.text())
        self.assertIn('could not be read', self.tab.disk_io_label.text())

    def test_53_no_label_is_left_on_the_words_it_was_born_with(self):
        self.instrument()
        self.tab.refresh_metrics()
        texts = [one.text() for one in (self.tab.cpu_usage_label,
                                        self.tab.memory_usage_label,
                                        self.tab.active_threads_label,
                                        self.tab.disk_io_label)]
        for text in texts:
            self.assertNotIn('not measured yet', text)
            self.assertNotIn('not counted yet', text)


class ProblemsCase(PaneHome):
    """Errors & Warnings is what the runs reported, counted from that same list."""

    def test_54_a_recorded_problem_shows_in_the_log_and_both_counts(self):
        self.tab._record_problem('ERROR', 'demo: it broke')
        self.assertEqual(len(self.problem_lines()), 1)
        self.assertTrue(self.problem_lines()[0].endswith('ERROR: demo: it broke'))
        self.assertEqual(self.tab.errors_count_label.text(), 'Errors: 1')
        self.assertEqual(self.tab.warnings_count_label.text(), 'Warnings: 0')

    def test_55_the_counts_are_read_from_the_same_list_the_log_renders(self):
        for level, message in (('ERROR', 'a'), ('ERROR', 'b'), ('WARNING', 'c')):
            self.tab._record_problem(level, message)
        self.assertEqual(len(self.problem_lines()), 3)
        self.assertEqual(self.tab.errors_count_label.text(), 'Errors: 2')
        self.assertEqual(self.tab.warnings_count_label.text(), 'Warnings: 1')

    def test_56_a_failed_workflow_reaches_the_log(self):
        workflow = self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=100.0)
        self.tab.on_workflow_failed(workflow.workflow_id, 'step 2 has no action')
        self.assertIn("workflow 'Alpha' failed: step 2 has no action",
                      ' '.join(self.problem_lines()))
        self.assertEqual(self.tab.errors_count_label.text(), 'Errors: 1')

    def test_57_a_failed_task_reaches_the_log(self):
        self.add_task('t1', 'Nightly')
        self.tab.on_task_completed('t1', False, {'error': 'the file was not there'})
        self.assertIn("task 'Nightly' failed: the file was not there",
                      ' '.join(self.problem_lines()))

    def test_58_a_failed_batch_file_is_named_in_the_log(self):
        summary = {'results': [{'item': os.path.join('dir', 'a.obj'), 'success': False,
                                'error': 'disk full'},
                               {'item': 'b.obj', 'success': True, 'result': 'copied'}],
                   'total': 2, 'ran': 2, 'succeeded': 1, 'failed': 1,
                   'not_run': 0, 'stopped': False}
        self.tab.on_batch_completed_engine(summary)
        self.assertIn('batch: a.obj - disk full', ' '.join(self.problem_lines()))
        self.assertEqual(self.tab.errors_count_label.text(), 'Errors: 1')

    def test_59_files_that_never_ran_are_warned_about(self):
        summary = {'results': [], 'total': 3, 'ran': 0, 'succeeded': 0,
                   'failed': 0, 'not_run': 3, 'stopped': True}
        self.tab.on_batch_completed_engine(summary)
        self.assertIn('batch: 3 file(s) never ran', ' '.join(self.problem_lines()))
        self.assertEqual(self.tab.warnings_count_label.text(), 'Warnings: 1')

    def test_60_a_batch_refused_over_the_blocked_files_is_warned_about(self):
        for name in ('a.obj', 'b.obj'):
            self.write(self.src, name)
        self.write(self.out, 'a.obj')
        self.point_at_folder_copy()
        self.tab.start_batch_operation()
        self.assertIn('batch not started: 1 of 2 file(s) cannot run',
                      ' '.join(self.problem_lines()))
        self.assertFalse(self.engine.batch_processor.is_processing,
                         'a blocked batch must not start halfway')

    def test_61_a_failed_auto_action_reaches_the_log(self):
        self.tab.on_auto_actions_finished('hero.obj', ['validate - failed: no normals'])
        self.assertIn('watched file: validate - failed: no normals',
                      ' '.join(self.problem_lines()))

    def test_62_clear_log_empties_the_text_and_resets_both_counts(self):
        self.tab._record_problem('ERROR', 'a')
        self.tab._record_problem('WARNING', 'b')
        self.tab.clear_log_btn.click()
        self.assertEqual(self.tab.error_log_display.toPlainText(), '')
        self.assertEqual(self.tab.errors_count_label.text(), 'Errors: 0')
        self.assertEqual(self.tab.warnings_count_label.text(), 'Warnings: 0')

    def test_63_export_writes_the_lines_the_log_shows(self):
        self.tab._record_problem('ERROR', 'a')
        self.tab._record_problem('WARNING', 'b')
        path = os.path.join(self.home, 'exported.txt')
        self.save_as(path)
        self.tab.export_log_btn.click()
        with open(path, encoding='utf-8') as handle:
            written = handle.read().splitlines()
        self.assertEqual(written, self.problem_lines())
        self.assertIn('Exported 2 log line(s) to %s' % path,
                      ' '.join(self.activity_lines()))

    def test_64_a_cancelled_export_writes_nothing(self):
        self.tab._record_problem('ERROR', 'a')
        path = os.path.join(self.home, 'never_written.txt')
        previous = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ('', ''))
        self.addCleanup(setattr, QFileDialog, 'getSaveFileName', previous)
        self.tab.export_log_btn.click()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.dialogs('warning'), [], 'a cancel is not a failure')
        self.assertEqual(self.activity_lines(), [])

    def test_65_an_export_that_cannot_be_written_says_so(self):
        self.tab._record_problem('ERROR', 'a')
        self.save_as(self.out)
        self.tab.export_log_btn.click()
        self.assertIn('The log could not be written', self.popup_text())
        self.assertEqual(self.activity_lines(), [])

    def test_66_the_log_keeps_the_last_500_problems(self):
        for index in range(501):
            self.tab._record_problem('ERROR', 'problem %d' % index)
        self.assertEqual(len(self.tab._problems), 500)
        lines = self.problem_lines()
        self.assertEqual(len(lines), 500)
        self.assertIn('ERROR: problem 500', lines[-1])
        self.assertIn('ERROR: problem 1', lines[0])

    def test_67_the_activity_list_keeps_the_last_200_lines(self):
        for index in range(205):
            self.tab._log_activity('line %d' % index)
        self.assertEqual(self.tab.activity_list.count(), 200)
        self.assertIn('line 204', self.activity_lines()[-1])
        self.assertIn('line 5', self.activity_lines()[0])


class ShutdownCase(PaneHome):
    """Closing the window cannot cut a run the engine is still doing."""

    def test_68_live_work_is_empty_when_nothing_runs(self):
        self.assertEqual(self.engine.live_work(), [])

    def test_69_live_work_names_each_kind_of_run_a_close_would_cut(self):
        self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=100.0)
        self.add_workflow('Idle', TaskStatus.PENDING)
        self.add_task('t1', 'Nightly', status=TaskStatus.RUNNING, started_at=100.0)
        self.engine.batch_processor.is_processing = True
        self.assertEqual(sorted(self.engine.live_work()),
                         sorted(["workflow 'Alpha'", "task 'Nightly'",
                                 'a batch of files']))

    def test_70_a_run_that_ended_is_no_longer_live_work(self):
        self.add_workflow('Alpha', TaskStatus.COMPLETED)
        self.add_task('t1', 'Nightly', status=TaskStatus.FAILED)
        self.assertEqual(self.engine.live_work(), [])

    def test_71_the_close_path_learns_what_runs_before_it_stops_the_engine(self):
        body = MAIN_SOURCE[MAIN_SOURCE.index('def closeEvent'):]
        self.assertIn('self.automation_tab.automation_engine', body)
        self.assertLess(body.index('engine.live_work()'), body.index('engine.stop()'),
                        'a close must ask what is running before cutting it short')
        self.assertIn('event.ignore()', body[:body.index('engine.stop()')],
                      'a refused close has to ignore the event')

    def test_72_a_finished_run_leaves_no_live_work_and_one_completed_count(self):
        path = self.make('a.obj')
        self.assertTrue(self.engine.run_batch([path],
                                              lambda item: {'success': True,
                                                            'result': 'copied'}))
        self.wait_for_batch()
        self.assertEqual(self.engine.live_work(), [])
        self.assertEqual(self.engine.completed_today, 1)

    def test_73_a_run_that_failed_every_file_is_not_counted_as_completed(self):
        self.assertTrue(self.engine.run_batch(['missing.obj'],
                                              lambda item: {'success': False,
                                                            'error': 'no disk'}))
        self.wait_for_batch()
        self.assertEqual(self.engine.completed_today, 0)


class RunCountersCase(PaneHome):
    """Completed Today counts runs that ended with what they were asked for."""

    def delete_step(self, path):
        return WorkflowStep('sweep', 'file.delete', {'path': path})

    def put_workflow(self, *paths):
        workflow = Workflow('Sweep')
        workflow.steps = [self.delete_step(path) for path in paths]
        self.engine.workflows[workflow.workflow_id] = workflow
        self.assertTrue(self.engine.execute_workflow(workflow.workflow_id))
        return workflow

    def test_74_a_workflow_that_ran_is_one_completed_run(self):
        workflow = self.put_workflow(self.make('hero.obj'))
        self.assertTrue(self.spin(lambda: workflow.status is TaskStatus.COMPLETED),
                        'the workflow never reported a finish')
        self.assertEqual(self.engine.completed_today, 1)

    def test_75_a_workflow_that_failed_is_not_a_completed_run(self):
        workflow = self.put_workflow(os.path.join(self.home, 'never_was.obj'))
        self.assertTrue(self.spin(lambda: workflow.status is TaskStatus.FAILED),
                        'the workflow never reported a failure')
        self.assertEqual(self.engine.completed_today, 0)

    def test_76_a_task_that_ran_is_one_completed_run(self):
        self.add_task('t1', 'Sweep', parameters={'path': self.make('hero.obj')})
        self.assertTrue(self.engine.execute_task('t1'))
        self.assertEqual(self.engine.completed_today, 1)

    def test_77_a_task_that_failed_is_not_a_completed_run(self):
        self.add_task('t1', 'Sweep')
        self.assertFalse(self.engine.execute_task('t1'))
        self.assertEqual(self.engine.completed_today, 0)

    def test_78_a_batch_with_one_refused_file_is_not_one_completed_run(self):
        def operation(item):
            if item == 'a':
                return {'success': True, 'result': 'ok'}
            return {'success': False, 'error': 'no room left'}

        self.assertTrue(self.engine.run_batch(['a', 'b'], operation))
        self.wait_for_batch()
        self.assertEqual(self.engine.completed_today, 0)

    def test_79_the_saved_workflow_carries_the_moment_its_run_started(self):
        workflow = Workflow('Sweep')
        workflow.steps = [self.delete_step('x.obj')]
        workflow.started_at = 1234.5
        self.engine.workflows[workflow.workflow_id] = workflow
        self.engine._save_workflows()
        with open(os.path.join(self.home, 'workflows.json'), encoding='utf-8') as handle:
            saved = json.load(handle)
        self.assertEqual(saved[workflow.workflow_id]['started_at'], 1234.5)

    def test_80_reading_the_saved_workflow_back_keeps_its_start(self):
        workflow = Workflow('Sweep')
        workflow.started_at = 987.5
        again = Workflow.from_dict(workflow.to_dict())
        self.assertEqual(again.started_at, 987.5)

    def test_81_a_new_day_starts_the_counters_at_one(self):
        path = os.path.join(self.home, 'automation_stats.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'date': '2001-01-01', 'completed': 7, 'failed': 3}, handle)
        engine = AutomationEngine()
        self.addCleanup(engine.stop)
        engine._note_finished(True)
        self.assertEqual(engine.completed_today, 1,
                         "yesterday's runs were counted as today's")

    def test_82_todays_counter_survives_into_the_next_engine(self):
        self.engine._note_finished(True)
        self.engine._note_finished(True)
        again = AutomationEngine()
        self.addCleanup(again.stop)
        self.assertEqual(again.completed_today, 2)

    def test_83_a_stats_file_that_is_not_json_starts_fresh_counters(self):
        path = os.path.join(self.home, 'automation_stats.json')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('this is not json')
        engine = AutomationEngine()
        self.addCleanup(engine.stop)
        engine._note_finished(True)
        self.assertEqual(engine.completed_today, 1)

    def test_84_a_stopped_engine_leaves_nothing_it_still_owes(self):
        ran = []
        lock = threading.Lock()

        def operation(item):
            with lock:
                ran.append(item)
            time.sleep(0.3)
            return {'success': True, 'result': item}

        items = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']
        self.assertTrue(self.engine.run_batch(items, operation))
        self.assertTrue(self.spin(lambda: bool(ran)), 'the batch never took a file')
        self.assertEqual(self.engine.live_work(), ['a batch of files'])
        self.engine.stop()
        self.assertEqual(self.engine.live_work(), [],
                         'a close left a worker still taking files')
        with lock:
            took = len(ran)
        self.assertLess(took, len(items),
                        'the run was told to stop and still worked through every file '
                        '(%d of %d)' % (took, len(items)))


class LiveRunCase(PaneHome):
    """A run the engine started reaches the Monitor without anyone clicking Refresh."""

    def test_85_a_started_run_needs_no_manual_refresh_to_appear(self):
        self.instrument(FakeProcess(cpu=99.0))
        workflow = self.add_workflow('Alpha', TaskStatus.RUNNING, started_at=100.0)
        self.tab.on_workflow_started(workflow.workflow_id)
        self.assertEqual(self.tab.processes_table.rowCount(), 1,
                         'a run that started only showed up after a manual Refresh')
        self.assertIn('99.0% of one core', self.tab.cpu_usage_label.text(),
                      'the dashboard stopped refreshing the metrics')

    def test_86_a_real_run_shows_its_steps_and_the_moment_it_began(self):
        def hold():
            time.sleep(0.25)
            return {'success': True, 'result': 'held'}

        register_probe('probe.hold', hold, case=self)
        workflow = Workflow('Slow')
        workflow.steps = [WorkflowStep('hold', 'probe.hold', {}) for _ in range(3)]
        self.engine.workflows[workflow.workflow_id] = workflow
        self.assertTrue(self.engine.execute_workflow(workflow.workflow_id))
        self.assertTrue(self.spin(lambda: workflow.status is TaskStatus.RUNNING
                                  and workflow.current_step > 0),
                        'the run never reached the worker')
        self.tab.rebuild_process_table()
        self.addCleanup(self.engine.stop)
        self.assertEqual(self.tab.processes_table.rowCount(), 1)
        self.assertEqual(self.cells(0)[1], 'Slow')
        self.assertEqual(self.cells(0)[2], '1/3')
        self.assertEqual(self.cells(0)[3], 'Running')
        self.assertNotEqual(self.cells(0)[4], 'unknown',
                            'the engine started the run without recording when')

    def test_87_a_task_that_already_finished_has_no_row(self):
        self.add_task('t1', 'Nightly', status=TaskStatus.COMPLETED, started_at=100.0)
        self.tab.rebuild_process_table()
        self.assertEqual(self.tab.processes_table.rowCount(), 0)
        self.assertEqual(self.tab._process_keys, [])

    def test_88_a_batch_the_pane_started_is_named_by_what_it_is_doing(self):
        def slow_copy(source, destination):
            time.sleep(0.25)
            shutil.copyfile(source, destination)
            return {'success': True, 'result': 'copied'}

        register_probe('probe.slow_copy', slow_copy,
                       {'source': {'type': 'str', 'required': True},
                        'destination': {'type': 'str', 'required': True}},
                       batch=('source', 'destination'), case=self)
        self.tab = AutomationTab()
        self.engine = self.tab.automation_engine
        self.addCleanup(self.engine.stop)
        for name in ('a.obj', 'b.obj'):
            self.write(self.src, name)
        self.point_at_folder_copy('probe.slow_copy')
        self.tab.start_batch_operation()
        self.assertTrue(self.spin(lambda: self.engine.batch_processor.is_processing),
                        'the batch never began')
        self.tab.rebuild_process_table()
        self.assertEqual(self.cells(0)[1], 'probe.slow_copy over 2 file(s)')
        self.assertEqual(self.cells(0)[3], 'Running')
        self.engine.stop_batch()
        self.wait_for_batch()
        self.assertEqual(self.engine.live_work(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

