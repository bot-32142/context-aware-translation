from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from context_aware_translation.application.contracts.common import (
    CapabilityCode,
    ContractModel,
    ProviderKind,
    UserMessage,
)


class ConnectionStatus(StrEnum):
    UNTESTED = "untested"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class WorkflowProfileKind(StrEnum):
    SHARED = "shared"
    PROJECT_SPECIFIC = "project_specific"


class SetupWizardMode(StrEnum):
    QUALITY = "quality"
    BALANCED = "balanced"
    BUDGET = "budget"


class WorkflowStepId(StrEnum):
    EXTRACTOR = "extractor"
    SUMMARIZER = "summarizer"
    GLOSSARY_TRANSLATOR = "glossary_translator"
    TRANSLATOR = "translator"
    POLISH = "polish"
    REVIEWER = "reviewer"
    OCR = "ocr"
    IMAGE_REEMBEDDING = "image_reembedding"
    MANGA_TRANSLATOR = "manga_translator"
    TRANSLATOR_BATCH = "translator_batch"


_DEFAULT_CONNECTION_CONCURRENCY = 5
_DEEPSEEK_DEFAULT_CONNECTION_CONCURRENCY = 15


def default_connection_concurrency(provider: ProviderKind | None) -> int:
    if provider is ProviderKind.DEEPSEEK:
        return _DEEPSEEK_DEFAULT_CONNECTION_CONCURRENCY
    return _DEFAULT_CONNECTION_CONCURRENCY


class ProviderCard(ContractModel):
    provider: ProviderKind
    label: str
    helper_text: str | None = None


class ConnectionSummary(ContractModel):
    connection_id: str
    display_name: str
    is_managed: bool = False
    provider: ProviderKind
    description: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    temperature: float = 0.0
    timeout: int = 60
    max_retries: int = 3
    concurrency: int = _DEFAULT_CONNECTION_CONCURRENCY
    token_limit: int | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    tokens_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    cached_input_tokens_used: int = 0
    uncached_input_tokens_used: int = 0
    custom_parameters_json: str | None = None
    status: ConnectionStatus = ConnectionStatus.UNTESTED


class ConnectionDraft(ContractModel):
    display_name: str
    provider: ProviderKind
    description: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    temperature: float = 0.0
    timeout: int = 60
    max_retries: int = 3
    concurrency: int = _DEFAULT_CONNECTION_CONCURRENCY
    token_limit: int | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    custom_parameters_json: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _apply_provider_specific_defaults(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "concurrency" in data and data.get("concurrency") is not None:
            return data

        provider_value = data.get("provider")
        provider: ProviderKind | None = None
        if isinstance(provider_value, ProviderKind):
            provider = provider_value
        elif isinstance(provider_value, str):
            try:
                provider = ProviderKind(provider_value)
            except ValueError:
                provider = None

        if provider is None:
            return data

        payload = dict(data)
        payload["concurrency"] = default_connection_concurrency(provider)
        return payload


class WorkflowStepRoute(ContractModel):
    step_id: WorkflowStepId
    step_label: str
    connection_id: str | None = None
    connection_label: str | None = None
    model: str | None = None
    step_config: dict[str, Any] = Field(default_factory=dict)


class WorkflowProfileDetail(ContractModel):
    profile_id: str
    name: str
    kind: WorkflowProfileKind
    target_language: str
    routes: list[WorkflowStepRoute] = Field(default_factory=list)
    is_default: bool = False


class ConnectionTestRequest(ContractModel):
    connection: ConnectionDraft


class ConnectionTestResult(ContractModel):
    connection_label: str
    supported_capabilities: list[CapabilityCode] = Field(default_factory=list)
    message: UserMessage | None = None


class SaveConnectionRequest(ContractModel):
    connection: ConnectionDraft
    connection_id: str | None = None


class SaveWorkflowProfileRequest(ContractModel):
    profile: WorkflowProfileDetail
    set_as_default: bool = False


class SetupWizardRequest(ContractModel):
    providers: list[ProviderKind]
    connections: list[ConnectionDraft]
    profile_name: str | None = None
    target_language: str | None = None
    recommendation_mode: SetupWizardMode = SetupWizardMode.BALANCED


class SetupWizardState(ContractModel):
    available_providers: list[ProviderCard] = Field(default_factory=list)
    selected_providers: list[ProviderKind] = Field(default_factory=list)
    drafts: list[ConnectionDraft] = Field(default_factory=list)
    test_results: list[ConnectionTestResult] = Field(default_factory=list)
    recommendation: WorkflowProfileDetail | None = None
    profile_name: str | None = None
    target_language: str = "English"
    recommendation_mode: SetupWizardMode = SetupWizardMode.BALANCED


class AppSetupState(ContractModel):
    connections: list[ConnectionSummary]
    shared_profiles: list[WorkflowProfileDetail] = Field(default_factory=list)
