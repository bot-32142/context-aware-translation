from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import SurfaceStatus, UserMessageSeverity
from context_aware_translation.application.contracts.document import (
    DocumentTranslationState,
    RetranslateRequest,
    SaveTranslationRequest,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.utils import create_tip_label

_STATUS_TEXT: dict[SurfaceStatus, str] = {
    SurfaceStatus.READY: "Ready",
    SurfaceStatus.RUNNING: "Running",
    SurfaceStatus.BLOCKED: "Blocked",
    SurfaceStatus.FAILED: "Failed",
    SurfaceStatus.DONE: "Done",
    SurfaceStatus.CANCELLED: "Cancelled",
}

_STATUS_ICON: dict[SurfaceStatus, str] = {
    SurfaceStatus.READY: "○",
    SurfaceStatus.RUNNING: "…",
    SurfaceStatus.BLOCKED: "–",
    SurfaceStatus.FAILED: "!",
    SurfaceStatus.DONE: "✓",
    SurfaceStatus.CANCELLED: "–",
}


class DocumentTranslationView(QWidget):
    def __init__(
        self,
        service: DocumentService,
        project_id: str,
        document_id: int,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._project_id = project_id
        self._document_id = document_id
        self._state: DocumentTranslationState | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tip_label = create_tip_label(
            self.tr("Translation review is scoped to this document only. Saving edits does not trigger hidden reruns."),
        )
        layout.addWidget(self.tip_label)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #666666;")
        layout.addWidget(self.progress_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(self.tr("Units")))
        self.unit_list = QListWidget()
        self.unit_list.currentRowChanged.connect(self._on_unit_selected)
        left_layout.addWidget(self.unit_list)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.selection_label = QLabel(self.tr("No unit selected"))
        self.selection_label.setStyleSheet("font-weight: 600;")
        right_layout.addWidget(self.selection_label)

        self.blocker_label = create_tip_label("")
        self.blocker_label.hide()
        right_layout.addWidget(self.blocker_label)

        self.source_label = QLabel(self.tr("Source"))
        self.source_label.setStyleSheet("font-weight: 600;")
        right_layout.addWidget(self.source_label)

        self.source_text = QTextEdit()
        self.source_text.setReadOnly(True)
        self.source_text.setMaximumHeight(180)
        right_layout.addWidget(self.source_text)

        self.translation_label = QLabel(self.tr("Translation"))
        self.translation_label.setStyleSheet("font-weight: 600;")
        right_layout.addWidget(self.translation_label)

        self.translation_text = QTextEdit()
        right_layout.addWidget(self.translation_text, 1)

        self.line_hint = QLabel()
        self.line_hint.setStyleSheet("color: #666666;")
        self.line_hint.hide()
        right_layout.addWidget(self.line_hint)

        button_row = QHBoxLayout()
        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.clicked.connect(self._save_current_unit)
        button_row.addWidget(self.save_button)

        self.retranslate_button = QPushButton(self.tr("Retranslate"))
        self.retranslate_button.clicked.connect(self._retranslate_current_unit)
        button_row.addWidget(self.retranslate_button)
        button_row.addStretch()
        right_layout.addLayout(button_row)

        splitter.addWidget(right_panel)
        splitter.setSizes([260, 740])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        previous_unit_id = self._selected_unit_id()
        self._apply_state(self._service.get_translation(self._project_id, self._document_id), previous_unit_id=previous_unit_id)

    def get_running_operations(self) -> list[str]:
        if self._state is None or self._state.active_task_id is None:
            return []
        return [self._state.active_task_id]

    def _apply_state(self, state: DocumentTranslationState, *, previous_unit_id: str | None) -> None:
        self._state = state
        self.progress_label.setText(self._progress_text(state))
        self.unit_list.blockSignals(True)
        self.unit_list.clear()
        selected_row = 0
        target_unit_id = previous_unit_id or state.current_unit_id
        for index, unit in enumerate(state.units):
            item = QListWidgetItem(self._row_text(unit))
            item.setData(Qt.ItemDataRole.UserRole, unit.unit_id)
            item.setToolTip(unit.blocker.message if unit.blocker is not None else "")
            self.unit_list.addItem(item)
            if target_unit_id is not None and unit.unit_id == target_unit_id:
                selected_row = index
        self.unit_list.blockSignals(False)
        if state.units:
            self.unit_list.setCurrentRow(selected_row)
            self._render_selected_unit(state.units[selected_row])
        else:
            self._render_selected_unit(None)

    def _on_unit_selected(self, row: int) -> None:
        if self._state is None or row < 0 or row >= len(self._state.units):
            self._render_selected_unit(None)
            return
        self._render_selected_unit(self._state.units[row])

    def _render_selected_unit(self, unit: TranslationUnitState | None) -> None:
        if unit is None:
            self.selection_label.setText(self.tr("No unit selected"))
            self.blocker_label.hide()
            self.source_text.clear()
            self.translation_text.clear()
            self.translation_text.setReadOnly(True)
            self.line_hint.hide()
            self.save_button.setEnabled(False)
            self.retranslate_button.setEnabled(False)
            return

        self.selection_label.setText(f"{unit.label} · {self.tr(_STATUS_TEXT[unit.status])}")
        self.source_text.setPlainText(unit.source_text or "")
        self.translation_text.setPlainText(unit.translated_text or "")
        self.translation_text.setReadOnly(not unit.actions.can_save)
        self.save_button.setEnabled(unit.actions.can_save)
        self.retranslate_button.setEnabled(unit.actions.can_retranslate)
        self.save_button.setToolTip(unit.actions.save_blocker.message if unit.actions.save_blocker is not None else "")
        self.retranslate_button.setToolTip(
            unit.actions.retranslate_blocker.message if unit.actions.retranslate_blocker is not None else ""
        )

        blocker_text = unit.blocker.message if unit.blocker is not None else ""
        self.blocker_label.setText(blocker_text)
        self.blocker_label.setVisible(bool(blocker_text))

        if unit.unit_kind is TranslationUnitKind.CHUNK and unit.line_count and unit.line_count > 0:
            self.line_hint.setText(
                self.tr("Line count must stay at %1.").replace("%1", str(unit.line_count))
            )
            self.line_hint.show()
        else:
            self.line_hint.hide()

    def _selected_unit(self) -> TranslationUnitState | None:
        if self._state is None:
            return None
        row = self.unit_list.currentRow()
        if row < 0 or row >= len(self._state.units):
            return None
        return self._state.units[row]

    def _selected_unit_id(self) -> str | None:
        unit = self._selected_unit()
        return unit.unit_id if unit is not None else None

    def _save_current_unit(self) -> None:
        unit = self._selected_unit()
        if unit is None:
            return
        try:
            state = self._service.save_translation(
                SaveTranslationRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    unit_id=unit.unit_id,
                    translated_text=self.translation_text.toPlainText(),
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.warning(self, self.tr("Save Unavailable"), exc.payload.message)
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Save Failed"), exc.payload.message)
            self.refresh()
            return
        self._apply_state(state, previous_unit_id=unit.unit_id)
        self._set_message(UserMessageSeverity.SUCCESS, self.tr("Translation saved."))

    def _retranslate_current_unit(self) -> None:
        unit = self._selected_unit()
        if unit is None:
            return
        target_label = self.tr("page") if unit.unit_kind is TranslationUnitKind.PAGE else self.tr("chunk")
        reply = QMessageBox.question(
            self,
            self.tr("Retranslate"),
            self.tr("Retranslate this %1? LLM API costs will be incurred.").replace("%1", target_label),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            command = self._service.retranslate(
                RetranslateRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    unit_id=unit.unit_id,
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.information(self, self.tr("Retranslate Unavailable"), exc.payload.message)
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Retranslate Failed"), exc.payload.message)
            self.refresh()
            return
        self.refresh()
        if command.message is not None:
            self._set_message(command.message.severity, command.message.text)
        else:
            self._set_message(UserMessageSeverity.INFO, self.tr("Retranslate queued."))

    def _set_message(self, severity: UserMessageSeverity, text: str) -> None:
        color = {
            UserMessageSeverity.SUCCESS: "#15803d",
            UserMessageSeverity.WARNING: "#b45309",
            UserMessageSeverity.ERROR: "#b91c1c",
        }.get(severity, "#2563eb")
        self.progress_label.setStyleSheet(f"color: {color};")
        self.progress_label.setText(text)

    def _row_text(self, unit: TranslationUnitState) -> str:
        return f"{_STATUS_ICON[unit.status]} {unit.label}"

    def _progress_text(self, state: DocumentTranslationState) -> str:
        parts: list[str] = []
        if state.progress is not None and state.progress.total is not None and state.progress.current is not None:
            parts.append(
                self.tr("Progress: %1/%2").replace("%1", str(state.progress.current)).replace("%2", str(state.progress.total))
            )
        elif state.progress is not None and state.progress.label:
            parts.append(state.progress.label)
        if state.active_task_id is not None:
            parts.append(self.tr("Active task: %1").replace("%1", state.active_task_id))
        return " | ".join(parts)


__all__ = ["DocumentTranslationView"]
