from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import UserMessageSeverity
from context_aware_translation.application.contracts.terms import (
    BulkUpdateTermsRequest,
    ExportTermsRequest,
    FilterNoiseRequest,
    ImportTermsRequest,
    ReviewTermsRequest,
    TermsTableState,
    TranslatePendingTermsRequest,
    UpdateTermRequest,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
)
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.features.terms_table_widget import TermsTableWidget
from context_aware_translation.ui.utils import create_tip_label


class TermsView(QWidget):
    """Project-level shared Terms surface backed by application services."""

    def __init__(
        self,
        project_id: str,
        service: TermsService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self._service = service
        self._state: TermsTableState | None = None
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.terms_invalidated.connect(self._on_terms_invalidated)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel(self.tr("Terms"))
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        toolbar_layout = QHBoxLayout()
        self.table_panel = TermsTableWidget(parent=self)
        self.table_panel.term_update_requested.connect(self._on_term_update_requested)
        self.search_input = self.table_panel.search_input
        self.filter_combo = self.table_panel.filter_combo
        self.scope_label = self.table_panel.scope_label
        self.summary_label = self.table_panel.summary_label
        self.table_model = self.table_panel.table_model
        self.proxy_model = self.table_panel.proxy_model
        self.table_view = self.table_panel.table_view
        self.table_view.selectionModel().selectionChanged.connect(lambda *_args: self._update_bulk_button_state())
        toolbar_layout.addWidget(self.search_input, 1)
        toolbar_layout.addWidget(self.filter_combo)

        self.translate_button = QPushButton(self.tr("Translate Untranslated"))
        self.translate_button.clicked.connect(self._on_translate_pending)
        toolbar_layout.addWidget(self.translate_button)

        self.review_button = QPushButton(self.tr("Review Terms"))
        self.review_button.clicked.connect(self._on_review_terms)
        toolbar_layout.addWidget(self.review_button)

        self.filter_noise_button = QPushButton(self.tr("Filter Rare"))
        self.filter_noise_button.clicked.connect(self._on_filter_noise)
        toolbar_layout.addWidget(self.filter_noise_button)

        self.bulk_menu = QMenu(self)
        self.bulk_mark_reviewed_action = self.bulk_menu.addAction(
            self.tr("Mark Reviewed"),
            lambda: self._run_bulk_update(reviewed=True),
        )
        self.bulk_unmark_reviewed_action = self.bulk_menu.addAction(
            self.tr("Unmark Reviewed"),
            lambda: self._run_bulk_update(reviewed=False),
        )
        self.bulk_mark_ignored_action = self.bulk_menu.addAction(
            self.tr("Mark Ignored"),
            lambda: self._run_bulk_update(ignored=True),
        )
        self.bulk_unmark_ignored_action = self.bulk_menu.addAction(
            self.tr("Unmark Ignored"),
            lambda: self._run_bulk_update(ignored=False),
        )
        self.bulk_delete_action = self.bulk_menu.addAction(
            self.tr("Delete Selected"),
            self._delete_selected_terms,
        )
        self.bulk_button = QPushButton(self.tr("Bulk Actions"))
        self.bulk_button.setMenu(self.bulk_menu)
        toolbar_layout.addWidget(self.bulk_button)

        self.import_button = QPushButton(self.tr("Import Terms"))
        self.import_button.clicked.connect(self._on_import_terms)
        toolbar_layout.addWidget(self.import_button)

        self.export_button = QPushButton(self.tr("Export Terms"))
        self.export_button.clicked.connect(self._on_export_terms)
        toolbar_layout.addWidget(self.export_button)

        layout.addLayout(toolbar_layout)
        layout.addWidget(self.table_panel, 1)

    def refresh(self) -> None:
        self._apply_state(self._service.get_project_terms(self.project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.title_label.setText(self.tr("Terms"))
        self.tip_label.setText(self._tip_text())
        self.translate_button.setText(self.tr("Translate Untranslated"))
        self.review_button.setText(self.tr("Review Terms"))
        self.filter_noise_button.setText(self.tr("Filter Rare"))
        self.bulk_button.setText(self.tr("Bulk Actions"))
        self.bulk_mark_reviewed_action.setText(self.tr("Mark Reviewed"))
        self.bulk_unmark_reviewed_action.setText(self.tr("Unmark Reviewed"))
        self.bulk_mark_ignored_action.setText(self.tr("Mark Ignored"))
        self.bulk_unmark_ignored_action.setText(self.tr("Unmark Ignored"))
        self.bulk_delete_action.setText(self.tr("Delete Selected"))
        self.import_button.setText(self.tr("Import Terms"))
        self.export_button.setText(self.tr("Export Terms"))
        self.table_panel.retranslateUi()
        if self._state is not None:
            self._apply_toolbar_state(self._state.toolbar)

    def _apply_state(self, state: TermsTableState) -> None:
        self._state = state
        self._apply_toolbar_state(state.toolbar)
        self.table_panel.set_state(state)
        self._update_bulk_button_state()

    def _apply_toolbar_state(self, toolbar) -> None:  # noqa: ANN001
        self.translate_button.setEnabled(toolbar.can_translate_pending)
        self.review_button.setEnabled(toolbar.can_review)
        self.filter_noise_button.setEnabled(toolbar.can_filter_noise)
        self.import_button.setEnabled(toolbar.can_import)
        self.export_button.setEnabled(toolbar.can_export)

        self.translate_button.setToolTip(
            toolbar.translate_pending_blocker.message
            if toolbar.translate_pending_blocker
            else self.tr("Translate all currently untranslated glossary terms.")
        )
        self.review_button.setToolTip(
            toolbar.review_blocker.message
            if toolbar.review_blocker
            else self.tr("Run an LLM review pass on unreviewed glossary terms.")
        )
        self.filter_noise_button.setToolTip(
            toolbar.filter_noise_blocker.message
            if toolbar.filter_noise_blocker
            else self.tr(
                "Automatically ignore terms that occurred only once or were recognized by the LLM in only one chunk."
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
        self._update_bulk_button_state()

    def _on_translate_pending(self) -> None:
        self._run_command(
            lambda: self._service.translate_pending(TranslatePendingTermsRequest(project_id=self.project_id)),
            title=self.tr("Translate Terms"),
        )

    def _on_review_terms(self) -> None:
        self._run_command(
            lambda: self._service.review_terms(ReviewTermsRequest(project_id=self.project_id)),
            title=self.tr("Review Terms"),
        )

    def _on_filter_noise(self) -> None:
        if (
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
            state = self._service.filter_noise(FilterNoiseRequest(project_id=self.project_id))
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Filter Rare Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Filter Rare Terms"), exc)
            return
        self._apply_state(state)
        self._show_message(UserMessageSeverity.SUCCESS, self.tr("Rare terms were filtered."))

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
        path, _selected = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Terms"),
            "terms.json",
            self.tr("JSON Files (*.json);;All Files (*)"),
        )
        if not path:
            return
        self._run_command(
            lambda: self._service.export_terms(ExportTermsRequest(project_id=self.project_id, output_path=path)),
            title=self.tr("Export Terms"),
        )

    def _on_term_update_requested(self, request: UpdateTermRequest) -> None:
        try:
            state = self._service.update_term(request)
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Terms"), exc)
            self.refresh()
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Terms"), exc)
            self.refresh()
            return
        self._apply_state(state)

    def _run_command(self, action, *, title: str) -> None:  # noqa: ANN001
        try:
            accepted = action()
        except BlockedOperationError as exc:
            self._show_application_error(title, exc)
            return
        except ApplicationError as exc:
            self._show_application_error(title, exc)
            return
        message = accepted.message.text if accepted.message is not None else self.tr("Task queued.")
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
        try:
            state = self._service.bulk_update_terms(
                BulkUpdateTermsRequest(
                    scope=self._state.scope,
                    term_keys=[row.term_key for row in selected],
                    ignored=ignored,
                    reviewed=reviewed,
                )
            )
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Terms"), exc)
            return
        self._apply_state(state)

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
                self.tr("Delete the selected terms from this project?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            state = self._service.bulk_update_terms(
                BulkUpdateTermsRequest(
                    scope=self._state.scope,
                    term_keys=[row.term_key for row in selected],
                    delete=True,
                )
            )
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Delete Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Delete Terms"), exc)
            return
        self._apply_state(state)
        self._show_message(UserMessageSeverity.SUCCESS, self.tr("Selected terms were deleted."))

    def _update_bulk_button_state(self) -> None:
        self.bulk_button.setEnabled(bool(self.table_panel.selected_rows()))

    def _show_application_error(self, title: str, exc: ApplicationError) -> None:
        if isinstance(exc, BlockedOperationError):
            QMessageBox.warning(self, title, exc.payload.message)
        else:
            QMessageBox.warning(self, title, exc.payload.message)
        self._show_message(UserMessageSeverity.ERROR, exc.payload.message, show_dialog=False)

    def _show_message(self, severity: UserMessageSeverity, text: str, *, show_dialog: bool = False) -> None:
        self.table_panel.set_message(severity, text)
        if show_dialog:
            QMessageBox.information(self, self.tr("Terms"), text)

    def _on_terms_invalidated(self, event: TermsInvalidatedEvent) -> None:
        if event.project_id != self.project_id:
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.refresh()

    def _tip_text(self) -> str:
        return self.tr(
            "Terms are shared across the project. Build terms from document pages in document Terms, then translate, review, filter, import, or export them here."
        )
