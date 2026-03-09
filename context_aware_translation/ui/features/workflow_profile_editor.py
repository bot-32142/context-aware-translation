from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.llm.image_generator import ImageBackend
from context_aware_translation.ui.constants import LANGUAGES
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets.collapsible_section import CollapsibleSection


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


@dataclass(frozen=True)
class _SpinFieldSpec:
    attr_name: str
    label: str
    key: str
    minimum: int
    maximum: int
    default: int


@dataclass(frozen=True)
class _CheckFieldSpec:
    attr_name: str
    label: str
    key: str
    default: bool


@dataclass(frozen=True)
class _ChoiceFieldSpec:
    attr_name: str
    label: str
    key: str
    default: str
    options: tuple[tuple[str, str], ...]


class StepAdvancedConfigDialog(QDialog):
    _TIP_TEXTS = {
        WorkflowStepId.EXTRACTOR: "Extraction settings control how aggressively terms are discovered.",
        WorkflowStepId.TRANSLATOR: "Translator settings tune chunk sizing and request budget.",
        WorkflowStepId.OCR: "OCR settings control image compression and artifact cleanup.",
        WorkflowStepId.IMAGE_REEMBEDDING: "Image reembedding settings choose the image-edit backend for this workflow step.",
        WorkflowStepId.TRANSLATOR_BATCH: "Batch settings configure optional async translation jobs.",
    }
    _SIMPLE_STEP_SPECS: dict[WorkflowStepId, tuple[_SpinFieldSpec | _CheckFieldSpec | _ChoiceFieldSpec, ...]] = {
        WorkflowStepId.EXTRACTOR: (
            _SpinFieldSpec("max_gleaning_spin", "Max gleaning", "max_gleaning", 0, 10, 3),
            _SpinFieldSpec("max_term_name_spin", "Max term name length", "max_term_name_length", 10, 500, 200),
        ),
        WorkflowStepId.TRANSLATOR: (
            _SpinFieldSpec("max_tokens_spin", "Max tokens per call", "max_tokens_per_llm_call", 100, 100000, 4000),
            _SpinFieldSpec("chunk_size_spin", "Chunk size", "chunk_size", 100, 5000, 1000),
        ),
        WorkflowStepId.OCR: (
            _SpinFieldSpec("ocr_dpi_spin", "OCR DPI", "ocr_dpi", 72, 600, 150),
            _CheckFieldSpec("strip_artifacts_check", "Strip artifacts", "strip_llm_artifacts", True),
        ),
        WorkflowStepId.IMAGE_REEMBEDDING: (
            _ChoiceFieldSpec(
                "backend_combo",
                "Backend",
                "backend",
                ImageBackend.GEMINI.value,
                (
                    ("Gemini", ImageBackend.GEMINI.value),
                    ("OpenAI", ImageBackend.OPENAI.value),
                    ("Qwen", ImageBackend.QWEN.value),
                ),
            ),
        ),
    }
    _BATCH_THINKING_OPTIONS = (
        ("Auto", "auto"),
        ("Off", "off"),
        ("Low", "low"),
        ("Medium", "medium"),
        ("High", "high"),
    )

    def __init__(self, route: WorkflowStepRoute, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._route = route
        self._serialize: Callable[[], WorkflowStepRoute] = lambda: self._route
        self.setWindowTitle(self.tr("Step Settings"))
        self.setMinimumWidth(420)
        self.resize(460, 360)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(create_tip_label(self._tip_text()))

        form_widget = QWidget()
        self._form_layout = QFormLayout(form_widget)
        self._form_layout.setContentsMargins(16, 8, 8, 8)
        self._form_layout.setVerticalSpacing(8)
        self._form_layout.setHorizontalSpacing(12)

        config = dict(self._route.step_config)
        if simple_specs := self._SIMPLE_STEP_SPECS.get(self._route.step_id):
            self._serialize = self._build_simple_step(config, simple_specs)
        elif self._route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            self._serialize = self._build_translator_batch(config)
        else:
            self._form_layout.addRow(
                create_tip_label(self.tr("This step has no additional settings beyond connection and model."))
            )

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def route(self) -> WorkflowStepRoute:
        return self._serialize()

    def _tip_text(self) -> str:
        return self.tr(self._TIP_TEXTS.get(self._route.step_id, "Edit advanced settings for this workflow step."))

    def _spin(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _select_combo_value(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if str(combo.itemData(index) or "") == value:
                combo.setCurrentIndex(index)
                return

    def _build_simple_step(
        self,
        config: dict[str, object],
        specs: tuple[_SpinFieldSpec | _CheckFieldSpec | _ChoiceFieldSpec, ...],
    ) -> Callable[[], WorkflowStepRoute]:
        readers: dict[str, Callable[[], bool | int | float | str | None]] = {}
        for spec in specs:
            if isinstance(spec, _SpinFieldSpec):
                widget = self._spin(spec.minimum, spec.maximum, int(config.get(spec.key, spec.default) or spec.default))
                readers[spec.key] = lambda w=widget: int(w.value())
            elif isinstance(spec, _CheckFieldSpec):
                widget = QCheckBox()
                widget.setChecked(bool(config.get(spec.key, spec.default)))
                readers[spec.key] = lambda w=widget: bool(w.isChecked())
            else:
                widget = QComboBox()
                for label, value in spec.options:
                    widget.addItem(label, value)
                self._select_combo_value(widget, str(config.get(spec.key) or spec.default))
                readers[spec.key] = lambda w=widget, d=spec.default: str(w.currentData() or d)
            setattr(self, spec.attr_name, widget)
            self._form_layout.addRow(self.tr(spec.label), widget)
        return lambda: self._route.model_copy(update={"step_config": {key: read() for key, read in readers.items()}})

    def _build_translator_batch(self, config: dict[str, object]) -> Callable[[], WorkflowStepRoute]:
        provider_combo = QComboBox()
        provider_combo.addItem(self.tr("Disabled"), "")
        provider_combo.addItem(self.tr("Gemini AI Studio"), "gemini_ai_studio")
        self._select_combo_value(provider_combo, str(config.get("provider") or ""))

        api_key_edit = QLineEdit(str(config.get("api_key") or ""))
        model_edit = QLineEdit(self._route.model or "")
        batch_size_spin = self._spin(1, 5000, int(config.get("batch_size", 100) or 100))
        thinking_combo = QComboBox()
        for label, value in self._BATCH_THINKING_OPTIONS:
            thinking_combo.addItem(label, value)
        self._select_combo_value(thinking_combo, str(config.get("thinking_mode") or "auto"))

        self._form_layout.addRow(self.tr("Provider"), provider_combo)
        self._form_layout.addRow(self.tr("API key"), api_key_edit)
        self._form_layout.addRow(self.tr("Model"), model_edit)
        self._form_layout.addRow(self.tr("Batch size"), batch_size_spin)
        self._form_layout.addRow(self.tr("Thinking mode"), thinking_combo)

        def _serialize_batch() -> WorkflowStepRoute:
            provider = str(provider_combo.currentData() or "")
            if not provider:
                return self._route.model_copy(update={"model": None, "step_config": {}})
            return self._route.model_copy(
                update={
                    "model": model_edit.text().strip() or None,
                    "step_config": {
                        "provider": provider,
                        "api_key": api_key_edit.text().strip(),
                        "batch_size": int(batch_size_spin.value()),
                        "thinking_mode": str(thinking_combo.currentData() or "auto"),
                    },
                }
            )

        return _serialize_batch


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
        self._original_profile = profile
        self._connection_choices = connection_choices
        self._allow_name_edit = allow_name_edit
        self._rows: list[RouteRow] = []
        self.setWindowTitle(self.tr("Workflow Profile"))
        self.setMinimumSize(650, 600)
        self.resize(750, 750)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = create_tip_label(
            self.tr(
                "A workflow profile is a user-facing wrapper over the existing step-based config. Edit connection and model choices here."
            )
        )
        layout.addWidget(header)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        self.general_section = CollapsibleSection(self.tr("General"))
        general_widget = QWidget()
        basics_layout = QFormLayout(general_widget)
        basics_layout.setContentsMargins(16, 8, 8, 8)
        basics_layout.setVerticalSpacing(8)
        basics_layout.setHorizontalSpacing(12)
        self.name_edit = QLineEdit(self._original_profile.name)
        self.name_edit.setEnabled(self._allow_name_edit)
        self.target_language_combo = QComboBox()
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
        self.general_section.set_content(general_widget)
        self.general_section.set_expanded(True)
        scroll_layout.addWidget(self.general_section)

        self.routes_section = CollapsibleSection(self.tr("Workflow Routing"))
        routes_widget = QWidget()
        routes_layout = QVBoxLayout(routes_widget)
        routes_layout.addWidget(create_tip_label(self.tr("Double-click a step to edit advanced step settings.")))
        self.routes_table = QTableWidget(0, 3)
        self.routes_table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
        self.routes_table.verticalHeader().setVisible(False)
        self.routes_table.setAlternatingRowColors(True)
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routes_table.verticalHeader().setDefaultSectionSize(34)
        self.routes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.routes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.routes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.routes_table.horizontalHeader().setStretchLastSection(True)
        self.routes_table.cellDoubleClicked.connect(self._open_step_advanced_dialog)
        self._populate_routes()
        routes_layout.addWidget(self.routes_table)
        self.routes_section.set_content(routes_widget)
        self.routes_section.set_expanded(True)
        scroll_layout.addWidget(self.routes_section)
        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

        footer = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        footer.accepted.connect(self._accept_if_valid)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)

    def profile(self) -> WorkflowProfileDetail:
        return WorkflowProfileDetail(
            profile_id=self._original_profile.profile_id,
            name=self.name_edit.text().strip() or self._original_profile.name,
            kind=self._original_profile.kind,
            target_language=self.target_language_combo.currentText().strip() or self._original_profile.target_language,
            routes=self._build_routes(),
            is_default=self._original_profile.is_default,
        )

    def _populate_routes(self) -> None:
        self.routes_table.setRowCount(0)
        self._rows.clear()
        for route in self._original_profile.routes:
            row = self.routes_table.rowCount()
            self.routes_table.insertRow(row)
            self.routes_table.setItem(row, 0, self._item(route.step_label))

            if route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                self.routes_table.setItem(row, 1, self._item(route.connection_label or self.tr("Direct batch config")))
                model_edit = QLineEdit(route.model or "")
                model_edit.setReadOnly(True)
                self.routes_table.setCellWidget(row, 2, model_edit)
                self._rows.append(RouteRow(route=route, connection_combo=None, model_edit=model_edit))
                continue

            combo = QComboBox()
            combo.addItem(self.tr("Select connection"), "")
            for choice in self._connection_choices:
                combo.addItem(choice.label, choice.connection_id)
            if route.connection_id:
                index = combo.findData(route.connection_id)
                if index >= 0:
                    combo.setCurrentIndex(index)
            model_edit = QLineEdit(route.model or "")
            combo.currentIndexChanged.connect(lambda _i, c=combo, e=model_edit: self._sync_model_from_connection(c, e))
            self.routes_table.setCellWidget(row, 1, combo)
            self.routes_table.setCellWidget(row, 2, model_edit)
            self._rows.append(RouteRow(route=route, connection_combo=combo, model_edit=model_edit))

    def _build_routes(self) -> list[WorkflowStepRoute]:
        routes: list[WorkflowStepRoute] = []
        for row in self._rows:
            if row.route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                routes.append(row.route)
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
                    }
                )
            )
        return routes

    def _accept_if_valid(self) -> None:
        target_language = self.target_language_combo.currentText().strip()
        if not target_language:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Target language is required."))
            return
        for row in self._rows:
            if row.route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                continue
            if row.connection_combo is None or not str(row.connection_combo.currentData() or "").strip():
                QMessageBox.warning(
                    self,
                    self.tr("Missing Connection"),
                    self.tr("Every workflow step must use a connection."),
                )
                return
            if not row.model_edit.text().strip():
                QMessageBox.warning(
                    self,
                    self.tr("Missing Model"),
                    self.tr("Every workflow step must have a model."),
                )
                return
        self.accept()

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

    def _item(self, text: str) -> QTableWidgetItem:
        return QTableWidgetItem(text)

    def _open_step_advanced_dialog(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._rows):
            return
        route_row = self._rows[row]
        dialog = StepAdvancedConfigDialog(route_row.route, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated_route = dialog.route()
        route_row.route = updated_route
        if updated_route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            route_row.model_edit.setText(updated_route.model or "")
