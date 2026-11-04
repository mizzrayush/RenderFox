"""
Base worker class with global exception handling.
"""
import traceback
import logging
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

class SafeWorker(QThread):
    """
    Base class for workers that provides safe execution with error handling.
    Subclasses should implement `safe_run` instead of `run`.
    """
    error_occurred = pyqtSignal(str)
    finished_safe = pyqtSignal()

    def run(self):
        try:
            self.safe_run()
        except Exception as e:
            error_msg = f"Worker error: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            self.error_occurred.emit(str(e))
        finally:
            self.finished_safe.emit()

    def safe_run(self):
        """
        Implement the actual worker logic here.
        Raises exceptions that will be caught by `run`.
        """
        raise NotImplementedError("Subclasses must implement safe_run")
