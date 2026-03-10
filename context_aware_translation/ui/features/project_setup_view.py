from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import ApplicationEventSubscriber, SetupInvalidatedEvent
from context_aware_translation.application.services.project_setup import ProjectSetupService
from context_aware_translation.llm.image_generator import ImageBackend
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.features.workflow_profile_editor import StepAdvancedConfigDialog
from context_aware_translation.ui.utils import create_tip_label


@dataclass
class _CustomRouteRow:
    step_id: WorkflowStepId
    step_label: str
    connection_combo: QComboBox
    model_edit: QLineEdit
    step_config: dict[str, bool | int | float | str | None]


class ProjectSetupView(QWidget):
    """Project-scoped setup surface backed by application contracts."""

    open_app_setup_requested = Signal()
    save_completed = Signal(str)
    _ADVANCED_STEP_IDS = frozenset(
        {
            WorkflowStepId.EXTRACTOR,
            WorkflowStepId.TRANSLATOR,
            WorkflowStepId.OCR,
            WorkflowStepId.TRANSLATOR_BATCH,
        }
    )

    def __init__(
        self,
        project_id: str,
        service: ProjectSetupService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self._service = service
        self._state: ProjectSetupState | None = None
        self._draft_project_profile: WorkflowProfileDetail | None = None
        self._custom_base_profile_id: str | None = None
        self._last_shared_profile_id: str | None = None
        self._custom_rows: list[_CustomRouteRow] = []
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.summary_label = create_tip_label("")
        layout.addWidget(self.summary_label)

        self.blocker_label = create_tip_label("")
        self.blocker_label.setStyleSheet("QLabel { color: #b42318; }")
        self.blocker_label.hide()
        layout.addWidget(self.blocker_label)

        selector_group = QGroupBox(self.tr("Workflow profile"))
        selector_layout = QVBoxLayout(selector_group)
        row = QHBoxLayout()
        self.shared_profile_combo = QComboBox()
        self.shared_profile_combo.currentIndexChanged.connect(self._on_shared_profile_changed)
        row.addWidget(self.shared_profile_combo, 1)
        selector_layout.addLayout(row)
        layout.addWidget(selector_group)

        self.custom_profile_group = QGroupBox(self.tr("Custom profile"))
        custom_layout = QVBoxLayout(self.custom_profile_group)
        self.custom_profile_label = create_tip_label("")
        custom_layout.addWidget(self.custom_profile_label)
        custom_layout.addWidget(
            create_tip_label(self.tr("Steps marked [advanced] can be double-clicked to edit advanced step settings."))
        )
        self.routes_table = QTableWidget(0, 3)
        self.routes_table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
        self.routes_table.verticalHeader().setVisible(False)
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.routes_table.setWordWrap(False)
        self.routes_table.verticalHeader().setDefaultSectionSize(34)
        self.routes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.routes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.routes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.routes_table.setColumnWidth(1, 360)
        self.routes_table.setColumnWidth(2, 320)
        self.routes_table.cellDoubleClicked.connect(self._on_custom_step_double_clicked)
        custom_layout.addWidget(self.routes_table)
        layout.addWidget(self.custom_profile_group)

        actions_layout = QHBoxLayout()
        self.open_app_setup_button = QPushButton(self.tr("Open App Setup"))
        self.open_app_setup_button.clicked.connect(self.open_app_setup_requested.emit)
        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.clicked.connect(self._save)
        actions_layout.addWidget(self.open_app_setup_button)
        actions_layout.addStretch()
        actions_layout.addWidget(self.save_button)
        layout.addLayout(actions_layout)
        layout.addStretch()

    def refresh(self) -> None:
        self._apply_state(self._service.get_state(self.project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.custom_profile_group.setTitle(self.tr("Custom profile"))
        self.routes_table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
        self.open_app_setup_button.setText(self.tr("Open App Setup"))
        self.save_button.setText(self.tr("Save"))
        self.title_label.setText(self._title_text())
        if self._state is not None:
            self.summary_label.setText(self._summary_text())
            self._render_effective_profile()

    def _apply_state(self, state: ProjectSetupState) -> None:
        self._state = state
        self._draft_project_profile = state.project_profile
        self._custom_base_profile_id = state.selected_shared_profile_id
        self.title_label.setText(self._title_text())
        self.blocker_label.setVisible(state.blocker is not None)
        self.blocker_label.setText(state.blocker.message if state.blocker is not None else "")

        self.shared_profile_combo.blockSignals(True)
        self.shared_profile_combo.clear()
        for profile in state.shared_profiles:
            self.shared_profile_combo.addItem(profile.name, profile.profile_id)
        if state.shared_profiles or state.project_profile is not None:
            self.shared_profile_combo.addItem(self.tr("Custom profile"), "__custom__")
        if state.project_profile is not None:
            index = self.shared_profile_combo.findData("__custom__")
            if index >= 0:
                self.shared_profile_combo.setCurrentIndex(index)
        elif state.selected_shared_profile_id is not None:
            index = self.shared_profile_combo.findData(state.selected_shared_profile_id)
            if index >= 0:
                self.shared_profile_combo.setCurrentIndex(index)
                self._last_shared_profile_id = state.selected_shared_profile_id
        self.shared_profile_combo.blockSignals(False)

        self.open_app_setup_button.setVisible(state.blocker is not None)
        self.summary_label.setText(self._summary_text())
        self._render_effective_profile()
        self._show_message("", is_error=False)

    def _current_shared_profile_id(self) -> str | None:
        current = self.shared_profile_combo.currentData()
        return str(current) if isinstance(current, str) and current else None

    def _is_custom_selected(self) -> bool:
        return self._current_shared_profile_id() == "__custom__"

    def _current_shared_profile(self) -> WorkflowProfileDetail | None:
        if self._state is None:
            return None
        profile_id = self._current_shared_profile_id()
        if profile_id is None or profile_id == "__custom__":
            return None
        return next((profile for profile in self._state.shared_profiles if profile.profile_id == profile_id), None)

    def _effective_profile(self) -> WorkflowProfileDetail | None:
        if self._is_custom_selected():
            return self._draft_project_profile or (self._state.project_profile if self._state is not None else None)
        return self._current_shared_profile() or (self._state.selected_shared_profile if self._state is not None else None)

    def _render_effective_profile(self) -> None:
        profile = self._effective_profile()
        self.routes_table.setRowCount(0)
        self._custom_rows.clear()
        if profile is None:
            self.custom_profile_group.hide()
            return
        if not self._is_custom_selected():
            self.custom_profile_group.hide()
            return
        self.custom_profile_group.show()
        base_name = self._base_profile_name()
        self.custom_profile_label.setText(
            self.tr("Editing a project-specific profile based on %1.").replace("%1", base_name)
        )
        for route in profile.routes:
            row = self.routes_table.rowCount()
            self.routes_table.insertRow(row)
            step_item = self._step_item(route.step_label, route.step_id in self._ADVANCED_STEP_IDS)
            self.routes_table.setItem(row, 0, step_item)
            combo = QComboBox()
            combo.addItem(self.tr("Select connection"), "")
            for connection in self._state.available_connections if self._state is not None else []:
                combo.addItem(connection.display_name, connection.connection_id)
            combo.setMinimumWidth(340)
            combo.setStyleSheet("QComboBox { font-size: 13px; padding: 4px 8px; }")
            if route.connection_id:
                index = combo.findData(route.connection_id)
                if index >= 0:
                    combo.setCurrentIndex(index)
            model_edit = QLineEdit(route.model or "")
            model_edit.setMinimumWidth(300)
            model_edit.setStyleSheet("QLineEdit { font-size: 13px; padding: 4px 6px; }")
            combo.currentIndexChanged.connect(lambda _i, c=combo, e=model_edit: self._sync_model_from_connection(c, e))
            self.routes_table.setCellWidget(row, 1, combo)
            self.routes_table.setCellWidget(row, 2, model_edit)
            self._custom_rows.append(
                _CustomRouteRow(
                    step_id=route.step_id,
                    step_label=route.step_label,
                    connection_combo=combo,
                    model_edit=model_edit,
                    step_config=dict(route.step_config),
                )
            )

    def _save(self) -> None:
        shared_profile_id = self._current_shared_profile_id()
        if self._is_custom_selected():
            if self._draft_project_profile is None:
                self._show_message(self.tr("Select a shared workflow profile first."), is_error=True)
                return
            project_profile = self._build_custom_profile()
            base_profile_id = self._custom_base_profile_id
        else:
            project_profile = None
            base_profile_id = shared_profile_id
        if base_profile_id is None and project_profile is None:
            self._show_message(self.tr("Select a shared workflow profile before saving."), is_error=True)
            return
        try:
            state = self._service.save(
                SaveProjectSetupRequest(
                    project_id=self.project_id,
                    shared_profile_id=(base_profile_id if project_profile is not None else shared_profile_id),
                    project_profile=project_profile,
                )
            )
        except BlockedOperationError as exc:
            self._show_message(exc.payload.message, is_error=True)
            return
        except ApplicationError as exc:
            self._show_message(exc.payload.message, is_error=True)
            return

        self._apply_state(state)
        self._show_message(self.tr("Project setup saved."), is_error=False)
        self.save_completed.emit(self.project_id)

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.refresh()

    def _on_shared_profile_changed(self, _index: int) -> None:
        profile_id = self._current_shared_profile_id()
        if profile_id == "__custom__":
            self._ensure_custom_profile()
        elif profile_id:
            self._last_shared_profile_id = profile_id
            self._draft_project_profile = None
        self._render_effective_profile()

    def _show_message(self, text: str, *, is_error: bool) -> None:
        if not text:
            self.message_label.hide()
            self.message_label.clear()
            return
        color = "#b42318" if is_error else "#027a48"
        self.message_label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: 600; }}")
        self.message_label.setText(text)
        self.message_label.show()

    def _title_text(self) -> str:
        if self._state is None:
            return self.tr("Project Setup")
        return self.tr("Setup for %1").replace("%1", self._state.project.name)

    def _summary_text(self) -> str:
        if self._state is None:
            return ""
        if self._is_custom_selected():
            return self.tr("This project is using a project-specific workflow profile.")
        if self._current_shared_profile() is not None or self._state.selected_shared_profile is not None:
            return self.tr("This project is using a shared workflow profile.")
        return self.tr("Choose a shared workflow profile to continue.")

    def _tip_text(self) -> str:
        return self.tr(
            "Choose a shared workflow profile, or select Custom profile to edit connection and model choices for this project."
        )

    def _ensure_custom_profile(self) -> None:
        if self._draft_project_profile is not None:
            return
        if self._state is None:
            return
        if self._state.project_profile is not None:
            self._draft_project_profile = self._state.project_profile
            return
        base_profile = self._current_shared_profile()
        if base_profile is None:
            base_profile = next(
                (profile for profile in self._state.shared_profiles if profile.profile_id == self._last_shared_profile_id),
                (self._state.shared_profiles[0] if self._state.shared_profiles else None),
            )
        if base_profile is None:
            return
        self._custom_base_profile_id = base_profile.profile_id
        self._draft_project_profile = base_profile.model_copy(
            update={
                "profile_id": f"project:{self.project_id}",
                "name": f"{self._state.project.name} custom profile",
                "kind": WorkflowProfileKind.PROJECT_SPECIFIC,
                "is_default": False,
            }
        )

    def _base_profile_name(self) -> str:
        if self._state is None or self._custom_base_profile_id is None:
            return self.tr("the selected shared profile")
        return next(
            (profile.name for profile in self._state.shared_profiles if profile.profile_id == self._custom_base_profile_id),
            self.tr("the selected shared profile"),
        )

    def _sync_model_from_connection(self, combo: QComboBox, model_edit: QLineEdit) -> None:
        if self._state is None:
            return
        connection_id = combo.currentData()
        if not isinstance(connection_id, str) or not connection_id:
            return
        default_model = next(
            (connection.default_model for connection in self._state.available_connections if connection.connection_id == connection_id),
            None,
        )
        if default_model:
            model_edit.setText(default_model)

    def _build_custom_profile(self) -> WorkflowProfileDetail:
        assert self._draft_project_profile is not None
        routes = []
        for row in self._custom_rows:
            connection_id = row.connection_combo.currentData()
            connection_id_str = str(connection_id) if isinstance(connection_id, str) and connection_id else None
            connection_label = row.connection_combo.currentText().strip() or None
            step_config = dict(row.step_config)
            if row.step_id is WorkflowStepId.IMAGE_REEMBEDDING:
                inferred_backend = self._infer_image_backend(connection_id_str, row.model_edit.text().strip() or None)
                if inferred_backend is not None:
                    step_config["backend"] = inferred_backend
            routes.append(
                next(route for route in self._draft_project_profile.routes if route.step_id is row.step_id).model_copy(
                    update={
                        "connection_id": connection_id_str,
                        "connection_label": connection_label,
                        "model": row.model_edit.text().strip() or None,
                        "step_config": step_config,
                    }
                )
            )
        return self._draft_project_profile.model_copy(update={"routes": routes, "kind": WorkflowProfileKind.PROJECT_SPECIFIC})

    def _on_custom_step_double_clicked(self, row: int, column: int) -> None:
        if column != 0 or not self._is_custom_selected():
            return
        if row < 0 or row >= len(self._custom_rows) or self._draft_project_profile is None:
            return
        row_state = self._custom_rows[row]
        if row_state.step_id not in self._ADVANCED_STEP_IDS:
            return
        route = next(route for route in self._draft_project_profile.routes if route.step_id is row_state.step_id).model_copy(
            update={
                "connection_id": self._current_combo_connection_id(row_state.connection_combo),
                "connection_label": row_state.connection_combo.currentText().strip() or None,
                "model": row_state.model_edit.text().strip() or None,
                "step_config": dict(row_state.step_config),
            }
        )
        dialog = StepAdvancedConfigDialog(route, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.route()
        row_state.step_config = dict(updated.step_config)
        if updated.step_id is WorkflowStepId.TRANSLATOR_BATCH and updated.model is not None:
            row_state.model_edit.setText(updated.model)

    def _current_combo_connection_id(self, combo: QComboBox) -> str | None:
        current = combo.currentData()
        return str(current) if isinstance(current, str) and current else None

    def _step_item(self, step_label: str, is_advanced: bool) -> QTableWidgetItem:
        item = QTableWidgetItem(f"{step_label} [advanced]" if is_advanced else step_label)
        item.setToolTip(
            self.tr("Double-click to edit advanced settings.")
            if is_advanced
            else self.tr("This step has no additional settings beyond connection and model.")
        )
        return item

    def _infer_image_backend(self, connection_id: str | None, model: str | None) -> str | None:
        if self._state is None or not connection_id:
            return None
        connection = next(
            (connection for connection in self._state.available_connections if connection.connection_id == connection_id),
            None,
        )
        if connection is None:
            return None
        provider = connection.provider.value.lower()
        base_url = (connection.base_url or "").lower()
        model_name = (model or connection.default_model or "").lower()
        if provider == "gemini" or model_name.startswith("gemini") or "generativelanguage.googleapis.com" in base_url:
            return ImageBackend.GEMINI.value
        if model_name.startswith("qwen") or "dashscope" in base_url:
            return ImageBackend.QWEN.value
        return ImageBackend.OPENAI.value
