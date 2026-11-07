"""The exit path, asked where a wrong answer costs a process rather than a test.

`#50` is the reason this file exists. A PyQt6 process dies two ways, and only one of them
reports itself: a raise nobody caught prints a traceback and a failing test name, while a fault at
the edge of a C++ frame is answered with `0xc0000409` - `STATUS_FAIL_FAST_EXCEPTION`, a fast fail
with no output, because `unittest` prints its summary at the end and there is no end. A suite that
printed `Ran 6 tests in 20.1s / OK` arrived at the audit as
`Core Backend & Regression Suite [FAIL]`, because `run_audit.py:297` reads
`proc.returncode == 0`. That was measured 3 times in 6 subprocess runs of one tree and 1 in 6 of
another.

This phase found, and this file keeps finding, that **the shape does not abort on this tree
today**: twenty-two child processes over six shapes - among them the frame that raises
`SystemExit` with the loop's result, a module global, a module global with an `atexit` survivor
report, and `tests/verify_all_fixes.py` both on the committed file and on the one this phase
changed - returned 0 twenty-two times, as `run_teardown.shutdown`'s own docstring records. So
nothing here claims a crash was reproduced. What is claimed is narrower and
checkable: the exit is a *shape*, five files in app scope carried it - `main.py` and the four
panes with a hand-run `__main__` block, measured as ten findings on the tree as #50 left it - and
a release must not depend on which side of a race the interpreter's last few
milliseconds win. The instruments below are what stop the shape coming back by somebody typing
`sys.exit(app.exec())` again, and the child processes are what keep the drain honest about what
it actually does.

Three kinds of question, in three classes:

* `TestInstrument` runs `tools/check_clean_exit.py` over the shipped tree and over planted
  modules, the way `tests/test_stdout_quiet_contract.py` does - including the count in its own
  summary line, because an instrument pointed at nothing passes everything.
* `TestDrain` calls `run_teardown.shutdown` on plain `QWidget`s and asks the three facts the
  function promises: a window on screen goes away, a window that refuses the close is *named*,
  and a window already through its `closeEvent` is not asked twice. No `MainWindow`, no
  `closeEvent` that raises, nothing that can end this process before it prints.
* `TestQuitPath` spends two seconds of child process on what cannot be tested in-process at all:
  the loop ending with a code that survives to the exit, and the crash reporter returning instead
  of waiting on a modal `QMessageBox` that no one is there to dismiss - the failure this phase
  found by hanging on it. A guard removed there is caught by the test's own timeout, so the suite
  reports a name rather than joining the hang.

Run: python -X utf8 tests/test_clean_exit_contract.py
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from src.utils import run_teardown

CHECKER = os.path.join(ROOT, 'tools', 'check_clean_exit.py')
MAIN_FILE = os.path.join(ROOT, 'main.py')
SUITE_FILE = os.path.join(ROOT, 'tests', 'verify_all_fixes.py')
TEARDOWN_FILE = os.path.join(ROOT, 'src', 'utils', 'run_teardown.py')

_spec = importlib.util.spec_from_file_location('clean_exit_checker', CHECKER)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

# Planted inside `src/` so the checker's own walk reaches it, and named in two pieces because the
# dead-module checker asks whether a word appears anywhere in the tree.
PROBE = os.path.join(ROOT, 'src', 'ui', '_probe' + '_exit_module.py')

LOOP_OWNERS = 5  # main.py and the four panes with a hand-run `__main__` block, measured


def plant(text):
    assert not os.path.exists(PROBE), 'an earlier run left the probe behind'
    with open(PROBE, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return Path(PROBE)


def checker_run(*args):
    return subprocess.run([sys.executable, '-X', 'utf8', CHECKER, *args], cwd=ROOT,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def probe_rules():
    return sorted((rule, line) for _f, rule, line, _d in checker.scan([Path(PROBE)]))


def child(source, timeout=90):
    """Run a snippet in a fresh process and hand back its code, its output and how long it took.

    The marker is written with `os.write(1, ...)`: a fast fail after the last flush still leaves
    the line that named what was built, which is the difference between a measurement and a
    silence somebody has to explain.
    """
    handle, path = tempfile.mkstemp(suffix='.py', prefix='rf_exit_child_')
    with os.fdopen(handle, 'w', encoding='utf-8') as stream:
        stream.write(source)
    start = time.time()
    try:
        proc = subprocess.run([sys.executable, '-X', 'utf8', path], cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr, time.time() - start
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', '', time.time() - start
    finally:
        os.remove(path)


class TestInstrument(unittest.TestCase):
    """The checker, on the tree it will be run on and on defects planted one at a time."""

    def tearDown(self):
        if os.path.exists(PROBE):
            os.remove(PROBE)

    def test_01_the_tree_the_app_ships_is_clean(self):
        found = checker.scan(checker.app_files())
        self.assertEqual([], found,
                         'an event loop is used as the exit, or ends with no drain after it: '
                         + '; '.join(f'{f}:{r}:{l}' for f, r, l, _ in found))

    def test_02_the_strict_run_exits_zero_and_says_so(self):
        run = checker_run('--strict')
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertIn('every Qt event loop', run.stdout,
                      'a passing run has to say what it checked, not only exit')

    def test_03_the_files_it_counts_are_the_files_that_own_a_loop(self):
        """An instrument whose reach is zero passes everything, so its reach is measured.

        Five files in app scope construct a `QApplication`. The report has to say five, and say
        that all five of their loops reach a drain - the line that goes red when a sixth file
        starts an event loop and the rules silently stop covering it.
        """
        run = checker_run()
        self.assertIn(f'files owning a QApplication: {LOOP_OWNERS}', run.stdout, run.stdout)
        self.assertIn(f'application event loops: {LOOP_OWNERS} = {LOOP_OWNERS} drained + 0 not',
                      run.stdout, run.stdout)
        self.assertGreater(len(checker.app_files()), 60, 'the walk does not reach the app')
        self.assertIn('main.py', [p.name for p in checker.app_files()],
                      'the entry point is not walked, and it is the one process users start')

    def test_04_a_loop_used_as_the_exit_is_reported(self):
        plant('from PyQt6.QtWidgets import QApplication\nimport sys\n'
              'app = QApplication(sys.argv)\nwindow = object()\n'
              'def drive():\n    sys.exit(app.exec())\n')
        rules = [rule for rule, _line in probe_rules()]
        self.assertIn('loop-as-exit', rules, 'the shipped shape was not reported')
        self.assertIn('loop-undrained', rules,
                      'the same line is both the exit and no drain, and both are true')
        self.assertEqual(1, checker_run('--strict').returncode,
                         'the strict run passed over a tree holding the shipped shape')
        # The summary counts the probe as well, and counts it on the right side of the drain
        # column: an instrument that books every loop as drained reports a clean app either way.
        counted = checker_run()
        self.assertIn(f'application event loops: {LOOP_OWNERS + 1} = {LOOP_OWNERS} drained + 1 not',
                      counted.stdout, counted.stdout)

    def test_05_the_same_loop_taken_down_is_clean(self):
        plant('from PyQt6.QtWidgets import QApplication\nimport sys\n'
              'from src.utils.run_teardown import shutdown\n'
              'app = QApplication(sys.argv)\n'
              'def drive():\n    code = app.exec()\n    shutdown(app)\n    return code\n'
              'sys.exit(drive())\n')
        found = [row for row in checker.scan([Path(PROBE)]) if row[0].endswith('_exit_module.py')]
        self.assertEqual([], found, f'the fixed shape was reported: {found}')

    def test_06_raise_system_exit_carrying_the_loop_is_the_same_defect(self):
        plant('from PyQt6.QtWidgets import QApplication\n'
              'app = QApplication([])\n'
              'def drive():\n    raise SystemExit(app.exec())\n')
        self.assertIn('loop-as-exit', [rule for rule, _ in probe_rules()],
                      'the raise is the exit by another spelling and was passed')

    def test_07_the_instance_or_construct_shape_still_owns_the_loop(self):
        """`QApplication.instance() or QApplication([])` binds the name by boolean, not by call.

        A rule that matched only a direct construction would find no owner here, conclude the
        file starts no application loop, and pass the shipped shape - which is how this file is
        written in every suite, so the miss would have covered the app.
        """
        plant('from PyQt6.QtWidgets import QApplication\nimport sys\n'
              'app = QApplication.instance() or QApplication(sys.argv)\n'
              'def drive():\n    sys.exit(app.exec())\n')
        self.assertIn('loop-as-exit', [rule for rule, _ in probe_rules()],
                      'the loop on a boolean-bound name was treated as somebody else\'s')

    def test_08_a_dialogs_loop_is_not_the_apps_loop(self):
        """`dialog.exec()` runs a modal loop and returns; the process survives it either way.

        Forty-some call sites in the panes do this. A rule that read them as application loops
        would report the tree as broken and be switched off, which is the fate of an instrument
        that cries wolf.
        """
        plant('from PyQt6.QtWidgets import QApplication, QDialog\n'
              'app = QApplication([])\n'
              'def ask():\n    dialog = QDialog()\n    return dialog.exec()\n')
        found = [row for row in checker.scan([Path(PROBE)]) if row[0].endswith('_exit_module.py')]
        self.assertEqual([], found, f'a modal dialog was read as an application loop: {found}')

    def test_09_a_loop_that_reaches_nobody_is_reported(self):
        plant('from PyQt6.QtWidgets import QApplication\nimport sys\n'
              'app = QApplication([])\n'
              'def drive():\n    code = app.exec()\n    return code\n')
        self.assertIn('loop-undrained', [rule for rule, _ in probe_rules()],
                      'a loop that ends with the windows still queued was passed')

    def test_10_an_atexit_hook_in_app_scope_is_reported(self):
        plant('import atexit\nfrom PyQt6.QtWidgets import QApplication\n'
              'app = QApplication([])\n'
              'atexit.register(lambda: app.topLevelWidgets())\n')
        self.assertIn('atexit-hook', [rule for rule, _ in probe_rules()],
                      'a callback scheduled for after the app is gone was passed; the first '
                      'probe of this phase measured its survivor report at 3 of 3 aborts on '
                      'another tree')

    def test_11_a_drain_that_stopped_running_the_queue_is_reported(self):
        """The call site cannot see this: `shutdown(app)` reads the same from either side."""
        original = Path(TEARDOWN_FILE).read_text(encoding='utf-8')
        body = original.replace('    app.processEvents()\n', '    pass  # app.processEvents()\n',
                                1)
        self.assertNotEqual(original, body,
                            'the drain file no longer holds the line this test plants')
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False,
                                         encoding='utf-8') as handle:
            handle.write(body)
            parked = Path(handle.name)
        try:
            found = checker.drain_steps_missing(parked)
            self.assertIn('run the delete queue while the app is alive',
                          ' '.join(detail for _line, detail in found),
                          'a drain that never runs the queue was accepted')
        finally:
            os.remove(parked)

    def test_12_a_drain_that_closes_every_window_twice_is_reported(self):
        """The visibility test is what keeps a closed window out of its own `closeEvent` again.

        On the normal quit the window has already answered the questions a `closeEvent` asks -
        including the one that refuses an exit over a running render - and asking again from
        inside a quit that is already under way is a raise at the edge of a C++ frame.
        """
        original = Path(TEARDOWN_FILE).read_text(encoding='utf-8')
        body = original.replace('        if widget.isVisible():\n            widget.close()\n',
                                '        widget.close()\n', 1)
        self.assertNotEqual(original, body,
                            'the drain no longer holds the guarded close this test takes out')
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False,
                                         encoding='utf-8') as handle:
            handle.write(body)
            parked = Path(handle.name)
        try:
            found = ' '.join(detail for _line, detail in checker.drain_steps_missing(parked))
            self.assertIn('closes only what is on screen', found,
                          'a drain that re-closes a window that already answered the question was '
                          'accepted: the word `isVisible` still appears in the second loop, so '
                          'only a structural read sees that the guard around the close is gone')
        finally:
            os.remove(parked)

    def test_13_a_suite_that_drains_in_a_test_rather_than_in_teardown_is_reported(self):
        """A test that fails halfway never reaches its own cleanup, and the window stays.

        The guarantee #50 needs is the one that runs whatever happened in between, which is
        `tearDownClass`; the same call in the last test method is a promise a red run breaks.
        """
        in_test = ('import unittest\nfrom PyQt6.QtWidgets import QApplication\n'
                   'from src.utils import run_teardown\n'
                   'class T(unittest.TestCase):\n'
                   '    @classmethod\n    def setUpClass(cls):\n'
                   '        cls.app = QApplication([])\n'
                   '    def test_last(self):\n'
                   '        from src.ui.main_window import MainWindow\n'
                   '        MainWindow()\n        run_teardown.shutdown(cls)\n')
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False,
                                         encoding='utf-8') as handle:
            handle.write(in_test)
            parked = Path(handle.name)
        try:
            self.assertTrue(checker.suite_drains_in_teardown(parked),
                            'a drain written in a test method was accepted as a teardown drain')
        finally:
            os.remove(parked)

    def test_14_the_entry_point_hands_the_loops_code_to_the_exit(self):
        """`run_audit.py` reads exit codes; a quit that loses one reports failure as success."""
        source = Path(MAIN_FILE).read_text(encoding='utf-8')
        self.assertTrue(source.rstrip().endswith('sys.exit(main())'),
                        'main.py no longer leaves with what main() returned for the loop')
        found = checker.entry_keeps_the_loop_code(Path(MAIN_FILE))
        self.assertEqual([], found, f'the entry point throws the exit code away: {found}')

    def test_15_the_real_drain_and_the_real_suite_are_the_ones_pinned(self):
        """The two files the rules read by name, checked by path, so a move cannot hide them."""
        self.assertTrue(os.path.exists(TEARDOWN_FILE), 'the drain moved out from under rule 3')
        self.assertEqual([], checker.drain_steps_missing(),
                          'the shipped drain is missing a step this phase says it performs')
        self.assertEqual([], checker.suite_drains_in_teardown(),
                          'verify_all_fixes.py no longer drains in teardown')

    def test_16_a_drain_that_stops_naming_what_stayed_is_reported(self):
        """The return value is a step too, and it is the only one with a reader outside the file.

        `main.py` writes what came back into a warning, and `verify_all_fixes.py` fails the run on
        it; a `shutdown` that still closes and still deletes but says nothing leaves a quit that
        cannot tell a closed window from one that refused. Rule 3 counts the three verbs and the
        guarded close, so this is the fourth thing it has to see - and the only one a name-in-a-
        list check would miss, because `owed` is still in the function either way.
        """
        original = Path(TEARDOWN_FILE).read_text(encoding='utf-8')
        body = original.replace('    return owed\n', '    return\n', 1)
        self.assertNotEqual(original, body,
                            'the drain no longer holds the return this test takes the value out of')
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False,
                                         encoding='utf-8') as handle:
            handle.write(body)
            parked = Path(handle.name)
        try:
            found = ' '.join(detail for _line, detail in checker.drain_steps_missing(parked))
            self.assertIn('returns nothing', found,
                          f'a drain that answers None was accepted: {found}')
        finally:
            os.remove(parked)

    def test_17_the_exit_code_rule_is_applied_where_a_code_is_read(self):
        """Rule 2b is keyed to one file, so the keying is what is tested here, not the rule.

        `run_audit.py:297` reads the exit code of the process it starts - `main.py`, and nothing
        else - so the rule that keeps that code alive runs on that file only. A file that is not
        the entry point is not asked, and the entry point is asked whatever its name in the tree
        happens to be; both halves have to hold, or the rule is either blind or noisy.
        """
        plant('import sys\n'
              'def main():\n    return\n'
              "if __name__ == '__main__':\n    main()\n")
        probe = Path(PROBE)
        named = [rule for _f, rule, _l, _d in checker.scan([probe], entry=probe)]
        self.assertIn('exit-code-lost', named,
                      'the rule was never applied to the file handed to it as the entry point')
        passed = [rule for _f, rule, _l, _d in checker.scan([probe])]
        self.assertNotIn('exit-code-lost', passed,
                         'a module nobody reads an exit code for was reported anyway')
        scoped = checker_run('--file', 'main.py')
        self.assertEqual(0, scoped.returncode, scoped.stdout + scoped.stderr)
        # `--file` resolves against the repository root, so the one name a real scoped run can
        # give rule 2b is the one it is keyed to; a path that never matched would make the third
        # assert above a tautology.
        self.assertIn('files owning a QApplication: 1', scoped.stdout, scoped.stdout)
        self.assertIn('application event loops: 1 = 1 drained + 0 not', scoped.stdout, scoped.stdout)


class Counting(QWidget):
    """A window that says how many times its close was asked for."""

    asks = 0

    def __init__(self):
        super().__init__()
        self.closed_for_good = False

    def closeEvent(self, event):
        Counting.asks += 1
        super().closeEvent(event)


class Refusing(QWidget):
    """A window that answers the close the way a pane with a running render does."""

    refuse = True

    def closeEvent(self, event):
        if Refusing.refuse:
            event.ignore()
        else:
            super().closeEvent(event)


class TestDrain(unittest.TestCase):
    """`run_teardown.shutdown` called as the plain function it is, over plain `QWidget`s."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        Counting.asks = 0
        Refusing.refuse = True
        self.made = []

    def tearDown(self):
        Refusing.refuse = False
        for widget in self.made:
            widget.close()
            widget.deleteLater()
        self.app.processEvents()

    def make(self, kind, show=True):
        widget = kind()
        self.made.append(widget)
        if show:
            widget.show()
        self.app.processEvents()
        return widget

    def test_20_a_window_on_screen_is_taken_down(self):
        widget = self.make(Counting)
        self.assertTrue(widget.isVisible(), 'the planted window never came on screen')
        owed = run_teardown.shutdown(self.app)
        self.app.processEvents()
        self.assertEqual([], owed, f'the drain named a window it could not close: {owed}')
        self.assertFalse(widget.isVisible(), 'a window the drain closed is still on screen')
        self.assertEqual(1, Counting.asks,
                         'the close was asked a number of times other than once')
        print('✓ A window on screen goes through one close and leaves the screen.')

    def test_21_a_window_that_refuses_the_close_is_named(self):
        """`event.ignore()` is a decision a pane makes on purpose, and the drain must not hide it.

        This is the branch that keeps the return value worth having: a quit that says nothing
        about a window still on screen is the same silence as no drain at all, only later.
        """
        widget = self.make(Refusing)
        owed = run_teardown.shutdown(self.app)
        self.assertIn('Refusing', owed,
                      f'a window that refused the close was not named: {owed}')
        self.assertTrue(widget.isVisible(), 'a refused close was undone anyway')
        Refusing.refuse = False
        widget.close()
        self.assertFalse(widget.isVisible(), 'the window only answers a close once')

    def test_22_a_window_already_closed_is_not_asked_twice(self):
        """On the normal quit the window has been through its own `closeEvent` already.

        The second pass is not harmless: `MainWindow.closeEvent` asks about a running render and
        drains every holder of a run, so running it again from inside a quit that is already
        under way is work done twice and a raise waiting at the edge of a C++ frame.
        """
        widget = self.make(Counting, show=True)
        widget.close()
        self.app.processEvents()
        asked_before = Counting.asks
        self.assertEqual(1, asked_before, 'the direct close did not reach the window')
        owed = run_teardown.shutdown(self.app)
        self.assertEqual([], owed)
        self.assertEqual(asked_before, Counting.asks,
                         'the drain re-closed a window that had already answered the question')

    def test_23_the_drain_returns_names_and_not_a_count(self):
        """`main.py` writes what came back into a log line, so the value has to name the window."""
        widget = self.make(Refusing)
        owed = run_teardown.shutdown(self.app)
        self.assertIsInstance(owed, list, 'the log line joins a list of class names')
        self.assertTrue(all(isinstance(one, str) for one in owed),
                        f'a non-name came out of the drain: {owed}')
        Refusing.refuse = False


class TestQuitPath(unittest.TestCase):
    """What only a process that is leaving can answer."""

    def test_30_the_shipped_shape_is_kept_under_measurement(self):
        """`sys.exit(app.exec())` with a window owned by the frame returns 0 here, today.

        Recorded rather than assumed, in both directions: this is the shape #50 blames, this
        exact child answered 0 eight times out of eight when this phase ran it eight times on the
        committed tree, and if a future Qt, Python or PyQt turns it back into a fast fail this
        test says so with a name instead of the audit chain losing a suite's report. The audit
        runs it once per chain, which is what keeps the sentence above current.
        """
        code, output, seconds = child(
            'import os, sys\n'
            'os.environ["QT_QPA_PLATFORM"] = "offscreen"\n'
            f'sys.path.insert(0, r"{ROOT}")\n'
            'from PyQt6.QtWidgets import QApplication, QWidget\n'
            'from PyQt6.QtCore import QTimer\n'
            'def drive():\n'
            '    app = QApplication(sys.argv)\n'
            '    window = QWidget()\n    window.show()\n'
            '    QTimer.singleShot(120, app.quit)\n'
            '    os.write(1, b"BUILT\\n")\n'
            '    sys.exit(app.exec())\n'
            'drive()\n')
        self.assertIn('BUILT', output, f'the child never reached its loop: {output}')
        self.assertEqual(0, code,
                         f'the undeleted-widget shape left with {code:#x} after {seconds:.1f}s - '
                         'the abort #50 recorded is reproducing again, and this time a test '
                         'names it')

    def test_31_the_quitted_loop_returns_through_the_drain_with_its_code(self):
        """The product's own ending, in a child: loop, drain, exit - and what each one says.

        Three facts in one process: a loop that ends on a failure code still leaves with it after
        the drain has run, the window that answered its own `closeEvent` is gone from the screen,
        and the one that refused is named on the way out. All of that is `main.py`'s last four
        statements, and none of it is visible from the call site.
        """
        code, output, _seconds = child(
            'import os, sys\n'
            'os.environ["QT_QPA_PLATFORM"] = "offscreen"\n'
            f'sys.path.insert(0, r"{ROOT}")\n'
            'from PyQt6.QtWidgets import QApplication, QWidget\n'
            'from PyQt6.QtCore import QTimer\n'
            'from src.utils import run_teardown\n'
            'class Refusing(QWidget):\n'
            '    def closeEvent(self, event): event.ignore()\n'
            'app = QApplication(sys.argv)\n'
            'plain = QWidget()\n'
            'stuck = Refusing()\n'
            'plain.show()\n'
            'stuck.show()\n'
            'def stop():\n'
            '    plain.close()\n    app.exit(3)\n'
            'QTimer.singleShot(120, stop)\n'
            'code = app.exec()\n'
            'os.write(1, ("LOOP_CODE %r PLAIN_VISIBLE %s REFUSING_VISIBLE %s\\n"'
            '              % (code, plain.isVisible(), stuck.isVisible())).encode())\n'
            'owed = run_teardown.shutdown(app)\n'
            'os.write(1, ("OWED %s\\n" % (owed,)).encode())\n'
            'sys.exit(code)\n')
        self.assertIn('LOOP_CODE 3', output,
                      f'the loop did not end on the code it was handed: {output}')
        self.assertIn('PLAIN_VISIBLE False', output,
                      f'a window closed before the quit is on screen again: {output}')
        self.assertIn('REFUSING_VISIBLE True', output,
                      f'the drain ran while the loop was still open: {output}')
        self.assertIn("OWED ['Refusing']", output,
                      f'the window that refused the close was not named by the drain: {output}')
        self.assertEqual(3, code,
                         'a quit that ended on a failure code did not leave on it, which is what '
                         '`run_audit.py:297` reads')

    def test_32_the_crash_reporter_does_not_wait_on_a_button_nobody_can_press(self):
        """A modal dialog in an offscreen process is not a report; it is a hang.

        Found the hard way, by a probe of this phase that raised inside `main.main()` and sat
        there: `global_exception_handler` writes the crash to the log, then calls `msg.exec()`
        whenever a `QApplication` exists. A user can dismiss that. Every suite the audit chain
        runs, and `installer.nsi`'s headless mode, cannot - so the failure this handler exists to
        announce arrives as a timeout with no exit code and no line, which is the class of
        silence phase 6w spent itself removing. The guard is Qt's own platform name, not a guess
        from the environment, and the number below is measured rather than assumed. The child
        timeout is 25 s: a guard taken out costs this suite one named failure and 25 s, instead
        of costing the audit chain the budget it grants the whole run.
        """
        code, output, seconds = child(
            'import importlib, os, sys, time\n'
            'os.environ["QT_QPA_PLATFORM"] = "offscreen"\n'
            f'sys.path.insert(0, r"{ROOT}")\n'
            'from PyQt6.QtWidgets import QApplication\n'
            'app = QApplication(sys.argv)\n'
            'import main as app_main\n'
            'import src.features.diagnostic_engine as engine\n'
            'recorded = []\n'
            'engine.ErrorLogger = lambda: type("W", (), {"log_error": '
            'lambda _s, *a: recorded.append(a)})()\n'
            'app_main.get_telemetry = lambda: type("T", (), {"track_error": '
            'lambda _s, *a: recorded.append(a)})()\n'
            'try:\n'
            '    raise RuntimeError("planted for the exit contract")\n'
            'except RuntimeError:\n'
            '    info = sys.exc_info()\n'
            'start = time.time()\n'
            'app_main.global_exception_handler(*info)\n'
            'os.write(1, ("HANDLER_SECONDS %.3f RECORDS %d\\n"'
            '             % (time.time() - start, len(recorded))).encode())\n',
            timeout=25)
        self.assertNotEqual('TIMEOUT', code,
                            'the crash reporter is waiting on a modal dialog again: a raise in a '
                            'headless run costs the audit chain its timeout instead of naming '
                            'the failure')
        self.assertEqual(0, code, f'the child that only reported a crash left with {code}:\n{output}')
        line = next((one for one in output.splitlines() if one.startswith('HANDLER_SECONDS')), '')
        self.assertTrue(line, f'the handler never returned to print its own timing:\n{output}')
        elapsed = float(line.split()[1])
        records = int(line.split()[3])
        self.assertLess(elapsed, 1.0,
                        f'the reporter took {elapsed:.1f}s to come back; anything that long is a '
                        f'loop waiting for someone')
        self.assertEqual(2, records,
                         'the crash reached neither the error log nor telemetry, which is the '
                         'half of the handler that has no dialog to hide behind')
        whole = Path(MAIN_FILE).read_text(encoding='utf-8')
        start = whole.index('def global_exception_handler(')
        handler = whole[start:whole.index('\ndef ', start + 1)]
        self.assertIn('QMessageBox', handler,
                      'the crash reporter lost its dialog, which is the half a user needs')
        # Anchored on the statements, not on the words: this function's own comment quotes both
        # of them, and a first-index search lands in prose.
        guard = handler.index("if app and app.platformName() != 'offscreen':")
        shown = handler.index('\n        msg.exec()')
        recorded_at = handler.index('\n        ErrorLogger().log_error(')
        self.assertLess(recorded_at, guard,
                        'the crash record moved after the dialog, so a run that hangs writes '
                        'nothing on its way to hanging')
        self.assertLess(guard, shown, 'the dialog is no longer behind the guard')
        print(f'✓ The crash reporter returns in {elapsed:.3f}s with its record written, and the '
              'dialog stays behind the platform check.')


if __name__ == '__main__':
    unittest.main()
