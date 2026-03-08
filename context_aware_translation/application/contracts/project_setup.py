from __future__ import annotations

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    BindingSource,
    BlockerInfo,
    CapabilityAvailability,
    CapabilityCode,
    ContractModel,
    PresetCode,
    ProjectRef,
)


class ProjectCapabilityBinding(ContractModel):
    capability: CapabilityCode
    availability: CapabilityAvailability
    source: BindingSource
    connection_id: str | None = None
    connection_label: str | None = None
    blocker: BlockerInfo | None = None


class ProjectConnectionOption(ContractModel):
    connection_id: str
    connection_label: str


class ProjectCapabilityCard(ContractModel):
    capability: CapabilityCode
    availability: CapabilityAvailability
    source: BindingSource
    connection_id: str | None = None
    connection_label: str | None = None
    options: list[ProjectConnectionOption] = Field(default_factory=list)
    blocker: BlockerInfo | None = None


class ProjectSetupState(ContractModel):
    project: ProjectRef
    target_language: str | None = None
    preset: PresetCode | None = None
    bindings: list[ProjectCapabilityBinding] = Field(default_factory=list)
    capability_cards: list[ProjectCapabilityCard] = Field(default_factory=list)


class ProjectCapabilityOverride(ContractModel):
    capability: CapabilityCode
    connection_id: str | None = None


class SaveProjectSetupRequest(ContractModel):
    project_id: str
    target_language: str
    preset: PresetCode
    overrides: list[ProjectCapabilityOverride] = Field(default_factory=list)
