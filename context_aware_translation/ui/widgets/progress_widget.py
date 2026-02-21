"""Progress widget for displaying operation progress."""

import time

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..i18n import qarg


class ProgressWidget(QWidget):
    """A composite widget showing progress with ETA and cancel option."""

    cancelled = Signal()

    def __init__(self, parent=None):
        """Initialize the progress widget.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        self._start_time: float | None = None

        # Create widgets
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)

        self.message_label = QLabel("")
        self.eta_label = QLabel("")
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self.cancelled.emit)

        # Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Progress bar row
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.cancel_button)
        main_layout.addLayout(progress_layout)

        # Info row
        info_layout = QHBoxLayout()
        info_layout.addWidget(self.message_label, stretch=1)
        info_layout.addWidget(self.eta_label)
        main_layout.addLayout(info_layout)

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events including language changes."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate all UI strings."""
        self.cancel_button.setText(self.tr("Cancel"))

    def set_progress(self, current: int, total: int, message: str = "") -> None:
        """Update progress.

        Args:
            current: Current progress value
            total: Total value
            message: Optional status message
        """
        # Initialize timing on first update
        if self._start_time is None:
            self._start_time = time.time()

        # Update progress bar
        percentage = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percentage)

        # Update message
        if message:
            self.message_label.setText(message)
        else:
            self.message_label.setText(qarg(self.tr("%1 / %2"), current, total))

        # Calculate ETA
        if current > 0 and current < total:
            elapsed = time.time() - self._start_time
            rate = current / elapsed  # items per second
            remaining = total - current
            eta_seconds = remaining / rate if rate > 0 else 0

            if eta_seconds > 0:
                eta_text = self._format_time(eta_seconds)
                self.eta_label.setText(qarg(self.tr("ETA: %1"), eta_text))
            else:
                self.eta_label.setText("")
        else:
            self.eta_label.setText("")

    def reset(self) -> None:
        """Reset the progress widget to initial state."""
        # Restore determinate progress mode after indeterminate operations.
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.message_label.setText("")
        self.eta_label.setText("")
        self._start_time = None

    def set_cancellable(self, enabled: bool) -> None:
        """Show or hide the cancel button.

        Args:
            enabled: Whether cancel button should be visible
        """
        self.cancel_button.setVisible(enabled)

    def _format_time(self, seconds: float) -> str:
        """Format seconds into human-readable time.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted time string
        """
        if seconds < 60:
            return qarg(self.tr("%1s"), int(seconds))
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return qarg(self.tr("%1m %2s"), minutes, secs)
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return qarg(self.tr("%1h %2m"), hours, minutes)
