from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, QT_TRANSLATE_NOOP, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = QT_TRANSLATE_NOOP(
    "WorkView",
    "Import documents here, review project-wide progress, and open the next document tool directly from the table.",
)
_IMPORT_MESSAGE_SUCCESS = "success"
_IMPORT_MESSAGE_ERROR = "error"


class WorkHomeViewModel(ViewModelBase):
    """QML-facing chrome state for the project work-home surface."""

    labels_changed = Signal()
    content_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._context_summary = ""
        self._context_blocker_text = ""
        self._setup_message = ""
        self._setup_action_label = ""
        self._import_summary = ""
        self._import_message = ""
        self._import_message_kind = ""
        self._can_import = False
        self._import_type_options: list[dict[str, object]] = []
        self._import_type_option_sources: list[tuple[str, str]] = []
        self._selected_import_type = ""
        self._select_files_tooltip = ""
        self._select_folder_tooltip = ""
        self._import_tooltip = ""
        self._setup_action_tooltip = ""

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate("WorkView", _TIP_TEXT)

    @Property(str, notify=labels_changed)
    def select_files_label(self) -> str:
        return QCoreApplication.translate("WorkView", "Select Files")

    @Property(str, notify=labels_changed)
    def select_folder_label(self) -> str:
        return QCoreApplication.translate("WorkView", "Select Folder")

    @Property(str, notify=labels_changed)
    def import_label(self) -> str:
        return QCoreApplication.translate("WorkView", "Import")

    @Property(str, notify=content_changed)
    def context_summary(self) -> str:
        return self._context_summary

    @Property(str, notify=content_changed)
    def context_blocker_text(self) -> str:
        return self._context_blocker_text

    @Property(bool, notify=content_changed)
    def has_context_blocker(self) -> bool:
        return bool(self._context_blocker_text)

    @Property(bool, notify=content_changed)
    def has_setup_blocker(self) -> bool:
        return bool(self._setup_message)

    @Property(str, notify=content_changed)
    def setup_message(self) -> str:
        return self._setup_message

    @Property(str, notify=content_changed)
    def setup_action_label(self) -> str:
        return self._setup_action_label

    @Property(str, notify=content_changed)
    def import_summary(self) -> str:
        return self._import_summary

    @Property(str, notify=content_changed)
    def import_message(self) -> str:
        return self._import_message

    @Property(bool, notify=content_changed)
    def has_import_message(self) -> bool:
        return bool(self._import_message)

    @Property(str, notify=content_changed)
    def import_message_kind(self) -> str:
        return self._import_message_kind

    @Property(bool, notify=content_changed)
    def can_import(self) -> bool:
        return self._can_import

    @Property("QVariantList", notify=content_changed)
    def import_type_options(self) -> list[dict[str, object]]:
        return self._import_type_options

    @Property(bool, notify=content_changed)
    def has_import_type_options(self) -> bool:
        return bool(self._import_type_options)

    @Property(str, notify=content_changed)
    def selected_import_type(self) -> str:
        return self._selected_import_type

    @Property(str, notify=content_changed)
    def select_files_tooltip(self) -> str:
        return self._select_files_tooltip

    @Property(str, notify=content_changed)
    def select_folder_tooltip(self) -> str:
        return self._select_folder_tooltip

    @Property(str, notify=content_changed)
    def import_tooltip(self) -> str:
        return self._import_tooltip

    @Property(str, notify=content_changed)
    def setup_action_tooltip(self) -> str:
        return self._setup_action_tooltip

    def set_context(self, summary: str, blocker_text: str) -> None:
        self._context_summary = summary
        self._context_blocker_text = blocker_text
        self._emit_content_changed()

    def set_setup(self, message: str, action_label: str) -> None:
        self._setup_message = message
        self._setup_action_label = action_label
        self._setup_action_tooltip = (
            QCoreApplication.translate("WorkView", "Open project setup to fix this blocker.") if action_label else ""
        )
        self._emit_content_changed()

    def clear_setup(self) -> None:
        self.set_setup("", "")

    def set_import_state(
        self,
        *,
        summary: str,
        message: str,
        is_error: bool,
        can_import: bool,
        options: list[tuple[str, str]],
        selected_import_type: str | None,
    ) -> None:
        self._import_summary = summary
        self._import_message = message
        self._import_message_kind = (
            _IMPORT_MESSAGE_ERROR if message and is_error else _IMPORT_MESSAGE_SUCCESS if message else ""
        )
        self._can_import = can_import
        resolved_selected = selected_import_type or ""
        self._selected_import_type = resolved_selected
        self._import_type_option_sources = list(options)
        self._import_type_options = self._build_import_type_options()
        self._select_files_tooltip = QCoreApplication.translate(
            "WorkView", "Choose one or more source files to import."
        )
        self._select_folder_tooltip = QCoreApplication.translate(
            "WorkView", "Choose a folder and import supported files from it."
        )
        self._import_tooltip = (
            QCoreApplication.translate("WorkView", "Import the selected files or folder into this project.")
            if can_import
            else QCoreApplication.translate("WorkView", "Select files or a folder before importing.")
        )
        self._emit_content_changed()

    def select_import_type(self, document_type: str) -> None:
        normalized = document_type.strip()
        if normalized == self._selected_import_type:
            return
        self._selected_import_type = normalized
        self._import_type_options = self._build_import_type_options()
        self._emit_content_changed()

    def clear_import_message(self) -> None:
        self._import_message = ""
        self._import_message_kind = ""
        self._emit_content_changed()

    def retranslate(self) -> None:
        self._import_type_options = self._build_import_type_options()
        self._select_files_tooltip = QCoreApplication.translate(
            "WorkView", "Choose one or more source files to import."
        )
        self._select_folder_tooltip = QCoreApplication.translate(
            "WorkView", "Choose a folder and import supported files from it."
        )
        self._import_tooltip = (
            QCoreApplication.translate("WorkView", "Import the selected files or folder into this project.")
            if self._can_import
            else QCoreApplication.translate("WorkView", "Select files or a folder before importing.")
        )
        self._setup_action_tooltip = (
            QCoreApplication.translate("WorkView", "Open project setup to fix this blocker.")
            if self._setup_action_label
            else ""
        )
        self.labels_changed.emit()
        self._emit_content_changed()

    def _translate_option_label(self, label: str) -> str:
        return QCoreApplication.translate("WorkView", label)

    def _build_import_type_options(self) -> list[dict[str, object]]:
        return [
            {
                "documentType": document_type,
                "label": self._translate_option_label(label),
                "selected": document_type == self._selected_import_type,
            }
            for document_type, label in self._import_type_option_sources
        ]

    def _emit_content_changed(self) -> None:
        self.content_changed.emit()
        self.mark_changed()
