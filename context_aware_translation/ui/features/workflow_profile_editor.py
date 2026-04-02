from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from superqt import QCollapsible, QSearchableComboBox

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.ui.constants import LANGUAGES
from context_aware_translation.ui.json_utils import parse_json_object_text
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone


@dataclass(frozen=True)
class ConnectionChoice:
    connection_id: str
    label: str
    default_model: str | None = None


@dataclass
class RouteRow:
    route: WorkflowStepRoute
    connection_combo: QComboBox | None
    model_edit: QLineEdit
    connection_label_widget: QLabel | None = None
    row_widget: QWidget | None = None
    step_label_widget: QLabel | None = None


_STEP_TOOLTIP_TEXTS = {
    WorkflowStepId.EXTRACTOR: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Find candidate glossary terms from source text."
    ),
    WorkflowStepId.SUMMARIZER: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Summarize nearby context so later steps can work with less text."
    ),
    WorkflowStepId.GLOSSARY_TRANSLATOR: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Translate glossary terms before full document translation."
    ),
    WorkflowStepId.TRANSLATOR: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Translate the main document text into the target language."
    ),
    WorkflowStepId.REVIEWER: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Review glossary candidates and mark likely noise or confirmed terms."
    ),
    WorkflowStepId.OCR: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Extract editable text from scanned or image-based pages."
    ),
    WorkflowStepId.IMAGE_REEMBEDDING: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Put translated text back into document images."
    ),
    WorkflowStepId.MANGA_TRANSLATOR: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Translate manga pages with image-aware text handling."
    ),
    WorkflowStepId.TRANSLATOR_BATCH: QT_TRANSLATE_NOOP(
        "WorkflowRoutesEditor", "Submit document translation through the provider's asynchronous batch API."
    ),
}

_STEP_LABELS = {
    WorkflowStepId.EXTRACTOR: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Extractor"),
    WorkflowStepId.SUMMARIZER: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Summarizer"),
    WorkflowStepId.GLOSSARY_TRANSLATOR: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Glossary translator"),
    WorkflowStepId.TRANSLATOR: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Translator"),
    WorkflowStepId.REVIEWER: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Reviewer"),
    WorkflowStepId.OCR: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "OCR"),
    WorkflowStepId.IMAGE_REEMBEDDING: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Image reembedding"),
    WorkflowStepId.MANGA_TRANSLATOR: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Manga translator"),
    WorkflowStepId.TRANSLATOR_BATCH: QT_TRANSLATE_NOOP("WorkflowRoutesEditor", "Translator batch"),
}

_STEP_TOOLTIP_FALLBACK = QT_TRANSLATE_NOOP(
    "WorkflowRoutesEditor", "Connection and model settings for this workflow step."
)

_ADVANCED_TIP_TEXTS = {
    WorkflowStepId.EXTRACTOR: QT_TRANSLATE_NOOP(
        "StepAdvancedConfigDialog", "Extraction settings control how aggressively terms are discovered."
    ),
    WorkflowStepId.TRANSLATOR: QT_TRANSLATE_NOOP(
        "StepAdvancedConfigDialog", "Translator settings tune chunk sizing and request budget."
    ),
    WorkflowStepId.OCR: QT_TRANSLATE_NOOP(
        "StepAdvancedConfigDialog", "OCR settings control image compression and artifact cleanup."
    ),
    WorkflowStepId.TRANSLATOR_BATCH: QT_TRANSLATE_NOOP(
        "StepAdvancedConfigDialog", "Batch settings configure optional async translation jobs."
    ),
}

_ADVANCED_TIP_FALLBACK = QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Edit advanced settings for this workflow step.")


@dataclass(frozen=True)
class _SpinFieldSpec:
    attr_name: str
    label: object
    key: str
    minimum: int
    maximum: int
    default: int


@dataclass(frozen=True)
class _CheckFieldSpec:
    attr_name: str
    label: object
    key: str
    default: bool


@dataclass(frozen=True)
class _NumericOverrideFieldSpec:
    label: object
    key: str
    checkbox_attr: str
    input_attr: str
    minimum: int | float
    maximum: int | float
    default: int | float
    suffix: str = ""
    is_float: bool = False


def validate_workflow_routes(
    routes: list[WorkflowStepRoute],
    *,
    tr: Callable[[str], str],
) -> str | None:
    for route in routes:
        if route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            provider = str(route.step_config.get("provider") or "").strip()
            if not provider:
                continue
            if not str(route.step_config.get("api_key") or "").strip():
                return tr("Translator batch requires an API key when enabled.")
            if not str(route.model or "").strip():
                return tr("Translator batch requires a model when enabled.")
            continue
        if not str(route.connection_id or "").strip() or not str(route.model or "").strip():
            return tr("Every workflow step must use a connection and model.")
    return None


def workflow_step_tooltip(step_id: WorkflowStepId, *, tr: Callable[[str], str]) -> str:
    return tr(str(_STEP_TOOLTIP_TEXTS.get(step_id, _STEP_TOOLTIP_FALLBACK)))


def workflow_step_label(step_id: WorkflowStepId, *, tr: Callable[[str], str]) -> str:
    return tr(str(_STEP_LABELS.get(step_id, step_id.value.replace("_", " ").title())))


def workflow_step_label_from_text(step_label: str, *, tr: Callable[[str], str]) -> str:
    normalized = step_label.strip().lower().replace(" ", "_")
    for step_id in WorkflowStepId:
        if step_id.value == normalized:
            return workflow_step_label(step_id, tr=tr)
    return tr(step_label)


class StepAdvancedConfigDialog(QDialog):
    _SIMPLE_STEP_SPECS: dict[WorkflowStepId, tuple[_SpinFieldSpec | _CheckFieldSpec, ...]] = {
        WorkflowStepId.EXTRACTOR: (
            _SpinFieldSpec(
                "max_gleaning_spin",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Max gleaning"),
                "max_gleaning",
                0,
                10,
                3,
            ),
            _SpinFieldSpec(
                "max_term_name_spin",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Max term name length"),
                "max_term_name_length",
                10,
                500,
                200,
            ),
        ),
        WorkflowStepId.TRANSLATOR: (
            _CheckFieldSpec(
                "strip_epub_ruby_check",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Strip EPUB ruby annotations"),
                "strip_epub_ruby",
                True,
            ),
            _SpinFieldSpec(
                "max_tokens_spin",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Max tokens per call"),
                "max_tokens_per_llm_call",
                100,
                100000,
                4000,
            ),
            _SpinFieldSpec(
                "chunk_size_spin",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Chunk size"),
                "chunk_size",
                100,
                5000,
                1000,
            ),
        ),
        WorkflowStepId.OCR: (
            _SpinFieldSpec(
                "ocr_dpi_spin",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "OCR DPI"),
                "ocr_dpi",
                72,
                600,
                150,
            ),
            _CheckFieldSpec(
                "strip_artifacts_check",
                QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Strip artifacts"),
                "strip_llm_artifacts",
                True,
            ),
        ),
    }
    _OVERRIDE_FIELD_SPECS: tuple[_NumericOverrideFieldSpec, ...] = (
        _NumericOverrideFieldSpec(
            QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Temperature"),
            "temperature",
            "temperature_override_checkbox",
            "temperature_override_spin",
            0.0,
            2.0,
            0.0,
            is_float=True,
        ),
        _NumericOverrideFieldSpec(
            QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Timeout"),
            "timeout",
            "timeout_override_checkbox",
            "timeout_override_spin",
            1,
            600,
            60,
            suffix=" s",
        ),
        _NumericOverrideFieldSpec(
            QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Max retries"),
            "max_retries",
            "retries_override_checkbox",
            "retries_override_spin",
            0,
            10,
            3,
        ),
        _NumericOverrideFieldSpec(
            QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Concurrency"),
            "concurrency",
            "concurrency_override_checkbox",
            "concurrency_override_spin",
            1,
            50,
            5,
        ),
    )
    _BATCH_THINKING_OPTIONS = (
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Auto"), "auto"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Off"), "off"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Low"), "low"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Medium"), "medium"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "High"), "high"),
    )
    _REASONING_EFFORT_OPTIONS = (
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Inherit from connection"), ""),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "None"), "none"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Low"), "low"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "Medium"), "medium"),
        (QT_TRANSLATE_NOOP("StepAdvancedConfigDialog", "High"), "high"),
    )

    def __init__(self, route: WorkflowStepRoute, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setWindowModality(Qt.WindowModality.WindowModal)
        self._route = route
        self._serialize: Callable[[], WorkflowStepRoute] = lambda: self._route
        self.setWindowTitle(self.tr("Step Settings"))
        self.setMinimumWidth(420)
        self.resize(460, 420)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(create_tip_label(self._tip_text()))

        form_widget = QWidget()
        self._form_layout = QFormLayout(form_widget)
        self._form_layout.setContentsMargins(16, 8, 8, 8)
        self._form_layout.setVerticalSpacing(8)
        self._form_layout.setHorizontalSpacing(12)

        config = dict(self._route.step_config)
        if self._route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            self._serialize = self._build_translator_batch(config)
        else:
            simple_specs = self._SIMPLE_STEP_SPECS.get(self._route.step_id, ())
            self._serialize = self._build_standard_step(config, simple_specs)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area, 1)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._accept_if_valid)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        apply_hybrid_control_theme(self)
        set_button_tone(self._buttons.button(QDialogButtonBox.StandardButton.Save), "primary")
        set_button_tone(self._buttons.button(QDialogButtonBox.StandardButton.Cancel), "ghost")

    def route(self) -> WorkflowStepRoute:
        return self._serialize()

    def _accept_if_valid(self) -> None:
        try:
            self._serialize()
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Invalid Settings"), str(exc))
            return
        self.accept()

    def _tip_text(self) -> str:
        return self.tr(str(_ADVANCED_TIP_TEXTS.get(self._route.step_id, _ADVANCED_TIP_FALLBACK)))

    def _spin(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _double_spin(self, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(0.1)
        spin.setDecimals(2)
        spin.setValue(value)
        return spin

    def _select_combo_value(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if str(combo.itemData(index) or "") == value:
                combo.setCurrentIndex(index)
                return

    def _create_numeric_override_row(
        self,
        spec: _NumericOverrideFieldSpec,
        value: object,
    ) -> tuple[QWidget, QCheckBox, QSpinBox | QDoubleSpinBox]:
        layout = QHBoxLayout()
        checkbox = QCheckBox(self.tr("Override"))
        if spec.is_float:
            numeric_value = (
                float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float(spec.default)
            )
            input_widget: QSpinBox | QDoubleSpinBox = self._double_spin(
                float(spec.minimum), float(spec.maximum), numeric_value
            )
            has_value = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            input_widget = self._spin(
                int(spec.minimum),
                int(spec.maximum),
                int(value) if isinstance(value, int) else int(spec.default),
            )
            if spec.suffix:
                input_widget.setSuffix(self.tr(spec.suffix))
            has_value = isinstance(value, int)
        input_widget.setEnabled(has_value)
        checkbox.setChecked(has_value)
        checkbox.toggled.connect(input_widget.setEnabled)
        layout.addWidget(checkbox)
        layout.addWidget(input_widget)
        layout.addStretch()
        widget = QWidget()
        widget.setLayout(layout)
        return widget, checkbox, input_widget

    def _serialize_custom_parameters(self) -> dict[str, object]:
        custom_parameters = parse_json_object_text(self.custom_parameters_edit.toPlainText(), tr=self.tr)
        reasoning_effort = str(self.reasoning_effort_combo.currentData() or "")
        if reasoning_effort:
            custom_parameters["reasoning_effort"] = reasoning_effort
        return custom_parameters

    def _build_standard_step(
        self,
        config: Mapping[str, object],
        specs: tuple[_SpinFieldSpec | _CheckFieldSpec, ...],
    ) -> Callable[[], WorkflowStepRoute]:
        readers: dict[str, Callable[[], bool | int]] = {}
        for spec in specs:
            if isinstance(spec, _SpinFieldSpec):
                raw_value = config.get(spec.key, spec.default)
                spin_widget = self._spin(
                    spec.minimum, spec.maximum, int(raw_value) if isinstance(raw_value, int) else spec.default
                )
                readers[spec.key] = spin_widget.value
                setattr(self, spec.attr_name, spin_widget)
                self._form_layout.addRow(self.tr(str(spec.label)), spin_widget)
                continue

            check_widget = QCheckBox()
            check_widget.setChecked(bool(config.get(spec.key, spec.default)))
            readers[spec.key] = check_widget.isChecked
            setattr(self, spec.attr_name, check_widget)
            self._form_layout.addRow(self.tr(str(spec.label)), check_widget)

        self._form_layout.addRow(
            create_tip_label(
                self.tr("Connection overrides apply only to this workflow step and override the selected connection.")
            )
        )

        override_writers: list[Callable[[dict[str, object]], None]] = []

        def _make_override_writer(
            spec: _NumericOverrideFieldSpec,
            checkbox: QCheckBox,
            input_widget: QSpinBox | QDoubleSpinBox,
        ) -> Callable[[dict[str, object]], None]:
            def _write(payload: dict[str, object]) -> None:
                if not checkbox.isChecked():
                    return
                payload[spec.key] = float(input_widget.value()) if spec.is_float else int(input_widget.value())

            return _write

        for override_spec in self._OVERRIDE_FIELD_SPECS:
            row_widget, checkbox, input_widget = self._create_numeric_override_row(
                override_spec, config.get(override_spec.key)
            )
            setattr(self, override_spec.checkbox_attr, checkbox)
            setattr(self, override_spec.input_attr, input_widget)
            self._form_layout.addRow(self.tr(str(override_spec.label)), row_widget)
            override_writers.append(_make_override_writer(override_spec, checkbox, input_widget))

        kwargs_config = config.get("kwargs") if isinstance(config.get("kwargs"), dict) else {}
        kwargs_payload = dict(kwargs_config) if isinstance(kwargs_config, dict) else {}
        reasoning_value = str(kwargs_payload.pop("reasoning_effort", "") or "")
        self.reasoning_effort_combo = QComboBox()
        for label, value in self._REASONING_EFFORT_OPTIONS:
            self.reasoning_effort_combo.addItem(self.tr(str(label)), value)
        self._select_combo_value(self.reasoning_effort_combo, reasoning_value)
        self._form_layout.addRow(self.tr("Reasoning effort"), self.reasoning_effort_combo)

        self.custom_parameters_edit = QTextEdit()
        self.custom_parameters_edit.setMaximumHeight(90)
        self.custom_parameters_edit.setPlaceholderText('{"reasoning_effort": "none"}')
        if kwargs_payload:
            self.custom_parameters_edit.setPlainText(json.dumps(kwargs_payload, indent=2, ensure_ascii=False))
        self._form_layout.addRow(self.tr("Custom parameters"), self.custom_parameters_edit)

        def _serialize_standard_step() -> WorkflowStepRoute:
            preserved = {
                str(key): value
                for key, value in config.items()
                if key not in readers and key not in {"temperature", "timeout", "max_retries", "concurrency", "kwargs"}
            }
            preserved.update({key: read() for key, read in readers.items()})
            for write_override in override_writers:
                write_override(preserved)

            custom_parameters = self._serialize_custom_parameters()
            if custom_parameters:
                preserved["kwargs"] = custom_parameters

            return self._route.model_copy(update={"step_config": preserved})

        return _serialize_standard_step

    def _build_translator_batch(self, config: Mapping[str, object]) -> Callable[[], WorkflowStepRoute]:
        provider_combo = QComboBox()
        provider_combo.addItem(self.tr("Disabled"), "")
        provider_combo.addItem(self.tr("Gemini AI Studio"), "gemini_ai_studio")
        self._select_combo_value(provider_combo, str(config.get("provider") or ""))

        api_key_edit = QLineEdit(str(config.get("api_key") or ""))
        raw_batch_size = config.get("batch_size", 100)
        batch_size_spin = self._spin(1, 5000, int(raw_batch_size) if isinstance(raw_batch_size, int) else 100)
        thinking_combo = QComboBox()
        for label, value in self._BATCH_THINKING_OPTIONS:
            thinking_combo.addItem(self.tr(str(label)), value)
        self._select_combo_value(thinking_combo, str(config.get("thinking_mode") or "auto"))

        self._form_layout.addRow(self.tr("Provider"), provider_combo)
        self._form_layout.addRow(self.tr("API key"), api_key_edit)
        self._form_layout.addRow(self.tr("Batch size"), batch_size_spin)
        self._form_layout.addRow(self.tr("Thinking mode"), thinking_combo)

        def _serialize_batch() -> WorkflowStepRoute:
            provider = str(provider_combo.currentData() or "")
            if not provider:
                return self._route.model_copy(update={"connection_label": None, "model": None, "step_config": {}})
            return self._route.model_copy(
                update={
                    "connection_label": provider_combo.currentText().strip() or None,
                    "step_config": {
                        "provider": provider,
                        "api_key": api_key_edit.text().strip(),
                        "batch_size": int(batch_size_spin.value()),
                        "thinking_mode": str(thinking_combo.currentData() or "auto"),
                    },
                }
            )

        return _serialize_batch


class WorkflowRoutesEditor(QWidget):
    EditTrigger = QTableWidget.EditTrigger
    _COLUMN_COUNT = 4
    _COLUMN_SIDE_MARGIN = 12
    _COLUMN_SPACING = 8
    _ROW_VIEWPORT_PADDING = 12
    _MIN_STEP_COLUMN_WIDTH = 100
    _MIN_ADVANCED_COLUMN_WIDTH = 88
    _MIN_CONNECTION_COLUMN_WIDTH = 180
    _MIN_MODEL_COLUMN_WIDTH = 160
    _TABLE_STYLESHEET = (
        "WorkflowRoutesEditor {"
        " background-color: transparent;"
        "}"
        " QFrame#workflowRoutesHeader {"
        " background-color: #f5f5f5;"
        " border: 1px solid #e0e0e0;"
        " border-bottom: none;"
        "}"
        " QFrame#workflowRouteRow {"
        " background-color: white;"
        " border-left: 1px solid #e0e0e0;"
        " border-right: 1px solid #e0e0e0;"
        " border-bottom: 1px solid #e0e0e0;"
        "}"
        " QLabel#workflowRouteHeader {"
        " color: #333333;"
        " font-weight: bold;"
        "}"
        " QLabel#workflowRouteCell, QLabel#workflowRouteDash {"
        " color: #333333;"
        "}"
        " QScrollArea {"
        " background-color: transparent;"
        " border: none;"
        "}"
        " QLineEdit, QComboBox {"
        " background-color: white;"
        " color: #333333;"
        "}"
    )

    def __init__(
        self,
        routes: list[WorkflowStepRoute],
        connection_choices: list[ConnectionChoice],
        *,
        hint_text: str,
        max_visible_rows: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._connection_choices = connection_choices
        self._connection_choice_by_id = {choice.connection_id: choice for choice in connection_choices}
        self._max_visible_rows = max_visible_rows
        self.rows: list[RouteRow] = []
        self.table = self
        self._items: dict[tuple[int, int], QTableWidgetItem] = {}
        self._cell_widgets: dict[tuple[int, int], QWidget] = {}
        self._header_columns: list[QWidget] = []
        self._row_columns: list[list[QWidget]] = []

        self.setObjectName("workflowRoutesEditor")
        self.setStyleSheet(self._TABLE_STYLESHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._hint_label = create_tip_label(hint_text)
        layout.addWidget(self._hint_label)

        self._header = self._build_frame("workflowRoutesHeader")
        self._header_columns = self._build_columns(
            self._header,
            [
                self._header_label(self.tr("Step")),
                self._header_label(self.tr("Connection")),
                self._header_label(self.tr("Model")),
                self._header_label(self.tr("Advanced")),
            ],
        )
        layout.addWidget(self._header)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._scroll_area.setWidget(self._rows_container)
        self._scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(self._scroll_area)
        self.set_routes(routes)

    def set_routes(self, routes: list[WorkflowStepRoute]) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if isinstance(widget, QWidget):
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.rows.clear()
        self._items.clear()
        self._cell_widgets.clear()
        self._row_columns.clear()

        for row_index, route in enumerate(routes):
            row_frame = self._build_frame("workflowRouteRow")
            step_text = workflow_step_label(route.step_id, tr=self.tr)
            step_label = self._body_label(step_text)
            step_tooltip = workflow_step_tooltip(route.step_id, tr=self.tr)
            step_label.setToolTip(step_tooltip)

            if route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                connection_label = self._body_label(route.connection_label or self.tr("Direct batch config"))
                batch_enabled = isinstance(route.step_config.get("provider"), str) and bool(
                    str(route.step_config.get("provider") or "").strip()
                )
                model_edit = self._build_model_edit(route.model or "", readonly=not batch_enabled)
                advanced_widget = self._build_advanced_cell(row_index)
                columns = self._build_columns(
                    row_frame,
                    [
                        step_label,
                        connection_label,
                        self._wrap_cell_widget(model_edit),
                        advanced_widget,
                    ],
                )
                route_row = RouteRow(
                    route=route,
                    connection_combo=None,
                    model_edit=model_edit,
                    connection_label_widget=connection_label,
                    row_widget=row_frame,
                    step_label_widget=step_label,
                )
                self._items[(row_index, 0)] = self._step_item(step_text, tooltip=step_tooltip)
                self._items[(row_index, 1)] = self._item(connection_label.text())
            else:
                combo = self._build_connection_combo(route.connection_id)
                model_edit = self._build_model_edit(route.model or "")
                combo.currentIndexChanged.connect(
                    lambda _i, c=combo, e=model_edit: self._sync_model_from_connection(c, e)
                )
                advanced_widget = self._build_advanced_cell(row_index)
                columns = self._build_columns(
                    row_frame,
                    [
                        step_label,
                        self._wrap_cell_widget(combo),
                        self._wrap_cell_widget(model_edit),
                        advanced_widget,
                    ],
                )
                route_row = RouteRow(
                    route=route,
                    connection_combo=combo,
                    model_edit=model_edit,
                    row_widget=row_frame,
                    step_label_widget=step_label,
                )
                self._items[(row_index, 0)] = self._step_item(step_text, tooltip=step_tooltip)

            self.rows.append(route_row)
            self._row_columns.append(columns)
            self._cell_widgets[(row_index, 1)] = columns[1]
            self._cell_widgets[(row_index, 2)] = columns[2]
            self._cell_widgets[(row_index, 3)] = columns[3]
            self._rows_layout.addWidget(row_frame)

        self._rows_layout.addStretch()
        self._update_layout_geometry()

    def set_connection_choices(self, connection_choices: list[ConnectionChoice]) -> None:
        self._connection_choices = connection_choices
        self._connection_choice_by_id = {choice.connection_id: choice for choice in connection_choices}

    def build_routes(self) -> list[WorkflowStepRoute]:
        routes: list[WorkflowStepRoute] = []
        for row in self.rows:
            if row.route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                provider = row.route.step_config.get("provider")
                has_provider = isinstance(provider, str) and bool(provider.strip())
                routes.append(
                    row.route.model_copy(
                        update={
                            "connection_label": (
                                row.connection_label_widget.text().strip()
                                if row.connection_label_widget is not None and has_provider
                                else None
                            ),
                            "model": (row.model_edit.text().strip() or None) if has_provider else None,
                            "step_config": dict(row.route.step_config),
                        }
                    )
                )
                continue
            connection_id = row.connection_combo.currentData() if row.connection_combo is not None else None
            connection_id_str = str(connection_id) if isinstance(connection_id, str) and connection_id else None
            connection_label = None
            if row.connection_combo is not None and connection_id_str is not None:
                connection_label = row.connection_combo.currentText().strip() or None
            routes.append(
                row.route.model_copy(
                    update={
                        "connection_id": connection_id_str,
                        "connection_label": connection_label,
                        "model": row.model_edit.text().strip() or None,
                        "step_config": dict(row.route.step_config),
                    }
                )
            )
        return routes

    def validate_routes(self) -> str | None:
        return validate_workflow_routes(self.build_routes(), tr=self.tr)

    def _build_connection_combo(self, connection_id: str | None) -> QComboBox:
        combo = QSearchableComboBox()
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(16)
        combo.setStyleSheet("QComboBox { font-size: 13px; padding: 4px 8px; }")
        combo.setMinimumHeight(combo.sizeHint().height())
        combo.addItem(self.tr("Select connection"), "")
        for choice in self._connection_choices:
            combo.addItem(choice.label, choice.connection_id)
        if connection_id:
            index = combo.findData(connection_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        return combo

    def _build_model_edit(self, value: str, *, readonly: bool = False) -> QLineEdit:
        model_edit = QLineEdit(value)
        model_edit.setReadOnly(readonly)
        model_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_edit.setStyleSheet("QLineEdit { font-size: 13px; padding: 4px 6px; }")
        model_edit.setMinimumHeight(model_edit.sizeHint().height())
        return model_edit

    def _wrap_cell_widget(self, widget: QWidget, *, center_in_cell: bool = False) -> QWidget:
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        alignment = Qt.AlignmentFlag.AlignVCenter
        if center_in_cell:
            alignment |= Qt.AlignmentFlag.AlignHCenter
        layout.addWidget(widget, 0, alignment)
        container.setMinimumHeight(max(widget.minimumHeight(), widget.sizeHint().height()))
        container.setMinimumWidth(widget.sizeHint().width())
        return container

    def _sync_model_from_connection(self, combo: QComboBox, model_edit: QLineEdit) -> None:
        connection_id = combo.currentData()
        if not isinstance(connection_id, str) or not connection_id:
            return
        default_model = next(
            (choice.default_model for choice in self._connection_choices if choice.connection_id == connection_id),
            None,
        )
        if default_model:
            model_edit.setText(default_model)

    def _item(self, text: str, *, tooltip: str | None = None, centered: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if tooltip:
            item.setToolTip(tooltip)
        if centered:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _step_item(self, step_label: str, *, tooltip: str) -> QTableWidgetItem:
        item = self._item(step_label)
        item.setToolTip(tooltip)
        return item

    def _build_advanced_cell(self, row: int) -> QWidget:
        button = QPushButton(self.tr("Advanced"))
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(button.sizeHint().height())
        button.clicked.connect(lambda _checked=False, r=row: self._open_step_advanced_dialog(r))
        return self._wrap_cell_widget(button, center_in_cell=True)

    def _open_step_advanced_dialog(self, row: int) -> None:
        if row < 0 or row >= len(self.rows):
            return
        route_row = self.rows[row]
        parent = self.window()
        dialog = StepAdvancedConfigDialog(route_row.route, parent if isinstance(parent, QWidget) else self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated_route = dialog.route()
        route_row.route = updated_route
        if updated_route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            if route_row.connection_label_widget is not None:
                route_row.connection_label_widget.setText(
                    updated_route.connection_label or self.tr("Direct batch config")
                )
            if updated_route.step_config.get("provider"):
                route_row.model_edit.setReadOnly(False)
            else:
                route_row.model_edit.setReadOnly(True)
                route_row.model_edit.clear()

    def _build_frame(self, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return frame

    def _build_columns(self, parent: QWidget, widgets: list[QWidget]) -> list[QWidget]:
        layout = QHBoxLayout(parent)
        layout.setContentsMargins(self._COLUMN_SIDE_MARGIN, 8, self._COLUMN_SIDE_MARGIN, 8)
        layout.setSpacing(self._COLUMN_SPACING)
        hosts: list[QWidget] = []
        for index, widget in enumerate(widgets):
            host = QWidget(parent)
            host.setSizePolicy(
                QSizePolicy.Policy.Expanding if index in {1, 2} else QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(0)
            alignment = Qt.AlignmentFlag.AlignVCenter
            if index == 3:
                alignment |= Qt.AlignmentFlag.AlignHCenter
            else:
                alignment |= Qt.AlignmentFlag.AlignLeft
            host_layout.addWidget(widget, 0, alignment)
            layout.addWidget(host, 1 if index in {1, 2} else 0)
            hosts.append(host)
        return hosts

    def _header_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("workflowRouteHeader")
        return label

    def _body_label(self, text: str, *, object_name: str = "workflowRouteCell", centered: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(False)
        label.setAlignment(
            Qt.AlignmentFlag.AlignCenter if centered else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return label

    def _update_layout_geometry(self) -> None:
        self._apply_column_widths()
        for row in self.rows:
            if row.row_widget is not None:
                row.row_widget.adjustSize()
                row.row_widget.setFixedHeight(row.row_widget.sizeHint().height())

        row_heights = [self.rowHeight(index) for index in range(self.rowCount())]
        visible_rows = (
            len(row_heights) if self._max_visible_rows is None else min(len(row_heights), self._max_visible_rows)
        )
        visible_height = sum(row_heights[:visible_rows])
        if visible_rows > 0:
            visible_height += self._rows_layout.spacing() * (visible_rows - 1)

        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if self._max_visible_rows is None or len(row_heights) <= self._max_visible_rows
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        viewport_padding = self._ROW_VIEWPORT_PADDING if visible_rows > 0 else 2
        self._scroll_area.setFixedHeight(max(visible_height + viewport_padding, 2))
        self.setMinimumWidth(self._minimum_editor_width())

        layout = self.layout()
        assert layout is not None
        editor_height = (
            layout.contentsMargins().top()
            + self._hint_label.sizeHint().height()
            + layout.spacing()
            + self._header.sizeHint().height()
            + layout.spacing()
            + self._scroll_area.height()
            + layout.contentsMargins().bottom()
        )
        self.setMinimumHeight(editor_height)
        self.updateGeometry()

    def _minimum_editor_width(self) -> int:
        return sum(self._minimum_column_widths()) + self._column_layout_overhead()

    def _column_layout_overhead(self) -> int:
        return self._COLUMN_SIDE_MARGIN * 2 + self._COLUMN_SPACING * (self._COLUMN_COUNT - 1)

    def _minimum_column_widths(self) -> list[int]:
        def _max_width(default: int, widgets: list[QWidget]) -> int:
            return max(
                default,
                *(max(widget.sizeHint().width(), widget.minimumSizeHint().width()) for widget in widgets),
            )

        step_widgets = [
            self._header_columns[0],
            *(row.step_label_widget for row in self.rows if row.step_label_widget is not None),
        ]
        connection_widgets = [
            self._header_columns[1],
            *(self._cell_widgets[index, 1] for index in range(self.rowCount())),
        ]
        model_widgets = [self._header_columns[2], *(self._cell_widgets[index, 2] for index in range(self.rowCount()))]
        advanced_widgets = [
            self._header_columns[3],
            *(self._cell_widgets[index, 3] for index in range(self.rowCount())),
        ]
        return [
            _max_width(self._MIN_STEP_COLUMN_WIDTH, step_widgets),
            _max_width(self._MIN_CONNECTION_COLUMN_WIDTH, connection_widgets),
            _max_width(self._MIN_MODEL_COLUMN_WIDTH, model_widgets),
            _max_width(self._MIN_ADVANCED_COLUMN_WIDTH, advanced_widgets),
        ]

    def _apply_column_widths(self) -> None:
        minimum_widths = self._minimum_column_widths()
        available_width = max(self._scroll_area.viewport().width(), self._minimum_editor_width())
        step_width, connection_width, model_width, advanced_width = minimum_widths
        extra_width = max(
            available_width
            - self._column_layout_overhead()
            - step_width
            - connection_width
            - model_width
            - advanced_width,
            0,
        )
        connection_growth = int(extra_width * 0.55)
        model_growth = extra_width - connection_growth
        widths = [
            step_width,
            connection_width + connection_growth,
            model_width + model_growth,
            advanced_width,
        ]
        for columns in [self._header_columns, *self._row_columns]:
            if not columns:
                continue
            for host, width in zip(columns, widths, strict=False):
                host.setFixedWidth(width)

    def rowCount(self) -> int:
        return len(self.rows)

    def columnCount(self) -> int:
        return self._COLUMN_COUNT

    def editTriggers(self) -> QTableWidget.EditTrigger:
        return QTableWidget.EditTrigger.NoEditTriggers

    def verticalScrollBarPolicy(self) -> Qt.ScrollBarPolicy:
        return self._scroll_area.verticalScrollBarPolicy()

    def columnWidth(self, column: int) -> int:
        if column < 0 or column >= len(self._header_columns):
            return 0
        return self._header_columns[column].width() or self._header_columns[column].minimumWidth()

    def rowHeight(self, row: int) -> int:
        if row < 0 or row >= len(self.rows):
            return 0
        row_widget = self.rows[row].row_widget
        if row_widget is None:
            return 0
        return row_widget.height() or row_widget.sizeHint().height()

    def item(self, row: int, column: int) -> QTableWidgetItem | None:
        return self._items.get((row, column))

    def cellWidget(self, row: int, column: int) -> QWidget | None:
        return self._cell_widgets.get((row, column))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_layout_geometry()


class WorkflowProfileEditorDialog(QDialog):
    def __init__(
        self,
        profile: WorkflowProfileDetail,
        connection_choices: list[ConnectionChoice],
        *,
        allow_name_edit: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setWindowModality(Qt.WindowModality.WindowModal)
        self._original_profile = profile
        self._connection_choices = connection_choices
        self._allow_name_edit = allow_name_edit
        self._layout_refresh_timer = QTimer(self)
        self._layout_refresh_timer.setSingleShot(True)
        self._layout_refresh_timer.timeout.connect(self._refresh_body_layout)
        self.setWindowTitle(self.tr("Workflow Profile"))
        self.setMinimumSize(780, 260)
        self.setSizeGripEnabled(True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self._body_scroll = QScrollArea()
        self._body_scroll.setWidgetResizable(True)
        self._body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        body_widget = QWidget()
        self._body_layout = QVBoxLayout(body_widget)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(4)
        self._body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = create_tip_label(
            self.tr(
                "A workflow profile is a user-facing wrapper over the existing step-based config. Edit connection and model choices here."
            )
        )
        self._body_layout.addWidget(header)

        self.general_section = QCollapsible(self.tr("General"))
        general_widget = QWidget()
        basics_layout = QFormLayout(general_widget)
        basics_layout.setContentsMargins(16, 8, 8, 8)
        basics_layout.setVerticalSpacing(8)
        basics_layout.setHorizontalSpacing(12)
        self.name_edit = QLineEdit(self._original_profile.name)
        self.name_edit.setEnabled(self._allow_name_edit)
        self.target_language_combo = QSearchableComboBox()
        self.target_language_combo.setEditable(True)
        seen_languages: set[str] = set()
        for display_name, _code in LANGUAGES:
            if display_name in seen_languages:
                continue
            seen_languages.add(display_name)
            self.target_language_combo.addItem(display_name)
        index = self.target_language_combo.findText(self._original_profile.target_language)
        if index >= 0:
            self.target_language_combo.setCurrentIndex(index)
        else:
            self.target_language_combo.setEditText(self._original_profile.target_language)

        basics_layout.addRow(self.tr("Profile name"), self.name_edit)
        basics_layout.addRow(self.tr("Target language"), self.target_language_combo)
        self.general_section.setContent(general_widget)
        self.general_section.collapse(False)
        self.general_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._body_layout.addWidget(self.general_section)

        self.routes_section = QCollapsible(self.tr("Workflow Routing"))
        self.routes_editor = WorkflowRoutesEditor(
            self._original_profile.routes,
            self._connection_choices,
            hint_text=self.tr("Use the Advanced column to edit step-specific settings."),
            parent=self,
        )
        self.routes_table = self.routes_editor.table
        self._rows = self.routes_editor.rows
        self.routes_section.setContent(self.routes_editor)
        self.routes_section.expand(False)
        self.routes_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._body_layout.addWidget(self.routes_section)

        self._body_scroll.setWidget(body_widget)
        layout.addWidget(self._body_scroll, 1)

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        footer.accepted.connect(self._accept_if_valid)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)
        apply_hybrid_control_theme(self)
        set_button_tone(footer.button(QDialogButtonBox.StandardButton.Save), "primary")
        set_button_tone(footer.button(QDialogButtonBox.StandardButton.Cancel), "ghost")
        for section in (self.general_section, self.routes_section):
            section.toggled.connect(self._refresh_body_layout)
        self._schedule_body_layout_refresh()
        self.resize(
            max(self.minimumWidth(), min(self.sizeHint().width(), 920)), min(max(self.sizeHint().height(), 420), 720)
        )

    def profile(self) -> WorkflowProfileDetail:
        return WorkflowProfileDetail(
            profile_id=self._original_profile.profile_id,
            name=self.name_edit.text().strip() or self._original_profile.name,
            kind=self._original_profile.kind,
            target_language=self.target_language_combo.currentText().strip() or self._original_profile.target_language,
            routes=self.routes_editor.build_routes(),
            is_default=self._original_profile.is_default,
        )

    def _accept_if_valid(self) -> None:
        target_language = self.target_language_combo.currentText().strip()
        if not target_language:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Target language is required."))
            return
        route_error = self.routes_editor.validate_routes()
        if route_error is not None:
            QMessageBox.warning(
                self,
                self.tr("Missing Information"),
                route_error,
            )
            return
        self.accept()

    def _refresh_body_layout(self, *_args: object) -> None:
        self.routes_editor.updateGeometry()
        self.routes_editor.adjustSize()
        self._sync_section_height(self.general_section)
        self._sync_section_height(self.routes_section)
        body_widget = self._body_scroll.widget()
        if isinstance(body_widget, QWidget):
            body_widget.adjustSize()
        self._body_layout.activate()
        layout = self.layout()
        if layout is not None:
            layout.activate()

    def _schedule_body_layout_refresh(self) -> None:
        self._layout_refresh_timer.start(0)

    def _sync_section_height(self, section: QCollapsible) -> None:
        content = section.content()
        if section.isExpanded():
            if not content.isVisible():
                content.show()
            content.updateGeometry()
            content.adjustSize()
            target_height = content.sizeHint().height() + 10
        else:
            target_height = 0
            content.hide()
        if content.maximumHeight() != target_height:
            content.setMaximumHeight(target_height)
        layout = section.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        total_height = (
            margins.top()
            + section.toggleButton().sizeHint().height()
            + (layout.spacing() if section.isExpanded() else 0)
            + target_height
            + margins.bottom()
        )
        section.setFixedHeight(total_height)
        section.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._schedule_body_layout_refresh()
