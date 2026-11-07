import logging
import sys
import traceback
from PyQt6.QtCore import QRunnable, pyqtSlot, QObject, pyqtSignal

# The packaged build has no console (`RenderFox.spec`: console=False), and this is the one
# place every `Worker` run lands when the function it wraps raises. The `error` signal below
# is still what a pane connects to; this record is what the Diagnostics table gets when
# nothing is connected to it.
logger = logging.getLogger(__name__)

class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.
    Supported signals are:
    finished
        No data
    error
        tuple (exctype, value, traceback.format_exc() )
    result
        object data returned from processing, anything
    progress
        int indicating % progress
    """
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)

class Worker(QRunnable):
    """
    Worker thread
    Inherits from QRunnable to handle worker thread setup, signals and wrap-up.
    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function
    """

    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        # Add the callback to our kwargs
        # The function must accept a 'progress_callback' argument if it wants to report progress
        # `.emit` and not the signal itself: a PyQt6 signal object is not callable.
        self.kwargs['progress_callback'] = self.signals.progress.emit

    @pyqtSlot()
    def run(self):
        """
        Initialise the runner function with passed args, kwargs.
        """
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            exctype, value = sys.exc_info()[:2]
            # One traceback, read twice: the record the Diagnostics pane turns into a row, and
            # the tuple a connected pane catches. The write this replaces went to the stream the
            # build has no reader for and formatted the same traceback a second time.
            text = traceback.format_exc()
            logger.error("%s failed: %s", getattr(self.fn, '__name__', repr(self.fn)), text)
            self.signals.error.emit((exctype, value, text))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit()  # Done
