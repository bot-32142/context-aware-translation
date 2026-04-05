from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

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
    concurrency: int = 5
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
    concurrency: int = 5
    token_limit: int | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    custom_parameters_json: str | None = None


class WorkflowStepRoute(ContractModel):
    step_id: WorkflowStepId
    step_label: str
    connection_id: str | None = None
    connection_label: str | None = None
    connection_base_url: str | None = None
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
    translator_batch_size: int | None = None
    polish_batch_size: int | None = None


class SetupWizardState(ContractModel):
    available_providers: list[ProviderCard] = Field(default_factory=list)
    selected_providers: list[ProviderKind] = Field(default_factory=list)
    drafts: list[ConnectionDraft] = Field(default_factory=list)
    test_results: list[ConnectionTestResult] = Field(default_factory=list)
    recommendation: WorkflowProfileDetail | None = None
    profile_name: str | None = None
    target_language: str = "English"
    translator_batch_size: int = 100
    polish_batch_size: int = 100


class AppSetupState(ContractModel):
    connections: list[ConnectionSummary]
    shared_profiles: list[WorkflowProfileDetail] = Field(default_factory=list)
