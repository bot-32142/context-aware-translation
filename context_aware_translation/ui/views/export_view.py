"""Export view for exporting translated content."""

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.documents.base import (
    get_supported_formats_for_type,
    is_ocr_required_for_type,
    supports_multi_export_for_type,
    supports_preserve_structure_for_type,
)
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository

from ..i18n import qarg, translate_progress_message
from ..utils import create_tip_label, translate_document_type
from ..widgets import ProgressWidget
from ..workers.export_worker import ExportWorker


class ExportView(QWidget):
    """View for exporting translated content."""

    export_completed = Signal(str)  # output path

    def __init__(self, book_manager: BookManager, book_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self.worker: ExportWorker | None = None
        self.documents: list[dict] = []

        self._init_ui()
        self._load_documents()

    def _init_ui(self) -> None:
        """Initialize the UI."""
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # Document selection group
        self.doc_group = QGroupBox(self.tr("Select Documents"))
        doc_layout = QVBoxLayout(self.doc_group)

        self.doc_list = QListWidget()
        self.doc_list.itemChanged.connect(self._on_document_selection_changed)
        doc_layout.addWidget(self.doc_list)

        # Select all/none buttons
        select_buttons_layout = QHBoxLayout()
        self.select_all_btn = QPushButton(self.tr("Select All"))
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn = QPushButton(self.tr("Deselect All"))
        self.select_none_btn.clicked.connect(self._deselect_all)
        select_buttons_layout.addWidget(self.select_all_btn)
        select_buttons_layout.addWidget(self.select_none_btn)
        select_buttons_layout.addStretch()
        doc_layout.addLayout(select_buttons_layout)

        layout.addWidget(self.doc_group)

        # Format selection
        format_layout = QHBoxLayout()
        self.format_label = QLabel(self.tr("Export Format:"))
        format_layout.addWidget(self.format_label)
        self.format_combo = QComboBox()
        self.format_combo.currentTextChanged.connect(self._update_output_extension)
        format_layout.addWidget(self.format_combo)
        format_layout.addStretch()
        layout.addLayout(format_layout)

        # Output path
        output_layout = QHBoxLayout()
        self.output_label = QLabel(self.tr("Output Path:"))
        output_layout.addWidget(self.output_label)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        output_layout.addWidget(self.output_path_edit)
        self.browse_btn = QPushButton(self.tr("Browse..."))
        self.browse_btn.clicked.connect(self._browse_output)
        output_layout.addWidget(self.browse_btn)
        layout.addLayout(output_layout)

        # Options
        self.preserve_structure_cb = QCheckBox(self.tr("Preserve folder structure (text documents only)"))
        self.preserve_structure_cb.stateChanged.connect(self._toggle_preserve_structure)
        layout.addWidget(self.preserve_structure_cb)
        self.allow_original_fallback_cb = QCheckBox(
            self.tr("Allow fallback to original content for untranslated chunks")
        )
        self.allow_original_fallback_cb.stateChanged.connect(self._update_available_formats)
        layout.addWidget(self.allow_original_fallback_cb)

        # Progress widget
        self.progress_widget = ProgressWidget()
        self.progress_widget.cancelled.connect(self._cancel_export)
        self.progress_widget.hide()
        layout.addWidget(self.progress_widget)

        # Export button
        self.export_btn = QPushButton(self.tr("Export"))
        self.export_btn.clicked.connect(self._start_export)
        layout.addWidget(self.export_btn)

        # Result area
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        layout.addWidget(self.result_label)

        self.open_folder_btn = QPushButton(self.tr("Open Containing Folder"))
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.open_folder_btn.hide()
        layout.addWidget(self.open_folder_btn)

        layout.addStretch()

    def _load_documents(self, *, show_errors: bool = True) -> None:
        """Load documents from the database, excluding those with pending OCR."""
        self.documents = []
        try:
            db_path = self.book_manager.get_book_db_path(self.book_id)
            db = SQLiteBookDB(db_path)
            try:
                repo = DocumentRepository(db)
                all_documents = repo.get_documents_with_status()

                # Filter out documents with pending OCR (skip check for types where OCR is optional)
                self.documents = []
                for doc in all_documents:
                    if not is_ocr_required_for_type(doc.get("document_type", "")):
                        self.documents.append(doc)
                        continue
                    pending_ocr = int(doc.get("ocr_pending", 0) or 0)
                    if pending_ocr == 0:
                        self.documents.append(doc)
            finally:
                db.close()

            if not self.documents:
                if all_documents:
                    message = self.tr("All documents have pending OCR. Please complete OCR first.")
                else:
                    message = self.tr("No documents found in the database.")
                if show_errors:
                    self._show_error(message)
                else:
                    self._show_inline_error(message)
                self.export_btn.setEnabled(False)
                return

            # Populate document list (block signals during initial population)
            self.doc_list.blockSignals(True)
            for doc in self.documents:
                doc_type_display = translate_document_type(doc["document_type"])
                total_chunks = int(doc.get("total_chunks", 0) or 0)
                translated_chunks = int(doc.get("chunks_translated", 0) or 0)
                if total_chunks > 0 and translated_chunks == total_chunks:
                    label = qarg(self.tr("Document %1 (%2) [Translated]"), doc["document_id"], doc_type_display)
                elif translated_chunks > 0:
                    label = qarg(
                        self.tr("Document %1 (%2) [%3/%4 translated]"),
                        doc["document_id"],
                        doc_type_display,
                        translated_chunks,
                        total_chunks,
                    )
                elif total_chunks == 0:
                    label = qarg(self.tr("Document %1 (%2) [Not translated]"), doc["document_id"], doc_type_display)
                else:
                    label = qarg(self.tr("Document %1 (%2)"), doc["document_id"], doc_type_display)
                item = QListWidgetItem(label)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, doc["document_id"])
                self.doc_list.addItem(item)
            self.doc_list.blockSignals(False)

            # Determine available formats based on document types
            self._update_available_formats()
            if self.result_label.styleSheet() == "color: red;":
                self.result_label.hide()

        except Exception as e:
            message = qarg(self.tr("Failed to load documents: %1"), e)
            if show_errors:
                self._show_error(message)
            else:
                self._show_inline_error(message)
            self.export_btn.setEnabled(False)

    def refresh(self) -> None:
        """Refresh the view with current data.

        Called when switching to this tab to ensure document list is up-to-date.
        """
        # Save current per-document check states.
        selection_states: dict[int, Qt.CheckState] = {}
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            if item:
                doc_id = item.data(Qt.ItemDataRole.UserRole)
                if doc_id is not None:
                    selection_states[int(doc_id)] = item.checkState()

        # Clear and reload
        self.doc_list.clear()
        self._load_documents(show_errors=False)

        # Restore previous check states where possible.
        self.doc_list.blockSignals(True)
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            if item:
                doc_id = item.data(Qt.ItemDataRole.UserRole)
                if doc_id is not None and int(doc_id) in selection_states:
                    item.setCheckState(selection_states[int(doc_id)])
        self.doc_list.blockSignals(False)
        self._update_available_formats()

    def _update_available_formats(self, *_args) -> None:
        """Update available export formats based on selected documents."""
        selected_docs = self._get_selected_documents()
        if not selected_docs:
            self.format_combo.clear()
            self.preserve_structure_cb.setEnabled(False)
            self.preserve_structure_cb.setChecked(False)
            self.export_btn.setEnabled(False)
            return

        # Get document types
        doc_types = {doc["document_type"] for doc in selected_docs}

        if len(doc_types) > 1:
            # Mixed types - no export allowed
            self.format_combo.clear()
            self.format_combo.addItem(self.tr("(Mixed document types - cannot export)"))
            self.export_btn.setEnabled(False)
            return

        # Single type - get formats from document class
        doc_type = doc_types.pop()

        if len(selected_docs) > 1 and not supports_multi_export_for_type(doc_type):
            self.format_combo.clear()
            self.format_combo.addItem(self.tr("(Select only one document for this type)"))
            self.export_btn.setEnabled(False)
            return
        formats = list(get_supported_formats_for_type(doc_type))

        # Enable preserve structure based on document class attribute
        if supports_preserve_structure_for_type(doc_type):
            self.preserve_structure_cb.setEnabled(True)
        else:
            self.preserve_structure_cb.setEnabled(False)
            self.preserve_structure_cb.setChecked(False)

        self.format_combo.clear()
        self.format_combo.addItems(formats)
        allow_fallback = self.allow_original_fallback_cb.isChecked()
        fully_translated = self._are_documents_fully_translated(selected_docs)
        can_export = bool(formats) and (allow_fallback or fully_translated)
        self.export_btn.setEnabled(can_export)
        if not can_export and not allow_fallback and bool(formats):
            self.export_btn.setToolTip(
                self.tr(
                    "Translate all selected documents first, or enable fallback to export "
                    "untranslated chunks using original content."
                )
            )
        else:
            self.export_btn.setToolTip("")

    @staticmethod
    def _are_documents_fully_translated(documents: list[dict]) -> bool:
        """Return True only if each selected document has all chunks translated."""
        if not documents:
            return False
        for doc in documents:
            total_chunks = int(doc.get("total_chunks", 0) or 0)
            translated_chunks = int(doc.get("chunks_translated", 0) or 0)
            if total_chunks <= 0 or translated_chunks < total_chunks:
                return False
        return True

    def _get_selected_documents(self) -> list[dict]:
        """Get list of selected documents."""
        selected = []
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                doc_id = item.data(Qt.ItemDataRole.UserRole)
                doc = next((d for d in self.documents if d["document_id"] == doc_id), None)
                if doc:
                    selected.append(doc)
        return selected

    def _on_document_selection_changed(self, _item: QListWidgetItem) -> None:
        """Handle document selection change."""
        self._update_available_formats()

    def _select_all(self) -> None:
        """Select all documents."""
        self.doc_list.blockSignals(True)
        for i in range(self.doc_list.count()):
            self.doc_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.doc_list.blockSignals(False)
        self._update_available_formats()

    def _deselect_all(self) -> None:
        """Deselect all documents."""
        self.doc_list.blockSignals(True)
        for i in range(self.doc_list.count()):
            self.doc_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.doc_list.blockSignals(False)
        self._update_available_formats()

    def _update_output_extension(self) -> None:
        """Update output path extension when format changes."""
        current_path = self.output_path_edit.text()
        if current_path:
            path = Path(current_path)
            new_format = self.format_combo.currentText()
            if new_format and not new_format.startswith("("):
                new_path = path.with_suffix(f".{new_format}")
                self.output_path_edit.setText(str(new_path))

    def _toggle_preserve_structure(self, state: int) -> None:
        """Toggle preserve structure mode."""
        if state == Qt.CheckState.Checked.value:
            # Preserve structure mode - select folder
            self.output_path_edit.setPlaceholderText(self.tr("Select output folder..."))
        else:
            # Normal mode - select file
            self.output_path_edit.setPlaceholderText(self.tr("Select output file..."))

    def _browse_output(self) -> None:
        """Browse for output location."""
        if self.preserve_structure_cb.isChecked():
            # Select folder
            folder = QFileDialog.getExistingDirectory(self, self.tr("Select Output Folder"))
            if folder:
                self.output_path_edit.setText(folder)
        else:
            # Select file
            export_format = self.format_combo.currentText()
            if not export_format or export_format.startswith("("):
                QMessageBox.warning(self, self.tr("No Format"), self.tr("Please select a valid export format first."))
                return

            # Build filter
            filter_str = qarg(self.tr("%1 Files (*.%2)"), export_format.upper(), export_format)

            file_path, _ = QFileDialog.getSaveFileName(
                self, self.tr("Save Export File"), f"export.{export_format}", filter_str
            )
            if file_path:
                self.output_path_edit.setText(file_path)

    def _start_export(self) -> None:
        """Start the export process."""
        if self.worker and self.worker.isRunning():
            return

        selected_docs = self._get_selected_documents()
        if not selected_docs:
            QMessageBox.warning(
                self, self.tr("No Documents"), self.tr("Please select at least one document to export.")
            )
            return

        output_path = self.output_path_edit.text()
        if not output_path:
            QMessageBox.warning(self, self.tr("No Output Path"), self.tr("Please select an output path."))
            return

        export_format = self.format_combo.currentText()
        preserve_structure = self.preserve_structure_cb.isChecked()
        allow_original_fallback = self.allow_original_fallback_cb.isChecked()

        # Validate format
        if export_format.startswith("("):
            QMessageBox.warning(self, self.tr("Invalid Format"), self.tr("Cannot export with mixed document types."))
            return

        if not allow_original_fallback and not self._are_documents_fully_translated(selected_docs):
            QMessageBox.warning(
                self,
                self.tr("Incomplete Translation"),
                self.tr(
                    "Some selected documents are not fully translated.\n\n"
                    "Translate all chunks first, or enable fallback to export untranslated chunks using original content."
                ),
            )
            return

        # Get document IDs
        document_ids = [doc["document_id"] for doc in selected_docs]

        # Hide result, show progress
        self.result_label.hide()
        self.open_folder_btn.hide()
        self.progress_widget.reset()
        self.progress_widget.set_cancellable(True)
        self.progress_widget.show()
        self.export_btn.setEnabled(False)

        # Create worker
        self.worker = ExportWorker(
            book_manager=self.book_manager,
            book_id=self.book_id,
            output_path=Path(output_path),
            export_format=None if preserve_structure else export_format,
            document_ids=document_ids,
            preserve_structure=preserve_structure,
            allow_original_fallback=allow_original_fallback,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_success.connect(self._on_export_success)
        self.worker.cancelled.connect(self._on_export_cancelled)
        self.worker.error.connect(self._on_export_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _cancel_export(self) -> None:
        """Cancel the export."""
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.progress_widget.message_label.setText(self.tr("Cancelling..."))
            self.progress_widget.set_cancellable(False)

    def _on_progress(self, current: int, total: int, message: str) -> None:
        """Handle progress update."""
        translated_message = translate_progress_message(message)
        self.progress_widget.set_progress(current, total, translated_message)

    def _on_export_success(self, output_path: str) -> None:
        """Handle successful export."""
        self.progress_widget.hide()

        self.result_label.setText(qarg(self.tr("Export completed successfully!\n\nOutput: %1"), output_path))
        self.result_label.setStyleSheet("color: green;")
        self.result_label.show()
        self.open_folder_btn.show()

        self.export_completed.emit(output_path)

    def _on_export_cancelled(self) -> None:
        """Handle cancelled export."""
        self.progress_widget.hide()
        QMessageBox.information(self, self.tr("Cancelled"), self.tr("Export cancelled."))

    def _on_export_error(self, error_msg: str) -> None:
        """Handle export error."""
        self.progress_widget.hide()
        self._show_error(qarg(self.tr("Export failed: %1"), error_msg))

    def _on_worker_finished(self) -> None:
        """Handle worker completion cleanup."""
        self.progress_widget.set_cancellable(True)
        self._update_available_formats()
        self.worker = None

    def _show_error(self, message: str) -> None:
        """Show error message."""
        QMessageBox.critical(self, self.tr("Export Error"), message)

    def _show_inline_error(self, message: str) -> None:
        """Show non-modal error message inside the view."""
        self.result_label.setText(qarg(self.tr("Export unavailable: %1"), message))
        self.result_label.setStyleSheet("color: red;")
        self.result_label.show()
        self.open_folder_btn.hide()

    def _open_folder(self) -> None:
        """Open the containing folder of the exported file."""
        output_path = self.output_path_edit.text()
        if output_path:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            path = Path(output_path)
            folder = path.parent if path.is_file() else path
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def cleanup(self) -> None:
        """Clean up running export worker."""
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle widget close event."""
        self.cleanup()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.doc_group.setTitle(self.tr("Select Documents"))
        self.select_all_btn.setText(self.tr("Select All"))
        self.select_none_btn.setText(self.tr("Deselect All"))
        self.format_label.setText(self.tr("Export Format:"))
        self.output_label.setText(self.tr("Output Path:"))
        self.browse_btn.setText(self.tr("Browse..."))
        self.preserve_structure_cb.setText(self.tr("Preserve folder structure (text documents only)"))
        self.allow_original_fallback_cb.setText(self.tr("Allow fallback to original content for untranslated chunks"))
        self.export_btn.setText(self.tr("Export"))
        self.open_folder_btn.setText(self.tr("Open Containing Folder"))

    def _tip_text(self) -> str:
        return self.tr(
            "Export translated documents. One document type per batch.\n"
            "By default, export requires all selected chunks to be translated."
        )
