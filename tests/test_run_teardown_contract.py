"""The two questions the close asks a pane, asked where nothing can crash before the answer.

This file exists because of how `tools/mutation_check.py` reads a run. Four of the sixteen
defects the teardown list had when this file was written were each detected by the headless tab
suite, and detecting them there means **killing it**: the mutation leaves a `QRunnable` the
pane never referenced while the pool still runs it, or leaves a verdict queued into widgets
the window has destroyed, and Qt answers both with an access violation (0xc0000005) or a
fail-fast (0xc0000409) rather than a traceback. unittest prints the names of what went wrong
only in its summary, so a process that dies in the fifth test reports nothing at all, and a
defect nobody can read is a defect nobody can fix twice. The rule in this project is that a
mutation which no test catches gets a test rather than a pass, so here are those tests, in a
file that never enters a C++ frame: no `closeEvent`, no `done()` override, every helper called
as the plain Python function it is. That is the whole reason
`tests/test_download_teardown_contract.py` exists beside it - the AI Model Manager's dialog
stops its download inside `done()`, which Qt calls, so a defect in the clause this file's
first test owns raises through that override and ends the process before any name is printed.
Measured here as four named errors followed by exit `0xc0000409` and no report at all. Ten of
the list's thirty-two entries are read here, and every one of them plants one of four steps:
the clause that turns an empty `disconnect()` into "nothing came off", the lines that file a
run in the bucket its close drains, the wait that answers for a runner which is not a
`QThread`, and the pane's own answer - how many runs it reports owed, and whose receivers it
takes off.

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

The last test asks the same three facts of the one run no `QObject` can be handed over for:
the Automation pane's Auto Actions worker is a plain `threading.Thread`, so it has no channel
of its own to take off and no stop verb to ask, and the only thing a close can do with it is
wait - which needs the list it was filed in, and needs the pane's own signal taken off,
because that signal is how the worker's verdict travels.

Run: python -X utf8 tests/test_run_teardown_contract.py
"""

import os
import sys
import threading
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtCore import QThread, QThreadPool
from PyQt6.QtWidgets import QApplication

from src.ui.automation_tab import AutomationTab
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
        cls.auto = AutomationTab()
        # The pane's own sample timer would put real readers on the shared pool while this
        # test is asking what the pool answers about the runs it is handed.
        cls.perf.performance_analyzer.stop_monitoring()

    @classmethod
    def tearDownClass(cls):
        for pane in (cls.mesh, cls.perf, cls.diag, cls.auto):
            # A defective close verb raises here, after the tests that name it have already
            # run. Letting it escape strands every pane behind it, and a stranded run loses
            # its references with this frame - which is the abort this file refuses to
            # answer with.
            try:
                pane.shutdown_runs(timeout_ms=10000)
            except Exception as error:
                print(f'teardown: {type(pane).__name__} raised {type(error).__name__}: {error}')
        # The scheduler's polling thread is the engine's own run, and the engine is stopped
        # by the window's close in the app; here nothing else reaches it.
        cls.auto.automation_engine.stop()
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
        edge of a slot instead of showing a traceback. That is why this answer is asked here
        and not through a window: a call made from Python raises into a test that names it,
        while the same raise through a virtual Qt calls ends the process and buries every name
        with it. Nothing is started in this test; the plain worker the third test starts stays
        in the pane's own list, so no frame dying here can drop its last reference.
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

    def test_03_a_plain_thread_is_filed_joined_and_silenced_by_the_pane_that_started_it(self):
        """Automation's Auto Actions worker has no channel, no verb and no `QObject`.

        `threading.Thread` answers neither `disconnect` nor any of the four stop spellings, so
        everything the close can do with it is the wait - and a wait needs the list it was
        filed in. The verdict travels on the pane's own `auto_actions_finished`, so the
        silencing half cannot be asked of the runner and has to be asked of the pane; that is
        the line a pane with no `QObject` to hand over would otherwise skip, and the reason
        `silence` is called twice here rather than once.
        """
        gate, release, finished_worker = threading.Event(), threading.Event(), threading.Event()

        def blocked(file_path, settings):
            gate.set()
            release.wait(10)
            time.sleep(0.2)
            finished_worker.set()
            self.auto.auto_actions_finished.emit(file_path, ['watched file'])

        previous = self.auto._emit_auto_actions
        self.auto._emit_auto_actions = blocked
        self.addCleanup(setattr, self.auto, '_emit_auto_actions', previous)
        self.assertEqual(1, self.auto.receivers(self.auto.auto_actions_finished),
                         'the pane never wired its own verdict channel, so nothing is proved')

        self.auto._spawn_action_run('watched.obj', {'backup': True})
        self.assertTrue(gate.wait(5), 'the Auto Actions worker never reached its blocking call')
        thread = self.auto._action_threads[0]
        self.assertEqual(1, self.auto.shutdown_runs(timeout_ms=200),
                         'a worker that would not end was answered to the close as ended')
        self.assertIn(thread, self.auto._action_threads,
                      'the run that outlasted the wait was dropped from the list that holds it')
        self.assertEqual(0, self.auto.receivers(self.auto.auto_actions_finished),
                         'the pane left its own log wired to a worker that is still running')

        release.set()
        self.assertEqual(0, self.auto.shutdown_runs(timeout_ms=5000),
                         'a worker that had ended is still owed to the pane')
        self.assertTrue(finished_worker.is_set(),
                        'the close said it had waited, and the worker was still between its '
                        'last file operation and its verdict')
        self.assertEqual([], self.auto._action_threads,
                         'the finished worker stayed in the list, as it would for every file '
                         'the watcher found')

        self.auto._spawn_action_run('second.obj', {'backup': True})
        second = self.auto._action_threads[-1]
        second.join(5)
        self.assertFalse(second.is_alive(), 'the second worker never ended')
        self.auto._spawn_action_run('third.obj', {'backup': True})
        third = self.auto._action_threads[-1]
        self.assertEqual([third], self.auto._action_threads,
                         'nothing pruned the worker that had already ended, so the list '
                         'grows one entry per watched file for the life of the session')
        self.assertEqual(0, self.auto.shutdown_runs(timeout_ms=5000))
        self.assertEqual([], self.auto._action_threads)
        print('✓ A plain thread is filed, waited on, silenced and pruned by its pane.')

if __name__ == '__main__':
    unittest.main()
