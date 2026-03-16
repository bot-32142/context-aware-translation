from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, QT_TRANSLATE_NOOP, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = QT_TRANSLATE_NOOP(
    "DocumentImagesView",
    "Image actions are explicit. Review one image, reinsert pending images, or rerun everything for this document.",
)


class DocumentImagesPaneViewModel(ViewModelBase):
    """QML-facing chrome state for the document images pane."""

    labels_changed = Signal()
    chrome_state_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._blocker_text = ""
        self._blocker_action_label = ""
        self._page_label = ""
        self._page_input_text = "1"
        self._status_text = ""
        self._status_color = "#5f5447"
        self._toggle_label = ""
        self._message_text = ""
        self._progress_text = ""
        self._has_blocker = False
        self._has_blocker_action = False
        self._toggle_enabled = False
        self._first_enabled = False
        self._previous_enabled = False
        self._next_enabled = False
        self._last_enabled = False
        self._go_enabled = False
        self._run_selected_enabled = False
        self._run_pending_enabled = False
        self._force_all_enabled = False
        self._toggle_tooltip = ""
        self._run_selected_tooltip = ""
        self._run_pending_tooltip = ""
        self._force_all_tooltip = ""
        self._progress_visible = False
        self._progress_can_cancel = False
        self._empty_visible = True

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", _TIP_TEXT)

    @Property(str, notify=labels_changed)
    def first_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "|<")

    @Property(str, notify=labels_changed)
    def previous_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "<")

    @Property(str, notify=labels_changed)
    def next_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", ">")

    @Property(str, notify=labels_changed)
    def last_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", ">|")

    @Property(str, notify=labels_changed)
    def go_to_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "Go to:")

    @Property(str, notify=labels_changed)
    def go_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "Go")

    @Property(str, notify=labels_changed)
    def cancel_label(self) -> str:
        return QCoreApplication.translate("QueueDrawerView", "Cancel")

    @Property(str, notify=labels_changed)
    def run_selected_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "Reembed This Image")

    @Property(str, notify=labels_changed)
    def run_pending_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "Reembed Pending")

    @Property(str, notify=labels_changed)
    def force_all_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "Force Reembed All")

    @Property(str, notify=chrome_state_changed)
    def blocker_text(self) -> str:
        return self._blocker_text

    @Property(bool, notify=chrome_state_changed)
    def has_blocker(self) -> bool:
        return self._has_blocker

    @Property(bool, notify=chrome_state_changed)
    def blocker_action_visible(self) -> bool:
        return self._has_blocker_action

    @Property(str, notify=chrome_state_changed)
    def blocker_action_label(self) -> str:
        return self._blocker_action_label

    @Property(str, notify=chrome_state_changed)
    def page_label(self) -> str:
        return self._page_label

    @Property(str, notify=chrome_state_changed)
    def page_input_text(self) -> str:
        return self._page_input_text

    @Property(str, notify=chrome_state_changed)
    def status_text(self) -> str:
        return self._status_text

    @Property(str, notify=chrome_state_changed)
    def status_color(self) -> str:
        return self._status_color

    @Property(str, notify=chrome_state_changed)
    def toggle_label(self) -> str:
        return self._toggle_label

    @Property(bool, notify=chrome_state_changed)
    def toggle_enabled(self) -> bool:
        return self._toggle_enabled

    @Property(bool, notify=chrome_state_changed)
    def first_enabled(self) -> bool:
        return self._first_enabled

    @Property(bool, notify=chrome_state_changed)
    def previous_enabled(self) -> bool:
        return self._previous_enabled

    @Property(bool, notify=chrome_state_changed)
    def next_enabled(self) -> bool:
        return self._next_enabled

    @Property(bool, notify=chrome_state_changed)
    def last_enabled(self) -> bool:
        return self._last_enabled

    @Property(bool, notify=chrome_state_changed)
    def go_enabled(self) -> bool:
        return self._go_enabled

    @Property(bool, notify=chrome_state_changed)
    def run_selected_enabled(self) -> bool:
        return self._run_selected_enabled

    @Property(bool, notify=chrome_state_changed)
    def run_pending_enabled(self) -> bool:
        return self._run_pending_enabled

    @Property(bool, notify=chrome_state_changed)
    def force_all_enabled(self) -> bool:
        return self._force_all_enabled

    @Property(str, notify=chrome_state_changed)
    def toggle_tooltip(self) -> str:
        return self._toggle_tooltip

    @Property(str, notify=chrome_state_changed)
    def run_selected_tooltip(self) -> str:
        return self._run_selected_tooltip

    @Property(str, notify=chrome_state_changed)
    def run_pending_tooltip(self) -> str:
        return self._run_pending_tooltip

    @Property(str, notify=chrome_state_changed)
    def force_all_tooltip(self) -> str:
        return self._force_all_tooltip

    @Property(str, notify=chrome_state_changed)
    def message_text(self) -> str:
        return self._message_text

    @Property(bool, notify=chrome_state_changed)
    def has_message(self) -> bool:
        return bool(self._message_text)

    @Property(bool, notify=chrome_state_changed)
    def message_visible(self) -> bool:
        return bool(self._message_text)

    @Property(bool, notify=chrome_state_changed)
    def progress_visible(self) -> bool:
        return self._progress_visible

    @Property(str, notify=chrome_state_changed)
    def progress_text(self) -> str:
        return self._progress_text

    @Property(bool, notify=chrome_state_changed)
    def progress_can_cancel(self) -> bool:
        return self._progress_can_cancel

    @Property(bool, notify=chrome_state_changed)
    def empty_visible(self) -> bool:
        return self._empty_visible

    @Property(str, notify=labels_changed)
    def empty_text(self) -> str:
        return QCoreApplication.translate(
            "DocumentImagesView", "No reembeddable images are available for this document."
        )

    def apply_state(
        self,
        *,
        blocker_text: str,
        has_blocker: bool,
        blocker_action_label: str,
        has_blocker_action: bool,
        page_label: str,
        page_input_text: str,
        status_text: str,
        status_color: str,
        toggle_label: str,
        toggle_enabled: bool,
        first_enabled: bool,
        previous_enabled: bool,
        next_enabled: bool,
        last_enabled: bool,
        go_enabled: bool,
        run_selected_enabled: bool,
        run_pending_enabled: bool,
        force_all_enabled: bool,
        toggle_tooltip: str = "",
        run_selected_tooltip: str = "",
        run_pending_tooltip: str = "",
        force_all_tooltip: str = "",
        message_text: str,
        progress_visible: bool,
        progress_text: str,
        progress_can_cancel: bool,
        empty_visible: bool,
    ) -> None:
        tooltip_state = (toggle_tooltip, run_selected_tooltip, run_pending_tooltip, force_all_tooltip)
        next_state = (
            blocker_text,
            has_blocker,
            blocker_action_label,
            has_blocker_action,
            page_label,
            page_input_text,
            status_text,
            status_color,
            toggle_label,
            toggle_enabled,
            first_enabled,
            previous_enabled,
            next_enabled,
            last_enabled,
            go_enabled,
            run_selected_enabled,
            run_pending_enabled,
            force_all_enabled,
            message_text,
            progress_visible,
            progress_text,
            progress_can_cancel,
            empty_visible,
        )
        current_state = (
            self._blocker_text,
            self._has_blocker,
            self._blocker_action_label,
            self._has_blocker_action,
            self._page_label,
            self._page_input_text,
            self._status_text,
            self._status_color,
            self._toggle_label,
            self._toggle_enabled,
            self._first_enabled,
            self._previous_enabled,
            self._next_enabled,
            self._last_enabled,
            self._go_enabled,
            self._run_selected_enabled,
            self._run_pending_enabled,
            self._force_all_enabled,
            self._message_text,
            self._progress_visible,
            self._progress_text,
            self._progress_can_cancel,
            self._empty_visible,
        )
        if next_state == current_state and tooltip_state == (
            self._toggle_tooltip,
            self._run_selected_tooltip,
            self._run_pending_tooltip,
            self._force_all_tooltip,
        ):
            return
        (
            self._blocker_text,
            self._has_blocker,
            self._blocker_action_label,
            self._has_blocker_action,
            self._page_label,
            self._page_input_text,
            self._status_text,
            self._status_color,
            self._toggle_label,
            self._toggle_enabled,
            self._first_enabled,
            self._previous_enabled,
            self._next_enabled,
            self._last_enabled,
            self._go_enabled,
            self._run_selected_enabled,
            self._run_pending_enabled,
            self._force_all_enabled,
            self._message_text,
            self._progress_visible,
            self._progress_text,
            self._progress_can_cancel,
            self._empty_visible,
        ) = next_state
        self._toggle_tooltip = toggle_tooltip
        self._run_selected_tooltip = run_selected_tooltip
        self._run_pending_tooltip = run_pending_tooltip
        self._force_all_tooltip = force_all_tooltip
        self.chrome_state_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()
