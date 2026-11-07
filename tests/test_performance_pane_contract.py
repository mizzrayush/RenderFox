"""The Performance pane contract - the tables are the screen, and the store door is the refusal.

`test_performance_backend_contract.py` covers what the machine was asked and what it answered:
the frame clock, the monitor, the score, the benchmark engine and the words those hand to a
table. This file covers the other half of 7b: the pane that paints those words, the control
table that says what each box does, and the one door through which a box may reach the
settings store.

It is a separate process because the two halves answer different questions about the same
line of code. A sweep that plants a defect in `write_control` wants to know which pane test
notices; run against the machine tests in one file the same sweep paid **240 s** per defect,
and the pane classes alone answer in **50 s** (measured on this tree, 35 tests). These classes
also build a `PerformanceTab` per test and drain the global thread pool around it, which is
the slow part of the whole performance suite - and the reason the machine half, on its own,
is back to 118 tests in **29 s**.

What is pinned here, in order:

* the boxes on the screen are exactly the rows of `performance_controls.CONTROLS` - by name,
  by object, by widget-tree count - and every widget is built in one method off one row;
* no range, no item list and no seeded figure is the pane's own; a box that cannot show the
  store's number says so, and the engine is the only thing that refuses a value;
* every control prints the verdict its row carries, refused controls stay visible, and the
  contract table repeats the two tables' wording rather than inventing its own;
* the sixteen buttons are the sixteen verbs, each connected to the method the table names,
  each producing the artefact the table claims, with a dead connection reported as a failure;
* a stored value lands on the key its reader looks in - the Post-Processing box included -
  an out-of-range value is shown and refused rather than corrected, a refused priority never
  reaches Windows, and constructing the pane runs no verb and writes no key;
* a profile is the values on screen: the knobs it may name are the controls an engine honours,
  applying one writes them and runs their verbs, and `applied_profile` is a record that is
  never re-applied at start-up.

Run: python -X utf8 tests/test_performance_pane_contract.py
"""

import ast
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

# The machine half of this contract already owns the figures, the words and the paths a pane
# test has to read; importing it is the only way to check the pane against the same source
# the other suite checks the engine against, rather than a copy that can drift.
from tests.test_performance_backend_contract import (  # noqa: E402
    PANE, BenchmarkHistory, PerformanceMetrics, code_of, source)

# ---- 7b-1 + 7b-2: the pane is the tables, and the tables are the machine ----------------

STORE_BACKUP = []

WIDGET_KINDS = ('QSpinBox', 'QComboBox', 'QCheckBox', 'QLineEdit')

# The figures the pane used to carry before anything had read them. Each one is measured
# off the machine that shipped it, so a return of any of them is a claim about a machine
# this app has never looked at.
SEEDED_FIGURES = ('45%', '6,847', '72 degC', '285W', '16.7 ms', '16.0 GB', '8.5 GB',
                  '2.3 GB', 'Top 1%')


def isolated_store():
    """Point the app's one settings store at a fresh ini file and hand back its path.

    These classes drive controls, and a driven control writes. `RENDERFOX_SETTINGS_PATH` is
    how a suite persists a setting without becoming the thing that changed this machine's
    real ones - and an empty file is the only way a test can know nothing was stored yet.
    """
    from src.utils import app_settings
    path = os.path.join(tempfile.mkdtemp(prefix='rf-perf-store-'), 'store.ini')
    STORE_BACKUP.append(os.environ.get('RENDERFOX_SETTINGS_PATH'))
    os.environ['RENDERFOX_SETTINGS_PATH'] = path
    app_settings.reset()
    return path


def restore_store():
    """Put the store back where the suite found it, so nothing leaks into the next class."""
    from src.utils import app_settings
    previous = STORE_BACKUP.pop()
    if previous is None:
        os.environ.pop('RENDERFOX_SETTINGS_PATH', None)
    else:
        os.environ['RENDERFOX_SETTINGS_PATH'] = previous
    app_settings.reset()


def stored_controls():
    """The controls a start-up has to honour: wired and with a key. Twelve, measured here."""
    from src.features import performance_controls as pc
    return [name for name, item in pc.CONTROLS.items() if item.wired and item.key]


class PaneHarness:
    """The pane, on its own store, with every timer taken off before it closes."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtCore import QThreadPool
        from src.ui.performance_tab import PerformanceTab
        QThreadPool.globalInstance().waitForDone(15000)
        self.store_path = isolated_store()
        self.tab = PerformanceTab()
        self.tab.performance_analyzer.stop_everything()
        self.tab.update_timer.stop()

    def tearDown(self):
        from PyQt6.QtCore import QThreadPool
        self.tab.performance_analyzer.stop_everything()
        self.tab.update_timer.stop()
        QThreadPool.globalInstance().waitForDone(15000)
        self.tab.close()
        self.app.processEvents()
        restore_store()

    def pump(self, seconds=30.0, until=None):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)
            if until and until():
                return True
        return until() if until else False

    def cells(self, table, row):
        return [(table.item(row, column).text() if table.item(row, column) else '')
                for column in range(table.columnCount())]


class Test110TheTableIsThePane(PaneHarness, unittest.TestCase):
    """Every box, line and figure on the pane is a table row's - or it is not on the pane.

    7b-1 moved the truth about the controls into `performance_controls.CONTROLS` and `VERBS`
    and 7b-2 rebuilt the pane off them. What keeps that honest is a test that cannot be
    satisfied by the pane agreeing with itself: these read the tables, the widget tree and
    the source, and fail on a widget no row speaks for, a range typed into the pane, a
    seeded figure, an unwritten verdict line or a deleted refusal.
    """

    def test_110_the_controls_on_screen_are_exactly_the_rows_of_the_table(self):
        from src.features import performance_controls as pc
        self.assertEqual(set(pc.CONTROLS), set(self.tab._controls),
                         'a control the table names is missing from the screen, or the '
                         'screen shows one the table does not answer for')
        self.assertEqual([], pc.uncovered(sorted(self.tab._controls)),
                         'the pane carries a control neither table speaks for')
        self.assertEqual([], self.tab.performance_analyzer.uncovered_controls(
            sorted(self.tab._controls)))
        for name, widget in self.tab._controls.items():
            self.assertEqual(name, widget.objectName(),
                             f'{name} is not the widget its row is read back from')
            self.assertIs(widget, getattr(self.tab, name))

    def test_111_the_widget_tree_holds_no_control_outside_the_table(self):
        from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QSpinBox
        from src.features import performance_controls as pc
        kinds = {'spin': QSpinBox, 'combo': QComboBox, 'check': QCheckBox,
                 'text': QLineEdit}
        wanted = {kind: sum(1 for item in pc.CONTROLS.values() if item.kind == kind)
                  for kind in kinds}
        for kind, widget_class in kinds.items():
            # A QSpinBox owns a line edit of Qt's own (`qt_spinbox_lineedit`, measured here
            # as 8 of them); it is the spin box's internals, not a control on the pane.
            found = [child for child in self.tab.findChildren(widget_class)
                     if not child.objectName().startswith('qt_')]
            self.assertEqual(wanted[kind], len(found),
                             f'{kind} controls on screen do not match the {wanted[kind]} '
                             f'the table rows describe')
            for widget in found:
                self.assertIn(widget.objectName(), pc.CONTROLS,
                              f'a {kind} widget carries no row, so nothing says what it does')
        self.assertEqual(len(pc.CONTROLS), sum(wanted.values()),
                         'the table describes kinds the pane does not build')

    def test_112_the_pane_builds_every_widget_in_one_place_off_one_row(self):
        tree = ast.parse(source(PANE))
        builders = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for call in ast.walk(function):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                        and call.func.id in WIDGET_KINDS):
                    builders.setdefault(call.func.id, set()).add(function.name)
        self.assertEqual({name: {'build_widget'} for name in WIDGET_KINDS}, builders,
                         'a widget of some kind is constructed somewhere other than the one '
                         'method that reads a table row')

    def test_113_no_box_carries_a_range_or_an_item_list_the_pane_wrote(self):
        tree = ast.parse(source(PANE))
        found = []
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for call in ast.walk(function):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                    continue
                if call.func.attr not in ('setRange', 'addItems', 'addItem'):
                    continue
                found.append((call.func.attr, function.name,
                              ast.unparse(call.func.value),
                              [ast.unparse(argument) for argument in call.args]))
        ranges = [row for row in found if row[0] == 'setRange']
        self.assertIn(('setRange', 'build_widget', 'widget', ['0', 'TYPABLE_LIMIT']), ranges,
                      'the figure boxes no longer bound only what can be typed')
        for name, function, receiver, arguments in ranges:
            if function == 'build_widget':
                continue
            self.assertEqual(('self.benchmark_progress', ['0', '100']), (receiver, arguments),
                             f'{function} puts a bound on {receiver}: a control range belongs '
                             f'to the table, and a bar range belongs to Qt')
        for kind, function, receiver, arguments in found:
            if kind == 'addItem':
                self.fail(f'{function} adds {receiver} an item one at a time, which the '
                          f'table cannot be read back from')
            if kind != 'addItems':
                continue
            self.assertIn(function, ('build_widget', 'refresh_variable_controls'),
                          f'{function} fills a list the two tables do not hand it')
            for argument in arguments:
                node = ast.parse(argument).body[0].value
                self.assertNotIsInstance(node, (ast.List, ast.Tuple),
                                         f'{function} writes the items into the pane: {argument}')

    def test_114_the_pane_reads_no_machine_of_its_own(self):
        tree = ast.parse(source(PANE))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertNotIn('psutil', imported,
                         'the pane imported the reader it is not allowed to have')
        self.assertNotIn('GPUtil', imported)
        body = code_of(PANE)
        for reader in ('psutil', 'GPUtil', 'nvidia-smi'):
            self.assertNotIn(reader, body,
                             f'the pane still reaches for {reader} itself instead of asking '
                             f'the one reader the backend holds')

    def test_115_every_box_has_the_engines_verdict_written_beside_it(self):
        from src.features import performance_controls as pc
        self.assertEqual(set(pc.CONTROLS), set(self.tab._effects),
                         'a control was built without the line that says what reads it')
        for name, item in pc.CONTROLS.items():
            text = self.tab._effects[name].text()
            self.assertTrue(text, f'{name} carries no verdict, so nothing tells a setting '
                                  f'apart from a decoration')
            if not item.wired:
                self.assertTrue(text.startswith('this box changes nothing in this app'),
                                f'{name} is refused and does not say so: {text}')
                self.assertIn(item.refusal, text, f'{name} does not carry its own refusal')
            elif item.key:
                self.assertTrue(text.startswith(f'default {item.default}'),
                                f'{name} should show the default its row names: {text}')
                self.assertIn('nothing has written this key yet', text)
            else:
                self.assertTrue(text.startswith('not a stored setting'),
                                f'{name} stores nothing and does not say so: {text}')

    def test_116_a_refused_control_stays_on_the_screen(self):
        from src.features import performance_controls as pc
        refused = sorted(name for name, item in pc.CONTROLS.items() if not item.wired)
        self.assertTrue(refused, 'the table refuses nothing, which is not a measured machine')
        printed = {self.tab.contract_table.item(row, 0).text()
                   for row in range(self.tab.contract_table.rowCount())}
        self.assertEqual(set(pc.CONTROLS) | set(pc.VERBS), printed)
        for name in refused:
            widget = self.tab._controls[name]
            self.assertFalse(widget.isHidden(), f'{name} was hidden, which is deleting a '
                                               f'claim by deleting the box')
            self.assertTrue(widget.isEnabled(), f'{name} was disabled out of the interface')
            self.assertIn(name, printed, f'{name} is refused and is not printed either')

    def test_117_the_contract_table_prints_what_the_two_tables_say(self):
        from src.features import performance_controls as pc
        table = self.tab.contract_table
        self.assertEqual(len(pc.CONTROLS) + len(pc.VERBS), table.rowCount(),
                         'the printed verdicts no longer cover every control and button')
        for row in range(table.rowCount()):
            cells = self.cells(table, row)
            name = cells[0]
            if name in pc.CONTROLS:
                item = pc.control(name)
                self.assertEqual('yes' if item.wired else 'no', cells[2])
                self.assertEqual(item.qualified or 'not stored', cells[3])
                self.assertEqual(pc.sentence_for(item), cells[4],
                                 f'{name} is printed with a sentence its row does not carry')
            else:
                self.assertIn(name, pc.VERBS, f'{name} is on the printed table and in no table')
                self.assertEqual('button', cells[2])
                self.assertEqual(pc.VERBS[name].produces, cells[4])

    def test_118_nothing_is_seeded_and_nothing_is_claimed_at_construction(self):
        from src.ui import performance_tab as PT
        self.assertEqual('', self.tab.store_note.text(),
                         'the pane reported a start-up it did not run')
        self.assertEqual('', self.tab.gc_label.text(),
                         'the collector claimed a pass before one had happened')
        self.assertEqual('no memory verb has run yet', self.tab.memory_status.text())
        self.assertEqual('nothing has been exported yet', self.tab.export_status.text())
        for label in (self.tab.gpu_utilization_label, self.tab.gpu_memory_used_label,
                      self.tab.gpu_temperature_label):
            self.assertEqual(PT.GPU_NOT_READ_NOTE, label.text())
        self.assertEqual(PT.GPU_POWER_NOTE, self.tab.gpu_power_label.text())
        for card in self.tab._cards.values():
            self.assertEqual(PT.MEMORY_NOT_READ_NOTE, card.text(),
                             'a card carries a figure no reader answered')
        body = code_of(PANE)
        for figure in SEEDED_FIGURES:
            self.assertNotIn(figure, body, f'the pane still seeds the figure {figure!r}')

    def test_119_the_sample_table_offers_no_field_the_metrics_do_not_carry(self):
        from src.ui import performance_tab as PT
        row = PerformanceMetrics(timestamp=time.time()).to_dict()
        named = {field for _, field, _, _ in PT.SAMPLE_FIELDS}
        self.assertEqual(set(row) - {'timestamp', 'window_seconds', 'gpu_reader',
                                    'not_read'}, named,
                         'the sample columns and the reader fields are two different lists')
        self.assertEqual({title for title, _ in PT.SERIES},
                         {'CPU %', 'Physical memory %', 'Adapter load %'})
        for _, field in PT.SERIES:
            self.assertIn(field, row, f'the graphs draw {field}, which no sample carries')
        self.assertEqual(60, PT.GRAPH_READINGS,
                         'the graphs hold a number of readings that is not a widget width')


class Test120EveryVerbReaches(PaneHarness, unittest.TestCase):
    """Sixteen buttons, sixteen methods, sixteen artefacts - and no seventh of any of them."""

    def setUp(self):
        super().setUp()
        self.history_path = os.path.join(tempfile.mkdtemp(prefix='rf-perf-work-'),
                                         'benchmarks.json')
        engine = self.tab.performance_analyzer.benchmark
        self.addCleanup(setattr, engine, 'history', engine.history)
        engine.history = BenchmarkHistory(path=self.history_path)

    def test_120_every_verb_the_table_names_is_a_button_on_the_screen(self):
        from src.features import performance_controls as pc
        self.assertEqual(set(pc.VERBS), set(self.tab._verbs),
                         'a button the table names is not on the screen, or the screen has '
                         'one the table does not answer for')
        for name, verb in pc.VERBS.items():
            self.assertEqual(verb.label, self.tab._verbs[name].text(),
                             f'{name} is labelled {verb.label!r} in the table and something '
                             f'else on the screen')

    def test_121_every_button_reaches_the_method_the_table_names(self):
        from src.features import performance_controls as pc
        text = source(PANE)
        for name, verb in pc.VERBS.items():
            self.assertIn(f'{name}.clicked.connect(self.{verb.method})', text,
                          f'{name} is connected to nothing, or to a method other than '
                          f'{verb.method}')
            self.assertTrue(callable(getattr(self.tab, verb.method, None)),
                            f'{verb.method} is not a method of the pane the table can call')

    def test_122_a_button_with_no_receiver_is_a_failure_not_a_quiet_run(self):
        """`disconnect()` is how PyQt answers a signal nobody listens to - measured here."""
        from src.features import performance_controls as pc
        failures = []
        for name, button in self.tab._verbs.items():
            try:
                button.clicked.disconnect()
            except TypeError:
                failures.append(name)
        self.assertEqual([], failures,
                         'these buttons are on the screen with nothing listening: '
                         + ', '.join(failures))
        self.assertEqual(set(pc.VERBS), set(self.tab._verbs))

    def test_123_clearing_the_table_names_the_runs_the_disk_still_holds(self):
        for index, value in enumerate((111.0, 222.0)):
            self.tab.performance_analyzer.benchmark.history.record(
                {'kind': 'cpu', 'value': value, 'unit': 'multiplies/s',
                 'at': f'2026-11-06T22:0{index}:00'})
        self.tab.results_table.insertRow(0)
        self.tab.clear_results_btn.click()
        self.assertEqual(0, self.tab.results_table.rowCount())
        text = self.tab.export_status.text()
        self.assertIn('2 run(s)', text, f'the clear did not count what it left behind: {text}')
        self.assertIn(self.history_path, text, 'the sentence does not name the file it means')
        self.assertIn('not the history', text)

    def test_124_the_memory_verb_answers_and_no_line_says_it_is_still_running(self):
        self.tab.memory_status.setText('trimming the working set...')
        self.tab.analyze_memory_btn.click()
        self.assertTrue(self.pump(until=lambda: 'figure(s)' in self.tab.memory_status.text()),
                        f'the readers never reported: {self.tab.memory_status.text()}')
        text = self.tab.memory_status.text()
        self.assertNotIn('trimming', text, 'the in-progress line outlived the run it described')
        self.assertIn('readers answered', text)
        self.assertGreaterEqual(self.tab.memory_rows_table.rowCount(), 6,
                                'the rows the engine words are not on the screen')
        for row in range(self.tab.memory_rows_table.rowCount()):
            cells = self.cells(self.tab.memory_rows_table, row)
            self.assertTrue(cells[1], f'row {cells[0]} carries neither a figure nor a reason')
        self.assertIn('pass(es) this session', self.tab.gc_label.text())

    def test_125_the_work_the_engine_will_run_is_the_stored_work(self):
        self.tab.change_control('buffer_size_spin', 128)
        self.tab.change_control('memory_mapping_cb', False)
        work = self.tab.performance_analyzer.benchmark_work_settings()
        self.assertEqual({'buffer_kb': 128, 'use_memory_map': False}, work,
                         'the two boxes the storage kind reads do not reach the engine')
        text = self.tab.benchmark_work.text()
        self.assertIn('128', text)
        self.assertIn('plain read', text, f'the line says the map is still used: {text}')

    def test_126_the_full_benchmark_hands_the_stored_work_to_the_engine(self):
        captured = self.fake_engine()
        self.tab.change_control('buffer_size_spin', 256)
        self.tab.change_control('memory_mapping_cb', False)
        self.tab.run_full_benchmark()
        self.assertTrue(self.pump(until=lambda: self.tab.benchmark_cpu_btn.isEnabled()))
        kinds = [kind for kind, _ in captured]
        self.assertEqual(['all'], kinds, f'the full run went around the engine: {captured}')
        self.assertEqual({'buffer_kb': 256, 'use_memory_map': False}, captured[0][1],
                         'the four-kind run timed the storage probe with a different chunk '
                         'size than the one the box names')

    def test_127_a_single_benchmark_gets_the_same_stored_work(self):
        captured = self.fake_engine()
        self.tab.change_control('buffer_size_spin', 32)
        self.tab.run_storage_benchmark()
        self.assertTrue(self.pump(until=lambda: self.tab.benchmark_storage_btn.isEnabled()))
        self.assertEqual([('storage', {'buffer_kb': 32, 'use_memory_map': True})], captured,
                         'the Storage button reached the engine without the stored work')
        self.assertEqual(1, self.tab.results_table.rowCount())

    def test_128_the_export_names_a_file_the_engine_read_back(self):
        result = {'kind': 'cpu', 'ran': 'matrix multiplies', 'reason': '',
                  'result': {'multiplies_per_s': 1000.0}, 'against': {}, 'machine': {},
                  'work': {}}
        self.tab.show_benchmark_result(result)
        self.tab.export_results_btn.click()
        text = self.tab.export_status.text()
        self.assertIn('wrote 1 row(s)', text, f'the export counted nothing: {text}')
        path = text.split('wrote 1 row(s) to ')[1].split(' -')[0]
        self.assertTrue(os.path.exists(path), f'the pane named a file that is not there: {path}')
        with open(path, encoding='utf-8') as handle:
            lines = handle.read().splitlines()
        self.assertEqual(2, len(lines), 'the file does not hold the one row it was given')
        self.assertIn('read the file back as 2 lines', text)

    def fake_engine(self):
        """Replace only the timed work, so the pane still reads the real history object."""
        engine = self.tab.performance_analyzer.benchmark
        captured = []
        original_run, original_all = engine.run, engine.run_all

        def run(kind, duration=2.0, record=False, should_stop=None,
                progress_callback=None, **work):
            captured.append((kind, work))
            return {'kind': kind, 'ran': 'fake work', 'reason': '',
                    'result': {'multiplies_per_s': 1000.0}, 'against': {}, 'machine': {},
                    'work': work}

        def run_all(duration=2.0, record=False, should_stop=None,
                    progress_callback=None, **work):
            captured.append(('all', work))
            # Assembled here rather than by calling `run`, so the list holds the calls the
            # pane made and not the calls the fake made to answer one; the two derived
            # fields keep the engine's own expressions, or the fake would grade its own work.
            answers = {kind: {'kind': kind, 'ran': 'fake work', 'reason': '',
                              'result': {'multiplies_per_s': 1000.0},
                              'against': {}, 'machine': {}, 'work': work}
                       for kind in engine.KINDS}
            return {'kinds': answers,
                    'performed': [k for k, a in answers.items() if a['ran'] is not None],
                    'refused': [f'{k}: {a["reason"]}' for k, a in answers.items()
                                if a['ran'] is None],
                    'measured_at': '2026-11-08T00:00:00'}

        engine.run = run
        engine.run_all = run_all
        self.addCleanup(setattr, engine, 'run', original_run)
        self.addCleanup(setattr, engine, 'run_all', original_all)
        return captured


class Test130WhatAStoreValueChanges(PaneHarness, unittest.TestCase):
    """What a control does when it is moved: the store, the verb, and the reason either fails.

    The boxes were built to be typed into, and the engine was made the only thing that
    refuses. These drive the pane's own door and read the store back through a second
    `QSettings` instance - the object the Post-Processing pane holds - because the claim
    that the two Max Threads boxes are one setting has to be measured, not repeated.
    """

    def setUp(self):
        from src.features import performance_analyzer as PA
        from src.features import performance_controls as pc
        self.live_calls = []
        self.os_calls = []
        real_live = PA.PerformanceAnalyzer._apply_live

        def spy(analyzer_self, widget, value):
            self.live_calls.append((widget, value))
            return real_live(analyzer_self, widget, value)

        PA.PerformanceAnalyzer._apply_live = spy
        self.addCleanup(setattr, PA.PerformanceAnalyzer, '_apply_live', real_live)
        for name in ('set_process_priority', 'apply_cpu_affinity', 'apply_stack_size'):
            real = getattr(pc, name)
            self.addCleanup(setattr, pc, name, real)

            def stub(*args, _name=name, **kwargs):
                self.os_calls.append((_name, args, kwargs))
                return {'verb': _name, 'stubbed': 'this test does not change the process'}

            setattr(pc, name, stub)
        super().setUp()

    def keys_in_store(self):
        from src.utils import app_settings
        store = app_settings.settings()
        store.sync()
        return sorted(store.allKeys())

    def test_130_a_box_lets_anything_be_typed_and_the_engine_refuses_it(self):
        from src.features import performance_controls as pc
        from src.ui import performance_tab as PT
        item = pc.control('max_threads_spin')
        self.assertEqual((1, 16), item.bounds, 'the offer the refusal quotes is not the row')
        self.tab.max_threads_spin.setValue(999)
        self.assertEqual(999, self.tab.max_threads_spin.value(),
                         'the box corrected the number before anybody could read the reason')
        self.assertEqual(PT.TYPABLE_LIMIT, self.tab.max_threads_spin.maximum())
        self.tab.change_control('max_threads_spin', 999)
        text = self.tab._effects['max_threads_spin'].text()
        self.assertTrue(text.startswith('not stored - '), text)
        self.assertIn('is outside the 1 to 16 this control offers', text)

    def test_131_a_refused_number_never_reaches_the_store(self):
        from src.utils import app_settings
        self.tab.change_control('max_threads_spin', 999)
        self.assertIsNone(app_settings.read('PostProcessing', 'max_threads', None))
        self.assertEqual([], self.keys_in_store(),
                         'a value the engine refused was written anyway')
        self.tab.change_control('memory_limit_spin', 1)
        self.assertIsNone(app_settings.read('Performance', 'process_memory_budget_mb', None))

    def test_132_a_stored_value_lands_on_the_key_its_reader_names(self):
        from PyQt6.QtCore import QSettings
        from src.utils import app_settings
        self.tab.change_control('max_threads_spin', 6)
        self.assertEqual(6, app_settings.read('PostProcessing', 'max_threads', None, int))
        other = QSettings(self.store_path, QSettings.Format.IniFormat)
        self.assertEqual(6, other.value('PostProcessing/max_threads', 4, int),
                         'the Performance box wrote a key the Post-Processing instance '
                         'cannot see, so the two boxes are not one setting')
        text = self.tab._effects['max_threads_spin'].text()
        self.assertIn('stored 6 under PostProcessing/max_threads', text)
        self.assertIn('stored only', text, 'a control with no live verb claimed one')

    def test_133_a_value_already_stored_out_of_range_is_shown_and_refused(self):
        from src.features import performance_controls as pc
        from src.utils import app_settings
        app_settings.write('PostProcessing', 'max_threads', 99)
        self.tab.paint_controls_from_store()
        item = pc.control('max_threads_spin')
        stored = pc.read_control(item)
        self.assertTrue(stored['stored'])
        self.assertEqual(99, stored['value'], 'the read corrected the number it was given')
        self.assertIn('is outside the 1 to 16', stored['note'])
        text = self.tab._effects['max_threads_spin'].text()
        self.assertIn('stored 99', text)
        self.assertIn('outside the 1 to 16', text)
        self.assertEqual(99, self.tab.max_threads_spin.value(),
                         'the box hid the number that is really in the store')
        self.assertEqual(99, app_settings.read('PostProcessing', 'max_threads', None, int))

    def test_134_a_priority_the_control_offers_is_refused_by_name(self):
        from src.features import performance_controls as pc
        from src.utils import app_settings
        item = pc.control('thread_priority_combo')
        self.assertIn('Real-time', item.bounds,
                      'the box no longer offers what the engine refuses, so the refusal is '
                      'about a value nobody can reach')
        self.tab.change_control('thread_priority_combo', 'Real-time')
        text = self.tab._effects['thread_priority_combo'].text()
        self.assertTrue(text.startswith('not stored - '), text)
        self.assertIn(pc.PRIORITY_REFUSALS['Real-time'], text)
        self.assertIsNone(app_settings.read('Performance', 'process_priority', None))
        self.assertEqual([], self.os_calls, 'a refused priority still reached Windows')

    def test_135_an_unwired_box_writes_nothing_and_prints_its_reason(self):
        from src.features import performance_controls as pc
        self.tab.change_control('cache_size_spin', 1024)
        text = self.tab._effects['cache_size_spin'].text()
        self.assertTrue(text.startswith('not stored - '), text)
        self.assertIn(pc.control('cache_size_spin').refusal, text)
        self.assertEqual([], self.keys_in_store())
        self.assertEqual([], self.live_calls)

    def test_136_building_the_pane_asks_nothing_of_this_process(self):
        self.assertEqual([], self.live_calls,
                         'a pane that was only constructed ran a verb on this process: '
                         f'{self.live_calls}')
        self.assertEqual([], self.os_calls)
        self.assertEqual([], self.keys_in_store(),
                         'constructing the pane wrote a setting nobody chose')

    def test_137_a_first_run_with_nothing_stored_changes_nothing(self):
        answer = self.tab.apply_stored_settings()
        self.assertEqual(stored_controls(), [row['widget'] for row in answer['applied']],
                         'the start-up pass is not the controls the app can honour')
        for row in answer['applied']:
            self.assertEqual('default', row['source'], f'{row["widget"]} invented a stored value')
            self.assertIsNone(row['live'], f'{row["widget"]} ran a verb nobody stored')
        self.assertEqual([], self.live_calls)
        self.assertIn(f'0 of the {len(stored_controls())} controls this pane stores were '
                      f'read out of the store', self.tab.store_note.text())

    def test_138_applied_profile_is_a_record_and_never_re_applied(self):
        from src.features import performance_controls as pc
        from src.utils import app_settings
        app_settings.write('Performance', 'applied_profile', 'Quality')
        answer = self.tab.apply_stored_settings()
        row = [one for one in answer['applied'] if one['widget'] == 'profile_combo'][0]
        self.assertIsNone(row['live'], 'the profile ran again at start-up, over the knobs the '
                                       'user changed after the button')
        self.assertEqual(pc.RESTART_NOTE, row['reason'])
        self.assertIn('Quality', self.tab._effects['profile_combo'].text())
        self.assertIn(pc.RESTART_NOTE, self.tab._effects['profile_combo'].text(),
                      'the refusal never reached the screen beside the box it refuses')
        self.assertIsNone(app_settings.read('PostProcessing', 'max_threads', None),
                          'Quality wrote its thread count back into the store at start-up')

    def test_139_the_store_note_counts_what_was_read_and_what_ran(self):
        from src.utils import app_settings
        app_settings.write('Performance', 'process_memory_budget_mb', 6000)
        app_settings.write('Performance', 'process_priority', 'Normal')
        app_settings.write('Performance', 'applied_profile', 'Balanced')
        self.tab.apply_stored_settings()
        text = self.tab.store_note.text()
        self.assertIn(f'3 of the {len(stored_controls())} controls this pane stores were '
                      f'read out of the store', text)
        self.assertIn('2 of those ran a verb on this process', text)
        listed = text.split('ran a verb on this process: ')[1].split(' - ')[0]
        self.assertEqual({'thread_priority_combo', 'memory_limit_spin'}, set(listed.split(', ')),
                         f'the verbs counted as run are not the ones the store named: {listed}')
        self.assertEqual({'thread_priority_combo', 'memory_limit_spin'},
                         {name for name, _ in self.live_calls},
                         f'the count says two verbs ran and these did: {self.live_calls}')

    def test_140_no_profile_knob_is_a_box_nothing_reads(self):
        from src.features import performance_controls as pc
        names = self.tab.performance_analyzer.profiles.live_knob_names()
        self.assertEqual([name for name in stored_controls()
                          if pc.control(name).key not in pc.RESTART_KEYS], names,
                         'the knobs a profile may name are not the controls an engine honours')
        self.assertNotIn('profile_combo', names,
                         'a profile could name the profile box, and so apply itself')
        for name in names:
            item = pc.control(name)
            self.assertTrue(item.wired and item.key, f'{name} is a knob nothing can honour')
            self.assertIn(name, self.tab._controls, f'{name} is a knob the screen does not have')

    def test_141_apply_profile_writes_the_knobs_and_says_how_many(self):
        from src.utils import app_settings
        self.tab.profile_combo.blockSignals(True)
        self.tab.profile_combo.setCurrentText('Power Saving')
        self.tab.profile_combo.blockSignals(False)
        self.tab.apply_profile_btn.click()
        self.assertEqual(2, app_settings.read('PostProcessing', 'max_threads', None, int))
        self.assertEqual(32, app_settings.read('Performance', 'storage_probe_buffer_kb', None, int))
        self.assertEqual('Aggressive',
                         app_settings.read('Performance', 'gc_mode', None))
        self.assertEqual(sorted(['set_process_priority', 'apply_cpu_affinity']),
                         sorted({call[0] for call in self.os_calls}),
                         'the profile wrote a knob without running the verb it owns')
        text = self.tab._effects['profile_combo'].text()
        self.assertIn('wrote 8 knob(s)', text, text)
        self.assertEqual(2, self.tab.max_threads_spin.value(),
                         'the store was written and the box still shows the old number')
        self.assertIn('plain read', self.tab.benchmark_work.text(),
                      'the mapping knob moved and the work line was never repainted')

    def test_142_saving_over_a_built_in_name_is_refused_and_the_file_untouched(self):
        profiles = self.tab.performance_analyzer.profiles
        self.tab.profile_name_edit.setText('Balanced')
        self.tab.save_profile_btn.click()
        text = self.tab._effects['profile_name_edit'].text()
        self.assertTrue(text.startswith('not saved - '), text)
        self.assertIn('built-in', text)
        self.assertEqual([], [name for name in profiles.names() if name not in
                              profiles.BUILT_IN], 'a built-in profile was overwritten')
        self.assertFalse(os.path.exists(profiles.path))

    def test_143_a_saved_profile_is_the_values_on_screen_and_reads_back(self):
        profiles = self.tab.performance_analyzer.profiles
        self.tab.profile_name_edit.setText('My Working Set')
        self.tab.save_profile_btn.click()
        text = self.tab._effects['profile_name_edit'].text()
        self.assertIn('saved "My Working Set"', text)
        read_back = profiles.read_back('My Working Set')
        self.assertTrue(read_back['found'], text)
        self.assertEqual(sorted(profiles.live_knob_names()),
                         sorted(read_back['entry']['knobs']))
        self.assertNotIn('profile_combo', read_back['entry']['knobs'],
                         'the saved set carries the profile box, so a profile applies itself')
        on_screen = [self.tab.profile_combo.itemText(index)
                     for index in range(self.tab.profile_combo.count())]
        self.assertIn('My Working Set', on_screen,
                      'written to the file, absent from the box that lists it')
        with open(profiles.path, encoding='utf-8') as handle:
            self.assertIn('My Working Set', json.load(handle)['custom'])

    def test_144_the_collection_mode_names_the_interval_that_actually_runs(self):
        from src.features import performance_controls as pc
        garbage = self.tab.performance_analyzer.garbage
        garbage.start()
        self.tab.change_control('garbage_collection_combo', 'Aggressive')
        self.assertEqual(pc.GC_INTERVALS['Aggressive'], garbage.timer.interval())
        self.assertEqual(15000, garbage.timer.interval())
        self.assertIn('15000', self.tab._effects['garbage_collection_combo'].text())
        self.tab.change_control('garbage_collection_combo', 'Manual')
        self.assertFalse(garbage.timer.isActive())
        self.assertEqual('Manual', garbage.mode)
        self.assertIn('only', self.tab._effects['garbage_collection_combo'].text(),
                      'Manual said it was running when nothing runs in that mode')

    def test_145_the_collector_reports_its_timer_without_asking_qt_across_a_thread(self):
        """The pane's memory worker reads `summary()`; asking a QTimer there was a fault.

        Measured on this machine: a worker that called `QTimer.isActive()` on the timer the
        interface thread owns raised `wrapped C/C++ object of type QTimer has been deleted`,
        which is a heap fault rather than an exception anybody could print. The runner keeps
        the state its own last command left the timer in, so neither read asks Qt anything.
        """
        from src.features import performance_controls as pc
        from src.utils.worker import Worker
        import inspect
        for name in ('summary', 'set_mode'):
            body = inspect.getsource(getattr(pc.GarbageCollectionRunner, name))
            self.assertNotIn('isActive', body,
                             f'{name} asks a QTimer what it is doing, from a thread that may '
                             f'not own it')
        garbage = self.tab.performance_analyzer.garbage
        garbage.start()
        garbage.set_mode('Automatic')
        self.assertTrue(garbage.summary()['timer_active'])
        garbage.stop()
        self.assertFalse(garbage.summary()['timer_active'])
        analyzer = self.tab.performance_analyzer
        answers, errors = [], []
        worker = Worker(lambda progress_callback=None: analyzer.memory_rows())
        worker.signals.result.connect(answers.append)
        worker.signals.error.connect(errors.append)
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(worker)
        self.assertTrue(self.pump(until=lambda: answers or errors))
        self.assertEqual([], errors, 'the memory reader died on its worker thread')
        self.assertIn('timer_active', answers[0]['garbage']['passes'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
