from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, QT_TRANSLATE_NOOP, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_PROJECT_SETTINGS_SUBTITLE = QT_TRANSLATE_NOOP(
    "ProjectSettingsPane",
    "Choose a shared workflow profile, or select Custom profile to edit connection and model choices for this project.",
)


class ProjectSettingsDialogViewModel(ViewModelBase):
    """QML-facing state for the project-settings dialog chrome."""

    labels_changed = Signal()
    presented_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._is_presented = False

    @Property(str, notify=labels_changed)
    def title(self) -> str:
        return QCoreApplication.translate("MainWindow", "Project Settings")

    @Property(str, notify=labels_changed)
    def subtitle(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", _PROJECT_SETTINGS_SUBTITLE)

    @Property(bool, notify=presented_changed)
    def is_presented(self) -> bool:
        return self._is_presented

    def present(self) -> None:
        if self._is_presented:
            return
        self._is_presented = True
        self.presented_changed.emit()
        self.mark_changed()

    def dismiss(self) -> None:
        if not self._is_presented:
            return
        self._is_presented = False
        self.presented_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()
