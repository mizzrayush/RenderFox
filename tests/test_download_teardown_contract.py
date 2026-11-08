"""The two holders the close could only reach by being asked from inside the run.

Phase 6o moved the stop-over-a-live-run from a list of tabs to a walk of the whole widget
tree, which reaches every pane - and reaches nothing at all in the two shapes this file asks
about. One is the AI Model Manager's `QThread`, started inside a dialog the Settings pane kept
in a function-local and parented to nothing: no walk above it could see either the download or
the reference that keeps Qt from ending the process. The other is how that dialog is closed -
`done()`, which the Close button, the title-bar cross, Escape and the completion path all
funnel into, so a stop asked anywhere else covers whoever forgets to ask it.

Why these four tests are not in `tests/test_run_teardown_contract.py`, measured rather than
chosen: the download tests enter Qt as well as leave it, because `done()` is a virtual Qt
calls. Plant a defect in the shared helper's `except TypeError` clause - the defect that
file's `test_01` owns - and the raise escapes this code's `done()` override and ends the
process exactly as one escaping a slot does: four named errors, then exit `0xc0000409`, and no
report at all. Split in two, each file answers its own defects as names. The helper's clause is
read where nothing enters a C++ frame, and the shapes below are read against their own
single-line defects, which every one of them catches.

What is asked is the same three facts the panes keep - hold the run, take its receivers off,
let go only when it has ended - plus the two lines around the modal `exec()` that decide
whether the tree can see the dialog at all.

Run: python -X utf8 tests/test_download_teardown_contract.py
"""

import contextlib
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication, QWidget

from src.features.model_downloader import (
    ModelDownloaderDialog, ModelDownloaderThread)
from src.ui.settings_tab import SettingsTab
from src.utils.run_teardown import silence


class _FakeHub(types.ModuleType):
    """The two network calls `ModelDownloaderThread.run` makes, recorded instead of sent.

    `hf_hub_download` blocks, because the only interesting moment of a stop is the one where
    a step is already in flight and cannot be interrupted. Nothing here touches a network and
    nothing here is installed: the module goes into `sys.modules` for the length of one test,
    which is what makes the second step's absence a fact about this code rather than about a
    download server.
    """

    def __init__(self, hold_seconds):
        super().__init__('huggingface_hub')
        self.hold_seconds = hold_seconds
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def hf_hub_download(self, **kwargs):
        self.calls.append('sd')
        self.entered.set()
        self.release.wait(self.hold_seconds)

    def snapshot_download(self, **kwargs):
        self.calls.append('clip')


class TestDownloadTeardownContract(unittest.TestCase):
    """The numbering continues the file these tests were split out of, because the mutation
    spec names them by it."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    @classmethod
    def tearDownClass(cls):
        QThreadPool.globalInstance().waitForDone(20000)
        cls.app.processEvents()

    @contextlib.contextmanager
    def download_fixture(self, hold_seconds):
        """A downloader whose two network calls are here, writing into a tree that goes away.

        `run` asks `src/utils/app_paths.py` where its models go, so `RENDERFOX_DATA_DIR` is
        the one thing to move to put `ai_models` somewhere the test can delete; the fake module
        is what keeps the test off a network it has no business using.

        The recorded `start` is what keeps the test alive. Every thread that comes through
        here is waited on when the fixture closes, whatever the body did in between - a body
        cut short before its own stop leaves its download running and its dialog in a frame
        that is about to die, and the last reference of a running `QThread` is the one thing
        between this process and Qt's abort.
        """
        home = tempfile.mkdtemp(prefix='renderfox_dl_')
        previous_module = sys.modules.get('huggingface_hub')
        previous_data = os.environ.get('RENDERFOX_DATA_DIR')
        previous_start = ModelDownloaderThread.start
        hub = _FakeHub(hold_seconds)
        started = []

        def record_then_start(thread):
            started.append(thread)
            previous_start(thread)

        ModelDownloaderThread.start = record_then_start
        sys.modules['huggingface_hub'] = hub
        os.environ['RENDERFOX_DATA_DIR'] = home
        try:
            yield hub
        finally:
            hub.release.set()
            for thread in started:
                self.assertTrue(thread.wait(15000),
                                'the download this fixture launched never reached its end')
            ModelDownloaderThread.start = previous_start
            if previous_data is None:
                del os.environ['RENDERFOX_DATA_DIR']
            else:
                os.environ['RENDERFOX_DATA_DIR'] = previous_data
            if previous_module is None:
                del sys.modules['huggingface_hub']
            else:
                sys.modules['huggingface_hub'] = previous_module
            shutil.rmtree(home, ignore_errors=True)

    def test_04_the_download_dialog_stops_holds_and_silences_the_thread_inside_it(self):
        """The AI Model Manager is the run the object tree could not see.

        Its `QThread` is a member of a dialog `Settings` kept in a function-local, and the
        measured fact behind this test is the abort: dropping the last reference of a running
        `QThread` ended the process at the drop itself, while dropping a finished one
        survived. So the close owes two things here - the reference, for a download still in
        flight, and the release of it once it is not - and both are answered from the dialog,
        because no holder above it can see a thread that lives in a widget nobody parented.
        `auto_start=False` is not a preference: the default constructor starts a download of
        its own, and the assignment that follows it then drops that running thread - which is
        this same abort, measured here as `0xc0000409` at the assignment itself.
        """
        with self.download_fixture(hold_seconds=6) as hub:
            dialog = ModelDownloaderDialog(auto_start=False)
            dialog.start_download()
            self.assertTrue(hub.entered.wait(5),
                            'the download never reached the step it blocks in')
            thread = dialog.thread
            self.assertEqual(1, dialog.shutdown_runs(timeout_ms=200),
                             'a download still in flight was answered as finished')
            self.assertIs(thread, dialog.thread,
                          'the reference that keeps Qt from aborting was let go of')
            self.assertEqual([], silence(thread),
                             'the close left the progress bar wired to a download still running')

            hub.release.set()
            self.assertEqual(0, dialog.shutdown_runs(timeout_ms=5000),
                             'the wait was not told the download had ended')
            self.assertIsNone(dialog.thread, 'a finished download stayed in the attribute')
        print('✓ The downloader dialog holds, silences and releases its own running thread.')

    def test_05_the_dialogs_own_way_out_is_where_the_stop_is_asked(self):
        """`done()` is the one line every exit passes through, and it is what asks.

        The Close button, the title-bar cross, Escape, and the completion and error paths all
        funnel into `done()`, so stopping there covers a caller that never thinks to call the
        close verb at all. The proof is the second step: a stop asked at the boundary means
        `snapshot_download` is never called, and a stop nobody asked runs it after the dialog
        is gone - which is also the half of this that no `silence` can cover, because a
        download is a network call and a network call is not interruptible from outside.
        """
        with self.download_fixture(hold_seconds=2) as hub:
            dialog = ModelDownloaderDialog(auto_start=False)
            dialog.start_download()
            self.assertTrue(hub.entered.wait(5),
                            'the download never reached the step it blocks in')
            dialog.reject()
            self.assertEqual(['sd'], hub.calls,
                             'the step after the one in flight was started anyway, so the way '
                             'out of the dialog asked nothing of the download')
            self.assertIsNone(dialog.thread, 'the closed dialog still holds the reference')
        print('✓ Closing the manager the way the user does stops the download at its boundary.')

    def test_06_the_settings_pane_opens_the_manager_inside_itself_and_keeps_it(self):
        """The two lines around a modal `exec()` are the whole reachability of this run.

        `download_ai_models` is driven with the loop taken out, because what the close leans
        on is the line before it - the dialog is a child of the pane, so the tree walk finds
        it and asks it - and the line after it, where the reference has to be an attribute of
        the pane rather than a local that dies with the call. A dialog that is neither is a
        run this app has no way to stop.
        """
        pane = SettingsTab()
        seen = []
        previous = ModelDownloaderDialog.exec
        ModelDownloaderDialog.exec = lambda dialog: (seen.append(dialog), 0)[1]
        try:
            pane.download_ai_models()
        finally:
            ModelDownloaderDialog.exec = previous

        self.assertEqual(1, len(seen), 'the pane never opened the manager it says it opens')
        dialog = seen[0]
        self.assertIs(pane, dialog.parent(),
                      'the manager is a child of nothing, so no close walk can reach it')
        self.assertIs(dialog, getattr(pane, 'model_manager', None),
                      'the only reference to the dialog died with the call')
        self.assertIn(dialog, pane.findChildren(QWidget),
                      'the dialog is not in the pane\'s tree, so the walk cannot ask it')
        self.assertEqual(0, dialog.shutdown_runs(timeout_ms=100),
                         'a manager with no download running owes the close a run')

    def test_07_a_stop_asked_before_the_run_begins_leaves_nothing_to_run(self):
        """The two step guards are what a stop asked early is worth.

        A close can ask while the thread is still queued to start, and a step that has
        already begun cannot be interrupted - so the step boundary is the whole answer, and it
        is read off the fake hub's own record: no call at all, and no `finished` that would
        tell a user the downloads are complete when nothing was downloaded.

        The `finished` half is a signal emitted from inside the worker, so it arrives in the
        main thread as a queued event: the wait tells the thread had ended, and only the
        event loop delivers the verdict that went with it. Reading `ended` before that is
        reading an empty list whatever the code did, which is how a download that announced
        itself complete slipped past this test once already.
        """
        with self.download_fixture(hold_seconds=2) as hub:
            thread = ModelDownloaderThread(download_sd=True, download_clip=True)
            ended = []
            thread.finished.connect(lambda: ended.append(1))
            thread.request_stop()
            thread.start()
            self.assertTrue(thread.wait(8000), 'the stopped download never ended')
            self.app.processEvents()
            self.assertEqual([], hub.calls,
                              'a stop asked before the first step still ran both of them')
            self.assertEqual([], ended, 'a download that ran nothing reported itself complete')


if __name__ == '__main__':
    unittest.main()
