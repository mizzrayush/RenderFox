"""The packaged app has no console, so a report written to stdout is a report to nobody.

`RenderFox.spec:29` is `console=False`. The process therefore has no stream anybody reads.
Measured on the tree as this phase opened: 122 `print()` calls in `src/` and `main.py`, and 20 of
them were `print("DEBUG: ...")` traces sitting in the model load, the vertex pick and the paint -
the three paths the app runs most. `paintGL` held two more, one of them a `traceback.print_exc()`
that rebuilt a whole traceback on every frame the drawing failed. None of it could ever be seen,
and in the repaint it cost something on every frame for nothing. Out of the tree: **23 `print`
calls** (the 20 traces plus the line in `paintGL` and the *same* `Export failed:` line written twice
- once in `export_model`, which the Painting pane calls, and once in `export_scene`, which the
Rendering pane calls), **both** `traceback.print_exc()` calls in `model_viewer.py`, **7** parked
commented-out traces, and the `total_verts` sum whose only reader was a trace. The app scope is now
99 `print` calls, 69 of them inside `except` handlers; one `traceback.print_exc()` survives, at
`src/utils/worker.py:56`, and it is the one line the `error` signal is emitted beneath a frame
later. That class is #52's, and nothing in this file claims it is fixed; what is claimed here is
narrower and checkable.

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
failure and adds one of its own. So `tools/check_stdout_quiet.py` answers three questions and
this suite asks the checker all three, in both directions:

- rules 1 and 2 (no `DEBUG` write anywhere, nothing at all written from a repaint, comments
  included, because the trace deleted here was parked with the words "useful if needed"): run
  over the real tree, and over six files this suite plants and removes again;
- rule 3 (`logger` resolves where it is used): including the two cases a naive name search gets
  wrong - a binding in a class body, which a method cannot reach by bare name, and a binding in
  a sibling function, which cannot reach this one;
- the channel itself: a warning written on this thread and on another one both land in the
  Diagnostics table, and a repaint that raises leaves one row per distinct reason rather than
  one per frame, which at 60 fps would fill the table's 10,000-row cap in under three minutes
  and push the reason off the end.

Two things are read off the syntax tree rather than executed. The window-icon branches need a whole
`MainWindow()` and its 22-second start, and `paintGL` needs a GL context this machine cannot give -
so the suite calls the helper the paint was moved into, for real, and runs both of the viewer's
export methods against a directory and a real file.

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
from contextlib import redirect_stdout
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
        self.assertEqual(1, len(found), f'the planted trace was missed: {found}')
        self.assertEqual('debug-trace', found[0][1])
        run = strict_run()
        self.assertEqual(1, run.returncode, 'the strict run passed over a tree holding a trace')
        out = run.stdout.replace('\\', '/')
        self.assertIn('src/ui/_probe' + '_stdout_module.py', out,
                      'the report did not name the file it found the defect in')

    def test_05_a_trace_built_from_an_f_string_is_a_trace_too(self):
        plant('def load(path):\n    print(f"DEBUG: reading {path} now")\n')
        self.assertEqual(['debug-trace'], [rule for _f, rule, _l, _d in probe_findings()],
                         'an f-string trace was treated as an ordinary message')

    def test_06_an_ordinary_message_is_not_called_a_trace(self):
        """The rule is about debug traces, not about every sentence the app might print."""
        plant('def load(path):\n    print("Loaded 12 models from the library")\n')
        self.assertEqual([], probe_findings(),
                          'a plain message was reported as a debug trace')

    def test_07_a_debug_record_in_the_log_is_not_a_trace(self):
        plant('import logging\nlog = logging.getLogger("probe")\n\n'
              'def load(path):\n    log.debug("DEBUG: reading %s", path)\n')
        self.assertEqual([], probe_findings(),
                          'a record the Diagnostics pane can filter was reported as a trace')

    def test_08_a_write_from_the_repaint_is_reported(self):
        plant('class V:\n    def paintGL(self):\n        print("painted")\n')
        found = probe_findings()
        self.assertEqual(['paint-path'], [rule for _f, rule, _l, _d in found],
                         'a per-frame write was reported as nothing, or as the wrong rule')

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
        self.assertEqual(3, len(found), f'three different defects were expected, got {found}')
        run = strict_run()
        for label, expected in (('debug traces', '1'), ('writes from a repaint', '1'),
                                ('unresolved `logger`', '1')):
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
        """The panes told the user to check a console the packaged build does not have."""
        for path in (PAINTING_FILE, RENDERING_FILE):
            source = Path(path).read_text(encoding='utf-8')
            self.assertNotIn('console', source.lower(),
                             f'{os.path.basename(path)} still sends the user to a stream they '
                             'cannot open')
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
