from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


@dataclass(frozen=True)
class _SpinFieldSpec:
    label: str
    attr_name: str
    minimum: int
    maximum: int
    default: int
    suffix: str = ""


@dataclass(frozen=True)
class _TokenLimitSpec:
    label: str
    checkbox_attr: str
    spin_attr: str
    default: int = 1_000_000


class ConnectionDraftForm(QWidget):
    _SPIN_FIELDS = (
        _SpinFieldSpec("Timeout", "timeout_spin", 1, 600, 60, " s"),
        _SpinFieldSpec("Max retries", "retries_spin", 0, 10, 3),
        _SpinFieldSpec("Concurrency", "concurrency_spin", 1, 50, 5),
    )
    _TOKEN_LIMIT_FIELDS = (
        _TokenLimitSpec("Total token limit", "total_limit_checkbox", "total_limit_spin"),
        _TokenLimitSpec("Input token limit", "input_limit_checkbox", "input_limit_spin"),
        _TokenLimitSpec("Output token limit", "output_limit_checkbox", "output_limit_spin"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        self._on_provider_changed(0)

    def _create_token_limit_row(self, default: int) -> tuple[QWidget, QCheckBox, QSpinBox]:
        layout = QHBoxLayout()
        checkbox = QCheckBox(self.tr("Enable"))
        spinner = QSpinBox()
        spinner.setRange(1, 999_999_999)
        spinner.setValue(default)
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

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        connection_tab = QWidget()
        connection_layout = QVBoxLayout(connection_tab)
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
        connection_layout.addLayout(form)

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
        self._build_spin_fields(advanced_form)
        advanced_form.addRow(self.advanced_note)
        self.advanced_section.set_content(advanced_widget)
        self.advanced_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        connection_layout.addWidget(self.advanced_section)
        self.tabs.addTab(connection_tab, self.tr("Connection"))

        token_tab = QWidget()
        self.token_tab_layout = QVBoxLayout(token_tab)
        token_form = QFormLayout()
        self._build_token_limit_fields(token_form)
        self.token_meter_note = create_tip_label(
            self.tr("Token limits and usage tracking apply to this connection profile only.")
        )
        self.token_tab_layout.addLayout(token_form)
        self.token_tab_layout.addWidget(self.token_meter_note)
        self.tabs.addTab(token_tab, self.tr("Token Meter"))

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

    def add_token_meter_widget(self, widget: QWidget) -> None:
        insert_at = max(self.token_tab_layout.count() - 1, 0)
        self.token_tab_layout.insertWidget(insert_at, widget)

    def _build_spin_fields(self, form: QFormLayout) -> None:
        for spec in self._SPIN_FIELDS:
            spin = QSpinBox()
            spin.setRange(spec.minimum, spec.maximum)
            spin.setValue(spec.default)
            if spec.suffix:
                spin.setSuffix(self.tr(spec.suffix))
            setattr(self, spec.attr_name, spin)
            form.addRow(self.tr(spec.label), spin)

    def _build_token_limit_fields(self, form: QFormLayout) -> None:
        for spec in self._TOKEN_LIMIT_FIELDS:
            widget, checkbox, spin = self._create_token_limit_row(spec.default)
            setattr(self, spec.checkbox_attr, checkbox)
            setattr(self, spec.spin_attr, spin)
            form.addRow(self.tr(spec.label), widget)

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
            output_token_limit=(
                int(self.output_limit_spin.value()) if self.output_limit_checkbox.isChecked() else None
            ),
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
        connection_summary: ConnectionSummary | None = None,
        test_callback: Callable[[ConnectionDraft], ConnectionTestResult] | None = None,
        reset_tokens_callback: Callable[[str], ConnectionSummary] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._connection_summary = connection_summary
        self._test_callback = test_callback
        self._reset_tokens_callback = reset_tokens_callback
        self.setWindowTitle(self.tr("Connection"))
        self.setMinimumWidth(460)
        self.resize(520, 300)
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
        if self._connection_summary is not None:
            self.token_usage_group = QGroupBox(self.tr("Token usage"))
            usage_layout = QFormLayout(self.token_usage_group)
            self.total_used_label = QLabel()
            self.input_used_label = QLabel()
            self.cached_input_label = QLabel()
            self.uncached_input_label = QLabel()
            self.output_used_label = QLabel()
            usage_layout.addRow(self.tr("Total"), self.total_used_label)
            usage_layout.addRow(self.tr("Input"), self.input_used_label)
            usage_layout.addRow(self.tr("  Cached input"), self.cached_input_label)
            usage_layout.addRow(self.tr("  Uncached input"), self.uncached_input_label)
            usage_layout.addRow(self.tr("Output"), self.output_used_label)
            self.reset_tokens_button = QPushButton(self.tr("Reset Usage"))
            self.reset_tokens_button.clicked.connect(self._on_reset_tokens)
            usage_layout.addRow(self.reset_tokens_button)
            self.form.add_token_meter_widget(self.token_usage_group)
            self._set_token_usage(self._connection_summary)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.test_button = self.button_box.addButton(self.tr("Test"), QDialogButtonBox.ButtonRole.ActionRole)
        self.button_box.accepted.connect(self._accept_if_valid)
        self.button_box.rejected.connect(self.reject)
        self.test_button.clicked.connect(self._on_test)
        layout.addWidget(self.button_box)
        self.form.advanced_section.toggled.connect(self._schedule_resize)
        self.form.tabs.currentChanged.connect(lambda _index: self._schedule_resize())
        self._schedule_resize()

    def request(self) -> SaveConnectionRequest:
        return SaveConnectionRequest(connection=self.form.to_draft(), connection_id=self._connection_id)

    def _accept_if_valid(self) -> None:
        valid, message = self.form.validate(require_api_key=self._connection_id is None)
        if not valid:
            QMessageBox.warning(self, self.tr("Missing Information"), message or self.tr("Please complete the form."))
            return
        self.accept()

    def _on_test(self) -> None:
        if self._test_callback is None:
            return
        valid, message = self.form.validate(require_api_key=self._connection_id is None)
        if not valid:
            QMessageBox.warning(self, self.tr("Missing Information"), message or self.tr("Please complete the form."))
            return
        self._test_callback(self.form.to_draft(allow_empty_api_key=self._connection_id is not None))

    def _on_reset_tokens(self) -> None:
        if self._connection_id is None or self._reset_tokens_callback is None:
            return
        updated = self._reset_tokens_callback(self._connection_id)
        self._connection_summary = updated
        self._set_token_usage(updated)

    def _set_token_usage(self, summary: ConnectionSummary) -> None:
        self.total_used_label.setText(f"{summary.tokens_used:,}")
        self.input_used_label.setText(f"{summary.input_tokens_used:,}")
        self.cached_input_label.setText(f"{summary.cached_input_tokens_used:,}")
        self.uncached_input_label.setText(f"{summary.uncached_input_tokens_used:,}")
        self.output_used_label.setText(f"{summary.output_tokens_used:,}")

    def _schedule_resize(self, *_args: object) -> None:
        QTimer.singleShot(0, self._resize_to_content)
        QTimer.singleShot(220, self._resize_to_content)

    def _resize_to_content(self) -> None:
        target_height = min(max(self.sizeHint().height() + 24, 300), 620)
        self.resize(self.width(), target_height)


class SetupWizardDialog(QDialog):
    def __init__(
        self, service: AppSetupService, initial_state: SetupWizardState, parent: QWidget | None = None
    ) -> None:
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
                "Choose providers and paste API keys. The wizard will test capabilities and create a concrete shared workflow profile. Use Connections for custom providers and advanced connection settings."
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
        self._provider_api_key_edits: dict[ProviderKind, QLineEdit] = {}
        self._profile_name_edit: QLineEdit | None = None

    def _build_page(self) -> None:
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if self._page_index == 0:
            self.step_title.setText(self.tr("Choose providers"))
            self._provider_checks = {}
            self._provider_api_key_edits = {}
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setSpacing(12)
            for provider in self._available_providers:
                group = QGroupBox(provider.label)
                group_layout = QFormLayout(group)
                checkbox = QCheckBox(self.tr("Use this provider"))
                checkbox.setToolTip(provider.helper_text or "")
                checkbox.setProperty("provider", provider.provider.value)
                checkbox.setChecked(provider.provider in self._wizard_state.selected_providers)
                api_key_edit = QLineEdit()
                api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
                api_key_edit.setPlaceholderText(self.tr("Paste API key"))
                api_key_edit.setText(self._draft_for_provider(provider.provider).api_key or "")
                api_key_edit.setEnabled(checkbox.isChecked())
                checkbox.toggled.connect(api_key_edit.setEnabled)
                group_layout.addRow(checkbox)
                if provider.helper_text:
                    group_layout.addRow(create_tip_label(provider.helper_text))
                group_layout.addRow(self.tr("API key"), api_key_edit)
                self._provider_checks[provider.provider] = checkbox
                self._provider_api_key_edits[provider.provider] = api_key_edit
                host_layout.addWidget(group)
            host_layout.addStretch()
            self.page_layout.addWidget(host)
        else:
            self._ensure_preview_state()
            self.step_title.setText(self.tr("Review workflow profile"))
            preview = self._preview_state
            if preview is None:
                return
            profile_name_group = QGroupBox(self.tr("Workflow profile"))
            profile_name_layout = QFormLayout(profile_name_group)
            self._profile_name_edit = QLineEdit(preview.profile_name or "Recommended")
            profile_name_layout.addRow(self.tr("Profile name"), self._profile_name_edit)
            self.page_layout.addWidget(profile_name_group)
            for result in preview.test_results:
                result_group = QGroupBox(result.connection_label)
                result_layout = QVBoxLayout(result_group)
                if result.message is not None:
                    result_layout.addWidget(create_tip_label(result.message.text))
                supported = ", ".join(_CAPABILITY_LABELS[capability] for capability in result.supported_capabilities)
                result_layout.addWidget(QLabel(supported or self.tr("No supported workflow capabilities detected.")))
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
        if not self._provider_api_key_edits:
            return
        drafts = [
            self._draft_for_provider(provider).model_copy(update={"api_key": api_key_edit.text().strip() or None})
            for provider, api_key_edit in self._provider_api_key_edits.items()
            if provider in self.selected_providers()
        ]
        self._wizard_state = self._wizard_state.model_copy(update={"drafts": drafts})

    def final_request(self) -> SetupWizardRequest | None:
        if self._preview_state is None:
            return None
        return SetupWizardRequest(
            providers=list(self._wizard_state.selected_providers),
            connections=list(self._wizard_state.drafts),
            profile_name=(self._profile_name_edit.text().strip() if self._profile_name_edit is not None else None),
        )

    def _populate_provider_cards(self, providers: Sequence[ProviderCard]) -> None:
        self._available_providers = [
            provider for provider in providers if provider.provider is not ProviderKind.OPENAI_COMPATIBLE
        ]

    def _go_back(self) -> None:
        if self._page_index == 0:
            return
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
            self._persist_drafts()
            for draft in self._wizard_state.drafts:
                if not draft.api_key:
                    QMessageBox.warning(
                        self,
                        self.tr("Missing Information"),
                        self.tr("API key is required for every selected provider."),
                    )
                    return
            self._preview_state = None
        self._page_index = min(self._page_index + 1, 1)
        self._build_page()

    def _finish(self) -> None:
        request = self.final_request()
        if request is None:
            QMessageBox.warning(
                self,
                self.tr("Wizard Incomplete"),
                self.tr("Review the recommended workflow profile before saving setup."),
            )
            return
        if not (request.profile_name or "").strip():
            QMessageBox.warning(
                self,
                self.tr("Missing Information"),
                self.tr("Workflow profile name is required."),
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
        self.next_button.setVisible(self._page_index < 1)
        self.finish_button.setVisible(self._page_index == 1)


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
        self.duplicate_connection_button = QPushButton(self.tr("Duplicate"))
        self.duplicate_connection_button.clicked.connect(self._on_duplicate_connection)
        self.delete_connection_button = QPushButton(self.tr("Delete"))
        self.delete_connection_button.clicked.connect(self._on_delete_connection)
        connections_toolbar.addWidget(self.run_wizard_button)
        connections_toolbar.addWidget(self.add_connection_button)
        connections_toolbar.addWidget(self.duplicate_connection_button)
        connections_toolbar.addWidget(self.delete_connection_button)
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
        self.connections_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.connections_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.connections_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.connections_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.connections_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.connections_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.connections_table.setColumnWidth(3, 320)
        self.connections_table.setColumnWidth(4, 500)
        self.connections_table.itemSelectionChanged.connect(self._update_connection_buttons)
        self.connections_table.cellDoubleClicked.connect(self._on_connection_double_clicked)
        connections_layout.addWidget(self.connections_table)
        connections_tab_layout.addWidget(self.connections_group, 1)

        self.profiles_group = QGroupBox(self.tr("Shared workflow profiles"))
        profiles_layout = QVBoxLayout(self.profiles_group)
        profiles_toolbar = QHBoxLayout()
        self.duplicate_profile_button = QPushButton(self.tr("Duplicate"))
        self.duplicate_profile_button.clicked.connect(self._on_duplicate_profile)
        profiles_toolbar.addWidget(self.duplicate_profile_button)
        self.delete_profile_button = QPushButton(self.tr("Delete"))
        self.delete_profile_button.clicked.connect(self._on_delete_profile)
        profiles_toolbar.addWidget(self.delete_profile_button)
        profiles_toolbar.addStretch()
        profiles_layout.addLayout(profiles_toolbar)
        self.profiles_table = QTableWidget(0, 3)
        self.profiles_table.setHorizontalHeaderLabels([self.tr("Name"), self.tr("Target language"), self.tr("Default")])
        self.profiles_table.verticalHeader().setVisible(False)
        self.profiles_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.profiles_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.profiles_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.profiles_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.profiles_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.profiles_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.profiles_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.profiles_table.setColumnWidth(0, 360)
        self.profiles_table.setColumnWidth(1, 220)
        self.profiles_table.itemSelectionChanged.connect(self._update_profile_buttons)
        self.profiles_table.cellDoubleClicked.connect(self._on_profile_double_clicked)
        profiles_layout.addWidget(self.profiles_table)

        self.profiles_tab = QWidget()
        profiles_tab_layout = QVBoxLayout(self.profiles_tab)
        profiles_tab_layout.addWidget(self.profiles_group, 1)

        self.setup_tabs.addTab(self.connections_tab, self.tr("Connections"))
        self.setup_tabs.addTab(self.profiles_tab, self.tr("Workflow Profiles"))
        self._update_connection_buttons()

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
        self.duplicate_connection_button.setText(self.tr("Duplicate"))
        self.setup_tabs.setTabText(self.setup_tabs.indexOf(self.connections_tab), self.tr("Connections"))
        self.setup_tabs.setTabText(self.setup_tabs.indexOf(self.profiles_tab), self.tr("Workflow Profiles"))
        self.connections_group.setTitle(self.tr("Connections"))
        self.connections_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Provider"), self.tr("Status"), self.tr("Model"), self.tr("Base URL")]
        )
        self.delete_connection_button.setText(self.tr("Delete"))
        self.profiles_group.setTitle(self.tr("Shared workflow profiles"))
        self.duplicate_profile_button.setText(self.tr("Duplicate"))
        self.delete_profile_button.setText(self.tr("Delete"))
        self.profiles_table.setHorizontalHeaderLabels([self.tr("Name"), self.tr("Target language"), self.tr("Default")])
        if self._state is not None:
            self.summary_label.setText(self._summary_text(self._state))
            self._populate_profiles(self._state)
            self._update_profile_buttons()

    def _populate_connections(self, connections: Sequence[ConnectionSummary]) -> None:
        self.connections_table.setRowCount(0)
        for connection in connections:
            row = self.connections_table.rowCount()
            self.connections_table.insertRow(row)
            name_item = self._set_table_item(
                self.connections_table, row, 0, connection.display_name, connection.connection_id
            )
            if connection.is_managed:
                name_item.setToolTip(self.tr("Managed by the setup wizard. Duplicate it if you need an editable copy."))
            self._set_table_item(
                self.connections_table, row, 1, _PROVIDER_LABELS.get(connection.provider, connection.provider.value)
            )
            self._set_table_item(self.connections_table, row, 2, connection.status.value.replace("_", " ").title())
            self._set_table_item(self.connections_table, row, 3, connection.default_model or "")
            self._set_table_item(self.connections_table, row, 4, connection.base_url or "")
        self.connections_table.resizeRowsToContents()

    def _populate_profiles(self, state: AppSetupState) -> None:
        self.profiles_table.setRowCount(0)
        for profile in state.shared_profiles:
            row = self.profiles_table.rowCount()
            self.profiles_table.insertRow(row)
            self._set_table_item(self.profiles_table, row, 0, profile.name, profile.profile_id)
            self._set_table_item(self.profiles_table, row, 1, profile.target_language)
            self._set_table_item(self.profiles_table, row, 2, self.tr("Yes") if profile.is_default else "")
        self.profiles_table.resizeRowsToContents()

        selected_id = self._preferred_profile_id(state)
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
        if self._state is None:
            return None
        if not rows:
            preferred_profile_id = self._preferred_profile_id(self._state)
            return next(
                (profile for profile in self._state.shared_profiles if profile.profile_id == preferred_profile_id),
                (self._state.shared_profiles[0] if self._state.shared_profiles else None),
            )
        row = rows[0].row()
        if row < 0 or row >= len(self._state.shared_profiles):
            return None
        return self._state.shared_profiles[row]

    def _preferred_profile_id(self, state: AppSetupState) -> str | None:
        if state.default_profile_id:
            return state.default_profile_id
        if state.shared_profiles:
            return state.shared_profiles[0].profile_id
        return None

    def _update_connection_buttons(self) -> None:
        selected_connection = self._selected_connection()
        selected = selected_connection is not None
        managed = bool(selected_connection and selected_connection.is_managed)
        self.duplicate_connection_button.setEnabled(selected)
        self.delete_connection_button.setEnabled(selected and not managed)

    def _update_profile_buttons(self) -> None:
        selected = self._selected_profile() is not None
        self.duplicate_profile_button.setEnabled(selected)
        self.delete_profile_button.setEnabled(selected)

    def _on_run_wizard(self) -> None:
        dialog = SetupWizardDialog(self._service, self._service.get_wizard_state(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _on_add_connection(self) -> None:
        dialog = ConnectionEditorDialog(test_callback=self._test_connection_draft, parent=self)
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
            connection_summary=connection,
            test_callback=self._test_connection_draft,
            reset_tokens_callback=self._reset_connection_tokens,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._service.save_connection(dialog.request())
            self.refresh()

    def _on_delete_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        result = QMessageBox.question(
            self,
            self.tr("Delete Connection"),
            self.tr(
                "Delete the selected connection? Existing profiles or projects may stop working until setup is fixed."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._service.delete_connection(connection.connection_id)
        self.refresh()

    def _on_duplicate_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        self._service.duplicate_connection(connection.connection_id)
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
                    provider=connection.provider.value,
                    base_url=connection.base_url,
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

    def _on_delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        result = QMessageBox.question(
            self,
            self.tr("Delete Workflow Profile"),
            self.tr("Delete the selected workflow profile? Projects using it will need setup first."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_workflow_profile(profile.profile_id)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("App Setup"), str(exc))
            return
        self.refresh()

    def _on_duplicate_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self._service.duplicate_workflow_profile(profile.profile_id)
        self.refresh()

    def _on_profile_double_clicked(self, _row: int, _column: int) -> None:
        self._on_edit_profile()

    def _on_connection_double_clicked(self, _row: int, _column: int) -> None:
        connection = self._selected_connection()
        if connection is None or connection.is_managed:
            return
        self._on_edit_connection()

    def _test_connection_draft(self, draft: ConnectionDraft) -> ConnectionTestResult:
        result = self._service.test_connection(ConnectionTestRequest(connection=draft))
        self._show_test_result(result)
        return result

    def _reset_connection_tokens(self, connection_id: str) -> ConnectionSummary:
        updated = self._service.reset_connection_tokens(connection_id)
        self.refresh()
        return updated

    def _show_test_result(self, result: ConnectionTestResult) -> None:
        lines = [result.connection_label]
        for capability in result.supported_capabilities:
            lines.append(f"- {_CAPABILITY_LABELS[capability]}")
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
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if user_data is not None:
            item.setData(Qt.ItemDataRole.UserRole, user_data)
        table.setItem(row, column, item)
        return item

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
