"""Base worker class for background operations."""

import logging

from PySide6.QtCore import QThread, Signal

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressUpdate
from context_aware_translation.ui import sleep_inhibitor

logger = logging.getLogger(__name__)


class BaseWorker(QThread):
    """Base worker with common signals and error handling template."""

    progress = Signal(int, int, str)  # current, total, message
    finished_success = Signal(object)  # result data
    cancelled = Signal()  # cancelled by user
    error = Signal(str)  # error message

    def _emit_progress(self, update: ProgressUpdate) -> None:
        """Convert ProgressUpdate to signal emission."""
        self._raise_if_cancelled()
        self.progress.emit(update.current, update.total, update.message)
        self._raise_if_cancelled()

    def _raise_if_cancelled(self) -> None:
        """Raise cooperative cancellation if interruption was requested."""
        if self.isInterruptionRequested():
            raise OperationCancelledError("Worker interrupted")

    def _is_cancelled(self) -> bool:
        """Return True when interruption has been requested."""
        return self.isInterruptionRequested()

    def run(self) -> None:
        """Execute worker with standard error handling.

        Subclasses should override _execute() instead of run().
        """
        sleep_inhibitor.SleepInhibitor.acquire()
        try:
            self._raise_if_cancelled()
            self._execute()
        except OperationCancelledError:
            logger.info("%s cancelled", self.__class__.__name__)
            self.cancelled.emit()
        except Exception as e:
            logger.exception(f"{self.__class__.__name__} failed")
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            sleep_inhibitor.SleepInhibitor.release()

    def _execute(self) -> None:
        """Execute the worker's main task.

        Subclasses must override this method to implement their logic.
        Should emit finished_success signal when complete.
        """
        raise NotImplementedError("Subclasses must implement _execute()")
