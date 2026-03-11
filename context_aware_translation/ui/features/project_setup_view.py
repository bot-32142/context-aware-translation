from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.app_setup import (
    ConnectionSummary,
    WorkflowProfileDetail,
    WorkflowProfileKind,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import ApplicationEventSubscriber, SetupInvalidatedEvent
from context_aware_translation.application.services.project_setup import ProjectSetupService
from context_aware_translation.ui.features.workflow_profile_editor import (
    ADVANCED_STEP_IDS,
    ConnectionChoice,
    WorkflowRoutesEditor,
)
from context_aware_translation.ui.tips import create_tip_label


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
        self._custom_base_profile_id: str | None = None
        self._last_shared_profile_id: str | None = None
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.blocker_label = create_tip_label("")
        self.blocker_label.setStyleSheet("QLabel { color: #b42318; }")
        self.blocker_label.hide()
        layout.addWidget(self.blocker_label)

        selector_group = QGroupBox(self.tr("Workflow profile"))
        selector_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        selector_layout = QVBoxLayout(selector_group)
        row = QHBoxLayout()
        self.shared_profile_combo = QComboBox()
        self.shared_profile_combo.setMinimumWidth(420)
        self.shared_profile_combo.setMaximumWidth(560)
        self.shared_profile_combo.currentIndexChanged.connect(self._on_shared_profile_changed)
        row.addWidget(self.shared_profile_combo)
        selector_layout.addLayout(row)
        layout.addWidget(selector_group, 0, Qt.AlignmentFlag.AlignTop)

        self.custom_profile_group = QGroupBox(self.tr("Custom profile"))
        self.custom_profile_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        custom_layout = QVBoxLayout(self.custom_profile_group)
        self.custom_profile_label = create_tip_label("")
        custom_layout.addWidget(self.custom_profile_label)
        self.routes_editor = WorkflowRoutesEditor(
            [],
            [],
            advanced_step_ids=ADVANCED_STEP_IDS,
            hint_text=self.tr("Use the Advanced column to edit step-specific settings."),
            max_visible_rows=6,
            parent=self,
        )
        self.routes_editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.routes_editor.hide()
        self.routes_table = self.routes_editor.table
        self._custom_rows = self.routes_editor.rows
        custom_layout.addWidget(self.routes_editor)
        layout.addWidget(self.custom_profile_group, 0, Qt.AlignmentFlag.AlignTop)

        actions_layout = QHBoxLayout()
        self.open_app_setup_button = QPushButton(self.tr("Open App Setup"))
        self.open_app_setup_button.clicked.connect(self.open_app_setup_requested.emit)
        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.clicked.connect(self._save)
        actions_layout.addWidget(self.open_app_setup_button)
        actions_layout.addWidget(self.save_button)
        actions_layout.addStretch()
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
        self.custom_profile_group.setTitle(self.tr("Custom profile"))
        self.open_app_setup_button.setText(self.tr("Open App Setup"))
        self.save_button.setText(self.tr("Save"))
        self.title_label.setText(self._title_text())
        if self._state is not None:
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
        return self._current_shared_profile() or (
            self._state.selected_shared_profile if self._state is not None else None
        )

    def _render_effective_profile(self) -> None:
        profile = self._effective_profile()
        if profile is None:
            self.custom_profile_group.hide()
            self.custom_profile_group.setMinimumHeight(0)
            return
        if not self._is_custom_selected():
            self.custom_profile_group.hide()
            self.custom_profile_group.setMinimumHeight(0)
            return
        self.custom_profile_group.show()
        base_name = self._base_profile_name()
        self.custom_profile_label.setText(
            self.tr("Editing a project-specific profile based on %1.").replace("%1", base_name)
        )
        self.routes_editor.show()
        self.routes_editor.set_connection_choices(self._connection_choices())
        self.routes_editor.set_routes(profile.routes)
        self.routes_editor.adjustSize()
        self.custom_profile_group.adjustSize()
        self.custom_profile_group.setMinimumHeight(self.custom_profile_group.sizeHint().height())

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
                (
                    profile
                    for profile in self._state.shared_profiles
                    if profile.profile_id == self._last_shared_profile_id
                ),
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
            (
                profile.name
                for profile in self._state.shared_profiles
                if profile.profile_id == self._custom_base_profile_id
            ),
            self.tr("the selected shared profile"),
        )

    def _build_custom_profile(self) -> WorkflowProfileDetail:
        assert self._draft_project_profile is not None
        routes = self.routes_editor.build_routes()
        return self._draft_project_profile.model_copy(
            update={"routes": routes, "kind": WorkflowProfileKind.PROJECT_SPECIFIC}
        )

    def _connection_choices(self) -> list[ConnectionChoice]:
        if self._state is None:
            return []
        return [self._connection_choice_from_summary(connection) for connection in self._state.available_connections]

    def _connection_choice_from_summary(self, connection: ConnectionSummary) -> ConnectionChoice:
        return ConnectionChoice(
            connection_id=connection.connection_id,
            label=connection.display_name,
            default_model=connection.default_model,
            provider=connection.provider.value,
            base_url=connection.base_url,
        )
