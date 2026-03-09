from __future__ import annotations

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


class StepAdvancedConfigDialog(QDialog):
    def __init__(self, route: WorkflowStepRoute, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._route = route
        self._empty = False
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
        if self._route.step_id is WorkflowStepId.EXTRACTOR:
            self.max_gleaning_spin = QSpinBox()
            self.max_gleaning_spin.setRange(0, 10)
            self.max_gleaning_spin.setValue(int(config.get("max_gleaning", 3) or 3))
            self.max_term_name_spin = QSpinBox()
            self.max_term_name_spin.setRange(10, 500)
            self.max_term_name_spin.setValue(int(config.get("max_term_name_length", 200) or 200))
            self._form_layout.addRow(self.tr("Max gleaning"), self.max_gleaning_spin)
            self._form_layout.addRow(self.tr("Max term name length"), self.max_term_name_spin)
        elif self._route.step_id is WorkflowStepId.TRANSLATOR:
            self.max_tokens_spin = QSpinBox()
            self.max_tokens_spin.setRange(100, 100000)
            self.max_tokens_spin.setValue(int(config.get("max_tokens_per_llm_call", 4000) or 4000))
            self.chunk_size_spin = QSpinBox()
            self.chunk_size_spin.setRange(100, 5000)
            self.chunk_size_spin.setValue(int(config.get("chunk_size", 1000) or 1000))
            self._form_layout.addRow(self.tr("Max tokens per call"), self.max_tokens_spin)
            self._form_layout.addRow(self.tr("Chunk size"), self.chunk_size_spin)
        elif self._route.step_id is WorkflowStepId.OCR:
            self.ocr_dpi_spin = QSpinBox()
            self.ocr_dpi_spin.setRange(72, 600)
            self.ocr_dpi_spin.setValue(int(config.get("ocr_dpi", 150) or 150))
            self.strip_artifacts_check = QCheckBox()
            self.strip_artifacts_check.setChecked(bool(config.get("strip_llm_artifacts", True)))
            self._form_layout.addRow(self.tr("OCR DPI"), self.ocr_dpi_spin)
            self._form_layout.addRow(self.tr("Strip artifacts"), self.strip_artifacts_check)
        elif self._route.step_id is WorkflowStepId.IMAGE_REEMBEDDING:
            self.backend_combo = QComboBox()
            self.backend_combo.addItem("Gemini", ImageBackend.GEMINI.value)
            self.backend_combo.addItem("OpenAI", ImageBackend.OPENAI.value)
            self.backend_combo.addItem("Qwen", ImageBackend.QWEN.value)
            backend_value = str(config.get("backend") or ImageBackend.GEMINI.value)
            for i in range(self.backend_combo.count()):
                if str(self.backend_combo.itemData(i)) == backend_value:
                    self.backend_combo.setCurrentIndex(i)
                    break
            self._form_layout.addRow(self.tr("Backend"), self.backend_combo)
        elif self._route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            self.batch_provider_combo = QComboBox()
            self.batch_provider_combo.addItem(self.tr("Disabled"), "")
            self.batch_provider_combo.addItem(self.tr("Gemini AI Studio"), "gemini_ai_studio")
            provider_value = str(config.get("provider") or "")
            for i in range(self.batch_provider_combo.count()):
                if str(self.batch_provider_combo.itemData(i) or "") == provider_value:
                    self.batch_provider_combo.setCurrentIndex(i)
                    break

            self.batch_api_key_edit = QLineEdit(str(config.get("api_key") or ""))
            self.batch_model_edit = QLineEdit(self._route.model or "")
            self.batch_size_spin = QSpinBox()
            self.batch_size_spin.setRange(1, 5000)
            self.batch_size_spin.setValue(int(config.get("batch_size", 100) or 100))
            self.batch_thinking_combo = QComboBox()
            self.batch_thinking_combo.addItem(self.tr("Auto"), "auto")
            self.batch_thinking_combo.addItem(self.tr("Off"), "off")
            self.batch_thinking_combo.addItem(self.tr("Low"), "low")
            self.batch_thinking_combo.addItem(self.tr("Medium"), "medium")
            self.batch_thinking_combo.addItem(self.tr("High"), "high")
            thinking_value = str(config.get("thinking_mode") or "auto")
            for i in range(self.batch_thinking_combo.count()):
                if str(self.batch_thinking_combo.itemData(i) or "") == thinking_value:
                    self.batch_thinking_combo.setCurrentIndex(i)
                    break

            self._form_layout.addRow(self.tr("Provider"), self.batch_provider_combo)
            self._form_layout.addRow(self.tr("API key"), self.batch_api_key_edit)
            self._form_layout.addRow(self.tr("Model"), self.batch_model_edit)
            self._form_layout.addRow(self.tr("Batch size"), self.batch_size_spin)
            self._form_layout.addRow(self.tr("Thinking mode"), self.batch_thinking_combo)
        else:
            self._empty = True
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
        if self._empty:
            return self._route
        if self._route.step_id is WorkflowStepId.EXTRACTOR:
            return self._route.model_copy(
                update={
                    "step_config": {
                        "max_gleaning": int(self.max_gleaning_spin.value()),
                        "max_term_name_length": int(self.max_term_name_spin.value()),
                    }
                }
            )
        if self._route.step_id is WorkflowStepId.TRANSLATOR:
            return self._route.model_copy(
                update={
                    "step_config": {
                        "max_tokens_per_llm_call": int(self.max_tokens_spin.value()),
                        "chunk_size": int(self.chunk_size_spin.value()),
                    }
                }
            )
        if self._route.step_id is WorkflowStepId.OCR:
            return self._route.model_copy(
                update={
                    "step_config": {
                        "ocr_dpi": int(self.ocr_dpi_spin.value()),
                        "strip_llm_artifacts": bool(self.strip_artifacts_check.isChecked()),
                    }
                }
            )
        if self._route.step_id is WorkflowStepId.IMAGE_REEMBEDDING:
            return self._route.model_copy(
                update={
                    "step_config": {
                        "backend": str(self.backend_combo.currentData() or ImageBackend.GEMINI.value),
                    }
                }
            )
        if self._route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            provider = str(self.batch_provider_combo.currentData() or "")
            if not provider:
                return self._route.model_copy(update={"model": None, "step_config": {}})
            return self._route.model_copy(
                update={
                    "model": self.batch_model_edit.text().strip() or None,
                    "step_config": {
                        "provider": provider,
                        "api_key": self.batch_api_key_edit.text().strip(),
                        "batch_size": int(self.batch_size_spin.value()),
                        "thinking_mode": str(self.batch_thinking_combo.currentData() or "auto"),
                    },
                }
            )
        return self._route

    def _tip_text(self) -> str:
        if self._route.step_id is WorkflowStepId.EXTRACTOR:
            return self.tr("Extraction settings control how aggressively terms are discovered.")
        if self._route.step_id is WorkflowStepId.TRANSLATOR:
            return self.tr("Translator settings tune chunk sizing and request budget.")
        if self._route.step_id is WorkflowStepId.OCR:
            return self.tr("OCR settings control image compression and artifact cleanup.")
        if self._route.step_id is WorkflowStepId.IMAGE_REEMBEDDING:
            return self.tr("Image reembedding settings choose the image-edit backend for this workflow step.")
        if self._route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            return self.tr("Batch settings configure optional async translation jobs.")
        return self.tr("Edit advanced settings for this workflow step.")


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
        self._row_widgets: list[tuple[WorkflowStepRoute, QComboBox | None, QLineEdit]] = []
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
            preset=self._original_profile.preset,
            routes=self._build_routes(),
            is_default=self._original_profile.is_default,
        )

    def _populate_routes(self) -> None:
        self.routes_table.setRowCount(0)
        self._row_widgets.clear()
        for route in self._original_profile.routes:
            row = self.routes_table.rowCount()
            self.routes_table.insertRow(row)
            self.routes_table.setItem(row, 0, self._item(route.step_label))

            if route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                combo: QComboBox | None = None
                self.routes_table.setItem(row, 1, self._item(route.connection_label or self.tr("Direct batch config")))
                model_edit = QLineEdit(route.model or "")
                model_edit.setReadOnly(True)
                self.routes_table.setCellWidget(row, 2, model_edit)
                self._row_widgets.append((route, combo, model_edit))
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
            self._row_widgets.append((route, combo, model_edit))

    def _build_routes(self) -> list[WorkflowStepRoute]:
        routes: list[WorkflowStepRoute] = []
        for original_route, combo, model_edit in self._row_widgets:
            if original_route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                routes.append(original_route)
                continue
            connection_id = combo.currentData() if combo is not None else None
            connection_id_str = str(connection_id) if isinstance(connection_id, str) and connection_id else None
            connection_label = None
            if combo is not None and connection_id_str is not None:
                connection_label = combo.currentText().strip() or None
            routes.append(
                original_route.model_copy(
                    update={
                        "connection_id": connection_id_str,
                        "connection_label": connection_label,
                        "model": model_edit.text().strip() or None,
                    }
                )
            )
        return routes

    def _accept_if_valid(self) -> None:
        target_language = self.target_language_combo.currentText().strip()
        if not target_language:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Target language is required."))
            return
        for route, combo, model_edit in self._row_widgets:
            if route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
                continue
            if combo is None or not str(combo.currentData() or "").strip():
                QMessageBox.warning(
                    self,
                    self.tr("Missing Connection"),
                    self.tr("Every workflow step must use a connection."),
                )
                return
            if not model_edit.text().strip():
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
        if row < 0 or row >= len(self._row_widgets):
            return
        route, combo, model_edit = self._row_widgets[row]
        dialog = StepAdvancedConfigDialog(route, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated_route = dialog.route()
        self._row_widgets[row] = (updated_route, combo, model_edit)
        if updated_route.step_id is WorkflowStepId.TRANSLATOR_BATCH:
            model_edit.setText(updated_route.model or "")
