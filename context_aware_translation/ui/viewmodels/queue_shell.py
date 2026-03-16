from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase


class QueueShellViewModel(ViewModelBase):
    """QML-facing chrome state for the queue secondary surface."""

    scope_changed = Signal()
    labels_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._project_id: str | None = None
        self._project_name = ""

    @Property(bool, notify=scope_changed)
    def has_project_scope(self) -> bool:
        return self._project_id is not None

    @Property(str, notify=labels_changed)
    def title(self) -> str:
        return QCoreApplication.translate("QueueDrawerView", "Queue")

    @Property(str, notify=scope_changed)
    def subtitle(self) -> str:
        if self._project_id is None:
            return QCoreApplication.translate("QueueDrawerView", "Showing background actions across all projects.")
        if self._project_name:
            template = QCoreApplication.translate("QueueDrawerView", "Showing background actions for {0}.")
            return template.format(self._project_name)
        return QCoreApplication.translate("QueueDrawerView", "Showing background actions for the current project.")

    def set_scope(self, project_id: str | None, *, project_name: str | None = None) -> None:
        normalized_name = (project_name or "").strip()
        if project_id == self._project_id and normalized_name == self._project_name:
            return
        self._project_id = project_id
        self._project_name = normalized_name
        self.scope_changed.emit()
        self.mark_changed()

    def clear_scope(self) -> None:
        self.set_scope(None)

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.scope_changed.emit()
        self.mark_changed()
