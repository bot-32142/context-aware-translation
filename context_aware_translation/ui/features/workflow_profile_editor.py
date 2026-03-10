from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
from context_aware_translation.ui.constants import LANGUAGES
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets.collapsible_section import CollapsibleSection


@dataclass(frozen=True)
class ConnectionChoice:
    connection_id: str
    label: str
    default_model: str | None = None
    provider: str | None = None
    base_url: str | None = None


@dataclass
class RouteRow:
    route: WorkflowStepRoute
    connection_combo: QComboBox | None
    model_edit: QLineEdit

    @property
    def step_id(self) -> WorkflowStepId:
        return self.route.step_id

    @property
    def step_label(self) -> str:
        return self.route.step_label

    @property
    def step_config(self) -> dict[str, bool | int | float | str | None]:
        return self.route.step_config

    @step_config.setter
    def step_config(self, value: dict[str, bool | int | float | str | None]) -> None:
        self.route = self.route.model_copy(update={"step_config": value})


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


class StepAdvancedConfigDialog(QDialog):
    _TIP_TEXTS = {
        WorkflowStepId.EXTRACTOR: "Extraction settings control how aggressively terms are discovered.",
        WorkflowStepId.TRANSLATOR: "Translator settings tune chunk sizing and request budget.",
        WorkflowStepId.OCR: "OCR settings control image compression and artifact cleanup.",
        WorkflowStepId.TRANSLATOR_BATCH: "Batch settings configure optional async translation jobs.",
    }
    _SIMPLE_STEP_SPECS: dict[WorkflowStepId, tuple[_SpinFieldSpec | _CheckFieldSpec, ...]] = {
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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
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
        specs: tuple[_SpinFieldSpec | _CheckFieldSpec, ...],
    ) -> Callable[[], WorkflowStepRoute]:
        readers: dict[str, Callable[[], bool | int | float | str | None]] = {}
        for spec in specs:
            if isinstance(spec, _SpinFieldSpec):
                widget = self._spin(spec.minimum, spec.maximum, int(config.get(spec.key, spec.default) or spec.default))
                readers[spec.key] = lambda w=widget: int(w.value())
            else:
                widget = QCheckBox()
                widget.setChecked(bool(config.get(spec.key, spec.default)))
                readers[spec.key] = lambda w=widget: bool(w.isChecked())
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


ADVANCED_STEP_IDS = frozenset(
    {
        WorkflowStepId.EXTRACTOR,
        WorkflowStepId.TRANSLATOR,
        WorkflowStepId.OCR,
        WorkflowStepId.TRANSLATOR_BATCH,
    }
)


class WorkflowRoutesEditor(QWidget):
    _STEP_COLUMN_WIDTH = 180
    _ADVANCED_COLUMN_WIDTH = 110
    _CONNECTION_COLUMN_WIDTH = 300
    _MODEL_COLUMN_WIDTH = 340

    def __init__(
        self,
        routes: list[WorkflowStepRoute],
        connection_choices: list[ConnectionChoice],
        *,
        advanced_step_ids: frozenset[WorkflowStepId],
        hint_text: str,
        max_visible_rows: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._connection_choices = connection_choices
        self._connection_choice_by_id = {choice.connection_id: choice for choice in connection_choices}
        self._advanced_step_ids = advanced_step_ids
        self._max_visible_rows = max_visible_rows
        self.rows: list[RouteRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._hint_label = create_tip_label(hint_text)
        layout.addWidget(self._hint_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Step"), self.tr("Connection"), self.tr("Model"), self.tr("Advanced")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setStyleSheet(
            "QTableWidget, QTableView { background: palette(base); selection-background-color: transparent; selection-color: palette(text); }"
            " QTableWidget::item, QTableView::item { background-color: transparent; color: palette(text); }"
            " QTableWidget::item:selected, QTableWidget::item:selected:active, QTableWidget::item:selected:!active,"
            " QTableView::item:selected, QTableView::item:selected:active, QTableView::item:selected:!active { background-color: transparent; color: palette(text); }"
            " QTableWidget::item:hover, QTableView::item:hover { background-color: transparent; color: palette(text); }"
            " QTableWidget QLineEdit, QTableWidget QComboBox, QTableWidget QPushButton { selection-background-color: transparent; }"
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, self._STEP_COLUMN_WIDTH)
        self.table.setColumnWidth(1, self._CONNECTION_COLUMN_WIDTH)
        self.table.setColumnWidth(2, self._MODEL_COLUMN_WIDTH)
        self.table.setColumnWidth(3, self._ADVANCED_COLUMN_WIDTH)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.table)
        self.set_routes(routes)

    def set_routes(self, routes: list[WorkflowStepRoute]) -> None:
        self.table.setRowCount(0)
        self.rows.clear()
        for route in routes:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            self.table.setItem(row_index, 0, self._step_item(route.step_label))
            self._set_advanced_widget(row_index, route)

            if route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                self.table.setItem(row_index, 1, self._item(route.connection_label or self.tr("Direct batch config")))
                model_edit = self._build_model_edit(route.model or "", readonly=True)
                self.table.setCellWidget(row_index, 2, self._cell_widget(model_edit))
                self.rows.append(RouteRow(route=route, connection_combo=None, model_edit=model_edit))
                continue

            combo = self._build_connection_combo(route.connection_id)
            model_edit = self._build_model_edit(route.model or "")
            combo.currentIndexChanged.connect(lambda _i, c=combo, e=model_edit: self._sync_model_from_connection(c, e))
            self.table.setCellWidget(row_index, 1, self._cell_widget(combo))
            self.table.setCellWidget(row_index, 2, self._cell_widget(model_edit))
            self.rows.append(RouteRow(route=route, connection_combo=combo, model_edit=model_edit))

        self._update_table_geometry()

    def set_connection_choices(self, connection_choices: list[ConnectionChoice]) -> None:
        self._connection_choices = connection_choices
        self._connection_choice_by_id = {choice.connection_id: choice for choice in connection_choices}

    def build_routes(self) -> list[WorkflowStepRoute]:
        routes: list[WorkflowStepRoute] = []
        for row in self.rows:
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
                        "step_config": dict(row.route.step_config),
                    }
                )
            )
        return routes

    def has_missing_required_fields(self) -> bool:
        for row in self.rows:
            if row.route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                continue
            if row.connection_combo is None or not str(row.connection_combo.currentData() or "").strip():
                return True
            if not row.model_edit.text().strip():
                return True
        return False

    def _build_connection_combo(self, connection_id: str | None) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(self._CONNECTION_COLUMN_WIDTH - 24)
        combo.setMaximumWidth(self._CONNECTION_COLUMN_WIDTH - 24)
        combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setStyleSheet("QComboBox { font-size: 13px; padding: 4px 8px; }")
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
        model_edit.setMinimumWidth(self._MODEL_COLUMN_WIDTH - 24)
        model_edit.setMaximumWidth(self._MODEL_COLUMN_WIDTH - 24)
        model_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        model_edit.setStyleSheet("QLineEdit { font-size: 13px; padding: 4px 6px; }")
        return model_edit

    def _cell_widget(self, widget: QWidget) -> QWidget:
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(0)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
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

    def _step_item(self, step_label: str) -> QTableWidgetItem:
        item = self._item(step_label)
        item.setToolTip(self.tr("Connection and model settings for this workflow step."))
        return item

    def _set_advanced_widget(self, row: int, route: WorkflowStepRoute) -> None:
        if route.step_id in self._advanced_step_ids:
            button = QPushButton(self.tr("Advanced"))
            button.setFixedWidth(self._ADVANCED_COLUMN_WIDTH - 16)
            button.clicked.connect(lambda _checked=False, r=row: self._open_step_advanced_dialog(r))
            self.table.setCellWidget(row, 3, self._cell_widget(button))
            return
        item = self._item("—")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(self.tr("This step has no additional settings beyond connection and model."))
        self.table.setItem(row, 3, item)

    def _open_step_advanced_dialog(self, row: int) -> None:
        if row < 0 or row >= len(self.rows):
            return
        route_row = self.rows[row]
        if route_row.route.step_id not in self._advanced_step_ids:
            return
        dialog = StepAdvancedConfigDialog(route_row.route, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated_route = dialog.route()
        route_row.route = updated_route
        if updated_route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            route_row.model_edit.setText(updated_route.model or "")

    def _update_table_geometry(self) -> None:
        self.table.resizeRowsToContents()
        header_height = self.table.horizontalHeader().height()
        frame_height = self.table.frameWidth() * 2
        row_heights = [self.table.rowHeight(index) for index in range(self.table.rowCount())]
        visible_rows = (
            len(row_heights) if self._max_visible_rows is None else min(len(row_heights), self._max_visible_rows)
        )
        visible_height = sum(row_heights[:visible_rows])
        self.table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if self._max_visible_rows is None or len(row_heights) <= self._max_visible_rows
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table.setFixedHeight(header_height + visible_height + frame_height + 4)
        total_width = (
            self.table.verticalHeader().width()
            + self.table.columnWidth(0)
            + self.table.columnWidth(1)
            + self.table.columnWidth(2)
            + self.table.columnWidth(3)
            + self.table.frameWidth() * 2
            + 4
        )
        self.table.setMinimumWidth(total_width)
        editor_height = (
            self.layout().contentsMargins().top()
            + self._hint_label.sizeHint().height()
            + self.layout().spacing()
            + self.table.height()
            + self.layout().contentsMargins().bottom()
        )
        self.setMinimumHeight(editor_height)
        self.updateGeometry()

    def _item(self, text: str) -> QTableWidgetItem:
        return QTableWidgetItem(text)


class WorkflowProfileEditorDialog(QDialog):
    _ADVANCED_STEP_IDS = ADVANCED_STEP_IDS

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
        self.setWindowTitle(self.tr("Workflow Profile"))
        self.setMinimumWidth(980)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = create_tip_label(
            self.tr(
                "A workflow profile is a user-facing wrapper over the existing step-based config. Edit connection and model choices here."
            )
        )
        layout.addWidget(header)

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
        self.general_section.set_expanded(False)
        self.general_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.general_section)

        self.routes_section = CollapsibleSection(self.tr("Workflow Routing"))
        self.routes_editor = WorkflowRoutesEditor(
            self._original_profile.routes,
            self._connection_choices,
            advanced_step_ids=self._ADVANCED_STEP_IDS,
            hint_text=self.tr("Use the Advanced column to edit step-specific settings."),
            parent=self,
        )
        self.routes_table = self.routes_editor.table
        self._rows = self.routes_editor.rows
        self.routes_section.set_content(self.routes_editor)
        self.routes_section.set_expanded(True)
        self.routes_section.refresh_content_height()
        self.routes_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.routes_section)

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        footer.accepted.connect(self._accept_if_valid)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)
        self.general_section.toggled.connect(self._schedule_resize)
        self.routes_section.toggled.connect(self._schedule_resize)
        self._schedule_resize()

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
        if self.routes_editor.has_missing_required_fields():
            QMessageBox.warning(
                self,
                self.tr("Missing Connection"),
                self.tr("Every workflow step must use a connection and model."),
            )
            return
        self.accept()

    def _schedule_resize(self, *_args: object) -> None:
        self.layout().activate()
        self.adjustSize()
        target_width = max(980, self.routes_editor.table.minimumWidth() + 44)
        target_height = min(max(self.sizeHint().height(), 260), 700)
        self.setMinimumWidth(target_width)
        self.setFixedSize(target_width, target_height)
