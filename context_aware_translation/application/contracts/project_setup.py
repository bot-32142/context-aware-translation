from __future__ import annotations

from context_aware_translation.application.contracts.app_setup import ConnectionSummary, WorkflowProfileDetail
from context_aware_translation.application.contracts.common import BlockerInfo, ContractModel, ProjectRef


class ProjectSetupState(ContractModel):
    project: ProjectRef
    available_connections: list[ConnectionSummary]
    shared_profiles: list[WorkflowProfileDetail]
    selected_shared_profile_id: str | None = None
    project_profile: WorkflowProfileDetail | None = None
    blocker: BlockerInfo | None = None


class SaveProjectSetupRequest(ContractModel):
    project_id: str
    shared_profile_id: str | None = None
    project_profile: WorkflowProfileDetail | None = None
