from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_TIP_TEXT = "Translation review is scoped to this document only. Saving edits does not trigger hidden reruns."


class DocumentTranslationPaneViewModel(ViewModelBase):
    """QML-facing chrome state for the document translation pane."""

    labels_changed = Signal()
    chrome_state_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._progress_text = ""
        self._polish_enabled = True
        self._can_translate = False
        self._supports_batch = False
        self._can_batch = False

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        return QCoreApplication.translate("DocumentTranslationView", _TIP_TEXT)

    @Property(str, notify=labels_changed)
    def polish_label(self) -> str:
        return QCoreApplication.translate("DocumentTranslationView", "Enable polish pass")

    @Property(str, notify=labels_changed)
    def translate_label(self) -> str:
        return QCoreApplication.translate("DocumentTranslationView", "Translate")

    @Property(str, notify=labels_changed)
    def batch_label(self) -> str:
        return QCoreApplication.translate("DocumentTranslationView", "Submit Batch Task")

    @Property(str, notify=chrome_state_changed)
    def progress_text(self) -> str:
        return self._progress_text

    @Property(bool, notify=chrome_state_changed)
    def polish_enabled(self) -> bool:
        return self._polish_enabled

    @Property(bool, notify=chrome_state_changed)
    def can_translate(self) -> bool:
        return self._can_translate

    @Property(bool, notify=chrome_state_changed)
    def supports_batch(self) -> bool:
        return self._supports_batch

    @Property(bool, notify=chrome_state_changed)
    def can_batch(self) -> bool:
        return self._can_batch

    def apply_state(
        self,
        *,
        progress_text: str,
        polish_enabled: bool,
        can_translate: bool,
        supports_batch: bool,
        can_batch: bool,
    ) -> None:
        next_state = (progress_text, polish_enabled, can_translate, supports_batch, can_batch)
        current_state = (
            self._progress_text,
            self._polish_enabled,
            self._can_translate,
            self._supports_batch,
            self._can_batch,
        )
        if next_state == current_state:
            return
        (
            self._progress_text,
            self._polish_enabled,
            self._can_translate,
            self._supports_batch,
            self._can_batch,
        ) = next_state
        self.chrome_state_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()
