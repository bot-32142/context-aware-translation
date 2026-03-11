from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.app_setup import WorkflowProfileDetail, WorkflowProfileKind
from context_aware_translation.application.contracts.common import BlockerCode, NavigationTargetKind
from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    build_connection_summary,
    build_workflow_profile_detail,
    build_workflow_profile_payload,
    make_blocker,
    raise_application_error,
    read_source_profile_id,
)


class ProjectSetupService(Protocol):
    def get_state(self, project_id: str) -> ProjectSetupState: ...

    def save(self, request: SaveProjectSetupRequest) -> ProjectSetupState: ...


class DefaultProjectSetupService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_state(self, project_id: str) -> ProjectSetupState:
        project = self._runtime.get_project_ref(project_id)
        book = self._runtime.get_book(project_id)
        available_connections = [
            build_connection_summary(profile) for profile in self._runtime.book_manager.list_endpoint_profiles()
        ]
        shared_profiles = self._shared_profile_details()
        shared_by_id = {profile.profile_id: profile for profile in shared_profiles}

        selected_shared_profile_id: str | None = None
        project_profile: WorkflowProfileDetail | None = None
        blocker = None

        if book.profile_id is not None:
            selected_shared_profile_id = book.profile_id
            if shared_by_id.get(book.profile_id) is None:
                blocker = make_blocker(
                    BlockerCode.NEEDS_SETUP,
                    "The selected shared workflow profile no longer exists. Open App Setup.",
                    target_kind=NavigationTargetKind.APP_SETUP,
                )
        else:
            config = self._runtime.get_effective_config_payload(project_id)
            source_profile_id = read_source_profile_id(config)
            if source_profile_id is not None:
                selected_shared_profile_id = source_profile_id if source_profile_id in shared_by_id else None
            project_profile = self._profile_detail_from_payload(
                profile_id=f"project:{project_id}",
                name=f"{project.name} project profile",
                config=config,
                kind=WorkflowProfileKind.PROJECT_SPECIFIC,
                is_default=False,
            )

        if not shared_profiles and project_profile is None:
            blocker = make_blocker(
                BlockerCode.NEEDS_SETUP,
                "No shared workflow profiles are available. Open App Setup.",
                target_kind=NavigationTargetKind.APP_SETUP,
            )

        return ProjectSetupState(
            project=project,
            available_connections=available_connections,
            shared_profiles=shared_profiles,
            selected_shared_profile_id=selected_shared_profile_id,
            project_profile=project_profile,
            blocker=blocker,
        )

    def save(self, request: SaveProjectSetupRequest) -> ProjectSetupState:
        if request.project_profile is not None:
            base_config = self._base_config_for_project_profile(request)
            payload = build_workflow_profile_payload(
                base_config=base_config,
                profile=request.project_profile,
                source_profile_id=request.shared_profile_id,
            )
            try:
                self._runtime.book_manager.set_book_custom_config(request.project_id, payload)
            except ValueError as exc:
                raise_application_error(ApplicationErrorCode.PRECONDITION, str(exc), project_id=request.project_id)
        elif request.shared_profile_id is not None:
            shared_profile = self._runtime.book_manager.get_profile(request.shared_profile_id)
            if shared_profile is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"Workflow profile not found: {request.shared_profile_id}",
                    project_id=request.project_id,
                )
            updated = self._runtime.book_manager.update_book(request.project_id, profile_id=request.shared_profile_id)
            if updated is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Project not found: {request.project_id}")
        else:
            raise_application_error(
                ApplicationErrorCode.PRECONDITION,
                "Select a shared workflow profile or save a project-specific workflow profile.",
                project_id=request.project_id,
            )

        self._runtime.invalidate_setup(request.project_id)
        self._runtime.invalidate_workboard(request.project_id)
        self._runtime.invalidate_projects()
        return self.get_state(request.project_id)

    def _base_config_for_project_profile(self, request: SaveProjectSetupRequest) -> dict:
        if request.shared_profile_id is not None:
            shared_profile = self._runtime.book_manager.get_profile(request.shared_profile_id)
            if shared_profile is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"Workflow profile not found: {request.shared_profile_id}",
                    project_id=request.project_id,
                )
            return dict(shared_profile.config)
        return self._runtime.get_effective_config_payload(request.project_id)

    def _shared_profile_details(self) -> list[WorkflowProfileDetail]:
        return [
            self._profile_detail_from_payload(
                profile_id=profile.profile_id,
                name=profile.name,
                config=profile.config,
                kind=WorkflowProfileKind.SHARED,
                is_default=profile.is_default,
            )
            for profile in self._runtime.book_manager.list_profiles()
        ]

    def _profile_detail_from_payload(
        self,
        *,
        profile_id: str,
        name: str,
        config: dict,
        kind: WorkflowProfileKind,
        is_default: bool,
    ) -> WorkflowProfileDetail:
        endpoint_profiles = self._runtime.book_manager.list_endpoint_profiles()
        connection_name_by_id = {profile.profile_id: profile.name for profile in endpoint_profiles}
        connection_model_by_id = {profile.profile_id: (profile.model or None) for profile in endpoint_profiles}
        return build_workflow_profile_detail(
            profile_id=profile_id,
            name=name,
            kind=kind,
            config=config,
            connection_name_by_id=connection_name_by_id,
            connection_model_by_id=connection_model_by_id,
            is_default=is_default,
        )
