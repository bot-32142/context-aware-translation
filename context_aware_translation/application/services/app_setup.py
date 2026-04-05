from __future__ import annotations

import json
import sqlite3
from typing import Protocol

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionSummary,
    ConnectionTestRequest,
    ConnectionTestResult,
    ProviderCard,
    SaveConnectionRequest,
    SaveWorkflowProfileRequest,
    SetupWizardRequest,
    SetupWizardState,
    WizardRecommendationMode,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
)
from context_aware_translation.application.contracts.common import ProviderKind, UserMessage, UserMessageSeverity
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    _DEFAULT_PROFILE_NAME,
    _MANAGED_CONNECTION_DISPLAY_NAME_KEY,
    _MANAGED_CONNECTION_TEMPLATE_KEY,
    ApplicationRuntime,
    build_connection_summary,
    build_workflow_profile_detail,
    build_workflow_profile_payload,
    connection_display_name,
    expand_wizard_connection_drafts,
    infer_capabilities,
    is_managed_connection,
    managed_connection_key,
    raise_application_error,
    recommended_workflow_profile_from_drafts,
    wizard_connection_key_for_draft,
)
from context_aware_translation.storage.models.config_profile import ConfigProfile
from context_aware_translation.storage.models.endpoint_profile import EndpointProfile


class AppSetupService(Protocol):
    def get_state(self) -> AppSetupState: ...

    def get_wizard_state(self) -> SetupWizardState: ...

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState: ...

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState: ...

    def delete_connection(self, connection_id: str) -> AppSetupState: ...

    def duplicate_connection(self, connection_id: str) -> AppSetupState: ...

    def reset_connection_tokens(self, connection_id: str) -> ConnectionSummary: ...

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult: ...

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState: ...

    def save_workflow_profile(self, request: SaveWorkflowProfileRequest) -> AppSetupState: ...

    def duplicate_workflow_profile(self, profile_id: str) -> AppSetupState: ...

    def delete_workflow_profile(self, profile_id: str) -> AppSetupState: ...


class DefaultAppSetupService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_state(self) -> AppSetupState:
        connections = self._connection_summaries()
        shared_profiles = self._shared_profile_details()
        return AppSetupState(
            connections=connections,
            shared_profiles=shared_profiles,
        )

    def get_wizard_state(self) -> SetupWizardState:
        target_language = "English"
        translator_batch_size = 100
        polish_batch_size = 100
        current_default = self._runtime.get_default_profile()
        if current_default is not None:
            current_detail = self._profile_detail_from_payload(
                profile_id=current_default.profile_id,
                name=current_default.name,
                config=current_default.config,
                kind=WorkflowProfileKind.SHARED,
                is_default=current_default.is_default,
            )
            target_language = current_detail.target_language
            translator_route = next(
                (route for route in current_detail.routes if route.step_id is WorkflowStepId.TRANSLATOR),
                None,
            )
            if translator_route is not None and isinstance(translator_route.step_config.get("batch_size"), int):
                translator_batch_size = int(translator_route.step_config["batch_size"])
            polish_route = next(
                (route for route in current_detail.routes if route.step_id is WorkflowStepId.POLISH), None
            )
            if polish_route is not None and isinstance(polish_route.step_config.get("batch_size"), int):
                polish_batch_size = int(polish_route.step_config["batch_size"])
        return SetupWizardState(
            available_providers=[
                ProviderCard(
                    provider=ProviderKind.GEMINI,
                    label="Gemini",
                    helper_text="Good for image text reading and image editing.",
                ),
                ProviderCard(
                    provider=ProviderKind.OPENAI,
                    label="OpenAI",
                    helper_text="General-purpose text and image-capable provider.",
                ),
                ProviderCard(
                    provider=ProviderKind.DEEPSEEK,
                    label="DeepSeek",
                    helper_text="Low-cost text translation and context building.",
                ),
                ProviderCard(
                    provider=ProviderKind.ANTHROPIC,
                    label="Anthropic",
                    helper_text="Text translation and image understanding.",
                ),
            ],
            target_language=target_language,
            recommendation_mode=WizardRecommendationMode.BALANCED,
            translator_batch_size=translator_batch_size,
            polish_batch_size=polish_batch_size,
        )

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState:
        current_default = self._runtime.get_default_profile()
        target_language = "English"
        if current_default is not None:
            current_detail = self._profile_detail_from_payload(
                profile_id=current_default.profile_id,
                name=current_default.name,
                config=current_default.config,
                kind=WorkflowProfileKind.SHARED,
                is_default=current_default.is_default,
            )
            target_language = current_detail.target_language
        requested_target_language = (request.target_language or "").strip()
        if requested_target_language:
            target_language = requested_target_language
        profile_name = (request.profile_name or "").strip() or None
        recommendation = recommended_workflow_profile_from_drafts(
            request.connections,
            name=profile_name or "Recommended",
            target_language=target_language,
            recommendation_mode=request.recommendation_mode,
            translator_batch_size=request.translator_batch_size or 100,
            polish_batch_size=request.polish_batch_size or 100,
        )
        return SetupWizardState(
            available_providers=self.get_wizard_state().available_providers,
            selected_providers=request.providers,
            drafts=request.connections,
            test_results=[self._test_connection_result(draft) for draft in request.connections],
            recommendation=recommendation,
            profile_name=profile_name,
            target_language=target_language,
            recommendation_mode=request.recommendation_mode,
            translator_batch_size=request.translator_batch_size or 100,
            polish_batch_size=request.polish_batch_size or 100,
        )

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState:
        self._persist_connection(request.connection, connection_id=request.connection_id)
        self._runtime.invalidate_setup()
        return self.get_state()

    def delete_connection(self, connection_id: str) -> AppSetupState:
        existing = self._runtime.book_manager.get_endpoint_profile(connection_id)
        if existing is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
        try:
            deleted = self._runtime.book_manager.delete_endpoint_profile(connection_id)
        except sqlite3.IntegrityError as exc:
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                "Connection is still referenced by existing workflow configuration.",
                connection_id=connection_id,
                reason=str(exc),
            )
        if not deleted:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
        self._runtime.invalidate_setup()
        self._runtime.invalidate_projects()
        self._runtime.invalidate_workboard()
        return self.get_state()

    def duplicate_connection(self, connection_id: str) -> AppSetupState:
        existing = self._runtime.book_manager.get_endpoint_profile(connection_id)
        if existing is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
        try:
            self._runtime.book_manager.create_endpoint_profile(
                name=self._next_connection_copy_name(connection_display_name(existing)),
                api_key=existing.api_key,
                base_url=existing.base_url,
                model=existing.model,
                temperature=existing.temperature,
                kwargs=dict(existing.kwargs or {}),
                timeout=existing.timeout,
                max_retries=existing.max_retries,
                concurrency=existing.concurrency,
                description=existing.description,
                token_limit=existing.token_limit,
                input_token_limit=existing.input_token_limit,
                output_token_limit=existing.output_token_limit,
            )
        except sqlite3.IntegrityError as exc:
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                "A connection with that name already exists.",
                connection_id=connection_id,
                reason=str(exc),
            )
        self._runtime.invalidate_setup()
        return self.get_state()

    def reset_connection_tokens(self, connection_id: str) -> ConnectionSummary:
        existing = self._runtime.book_manager.get_endpoint_profile(connection_id)
        if existing is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
        updated = self._runtime.book_manager.reset_endpoint_tokens(connection_id)
        if updated is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
        self._runtime.invalidate_setup()
        return build_connection_summary(updated)

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult:
        return self._test_connection_result(request.connection)

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState:
        preview = self.preview_setup_wizard(request)
        recommendation = preview.recommendation
        if recommendation is None:
            raise_application_error(
                ApplicationErrorCode.PRECONDITION, "Setup wizard did not produce a workflow profile."
            )

        saved_ids: dict[str, str] = {}
        for draft in expand_wizard_connection_drafts(request.connections):
            existing_connection = self._find_connection_for_wizard_draft(draft)
            saved = self._persist_connection(
                draft,
                connection_id=(existing_connection.profile_id if existing_connection is not None else None),
                allow_managed_update=True,
            )
            saved_ids[draft.display_name] = saved.profile_id

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
        existing_profile = self._find_profile_by_name(recommended_profile.name)
        if existing_profile is not None:
            recommended_profile = recommended_profile.model_copy(update={"profile_id": existing_profile.profile_id})
        self.save_workflow_profile(SaveWorkflowProfileRequest(profile=recommended_profile, set_as_default=True))
        return self.get_state()

    def save_workflow_profile(self, request: SaveWorkflowProfileRequest) -> AppSetupState:
        should_be_default = request.set_as_default or request.profile.is_default
        existing = self._runtime.book_manager.get_profile(request.profile.profile_id)
        if existing is not None:
            payload = build_workflow_profile_payload(base_config=existing.config, profile=request.profile)
            try:
                updated = self._runtime.book_manager.update_profile(
                    request.profile.profile_id,
                    name=request.profile.name,
                    config=payload,
                    is_default=existing.is_default,
                )
            except sqlite3.IntegrityError as exc:
                raise_application_error(
                    ApplicationErrorCode.CONFLICT,
                    "A workflow profile with that name already exists.",
                    profile_id=request.profile.profile_id,
                    reason=str(exc),
                )
            if updated is None:
                raise_application_error(ApplicationErrorCode.INTERNAL, "Failed to update workflow profile.")
            profile_id = request.profile.profile_id
        else:
            payload = build_workflow_profile_payload(base_config=None, profile=request.profile)
            try:
                created = self._runtime.book_manager.create_profile(
                    name=request.profile.name or _DEFAULT_PROFILE_NAME,
                    config=payload,
                    is_default=False,
                )
            except sqlite3.IntegrityError as exc:
                raise_application_error(
                    ApplicationErrorCode.CONFLICT,
                    "A workflow profile with that name already exists.",
                    profile_name=request.profile.name or _DEFAULT_PROFILE_NAME,
                    reason=str(exc),
                )
            profile_id = created.profile_id

        if should_be_default:
            self._runtime.book_manager.set_default_profile(profile_id)

        self._runtime.invalidate_setup()
        self._runtime.invalidate_projects()
        self._runtime.invalidate_workboard()
        return self.get_state()

    def duplicate_workflow_profile(self, profile_id: str) -> AppSetupState:
        existing = self._runtime.book_manager.get_profile(profile_id)
        if existing is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Workflow profile not found: {profile_id}")
        try:
            self._runtime.book_manager.create_profile(
                name=self._next_profile_copy_name(existing.name),
                config=dict(existing.config),
                description=existing.description,
                is_default=False,
            )
        except sqlite3.IntegrityError as exc:
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                "A workflow profile with that name already exists.",
                profile_id=profile_id,
                reason=str(exc),
            )
        self._runtime.invalidate_setup()
        self._runtime.invalidate_projects()
        self._runtime.invalidate_workboard()
        return self.get_state()

    def delete_workflow_profile(self, profile_id: str) -> AppSetupState:
        try:
            deleted = self._runtime.book_manager.delete_profile(profile_id)
        except ValueError as exc:
            raise_application_error(ApplicationErrorCode.PRECONDITION, str(exc))
        except sqlite3.IntegrityError as exc:
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                "Workflow profile is still referenced by existing projects.",
                profile_id=profile_id,
                reason=str(exc),
            )
        if not deleted:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Workflow profile not found: {profile_id}")
        self._runtime.invalidate_setup()
        self._runtime.invalidate_projects()
        self._runtime.invalidate_workboard()
        return self.get_state()

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
        connection_name_by_id = {profile.profile_id: connection_display_name(profile) for profile in endpoint_profiles}
        connection_model_by_id = {profile.profile_id: (profile.model or None) for profile in endpoint_profiles}
        connection_base_url_by_id = {profile.profile_id: (profile.base_url or None) for profile in endpoint_profiles}
        return build_workflow_profile_detail(
            profile_id=profile_id,
            name=name,
            kind=kind,
            config=config,
            connection_name_by_id=connection_name_by_id,
            connection_model_by_id=connection_model_by_id,
            connection_base_url_by_id=connection_base_url_by_id,
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
        return ConnectionTestResult(
            connection_label=draft.display_name,
            supported_capabilities=infer_capabilities(draft.provider),
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text="Connection accepted. Capability testing was inferred from the provider type.",
            ),
        )

    def _parse_connection_kwargs(self, draft: ConnectionDraft) -> dict[str, object]:
        payload: dict[str, object] = {"provider": draft.provider.value}
        raw_json = (draft.custom_parameters_json or "").strip()
        if not raw_json:
            return payload
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            raise_application_error(
                ApplicationErrorCode.PRECONDITION,
                "Custom parameters must be valid JSON.",
            )
        if not isinstance(parsed, dict):
            raise_application_error(
                ApplicationErrorCode.PRECONDITION,
                "Custom parameters must be a JSON object.",
            )
        payload.update({str(key): value for key, value in parsed.items()})
        return payload

    def _persist_connection(
        self,
        draft: ConnectionDraft,
        *,
        connection_id: str | None = None,
        allow_managed_update: bool = False,
    ) -> EndpointProfile:
        kwargs_payload = self._parse_connection_kwargs(draft)
        existing = self._runtime.book_manager.get_endpoint_profile(connection_id) if connection_id else None
        if connection_id and existing is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")

        managed_key = (
            managed_connection_key(existing)
            if existing is not None
            else (wizard_connection_key_for_draft(draft) if allow_managed_update else None)
        )
        if managed_key is not None:
            kwargs_payload[_MANAGED_CONNECTION_TEMPLATE_KEY] = managed_key

        persisted_name = draft.display_name
        if existing is not None and is_managed_connection(existing) and not allow_managed_update:
            persisted_name = existing.name
            public_name = connection_display_name(existing)
            if draft.display_name == public_name:
                kwargs_payload.pop(_MANAGED_CONNECTION_DISPLAY_NAME_KEY, None)
            else:
                kwargs_payload[_MANAGED_CONNECTION_DISPLAY_NAME_KEY] = draft.display_name
        else:
            kwargs_payload.pop(_MANAGED_CONNECTION_DISPLAY_NAME_KEY, None)

        if existing is not None:
            assert connection_id is not None
            try:
                updated = self._runtime.book_manager.update_endpoint_profile(
                    connection_id,
                    name=persisted_name,
                    description=draft.description,
                    api_key=existing.api_key if draft.api_key is None else draft.api_key,
                    base_url=existing.base_url if draft.base_url is None else draft.base_url,
                    model=existing.model if draft.default_model is None else draft.default_model,
                    temperature=draft.temperature,
                    kwargs=kwargs_payload,
                    timeout=draft.timeout,
                    max_retries=draft.max_retries,
                    concurrency=draft.concurrency,
                    token_limit=draft.token_limit,
                    input_token_limit=draft.input_token_limit,
                    output_token_limit=draft.output_token_limit,
                )
            except sqlite3.IntegrityError as exc:
                raise_application_error(
                    ApplicationErrorCode.CONFLICT,
                    "A connection with that name already exists.",
                    connection_id=connection_id,
                    reason=str(exc),
                )
            if updated is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Connection not found: {connection_id}")
            return updated

        try:
            return self._runtime.book_manager.create_endpoint_profile(
                name=persisted_name,
                api_key=draft.api_key or "",
                base_url=draft.base_url or "",
                model=draft.default_model or "",
                temperature=draft.temperature,
                kwargs=kwargs_payload,
                timeout=draft.timeout,
                max_retries=draft.max_retries,
                concurrency=draft.concurrency,
                description=draft.description,
                token_limit=draft.token_limit,
                input_token_limit=draft.input_token_limit,
                output_token_limit=draft.output_token_limit,
            )
        except sqlite3.IntegrityError as exc:
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                "A connection with that name already exists.",
                connection_name=persisted_name,
                reason=str(exc),
            )

    def _find_connection_for_wizard_draft(self, draft: ConnectionDraft) -> EndpointProfile | None:
        profiles = self._runtime.book_manager.list_endpoint_profiles()
        managed_key = wizard_connection_key_for_draft(draft)
        if managed_key is not None:
            matched = next((profile for profile in profiles if managed_connection_key(profile) == managed_key), None)
            if matched is not None:
                return matched
        return next((profile for profile in profiles if profile.name == draft.display_name), None)

    def _find_profile_by_name(self, name: str) -> ConfigProfile | None:
        return next((profile for profile in self._runtime.book_manager.list_profiles() if profile.name == name), None)

    def _next_connection_copy_name(self, base_name: str) -> str:
        existing = {profile.name for profile in self._runtime.book_manager.list_endpoint_profiles()}
        return self._next_copy_name(base_name, existing)

    def _next_profile_copy_name(self, base_name: str) -> str:
        existing = {profile.name for profile in self._runtime.book_manager.list_profiles()}
        return self._next_copy_name(base_name, existing)

    def _next_copy_name(self, base_name: str, existing_names: set[str]) -> str:
        stem = f"{base_name} Copy"
        if stem not in existing_names:
            return stem
        index = 2
        while True:
            candidate = f"{stem} {index}"
            if candidate not in existing_names:
                return candidate
            index += 1
