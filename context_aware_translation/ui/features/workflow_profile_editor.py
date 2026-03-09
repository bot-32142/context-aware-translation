from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
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
from context_aware_translation.application.contracts.common import PresetCode
from context_aware_translation.ui.constants import LANGUAGES
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets.collapsible_section import CollapsibleSection


@dataclass(frozen=True)
class ConnectionChoice:
    connection_id: str
    label: str
    default_model: str | None = None


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

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(self.tr("Fast"), PresetCode.FAST.value)
        self.preset_combo.addItem(self.tr("Balanced"), PresetCode.BALANCED.value)
        self.preset_combo.addItem(self.tr("Best quality"), PresetCode.BEST.value)
        preset_index = self.preset_combo.findData(self._original_profile.preset.value)
        self.preset_combo.setCurrentIndex(max(preset_index, 0))

        basics_layout.addRow(self.tr("Profile name"), self.name_edit)
        basics_layout.addRow(self.tr("Target language"), self.target_language_combo)
        basics_layout.addRow(self.tr("Preset"), self.preset_combo)
        self.general_section.set_content(general_widget)
        self.general_section.set_expanded(True)
        scroll_layout.addWidget(self.general_section)

        self.routes_section = CollapsibleSection(self.tr("Workflow Routing"))
        routes_widget = QWidget()
        routes_layout = QVBoxLayout(routes_widget)
        self.routes_table = QTableWidget(0, 3)
        self.routes_table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
        self.routes_table.verticalHeader().setVisible(False)
        self.routes_table.setAlternatingRowColors(True)
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
            preset=PresetCode(str(self.preset_combo.currentData() or PresetCode.BALANCED.value)),
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

        self.routes_table.resizeColumnsToContents()

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
