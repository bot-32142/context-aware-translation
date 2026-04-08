from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QGroupBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import ApplicationEventSubscriber, SetupInvalidatedEvent
from context_aware_translation.application.services.project_setup import ProjectSetupService
from context_aware_translation.ui.chrome_sizing import sync_qml_host_height
from context_aware_translation.ui.features.workflow_profile_editor import (
    ConnectionChoice,
    WorkflowRoutesEditor,
    validate_workflow_routes,
)
from context_aware_translation.ui.i18n import translate_backend_text
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.viewmodels.project_settings_pane import ProjectSettingsPaneViewModel
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme

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
        auto_refresh: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self._service = service
        self._state: ProjectSetupState | None = None
        self._selected_profile_id: str | None = None
        self._profile_option_values: list[str] = []
        self._profile_option_signature: tuple[tuple[str, str], ...] = ()
        self._draft_project_profile: WorkflowProfileDetail | None = None
        self._custom_base_profile_id: str | None = None
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self.viewmodel = ProjectSettingsPaneViewModel(self)
        self._init_ui()
        if auto_refresh:
            self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.chrome_host = QmlChromeHost(
            "dialogs/project_settings/ProjectSettingsPane.qml",
            context_objects={"projectSettingsPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)

        self.profile_section = QWidget(self)
        profile_layout = QVBoxLayout(self.profile_section)
        profile_layout.setContentsMargins(18, 0, 18, 0)
        profile_layout.setSpacing(6)
        self.profile_label = QLabel(self.tr("Workflow profile"), self.profile_section)
        self.profile_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #2f251d;")
        profile_layout.addWidget(self.profile_label)
        self.profile_combo = QComboBox(self.profile_section)
        self.profile_combo.setObjectName("projectWorkflowProfileCombo")
        self.profile_combo.setMinimumWidth(420)
        self.profile_combo.setMaximumWidth(560)
        self.profile_combo.setMinimumContentsLength(24)
        self.profile_combo.setMinimumHeight(40)
        self.profile_combo.setMaxVisibleItems(10)
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        profile_popup = self.profile_combo.view()
        profile_popup.setMinimumWidth(self.profile_combo.minimumWidth())
        profile_popup.clicked.connect(self._on_profile_popup_clicked)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_index_requested)
        profile_layout.addWidget(self.profile_combo)
        self.profile_detail_label = QLabel(self.profile_section)
        self.profile_detail_label.setWordWrap(True)
        self.profile_detail_label.setStyleSheet("color: #6e6154; font-size: 12px;")
        profile_layout.addWidget(self.profile_detail_label)
        layout.addWidget(self.profile_section)

        self.routes_group = QGroupBox(self.tr("Step routes"), self)
        self.routes_group.setContentsMargins(18, 16, 18, 18)
        self.routes_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        group_layout = QVBoxLayout(self.routes_group)
        group_layout.setContentsMargins(18, 16, 18, 18)
        group_layout.setSpacing(0)
        self.routes_editor = WorkflowRoutesEditor(
            [],
            [],
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

        apply_hybrid_control_theme(self)
        self._connect_qml_signals()
        self._schedule_chrome_resize()

    def refresh(self) -> None:
        self._apply_state(self._service.get_state(self.project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.profile_label.setText(self.tr("Workflow profile"))
        self.routes_group.setTitle(self.tr("Step routes"))
        self.viewmodel.retranslate()
        self._sync_viewmodel()
        self._schedule_chrome_resize()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._schedule_chrome_resize()

    def _apply_state(self, state: ProjectSetupState) -> None:
        self._state = state
        self._draft_project_profile = state.project_profile
        self._custom_base_profile_id = state.selected_shared_profile_id
        self._selected_profile_id = self._initial_selected_profile_id(state)
        self._sync_routes_editor()
        self._sync_viewmodel()
        self.viewmodel.clear_message()
        self._schedule_chrome_resize()

    def _initial_selected_profile_id(self, state: ProjectSetupState) -> str | None:
        if state.project_profile is not None:
            return _CUSTOM_PROFILE_ID
        if state.selected_shared_profile_id is not None:
            return state.selected_shared_profile_id
        if state.shared_profiles:
            return state.shared_profiles[0].profile_id
        return None

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.saveRequested.connect(self._save)
        root.openAppSetupRequested.connect(self.open_app_setup_requested.emit)

    def _on_profile_index_requested(self, index: int) -> None:
        if index < 0 or index >= len(self._profile_option_values):
            return
        self._apply_profile_index(index)

    def _on_profile_popup_clicked(self, model_index) -> None:  # noqa: ANN001
        if model_index.isValid():
            self.profile_combo.setCurrentIndex(model_index.row())

    def _apply_profile_index(self, index: int) -> None:
        self._persist_custom_draft()
        profile_id = self._profile_option_values[index]
        if profile_id == _CUSTOM_PROFILE_ID:
            self._selected_profile_id = _CUSTOM_PROFILE_ID
            self._ensure_custom_profile()
        else:
            self._selected_profile_id = profile_id
            self._custom_base_profile_id = profile_id
        self._sync_routes_editor()
        self._sync_viewmodel()
        self.viewmodel.clear_message()

    def _sync_viewmodel(self) -> None:
        state = self._state
        if state is None:
            self._sync_profile_selector([], -1)
            self.viewmodel.apply_state(
                project_name="",
                blocker_text="",
                profile_options=[],
                custom_profile_text="",
                show_custom_profile=False,
                show_open_app_setup=False,
                can_save=False,
            )
            self._schedule_chrome_resize()
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
        selected_profile_index = (
            option_values.index(self._selected_profile_id) if self._selected_profile_id in option_values else -1
        )
        self._sync_profile_selector(options, selected_profile_index)

        can_save = False
        if self._is_custom_selected():
            can_save = self._draft_project_profile is not None
        elif self._selected_profile_id is not None:
            can_save = True

        self.viewmodel.apply_state(
            project_name=state.project.name,
            blocker_text=translate_backend_text(state.blocker.message) if state.blocker is not None else "",
            profile_options=options,
            custom_profile_text=self._custom_profile_text(),
            show_custom_profile=self._is_custom_selected() and self._effective_profile() is not None,
            show_open_app_setup=state.blocker is not None,
            can_save=can_save,
        )
        self._schedule_chrome_resize()

    def _sync_profile_selector(self, options: list[dict[str, object]], selected_index: int) -> None:
        signature = tuple((str(option.get("label", "")), str(option.get("detail", ""))) for option in options)
        if signature != self._profile_option_signature:
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            for option in options:
                self.profile_combo.addItem(str(option.get("label", "")), str(option.get("detail", "")))
            self.profile_combo.blockSignals(False)
            self._profile_option_signature = signature

        if self.profile_combo.currentIndex() != selected_index:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(selected_index)
            self.profile_combo.blockSignals(False)

        has_options = bool(options)
        self.profile_section.setVisible(has_options)
        self.profile_combo.setEnabled(has_options)
        if not has_options or selected_index < 0 or selected_index >= len(options):
            self.profile_detail_label.clear()
            self.profile_detail_label.hide()
            return
        detail = str(options[selected_index].get("detail", "")).strip()
        self.profile_detail_label.setText(detail)
        self.profile_detail_label.setVisible(bool(detail))

    def _sync_routes_editor(self) -> None:
        profile = self._effective_profile()
        if profile is None or not self._is_custom_selected():
            self.routes_editor.hide()
            self.routes_group.hide()
            self.routes_group.setMinimumHeight(0)
            self.routes_group.setMaximumHeight(0)
            self.routes_group.updateGeometry()
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self._schedule_chrome_resize()
            return
        self.routes_group.show()
        self.routes_editor.show()
        self.routes_editor.set_connection_choices(self._connection_choices())
        self.routes_editor.set_routes(profile.routes)
        self.routes_group.setMinimumHeight(0)
        self.routes_group.setMaximumHeight(16777215)
        self.routes_editor.updateGeometry()
        self.routes_group.updateGeometry()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self._schedule_chrome_resize()

    def _schedule_chrome_resize(self) -> None:
        self._sync_chrome_height()
        QTimer.singleShot(0, self._sync_chrome_height)

    def _sync_chrome_height(self) -> None:
        sync_qml_host_height(self.chrome_host)

    def _save(self) -> None:
        shared_profile_id = self._selected_shared_profile_id()
        project_profile = None
        base_profile_id = shared_profile_id
        if self._is_custom_selected():
            if self._draft_project_profile is None:
                self.viewmodel.set_message(self.tr("Select a shared workflow profile first."), is_error=True)
                return
            routes = self.routes_editor.build_routes()
            route_error = validate_workflow_routes(routes, tr=self.tr)
            if route_error is not None:
                self.viewmodel.set_message(route_error, is_error=True)
                return
            project_profile = self._build_custom_profile(routes)
            base_profile_id = self._custom_base_profile_id
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

    def _build_custom_profile(self, routes: list[WorkflowStepRoute]) -> WorkflowProfileDetail:
        assert self._draft_project_profile is not None
        return self._draft_project_profile.model_copy(
            update={"routes": routes, "kind": WorkflowProfileKind.PROJECT_SPECIFIC}
        )

    def _persist_custom_draft(self) -> None:
        if not self._is_custom_selected() or self._draft_project_profile is None:
            return
        self._draft_project_profile = self._build_custom_profile(self.routes_editor.build_routes())

    def _connection_choices(self) -> list[ConnectionChoice]:
        if self._state is None:
            return []
        return [
            ConnectionChoice(
                connection_id=connection.connection_id,
                label=connection.display_name,
                default_model=connection.default_model,
                base_url=connection.base_url,
            )
            for connection in self._state.available_connections
        ]

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.refresh()
