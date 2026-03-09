from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    CapabilityAvailability,
    CapabilityCode,
    ContractModel,
    PresetCode,
    ProviderKind,
    UserMessage,
)


class ConnectionStatus(StrEnum):
    UNTESTED = "untested"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class SetupWizardStep(StrEnum):
    CHOOSE_PROVIDERS = "choose_providers"
    ENTER_KEYS = "enter_keys"
    TEST_CAPABILITIES = "test_capabilities"
    REVIEW_PROFILE = "review_profile"
    COMPLETE = "complete"


class WorkflowProfileKind(StrEnum):
    SHARED = "shared"
    PROJECT_SPECIFIC = "project_specific"


class WorkflowStepId(StrEnum):
    EXTRACTOR = "extractor"
    SUMMARIZER = "summarizer"
    GLOSSARY_TRANSLATOR = "glossary_translator"
    TRANSLATOR = "translator"
    REVIEWER = "reviewer"
    OCR = "ocr"
    IMAGE_REEMBEDDING = "image_reembedding"
    MANGA_TRANSLATOR = "manga_translator"
    TRANSLATOR_BATCH = "translator_batch"


class ProviderCard(ContractModel):
    provider: ProviderKind
    label: str
    helper_text: str | None = None
    supports_custom_endpoint: bool = False
    recommended_for: list[CapabilityCode] = Field(default_factory=list)


class ConnectionSummary(ContractModel):
    connection_id: str
    display_name: str
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
    custom_parameters_json: str | None = None
    status: ConnectionStatus = ConnectionStatus.UNTESTED
    capabilities: list[CapabilityCode] = Field(default_factory=list)


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


class CapabilityCard(ContractModel):
    capability: CapabilityCode
    availability: CapabilityAvailability
    message: str | None = None
    connection_id: str | None = None
    connection_label: str | None = None


class WorkflowStepRoute(ContractModel):
    step_id: WorkflowStepId
    step_label: str
    connection_id: str | None = None
    connection_label: str | None = None
    model: str | None = None
    step_config: dict[str, bool | int | float | str | None] = Field(default_factory=dict)


class WorkflowProfileSummary(ContractModel):
    profile_id: str
    name: str
    kind: WorkflowProfileKind
    target_language: str | None = None
    preset: PresetCode | None = None
    is_default: bool = False


class WorkflowProfileDetail(ContractModel):
    profile_id: str
    name: str
    kind: WorkflowProfileKind
    target_language: str
    preset: PresetCode
    routes: list[WorkflowStepRoute] = Field(default_factory=list)
    is_default: bool = False


class ConnectionTestRequest(ContractModel):
    connection: ConnectionDraft


class ConnectionTestResult(ContractModel):
    connection_label: str
    capabilities: list[CapabilityCard]
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


class SetupWizardState(ContractModel):
    step: SetupWizardStep
    available_providers: list[ProviderCard] = Field(default_factory=list)
    selected_providers: list[ProviderKind] = Field(default_factory=list)
    drafts: list[ConnectionDraft] = Field(default_factory=list)
    test_results: list[ConnectionTestResult] = Field(default_factory=list)
    recommendation: WorkflowProfileDetail | None = None


class AppSetupState(ContractModel):
    connections: list[ConnectionSummary]
    capabilities: list[CapabilityCard]
    shared_profiles: list[WorkflowProfileDetail] = Field(default_factory=list)
    default_profile_id: str | None = None
    selected_profile: WorkflowProfileDetail | None = None
    requires_wizard: bool = False
    wizard: SetupWizardState | None = None
