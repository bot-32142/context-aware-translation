from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    CapabilityCard,
    ConnectionDraft,
    ConnectionTestRequest,
    ConnectionTestResult,
    DefaultRoute,
    ProviderCard,
    RoutingRecommendation,
    SaveConnectionRequest,
    SaveDefaultRoutesRequest,
    SetupWizardRequest,
    SetupWizardState,
    SetupWizardStep,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    CapabilityAvailability,
    CapabilityCode,
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
    build_default_routes_from_config,
    build_workflow_profile_payload,
    infer_capabilities,
    raise_application_error,
)


class AppSetupService(Protocol):
    def get_state(self) -> AppSetupState: ...

    def get_wizard_state(self) -> SetupWizardState: ...

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState: ...

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState: ...

    def delete_connection(self, connection_id: str) -> AppSetupState: ...

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult: ...

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState: ...

    def save_default_routes(self, request: SaveDefaultRoutesRequest) -> AppSetupState: ...

    def seed_defaults(self) -> AcceptedCommand: ...


class DefaultAppSetupService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_state(self) -> AppSetupState:
        connections = [build_connection_summary(profile) for profile in self._runtime.book_manager.list_endpoint_profiles()]
        default_profile = self._runtime.get_default_profile()
        routes = build_default_routes_from_config(default_profile.config) if default_profile is not None else []
        connection_name_by_id = {profile.connection_id: profile.display_name for profile in connections}
        routes = [
            route.model_copy(update={"connection_label": connection_name_by_id.get(route.connection_id, route.connection_id)})
            for route in routes
        ]
        return AppSetupState(
            connections=connections,
            capabilities=build_capability_cards(connections, routes),
            default_routes=routes,
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
        return SetupWizardState(
            step=SetupWizardStep.REVIEW_ROUTING,
            available_providers=self.get_wizard_state().available_providers,
            selected_providers=request.providers,
            drafts=request.connections,
            test_results=[self._test_connection_result(draft) for draft in request.connections],
            recommendation=self._build_recommendation(request.connections),
        )

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState:
        draft = request.connection
        if request.connection_id:
            existing = self._runtime.book_manager.get_endpoint_profile(request.connection_id)
            if existing is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {request.connection_id}")
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
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {request.connection_id}")
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
        actual_routes = [
            route.model_copy(
                update={"connection_id": saved_ids.get(route.connection_label, route.connection_id)}
            )
            for route in (preview.recommendation.routes if preview.recommendation is not None else [])
            if saved_ids.get(route.connection_label, route.connection_id)
        ]
        self.save_default_routes(SaveDefaultRoutesRequest(routes=actual_routes))
        return self.get_state()

    def save_default_routes(self, request: SaveDefaultRoutesRequest) -> AppSetupState:
        existing_default = self._runtime.get_default_profile()
        base_config = existing_default.config if existing_default is not None else None
        target_language = "English"
        if existing_default is not None and isinstance(existing_default.config.get("translation_target_language"), str):
            target_language = str(existing_default.config["translation_target_language"])
        payload = build_workflow_profile_payload(
            base_config=base_config,
            routes=request.routes,
            target_language=target_language,
            preset_code=(base_config or {}).get("_ui_preset") if base_config else None,
        )
        if existing_default is not None:
            updated = self._runtime.book_manager.update_profile(
                existing_default.profile_id,
                config=payload,
                is_default=True,
            )
            if updated is None:
                raise_application_error(ApplicationErrorCode.INTERNAL, "Failed to update default routing profile.")
        else:
            profile = self._runtime.book_manager.create_profile(
                name=_DEFAULT_PROFILE_NAME,
                config=payload,
                is_default=True,
            )
            self._runtime.book_manager.set_default_profile(profile.profile_id)
        self._runtime.invalidate_setup()
        self._runtime.invalidate_projects()
        self._runtime.invalidate_workboard()
        return self.get_state()

    def _test_connection_result(self, draft: ConnectionDraft) -> ConnectionTestResult:
        capabilities = [
            CapabilityCard(
                capability=capability,
                availability=CapabilityAvailability.READY,
                message=f"Supported by {draft.provider.value}",
            )
            for capability in infer_capabilities(draft.provider)
        ]
        recommendation = self._build_recommendation([draft])
        return ConnectionTestResult(
            connection_label=draft.display_name,
            capabilities=capabilities,
            recommendation=recommendation,
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text="Connection accepted. Capability routing was inferred from the provider type.",
            ),
        )

    def _build_recommendation(self, drafts: list[ConnectionDraft]) -> RoutingRecommendation:
        routes: list[DefaultRoute] = []
        notes: list[str] = []
        for capability in CapabilityCode:
            chosen = next((draft for draft in drafts if capability in infer_capabilities(draft.provider)), None)
            if chosen is None:
                notes.append(f"No configured provider supports {capability.value}.")
                continue
            routes.append(
                DefaultRoute(
                    capability=capability,
                    connection_id=chosen.display_name,
                    connection_label=chosen.display_name,
                )
            )
        if drafts:
            notes.append("Recommended routing prefers the first selected provider that supports each capability.")
        return RoutingRecommendation(routes=routes, notes=notes)

    def seed_defaults(self) -> AcceptedCommand:
        self._runtime.book_manager.seed_system_defaults()
        self._runtime.invalidate_setup()
        return AcceptedCommand(
            command_name="seed_defaults",
            message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Default setup profiles created."),
        )
