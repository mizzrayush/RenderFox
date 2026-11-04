"""Phase 6c contract: the Workflow Builder runs the steps it shows.

What this suite exists to keep out of the app:

  * `create_workflow` called `Workflow(workflow_id=..., steps=..., ...)`, which is not
    that constructor - every call raised TypeError, so no workflow could be stored.
  * `WorkflowExecutor.execute_workflow` did `step.get('name')` on `WorkflowStep`
    objects, so the first step of any run raised AttributeError in a worker thread.
  * `workflow_completed` is `pyqtSignal(str, dict)` and was emitted with three
    arguments, so even a run that finished could not report it.
  * `workflow_progress` was declared and never emitted; nothing could stop a run.
  * The pane listed five invented workflow names, filled the steps table with four
    fake sample steps, invented the description on selection, wired nine of its
    buttons to nothing, turned a step's display name into an action id with
    `step_name.lower().replace(' ', '_')` (no registry has ever seen those ids), wrote
    its verdicts into the Batch tab's progress bar, and ran a
    `WorkflowExecutionThread` class nothing built - which, when it had no action to
    call, slept 500 ms and reported success.

Run: python -X utf8 tests/test_automation_workflows_contract.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from src.features import automation_engine as engine_module
from src.features.automation_engine import (
    ActionRegistry, AutomationEngine, TaskStatus, Workflow, WorkflowExecutor, WorkflowStep)
from src.ui.automation_tab import AutomationTab


def register_probe(action_id, func, params=None, case=None):
    """Put an action in the registry for the duration of one test."""
    ActionRegistry.register(action_id, func, 'probe', params or {})
    pop = lambda: ActionRegistry._actions.pop(action_id, None)
    if case is not None:
        case.addCleanup(pop)
    return pop


class RegistryCase(unittest.TestCase):
    """The registry is the only place that knows what an action takes."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix='renderfox_6c_reg_')
        cls.real_home = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: cls.home
        cls.engine = AutomationEngine()

    @classmethod
    def tearDownClass(cls):
        cls.engine.stop()
        engine_module.app_data_dir = cls.real_home
        shutil.rmtree(cls.home, ignore_errors=True)

    def test_01_a_missing_value_names_the_parameter_and_the_action(self):
        complaints = ActionRegistry.validate('file.copy', {'source': 'a'})
        self.assertEqual(len(complaints), 1, complaints)
        self.assertIn('destination', complaints[0])

    def test_02_a_parameter_the_action_does_not_take_is_named(self):
        complaints = ActionRegistry.validate('file.copy', {'source': 'a', 'destination': 'b',
                                                           'bogus': 1})
        self.assertEqual(complaints, ["file.copy has no parameter named: bogus"], complaints)

    def test_03_an_action_nobody_registered_says_so(self):
        complaints = ActionRegistry.validate('no.such.action', {})
        self.assertEqual(len(complaints), 1, complaints)
        self.assertIn('no.such.action', complaints[0])

    def test_04_execute_refuses_before_calling_anything(self):
        called = []
        register_probe('probe.refuse', lambda **kw: called.append(1), case=self)
        result = ActionRegistry.execute('probe.refuse', anything=1)
        self.assertFalse(result['success'])
        self.assertEqual(called, [], 'the action ran even though it was refused')

    def test_05_a_wrong_type_is_refused_before_the_action_runs(self):
        result = ActionRegistry.execute('processing.generate_lod',
                                        input_file='a', output_dir='b', levels='three')
        self.assertFalse(result['success'])
        self.assertIn('levels', result['error'])


class ExecutorCase(unittest.TestCase):
    """Every step in order, then one honest verdict."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_6c_steps_')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.executor = WorkflowExecutor()
        register_probe('probe.noop', lambda: {'success': True}, case=self)

    def step(self, name, action, params=None, **kw):
        return WorkflowStep(name=name, action=action, parameters=params or {}, **kw)

    def write(self, name, text='hello'):
        path = os.path.join(self.work, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def test_06_an_empty_workflow_says_there_is_nothing_to_run(self):
        seen = []
        workflow = Workflow('Empty')
        ok = self.executor.execute_workflow(workflow, callback=lambda s, r: seen.append((s, r)))
        self.assertFalse(ok)
        self.assertEqual(len(seen), 1)
        self.assertIn('no steps', seen[0][1]['error'])
        self.assertEqual(workflow.status, TaskStatus.FAILED)

    def test_07_the_steps_run_and_the_copy_lands_on_disk(self):
        source = self.write('hero.obj', 'v 0 0 0')
        target = os.path.join(self.work, 'out', 'hero.obj')
        workflow = Workflow('Copy')
        first = self.step('copy', 'file.copy', {'source': source, 'destination': target})
        second = self.step('again', 'file.copy',
                           {'source': target, 'destination': target + '2'})
        workflow.add_step(first)
        workflow.add_step(second)
        self.assertTrue(self.executor.execute_workflow(workflow))
        self.assertEqual(open(target, encoding='utf-8').read(), 'v 0 0 0')
        self.assertEqual(open(target + '2', encoding='utf-8').read(), 'v 0 0 0')
        self.assertEqual([s.status for s in workflow.steps],
                         [TaskStatus.COMPLETED, TaskStatus.COMPLETED])
        self.assertEqual(workflow.status, TaskStatus.COMPLETED)

    def test_08_a_failing_step_stops_the_run_and_is_named(self):
        workflow = Workflow('Broken')
        ok_first = self.step('good', 'probe.noop')
        bad = self.step('bad', 'file.copy',
                        {'source': os.path.join(self.work, 'not-there.obj'),
                         'destination': os.path.join(self.work, 'x.obj')})
        never = self.step('never', 'probe.noop')
        for one in (ok_first, bad, never):
            workflow.add_step(one)
        seen = []
        self.assertFalse(self.executor.execute_workflow(
            workflow, callback=lambda s, r: seen.append(r)))
        self.assertEqual(seen[0]['failed_step'], 'bad')
        self.assertEqual(seen[0]['steps_completed'], 1)
        self.assertEqual(never.status, TaskStatus.PENDING, 'a step after the failure ran')
        self.assertEqual(bad.error, seen[0]['error'], 'the verdict is not the step\'s own reason')
        self.assertFalse(os.path.exists(os.path.join(self.work, 'x.obj')))

    def test_09_on_error_continue_carries_the_failure_and_the_run_on(self):
        marker = os.path.join(self.work, 'after.txt')
        written = []

        def write_file(path):
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('y')
            written.append(path)
            return {'success': True, 'result': path}

        register_probe('probe.write', write_file,
                       {'path': {'type': 'str', 'required': True}}, case=self)
        workflow = Workflow('Tolerant')
        workflow.add_step(self.step('bad', 'file.copy',
                                    {'source': os.path.join(self.work, 'no.obj'),
                                     'destination': marker}, on_error='continue'))
        workflow.add_step(self.step('good', 'probe.write', {'path': marker}))
        seen = []
        self.assertTrue(self.executor.execute_workflow(
            workflow, callback=lambda s, r: seen.append((s, r))))
        self.assertEqual(written, [marker], 'the tolerated failure stopped the run')
        self.assertEqual(len(seen[0][1]['tolerated_failures']), 1, seen[0][1])
        self.assertIn('bad', seen[0][1]['tolerated_failures'][0])

    def test_10_on_error_retry_retries_exactly_max_retries_more_times(self):
        hits = []

        def flaky(value=True):
            hits.append(value)
            return {'success': bool(value)}

        register_probe('probe.flaky', flaky,
                       {'value': {'type': 'bool', 'required': True}}, case=self)
        workflow = Workflow('Retry')
        step = self.step('flaky', 'probe.flaky', {'value': False},
                         on_error='retry', max_retries=2)
        workflow.add_step(step)
        self.assertFalse(self.executor.execute_workflow(workflow))
        self.assertEqual(len(hits), 3, f'{len(hits)} attempts, wanted the first plus 2 retries')
        self.assertEqual(step.status, TaskStatus.FAILED)

    def test_11_progress_names_each_step_before_it_runs(self):
        workflow = Workflow('Three')
        for index in range(3):
            workflow.add_step(self.step(f'step{index}', 'probe.noop'))
        seen = []
        self.executor.execute_workflow(workflow,
                                       progress=lambda c, t, n: seen.append((c, t, n)))
        self.assertEqual(seen, [(1, 3, 'step0'), (2, 3, 'step1'), (3, 3, 'step2')], seen)
        self.assertEqual(workflow.current_step, 3)

    def test_12_a_stop_asked_between_steps_leaves_the_rest_alone(self):
        workflow = Workflow('Stop')
        for index in range(4):
            workflow.add_step(self.step(f's{index}', 'probe.noop'))
        seen = []
        self.assertFalse(self.executor.execute_workflow(
            workflow, callback=lambda s, r: seen.append(r),
            should_stop=lambda: workflow.current_step >= 2))
        self.assertTrue(seen[0]['stopped'])
        self.assertIn('s2', seen[0]['error'])
        self.assertEqual([s.status for s in workflow.steps][3], TaskStatus.PENDING)
        self.assertEqual(workflow.status, TaskStatus.CANCELLED)

    def test_13_the_verdict_survives_a_save_and_a_read(self):
        workflow = Workflow('Kept', 'a description')
        workflow.add_step(self.step('copy', 'file.copy', {'source': 'a', 'destination': 'b'},
                                    on_error='continue'))
        self.executor.execute_workflow(workflow)
        record = workflow.to_dict()
        again = Workflow.from_dict(record)
        self.assertEqual(again.workflow_id, workflow.workflow_id)
        self.assertEqual(again.name, 'Kept')
        self.assertEqual(again.description, 'a description')
        self.assertEqual(again.status, workflow.status)
        self.assertEqual(again.error, workflow.error)
        self.assertEqual([s.action for s in again.steps], ['file.copy'])
        self.assertEqual([s.on_error for s in again.steps], ['continue'])
        self.assertEqual(again.to_dict(), record)


class EngineWorkflowCase(unittest.TestCase):
    """The engine stores, copies, deletes and runs what the pane builds."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.home = tempfile.mkdtemp(prefix='renderfox_6c_eng_')
        cls.real_home = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: cls.home

    @classmethod
    def tearDownClass(cls):
        engine_module.app_data_dir = cls.real_home
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.engine = AutomationEngine()
        self.addCleanup(self.engine.stop)
        self.work = tempfile.mkdtemp(prefix='renderfox_6c_run_')
        self.addCleanup(shutil.rmtree, self.work, True)

    def record(self, name='copy', action='file.copy', params=None, **kw):
        one = {'name': name, 'action': action, 'parameters': params or {}}
        one.update(kw)
        return one

    def spin(self, want, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if want():
                return True
            time.sleep(0.02)
        return False

    def test_14_create_stores_real_steps_under_the_id_the_workflow_owns(self):
        workflow_id = self.engine.create_workflow(
            'Nightly', 'copies then logs',
            [self.record(params={'source': 'a', 'destination': 'b'})])
        stored = self.engine.workflows[workflow_id]
        self.assertIsInstance(stored, Workflow)
        self.assertEqual(stored.name, 'Nightly')
        self.assertEqual(len(stored.steps), 1)
        self.assertIsInstance(stored.steps[0], WorkflowStep)
        self.assertEqual(stored.steps[0].parameters, {'source': 'a', 'destination': 'b'})
        self.assertEqual(list(self.engine.workflows), [workflow_id])

    def test_15_the_workflows_file_is_the_engines_own_and_reloads(self):
        workflow_id = self.engine.create_workflow('On disk', 'kept', [self.record()])
        path = os.path.join(self.home, 'workflows.json')
        self.assertTrue(os.path.exists(path), 'nothing was written where the app looks')
        rebuilt = AutomationEngine()
        self.addCleanup(rebuilt.stop)
        self.assertIn(workflow_id, rebuilt.workflows)
        self.assertEqual(rebuilt.workflows[workflow_id].name, 'On disk')
        self.assertEqual(rebuilt.workflows[workflow_id].description, 'kept')
        self.assertEqual(len(rebuilt.workflows[workflow_id].steps), 1)

    def test_16_update_changes_only_what_it_was_given(self):
        workflow_id = self.engine.create_workflow(
            'First', 'keep me', [self.record(params={'source': 'a', 'destination': 'b'})])
        self.assertTrue(self.engine.update_workflow(workflow_id, name='Second'))
        stored = self.engine.workflows[workflow_id]
        self.assertEqual(stored.name, 'Second')
        self.assertEqual(stored.description, 'keep me')
        self.assertEqual(len(stored.steps), 1)
        self.assertTrue(self.engine.update_workflow(workflow_id, steps=[]))
        self.assertEqual(self.engine.workflows[workflow_id].steps, [])
        self.assertFalse(self.engine.update_workflow('no-such-id', name='x'))

    def test_17_duplicate_makes_a_new_id_and_fresh_step_ids(self):
        workflow_id = self.engine.create_workflow(
            'Original', 'notes',
            [self.record(params={'source': 'a', 'destination': 'b'})])
        copy_id = self.engine.duplicate_workflow(workflow_id)
        self.assertNotEqual(copy_id, workflow_id)
        original = self.engine.workflows[workflow_id]
        copy = self.engine.workflows[copy_id]
        self.assertEqual(copy.name, 'Original copy')
        self.assertEqual(copy.description, 'notes')
        self.assertEqual([s.parameters for s in copy.steps],
                         [s.parameters for s in original.steps])
        self.assertNotEqual(copy.steps[0].step_id, original.steps[0].step_id)
        self.assertIsNone(self.engine.duplicate_workflow('no-such-id'))

    def test_18_delete_leaves_the_list_the_file_and_nothing_else(self):
        workflow_id = self.engine.create_workflow('Doomed', '', [self.record()])
        self.assertTrue(self.engine.delete_workflow(workflow_id))
        self.assertNotIn(workflow_id, self.engine.workflows)
        with open(os.path.join(self.home, 'workflows.json'), encoding='utf-8') as handle:
            data = json.load(handle)
        self.assertNotIn(workflow_id, data)
        self.assertFalse(self.engine.delete_workflow(workflow_id))

    def test_19_problems_names_every_reason_before_anything_runs(self):
        complaints = self.engine.workflow_problems('', [])
        self.assertIn('a workflow needs a name', ' '.join(complaints))
        self.assertIn('at least one step', ' '.join(complaints))
        complaints = self.engine.workflow_problems('X', [self.record(action='nope.nope'),
                                                         self.record(name='blank', action='')])
        self.assertTrue(any('nope.nope' in one for one in complaints), complaints)
        self.assertTrue(any('names no action' in one for one in complaints), complaints)
        complaints = self.engine.workflow_problems(
            'X', [self.record(params={'source': 'a', 'destination': 'b'}, on_error='explode')])
        self.assertTrue(any('explode' in one for one in complaints), complaints)
        self.assertEqual(self.engine.workflow_problems(
            'X', [self.record(params={'source': 'a', 'destination': 'b'})]), [])

    def test_20_an_unknown_id_and_an_empty_workflow_say_no(self):
        self.assertFalse(self.engine.execute_workflow('no-such-id'))
        workflow_id = self.engine.create_workflow('Bare', '', [self.record()])
        self.engine.update_workflow(workflow_id, steps=[])
        self.assertFalse(self.engine.execute_workflow(workflow_id))

    def test_21_the_signals_carry_what_the_run_really_did(self):
        source = os.path.join(self.work, 'hero.obj')
        with open(source, 'w', encoding='utf-8') as handle:
            handle.write('v 0 0 0')
        target = os.path.join(self.work, 'hero2.obj')
        started, done, failed, progress = [], [], [], []
        self.engine.workflow_started.connect(lambda wid: started.append(wid))
        self.engine.workflow_completed.connect(lambda wid, result: done.append((wid, result)))
        self.engine.workflow_failed.connect(lambda wid, error: failed.append((wid, error)))
        self.engine.workflow_progress.connect(
            lambda wid, current, total, name: progress.append((current, total, name)))

        workflow_id = self.engine.create_workflow('Real', '', [
            self.record(params={'source': source, 'destination': target})])
        self.assertTrue(self.engine.execute_workflow(workflow_id))
        self.assertTrue(self.spin(lambda: done or failed), 'the run reported nothing')
        self.assertEqual(started, [workflow_id], 'workflow_started never reached the app')
        self.assertEqual(failed, [], 'a run that worked came back as a failure')
        self.assertEqual([wid for wid, _ in done], [workflow_id])
        self.assertTrue(done[0][1]['success'])
        self.assertEqual(done[0][1]['steps_completed'], 1)
        self.assertEqual(progress, [(1, 1, 'copy')], progress)
        with open(target, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'v 0 0 0',
                             'the workflow reported success and copied nothing')
        self.assertEqual(self.engine.workflows[workflow_id].status, TaskStatus.COMPLETED)

    def test_22_a_failing_run_reaches_the_failure_signal_with_its_reason(self):
        failed, done = [], []
        self.engine.workflow_failed.connect(lambda wid, error: failed.append((wid, error)))
        self.engine.workflow_completed.connect(lambda wid, result: done.append(result))
        workflow_id = self.engine.create_workflow('Bad', '', [
            self.record(name='ghost', params={'source': os.path.join(self.work, 'nope.obj'),
                                              'destination': os.path.join(self.work, 'x.obj')})])
        self.assertTrue(self.engine.execute_workflow(workflow_id))
        self.assertTrue(self.spin(lambda: failed), 'the failing run reported nothing')
        self.assertEqual([wid for wid, _ in failed], [workflow_id])
        self.assertIn('nope.obj', failed[0][1])
        self.assertEqual(done, [], 'a failed run also reported success')
        self.assertEqual(self.engine.workflows[workflow_id].status, TaskStatus.FAILED)

    def test_23_stop_asks_the_worker_to_leave_the_rest_alone(self):
        def slow():
            time.sleep(0.3)
            return {'success': True}

        register_probe('probe.slow', slow, case=self)
        done = []
        self.engine.workflow_completed.connect(lambda wid, result: done.append(result))
        workflow_id = self.engine.create_workflow('Slow', '', [
            self.record(name=f's{index}', action='probe.slow') for index in range(4)])
        self.assertTrue(self.engine.execute_workflow(workflow_id))
        self.assertTrue(self.spin(lambda: self.engine.workflows[workflow_id].status
                                  == TaskStatus.RUNNING), 'the run never reached the worker')
        self.assertTrue(self.engine.stop_workflow(workflow_id))
        self.assertTrue(self.spin(lambda: bool(done)), 'a stopped workflow reported nothing')
        self.assertTrue(done[0].get('stopped'), done[0])
        self.assertLess(done[0]['steps_completed'], 4, 'it ran every step anyway')
        self.assertEqual(self.engine.workflows[workflow_id].status, TaskStatus.CANCELLED)

    def test_24_stop_of_an_unknown_id_says_no(self):
        self.assertFalse(self.engine.stop_workflow('no-such-id'))

    def test_25_a_workflow_is_run_by_the_engine_not_by_a_thread_nobody_builds(self):
        with open(os.path.join(ROOT, 'src', 'ui', 'automation_tab.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        for needle in ('WorkflowExecutionThread', 'Simulation fallback', 'msleep(500)'):
            self.assertNotIn(needle, source, f'{needle} is back in the pane')


class PaneCase(unittest.TestCase):
    """The Workflow Builder the user clicks: each control reaches the engine or says why."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.home = tempfile.mkdtemp(prefix='renderfox_6c_panehome_')
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
        self.work = tempfile.mkdtemp(prefix='renderfox_6c_pane_')
        self.addCleanup(shutil.rmtree, self.work, True)
        for name in ('tasks.json', 'workflows.json'):
            path = os.path.join(self.home, name)
            if os.path.exists(path):
                os.remove(path)
        self.popups.clear()
        self.tab = AutomationTab()
        self.addCleanup(self.tab.automation_engine.stop)

    # --- helpers ---------------------------------------------------------------
    def tab_source(self):
        with open(os.path.join(ROOT, 'src', 'ui', 'automation_tab.py'),
                  encoding='utf-8') as handle:
            return handle.read()

    def activity(self):
        return [self.tab.activity_list.item(i).text()
                for i in range(self.tab.activity_list.count())]

    def workflow_source(self):
        """Only the Workflow Builder's own code: its tab and the methods behind it."""
        source = self.tab_source()
        parts = []
        for first, last in (('    def create_workflow_builder_tab(self):',
                             '    def create_batch_operations_tab(self):'),
                            ('    # --- Workflow Builder',
                             '    def on_task_started(self, task_id):')):
            start = source.index(first)
            parts.append(source[start:source.index(last, start)])
        return '\n'.join(parts)

    def list_rows(self):
        return [self.tab.workflows_list.item(i).text()
                for i in range(self.tab.workflows_list.count())]

    def step_rows(self):
        table = self.tab.steps_table
        rows = []
        for row in range(table.rowCount()):
            action = table.cellWidget(row, 2)
            policy = table.cellWidget(row, 4)
            name = table.item(row, 1)
            params = table.item(row, 3)
            rows.append([(name.text() if name else ''),
                         action.currentData() if action else '',
                         (params.text() if params else ''),
                         policy.currentData() if policy else ''])
        return rows

    def written(self, name, text='v 0 0 0'):
        path = os.path.join(self.work, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def copy_step(self, name, source, destination):
        return (name, 'file.copy',
                json.dumps({'source': source, 'destination': destination}))

    def fill(self, name='Nightly copy', steps=(('copy', 'file.copy', '"source": "a", '
                                                                     '"destination": "b"'),)):
        self.tab.new_workflow()
        self.tab.workflow_name_edit.setText(name)
        self.tab.steps_table.setRowCount(0)
        for one in steps:
            self.tab.add_workflow_step(*one)

    def spin(self, want, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if want():
                return True
            time.sleep(0.02)
        return False

    def warnings(self):
        return [str(args[2]) for kind, args in self.popups if kind == 'warning']

    # --- the pane's own wiring -------------------------------------------------
    def test_26_every_workflow_control_is_connected(self):
        for name in ('new_workflow_btn', 'save_workflow_btn', 'load_workflow_btn',
                     'duplicate_workflow_btn', 'delete_workflow_btn', 'run_workflow_btn',
                     'test_workflow_btn', 'stop_workflow_btn', 'add_step_btn',
                     'remove_step_btn', 'move_up_btn', 'move_down_btn'):
            button = getattr(self.tab, name)
            self.assertTrue(button.receivers(button.clicked), f'{name} is still a dead button')
        self.assertTrue(self.tab.workflows_list.receivers(
            self.tab.workflows_list.itemSelectionChanged))

    def test_27_the_list_shows_stored_workflows_and_no_invented_names(self):
        """Five names no object ever had, and a description made up on selection."""
        self.assertEqual(self.list_rows(), [])
        self.assertEqual(self.tab.workflows_list.count(),
                         len(self.tab.automation_engine.workflows))
        stored = self.tab.automation_engine.create_workflow('From disk', 'a real note', [
            {'name': 'copy', 'action': 'file.copy',
             'parameters': {'source': 'a', 'destination': 'b'}, 'on_error': 'retry'}])
        self.addCleanup(lambda: self.tab.automation_engine.workflows.pop(stored, None))
        self.tab.refresh_workflow_list()
        self.assertEqual([row for row in self.list_rows() if 'From disk' in row],
                         ['From disk [pending]'])
        source = self.workflow_source()
        for needle in ('Model Conversion Pipeline', 'Batch LOD Generation', 'Texture Optimization',
                       'Quality Assurance Check', 'Daily Report Generation', 'load_sample_data',
                       'Description for', "step_name.lower().replace(' ', '_')",
                       '"Always"', 'If valid', 'Condition'):
            self.assertNotIn(needle, source, f'{needle} is back in the pane')

    def test_28_the_action_cell_offers_the_registry_ids(self):
        self.tab.add_workflow_step()
        combo = self.tab.steps_table.cellWidget(0, 2)
        offered = {combo.itemData(i) for i in range(combo.count())}
        self.assertEqual(offered, set(ActionRegistry.get_all_actions()))
        self.assertIn('system.run_command', offered)
        self.assertEqual(self.tab.steps_table.horizontalHeaderItem(3).text(), 'Parameters')

    def test_29_the_on_error_cell_offers_only_what_the_executor_honours(self):
        self.tab.add_workflow_step()
        combo = self.tab.steps_table.cellWidget(0, 4)
        self.assertEqual([combo.itemData(i) for i in range(combo.count())],
                         list(WorkflowStep.ON_ERROR))
        self.assertEqual(combo.currentData(), 'stop')

    def test_30_new_clears_the_editor_and_detaches_the_stored_id(self):
        self.fill(name='Something')
        self.tab.save_workflow_btn.click()
        first_id = self.tab.current_workflow_id
        self.assertIsNotNone(first_id)
        self.tab.new_workflow()
        self.assertIsNone(self.tab.current_workflow_id)
        self.assertEqual(self.tab.workflow_name_edit.text(), '')
        self.assertEqual(self.tab.steps_table.rowCount(), 0)
        self.fill(name='Something else')
        self.tab.save_workflow_btn.click()
        self.assertNotEqual(self.tab.current_workflow_id, first_id)
        self.assertEqual(sorted(one.name for one in self.tab.automation_engine.workflows.values()),
                         ['Something', 'Something else'])

    def test_31_saving_writes_a_record_the_engine_and_the_disk_both_have(self):
        self.fill(name='Backup pass',
                  steps=(('copy', 'file.copy', '"source": "a", "destination": "b"', 'continue'),
                         ('log', 'system.run_command', '"command": "echo hi"', 'retry')))
        self.tab.save_workflow_btn.click()
        self.assertEqual([kind for kind, _ in self.popups], [], f'{self.popups}')
        workflow_id = self.tab.current_workflow_id
        stored = self.tab.automation_engine.workflows[workflow_id]
        self.assertEqual(stored.name, 'Backup pass')
        self.assertEqual([step.action for step in stored.steps],
                         ['file.copy', 'system.run_command'])
        self.assertEqual([step.on_error for step in stored.steps], ['continue', 'retry'])
        with open(os.path.join(self.home, 'workflows.json'), encoding='utf-8') as handle:
            records = json.load(handle)
        self.assertEqual(sorted(records), [workflow_id])
        self.assertEqual(records[workflow_id]['steps'][0]['parameters'],
                         {'source': 'a', 'destination': 'b'})
        self.assertIn('Backup pass', self.list_rows()[0])

    def test_32_a_workflow_with_no_step_is_refused_and_stays_unstored(self):
        self.tab.new_workflow()
        self.tab.workflow_name_edit.setText('Nothing in it')
        self.tab.save_workflow_btn.click()
        self.assertEqual(self.tab.automation_engine.workflows, {})
        self.assertIsNone(self.tab.current_workflow_id)
        self.assertTrue(any('at least one step' in text for text in self.warnings()),
                        self.warnings())

    def test_33_a_nameless_workflow_is_refused(self):
        self.fill(name='   ')
        self.tab.save_workflow_btn.click()
        self.assertEqual(self.tab.automation_engine.workflows, {})
        self.assertTrue(any('needs a name' in text for text in self.warnings()), self.warnings())

    def test_34_a_step_whose_parameters_are_not_data_is_refused(self):
        marker = os.path.join(self.work, 'pwned.txt').replace('\\', '/')
        self.fill(steps=((('evil', 'file.copy',
                           f'"source": __import__("os").popen("echo x > \\"{marker}\\").read()'),)))
        self.tab.save_workflow_btn.click()
        self.assertEqual(self.tab.automation_engine.workflows, {})
        self.assertFalse(os.path.exists(marker), 'the parameters were evaluated')
        self.assertTrue(any('name/value pairs' in text for text in self.warnings()),
                        self.warnings())

    def test_35_a_step_missing_a_required_value_is_named_before_it_runs(self):
        self.fill(steps=(('half a copy', 'file.copy', '"source": "a"'),))
        self.tab.save_workflow_btn.click()
        self.assertEqual(self.tab.automation_engine.workflows, {})
        self.assertTrue(any('destination' in text for text in self.warnings()), self.warnings())

    def test_36_test_workflow_proves_the_order_without_running_any_of_it(self):
        source = self.written('hero.obj')
        target = os.path.join(self.work, 'out.obj')
        started = []
        self.tab.automation_engine.workflow_started.connect(lambda wid: started.append(wid))
        self.fill(name='Dry run', steps=(self.copy_step('copy', source, target),))
        self.tab.test_workflow_btn.click()
        # A worker that had been handed the run needs a moment to write, so give it one
        # before looking; checking the disk on the same tick proves nothing.
        self.spin(lambda: False, timeout=0.6)
        self.assertEqual(started, [], 'Test Workflow handed the workflow to the engine')
        self.assertIsNone(self.tab._running_workflow, 'the pane counts a check as a run')
        self.assertEqual(self.tab.active_workflows, {}, 'a check was counted as active work')
        self.assertFalse(os.path.exists(target), 'Test Workflow ran the step it was checking')
        kinds = [kind for kind, _ in self.popups]
        self.assertEqual(kinds, ['information'], self.popups)
        text = str(self.popups[0][1][2])
        self.assertIn('Dry run', text)
        self.assertIn('file.copy', text)
        self.assertIn('would run 1 step', text)

    def test_37_test_workflow_says_which_step_cannot_run(self):
        self.fill(name='Broken', steps=(('bad', 'processing.generate_lod', '"levels": 3'),))
        self.tab.test_workflow_btn.click()
        kinds = [kind for kind, _ in self.popups]
        self.assertEqual(kinds, ['warning'], self.popups)
        self.assertIn('input_file', self.warnings()[0])

    def test_38_run_stores_then_executes_and_the_copy_lands_on_disk(self):
        source = self.written('hero.obj', 'v 1 1 1')
        target = os.path.join(self.work, 'out.obj')
        self.fill(name='Real run', steps=(self.copy_step('copy', source, target),))
        self.tab.run_workflow_btn.click()
        self.assertTrue(self.spin(lambda: any('completed' in line for line in self.activity())),
                        f'no verdict: {self.activity()}')
        with open(target, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'v 1 1 1', 'the pane claimed a copy it did not do')
        stored = self.tab.automation_engine.workflows[self.tab.current_workflow_id]
        self.assertEqual(stored.status, TaskStatus.COMPLETED)
        lines = self.activity()
        self.assertTrue(any('started' in line for line in lines), lines)
        self.assertTrue(any('step 1/1: copy' in line for line in lines), lines)
        self.assertTrue(any("completed 1/1 step(s)" in line for line in lines), lines)
        self.assertTrue(self.tab.run_workflow_btn.isEnabled())
        self.assertFalse(self.tab.stop_workflow_btn.isEnabled())
        self.assertEqual(self.tab.active_workflows, {}, 'the run is still counted as active')

    def test_39_a_failing_run_reports_the_reason_and_no_success(self):
        missing = os.path.join(self.work, 'not-here.obj')
        target = os.path.join(self.work, 'out.obj')
        self.fill(name='Failed run', steps=(self.copy_step('copy', missing, target),))
        self.tab.run_workflow_btn.click()
        self.assertTrue(self.spin(lambda: any('FAILED' in line for line in self.activity())),
                        f'no failure reported: {self.activity()}')
        lines = self.activity()
        self.assertTrue(any('not-here.obj' in line for line in lines), lines)
        self.assertFalse(any('completed' in line for line in lines), lines)
        self.assertEqual([kind for kind, _ in self.popups if kind == 'information'], [],
                         'a failed run was announced with a success box')
        self.assertFalse(os.path.exists(target))
        self.assertEqual(self.tab.automation_engine.workflows[
            self.tab.current_workflow_id].status, TaskStatus.FAILED)
        self.assertTrue(self.tab.run_workflow_btn.isEnabled())

    def test_40_a_workflow_verdict_never_lands_in_the_batch_tab(self):
        """The builder used to drive the batch pane's progress bar and log."""
        source = self.written('hero.obj')
        target = os.path.join(self.work, 'out.obj')
        before_bar = self.tab.batch_progress.value()
        before_log = self.tab.batch_log.toPlainText()
        before_label = self.tab.batch_status_label.text()
        self.fill(name='Not batch', steps=(self.copy_step('copy', source, target),))
        self.tab.run_workflow_btn.click()
        self.assertTrue(self.spin(lambda: any('completed' in line for line in self.activity())))
        self.assertEqual(self.tab.batch_progress.value(), before_bar,
                         'the batch bar moved for a workflow')
        self.assertEqual(self.tab.batch_log.toPlainText(), before_log,
                         'the batch log was written to for a workflow')
        self.assertEqual(self.tab.batch_status_label.text(), before_label)

    def test_41_stop_is_asked_of_the_engine_and_the_steps_left_behind(self):
        count = []

        def slow():
            count.append(1)
            time.sleep(0.3)
            return {'success': True}

        register_probe('probe.slow', slow, case=self)
        self.fill(name='Long run',
                  steps=tuple((f's{index}', 'probe.slow', '{}') for index in range(6)))
        self.tab.run_workflow_btn.click()
        self.assertTrue(self.spin(lambda: len(count) >= 1), 'the run never started')
        self.assertFalse(self.tab.run_workflow_btn.isEnabled(), 'Run stayed clickable')
        self.assertTrue(self.tab.stop_workflow_btn.isEnabled())
        self.tab.stop_workflow_btn.click()
        self.assertTrue(self.spin(lambda: any('stopped after' in line for line in self.activity())),
                        f'no stop verdict: {self.activity()}')
        self.assertLess(len(count), 6, 'it ran every step after being told to stop')
        self.assertEqual(self.tab.automation_engine.workflows[
            self.tab.current_workflow_id].status, TaskStatus.CANCELLED)

    def test_42_stop_without_a_run_says_so_instead_of_claiming_one(self):
        self.tab.stop_workflow_btn.setEnabled(True)
        self.tab.stop_workflow_btn.click()
        self.assertTrue(any('no workflow running' in text.lower() for text in self.warnings()),
                        self.warnings())

    def test_43_selecting_a_stored_workflow_loads_what_the_engine_holds(self):
        source = self.written('hero.obj')
        workflow_id = self.tab.automation_engine.create_workflow(
            'On the list', 'written once, read back',
            [{'name': 'only step', 'action': 'file.copy',
              'parameters': {'source': source, 'destination': 'D:/ nowhere.obj'},
              'on_error': 'continue'}])
        self.tab.refresh_workflow_list()
        self.tab.workflows_list.setCurrentRow(0)
        self.app.processEvents()
        self.assertEqual(self.tab.current_workflow_id, workflow_id)
        self.assertEqual(self.tab.workflow_name_edit.text(), 'On the list')
        self.assertEqual(self.tab.workflow_description_edit.toPlainText(), 'written once, read back')
        rows = self.step_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'only step')
        self.assertEqual(rows[0][1], 'file.copy')
        self.assertEqual(json.loads(rows[0][2]),
                         {'source': source, 'destination': 'D:/ nowhere.obj'})
        self.assertEqual(rows[0][3], 'continue')

    def test_44_moving_a_step_changes_the_order_the_engine_will_run(self):
        self.fill(name='Two steps', steps=(('first', 'file.copy', '"source": "a", "destination": "b"'),
                                           ('second', 'system.run_command', '"command": "echo x"')))
        self.tab.steps_table.setCurrentCell(1, 1)
        self.tab.move_up_btn.click()
        self.assertEqual([row[0] for row in self.step_rows()], ['second', 'first'])
        self.tab.save_workflow_btn.click()
        stored = self.tab.automation_engine.workflows[self.tab.current_workflow_id]
        self.assertEqual([step.name for step in stored.steps], ['second', 'first'])
        self.assertEqual([step.action for step in stored.steps],
                         ['system.run_command', 'file.copy'])

    def test_45_moving_past_the_end_is_refused_not_silently_ignored(self):
        self.fill(name='Single', steps=(('only', 'file.copy', '"source": "a", '
                                                         '"destination": "b"'),))
        self.tab.steps_table.setCurrentCell(0, 1)
        self.tab.move_up_btn.click()
        self.assertTrue(any('already at the top' in text for text in self.warnings()),
                        self.warnings())
        self.assertEqual([row[0] for row in self.step_rows()], ['only'])

    def test_46_removing_a_step_drops_it_and_renumbers_the_rest(self):
        self.fill(name='Three', steps=tuple(
            (f's{index}', 'file.copy', '"source": "a", "destination": "b"')
            for index in range(3)))
        self.tab.steps_table.setCurrentCell(1, 1)
        self.tab.remove_step_btn.click()
        self.assertEqual([row[0] for row in self.step_rows()], ['s0', 's2'])
        self.assertEqual([self.tab.steps_table.item(r, 0).text() for r in range(2)], ['1', '2'])

    def test_47_duplicate_copies_the_stored_workflow_into_list_and_file(self):
        self.fill(name='Original', steps=(('copy', 'file.copy', '"source": "a", '
                                                            '"destination": "b"'),))
        self.tab.save_workflow_btn.click()
        original = self.tab.current_workflow_id
        self.tab.duplicate_workflow_btn.click()
        copy_id = self.tab.current_workflow_id
        self.assertNotEqual(copy_id, original)
        self.assertEqual(self.tab.automation_engine.workflows[copy_id].name, 'Original copy')
        self.assertEqual(self.tab.workflow_name_edit.text(), 'Original copy',
                         'the editor still shows the workflow that was copied from')
        self.assertEqual(len(self.tab.automation_engine.workflows), 2)
        with open(os.path.join(self.home, 'workflows.json'), encoding='utf-8') as handle:
            self.assertEqual(sorted(json.load(handle)), sorted([original, copy_id]))
        self.assertEqual(len(self.list_rows()), 2)

    def test_48_delete_removes_it_from_the_list_the_engine_and_the_file(self):
        self.fill(name='Doomed', steps=(('copy', 'file.copy', '"source": "a", '
                                                           '"destination": "b"'),))
        self.tab.save_workflow_btn.click()
        workflow_id = self.tab.current_workflow_id
        self.tab.delete_workflow_btn.click()
        self.assertNotIn(workflow_id, self.tab.automation_engine.workflows)
        self.assertEqual(self.list_rows(), [])
        self.assertIsNone(self.tab.current_workflow_id)
        self.assertEqual(self.tab.workflow_name_edit.text(), '')
        with open(os.path.join(self.home, 'workflows.json'), encoding='utf-8') as handle:
            self.assertNotIn(workflow_id, json.load(handle))

    def test_49_duplicate_and_delete_refuse_a_workflow_that_was_never_saved(self):
        self.tab.new_workflow()
        self.tab.duplicate_workflow_btn.click()
        self.tab.delete_workflow_btn.click()
        kinds = [kind for kind, _ in self.popups]
        self.assertEqual(kinds, ['warning', 'warning'], self.popups)
        self.assertEqual(self.tab.automation_engine.workflows, {})

    def test_50_load_reads_a_file_into_the_engine_and_refuses_what_cannot_run(self):
        good = {'name': 'From a file', 'description': 'imported',
                'steps': [{'name': 'copy', 'action': 'file.copy',
                           'parameters': {'source': 'a', 'destination': 'b'}}]}
        bad = {'name': 'Broken', 'steps': [{'name': 'ghost', 'action': 'no.such.action',
                                            'parameters': {}}]}
        path = os.path.join(self.work, 'bundle.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump([good, bad], handle)
        previous = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = lambda *a, **k: (path, '')
        self.addCleanup(setattr, QFileDialog, 'getOpenFileName', previous)
        self.tab.load_workflow_btn.click()
        loaded = [one for one in self.tab.automation_engine.workflows.values()
                  if one.name == 'From a file']
        self.assertEqual(len(loaded), 1, 'the valid workflow did not arrive')
        self.assertEqual(loaded[0].description, 'imported')
        self.assertEqual([one.name for one in self.tab.automation_engine.workflows.values()],
                         ['From a file'], 'a workflow nothing can run was stored anyway')
        self.assertTrue(any('no.such.action' in text for text in self.warnings()), self.warnings())

    def test_51_a_file_that_is_not_a_workflow_is_read_as_one_and_refused(self):
        path = os.path.join(self.work, 'broken.json')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('{"name": "no steps key", "description": "x"}')
        previous = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = lambda *a, **k: (path, '')
        self.addCleanup(setattr, QFileDialog, 'getOpenFileName', previous)
        self.tab.load_workflow_btn.click()
        self.assertEqual(self.tab.automation_engine.workflows, {})
        self.assertTrue(any('holds no record' in text for text in self.warnings()),
                        self.warnings())

    def test_52_the_dashboard_counts_the_workflows_the_engine_has(self):
        self.fill(name='Counted', steps=(('copy', 'file.copy', '"source": "a", '
                                                             '"destination": "b"'),))
        self.tab.save_workflow_btn.click()
        self.assertEqual(self.tab.active_workflows_label.text(), '0')
        self.tab.active_workflows['somewhere-else'] = 'Counted'
        self.tab.update_dashboard_metrics()
        self.assertEqual(self.tab.active_workflows_label.text(), '1')
        self.fill(name='Second counted', steps=(('copy', 'file.copy', '"source": "a", '
                                                                 '"destination": "b"'),))
        self.tab.save_workflow_btn.click()
        self.assertEqual(len(self.tab.automation_engine.workflows), 2)
        self.assertEqual(self.tab.workflows_list.count(), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
