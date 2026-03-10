from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.document import (
    DocumentOCRState,
    OCRBoundingBox,
    OCRPageState,
    OCRTextElement,
    RunOCRRequest,
    SaveOCRPageRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets import ImageViewer, ProgressWidget


class _SelectableTextEdit(QTextEdit):
    focused = Signal()

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self.focused.emit()
        super().focusInEvent(event)


class _StructuredElementCard(QFrame):
    selected = Signal(int)

    def __init__(self, index: int, element: OCRTextElement, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._selected = False
        self._editor = _SelectableTextEdit(self)
        self._editor.setPlainText(element.text)
        self._editor.setMinimumHeight(64)
        self._editor.focused.connect(lambda: self.selected.emit(self._index))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        title = QLabel(self._title_text(element), self)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        if element.bbox is not None:
            bbox_label = QLabel(self._bbox_text(element.bbox), self)
            bbox_label.setStyleSheet("color: #667085; font-size: 11px;")
            layout.addWidget(bbox_label)
        layout.addWidget(self._editor)
        self._apply_style()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.selected.emit(self._index)
        super().mousePressEvent(event)

    def text(self) -> str:
        return self._editor.toPlainText()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        border = "#f79009" if self._selected else "#d0d5dd"
        background = "#fff7ed" if self._selected else "#ffffff"
        self.setStyleSheet(
            f"QFrame {{ border: 2px solid {border}; border-radius: 6px; background: {background}; }}"
        )

    @staticmethod
    def _title_text(element: OCRTextElement) -> str:
        kind = (element.kind or "Text").replace("_", " ").title()
        return f"{kind}"

    @staticmethod
    def _bbox_text(bbox: OCRBoundingBox) -> str:
        return f"x={bbox.x:.3f}, y={bbox.y:.3f}, w={bbox.width:.3f}, h={bbox.height:.3f}"


class _StructuredElementList(QScrollArea):
    element_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[_StructuredElementCard] = []
        self._selected_index = -1
        self._container = QWidget(self)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)
        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def set_elements(self, elements: list[OCRTextElement]) -> None:
        self.clear()
        for index, element in enumerate(elements):
            card = _StructuredElementCard(index, element, parent=self._container)
            card.selected.connect(self._on_selected)
            self._cards.append(card)
            self._layout.addWidget(card)
        self._layout.addStretch()

    def clear(self) -> None:
        self._selected_index = -1
        self._cards.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def texts(self) -> list[str]:
        return [card.text() for card in self._cards]

    def select_element(self, index: int) -> None:
        if 0 <= self._selected_index < len(self._cards):
            self._cards[self._selected_index].set_selected(False)
        self._selected_index = index
        if 0 <= index < len(self._cards):
            self._cards[index].set_selected(True)
            self.ensureWidgetVisible(self._cards[index])

    def _on_selected(self, index: int) -> None:
        self.select_element(index)
        self.element_selected.emit(index)


class DocumentOCRTab(QWidget):
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
        self._state: DocumentOCRState | None = None
        self._current_page_index: int | None = None
        self._element_to_bbox: dict[int, int] = {}
        self._bbox_to_element: dict[int, int] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(
            self.tr("OCR applies only to the current document. Saving OCR does not rerun later steps.")
        )
        layout.addWidget(self.tip_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.image_viewer = ImageViewer(self)
        self.image_viewer.bbox_clicked.connect(self._on_bbox_clicked)
        splitter.addWidget(self.image_viewer)

        self._right_stack = QStackedWidget(self)
        self.text_edit = QTextEdit(self)
        self.text_edit.setPlaceholderText(self.tr("OCR text will appear here."))
        self.structured_list = _StructuredElementList(self)
        self.structured_list.element_selected.connect(self._on_element_selected)
        self._right_stack.addWidget(self.text_edit)
        self._right_stack.addWidget(self.structured_list)
        splitter.addWidget(self._right_stack)
        splitter.setSizes([480, 480])
        layout.addWidget(splitter, 1)

        nav_row = QHBoxLayout()
        self.first_button = QPushButton(self.tr("|<"), self)
        self.first_button.clicked.connect(self._go_first)
        nav_row.addWidget(self.first_button)

        self.prev_button = QPushButton(self.tr("Previous"), self)
        self.prev_button.clicked.connect(self._go_previous)
        nav_row.addWidget(self.prev_button)

        self.page_label = QLabel(self.tr("Page 0 of 0"), self)
        nav_row.addWidget(self.page_label)

        self.page_status_label = QLabel(self)
        nav_row.addWidget(self.page_status_label)

        self.next_button = QPushButton(self.tr("Next"), self)
        self.next_button.clicked.connect(self._go_next)
        nav_row.addWidget(self.next_button)

        self.last_button = QPushButton(self.tr(">|"), self)
        self.last_button.clicked.connect(self._go_last)
        nav_row.addWidget(self.last_button)

        self.page_combo = QComboBox(self)
        self.page_combo.hide()
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)

        self.page_spinbox = QSpinBox(self)
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setFixedWidth(64)
        nav_row.addWidget(self.page_spinbox)

        self.go_button = QPushButton(self.tr("Go"), self)
        self.go_button.clicked.connect(self._go_to_entered_page)
        nav_row.addWidget(self.go_button)
        layout.addLayout(nav_row)

        action_row = QHBoxLayout()
        self.save_button = QPushButton(self.tr("Save"), self)
        self.save_button.clicked.connect(self._save_current)
        action_row.addWidget(self.save_button)

        self.run_current_button = QPushButton(self.tr("Run OCR for This Page"), self)
        self.run_current_button.clicked.connect(self._run_current)
        action_row.addWidget(self.run_current_button)

        self.run_pending_button = QPushButton(self.tr("Run OCR for Pending Pages"), self)
        self.run_pending_button.clicked.connect(self._run_pending)
        action_row.addWidget(self.run_pending_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.message_label = QLabel(self)
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.progress_widget = ProgressWidget(self)
        self.progress_widget.setVisible(False)
        self.progress_widget.set_cancellable(False)
        layout.addWidget(self.progress_widget)

        self.empty_label = create_tip_label(self.tr("No image pages are available for OCR in this document."))
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

    def refresh(self) -> None:
        current_source_id = self._current_page.source_id if self._current_page is not None else None
        self._state = self._service.get_ocr(self._project_id, self._document_id)
        self._sync_page_combo(current_source_id=current_source_id)
        self._apply_actions()
        self._apply_progress()

    def get_running_operations(self) -> list[str]:
        if self._state is not None and self._state.active_task_id is not None:
            return ["ocr"]
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:  # noqa: ARG002
        return

    @property
    def _current_page(self) -> OCRPageState | None:
        if self._state is None or self._current_page_index is None:
            return None
        if self._current_page_index < 0 or self._current_page_index >= len(self._state.pages):
            return None
        return self._state.pages[self._current_page_index]

    def _sync_page_combo(self, *, current_source_id: int | None) -> None:
        assert self._state is not None
        pages = self._state.pages
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for page in pages:
            self.page_combo.addItem(self.tr("Page %1").replace("%1", str(page.page_number)), page.source_id)
        self.page_combo.blockSignals(False)

        if not pages:
            self._current_page_index = None
            self.image_viewer.clear_image()
            self.image_viewer.clear_bboxes()
            self.text_edit.clear()
            self.structured_list.clear()
            self._right_stack.setCurrentWidget(self.text_edit)
            self.page_label.setText(self.tr("Page 0 of 0"))
            self.page_status_label.clear()
            self.page_spinbox.setMaximum(1)
            self.empty_label.show()
            return

        self.empty_label.hide()
        selected_index = 0
        if current_source_id is not None:
            for index, page in enumerate(pages):
                if page.source_id == current_source_id:
                    selected_index = index
                    break
        elif self._state.current_page_index is not None and 0 <= self._state.current_page_index < len(pages):
            selected_index = self._state.current_page_index

        self._set_current_page(selected_index)

    def _set_current_page(self, index: int) -> None:
        if self._state is None or not self._state.pages:
            self._current_page_index = None
            return
        if index < 0 or index >= len(self._state.pages):
            index = 0
        self._current_page_index = index
        self.page_combo.blockSignals(True)
        self.page_combo.setCurrentIndex(index)
        self.page_combo.blockSignals(False)

        page = self._state.pages[index]
        total_pages = len(self._state.pages)
        self.page_label.setText(self.tr("Page %1 of %2").replace("%1", str(index + 1)).replace("%2", str(total_pages)))
        self.page_spinbox.setMaximum(total_pages)
        self.page_spinbox.setValue(index + 1)
        self.first_button.setEnabled(index > 0)
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self._state.pages) - 1)
        self.last_button.setEnabled(index < len(self._state.pages) - 1)
        self.page_status_label.setText(page.status.value.replace("_", " ").title())

        try:
            image_bytes = self._service.get_ocr_page_image(self._project_id, self._document_id, page.source_id)
        except ApplicationError:
            image_bytes = None
        if image_bytes:
            self.image_viewer.set_image(image_bytes)
        else:
            self.image_viewer.clear_image()

        if page.elements:
            self._set_structured_page(page)
        else:
            self.image_viewer.clear_bboxes()
            self.structured_list.clear()
            self.text_edit.setPlainText(page.extracted_text or "")
            self._right_stack.setCurrentWidget(self.text_edit)

    def _set_structured_page(self, page: OCRPageState) -> None:
        self.structured_list.set_elements(page.elements)
        self._right_stack.setCurrentWidget(self.structured_list)
        self._element_to_bbox = {}
        self._bbox_to_element = {}
        bboxes: list[OCRBoundingBox] = []
        for index, element in enumerate(page.elements):
            if element.bbox is None:
                continue
            bbox_index = len(bboxes)
            bboxes.append(element.bbox)
            self._element_to_bbox[index] = bbox_index
            self._bbox_to_element.setdefault(bbox_index, index)
        if bboxes:
            self.image_viewer.set_bboxes(bboxes)
        else:
            self.image_viewer.clear_bboxes()

    def _on_bbox_clicked(self, bbox_index: int) -> None:
        element_index = self._bbox_to_element.get(bbox_index)
        if element_index is None:
            return
        self.structured_list.select_element(element_index)
        self.image_viewer.highlight_bbox(bbox_index)

    def _on_element_selected(self, element_index: int) -> None:
        bbox_index = self._element_to_bbox.get(element_index, -1)
        self.image_viewer.highlight_bbox(bbox_index)

    def _apply_actions(self) -> None:
        if self._state is None:
            self.save_button.setEnabled(False)
            self.run_current_button.setEnabled(False)
            self.run_pending_button.setEnabled(False)
            return

        self.save_button.setEnabled(self._state.actions.save.enabled)
        self.save_button.setToolTip(
            self._state.actions.save.blocker.message if self._state.actions.save.blocker is not None else ""
        )

        self.run_current_button.setEnabled(self._state.actions.run_current.enabled)
        self.run_current_button.setToolTip(
            self._state.actions.run_current.blocker.message
            if self._state.actions.run_current.blocker is not None
            else ""
        )

        self.run_pending_button.setEnabled(self._state.actions.run_pending.enabled)
        self.run_pending_button.setToolTip(
            self._state.actions.run_pending.blocker.message
            if self._state.actions.run_pending.blocker is not None
            else ""
        )

    def _apply_progress(self) -> None:
        if self._state is None or self._state.active_task_id is None:
            self.progress_widget.reset()
            self.progress_widget.setVisible(False)
            return

        self.progress_widget.setVisible(True)
        self.progress_widget.set_cancellable(False)
        progress = self._state.progress
        if progress is not None and progress.current is not None and progress.total is not None and progress.total > 0:
            self.progress_widget.progress_bar.setRange(0, 100)
            self.progress_widget.set_progress(
                progress.current, progress.total, progress.label or self.tr("OCR running...")
            )
            return

        self.progress_widget.progress_bar.setRange(0, 0)
        self.progress_widget.message_label.setText(self.tr("OCR running..."))
        self.progress_widget.eta_label.clear()

    def _go_previous(self) -> None:
        if self._current_page_index is None:
            return
        self._set_current_page(self._current_page_index - 1)

    def _go_first(self) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(0)

    def _go_next(self) -> None:
        if self._current_page_index is None:
            return
        self._set_current_page(self._current_page_index + 1)

    def _go_last(self) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(len(self._state.pages) - 1)

    def _on_page_changed(self, index: int) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(index)

    def _go_to_entered_page(self) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(self.page_spinbox.value() - 1)

    def _save_current(self) -> None:
        page = self._current_page
        if page is None:
            return

        if page.elements:
            edited_lines = self.structured_list.texts()
            if len(edited_lines) != len(page.elements):
                QMessageBox.warning(
                    self,
                    self.tr("Line Count Mismatch"),
                    self.tr("Structured OCR text must keep the same number of lines as the original OCR result."),
                )
                return
            elements = [
                OCRTextElement(
                    element_id=original.element_id,
                    bbox_id=original.bbox_id,
                    text=text,
                )
                for original, text in zip(page.elements, edited_lines, strict=True)
            ]
            request = SaveOCRPageRequest(
                project_id=self._project_id,
                document_id=self._document_id,
                source_id=page.source_id,
                extracted_text="\n".join(edited_lines),
                elements=elements,
            )
        else:
            edited_text = self.text_edit.toPlainText()
            if not ((page.extracted_text or "").strip() or edited_text.strip()):
                QMessageBox.information(self, self.tr("OCR"), self.tr("No OCR data is available for this page yet."))
                return
            request = SaveOCRPageRequest(
                project_id=self._project_id,
                document_id=self._document_id,
                source_id=page.source_id,
                extracted_text=edited_text,
            )

        try:
            self._state = self._service.save_ocr(request)
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), exc.payload.message)
            self.refresh()
            return

        self._set_message(self.tr("OCR text saved."))
        self._sync_page_combo(current_source_id=page.source_id)
        self._apply_actions()
        self._apply_progress()

    def _run_current(self) -> None:
        page = self._current_page
        if page is None:
            return
        try:
            result = self._service.run_ocr(
                RunOCRRequest(project_id=self._project_id, document_id=self._document_id, source_id=page.source_id)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), exc.payload.message)
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("OCR queued."))

    def _run_pending(self) -> None:
        try:
            result = self._service.run_ocr(
                RunOCRRequest(project_id=self._project_id, document_id=self._document_id, pending_only=True)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), exc.payload.message)
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("OCR queued."))

    def _set_message(self, text: str) -> None:
        if not text:
            self.message_label.hide()
            self.message_label.clear()
            return
        self.message_label.setText(text)
        self.message_label.show()
