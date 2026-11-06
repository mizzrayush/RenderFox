"""
Automation tab Task Scheduler contract test.

Before this pass the Task Scheduler pane was a picture of a scheduler. The list was filled
by `populate_sample_tasks()` with five rows ("Daily Model Backup" / Success, "Model
Validation Check" / Running, and so on) that no object anywhere described. `Save Task`
opened a "Task '...' saved successfully!" box and wrote nothing. `Create Task` only
cleared two fields. `Edit`, `Delete`, `Enable`, `Disable`, `Test Task` and `Run Now` had
no `.connect()` at all. The Type column offered seven names - "Batch Processing", "File
Cleanup", "Report Generation", "System Maintenance" - that `ActionRegistry` has never
heard of, so even a task that had been stored could not have run. The pane talked to a
second `TaskScheduler` that nothing started, while `AutomationEngine.start()` - the
polling thread that makes a schedule happen - was never called from anywhere in the app.
`~/.renderfox/tasks.json` was read and written as `tasks.json` next to the current
directory, and `_load_tasks` restored the records without re-arming them, so a schedule
survived on disk and died in the app.

Run: python -X utf8 tests/test_automation_tasks_contract.py
"""

import ast
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.features import automation_engine as engine_module
from src.features.automation_engine import (
    ActionRegistry, AutomationEngine, SCHEDULE_UNITS, TaskScheduler, TaskStatus,
    _monthly_occurrence)
from src.ui.automation_tab import AutomationTab


class SchedulerCase(unittest.TestCase):
    """The scheduler's own vocabulary, driven without a window."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.home = tempfile.mkdtemp(prefix='renderfox_schedhome_')
        cls.previous_data_dir = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: cls.home

    @classmethod
    def tearDownClass(cls):
        engine_module.app_data_dir = cls.previous_data_dir
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.sched = TaskScheduler()
        self.addCleanup(self.sched.stop_scheduler)
        for name in ('tasks.json', 'workflows.json'):
            path = os.path.join(self.home, name)
            if os.path.exists(path):
                os.remove(path)

    def test_01_every_spec_the_pane_builds_is_accepted(self):
        """The tab composes these strings; the scheduler must not disagree about them."""
        accepted = ['hourly', 'daily', 'weekly', 'daily@09:00', 'weekly@09:00',
                    'monthly@03:15', 'every_5_minutes', 'every_2_hours', 'every_1_days',
                    'every_30_seconds']
        for spec in accepted:
            self.assertTrue(self.sched.schedule_task('t', spec, lambda: None),
                            f'{spec} was refused by the scheduler the pane trusts')

    def test_02_every_0_never_reaches_the_schedule_library(self):
        """`schedule.every(0)` spins forever inside _schedule_next_run; a freeze here
        would take the whole app down with it."""
        deadline = time.time() + 5
        self.assertFalse(self.sched.schedule_task('t', 'every_0_minutes', lambda: None))
        self.assertFalse(self.sched.schedule_task('t', 'every_0_seconds', lambda: None))
        self.assertLess(time.time(), deadline, 'the refusal did not come back')

    def test_03_an_unknown_spec_is_refused_not_guessed(self):
        for spec in ('someday', '', None, 'every_5_weeks', 'every_minutes',
                     'every_abc_hours', 'once:not-a-date'):
            with self.subTest(spec=spec):
                self.assertFalse(self.sched.schedule_task('t', spec, lambda: None))

    def test_04_a_one_time_in_the_past_is_refused(self):
        past = (datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        self.assertFalse(self.sched.schedule_task('t', f'once:{past}', lambda: None))

    def test_05_the_next_run_is_a_real_moment(self):
        self.assertIsNone(self.sched.next_run('nobody'))
        self.assertTrue(self.sched.schedule_task('t', 'daily@09:00', lambda: None))
        when = self.sched.next_run('t')
        self.assertIsInstance(when, datetime)
        self.assertEqual((when.hour, when.minute), (9, 0), 'not the clock the pane asked for')

    def test_06_two_schedulers_do_not_share_one_job_list(self):
        """`schedule`'s default scheduler is a module global: two engines on it would each
        run the other's jobs, so a task would fire once per live engine."""
        other = TaskScheduler()
        self.addCleanup(other.stop_scheduler)
        self.sched.schedule_task('x', 'every_5_minutes', lambda: None)
        other.schedule_task('y', 'every_5_minutes', lambda: None)
        self.assertEqual(len(self.sched._jobs.jobs), 1)
        self.assertEqual(len(other._jobs.jobs), 1, 'both schedulers are looking at one list')
        self.assertIsNone(other.next_run('x'))

    def test_07_a_scheduled_job_fires_on_the_polling_thread(self):
        fired = threading.Event()
        self.sched.schedule_task('t', 'every_1_seconds', fired.set)
        self.sched.start_scheduler()
        self.assertTrue(fired.wait(5.0), 'the job never ran; nothing in this app would fire')

    def test_08_a_one_off_fires_once_and_leaves_the_registry(self):
        hits = []
        when = datetime.now() + timedelta(seconds=2)
        spec = 'once:' + when.strftime('%Y-%m-%dT%H:%M:%S')
        self.assertTrue(self.sched.schedule_task('t', spec, lambda: hits.append(when)))
        self.sched.start_scheduler()
        deadline = time.time() + 8
        while time.time() < deadline and not hits:
            time.sleep(0.1)
        self.assertEqual(len(hits), 1, f'the one-off fired {len(hits)} times')
        time.sleep(1.5)
        self.assertEqual(len(hits), 1, 'a one-off re-armed itself')
        self.assertIsNone(self.sched.next_run('t'), 'it should have taken itself out')

    def test_09_a_monthly_job_clamps_a_short_month_and_rearms(self):
        """This build of `schedule` has no month unit, so the engine counts them itself."""
        self.assertEqual(_monthly_occurrence(31, 3, 15, datetime(2026, 2, 10)).day, 28)
        rolled = _monthly_occurrence(31, 3, 15, datetime(2026, 2, 28, 4, 0))
        self.assertEqual((rolled.year, rolled.month, rolled.day), (2026, 3, 31))
        hits = []
        self.assertTrue(self.sched.schedule_task(
            'm', 'monthly@03:15', lambda: hits.append(datetime.now())))
        self.assertIsNotNone(self.sched.next_run('m'))

    def test_10_stopping_the_scheduler_is_prompt(self):
        self.sched.start_scheduler()
        started = time.time()
        self.sched.stop_scheduler()
        self.assertLess(time.time() - started, 0.5, 'stop waited a whole poll interval')

    def test_11_a_callback_that_raises_does_not_stop_the_loop(self):
        good = threading.Event()

        def broken():
            raise RuntimeError('this job is broken on purpose')

        self.sched.schedule_task('bad', 'every_1_seconds', broken)
        self.sched.schedule_task('good', 'every_2_seconds', good.set)
        self.sched.start_scheduler()
        self.assertTrue(good.wait(8.0), 'one raising job silenced the others')
        self.assertTrue(self.sched.is_running)

    def test_12_re_scheduling_replaces_the_old_job(self):
        self.sched.schedule_task('t', 'daily@09:00', lambda: None)
        self.sched.schedule_task('t', 'hourly', lambda: None)
        self.assertEqual(len(self.sched._jobs.jobs), 1, 'the old schedule is still live')

    def test_13_the_units_the_engine_advertises_are_the_units_it_uses(self):
        self.assertEqual(SCHEDULE_UNITS, ('seconds', 'minutes', 'hours', 'days'))


class EngineTaskCase(unittest.TestCase):
    """Tasks as the engine owns them: stored, scheduled, run, restored."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.home = tempfile.mkdtemp(prefix='renderfox_enginehome_')
        cls.previous_data_dir = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: cls.home

    @classmethod
    def tearDownClass(cls):
        engine_module.app_data_dir = cls.previous_data_dir
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_engine_')
        for name in ('tasks.json', 'workflows.json'):
            path = os.path.join(self.home, name)
            if os.path.exists(path):
                os.remove(path)
        self.engine = AutomationEngine()
        self.addCleanup(self.engine.stop)

    def test_01_a_saved_task_is_written_where_the_app_looks(self):
        task_id = self.engine.create_task('Copy', 'file.copy', {'source': 'a', 'destination': 'b'})
        with open(os.path.join(self.home, 'tasks.json'), encoding='utf-8') as handle:
            records = json.load(handle)
        self.assertEqual([record['task_id'] for record in records], [task_id])
        self.assertEqual(records[0]['name'], 'Copy')
        self.assertEqual(records[0]['parameters'], {'source': 'a', 'destination': 'b'})

    def test_02_create_task_stores_it_without_inventing_a_schedule(self):
        task_id = self.engine.create_task('Plain', 'file.copy', {})
        task = self.engine.tasks[task_id]
        self.assertIsNone(task.schedule_time, 'the schedule is schedule_task()\'s job')
        self.assertIsNone(self.engine.next_run(task_id))

    def test_03_a_schedule_the_engine_cannot_honour_is_not_claimed(self):
        task_id = self.engine.create_task('Bad', 'file.copy', {})
        self.assertFalse(self.engine.schedule_task(task_id, 'every day at 9'))
        self.assertNotEqual(self.engine.tasks[task_id].status, TaskStatus.SCHEDULED)
        self.assertIsNone(self.engine.tasks[task_id].schedule_time)

    def test_04_a_real_schedule_marks_the_task_and_the_row_honest(self):
        task_id = self.engine.create_task('Nightly', 'file.copy', {})
        self.assertTrue(self.engine.schedule_task(task_id, 'daily@02:00'))
        task = self.engine.tasks[task_id]
        self.assertEqual(task.status, TaskStatus.SCHEDULED)
        self.assertEqual(task.schedule_time, 'daily@02:00')
        self.assertIsInstance(self.engine.next_run(task_id), datetime)

    def test_05_disabling_takes_the_schedule_away_and_re_enabling_brings_it_back(self):
        task_id = self.engine.create_task('Toggle', 'file.copy', {})
        self.engine.schedule_task(task_id, 'hourly')
        self.assertTrue(self.engine.set_task_enabled(task_id, False))
        self.assertIsNone(self.engine.next_run(task_id), 'a disabled task is still on the list')
        self.assertTrue(self.engine.set_task_enabled(task_id, True))
        self.assertIsNotNone(self.engine.next_run(task_id), 'it did not go back on the calendar')

    def test_05b_a_disabled_task_stays_disabled_and_off_the_calendar_after_a_restart(self):
        task_id = self.engine.create_task('Paused', 'file.copy', {})
        self.engine.schedule_task(task_id, 'hourly')
        self.assertTrue(self.engine.set_task_enabled(task_id, False))
        rebuilt = AutomationEngine()
        self.addCleanup(rebuilt.stop)
        self.assertFalse(rebuilt.tasks[task_id].enabled, 'the disabled flag did not survive')
        self.assertIsNone(rebuilt.next_run(task_id), 'a disabled task came back on the calendar')

    def test_06_a_disabled_task_refuses_to_run_and_says_why(self):
        task_id = self.engine.create_task('Off', 'file.copy', {})
        self.engine.set_task_enabled(task_id, False)
        seen = []
        self.engine.task_completed.connect(lambda *a: seen.append(a))
        self.assertFalse(self.engine.execute_task(task_id))
        self.assertEqual(seen[0][1], False)
        self.assertIn('disabled', seen[0][2]['error'])

    def test_07_the_actions_verdict_decides_the_status(self):
        missing = os.path.join(self.work, 'gone.obj')
        task_id = self.engine.create_task('Copy nothing', 'file.copy',
                                          {'source': missing, 'destination': missing + '.2'})
        seen = []
        self.engine.task_completed.connect(lambda *a: seen.append(a))
        self.assertFalse(self.engine.execute_task(task_id))
        task = self.engine.tasks[task_id]
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn('no file to copy', task.error)
        self.assertEqual(seen[0][1], False)

    def test_08_a_successful_run_is_recorded_and_reported(self):
        source = os.path.join(self.work, 'hero.obj')
        with open(source, 'w', encoding='utf-8') as handle:
            handle.write('v 0 0 0\n')
        destination = os.path.join(self.work, 'hero_copy.obj')
        task_id = self.engine.create_task('Copy it', 'file.copy',
                                          {'source': source, 'destination': destination})
        seen = []
        self.engine.task_completed.connect(lambda *a: seen.append(a))
        self.assertTrue(self.engine.execute_task(task_id))
        self.assertEqual(self.engine.tasks[task_id].status, TaskStatus.COMPLETED)
        self.assertTrue(os.path.isfile(destination), 'it claimed a copy it did not make')
        self.assertIn('Copied', seen[0][2]['result'])

    def test_09_update_task_leaves_untouched_fields_alone(self):
        task_id = self.engine.create_task('Original', 'file.copy', {'source': 'a',
                                                                    'destination': 'b'})
        self.engine.schedule_task(task_id, 'hourly')
        self.assertTrue(self.engine.update_task(task_id, name='Renamed'))
        task = self.engine.tasks[task_id]
        self.assertEqual(task.name, 'Renamed')
        self.assertEqual(task.parameters, {'source': 'a', 'destination': 'b'})
        self.assertEqual(task.task_type, 'file.copy')

    def test_10_delete_removes_it_from_the_list_and_the_file(self):
        task_id = self.engine.create_task('Doomed', 'file.copy', {})
        self.engine.schedule_task(task_id, 'hourly')
        self.assertTrue(self.engine.delete_task(task_id))
        self.assertNotIn(task_id, self.engine.tasks)
        self.assertIsNone(self.engine.next_run(task_id))
        with open(os.path.join(self.home, 'tasks.json'), encoding='utf-8') as handle:
            self.assertEqual(json.load(handle), [])

    def test_11_a_restarted_engine_re_arms_what_was_scheduled(self):
        task_id = self.engine.create_task('Nightly', 'file.copy', {})
        self.engine.schedule_task(task_id, 'daily@02:00')
        rebuilt = AutomationEngine()
        self.addCleanup(rebuilt.stop)
        self.assertIn(task_id, rebuilt.tasks)
        self.assertIsNotNone(rebuilt.next_run(task_id),
                             'the schedule was read back and then never put on the calendar')
        self.assertEqual(rebuilt.tasks[task_id].status, TaskStatus.SCHEDULED)

    def test_12_a_one_off_that_was_missed_is_cancelled_not_rescheduled(self):
        past = (datetime.now() - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%S')
        task_id = self.engine.create_task('Missed', 'file.copy', {})
        self.engine.tasks[task_id].schedule_time = f'once:{past}'
        self.engine._save_tasks()
        rebuilt = AutomationEngine()
        self.addCleanup(rebuilt.stop)
        self.assertEqual(rebuilt.tasks[task_id].status, TaskStatus.CANCELLED)
        self.assertIsNone(rebuilt.next_run(task_id), 'a missed one-off must not fire late')

    def test_13_an_unreadable_record_is_skipped_not_fatal(self):
        self.engine.create_task('Kept', 'file.copy', {})
        with open(os.path.join(self.home, 'tasks.json'), 'w', encoding='utf-8') as handle:
            json.dump([{'no': 'id here'}, {'task_id': 'x', 'name': 'Kept',
                                           'task_type': 'file.copy'}], handle)
        rebuilt = AutomationEngine()
        self.addCleanup(rebuilt.stop)
        self.assertEqual(sorted(task.name for task in rebuilt.tasks.values()), ['Kept'])

    def test_14_task_ids_stay_unique_when_two_land_in_one_millisecond(self):
        ids = {self.engine.create_task(f'T{n}', 'file.copy', {}) for n in range(40)}
        self.assertEqual(len(ids), 40, 'two tasks were given the same id')

    def test_15_a_task_names_an_action_the_registry_has(self):
        registered = set(ActionRegistry.get_all_actions())
        task_id = self.engine.create_task('Ghost', 'file.transmogrify', {})
        seen = []
        self.engine.task_completed.connect(lambda *a: seen.append(a))
        self.assertFalse(self.engine.execute_task(task_id))
        self.assertIn('file.transmogrify', seen[0][2]['error'])
        self.assertNotIn('file.transmogrify', registered)


class TaskPaneCase(unittest.TestCase):
    """The pane the user clicks: every button must reach the engine, or say it cannot."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.home = tempfile.mkdtemp(prefix='renderfox_panehome_')
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
        (QMessageBox.information, QMessageBox.critical,
         QMessageBox.warning, QMessageBox.question) = cls.previous_boxes
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_pane_')
        for name in ('tasks.json', 'workflows.json'):
            path = os.path.join(self.home, name)
            if os.path.exists(path):
                os.remove(path)
        self.popups.clear()
        self.tab = AutomationTab()
        self.addCleanup(self.tab.automation_engine.stop)
        self.file_copy = self.tab.task_type_combo.findData('file.copy')

    # --- helpers ---------------------------------------------------------------
    def tab_source(self):
        with open(os.path.join(ROOT, 'src', 'ui', 'automation_tab.py'),
                  encoding='utf-8') as handle:
            return handle.read()

    def activity(self):
        return [self.tab.activity_list.item(i).text()
                for i in range(self.tab.activity_list.count())]

    def rows(self):
        table = self.tab.scheduled_tasks_table
        return [[(table.item(r, c).text() if table.item(r, c) else '')
                 for c in range(table.columnCount())] for r in range(table.rowCount())]

    def choose(self, action_id='file.copy'):
        self.tab.task_type_combo.setCurrentIndex(self.tab.task_type_combo.findData(action_id))

    def fill(self, name='Nightly copy', params=None, schedule='Daily', action_id='file.copy'):
        """Set the editor up; `params=None` means parameters this action accepts."""
        self.tab.new_task()
        self.tab.task_name_edit.setText(name)
        self.choose(action_id)
        self.tab.task_actions_edit.setPlainText(
            params if params is not None else '"source": "a", "destination": "b"')
        self.tab.schedule_type_combo.setCurrentText(schedule)

    def spin(self, want, timeout=12.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if want():
                return True
            time.sleep(0.02)
        return False

    def script(self, name, body):
        path = os.path.join(self.work, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(body)
        return path

    # --- the pane's own wiring -------------------------------------------------
    def test_01_every_task_control_is_connected(self):
        for name in ('create_task_btn', 'save_task_btn', 'edit_task_btn', 'delete_task_btn',
                     'enable_task_btn', 'disable_task_btn', 'test_task_btn', 'run_now_btn'):
            button = getattr(self.tab, name)
            self.assertTrue(button.receivers(button.clicked), f'{name} is still a dead button')
        table = self.tab.scheduled_tasks_table
        self.assertTrue(table.receivers(table.itemSelectionChanged))
        combo = self.tab.schedule_type_combo
        self.assertTrue(combo.receivers(combo.currentTextChanged))

    def test_02_the_task_list_starts_empty_and_stays_that_way(self):
        """Five invented rows - and the code that wrote them - must not come back."""
        self.assertEqual(self.tab.scheduled_tasks_table.rowCount(), 0)
        source = self.tab_source()
        for needle in ('populate_sample_tasks', 'Daily Model Backup', 'Cleanup Temp Files',
                       'Model Validation Check', 'System Health Check',
                       'Weekly Report Generation', 'On Startup', 'On File Change'):
            self.assertNotIn(needle, source, f'{needle} is back in the pane')

    def test_03_the_type_column_offers_the_registry_ids(self):
        offered = {self.tab.task_type_combo.itemData(i)
                   for i in range(self.tab.task_type_combo.count())}
        self.assertEqual(offered, set(ActionRegistry.get_all_actions()))
        self.assertIn('system.run_command', offered)
        self.assertTrue(self.file_copy >= 0, 'the pane cannot name the action it runs')

    def test_04_the_default_schedule_is_one_that_can_be_saved(self):
        """The old pane defaulted to a schedule its own Save button would refuse."""
        self.assertEqual(self.tab.schedule_type_combo.currentText(), 'Daily')
        self.fill()
        self.tab.save_task_btn.click()
        self.assertEqual([kind for kind, _ in self.popups], [], f'{self.popups}')
        self.assertEqual(self.tab.scheduled_tasks_table.rowCount(), 1)

    def test_04b_an_empty_parameters_box_is_refused_for_an_action_that_needs_values(self):
        self.tab.new_task()
        self.tab.task_name_edit.setText('No parameters')
        self.choose()
        self.tab.task_actions_edit.setPlainText('')
        self.tab.save_task_btn.click()
        self.assertEqual(self.tab.automation_engine.tasks, {})
        texts = [str(a[2]) for kind, a in self.popups if kind == 'warning']
        self.assertTrue(any('needs a value for' in text for text in texts), self.popups)

    def test_05_saving_writes_a_record_the_engine_and_the_disk_both_have(self):
        self.fill(name='Backup pass', params='"source": "x", "destination": "y"',
                  schedule='Weekly')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        task = self.tab.automation_engine.tasks[task_id]
        self.assertEqual(task.name, 'Backup pass')
        self.assertEqual(task.task_type, 'file.copy')
        self.assertEqual(task.schedule_time, 'weekly@09:00')
        with open(os.path.join(self.home, 'tasks.json'), encoding='utf-8') as handle:
            records = json.load(handle)
        self.assertEqual([record['task_id'] for record in records], [task_id])
        self.assertEqual(self.tab.scheduled_tasks_table.rowCount(), 1)

    def test_06_the_parameters_box_is_data_never_code(self):
        """The workflow path handed this cell to eval(); a payload must not run.

        A side-effecting payload on its own is not proof. With a Windows path in it,
        `eval()` dies on the `\\U` of `C:\\Users` long before the redirection happens, so
        the parse refuses for the wrong reason and an eval() put back here still passes
        every assertion - mutation N21 found exactly that. So this asks for a value only
        code can produce, and then reads the pane's syntax tree for a call by that name.
        """
        marker = os.path.join(self.work, 'pwned.txt').replace('\\', '/')
        payloads = [f'"source": __import__("os").popen("echo x > \\"{marker}\\").read()',
                    '"levels": (lambda: 3)()']
        for payload in payloads:
            with self.subTest(payload=payload):
                params, problem = self.tab._parse_parameters(payload)
                self.assertIsNotNone(problem, f'{payload} parsed as {params!r}')
        self.assertFalse(os.path.exists(marker), 'the parameters were evaluated')

        tree = ast.parse(self.tab_source())
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(called & {'eval', 'exec', 'compile'},
                         f'the pane evaluates text again: {sorted(called & {"eval", "exec", "compile"})}')
        self.assertIn('ast.literal_eval', self.tab_source(),
                      'the parameters are no longer parsed as data')

    def test_07_a_json_object_and_a_bare_pair_both_parse(self):
        self.assertEqual(self.tab._parse_parameters('{"levels": 3}'), ({'levels': 3}, None))
        self.assertEqual(self.tab._parse_parameters('"levels": 3'), ({'levels': 3}, None))
        self.assertEqual(self.tab._parse_parameters("'source': 'a'"), ({'source': 'a'}, None))
        self.assertEqual(self.tab._parse_parameters(''), ({}, None))

    def test_08_a_parameter_the_action_does_not_take_is_named(self):
        complaints = self.tab._validate_parameters('file.copy', {'source': 'a',
                                                                 'destination': 'b',
                                                                 'overwrite': True})
        self.assertEqual(len(complaints), 1, complaints)
        self.assertIn('overwrite', complaints[0])

    def test_09_a_missing_or_wrongly_typed_parameter_is_named(self):
        missing = self.tab._validate_parameters('file.copy', {'source': 'a'})
        self.assertEqual(len(missing), 1)
        self.assertIn('destination', missing[0])
        wrong = self.tab._validate_parameters('processing.generate_lod',
                                              {'input_file': 'a', 'output_dir': 'b',
                                               'levels': 'three'})
        self.assertTrue(any("'levels' must be int" in line for line in wrong), wrong)

    def test_10_a_refused_parameter_never_reaches_the_engine(self):
        self.fill(params='"source": "a"')
        self.tab.save_task_btn.click()
        self.assertEqual(self.tab.automation_engine.tasks, {})
        texts = [str(a[2]) for kind, a in self.popups if kind == 'warning']
        self.assertTrue(any('destination' in text for text in texts), self.popups)

    def test_11_the_schedule_the_pane_builds_is_the_schedule_the_engine_keeps(self):
        cases = {'Hourly': 'hourly', 'Daily': 'daily@09:00', 'Weekly': 'weekly@09:00',
                 'Monthly': 'monthly@09:00'}
        for label, expected in cases.items():
            with self.subTest(label):
                self.fill(schedule=label)
                self.tab.save_task_btn.click()
                task = self.tab.automation_engine.tasks[self.tab.current_task_id]
                self.assertEqual(task.schedule_time, expected)
                self.assertIsNotNone(self.tab.automation_engine.next_run(task.task_id))

    def test_12_a_repeated_interval_reaches_the_engine_as_every_n_unit(self):
        self.fill(schedule='Repeated interval')
        self.tab.repeat_interval_spin.setValue(5)
        self.tab.repeat_unit_combo.setCurrentText('Hours')
        self.tab.save_task_btn.click()
        task = self.tab.automation_engine.tasks[self.tab.current_task_id]
        self.assertEqual(task.schedule_time, 'every_5_hours')
        self.assertIsNotNone(self.tab.automation_engine.next_run(task.task_id))

    def test_13_a_one_time_in_the_past_is_refused(self):
        self.fill(schedule='One Time')
        self.tab.schedule_date_edit.setDate(
            self.tab.schedule_date_edit.date().addDays(-2))
        self.tab.save_task_btn.click()
        warnings = [a[2] for kind, a in self.popups if kind == 'warning']
        self.assertTrue(any('already passed' in str(text) for text in warnings), self.popups)
        self.assertEqual(self.tab.automation_engine.tasks, {})

    def test_14_a_one_time_in_the_future_is_scheduled(self):
        self.fill(schedule='One Time')
        self.tab.schedule_date_edit.setDate(self.tab.schedule_date_edit.date().addDays(1))
        self.tab.save_task_btn.click()
        task = self.tab.automation_engine.tasks[self.tab.current_task_id]
        self.assertTrue(task.schedule_time.startswith('once:'))
        self.assertGreater(self.tab.automation_engine.next_run(task.task_id), datetime.now())

    def test_15_the_next_run_column_is_the_engines_own(self):
        self.fill(schedule='Daily')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        expected = self.tab.automation_engine.next_run(task_id).strftime('%Y-%m-%d %H:%M')
        self.assertEqual(self.rows()[0][3], expected)

    def test_16_the_schedule_controls_only_offer_what_the_choice_uses(self):
        for label, enabled in (('One Time', (True, True)), ('Daily', (False, True)),
                               ('Hourly', (False, False)),
                               ('Repeated interval', (False, False))):
            with self.subTest(label):
                self.tab.schedule_type_combo.setCurrentText(label)
                self.assertEqual(self.tab.schedule_date_edit.isEnabled(), enabled[0], label)
                self.assertEqual(self.tab.schedule_time_edit.isEnabled(), enabled[1], label)

    def test_17_run_now_of_a_real_command_lands_its_output_in_the_log(self):
        printed = 'hello-from-a-task'
        script = self.script('printer.py', f'print({printed!r})\n')
        self.fill(name='Printer', schedule='Hourly', action_id='system.run_command')
        self.tab.task_actions_edit.setPlainText(
            json.dumps({'command': f'"{sys.executable}" "{script}"'}))
        self.tab.save_task_btn.click()
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.run_now_btn.click()
        self.assertTrue(self.spin(lambda: printed in ' '.join(self.activity())),
                        f'the command output never reached the log: {self.activity()}')
        self.assertEqual(self.tab.automation_engine.tasks[self.tab.current_task_id].status,
                         TaskStatus.COMPLETED)

    def test_17b_run_now_files_its_thread_where_the_close_waits(self):
        """A task begun from the pane is joined only if the engine was told about it.

        `engine.stop()` joins exactly `_worker_threads`, and the window's close calls it
        before it destroys anything; a thread started beside that list keeps writing files
        after the window is gone, and `live_work` - the question the close asks the user -
        would not have named it. The command sleeps, so the run is certainly still in flight
        when the filing is read, and a second press meets a task the engine already holds.
        """
        engine = self.tab.automation_engine
        self.fill(name='Sleeper', schedule='Hourly', action_id='system.run_command')
        self.tab.task_actions_edit.setPlainText(
            json.dumps({'command': f'"{sys.executable}" -c "import time; time.sleep(3)"'}))
        self.tab.save_task_btn.click()
        self.tab.scheduled_tasks_table.selectRow(0)
        task_id = self.tab.current_task_id

        self.tab.run_now_btn.click()
        self.assertEqual(1, len(engine._worker_threads),
                         'Run Now started a thread no code can join')
        self.assertEqual(["task 'Sleeper'"], engine.live_work(),
                         'the close asks `live_work` before it cuts anything off, and it is '
                         'being told nothing is running')
        self.popups.clear()
        self.tab.run_now_btn.click()
        self.assertEqual(1, len(engine._worker_threads),
                         'a second press started a second thread for the same task')
        self.assertTrue(any(kind == 'warning' for kind, _ in self.popups),
                        f'the refused press said nothing: {self.popups}')
        self.assertTrue(self.spin(
            lambda: engine.tasks[task_id].status is TaskStatus.COMPLETED),
                        f'the task never finished: {self.activity()}')

    def test_18_a_failing_action_is_reported_as_a_failure(self):
        gone = os.path.join(self.work, 'not_here.obj')
        self.fill(name='Copy of nothing',
                  params=json.dumps({'source': gone, 'destination': 'b'}))
        self.tab.save_task_btn.click()
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.run_now_btn.click()
        self.assertTrue(self.spin(lambda: 'FAILED' in ' '.join(self.activity())),
                        self.activity())
        row = self.rows()[0]
        self.assertIn('failed', row[4])
        self.assertIn('no file to copy', row[5], 'the row shows no reason')

    def test_19_run_now_without_a_selection_says_so(self):
        self.tab.run_now_btn.click()
        self.assertTrue(any(kind == 'warning' for kind, _ in self.popups), self.popups)

    def test_20_a_disabled_task_is_not_run_silently(self):
        self.fill(schedule='Hourly')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.disable_task_btn.click()
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.run_now_btn.click()
        self.assertTrue(self.spin(lambda: 'disabled' in ' '.join(self.activity())),
                        self.activity())
        self.assertIsNone(self.tab.automation_engine.next_run(task_id))
        self.assertEqual([], self.tab.automation_engine.live_work(),
                         'the refused run left its task in `live_work`, so the next close asks '
                         'the user whether to cut off something that never started')

    def test_21_enable_and_disable_move_the_row_and_the_schedule(self):
        self.fill(schedule='Hourly')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.disable_task_btn.click()
        self.assertFalse(self.tab.automation_engine.tasks[task_id].enabled)
        self.assertIn('(disabled)', self.rows()[0][4])
        self.assertIsNone(self.tab.automation_engine.next_run(task_id))
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.enable_task_btn.click()
        self.assertTrue(self.tab.automation_engine.tasks[task_id].enabled)
        self.assertNotIn('(disabled)', self.rows()[0][4])
        self.assertIsNotNone(self.tab.automation_engine.next_run(task_id))

    def test_22_delete_removes_it_from_the_table_the_engine_and_the_file(self):
        self.fill(schedule='Hourly')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.delete_task_btn.click()
        self.assertEqual(self.tab.scheduled_tasks_table.rowCount(), 0)
        self.assertNotIn(task_id, self.tab.automation_engine.tasks)
        with open(os.path.join(self.home, 'tasks.json'), encoding='utf-8') as handle:
            self.assertEqual(json.load(handle), [])

    def test_23_delete_without_a_selection_says_so(self):
        self.tab.delete_task_btn.click()
        self.assertTrue(any('Select a task' in str(a[2]) for kind, a in self.popups
                            if kind == 'warning'), self.popups)

    def test_24_editing_puts_the_selected_task_back_in_the_editor(self):
        self.fill(name='Second pass', params='"source": "keep", "destination": "me"')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        self.tab.new_task()
        self.assertEqual(self.tab.task_name_edit.text(), '')
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.edit_task_btn.click()
        self.assertEqual(self.tab.current_task_id, task_id)
        self.assertEqual(self.tab.task_name_edit.text(), 'Second pass')
        self.assertEqual(self.tab.task_type_combo.currentData(), 'file.copy')
        self.assertIn('keep', self.tab.task_actions_edit.toPlainText())

    def test_25_saving_again_updates_instead_of_duplicating(self):
        self.fill(name='Original')
        self.tab.save_task_btn.click()
        first = self.tab.current_task_id
        self.tab.task_name_edit.setText('Renamed')
        self.tab.save_task_btn.click()
        self.assertEqual(self.tab.current_task_id, first)
        self.assertEqual(len(self.tab.automation_engine.tasks), 1)
        self.assertEqual(self.rows()[0][0], 'Renamed')

    def test_25b_a_task_restored_from_disk_loads_into_the_editor(self):
        self.fill(name='From disk', params='"source": "s", "destination": "d"',
                  schedule='Weekly')
        self.tab.save_task_btn.click()
        self.tab.automation_engine.stop()
        for name in ('tasks.json',):
            self.assertTrue(os.path.exists(os.path.join(self.home, name)))
        self.tab = AutomationTab()
        self.addCleanup(self.tab.automation_engine.stop)
        self.assertEqual(self.tab.scheduled_tasks_table.rowCount(), 1)
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.edit_task_btn.click()
        self.assertEqual(self.tab.task_name_edit.text(), 'From disk')
        self.assertEqual(self.tab.task_type_combo.currentData(), 'file.copy')
        self.assertIn('s', self.tab.task_actions_edit.toPlainText())

    def test_26_test_task_says_what_it_would_do_and_does_not_do_it(self):
        doomed = os.path.join(self.work, 'doomed.obj')
        with open(doomed, 'w', encoding='utf-8') as handle:
            handle.write('v 0 0 0\n')
        self.fill(name='Dry run', params=json.dumps({'path': doomed}),
                  action_id='file.delete')
        self.tab.test_task_btn.click()
        self.assertTrue(os.path.isfile(doomed), 'Test Task ran the action')
        texts = [str(a[2]) for kind, a in self.popups if kind == 'information']
        self.assertTrue(any('would run file.delete' in text for text in texts), self.popups)

    def test_27_test_task_names_what_is_wrong(self):
        self.fill(name='Broken', params='"source": "only-one"', schedule='Hourly')
        self.tab.test_task_btn.click()
        warnings = [str(a[2]) for kind, a in self.popups if kind == 'warning']
        self.assertTrue(any('destination' in text for text in warnings), self.popups)
        self.assertEqual(self.tab.automation_engine.tasks, {})

    def test_28_the_dashboard_counts_the_engines_tasks(self):
        self.assertEqual(self.tab.scheduled_tasks_label.text(), '0')
        self.fill(schedule='Hourly')
        self.tab.save_task_btn.click()
        self.assertEqual(self.tab.scheduled_tasks_label.text(), '1')
        self.tab.scheduled_tasks_table.selectRow(0)
        self.tab.delete_task_btn.click()
        self.assertEqual(self.tab.scheduled_tasks_label.text(), '0')

    def test_29_no_second_scheduler_is_left_behind(self):
        """The pane used to build its own TaskScheduler that nothing ever started."""
        source = self.tab_source()
        for needle in ('TaskScheduler()', 'task_scheduler', 'load_tasks()',
                       'self.scheduled_tasks = []'):
            self.assertNotIn(needle, source, f'{needle} is back in the tab')
        self.assertTrue(self.tab.automation_engine.scheduler.is_running,
                        'the engine thread was never started, so no schedule could fire')

    def test_30_a_saved_task_survives_a_restart_with_its_schedule(self):
        self.fill(name='Keeper', schedule='Daily')
        self.tab.save_task_btn.click()
        task_id = self.tab.current_task_id
        self.tab.automation_engine.stop()
        rebuilt = AutomationEngine()
        self.addCleanup(rebuilt.stop)
        self.assertIsNotNone(rebuilt.next_run(task_id))
        self.assertEqual(rebuilt.tasks[task_id].schedule_time, 'daily@09:00')

    def test_31_the_app_starts_exactly_one_engine(self):
        """main.py built a second AutomationEngine and started it beside the tab's.

        Once the scheduler inside that class became real, that stopped being harmless:
        a second live instance reads the same tasks file and gives every task its own
        calendar, so a nightly copy runs twice a night and each run rewrites the record.
        """
        with open(os.path.join(ROOT, 'main.py'), encoding='utf-8') as handle:
            source = handle.read()
        for needle in ('AutomationEngine(', 'engine.start()'):
            self.assertNotIn(needle, source, f'{needle} is back in the launcher')
        registered = source.find('ActionRegistry.register(')
        window = source.find('MainWindow()')
        self.assertGreater(registered, -1, 'the pcd.* actions are no longer registered')
        self.assertLess(registered, window,
                        'registered after the window, the pane never gets to offer them')


if __name__ == '__main__':
    unittest.main(verbosity=2)
