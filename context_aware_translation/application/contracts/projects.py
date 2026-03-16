from __future__ import annotations

from context_aware_translation.application.contracts.common import BlockerInfo, ContractModel, ProjectRef


class ProjectSummary(ContractModel):
    project: ProjectRef
    target_language: str | None = None
    progress_summary: str | None = None
    modified_at: float | None = None
    blocker: BlockerInfo | None = None


class ProjectsScreenState(ContractModel):
    items: list[ProjectSummary]
    requires_app_setup: bool = False
    blocker: BlockerInfo | None = None


class CreateProjectRequest(ContractModel):
    name: str
    target_language: str | None = None


class UpdateProjectRequest(ContractModel):
    project_id: str
    name: str | None = None
    target_language: str | None = None
