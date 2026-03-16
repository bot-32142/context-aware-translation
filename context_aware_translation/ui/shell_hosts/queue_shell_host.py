from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from context_aware_translation.ui.shell_hosts.hybrid import HybridShellHost
from context_aware_translation.ui.viewmodels.queue_shell import QueueShellViewModel


class QueueShellHost(HybridShellHost):
    """Secondary-surface shell host for the queue drawer chrome."""

    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.viewmodel = QueueShellViewModel(parent)
        self._queue_widget: QWidget | None = None
        super().__init__(
            "queue/QueueShellChrome.qml",
            context_objects={"queueShell": self.viewmodel},
            parent=parent,
        )
        self._connect_qml_signals()

    def set_queue_widget(self, widget: QWidget) -> QWidget:
        self._queue_widget = widget
        registered = self.register_content("queue", widget)
        self.show_content("queue")
        return registered

    def set_scope(self, project_id: str | None, *, project_name: str | None = None) -> None:
        self.viewmodel.set_scope(project_id, project_name=project_name)
        if self._queue_widget is not None:
            set_scope = getattr(self._queue_widget, "set_scope", None)
            if callable(set_scope):
                set_scope(project_id, project_name=project_name)

    def clear_scope(self) -> None:
        self.viewmodel.clear_scope()
        if self._queue_widget is not None:
            set_scope = getattr(self._queue_widget, "set_scope", None)
            if callable(set_scope):
                set_scope(None)

    def retranslate(self) -> None:
        self.viewmodel.retranslate()
        if self._queue_widget is not None:
            retranslate = getattr(self._queue_widget, "retranslateUi", None)
            if callable(retranslate):
                retranslate()

    def cleanup(self) -> None:
        super().cleanup()
        self._queue_widget = None

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.closeRequested.connect(self.close_requested.emit)
