"""The packaged app has no console, so a report written to stdout is a report to nobody.

`RenderFox.spec:29` is `console=False`. The process therefore has no stream anybody reads. The
first wave of this work - the commit before this one - took out the 20 `print("DEBUG: ...")`
traces that sat in the model load, the vertex pick and the paint, the two writes `paintGL` held
(one a `traceback.print_exc()` that rebuilt a whole traceback on every frame the drawing failed)
and the parked commented-out copies of them. What the checker measured on that tree, and measures
on this one, is the rest of it: **100 stream writes** over 70 app files, of which 7 sit in a
module's own hand-run `if __name__ == "__main__":`, 5 are named individually as lines that do have
a reader, and **88 had no reader at all** - a failure caught, described, and written into the
stream the package closes.

Those 88 are now records. Measured the same way on this tree: **12 stream writes** left, 0 of them
unreadable, and **240 log records** written by 33 of the 73 files where 151 were written by 16 -
the arithmetic the suite pins, because a report that changed channel rather than vanishing is the
whole claim. The levels are 104 `warning`, 68 `error`, 60 `info`, 6 `debug` and 2 `logger.exception`.
The file count is 73 and not 71 because 7b-1 shipped `src/utils/app_settings.py` and
`src/features/performance_controls.py`, neither of which emits. The count is the channel phase's 239
plus one, and the one is this phase's: the pane lost the `update_system_info` warning that sat in a
method it no longer has (HEAD `src/ui/performance_tab.py:1117`) and gained two failure channels for
work that used to reach only the screen - `on_identity_reader_failed` (`:1134`) and
`on_memory_task_failed` (`:1636`). A record on a branch that runs is the claim; the earlier
correction ran the other way, when that phase lost a warning written by a shadowed
`update_model_info` no caller could reach, and a record that cannot run is not a report.
Rules 5 and 6 found seventeen defects on the tree the sweep landed on, all of them records the
channel was already losing: three calls written on the root logger, whose rows are named `root`,
and fourteen sentences that needed a glyph to be understood.

What is claimed here is that an export which fails says so where a user can read it, on both routes.
The two panes' copy points at the Diagnostics log, so every branch of both viewer export methods
that answers `False` now writes a row first - including the refusal for want of a model, which used
to answer `False` and explain nothing anywhere at all.

The app has exactly one report channel. `src/ui/diagnostics_tab.py` puts a `PaneLogHandler` on
the *root* logger, so a `logger.warning` written anywhere in the tree becomes a row in the
Diagnostics table - including from a worker thread, because the handler only re-emits a Qt
signal and the delivery is queued. That is the half of the story the checker cannot see from one
file: a record has to be written *and* the name it is written through has to exist. A
`logger.warning` in a module without a `logger` raises `NameError` inside the `except` block that
was trying to report a failure, which is worse than the silent line it replaced - it hides the
failure and adds one of its own. So `tools/check_stdout_quiet.py` answers six questions and
this suite asks the checker all six, in both directions:

- rules 1 and 2 (no `DEBUG` write anywhere, nothing at all written from a repaint, comments
  included, because the trace deleted here was parked with the words "useful if needed"): run
  over the real tree, and over the files this suite plants and removes again;
- rule 3 (`logger` resolves where it is used): including the two cases a naive name search gets
  wrong - a binding in a class body, which a method cannot reach by bare name, and a binding in
  a sibling function, which cannot reach this one;
- rule 4 (no app file writes to a stream at all, bar the twelve lines that have a reader), in
  both directions: a plain report planted in a pane is caught, an exemption that matches nothing
  is caught with it, and a write inside a module's own `if __name__ == "__main__":` is not -
  because that block only runs when a developer executes the file in a console that exists. A
  guard written inside a *function* is caught: that is a body the packaged app can reach;
- rule 5a (a record that reaches the channel can be turned into text): a literal message whose
  `%`-slots and arguments disagree raises inside `logging` at emit time, and `Handler.handleError`
  answers by writing to stderr. One of these was planted by this phase itself, in a line that
  ends `(%.1f%% reduction)` twice - which is also why the slot count is pinned on a literal
  percent, an f-string and a correct two-argument call as well as on the broken one;
- rule 5b (the row has a component a reader can filter on) and rule 6 (the sentence does not need
  a glyph the table has no colour for), each with the clean counterpart planted beside it;
- the counts themselves: `records named root: 0` means nothing if the tree emits nothing, so the
  number of log calls, of emitters and of calls per level is measured here rather than remembered,
  and the two summary lines the checker prints are checked against the rows it listed;
- the channel itself: a warning written on this thread and on another one both land in the
  Diagnostics table, and a repaint that raises leaves one row per distinct reason rather than
  one per frame, which at 60 fps would fill the table's 10,000-row cap in 167 seconds and push
  the reason off the end;
- the two ways that table could still be empty while full: its level filter used to be an
  equality against a default of INFO, so the WARNING rows the app writes were stored and shown
  as nothing, and its component list offered nine names no emitter has ever had;
- the records written before the pane exists: `logging.lastResort` hands a record with no handler
  to stderr, which `console=False` discards exactly like a `print`, so five of `main.py`'s reports
  and one written while `src/features/ai_asset_tagger.py` is imported were invisible.
  `src/utils/early_log.py` is the queue that holds them until `setup_logging` plays them back. Its
  premise - that stderr really is where an unhandled record goes - is executed in a child process
  here, both with and without the queue, because inside this suite the root logger has handlers on
  it and cannot show it.

Four things are read off the syntax tree rather than executed. The window-icon branches need a whole
`MainWindow()` and its 22-second start, and `paintGL` needs a GL context this machine cannot give -
so the suite calls the helper the paint was moved into, for real, and runs both of the viewer's
export methods against a directory and a real file. Three more are pinned at the source because
running them would open the window: `main.py`'s two `setLevel` calls, its `early_log.install()`
standing above every report and level change in `main()`, and the level each converted call carries
at the eight sites this phase chose between `warning` and `error` - a failure the app caught and
still answered, against one that left its own records or state wrong. What is proved instead, by
executing it, is that the mechanism those lines rely on is real: a child logger's level lets a
record through to a root handler while root itself stays at WARNING, and a `logger.debug` - which
is what the per-action registration line in `automation_engine` is written at - does not.

Run: python -X utf8 tests/test_stdout_quiet_contract.py
"""

import ast
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import importlib.util
import numpy as np
from PyQt6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CHECKER = os.path.join(ROOT, 'tools', 'check_stdout_quiet.py')
VIEWER_FILE = os.path.join(ROOT, 'src', 'ui', 'model_viewer.py')
PAINTING_FILE = os.path.join(ROOT, 'src', 'ui', 'painting_tab.py')
RENDERING_FILE = os.path.join(ROOT, 'src', 'ui', 'rendering_tab.py')
MAIN_FILE = os.path.join(ROOT, 'main.py')
VIEWER_LOGGER_NAME = 'src.ui.model_viewer'

_spec = importlib.util.spec_from_file_location('stdout_quiet_checker', CHECKER)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

# The probe file, planted inside `src/` so the checker's own file list sees it, and removed by
# addCleanup. Its name is spelled in pieces: the dead-module checker asks whether a word appears
# anywhere in the tree, and this file writing the whole word would be the thing that made its own
# probe look reachable.
PROBE = os.path.join(ROOT, 'src', 'ui', '_probe' + '_stdout_module.py')


def plant(text):
    """Write a throwaway module into `src/` for the length of one test."""
    assert not os.path.exists(PROBE), 'an earlier run left the probe behind'
    with open(PROBE, 'w', encoding='utf-8') as handle:
        handle.write(text)


def strict_run():
    return subprocess.run([sys.executable, '-X', 'utf8', CHECKER, '--strict'],
                          cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                          errors='replace')


def probe_findings():
    return [row for row in checker.scan([Path(PROBE)])]


def probe_rules():
    """``[(rule, line), ...]`` for the planted file - one line can be reported twice.

    Rule 1 and rule 4 read the same call for different reasons: a `DEBUG` trace is a trace *and*
    a write with no reader. Assertions here are therefore about the rule, not about the count.
    """
    return sorted((rule, line) for _f, rule, line, _d in probe_findings())


class TestInstrument(unittest.TestCase):
    """The checker, over the tree it will be run on from now on, and over planted defects."""

    def tearDown(self):
        if os.path.exists(PROBE):
            os.remove(PROBE)

    def test_01_the_tree_the_app_ships_is_clean(self):
        found = checker.scan(checker.app_files())
        self.assertEqual([], found,
                         'the app writes to a stream nobody reads, or names a logger that '
                         'is not there: ' + '; '.join(f'{r}:{c}:{l}' for r, c, l, _ in found))

    def test_02_the_strict_run_exits_zero_and_says_so(self):
        run = strict_run()
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertIn('no DEBUG trace remains', run.stdout,
                      'a passing run has to say what it checked, not only exit')

    def test_03_the_files_it_checked_are_the_files_the_build_carries(self):
        """An instrument pointed at nothing passes everything, so its reach is measured."""
        files = checker.app_files()
        relative = [p.relative_to(Path(ROOT)).as_posix() for p in files]
        self.assertIn('main.py', relative, 'the entry point is not walked')
        self.assertIn('src/ui/model_viewer.py', relative, 'the repaint is not walked')
        self.assertFalse([p for p in files if {'dist', 'build', 'patch_script'} & set(p.parts)],
                         'a packaged copy was read as if it were the source')
        self.assertGreater(len(files), 60, f'only {len(files)} files were walked')

    def test_04_a_debug_trace_planted_in_a_pane_is_reported(self):
        plant('def load(path):\n    print("DEBUG: about to read")\n    return path\n')
        found = probe_findings()
        # Rule 1 names it a trace and rule 4 names it a write with no reader: the same line,
        # reported twice, for two reasons that are both true.
        self.assertEqual([('debug-trace', 2), ('stream-write', 2)], probe_rules(),
                         f'the planted trace was not reported as both defects: {found}')
        run = strict_run()
        self.assertEqual(1, run.returncode, 'the strict run passed over a tree holding a trace')
        out = run.stdout.replace('\\', '/')
        self.assertIn('src/ui/_probe' + '_stdout_module.py', out,
                      'the report did not name the file it found the defect in')

    def test_05_a_trace_built_from_an_f_string_is_a_trace_too(self):
        plant('def load(path):\n    print(f"DEBUG: reading {path} now")\n')
        self.assertIn(('debug-trace', 2), probe_rules(),
                      'an f-string trace was treated as an ordinary message')

    def test_06_an_ordinary_message_is_not_called_a_trace(self):
        """Rule 1 is about debug traces. Rule 4 is what catches every other write."""
        plant('def load(path):\n    print("Loaded 12 models from the library")\n')
        rules = probe_rules()
        self.assertNotIn('debug-trace', [rule for rule, _l in rules],
                         'a plain message was reported as a debug trace')
        self.assertEqual(['stream-write'], [rule for rule, _l in rules],
                         'a report written to the stream the build closes went unreported')

    def test_07_a_debug_record_in_the_log_is_not_a_trace(self):
        plant('import logging\nlog = logging.getLogger("probe")\n\n'
              'def load(path):\n    log.debug("DEBUG: reading %s", path)\n')
        self.assertEqual([], probe_findings(),
                          'a record the Diagnostics pane can filter was reported as a trace')

    def test_08_a_write_from_the_repaint_is_reported(self):
        plant('class V:\n    def paintGL(self):\n        print("painted")\n')
        self.assertEqual([('paint-path', 3), ('stream-write', 3)], probe_rules(),
                         'a per-frame write was not reported as both a paint defect and a write '
                         'with no reader')

    def test_09_a_parked_write_in_the_repaint_is_reported(self):
        """A commented trace in the paint body is one un-comment away from running per frame."""
        plant('class V:\n    def paintGL(self):\n        # print("DEBUG: frame")\n        x = 1\n')
        found = probe_findings()
        self.assertEqual(['paint-path'], [rule for _f, rule, _l, _d in found],
                         'the parked write was invisible, which is how the real one survived')

    def test_09b_a_traceback_dump_from_the_paint_is_the_same_defect(self):
        """`traceback.print_exc()` writes to the same vanished stream, one line at a time."""
        plant('def paintGL(self):\n    import traceback\n    traceback.print_exc()\n')
        found = [row for row in probe_findings() if row[1] == 'paint-path']
        self.assertEqual(1, len(found),
                         'the dump that the real paint carried until today was invisible')

    def test_10_the_same_line_outside_a_repaint_is_not_a_paint_defect(self):
        plant('class V:\n    def load_model(self):\n        # print("DEBUG: frame")\n        x = 1\n')
        self.assertEqual([], [row for row in probe_findings() if row[1] == 'paint-path'])

    def test_11_a_logger_that_was_never_bound_is_reported(self):
        plant('import logging\n\n\nclass V:\n    def load(self, path):\n        '
              'try:\n            raise OSError("no")\n        except OSError as e:\n'
              '            logger.warning("failed: %s", e)\n')
        found = [row for row in probe_findings() if row[1] == 'logger-name']
        self.assertEqual(1, len(found), 'the NameError waiting in that except block went unseen')

    def test_12_a_logger_bound_in_the_module_reaches_the_method(self):
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'class V:\n    def load(self, path):\n        logger.warning("done")\n')
        self.assertEqual([], probe_findings())

    def test_13_a_logger_bound_in_a_class_body_does_not_reach_the_method(self):
        """Python looks a bare name up in the module and the function, never in a class body."""
        plant('import logging\n\n\nclass V:\n    logger = logging.getLogger(__name__)\n\n'
              '    def load(self, path):\n        logger.warning("done")\n')
        found = [row for row in probe_findings() if row[1] == 'logger-name']
        self.assertEqual(1, len(found),
                         'a `logger` moved into a class header reads as bound to the checker '
                         'and raises in the method')

    def test_14_a_logger_bound_in_a_sibling_function_does_not_reach_this_one(self):
        plant('import logging\n\n\ndef a():\n    logger = logging.getLogger("a")\n    '
              'logger.info("x")\n\n\ndef b():\n    logger.warning("y")\n')
        found = [row for row in probe_findings() if row[1] == 'logger-name']
        self.assertEqual(1, len(found), 'two functions were treated as one namespace')

    def test_15_a_logger_built_by_the_function_that_uses_it_is_bound(self):
        plant('import logging\n\n\ndef b():\n    logger = logging.getLogger("b")\n'
              '    logger.warning("y")\n')
        self.assertEqual([], probe_findings())

    def test_16_the_a_line_counted_is_the_line_printed(self):
        """The summary is what a reader trusts; it has to be the same number as the listing."""
        plant('import logging\n\n\nprint("DEBUG: one")\n\n\ndef paintGL(self):\n'
              '    print("two")\n\n\ndef c():\n    logger.warning("three")\n')
        found = probe_findings()
        # Three defects, one per rule, and five findings: rule 4 reads both prints as well,
        # which is the difference between a trace and an ordinary write.
        self.assertEqual(5, len(found), f'three defects across five findings were expected, '
                                        f'got {found}')
        run = strict_run()
        for label, expected in (('debug traces', '1'), ('writes from a repaint', '1'),
                                ('unresolved `logger`', '1'), ('writes with no reader', '2')):
            stated = re.search(re.escape(label) + r': (\d+)', run.stdout)
            self.assertIsNotNone(stated, f'the report never counted {label}: {run.stdout}')
            self.assertEqual(expected, stated.group(1),
                             f'the report said {stated.group(1)} for {label} while listing '
                             f'{len(found)} rows')

    def test_17_a_file_that_does_not_parse_does_not_pass(self):
        plant('def broken(:\n')
        run = strict_run()
        self.assertNotEqual(0, run.returncode,
                            'an unparsable file was walked past and the run said all clear')
        self.assertNotIn('nothing is written to a stream', run.stdout,
                         'the all-clear printed over a tree the checker could not read')

    def test_18_the_real_repaint_is_the_one_being_guarded(self):
        """Rules 1 and 2 pass on the tree, so prove they saw the functions they are about."""
        guarded = [node for node in ast.walk(ast.parse(Path(VIEWER_FILE).read_text(encoding='utf-8')))
                   if isinstance(node, ast.FunctionDef) and node.name in checker.PAINT_FUNCTIONS]
        self.assertEqual({'paintGL', '_report_paint_failure'}, {n.name for n in guarded},
                         'the shipped viewer has no repaint - and no report it hands the failure '
                         'to - under the names the checker guards')
        self.assertEqual([], checker.paint_path_writes(Path(VIEWER_FILE)))
        paint = [n for n in guarded if n.name == 'paintGL'][0]
        span = range(paint.lineno, paint.end_lineno + 1)
        inside = [line for line, _text in checker.stdout_writes(Path(VIEWER_FILE)) if line in span]
        self.assertEqual([], inside, f'line(s) {inside} write from inside the paint')

    def test_19_the_log_calls_it_counts_are_real_ones(self):
        """`0 unresolved` is only worth reading if the tree really does call a module logger."""
        used = 0
        for path in checker.app_files():
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
            used += sum(1 for node in ast.walk(tree)
                        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == 'logger')
        self.assertGreaterEqual(used, 3, f'the rule was measured against {used} calls')

    # ---- rule 4 from the other side: which writes do have a reader -------------------------------

    def test_31_a_write_inside_a_hand_run_block_is_not_reported(self):
        """`if __name__ == "__main__":` runs for a developer with a console, and for nobody else."""
        plant('import sys\n\n\nif __name__ == "__main__":\n    print("smoke: the module imports")\n')
        self.assertEqual([], probe_findings(), 'a smoke test written for a console that exists was reported')

    def test_32_a_guard_written_inside_a_function_is_not_a_hand_run_block(self):
        """The exemption stops at the module body: a function is reachable from the packaged app."""
        plant('def run():\n    if __name__ == "__main__":\n        print("smoke")\n')
        self.assertEqual([('stream-write', 3)], probe_rules(),
                          'the guard reached into a function body, where the build can run it')

    def test_33_an_exemption_that_matches_no_write_is_itself_reported(self):
        """A guard whose exception no longer applies is the widest blind spot it can have."""
        dead = ('main.py', 'ZZZ no line of the entry point reads like this', 'probe')
        original = checker.VISIBLE_WRITES
        checker.VISIBLE_WRITES = original + (dead,)
        self.addCleanup(setattr, checker, 'VISIBLE_WRITES', original)
        found = [row for row in checker.scan([Path(MAIN_FILE)]) if row[1] == 'stale-exemption']
        self.assertEqual(1, len(found), f'the dead exemption was not reported: {found}')
        self.assertIn('ZZZ no line', found[0][3], 'the report did not name the exemption it rejected')

    def test_34_the_writes_the_report_splits_add_up_to_the_writes_it_walked(self):
        total, guard, named, unreadable = checker.total_stream_writes(checker.app_files())
        self.assertEqual(0, unreadable, 'an app file writes to a stream nobody reads again')
        self.assertEqual(total, guard + named + unreadable,
                         f'{total} writes walked, {guard + named + unreadable} accounted for')
        self.assertEqual((12, 7, 5, 0), (total, guard, named, unreadable),
                         'the figures this file documents. Re-measure them before editing this '
                         'line, and correct the two docstrings with it.')

    # ---- rule 5a: a record that reaches the channel can still be turned into text ----------------

    def test_35_a_message_and_its_arguments_that_disagree_are_reported(self):
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def save(rows):\n    logger.info("wrote %d files")\n')
        found = [row for row in probe_findings() if row[1] == 'unformattable']
        self.assertEqual(1, len(found), f'the record that raises inside logging passed: {found}')
        self.assertIn('1-slot message handed 0 argument(s)', found[0][3])
        self.assertEqual(1, strict_run().returncode,
                         'the strict run passed over a tree whose report cannot be formatted')

    def test_36_the_same_message_with_its_argument_is_clean(self):
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def save(rows):\n    logger.info("wrote %d files", len(rows))\n')
        self.assertEqual([], probe_findings(), 'a correct call was reported')

    def test_37_a_literal_percent_is_not_counted_as_a_slot(self):
        """`%.1f%% reduction` has one slot, not two - the mistake this rule made about my own line."""
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def lod(i, v):\n    logger.info("Generated LOD%d: %.1f%% reduction", i, v)\n')
        self.assertEqual([], probe_findings(),
                          'a two-slot call handed two arguments was reported, which is how the '
                          'real LOD row was nearly rewritten to match a broken instrument')

    def test_37b_the_slot_a_literal_percent_hides_is_still_counted(self):
        """The same message with one argument missing has to be the same finding as any other."""
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def lod(i, v):\n    logger.info("Generated LOD%d: %.1f%% reduction", i)\n')
        found = [row for row in probe_findings() if row[1] == 'unformattable']
        self.assertEqual(1, len(found), 'dropping one of the two arguments went unseen')
        self.assertIn('2-slot message handed 1 argument(s)', found[0][3])

    def test_38_a_message_the_caller_builds_has_no_slots_to_miss(self):
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def save(rows):\n    logger.info(f"wrote {len(rows)} files")\n')
        self.assertEqual([], probe_findings(),
                          'an already-interpolated message was measured for `%` slots')

    # ---- rule 5b and rule 6: the row a record becomes has a name and needs no glyph --------------

    def test_39_a_record_written_on_the_root_logger_is_reported(self):
        plant('import logging\n\n\ndef save(p):\n    logging.warning("could not write %s", p)\n')
        found = [row for row in probe_findings() if row[1] == 'root-logger']
        self.assertEqual(1, len(found), f'the row that would arrive named `root` passed: {found}')
        self.assertEqual(5, found[0][2])

    def test_40_the_same_call_through_a_module_logger_keeps_its_name(self):
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def save(p):\n    logger.warning("could not write %s", p)\n')
        self.assertEqual([], probe_findings())

    def test_41_a_glyph_written_into_a_record_is_reported(self):
        """Written as an escape so that this file stays plain ASCII while the probe does not."""
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def load(m):\n    logger.info("model loaded \\u2713")\n')
        found = [row for row in probe_findings() if row[1] == 'glyph-in-record']
        self.assertEqual(1, len(found), f'the status glyph that leaked into a row passed: {found}')
        self.assertIn('\u2713', found[0][3], 'the report did not name the character it objected to')

    def test_42_the_word_that_means_the_same_thing_passes(self):
        plant('import logging\nlogger = logging.getLogger(__name__)\n\n\n'
              'def load(m):\n    logger.info("model loaded successfully")\n')
        self.assertEqual([], probe_findings())

    def test_43_the_counts_are_measured_against_emitters_the_tree_has(self):
        """`records named root: 0` means nothing if the tree writes no records at all."""
        levels = {}
        on_root = 0
        through_a_module_logger = 0
        emitters = set()
        for path in checker.app_files():
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
            for node in ast.walk(tree):
                call = checker._logger_call(node)
                if call is None:
                    continue
                levels[call[0]] = levels.get(call[0], 0) + 1
                emitters.add(path)
                if call[1]:
                    on_root += 1
                else:
                    through_a_module_logger += 1
        self.assertEqual(0, on_root, 'a record is written on the root logger after all')
        self.assertEqual(240, sum(levels.values()),
                         f'the tree writes {sum(levels.values())} records, not the 240 this file '
                         'documents: re-measure, then correct the docstring')
        self.assertGreaterEqual(through_a_module_logger, 230, 'rules 5 and 6 have almost nothing to read')
        self.assertGreaterEqual(len(emitters), 30, f'only {len(emitters)} files emit at all')
        for level in ('debug', 'info', 'warning', 'error', 'exception'):
            self.assertIn(level, levels, f'the convention names {level} and the tree writes none')
        run = strict_run()
        for label in ('records that cannot be formatted', 'records named `root`',
                      'sentences that need a glyph'):
            stated = re.search(re.escape(label) + r': (\d+)', run.stdout)
            self.assertIsNotNone(stated, f'the report never counted {label}: {run.stdout}')
            self.assertEqual('0', stated.group(1), f'{label} is not zero over the shipped tree')


class TestTheChannel(unittest.TestCase):
    """A report that survives the paint, in the one place a user can open."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from src.ui.diagnostics_tab import DiagnosticsTab
        self.records = []
        self.pane = DiagnosticsTab()
        self.log = logging.getLogger(VIEWER_LOGGER_NAME)
        self.capture = io.StringIO()

    def tearDown(self):
        self.pane.deleteLater()
        self.app.processEvents()

    def capturing(self):
        return redirect_stdout(self.capture)

    def test_20_a_repaint_that_raises_writes_nothing_to_a_stream(self):
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        with self.capturing():
            viewer._report_paint_failure(RuntimeError('framebuffer incomplete'))
        self.assertEqual('', self.capture.getvalue(),
                         'the paint failure went to the stream the build discards')

    def test_21_a_failing_repaint_is_reported_once_per_reason_not_once_per_frame(self):
        """`paintGL` runs at the frame rate, so an unthrottled report is not a report."""
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        before = len(self.pane.log_entries)
        with self.capturing():
            for _ in range(100):
                viewer._report_paint_failure(RuntimeError('framebuffer incomplete'))
        added = self.pane.log_entries[before:]
        self.assertEqual(1, len(added), f'100 identical failures produced {len(added)} rows')
        self.assertEqual('WARNING', added[0]['level'])
        self.assertIn('framebuffer incomplete', added[0]['message'])
        with self.capturing():
            viewer._report_paint_failure(ValueError('shader program not linked'))
        self.assertEqual(2, len(self.pane.log_entries) - before,
                         'a second, different reason was swallowed by the latch')
        self.assertIn('shader program not linked', self.pane.log_entries[-1]['message'])
        self.assertEqual('', self.capture.getvalue())

    def test_22_the_warning_lands_in_the_diagnostics_table(self):
        with self.capturing():
            self.log.warning('Model export to %s failed: %s', 'C:/tmp/thing.obj', 'locked')
        self.app.processEvents()
        rows = [r for r in self.pane.log_entries if r['level'] == 'WARNING']
        self.assertTrue(rows, 'a logger.warning reached no row in the table it exists for')
        self.assertEqual(VIEWER_LOGGER_NAME, rows[-1]['component'])
        self.assertIn('thing.obj', rows[-1]['message'])
        self.assertIn('locked', rows[-1]['message'])
        self.assertEqual('', self.capture.getvalue())

    def test_23_a_record_written_on_another_thread_arrives_through_the_loop(self):
        """The handler only re-emits a signal, so the worker thread never touches the table."""
        def work():
            logging.getLogger('src.features.some_engine').warning('finished on a worker')

        thread = threading.Thread(target=work)
        with self.capturing():
            thread.start()
            thread.join()
        self.app.processEvents()
        rows = [r for r in self.pane.log_entries if 'finished on a worker' in r['message']]
        self.assertEqual(1, len(rows), 'the cross-thread record never became a row')
        self.assertEqual('src.features.some_engine', rows[0]['component'])
        self.assertEqual('', self.capture.getvalue())

    def test_24_a_failed_export_names_the_file_and_still_answers(self):
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        viewer.meshes = [{'vertices': np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='f4'),
                          'faces': np.array([[0, 1, 2]], dtype='i4')}]
        work = tempfile.mkdtemp(prefix='renderfox_34_')
        with self.capturing():
            answered = viewer.export_model(work)  # a folder is not a file the export can open
        self.assertFalse(answered, 'a failed export said it succeeded')
        rows = [r for r in self.pane.log_entries if r['level'] == 'WARNING']
        self.assertTrue(any(work.replace('\\', '/') in r['message'] or work in r['message']
                            for r in rows),
                        f'the failure was logged without the file it failed on: {rows[-3:]}')
        self.assertEqual('', self.capture.getvalue())

    def test_25_a_successful_export_writes_a_file_that_reloads(self):
        """The quiet failure path must not have been bought by making every export answer False."""
        import trimesh
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        viewer.meshes = [{'vertices': np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='f4'),
                          'faces': np.array([[0, 1, 2]], dtype='i4')}]
        work = tempfile.mkdtemp(prefix='renderfox_34_')
        target = os.path.join(work, 'written.obj')
        with self.capturing():
            answered = viewer.export_model(target)
        self.assertTrue(answered, 'a good export answered False')
        self.assertTrue(os.path.isfile(target) and os.path.getsize(target) > 0,
                        'it said True and wrote nothing')
        reloaded = trimesh.load(target, force='mesh')
        self.assertEqual(3, len(reloaded.vertices))
        self.assertEqual(1, len(reloaded.faces))
        self.assertEqual('', self.capture.getvalue())

    def test_26_the_export_failure_copy_points_at_the_log(self):
        """The panes told the user to check a console the packaged build does not have.

        The strings are read out of the parse tree rather than out of the file: both panes now
        carry a comment naming `console=False` as the reason their reports go to the log, and a
        comment is not a sentence a user reads.
        """
        for path in (PAINTING_FILE, RENDERING_FILE):
            source = Path(path).read_text(encoding='utf-8')
            tree = ast.parse(source)
            docstrings = {ast.get_docstring(tree),
                          *(ast.get_docstring(n) for n in ast.walk(tree)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))}
            text = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value not in docstrings]
            self.assertEqual([], [s for s in text if 'console' in s.lower()],
                             f'{os.path.basename(path)} still shows the user a line that sends '
                             'them to a stream they cannot open')
            self.assertIn('Diagnostics', source,
                          f'{os.path.basename(path)} does not name the pane that has the reason')

    def test_28_a_failed_scene_export_names_the_file_and_still_answers(self):
        """Rendering -> Export Scene is a second route out of the same viewer."""
        import trimesh
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        viewer.original_meshes = [trimesh.Trimesh(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])]
        work = tempfile.mkdtemp(prefix='renderfox_34_')
        with self.capturing():
            answered = viewer.export_scene(work, {'base_color': [1.0, 1.0, 1.0]})
        self.assertFalse(answered, 'a failed scene export said it succeeded')
        rows = [r for r in self.pane.log_entries if r['level'] == 'WARNING']
        self.assertTrue(any(work in r['message'] for r in rows),
                        f'the scene export failed without naming the file: {rows[-3:]}')
        self.assertEqual('', self.capture.getvalue())

    def test_29_an_export_refused_for_want_of_a_model_says_that_is_why(self):
        """Every route that answers False has to have written the reason, or the pane's copy lies."""
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        target = os.path.join(tempfile.mkdtemp(prefix='renderfox_34_'), 'nothing.obj')
        with self.capturing():
            first = viewer.export_model(target)
            second = viewer.export_scene(target, {})
        self.assertFalse(first, 'export_model said it wrote a file it never had a mesh for')
        self.assertFalse(second, 'export_scene said it wrote a file it never had a mesh for')
        rows = [r for r in self.pane.log_entries if r['level'] == 'WARNING']
        self.assertEqual(2, len(rows), f'two refusals produced {len(rows)} rows')
        for row in rows:
            self.assertIn(target, row['message'], f'a refusal names no file: {row}')
            self.assertIn('nothing is loaded', row['message'],
                          f'a refusal does not say what stopped it: {row}')
        self.assertEqual('', self.capture.getvalue())

    def test_30_a_successful_scene_export_writes_a_file_that_reloads(self):
        """The quiet failure path must not have been bought by making every export answer False."""
        import trimesh
        from src.ui.model_viewer import ModelViewer3D
        viewer = ModelViewer3D()
        viewer.original_meshes = [trimesh.Trimesh(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])]
        target = os.path.join(tempfile.mkdtemp(prefix='renderfox_34_'), 'written.obj')
        with self.capturing():
            answered = viewer.export_scene(target, {'base_color': [1.0, 1.0, 1.0]})
        self.assertTrue(answered, 'a good scene export answered False')
        self.assertTrue(os.path.isfile(target) and os.path.getsize(target) > 0,
                        'it said True and wrote nothing')
        self.assertEqual(3, len(trimesh.load(target, force='mesh').vertices))
        self.assertEqual('', self.capture.getvalue())

    def test_27_a_missing_window_icon_is_logged_without_a_write(self):
        """Both icon branches report through the log; neither can be run without the window."""
        for relative in ('main.py', os.path.join('src', 'ui', 'main_window.py')):
            path = os.path.join(ROOT, relative)
            source = Path(path).read_text(encoding='utf-8')
            tree = ast.parse(source)
            holders = []
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and any(
                        isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == 'setWindowIcon' for call in ast.walk(node)):
                    holders.append(node)
            self.assertTrue(holders, f'{relative} sets no window icon through a branch')
            writes = {line for line, _text in checker.stdout_writes(Path(path))}
            for branch in holders:
                self.assertEqual(
                    [], [line for line in writes if branch.lineno <= line <= branch.end_lineno],
                    f'{relative}:{branch.lineno} writes the icon verdict to a stream')
                reported = [n for n in ast.walk(branch.orelse[0] if branch.orelse else branch)
                            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr in ('warning', 'error')]
                self.assertTrue(reported, f'{relative}:{branch.lineno} has no branch that reports '
                                          f'a missing icon at all')


class TestTheTable(unittest.TestCase):
    """The two ways the Diagnostics table could be full and still show nothing."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from src.ui.diagnostics_tab import DiagnosticsTab
        self.pane = DiagnosticsTab()

    def tearDown(self):
        self.pane.deleteLater()
        self.app.processEvents()

    def shown(self):
        """The text actually on screen, after the filters have been applied."""
        self.pane.filter_logs()
        return self.pane.log_display.toPlainText()

    def combo_names(self):
        combo = self.pane.component_filter_combo
        return [combo.itemText(i) for i in range(combo.count())]

    def rows(self, message):
        return [r for r in self.pane.log_entries if message in r['message']]

    def test_45_a_warning_is_visible_under_the_default_level(self):
        """The filter used to be an equality against a default of INFO.

        Every row this app writes is WARNING or ERROR, so the table stored all of them and showed
        none - the emptiest it ever looked was the fullest it had been.
        """
        self.assertEqual('INFO', self.pane.log_level_combo.currentText())
        logging.getLogger(VIEWER_LOGGER_NAME).warning('shader program not linked')
        self.app.processEvents()
        self.assertEqual(1, len(self.rows('shader program not linked')),
                         'the record wrote no row at all')
        self.assertIn('shader program not linked', self.shown(),
                      'a row the app wrote was hidden by the level filter')
        self.pane.log_level_combo.setCurrentText('ERROR')
        self.assertNotIn('shader program not linked', self.shown(),
                         'the floor lets a WARNING through under ERROR, so it filters nothing')

    def test_46_an_info_row_shows_under_its_own_floor_and_not_under_a_higher_one(self):
        """The floor has to order the levels, not merely stop hiding everything above zero.

        The record is written with `src` open to INFO because that is what `main.py` does; at the
        library default the logger drops an INFO record before any handler sees it, which is a
        different claim and test_57 measures it on its own.
        """
        source = logging.getLogger('src')
        saved = source.level
        source.setLevel(logging.INFO)
        try:
            logging.getLogger(VIEWER_LOGGER_NAME).info('24 LODs written for chair_01')
            self.app.processEvents()
            self.assertIn('24 LODs written', self.shown(), 'an INFO row is hidden behind the INFO floor')
            self.pane.log_level_combo.setCurrentText('ALL')
            self.assertIn('24 LODs written', self.shown(), 'ALL hides a row')
            self.pane.log_level_combo.setCurrentText('WARNING')
            self.assertNotIn('24 LODs written', self.shown(), 'WARNING lets an INFO row through')
        finally:
            source.setLevel(saved)

    def test_47_the_component_list_offers_only_emitters_that_wrote(self):
        """A choice that matches no record is not a filter, it is an empty table.

        The nine names this combo shipped - "Renderer", "GPU", "UI", the rest - were such choices,
        because a record's component is its module path and no module is called "Renderer".
        """
        self.assertEqual(['All Components'], self.combo_names())
        logging.getLogger(VIEWER_LOGGER_NAME).warning('the paint failed')
        self.app.processEvents()
        self.assertEqual(['All Components', VIEWER_LOGGER_NAME], self.combo_names(),
                         f'the emitter of the only row in the table is not on the list: {self.combo_names()}')
        self.assertNotIn('Renderer', self.combo_names(), 'a name no module has ever emitted is back')
        self.assertEqual('All Components', self.pane.component_filter_combo.currentText(),
                         'a record arriving hijacked the filter the user is reading through')

    def test_48_a_component_choice_leaves_only_that_modules_rows(self):
        logging.getLogger(VIEWER_LOGGER_NAME).warning('the paint failed')
        logging.getLogger('src.processing.lod_generator').warning('LOD2 is the raw simplification')
        self.app.processEvents()
        self.pane.component_filter_combo.setCurrentText('src.processing.lod_generator')
        shown = self.shown()
        self.assertIn('LOD2 is the raw simplification', shown, 'the chosen component is not shown')
        self.assertNotIn('the paint failed', shown, 'the component filter filters nothing')


class TestEarlyRecords(unittest.TestCase):
    """The reports written before the pane that reads them exists."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from src.utils import early_log
        self.early_log = early_log
        self.root = logging.getLogger()
        self.panes = []
        early_log.take()  # a leftover from another test is not this test's row

    def tearDown(self):
        for pane in self.panes:
            pane.deleteLater()
        self.app.processEvents()
        for handler in [h for h in self.root.handlers
                        if isinstance(h, self.early_log.EarlyLogHandler)]:
            self.root.removeHandler(handler)
        self.assertEqual([], [h for h in self.root.handlers
                              if isinstance(h, self.early_log.EarlyLogHandler)],
                         'the queue was left on the root logger for every test after this one')
        self.early_log.take()

    def pane(self):
        from src.ui.diagnostics_tab import DiagnosticsTab
        built = DiagnosticsTab()
        self.panes.append(built)
        self.app.processEvents()
        return built

    def child(self, body):
        """Run a snippet in a process that has no handlers on the root logger, like the app before
        `MainWindow` builds its pane."""
        script = f'import logging, sys\nsys.path.insert(0, {ROOT!r})\n{body}\n'
        return subprocess.run([sys.executable, '-X', 'utf8', '-c', script], cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8', errors='replace')

    def test_49_a_second_install_adds_no_second_queue(self):
        self.assertTrue(self.early_log.install())
        self.assertFalse(self.early_log.install(),
                         'a second main() in the same process stacked a queue in front of the first')
        self.assertEqual(1, len([h for h in self.root.handlers
                                 if isinstance(h, self.early_log.EarlyLogHandler)]))

    def test_50_the_held_records_come_back_oldest_first_and_only_once(self):
        self.early_log.install()
        log = logging.getLogger(VIEWER_LOGGER_NAME)
        log.warning('icon not found')
        log.warning('splash not found')
        self.assertEqual(['icon not found', 'splash not found'],
                         [r.getMessage() for r in self.early_log.take()],
                         'the startup order was not kept, so the first reason is not first')
        self.assertEqual([], self.early_log.take(), 'the buffer was peeked at rather than drained')

    def test_51_the_buffer_stops_at_its_cap_and_keeps_the_earliest(self):
        self.early_log.install()
        log = logging.getLogger(VIEWER_LOGGER_NAME)
        for i in range(self.early_log.EARLY_LIMIT + 50):
            log.warning('startup line %d', i)
        held = self.early_log.take()
        self.assertEqual(self.early_log.EARLY_LIMIT, len(held),
                         'a startup that fails in a loop grew the buffer without limit')
        self.assertEqual('startup line 0', held[0].getMessage(),
                         'the first reason was dropped for the last, which is the opposite of '
                         'what a crash report is for')

    def test_52_a_pane_shows_what_was_held_before_it_existed(self):
        self.early_log.install()
        logging.getLogger(VIEWER_LOGGER_NAME).warning('icon not found at C:/app/icons/logo.png')
        rows = [r for r in self.pane().log_entries if 'icon not found' in r['message']]
        self.assertEqual(1, len(rows), 'the startup report was still lost, only from stderr')
        self.assertEqual(('WARNING', VIEWER_LOGGER_NAME), (rows[0]['level'], rows[0]['component']))
        self.assertEqual([], self.early_log.take(),
                         'the playback left the record queued, so the next pane would show it too')

    def test_53_a_pane_built_without_the_queue_starts_empty(self):
        """Only `main()` installs the buffer, so no suite can inherit another suite's startup."""
        self.assertEqual([], [h for h in self.root.handlers
                              if isinstance(h, self.early_log.EarlyLogHandler)])
        self.assertEqual([], self.pane().log_entries,
                         'a pane arrived holding history nobody wrote into its own queue')

    def test_54_a_record_with_no_handler_reaches_the_stream_the_build_discards(self):
        """The premise of `early_log`, run where nothing is installed to hold the record."""
        run = self.child('logging.getLogger("src.ui.model_viewer").warning("reaches lastResort")')
        self.assertIn('reaches lastResort', run.stderr,
                      'a log call with no handler no longer goes to stderr, which means the '
                      'reports this phase replaced were invisible for some other reason entirely')

    def test_55_the_queue_keeps_a_startup_record_out_of_that_stream(self):
        run = self.child('from src.utils import early_log\n'
                         'early_log.install()\n'
                         'logging.getLogger("src.ui.model_viewer").warning("held for the pane")')
        self.assertEqual('', run.stderr.strip(),
                         f'the record still went to the discarded stream: {run.stderr!r}')
        self.assertEqual('', run.stdout.strip())


class TestTheLevel(unittest.TestCase):
    """Which level a report is written at, and what that level does to the row."""

    # file, the sentence, the level it carries and the reason for that level
    LEVELS = [
        (os.path.join('src', 'ui', 'model_viewer.py'), 'Vertex shader compile failed: %s', 'warning',
         'the fallback viewer answers, so the app caught the failure and still replied'),
        (os.path.join('src', 'ui', 'model_viewer.py'), 'Viewer clear failed: %s', 'error',
         'the meshes are gone and `cleared` was never emitted, so the panes still show them'),
        (os.path.join('src', 'ui', 'model_viewer.py'), 'Failed to switch to fallback viewer: %s',
         'error', 'the GL viewer is deleted before the fallback is built: a raise leaves none'),
        (os.path.join('src', 'utils', 'worker.py'), '%s failed: %s', 'error',
         'the task ended in its except arm, whatever a connected pane then reports'),
        (os.path.join('src', 'processing', 'texture_baker.py'), 'Baking failed: %s', 'error',
         'the batch has no map where its record says one exists'),
        (os.path.join('src', 'processing', 'lod_generator.py'),
         'Quadric decimation failed, using convex hull', 'warning',
         'a named fallback produced the LOD the user asked for, at another shape'),
        (os.path.join('src', 'features', 'automation_engine.py'), 'Registered action: %s', 'debug',
         'per-item chatter, below the floor on purpose so a 90-action start writes no rows'),
        (MAIN_FILE, 'Could not write the crash record: %s', 'error',
         'the app is dying and its own record of why did not get written'),
    ]

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.root = logging.getLogger()
        self.saved = {name: logging.getLogger(name).level for name in ('', 'src', '__main__')}

    def tearDown(self):
        for name, level in self.saved.items():
            logging.getLogger(name).setLevel(level)

    def test_56_a_report_is_written_at_the_level_its_sentence_claims(self):
        """The convention is the sweep, and a sweep nobody can re-check is a claim.

        `warning` for a failure the app caught and still answered; `error` for one that left its
        own records or state wrong; `info` for progress; `debug` for per-item chatter.
        """
        for relative, sentence, level, reason in self.LEVELS:
            path = Path(relative) if os.path.isabs(relative) else Path(ROOT) / relative
            tree = ast.parse(path.read_text(encoding='utf-8'))
            calls = [node for node in ast.walk(tree) if checker._logger_call(node)
                     and any(sentence in text for text in checker._message_literals(node))]
            self.assertEqual(1, len(calls),
                             f'{relative} has {len(calls)} records reading {sentence!r}; the pin '
                             f'names one, so a second copy would go unlevelled')
            found = checker._logger_call(calls[0])
            self.assertEqual(level, found[0],
                             f'{relative}:{calls[0].lineno} writes {sentence!r} at {found[0]}, '
                             f'not {level} - {reason}')

    def test_57_the_apps_own_floor_lets_info_through_and_keeps_debug_below_it(self):
        """`main.py` opens two namespaces and leaves root at WARNING; the mechanism is run here."""
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger('src').setLevel(logging.INFO)
        from src.ui.diagnostics_tab import DiagnosticsTab
        pane = DiagnosticsTab()
        try:
            log = logging.getLogger(VIEWER_LOGGER_NAME)
            log.debug('per-item chatter')
            log.info('24 LODs written for chair_01')
            log.warning('the paint failed')
            logging.getLogger('trimesh.grouping').info('a dependency chattering')
            self.app.processEvents()
            levels = {r['message']: r['level'] for r in pane.log_entries}
            self.assertEqual('INFO', levels.get('24 LODs written for chair_01'),
                             f'the floor does not let the app own INFO records through: {levels}')
            self.assertEqual('WARNING', levels.get('the paint failed'))
            self.assertNotIn('per-item chatter', levels,
                             'a DEBUG record reaches the table, so the six per-item sites are rows')
            self.assertNotIn('a dependency chattering', levels,
                             'root is open to INFO, so every library in the process can fill a '
                             'table capped at 10,000 rows')
            self.assertEqual(logging.WARNING, self.root.level,
                             'root itself was moved off WARNING by a test that set it back')
        finally:
            pane.deleteLater()
            self.app.processEvents()

    def test_58_main_opens_its_own_two_namespaces_and_nobody_elses(self):
        """Read off the tree: building the window to check two lines costs 22 seconds."""
        tree = ast.parse(Path(MAIN_FILE).read_text(encoding='utf-8'))
        named = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'setLevel'):
                continue
            getter = node.func.value
            self.assertTrue(isinstance(getter, ast.Call)
                            and getattr(getter.func, 'attr', '') == 'getLogger',
                            f'main.py:{node.lineno} sets a level on a logger this cannot name')
            name = getter.args[0].value if getter.args else '<root>'
            level = getattr(node.args[0], 'attr', None) if node.args else None
            named.append((name, level))
        self.assertEqual([('src', 'INFO'), ('__main__', 'INFO')], named,
                         'the entry point opens a level this file does not describe. A `setLevel` '
                         'on <root> would let every dependency write rows into the pane.')

    def test_59_the_queue_is_installed_before_main_reports_or_levels_anything(self):
        """`install()` has to be the first thing the entry point does, or it holds nothing."""
        tree = ast.parse(Path(MAIN_FILE).read_text(encoding='utf-8'))
        mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
        self.assertEqual(1, len(mains), 'main.py no longer has one top-level main()')
        body = [s for s in mains[0].body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        first = body[0]
        self.assertTrue(isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                        and isinstance(first.value.func, ast.Attribute)
                        and first.value.func.attr == 'install'
                        and getattr(first.value.func.value, 'id', '') == 'early_log',
                        f'main() now opens with a {type(first).__name__}, so the seven reports '
                        'below it are back in the stream the build discards')
        for node in ast.walk(mains[0]):
            if not isinstance(node, ast.Call):
                continue
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else ''
            called = node.func.id if isinstance(node.func, ast.Name) else ''
            if attr in checker.LEVEL_CALLS or attr == 'setLevel' or called in checker.PRINT_NAMES:
                self.assertGreater(node.lineno, first.lineno,
                                   f'main.py:{node.lineno} reports or sets a level before '
                                   f'early_log.install() at :{first.lineno} could hold it')


if __name__ == '__main__':
    unittest.main(verbosity=2)
