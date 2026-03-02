"""Import view for adding documents to a book."""

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.documents.base import get_document_classes
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.utils import create_tip_label, translate_document_type
from context_aware_translation.ui.widgets import ProgressWidget
from context_aware_translation.ui.workers.import_worker import ImportWorker
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim


class ImportView(QWidget):
    """View for importing documents into a book."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        parent: QWidget | None = None,
        *,
        task_engine=None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self._task_engine = task_engine
        self.selected_path: Path | None = None
        self.worker: ImportWorker | None = None
        self._config_valid = False

        self._init_ui()
        self._check_config()
        self._load_documents()

    def _check_config(self) -> None:
        """Check config and show warnings, but never block import."""
        config = self.book_manager.get_book_config(self.book_id)

        if not config:
            self._show_config_warning(
                self.tr(
                    "No configuration found for this book.\n\n"
                    "You can still import documents now. Configure profiles before OCR/glossary/translation."
                )
            )
            return

        # Warn if step configs are missing endpoint profiles.
        # Import itself does not require these profiles.
        missing = []

        extractor = config.get("extractor_config", {})
        if not extractor or not extractor.get("endpoint_profile"):
            missing.append("Extractor")

        summarizer = config.get("summarizor_config", {})
        if not summarizer or not summarizer.get("endpoint_profile"):
            missing.append("Summarizer")

        glossary = config.get("glossary_config", {})
        if not glossary or not glossary.get("endpoint_profile"):
            missing.append("Glossary")

        translator = config.get("translator_config", {})
        if not translator or not translator.get("endpoint_profile"):
            missing.append("Translator")

        if missing:
            self._show_config_warning(
                qarg(
                    self.tr(
                        "Missing endpoint profile for: %1.\n\n"
                        "Import can continue, but OCR/glossary/translation for these steps will fail until configured:\n"
                        "1. Go to Profiles tab\n"
                        "2. Create an Endpoint Profile with your API settings\n"
                        "3. Create or edit a Config Profile and select the endpoint profile for each step\n"
                        "4. Edit this book and select the config profile"
                    ),
                    ", ".join(missing),
                )
            )
            return

        # Config is ready for full workflow.
        self._config_valid = True
        self.warning_label.hide()
        self._enable_controls(True)

    def _show_config_warning(self, message: str) -> None:
        """Show config warning without blocking import."""
        self._config_valid = True
        self.warning_label.setText(message)
        self.warning_label.show()
        self._enable_controls(True)

    def _has_valid_selected_type(self) -> bool:
        """Return True when the current type selection is importable."""
        if self.type_combo.count() == 0:
            return False

        selected_type = self.type_combo.currentData()
        if selected_type is None:
            return False

        # Guard against placeholder entries like "(No compatible type detected)".
        return not (isinstance(selected_type, str) and selected_type.startswith("("))

    def _enable_controls(self, enabled: bool) -> None:
        """Enable or disable import controls."""
        self.select_file_btn.setEnabled(enabled)
        self.select_folder_btn.setEnabled(enabled)

        has_selected_path = self.selected_path is not None
        has_valid_type = self._has_valid_selected_type()
        can_import = enabled and has_selected_path and has_valid_type
        self.import_btn.setEnabled(can_import)
        self.type_combo.setEnabled(can_import)

    def _has_claim_conflict(self, wanted: frozenset[ResourceClaim]) -> bool:
        if self._task_engine is None:
            return False
        return bool(self._task_engine.has_active_claims(self.book_id, wanted))

    def _init_ui(self) -> None:
        """Initialize the user interface."""
        layout = QVBoxLayout(self)

        # Warning label for config issues
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            "QLabel { background-color: #fef3c7; color: #92400e; "
            "padding: 12px; border: 1px solid #f59e0b; border-radius: 4px; }"
        )
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # === Import Section ===
        self.import_group = QGroupBox(self.tr("Import New Document"))
        import_layout = QVBoxLayout(self.import_group)

        # File/Folder selection buttons
        button_layout = QHBoxLayout()
        self.select_file_btn = QPushButton(self.tr("Select File"))
        self.select_file_btn.clicked.connect(self._select_file)
        self.select_folder_btn = QPushButton(self.tr("Select Folder"))
        self.select_folder_btn.clicked.connect(self._select_folder)
        button_layout.addWidget(self.select_file_btn)
        button_layout.addWidget(self.select_folder_btn)
        button_layout.addStretch()
        import_layout.addLayout(button_layout)

        # Selected path display
        self.path_label = QLabel(self.tr("No file or folder selected"))
        self.path_label.setWordWrap(True)
        import_layout.addWidget(self.path_label)

        # Document type section
        type_layout = QHBoxLayout()
        self.type_label = QLabel(self.tr("Document Type:"))
        self.type_combo = QComboBox()
        self.type_combo.setEnabled(False)
        type_layout.addWidget(self.type_label)
        type_layout.addWidget(self.type_combo)
        type_layout.addStretch()
        import_layout.addLayout(type_layout)

        # Import button
        self.import_btn = QPushButton(self.tr("Import"))
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._start_import)
        import_layout.addWidget(self.import_btn)

        # Progress widget
        self.progress_widget = ProgressWidget()
        self.progress_widget.cancelled.connect(self._cancel_import)
        self.progress_widget.hide()
        import_layout.addWidget(self.progress_widget)

        # Result message
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        import_layout.addWidget(self.result_label)

        layout.addWidget(self.import_group)

        # === Documents Section ===
        self.docs_group = QGroupBox(self.tr("Imported Documents"))
        docs_layout = QVBoxLayout(self.docs_group)

        # Refresh button
        refresh_layout = QHBoxLayout()
        self.refresh_docs_btn = QPushButton(self.tr("Refresh"))
        self.refresh_docs_btn.clicked.connect(self._load_documents)
        refresh_layout.addWidget(self.refresh_docs_btn)
        refresh_layout.addStretch()
        docs_layout.addLayout(refresh_layout)

        # Documents table
        self.docs_table = QTableWidget()
        self.docs_table.setColumnCount(6)
        self.docs_table.setHorizontalHeaderLabels(
            [
                self.tr("ID"),
                self.tr("Type"),
                self.tr("Sources"),
                self.tr("OCR"),
                self.tr("Glossary"),
                self.tr("Translation"),
            ]
        )
        self.docs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.docs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.docs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.docs_table.verticalHeader().setVisible(False)
        self.docs_table.itemSelectionChanged.connect(self._on_doc_selection_changed)
        docs_layout.addWidget(self.docs_table)

        # Document action buttons
        doc_actions_layout = QHBoxLayout()
        self.reset_doc_btn = QPushButton(self.tr("Reset Document"))
        self.reset_doc_btn.setToolTip(
            self.tr("Reset processing state for selected document and all documents after it")
        )
        self.reset_doc_btn.clicked.connect(self._on_reset_document)
        self.reset_doc_btn.setEnabled(False)
        doc_actions_layout.addWidget(self.reset_doc_btn)

        self.delete_doc_btn = QPushButton(self.tr("Delete Document"))
        self.delete_doc_btn.setToolTip(self.tr("Delete selected document and all documents after it"))
        self.delete_doc_btn.clicked.connect(self._on_delete_document)
        self.delete_doc_btn.setEnabled(False)
        doc_actions_layout.addWidget(self.delete_doc_btn)

        doc_actions_layout.addStretch()
        docs_layout.addLayout(doc_actions_layout)

        layout.addWidget(self.docs_group, 1)  # Give stretch to docs section

    def _select_file(self) -> None:
        """Open file dialog to select a file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Document File"),
            str(Path.home()),
            self.tr("All Files (*.*)"),
        )
        if file_path:
            self._handle_path_selection(Path(file_path))

    def _select_folder(self) -> None:
        """Open folder dialog to select a folder."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Document Folder"),
            str(Path.home()),
        )
        if folder_path:
            self._handle_path_selection(Path(folder_path))

    def _handle_path_selection(self, path: Path) -> None:
        """Handle path selection and auto-detect document type."""
        self.selected_path = path
        self.path_label.setText(qarg(self.tr("Selected: %1"), path))
        self.result_label.hide()

        # Auto-detect document type
        doc_classes = get_document_classes()
        matches = [cls for cls in doc_classes if cls.can_import(path)]

        self.type_combo.clear()
        self.type_combo.setEnabled(True)

        if len(matches) == 0:
            self.type_combo.addItem(self.tr("(No compatible type detected)"))
            self.type_combo.setEnabled(False)
            self.import_btn.setEnabled(False)
            QMessageBox.warning(
                self,
                self.tr("Import Error"),
                self.tr("Cannot import this path: no supported document type matches."),
            )
        elif len(matches) == 1:
            # Single match - auto-select
            doc_type = matches[0].document_type
            self.type_combo.addItem(translate_document_type(doc_type), doc_type)
            self.import_btn.setEnabled(self._config_valid)
        else:
            # Multiple matches - let user choose
            for cls in matches:
                doc_type = cls.document_type
                self.type_combo.addItem(translate_document_type(doc_type), doc_type)
            self.import_btn.setEnabled(self._config_valid)

    def _start_import(self) -> None:
        """Start the import operation in a background thread."""
        if self.worker and self.worker.isRunning():
            return

        if not self.selected_path:
            return

        if self._has_claim_conflict(frozenset({ResourceClaim("doc", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE)})):
            QMessageBox.warning(
                self,
                self.tr("Import Unavailable"),
                self.tr("Cannot import while other tasks are modifying documents."),
            )
            return

        # Import is intentionally allowed even if workflow endpoint profiles are incomplete.

        # Get selected document type
        document_type = self.type_combo.currentData()
        if not document_type or document_type.startswith("("):
            QMessageBox.warning(self, self.tr("Import Error"), self.tr("Please select a valid document type."))
            return

        # Disable controls
        self.select_file_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(False)
        self.import_btn.setEnabled(False)
        self.type_combo.setEnabled(False)
        self.result_label.hide()

        # Show progress
        self.progress_widget.show()
        self.progress_widget.reset()
        self.progress_widget.set_cancellable(True)
        self.progress_widget.message_label.setText(self.tr("Importing..."))

        # Create and start worker
        self.worker = ImportWorker(
            self.book_manager,
            self.book_id,
            self.selected_path,
            document_type,
        )
        self.worker.finished_success.connect(self._on_import_success)
        self.worker.cancelled.connect(self._on_import_cancelled)
        self.worker.error.connect(self._on_import_error)
        self.worker.progress.connect(self._on_import_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _cancel_import(self) -> None:
        """Cancel running import operation."""
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.progress_widget.message_label.setText(self.tr("Cancelling..."))
            self.progress_widget.set_cancellable(False)

    def _on_import_success(self, result: dict) -> None:
        """Handle successful import."""
        imported = result.get("imported", 0)
        skipped = result.get("skipped", 0)

        message = qarg(self.tr("Import completed: %1 imported, %2 skipped"), imported, skipped)
        self.result_label.setText(message)
        self.result_label.setStyleSheet("color: green;")
        self.result_label.show()

        # Refresh documents list
        self._load_documents()

    def _on_import_error(self, error_msg: str) -> None:
        """Handle import error."""
        self.result_label.setText(qarg(self.tr("Import failed: %1"), error_msg))
        self.result_label.setStyleSheet("color: red;")
        self.result_label.show()

        QMessageBox.critical(self, self.tr("Import Error"), qarg(self.tr("Failed to import document:\n%1"), error_msg))

    def _on_import_cancelled(self) -> None:
        """Handle cancelled import."""
        self.result_label.setText(self.tr("Import cancelled."))
        self.result_label.setStyleSheet("color: #b45309;")
        self.result_label.show()

    def _on_import_progress(self, current: int, total: int, message: str) -> None:
        """Handle import progress updates from worker."""
        translated_message = self.tr(message) if message else ""
        self.progress_widget.set_progress(current, total, translated_message)

    def _on_worker_finished(self) -> None:
        """Clean up after worker finishes."""
        self.progress_widget.hide()
        self.progress_widget.set_cancellable(True)
        self._enable_controls(self._config_valid)
        self.worker = None

    def _load_documents(self) -> None:
        """Load and display documents with their status."""
        try:
            db_path = self.book_manager.get_book_db_path(self.book_id)
            db = SQLiteBookDB(db_path)
            try:
                repo = DocumentRepository(db)
                documents = repo.get_documents_with_status()
            finally:
                db.close()

            self.docs_table.setRowCount(len(documents))

            for row, doc in enumerate(documents):
                # ID
                id_item = QTableWidgetItem(str(doc["document_id"]))
                id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.docs_table.setItem(row, 0, id_item)

                # Type
                type_item = QTableWidgetItem(translate_document_type(doc.get("document_type", "unknown")))
                self.docs_table.setItem(row, 1, type_item)

                # Sources count
                sources_item = QTableWidgetItem(str(doc["total_sources"]))
                sources_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.docs_table.setItem(row, 2, sources_item)

                # OCR status
                ocr_key, ocr_text = self._get_ocr_status(doc)
                ocr_item = QTableWidgetItem(ocr_text)
                ocr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._set_status_color(ocr_item, ocr_key)
                self.docs_table.setItem(row, 3, ocr_item)

                # Glossary status
                glossary_key, glossary_text = self._get_glossary_status(doc)
                glossary_item = QTableWidgetItem(glossary_text)
                glossary_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._set_status_color(glossary_item, glossary_key)
                self.docs_table.setItem(row, 4, glossary_item)

                # Translation status
                translation_key, translation_text = self._get_translation_status(doc)
                translation_item = QTableWidgetItem(translation_text)
                translation_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._set_status_color(translation_item, translation_key)
                self.docs_table.setItem(row, 5, translation_item)

        except Exception as e:
            QMessageBox.warning(self, self.tr("Error"), qarg(self.tr("Failed to load documents: %1"), e))

    def _get_ocr_status(self, doc: dict) -> tuple[str, str]:
        """Get OCR status key and display string for a document."""
        if doc["ocr_pending"] > 0:
            return "pending", qarg(self.tr("Pending (%1)"), doc["ocr_pending"])
        elif doc["ocr_completed"] > 0:
            return "complete", self.tr("Complete")
        else:
            return "na", self.tr("N/A")

    def _get_glossary_status(self, doc: dict) -> tuple[str, str]:
        """Get glossary building status key and display string for a document."""
        total = doc["total_chunks"]
        if total == 0:
            return "not_started", self.tr("Not Started")

        extracted = doc["chunks_extracted"]
        mapped = doc["chunks_mapped"]

        if extracted == total and mapped == total:
            return "complete", self.tr("Complete")
        elif extracted > 0 or mapped > 0:
            return "in_progress", qarg(self.tr("In Progress (%1/%2)"), mapped, total)
        else:
            return "not_started", self.tr("Not Started")

    def _get_translation_status(self, doc: dict) -> tuple[str, str]:
        """Get translation status key and display string for a document."""
        total = doc["total_chunks"]
        if total == 0:
            return "not_started", self.tr("Not Started")

        translated = doc["chunks_translated"]
        if translated == total:
            return "complete", self.tr("Complete")
        elif translated > 0:
            return "in_progress", qarg(self.tr("In Progress (%1/%2)"), translated, total)
        else:
            return "not_started", self.tr("Not Started")

    def _set_status_color(self, item: QTableWidgetItem, status_key: str) -> None:
        """Set background color based on status key."""
        if status_key == "complete":
            item.setBackground(Qt.GlobalColor.green)
        elif status_key in ("pending", "in_progress"):
            item.setBackground(Qt.GlobalColor.yellow)
        elif status_key == "not_started":
            item.setBackground(Qt.GlobalColor.lightGray)
        # "na" gets no special color

    def _on_doc_selection_changed(self) -> None:
        """Enable/disable document action buttons based on selection."""
        has_selection = len(self.docs_table.selectedItems()) > 0
        self.reset_doc_btn.setEnabled(has_selection)
        self.delete_doc_btn.setEnabled(has_selection)

    def _get_selected_document_id(self) -> int | None:
        """Get the document_id of the selected row."""
        selected_rows = self.docs_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        id_item = self.docs_table.item(row, 0)
        if id_item:
            return int(id_item.text())
        return None

    def _on_reset_document(self) -> None:
        """Reset selected document and all documents after it (stack-based)."""
        doc_id = self._get_selected_document_id()
        if doc_id is None:
            return

        if self._has_claim_conflict(
            frozenset(
                {
                    ResourceClaim("doc", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                    ResourceClaim("glossary_state", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                    ResourceClaim("context_tree", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                    ResourceClaim("ocr", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                }
            )
        ):
            QMessageBox.warning(
                self,
                self.tr("Reset Unavailable"),
                self.tr("Cannot reset documents while other tasks are active."),
            )
            return

        reply = QMessageBox.warning(
            self,
            self.tr("Reset Document"),
            qarg(
                self.tr(
                    "This will reset Document %1 and all documents added after it.\n"
                    "All glossary data, translations, and OCR processing state for affected "
                    "documents will be cleared.\n\n"
                    "The documents themselves will remain \u2014 you can rebuild the glossary afterwards.\n\n"
                    "Do you want to continue?"
                ),
                doc_id,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            db_path = self.book_manager.get_book_db_path(self.book_id)
            ct_path = self.book_manager.get_book_context_tree_path(self.book_id)
            db = SQLiteBookDB(db_path)
            try:
                repo = DocumentRepository(db)
                result = repo.reset_document_stack(doc_id, context_tree_db_path=ct_path)
            finally:
                db.close()

            affected = result.get("affected_document_ids", [])
            QMessageBox.information(
                self,
                self.tr("Reset Complete"),
                qarg(
                    self.tr("Reset %1 document(s): %2\nDeleted %3 chunks, pruned %4 terms, deleted %5 terms."),
                    len(affected),
                    affected,
                    result.get("deleted_chunks", 0),
                    result.get("pruned_terms", 0),
                    result.get("deleted_terms", 0),
                ),
            )

            self._load_documents()

        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to reset document: %1"), e))

    def _on_delete_document(self) -> None:
        """Delete selected document and all documents after it (stack-based)."""
        doc_id = self._get_selected_document_id()
        if doc_id is None:
            return

        if self._has_claim_conflict(
            frozenset(
                {
                    ResourceClaim("doc", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                    ResourceClaim("glossary_state", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                    ResourceClaim("context_tree", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                    ResourceClaim("ocr", self.book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                }
            )
        ):
            QMessageBox.warning(
                self,
                self.tr("Delete Unavailable"),
                self.tr("Cannot delete documents while other tasks are active."),
            )
            return

        reply = QMessageBox.warning(
            self,
            self.tr("Delete Document"),
            qarg(
                self.tr(
                    "This will PERMANENTLY DELETE Document %1 and all documents added after it.\n"
                    "All sources, glossary data, translations, and OCR results for affected "
                    "documents will be removed.\n\n"
                    "This action cannot be undone.\n\n"
                    "Do you want to continue?"
                ),
                doc_id,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            db_path = self.book_manager.get_book_db_path(self.book_id)
            ct_path = self.book_manager.get_book_context_tree_path(self.book_id)
            db = SQLiteBookDB(db_path)
            try:
                repo = DocumentRepository(db)
                result = repo.delete_documents_stack(doc_id, context_tree_db_path=ct_path)
            finally:
                db.close()

            affected = result.get("affected_document_ids", [])
            QMessageBox.information(
                self,
                self.tr("Delete Complete"),
                qarg(
                    self.tr("Deleted %1 document(s): %2\nRemoved %3 sources, %4 chunks, deleted %5 terms."),
                    result.get("deleted_documents", 0),
                    affected,
                    result.get("deleted_sources", 0),
                    result.get("deleted_chunks", 0),
                    result.get("deleted_terms", 0),
                ),
            )

            self._load_documents()

        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to delete document: %1"), e))

    def refresh(self) -> None:
        """Refresh the view and re-check config."""
        self._check_config()
        self._load_documents()

    def cleanup(self) -> None:
        """Clean up running import worker."""
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
        self.import_group.setTitle(self.tr("Import New Document"))
        self.select_file_btn.setText(self.tr("Select File"))
        self.select_folder_btn.setText(self.tr("Select Folder"))
        if self.selected_path is None:
            self.path_label.setText(self.tr("No file or folder selected"))
        else:
            self.path_label.setText(qarg(self.tr("Selected: %1"), self.selected_path))
        self.type_label.setText(self.tr("Document Type:"))
        self.import_btn.setText(self.tr("Import"))
        self.docs_group.setTitle(self.tr("Imported Documents"))
        self.refresh_docs_btn.setText(self.tr("Refresh"))
        self.docs_table.setHorizontalHeaderLabels(
            [
                self.tr("ID"),
                self.tr("Type"),
                self.tr("Sources"),
                self.tr("OCR"),
                self.tr("Glossary"),
                self.tr("Translation"),
            ]
        )
        self.reset_doc_btn.setText(self.tr("Reset Document"))
        self.reset_doc_btn.setToolTip(
            self.tr("Reset processing state for selected document and all documents after it")
        )
        self.delete_doc_btn.setText(self.tr("Delete Document"))
        self.delete_doc_btn.setToolTip(self.tr("Delete selected document and all documents after it"))

    def _tip_text(self) -> str:
        return self.tr(
            "Import in intended reading order: earlier imports shape later summaries and translation context. "
            "For OCR-required documents, incomplete earlier OCR blocks later glossary/translation until fixed."
        )
