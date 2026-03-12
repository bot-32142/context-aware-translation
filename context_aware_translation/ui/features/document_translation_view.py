from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    RunDocumentTranslationRequest,
    SaveTranslationRequest,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.document_translation_pane import DocumentTranslationPaneViewModel

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
        self.viewmodel = DocumentTranslationPaneViewModel(self)
        self._state: DocumentTranslationState | None = None
        self._find_pos = 0
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chrome_host = QmlChromeHost(
            "document/translation/DocumentTranslationPaneChrome.qml",
            context_objects={"translationPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)
        self.tip_label = create_tip_label(
            self.tr("Translation review is scoped to this document only. Saving edits does not trigger hidden reruns."),
        )
        self.tip_label.hide()
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #666666;")
        self.progress_label.hide()

        self.enable_polish_cb = QCheckBox(self.tr("Enable polish pass"), self)
        self.enable_polish_cb.setChecked(True)
        self.enable_polish_cb.toggled.connect(self.refresh)
        self.enable_polish_cb.hide()
        self.translate_button = QPushButton(self.tr("Translate"), self)
        self.translate_button.clicked.connect(self._translate_document)
        self.translate_button.hide()
        self.batch_translate_button = QPushButton(self.tr("Submit Batch Task"), self)
        self.batch_translate_button.clicked.connect(self._submit_batch_translation)
        self.batch_translate_button.hide()

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

        find_replace_layout = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText(self.tr("Find..."))
        self.find_input.textChanged.connect(self._on_find_text_changed)
        self.find_input.returnPressed.connect(self._find_next)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText(self.tr("Replace with..."))
        self.find_next_button = QPushButton(self.tr("Find Next"))
        self.find_next_button.clicked.connect(self._find_next)
        self.replace_button = QPushButton(self.tr("Replace"))
        self.replace_button.clicked.connect(self._replace_current)
        self.replace_all_button = QPushButton(self.tr("Replace All"))
        self.replace_all_button.clicked.connect(self._replace_all)
        find_replace_layout.addWidget(self.find_input, 1)
        find_replace_layout.addWidget(self.replace_input, 1)
        find_replace_layout.addWidget(self.find_next_button)
        find_replace_layout.addWidget(self.replace_button)
        find_replace_layout.addWidget(self.replace_all_button)
        right_layout.addLayout(find_replace_layout)

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
        self.previous_button = QPushButton("\u2190 " + self.tr("Previous"))
        self.previous_button.clicked.connect(self._go_previous_unit)
        button_row.addWidget(self.previous_button)
        self.next_button = QPushButton(self.tr("Next") + " \u2192")
        self.next_button.clicked.connect(self._go_next_unit)
        button_row.addWidget(self.next_button)
        button_row.addStretch()
        right_layout.addLayout(button_row)

        splitter.addWidget(right_panel)
        splitter.setSizes([260, 740])
        layout.addWidget(splitter, 1)
        self._connect_qml_signals()
        self._sync_chrome_state()

    def refresh(self) -> None:
        previous_unit_id = self._selected_unit_id()
        self._apply_state(
            self._service.get_translation(
                self._project_id,
                self._document_id,
                enable_polish=self.enable_polish_cb.isChecked(),
            ),
            previous_unit_id=previous_unit_id,
        )
        self._sync_chrome_state()

    def get_running_operations(self) -> list[str]:
        if self._state is None or self._state.active_task_id is None:
            return []
        return [self._state.active_task_id]

    def _apply_state(self, state: DocumentTranslationState, *, previous_unit_id: str | None) -> None:
        self._state = state
        self.progress_label.setText(self._progress_text(state))
        self.translate_button.setEnabled(state.run_action.enabled)
        self.translate_button.setToolTip(state.run_action.blocker.message if state.run_action.blocker else "")
        self.batch_translate_button.setVisible(state.supports_batch)
        self.batch_translate_button.setEnabled(state.batch_action.enabled)
        self.batch_translate_button.setToolTip(state.batch_action.blocker.message if state.batch_action.blocker else "")
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
        self._sync_chrome_state()

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
            self._clear_find_highlight()
            self.line_hint.hide()
            self.save_button.setEnabled(False)
            self.retranslate_button.setEnabled(False)
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self._sync_chrome_state()
            return

        self._find_pos = 0
        self._clear_find_highlight()
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
            self.line_hint.setText(self.tr("Line count must stay at %1.").replace("%1", str(unit.line_count)))
            self.line_hint.show()
        else:
            self.line_hint.hide()
        self._update_navigation_buttons()
        self._sync_chrome_state()

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

    def _go_previous_unit(self) -> None:
        row = self.unit_list.currentRow()
        if row > 0:
            self.unit_list.setCurrentRow(row - 1)

    def _go_next_unit(self) -> None:
        row = self.unit_list.currentRow()
        if self._state is None:
            return
        if row < len(self._state.units) - 1:
            self.unit_list.setCurrentRow(row + 1)

    def _update_navigation_buttons(self) -> None:
        row = self.unit_list.currentRow()
        total = len(self._state.units) if self._state is not None else 0
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(0 <= row < total - 1)

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

    def _translate_document(self) -> None:
        try:
            command = self._service.run_translation(
                RunDocumentTranslationRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    enable_polish=self.enable_polish_cb.isChecked(),
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.information(self, self.tr("Translate Unavailable"), exc.payload.message)
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Translate Failed"), exc.payload.message)
            self.refresh()
            return
        self.refresh()
        if command.message is not None:
            self._set_message(command.message.severity, command.message.text)
        else:
            self._set_message(UserMessageSeverity.INFO, self.tr("Translation queued."))

    def _submit_batch_translation(self) -> None:
        try:
            command = self._service.run_translation(
                RunDocumentTranslationRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    enable_polish=self.enable_polish_cb.isChecked(),
                    batch=True,
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.information(self, self.tr("Batch Translation Unavailable"), exc.payload.message)
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Batch Translation Failed"), exc.payload.message)
            self.refresh()
            return
        self.refresh()
        if command.message is not None:
            self._set_message(command.message.severity, command.message.text)
        else:
            self._set_message(UserMessageSeverity.INFO, self.tr("Async batch translation queued."))

    def _set_message(self, severity: UserMessageSeverity, text: str) -> None:
        color = {
            UserMessageSeverity.SUCCESS: "#15803d",
            UserMessageSeverity.WARNING: "#b45309",
            UserMessageSeverity.ERROR: "#b91c1c",
        }.get(severity, "#2563eb")
        self.progress_label.setStyleSheet(f"color: {color};")
        self.progress_label.setText(text)
        self._sync_chrome_state()

    def _row_text(self, unit: TranslationUnitState) -> str:
        return f"{_STATUS_ICON[unit.status]} {unit.label}"

    def _progress_text(self, state: DocumentTranslationState) -> str:
        parts: list[str] = []
        if state.progress is not None and state.progress.total is not None and state.progress.current is not None:
            parts.append(
                self.tr("Progress: %1/%2")
                .replace("%1", str(state.progress.current))
                .replace("%2", str(state.progress.total))
            )
        elif state.progress is not None and state.progress.label:
            parts.append(state.progress.label)
        if state.active_task_id is not None:
            parts.append(self.tr("Active task: %1").replace("%1", state.active_task_id))
        return " | ".join(parts)

    def _on_find_text_changed(self, _text: str) -> None:
        self._find_pos = 0
        self._clear_find_highlight()

    def _find_next(self) -> None:
        search_text = self.find_input.text()
        if not search_text:
            return
        self._clear_find_highlight()
        text = self.translation_text.toPlainText()
        start = self._find_pos
        pos = text.find(search_text, start)
        if pos < 0 and start > 0:
            pos = text.find(search_text, 0)
        if pos < 0:
            return
        self._find_pos = pos + len(search_text)
        cursor = self.translation_text.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(search_text), QTextCursor.MoveMode.KeepAnchor)
        self.translation_text.setTextCursor(cursor)
        extra = QTextEdit.ExtraSelection()
        extra.cursor = cursor
        fmt = QTextCharFormat()
        fmt.setBackground(Qt.GlobalColor.yellow)
        extra.format = fmt
        self.translation_text.setExtraSelections([extra])

    def _replace_current(self) -> None:
        search_text = self.find_input.text()
        if not search_text:
            return
        cursor = self.translation_text.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == search_text:
            cursor.insertText(self.replace_input.text())
            self._find_pos = cursor.position()
        self._find_next()

    def _replace_all(self) -> None:
        search_text = self.find_input.text()
        if not search_text:
            return
        self.translation_text.setPlainText(
            self.translation_text.toPlainText().replace(search_text, self.replace_input.text())
        )
        self._find_pos = 0
        self._clear_find_highlight()

    def _clear_find_highlight(self) -> None:
        self.translation_text.setExtraSelections([])

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(
            self.tr("Translation review is scoped to this document only. Saving edits does not trigger hidden reruns."),
        )
        self.enable_polish_cb.setText(self.tr("Enable polish pass"))
        self.translate_button.setText(self.tr("Translate"))
        self.batch_translate_button.setText(self.tr("Submit Batch Task"))
        self.source_label.setText(self.tr("Source"))
        self.translation_label.setText(self.tr("Translation"))
        self.find_input.setPlaceholderText(self.tr("Find..."))
        self.replace_input.setPlaceholderText(self.tr("Replace with..."))
        self.find_next_button.setText(self.tr("Find Next"))
        self.replace_button.setText(self.tr("Replace"))
        self.replace_all_button.setText(self.tr("Replace All"))
        self.save_button.setText(self.tr("Save"))
        self.retranslate_button.setText(self.tr("Retranslate"))
        self.previous_button.setText("\u2190 " + self.tr("Previous"))
        self.next_button.setText(self.tr("Next") + " \u2192")
        self.viewmodel.retranslate()
        self._sync_chrome_state()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.polishToggled.connect(self._on_polish_toggled)
        root.translateRequested.connect(self._translate_document)
        root.batchRequested.connect(self._submit_batch_translation)

    def _on_polish_toggled(self, enabled: bool) -> None:
        self.enable_polish_cb.setChecked(enabled)
        self._sync_chrome_state()

    def _sync_chrome_state(self) -> None:
        self.viewmodel.apply_state(
            progress_text=self.progress_label.text().strip(),
            polish_enabled=self.enable_polish_cb.isChecked(),
            can_translate=self.translate_button.isEnabled(),
            supports_batch=not self.batch_translate_button.isHidden(),
            can_batch=self.batch_translate_button.isEnabled(),
        )


__all__ = ["DocumentTranslationView"]
