from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.projects import (
    CreateProjectRequest,
    ProjectsScreenState,
    ProjectSummary,
    UpdateProjectRequest,
)


class ProjectsService(Protocol):
    def list_projects(self) -> ProjectsScreenState: ...

    def get_project(self, project_id: str) -> ProjectSummary: ...

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary: ...

    def update_project(self, request: UpdateProjectRequest) -> ProjectSummary: ...

    def delete_project(self, project_id: str, *, permanent: bool = True) -> None: ...
