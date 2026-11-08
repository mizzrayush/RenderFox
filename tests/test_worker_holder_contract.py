"""What a pane owes a run it started, asked in a file that starts neither.

Two entries in two mutation lists defect the same line - the `self._workers.append(worker)`
inside `PerformanceTab._keep_worker` (`src/ui/performance_tab.py:304`) - and both were read by
`tests/test_run_teardown_contract.py::test_02`, which is where this question was answered when
the answer was written. That answer is a race now, and the reason is this pane: since 7b-2 its
constructor starts three runs of its own (`refresh_machine_info` `:1101`, `detect_gpu_hardware`
`:1154`, `refresh_storage_info` `:1192`), so a process that has been handed a `PerformanceTab`
already has pool work in flight whose only intended owner is the list the entry deletes.
Measured with the defect planted, that file named `test_02` in eight runs in a row - and then,
with one more test added to the file and nothing else changed, died at `0xc0000005` in three of
five runs inside `tearDownClass`, the faulting frame the pane's own release lambda. Same
product, same defect, different timing, which is the definition of an answer that cannot be
depended on; and the copy of this entry aimed at the Performance suite has never been anything
but a dead process.

So both halves of the promise are asked here, where no pane is built. The first is behavioural
and needs nothing but the pane's own two verbs called as the plain functions they are, on a
holder that carries the one attribute they read, and a `Worker` that is handed the helper and
never the pool: a run the helper is given is held, and the run's own `finished` is what lets it
go. The second half is asked of the syntax tree, because the only way to ask it by execution is
to start a run nobody holds: every call site that hands a runner to the pool files it in the
list its close drains first, and the filing line is *before* the start line, which is what makes
the window between them empty.

Neither question can be asked of `main_window`, and neither needs one: no `QApplication` is
created in this file, so no window exists at interpreter exit for the exit shape to go wrong
over.

Run: python -X utf8 tests/test_worker_holder_contract.py
"""

import ast
import os
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.ui.performance_tab import PerformanceTab
from src.utils.worker import Worker

PANE = os.path.join(ROOT, 'src', 'ui', 'performance_tab.py')


class Holder:
    """The two attributes the pane's keep-helper and its release verb read, and nothing else.

    `PerformanceTab._keep_worker`, `._release_worker` and `.shutdown_runs` are called on this
    object as the plain Python functions they are. They touch `self._workers` and the runner
    they are handed, which is the whole of what this file asks; the 1,700 lines of widgets the
    real pane builds are what makes asking them in a live pane a race with the process itself.
    """

    _keep_worker = PerformanceTab._keep_worker
    _release_worker = PerformanceTab._release_worker
    shutdown_runs = PerformanceTab.shutdown_runs

    def __init__(self):
        self._workers = []


def calls_written_in(function):
    """Every call typed in this function's own body, with nested definitions left out."""
    found = []
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


class TestWorkerHolderContract(unittest.TestCase):
    def test_01_a_run_handed_to_the_keep_helper_is_held_until_it_reports(self):
        """The append and the release, as two facts about one object.

        `start_benchmark` and its seven siblings keep the run in a local name that dies with
        the method, so this list is the only reference the run has while the pool works on it.
        The release is asked of the same channel the app uses - the runner's own `finished` -
        emitted here, on this thread, which is a direct connection and therefore deterministic
        where the real thing is queued behind a pool thread.
        """
        holder = Holder()
        worker = Worker(lambda progress_callback=None: None)
        self.assertIs(worker, holder._keep_worker(worker),
                      'the helper no longer answers with the run it was given, so a start site '
                      'that keeps its own name would be the only thing holding it')
        self.assertEqual([worker], holder._workers,
                          'a run handed to the keep-helper was not filed in the list the close '
                          'drains: nothing will silence it, nothing will wait for it, and the '
                          'reference of a running worker is the only thing between this process '
                          "and Qt's abort")
        worker.signals.finished.emit()
        self.assertEqual([], holder._workers,
                          'the run reported and the helper still holds it, so a session that '
                          'presses a button fifty times keeps fifty finished runs')

    def test_02_the_pane_files_a_run_before_it_hands_it_to_the_pool(self):
        """Every start site, including the eight this pane has today.

        The test above asks what the helper does with a runner; a call site that stops calling
        the helper leaves it green while the product runs something nobody holds. That half is
        the tree's, and it is read from the tree because executing it is the fault: an unfiled
        `QRunnable` is collected inside `Worker.run`, and the names of what failed are printed
        only in the summary such a process never reaches.
        """
        with open(PANE, encoding='utf-8') as handle:
            tree = ast.parse(handle.read())
        started = 0
        for function in [node for node in ast.walk(tree)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            filed = {}
            for call in calls_written_in(function):
                if (isinstance(call.func, ast.Attribute)
                        and call.func.attr == '_keep_worker'
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == 'self'
                        and len(call.args) == 1
                        and isinstance(call.args[0], ast.Name)):
                    filed.setdefault(call.args[0].id, call.lineno)
            for call in calls_written_in(function):
                if not (isinstance(call.func, ast.Attribute)
                        and call.func.attr == 'start'
                        and ast.unparse(call.func.value) == 'QThreadPool.globalInstance()'
                        and len(call.args) == 1
                        and isinstance(call.args[0], ast.Name)):
                    continue
                started += 1
                name = call.args[0].id
                # `msg` is built before either assertion, and the name it quotes comes from a
                # dict this walk only fills when a filing call exists: an exception escaping a
                # test body is answered by PyQt6 with an abort rather than a traceback, and an
                # aborted suite names nothing - the shape this whole file exists to avoid.
                msg = f'{function.name} starts {name} on the pool at line {call.lineno}'
                self.assertIn(name, filed,
                              msg + ' without filing it in the list its own close drains')
                self.assertLess(filed[name], call.lineno,
                                msg + ' before it files it, which leaves a window in which the '
                                      'run has no owner at all')
        self.assertEqual(8, started,
                         'the pane no longer starts the eight runs this rule was measured on, '
                         'so the walk above has to be re-read rather than trusted')
        print(f'✓ All {started} pool starts in the Performance pane file their run first.')


if __name__ == '__main__':
    unittest.main()
