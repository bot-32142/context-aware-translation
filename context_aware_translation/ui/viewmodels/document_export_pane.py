from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, QT_TRANSLATE_NOOP, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = QT_TRANSLATE_NOOP(
    "DocumentWorkspaceView",
    "Export applies only to the current document. You can also start export "
    "directly from the Work list when that row is exportable.",
)


class DocumentExportPaneViewModel(ViewModelBase):
    """QML-facing chrome state for the document export pane."""

    labels_changed = Signal()
    chrome_state_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._can_export = False
        self._result_text = ""
        self._export_tooltip = ""

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate("DocumentWorkspaceView", _TIP_TEXT)

    @Property(str, notify=labels_changed)
    def export_label(self) -> str:
        return QCoreApplication.translate("DocumentWorkspaceView", "Export This Document")

    @Property(bool, notify=chrome_state_changed)
    def can_export(self) -> bool:
        return self._can_export

    @Property(str, notify=chrome_state_changed)
    def result_text(self) -> str:
        return self._result_text

    @Property(bool, notify=chrome_state_changed)
    def has_result(self) -> bool:
        return bool(self._result_text)

    @Property(str, notify=chrome_state_changed)
    def export_tooltip(self) -> str:
        return self._export_tooltip

    def apply_state(self, *, can_export: bool, result_text: str, export_tooltip: str = "") -> None:
        if (
            can_export == self._can_export
            and result_text == self._result_text
            and export_tooltip == self._export_tooltip
        ):
            return
        self._can_export = can_export
        self._result_text = result_text
        self._export_tooltip = export_tooltip
        self.chrome_state_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()
