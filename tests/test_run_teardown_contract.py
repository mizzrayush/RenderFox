"""The two questions the close asks a pane, asked where nothing can crash before the answer.

This file exists because of how `tools/mutation_check.py` reads a run. Four of the sixteen
defects in the teardown list - a run filed in no bucket, a bucket the close does not drain,
and a `disconnect()` on a signal with no receivers - were each detected by the headless tab
suite, and detecting them there means **killing it**: the mutation leaves a `QRunnable` the
pane never referenced while the pool still runs it, or leaves a verdict queued into widgets
the window has destroyed, and Qt answers both with an access violation (0xc0000005) or a
fail-fast (0xc0000409) rather than a traceback. unittest prints the names of what went wrong
only in its summary, so a process that dies in the fifth test reports nothing at all, and a
defect nobody can read is a defect nobody can fix twice. The rule in this project is that a
mutation which no test catches gets a test rather than a pass, so here are those tests, in a
file that never starts a run.

What is asked is the same three facts the panes are supposed to keep. A `Worker` handed to a
pane's own keep-helper must end up in the list the pane's `shutdown_runs` drains, must leave
it when the pool says the queue emptied, and must have nothing left connected when the close
is done - including for the Diagnostics pane, which keeps two lists and names both exactly
once, in the sum that is handed to the helper. That pane is why the third fact is asked
separately: its close rebuilds both lists from what the wait still owes, so a bucket the
helper never touched comes back looking emptied. And a runner with nothing connected has to
come back from `silence` as nothing taken off, not as an exception, because `silence` is
called from `closeEvent`, and an exception that escapes a slot is how this app ends instead
of reporting.

Run: python -X utf8 tests/test_run_teardown_contract.py
"""

import os
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtCore import QThread, QThreadPool
from PyQt6.QtWidgets import QApplication

from src.ui.diagnostics_tab import DiagnosticsTab
from src.ui.mesh_tools_tab import MeshToolsTab
from src.ui.performance_tab import PerformanceTab
from src.utils.run_teardown import channels, silence
from src.utils.worker import Worker


class TestRunTeardownContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.mesh = MeshToolsTab()
        cls.perf = PerformanceTab()
        cls.diag = DiagnosticsTab()
        # The pane's own sample timer would put real readers on the shared pool while this
        # test is asking what the pool answers about the runs it is handed.
        cls.perf.performance_analyzer.stop_monitoring()

    @classmethod
    def tearDownClass(cls):
        for pane in (cls.mesh, cls.perf, cls.diag):
            pane.shutdown_runs(timeout_ms=10000)
        QThreadPool.globalInstance().waitForDone(20000)
        cls.app.processEvents()

    def drain_global_pool(self):
        """Make the shared pool idle, and refuse to measure against a busy one.

        `waitForDone` is the only answer a pool gives, and it answers for every run queued on
        it - so a pool still holding another pane's work would make the release assertions
        below say something about a run this test never started.
        """
        drained = QThreadPool.globalInstance().waitForDone(20000)
        self.assertTrue(drained,
                        'the shared pool was still busy, so its answer is not this pane\'s')
        return QThreadPool.globalInstance()

    def test_01_a_runner_with_nothing_connected_is_silenced_without_raising(self):
        """Qt's `TypeError` for an empty connection is the same fact as "nothing reaches here".

        The helper's `except TypeError` is what turns it into a list of names that came off.
        Change that clause to any other error and the raise runs on through `drain`, through
        the pane's `shutdown_runs`, out of `closeEvent` - and PyQt ends the process at the
        edge of a slot instead of showing a traceback. Nothing is started here, so the
        answer arrives as a named test on a suite that is still alive.
        """
        runnable = Worker(lambda progress_callback=None: None)
        self.assertGreater(len(channels(runnable)), 0,
                           'a runner with no channels proves nothing about disconnecting them')
        self.assertEqual([], silence(runnable),
                         'a runner nobody connected to is reported as a run something came off')
        self.assertEqual([], silence(runnable),
                         'the second pass over an already-silent runner is the same case again')

        threaded = QThread()  # Qt's own channels, none of them connected to anything
        self.assertGreater(len(channels(threaded)), 0,
                           'a thread with no signals to take off proves nothing either')
        self.assertEqual([], silence(threaded),
                         'the same question asked of a QObject that is not a QRunnable')
        print('✓ A runner with nothing connected silences to nothing instead of raising.')

    def test_02_a_run_is_filed_in_the_bucket_the_close_drains(self):
        """Keep-helper in, bucket out, receivers off - for every list the pane keeps.

        The line that files a run is the line a pane forgets when it grows a second list, and
        it is invisible from outside until the close, which is where it stops being a test
        problem and becomes a dead process. A `Worker` that is never handed to the pool is
        enough to see the filing, and the pane's own `shutdown_runs` is enough to see the
        release, because the pool it is asked about is empty.

        The emptying alone is not the contract, and the third pane is what proves it: its
        close rebuilds *both* lists from whatever the wait still owes, so dropping one list
        out of the sum it drains leaves that bucket perfectly empty and still connected. Ask
        the runner itself - after the close, nothing should be left on it to come off.
        """
        pool = self.drain_global_pool()

        filed = Worker(lambda progress_callback=None: None)
        self.mesh._keep_worker(filed)
        self.assertIn(filed, self.mesh._runs,
                      'Mesh Tools filed nothing where it said it held the operation')
        self.assertEqual(0, self.mesh.shutdown_runs(timeout_ms=1000),
                         'Mesh Tools owed a run that never started')
        self.assertNotIn(filed, self.mesh._runs,
                         'the bucket kept a run the pool had finished with')
        self.assertEqual([], silence(filed),
                         'the closed bucket still has a receiver on its run')

        read = Worker(lambda progress_callback=None: None)
        self.perf._keep_worker(read)
        self.assertIn(read, self.perf._workers,
                      'Performance filed nothing where it said it held the machine reader')
        self.assertEqual(0, self.perf.shutdown_runs(timeout_ms=1000),
                         'Performance owed a run that never started')
        self.assertNotIn(read, self.perf._workers,
                         'a finished reader was never released')
        self.assertEqual([], silence(read),
                         'the finished reader is still wired to the pane it writes into')

        benchmark = Worker(lambda progress_callback=None: None)
        measure = Worker(lambda progress_callback=None: None)
        self.diag._keep_worker(self.diag._benchmark_workers, benchmark)
        self.diag._keep_worker(self.diag._measure_workers, measure)
        self.assertIn(benchmark, self.diag._benchmark_workers,
                      'the benchmark list was not the one this run was filed in')
        self.assertIn(measure, self.diag._measure_workers,
                      'the measurement list was not the one this run was filed in')
        self.assertEqual(0, self.diag.shutdown_runs(timeout_ms=1000),
                         'Diagnostics owed a run that never started')
        self.assertEqual([], self.diag._benchmark_workers,
                          'the first of the two buckets was never emptied')
        self.assertEqual([], self.diag._measure_workers,
                          'Diagnostics drained the bucket it summed and left the other one '
                          'holding a run the pool had finished')
        self.assertEqual([], silence(benchmark),
                         'the benchmark run reached the close still wired to its own release')
        self.assertEqual([], silence(measure),
                          'the measurement run is drained from neither list: emptied by the '
                          're-filter that rebuilds every bucket, and still connected to the '
                          'report view it writes into')
        self.assertTrue(pool.waitForDone(5000), 'the pool this test never used is still busy')
        print('✓ Every bucket a pane keeps is filed, emptied and silenced by its close verb, '
              'both Diagnostics lists included.')


if __name__ == '__main__':
    unittest.main()
