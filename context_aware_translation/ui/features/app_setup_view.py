from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionSummary,
    ConnectionTestRequest,
    ConnectionTestResult,
    ProviderCard,
    SaveConnectionRequest,
    SetupWizardRequest,
    SetupWizardState,
)
from context_aware_translation.application.contracts.common import (
    CapabilityAvailability,
    CapabilityCode,
    ProviderKind,
    UserMessageSeverity,
)
from context_aware_translation.application.services.app_setup import AppSetupService
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets.collapsible_section import CollapsibleSection

_PROVIDER_DEFAULTS: dict[ProviderKind, tuple[str, str]] = {
    ProviderKind.GEMINI: ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3-flash-preview"),
    ProviderKind.OPENAI: ("https://api.openai.com/v1", "gpt-4.1-mini"),
    ProviderKind.DEEPSEEK: ("https://api.deepseek.com", "deepseek-chat"),
    ProviderKind.ANTHROPIC: ("https://api.anthropic.com/v1", "claude-3-5-sonnet-latest"),
    ProviderKind.OPENAI_COMPATIBLE: ("", ""),
}

_PROVIDER_LABELS: dict[ProviderKind, str] = {
    ProviderKind.GEMINI: "Gemini",
    ProviderKind.OPENAI: "OpenAI",
    ProviderKind.DEEPSEEK: "DeepSeek",
    ProviderKind.ANTHROPIC: "Anthropic",
    ProviderKind.OPENAI_COMPATIBLE: "OpenAI-compatible / Custom",
}

_CAPABILITY_LABELS: dict[CapabilityCode, str] = {
    CapabilityCode.TRANSLATION: "Translation",
    CapabilityCode.IMAGE_TEXT_READING: "Image text reading",
    CapabilityCode.IMAGE_EDITING: "Image editing",
    CapabilityCode.REASONING_AND_REVIEW: "Reasoning and review",
}

_AVAILABILITY_LABELS: dict[CapabilityAvailability, str] = {
    CapabilityAvailability.READY: "Ready",
    CapabilityAvailability.MISSING: "Missing",
    CapabilityAvailability.PARTIAL: "Partial",
    CapabilityAvailability.UNSUPPORTED_FOR_WORKFLOW: "Unsupported",
}

_STATUS_COLORS = {
    CapabilityAvailability.READY: "#15803d",
    CapabilityAvailability.PARTIAL: "#b45309",
    CapabilityAvailability.MISSING: "#b91c1c",
    CapabilityAvailability.UNSUPPORTED_FOR_WORKFLOW: "#6b7280",
}


class ConnectionDraftForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        self._on_provider_changed(0)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self.display_name_edit = QLineEdit()
        self.provider_combo = QComboBox()
        for provider in ProviderKind:
            self.provider_combo.addItem(_PROVIDER_LABELS[provider], provider)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(self.tr("Paste API key"))

        form.addRow(self.tr("Connection name"), self.display_name_edit)
        form.addRow(self.tr("Provider"), self.provider_combo)
        form.addRow(self.tr("API key"), self.api_key_edit)
        layout.addLayout(form)

        self.advanced_section = CollapsibleSection(self.tr("Advanced"))
        advanced_widget = QWidget()
        advanced_form = QFormLayout(advanced_widget)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(self.tr("Base URL"))
        self.default_model_edit = QLineEdit()
        self.default_model_edit.setPlaceholderText(self.tr("Default model"))
        self.advanced_note = create_tip_label(
            self.tr("Known providers are prefilled. Change these only if you need custom endpoint or model settings.")
        )
        advanced_form.addRow(self.tr("Base URL"), self.base_url_edit)
        advanced_form.addRow(self.tr("Default model"), self.default_model_edit)
        advanced_form.addRow(self.advanced_note)
        self.advanced_section.set_content(advanced_widget)
        layout.addWidget(self.advanced_section)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

    def set_draft(self, draft: ConnectionDraft, *, preserve_api_key_placeholder: bool = True) -> None:
        self.display_name_edit.setText(draft.display_name)
        index = self.provider_combo.findData(draft.provider)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        self.api_key_edit.setText(draft.api_key or "")
        if preserve_api_key_placeholder and draft.api_key is None:
            self.api_key_edit.setPlaceholderText(self.tr("Leave blank to keep the current key"))
        self.base_url_edit.setText(draft.base_url or "")
        self.default_model_edit.setText(draft.default_model or "")
        self._sync_advanced_visibility(draft.provider)

    def to_draft(self, *, allow_empty_api_key: bool = True) -> ConnectionDraft:
        api_key = self.api_key_edit.text().strip()
        return ConnectionDraft(
            display_name=self.display_name_edit.text().strip(),
            provider=self.current_provider(),
            api_key=(api_key if api_key else (None if allow_empty_api_key else "")),
            base_url=self.base_url_edit.text().strip() or None,
            default_model=self.default_model_edit.text().strip() or None,
        )

    def current_provider(self) -> ProviderKind:
        provider = self.provider_combo.currentData()
        return provider if isinstance(provider, ProviderKind) else ProviderKind.OPENAI_COMPATIBLE

    def validate(self, *, require_api_key: bool) -> tuple[bool, str | None]:
        draft = self.to_draft(allow_empty_api_key=not require_api_key)
        if not draft.display_name:
            return False, self.tr("Connection name is required.")
        if require_api_key and not draft.api_key:
            return False, self.tr("API key is required.")
        if draft.provider is ProviderKind.OPENAI_COMPATIBLE and (not draft.base_url or not draft.default_model):
            return False, self.tr("Custom connections require base URL and default model.")
        return True, None

    def _on_provider_changed(self, _index: int) -> None:
        provider = self.current_provider()
        default_base_url, default_model = _PROVIDER_DEFAULTS[provider]
        self.base_url_edit.setText(default_base_url)
        self.default_model_edit.setText(default_model)
        if not self.display_name_edit.text().strip() or self.display_name_edit.text().strip() in _PROVIDER_LABELS.values():
            self.display_name_edit.setText(_PROVIDER_LABELS[provider])
        self._sync_advanced_visibility(provider)

    def _sync_advanced_visibility(self, provider: ProviderKind) -> None:
        custom = provider is ProviderKind.OPENAI_COMPATIBLE
        self.advanced_section.set_expanded(custom)


class ConnectionEditorDialog(QDialog):
    def __init__(
        self,
        *,
        draft: ConnectionDraft | None = None,
        connection_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self.setWindowTitle(self.tr("Connection"))
        self.resize(520, 320)
        self.form = ConnectionDraftForm(self)
        if draft is not None:
            self.form.set_draft(draft)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._accept_if_valid)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def request(self) -> SaveConnectionRequest:
        return SaveConnectionRequest(connection=self.form.to_draft(), connection_id=self._connection_id)

    def _accept_if_valid(self) -> None:
        valid, message = self.form.validate(require_api_key=self._connection_id is None)
        if not valid:
            QMessageBox.warning(self, self.tr("Missing Information"), message or self.tr("Please complete the form."))
            return
        self.accept()


class SetupWizardDialog(QDialog):
    def __init__(self, service: AppSetupService, initial_state: SetupWizardState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._wizard_state = initial_state
        self._preview_state: SetupWizardState | None = None
        self.setWindowTitle(self.tr("Setup Wizard"))
        self.resize(760, 620)
        self._init_ui()
        self._populate_provider_cards(initial_state.available_providers)
        self._update_buttons()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr("Tell the app which providers you already have. The wizard will test capabilities and generate a recommended default routing."),
        )
        layout.addWidget(self.tip_label)

        self.step_title = QLabel()
        self.step_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(self.step_title)

        self.page_stack = QScrollArea()
        self.page_stack.setWidgetResizable(True)
        self.page_content = QWidget()
        self.page_layout = QVBoxLayout(self.page_content)
        self.page_stack.setWidget(self.page_content)
        layout.addWidget(self.page_stack, 1)

        self.button_box = QDialogButtonBox()
        self.back_button = self.button_box.addButton(self.tr("Back"), QDialogButtonBox.ButtonRole.ActionRole)
        self.next_button = self.button_box.addButton(self.tr("Next"), QDialogButtonBox.ButtonRole.ActionRole)
        self.finish_button = self.button_box.addButton(self.tr("Save Setup"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = self.button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.back_button.clicked.connect(self._go_back)
        self.next_button.clicked.connect(self._go_next)
        self.finish_button.clicked.connect(self._finish)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.button_box)

        self._page_index = 0
        self._provider_checks: dict[ProviderKind, QCheckBox] = {}
        self._draft_forms: list[ConnectionDraftForm] = []
        self._page_widgets: list[QWidget] = []
        self._build_page()

    def _build_page(self) -> None:
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets.clear()
        if self._page_index == 0:
            self.step_title.setText(self.tr("Choose providers"))
            card_host = QWidget()
            card_layout = QVBoxLayout(card_host)
            card_layout.setSpacing(12)
            for checkbox in self._provider_checks.values():
                card_layout.addWidget(checkbox)
            card_layout.addStretch()
            self.page_layout.addWidget(card_host)
        elif self._page_index == 1:
            self.step_title.setText(self.tr("Enter connection details"))
            self._draft_forms.clear()
            for provider in self.selected_providers():
                group = QGroupBox(_PROVIDER_LABELS[provider])
                group_layout = QVBoxLayout(group)
                form = ConnectionDraftForm(group)
                default_base_url, default_model = _PROVIDER_DEFAULTS[provider]
                form.set_draft(
                    ConnectionDraft(
                        display_name=_PROVIDER_LABELS[provider],
                        provider=provider,
                        base_url=default_base_url or None,
                        default_model=default_model or None,
                    ),
                    preserve_api_key_placeholder=False,
                )
                group_layout.addWidget(form)
                self._draft_forms.append(form)
                self.page_layout.addWidget(group)
            self.page_layout.addStretch()
        else:
            self._ensure_preview_state()
            self.step_title.setText(self.tr("Review capabilities and routing"))
            preview = self._preview_state
            if preview is None:
                return
            for result in preview.test_results:
                result_group = QGroupBox(result.connection_label)
                result_layout = QVBoxLayout(result_group)
                if result.message is not None:
                    result_layout.addWidget(create_tip_label(result.message.text))
                grid = QGridLayout()
                for row, capability in enumerate(result.capabilities):
                    grid.addWidget(QLabel(_CAPABILITY_LABELS[capability.capability]), row, 0)
                    status = QLabel(_AVAILABILITY_LABELS[capability.availability])
                    status.setStyleSheet(f"color: {_STATUS_COLORS.get(capability.availability, '#111827')}; font-weight: 600;")
                    grid.addWidget(status, row, 1)
                    grid.addWidget(QLabel(capability.message or ""), row, 2)
                result_layout.addLayout(grid)
                self.page_layout.addWidget(result_group)
            routes_group = QGroupBox(self.tr("Recommended routing"))
            routes_layout = QVBoxLayout(routes_group)
            routes_table = QTableWidget(0, 2)
            routes_table.setHorizontalHeaderLabels([self.tr("Capability"), self.tr("Connection")])
            routes_table.verticalHeader().setVisible(False)
            routes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            for route in preview.recommendation.routes if preview.recommendation is not None else []:
                row = routes_table.rowCount()
                routes_table.insertRow(row)
                routes_table.setItem(row, 0, QTableWidgetItem(_CAPABILITY_LABELS[route.capability]))
                routes_table.setItem(row, 1, QTableWidgetItem(route.connection_label))
            routes_layout.addWidget(routes_table)
            for note in preview.recommendation.notes if preview.recommendation is not None else []:
                routes_layout.addWidget(create_tip_label(note))
            self.page_layout.addWidget(routes_group)
            self.page_layout.addStretch()
        self._update_buttons()

    def selected_providers(self) -> list[ProviderKind]:
        return [provider for provider, checkbox in self._provider_checks.items() if checkbox.isChecked()]

    def final_request(self) -> SetupWizardRequest | None:
        if self._preview_state is None:
            return None
        return SetupWizardRequest(
            providers=self.selected_providers(),
            connections=[form.to_draft(allow_empty_api_key=False) for form in self._draft_forms],
        )

    def _populate_provider_cards(self, providers: Sequence[ProviderCard]) -> None:
        self._provider_checks.clear()
        for provider in providers:
            checkbox = QCheckBox(provider.label)
            checkbox.setToolTip(provider.helper_text or "")
            checkbox.setProperty("provider", provider.provider.value)
            if provider.helper_text:
                checkbox.setText(f"{provider.label} — {provider.helper_text}")
            self._provider_checks[provider.provider] = checkbox

    def _go_back(self) -> None:
        if self._page_index == 0:
            return
        self._page_index -= 1
        self._build_page()

    def _go_next(self) -> None:
        if self._page_index == 0:
            if not self.selected_providers():
                QMessageBox.warning(self, self.tr("No Providers Selected"), self.tr("Select at least one provider to continue."))
                return
        elif self._page_index == 1:
            for form in self._draft_forms:
                valid, message = form.validate(require_api_key=True)
                if not valid:
                    QMessageBox.warning(self, self.tr("Missing Information"), message or self.tr("Please complete the form."))
                    return
            self._preview_state = None
        self._page_index = min(self._page_index + 1, 2)
        self._build_page()

    def _finish(self) -> None:
        request = self.final_request()
        if request is None:
            QMessageBox.warning(self, self.tr("Wizard Incomplete"), self.tr("Review the recommended routing before saving setup."))
            return
        self._service.run_setup_wizard(request)
        self.accept()

    def _ensure_preview_state(self) -> None:
        if self._preview_state is not None:
            return
        self._preview_state = self._service.preview_setup_wizard(
            SetupWizardRequest(
                providers=self.selected_providers(),
                connections=[form.to_draft(allow_empty_api_key=False) for form in self._draft_forms],
            )
        )

    def _update_buttons(self) -> None:
        self.back_button.setVisible(self._page_index > 0)
        self.next_button.setVisible(self._page_index < 2)
        self.finish_button.setVisible(self._page_index == 2)


class AppSetupView(QWidget):
    def __init__(self, service: AppSetupService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._state: AppSetupState | None = None
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        toolbar = QHBoxLayout()
        self.run_wizard_button = QPushButton(self.tr("Run Setup Wizard"))
        self.run_wizard_button.clicked.connect(self._on_run_wizard)
        self.add_connection_button = QPushButton(self.tr("Add Connection"))
        self.add_connection_button.clicked.connect(self._on_add_connection)
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.run_wizard_button)
        toolbar.addWidget(self.add_connection_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.summary_label = create_tip_label("")
        layout.addWidget(self.summary_label)

        self.connections_group = QGroupBox(self.tr("Connections"))
        connections_layout = QVBoxLayout(self.connections_group)
        self.connections_table = QTableWidget(0, 5)
        self.connections_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Provider"), self.tr("Status"), self.tr("Model"), self.tr("Base URL")]
        )
        self.connections_table.verticalHeader().setVisible(False)
        self.connections_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.connections_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.connections_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.connections_table.itemSelectionChanged.connect(self._update_connection_buttons)
        connections_layout.addWidget(self.connections_table)
        connection_actions = QHBoxLayout()
        self.edit_connection_button = QPushButton(self.tr("Edit"))
        self.edit_connection_button.clicked.connect(self._on_edit_connection)
        self.test_connection_button = QPushButton(self.tr("Test"))
        self.test_connection_button.clicked.connect(self._on_test_connection)
        self.delete_connection_button = QPushButton(self.tr("Delete"))
        self.delete_connection_button.clicked.connect(self._on_delete_connection)
        connection_actions.addWidget(self.edit_connection_button)
        connection_actions.addWidget(self.test_connection_button)
        connection_actions.addWidget(self.delete_connection_button)
        connection_actions.addStretch()
        connections_layout.addLayout(connection_actions)
        layout.addWidget(self.connections_group)

        self.capabilities_group = QGroupBox(self.tr("Capability coverage"))
        capabilities_layout = QVBoxLayout(self.capabilities_group)
        self.capabilities_table = QTableWidget(0, 4)
        self.capabilities_table.setHorizontalHeaderLabels(
            [self.tr("Capability"), self.tr("Status"), self.tr("Connection"), self.tr("Message")]
        )
        self.capabilities_table.verticalHeader().setVisible(False)
        self.capabilities_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        capabilities_layout.addWidget(self.capabilities_table)
        layout.addWidget(self.capabilities_group)

        self.routes_group = QGroupBox(self.tr("Default routing"))
        routes_layout = QVBoxLayout(self.routes_group)
        self.routes_table = QTableWidget(0, 2)
        self.routes_table.setHorizontalHeaderLabels([self.tr("Capability"), self.tr("Connection")])
        self.routes_table.verticalHeader().setVisible(False)
        self.routes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        routes_layout.addWidget(self.routes_table)
        layout.addWidget(self.routes_group)

        self.advanced_section = CollapsibleSection(self.tr("Advanced"))
        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)
        self.advanced_label = create_tip_label(
            self.tr("Advanced endpoint and model settings are edited per connection. Use Add or Edit, then expand Advanced inside the connection dialog.")
        )
        self.seed_defaults_button = QPushButton(self.tr("Seed System Defaults"))
        self.seed_defaults_button.clicked.connect(self._on_seed_defaults)
        advanced_layout.addWidget(self.advanced_label)
        advanced_layout.addWidget(self.seed_defaults_button)
        advanced_layout.addStretch()
        self.advanced_section.set_content(advanced_content)
        layout.addWidget(self.advanced_section)

        layout.addStretch()
        self._update_connection_buttons()

    def refresh(self) -> None:
        self._state = self._service.get_state()
        self._populate_connections(self._state.connections)
        self._populate_capabilities(self._state)
        self._populate_routes(self._state)
        self.summary_label.setText(self._summary_text(self._state))
        self.run_wizard_button.setText(self.tr("Run Setup Wizard") if self._state.requires_wizard else self.tr("Open Setup Wizard"))
        self._update_connection_buttons()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.run_wizard_button.setText(self.tr("Run Setup Wizard") if self._state and self._state.requires_wizard else self.tr("Open Setup Wizard"))
        self.add_connection_button.setText(self.tr("Add Connection"))
        self.refresh_button.setText(self.tr("Refresh"))
        self.connections_group.setTitle(self.tr("Connections"))
        self.connections_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Provider"), self.tr("Status"), self.tr("Model"), self.tr("Base URL")]
        )
        self.edit_connection_button.setText(self.tr("Edit"))
        self.test_connection_button.setText(self.tr("Test"))
        self.delete_connection_button.setText(self.tr("Delete"))
        self.capabilities_group.setTitle(self.tr("Capability coverage"))
        self.capabilities_table.setHorizontalHeaderLabels(
            [self.tr("Capability"), self.tr("Status"), self.tr("Connection"), self.tr("Message")]
        )
        self.routes_group.setTitle(self.tr("Default routing"))
        self.routes_table.setHorizontalHeaderLabels([self.tr("Capability"), self.tr("Connection")])
        self.advanced_section.toggle_button.setText(self.tr("Advanced"))
        self.advanced_label.setText(
            self.tr("Advanced endpoint and model settings are edited per connection. Use Add or Edit, then expand Advanced inside the connection dialog.")
        )
        self.seed_defaults_button.setText(self.tr("Seed System Defaults"))
        if self._state is not None:
            self.summary_label.setText(self._summary_text(self._state))
            self._populate_capabilities(self._state)
            self._populate_routes(self._state)

    def _populate_connections(self, connections: Sequence[ConnectionSummary]) -> None:
        self.connections_table.setRowCount(0)
        for connection in connections:
            row = self.connections_table.rowCount()
            self.connections_table.insertRow(row)
            self._set_table_item(self.connections_table, row, 0, connection.display_name, connection.connection_id)
            self._set_table_item(self.connections_table, row, 1, _PROVIDER_LABELS.get(connection.provider, connection.provider.value))
            self._set_table_item(self.connections_table, row, 2, connection.status.value.replace("_", " ").title())
            self._set_table_item(self.connections_table, row, 3, connection.default_model or "")
            self._set_table_item(self.connections_table, row, 4, connection.base_url or "")
        self.connections_table.resizeColumnsToContents()

    def _populate_capabilities(self, state: AppSetupState) -> None:
        self.capabilities_table.setRowCount(0)
        for capability in state.capabilities:
            row = self.capabilities_table.rowCount()
            self.capabilities_table.insertRow(row)
            self._set_table_item(self.capabilities_table, row, 0, _CAPABILITY_LABELS[capability.capability])
            status_item = QTableWidgetItem(_AVAILABILITY_LABELS[capability.availability])
            status_item.setForeground(Qt.GlobalColor.black)
            self.capabilities_table.setItem(row, 1, status_item)
            self._set_table_item(self.capabilities_table, row, 2, capability.connection_label or "")
            self._set_table_item(self.capabilities_table, row, 3, capability.message or "")
        self.capabilities_table.resizeColumnsToContents()

    def _populate_routes(self, state: AppSetupState) -> None:
        self.routes_table.setRowCount(0)
        for route in state.default_routes:
            row = self.routes_table.rowCount()
            self.routes_table.insertRow(row)
            self._set_table_item(self.routes_table, row, 0, _CAPABILITY_LABELS[route.capability])
            self._set_table_item(self.routes_table, row, 1, route.connection_label)
        self.routes_table.resizeColumnsToContents()

    def _selected_connection(self) -> ConnectionSummary | None:
        rows = self.connections_table.selectionModel().selectedRows()
        if not rows or self._state is None:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._state.connections):
            return None
        return self._state.connections[row]

    def _update_connection_buttons(self) -> None:
        selected = self._selected_connection() is not None
        self.edit_connection_button.setEnabled(selected)
        self.test_connection_button.setEnabled(selected)
        self.delete_connection_button.setEnabled(selected)

    def _on_run_wizard(self) -> None:
        dialog = SetupWizardDialog(self._service, self._service.get_wizard_state(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _on_add_connection(self) -> None:
        dialog = ConnectionEditorDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._service.save_connection(dialog.request())
            self.refresh()

    def _on_edit_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        dialog = ConnectionEditorDialog(
            draft=ConnectionDraft(
                display_name=connection.display_name,
                provider=connection.provider,
                base_url=connection.base_url,
                default_model=connection.default_model,
            ),
            connection_id=connection.connection_id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._service.save_connection(dialog.request())
            self.refresh()

    def _on_test_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        result = self._service.test_connection(
            ConnectionTestRequest(
                connection=ConnectionDraft(
                    display_name=connection.display_name,
                    provider=connection.provider,
                    base_url=connection.base_url,
                    default_model=connection.default_model,
                )
            )
        )
        self._show_test_result(result)

    def _on_delete_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        result = QMessageBox.question(
            self,
            self.tr("Delete Connection"),
            self.tr("Delete the selected connection? Existing projects may stop working until setup is fixed."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._service.delete_connection(connection.connection_id)
        self.refresh()

    def _on_seed_defaults(self) -> None:
        command = self._service.seed_defaults()
        if command.message is not None:
            self._show_message(command.message.severity, command.message.text)
        self.refresh()

    def _show_test_result(self, result: ConnectionTestResult) -> None:
        lines = [result.connection_label]
        for capability in result.capabilities:
            lines.append(
                f"- {_CAPABILITY_LABELS[capability.capability]}: {_AVAILABILITY_LABELS[capability.availability]}"
            )
        if result.recommendation is not None and result.recommendation.routes:
            lines.append("")
            lines.append(self.tr("Recommended routing:"))
            for route in result.recommendation.routes:
                lines.append(f"- {_CAPABILITY_LABELS[route.capability]} -> {route.connection_label}")
        if result.message is not None:
            self._show_message(result.message.severity, "\n".join(lines + ["", result.message.text]))
        else:
            self._show_message(UserMessageSeverity.INFO, "\n".join(lines))

    def _show_message(self, severity: UserMessageSeverity, text: str) -> None:
        if severity is UserMessageSeverity.ERROR:
            QMessageBox.critical(self, self.tr("App Setup"), text)
        elif severity is UserMessageSeverity.WARNING:
            QMessageBox.warning(self, self.tr("App Setup"), text)
        else:
            QMessageBox.information(self, self.tr("App Setup"), text)

    def _set_table_item(self, table: QTableWidget, row: int, column: int, text: str, user_data: str | None = None) -> None:
        item = QTableWidgetItem(text)
        if user_data is not None:
            item.setData(Qt.ItemDataRole.UserRole, user_data)
        table.setItem(row, column, item)

    def _summary_text(self, state: AppSetupState) -> str:
        ready_capabilities = sum(1 for capability in state.capabilities if capability.availability is CapabilityAvailability.READY)
        if state.requires_wizard:
            return self.tr("No connections are configured yet. Run the setup wizard to create app-wide defaults.")
        return (
            f"{len(state.connections)} "
            + self.tr("connections configured.")
            + f" {ready_capabilities}/{len(state.capabilities)} "
            + self.tr("capabilities ready.")
        )

    def _tip_text(self) -> str:
        return self.tr(
            "App Setup manages reusable provider connections and default routing. Set this up once, then reuse it across projects."
        )
