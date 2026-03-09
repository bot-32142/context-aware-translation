from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import (
    BindingSource,
    BlockerCode,
    CapabilityAvailability,
    CapabilityCode,
    NavigationTargetKind,
    PresetCode,
)
from context_aware_translation.application.contracts.project_setup import (
    ProjectCapabilityBinding,
    ProjectCapabilityCard,
    ProjectConnectionOption,
    ProjectSetupState,
    SaveProjectSetupRequest,
)
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    build_default_routes_from_config,
    build_workflow_profile_payload,
    make_blocker,
    raise_application_error,
    read_ui_preset,
)


class ProjectSetupService(Protocol):
    def get_state(self, project_id: str) -> ProjectSetupState: ...

    def save(self, request: SaveProjectSetupRequest) -> ProjectSetupState: ...


class DefaultProjectSetupService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_state(self, project_id: str) -> ProjectSetupState:
        project = self._runtime.get_project_ref(project_id)
        config = self._runtime.get_effective_config_payload(project_id)
        default_profile = self._runtime.get_default_profile()
        default_config = default_profile.config if default_profile is not None else {}
        default_routes = {route.capability: route.connection_id for route in build_default_routes_from_config(default_config)}
        current_routes = {route.capability: route.connection_id for route in build_default_routes_from_config(config)}
        options = [ProjectConnectionOption(connection_id=conn_id, connection_label=label) for conn_id, label in self._runtime.list_connection_options()]
        option_ids = {option.connection_id for option in options}

        bindings: list[ProjectCapabilityBinding] = []
        cards: list[ProjectCapabilityCard] = []
        for capability in CapabilityCode:
            current_id = current_routes.get(capability)
            default_id = default_routes.get(capability)
            if current_id is not None:
                source = BindingSource.APP_DEFAULT if current_id == default_id else BindingSource.PROJECT_OVERRIDE
            else:
                source = BindingSource.MISSING

            blocker = None
            if current_id is None:
                availability = CapabilityAvailability.MISSING
                blocker = make_blocker(
                    BlockerCode.NEEDS_SETUP,
                    f"{capability.value.replace('_', ' ').title()} needs a shared connection in App Setup.",
                    target_kind=NavigationTargetKind.APP_SETUP,
                )
            elif current_id not in option_ids:
                availability = CapabilityAvailability.MISSING
                blocker = make_blocker(
                    code=BlockerCode.NEEDS_SETUP,
                    message=f"{capability.value.replace('_', ' ').title()} needs a shared connection in App Setup.",
                    target_kind=NavigationTargetKind.APP_SETUP,
                )
            else:
                availability = CapabilityAvailability.READY
            label = next((opt.connection_label for opt in options if opt.connection_id == current_id), current_id)
            bindings.append(
                ProjectCapabilityBinding(
                    capability=capability,
                    availability=availability,
                    source=source,
                    connection_id=current_id,
                    connection_label=label,
                    blocker=blocker,
                )
            )
            cards.append(
                ProjectCapabilityCard(
                    capability=capability,
                    availability=availability,
                    source=source,
                    connection_id=current_id,
                    connection_label=label,
                    options=options,
                    blocker=blocker,
                )
            )
        preset_value = read_ui_preset(config) or "balanced"
        return ProjectSetupState(
            project=project,
            target_language=str(config.get("translation_target_language") or ""),
            preset=PresetCode(preset_value),
            bindings=bindings,
            capability_cards=cards,
        )

    def save(self, request: SaveProjectSetupRequest) -> ProjectSetupState:
        default_profile = self._runtime.get_default_profile()
        base_config = default_profile.config if default_profile is not None else self._runtime.get_effective_config_payload(request.project_id)
        routes = [
            route
            for route in build_default_routes_from_config(base_config)
            if route.capability not in {override.capability for override in request.overrides}
        ]
        from context_aware_translation.application.contracts.app_setup import DefaultRoute
        routes.extend(
            DefaultRoute(
                capability=override.capability,
                connection_id=override.connection_id,
                connection_label=override.connection_id,
            )
            for override in request.overrides
            if override.connection_id is not None
        )
        payload = build_workflow_profile_payload(
            base_config=base_config,
            routes=routes,
            target_language=request.target_language,
            preset_code=request.preset.value,
        )
        try:
            self._runtime.book_manager.set_book_custom_config(request.project_id, payload)
            self._runtime.book_manager.update_book(request.project_id, profile_id=None)
        except ValueError as exc:
            raise_application_error(ApplicationErrorCode.PRECONDITION, str(exc), project_id=request.project_id)
        self._runtime.invalidate_setup(request.project_id)
        self._runtime.invalidate_workboard(request.project_id)
        self._runtime.invalidate_projects()
        return self.get_state(request.project_id)
