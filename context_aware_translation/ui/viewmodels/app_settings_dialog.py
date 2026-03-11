from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_APP_SETTINGS_SUBTITLE = (
    "App Setup manages reusable connections and shared workflow profiles. "
    "The wizard creates a concrete shared workflow profile using the existing "
    "step-based config system."
)


class AppSettingsDialogViewModel(ViewModelBase):
    """QML-facing state for the app-settings dialog chrome."""

    labels_changed = Signal()
    presented_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._is_presented = False

    @Property(str, notify=labels_changed)
    def title(self) -> str:
        return QCoreApplication.translate("MainWindow", "App Settings")

    @Property(str, notify=labels_changed)
    def subtitle(self) -> str:
        return QCoreApplication.translate("AppSettingsPane", _APP_SETTINGS_SUBTITLE)

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
