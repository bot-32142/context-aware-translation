from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    CapabilityCard,
    ConnectionDraft,
    ConnectionTestRequest,
    ConnectionTestResult,
    ProviderCard,
    SaveConnectionRequest,
    SaveWorkflowProfileRequest,
    SetupWizardRequest,
    SetupWizardState,
    SetupWizardStep,
    WorkflowProfileDetail,
    WorkflowProfileKind,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    CapabilityAvailability,
    CapabilityCode,
    PresetCode,
    ProviderKind,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    _DEFAULT_PROFILE_NAME,
    ApplicationRuntime,
    build_capability_cards,
    build_connection_summary,
    build_workflow_profile_detail,
    build_workflow_profile_payload,
    infer_capabilities,
    raise_application_error,
    recommended_workflow_profile_from_drafts,
)


class AppSetupService(Protocol):
    def get_state(self) -> AppSetupState: ...

    def get_wizard_state(self) -> SetupWizardState: ...

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState: ...

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState: ...

    def delete_connection(self, connection_id: str) -> AppSetupState: ...

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult: ...

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState: ...

    def save_workflow_profile(self, request: SaveWorkflowProfileRequest) -> AppSetupState: ...

    def seed_defaults(self) -> AcceptedCommand: ...


class DefaultAppSetupService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_state(self) -> AppSetupState:
        connections = self._connection_summaries()
        capabilities = build_capability_cards(connections)
        shared_profiles = self._shared_profile_details()
        default_profile = next((profile for profile in shared_profiles if profile.is_default), None)
        selected_profile = default_profile or (shared_profiles[0] if shared_profiles else None)
        return AppSetupState(
            connections=connections,
            capabilities=capabilities,
            shared_profiles=shared_profiles,
            default_profile_id=(default_profile.profile_id if default_profile is not None else None),
            selected_profile=selected_profile,
            requires_wizard=not bool(connections),
            wizard=self.get_wizard_state() if not connections else None,
        )

    def get_wizard_state(self) -> SetupWizardState:
        return SetupWizardState(
            step=SetupWizardStep.CHOOSE_PROVIDERS,
            available_providers=[
                ProviderCard(
                    provider=ProviderKind.GEMINI,
                    label="Gemini",
                    helper_text="Good for image text reading and image editing.",
                    recommended_for=[
                        CapabilityCode.IMAGE_TEXT_READING,
                        CapabilityCode.IMAGE_EDITING,
                        CapabilityCode.TRANSLATION,
                    ],
                ),
                ProviderCard(
                    provider=ProviderKind.OPENAI,
                    label="OpenAI",
                    helper_text="General-purpose text and image-capable provider.",
                    recommended_for=[
                        CapabilityCode.TRANSLATION,
                        CapabilityCode.IMAGE_TEXT_READING,
                        CapabilityCode.IMAGE_EDITING,
                    ],
                ),
                ProviderCard(
                    provider=ProviderKind.DEEPSEEK,
                    label="DeepSeek",
                    helper_text="Low-cost text translation and context building.",
                    recommended_for=[CapabilityCode.TRANSLATION],
                ),
                ProviderCard(
                    provider=ProviderKind.ANTHROPIC,
                    label="Anthropic",
                    helper_text="Text translation and image understanding.",
                    recommended_for=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
                ),
                ProviderCard(
                    provider=ProviderKind.OPENAI_COMPATIBLE,
                    label="OpenAI-compatible / Custom",
                    helper_text="Use a custom base URL and model names.",
                    supports_custom_endpoint=True,
                    recommended_for=[CapabilityCode.TRANSLATION],
                ),
            ],
        )

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState:
        current_default = self._runtime.get_default_profile()
        target_language = "English"
        preset = PresetCode.BALANCED
        if current_default is not None:
            current_detail = self._profile_detail_from_payload(
                profile_id=current_default.profile_id,
                name=current_default.name,
                config=current_default.config,
                kind=WorkflowProfileKind.SHARED,
                is_default=current_default.is_default,
            )
            target_language = current_detail.target_language
            preset = current_detail.preset
        recommendation = recommended_workflow_profile_from_drafts(
            request.connections,
            target_language=target_language,
            preset=preset,
        )
        return SetupWizardState(
            step=SetupWizardStep.REVIEW_PROFILE,
            available_providers=self.get_wizard_state().available_providers,
            selected_providers=request.providers,
            drafts=request.connections,
            test_results=[self._test_connection_result(draft) for draft in request.connections],
            recommendation=recommendation,
        )

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState:
        draft = request.connection
        if request.connection_id:
            existing = self._runtime.book_manager.get_endpoint_profile(request.connection_id)
            if existing is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND, f"Connection not found: {request.connection_id}"
                )
            updated = self._runtime.book_manager.update_endpoint_profile(
                request.connection_id,
                name=draft.display_name,
                api_key=existing.api_key if draft.api_key is None else draft.api_key,
                base_url=existing.base_url if draft.base_url is None else draft.base_url,
                model=existing.model if draft.default_model is None else draft.default_model,
                kwargs=(
                    {**existing.kwargs, "provider": draft.provider.value}
                    if not draft.metadata
                    else {**{item.key: item.value for item in draft.metadata}, "provider": draft.provider.value}
                ),
            )
            if updated is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND, f"Connection not found: {request.connection_id}"
                )
        else:
            self._runtime.book_manager.create_endpoint_profile(
                name=draft.display_name,
                api_key=draft.api_key or "",
                base_url=draft.base_url or "",
                model=draft.default_model or "",
                kwargs={**{item.key: item.value for item in draft.metadata}, "provider": draft.provider.value},
            )
        self._runtime.invalidate_setup()
        return self.get_state()

    def delete_connection(self, connection_id: str) -> AppSetupState:
        deleted = self._runtime.book_manager.delete_endpoint_profile(connection_id)
        if not deleted:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
        self._runtime.invalidate_setup()
        return self.get_state()

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult:
        return self._test_connection_result(request.connection)

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState:
        preview = self.preview_setup_wizard(request)
        recommendation = preview.recommendation
        if recommendation is None:
            raise_application_error(ApplicationErrorCode.PRECONDITION, "Setup wizard did not produce a workflow profile.")

        saved_ids: dict[str, str] = {}
        for draft in request.connections:
            state_before = {p.profile_id for p in self._runtime.book_manager.list_endpoint_profiles()}
            self.save_connection(SaveConnectionRequest(connection=draft))
            new_profiles = self._runtime.book_manager.list_endpoint_profiles()
            for profile in new_profiles:
                if profile.profile_id not in state_before and profile.name == draft.display_name:
                    saved_ids[draft.display_name] = profile.profile_id
                    break
            else:
                existing = next((p for p in new_profiles if p.name == draft.display_name), None)
                if existing is not None:
                    saved_ids[draft.display_name] = existing.profile_id

        recommended_profile = recommendation.model_copy(
            update={
                "routes": [
                    route.model_copy(
                        update={
                            "connection_id": saved_ids.get(route.connection_id or "", route.connection_id),
                            "connection_label": route.connection_label,
                        }
                    )
                    for route in recommendation.routes
                ]
            }
        )
        self.save_workflow_profile(SaveWorkflowProfileRequest(profile=recommended_profile, set_as_default=True))
        return self.get_state()

    def save_workflow_profile(self, request: SaveWorkflowProfileRequest) -> AppSetupState:
        existing = self._runtime.book_manager.get_profile(request.profile.profile_id)
        if existing is not None:
            payload = build_workflow_profile_payload(base_config=existing.config, profile=request.profile)
            updated = self._runtime.book_manager.update_profile(
                request.profile.profile_id,
                name=request.profile.name,
                config=payload,
                is_default=request.set_as_default or request.profile.is_default,
            )
            if updated is None:
                raise_application_error(ApplicationErrorCode.INTERNAL, "Failed to update workflow profile.")
            profile_id = request.profile.profile_id
        else:
            payload = build_workflow_profile_payload(base_config=None, profile=request.profile)
            created = self._runtime.book_manager.create_profile(
                name=request.profile.name or _DEFAULT_PROFILE_NAME,
                config=payload,
                is_default=request.set_as_default or request.profile.is_default,
            )
            profile_id = created.profile_id

        if request.set_as_default:
            self._runtime.book_manager.set_default_profile(profile_id)

        self._runtime.invalidate_setup()
        self._runtime.invalidate_projects()
        self._runtime.invalidate_workboard()
        return self.get_state()

    def seed_defaults(self) -> AcceptedCommand:
        self._runtime.book_manager.seed_system_defaults()
        self._runtime.invalidate_setup()
        return AcceptedCommand(
            command_name="seed_defaults",
            message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Default setup profiles created."),
        )

    def _connection_summaries(self) -> list:
        return [build_connection_summary(profile) for profile in self._runtime.book_manager.list_endpoint_profiles()]

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

    def _test_connection_result(self, draft: ConnectionDraft) -> ConnectionTestResult:
        capabilities = [
            CapabilityCard(
                capability=capability,
                availability=CapabilityAvailability.READY,
                message=f"Supported by {draft.provider.value}",
            )
            for capability in infer_capabilities(draft.provider)
        ]
        return ConnectionTestResult(
            connection_label=draft.display_name,
            capabilities=capabilities,
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text="Connection accepted. Capability testing was inferred from the provider type.",
            ),
        )
