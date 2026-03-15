from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.common import UserMessageSeverity
from context_aware_translation.application.contracts.terms import (
    BuildTermsRequest,
    BulkUpdateTermsRequest,
    ExportTermsRequest,
    FilterNoiseRequest,
    ImportTermsRequest,
    ReviewTermsRequest,
    TermsTableState,
    TermTableRow,
    TranslatePendingTermsRequest,
    UpdateTermRowsRequest,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
)
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.ui.chrome_sizing import sync_qml_host_height
from context_aware_translation.ui.features.terms_table_widget import TermsTableWidget
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.terms_pane import TermsPaneViewModel
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone


class TermsView(QWidget):
    """Shared Terms surface for either project or document scope."""

    def __init__(
        self,
        project_id: str,
        service: TermsService,
        events: ApplicationEventSubscriber | None,
        *,
        document_id: int | None = None,
        embedded: bool = False,
        auto_refresh: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.document_id = document_id
        self._embedded = embedded
        self._use_qml_chrome = (document_id is None and not embedded) or document_id is not None
        self._service = service
        self._state: TermsTableState | None = None
        self._loaded_once = False
        self._needs_refresh = False
        self._event_bridge: QtApplicationEventBridge | None = None
        self._pending_local_terms_invalidations = 0
        self.viewmodel = (
            TermsPaneViewModel(document_scope=self._is_document_scope, embedded=self._embedded, parent=self)
            if self._use_qml_chrome
            else None
        )
        if events is not None:
            self._event_bridge = QtApplicationEventBridge(events, parent=self)
            self._event_bridge.terms_invalidated.connect(self._on_terms_invalidated)
            if not (self._is_document_scope and self._embedded):
                self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        if auto_refresh and not self._embedded:
            self.refresh()

    @property
    def _is_document_scope(self) -> bool:
        return self.document_id is not None

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.chrome_host: QmlChromeHost | None = None
        if self._use_qml_chrome:
            self.chrome_host = QmlChromeHost(
                "project/terms/TermsPaneChrome.qml",
                context_objects={"termsPane": self.viewmodel},
                parent=self,
            )
            layout.addWidget(self.chrome_host)

        self.title_label = QLabel(self.tr("Terms"))
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.title_label.setVisible(not self._embedded and not self._use_qml_chrome)
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label(self._tip_text())
        self.tip_label.setVisible(not self._embedded and not self._use_qml_chrome)
        layout.addWidget(self.tip_label)

        toolbar_layout = QHBoxLayout()
        self.table_panel = TermsTableWidget(parent=self)
        self.table_panel.term_rows_update_requested.connect(self._on_term_rows_update_requested)
        self.search_input = self.table_panel.search_input
        self.filter_combo = self.table_panel.filter_combo
        self.scope_label = self.table_panel.scope_label
        self.summary_label = self.table_panel.summary_label
        self.table_model = self.table_panel.table_model
        self.proxy_model = self.table_panel.proxy_model
        self.table_view = self.table_panel.table_view
        self.table_view.selectionModel().selectionChanged.connect(lambda *_args: self._update_bulk_button_state())
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        toolbar_layout.addWidget(self.search_input, 1)
        toolbar_layout.addWidget(self.filter_combo)

        self.build_button = QPushButton(self.tr("Build Terms"), self)
        self.build_button.clicked.connect(self._on_build_terms)
        self.build_button.setVisible(self._is_document_scope and not self._use_qml_chrome)
        if self._is_document_scope and not self._use_qml_chrome:
            toolbar_layout.addWidget(self.build_button)

        self.translate_button = QPushButton(self.tr("Translate Untranslated"), self)
        self.translate_button.clicked.connect(self._on_translate_pending)
        self.translate_button.setVisible(not self._use_qml_chrome)
        if not self._use_qml_chrome:
            toolbar_layout.addWidget(self.translate_button)

        self.review_button = QPushButton(self.tr("Review Terms"), self)
        self.review_button.clicked.connect(self._on_review_terms)
        self.review_button.setVisible(not self._use_qml_chrome)
        if not self._use_qml_chrome:
            toolbar_layout.addWidget(self.review_button)

        self.filter_noise_button = QPushButton(self.tr("Filter Rare"), self)
        self.filter_noise_button.clicked.connect(self._on_filter_noise)
        self.filter_noise_button.setVisible(not self._use_qml_chrome)
        if not self._use_qml_chrome:
            toolbar_layout.addWidget(self.filter_noise_button)

        self.edit_selected_action = QAction(self.tr("Edit Selected"), self)
        self.edit_selected_action.triggered.connect(self._edit_selected_terms)
        self.bulk_mark_reviewed_action = QAction(self.tr("Mark Reviewed"), self)
        self.bulk_mark_reviewed_action.triggered.connect(lambda: self._run_bulk_update(reviewed=True))
        self.bulk_unmark_reviewed_action = QAction(self.tr("Unmark Reviewed"), self)
        self.bulk_unmark_reviewed_action.triggered.connect(lambda: self._run_bulk_update(reviewed=False))
        self.bulk_mark_ignored_action = QAction(self.tr("Mark Ignored"), self)
        self.bulk_mark_ignored_action.triggered.connect(lambda: self._run_bulk_update(ignored=True))
        self.bulk_unmark_ignored_action = QAction(self.tr("Unmark Ignored"), self)
        self.bulk_unmark_ignored_action.triggered.connect(lambda: self._run_bulk_update(ignored=False))
        self.bulk_delete_action = QAction(self.tr("Delete Selected"), self)
        self.bulk_delete_action.triggered.connect(self._delete_selected_terms)
        self.mark_reviewed_action = self.bulk_mark_reviewed_action
        self.unmark_reviewed_action = self.bulk_unmark_reviewed_action
        self.mark_ignored_action = self.bulk_mark_ignored_action
        self.unmark_ignored_action = self.bulk_unmark_ignored_action
        self.delete_selected_action = self.bulk_delete_action

        self.import_button = QPushButton(self.tr("Import Terms"), self)
        self.import_button.clicked.connect(self._on_import_terms)
        self.import_button.setVisible(not self._is_document_scope and not self._use_qml_chrome)
        if not self._is_document_scope and not self._use_qml_chrome:
            toolbar_layout.addWidget(self.import_button)

        self.export_button = QPushButton(self.tr("Export Terms"), self)
        self.export_button.clicked.connect(self._on_export_terms)
        self.export_button.setVisible(not self._is_document_scope and not self._use_qml_chrome)
        if not self._is_document_scope and not self._use_qml_chrome:
            toolbar_layout.addWidget(self.export_button)

        layout.addLayout(toolbar_layout)
        layout.addWidget(self.table_panel, 1)
        if self._use_qml_chrome:
            self._connect_qml_signals()
            self._schedule_chrome_resize()
        apply_hybrid_control_theme(self)
        for button in (
            self.build_button,
            self.translate_button,
            self.review_button,
            self.filter_noise_button,
            self.import_button,
            self.export_button,
        ):
            set_button_tone(button)

    def refresh(self) -> None:
        if self._is_document_scope:
            self._apply_state(self._service.get_document_terms(self.project_id, self.document_id))
        else:
            self._apply_state(self._service.get_project_terms(self.project_id))
        self._loaded_once = True
        self._needs_refresh = False

    def ensure_loaded(self) -> None:
        if self._loaded_once and not self._needs_refresh:
            return
        self.refresh()

    def activate_view(self) -> None:
        self.ensure_loaded()

    def cleanup(self) -> None:
        if self._event_bridge is not None:
            self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.title_label.setText(self.tr("Terms"))
        self.tip_label.setText(self._tip_text())
        self.build_button.setText(self.tr("Build Terms"))
        self.translate_button.setText(self.tr("Translate Untranslated"))
        self.review_button.setText(self.tr("Review Terms"))
        self.filter_noise_button.setText(self.tr("Filter Rare"))
        self.edit_selected_action.setText(self.tr("Edit Selected"))
        self.bulk_mark_reviewed_action.setText(self.tr("Mark Reviewed"))
        self.bulk_unmark_reviewed_action.setText(self.tr("Unmark Reviewed"))
        self.bulk_mark_ignored_action.setText(self.tr("Mark Ignored"))
        self.bulk_unmark_ignored_action.setText(self.tr("Unmark Ignored"))
        self.bulk_delete_action.setText(self.tr("Delete Selected"))
        self.import_button.setText(self.tr("Import Terms"))
        self.export_button.setText(self.tr("Export Terms"))
        self.table_panel.retranslateUi()
        if self.viewmodel is not None:
            self.viewmodel.retranslate()
        if self._state is not None:
            self._apply_toolbar_state(self._state.toolbar)
        if self._use_qml_chrome:
            self._schedule_chrome_resize()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        if self._use_qml_chrome:
            self._schedule_chrome_resize()

    def _apply_state(self, state: TermsTableState) -> None:
        self._state = state
        self._apply_toolbar_state(state.toolbar)
        self.table_panel.set_state(state)
        self._update_bulk_button_state()
        if self._use_qml_chrome:
            self._schedule_chrome_resize()

    def _apply_toolbar_state(self, toolbar) -> None:  # noqa: ANN001
        self.build_button.setEnabled(toolbar.can_build)
        self.translate_button.setEnabled(toolbar.can_translate_pending)
        self.review_button.setEnabled(toolbar.can_review)
        self.filter_noise_button.setEnabled(toolbar.can_filter_noise)
        self.import_button.setEnabled(toolbar.can_import)
        self.export_button.setEnabled(toolbar.can_export)

        self.build_button.setToolTip(
            toolbar.build_blocker.message if toolbar.build_blocker else self.tr("Extract terms from this document.")
        )
        self.translate_button.setToolTip(
            toolbar.translate_pending_blocker.message
            if toolbar.translate_pending_blocker
            else self.tr("Translate all currently untranslated glossary terms for the current scope.")
        )
        self.review_button.setToolTip(
            toolbar.review_blocker.message
            if toolbar.review_blocker
            else self.tr("Run an LLM review pass on unreviewed glossary terms for the current scope.")
        )
        self.filter_noise_button.setToolTip(
            toolbar.filter_noise_blocker.message
            if toolbar.filter_noise_blocker
            else (
                self.tr("Ignore rare terms for this document.")
                if self._is_document_scope
                else self.tr(
                    "Automatically ignore terms that occurred only once or were recognized by the LLM in only one chunk."
                )
            )
        )
        self.import_button.setToolTip(
            toolbar.import_blocker.message
            if toolbar.import_blocker
            else self.tr("Import terms from a JSON file and replace current project terms.")
        )
        self.export_button.setToolTip(
            toolbar.export_blocker.message if toolbar.export_blocker else self.tr("Export terms to a JSON file.")
        )
        if self.viewmodel is not None:
            self.viewmodel.apply_toolbar_state(
                can_build=toolbar.can_build,
                can_translate=toolbar.can_translate_pending,
                can_review=toolbar.can_review,
                can_filter=toolbar.can_filter_noise,
                can_import=toolbar.can_import,
                can_export=toolbar.can_export,
            )
        self._update_bulk_button_state()

    def _connect_qml_signals(self) -> None:
        if self.chrome_host is None:
            return
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.buildRequested.connect(self._on_build_terms)
        root.translateRequested.connect(self._on_translate_pending)
        root.reviewRequested.connect(self._on_review_terms)
        root.filterRequested.connect(self._on_filter_noise)
        root.importRequested.connect(self._on_import_terms)
        root.exportRequested.connect(self._on_export_terms)

    def _schedule_chrome_resize(self) -> None:
        self._sync_chrome_height()
        QTimer.singleShot(0, self._sync_chrome_height)

    def _sync_chrome_height(self) -> None:
        sync_qml_host_height(self.chrome_host)

    def _on_build_terms(self) -> None:
        if self.document_id is None:
            return
        self._run_command(
            lambda: self._service.build_terms(
                BuildTermsRequest(project_id=self.project_id, document_id=self.document_id)
            ),
            title=self.tr("Build Terms"),
            success_message=self.tr("Terms extraction queued for this document."),
        )

    def _on_translate_pending(self) -> None:
        self._run_command(
            lambda: self._service.translate_pending(
                TranslatePendingTermsRequest(project_id=self.project_id, document_id=self.document_id)
            ),
            title=self.tr("Translate Terms"),
        )

    def _on_review_terms(self) -> None:
        self._run_command(
            lambda: self._service.review_terms(
                ReviewTermsRequest(project_id=self.project_id, document_id=self.document_id)
            ),
            title=self.tr("Review Terms"),
        )

    def _on_filter_noise(self) -> None:
        if not self._is_document_scope and (
            QMessageBox.question(
                self,
                self.tr("Filter Rare Terms"),
                self.tr(
                    "This will mark terms as ignored when they occurred only once or were recognized in only one chunk. Continue?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            state = self._service.filter_noise(
                FilterNoiseRequest(project_id=self.project_id, document_id=self.document_id)
            )
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Filter Rare Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Filter Rare Terms"), exc)
            return
        self._apply_state(state)
        self._show_message(
            UserMessageSeverity.SUCCESS,
            self.tr("Rare document terms were filtered.")
            if self._is_document_scope
            else self.tr("Rare terms were filtered."),
        )

    def _on_import_terms(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Terms"),
            "",
            self.tr("JSON Files (*.json);;All Files (*)"),
        )
        if not path:
            return
        try:
            state = self._service.import_terms(ImportTermsRequest(project_id=self.project_id, input_path=path))
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Import Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Import Terms"), exc)
            return
        self._apply_state(state)
        self._show_message(UserMessageSeverity.SUCCESS, self.tr("Terms imported."))

    def _on_export_terms(self) -> None:
        if (
            QMessageBox.question(
                self,
                self.tr("Export Terms"),
                self.tr(
                    "Exporting terms may build missing context summaries before writing the file. "
                    "The export will run in the background and appear in Queue so you can keep working. Continue?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Terms"),
            "terms.json",
            self.tr("JSON Files (*.json);;All Files (*)"),
        )
        if not path:
            return
        try:
            self._service.export_terms(
                ExportTermsRequest(project_id=self.project_id, output_path=path, document_id=self.document_id)
            )
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Export Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Export Terms"), exc)
            return
        self._show_message(
            UserMessageSeverity.INFO,
            self.tr(
                "Terms export was queued. Context summaries will be built in the background if needed. "
                "Check Queue for progress."
            ),
        )
        self.refresh()

    def _on_term_rows_update_requested(self, rows: list[TermTableRow]) -> None:
        if self._state is None or not rows:
            return
        self._persist_local_terms_write(
            lambda: self._service.update_term_rows(UpdateTermRowsRequest(scope=self._state.scope, rows=rows)),
            title=self.tr("Terms"),
        )

    def _run_command(self, action, *, title: str, success_message: str | None = None) -> None:  # noqa: ANN001
        try:
            accepted = action()
        except BlockedOperationError as exc:
            self._show_application_error(title, exc)
            return
        except ApplicationError as exc:
            self._show_application_error(title, exc)
            return
        message = (
            accepted.message.text if accepted.message is not None else (success_message or self.tr("Task queued."))
        )
        severity = accepted.message.severity if accepted.message is not None else UserMessageSeverity.INFO
        self._show_message(severity, message)
        self.refresh()

    def _run_bulk_update(
        self,
        *,
        ignored: bool | None = None,
        reviewed: bool | None = None,
    ) -> None:
        if self._state is None:
            return
        selected = self.table_panel.selected_rows()
        if not selected:
            return
        updated_rows = []
        updated_term_keys = []
        for row in selected:
            next_ignored = row.ignored if ignored is None else ignored
            next_reviewed = row.reviewed if reviewed is None else reviewed
            if next_ignored == row.ignored and next_reviewed == row.reviewed:
                continue
            updated_rows.append(
                row.model_copy(
                    update={
                        "ignored": next_ignored,
                        "reviewed": next_reviewed,
                    }
                )
            )
            updated_term_keys.append(row.term_key)
        if not updated_rows:
            return
        self.table_panel.apply_row_updates(updated_rows)
        self._persist_local_terms_write(
            lambda: self._service.bulk_update_terms(
                BulkUpdateTermsRequest(
                    scope=self._state.scope,
                    term_keys=updated_term_keys,
                    ignored=ignored,
                    reviewed=reviewed,
                )
            ),
            title=self.tr("Terms"),
        )

    def _delete_selected_terms(self) -> None:
        if self._state is None:
            return
        selected = self.table_panel.selected_rows()
        if not selected:
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Delete Terms"),
                (
                    self.tr("Delete the selected terms from this document?")
                    if self._is_document_scope
                    else self.tr("Delete the selected terms from this project?")
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        term_keys = [row.term_key for row in selected]
        self.table_panel.remove_rows(term_keys)
        if self._persist_local_terms_write(
            lambda: self._service.bulk_update_terms(
                BulkUpdateTermsRequest(
                    scope=self._state.scope,
                    term_keys=term_keys,
                    delete=True,
                )
            ),
            title=self.tr("Delete Terms"),
        ):
            self._show_message(UserMessageSeverity.SUCCESS, self.tr("Selected terms were deleted."))

    def _edit_selected_terms(self) -> None:
        self.table_panel.open_editors_for_selection()

    def _update_bulk_button_state(self) -> None:
        has_selection = bool(self.table_panel.selected_rows())
        self.edit_selected_action.setEnabled(has_selection)
        self.bulk_mark_reviewed_action.setEnabled(has_selection)
        self.bulk_unmark_reviewed_action.setEnabled(has_selection)
        self.bulk_mark_ignored_action.setEnabled(has_selection)
        self.bulk_unmark_ignored_action.setEnabled(has_selection)
        self.bulk_delete_action.setEnabled(has_selection)

    def _show_context_menu(self, pos: QPoint) -> None:
        if not self.table_panel.prepare_context_selection(pos):
            return
        self._update_bulk_button_state()

        menu = QMenu(self)
        menu.addAction(self.edit_selected_action)
        menu.addSeparator()
        proxy_index = self.table_view.currentIndex()
        source_index = self.proxy_model.mapToSource(proxy_index)
        description = self.table_model.data(self.table_model.index(source_index.row(), 2), Qt.ItemDataRole.ToolTipRole)
        if isinstance(description, str) and description.strip():
            copy_action = menu.addAction(self.tr("Copy Description"))
            copy_action.triggered.connect(lambda: self._copy_description(description))
            menu.addSeparator()

        menu.addAction(self.bulk_mark_reviewed_action)
        menu.addAction(self.bulk_unmark_reviewed_action)
        menu.addAction(self.bulk_mark_ignored_action)
        menu.addAction(self.bulk_unmark_ignored_action)
        menu.addAction(self.bulk_delete_action)
        self._context_menu = menu
        menu.popup(self.table_view.viewport().mapToGlobal(pos))

    def _copy_description(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _show_application_error(self, title: str, exc: ApplicationError) -> None:
        QMessageBox.warning(self, title, exc.payload.message)
        self._show_message(UserMessageSeverity.ERROR, exc.payload.message, show_dialog=False)

    def _show_message(self, severity: UserMessageSeverity, text: str, *, show_dialog: bool = False) -> None:
        self.table_panel.set_message(severity, text)
        if show_dialog:
            QMessageBox.information(self, self.tr("Terms"), text)

    def _persist_local_terms_write(self, action, *, title: str) -> bool:  # noqa: ANN001
        tracks_invalidation = self._event_bridge is not None
        if tracks_invalidation:
            self._pending_local_terms_invalidations += 1
        try:
            action()
        except ApplicationError as exc:
            self._show_application_error(title, exc)
            self.refresh()
            return False
        finally:
            if tracks_invalidation:
                self._pending_local_terms_invalidations = max(0, self._pending_local_terms_invalidations - 1)
        if self._state is not None:
            self._state = self._state.model_copy(update={"rows": self.table_panel.rows_snapshot()})
        self._update_bulk_button_state()
        return True

    def _on_terms_invalidated(self, event: TermsInvalidatedEvent) -> None:
        if event.project_id != self.project_id:
            return
        if self.document_id is not None and event.document_id not in {None, self.document_id}:
            return
        if self._pending_local_terms_invalidations > 0:
            self._pending_local_terms_invalidations -= 1
            return
        if not self.isVisible():
            self._needs_refresh = True
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        if not self.isVisible():
            self._needs_refresh = True
            return
        self.refresh()

    def _tip_text(self) -> str:
        if self._is_document_scope:
            return self.tr("Review and adjust terms extracted for this document.")
        return self.tr(
            "Terms are shared across the project. Build terms from document pages in document Terms, then translate, review, filter, import, or export them here."
        )
