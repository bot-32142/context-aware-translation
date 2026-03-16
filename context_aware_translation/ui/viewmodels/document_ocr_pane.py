from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.application.contracts.common import SurfaceStatus
from context_aware_translation.ui.viewmodels.base import ViewModelBase


@dataclass(frozen=True, slots=True)
class _OcrChromeState:
    has_pages: bool = False
    page_number: int = 0
    page_count: int = 0
    page_status: SurfaceStatus | None = None
    page_input_value: int = 1
    first_enabled: bool = False
    previous_enabled: bool = False
    next_enabled: bool = False
    last_enabled: bool = False
    go_enabled: bool = False
    run_current_enabled: bool = False
    run_pending_enabled: bool = False
    save_enabled: bool = False
    message_text: str = ""
    progress_visible: bool = False
    progress_text: str = ""
    progress_can_cancel: bool = False
    empty_visible: bool = True


class DocumentOcrPaneViewModel(ViewModelBase):
    """QML-facing chrome state for the OCR pane."""

    chrome_state_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._state = _OcrChromeState()
        self._run_current_tooltip = ""
        self._run_pending_tooltip = ""
        self._save_tooltip = ""

    @Property(str, notify=chrome_state_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate(
            "DocumentOCRTab",
            "OCR applies only to the current document. Saving OCR does not rerun later steps.",
        )

    @Property(str, notify=chrome_state_changed)
    def page_label(self) -> str:
        return (
            QCoreApplication.translate("DocumentOCRTab", "Page %1 of %2")
            .replace("%1", str(self._state.page_number))
            .replace("%2", str(self._state.page_count))
        )

    @Property(str, notify=chrome_state_changed)
    def page_status_text(self) -> str:
        if self._state.page_status is SurfaceStatus.DONE:
            return QCoreApplication.translate("DocumentOCRTab", "OCR Done")
        if self._state.page_status is SurfaceStatus.RUNNING:
            return QCoreApplication.translate("DocumentOCRTab", "OCR Running")
        if self._state.page_status is SurfaceStatus.FAILED:
            return QCoreApplication.translate("DocumentOCRTab", "OCR Failed")
        return QCoreApplication.translate("DocumentOCRTab", "Pending OCR")

    @Property(str, notify=chrome_state_changed)
    def page_status_color(self) -> str:
        if self._state.page_status is SurfaceStatus.DONE:
            return "#15803d"
        if self._state.page_status is SurfaceStatus.RUNNING:
            return "#2563eb"
        if self._state.page_status is SurfaceStatus.FAILED:
            return "#d92d20"
        return "#b54708"

    @Property(str, notify=chrome_state_changed)
    def first_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "|<")

    @Property(str, notify=chrome_state_changed)
    def previous_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "<")

    @Property(str, notify=chrome_state_changed)
    def next_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", ">")

    @Property(str, notify=chrome_state_changed)
    def last_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", ">|")

    @Property(str, notify=chrome_state_changed)
    def go_to_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "Go to:")

    @Property(str, notify=chrome_state_changed)
    def go_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "Go")

    @Property(str, notify=chrome_state_changed)
    def run_current_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "(Re)run OCR (Current Page)")

    @Property(str, notify=chrome_state_changed)
    def run_pending_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "Run OCR for Pending Pages")

    @Property(str, notify=chrome_state_changed)
    def save_label(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "Save")

    @Property(str, notify=chrome_state_changed)
    def empty_text(self) -> str:
        return QCoreApplication.translate("DocumentOCRTab", "No image pages are available for OCR in this document.")

    @Property(str, notify=chrome_state_changed)
    def progress_label(self) -> str:
        return self._state.progress_text or QCoreApplication.translate("DocumentOCRTab", "OCR running...")

    @Property(str, notify=chrome_state_changed)
    def cancel_label(self) -> str:
        return QCoreApplication.translate("QueueDrawerView", "Cancel")

    @Property(str, notify=chrome_state_changed)
    def message_text(self) -> str:
        return self._state.message_text

    @Property(bool, notify=chrome_state_changed)
    def message_visible(self) -> bool:
        return bool(self._state.message_text)

    @Property(str, notify=chrome_state_changed)
    def page_input_text(self) -> str:
        return str(self._state.page_input_value)

    @Property(bool, notify=chrome_state_changed)
    def has_pages(self) -> bool:
        return self._state.has_pages

    @Property(bool, notify=chrome_state_changed)
    def first_enabled(self) -> bool:
        return self._state.first_enabled

    @Property(bool, notify=chrome_state_changed)
    def previous_enabled(self) -> bool:
        return self._state.previous_enabled

    @Property(bool, notify=chrome_state_changed)
    def next_enabled(self) -> bool:
        return self._state.next_enabled

    @Property(bool, notify=chrome_state_changed)
    def last_enabled(self) -> bool:
        return self._state.last_enabled

    @Property(bool, notify=chrome_state_changed)
    def go_enabled(self) -> bool:
        return self._state.go_enabled

    @Property(bool, notify=chrome_state_changed)
    def run_current_enabled(self) -> bool:
        return self._state.run_current_enabled

    @Property(bool, notify=chrome_state_changed)
    def run_pending_enabled(self) -> bool:
        return self._state.run_pending_enabled

    @Property(bool, notify=chrome_state_changed)
    def save_enabled(self) -> bool:
        return self._state.save_enabled

    @Property(str, notify=chrome_state_changed)
    def run_current_tooltip(self) -> str:
        return self._run_current_tooltip

    @Property(str, notify=chrome_state_changed)
    def run_pending_tooltip(self) -> str:
        return self._run_pending_tooltip

    @Property(str, notify=chrome_state_changed)
    def save_tooltip(self) -> str:
        return self._save_tooltip

    @Property(bool, notify=chrome_state_changed)
    def progress_visible(self) -> bool:
        return self._state.progress_visible

    @Property(bool, notify=chrome_state_changed)
    def progress_can_cancel(self) -> bool:
        return self._state.progress_can_cancel

    @Property(bool, notify=chrome_state_changed)
    def empty_visible(self) -> bool:
        return self._state.empty_visible

    def apply_values(
        self,
        *,
        has_pages: bool,
        page_number: int,
        page_count: int,
        page_status: SurfaceStatus | None,
        page_input_value: int,
        first_enabled: bool,
        previous_enabled: bool,
        next_enabled: bool,
        last_enabled: bool,
        go_enabled: bool,
        run_current_enabled: bool,
        run_pending_enabled: bool,
        save_enabled: bool,
        run_current_tooltip: str = "",
        run_pending_tooltip: str = "",
        save_tooltip: str = "",
        message_text: str,
        progress_visible: bool,
        progress_text: str,
        progress_can_cancel: bool,
        empty_visible: bool,
    ) -> None:
        tooltip_state = (run_current_tooltip, run_pending_tooltip, save_tooltip)
        state = _OcrChromeState(
            has_pages=has_pages,
            page_number=page_number,
            page_count=page_count,
            page_status=page_status,
            page_input_value=page_input_value,
            first_enabled=first_enabled,
            previous_enabled=previous_enabled,
            next_enabled=next_enabled,
            last_enabled=last_enabled,
            go_enabled=go_enabled,
            run_current_enabled=run_current_enabled,
            run_pending_enabled=run_pending_enabled,
            save_enabled=save_enabled,
            message_text=message_text,
            progress_visible=progress_visible,
            progress_text=progress_text,
            progress_can_cancel=progress_can_cancel,
            empty_visible=empty_visible,
        )
        if state == self._state and tooltip_state == (
            self._run_current_tooltip,
            self._run_pending_tooltip,
            self._save_tooltip,
        ):
            return
        self._state = state
        self._run_current_tooltip = run_current_tooltip
        self._run_pending_tooltip = run_pending_tooltip
        self._save_tooltip = save_tooltip
        self.chrome_state_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.chrome_state_changed.emit()
        self.mark_changed()
