from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowProfileKind,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import ApplicationEventSubscriber, SetupInvalidatedEvent
from context_aware_translation.application.services.project_setup import ProjectSetupService
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.features.workflow_profile_editor import ConnectionChoice, WorkflowProfileEditorDialog
from context_aware_translation.ui.utils import create_tip_label


class ProjectSetupView(QWidget):
    """Project-scoped setup surface backed by application contracts."""

    open_app_setup_requested = Signal()
    save_completed = Signal(str)

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
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
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
        self.use_shared_button = QPushButton(self.tr("Use shared profile"))
        self.use_shared_button.clicked.connect(self._use_shared_profile)
        row.addWidget(self.use_shared_button)
        selector_layout.addLayout(row)
        layout.addWidget(selector_group)

        self.current_profile_group = QGroupBox(self.tr("Current profile"))
        current_layout = QVBoxLayout(self.current_profile_group)
        self.current_profile_label = create_tip_label("")
        current_layout.addWidget(self.current_profile_label)
        self.routes_table = QTableWidget(0, 3)
        self.routes_table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
        self.routes_table.verticalHeader().setVisible(False)
        self.routes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routes_table.verticalHeader().setDefaultSectionSize(34)
        self.routes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.routes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.routes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        current_layout.addWidget(self.routes_table)
        layout.addWidget(self.current_profile_group, 1)

        actions_layout = QHBoxLayout()
        self.customize_button = QPushButton(self.tr("Customize for this project"))
        self.customize_button.clicked.connect(self._customize_for_project)
        self.edit_project_button = QPushButton(self.tr("Edit project profile"))
        self.edit_project_button.clicked.connect(self._edit_project_profile)
        self.open_app_setup_button = QPushButton(self.tr("Open App Setup"))
        self.open_app_setup_button.clicked.connect(self.open_app_setup_requested.emit)
        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.clicked.connect(self._save)
        actions_layout.addWidget(self.customize_button)
        actions_layout.addWidget(self.edit_project_button)
        actions_layout.addWidget(self.open_app_setup_button)
        actions_layout.addStretch()
        actions_layout.addWidget(self.save_button)
        layout.addLayout(actions_layout)

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
        self.current_profile_group.setTitle(self.tr("Current profile"))
        self.routes_table.setHorizontalHeaderLabels([self.tr("Step"), self.tr("Connection"), self.tr("Model")])
        self.use_shared_button.setText(self.tr("Use shared profile"))
        self.customize_button.setText(self.tr("Customize for this project"))
        self.edit_project_button.setText(self.tr("Edit project profile"))
        self.open_app_setup_button.setText(self.tr("Open App Setup"))
        self.save_button.setText(self.tr("Save"))
        self.title_label.setText(self._title_text())
        if self._state is not None:
            self.summary_label.setText(self._summary_text())
            self._render_effective_profile()

    def _apply_state(self, state: ProjectSetupState) -> None:
        self._state = state
        self._draft_project_profile = state.project_profile
        self.title_label.setText(self._title_text())
        self.summary_label.setText(self._summary_text())
        self.blocker_label.setVisible(state.blocker is not None)
        self.blocker_label.setText(state.blocker.message if state.blocker is not None else "")

        self.shared_profile_combo.blockSignals(True)
        self.shared_profile_combo.clear()
        for profile in state.shared_profiles:
            self.shared_profile_combo.addItem(profile.name, profile.profile_id)
        if state.selected_shared_profile_id is not None:
            index = self.shared_profile_combo.findData(state.selected_shared_profile_id)
            if index >= 0:
                self.shared_profile_combo.setCurrentIndex(index)
        self.shared_profile_combo.blockSignals(False)

        self.use_shared_button.setEnabled(state.selected_shared_profile is not None)
        self.customize_button.setEnabled(state.selected_shared_profile is not None)
        self.edit_project_button.setEnabled(self._draft_project_profile is not None)
        self.open_app_setup_button.setVisible(state.blocker is not None)
        self._render_effective_profile()
        self._show_message("", is_error=False)

    def _current_shared_profile_id(self) -> str | None:
        current = self.shared_profile_combo.currentData()
        return str(current) if isinstance(current, str) and current else None

    def _current_shared_profile(self) -> WorkflowProfileDetail | None:
        if self._state is None:
            return None
        profile_id = self._current_shared_profile_id()
        if profile_id is None:
            return None
        return next((profile for profile in self._state.shared_profiles if profile.profile_id == profile_id), None)

    def _effective_profile(self) -> WorkflowProfileDetail | None:
        return self._draft_project_profile or (self._state.project_profile if self._state is not None else None) or (self._state.selected_shared_profile if self._state is not None else None)

    def _render_effective_profile(self) -> None:
        profile = self._effective_profile()
        self.routes_table.setRowCount(0)
        if profile is None:
            self.current_profile_label.setText(self.tr("No workflow profile selected yet."))
            return
        scope_label = self.tr("Project-specific profile") if profile.kind is WorkflowProfileKind.PROJECT_SPECIFIC else self.tr("Shared profile")
        self.current_profile_label.setText(
            self.tr("%1 | Target language: %2")
            .replace("%1", scope_label)
            .replace("%2", profile.target_language)
        )
        for route in profile.routes:
            row = self.routes_table.rowCount()
            self.routes_table.insertRow(row)
            self.routes_table.setItem(row, 0, QTableWidgetItem(route.step_label))
            self.routes_table.setItem(row, 1, QTableWidgetItem(route.connection_label or ""))
            self.routes_table.setItem(row, 2, QTableWidgetItem(route.model or ""))
    def _use_shared_profile(self) -> None:
        self._draft_project_profile = None
        self.edit_project_button.setEnabled(False)
        self._render_effective_profile()

    def _customize_for_project(self) -> None:
        shared_profile = self._current_shared_profile()
        if shared_profile is None:
            self._show_message(self.tr("Select a shared workflow profile first."), is_error=True)
            return
        project_profile = shared_profile.model_copy(
            update={
                "profile_id": f"project:{self.project_id}",
                "name": f"{self._state.project.name} project profile" if self._state is not None else shared_profile.name,
                "kind": WorkflowProfileKind.PROJECT_SPECIFIC,
                "is_default": False,
            }
        )
        dialog = WorkflowProfileEditorDialog(
            profile=project_profile,
            connection_choices=self._connection_choices(),
            allow_name_edit=False,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._draft_project_profile = dialog.profile().model_copy(update={"kind": WorkflowProfileKind.PROJECT_SPECIFIC})
        self.edit_project_button.setEnabled(True)
        self._render_effective_profile()

    def _edit_project_profile(self) -> None:
        profile = self._draft_project_profile or (self._state.project_profile if self._state is not None else None)
        if profile is None:
            self._show_message(self.tr("No project-specific profile is available to edit."), is_error=True)
            return
        dialog = WorkflowProfileEditorDialog(
            profile=profile,
            connection_choices=self._connection_choices(),
            allow_name_edit=False,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._draft_project_profile = dialog.profile().model_copy(update={"kind": WorkflowProfileKind.PROJECT_SPECIFIC})
        self._render_effective_profile()

    def _save(self) -> None:
        shared_profile_id = self._current_shared_profile_id()
        if shared_profile_id is None and self._draft_project_profile is None:
            self._show_message(self.tr("Select a shared workflow profile before saving."), is_error=True)
            return
        try:
            state = self._service.save(
                SaveProjectSetupRequest(
                    project_id=self.project_id,
                    shared_profile_id=shared_profile_id,
                    project_profile=self._draft_project_profile,
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
        if self._draft_project_profile is None:
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
        if self._draft_project_profile is not None or self._state.project_profile is not None:
            return self.tr("This project is using a project-specific workflow profile.")
        if self._state.selected_shared_profile is not None:
            return self.tr("This project is using a shared workflow profile.")
        return self.tr("Choose a shared workflow profile to continue.")

    def _tip_text(self) -> str:
        return self.tr(
            "Project Setup chooses a shared workflow profile or creates a project-specific profile. Target language lives inside the selected profile."
        )

    def _connection_choices(self) -> list[ConnectionChoice]:
        if self._state is None:
            return []
        return [
            ConnectionChoice(
                connection_id=connection.connection_id,
                label=connection.display_name,
                default_model=connection.default_model,
            )
            for connection in self._state.available_connections
        ]
