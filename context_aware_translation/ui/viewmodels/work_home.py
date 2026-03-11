from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = (
    "Import documents here, review project-wide progress, and open the next "
    "document tool directly from the table."
)


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
        self._selected_import_type = ""

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

    def set_context(self, summary: str, blocker_text: str) -> None:
        self._context_summary = summary
        self._context_blocker_text = blocker_text
        self._emit_content_changed()

    def set_setup(self, message: str, action_label: str) -> None:
        self._setup_message = message
        self._setup_action_label = action_label
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
        self._import_message_kind = "error" if is_error else "success"
        self._can_import = can_import
        resolved_selected = selected_import_type or ""
        self._selected_import_type = resolved_selected
        self._import_type_options = [
            {
                "documentType": document_type,
                "label": label,
                "selected": document_type == resolved_selected,
            }
            for document_type, label in options
        ]
        self._emit_content_changed()

    def select_import_type(self, document_type: str) -> None:
        normalized = document_type.strip()
        if normalized == self._selected_import_type:
            return
        self._selected_import_type = normalized
        self._import_type_options = [
            {**option, "selected": str(option["documentType"]) == normalized} for option in self._import_type_options
        ]
        self._emit_content_changed()

    def clear_import_message(self) -> None:
        self._import_message = ""
        self._import_message_kind = ""
        self._emit_content_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()

    def _emit_content_changed(self) -> None:
        self.content_changed.emit()
        self.mark_changed()
