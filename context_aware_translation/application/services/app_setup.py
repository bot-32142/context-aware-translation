from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionTestRequest,
    ConnectionTestResult,
    SaveConnectionRequest,
    SaveDefaultRoutesRequest,
    SetupWizardRequest,
    SetupWizardState,
)
from context_aware_translation.application.contracts.common import AcceptedCommand


class AppSetupService(Protocol):
    def get_state(self) -> AppSetupState: ...

    def get_wizard_state(self) -> SetupWizardState: ...

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState: ...

    def delete_connection(self, connection_id: str) -> AppSetupState: ...

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult: ...

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState: ...

    def save_default_routes(self, request: SaveDefaultRoutesRequest) -> AppSetupState: ...

    def seed_defaults(self) -> AcceptedCommand: ...
