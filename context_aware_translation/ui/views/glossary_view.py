"""Glossary editor view for managing translation terms."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.glossary_io import import_glossary
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.context_tree_db import ContextTreeDB
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.workflow.tasks.glossary_preflight import compute_glossary_preflight
from context_aware_translation.workflow.tasks.models import TaskAction

if TYPE_CHECKING:
    from ..tasks.qt_task_engine import TaskEngine

from ..i18n import qarg, translate_progress_message
from ..models.term_model import TermTableModel
from ..tasks.task_console import TaskConsole
from ..utils import create_tip_label, translate_document_type
from ..widgets import ProgressWidget
from ..workers.glossary_worker import (
    ExportGlossaryWorker,
    TranslateGlossaryWorker,
)


class _TranslationDelegate(QStyledItemDelegate):
    """Delegate that provides a larger text editor for the Translation column."""

    _EDITOR_MIN_HEIGHT = 80

    def createEditor(self, parent, _option, _index):
        editor = QTextEdit(parent)
        editor.setAcceptRichText(False)
        editor.setMinimumHeight(self._EDITOR_MIN_HEIGHT)
        return editor

    def setEditorData(self, editor, index):
        text = index.data(Qt.ItemDataRole.EditRole) or ""
        editor.setPlainText(text)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), self._EDITOR_MIN_HEIGHT))

    def updateEditorGeometry(self, editor, option, _index):
        rect = option.rect
        editor.setGeometry(rect.x(), rect.y(), rect.width(), max(rect.height(), self._EDITOR_MIN_HEIGHT))


class GlossaryView(QWidget):
    """Glossary editor view with filtering, sorting, and bulk operations."""

    glossary_changed = Signal()

    def __init__(self, book_manager: BookManager, book_id: str, task_engine: "TaskEngine", parent: QWidget | None = None) -> None:
        """Initialize the glossary view.

        Args:
            book_manager: Book manager instance
            book_id: Book ID to manage glossary for
            task_engine: Task engine for glossary_extraction tasks
            parent: Parent widget
        """
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self._task_engine = task_engine

        # Get database and repository
        db_path = self.book_manager.get_book_db_path(book_id)
        self.term_db = SQLiteBookDB(db_path)
        self.document_repo = DocumentRepository(self.term_db)

        # Workers (build glossary and review now handled via task engine)
        self._translate_worker: TranslateGlossaryWorker | None = None
        self._export_worker: ExportGlossaryWorker | None = None

        self._completed_task_ids: set[str] = set()

        self._setup_ui()
        self._update_stats()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # Toolbar row 1: Search, filter, build
        toolbar_layout = QHBoxLayout()

        # Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Search terms..."))
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self.search_input)

        # Filter dropdown - use data-based approach for i18n safety
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(self.tr("All"), "all")
        self.filter_combo.addItem(self.tr("Unreviewed"), "unreviewed")
        self.filter_combo.addItem(self.tr("Ignored"), "ignored")
        self.filter_combo.addItem(self.tr("Translated"), "translated")
        self.filter_combo.addItem(self.tr("Untranslated"), "untranslated")
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar_layout.addWidget(self.filter_combo)

        # Document selector for Build Glossary
        self.build_until_label = QLabel(self.tr("Build until:"))
        toolbar_layout.addWidget(self.build_until_label)
        self.doc_combo = QComboBox()
        self.doc_combo.addItem(self.tr("All Documents"), None)
        self._populate_documents()
        self.doc_combo.currentIndexChanged.connect(self._on_build_selection_changed)
        toolbar_layout.addWidget(self.doc_combo)

        # Build Glossary button
        self.build_button = QPushButton(self.tr("Build Glossary"))
        self.build_button.clicked.connect(self._on_build_glossary)
        toolbar_layout.addWidget(self.build_button)

        # Update build button state based on pending documents
        self._update_build_button_state()

        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        # Toolbar row 2: Actions
        actions_layout = QHBoxLayout()

        # Translate untranslated terms button
        self.translate_button = QPushButton(self.tr("Translate Untranslated"))
        self.translate_button.clicked.connect(self._on_translate_glossary)
        actions_layout.addWidget(self.translate_button)

        # Review terms button
        self.review_button = QPushButton(self.tr("Review Terms"))
        self.review_button.clicked.connect(self._on_review_terms)
        actions_layout.addWidget(self.review_button)

        # Filter rare terms button
        self.filter_rare_button = QPushButton(self.tr("Filter Rare"))
        self.filter_rare_button.clicked.connect(self._on_filter_rare)
        actions_layout.addWidget(self.filter_rare_button)

        # Bulk Actions menu
        self.bulk_menu = QMenu(self.tr("Bulk Actions"), self)
        self.bulk_mark_reviewed_action = self.bulk_menu.addAction(self.tr("Mark Reviewed"), self._on_mark_reviewed)
        self.bulk_unmark_reviewed_action = self.bulk_menu.addAction(
            self.tr("Unmark Reviewed"), self._on_unmark_reviewed
        )
        self.bulk_mark_ignored_action = self.bulk_menu.addAction(self.tr("Mark Ignored"), self._on_mark_ignored)
        self.bulk_unmark_ignored_action = self.bulk_menu.addAction(self.tr("Unmark Ignored"), self._on_unmark_ignored)
        self.bulk_delete_action = self.bulk_menu.addAction(self.tr("Delete Selected"), self._on_delete_selected)

        # Refresh button
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.clicked.connect(self._on_refresh)
        actions_layout.addWidget(self.refresh_button)

        # Export Glossary button
        self.export_button = QPushButton(self.tr("Export Glossary"))
        self.export_button.clicked.connect(self._on_export_glossary)
        actions_layout.addWidget(self.export_button)

        # Import Glossary button
        self.import_button = QPushButton(self.tr("Import Glossary"))
        self.import_button.clicked.connect(self._on_import_glossary)
        actions_layout.addWidget(self.import_button)
        self._apply_button_tooltips()

        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        # Progress widget (hidden by default)
        self.progress_widget = ProgressWidget()
        self.progress_widget.cancelled.connect(self._on_cancel_operation)
        self.progress_widget.hide()
        layout.addWidget(self.progress_widget)

        # Task console for glossary_extraction engine tasks
        self.task_console = TaskConsole(
            task_engine=self._task_engine,
            book_id=self.book_id,
            task_type="glossary_extraction",
            parent=self,
        )
        layout.addWidget(self.task_console)
        self.task_console.console_refreshed.connect(self._on_task_console_refreshed)

        # Task console for glossary_review engine tasks
        self.review_task_console = TaskConsole(
            task_engine=self._task_engine,
            book_id=self.book_id,
            task_type="glossary_review",
            parent=self,
        )
        layout.addWidget(self.review_task_console)
        self.review_task_console.console_refreshed.connect(self._on_review_task_console_refreshed)

        # Table view
        self.table_view = QTableView()
        self.table_model = TermTableModel(self.term_db)
        self.table_view.setModel(self.table_model)

        # Table settings
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        # Columns: Term, Translation, Description, Created, Occurrences, Votes, Ignored, Reviewed
        self.table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Term
        self.table_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Translation
        self.table_view.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Description

        # Use a larger text editor for the Translation column
        self.table_view.setItemDelegateForColumn(1, _TranslationDelegate(self.table_view))

        # Connect sorting signal
        self.table_view.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)

        # Context menu
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self.table_view)

        # Status bar
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

    def _on_task_console_refreshed(self) -> None:
        """Handle task console refresh — sync term DB, table, stats, and button state."""
        from context_aware_translation.workflow.tasks.models import (
            STATUS_COMPLETED,
            STATUS_COMPLETED_WITH_ERRORS,
            TERMINAL_TASK_STATUSES,
        )

        self.term_db.refresh()
        self.table_model.refresh()
        self._update_stats()
        self._refresh_document_selector()

        # Emit glossary_changed only on success-like completions (not cancelled/failed)
        _SUCCESS_TERMINAL = {STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS}
        for vm in self.task_console.task_vms():
            if vm.status in TERMINAL_TASK_STATUSES and vm.task_id not in self._completed_task_ids:
                self._completed_task_ids.add(vm.task_id)
                if vm.status in _SUCCESS_TERMINAL:
                    self.glossary_changed.emit()

    def _on_review_task_console_refreshed(self) -> None:
        """Handle review task console refresh — sync term DB, table, stats, and button state."""
        from context_aware_translation.workflow.tasks.models import (
            STATUS_COMPLETED,
            STATUS_COMPLETED_WITH_ERRORS,
            TERMINAL_TASK_STATUSES,
        )

        self.term_db.refresh()
        self.table_model.refresh()
        self._update_stats()

        # Emit glossary_changed only on success-like completions (not cancelled/failed)
        _SUCCESS_TERMINAL = {STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS}
        for vm in self.review_task_console.task_vms():
            if vm.status in TERMINAL_TASK_STATUSES and vm.task_id not in self._completed_task_ids:
                self._completed_task_ids.add(vm.task_id)
                if vm.status in _SUCCESS_TERMINAL:
                    self.glossary_changed.emit()

        self._update_review_button_state()

    def _update_stats(self) -> None:
        """Update the status bar with term statistics."""
        stats = self.term_db.get_term_stats()
        status_text = qarg(
            self.tr(
                "Showing %1 terms | Total: %2 | Unignored: %3 | Unignored+Reviewed: %4 | Reviewed: %5 | Translated: %6"
            ),
            self.table_model.rowCount(),
            stats["total"],
            stats["unignored"],
            stats["unignored_reviewed"],
            stats["reviewed"],
            stats["translated"],
        )
        self.status_label.setText(status_text)
        self._update_action_button_states()

    def _update_action_button_states(self) -> None:
        """Keep glossary term-table actions available whenever controls are enabled."""
        self.translate_button.setEnabled(True)
        self.filter_rare_button.setEnabled(True)
        self._update_review_button_state()

    def _update_review_button_state(self) -> None:
        """Enable/disable review button based on engine preflight."""
        engine_decision = self._task_engine.preflight(
            "glossary_review",
            self.book_id,
            {},
            TaskAction.RUN,
        )
        if engine_decision.allowed:
            self.review_button.setEnabled(True)
            self.review_button.setToolTip(self.tr("Run an LLM review pass on unreviewed glossary terms."))
        else:
            self.review_button.setEnabled(False)
            self.review_button.setToolTip(
                qarg(self.tr("Review unavailable: %1"), engine_decision.reason or engine_decision.code or "")
            )

    def _on_search_changed(self, text: str) -> None:
        """Handle search text change.

        Args:
            text: Search text
        """
        self.table_model.set_search(text)
        self._update_stats()

    def _on_filter_changed(self, _index: int) -> None:
        """Handle filter change.

        Args:
            _index: Combo box index (unused, we use currentData)
        """
        filter_value = self.filter_combo.currentData()
        self.table_model.set_filter(filter_value or "all")
        self._update_stats()

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        """Handle sort order change.

        Args:
            column: Column index
            order: Sort order
        """
        descending = order == Qt.SortOrder.DescendingOrder
        self.table_model.set_sort(column, descending)

    def _on_refresh(self) -> None:
        """Handle refresh button click."""
        self.table_model.refresh()
        self._update_stats()

    def _confirm_export_glossary(self) -> bool | None:
        """Return skip_context selection, or None if user cancelled."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr("Export Glossary"))
        msg_box.setText(
            self.tr(
                "By default, this export will summarize glossary descriptions before writing the file.\n"
                "For large glossaries, this may take some time.\n\n"
                'Enable "Skip context" below to use only the first description per term.\n\n'
                "Continue?"
            )
        )
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        skip_context_cb = QCheckBox(self.tr("Skip context (use first description only)"))
        skip_context_cb.setChecked(False)
        msg_box.setCheckBox(skip_context_cb)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return None
        return skip_context_cb.isChecked()

    def _on_export_glossary(self) -> None:
        if self._export_worker and self._export_worker.isRunning():
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Glossary"),
            "",
            self.tr("JSON Files (*.json)"),
        )
        if not file_path:
            return

        skip_context = self._confirm_export_glossary()
        if skip_context is None:
            return

        self._export_worker = ExportGlossaryWorker(
            self.book_manager,
            self.book_id,
            Path(file_path),
            skip_context=skip_context,
        )
        self._export_worker.progress.connect(self._on_progress)
        self._export_worker.finished_success.connect(self._on_export_finished)
        self._export_worker.cancelled.connect(self._on_operation_cancelled)
        self._export_worker.error.connect(self._on_operation_error)
        self._export_worker.finished.connect(self._on_export_worker_finished)

        self.progress_widget.reset()
        self.progress_widget.set_cancellable(True)
        self.progress_widget.show()
        self._set_controls_enabled(False)

        self._export_worker.start()

    def _on_import_glossary(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Glossary"),
            "",
            self.tr("JSON Files (*.json)"),
        )
        if not file_path:
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr("Import Glossary"))
        msg_box.setText(
            self.tr(
                "This will REPLACE all existing glossary terms with the imported data.\n\n"
                "This action cannot be undone. Continue?"
            )
        )
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        include_translations_cb = QCheckBox(self.tr("Include translations"))
        include_translations_cb.setChecked(True)
        msg_box.setCheckBox(include_translations_cb)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        include_translations = include_translations_cb.isChecked()

        try:
            context_tree_db_path = self.book_manager.get_book_context_tree_path(self.book_id)
            context_tree_db = ContextTreeDB(context_tree_db_path)
            try:
                count = import_glossary(
                    self.term_db,
                    context_tree_db,
                    Path(file_path),
                    include_translations=include_translations,
                )
            finally:
                context_tree_db.close()

            self.term_db.refresh()
            self.table_model.refresh()
            self._update_stats()
            self.glossary_changed.emit()

            QMessageBox.information(
                self,
                self.tr("Import Complete"),
                qarg(self.tr("Imported %1 term(s)."), count),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Import Failed"),
                qarg(self.tr("An error occurred:\n\n%1"), str(e)),
            )

    def _populate_documents(self) -> None:
        """Populate document selector with documents pending glossary building."""
        documents = self.document_repo.list_documents_pending_glossary()
        documents.sort(key=lambda d: d["document_id"])
        for doc in documents:
            doc_id = doc["document_id"]
            doc_type = translate_document_type(doc.get("document_type", "unknown"))
            self.doc_combo.addItem(qarg(self.tr("Document %1 (%2)"), doc_id, doc_type), doc_id)

    def _sync_build_selector_from_db(self) -> None:
        """Refresh doc_combo items from current DB state without changing selection."""
        self._refresh_document_selector()

    def _format_build_block_reason(self, blocking_doc_ids: list[int]) -> str:
        joined_ids = ", ".join(str(doc_id) for doc_id in blocking_doc_ids)
        return qarg(
            self.tr("Blocked: earlier OCR-required document(s) pending OCR: %1"),
            joined_ids,
        )

    def _format_engine_preflight_denial(self, decision) -> str:
        return qarg(
            self.tr("Task engine blocked: %1"),
            decision.reason or decision.code,
        )

    def _format_submit_error(self, exc: Exception) -> str:
        return qarg(self.tr("Submit error: %1"), str(exc))

    def _update_build_button_state(self) -> None:
        """Enable/disable build button based on pending documents and engine preflight."""
        pending_ids = self._get_pending_document_ids()
        has_pending = len(pending_ids) > 0
        if not has_pending:
            self.build_button.setEnabled(False)
            self.doc_combo.setEnabled(False)
            return

        selected_cutoff = self.doc_combo.currentData()
        selected_cutoff_int = int(selected_cutoff) if selected_cutoff is not None else None

        preflight = compute_glossary_preflight(pending_ids, selected_cutoff_int, self.document_repo)
        if preflight.is_blocked:
            self.build_button.setEnabled(False)
            self.build_button.setToolTip(self._format_build_block_reason(preflight.blocking_ocr_doc_ids))
            self.doc_combo.setEnabled(True)
            return

        # Check engine preflight for claim conflicts
        engine_decision = self._task_engine.preflight(
            "glossary_extraction",
            self.book_id,
            {"document_ids": preflight.target_doc_ids, "cutoff_doc_id": preflight.cutoff_doc_id},
            TaskAction.RUN,
        )
        if not engine_decision.allowed:
            self.build_button.setEnabled(False)
            self.build_button.setToolTip(self._format_engine_preflight_denial(engine_decision))
            self.doc_combo.setEnabled(True)
            return

        self.build_button.setEnabled(True)
        self.build_button.setToolTip(
            self.tr("Build glossary terms from pending documents up to the selected document.")
        )
        self.doc_combo.setEnabled(True)

    def _on_build_selection_changed(self, _index: int) -> None:
        """Re-evaluate glossary build availability when build target changes."""
        self._update_build_button_state()

    def _get_pending_document_ids(self) -> list[int]:
        """Return pending glossary document IDs currently shown in the selector."""
        pending_ids: list[int] = []
        for i in range(1, self.doc_combo.count()):  # skip index 0 ("All Documents")
            did = self.doc_combo.itemData(i)
            if did is not None:
                pending_ids.append(int(did))
        pending_ids.sort()
        return pending_ids

    def _get_selected_document_ids(self) -> list[int]:
        """Get pending document IDs up to and including the selected document (stack ordering)."""
        pending_ids = self._get_pending_document_ids()
        selected_id = self.doc_combo.currentData()
        if selected_id is None:
            return pending_ids
        return [doc_id for doc_id in pending_ids if doc_id <= int(selected_id)]

    def _on_build_glossary(self) -> None:
        """Handle build glossary button click."""
        self.term_db.refresh()
        self._sync_build_selector_from_db()

        pending_ids = self._get_pending_document_ids()
        if not pending_ids:
            QMessageBox.information(
                self,
                self.tr("No Pending Documents"),
                self.tr("No documents are pending glossary build."),
            )
            return

        selected_cutoff = self.doc_combo.currentData()
        selected_cutoff_int = int(selected_cutoff) if selected_cutoff is not None else None
        document_ids = self._get_selected_document_ids()

        preflight = compute_glossary_preflight(pending_ids, selected_cutoff_int, self.document_repo)
        if preflight.is_blocked:
            joined_ids = ", ".join(str(doc_id) for doc_id in preflight.blocking_ocr_doc_ids)
            QMessageBox.warning(
                self,
                self.tr("OCR Not Complete"),
                qarg(
                    self.tr(
                        "Cannot build glossary yet because earlier OCR-required document(s) are still pending OCR: %1.\n\n"
                        "Please complete OCR in import order before building later documents."
                    ),
                    joined_ids,
                ),
            )
            return

        selected_id = self.doc_combo.currentData()
        if selected_id is None:
            doc_label = self.tr("all pending documents")
        else:
            doc_label = qarg(self.tr("all pending documents up to and including document %1"), selected_id)

        reply = QMessageBox.question(
            self,
            self.tr("Build Glossary"),
            qarg(
                self.tr(
                    "This will extract terms and build occurrence mapping from %1.\n"
                    'It will not translate glossary terms; use "Translate Untranslated" afterwards.\n\n'
                    "Continue?"
                ),
                doc_label,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._task_engine.submit(
                "glossary_extraction",
                self.book_id,
                document_ids=document_ids,
                cutoff_doc_id=preflight.cutoff_doc_id,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.tr("Submit Failed"),
                self._format_submit_error(exc),
            )
            return

        self._update_build_button_state()

    def _on_translate_glossary(self) -> None:
        """Handle re-translate button click."""
        if self._translate_worker and self._translate_worker.isRunning():
            return

        reply = QMessageBox.question(
            self,
            self.tr("Translate Untranslated"),
            self.tr("This will translate all untranslated terms.\nIgnored terms will be skipped.\n\nContinue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Start worker
        self._translate_worker = TranslateGlossaryWorker(self.book_manager, self.book_id)
        self._translate_worker.progress.connect(self._on_progress)
        self._translate_worker.finished_success.connect(self._on_translate_finished)
        self._translate_worker.cancelled.connect(self._on_operation_cancelled)
        self._translate_worker.error.connect(self._on_operation_error)
        self._translate_worker.finished.connect(self._on_translate_worker_finished)

        # Show progress
        self.progress_widget.reset()
        self.progress_widget.set_cancellable(True)
        self.progress_widget.show()

        # Disable controls
        self._set_controls_enabled(False)

        self._translate_worker.start()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        """Handle progress update.

        Args:
            current: Current progress
            total: Total items
            message: Progress message
        """
        translated_message = translate_progress_message(message)
        self.progress_widget.set_progress(current, total, translated_message)

    def _refresh_document_selector(self) -> None:
        """Refresh the document selector with current pending documents."""
        current_data = self.doc_combo.currentData()
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()
        self.doc_combo.addItem(self.tr("All Documents"), None)
        self._populate_documents()
        # Try to restore previous selection
        if current_data is not None:
            for i in range(self.doc_combo.count()):
                if self.doc_combo.itemData(i) == current_data:
                    self.doc_combo.setCurrentIndex(i)
                    break
        self.doc_combo.blockSignals(False)
        self._update_build_button_state()

    def refresh(self) -> None:
        """Refresh the view with current data.

        Called when switching to this tab to ensure document list and stats are up-to-date.
        """
        self.term_db.refresh()
        self._refresh_document_selector()
        self.table_model.refresh()
        self._update_stats()

    def _on_translate_finished(self, _result) -> None:
        """Handle translate glossary completion."""
        self.progress_widget.hide()
        self._set_controls_enabled(True)

        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Translation Complete"),
            self.tr("Untranslated terms have been translated successfully."),
        )

    def _on_review_terms(self) -> None:
        """Handle review terms button click — submit a glossary_review engine task."""
        engine_decision = self._task_engine.preflight(
            "glossary_review",
            self.book_id,
            {},
            TaskAction.RUN,
        )
        if not engine_decision.allowed:
            QMessageBox.warning(
                self,
                self.tr("Review Unavailable"),
                qarg(
                    self.tr("Cannot start review: %1"),
                    engine_decision.reason or engine_decision.code or self.tr("unknown reason"),
                ),
            )
            return

        reply = QMessageBox.question(
            self,
            self.tr("Review Terms"),
            self.tr("This will review all unreviewed terms using LLM. Continue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._task_engine.submit("glossary_review", self.book_id)
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.tr("Submit Failed"),
                self._format_submit_error(exc),
            )
            return

        self._update_review_button_state()

    def _on_export_finished(self, result: object) -> None:
        """Handle glossary export completion."""
        self.progress_widget.hide()
        self._set_controls_enabled(True)

        count = result["count"] if isinstance(result, dict) and "count" in result else 0
        QMessageBox.information(
            self,
            self.tr("Export Complete"),
            qarg(self.tr("Exported %1 term(s) to file."), count),
        )

    def _on_operation_error(self, error_message: str) -> None:
        """Handle operation error.

        Args:
            error_message: Error message
        """
        self.progress_widget.hide()
        self._set_controls_enabled(True)

        QMessageBox.critical(
            self,
            self.tr("Operation Failed"),
            qarg(self.tr("An error occurred:\n\n%1"), error_message),
        )

    def _on_cancel_operation(self) -> None:
        """Handle operation cancellation."""
        # Try to cancel any running worker
        if self._translate_worker and self._translate_worker.isRunning():
            self._translate_worker.requestInterruption()
        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.requestInterruption()
        self.progress_widget.message_label.setText(self.tr("Cancelling..."))
        self.progress_widget.set_cancellable(False)

    def _on_operation_cancelled(self) -> None:
        """Handle user cancellation."""
        self.progress_widget.hide()
        self._set_controls_enabled(True)
        QMessageBox.information(self, self.tr("Cancelled"), self.tr("Operation cancelled."))

    def _on_translate_worker_finished(self) -> None:
        """Reset translate worker pointer."""
        self.progress_widget.set_cancellable(True)
        self._translate_worker = None

    def _on_export_worker_finished(self) -> None:
        """Reset export worker pointer."""
        self.progress_widget.set_cancellable(True)
        self._export_worker = None

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable controls.

        Args:
            enabled: Enable controls if True
        """
        self.search_input.setEnabled(enabled)
        self.filter_combo.setEnabled(enabled)
        self.translate_button.setEnabled(enabled)
        self.filter_rare_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.table_view.setEnabled(enabled)
        if enabled:
            self._update_build_button_state()
            self._update_action_button_states()
        else:
            self.build_button.setEnabled(False)
            self.doc_combo.setEnabled(False)
            self.translate_button.setEnabled(False)
            self.filter_rare_button.setEnabled(False)

    def _get_selected_keys(self) -> list[str]:
        """Get keys of selected terms.

        Returns:
            List of term keys
        """
        selection_model = self.table_view.selectionModel()
        if not selection_model:
            return []

        selected_rows = [index.row() for index in selection_model.selectedRows()]
        return self.table_model.get_selected_keys(selected_rows)

    def _on_mark_reviewed(self) -> None:
        """Mark selected terms as reviewed."""
        keys = self._get_selected_keys()
        if not keys:
            QMessageBox.warning(self, self.tr("No Selection"), self.tr("Please select terms to mark as reviewed."))
            return

        count = self.term_db.update_terms_bulk(keys, is_reviewed=True)
        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Marked %1 term(s) as reviewed."), count),
        )

    def _on_unmark_reviewed(self) -> None:
        """Unmark selected terms as reviewed."""
        keys = self._get_selected_keys()
        if not keys:
            QMessageBox.warning(self, self.tr("No Selection"), self.tr("Please select terms to unmark as reviewed."))
            return

        count = self.term_db.update_terms_bulk(keys, is_reviewed=False)
        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Unmarked %1 term(s) as reviewed."), count),
        )

    def _on_mark_ignored(self) -> None:
        """Mark selected terms as ignored."""
        keys = self._get_selected_keys()
        if not keys:
            QMessageBox.warning(self, self.tr("No Selection"), self.tr("Please select terms to mark as ignored."))
            return

        count = self.term_db.update_terms_bulk(keys, ignored=True)
        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Marked %1 term(s) as ignored."), count),
        )

    def _on_unmark_ignored(self) -> None:
        """Unmark selected terms as ignored."""
        keys = self._get_selected_keys()
        if not keys:
            QMessageBox.warning(self, self.tr("No Selection"), self.tr("Please select terms to unmark as ignored."))
            return

        count = self.term_db.update_terms_bulk(keys, ignored=False)
        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Unmarked %1 term(s) as ignored."), count),
        )

    def _occurrence_label(self) -> str:
        """Return localized glossary occurrence column label."""
        return self.tr("Occurrences")

    def _votes_label(self) -> str:
        """Return localized glossary votes column label."""
        return self.tr("Votes")

    def _occurrence_votes_label(self, separator: str = "/") -> str:
        """Return localized combined occurrence/votes label."""
        return f"{self._occurrence_label()}{separator}{self._votes_label()}"

    def _on_filter_rare(self) -> None:
        """Ignore terms that occurred only once or were recognized in only one chunk."""
        reply = QMessageBox.question(
            self,
            self.tr("Filter Rare Terms"),
            self.tr(
                "This will mark terms as ignored when:\n\n"
                "- The term occurred only once across all chunks, OR\n"
                "- The term was recognized by the LLM in only one chunk.\n\n"
                "Why:\n"
                "Terms appearing only once are likely not significant enough "
                "to warrant a glossary entry.\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        rare_keys = self._get_rare_term_keys()
        if not rare_keys:
            QMessageBox.information(
                self,
                self.tr("No Rare Terms Found"),
                self.tr("No terms matched the rare-term criteria."),
            )
            return

        count = self.term_db.update_terms_bulk(rare_keys, ignored=True, is_reviewed=True)
        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Ignored %1 rare term(s)."), count),
        )

    def _get_rare_term_keys(self) -> list[str]:
        """Return non-ignored, non-reviewed term keys that occurred only once or were recognized in one chunk."""
        rare_keys: list[str] = []
        for term in self.term_db.list_terms():
            if term.ignored or term.is_reviewed:
                continue

            total_occurrences = sum((term.occurrence or {}).values())
            if total_occurrences <= 1:
                rare_keys.append(term.key)
                continue

            # Count chunk-id description keys (numeric strings = extracted from chunks)
            chunk_desc_count = sum(1 for k in (term.descriptions or {}) if str(k).lstrip("-").isdigit())
            if chunk_desc_count <= 1:
                rare_keys.append(term.key)

        return rare_keys

    def _on_delete_selected(self) -> None:
        """Delete selected terms."""
        keys = self._get_selected_keys()
        if not keys:
            QMessageBox.warning(self, self.tr("No Selection"), self.tr("Please select terms to delete."))
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            qarg(self.tr("Are you sure you want to delete %1 term(s)?"), len(keys)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        count = self.term_db.delete_terms(keys)
        self.table_model.refresh()
        self._update_stats()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Deleted %1 term(s)."), count),
        )

    def _on_context_menu(self, pos: QPoint) -> None:
        """Show context menu at position.

        Args:
            pos: Position to show menu
        """
        index = self.table_view.indexAt(pos)
        row = index.row() if index.isValid() else self.table_view.rowAt(pos.y())
        if row < 0:
            # Be lenient when callers pass table-relative coordinates instead of viewport-relative ones.
            viewport_pos = self.table_view.viewport().mapFrom(self.table_view, pos)
            row = self.table_view.rowAt(viewport_pos.y())
        if row < 0:
            return

        model = self.table_view.model()
        if model is not None:
            current = model.index(row, 0)
            if current.isValid():
                self.table_view.setCurrentIndex(current)
        self.table_view.selectRow(row)

        menu = QMenu(self)

        # Copy Description action
        term = self.table_model.get_term(row)
        if term and term.descriptions:
            copy_desc_action = menu.addAction(self.tr("Copy Description"))
            copy_desc_action.triggered.connect(lambda: self._copy_description(term.descriptions))
            menu.addSeparator()

        # Add bulk actions
        menu.addAction(self.bulk_mark_reviewed_action)
        menu.addAction(self.bulk_unmark_reviewed_action)
        menu.addAction(self.bulk_mark_ignored_action)
        menu.addAction(self.bulk_unmark_ignored_action)
        menu.addAction(self.bulk_delete_action)

        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _copy_description(self, descriptions: dict[str, str]) -> None:
        """Copy full description text to clipboard."""
        text = "\n".join(descriptions.values())
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def cleanup(self) -> None:
        """Clean up resources."""
        if hasattr(self, "task_console"):
            self.task_console.cleanup()

        if hasattr(self, "review_task_console"):
            self.review_task_console.cleanup()

        if self._translate_worker and self._translate_worker.isRunning():
            self._translate_worker.requestInterruption()
            self._translate_worker.wait()

        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.requestInterruption()
            self._export_worker.wait()

        if hasattr(self, "term_db"):
            self.term_db.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle widget close event."""
        self.cleanup()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def _apply_button_tooltips(self) -> None:
        """Apply hover explanations for toolbar buttons."""
        self.build_button.setToolTip(
            self.tr("Build glossary terms from pending documents up to the selected document.")
        )
        self.translate_button.setToolTip(self.tr("Translate all currently untranslated glossary terms."))
        self.review_button.setToolTip(self.tr("Run an LLM review pass on unreviewed glossary terms."))
        self.filter_rare_button.setToolTip(
            self.tr(
                "Automatically ignore terms that occurred only once or were recognized by the LLM in only one chunk."
            )
        )
        self.refresh_button.setToolTip(self.tr("Reload glossary table data and refresh statistics."))
        self.export_button.setToolTip(self.tr("Export glossary terms to a JSON file."))
        self.import_button.setToolTip(self.tr("Import glossary terms from a JSON file and replace current glossary."))

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.search_input.setPlaceholderText(self.tr("Search terms..."))
        # Re-set filter combo item texts
        self.filter_combo.setItemText(0, self.tr("All"))
        self.filter_combo.setItemText(1, self.tr("Unreviewed"))
        self.filter_combo.setItemText(2, self.tr("Ignored"))
        self.filter_combo.setItemText(3, self.tr("Translated"))
        self.filter_combo.setItemText(4, self.tr("Untranslated"))
        self.build_until_label.setText(self.tr("Build until:"))
        self.build_button.setText(self.tr("Build Glossary"))
        self.translate_button.setText(self.tr("Translate Untranslated"))
        self.review_button.setText(self.tr("Review Terms"))
        self.filter_rare_button.setText(self.tr("Filter Rare"))
        self.refresh_button.setText(self.tr("Refresh"))
        self.bulk_menu.setTitle(self.tr("Bulk Actions"))
        self.bulk_mark_reviewed_action.setText(self.tr("Mark Reviewed"))
        self.bulk_unmark_reviewed_action.setText(self.tr("Unmark Reviewed"))
        self.bulk_mark_ignored_action.setText(self.tr("Mark Ignored"))
        self.bulk_unmark_ignored_action.setText(self.tr("Unmark Ignored"))
        self.bulk_delete_action.setText(self.tr("Delete Selected"))
        self.export_button.setText(self.tr("Export Glossary"))
        self.import_button.setText(self.tr("Import Glossary"))
        self._apply_button_tooltips()
        self.table_model.retranslate()
        self._update_stats()

    def _tip_text(self) -> str:
        return self.tr(
            "Glossary is optional: build it after OCR if you want auto-extracted terms, or import your own glossary.\n"
            "Review/ignore/translate glossary terms before main translation for best consistency.\n"
            "During translation, relevant terms are selected per chunk via normalized substring matching "
            "and sent alongside the source text. Each term includes its name, translation, and a "
            "summarized description to guide the translator for consistent output."
        )
