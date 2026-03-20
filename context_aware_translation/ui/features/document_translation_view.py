from __future__ import annotations

from bisect import bisect_right
from typing import Any, cast

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QKeySequence,
    QPainter,
    QShortcut,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
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
from context_aware_translation.ui.i18n import translate_backend_text, translate_progress_label
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.document_translation_pane import DocumentTranslationPaneViewModel
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone

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


class _TranslationUnitListDelegate(QStyledItemDelegate):
    _TEXT_COLOR = QColor("#2f251d")
    _HOVER_COLOR = QColor("#f4ecdf")
    _SELECTED_COLOR = QColor("#efe7da")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)

        row_rect = item_option.rect.adjusted(4, 2, -4, -2)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        if item_option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(self._SELECTED_COLOR)
            painter.drawRoundedRect(row_rect, 10, 10)
        elif item_option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(self._HOVER_COLOR)
            painter.drawRoundedRect(row_rect, 10, 10)
        painter.restore()

        item_option.state &= ~QStyle.StateFlag.State_Selected
        item_option.state &= ~QStyle.StateFlag.State_HasFocus
        item_option.palette.setColor(item_option.palette.ColorRole.Text, self._TEXT_COLOR)
        item_option.palette.setColor(item_option.palette.ColorRole.HighlightedText, self._TEXT_COLOR)
        item_option.rect = row_rect.adjusted(10, 0, -10, 0)
        style = item_option.widget.style() if item_option.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item_option, painter, item_option.widget)


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
        self._supports_batch = False
        self._progress_text_value = ""
        self._message_text_value = ""
        self._polish_enabled = True
        self._can_translate = False
        self._can_batch = False
        self._drafts_by_unit_id: dict[str, str] = {}
        self._suppressed_draft_unit_ids: set[str] = set()
        self._rendered_unit_id: str | None = None
        self._syncing_editor_scroll = False
        self._line_height_sync_pending = False
        self._source_block_tops: list[float] = []
        self._source_block_heights: list[float] = []
        self._translation_block_tops: list[float] = []
        self._translation_block_heights: list[float] = []
        self._shortcuts: list[QShortcut] = []
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

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(self.tr("Units")))
        self.unit_list = QListWidget()
        self.unit_list.setMouseTracking(True)
        self.unit_list.setSpacing(2)
        self.unit_list.setUniformItemSizes(True)
        self.unit_list.setItemDelegate(_TranslationUnitListDelegate(self.unit_list))
        self.unit_list.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
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

        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.splitterMoved.connect(lambda *_args: self._schedule_wrapped_line_sync())

        source_panel = QWidget()
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        self.source_label = QLabel(self.tr("Source"))
        self.source_label.setStyleSheet("font-weight: 600;")
        source_layout.addWidget(self.source_label)

        self.source_text = QTextEdit()
        self._configure_text_editor(self.source_text, read_only=True)
        source_layout.addWidget(self.source_text, 1)
        self.editor_splitter.addWidget(source_panel)

        translation_panel = QWidget()
        translation_layout = QVBoxLayout(translation_panel)
        translation_layout.setContentsMargins(0, 0, 0, 0)
        self.translation_label = QLabel(self.tr("Translation"))
        self.translation_label.setStyleSheet("font-weight: 600;")
        translation_layout.addWidget(self.translation_label)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText(self.tr("Find..."))
        self.find_input.textChanged.connect(self._on_find_text_changed)
        self.find_input.returnPressed.connect(self._find_next)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText(self.tr("Replace with..."))
        self.replace_input.returnPressed.connect(self._replace_current)
        self.find_next_button = QPushButton(self.tr("Find Next"))
        self.find_next_button.clicked.connect(self._find_next)
        self.show_replace_button = QPushButton(self.tr("Replace"))
        self.show_replace_button.setCheckable(True)
        self.show_replace_button.toggled.connect(self._toggle_replace_panel)
        self.replace_button = QPushButton(self.tr("Replace"))
        self.replace_button.clicked.connect(self._replace_current)
        self.replace_all_button = QPushButton(self.tr("Replace All"))
        self.replace_all_button.clicked.connect(self._replace_all)
        self.close_find_button = QPushButton("\u00d7")
        self.close_find_button.clicked.connect(self._hide_find_panel)

        self.find_panel = QFrame(right_panel)
        self.find_panel.setObjectName("translationFindPanel")
        self.find_panel.setVisible(False)
        self.find_panel.setStyleSheet(
            """
            QFrame#translationFindPanel {
                border: 1px solid #d9d0c4;
                border-radius: 14px;
                background: #fcfaf6;
            }
            """
        )
        find_panel_layout = QVBoxLayout(self.find_panel)
        find_panel_layout.setContentsMargins(12, 12, 12, 12)
        find_panel_layout.setSpacing(8)

        find_row = QHBoxLayout()
        find_row.setContentsMargins(0, 0, 0, 0)
        find_row.addWidget(self.find_input, 1)
        find_row.addWidget(self.find_next_button)
        find_row.addWidget(self.show_replace_button)
        find_row.addWidget(self.close_find_button)
        find_panel_layout.addLayout(find_row)

        self.replace_panel = QWidget(self.find_panel)
        replace_row = QHBoxLayout(self.replace_panel)
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.addWidget(self.replace_input, 1)
        replace_row.addWidget(self.replace_button)
        replace_row.addWidget(self.replace_all_button)
        find_panel_layout.addWidget(self.replace_panel)

        self.translation_text = QTextEdit()
        self._configure_text_editor(self.translation_text, read_only=False)
        self.translation_text.textChanged.connect(self._schedule_wrapped_line_sync)
        translation_layout.addWidget(self.translation_text, 1)

        self.line_hint = QLabel()
        self.line_hint.setStyleSheet("color: #666666;")
        self.line_hint.hide()
        self.editor_splitter.addWidget(translation_panel)
        self.editor_splitter.setStretchFactor(0, 1)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_splitter.setSizes([380, 420])
        right_layout.addWidget(self.editor_splitter, 1)
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
        apply_hybrid_control_theme(self)
        set_button_tone(self.find_next_button, size="compact")
        set_button_tone(self.show_replace_button, size="compact")
        set_button_tone(self.replace_button, size="compact")
        set_button_tone(self.replace_all_button, size="compact")
        set_button_tone(self.close_find_button, "ghost", size="compact")
        set_button_tone(self.save_button, "primary")
        set_button_tone(self.retranslate_button)
        set_button_tone(self.previous_button, size="compact")
        set_button_tone(self.next_button, size="compact")
        self._connect_editor_scrollbars()
        self._connect_shortcuts()
        self._connect_qml_signals()
        self._sync_chrome_state()

    def refresh(self) -> None:
        self._capture_current_draft()
        previous_unit_id = self._selected_unit_id()
        self._apply_state(
            self._service.get_translation(
                self._project_id,
                self._document_id,
                enable_polish=self._polish_enabled,
            ),
            previous_unit_id=previous_unit_id,
        )
        self._sync_chrome_state()

    def _refresh_with_suppressed_drafts(self, unit_ids: set[str]) -> None:
        self._suppressed_draft_unit_ids.update(unit_ids)
        self.refresh()

    def get_running_operations(self) -> list[str]:
        if self._state is None or self._state.active_task_id is None:
            return []
        return [self._state.active_task_id]

    def get_navigation_blocking_operations(self) -> list[str]:
        return []

    def _apply_state(self, state: DocumentTranslationState, *, previous_unit_id: str | None) -> None:
        self._prune_drafts(state)
        self._state = state
        self._supports_batch = state.supports_batch
        self._progress_text_value = self._progress_text(state)
        self._can_translate = state.run_action.enabled
        self._can_batch = state.batch_action.enabled
        self.unit_list.blockSignals(True)
        self.unit_list.clear()
        selected_row = 0
        target_unit_id = previous_unit_id or state.current_unit_id
        for index, unit in enumerate(state.units):
            item = QListWidgetItem(self._row_text(unit))
            item.setData(Qt.ItemDataRole.UserRole, unit.unit_id)
            item.setToolTip(translate_backend_text(unit.blocker.message if unit.blocker is not None else ""))
            self.unit_list.addItem(item)
            if target_unit_id is not None and unit.unit_id == target_unit_id:
                selected_row = index
        self.unit_list.blockSignals(False)
        if state.units:
            self.unit_list.setCurrentRow(selected_row)
            self._render_selected_unit(state.units[selected_row])
        else:
            self._render_selected_unit(None)
        self._suppressed_draft_unit_ids -= {unit.unit_id for unit in state.units}
        self._sync_chrome_state()

    def _on_unit_selected(self, row: int) -> None:
        self._capture_current_draft()
        if self._state is None or row < 0 or row >= len(self._state.units):
            self._render_selected_unit(None)
            return
        self._render_selected_unit(self._state.units[row])

    def _render_selected_unit(self, unit: TranslationUnitState | None) -> None:
        if unit is None:
            self._rendered_unit_id = None
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

        self._clear_find_highlight()
        self._rendered_unit_id = unit.unit_id
        self.selection_label.setText(f"{translate_backend_text(unit.label)} · {self.tr(_STATUS_TEXT[unit.status])}")
        self.source_text.setPlainText(unit.source_text or "")
        self.translation_text.setPlainText(self._display_text_for_unit(unit))
        self.translation_text.setReadOnly(not unit.actions.can_save)
        self.save_button.setEnabled(unit.actions.can_save)
        self.retranslate_button.setEnabled(unit.actions.can_retranslate)
        self.save_button.setToolTip(
            translate_backend_text(unit.actions.save_blocker.message if unit.actions.save_blocker is not None else "")
        )
        self.retranslate_button.setToolTip(
            translate_backend_text(
                unit.actions.retranslate_blocker.message if unit.actions.retranslate_blocker is not None else ""
            )
        )

        blocker_text = translate_backend_text(unit.blocker.message if unit.blocker is not None else "")
        self.blocker_label.setText(blocker_text)
        self.blocker_label.setVisible(bool(blocker_text))

        if unit.unit_kind is TranslationUnitKind.CHUNK and unit.line_count and unit.line_count > 0:
            self.line_hint.setText(self.tr("Line count must stay at %1.").replace("%1", str(unit.line_count)))
            self.line_hint.show()
        else:
            self.line_hint.hide()
        self._schedule_wrapped_line_sync()
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
        translated_text = self.translation_text.toPlainText()
        try:
            state = self._service.save_translation(
                SaveTranslationRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    unit_id=unit.unit_id,
                    translated_text=translated_text,
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.warning(self, self.tr("Save Unavailable"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Save Failed"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        saved_unit = self._unit_by_id(state, unit.unit_id)
        if saved_unit is not None and (saved_unit.translated_text or "") == translated_text:
            self._drafts_by_unit_id.pop(unit.unit_id, None)
        else:
            self._drafts_by_unit_id[unit.unit_id] = translated_text
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
            QMessageBox.information(
                self, self.tr("Retranslate Unavailable"), translate_backend_text(exc.payload.message)
            )
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Retranslate Failed"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        self._refresh_with_suppressed_drafts({unit.unit_id})
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
                    enable_polish=self._polish_enabled,
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.information(self, self.tr("Translate Unavailable"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Translate Failed"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        affected_unit_ids = {unit.unit_id for unit in self._state.units} if self._state is not None else set()
        self._refresh_with_suppressed_drafts(affected_unit_ids)
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
                    enable_polish=self._polish_enabled,
                    batch=True,
                )
            )
        except BlockedOperationError as exc:
            QMessageBox.information(
                self, self.tr("Batch Translation Unavailable"), translate_backend_text(exc.payload.message)
            )
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Batch Translation Failed"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        affected_unit_ids = {unit.unit_id for unit in self._state.units} if self._state is not None else set()
        self._refresh_with_suppressed_drafts(affected_unit_ids)
        if command.message is not None:
            self._set_message(command.message.severity, command.message.text)
        else:
            self._set_message(UserMessageSeverity.INFO, self.tr("Async batch translation queued."))

    def _set_message(self, severity: UserMessageSeverity, text: str) -> None:
        _ = severity
        self._message_text_value = translate_backend_text(text)
        self._sync_chrome_state()

    def _capture_current_draft(self) -> None:
        unit = self._rendered_unit()
        if unit is None:
            return
        if unit.unit_id in self._suppressed_draft_unit_ids:
            self._drafts_by_unit_id.pop(unit.unit_id, None)
            return
        current_text = self.translation_text.toPlainText()
        persisted_text = unit.translated_text or ""
        if current_text == persisted_text:
            self._drafts_by_unit_id.pop(unit.unit_id, None)
            return
        self._drafts_by_unit_id[unit.unit_id] = current_text

    def _display_text_for_unit(self, unit: TranslationUnitState) -> str:
        return self._drafts_by_unit_id.get(unit.unit_id, unit.translated_text or "")

    def _prune_drafts(self, state: DocumentTranslationState) -> None:
        next_unit_ids = {unit.unit_id for unit in state.units}
        suppressed_unit_ids = self._suppressed_draft_unit_ids & next_unit_ids
        self._drafts_by_unit_id = {
            unit_id: draft for unit_id, draft in self._drafts_by_unit_id.items() if unit_id in next_unit_ids
        }
        for unit_id in suppressed_unit_ids:
            self._drafts_by_unit_id.pop(unit_id, None)
        for unit in state.units:
            persisted_text = unit.translated_text or ""
            if self._drafts_by_unit_id.get(unit.unit_id) == persisted_text:
                self._drafts_by_unit_id.pop(unit.unit_id, None)

    def _row_text(self, unit: TranslationUnitState) -> str:
        return f"{_STATUS_ICON[unit.status]} {translate_backend_text(unit.label)}"

    def _progress_text(self, state: DocumentTranslationState) -> str:
        parts: list[str] = []
        if state.progress is not None and state.progress.total is not None and state.progress.current is not None:
            parts.append(
                self.tr("Progress: %1/%2")
                .replace("%1", str(state.progress.current))
                .replace("%2", str(state.progress.total))
            )
        elif state.progress is not None and state.progress.label:
            parts.append(translate_progress_label(state.progress.label))
        if state.active_task_id is not None:
            parts.append(self.tr("Active task: %1").replace("%1", state.active_task_id))
        return " | ".join(parts)

    def _on_find_text_changed(self, _text: str) -> None:
        self._clear_find_highlight()

    def _find_next(self) -> None:
        search_text = self.find_input.text()
        if not search_text or self._state is None or not self._state.units:
            return
        self._show_find_panel(show_replace=self.show_replace_button.isChecked())
        self._clear_find_highlight()
        current_row = self.unit_list.currentRow()
        if current_row < 0:
            current_row = 0
        start_position = self._find_start_position()
        match_start = self._find_in_unit_row(current_row, search_text, start_position=start_position)
        if match_start is not None:
            self._select_find_match(current_row, match_start, len(search_text))
            return

        for row in range(current_row + 1, len(self._state.units)):
            match_start = self._find_in_unit_row(row, search_text)
            if match_start is not None:
                self._select_find_match(row, match_start, len(search_text))
                return

        for row in range(0, current_row):
            match_start = self._find_in_unit_row(row, search_text)
            if match_start is not None:
                self._select_find_match(row, match_start, len(search_text))
                return

        wrapped_match = self._find_in_unit_row(current_row, search_text)
        if wrapped_match is not None and wrapped_match < start_position:
            self._select_find_match(current_row, wrapped_match, len(search_text))

    def _replace_current(self) -> None:
        search_text = self.find_input.text()
        if not search_text:
            return
        self._show_find_panel(show_replace=True)
        cursor = self.translation_text.textCursor()
        if cursor.hasSelection() and self._normalized_selected_text(cursor) == search_text:
            cursor.insertText(self.replace_input.text())
        self._find_next()

    def _replace_all(self) -> None:
        search_text = self.find_input.text()
        if not search_text:
            return
        self._show_find_panel(show_replace=True)
        self.translation_text.setPlainText(
            self.translation_text.toPlainText().replace(search_text, self.replace_input.text())
        )
        self._clear_find_highlight()

    def _clear_find_highlight(self) -> None:
        self.translation_text.setExtraSelections([])

    def _configure_text_editor(self, editor: QTextEdit, *, read_only: bool) -> None:
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        editor.setFont(fixed_font)
        editor.setAcceptRichText(False)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setTabStopDistance(editor.fontMetrics().horizontalAdvance(" ") * 4)
        editor.setReadOnly(read_only)

    def _connect_editor_scrollbars(self) -> None:
        self.source_text.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_vertical_scroll(self.source_text, self.translation_text, value)
        )
        self.translation_text.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_vertical_scroll(self.translation_text, self.source_text, value)
        )

    def _sync_vertical_scroll(self, source: QTextEdit, target: QTextEdit, value: int) -> None:
        if self._syncing_editor_scroll:
            return
        target_bar = target.verticalScrollBar()
        mapped_value = self._map_scroll_value(source, target, value)
        if target_bar.value() == mapped_value:
            return
        self._syncing_editor_scroll = True
        try:
            target_bar.setValue(mapped_value)
        finally:
            self._syncing_editor_scroll = False

    def _schedule_wrapped_line_sync(self) -> None:
        if self._line_height_sync_pending:
            return
        self._line_height_sync_pending = True
        QTimer.singleShot(0, self._sync_wrapped_line_heights)

    def _sync_wrapped_line_heights(self) -> None:
        self._line_height_sync_pending = False
        try:
            self._source_block_tops, self._source_block_heights = self._editor_block_metrics(self.source_text)
            self._translation_block_tops, self._translation_block_heights = self._editor_block_metrics(
                self.translation_text
            )
        except RuntimeError:
            return
        if not self._source_block_heights or not self._translation_block_heights:
            self._position_find_panel()
            return
        if self.translation_text.hasFocus() or self.translation_text.textCursor().hasSelection():
            self._sync_vertical_scroll(
                self.translation_text, self.source_text, self.translation_text.verticalScrollBar().value()
            )
        elif self.source_text.hasFocus():
            self._sync_vertical_scroll(
                self.source_text, self.translation_text, self.source_text.verticalScrollBar().value()
            )
        self._ensure_active_translation_selection_visible()
        self._position_find_panel()

    def _editor_block_metrics(self, editor: QTextEdit) -> tuple[list[float], list[float]]:
        tops: list[float] = []
        heights: list[float] = []
        block = editor.document().begin()
        line_height = max(1, editor.fontMetrics().lineSpacing())
        first_top: float | None = None
        layout = editor.document().documentLayout()
        while block.isValid():
            top = float(len(tops) * line_height)
            height = float(line_height)
            rect = layout.blockBoundingRect(block)
            if rect.isValid():
                if first_top is None:
                    first_top = rect.top()
                top = rect.top() - first_top
                height = max(line_height, rect.height())
            tops.append(max(0.0, top))
            heights.append(float(height))
            block = block.next()
        return tops, heights

    def _map_scroll_value(self, source: QTextEdit, target: QTextEdit, value: int) -> int:
        source_tops, source_heights = self._scroll_metrics_for_editor(source)
        target_tops, target_heights = self._scroll_metrics_for_editor(target)
        target_bar = target.verticalScrollBar()
        if not source_tops or not target_tops:
            source_bar = source.verticalScrollBar()
            if source_bar.maximum() <= source_bar.minimum():
                return target_bar.minimum()
            ratio = (value - source_bar.minimum()) / (source_bar.maximum() - source_bar.minimum())
            mapped = target_bar.minimum() + ratio * (target_bar.maximum() - target_bar.minimum())
            return int(round(max(target_bar.minimum(), min(target_bar.maximum(), mapped))))
        source_index = max(0, bisect_right(source_tops, float(value)) - 1)
        source_index = min(source_index, len(source_heights) - 1, len(target_heights) - 1, len(target_tops) - 1)
        source_height = max(1.0, source_heights[source_index])
        target_height = max(1.0, target_heights[source_index])
        offset = min(max(0.0, float(value) - source_tops[source_index]), source_height)
        mapped = target_tops[source_index] + (offset / source_height) * target_height
        return int(round(max(target_bar.minimum(), min(target_bar.maximum(), mapped))))

    def _scroll_metrics_for_editor(self, editor: QTextEdit) -> tuple[list[float], list[float]]:
        if editor is self.source_text:
            return self._source_block_tops, self._source_block_heights
        return self._translation_block_tops, self._translation_block_heights

    def _rendered_unit(self) -> TranslationUnitState | None:
        return self._unit_by_id(self._state, self._rendered_unit_id)

    def _unit_by_id(self, state: DocumentTranslationState | None, unit_id: str | None) -> TranslationUnitState | None:
        if state is None or unit_id is None:
            return None
        for unit in state.units:
            if unit.unit_id == unit_id:
                return unit
        return None

    def _connect_shortcuts(self) -> None:
        find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find_shortcut.activated.connect(self._show_find_panel)
        replace_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Replace), self)
        replace_shortcut.activated.connect(self._show_replace_panel)
        close_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.find_panel)
        close_shortcut.activated.connect(self._hide_find_panel)
        self._shortcuts = [find_shortcut, replace_shortcut, close_shortcut]

    def _show_find_panel(self, *, show_replace: bool = False) -> None:
        if not self.find_panel.isVisible():
            self.find_panel.show()
        self._set_replace_toggle_state(show_replace)
        self.replace_panel.setVisible(show_replace)
        self._position_find_panel()
        self.find_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.find_input.selectAll()

    def _show_replace_panel(self) -> None:
        self._show_find_panel(show_replace=True)
        self.replace_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.replace_input.selectAll()

    def _toggle_replace_panel(self, checked: bool) -> None:
        if checked:
            self._show_find_panel(show_replace=True)
            self.replace_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.replace_input.selectAll()
            return
        if not self.find_panel.isVisible():
            return
        self.replace_panel.hide()
        self._position_find_panel()
        self.find_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _hide_find_panel(self) -> None:
        self.find_panel.hide()
        self._set_replace_toggle_state(False)
        self.replace_panel.hide()
        self.translation_text.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_replace_toggle_state(self, checked: bool) -> None:
        blocker = QSignalBlocker(self.show_replace_button)
        self.show_replace_button.setChecked(checked)
        del blocker

    def _position_find_panel(self) -> None:
        try:
            self.find_panel.adjustSize()
            panel_width = self.find_panel.sizeHint().width()
            panel_height = self.find_panel.sizeHint().height()
            host_rect = self.editor_splitter.geometry()
            margin = 12
            x = max(margin, host_rect.right() - panel_width - margin)
            y = host_rect.top() + margin
            self.find_panel.setGeometry(x, y, panel_width, panel_height)
            self.find_panel.raise_()
        except RuntimeError:
            return

    def _find_start_position(self) -> int:
        cursor = self.translation_text.textCursor()
        if cursor.hasSelection():
            return cursor.selectionEnd()
        return cursor.position()

    def _find_in_unit_row(self, row: int, search_text: str, *, start_position: int = 0) -> int | None:
        text = self._translation_text_for_row(row)
        match_start = text.find(search_text, max(0, start_position))
        return match_start if match_start >= 0 else None

    def _translation_text_for_row(self, row: int) -> str:
        if self._state is None or row < 0 or row >= len(self._state.units):
            return ""
        if row == self.unit_list.currentRow():
            return self.translation_text.toPlainText()
        return self._display_text_for_unit(self._state.units[row])

    def _select_find_match(self, row: int, start: int, length: int) -> None:
        if row != self.unit_list.currentRow():
            self.unit_list.setCurrentRow(row)
        self.translation_text.setFocus(Qt.FocusReason.OtherFocusReason)
        cursor = self.translation_text.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        self.translation_text.setTextCursor(cursor)
        self.translation_text.ensureCursorVisible()
        self._ensure_find_match_clear_of_overlay()

    def _ensure_active_translation_selection_visible(self) -> None:
        if not self.translation_text.textCursor().hasSelection():
            return
        self.translation_text.ensureCursorVisible()
        self._ensure_find_match_clear_of_overlay()

    def _ensure_find_match_clear_of_overlay(self) -> None:
        if not self.find_panel.isVisible():
            return
        try:
            panel_bottom = (
                self.translation_text.viewport()
                .mapFromGlobal(self.find_panel.mapToGlobal(self.find_panel.rect().bottomLeft()))
                .y()
            )
        except RuntimeError:
            return
        clearance_top = max(0, panel_bottom + 12)
        cursor_top = self.translation_text.cursorRect().top()
        if cursor_top >= clearance_top:
            return
        scroll_bar = self.translation_text.verticalScrollBar()
        target_value = max(scroll_bar.minimum(), scroll_bar.value() - (clearance_top - cursor_top))
        if target_value != scroll_bar.value():
            scroll_bar.setValue(target_value)

    def _normalized_selected_text(self, cursor: QTextCursor) -> str:
        return cursor.selectedText().replace("\u2029", "\n")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._position_find_panel()
        self._schedule_wrapped_line_sync()

    def retranslateUi(self) -> None:
        self.source_label.setText(self.tr("Source"))
        self.translation_label.setText(self.tr("Translation"))
        self.find_input.setPlaceholderText(self.tr("Find..."))
        self.replace_input.setPlaceholderText(self.tr("Replace with..."))
        self.find_next_button.setText(self.tr("Find Next"))
        self.show_replace_button.setText(self.tr("Replace"))
        self.replace_button.setText(self.tr("Replace"))
        self.replace_all_button.setText(self.tr("Replace All"))
        self.close_find_button.setToolTip(self.tr("Close find panel"))
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
        cast(Any, root).polishToggled.connect(self._on_polish_toggled)
        cast(Any, root).translateRequested.connect(self._translate_document)
        cast(Any, root).batchRequested.connect(self._submit_batch_translation)

    def _on_polish_toggled(self, enabled: bool) -> None:
        if enabled == self._polish_enabled:
            return
        self._polish_enabled = enabled
        self.refresh()

    def _sync_chrome_state(self) -> None:
        translate_tooltip = self.tr("Translate all pending units in this document with the current settings.")
        batch_tooltip = self.tr("Submit this document as an asynchronous batch translation job.")
        if self._state is not None and self._state.run_action.blocker is not None:
            translate_tooltip = translate_backend_text(self._state.run_action.blocker.message)
        if self._state is not None and self._state.batch_action.blocker is not None:
            batch_tooltip = translate_backend_text(self._state.batch_action.blocker.message)
        self.viewmodel.apply_state(
            progress_text=self._progress_text_value.strip(),
            message_text=self._message_text_value.strip(),
            polish_enabled=self._polish_enabled,
            can_translate=self._can_translate,
            supports_batch=self._supports_batch,
            can_batch=self._can_batch,
            translate_tooltip=translate_tooltip,
            batch_tooltip=batch_tooltip,
        )


__all__ = ["DocumentTranslationView"]
