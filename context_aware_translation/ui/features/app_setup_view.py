from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
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
from superqt import QCollapsible, QSearchableComboBox

from context_aware_translation.application.contracts.app_setup import (
    ConnectionDraft,
    ConnectionSummary,
    ConnectionTestResult,
    ProviderCard,
    SaveConnectionRequest,
    SetupWizardMode,
    SetupWizardRequest,
    SetupWizardState,
    WorkflowStepId,
    default_connection_concurrency,
)
from context_aware_translation.application.contracts.common import CapabilityCode, ProviderKind, UserMessageSeverity
from context_aware_translation.application.services.app_setup import AppSetupService
from context_aware_translation.ui.constants import LANGUAGES, display_target_language_name
from context_aware_translation.ui.features.workflow_profile_editor import workflow_step_label_from_text
from context_aware_translation.ui.json_utils import parse_json_object_text
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone
from context_aware_translation.ui.widgets.table_support import (
    configure_readonly_row_table,
    fit_table_height_to_rows,
)

_PROVIDER_DEFAULTS: dict[ProviderKind, tuple[str, str]] = {
    ProviderKind.GEMINI: ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.1-pro"),
    ProviderKind.OPENAI: ("https://api.openai.com/v1", "gpt-5.4"),
    ProviderKind.DEEPSEEK: ("https://api.deepseek.com", "deepseek-chat"),
    ProviderKind.ANTHROPIC: ("https://api.anthropic.com/v1", "claude-opus-4-6"),
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

_DEFAULT_SETUP_WIZARD_TARGET_LANGUAGE = LANGUAGES[0][0] if LANGUAGES else "English"


_NEW_PROFILE_ROUTE_SPECS: tuple[tuple[WorkflowStepId, str], ...] = (
    (WorkflowStepId.EXTRACTOR, "Extractor"),
    (WorkflowStepId.SUMMARIZER, "Summarizer"),
    (WorkflowStepId.GLOSSARY_TRANSLATOR, "Glossary translator"),
    (WorkflowStepId.TRANSLATOR, "Translator"),
    (WorkflowStepId.POLISH, "Polish"),
    (WorkflowStepId.REVIEWER, "Reviewer"),
    (WorkflowStepId.OCR, "OCR"),
    (WorkflowStepId.IMAGE_REEMBEDDING, "Image reembedding"),
    (WorkflowStepId.MANGA_TRANSLATOR, "Manga translator"),
    (WorkflowStepId.TRANSLATOR_BATCH, "Translator batch"),
)


def _provider_label(provider: ProviderKind) -> str:
    return _PROVIDER_LABELS.get(provider, provider.value)


def _translate_workflow_route_label(text: str) -> str:
    return QCoreApplication.translate("WorkflowRoutesEditor", text)


def _provider_defaults(provider: ProviderKind) -> tuple[str, str | None, str | None]:
    base_url, default_model = _PROVIDER_DEFAULTS[provider]
    return _provider_label(provider), (base_url or None), (default_model or None)


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


_CONNECTION_SPIN_FIELDS = (
    _SpinFieldSpec(QT_TRANSLATE_NOOP("ConnectionDraftForm", "Timeout"), "timeout_spin", 1, 600, 60, " s"),
    _SpinFieldSpec(QT_TRANSLATE_NOOP("ConnectionDraftForm", "Max retries"), "retries_spin", 0, 10, 3),
    _SpinFieldSpec(QT_TRANSLATE_NOOP("ConnectionDraftForm", "Concurrency"), "concurrency_spin", 1, 50, 5),
)

_CONNECTION_TOKEN_LIMIT_FIELDS = (
    _TokenLimitSpec(
        QT_TRANSLATE_NOOP("ConnectionDraftForm", "Total token limit"),
        "total_limit_checkbox",
        "total_limit_spin",
    ),
    _TokenLimitSpec(
        QT_TRANSLATE_NOOP("ConnectionDraftForm", "Input token limit"),
        "input_limit_checkbox",
        "input_limit_spin",
    ),
    _TokenLimitSpec(
        QT_TRANSLATE_NOOP("ConnectionDraftForm", "Output token limit"),
        "output_limit_checkbox",
        "output_limit_spin",
    ),
)


class ConnectionDraftForm(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._auto_concurrency_default: int | None = None
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
        self.tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.tabs)

        connection_tab = QWidget()
        connection_layout = QVBoxLayout(connection_tab)
        form = QFormLayout()
        self.display_name_edit = QLineEdit()
        self.provider_combo = QComboBox()
        for provider in ProviderKind:
            self.provider_combo.addItem(self.tr(_provider_label(provider)), provider.value)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(self.tr("Paste API key"))

        form.addRow(self.tr("Connection name"), self.display_name_edit)
        form.addRow(self.tr("Provider"), self.provider_combo)
        form.addRow(self.tr("API key"), self.api_key_edit)
        connection_layout.addLayout(form)

        self.advanced_section = QCollapsible(self.tr("Advanced"))
        advanced_widget = QWidget()
        advanced_form = QFormLayout(advanced_widget)
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(60)
        self.description_edit.setMinimumWidth(440)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(self.tr("Base URL"))
        self.base_url_edit.setMinimumWidth(440)
        self.default_model_edit = QLineEdit()
        self.default_model_edit.setPlaceholderText(self.tr("Default model"))
        self.default_model_edit.setMinimumWidth(440)
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.0)
        self.custom_parameters_edit = QTextEdit()
        self.custom_parameters_edit.setMaximumHeight(90)
        self.custom_parameters_edit.setMinimumWidth(440)
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
        self.advanced_section.setContent(advanced_widget)
        self.advanced_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        connection_layout.addWidget(self.advanced_section)
        connection_layout.addStretch()
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
        self.token_tab_layout.addStretch()
        self.tabs.addTab(token_tab, self.tr("Token Meter"))

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

    def add_token_meter_widget(self, widget: QWidget) -> None:
        insert_at = max(self.token_tab_layout.count() - 1, 0)
        self.token_tab_layout.insertWidget(insert_at, widget)

    def _build_spin_fields(self, form: QFormLayout) -> None:
        for spec in _CONNECTION_SPIN_FIELDS:
            spin = QSpinBox()
            spin.setRange(spec.minimum, spec.maximum)
            spin.setValue(spec.default)
            if spec.suffix:
                spin.setSuffix(self.tr(spec.suffix))
            setattr(self, spec.attr_name, spin)
            form.addRow(self.tr(spec.label), spin)

    def _build_token_limit_fields(self, form: QFormLayout) -> None:
        for spec in _CONNECTION_TOKEN_LIMIT_FIELDS:
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
            self.api_key_edit.setPlaceholderText(
                self.tr("Stored API key is hidden. Leave blank to keep it or paste a new key.")
            )
        self.description_edit.setPlainText(draft.description or "")
        self.base_url_edit.setText(draft.base_url or "")
        self.default_model_edit.setText(draft.default_model or "")
        self.temperature_spin.setValue(draft.temperature)
        self.custom_parameters_edit.setPlainText(draft.custom_parameters_json or "")
        self.timeout_spin.setValue(draft.timeout)
        self.retries_spin.setValue(draft.max_retries)
        self.concurrency_spin.setValue(draft.concurrency)
        self._auto_concurrency_default = default_connection_concurrency(draft.provider)
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
                parse_json_object_text(draft.custom_parameters_json, tr=self.tr)
            except ValueError as exc:
                return False, str(exc)
        if draft.provider is ProviderKind.OPENAI_COMPATIBLE and (not draft.base_url or not draft.default_model):
            return False, self.tr("Custom connections require base URL and default model.")
        return True, None

    def _on_provider_changed(self, _index: int) -> None:
        provider = self.current_provider()
        display_name, base_url, default_model = _provider_defaults(provider)
        provider_concurrency = default_connection_concurrency(provider)
        self.base_url_edit.setText(base_url or "")
        self.default_model_edit.setText(default_model or "")
        if self._auto_concurrency_default is None or self.concurrency_spin.value() == self._auto_concurrency_default:
            self.concurrency_spin.setValue(provider_concurrency)
        self._auto_concurrency_default = provider_concurrency
        if (
            not self.display_name_edit.text().strip()
            or self.display_name_edit.text().strip() in _PROVIDER_LABELS.values()
        ):
            self.display_name_edit.setText(display_name)
        self._sync_advanced_visibility(provider)

    def _sync_advanced_visibility(self, provider: ProviderKind) -> None:
        if provider is ProviderKind.OPENAI_COMPATIBLE:
            self.advanced_section.expand(False)
        else:
            self.advanced_section.collapse(False)


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
        if parent is not None:
            self.setWindowModality(Qt.WindowModality.WindowModal)
        self._connection_id = connection_id
        self._connection_summary = connection_summary
        self._test_callback = test_callback
        self._reset_tokens_callback = reset_tokens_callback
        self.setWindowTitle(self.tr("Connection"))
        self.setMinimumSize(820, 480)
        self.resize(900, 560)
        self.form = ConnectionDraftForm(self)
        self.form.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if draft is not None:
            self.form.set_draft(draft)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.form)
        layout.addWidget(self.scroll_area, 1)
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
        apply_hybrid_control_theme(self)
        set_button_tone(self.button_box.button(QDialogButtonBox.StandardButton.Save), "primary")
        set_button_tone(self.button_box.button(QDialogButtonBox.StandardButton.Cancel), "ghost")
        set_button_tone(self.test_button)
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
        result = self._test_callback(self.form.to_draft(allow_empty_api_key=self._connection_id is not None))
        self._show_test_result(result)

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
        current_tab = self.form.tabs.currentIndex()
        is_advanced = current_tab == 0 and self.form.advanced_section.isExpanded()
        target_width = 960 if is_advanced else 860
        current_widget = self.form.tabs.currentWidget()
        if current_widget is not None:
            current_widget.adjustSize()
            tab_bar_height = self.form.tabs.tabBar().sizeHint().height()
            tab_height = current_widget.sizeHint().height() + tab_bar_height + 12
            self.form.tabs.setFixedHeight(tab_height)
        self.layout().activate()
        self.form.adjustSize()
        if current_tab == 0 and not is_advanced:
            target_height = 520
        elif current_tab == 1:
            target_height = 560 if self._connection_summary is not None else 500
        else:
            target_height = min(max(self.sizeHint().height(), 620), 760)
        self.resize(max(self.width(), self.minimumWidth(), target_width), max(self.minimumHeight(), target_height))

    def _show_test_result(self, result: ConnectionTestResult) -> None:
        lines = [result.connection_label]
        for capability in result.supported_capabilities:
            label = _CAPABILITY_LABELS.get(
                capability, capability.value if isinstance(capability, CapabilityCode) else str(capability)
            )
            lines.append(f"- {label}")
        if result.message is not None:
            severity = result.message.severity
            text = "\n".join(lines + ["", result.message.text])
        else:
            severity = UserMessageSeverity.INFO
            text = "\n".join(lines)
        box = QMessageBox(self)
        box.setWindowTitle(self.tr("Connection Test"))
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setWindowModality(Qt.WindowModality.WindowModal)
        if severity is UserMessageSeverity.ERROR:
            box.setIcon(QMessageBox.Icon.Critical)
        elif severity is UserMessageSeverity.WARNING:
            box.setIcon(QMessageBox.Icon.Warning)
        else:
            box.setIcon(QMessageBox.Icon.Information)
        box.exec()
        self.raise_()
        self.activateWindow()
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setFocus(Qt.FocusReason.OtherFocusReason)


class SetupWizardDialog(QDialog):
    def __init__(
        self, service: AppSetupService, initial_state: SetupWizardState, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setWindowModality(Qt.WindowModality.WindowModal)
        self._service = service
        self._wizard_state = initial_state
        if not self._service.get_state().shared_profiles and self._wizard_state.target_language == "English":
            self._wizard_state = self._wizard_state.model_copy(
                update={"target_language": _DEFAULT_SETUP_WIZARD_TARGET_LANGUAGE}
            )
        self._preview_state: SetupWizardState | None = None
        self.setWindowTitle(self.tr("Setup Wizard"))
        self.resize(780, 680)
        self._init_ui()
        self._available_providers = [
            provider
            for provider in initial_state.available_providers
            if provider.provider is not ProviderKind.OPENAI_COMPATIBLE
        ]
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
        apply_hybrid_control_theme(self)
        set_button_tone(self.back_button, "ghost")
        set_button_tone(self.next_button)
        set_button_tone(self.finish_button, "primary")
        set_button_tone(self.cancel_button, "ghost")

        self._page_index = 0
        self._available_providers: list[ProviderCard] = []
        self._provider_inputs: dict[ProviderKind, tuple[QCheckBox, QLineEdit]] = {}
        self._profile_name_edit: QLineEdit | None = None
        self._target_language_combo: QSearchableComboBox | None = None
        self._mode_button_group: QButtonGroup | None = None
        self._quality_mode_radio: QRadioButton | None = None
        self._balanced_mode_radio: QRadioButton | None = None
        self._budget_mode_radio: QRadioButton | None = None
        self._review_rebuild_pending = False

    def _translate_provider_helper_text(self, text: str | None) -> str:
        if not text:
            return ""
        translations = {
            "Good for image text reading and image editing.": self.tr("Good for image text reading and image editing."),
            "General-purpose text and image-capable provider.": self.tr(
                "General-purpose text and image-capable provider."
            ),
            "Low-cost text translation and context building.": self.tr(
                "Low-cost text translation and context building."
            ),
            "Text translation and image understanding.": self.tr("Text translation and image understanding."),
        }
        return translations.get(text, text)

    def _build_page(self) -> None:
        self._clear_page_layout()
        self._profile_name_edit = None
        self._target_language_combo = None
        self._mode_button_group = None
        self._quality_mode_radio = None
        self._balanced_mode_radio = None
        self._budget_mode_radio = None

        if self._page_index == 0:
            self.step_title.setText(self.tr("Choose providers"))
            self._provider_inputs = {}
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setSpacing(12)
            for provider in self._available_providers:
                translated_helper_text = self._translate_provider_helper_text(provider.helper_text)
                group = QGroupBox(provider.label)
                group_layout = QFormLayout(group)
                checkbox = QCheckBox(self.tr("Use this provider"))
                checkbox.setToolTip(translated_helper_text)
                checkbox.setProperty("provider", provider.provider.value)
                checkbox.setChecked(provider.provider in self._wizard_state.selected_providers)
                api_key_edit = QLineEdit()
                api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
                api_key_edit.setPlaceholderText(self.tr("Paste API key"))
                api_key_edit.setText(self._draft_for_provider(provider.provider).api_key or "")
                api_key_edit.setEnabled(checkbox.isChecked())
                checkbox.toggled.connect(api_key_edit.setEnabled)
                group_layout.addRow(checkbox)
                if translated_helper_text:
                    group_layout.addRow(create_tip_label(translated_helper_text))
                group_layout.addRow(self.tr("API key"), api_key_edit)
                self._provider_inputs[provider.provider] = (checkbox, api_key_edit)
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
            suggested_name = preview.profile_name or (
                preview.recommendation.name if preview.recommendation is not None else "Recommended"
            )
            self._profile_name_edit = QLineEdit(suggested_name)
            self._target_language_combo = QSearchableComboBox()
            self._target_language_combo.setEditable(True)
            seen_languages: set[str] = set()
            for display_name, _internal_name in LANGUAGES:
                if display_name in seen_languages:
                    continue
                seen_languages.add(display_name)
                self._target_language_combo.addItem(display_name)
            target_language = display_target_language_name(preview.target_language) or display_target_language_name(
                preview.recommendation.target_language if preview.recommendation is not None else None
            ) or _DEFAULT_SETUP_WIZARD_TARGET_LANGUAGE
            index = self._target_language_combo.findText(target_language)
            if index >= 0:
                self._target_language_combo.setCurrentIndex(index)
            else:
                self._target_language_combo.setEditText(target_language)
            mode_row = QWidget()
            mode_row_layout = QHBoxLayout(mode_row)
            mode_row_layout.setContentsMargins(0, 0, 0, 0)
            mode_row_layout.setSpacing(12)
            self._mode_button_group = QButtonGroup(mode_row)
            self._quality_mode_radio = QRadioButton(self.tr("Quality"))
            self._balanced_mode_radio = QRadioButton(self.tr("Balanced"))
            self._budget_mode_radio = QRadioButton(self.tr("Budget"))
            self._mode_button_group.addButton(self._quality_mode_radio)
            self._mode_button_group.addButton(self._balanced_mode_radio)
            self._mode_button_group.addButton(self._budget_mode_radio)
            self._quality_mode_radio.toggled.connect(
                lambda checked: checked and self._on_recommendation_mode_changed(SetupWizardMode.QUALITY)
            )
            self._balanced_mode_radio.toggled.connect(
                lambda checked: checked and self._on_recommendation_mode_changed(SetupWizardMode.BALANCED)
            )
            self._budget_mode_radio.toggled.connect(
                lambda checked: checked and self._on_recommendation_mode_changed(SetupWizardMode.BUDGET)
            )
            mode_row_layout.addWidget(self._quality_mode_radio)
            mode_row_layout.addWidget(self._balanced_mode_radio)
            mode_row_layout.addWidget(self._budget_mode_radio)
            mode_row_layout.addStretch(1)
            if self._wizard_state.recommendation_mode is SetupWizardMode.BUDGET:
                self._budget_mode_radio.setChecked(True)
            elif self._wizard_state.recommendation_mode is SetupWizardMode.BALANCED:
                self._balanced_mode_radio.setChecked(True)
            else:
                self._quality_mode_radio.setChecked(True)
            profile_name_layout.addRow(self.tr("Profile name"), self._profile_name_edit)
            profile_name_layout.addRow(self.tr("Target language"), self._target_language_combo)
            profile_name_layout.addRow(self.tr("Workflow mode"), mode_row)
            self.page_layout.addWidget(profile_name_group)
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
                configure_readonly_row_table(table)
                for route in recommendation.routes:
                    row = table.rowCount()
                    table.insertRow(row)
                    table.setItem(
                        row,
                        0,
                        QTableWidgetItem(
                            workflow_step_label_from_text(route.step_label, tr=_translate_workflow_route_label)
                        ),
                    )
                    table.setItem(row, 1, QTableWidgetItem(route.connection_label or ""))
                    table.setItem(row, 2, QTableWidgetItem(route.model or ""))
                table.resizeColumnsToContents()
                table.resizeRowsToContents()
                fit_table_height_to_rows(table, padding=4)
                profile_layout.addWidget(table)
            self.page_layout.addWidget(profile_group)
            self.page_layout.addStretch()
        self._update_buttons()
        QTimer.singleShot(0, self._resize_to_page)
        QTimer.singleShot(120, self._resize_to_page)

    def selected_providers(self) -> list[ProviderKind]:
        checked = [provider for provider, (checkbox, _) in self._provider_inputs.items() if checkbox.isChecked()]
        return checked

    def _draft_for_provider(self, provider: ProviderKind) -> ConnectionDraft:
        for draft in self._wizard_state.drafts:
            if draft.provider is provider:
                return draft
        display_name, base_url, default_model = _provider_defaults(provider)
        return ConnectionDraft(
            display_name=display_name,
            provider=provider,
            base_url=base_url,
            default_model=default_model,
            temperature=0.0,
            timeout=60,
            max_retries=3,
            concurrency=default_connection_concurrency(provider),
        )

    def _persist_drafts(self) -> None:
        if not self._provider_inputs:
            return
        drafts = [
            self._draft_for_provider(provider).model_copy(update={"api_key": api_key_edit.text().strip() or None})
            for provider, (_, api_key_edit) in self._provider_inputs.items()
            if provider in self.selected_providers()
        ]
        self._wizard_state = self._wizard_state.model_copy(update={"drafts": drafts})

    def _persist_review_inputs(self) -> None:
        updates: dict[str, str | None] = {}
        if self._profile_name_edit is not None:
            updates["profile_name"] = self._profile_name_edit.text().strip() or None
        if self._target_language_combo is not None:
            updates["target_language"] = (
                self._target_language_combo.currentText().strip() or _DEFAULT_SETUP_WIZARD_TARGET_LANGUAGE
            )
        if self._budget_mode_radio is not None and self._budget_mode_radio.isChecked():
            updates["recommendation_mode"] = SetupWizardMode.BUDGET
        elif self._balanced_mode_radio is not None and self._balanced_mode_radio.isChecked():
            updates["recommendation_mode"] = SetupWizardMode.BALANCED
        elif self._quality_mode_radio is not None and self._quality_mode_radio.isChecked():
            updates["recommendation_mode"] = SetupWizardMode.QUALITY
        if updates:
            self._wizard_state = self._wizard_state.model_copy(update=updates)

    def final_request(self) -> SetupWizardRequest | None:
        if self._preview_state is None:
            return None
        self._persist_review_inputs()
        return SetupWizardRequest(
            providers=list(self._wizard_state.selected_providers),
            connections=list(self._wizard_state.drafts),
            profile_name=self._wizard_state.profile_name,
            target_language=self._wizard_state.target_language,
            recommendation_mode=self._wizard_state.recommendation_mode,
        )

    def _go_back(self) -> None:
        if self._page_index == 0:
            return
        self._persist_review_inputs()
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
            # The provider-page widgets are about to be destroyed; keep only the
            # persisted wizard state once we transition into review.
            self._provider_inputs = {}
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
        if not (request.target_language or "").strip():
            QMessageBox.warning(
                self,
                self.tr("Missing Information"),
                self.tr("Target language is required."),
            )
            return
        self._service.run_setup_wizard(request)
        self.accept()

    def _on_recommendation_mode_changed(self, mode: SetupWizardMode) -> None:
        if self._wizard_state.recommendation_mode is mode:
            return
        self._persist_review_inputs()
        self._wizard_state = self._wizard_state.model_copy(update={"recommendation_mode": mode})
        self._preview_state = None
        if self._review_rebuild_pending:
            return
        self._review_rebuild_pending = True
        QTimer.singleShot(0, self._rebuild_review_page_after_mode_change)

    def _rebuild_review_page_after_mode_change(self) -> None:
        self._review_rebuild_pending = False
        if self._page_index != 1:
            return
        self._build_page()

    def _ensure_preview_state(self) -> None:
        if self._preview_state is not None:
            return
        self._preview_state = self._service.preview_setup_wizard(
            SetupWizardRequest(
                providers=list(self._wizard_state.selected_providers),
                connections=list(self._wizard_state.drafts),
                profile_name=self._wizard_state.profile_name,
                target_language=self._wizard_state.target_language,
                recommendation_mode=self._wizard_state.recommendation_mode,
            )
        )

    def _update_buttons(self) -> None:
        self.back_button.setVisible(self._page_index > 0)
        self.next_button.setVisible(self._page_index < 1)
        self.finish_button.setVisible(self._page_index == 1)

    def _resize_to_page(self) -> None:
        self.layout().activate()
        self.page_content.adjustSize()
        minimum_height = 360 if self._page_index == 0 else 520
        target_height = min(max(self.sizeHint().height(), minimum_height), 760)
        self.resize(max(self.width(), 780), target_height)

    def _clear_page_layout(self) -> None:
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
