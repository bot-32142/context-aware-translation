from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, QT_TRANSLATE_NOOP, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = QT_TRANSLATE_NOOP(
    "ProjectSettingsPane",
    "Choose a shared workflow profile, or select Custom profile to edit connection and model choices for this project.",
)
_ROUTES_HINT_TEXT = QT_TRANSLATE_NOOP(
    "ProjectSettingsPane",
    "Step-specific route overrides remain editable below during this migration.",
)
_PROFILE_OPTION_DETAIL_KEYS = {"detail"}


class ProjectSettingsPaneViewModel(ViewModelBase):
    """QML-facing state for the project-settings dialog body."""

    labels_changed = Signal()
    content_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._project_name = ""
        self._blocker_text = ""
        self._message_text = ""
        self._message_kind = ""
        self._profile_options: list[dict[str, object]] = []
        self._custom_profile_text = ""
        self._show_custom_profile = False
        self._show_open_app_setup = False
        self._can_save = False
        self._open_app_setup_tooltip = ""
        self._save_tooltip = ""

    @Property(str, notify=labels_changed)
    def title_text(self) -> str:
        if not self._project_name:
            return QCoreApplication.translate("ProjectSettingsPane", "Project Setup")
        return QCoreApplication.translate("ProjectSettingsPane", "Setup for %1").replace("%1", self._project_name)

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", _TIP_TEXT)

    @Property(str, notify=labels_changed)
    def workflow_profile_label(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", "Workflow profile")

    @Property(str, notify=labels_changed)
    def custom_profile_label(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", "Custom profile")

    @Property(str, notify=labels_changed)
    def open_app_setup_label(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", "Open App Setup")

    @Property(str, notify=labels_changed)
    def save_label(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", "Save")

    @Property(str, notify=labels_changed)
    def routes_hint_text(self) -> str:
        return QCoreApplication.translate("ProjectSettingsPane", _ROUTES_HINT_TEXT)

    @Property(str, notify=content_changed)
    def blocker_text(self) -> str:
        return self._blocker_text

    @Property(bool, notify=content_changed)
    def has_blocker(self) -> bool:
        return bool(self._blocker_text)

    @Property(str, notify=content_changed)
    def message_text(self) -> str:
        return self._message_text

    @Property(bool, notify=content_changed)
    def has_message(self) -> bool:
        return bool(self._message_text)

    @Property(str, notify=content_changed)
    def message_kind(self) -> str:
        return self._message_kind

    @Property("QVariantList", notify=content_changed)
    def profile_options(self) -> list[dict[str, object]]:
        return self._profile_options

    @Property(bool, notify=content_changed)
    def has_profile_options(self) -> bool:
        return bool(self._profile_options)

    @Property(str, notify=content_changed)
    def custom_profile_text(self) -> str:
        return self._custom_profile_text

    @Property(bool, notify=content_changed)
    def show_custom_profile(self) -> bool:
        return self._show_custom_profile

    @Property(bool, notify=content_changed)
    def show_open_app_setup(self) -> bool:
        return self._show_open_app_setup

    @Property(bool, notify=content_changed)
    def can_save(self) -> bool:
        return self._can_save

    @Property(str, notify=content_changed)
    def open_app_setup_tooltip(self) -> str:
        return self._open_app_setup_tooltip

    @Property(str, notify=content_changed)
    def save_tooltip(self) -> str:
        return self._save_tooltip

    def apply_state(
        self,
        *,
        project_name: str,
        blocker_text: str,
        profile_options: list[dict[str, object]],
        custom_profile_text: str,
        show_custom_profile: bool,
        show_open_app_setup: bool,
        can_save: bool,
    ) -> None:
        self._project_name = project_name
        self._blocker_text = blocker_text
        self._profile_options = self._translate_profile_options(profile_options)
        self._custom_profile_text = custom_profile_text
        self._show_custom_profile = show_custom_profile
        self._show_open_app_setup = show_open_app_setup
        self._can_save = can_save
        self._open_app_setup_tooltip = (
            QCoreApplication.translate(
                "ProjectSettingsPane", "Open App Setup to configure shared connections and profiles."
            )
            if show_open_app_setup
            else ""
        )
        self._save_tooltip = (
            QCoreApplication.translate("ProjectSettingsPane", "Save the selected workflow profile for this project.")
            if can_save
            else QCoreApplication.translate(
                "ProjectSettingsPane", "Select or configure a workflow profile before saving project setup."
            )
        )
        self._emit_content_changed()

    def set_message(self, text: str, *, is_error: bool) -> None:
        self._message_text = text
        self._message_kind = "error" if text and is_error else "success" if text else ""
        self._emit_content_changed()

    def clear_message(self) -> None:
        self.set_message("", is_error=False)

    def retranslate(self) -> None:
        self._profile_options = self._translate_profile_options(self._profile_options)
        self._open_app_setup_tooltip = (
            QCoreApplication.translate(
                "ProjectSettingsPane", "Open App Setup to configure shared connections and profiles."
            )
            if self._show_open_app_setup
            else ""
        )
        self._save_tooltip = (
            QCoreApplication.translate("ProjectSettingsPane", "Save the selected workflow profile for this project.")
            if self._can_save
            else QCoreApplication.translate(
                "ProjectSettingsPane", "Select or configure a workflow profile before saving project setup."
            )
        )
        self.labels_changed.emit()
        self._emit_content_changed()

    def _emit_content_changed(self) -> None:
        self.content_changed.emit()
        self.mark_changed()

    def _translate_profile_options(self, profile_options: list[dict[str, object]]) -> list[dict[str, object]]:
        translated_options: list[dict[str, object]] = []
        for option in profile_options:
            translated_option = dict(option)
            for key in _PROFILE_OPTION_DETAIL_KEYS:
                value = translated_option.get(key)
                if isinstance(value, str):
                    translated_option[key] = QCoreApplication.translate("ProjectSettingsPane", value)
            translated_options.append(translated_option)
        return translated_options
