from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.document import (
    DocumentOCRState,
    OCRPageState,
    OCRTextElement,
    RunOCRRequest,
    SaveOCRPageRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets import ImageViewer, ProgressWidget


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
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(
            self.tr("OCR applies only to the current document. Saving OCR does not rerun later steps.")
        )
        layout.addWidget(self.tip_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.image_viewer = ImageViewer(self)
        splitter.addWidget(self.image_viewer)

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlaceholderText(self.tr("OCR text will appear here."))
        splitter.addWidget(self.text_edit)
        splitter.setSizes([480, 480])
        layout.addWidget(splitter, 1)

        nav_row = QHBoxLayout()
        self.prev_button = QPushButton(self.tr("Previous"), self)
        self.prev_button.clicked.connect(self._go_previous)
        nav_row.addWidget(self.prev_button)

        self.page_combo = QComboBox(self)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        nav_row.addWidget(self.page_combo, 1)

        self.next_button = QPushButton(self.tr("Next"), self)
        self.next_button.clicked.connect(self._go_next)
        nav_row.addWidget(self.next_button)

        self.page_status_label = QLabel(self)
        nav_row.addWidget(self.page_status_label)
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
            self.text_edit.clear()
            self.page_status_label.clear()
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
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self._state.pages) - 1)
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
            self.text_edit.setPlainText("\n".join(element.text for element in page.elements))
        else:
            self.text_edit.setPlainText(page.extracted_text or "")

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

    def _go_next(self) -> None:
        if self._current_page_index is None:
            return
        self._set_current_page(self._current_page_index + 1)

    def _on_page_changed(self, index: int) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(index)

    def _save_current(self) -> None:
        page = self._current_page
        if page is None:
            return

        if page.elements:
            edited_lines = self.text_edit.toPlainText().split("\n")
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
