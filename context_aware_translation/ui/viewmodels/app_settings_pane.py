from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, QT_TRANSLATE_NOOP, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = QT_TRANSLATE_NOOP(
    "AppSettingsPane",
    "App Setup manages reusable connections and shared workflow profiles. "
    "The wizard creates a concrete shared workflow profile using the existing "
    "step-based config system.",
)


class AppSettingsPaneViewModel(ViewModelBase):
    """QML-facing state for the app-settings dialog body."""

    labels_changed = Signal()
    content_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._current_tab = "connections"
        self._action_buttons: list[dict[str, object]] = []

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate("AppSettingsPane", _TIP_TEXT)

    @Property(str, notify=labels_changed)
    def connections_tab_label(self) -> str:
        return QCoreApplication.translate("AppSettingsPane", "Connections")

    @Property(str, notify=labels_changed)
    def profiles_tab_label(self) -> str:
        return QCoreApplication.translate("AppSettingsPane", "Workflow Profiles")

    @Property(str, notify=content_changed)
    def current_tab(self) -> str:
        return self._current_tab

    @Property(bool, notify=content_changed)
    def showing_connections(self) -> bool:
        return self._current_tab == "connections"

    @Property(bool, notify=content_changed)
    def showing_profiles(self) -> bool:
        return self._current_tab == "profiles"

    @Property("QVariantList", notify=content_changed)
    def action_buttons(self) -> list[dict[str, object]]:
        return self._action_buttons

    def apply_state(self, *, current_tab: str, action_buttons: list[dict[str, object]]) -> None:
        self._current_tab = current_tab
        self._action_buttons = [dict(button) for button in action_buttons]
        self.content_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.content_changed.emit()
        self.mark_changed()
