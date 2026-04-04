from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    UpsertProjectTermRequest,
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
from context_aware_translation.ui.i18n import translate_backend_text
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.terms_pane import TermsPaneViewModel
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone


class _AddTermsDialogTitleBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("termsAddTitleBar")
        self._drag_offset: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 12, 8)
        layout.setSpacing(12)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("termsAddTitleLabel")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label, 1)

        self.close_button = QPushButton("X", self)
        self.close_button.setObjectName("termsAddCloseButton")
        self.close_button.setFixedSize(36, 36)
        self.close_button.clicked.connect(lambda: self.window().close())
        layout.addWidget(self.close_button)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_offset is not None and bool(event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _AddTermsDialog(QDialog):
    submitted = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("termsAddDialog")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(620)
        self._has_position = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = _AddTermsDialogTitleBar(self)
        layout.addWidget(self.title_bar)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(18, 8, 18, 18)
        content_layout.setSpacing(12)
        layout.addLayout(content_layout)

        row_layout = QHBoxLayout()
        row_layout.setSpacing(10)
        content_layout.addLayout(row_layout)

        self.term_input = QLineEdit(self)
        self.term_input.setObjectName("termsAddTermInput")
        row_layout.addWidget(self.term_input, 1)

        self.arrow_label = QLabel("=>", self)
        self.arrow_label.setObjectName("termsAddArrowLabel")
        row_layout.addWidget(self.arrow_label)

        self.translation_input = QLineEdit(self)
        self.translation_input.setObjectName("termsAddTranslationInput")
        self.translation_input.returnPressed.connect(self._emit_submit)
        row_layout.addWidget(self.translation_input, 1)

        self.add_button = QPushButton(self)
        self.add_button.setObjectName("termsAddSubmitButton")
        self.add_button.clicked.connect(self._emit_submit)
        row_layout.addWidget(self.add_button)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("termsAddStatusLabel")
        self.status_label.hide()
        content_layout.addWidget(self.status_label)

        apply_hybrid_control_theme(
            self,
            extra_stylesheet="""
QDialog#termsAddDialog {
    background: #2f2c31;
    border: 1px solid #4c4852;
    border-radius: 16px;
}
QLabel#termsAddTitleLabel {
    color: #f5f3f7;
    font-size: 26px;
    font-weight: 700;
}
QLabel#termsAddArrowLabel {
    color: #d6d1da;
    font-size: 18px;
    font-weight: 700;
}
QLineEdit#termsAddTermInput,
QLineEdit#termsAddTranslationInput {
    min-height: 46px;
    background: #4b494f;
    border: 1px solid #5a5660;
    color: #f5f3f7;
}
QLineEdit#termsAddTermInput::placeholder,
QLineEdit#termsAddTranslationInput::placeholder {
    color: #aba4b0;
}
QLabel#termsAddStatusLabel {
    color: #f7b3ad;
    padding-left: 4px;
    min-height: 22px;
}
QPushButton#termsAddCloseButton {
    min-height: 32px;
    min-width: 32px;
    padding: 0;
    border: none;
    border-radius: 10px;
    background: transparent;
    color: #d6d1da;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#termsAddCloseButton:hover:enabled {
    background: #403d44;
}
QPushButton#termsAddCloseButton:pressed:enabled {
    background: #4b4850;
}
""",
        )
        set_button_tone(self.add_button, "primary")
        self.retranslateUi()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.title_bar.title_label.setText(self.tr("Add Terms"))
        self.term_input.setPlaceholderText(self.tr("Term"))
        self.translation_input.setPlaceholderText(self.tr("Translation"))
        self.add_button.setText(self.tr("Add"))

    def show_near(self, anchor: QWidget) -> None:
        if not self._has_position:
            self.adjustSize()
            center = anchor.mapToGlobal(anchor.rect().center())
            self.move(center - QPoint(self.width() // 2, self.height() // 2))
            self._has_position = True
        self.show()
        self.raise_()
        self.activateWindow()
        self.term_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_status(self, severity: UserMessageSeverity, text: str) -> None:
        color = {
            UserMessageSeverity.SUCCESS: "#7bd88f",
            UserMessageSeverity.WARNING: "#f4c86a",
            UserMessageSeverity.ERROR: "#f7b3ad",
        }.get(severity, "#8bc5ff")
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(text)
        self.status_label.show()

    def clear_status(self) -> None:
        self.status_label.clear()
        self.status_label.hide()

    def handle_submit_success(self, *, updated_existing: bool) -> None:
        self.term_input.clear()
        self.translation_input.clear()
        self.show_status(
            UserMessageSeverity.SUCCESS,
            self.tr("Updated existing term.") if updated_existing else self.tr("Term added."),
        )
        self.term_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _emit_submit(self) -> None:
        term = self.term_input.text().strip()
        translation = self.translation_input.text().strip()
        if not term:
            self.show_status(UserMessageSeverity.ERROR, self.tr("Term is required."))
            self.term_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if not translation:
            self.show_status(UserMessageSeverity.ERROR, self.tr("Translation is required."))
            self.translation_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self.clear_status()
        self.submitted.emit(term, translation)


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
        self._message_is_transient = False
        self._event_bridge: QtApplicationEventBridge | None = None
        self._pending_local_terms_invalidations = 0
        self._add_terms_dialog: _AddTermsDialog | None = None
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

        self.add_terms_button = QPushButton(self.tr("Add Terms"), self)
        self.add_terms_button.clicked.connect(self._open_add_terms_dialog)
        self.add_terms_button.setVisible(not self._is_document_scope and not self._use_qml_chrome)
        if not self._is_document_scope and not self._use_qml_chrome:
            toolbar_layout.addWidget(self.add_terms_button)

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
            self.add_terms_button,
            self.import_button,
            self.export_button,
        ):
            set_button_tone(button)
        set_button_tone(self.add_terms_button, "primary")

    def refresh(self) -> None:
        self._clear_transient_message()
        if self._is_document_scope:
            document_id = self.document_id
            if document_id is None:
                return
            self._apply_state(self._service.get_document_terms(self.project_id, document_id))
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
        if self._add_terms_dialog is not None:
            self._add_terms_dialog.close()

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
        self.add_terms_button.setText(self.tr("Add Terms"))
        self.edit_selected_action.setText(self.tr("Edit Selected"))
        self.bulk_mark_reviewed_action.setText(self.tr("Mark Reviewed"))
        self.bulk_unmark_reviewed_action.setText(self.tr("Unmark Reviewed"))
        self.bulk_mark_ignored_action.setText(self.tr("Mark Ignored"))
        self.bulk_unmark_ignored_action.setText(self.tr("Unmark Ignored"))
        self.bulk_delete_action.setText(self.tr("Delete Selected"))
        self.import_button.setText(self.tr("Import Terms"))
        self.export_button.setText(self.tr("Export Terms"))
        if self._add_terms_dialog is not None:
            self._add_terms_dialog.retranslateUi()
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
        self.add_terms_button.setEnabled(toolbar.can_add_terms)
        self.import_button.setEnabled(toolbar.can_import)
        self.export_button.setEnabled(toolbar.can_export)

        build_tooltip = (
            translate_backend_text(toolbar.build_blocker.message)
            if toolbar.build_blocker
            else self.tr("Extract terms from this document.")
        )
        translate_tooltip = (
            translate_backend_text(toolbar.translate_pending_blocker.message)
            if toolbar.translate_pending_blocker
            else self.tr("Translate all currently untranslated glossary terms for the current scope.")
        )
        review_tooltip = (
            translate_backend_text(toolbar.review_blocker.message)
            if toolbar.review_blocker
            else self.tr("Run an LLM review pass on unreviewed glossary terms for the current scope.")
        )
        filter_tooltip = (
            translate_backend_text(toolbar.filter_noise_blocker.message)
            if toolbar.filter_noise_blocker
            else (
                self.tr("Ignore rare terms for this document.")
                if self._is_document_scope
                else self.tr(
                    "Automatically ignore terms that occurred only once or were recognized by the LLM in only one chunk."
                )
            )
        )
        add_terms_tooltip = (
            translate_backend_text(toolbar.add_terms_blocker.message)
            if toolbar.add_terms_blocker
            else self.tr("Add or update a shared term translation for this project.")
        )
        import_tooltip = (
            translate_backend_text(toolbar.import_blocker.message)
            if toolbar.import_blocker
            else self.tr("Import terms from a JSON file.")
        )
        export_tooltip = (
            translate_backend_text(toolbar.export_blocker.message)
            if toolbar.export_blocker
            else self.tr("Export terms to a JSON file.")
        )

        self.build_button.setToolTip(build_tooltip)
        self.translate_button.setToolTip(translate_tooltip)
        self.review_button.setToolTip(review_tooltip)
        self.filter_noise_button.setToolTip(filter_tooltip)
        self.add_terms_button.setToolTip(add_terms_tooltip)
        self.import_button.setToolTip(import_tooltip)
        self.export_button.setToolTip(export_tooltip)
        if self.viewmodel is not None:
            self.viewmodel.apply_toolbar_state(
                can_build=toolbar.can_build,
                can_translate=toolbar.can_translate_pending,
                can_review=toolbar.can_review,
                can_filter=toolbar.can_filter_noise,
                can_add=toolbar.can_add_terms,
                can_import=toolbar.can_import,
                can_export=toolbar.can_export,
                build_tooltip=build_tooltip,
                translate_tooltip=translate_tooltip,
                review_tooltip=review_tooltip,
                filter_tooltip=filter_tooltip,
                add_tooltip=add_terms_tooltip,
                import_tooltip=import_tooltip,
                export_tooltip=export_tooltip,
            )
        self._update_bulk_button_state()

    def _connect_qml_signals(self) -> None:
        if self.chrome_host is None:
            return
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root_obj = cast(Any, root)
        for signal_name, handler in (
            ("buildRequested", self._on_build_terms),
            ("translateRequested", self._on_translate_pending),
            ("reviewRequested", self._on_review_terms),
            ("filterRequested", self._on_filter_noise),
            ("addRequested", self._open_add_terms_dialog),
            ("importRequested", self._on_import_terms),
            ("exportRequested", self._on_export_terms),
        ):
            getattr(root_obj, signal_name).connect(handler)

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

    def _open_add_terms_dialog(self) -> None:
        if self._is_document_scope:
            return
        dialog = self._ensure_add_terms_dialog()
        dialog.clear_status()
        dialog.show_near(self)

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
        self.refresh()
        self._show_message(
            UserMessageSeverity.INFO,
            self.tr(
                "Terms export was queued. Context summaries will be built in the background if needed. "
                "Check Queue for progress."
            ),
            transient=True,
        )

    def _on_term_rows_update_requested(self, rows: list[TermTableRow]) -> None:
        state = self._state
        if state is None or not rows:
            return
        scope = state.scope
        self._persist_local_terms_write(
            lambda: self._service.update_term_rows(UpdateTermRowsRequest(scope=scope, rows=rows)),
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
        self.refresh()
        self._show_message(severity, message, transient=True)

    def _run_bulk_update(
        self,
        *,
        ignored: bool | None = None,
        reviewed: bool | None = None,
    ) -> None:
        state = self._state
        if state is None:
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
        scope = state.scope
        self.table_panel.apply_row_updates(updated_rows)
        self._persist_local_terms_write(
            lambda: self._service.bulk_update_terms(
                BulkUpdateTermsRequest(
                    scope=scope,
                    term_keys=updated_term_keys,
                    ignored=ignored,
                    reviewed=reviewed,
                )
            ),
            title=self.tr("Terms"),
        )

    def _delete_selected_terms(self) -> None:
        state = self._state
        if state is None:
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
        scope = state.scope
        self.table_panel.remove_rows(term_keys)
        if self._persist_local_terms_write(
            lambda: self._service.bulk_update_terms(
                BulkUpdateTermsRequest(
                    scope=scope,
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
        translated = translate_backend_text(exc.payload.message)
        QMessageBox.warning(self, title, translated)
        self._show_message(UserMessageSeverity.ERROR, translated, show_dialog=False)

    def _show_message(
        self,
        severity: UserMessageSeverity,
        text: str,
        *,
        show_dialog: bool = False,
        transient: bool = False,
    ) -> None:
        translated = translate_backend_text(text)
        self.table_panel.set_message(severity, translated)
        self._message_is_transient = transient and bool(translated)
        if show_dialog:
            QMessageBox.information(self, self.tr("Terms"), translated)

    def _clear_transient_message(self) -> None:
        if not self._message_is_transient:
            return
        self.table_panel.clear_message()
        self._message_is_transient = False

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
            self._refresh_toolbar_state()
        self._update_bulk_button_state()
        return True

    def _refresh_toolbar_state(self) -> None:
        if self._state is None:
            return
        toolbar = self._service.get_toolbar_state(
            self.project_id,
            document_id=self.document_id,
            rows=self._state.rows,
        )
        self._state = self._state.model_copy(update={"toolbar": toolbar})
        self._apply_toolbar_state(toolbar)

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

    def _ensure_add_terms_dialog(self) -> _AddTermsDialog:
        if self._add_terms_dialog is None:
            self._add_terms_dialog = _AddTermsDialog(self.window())
            self._add_terms_dialog.submitted.connect(self._on_add_terms_submitted)
        return self._add_terms_dialog

    def _on_add_terms_submitted(self, term: str, translation: str) -> None:
        dialog = self._ensure_add_terms_dialog()
        tracks_invalidation = self._event_bridge is not None
        if tracks_invalidation:
            self._pending_local_terms_invalidations += 1
        try:
            result = self._service.upsert_project_term(
                UpsertProjectTermRequest(project_id=self.project_id, term=term, translation=translation)
            )
        except ApplicationError as exc:
            dialog.show_status(UserMessageSeverity.ERROR, translate_backend_text(exc.payload.message))
            return
        finally:
            if tracks_invalidation:
                self._pending_local_terms_invalidations = max(0, self._pending_local_terms_invalidations - 1)
        self._apply_state(result.state)
        dialog.handle_submit_success(updated_existing=result.updated_existing)
