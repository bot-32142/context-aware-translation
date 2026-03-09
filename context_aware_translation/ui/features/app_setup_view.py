from __future__ import annotations

import json
from collections.abc import Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
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
    SaveWorkflowProfileRequest,
    SetupWizardRequest,
    SetupWizardState,
    WorkflowProfileDetail,
)
from context_aware_translation.application.contracts.common import (
    CapabilityAvailability,
    CapabilityCode,
    ProviderKind,
    UserMessageSeverity,
)
from context_aware_translation.application.services.app_setup import AppSetupService
from context_aware_translation.ui.features.workflow_profile_editor import ConnectionChoice, WorkflowProfileEditorDialog
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


class ConnectionDraftForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        self._on_provider_changed(0)

    def _create_token_limit_row(self) -> tuple[QWidget, QCheckBox, QSpinBox]:
        layout = QHBoxLayout()
        checkbox = QCheckBox(self.tr("Enable"))
        spinner = QSpinBox()
        spinner.setRange(1, 999_999_999)
        spinner.setValue(1_000_000)
        spinner.setEnabled(False)
        checkbox.toggled.connect(spinner.setEnabled)
        layout.addWidget(checkbox)
        layout.addWidget(spinner)
        layout.addStretch()
        widget = QWidget()
        widget.setLayout(layout)
        return widget, checkbox, spinner

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self.display_name_edit = QLineEdit()
        self.provider_combo = QComboBox()
        for provider in ProviderKind:
            self.provider_combo.addItem(_PROVIDER_LABELS[provider], provider.value)
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
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(60)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(self.tr("Base URL"))
        self.default_model_edit = QLineEdit()
        self.default_model_edit.setPlaceholderText(self.tr("Default model"))
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.0)
        self.custom_parameters_edit = QTextEdit()
        self.custom_parameters_edit.setMaximumHeight(90)
        self.custom_parameters_edit.setPlaceholderText('{"reasoning_effort": "none"}')
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix(self.tr(" s"))
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(3)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 50)
        self.concurrency_spin.setValue(5)
        self.total_limit_widget, self.total_limit_checkbox, self.total_limit_spin = self._create_token_limit_row()
        self.input_limit_widget, self.input_limit_checkbox, self.input_limit_spin = self._create_token_limit_row()
        self.output_limit_widget, self.output_limit_checkbox, self.output_limit_spin = self._create_token_limit_row()
        self.advanced_note = create_tip_label(
            self.tr(
                "Advanced matches the old endpoint-profile model: timeout, retries, concurrency, token limits, and custom JSON parameters."
            )
        )
        advanced_form.addRow(self.tr("Description"), self.description_edit)
        advanced_form.addRow(self.tr("Base URL"), self.base_url_edit)
        advanced_form.addRow(self.tr("Default model"), self.default_model_edit)
        advanced_form.addRow(self.tr("Temperature"), self.temperature_spin)
        advanced_form.addRow(self.tr("Custom parameters"), self.custom_parameters_edit)
        advanced_form.addRow(self.tr("Timeout"), self.timeout_spin)
        advanced_form.addRow(self.tr("Max retries"), self.retries_spin)
        advanced_form.addRow(self.tr("Concurrency"), self.concurrency_spin)
        advanced_form.addRow(self.tr("Total token limit"), self.total_limit_widget)
        advanced_form.addRow(self.tr("Input token limit"), self.input_limit_widget)
        advanced_form.addRow(self.tr("Output token limit"), self.output_limit_widget)
        advanced_form.addRow(self.advanced_note)
        self.advanced_section.set_content(advanced_widget)
        layout.addWidget(self.advanced_section)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

    def set_draft(self, draft: ConnectionDraft, *, preserve_api_key_placeholder: bool = True) -> None:
        self.display_name_edit.setText(draft.display_name)
        index = self.provider_combo.findData(draft.provider.value)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        self.api_key_edit.setText(draft.api_key or "")
        if preserve_api_key_placeholder and draft.api_key is None:
            self.api_key_edit.setPlaceholderText(self.tr("Leave blank to keep the current key"))
        self.description_edit.setPlainText(draft.description or "")
        self.base_url_edit.setText(draft.base_url or "")
        self.default_model_edit.setText(draft.default_model or "")
        self.temperature_spin.setValue(draft.temperature)
        self.custom_parameters_edit.setPlainText(draft.custom_parameters_json or "")
        self.timeout_spin.setValue(draft.timeout)
        self.retries_spin.setValue(draft.max_retries)
        self.concurrency_spin.setValue(draft.concurrency)
        self.total_limit_checkbox.setChecked(draft.token_limit is not None)
        if draft.token_limit is not None:
            self.total_limit_spin.setValue(draft.token_limit)
        self.input_limit_checkbox.setChecked(draft.input_token_limit is not None)
        if draft.input_token_limit is not None:
            self.input_limit_spin.setValue(draft.input_token_limit)
        self.output_limit_checkbox.setChecked(draft.output_token_limit is not None)
        if draft.output_token_limit is not None:
            self.output_limit_spin.setValue(draft.output_token_limit)
        self._sync_advanced_visibility(draft.provider)

    def to_draft(self, *, allow_empty_api_key: bool = True) -> ConnectionDraft:
        api_key = self.api_key_edit.text().strip()
        return ConnectionDraft(
            display_name=self.display_name_edit.text().strip(),
            provider=self.current_provider(),
            description=self.description_edit.toPlainText().strip() or None,
            api_key=(api_key if api_key else (None if allow_empty_api_key else "")),
            base_url=self.base_url_edit.text().strip() or None,
            default_model=self.default_model_edit.text().strip() or None,
            temperature=float(self.temperature_spin.value()),
            timeout=int(self.timeout_spin.value()),
            max_retries=int(self.retries_spin.value()),
            concurrency=int(self.concurrency_spin.value()),
            token_limit=(int(self.total_limit_spin.value()) if self.total_limit_checkbox.isChecked() else None),
            input_token_limit=(int(self.input_limit_spin.value()) if self.input_limit_checkbox.isChecked() else None),
            output_token_limit=(int(self.output_limit_spin.value()) if self.output_limit_checkbox.isChecked() else None),
            custom_parameters_json=self.custom_parameters_edit.toPlainText().strip() or None,
        )

    def current_provider(self) -> ProviderKind:
        provider = self.provider_combo.currentData()
        if isinstance(provider, ProviderKind):
            return provider
        if isinstance(provider, str):
            try:
                return ProviderKind(provider)
            except ValueError:
                pass
        return ProviderKind.OPENAI_COMPATIBLE

    def validate(self, *, require_api_key: bool) -> tuple[bool, str | None]:
        draft = self.to_draft(allow_empty_api_key=not require_api_key)
        if not draft.display_name:
            return False, self.tr("Connection name is required.")
        if require_api_key and not draft.api_key:
            return False, self.tr("API key is required.")
        if draft.custom_parameters_json:
            try:
                parsed = json.loads(draft.custom_parameters_json)
            except json.JSONDecodeError:
                return False, self.tr("Custom parameters must be valid JSON.")
            if not isinstance(parsed, dict):
                return False, self.tr("Custom parameters must be a JSON object.")
        if draft.provider is ProviderKind.OPENAI_COMPATIBLE and (not draft.base_url or not draft.default_model):
            return False, self.tr("Custom connections require base URL and default model.")
        return True, None

    def _on_provider_changed(self, _index: int) -> None:
        provider = self.current_provider()
        default_base_url, default_model = _PROVIDER_DEFAULTS[provider]
        self.base_url_edit.setText(default_base_url)
        self.default_model_edit.setText(default_model)
        if (
            not self.display_name_edit.text().strip()
            or self.display_name_edit.text().strip() in _PROVIDER_LABELS.values()
        ):
            self.display_name_edit.setText(_PROVIDER_LABELS[provider])
        self._sync_advanced_visibility(provider)

    def _sync_advanced_visibility(self, provider: ProviderKind) -> None:
        self.advanced_section.set_expanded(provider is ProviderKind.OPENAI_COMPATIBLE)


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
        self.setMinimumWidth(460)
        self.resize(520, 640)
        self.form = ConnectionDraftForm(self)
        if draft is not None:
            self.form.set_draft(draft)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(self.form)
        layout.addWidget(scroll_area, 1)
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
        self.resize(780, 680)
        self._init_ui()
        self._populate_provider_cards(initial_state.available_providers)
        self._build_page()
        self._update_buttons()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr(
                "Tell the app which providers you already have. The wizard will test capabilities and create a concrete shared workflow profile."
            )
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
        self._available_providers: list[ProviderCard] = []
        self._provider_checks: dict[ProviderKind, QCheckBox] = {}
        self._draft_forms: list[ConnectionDraftForm] = []

    def _build_page(self) -> None:
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if self._page_index == 0:
            self.step_title.setText(self.tr("Choose providers"))
            self._provider_checks = {}
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setSpacing(12)
            for provider in self._available_providers:
                checkbox = QCheckBox(provider.label)
                checkbox.setToolTip(provider.helper_text or "")
                checkbox.setProperty("provider", provider.provider.value)
                checkbox.setChecked(provider.provider in self._wizard_state.selected_providers)
                if provider.helper_text:
                    checkbox.setText(f"{provider.label} — {provider.helper_text}")
                self._provider_checks[provider.provider] = checkbox
                host_layout.addWidget(checkbox)
            host_layout.addStretch()
            self.page_layout.addWidget(host)
        elif self._page_index == 1:
            self.step_title.setText(self.tr("Enter connection details"))
            self._draft_forms.clear()
            for provider in self._wizard_state.selected_providers:
                group = QGroupBox(_PROVIDER_LABELS[provider])
                group_layout = QVBoxLayout(group)
                form = ConnectionDraftForm(group)
                form.set_draft(self._draft_for_provider(provider), preserve_api_key_placeholder=False)
                group_layout.addWidget(form)
                self._draft_forms.append(form)
                self.page_layout.addWidget(group)
            self.page_layout.addStretch()
        else:
            self._ensure_preview_state()
            self.step_title.setText(self.tr("Review workflow profile"))
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
                    grid.addWidget(QLabel(_AVAILABILITY_LABELS[capability.availability]), row, 1)
                    grid.addWidget(QLabel(capability.message or ""), row, 2)
                result_layout.addLayout(grid)
                self.page_layout.addWidget(result_group)

            profile_group = QGroupBox(self.tr("Recommended workflow profile"))
            profile_layout = QVBoxLayout(profile_group)
            recommendation = preview.recommendation
            if recommendation is not None:
                profile_layout.addWidget(
                    create_tip_label(
                        self.tr("This will be saved as a shared workflow profile and can be reused across projects.")
                    )
                )
                table = QTableWidget(0, 3)
                table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
                table.verticalHeader().setVisible(False)
                table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                for route in recommendation.routes:
                    row = table.rowCount()
                    table.insertRow(row)
                    table.setItem(row, 0, QTableWidgetItem(route.step_label))
                    table.setItem(row, 1, QTableWidgetItem(route.connection_label or ""))
                    table.setItem(row, 2, QTableWidgetItem(route.model or ""))
                table.resizeColumnsToContents()
                profile_layout.addWidget(table)
            self.page_layout.addWidget(profile_group)
            self.page_layout.addStretch()
        self._update_buttons()

    def selected_providers(self) -> list[ProviderKind]:
        checked = [provider for provider, checkbox in self._provider_checks.items() if checkbox.isChecked()]
        return checked if checked else list(self._wizard_state.selected_providers)

    def _draft_for_provider(self, provider: ProviderKind) -> ConnectionDraft:
        for draft in self._wizard_state.drafts:
            if draft.provider is provider:
                return draft
        default_base_url, default_model = _PROVIDER_DEFAULTS[provider]
        return ConnectionDraft(
            display_name=_PROVIDER_LABELS[provider],
            provider=provider,
            base_url=default_base_url or None,
            default_model=default_model or None,
            temperature=0.0,
            timeout=60,
            max_retries=3,
            concurrency=5,
        )

    def _persist_drafts(self) -> None:
        if not self._draft_forms:
            return
        self._wizard_state = self._wizard_state.model_copy(
            update={"drafts": [form.to_draft(allow_empty_api_key=False) for form in self._draft_forms]}
        )

    def final_request(self) -> SetupWizardRequest | None:
        if self._preview_state is None:
            return None
        return SetupWizardRequest(
            providers=list(self._wizard_state.selected_providers),
            connections=list(self._wizard_state.drafts),
        )

    def _populate_provider_cards(self, providers: Sequence[ProviderCard]) -> None:
        self._available_providers = list(providers)

    def _go_back(self) -> None:
        if self._page_index == 0:
            return
        if self._page_index == 1:
            self._persist_drafts()
        self._page_index -= 1
        self._build_page()

    def _go_next(self) -> None:
        if self._page_index == 0:
            selected_providers = self.selected_providers()
            if not selected_providers:
                QMessageBox.warning(
                    self, self.tr("No Providers Selected"), self.tr("Select at least one provider to continue.")
                )
                return
            self._wizard_state = self._wizard_state.model_copy(update={"selected_providers": selected_providers})
        elif self._page_index == 1:
            for form in self._draft_forms:
                valid, message = form.validate(require_api_key=True)
                if not valid:
                    QMessageBox.warning(
                        self, self.tr("Missing Information"), message or self.tr("Please complete the form.")
                    )
                    return
            self._persist_drafts()
            self._preview_state = None
        self._page_index = min(self._page_index + 1, 2)
        self._build_page()

    def _finish(self) -> None:
        request = self.final_request()
        if request is None:
            QMessageBox.warning(
                self, self.tr("Wizard Incomplete"), self.tr("Review the recommended workflow profile before saving setup.")
            )
            return
        self._service.run_setup_wizard(request)
        self.accept()

    def _ensure_preview_state(self) -> None:
        if self._preview_state is not None:
            return
        self._persist_drafts()
        self._preview_state = self._service.preview_setup_wizard(
            SetupWizardRequest(
                providers=list(self._wizard_state.selected_providers),
                connections=list(self._wizard_state.drafts),
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

        self.summary_label = create_tip_label("")
        layout.addWidget(self.summary_label)

        self.setup_tabs = QTabWidget()
        layout.addWidget(self.setup_tabs, 1)

        self.connections_tab = QWidget()
        connections_tab_layout = QVBoxLayout(self.connections_tab)
        connections_toolbar = QHBoxLayout()
        self.run_wizard_button = QPushButton(self.tr("Run Setup Wizard"))
        self.run_wizard_button.clicked.connect(self._on_run_wizard)
        self.add_connection_button = QPushButton(self.tr("Add Connection"))
        self.add_connection_button.clicked.connect(self._on_add_connection)
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        connections_toolbar.addWidget(self.run_wizard_button)
        connections_toolbar.addWidget(self.add_connection_button)
        connections_toolbar.addWidget(self.refresh_button)
        connections_toolbar.addStretch()
        connections_tab_layout.addLayout(connections_toolbar)

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
        connections_tab_layout.addWidget(self.connections_group)

        self.profiles_group = QGroupBox(self.tr("Shared workflow profiles"))
        profiles_layout = QVBoxLayout(self.profiles_group)
        self.profiles_table = QTableWidget(0, 4)
        self.profiles_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Target language"), self.tr("Preset"), self.tr("Default")]
        )
        self.profiles_table.verticalHeader().setVisible(False)
        self.profiles_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.profiles_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.profiles_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.profiles_table.itemSelectionChanged.connect(self._update_profile_buttons)
        profiles_layout.addWidget(self.profiles_table)
        profile_actions = QHBoxLayout()
        self.edit_profile_button = QPushButton(self.tr("Edit workflow profile"))
        self.edit_profile_button.clicked.connect(self._on_edit_profile)
        profile_actions.addWidget(self.edit_profile_button)
        profile_actions.addStretch()
        profiles_layout.addLayout(profile_actions)

        self.profiles_tab = QWidget()
        profiles_tab_layout = QVBoxLayout(self.profiles_tab)
        profiles_tab_layout.addWidget(self.profiles_group)
        profiles_tab_layout.addStretch()
        connections_tab_layout.addStretch()

        self.setup_tabs.addTab(self.connections_tab, self.tr("Connections"))
        self.setup_tabs.addTab(self.profiles_tab, self.tr("Workflow Profiles"))
        self._update_connection_buttons()
        self.edit_profile_button.setEnabled(False)

    def refresh(self) -> None:
        self._state = self._service.get_state()
        self._populate_connections(self._state.connections)
        self._populate_profiles(self._state)
        self.summary_label.setText(self._summary_text(self._state))
        self.run_wizard_button.setText(
            self.tr("Run Setup Wizard") if self._state.requires_wizard else self.tr("Open Setup Wizard")
        )
        self._update_connection_buttons()
        self._update_profile_buttons()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.run_wizard_button.setText(
            self.tr("Run Setup Wizard") if self._state and self._state.requires_wizard else self.tr("Open Setup Wizard")
        )
        self.add_connection_button.setText(self.tr("Add Connection"))
        self.refresh_button.setText(self.tr("Refresh"))
        self.setup_tabs.setTabText(self.setup_tabs.indexOf(self.connections_tab), self.tr("Connections"))
        self.setup_tabs.setTabText(self.setup_tabs.indexOf(self.profiles_tab), self.tr("Workflow Profiles"))
        self.connections_group.setTitle(self.tr("Connections"))
        self.connections_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Provider"), self.tr("Status"), self.tr("Model"), self.tr("Base URL")]
        )
        self.edit_connection_button.setText(self.tr("Edit"))
        self.test_connection_button.setText(self.tr("Test"))
        self.delete_connection_button.setText(self.tr("Delete"))
        self.profiles_group.setTitle(self.tr("Shared workflow profiles"))
        self.profiles_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Target language"), self.tr("Preset"), self.tr("Default")]
        )
        self.edit_profile_button.setText(self.tr("Edit workflow profile"))
        if self._state is not None:
            self.summary_label.setText(self._summary_text(self._state))
            self._populate_profiles(self._state)
            self._update_profile_buttons()

    def _populate_connections(self, connections: Sequence[ConnectionSummary]) -> None:
        self.connections_table.setRowCount(0)
        for connection in connections:
            row = self.connections_table.rowCount()
            self.connections_table.insertRow(row)
            self._set_table_item(self.connections_table, row, 0, connection.display_name, connection.connection_id)
            self._set_table_item(
                self.connections_table, row, 1, _PROVIDER_LABELS.get(connection.provider, connection.provider.value)
            )
            self._set_table_item(self.connections_table, row, 2, connection.status.value.replace("_", " ").title())
            self._set_table_item(self.connections_table, row, 3, connection.default_model or "")
            self._set_table_item(self.connections_table, row, 4, connection.base_url or "")
        self.connections_table.resizeColumnsToContents()

    def _populate_profiles(self, state: AppSetupState) -> None:
        self.profiles_table.setRowCount(0)
        for profile in state.shared_profiles:
            row = self.profiles_table.rowCount()
            self.profiles_table.insertRow(row)
            self._set_table_item(self.profiles_table, row, 0, profile.name, profile.profile_id)
            self._set_table_item(self.profiles_table, row, 1, profile.target_language)
            self._set_table_item(self.profiles_table, row, 2, profile.preset.value)
            self._set_table_item(self.profiles_table, row, 3, self.tr("Yes") if profile.is_default else "")
        self.profiles_table.resizeColumnsToContents()

        selected_id = state.selected_profile.profile_id if state.selected_profile is not None else state.default_profile_id
        if selected_id:
            for row in range(self.profiles_table.rowCount()):
                item = self.profiles_table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == selected_id:
                    self.profiles_table.selectRow(row)
                    break

    def _selected_connection(self) -> ConnectionSummary | None:
        rows = self.connections_table.selectionModel().selectedRows()
        if not rows or self._state is None:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._state.connections):
            return None
        return self._state.connections[row]

    def _selected_profile(self) -> WorkflowProfileDetail | None:
        rows = self.profiles_table.selectionModel().selectedRows()
        if not rows or self._state is None:
            return self._state.selected_profile if self._state is not None else None
        row = rows[0].row()
        if row < 0 or row >= len(self._state.shared_profiles):
            return None
        return self._state.shared_profiles[row]

    def _update_connection_buttons(self) -> None:
        selected = self._selected_connection() is not None
        self.edit_connection_button.setEnabled(selected)
        self.test_connection_button.setEnabled(selected)
        self.delete_connection_button.setEnabled(selected)

    def _update_profile_buttons(self) -> None:
        profile = self._selected_profile()
        self.edit_profile_button.setEnabled(profile is not None)

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
                description=connection.description,
                base_url=connection.base_url,
                default_model=connection.default_model,
                temperature=connection.temperature,
                timeout=connection.timeout,
                max_retries=connection.max_retries,
                concurrency=connection.concurrency,
                token_limit=connection.token_limit,
                input_token_limit=connection.input_token_limit,
                output_token_limit=connection.output_token_limit,
                custom_parameters_json=connection.custom_parameters_json,
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
                    description=connection.description,
                    base_url=connection.base_url,
                    default_model=connection.default_model,
                    temperature=connection.temperature,
                    timeout=connection.timeout,
                    max_retries=connection.max_retries,
                    concurrency=connection.concurrency,
                    token_limit=connection.token_limit,
                    input_token_limit=connection.input_token_limit,
                    output_token_limit=connection.output_token_limit,
                    custom_parameters_json=connection.custom_parameters_json,
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
            self.tr("Delete the selected connection? Existing profiles or projects may stop working until setup is fixed."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._service.delete_connection(connection.connection_id)
        self.refresh()

    def _on_edit_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None or self._state is None:
            return
        dialog = WorkflowProfileEditorDialog(
            profile=profile,
            connection_choices=[
                ConnectionChoice(
                    connection_id=connection.connection_id,
                    label=connection.display_name,
                    default_model=connection.default_model,
                )
                for connection in self._state.connections
            ],
            allow_name_edit=True,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._service.save_workflow_profile(
                SaveWorkflowProfileRequest(
                    profile=dialog.profile(),
                    set_as_default=(profile.profile_id == self._state.default_profile_id),
                )
            )
            self.refresh()

    def _show_test_result(self, result: ConnectionTestResult) -> None:
        lines = [result.connection_label]
        for capability in result.capabilities:
            lines.append(
                f"- {_CAPABILITY_LABELS[capability.capability]}: {_AVAILABILITY_LABELS[capability.availability]}"
            )
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

    def _set_table_item(
        self, table: QTableWidget, row: int, column: int, text: str, user_data: str | None = None
    ) -> None:
        item = QTableWidgetItem(text)
        if user_data is not None:
            item.setData(Qt.ItemDataRole.UserRole, user_data)
        table.setItem(row, column, item)

    def _summary_text(self, state: AppSetupState) -> str:
        if state.requires_wizard:
            return self.tr(
                "No connections are configured yet. Run the setup wizard to create reusable connections and a shared workflow profile."
            )
        return (
            f"{len(state.connections)} "
            + self.tr("connections configured.")
            + f" {len(state.shared_profiles)} "
            + self.tr("shared workflow profiles available.")
        )

    def _tip_text(self) -> str:
        return self.tr(
            "App Setup manages reusable connections and shared workflow profiles. The wizard creates a concrete shared workflow profile using the existing step-based config system."
        )
