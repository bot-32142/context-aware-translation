from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QGroupBox, QSizePolicy, QVBoxLayout, QWidget

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.app_setup import (
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
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.viewmodels.project_settings_pane import ProjectSettingsPaneViewModel

_CUSTOM_PROFILE_ID = "__custom__"


class ProjectSettingsPane(QWidget):
    """Hybrid project-settings body with QML chrome and hosted route editor."""

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
        self._selected_profile_id: str | None = None
        self._profile_option_values: list[str] = []
        self._draft_project_profile: WorkflowProfileDetail | None = None
        self._custom_base_profile_id: str | None = None
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self.viewmodel = ProjectSettingsPaneViewModel(self)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chrome_host = QmlChromeHost(
            "dialogs/project_settings/ProjectSettingsPane.qml",
            context_objects={"projectSettingsPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)

        self.routes_group = QGroupBox(self.tr("Step routes"), self)
        self.routes_group.setContentsMargins(18, 16, 18, 18)
        self.routes_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        group_layout = QVBoxLayout(self.routes_group)
        group_layout.setContentsMargins(18, 16, 18, 18)
        group_layout.setSpacing(0)
        self.routes_editor = WorkflowRoutesEditor(
            [],
            [],
            advanced_step_ids=ADVANCED_STEP_IDS,
            hint_text=self.tr("Use the Advanced column to edit step-specific settings."),
            max_visible_rows=6,
            parent=self.routes_group,
        )
        self.routes_editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.routes_editor.hide()
        self.routes_table = self.routes_editor.table
        self._custom_rows = self.routes_editor.rows
        group_layout.addWidget(self.routes_editor)
        layout.addWidget(self.routes_group, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        self.routes_group.hide()

        self._connect_qml_signals()

    def refresh(self) -> None:
        self._apply_state(self._service.get_state(self.project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.routes_group.setTitle(self.tr("Step routes"))
        self.viewmodel.retranslate()
        self._sync_viewmodel()

    def _apply_state(self, state: ProjectSetupState) -> None:
        self._state = state
        self._draft_project_profile = state.project_profile
        self._custom_base_profile_id = state.selected_shared_profile_id
        self._selected_profile_id = self._initial_selected_profile_id(state)
        self._sync_routes_editor()
        self._sync_viewmodel()
        self.viewmodel.clear_message()

    def _initial_selected_profile_id(self, state: ProjectSetupState) -> str | None:
        if state.project_profile is not None:
            return _CUSTOM_PROFILE_ID
        if state.selected_shared_profile_id is not None:
            return state.selected_shared_profile_id
        if state.shared_profiles:
            return state.shared_profiles[0].profile_id
        if state.project_profile is not None:
            return _CUSTOM_PROFILE_ID
        return None

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.profileIndexRequested.connect(self._on_profile_index_requested)
        root.saveRequested.connect(self._save)
        root.openAppSetupRequested.connect(self.open_app_setup_requested.emit)

    def _on_profile_index_requested(self, index: int) -> None:
        if index < 0 or index >= len(self._profile_option_values):
            return
        profile_id = self._profile_option_values[index]
        if profile_id == _CUSTOM_PROFILE_ID:
            self._selected_profile_id = _CUSTOM_PROFILE_ID
            self._ensure_custom_profile()
        else:
            self._selected_profile_id = profile_id
            self._custom_base_profile_id = profile_id
            self._draft_project_profile = None
        self._sync_routes_editor()
        self._sync_viewmodel()
        self.viewmodel.clear_message()

    def _sync_viewmodel(self) -> None:
        state = self._state
        if state is None:
            self.viewmodel.apply_state(
                project_name="",
                blocker_text="",
                profile_options=[],
                custom_profile_text="",
                show_custom_profile=False,
                show_open_app_setup=False,
                can_save=False,
            )
            return

        options: list[dict[str, object]] = []
        option_values: list[str] = []
        shared_detail = self.tr("Shared workflow profile")
        for profile in state.shared_profiles:
            options.append(
                {
                    "label": profile.name,
                    "detail": shared_detail,
                    "selected": profile.profile_id == self._selected_profile_id,
                }
            )
            option_values.append(profile.profile_id)
        if state.shared_profiles or state.project_profile is not None:
            options.append(
                {
                    "label": self.tr("Custom profile"),
                    "detail": self.tr("Project-specific overrides"),
                    "selected": self._selected_profile_id == _CUSTOM_PROFILE_ID,
                }
            )
            option_values.append(_CUSTOM_PROFILE_ID)
        self._profile_option_values = option_values

        can_save = False
        if self._is_custom_selected():
            can_save = self._draft_project_profile is not None
        elif self._selected_profile_id is not None:
            can_save = True

        self.viewmodel.apply_state(
            project_name=state.project.name,
            blocker_text=state.blocker.message if state.blocker is not None else "",
            profile_options=options,
            custom_profile_text=self._custom_profile_text(),
            show_custom_profile=self._is_custom_selected() and self._effective_profile() is not None,
            show_open_app_setup=state.blocker is not None,
            can_save=can_save,
        )

    def _sync_routes_editor(self) -> None:
        profile = self._effective_profile()
        if profile is None or not self._is_custom_selected():
            self.routes_editor.hide()
            self.routes_group.hide()
            self.routes_group.setMinimumHeight(0)
            return
        self.routes_group.show()
        self.routes_editor.show()
        self.routes_editor.set_connection_choices(self._connection_choices())
        self.routes_editor.set_routes(profile.routes)
        self.routes_editor.adjustSize()
        self.routes_group.adjustSize()
        self.routes_group.setMinimumHeight(self.routes_group.sizeHint().height())

    def _save(self) -> None:
        shared_profile_id = self._selected_shared_profile_id()
        if self._is_custom_selected():
            if self._draft_project_profile is None:
                self.viewmodel.set_message(self.tr("Select a shared workflow profile first."), is_error=True)
                return
            project_profile = self._build_custom_profile()
            base_profile_id = self._custom_base_profile_id
        else:
            project_profile = None
            base_profile_id = shared_profile_id
        if base_profile_id is None and project_profile is None:
            self.viewmodel.set_message(self.tr("Select a shared workflow profile before saving."), is_error=True)
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
            self.viewmodel.set_message(exc.payload.message, is_error=True)
            return
        except ApplicationError as exc:
            self.viewmodel.set_message(exc.payload.message, is_error=True)
            return

        self._apply_state(state)
        self.viewmodel.set_message(self.tr("Project setup saved."), is_error=False)
        self.save_completed.emit(self.project_id)

    def _selected_shared_profile_id(self) -> str | None:
        profile_id = self._selected_profile_id
        if profile_id is None or profile_id == _CUSTOM_PROFILE_ID:
            return None
        return profile_id

    def _is_custom_selected(self) -> bool:
        return self._selected_profile_id == _CUSTOM_PROFILE_ID

    def _current_shared_profile(self) -> WorkflowProfileDetail | None:
        if self._state is None:
            return None
        profile_id = self._selected_shared_profile_id()
        if profile_id is None:
            return None
        return next((profile for profile in self._state.shared_profiles if profile.profile_id == profile_id), None)

    def _effective_profile(self) -> WorkflowProfileDetail | None:
        if self._is_custom_selected():
            return self._draft_project_profile or (self._state.project_profile if self._state is not None else None)
        return self._current_shared_profile()

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
                    if profile.profile_id == self._custom_base_profile_id
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

    def _custom_profile_text(self) -> str:
        if not self._is_custom_selected() or self._effective_profile() is None:
            return ""
        base_name = self._base_profile_name()
        return self.tr("Editing a project-specific profile based on %1.").replace("%1", base_name)

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
        return [
            ConnectionChoice(
                connection_id=connection.connection_id,
                label=connection.display_name,
                default_model=connection.default_model,
            )
            for connection in self._state.available_connections
        ]

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.refresh()
