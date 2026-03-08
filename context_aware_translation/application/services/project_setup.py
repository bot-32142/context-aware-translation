from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest


class ProjectSetupService(Protocol):
    def get_state(self, project_id: str) -> ProjectSetupState: ...

    def save(self, request: SaveProjectSetupRequest) -> ProjectSetupState: ...
