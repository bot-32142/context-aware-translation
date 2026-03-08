from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    CapabilityAvailability,
    CapabilityCode,
    ContractModel,
    MetadataValue,
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
    REVIEW_ROUTING = "review_routing"
    COMPLETE = "complete"


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
    base_url: str | None = None
    default_model: str | None = None
    status: ConnectionStatus = ConnectionStatus.UNTESTED
    capabilities: list[CapabilityCode] = Field(default_factory=list)


class ConnectionDraft(ContractModel):
    display_name: str
    provider: ProviderKind
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    metadata: list[MetadataValue] = Field(default_factory=list)


class CapabilityCard(ContractModel):
    capability: CapabilityCode
    availability: CapabilityAvailability
    message: str | None = None
    connection_id: str | None = None
    connection_label: str | None = None


class DefaultRoute(ContractModel):
    capability: CapabilityCode
    connection_id: str
    connection_label: str


class RoutingRecommendation(ContractModel):
    routes: list[DefaultRoute]
    notes: list[str] = Field(default_factory=list)


class ConnectionTestRequest(ContractModel):
    connection: ConnectionDraft


class ConnectionTestResult(ContractModel):
    connection_label: str
    capabilities: list[CapabilityCard]
    recommendation: RoutingRecommendation | None = None
    message: UserMessage | None = None


class SaveConnectionRequest(ContractModel):
    connection: ConnectionDraft
    connection_id: str | None = None


class SaveDefaultRoutesRequest(ContractModel):
    routes: list[DefaultRoute]


class SetupWizardRequest(ContractModel):
    providers: list[ProviderKind]
    connections: list[ConnectionDraft]


class SetupWizardState(ContractModel):
    step: SetupWizardStep
    available_providers: list[ProviderCard] = Field(default_factory=list)
    selected_providers: list[ProviderKind] = Field(default_factory=list)
    drafts: list[ConnectionDraft] = Field(default_factory=list)
    test_results: list[ConnectionTestResult] = Field(default_factory=list)
    recommendation: RoutingRecommendation | None = None


class AppSetupState(ContractModel):
    connections: list[ConnectionSummary]
    capabilities: list[CapabilityCard]
    default_routes: list[DefaultRoute]
    requires_wizard: bool = False
    wizard: SetupWizardState | None = None
